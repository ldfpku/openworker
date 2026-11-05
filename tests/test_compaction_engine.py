"""OPE-27 engine hook: the mid-run trigger, the outbound view, the usage signal, the
failure policy (attended prompt / unattended auto-trim), raw-overflow routing, and the
session persistence round-trip. Scripted providers, tiny forced windows, no network."""

import asyncio
import threading
import time

from coworker.engine import TurnEngine
from coworker.events import EventType
from coworker.permissions import PermissionEngine
from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    ToolCall,
)
from coworker.providers.base import TokenUsage
from coworker.tools import ToolRegistry

# Must clear the OPE-189 quality gate: all eight sections, past the minimum length. A
# summary that fails it is refused and the engine falls back to trimming, which is what
# these tests would otherwise be asserting against.
SUMMARY = "\n".join(
    f"## {name}\nenough detail in this section to clear the summary minimum length"
    for name in (
        "Primary request and intent",
        "Key concepts and decisions",
        "Artifacts and files",
        "Errors and fixes",
        "All user messages",
        "Pending tasks",
        "Current work",
        "Next step",
    )
)


class CompactingProvider(ProviderClient):
    """Scripted main turns; summarizer calls (recognized by the compaction system prompt)
    are answered out-of-band so they never consume the main script."""

    def __init__(self, turns, *, summary=SUMMARY, summary_fails=0, main_overflows=0):
        self._turns = list(turns)
        self.summary = summary
        self.summary_fails = summary_fails
        self.main_overflows = main_overflows
        self.summary_calls = []
        self.main_calls = 0

    def complete(self, *, model, messages, tools=None, **settings):
        if messages and "compacting an AI coworker" in str(
            messages[0].get("content", "")
        ):
            self.summary_calls.append({"model": model, "messages": messages})
            if self.summary_fails > 0:
                self.summary_fails -= 1
                raise RuntimeError("summarizer down")
            return AssistantTurn(text=self.summary, finish_reason="stop")
        self.main_calls += 1
        if self.main_overflows > 0:
            self.main_overflows -= 1
            raise RuntimeError(
                "Error 400: maximum context length is 100000 tokens, request used more"
            )
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def long_history(turns=8, bulk=1500):
    msgs = [{"role": "system", "content": "be helpful"}]
    for i in range(turns):
        msgs.append({"role": "user", "content": f"request {i}", "ts": 1.0})
        msgs.append(
            {"role": "assistant", "content": f"answer {i} " + "x" * bulk, "ts": 1.0}
        )
    return msgs


def make_engine(tmp_path, provider, *, messages=None, cap=400):
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        messages=messages,
    )
    engine.compaction_settings = lambda: {
        "cap_tokens": cap,
        "threshold_pct": 0.8,
        "context_window": 100_000,
    }
    return engine


def collect(engine, text="continue"):
    async def _run():
        return [e async for e in engine.run(text)]

    return asyncio.run(_run())


def test_catalog_window_drives_the_trigger_for_a_custom_model(tmp_path):
    # A custom/relay model the static matrix doesn't carry: its window comes from the
    # injected catalog hook, and with no cap the trigger is 0.8 × that window.
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="custom:crouton-alpha",
    )
    # No cap_tokens and no context_window from settings — the engine must resolve the
    # window from the catalog hook, exactly as the manager injects it.
    engine.compaction_settings = lambda: {"threshold_pct": 0.8}
    engine.catalog_context_window = lambda m: 1_050_000 if m == "custom:crouton-alpha" else None

    cfg = engine._compaction_config()
    assert cfg["context_window"] == 1_050_000
    assert cfg.get("cap_tokens") in (None, 0)  # no GUI/default cap

    # 0.8 × 1.05M = 840k, no clamp. Just under does not compact; just over does.
    assert engine._last_context_tokens is None
    engine._last_context_tokens = 839_999
    assert engine._compaction_due() is False
    engine._last_context_tokens = 840_001
    assert engine._compaction_due() is True


def test_power_user_cap_still_clamps_the_catalog_window(tmp_path):
    # The config.toml / env power-user path threads a cap through compaction_settings();
    # then the old min(...) applies even for a large catalog window.
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="custom:crouton-alpha",
    )
    engine.compaction_settings = lambda: {"threshold_pct": 0.8, "cap_tokens": 250_000}
    engine.catalog_context_window = lambda m: 1_050_000

    engine._last_context_tokens = 249_999
    assert engine._compaction_due() is False
    engine._last_context_tokens = 250_001
    assert engine._compaction_due() is True


def test_compacts_before_the_turn_when_estimate_crosses(tmp_path):
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = make_engine(tmp_path,provider, messages=long_history(), cap=400)
    events = collect(engine)

    assert any(e.type == EventType.COMPACTED for e in events)
    assert not any(e.type == EventType.ERROR for e in events)
    state = engine.compaction_state
    assert state is not None and not state.trimmed
    assert provider.summary_calls[0]["model"] == "gpt-5.5"  # session's own model

    # Outbound view: system survives, the block stands in for the old turns, the
    # canonical transcript is untouched, and the persisted notice marks the spot.
    out = engine._outbound_messages()
    assert out[0]["role"] == "system"
    assert "<compacted-history>" in out[1]["content"]
    assert SUMMARY.splitlines()[-1] in out[1]["content"]
    assert "request 0" in out[1]["content"]  # mechanical user-message list
    assert any("answer 0" in str(m.get("content")) for m in engine.messages)
    assert any(
        m.get("role") == "notice" and m.get("kind") == "compacted"
        for m in engine.messages
    )


def test_usage_signal_triggers_between_tool_turns(tmp_path):
    # History too small for the estimate path — only the reported usage crosses the
    # trigger, after iteration 1's round-trip. The compaction runs before iteration 2.
    provider = CompactingProvider(
        [
            AssistantTurn(
                tool_calls=[ToolCall(id="c1", name="nonexistent_tool", arguments={})],
                finish_reason="tool_calls",
                usage=TokenUsage(input=90_000, output=10),
            ),
            AssistantTurn(text="done", finish_reason="stop"),
        ]
    )
    engine = make_engine(tmp_path,provider, messages=long_history(turns=2, bulk=10), cap=400)
    events = collect(engine)
    assert any(e.type == EventType.COMPACTED for e in events)
    assert provider.summary_calls  # driven by usage, not the (tiny) estimate
    assert engine._last_context_tokens is None  # reset once the view shrank


def test_summarizer_failure_unattended_auto_trims(tmp_path):
    provider = CompactingProvider(
        [AssistantTurn(text="done", finish_reason="stop")], summary_fails=99
    )
    engine = make_engine(tmp_path,provider, messages=long_history(), cap=400)
    events = collect(engine)  # is_attended is None → unattended policy

    compacted = [e for e in events if e.type == EventType.COMPACTED]
    assert compacted and "trimmed" in compacted[0].data["text"].lower()
    assert engine.compaction_state is not None and engine.compaction_state.trimmed
    assert len(provider.summary_calls) == 2  # the one unconditional retry, then trim


def test_stalled_summarizer_times_out_and_auto_trims(tmp_path):
    """A wedged Cloudflare/non-streaming call must not hold COMPACTING for the SDK's
    ten-minute read timeout. Both attempts are bounded and carry the request timeout."""
    release = threading.Event()

    class HangingProvider(CompactingProvider):
        def complete(self, *, model, messages, tools=None, **settings):
            if messages and "compacting an AI coworker" in str(
                messages[0].get("content", "")
            ):
                self.summary_calls.append(settings)
                release.wait(5)
                raise RuntimeError("released after the deadline")
            return super().complete(
                model=model, messages=messages, tools=tools, **settings
            )

    provider = HangingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    configured = engine.compaction_settings
    engine.compaction_settings = lambda: {**configured(), "summary_timeout": 0.03}

    async def scenario():
        started = time.monotonic()
        events = [event async for event in engine.run("continue")]
        # Measure before asyncio.run() shuts down its default executor: that shutdown
        # deliberately joins abandoned to_thread calls, unlike the long-lived app loop.
        return events, time.monotonic() - started

    try:
        events, elapsed = asyncio.run(scenario())
    finally:
        release.set()

    assert elapsed < 1.0
    assert len(provider.summary_calls) == 2
    assert all(call["timeout"] == 0.03 for call in provider.summary_calls)
    compacted = [e for e in events if e.type == EventType.COMPACTED]
    assert compacted and "trimmed" in compacted[0].data["text"].lower()
    assert engine.compaction_state is not None and engine.compaction_state.trimmed


def test_self_managed_timeouts_try_each_gateway_once_then_clear_the_trigger(tmp_path):
    """A self-managed MAIN model never summarizes on local hardware. Each gateway pool
    member gets one bounded attempt, then the trim leaves nothing to re-compact."""
    release = threading.Event()

    class SlowGatewayProvider(CompactingProvider):
        def complete(self, *, model, messages, tools=None, **settings):
            if messages and "compacting an AI coworker" in str(
                messages[0].get("content", "")
            ):
                self.summary_calls.append({"model": model, **settings})
                release.wait(5)
                raise RuntimeError("released after the deadline")
            return super().complete(
                model=model, messages=messages, tools=tools, **settings
            )

    provider = SlowGatewayProvider(
        [
            AssistantTurn(
                tool_calls=[ToolCall(id="c1", name="nonexistent_tool", arguments={})],
                finish_reason="tool_calls",
            ),
            AssistantTurn(text="done", finish_reason="stop"),
        ]
    )
    engine = make_engine(tmp_path, provider, messages=long_history(turns=20), cap=400)
    engine.model = "ollama:qwen3:8b"
    engine.compaction_settings = lambda: {
        "cap_tokens": 400,
        "threshold_pct": 0.8,
        "context_window": 32_768,
        "summary_timeout": 0.03,
    }

    async def scenario():
        started = time.monotonic()
        events = [event async for event in engine.run("continue")]
        return events, time.monotonic() - started

    try:
        events, elapsed = asyncio.run(scenario())
    finally:
        release.set()

    assert elapsed < 1.0
    assert [call["model"] for call in provider.summary_calls] == [
        "aigw:openai/gpt-6-luna",
        "aigw:workers-ai/@cf/zai-org/glm-5.3-flash",
        "aigw:anthropic/claude-haiku-5.5",
    ]
    for call in provider.summary_calls:
        assert call["timeout"] == 0.03
        assert call.get("reasoning_effort") is None
        assert call["max_tokens"] == 16_000
    compacted = [e for e in events if e.type == EventType.COMPACTED]
    # Exactly one compaction across both iterations: the trim cleared the trigger.
    assert len(compacted) == 1 and "trimmed" in compacted[0].data["text"].lower()
    assert not engine._compaction_due()
    assert provider.main_calls == 2


def test_self_managed_session_uses_fixed_gateway_pool(tmp_path):
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    engine.model = "ollama:qwen3:8b"
    # Neither an old direct-provider pin nor an absent gateway_model may alter the pool.
    engine.compaction_settings = lambda: {
        "cap_tokens": 400,
        "threshold_pct": 0.8,
        "context_window": 32_768,
        "model": "gemini:gemini-3.5-flash-lite",
        "gateway_model": "",
    }
    cfg = engine._compaction_config()
    assert cfg["model"] == "aigw:openai/gpt-6-luna"
    assert cfg["fallback_models"] == [
        "aigw:workers-ai/@cf/zai-org/glm-5.3-flash",
        "aigw:anthropic/claude-haiku-5.5",
    ]
    assert cfg["local_summarizer"] is False
    assert cfg["summary_max_tokens"] == 16_000
    assert cfg["summary_timeout"] == 120.0

    events = collect(engine)
    assert any(e.type == EventType.COMPACTED for e in events)
    assert provider.summary_calls[0]["model"] == "aigw:openai/gpt-6-luna"
    assert provider.summary_calls[0].get("reasoning_effort") is None
    assert engine.model == "ollama:qwen3:8b"


def test_hosted_session_still_honours_a_direct_provider_pin(tmp_path):
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    assert engine._compaction_config()["model"] == "gpt-5.5"
    engine.compaction_settings = lambda: {"model": "gemini:gemini-3.5-flash-lite"}
    cfg = engine._compaction_config()
    assert cfg["model"] == "gemini:gemini-3.5-flash-lite"
    assert cfg["fallback_models"] == []


def test_gateway_pool_automatically_fails_over_to_the_next_model(tmp_path):
    provider = CompactingProvider(
        [AssistantTurn(text="done", finish_reason="stop")], summary_fails=1
    )
    provider.is_local_model = lambda model: model.startswith("custom:")
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    engine.model = "custom:qwen3.8-flash-next-iq2_xs"

    events = collect(engine)

    assert [call["model"] for call in provider.summary_calls] == [
        "aigw:openai/gpt-6-luna",
        "aigw:workers-ai/@cf/zai-org/glm-5.3-flash",
    ]
    assert engine.compaction_state is not None
    assert engine.compaction_state.model_used == "aigw:workers-ai/@cf/zai-org/glm-5.3-flash"
    assert not engine.compaction_state.trimmed
    assert not any(e.type == EventType.ERROR for e in events)


def test_gateway_pool_tries_each_model_once_before_trimming(tmp_path):
    provider = CompactingProvider(
        [AssistantTurn(text="done", finish_reason="stop")], summary_fails=99
    )
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    engine.model = "ollama:qwen3:8b"

    collect(engine)

    assert [call["model"] for call in provider.summary_calls] == [
        "aigw:openai/gpt-6-luna",
        "aigw:workers-ai/@cf/zai-org/glm-5.3-flash",
        "aigw:anthropic/claude-haiku-5.5",
    ]
    assert engine.compaction_state is not None and engine.compaction_state.trimmed


def test_local_custom_session_cannot_be_diverted_to_direct_gemini(tmp_path):
    """The reported 192K custom session must ignore its stale direct-Gemini pin."""
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    provider.is_local_model = lambda model: model.startswith("custom:")
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    engine.model = "custom:qwen3.8-flash-next-iq2_xs"
    engine.compaction_settings = lambda: {
        "cap_tokens": 400,
        "threshold_pct": 0.75,
        "context_window": 192_000,
        "model": "gemini:gemini-3.5-flash-lite",
        "gateway_model": "aigw:anthropic/claude-haiku-5.5",
    }

    cfg = engine._compaction_config()
    assert cfg["local_session"] is True
    assert cfg["model"] == "aigw:openai/gpt-6-luna"
    assert cfg["local_summarizer"] is False

    events = collect(engine)
    assert any(e.type == EventType.COMPACTED for e in events)
    assert provider.summary_calls[0]["model"] == "aigw:openai/gpt-6-luna"
    assert engine.model == "custom:qwen3.8-flash-next-iq2_xs"


def test_hosted_and_self_managed_summarizer_budgets(tmp_path):
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    cfg = engine._compaction_config()
    assert cfg["local_summarizer"] is False
    assert cfg["summary_max_tokens"] == 16_000
    assert cfg["summary_timeout"] == 120.0
    engine.model = "ollama:gemma4"
    local = engine._compaction_config()
    assert local["local_summarizer"] is False
    assert local["summary_max_tokens"] == 16_000
    assert local["summary_timeout"] == 120.0


def test_summarizer_failure_attended_prompts_retry_then_succeeds(tmp_path):
    provider = CompactingProvider(
        [AssistantTurn(text="done", finish_reason="stop")], summary_fails=2
    )
    engine = make_engine(tmp_path,provider, messages=long_history(), cap=400)
    engine.is_attended = lambda: True
    asked = []

    async def asker(args, tool_call_id=None):
        asked.append(args)
        return {"answer": "Retry"}

    engine.question_asker = asker
    collect(engine)

    assert asked and asked[0]["options"] == ["Retry", "Trim oldest 10%"]
    assert engine.compaction_state is not None and not engine.compaction_state.trimmed


def test_summarizer_failure_attended_choose_trim(tmp_path):
    provider = CompactingProvider(
        [AssistantTurn(text="done", finish_reason="stop")], summary_fails=99
    )
    engine = make_engine(tmp_path,provider, messages=long_history(), cap=400)
    engine.is_attended = lambda: True

    async def asker(args, tool_call_id=None):
        return {"answer": "Trim oldest 10%"}

    engine.question_asker = asker
    collect(engine)
    assert engine.compaction_state is not None and engine.compaction_state.trimmed


def test_raw_overflow_routes_into_compaction_and_retries(tmp_path):
    # Trigger never fires (huge cap) — the provider 400 is the only signal. The engine
    # must compact (force) and retry the call instead of surfacing the error.
    provider = CompactingProvider(
        [AssistantTurn(text="recovered", finish_reason="stop")], main_overflows=1
    )
    engine = make_engine(tmp_path,provider, messages=long_history(), cap=1_000_000)
    events = collect(engine)

    assert any(e.type == EventType.COMPACTED for e in events)
    assert not any(e.type == EventType.ERROR for e in events)
    finals = [e for e in events if e.type == EventType.ASSISTANT_MESSAGE]
    assert finals and finals[-1].data["text"] == "recovered"
    assert provider.main_calls == 2


def test_non_overflow_provider_errors_still_surface(tmp_path):
    class FailingProvider(CompactingProvider):
        def complete(self, *, model, messages, tools=None, **settings):
            raise RuntimeError("rate limit exceeded")

    engine = make_engine(tmp_path,FailingProvider([]), messages=long_history(turns=1), cap=1_000_000)
    events = collect(engine)
    assert any(e.type == EventType.ERROR for e in events)
    assert not any(e.type == EventType.COMPACTED for e in events)


def test_set_compaction_settings_pins_only_the_summarizer_model(tmp_path):
    # The ratio is fixed and the token cap is config/env-only now: the GUI can only pin the
    # summarizer model. A threshold/cap posted by an older client is accepted-but-ignored.
    from coworker.compaction import DEFAULT_THRESHOLD_PCT
    from coworker.server.manager import SessionManager

    class Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="hi")

        def capabilities(self, model):
            return ModelCapabilities()

    mgr = SessionManager(workspace=tmp_path, provider=Provider())
    out = mgr.set_compaction_settings(
        threshold_pct=0.5, cap_tokens=100_000, model="gpt-4o-mini"
    )
    assert out["ok"]
    # The pin persisted; the stale threshold/cap did NOT change the effective settings.
    assert mgr.compaction_settings()["model"] == "gpt-4o-mini"
    assert mgr.compaction_settings()["threshold_pct"] == DEFAULT_THRESHOLD_PCT
    assert "cap_tokens" not in mgr.compaction_settings()  # no GUI cap, no default
    assert "compaction_threshold_pct" not in mgr._prefs  # not persisted
    assert "compaction_cap_tokens" not in mgr._prefs

    # The flat /v1/settings names: ratio reported read-only, cap not surfaced.
    payload = mgr.compaction_settings_payload()
    assert payload["compaction_threshold_pct"] == DEFAULT_THRESHOLD_PCT
    assert payload["compaction_model"] == "gpt-4o-mini"
    assert "compaction_cap_tokens" not in payload


def test_power_user_cap_from_config_reaches_compaction_settings(tmp_path, monkeypatch):
    # The config.toml / COWORKER_COMPACTION_CAP_TOKENS escape hatch is the ONLY way a cap
    # reaches compaction now — surfaced as cap_tokens, never from a GUI pref.
    from coworker.config import COMPACTION_CAP_TOKENS_ENV
    from coworker.server.manager import SessionManager

    class Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="hi")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv(COMPACTION_CAP_TOKENS_ENV, "60000")
    mgr = SessionManager(workspace=tmp_path, provider=Provider())
    assert mgr.compaction_settings()["cap_tokens"] == 60_000


def test_compaction_has_no_gateway_model_or_catalog_dependency(tmp_path):
    from coworker.server.manager import SessionManager

    class Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="hi")

        def capabilities(self, model):
            return ModelCapabilities()

    mgr = SessionManager(workspace=tmp_path, provider=Provider())
    mgr._prefs["compaction_model"] = "gemini:gemini-3.5-flash-lite"
    settings = mgr.compaction_settings()
    assert "gateway_model" not in settings
    assert not hasattr(mgr, "_compaction_gateway_model")
    # The legacy value remains available to hosted sessions only; the engine ignores it
    # for self-managed sessions and uses GATEWAY_SUMMARY_MODELS without catalog checks.


def test_compaction_state_survives_save_and_rebuild(tmp_path):
    from coworker.compaction import CompactionState
    from coworker.server.manager import SessionManager

    class Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="hi", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    mgr = SessionManager(workspace=tmp_path, provider=Provider())
    sid = "compact-persist"
    engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
    assert callable(engine.compaction_settings)  # live Settings getter is wired
    assert engine.compaction_settings()["threshold_pct"] == 0.8

    engine.messages += long_history(turns=3)[1:]
    engine.compaction_state = CompactionState(
        boundary_index=3, summary_text="the gist", working_state="", user_messages=["u"]
    )
    mgr.save(sid, engine)
    mgr._engines.pop(sid)

    rebuilt = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
    assert rebuilt.compaction_state == engine.compaction_state


def test_compacting_signal_precedes_the_compacted_marker(tmp_path):
    # The transient-progress contract: COMPACTING fires before the (slow) summarizer
    # call, COMPACTED after — surfaces key the "Compacting context…" spinner on it.
    provider = CompactingProvider([AssistantTurn(text="done", finish_reason="stop")])
    engine = make_engine(tmp_path, provider, messages=long_history(), cap=400)
    events = collect(engine)

    types = [e.type for e in events]
    assert EventType.COMPACTING in types
    assert types.index(EventType.COMPACTING) < types.index(EventType.COMPACTED)
    # The signal is not persisted — only the compacted marker lands in the transcript.
    assert not any(
        m.get("role") == "notice" and m.get("kind") == "compacting"
        for m in engine.messages
    )
