"""Tests for provider key detection + the live (read-only) Test/verify path. SDK-free: the
single httpx.get is monkeypatched so no network is touched."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from coworker.providers import detect_provider, verify_provider_key


# -- detect_provider ------------------------------------------------------------
@pytest.mark.parametrize(
    "key,expected",
    [
        ("sk-ant-api03-abc", "anthropic"),
        ("sk-or-v1-abc", "openrouter"),
        ("AIzaSyAbc123", "gemini"),
        ("sk-proj-abc", "openai"),
        ("sk_live_abc", "openai"),
        ("", None),
        ("   ", None),
        ("nonsense", None),
    ],
)
def test_detect_provider(key, expected):
    assert detect_provider(key) == expected


# -- verify_provider_key: status-code mapping + per-provider request shape -------
def _patch_get(monkeypatch, status=200, capture=None, raise_exc=None):
    def fake_get(url, **kwargs):
        if capture is not None:
            capture["url"] = url
            capture.update(kwargs)
        if raise_exc is not None:
            raise raise_exc
        return SimpleNamespace(status_code=status)

    monkeypatch.setattr("httpx.get", fake_get)


def _patch_post(monkeypatch, status=200, capture=None, raise_exc=None):
    def fake_post(url, **kwargs):
        if capture is not None:
            capture["url"] = url
            capture.update(kwargs)
        if raise_exc is not None:
            raise raise_exc
        return SimpleNamespace(status_code=status)

    monkeypatch.setattr("httpx.post", fake_post)


def test_verify_openai_ok(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    assert verify_provider_key("openai", api_key="sk-x") == {"ok": True}
    assert cap["url"] == "https://api.openai.com/v1/models"
    assert cap["headers"]["Authorization"] == "Bearer sk-x"


def test_verify_openai_custom_endpoint(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    verify_provider_key(
        "openai", api_key="sk-x", base_url="https://gw.example/openai/v1/"
    )
    # trailing slash trimmed, /models appended to the custom endpoint
    assert cap["url"] == "https://gw.example/openai/v1/models"


def test_verify_bad_key_is_invalid(monkeypatch):
    _patch_get(monkeypatch, status=401)
    assert verify_provider_key("openai", api_key="sk-bad") == {
        "ok": False,
        "error": "Invalid API key.",
    }


def test_verify_anthropic_headers(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    verify_provider_key("anthropic", api_key="sk-ant-x")
    assert cap["url"] == "https://api.anthropic.com/v1/models"
    assert cap["headers"]["x-api-key"] == "sk-ant-x"
    assert "anthropic-version" in cap["headers"]


def test_verify_gemini_uses_relay_and_header_auth(monkeypatch):
    # gemini-relay multi-user rollout: the probe now hits the company relay with the key
    # in a header, not `?key=` on the (unreachable-from-China) Google endpoint.
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    verify_provider_key("gemini", api_key="AIza-x")
    assert cap["url"] == "https://gemini.smjtools.com/v1beta/models"
    assert cap["headers"]["x-goog-api-key"] == "AIza-x"
    assert "params" not in cap


def test_verify_gemini_surfaces_the_relays_own_words(monkeypatch):
    """The v3 relay refuses in a Google-shaped JSON envelope whose message was written for
    the person (not signed in / login revoked / over quota) — Test passes it through
    instead of flattening every 4xx into "Invalid API key."."""
    message = "OpenWorker 中转：登录已失效（过期、被吊销，或已不在允许名单里），请重新登录。"

    def fake_get(url, **kwargs):
        return SimpleNamespace(
            status_code=403,
            json=lambda: {
                "error": {"code": 403, "message": message, "status": "PERMISSION_DENIED"}
            },
        )

    monkeypatch.setattr("httpx.get", fake_get)
    res = verify_provider_key("gemini", api_key="AIzaSy-x")
    assert res == {"ok": False, "error": message}


def test_verify_gemini_non_json_error_still_maps(monkeypatch):
    # a fake with no .json at all — the passthrough must degrade to the generic mapping
    _patch_get(monkeypatch, status=403)
    res = verify_provider_key("gemini", api_key="AIza-x")
    assert res == {"ok": False, "error": "Invalid API key."}


def test_verify_gemini_maps_unusable_auth_key_to_a_key_swap_hint(monkeypatch):
    """An unusable AI Studio `AQ.…` auth key (dead / mis-copied / the wrong one): Google
    answers 401 ACCESS_TOKEN_TYPE_UNSUPPORTED (header form) / API_KEY_SERVICE_BLOCKED
    (bearer form) — verified live 2026-08-27; a healthy auth key sails through untouched.
    Test must say "this key — recopy or reissue it" instead of relaying the riddle."""
    for reason in ("ACCESS_TOKEN_TYPE_UNSUPPORTED", "API_KEY_SERVICE_BLOCKED"):

        def fake_get(url, _reason=reason, **kwargs):
            return SimpleNamespace(
                status_code=401,
                json=lambda: {
                    "error": {
                        "code": 401,
                        "message": "Request had invalid authentication credentials. …",
                        "status": "UNAUTHENTICATED",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                "reason": _reason,
                            }
                        ],
                    }
                },
            )

        monkeypatch.setattr("httpx.get", fake_get)
        res = verify_provider_key("gemini", api_key="AQ.Ab8-auth-key")
        assert res["ok"] is False
        assert "拒收了这一把" in res["error"]


def test_verify_ollama_uses_v1_models_no_key(monkeypatch):
    cap: dict = {}
    _patch_get(monkeypatch, status=200, capture=cap)
    verify_provider_key("ollama", base_url="http://localhost:11434")
    assert cap["url"] == "http://localhost:11434/v1/models"
    assert "headers" not in cap  # keyless


@pytest.mark.parametrize(
    "name,base_url,model",
    [
        (
            "ark",
            "https://ark.ap-southeast.bytepluses.com/api/v3",
            "dola-seed-evolving-latest-version",
        ),
        (
            "ark-agent-plan-cn",
            "https://ark.cn-beijing.volces.com/api/plan/v3",
            "doubao-seed-evolving",
        ),
    ],
)
def test_verify_ark_uses_non_persisted_responses_probe(
    monkeypatch, name, base_url, model
):
    """Reverse-verified probe: the captured fixture must be non-empty and provider-specific."""
    cap: dict = {}
    _patch_post(monkeypatch, status=200, capture=cap)

    assert verify_provider_key(name, api_key="ark-key") == {"ok": True}
    assert cap["url"] == base_url + "/responses"
    assert cap["headers"]["Authorization"] == "Bearer ark-key"
    assert cap["json"] == {
        "model": model,
        "input": "Reply with OK.",
        "max_output_tokens": 1,
        "store": False,
    }


def test_verify_ark_profile_endpoint_override(monkeypatch):
    cap: dict = {}
    _patch_post(monkeypatch, status=200, capture=cap)

    verify_provider_key(
        "ark",
        api_key="ark-key",
        base_url="https://gateway.example/ark/v3/",
    )

    assert cap["url"] == "https://gateway.example/ark/v3/responses"


def test_verify_network_error_is_clean(monkeypatch):
    _patch_get(monkeypatch, raise_exc=ConnectionError("boom"))
    res = verify_provider_key("openai", api_key="sk-x")
    assert res["ok"] is False
    assert "Couldn't reach" in res["error"]


def test_verify_unexpected_status(monkeypatch):
    _patch_get(monkeypatch, status=500)
    res = verify_provider_key("anthropic", api_key="sk-ant-x")
    assert res["ok"] is False
    assert "500" in res["error"]
