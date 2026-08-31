"""Stateless outbound senders — one-shot HTTP POSTs, no SDK, no live connection.

These power the `send_message` tool (and the super-agent's replies). Both Telegram and
Slack outbound are simple HTTP calls, so we use a synchronous `httpx` client and avoid the
heavy SDKs (those are only needed for the inbound listeners). Sync fits the ToolRegistry's
`execute` contract (the engine runs it in a thread).

A `Sender` is `(token, chat_id, text, thread_id) -> SendResult`. The registry is swappable so
tests inject fakes — no network.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from .base import SendResult

Sender = Callable[[str, str, str, Optional[str]], SendResult]

_TIMEOUT = 30.0


def _slack_api_base() -> str:
    """Web API base URL. `SLACK_API_URL` (trailing slash) lets tests / the FakeSlack harness
    redirect outbound sends to a local fake. See platform/docs/FAKE-SLACK-SPEC.md."""
    return os.environ.get("SLACK_API_URL", "https://slack.com/api/")


def _send_telegram(
    token: str, chat_id: str, text: str, thread_id: Optional[str] = None
) -> SendResult:
    import httpx

    payload: dict = {"chat_id": chat_id, "text": text}
    # Telegram's General forum topic is thread_id "1", which sendMessage rejects → omit it.
    if thread_id and thread_id != "1":
        try:
            payload["message_thread_id"] = int(thread_id)
        except ValueError:
            pass
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=_TIMEOUT,
        )
        data = resp.json()
    except Exception as exc:  # network / decode
        return SendResult(False, error=str(exc))
    if data.get("ok"):
        return SendResult(
            True, message_id=str(data.get("result", {}).get("message_id"))
        )
    return SendResult(False, error=data.get("description") or "telegram send failed")


def _send_slack(
    token: str, chat_id: str, text: str, thread_id: Optional[str] = None
) -> SendResult:
    import httpx

    from .slack_addr import split

    # A managed-relay chat_id is team-qualified ("T…/C…"); Slack's API wants the
    # bare channel. The per-team token is selected by the caller (send_message).
    _team, chat_id = split(chat_id)
    payload: dict = {"channel": chat_id, "text": text}
    if thread_id:
        payload["thread_ts"] = thread_id
    try:
        resp = httpx.post(
            f"{_slack_api_base()}chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=_TIMEOUT,
        )
        data = resp.json()
    except Exception as exc:
        return SendResult(False, error=str(exc))
    if data.get("ok"):
        return SendResult(True, message_id=data.get("ts"))
    err = data.get("error") or "slack send failed"
    if err == "not_in_channel":
        err = "not_in_channel — invite @OpenWorker to the channel in Slack, then retry"
    return SendResult(False, error=err)


def _slack_blocks(text: str, buttons) -> list[dict]:
    """A Block Kit message: a text section + a row of action buttons (action_id `ocw_<i>`,
    value = the encoded item id + resolution)."""
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if buttons:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": b.label[:75]},
                        "value": b.value,
                        "action_id": f"ocw_{i}",
                    }
                    for i, b in enumerate(buttons)
                ],
            }
        )
    return blocks


def _send_slack_interactive(
    token: str, chat_id: str, text: str, buttons, thread_id: Optional[str] = None
) -> SendResult:
    import httpx

    from .slack_addr import split

    _team, chat_id = split(chat_id)
    payload: dict = {
        "channel": chat_id,
        "text": text,
        "blocks": _slack_blocks(text, buttons),
    }
    if thread_id:
        payload["thread_ts"] = thread_id
    try:
        resp = httpx.post(
            f"{_slack_api_base()}chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=_TIMEOUT,
        )
        data = resp.json()
    except Exception as exc:
        return SendResult(False, error=str(exc))
    if data.get("ok"):
        return SendResult(True, message_id=data.get("ts"))
    return SendResult(False, error=data.get("error") or "slack send failed")


def _send_weixin(
    token: str, chat_id: str, text: str, thread_id: Optional[str] = None
) -> SendResult:
    """Personal WeChat via the iLink Bot API (no threads — `thread_id` ignored).

    Stateless like the other senders, but iLink needs two bits of local runtime
    state (written by the adapter/QR login, NOT the SecretStore): the per-account
    base URL + account id from `runtime.json`, and the peer's cached
    `context_token`, which outbound sends echo. Text is markdown-normalized and
    split into <=2000-char chunks; each chunk retries on rate limit (-2), and a
    session-expired response (-14, or -2 disguised as "unknown error") drops the
    cached token and retries once tokenless — iLink accepts degraded tokenless
    sends, which keeps unattended pushes alive.
    """
    import time
    import uuid

    import httpx

    from .weixin_protocol import (
        API_TIMEOUT_S,
        EP_SEND_MESSAGE,
        RATE_LIMIT_ERRCODE,
        SESSION_EXPIRED_ERRCODE,
        api_post_sync,
        build_send_payload,
        format_outbound,
        is_stale_session,
        split_for_delivery,
    )
    from .weixin_state import WeixinState

    state = WeixinState()
    runtime = state.load_runtime()
    account_id = str(runtime.get("account_id") or "")
    base_url = str(runtime.get("base_url") or "")
    if not account_id or not base_url:
        return SendResult(False, error="weixin not connected")
    chunks = [c for c in split_for_delivery(format_outbound(text)) if c.strip()]
    if not chunks:
        return SendResult(False, error="empty message")
    context_token = state.context_token(account_id, chat_id)
    last_message_id: Optional[str] = None
    _MAX_ATTEMPTS = 4  # per chunk, across transport + rate-limit retries
    _CHUNK_DELAY = 1.5  # between chunks, not after the last
    with httpx.Client() as client:
        for index, chunk in enumerate(chunks):
            # client_id doubles as the server-side dedup key: a retried chunk MUST
            # reuse it so a send that actually landed isn't duplicated.
            client_id = f"ow-weixin-{uuid.uuid4().hex}"
            retried_without_token = False
            attempt = 0
            while True:
                try:
                    resp = api_post_sync(
                        client,
                        base_url=base_url,
                        endpoint=EP_SEND_MESSAGE,
                        payload=build_send_payload(
                            chat_id, chunk, context_token, client_id
                        ),
                        token=token,
                        timeout_s=API_TIMEOUT_S,
                    )
                except Exception as exc:  # network / decode
                    attempt += 1
                    if attempt >= _MAX_ATTEMPTS:
                        return SendResult(False, error=str(exc))
                    time.sleep(1.0 * attempt)  # linear backoff
                    continue
                ret = resp.get("ret")
                errcode = resp.get("errcode")
                if ret in (0, None) and errcode in (0, None):
                    last_message_id = str(resp.get("message_id") or "") or client_id
                    break
                stale = (
                    ret == SESSION_EXPIRED_ERRCODE
                    or errcode == SESSION_EXPIRED_ERRCODE
                    or is_stale_session(ret, errcode, resp.get("errmsg"))
                )
                if stale and context_token and not retried_without_token:
                    # Session expired: drop the cached token, retry once tokenless.
                    retried_without_token = True
                    state.drop_context_token(account_id, chat_id)
                    context_token = None
                    continue
                if ret == RATE_LIMIT_ERRCODE or errcode == RATE_LIMIT_ERRCODE:
                    attempt += 1
                    if attempt >= _MAX_ATTEMPTS:
                        errmsg = resp.get("errmsg") or resp.get("msg") or "rate limited"
                        return SendResult(
                            False,
                            error=(
                                "iLink sendmessage rate limited: "
                                f"ret={ret} errcode={errcode} errmsg={errmsg}"
                            ),
                        )
                    time.sleep(3.0)  # 3x backoff for genuine rate limits
                    continue
                errmsg = resp.get("errmsg") or resp.get("msg") or "unknown error"
                return SendResult(
                    False,
                    error=(
                        "iLink sendmessage error: "
                        f"ret={ret} errcode={errcode} errmsg={errmsg}"
                    ),
                )
            if index < len(chunks) - 1:
                time.sleep(_CHUNK_DELAY)
    return SendResult(True, message_id=last_message_id)


DEFAULT_SENDERS: dict[str, Sender] = {
    "telegram": _send_telegram,
    "slack": _send_slack,
    "weixin": _send_weixin,
}


# -- file upload (§34 / UX-016) --------------------------------------------------------
# A FileSender is (token, chat_id, thread_id, filename, data, title, comment) -> SendResult.
FileSender = Callable[
    [str, str, Optional[str], str, bytes, Optional[str], Optional[str]], SendResult
]


def _send_slack_file(
    token: str,
    chat_id: str,
    thread_id: Optional[str],
    filename: str,
    data: bytes,
    title: Optional[str] = None,
    comment: Optional[str] = None,
) -> SendResult:
    """files_upload_v2 (the only non-deprecated path): reserve an upload URL, PUT the
    bytes, then complete into the channel/thread. Slack renders its own previews for
    pdf/csv/images — that's the whole point of sending the file instead of a thumbnail.
    """
    import httpx

    from .slack_addr import split

    _team, chat_id = split(chat_id)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.post(
            f"{_slack_api_base()}files.getUploadURLExternal",
            headers=headers,
            data={"filename": filename, "length": str(len(data))},
            timeout=_TIMEOUT,
        )
        got = resp.json()
        if not got.get("ok"):
            return SendResult(
                False, error=got.get("error") or "slack upload-url failed"
            )
        up = httpx.post(
            got["upload_url"],
            files={"file": (filename, data)},
            timeout=max(_TIMEOUT, 120.0),
        )
        if up.status_code != 200:
            return SendResult(False, error=f"slack upload failed ({up.status_code})")
        complete: dict = {
            "files": [{"id": got["file_id"], "title": title or filename}],
            "channel_id": chat_id,
        }
        if thread_id:
            complete["thread_ts"] = thread_id
        if comment:
            complete["initial_comment"] = comment
        resp = httpx.post(
            f"{_slack_api_base()}files.completeUploadExternal",
            headers=headers,
            json=complete,
            timeout=_TIMEOUT,
        )
        data_out = resp.json()
    except Exception as exc:  # network / decode
        return SendResult(False, error=str(exc))
    if data_out.get("ok"):
        return SendResult(True, message_id=got["file_id"])
    return SendResult(False, error=data_out.get("error") or "slack file send failed")


def _send_weixin_file(
    token: str,
    chat_id: str,
    thread_id: Optional[str],
    filename: str,
    data: bytes,
    title: Optional[str] = None,
    comment: Optional[str] = None,
) -> SendResult:
    """Personal WeChat attachment via the iLink encrypted CDN (no threads).

    WeChat never takes the bytes directly. Every attachment goes: reserve a slot
    (`getuploadurl`) -> encrypt locally with AES-128-ECB + PKCS7 -> POST the ciphertext
    to the returned CDN URL -> `sendmessage` with an item that carries the CDN url, the
    key as hex, and the PLAINTEXT size. The server may hand back its own `aes_key`; when
    it does we use it rather than minting one, since the CDN will be decrypting with it.

    Extension picks the item type, so a .jpg arrives as a real photo rather than a
    file card. `comment` rides as a separate text message — items are one per message.
    """
    import uuid

    import httpx

    from .weixin_protocol import (
        API_TIMEOUT_S,
        EP_GET_UPLOAD_URL,
        EP_SEND_MESSAGE,
        ITEM_FILE,
        aes128_ecb_encrypt,
        api_post_sync,
        build_item_send_payload,
        build_media_item,
        media_type_for,
        new_aes_key,
        parse_aes_key,
    )
    from .weixin_state import WeixinState

    state = WeixinState()
    runtime = state.load_runtime()
    account_id = str(runtime.get("account_id") or "")
    base_url = str(runtime.get("base_url") or "")
    if not account_id or not base_url:
        return SendResult(False, error="weixin not connected")
    if not data:
        return SendResult(False, error="empty file")

    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    kind = media_type_for(ext)
    context_token = state.context_token(account_id, chat_id)
    try:
        with httpx.Client() as client:
            reserved = api_post_sync(
                client,
                base_url=base_url,
                endpoint=EP_GET_UPLOAD_URL,
                payload={"media_type": kind},
                token=token,
                timeout_s=API_TIMEOUT_S,
            )
            upload_url = str(
                reserved.get("upload_url") or reserved.get("uploadurl") or ""
            )
            if not upload_url:
                # Probed against the live API 2026-08-31: `getuploadurl` exists (sibling
                # spellings 404, this one doesn't) but answers a bare `ret: -2` to every
                # payload shape, with no errmsg — while `getconfig` on the same token
                # answers ret 0 and names its missing field when one is absent. That is
                # a capability gate, not a payload we can guess: a QR-minted personal
                # bot appears not to be allowed to upload media at all. Say so, so the
                # agent stops offering files and falls back to text.
                return SendResult(
                    False,
                    error=(
                        "this WeChat bot cannot send attachments — Tencent refused the "
                        f"upload slot ({reserved.get('errmsg') or reserved}). Personal "
                        "QR-login bots appear to be text-only. Send the content as a "
                        "message, or tell them the local file path instead."
                    ),
                )
            server_key = str(reserved.get("aes_key") or "")
            key = parse_aes_key(server_key) if server_key else new_aes_key()
            ticket = str(
                reserved.get("upload_ticket") or reserved.get("uploadticket") or ""
            )

            headers = {"Content-Type": "application/octet-stream"}
            if ticket:
                headers["Upload-Ticket"] = ticket
            uploaded = client.post(
                upload_url,
                content=aes128_ecb_encrypt(data, key),
                headers=headers,
                timeout=120.0,
            )
            if not uploaded.is_success:
                return SendResult(
                    False,
                    error=f"weixin CDN upload HTTP {uploaded.status_code}: {uploaded.text[:160]}",
                )
            try:
                body = uploaded.json()
            except Exception:
                body = {}
            cdn_url = str(
                body.get("cdn_url") or body.get("url") or body.get("file_url") or ""
            ) or upload_url.split("?")[0]

            item = build_media_item(
                kind,
                cdn_url,
                key,
                len(data),  # PLAINTEXT size — the receiver unpads after decrypting
                filename=filename if kind == ITEM_FILE else None,
            )
            sent = api_post_sync(
                client,
                base_url=base_url,
                endpoint=EP_SEND_MESSAGE,
                payload=build_item_send_payload(
                    chat_id, item, context_token, f"ow-weixin-{uuid.uuid4().hex}"
                ),
                token=token,
                timeout_s=API_TIMEOUT_S,
            )
    except RuntimeError as exc:  # cryptography missing, or an iLink HTTP error
        return SendResult(False, error=str(exc))
    except Exception as exc:
        return SendResult(False, error=f"weixin file send failed: {exc}")

    ret, errcode = sent.get("ret", 0), sent.get("errcode", 0)
    if ret not in (0, None) or errcode not in (0, None):
        return SendResult(
            False,
            error=f"weixin rejected the attachment (ret={ret} errcode={errcode}): "
            f"{sent.get('errmsg') or ''}".strip(),
        )
    caption = (comment or title or "").strip()
    if caption:
        _send_weixin(token, chat_id, caption, thread_id)  # best-effort, separate bubble
    return SendResult(True, message_id=str(sent.get("message_id") or "") or None)


DEFAULT_FILE_SENDERS: dict[str, FileSender] = {
    "slack": _send_slack_file,
    "weixin": _send_weixin_file,
}
