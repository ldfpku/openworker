"""Cloudflare AI Gateway provider — wire dispatch, credential plumbing, curated ids.

Deliberately offline. WHICH model ids the gateway serves was settled by calling the live
API (the findings are recorded in `matrix.py`); a test cannot re-litigate that without a
token and a bill. What can regress silently is everything around it: sending Anthropic a
request shaped for OpenAI, dropping the `cf-aig-gateway-id` header so calls land in the
wrong gateway, or reading `anthropic/claude-haiku-4.5` as an unknown Claude family and
picking a thinking config it rejects. Those are what these cover.
"""

from __future__ import annotations

import pytest

from coworker.providers import capabilities_for
from coworker.providers.aigateway_provider import (
    AIGatewayProvider,
    ai_base_url,
    gateway_headers,
    openai_base_url,
    resolve_settings,
    wire_for,
)
from coworker.providers.anthropic_provider import (
    AnthropicProvider,
    _needs_refusal_fallback,
    _uses_budget_thinking,
)
from coworker.providers.errors import friendly_model_error
from coworker.providers.matrix import MATRIX
from coworker.providers.openai_provider import OpenAIProvider
from coworker.providers.openai_responses import OpenAIResponsesProvider
from coworker.providers.registry import (
    descriptor_configured,
    get_descriptor,
    verify_provider_key,
)
from coworker.providers.router import ProviderRouter

ACCOUNT = "0" * 32


def _provider(**kw) -> AIGatewayProvider:
    return AIGatewayProvider(
        account_id=ACCOUNT, api_token="cf-token", gateway_id="openworker-agw", **kw
    )


# -- wire selection ----------------------------------------------------------------


@pytest.mark.parametrize(
    "model,wire",
    [
        ("anthropic/claude-sonnet-4.6", "messages"),
        ("openai/gpt-5.6-terra", "responses"),
        ("xai/grok-4.3", "chat"),
        ("deepseek/deepseek-v4-pro", "chat"),
        ("@cf/zai-org/glm-5.2", "chat"),
        # No author segment at all: nothing to route on, so the compat default.
        ("some-bare-model", "chat"),
    ],
)
def test_wire_for_picks_the_schema_each_author_needs(model, wire):
    assert wire_for(model) == wire


def test_each_wire_builds_the_matching_sdk_client():
    p = _provider()
    assert isinstance(p._client_for("anthropic/claude-sonnet-4.6"), AnthropicProvider)
    assert isinstance(p._client_for("openai/gpt-5.5"), OpenAIResponsesProvider)
    assert isinstance(p._client_for("@cf/zai-org/glm-5.2"), OpenAIProvider)


def test_sub_clients_are_cached_per_wire_not_per_model():
    p = _provider()
    first = p._client_for("deepseek/deepseek-v4-pro")
    assert p._client_for("xai/grok-4.3") is first


# -- credentials and routing headers -----------------------------------------------


def test_openai_wires_get_the_v1_base_and_the_gateway_header():
    p = _provider()
    for model in ("openai/gpt-5.5", "@cf/zai-org/glm-5.2"):
        client = p._client_for(model)
        assert client._base_url == openai_base_url(ACCOUNT)
        assert client._base_url.endswith("/ai/v1")
        assert client._api_key == "cf-token"
        assert client._default_headers == {"cf-aig-gateway-id": "openworker-agw"}


def test_anthropic_wire_uses_bearer_auth_and_the_unsuffixed_base():
    # The Anthropic SDK appends `/v1/messages` itself, so its base stops at `/ai` — and it
    # authenticates with a bearer token here, not the `x-api-key` header a real Anthropic
    # key would use. Getting either wrong is a 404 or a 401, not a subtle bug, but both
    # are one keystroke away.
    client = _provider()._client_for("anthropic/claude-haiku-4.5")
    assert client._base_url == ai_base_url(ACCOUNT)
    assert client._base_url.endswith("/ai")
    assert client._auth_token == "cf-token"
    assert client._api_key is None
    assert client._default_headers == {"cf-aig-gateway-id": "openworker-agw"}


def test_no_gateway_name_means_no_header_rather_than_an_empty_one():
    # An empty `cf-aig-gateway-id` is not the same as omitting it; Cloudflare falls back
    # to the account's default gateway only when the header is absent.
    assert gateway_headers("") == {}
    assert gateway_headers("  ") == {}
    client = AIGatewayProvider(account_id=ACCOUNT, api_token="t")._client_for("xai/x")
    assert client._default_headers is None


@pytest.mark.parametrize(
    "kwargs,missing",
    [
        ({"account_id": "", "api_token": "t"}, "account ID"),
        ({"account_id": ACCOUNT, "api_token": ""}, "API token"),
    ],
)
def test_missing_credentials_say_which_one(kwargs, missing):
    p = AIGatewayProvider(**kwargs)
    with pytest.raises(RuntimeError, match=missing):
        p._client_for("xai/grok-4.3")


def test_profile_beats_environment(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "env-account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "env-token")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_ID", "env-gateway")
    assert resolve_settings({"account_id": ACCOUNT, "api_token": "tok"}) == (
        ACCOUNT,
        "tok",
        "env-gateway",  # not in the profile, so the env still supplies it
    )


def test_environment_fills_in_an_empty_profile(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "env-account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "env-token")
    monkeypatch.delenv("CLOUDFLARE_AI_GATEWAY_ID", raising=False)
    assert resolve_settings({}) == ("env-account", "env-token", "")


# -- model ids ----------------------------------------------------------------------


def test_router_hands_the_provider_the_gateway_id_verbatim():
    # The gateway's own id must survive routing intact — including the `@cf/` publisher
    # segment, whose slashes must not be mistaken for anything the router should strip.
    router = ProviderRouter()
    assert router._provider_name("aigw:@cf/zai-org/glm-5.2") == "aigw"
    assert router._bare("aigw:@cf/zai-org/glm-5.2") == "@cf/zai-org/glm-5.2"
    assert router._bare("aigw:anthropic/claude-sonnet-4.6") == "anthropic/claude-sonnet-4.6"


def test_every_curated_gateway_row_is_an_author_qualified_id():
    rows = [m for m in MATRIX if m.startswith("aigw:")]
    assert rows, "the matrix lost its Cloudflare AI Gateway rows"
    for full_id in rows:
        bare = full_id.split(":", 1)[1]
        assert "/" in bare, f"{full_id} has no author segment to route on"
        assert MATRIX[full_id].label.endswith("· via Cloudflare")


def test_no_google_models_ride_the_gateway():
    # Gemini already has its own relay in this fork; two routes to one vendor in one
    # picker is the support ticket this exclusion exists to prevent.
    for full_id in MATRIX:
        if full_id.startswith("aigw:"):
            assert "google" not in full_id and "gemini" not in full_id


@pytest.mark.parametrize(
    "model,vision",
    [
        ("aigw:anthropic/claude-sonnet-4.6", True),
        ("aigw:openai/gpt-5.5", True),
        ("aigw:@cf/zai-org/glm-5.2", False),
        ("aigw:xai/grok-4.3", False),
    ],
)
def test_curated_capabilities(model, vision):
    caps = capabilities_for(model)
    assert caps.tools and caps.streaming
    assert caps.vision is vision
    # Inline PDF parts were never probed on the gateway, so none of these claim it —
    # pdf_support.py rasterizes instead, which needs vision, not pdf.
    assert caps.pdf is False


@pytest.mark.parametrize(
    "model,vision",
    [
        # Custom (non-curated) ids fall through to the heuristics, which have to look past
        # the author segment or they would only ever see "openai" / "@cf".
        ("aigw:openai/gpt-4.1-mini", True),
        # In Cloudflare's catalog, deliberately not curated by us.
        ("aigw:anthropic/claude-opus-4.5", True),
        ("aigw:deepseek/deepseek-v9", False),
        ("aigw:@cf/qwen/qwen3-30b-a3b-fp8", False),
    ],
)
def test_uncurated_gateway_ids_are_judged_on_the_model_half(model, vision):
    assert model not in MATRIX
    caps = capabilities_for(model)
    assert caps.tools
    assert caps.vision is vision


# -- Anthropic family detection through the gateway --------------------------------


@pytest.mark.parametrize(
    "model,budget",
    [
        # Cloudflare writes dots where Anthropic writes dashes, and prefixes the author.
        # Both spellings must land on the same thinking config: Haiku 4.5 only accepts
        # budget_tokens, and 4.6+ only accepts adaptive — a mismatch is a hard 400.
        ("claude-haiku-4-5", True),
        ("anthropic/claude-haiku-4.5", True),
        ("claude-sonnet-4-6", False),
        ("anthropic/claude-sonnet-4.6", False),
    ],
)
def test_thinking_family_survives_the_gateway_spelling(model, budget):
    assert _uses_budget_thinking(model) is budget


def test_refusal_fallback_family_survives_the_gateway_spelling():
    assert _needs_refusal_fallback("anthropic/claude-fable-5") is True
    assert _needs_refusal_fallback("anthropic/claude-sonnet-4.6") is False


def test_gateway_claude_never_takes_the_refusal_fallback_beta():
    # The beta names its fallback by Anthropic's own model id, which is not a valid model
    # on the gateway — so the gateway's Claude client opts out entirely, whatever family
    # the model belongs to.
    client = _provider()._client_for("anthropic/claude-fable-5")
    assert client._refusal_fallback is False
    assert client._use_refusal_fallback("anthropic/claude-fable-5") is False


@pytest.mark.parametrize(
    "model,expected",
    [
        ("anthropic/claude-haiku-4.5", "enabled"),
        ("anthropic/claude-sonnet-4.6", "adaptive"),
    ],
)
def test_request_kwargs_pick_the_right_thinking_shape(model, expected):
    client = _provider(thinking_budget=1024)._client_for(model)
    kwargs = client._request_kwargs(
        model=model, messages=[{"role": "user", "content": "hi"}], tools=None, settings={}
    )
    assert kwargs["thinking"]["type"] == expected


# -- errors -------------------------------------------------------------------------


# Both 402 bodies end in "BYOK", and reading the transient one as the permanent one is
# not hypothetical: three flagship models were cut from the matrix on exactly that
# mistake, because a burst of probes tripped the rate limiter and only the status code
# was looked at. These pin the two apart, in both directions.

BUSY = "2021: Wholesale rate limit exceeded for this gateway. Please reduce request rate or use BYOK."
UNAVAILABLE = "2021: This model is not available via unified billing. Please use BYOK."


def test_byok_only_models_say_so():
    msg = friendly_model_error("aigw:thinkingmachines/inkling", Exception(UNAVAILABLE))
    assert msg and "BYOK" in msg
    assert "try again" not in msg  # permanent — do not tell them to wait


def test_a_busy_pool_is_not_reported_as_an_unavailable_model():
    msg = friendly_model_error("aigw:moonshotai/kimi-k3", Exception(BUSY))
    assert msg and "try again in a moment" in msg
    # The killer detail: this message also says "use BYOK", so a sloppy marker would
    # match it and send the user off to configure a key they do not need.
    assert "isn't covered" not in msg


def test_the_flagships_are_curated_not_written_off():
    # They answered 402 under a burst of probes and were briefly (wrongly) excluded.
    for mid in (
        "aigw:openai/gpt-5.6-sol",
        "aigw:anthropic/claude-fable-5",
        "aigw:anthropic/claude-opus-4.8",
    ):
        assert mid in MATRIX, f"{mid} works on Unified Billing — verified 2026-08-23"


def test_unrelated_errors_still_pass_through_untranslated():
    assert friendly_model_error("aigw:xai/grok-4.3", Exception("connection reset")) is None


# -- registry -----------------------------------------------------------------------


def test_descriptor_is_registered_with_a_curated_default():
    d = get_descriptor("aigw")
    assert d is not None and d.title == "Cloudflare AI Gateway"
    assert f"aigw:{d.recommended_model}" in MATRIX


def test_both_credentials_are_required_before_the_provider_counts_as_set_up():
    d = get_descriptor("aigw")
    assert descriptor_configured(d, {"account_id": ACCOUNT, "api_token": "t"}) is True
    # A token with no account has nowhere to go; the gateway name is optional.
    assert descriptor_configured(d, {"api_token": "t"}) is False
    assert descriptor_configured(d, {"account_id": ACCOUNT}) is False


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({}, "account ID"),
        ({"account_id": ACCOUNT}, "API token"),
    ],
)
def test_test_button_reports_missing_fields_without_a_round_trip(
    fields, expected, monkeypatch
):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: pytest.fail("verify should not call out with fields missing"),
    )
    out = verify_provider_key("aigw", fields=fields)
    assert out["ok"] is False and expected in out["error"]
