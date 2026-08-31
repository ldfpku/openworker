"""Tests for the weixin (iLink Bot API) protocol + state layers: pure request
builders/parsers, media crypto helpers, outbound formatting/chunking, and the
on-disk WeixinState — all offline (httpx.MockTransport for the API plumbing);
`cryptography` is optional via importorskip.
"""

from __future__ import annotations

import base64
import json
import sys
import time

import httpx
import pytest

from coworker.connectors import weixin_protocol as wp
from coworker.connectors.weixin_state import WeixinState


# -- headers & serialization ---------------------------------------------------
def test_ilink_headers_shape():
    h = wp.ilink_headers("TOK", "body")
    assert h["Content-Type"] == "application/json"
    assert h["AuthorizationType"] == "ilink_bot_token"
    assert h["iLink-App-Id"] == "bot"
    assert h["iLink-App-ClientVersion"] == "131584"  # 2.2.0 packed per byte
    assert h["Authorization"] == "Bearer TOK"
    # Content-Length counts UTF-8 bytes, not characters
    assert wp.ilink_headers(None, "你好")["Content-Length"] == "6"
    # no token -> no Authorization header at all
    assert "Authorization" not in wp.ilink_headers(None, "x")
    assert "Authorization" not in wp.ilink_headers("", "x")


def test_ilink_headers_uin_fresh_per_call():
    uin = wp.ilink_headers("T", "b")["X-WECHAT-UIN"]
    value = int(base64.b64decode(uin).decode("ascii"))
    assert 0 <= value < 2**32  # base64 of the decimal string of a uint32
    uins = {wp.ilink_headers("T", "b")["X-WECHAT-UIN"] for _ in range(8)}
    assert len(uins) > 1  # regenerated every request


def test_json_dumps_compact_non_ascii():
    assert wp.json_dumps({"a": 1, "b": "微信"}) == '{"a":1,"b":"微信"}'


# -- api plumbing (MockTransport, offline) -------------------------------------
def test_api_post_sync_envelope_and_error():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["headers"] = request.headers
        return httpx.Response(200, text='{"ret":0}')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        out = wp.api_post_sync(
            client,
            base_url="https://api.example/",  # trailing slash must not double up
            endpoint=wp.EP_SEND_MESSAGE,
            payload={"msg": {"x": 1}},
            token="TOK",
            timeout_s=5.0,
        )
    assert out == {"ret": 0}
    assert captured["url"] == "https://api.example/ilink/bot/sendmessage"
    assert captured["body"]["base_info"] == {"channel_version": "2.2.0"}
    assert captured["body"]["msg"] == {"x": 1}
    assert captured["headers"]["Authorization"] == "Bearer TOK"

    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    ) as client:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            wp.api_post_sync(
                client,
                base_url="https://api.example",
                endpoint=wp.EP_SEND_MESSAGE,
                payload={},
                token="TOK",
                timeout_s=5.0,
            )


async def test_api_get_minimal_headers_query_in_endpoint():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        return httpx.Response(200, text='{"status":"wait"}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await wp.api_get(
            client,
            base_url=wp.ILINK_BASE_URL,
            endpoint=f"{wp.EP_GET_QR_STATUS}?qrcode=abc",
            timeout_s=5.0,
        )
    assert out == {"status": "wait"}
    assert captured["url"] == (
        "https://ilinkai.weixin.qq.com/ilink/bot/get_qrcode_status?qrcode=abc"
    )
    # QR GETs carry only the two app headers — no Authorization, no body
    assert "Authorization" not in captured["headers"]
    assert captured["headers"]["iLink-App-Id"] == "bot"
    assert captured["headers"]["iLink-App-ClientVersion"] == "131584"


# -- response classification ---------------------------------------------------
def test_is_stale_session_asymmetry():
    assert wp.is_stale_session(-2, None, "unknown error") is True
    assert wp.is_stale_session(None, -2, " Unknown Error ") is True  # tolerant
    assert wp.is_stale_session(-2, None, "freq limit") is False  # genuine rate limit
    assert wp.is_stale_session(-2, None, None) is False
    # -14 is deliberately NOT matched here — callers handle it separately
    assert wp.is_stale_session(-14, -14, "unknown error") is False
    assert wp.is_stale_session(0, 0, "unknown error") is False


# -- inbound parsing -----------------------------------------------------------
def test_extract_text_plain():
    assert wp.extract_text([{"type": 1, "text_item": {"text": "hello"}}]) == "hello"
    assert wp.extract_text([]) == ""
    assert wp.extract_text([{"type": 2, "image_item": {}}]) == ""


def test_extract_text_quoted_text_ref():
    items = [
        {
            "type": 1,
            "text_item": {"text": "回复内容"},
            "ref_msg": {
                "title": "Alice",
                "message_item": {"type": 1, "text_item": {"text": "原始消息"}},
            },
        }
    ]
    assert wp.extract_text(items) == "[引用: Alice | 原始消息]\n回复内容"


def test_extract_text_quoted_media_ref():
    items = [
        {
            "type": 1,
            "text_item": {"text": "看这个"},
            "ref_msg": {"title": "photo.jpg", "message_item": {"type": 2}},
        }
    ]
    assert wp.extract_text(items) == "[引用媒体: photo.jpg]\n看这个"
    items[0]["ref_msg"]["title"] = ""
    assert wp.extract_text(items) == "[引用媒体]\n看这个"


def test_extract_text_voice_transcript_without_media():
    # Inverted from Hermes: with no raw audio (and no local STT in openworker)
    # we USE Tencent's transcript, marked so the agent knows it was spoken.
    items = [{"type": 3, "voice_item": {"text": "开会时间改到三点"}}]
    assert wp.extract_text(items) == "[语音转写] 开会时间改到三点"


def test_extract_text_voice_transcript_wins_over_audio():
    # Tencent's transcript is used WHENEVER it is supplied, audio attached or not.
    # It used to be dropped as soon as media was present, and since nothing here
    # decodes SILK the spoken words became unreachable -- the agent saw a file path
    # and nothing else.
    items = [
        {
            "type": 3,
            "voice_item": {"text": "开会时间改到三点", "media": {"aes_key": "k"}},
        }
    ]
    assert wp.extract_text(items) == "[语音转写] 开会时间改到三点"


def test_extract_text_voice_without_transcript_is_empty():
    # No transcript from Tencent -> empty body; the adapter still saves the .silk.
    items = [{"type": 3, "voice_item": {"media": {"aes_key": "k"}}}]
    assert wp.extract_text(items) == ""


def test_guess_chat_type():
    account = "bot@im.bot"
    dm = {"from_user_id": "wxid_peer", "to_user_id": account, "msg_type": 1}
    assert wp.guess_chat_type(dm, account) == ("dm", "wxid_peer")
    room = {"from_user_id": "wxid_peer", "room_id": "g1@chatroom", "msg_type": 1}
    assert wp.guess_chat_type(room, account) == ("group", "g1@chatroom")
    # roomless heuristic: addressed to a third party with msg_type == 1
    third = {"from_user_id": "wxid_peer", "to_user_id": "wxid_other", "msg_type": 1}
    assert wp.guess_chat_type(third, account) == ("group", "wxid_other")
    # but not for bot-typed messages
    bot_typed = {"from_user_id": "wxid_peer", "to_user_id": "wxid_other", "msg_type": 2}
    assert wp.guess_chat_type(bot_typed, account) == ("dm", "wxid_peer")


# -- outbound payload ----------------------------------------------------------
def test_build_send_payload_shape():
    payload = wp.build_send_payload("wxid_p", "hi", "CTX", "ow-weixin-abc")
    assert payload == {
        "msg": {
            "from_user_id": "",
            "to_user_id": "wxid_p",
            "client_id": "ow-weixin-abc",
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
            "context_token": "CTX",
        }
    }
    # context_token omitted entirely when absent (tokenless degraded sends)
    tokenless = wp.build_send_payload("wxid_p", "hi", None, "ow-weixin-abc")
    assert "context_token" not in tokenless["msg"]


# -- formatting & chunking -----------------------------------------------------
def test_format_outbound_collapses_blank_runs_and_wraps():
    assert wp.format_outbound("a\n\n\n\nb") == "a\n\nb"
    long_line = ("word " * 40).strip()  # ~200 chars of wrappable prose
    out = wp.format_outbound(long_line)
    assert all(len(line) <= 120 for line in out.splitlines())
    assert " ".join(out.split()) == long_line  # no words lost or broken


def test_format_outbound_skips_long_urls():
    url = "https://example.com/" + "p" * 150
    assert wp.format_outbound(url) == url  # break_long_words=False keeps it whole
    # A pipe line with no header rule is not a table -- ASCII art and prose survive.
    pipes = "| " + "a" * 130 + " |"
    assert wp.format_outbound(pipes) == pipes


def test_format_outbound_rewrites_headings():
    # WeChat renders neither '#' nor bold, but the brackets read as a heading and a
    # bare '##' reads as stray punctuation.
    assert wp.format_outbound("# 季度回顾") == "【季度回顾】"
    assert wp.format_outbound("## 关键数字") == "**关键数字**"
    assert wp.format_outbound("#### 细节") == "**细节**"
    assert wp.format_outbound("# Closed ###") == "【Closed】"  # closing hashes dropped
    assert wp.format_outbound("#nospace") == "#nospace"  # not a heading
    # '#' inside a fence is a comment in most languages -- never a heading.
    assert "【" not in wp.format_outbound("```python\n# a comment\n```")


NBSP = " "


def test_format_outbound_hardens_code_against_wechats_soft_wrap():
    """WeChat re-renders the message as Markdown and its subset ignores ``` fences, so
    code was soft-wrapped like prose: every newline became a space and the indentation
    vanished. Observed in the field 2026-08-31 -- a 119-line answer arrived as one
    run-on paragraph. Blank lines and NBSP are what survive that renderer."""
    code = (
        "```python\n"
        "class Priority(Enum):\n"
        '    LOW = "low"\n'
        "\n"
        "def add(self, title):\n"
        "    self.tasks.append(title)\n"
        "```"
    )
    out = wp.format_outbound(code)
    assert "```" not in out  # the markers only render as literal junk
    # Every code line still ends up on its own line, blank-line separated -- the only
    # break that survives (an empty line inside the code collapses away, cosmetic).
    lines = [ln for ln in out.split("\n\n") if ln.strip()]
    assert lines == [
        "class Priority(Enum):",
        NBSP * 4 + 'LOW = "low"',
        "def add(self, title):",
        NBSP * 4 + "self.tasks.append(title)",
    ]
    assert "    LOW" not in out  # plain leading spaces would be collapsed away


def test_format_outbound_leaves_prose_and_lists_alone():
    # Both already render correctly in WeChat: prose soft-wraps (fine) and '- item'
    # becomes a real bullet on its own line. Only fenced code needed hardening.
    assert wp.format_outbound("just a sentence") == "just a sentence"
    assert wp.format_outbound("- one\n- two") == "- one\n- two"


def test_format_outbound_flattens_tables_into_labelled_records():
    table = (
        "| 指标 | 本季 |\n"
        "| --- | --- |\n"
        "| 收入 | 1200 万 |\n"
        "| 毛利 | 430 万 |"
    )
    out = wp.format_outbound(table)
    assert "|" not in out  # a chat bubble has no table rendering and no h-scroll
    assert out == "- 指标: 收入\n- 本季: 1200 万\n\n- 指标: 毛利\n- 本季: 430 万"


def test_format_outbound_table_edge_cases():
    # Empty cells are dropped rather than emitting a label with nothing after it.
    out = wp.format_outbound("| a | b |\n| --- | --- |\n| 1 |  |")
    assert out == "- a: 1"
    # An escaped pipe belongs to its cell, not to the column split.
    out = wp.format_outbound("| k | v |\n| --- | --- |\n| or | a \\| b |")
    assert out == "- k: or\n- v: a | b"
    # A header with no body rows says nothing at all.
    assert wp.format_outbound("| a | b |\n| --- | --- |") == ""


def test_split_for_delivery_passthrough_and_empty():
    assert wp.split_for_delivery("") == []
    assert wp.split_for_delivery("short\n\nmessage") == ["short\n\nmessage"]


def test_split_for_delivery_blank_line_split_and_greedy_repack():
    blocks = [f"block {i} " + "x" * 700 for i in range(4)]
    chunks = wp.split_for_delivery("\n\n".join(blocks), max_length=1500)
    assert chunks == [
        blocks[0] + "\n\n" + blocks[1],
        blocks[2] + "\n\n" + blocks[3],
    ]
    assert all(len(c) <= 1500 for c in chunks)


def test_split_for_delivery_never_splits_fences():
    fence = "```python\n" + "\n".join(f"line {i}" for i in range(40)) + "\n```"
    text = "x" * 1900 + "\n\n" + fence
    chunks = wp.split_for_delivery(text, max_length=2000)
    assert chunks == ["x" * 1900, fence]
    assert chunks[1].startswith("```python") and chunks[1].endswith("```")


def test_split_for_delivery_oversized_block_is_split_not_truncated():
    # Blocks are only cut at blank lines and fences, so a table, a long list or one
    # long paragraph is a single block however long it runs. This used to be cut to
    # the limit and the tail silently dropped -- a 5000-char answer arrived as 2000.
    chunks = wp.split_for_delivery("y" * 5000, max_length=2000)
    assert "".join(chunks) == "y" * 5000  # nothing lost
    assert all(len(c) <= 2000 for c in chunks)


def test_split_for_delivery_oversized_block_breaks_at_line_ends():
    rows = [f"| row {i} | " + "v" * 60 + " |" for i in range(60)]
    body = "\n".join(rows)
    chunks = wp.split_for_delivery(body, max_length=800)
    assert "\n".join(chunks) == body  # every row survives, none torn mid-line
    assert all(len(c) <= 800 for c in chunks)
    assert all(c.startswith("| row ") for c in chunks)


def test_split_for_delivery_oversized_fence_closes_and_reopens():
    # Cutting a fenced block mid-body used to ship an unbalanced ``` -- the WeChat
    # client then reads everything after it as code.
    lines = [f"x{i} = compute({i})" for i in range(300)]
    fence = "```python\n" + "\n".join(lines) + "\n```"
    chunks = wp.split_for_delivery(fence, max_length=2000)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 2000
        assert chunk.startswith("```python")
        assert chunk.endswith("```")
        assert chunk.count("```") % 2 == 0  # balanced on its own
    body = [
        line
        for chunk in chunks
        for line in chunk.splitlines()
        if not line.startswith("```")
    ]
    assert body == lines  # every statement survives, in order


def test_split_for_delivery_keeps_indentation_across_seams():
    # Cutting at a newline must consume the newline and nothing else. Stripping the
    # remainder took the next line's indentation with it, so a split Python block came
    # out de-indented at every seam and would not run when copied out of WeChat.
    lines = []
    for i in range(120):
        lines.append(f"def f{i}(x):")
        lines.append(f"    return {i} + compute(x)")
    chunks = wp.split_for_delivery("```python\n" + "\n".join(lines) + "\n```", 2000)
    assert len(chunks) > 1
    body = [
        line
        for chunk in chunks
        for line in chunk.splitlines()
        if not line.startswith("```")
    ]
    assert body == lines  # byte-exact, indentation included


# -- media crypto & CDN --------------------------------------------------------
def test_parse_aes_key_encodings():
    raw = bytes(range(16))
    assert wp.parse_aes_key(base64.b64encode(raw).decode()) == raw
    # base64 of the 32-char ASCII-hex string of the key
    assert wp.parse_aes_key(base64.b64encode(raw.hex().encode()).decode()) == raw
    with pytest.raises(ValueError):
        wp.parse_aes_key(base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):  # 32 decoded bytes that are not hex
        wp.parse_aes_key(base64.b64encode(b"@" * 32).decode())


def test_aes128_ecb_decrypt_round_trip():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = bytes(range(16))
    plaintext = "机密 payload".encode("utf-8")
    pad_len = 16 - len(plaintext) % 16
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ciphertext = (
        encryptor.update(plaintext + bytes([pad_len]) * pad_len) + encryptor.finalize()
    )
    assert wp.aes128_ecb_decrypt(ciphertext, key) == plaintext

    # tolerant unpad: a tail that is not valid PKCS7 comes back untouched
    block = b"0123456789abcdeX"  # last byte 0x58 is not a pad length
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ct = encryptor.update(block) + encryptor.finalize()
    assert wp.aes128_ecb_decrypt(ct, key) == block


def test_aes_decrypt_without_cryptography_raises_runtime_error(monkeypatch):
    for name in [
        n for n in sys.modules if n == "cryptography" or n.startswith("cryptography.")
    ]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "cryptography", None)  # lazy import now fails
    with pytest.raises(RuntimeError, match="cryptography is required"):
        wp.aes128_ecb_decrypt(b"\x00" * 16, bytes(16))


def test_media_reference():
    item = {"file_item": {"media": {"aes_key": "k", "full_url": "u"}}}
    assert wp.media_reference(item, "file_item") == {"aes_key": "k", "full_url": "u"}
    assert wp.media_reference({}, "file_item") == {}
    assert wp.media_reference({"file_item": {}}, "file_item") == {}


def test_image_aes_key_prefers_hex_sibling():
    raw = bytes(range(16))
    other = base64.b64encode(b"\x01" * 16).decode()
    item = {"image_item": {"aeskey": raw.hex(), "media": {"aes_key": other}}}
    assert wp.image_aes_key(item) == raw  # hex sibling wins over media.aes_key
    item = {"image_item": {"media": {"aes_key": base64.b64encode(raw).decode()}}}
    assert wp.image_aes_key(item) == raw
    assert wp.image_aes_key({"image_item": {}}) is None
    assert wp.image_aes_key({}) is None


def test_cdn_download_url_quotes_param():
    url = wp.cdn_download_url("https://cdn.example/c2c/", "a/b+c=")
    assert url == "https://cdn.example/c2c/download?encrypted_query_param=a%2Fb%2Bc%3D"


def test_assert_weixin_cdn_url_allowlist():
    wp.assert_weixin_cdn_url("https://novac2c.cdn.weixin.qq.com/c2c/x")  # no raise
    wp.assert_weixin_cdn_url("http://mmbiz.qpic.cn/pic")  # no raise
    for bad in (
        "https://evil.example/x",
        "ftp://novac2c.cdn.weixin.qq.com/x",
        "https://novac2c.cdn.weixin.qq.com.evil.example/x",  # suffix spoof
    ):
        with pytest.raises(ValueError):
            wp.assert_weixin_cdn_url(bad)


# -- dedup ---------------------------------------------------------------------
def test_message_deduplicator_ttl():
    dedup = wp.MessageDeduplicator(ttl_seconds=0.05)
    assert dedup.is_duplicate("m1") is False  # records on first sight
    assert dedup.is_duplicate("m1") is True
    assert dedup.is_duplicate("") is False  # empty key never dedups
    assert dedup.is_duplicate("") is False
    time.sleep(0.08)
    assert dedup.is_duplicate("m1") is False  # TTL expired -> new again
    assert dedup.is_duplicate("m1") is True


# -- WeixinState ---------------------------------------------------------------
def test_weixin_state_runtime_and_sync_round_trip(tmp_path):
    st = WeixinState(root=tmp_path / "weixin")
    assert st.load_runtime() == {}
    assert st.load_sync("acct@im.bot") == ""
    st.save_runtime("acct@im.bot", "https://ilinkai.weixin.qq.com")
    st.save_sync("acct@im.bot", "CURSOR")
    fresh = WeixinState(root=tmp_path / "weixin")  # survives process restart
    assert fresh.load_runtime() == {
        "account_id": "acct@im.bot",
        "base_url": "https://ilinkai.weixin.qq.com",
    }
    assert fresh.load_sync("acct@im.bot") == "CURSOR"


def test_weixin_state_corrupt_files_read_as_defaults(tmp_path):
    root = tmp_path / "weixin"
    root.mkdir()
    (root / "runtime.json").write_text("{not json", encoding="utf-8")
    (root / "a.sync.json").write_text("[1,2]", encoding="utf-8")  # wrong shape
    (root / "a.context-tokens.json").write_text("garbage", encoding="utf-8")
    st = WeixinState(root=root)
    assert st.load_runtime() == {}
    assert st.load_sync("a") == ""
    assert st.context_token("a", "peer") is None


def test_weixin_state_atomic_write_keeps_old_file_on_failure(tmp_path, monkeypatch):
    import coworker.connectors.weixin_state as ws

    st = WeixinState(root=tmp_path / "weixin")
    st.save_sync("a", "OLD")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(ws, "_replace", boom)
    st.save_sync("a", "NEW")  # must not raise
    st.set_context_token("a", "peer", "tok")  # must not raise either
    assert WeixinState(root=tmp_path / "weixin").load_sync("a") == "OLD"


def test_weixin_state_context_tokens_disk_round_trip(tmp_path):
    root = tmp_path / "weixin"
    writer = WeixinState(root=root)
    writer.set_context_token("a", "peer1", "tok1")
    writer.set_context_token("a", "peer2", "tok2")
    # a separate instance (the sender's thread) finds tokens via disk
    reader = WeixinState(root=root)
    assert reader.context_token("a", "peer1") == "tok1"
    # written AFTER the reader populated its cache -> still found (re-read on miss)
    writer.set_context_token("a", "peer3", "tok3")
    assert reader.context_token("a", "peer3") == "tok3"
    writer.drop_context_token("a", "peer1")
    assert WeixinState(root=root).context_token("a", "peer1") is None
    assert WeixinState(root=root).context_token("a", "peer2") == "tok2"
    # dropping an unknown peer is a no-op, not an error
    writer.drop_context_token("a", "nobody")


def test_weixin_state_media_dir(tmp_path):
    st = WeixinState(root=tmp_path / "weixin")
    media = st.media_dir()
    assert media == tmp_path / "weixin" / "media" and media.is_dir()
