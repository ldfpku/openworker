"""What an engine build is allowed to cost (audit 2026-09-13).

The draft re-target path rebuilds the engine on every coworker and folder pick, so a build
is not a once-per-session event. Measured before this suite existed: SIX `git` subprocesses
per build (~180 ms of ~220 ms on Windows) plus a full re-parse of all 163 SKILL.md files,
because each build constructed a fresh SkillLoader whose mtime fingerprint can never
short-circuit on its first scan.

These are budget tests: they pin the number of spawns and parses, not the wording of
anything. If a future change needs a third git command at build time, the honest move is to
raise the number here deliberately — not to let it drift.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from coworker import environment, gitprobe, session_facts
from coworker.projects import project_key, resolve_memory_key
from coworker.providers import ModelCapabilities
from coworker.skills import base as skills_base


@pytest.fixture(autouse=True)
def _cold_caches():
    """Every test here starts cold, and leaves nothing behind for the next one."""
    gitprobe.clear_all()
    skills_base.reset_shared_loaders()
    yield
    gitprobe.clear_all()
    skills_base.reset_shared_loaders()


class _Stub:
    def complete(self, **kwargs):  # pragma: no cover — never driven here
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()


def _git(ws, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(ws), *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def repo(tmp_path):
    ws = tmp_path / "repo"
    ws.mkdir()
    _git(ws, "init", "-q", "-b", "main")
    (ws / "f.txt").write_text("1", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "first commit")
    return ws


class _GitCounter:
    """Counts `git` spawns while leaving every other subprocess alone."""

    def __init__(self, monkeypatch):
        self.commands: list[list[str]] = []
        real = subprocess.run

        def counting(args, *a, **kw):
            if isinstance(args, (list, tuple)) and args and str(args[0]) == "git":
                self.commands.append([str(x) for x in args])
            return real(args, *a, **kw)

        monkeypatch.setattr(subprocess, "run", counting)

    @property
    def count(self) -> int:
        return len(self.commands)


# -- git spawns ------------------------------------------------------------------


def test_cold_build_spawns_at_most_two_git_processes(repo, monkeypatch):
    """The whole build budget: one `status --porcelain=v1 -b` and one `log -n5`.

    Of the six this used to be, three are gone for good rather than memoised —
    `rev-parse --is-inside-work-tree` and `rev-parse --abbrev-ref HEAD` fold into the
    status call, and `remote -v` is a flat read of `.git/config`. The sixth,
    `rev-parse --git-common-dir`, belongs to `resolve_memory_key` (the manager's call, not
    the build) and is asserted separately below.
    """
    from coworker.agent import build_engine

    counter = _GitCounter(monkeypatch)
    engine = build_engine(agent=_code(), workspace=repo, provider=_Stub())
    try:
        assert counter.count <= 2, counter.commands
        assert any("status" in c for c in counter.commands)
        assert not any("remote" in c for c in counter.commands)
        # The known world was still captured — cheaper, not skipped.
        assert engine.session_facts.world.captured_at > 0
    finally:
        engine.executor.close()


def test_whole_cold_session_start_spawns_at_most_three(repo, monkeypatch):
    """Build plus the manager's own probe (`resolve_memory_key` → `--git-common-dir`).
    That one stays a real git call on purpose: it decides the memory/board identity key,
    and a wrong answer silently re-keys the user's memories — not a place to hand-roll
    git's worktree and submodule resolution."""
    from coworker.agent import build_engine

    counter = _GitCounter(monkeypatch)
    engine = build_engine(agent=_code(), workspace=repo, provider=_Stub())
    try:
        resolve_memory_key(str(repo))
        session_facts.capture(roots=[], workspace=repo)
        assert counter.count <= 3, counter.commands
    finally:
        engine.executor.close()


def test_second_build_inside_the_ttl_spawns_no_git_at_all(repo, monkeypatch):
    from coworker.agent import build_engine

    first = build_engine(agent=_code(), workspace=repo, provider=_Stub())
    first.executor.close()
    resolve_memory_key(str(repo))
    session_facts.capture(roots=[], workspace=repo)

    counter = _GitCounter(monkeypatch)
    second = build_engine(agent=_code(), workspace=repo, provider=_Stub())
    try:
        resolve_memory_key(str(repo))
        session_facts.capture(roots=[], workspace=repo)
        assert counter.count == 0, counter.commands
    finally:
        second.executor.close()


def test_memo_expires_so_a_stale_tree_cannot_be_reported_forever(repo, monkeypatch):
    """The memo is a burst absorber, not a cache of record: past the TTL the next reader
    goes back to git, which is what keeps a working tree the user is editing honest."""
    # Per-cache `_ttl`, not the module constant: `TTLCache.__init__` binds TTL_SECONDS as
    # a default at import time, so patching it expires nothing — not even a cache built
    # afterwards.
    monkeypatch.setattr(environment._CONTEXT_CACHE, "_ttl", 0.0)
    environment.environment_context(repo)
    counter = _GitCounter(monkeypatch)
    environment.environment_context(repo)
    assert counter.count >= 1


def test_environment_block_is_byte_identical_across_builds(repo):
    """Provider prompt caching (see environment.py's docstring) is only worth anything if
    two sessions on one workspace produce the same system-prompt bytes."""
    first = environment.environment_context(repo)
    gitprobe.clear_all()  # even with nothing memoised, the bytes must match
    assert environment.environment_context(repo) == first


# -- the collapsed status command ------------------------------------------------


def test_status_reports_branch_dirtiness_and_commits_from_one_spawn(repo, monkeypatch):
    (repo / "f.txt").write_text("2", encoding="utf-8")
    (repo / "new.txt").write_text("x", encoding="utf-8")
    counter = _GitCounter(monkeypatch)
    block = environment.environment_context(repo)
    assert "Git branch: main" in block
    assert "Git status (2 changed):" in block
    assert "first commit" in block
    assert counter.count == 2, counter.commands  # status + log, nothing else


def test_detached_head_and_fresh_repo_branch_headers(tmp_path):
    assert environment._branch_from_header("## main") == "main"
    assert environment._branch_from_header("## main...origin/main [ahead 1]") == "main"
    assert environment._branch_from_header("## HEAD (no branch)") == "HEAD (detached)"
    # A repo with no commits: the old `rev-parse --abbrev-ref HEAD` failed outright here
    # and the block said "(unknown)".
    assert environment._branch_from_header("## No commits yet on main") == "main"


def test_fresh_repo_reports_its_branch_not_unknown(tmp_path):
    ws = tmp_path / "empty"
    ws.mkdir()
    _git(ws, "init", "-q", "-b", "main")
    assert "Git branch: main" in environment.environment_context(ws)


def test_detached_head_is_named_as_such(repo):
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git(repo, "checkout", "-q", head)
    assert "Git branch: HEAD (detached)" in environment.environment_context(repo)


def test_non_repo_still_says_so(tmp_path):
    assert "not a git repository" in environment.environment_context(tmp_path)


def test_broken_git_is_not_reported_as_not_a_repo(tmp_path, monkeypatch):
    """A stale index.lock or a corrupt repo is not the same fact as "this isn't a repo",
    and the agent acts differently on the two."""
    monkeypatch.setattr(
        environment, "_run", lambda ws, *a: (128, "", "fatal: index file smaller than expected")
    )
    assert environment._git_snapshot(tmp_path) == ["Git: state unavailable"]


def test_a_corrupt_repo_is_not_mistaken_for_a_missing_folder(tmp_path, monkeypatch):
    """Both failures say "No such file or directory"; only one of them is about the folder.
    Matching the bare phrase swallowed a corrupt repo into "not a git repository" — the
    inversion the branch above exists to prevent (audit 2026-09-13)."""
    monkeypatch.setattr(
        environment,
        "_run",
        lambda ws, *a: (128, "", "fatal: could not open '.git/index': No such file or directory"),
    )
    assert environment._git_snapshot(tmp_path) == ["Git: state unavailable"]
    monkeypatch.setattr(
        environment,
        "_run",
        lambda ws, *a: (128, "", "fatal: cannot change to 'gone': No such file or directory"),
    )
    assert environment._git_snapshot(tmp_path) == ["Git: not a git repository"]


def test_the_git_probe_pins_the_message_locale(tmp_path, monkeypatch):
    """The classification above reads git's ENGLISH stderr. gettext translates those fatals
    wherever catalogs are installed, so an ordinary non-repo folder on a localized git would
    read as a tooling failure — the outcome the comment there calls the wrong path."""
    seen: dict[str, object] = {}

    def spy(*args, **kwargs):
        seen.update(kwargs.get("env") or {})

        class _R:
            returncode, stdout, stderr = 0, "## main\n", ""

        return _R()

    monkeypatch.setattr(environment.subprocess, "run", spy)
    environment._run(tmp_path, "status")
    assert seen["LC_ALL"] == "C" and seen["LANGUAGE"] == ""
    assert "PATH" in seen  # the real environment is carried, not replaced


# -- skills ----------------------------------------------------------------------


def _skill(base, name, body="do it"):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\n\n{body}\n", encoding="utf-8"
    )


def test_skill_md_is_not_reparsed_on_every_build(tmp_path, monkeypatch):
    from coworker.agent import build_engine

    lib = tmp_path / "lib"
    for i in range(5):
        _skill(lib, f"s{i}")

    parses: list[str] = []
    real_parse = skills_base._parse_skill
    monkeypatch.setattr(
        skills_base,
        "_parse_skill",
        lambda md: (parses.append(str(md)), real_parse(md))[1],
    )

    engines = []
    try:
        for _ in range(3):
            engines.append(
                build_engine(
                    agent=_code(),
                    workspace=tmp_path / "ws",
                    provider=_Stub(),
                    extra_skill_dirs=[lib],
                )
            )
        assert len(parses) == 5, parses  # parsed once, for the first build only
        assert engines[-1].skill_loader.get("s3") is not None
    finally:
        for e in engines:
            e.executor.close()


def test_a_skill_written_between_builds_is_still_picked_up(tmp_path):
    from coworker.agent import build_engine

    lib = tmp_path / "lib"
    _skill(lib, "early")
    first = build_engine(
        agent=_code(), workspace=tmp_path / "ws", provider=_Stub(), extra_skill_dirs=[lib]
    )
    first.executor.close()
    _skill(lib, "late")
    second = build_engine(
        agent=_code(), workspace=tmp_path / "ws", provider=_Stub(), extra_skill_dirs=[lib]
    )
    try:
        assert second.skill_loader.get("late") is not None
    finally:
        second.executor.close()


def test_same_second_edit_is_not_mistaken_for_no_change(tmp_path):
    """The fingerprint carries size as well as mtime: a loader now outlives the build that
    made it, so an edit landing inside one filesystem tick must not read as unchanged."""
    lib = tmp_path / "lib"
    _skill(lib, "one", body="short")
    loader = skills_base.shared_loader([lib])
    stamp = (lib / "one" / "SKILL.md").stat().st_mtime
    _skill(lib, "one", body="a noticeably longer body than before")
    import os

    os.utime(lib / "one" / "SKILL.md", (stamp, stamp))  # pretend the tick did not advance
    loader.rescan()
    assert "longer body" in loader.get("one").instructions


def test_shared_loader_is_the_same_object_for_the_same_dirs(tmp_path):
    lib = tmp_path / "lib"
    _skill(lib, "one")
    assert skills_base.shared_loader([lib]) is skills_base.shared_loader([lib])
    assert skills_base.shared_loader([lib]) is not skills_base.shared_loader(
        [tmp_path / "other"]
    )


# -- thread safety ---------------------------------------------------------------


def test_concurrent_builds_do_not_corrupt_the_catalogue(tmp_path):
    """Wave 2 moves the build onto a worker thread; nothing here may be single-threaded."""
    import threading

    lib = tmp_path / "lib"
    for i in range(20):
        _skill(lib, f"s{i}")

    seen: list[int] = []
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(10):
                loader = skills_base.shared_loader([lib])
                loader.rescan()
                seen.append(len(loader.names()))
        except BaseException as exc:  # noqa: BLE001 — the assertion is "none escaped"
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert set(seen) == {20}  # never a half-built catalogue


def test_ttl_cache_is_thread_safe(tmp_path):
    import threading

    cache = gitprobe.TTLCache()
    calls: list[int] = []
    out: list[str] = []

    def worker():
        for _ in range(20):
            out.append(cache.get("k", lambda: (calls.append(1), "v")[1]))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(out) == {"v"}
    assert len(calls) <= 6  # at most one cold compute per racing thread, never 120


def _code():
    from coworker.agents import code_agent

    return code_agent()


def test_ttl_cache_evicts_rather_than_growing_without_bound():
    cache = gitprobe.TTLCache()
    for i in range(gitprobe._MAX_ENTRIES * 2):
        cache.get(f"k{i}", lambda: i)
    assert len(cache._entries) <= gitprobe._MAX_ENTRIES


def test_project_key_memo_survives_repeated_resolution(repo, monkeypatch):
    project_key(repo)  # cold
    counter = _GitCounter(monkeypatch)
    for _ in range(5):
        assert project_key(repo) == str(repo.resolve())
    assert counter.count == 0, counter.commands


def test_known_world_memo_does_not_make_a_new_remote_look_familiar(repo):
    """Staleness here must err safe: a remote the agent adds is absent from the next
    snapshot, never wrongly present."""
    before = session_facts.capture(roots=[], workspace=repo)
    _git(repo, "remote", "add", "backup", "https://attacker.net/r.git")
    after = session_facts.capture(roots=[], workspace=repo)
    assert before.remotes == after.remotes == ()
    assert "attacker.net" not in after.hosts


def test_remotes_are_read_from_config_not_a_subprocess(repo, monkeypatch):
    _git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
    _git(repo, "remote", "add", "fork", "git@github.com:me/repo.git")
    counter = _GitCounter(monkeypatch)
    world = session_facts.capture(roots=[], workspace=repo)
    assert world.remotes == (
        ("fork", "git@github.com:me/repo.git"),
        ("origin", "https://github.com/org/repo.git"),
    )
    assert counter.count == 0, counter.commands


def test_remotes_fall_back_to_git_for_a_worktree(repo, tmp_path, monkeypatch):
    """A worktree's `.git` is a FILE pointing elsewhere; the flat read must not guess."""
    _git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt))
    gitprobe.clear_all()
    assert session_facts._remotes_from_config(wt) is None
    counter = _GitCounter(monkeypatch)
    world = session_facts.capture(roots=[], workspace=wt)
    assert world.remotes == (("origin", "https://github.com/org/repo.git"),)
    assert counter.count == 1, counter.commands  # git answered, exactly once


def test_config_includes_fall_back_to_git(repo):
    config = repo / ".git" / "config"
    config.write_text(
        config.read_text(encoding="utf-8") + '\n[include]\n\tpath = ../extra\n',
        encoding="utf-8",
    )
    assert session_facts._remotes_from_config(repo) is None


@pytest.mark.parametrize(
    "extra",
    [
        '\n[REMOTE "backup"]\n\turl = https://example.invalid/b.git\n',  # git names are case-insensitive
        '\n[remote "b"] url = https://example.invalid/b.git\n',  # key on the header line
        '\n[remote "quoted"]\n\turl = "https://example.invalid/q.git"\n',  # git strips the quotes
        "\n[remote \"winpath\"]\n\turl = C:\\\\repos\\\\proj\n",  # backslash escapes
    ],
)
def test_a_remote_shape_this_parser_misses_hands_the_whole_answer_to_git(repo, extra):
    """The bail-out is PER SECTION and per value. A partial answer returned as
    authoritative is the dangerous outcome: the frozen known world would omit a remote the
    user really works with, so a push there reads as a destination they have never used."""
    _git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
    config = repo / ".git" / "config"
    config.write_text(config.read_text(encoding="utf-8") + extra, encoding="utf-8")
    assert session_facts._remotes_from_config(repo) is None


def test_a_local_path_remote_matches_what_git_prints(repo, tmp_path):
    """Differential: whatever the flat parser claims must equal git's own answer — git
    writes backslash escapes itself for a Windows path remote."""
    other = tmp_path / "local repo"
    other.mkdir()
    _git(other, "init", "-q")
    _git(repo, "remote", "add", "local", str(other))
    gitprobe.clear_all()
    flat = session_facts._remotes_from_config(repo)
    assert flat is None or flat == session_facts._git_remotes_uncached(repo)


def test_remotes_memo_expires_so_a_new_remote_eventually_shows(repo, monkeypatch):
    """The other half of the memo invariant (the safe-direction one is above): a burst
    absorber, not a cache of record — a genuinely new remote must become visible."""
    assert session_facts.capture(roots=[], workspace=repo).remotes == ()
    _git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
    assert session_facts.capture(roots=[], workspace=repo).remotes == ()  # memo holds
    monkeypatch.setattr(session_facts._REMOTES_CACHE, "_ttl", 0.0)
    assert session_facts.capture(roots=[], workspace=repo).remotes == (
        ("origin", "https://github.com/org/repo.git"),
    )


def test_a_plain_folder_needs_no_git_to_report_no_remotes(tmp_path, monkeypatch):
    counter = _GitCounter(monkeypatch)
    world = session_facts.capture(roots=[], workspace=tmp_path)
    assert world.remotes == ()
    assert counter.count == 0, counter.commands


def test_build_timing_is_reported(repo, capsys):
    """Not a threshold (CI machines vary) — a printed before/after so a regression in the
    build budget is visible to whoever runs this file with -s."""
    from coworker.agent import build_engine

    engines = []
    try:
        t0 = time.perf_counter()
        engines.append(build_engine(agent=_code(), workspace=repo, provider=_Stub()))
        cold = time.perf_counter() - t0
        t1 = time.perf_counter()
        engines.append(build_engine(agent=_code(), workspace=repo, provider=_Stub()))
        warm = time.perf_counter() - t1
        print(f"\nengine build: cold {cold * 1000:.0f} ms, warm {warm * 1000:.0f} ms")
        assert warm >= 0
    finally:
        for e in engines:
            e.executor.close()
