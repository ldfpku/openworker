"""The six `manager.spawn_background(...)` call sites (app.py REST routes + the two
team-delivery `_deliver` closures in manager.py): each used to fire an
`asyncio.create_task(...)` whose return value nobody held. These tests drive the real
route/method and prove the in-flight coroutine is tracked in `manager._bg_tasks` — a
strong reference the bare `create_task` calls never had — and is dropped once it
finishes. See `coworker/taskutil.py` for the underlying mechanism and
`tests/test_taskutil.py` for its unit tests.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from coworker.server import SessionManager, create_app


def _poll_until_empty(tasks: set, *, timeout: float = 5.0) -> None:
    """`_bg_tasks`'s done-callback runs on the server loop — a different thread from
    the TestClient portal calling this — so poll with a timeout instead of asserting
    the discard is instantaneous. Same reasoning/style as
    `test_ws_turn_task_tracked_and_cleared` in tests/test_server.py."""
    deadline = time.monotonic() + timeout
    while tasks and time.monotonic() < deadline:
        time.sleep(0.05)
    assert tasks == set()


# -- REST routes: /v1/mcp/{name}/connect, /v1/connectors/{name}/mcp-connect, ---------
# -- /auth/callback, /v1/providers/openai-codex/signin -------------------------------


def test_mcp_connect_route_retains_background_task(tmp_path, monkeypatch):
    manager = SessionManager(data_dir=tmp_path / "data")
    started = threading.Event()
    gate = threading.Event()

    async def fake_connect_mcp(name):
        started.set()
        await asyncio.to_thread(gate.wait)
        return {"ok": True}

    monkeypatch.setattr(manager, "connect_mcp", fake_connect_mcp)

    with TestClient(create_app(manager)) as client:
        try:
            resp = client.post("/v1/mcp/probe-server/connect")
            assert resp.json() == {"ok": True, "started": True}

            assert started.wait(timeout=2.0), "background connect_mcp() never started"
            assert len(manager._bg_tasks) == 1
            (task,) = manager._bg_tasks
            assert not task.done()
        finally:
            # Always release the worker thread blocked in `gate.wait()` — even (in
            # fact, especially) if an assertion above just failed. Otherwise the
            # TestClient portal's shutdown, right after this `with` block, hangs
            # waiting for that permanently-blocked to_thread() work item instead of
            # letting the real failure surface.
            gate.set()
        _poll_until_empty(manager._bg_tasks)


def test_connector_mcp_connect_route_retains_background_task(tmp_path, monkeypatch):
    manager = SessionManager(data_dir=tmp_path / "data")
    started = threading.Event()
    gate = threading.Event()

    async def fake_mcp_connect_connector(name):
        started.set()
        await asyncio.to_thread(gate.wait)
        return {"ok": True}

    monkeypatch.setattr(manager, "mcp_connect_connector", fake_mcp_connect_connector)

    with TestClient(create_app(manager)) as client:
        try:
            # "monday" is a real connector descriptor with mcp_url set (required for
            # the route to get past its `d is None or not d.mcp_url` guard).
            resp = client.post("/v1/connectors/monday/mcp-connect")
            assert resp.json() == {"ok": True, "started": True}

            assert started.wait(timeout=2.0), "background mcp_connect_connector() never started"
            assert len(manager._bg_tasks) == 1
            (task,) = manager._bg_tasks
            assert not task.done()
        finally:
            # See test_mcp_connect_route_retains_background_task for why this must
            # run unconditionally: an assertion failure above must not leave the
            # to_thread() worker blocked forever and hang TestClient's teardown.
            gate.set()
        _poll_until_empty(manager._bg_tasks)


def test_codex_signin_route_retains_background_task(tmp_path, monkeypatch):
    manager = SessionManager(data_dir=tmp_path / "data")
    started = threading.Event()
    gate = threading.Event()

    async def fake_codex_signin():
        started.set()
        await asyncio.to_thread(gate.wait)
        return {"ok": True}

    monkeypatch.setattr(manager, "codex_signin", fake_codex_signin)

    with TestClient(create_app(manager)) as client:
        try:
            resp = client.post("/v1/providers/openai-codex/signin")
            assert resp.json() == {"ok": True, "started": True}

            assert started.wait(timeout=2.0), "background codex_signin() never started"
            assert len(manager._bg_tasks) == 1
            (task,) = manager._bg_tasks
            assert not task.done()
        finally:
            # See test_mcp_connect_route_retains_background_task for why this must
            # run unconditionally.
            gate.set()
        _poll_until_empty(manager._bg_tasks)


def test_cloud_auth_callback_route_retains_background_task(tmp_path, monkeypatch):
    """`/auth/callback`'s `_restore_connections` closure awaits
    `asyncio.to_thread(lambda: cloud.sync_connections(...))` — block THAT (off-loop
    already, so a plain `threading.Event` is fine, no `asyncio.to_thread` needed on
    our side) while `cloud.complete_login` is stubbed to succeed so the route reaches
    the spawn line at all."""
    from coworker import cloud

    manager = SessionManager(workspace=tmp_path)
    monkeypatch.setattr(
        cloud, "complete_login", lambda secrets, config, code, state: {"ok": True}
    )

    started = threading.Event()
    gate = threading.Event()

    def fake_sync_connections(secrets, config):
        started.set()
        gate.wait()
        return {"ok": True}  # no "restored" key -> refresh_gateway() is never reached

    monkeypatch.setattr(cloud, "sync_connections", fake_sync_connections)

    with TestClient(create_app(manager)) as client:
        try:
            resp = client.get("/auth/callback", params={"code": "c", "state": "s"})
            assert resp.status_code == 200
            assert "Signed in" in resp.text

            assert started.wait(timeout=2.0), "background _restore_connections() never started"
            assert len(manager._bg_tasks) == 1
            (task,) = manager._bg_tasks
            assert not task.done()
        finally:
            # See test_mcp_connect_route_retains_background_task for why this must
            # run unconditionally.
            gate.set()
        _poll_until_empty(manager._bg_tasks)


# -- team delivery: manager._maybe_backstop_lead / _drain_team_member ----------------


def _build_team(monkeypatch, tmp_path):
    """Same recipe as tests/test_team_wake.py's `manager` fixture plus
    `test_lead_backstop_fires_only_for_forgotten_timers` / `create_team_prespawns...`:
    a real SessionManager with one lead + one worker and one assigned, in-progress
    item — enough for both `_drain_team_member` and `_maybe_backstop_lead` to find
    real work to deliver."""
    from coworker.agents.base import Agent
    from coworker.server import manager as mgr_mod
    from coworker.sessions import SessionRecord
    from coworker.teams import Actor, Role
    from coworker.teams.model import space_for_workspace

    ws = tmp_path / "repo"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", workspace=str(ws))
    worker_agent = Agent(name="swe-worker", title="SWE", system_prompt="p", team="worker")
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
    result = manager.create_team("lead-sid", [{"persona": "swe-worker", "name": "nia"}])
    assert result["approved"], result
    team = manager.teams.for_lead_session("lead-sid")
    space = space_for_workspace(manager.default_workspace)
    lead = Actor(id=team.lead_actor, role=Role.LEAD)
    item = manager.team_store.create_item(space, lead, title="T", criteria="c")
    manager.team_store.assign(space, lead, item["id"], "nia")
    return manager, team, space, item


async def test_drain_team_member_retains_background_delivery(tmp_path, monkeypatch):
    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker_sid = team.workers[0].session_id

    started = asyncio.Event()
    gate = asyncio.Event()

    async def fake_deliver(session_id, message, *, source=None):
        started.set()
        await gate.wait()

    monkeypatch.setattr(manager, "deliver_to_session", fake_deliver)

    try:
        n = await manager._drain_team_member(
            team, session_id=worker_sid, actor="nia", is_lead=False
        )
        assert n == 1
        await asyncio.wait_for(started.wait(), timeout=2.0)

        assert len(manager._bg_tasks) == 1
        (task,) = manager._bg_tasks
        assert not task.done()
        assert manager._team_inflight == {worker_sid}
    finally:
        # Release the gate unconditionally: if an assertion above already failed,
        # this still lets `_deliver` finish instead of leaking a pending task past
        # the end of this test's event loop.
        gate.set()

    await asyncio.wait_for(task, timeout=2.0)
    assert manager._bg_tasks == set()
    assert manager._team_inflight == set()


async def test_maybe_backstop_lead_retains_background_delivery(tmp_path, monkeypatch):
    from coworker.teams import Actor, Role

    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker = Actor(id="nia", role=Role.WORKER)
    manager.team_store.transition(space, worker, item["id"], "in_progress")
    manager._team_last_alive["lead-sid"] = time.time() - 700
    assert manager._lead_backstop_due(team), "fixture wrong — backstop not due"

    started = asyncio.Event()
    gate = asyncio.Event()

    async def fake_deliver(session_id, message, *, source=None):
        started.set()
        await gate.wait()

    monkeypatch.setattr(manager, "deliver_to_session", fake_deliver)

    try:
        n = await manager._maybe_backstop_lead(team)
        assert n == 1
        await asyncio.wait_for(started.wait(), timeout=2.0)

        assert len(manager._bg_tasks) == 1
        (task,) = manager._bg_tasks
        assert not task.done()
        assert manager._team_inflight == {"lead-sid"}
    finally:
        # See test_drain_team_member_retains_background_delivery for why this must
        # run unconditionally.
        gate.set()

    await asyncio.wait_for(task, timeout=2.0)
    assert manager._bg_tasks == set()
    assert manager._team_inflight == set()


# -- bonus: no running loop must not strand the in-flight marker ---------------------
#
# `_drain_team_member`/`_maybe_backstop_lead` have no `await` of their own before the
# spawn_background(...) line (everything up to there is sync store/dict work); their
# coroutine objects therefore run to completion on a single manual `.send(None)`, with
# no asyncio loop running anywhere — exactly the "sync caller" case spawn_background's
# `tasks`/`_team_inflight`-cleanup branch exists for. Driving them this way from a
# plain (non-async) test function is cheap and needs no extra fixtures.


def _run_to_completion_with_no_loop(coro):
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    coro.close()
    pytest.fail(
        "coroutine suspended instead of completing synchronously — "
        "this probe's no-running-loop assumption no longer holds"
    )


def test_drain_team_member_no_loop_does_not_strand_team_inflight(tmp_path, monkeypatch):
    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker_sid = team.workers[0].session_id

    coro = manager._drain_team_member(
        team, session_id=worker_sid, actor="nia", is_lead=False
    )
    result = _run_to_completion_with_no_loop(coro)
    assert result == 1
    assert manager._bg_tasks == set()
    assert manager._team_inflight == set()


def test_maybe_backstop_lead_no_loop_does_not_strand_team_inflight(tmp_path, monkeypatch):
    from coworker.teams import Actor, Role

    manager, team, space, item = _build_team(monkeypatch, tmp_path)
    worker = Actor(id="nia", role=Role.WORKER)
    manager.team_store.transition(space, worker, item["id"], "in_progress")
    manager._team_last_alive["lead-sid"] = time.time() - 700
    assert manager._lead_backstop_due(team), "fixture wrong — backstop not due"

    coro = manager._maybe_backstop_lead(team)
    result = _run_to_completion_with_no_loop(coro)
    assert result == 1
    assert manager._bg_tasks == set()
    assert manager._team_inflight == set()
