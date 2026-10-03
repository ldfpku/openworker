from __future__ import annotations

import pytest

from coworker.providers.catalog import supports_catalog
from coworker.providers.matrix import MATRIX, models_for_provider
from coworker.providers.registry import (
    build_provider_client, detect_provider, get_descriptor, list_provider_models,
    provider_names, verify_provider_key,
)
from coworker.providers.router import ProviderRouter


@pytest.mark.parametrize("name", ["gemini", "nvidia"])
def test_retired_provider_is_not_offered_or_probed(name, monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: pytest.fail("retired providers must not call out"))
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


def test_retirement_preserves_gateway_google_and_other_providers():
    assert any(m.startswith("aigw:google-ai-studio/") for m in MATRIX)
    assert any(m.startswith("vertex:gemini/") for m in MATRIX)
    for name in ("aigw", "vertex", "ollama", "custom", "openai", "anthropic"):
        assert get_descriptor(name) is not None
    assert detect_provider("AIza-old") is None
    assert detect_provider("nvapi-old") is None


def test_relay_routes_are_not_registered(tmp_path):
    from coworker.server import SessionManager, create_app

    app = create_app(SessionManager(data_dir=tmp_path))
    paths = {route.path for route in app.routes}
    for path in ("/v1/relay/login", "/v1/relay/status", "/v1/relay/logout", "/relay/callback"):
        assert path not in paths
    assert "/v1/aigw/login" in paths
