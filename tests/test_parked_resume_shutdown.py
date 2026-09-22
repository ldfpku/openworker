"""A parked durable resume must not be started while the process is going away.

`_durable_resume_turn` parks a resume whose session is busy, and `mark_idle` starts it once
the turn holding the session ends. But on shutdown that turn does not "end" — it is
cancelled: `asyncio.run` cancels every task still pending when the server's main coroutine
returns, and `aclose` -> `Scheduler.stop` cancels in-flight scheduled runs. Their
`finally: mark_idle` then started the parked resume as a brand-new task, created after the
cancellation sweep, so nothing cancelled it: the approved tool ran in the middle of the
teardown. On the unfixed code the last test (a real `asyncio.run`) fails on exactly that —
the approved write is on disk. Run standalone, the same scenario also saved the
continuation ending in an `error` notice, "Executor shutdown has been called": its model
call came after `asyncio.run` had shut the default executor down.

Asserted: neither a cancelled holding turn nor a turn that ends after `aclose` has begun
starts a parked resume; a runner already going stops before its next item once shutdown
begins, and one that is cancelled — wherever it is waiting — says which items it never
started and names the one it cut short. Every skipped item is logged by id and left parked
rather than dropped: not every cancellation is a shutdown (a connector refresh cancels a
WeChat turn in flight — manager `_parked_resume_blocker`, read from the code), and a dropped
item would lose the approval for good. The item cut short is not parked again: it may
already have run its call.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from types import SimpleNamespace

import pytest

from coworker.server.manager import SessionManager
from test_durable_resume_busy_session import (
    _GatedEngine,
    _approval_manager,
    _approved_after_restart,
    _eventually,
    _persisted,
    _settle,
)

MANAGER_LOGGER = "coworker.manager"


def _skip_logged(caplog, item_id: str) -> bool:
    return any(
        r.name == MANAGER_LOGGER
        and r.levelno >= logging.WARNING
        and item_id in r.getMessage()
        for r in caplog.records
    )


def _spy_on_resume_starts(mgr: SessionManager, monkeypatch) -> list[str]:
    """Record every durable resume that gets as far as `_durable_resume_turn` — the
    moment it would build an engine and claim the session."""
    started: list[str] = []
    real = mgr._durable_resume_turn

    async def spy(item):
        started.append(item.id)
        return await real(item)

    monkeypatch.setattr(mgr, "_durable_resume_turn", spy)
    return started


def _holding_turn_coro(mgr: SessionManager, sid: str, release: asyncio.Event):
    """A turn that owns `sid` until `release` is set, with the shape every turn path has
    (app.py `run_turn`, `deliver_to_session`, a scheduled run): claim first, and
    `mark_idle` in its `finally`, however it ends."""
    assert mgr.try_mark_running(sid)

    async def turn() -> None:
        try:
            await release.wait()
        finally:
            mgr.mark_idle(sid)

    return turn()


def _holding_turn(mgr: SessionManager, sid: str, release: asyncio.Event) -> asyncio.Task:
    return asyncio.ensure_future(_holding_turn_coro(mgr, sid, release))


async def test_cancelled_holding_turn_leaves_the_resume_parked(
    tmp_path, monkeypatch, caplog
):
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "cancelled-holder"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    release = asyncio.Event()
    holder = _holding_turn(mgr, sid, release)
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
        assert item.id in mgr._deferred_resumes.get(sid, {}), "should have parked"
        started = _spy_on_resume_starts(mgr, monkeypatch)
    finally:
        holder.cancel()  # what shutdown does to a turn still in flight
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(holder, timeout=10)
    await _settle(mgr)

    assert started == [], "a parked resume was started by a cancelled turn's mark_idle"
    assert not target.exists(), "the approved tool ran while the process was going away"
    assert item.id in mgr._deferred_resumes.get(sid, {}), "the approval was dropped"
    assert _skip_logged(caplog, item.id), "a skipped resume must leave a log line"

    # Left parked, not lost: the next turn to end on this session does start it.
    assert mgr.try_mark_running(sid)
    mgr.mark_idle(sid)
    await _eventually(
        lambda: target.exists() and not mgr.is_running(sid),
        what="the still-parked resume to run after an ordinary turn end",
    )
    await _settle(mgr)
    assert started == [item.id]


class _TaskWithoutCancelling(asyncio.Task):
    """A task the way Python 3.10 has them: no `Task.cancelling()` (pyproject admits 3.10;
    CI runs a newer interpreter, so this is simulated)."""

    @property
    def cancelling(self):
        raise AttributeError("'Task' object has no attribute 'cancelling'")


async def test_ordinary_turn_end_starts_the_resume_without_task_cancelling(
    tmp_path, caplog
):
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "no-task-cancelling"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    assert mgr.try_mark_running(sid)  # a turn holds the session
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
        assert item.id in mgr._deferred_resumes.get(sid, {}), "should have parked"
    finally:

        async def turn_ends() -> None:
            mgr.mark_idle(sid)

        # ...and ends normally, on a task without `cancelling`.
        ended = _TaskWithoutCancelling(turn_ends())
        await asyncio.wait_for(ended, timeout=10)
    assert not hasattr(ended, "cancelling")

    def errors() -> list[str]:
        return [
            f"{r.getMessage()} | {r.exc_info[1]!r}" if r.exc_info else r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.ERROR
        ]

    assert errors() == [], "mark_idle could not start the parked resume"
    await _eventually(
        lambda: target.exists() and not mgr.is_running(sid),
        what="the parked resume to run after the turn ended",
    )
    await _settle(mgr)
    assert target.read_text() == "ok"
    assert item.id not in mgr._deferred_resumes.get(sid, {})
    assert errors() == []


async def test_turn_ending_after_shutdown_began_does_not_start_the_resume(
    tmp_path, monkeypatch, caplog
):
    """`aclose` runs in the lifespan shutdown, and a turn can still finish normally after
    it — no cancellation involved, so only the manager itself knows it is closing."""
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "closing-holder"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    release = asyncio.Event()
    holder = _holding_turn(mgr, sid, release)
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
        assert item.id in mgr._deferred_resumes.get(sid, {})
        started = _spy_on_resume_starts(mgr, monkeypatch)
        await asyncio.wait_for(mgr.aclose(), timeout=10)
    finally:
        release.set()  # ...and the turn ends normally
    await asyncio.wait_for(holder, timeout=10)
    await _settle(mgr)

    assert started == [], "a parked resume was started after aclose had begun"
    assert not target.exists()
    assert item.id in mgr._deferred_resumes.get(sid, {})
    assert _skip_logged(caplog, item.id)


async def test_aclose_cancelling_a_scheduled_run_does_not_start_the_resume(
    tmp_path, monkeypatch, caplog
):
    """The manager's own shutdown doing the cancelling: `aclose` -> `Scheduler.stop`
    cancels the runs it spawned, and a scheduled run holds its session exactly like the
    turn below (`_run_scheduled_task`: claim, then `mark_idle` in its `finally`)."""
    from coworker.taskutil import spawn_retained

    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "scheduled-holder"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    release = asyncio.Event()
    run = spawn_retained(mgr.scheduler._spawned, _holding_turn_coro(mgr, sid, release))
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
        assert item.id in mgr._deferred_resumes.get(sid, {})
        started = _spy_on_resume_starts(mgr, monkeypatch)
        await asyncio.wait_for(mgr.aclose(), timeout=10)
        assert run.cancelled(), "Scheduler.stop should have cancelled the run"
    finally:
        release.set()
    await _settle(mgr)

    assert started == [], "a parked resume was started by the shutdown itself"
    assert not target.exists()
    assert item.id in mgr._deferred_resumes.get(sid, {})
    assert _skip_logged(caplog, item.id)


async def _park_two(mgr: SessionManager, sid: str, monkeypatch, tmp_path):
    """Two answered prompts parked on `sid` behind a running turn, each resume running on
    a `_GatedEngine` that holds until its gate opens."""
    engine = _GatedEngine()

    async def fake_ensure_engine(session_id, **kwargs):
        return engine

    monkeypatch.setattr(mgr, "ensure_engine", fake_ensure_engine)
    monkeypatch.setattr(mgr, "save", lambda *a, **k: None)
    _persisted(mgr, sid, tmp_path)
    first = SimpleNamespace(id="i1", session_id=sid, tool_call_id="c1")
    second = SimpleNamespace(id="i2", session_id=sid, tool_call_id="c2")
    assert mgr.try_mark_running(sid)
    await asyncio.wait_for(mgr._durable_resume(first), timeout=10)
    await asyncio.wait_for(mgr._durable_resume(second), timeout=10)
    assert set(mgr._deferred_resumes.get(sid, {})) == {"i1", "i2"}
    return engine


async def test_parked_runner_stops_before_its_next_item_once_shutdown_begins(
    tmp_path, monkeypatch, caplog
):
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sid = "runner-closing"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    engine = await _park_two(mgr, sid, monkeypatch, tmp_path)

    real_exists = mgr._session_still_exists
    reads_after_close: list[str] = []

    async def exists_spy(session_id):
        if mgr._closing:
            reads_after_close.append(session_id)
        return await real_exists(session_id)

    monkeypatch.setattr(mgr, "_session_still_exists", exists_spy)
    mgr.mark_idle(sid)  # the holding turn ends: the runner starts on the first item
    try:
        await _eventually(lambda: engine.calls == 1, what="the first parked resume")
        await asyncio.wait_for(mgr.aclose(), timeout=10)
    finally:
        engine.gate.set()
    await _settle(mgr)

    assert engine.calls == 1, "the runner started another resume after aclose began"
    assert "i2" in mgr._deferred_resumes.get(sid, {})
    assert _skip_logged(caplog, "i2")
    # The item goes back to the park either way; reading the store for it on the way out
    # is wasted work on a shutting-down process.
    assert reads_after_close == []


def _cut_short_logged(caplog, item_id: str) -> bool:
    return any(
        r.name == MANAGER_LOGGER
        and r.levelno >= logging.WARNING
        and item_id in r.getMessage()
        and "cancelled partway" in r.getMessage()
        for r in caplog.records
    )


async def _cancel_runners(mgr: SessionManager) -> None:
    """Cancel the parked-resume runner — what `asyncio.run` does to every task still
    pending when the server's main coroutine returns."""
    runners = [t for t in mgr._bg_tasks if not t.done()]
    assert runners, "expected the parked-resume runner in _bg_tasks"
    for task in runners:
        task.cancel()
    await asyncio.wait(runners, timeout=10)
    assert all(t.done() for t in runners)


async def test_cancelled_parked_runner_names_the_items_it_never_started(
    tmp_path, monkeypatch, caplog
):
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sid = "runner-cancelled"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    engine = await _park_two(mgr, sid, monkeypatch, tmp_path)

    mgr.mark_idle(sid)
    try:
        await _eventually(lambda: engine.calls == 1, what="the first parked resume")
        await _cancel_runners(mgr)
    finally:
        engine.gate.set()
    await _settle(mgr)

    assert engine.calls == 1
    assert "i2" in mgr._deferred_resumes.get(sid, {}), "an unstarted item vanished"
    assert _skip_logged(caplog, "i2"), "an unstarted item vanished without a log line"
    # The one that was already running is named, and not parked again: it had claimed
    # the session and was inside `engine.resume()` — a second run could repeat its call.
    assert _cut_short_logged(caplog, "i1")
    assert "i1" not in mgr._deferred_resumes.get(sid, {})


@pytest.mark.parametrize("closing", [False, True], ids=["running", "closing"])
async def test_runner_cancelled_during_the_existence_read_leaves_every_item_parked(
    tmp_path, monkeypatch, caplog, closing
):
    """Cancelled while the check before the first item is still reading the store on a
    worker thread (`_session_still_exists`) — with shutdown begun during that read, or
    not. Neither item has started."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sid = f"runner-cancelled-in-read-{closing}"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    engine = await _park_two(mgr, sid, monkeypatch, tmp_path)

    in_read = threading.Event()
    release_read = threading.Event()
    real_load = mgr.session_store.load

    def blocking_load(session_id):
        # Only the off-loop read blocks; anything reading on the loop thread goes through.
        if threading.current_thread() is not threading.main_thread():
            in_read.set()
            release_read.wait(10)
        return real_load(session_id)

    monkeypatch.setattr(mgr.session_store, "load", blocking_load)
    mgr.mark_idle(sid)
    try:
        await _eventually(in_read.is_set, what="the runner's existence read")
        if closing:
            mgr._closing = True
        await _cancel_runners(mgr)
    finally:
        release_read.set()
        engine.gate.set()
    await _settle(mgr)

    assert engine.calls == 0
    # (parked again, logged) for each item, checked together so a failure shows both.
    assert (
        set(mgr._deferred_resumes.get(sid, {})),
        _skip_logged(caplog, "i1"),
        _skip_logged(caplog, "i2"),
    ) == ({"i1", "i2"}, True, True), "unstarted items vanished"


async def test_runner_cancelled_while_the_item_builds_its_engine_names_it(
    tmp_path, monkeypatch, caplog
):
    """Cancelled while the first item is still inside `ensure_engine`, before it has
    claimed the session: that item is named, the one after it goes back to the park."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sid = "runner-cancelled-in-ensure-engine"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    engine = await _park_two(mgr, sid, monkeypatch, tmp_path)

    building = asyncio.Event()
    never = asyncio.Event()

    async def stuck_ensure_engine(session_id, **kwargs):
        building.set()
        await never.wait()

    monkeypatch.setattr(mgr, "ensure_engine", stuck_ensure_engine)
    mgr.mark_idle(sid)
    try:
        await asyncio.wait_for(building.wait(), timeout=10)
        await _cancel_runners(mgr)
    finally:
        never.set()
        engine.gate.set()
    await _settle(mgr)

    assert engine.calls == 0
    assert not mgr.is_running(sid)
    assert (
        "i2" in mgr._deferred_resumes.get(sid, {}),
        _skip_logged(caplog, "i2"),
        _cut_short_logged(caplog, "i1"),
    ) == (True, True, True), "(i2 parked again, i2 logged, i1 named)"


def test_asyncio_run_teardown_does_not_run_a_parked_resume(tmp_path, caplog):
    """The real thing: the server's main coroutine returns while a turn still holds the
    session, and `asyncio.run` cancels that turn on its way out. Run on a daemon thread
    with a join timeout, so a regression can fail this test but never hang the suite."""
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "asyncio-run-teardown"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    parked: dict[str, list[str]] = {}

    async def server_main() -> None:
        item, _live = await _approved_after_restart(mgr, sid, tmp_path)
        release = asyncio.Event()  # never set: the turn is still running at exit
        # Retained the way app.py `claim_turn` retains a WS turn.
        mgr.spawn_turn_task(_holding_turn_coro(mgr, sid, release))
        await mgr._durable_resume(item)
        parked[sid] = list(mgr._deferred_resumes.get(sid, {}))

    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            asyncio.run(server_main())
            outcome["ok"] = True
        except BaseException as exc:  # reported below, never swallowed silently
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(60)
    assert not thread.is_alive(), "asyncio.run did not finish within 60s"
    assert outcome.get("ok"), f"server_main failed: {outcome.get('error')!r}"
    assert parked.get(sid), "the resume should have parked behind the running turn"

    assert not target.exists(), "the approved tool ran during asyncio.run's teardown"
    assert _skip_logged(caplog, parked[sid][0])


async def test_turn_ending_after_aclose_spawns_no_runner_that_teardown_could_drop(
    tmp_path, monkeypatch, caplog
):
    """`_parked_resume_blocker`'s own `_closing` check, not just the runner's. Without it
    a turn ending after `aclose` still hands the items to a new runner task, taking them
    out of `_deferred_resumes` — and `asyncio.run`'s teardown cancels every pending task.
    A task cancelled before its first step never runs its body, so the runner's own
    cancellation handler never puts the items back: they vanish without a log line."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sid = "closing-no-runner"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    engine = await _park_two(mgr, sid, monkeypatch, tmp_path)
    await asyncio.wait_for(mgr.aclose(), timeout=10)

    before = set(mgr._bg_tasks)
    mgr.mark_idle(sid)  # the holding turn ends normally, after aclose
    spawned = [t for t in mgr._bg_tasks if t not in before]
    # What the teardown does to them, before any of them gets to run.
    for task in spawned:
        task.cancel()
    if spawned:
        await asyncio.wait(spawned, timeout=10)
    try:
        await _settle(mgr)
    finally:
        engine.gate.set()

    assert engine.calls == 0
    assert (
        spawned,
        set(mgr._deferred_resumes.get(sid, {})),
        _skip_logged(caplog, "i1"),
        _skip_logged(caplog, "i2"),
    ) == ([], {"i1", "i2"}, True, True), "(no runner, both parked, both logged)"


async def test_turn_ending_while_the_scheduler_is_stopping_does_not_start_the_resume(
    tmp_path, monkeypatch, caplog
):
    """`aclose` sets `_closing` before `Scheduler.stop`, not after: that stop awaits the
    runs it cancels, and any turn on the loop can end normally in the meantime. That turn's
    `finally: mark_idle` runs in an uncancelled task, so `Task.cancelling()` does not
    stop it — only `_closing` does."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sid = "ends-during-scheduler-stop"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    engine = await _park_two(mgr, sid, monkeypatch, tmp_path)

    real_stop = mgr.scheduler.stop

    async def stop_while_a_turn_ends() -> None:
        before = set(mgr._bg_tasks)
        mgr.mark_idle(sid)  # the holding turn ends normally while the scheduler stops
        spawned = [t for t in mgr._bg_tasks if t not in before]
        if spawned:
            # A runner got started: let it reach the engine (or finish) before the stop
            # goes on, as a slow cancelled run would.
            await _eventually(
                lambda: engine.calls >= 1 or all(t.done() for t in spawned),
                what="the started runner to reach the engine",
            )
        await real_stop()

    monkeypatch.setattr(mgr.scheduler, "stop", stop_while_a_turn_ends)
    try:
        await asyncio.wait_for(mgr.aclose(), timeout=10)
    finally:
        engine.gate.set()
    await _settle(mgr)

    assert engine.calls == 0, "a parked resume was started while aclose was running"
    assert set(mgr._deferred_resumes.get(sid, {})) == {"i1", "i2"}
    assert _skip_logged(caplog, "i1") and _skip_logged(caplog, "i2")
