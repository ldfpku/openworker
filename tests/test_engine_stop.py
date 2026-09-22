"""Stop-button semantics: interrupt must bite in EVERY engine state, not just the
between-iterations checkpoint (v0.1.4 shipped with that as the only one — ledgered
2026-07-21). History invariant throughout: every tool_call gets a tool result, since
hosted chat templates reject orphans and durable-resume re-prompts them."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import aisuite as ai
from coworker.agent import build_engine
from coworker.agents import cowork_agent
from coworker.engine import ApprovalOutcome, TurnEngine
from coworker.events import EventType
from coworker.mcp import build_callables
from coworker.mcp.config import MCPServerDef
from coworker.permissions import Mode, PermissionEngine
from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    ToolCall,
)
from coworker.risk import RiskClass, classify
from coworker.tools import ToolRegistry
from coworker.tools.subagent import _run_without_joining_executor


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


# -- Stop that does not wait for the tool (2026-09-22) --------------------------------
#
# Two mechanisms, deliberately separate. MCP calls are genuinely CANCELLED (the future the
# worker thread is blocked on is cancelled from an interrupt hook), so their result is
# accurate. Everything else the classification calls side-effect-free is merely ABANDONED:
# the thread runs on and its result is discarded, which is why it may only ever apply
# where discarding the result is the whole loss.


def _run_tool_engine(tmp_path, registry, calls, **kwargs):
    kwargs.setdefault("permissions", PermissionEngine(workspace_root=tmp_path))
    return TurnEngine(
        provider=OneTurnProvider(_tool_turn(calls)),
        registry=registry,
        model="gpt-5.5",
        **kwargs,
    )


def _stop_once_started(engine, started):
    """Press Stop from outside, as the user does: once the tool is really running."""

    def press():
        started.wait(10)
        engine.request_interrupt()

    thread = threading.Thread(target=press, daemon=True)
    thread.start()
    return thread


def _finished_events(events):
    return [ev for ev in events if ev.type == EventType.TOOL_FINISHED]


def test_stop_abandons_the_wait_for_a_read_tool(tmp_path):
    """The shape this exists for: a read that is still running when the user stops. The
    turn must not sit through the rest of it. The gate is released in `finally`, so the
    pinned worker thread is never left behind whatever the assertions do."""
    registry = ToolRegistry()
    started, release = threading.Event(), threading.Event()

    def slow_read():
        """A read that is still running when Stop lands."""
        started.set()
        release.wait(10)  # the tool's own runtime, as far as the turn is concerned
        return {"rows": 3}

    registry.register(slow_read)
    engine = _run_tool_engine(tmp_path, registry, [("slow_read", {})])

    async def scenario():
        _stop_once_started(engine, started)
        clock = time.monotonic()
        events = [ev async for ev in engine.run("go")]
        elapsed = time.monotonic() - clock
        # Read the side table BEFORE the thread finishes: the done-callback pops it too,
        # so checking afterwards would pass even if the abandon leaked it.
        tables = (
            dict(engine._tool_started_at),
            dict(engine._approval_origins),
            dict(engine._standing_notes),
        )
        # Let the abandoned thread finish while the loop is still alive, so its
        # done-callback really runs (a closed loop simply never runs it).
        release.set()
        await asyncio.sleep(0.3)
        return events, elapsed, tables

    try:
        events, elapsed, tables = asyncio.run(scenario())
    finally:
        release.set()

    assert elapsed < 10 / 3, f"the turn waited {elapsed:.2f}s for an abandoned tool"
    finished = _finished_events(events)
    assert [ev.data["status"] for ev in finished] == ["abandoned"]
    # No orphan: the call has exactly one tool result, and it tells the model the tool
    # DID run — otherwise the next turn re-runs a call that already happened.
    results = _tool_results(engine)
    assert len(results) == 1
    answer = json.loads(results[0]["content"])
    assert answer == {
        "error": "tool result unavailable",
        "reason": (
            "stopped waiting for the tool; it may have completed after the stop"
        ),
        "executed": True,
    }
    # The real result never arrives late, and the per-call side tables are clear.
    assert len(_tool_results(engine)) == 1
    assert tables == ({}, {}, {})
    assert engine._tool_started_at == {}


def test_abandoning_clears_the_approval_origin_table(tmp_path):
    """`_approval_origins` only fills where a call was allowed without a card — here
    bypass-approvals mode. Abandoning must clear it: nothing will ever come back for this
    tool_call.id, and `_record_result` (which normally pops it) never runs."""
    registry = ToolRegistry()
    started, release = threading.Event(), threading.Event()

    def web_fetch(url: str):
        """Read-only network, and consequential enough to be annotated in bypass mode."""
        started.set()
        release.wait(10)
        return {"body": "..."}

    registry.register(web_fetch)
    engine = _run_tool_engine(
        tmp_path,
        registry,
        [("web_fetch", {"url": "https://example.invalid/x"})],
        permissions=PermissionEngine(
            workspace_root=tmp_path, mode=Mode.BYPASS_APPROVALS
        ),
    )

    async def scenario():
        _stop_once_started(engine, started)
        events = [ev async for ev in engine.run("go")]
        tables = dict(engine._approval_origins), dict(engine._tool_started_at)
        # Release inside the loop: `asyncio.run` waits for its default executor on the way
        # out, so a still-blocked worker thread would hold the test for the gate's timeout.
        release.set()
        await asyncio.sleep(0.05)
        return (events, *tables)

    try:
        events, origins, started_at = asyncio.run(scenario())
    finally:
        release.set()

    assert [ev.data["status"] for ev in _finished_events(events)] == ["abandoned"]
    assert origins == {} and started_at == {}


def test_an_abandoned_tool_that_blows_up_is_logged_and_changes_nothing(tmp_path, caplog):
    """An exception raised after the turn stopped waiting is swallowed — but not
    silently. The history it can no longer touch must be exactly what the abandon
    wrote."""
    registry = ToolRegistry()
    started, release = threading.Event(), threading.Event()

    def slow_read():
        """Raises, but only after the user has already stopped."""
        started.set()
        release.wait(10)
        raise RuntimeError("blew up after the stop")

    registry.register(slow_read)
    engine = _run_tool_engine(tmp_path, registry, [("slow_read", {})])

    async def scenario():
        _stop_once_started(engine, started)
        events = [ev async for ev in engine.run("go")]
        release.set()
        await asyncio.sleep(0.3)
        return events

    with caplog.at_level(logging.WARNING, logger="coworker.engine"):
        try:
            asyncio.run(scenario())
        finally:
            release.set()

    assert len(_tool_results(engine)) == 1
    assert "tool result unavailable" in _tool_results(engine)[0]["content"]
    # `_execute_sync` catches the exception before the thread ever raises, so the line
    # names the error status it turned into — including the exception type.
    logged = [r.getMessage() for r in caplog.records]
    assert any(
        "abandoned tool slow_read finished" in m
        and "status=error" in m
        and "RuntimeError" in m
        for m in logged
    ), logged


def test_an_abandoned_tool_result_is_never_recorded_as_a_product(tmp_path):
    """The done-callback's hard limit: it logs and audits, and touches nothing else. A
    late `_record_result` would append a second result for the same tool_call_id and file
    the call in the Artifacts panel for a turn the user stopped."""
    registry = ToolRegistry()
    started, release = threading.Event(), threading.Event()
    recorded = []

    def slow_read():
        """Comes back with a perfectly good result, far too late to use."""
        started.set()
        release.wait(10)
        return {"rows": 3}

    registry.register(slow_read)
    engine = _run_tool_engine(tmp_path, registry, [("slow_read", {})])
    engine._agent_files.record = lambda *a, **k: recorded.append(a)

    async def scenario():
        _stop_once_started(engine, started)
        async for _ in engine.run("go"):
            pass
        before = list(engine.messages)
        release.set()
        await asyncio.sleep(0.3)
        return before

    try:
        before = asyncio.run(scenario())
    finally:
        release.set()

    assert recorded == []
    assert engine.messages == before


def test_a_write_tool_is_still_waited_out(tmp_path):
    """Unchanged behaviour for anything that is not classified side-effect-free: the turn
    waits for it, because its result is the only record of what it did."""
    registry = ToolRegistry()
    started, release = threading.Event(), threading.Event()

    def write_file(path: str, content: str):
        """Named for the classification: `risk.WRITE_TOOLS` pins this one by name."""
        started.set()
        release.wait(10)
        return {"written": path, "bytes": len(content)}

    registry.register(write_file)

    async def approve(_req):
        return ApprovalOutcome.ONCE

    target = str(tmp_path / "out.txt")
    engine = _run_tool_engine(
        tmp_path,
        registry,
        [("write_file", {"path": target, "content": "hi"})],
        approver=approve,
    )

    async def scenario():
        _stop_once_started(engine, started)
        releaser = threading.Timer(0.4, release.set)
        releaser.start()
        try:
            return [ev async for ev in engine.run("go")]
        finally:
            releaser.cancel()

    try:
        events = asyncio.run(scenario())
    finally:
        release.set()

    finished = _finished_events(events)
    assert [ev.data["status"] for ev in finished] == ["ok"]
    assert "written" in _tool_results(engine)[0]["content"]


def test_a_read_tool_nobody_stopped_is_unaffected(tmp_path):
    registry = ToolRegistry()

    def quick_read():
        """The ordinary path: no Stop anywhere near it."""
        return {"rows": 1}

    registry.register(quick_read)
    engine = _run_tool_engine(tmp_path, registry, [("quick_read", {})])

    # `OneTurnProvider` re-issues the same call every round, so the turn runs it until
    # the iteration cap; the first one is the one under test.
    events = asyncio.run(_drain(engine))
    assert _finished_events(events)[0].data["status"] == "ok"
    assert json.loads(_tool_results(engine)[0]["content"]) == {"rows": 1}
    assert engine._tool_started_at == {}


async def _drain(engine):
    return [ev async for ev in engine.run("go")]


def _abandon_case(tmp_path, tool_name, arguments=None, approver=None):
    """Run one tool that is still going when Stop lands; return its finished status."""
    registry = ToolRegistry()
    started, release = threading.Event(), threading.Event()

    def body(path: str = "", content: str = ""):
        started.set()
        release.wait(10)
        return {"ok": True}

    body.__name__ = tool_name
    body.__doc__ = "Still running when the user stops."
    registry.register(body)
    engine = _run_tool_engine(
        tmp_path,
        registry,
        [(tool_name, arguments or {})],
        **({"approver": approver} if approver else {}),
    )

    async def scenario():
        _stop_once_started(engine, started)
        releaser = threading.Timer(1.0, release.set)  # so `none`/write cases terminate
        releaser.start()
        try:
            events = [ev async for ev in engine.run("go")]
        finally:
            releaser.cancel()
        release.set()
        await asyncio.sleep(0.3)
        return events

    try:
        events = asyncio.run(scenario())
    finally:
        release.set()
    return [ev.data["status"] for ev in _finished_events(events)]


def test_abandon_switch_auto_all_none(tmp_path, monkeypatch):
    """`OPENWORKER_STOP_ABANDONS_TOOLS`: `auto` (default) goes by the classification,
    `all` abandons regardless of it, `none` restores waiting for everything."""

    async def approve(_req):
        return ApprovalOutcome.ONCE

    write_args = {"path": str(tmp_path / "o.txt"), "content": "x"}

    monkeypatch.delenv("OPENWORKER_STOP_ABANDONS_TOOLS", raising=False)
    assert _abandon_case(tmp_path, "read_thing") == ["abandoned"]
    assert _abandon_case(tmp_path, "write_file", write_args, approve) == ["ok"]

    monkeypatch.setenv("OPENWORKER_STOP_ABANDONS_TOOLS", "none")
    assert _abandon_case(tmp_path, "read_thing") == ["ok"]

    monkeypatch.setenv("OPENWORKER_STOP_ABANDONS_TOOLS", "all")
    assert _abandon_case(tmp_path, "write_file", write_args, approve) == ["abandoned"]

    monkeypatch.setenv("OPENWORKER_STOP_ABANDONS_TOOLS", "nonsense")
    assert _abandon_case(tmp_path, "read_thing") == ["abandoned"]


def test_all_mode_abandons_a_write_without_stopping_it(tmp_path, monkeypatch):
    """What `all` actually buys, so the docstring's warning is a checked statement.

    Abandoning never stops a tool; it stops WAITING for one. Under `all` that reaches
    the writes as well, so the file is written exactly as it would have been and the
    turn ends telling the model the result is unavailable. Nobody should arrive here by
    accident — it takes setting the environment variable by hand — but the option exists
    and this is its shape.
    """
    monkeypatch.setenv("OPENWORKER_STOP_ABANDONS_TOOLS", "all")
    target = tmp_path / "written-after-the-stop.txt"
    registry = ToolRegistry()
    started, release, written = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def write_file(path: str, content: str):
        """Still running when the user stops; finishes the write regardless."""
        started.set()
        release.wait(10)
        Path(path).write_text(content, encoding="utf-8")
        written.set()
        return {"ok": True}

    registry.register(write_file)

    async def approve(_req):
        return ApprovalOutcome.ONCE

    engine = _run_tool_engine(
        tmp_path,
        registry,
        [("write_file", {"path": str(target), "content": "landed"})],
        approver=approve,
    )

    async def scenario():
        _stop_once_started(engine, started)
        return [ev async for ev in engine.run("go")]

    try:
        events = _run_without_joining_executor(scenario())
        stopped_before_the_write = not written.is_set()
    finally:
        release.set()  # never leave the worker thread behind
    assert written.wait(10)

    assert stopped_before_the_write, "the turn outlasted the write; nothing was abandoned"
    assert [ev.data["status"] for ev in _finished_events(events)] == ["abandoned"]
    assert json.loads(_tool_results(engine)[0]["content"])["executed"] is True
    # The write landed anyway — that is the trade, not a bug.
    assert target.read_text(encoding="utf-8") == "landed"


def _fake_mcp_tool(name):
    return SimpleNamespace(
        name=name,
        description=f"{name} tool",
        inputSchema={"type": "object", "properties": {}},
    )


def test_stop_cancels_an_in_flight_mcp_call(tmp_path):
    """MCP is the one batch that can be stopped for real: the future the worker thread is
    blocked on is cancelled from an interrupt hook, so the request is dropped instead of
    merely un-awaited, and the recorded result is the accurate one — `run_shell`'s shape
    when `interrupt_now` cuts it short."""
    started = threading.Event()
    entered = []

    async def call_async(tool, args):
        entered.append(tool)
        started.set()
        await asyncio.sleep(30)  # a server that never answers
        raise AssertionError("the MCP call was not cancelled")

    async def scenario():
        loop = asyncio.get_running_loop()
        registry = ToolRegistry()
        engine = _run_tool_engine(
            tmp_path, registry, [("mcp__srv__hang", {})]
        )
        registry.register_all(
            build_callables(
                MCPServerDef(name="srv", transport="stdio", requires_approval=False),
                [_fake_mcp_tool("hang")],
                call_async,
                loop,
                register_stop_hook=engine.add_interrupt_hook,
            )
        )
        _stop_once_started(engine, started)
        clock = time.monotonic()
        events = [ev async for ev in engine.run("go")]
        return engine, events, time.monotonic() - clock

    engine, events, elapsed = asyncio.run(scenario())

    assert entered == ["hang"]
    assert elapsed < 1.0, f"the stopped turn took {elapsed:.2f}s to end"
    # Not "abandoned": a cancelled MCP call has a real answer, so it is recorded as one.
    assert [ev.data["status"] for ev in _finished_events(events)] == ["ok"]
    assert json.loads(_tool_results(engine)[0]["content"]) == {
        "error": "interrupted by user"
    }
    # And the hook is detached again, so the future cannot outlive the call.
    assert engine._interrupt_hooks == []


def test_mcp_tools_are_cancelled_rather_than_abandoned(tmp_path):
    """The exclusion that keeps the two mechanisms from fighting. An MCP tool classifies
    READ whenever its server does not require approval, so without this it would be
    abandoned — and the abandon would win the race against its own cancellation, turning
    an accurate "interrupted by user" into "result unavailable"."""
    registry = ToolRegistry()
    registry.register_all(
        build_callables(
            # A connector-backed server pins approval per tool, so its READ tools really
            # do arrive here with `requires_approval=False` (manager `prepare_mcp_tools`).
            MCPServerDef(name="srv", transport="stdio", requires_approval=False),
            [_fake_mcp_tool("hang")],
            lambda tool, args: None,
            asyncio.new_event_loop(),
        )
    )
    engine = _run_tool_engine(tmp_path, registry, [("mcp__srv__hang", {})])
    call = ToolCall(id="c0", name="mcp__srv__hang", arguments={})
    spec = registry.get("mcp__srv__hang")
    assert classify(call.name, spec.metadata) is RiskClass.READ  # …and yet:
    assert engine._abandonable(call) is False


def test_explore_is_stopped_for_real_rather_than_abandoned(tmp_path):
    """Same exclusion, same reason, different mechanism: `explore` relays the parent's
    Stop into its child engine and comes back with the partial report (tools/subagent.py,
    landed 2026-09-19). It classifies READ — low risk, no approval — so without the
    exclusion the parent would stop waiting and throw that report away. The behaviour this
    protects is pinned end-to-end by tests/test_subagent.py's stop tests."""
    registry = ToolRegistry()

    def explore(task: str):
        """Stands in for tools/subagent.py's tool: same name, same classification."""
        return {"report": "…"}

    registry.register(
        ai.tool(
            explore,
            metadata=ai.ToolMetadata(
                category="search",
                risk_level="low",
                capabilities=["search"],
                requires_approval=False,
            ),
        )
    )
    engine = _run_tool_engine(tmp_path, registry, [("explore", {"task": "x"})])
    call = ToolCall(id="c0", name="explore", arguments={"task": "x"})
    assert classify(call.name, registry.get("explore").metadata) is RiskClass.READ
    assert engine._abandonable(call) is False


def test_the_pool_pressure_warning_rearms_between_bursts(tmp_path, caplog, monkeypatch):
    """Abandoned threads sit in the loop's DEFAULT executor, which `_astream` also uses
    for the provider's stream producer — so a full pool delays the next MODEL call, and
    this warning is the only place that says so. It is about a BURST, and it was a
    module-level one-shot that nothing ever reset: a process reported its first burst and
    went quiet through every later one. Counters are patched through `monkeypatch` so the
    process-wide state is restored for the rest of the suite.
    """
    from coworker import engine as engine_module

    monkeypatch.setattr(engine_module, "_default_thread_pool_size", lambda: 2)
    monkeypatch.setattr(engine_module, "_abandoned_live", 0)
    monkeypatch.setattr(engine_module, "_abandoned_warned", False)

    registry = ToolRegistry()

    def read_thing():
        """Never actually run here: the futures below stand in for its threads."""
        return {}

    registry.register(read_thing)
    engine = _run_tool_engine(tmp_path, registry, [("read_thing", {})])

    def warnings_so_far():
        return sum("thread pool holds" in r.getMessage() for r in caplog.records)

    async def two_bursts():
        counted = []
        for burst in range(2):
            futures = []
            for i in range(2):  # pool // 2 == 1, so the second one trips the warning
                fut = asyncio.get_running_loop().create_future()
                engine._abandon_tool_wait(
                    ToolCall(id=f"b{burst}-{i}", name="read_thing", arguments={}), fut
                )
                futures.append(fut)
            for fut in futures:
                fut.set_result(({"rows": 1}, "ok"))  # the thread comes back
            await asyncio.sleep(0)
            await asyncio.sleep(0)  # let the done-callbacks run
            counted.append(warnings_so_far())
        return counted

    with caplog.at_level(logging.WARNING, logger="coworker.engine"):
        counted = asyncio.run(two_bursts())

    assert counted == [1, 2], counted
    assert engine_module._abandoned_live == 0


def test_read_classified_tools_that_mutate_are_waited_out(tmp_path):
    """`RiskClass.READ` is risk.py's FALLBACK for a tool it does not know that declares no
    approval — not a promise that the tool is pure. Four of the real ones mutate:

    * `load_skill` mounts the skill's folder on the session's SHARED roots list
      (skills/base.py `_mount`), widening what the session may read — after the stop, and
      invisibly, since the model never sees the result. It is also the only one that can
      be slow enough to be abandoned for real (a catalog miss walks the disk).
    * `shell_task_output` is a destructive read: `read_new` advances a cursor, so an
      abandoned call eats that slice of the background task's output for good.
    * `todo_write` rewrites the session's todo list; `shell_task_kill` kills a task.
    * `browser_wait` and `browser_read_page` go through `_BrowserController.call`, which
      occupies the process-wide single-worker browser executor and writes the GUI's
      `_state` on the success path. `test_a_stopped_browser_wait_is_waited_out` below is
      the behavioural half of this.

    So does every on-demand loader: `_load` calls `registry.register_all`, mutating the
    dict the loop iterates unlocked in `schemas()` every round trip. Nothing could outlive
    a turn before this branch, which is exactly the guarantee abandoning removes.

    Built from the real registry, not from hand-made metadata, so a tool that is renamed
    or re-categorised is caught here.
    """
    engine = build_engine(agent=cowork_agent(), workspace=tmp_path, roots=[])
    registry = engine.registry
    for name in list(getattr(registry, "_deferred", {})):
        registry.get(name)  # materialise the deferred sets so they can be classified

    def abandonable(name):
        return engine._abandonable(ToolCall(id="c0", name=name, arguments={}))

    mutating_reads = [
        "load_skill",
        "shell_task_output",
        "todo_write",
        "shell_task_kill",
        "browser_wait",
        "browser_read_page",
    ]
    loaders = [n for n in registry._tools if n.startswith("load_") and n.endswith("_tools")]
    assert loaders, "expected the on-demand loaders to be registered"
    for name in mutating_reads + loaders:
        spec = registry.get(name)
        # Each really does arrive here classified READ — that is the whole problem.
        assert classify(name, spec.metadata) is RiskClass.READ, name
        assert abandonable(name) is False, name

    # …and the exclusions are surgical: ordinary reads are still abandoned.
    for name in ("read_file", "grep", "list_files", "web_fetch"):
        assert abandonable(name) is True, name


def test_the_auto_abandon_set_is_exactly_the_tools_that_were_audited(tmp_path):
    """The whole `auto` set, pinned by name.

    Every tool in the `cowork` persona's registry (deferred sets materialised) was walked
    one at a time on 2026-09-22 against three questions: does it hold a process-wide or
    cross-session executor, lock or singleton; does either path write shared state, a
    registry, a cursor, a cache or a file; is its runtime uncapped. These seven answered
    no to all three. The point of asserting EQUALITY rather than membership is that a new
    tool cannot slip into the set unexamined — `RiskClass.READ` is risk.py's fallback, so
    joining is the default, and this line is what makes joining deliberate.

    `propose_plan` and `request_directory` are in the set only because `_abandonable`
    would say yes if asked; `test_interactive_tools_never_reach_run_tool` below shows
    they are never asked.
    """
    engine = build_engine(agent=cowork_agent(), workspace=tmp_path, roots=[])
    registry = engine.registry
    for name in list(getattr(registry, "_deferred", {})):
        registry.get(name)
    abandonable = {
        name
        for name in registry._tools
        if engine._abandonable(ToolCall(id="c0", name=name, arguments={}))
    }
    assert abandonable == {
        "read_file",
        "grep",
        "list_files",
        "web_fetch",
        "web_search",
        "propose_plan",
        "request_directory",
    }
    # The connector reads left the set with this audit: each reaches its API through a
    # credential path that WRITES (`_account_profile` → `ensure_fresh_connector_token`,
    # `_github_call` → `github_installation_token` → `fresh_access_token` →
    # `_store_cloud_tokens`), and `SecretStore.put` is a read-modify-write of the whole
    # secret file. None of them is registered in this environment — the deferred
    # connector sets only materialise where that connector is configured, which is why
    # the equality above is about the same seven names here as on a machine with GitHub
    # and Outlook connected. So the rule is pinned on a stand-in instead: an unknown
    # tool in that category, i.e. exactly how a connector read arrives at `_abandonable`.
    for category in ("connector", "meta"):

        def unregistered_read():  # pragma: no cover - never executed
            return {}

        unregistered_read.__name__ = f"a_new_{category}_read"
        unregistered_read.__aisuite_tool_metadata__ = ai.ToolMetadata(
            name=unregistered_read.__name__,
            category=category,
            risk_level="low",
            capabilities=["read"],
            requires_approval=False,
        )
        registry.register(unregistered_read)
        call = ToolCall(id="c0", name=unregistered_read.__name__, arguments={})
        # It really does arrive classified READ — that is what makes it a candidate.
        assert classify(call.name, registry.get(call.name).metadata) is RiskClass.READ
        assert engine._abandonable(call) is False, category


def test_interactive_tools_never_reach_run_tool(tmp_path):
    """Why `propose_plan` and `request_directory` being in the abandon set is harmless.

    `_handle_tool_calls` dispatches both by name and `continue`s before the call can be
    cleared for execution, so `_run_tool` — and with it `_abandonable` — never sees them.
    Asserted behaviourally rather than by reading the branch, so that moving the
    interception without moving the exclusion shows up here.
    """
    registry = ToolRegistry()

    def propose_plan(plan: str):  # pragma: no cover - never executed, that's the point
        raise AssertionError("propose_plan executed as an ordinary tool")

    registry.register(propose_plan)
    engine = _run_tool_engine(tmp_path, registry, [("propose_plan", {"plan": "x"})])
    ran = []
    engine._run_tool = lambda tc: ran.append(tc.name)  # would be awaited if reached

    async def scenario():
        return [ev async for ev in engine.run("go")]

    events = asyncio.run(scenario())
    assert ran == []
    # It still answers the model — an intercepted call is answered, not dropped.
    # (`OneTurnProvider` re-issues the same call every round trip, so there is one
    # result per iteration, not one in total.)
    results = _tool_results(engine)
    assert results and json.loads(results[0]["content"])["approved"] is False
    assert any(ev.type == EventType.TOOL_FINISHED for ev in events)


def test_a_stopped_browser_wait_is_waited_out(tmp_path, monkeypatch):
    """The behavioural half of the browser exclusion, on the real `browser_wait`.

    `browser_wait` is the worst case in the set: the only tool DESIGNED to be slow, and
    the only one whose duration the model picks without a cap — the `target` branch is
    `wait_for(timeout=max(1, int(milliseconds)))`, no clamp (the branch without a target
    clamps to 30 s). Abandoning it would leave the process-wide
    `ThreadPoolExecutor(max_workers=1)` in `_BrowserController` occupied for as long as
    the model asked for, with the turn already reported as over, and would let the tool
    write `_BROWSER._state` — what `GET /v1/browser/state` serves the GUI panel — after
    the stop, where the model never sees it.

    Playwright is not installed here, so `_BROWSER.page()` is stubbed with a page whose
    `wait_for_timeout` blocks on a gate; everything between the engine and that gate is
    the real code path. The loop is a long-lived one (`_run_without_joining_executor`,
    i.e. `asyncio.run` minus the executor join): plain `asyncio.run` would join an
    abandoned thread on the way out and hide the very difference this pins.
    """
    from coworker.connectors.browser_automation import (
        _BROWSER,
        make_browser_automation_tools,
    )

    started, release = threading.Event(), threading.Event()

    class _GatedPage:
        url = "https://example.invalid/page"

        def wait_for_timeout(self, milliseconds):
            started.set()
            release.wait(10)

    monkeypatch.setattr(_BROWSER, "page", lambda: (_GatedPage(), None))
    # `_state` is on the module-level singleton, so leave it as it was found.
    monkeypatch.setattr(_BROWSER, "_state", dict(_BROWSER._state))

    registry = ToolRegistry()
    browser_wait = next(
        fn for fn in make_browser_automation_tools() if fn.__name__ == "browser_wait"
    )
    registry.register(browser_wait)
    engine = _run_tool_engine(
        tmp_path, registry, [("browser_wait", {"milliseconds": 600000})]
    )
    assert (
        engine._abandonable(ToolCall(id="c0", name="browser_wait", arguments={}))
        is False
    )

    def release_after_stop():
        started.wait(10)
        time.sleep(0.4)  # the turn must still be here when this lands
        release.set()

    async def scenario():
        _stop_once_started(engine, started)
        threading.Thread(target=release_after_stop, daemon=True).start()
        clock = time.monotonic()
        events = [ev async for ev in engine.run("go")]
        return events, time.monotonic() - clock

    try:
        events, elapsed = _run_without_joining_executor(scenario())
    finally:
        release.set()  # never leave the ONE browser worker pinned

    finished = _finished_events(events)
    assert [ev.data["status"] for ev in finished] == ["ok"], finished
    # The real result reached the model, not the "unavailable" placeholder.
    assert json.loads(_tool_results(engine)[0]["content"]) == {
        "ok": True,
        "url": "https://example.invalid/page",
    }
    assert elapsed >= 0.4, f"the turn let go of browser_wait after {elapsed:.2f}s"
    # The `_state` write the panel reads happened inside the turn, not after it.
    assert _BROWSER._state["last_action"] == "wait"
    assert _BROWSER._state["last_result"] == "ok"


def test_a_torn_down_abandoned_tool_is_not_logged_as_finished(tmp_path, caplog):
    """The done-callback's second shape, and the reason it may not assume the thread is
    over. `explore` runs its child turn on a loop of its own and tears it down the way
    `asyncio.run` does — cancel the leftover tasks, then gather them, both while the loop
    is still ALIVE (`_cancel_leftover_tasks`, tools/subagent.py). So the callback of an
    abandoned tool fires there with the thread still running, and the line it logs must
    not say the tool finished.

    This is the case the first version of this branch got wrong twice over: it said a
    CLOSED loop would swallow the callback (cancellation reaches it first) and it printed
    "finished after 0.0s" about a thread that ran on for another second.
    """
    registry = ToolRegistry()
    started, release, body_done = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def slow_read():
        """Still running when Stop lands, and still running when the loop goes away."""
        started.set()
        release.wait(10)
        body_done.set()
        return {"rows": 1}

    registry.register(slow_read)
    engine = _run_tool_engine(tmp_path, registry, [("slow_read", {})])

    async def turn():
        _stop_once_started(engine, started)
        async for _ in engine.run("go"):
            pass

    try:
        with caplog.at_level(logging.WARNING, logger="coworker.engine"):
            _run_without_joining_executor(turn())
            outlived = not body_done.is_set()
    finally:
        release.set()  # never leave the pinned worker thread behind
    assert body_done.wait(10)

    assert outlived, "this test only means anything if the thread outlives the loop"
    lines = [
        r.getMessage() for r in caplog.records if "abandoned tool slow_read" in r.getMessage()
    ]
    assert len(lines) == 1, lines
    assert "still running" in lines[0], lines[0]
    assert "finished" not in lines[0], lines[0]
