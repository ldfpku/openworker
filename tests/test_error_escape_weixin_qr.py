"""The WeChat QR login's commit step must report its failures where the GUI is looking.

`weixin_qr_start` runs the whole login as a background task and returns at once; the QR
pane polls `weixin_qr_status` every second, and that state object is the ONLY channel back
to the user. The flow's own failures already land there ("failed" + error). The commit
after the phone confirms — profile write, runtime state file, gateway reload — did not:
it ran shielded inside a bare `asyncio.create_task` whose exception nobody retrieved, so a
failed write left the pane on "Scanned — confirm on your phone" indefinitely, with the
reason nowhere but asyncio's context-free "Task exception was never retrieved".

Asserted: the task is kept by `spawn_retained` (the manager's background set), a failing
commit step flips the polled state to "failed" with the reason, the failure is logged with
its traceback, and the task itself ends cleanly.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from coworker.connectors.base import SendResult
from coworker.connectors.weixin_login import QrLoginState
from coworker.providers import ModelCapabilities, ProviderClient
from coworker.server.manager import SessionManager

MANAGER_LOGGER = "coworker.manager"


class _NoTurns(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("no turns expected")

    def capabilities(self, model):
        return ModelCapabilities()


def _fake_login(mgr, monkeypatch, *, failing_step: str = "") -> None:
    """A QR flow that has already been scanned and confirmed, and a commit whose
    `failing_step` ("profile_write" / "gateway_reload") raises."""

    async def fake_flow(*, on_state, **kw):
        # The phone scanned; what follows the confirm is the commit under test.
        on_state(QrLoginState(state="scanned"))
        return {
            "account_id": "newbot@im.bot",
            "token": "tok-x",
            "base_url": "https://api.example",
            "user_id": "wxid_scanner",
        }

    monkeypatch.setattr("coworker.connectors.weixin_login.qr_login_flow", fake_flow)

    async def fake_refresh():
        if failing_step == "gateway_reload":
            raise RuntimeError("gateway-reload-boom")

    monkeypatch.setattr(mgr, "refresh_gateway", fake_refresh)
    if failing_step == "profile_write":

        def disk_full(name, value):
            raise OSError("profile-write-boom: no space left on device")

        monkeypatch.setattr(mgr.secrets, "put", disk_full)
    monkeypatch.setattr(
        "coworker.connectors.senders._send_weixin",
        lambda *a, **k: SendResult(True, message_id="m"),
    )


async def test_login_task_is_retained_while_it_runs(tmp_path, monkeypatch):
    mgr = SessionManager(workspace=tmp_path, provider=_NoTurns())
    _fake_login(mgr, monkeypatch)

    await mgr.weixin_qr_start()
    task = mgr._weixin_qr_task
    try:
        assert task in mgr._bg_tasks, "the login task must be retained (spawn_retained)"
    finally:
        await asyncio.wait({task}, timeout=5)
    assert mgr.weixin_qr_status()["state"] == "confirmed"


@pytest.mark.parametrize("failing_step", ["profile_write", "gateway_reload"])
async def test_commit_failure_reaches_the_polled_status_and_the_log(
    tmp_path, monkeypatch, caplog, failing_step
):
    mgr = SessionManager(workspace=tmp_path, provider=_NoTurns())
    _fake_login(mgr, monkeypatch, failing_step=failing_step)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    out = await mgr.weixin_qr_start()
    assert out["ok"]
    task = mgr._weixin_qr_task
    await asyncio.wait({task}, timeout=5)

    assert task.done()
    status = mgr.weixin_qr_status()
    assert status["state"] == "failed", "the pane would wait on the phone forever"
    assert task.exception() is None, "the failure escaped into a task nobody awaits"
    expected = "profile-write-boom" if failing_step == "profile_write" else "gateway-reload-boom"
    assert status["error"] and expected in status["error"]
    assert mgr._weixin_qr_committing is False
    logged = [
        r
        for r in caplog.records
        if r.name == MANAGER_LOGGER and r.levelno >= logging.ERROR and r.exc_info
    ]
    assert logged, "the failure must be logged with its traceback"
