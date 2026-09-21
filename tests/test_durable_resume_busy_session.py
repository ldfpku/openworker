"""A durable resume must never become a second turn on an engine that is already running one.

`_durable_resume` continues a turn that was suspended on an Inbox prompt when that prompt is
answered with no live `inbox.wait` left to release (restart, evicted engine). Its callers
check `is_running` first, but the resume then awaits `ensure_engine` — a hop to a worker
thread behind the per-session engine lock, which a reconnecting socket holds while it
rebuilds the session — and a WebSocket `claim_turn` can win the session in that gap. The
resume used to claim it anyway with the unconditional `mark_running` and call
`engine.resume()` on the same engine, whose first act is `_cancel.clear()`: a Stop the user
had just pressed on the running turn was wiped, the older stream ended on
`StreamBridgeError`, and the resume's `finally: mark_idle` then released the claim the
socket's turn still held.

The contract asserted here: while another turn holds the session the resume runs nothing
and leaves the Stop flag and the claim alone; the approval is not lost — the resume runs
once the session goes idle — and it re-parks if yet another turn gets there first.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from coworker.server.manager import SessionManager
from coworker.sessions import SessionRecord
from test_durable_resume import (
    ScriptedProvider,
    _final_assistant_texts,
    _run_until_pending,
    _text,
    _tool,
)


async def _eventually(predicate, *, timeout: float = 10.0, what: str = "") -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, f"timed out waiting for: {what or predicate}"
        await asyncio.sleep(0.01)


async def _settle(mgr: SessionManager, *, timeout: float = 10.0) -> None:
    """Wait out every background flow the manager has in flight — parked resumes and the
    auto-title calls `mark_idle` fires (a finished resume can start more, so loop until
    none is left) — so nothing is left pending at teardown."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        pending = [
            t for t in (*mgr._bg_tasks, *mgr._autotitle_tasks) if not t.done()
        ]
        if not pending:
            return
        remaining = deadline - loop.time()
        assert remaining > 0, "background tasks never settled"
        await asyncio.wait(pending, timeout=remaining)


class _ChatOnlyScript(ScriptedProvider):
    """`ScriptedProvider`, except the post-turn auto-title call (every `mark_idle` can
    fire one) is answered on the side instead of consuming the next scripted chat turn."""

    def complete(self, *, model, messages, tools=None, **settings):
        if messages and "title chat sessions" in str(messages[0].get("content", "")):
            return _text("Approved File Write")
        return super().complete(model=model, messages=messages, tools=tools, **settings)


def _approval_manager(tmp_path, target):
    """A session whose model asks to write `target` (an approval prompt), then says Done."""
    return SessionManager(
        workspace=tmp_path,
        provider=_ChatOnlyScript(
            [
                _tool("write_file", {"path": str(target), "content": "ok"}, "call_w"),
                _text("Done — file written."),
            ]
        ),
    )


async def _approved_after_restart(mgr, sid, tmp_path):
    """Suspend a turn on its approval, "restart" (drop the live engine), then approve the
    item in the store — the state `_durable_resume` is called on. Returns (item, engine),
    the engine being the one the session's next turn — any turn — will run on."""
    engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
    item = await _run_until_pending(mgr, sid, engine)
    assert item.kind == "approval" and item.tool_call_id == "call_w"
    assert mgr.inbox.resolve(item.id, "allow")
    live = await mgr.ensure_engine(sid)
    return item, live


async def test_resume_while_a_turn_holds_the_session_does_not_start_a_second_turn(
    tmp_path,
):
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "busy-no-second-turn"
    item, live = await _approved_after_restart(mgr, sid, tmp_path)

    # A WebSocket turn owns the session (app.py `claim_turn`), and the user has just
    # pressed Stop on it — its stream is winding down on the engine's stop flag.
    assert mgr.try_mark_running(sid)
    live.request_interrupt()
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)

        assert live._cancel.is_set(), "the user's Stop was wiped by a second turn"
        assert mgr.is_running(sid), "the running turn's claim was released under it"
        assert not target.exists(), "the approved call ran as a second, concurrent turn"
    finally:
        mgr.mark_idle(sid)  # the socket's turn ends
        await _settle(mgr)


async def test_resume_deferred_by_a_running_turn_runs_once_that_turn_ends(tmp_path):
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "busy-then-idle"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)

    assert mgr.try_mark_running(sid)  # another turn is running
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
        assert not target.exists(), "must wait for the running turn, not collide with it"
    finally:
        mgr.mark_idle(sid)  # ...and now it has ended

    await _eventually(
        lambda: target.exists() and not mgr.is_running(sid),
        what="the deferred resume to run the approved write",
    )
    await _settle(mgr)
    assert target.read_text() == "ok"
    assert any("Done" in (t or "") for t in _final_assistant_texts(mgr, sid))
    assert mgr.inbox.pending(sid) == []


async def test_deferred_resume_waits_again_if_another_turn_gets_there_first(tmp_path):
    target = tmp_path / "approved.txt"
    mgr = _approval_manager(tmp_path, target)
    sid = "busy-twice"
    item, _live = await _approved_after_restart(mgr, sid, tmp_path)

    assert mgr.try_mark_running(sid)
    try:
        await asyncio.wait_for(mgr._durable_resume(item), timeout=10)
    finally:
        mgr.mark_idle(sid)
    # Before the deferred resume gets its turn (it has an engine lookup to await first),
    # the user sends another message and a new turn claims the session.
    assert mgr.try_mark_running(sid)
    try:
        await _settle(mgr)
        assert not target.exists(), "ran on top of the turn that claimed the session"
        assert mgr.is_running(sid)
    finally:
        mgr.mark_idle(sid)

    await _eventually(
        lambda: target.exists() and not mgr.is_running(sid),
        what="the twice-deferred resume to run",
    )
    await _settle(mgr)
    assert target.read_text() == "ok"


def _persisted(mgr: SessionManager, sid: str, workspace) -> None:
    """The row every real parked resume's session has: its suspended tool call was
    persisted when the prompt was raised (`persist_session`)."""
    mgr.session_store.save(
        SessionRecord(
            session_id=sid,
            workspace=str(workspace),
            model="test-model",
            mode="interactive",
            messages=[{"role": "user", "content": "go"}],
        )
    )


class _GatedEngine:
    """Counts how many `resume()` turns are in flight at once; each one holds until
    `gate` opens. `messages` is read by the post-turn auto-title hook."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.gate = asyncio.Event()
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def resume(self):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await self.gate.wait()
            yield SimpleNamespace(type="turn_start", data={})
        finally:
            self.active -= 1


async def test_two_resumes_of_one_session_never_overlap(tmp_path, monkeypatch):
    """Two prompts of one suspended assistant message answered back to back (both
    `resolve_inbox` calls see the session idle before either resume has claimed it)."""
    mgr = SessionManager(data_dir=tmp_path / "data", workspace=str(tmp_path))
    engine = _GatedEngine()
    built = 0

    async def fake_ensure_engine(session_id, **kwargs):
        nonlocal built
        built += 1
        return engine

    monkeypatch.setattr(mgr, "ensure_engine", fake_ensure_engine)
    monkeypatch.setattr(mgr, "save", lambda *a, **k: None)
    _persisted(mgr, "pair", tmp_path)  # a parked resume is only run for a live session
    first = SimpleNamespace(id="i1", session_id="pair", tool_call_id="c1")
    second = SimpleNamespace(id="i2", session_id="pair", tool_call_id="c2")

    both = asyncio.gather(mgr._durable_resume(first), mgr._durable_resume(second))
    try:
        await _eventually(lambda: built == 2, what="both resumes to reach their engine")
        for _ in range(5):
            await asyncio.sleep(0)
        assert engine.calls == 1 and engine.max_active == 1, (
            f"{engine.calls} resume turns started on one engine at once"
        )
    finally:
        engine.gate.set()
    await asyncio.wait_for(both, timeout=10)
    await _eventually(
        lambda: engine.calls == 2 and not mgr.is_running("pair"),
        what="the second resume to run after the first",
    )
    await _settle(mgr)
    assert engine.max_active == 1
