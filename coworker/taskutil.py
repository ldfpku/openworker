"""The one place that decides HOW a fire-and-forget `asyncio.Task` is kept alive.

**Why this exists.** `asyncio.create_task()` returns a `Task`, but the running loop
itself only holds a WEAK reference to it. If nothing else in the program holds a strong
reference to that `Task` object, it is eligible for garbage collection at any suspend
point — even while it is still pending — and CPython's collector can and does collect
it, silently ending the coroutine mid-run. (When it happens under a debug-enabled loop
you get a logged "Task was destroyed but it is pending!"; under a normal loop you get
nothing at all — the work just stops.)

Several call sites in this package fire a coroutine with `create_task(...)` and never
store the returned Task anywhere. Today, each of those happens to keep running anyway,
because whatever the coroutine is suspended on (a thread-pool work item, a `wait_for`
timer handle, an object a manager already holds elsewhere) happens to be reachable from
some OTHER strong reference. That is an accident of what the coroutine happens to await
right now, not a designed guarantee, and it silently breaks the moment that changes —
e.g. a refactor that removes the incidental anchor. `spawn_retained()` replaces the
accident with an explicit guarantee: the caller's own `set` of tasks IS the strong
reference, for as long as the task is in flight.

**Usage.** Each call site owns one `set[asyncio.Task]` (e.g. an instance attribute like
`self._bg_tasks`) and passes it to `spawn_retained()` alongside the coroutine to run.
Because the caller owns that set, it can also inspect it (e.g. assert on how many
background tasks are in flight) or cancel its members (e.g. at shutdown) — this module
never touches the set except to add the new task and, later, remove it again.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine


def spawn_retained(
    tasks: set[asyncio.Task], coro: Coroutine[Any, Any, Any], *, name: str | None = None
) -> asyncio.Task | None:
    """Schedule `coro` on the running loop and keep it alive via `tasks` for as long as
    it is in flight.

    Adds the new `Task` to `tasks` (the caller-owned strong reference that keeps it from
    being collected while pending) and registers a done callback that discards it from
    `tasks` again — on a normal return, an unhandled exception, or a cancellation alike,
    exactly once, whenever the task finishes. The done callback only discards; it does
    not retrieve the result or log the exception, so this function changes nothing about
    how a caller's coroutine is allowed to fail — a task that would have raised silently
    (nobody awaits it or calls `.result()`) still does, same as a bare `create_task`.

    If the current thread has no running event loop (`asyncio.get_running_loop()` raises
    `RuntimeError`), there is nothing to schedule `coro` on: the coroutine is closed (so
    it does not trigger a "coroutine ... was never awaited" warning later) and `None` is
    returned, with `tasks` left untouched. Callers that set up bookkeeping before calling
    this (e.g. marking something "in flight") must check for `None` and undo it
    themselves — this function has no way to know what that bookkeeping was.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return None
    task = loop.create_task(coro, name=name)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return task
