"""Team delivery (`manager._drain_team_member`) and the post-turn bookkeeping it
depends on.

Delivering a wake and consuming the batch it carried are two separate writes: the
turn is dispatched first, the feed / subscription / chat cursors move past the
batch second. Two ways the second write used to be lost, both silently — the
`_deliver` closure runs on a `spawn_background` task whose done-callback
deliberately only discards (see `coworker/taskutil.py`), so nothing ever retrieved
the exception:

  * a `consume_*` call raising (a locked or full sqlite db) left the batch
    unconsumed although the agent had already answered it, so every following tick
    delivered the same digest again — a second (third, fourth…) paid model turn;
  * `deliver_to_session`'s own `finally` (`mark_idle` -> `_maybe_autotitle`, then
    `broadcast_session`) runs after the turn is complete and persisted, and a raise
    there propagated out of a delivery that SUCCEEDED, skipping the cursor advance
    entirely and the `turn_done` broadcast with it.

What is asserted here: a failure in either place is contained and logged; a
completed turn always gets its bookkeeping; and a member whose bookkeeping failed
settles it before it is woken again instead of being handed the same digest twice
(`manager._team_pending_cursors`) — while never becoming permanently undrainable.
"""

from __future__ import annotations

import asyncio
import logging

from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.server.manager import SessionManager

MANAGER_LOGGER = "coworker.manager"


class _ScriptedProvider(ProviderClient):
    """One canned assistant turn per `complete()` — a real turn with no network.
    Same shape as tests/test_durable_resume.py's provider."""

    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="ack", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


class _Breaker:
    """A monkeypatched store call that fails while `broken` is set. Lets one test
    break a cursor write, watch the drain hold off, then repair the store and watch
    the member settle its books and resume."""

    def __init__(self, real, label: str):
        self._real = real
        self._label = label
        self.broken = True
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        if self.broken:
            raise RuntimeError(f"{self._label} failed (injected)")
        return self._real(*args, **kwargs)


def _build_team(monkeypatch, tmp_path):
    """A real SessionManager with one lead + one worker, chat enabled, and one item
    assigned to the worker — enough queued board news for `_drain_team_member` to
    have something to deliver. Same recipe as
    tests/test_background_task_retention.py's `_build_team`, plus `enable_chat` and
    a scripted provider (so the tests that let the real `deliver_to_session` run
    never reach a vendor API)."""
    from coworker.agents.base import Agent
    from coworker.server import manager as mgr_mod
    from coworker.sessions import SessionRecord
    from coworker.teams import Actor, Role
    from coworker.teams.model import space_for_workspace

    ws = tmp_path / "repo"
    ws.mkdir()
    manager = SessionManager(
        data_dir=tmp_path / "data", workspace=str(ws), provider=_ScriptedProvider()
    )
    worker_agent = Agent(
        name="swe-worker", title="SWE", system_prompt="p", team="worker"
    )
    monkeypatch.setattr(mgr_mod, "get_agent", lambda name: worker_agent)
    manager.session_store.save(
        SessionRecord(
            session_id="lead-sid",
            workspace=manager.default_workspace,
            model="m",
            mode="interactive",
            messages=[],
            agent="swe-lead",
        )
    )
    result = manager.create_team(
        "lead-sid", [{"persona": "swe-worker", "name": "nia"}], enable_chat=True
    )
    assert result["approved"], result
    team = manager.teams.for_lead_session("lead-sid")
    space = space_for_workspace(manager.default_workspace)
    lead = Actor(id=team.lead_actor, role=Role.LEAD)
    item = manager.team_store.create_item(space, lead, title="T", criteria="c")
    manager.team_store.assign(space, lead, item["id"], "nia")
    return manager, team, space, item


def _stub_delivery(manager, monkeypatch) -> list[str]:
    """Replace `deliver_to_session` with a no-op that records who it was called for
    — the tests about bookkeeping care that a delivery happened, not what the model
    said. Returns the (live) list of delivered session ids."""
    delivered: list[str] = []

    async def fake_deliver(session_id, message, *, source=None):
        delivered.append(session_id)

    monkeypatch.setattr(manager, "deliver_to_session", fake_deliver)
    return delivered


async def _finished_delivery_task(manager, *, timeout: float = 5.0):
    """The single `_deliver` task `_drain_team_member` just spawned, run to
    completion. Bounded wait — this repo configures no pytest timeout, so an
    unbounded await would hang the whole run instead of failing. `asyncio.wait`
    rather than `await task`, because the point of several tests here is to inspect
    `task.exception()` instead of re-raising it."""
    assert len(manager._bg_tasks) == 1, manager._bg_tasks
    (task,) = manager._bg_tasks
    await asyncio.wait({task}, timeout=timeout)
    assert task.done(), "the background delivery never finished"
    return task


def _manager_warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.name == MANAGER_LOGGER and r.levelno >= logging.WARNING
    ]


def _pending_kinds(manager, session_id) -> list[str]:
    return [kind for kind, *_ in manager._team_pending_cursors.get(session_id, [])]


# -- a cursor write that fails must be contained, logged and dead-lettered -----------


async def test_feed_cursor_failure_is_contained_and_dead_lettered(
    tmp_path, monkeypatch, caplog
):
    """Injected: `team_store.consume_feed` raises after a delivered wake.

    Expected: the failure stays on the delivery task (nothing escapes to be lost at
    GC time), it is logged, the in-flight marker is released, the outstanding
    advance is parked on the member, and a dead-letter entry says the message WAS
    delivered — the opposite of what the panel's own wording implies.
    """
    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker_sid = team.workers[0].session_id
    delivered = _stub_delivery(manager, monkeypatch)
    monkeypatch.setattr(
        manager.team_store,
        "consume_feed",
        _Breaker(manager.team_store.consume_feed, "consume_feed"),
    )

    with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
        assert (
            await manager._drain_team_member(
                team, session_id=worker_sid, actor="nia", is_lead=False
            )
            == 1
        )
        task = await _finished_delivery_task(manager)

    assert delivered == [worker_sid], "fixture wrong — nothing was delivered"
    assert task.exception() is None, (
        "the cursor failure escaped onto the fire-and-forget delivery task: "
        f"{task.exception()!r}"
    )
    assert _manager_warnings(caplog), "the cursor-advance failure was never logged"
    # Released by `_deliver`'s own `finally`, so a failed batch can never make this
    # member permanently undrainable.
    assert manager._team_inflight == set()
    assert _pending_kinds(manager, worker_sid) == ["feed"]

    (entry,) = manager.unrouted.list()
    assert entry["source"] == worker_sid
    assert entry["sender"] == "-"
    assert entry["reason"].startswith("delivered, but the cursor did not advance")
    assert "the agent has the message" in entry["reason"]
    # The digest lives on the board; the dead-letter text is a one-line pointer.
    assert len(entry["text"]) < 200 and "feed" in entry["text"]


async def test_subscription_cursor_failure_is_contained_and_dead_lettered(
    tmp_path, monkeypatch, caplog
):
    """Injected: `team_store.consume_subscription` raises, on a LEAD drain that has
    both feed events and subscription events — so `consume_feed` has already landed
    when it fires.

    Expected: contained and logged as above, and the ledger holds ONLY the
    subscription advance: a cursor that already moved must not be redone.
    """
    from coworker.teams import Actor, Role

    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker = Actor(id="nia", role=Role.WORKER)
    manager.team_store.transition(space, worker, item["id"], "in_progress")
    # "review" is one of TeamStore.SUBSCRIBED_TRANSITIONS, so this event reaches the
    # lead through BOTH `feed_for` and `subscribed_events` — the case the two cursor
    # writes exist for.
    manager.team_store.transition(space, worker, item["id"], "review")
    assert manager.team_store.subscribed_events(
        space, team.lead_actor
    ), "fixture wrong — the lead has no subscription events"
    _stub_delivery(manager, monkeypatch)
    monkeypatch.setattr(
        manager.team_store,
        "consume_subscription",
        _Breaker(manager.team_store.consume_subscription, "consume_subscription"),
    )

    with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
        assert (
            await manager._drain_team_member(
                team, session_id="lead-sid", actor=team.lead_actor, is_lead=True
            )
            == 1
        )
        task = await _finished_delivery_task(manager)

    assert task.exception() is None, f"escaped: {task.exception()!r}"
    assert _manager_warnings(caplog)
    assert manager._team_inflight == set()
    assert _pending_kinds(manager, "lead-sid") == ["subscription"]
    assert manager.team_store.feed_for(space, team.lead_actor) == [], (
        "the feed cursor landed before the failure — it must not be rolled back"
    )
    assert len(manager.unrouted.list()) == 1


async def test_chat_cursor_failure_is_contained_and_dead_lettered(
    tmp_path, monkeypatch, caplog
):
    """Injected: `chat_store.consume` raises — the third and last cursor write,
    reached only when the team has chat enabled and the member has unread posts.

    Expected: same containment, and the ledger holds only the chat advance.
    """
    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker_sid = team.workers[0].session_id
    manager.chat_store.post(
        team.chat_group, "lead", "@nia how is T going?", author_role="lead"
    )
    assert manager.chat_store.unread_for(
        team.chat_group, "nia"
    ), "fixture wrong — the worker has no unread chat"
    _stub_delivery(manager, monkeypatch)
    monkeypatch.setattr(
        manager.chat_store,
        "consume",
        _Breaker(manager.chat_store.consume, "chat consume"),
    )

    with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
        assert (
            await manager._drain_team_member(
                team, session_id=worker_sid, actor="nia", is_lead=False
            )
            == 1
        )
        task = await _finished_delivery_task(manager)

    assert task.exception() is None, f"escaped: {task.exception()!r}"
    assert _manager_warnings(caplog)
    assert manager._team_inflight == set()
    assert _pending_kinds(manager, worker_sid) == ["chat"]
    assert manager.team_store.feed_for(space, "nia") == []
    assert len(manager.unrouted.list()) == 1


# -- the ledger: settle the books before waking the member again ---------------------


async def test_member_with_pending_cursors_is_not_redelivered(
    tmp_path, monkeypatch, caplog
):
    """A member whose cursor advance failed is drained again while the store is
    still broken.

    Expected: no second delivery. The drain tries the outstanding bookkeeping
    first, it fails again, and the member is skipped for this round — the digest it
    already answered is not handed to it (and paid for) a second time. The failure
    is logged again, but only the first one is dead-lettered, so a store that stays
    broken cannot flood the 200-entry panel.
    """
    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker_sid = team.workers[0].session_id
    delivered = _stub_delivery(manager, monkeypatch)
    breaker = _Breaker(manager.team_store.consume_feed, "consume_feed")
    monkeypatch.setattr(manager.team_store, "consume_feed", breaker)

    assert (
        await manager._drain_team_member(
            team, session_id=worker_sid, actor="nia", is_lead=False
        )
        == 1
    )
    await _finished_delivery_task(manager)
    assert delivered == [worker_sid]

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
        assert (
            await manager._drain_team_member(
                team, session_id=worker_sid, actor="nia", is_lead=False
            )
            == 0
        ), "the member was woken again although its books were not settled"

    assert delivered == [worker_sid], "the same digest was delivered twice"
    assert manager._bg_tasks == set(), "a second delivery task was spawned"
    assert _manager_warnings(caplog), "the repeated failure was not logged"
    assert _pending_kinds(manager, worker_sid) == ["feed"]
    assert len(manager.unrouted.list()) == 1, "the dead-letter store was flooded"


async def test_repeated_bookkeeping_failure_does_not_strand_the_member(
    tmp_path, monkeypatch
):
    """The store stays broken across several ticks, then recovers.

    Expected: every skipped round leaves the member drainable — no in-flight marker
    stuck, no running marker stuck, the ledger intact — and the very next drain
    after the store recovers settles the books and lets the member receive news
    again. A failing cursor must never silence a member permanently.
    """
    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker_sid = team.workers[0].session_id
    delivered = _stub_delivery(manager, monkeypatch)
    breaker = _Breaker(manager.team_store.consume_feed, "consume_feed")
    monkeypatch.setattr(manager.team_store, "consume_feed", breaker)

    assert (
        await manager._drain_team_member(
            team, session_id=worker_sid, actor="nia", is_lead=False
        )
        == 1
    )
    await _finished_delivery_task(manager)

    for _ in range(3):
        assert (
            await manager._drain_team_member(
                team, session_id=worker_sid, actor="nia", is_lead=False
            )
            == 0
        )
        assert manager._team_inflight == set()
        assert manager._running_sessions == set()
        assert _pending_kinds(manager, worker_sid) == ["feed"]

    breaker.broken = False  # the store recovers
    # Nothing new on the board yet, so this drain only settles the books.
    assert (
        await manager._drain_team_member(
            team, session_id=worker_sid, actor="nia", is_lead=False
        )
        == 0
    )
    assert manager._team_pending_cursors == {}
    assert manager.team_store.feed_for(space, "nia") == []
    assert delivered == [worker_sid]

    # …and the member is live again: fresh board news reaches it normally.
    from coworker.teams import Actor, Role

    manager.team_store.comment(
        space, Actor(id=team.lead_actor, role=Role.LEAD), item["id"], "ping"
    )
    assert (
        await manager._drain_team_member(
            team, session_id=worker_sid, actor="nia", is_lead=False
        )
        == 1
    )
    task = await _finished_delivery_task(manager)
    assert task.exception() is None
    assert delivered == [worker_sid, worker_sid]
    assert manager.team_store.feed_for(space, "nia") == []


async def test_partial_advance_replays_only_the_cursor_that_failed(
    tmp_path, monkeypatch
):
    """A lead whose `consume_feed` landed but whose `consume_subscription` did not,
    then the store recovers.

    Expected: the replay runs the subscription advance only. Re-running an advance
    that already landed would be harmless for a monotonic cursor but is exactly the
    "redo the whole batch" behaviour the ledger exists to avoid, so it is asserted
    against here.
    """
    from coworker.teams import Actor, Role

    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker = Actor(id="nia", role=Role.WORKER)
    manager.team_store.transition(space, worker, item["id"], "in_progress")
    manager.team_store.transition(space, worker, item["id"], "review")
    _stub_delivery(manager, monkeypatch)

    feed_spy = _Breaker(manager.team_store.consume_feed, "consume_feed")
    feed_spy.broken = False  # a spy, not a breaker: the feed cursor must still work
    sub_breaker = _Breaker(manager.team_store.consume_subscription, "consume_sub")
    monkeypatch.setattr(manager.team_store, "consume_feed", feed_spy)
    monkeypatch.setattr(manager.team_store, "consume_subscription", sub_breaker)

    assert (
        await manager._drain_team_member(
            team, session_id="lead-sid", actor=team.lead_actor, is_lead=True
        )
        == 1
    )
    await _finished_delivery_task(manager)
    assert len(feed_spy.calls) == 1 and len(sub_breaker.calls) == 1
    assert _pending_kinds(manager, "lead-sid") == ["subscription"]

    sub_breaker.broken = False
    assert (
        await manager._drain_team_member(
            team, session_id="lead-sid", actor=team.lead_actor, is_lead=True
        )
        == 0
    )
    assert len(feed_spy.calls) == 1, "the feed cursor that already landed was redone"
    assert len(sub_breaker.calls) == 2
    assert manager._team_pending_cursors == {}
    assert manager.team_store.subscribed_events(space, team.lead_actor) == []


# -- deliver_to_session's own post-turn finally --------------------------------------


async def test_post_turn_finally_failure_does_not_block_cursor_advance(
    tmp_path, monkeypatch, caplog
):
    """Injected: `_maybe_autotitle` raises — a failure inside `mark_idle`, which
    `deliver_to_session` calls from its `finally` (auto-titling reads the session
    store and spawns its own task; any of that can fail).

    This runs the REAL `deliver_to_session` over a scripted provider, so the turn
    genuinely happens: the session ends up with a persisted assistant reply before
    the injected failure fires. The `finally` is reached only after `engine.run(...)`
    is drained and `self.save(...)` has returned, and the `except` clause is already
    behind it — so the raise came out of a delivery that SUCCEEDED.

    Expected: cosmetic post-turn bookkeeping cannot un-deliver a completed
    delivery. Nothing escapes, the failure is logged, all three cursors advance as
    they would have, and the `turn_done` broadcast still reaches the socket (without
    it the GUI spins forever on a turn that finished).
    """
    from coworker.teams import Actor, Role

    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker = Actor(id="nia", role=Role.WORKER)
    manager.team_store.transition(space, worker, item["id"], "in_progress")
    manager.team_store.transition(space, worker, item["id"], "review")
    manager.chat_store.post(
        team.chat_group, "nia", "@lead please review T", author_role="worker"
    )
    assert manager.team_store.subscribed_events(space, team.lead_actor)
    assert manager.chat_store.unread_for(team.chat_group, "lead")

    def boom(session_id):
        raise RuntimeError("_maybe_autotitle failed (injected)")

    monkeypatch.setattr(manager, "_maybe_autotitle", boom)

    seen: list[str] = []

    async def socket(message):
        seen.append(message.get("type"))

    manager.register_session_client("lead-sid", socket)

    with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
        assert (
            await manager._drain_team_member(
                team, session_id="lead-sid", actor=team.lead_actor, is_lead=True
            )
            == 1
        )
        task = await _finished_delivery_task(manager, timeout=20.0)

    record = manager.session_store.load("lead-sid")
    assert record is not None and any(
        m.get("role") == "assistant" for m in record.messages
    ), "fixture wrong — the turn did not run, so nothing was delivered"

    assert task.exception() is None, (
        "a post-turn finally failure escaped onto the fire-and-forget delivery "
        f"task: {task.exception()!r}"
    )
    assert _manager_warnings(caplog), "the post-turn failure was never logged"
    assert manager._team_inflight == set()
    assert manager._running_sessions == set()
    assert "turn_done" in seen, "the turn never reported itself finished to the GUI"

    assert manager.team_store.feed_for(space, team.lead_actor) == []
    assert manager.team_store.subscribed_events(space, team.lead_actor) == []
    assert manager.chat_store.unread_for(team.chat_group, "lead") == []
    assert manager._team_pending_cursors == {}
    assert manager.unrouted.list() == []


async def test_backstop_wake_failure_is_contained(tmp_path, monkeypatch, caplog):
    """Injected: `deliver_to_session` raises on the lead check-in backstop — the
    other `_deliver` closure on the same fire-and-forget pattern.

    Expected: contained and logged, and the in-flight marker released so the next
    tick can try again. The backstop carries a computed digest, not a queue batch,
    so there is no bookkeeping to hold.
    """
    import time

    from coworker.teams import Actor, Role

    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker = Actor(id="nia", role=Role.WORKER)
    manager.team_store.transition(space, worker, item["id"], "in_progress")
    manager._team_last_alive["lead-sid"] = time.time() - 700
    assert manager._lead_backstop_due(team), "fixture wrong — backstop not due"

    async def fake_deliver(session_id, message, *, source=None):
        raise RuntimeError("backstop delivery failed (injected)")

    monkeypatch.setattr(manager, "deliver_to_session", fake_deliver)

    with caplog.at_level(logging.WARNING, logger=MANAGER_LOGGER):
        assert await manager._maybe_backstop_lead(team) == 1
        task = await _finished_delivery_task(manager)

    assert task.exception() is None, f"escaped: {task.exception()!r}"
    assert _manager_warnings(caplog)
    assert manager._team_inflight == set()
