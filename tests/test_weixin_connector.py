"""Offline tests for the Weixin connector — adapter poll loop, stateless sender, and
the QR login flow. The pure protocol/state layers have their own suite
(test_weixin_protocol.py); here the protocol api functions are monkeypatched and every
sleep is collapsed, so nothing touches the network or waits.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from coworker.connectors.weixin_adapter import WeixinAdapter
from coworker.connectors.weixin_state import WeixinState

ACCOUNT = "bot1@im.bot"
BASE_URL = "https://api.example"


def _profile() -> dict:
    return {"bot_token": "tok", "account_id": ACCOUNT, "base_url": BASE_URL}


def _make_adapter(tmp_path, **kw) -> tuple[WeixinAdapter, WeixinState]:
    state = WeixinState(tmp_path / "wx-state")
    return WeixinAdapter(_profile(), state=state, **kw), state


def _scripted_api_post(responses: list):
    """Fake getupdates: serve scripted batches in order, then park forever (a parked
    call is cancelled by disconnect, like a real long poll)."""
    calls: list[dict] = []

    async def api_post(client, *, base_url, endpoint, payload, token, timeout_s):
        calls.append(
            {"base_url": base_url, "endpoint": endpoint, "payload": dict(payload)}
        )
        if responses:
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        await asyncio.Event().wait()

    return api_post, calls


def _text_msg(msg_id: str, sender: str, text: str, **extra) -> dict:
    return {
        "from_user_id": sender,
        "message_id": msg_id,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
        **extra,
    }


# -- adapter poll loop ---------------------------------------------------------
async def test_adapter_poll_dispatches_and_persists_cursor(tmp_path, monkeypatch):
    adapter, state = _make_adapter(tmp_path, batch_delay=0.02, batch_split_delay=0.02)
    api_post, calls = _scripted_api_post(
        [
            {
                "ret": 0,
                "get_updates_buf": "buf-1",
                "msgs": [_text_msg("m1", "wxid_alice", "hello", context_token="ctx-1")],
            }
        ]
    )
    monkeypatch.setattr("coworker.connectors.weixin_adapter.api_post", api_post)
    got: list = []
    done = asyncio.Event()

    async def handler(event):
        got.append(event)
        done.set()

    adapter.set_message_handler(handler)
    assert await adapter.connect() is True
    try:
        await asyncio.wait_for(done.wait(), timeout=2)
    finally:
        await adapter.disconnect()
    (event,) = got
    assert event.text == "hello"
    assert event.source.platform == "weixin"
    assert event.source.chat_id == "wxid_alice" and event.source.chat_type == "dm"
    assert event.source.user_id == "wxid_alice"
    assert event.message_id == "m1"
    # first poll starts from the empty cursor; the returned cursor is persisted
    assert calls[0]["payload"] == {"get_updates_buf": ""}
    assert state.load_sync(ACCOUNT) == "buf-1"
    # inbound context token stored for the sender to echo
    assert state.context_token(ACCOUNT, "wxid_alice") == "ctx-1"


async def test_adapter_debounce_merges_rapid_texts(tmp_path, monkeypatch):
    adapter, _state = _make_adapter(tmp_path, batch_delay=0.05, batch_split_delay=0.05)
    api_post, _calls = _scripted_api_post(
        [
            {
                "ret": 0,
                "get_updates_buf": "b",
                "msgs": [
                    _text_msg("m1", "wxid_alice", "one"),
                    _text_msg("m2", "wxid_alice", "two"),
                ],
            }
        ]
    )
    monkeypatch.setattr("coworker.connectors.weixin_adapter.api_post", api_post)
    got: list = []
    done = asyncio.Event()

    async def handler(event):
        got.append(event)
        done.set()

    adapter.set_message_handler(handler)
    assert await adapter.connect()
    try:
        await asyncio.wait_for(done.wait(), timeout=2)
        await asyncio.sleep(0.1)  # no second flush must arrive
    finally:
        await adapter.disconnect()
    assert [e.text for e in got] == ["one\ntwo"]


async def test_debounce_fragment_during_dispatch_never_cancels_delivery(tmp_path):
    """A fragment arriving while the previous flush is mid-dispatch must not cancel
    that dispatch — cancelling there loses the aggregated text and aborts the
    downstream handler chain half-committed (review finding). Both messages must
    reach the handler."""
    from coworker.connectors.base import MessageEvent, SessionSource

    adapter, _state = _make_adapter(tmp_path, batch_delay=0.01, batch_split_delay=0.01)
    got: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(event):
        entered.set()
        await release.wait()  # simulate a long agent dispatch
        got.append(event.text)

    adapter.set_message_handler(slow_handler)
    src = SessionSource(platform="weixin", chat_id="wxid_a", user_id="wxid_a")
    try:
        adapter._enqueue_text_event(MessageEvent(text="A", source=src))
        await asyncio.wait_for(entered.wait(), timeout=2)  # flush A is mid-dispatch
        # Before the fix this cancelled A's flush task mid-handler.
        adapter._enqueue_text_event(MessageEvent(text="B", source=src))
        await asyncio.sleep(0.05)  # B's own flush fires and also blocks on release
        release.set()
        for _ in range(100):
            if len(got) == 2:
                break
            await asyncio.sleep(0.01)
    finally:
        await adapter.disconnect()
    assert sorted(got) == ["A", "B"]


async def test_adapter_dedup_and_self_drop(tmp_path, monkeypatch):
    adapter, _state = _make_adapter(tmp_path, batch_delay=0.02, batch_split_delay=0.02)
    api_post, _calls = _scripted_api_post(
        [
            {
                "ret": 0,
                "get_updates_buf": "b",
                "msgs": [
                    _text_msg("m1", "wxid_alice", "hi"),
                    _text_msg("m1", "wxid_alice", "hi"),  # duplicate message_id
                    _text_msg("m2", "wxid_alice", "hi"),  # content fingerprint dup
                    _text_msg("m3", ACCOUNT, "self echo"),  # from the bot itself
                ],
            }
        ]
    )
    monkeypatch.setattr("coworker.connectors.weixin_adapter.api_post", api_post)
    got: list = []
    done = asyncio.Event()

    async def handler(event):
        got.append(event)
        done.set()

    adapter.set_message_handler(handler)
    assert await adapter.connect()
    try:
        await asyncio.wait_for(done.wait(), timeout=2)
        await asyncio.sleep(0.1)
    finally:
        await adapter.disconnect()
    assert [e.text for e in got] == ["hi"]


async def test_adapter_session_expired_pauses_600(tmp_path, monkeypatch):
    adapter, _state = _make_adapter(tmp_path)
    api_post, calls = _scripted_api_post([{"ret": -14, "errmsg": "session expired"}])
    monkeypatch.setattr("coworker.connectors.weixin_adapter.api_post", api_post)
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert await adapter.connect()
    try:
        for _ in range(200):
            if 600.0 in sleeps and len(calls) >= 2:
                break
            await real_sleep(0.01)
    finally:
        await adapter.disconnect()
    assert 600.0 in sleeps  # paused instead of hammering
    assert len(calls) >= 2  # ...and resumed polling afterwards


async def test_adapter_connect_requires_credentials(tmp_path):
    adapter = WeixinAdapter(
        {"bot_token": "", "account_id": ""}, state=WeixinState(tmp_path / "wx")
    )
    assert await adapter.connect() is False
    await adapter.disconnect()  # idempotent even when never connected


# -- manager QR session --------------------------------------------------------
async def test_manager_qr_start_commits_and_greets(tmp_path, monkeypatch):
    """A confirmed QR login writes the profile, flips status, and greets the scanner
    so the new bot chat is labeled OpenWorker in WeChat from its first message
    (distinguishes it from look-alike bot chats minted by other agent stacks)."""
    import threading

    from coworker.connectors.base import SendResult
    from coworker.providers import ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class NoTurns(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            raise AssertionError("no turns expected")

        def capabilities(self, model):
            return ModelCapabilities()

    mgr = SessionManager(workspace=tmp_path, provider=NoTurns())
    creds = {
        "account_id": "newbot@im.bot",
        "token": "tok-x",
        "base_url": "https://api.example",
        "user_id": "wxid_scanner",
    }

    async def fake_flow(*, on_state, **kw):
        return creds

    monkeypatch.setattr("coworker.connectors.weixin_login.qr_login_flow", fake_flow)

    async def fake_refresh():
        pass

    monkeypatch.setattr(mgr, "refresh_gateway", fake_refresh)
    greeted: dict = {}
    done = threading.Event()

    def fake_send(token, chat_id, text, thread_id=None):
        greeted.update(token=token, chat_id=chat_id, text=text)
        done.set()
        return SendResult(True, message_id="m1")

    monkeypatch.setattr("coworker.connectors.senders._send_weixin", fake_send)

    out = await mgr.weixin_qr_start()
    assert out["ok"]
    await mgr._weixin_qr_task
    st = mgr.weixin_qr_status()
    assert st["state"] == "confirmed" and st["account"] == "newbot@im.bot"
    prof = mgr.secrets.get("weixin:default")
    assert prof["bot_token"] == "tok-x" and prof["account_id"] == "newbot@im.bot"
    # Scanning IS the answer to "who is connecting" -- the QR status returns the
    # scanner's own WeChat id, so they are allow-listed by the act of scanning.
    # Without this the owner's very first DM to their own bot parked, unanswered,
    # with nothing on screen explaining why.
    assert prof["allowed_users"] == ["wxid_scanner"]
    assert done.wait(timeout=2), "connect greeting was never attempted"
    assert greeted["chat_id"] == "wxid_scanner"
    assert "OpenWorker" in greeted["text"] and "newbot@im.bot" in greeted["text"]


@pytest.mark.asyncio
async def test_qr_rescan_keeps_existing_contacts_and_adds_the_scanner(monkeypatch, tmp_path):
    """Re-scanning after a session expiry must not cost the user their allow-list."""
    from coworker.connectors.base import SendResult
    from coworker.providers import ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class NoTurns(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            raise AssertionError("no turns expected")

        def capabilities(self, model):
            return ModelCapabilities()

    mgr = SessionManager(workspace=tmp_path, provider=NoTurns())
    mgr.secrets.put(
        "weixin:default",
        {"bot_token": "old", "account_id": "old@im.bot", "allowed_users": ["wxid_a"]},
    )

    async def fake_flow(*, on_state, **kw):
        return {
            "account_id": "new@im.bot",
            "token": "tok-y",
            "base_url": "https://api.example",
            "user_id": "wxid_scanner",
        }

    monkeypatch.setattr("coworker.connectors.weixin_login.qr_login_flow", fake_flow)

    async def fake_refresh():
        pass

    monkeypatch.setattr(mgr, "refresh_gateway", fake_refresh)
    monkeypatch.setattr(
        "coworker.connectors.senders._send_weixin",
        lambda *a, **k: SendResult(True, message_id="m"),
    )

    await mgr.weixin_qr_start()
    await mgr._weixin_qr_task
    allowed = mgr.secrets.get("weixin:default")["allowed_users"]
    assert allowed == ["wxid_a", "wxid_scanner"]  # kept, and the scanner appended


# -- stateless sender ----------------------------------------------------------
def _seed_runtime() -> WeixinState:
    # The sender reads the DEFAULT state root — isolated per test by the
    # autouse COWORKER_STATE_DIR fixture in conftest.py.
    state = WeixinState()
    state.save_runtime(ACCOUNT, BASE_URL)
    return state


def _patch_formatting(monkeypatch, chunks=None):
    import coworker.connectors.weixin_protocol as proto

    monkeypatch.setattr(proto, "format_outbound", lambda t: t)
    if chunks is not None:
        monkeypatch.setattr(
            proto, "split_for_delivery", lambda t, max_length=2000: list(chunks)
        )
    # A recording payload builder keeps the assertions on the SENDER's behavior,
    # not on build_send_payload's exact envelope (protocol suite covers that).
    monkeypatch.setattr(
        proto,
        "build_send_payload",
        lambda to, text, context_token, client_id: {
            "to": to,
            "text": text,
            "context_token": context_token,
            "client_id": client_id,
        },
    )


def test_sender_not_connected(monkeypatch):
    from coworker.connectors.senders import _send_weixin

    _patch_formatting(monkeypatch, chunks=["x"])
    res = _send_weixin("tok", "wxid_bob", "x")
    assert not res.ok and "not connected" in (res.error or "")


def test_sender_empty_message(monkeypatch):
    from coworker.connectors.senders import _send_weixin

    _seed_runtime()
    _patch_formatting(monkeypatch, chunks=[])
    res = _send_weixin("tok", "wxid_bob", "")
    assert not res.ok and res.error == "empty message"


def test_sender_chunking_order_and_delay(monkeypatch):
    import coworker.connectors.weixin_protocol as proto

    from coworker.connectors.senders import _send_weixin

    _seed_runtime()
    _patch_formatting(monkeypatch, chunks=["part one", "part two"])
    sent: list[dict] = []

    def fake_post(client, *, base_url, endpoint, payload, token, timeout_s):
        sent.append({"endpoint": endpoint, "payload": payload, "token": token})
        return {"ret": 0, "message_id": f"srv-{len(sent)}"}

    monkeypatch.setattr(proto, "api_post_sync", fake_post)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    res = _send_weixin("tok", "wxid_bob", "part one\n\npart two")
    assert res.ok and res.message_id == "srv-2"
    assert [s["payload"]["text"] for s in sent] == ["part one", "part two"]
    assert all(s["payload"]["to"] == "wxid_bob" and s["token"] == "tok" for s in sent)
    # distinct client ids per chunk; 1.5 s between chunks, none after the last
    assert sent[0]["payload"]["client_id"] != sent[1]["payload"]["client_id"]
    assert slept == [1.5]


def test_sender_session_expired_drops_token_and_retries_once(monkeypatch):
    import coworker.connectors.weixin_protocol as proto

    from coworker.connectors.senders import _send_weixin

    state = _seed_runtime()
    state.set_context_token(ACCOUNT, "wxid_bob", "ctx-9")
    _patch_formatting(monkeypatch, chunks=["hello"])
    sent: list[dict] = []
    responses = [{"ret": -14, "errmsg": "session expired"}, {"ret": 0}]

    def fake_post(client, *, base_url, endpoint, payload, token, timeout_s):
        sent.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(proto, "api_post_sync", fake_post)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    res = _send_weixin("tok", "wxid_bob", "hello")
    assert res.ok
    # first try echoed the cached token; the retry went tokenless with the SAME
    # client_id (server-side dedup key for a send that may have landed)
    assert [p["context_token"] for p in sent] == ["ctx-9", None]
    assert sent[0]["client_id"] == sent[1]["client_id"]
    assert slept == []  # a stale-session retry is immediate, not a rate-limit wait
    # the stored token is gone (fresh state instance re-reads from disk)
    assert WeixinState().context_token(ACCOUNT, "wxid_bob") is None


def test_sender_stale_disguise_minus2_unknown_error(monkeypatch):
    import coworker.connectors.weixin_protocol as proto

    from coworker.connectors.senders import _send_weixin

    state = _seed_runtime()
    state.set_context_token(ACCOUNT, "wxid_bob", "ctx-9")
    _patch_formatting(monkeypatch, chunks=["hello"])
    responses = [{"ret": -2, "errmsg": "unknown error"}, {"ret": 0}]
    sent: list[dict] = []

    def fake_post(client, *, base_url, endpoint, payload, token, timeout_s):
        sent.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(proto, "api_post_sync", fake_post)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    res = _send_weixin("tok", "wxid_bob", "hello")
    assert res.ok
    assert [p["context_token"] for p in sent] == ["ctx-9", None]
    assert slept == []  # treated as stale session, NOT as a rate limit


def test_sender_rate_limit_backoff_then_error(monkeypatch):
    import coworker.connectors.weixin_protocol as proto

    from coworker.connectors.senders import _send_weixin

    _seed_runtime()
    _patch_formatting(monkeypatch, chunks=["hello"])

    def fake_post(client, *, base_url, endpoint, payload, token, timeout_s):
        return {"ret": -2, "errmsg": "freq limit"}

    monkeypatch.setattr(proto, "api_post_sync", fake_post)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    res = _send_weixin("tok", "wxid_bob", "hello")
    assert not res.ok and "rate limited" in (res.error or "")
    assert slept == [3.0, 3.0, 3.0]  # 4 attempts total, 3 backoffs


def test_sender_error_mapping(monkeypatch):
    import coworker.connectors.weixin_protocol as proto

    from coworker.connectors.senders import _send_weixin

    _seed_runtime()
    _patch_formatting(monkeypatch, chunks=["hello"])
    monkeypatch.setattr(
        proto,
        "api_post_sync",
        lambda client, **kw: {"ret": 5, "errcode": 0, "errmsg": "boom"},
    )
    res = _send_weixin("tok", "wxid_bob", "hello")
    assert not res.ok
    assert "iLink sendmessage error" in (res.error or "") and "boom" in res.error


# -- QR login flow -------------------------------------------------------------
async def test_qr_login_flow_success_state_sequence(monkeypatch):
    import coworker.connectors.weixin_login as login

    statuses = [
        {"status": "wait"},
        {"status": "scaned"},
        {
            "status": "confirmed",
            "ilink_bot_id": "bot9@im.bot",
            "bot_token": "tk-1",
            "baseurl": "https://acct.example",
            "ilink_user_id": "u-1",
        },
    ]

    async def fake_get(client, *, base_url, endpoint, timeout_s):
        if endpoint.startswith(login.EP_GET_BOT_QR):
            return {"qrcode": "abc123", "qrcode_img_content": "https://liteapp/x"}
        assert endpoint == f"{login.EP_GET_QR_STATUS}?qrcode=abc123"
        return statuses.pop(0)

    monkeypatch.setattr(login, "api_get", fake_get)
    monkeypatch.setattr(login, "_qr_data_uri", lambda url: "data:image/png;base64,QQ==")
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda d: real_sleep(0))

    seen: list[str] = []
    creds = await login.qr_login_flow(on_state=lambda st: seen.append(st.state))
    assert creds == {
        "account_id": "bot9@im.bot",
        "token": "tk-1",
        "base_url": "https://acct.example",
        "user_id": "u-1",
    }
    # "confirmed" is emitted by the CALLER after persisting, never by the flow
    assert seen == ["starting", "waiting_scan", "scanned"]


async def test_qr_login_flow_expired_four_times_fails(monkeypatch):
    import coworker.connectors.weixin_login as login

    qr_fetches: list[str] = []
    statuses = [{"status": "expired"}] * 4

    async def fake_get(client, *, base_url, endpoint, timeout_s):
        if endpoint.startswith(login.EP_GET_BOT_QR):
            qr_fetches.append(base_url)
            return {
                "qrcode": f"qr-{len(qr_fetches)}",
                "qrcode_img_content": "https://liteapp/x",
            }
        return statuses.pop(0)

    monkeypatch.setattr(login, "api_get", fake_get)
    monkeypatch.setattr(login, "_qr_data_uri", lambda url: "data:image/png;base64,QQ==")
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda d: real_sleep(0))

    seen: list[str] = []
    holder: dict = {}

    def on_state(st):
        seen.append(st.state)
        holder["st"] = st

    creds = await login.qr_login_flow(on_state=on_state)
    assert creds is None
    st = holder["st"]
    assert st.state == "failed" and st.refreshes == 3
    # initial fetch + 3 refreshes, all from the DEFAULT host
    assert len(qr_fetches) == 4
    assert all(b == login.ILINK_BASE_URL for b in qr_fetches)
    assert seen.count("waiting_scan") == 4 and seen[-1] == "failed"
