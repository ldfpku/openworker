"""Cloudflare AI Gateway provider — wire dispatch, credential plumbing, curated ids.

Deliberately offline. WHICH model ids the gateway serves was settled by calling the live
API (the findings are recorded in `matrix.py`); a test cannot re-litigate that without an
Access session and a bill. What can regress silently is everything around it: sending
Anthropic a request shaped for OpenAI, forwarding a model id with the `author/` prefix on
a wire that 404s on it (or stripping it on the one wire that requires it), or reading
`anthropic/claude-haiku-4-5` as an unknown Claude family and picking a thinking config it
rejects. Those are what these cover.
"""

from __future__ import annotations

import pytest

from coworker.providers import capabilities_for
from coworker.providers.aigateway_provider import (
    AIGatewayProvider,
    access_headers,
    normalise_base,
    resolve_settings,
    upstream_model,
    wire_for,
    wire_url,
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

BASE = "https://gateway.example.com"
SESSION = "access-jwt"


def _provider(**kw) -> AIGatewayProvider:
    return AIGatewayProvider(base_url=BASE, access_token=SESSION, **kw)


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


def test_each_wire_gets_its_own_path_under_the_gateway_domain():
    # Each SDK appends its own suffix, so these bases stop at different depths: the
    # Anthropic SDK adds `/v1/messages`, the OpenAI ones add `/responses` and
    # `/chat/completions`. Off-by-one here is a 404 nobody enjoys diagnosing.
    p = _provider()
    assert p._client_for("anthropic/claude-haiku-4-5")._base_url == BASE + "/anthropic"
    assert p._client_for("openai/gpt-5.6-sol")._base_url == BASE + "/openai/v1"
    assert (
        p._client_for("google-ai-studio/gemini-3.6-flash")._base_url == BASE + "/compat"
    )


def test_every_wire_authenticates_with_the_access_session_only():
    # Access is the authentication; the SDKs' own credential slots carry a placeholder
    # the gateway ignores. A real token appearing in any of them would be a regression
    # towards the per-person-token design this replaced.
    p = _provider()
    for model in ("anthropic/claude-haiku-4-5", "openai/gpt-5.6-sol", "x/y"):
        assert p._client_for(model)._default_headers["cf-access-token"] == SESSION
    assert p._client_for("openai/gpt-5.6-sol")._api_key != SESSION
    anthropic = p._client_for("anthropic/claude-haiku-4-5")
    assert anthropic._api_key is None and anthropic._auth_token != SESSION


def test_access_header_is_omitted_rather_than_sent_empty():
    assert "cf-access-token" not in access_headers("")
    assert "cf-access-token" not in access_headers("  ")


def test_the_sdk_user_agent_is_replaced_on_every_wire():
    # `OpenAI/Python …` and `Anthropic/Python …` match Cloudflare's AI-crawler bot
    # signatures; on a protected zone the edge answers 403 "Your request was blocked."
    # before Access even runs. Verified live 2026-08-23 — this override is what makes the
    # provider work at all there, so it is asserted rather than left to a comment.
    p = _provider()
    for model in ("anthropic/claude-haiku-4-5", "openai/gpt-5.6-sol", "x/y"):
        ua = p._client_for(model)._default_headers["User-Agent"]
        assert ua.startswith("openworker/")
        assert "/Python" not in ua


@pytest.mark.parametrize(
    "kwargs,missing",
    [
        ({"base_url": "", "access_token": "t"}, "gateway address"),
        ({"base_url": BASE, "access_token": ""}, "Access session"),
    ],
)
def test_missing_settings_say_which_one(kwargs, missing):
    p = AIGatewayProvider(**kwargs)
    with pytest.raises(RuntimeError, match=missing):
        p._client_for("x/y")


@pytest.mark.parametrize(
    "pasted",
    [
        "https://gateway.example.com",
        "https://gateway.example.com/",
        # What the dashboard actually shows people, and what they paste.
        "https://gateway.example.com/compat/chat/completions",
        "gateway.example.com",
    ],
)
def test_a_pasted_url_is_trimmed_back_to_its_origin(pasted):
    assert normalise_base(pasted) == BASE
    assert wire_url(pasted, "chat") == BASE + "/compat"


def test_profile_beats_environment(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AIGW_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", "env-session")
    assert resolve_settings({"base_url": BASE}) == (
        BASE,
        "env-session",  # not in the profile, so the env still supplies it
    )


def test_environment_fills_in_an_empty_profile(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_AIGW_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", "env-session")
    assert resolve_settings({}) == ("https://env.example.com", "env-session")


@pytest.mark.parametrize(
    "model,sent",
    [
        # Provider-native wires reach the vendor's own API, which has never heard of
        # Cloudflare's `author/` namespace.
        ("anthropic/claude-haiku-4-5", "claude-haiku-4-5"),
        ("openai/gpt-5.6-sol", "gpt-5.6-sol"),
        # `/compat` is the opposite: the prefix is how it picks a provider, and without
        # one it answers `2008 Invalid provider`.
        ("google-ai-studio/gemini-3.6-flash", "google-ai-studio/gemini-3.6-flash"),
        ("bare-model-no-author", "bare-model-no-author"),
    ],
)
def test_the_prefix_is_stripped_on_exactly_the_wires_that_reject_it(model, sent):
    assert upstream_model(model, wire_for(model)) == sent


def test_the_transformed_id_is_what_reaches_the_sub_client():
    # The stripping is useless if `complete`/`stream` forward the routed id anyway.
    seen: dict[str, Any] = {}

    class Spy:
        def complete(self, *, model, messages, tools=None, **kw):
            seen["complete"] = model

        def stream(self, *, model, messages, tools=None, **kw):
            seen["stream"] = model

    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": Spy(), "chat": Spy()},
    )
    p.complete(model="anthropic/claude-haiku-4-5", messages=[])
    p.stream(model="google-ai-studio/gemini-3.6-flash", messages=[])
    assert seen["complete"] == "claude-haiku-4-5"
    assert seen["stream"] == "google-ai-studio/gemini-3.6-flash"


# -- model ids ----------------------------------------------------------------------


def test_router_hands_the_provider_the_gateway_id_verbatim():
    # The gateway's own id must survive routing intact — including the `@cf/` publisher
    # segment, whose slashes must not be mistaken for anything the router should strip.
    # `@cf/` models are no longer curated, but a user can still type one as a custom id,
    # and that is exactly the shape most likely to break the split.
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


def test_gateway_rows_stay_within_the_three_curated_labs():
    # Owner call: the gateway carries a dozen authors plus Workers AI, and adding rows is
    # a one-line temptation. The picker is the thing being protected, so the boundary is
    # asserted rather than left to review.
    for full_id in MATRIX:
        if not full_id.startswith("aigw:"):
            continue
        author = full_id.split(":", 1)[1].split("/", 1)[0]
        assert author in {"openai", "anthropic", "google-ai-studio"}, full_id


def test_gateway_rows_are_text_and_vision_only():
    # No image-generation, TTS, transcription or realtime models: this app drives them as
    # chat models and would mislabel anything else. Every row is tool-capable too — a
    # model that cannot call tools is useless to the agent loop.
    for full_id in MATRIX:
        if not full_id.startswith("aigw:"):
            continue
        caps = capabilities_for(full_id)
        assert caps.tools and caps.streaming and caps.vision, full_id
        bare = full_id.split(":", 1)[1]
        assert not any(
            marker in bare
            for marker in ("tts", "whisper", "image", "-live", "realtime", "embed")
        ), full_id


def test_gateway_gemini_rows_are_a_subset_of_the_direct_ones():
    # Same spelling on both routes, `-preview` suffixes and all — this path forwards the
    # id to Google verbatim. But a strict SUBSET, not a copy: Unified Billing covers only
    # part of the line here (see the matrix comment), and 2.5 is deliberately direct-only.
    # A new gateway row that is not also a direct row is almost certainly a typo.
    direct_3x = {
        m.split(":", 1)[1] for m in MATRIX if m.startswith("gemini:gemini-3")
    }
    gateway = {
        m.split("/", 1)[1] for m in MATRIX if m.startswith("aigw:google-ai-studio/")
    }
    assert gateway and gateway <= direct_3x, sorted(gateway - direct_3x)
    assert not any(m.startswith("aigw:google-ai-studio/gemini-2") for m in MATRIX)


@pytest.mark.parametrize(
    "model",
    [
        "aigw:anthropic/claude-sonnet-5",
        "aigw:openai/gpt-5.6-sol",
        "aigw:google-ai-studio/gemini-3.6-flash",
    ],
)
def test_curated_capabilities(model):
    assert model in MATRIX
    caps = capabilities_for(model)
    assert caps.tools and caps.streaming and caps.vision
    # Inline PDF parts were never probed on the gateway, so none of these claim it —
    # pdf_support.py rasterizes instead, which needs vision, not pdf. Note the `gemini:`
    # rows DO claim pdf; the gateway ones deliberately do not.
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
        "aigw:anthropic/claude-opus-5",
    ):
        assert mid in MATRIX, f"{mid} works on Unified Billing — verified 2026-08-23"


def test_unrelated_errors_still_pass_through_untranslated():
    assert friendly_model_error("aigw:xai/grok-4.3", Exception("connection reset")) is None


# -- registry -----------------------------------------------------------------------


def test_descriptor_is_registered_with_a_curated_default():
    d = get_descriptor("aigw")
    assert d is not None and d.title == "Cloudflare AI Gateway"
    assert f"aigw:{d.recommended_model}" in MATRIX


def test_both_settings_are_required_before_the_provider_counts_as_set_up():
    d = get_descriptor("aigw")
    assert descriptor_configured(d, {"base_url": BASE, "access_token": "t"}) is True
    # A session with no address has nowhere to go, and vice versa.
    assert descriptor_configured(d, {"access_token": "t"}) is False
    assert descriptor_configured(d, {"base_url": BASE}) is False


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({}, "gateway address"),
        ({"base_url": BASE}, "Access session"),
    ],
)
def test_test_button_reports_missing_fields_without_a_round_trip(
    fields, expected, monkeypatch
):
    monkeypatch.delenv("CLOUDFLARE_AIGW_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: pytest.fail("verify should not call out with fields missing"),
    )
    out = verify_provider_key("aigw", fields=fields)
    assert out["ok"] is False and expected in out["error"]
