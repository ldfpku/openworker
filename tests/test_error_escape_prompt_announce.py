"""`SessionManager._announce_prompt_resolved` must contain its own failures.

`notify_prompt_resolved` is synchronous (the WeChat reply hop can only schedule work), so
the announcement always runs as a fire-and-forget task via `_spawn_weixin_task` — and
`spawn_retained` deliberately never retrieves a task's exception (coworker/taskutil.py).
Only the session broadcast used to sit inside a `try`; the import, the item's `wx` sidecar
lookup, and the WeChat receipt's wording (`outcome_text(...)`, `.format(...)`) did not, so
a raise there vanished into asyncio's context-free "Task exception was never retrieved".
The receipt is best-effort — nobody is blocked on it — so the contract is: logged with its
traceback, never escaping the task.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from coworker.server.manager import SessionManager

MANAGER_LOGGER = "coworker.manager"


async def test_receipt_failure_is_logged_not_left_in_the_task(
    tmp_path, monkeypatch, caplog
):
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    item = SimpleNamespace(
        id="inbox-1",
        session_id="announce",
        kind="approval",
        title="Run the build?",
        data={"wx": {"target": "weixin:wxid_peer"}},
    )

    def boom(item, resolution):
        raise RuntimeError("outcome-text-boom")

    monkeypatch.setattr("coworker.interactions.outcome_text", boom)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    mgr.notify_prompt_resolved(item, "allow", via="app")
    assert len(mgr._wx_tasks) == 1
    (task,) = mgr._wx_tasks
    await asyncio.wait({task}, timeout=5)

    assert task.done()
    assert task.exception() is None, "the failure escaped into a task nobody awaits"
    logged = [
        r
        for r in caplog.records
        if r.name == MANAGER_LOGGER and r.levelno >= logging.ERROR and r.exc_info
    ]
    assert logged, "the failure must be logged with its traceback"


async def test_cancellation_is_not_swallowed_or_logged(tmp_path, monkeypatch, caplog):
    """Containing failures must not contain cancellation: shutdown cancels these tasks, and
    one that turned that into an ordinary return (or an error log) would break it."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    item = SimpleNamespace(
        id="inbox-2",
        session_id="announce",
        kind="approval",
        title="Run the build?",
        data={"wx": {"target": "weixin:wxid_peer"}},
    )
    entered = asyncio.Event()

    async def parked_say(target, text):
        entered.set()
        await asyncio.Event().wait()  # released only by the cancel below

    monkeypatch.setattr(mgr, "_weixin_say", parked_say)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    mgr.notify_prompt_resolved(item, "allow", via="app")
    (task,) = mgr._wx_tasks
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
    await asyncio.wait({task}, timeout=5)

    assert task.cancelled(), "the cancellation was swallowed"
    assert not [
        r for r in caplog.records if r.name == MANAGER_LOGGER and r.levelno >= logging.ERROR
    ], "a cancellation was logged as a failure"
