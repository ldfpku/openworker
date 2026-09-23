"""gateway-guard's per-user model gate, client side.

The company gateway now fronts a guard Worker that restricts some models to certain
roles (server-side 403). The client half is cosmetic: `fetch_gate_policy` reads
`GET {base}/gate/policy`, and the manager hides the returned `blocked` ids from the
composer picker and the "add model" suggestions. Every failure mode must degrade to
"no filtering" — enforcement lives on the server, so a missed fetch can only ever be
a cosmetic miss, never a hole.
"""

from __future__ import annotations

import time

import httpx
import pytest

from coworker.providers.aigateway_provider import (
    DEFAULT_BASE_URL,
    blocked_model_ids,
    family_form,
    fetch_gate_policy,
    gate_families,
    is_blocked_model,
    is_gated_model,
    is_out_of_scope,
)
from coworker.server.manager import SessionManager as Manager


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self._text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _no_env(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_AIGW_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", raising=False)


# -- fetch_gate_policy -------------------------------------------------------------------
def test_no_credential_means_no_request_at_all(monkeypatch):
    _no_env(monkeypatch)

    def boom(*a, **k):  # pragma: no cover - the point is it must not run
        raise AssertionError("network call without a credential")

    monkeypatch.setattr(httpx, "get", boom)
    assert fetch_gate_policy({}) is None


def test_fetches_gate_policy_from_the_gateway_origin(monkeypatch):
    _no_env(monkeypatch)
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Resp(200, {"email": "a@x.com", "role": "employee", "active": True,
                           "blocked": ["openai/gpt-5.6-sol"], "enforce": True})

    monkeypatch.setattr(httpx, "get", fake_get)
    data = fetch_gate_policy({"oauth_token": "tok-123"})
    assert data and data["blocked"] == ["openai/gpt-5.6-sol"]
    assert seen["url"] == DEFAULT_BASE_URL + "/gate/policy"
    # OAuth rides the slot its protocol names, and the UA is ours (edge bot rules)
    assert seen["headers"]["Authorization"] == "Bearer tok-123"
    assert seen["headers"]["User-Agent"].startswith("openworker/")


def test_every_failure_shape_degrades_to_none(monkeypatch):
    _no_env(monkeypatch)
    cases = [
        _Resp(404, text="not found"),            # guard not deployed (bare custom domain)
        _Resp(401, {"error": {}}),               # signed out
        _Resp(200, None, text="<html>"),          # Access login page instead of JSON
        _Resp(200, {"blocked": "oops"}),          # malformed shape
    ]
    for resp in cases:
        monkeypatch.setattr(httpx, "get", lambda *a, _r=resp, **k: _r)
        assert fetch_gate_policy({"access_token": "jwt"}) is None

    def raising(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", raising)
    assert fetch_gate_policy({"access_token": "jwt"}) is None


def test_blocked_model_ids_normalizes_and_tolerates_junk():
    assert blocked_model_ids(None) == frozenset()
    assert blocked_model_ids({"blocked": "nope"}) == frozenset()
    assert blocked_model_ids(
        {"blocked": [" OpenAI/GPT-5.6-Sol ", "", 42, "anthropic/claude-fable-5"]}
    ) == frozenset({"openai/gpt-5.6-sol", "anthropic/claude-fable-5"})


# -- is_blocked_model ---------------------------------------------------------------------
# Mirrors gateway-guard's own server-side match exactly: exact id, or the same base id
# plus one optional dated/tagged suffix in a fixed shape. A miss here is only ever
# cosmetic (the server still 403s), but it must not drift from the server's shape.
_BLOCKED = frozenset({"anthropic/claude-fable-5", "openai/gpt-5.6-sol"})


@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic/claude-fable-5",
        "aigw:anthropic/claude-fable-5",
        "anthropic/claude-fable-5-20260901",
        "anthropic/claude-fable-5-latest",
        "anthropic/claude-fable-5@20260901",
        "anthropic/claude-fable-5:batch",
        "anthropic/claude-fable-5:beta",
        "anthropic/claude-fable-5-20260901:batch",
        "openai/gpt-5.6-sol-20260709",
        "openai/gpt-5.6-sol:batch",
        # case / whitespace variants
        " Anthropic/Claude-Fable-5 ",
        "AIGW:ANTHROPIC/CLAUDE-FABLE-5-LATEST",
    ],
)
def test_is_blocked_model_matches_known_variant_shapes(model_id):
    assert is_blocked_model(model_id, _BLOCKED) is True


@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic/claude-fable-5-1",  # 5.1's hyphen spelling: a distinct major version
        "anthropic/claude-fable-5.1",
        "anthropic/claude-fable-50",
        "anthropic/claude-fable-5-preview",
        "anthropic/claude-fable-5-2026090",  # 7 digits, not a full YYYYMMDD date
        "anthropic/claude-haiku-4-5",  # probe model, never restricted
        "openai/gpt-5.6-terra",
        "",
    ],
)
def test_is_blocked_model_rejects_lookalikes(model_id):
    assert is_blocked_model(model_id, _BLOCKED) is False


def test_is_blocked_model_empty_blocked_entry_matches_nothing():
    assert is_blocked_model("anthropic/claude-fable-5", frozenset({""})) is False
    assert is_blocked_model("anything-at-all", frozenset({"", " "})) is False


def test_is_blocked_model_strips_the_aigw_prefix_but_only_that_one():
    # A bare id and its "aigw:"-prefixed spelling are the same model to the gate.
    assert is_blocked_model("aigw:openai/gpt-5.6-sol", _BLOCKED) is True
    assert is_blocked_model("openai/gpt-5.6-sol", _BLOCKED) is True
    # A direct-provider id never carries "aigw:" and must not accidentally match a
    # differently-shaped blocked entry.
    assert is_blocked_model("anthropic:claude-fable-5", _BLOCKED) is False


# -- manager-side filtering --------------------------------------------------------------
def _bare_manager(blocked: set[str]) -> Manager:
    """A Manager shell with just the attributes the model-list paths touch — the cache is
    fresh, so `_aigw_blocked` serves it without kicking a background refresh."""
    m = object.__new__(Manager)
    m._prefs = {}
    m.model = "aigw:anthropic/claude-sonnet-5"
    m._aigw_gate_cache = (time.monotonic(), frozenset(blocked))
    return m


def test_curated_models_hide_gate_blocked_aigw_models():
    m = _bare_manager({"anthropic/claude-fable-5", "openai/gpt-5.6-sol"})
    models = Manager._curated_models(m)
    assert "aigw:anthropic/claude-fable-5" not in models
    assert "aigw:openai/gpt-5.6-sol" not in models
    # unblocked stablemates stay
    assert "aigw:anthropic/claude-sonnet-5" in models
    assert "aigw:openai/gpt-5.6-terra" in models


def test_gate_only_touches_aigw_ids_not_direct_provider_models():
    # The same flagship reached directly (own API key) is none of the gateway's business
    m = _bare_manager({"openai/gpt-5.6-sol", "anthropic/claude-fable-5"})
    models = Manager._curated_models(m)
    assert "gpt-5.6-sol" in models
    assert "anthropic:claude-fable-5" in models


def test_active_default_stays_selectable_even_when_blocked():
    # Matches the hidden_models invariant: the active default is always in the list
    # (the guard's server-side 403 still applies if it is actually used).
    m = _bare_manager({"anthropic/claude-fable-5"})
    m.model = "aigw:anthropic/claude-fable-5"
    assert Manager._curated_models(m)[0] == "aigw:anthropic/claude-fable-5"


def test_suggested_models_hide_blocked_for_aigw():
    m = _bare_manager({"openai/gpt-5.6-sol"})
    sugg = Manager._suggested_models(m, "aigw")
    assert "openai/gpt-5.6-sol" not in sugg
    assert "anthropic/claude-sonnet-5" in sugg


def test_empty_gate_filters_nothing():
    m = _bare_manager(set())
    models = Manager._curated_models(m)
    assert "aigw:anthropic/claude-fable-5" in models
    assert "aigw:openai/gpt-5.6-sol" in models


def test_curated_models_hide_gate_blocked_aigw_model_variants():
    # A user-added custom id that is a dated/tagged variant of a blocked base id must be
    # hidden too — the picker filter now matches the same shape the guard does server-
    # side, not just bare equality. 5.1's hyphen spelling is a distinct model and stays.
    m = _bare_manager({"anthropic/claude-fable-5"})
    m._prefs = {
        "models": [
            "aigw:anthropic/claude-fable-5-20260901",
            "aigw:anthropic/claude-fable-5:batch",
            "aigw:anthropic/claude-fable-5-1",
        ]
    }
    models = Manager._curated_models(m)
    assert "aigw:anthropic/claude-fable-5-20260901" not in models
    assert "aigw:anthropic/claude-fable-5:batch" not in models
    assert "aigw:anthropic/claude-fable-5-1" in models


def test_suggested_models_hide_blocked_variants_for_aigw():
    m = _bare_manager({"openai/gpt-5.6-sol"})
    # Instance override of the class-level suggestion table — real matrix ids never
    # carry a date/tag suffix, so inject some to exercise the variant match.
    m.COMPAT_MODELS = {
        "aigw": [
            "openai/gpt-5.6-sol-20260709",
            "openai/gpt-5.6-sol:batch",
            "openai/gpt-5.6-terra",
        ]
    }
    sugg = Manager._suggested_models(m, "aigw")
    assert "openai/gpt-5.6-sol-20260709" not in sugg
    assert "openai/gpt-5.6-sol:batch" not in sugg
    assert "openai/gpt-5.6-terra" in sugg


# -- open-vendor scope (`families`, guard 2026-09-23) -------------------------------------
# The guard's second layer: a model under none of the open vendor prefixes gets the same
# 403 as a restricted one unless the caller's role is allowed. `/gate/policy` reports the
# prefixes as `families` (null for allowed roles). These cases are the guard's own smoke
# examples (smj-help-website test/gateway-guard.smoke.mjs §13), so the two sides can't drift.
_FAMILIES = (
    "openai/", "anthropic/", "google-ai-studio/",
    "workers-ai/@cf/zai-org/", "workers-ai/@cf/qwen/", "workers-ai/@cf/deepseek-ai/",
)


def test_gate_families_parses_like_the_guard():
    assert gate_families(None) is None
    assert gate_families({"blocked": []}) is None  # older guard: key missing → no scope filter
    assert gate_families({"blocked": [], "families": None}) is None  # allowed role
    assert gate_families({"families": "openai/"}) is None  # malformed → no filter
    assert gate_families(
        {"families": [" OpenAI/ ", "anthropic", "/", 7, "workers-ai/@cf/qwen/"]}
    ) == ("openai/", "workers-ai/@cf/qwen/")
    assert gate_families({"families": []}) == ()  # explicit [] = nothing open


def test_family_form_prefixes_bare_cf_ids_only():
    assert family_form(" @CF/qwen/QwQ-32b ") == "workers-ai/@cf/qwen/qwq-32b"
    assert family_form("workers-ai/@cf/qwen/qwq-32b") == "workers-ai/@cf/qwen/qwq-32b"
    assert family_form("openai/gpt-5.6-sol") == "openai/gpt-5.6-sol"


@pytest.mark.parametrize(
    "model_id",
    [
        "openai/gpt-5.6-sol",
        "aigw:anthropic/claude-haiku-4-5",  # probe model: always in scope
        "google-ai-studio/gemini-3.8-flash",
        "workers-ai/@cf/zai-org/glm-5.3",
        "@cf/qwen/qwq-32b",  # bare @cf gains workers-ai/ first
        "workers-ai/@cf/deepseek-ai/deepseek-v4-flash-0731",
        "dynamic/ow-anthropic-claude-sonnet-5",  # route names are judged by expansion
        " Anthropic/Claude-Sonnet-5 ",
    ],
)
def test_in_scope_models(model_id):
    assert is_out_of_scope(model_id, _FAMILIES) is False


@pytest.mark.parametrize(
    "model_id",
    [
        "grok/grok-4.7",
        "aigw:grok/grok-4.7",
        "workers-ai/@cf/moonshotai/kimi-k2.6",
        "@cf/meta/llama-3.2-1b-instruct",
        "gpt-4o-mini",  # no vendor prefix at all
        "openai/",  # a bare prefix with nothing after it
        "openrouter/anthropic/claude-fable-5",
        "openai-evil/gpt-5",
    ],
)
def test_out_of_scope_models(model_id):
    assert is_out_of_scope(model_id, _FAMILIES) is True


def test_no_families_means_no_scope_filter_and_empty_means_nothing_open():
    assert is_out_of_scope("grok/grok-4.7", None) is False
    assert is_out_of_scope("openai/gpt-5.6-terra", ()) is True


def test_is_gated_model_is_either_layer():
    blocked = frozenset({"openai/gpt-5.6-sol"})
    assert is_gated_model("aigw:openai/gpt-5.6-sol-20260709", blocked, _FAMILIES) is True
    assert is_gated_model("aigw:grok/grok-4.7", blocked, _FAMILIES) is True
    assert is_gated_model("aigw:openai/gpt-5.6-terra", blocked, _FAMILIES) is False
    assert is_gated_model("aigw:grok/grok-4.7", blocked, None) is False


def _scoped_manager(families, blocked=()):
    m = _bare_manager(set(blocked))
    m._aigw_gate_cache = (time.monotonic(), frozenset(blocked), families)
    return m


def test_curated_models_hide_out_of_scope_aigw_models_only():
    m = _scoped_manager(_FAMILIES)
    m._prefs = {"models": ["aigw:grok/grok-4.7", "aigw:workers-ai/@cf/meta/llama-4-scout", "grok-4.7",
                           "aigw:workers-ai/@cf/qwen/qwq-32b"]}
    models = Manager._curated_models(m)
    assert "aigw:grok/grok-4.7" not in models
    assert "aigw:workers-ai/@cf/meta/llama-4-scout" not in models
    assert "aigw:workers-ai/@cf/qwen/qwq-32b" in models
    # direct-provider ids have no gateway vendor prefix to test and are none of its business
    assert "grok-4.7" in models
    # every curated-matrix aigw model sits inside the six open vendors
    assert "aigw:anthropic/claude-sonnet-5" in models
    assert "aigw:openai/gpt-5.6-terra" in models


def test_allowed_role_or_old_cache_shape_filters_nothing_by_scope():
    m = _scoped_manager(None)
    m._prefs = {"models": ["aigw:grok/grok-4.7"]}
    assert "aigw:grok/grok-4.7" in Manager._curated_models(m)
    m = _bare_manager(set())  # pre-families 2-tuple cache
    m._prefs = {"models": ["aigw:grok/grok-4.7"]}
    assert "aigw:grok/grok-4.7" in Manager._curated_models(m)


def test_suggested_models_hide_out_of_scope_for_aigw():
    m = _scoped_manager(_FAMILIES)
    m.COMPAT_MODELS = {"aigw": ["grok/grok-4.7", "openai/gpt-5.6-terra", "@cf/meta/llama-3.2-1b-instruct"]}
    sugg = Manager._suggested_models(m, "aigw")
    assert "grok/grok-4.7" not in sugg
    assert "@cf/meta/llama-3.2-1b-instruct" not in sugg
    assert "openai/gpt-5.6-terra" in sugg
