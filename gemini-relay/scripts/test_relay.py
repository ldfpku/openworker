"""Gemini relay smoke test — standalone diagnostic, not part of the openworker app.

Verifies that gemini.smjtools.com correctly relays both the sync and the streaming
Gemini API calls, and that the streaming response really arrives incrementally
(SSE chunks over time) rather than being buffered somewhere and delivered all at
once. Modeled on the style of `.research/test_proxy.py` (manual .env parsing, one
genai.Client per run, OK/FAIL + elapsed-time printing) but exercises the relay's
GOOGLE_GEMINI_BASE_URL override instead of a forward HTTPS_PROXY.

Run with the hermes-agent venv — the interpreter that actually backs openworker
today (see gemini-relay/docs/01-背景与结论.md):

    & "C:\\Users\\liude\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe" gemini-relay\\scripts\\test_relay.py

Override the relay URL:

    & "C:\\Users\\liude\\AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts\\python.exe" gemini-relay\\scripts\\test_relay.py --relay https://gemini.smjtools.com

Exit code: 0 if both the sync and the streaming test pass, 1 otherwise. The API
key is never printed — only whether one was found.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_RELAY = "https://gemini.smjtools.com"
MODEL = "gemini-3.5-flash-lite"
PROMPT = "hi, reply with one word"

# This file lives at gemini-relay/scripts/test_relay.py; the repo root (where .env
# lives) is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]

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
    app (mirrors .research/test_proxy.py's own manual line parsing)."""
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def resolve_api_key() -> str | None:
    """env GEMINI_API_KEY -> env GOOGLE_API_KEY -> repo-root .env's GEMINI_API_KEY= line."""
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or _read_key_from_dotenv(REPO_ROOT / ".env")
    )


def _clear_proxy_env() -> None:
    for name in _PROXY_ENV_VARS:
        os.environ.pop(name, None)


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

    key = resolve_api_key()
    print("key found:", bool(key))
    if not key:
        print("no GEMINI_API_KEY/GOOGLE_API_KEY in env or repo-root .env — aborting")
        return 1

    _clear_proxy_env()
    os.environ["GOOGLE_GEMINI_BASE_URL"] = args.relay
    print(f"GOOGLE_GEMINI_BASE_URL = {args.relay}")

    from google import genai

    client = genai.Client(api_key=key)

    ok_sync = test_sync(client)
    ok_stream = test_stream(client)

    if ok_sync and ok_stream:
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
