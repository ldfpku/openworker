"""Gemini relay smoke test — standalone diagnostic, not part of the openworker app.

Verifies that gemini.smjtools.com correctly relays both the sync and the streaming
Gemini API calls, and that the streaming response really arrives incrementally
(SSE chunks over time) rather than being buffered somewhere and delivered all at
once. Deliberately standalone — manual .env parsing, one genai.Client per run,
OK/FAIL + elapsed-time printing — and exercises the relay's GOOGLE_GEMINI_BASE_URL
override rather than a forward HTTPS_PROXY.

Run with the hermes-agent venv — the interpreter that actually backs openworker
today (see gemini-relay/docs/01-背景与结论.md):

    & "C:\\Users\\liude\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe" gemini-relay\\scripts\\test_relay.py

Override the relay URL:

    & "C:\\Users\\liude\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe" gemini-relay\\scripts\\test_relay.py --relay https://gemini.smjtools.com

The relay wants TWO credentials and this script needs both:

  * a **login token** (`owr_...`), which says who you are — sign in from OpenWorker
    (Settings ▸ Models ▸ Gemini ▸ 登录) and it is picked up out of the app's secret
    store automatically, or set `OPENWORKER_RELAY_TOKEN`;
  * your **own Gemini API key**, which is what Google bills — `GEMINI_API_KEY` /
    `GOOGLE_API_KEY`, the app's secret store, or the repo-root .env.

Pointing `--relay` straight at generativelanguage.googleapis.com needs only the key,
which keeps "is it the relay or is it Google" answerable in one command.

Exit code: 0 if both the sync and the streaming test pass, 1 otherwise. Neither
credential is ever printed — only which source it came from.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# google-genai warns about "direct AFC use" on every bare generate_content(_stream)
# call, tools or no tools; this smoke test passes no tools, so it's pure noise here.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

DEFAULT_RELAY = "https://gemini.smjtools.com"
MODEL = "gemini-3.5-flash-lite"
PROMPT = "hi, reply with one word"

# This file lives at gemini-relay/scripts/test_relay.py; the repo root (where .env
# lives) is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: What a relay login token looks like (worker/src/auth.ts TOKEN_PREFIX).
RELAY_TOKEN_PREFIX = "owr_"

# Proxy env vars to clear in-process before touching the relay, so this test measures
# the relay's own reachability instead of whatever local forward proxy (v2rayN via
# proxy-guard) may already be configured on this machine.
_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def _read_key_from_dotenv(path: Path) -> str | None:
    """Manually parse a `GEMINI_API_KEY=` line out of a .env file. Deliberately not
    routed through coworker's SecretStore — this script runs standalone, outside the
    app."""
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def _secret_profile() -> dict:
    """OpenWorker's stored `provider:gemini` profile, or `{}`.

    Read straight off disk rather than through coworker.secrets: this script is a
    standalone diagnostic that must run under any interpreter, including one with no
    openworker install (see the module docstring).
    """
    base = os.environ.get("COWORKER_STATE_DIR")
    if base:
        path = Path(base).expanduser() / "secrets.json"
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "coworker" / "secrets.json"
    else:
        path = Path.home() / ".config" / "coworker" / "secrets.json"

    if not path.is_file():
        return {}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    profile = stored.get("provider:gemini")
    return profile if isinstance(profile, dict) else {}


def resolve_token() -> tuple[str | None, str]:
    """The relay login token, and where it came from.

    Order: env `OPENWORKER_RELAY_TOKEN` -> the signed-in app's `relay_token`. A build
    from before the quota change parked the token in `api_key` instead; that slot is
    accepted as a last resort so this script still works on a machine that has not
    signed in again since upgrading.
    """
    token = (os.environ.get("OPENWORKER_RELAY_TOKEN") or "").strip()
    if token:
        return token, "env OPENWORKER_RELAY_TOKEN"
    profile = _secret_profile()
    token = (profile.get("relay_token") or "").strip()
    if token.startswith(RELAY_TOKEN_PREFIX):
        return token, "OpenWorker secret store (signed in)"
    legacy = (profile.get("api_key") or "").strip()
    if legacy.startswith(RELAY_TOKEN_PREFIX):
        return legacy, "OpenWorker secret store (pre-quota api_key slot)"
    return None, ""


def resolve_key() -> tuple[str | None, str]:
    """The caller's own Gemini API key, and where it came from.

    Order: env `GEMINI_API_KEY` -> env `GOOGLE_API_KEY` -> the app's secret store ->
    repo-root .env. Same env-first precedence the app itself uses.
    """
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value, f"env {name}"
    stored = (_secret_profile().get("api_key") or "").strip()
    # A pre-quota build kept the login token here; that is not a Gemini key.
    if stored and not stored.startswith(RELAY_TOKEN_PREFIX):
        return stored, "OpenWorker secret store"
    value = _read_key_from_dotenv(REPO_ROOT / ".env")
    if value:
        return value, "repo-root .env"
    return None, ""


def _clear_proxy_env() -> None:
    for name in _PROXY_ENV_VARS:
        os.environ.pop(name, None)


def show_identity(relay: str, token: str) -> None:
    """Print who the relay thinks we are and how much of today's quota is left.

    Best effort: a relay that cannot answer /auth/whoami is a finding worth printing,
    not a reason to skip the actual relay tests below.
    """
    request = urllib.request.Request(
        relay.rstrip("/") + "/auth/whoami", headers={"Authorization": "Bearer " + token}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"[whoami] HTTP {exc.code} -> {exc.read().decode('utf-8', 'replace')[:160]}")
        return
    except (urllib.error.URLError, ValueError, OSError) as exc:
        print(f"[whoami] unreachable -> {type(exc).__name__}: {exc}")
        return

    who = " / ".join(x for x in (data.get("name"), data.get("dept"), data.get("email")) if x)
    print(f"[whoami] {who or '(unnamed)'}")
    quota = data.get("quota") or {}
    limits, used = quota.get("limits") or {}, quota.get("used") or {}
    if limits:
        def show(limit: object, spent: object) -> str:
            if limit == -1:
                return f"{spent}/不限"
            if limit == 0:
                return "停用"
            return f"{spent}/{limit}"

        print(
            f"[quota]  requests {show(limits.get('rpd'), used.get('dayRequests'))}/day, "
            f"{show(limits.get('rpm'), used.get('minuteRequests'))}/min; "
            f"tokens {show(limits.get('tpd'), used.get('dayTokens'))}/day"
        )


def test_sync(client: "object") -> bool:
    """Non-streaming generate_content — prints OK/FAIL and elapsed time."""
    t0 = time.monotonic()
    try:
        resp = client.models.generate_content(model=MODEL, contents=PROMPT)  # type: ignore[union-attr]
        elapsed = time.monotonic() - t0
        text = (resp.text or "").strip().replace("\n", " ")[:80]
        print(f"[sync]   OK   {elapsed:.2f}s -> {text!r}")
        return True
    except Exception as exc:  # noqa: BLE001 - report and continue to the next test
        elapsed = time.monotonic() - t0
        print(f"[sync]   FAIL {elapsed:.2f}s -> {type(exc).__name__}: {exc}")
        return False


def test_stream(client: "object") -> bool:
    """Streaming generate_content_stream — records each chunk's relative arrival
    timestamp, then prints chunk count and the first/last chunk time gap so a
    buffered (non-incremental) response is visible as a near-zero gap."""
    t0 = time.monotonic()
    timestamps: list[float] = []
    try:
        stream = client.models.generate_content_stream(model=MODEL, contents=PROMPT)  # type: ignore[union-attr]
        for _chunk in stream:
            timestamps.append(time.monotonic() - t0)
        if not timestamps:
            print("[stream] FAIL 0.00s -> no chunks received")
            return False
        span = timestamps[-1] - timestamps[0]
        print(
            f"[stream] OK   {timestamps[-1]:.2f}s -> {len(timestamps)} chunk(s), "
            f"first at {timestamps[0]:.2f}s, last at {timestamps[-1]:.2f}s, span {span:.2f}s"
        )
        if len(timestamps) > 1 and span < 0.01:
            print(
                "[stream] WARN chunks arrived within 10ms of each other — the response "
                "may have been buffered upstream instead of streamed incrementally"
            )
        return True
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        print(f"[stream] FAIL {elapsed:.2f}s -> {type(exc).__name__}: {exc}")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Gemini relay (sync generate_content + streaming SSE)."
    )
    parser.add_argument(
        "--relay",
        default=DEFAULT_RELAY,
        help=f"relay base URL (default: {DEFAULT_RELAY})",
    )
    args = parser.parse_args(argv)
    via_relay = DEFAULT_RELAY in args.relay

    key, key_source = resolve_key()
    token, token_source = resolve_token()
    print("api key   :", key_source or "(none found)")
    print("login token:", token_source or "(none found)")

    if not key:
        print(
            "no Gemini API key found — get one at https://aistudio.google.com/apikey and "
            "set GEMINI_API_KEY (or add it in OpenWorker: Settings ▸ Models ▸ Gemini) — aborting"
        )
        return 1
    if via_relay and not token:
        # Fail here rather than letting the relay answer 401 and leaving the reader to work
        # out that "not signed in" is about a login, not about the key they just checked.
        print(
            "no relay login token — sign in from OpenWorker first "
            "(Settings ▸ Models ▸ Gemini ▸ 登录), or set OPENWORKER_RELAY_TOKEN — aborting"
        )
        return 1

    _clear_proxy_env()
    os.environ["GOOGLE_GEMINI_BASE_URL"] = args.relay
    print(f"GOOGLE_GEMINI_BASE_URL = {args.relay}")

    if token and via_relay:
        show_identity(args.relay, token)

    from google import genai
    from google.genai import types

    # api_key becomes x-goog-api-key (forwarded to Google untouched); the login token rides
    # Authorization, which the relay consumes and strips. Talking straight to Google sends
    # only the key, so the same script works as a bypass baseline.
    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(
            headers={"Authorization": "Bearer " + token} if token and via_relay else None
        ),
    )

    ok_sync = test_sync(client)
    ok_stream = test_stream(client)

    if ok_sync and ok_stream:
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
