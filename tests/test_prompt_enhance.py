"""Composer "Enhance prompt" button — POST /v1/prompt/enhance → manager.enhance_prompt().

Session-agnostic (like autotitle): one one-shot provider.complete call, no agent loop, no
session id required — so a draft session (nothing persisted yet) can still use it. Every
failure path (empty/too-long input, provider error, empty completion) must come back as
{"ok": False, "error": ...} over a 200 response — never a 500 — so the frontend's `!r.ok`
check on the HTTP response can never be the thing that catches a backend failure.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.server import SessionManager, create_app


class RecordingProvider(ProviderClient):
    """Queues completions (or exceptions) and records every call's model/messages/settings."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls: list[dict] = []

    def complete(self, *, model, messages, tools=None, **settings):
        self.calls.append({"model": model, "messages": messages, **settings})
        item = self._turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def capabilities(self, model):
        return ModelCapabilities()


def _text(text):
    return AssistantTurn(text=text, finish_reason="stop")


def _client(tmp_path, turns, model="gpt-5.6-sol"):
    provider = RecordingProvider(turns)
    manager = SessionManager(workspace=tmp_path, provider=provider, model=model)
    return TestClient(create_app(manager)), provider


def test_enhance_prompt_success(tmp_path):
    client, provider = _client(tmp_path, [_text("写一份更清楚的提示词")])
    resp = client.post("/v1/prompt/enhance", json={"text": "帮我写个东西"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "text": "写一份更清楚的提示词"}
    assert len(provider.calls) == 1


def test_system_prompt_contains_rewrite_only_rules(tmp_path):
    client, provider = _client(tmp_path, [_text("改写后的提示词")])
    client.post("/v1/prompt/enhance", json={"text": "帮我写个东西"})
    system_msg = provider.calls[0]["messages"][0]
    assert system_msg["role"] == "system"
    # Only-rewrite-never-execute, and the "preserve as-is" carve-outs, must be in the
    # instructions actually sent to the model — not just in a comment above the constant.
    assert "改写" in system_msg["content"]
    assert "不执行" in system_msg["content"]
    assert "原样保留" in system_msg["content"]
    user_msg = provider.calls[0]["messages"][1]
    assert user_msg["role"] == "user"
    assert "帮我写个东西" in user_msg["content"]


def test_model_passthrough(tmp_path):
    client, provider = _client(tmp_path, [_text("x")])
    client.post(
        "/v1/prompt/enhance", json={"text": "hi", "model": "anthropic:claude-opus-4-8"}
    )
    assert provider.calls[0]["model"] == "anthropic:claude-opus-4-8"


def test_model_falls_back_to_session_default(tmp_path):
    client, provider = _client(tmp_path, [_text("x")], model="gpt-5.6-terra")
    client.post("/v1/prompt/enhance", json={"text": "hi"})
    assert provider.calls[0]["model"] == "gpt-5.6-terra"


def test_empty_text_does_not_call_provider(tmp_path):
    client, provider = _client(tmp_path, [])
    resp = client.post("/v1/prompt/enhance", json={"text": "   "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body
    assert provider.calls == []


def test_missing_text_field_does_not_call_provider(tmp_path):
    client, provider = _client(tmp_path, [])
    resp = client.post("/v1/prompt/enhance", json={})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert provider.calls == []


def test_too_long_text_does_not_call_provider(tmp_path):
    client, provider = _client(tmp_path, [])
    resp = client.post("/v1/prompt/enhance", json={"text": "x" * 8001})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert provider.calls == []


def test_non_string_text_returns_200_with_ok_false(tmp_path):
    """A malformed body (e.g. {"text": 12345}) must never 500 — `int`/`list` have no
    .strip(), so the handler must reject non-str input before touching it."""
    client, provider = _client(tmp_path, [])
    resp = client.post("/v1/prompt/enhance", json={"text": 12345})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body
    assert provider.calls == []


def test_provider_error_returns_200_with_ok_false(tmp_path):
    client, provider = _client(tmp_path, [RuntimeError("model down")])
    resp = client.post("/v1/prompt/enhance", json={"text": "hi"})
    assert resp.status_code == 200  # must never 500 — the frontend relies on this
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body


def test_empty_completion_does_not_overwrite(tmp_path):
    """A whitespace-only completion is treated as a failure, not a text to hand back —
    the composer must not replace the user's draft with an empty string."""
    client, provider = _client(tmp_path, [_text("   ")])
    resp = client.post("/v1/prompt/enhance", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "text" not in body


def test_strips_surrounding_code_fence(tmp_path):
    client, provider = _client(tmp_path, [_text("```\n改写后的提示词\n```")])
    resp = client.post("/v1/prompt/enhance", json={"text": "hi"})
    assert resp.json() == {"ok": True, "text": "改写后的提示词"}


def test_strips_surrounding_quotes(tmp_path):
    client, provider = _client(tmp_path, [_text('"改写后的提示词"')])
    resp = client.post("/v1/prompt/enhance", json={"text": "hi"})
    assert resp.json() == {"ok": True, "text": "改写后的提示词"}


def test_settings_passed_to_provider(tmp_path):
    client, provider = _client(tmp_path, [_text("x")])
    client.post("/v1/prompt/enhance", json={"text": "hi"})
    call = provider.calls[0]
    assert call["temperature"] == 0.3
    assert call["max_tokens"] == 2000
    assert call["reasoning_effort"] == "none"
