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
# Cloudflare AI Gateway has a failure the other vendors don't: a model can sit in the
# catalog, resolve, and still refuse to run on the account's prepaid credits until that
# vendor's own key is stored on the gateway. Verbatim body (code 2021, 2026-08-23):
# "This model is not available via unified billing. Please use BYOK." Its sibling,
# "Wholesale rate limit exceeded for this gateway", is the shared pool being busy — the
# same fix unblocks it, so both name BYOK.
# Not covered: some models answer a bare HTTP 402 with no body text to match on. Those
# keep their raw error rather than being guessed at.
_NEEDS_BYOK = (
    "not available via unified billing",
    "please use byok",
)
_GATEWAY_BUSY = ("wholesale rate limit exceeded",)


def friendly_model_error(model: str, exc: Exception) -> Optional[str]:
    """One actionable sentence for "your account can't use this model" failures, or None."""
    text = str(exc).lower()
    no_access = (
        f"Your account doesn't have access to {model} — new models can roll out "
        "gradually or require a plan upgrade. Pick a different model, or check "
        "the provider's console for availability."
    )
    if any(marker in text for marker in _NEEDS_BYOK):
        return (
            f"{model} is in Cloudflare's catalog but isn't covered by AI Gateway "
            "credits — store that vendor's own API key on the gateway (BYOK), or pick "
            "a different model."
        )
    if any(marker in text for marker in _GATEWAY_BUSY):
        return (
            f"Cloudflare's shared capacity for {model} is saturated right now — try "
            "again in a moment, or store that vendor's own API key on the gateway "
            "(BYOK) to stop sharing the pool."
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
