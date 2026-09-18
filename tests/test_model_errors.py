"""New-flagship rollout (2026-07-14): GPT-5.6 Sol/Terra/Luna + Claude Fable 5 in the
matrix, both families' flagships as defaults, and friendly errors when an account can't
use them (GPT-5.6 rolls out per-organization; quota/credits can run out on any model).
"""

import pytest

from coworker.config import Config
from coworker.providers.errors import (
    friendly_model_error,
    is_gateway_busy,
    is_transient_model_error,
    retry_after_seconds,
)
from coworker.providers.matrix import MATRIX, models_for_provider
from coworker.providers.registry import get_descriptor


def test_new_flagships_in_matrix_with_labels():
    for mid, label in {
        "gpt-5.6-sol": "GPT-5.6 Sol · OpenAI",
        "gpt-5.6-terra": "GPT-5.6 Terra · OpenAI",
        "gpt-5.6-luna": "GPT-5.6 Luna · OpenAI",
        "anthropic:claude-fable-5": "Claude Fable 5 · Anthropic",
    }.items():
        assert MATRIX[mid].label == label
        assert MATRIX[mid].caps.tools and MATRIX[mid].caps.vision

    assert "gpt-5.6-sol" in models_for_provider("openai")
    assert "claude-fable-5" in models_for_provider("anthropic")


def test_flagships_are_the_defaults():
    assert Config().model == "gpt-5.6-sol"
    assert get_descriptor("openai").recommended_model == "gpt-5.6-sol"
    assert get_descriptor("anthropic").recommended_model == "claude-fable-5"


# -- friendly access/quota errors --------------------------------------------------------
def test_no_access_errors_are_translated():
    # OpenAI's 404/403 body for a model the org can't use yet
    exc = RuntimeError(
        "Error code: 404 - {'error': {'code': 'model_not_found', 'message': "
        "'The model `gpt-5.6-sol` does not exist or you do not have access to it.'}}"
    )
    msg = friendly_model_error("gpt-5.6-sol", exc)
    assert msg and "doesn't have access to gpt-5.6-sol" in msg

    # Anthropic's 404 body is type not_found_error + "model: <id>"
    exc = RuntimeError(
        "Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', "
        "'message': 'model: claude-fable-5'}}"
    )
    msg = friendly_model_error("anthropic:claude-fable-5", exc)
    assert msg and "doesn't have access to anthropic:claude-fable-5" in msg


def test_quota_errors_are_translated():
    exc = RuntimeError(
        "Error code: 429 - {'error': {'code': 'insufficient_quota', 'message': "
        "'You exceeded your current quota, please check your plan and billing details.'}}"
    )
    msg = friendly_model_error("gpt-5.6-sol", exc)
    assert msg and "out of quota for gpt-5.6-sol" in msg

    exc = RuntimeError(
        "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
        "'message': 'Your credit balance is too low to access the Anthropic API.'}}"
    )
    msg = friendly_model_error("anthropic:claude-fable-5", exc)
    assert msg and "out of quota" in msg


def test_gateway_guard_restriction_surfaces_its_own_message():
    # gateway-guard (the company gateway's model gate) answers 403 with code
    # model_restricted and a Chinese message that is already the right thing to show —
    # extract it verbatim instead of wrapping it in the "Error code: 403 - {...}" shell.
    exc = RuntimeError(
        "Error code: 403 - {'error': {'code': 'model_restricted', 'type': "
        "'model_restricted', 'status': 403, 'message': '模型 anthropic/claude-fable-5 "
        "暂未对你的账号开放（现仅管理员、总经理可用）。请改用其他模型，或联系管理员开通。"
        "[gateway-guard]'}}"
    )
    msg = friendly_model_error("aigw:anthropic/claude-fable-5", exc)
    assert msg and msg.endswith("[gateway-guard]")
    assert "暂未对你的账号开放" in msg
    assert "Error code" not in msg

    # The JSON double-quote shape (a raw body, not the SDKs' dict repr) extracts too
    exc = RuntimeError('403 {"error": {"code": "model_restricted", "message": "模型受限。[gateway-guard]"}}')
    assert friendly_model_error("m", exc) == "模型受限。[gateway-guard]"


def test_model_restricted_without_extractable_message_gets_a_fallback():
    msg = friendly_model_error(
        "aigw:openai/gpt-5.6-sol", RuntimeError("403 model_restricted")
    )
    assert msg and "restricted by your administrator" in msg


def test_unrelated_errors_pass_through_raw():
    # a plain rate-limit (429 without a quota code) must NOT be dressed up
    assert (
        friendly_model_error(
            "gpt-5.6-sol",
            RuntimeError("Error code: 429 - rate_limit_exceeded, retry after 2s"),
        )
        is None
    )
    # a 404 from a wrong base_url isn't an access problem
    assert (
        friendly_model_error(
            "gpt-5.6-sol", RuntimeError("Error code: 404 - no route /v2/chat")
        )
        is None
    )
    assert (
        friendly_model_error("gpt-5.6-sol", RuntimeError("connection reset by peer"))
        is None
    )


# -- transient vs. permanent (the automatic-retry gate) --------------------------------
#
# The engine re-runs a model call that never landed. A wrong True here costs the user
# three round-trips and two backoffs before the real diagnosis arrives, so the classifier
# is deliberately conservative — these pin both halves of that judgment.


def _status_error(status, body=""):
    exc = RuntimeError(f"Error code: {status} - {body}")
    exc.status_code = status
    return exc


def test_wire_and_capacity_failures_are_transient():
    for status in (408, 409, 425, 429, 500, 502, 503, 504, 529):
        assert is_transient_model_error(_status_error(status)), status
    for exc in (
        TimeoutError("read timed out"),
        ConnectionResetError("connection reset by peer"),
        type("APIConnectionError", (Exception,), {})("upstream closed"),
        type("OverloadedError", (Exception,), {})("overloaded"),
        type("ThrottlingException", (Exception,), {})("slow down"),
        RuntimeError("server disconnected without sending a response"),
        RuntimeError("Error code: 502 - bad gateway"),
    ):
        assert is_transient_model_error(exc), type(exc).__name__


def test_refusals_and_quota_failures_are_not_transient():
    for status in (400, 401, 402, 403, 404, 422):
        assert not is_transient_model_error(_status_error(status)), status
    # OpenAI bills an exhausted quota as 429 and the gateway bills "needs BYOK" as 402:
    # transient-LOOKING, but nothing about the account changes in six seconds.
    assert not is_transient_model_error(
        _status_error(429, "{'code': 'insufficient_quota'}")
    )
    assert not is_transient_model_error(
        _status_error(402, "This model is not available via unified billing. Please use BYOK.")
    )
    assert not is_transient_model_error(
        _status_error(403, "{'code': 'model_restricted'}")
    )
    assert not is_transient_model_error(RuntimeError("your prompt was rejected"))


def test_the_gateways_busy_pool_counts_as_transient_despite_its_402():
    """Cloudflare answers "the shared pool for this model is busy" with 402 OR 429, and
    `is_gateway_busy` exists precisely to say that one IS worth waiting out. Asking the
    status code first would have called the 402 half permanent and contradicted it."""
    assert is_transient_model_error(
        _status_error(402, "Wholesale rate limit exceeded for this gateway. Please use BYOK.")
    )
    busy_429 = _status_error(429, "{'code': 2018, 'message': 'Wholesale Rate limited'}")
    assert is_gateway_busy(busy_429) and is_transient_model_error(busy_429)
    # …and the OTHER 402, which really is permanent, still is.
    assert not is_transient_model_error(
        _status_error(402, "This model is not available via unified billing. Please use BYOK.")
    )


def test_the_busy_pool_test_is_loose_so_it_is_asked_last_and_only_on_its_own_statuses():
    """`is_gateway_busy` matches on the phrase "rate limited" plus a 429 ANYWHERE in the
    text, which is loose enough to over-claim twice. Two guards, both load-bearing: the
    permanent markers are asked first, and the response's OWN status has to be one the
    gateway actually answers with — quoting a status is not being given one."""
    # An exhausted quota that happens to word itself as a rate limit is still permanent.
    quota = _status_error(
        429, "{'code':'insufficient_quota','message':'Rate limited, quota exceeded'}"
    )
    assert is_gateway_busy(quota) and not is_transient_model_error(quota)
    # A 400 that merely quotes an upstream 429 was never rate-limited itself.
    quoting = _status_error(400, "upstream said 'Rate limited' (429)")
    assert is_gateway_busy(quoting) and not is_transient_model_error(quoting)


def test_retry_after_also_accepts_an_http_date():
    """RFC 9110 allows a date instead of a delay, and CDNs in front of model endpoints
    send one. Read relative to our own clock — a date already past yields a non-positive
    value and the caller falls back to its own schedule."""
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    class _Headers:
        def __init__(self, value):
            self.value = value

        def get(self, name):
            return self.value if name == "retry-after" else None

    def _with(value):
        exc = _status_error(503)
        exc.response = type("R", (), {"headers": _Headers(value)})()
        return exc

    soon = datetime.now(timezone.utc) + timedelta(seconds=20)
    assert retry_after_seconds(_with(format_datetime(soon))) == pytest.approx(20, abs=3)
    past = datetime.now(timezone.utc) - timedelta(seconds=60)
    assert retry_after_seconds(_with(format_datetime(past))) < 0
    assert retry_after_seconds(_with("not a date and not a number")) is None


def test_retry_after_is_read_when_the_vendor_sends_one():
    class _Headers:
        def get(self, name):
            return "12" if name == "retry-after" else None

    exc = _status_error(429)
    exc.response = type("R", (), {"headers": _Headers()})()
    assert retry_after_seconds(exc) == 12.0
    assert retry_after_seconds(_status_error(429)) is None
    assert retry_after_seconds(RuntimeError("no headers here")) is None
