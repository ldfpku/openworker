"""Weixin (personal WeChat) inbound adapter — iLink Bot API long-poll.

Port of Hermes' weixin adapter (read-only ref) onto openworker's adapter contract:
`connect()` starts a getupdates long-poll task; each message is parsed by the pure
functions in `weixin_protocol`, deduplicated, media-resolved, and dispatched via
`handle_message`. Delivery authorization stays in the Gateway allowlist (house
invariant); the adapter only consults the Gateway-installed auth probe to skip
expensive side effects (media download/decrypt, context-token persistence) for
senders the allowlist is going to park. Outbound reuses the stateless
`_send_weixin` sender in a thread.

Rapid-fire texts are debounced per sender: iLink delivers each WeChat bubble (and each
~2048-char fragment of a long message) as a separate message, so text events buffer and
flush after a quiet period, joined with newlines. Media-bearing events skip the buffer.

IMPORTANT: getupdates is consume-on-read — one poller per token. Never run two
openworker instances polling the same bot token (each steals half the messages).
A fresh QR login mints its own bot identity/token, so separate logins coexist fine.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx

from .base import BasePlatformAdapter, MessageEvent, SendResult, SessionSource
from .senders import _send_weixin
from .weixin_lock import LOCK_BUSY_MESSAGE, TokenLock
from .weixin_protocol import (
    EP_GET_CONFIG,
    EP_GET_UPDATES,
    EP_SEND_TYPING,
    ILINK_BASE_URL,
    ITEM_FILE,
    ITEM_IMAGE,
    ITEM_VIDEO,
    ITEM_VOICE,
    LONG_POLL_TIMEOUT_S,
    SESSION_EXPIRED_ERRCODE,
    SPLIT_THRESHOLD,
    TYPING_KEEPALIVE_S,
    TYPING_START,
    TYPING_STOP,
    TYPING_TICKET_TTL_S,
    WEIXIN_CDN_BASE_URL,
    MessageDeduplicator,
    api_post,
    assert_weixin_cdn_url,
    build_typing_payload,
    cdn_download_url,
    extract_text,
    guess_chat_type,
    image_aes_key,
    is_stale_session,
    parse_aes_key,
)
from .weixin_state import WeixinState

logger = logging.getLogger("coworker.connectors")

# Poll-loop backoff (mirrors Hermes): 2 s per failure, 30 s after a 3-failure streak.
_MAX_CONSECUTIVE_FAILURES = 3
_RETRY_DELAY_S = 2.0
_BACKOFF_DELAY_S = 30.0
# Session-expired (-14 / -2+"unknown error") on poll: pause, don't hammer.
_SESSION_EXPIRED_PAUSE_S = 600.0

_CRYPTOGRAPHY_NOTE = "[收到媒体，未安装 cryptography，无法解密]"

_MAX_MEDIA_BYTES = 50 * 1024 * 1024  # inbound attachment cap, mirrors send_file's 50 MB

_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def _safe_ext(ext: str) -> str:
    """Peer-supplied file extensions go into a cache path — allow only a short
    alphanumeric suffix (no separators, no dots) so a crafted file_name can't
    traverse out of the media dir."""
    return ext if _EXT_RE.match(ext or "") else ".bin"


def _decrypt_and_write(data: bytes, aes_key, path) -> None:
    if aes_key is not None:
        from .weixin_protocol import aes128_ecb_decrypt

        data = aes128_ecb_decrypt(data, aes_key)
    path.write_bytes(data)


class WeixinAdapter(BasePlatformAdapter):
    platform = "weixin"

    def __init__(
        self,
        profile: dict,
        *,
        state: Optional[WeixinState] = None,
        batch_delay: float = 3.0,
        batch_split_delay: float = 5.0,
    ) -> None:
        super().__init__()
        self._token = str(profile.get("bot_token") or "")
        self._account_id = str(profile.get("account_id") or "")
        self._base_url = str(profile.get("base_url") or "") or ILINK_BASE_URL
        self._state = state or WeixinState()
        self._batch_delay = batch_delay
        self._batch_split_delay = batch_split_delay
        self._client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False
        self._dedup = MessageDeduplicator()
        # Per-sender text debounce buffers + their flush tasks (see module docstring).
        self._pending_batches: dict[str, MessageEvent] = {}
        self._pending_last_len: dict[str, int] = {}
        self._batch_tasks: dict[str, asyncio.Task] = {}
        # Fire-and-forget per-message tasks, kept so disconnect() can cancel them.
        self._msg_tasks: set[asyncio.Task] = set()
        # Held between connect() and disconnect() — see weixin_lock.
        self._lock: Optional[TokenLock] = None
        # peer -> (typing_ticket, expires_at monotonic)
        self._typing_tickets: dict[str, tuple[str, float]] = {}

    async def connect(self) -> bool:
        if not self._token or not self._account_id:
            logger.warning("weixin: profile missing bot_token/account_id — skipping")
            return False
        # One poller per token, enforced rather than merely documented (weixin_lock):
        # a second instance would take half the messages and nothing would say so.
        self._lock = TokenLock(self._token, self._state.root)
        if not self._lock.acquire():
            held_by = self._lock.holder_pid()
            self._lock = None
            logger.error(
                "weixin: %s%s",
                LOCK_BUSY_MESSAGE,
                f" (holder pid {held_by})" if held_by else "",
            )
            return False
        self._client = httpx.AsyncClient()
        # Runtime state lets the stateless sender find the per-account base URL and
        # account id without touching the SecretStore.
        self._state.save_runtime(self._account_id, self._base_url)
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        # No live credential check: getupdates is consume-on-read, the first poll IS
        # the check (a validation call would eat a batch of messages).
        logger.info("weixin adapter polling as %s…", self._account_id[:8])
        return True

    async def disconnect(self) -> None:
        # Idempotent full teardown — refresh_gateway calls this on every connector change.
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        for task in list(self._batch_tasks.values()):
            task.cancel()
        self._batch_tasks.clear()
        self._pending_batches.clear()
        self._pending_last_len.clear()
        for task in list(self._msg_tasks):
            task.cancel()
        self._msg_tasks.clear()
        if self._client is not None:
            client, self._client = self._client, None
            try:
                await client.aclose()
            except Exception:
                pass
        # Released LAST: the token stays claimed until this adapter has genuinely
        # stopped polling, so a refresh_gateway disconnect/reconnect cycle can't
        # briefly run two pollers. (The OS also drops it if we die outright.)
        if self._lock is not None:
            lock, self._lock = self._lock, None
            lock.release()

    async def send(
        self, chat_id: str, text: str, *, thread_id: Optional[str] = None
    ) -> SendResult:
        # One code path for gateway.deliver and the send_message tool: the stateless
        # sync sender, off the event loop.
        return await asyncio.to_thread(
            _send_weixin, self._token, chat_id, text, thread_id
        )

    # -- long-poll loop ---------------------------------------------------------
    async def _poll_loop(self) -> None:
        buf = self._state.load_sync(self._account_id)
        timeout_s = LONG_POLL_TIMEOUT_S
        consecutive_failures = 0
        while self._running:
            try:
                try:
                    response = await api_post(
                        self._client,
                        base_url=self._base_url,
                        endpoint=EP_GET_UPDATES,
                        payload={"get_updates_buf": buf},
                        token=self._token,
                        timeout_s=timeout_s,
                    )
                except httpx.TimeoutException:
                    # A timed-out long poll is a normal empty batch — re-poll now.
                    continue
                # Honor the server-suggested long-poll timeout for subsequent polls.
                suggested = response.get("longpolling_timeout_ms")
                if isinstance(suggested, int) and suggested > 0:
                    timeout_s = suggested / 1000.0
                ret = response.get("ret", 0)
                errcode = response.get("errcode", 0)
                if ret not in (0, None) or errcode not in (0, None):
                    if (
                        ret == SESSION_EXPIRED_ERRCODE
                        or errcode == SESSION_EXPIRED_ERRCODE
                        or is_stale_session(ret, errcode, response.get("errmsg"))
                    ):
                        logger.warning(
                            "weixin: session expired — pausing polls for 10 minutes "
                            "(re-run the QR login to refresh credentials)"
                        )
                        await asyncio.sleep(_SESSION_EXPIRED_PAUSE_S)
                        consecutive_failures = 0
                        continue
                    consecutive_failures += 1
                    logger.warning(
                        "weixin: getupdates failed ret=%s errcode=%s errmsg=%s (%d/%d)",
                        ret,
                        errcode,
                        response.get("errmsg", ""),
                        consecutive_failures,
                        _MAX_CONSECUTIVE_FAILURES,
                    )
                    await asyncio.sleep(
                        _BACKOFF_DELAY_S
                        if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
                        else _RETRY_DELAY_S
                    )
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        consecutive_failures = 0
                    continue
                consecutive_failures = 0
                new_buf = str(response.get("get_updates_buf") or "")
                if new_buf:
                    buf = new_buf
                    self._state.save_sync(self._account_id, buf)
                for message in response.get("msgs") or []:
                    task = asyncio.create_task(self._process_message_safe(message))
                    self._msg_tasks.add(task)
                    task.add_done_callback(self._msg_tasks.discard)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "weixin: poll error (%d/%d): %s",
                    consecutive_failures,
                    _MAX_CONSECUTIVE_FAILURES,
                    exc,
                )
                await asyncio.sleep(
                    _BACKOFF_DELAY_S
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
                    else _RETRY_DELAY_S
                )
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    # Failed connects through a local proxy can strand sockets in the
                    # pool; a fresh client starts the next attempt from zero fds.
                    await self._recycle_client()

    # -- "对方正在输入中" -------------------------------------------------------
    # A WeChat DM looks like a chat, so silence between question and answer reads as
    # "it didn't get my message" — and openworker makes that gap longer than most,
    # since inbound text is debounced for seconds before the turn even starts. The
    # indicator costs one cheap call and covers the whole wait.
    #
    # Every failure here is swallowed: a missing typing bubble is cosmetic, and must
    # never cost the user their reply.
    async def _typing_ticket(self, peer: str) -> Optional[str]:
        cached = self._typing_tickets.get(peer)
        now = time.monotonic()
        if cached and now < cached[1]:
            return cached[0]
        client = self._client
        if client is None:
            return None
        try:
            response = await api_post(
                client,
                base_url=self._base_url,
                endpoint=EP_GET_CONFIG,
                # `ilink_user_id`, not `user_id` — see build_typing_payload.
                payload={"ilink_user_id": peer},
                token=self._token,
                timeout_s=10.0,
            )
        except Exception as exc:
            logger.warning("weixin: getconfig failed for typing ticket: %s", exc)
            return None
        if response.get("ret") not in (0, None):
            # Logged, not swallowed: a wrong field name here cost a whole round of
            # "the typing indicator still doesn't show" with nothing in the log.
            logger.warning("weixin: getconfig refused a typing ticket: %s", response)
            return None
        ticket = str(response.get("typing_ticket") or "")
        if not ticket:
            return None
        self._typing_tickets[peer] = (ticket, now + TYPING_TICKET_TTL_S)
        return ticket

    async def _send_typing(self, peer: str, status: int) -> bool:
        ticket = await self._typing_ticket(peer)
        client = self._client
        if not ticket or client is None:
            return False
        try:
            response = await api_post(
                client,
                base_url=self._base_url,
                endpoint=EP_SEND_TYPING,
                payload=build_typing_payload(peer, ticket, status),
                token=self._token,
                timeout_s=10.0,
            )
        except Exception as exc:
            logger.warning("weixin: sendtyping(%s) failed: %s", status, exc)
            self._typing_tickets.pop(peer, None)
            return False
        if response.get("ret") not in (0, None):
            logger.warning("weixin: sendtyping(%s) refused: %s", status, response)
            # A ticket the server has stopped accepting must not stick around.
            self._typing_tickets.pop(peer, None)
            return False
        return True

    async def _typing_keepalive(self, peer: str) -> None:
        """Re-assert "typing" until cancelled — the bubble self-clears otherwise."""
        try:
            while True:
                if not await self._send_typing(peer, TYPING_START):
                    return  # unsupported or refused: stop trying for this turn
                await asyncio.sleep(TYPING_KEEPALIVE_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("weixin: typing keepalive stopped", exc_info=True)

    @asynccontextmanager
    async def _typing(self, peer: str):
        """Hold "typing" for the duration of the block."""
        task: Optional[asyncio.Task] = None
        if peer:
            task = asyncio.create_task(self._typing_keepalive(peer))
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                # Clear it explicitly; waiting for the client's own timeout leaves the
                # bubble up next to an answer that has already arrived.
                try:
                    await self._send_typing(peer, TYPING_STOP)
                except Exception:
                    pass

    async def _dispatch(self, event: MessageEvent) -> None:
        """Hand one event to the gateway, showing "typing…" until the turn returns.

        `handle_message` is awaited all the way through the agent's turn, so the
        indicator's lifetime is the turn's lifetime for free. (A busy session queues
        the text as steering and returns early — the bubble clears then, which is
        honest: that turn's answer belongs to the message already in flight.)
        """
        async with self._typing(event.source.user_id or ""):
            await self.handle_message(event)

    async def _recycle_client(self) -> None:
        """Swap-then-close so concurrent message tasks never observe a closed client."""
        if not self._running:
            return
        old = self._client
        self._client = httpx.AsyncClient()
        if old is not None:
            try:
                await old.aclose()
            except Exception:
                pass

    # -- inbound processing -----------------------------------------------------
    async def _process_message_safe(self, message: dict) -> None:
        try:
            await self._process_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("weixin: unhandled inbound error")

    async def _process_message(self, message: dict) -> None:
        sender_id = str(message.get("from_user_id") or "").strip()
        if not sender_id or sender_id == self._account_id:
            return  # empty sender / self-echo
        message_id = str(message.get("message_id") or "").strip()
        if message_id and self._dedup.is_duplicate(message_id):
            return
        item_list = message.get("item_list") or []
        text = extract_text(item_list)
        if text:
            # Secondary content fingerprint: the API can redeliver identical
            # content under a fresh message_id.
            content_key = (
                f"content:{sender_id}:{hashlib.md5(text.encode()).hexdigest()}"
            )
            if self._dedup.is_duplicate(content_key):
                return
        chat_type, effective_chat_id = guess_chat_type(message, self._account_id)
        source = SessionSource(
            platform="weixin",
            chat_id=effective_chat_id,
            user_id=sender_id,
            user_name=sender_id,  # no display names on this API
            chat_type=chat_type,
            thread_id=None,
        )
        # The Gateway owns delivery authorization, but side effects (context-token
        # persistence, media download/decrypt to disk) must not be spent on senders
        # the allowlist will park — any WeChat user who finds the bot could
        # otherwise fill the disk before ever being allowed.
        authorized = self._auth_check is None or self._auth_check(source)

        media_notes: list[str] = []
        if authorized:
            # Store the inbound context token — outbound sends echo it (session
            # freshness). Not-yet-allowed senders fall back to tokenless sends
            # (accepted as degraded) if the user later allow-and-delivers.
            context_token = str(message.get("context_token") or "").strip()
            if context_token:
                self._state.set_context_token(
                    self._account_id, sender_id, context_token
                )
            for item in item_list:
                await self._collect_media(item, media_notes)
                ref_item = (item.get("ref_msg") or {}).get("message_item")
                if isinstance(ref_item, dict):
                    # Quoted media is downloaded too.
                    await self._collect_media(ref_item, media_notes)
        elif self._has_downloadable_media(item_list):
            media_notes.append("[发送者未授权，附件未下载]")
        if media_notes:
            text = (text + "\n" if text else "") + "\n".join(media_notes)
        if not text:
            return

        event = MessageEvent(text=text, source=source, message_id=message_id or None)
        if media_notes:
            await self._dispatch(event)  # media-bearing: dispatch immediately
        else:
            self._enqueue_text_event(event)

    @staticmethod
    def _has_downloadable_media(item_list: list) -> bool:
        """True when any item would trigger a media download (mirrors _collect_media:
        image/video/file always; voice only when it carries actual audio media)."""
        for item in item_list:
            item_type = item.get("type")
            if item_type in (ITEM_IMAGE, ITEM_VIDEO, ITEM_FILE):
                return True
            if item_type == ITEM_VOICE:
                media = (item.get("voice_item") or {}).get("media") or {}
                if media.get("encrypt_query_param") or media.get("full_url"):
                    return True
        return False

    # -- text debounce ----------------------------------------------------------
    def _batch_key(self, event: MessageEvent) -> str:
        return f"{event.source.chat_id}:{event.source.user_id}"

    def _enqueue_text_event(self, event: MessageEvent) -> None:
        """Buffer a text event and reset the flush timer (fragments join with \\n)."""
        key = self._batch_key(event)
        chunk_len = len(event.text or "")
        existing = self._pending_batches.get(key)
        if existing is None:
            self._pending_batches[key] = event
        else:
            existing.text = (
                f"{existing.text}\n{event.text}" if existing.text else event.text
            )
        self._pending_last_len[key] = chunk_len
        prior = self._batch_tasks.get(key)
        if prior is not None and not prior.done():
            if existing is not None:
                # Sleep phase: the buffer entry still exists, so the prior flush
                # has not reached its commit point — cancel to re-arm the timer.
                prior.cancel()
            else:
                # Past the commit point: the prior flush already popped its batch
                # and is awaiting handle_message. Cancelling now would abort the
                # dispatch mid-flight and lose the aggregated text — let it finish,
                # tracked in _msg_tasks so disconnect() can still cancel it.
                self._msg_tasks.add(prior)
                prior.add_done_callback(self._msg_tasks.discard)
        self._batch_tasks[key] = asyncio.create_task(self._flush_text_batch(key))

    async def _flush_text_batch(self, key: str) -> None:
        """Wait for the quiet period, then dispatch the aggregated text as ONE event.
        A near-limit last fragment means iLink probably split a long message — wait
        longer for the continuation."""
        current = asyncio.current_task()
        try:
            delay = (
                self._batch_split_delay
                if self._pending_last_len.get(key, 0) >= SPLIT_THRESHOLD
                else self._batch_delay
            )
            await asyncio.sleep(delay)
            if self._batch_tasks.get(key) is not current:
                return  # superseded by a newer fragment
            event = self._pending_batches.pop(key, None)
            self._pending_last_len.pop(key, None)
            if event is not None:
                await self._dispatch(event)
        finally:
            if self._batch_tasks.get(key) is current:
                self._batch_tasks.pop(key, None)

    # -- inbound media ----------------------------------------------------------
    async def _collect_media(self, item: dict, notes: list[str]) -> None:
        """Download + decrypt one media item into the local cache and append a
        Chinese note the agent can act on. Failures are logged and noted — a broken
        attachment never drops the message."""
        item_type = item.get("type")
        if item_type == ITEM_IMAGE:
            await self._save_media(
                item, "image_item", notes, ext=".jpg", timeout_s=30.0
            )
        elif item_type == ITEM_VIDEO:
            await self._save_media(
                item, "video_item", notes, ext=".mp4", timeout_s=120.0
            )
        elif item_type == ITEM_FILE:
            file_item = item.get("file_item") or {}
            filename = str(file_item.get("file_name") or "document.bin")
            ext = "." + filename.rsplit(".", 1)[1] if "." in filename else ".bin"
            await self._save_media(
                item, "file_item", notes, ext=ext, timeout_s=60.0, filename=filename
            )
        elif item_type == ITEM_VOICE:
            media = (item.get("voice_item") or {}).get("media") or {}
            if not (media.get("encrypt_query_param") or media.get("full_url")):
                return  # transcript-only voice: nothing to download
            # Saved ALONGSIDE the transcript, which extract_text now always prefers
            # when Tencent supplies one. Nothing here decodes SILK, so the audio is
            # a keepsake for the user, not something the agent can read.
            await self._save_media(
                item, "voice_item", notes, ext=".silk", timeout_s=60.0
            )

    async def _save_media(
        self,
        item: dict,
        key: str,
        notes: list[str],
        *,
        ext: str,
        timeout_s: float,
        filename: Optional[str] = None,
    ) -> None:
        media = (item.get(key) or {}).get("media") or {}
        try:
            aes_key = (
                image_aes_key(item)
                if key == "image_item"
                else (
                    parse_aes_key(str(media["aes_key"]))
                    if media.get("aes_key")
                    else None
                )
            )
            data = await self._download_media_bytes(media, timeout_s)
            path = self._state.media_dir() / f"{uuid.uuid4().hex}{_safe_ext(ext)}"
            # Decrypt (CPU-bound) + write off the event loop — a large video would
            # otherwise stall every poll and route in the process for seconds.
            await asyncio.to_thread(_decrypt_and_write, data, aes_key, path)
            if filename:
                notes.append(f"[文件 {filename} 已保存: {path}]")
            else:
                notes.append(f"[附件已保存: {path}]")
        except RuntimeError as exc:
            # The AES helpers raise "cryptography is required…" when the optional
            # dep is missing — degrade with a hint instead of failing the message.
            if "cryptography" in str(exc):
                logger.warning(
                    "weixin: encrypted media received but cryptography is not "
                    "installed — `pip install coworker[messaging]`"
                )
                if _CRYPTOGRAPHY_NOTE not in notes:
                    notes.append(_CRYPTOGRAPHY_NOTE)
            else:
                logger.warning("weixin: media download failed: %s", exc)
                notes.append("[附件下载失败]")
        except Exception as exc:
            logger.warning("weixin: media download failed: %s", exc)
            notes.append("[附件下载失败]")

    async def _download_media_bytes(self, media: dict, timeout_s: float) -> bytes:
        eqp = media.get("encrypt_query_param")
        if eqp:
            # Constructed URLs are trusted: the host is the configured CDN base.
            url = cdn_download_url(WEIXIN_CDN_BASE_URL, str(eqp))
        elif media.get("full_url"):
            url = str(media["full_url"])
            assert_weixin_cdn_url(url)  # SSRF guard for server-supplied URLs
        else:
            raise RuntimeError("media item had neither encrypt_query_param nor full_url")
        assert self._client is not None
        # Stream with a hard size cap: resp.content on an unbounded body is a
        # memory DoS handed to whoever can DM the bot.
        chunks: list[bytes] = []
        total = 0
        async with self._client.stream("GET", url, timeout=timeout_s) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > _MAX_MEDIA_BYTES:
                raise RuntimeError(f"media too large ({declared} bytes)")
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_MEDIA_BYTES:
                    raise RuntimeError("media exceeds the 50 MB cap")
                chunks.append(chunk)
        return b"".join(chunks)
