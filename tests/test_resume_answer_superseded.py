"""An answer that arrives after the conversation has moved past its prompt must not vanish
without a word.

A durable resume continues the tool calls left unanswered at the END of the transcript
(`engine._unanswered_trailing_tool_calls`). What realistically collides with it is the
user's next message: a WebSocket turn (or a delivery, a team message) appends a new user
message after the suspended call. From then on that call is no longer "trailing", so the
resume — run directly, or parked and started once that turn ends — finds nothing to do and
returns: the approved tool never runs, the Inbox shows the prompt resolved as allowed, and
nothing anywhere told the user. That silence is older than the parking; parking only made
the collision easier to reach.

Asserted: the resume still runs nothing (the conversation has moved on; replaying an old
tool call behind the user's back would be worse), but it logs the fact and leaves an
`answer_superseded` notice in the transcript, also pushed to whoever is viewing the session.
A call that already has its real result — an earlier resume used the answer — gets no such
notice. The notice is written once the resume is done, never while a later prompt of the
session is still pending (the last two tests).
"""

from __future__ import annotations

import asyncio
import logging

from coworker.server.manager import SessionManager
from test_durable_resume import _run_until_pending, _text, _tool
from test_durable_resume_busy_session import (
    _ChatOnlyScript,
    _approval_manager,
    _approved_after_restart,
    _eventually,
    _settle,
)

MANAGER_LOGGER = "coworker.manager"


def _notices(mgr: SessionManager, sid: str) -> list[dict]:
    rec = mgr.session_store.load(sid)
    return [
        m
        for m in (rec.messages if rec else [])
        if m.get("role") == "notice" and m.get("kind") == "answer_superseded"
    ]


def _record_broadcasts(mgr: SessionManager, monkeypatch) -> list[tuple[str, dict]]:
    sent: list[tuple[str, dict]] = []
    real = mgr.broadcast_session

    async def record(session_id, message):
        sent.append((session_id, message))
        await real(session_id, message)

    monkeypatch.setattr(mgr, "broadcast_session", record)
    return sent


def _pushed(sent, sid: str) -> list[dict]:
    return [m["data"] for (s, m) in sent if s == sid and m.get("type") == "answer_superseded"]


def _logged(caplog, item_id: str) -> bool:
    return any(
        r.name == MANAGER_LOGGER and r.levelno >= logging.INFO and item_id in r.getMessage()
        and "moved past" in r.getMessage()
        for r in caplog.records
    )


def _assert_reported(mgr, sent, caplog, sid: str, item) -> None:
    (notice,) = _notices(mgr, sid)
    assert notice["prompt"] == "approval"
    assert notice["resolution"] == "allow"
    assert notice["tool"] == "write_file"
    assert "write_file" in notice["text"]
    (pushed,) = _pushed(sent, sid)
    assert (pushed["prompt"], pushed["resolution"], pushed["tool"]) == (
        "approval",
        "allow",
        "write_file",
    )
    assert _logged(caplog, item.id), "the superseded answer must leave a log line"


async def test_user_turn_started_in_the_ensure_engine_gap(tmp_path, monkeypatch, caplog):
    """The real collision, with a real `engine.run` turn: the user sends their next message
    while the resume is waiting on the engine lock, then presses Stop on that turn."""
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "gap-user-turn"
    item, live = await _approved_after_restart(mgr, sid, tmp_path)
    sent = _record_broadcasts(mgr, monkeypatch)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    turn_started = asyncio.Event()
    socket_ready = asyncio.Event()  # the socket takes the turn_start frame once this is set
    turn: dict[str, asyncio.Task] = {}

    async def run_turn(content: str) -> None:
        # app.py `run_turn`, minus the socket: checkpoint on turn_start, then `mark_idle`
        # and a save on the way out, however the turn ends.
        try:
            async for event in live.run(content):
                if event.type.value == "turn_start":
                    mgr.save(sid, live)
                    turn_started.set()
                    await socket_ready.wait()
        finally:
            mgr.mark_idle(sid)
            mgr.save(sid, live)

    real_ensure_engine = mgr.ensure_engine

    async def ensure_engine_with_a_user_in_the_gap(session_id, **kwargs):
        engine = await real_ensure_engine(session_id, **kwargs)
        if "task" not in turn:
            # app.py `claim_turn`: claim, then start the turn on the session's engine.
            assert mgr.try_mark_running(sid)
            turn["task"] = asyncio.ensure_future(run_turn("never mind, do something else"))
            await asyncio.wait_for(turn_started.wait(), timeout=10)
            live.request_interrupt()  # ...and the user presses Stop on it
        return engine

    monkeypatch.setattr(mgr, "ensure_engine", ensure_engine_with_a_user_in_the_gap)
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)

        assert mgr.is_running(sid), "the user's turn lost its claim on the session"
        assert live._cancel.is_set(), "the Stop the user pressed was wiped"
        assert not turn["task"].done()
        assert item.id in mgr._deferred_resumes.get(sid, {}), "should have parked"
        assert not target.exists()
    finally:
        socket_ready.set()
    await asyncio.wait_for(turn["task"], timeout=10)
    await _settle(mgr)

    # The parked resume ran once the user's turn ended, and ran nothing: the user's message
    # overtook the approved call.
    assert not target.exists()
    assert not mgr.is_running(sid)
    assert item.id not in mgr._deferred_resumes.get(sid, {})
    # ...and it says so, after the user's (stopped) turn.
    _assert_reported(mgr, sent, caplog, sid, item)
    rec = mgr.session_store.load(sid)
    kinds = [m.get("kind") for m in rec.messages if m.get("role") == "notice"]
    assert kinds[-2:] == ["interrupted", "answer_superseded"], kinds


async def _moved_on(tmp_path, sid: str, target):
    """A prompt left pending across a restart, then the user carries on in the session
    (a complete turn of their own) without answering it."""
    mgr = SessionManager(
        workspace=tmp_path,
        provider=_ChatOnlyScript(
            [
                _tool("write_file", {"path": str(target), "content": "ok"}, "call_w"),
                _text("Fine, something else then."),
            ]
        ),
    )
    engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
    item = await _run_until_pending(mgr, sid, engine)
    live = await mgr.ensure_engine(sid)
    assert mgr.try_mark_running(sid)
    try:
        async for _ in live.run("never mind, do something else"):
            pass
    finally:
        mgr.mark_idle(sid)
    mgr.save(sid, live)
    await _settle(mgr)
    return mgr, item


async def test_answer_given_after_the_conversation_moved_on_is_reported(
    tmp_path, monkeypatch, caplog
):
    """No collision at all: the prompt is answered from the Inbox only after the user has
    moved on. `resolve_inbox` finds the session idle and resumes directly — same code, same
    silence before."""
    target = tmp_path / "approved.txt"
    sid = "moved-on"
    mgr, item = await _moved_on(tmp_path, sid, target)
    sent = _record_broadcasts(mgr, monkeypatch)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    assert await asyncio.wait_for(mgr.resolve_inbox(item.id, "allow"), timeout=10)
    await _settle(mgr)

    assert not target.exists()
    _assert_reported(mgr, sent, caplog, sid, item)


async def test_answer_superseded_is_reported_after_the_engine_is_rebuilt(
    tmp_path, monkeypatch, caplog
):
    """Rebuilt from the store, the overtaken call is no longer bare: loading repairs the
    thread with a stand-in result ("tool result was lost during an interrupted turn") — which
    must not read as the call having run."""
    target = tmp_path / "approved.txt"
    sid = "moved-on-rebuilt"
    mgr, item = await _moved_on(tmp_path, sid, target)
    mgr._engines.pop(sid, None)  # evicted: the resume rebuilds it from the store
    sent = _record_broadcasts(mgr, monkeypatch)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    assert await asyncio.wait_for(mgr.resolve_inbox(item.id, "allow"), timeout=10)
    await _settle(mgr)

    rebuilt = mgr._engines[sid]
    assert any(
        m.get("role") == "tool" and m.get("tool_call_id") == "call_w"
        for m in rebuilt.messages
    ), "expected the load-time stand-in result for the overtaken call"
    assert not target.exists()
    _assert_reported(mgr, sent, caplog, sid, item)


async def test_answer_already_used_is_not_reported(tmp_path, monkeypatch, caplog):
    """A second resume of an answer the first one already used (two surfaces resuming the
    same item) finds the call with its real result: nothing was lost, nothing to say."""
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "already-used"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)
    sent = _record_broadcasts(mgr, monkeypatch)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
    await _settle(mgr)
    assert target.read_text() == "ok"
    await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
    await _settle(mgr)

    assert _notices(mgr, sid) == []
    assert _pushed(sent, sid) == []
    assert not _logged(caplog, item.id)


# A stale answer while a LATER prompt of the same session is still pending. The resume of
# the overtaken call X still calls `engine.resume()`, which continues the call that IS
# trailing (Y): it re-raises Y's prompt, the approver saves the thread, and the resume
# waits for Y's answer. Where the notice about X lands matters here: the loader
# (`ConversationStore._repair_tool_pairing`) treats a call as pending only while its
# assistant block is the very last message, so a notice saved after Y's block makes Y a
# call "the thread moved past" on the next load — it gets the stand-in result, and Y's own
# answer is then reported as superseded instead of running Y.


def _two_prompt_manager(tmp_path, x_target, y_target) -> SessionManager:
    return SessionManager(
        workspace=tmp_path,
        provider=_ChatOnlyScript(
            [
                _tool("write_file", {"path": str(x_target), "content": "x"}, "call_x"),
                _tool("write_file", {"path": str(y_target), "content": "y"}, "call_y"),
                _text("Done, y written."),
            ]
        ),
    )


async def _run_until_prompt(mgr: SessionManager, sid: str, engine, content: str, call_id: str):
    """Run a turn until the prompt for `call_id` is a pending Inbox item, then simulate a
    restart the way `_run_until_pending` does (cancel the suspended turn, drop the engine)."""

    def pending_item():
        return next((i for i in mgr.inbox.pending(sid) if i.tool_call_id == call_id), None)

    async def turn() -> None:
        async for _ in engine.run(content):
            pass

    task = asyncio.ensure_future(turn())
    try:
        await _eventually(lambda: pending_item() is not None, what=f"the {call_id} prompt")
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    mgr._engines.pop(sid, None)
    mgr.mark_idle(sid)
    return pending_item()


async def _stale_answer_waiting_on_a_later_prompt(tmp_path, monkeypatch, sid: str):
    """Prompt X pending across a restart; the user moves on and the model raises prompt Y,
    also left pending across a restart; then the user answers the stale X. Returns with
    X's resume blocked waiting for Y's answer."""
    x_target, y_target = tmp_path / "x.txt", tmp_path / "y.txt"
    mgr = _two_prompt_manager(tmp_path, x_target, y_target)
    engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
    item_x = await _run_until_pending(mgr, sid, engine)
    assert item_x.tool_call_id == "call_x"
    live = await mgr.ensure_engine(sid)
    item_y = await _run_until_prompt(mgr, sid, live, "never mind, do something else", "call_y")

    blocked_on_y = asyncio.Event()
    real_wait = mgr.inbox.wait

    async def wait_spy(item_id: str) -> str:
        if item_id == item_y.id:
            blocked_on_y.set()
        return await real_wait(item_id)

    monkeypatch.setattr(mgr.inbox, "wait", wait_spy)
    resume_x = asyncio.ensure_future(mgr.resolve_inbox(item_x.id, "allow"))
    await asyncio.wait_for(blocked_on_y.wait(), timeout=10)
    return mgr, item_x, item_y, resume_x, x_target, y_target


def _persisted_results_for(mgr: SessionManager, sid: str, call_id: str) -> list[str]:
    rec = mgr.session_store.load(sid)
    return [
        str(m.get("content"))
        for m in rec.messages
        if m.get("role") == "tool" and m.get("tool_call_id") == call_id
    ]


async def test_stale_answer_does_not_bury_a_later_pending_prompt_across_a_restart(
    tmp_path, monkeypatch, caplog
):
    sid = "stale-x-pending-y"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    mgr, item_x, item_y, resume_x, x_target, y_target = (
        await _stale_answer_waiting_on_a_later_prompt(tmp_path, monkeypatch, sid)
    )

    # What a restart right now would reload: Y must still be the pending call, not a call
    # the thread moved past.
    assert _persisted_results_for(mgr, sid, "call_y") == [], (
        "Y's pending call no longer loads as trailing: it got the stand-in result"
    )

    # ...and the restart itself, while X's resume is still waiting on Y.
    resume_x.cancel()
    try:
        await resume_x
    except asyncio.CancelledError:
        pass
    mgr._engines.pop(sid, None)
    await _settle(mgr)

    assert await asyncio.wait_for(mgr.resolve_inbox(item_y.id, "allow"), timeout=10)
    await _settle(mgr)

    assert y_target.exists() and y_target.read_text() == "y", "the approved Y never ran"
    assert not x_target.exists()
    assert _logged(caplog, item_x.id)
    assert not _logged(caplog, item_y.id), "Y's own answer was reported as superseded"


async def test_stale_answer_notice_lands_after_the_later_prompt_is_done(
    tmp_path, monkeypatch, caplog
):
    """No restart: Y is answered while X's resume is still waiting on it, so Y runs inside
    that resume. The notice about X is still left, once the continuation is done."""
    sid = "stale-x-live-y"
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)
    mgr, item_x, item_y, resume_x, x_target, y_target = (
        await _stale_answer_waiting_on_a_later_prompt(tmp_path, monkeypatch, sid)
    )
    sent = _record_broadcasts(mgr, monkeypatch)

    assert await asyncio.wait_for(mgr.resolve_inbox(item_y.id, "allow"), timeout=10)
    assert await asyncio.wait_for(resume_x, timeout=10)
    await _settle(mgr)

    assert y_target.read_text() == "y"
    assert not x_target.exists()
    _assert_reported(mgr, sent, caplog, sid, item_x)
    assert not _logged(caplog, item_y.id)
    rec = mgr.session_store.load(sid)
    assert rec.messages[-1].get("kind") == "answer_superseded", rec.messages[-1]
    assert [r for r in _persisted_results_for(mgr, sid, "call_y") if "Wrote" in r], (
        "expected Y's real result in the saved thread"
    )
