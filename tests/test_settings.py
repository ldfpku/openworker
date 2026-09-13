"""Tests for the model API-key settings path (Tauri desktop Phase 2).

A Tauri-launched sidecar doesn't inherit the shell env, so the key may live only in the
SecretStore. These cover: the env→store resolver, the status shape (never leaks the key),
and the REST round-trip. No network, no model calls.
"""

from __future__ import annotations

from pathlib import Path

from coworker.providers import resolve_api_key
from coworker.secrets import SecretStore


def test_resolve_api_key_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-123")
    secrets = SecretStore(path=tmp_path / "secrets.json")
    secrets.put("provider:openai", {"type": "api_key", "api_key": "sk-store-999"})
    assert resolve_api_key(secrets) == "sk-env-123"


def test_resolve_api_key_falls_back_to_store(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    secrets = SecretStore(path=tmp_path / "secrets.json")
    assert resolve_api_key(secrets) is None
    secrets.put("provider:openai", {"type": "api_key", "api_key": "sk-store-999"})
    assert resolve_api_key(secrets) == "sk-store-999"


def test_settings_rest_roundtrip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    client = TestClient(create_app(manager))

    before = client.get("/v1/settings").json()
    assert (
        before["has_key"] is False
        and before["source"] is None
        and before["provider"] == "openai"
    )
    assert before["onboarded"] is False and before["model"] in before["models"]

    set_resp = client.post(
        "/v1/settings/model-key", json={"api_key": "sk-secret-xyz"}
    ).json()
    assert (
        set_resp["ok"] is True
        and set_resp["has_key"] is True
        and set_resp["source"] == "store"
    )

    after = client.get("/v1/settings").json()
    assert after["has_key"] is True
    # the key value is never returned by either endpoint
    assert "sk-secret-xyz" not in str(set_resp) and "api_key" not in after

    # empty key is rejected
    assert (
        client.post("/v1/settings/model-key", json={"api_key": "  "}).json()["ok"]
        is False
    )


def test_default_model_and_onboarding_persist(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    data_dir = tmp_path / "data"
    client = TestClient(create_app(SessionManager(data_dir=data_dir)))

    # set a default model + mark onboarded
    assert (
        client.post("/v1/settings/default-model", json={"model": "gpt-4o"}).json()[
            "model"
        ]
        == "gpt-4o"
    )
    assert (
        client.post("/v1/settings/onboarded", json={"value": True}).json()["onboarded"]
        is True
    )
    assert (
        client.post("/v1/settings/default-model", json={"model": " "}).json()["ok"]
        is False
    )

    # a fresh manager over the same data dir restores both from prefs.json
    reborn = SessionManager(data_dir=data_dir)
    assert reborn.model == "gpt-4o"
    s = reborn.get_settings()
    assert s["onboarded"] is True and s["model"] == "gpt-4o"


def test_nav_layout_setting_roundtrips(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    data_dir = tmp_path / "data"
    client = TestClient(create_app(SessionManager(data_dir=data_dir)))

    # defaults to "flat"
    assert client.get("/v1/settings").json()["nav_layout"] == "flat"

    resp = client.post("/v1/settings/nav-layout", json={"nav_layout": "grouped"}).json()
    assert resp == {"ok": True, "nav_layout": "grouped"}
    assert client.get("/v1/settings").json()["nav_layout"] == "grouped"

    # unknown value falls back to flat; persists across a restart
    assert (
        client.post("/v1/settings/nav-layout", json={"nav_layout": "bogus"}).json()[
            "nav_layout"
        ]
        == "flat"
    )
    client.post("/v1/settings/nav-layout", json={"nav_layout": "grouped"})
    reborn = SessionManager(data_dir=data_dir)
    assert reborn.get_settings()["nav_layout"] == "grouped"


def test_scratch_base_setting_persists_and_drives_provisioning(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    data_dir = tmp_path / "data"
    client = TestClient(create_app(SessionManager(data_dir=data_dir)))

    # defaults to ~/OpenWorker
    assert client.get("/v1/settings").json()["scratch_base"] == "~/OpenWorker"

    base = tmp_path / "my coworker files"
    resp = client.post("/v1/settings/scratch-base", json={"path": str(base)}).json()
    assert resp["ok"] is True and resp["scratch_base"] == str(base)
    assert base.is_dir()  # created on set
    assert (
        client.post("/v1/settings/scratch-base", json={"path": " "}).json()["ok"]
        is False
    )

    # persists across a restart and actually drives where scratch dirs are provisioned
    reborn = SessionManager(data_dir=data_dir)
    assert reborn.get_settings()["scratch_base"] == str(base)
    scratch = reborn._provision_scratch("sess-xyz")
    assert Path(scratch) == (base / "sess-xyz").resolve() and Path(scratch).is_dir()


def test_ollama_models_gated_on_liveness(tmp_path, monkeypatch):
    """`ollama:*` entries show only while a local Ollama answers — keyless must not mean
    always-present (a stray ollama:<junk> pref would otherwise render forever)."""
    from coworker.server.manager import SessionManager

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.add_model("ollama:llama3.3")

    monkeypatch.setattr(SessionManager, "_ollama_alive", lambda self: False)
    assert "ollama:llama3.3" not in manager.get_settings()["models"]

    monkeypatch.setattr(SessionManager, "_ollama_alive", lambda self: True)
    assert "ollama:llama3.3" in manager.get_settings()["models"]


def test_default_model_change_rebinds_open_drafts_but_not_history_or_hand_picks(
    tmp_path, monkeypatch
):
    """Owner-hit 2026-09-10 ("the default model doesn't apply globally"): a draft whose
    engine was built before the default changed kept the OLD default, so the composer the
    person came back to still showed the model they had just moved away from. The new
    default now lands in every open draft — except one whose model was picked by hand in
    the composer (engine.model_pinned) — and never touches a session with history."""
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    old = manager.model

    draft = manager.get_engine("draft-1", agent="cowork")
    pinned = manager.get_engine("draft-2", agent="cowork")
    pinned.switch_model("zai:glm-5.2")
    pinned.model_pinned = True  # what the socket's set_model sets
    talked = manager.get_engine("talked-1", agent="cowork")
    talked.messages.append({"role": "user", "content": "hi"})
    talked.messages.append({"role": "assistant", "content": "hello"})
    assert draft.model == old and talked.model == old

    # A draft mid re-target carries its picks outside the engine map.
    manager._draft_carry["draft-3"] = {
        "model": old,
        "mode": manager.mode,
        "messages": [],
        "extra_roots": [],
    }
    manager._draft_carry["draft-4"] = {
        "model": "zai:glm-5.2",
        "model_pinned": True,
        "mode": manager.mode,
        "messages": [],
        "extra_roots": [],
    }

    res = manager.set_default_model("gemini:gemini-3.5-flash")
    assert res["ok"] is True and res["model"] == "gemini:gemini-3.5-flash"
    assert draft.model == "gemini:gemini-3.5-flash"
    assert pinned.model == "zai:glm-5.2"
    assert talked.model == old
    assert manager._draft_carry["draft-3"]["model"] == "gemini:gemini-3.5-flash"
    assert manager._draft_carry["draft-4"]["model"] == "zai:glm-5.2"


def test_remove_key_keeps_the_gemini_login_and_moves_a_stranded_default(tmp_path, monkeypatch):
    """Audit 2026-09-10: "Remove key…" on Gemini used to delete the whole profile —
    including the relay sign-in the confirm dialog never mentioned — and a default model
    left on a provider that just lost its key blocked sending in every session even with
    another provider connected. Now the login survives, the cached catalog goes, and the
    default moves to a model whose provider still works."""
    from coworker.server.manager import SessionManager

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.secrets.put(
        "provider:gemini",
        {
            "type": "api_key",
            "api_key": "AIza-test",
            "key_set_at": "2026-09-01",
            "relay_token": "owr_abc",
            "relay_email": "a@example.test",
            "relay_name": "A",
        },
    )
    manager.secrets.put("provider:zai", {"type": "api_key", "api_key": "sk-glm"})
    manager._model_catalog["gemini"] = {"fetched_at": "x", "models": [{"id": "m", "label": "M"}], "error": None, "failed_at": None}
    assert manager.set_default_model("gemini:gemini-3.5-flash")["ok"] is True
    assert manager.get_settings()["model_ready"] is True

    # The Gemini card knows a key without a login is not "connected".
    row = next(r for r in manager.get_providers() if r["name"] == "gemini")
    assert row["configured"] is True and row["needs_signin"] is False

    assert manager.remove_provider("gemini")["ok"] is True
    profile = manager.secrets.get("provider:gemini") or {}
    assert "api_key" not in profile and "key_set_at" not in profile
    assert profile["relay_token"] == "owr_abc" and profile["relay_email"] == "a@example.test"
    assert "gemini" not in manager._model_catalog
    assert manager._model_provider(manager.model) == "zai"
    assert manager.get_settings()["model_ready"] is True

    # A key without a login: still "configured", but flagged so the card can say so.
    manager.secrets.put("provider:gemini", {"type": "api_key", "api_key": "AIza-test"})
    row = next(r for r in manager.get_providers() if r["name"] == "gemini")
    assert row["configured"] is True and row["needs_signin"] is True


def test_default_stays_put_when_no_other_provider_is_connected(tmp_path, monkeypatch):
    from coworker.providers.registry import provider_descriptors
    from coworker.server.manager import SessionManager

    # EVERY provider key the registry reads, not just OpenAI's: one of them set on the
    # machine running the suite (NVIDIA_API_KEY, ZAI_API_KEY…) makes "nothing else to move
    # to" false, and the test then fails for a reason unrelated to what it checks.
    for desc in provider_descriptors():
        if getattr(desc, "env_key", None):
            monkeypatch.delenv(desc.env_key, raising=False)
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.secrets.put("provider:zai", {"type": "api_key", "api_key": "sk-glm"})
    manager.set_default_model("zai:glm-5.2")
    assert manager.remove_provider("zai")["ok"] is True
    # Nothing else to move to: the default is left alone (model_ready says the rest).
    assert manager.model == "zai:glm-5.2"
    assert manager.get_settings()["model_ready"] is False
