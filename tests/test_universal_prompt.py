from __future__ import annotations

import pytest

from coworker.agent import build_engine
from coworker.agents import chat_agent, code_agent, cowork_agent, myhelper_agent
from coworker.providers.base import ModelCapabilities
from coworker.universal_prompt import ENV_VAR, load_universal_prompt


class _StubProvider:
    def complete(self, **_kw):  # pragma: no cover - never invoked at build time
        from coworker.providers import AssistantTurn

        return AssistantTurn()

    def capabilities(self, _model):
        return ModelCapabilities()


@pytest.mark.parametrize(
    ("name", "heading"),
    [
        ("core", "# Universal Core"),
        ("balanced", "# Universal Balanced"),
        ("complete", "# Universal Complete"),
    ],
)
def test_prompt_selection(name, heading, monkeypatch):
    monkeypatch.setenv(ENV_VAR, name)
    assert load_universal_prompt().startswith(heading)


@pytest.mark.parametrize("value", ["off", "NONE", ""])
def test_prompt_can_be_disabled(value, monkeypatch):
    monkeypatch.setenv(ENV_VAR, value)
    assert load_universal_prompt() == ""


def test_invalid_prompt_selection_fails_clearly(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "everything")
    with pytest.raises(ValueError, match="core, balanced, complete, off"):
        load_universal_prompt()


@pytest.mark.parametrize(
    ("agent_factory", "role_prompt"),
    [
        (chat_agent, "You are coworker's chat assistant"),
        (code_agent, "You are coworker's coding agent"),
        (cowork_agent, "You are a Cowork agent"),
        (myhelper_agent, "the user's always-on personal helper"),
    ],
)
def test_every_main_agent_gets_balanced_by_default(
    agent_factory, role_prompt, tmp_path, monkeypatch
):
    monkeypatch.delenv(ENV_VAR, raising=False)
    engine = build_engine(
        agent=agent_factory(),
        workspace=tmp_path,
        provider=_StubProvider(),
    )
    try:
        instructions = engine.messages[0]["content"]
        assert role_prompt in instructions
        assert "# Universal Balanced" in instructions
        assert instructions.count("# Universal Balanced") == 1
    finally:
        engine.executor.close()


def test_off_leaves_agent_instructions_without_universal(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "off")
    engine = build_engine(agent=chat_agent(), workspace=tmp_path, provider=_StubProvider())
    try:
        instructions = engine.messages[0]["content"]
        assert "You are coworker's chat assistant" in instructions
        assert "Universal behavioral guidelines" not in instructions
        assert "# Universal Balanced" not in instructions
    finally:
        engine.executor.close()
