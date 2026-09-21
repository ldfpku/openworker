"""`Scheduler._run_claimed` must contain its own failures.

`_tick` spawns every due run with `spawn_retained` and never awaits it, and
`spawn_retained` deliberately never retrieves a task's exception (coworker/taskutil.py).
Only the runner call sat inside a `try`: recording a failed run (`store.add_run` inside the
`except`) and advancing the task afterwards (`store.get` / `store.save` — a locked or full
sqlite db) could raise straight out of the task, where nothing receives it but asyncio's
context-free "Task exception was never retrieved". The contract: logged with its traceback,
never escaping the task, and the run's own status still passed through untouched (a stopped
run stays "canceled" — see 17bd004).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from coworker.automation import Schedule, ScheduledTask, Scheduler, TaskRun, TaskStore

SCHED_LOGGER = "coworker.automation"


def _due_task(store: TaskStore) -> ScheduledTask:
    """A task that is due right now (same recipe as tests/test_automation.py)."""
    t = ScheduledTask(
        title="Daily brief",
        instructions="brief me",
        schedule=Schedule(kind="cron", cron="* * * * *"),
        workspace="/tmp/cw-auto",
    )
    store.save(t)
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (t.id,))
    store._conn.commit()
    return t


async def _tick_and_collect(sched: Scheduler) -> asyncio.Task:
    await sched._tick(trigger="schedule")
    assert len(sched._spawned) == 1
    (spawned,) = sched._spawned
    await asyncio.wait({spawned}, timeout=5)
    assert spawned.done()
    return spawned


def _logged_with_traceback(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == SCHED_LOGGER and r.levelno >= logging.ERROR and r.exc_info
    ]


async def test_advance_failure_after_a_spawned_run_is_logged_not_lost(
    tmp_path, monkeypatch, caplog
):
    store = TaskStore(tmp_path / "auto.db")
    t = _due_task(store)

    async def runner(task, trigger):
        return TaskRun(task_id=task.id, status="ok", trigger=trigger)

    def locked(task):
        raise sqlite3.OperationalError("database is locked")

    sched = Scheduler(store, runner)
    monkeypatch.setattr(store, "save", locked)
    caplog.set_level(logging.INFO, logger=SCHED_LOGGER)

    spawned = await _tick_and_collect(sched)

    assert spawned.exception() is None, "the failure escaped into a task nobody awaits"
    assert spawned.result() is not None and spawned.result().status == "ok"
    assert _logged_with_traceback(caplog)
    assert t.id not in sched._running_ids  # the overlap guard is released regardless


async def test_recording_a_failed_run_failing_is_logged_not_lost(
    tmp_path, monkeypatch, caplog
):
    store = TaskStore(tmp_path / "auto.db")
    _due_task(store)

    async def runner(task, trigger):
        raise RuntimeError("runner-boom")

    def locked(run):
        raise sqlite3.OperationalError("database is locked")

    sched = Scheduler(store, runner)
    monkeypatch.setattr(store, "add_run", locked)
    caplog.set_level(logging.INFO, logger=SCHED_LOGGER)

    spawned = await _tick_and_collect(sched)

    assert spawned.exception() is None, "the failure escaped into a task nobody awaits"
    assert spawned.result().status == "error"
    # Both the run's own failure and the failure to record it are on the log.
    assert len(_logged_with_traceback(caplog)) >= 2


async def test_canceled_status_still_passes_through(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _due_task(store)

    async def runner(task, trigger):
        return TaskRun(task_id=task.id, status="canceled", trigger=trigger)

    sched = Scheduler(store, runner)
    spawned = await _tick_and_collect(sched)

    assert spawned.result().status == "canceled"
    fresh = store.get(t.id)
    assert fresh.last_status == "canceled" and fresh.run_count == 1
