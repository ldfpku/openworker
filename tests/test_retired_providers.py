from __future__ import annotations

import pytest

from coworker.providers.catalog import supports_catalog
from coworker.providers.matrix import MATRIX, models_for_provider
from coworker.providers.registry import (
    RETIRED_PROVIDERS, build_provider_client, detect_provider, get_descriptor,
    list_provider_models, provider_names, verify_provider_key,
)
from coworker.providers.router import ProviderRouter


@pytest.mark.parametrize("name", ["nvidia"])
def test_retired_provider_is_not_offered_or_probed(name, monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("retired providers must not call out"))
    assert name in RETIRED_PROVIDERS
    assert name not in provider_names()
    assert get_descriptor(name) is None
    assert not supports_catalog(name)
    assert models_for_provider(name) == []
    assert verify_provider_key(name, api_key="old")["ok"] is False
    assert list_provider_models(name, api_key="old")["ok"] is False
    with pytest.raises(ValueError, match="no longer available"):
        build_provider_client(name, {}, None)
    with pytest.raises(ValueError, match="no longer available"):
        ProviderRouter().complete(model=f"{name}:old", messages=[])


def test_gemini_is_offered_again():
    """Restored 2026-10-14: the person's own Google AI Studio key, sent through the
    company relay. Only NVIDIA stays retired."""
    from coworker.providers import GeminiProvider

    assert "gemini" not in RETIRED_PROVIDERS
    assert "gemini" in provider_names()
    assert get_descriptor("gemini") is not None
    assert supports_catalog("gemini")
    assert "gemini:gemini-3.7-flash" in MATRIX
    assert models_for_provider("gemini")
    assert isinstance(build_provider_client("gemini", {}, None), GeminiProvider)
    assert ProviderRouter()._provider_name("gemini:gemini-3.7-flash") == "gemini"
    names = provider_names()
    assert names.index("anthropic") < names.index("gemini") < names.index("bedrock")


def test_retirement_preserves_gateway_google_and_other_providers():
    assert any(m.startswith("aigw:google-ai-studio/") for m in MATRIX)
    assert any(m.startswith("vertex:gemini/") for m in MATRIX)
    for name in ("aigw", "vertex", "ollama", "custom", "openai", "anthropic", "gemini"):
        assert get_descriptor(name) is not None
    assert detect_provider("AIza-old") == "gemini"
    assert detect_provider("nvapi-old") is None


def test_relay_routes_are_registered(tmp_path):
    from coworker.server import SessionManager, create_app

    app = create_app(SessionManager(data_dir=tmp_path))
    paths = {route.path for route in app.routes}
    for path in ("/v1/relay/login", "/v1/relay/status", "/v1/relay/logout", "/relay/callback"):
        assert path in paths
    assert "/v1/aigw/login" in paths
