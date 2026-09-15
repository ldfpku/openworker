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
