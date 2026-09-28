"""`write_spreadsheet` as the rest of the app sees it — the wiring, not the .xlsx.

`tests/test_office_tools.py` covers what the tool writes. This file covers everything that
has to KNOW about it: the two name registries that make it a write tool, the permission
verdicts that follow from them, provenance and the Artifacts panel, the loader that keeps
its 2.3k-char schema out of every prompt, and the packaging pins.

Most of it exists because the failure modes are silent. A missing `_PATH_ARG` entry does
not error — it just makes every write ask a human, in every mode. A missing `WRITE_TOOLS`
entry does not error either — the tool still runs, but unscoped, uncredited and invisible
in the panel. So each group below states what its absence would look like on the user's
screen, because that is the thing a merge from upstream can quietly restore.
"""

from __future__ import annotations

import json
import time

from coworker.permissions import Mode, PermissionEngine
from coworker.permissions import _PATH_ARG as PATH_ARG
from coworker.risk import WRITE_TOOLS, RiskClass, classify
from coworker.tools.office import office_tools


def _meta():
    """The tool's own metadata, as the registry hands it to the permission engine."""
    return office_tools("/tmp/cw-office")[0].__aisuite_tool_metadata__


def _sheets():
    return [{"name": "汇总", "rows": [["项目", "金额"], ["项目甲", "1200"]]}]


# -- the two name registries ------------------------------------------------------------


def test_write_spreadsheet_is_a_declared_write_tool_in_fork():
    """`risk.WRITE_TOOLS` is what makes this a write rather than a generic external call.
    Dropped, `classify` falls back to the metadata (`requires_approval=True` → EXTERNAL):
    still approval-gated, but path scoping, the read-only-mode denial, provenance and the
    Artifacts panel all key off WRITE_LOCAL — so an approved call could write to any
    absolute path on the machine and never appear in the panel."""
    assert "write_spreadsheet" in WRITE_TOOLS
    assert classify("write_spreadsheet", _meta()) is RiskClass.WRITE_LOCAL


def test_write_spreadsheet_path_argument_is_registered_in_fork():
    """`permissions._PATH_ARG` maps a write tool to the argument naming its target. Without
    the entry `write_paths` reports `located=False` and `evaluate` fails closed with
    "cannot determine the write path to scope" + `human_only=True` — i.e. every
    spreadsheet, in every mode including bypass-approvals, stops for a human click. The
    contrast test below runs exactly that removal."""
    assert PATH_ARG["write_spreadsheet"] == "path"


# -- what those two registries buy: the permission verdicts ------------------------------


def _engine(tmp_path, mode, **kw):
    return PermissionEngine(workspace_root=tmp_path, mode=mode, **kw)


def test_bypass_approvals_writes_a_spreadsheet_without_asking(tmp_path):
    decision = _engine(tmp_path, Mode.BYPASS_APPROVALS).evaluate(
        "write_spreadsheet", {"path": "报告.xlsx", "sheets": _sheets()}, _meta()
    )
    assert decision.allowed, decision.reason


def test_without_the_path_arg_entry_even_bypass_approvals_stops_to_ask(
    tmp_path, monkeypatch
):
    """The contrast for the pin above: the ONLY difference is the `_PATH_ARG` entry."""
    import coworker.permissions as permissions

    monkeypatch.delitem(permissions._PATH_ARG, "write_spreadsheet")
    decision = _engine(tmp_path, Mode.BYPASS_APPROVALS).evaluate(
        "write_spreadsheet", {"path": "报告.xlsx", "sheets": _sheets()}, _meta()
    )
    assert not decision.allowed
    assert decision.needs_user and decision.human_only
    assert "scope" in decision.reason


def test_interactive_mode_asks_before_writing_a_spreadsheet(tmp_path):
    decision = _engine(tmp_path, Mode.INTERACTIVE).evaluate(
        "write_spreadsheet", {"path": "报告.xlsx", "sheets": _sheets()}, _meta()
    )
    assert not decision.allowed and decision.needs_user


def test_read_only_modes_refuse_a_spreadsheet_outright(tmp_path):
    for mode in (Mode.PLAN, Mode.DISCUSS):
        decision = _engine(tmp_path, mode).evaluate(
            "write_spreadsheet", {"path": "报告.xlsx", "sheets": _sheets()}, _meta()
        )
        assert not decision.allowed, mode
        # A read-only mode never asks — there is nothing a click could unlock.
        assert not decision.needs_user, mode
        assert "read-only" in decision.reason


def test_a_spreadsheet_outside_the_writable_roots_is_refused(tmp_path):
    """Same scoping write_file gets: a read-only root and a path outside every root are
    both refused, in the mode that asks the FEWEST questions."""
    ro, rw, outside = tmp_path / "ro", tmp_path / "rw", tmp_path / "elsewhere"
    for d in (ro, rw, outside):
        d.mkdir()
    engine = _engine(
        tmp_path,
        Mode.BYPASS_APPROVALS,
        roots=[{"path": str(rw), "writable": True}, {"path": str(ro), "writable": False}],
    )

    assert engine.evaluate(
        "write_spreadsheet", {"path": str(rw / "报告.xlsx"), "sheets": _sheets()}, _meta()
    ).allowed
    for denied in (ro / "报告.xlsx", outside / "报告.xlsx"):
        decision = engine.evaluate(
            "write_spreadsheet", {"path": str(denied), "sheets": _sheets()}, _meta()
        )
        assert not decision.allowed, denied
        assert "writable" in decision.reason


# -- provenance and the Artifacts panel --------------------------------------------------


def test_provenance_credits_a_successful_spreadsheet_and_nothing_else(tmp_path):
    """`created_paths` is how a written file becomes an openable artifact and how the
    downstream "this file came from the agent" checks work. It is called only for calls
    that SUCCEEDED, so the failure case here is about the arguments, not the result."""
    from coworker.provenance import WRITTEN, created_paths

    paths, origin = created_paths(
        "write_spreadsheet", {"path": "报告.xlsx", "sheets": _sheets()}, "Wrote …"
    )
    assert paths == ["报告.xlsx"] and origin == WRITTEN

    # No path argument at all: nothing to credit, and no exception either.
    assert created_paths("write_spreadsheet", {"sheets": _sheets()}, "") == ([], "")


def test_the_artifacts_panel_lists_a_spreadsheet_this_session_wrote(tmp_path):
    """The panel's precise-source pass walks the session's own tool calls and keeps the
    ones whose result says they succeeded. A .xlsx the agent wrote must appear; the same
    call with an error result must not — that path may name a file the user already had."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):  # pragma: no cover
            return AssistantTurn(text="", finish_reason="stop")

        def capabilities(self, model):  # pragma: no cover
            return ModelCapabilities()

    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    manager._prefs["scratch_base"] = str(tmp_path / "scratchbase")
    ws = tmp_path / "新建文件夹 (8)"
    ws.mkdir()
    sid = "sessOffice1"
    engine = manager.get_engine(sid, agent="code", workspace=str(ws))
    assert engine is not None

    # Built directly, not through the registry: this test is about what the panel does
    # with a recorded call. How the tool reaches a session is the loader's story, below.
    write_spreadsheet = office_tools(str(ws))[0]
    good = {"path": "成品.xlsx", "sheets": _sheets()}
    result = write_spreadsheet(**good)
    # The file the model asked for but never got: written by hand so the panel's own
    # mtime sweep cannot credit it, then recorded as a FAILED call.
    (ws / "失败.xlsx").write_bytes(b"PK\x03\x04 not ours")

    for call_id, name, args, answer in (
        ("c1", "write_spreadsheet", good, result),
        (
            "c2",
            "write_spreadsheet",
            {"path": "失败.xlsx", "sheets": _sheets()},
            {"error": "boom", "error_type": "ValueError"},
        ),
    ):
        engine.messages.append(
            {
                "role": "assistant",
                "content": "",
                "ts": time.time(),
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            }
        )
        engine.messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": answer if isinstance(answer, str) else json.dumps(answer),
                "ts": time.time(),
                "t0": time.time(),
            }
        )
    manager.save(sid, engine)

    listed = {a["name"]: a for a in manager.list_artifacts(sid)}
    assert "成品.xlsx" in listed
    assert listed["成品.xlsx"]["root"] == "workspace"
    assert listed["成品.xlsx"]["path"] == (ws.resolve() / "成品.xlsx").as_posix()
    assert "失败.xlsx" not in listed


async def test_a_scheduled_task_approves_its_own_spreadsheet_write(tmp_path, monkeypatch):
    """Unattended runs auto-approve the deliverable writes — keyed off WRITE_TOOLS. A
    spreadsheet missing from that set would park the run in the Inbox and suspend it, so a
    nightly report task would silently stop producing reports."""
    from coworker.automation import Schedule, ScheduledTask, TaskRun
    from coworker.engine import ApprovalOutcome, PermissionRequest
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):  # pragma: no cover
            return AssistantTurn(text="ok", finish_reason="stop")

        def capabilities(self, model):  # pragma: no cover
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    task = ScheduledTask(
        title="月度报表",
        instructions="生成月度报表",
        schedule=Schedule(kind="cron", cron="0 9 1 * *"),
        workspace=str(ws),
        agent="cowork",
    )
    manager.task_store.save(task)
    run = TaskRun(task_id=task.id)
    manager.task_store.add_run(run)

    outcome = await manager._scheduled_approver(task, run.session_id)(
        PermissionRequest(
            tool_name="write_spreadsheet",
            arguments={"path": str(ws / "月度报表.xlsx"), "sheets": _sheets()},
            metadata=_meta(),
            reason="requires approval",
            tool_call_id="tc1",
        )
    )
    assert outcome is ApprovalOutcome.ONCE
    assert manager.inbox.pending(run.session_id) == []


# -- on-demand exposure: the loader, and who gets it -------------------------------------


class _StubProvider:
    """build_engine never calls the provider at build time (same stand-in the other
    build_engine suites use)."""

    def complete(self, **_kw):  # pragma: no cover - never invoked at build time
        from coworker.providers import AssistantTurn

        return AssistantTurn()

    def capabilities(self, _model):  # pragma: no cover
        from coworker.providers.base import ModelCapabilities

        return ModelCapabilities()


def _engine_for(agent, tmp_path, **kw):
    from coworker.agent import build_engine

    return build_engine(agent=agent, workspace=tmp_path, provider=_StubProvider(), **kw)


def _schema_names(engine) -> set[str]:
    return {s["function"]["name"] for s in engine.registry.schemas()}


def test_a_fresh_session_advertises_the_loader_not_the_spreadsheet_tool(tmp_path):
    """The whole point of the deferral: `write_spreadsheet`'s schema is ~2,300 chars,
    re-billed every round trip of every session, for a tool most turns never call. The
    loader stands in at ~300."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        names = _schema_names(engine)
        assert "load_office_tools" in names
        assert "write_spreadsheet" not in names
    finally:
        engine.executor.close()


def test_calling_the_loader_puts_the_spreadsheet_tool_in_the_next_prompt(tmp_path):
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        said = engine.registry.execute("load_office_tools", {})
        assert "write_spreadsheet" in said
        assert "write_spreadsheet" in _schema_names(engine)
        # Idempotent: a second call reports the state instead of re-describing the set.
        assert "already loaded" in engine.registry.execute("load_office_tools", {})
    finally:
        engine.executor.close()


def test_the_spreadsheet_tool_is_reachable_by_name_without_the_loader(tmp_path):
    """`ToolRegistry.defer` keeps the held-back name KNOWN. A model that calls
    `write_spreadsheet` straight out — from a resumed transcript, or because the refusal
    text named it — gets the tool, not "no such tool"."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        spec = engine.registry.get("write_spreadsheet")
        assert spec is not None and spec.name == "write_spreadsheet"
        assert spec.metadata.requires_approval is True
        assert "write_spreadsheet" in _schema_names(engine)
    finally:
        engine.executor.close()


def test_every_persona_with_write_file_gets_the_loader_and_no_other_does(tmp_path):
    """The registration condition, stated as behaviour. Cowork and Code have file tools;
    Chat has none and must not carry the loader (it could not use the tool if it did — no
    writable root), and the read-only explorer subagent builds its own registry entirely."""
    from coworker.agents import chat_agent, code_agent, cowork_agent

    for factory in (cowork_agent, code_agent):
        engine = _engine_for(factory(), tmp_path)
        try:
            assert "write_file" in engine.registry.names(), factory.__name__
            assert "load_office_tools" in _schema_names(engine), factory.__name__
        finally:
            engine.executor.close()

    chat = _engine_for(chat_agent(), tmp_path)
    try:
        assert "write_file" not in chat.registry.names()
        assert "load_office_tools" not in _schema_names(chat)
        # Not merely hidden — never deferred either, so no call can conjure it.
        assert chat.registry.get("write_spreadsheet") is None
    finally:
        if chat.executor is not None:
            chat.executor.close()


def test_the_explorer_subagent_carries_neither_the_loader_nor_the_tool(tmp_path):
    """Explore is read-only by construction — its child registry is assembled in
    `subagent.build_explorer_engine`, not by build_engine, so the loader must be absent
    and unreachable there however build_engine changes."""
    from coworker.tools.subagent import build_explorer_engine

    child = build_explorer_engine(
        workspace=tmp_path, provider=_StubProvider(), model="stub"
    )
    assert "write_file" not in child.registry.names()
    assert "load_office_tools" not in _schema_names(child)
    assert child.registry.get("write_spreadsheet") is None


def test_the_materialised_tool_shares_the_session_roots_with_write_file(tmp_path):
    """The loader is built from the same roots LIST object the file tools got, not a copy.
    A folder granted mid-session therefore becomes writable for spreadsheets in that same
    turn — snapshotting the list is the bug this pins (it is what once made `read_file`
    blind to a fresh grant)."""
    from coworker.agents import cowork_agent
    from coworker.roots import RootDir

    scratch, granted = tmp_path / "scratch", tmp_path / "granted"
    scratch.mkdir()
    granted.mkdir()
    engine = _engine_for(
        cowork_agent(),
        scratch,
        roots=[RootDir(path=scratch, writable=True, label="scratch")],
    )
    try:
        write_spreadsheet = engine.registry.get("write_spreadsheet").func
        # Before the grant the folder is off limits — same wording write_file uses.
        try:
            write_spreadsheet(path=str(granted / "报告.xlsx"), sheets=_sheets())
            raise AssertionError("a path outside every root must be refused")
        except PermissionError as exc:
            assert "escapes allowed roots" in str(exc)

        engine.permissions.roots.append(
            RootDir(path=granted, writable=True, label="granted")
        )
        out = write_spreadsheet(path=str(granted / "报告.xlsx"), sheets=_sheets())
        assert (granted / "报告.xlsx").exists()
        assert "(root: granted)" in out
    finally:
        engine.executor.close()


def test_the_loader_description_stays_small(tmp_path):
    """The loader's own schema is prompt too, paid on every round trip of every session
    with file tools. Measured 2026-09-18 at 343 chars, up from 302 when `write_document`
    joined the set — one clause for a second tool. The ceiling leaves room for wording but
    not for a second paragraph, and NOT for naming a third tool in prose: a set that keeps
    growing should get a shorter formulation, not a longer description. (The two tools'
    own schemas are ~2,300 and ~1,000 — that asymmetry IS the feature.)"""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        schema = next(
            s
            for s in engine.registry.schemas()
            if s["function"]["name"] == "load_office_tools"
        )
        assert len(json.dumps(schema)) <= 400, len(json.dumps(schema))
        assert schema["function"]["parameters"]["properties"] == {}
        assert "write_spreadsheet" in schema["function"]["description"]
    finally:
        engine.executor.close()


# -- packaging: the dependency must survive a merge from upstream ------------------------


def test_openpyxl_is_declared_and_importable_in_fork():
    """Two pins and a real import. CI installs the backend straight from pyproject and
    never smoke-tests a frozen build, so a merge that drops either line fails NOWHERE in
    this repo — it surfaces as "this build is missing openpyxl" on a user's machine, where
    there is no Python to fall back on."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "openpyxl" in (root / "pyproject.toml").read_text(encoding="utf-8")
    spec = (root / "packaging" / "openworker-server.spec").read_text(encoding="utf-8")
    assert "openpyxl" in spec

    import openpyxl  # noqa: F401  - the dependency itself, not a stub


# -- the second door: a refused write materialises the tool that can do it ---------------


def _call(name, arguments, call_id="tc1"):
    from coworker.providers import ToolCall

    return ToolCall(id=call_id, name=name, arguments=arguments)


def test_a_tool_can_name_the_tool_the_model_should_have_used(tmp_path):
    """`engine._execute_sync` reads `materialize_tools` off the raised exception. The
    contract is deliberately narrow: the tool the model sees as failing is unchanged —
    same message, same `error_type` — and the named tool simply becomes available."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:

        def needs_helper() -> str:
            error = ValueError("use write_spreadsheet for that")
            error.materialize_tools = ("write_spreadsheet",)
            raise error

        engine.registry.register(needs_helper)
        assert "write_spreadsheet" not in _schema_names(engine)

        result, status = engine._execute_sync(_call("needs_helper", {}))
        assert status == "error"
        assert result["error_type"] == "ValueError"
        assert result["error"] == "use write_spreadsheet for that"
        assert "write_spreadsheet" in _schema_names(engine)
    finally:
        engine.executor.close()


def test_a_refused_xlsx_write_makes_write_spreadsheet_available(tmp_path):
    """The real path, through the real `write_file`: the model asks for a .xlsx, is told
    no, and finds the right tool in its list on the next round trip without having to
    think of `load_office_tools` first."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        assert "write_spreadsheet" not in _schema_names(engine)

        result, status = engine._execute_sync(
            _call("write_file", {"path": "x.xlsx", "content": "a,b\n1,2\n"})
        )
        assert status == "error"
        assert result["error_type"] == "ValueError"  # unchanged for the model
        assert "write_spreadsheet" in result["error"]
        assert "write_spreadsheet" in _schema_names(engine)
        assert not (tmp_path / "x.xlsx").exists()
    finally:
        engine.executor.close()


def test_naming_a_tool_that_does_not_exist_is_not_an_error(tmp_path):
    """A stale name — a renamed tool, a persona that never registered it — must degrade to
    "no extra tool appeared", never to a second exception that buries the first."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:

        def points_nowhere() -> str:
            error = ValueError("original message")
            error.materialize_tools = ("no_such_tool", "write_spreadsheet")
            raise error

        engine.registry.register(points_nowhere)
        result, status = engine._execute_sync(_call("points_nowhere", {}))
        assert status == "error" and result["error"] == "original message"
        # The reachable name in the same tuple still loaded.
        assert "write_spreadsheet" in _schema_names(engine)
        assert "no_such_tool" not in _schema_names(engine)
    finally:
        engine.executor.close()


def test_a_refused_xls_write_offers_xlsx_instead(tmp_path):
    """`.xls` is the OLE2 binary Office 97 wrote, not a ZIP container, and on a Chinese
    office PC it is still what "Excel 文件" often means — so a model reaches for write_file
    with it exactly as it would for .xlsx. Nothing here can write it (openpyxl cannot), so
    the refusal has to say which format IS on offer."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        result, status = engine._execute_sync(
            _call("write_file", {"path": "旧表.xls", "content": "a,b\n"})
        )
        assert status == "error" and result["error_type"] == "ValueError"
        message = result["error"]
        assert "old binary Excel format" in message
        assert "ZIP container" not in message  # it genuinely is not one
        assert "write_spreadsheet" in message and ".xlsx" in message
        assert "write_spreadsheet" in _schema_names(engine)
        assert not (tmp_path / "旧表.xls").exists()
    finally:
        engine.executor.close()


def test_an_ordinary_failure_materialises_nothing(tmp_path):
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        result, status = engine._execute_sync(
            _call("write_file", {"path": str(tmp_path.parent / "越界.txt"), "content": "x"})
        )
        assert status == "error"
        assert "write_spreadsheet" not in _schema_names(engine)
    finally:
        engine.executor.close()


# -- read_spreadsheet: same wiring questions, opposite answers -------------------------
#
# `write_spreadsheet` needed two name-table entries (`WRITE_TOOLS`, `_PATH_ARG`) to become
# a scoped, credited write. `read_spreadsheet` needs NEITHER — its own metadata
# (`requires_approval=False`) is enough for `classify()` to land it on `RiskClass.READ`,
# and `PermissionEngine.evaluate()` allows a non-consequential call before it even looks at
# mode, allowlists or the scheduled-task approver. These pin that absence of wiring is the
# CORRECT state, not an oversight — and that the loader/redirect machinery `write_spreadsheet`
# uses also carries `read_spreadsheet`/`read_document` along.


def _read_meta():
    from coworker.tools.office import spreadsheet_read_tools

    return spreadsheet_read_tools("/tmp/cw-office-read")[0].__aisuite_tool_metadata__


def test_read_spreadsheet_is_read_risk_with_no_write_side_entries():
    assert "read_spreadsheet" not in WRITE_TOOLS
    assert "read_spreadsheet" not in PATH_ARG
    assert classify("read_spreadsheet", _read_meta()) is RiskClass.READ


def test_read_spreadsheet_needs_no_approval_in_any_mode(tmp_path):
    """Every mode this app has, including the two read-only ones and the unattended
    scheduler's own `Mode.INTERACTIVE` — a non-consequential call clears `evaluate()`
    before the read-only-mode denial, the allowlists, or bypass-approvals are even
    consulted (see `Decision(True, "low risk")` ahead of every branch in permissions.py)."""
    for mode in Mode:
        decision = _engine(tmp_path, mode).evaluate(
            "read_spreadsheet", {"path": "台账.xlsx"}, _read_meta()
        )
        assert decision.allowed and not decision.needs_user, mode


async def test_a_scheduled_run_reads_a_spreadsheet_without_ever_reaching_the_approver(
    tmp_path, monkeypatch
):
    """The unattended-run guarantee, driven through a REAL scheduled run
    (`manager._run_scheduled_task`, the same entry point `test_automation.py` uses): the
    model calls `read_spreadsheet` on a fixture workbook, and the run must complete without
    ever parking an approval in the Inbox — the way a `run_shell` fallback to read the file
    would have stalled every week. `_scheduled_approver` is wrapped so a call reaching it
    at all fails the test outright, not just an empty-inbox assertion after the fact."""
    from openpyxl import Workbook

    from coworker.automation import Schedule, ScheduledTask
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    wb = Workbook()
    wb.active.append(["姓名", "金额"])
    wb.active.append(["张三", 1200])
    wb.save(str(ws / "台账.xlsx"))

    class ScriptedProvider(ProviderClient):
        def __init__(self):
            self.calls = 0

        def complete(self, *, model, messages, tools=None, **settings):
            self.calls += 1
            if self.calls == 1:
                return AssistantTurn(
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="read_spreadsheet",
                            arguments={"path": "台账.xlsx"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            return AssistantTurn(text="本周台账已读，共 1 条记录。", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = ScheduledTask(
        title="周报",
        instructions="读取台账并总结",
        schedule=Schedule(kind="cron", cron="0 9 * * 1"),
        workspace=str(ws),
        agent="cowork",
    )
    manager.task_store.save(task)

    real_approver_factory = manager._scheduled_approver

    def _guarded_approver(task_arg, session_id):
        async def _never(request):
            raise AssertionError(
                f"the scheduled approver must never be reached for a read; got "
                f"{request.tool_name!r}"
            )

        return _never

    monkeypatch.setattr(manager, "_scheduled_approver", _guarded_approver)
    try:
        run = await manager._run_scheduled_task(task, trigger="schedule")
    finally:
        monkeypatch.setattr(manager, "_scheduled_approver", real_approver_factory)

    assert run.status == "ok", run.error
    assert manager.inbox.pending(run.session_id) == []
    record = manager.session_store.load(run.session_id)
    tool_messages = [m for m in record.messages if m.get("role") == "tool"]
    # `json.dumps` (default `ensure_ascii=True`) escapes 张三 to \uXXXX in the stored
    # content, so assert on the ASCII amount instead of the Chinese name.
    assert any("1200" in (m.get("content") or "") for m in tool_messages)


def test_the_loader_now_also_advertises_and_loads_the_readers(tmp_path):
    """`load_office_tools` is one defer group for all four tools (agent.py) — calling it
    for a write must not leave the readers behind, and vice versa."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        names = _schema_names(engine)
        assert "read_spreadsheet" not in names and "read_document" not in names
        said = engine.registry.execute("load_office_tools", {})
        assert "read_spreadsheet" in said and "read_document" in said
        assert "read_spreadsheet" in _schema_names(engine)
        assert "read_document" in _schema_names(engine)
    finally:
        engine.executor.close()


def test_the_readers_are_reachable_by_name_without_the_loader(tmp_path):
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        spec = engine.registry.get("read_spreadsheet")
        assert spec is not None and spec.metadata.requires_approval is False
        assert "read_spreadsheet" in _schema_names(engine)
    finally:
        engine.executor.close()


def test_the_explorer_subagent_carries_the_readers_directly_not_the_loader(tmp_path):
    """Unlike the main session, `explore`'s child registry has no `load_office_tools` at
    all (it has no writers to answer for) — `read_spreadsheet`/`read_document` are
    registered straight into it (tools/subagent.py) since the child is rebuilt fresh per
    call and there is no round trip to amortise a deferral against."""
    from coworker.tools.subagent import build_explorer_engine

    child = build_explorer_engine(workspace=tmp_path, provider=_StubProvider(), model="stub")
    assert "load_office_tools" not in _schema_names(child)
    assert "read_spreadsheet" in child.registry.names()
    assert "read_document" in child.registry.names()
    assert "read_spreadsheet" in _schema_names(child)


def test_a_refused_xlsx_read_makes_read_spreadsheet_available(tmp_path):
    """The real path, through the real `read_file`: the model tries to read a .xlsx as
    text, is told no, and finds the right tool in its list on the next round trip."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        (tmp_path / "台账.xlsx").write_bytes(b"PK\x03\x04 not real xlsx bytes, never opened")
        assert "read_spreadsheet" not in _schema_names(engine)

        result, status = engine._execute_sync(_call("read_file", {"path": "台账.xlsx"}))
        assert status == "error"
        assert result["error_type"] == "ValueError"
        assert "read_spreadsheet" in result["error"]
        assert "read_spreadsheet" in _schema_names(engine)
    finally:
        engine.executor.close()


def test_a_refused_xls_read_offers_xlsx_instead(tmp_path):
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        (tmp_path / "旧表.xls").write_bytes(b"not a real xls, never opened")
        result, status = engine._execute_sync(_call("read_file", {"path": "旧表.xls"}))
        assert status == "error" and result["error_type"] == "ValueError"
        message = result["error"]
        assert "old binary Excel format" in message
        assert "read_spreadsheet" in message and ".xlsx" in message
        # No tool answers for an .xls — nothing to materialise.
        assert "read_spreadsheet" not in _schema_names(engine)
    finally:
        engine.executor.close()


async def test_an_interactive_engine_runs_read_spreadsheet_without_asking(tmp_path):
    """The permission story end to end, through a REAL `TurnEngine` turn: the model calls
    `read_spreadsheet`, the approver is wired but must never be awaited, and no
    `PERMISSION_REQUIRED` event is ever emitted — matching how `read_file` already behaves
    (tests/test_engine.py::test_tool_turn_order_and_execution)."""
    from coworker.engine import PermissionRequest, TurnEngine
    from coworker.events import EventType
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
    from coworker.tools import ToolRegistry
    from coworker.tools.office import spreadsheet_read_tools

    _fixture_workbook = tmp_path / "台账.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["姓名", "金额"])
    wb.active.append(["张三", 1200])
    wb.save(str(_fixture_workbook))

    class _ScriptedProvider(ProviderClient):
        def __init__(self):
            self.calls = 0

        def complete(self, *, model, messages, tools=None, **settings):
            self.calls += 1
            if self.calls == 1:
                return AssistantTurn(
                    tool_calls=[
                        ToolCall(id="c1", name="read_spreadsheet", arguments={"path": "台账.xlsx"})
                    ],
                    finish_reason="tool_calls",
                )
            return AssistantTurn(text="读完了", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    registry = ToolRegistry()
    registry.register_all(spreadsheet_read_tools(str(tmp_path)))
    permissions = PermissionEngine(workspace_root=tmp_path, mode=Mode.INTERACTIVE)

    approver_calls: list[str] = []

    async def _recording_approver(request: PermissionRequest):
        approver_calls.append(request.tool_name)
        raise AssertionError("approver must never be awaited for a read")

    engine = TurnEngine(
        provider=_ScriptedProvider(),
        registry=registry,
        permissions=permissions,
        model="gpt-5.5",
        approver=_recording_approver,
    )
    engine._finish_reason_seen.add(engine.model)

    events = [ev async for ev in engine.run("读一下台账")]
    types = [ev.type for ev in events]
    assert EventType.PERMISSION_REQUIRED not in types
    assert approver_calls == []
    finished = [ev for ev in events if ev.type == EventType.TOOL_FINISHED]
    assert len(finished) == 1 and finished[0].data["status"] == "ok"
    assert events[-1].data["status"] == "completed"
