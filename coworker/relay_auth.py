"""Sign-in to the company Gemini relay with Cloudflare Access One-time PIN.

Signing in establishes WHO you are, not what you may spend. The colleague proves they own an
allow-listed mailbox — Cloudflare emails them a one-time PIN — and the relay hands back a
token that is only good against the relay. They separately carry a Gemini API key issued to
them by the administrator; the token is what lets the relay attribute and cap usage per
person (`worker/src/quota.ts`).

The token lands in the `provider:gemini` secret profile under `relay_token`, deliberately
NOT in `api_key`: that slot holds their Gemini key, which the SDK sends as
`x-goog-api-key` and the relay forwards untouched.

Shape (mirrors `cloud.py`'s Auth0 flow, and RFC 8252 for native apps):

    begin_login()       POST {relay}/auth/session   -> {sid, login_url}; opens the browser
    <the browser>       GET  {relay}/login/<sid>    -> Access OTP -> 302 to our loopback
    deliver_callback()  POST {relay}/auth/token     -> {token, email, ...}; stored

Two things keep the loopback leg honest. The relay only ever redirects to
`http://127.0.0.1:<port>/relay/callback`, so the authorization code never leaves this
machine; and PKCE binds the exchange to this process, so another local program that raced us
to the loopback port still cannot redeem the code without our verifier.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets as _secrets
import time
from typing import Any, Optional

import httpx

from .config import Config
from .secrets import SecretStore

#: Where the relay token is kept — the Gemini profile, alongside (never instead of) the
#: person's own `api_key`. `gemini_provider.resolve_relay_token` is the reader.
PROFILE = "provider:gemini"
TOKEN_FIELD = "relay_token"

#: Relay tokens are prefixed by the Worker so they are never confused with a Google
#: `AIza...` key. Kept in sync with `TOKEN_PREFIX` in gemini-relay/worker/src/auth.ts.
TOKEN_PREFIX = "owr_"

_CALLBACK_PATH = "/relay/callback"
_PENDING_TTL = 15 * 60  # a login the user walked away from stops being redeemable
_HTTP_TIMEOUT = 20.0

# sid -> {"verifier": str, "created": float}. In-process only: the browser round trip
# finishes against this same sidecar, and a restart mid-login should invalidate the attempt.
_pending_logins: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _relay_base_url() -> str:
    from .providers.gemini_provider import resolve_base_url

    return resolve_base_url(None)


def _loopback_callback(config: Config) -> str:
    # The packaged desktop shell binds the sidecar to a RANDOM free port and publishes it as
    # COWORKER_PORT; config.port is only right in dev. Same lookup as cloud.py — getting this
    # wrong shipped once as "Firefox can't connect to 127.0.0.1:8765".
    port = os.environ.get("COWORKER_PORT") or config.port
    return f"http://127.0.0.1:{port}{_CALLBACK_PATH}"


def _prune_pending() -> None:
    for sid, pending in list(_pending_logins.items()):
        if float(pending["created"]) < _now() - _PENDING_TTL:
            _pending_logins.pop(sid, None)


def _profile(secrets: SecretStore) -> dict[str, Any]:
    return dict(secrets.get(PROFILE) or {})


# ---------------------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------------------


def begin_login(config: Config) -> dict[str, Any]:
    """Reserve a login session on the relay and return the URL the browser should open."""
    verifier = _b64url(_secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    relay = _relay_base_url()

    try:
        response = httpx.post(
            relay + "/auth/session",
            json={"callback": _loopback_callback(config), "challenge": challenge},
            timeout=_HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"连不上中转 {relay}：{exc}"}

    if response.status_code != 200:
        return {"ok": False, "error": _relay_error(response)}

    payload = response.json()
    sid = payload.get("sid") or ""
    login_url = payload.get("login_url") or ""
    if not sid or not login_url:
        return {"ok": False, "error": "中转返回的登录会话不完整"}

    _prune_pending()
    _pending_logins[sid] = {"verifier": verifier, "created": _now()}
    return {"ok": True, "login_url": login_url, "sid": sid, "relay": relay}


def deliver_callback(secrets: SecretStore, code: str, state: str) -> dict[str, Any]:
    """Redeem the one-time code the browser just handed to our loopback, and store the token.

    `state` is the sid we opened the browser with; matching it is what tells us this callback
    belongs to a login *we* started rather than one a stray tab is replaying.
    """
    _prune_pending()
    pending = _pending_logins.pop(state, None)
    if pending is None:
        return {"ok": False, "error": "登录会话已过期或不属于这次登录，请重新点一次登录"}
    if not code:
        return {"ok": False, "error": "中转没有返回授权码"}

    relay = _relay_base_url()
    try:
        response = httpx.post(
            relay + "/auth/token",
            json={"code": code, "verifier": pending["verifier"]},
            timeout=_HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"连不上中转 {relay}：{exc}"}

    if response.status_code != 200:
        return {"ok": False, "error": _relay_error(response)}

    payload = response.json()
    token = payload.get("token") or ""
    if not token.startswith(TOKEN_PREFIX):
        return {"ok": False, "error": "中转返回的令牌格式不对"}

    # Read-modify-write: `put` replaces the whole profile, and both the person's own
    # `api_key` and a hidden `base_url` override may be sitting in there
    # (registry._build_gemini reads the latter).
    profile = _profile(secrets)
    profile.update(
        {
            TOKEN_FIELD: token,
            "relay_email": payload.get("email") or "",
            "relay_name": payload.get("name") or "",
            "relay_dept": payload.get("dept") or "",
            "relay_role": payload.get("role") or "",
            "relay_expires_at": payload.get("expires_at") or "",
            "relay_base_url": relay,
        }
    )
    secrets.put(PROFILE, profile)

    return {
        "ok": True,
        "email": profile["relay_email"],
        "name": profile["relay_name"],
        "dept": profile["relay_dept"],
        "role": profile["relay_role"],
    }


def status(secrets: SecretStore, verify: bool = False) -> dict[str, Any]:
    """Current sign-in state.

    Local by default — this is polled to render the settings pane. `verify=True` additionally
    asks the relay whether the token is still live, which is the only way to notice that an
    admin removed the person from the roster (their token stays on disk either way).
    """
    profile = _profile(secrets)
    token = (profile.get(TOKEN_FIELD) or "").strip()
    relay = _relay_base_url()
    signed_in = token.startswith(TOKEN_PREFIX)

    out: dict[str, Any] = {
        "signed_in": signed_in,
        "email": profile.get("relay_email") or "",
        "name": profile.get("relay_name") or "",
        "dept": profile.get("relay_dept") or "",
        "role": profile.get("relay_role") or "",
        "expires_at": profile.get("relay_expires_at") or "",
        "relay": relay,
        # Signing in is only half the setup — the relay refuses a signed-in caller who has
        # not supplied their own Google key. The UI needs to be able to say which half is
        # missing instead of showing a green tick next to something that will 400.
        "has_api_key": bool(_own_api_key(secrets)),
        # The token is bound to the relay that issued it. If GOOGLE_GEMINI_BASE_URL is
        # pointing somewhere else today, say so rather than letting it fail as a 401.
        "stale_relay": bool(
            signed_in and profile.get("relay_base_url") and profile["relay_base_url"] != relay
        ),
    }
    if not (signed_in and verify):
        return out

    try:
        response = httpx.get(
            relay + "/auth/whoami",
            headers={"authorization": "Bearer " + token},
            timeout=_HTTP_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - a status endpoint must degrade, never 500.
        # Not just httpx.HTTPError: a SOCKS proxy env without socksio raises ImportError
        # from inside httpx (2026-08-28), and that used to take the whole pane down.
        out["verify_error"] = f"连不上中转 {relay}：{exc}"
        return out

    if response.status_code == 200:
        live = response.json()
        # Refresh the cached display fields — a rename or a department move shows up here.
        out.update(
            {
                "email": live.get("email") or out["email"],
                "name": live.get("name") or "",
                "dept": live.get("dept") or "",
                "role": live.get("role") or "",
                # Today's counters against today's ceilings, straight from the relay: it is
                # the only thing that actually knows, and seeing the number beats meeting it.
                "quota": live.get("quota") or None,
            }
        )
        return out

    # 401/403: the token is expired, revoked, or its owner left the roster. Drop it so the UI
    # shows a plain "signed out" instead of a credential that will 403 on every message.
    if response.status_code in (401, 403):
        _clear_token(secrets)
        return {
            "signed_in": False,
            "email": "",
            "name": "",
            "dept": "",
            "role": "",
            "expires_at": "",
            "relay": relay,
            "has_api_key": out["has_api_key"],
            "stale_relay": False,
            "verify_error": "登录已失效（过期、被吊销，或已不在允许名单里），请重新登录",
        }

    out["verify_error"] = _relay_error(response)
    return out


def logout(secrets: SecretStore) -> dict[str, Any]:
    """Drop the login here and, best effort, on the relay too. The person's own Gemini key
    is theirs and stays put — signing out is not the same as throwing a credential away."""
    profile = _profile(secrets)
    token = (profile.get(TOKEN_FIELD) or "").strip()
    relay = _relay_base_url()

    if token.startswith(TOKEN_PREFIX):
        try:
            httpx.post(
                relay + "/auth/logout",
                headers={"authorization": "Bearer " + token},
                timeout=_HTTP_TIMEOUT,
            )
        except httpx.HTTPError:
            # The local credential is what actually matters; a stranded server-side token
            # expires on its own in 30 days. Never block sign-out on the network.
            pass

    _clear_token(secrets)
    return {"ok": True}


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _own_api_key(secrets: SecretStore) -> str:
    """The person's own Gemini key, wherever it lives — resolved through the provider so the
    UI cannot claim a key is missing on a machine that will happily make calls."""
    from .providers.gemini_provider import resolve_api_key

    return (resolve_api_key(secrets) or "").strip()


def _clear_token(secrets: SecretStore) -> None:
    """Sign out: the login token and everything derived from it. `api_key` is untouched."""
    profile = _profile(secrets)
    for key in (
        TOKEN_FIELD,
        "relay_email",
        "relay_name",
        "relay_dept",
        "relay_role",
        "relay_expires_at",
        "relay_base_url",
    ):
        profile.pop(key, None)
    if profile:
        secrets.put(PROFILE, profile)  # keeps the person's own key and any base_url override
    else:
        secrets.delete(PROFILE)


def _relay_error(response: httpx.Response) -> str:
    """The relay answers JSON `{"error": ...}` on its auth routes; fall back to the body."""
    detail: Optional[str] = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            detail = parsed.get("error")
    except ValueError:
        pass
    if not detail:
        detail = (response.text or "").strip()[:200]
    return f"中转返回 {response.status_code}：{detail or '(无正文)'}"
