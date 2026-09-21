"""Explorer subagent tests — read-only child engine, report return, no recursion."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from coworker.events import Event, EventType
from coworker.permissions import Mode
from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    ToolCall,
)
from coworker.tools import ToolRegistry, subagent
from coworker.tools.subagent import build_explorer_engine, explorer_tools

# The gated script that makes "the explorer is running RIGHT NOW" an observable state
# instead of a lucky moment. Same object the bridge's own tests park producers with.
from test_engine import _GatedStream


def _text_turn(text):
    return AssistantTurn(text=text, finish_reason="stop")


def _tool_turn(name, args, call_id="call_1"):
    return AssistantTurn(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        finish_reason="tool_calls",
    )


def _explore_turn(*tasks):
    """One assistant turn asking for `explore` once per task."""
    return AssistantTurn(
        tool_calls=[
            ToolCall(id=f"call_{n}", name="explore", arguments={"task": task})
            for n, task in enumerate(tasks, start=1)
        ],
        finish_reason="tool_calls",
    )


class ScriptedProvider(ProviderClient):
    def __init__(self, turns):
        self._turns = list(turns)

    def complete(self, *, model, messages, tools=None, **settings):
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def test_explorer_engine_is_read_only(tmp_path):
    engine = build_explorer_engine(
        workspace=tmp_path, provider=ScriptedProvider([]), model="gpt-5.5"
    )
    names = set(engine.registry.names())
    assert {
        "grep",
        "read_file",
        "list_files",
        "git_log",
        "git_status",
        "git_diff",
    } <= names
    assert "write_file" not in names and "replace_in_file" not in names
    assert "run_shell" not in names
    assert "explore" not in names  # no recursion
    assert engine.permissions.mode is Mode.PLAN  # writes hard-blocked even if present


def test_explore_returns_final_report(tmp_path):
    (tmp_path / "a.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            _tool_turn("grep", {"pattern": "answer"}),
            _text_turn("Found it: a.py:1 defines answer() returning 42."),
        ]
    )
    reg = ToolRegistry()
    reg.register_all(
        explorer_tools(workspace=tmp_path, provider=provider, model="gpt-5.5")
    )
    spec = reg.get("explore")
    assert spec.metadata.risk_level == "low"  # parallel-safe in the parent engine

    result = reg.execute("explore", {"task": "where is answer defined?"})
    assert result["report"] == "Found it: a.py:1 defines answer() returning 42."
    assert "note" not in result  # completed normally


def test_explore_child_cannot_write(tmp_path):
    provider = ScriptedProvider(
        [
            _tool_turn("write_file", {"path": "evil.py", "content": "x"}),
            _text_turn("I was blocked; reporting findings only."),
        ]
    )
    reg = ToolRegistry()
    reg.register_all(
        explorer_tools(workspace=tmp_path, provider=provider, model="gpt-5.5")
    )
    result = reg.execute("explore", {"task": "look around"})
    assert not (tmp_path / "evil.py").exists()
    assert "report" in result


def test_explore_flags_partial_report_on_iteration_rail(tmp_path):
    # A provider that always asks for another grep: the child hits max_iterations.
    class LoopingProvider(ScriptedProvider):
        def complete(self, **kwargs):
            return _tool_turn("grep", {"pattern": "x"})

    reg = ToolRegistry()
    reg.register_all(
        explorer_tools(
            workspace=tmp_path, provider=LoopingProvider([]), model="gpt-5.5"
        )
    )
    result = reg.execute("explore", {"task": "endless"})
    assert "max_iterations" in result.get(
        "error", ""
    ) or "max_iterations" in result.get("note", "")


def test_code_engine_registers_explore_chat_does_not(tmp_path):
    from coworker.agent import build_engine
    from coworker.agents import code_agent
    from coworker.agents.chat import chat_agent

    class _Stub:
        def complete(self, **kwargs):  # pragma: no cover
            raise NotImplementedError

        def capabilities(self, model):
            return ModelCapabilities()

    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        assert "explore" in engine.registry.names()
    finally:
        engine.executor.close()

    chat = build_engine(agent=chat_agent(), provider=_Stub())
    assert "explore" not in chat.registry.names()


# -- Stop, relayed into a running explorer ---------------------------------------------

_CHILD_REPORT = "half a report, then the rest"


def _parked_explorer_stream():
    """A child answer that stops halfway through, with the rest held behind the gate.

    Parked before wire chunk 1, so the first delta has provably been delivered and the
    child is provably still streaming when the test presses Stop. `produced` then says
    exactly how much of the answer the child pulled after the gate opened — one chunk if
    the Stop reached it, the whole script if it didn't.
    """
    return _GatedStream(
        [
            StreamChunk(text_delta="half a report, "),
            StreamChunk(text_delta="then the rest"),
            StreamChunk(turn=AssistantTurn(text=_CHILD_REPORT, finish_reason="stop")),
        ],
        park_at=1,
    )


class GatedExplorerProvider(ProviderClient):
    """One provider for parent and children — `build_engine` hands the explorers its own.

    Call 1 is the parent's (it asks for `explore`); every call after that is a child's and
    gets the next gated script. Children stream from their own threads, hence the lock.
    """

    def __init__(self, parent_turn, child_scripts):
        self._parent_turn = parent_turn
        self._child_scripts = list(child_scripts)
        self._lock = threading.Lock()
        self.calls = 0

    def complete(self, **kwargs):  # pragma: no cover - streamed instead
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        with self._lock:
            self.calls += 1
            script = None if self.calls == 1 else self._child_scripts.pop(0)
        if script is None:
            yield StreamChunk(turn=self._parent_turn)
            return
        yield from script


async def _drain(engine, text, sink):
    async for event in engine.run(text):
        sink.append(event)


def _tool_results(engine):
    """Every tool result the turn recorded, decoded."""
    return [
        json.loads(m["content"])
        for m in engine.messages
        if m.get("role") == "tool" and m.get("content", "").startswith("{")
    ]


def _run_until_parked_then_stop(engine, scripts, events):
    """Start a turn, press Stop once every script has parked, and wait for the turn out.

    Stop is pressed from the loop thread, which is where the WebSocket handler presses it.
    The gates open in `finally` whatever happens: a producer left parked would sit in its
    executor thread for good, and `concurrent.futures` joins every worker when the test
    process exits.
    """

    async def _turn():
        loop = asyncio.get_running_loop()
        task = asyncio.ensure_future(_drain(engine, "go", events))
        try:
            for script in scripts:
                # Off the loop — the park is a threading.Event and the turn needs the loop.
                # The timeout is a failure bound, never part of the happy path.
                assert await loop.run_in_executor(None, script.parked.wait, 30)
            engine.request_interrupt()
        finally:
            for script in scripts:
                script.gate.set()
        await asyncio.wait_for(task, timeout=60)

    asyncio.run(_turn())


def test_stop_reaches_a_running_explore(tmp_path):
    """Stop has to land on the explorer too, not just the session that spawned it: the
    child is a whole engine of its own, on its own loop, in a worker thread."""
    from coworker.agent import build_engine
    from coworker.agents import code_agent

    script = _parked_explorer_stream()
    provider = GatedExplorerProvider(_explore_turn("where is retry handled?"), [script])
    parent = build_engine(agent=code_agent(), workspace=tmp_path, provider=provider)
    hooks_before = list(parent._interrupt_hooks)
    events: list = []

    try:
        _run_until_parked_then_stop(parent, [script], events)
    finally:
        parent.executor.close()

    # The child pulled the chunk already on its wire and nothing after it.
    assert script.produced == script.park_at + 1
    results = _tool_results(parent)
    assert len(results) == 1 and "interrupted" in json.dumps(results[0])
    assert _CHILD_REPORT not in json.dumps(results[0])
    assert events[-1].type == EventType.INTERRUPTED
    assert provider.calls == 2  # the parent's round, then the child's — no third
    assert parent._interrupt_hooks == hooks_before  # the relay hook was taken off again


def test_stop_reaches_every_explore_running_in_parallel(tmp_path):
    """Independent explores are dispatched together (low risk ⇒ parallel-safe), so one
    Stop has to land on every one of them — including the relay hooks detaching
    themselves, from their own threads, while that Stop is going round."""
    from coworker.agent import build_engine
    from coworker.agents import code_agent

    scripts = [_parked_explorer_stream(), _parked_explorer_stream()]
    provider = GatedExplorerProvider(
        _explore_turn("where is retry handled?", "where is Stop handled?"), scripts
    )
    parent = build_engine(agent=code_agent(), workspace=tmp_path, provider=provider)
    hooks_before = list(parent._interrupt_hooks)
    events: list = []

    try:
        _run_until_parked_then_stop(parent, scripts, events)
    finally:
        parent.executor.close()

    assert [s.produced for s in scripts] == [s.park_at + 1 for s in scripts]
    results = _tool_results(parent)
    assert len(results) == 2
    assert all("interrupted" in json.dumps(r) for r in results)
    assert all(_CHILD_REPORT not in json.dumps(r) for r in results)
    assert events[-1].type == EventType.INTERRUPTED
    assert provider.calls == 3  # the parent's round, then one per child
    assert parent._interrupt_hooks == hooks_before


def test_a_stop_that_lands_before_the_hook_is_attached_still_bites(tmp_path):
    """The narrow window: the tool was already dispatched when Stop was pressed, so the
    child engine has no hook yet and nothing later will ever call one. `explore` relies on
    `add_interrupt_hook` firing a hook it receives after the fact — and on attaching it no
    earlier than the child's first event, since `run()` clears the stop flag before that.

    A `register_stop_hook` that fires on registration stands in for both orderings.
    """
    removals = []

    def _already_stopped(hook):
        hook()
        return lambda: removals.append("removed")

    explore = explorer_tools(
        workspace=tmp_path,
        provider=ScriptedProvider([_text_turn("FULL REPORT")]),
        model="gpt-5.5",
        register_stop_hook=_already_stopped,
    )[0]

    result = json.dumps(explore("look around"))

    assert "interrupted" in result
    assert "FULL REPORT" not in result  # the Stop was not clear()ed away
    assert removals == ["removed"]  # detached exactly once


def test_the_stop_hook_is_detached_when_the_explorer_blows_up(tmp_path, monkeypatch):
    """The hook holds the child engine — a whole conversation history — on the parent for
    the rest of the session, so it has to come off the error path too."""
    removals = []

    class _ExplodingEngine:
        def request_interrupt(self):  # pragma: no cover - nothing fires it here
            pass

        async def run(self, task):
            yield Event(EventType.TURN_START, {"input": task})
            raise RuntimeError("the child engine died mid-turn")

    monkeypatch.setattr(subagent, "build_explorer_engine", lambda **kw: _ExplodingEngine())
    explore = explorer_tools(
        workspace=tmp_path,
        provider=ScriptedProvider([]),
        model="gpt-5.5",
        register_stop_hook=lambda hook: lambda: removals.append("removed"),
    )[0]

    with pytest.raises(RuntimeError):
        explore("look around")
    assert removals == ["removed"]


# -- a stopped explore does not wait for the read it walked away from ------------------


class _HeldChildStream:
    """A child answer whose read hangs after the first delta, for at most `hold` seconds.

    Stands in for a provider read that nothing can interrupt: the Stop ends the child's
    turn at once, but the producer thread stays inside this read until the gate opens or
    `hold` runs out. `closed` is set once the producer has let go of the stream.
    """

    def __init__(self, hold):
        self.hold = hold
        self.parked = threading.Event()
        self.gate = threading.Event()
        self.closed = threading.Event()
        self.produced = 0

    def __iter__(self):
        try:
            self.produced = 1
            yield StreamChunk(text_delta="half a report, ")
            self.parked.set()
            self.gate.wait(self.hold)
            self.produced = 2
            yield StreamChunk(text_delta="then the rest")
            self.produced = 3
            yield StreamChunk(turn=AssistantTurn(text=_CHILD_REPORT, finish_reason="stop"))
        finally:
            self.closed.set()


class _OneStreamProvider(ProviderClient):
    def __init__(self, script):
        self._script = script

    def complete(self, **kwargs):  # pragma: no cover - streamed instead
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        yield from self._script


def test_a_stopped_explore_returns_without_waiting_for_its_producer(tmp_path, monkeypatch):
    """`asyncio.run` ends by joining its default executor, for up to
    `THREAD_JOIN_TIMEOUT` — 300 seconds on 3.13. After a Stop the child's turn is over in
    milliseconds, but its producer thread is still inside a provider read that nothing can
    interrupt, so `explore` sat there until that read came back or the join gave up, and
    the parent session with it. It has to return as soon as the child's turn has ended.

    Both waits are cut to fractions of a second here so a regression fails instead of
    hanging: the join to `JOIN`, the read to `HOLD`."""
    join, hold = 0.5, 1.0
    monkeypatch.setattr(asyncio.constants, "THREAD_JOIN_TIMEOUT", join)
    script = _HeldChildStream(hold)
    stops = []

    def _register(hook):
        stops.append(hook)
        return lambda: None

    explore = explorer_tools(
        workspace=tmp_path,
        provider=_OneStreamProvider(script),
        model="gpt-5.5",
        register_stop_hook=_register,
    )[0]
    outcome = {}

    def _call():
        try:
            outcome["result"] = explore("look around")
        except BaseException as exc:  # reported below, never lost in the thread
            outcome["error"] = exc
        finally:
            outcome["returned_at"] = time.monotonic()

    worker = threading.Thread(target=_call, daemon=True)
    worker.start()
    try:
        # Failure bounds only, never part of the happy path.
        assert script.parked.wait(10)
        assert stops, "the explorer never attached its Stop relay"
        stopped_at = time.monotonic()
        stops[0]()  # the parent's Stop, relayed into the child
        worker.join(10)
        assert not worker.is_alive()
        still_reading = not script.closed.is_set()
    finally:
        script.gate.set()
        worker.join(10)

    assert "error" not in outcome, outcome.get("error")
    elapsed = outcome["returned_at"] - stopped_at
    assert elapsed < join / 2, (
        f"explore took {elapsed:.3f}s to return after Stop; its producer holds the read "
        f"for {hold}s"
    )
    assert still_reading  # it really did return with the read still in flight
    assert "interrupted" in json.dumps(outcome["result"])
    assert _CHILD_REPORT not in json.dumps(outcome["result"])
    # Released, the producer pulls the chunk that was on the wire, lets go of the stream
    # and nothing more.
    assert script.closed.wait(10)
    assert script.produced == 2


def test_the_explorer_loop_still_cleans_up_the_way_asyncio_run_does():
    """Only the executor join was dropped. Whatever the explorer leaves behind on its loop
    is still wound down: tasks cancelled and awaited, async generators finalised."""
    wound_down = []
    kept = []

    async def _answers():
        try:
            yield "first"
            yield "second"  # pragma: no cover - never reached
        finally:
            wound_down.append("generator finalised")

    async def _background():
        try:
            await asyncio.sleep(3600)  # cancelled at once; never actually waited
        except asyncio.CancelledError:
            wound_down.append("task cancelled")
            raise

    async def _main():
        asyncio.ensure_future(_background())
        answers = _answers()
        kept.append(answers)  # alive and suspended when `_main` returns
        await answers.__anext__()
        await asyncio.sleep(0)  # let the background task start waiting
        return "report"

    assert subagent._run_without_joining_executor(_main()) == "report"
    assert sorted(wound_down) == ["generator finalised", "task cancelled"]


def test_the_explorer_loop_refuses_to_nest_inside_a_running_one(recwarn):
    async def _main():  # pragma: no cover - must never start
        return "report"

    async def _nested():
        with pytest.raises(RuntimeError, match="running event loop"):
            subagent._run_without_joining_executor(_main())

    asyncio.run(_nested())
    assert not [w for w in recwarn if "never awaited" in str(w.message)]
