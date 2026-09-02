"""Phase 1 gate — persona registry lifecycle (installed → enabled → surfaced + default),
plus the shipping lineup (owner calls 2026-08-21): Chat removed, Code disabled by default,
ships:false personas hidden outside internal builds (OPENWORKER_UNSHIPPED=1)."""

from __future__ import annotations

import pytest

from coworker.personas.registry import DEFAULT_PERSONA_ID, PersonaRegistry


def _reg(tmp_path) -> PersonaRegistry:
    return PersonaRegistry(state_path=tmp_path / "personas.json")


@pytest.fixture
def internal(monkeypatch):
    """Internal build: ships:false personas (teams, ops, design…) are visible."""
    monkeypatch.setenv("OPENWORKER_UNSHIPPED", "1")


def test_builtins_present(tmp_path):
    reg = _reg(tmp_path)
    assert {"code", "cowork", "ops"} <= set(reg.ids())
    assert "chat" not in reg.ids()  # removed entirely, not just disabled
    assert reg.get("ops").builtin is True
    # Ops came from a markdown manifest; Code from a builder.
    assert reg.get("ops").manifest is not None
    assert reg.get("code").manifest is None


# The shipped industry roster (owner 2026-08-31): the customer makes high-end downhole
# oil equipment, so the examples are production/operations and R&D roles. Software and
# cloud security went ships:false in the same call.
_OPERATIONS = {
    "production-planning", "quality-system", "supply-chain", "equipment-maintenance",
    "process-tooling",
}
_RESEARCH = {"product-design", "test-validation", "failure-analysis", "rd-project-ip"}


def test_release_lineup(tmp_path, monkeypatch):
    # A release build (no flag) offers exactly OpenWorker in the picker. Every other
    # shipped coworker is an EXAMPLE: listed in Settings with its toggle off, one
    # checkbox from the picker. A lineup that opens pre-stocked with roles this
    # customer doesn't do reads as the product's opinion of their work.
    monkeypatch.delenv("OPENWORKER_UNSHIPPED", raising=False)
    reg = _reg(tmp_path)
    assert [e["name"] for e in reg.sidebar()] == ["cowork"]
    listed = {p["id"]: p for p in reg.list_all()}
    assert set(listed) == {"cowork", "code", "expert-lead"} | _OPERATIONS | _RESEARCH
    for pid, entry in listed.items():
        assert entry["enabled"] is (pid == "cowork"), pid
    # Code alone is also UNsurfaced (the recovery path); the industry coworkers surface,
    # so enabling one is the only step between Settings and the picker.
    assert listed["code"]["surfaced"] is False
    assert listed["expert-lead"]["surfaced"] is True
    assert listed["cowork"]["group"] == "general"
    assert {listed[i]["group"] for i in _OPERATIONS} == {"operations"}
    assert {listed[i]["group"] for i in _RESEARCH} == {"research"}
    # Software/cloud security is not part of a downhole-equipment release.
    assert not {"security", "cloud-posture", "dep-audit"} & set(listed)
    # Enabling Code from Settings puts it in the picker (enable implies surface).
    reg.set_enabled("code", True)
    assert "code" in [e["name"] for e in reg.sidebar()]


def test_industry_personas_are_knowledge_work_not_repo_work(tmp_path, monkeypatch):
    """The industry coworkers are business/engineering roles: they work on documents
    and data in the session scratch, never on a checked-out repo. A stray `code_files`
    or `requires_folder` would put a folder gate in front of a production planner."""
    monkeypatch.delenv("OPENWORKER_UNSHIPPED", raising=False)
    reg = _reg(tmp_path)
    for pid in sorted(_OPERATIONS | _RESEARCH):
        entry = reg.get(pid)
        assert entry.tools == ["files", "search", "shell", "todo"], pid
        assert entry.requires_folder is False, pid
        assert entry.manifest is not None and entry.manifest.team is None, pid
        # Named in the customer's language — these ship to a Chinese factory floor.
        assert any("一" <= c <= "鿿" for c in entry.name), pid


def test_unshipped_hidden_unless_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENWORKER_UNSHIPPED", raising=False)
    reg = _reg(tmp_path)
    assert "swe-lead" not in {p["id"] for p in reg.list_all()}
    # Still resolvable (a session born on it keeps working)…
    assert reg.agent("swe-lead").name == "swe-lead"
    # …and an explicit user enable (made on an internal build) keeps it visible.
    reg.set_enabled("swe-lead", True)
    assert "swe-lead" in {p["id"] for p in reg.list_all()}


def test_sidebar_defaults_to_surfaced_builtins(tmp_path, internal):
    reg = _reg(tmp_path)
    sidebar = reg.sidebar()
    # Only OpenWorker ships enabled (owner 2026-08-31) — everything else is an example
    # waiting behind its Settings toggle, on internal builds too.
    assert [e["name"] for e in sidebar] == ["cowork"]
    assert sidebar[0]["default"] is True

    # SURFACING is a separate axis and unchanged: leads surface (the user's entry to a
    # team — "the team IS the lead"), team workers never do.
    listed = {p["id"]: p for p in reg.list_all()}
    for lead in ("expert-lead", "swe-lead", "devsecops-lead", "devops-lead"):
        assert listed[lead]["surfaced"] is True, lead
    for worker in (
        "swe-worker", "design-worker", "test-worker",
        "appsec-worker", "secrets-worker", "posture-worker",
        "logs-worker", "infra-worker", "change-worker",
    ):
        assert listed[worker]["surfaced"] is False, worker
        # …and they stay ENABLED regardless: a worker is never OFFERED to the user, so
        # shipping it off would only break its lead's staffing gate.
        assert listed[worker]["enabled"] is True, worker

    # Enabling from Settings puts a coworker in the picker (enable implies surface),
    # and an explicit disable takes it back out.
    reg.set_enabled("security", True)
    assert "security" in [e["name"] for e in reg.sidebar()]
    reg.set_enabled("security", False)
    assert "security" not in [e["name"] for e in reg.sidebar()]


def test_code_ships_disabled_but_recoverable(tmp_path):
    reg = _reg(tmp_path)
    # Code ships disabled + unsurfaced (owner call 2026-08-21): OpenWorker leads the
    # launch, Code stays one checkbox away as the plain work-in-my-repo persona.
    assert reg.is_enabled("code") is False
    assert reg.is_surfaced("code") is False
    assert reg.agent("code").name == "code"  # live sessions keep resolving
    reg.set_enabled("code", True)
    assert "code" in [e["name"] for e in reg.sidebar()]


def test_chat_gone_resolves_to_default(tmp_path):
    reg = _reg(tmp_path)
    # Chat is removed outright; a stray persona=chat session id falls back to the
    # default persona instead of erroring.
    assert reg.get("chat") is None
    assert reg.agent("chat").name == reg.default_id()


def test_surface_toggle_filters_picker_but_keeps_resolvable(tmp_path, internal):
    reg = _reg(tmp_path)
    reg.set_surfaced("ops", False)
    assert "ops" not in [e["name"] for e in reg.sidebar()]
    # Still installed + still resolvable (a session already on Ops keeps working).
    assert "ops" in reg.ids()
    assert reg.agent("ops").name == "ops"
    assert any(p["id"] == "ops" and not p["surfaced"] for p in reg.list_all())


def test_disable_default_falls_back(tmp_path):
    reg = _reg(tmp_path)
    assert reg.default_id() == DEFAULT_PERSONA_ID  # cowork
    reg.set_enabled("ops", True)  # another persona must be enabled to fall back to
    reg.set_enabled("cowork", False)
    # Cowork off → default resolves to another enabled persona, not cowork.
    assert reg.default_id() != "cowork"
    # Unknown / unspecified persona falls back to the (new) default, which is enabled.
    fallback = reg.agent(None)
    assert reg.is_enabled(fallback.name)


def test_set_default_enables_and_persists(tmp_path):
    reg = _reg(tmp_path)
    reg.set_default("ops")
    assert reg.default_id() == "ops" and reg.is_enabled("ops")
    # New instance reads persisted state.
    reg2 = _reg(tmp_path)
    assert reg2.default_id() == "ops"


def test_agent_resolution(tmp_path):
    reg = _reg(tmp_path)
    assert reg.agent("ops").requires_folder is False
    assert reg.agent("code").requires_folder is True
    # Unknown id → default persona.
    assert reg.agent("does-not-exist").name == reg.default_id()


def test_list_all_carries_requires_folder(tmp_path, internal):
    # The workspace enum collapsed into the requires_folder trait
    # (workspace-scratch-design.md): Code gates a folder; scratch personas don't.
    reg = _reg(tmp_path)
    gated = {p["id"]: p["requires_folder"] for p in reg.list_all()}
    assert gated["code"] is True
    assert gated["cowork"] is False
    assert gated["ops"] is False


def test_set_unknown_persona_raises(tmp_path):
    reg = _reg(tmp_path)
    with pytest.raises(KeyError):
        reg.set_enabled("ghost", False)


def _mini_manifest(pid: str, name: str) -> str:
    return "\n".join(
        ["---", f"id: {pid}", f"name: {name}", "tools: [files]", "---", "", "Prompt.", ""]
    )


def test_a_bad_installed_manifest_is_skipped_not_fatal(tmp_path, caplog):
    """The managed personas-installed dir is walked while the registry is being
    CONSTRUCTED — i.e. during server startup (server/manager.py builds one). The dir
    is app-written and therefore always UTF-8, but nothing stops a user hand-dropping
    a file into it: a manifest saved in a legacy codepage (GBK on zh-CN Windows) used
    to raise UnicodeDecodeError straight out of __init__ and take the whole server
    down with it. One bad file must cost exactly one persona.
    """
    installed = tmp_path / "personas-installed"
    # (a) legacy codepage — the bytes are not valid UTF-8, so a strict decode raised.
    gbk = installed / "gbk-drop"
    gbk.mkdir(parents=True)
    (gbk / "manifest.md").write_bytes(_mini_manifest("gbkdrop", "坏了").encode("gbk"))
    # (b) not a manifest at all — the same walk, a different way to fail.
    junk = installed / "junk"
    junk.mkdir()
    (junk / "manifest.md").write_text("no frontmatter here", encoding="utf-8")
    # (c) the healthy neighbour that must survive both.
    good = installed / "fine"
    good.mkdir()
    (good / "manifest.md").write_text(_mini_manifest("fine", "Fine"), encoding="utf-8")

    with caplog.at_level("WARNING", logger="coworker.personas.registry"):
        reg = PersonaRegistry(state_path=tmp_path / "personas.json")

    assert "fine" in reg.ids()  # the healthy sibling installed
    assert DEFAULT_PERSONA_ID in reg.ids()  # and the built-ins are all there
    assert "junk" not in reg.ids() and "no frontmatter" not in str(reg.ids())
    # Skips are logged, never swallowed.
    assert any("manifest" in r.getMessage() for r in caplog.records)
    # The GBK drop is decoded with errors="replace", so it lands as mojibake rather
    # than exploding — either outcome is fine, a raised UnicodeDecodeError is not.
    assert "gbkdrop" in reg.ids() or any(
        "gbk-drop" in r.getMessage() for r in caplog.records
    )


def test_a_broken_builtin_manifest_still_raises(tmp_path):
    """The skip is for user-supplied dirs only. A built-in that will not parse is a
    packaging bug, and shipping with that persona silently missing is worse than
    failing the build — so built-ins stay loud.
    """
    from coworker.personas.manifest import ManifestError

    builtin = tmp_path / "builtin"
    builtin.mkdir()
    (builtin / "nope.md").write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(ManifestError):
        PersonaRegistry(builtin_dir=builtin, state_path=tmp_path / "personas.json")


def test_concurrent_install_and_reads_never_break_iteration(tmp_path, monkeypatch):
    """/v1/agents and /v1/personas run as sync routes in FastAPI's threadpool, so
    sidebar()/list_all() iterate the entry dict while an install route (or the expert
    library's install_from_dir in coworker/library/api.py) inserts new keys into it —
    unguarded, CPython kills the iteration with RuntimeError ("dictionary changed size
    during iteration"). Same Barrier pattern as
    test_library_api.test_concurrent_first_load_returns_data_to_every_thread."""
    import threading
    import time

    reg = _reg(tmp_path)

    # Widen each iteration step the way a busy threadpool does, so an unlocked
    # registry would reliably interleave an insert into a running read loop.
    real_is_surfaced = PersonaRegistry.is_surfaced

    def slow_is_surfaced(self, persona_id):
        time.sleep(0.001)
        return real_is_surfaced(self, persona_id)

    monkeypatch.setattr(PersonaRegistry, "is_surfaced", slow_is_surfaced)

    errors: list[Exception] = []
    barrier = threading.Barrier(5)

    def read_loop():
        barrier.wait()
        try:
            for _ in range(15):
                reg.sidebar()
                reg.list_all()
        except Exception as e:
            errors.append(e)

    def install_loop(worker: int):
        barrier.wait()
        try:
            for r in range(4):
                pid = f"race-{worker}-{r}"
                d = tmp_path / f"incoming-{pid}"
                d.mkdir()
                (d / f"{pid}.md").write_text(
                    f"---\nid: {pid}\nname: {pid}\n---\nprompt for {pid}\n",
                    encoding="utf-8",
                )
                reg.install_from_dir(d)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=read_loop) for _ in range(3)] + [
        threading.Thread(target=install_loop, args=(w,)) for w in (0, 1)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert {f"race-{w}-{r}" for w in (0, 1) for r in range(4)} <= set(reg.ids())
