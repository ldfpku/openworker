"""Sign in to the Cloudflare AI Gateway with Access Managed OAuth.

This replaces the two-step chore the gateway provider shipped with: run `cloudflared
access login`, paste the JWT it prints into Settings — and do it again tomorrow, because
that session lasts a day. Here the colleague presses one button, proves who they are in
the browser, and the token renews itself silently for a fortnight. Nothing to install,
nothing to paste, no Cloudflare credential of their own.

Signing in settles WHO you are, not what you may spend. It is the same identity the
gateway stamps onto every request as `cf.user_id`, which is what drives per-person usage
and per-person budgets — so the login is also the accounting.

Shape (RFC 8252 native app + RFC 7636 PKCE + RFC 8707 resource indicators):

    begin_login()   discovery -> DCR (once ever) -> open the browser at Access
    <the browser>   Access login -> 302 to our loopback
    _redeem()       code + verifier -> {access_token, refresh_token}; stored
    access_token()  what the provider calls on every request; refreshes before expiry

Three properties of Cloudflare's authorization server shaped this file. All three were
measured against the live endpoint on 2026-08-23, and two of them are traps:

  * **Redirect URIs match exactly, port included.** RFC 8252 §7.3 says a loopback
    redirect must be honoured on any port. Cloudflare does not do that: a client
    registered for `127.0.0.1:53682` authorizes (302 to the login page) while
    `127.0.0.1:59999` is a flat 400. That rules out hosting the callback on the sidecar
    the way `relay_auth.py` does, because the packaged desktop shell binds the sidecar to
    a RANDOM free port — every sign-in would land on a new port and need a new client
    registration, and Cloudflare offers no way to list or delete one, so each would be
    litter nobody can sweep up. Instead we register ONCE against a fixed list of
    candidate ports and run a one-shot loopback listener on whichever is free.
  * **`resource` is mandatory.** Managed OAuth is RFC 8707-gated; the authorize call and
    both token calls have to name the gateway they are for.
  * **The token rides `Authorization: Bearer`.** That is what the challenge asks for
    (`WWW-Authenticate: Bearer realm="OAuth"`), and it is a different slot from the
    pasted-JWT path's `cf-access-token`. Access accepts either; each credential travels
    in the header its own protocol specifies.

The pasted-session path is deliberately left working. Signing in is strictly better, but
a colleague mid-migration — or anyone on a machine that cannot open a browser — still has
the old route, and `resolve_settings` keeps preferring whatever is actually present.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import logging
import os
import secrets as _secrets
import threading
import time
import urllib.parse
from typing import Any, Optional

import httpx

from .secrets import SecretStore

logger = logging.getLogger(__name__)

#: The gateway provider's profile. The OAuth state is a nested dict inside it so it can
#: never collide with `base_url`, the legacy pasted `access_token`, or `thinking_budget`.
PROFILE = "provider:aigw"
OAUTH_FIELD = "oauth"

CLIENT_NAME = "OpenWorker"
CALLBACK_PATH = "/aigw/callback"

#: Fixed because Cloudflare pins the redirect URI down to the port (see module docstring).
#: Registered together, so any one of them can serve a given sign-in and the registration
#: survives for the life of the install. Four is enough to dodge a busy port without
#: turning a stuck flow into a long retry loop.
CALLBACK_PORTS = (53682, 53683, 53684, 53685)

#: How long the loopback listener waits for the person to finish in the browser.
FLOW_TIMEOUT_SECONDS = 300
_HTTP_TIMEOUT = 20.0

#: Renew this far ahead of the stated expiry. Access tokens are minted for 15 minutes, so
#: a two-minute skew keeps a long streaming call from expiring in flight without
#: refreshing on almost every request.
_REFRESH_SKEW_SECONDS = 120

# One interactive sign-in at a time — the flow is driven by a human at a browser, so
# concurrency here would only mean two tabs fighting over one listener.
_flow_lock = threading.Lock()
#: Separate from `_flow_lock` on purpose: a silent refresh is a network call on the request
#: path, and sharing one lock would let it stall an arriving browser callback (and the
#: reverse) for as long as the other side's HTTP timeout.
_refresh_lock = threading.Lock()
_pending: Optional[dict[str, Any]] = None
#: Why the last flow failed, surfaced by `status()` so the pane can say more than
#: "still not signed in" after the browser tab has already been closed.
_last_error: str = ""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------------------
# Stored state
# ---------------------------------------------------------------------------------------


def _profile(secrets: SecretStore) -> dict[str, Any]:
    return dict(secrets.get(PROFILE) or {})


def _state(secrets: SecretStore) -> dict[str, Any]:
    raw = _profile(secrets).get(OAUTH_FIELD)
    return dict(raw) if isinstance(raw, dict) else {}


def _save_state(secrets: SecretStore, patch: dict[str, Any]) -> dict[str, Any]:
    """Read-modify-write, twice over: `put` replaces the whole profile, and the OAuth
    sub-dict has to merge rather than replace so a refresh never drops the registration."""
    profile = _profile(secrets)
    merged = {**_state(secrets), **patch}
    profile[OAUTH_FIELD] = merged
    secrets.put(PROFILE, profile)
    return merged


# ---------------------------------------------------------------------------------------
# Discovery and registration
# ---------------------------------------------------------------------------------------


def _discover(base_url: str) -> dict[str, str]:
    """Protected-resource metadata on the gateway, then the authorization server's own.

    Both documents are public and unauthenticated — this is the part of the flow that
    works before anybody has signed in to anything.
    """
    from .providers.aigateway_provider import normalise_base

    origin = normalise_base(base_url)
    if not origin:
        raise RuntimeError("没有网关地址，先在 设置 ▸ 模型 里填上再登录。")

    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        resource_doc = client.get(origin + "/.well-known/oauth-protected-resource")
        if resource_doc.status_code != 200:
            raise RuntimeError(
                f"{origin} 没有提供 OAuth 元数据（HTTP {resource_doc.status_code}）——"
                "这个网关可能还没开启托管 OAuth，找管理员确认。"
            )
        resource_meta = resource_doc.json()
        servers = resource_meta.get("authorization_servers") or []
        if not servers:
            raise RuntimeError("网关没有声明授权服务器，无法登录。")
        issuer = str(servers[0]).rstrip("/")

        server_doc = client.get(issuer + "/.well-known/oauth-authorization-server")
        if server_doc.status_code != 200:
            raise RuntimeError(
                f"取不到 {issuer} 的授权服务器元数据（HTTP {server_doc.status_code}）。"
            )
        meta = server_doc.json()

    missing = [
        k
        for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint")
        if not meta.get(k)
    ]
    if missing:
        raise RuntimeError(
            "授权服务器缺少必要的端点：" + "、".join(missing) + "。"
            "多半是管理员还没打开动态客户端注册。"
        )

    return {
        "resource": str(resource_meta.get("resource") or origin),
        "issuer": issuer,
        "authorization_endpoint": str(meta["authorization_endpoint"]),
        "token_endpoint": str(meta["token_endpoint"]),
        "registration_endpoint": str(meta["registration_endpoint"]),
        "revocation_endpoint": str(meta.get("revocation_endpoint") or ""),
    }


def _redirect_uris() -> list[str]:
    return [f"http://127.0.0.1:{port}{CALLBACK_PATH}" for port in CALLBACK_PORTS]


def _ensure_client(secrets: SecretStore, meta: dict[str, str]) -> str:
    """The DCR client id, registering one the first time and never again.

    Re-registering is not merely wasteful: a registered client cannot be listed or deleted
    through any Cloudflare API, so a flow that registered per sign-in would leave a
    permanent trail of dead clients on the Access app. The stored id is therefore reused
    until the issuer or our port list changes, which is the only way it can go stale.
    """
    # Endpoints are re-persisted on every sign-in, cached client or not: `_refresh` reads
    # the token endpoint and resource straight out of storage, so a server that moved one
    # of them would otherwise keep refreshing against the stale address forever.
    state = _save_state(secrets, dict(meta))
    fingerprint = meta["issuer"] + "|" + ",".join(_redirect_uris())
    if state.get("client_id") and state.get("client_fingerprint") == fingerprint:
        return str(state["client_id"])

    response = httpx.post(
        meta["registration_endpoint"],
        json={
            "client_name": CLIENT_NAME,
            "redirect_uris": _redirect_uris(),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            # Public client: a desktop app cannot keep a secret, and the server offers
            # `none` as an auth method precisely for this case.
            "token_endpoint_auth_method": "none",
        },
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": _user_agent()},
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"注册客户端失败（HTTP {response.status_code}）：{response.text[:200]}"
        )
    client_id = str(response.json().get("client_id") or "")
    if not client_id:
        raise RuntimeError("授权服务器没有返回 client_id。")

    _save_state(secrets, {"client_id": client_id, "client_fingerprint": fingerprint})
    return client_id


def _user_agent() -> str:
    from .providers.aigateway_provider import _user_agent as ua

    return ua()


# ---------------------------------------------------------------------------------------
# The loopback leg
# ---------------------------------------------------------------------------------------


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot landing for the browser redirect. Serves exactly our callback path."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)

        def one(key: str) -> str:
            values = params.get(key) or []
            return values[0] if values else ""

        title, detail, error = _complete(one("code"), one("state"), one("error"))
        body = _page(title, detail, error)
        self.send_response(200 if not error else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        # The stdlib default writes an access log to stderr, which in the packaged app is
        # the user's log file. Nothing here is worth a line there.
        return


def _page(title: str, detail: str, error: str) -> bytes:
    """The branded card the person lands on. Reuses the sidecar's own page builder so this
    tail looks like every other loopback flow in the app; imported late because the server
    module pulls in most of the application."""
    try:
        from .server.app import _browser_page

        html = _browser_page(title, detail, ok=not error, error=error, company=True)
    except Exception:  # pragma: no cover - only if the server module cannot import
        html = f"<!doctype html><meta charset=utf-8><h1>{title}</h1><p>{detail}</p>"
    return html.encode("utf-8")


def _complete(code: str, state: str, error: str) -> tuple[str, str, str]:
    """Redeem the code the browser just handed us. Returns (title, detail, error)."""
    global _pending, _last_error

    failed_detail = "关掉这个标签页，回 OpenWorker 重新点一次「登录」。"
    with _flow_lock:
        pending = _pending
        # Matching `state` is what says this callback belongs to the sign-in *we* started
        # rather than a stray tab replaying an old one. A mismatch leaves the real flow
        # waiting rather than consuming it.
        if pending is None or not state or not _secrets.compare_digest(
            state, str(pending["state"])
        ):
            return ("登录失败", failed_detail, "这次回调不属于正在进行的登录")
        _pending = None

    if error:
        _last_error = error
        return ("登录失败", failed_detail, error)
    if not code:
        _last_error = "授权服务器没有返回授权码"
        return ("登录失败", failed_detail, _last_error)

    try:
        _redeem(pending, code)
    except Exception as exc:  # noqa: BLE001 - surfaced to the browser and the pane
        _last_error = str(exc)
        logger.warning("aigw oauth: token exchange failed: %s", exc)
        return ("登录失败", failed_detail, str(exc))

    _last_error = ""
    return ("登录成功", "可以关掉这个标签页，回 OpenWorker 继续。", "")


def _redeem(pending: dict[str, Any], code: str) -> None:
    secrets_store: SecretStore = pending["secrets"]
    meta: dict[str, str] = pending["meta"]
    response = httpx.post(
        meta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending["redirect_uri"],
            "client_id": pending["client_id"],
            "code_verifier": pending["verifier"],
            "resource": meta["resource"],
        },
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": _user_agent()},
    )
    if response.status_code != 200:
        raise RuntimeError(f"换取令牌失败（HTTP {response.status_code}）：{response.text[:200]}")
    _store_tokens(secrets_store, response.json())


def _store_tokens(secrets: SecretStore, payload: dict[str, Any]) -> dict[str, Any]:
    access = str(payload.get("access_token") or "")
    if not access:
        raise RuntimeError("授权服务器没有返回访问令牌。")
    try:
        lifetime = int(payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        lifetime = 0
    patch: dict[str, Any] = {
        "access_token": access,
        "expires_at": _now() + lifetime if lifetime > 0 else 0,
        "obtained_at": _now(),
    }
    # A refresh response may legitimately omit the refresh token, meaning "keep using the
    # one you have". Overwriting it with "" there would end the two-week grant early.
    refresh = str(payload.get("refresh_token") or "")
    if refresh:
        patch["refresh_token"] = refresh
    return _save_state(secrets, patch)


def _serve(port: int) -> http.server.HTTPServer:
    # 127.0.0.1, never 0.0.0.0: the authorization code must not be reachable from the
    # network, and Cloudflare only ever redirects to a loopback address anyway.
    return http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)


def _bind_listener() -> tuple[http.server.HTTPServer, int]:
    last: Optional[OSError] = None
    for port in CALLBACK_PORTS:
        try:
            return _serve(port), port
        except OSError as exc:
            last = exc
    raise RuntimeError(
        "本机 " + "、".join(str(p) for p in CALLBACK_PORTS) + " 端口都被占用了，"
        "关掉占用的程序再试。"
    ) from last


# ---------------------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------------------


def begin_login(secrets: SecretStore, base_url: str = "") -> dict[str, Any]:
    """Start a sign-in and return the URL the browser should open.

    Returns immediately; the loopback listener finishes the exchange on its own thread and
    the pane polls `status()`. That mirrors the relay sign-in, and it means a person who
    abandons the browser tab costs nothing but one idle thread for five minutes.
    """
    global _pending, _last_error

    if not base_url:
        base_url = str(_profile(secrets).get("base_url") or "").strip()
    if not base_url:
        base_url = os.environ.get("CLOUDFLARE_AIGW_BASE_URL", "").strip()

    try:
        meta = _discover(base_url)
        client_id = _ensure_client(secrets, meta)
        server, port = _bind_listener()
    except Exception as exc:  # noqa: BLE001 - the pane shows this verbatim
        _last_error = str(exc)
        return {"ok": False, "error": str(exc)}

    verifier = _b64url(_secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(_secrets.token_bytes(24))
    redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"

    with _flow_lock:
        _pending = {
            "state": state,
            "verifier": verifier,
            "meta": meta,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "secrets": secrets,
        }
    _last_error = ""

    def run() -> None:
        global _pending
        # Keep serving until the flow is actually resolved, NOT until the first request
        # arrives. `handle_request()` answers exactly one caller, so a single stray hit on
        # the loopback port would otherwise close the listener and strand the real
        # sign-in — the state check would correctly reject that hit and the person would
        # still be locked out, which is the very denial-of-service the check exists to
        # stop. Measured 2026-08-23: one bogus `?error=probe&state=wrong` ended the flow.
        # `_complete` clears `_pending` only on a callback whose state matches, so looping
        # on that condition means bad callers get their 400 and are simply ignored.
        deadline = _now() + FLOW_TIMEOUT_SECONDS
        server.timeout = 1.0  # short, so the deadline is re-checked while idle
        try:
            while _now() < deadline:
                with _flow_lock:
                    if _pending is None or _pending["state"] != state:
                        break  # redeemed, refused by the user, or superseded
                server.handle_request()
        finally:
            server.server_close()
            with _flow_lock:
                if _pending is not None and _pending["state"] == state:
                    _pending = None

    threading.Thread(target=run, name="aigw-oauth-callback", daemon=True).start()

    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # RFC 8707. Managed OAuth refuses the request without it.
            "resource": meta["resource"],
        }
    )
    return {"ok": True, "login_url": meta["authorization_endpoint"] + "?" + query}


def _refresh(secrets: SecretStore, state: dict[str, Any]) -> str:
    """Trade the refresh token for a new access token. Silent: no browser, and Access
    re-evaluates the person against the app's policy on every one of these, which is what
    makes a two-week grant safe."""
    response = httpx.post(
        str(state.get("token_endpoint") or ""),
        data={
            "grant_type": "refresh_token",
            "refresh_token": str(state.get("refresh_token") or ""),
            "client_id": str(state.get("client_id") or ""),
            "resource": str(state.get("resource") or ""),
        },
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": _user_agent()},
    )
    if response.status_code != 200:
        # The grant is spent (or was revoked): drop the tokens so the pane says "signed
        # out" and offers the button, rather than failing every call with a stale secret.
        if response.status_code in (400, 401):
            _save_state(secrets, {"access_token": "", "refresh_token": "", "expires_at": 0})
        raise RuntimeError(f"续签失败（HTTP {response.status_code}）")
    return str(_store_tokens(secrets, response.json()).get("access_token") or "")


def _is_fresh(state: dict[str, Any]) -> bool:
    """Whether the stored access token can be sent as-is.

    An expiry we were never told is treated as STALE, not as "valid forever". That
    distinction is the exact trap `coworker/mcp/oauth.py` records being bitten by: a token
    of unknown age keeps getting sent, the server 401s, and nothing self-heals because the
    refresh grant is never reached. Cloudflare does return `expires_in`, so this is the
    defensive branch rather than the usual one — and when a refresh token exists, spending
    one grant call is strictly cheaper than a failed request.
    """
    if not state.get("access_token"):
        return False
    expires_at = float(state.get("expires_at") or 0)
    if expires_at <= 0:
        return not state.get("refresh_token")
    return _now() < expires_at - _REFRESH_SKEW_SECONDS


def access_token(secrets: SecretStore) -> str:
    """The bearer token for right now — the provider's entry point.

    Returns "" when nobody has signed in, which the provider reports as "not signed in"
    rather than as a failed call.
    """
    state = _state(secrets)
    if _is_fresh(state):
        return str(state.get("access_token") or "")
    if not state.get("refresh_token"):
        # Nothing better is available, so send what we have and let the gateway judge it.
        return str(state.get("access_token") or "")
    with _refresh_lock:
        # Re-read under the lock: a concurrent call may already have refreshed, and two
        # refreshes racing would burn one of the rotated tokens for nothing.
        state = _state(secrets)
        if _is_fresh(state):
            return str(state.get("access_token") or "")
        try:
            return _refresh(secrets, state)
        except Exception as exc:  # noqa: BLE001
            logger.info("aigw oauth: silent refresh failed: %s", exc)
            return ""


def status(secrets: SecretStore) -> dict[str, Any]:
    """What the settings pane renders. Local only — no network."""
    state = _state(secrets)
    signed_in = bool(state.get("access_token") or state.get("refresh_token"))
    return {
        "signed_in": signed_in,
        "pending": _pending is not None,
        "expires_at": float(state.get("expires_at") or 0),
        "registered": bool(state.get("client_id")),
        "error": _last_error,
        # The legacy route, so the pane can tell "signed in" apart from "still on a
        # pasted session" and stop nagging someone who is genuinely set up.
        "pasted_session": bool(str(_profile(secrets).get("access_token") or "").strip()),
    }


def logout(secrets: SecretStore) -> dict[str, Any]:
    """Forget the tokens, and tell Cloudflare to forget them too where possible.

    The DCR registration is deliberately kept: it is not a credential, it cannot be
    deleted server-side, and reusing it is what stops repeated sign-ins from littering the
    Access app with dead clients.
    """
    state = _state(secrets)
    revocation = str(state.get("revocation_endpoint") or "")
    token = str(state.get("refresh_token") or state.get("access_token") or "")
    if revocation and token:
        try:
            httpx.post(
                revocation,
                data={"token": token, "client_id": str(state.get("client_id") or "")},
                timeout=_HTTP_TIMEOUT,
                headers={"User-Agent": _user_agent()},
            )
        except httpx.HTTPError:
            # Best effort: the local tokens go either way, and a token we cannot revoke
            # still expires on its own.
            logger.debug("aigw oauth: revocation call failed", exc_info=True)

    _save_state(secrets, {"access_token": "", "refresh_token": "", "expires_at": 0})
    return {"ok": True}
