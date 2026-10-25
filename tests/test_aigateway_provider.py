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

import json
import re

import httpx
import pytest

from coworker.providers import capabilities_for
from coworker.providers.aigateway_provider import (
    AIGatewayProvider,
    DEFAULT_BASE_URL,
    ENV_DYNAMIC_ROUTING,
    _ROUTES,
    _Route,
    access_headers,
    context_window,
    dynamic_routing_enabled,
    fallback_for,
    fits_the_stand_in,
    normalise_base,
    resolve_settings,
    route_allowed,
    route_for,
    upstream_model,
    wire_for,
    wire_url,
)
from coworker.providers.anthropic_provider import (
    AnthropicProvider,
    _needs_refusal_fallback,
    _uses_budget_thinking,
)
from coworker.providers.errors import friendly_model_error, is_gateway_busy
from coworker.providers.matrix import MATRIX
from coworker.providers.openai_provider import DEFAULT_MAX_TOKENS, OpenAIProvider
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


def test_router_passes_the_saved_display_name_to_the_gateway_provider():
    class Secrets:
        def get(self, profile):
            assert profile == "provider:aigw"
            return {"base_url": BASE, "access_token": SESSION, "display_name": "DF"}

    router = ProviderRouter(Secrets())
    gateway = router._client_for("aigw:x/y")
    headers = gateway._client_for("x/y")._default_headers
    assert json.loads(headers["cf-aig-metadata"]) == {"display_name": "DF"}


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
    assert "cf-aig-metadata" not in access_headers(SESSION)
    assert "cf-aig-metadata" not in access_headers(SESSION, "   ")


def test_display_name_metadata_reaches_every_wire_without_changing_access_identity():
    p = _provider(display_name="  刘德富  ")
    for model in ("anthropic/claude-haiku-4-5", "openai/gpt-5.6-sol", "x/y"):
        headers = p._client_for(model)._default_headers
        assert headers["cf-access-token"] == SESSION
        assert json.loads(headers["cf-aig-metadata"]) == {"display_name": "刘德富"}
        # The display label must not create a second User Insights identity. Access owns
        # cf.user_id; custom user/user_id fields could split the same person's usage.
        assert set(json.loads(headers["cf-aig-metadata"])) == {"display_name"}


def test_oauth_display_name_metadata_is_ascii_on_the_wire():
    p = AIGatewayProvider(
        base_url=BASE, token_provider=lambda: "oauth-tok", display_name="张三"
    )
    headers = p._client_for("x/y")._default_headers
    assert headers["Authorization"] == "Bearer oauth-tok"
    assert headers["cf-aig-metadata"].isascii()
    assert json.loads(headers["cf-aig-metadata"]) == {"display_name": "张三"}


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
        # coworker/__init__.py used to hardcode __version__ = "0.0.0", which made
        # every packaged build's gateway log entry look identical and impossible to
        # tell apart by version. It must now come from the real app version (a
        # semver stamped in at packaging time by packaging/write_version.py) or,
        # in an unpackaged checkout with no coworker/_version.py, the literal "dev".
        assert ua != "openworker/0.0.0"
        assert re.fullmatch(r"openworker/(dev|\d+\.\d+\.\d+\S*)", ua)


@pytest.mark.parametrize(
    "kwargs,missing",
    [
        ({"base_url": "", "access_token": "t"}, "gateway address"),
        ({"base_url": BASE, "access_token": ""}, "not signed in"),
    ],
)
def test_missing_settings_say_which_one(kwargs, missing):
    p = AIGatewayProvider(**kwargs)
    with pytest.raises(RuntimeError, match=missing):
        p._client_for("x/y")


# -- the OAuth session ---------------------------------------------------------------
# Signing in supersedes the pasted JWT, and the two credentials ride different headers:
# an OAuth bearer goes where Access's own challenge asks for it (`Authorization: Bearer`),
# a pasted session stays on `cf-access-token`.


def test_an_oauth_session_travels_as_a_bearer_not_as_a_pasted_session():
    p = AIGatewayProvider(base_url=BASE, token_provider=lambda: "oauth-tok")
    for model in ("anthropic/claude-haiku-4-5", "openai/gpt-5.6-sol", "x/y"):
        headers = p._client_for(model)._default_headers
        assert headers["Authorization"] == "Bearer oauth-tok"
        assert "cf-access-token" not in headers


def test_signing_in_wins_over_a_session_left_from_the_old_flow():
    p = AIGatewayProvider(
        base_url=BASE, access_token=SESSION, token_provider=lambda: "oauth-tok"
    )
    headers = p._client_for("x/y")._default_headers
    assert headers["Authorization"] == "Bearer oauth-tok"
    assert "cf-access-token" not in headers


def test_the_pasted_session_still_works_when_nobody_has_signed_in():
    # The old route has to keep working: a colleague mid-migration, or a headless run
    # where no browser can be opened, still has only the pasted JWT.
    p = AIGatewayProvider(base_url=BASE, access_token=SESSION, token_provider=lambda: "")
    headers = p._client_for("x/y")._default_headers
    assert headers["cf-access-token"] == SESSION
    assert "Authorization" not in headers


def test_a_broken_sign_in_falls_back_instead_of_taking_the_provider_down():
    def boom() -> str:
        raise RuntimeError("secret store unreadable")

    p = AIGatewayProvider(base_url=BASE, access_token=SESSION, token_provider=boom)
    assert p._client_for("x/y")._default_headers["cf-access-token"] == SESSION


def test_a_broken_sign_in_without_a_pasted_session_preserves_the_real_error():
    def boom() -> str:
        raise RuntimeError("token refresh failed: Invalid port")

    p = AIGatewayProvider(base_url=BASE, token_provider=boom)
    with pytest.raises(RuntimeError, match="token refresh failed: Invalid port"):
        p._client_for("x/y")


def test_a_refreshed_token_reaches_the_next_request():
    # The credential is baked into each sub-client's headers at build time, so a silent
    # refresh is only real if the cached sub-clients are dropped. Without this the
    # provider would keep presenting the expired bearer until the app restarted.
    tokens = iter(["first", "first", "second"])
    p = AIGatewayProvider(base_url=BASE, token_provider=lambda: next(tokens))
    first = p._client_for("x/y")
    assert first._default_headers["Authorization"] == "Bearer first"
    assert p._client_for("x/y") is first  # unchanged token reuses the sub-client
    second = p._client_for("x/y")
    assert second is not first
    assert second._default_headers["Authorization"] == "Bearer second"


def test_rotation_never_evicts_an_injected_client():
    spy = object()
    tokens = iter(["a", "b"])
    p = AIGatewayProvider(
        base_url=BASE, token_provider=lambda: next(tokens), clients={"chat": spy}
    )
    assert p._client_for("x/y") is spy
    assert p._client_for("x/y") is spy


def test_the_anthropic_wire_leaves_the_authorization_slot_to_access():
    # The Anthropic SDK's `auth_token` would claim `Authorization: Bearer <placeholder>`,
    # colliding with the Access bearer; under OAuth the placeholder moves to `x-api-key`.
    signed_in = AIGatewayProvider(base_url=BASE, token_provider=lambda: "oauth-tok")
    assert signed_in._client_for("anthropic/claude-haiku-4-5")._auth_token is None
    pasted = AIGatewayProvider(base_url=BASE, access_token=SESSION)
    assert pasted._client_for("anthropic/claude-haiku-4-5")._auth_token is not None


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


def test_the_company_gateway_is_the_address_of_last_resort(monkeypatch):
    # Zero config is a complete setup (owner call 2026-08-27): with nothing stored and
    # nothing in the environment, the built-in company gateway answers — which is what
    # lets the settings pane drop the address field entirely. The session has no such
    # default: an address can be public, a credential cannot.
    monkeypatch.delenv("CLOUDFLARE_AIGW_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", raising=False)
    assert resolve_settings({}) == (DEFAULT_BASE_URL, "")


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
            return iter(())

    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": Spy(), "chat": Spy()},
    )
    p.complete(model="anthropic/claude-haiku-4-5", messages=[])
    # `stream` is a generator now (dynamic routing has to catch the sub-client's error),
    # so nothing reaches the sub-client until it is iterated.
    list(p.stream(model="google-ai-studio/gemini-3.6-flash", messages=[]))
    assert seen["complete"] == "claude-haiku-4-5"
    assert seen["stream"] == "google-ai-studio/gemini-3.6-flash"


# -- dynamic routing (429 → the same-tier stand-in) ---------------------------------
#
# The gateway's per-model wholesale limiter refuses a second in-flight request for the
# same model with 429 `Wholesale Rate limited` — every 429 this gateway has produced so
# far. Cloudflare's own Dynamic Route can fail over to a same-tier model, but its fallback
# edge fires on "error or timeout" and cannot be told "429 specifically", so the decision
# to reach for the route lives here. These cover the decision, not the route graph.


class _Busy(Exception):
    """What the OpenAI SDK raises for the gateway's 429 (body is plain `Rate limited`)."""

    status_code = 429

    def __init__(self):
        super().__init__(
            "Error code: 429 - {'code': 2018, 'message': 'Wholesale Rate limited'}"
        )


class _Spy:
    """A sub-client that records what it was asked for, and optionally fails."""

    def __init__(self, error: Exception | None = None, chunks=()):
        self.calls: list[dict[str, Any]] = []
        self.error = error
        self.chunks = list(chunks)

    def complete(self, *, model, messages, tools=None, **kw):
        self.calls.append({"model": model, **kw})
        if self.error is not None:
            raise self.error
        return {"model": model}

    def stream(self, *, model, messages, tools=None, **kw):
        self.calls.append({"model": model, **kw})
        if self.error is not None:
            raise self.error
        return iter(self.chunks)


def test_every_routed_model_and_stand_in_is_a_curated_gateway_row():
    # A route naming an id the picker cannot offer is dead weight; a route naming an id
    # the matrix spells differently is worse — the retry would 404 on a live 429.
    assert _ROUTES, "the routing table lost its entries"
    for bare, route in _ROUTES.items():
        assert f"aigw:{bare}" in MATRIX, bare
        assert f"aigw:{route.fallback}" in MATRIX, route.fallback
        assert route.fallback != bare, bare
        # `ow-<vendor>-<model>`, dots flattened — the spelling gateway-guard's
        # ROUTE_MODELS is keyed on.
        assert route.name == "ow-" + bare.replace("/", "-").replace(".", "-")


def test_a_429_never_resends_to_a_stand_in_outside_the_persons_list():
    # The guard is an allowlist and judges a `dynamic/<route>` call by BOTH of its ends:
    # with the stand-in unticked the re-send is a guaranteed 403, and with it ticked a
    # busy moment must still never hand someone a model their administrator did not open.
    # So the provider asks the person's server list before re-sending — for every row.
    for bare, route in _ROUTES.items():
        wire = wire_for(bare)
        for listed, resent in (
            ({bare, route.fallback}, True),
            ({bare}, False),  # stand-in not on the list
            ({route.fallback}, False),  # (cannot 429 in practice; still never re-sent)
            (set(), False),  # no successful pull yet
            (None, False),
        ):
            chat = _Spy()
            p = AIGatewayProvider(
                base_url=BASE,
                access_token=SESSION,
                clients={wire: _Spy(error=_Busy()), "chat": chat},
                allowed_models=lambda listed=listed: listed,
            )
            if resent:
                assert p.complete(model=bare, messages=[]) == {"model": f"dynamic/{route.name}"}
                assert [c["model"] for c in chat.calls] == [f"dynamic/{route.name}"]
            else:
                with pytest.raises(_Busy):
                    p.complete(model=bare, messages=[])
                assert chat.calls == [], (bare, listed)


def test_a_streamed_429_obeys_the_same_list_gate():
    chat = _Spy(chunks=["x"])
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
        allowed_models=lambda: {"anthropic/claude-opus-5"},  # terra, the stand-in, is not on it
    )
    with pytest.raises(_Busy):
        list(p.stream(model="anthropic/claude-opus-5", messages=[]))
    assert chat.calls == []
    p.bind_allowed_models(lambda: {"anthropic/claude-opus-5", "openai/gpt-5.6-terra"})
    assert list(p.stream(model="anthropic/claude-opus-5", messages=[])) == ["x"]
    assert chat.calls[0]["model"] == "dynamic/ow-anthropic-claude-opus-5"


def test_an_unwired_provider_is_not_gated_and_a_broken_reader_means_no_resend():
    # No reader at all (headless `agent.py`, these unit tests): nothing to ask, so the
    # guard's own 403 stays the only judge and the re-send is attempted as before.
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE, access_token=SESSION, clients={"messages": _Spy(error=_Busy()), "chat": chat}
    )
    assert p.complete(model="anthropic/claude-opus-5", messages=[])
    assert len(chat.calls) == 1

    def boom():
        raise RuntimeError("catalog cache unreadable")

    # A reader that fails is an unknown list — never a reason to send somewhere unvetted.
    p.bind_allowed_models(boom)
    with pytest.raises(_Busy):
        p.complete(model="anthropic/claude-opus-5", messages=[])
    assert len(chat.calls) == 1
    assert route_allowed("anthropic/claude-opus-5", None) is False


def test_the_utility_tier_is_deliberately_unrouted():
    # Haiku and Luna are the cheap summariser (auto-title) siblings; the limiter has never
    # fired there, and a route on them would put a second model behind what is meant to
    # be the cheapest call. Adding one should be a decision, not a drift.
    assert route_for("anthropic/claude-haiku-4-5") is None
    assert route_for("openai/gpt-5.6-luna") is None
    assert route_for("google-ai-studio/gemini-3.6-flash") is None


def test_route_lookups_accept_the_routed_id_as_well_as_the_bare_one():
    # The provider is handed the bare id; the GUI settings payload is keyed on `aigw:`.
    assert route_for("anthropic/claude-opus-5") == "ow-anthropic-claude-opus-5"
    assert route_for("aigw:anthropic/claude-opus-5") == "ow-anthropic-claude-opus-5"
    assert fallback_for("AIGW:Anthropic/Claude-Opus-5") == "openai/gpt-5.6-terra"
    assert route_for("openai/gpt-4o") is None and fallback_for("nonsense") is None


@pytest.mark.parametrize("value,on", [("0", False), ("off", False), ("no", False),
                                      ("false", False), ("1", True), ("", True)])
def test_the_env_switch_is_the_rollback_lever(monkeypatch, value, on):
    monkeypatch.setenv(ENV_DYNAMIC_ROUTING, value)
    assert dynamic_routing_enabled() is on
    monkeypatch.delenv(ENV_DYNAMIC_ROUTING, raising=False)
    assert dynamic_routing_enabled() is True  # absent = on


def test_a_dynamic_route_addresses_compat_with_its_prefix_intact():
    # The retry's whole URL contract: `/compat`, and the `dynamic/` prefix survives —
    # strip it and the gateway answers `2008 Invalid provider` like any other bare id.
    assert wire_for("dynamic/ow-anthropic-claude-opus-5") == "chat"
    assert (
        upstream_model("dynamic/ow-anthropic-claude-opus-5", "chat")
        == "dynamic/ow-anthropic-claude-opus-5"
    )
    assert wire_url(BASE, "chat") == BASE + "/compat"


def test_a_rate_limited_completion_is_resent_on_the_models_route():
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    out = p.complete(model="anthropic/claude-opus-5", messages=[], tools=[{"x": 1}])
    assert out == {"model": "dynamic/ow-anthropic-claude-opus-5"}
    assert chat.calls[0]["model"] == "dynamic/ow-anthropic-claude-opus-5"


@pytest.mark.parametrize(
    "model,route",
    [
        # OpenAI primary — the classic case.
        ("openai/gpt-5.6-sol", "dynamic/ow-openai-gpt-5-6-sol"),
        # Anthropic primary whose STAND-IN is an OpenAI tier. The client cannot know which
        # end the gateway picks, so the pin has to be there either way; without it this
        # re-send reaches Chat Completions unpinned and only recovers via
        # `openai_provider._param_fix_retry` — a third round-trip on a turn already two
        # requests deep.
        ("anthropic/claude-opus-5", "dynamic/ow-anthropic-claude-opus-5"),
    ],
)
def test_effort_is_pinned_whenever_either_end_of_the_route_is_an_openai_tier(
    model, route
):
    # `_pin_reasoning_effort` matches on a `gpt-5.6…` model string and the resend's is
    # `dynamic/ow-…`, so without this the retry would hit Chat Completions' refusal of
    # function tools at any effort other than "none".
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={
            wire_for(model): _Spy(error=_Busy()),
            "chat": chat,
        },
    )
    p.complete(model=model, messages=[], tools=[{"x": 1}])
    assert chat.calls[0]["model"] == route
    assert chat.calls[0]["reasoning_effort"] == "none"


def test_an_all_anthropic_route_would_carry_no_effort_knob():
    # No such pair exists in today's table (every route has an OpenAI end), so this pins
    # the RULE rather than a row: the knob is for OpenAI's Chat Completions refusal, and
    # a route that can never land there should not carry it. The max-tokens rename below
    # is unconditional, though, so it still shows up here.
    assert AIGatewayProvider._retry_settings(
        "anthropic/claude-opus-5",
        _Route("ow-made-up", "anthropic/claude-sonnet-5"),
        {"temperature": 0.2},
    ) == {"temperature": 0.2, "max_completion_tokens": DEFAULT_MAX_TOKENS}


def test_an_explicit_effort_setting_is_not_overwritten_by_the_resend():
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"responses": _Spy(error=_Busy()), "chat": chat},
    )
    p.complete(model="openai/gpt-5.6-sol", messages=[], reasoning_effort="low")
    assert chat.calls[0]["reasoning_effort"] == "low"


# -- the resend's `max_tokens` → `max_completion_tokens` rename ---------------------
#
# `openai_provider.complete`/`stream` default `kwargs.setdefault("max_tokens", ...)`, and
# EVERY dynamic resend goes out through that same `OpenAIProvider` on the `chat` wire
# (`_client_for_wire("chat")`). GPT-5.6 on Chat Completions 400s on `max_tokens` ("use
# max_completion_tokens"); Cloudflare's fallback edge cannot distinguish that 400 from any
# other failure, so it just falls through to the route's Anthropic stand-in and answers
# 200 — the caller's chosen model was silently never retried. Verified live 2026-09-16
# that `/compat` accepts `max_completion_tokens` for an anthropic/* id too (a real
# `usage.completion_tokens` came back), so the rename applies to every route, not only the
# ones whose primary is OpenAI.


def test_a_resend_renames_max_tokens_to_max_completion_tokens():
    # OpenAI-primary route — the classic case (`ow-openai-gpt-5-6-terra`).
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"responses": _Spy(error=_Busy()), "chat": chat},
    )
    p.complete(model="openai/gpt-5.6-terra", messages=[], max_tokens=4096)
    assert chat.calls[0]["model"] == "dynamic/ow-openai-gpt-5-6-terra"
    assert chat.calls[0]["max_completion_tokens"] == 4096
    assert "max_tokens" not in chat.calls[0]


def test_an_anthropic_primary_resend_also_renames_max_tokens():
    # rename_universal: the client cannot know which end of the route actually answers
    # (an Anthropic-primary route can still land on its OpenAI stand-in), and `/compat`
    # accepts the renamed field for every author it fronts — so this is not conditioned on
    # which end is OpenAI, unlike the reasoning_effort pin above.
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    p.complete(model="anthropic/claude-opus-5", messages=[], max_tokens=4096)
    assert chat.calls[0]["model"] == "dynamic/ow-anthropic-claude-opus-5"
    assert chat.calls[0]["max_completion_tokens"] == 4096
    assert "max_tokens" not in chat.calls[0]


def test_a_resend_with_no_max_tokens_setting_still_gets_a_completion_ceiling():
    # Without this, `OpenAIProvider.complete`'s own `setdefault("max_tokens", ...)` would
    # re-add the very field the rename above removes.
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    p.complete(model="anthropic/claude-sonnet-5", messages=[])
    assert chat.calls[0]["max_completion_tokens"] == DEFAULT_MAX_TOKENS
    assert "max_tokens" not in chat.calls[0]


def test_an_already_renamed_setting_is_left_alone():
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"responses": _Spy(error=_Busy()), "chat": chat},
    )
    p.complete(model="openai/gpt-5.6-terra", messages=[], max_completion_tokens=999)
    assert chat.calls[0]["max_completion_tokens"] == 999
    assert "max_tokens" not in chat.calls[0]


def test_a_streamed_resend_also_renames_max_tokens():
    chat = _Spy(chunks=["b"])
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"responses": _Spy(error=_Busy()), "chat": chat},
    )
    assert list(
        p.stream(model="openai/gpt-5.6-terra", messages=[], max_tokens=2048)
    ) == ["b"]
    assert chat.calls[0]["model"] == "dynamic/ow-openai-gpt-5-6-terra"
    assert chat.calls[0]["max_completion_tokens"] == 2048
    assert "max_tokens" not in chat.calls[0]


def test_only_a_busy_shared_pool_earns_a_resend():
    # A bad id, a model off the person's list or an empty balance would fail identically
    # on the stand-in; retrying those only buys a second round-trip and a second bill.
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={
            "messages": _Spy(error=RuntimeError("Error code: 404 - model not found")),
            "chat": chat,
        },
    )
    with pytest.raises(RuntimeError):
        p.complete(model="anthropic/claude-opus-5", messages=[])
    assert chat.calls == []


def test_an_unrouted_model_keeps_its_429():
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    with pytest.raises(_Busy):
        p.complete(model="anthropic/claude-haiku-4-5", messages=[])
    assert chat.calls == []


def test_the_env_switch_off_restores_the_old_behaviour(monkeypatch):
    monkeypatch.setenv(ENV_DYNAMIC_ROUTING, "0")
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    with pytest.raises(_Busy):
        p.complete(model="anthropic/claude-opus-5", messages=[])
    assert chat.calls == []


def test_when_the_route_fails_too_the_original_429_is_what_surfaces():
    # Not the route's error: a missing route (the Cloudflare side not deployed yet) and a
    # busy stand-in both mean "this tier is unavailable right now", and only the original
    # body carries the marker `errors.py` reads.
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={
            "messages": _Spy(error=_Busy()),
            "chat": _Spy(error=RuntimeError("Error code: 404 - route not found")),
        },
    )
    with pytest.raises(_Busy) as caught:
        p.complete(model="anthropic/claude-fable-5", messages=[])
    assert caught.value.aigw_route == "ow-anthropic-claude-fable-5"
    assert caught.value.aigw_fallback == "openai/gpt-5.6-sol"
    # …and the tag is what turns the message from "go configure BYOK" into "wait".
    friendly = friendly_model_error("aigw:anthropic/claude-fable-5", caught.value)
    assert friendly and "ow-anthropic-claude-fable-5" in friendly
    assert "BYOK" not in friendly


# -- the stand-in's window ----------------------------------------------------------
#
# Same tier is not the same window. Both 1M Claude tiers fail over to gpt-5.6-terra, whose
# 400k is the one unverified number in the matrix — so a long session's 429 must not be
# re-sent into a context overflow. The user would then be told "the shared pool is busy"
# (the original 429 is what surfaces), which is the wrong diagnosis entirely.


def _turn_of(tokens: int) -> list[dict[str, Any]]:
    """A message list `estimate_tokens` scores at roughly `tokens` (chars/4, + JSON)."""
    return [{"role": "user", "content": "x" * (tokens * 4)}]


def test_a_turn_too_big_for_the_stand_in_is_not_resent():
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    # Opus 5 (1,000,000) falls back to Terra (400,000). A 500k turn fits the primary and
    # cannot fit the stand-in; re-sending it buys a guaranteed second failure.
    with pytest.raises(_Busy):
        p.complete(model="anthropic/claude-opus-5", messages=_turn_of(500_000))
    assert chat.calls == []


def test_a_turn_that_fits_the_stand_in_is_still_resent():
    # The other side of the same gate — the guard must not swallow ordinary turns.
    chat = _Spy()
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    p.complete(model="anthropic/claude-opus-5", messages=_turn_of(50_000))
    assert chat.calls[0]["model"] == "dynamic/ow-anthropic-claude-opus-5"


def test_the_window_gate_reserves_headroom_for_the_reply():
    # `estimate_tokens` counts the prompt only, so filling the stand-in to the brim would
    # leave nowhere for the answer to go. Terra is 400,000; the ceiling is 90% of it.
    terra = _Route("ow-anthropic-claude-opus-5", "openai/gpt-5.6-terra")
    assert context_window("openai/gpt-5.6-terra") == 400_000
    assert fits_the_stand_in(terra, _turn_of(359_000))
    assert not fits_the_stand_in(terra, _turn_of(361_000))


def test_a_stand_in_with_no_published_window_is_not_second_guessed():
    # No matrix number means no ceiling to test against; inventing one would be the worse
    # guess (it would silently disable the re-send for that route).
    unknown = _Route("ow-made-up", "openai/gpt-7-unpublished")
    assert context_window("openai/gpt-7-unpublished") is None
    assert fits_the_stand_in(unknown, _turn_of(5_000_000))


def test_a_stream_that_has_emitted_nothing_is_resent_on_the_route():
    chat = _Spy(chunks=["b"])
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    assert list(p.stream(model="anthropic/claude-sonnet-5", messages=[])) == ["b"]
    assert chat.calls[0]["model"] == "dynamic/ow-anthropic-claude-sonnet-5"


def test_a_stream_that_already_emitted_is_never_replayed():
    # Re-sending after the user has watched text arrive would duplicate the turn.
    chat = _Spy(chunks=["never"])

    class _HalfWay:
        def stream(self, *, model, messages, tools=None, **kw):
            yield "a"
            raise _Busy()

    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _HalfWay(), "chat": chat},
    )
    out = p.stream(model="anthropic/claude-sonnet-5", messages=[])
    assert next(out) == "a"
    with pytest.raises(_Busy):
        next(out)
    assert chat.calls == []


def test_when_a_streamed_route_fails_too_the_original_429_is_what_surfaces():
    # `complete`'s twin, and the more fragile half: the retry lives in a second `try`
    # AFTER the generator's `except`, so `first_error` has to survive the hand-off.
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={
            "messages": _Spy(error=_Busy()),
            "chat": _Spy(error=RuntimeError("Error code: 404 - route not found")),
        },
    )
    with pytest.raises(_Busy) as caught:
        list(p.stream(model="anthropic/claude-sonnet-5", messages=[]))
    assert caught.value.aigw_route == "ow-anthropic-claude-sonnet-5"
    assert caught.value.aigw_fallback == "openai/gpt-5.6-terra"
    friendly = friendly_model_error("aigw:anthropic/claude-sonnet-5", caught.value)
    assert friendly and "ow-anthropic-claude-sonnet-5" in friendly


def test_a_route_that_dies_mid_stream_keeps_its_text_and_blames_the_first_error():
    # The accepted limitation, pinned so nobody debugs it twice: the chunks the STAND-IN
    # already handed out stay handed out, and the error the caller finally sees is still
    # the original 429 — so the copy says "the stand-in was busy too" even when the route
    # actually died of something else. Diagnosing that needs the gateway's Logs.
    class _DiesLate:
        def stream(self, *, model, messages, tools=None, **kw):
            yield "half an answer"
            raise RuntimeError("connection reset")

    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": _DiesLate()},
    )
    out = p.stream(model="anthropic/claude-sonnet-5", messages=[])
    assert next(out) == "half an answer"
    with pytest.raises(_Busy) as caught:
        next(out)
    assert caught.value.aigw_route == "ow-anthropic-claude-sonnet-5"


def test_the_window_gate_applies_to_streams_as_well():
    chat = _Spy(chunks=["never"])
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=_Busy()), "chat": chat},
    )
    with pytest.raises(_Busy):
        list(p.stream(model="anthropic/claude-sonnet-5", messages=_turn_of(500_000)))
    assert chat.calls == []


def test_stream_raises_on_the_first_next_not_at_call_time():
    # The consequence of making `stream` a generator, pinned deliberately: `engine._astream`
    # calls and iterates inside one `try`, so this is invisible there — but a future caller
    # that only calls `stream()` and inspects the result would silently see no error.
    p = AIGatewayProvider(
        base_url=BASE,
        access_token=SESSION,
        clients={"messages": _Spy(error=RuntimeError("nope")), "chat": _Spy()},
    )
    it = p.stream(model="anthropic/claude-haiku-4-5", messages=[])
    with pytest.raises(RuntimeError):
        next(it)


@pytest.mark.parametrize(
    "text,status,busy",
    [
        # The 429 as the SDK renders it, and the bare body the gateway actually sends.
        ("Error code: 429 - {'code': 2018, 'message': 'Wholesale Rate limited'}", 429, True),
        ("Error code: 429 - Rate limited", 429, True),
        # The older 402 spelling of the same condition.
        ("Error code: 402 - wholesale rate limit exceeded for this gateway", 402, True),
        # No status attribute at all — the rendered "429" is the only evidence, and it
        # counts: the SDKs' `str(exc)` always carries it.
        ("Error code: 429 - you are being rate limited", None, True),
        # `rate limited` without a 429 is not this condition.
        ("Error code: 400 - rate limited", 400, False),
        # The permanent 402 must never be read as busy.
        ("Error code: 402 - This model is not available via unified billing.", 402, False),
        ("Error code: 500 - internal error", 500, False),
    ],
)
def test_is_gateway_busy_reads_the_body_not_just_the_status(text, status, busy):
    exc = RuntimeError(text)
    if status is not None:
        exc.status_code = status
    assert is_gateway_busy(exc) is busy


def test_the_429_copy_never_tells_people_to_go_set_up_byok():
    # 402-permanent says "store your own key"; 429-busy says "wait". Conflating the two
    # is exactly how three good models were cut from the matrix once already.
    busy = friendly_model_error("aigw:openai/gpt-5.6-sol", _Busy())
    assert busy and "BYOK" not in busy
    permanent = friendly_model_error(
        "aigw:openai/gpt-5.6-sol",
        RuntimeError("Error code: 402 - This model is not available via unified billing."),
    )
    assert permanent and "BYOK" in permanent


def test_another_vendors_own_429_is_not_dressed_up_as_the_shared_pool():
    # `rate limited` is a loose phrase; a direct OpenAI/Anthropic 429 saying it is that
    # account's own limiter, which no same-tier stand-in on our gateway would fix. It has
    # to keep its raw message rather than gain a sentence about Cloudflare.
    direct = RuntimeError("Error code: 429 - you are being rate limited")
    assert friendly_model_error("gpt-5.6-sol", direct) is None
    # The same body on a gateway-routed id IS ours, and says so.
    assert "Cloudflare" in (friendly_model_error("aigw:openai/gpt-5.6-sol", direct) or "")


def _everything_routed() -> frozenset[str]:
    """A person whose list carries every routed model and every stand-in."""
    return frozenset(_ROUTES) | frozenset(r.fallback for r in _ROUTES.values())


def test_the_picker_badge_map_is_labels_for_routed_models_only():
    from coworker.server.manager import SessionManager

    labels = {mid: e.label for mid, e in MATRIX.items()}
    out = SessionManager._model_fallbacks(labels, _everything_routed())
    assert out["aigw:anthropic/claude-fable-5"] == "GPT-5.6 Sol · via Cloudflare"
    assert out["aigw:openai/gpt-5.6-sol"] == "Claude Opus 5 · via Cloudflare"
    assert set(out) == {f"aigw:{m}" for m in _ROUTES}
    # A stand-in the matrix has no label for is dropped rather than shown as a raw id.
    assert SessionManager._model_fallbacks({}, _everything_routed()) == {}


def test_the_picker_badge_map_only_covers_routes_on_the_persons_list():
    # The badge says "survives a busy pool". The guard refuses the route unless BOTH ends
    # are on the caller's list, so a badge for anything less would be a promise the
    # re-send (same `route_allowed` test) does not keep.
    from coworker.server.manager import SessionManager

    labels = {mid: e.label for mid, e in MATRIX.items()}
    some = frozenset({"anthropic/claude-opus-5", "openai/gpt-5.6-terra", "anthropic/claude-fable-5"})
    assert SessionManager._model_fallbacks(labels, some) == {
        "aigw:anthropic/claude-opus-5": "GPT-5.6 Terra · via Cloudflare"
    }
    # No list (never pulled) → no badge for anything.
    assert SessionManager._model_fallbacks(labels, None) == {}
    assert SessionManager._model_fallbacks(labels, frozenset()) == {}


def test_the_picker_badge_map_respects_the_rollback_switch(monkeypatch):
    from coworker.server.manager import SessionManager

    monkeypatch.setenv(ENV_DYNAMIC_ROUTING, "off")
    labels = {mid: e.label for mid, e in MATRIX.items()}
    assert SessionManager._model_fallbacks(labels, _everything_routed()) == {}


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


def test_the_pane_only_asks_for_an_optional_display_name():
    # No address or session field may reappear: signing in remains the whole credential.
    # The one non-credential field is the optional User Insights label.
    d = get_descriptor("aigw")
    assert [f.key for f in d.fields] == ["display_name"]
    assert d.fields[0].required is False
    assert d.fields[0].secret is False


def test_configured_means_holding_a_credential_not_an_address(monkeypatch):
    # With the address baked in it can no longer count toward "configured" — otherwise a
    # fresh install would read "✓ Connected" before anyone signed in. What counts is a
    # credential: the sign-in state aigw_auth keeps inside the profile, a pasted session,
    # or the env session a headless machine sets.
    monkeypatch.delenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", raising=False)
    d = get_descriptor("aigw")
    assert descriptor_configured(d, {}) is False
    assert descriptor_configured(d, {"base_url": BASE}) is False
    assert descriptor_configured(d, {"access_token": "t"}) is True
    assert descriptor_configured(d, {"oauth": {"access_token": "a"}}) is True
    assert descriptor_configured(d, {"oauth": {"refresh_token": "r"}}) is True
    monkeypatch.setenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", "env-session")
    assert descriptor_configured(d, {}) is True


def test_test_button_asks_for_a_sign_in_not_an_address(monkeypatch):
    # No settings at all: the built-in address fills itself in, so the only thing Test can
    # be missing is a credential — and it must say so without a network round trip.
    monkeypatch.delenv("CLOUDFLARE_AIGW_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", raising=False)
    for verb in ("httpx.get", "httpx.post"):
        monkeypatch.setattr(
            verb,
            lambda *a, **k: pytest.fail("verify should not call out without a credential"),
        )
    out = verify_provider_key("aigw", fields={})
    assert out["ok"] is False and "Sign in" in out["error"]
    assert "address" not in out["error"]  # nothing to fill any more — never ask for it


# -- the Test button: ask the guard which model to probe, then probe it ------------------


class _Http:
    """Offline stand-in for the Test's two requests. `listing` answers `GET /gate/models`,
    `completion` answers the POST; every call is recorded in order."""

    def __init__(self, monkeypatch, listing, completion=(200, {})):
        self.calls: list[dict] = []
        self._listing, self._completion = listing, completion
        monkeypatch.setattr("httpx.get", self._get)
        monkeypatch.setattr("httpx.post", self._post)

    @staticmethod
    def _resp(status, body):
        import json as _json

        class _Resp:
            status_code = status
            text = body if isinstance(body, str) else _json.dumps(body, ensure_ascii=False)

            def json(self):
                if isinstance(body, str):
                    raise ValueError("not json")
                return body

        return _Resp()

    def _get(self, url, headers=None, **kwargs):
        self.calls.append({"verb": "GET", "url": url, "headers": dict(headers or {})})
        if isinstance(self._listing, Exception):
            raise self._listing
        return self._resp(*self._listing)

    def _post(self, url, headers=None, json=None, **kwargs):
        self.calls.append(
            {"verb": "POST", "url": url, "headers": dict(headers or {}), "json": json}
        )
        if isinstance(self._completion, Exception):
            raise self._completion
        return self._resp(*self._completion)

    @property
    def verbs(self) -> list[str]:
        return [c["verb"] for c in self.calls]


_SIGNED_IN = {"base_url": BASE, "access_token": "stale", "oauth_token": "fresh"}
_LISTING = {
    "email": "a@smjtools.com",
    "role": "employee",
    "exempt": False,
    "models": [
        {"id": "openai/gpt-5.6-terra", "family": "openai/", "context": None, "created": None},
        {"id": "google-ai-studio/gemini-3.6-flash", "family": "google-ai-studio/"},
    ],
    "probe": "google-ai-studio/gemini-3.6-flash",
}


def test_test_probes_with_the_model_the_guard_names(monkeypatch):
    # The guard is an allowlist, so no model can be assumed: the id comes from the
    # person's own `/gate/models` answer, and nothing is hard-coded.
    http = _Http(monkeypatch, (200, _LISTING))
    assert verify_provider_key("aigw", fields=_SIGNED_IN) == {"ok": True}
    assert http.verbs == ["GET", "POST"]
    listing, completion = http.calls
    assert listing["url"] == BASE + "/gate/models"
    assert completion["url"] == BASE + "/compat/chat/completions"
    assert completion["json"]["model"] == "google-ai-studio/gemini-3.6-flash"
    assert completion["json"]["max_tokens"] == 16  # still a sub-cent call


def test_test_probe_also_carries_the_display_name(monkeypatch):
    http = _Http(monkeypatch, (200, _LISTING))
    fields = {**_SIGNED_IN, "display_name": "测试用户"}
    assert verify_provider_key("aigw", fields=fields) == {"ok": True}
    metadata = http.calls[1]["headers"]["cf-aig-metadata"]
    assert json.loads(metadata) == {"display_name": "测试用户"}


def test_the_probe_model_is_not_hard_coded_anywhere(monkeypatch):
    import coworker.providers.aigateway_provider as provider_mod
    import coworker.providers.registry as registry_mod

    assert not hasattr(provider_mod, "PROBE_MODEL")
    assert not hasattr(registry_mod, "PROBE_MODEL")
    # Whatever id the guard names is the id that is called — even one no table here knows.
    http = _Http(monkeypatch, (200, {"models": [], "probe": "workers-ai/@cf/zai-org/glm-9"}))
    assert verify_provider_key("aigw", fields=_SIGNED_IN) == {"ok": True}
    assert http.calls[1]["json"]["model"] == "workers-ai/@cf/zai-org/glm-9"


@pytest.mark.parametrize("probe", [None, "", "   ", 7, "absent"])
def test_without_a_probe_the_first_listed_model_is_used(monkeypatch, probe):
    body = {k: v for k, v in _LISTING.items() if k != "probe"}
    if probe != "absent":
        body["probe"] = probe
    http = _Http(monkeypatch, (200, body))
    assert verify_provider_key("aigw", fields=_SIGNED_IN) == {"ok": True}
    assert http.calls[1]["json"]["model"] == "openai/gpt-5.6-terra"


def test_a_list_with_nothing_to_probe_fails_without_inventing_a_model(monkeypatch):
    http = _Http(monkeypatch, (200, {"models": [], "probe": None}))
    out = verify_provider_key("aigw", fields=_SIGNED_IN)
    assert out["ok"] is False and "no model to test with" in out["error"]
    assert http.verbs == ["GET"]  # no completion on a guessed id


@pytest.mark.parametrize(
    "status,code,message",
    [
        (502, "catalog_unavailable", "你的账号暂未开通任何模型，请联系管理员开通。[gateway-guard]"),
        (503, "gate_unavailable", "网关配置暂时读不到，请稍后重试。[gateway-guard]"),
    ],
)
def test_the_guards_refusal_of_the_list_is_the_tests_failure_verbatim(
    monkeypatch, status, code, message
):
    http = _Http(
        monkeypatch,
        (status, {"error": {"code": code, "status": status, "message": message}}),
    )
    assert verify_provider_key("aigw", fields=_SIGNED_IN) == {"ok": False, "error": message}
    assert http.verbs == ["GET"]  # nothing to probe with, so nothing is probed


def test_a_guard_refusal_of_the_completion_is_shown_verbatim_too(monkeypatch):
    # The guard fronts the completion as well. Its 403 must not be read as "your Access
    # session is stale" — the list request just succeeded with the same credential.
    message = "模型 google-ai-studio/gemini-3.6-flash 不在你的可用清单。[gateway-guard]"
    for status, code in ((403, "model_restricted"), (503, "gate_unavailable")):
        http = _Http(
            monkeypatch,
            (200, _LISTING),
            (status, {"error": {"code": code, "status": status, "message": message}}),
        )
        assert verify_provider_key("aigw", fields=_SIGNED_IN) == {"ok": False, "error": message}
        assert http.verbs == ["GET", "POST"]


@pytest.mark.parametrize(
    "listing,completion,needle",
    [
        # A stale Access session shows up on the very first request.
        ((302, "<html>Cloudflare Access</html>"), (200, {}), "Access session isn't valid"),
        ((200, "<html>Cloudflare Access login</html>"), (200, {}), "Access session isn't valid"),
        # The address is not reaching the guard at all.
        ((404, "not found"), (200, {}), "didn't answer as a gateway"),
        ((200, "<html>hello</html>"), (200, {}), "didn't answer as a gateway"),
        (RuntimeError("dns"), (200, {}), "Couldn't reach the gateway"),
        # The list is fine; the completion is what fails — same readings as before.
        ((200, _LISTING), RuntimeError("timeout"), "Couldn't reach the gateway"),
        ((200, _LISTING), (402, {"error": "no credit"}), "out of AI Gateway credits"),
        ((200, _LISTING), (429, "Rate limited"), "Rate limited right now"),
        ((200, _LISTING), (400, {"errors": [{"message": "Invalid provider"}]}), "provider prefix"),
        ((200, _LISTING), (500, "boom"), "HTTP 500"),
        # A vendor error the gateway merely relayed has the guard's JSON shape but not
        # its tag — it keeps the status-code reading instead of being shown raw.
        ((200, _LISTING), (403, {"error": {"message": "forbidden"}}), "Access session isn't valid"),
    ],
)
def test_other_test_failures_keep_their_plain_reading(monkeypatch, listing, completion, needle):
    _Http(monkeypatch, listing, completion)
    out = verify_provider_key("aigw", fields=_SIGNED_IN)
    assert out["ok"] is False and needle in out["error"], out


@pytest.mark.parametrize(
    "exc,needle",
    [
        # Python's wording for a TLS handshake that never completes — the failure this
        # network hit repeatedly in 2026-10. It must read as TLS (proxy / VPN), not as a
        # generic timeout.
        (
            httpx.ConnectTimeout("_ssl.c:980: The handshake operation timed out"),
            "TLS handshake failed or timed out",
        ),
        (httpx.ConnectTimeout("The request timed out."), "connection timed out"),
        (httpx.ConnectError("[Errno 11001] getaddrinfo failed"), "DNS could not resolve"),
        (httpx.ConnectError("[Errno 10061] Connection refused"), "connection was refused"),
        (
            httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"),
            "certificate verification failed",
        ),
        # Unknown cause → the original sentence, byte for byte (its translation key).
        (RuntimeError("boom"), "Couldn't reach the gateway — check your network and try again."),
    ],
)
def test_unreachable_gateway_names_the_failure_kind_in_a_fixed_sentence(
    monkeypatch, caplog, exc, needle
):
    # The GUI translates the Test's answer by whole-string lookup, so the sentence is one
    # of a fixed family (every one starting "Couldn't reach the gateway") rather than the
    # free-form class+message line the other providers show. Both requests — the list and
    # the completion — answer the same way, and the raw cause goes to the log at WARNING,
    # where a packaged build keeps it.
    import logging

    from coworker.providers.registry import _AIGW_UNREACHABLE, _AIGW_UNREACHABLE_DEFAULT

    family = {_AIGW_UNREACHABLE_DEFAULT, *_AIGW_UNREACHABLE.values()}
    for listing, completion in ((exc, (200, {})), ((200, _LISTING), exc)):
        _Http(monkeypatch, listing, completion)
        with caplog.at_level(logging.WARNING, logger="coworker.providers.registry"):
            out = verify_provider_key("aigw", fields=_SIGNED_IN)
        assert out["ok"] is False and needle in out["error"], out
        assert out["error"] in family and out["error"].startswith("Couldn't reach the gateway")
        assert any(
            "aigw verify" in r.getMessage() and type(exc).__name__ in r.getMessage()
            for r in caplog.records
        ), caplog.text
        caplog.clear()


def test_every_gateway_unreachable_sentence_has_a_chinese_translation():
    # The whole point of the fixed family: each sentence is a literal key in the GUI's
    # zh-CN catalog. A new kind without its entry would show colleagues English.
    import json
    from pathlib import Path

    from coworker.providers.registry import _AIGW_UNREACHABLE, _AIGW_UNREACHABLE_DEFAULT

    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "surfaces/gui/src/locales/zh-CN.json").read_text("utf-8"))
    for sentence in (_AIGW_UNREACHABLE_DEFAULT, *_AIGW_UNREACHABLE.values()):
        assert catalog.get(sentence, "").startswith("连不上网关"), sentence


def test_test_exercises_the_credential_a_real_call_would_use(monkeypatch):
    # Test has to prefer the signed-in session exactly as the provider does. Probing with
    # a leftover pasted value would report success against a credential nothing else uses.
    http = _Http(monkeypatch, (200, _LISTING))
    out = verify_provider_key("aigw", fields=_SIGNED_IN)
    assert out["ok"] is True
    for call in http.calls:  # the list request and the completion alike
        assert call["headers"]["Authorization"] == "Bearer fresh"
        assert "cf-access-token" not in call["headers"]
    assert http.calls[1]["headers"]["cf-aig-skip-cache"] == "true"
    # A pasted session alone travels in Access's own header, on both requests.
    http = _Http(monkeypatch, (200, _LISTING))
    assert verify_provider_key("aigw", fields={"base_url": BASE, "access_token": "jwt"})["ok"]
    assert [c["headers"].get("cf-access-token") for c in http.calls] == ["jwt", "jwt"]
