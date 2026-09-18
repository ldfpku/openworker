"""Friendly translation of model access + quota failures.

The picker now defaults to brand-new flagships (GPT-5.6 Sol, Claude Fable 5), and not every
account can use them: OpenAI is still rolling GPT-5.6 out per-organization, and both vendors
reject calls once quota/credits run out. Those failures arrive as terse SDK exceptions
wrapping JSON error bodies; this maps the well-known shapes to one actionable sentence.
Anything unrecognized returns None and the caller surfaces the raw error unchanged.

Matching is on the error BODY text (error codes/types), not just HTTP status — a 404 also
means "wrong base_url" and a 429 also means "slow down", and neither of those should be
dressed up as an access problem.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

# Error-body markers, verbatim from the vendors' error codes/messages:
# OpenAI: {"error": {"code": "model_not_found", "message": "The model `X` does not exist or
#   you do not have access to it."}} (404/403) and {"code": "insufficient_quota"} (429).
# Anthropic: {"type": "not_found_error", "message": "model: X"} (404),
#   {"type": "permission_error"} (403), and "credit balance is too low" (400).
_NO_ACCESS = (
    "model_not_found",
    "does not exist or you do not have access",
    "does not have access to model",
    "permission_error",
    "permission denied",
)
_NO_QUOTA = (
    "insufficient_quota",
    "exceeded your current quota",
    "credit balance is too low",
    "billing hard limit",
)
# Cloudflare AI Gateway answers HTTP 402 for two unrelated reasons, and only the body
# tells them apart (verbatim, code 2021, 2026-08-23):
#
#   "This model is not available via unified billing. Please use BYOK."
#       → permanent: this model is not on Unified Billing at all.
#   "Wholesale rate limit exceeded for this gateway. Please reduce request rate or use BYOK."
#       → transient: the shared wholesale pool for that model is busy right now.
#
# Both sentences end in "BYOK", which is exactly how the two got conflated once already —
# three perfectly good flagship models were cut from the matrix because a burst of probes
# tripped the rate limiter and the bare status code was read as unavailability. So match
# the halves that actually differ, and check the transient one FIRST: telling a user to
# go configure BYOK when they only need to wait ten seconds is the worse wrong answer.
_GATEWAY_BUSY = ("wholesale rate limit exceeded",)
_NEEDS_BYOK = ("not available via unified billing",)

# The same pool, the same meaning, a different status code: the gateway's per-model
# wholesale concurrency limiter answers **429** with a plain-text body `Rate limited`
# (the OpenAI SDK renders it as `Error code: 429 - {'code': 2018, 'message': 'Wholesale
# Rate limited'}`). Every 429 seen on this gateway so far has been this — a second
# request for a model whose previous slow call was still in flight, refused within
# 200–500 ms. It is transient by construction, which is why it earns the retry in
# `aigateway_provider` and why its copy must never say "go configure BYOK" the way a
# permanent 402 does.
#
# "rate limited" alone is too common a phrase to trust on its own (any vendor's own
# per-key limiter says it too, and that one is NOT fixed by a same-tier stand-in), so the
# status has to agree — hence the 429 half of the test below. `wholesale rate limited`
# contains the shorter marker, so one string covers both spellings.
_RATE_LIMITED = "rate limited"


def is_gateway_busy(exc: Exception) -> bool:
    """True when the failure is "Cloudflare's shared pool for this model is busy".

    Both spellings count: the 429 concurrency refusal above, and the older 402
    `wholesale rate limit exceeded`. Anything else — including a vendor's own 429 that
    arrived without the gateway's marker — is False, because retrying it on a same-tier
    stand-in would only buy a second failure.
    """
    text = str(exc).lower()
    if any(marker in text for marker in _GATEWAY_BUSY):
        return True
    if _RATE_LIMITED not in text:
        return False
    status = getattr(exc, "status_code", None)
    return status == 429 or "429" in text

# The company gateway's guard Worker (gateway-guard) refuses restricted models with
# {"error": {"code": "model_restricted", "message": "<Chinese sentence ending in
# [gateway-guard]>"}}. That message is already the right thing to show verbatim — it names
# the model, the roles that may use it, and who to ask — so extract it instead of wrapping
# it in the "Error code: 403 - {...}" shell. The code was chosen on the guard side to miss
# every marker above (a message matching `permission_error` etc. would get swallowed here).
_RESTRICTED = "model_restricted"

# The message value in either JSON (`"message": "..."`) or the SDKs' dict-repr
# (`'message': '...'`) shape. The guard's text contains no quotes, so the character
# class is safe.
_MESSAGE_RE = re.compile(r"[\"']message[\"']\s*:\s*[\"']([^\"']+)[\"']")


# -- transient vs. permanent (the automatic-retry gate) --------------------------------
#
# Statuses where the request never got a considered answer, so re-sending the SAME request
# can succeed: the queue was full (408/409/425/429), the backend fell over (500/502/503/
# 504), or Anthropic was overloaded (529). Everything else — 400/401/403/404 and friends —
# means the request itself was refused, and re-sending it only buys the same refusal.
_TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})

# The two statuses Cloudflare's shared-pool refusal actually arrives with (the 402
# `wholesale rate limit exceeded` and the 429 concurrency refusal), plus None for a
# failure that carries no status at all. `is_gateway_busy` matches on text, so this is
# what stops it claiming a 400 that merely QUOTES an upstream 429.
_GATEWAY_BUSY_STATUSES = frozenset({None, 402, 429})

# Matched by NAME, not isinstance: every vendor SDK defines its own connection/timeout/
# overload classes, and importing all of them here would defeat the point of the provider
# layer (same reasoning as manager._is_timeout_error). openai + anthropic (APIConnection/
# APITimeout/RateLimit/InternalServer/Overloaded), google-genai (ServiceUnavailable,
# DeadlineExceeded, ResourceExhausted), botocore/bedrock (Throttling/ModelTimeout/
# InternalServer/ServiceUnavailable/ModelNotReady) and the httpx/urllib3 wire errors
# underneath them all.
_TRANSIENT_EXC_NAMES = frozenset(
    {
        "apiconnectionerror",
        "apitimeouterror",
        "apiconnectiontimeouterror",
        "ratelimiterror",
        "internalservererror",
        "internalserverexception",
        "overloadederror",
        "serviceunavailable",
        "serviceunavailableerror",
        "serviceunavailableexception",
        "deadlineexceeded",
        "resourceexhausted",
        "throttlingexception",
        "modeltimeoutexception",
        "modelnotreadyexception",
        "connectionerror",
        "connectionreseterror",
        "connectionaborted",
        "remoteprotocolerror",
        "protocolerror",
        "readtimeout",
        "writetimeout",
        "connecttimeout",
        "pooltimeout",
        "incompleteread",
        "chunkedencodingerror",
    }
)

# Last resort, for backends that surface a bare RuntimeError carrying the vendor's text.
_TRANSIENT_MARKERS = (
    "connection reset",
    "connection aborted",
    "connection broken",
    "server disconnected",
    "peer closed connection",
    "incomplete chunked read",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "overloaded",
)

# The OpenAI/Anthropic SDKs render a status into `str(exc)` as "Error code: 503 - {...}";
# `is_gateway_busy` above already leans on that shape for its 429.
_STATUS_IN_TEXT_RE = re.compile(r"error code:\s*(\d{3})")


def _status_of(exc: BaseException) -> Optional[int]:
    """The HTTP status behind a provider exception, or None when it carries none."""
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    # botocore: ClientError.response["ResponseMetadata"]["HTTPStatusCode"].
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if isinstance(status, int):
            return status
    match = _STATUS_IN_TEXT_RE.search(str(exc).lower())
    return int(match.group(1)) if match else None


def is_transient_model_error(exc: BaseException) -> bool:
    """Whether re-sending the same model call could plausibly succeed.

    The gate for the engine's automatic retry. Deliberately conservative: a False here
    costs one manual Retry click, a wrong True costs the user three round-trips and three
    backoffs before the real (permanent) diagnosis reaches them.
    """
    text = str(exc).lower()
    # The permanent markers are asked FIRST, before anything that reads loosely. Quota,
    # credit and entitlement failures arrive on transient-LOOKING statuses — OpenAI bills
    # an exhausted quota as 429, the gateway's "needs BYOK" as 402 — but nothing about the
    # account changes in six seconds, so they are permanent for our purposes.
    if _RESTRICTED in text:
        return False
    if any(marker in text for marker in _NO_QUOTA + _NEEDS_BYOK + _NO_ACCESS):
        return False
    status = _status_of(exc)
    # Cloudflare's shared-pool refusal comes back as 402 OR 429 and is transient by
    # construction — a slot frees up in seconds. It has to be asked before the status
    # check, or the 402 half would be read as "permanent" and contradict the very function
    # that exists to say this one IS worth waiting out. Two guards keep its loose test
    # (the phrase "rate limited" plus a 429 ANYWHERE in the text) from over-claiming: the
    # permanent markers above win, so an exhausted quota that happens to say "Rate
    # limited" is still permanent; and the response's OWN status has to be one the gateway
    # actually answers with, so a 400 that merely quotes an upstream 429 stays permanent
    # too — quoting a status is not being given one.
    if is_gateway_busy(exc) and status in _GATEWAY_BUSY_STATUSES:
        return True
    if status is not None:
        return status in _TRANSIENT_STATUSES
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError)):
            return True
        if type(current).__name__.lower() in _TRANSIENT_EXC_NAMES:
            return True
        current = current.__cause__ or current.__context__
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    """The vendor's own `Retry-After`, in seconds, when the 429 carried one. Best effort —
    a header we can't read is no reason to fail the call, the caller just uses its own
    backoff instead. Both RFC 9110 spellings are accepted: a delay in seconds, and an
    HTTP-date (which some CDNs in front of model endpoints send instead)."""
    for source in (getattr(exc, "retry_after", None), _header(exc, "retry-after")):
        if source is None:
            continue
        raw = str(source).strip()
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
        moment = _http_date(raw)
        if moment is not None:
            # Relative to OUR clock, which is the only one the backoff can use; a date
            # already in the past yields a non-positive value and the caller falls back
            # to its own schedule.
            return moment - datetime.now(timezone.utc).timestamp()
    return None


def _http_date(raw: str) -> Optional[float]:
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:  # RFC 9110 dates are GMT; an SDK may hand one back naive
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _header(exc: BaseException, name: str) -> Optional[str]:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    try:
        return getter(name)
    except Exception:  # noqa: BLE001 - a header we can't read is simply absent
        return None


def friendly_model_error(model: str, exc: Exception) -> Optional[str]:
    """One actionable sentence for "your account can't use this model" failures, or None."""
    raw = str(exc)
    text = raw.lower()
    if _RESTRICTED in text:
        m = _MESSAGE_RE.search(raw)
        if m:
            return m.group(1)
        return (
            f"{model} is restricted by your administrator — pick a different model, "
            "or ask the administrator to open it up."
        )
    no_access = (
        f"Your account doesn't have access to {model} — new models can roll out "
        "gradually or require a plan upgrade. Pick a different model, or check "
        "the provider's console for availability."
    )
    # The 429 concurrency refusal FIRST, and with its own sentence: by the time this is
    # read, `aigateway_provider` has already re-sent the turn on the model's dynamic route
    # and that failed too, so "try again in a moment" is the whole advice. Telling someone
    # to go set up BYOK — right for a permanent 402 — would be wrong here twice over.
    route = str(getattr(exc, "aigw_route", "") or "").strip()
    if (
        is_gateway_busy(exc)
        and not any(marker in text for marker in _GATEWAY_BUSY)
        # `rate limited` is loose enough that some other vendor's own 429 could say it,
        # and that one is NOT the shared Cloudflare pool — so only claim it is when the
        # evidence says gateway: the body's own `wholesale`, a route we just tried, or a
        # gateway-routed model id. Anything else keeps its raw message, as before.
        and (route or "wholesale" in text or model.lower().startswith("aigw:"))
    ):
        stand_in = str(getattr(exc, "aigw_fallback", "") or "").strip()
        if route:
            return (
                f"Cloudflare's shared capacity for {model} is busy right now, and the "
                f"same-tier stand-in was busy too — try again in a moment. "
                f"(route {route}"
                + (f" → {stand_in}" if stand_in else "")
                + ")"
            )
        return (
            f"Cloudflare's shared capacity for {model} is busy right now — try again in "
            "a moment."
        )
    if any(marker in text for marker in _GATEWAY_BUSY):
        return (
            f"Cloudflare's shared capacity for {model} is busy right now — try again in "
            "a moment. If it keeps happening, store that vendor's own API key on the "
            "gateway (BYOK) to stop sharing the pool."
        )
    if any(marker in text for marker in _NEEDS_BYOK):
        return (
            f"{model} isn't covered by AI Gateway credits — store that vendor's own API "
            "key on the gateway (BYOK), or pick a different model."
        )
    if any(marker in text for marker in _NO_QUOTA):
        return (
            f"Your account is out of quota for {model} — add credits or raise the limit "
            "in the provider's billing console, or pick a different model."
        )
    if any(marker in text for marker in _NO_ACCESS):
        return no_access
    # Anthropic's 404 body is just "model: <id>" under type not_found_error; require both
    # halves so unrelated 404s (bad base_url, deleted resource) keep their raw message.
    if "not_found_error" in text and f"model: {model.split(':')[-1].lower()}" in text:
        return no_access
    return None
