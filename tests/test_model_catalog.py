"""Tests for the live model catalog: `providers/catalog.py`'s parsers and label logic,
`registry.list_provider_models`'s wire behavior, and `SessionManager`'s cache/consumer
plumbing (refresh, persistence, `_suggested_models`/`_curated_models`/`get_settings`
integration). SDK-free: httpx is monkeypatched exactly like test_provider_verify.py.

`conftest.py`'s autouse `_no_live_model_catalog` fixture stubs `SessionManager.
_fetch_model_catalog` to an offline failure for every OTHER test file — the manager-level
tests here override it per-test with their own stub (or leave it, when a test wants that
default "offline" behavior).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from coworker.providers.catalog import (
    CATALOG_PROVIDERS,
    CatalogModel,
    is_chat_model_id,
    parse_anthropic,
    parse_catalog,
    parse_gemini,
    parse_openai_compat,
    pretty_model_label,
    supports_catalog,
)
from coworker.providers.registry import list_provider_models, verify_provider_key
from coworker.server.manager import SessionManager


# -- CatalogModel / CATALOG_PROVIDERS --------------------------------------------------


def test_catalog_model_to_dict():
    m = CatalogModel("glm-5.2", "GLM-5.2 · Z AI", 128000)
    assert m.to_dict() == {
        "id": "glm-5.2",
        "label": "GLM-5.2 · Z AI",
        "context_window": 128000,
    }


def test_catalog_providers_membership():
    for name in (
        "openai",
        "anthropic",
        "gemini",
        "custom",
        "nvidia",
        "together",
        "fireworks",
        "openrouter",
        "zai",
        "deepseek",
        "kimi",
        "minimax",
        "qwen",
        "xai",
        "mistral",
        "meta",
    ):
        assert supports_catalog(name), name
        assert name in CATALOG_PROVIDERS
    for name in (
        "ollama",
        "ark",
        "ark-agent-plan-cn",
        "bedrock",
        "vertex",
        "aigw",
        "openai-codex",
    ):
        assert not supports_catalog(name), name


# -- is_chat_model_id -------------------------------------------------------------


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("gpt-5.6-sol", True),
        ("claude-3-5-sonnet-latest", True),
        ("gemini-3.7-flash", True),
        ("text-embedding-3-large", False),
        ("whisper-1", False),
        ("dall-e-3", False),
        ("gemini-2.0-flash-live", False),
        ("gpt-4o-realtime-preview", False),
        ("text-moderation-latest", False),
        ("imagen-3.0-generate", False),
        ("gemini-embedding-001", False),
    ],
)
def test_is_chat_model_id(model_id, expected):
    assert is_chat_model_id(model_id) is expected


# -- pretty_model_label -----------------------------------------------------------


@pytest.mark.parametrize(
    "model_id,provider,provider_title,expected",
    [
        ("gpt-5.6-sol", "openai", "", "GPT-5.6 Sol · OpenAI"),
        ("moonshotai/kimi-k3", "nvidia", "", "Kimi K3 · via NVIDIA"),
        ("glm-5.2", "zai", "", "GLM-5.2 · Z AI"),
        ("deepseek-v4-flash", "deepseek", "DeepSeek", "Deepseek V4 Flash · DeepSeek"),
        (
            "mistral-large-latest",
            "mistral",
            "Mistral",
            "Mistral Large Latest · Mistral",
        ),
        ("xai-thing", "xai", "xAI (Grok)", "Xai Thing · xAI"),
    ],
)
def test_pretty_model_label(model_id, provider, provider_title, expected):
    assert pretty_model_label(model_id, provider, provider_title) == expected


def test_pretty_model_label_never_raises_on_garbage():
    assert pretty_model_label("", "zai") == "Z AI"
    # tokens strip to nothing (all-dash id) and no suffix is available either way →
    # falls back to the raw tail rather than raising or returning a bare " · ".
    assert pretty_model_label("---", "unknown-provider", "") == "---"


# -- parse_gemini -------------------------------------------------------------------


def test_parse_gemini_filters_and_extracts_fields():
    payload = {
        "models": [
            {
                "name": "models/gemini-3.7-flash",
                "displayName": "Gemini 3.7 Flash",
                "inputTokenLimit": 1048576,
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            {
                "name": "models/gemini-3.7-flash-tts",
                "displayName": "Gemini 3.7 Flash TTS",
                "inputTokenLimit": 8192,
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/embedding-001",
                "displayName": "Embedding 001",
                "supportedGenerationMethods": ["embedContent"],
            },
            {
                "name": "models/gemini-no-display",
                "supportedGenerationMethods": ["generateContent"],
            },
        ]
    }
    models = parse_gemini(payload)
    assert [m.id for m in models] == ["gemini-3.7-flash", "gemini-no-display"]
    flash = models[0]
    assert flash.label == "Gemini 3.7 Flash · Google"
    assert flash.context_window == 1048576
    fallback = models[1]
    assert fallback.label == pretty_model_label("gemini-no-display", "gemini")
    assert fallback.context_window is None


def test_parse_gemini_malformed_payload_returns_empty():
    assert parse_gemini(None) == []
    assert parse_gemini({"models": "nope"}) == []
    assert parse_gemini({"models": [1, 2, "x"]}) == []
    assert parse_gemini({"models": [{"name": "models/x"}]}) == []  # no methods list


# -- parse_anthropic ----------------------------------------------------------------


def test_parse_anthropic_basic():
    payload = {
        "data": [
            {"id": "claude-fable-5", "display_name": "Claude Fable 5"},
            {"id": "claude-no-name"},
        ]
    }
    models = parse_anthropic(payload)
    assert models[0].label == "Claude Fable 5 · Anthropic"
    assert models[0].context_window is None
    assert models[1].label == pretty_model_label("claude-no-name", "anthropic")


def test_parse_anthropic_malformed_payload_returns_empty():
    assert parse_anthropic(None) == []
    assert parse_anthropic({"data": "nope"}) == []
    assert parse_anthropic({"data": [1, "x", {}]}) == []


# -- parse_openai_compat --------------------------------------------------------------


def test_parse_openai_compat_dict_and_bare_list_shapes():
    payload_dict = {"data": [{"id": "glm-5.2"}, {"id": "text-embedding-ada-002"}]}
    models = parse_openai_compat(payload_dict, "zai", "Z AI")
    assert [m.id for m in models] == ["glm-5.2"]
    assert models[0].label == "GLM-5.2 · Z AI"

    payload_list = [{"id": "kimi-k2.6"}]  # bare list (some vLLM servers)
    models2 = parse_openai_compat(payload_list, "kimi", "Kimi (Moonshot AI)")
    assert models2[0].id == "kimi-k2.6"


def test_parse_openai_compat_openrouter_uses_name_and_context_length():
    payload = {
        "data": [
            {"id": "z-ai/glm-5.2", "name": "GLM 5.2", "context_length": 128000},
        ]
    }
    models = parse_openai_compat(payload, "openrouter", "OpenRouter")
    assert models[0].label == "GLM 5.2"  # vendor-supplied name wins, unsuffixed
    assert models[0].context_window == 128000


def test_parse_openai_compat_excludes_non_chat_ids():
    payload = {
        "data": [
            {"id": "gpt-5.6-sol"},
            {"id": "whisper-1"},
            {"id": "dall-e-3"},
            {"id": "text-embedding-3-large"},
        ]
    }
    models = parse_openai_compat(payload, "openai", "OpenAI")
    assert [m.id for m in models] == ["gpt-5.6-sol"]


def test_parse_openai_compat_malformed_payload_returns_empty():
    assert parse_openai_compat(None, "zai") == []
    assert parse_openai_compat({"data": None}, "zai") == []
    assert parse_openai_compat({"nope": []}, "zai") == []
    assert parse_openai_compat({"data": [1, "x"]}, "zai") == []


def test_parse_catalog_dispatch_and_never_raises():
    assert parse_catalog("gemini", {"models": []}) == []
    assert parse_catalog("anthropic", {"data": []}) == []
    assert parse_catalog("zai", {"data": [{"id": "glm-5.2"}]})[0].id == "glm-5.2"
    assert parse_catalog("gemini", object()) == []
    assert parse_catalog("anthropic", 12345) == []
    assert parse_catalog("openrouter", "not even a dict") == []


# -- registry.list_provider_models: wire behavior --------------------------------------


def _patch_get(monkeypatch, status=200, json_body=None, capture=None, raise_exc=None):
    def fake_get(url, **kwargs):
        if capture is not None:
            capture["url"] = url
            capture.update(kwargs)
        if raise_exc is not None:
            raise raise_exc
        ns = SimpleNamespace(status_code=status)
        if json_body is not None:
            ns.json = lambda: json_body
        return ns

    monkeypatch.setattr("httpx.get", fake_get)


def test_list_provider_models_gemini_relay_header_and_fields(monkeypatch):
    cap: dict = {}
    _patch_get(
        monkeypatch,
        status=200,
        json_body={
            "models": [
                {
                    "name": "models/gemini-3.7-flash",
                    "displayName": "Gemini 3.7 Flash",
                    "inputTokenLimit": 1048576,
                    "supportedGenerationMethods": ["generateContent"],
                }
            ]
        },
        capture=cap,
    )
    res = list_provider_models(
        "gemini", api_key="AIza-x", fields={"relay_token": "owr_x"}
    )
    assert res["ok"] is True
    assert res["models"] == [
        {
            "id": "gemini-3.7-flash",
            "label": "Gemini 3.7 Flash · Google",
            "context_window": 1048576,
        }
    ]
    assert cap["url"] == "https://gemini.smjtools.com/v1beta/models"
    assert cap["headers"]["x-goog-api-key"] == "AIza-x"
    assert cap["headers"]["Authorization"] == "Bearer owr_x"


def test_list_provider_models_anthropic(monkeypatch):
    _patch_get(
        monkeypatch,
        status=200,
        json_body={
            "data": [{"id": "claude-fable-5", "display_name": "Claude Fable 5"}]
        },
    )
    res = list_provider_models("anthropic", api_key="sk-ant-x")
    assert res == {
        "ok": True,
        "models": [
            {
                "id": "claude-fable-5",
                "label": "Claude Fable 5 · Anthropic",
                "context_window": None,
            }
        ],
    }


def test_list_provider_models_nvidia_and_openrouter(monkeypatch):
    cap: dict = {}
    _patch_get(
        monkeypatch,
        status=200,
        json_body={"data": [{"id": "moonshotai/kimi-k3"}]},
        capture=cap,
    )
    res = list_provider_models(
        "nvidia", api_key="nvapi-x", provider_title="NVIDIA (NIM)"
    )
    assert res["ok"] is True
    assert res["models"][0]["label"] == "Kimi K3 · via NVIDIA"
    assert "nvidia.smjtools.com" in cap["url"]

    _patch_get(
        monkeypatch,
        status=200,
        json_body={
            "data": [{"id": "z-ai/glm-5.2", "name": "GLM 5.2", "context_length": 128000}]
        },
    )
    res2 = list_provider_models("openrouter", api_key="sk-or-x")
    assert res2["models"] == [
        {"id": "z-ai/glm-5.2", "label": "GLM 5.2", "context_window": 128000}
    ]


def test_list_provider_models_unsupported_provider():
    res = list_provider_models("ollama", api_key="")
    assert res["ok"] is False and res["unsupported"] is True
    assert "no model list API" in res["error"]


def test_list_provider_models_oauth_provider_is_unsupported():
    res = list_provider_models("openai-codex")
    assert res["ok"] is False and res["unsupported"] is True


def test_list_provider_models_custom_blank_endpoint_no_network_call(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("must not reach the network with no endpoint typed")

    monkeypatch.setattr("httpx.get", fail)
    assert list_provider_models("custom", api_key="ak-x", base_url="") == {
        "ok": False,
        "error": "Enter the endpoint URL first.",
    }


def test_list_provider_models_401_maps_to_invalid_key(monkeypatch):
    _patch_get(monkeypatch, status=401)
    res = list_provider_models("openai", api_key="sk-bad")
    assert res == {"ok": False, "error": "Invalid API key."}


def test_list_provider_models_network_error_is_clean(monkeypatch):
    _patch_get(monkeypatch, raise_exc=ConnectionError("boom"))
    res = list_provider_models("openai", api_key="sk-x")
    assert res["ok"] is False and "Couldn't reach" in res["error"]
    assert "http_ok" not in res


def test_list_provider_models_empty_catalog_carries_http_ok(monkeypatch):
    """A 2xx with nothing chat-shaped in it: the credentials work, there's just no
    catalog — `http_ok` lets a caller (manager.verify_provider) still call that a pass."""
    _patch_get(monkeypatch, status=200, json_body={"data": []})
    res = list_provider_models("openai", api_key="sk-x")
    assert res["ok"] is False and res["http_ok"] is True
    assert "no models" in res["error"]


def test_list_provider_models_non_json_body_carries_http_ok(monkeypatch):
    _patch_get(monkeypatch, status=200)  # SimpleNamespace with no .json at all
    res = list_provider_models("openai", api_key="sk-x")
    assert res["ok"] is False and res["http_ok"] is True
    assert "non-JSON" in res["error"]


def test_verify_and_list_hit_the_same_url_and_headers(monkeypatch):
    """The Test button and the catalog pull must probe identically — same wire, same
    credentials — so a passing Test can double as a catalog fetch without surprises."""
    cap_verify: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap_verify)
    verify_provider_key("anthropic", api_key="sk-ant-x")

    cap_list: dict = {}
    _patch_get(monkeypatch, status=200, json_body={"data": []}, capture=cap_list)
    list_provider_models("anthropic", api_key="sk-ant-x")

    assert cap_verify["url"] == cap_list["url"]
    assert cap_verify["headers"] == cap_list["headers"]


# -- manager: cache plumbing (refresh / persistence / staleness) ------------------------


def test_catalog_refresh_persists_across_restart(tmp_path, monkeypatch):
    mgr = SessionManager(data_dir=tmp_path / "data")
    mgr.secrets.put("provider:zai", {"api_key": "zk"})
    monkeypatch.setattr(
        SessionManager,
        "_fetch_model_catalog",
        lambda self, name, fields=None: {
            "ok": True,
            "models": [{"id": "glm-5.2", "label": "GLM-5.2 · Z AI", "context_window": 128000}],
        },
    )
    res = mgr.refresh_model_catalog("zai")
    assert res["ok"] is True
    assert res["catalog"]["live"] is True and res["catalog"]["count"] == 1

    reborn = SessionManager(data_dir=tmp_path / "data")
    assert reborn._catalog_models("zai") == [
        {"id": "glm-5.2", "label": "GLM-5.2 · Z AI", "context_window": 128000}
    ]


def test_catalog_failure_keeps_previously_cached_models(tmp_path, monkeypatch):
    mgr = SessionManager(data_dir=tmp_path / "data")
    mgr.secrets.put("provider:zai", {"api_key": "zk"})
    monkeypatch.setattr(
        SessionManager,
        "_fetch_model_catalog",
        lambda self, name, fields=None: {
            "ok": True,
            "models": [{"id": "glm-5.2", "label": "x", "context_window": None}],
        },
    )
    mgr.refresh_model_catalog("zai")

    monkeypatch.setattr(
        SessionManager,
        "_fetch_model_catalog",
        lambda self, name, fields=None: {"ok": False, "error": "boom"},
    )
    res = mgr.refresh_model_catalog("zai")
    assert res["ok"] is False and res["error"] == "boom"
    # the earlier successful pull's models survive an outage
    assert mgr._catalog_models("zai") == [{"id": "glm-5.2", "label": "x", "context_window": None}]
    assert mgr._catalog_status("zai")["error"] == "boom"


def test_refresh_model_catalog_unknown_and_unsupported_and_unconfigured(tmp_path):
    mgr = SessionManager(data_dir=tmp_path / "data")
    assert mgr.refresh_model_catalog("nope") == {
        "ok": False,
        "error": "unknown provider: nope",
    }
    ark = mgr.refresh_model_catalog("ark")
    assert ark["ok"] is False and ark["unsupported"] is True and ark["provider"] == "ark"
    # never configured, no fields handed in → refused without a wasted fetch
    assert mgr.refresh_model_catalog("zai") == {"ok": False, "error": "not configured"}


def test_get_providers_kicks_refresh_only_when_configured_and_stale(tmp_path, monkeypatch):
    mgr = SessionManager(data_dir=tmp_path / "data")
    calls: list[str] = []
    monkeypatch.setattr(mgr, "_kick_catalog_refresh", lambda name: calls.append(name))
    mgr.get_providers()
    assert "zai" not in calls  # not configured → never kicked

    mgr.secrets.put("provider:zai", {"api_key": "zk"})
    calls.clear()
    mgr.get_providers()
    assert "zai" in calls  # configured, never fetched → stale → kicked

    from datetime import datetime, timezone

    mgr._model_catalog["zai"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "models": [{"id": "glm-5.2", "label": "x", "context_window": None}],
        "error": None,
    }
    calls.clear()
    mgr.get_providers()
    assert "zai" not in calls  # fresh → not kicked again


def test_kick_catalog_refresh_dedupes_inflight(tmp_path, monkeypatch):
    import threading
    import time as _time

    mgr = SessionManager(data_dir=tmp_path / "data")
    mgr.secrets.put("provider:zai", {"api_key": "zk"})
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def slow_fetch(self, name, fields=None):
        calls.append(name)
        started.set()
        release.wait(timeout=2)
        return {"ok": False, "error": "offline"}

    monkeypatch.setattr(SessionManager, "_fetch_model_catalog", slow_fetch)
    mgr._kick_catalog_refresh("zai")
    assert started.wait(timeout=2)
    mgr._kick_catalog_refresh("zai")  # already in-flight → no-op, no second thread
    release.set()
    _time.sleep(0.2)
    assert calls == ["zai"]


# -- manager: _suggested_models / _curated_models / add_model / remove_model -----------


def test_suggested_models_prefers_live_catalog_when_present(tmp_path):
    mgr = SessionManager(data_dir=tmp_path / "data")
    mgr._model_catalog["zai"] = {
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "models": [
            {"id": "glm-5.2", "label": "x", "context_window": None},
            {"id": "glm-6.0-preview", "label": "y", "context_window": None},
        ],
        "error": None,
    }
    assert mgr._suggested_models("zai") == ["glm-5.2", "glm-6.0-preview"]


def test_suggested_models_falls_back_to_static_matrix_without_a_catalog(tmp_path):
    mgr = SessionManager(data_dir=tmp_path / "data")
    sugg = mgr._suggested_models("zai")
    assert "glm-5.2" in sugg  # matrix
    assert "glm-4.6" in sugg  # COMPAT_MODELS extra


def test_curated_models_drops_a_stale_matrix_id_but_pins_the_active_default(tmp_path):
    mgr = SessionManager(data_dir=tmp_path / "data")
    mgr.model = "anthropic:claude-opus-4-8"
    mgr._model_catalog["anthropic"] = {
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "models": [{"id": "claude-fable-5", "label": "x", "context_window": None}],
        "error": None,
    }
    models = mgr._curated_models()
    assert "anthropic:claude-haiku-4-5" not in models  # not in the live catalog
    assert "anthropic:claude-fable-5" in models  # confirmed still live
    assert models[0] == "anthropic:claude-opus-4-8"  # active default always first


def test_add_model_stores_a_catalog_excluded_matrix_id_as_a_custom_model(tmp_path):
    mgr = SessionManager(data_dir=tmp_path / "data")
    mgr._model_catalog["anthropic"] = {
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "models": [{"id": "claude-fable-5", "label": "x", "context_window": None}],
        "error": None,
    }
    mgr.add_model("anthropic:claude-opus-4-8")
    assert "anthropic:claude-opus-4-8" in (mgr._prefs.get("models") or [])


# -- manager: set_provider auto-add follows the catalog ---------------------------


def test_set_provider_auto_add_follows_a_successful_catalog_pull(tmp_path, monkeypatch):
    mgr = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(
        SessionManager,
        "_fetch_model_catalog",
        lambda self, name, fields=None: {
            "ok": True,
            "models": [{"id": "glm-6.0", "label": "GLM 6.0 · Z AI", "context_window": None}],
        },
    )
    res = mgr.set_provider("zai", {"api_key": "zk"})
    assert res["ok"] is True
    # the static recommended model ("glm-5.2") isn't in the (fake) pulled catalog, so
    # set_provider's auto-add skips it — nothing from zai shows up uninvited.
    assert "zai:glm-5.2" not in mgr.get_settings()["models"]
    assert not any(m.startswith("zai:") for m in mgr.get_settings()["models"])
    # but the pull itself is cached and drives the "add model" suggestions
    assert mgr._catalog_models("zai") == [
        {"id": "glm-6.0", "label": "GLM 6.0 · Z AI", "context_window": None}
    ]
    assert mgr._suggested_models("zai") == ["glm-6.0"]


def test_set_provider_auto_add_falls_back_to_the_matrix_when_the_pull_fails(
    tmp_path, monkeypatch
):
    mgr = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(
        SessionManager,
        "_fetch_model_catalog",
        lambda self, name, fields=None: {"ok": False, "error": "offline"},
    )
    res = mgr.set_provider("zai", {"api_key": "zk"})
    assert res["ok"] is True
    assert "zai:glm-5.2" in mgr.get_settings()["models"]


# -- manager: get_settings merges catalog labels, matrix priority ----------------------


def test_get_settings_merges_catalog_labels_with_matrix_priority(tmp_path):
    from coworker.providers.matrix import model_labels

    mgr = SessionManager(data_dir=tmp_path / "data")
    mgr.secrets.put("provider:zai", {"api_key": "zk"})
    mgr._model_catalog["zai"] = {
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "models": [
            {"id": "glm-5.2", "label": "SHOULD NOT WIN", "context_window": 999},
            {
                "id": "glm-6.0-preview",
                "label": "GLM 6.0 Preview · Z AI",
                "context_window": 200000,
            },
        ],
        "error": None,
    }
    settings = mgr.get_settings()
    assert settings["model_labels"]["zai:glm-5.2"] == model_labels()["zai:glm-5.2"]
    assert settings["model_labels"]["zai:glm-6.0-preview"] == "GLM 6.0 Preview · Z AI"
    assert settings["model_context_windows"]["zai:glm-6.0-preview"] == 200000

    # an unconfigured provider's cached catalog must not leak labels
    mgr._model_catalog["kimi"] = {
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "models": [{"id": "kimi-ghost", "label": "Ghost", "context_window": None}],
        "error": None,
    }
    settings2 = mgr.get_settings()
    assert "kimi:kimi-ghost" not in settings2["model_labels"]


# -- manager: verify_provider's catalog-pull-on-Test path -------------------------


def test_verify_provider_success_writes_the_catalog(tmp_path, monkeypatch):
    mgr = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(
        "coworker.server.manager.list_provider_models",
        lambda name, **kwargs: {
            "ok": True,
            "models": [{"id": "glm-5.2", "label": "GLM-5.2 · Z AI", "context_window": 128000}],
        },
    )
    res = mgr.verify_provider("zai", {"api_key": "zk"})
    assert res == {"ok": True}
    assert mgr._catalog_models("zai") == [
        {"id": "glm-5.2", "label": "GLM-5.2 · Z AI", "context_window": 128000}
    ]


def test_verify_provider_http_ok_compat_passes_without_writing_a_catalog(
    tmp_path, monkeypatch
):
    """A 2xx probe with no parseable models (list_provider_models's `http_ok` marker):
    the credentials are good, Test must still say so — but nothing gets cached."""
    mgr = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(
        "coworker.server.manager.list_provider_models",
        lambda name, **kwargs: {"ok": False, "error": "no models", "http_ok": True},
    )
    res = mgr.verify_provider("zai", {"api_key": "zk"})
    assert res == {"ok": True}
    assert mgr._catalog_models("zai") == []


def test_verify_provider_failure_surfaces_the_catalog_error(tmp_path, monkeypatch):
    mgr = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(
        "coworker.server.manager.list_provider_models",
        lambda name, **kwargs: {"ok": False, "error": "Invalid API key."},
    )
    res = mgr.verify_provider("zai", {"api_key": "bad"})
    assert res == {"ok": False, "error": "Invalid API key."}
