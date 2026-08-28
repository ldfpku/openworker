"""New-flagship rollout (2026-07-14): GPT-5.6 Sol/Terra/Luna + Claude Fable 5 in the
matrix, both families' flagships as defaults, and friendly errors when an account can't
use them (GPT-5.6 rolls out per-organization; quota/credits can run out on any model).
"""

from coworker.config import Config
from coworker.providers.errors import friendly_model_error
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
