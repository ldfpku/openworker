"""Prompt-budget round 3 (2026-09-01) — ToolRegistry.hold_back() and its build_engine
wiring: a handful of rarely-first tools stay REGISTERED exactly as before, but drop out
of schemas() until the model calls one by name, at which point get() puts it right back.
See coworker/tools/registry.py:hold_back and the two prior rounds (git 8aa5c74, b4dadb6)
for the mechanism this extends."""

from __future__ import annotations

import json

from coworker.agent import build_engine, _hold_back_hint
from coworker.agents import code_agent, cowork_agent
from coworker.memory import SQLiteMemoryStore
from coworker.permissions import Mode
from coworker.personas.registry import PersonaRegistry
from coworker.providers.base import ModelCapabilities
from coworker.secrets import SecretStore


class _StubProvider:
    """build_engine never calls the provider at build time (same stand-in as
    test_connectors.py / test_plan_mode.py)."""

    def complete(self, **_kw):  # pragma: no cover - never invoked at build time
        from coworker.providers import AssistantTurn

        return AssistantTurn()

    def capabilities(self, _model):  # pragma: no cover
        return ModelCapabilities()


def _schema_names(engine) -> set[str]:
    return {s["function"]["name"] for s in engine.registry.schemas()}


# -- registered-but-hidden, per name --------------------------------------------------


def test_workspace_only_tools_are_registered_but_hidden(tmp_path):
    """No messaging, no memory store: only the four tools this bare setup registers
    should be affected. Each is checked individually — absent from schemas(), reachable
    via get(), and back in schemas() once fetched."""
    engine = build_engine(agent=cowork_agent(), workspace=tmp_path, provider=_StubProvider())
    try:
        before = _schema_names(engine)
        for name in ["request_directory", "save_skill", "shell_task_output", "shell_task_kill"]:
            assert name not in before, name
            spec = engine.registry.get(name)
            assert spec is not None, name
            assert name in _schema_names(engine), name
    finally:
        engine.executor.close()


def test_messaging_and_memory_tools_are_registered_but_hidden(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("telegram:default", {"bot_token": "T"})
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    engine = build_engine(
        agent=cowork_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
        memory_store=store,
    )
    try:
        before = _schema_names(engine)
        for name in ["send_file", "memory_update", "memory_forget", "memory_read"]:
            assert name not in before, name
            spec = engine.registry.get(name)
            assert spec is not None, name
            assert name in _schema_names(engine), name
        # `remember` is the common-path write, not a revision tool — stays listed.
        assert "remember" in before
    finally:
        engine.executor.close()


# -- propose_plan: mode-gated, not registration-gated ----------------------------------


def test_lead_role_never_registers_propose_plan(tmp_path):
    """hold_back() must not manufacture a tool the lead gate never granted: skipping an
    unregistered name has to be a true no-op, in both directions."""
    reg = PersonaRegistry()
    engine = build_engine(
        agent=reg.agent("expert-lead"), workspace=tmp_path, provider=_StubProvider()
    )
    try:
        assert "propose_plan" not in _schema_names(engine)
        assert engine.registry.get("propose_plan") is None
    finally:
        engine.executor.close()


def test_plan_mode_build_keeps_propose_plan_live_from_the_start(tmp_path):
    """A session that STARTS in Mode.PLAN needs propose_plan on the very first turn, so
    build_engine must not hold it back in this one case."""
    engine = build_engine(
        agent=code_agent(), workspace=tmp_path, provider=_StubProvider(), mode=Mode.PLAN
    )
    try:
        assert "propose_plan" in _schema_names(engine)
    finally:
        engine.executor.close()


def test_non_plan_build_holds_propose_plan_back_but_keeps_it_reachable(tmp_path):
    """Every other mode (default INTERACTIVE included) holds it back like the rest of the
    list; a mode flip INTO plan mid-session is what coworker/server/app.py's set_mode and
    coworker/tui/app.py's /mode handler materialize it for (registry.get, tested there by
    inspection since both need a live server/TUI harness)."""
    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_StubProvider())
    try:
        assert "propose_plan" not in _schema_names(engine)
        assert engine.registry.get("propose_plan") is not None
        assert "propose_plan" in _schema_names(engine)
    finally:
        engine.executor.close()


# -- catalog: overlapping patch tools trimmed for knowledge-work, kept for Code --------


def test_collab_role_drops_overlapping_patch_tools_code_role_keeps_them(tmp_path):
    cw_dir, code_dir = tmp_path / "cw", tmp_path / "code"
    cw_dir.mkdir()
    code_dir.mkdir()
    cowork = build_engine(agent=cowork_agent(), workspace=cw_dir, provider=_StubProvider())
    code = build_engine(agent=code_agent(), workspace=code_dir, provider=_StubProvider())
    try:
        for name in ("apply_patch", "apply_unified_diff"):
            assert name not in cowork.registry.names(), name
            assert name in code.registry.names(), name
        assert "replace_in_file" in cowork.registry.names()
    finally:
        cowork.executor.close()
        code.executor.close()


# -- discoverability: the hint names only what THIS session actually held back ---------


def test_hold_back_hint_reflects_only_the_names_actually_held_back():
    assert _hold_back_hint([]) == ""
    # propose_plan is named by the plan-mode reminder instead — never by this hint.
    assert _hold_back_hint(["propose_plan"]) == ""
    hint = _hold_back_hint(["propose_plan", "save_skill"])
    assert "save_skill —" in hint
    assert "propose_plan" not in hint


def test_instructions_carry_the_dynamic_hint_for_a_bare_workspace_session(tmp_path):
    engine = build_engine(agent=cowork_agent(), workspace=tmp_path, provider=_StubProvider())
    try:
        text = engine.messages[0]["content"]
        assert "request_directory(reason)" in text
        assert "save_skill —" in text
        assert "shell_task_output(task_id)" in text
        # never registered in this session (no messaging configured, no memory store)
        assert "send_file —" not in text
        assert "memory_update" not in text
        assert "memory_read —" not in text
        assert "propose_plan" not in text
    finally:
        engine.executor.close()


# -- anti-regrowth guardrail -------------------------------------------------------------


def test_fresh_cowork_session_schema_size_stays_within_budget(tmp_path):
    """Not a golden byte count — a tripwire. Measured today (2026-09-01) at 5,937 chars
    of json.dumps(schemas()) for a fresh Cowork session (workspace only, no messaging/
    memory configured). 10% slack absorbs incidental schema wording drift; a real
    addition to the roster should fail this and prompt a deliberate re-measure, not an
    accidental one."""
    engine = build_engine(agent=cowork_agent(), workspace=tmp_path, provider=_StubProvider())
    try:
        size = len(json.dumps(engine.registry.schemas()))
        assert size < 5_937 * 1.10
    finally:
        engine.executor.close()
