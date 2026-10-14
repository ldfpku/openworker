"""Approval ownership must hold on EVERY transport, not just the Slack lane.

The owner check for protected items (approval/directory/plan) used to run only when
platform == "slack". A Telegram reply or button therefore resolved protected items with no
owner or channel-binding validation, and items mirrored to Slack were resolvable from
Telegram. These tests pin the cross-transport enforcement. Questions stay answerable by any
allow-listed member.

WeChat is the fork's own transport: it has no inbox binding and no owner list — the §31
mention-thread map binds a DM peer to a session, and that peer (only) may answer that
session's prompts. The gate must keep honouring exactly that rule.
"""

from __future__ import annotations

import asyncio

from coworker.connectors.base import InteractionEvent, MessageEvent, SessionSource
from coworker.interactions import encode
from coworker.providers import ModelCapabilities, ProviderClient
from coworker.server.manager import SessionManager

WX_PEER = "weixin:wxid_peer"
WX_STRANGER = "weixin:wxid_stranger"
WX_SESSION = "sDM"


class NoTurnsProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("no model turns expected")

    def capabilities(self, model):
        return ModelCapabilities()


def _manager(tmp_path) -> SessionManager:
    return SessionManager(data_dir=tmp_path / "data", provider=NoTurnsProvider())


def _tg_reply(text: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform="telegram", chat_id="99", user_id="tg-user", user_name="TG"
        ),
    )


def _wx_reply(text: str, *, peer: str = WX_PEER, chat_type: str = "dm") -> MessageEvent:
    chat_id = peer.split(":", 1)[1]
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform="weixin", chat_id=chat_id, user_id=chat_id, chat_type=chat_type
        ),
    )


def _wx_manager(tmp_path) -> SessionManager:
    manager = _manager(tmp_path)
    # The mention-thread map IS the WeChat binding: `_dispatch_inbound` writes it on every
    # inbound DM, and the prompt flow reads it back in both directions.
    manager.mention_sessions.set(WX_PEER, WX_SESSION, channel=WX_PEER)
    return manager


def test_telegram_reply_cannot_resolve_a_protected_approval(tmp_path):
    manager = _manager(tmp_path)
    approval = manager.inbox.add_approval("s1", "Run it?")
    consumed = manager._resolve_inbox_reply(_tg_reply(f"approve [ow:{approval.id}]"))
    # The token was recognized (consumed), but the protected item must NOT be resolved.
    assert consumed is True
    assert manager.inbox.get(approval.id).state == "pending"


def test_telegram_button_cannot_resolve_a_protected_approval(tmp_path):
    manager = _manager(tmp_path)

    class GatewayStub:
        def __init__(self):
            self.rejections = []
            self.settings = {}

        async def reject_interaction(self, event, text=""):
            self.rejections.append(getattr(event, "user_id", None))

        async def deliver(self, target, text):
            return None

        async def update_message(self, *args):
            raise AssertionError("a refused interaction must not update the message")

    gateway = GatewayStub()
    manager.gateway = gateway
    approval = manager.inbox.add_approval("s1", "Run it?")

    asyncio.run(
        manager._on_interaction(
            InteractionEvent(
                platform="telegram",
                chat_id="99",
                message_id="1",
                value=encode(approval.id, "allow"),
                user_id="tg-user",
                user_name="TG",
            )
        )
    )
    assert manager.inbox.get(approval.id).state == "pending"
    assert gateway.rejections == ["tg-user"]


def test_telegram_reply_can_still_answer_a_question(tmp_path):
    # Questions are not protected — an allow-listed member may answer from any transport.
    manager = _manager(tmp_path)
    question = manager.inbox.add_question("s1", "Which region?", options=["A", "B"])
    consumed = manager._resolve_inbox_reply(_tg_reply(f"A [ow:{question.id}]"))
    assert consumed is True
    assert manager.inbox.get(question.id).resolution == "A"


def test_slack_bound_item_is_not_resolvable_from_telegram(tmp_path):
    # Cross-transport: an item whose inbox is bound to Slack must not be resolved by a
    # Telegram reply, even though Slack's own owner check would apply on the Slack lane.
    manager = _manager(tmp_path)
    manager.inbox_routing.set_binding("ops", channel="slack", target="T1:C1")
    approval = manager.inbox.add_approval("s1", "Deploy?", inbox="ops")
    consumed = manager._resolve_inbox_reply(_tg_reply(f"approve [ow:{approval.id}]"))
    assert consumed is True
    assert manager.inbox.get(approval.id).state == "pending"


# -- WeChat keeps its own ownership rule ---------------------------------------------------

def test_weixin_session_owner_still_resolves_a_protected_approval(tmp_path):
    manager = _wx_manager(tmp_path)
    approval = manager.inbox.add_approval(WX_SESSION, "Run `write_file`?")
    assert manager._resolve_inbox_reply(_wx_reply(f"同意 [ow:{approval.id}]")) is True
    assert manager.inbox.get(approval.id).resolution == "allow"


def test_weixin_non_owner_is_refused(tmp_path):
    # Allow-listed, DMing the bot, but bound to no session (or another one): refused.
    manager = _wx_manager(tmp_path)
    approval = manager.inbox.add_approval(WX_SESSION, "Run `write_file`?")
    stranger = _wx_reply(f"同意 [ow:{approval.id}]", peer=WX_STRANGER)
    assert manager._resolve_inbox_reply(stranger) is True  # consumed, but NOT honoured
    assert manager.inbox.get(approval.id).state == "pending"


def test_weixin_group_traffic_is_refused_even_from_the_owner(tmp_path):
    manager = _wx_manager(tmp_path)
    approval = manager.inbox.add_approval(WX_SESSION, "Run `write_file`?")
    group = _wx_reply(f"同意 [ow:{approval.id}]", chat_type="group")
    assert manager._resolve_inbox_reply(group) is True
    assert manager.inbox.get(approval.id).state == "pending"


def test_weixin_owner_resolves_even_when_the_inbox_is_bound_elsewhere(tmp_path):
    # WeChat mirroring is not driven by inbox routing: a default inbox bound to Telegram
    # (or Slack) must not lock the WeChat peer out of its own session's prompts.
    manager = _wx_manager(tmp_path)
    manager.inbox_routing.set_binding("default", channel="telegram", target="4242")
    approval = manager.inbox.add_approval(WX_SESSION, "Run `write_file`?")
    assert manager._resolve_inbox_reply(_wx_reply(f"同意 [ow:{approval.id}]")) is True
    assert manager.inbox.get(approval.id).resolution == "allow"
