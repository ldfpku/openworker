"""Stop-button semantics: interrupt must bite in EVERY engine state, not just the
between-iterations checkpoint (v0.1.4 shipped with that as the only one — ledgered
2026-07-21). History invariant throughout: every tool_call gets a tool result, since
hosted chat templates reject orphans and durable-resume re-prompts them."""

from __future__ import annotations

import asyncio
import time

import aisuite as ai
from coworker.engine import ApprovalOutcome, TurnEngine
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


class EndlessStreamProvider(ProviderClient):
    """Streams deltas ~forever (bounded so a regression fails instead of hanging)."""

    def __init__(self):
        self.chunks_produced = 0

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        for i in range(200):
            self.chunks_produced += 1
            yield StreamChunk(text_delta=f"w{i} ")
            time.sleep(0.01)
        yield StreamChunk(turn=AssistantTurn(text="full", finish_reason="stop"))


def _tool_turn(calls):
    return AssistantTurn(
        tool_calls=[ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)],
        finish_reason="tool_calls",
    )


class OneTurnProvider(ProviderClient):
    def __init__(self, turn):
        self._turn = turn
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        return self._turn

    def capabilities(self, model):
        return ModelCapabilities()


def _tool_results(engine):
    return [m for m in engine.messages if m.get("role") == "tool"]


def test_stop_mid_stream_keeps_partial_text(tmp_path):
    provider = EndlessStreamProvider()
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def run():
        events = []
        async for ev in engine.run("go"):
            events.append(ev)
            if ev.type == EventType.ASSISTANT_DELTA and len(events) > 3:
                engine.request_interrupt()
        return events

    events = asyncio.run(run())
    assert events[-1].type == EventType.INTERRUPTED
    # Far fewer than the full 200 chunks were consumed…
    assert provider.chunks_produced < 100
    # …and the partial text the user watched is persisted, with no tool calls,
    # capped by the interrupted marker (display-only notice role).
    assert engine.messages[-1] == {
        "role": "notice",
        "kind": "interrupted",
        "ts": engine.messages[-1]["ts"],
    }
    partial = engine.messages[-2]
    assert partial["role"] == "assistant" and partial["content"].startswith("w0 ")
    assert "tool_calls" not in partial
    # The notice never reaches a provider.
    assert all(m.get("role") != "notice" for m in engine._outbound_messages())


class FailingStreamProvider(ProviderClient):
    """Streams a few deltas, then dies — a provider outage mid-answer."""

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        yield StreamChunk(text_delta="partial ")
        yield StreamChunk(text_delta="answer")
        raise RuntimeError("provider went away")


def test_provider_error_mid_stream_keeps_partial_text(tmp_path):
    engine = TurnEngine(
        provider=FailingStreamProvider(),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def run():
        return [ev async for ev in engine.run("go")]

    events = asyncio.run(run())
    assert events[-1].type == EventType.ERROR
    notice = engine.messages[-1]
    assert notice["role"] == "notice" and notice["kind"] == "error"
    assert "provider went away" in notice["text"]
    partial = engine.messages[-2]
    assert partial["role"] == "assistant" and partial["content"] == "partial answer"
    assert "tool_calls" not in partial


class FlakyProvider(ProviderClient):
    """Fails the first N stream calls, then answers — a provider outage that recovers."""

    def __init__(self, failures=1):
        self._failures = failures
        self.calls = 0

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        self.calls += 1
        if self.calls <= self._failures:
            raise RuntimeError("outage")
        yield StreamChunk(turn=AssistantTurn(text="recovered", finish_reason="stop"))


def test_retry_reruns_failed_turn_without_new_user_message(tmp_path):
    provider = FlakyProvider(failures=1)
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def scenario():
        first = [ev async for ev in engine.run("hello")]
        second = [ev async for ev in engine.retry()]
        return first, second

    first, second = asyncio.run(scenario())
    assert first[-1].type == EventType.ERROR
    assert second[-1].type == EventType.TURN_END
    # Exactly one user message — retry re-runs, it doesn't re-ask.
    assert sum(1 for m in engine.messages if m.get("role") == "user") == 1
    assert engine.messages[-1]["content"] == "recovered"


def test_retry_is_noop_unless_tail_is_error_notice(tmp_path):
    engine = TurnEngine(
        provider=OneTurnProvider(AssistantTurn(text="done", finish_reason="stop")),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def scenario():
        async for _ in engine.run("hello"):
            pass
        return [ev async for ev in engine.retry()]

    # A completed session must not grow a second answer from a stray retry frame.
    assert asyncio.run(scenario()) == []
    assert engine.messages[-1]["content"] == "done"


def test_stop_while_awaiting_approval(tmp_path):
    async def never_answers(_req):
        await asyncio.Event().wait()  # a pending approval card nobody answers

    registry = ToolRegistry()

    def write_file(path: str, content: str):  # pragma: no cover — never approved
        raise AssertionError("executed while awaiting approval")

    registry.register(write_file)
    engine = TurnEngine(
        provider=OneTurnProvider(_tool_turn([("write_file", {"path": "x", "content": "y"})])),
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        approver=never_answers,
    )

    async def run():
        events = []
        async for ev in engine.run("go"):
            events.append(ev)
            if ev.type == EventType.PERMISSION_REQUIRED:
                engine.request_interrupt()
        return events

    events = asyncio.run(run())
    assert events[-1].type == EventType.INTERRUPTED
    (result,) = _tool_results(engine)
    assert "interrupted by user" in result["content"]


def test_stop_skips_remaining_tool_calls(tmp_path):
    registry = ToolRegistry()
    holder = {}

    def first_tool():
        """Runs, then the user hits Stop while it holds the turn."""
        holder["engine"].request_interrupt()
        return {"ok": True}

    def second_tool():  # pragma: no cover — must never run
        raise AssertionError("second tool executed after stop")

    registry.register(first_tool)
    registry.register(second_tool)

    async def approve(_req):
        return ApprovalOutcome.ONCE

    engine = TurnEngine(
        provider=OneTurnProvider(_tool_turn([("first_tool", {}), ("second_tool", {})])),
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        approver=approve,
    )
    holder["engine"] = engine

    async def run():
        return [ev async for ev in engine.run("go")]

    events = asyncio.run(run())
    assert events[-1].type == EventType.INTERRUPTED
    results = _tool_results(engine)
    assert len(results) == 2  # both calls answered — no orphans
    assert "interrupted by user" in results[1]["content"]


def test_stop_before_parallel_batch_dispatch_skips_whole_batch(tmp_path):
    """The serial loop below already checks `self._cancel` per call before running it
    (`test_stop_skips_remaining_tool_calls`). The parallel-safe batch above it used to
    have no such check: once a turn's remaining calls were all low-risk and parallel-safe,
    Stop being set before `asyncio.gather` dispatched them made no difference — the whole
    batch still ran. Stop pressed while the two calls are still being proposed (before the
    batch is split off and dispatched) must now skip the entire batch, with every call
    getting the same stop-path answer the serial loop gives its own skipped calls."""
    registry = ToolRegistry()

    def read_a():  # pragma: no cover — must never run, batch is skipped
        raise AssertionError("read_a executed after stop")

    def read_b():  # pragma: no cover — must never run, batch is skipped
        raise AssertionError("read_b executed after stop")

    read_a.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="read_a", category="test", risk_level="low", requires_approval=False,
    )
    read_b.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="read_b", category="test", risk_level="low", requires_approval=False,
    )
    registry.register(read_a)
    registry.register(read_b)

    engine = TurnEngine(
        provider=OneTurnProvider(_tool_turn([("read_a", {}), ("read_b", {})])),
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def run():
        events = []
        async for ev in engine.run("go"):
            events.append(ev)
            # Both calls are read-only (no approval card), so the only hook available
            # before dispatch is their TOOL_PROPOSED events — Stop lands after the
            # second is proposed, still before the batch is split off and gathered.
            if ev.type == EventType.TOOL_PROPOSED and ev.data["name"] == "read_b":
                engine.request_interrupt()
        return events

    events = asyncio.run(run())
    assert events[-1].type == EventType.INTERRUPTED
    results = _tool_results(engine)
    assert len(results) == 2  # both calls answered — no orphans
    assert all("interrupted by user" in r["content"] for r in results)
    # Same stop-path shape the serial loop's own skipped calls get.
    finished = [ev for ev in events if ev.type == EventType.TOOL_FINISHED]
    assert all(
        ev.data == {"name": ev.data["name"], "status": "interrupted", "reason": "stopped"}
        for ev in finished
    )


def _engine(tmp_path, provider):
    return TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )


def test_a_stop_relayed_into_a_child_engine_never_pays_for_a_model_call(tmp_path):
    """The `explore` shape (tools/subagent.py), where a Stop routinely lands in the one
    window nothing used to check: `run()` clears the flag as its first act, so the relay
    hook can only be attached on the child's FIRST event — and `add_interrupt_hook` fires
    it on the spot when a Stop is already pending. The child therefore starts its loop with
    the flag already set, and used to spend a whole model round-trip before the check after
    the stream looked at it. The answer to that call is discarded either way; the bill is
    not."""
    parent_turn = AssistantTurn(text="p", finish_reason="stop")
    parent = _engine(tmp_path, OneTurnProvider(parent_turn))
    child_provider = OneTurnProvider(AssistantTurn(text="report", finish_reason="stop"))
    child = _engine(tmp_path, child_provider)
    parent.request_interrupt()  # pressed while `explore` was still being dispatched

    async def run():
        events, detach = [], []
        async for ev in child.run("research this"):
            if not detach:  # `_relay_stop()`: first event, once per call
                detach.append(parent.add_interrupt_hook(child.request_interrupt))
            events.append(ev)
        for remove in detach:
            remove()
        return events

    events = asyncio.run(run())

    assert child_provider.calls == 0, "the stopped child still paid for a model round"
    assert [ev.type for ev in events] == [EventType.TURN_START, EventType.INTERRUPTED]
    assert child.messages[-1]["kind"] == "interrupted"


def _suspended_history(call_id="call_r", name="list_files", arguments="{}"):
    """A persisted thread stopped at an UNANSWERED trailing tool call — what durable
    resume rebuilds from (`_unanswered_trailing_tool_calls` reads exactly this shape)."""
    return [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        },
    ]


def _resume_engine(tmp_path, provider, messages):
    registry = ToolRegistry()
    registry.register_all(ai.toolkits.files(root=str(tmp_path)))  # read-only: no approval
    return TurnEngine(
        provider=provider,
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        messages=messages,
    )


def _orphans(engine):
    """tool_calls in history with no matching tool result — hosted chat templates reject
    them, and durable resume would re-prompt them."""
    answered = {m.get("tool_call_id") for m in engine.messages if m.get("role") == "tool"}
    return [
        tc.get("id")
        for m in engine.messages
        if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
        if tc.get("id") not in answered
    ]


def test_stop_during_a_durable_resume_still_ends_the_turn_out_loud(tmp_path):
    """A resume the user stops must end like every other stopped turn. It used to return
    straight after ITERATION_END — no INTERRUPTED event, no interrupted notice — so the
    transcript read as a resume that simply finished. Same silence the severed-stream work
    went after, reached through the durable-resume door instead of the streaming one."""
    provider = OneTurnProvider(AssistantTurn(text="never", finish_reason="stop"))
    engine = _resume_engine(tmp_path, provider, _suspended_history())

    async def run():
        events = []
        async for ev in engine.resume():
            # `resume()` clears the flag as its first act, so the Stop can only be staged
            # from here — which is also when it really lands (the user presses it while
            # the re-processed call is being answered).
            if ev.type == EventType.TURN_START:
                engine.request_interrupt()
            events.append(ev)
        return events

    events = asyncio.run(run())

    assert events[-1].type == EventType.INTERRUPTED
    assert engine.messages[-1]["role"] == "notice"
    assert engine.messages[-1]["kind"] == "interrupted"
    # …without buying a round for an answer nobody will read, and with no orphan left
    # behind: the skipped call still got its "interrupted by user" result.
    assert provider.calls == 0
    assert _orphans(engine) == []
    assert "interrupted by user" in _tool_results(engine)[0]["content"]


def test_a_durable_resume_nobody_stopped_still_finishes_the_turn(tmp_path):
    """The other half of dropping that guard: with no Stop in play the resume runs the
    tool, enters the model loop and completes exactly as before."""
    provider = OneTurnProvider(AssistantTurn(text="all done", finish_reason="stop"))
    engine = _resume_engine(tmp_path, provider, _suspended_history())

    async def run():
        return [ev async for ev in engine.resume()]

    events = asyncio.run(run())

    assert [ev.type for ev in events] == [
        EventType.TURN_START,
        EventType.TOOL_PROPOSED,
        EventType.TOOL_STARTED,
        EventType.TOOL_FINISHED,
        EventType.ITERATION_END,
        EventType.ASSISTANT_MESSAGE,
        EventType.TURN_END,
    ]
    assert events[-1].data["status"] == "completed"
    assert provider.calls == 1
    assert _orphans(engine) == []
    assert _tool_results(engine)[0]["tool_call_id"] == "call_r"
    assert not [m for m in engine.messages if m.get("role") == "notice"]


def test_interrupt_hook_fires(tmp_path):
    fired = []
    engine = TurnEngine(
        provider=OneTurnProvider(AssistantTurn(text="hi", finish_reason="stop")),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        interrupt_hooks=[lambda: fired.append(True)],
    )
    engine.request_interrupt()
    assert fired == [True]


class ReasoningStreamProvider(ProviderClient):
    """Streams thinking deltas, then answer text — a DeepSeek-style reasoning model."""

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        yield StreamChunk(reasoning_delta="hmm, ")
        yield StreamChunk(reasoning_delta="let me think")
        yield StreamChunk(text_delta="the answer")
        yield StreamChunk(
            turn=AssistantTurn(
                text="the answer", finish_reason="stop", reasoning="hmm, let me think"
            )
        )


def test_reasoning_streams_persists_and_never_reaches_providers(tmp_path):
    engine = TurnEngine(
        provider=ReasoningStreamProvider(),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="deepseek:deepseek-v4-pro",
    )

    async def run():
        return [ev async for ev in engine.run("go")]

    events = asyncio.run(run())
    deltas = [ev.data["text"] for ev in events if ev.type == EventType.REASONING_DELTA]
    assert deltas == ["hmm, ", "let me think"]
    final = next(ev for ev in events if ev.type == EventType.ASSISTANT_MESSAGE)
    assert final.data["reasoning"] == "hmm, let me think"
    persisted = engine.messages[-1]
    assert persisted["reasoning"] == "hmm, let me think"
    # Display-only: stripped from every provider feed.
    assert all("reasoning" not in m for m in engine._outbound_messages())


def test_stop_during_thinking_keeps_partial_reasoning(tmp_path):
    class EndlessThinkingProvider(ProviderClient):
        def complete(self, **kwargs):  # pragma: no cover
            raise NotImplementedError

        def capabilities(self, model):
            return ModelCapabilities()

        def stream(self, *, model, messages, tools=None, **settings):
            for i in range(200):
                yield StreamChunk(reasoning_delta=f"t{i} ")
                time.sleep(0.01)
            yield StreamChunk(turn=AssistantTurn(text="done", finish_reason="stop"))

    engine = TurnEngine(
        provider=EndlessThinkingProvider(),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def run():
        events = []
        async for ev in engine.run("go"):
            events.append(ev)
            if ev.type == EventType.REASONING_DELTA and len(events) > 3:
                engine.request_interrupt()
        return events

    events = asyncio.run(run())
    assert events[-1].type == EventType.INTERRUPTED
    partial = engine.messages[-2]  # [-1] is the interrupted notice
    assert partial["role"] == "assistant" and partial["reasoning"].startswith("t0 ")


def test_retry_survives_model_switches(tmp_path):
    """Error → switch models (one or more times) → Retry must still re-run, on the NEW
    model (owner-hit 2026-07-23: the switch notices consumed the retry guard)."""
    provider = FlakyProvider(failures=1)
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gemini:gemini-3.6-flash",
    )

    async def scenario():
        first = [ev async for ev in engine.run("hello")]
        assert engine.switch_model("gemini:gemini-3.1-pro-preview") is not None
        assert engine.switch_model("gpt-5.6-sol") is not None
        second = [ev async for ev in engine.retry()]
        return first, second

    first, second = asyncio.run(scenario())
    assert first[-1].type == EventType.ERROR
    assert second[-1].type == EventType.TURN_END
    assert engine.model == "gpt-5.6-sol"
    assert engine.messages[-1]["content"] == "recovered"
    # Still exactly one user message; and a completed session stays retry-proof.
    assert sum(1 for m in engine.messages if m.get("role") == "user") == 1
    assert asyncio.run(_drain_retry(engine)) == []


async def _drain_retry(engine):
    return [ev async for ev in engine.retry()]


def test_retry_looks_through_answer_superseded_notices_only(tmp_path):
    """An `answer_superseded` notice (manager `_note_superseded_answer`) is bookkeeping
    written whenever a stale Inbox answer comes in — which can be right after a failure.
    It must not consume the Retry, and the retry keeps it in place. Looking through it
    does not make a completed turn retriable, and it is not a licence to look through
    every notice: an `interrupted` one after the error still ends the Retry."""
    provider = FlakyProvider(failures=1)
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    def superseded() -> None:
        engine._append_notice(
            "answer_superseded", "not applied", prompt="approval", resolution="allow"
        )

    async def scenario():
        first = [ev async for ev in engine.run("hello")]
        superseded()
        engine.switch_model("gpt-5.6-sol")  # ...and a model switch after it, too
        superseded()
        assert engine._tail_is_retriable_error() is True
        engine._append_notice("interrupted")
        assert engine._tail_is_retriable_error() is False
        engine.messages.pop()  # back to [..., error, superseded, switch, superseded]
        second = [ev async for ev in engine.retry()]
        return first, second

    first, second = asyncio.run(scenario())
    assert first[-1].type == EventType.ERROR
    assert second[-1].type == EventType.TURN_END
    assert engine.messages[-1]["content"] == "recovered"
    kinds = [m.get("kind") for m in engine.messages if m.get("role") == "notice"]
    assert kinds == ["error", "answer_superseded", "model_switch", "answer_superseded"]
    # Completed now: a superseded notice after an answer is no Retry.
    superseded()
    assert engine._tail_is_retriable_error() is False
    assert asyncio.run(_drain_retry(engine)) == []
