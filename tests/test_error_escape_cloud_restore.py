"""Regression tests for the `/auth/callback` route's `_restore_connections` closure
(coworker/server/app.py): it used to wrap its whole body in `except Exception: pass`
— no logging, no state written anywhere. A broker hiccup during
`cloud.sync_connections` or a failure in the follow-up `manager.refresh_gateway()`
both used to vanish without a trace; the sign-in page still said "Signed in" and the
user only discovered connections didn't come back when something downstream (a
connector, the relay) quietly didn't work.

2026-09-19 audit, item 5. Per the accepted fix, this is a log-only fix (no new cloud
status field, no GUI/frontend channel — that stays a follow-up decision): each
failure now gets its own try/except so the two remedies aren't confused with each
other — a `sync_connections` failure means connections were never restored, a
`refresh_gateway` failure means they WERE restored but the gateway is still running
on stale wiring. Both tests assert a WARNING+ log record appears, and together they
assert the two failures produce distinguishable log text.

Isolation, following `tests/test_background_task_retention.py`'s
`test_cloud_auth_callback_route_retains_background_task` recipe: `cloud.complete_login`
is stubbed to succeed without any network call; `cloud.sync_connections` /
`manager.refresh_gateway` are stubbed per test to raise instead of doing real work.
No real cloud broker round trip, no keyring. `with TestClient(app) as client:` is
required (not a bare `TestClient(app)`) so the background task runs on the same
loop the route ran on and we can poll `manager._bg_tasks` for it to actually finish
before checking the logs — bounded to 5s, well under the file's 30s budget.
"""

from __future__ import annotations

import logging
import time

from fastapi.testclient import TestClient

from coworker import cloud
from coworker.server import SessionManager, create_app


def _wait_until_bg_tasks_empty(manager: SessionManager, *, timeout: float = 5.0) -> None:
    """The done-callback that drops a finished task from `_bg_tasks` runs on the
    server's own loop/thread (the TestClient portal), not this test's thread — poll
    instead of asserting it happened instantaneously. Same reasoning as
    `_poll_until_empty` in tests/test_background_task_retention.py."""
    deadline = time.monotonic() + timeout
    while manager._bg_tasks and time.monotonic() < deadline:
        time.sleep(0.05)
    assert manager._bg_tasks == set(), "background _restore_connections() never finished"


def test_sync_connections_failure_in_cloud_restore_is_logged(
    tmp_path, monkeypatch, caplog
):
    """Inject: `cloud.sync_connections` (the "restore managed connections" step)
    raises RuntimeError, as a broker 500 or a network blip would.

    Expected: the route itself still returns its normal "Signed in" 200 response
    (this is background, best-effort work that must not hold that response
    hostage), and a WARNING+ log record is emitted for the failure — `caplog` used
    to be empty here before the fix. `manager.refresh_gateway` must never be
    reached (it's gated on `sync_connections`'s result), so its own log message must
    not appear either.
    """
    manager = SessionManager(workspace=str(tmp_path))
    monkeypatch.setattr(
        cloud, "complete_login", lambda secrets, config, code, state: {"ok": True}
    )

    def boom_sync_connections(secrets, config):
        raise RuntimeError("sync-connections-boom")

    monkeypatch.setattr(cloud, "sync_connections", boom_sync_connections)

    caplog.set_level(logging.WARNING, logger="coworker.server")

    with TestClient(create_app(manager)) as client:
        resp = client.get("/auth/callback", params={"code": "c", "state": "s"})
        # The route itself must stand regardless — sign-in succeeded, only the
        # best-effort restore (running in the background, after this response was
        # already built) is what fails.
        assert resp.status_code == 200
        assert "Signed in" in resp.text

        _wait_until_bg_tasks_empty(manager)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "sync_connections failure must produce a WARNING+ log record"
    text = " ".join(r.getMessage() for r in warnings)
    assert "restor" in text.lower()  # "restoring managed connections failed"
    assert "gateway" not in text.lower()  # refresh_gateway's own message, not this one


def test_refresh_gateway_failure_in_cloud_restore_is_logged(
    tmp_path, monkeypatch, caplog
):
    """Inject: `cloud.sync_connections` succeeds and reports something restored, so
    `_restore_connections` proceeds to `await manager.refresh_gateway()` — which is
    then the thing that raises (e.g. rebuilding a connector's listener blows up).

    Expected: same as the sync_connections case — route still returns normally, and
    a WARNING+ log record is emitted — but the message text must be distinguishable
    from the sync_connections failure's message (different remedy: connections WERE
    restored, only the gateway reload needs retrying/a restart).
    """
    manager = SessionManager(workspace=str(tmp_path))
    monkeypatch.setattr(
        cloud, "complete_login", lambda secrets, config, code, state: {"ok": True}
    )
    monkeypatch.setattr(
        cloud,
        "sync_connections",
        lambda secrets, config: {"ok": True, "restored": ["install-1"]},
    )

    async def boom_refresh_gateway():
        raise RuntimeError("refresh-gateway-boom")

    monkeypatch.setattr(manager, "refresh_gateway", boom_refresh_gateway)

    caplog.set_level(logging.WARNING, logger="coworker.server")

    with TestClient(create_app(manager)) as client:
        resp = client.get("/auth/callback", params={"code": "c", "state": "s"})
        assert resp.status_code == 200
        assert "Signed in" in resp.text

        _wait_until_bg_tasks_empty(manager)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "refresh_gateway failure must produce a WARNING+ log record"
    text = " ".join(r.getMessage() for r in warnings)
    assert "gateway" in text.lower()


def test_sync_connections_and_refresh_gateway_failures_log_different_text(
    tmp_path, monkeypatch, caplog
):
    """Both failure modes must be tellable apart from the log text alone — someone
    reading the logs needs to know whether connections were never restored at all
    (retry sign-in / check the broker) or were restored but the gateway didn't pick
    them up (reconnect or restart). This drives both scenarios in the same test to
    compare their messages directly, rather than relying on two separate tests
    happening to use different wording by coincidence.
    """
    manager = SessionManager(workspace=str(tmp_path))
    monkeypatch.setattr(
        cloud, "complete_login", lambda secrets, config, code, state: {"ok": True}
    )

    caplog.set_level(logging.WARNING, logger="coworker.server")

    # First: sync_connections itself fails.
    monkeypatch.setattr(
        cloud,
        "sync_connections",
        lambda secrets, config: (_ for _ in ()).throw(RuntimeError("sync-boom")),
    )
    with TestClient(create_app(manager)) as client:
        client.get("/auth/callback", params={"code": "c1", "state": "s1"})
        _wait_until_bg_tasks_empty(manager)
    sync_failure_messages = {r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING}
    caplog.clear()

    # Second: sync_connections succeeds, refresh_gateway fails.
    monkeypatch.setattr(
        cloud,
        "sync_connections",
        lambda secrets, config: {"ok": True, "restored": ["install-1"]},
    )

    async def boom_refresh_gateway():
        raise RuntimeError("gateway-boom")

    monkeypatch.setattr(manager, "refresh_gateway", boom_refresh_gateway)
    with TestClient(create_app(manager)) as client:
        client.get("/auth/callback", params={"code": "c2", "state": "s2"})
        _wait_until_bg_tasks_empty(manager)
    gateway_failure_messages = {r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING}

    assert sync_failure_messages, "sync_connections failure must be logged"
    assert gateway_failure_messages, "refresh_gateway failure must be logged"
    assert sync_failure_messages.isdisjoint(gateway_failure_messages), (
        "the two failure modes must not share identical log text — a reader must be "
        "able to tell 'connections never restored' apart from 'restored but gateway "
        "reload failed' from the message alone"
    )
