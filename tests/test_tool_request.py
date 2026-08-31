"""`request_tool` — the agent asks for a missing CLI instead of dropping the check (OPE-85).

Engine-intercepted like `request_directory`: it never goes through the permission path,
because the user's out-of-band decision IS the consent.
"""

from __future__ import annotations

import pytest

from coworker.engine import EventType, TurnEngine
from coworker.permissions import Mode, PermissionEngine
from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
from coworker.tools import ToolRegistry


class ScriptedProvider(ProviderClient):
    """One turn that calls request_tool, then a plain reply."""

    def __init__(self, tool: str = "gitleaks"):
        self.calls = 0
        self.tool = tool

    def complete(self, *, model, messages, tools=None, **settings):
        self.calls += 1
        if self.calls == 1:
            return AssistantTurn(
                text="",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="request_tool",
                        arguments={"name": self.tool, "reason": "scan history for secrets"},
                    )
                ],
            )
        return AssistantTurn(text="done", tool_calls=[])

    def capabilities(self, model):
        return ModelCapabilities(tools=True)


def _engine(tmp_path, requester, tool: str = "gitleaks"):
    return TurnEngine(
        provider=ScriptedProvider(tool),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path, mode=Mode.INTERACTIVE),
        model="m",
        tool_requester=requester,
    )


async def _run(engine) -> list:
    return [e async for e in engine.run("check this repo")]


@pytest.mark.asyncio
async def test_emits_tool_requested_and_reports_install(tmp_path):
    async def requester(args, tool_call_id=None):
        assert args["name"] == "gitleaks"
        return {"installed": True, "path": "/tmp/gitleaks", "version": "8.30.1"}

    events = await _run(_engine(tmp_path, requester))
    requested = [e for e in events if e.type is EventType.TOOL_REQUESTED]
    assert requested and requested[0].data["name"] == "gitleaks"
    finished = [e for e in events if e.type is EventType.TOOL_FINISHED]
    assert finished[0].data["status"] == "ok"


@pytest.mark.asyncio
async def test_declining_tells_the_agent_to_fall_back_openly(tmp_path, monkeypatch):
    """A refusal must not read as 'check done'. The tool result has to push the agent
    toward a disclosed fallback, which is the whole point of the contract."""
    from coworker import toolchain

    # Truly absent — otherwise the decline-time re-check (below) would find the dev
    # machine's real gitleaks and turn this into the user-provided-copy path.
    monkeypatch.setattr(toolchain, "resolve", lambda name: None)

    async def requester(args, tool_call_id=None):
        return {"installed": False, "reason": "the user declined to install it"}

    engine = _engine(tmp_path, requester)
    events = await _run(engine)
    assert [e for e in events if e.type is EventType.TOOL_REQUESTED]
    finished = [e for e in events if e.type is EventType.TOOL_FINISHED]
    assert finished[0].data["status"] == "denied"

    tool_msg = [m for m in engine.messages if m.get("role") == "tool"][-1]
    body = str(tool_msg["content"]).lower()
    assert "degraded" in body or "fallback" in body


@pytest.mark.asyncio
async def test_decline_recheck_finds_a_copy_the_user_installed_themselves(tmp_path, monkeypatch):
    """The card says "or install it yourself and continue" — that has to be real. A user
    who brews the tool while the prompt is up and clicks Continue has PROVIDED the tool;
    the agent must be handed their copy's path, not a refusal."""
    from coworker import toolchain

    monkeypatch.setattr(toolchain, "resolve", lambda name: "/opt/homebrew/bin/gitleaks")

    async def requester(args, tool_call_id=None):
        return {"installed": False, "reason": "the user declined to install it"}

    engine = _engine(tmp_path, requester)
    events = await _run(engine)
    finished = [e for e in events if e.type is EventType.TOOL_FINISHED]
    assert finished[0].data["status"] == "ok"

    tool_msg = [m for m in engine.messages if m.get("role") == "tool"][-1]
    body = str(tool_msg["content"])
    assert "/opt/homebrew/bin/gitleaks" in body
    assert "own copy" in body  # attributed to the user, not to a managed install


@pytest.mark.asyncio
async def test_event_tells_the_truth_about_installability(tmp_path, monkeypatch):
    """Owner-hit 2026-08-14: the card offered Install for a tool with no pinned build —
    the surface guessed because the event said nothing. The event must carry the
    registry's verdict for catalog tools."""
    from coworker import toolchain

    monkeypatch.setattr(toolchain, "_platform_key", lambda: "darwin_arm64")

    async def requester(args, tool_call_id=None):
        return {"installed": False, "reason": "declined"}

    events = await _run(_engine(tmp_path, requester, tool="gitleaks"))
    data = [e for e in events if e.type is EventType.TOOL_REQUESTED][0].data
    assert data["installable"] is True
    assert data["version"] == toolchain.MANAGED["gitleaks"].version
    assert data["summary"]
    assert data["source"] == "github.com/gitleaks"


@pytest.mark.asyncio
async def test_non_catalog_tool_gets_no_card_and_a_shell_steer(tmp_path, monkeypatch):
    """Owner-hit 2026-08-20: agents routed ordinary brew/pip installs through the
    install card, which could only fail AFTER the user approved. A non-catalog name
    must produce NO prompt at all — just a result steering the agent to the shell."""
    from coworker import toolchain

    monkeypatch.setattr(toolchain, "_platform_key", lambda: "darwin_arm64")
    called = []

    async def requester(args, tool_call_id=None):
        called.append(args)
        return {"installed": False, "reason": "declined"}

    engine = _engine(tmp_path, requester, tool="semgrep")
    events = await _run(engine)
    assert not [e for e in events if e.type is EventType.TOOL_REQUESTED]
    assert called == []  # the user was never asked
    tool_msg = [m for m in engine.messages if m.get("role") == "tool"][-1]
    body = str(tool_msg["content"])
    assert "not in the pinned tool catalog" in body
    assert "shell" in body and "gitleaks" in body  # the catalog is named


@pytest.mark.asyncio
async def test_no_requester_still_returns_guidance(tmp_path):
    """Headless surfaces have nobody to ask — the agent must still be told to disclose
    rather than assume the check passed."""
    engine = _engine(tmp_path, None)
    events = await _run(engine)
    assert not [e for e in events if e.type is EventType.TOOL_REQUESTED]
    tool_msg = [m for m in engine.messages if m.get("role") == "tool"][-1]
    assert "degraded" in str(tool_msg["content"]).lower()


# -- who actually gets request_tool (2026-08-31, prompt cost) --------------------------


def test_request_tool_only_ships_to_personas_that_use_the_pinned_catalog(tmp_path):
    """`toolchain.MANAGED` is a closed set of three security scanners, and the tool's own
    text tells the model to install ANY other missing CLI with the shell instead. So a
    persona that never mentions gitleaks/trivy/osv-scanner could not legitimately call
    this — registering it anyway put ~1,150 chars of schema in front of every session
    with a shell, uncached, on every round trip."""
    from coworker.agent import _mentions_managed_tool, build_engine
    from coworker.agents import code_agent, cowork_agent
    from coworker.personas.registry import PersonaRegistry
    from coworker.secrets import SecretStore

    reg = PersonaRegistry()
    for pid in ("security", "cloud-posture", "dep-audit", "secrets-worker", "posture-worker"):
        assert _mentions_managed_tool(reg.agent(pid)) is True, pid
    for pid in ("cowork", "code", "expert-lead", "production-planning", "failure-analysis"):
        assert _mentions_managed_tool(reg.agent(pid)) is False, pid

    # …and it really is absent from the roster, not merely unmentioned.
    secrets = SecretStore(tmp_path / "secrets.json")
    for agent in (cowork_agent(), code_agent()):
        engine = build_engine(agent=agent, workspace=tmp_path, secrets=secrets)
        assert "request_tool" not in engine.registry.names(), agent.name
    sec = build_engine(agent=reg.agent("security"), workspace=tmp_path, secrets=secrets)
    assert "request_tool" in sec.registry.names()


def test_a_persona_whose_skills_use_a_pinned_tool_still_gets_it():
    """The gate reads the persona's prompt and declared skill NAMES. Guard the gap: if a
    persona's bundled skill body reaches for a managed tool, the persona had better name
    it too — otherwise that persona silently loses its only way to ask for the install."""
    from pathlib import Path

    from coworker.agent import _mentions_managed_tool
    from coworker.personas.registry import PersonaRegistry
    from coworker.toolchain import MANAGED

    reg = PersonaRegistry()
    for entry in reg.list_all():
        manifest = reg.get(entry["id"]).manifest
        if manifest is None or not manifest.skills:
            continue
        skills_dir = Path(manifest.source).parent / "skills"
        uses = False
        for skill in manifest.skills:
            body = skills_dir / skill / "SKILL.md"
            if body.is_file():
                text = body.read_text(encoding="utf-8", errors="replace").lower()
                uses = uses or any(name.lower() in text for name in MANAGED)
        if uses:
            assert _mentions_managed_tool(reg.agent(entry["id"])), entry["id"]
