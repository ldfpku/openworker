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


def test_dm_without_designation_opens_one(tmp_path, monkeypatch):
    """First contact must answer without the owner having found Inbox ▸ Configure first: an
    undesignated DM route opens a session and claims the slot rather than dead-ending in
    `unrouted`, where the message sat with nobody watching."""
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    _connect_slack(mgr)
    delivered: list[tuple[str, str]] = []

    async def fake_deliver(session_id, message, *, source=None):
        delivered.append((session_id, message))

    monkeypatch.setattr(mgr, "deliver_to_session", fake_deliver)
    assert mgr.dm_session("slack") is None

    asyncio.run(mgr._dispatch_inbound(_dm("hello there")))
    opened = mgr.dm_session("slack")
    assert opened is not None
    assert delivered == [(opened, delivered[0][1])] and "hello there" in delivered[0][1]
    assert mgr.unrouted.list() == []
    # It claimed SLACK's slot, not the shared one -- WeChat DMs stay unaffected.
    assert mgr.dm_session() is None
    assert mgr.dm_session("weixin") is None

    # The second DM reuses that session — one opened per route, not one per message.
    asyncio.run(mgr._dispatch_inbound(_dm("still there?")))
    assert mgr.dm_session("slack") == opened
    assert [sid for sid, _ in delivered] == [opened, opened]

    # Titled from the CONNECTOR descriptor, not the platform id: `get_descriptor` at
    # manager module scope is the provider registry and silently misses connectors.
    assert mgr.session_store.load(opened).title == "来自Slack的私信"


def test_dm_tells_the_agent_to_reply_through_the_connector(tmp_path, monkeypatch):
    """A reply handle is not an instruction. Delivered as bare `tagged_text()`, a question
    from WeChat reads like a question in the transcript, so the agent answers in the session
    and the person on their phone gets silence -- observed in the field, 2026-08-31."""
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    _connect_slack(mgr)
    delivered: list[str] = []

    async def fake_deliver(session_id, message, *, source=None):
        delivered.append(message)

    monkeypatch.setattr(mgr, "deliver_to_session", fake_deliver)
    mgr.set_dm_session("sDM")

    asyncio.run(mgr._dispatch_inbound(_dm("which model are you?")))
    opening = delivered[0]
    assert "which model are you?" in opening
    assert "send_message" in opening  # names the tool...
    assert "slack:D1" in opening  # ...and the exact target to pass it
    assert "answering" in opening  # ...and why the session alone is not enough


def test_deleting_the_dm_session_frees_the_route(tmp_path, monkeypatch):
    """A route pointing at a deleted session isn't inert — `get_engine` would rebuild the dead
    id as an empty session on the next DM. Deleting it gives the slot up so the next DM opens
    a live session instead."""
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    _connect_slack(mgr)

    async def fake_deliver(session_id, message, *, source=None):
        pass

    monkeypatch.setattr(mgr, "deliver_to_session", fake_deliver)
    asyncio.run(mgr._dispatch_inbound(_dm("hello there")))
    opened = mgr.dm_session("slack")
    assert opened is not None

    mgr.delete_session(opened)
    assert mgr.dm_session("slack") is None

    asyncio.run(mgr._dispatch_inbound(_dm("again")))
    assert mgr.dm_session("slack") not in (None, opened)


def test_dm_routes_are_per_connector_not_one_shared_slot(tmp_path, monkeypatch):
    """One global slot meant WeChat, Slack and Telegram DMs raced for it: whichever
    connector got the first message claimed it, and every other platform's DMs then
    landed in a session opened for someone else's conversation."""
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    _connect_slack(mgr)
    mgr.secrets.put(
        "weixin:default",
        {"bot_token": "tok", "account_id": "bot@im.bot", "enabled": True},
    )
    delivered: list[tuple[str, str]] = []

    async def fake_deliver(session_id, message, *, source=None):
        delivered.append((session_id, message))

    monkeypatch.setattr(mgr, "deliver_to_session", fake_deliver)

    wx = MessageEvent(
        text="hi",
        source=SessionSource(
            platform="weixin", chat_id="wxid_peer", user_id="wxid_peer", chat_type="dm"
        ),
    )
    asyncio.run(mgr._dispatch_inbound(wx))
    asyncio.run(mgr._dispatch_inbound(_dm("hello")))

    weixin_session = mgr.dm_session("weixin")
    slack_session = mgr.dm_session("slack")
    assert weixin_session and slack_session
    assert weixin_session != slack_session  # separate conversations, separate sessions
    assert [sid for sid, _ in delivered] == [weixin_session, slack_session]

    # Pointing one connector elsewhere leaves the other alone.
    mgr.set_dm_session("sOther", platform="weixin")
    assert mgr.dm_session("weixin") == "sOther"
    assert mgr.dm_session("slack") == slack_session


def test_shared_fallback_covers_connectors_without_their_own_route(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    mgr.set_dm_session("sShared")  # no platform -> the fallback slot
    assert mgr.dm_session("telegram") == "sShared"
    mgr.set_dm_session("sWeixin", platform="weixin")
    assert mgr.dm_session("weixin") == "sWeixin"  # its own wins...
    assert mgr.dm_session("telegram") == "sShared"  # ...without disturbing the rest


def test_legacy_single_slot_pref_still_routes(tmp_path):
    """Upgrades must not silently lose the route the user already set."""
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    mgr._prefs["dm_session"] = "sLegacy"  # written by a pre-per-connector build
    assert mgr.dm_session("weixin") == "sLegacy"
    assert mgr.dm_session() == "sLegacy"


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
