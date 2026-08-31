"""Pure protocol layer for Tencent's iLink Bot API (personal WeChat).

Constants, request builders, parsers, media crypto, and outbound formatting —
ported from Hermes' weixin gateway adapter. No framework imports (no secrets,
no base.py): stdlib + httpx only, with `cryptography` lazily imported inside
the AES helper so the connector degrades gracefully when it is missing.
Everything here is testable without network.

Protocol notes:
- Every POST body carries the `base_info` envelope and a fresh `X-WECHAT-UIN`
  header (base64 of a random uint32 rendered as a decimal string).
- `getupdates` is consume-on-read: exactly one poller per bot token. Never run
  two openworker instances polling the same token.
- Error codes: -14 = session expired; -2 = rate limit, EXCEPT -2 with errmsg
  "unknown error" which is a disguised stale-session signal (see
  `is_stale_session`).
"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import textwrap
import time
from typing import Any, Optional
from urllib.parse import quote, urlparse

import httpx

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
WEIXIN_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.2.0"
# Version 2.2.0 packed one int per byte -> 131584, sent stringified in a header.
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0

EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"
EP_GET_CONFIG = "ilink/bot/getconfig"  # mints the per-peer typing_ticket
EP_SEND_TYPING = "ilink/bot/sendtyping"
EP_GET_UPLOAD_URL = "ilink/bot/getuploadurl"  # reserves a CDN slot for outbound media

TYPING_START = 1
TYPING_STOP = 2
# The client clears the bubble on its own a few seconds after the last signal, so a
# turn that outlives one interval has to keep saying so.
TYPING_KEEPALIVE_S = 5.0
# Ticket lifetime is reportedly much longer (~24h); re-minting every 10 minutes costs
# one cheap call and keeps a stale ticket from silently killing the indicator.
TYPING_TICKET_TTL_S = 600.0

ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2

SESSION_EXPIRED_ERRCODE = -14
RATE_LIMIT_ERRCODE = -2  # iLink frequency limit — backoff and retry

MAX_MESSAGE_LENGTH = 2000
SPLIT_THRESHOLD = 1800  # iLink itself chunks long inbound texts at ~2048

LONG_POLL_TIMEOUT_S = 35.0
API_TIMEOUT_S = 15.0
QR_TIMEOUT_S = 35.0

_COPY_LINE_WIDTH = 120  # WeChat clients make copying long display lines painful
_FENCE_RE = re.compile(r"^```([^\n`]*)\s*$")
_TABLE_RULE_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


# -- request plumbing ----------------------------------------------------------
def json_dumps(payload: dict) -> str:
    """Compact JSON with non-ASCII kept literal — the wire format iLink expects."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _random_wechat_uin() -> str:
    """base64 of the decimal string of a random uint32 — regenerated per request."""
    value = struct.unpack(">I", os.urandom(4))[0]
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def ilink_headers(token: str | None, body: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Content-Length": str(len(body.encode("utf-8"))),
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _post_body(payload: dict) -> str:
    return json_dumps({**payload, "base_info": {"channel_version": CHANNEL_VERSION}})


async def api_post(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    endpoint: str,
    payload: dict,
    token: str | None,
    timeout_s: float = API_TIMEOUT_S,
) -> dict:
    body = _post_body(payload)
    url = f"{base_url.rstrip('/')}/{endpoint}"
    response = await client.post(
        url, content=body, headers=ilink_headers(token, body), timeout=timeout_s
    )
    raw = response.text
    if not response.is_success:
        raise RuntimeError(f"iLink POST {endpoint} HTTP {response.status_code}: {raw[:200]}")
    return json.loads(raw)


async def api_get(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    endpoint: str,
    timeout_s: float = QR_TIMEOUT_S,
) -> dict:
    """GET used only by the QR endpoints — no Authorization, no body; the
    endpoint string carries any query parameters."""
    url = f"{base_url.rstrip('/')}/{endpoint}"
    headers = {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }
    response = await client.get(url, headers=headers, timeout=timeout_s)
    raw = response.text
    if not response.is_success:
        raise RuntimeError(f"iLink GET {endpoint} HTTP {response.status_code}: {raw[:200]}")
    return json.loads(raw)


def api_post_sync(
    client: httpx.Client,
    *,
    base_url: str,
    endpoint: str,
    payload: dict,
    token: str | None,
    timeout_s: float = API_TIMEOUT_S,
) -> dict:
    """Same as `api_post` for the synchronous sender path (tool thread)."""
    body = _post_body(payload)
    url = f"{base_url.rstrip('/')}/{endpoint}"
    response = client.post(
        url, content=body, headers=ilink_headers(token, body), timeout=timeout_s
    )
    raw = response.text
    if not response.is_success:
        raise RuntimeError(f"iLink POST {endpoint} HTTP {response.status_code}: {raw[:200]}")
    return json.loads(raw)


# -- response classification ---------------------------------------------------
def is_stale_session(
    ret: Optional[int], errcode: Optional[int], errmsg: Optional[str]
) -> bool:
    """True when iLink returns ret=-2 / errcode=-2 with "unknown error", which is
    a stale-session signal (same as errcode=-14) rather than a genuine rate
    limit. -14 itself is deliberately NOT matched — callers handle it separately.
    """
    if ret != RATE_LIMIT_ERRCODE and errcode != RATE_LIMIT_ERRCODE:
        return False
    return (errmsg or "").strip().lower() == "unknown error"


# -- inbound parsing -----------------------------------------------------------
def guess_chat_type(message: dict, account_id: str) -> tuple[str, str]:
    """("dm"|"group", chat_id). Group rooms conventionally end with @chatroom;
    the to_user_id heuristic catches roomless group events (msg_type == 1)."""
    room_id = str(message.get("room_id") or message.get("chat_room_id") or "").strip()
    to_user_id = str(message.get("to_user_id") or "").strip()
    is_group = bool(room_id) or (
        to_user_id
        and account_id
        and to_user_id != account_id
        and message.get("msg_type") == 1
    )
    if is_group:
        return "group", room_id or to_user_id or str(message.get("from_user_id") or "")
    return "dm", str(message.get("from_user_id") or "")


def extract_text(item_list: list[dict]) -> str:
    """First ITEM_TEXT wins, with quote-reply prefixes; a voice item falls back to
    Tencent's own transcript, prefixed "[语音转写] ".

    The transcript wins WHENEVER Tencent supplies one, audio attached or not. It
    used to be taken only from a voice item with no media, on the belief that the
    reference adapter drops Tencent's STT and re-transcribes locally — the opposite
    of what that adapter documents ("若有文字转录，提取为文本；否则下载 SILK 格式的音频").
    The old order cost real words: nothing here decodes SILK, so a voice message
    carrying both audio and a transcript reached the agent as a `.silk` path and
    nothing else. The adapter still saves the audio alongside; the transcript is
    the body.
    """
    for item in item_list:
        if item.get("type") == ITEM_TEXT:
            text = str((item.get("text_item") or {}).get("text") or "")
            ref = item.get("ref_msg") or {}
            ref_item = ref.get("message_item") or {}
            ref_type = ref_item.get("type")
            if ref_type in {ITEM_IMAGE, ITEM_VIDEO, ITEM_FILE, ITEM_VOICE}:
                title = ref.get("title") or ""
                prefix = f"[引用媒体: {title}]\n" if title else "[引用媒体]\n"
                return f"{prefix}{text}".strip()
            if ref_item:
                parts: list[str] = []
                if ref.get("title"):
                    parts.append(str(ref["title"]))
                ref_text = extract_text([ref_item])
                if ref_text:
                    parts.append(ref_text)
                if parts:
                    return f"[引用: {' | '.join(parts)}]\n{text}".strip()
            return text
    for item in item_list:
        if item.get("type") == ITEM_VOICE:
            voice_item = item.get("voice_item") or {}
            voice_text = str(voice_item.get("text") or "").strip()
            if voice_text:
                return f"[语音转写] {voice_text}"
            continue
    return ""


# -- outbound payloads ---------------------------------------------------------
def build_send_payload(
    to: str, text: str, context_token: str | None, client_id: str
) -> dict:
    """sendmessage payload. `from_user_id` is deliberately the empty string;
    `client_id` doubles as the server-side dedup key — a retried chunk must
    reuse the same one. `context_token` is omitted entirely when absent
    (tokenless sends work as a degraded fallback)."""
    message: dict = {
        "from_user_id": "",
        "to_user_id": to,
        "client_id": client_id,
        "message_type": MSG_TYPE_BOT,
        "message_state": MSG_STATE_FINISH,
        "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
    }
    if context_token:
        message["context_token"] = context_token
    return {"msg": message}


def build_typing_payload(user_id: str, ticket: str, status: int) -> dict:
    """`sendtyping` payload — shows/hides "对方正在输入中" in the peer's WeChat.

    `base_info` is added by `_post_body` like every other call, so only the three
    call-specific fields belong here. The ticket comes from `getconfig` and is
    per-peer; `status` is TYPING_START or TYPING_STOP.

    The peer field is `ilink_user_id`, NOT `user_id` — verified against the live API
    2026-08-31, where `user_id` gets `{"ret": -2, "errmsg": "ilink_user_id required"}`
    and `ilink_user_id` gets `{"ret": 0}`. Third-party protocol write-ups say
    `user_id`; they are wrong, and the failure is silent from the caller's side.
    """
    return {"ilink_user_id": user_id, "typing_ticket": ticket, "status": status}


# -- outbound formatting -------------------------------------------------------
def _normalize_markdown_blocks(content: str) -> str:
    """Collapse blank-line runs to one, outside code fences."""
    result: list[str] = []
    in_code_block = False
    blank_run = 0
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if _FENCE_RE.match(line.strip()):
            in_code_block = not in_code_block
            result.append(line)
            blank_run = 0
            continue
        if in_code_block:
            result.append(line)
            continue
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                result.append("")
            continue
        blank_run = 0
        result.append(line)
    return "\n".join(result).strip()


def _wrap_copy_friendly_lines(content: str) -> str:
    """Hard-wrap long display lines at 120 columns for copy-friendliness.
    Code fences, table lines, and unbreakable words (long URLs) pass through
    untouched (`break_long_words=False`)."""
    if not content:
        return content
    wrapped: list[str] = []
    in_code_block = False
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            in_code_block = not in_code_block
            wrapped.append(line)
            continue
        if (
            in_code_block
            or len(line) <= _COPY_LINE_WIDTH
            or not stripped
            or stripped.startswith("|")
            or _TABLE_RULE_RE.match(stripped)
        ):
            wrapped.append(line)
            continue
        wrapped_lines = textwrap.wrap(
            line,
            width=_COPY_LINE_WIDTH,
            break_long_words=False,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )
        wrapped.extend(wrapped_lines or [line])
    return "\n".join(wrapped).strip()


def _split_table_row(line: str) -> list[str]:
    """`| a | b |` -> ["a", "b"]. Escaped pipes (`\\|`) stay inside their cell."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells, current, escaped = [], [], False
    for ch in body:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append("".join(current).strip())
    return cells


def _flatten_tables(content: str) -> str:
    """Pipe tables -> labelled `- 列名: 值` records.

    A WeChat chat bubble is a narrow single-column view with no table rendering and no
    horizontal scroll, so a pipe table arrives as a wall of `|` that says nothing about
    which column a value belongs to. One labelled block per row survives the width.

    A pipe block without a header rule is not a table (ASCII art, code, a Chinese
    sentence full of `|`) and is left alone. Fenced content is never touched.
    """
    lines = content.splitlines()
    out: list[str] = []
    in_code_block = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            in_code_block = not in_code_block
            out.append(line)
            i += 1
            continue
        is_table_head = (
            not in_code_block
            and stripped.startswith("|")
            and i + 1 < len(lines)
            and _TABLE_RULE_RE.match(lines[i + 1].strip())
        )
        if not is_table_head:
            out.append(line)
            i += 1
            continue
        headers = _split_table_row(stripped)
        i += 2  # header + rule
        records: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            cells = _split_table_row(lines[i].strip())
            record = [
                f"- {headers[n] or '—'}: {cell}"
                for n, cell in enumerate(cells)
                if n < len(headers) and cell
            ]
            if record:
                records.append("\n".join(record))
            i += 1
        if records:
            out.append("\n\n".join(records))
        # A header with no body rows collapses to nothing — an empty table says nothing.
    return "\n".join(out)


def _reformat_headings(content: str) -> str:
    """`# H1` -> `【H1】`, `## H2` and deeper -> `**H2**`.

    WeChat renders neither `#` nor bold, but it does render the brackets, and either
    form reads as a heading in plain text — where a bare `##` just looks like stray
    punctuation. Fenced content is left alone (`#` is a comment in most languages).
    """
    out: list[str] = []
    in_code_block = False
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if _FENCE_RE.match(stripped):
            in_code_block = not in_code_block
            out.append(raw_line)
            continue
        match = None if in_code_block else _HEADING_RE.match(raw_line)
        if match is None:
            out.append(raw_line)
            continue
        title = match.group(2).strip()
        if not title:
            out.append(raw_line)
            continue
        out.append(f"【{title}】" if len(match.group(1)) == 1 else f"**{title}**")
    return "\n".join(out)


def _harden_code_blocks(content: str) -> str:
    """Make fenced code survive WeChat's renderer.

    WeChat re-renders the message as Markdown, and its subset does NOT honour ```
    fences: the markers vanish and the code inside is soft-wrapped like prose, so every
    newline collapses to a space and the indentation disappears. Field evidence
    (2026-08-31): a 119-line Python answer arrived as one run-on paragraph —
    `import json from dataclasses import dataclass, field` — unreadable, uncopyable,
    unrunnable.

    Two things do survive, from the same evidence: a BLANK line still breaks a
    paragraph, and `- item` still renders as its own bulleted line. So each code line
    is separated by a blank line, and its leading indentation is rewritten with U+00A0,
    which Markdown does not collapse. Verbose, and correct — for code that is the trade
    worth making. (Long code is better sent as a file; see the DM opening instruction.)
    """
    if "```" not in content:
        return content
    out: list[str] = []
    code: list[str] | None = None
    for raw_line in content.splitlines():
        if _FENCE_RE.match(raw_line.strip()):
            if code is None:
                code = []
            else:
                # Blank-line separated so each source line stays a line, with the indent
                # carried by non-breaking spaces.
                out.append("\n\n".join(code))
                code = None
            continue
        if code is None:
            out.append(raw_line)
            continue
        stripped = raw_line.lstrip(" \t")
        indent = len(raw_line) - len(stripped)
        code.append(" " * indent + stripped if stripped else " ")
    if code:  # unterminated fence — keep the content rather than dropping it
        out.append("\n\n".join(code))
    return "\n".join(out)


def format_outbound(text: str) -> str:
    """Prepare agent markdown for a WeChat chat bubble.

    WeChat re-renders what we send as Markdown, and its subset is narrow: lists and
    links work, headings/tables/``` fences do not. So headings and tables are rewritten
    into forms it does render, fenced code is hardened against soft-wrapping, and then
    blank-line normalization and the 120-col copy-friendly wrap run as before.
    """
    return _wrap_copy_friendly_lines(
        _normalize_markdown_blocks(
            _harden_code_blocks(_flatten_tables(_reformat_headings(text)))
        )
    )


def _split_markdown_blocks(content: str) -> list[str]:
    """Split on blank lines into blocks; a fenced code block is one block."""
    if not content:
        return []
    blocks: list[str] = []
    current: list[str] = []
    in_code_block = False
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if _FENCE_RE.match(line.strip()):
            if not in_code_block and current:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(line)
            in_code_block = not in_code_block
            if not in_code_block:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        if in_code_block:
            current.append(line)
            continue
        if not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _fence_opener(block: str) -> str | None:
    """The opening fence line of a fenced block (e.g. "```python"), else None."""
    first = block.lstrip().splitlines()[0].strip() if block.strip() else ""
    return first if _FENCE_RE.match(first) else None


def _split_oversized_block(block: str, max_length: int) -> list[str]:
    """One block that alone exceeds max_length -> several chunks, losing nothing.

    Blocks are only cut at blank lines and fences upstream, so a table, a long list
    or a single paragraph is ONE block however long it runs — and this is the path
    they land on. It used to be `block[:max_length]`, which silently dropped the
    tail (a 5.8k code block arrived as 2k with 3.8k gone and no ellipsis), and cut
    fenced code mid-block, shipping an unbalanced ``` that swallows the rest of the
    conversation in the WeChat client. Cut at a line break where possible, then a
    space, then mid-run as a last resort; a fenced block closes its fence at every
    cut and reopens with the original language tag so each piece renders alone.
    """
    fence = _fence_opener(block)
    if fence:
        body = block.strip()
        lines = body.splitlines()
        # Drop the opener and the closer; they are re-added per piece below.
        inner = lines[1:]
        if inner and _FENCE_RE.match(inner[-1].strip()):
            inner = inner[:-1]
        body = "\n".join(inner)
        # Every piece costs the opener + a newline + a closing fence.
        budget = max_length - (len(fence) + 1) - 4
        pieces = _hard_wrap(body, budget) if budget > 0 else _hard_wrap(body, max_length)
        return [f"{fence}\n{piece}\n```" for piece in pieces]
    return _hard_wrap(block, max_length)


def _hard_wrap(text: str, limit: int) -> list[str]:
    """`text` -> pieces of at most `limit` chars, preferring a line break, then a
    space, then an exact cut. Drops only the one separator character it cuts on.

    That last part is load-bearing for code: `lstrip()`ing the remainder would eat the
    next line's indentation along with the newline, so a split Python block came out
    de-indented at every seam and would not run when copied out of WeChat. Trailing
    spaces go, blank lines stay.
    """
    if limit <= 0:
        return [text]
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[: limit + 1]
        cut, sep = window.rfind("\n"), 1
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut, sep = limit, 0  # no breathing room (CJK runs, minified text)
        pieces.append(rest[:cut].rstrip(" \t"))
        rest = rest[cut + sep :]
    if rest:
        pieces.append(rest)
    return [p for p in pieces if p.strip()]


def _greedy_pack_blocks(blocks: list[str], max_length: int) -> list[str]:
    """Greedily re-pack blocks into chunks of at most max_length, joined with
    a blank line. A single block that alone exceeds the limit is SPLIT, not
    truncated (`_split_oversized_block`)."""
    packed: list[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current:
            packed.append(current)
            current = ""
        if len(block) <= max_length:
            current = block
            continue
        packed.extend(_split_oversized_block(block, max_length))
    if current:
        packed.append(current)
    return packed


def split_for_delivery(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Compact chunking: one message when it fits; otherwise split on blank-line
    block boundaries (code fences never split) and greedily re-pack. "" -> []."""
    if not text:
        return []
    if len(text) <= max_length:
        return [text]
    return _greedy_pack_blocks(_split_markdown_blocks(text), max_length) or [text]


# -- media crypto & CDN --------------------------------------------------------
def parse_aes_key(aes_key_b64: str) -> bytes:
    """Inbound `media.aes_key` is base64 of either 16 raw key bytes or a
    32-char ASCII-hex string of the key (i.e. base64(hex))."""
    decoded = base64.b64decode(aes_key_b64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        text = decoded.decode("ascii", errors="ignore")
        if text and all(ch in "0123456789abcdefABCDEF" for ch in text):
            return bytes.fromhex(text)
    raise ValueError(f"unexpected aes_key format ({len(decoded)} decoded bytes)")


def aes128_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """AES-128-ECB with tolerant PKCS7 unpad: strip padding only when the tail
    actually repeats the pad byte, else return as-is."""
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is required to decrypt WeChat media (pip install cryptography)"
        ) from exc
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    if not padded:
        return padded
    pad_len = padded[-1]
    if 1 <= pad_len <= 16 and padded.endswith(bytes([pad_len]) * pad_len):
        return padded[:-pad_len]
    return padded


def new_aes_key() -> bytes:
    """A fresh 16-byte AES-128 key for one outbound upload."""
    import secrets as _secrets

    return _secrets.token_bytes(16)


def aes128_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """The inverse of `aes128_ecb_decrypt` — AES-128-ECB with real PKCS7 padding.

    Padding is added unconditionally (a whole extra block when the input is already
    aligned), which is what PKCS7 requires and what the decrypt side's tolerant
    unpad expects.
    """
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is required to send WeChat media (pip install cryptography)"
        ) from exc
    pad_len = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([pad_len]) * pad_len
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def build_media_item(
    kind: int, cdn_url: str, aes_key: bytes, filesize: int, filename: str | None = None
) -> dict:
    """One `item_list` entry referencing media already uploaded to the CDN.

    The key travels as 32 hex chars — the `image_item.aeskey` form the inbound parser
    already understands (`image_aes_key`), so a message we send round-trips through our
    own reader.
    """
    body: dict = {"url": cdn_url, "aeskey": aes_key.hex(), "filesize": int(filesize)}
    if kind == ITEM_IMAGE:
        return {"type": kind, "image_item": body}
    if kind == ITEM_VIDEO:
        return {"type": kind, "video_item": body}
    if filename:
        body["filename"] = filename
    return {"type": ITEM_FILE, "file_item": body}


def build_item_send_payload(
    to: str, item: dict, context_token: str | None, client_id: str
) -> dict:
    """`build_send_payload` for any single item_list entry, not just text."""
    message: dict = {
        "from_user_id": "",
        "to_user_id": to,
        "client_id": client_id,
        "message_type": MSG_TYPE_BOT,
        "message_state": MSG_STATE_FINISH,
        "item_list": [item],
    }
    if context_token:
        message["context_token"] = context_token
    return {"msg": message}


def media_type_for(ext: str) -> int:
    """The item type a file extension should be sent as."""
    ext = (ext or "").lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "gif", "bmp", "webp"}:
        return ITEM_IMAGE
    if ext in {"mp4", "mov", "m4v", "avi", "mkv"}:
        return ITEM_VIDEO
    return ITEM_FILE


def media_reference(item: dict, key: str) -> dict:
    """`item[key].media` — {encrypt_query_param, aes_key, full_url}, or {}."""
    return (item.get(key) or {}).get("media") or {}


def image_aes_key(item: dict) -> bytes | None:
    """Images may carry the key as `image_item.aeskey` (plain hex, sibling of
    `media`) — preferred; else fall back to the base64 `media.aes_key`."""
    image_item = item.get("image_item") or {}
    aeskey_hex = str(image_item.get("aeskey") or "")
    if aeskey_hex:
        return bytes.fromhex(aeskey_hex)
    aes_key_b64 = (image_item.get("media") or {}).get("aes_key")
    if aes_key_b64:
        return parse_aes_key(aes_key_b64)
    return None


def cdn_download_url(cdn_base_url: str, encrypted_query_param: str) -> str:
    return (
        f"{cdn_base_url.rstrip('/')}/download"
        f"?encrypted_query_param={quote(encrypted_query_param, safe='')}"
    )


_WEIXIN_CDN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "novac2c.cdn.weixin.qq.com",
        "ilinkai.weixin.qq.com",
        "wx.qlogo.cn",
        "thirdwx.qlogo.cn",
        "res.wx.qq.com",
        "mmbiz.qpic.cn",
        "mmbiz.qlogo.cn",
    }
)


def assert_weixin_cdn_url(url: str) -> None:
    """Raise ValueError if *url* does not point at a known WeChat CDN host
    (SSRF guard for `media.full_url`)."""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname or ""
    except Exception as exc:
        raise ValueError(f"Unparseable media URL: {url!r}") from exc
    if scheme not in {"http", "https"}:
        raise ValueError(
            f"Media URL has disallowed scheme {scheme!r}; only http/https are permitted."
        )
    if host not in _WEIXIN_CDN_ALLOWLIST:
        raise ValueError(
            f"Media URL host {host!r} is not in the WeChat CDN allowlist. "
            "Refusing to fetch to prevent SSRF."
        )


# -- dedup ---------------------------------------------------------------------
class MessageDeduplicator:
    """TTL-based seen-set. iLink can redeliver a message under the same id (and
    occasionally identical content under a fresh id — callers add a content
    fingerprint key for that)."""

    _MAX_SIZE = 2000

    def __init__(self, ttl_seconds: float = 300.0):
        self._ttl = ttl_seconds
        self._seen: dict[str, float] = {}

    def is_duplicate(self, key: str) -> bool:
        """True if *key* was seen within the TTL window; records it otherwise."""
        if not key:
            return False
        now = time.time()
        if key in self._seen:
            if now - self._seen[key] < self._ttl:
                return True
            del self._seen[key]
        self._seen[key] = now
        if len(self._seen) > self._MAX_SIZE:
            cutoff = now - self._ttl
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
            if len(self._seen) > self._MAX_SIZE:
                # Every entry still fresh — keep the newest to bound memory.
                newest = sorted(self._seen.items(), key=lambda kv: kv[1])
                self._seen = dict(newest[-self._MAX_SIZE :])
        return False
