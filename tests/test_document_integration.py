"""`write_document` as the rest of the app sees it — the wiring, not the .docx.

`tests/test_document_tool.py` covers what the tool writes. This file covers everything
that has to KNOW about it, and it is the sibling of `tests/test_office_integration.py`:
the two name registries that make it a write tool, the permission verdicts that follow,
provenance and the Artifacts panel, the loader that keeps its schema out of every prompt,
the refusal that hands it the job, and the packaging pins.

Written as its own file rather than folded into the spreadsheet suite because the failure
modes are per-name, not per-family: `write_spreadsheet` can be wired perfectly while
`write_document` is missing from both registries, and nothing errors. A missing `_PATH_ARG`
entry just makes every document ask a human, in every mode. A missing `WRITE_TOOLS` entry
leaves the tool running but unscoped, uncredited and invisible in the panel. So each group
below states what its absence would look like on the user's screen — that is the thing a
merge from upstream can quietly restore.
"""

from __future__ import annotations

import json
import time

from coworker.permissions import Mode, PermissionEngine
from coworker.permissions import _PATH_ARG as PATH_ARG
from coworker.risk import WRITE_TOOLS, RiskClass, classify
from coworker.tools.document import document_tools

_MARKDOWN = "# 季度报告\n\n第一段。\n\n- 甲\n- 乙\n"


def _meta():
    """The tool's own metadata, as the registry hands it to the permission engine."""
    return document_tools("/tmp/cw-doc")[0].__aisuite_tool_metadata__


def _args(path: str = "报告.docx") -> dict:
    return {"path": path, "markdown": _MARKDOWN}


# -- the two name registries ------------------------------------------------------------


def test_write_document_is_a_declared_write_tool_in_fork():
    """`risk.WRITE_TOOLS` is what makes this a write rather than a generic external call.
    Dropped, `classify` falls back to the metadata (`requires_approval=True` → EXTERNAL):
    still approval-gated, but path scoping, the read-only-mode denial, provenance and the
    Artifacts panel all key off WRITE_LOCAL — so an approved call could write to any
    absolute path on the machine and never appear in the panel."""
    assert "write_document" in WRITE_TOOLS
    assert classify("write_document", _meta()) is RiskClass.WRITE_LOCAL


def test_write_document_path_argument_is_registered_in_fork():
    """`permissions._PATH_ARG` maps a write tool to the argument naming its target. Without
    the entry `write_paths` reports `located=False` and `evaluate` fails closed with
    "cannot determine the write path to scope" + `human_only=True` — i.e. every document,
    in every mode including bypass-approvals, stops for a human click. The contrast test
    below runs exactly that removal."""
    assert PATH_ARG["write_document"] == "path"


# -- what those two registries buy: the permission verdicts ------------------------------


def _engine(tmp_path, mode, **kw):
    return PermissionEngine(workspace_root=tmp_path, mode=mode, **kw)


def test_bypass_approvals_writes_a_document_without_asking(tmp_path):
    decision = _engine(tmp_path, Mode.BYPASS_APPROVALS).evaluate(
        "write_document", _args(), _meta()
    )
    assert decision.allowed, decision.reason


def test_without_the_path_arg_entry_even_bypass_approvals_stops_to_ask(
    tmp_path, monkeypatch
):
    """The contrast for the pin above: the ONLY difference is the `_PATH_ARG` entry."""
    import coworker.permissions as permissions

    monkeypatch.delitem(permissions._PATH_ARG, "write_document")
    decision = _engine(tmp_path, Mode.BYPASS_APPROVALS).evaluate(
        "write_document", _args(), _meta()
    )
    assert not decision.allowed
    assert decision.needs_user and decision.human_only
    assert "scope" in decision.reason


def test_interactive_mode_asks_before_writing_a_document(tmp_path):
    decision = _engine(tmp_path, Mode.INTERACTIVE).evaluate(
        "write_document", _args(), _meta()
    )
    assert not decision.allowed and decision.needs_user


def test_read_only_modes_refuse_a_document_outright(tmp_path):
    for mode in (Mode.PLAN, Mode.DISCUSS):
        decision = _engine(tmp_path, mode).evaluate("write_document", _args(), _meta())
        assert not decision.allowed, mode
        # A read-only mode never asks — there is nothing a click could unlock.
        assert not decision.needs_user, mode
        assert "read-only" in decision.reason


def test_a_document_outside_the_writable_roots_is_refused(tmp_path):
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

    assert engine.evaluate("write_document", _args(str(rw / "报告.docx")), _meta()).allowed
    for denied in (ro / "报告.docx", outside / "报告.docx"):
        decision = engine.evaluate("write_document", _args(str(denied)), _meta())
        assert not decision.allowed, denied
        assert "writable" in decision.reason


# -- provenance and the Artifacts panel --------------------------------------------------


def test_provenance_credits_a_successful_document_and_nothing_else(tmp_path):
    """`created_paths` is how a written file becomes an openable artifact and how the
    downstream "this file came from the agent" checks work. It is called only for calls
    that SUCCEEDED, so the failure case here is about the arguments, not the result."""
    from coworker.provenance import WRITTEN, created_paths

    paths, origin = created_paths("write_document", _args(), "Wrote …")
    assert paths == ["报告.docx"] and origin == WRITTEN

    # No path argument at all: nothing to credit, and no exception either.
    assert created_paths("write_document", {"markdown": _MARKDOWN}, "") == ([], "")


def test_the_artifacts_panel_lists_a_document_this_session_wrote(tmp_path):
    """The panel's precise-source pass walks the session's own tool calls and keeps the
    ones whose result says they succeeded. A .docx the agent wrote must appear (the suffix
    is in both `manager._ARTIFACT_SUFFIXES` and the narrower non-scratch set); the same
    call with an error result must not — that path may name a file the user already had."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import (
        _ARTIFACT_SUFFIXES,
        _SESSION_ARTIFACT_SUFFIXES,
        SessionManager,
    )

    # The whitelists the panel filters on: a .docx missing from either would make a
    # perfectly wired write tool produce files the panel refuses to list.
    assert ".docx" in _ARTIFACT_SUFFIXES
    assert ".docx" in _SESSION_ARTIFACT_SUFFIXES

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):  # pragma: no cover
            return AssistantTurn(text="", finish_reason="stop")

        def capabilities(self, model):  # pragma: no cover
            return ModelCapabilities()

    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    manager._prefs["scratch_base"] = str(tmp_path / "scratchbase")
    ws = tmp_path / "新建文件夹 (9)"
    ws.mkdir()
    sid = "sessDoc1"
    engine = manager.get_engine(sid, agent="code", workspace=str(ws))
    assert engine is not None

    # Built directly, not through the registry: this test is about what the panel does
    # with a recorded call. How the tool reaches a session is the loader's story, below.
    write_document = document_tools(str(ws))[0]
    good = _args("成品.docx")
    result = write_document(**good)
    # The file the model asked for but never got: written by hand so the panel's own
    # mtime sweep cannot credit it, then recorded as a FAILED call.
    (ws / "失败.docx").write_bytes(b"PK\x03\x04 not ours")

    for call_id, args, answer in (
        ("c1", good, result),
        ("c2", _args("失败.docx"), {"error": "boom", "error_type": "ValueError"}),
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
                        "function": {
                            "name": "write_document",
                            "arguments": json.dumps(args),
                        },
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
    assert "成品.docx" in listed
    assert listed["成品.docx"]["root"] == "workspace"
    assert listed["成品.docx"]["path"] == (ws.resolve() / "成品.docx").as_posix()
    assert "失败.docx" not in listed


async def test_a_scheduled_task_approves_its_own_document_write(tmp_path, monkeypatch):
    """Unattended runs auto-approve the deliverable writes — keyed off WRITE_TOOLS. A
    document missing from that set would park the run in the Inbox and suspend it, so a
    weekly-summary task would silently stop producing summaries."""
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
        title="周报",
        instructions="生成周报",
        schedule=Schedule(kind="cron", cron="0 9 * * 1"),
        workspace=str(ws),
        agent="cowork",
    )
    manager.task_store.save(task)
    run = TaskRun(task_id=task.id)
    manager.task_store.add_run(run)

    outcome = await manager._scheduled_approver(task, run.session_id)(
        PermissionRequest(
            tool_name="write_document",
            arguments=_args(str(ws / "周报.docx")),
            metadata=_meta(),
            reason="requires approval",
            tool_call_id="tc1",
        )
    )
    assert outcome is ApprovalOutcome.ONCE
    assert manager.inbox.pending(run.session_id) == []


# -- on-demand exposure: the loader it shares with write_spreadsheet ---------------------


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


def test_office_tools_exposes_both_writers_in_one_set():
    """`agent.build_engine` hands the loader whatever `office_tools` returns, so the set
    membership IS the exposure. A `document_tools` that stopped being spliced in there
    would leave `write_document` importable, tested and unreachable from any session."""
    from coworker.tools.office import office_tools

    assert [t.__name__ for t in office_tools("/tmp/cw-both")] == [
        "write_spreadsheet",
        "write_document",
    ]


def test_a_fresh_session_advertises_the_loader_not_the_document_tool(tmp_path):
    """The whole point of the deferral: `write_document`'s schema is ~1,000 chars,
    re-billed every round trip of every session, for a tool most turns never call."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        names = _schema_names(engine)
        assert "load_office_tools" in names
        assert "write_document" not in names
    finally:
        engine.executor.close()


def test_calling_the_loader_puts_both_writers_in_the_next_prompt(tmp_path):
    """One loader, both tools — a model that called it for a spreadsheet and is then asked
    for a document must not have to discover a second loader."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        said = engine.registry.execute("load_office_tools", {})
        assert "write_document" in said and "write_spreadsheet" in said
        names = _schema_names(engine)
        assert "write_document" in names and "write_spreadsheet" in names
    finally:
        engine.executor.close()


def test_the_document_tool_is_reachable_by_name_without_the_loader(tmp_path):
    """`ToolRegistry.defer` keeps the held-back name KNOWN. A model that calls
    `write_document` straight out — from a resumed transcript, or because the refusal text
    named it — gets the tool, not "no such tool"."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        spec = engine.registry.get("write_document")
        assert spec is not None and spec.name == "write_document"
        assert spec.metadata.requires_approval is True
        assert "write_document" in _schema_names(engine)
    finally:
        engine.executor.close()


def test_every_persona_with_write_file_can_reach_the_document_tool(tmp_path):
    """The registration condition, stated as behaviour. Cowork and Code have file tools;
    Chat has none and must not be able to conjure the tool (it has no writable root
    either), and the read-only explorer subagent builds its own registry entirely."""
    from coworker.agents import chat_agent, code_agent, cowork_agent

    for factory in (cowork_agent, code_agent):
        engine = _engine_for(factory(), tmp_path)
        try:
            assert "write_file" in engine.registry.names(), factory.__name__
            assert "load_office_tools" in _schema_names(engine), factory.__name__
            assert engine.registry.get("write_document") is not None, factory.__name__
        finally:
            engine.executor.close()

    chat = _engine_for(chat_agent(), tmp_path)
    try:
        assert "write_file" not in chat.registry.names()
        assert "load_office_tools" not in _schema_names(chat)
        # Not merely hidden — never deferred either, so no call can conjure it.
        assert chat.registry.get("write_document") is None
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
    assert child.registry.get("write_document") is None


def test_the_loader_description_names_both_writers(tmp_path):
    """A model deciding whether to spend a round trip on the loader only sees this string.
    Naming just the spreadsheet — which is what the loader said before `write_document`
    existed — means a model asked for a Word file reads "not for me" and goes off to write
    Markdown instead. The size ceiling lives in tests/test_office_integration.py."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        schema = next(
            s
            for s in engine.registry.schemas()
            if s["function"]["name"] == "load_office_tools"
        )
        description = schema["function"]["description"]
        assert "write_document" in description and "write_spreadsheet" in description
        assert ".docx" in description
        assert len(json.dumps(schema)) <= 400, len(json.dumps(schema))
    finally:
        engine.executor.close()


def test_the_materialised_tool_shares_the_session_roots_with_write_file(tmp_path):
    """The loader is built from the same roots LIST object the file tools got, not a copy.
    A folder granted mid-session therefore becomes writable for documents in that same
    turn — snapshotting the list is the bug this pins."""
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
        write_document = engine.registry.get("write_document").func
        # Before the grant the folder is off limits — same wording write_file uses.
        try:
            write_document(path=str(granted / "报告.docx"), markdown=_MARKDOWN)
            raise AssertionError("a path outside every root must be refused")
        except PermissionError as exc:
            assert "escapes allowed roots" in str(exc)

        engine.permissions.roots.append(
            RootDir(path=granted, writable=True, label="granted")
        )
        out = write_document(path=str(granted / "报告.docx"), markdown=_MARKDOWN)
        assert (granted / "报告.docx").exists()
        assert "(root: granted)" in out
    finally:
        engine.executor.close()


# -- the second door: a refused .docx materialises the tool that can do it ---------------


def _call(name, arguments, call_id="tc1"):
    from coworker.providers import ToolCall

    return ToolCall(id=call_id, name=name, arguments=arguments)


def test_a_refused_docx_write_makes_write_document_available(tmp_path):
    """The real path, through the real `write_file`: the model asks for a .docx, is told
    no, and finds the right tool in its list on the next round trip without having to
    think of `load_office_tools` first. `engine._execute_sync` reads `materialize_tools`
    off the raised exception; the contract is that the error the model sees is UNCHANGED —
    same message, same `error_type` — and the named tool simply becomes available."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        assert "write_document" not in _schema_names(engine)

        result, status = engine._execute_sync(
            _call("write_file", {"path": "x.docx", "content": "# 标题\n"})
        )
        assert status == "error"
        assert result["error_type"] == "ValueError"  # unchanged for the model
        assert "write_document" in result["error"]
        assert "write_document" in _schema_names(engine)
        assert not (tmp_path / "x.docx").exists()
    finally:
        engine.executor.close()


def test_a_refused_docm_write_explains_the_macro_limit(tmp_path):
    """.docm is a real container this app could write the body of, but not the macros that
    are the whole reason for the extension — so the refusal has to say which format IS on
    offer rather than implying a .docm is coming."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        result, status = engine._execute_sync(
            _call("write_file", {"path": "宏文档.docm", "content": "x"})
        )
        assert status == "error" and result["error_type"] == "ValueError"
        message = result["error"]
        assert "Macros cannot be generated" in message
        assert "write_document" in message and ".docx" in message
        assert "write_document" in _schema_names(engine)
        assert not (tmp_path / "宏文档.docm").exists()
    finally:
        engine.executor.close()


def test_a_refused_doc_write_offers_docx_instead(tmp_path):
    """`.doc` is the OLE2 binary Word 97 wrote, not a ZIP container, and on a Chinese
    office PC it is still what "Word 文档" often means — so a model reaches for write_file
    with it exactly as it would for .docx. Nothing here can write it (python-docx cannot),
    so the refusal has to say which format IS on offer, and must not invent a container
    story the format does not have."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        result, status = engine._execute_sync(
            _call("write_file", {"path": "旧文档.doc", "content": "正文\n"})
        )
        assert status == "error" and result["error_type"] == "ValueError"
        message = result["error"]
        assert "old binary Word format" in message
        assert "ZIP container" not in message  # it genuinely is not one
        assert "write_document" in message and ".docx" in message
        assert "write_document" in _schema_names(engine)
        assert not (tmp_path / "旧文档.doc").exists()
    finally:
        engine.executor.close()


def test_a_trailing_space_or_dot_does_not_smuggle_a_text_file_past_the_refusal(tmp_path):
    """Windows drops trailing spaces and dots when it creates a file, so `报告.docx ` and
    `报告.docx.` both land on disk as `报告.docx` — while `Path(…).suffix` reports `".docx "`
    and `""` respectively, neither of which is in `_WRITERS`. Measured on Windows 11
    before the fix: the refusal was skipped, `write_file` reported success, and the user
    got a 5-byte text file that Word refuses to open — the exact outcome the whole refusal
    exists to prevent, reachable by one stray keystroke in the model's path argument.

    Both writers are checked because the padding is stripped once, for both families, in
    `_judged_suffix` — a fix applied to only one of them would be the same bug again.
    """
    from coworker.agents import cowork_agent

    cases = [
        ("报告.docx ", "write_document"),
        ("报告.docx.", "write_document"),
        ("报告.docx..", "write_document"),
        ("报告.docx . ", "write_document"),
        ("报告.DOCX ", "write_document"),
        ("旧文档.doc ", "write_document"),
        ("报表.xlsx ", "write_spreadsheet"),
        ("报表.xlsx.", "write_spreadsheet"),
        ("旧表.xls ", "write_spreadsheet"),
    ]
    for padded, expected_tool in cases:
        engine = _engine_for(cowork_agent(), tmp_path)
        try:
            result, status = engine._execute_sync(
                _call("write_file", {"path": padded, "content": "hello"})
            )
            assert status == "error", padded
            assert result["error_type"] == "ValueError", padded
            assert expected_tool in result["error"], padded
            # The tool still gets materialised: a padded path is a typo, not a different
            # request, so the model must land on the same next move.
            assert expected_tool in _schema_names(engine), padded
        finally:
            engine.executor.close()
        # Nothing on disk under EITHER spelling — Windows would have stripped the padding.
        assert list(tmp_path.iterdir()) == [], (padded, list(tmp_path.iterdir()))

    # The presentation family shares the one suffix computation, so it is closed too.
    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        result, status = engine._execute_sync(
            _call("write_file", {"path": "演示.pptx ", "content": "hello"})
        )
        assert status == "error" and "python-pptx" in result["error"]
    finally:
        engine.executor.close()
    assert list(tmp_path.iterdir()) == []


def test_padding_does_not_change_an_allowed_extension(tmp_path):
    """The stripping is for the JUDGEMENT only. A .md with a stray trailing space is still
    written, at the path the caller gave — stripping the path itself would be a silent
    rename, and the receipt would then name a file the model never asked for."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        result, status = engine._execute_sync(
            _call("write_file", {"path": "笔记.md ", "content": "# x\n"})
        )
        assert status == "ok", result
        # Windows strips the padding on the way to disk; the point is that it was written.
        assert [p.name for p in tmp_path.iterdir()] in (["笔记.md"], ["笔记.md "])
    finally:
        engine.executor.close()


def test_a_refused_pptx_write_names_neither_in_app_writer(tmp_path):
    """The family with no in-app writer keeps the old routing, and must not be handed a
    tool that writes a different kind of file — a model told to "use write_document" for a
    deck would deliver a .docx and report a presentation."""
    from coworker.agents import cowork_agent

    engine = _engine_for(cowork_agent(), tmp_path)
    try:
        result, status = engine._execute_sync(
            _call("write_file", {"path": "演示.pptx", "content": "x"})
        )
        assert status == "error" and result["error_type"] == "ValueError"
        message = result["error"]
        assert "python-pptx" in message
        assert "python-docx" not in message  # belonged to the old .docx branch
        assert "write_document" not in message and "write_spreadsheet" not in message
        assert "write_document" not in _schema_names(engine)
    finally:
        engine.executor.close()


# -- packaging: the dependencies must survive a merge from upstream ----------------------


def _spec_collectors(source: str | None = None) -> dict[str, set[str]]:
    """{PyInstaller collector name -> the packages the spec collects with it}.

    Read with `ast`, not `in spec`, because substring matching cannot tell the two cases
    apart and the difference between them IS the bug below: the spec collects packages in
    `for pkg in (...)` loops, so `'"docx"' in spec` is equally true whether docx sits in
    the `collect_all` loop or the `collect_submodules` one. Direct calls with a literal
    argument are read too, so rewriting the loop as `collect_all("docx")` still passes.

    `source` overrides the real spec — used below to check this parser can actually tell
    the two shapes apart, so its verdict on the real file is not taken on faith.
    """
    import ast
    from pathlib import Path

    if source is None:
        source = (
            Path(__file__).resolve().parents[1] / "packaging" / "openworker-server.spec"
        ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    out: dict[str, set[str]] = {}

    def _strings(node) -> set[str]:
        return {
            e.value
            for e in getattr(node, "elts", [])
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }

    # `for pkg in ("a", "b"): … collector(pkg)` — credit every name in the tuple to every
    # collector called anywhere inside the loop (including inside a try/except).
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        packages = _strings(node.iter)
        if not packages:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                out.setdefault(inner.func.id, set()).update(packages)

    # `collector("a")` written out directly.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out.setdefault(node.func.id, set()).add(first.value)
    return out


def test_python_docx_and_markdown_it_are_declared_and_importable_in_fork():
    """Two pins and two real imports. CI installs the backend straight from pyproject and
    never smoke-tests a frozen build, so a merge that drops a line fails NOWHERE in this
    repo — it surfaces as "this build is missing python-docx" on a user's machine, where
    there is no Python to fall back on.

    `docx` must be collected by `collect_all`, which stages DATA files, and not merely by
    `collect_submodules`, which stages code: a .docx is built by copying the package's own
    `docx/templates/default.docx` (plus the .xml part templates beside it). Code-only
    collection imports cleanly and then raises PackageNotFoundError on the first call —
    the worst shape of failure available here, because every test in this repo still
    passes and the break only appears on a user's machine. `markdown_it` is pure code, so
    either collector is enough for it.
    """
    from pathlib import Path

    pyproject = (
        Path(__file__).resolve().parents[1] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert "python-docx" in pyproject
    assert "markdown-it-py" in pyproject

    # The parser's whole job is telling the two loop shapes apart, so prove it does
    # before trusting its verdict on the real spec — otherwise the assertions below
    # could be passing because the parser finds everything everywhere.
    staged = _spec_collectors('for pkg in ("docx", "x"):\n    d, b, h = collect_all(pkg)\n')
    assert staged["collect_all"] == {"docx", "x"}
    assert "collect_submodules" not in staged
    code_only = _spec_collectors(
        'for pkg in ("docx", "x"):\n    hiddenimports += collect_submodules(pkg)\n'
    )
    assert code_only.get("collect_all", set()) == set()  # the regression this guards
    assert code_only["collect_submodules"] == {"docx", "x"}

    collectors = _spec_collectors()
    assert "docx" in collectors.get("collect_all", set()), sorted(collectors)
    assert "markdown_it" in collectors.get("collect_submodules", set()) | collectors.get(
        "collect_all", set()
    )

    import docx  # noqa: F401  - the dependency itself, not a stub
    import markdown_it  # noqa: F401
