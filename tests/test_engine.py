"""P2 gate tests — turn engine + event bus (scripted provider, no network)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import aisuite as ai
import pytest
from coworker.engine import (
    _FIRST_CHUNK_TIMEOUT_ENV,
    _LONG_ATTEMPT_ENV,
    _RETRY_AFTER_CAP,
    _RETRY_JITTER,
    _TURN_RETRY_CAP,
    ApprovalOutcome,
    FirstChunkTimeout,
    PermissionRequest,
    StreamBridgeError,
    TurnEngine,
    _first_chunk_timeout,
    _model_retries,
    _retry_delay,
)
from coworker.events import EventType
from coworker.permissions import PermissionEngine
from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    OpenAIProvider,
    ProviderClient,
    StreamChunk,
    ToolCall,
)
from coworker.providers.errors import is_transient_model_error
from coworker.tools import ToolRegistry


def _text_turn(text):
    return AssistantTurn(text=text, finish_reason="stop")


def _tool_turn(name, args, call_id="call_1"):
    return AssistantTurn(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        finish_reason="tool_calls",
    )


class ScriptedProvider(ProviderClient):
    """Returns queued AssistantTurns; streams via the base default (one final chunk). A
    queued Exception is raised instead, so a script can stage a provider failure."""

    def __init__(self, turns, *, loop=False):
        self._turns = list(turns)
        self._loop = loop
        self.calls = 0

    def complete(self, *, model, messages, tools=None, **settings):
        self.calls += 1
        turn = self._turns[0] if self._loop else self._turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        return turn

    def capabilities(self, model):
        return ModelCapabilities()


def _engine(
    tmp_path,
    turns,
    *,
    approver=None,
    loop=False,
    max_iterations=12,
    retries=0,
    finish_reasons_seen=True,
    messages=None,
):
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
        messages=messages,
    )
    # Automatic retry is off unless a test asks for it, and its backoff never really
    # waits: `retry_sleep` is the injection seam, and the recorded delays are what the
    # schedule/Retry-After tests assert on. Still honours Stop, like the real one.
    engine.model_retries = retries
    engine.slept = []

    async def _instant(delay):
        engine.slept.append(delay)
        return not engine._cancel.is_set()

    engine.retry_sleep = _instant
    # Stands in for "this model has already been watched reporting finish reasons in this
    # session" — the gate `truncated` has to pass before it means anything (a backend that
    # never sends the field must not have its ordinary replies read as severed streams).
    # The gate's own behaviour is driven through real rounds in its dedicated tests.
    if finish_reasons_seen:
        engine._finish_reason_seen.add(engine.model)
    return engine, provider


def _default_engine(tmp_path):
    """A default-wired engine — nothing overridden — for the pieces whose whole point is
    what `_engine()` above replaces (the constructor's own wiring, the real backoff)."""
    return TurnEngine(
        provider=ScriptedProvider([]),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )


def _collect(engine, user_input):
    async def _run():
        return [ev async for ev in engine.run(user_input)]

    return asyncio.run(_run())


async def _drain(stream):
    return [ev async for ev in stream]


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


def _assistant_call(call_id, name, arguments):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


def _read_engine(tmp_path, messages):
    return TurnEngine(
        provider=object(),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="x",
        messages=messages,
    )


def test_repeated_identical_read_keeps_only_the_newest(tmp_path):
    """Three reads of one file left three full copies, re-sent on every later call."""
    from coworker.engine import _SUPERSEDE_MIN_CHARS, _TOOL_RESULT_MAX_CHARS

    # Results are clipped to the cap on the way INTO history, so the floor must sit below
    # it or a read clipped at the cap — the typical big read — could never be superseded.
    assert _SUPERSEDE_MIN_CHARS < _TOOL_RESULT_MAX_CHARS

    big = "x" * 3_000
    eng = _read_engine(
        tmp_path,
        [
            {"role": "user", "content": "check it"},
            _assistant_call("a", "read_file", '{"path": "app.py"}'),
            {"role": "tool", "tool_call_id": "a", "content": big},
            _assistant_call("b", "read_file", '{"path": "other.py"}'),
            {"role": "tool", "tool_call_id": "b", "content": big},
            _assistant_call("c", "read_file", '{"path": "app.py"}'),
            {"role": "tool", "tool_call_id": "c", "content": big},
        ],
    )
    out = eng._outbound_messages()
    sent = {m["tool_call_id"]: m["content"] for m in out if m.get("role") == "tool"}
    assert sent["a"].startswith("[superseded")  # same args, read again later
    assert sent["b"] == big  # a different file — untouched
    assert sent["c"] == big  # the newest copy survives intact
    # Outbound-only: the canonical history still holds every copy.
    assert eng.messages[2]["content"] == big


def test_supersession_leaves_small_reads_and_shell_alone(tmp_path):
    """Rewriting history costs one cache miss — only worth it for a big copy, and never
    for `run_shell`, where two identical commands can straddle the change being checked."""
    small, big = "y" * 100, "z" * 3_000
    eng = _read_engine(
        tmp_path,
        [
            {"role": "user", "content": "go"},
            _assistant_call("a", "read_file", '{"path": "tiny.py"}'),
            {"role": "tool", "tool_call_id": "a", "content": small},
            _assistant_call("b", "read_file", '{"path": "tiny.py"}'),
            {"role": "tool", "tool_call_id": "b", "content": small},
            _assistant_call("c", "run_shell", '{"command": "pytest -q"}'),
            {"role": "tool", "tool_call_id": "c", "content": big},
            _assistant_call("d", "run_shell", '{"command": "pytest -q"}'),
            {"role": "tool", "tool_call_id": "d", "content": big},
        ],
    )
    sent = {
        m["tool_call_id"]: m["content"]
        for m in eng._outbound_messages()
        if m.get("role") == "tool"
    }
    assert sent["a"] == small  # under the size floor: not worth the re-cache
    assert sent["c"] == big  # the "before" half of a before/after comparison


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


# -- turns that ended badly (owner report 2026-09-18) -------------------------------


def _severed_turn(reasoning="Write file to reports/summary.md", **kw):
    """What a cut-off stream actually leaves behind: thinking text, no answer, no tool
    call, no usage frame, no finish reason — plus `truncated`, set by the provider that
    noticed the stream never said it was done."""
    return AssistantTurn(text=None, reasoning=reasoning, truncated=True, **kw)


def _notices(engine):
    return [m for m in engine.messages if m.get("role") == "notice"]


def test_severed_stream_is_reported_like_a_provider_failure(tmp_path):
    """The bug this group guards: the stream was cut mid-thought, the turn held nothing,
    and the engine ended it "completed". The GUI then showed thinking that stopped on
    "Write file to …" and went quiet, so the user read a dead turn as a finished one. An
    answerless turn must report exactly like a provider failure — same ERROR event, same
    retriable notice, no TURN_END — so the Retry button is offered. Automatic retry is off
    here, so what's under test is the shape of the REPORT; the retry group below drives
    the same failure with the budget switched on."""
    engine, _ = _engine(tmp_path, [_severed_turn()])
    events = _collect(engine, "write the summary")

    assert EventType.ERROR in _types(events)
    assert EventType.TURN_END not in _types(events)
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["error_type"] == "TurnAborted"
    assert err.data["reason"] == "no_finish"
    assert "cut off" in err.data["error"]

    notice = engine.messages[-1]
    assert notice["role"] == "notice" and notice["kind"] == "turn_aborted"
    assert notice["reason"] == "no_finish"
    assert notice["text"] == err.data["error"]
    assert engine._tail_is_retriable_error() is True

    # The thinking the user watched is the only thing this turn produced, so it stays —
    # ahead of the notice, which is the order the transcript reads in. It is marked
    # `aborted`, and that mark takes the WHOLE message out of the provider feed: a blank
    # assistant turn replayed on every later call is exactly what must not happen.
    aborted = engine.messages[-2]
    assert aborted["role"] == "assistant" and aborted["content"] == ""
    assert aborted["reasoning"].startswith("Write file to")
    assert aborted["aborted"] is True and not aborted.get("tool_calls")
    assert not any(m.get("role") == "assistant" for m in engine._outbound_messages())


def test_empty_turn_reason_separates_the_length_limit_from_a_real_empty_answer(tmp_path):
    """Same ending, three different causes — and the user can only act on the right one
    if the notice says which. `length` means "ask for less"; `empty` means the model
    genuinely answered with nothing (and `no_finish` above means it never got to)."""
    # Out of output budget: the provider said so, so `truncated` never enters into it.
    engine, _ = _engine(tmp_path, [AssistantTurn(text="", finish_reason="length")])
    events = _collect(engine, "write the summary")
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["reason"] == "length"
    assert "length limit" in err.data["error"]
    assert engine.messages[-1]["reason"] == "length"

    # A clean stop that produced nothing at all.
    engine, _ = _engine(tmp_path, [AssistantTurn(text="   ", finish_reason="stop")])
    events = _collect(engine, "write the summary")
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["reason"] == "empty"
    assert "empty response" in err.data["error"]
    assert engine.messages[-1]["reason"] == "empty"


def test_cut_off_answer_keeps_its_text_and_only_warns(tmp_path):
    """The other half of the split: text DID arrive before the cut. The user has already
    read it, so the turn still completes and the message stays — the truncation is a
    warning appended after it, not a failure, and it must not be retriable."""
    engine, _ = _engine(
        tmp_path,
        [AssistantTurn(text="Here are the first three findings:", truncated=True)],
    )
    events = _collect(engine, "summarize the findings")

    assert EventType.ERROR not in _types(events)
    assert _types(events)[-2:] == [EventType.TURN_TRUNCATED, EventType.TURN_END]
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == "completed"
    warn = next(ev for ev in events if ev.type == EventType.TURN_TRUNCATED)
    assert warn.data["reason"] == "no_finish"

    assert engine.messages[-2]["content"] == "Here are the first three findings:"
    notice = engine.messages[-1]
    assert notice["kind"] == "turn_truncated" and notice["reason"] == "no_finish"
    assert notice["text"].startswith("The response may be incomplete")
    # A completed turn is not a failed one — Retry must stay off.
    assert engine._tail_is_retriable_error() is False


def test_cut_off_answer_names_the_length_limit_when_the_provider_does(tmp_path):
    engine, _ = _engine(
        tmp_path, [AssistantTurn(text="Here are the first three", finish_reason="length")]
    )
    events = _collect(engine, "summarize the findings")
    warn = next(ev for ev in events if ev.type == EventType.TURN_TRUNCATED)
    assert warn.data["reason"] == "length"
    assert "output length limit" in engine.messages[-1]["text"]


def test_ordinary_turns_gain_no_new_notice_and_no_new_event(tmp_path):
    """The lockdown for everything above: a normal answer and a normal tool turn must
    behave byte-for-byte as they did before the classification existed."""
    engine, _ = _engine(tmp_path, [_text_turn("all done")])
    events = _collect(engine, "hi")
    assert _types(events) == [
        EventType.TURN_START,
        EventType.ASSISTANT_MESSAGE,
        EventType.TURN_END,
    ]
    assert _notices(engine) == []

    engine, _ = _engine(
        tmp_path,
        [_tool_turn("list_files", {"path": "."}), _text_turn("there you go")],
    )
    events = _collect(engine, "what's here?")
    assert EventType.TURN_TRUNCATED not in _types(events)
    assert EventType.ERROR not in _types(events)
    assert _notices(engine) == []


def test_finish_reason_sidecars_persist_but_never_reach_the_provider(tmp_path):
    """`finish_reason`/`truncated` are diagnostic sidecars: the record has to keep them
    (dropping them is what made the 2026-09-18 report unexplainable from the transcript
    alone), and no provider may ever see them — openai chat rejects unknown message keys."""
    engine, _ = _engine(tmp_path, [AssistantTurn(text="ok", finish_reason="stop")])
    _collect(engine, "hi")
    persisted = engine.messages[-1]
    assert persisted["finish_reason"] == "stop" and "truncated" not in persisted
    outbound = engine._outbound_messages()[-1]
    assert "finish_reason" not in outbound and "truncated" not in outbound
    assert outbound["content"] == "ok"

    engine, _ = _engine(tmp_path, [AssistantTurn(text="partial", truncated=True)])
    _collect(engine, "hi")
    persisted = next(m for m in engine.messages if m.get("role") == "assistant")
    assert persisted["truncated"] is True and "finish_reason" not in persisted
    assert not any(
        "truncated" in m or "finish_reason" in m for m in engine._outbound_messages()
    )


# -- automatic retry of a dead model call -------------------------------------------


class _Transient(Exception):
    """Stands in for openai's APIConnectionError & co: the classifier matches on the
    exception's NAME, so no vendor SDK has to be importable here."""


class APIConnectionError(_Transient):
    pass


class AuthenticationError(Exception):
    def __init__(self):
        super().__init__("Error code: 401 - {'error': {'message': 'Incorrect API key'}}")
        self.status_code = 401


def _retry_notices(engine):
    return [m for m in _notices(engine) if m["kind"] == "turn_retry"]


def test_severed_stream_is_retried_and_the_second_attempt_answers(tmp_path):
    """A cut stream is not a decision the model made — it's a call that never landed, so
    the engine re-runs it instead of asking the user to click Retry for it. The recovered
    turn ends normally, with only the marker to say a retry happened."""
    engine, provider = _engine(
        tmp_path, [_severed_turn(), _text_turn("wrote the summary")], retries=2
    )
    events = _collect(engine, "write the summary")

    assert provider.calls == 2
    assert EventType.ERROR not in _types(events)
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == "completed"
    # A retry re-runs the SAME round — it must not spend one of the turn's iterations.
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["iterations"] == 1

    retry = next(ev for ev in events if ev.type == EventType.TURN_RETRY)
    assert (retry.data["reason"], retry.data["attempt"], retry.data["max"]) == ("no_finish", 1, 2)
    marker = _retry_notices(engine)
    assert len(marker) == 1 and marker[0]["reason"] == "no_finish"
    assert not any(m["kind"] == "turn_aborted" for m in _notices(engine))
    # …and nothing of the abandoned attempt survives into the history the model sees.
    assert [m["content"] for m in engine.messages if m["role"] == "assistant"] == [
        "wrote the summary"
    ]


def test_transient_provider_failure_is_retried(tmp_path):
    """Same treatment for a call that died on the wire before any turn came back."""
    engine, provider = _engine(
        tmp_path, [APIConnectionError("connection reset"), _text_turn("recovered")], retries=2
    )
    events = _collect(engine, "write the summary")

    assert provider.calls == 2
    assert EventType.ERROR not in _types(events)
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == "completed"
    assert [n["reason"] for n in _retry_notices(engine)] == ["transient"]
    assert engine.slept == [pytest.approx(2.0, rel=_RETRY_JITTER)]


def test_retries_run_out_and_the_turn_reports_how_many_it_tried(tmp_path):
    """The budget is bounded. Once it's gone the turn ends exactly as it would have with
    no retry at all — provider-failure shape, retriable notice — and the copy admits the
    machine already tried, so the user isn't invited to repeat a lost cause blindly."""
    engine, provider = _engine(tmp_path, [_severed_turn()], loop=True, retries=2)
    events = _collect(engine, "write the summary")

    assert provider.calls == 3  # the original attempt plus two retries
    assert [n["reason"] for n in _retry_notices(engine)] == ["no_finish", "no_finish"]
    assert [n["attempt"] for n in _retry_notices(engine)] == [1, 2]

    assert EventType.TURN_END not in _types(events)
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["error_type"] == "TurnAborted" and err.data["retries"] == 2
    assert "2 retries" in err.data["error"]
    aborted = engine.messages[-1]
    assert aborted["kind"] == "turn_aborted" and aborted["retries"] == 2
    assert engine._tail_is_retriable_error() is True
    # Three dead attempts, ONE kept message: only the attempt that finally gave up leaves
    # its thinking behind, and even that never reaches a provider.
    kept = [m for m in engine.messages if m.get("role") == "assistant"]
    assert len(kept) == 1 and kept[0]["aborted"] is True
    assert not any(m.get("role") == "assistant" for m in engine._outbound_messages())
    assert engine.slept == [
        pytest.approx(2.0, rel=_RETRY_JITTER),
        pytest.approx(6.0, rel=_RETRY_JITTER),
    ]


def test_a_permanent_failure_is_never_retried(tmp_path):
    """A bad key answers the same way three times over. Retrying it only makes the user
    wait eight seconds for the diagnosis they could have had immediately."""
    engine, provider = _engine(tmp_path, [AuthenticationError()], loop=True, retries=2)
    events = _collect(engine, "write the summary")

    assert provider.calls == 1
    assert _retry_notices(engine) == [] and engine.slept == []
    assert [n["kind"] for n in _notices(engine)] == ["error"]
    assert next(ev for ev in events if ev.type == EventType.ERROR).data["error_type"] == (
        "AuthenticationError"
    )


def test_hitting_the_length_limit_is_never_retried(tmp_path):
    """Re-running the same prompt meets the same ceiling — the budget would buy nothing
    but two more waits before the identical sentence."""
    engine, provider = _engine(
        tmp_path, [AssistantTurn(text="", finish_reason="length")], loop=True, retries=2
    )
    events = _collect(engine, "write the summary")

    assert provider.calls == 1
    assert _retry_notices(engine) == []
    assert next(ev for ev in events if ev.type == EventType.ERROR).data["reason"] == "length"


def test_stop_during_the_backoff_cancels_instead_of_retrying(tmp_path):
    """The pause between attempts is dead time the user must be able to escape — the real
    `retry_sleep` waits on the cancel event for exactly this reason."""
    engine, provider = _engine(tmp_path, [_severed_turn()], loop=True, retries=2)

    async def _stop_during_backoff(delay):
        engine.request_interrupt()
        return False

    engine.retry_sleep = _stop_during_backoff
    events = _collect(engine, "write the summary")

    assert provider.calls == 1  # the second attempt never went out
    assert EventType.INTERRUPTED in _types(events)
    assert EventType.ERROR not in _types(events)
    assert engine.messages[-1]["kind"] == "interrupted"


def test_a_tool_heavy_turn_cannot_retry_forever(tmp_path):
    """The per-call budget renews every round, so a long agentic turn could pay it over
    and over. One cap covers the whole turn."""
    script = []
    for _ in range(_TURN_RETRY_CAP + 1):
        script += [_severed_turn(), _tool_turn("list_files", {"path": "."})]
    engine, provider = _engine(tmp_path, script, retries=1, max_iterations=20)
    events = _collect(engine, "explore everything")

    assert len(_retry_notices(engine)) == _TURN_RETRY_CAP
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["error_type"] == "TurnAborted"
    # The cap bit on the round after the budget ran out, not on the last scripted turn.
    assert provider.calls == _TURN_RETRY_CAP * 2 + 1


def test_the_abandoned_attempt_never_reaches_the_next_call(tmp_path):
    """Context hygiene: what the provider is handed on the retry must be byte-identical
    to what it was handed on the attempt that died."""
    engine, provider = _engine(
        tmp_path, [_severed_turn(), _text_turn("recovered")], retries=2
    )
    _collect(engine, "write the summary")
    assert not any(
        m.get("role") == "assistant" and not (m.get("content") or "").strip()
        for m in engine._outbound_messages()
    )
    # The `turn_retry` marker is display-only too — notices never leave the machine.
    assert all(m["role"] != "notice" for m in engine._outbound_messages())


def test_retry_budget_default_and_env_override(monkeypatch):
    """Two automatic retries by default; `OPENWORKER_MODEL_RETRIES` moves it, including
    all the way to 0 ("just ask me"). Garbage falls back rather than disabling the bound."""
    monkeypatch.delenv("OPENWORKER_MODEL_RETRIES", raising=False)
    assert _model_retries() == 2
    monkeypatch.setenv("OPENWORKER_MODEL_RETRIES", "0")
    assert _model_retries() == 0
    monkeypatch.setenv("OPENWORKER_MODEL_RETRIES", "3")
    assert _model_retries() == 3
    # Clamped to the turn-wide cap: a budget the turn can never spend would only show up
    # as a lie in the "(1/9)" counter.
    monkeypatch.setenv("OPENWORKER_MODEL_RETRIES", "9")
    assert _model_retries() == _TURN_RETRY_CAP
    for junk in ("", "  ", "lots", "-1"):
        monkeypatch.setenv("OPENWORKER_MODEL_RETRIES", junk)
        assert _model_retries() == 2, junk


def test_retry_after_header_wins_over_the_schedule_but_is_capped():
    """A vendor knows when its own queue drains, so its Retry-After beats our backoff —
    but a five-minute hint would be indistinguishable from a hang, so it's capped."""
    assert _retry_delay(1, retry_after=0.5) == 0.5
    assert _retry_delay(1, retry_after=600.0) == _RETRY_AFTER_CAP
    # "Retry immediately" against a backend that just refused us is how a bounded retry
    # becomes a hot loop, so a non-positive hint falls back to the schedule.
    for hint in (0.0, -3.0):
        assert _retry_delay(1, retry_after=hint) == pytest.approx(2.0, rel=_RETRY_JITTER)
    assert _retry_delay(1) == pytest.approx(2.0, rel=_RETRY_JITTER)
    assert _retry_delay(2) == pytest.approx(6.0, rel=_RETRY_JITTER)
    assert _retry_delay(9) == pytest.approx(6.0, rel=_RETRY_JITTER)  # past the schedule


def test_the_configured_budget_is_wired_through_the_constructor(tmp_path, monkeypatch):
    """`_engine()` overrides `model_retries` for determinism, which would hide a broken
    constructor forever — so drive the real wiring once, end to end."""
    monkeypatch.setenv("OPENWORKER_MODEL_RETRIES", "1")
    engine = _default_engine(tmp_path)
    assert engine.model_retries == 1
    assert engine.retry_sleep == engine._sleep_unless_stopped
    assert engine.clock is time.monotonic


# -- the backoff wait itself ---------------------------------------------------------


def test_backoff_returns_true_when_it_simply_elapses(tmp_path):
    engine = _default_engine(tmp_path)
    assert asyncio.run(engine._sleep_unless_stopped(0.01)) is True
    # A non-positive delay is still a cancellation checkpoint, not a no-op.
    assert asyncio.run(engine._sleep_unless_stopped(0)) is True


def test_backoff_reports_a_stop_pressed_during_it(tmp_path):
    """The wait IS the cancel event's wait, so Stop lands at once instead of six seconds
    later. Both orders count: pressed during the pause, and pressed before it started."""
    engine = _default_engine(tmp_path)

    async def _stop_midway():
        async def _press():
            await asyncio.sleep(0.01)
            engine.request_interrupt()

        asyncio.get_running_loop().create_task(_press())
        return await engine._sleep_unless_stopped(30.0)

    assert asyncio.run(_stop_midway()) is False

    already = _default_engine(tmp_path)
    already.request_interrupt()
    assert asyncio.run(already._sleep_unless_stopped(30.0)) is False
    assert asyncio.run(already._sleep_unless_stopped(0)) is False


def test_backoff_lets_an_outer_cancellation_through(tmp_path):
    """Cancelling the turn's task must kill the backoff too — swallowing CancelledError
    here would leave a stopped session sitting out a six-second wait it can't escape."""
    engine = _default_engine(tmp_path)

    async def _run():
        task = asyncio.ensure_future(engine._sleep_unless_stopped(30.0))
        await asyncio.sleep(0.01)
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())


# -- steering across a dead turn -----------------------------------------------------


def _roles(engine):
    return [
        (m.get("role"), m.get("kind") or (m.get("content") or ""))
        for m in engine.messages
        if m.get("role") != "system"
    ]


def test_steering_queued_during_a_dead_turn_lands_with_that_turn(tmp_path):
    """`queue_steering` is how a channel message (WeChat/iLink, a lead steering a worker,
    a self-wake) reaches a running turn. If the abort path returns without draining it,
    the message is neither in history nor in the dead-letter box: it silently reappears in
    the MIDDLE of the next turn, after that turn's first answer. It has to land right
    after the turn it was aimed at, exactly as it does when the turn ends normally — and
    BEFORE the notice, so the notice stays the tail and Retry stays on offer."""
    engine, _ = _engine(tmp_path, [_severed_turn()])
    engine.queue_steering("actually, use last quarter's numbers")
    _collect(engine, "write the summary")

    assert _roles(engine) == [
        ("user", "write the summary"),
        ("assistant", ""),  # the thinking that was all this turn produced
        ("user", "actually, use last quarter's numbers"),
        ("notice", "turn_aborted"),
    ]
    assert engine._tail_is_retriable_error() is True


def test_a_manual_retry_after_an_abort_carries_the_steering_once(tmp_path):
    """…and the point of that ordering: pressing Retry re-runs the dead turn WITH the
    correction the user sent while it was dying — once, not twice."""
    engine, provider = _engine(
        tmp_path, [_severed_turn(), _text_turn("used Q3 as asked")]
    )
    engine.queue_steering("actually, use last quarter's numbers")
    _collect(engine, "write the summary")

    outbound = engine._outbound_messages()
    steering = [m for m in outbound if m.get("content") == "actually, use last quarter's numbers"]
    assert len(steering) == 1

    events = asyncio.run(_drain(engine.retry()))
    assert provider.calls == 2
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == (
        "completed"
    )
    assert (
        len(
            [
                m
                for m in engine._outbound_messages()
                if m.get("content") == "actually, use last quarter's numbers"
            ]
        )
        == 1
    )


def test_steering_queued_during_a_retried_turn_reaches_the_retry(tmp_path):
    """Corrections typed while "retrying…" is on screen are aimed at the attempt about to
    go out, not at some later turn — so they have to be in its prompt."""
    engine, provider = _engine(
        tmp_path, [_severed_turn(), _text_turn("used Q3")], retries=2
    )
    seen: list[list[dict]] = []
    original = provider.complete

    def _recording(**kwargs):
        seen.append([dict(m) for m in kwargs["messages"]])
        return original(**kwargs)

    provider.complete = _recording
    engine.queue_steering("actually, use last quarter's numbers")
    _collect(engine, "write the summary")

    assert len(seen) == 2
    assert not any("last quarter" in str(m.get("content")) for m in seen[0])
    assert any("last quarter" in str(m.get("content")) for m in seen[1])


# -- the truncation gate -------------------------------------------------------------


def test_a_backend_that_never_reports_finish_reasons_is_not_accused_of_cutting_off(
    tmp_path,
):
    """`truncated` only means "severed" for a backend that otherwise SAYS when it's done.
    Trusting it blindly would put a "may be incomplete" warning under every single reply
    from a compat endpoint that just doesn't send the field."""
    engine, _ = _engine(
        tmp_path,
        [AssistantTurn(text="here you go", truncated=True)],
        finish_reasons_seen=False,
    )
    events = _collect(engine, "hi")
    assert EventType.TURN_TRUNCATED not in _types(events)
    assert _notices(engine) == []


def test_once_a_model_has_reported_a_finish_reason_truncation_is_believed(tmp_path):
    """…and the moment that same model IS seen reporting one, its silence starts meaning
    something. Driven through real rounds: round one reports `tool_calls`, round two is
    cut off."""
    engine, _ = _engine(
        tmp_path,
        [
            _tool_turn("list_files", {"path": "."}),
            AssistantTurn(text="here you go", truncated=True),
        ],
        finish_reasons_seen=False,
    )
    events = _collect(engine, "look around")
    warn = next(ev for ev in events if ev.type == EventType.TURN_TRUNCATED)
    assert warn.data["reason"] == "no_finish"


def test_the_gate_is_per_model_so_a_switch_starts_the_observation_over(tmp_path):
    """A model that reports finish reasons says nothing about the next one — the whole
    point is watching THIS backend behave."""
    engine, _ = _engine(
        tmp_path, [AssistantTurn(text="one", finish_reason="stop")], retries=0
    )
    _collect(engine, "hi")
    assert engine._trusts_truncation() is True
    engine.switch_model("zai:glm-5.2")
    assert engine._trusts_truncation() is False


def test_the_gate_is_recovered_from_the_persisted_history(tmp_path):
    """Learned once, remembered: `finish_reason` is a persisted sidecar, so a resumed
    session — or a restart, or an evicted-and-rebuilt engine — starts out already knowing
    this backend reports one. Without that, the first genuinely severed stream after every
    restart would be filed as "the model returned an empty response": wrong on the facts,
    and worth only the single courtesy retry an empty answer gets."""
    history = [
        {"role": "user", "content": "earlier"},
        {
            "role": "assistant",
            "content": "earlier answer",
            "finish_reason": "stop",
            "usage": {"model": "gpt-5.5", "input": 10, "output": 2},
        },
    ]
    engine, _ = _engine(
        tmp_path, [_severed_turn()], finish_reasons_seen=False, messages=history
    )
    events = _collect(engine, "write the summary")
    assert next(ev for ev in events if ev.type == EventType.ERROR).data["reason"] == (
        "no_finish"
    )


def test_history_from_another_model_does_not_vouch_for_this_one(tmp_path):
    """The record is keyed by the model that produced it — a different model's good
    behaviour says nothing about the one in play now."""
    history = [
        {
            "role": "assistant",
            "content": "earlier answer",
            "finish_reason": "stop",
            "usage": {"model": "zai:glm-5.2", "input": 10, "output": 2},
        }
    ]
    engine, _ = _engine(
        tmp_path, [_severed_turn()], finish_reasons_seen=False, messages=history
    )
    assert engine._trusts_truncation() is False
    events = _collect(engine, "write the summary")
    assert next(ev for ev in events if ev.type == EventType.ERROR).data["reason"] == "empty"


def test_history_without_a_usage_tag_counts_for_the_current_model(tmp_path):
    """Compat endpoints that report no usage still report finish reasons. Those messages
    carry no model tag, so they're attributed to the engine's own model — which is what
    they were for every session that never switched."""
    history = [{"role": "assistant", "content": "earlier", "finish_reason": "stop"}]
    engine, _ = _engine(
        tmp_path, [_severed_turn()], finish_reasons_seen=False, messages=history
    )
    assert engine._trusts_truncation() is True


def test_an_untagged_message_from_before_a_switch_vouches_for_nobody(tmp_path):
    """The one guess that must not be made. "Reports a finish reason but no usage" is the
    exact shape of the compat endpoints this gate exists for, so an untagged message is
    ordinary — and crediting one to whatever model happens to be loaded now would vouch
    for a backend nobody has ever watched, which is the false positive the gate exists to
    prevent."""
    history = [
        # Endpoint A: reports finish reasons, reports no usage, so carries no model tag.
        {"role": "assistant", "content": "answer from A", "finish_reason": "stop"},
        {"role": "notice", "kind": "model_switch", "text": "Model switched to B"},
    ]
    engine, _ = _engine(
        tmp_path, [_severed_turn()], finish_reasons_seen=False, messages=history
    )
    assert engine._finish_reason_seen == set()
    assert engine._trusts_truncation() is False


def test_an_untagged_message_from_after_the_last_switch_does_count(tmp_path):
    """…and the other side: once the switch is behind it, an untagged message can only
    have come from the model in play now."""
    history = [
        {"role": "assistant", "content": "answer from A", "finish_reason": "stop"},
        {"role": "notice", "kind": "model_switch", "text": "Model switched to B"},
        {"role": "assistant", "content": "answer from B", "finish_reason": "stop"},
    ]
    engine, _ = _engine(
        tmp_path, [_severed_turn()], finish_reasons_seen=False, messages=history
    )
    assert engine._finish_reason_seen == {"gpt-5.5"}
    assert engine._trusts_truncation() is True


def test_a_tagged_message_counts_wherever_it_sits(tmp_path):
    """A `usage.model` tag names its own producer, so it needs no help from position —
    including from before a switch."""
    history = [
        {
            "role": "assistant",
            "content": "answer from A",
            "finish_reason": "stop",
            "usage": {"model": "zai:glm-5.2", "input": 1, "output": 1},
        },
        {"role": "notice", "kind": "model_switch", "text": "Model switched to B"},
    ]
    engine, _ = _engine(
        tmp_path, [_severed_turn()], finish_reasons_seen=False, messages=history
    )
    assert engine._finish_reason_seen == {"zai:glm-5.2"}
    assert engine._trusts_truncation() is False


def test_an_unproven_backend_still_reports_an_empty_turn(tmp_path):
    """Degraded, not silent: without the gate the reason is `empty` rather than
    `no_finish`, but the turn is still refused instead of passing as completed."""
    engine, _ = _engine(tmp_path, [_severed_turn()], finish_reasons_seen=False)
    events = _collect(engine, "write the summary")
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["reason"] == "empty"
    assert EventType.TURN_END not in _types(events)


# -- blocked, not empty ---------------------------------------------------------------


def test_a_filtered_response_is_reported_as_a_block_and_never_retried(tmp_path):
    """Every provider normalizes its safety/guardrail stop to `content_filter`, because a
    block is a decision: re-running it buys the identical refusal, three times the tokens
    and eight seconds of the user's patience."""
    engine, provider = _engine(
        tmp_path,
        [AssistantTurn(text="", finish_reason="content_filter")],
        loop=True,
        retries=2,
    )
    events = _collect(engine, "write the summary")

    assert provider.calls == 1
    assert _retry_notices(engine) == []
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["reason"] == "filtered"
    # Worded for the whole class, not just safety: recitation and blocklist hits land here
    # too, and neither is a safety block.
    assert err.data["error"] == "The provider blocked this response under its content policy."


def test_a_plain_empty_answer_gets_one_courtesy_retry_not_the_full_budget(tmp_path):
    """An empty turn with an ordinary stop is the weakest evidence of a transport fault
    there is — it can equally be a model with nothing to say. One re-run, then report."""
    engine, provider = _engine(
        tmp_path,
        [AssistantTurn(text="", finish_reason="stop")],
        loop=True,
        retries=2,
    )
    events = _collect(engine, "write the summary")

    assert provider.calls == 2
    assert [n["reason"] for n in _retry_notices(engine)] == ["empty"]
    # The counter must promise what's actually available, not the configured budget.
    assert _retry_notices(engine)[0]["max"] == 1
    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["reason"] == "empty" and err.data["retries"] == 1


# -- what a dead attempt cost ---------------------------------------------------------


def test_an_expensive_attempt_is_only_repeated_once(tmp_path):
    """The 2026-09-18 incident thought for 232 seconds before the stream dropped. Running
    that twice more spends twelve minutes and three times the tokens to arrive at the
    same sentence, so a long attempt buys a single retry."""
    engine, provider = _engine(tmp_path, [_severed_turn()], loop=True, retries=2)
    ticks = iter([0.0, 120.0] * 10)
    engine.clock = lambda: next(ticks)
    events = _collect(engine, "write the summary")

    assert provider.calls == 2
    assert [n["max"] for n in _retry_notices(engine)] == [1]
    assert next(ev for ev in events if ev.type == EventType.ERROR).data["retries"] == 1


def test_a_quick_failure_still_gets_the_full_budget(tmp_path):
    engine, provider = _engine(tmp_path, [_severed_turn()], loop=True, retries=2)
    ticks = iter([0.0, 10.0] * 10)
    engine.clock = lambda: next(ticks)
    _collect(engine, "write the summary")

    assert provider.calls == 3
    assert [n["max"] for n in _retry_notices(engine)] == [2, 2]


# -- through the real OpenAI-compatible stream ---------------------------------------


def _sse_chunk(content=None, finish=None):
    """Shaped like the SDK's streamed chunk objects, which is all OpenAIProvider reads."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def _sse_tool_chunk(name, arguments, call_id="c1"):
    call = SimpleNamespace(
        index=0, id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )
    delta = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=None)])


def _stream_provider(*chunk_scripts):
    """A real OpenAIProvider over a fake SDK client, one scripted stream per call — so the
    seam between "what the provider builds from the wire" and "what the engine does with
    it" is actually exercised, not assumed."""
    scripts = list(chunk_scripts)

    class _Client:
        def __init__(self):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: iter(scripts.pop(0)))
            )

    return OpenAIProvider(client=_Client())


def _stream_engine(tmp_path, provider, *, retries=0, seen=True):
    registry = ToolRegistry()
    registry.register_all(ai.toolkits.files(root=str(tmp_path), allow_write=True))
    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )
    engine.model_retries = retries

    async def _instant(_delay):
        return not engine._cancel.is_set()

    engine.retry_sleep = _instant
    if seen:
        engine._finish_reason_seen.add(engine.model)
    return engine


def test_a_real_stream_that_ends_without_a_finish_reason_reaches_the_engine_as_severed(
    tmp_path,
):
    provider = _stream_provider([])  # the stream simply ends: no chunks, no finish
    engine = _stream_engine(tmp_path, provider)
    events = _collect(engine, "write the summary")

    err = next(ev for ev in events if ev.type == EventType.ERROR)
    assert err.data["error_type"] == "TurnAborted" and err.data["reason"] == "no_finish"
    assert EventType.TURN_END not in _types(events)


def test_a_real_stream_that_ends_normally_produces_no_new_notice(tmp_path):
    provider = _stream_provider(
        [_sse_chunk(content="all "), _sse_chunk(content="done"), _sse_chunk(finish="stop")]
    )
    engine = _stream_engine(tmp_path, provider, seen=False)
    events = _collect(engine, "hi")

    assert _types(events)[-1] == EventType.TURN_END
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == (
        "completed"
    )
    assert [m for m in engine.messages if m.get("role") == "notice"] == []
    assert engine.messages[-1]["content"] == "all done"


def test_a_real_stream_cut_off_mid_answer_warns_once_the_backend_is_proven(tmp_path):
    """Both halves of the gate over one turn and two real streams: round one reports
    `tool_calls` (proving this backend does say when it's done), round two streams text
    and then simply stops. One turn on purpose — the two halves belong to one turn's
    history, and keeping them there says so. (Two separate `asyncio.run()` loops are fine
    now; the bridge's cross-loop frame loss is covered below and is fixed.)"""
    provider = _stream_provider(
        [_sse_tool_chunk("list_files", '{"path": "."}'), _sse_chunk(finish="tool_calls")],
        [_sse_chunk(content="half an ans")],
    )
    engine = _stream_engine(tmp_path, provider, seen=False)
    events = _collect(engine, "look around, then summarize")

    warn = next(ev for ev in events if ev.type == EventType.TURN_TRUNCATED)
    assert warn.data["reason"] == "no_finish"
    assert engine.messages[-2]["content"] == "half an ans"
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == (
        "completed"
    )


# -- a cut-off tool call ---------------------------------------------------------------


def test_a_tool_turn_that_hit_the_ceiling_still_warns(tmp_path):
    """The mangled-arguments path is fed by exactly this: a tool call that ran out of
    output budget mid-JSON. The tools still run, but the user gets told why one of them
    may have received half a call."""
    engine, _ = _engine(
        tmp_path,
        [
            AssistantTurn(
                tool_calls=[ToolCall(id="c1", name="list_files", arguments={"path": "."})],
                finish_reason="length",
            ),
            _text_turn("there you go"),
        ],
    )
    events = _collect(engine, "what's here?")

    warn = next(ev for ev in events if ev.type == EventType.TURN_TRUNCATED)
    assert warn.data["reason"] == "length"
    # The tool still ran and the turn still completed — this is a warning, not a stop.
    assert EventType.TOOL_FINISHED in _types(events)
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == (
        "completed"
    )


# -- the stream bridge's own lifecycle -------------------------------------------------

# How many event-loop steps a test gives the bridge before calling it settled. Generous:
# the bridge that gave up needed five, and a loop step costs nothing to spend.
_BRIDGE_SETTLE_STEPS = 20


class _GatedStream:
    """A scripted SSE stream that parks the producer thread before wire chunk `park_at`.

    The park is what makes these tests deterministic instead of lucky: while the producer
    is held, the consumer provably HAS to wait for its next chunk, and that wait is the
    one moment the bridge can lose one. `produced` counts how much of the wire the
    producer actually pulled, which is how a producer left running is caught.
    """

    def __init__(self, chunks, park_at=0):
        self.chunks = chunks
        self.park_at = park_at
        self.gate = threading.Event()
        self.parked = threading.Event()
        self.produced = 0

    def __iter__(self):
        for index, chunk in enumerate(self.chunks):
            if index == self.park_at:
                self.parked.set()
                self.gate.wait()
            self.produced = index + 1
            yield chunk


class _BrokenStop:
    """A stop flag whose async wait always fails — what a cross-loop `asyncio.Event` did.

    The bridge has to surface that, never mistake it for the user pressing Stop.
    """

    def is_set(self):
        return False

    def set(self):
        pass

    def clear(self):
        pass

    async def wait(self):
        raise RuntimeError("stop flag is bound to a different event loop")


def _counting_stream_provider(*chunk_scripts):
    """`_stream_provider` plus a record of every wire call it actually made."""
    scripts = list(chunk_scripts)
    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        return iter(scripts.pop(0))

    class _Client:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    return OpenAIProvider(client=_Client()), calls


def _release_when_parked(script):
    """Open `script`'s gate from a plain thread, once the producer is really held.

    It has to be off the loop: `asyncio.run()` joins the default executor as it exits, so
    a producer still parked on the gate would wedge the loop's own shutdown.
    """

    def _wait_then_open():
        script.parked.wait()
        script.gate.set()

    opener = threading.Thread(target=_wait_then_open, daemon=True)
    opener.start()
    return opener


async def _drain_stream(engine, script=None):
    chunks = []
    try:
        async for chunk in engine._astream():
            chunks.append(chunk)
    finally:
        if script is not None:  # never leave a parked producer behind
            script.parked.set()
            script.gate.set()
    return chunks


def test_one_engine_streaming_on_a_second_event_loop_delivers_every_chunk(tmp_path):
    """The bridge used to end the stream the first time it had to WAIT for a chunk on any
    loop other than the one the engine's stop flag happened to bind to. The final
    `StreamChunk(turn=…)` arrives after exactly such a wait, so the turn came back empty
    for no reason the user, the events or the log could see."""
    parked = _GatedStream(
        [
            _sse_chunk(content="second "),
            _sse_chunk(content="loop"),
            _sse_chunk(finish="stop"),
        ]
    )
    provider, calls = _counting_stream_provider(
        [_sse_chunk(content="first loop"), _sse_chunk(finish="stop")], parked
    )
    engine = _stream_engine(tmp_path, provider)
    engine.messages.append({"role": "user", "content": "hi"})

    assert asyncio.run(_drain_stream(engine))[-1].turn is not None

    async def _on_a_second_loop():
        stream = engine._astream()
        step = asyncio.ensure_future(stream.__anext__())
        chunks = []
        try:
            # The producer is held, so the queue is provably empty and the bridge's only
            # correct move is to go on waiting. Stepping the loop — never the clock — is
            # what makes that observable: the old bridge gave up within a few steps.
            for _ in range(_BRIDGE_SETTLE_STEPS):
                await asyncio.sleep(0)
            still_waiting = not step.done()
            parked.gate.set()
            try:
                chunks.append(await step)
            except StopAsyncIteration:
                pass
            else:
                async for chunk in stream:
                    chunks.append(chunk)
        finally:
            parked.parked.set()
            parked.gate.set()
        return still_waiting, chunks

    still_waiting, second = asyncio.run(_on_a_second_loop())

    assert still_waiting, "the bridge abandoned a stream that had delivered nothing yet"
    assert [c.text_delta for c in second if c.text_delta] == ["second ", "loop"]
    assert second[-1].turn is not None and second[-1].turn.text == "second loop"
    assert parked.produced == len(parked.chunks)
    assert len(calls) == 2


def test_a_stop_wait_that_fails_is_raised_not_read_as_a_stop(tmp_path):
    """Belt and braces for the bridge: whatever goes wrong with the Stop wait, the turn
    has to hear about it. Ending the stream quietly is what turned a broken wait into an
    empty assistant reply with nothing to debug."""
    parked = _GatedStream([_sse_chunk(content="never "), _sse_chunk(finish="stop")])
    provider, _ = _counting_stream_provider(parked)
    engine = _stream_engine(tmp_path, provider)
    engine.messages.append({"role": "user", "content": "hi"})
    engine._cancel = _BrokenStop()

    opener = _release_when_parked(parked)
    with pytest.raises(RuntimeError):
        asyncio.run(_drain_stream(engine, parked))
    opener.join(timeout=5)


async def _settle_until_the_bridge_waits_on_the_stop_flag(engine):
    """Step the loop until the bridge has provably registered on the Stop flag.

    `_StopSignal` keeps its own waiter registry, so "the bridge is parked inside
    `asyncio.wait`" is directly observable instead of guessed at from a step count — which
    matters here because the window this opens is one event-loop step wide. Bounded, so a
    bridge that never registers fails the assertion below instead of spinning forever.
    """
    for _ in range(_BRIDGE_SETTLE_STEPS):
        if engine._cancel._waiters:
            return True
        await asyncio.sleep(0)
    return False


def test_a_stop_that_is_cleared_before_the_bridge_reads_it_is_raised_not_answered(
    tmp_path,
):
    """`StreamBridgeError`'s one and only route, made deterministic.

    The bridge waits on the queue and on the Stop flag together, then decides which woke
    it by READING THE FLAG BACK. Set-then-clear is the one sequence where those two
    disagree: the wait woke, the queue is provably empty (the producer is parked), and the
    flag says nobody stopped anything. In production `clear()` comes from `run`/`retry`/
    `resume` — a second turn started on this engine while this stream was still live.
    """
    parked = _GatedStream([_sse_chunk(content="never "), _sse_chunk(finish="stop")])
    provider, _ = _counting_stream_provider(parked)
    engine = _stream_engine(tmp_path, provider)
    engine.messages.append({"role": "user", "content": "hi"})

    async def _stop_then_unstop():
        stream = engine._astream()
        step = asyncio.ensure_future(stream.__anext__())
        try:
            registered = await _settle_until_the_bridge_waits_on_the_stop_flag(engine)
            if registered:
                # Same loop, same step: `set()` resolves the bridge's waiter inline
                # (exactly as `asyncio.Event.set()` does) and `clear()` lands before the
                # bridge is scheduled back in. No sleeping, no racing.
                engine._cancel.set()
                engine._cancel.clear()
            else:
                # A missed window must fail, never hang: with the producer held and no
                # Stop coming, the bridge would wait for a chunk forever.
                parked.parked.set()
                parked.gate.set()
            with pytest.raises(StreamBridgeError) as raised:
                await step
            produced, message = parked.produced, str(raised.value)
        finally:
            parked.parked.set()  # never leave a parked producer behind
            parked.gate.set()
        return registered, produced, message

    registered, produced, message = asyncio.run(_stop_then_unstop())

    assert registered, "the bridge never waited on the stop flag"
    assert "without delivering a turn" in message
    assert produced == 0  # the raise happened while the wire was still held


def test_the_bridge_error_ends_the_turn_on_an_error_the_user_can_retry(tmp_path):
    """What the same failure looks like from outside: an ordinary provider failure. It must
    not reach the user as the empty assistant turn the bridge's silent return used to hand
    them, and the tail has to stay retriable so the GUI still offers Retry."""
    parked = _GatedStream([_sse_chunk(content="never "), _sse_chunk(finish="stop")])
    provider, _ = _counting_stream_provider(parked)
    engine = _stream_engine(tmp_path, provider)
    outcome: dict[str, bool] = {}

    async def _one_turn():
        async def _stop_then_unstop():
            outcome["registered"] = (
                await _settle_until_the_bridge_waits_on_the_stop_flag(engine)
            )
            if outcome["registered"]:
                engine._cancel.set()
                engine._cancel.clear()
            else:  # as above: a missed window fails the assertions, it never hangs
                parked.parked.set()
                parked.gate.set()

        saboteur = asyncio.ensure_future(_stop_then_unstop())
        try:
            return [ev async for ev in engine.run("what's here?")]
        finally:
            parked.parked.set()
            parked.gate.set()
            await saboteur

    events = asyncio.run(_one_turn())

    assert outcome["registered"], "the bridge never waited on the stop flag"
    assert _types(events) == [EventType.TURN_START, EventType.ERROR]
    assert events[-1].data["error_type"] == "StreamBridgeError"
    assert "without delivering a turn" in events[-1].data["error"]
    # Nothing was passed off as an answer, and the turn ends on a notice that keeps Retry
    # on offer — the whole point of raising instead of returning.
    assert not [m for m in engine.messages if m.get("role") == "assistant"]
    assert engine.messages[-1]["kind"] == "error"
    assert engine._tail_is_retriable_error()


def test_two_turns_on_two_event_loops_both_complete(tmp_path):
    """The shape that first caught this: one engine, one whole turn per `asyncio.run()`.
    Each round has to stand on its own model call — an answer rescued by the automatic
    retry would hide the very frame loss this guards.

    This is an end-to-end scenario regression, not the deterministic guardrail: on the
    pre-fix code it only failed probabilistically, roughly 40-45% of runs in independent
    review. The deterministic guardrail is
    `test_one_engine_streaming_on_a_second_event_loop_delivers_every_chunk`, which parks
    the producer to force the exact race every run."""
    parked = _GatedStream(
        [_sse_chunk(content="second"), _sse_chunk(finish="stop")], park_at=1
    )
    provider, calls = _counting_stream_provider(
        [_sse_chunk(content="first"), _sse_chunk(finish="stop")], parked
    )
    engine = _stream_engine(tmp_path, provider)

    first = _collect(engine, "round one")
    opener = _release_when_parked(parked)
    second = _collect(engine, "round two")
    opener.join(timeout=5)

    for events in (first, second):
        assert next(
            ev for ev in events if ev.type == EventType.TURN_END
        ).data["status"] == ("completed")
    assert [m["content"] for m in engine.messages if m.get("role") == "assistant"] == [
        "first",
        "second",
    ]
    assert len(calls) == 2  # one call per round: no retry papered over a lost frame


def test_a_consumer_that_leaves_stops_the_producer(tmp_path):
    """A read already in flight can't be interrupted, but the producer must not keep
    pulling a stream nobody is reading: it used to drain the whole response into a queue
    that had already been thrown away."""
    parked = _GatedStream(
        [_sse_chunk(content="a"), _sse_chunk(content="b"), _sse_chunk(finish="stop")]
    )
    provider, _ = _counting_stream_provider(parked)
    engine = _stream_engine(tmp_path, provider)
    engine.messages.append({"role": "user", "content": "hi"})

    async def _leave_at_once():
        loop = asyncio.get_running_loop()
        # One worker, so "the producer has finished" becomes observable: the next job can
        # only start once `produce()` returned. No sleeping, no polling.
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        stream = engine._astream()
        first = asyncio.ensure_future(stream.__anext__())
        await asyncio.sleep(0)  # let the bridge start its producer, then walk away
        first.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await first
            await stream.aclose()
        finally:
            # Only now is the producer let go, so it cannot have got ahead of the
            # departure — and it's in `finally` so a failed assertion above still frees
            # the producer instead of wedging `asyncio.run()`'s executor shutdown on
            # gate.wait().
            parked.gate.set()
        await loop.run_in_executor(None, lambda: None)

    asyncio.run(_leave_at_once())

    # One more chunk was already on the wire when the consumer left; nothing after it.
    assert parked.produced == 1


class _RecordingExecutor(ThreadPoolExecutor):
    """One worker, and a handle on every job it was given — `run_in_executor` keeps the
    job's own future to itself, and that future is where a producer's exception lands."""

    def __init__(self):
        super().__init__(max_workers=1)
        self.jobs = []

    def submit(self, fn, /, *args, **kwargs):
        job = super().submit(fn, *args, **kwargs)
        self.jobs.append(job)
        return job


def test_a_producer_abandoned_on_a_closed_loop_lets_go_quietly(tmp_path):
    """A Stop ends the consumer at once, while its producer can still be sitting in a read
    nothing can interrupt. `explore` closes its loop without waiting for that thread
    (tools/subagent.py), so when the read finally returns the loop it would report to is
    gone. The producer has to let go of the stream and leave — not raise from its
    `finally` into a future nobody will ever read, and not reach for the next chunk.

    The loop runs on a thread of its own so that waiting for it is bounded from outside.
    Until the gate opens the producer is parked with no timeout, so a Stop path that waits
    for it would never return. On the test's own thread that would hang the whole run
    instead of failing this one test, and `asyncio.wait_for` would only help while the
    loop itself stays free to time out."""
    parked = _GatedStream(
        [_sse_chunk(content="a"), _sse_chunk(content="b"), _sse_chunk(finish="stop")],
        park_at=1,
    )
    provider, _ = _counting_stream_provider(parked)
    engine = _stream_engine(tmp_path, provider)
    engine.messages.append({"role": "user", "content": "hi"})
    executor = _RecordingExecutor()
    thread_errors = []
    previous_hook = threading.excepthook
    threading.excepthook = thread_errors.append
    outcome = {}

    async def _stop_mid_answer():
        chunks = []
        async for chunk in engine._astream():
            chunks.append(chunk)
            engine.request_interrupt()  # after the first delta, with the next still unread
        return chunks

    def _run_the_way_explore_does():
        loop = asyncio.new_event_loop()
        loop.set_default_executor(executor)
        try:
            outcome["delivered"] = loop.run_until_complete(_stop_mid_answer())
            loop.run_until_complete(loop.shutdown_asyncgens())
        except BaseException as exc:  # reported below, never lost in the thread
            outcome["error"] = exc
        finally:
            loop.close()  # what `explore` does: no wait for the producer

    driver = threading.Thread(target=_run_the_way_explore_does, daemon=True)
    driver.start()
    try:
        # Failure bounds only, never part of the happy path.
        driver.join(10)
        assert not driver.is_alive(), "the Stop path is waiting on the parked producer"
        assert "error" not in outcome, outcome.get("error")
        assert [c.text_delta for c in outcome["delivered"]] == ["a"]
        # Still inside the read when its loop went away; now the read returns.
        assert parked.parked.wait(10)
        parked.gate.set()
        producer_error = executor.jobs[0].exception(timeout=10)
    finally:
        parked.gate.set()  # a parked producer would hold the test process at exit
        threading.excepthook = previous_hook
        driver.join(10)
        # No join on the worker here. Once the gate is open it has nothing left to wait
        # on, and on the passing path its job is already done. A producer that hangs
        # anyway should fail this test, not stall the run.
        executor.shutdown(wait=False)

    assert producer_error is None
    # This never distinguishes the fix either way: concurrent.futures.thread._WorkItem.run()
    # catches every BaseException the submitted callable raises and stores it on the future
    # instead of letting it reach the thread (verified by weakening the fix above and
    # re-running: producer_error surfaced the RuntimeError while thread_errors stayed empty).
    # Kept anyway as a defensive check against some other, unrelated exception escaping to
    # threading.excepthook.
    assert thread_errors == []
    assert parked.produced == 2  # the chunk already on the wire, and nothing after it


# -- the first-chunk deadline ----------------------------------------------------------

# Short enough that a test spends a tenth of a second on it, long enough that scheduling
# a thread and waking the loop on a busy machine can't trip it by accident.
_TEST_DEADLINE = 0.1
# How long a "it must NOT give up" test waits before believing the bridge. Several
# deadlines' worth of real time, so a wrongly-armed deadline has fired well before it.
_PAST_THE_DEADLINE = _TEST_DEADLINE * 4


def _sse_reasoning_chunk(reasoning):
    """A wire chunk carrying thinking text and nothing else — `reasoning_content` is the
    spelling `_delta_reasoning` reads for most compat vendors (openai_provider.py)."""
    delta = SimpleNamespace(content=None, tool_calls=None, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=None)])


class _SilentStream:
    """A wire that sends `lead`, then goes quiet until `release` is set (or `hold` runs
    out), then sends `rest`.

    With an empty `lead` this is the failure the deadline exists for: the request was
    accepted and nothing at all came back. The wait is BOUNDED, unlike `_GatedStream`'s
    gate, because these producers are not always freed by the path under test —
    `asyncio.run()` joins the default executor as it exits, and a producer parked with no
    timeout would wedge that join instead of failing a test. `hold` is a failure bound
    only; every test below frees it deliberately.
    """

    def __init__(self, *, lead=(), rest=(), hold=5.0):
        self.lead = list(lead)
        self.rest = list(rest)
        self.hold = hold
        self.release = threading.Event()
        self.quiet = threading.Event()  # the producer has reached the silence
        self.produced = 0

    def __iter__(self):
        for chunk in self.lead:
            self.produced += 1
            yield chunk
        self.quiet.set()
        self.release.wait(self.hold)
        for chunk in self.rest:
            self.produced += 1
            yield chunk


def _deadline_engine(tmp_path, *scripts, retries=0, deadline=_TEST_DEADLINE, asked=True):
    """An engine over scripted wires, with the first-chunk deadline turned down to a tenth
    of a second. The knob is set on the instance, which is the seam the constructor's
    `_first_chunk_timeout()` exists to leave open — the parser itself is covered below.

    `asked` seeds the user turn that a bare `_astream` call needs; the tests that go
    through `run()` pass False, because `run` appends it itself.
    """
    provider, calls = _counting_stream_provider(*scripts)
    engine = _stream_engine(tmp_path, provider, retries=retries)
    engine.first_chunk_timeout = deadline
    if asked:
        engine.messages.append({"role": "user", "content": "hi"})
    return engine, calls


def test_a_stream_that_sends_nothing_at_all_gives_up_on_the_deadline(tmp_path):
    """The gap the bridge had no answer for: the provider accepted the request and then
    said nothing. Before this the bridge waited on the queue with no timeout at all, so
    the turn sat on `turn_start` for as long as the HTTP layer underneath took to notice —
    up to ~1800s on the OpenAI/Anthropic SDK defaults, and forever on Gemini."""
    script = _SilentStream()
    engine, _ = _deadline_engine(tmp_path, script)

    async def _wait_it_out():
        try:
            with pytest.raises(FirstChunkTimeout) as raised:
                async for _ in engine._astream():
                    pass
            return str(raised.value)
        finally:
            script.release.set()

    message = asyncio.run(_wait_it_out())

    # Named for what it is, and NOT reported as the bridge's other silent-queue outcome:
    # `StreamBridgeError` means "a second turn was started on this engine", which is a
    # different bug, with a different fix, and no automatic retry.
    assert "accepted the request but sent nothing" in message
    assert _FIRST_CHUNK_TIMEOUT_ENV in message
    assert script.produced == 0


def test_the_first_chunk_disarms_the_deadline(tmp_path):
    """The deadline covers the pre-first-token wait only. Once the stream has started,
    the gaps between chunks are not bounded by this (and a model that thinks for four
    minutes between two deltas must not be killed as "wedged")."""
    script = _SilentStream(
        lead=[_sse_chunk(content="hello")], rest=[_sse_chunk(finish="stop")]
    )
    engine, _ = _deadline_engine(tmp_path, script)

    async def _one_chunk_then_silence():
        stream = engine._astream()
        try:
            first = await stream.__anext__()
            assert first.text_delta == "hello"
            assert script.quiet.wait(5)  # the wire really is silent now
            step = asyncio.ensure_future(stream.__anext__())
            await asyncio.sleep(_PAST_THE_DEADLINE)
            still_waiting = not step.done()
            script.release.set()
            rest = [await step]
            async for chunk in stream:
                rest.append(chunk)
            return still_waiting, rest
        finally:
            script.release.set()

    still_waiting, rest = asyncio.run(_one_chunk_then_silence())

    assert still_waiting, "the deadline was still armed after the first chunk arrived"
    assert rest[-1].turn is not None and rest[-1].turn.text == "hello"


def test_thinking_text_counts_as_a_first_chunk(tmp_path):
    """A model that thinks before it writes is answering, not wedged — the first chunk is
    whatever arrives first, and for a reasoning model that is a `reasoning_delta`."""
    script = _SilentStream(
        lead=[_sse_reasoning_chunk("let me think")],
        rest=[_sse_chunk(content="done"), _sse_chunk(finish="stop")],
    )
    engine, _ = _deadline_engine(tmp_path, script)

    async def _think_then_go_quiet():
        stream = engine._astream()
        try:
            first = await stream.__anext__()
            assert first.reasoning_delta == "let me think"
            assert first.text_delta is None
            assert script.quiet.wait(5)
            step = asyncio.ensure_future(stream.__anext__())
            await asyncio.sleep(_PAST_THE_DEADLINE)
            still_waiting = not step.done()
            script.release.set()
            await step
            async for _ in stream:
                pass
            return still_waiting
        finally:
            script.release.set()

    assert asyncio.run(
        _think_then_go_quiet()
    ), "thinking text did not disarm the deadline"


def test_a_stop_before_the_deadline_is_still_read_as_a_stop(tmp_path):
    """The deadline joins the Stop race; it must not take it over. A user who gives up on
    a silent stream first gets the ordinary quiet return, not an error."""
    script = _SilentStream(hold=10.0)
    engine, _ = _deadline_engine(tmp_path, script, deadline=10.0)

    async def _stop_while_it_is_silent():
        stream = engine._astream()
        try:
            step = asyncio.ensure_future(stream.__anext__())
            assert await _settle_until_the_bridge_waits_on_the_stop_flag(engine)
            engine.request_interrupt()
            with pytest.raises(StopAsyncIteration):
                await step
        finally:
            script.release.set()

    asyncio.run(_stop_while_it_is_silent())


def test_the_deadline_can_be_switched_off(tmp_path):
    """`OPENWORKER_FIRST_CHUNK_TIMEOUT=off` restores the old behaviour exactly — for a
    self-hosted endpoint whose queue really can hold a request for many minutes."""
    script = _SilentStream(rest=[_sse_chunk(content="slow"), _sse_chunk(finish="stop")])
    engine, _ = _deadline_engine(tmp_path, script, deadline=None)

    async def _no_deadline_at_all():
        stream = engine._astream()
        try:
            step = asyncio.ensure_future(stream.__anext__())
            # Not `quiet.wait()`: a blocking wait here would hold the loop that has yet to
            # START the bridge, so the producer would never run and the wait would time
            # out. Sleeping lets both run, and by the far side the wire is provably quiet.
            await asyncio.sleep(_PAST_THE_DEADLINE)
            assert script.quiet.is_set()
            still_waiting = not step.done()
            script.release.set()
            chunks = [await step]
            async for chunk in stream:
                chunks.append(chunk)
            return still_waiting, chunks
        finally:
            script.release.set()

    still_waiting, chunks = asyncio.run(_no_deadline_at_all())

    assert still_waiting, "a switched-off deadline still gave up"
    assert chunks[-1].turn is not None and chunks[-1].turn.text == "slow"


def test_an_ordinary_stream_is_untouched_by_the_deadline(tmp_path):
    """The whole normal path, with the deadline armed at 50ms: a stream that answers
    promptly must not notice it exists."""
    engine, calls = _deadline_engine(
        tmp_path,
        [_sse_chunk(content="hi there"), _sse_chunk(finish="stop")],
        asked=False,
    )

    events = _collect(engine, "say hi")

    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == (
        "completed"
    )
    assert [m["content"] for m in engine.messages if m.get("role") == "assistant"] == [
        "hi there"
    ]
    assert len(calls) == 1  # no retry papered over anything


def test_a_producer_still_queued_in_the_thread_pool_is_not_timed(tmp_path, caplog):
    """The deadline is armed by the PRODUCER, not by `_astream` starting.

    `loop.run_in_executor(None, …)` uses the default pool, shared with
    `_handle_tool_calls`' `to_thread` and dozens of `to_thread` calls in `server/`. Under
    concurrency the producer can sit in that pool's queue for an unbounded time without
    the provider having been asked for anything yet. Timing that as provider silence
    would invent a timeout and retry into the very queue that caused it, so the clock
    only starts once the producer says it has entered `provider.stream()`.

    One worker, deliberately occupied, is that state made deterministic.

    It is also the only arm of the five that neither raises, returns nor yields, so it is
    the one place a turn can keep waiting with nothing said anywhere. The INFO line
    asserted at the end is what makes that state findable in a server log.
    """
    caplog.set_level(logging.INFO, logger="coworker.engine")
    script = _SilentStream(
        rest=[_sse_chunk(content="eventually"), _sse_chunk(finish="stop")]
    )
    engine, _ = _deadline_engine(tmp_path, script)
    occupied = threading.Event()
    free_the_pool = threading.Event()

    def _hog():
        occupied.set()
        free_the_pool.wait(10)

    async def _queued_behind_a_busy_pool():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        hog = loop.run_in_executor(None, _hog)
        try:
            assert occupied.wait(5)
            stream = engine._astream()
            step = asyncio.ensure_future(stream.__anext__())
            # Several deadlines' worth of real time with the producer not yet running.
            await asyncio.sleep(_PAST_THE_DEADLINE)
            still_waiting = not step.done()
            free_the_pool.set()
            script.release.set()
            chunks = [await step]
            async for chunk in stream:
                chunks.append(chunk)
            return still_waiting, chunks
        finally:
            free_the_pool.set()
            script.release.set()
            await hog

    still_waiting, chunks = asyncio.run(_queued_behind_a_busy_pool())

    assert still_waiting, "a producer that had not started yet was timed as if it had"
    assert chunks[-1].turn is not None and chunks[-1].turn.text == "eventually"
    assert any(
        "first_chunk_deadline_waiting_on_executor" in record.getMessage()
        for record in caplog.records
    ), "the one unbounded arm re-armed without saying so anywhere"


def _release_silent_scripts_as_the_turn_reports(engine, user_input, scripts):
    """Run one whole turn, freeing stalled producers ONE AT A TIME — the oldest each time
    the engine says it has given up on an attempt (the retry announcement, or the final
    error), in the order the scripts are handed to the wire.

    Freeing them from outside would race the deadline, freeing them all at once would let
    the NEXT attempt answer instantly (with an empty stream, since a stalled script has
    nothing queued behind its silence), and leaving them parked would make
    `asyncio.run()`'s executor shutdown wait out every `hold`.
    """
    pending = list(scripts)

    async def _one_turn():
        events = []
        try:
            async for event in engine.run(user_input):
                events.append(event)
                if event.type in (EventType.TURN_RETRY, EventType.ERROR) and pending:
                    pending.pop(0).release.set()
        finally:
            for script in scripts:
                script.release.set()
        return events

    return asyncio.run(_one_turn())


def test_a_first_chunk_timeout_is_transient_to_the_retry_gate():
    """The one line that makes the rest of this free: `FirstChunkTimeout` subclasses
    `TimeoutError`, which is an isinstance arm of `is_transient_model_error`. So v0.6.5's
    bounded automatic retry picks it up with no change to the retry code, the
    `turn_retry` reasons, or the GUI's localized sentences."""
    assert is_transient_model_error(
        FirstChunkTimeout(
            "gpt-5.5 accepted the request but sent nothing for 120s — the connection "
            f"looks wedged. ({_FIRST_CHUNK_TIMEOUT_ENV})"
        )
    )


def test_a_first_chunk_timeout_is_retried_and_the_retry_can_answer(tmp_path):
    """End to end: a wedged call is re-sent rather than handed to the user as a Retry
    button, and it arrives as an ordinary `reason="transient"` failure."""
    stalled = _SilentStream()
    engine, calls = _deadline_engine(
        tmp_path,
        stalled,
        [_sse_chunk(content="second time lucky"), _sse_chunk(finish="stop")],
        retries=1,
        asked=False,
    )

    events = _release_silent_scripts_as_the_turn_reports(engine, "hi", [stalled])

    retries = [ev for ev in events if ev.type == EventType.TURN_RETRY]
    assert [ev.data["reason"] for ev in retries] == ["transient"]
    assert next(ev for ev in events if ev.type == EventType.TURN_END).data["status"] == (
        "completed"
    )
    assert [m["content"] for m in engine.messages if m.get("role") == "assistant"] == [
        "second time lucky"
    ]
    assert len(calls) == 2


def test_a_first_chunk_timeout_that_keeps_happening_ends_the_turn_on_an_error(tmp_path):
    """The budget is bounded: when every attempt wedges, the turn ends on an error the
    user can act on, not on a fourth silent wait."""
    stalled = [_SilentStream(), _SilentStream()]
    engine, calls = _deadline_engine(tmp_path, *stalled, retries=1, asked=False)

    events = _release_silent_scripts_as_the_turn_reports(engine, "hi", stalled)

    assert len([ev for ev in events if ev.type == EventType.TURN_RETRY]) == 1
    error = next(ev for ev in events if ev.type == EventType.ERROR)
    assert error.data["error_type"] == "FirstChunkTimeout"
    assert "accepted the request but sent nothing" in error.data["error"]
    assert len(calls) == 2
    assert engine._tail_is_retriable_error()


def test_a_first_chunk_timeout_is_only_worth_one_retry_whatever_the_clock_says(
    tmp_path, monkeypatch
):
    """The budget clamp is carried by the caller, not by two defaults happening to line
    up. The deadline defaults to 120s and `_LONG_ATTEMPT_DEFAULT` is 90s, so the "long
    attempt" ceiling would normally apply on elapsed time alone — but
    `OPENWORKER_MODEL_RETRY_LONG_ATTEMPT_SECONDS` can be raised past the deadline, and
    then the worst case would be the full budget times a full deadline each."""
    monkeypatch.setenv(_LONG_ATTEMPT_ENV, "600")
    engine = _default_engine(tmp_path)
    engine.model_retries = 3

    assert engine._retry_budget("transient", elapsed=1.0) == 3
    assert engine._retry_budget("transient", elapsed=1.0, long_attempt=True) == 1


def test_the_clamp_holds_through_a_real_turn(tmp_path, monkeypatch):
    """…and the call site really passes it: three retries configured, the clock ceiling
    lifted out of the way, and the wedged call still gets exactly one re-send."""
    monkeypatch.setenv(_LONG_ATTEMPT_ENV, "600")
    stalled = [_SilentStream(), _SilentStream(), _SilentStream(), _SilentStream()]
    engine, calls = _deadline_engine(tmp_path, *stalled, retries=3, asked=False)

    events = _release_silent_scripts_as_the_turn_reports(engine, "hi", stalled)

    assert len([ev for ev in events if ev.type == EventType.TURN_RETRY]) == 1
    assert len(calls) == 2  # the original and one retry, not the configured four
    assert next(ev for ev in events if ev.type == EventType.ERROR)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, 120.0),  # unset
        ("", 120.0),
        ("   ", 120.0),
        ("off", None),
        ("OFF", None),
        ("none", None),
        ("Never", None),
        ("0", 120.0),  # NOT honoured — "wait forever" has to be spelled out
        ("-5", 120.0),
        ("banana", 120.0),
        ("30", 30.0),
        ("  45.5  ", 45.5),
    ],
)
def test_the_first_chunk_deadline_knob(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(_FIRST_CHUNK_TIMEOUT_ENV, raising=False)
    else:
        monkeypatch.setenv(_FIRST_CHUNK_TIMEOUT_ENV, raw)

    assert _first_chunk_timeout() == expected


# -- the stop flag, which outlives any one event loop ----------------------------------


def test_the_stop_flag_still_works_on_a_later_event_loop(tmp_path):
    """`asyncio.Event` binds to the first loop that awaits it and raises on every loop
    after that. An engine outlives loops — tools run their own — so its stop flag can't."""
    engine = _default_engine(tmp_path)

    async def _bind_and_walk_away():
        waiter = asyncio.ensure_future(engine._cancel.wait())
        await asyncio.sleep(0)
        waiter.cancel()

    asyncio.run(_bind_and_walk_away())

    async def _stop_on_a_new_loop():
        waiter = asyncio.ensure_future(engine._cancel.wait())
        await asyncio.sleep(0)
        engine.request_interrupt()
        return await asyncio.wait_for(waiter, timeout=5)

    assert asyncio.run(_stop_on_a_new_loop()) is True


def test_a_stop_from_another_thread_wakes_the_waiter(tmp_path):
    """Stop arrives off the loop thread too — the manager sets it when a team run is
    cancelled or a session is deleted."""
    engine = _default_engine(tmp_path)

    async def _wait_for_another_thread():
        waiter = asyncio.ensure_future(engine._cancel.wait())
        await asyncio.sleep(0)
        threading.Thread(target=engine.request_interrupt, daemon=True).start()
        return await asyncio.wait_for(waiter, timeout=5)

    assert asyncio.run(_wait_for_another_thread()) is True


def test_a_cancelled_stop_wait_leaves_nothing_registered(tmp_path):
    """Every streamed chunk starts a fresh stop wait, so a waiter that outlives its own
    cancellation would pile up for the length of the answer."""
    engine = _default_engine(tmp_path)

    async def _cancel_a_waiter():
        waiter = asyncio.ensure_future(engine._cancel.wait())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    asyncio.run(_cancel_a_waiter())

    assert not engine._cancel._waiters


def test_a_stop_survives_a_waiter_whose_loop_is_gone(tmp_path):
    """Stop is called from paths that can't know which loops are still alive (the manager
    deleting a session). A dead loop among the waiters must not break the others."""
    engine = _default_engine(tmp_path)
    loop = asyncio.new_event_loop()

    async def _park_a_waiter():
        waiter = asyncio.ensure_future(engine._cancel.wait())
        await asyncio.sleep(0)
        # Left pending on purpose — that IS the scenario. Silence the destructor's
        # complaint so the deliberate leak doesn't read as a test going wrong.
        waiter._log_destroy_pending = False

    try:
        loop.run_until_complete(_park_a_waiter())
    finally:
        loop.close()  # the waiter is still registered; its loop is not

    engine.request_interrupt()

    assert engine._cancel.is_set()


def test_a_failed_stop_wait_is_not_read_as_an_interruption(tmp_path):
    """`_interruptible` has the bridge's shape and had the bridge's bug: a wait that blew
    up satisfied the race and answered the pending approval with "interrupted"."""
    engine = _default_engine(tmp_path)
    engine._cancel = _BrokenStop()

    async def _never_finishes():
        await asyncio.sleep(3600)

    async def _await_an_approval():
        return await engine._interruptible(_never_finishes(), "interrupted")

    with pytest.raises(RuntimeError):
        asyncio.run(_await_an_approval())


# -- interrupt hooks attached for the length of one call -------------------------------


def _hook_engine(tmp_path, hooks=None):
    return TurnEngine(
        provider=ScriptedProvider([]),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        interrupt_hooks=hooks,
    )


def test_an_added_hook_runs_on_stop_and_a_removed_one_does_not(tmp_path):
    engine = _hook_engine(tmp_path)
    calls = []
    remove = engine.add_interrupt_hook(lambda: calls.append("hook"))

    engine.request_interrupt()
    assert calls == ["hook"]

    remove()
    remove()  # idempotent: a `finally` that runs twice must not raise or re-remove
    engine.request_interrupt()
    assert calls == ["hook"]
    assert engine._interrupt_hooks == []


def test_a_hook_added_after_stop_fires_at_once(tmp_path):
    """The window this closes: the tool was already dispatched when the user pressed Stop,
    so the thing it owns has no hook yet and nothing later will ever call one."""
    engine = _hook_engine(tmp_path)
    calls = []

    engine.request_interrupt()
    remove = engine.add_interrupt_hook(lambda: calls.append("hook"))

    assert calls == ["hook"]
    remove()


def test_constructor_hooks_still_run_alongside_added_ones(tmp_path):
    calls = []
    engine = _hook_engine(tmp_path, hooks=[lambda: calls.append("session")])
    engine.add_interrupt_hook(lambda: calls.append("call"))

    engine.request_interrupt()
    assert calls == ["session", "call"]


def test_a_hook_that_detaches_during_the_stop_does_not_skip_the_next_one(tmp_path):
    """Walking the LIVE list is the hazard the snapshot removes: a hook that detaches
    itself while being called — exactly what a finishing `explore` does, from a worker
    thread, while Stop is going round — shifts the list under the walk and the hook behind
    it is never reached. Two parallel explores, one Stop, one subagent left running."""
    engine = _hook_engine(tmp_path)
    calls = []
    removers = {}

    def first():
        calls.append("first")
        removers["first"]()  # this explore just finished; its relay hook goes

    removers["first"] = engine.add_interrupt_hook(first)
    removers["second"] = engine.add_interrupt_hook(lambda: calls.append("second"))

    engine.request_interrupt()
    assert calls == ["first", "second"]


def test_a_hook_that_raises_does_not_block_the_ones_behind_it(tmp_path):
    engine = _hook_engine(tmp_path)
    calls = []

    def boom():
        raise RuntimeError("dead executor")

    engine.add_interrupt_hook(boom)
    engine.add_interrupt_hook(lambda: calls.append("after"))

    engine.request_interrupt()
    assert calls == ["after"]
