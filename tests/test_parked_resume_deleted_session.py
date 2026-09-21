"""A parked durable resume must not bring a deleted session back.

`delete_session` drops the resumes still parked on the session, but `_kick_deferred_resumes`
takes them out of `_deferred_resumes` the moment the holding turn ends and hands them to a
runner task — so a delete that lands after that hand-off found nothing to drop. The runner
then went ahead: `ensure_engine` built a fresh engine under the dead id, holding nothing but
its system prompt, and the save after the (empty) resume wrote it back to the store as a new
session row.

Asserted: the runner checks, before each resume it starts, that the session still exists;
if it does not, nothing is built or saved under that id and the log says which resumes
were dropped.
"""

from __future__ import annotations

import asyncio
import logging

from coworker.server.manager import SessionManager
from test_durable_resume_busy_session import (
    _approval_manager,
    _approved_after_restart,
    _eventually,
    _settle,
)
from test_parked_resume_shutdown import _park_two, _spy_on_resume_starts

MANAGER_LOGGER = "coworker.manager"


def _drop_logged(caplog, item_id: str) -> bool:
    return any(
        r.name == MANAGER_LOGGER
        and r.levelno >= logging.INFO
        and item_id in r.getMessage()
        and "no longer exists" in r.getMessage()
        for r in caplog.records
    )


async def test_session_deleted_after_the_handoff_is_not_revived(
    tmp_path, monkeypatch, caplog
):
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "deleted-after-handoff"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    assert mgr.try_mark_running(sid)  # a turn holds the session
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
        assert item.id in mgr._deferred_resumes.get(sid, {})
        started = _spy_on_resume_starts(mgr, monkeypatch)
    finally:
        # The turn ends: the parked resume is handed to a runner task, which has not run
        # yet. The user deletes the session right then.
        mgr.mark_idle(sid)
    assert sid not in mgr._deferred_resumes, "the runner should hold the item by now"
    assert mgr.delete_session(sid)["ok"]
    await _settle(mgr)

    assert started == [], "a resume was started on a deleted session"
    assert mgr.session_store.load(sid) is None, "the deleted session was written back"
    assert sid not in mgr._engines, "an engine was rebuilt under the deleted id"
    assert not target.exists()
    assert _drop_logged(caplog, item.id)


async def test_runner_rechecks_before_each_item(tmp_path, monkeypatch, caplog):
    """Deleted while the runner is busy with the first of two items: the second, which
    had not started yet, is dropped instead of run."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    sid = "deleted-mid-runner"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    engine = await _park_two(mgr, sid, monkeypatch, tmp_path)

    mgr.mark_idle(sid)
    try:
        await _eventually(lambda: engine.calls == 1, what="the first parked resume")
        assert mgr.delete_session(sid)["ok"]
    finally:
        engine.gate.set()
    await _settle(mgr)

    assert engine.calls == 1, "the runner resumed a session that had been deleted"
    assert _drop_logged(caplog, "i2")
