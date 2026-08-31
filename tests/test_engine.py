"""P2 gate tests — turn engine + event bus (scripted provider, no network)."""

from __future__ import annotations

import asyncio
import threading
import time

import aisuite as ai
from coworker.engine import ApprovalOutcome, PermissionRequest, TurnEngine
from coworker.events import EventType
from coworker.permissions import PermissionEngine
from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    ToolCall,
)
from coworker.tools import ToolRegistry


def _text_turn(text):
    return AssistantTurn(text=text, finish_reason="stop")


def _tool_turn(name, args, call_id="call_1"):
    return AssistantTurn(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        finish_reason="tool_calls",
    )


class ScriptedProvider(ProviderClient):
    """Returns queued AssistantTurns; streams via the base default (one final chunk)."""

    def __init__(self, turns, *, loop=False):
        self._turns = list(turns)
        self._loop = loop
        self.calls = 0

    def complete(self, *, model, messages, tools=None, **settings):
        self.calls += 1
        return self._turns[0] if self._loop else self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def _engine(tmp_path, turns, *, approver=None, loop=False, max_iterations=12):
    provider = ScriptedProvider(turns, loop=loop)
    registry = ToolRegistry()
    registry.register_all(ai.toolkits.files(root=str(tmp_path), allow_write=True))
    permissions = PermissionEngine(workspace_root=tmp_path)
    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=permissions,
        model="gpt-5.5",
        approver=approver,
        max_iterations=max_iterations,
    )
    return engine, provider


def _collect(engine, user_input):
    async def _run():
        return [ev async for ev in engine.run(user_input)]

    return asyncio.run(_run())


def _types(events):
    return [ev.type for ev in events]


# -- tests ----------------------------------------------------------------------


def test_no_tool_turn(tmp_path):
    engine, _ = _engine(tmp_path, [_text_turn("all done")])
    events = _collect(engine, "hi")
    assert _types(events) == [
        EventType.TURN_START,
        EventType.ASSISTANT_MESSAGE,
        EventType.TURN_END,
    ]
    assert events[1].data["text"] == "all done"
    assert events[-1].data["status"] == "completed"


def test_tool_turn_order_and_execution(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    engine, _ = _engine(
        tmp_path,
        [_tool_turn("read_file", {"path": "a.txt"}), _text_turn("it says hello")],
    )
    events = _collect(engine, "read a.txt")
    assert EventType.PERMISSION_REQUIRED not in _types(events)
    assert _types(events) == [
        EventType.TURN_START,
        EventType.ASSISTANT_MESSAGE,
        EventType.TOOL_PROPOSED,
        EventType.TOOL_STARTED,
        EventType.TOOL_FINISHED,
        EventType.ITERATION_END,
        EventType.ASSISTANT_MESSAGE,
        EventType.TURN_END,
    ]
    finished = next(e for e in events if e.type == EventType.TOOL_FINISHED)
    assert finished.data["status"] == "ok"
    assert any(
        m.get("role") == "tool" and "hello" in m["content"] for m in engine.messages
    )


def test_write_requires_approval_then_approved(tmp_path):
    async def approve_once(_req: PermissionRequest):
        return ApprovalOutcome.ONCE

    engine, _ = _engine(
        tmp_path,
        [
            _tool_turn("write_file", {"path": "new.py", "content": "print(1)\n"}),
            _text_turn("wrote new.py"),
        ],
        approver=approve_once,
    )
    events = _collect(engine, "create new.py")
    assert EventType.PERMISSION_REQUIRED in _types(events)
    assert (tmp_path / "new.py").read_text() == "print(1)\n"


def test_denied_tool_yields_error_and_continues(tmp_path):
    async def deny(_req: PermissionRequest):
        return ApprovalOutcome.DENY

    engine, _ = _engine(
        tmp_path,
        [
            _tool_turn("write_file", {"path": "new.py", "content": "x"}),
            _text_turn("ok, skipped it"),
        ],
        approver=deny,
    )
    events = _collect(engine, "create new.py")
    assert not (tmp_path / "new.py").exists()
    finished = next(e for e in events if e.type == EventType.TOOL_FINISHED)
    assert finished.data["status"] == "denied"
    assert _types(events)[-1] == EventType.TURN_END
    assert any(
        m.get("role") == "tool" and "not executed" in m["content"]
        for m in engine.messages
    )


def test_max_iterations_rail(tmp_path):
    engine, provider = _engine(
        tmp_path, [_tool_turn("list_files", {})], loop=True, max_iterations=3
    )
    events = _collect(engine, "loop forever")
    end = events[-1]
    assert end.type == EventType.TURN_END
    assert end.data["status"] == "max_iterations_exceeded"
    assert provider.calls == 3


def test_interrupt_between_iterations(tmp_path):
    engine_holder = {}

    async def approve_and_interrupt(_req: PermissionRequest):
        engine_holder["engine"].request_interrupt()
        return ApprovalOutcome.ONCE

    engine, provider = _engine(
        tmp_path,
        [
            _tool_turn("write_file", {"path": "x.py", "content": "x"}),
            _text_turn("should not be reached"),
        ],
        approver=approve_and_interrupt,
    )
    engine_holder["engine"] = engine
    events = _collect(engine, "do a thing")
    assert events[-1].type == EventType.INTERRUPTED
    assert provider.calls == 1


def test_steering_injects_next_turn(tmp_path):
    engine, provider = _engine(tmp_path, [_text_turn("first"), _text_turn("second")])
    engine.queue_steering("actually, also do this")
    events = _collect(engine, "do the first thing")
    assert provider.calls == 2
    assert any(
        m.get("role") == "user" and m["content"] == "actually, also do this"
        for m in engine.messages
    )
    assert events[-1].data["status"] == "completed"


# -- parallel tool execution ------------------------------------------------------


def _multi_tool_turn(calls):
    return AssistantTurn(
        tool_calls=[
            ToolCall(id=f"call_{i}", name=name, arguments=args)
            for i, (name, args) in enumerate(calls)
        ],
        finish_reason="tool_calls",
    )


def _bare_engine(tmp_path, turns):
    provider = ScriptedProvider(turns)
    registry = ToolRegistry()
    permissions = PermissionEngine(workspace_root=tmp_path)
    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=permissions,
        model="gpt-5.5",
    )
    return engine, registry


def test_low_risk_tool_calls_run_concurrently(tmp_path):
    # Both tools block on a 2-party barrier: the turn only completes if the engine
    # really runs them at the same time (sequential execution would trip the timeout
    # and surface as an error result).
    barrier = threading.Barrier(2, timeout=5)
    low = ai.ToolMetadata(category="search", risk_level="low", requires_approval=False)

    def side_a():
        """Wait for side_b."""
        barrier.wait()
        return {"side": "a"}

    def side_b():
        """Wait for side_a."""
        barrier.wait()
        return {"side": "b"}

    engine, registry = _bare_engine(
        tmp_path,
        [_multi_tool_turn([("side_a", {}), ("side_b", {})]), _text_turn("done")],
    )
    registry.register(side_a, metadata=low)
    registry.register(side_b, metadata=low)

    events = _collect(engine, "go")
    finished = [e for e in events if e.type == EventType.TOOL_FINISHED]
    assert len(finished) == 2
    assert all(e.data["status"] == "ok" for e in finished)
    # a tool result message exists for every call id
    tool_ids = {
        m.get("tool_call_id") for m in engine.messages if m.get("role") == "tool"
    }
    assert tool_ids == {"call_0", "call_1"}


def test_non_low_risk_tool_calls_stay_sequential(tmp_path):
    order = []
    medium = ai.ToolMetadata(
        category="filesystem", risk_level="medium", requires_approval=False
    )

    def first():
        """Record start/end with a delay."""
        order.append("first-start")
        time.sleep(0.2)
        order.append("first-end")
        return "ok"

    def second():
        """Record start/end."""
        order.append("second-start")
        order.append("second-end")
        return "ok"

    engine, registry = _bare_engine(
        tmp_path,
        [_multi_tool_turn([("first", {}), ("second", {})]), _text_turn("done")],
    )
    registry.register(first, metadata=medium)
    registry.register(second, metadata=medium)

    _collect(engine, "go")
    assert order == ["first-start", "first-end", "second-start", "second-end"]


class StreamingProvider(ProviderClient):
    def complete(self, **kwargs):  # pragma: no cover - streamed instead
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        for piece in ["Hel", "lo, ", "world"]:
            yield StreamChunk(text_delta=piece)
        yield StreamChunk(turn=AssistantTurn(text="Hello, world", finish_reason="stop"))


def test_streaming_emits_deltas(tmp_path):
    registry = ToolRegistry()
    permissions = PermissionEngine(workspace_root=tmp_path)
    engine = TurnEngine(
        provider=StreamingProvider(),
        registry=registry,
        permissions=permissions,
        model="gpt-5.5",
    )
    events = _collect(engine, "say hi")
    deltas = [e.data["text"] for e in events if e.type == EventType.ASSISTANT_DELTA]
    assert deltas == ["Hel", "lo, ", "world"]
    final = next(e for e in events if e.type == EventType.ASSISTANT_MESSAGE)
    assert final.data["text"] == "Hello, world"
    assert events[-1].type == EventType.TURN_END


def _pdf_file_part():
    import base64
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    url = "data:application/pdf;base64," + base64.b64encode(buf.getvalue()).decode()
    return {"type": "file", "file": {"filename": "d.pdf", "file_data": url}}


def test_outbound_adapts_pdf_for_non_pdf_models(tmp_path):
    # ScriptedProvider reports default caps (pdf=False) → the file part must be
    # replaced at send time while the stored history keeps the real document.
    engine, _ = _engine(tmp_path, [_text_turn("ok")])
    engine.messages.append(
        {
            "role": "user",
            "content": [{"type": "text", "text": "read this"}, _pdf_file_part()],
        }
    )
    parts = engine._outbound_messages()[-1]["content"]
    assert all(p["type"] != "file" for p in parts)
    assert "d.pdf" in parts[-1]["text"]
    assert engine.messages[-1]["content"][1]["type"] == "file"  # history untouched


def test_outbound_keeps_pdf_for_native_models(tmp_path):
    class NativeProvider(ScriptedProvider):
        def capabilities(self, model):
            return ModelCapabilities(vision=True, pdf=True)

    engine, _ = _engine(tmp_path, [_text_turn("ok")])
    engine.provider = NativeProvider([_text_turn("ok")])
    message = {
        "role": "user",
        "content": [{"type": "text", "text": "read this"}, _pdf_file_part()],
    }
    engine.messages.append(message)
    assert engine._outbound_messages()[-1]["content"][1]["type"] == "file"


def test_provider_extras_persist_on_message_and_survive_outbound(tmp_path):
    """A turn's provider-private sidecar (`extras`, e.g. Gemini thought signatures) rides
    the persisted assistant message and is NOT stripped by _outbound_messages — the owning
    provider needs it back; foreign providers strip it themselves."""
    turn = AssistantTurn(
        text="ok",
        finish_reason="stop",
        extras={"_gemini": {"text_sig": "c2ln", "call_sigs": []}},
    )
    engine, _ = _engine(tmp_path, [turn])
    _collect(engine, "hi")

    persisted = engine.messages[-1]
    assert persisted["_gemini"] == {"text_sig": "c2ln", "call_sigs": []}
    outbound = engine._outbound_messages()[-1]
    assert outbound["_gemini"] == {"text_sig": "c2ln", "call_sigs": []}
    assert "ts" not in outbound  # display sidecars still stripped


def test_switch_model_appends_notice_only_midsession(tmp_path):
    engine, _ = _engine(tmp_path, [_text_turn("ok")])
    # Fresh session: first bind is silent.
    assert engine.switch_model("zai:glm-5.2") is None
    assert engine.model == "zai:glm-5.2"
    _collect(engine, "hi")
    # Same model: no-op.
    assert engine.switch_model("zai:glm-5.2") is None
    # Real mid-session switch: persisted marker with the matrix label.
    text = engine.switch_model("kimi:kimi-k2.6")
    assert "Kimi K2.6" in text and engine.model == "kimi:kimi-k2.6"
    notice = engine.messages[-1]
    assert notice["role"] == "notice" and notice["kind"] == "model_switch"
    assert all(m.get("role") != "notice" for m in engine._outbound_messages())


def test_switch_model_warns_when_images_meet_text_only_model(tmp_path):
    class NoVisionProvider(ScriptedProvider):
        def capabilities(self, model):
            return ModelCapabilities(vision=False)

    engine, _ = _engine(tmp_path, [_text_turn("ok")])
    engine.provider = NoVisionProvider([_text_turn("ok")])
    engine.messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ],
        }
    )
    text = engine.switch_model("zai:glm-5.2")
    assert "images" in text  # degradation is called out in the marker


def test_outbound_replaces_images_for_non_vision_models(tmp_path):
    class NoVisionProvider(ScriptedProvider):
        def capabilities(self, model):
            return ModelCapabilities(vision=False)

    engine, _ = _engine(tmp_path, [_text_turn("ok")])
    engine.provider = NoVisionProvider([_text_turn("ok")])
    engine.messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ],
        }
    )
    parts = engine._outbound_messages()[-1]["content"]
    assert all(p["type"] != "image_url" for p in parts)
    assert "not viewable" in parts[-1]["text"]
    assert engine.messages[-1]["content"][1]["type"] == "image_url"  # history untouched


def test_tool_results_are_bounded_before_entering_history():
    """A tool result is appended to history and then re-sent on EVERY later round trip,
    so its size is paid once per remaining turn. The engine used to enforce no bound at
    all — the ceiling was whatever each tool chose, and `run_shell` alone allows 20,000
    chars, more than the entire system prompt plus tool catalogue."""
    from coworker.engine import (
        _TOOL_RESULT_MAX_CHARS,
        _clip_tool_result,
        _tool_result_message,
    )
    from coworker.providers import ToolCall

    assert _clip_tool_result("small") == "small"
    at_cap = "y" * _TOOL_RESULT_MAX_CHARS
    assert _clip_tool_result(at_cap) == at_cap  # the cap itself is not truncation

    runaway = "HEAD-MATTERS" + ("a" * 40_000) + "TAIL-exit_code=0"
    clipped = _clip_tool_result(runaway)
    assert len(clipped) < len(runaway)
    # Head AND tail survive: output is front-loaded, but exit codes, totals and error
    # summaries live at the end — dropping those is what makes a truncation misleading.
    assert clipped.startswith("HEAD-MATTERS")
    assert clipped.endswith("TAIL-exit_code=0")
    # The marker is written FOR THE MODEL: a silent truncation reads as "that's all there
    # was" and sends it off reasoning about output it only half saw.
    assert "chars omitted" in clipped and "NOT the whole output" in clipped
    assert "Re-run narrowed" in clipped

    # The cap applies to dict results too (they are json.dumps'd on the way in).
    message = _tool_result_message(
        ToolCall(id="c1", name="run_shell", arguments={}), {"output": "z" * 40_000}
    )
    assert len(message["content"]) < 40_000
    assert message["role"] == "tool" and message["tool_call_id"] == "c1"


def test_token_gate_stops_a_runaway_turn_and_says_what_it_cost(tmp_path):
    """`max_iterations` counts ROUNDS, so it cannot tell a turn that read four small
    files from one that read four 40k-line logs — it stops both at the same place. The
    token gate is the same backstop in the unit the bill is actually denominated in.

    Both stops now report iterations AND tokens: naming only the mechanism left the user
    puzzling instead of replying, and an idle session is the expensive kind (the provider
    cache goes cold, so resuming re-bills the whole prompt at full price)."""
    from coworker.providers.base import TokenUsage

    turn = _tool_turn("list_files", {})
    turn.usage = TokenUsage(input=900, output=100)  # 1,000 billed per round
    engine, provider = _engine(tmp_path, [turn], loop=True, max_iterations=100)
    engine.max_turn_tokens = 3_000
    end = _collect(engine, "loop forever")[-1]

    assert end.type == EventType.TURN_END
    assert end.data["status"] == "max_tokens_exceeded"
    assert end.data["tokens"] >= 3_000
    assert end.data["iterations"] < 100  # the token gate tripped first, not the round one
    assert provider.calls == 3  # 3 x 1,000 reaches the 3,000 ceiling
    assert set(end.data) >= {"status", "iterations", "tokens"}


def test_round_gate_also_reports_the_token_cost(tmp_path):
    """The iteration stop carries the same two numbers, so the surfaces have one story."""
    from coworker.providers.base import TokenUsage

    turn = _tool_turn("list_files", {})
    turn.usage = TokenUsage(input=40, output=10)
    engine, _ = _engine(tmp_path, [turn], loop=True, max_iterations=3)
    end = _collect(engine, "loop forever")[-1]

    assert end.data["status"] == "max_iterations_exceeded"
    assert end.data["iterations"] == 3 and end.data["tokens"] == 150


def test_token_gate_is_off_by_default(tmp_path):
    """A ceiling that fires on legitimate long work is worse than no ceiling — the
    default stays 0 and only `max_iterations` guards, exactly as before."""
    from coworker.config import Config

    assert Config().max_turn_tokens == 0
    engine, _ = _engine(tmp_path, [_text_turn("hi")])
    assert engine.max_turn_tokens == 0


def test_leaked_tool_call_ends_the_turn_as_a_retriable_error(tmp_path):
    """A tool call the endpoint couldn't parse must not pass as an answer. Ending "completed"
    made a half-written call indistinguishable from the model deciding it was done — the user
    saw narration trailing off into stray tags (owner report 2026-07-26, qwen3.5-9b on LM
    Studio). It ends on the error path so the GUI offers Retry; the drift is probabilistic, so
    retrying the same model usually works."""
    leaked = "Let me read the key files.\n<tool_call>\n<function=nope_not_a_tool>\n<parameter="
    engine, _ = _engine(tmp_path, [_text_turn(leaked)])
    events = _collect(engine, "explore the codebase")

    assert EventType.ERROR in _types(events)
    assert EventType.TURN_END not in _types(events)
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["error_type"] == "UnparsedToolCall"
    assert "couldn't parse" in err.data["error"]
    # Persisted as an error notice, which is what unlocks retry().
    assert engine.messages[-1] == {
        **engine.messages[-1],
        "role": "notice",
        "kind": "error",
    }
    assert engine._tail_is_retriable_error() is True


def test_ordinary_text_answer_still_completes(tmp_path):
    """Guard the other side: prose that merely mentions tool syntax inside code fences is a
    real answer and must still complete normally."""
    engine, _ = _engine(
        tmp_path,
        [_text_turn("Qwen writes calls like:\n```\n<tool_call><function=x>\n```\nThat's it.")],
    )
    events = _collect(engine, "how does qwen format tool calls?")
    assert EventType.ERROR not in _types(events)
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == "completed"
