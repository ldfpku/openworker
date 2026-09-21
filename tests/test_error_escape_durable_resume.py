"""`SessionManager._durable_resume` must contain its own failures.

It is reached three ways — `resolve_inbox` (awaited by a REST route), the WeChat expiry
watchdog, and `_resume_after_reply`, which schedules it with `_spawn_weixin_task` and never
looks at it again. `spawn_retained` only keeps the task alive; its done-callback discards
without reading `.exception()` (by design, see coworker/taskutil.py), so on that last path
a raise out of `_durable_resume` reaches nobody: the only trace is asyncio's context-free
"Task exception was never retrieved" when the Task is collected, and the user who just
approved the prompt sees nothing at all.

The raise was not hypothetical: `ensure_engine` ran outside any `try`, and
`deliver_to_session`'s own comment records that exact call failing (an unprovisionable
scratch dir, a GBK snapshot). What is asserted here is the `deliver_to_session` contract: a
failure is logged WITH its traceback, surfaced to whoever is viewing the session as an
`error` event, the session is never left marked busy — and a cancellation is still a
cancellation, not an error.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from coworker.server.manager import SessionManager

MANAGER_LOGGER = "coworker.manager"
SID = "resume-escape"


def _item(session_id: str = SID) -> SimpleNamespace:
    # Just the attributes `_durable_resume` reads: which session, and which suspended
    # tool call it is meant to continue.
    return SimpleNamespace(
        id="inbox-1", session_id=session_id, tool_call_id="call_1", kind="approval"
    )


def _record_broadcasts(mgr: SessionManager, monkeypatch) -> list[tuple[str, dict]]:
    sent: list[tuple[str, dict]] = []

    async def fake_broadcast(session_id, message):
        sent.append((session_id, message))

    monkeypatch.setattr(mgr, "broadcast_session", fake_broadcast)
    return sent


def _errors_shown(sent) -> list[str]:
    return [
        m["data"]["error"] for (sid, m) in sent if sid == SID and m.get("type") == "error"
    ]


def _logged_with_traceback(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == MANAGER_LOGGER and r.levelno >= logging.ERROR and r.exc_info
    ]


class _ExplodingEngine:
    """Stands in for a cached engine whose resumed turn raises part-way through (an
    unexpected error out of the tool handling, not a provider error — those end the turn
    on an `error` event instead). `messages` is read by the post-turn auto-title hook."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def resume(self):
        yield SimpleNamespace(type="turn_start", data={})
        raise RuntimeError("resume-boom")


async def test_engine_build_failure_is_logged_and_shown_not_raised(
    tmp_path, monkeypatch, caplog
):
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sent = _record_broadcasts(mgr, monkeypatch)

    async def boom(session_id, **kwargs):
        raise RuntimeError("scratch-dir-boom")

    monkeypatch.setattr(mgr, "ensure_engine", boom)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    await asyncio.wait_for(mgr._durable_resume(_item()), timeout=5)  # must not raise

    assert _logged_with_traceback(caplog), "the failure must be logged with its traceback"
    shown = _errors_shown(sent)
    assert shown and "scratch-dir-boom" in shown[0]
    assert not mgr.is_running(SID)


async def test_scheduled_resume_does_not_leave_an_unretrieved_exception(
    tmp_path, monkeypatch, caplog
):
    """The fire-and-forget path itself: a WeChat reply resolves a prompt whose turn is not
    live, `_resume_after_reply` schedules the resume, and nobody ever awaits that task."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sent = _record_broadcasts(mgr, monkeypatch)

    async def boom(session_id, **kwargs):
        raise RuntimeError("scratch-dir-boom")

    monkeypatch.setattr(mgr, "ensure_engine", boom)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    mgr._resume_after_reply(_item())
    assert len(mgr._wx_tasks) == 1
    (task,) = mgr._wx_tasks
    await asyncio.wait({task}, timeout=5)

    assert task.done()
    assert task.exception() is None, "the failure escaped into a task nobody awaits"
    assert _logged_with_traceback(caplog)
    assert _errors_shown(sent)


async def test_resumed_turn_raising_is_logged_shown_and_releases_the_session(
    tmp_path, monkeypatch, caplog
):
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sent = _record_broadcasts(mgr, monkeypatch)
    mgr._engines[SID] = _ExplodingEngine()  # `ensure_engine`'s cache hit hands this back
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    await asyncio.wait_for(mgr._durable_resume(_item()), timeout=5)  # must not raise

    assert not mgr.is_running(SID)
    assert _logged_with_traceback(caplog)
    shown = _errors_shown(sent)
    assert shown and "resume-boom" in shown[0]


async def test_cancellation_is_not_swallowed_or_reported(tmp_path, monkeypatch):
    """Shutdown cancels in-flight work; a resume that turned that into an ordinary return
    (or into an `error` event for the user) would break it."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sent = _record_broadcasts(mgr, monkeypatch)
    entered = asyncio.Event()

    async def parked(session_id, **kwargs):
        entered.set()
        await asyncio.Event().wait()  # released only by the cancel below

    monkeypatch.setattr(mgr, "ensure_engine", parked)

    task = asyncio.ensure_future(mgr._durable_resume(_item()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    assert _errors_shown(sent) == []
    assert not mgr.is_running(SID)
