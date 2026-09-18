"""Unit tests for `coworker.taskutil.spawn_retained` — the shared helper that keeps a
fire-and-forget `asyncio.Task` alive by parking it in a caller-owned set instead of
relying on the loop's weak reference. See the module's own docstring for the mechanism
this guards against (a pending Task can be silently garbage-collected)."""

from __future__ import annotations

import asyncio
import gc
import inspect
import platform
import warnings
import weakref

import pytest

from coworker.taskutil import spawn_retained


async def _immediate() -> str:
    return "done"


async def _boom() -> None:
    raise ValueError("spawn_retained probe: deliberate failure")


async def _pending(gate: asyncio.Event) -> None:
    await gate.wait()


async def test_spawn_retained_returns_a_tracked_running_task():
    tasks: set[asyncio.Task] = set()
    gate = asyncio.Event()
    task = spawn_retained(tasks, _pending(gate))
    try:
        assert isinstance(task, asyncio.Task)
        assert task in tasks
        assert not task.done()
    finally:
        gate.set()
        await task


async def test_spawn_retained_discards_after_normal_completion():
    tasks: set[asyncio.Task] = set()
    task = spawn_retained(tasks, _immediate())
    assert await task == "done"
    assert task not in tasks
    assert tasks == set()


async def test_spawn_retained_discards_after_exception():
    tasks: set[asyncio.Task] = set()
    task = spawn_retained(tasks, _boom())
    with pytest.raises(ValueError, match="deliberate failure"):
        await task
    # The done callback only discards — it neither swallows nor logs the exception,
    # so it must still surface to whoever awaits the task (same as bare create_task).
    assert task not in tasks
    assert tasks == set()


async def test_spawn_retained_discards_after_cancel():
    tasks: set[asyncio.Task] = set()
    gate = asyncio.Event()
    task = spawn_retained(tasks, _pending(gate))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task not in tasks
    assert tasks == set()


async def test_spawn_retained_passes_name_through():
    tasks: set[asyncio.Task] = set()
    gate = asyncio.Event()
    task = spawn_retained(tasks, _pending(gate), name="probe-task")
    try:
        assert task.get_name() == "probe-task"
    finally:
        gate.set()
        await task


def test_spawn_retained_without_a_running_loop_closes_the_coroutine_and_returns_none():
    """Called from plain sync code — no running loop in this thread, so there is
    nothing to schedule `coro` on. `spawn_retained` must close the coroutine itself
    (otherwise Python would warn "coroutine ... was never awaited" once it is
    garbage-collected) and report the no-op back via `None`, leaving `tasks` untouched
    so a caller can undo any bookkeeping (e.g. an in-flight marker) it did beforehand."""
    tasks: set[asyncio.Task] = set()
    coro = _immediate()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = spawn_retained(tasks, coro)
        assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED
        del coro
        gc.collect()
    assert result is None
    assert tasks == set()
    assert not any("never awaited" in str(w.message) for w in caught), caught


async def test_spawn_retained_keeps_a_solely_self_referential_task_alive_under_gc():
    """The spawned coroutine awaits an `asyncio.Event` that only ITS OWN frame
    references. Past the first suspend point, the only things keeping the Task alive
    are (a) the cycle it is part of (Task -> coroutine -> frame -> Event -> waiter
    Future -> done-callback -> Task) and (b) `tasks`, the set `spawn_retained` added
    it to. Repeated `gc.collect()` — which is exactly what can and does collect an
    unreferenced cycle like this one, see the counterfactual test below — must not
    collect it while `tasks` still holds a strong reference."""

    async def wait_on_private_event() -> None:
        ev = asyncio.Event()
        await ev.wait()

    tasks: set[asyncio.Task] = set()
    task = spawn_retained(tasks, wait_on_private_event())
    assert task is not None
    for _ in range(20):
        gc.collect()
        await asyncio.sleep(0)
        assert not task.done()
        assert task in tasks
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task not in tasks


@pytest.mark.skipif(
    platform.python_implementation() != "CPython",
    reason=(
        "relies on CPython's cyclic GC collecting a Task that survives only via a "
        "reference cycle (Task -> coroutine -> frame -> Event -> Future -> Task); "
        "other implementations' GC timing gives no such bound"
    ),
)
async def test_bare_create_task_can_be_collected_while_still_pending():
    """Counterfactual, pinned as executable documentation: the exact same
    self-referential-await shape as the test above, but spawned with a bare
    `asyncio.create_task` and NO strong reference kept anywhere (only a `weakref`) —
    it does NOT survive `gc.collect()`. This is the accident `spawn_retained` exists
    to stop relying on. If this test starts failing, the loop (or CPython's GC) has
    changed to strongly hold pending Tasks on its own — that should be independently
    confirmed before treating any `spawn_retained` call site as now redundant.
    """

    async def wait_on_private_event() -> None:
        ev = asyncio.Event()
        await ev.wait()

    loop = asyncio.get_running_loop()
    caught: list[dict] = []
    previous_handler = loop.get_exception_handler()
    # A Task's __del__ reports a still-pending Task via call_exception_handler, which
    # the default handler logs at ERROR level straight into the test run's output.
    # Install a temporary handler so we both catch that (proving the mechanism this
    # test relies on actually fired) and keep it out of the captured test log.
    loop.set_exception_handler(lambda _loop, context: caught.append(context))
    try:
        # No local variable ever binds the Task itself — only a weakref — so this
        # test's own frame cannot be the thing keeping it alive.
        ref = weakref.ref(asyncio.create_task(wait_on_private_event()))  # noqa: RUF006 - deliberate, see docstring
        await asyncio.sleep(0)  # let it run once and suspend on `ev.wait()`
        for _ in range(200):
            gc.collect()
            if ref() is None:
                break
            await asyncio.sleep(0.01)
        assert ref() is None, (
            "the unreferenced Task survived gc.collect() — see this test's docstring"
        )
    finally:
        loop.set_exception_handler(previous_handler)
    assert any(
        "destroyed but it is pending" in str(c.get("message", "")) for c in caught
    ), caught
