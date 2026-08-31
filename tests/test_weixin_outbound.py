"""Outbound WeChat: attachments through the encrypted CDN, and the typing indicator.

Both talk to private Tencent endpoints we cannot reach from CI, so these pin the parts
that are ours: the request shapes, the crypto, the caching, and — most importantly —
that every failure here is survivable. A missing typing bubble is cosmetic; it must
never cost the user their reply.
"""

from __future__ import annotations

import asyncio

import pytest

from coworker.connectors import weixin_protocol as wp
from coworker.connectors.weixin_adapter import WeixinAdapter
from coworker.connectors.weixin_state import WeixinState

ACCOUNT = "bot@im.bot"
BASE_URL = "https://ilink.test"
PEER = "wxid_peer"


# -- crypto -------------------------------------------------------------------
def test_aes_encrypt_round_trips_through_our_own_decrypt():
    key = wp.new_aes_key()
    assert len(key) == 16
    for payload in (b"", b"hello", b"x" * 16, b"y" * 4096):
        cipher = wp.aes128_ecb_encrypt(payload, key)
        assert len(cipher) % 16 == 0
        # PKCS7 always pads, so a block-aligned input grows by a whole block.
        assert len(cipher) == (len(payload) // 16 + 1) * 16
        assert wp.aes128_ecb_decrypt(cipher, key) == payload


def test_new_aes_key_is_not_reused():
    assert wp.new_aes_key() != wp.new_aes_key()


# -- media items --------------------------------------------------------------
def test_media_type_is_picked_from_the_extension():
    assert wp.media_type_for("jpg") == wp.ITEM_IMAGE
    assert wp.media_type_for(".PNG") == wp.ITEM_IMAGE
    assert wp.media_type_for("mp4") == wp.ITEM_VIDEO
    assert wp.media_type_for("pdf") == wp.ITEM_FILE
    assert wp.media_type_for("") == wp.ITEM_FILE


def test_media_item_carries_the_key_as_hex_our_reader_understands():
    key = bytes(range(16))
    item = wp.build_media_item(wp.ITEM_IMAGE, "https://cdn/x", key, 99)
    assert item["type"] == wp.ITEM_IMAGE
    assert item["image_item"]["filesize"] == 99
    # Round-trip through the INBOUND parser: what we send, we can read back.
    assert wp.image_aes_key({"image_item": item["image_item"]}) == key

    doc = wp.build_media_item(wp.ITEM_FILE, "https://cdn/d", key, 5, filename="a.pdf")
    assert doc["file_item"]["filename"] == "a.pdf"
    # Images carry no filename — WeChat shows a photo, not a file card.
    assert "filename" not in item["image_item"]


def test_item_send_payload_matches_the_text_one_but_for_the_item():
    key = wp.new_aes_key()
    item = wp.build_media_item(wp.ITEM_IMAGE, "https://cdn/x", key, 1)
    payload = wp.build_item_send_payload("wxid_p", item, "CTX", "cid-1")["msg"]
    assert payload["to_user_id"] == "wxid_p"
    assert payload["client_id"] == "cid-1"
    assert payload["context_token"] == "CTX"
    assert payload["item_list"] == [item]
    # Tokenless degraded sends omit it entirely, same as text.
    assert "context_token" not in wp.build_item_send_payload(
        "wxid_p", item, None, "cid-2"
    )["msg"]


# -- typing indicator ---------------------------------------------------------
def _adapter(tmp_path) -> WeixinAdapter:
    profile = {"bot_token": "tok", "account_id": ACCOUNT, "base_url": BASE_URL}
    return WeixinAdapter(profile, state=WeixinState(tmp_path / "wx"))


def test_typing_payload_shape():
    payload = wp.build_typing_payload(PEER, "TICKET", wp.TYPING_START)
    # `ilink_user_id`, verified live: `user_id` returns
    # {"ret": -2, "errmsg": "ilink_user_id required"} and the indicator never shows.
    assert payload == {"ilink_user_id": PEER, "typing_ticket": "TICKET", "status": 1}
    assert wp.TYPING_STOP == 2


def test_typing_ticket_is_cached_per_peer(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path)
    adapter._client = object()  # only presence is checked before the call
    calls: list[dict] = []

    async def fake_post(client, *, base_url, endpoint, payload, token, timeout_s):
        calls.append({"endpoint": endpoint, "payload": payload})
        return {"ret": 0, "typing_ticket": f"T-{payload['ilink_user_id']}"}

    monkeypatch.setattr("coworker.connectors.weixin_adapter.api_post", fake_post)

    async def scenario():
        assert await adapter._typing_ticket(PEER) == f"T-{PEER}"
        assert await adapter._typing_ticket(PEER) == f"T-{PEER}"  # cached
        assert await adapter._typing_ticket("other") == "T-other"

    asyncio.run(scenario())
    assert [c["endpoint"] for c in calls] == [wp.EP_GET_CONFIG, wp.EP_GET_CONFIG]
    assert [c["payload"]["ilink_user_id"] for c in calls] == [PEER, "other"]


def test_a_refused_ticket_is_dropped_so_the_next_turn_re_mints(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path)
    adapter._client = object()
    monkeypatch.setattr(
        "coworker.connectors.weixin_adapter.api_post",
        _post_router({wp.EP_GET_CONFIG: {"typing_ticket": "T"}}, fail_on=wp.EP_SEND_TYPING),
    )
    asyncio.run(adapter._send_typing(PEER, wp.TYPING_START))
    assert PEER not in adapter._typing_tickets


def _post_router(responses: dict, fail_on: str | None = None):
    async def fake_post(client, *, base_url, endpoint, payload, token, timeout_s):
        if endpoint == fail_on:
            raise RuntimeError("iLink says no")
        return responses.get(endpoint, {})

    return fake_post


def test_typing_failure_never_blocks_the_message(tmp_path, monkeypatch):
    """The whole point: a bot that cannot show "typing" must still answer."""
    adapter = _adapter(tmp_path)
    adapter._client = object()
    monkeypatch.setattr(
        "coworker.connectors.weixin_adapter.api_post",
        _post_router({}, fail_on=wp.EP_GET_CONFIG),  # cannot even mint a ticket
    )
    handled: list[str] = []

    async def handler(event):
        handled.append(event.text)

    adapter.handle_message = handler

    from coworker.connectors.base import MessageEvent, SessionSource

    event = MessageEvent(
        text="ping",
        source=SessionSource(platform="weixin", chat_id=PEER, user_id=PEER, chat_type="dm"),
    )
    asyncio.run(adapter._dispatch(event))
    assert handled == ["ping"]  # delivered anyway


def test_typing_is_held_for_the_turn_then_stopped(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path)
    adapter._client = object()
    seen: list[int] = []

    async def fake_post(client, *, base_url, endpoint, payload, token, timeout_s):
        if endpoint == wp.EP_GET_CONFIG:
            return {"ret": 0, "typing_ticket": "T"}
        seen.append(payload["status"])
        return {"ret": 0}

    monkeypatch.setattr("coworker.connectors.weixin_adapter.api_post", fake_post)

    async def handler(event):
        await asyncio.sleep(0)  # let the keepalive task get its first send in

    adapter.handle_message = handler

    from coworker.connectors.base import MessageEvent, SessionSource

    event = MessageEvent(
        text="ping",
        source=SessionSource(platform="weixin", chat_id=PEER, user_id=PEER, chat_type="dm"),
    )
    asyncio.run(adapter._dispatch(event))
    assert seen[0] == wp.TYPING_START
    # Cleared explicitly rather than waiting for the client's own timeout, so the
    # bubble is gone by the time the answer lands.
    assert seen[-1] == wp.TYPING_STOP


# -- attachment send ----------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.is_success = 200 <= status < 300
        self.text = "{}"

    def json(self):
        return self._payload


def _install_fake_httpx(monkeypatch, *, upload_status=200, on_send=None, recorder=None):
    """Stand in for the CDN + iLink so the whole upload flow can run offline."""
    import httpx

    calls = recorder if recorder is not None else []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None, timeout=None, **kw):
            calls.append({"url": url, "content": content, "headers": headers or {}})
            return _FakeResponse({"cdn_url": "https://cdn.weixin/final"}, upload_status)

    monkeypatch.setattr(httpx, "Client", FakeClient)

    def fake_api_post_sync(client, *, base_url, endpoint, payload, token, timeout_s):
        calls.append({"endpoint": endpoint, "payload": payload})
        if endpoint == wp.EP_GET_UPLOAD_URL:
            return {
                "upload_url": "https://cdn.weixin/upload?slot=1",
                "upload_ticket": "TICKET",
            }
        return on_send({}) if on_send else {"ret": 0, "message_id": "m-1"}

    monkeypatch.setattr(
        "coworker.connectors.weixin_protocol.api_post_sync", fake_api_post_sync
    )
    return calls


@pytest.fixture()
def connected(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    WeixinState().save_runtime(ACCOUNT, BASE_URL)


def test_attachment_is_encrypted_then_uploaded_then_referenced(connected, monkeypatch):
    from coworker.connectors.senders import _send_weixin_file

    calls = _install_fake_httpx(monkeypatch)
    data = b"%PDF-1.4 hello"
    result = _send_weixin_file("tok", PEER, None, "report.pdf", data)
    assert result.ok, result.error

    reserve = next(c for c in calls if c.get("endpoint") == wp.EP_GET_UPLOAD_URL)
    assert reserve["payload"] == {"media_type": wp.ITEM_FILE}

    upload = next(c for c in calls if "url" in c)
    assert upload["headers"]["Upload-Ticket"] == "TICKET"
    assert upload["headers"]["Content-Type"] == "application/octet-stream"
    assert upload["content"] != data  # the CDN only ever sees ciphertext
    assert len(upload["content"]) % 16 == 0

    send = next(c for c in calls if c.get("endpoint") == wp.EP_SEND_MESSAGE)
    item = send["payload"]["msg"]["item_list"][0]
    assert item["type"] == wp.ITEM_FILE
    assert item["file_item"]["filename"] == "report.pdf"
    assert item["file_item"]["url"] == "https://cdn.weixin/final"
    # PLAINTEXT size: the receiver unpads after decrypting.
    assert item["file_item"]["filesize"] == len(data)
    # ...and the key it carries really opens the bytes we uploaded.
    key = bytes.fromhex(item["file_item"]["aeskey"])
    assert wp.aes128_ecb_decrypt(upload["content"], key) == data


def test_an_image_is_sent_as_a_photo_not_a_file_card(connected, monkeypatch):
    from coworker.connectors.senders import _send_weixin_file

    calls = _install_fake_httpx(monkeypatch)
    assert _send_weixin_file("tok", PEER, None, "chart.png", b"\x89PNG data").ok
    send = next(c for c in calls if c.get("endpoint") == wp.EP_SEND_MESSAGE)
    assert send["payload"]["msg"]["item_list"][0]["type"] == wp.ITEM_IMAGE


def test_send_failures_are_reported_not_swallowed(connected, monkeypatch):
    from coworker.connectors.senders import _send_weixin_file

    _install_fake_httpx(monkeypatch, upload_status=500)
    failed = _send_weixin_file("tok", PEER, None, "a.pdf", b"data")
    assert not failed.ok and "500" in failed.error

    _install_fake_httpx(
        monkeypatch, on_send=lambda _: {"ret": -14, "errmsg": "session expired"}
    )
    rejected = _send_weixin_file("tok", PEER, None, "a.pdf", b"data")
    assert not rejected.ok and "session expired" in rejected.error


def test_not_connected_and_empty_file_fail_cleanly(tmp_path, monkeypatch):
    from coworker.connectors.senders import _send_weixin_file

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "empty"))
    assert "not connected" in _send_weixin_file("t", PEER, None, "a.pdf", b"x").error


def test_weixin_is_registered_as_a_file_sender():
    from coworker.connectors.senders import DEFAULT_FILE_SENDERS

    # Before this, send_file answered "file sending is not supported on weixin yet".
    assert "weixin" in DEFAULT_FILE_SENDERS
