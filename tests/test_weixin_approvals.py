"""Finishing an approval from WeChat — directory grants, ask_user, plan confirmations.

The gate the desktop app draws inline is invisible to someone on their phone, which is exactly
where they are when a DM session is working for them. So every parked prompt whose session is
bound to a WeChat peer is ALSO mirrored there, as a numbered plain-text card (personal WeChat has
no buttons), and a reply of "1" resolves the same Inbox item the app would have.

The safety edges are the point of most of these: only the peer bound to the item's own session
can answer, group traffic never can, and an unreadable reply leaves the gate open rather than
guessing.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from coworker.connectors import ConnectorSettings, Gateway, MessageEvent
from coworker.connectors.base import SendResult, SessionSource
from coworker.connectors.fake import FakeAdapter
from coworker.permissions import Mode
from coworker.providers import ModelCapabilities, ProviderClient
from coworker.server import manager as manager_mod
from coworker.server.manager import SessionManager

PEER = "weixin:wxid_peer"
OTHER_PEER = "weixin:wxid_stranger"
SESSION = "sDM"


class ScriptedProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("no turns expected")

    def capabilities(self, model):
        return ModelCapabilities()


class GatewayStub:
    """Just the one method the WeChat mirror uses."""

    def __init__(self, ok: bool = True) -> None:
        self.sent: list[tuple[str, str]] = []
        self.ok = ok

    async def deliver(self, target: str, text: str):
        self.sent.append((target, text))
        return SendResult(self.ok, error=None if self.ok else "no adapter for weixin")

    def texts_to(self, target: str = PEER) -> list[str]:
        return [t for tgt, t in self.sent if tgt == target]


class WeixinFakeAdapter(FakeAdapter):
    platform = "weixin"


def _manager(tmp_path) -> SessionManager:
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider())
    mgr.gateway = GatewayStub()
    # The §31 mention-thread map IS the binding: `_dispatch_inbound` writes this entry on
    # every inbound WeChat DM, and both directions of the prompt flow read it back.
    mgr.mention_sessions.set(PEER, SESSION, channel=PEER)
    return mgr


def _event(text: str, *, target_peer: str = PEER, chat_type: str = "dm") -> MessageEvent:
    chat_id = target_peer.split(":", 1)[1]
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform="weixin",
            chat_id=chat_id,
            user_id=chat_id,
            chat_type=chat_type,
        ),
    )


@pytest.fixture(autouse=True)
def _no_dangling_watchdogs():
    """Each prompt arms a 30-minute expiry task; cancel whatever a test left armed so the
    loop doesn't shut down with pending work."""
    yield
    for mgr in _MANAGERS:
        for task in list(mgr._wx_watchdogs.values()):
            task.cancel()
        mgr._wx_watchdogs.clear()
    _MANAGERS.clear()


_MANAGERS: list[SessionManager] = []


def _tracked(tmp_path) -> SessionManager:
    mgr = _manager(tmp_path)
    _MANAGERS.append(mgr)
    return mgr


def _directory_item(mgr, *, path="/srv/data", writable=False):
    return mgr.inbox.add_directory(
        SESSION,
        "Grant access to a folder?",
        body="I need the deploy logs",
        data={"path": path, "writable": writable, "primary": False},
    )


# -- the outbound card ----------------------------------------------------------
async def test_directory_prompt_mirrors_a_numbered_card(tmp_path):
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)

    await mgr.mirror_inbox_item(item)

    (text,) = mgr.gateway.texts_to()
    assert "【需要你确认】" in text
    assert "建议路径：/srv/data（只读）" in text
    assert "1 同意" in text and "2 拒绝" in text
    assert "也可直接回复一个绝对路径" in text
    assert "30 分钟内有效" in text
    assert f"[ow:{item.id}]" in text
    # What was offered is recorded, so a reply is scored against exactly that card.
    assert item.data["wx"]["target"] == PEER
    assert [c["intent"] for c in item.data["wx"]["choices"]] == ["allow", "deny"]


async def test_directory_prompt_without_a_path_asks_for_one(tmp_path):
    """With nothing proposed, "1 同意" would grant a path that doesn't exist — the card asks
    for one instead of offering a grant that resolves to nothing."""
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr, path="")

    await mgr.mirror_inbox_item(item)

    (text,) = mgr.gateway.texts_to()
    assert "请直接回复要授权的绝对路径" in text
    assert "1 拒绝" in text  # the only discrete choice left
    assert "建议路径" not in text


async def test_grouped_question_is_not_answerable_from_wechat(tmp_path):
    """A 2+ question form can't be resolved by one reply, so it is announced but NOT
    registered — whatever the person types next stays an ordinary message to the agent."""
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_question(
        SESSION,
        "Which region?",
        questions=[{"question": "Which region?"}, {"question": "Which tier?"}],
    )

    await mgr.mirror_inbox_item(item)

    (text,) = mgr.gateway.texts_to()
    assert "请在电脑端回答" in text
    assert "wx" not in item.data
    assert mgr._resolve_inbox_reply(_event("华东区，标准档")) is False
    assert mgr.inbox.get(item.id).state == "pending"


async def test_a_binding_whose_connector_is_gone_arms_no_watchdog(tmp_path):
    """The binding outlives the connection — it is just the last DM's mention-thread entry. A
    card nobody could be shown must not be registered, or the watchdog would decline the gate
    half an hour later on their behalf."""
    mgr = _tracked(tmp_path)
    mgr.gateway = GatewayStub(ok=False)  # "no adapter for weixin"
    item = _directory_item(mgr)

    await mgr.mirror_inbox_item(item)

    assert "wx" not in item.data
    assert mgr._wx_watchdogs == {}
    assert mgr._resolve_inbox_reply(_event("1")) is True  # "already handled or expired"
    assert mgr.inbox.get(item.id).state == "pending"


async def test_a_session_with_no_wechat_peer_mirrors_nothing(tmp_path):
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_approval("sOther", "Run `write_file`?")

    await mgr.mirror_inbox_item(item)

    assert mgr.gateway.sent == []
    assert "wx" not in item.data


# -- the inbound reply ----------------------------------------------------------
async def test_numbered_reply_resolves_the_prompt_and_never_reaches_the_agent(tmp_path):
    """The whole flow through the real gateway: the reply is consumed by the resolver hop
    BEFORE `_dispatch_inbound`, so the agent is released with an ANSWER rather than handed
    the digit 1 as a new instruction."""
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr, path=str(tmp_path), writable=True)
    await mgr.mirror_inbox_item(item)

    routed: list[MessageEvent] = []

    async def handler(ev: MessageEvent) -> None:
        routed.append(ev)

    gw = Gateway(
        settings={"weixin": ConnectorSettings("weixin", enabled=True, allow_all=True)},
        handler=handler,
        reply_resolver=mgr._resolve_inbox_reply,
    )
    adapter = WeixinFakeAdapter()
    gw.register(adapter)
    await gw.start()

    waiting = asyncio.create_task(mgr.inbox.wait(item.id))
    await adapter.inject("1", chat_id="wxid_peer", user_id="wxid_peer")

    answer = json.loads(await asyncio.wait_for(waiting, 1))
    assert answer == {"granted": True, "path": str(tmp_path), "writable": True}
    assert routed == []  # never dispatched as a turn
    await gw.stop()


async def test_chinese_keyword_reply_also_resolves(tmp_path):
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_plan(SESSION, "Approve the plan?", body="1. do it")
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event("同意")) is True
    assert json.loads(mgr.inbox.get(item.id).resolution) == {
        "approved": True,
        "mode": "interactive",
    }


async def test_declining_an_approval_from_wechat(tmp_path):
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_approval(SESSION, "Run `run_shell`?", body="rm -rf /tmp/x")
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event("2")) is True
    assert mgr.inbox.get(item.id).resolution == "deny"
    await asyncio.sleep(0)  # let the receipt task run
    assert any("已收到：拒绝" in t for t in mgr.gateway.texts_to())


async def test_a_reply_from_an_unbound_peer_answers_nothing(tmp_path):
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event("1", target_peer=OTHER_PEER)) is False
    assert mgr.inbox.get(item.id).state == "pending"


async def test_group_traffic_never_answers_a_prompt(tmp_path):
    """The binding is a 1:1 reply handle; in a group anyone could otherwise approve on the
    owner's behalf."""
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event("1", chat_type="group")) is False
    assert mgr.inbox.get(item.id).state == "pending"


async def test_token_reply_still_requires_the_peer_to_own_the_session(tmp_path):
    """A quoted card carries `[ow:<id>]`, which on its own would let any allow-listed WeChat
    sender resolve any session's prompt."""
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_approval(SESSION, "Run `write_file`?")
    await mgr.mirror_inbox_item(item)

    stranger = _event(f"同意 [ow:{item.id}]", target_peer=OTHER_PEER)
    assert mgr._resolve_inbox_reply(stranger) is True  # consumed, but NOT honoured
    assert mgr.inbox.get(item.id).state == "pending"

    owner = _event(f"同意 [ow:{item.id}]")
    assert mgr._resolve_inbox_reply(owner) is True
    assert mgr.inbox.get(item.id).resolution == "allow"


async def test_answering_twice_says_it_is_already_handled(tmp_path):
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_approval(SESSION, "Run `write_file`?")
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event("1")) is True
    assert mgr._resolve_inbox_reply(_event("1")) is True
    await asyncio.sleep(0)
    assert any("该请求已处理或已过期" in t for t in mgr.gateway.texts_to())


async def test_unreadable_reply_keeps_the_gate_open_and_reaches_the_agent(tmp_path):
    """"What does that folder contain?" is a question for the agent, not an answer — it is
    steered in as usual, with a reminder that the gate is still open."""
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event("那个目录里有什么？")) is False
    assert mgr.inbox.get(item.id).state == "pending"
    await asyncio.sleep(0)
    assert any("我还在等你确认" in t for t in mgr.gateway.texts_to())


async def test_a_bare_number_after_the_prompt_closed_says_so(tmp_path):
    mgr = _tracked(tmp_path)
    assert mgr._resolve_inbox_reply(_event("1")) is True
    await asyncio.sleep(0)
    assert any("该请求已处理或已过期" in t for t in mgr.gateway.texts_to())


# -- typed paths (there is no folder picker on a phone) -------------------------
async def test_a_typed_absolute_path_grants_that_folder(tmp_path):
    mgr = _tracked(tmp_path)
    folder = tmp_path / "logs"
    folder.mkdir()
    item = _directory_item(mgr, path="/srv/data", writable=True)
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event(str(folder))) is True
    answer = json.loads(mgr.inbox.get(item.id).resolution)
    assert answer["granted"] is True and answer["writable"] is True
    assert answer["path"] == str(folder.resolve())


async def test_a_path_that_does_not_exist_re_prompts_without_consuming_the_item(tmp_path):
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event(str(tmp_path / "nope"))) is True
    assert mgr.inbox.get(item.id).state == "pending"  # they can try again
    await asyncio.sleep(0)
    assert any("有效的绝对目录路径" in t for t in mgr.gateway.texts_to())

    # A relative path isn't a path attempt at all — it goes to the agent with the nudge.
    assert mgr._resolve_inbox_reply(_event("logs/today")) is False
    assert mgr.inbox.get(item.id).state == "pending"


# -- expiry + the other surface -------------------------------------------------
async def test_an_unanswered_prompt_expires_as_a_decline(tmp_path, monkeypatch):
    """`InboxStore.wait` has no timeout, so without the watchdog the suspended turn would
    wait forever on a phone the person put down."""
    monkeypatch.setattr(manager_mod, "WX_PROMPT_TTL_MIN", 0)
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)

    await mgr.mirror_inbox_item(item)
    assert json.loads(await asyncio.wait_for(mgr.inbox.wait(item.id), 1)) == {
        "granted": False
    }
    assert any("已超时，按拒绝处理" in t for t in mgr.gateway.texts_to())


async def test_answering_in_the_app_tells_wechat_and_disarms_the_watchdog(tmp_path):
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)
    await mgr.mirror_inbox_item(item)
    assert item.id in mgr._wx_watchdogs

    assert await mgr.resolve_inbox(item.id, json.dumps({"granted": False})) is True

    assert item.id not in mgr._wx_watchdogs
    await asyncio.sleep(0)
    assert any("已在电脑端处理：拒绝" in t for t in mgr.gateway.texts_to())


# -- receipts: the resolutions that actually land aren't the card's own ----------
async def test_the_receipt_reads_as_chinese_when_the_app_approves_and_runs(tmp_path):
    """The app's "Approve and run" sends mode="bypass-approvals"; the card offered
    "interactive". Scoring the receipt by comparing resolution STRINGS would have sent the
    user "已在电脑端处理：{"approved": true, "mode": "bypass-approvals"}"."""
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_plan(SESSION, "Approve the plan?", body="1. ship it")
    await mgr.mirror_inbox_item(item)

    assert (
        await mgr.resolve_inbox(
            item.id, json.dumps({"approved": True, "mode": "bypass-approvals"})
        )
        is True
    )

    await asyncio.sleep(0)
    assert any("已在电脑端处理：同意" in t for t in mgr.gateway.texts_to())
    assert not any("approved" in t for t in mgr.gateway.texts_to())


async def test_the_receipt_reads_as_chinese_for_a_folder_the_user_typed(tmp_path):
    """A typed path resolves to a folder nobody offered, so its grant JSON matches no choice."""
    mgr = _tracked(tmp_path)
    folder = tmp_path / "logs"
    folder.mkdir()
    item = _directory_item(mgr, path="/srv/data")
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event(str(folder))) is True

    await asyncio.sleep(0)
    assert any("已收到：同意" in t for t in mgr.gateway.texts_to())
    assert not any("granted" in t for t in mgr.gateway.texts_to())


async def test_an_ask_user_receipt_quotes_the_chosen_option(tmp_path):
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_question(
        SESSION, "Which environment?", options=["staging", "prod"]
    )
    await mgr.mirror_inbox_item(item)

    assert mgr._resolve_inbox_reply(_event("2")) is True

    assert mgr.inbox.get(item.id).resolution == "prod"
    await asyncio.sleep(0)
    assert any("已收到：prod" in t for t in mgr.gateway.texts_to())


async def test_deleting_the_session_disarms_its_watchdogs(tmp_path):
    """`delete_session` closes the session's items in bulk (`InboxStore.resolve_session`) —
    the one resolution path that never runs through `resolve_inbox`, so it has to disarm the
    expiry tasks itself or they idle for the rest of the TTL holding a dead item."""
    mgr = _tracked(tmp_path)
    item = _directory_item(mgr)
    await mgr.mirror_inbox_item(item)
    assert item.id in mgr._wx_watchdogs

    mgr.delete_session(SESSION)

    assert item.id not in mgr._wx_watchdogs
    assert mgr.inbox.get(item.id).state != "pending"


async def test_a_wechat_answer_pushes_prompt_resolved_to_the_open_session(tmp_path):
    mgr = _tracked(tmp_path)
    item = mgr.inbox.add_approval(SESSION, "Run `write_file`?")
    await mgr.mirror_inbox_item(item)
    seen: list[dict] = []

    async def client(message: dict) -> None:
        seen.append(message)

    mgr.register_session_client(SESSION, client)
    assert mgr._resolve_inbox_reply(_event("1")) is True
    await asyncio.sleep(0)

    assert seen == [
        {
            "type": "prompt_resolved",
            "data": {"kind": "approval", "via": "weixin", "resolution": "allow"},
        }
    ]


# -- visibility: the two mirrors have different rules ---------------------------
async def test_an_attended_prompt_still_reaches_wechat_but_not_a_bound_channel(tmp_path):
    """The inline card renders on the computer the person is away from. The bound-channel
    mirror keeps its unattended-only rule; the WeChat one does not."""
    from coworker.inbox import VIS_INLINE

    mgr = _tracked(tmp_path)
    mgr.inbox_routing.set_binding("default", channel="slack", target="T1:C1")
    item = mgr.inbox.add_approval(SESSION, "Run `write_file`?", visibility=VIS_INLINE)

    await mgr.mirror_inbox_item(item)

    assert len(mgr.gateway.texts_to()) == 1  # WeChat got it...
    assert all(tgt == PEER for tgt, _ in mgr.gateway.sent)  # ...and only WeChat


# -- the decision that stays put ------------------------------------------------
def test_wechat_dm_sessions_keep_bypass_approvals(tmp_path):
    """Owner's call (2026-08-31, reaffirmed with this feature): the DM session a WeChat
    contact opens still runs in bypass — the allow-list is what gates who reaches it."""
    mgr = _manager(tmp_path)
    src = SessionSource(
        platform="weixin", chat_id="wxid_peer", user_id="wxid_peer", chat_type="dm"
    )
    sid = mgr._ensure_dm_session(src)
    assert sid is not None
    assert mgr._engines[sid].permissions.mode is Mode.BYPASS_APPROVALS
