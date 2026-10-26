"""Self-managed-main-model detection used by Cloudflare compaction routing."""

from __future__ import annotations

from coworker.providers.router import ProviderRouter


def test_custom_models_are_self_managed_even_behind_a_remote_domain():
    # The reported local deployment is exposed as https://qwen.smjtools.com/v1.
    # Looking for localhost/LAN addresses would miss that real configuration.
    router = ProviderRouter()
    assert router.is_local_model("custom:qwen3.8-flash-next-iq2_xs")
    assert router.is_local_model("custom:hosted-openai-compatible-model")


def test_ollama_is_self_managed_but_gateway_models_are_not():
    router = ProviderRouter()
    assert router.is_local_model("ollama:qwen3:8b")
    assert not router.is_local_model("aigw:anthropic/claude-haiku-5.5")
    assert not router.is_local_model("gemini:gemini-3.5-flash-lite")
