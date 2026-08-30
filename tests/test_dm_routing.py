"""DM routing + super-agent retirement: a DM goes to the user-designated session (delivered like any
background turn) or is parked as unrouted; the legacy super-agent surface is gone."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from coworker.connectors.base import MessageEvent, SessionSource
from coworker.providers import ModelCapabilities, ProviderClient
from coworker.server import create_app
from coworker.server.manager import SessionManager


class ScriptedProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("no turns expected")

    def capabilities(self, model):
        return ModelCapabilities()


def _dm(text, chat_id="D1", user="bob"):
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform="slack", chat_id=chat_id, user_name=user, chat_type="dm"
        ),
    )


def _connect_slack(mgr):
    """Inbound delivery is gated on the connector being CONNECTED (§4.3). Tests used to pass
    by riding the developer's real Slack profile; with the isolated state dir (conftest) each
    test must connect its own."""
    mgr.secrets.put(
        "slack:default",
        {"bot_token": "xoxb-test", "app_token": "xapp-test", "enabled": True},
    )


def test_dm_with_designated_session_delivers(tmp_path, monkeypatch):
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    _connect_slack(mgr)
    delivered: list[tuple[str, str]] = []

    async def fake_deliver(session_id, message, *, source=None):
        delivered.append((session_id, message))

    monkeypatch.setattr(mgr, "deliver_to_session", fake_deliver)
    mgr.set_dm_session("sDM")

    asyncio.run(mgr._dispatch_inbound(_dm("ping")))
    assert delivered[0][0] == "sDM"
    assert (
        "ping" in delivered[0][1]
    )  # the tagged text carries the message + a reply handle
    assert mgr.unrouted.list() == []


def test_weixin_dm_arms_standing_reply_grant(tmp_path, monkeypatch):
    """A weixin DM delivered to the designated session pre-approves send_message back
    to that peer (durably, via the mention-thread map get_engine re-seeds from).
    Slack DMs keep the normal approval flow — the grant is weixin-scoped."""
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    _connect_slack(mgr)
    mgr.secrets.put(
        "weixin:default",
        {"bot_token": "tok", "account_id": "bot@im.bot", "enabled": True},
    )

    async def fake_deliver(session_id, message, *, source=None):
        pass

    monkeypatch.setattr(mgr, "deliver_to_session", fake_deliver)
    mgr.set_dm_session("sDM")

    wx = MessageEvent(
        text="hi",
        source=SessionSource(
            platform="weixin", chat_id="wxid_peer", user_id="wxid_peer", chat_type="dm"
        ),
    )
    asyncio.run(mgr._dispatch_inbound(wx))
    assert mgr.mention_sessions.get("weixin:wxid_peer") == "sDM"

    asyncio.run(mgr._dispatch_inbound(_dm("ping")))
    assert mgr.mention_sessions.get("slack:D1") is None


def test_dm_without_designation_is_parked(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    assert mgr.dm_session() is None

    asyncio.run(mgr._dispatch_inbound(_dm("hello there")))
    parked = mgr.unrouted.list()
    assert len(parked) == 1
    assert parked[0]["text"] == "hello there"
    assert parked[0]["reason"] == "no DM session designated"


def test_dm_route_endpoints(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    client = TestClient(create_app(mgr))

    assert client.get("/v1/messaging/dm-route").json()["dm_session"] is None
    assert (
        client.post("/v1/messaging/dm-route", json={"session_id": "sX"}).json()[
            "dm_session"
        ]
        == "sX"
    )
    assert client.get("/v1/messaging/dm-route").json()["dm_session"] == "sX"
    # a falsy id clears it
    assert (
        client.post("/v1/messaging/dm-route", json={"session_id": ""}).json()[
            "dm_session"
        ]
        is None
    )


def test_dm_session_persists_across_manager_reload(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    mgr.set_dm_session("sKeep")
    # a fresh manager over the same data dir reloads the prefs-backed designation
    reborn = SessionManager(
        workspace=tmp_path, data_dir=mgr._data_base, provider=ScriptedProvider()
    )
    assert reborn.dm_session() == "sKeep"


def test_superagent_surface_is_gone(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    assert not hasattr(mgr, "superagent")
    assert not hasattr(mgr, "sa_register")
    client = TestClient(create_app(mgr))
    # the retired routes 404
    assert client.get("/v1/superagent").status_code == 404
