"""Weixin (personal WeChat, iLink Bot API) QR login flow.

Non-interactive port of Hermes' `qr_login` (read-only ref): instead of printing to a
terminal, the flow mutates one `QrLoginState` and calls `on_state` after every change so
the server can serve snapshots to a polling GUI (`/v1/connectors/weixin/qr-status`).

Flow: fetch a QR from the default iLink host, render it as a PNG data URI (segno),
then poll `get_qrcode_status` once a second until the user scans + confirms on their
phone. A `scaned_but_redirect` status silently moves polling to the per-account host;
an `expired` status refreshes the QR (from the DEFAULT host, max 3 times). On
`confirmed` the credentials are returned to the caller — the caller persists them and
flips the state to "confirmed" only after that, so the GUI never sees "confirmed"
before the profile exists.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

from .weixin_protocol import (
    EP_GET_BOT_QR,
    EP_GET_QR_STATUS,
    ILINK_BASE_URL,
    QR_TIMEOUT_S,
    api_get,
)

logger = logging.getLogger("coworker.connectors")

_MAX_QR_REFRESHES = 3


@dataclass
class QrLoginState:
    """Snapshot of one QR login session, served verbatim to the GUI's 1 s poll."""

    state: str = "starting"  # starting|waiting_scan|scanned|confirmed|failed
    qr_data_uri: str | None = None
    error: str | None = None
    account: str | None = None
    refreshes: int = 0


def _qr_data_uri(url: str) -> Optional[str]:
    """Render the scannable liteapp URL as a PNG data URI (segno, pure python).
    Best-effort: None on failure — the GUI shows the placeholder instead."""
    try:
        import segno

        return segno.make(url).png_data_uri(scale=6)
    except Exception:
        logger.warning("weixin: QR render failed", exc_info=True)
        return None


async def qr_login_flow(
    on_state: Callable[[QrLoginState], None],
    *,
    bot_type: str = "3",
    timeout_seconds: int = 480,
) -> Optional[dict]:
    """Run the QR login. Returns `{"account_id","token","base_url","user_id"}` on
    success, None on failure/timeout (the state is flagged "failed" first).

    The caller writes the SecretStore profile + runtime state and then sets the
    state to "confirmed" — this flow never emits "confirmed" itself.
    """
    state = QrLoginState()
    on_state(state)

    def _fail(error: str) -> None:
        state.state = "failed"
        state.error = error
        on_state(state)

    async with httpx.AsyncClient() as client:
        try:
            qr_resp = await api_get(
                client,
                base_url=ILINK_BASE_URL,
                endpoint=f"{EP_GET_BOT_QR}?bot_type={bot_type}",
                timeout_s=QR_TIMEOUT_S,
            )
        except Exception as exc:
            logger.error("weixin: failed to fetch QR code: %s", exc)
            _fail(f"failed to fetch QR code: {exc}")
            return None

        qrcode_value = str(qr_resp.get("qrcode") or "")
        qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
        if not qrcode_value:
            _fail("QR response missing qrcode")
            return None

        # qrcode_img_content is the full scannable liteapp URL; qrcode is just the
        # hex token used for status polling. WeChat must scan the full URL.
        state.qr_data_uri = _qr_data_uri(qrcode_url or qrcode_value)
        state.state = "waiting_scan"
        on_state(state)

        deadline = time.monotonic() + timeout_seconds
        current_base_url = ILINK_BASE_URL
        refresh_count = 0

        while time.monotonic() < deadline:
            try:
                status_resp = await api_get(
                    client,
                    base_url=current_base_url,
                    endpoint=f"{EP_GET_QR_STATUS}?qrcode={qrcode_value}",
                    timeout_s=QR_TIMEOUT_S,
                )
            except Exception as exc:
                logger.warning("weixin: QR poll error: %s", exc)
                await asyncio.sleep(1)
                continue

            status = str(status_resp.get("status") or "wait")
            if status == "scaned":
                if state.state != "scanned":
                    state.state = "scanned"
                    on_state(state)
            elif status == "scaned_but_redirect":
                # Per-account host handoff — internal, no state change for the GUI.
                redirect_host = str(status_resp.get("redirect_host") or "")
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
            elif status == "expired":
                refresh_count += 1
                if refresh_count > _MAX_QR_REFRESHES:
                    _fail("QR code expired too many times — start again")
                    return None
                # Refresh always goes to the DEFAULT host, not any redirect host.
                try:
                    qr_resp = await api_get(
                        client,
                        base_url=ILINK_BASE_URL,
                        endpoint=f"{EP_GET_BOT_QR}?bot_type={bot_type}",
                        timeout_s=QR_TIMEOUT_S,
                    )
                except Exception as exc:
                    logger.error("weixin: QR refresh failed: %s", exc)
                    _fail(f"QR refresh failed: {exc}")
                    return None
                qrcode_value = str(qr_resp.get("qrcode") or "")
                qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
                if not qrcode_value:
                    _fail("QR refresh response missing qrcode")
                    return None
                state.qr_data_uri = _qr_data_uri(qrcode_url or qrcode_value)
                state.refreshes = refresh_count
                state.state = "waiting_scan"
                on_state(state)
            elif status == "confirmed":
                account_id = str(status_resp.get("ilink_bot_id") or "")
                token = str(status_resp.get("bot_token") or "")
                base_url = str(status_resp.get("baseurl") or ILINK_BASE_URL)
                user_id = str(status_resp.get("ilink_user_id") or "")
                if not account_id or not token:
                    _fail("QR confirmed but credential payload was incomplete")
                    return None
                logger.info("weixin: QR login confirmed account=%s…", account_id[:8])
                return {
                    "account_id": account_id,
                    "token": token,
                    "base_url": base_url,
                    "user_id": user_id,
                }
            # "wait" and anything unknown: keep polling.
            await asyncio.sleep(1)

    _fail("QR login timed out")
    return None
