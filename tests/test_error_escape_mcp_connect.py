"""Regression tests for two MCP-connect failure paths hardened in
`coworker/server/manager.py` (phase 2 of the 2026-09-19 exception-escape audit; phase 1
found these two while cross-checking the background-task-retention work in
`coworker/taskutil.py`, but they are ORDINARY uncaught exceptions, unrelated to that
audit's GC hazard). Both `connect_mcp` and `mcp_connect_connector` run fire-and-forget
via `SessionManager.spawn_background` — nothing in production ever calls `.exception()`
on the resulting Task, so an exception that reaches the coroutine boundary is either
invisible or shows up, much later and unrecognizably, as a "Task exception was never
retrieved" line at GC time.

1. `connect_mcp`: `load_mcp_servers(...)` (which internally calls `secrets.resolve`) and
   `_mcp_workspace_trusted(...)` now run inside their own `try`, ahead of the per-server
   loop — a failure there is reported through the exact same `_mcp_errors` channel (and
   `_mcp_authorizing` clearing) the per-server `except` below already used, so `list_mcp`
   reports `status: "error"` with a populated `last_error` instead of leaving the server
   stuck on `"authorizing"` forever.

2. `mcp_connect_connector`: the whole body now runs inside one `try`/`except`. Any
   failure — from `connect_mcp` itself, from writing the connector profile, or even from
   the pre-existing "connect failed" cleanup — rolls the seeded `mcp.json` entry back
   (owner decision: `list_mcp` skips connector-backed servers entirely, so a half-seeded
   entry would be invisible on the MCP page yet still live for every agent session). The
   rollback's own `delete_global_server` call is wrapped separately so a rollback failure
   is only logged, never overwrites the original error.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from fastapi.testclient import TestClient

from coworker.mcp import read_global
from coworker.server import SessionManager, create_app
from coworker.server import manager as mgr_mod

_LOGGER_NAME = "coworker.manager"


def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.02) -> bool:
    """Bounded poll — this repo has no pytest timeout configured, so every wait in this
    file must have an explicit ceiling or a stuck bug would hang the run instead of
    failing it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ============================================================================
# 1. connect_mcp: config-load failure ahead of the per-server try/except
# ============================================================================


async def test_connect_mcp_workspace_trust_exception_clears_authorizing_and_reports_error(
    tmp_path, monkeypatch, caplog
):
    """Inject: `manager._mcp_workspace_trusted` (called as an argument to
    `load_mcp_servers(...)`, i.e. before `connect_mcp`'s per-server loop even starts)
    raises RuntimeError.

    Expect: `connect_mcp` returns `{"ok": False, "error": ...}` — the same contract its
    normal per-server `except` branch already uses — "probe" is removed from
    `_mcp_authorizing`, the message lands in `_mcp_errors["probe"]` (same channel, same
    value), and a WARNING+ is logged.
    """
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.add_mcp("probe", {"command": "true", "enabled": True})
    manager.begin_mcp_connect("probe")
    assert "probe" in manager._mcp_authorizing  # fixture sanity, matches real caller order

    def boom(_workspace):
        raise RuntimeError("workspace trust check exploded")

    monkeypatch.setattr(manager, "_mcp_workspace_trusted", boom)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        result = await manager.connect_mcp("probe")

    assert result == {"ok": False, "error": "workspace trust check exploded"}
    assert "probe" not in manager._mcp_authorizing, (
        "authorizing flag left stuck — the GUI's /v1/mcp poll would show this server "
        "stuck on 'authorizing' forever"
    )
    assert manager._mcp_errors.get("probe") == result["error"], (
        "the failure should land in the same _mcp_errors channel connect_mcp's normal "
        "except branch already uses"
    )
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "the failure was never logged"
    )


def test_mcp_connect_route_config_load_exception_reports_error_status(
    tmp_path, monkeypatch, caplog
):
    """Route-level mirror, injecting at a different call site: `load_mcp_servers` itself
    (the module-level name `connect_mcp` calls; this is what actually wraps
    `secrets.resolve` in production) raises RuntimeError. Drives the real
    `POST /v1/mcp/{name}/connect` route exactly as the GUI does, then reads the real
    `GET /v1/mcp` payload (`SessionManager.list_mcp()`) to see what the GUI sees.

    Expect: once the background task finishes, `list_mcp()` reports `status: "error"`
    (not `"authorizing"`) with `last_error` populated, and a WARNING+ is logged.
    """
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.add_mcp("probe", {"command": "true", "enabled": True})

    def boom(*_args, **_kwargs):
        raise RuntimeError("mcp config load exploded")

    monkeypatch.setattr(mgr_mod, "load_mcp_servers", boom)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        with TestClient(create_app(manager)) as client:
            resp = client.post("/v1/mcp/probe/connect")
            assert resp.json() == {"ok": True, "started": True}
            assert _wait_until(lambda: not manager._bg_tasks), (
                "background connect_mcp() task never finished"
            )

    status = {s["name"]: s for s in manager.list_mcp()}
    entry = status["probe"]
    assert entry["status"] == "error"
    assert entry["last_error"] == "mcp config load exploded"
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "the failure was never logged"
    )


# ============================================================================
# 2. mcp_connect_connector: whole-body try/except with seeded-config rollback
# ============================================================================


async def test_mcp_connect_connector_seed_write_oserror_reports_error_without_writing_config(
    tmp_path, monkeypatch, caplog
):
    """Inject: `put_global_server` (the very first call in `mcp_connect_connector`, so
    nothing has been written to `mcp.json` yet) raises OSError.

    Expect: `mcp_connect_connector` returns `{"ok": False, "error": ...}`, logs a
    WARNING+, and — since nothing was ever seeded — there is nothing to roll back:
    "monday" stays absent from the global config.
    """
    manager = SessionManager(data_dir=tmp_path / "data")

    def boom(_name, _config):
        raise OSError("disk full while writing mcp.json")

    monkeypatch.setattr(mgr_mod, "put_global_server", boom)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        result = await manager.mcp_connect_connector("monday")

    assert result == {"ok": False, "error": "disk full while writing mcp.json"}
    assert "monday" not in read_global()
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "the failure was never logged"
    )


async def test_mcp_connect_connector_profile_write_oserror_rolls_back_seeded_config(
    tmp_path, monkeypatch, caplog
):
    """Inject further downstream: "monday" has NO pre-existing config, the seed config
    write goes through for real and the (faked) OAuth connect reports success, then
    `self.secrets.put` — marking the connector profile `mode: "mcp"` — raises OSError.

    Expect (owner decision: "any failure rolls back", accepted cost: a genuinely
    successful MCP connection is torn down too if only the profile write fails):
    `mcp_connect_connector` returns `{"ok": False, "error": ...}`, logs a WARNING+, and
    — since there was nothing to restore — the seeded "monday" entry this call wrote to
    `mcp.json` is removed again: nothing invisible-but-live is left behind (`list_mcp`
    skips connector-backed servers, so a lingering entry here would never surface on
    the MCP page).
    """
    manager = SessionManager(data_dir=tmp_path / "data")

    async def fake_connect_mcp(_name):
        return {"ok": True, "tools": 5}

    monkeypatch.setattr(manager, "connect_mcp", fake_connect_mcp)

    def boom(_profile, _data):
        raise OSError("disk full while writing secrets.json")

    monkeypatch.setattr(manager.secrets, "put", boom)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        result = await manager.mcp_connect_connector("monday")

    assert result == {"ok": False, "error": "disk full while writing secrets.json"}
    assert "monday" not in read_global(), (
        "a failed connect must not leave an enabled, tokenless MCP server entry behind "
        "— it would be invisible on /v1/mcp (connector-backed servers are skipped there) "
        "yet still live for every agent session"
    )
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "the failure was never logged"
    )


async def test_mcp_connect_connector_profile_write_oserror_restores_previous_config_when_one_existed(
    tmp_path, monkeypatch, caplog
):
    """Inject the same failure as the previous test, but "monday" was ALREADY connected
    before this call — its `mcp.json` entry exists (as if a user is re-clicking Connect
    on a server that already works). The seed write overwrites it, the (faked) OAuth
    connect reports success, then `self.secrets.put` raises OSError.

    Expect: `mcp_connect_connector` returns `{"ok": False, "error": ...}` and the
    ORIGINAL pre-existing "monday" entry is restored byte-for-byte — not deleted, and
    not left as this attempt's freshly-seeded value. Deleting it here would silently
    disconnect a server that was working fine before this attempt — a plain `delete`
    only undoes a seed write correctly when there was nothing to undo it TO.
    """
    manager = SessionManager(data_dir=tmp_path / "data")
    prior_config = {
        "url": "https://mcp.monday.com/mcp",
        "auth": "oauth",
        "requires_approval": False,
        "include_tools": ["get_user_context"],
        "enabled": True,
        # Distinguishes "the old, already-working config" from this call's fresh seed
        # in the assertion below — the real seed never sets this key.
        "custom_marker": "pre-existing-config",
    }
    manager.add_mcp("monday", prior_config)

    async def fake_connect_mcp(_name):
        return {"ok": True, "tools": 5}

    monkeypatch.setattr(manager, "connect_mcp", fake_connect_mcp)

    def boom(_profile, _data):
        raise OSError("disk full while writing secrets.json")

    monkeypatch.setattr(manager.secrets, "put", boom)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        result = await manager.mcp_connect_connector("monday")

    assert result == {"ok": False, "error": "disk full while writing secrets.json"}
    assert read_global()["monday"] == prior_config, (
        "a failed connect on an ALREADY-connected server must restore its previous "
        "config, not delete it or leave this attempt's fresh seed behind"
    )
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "the failure was never logged"
    )


async def test_mcp_connect_connector_cleanup_failure_after_failed_connect_keeps_original_error(
    tmp_path, monkeypatch, caplog
):
    """Inject: `connect_mcp` reports a normal (non-exception) failure — e.g. OAuth
    rejected by the user — and the cleanup this triggers (there was no pre-existing
    "monday" config, so the cleanup is a plain delete) itself raises OSError.

    Expect: the returned `error` is still the ORIGINAL connect failure reason, not the
    cleanup exception's message — overwriting it would hide why the connect actually
    failed. The cleanup failure is logged separately as its own WARNING.
    """
    manager = SessionManager(data_dir=tmp_path / "data")

    async def fake_connect_mcp(_name):
        return {"ok": False, "error": "oauth rejected by the user"}

    monkeypatch.setattr(manager, "connect_mcp", fake_connect_mcp)

    def boom_delete(_name):
        raise OSError("disk full while deleting the mcp.json entry")

    monkeypatch.setattr(mgr_mod, "delete_global_server", boom_delete)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        result = await manager.mcp_connect_connector("monday")

    assert result == {"ok": False, "error": "oauth rejected by the user"}, (
        "a cleanup failure after a normal (non-exception) failed connect must not "
        "overwrite the real connect failure reason"
    )
    messages = [r.getMessage() for r in caplog.records]
    assert any("cleanup after failed connect" in m for m in messages), (
        "the cleanup failure must still be logged"
    )


async def test_mcp_connect_connector_rollback_failure_does_not_mask_original_error(
    tmp_path, monkeypatch, caplog
):
    """Inject two independent failures: `self.secrets.put` raises OSError (the ORIGINAL
    failure, same as the previous test) AND `delete_global_server` — the rollback this
    now triggers — ALSO raises OSError.

    Expect: the rollback is best-effort. Its own failure is logged separately but must
    not overwrite or hide the original error: the returned `error` and the primary log
    line both still carry the original secrets.put failure. The seeded "monday" entry
    is left behind in this case (the rollback itself could not remove it) — an accepted,
    logged residue, not a silent one.
    """
    manager = SessionManager(data_dir=tmp_path / "data")

    async def fake_connect_mcp(_name):
        return {"ok": True, "tools": 5}

    monkeypatch.setattr(manager, "connect_mcp", fake_connect_mcp)

    def boom_secrets_put(_profile, _data):
        raise OSError("disk full while writing secrets.json")

    monkeypatch.setattr(manager.secrets, "put", boom_secrets_put)

    def boom_delete(_name):
        raise OSError("disk full while deleting the mcp.json entry too")

    monkeypatch.setattr(mgr_mod, "delete_global_server", boom_delete)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        result = await manager.mcp_connect_connector("monday")

    assert result == {"ok": False, "error": "disk full while writing secrets.json"}, (
        "the rollback's own failure must not overwrite the ORIGINAL error message"
    )
    messages = [r.getMessage() for r in caplog.records]
    assert any("disk full while writing secrets.json" in m for m in messages), (
        "the original failure must still be logged"
    )
    assert any("rollback cleanup failed" in m for m in messages), (
        "the rollback's own failure must also be logged, not swallowed silently"
    )
    # Documents the accepted best-effort outcome: rollback failed, so the seeded entry
    # is left behind — logged, not hidden (see assertions above).
    assert "monday" in read_global()


def test_connector_mcp_connect_route_oserror_task_completes_without_unhandled_exception(
    tmp_path, monkeypatch, caplog
):
    """Route-level mirror, driving the real `POST /v1/connectors/{name}/mcp-connect`
    exactly as the GUI does. `/v1/connectors` carries no error/authorizing field for
    this flow at all (`connectMcpBacked()` in surfaces/gui/src/api.ts always gets
    `{"ok": True, "started": True}` back from the POST itself; its callers only poll
    `GET /v1/connectors`'s `connected` field afterward, with no error path — see
    AddConnectionModal.tsx / ManageTabs.tsx). Adding that channel was explicitly
    descoped for this fix, so the only thing to check at this level is that the
    background Task itself completes cleanly instead of ending with an unretrieved
    exception, and that the rollback still happens when driven through the real route.

    Expect: the background task ends with `task.exception() is None`, a WARNING+ is
    logged, and the seeded "monday" entry is rolled back from `mcp.json`.
    """
    manager = SessionManager(data_dir=tmp_path / "data")
    started = threading.Event()
    gate = threading.Event()

    async def fake_connect_mcp(_name):
        # Blocks on a real OS thread so the test can grab `manager._bg_tasks`'s one
        # entry mid-flight — without this, `connect_mcp` (faked) → `secrets.put`
        # (boom) run back-to-back with no await point, and the task could finish (and
        # get discarded by spawn_retained's done-callback) before the polling loop
        # below ever gets scheduled.
        started.set()
        await asyncio.to_thread(gate.wait)
        return {"ok": True, "tools": 3}

    monkeypatch.setattr(manager, "connect_mcp", fake_connect_mcp)

    def boom(_profile, _data):
        raise OSError("disk full while writing secrets.json")

    monkeypatch.setattr(manager.secrets, "put", boom)

    with caplog.at_level("WARNING", logger=_LOGGER_NAME):
        with TestClient(create_app(manager)) as client:
            try:
                resp = client.post("/v1/connectors/monday/mcp-connect")
                assert resp.json() == {"ok": True, "started": True}
                assert started.wait(timeout=2.0), (
                    "background mcp_connect_connector() task never started"
                )
                assert len(manager._bg_tasks) == 1
                (task,) = tuple(manager._bg_tasks)
            finally:
                # Always release the worker thread — even (especially) if an assertion
                # above just failed, so TestClient's portal shutdown right after this
                # `with` block doesn't hang on a permanently-blocked to_thread() item.
                gate.set()
            assert _wait_until(lambda: task.done()), "background task never finished"

    assert task.exception() is None, (
        "mcp_connect_connector's background task ended with an unhandled exception "
        f"that nothing in production ever retrieves: {task.exception()!r}"
    )
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "the failure was never logged"
    )
    assert "monday" not in read_global(), "the seeded config must be rolled back"
