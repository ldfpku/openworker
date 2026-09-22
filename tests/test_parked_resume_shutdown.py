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
begins, and one that is cancelled says which items it never started. Every skipped item is
logged by id and left parked — dropping it would lose the approval for good if the
cancellation were ever not a shutdown.
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
        runners = [t for t in mgr._bg_tasks if not t.done()]
        assert runners, "expected the parked-resume runner in _bg_tasks"
        for task in runners:
            task.cancel()  # shutdown sweeping the manager's background tasks
        await asyncio.wait(runners, timeout=10)
        assert all(t.done() for t in runners)
    finally:
        engine.gate.set()
    await _settle(mgr)

    assert engine.calls == 1
    assert "i2" in mgr._deferred_resumes.get(sid, {}), "an unstarted item vanished"
    assert _skip_logged(caplog, "i2"), "an unstarted item vanished without a log line"


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
