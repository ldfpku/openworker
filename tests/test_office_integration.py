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
