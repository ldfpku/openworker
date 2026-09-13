"""P6 gate tests — server: OpenAI-compatible endpoint, WS session API, REST."""

from __future__ import annotations

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    ToolCall,
)
from coworker.server import SessionManager, create_app
from coworker.sessions import SessionRecord


class ScriptedProvider(ProviderClient):
    """A ProviderClient that returns queued AssistantTurns (streams via base default)."""

    def __init__(self, turns):
        self._turns = list(turns)

    def complete(self, *, model, messages, tools=None, **settings):
        # Auto-titling fires a fire-and-forget completion of its own, and since
        # 2026-08-24 one of its three windows opens at turn START — concurrently with
        # the chat turn. It reaches this same provider, so without this guard it POPS a
        # scripted turn and every later turn shifts up by one. That is invisible in a
        # two-turn script (the title eats the trailing turn, after the assertions) and
        # fatal in a three-turn one: test_ws_browser_tool_audit_round_trip scripts
        # load_browser_tools first, which puts browser_close in exactly the slot the
        # title eats. The small-talk sentinel also keeps titling inert — the manager
        # drops that title instead of writing or broadcasting it.
        if messages and "title chat sessions" in str(messages[0].get("content", "")):
            return _text("small-talk")
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def _text(text):
    return AssistantTurn(text=text, finish_reason="stop")


def _tool(name, args, call_id="call_1"):
    return AssistantTurn(tool_calls=[ToolCall(id=call_id, name=name, arguments=args)])


def _client(tmp_path, turns):
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider(turns))
    return TestClient(create_app(manager))


# -- REST -----------------------------------------------------------------------


def test_chat_completions_openai_shape(tmp_path):
    client = _client(tmp_path, [_text("hello world")])
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.5", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello world"
    assert body["choices"][0]["finish_reason"] == "stop"


def test_agents_and_memory_rest(tmp_path):
    client = _client(tmp_path, [])
    agents = client.get("/v1/agents").json()["agents"]
    # The picker lists enabled+surfaced personas. Release lineup (owner 2026-08-31):
    # OpenWorker alone. Every other shipped coworker — Code, the expert lead, and the
    # eight production/R&D roles — is an example listed in Settings with its toggle
    # off; Chat is gone; ships:false personas need OPENWORKER_UNSHIPPED=1.
    names = [a["name"] for a in agents]
    assert names == ["cowork"]
    assert "skills" in client.get("/v1/skills").json()  # catalog (may be empty)

    added = client.post("/v1/memory", json={"content": "prefer pathlib"}).json()
    assert added["content"] == "prefer pathlib"
    assert any(
        m["content"] == "prefer pathlib"
        for m in client.get("/v1/memory").json()["memory"]
    )


def test_disable_persona_archives_its_sessions(tmp_path):
    """Disable = "put this coworker and its history away": the persona's real sessions are
    archived atomically server-side (so its sidebar section disappears with it), internal
    __run__ threads and other personas are untouched, and re-enable never unarchives."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    store = manager.session_store

    def mk(sid, agent):
        store.save(
            SessionRecord(
                session_id=sid,
                workspace=str(tmp_path),
                model="m",
                mode="interactive",
                agent=agent,
            )
        )

    mk("chat-a", "code")
    mk("chat-b", "code")
    mk("chat-old", "code")
    store.set_flags(
        "chat-old", archived=True
    )  # already archived — must not be re-counted
    mk("cowork-a", "cowork")
    mk("__run__r1", "code")  # internal automation thread — never touched

    client = TestClient(create_app(manager))
    body = client.post("/v1/personas/code", json={"enabled": False}).json()
    assert body["ok"] is True
    assert body["archived_sessions"] == 2
    assert store.load("chat-a").archived and store.load("chat-b").archived
    assert store.load("cowork-a").archived is False
    assert store.load("__run__r1").archived is False

    # Re-enable brings the persona back but never rewrites the user's archive state.
    client.post("/v1/personas/chat", json={"enabled": True})
    assert store.load("chat-a").archived

    # The dedicated §5/§8 enable route shares the same semantic.
    mk("chat-c", "code")
    client.post("/v1/personas/code/enable", json={"enabled": False})
    assert store.load("chat-c").archived

    # The DEFAULT coworker cannot be switched off (audit 2026-09-10): every new session,
    # the disabled-coworker fallback and inbound DMs land on it. Both routes refuse, and
    # its sessions stay put.
    for path in ("/v1/personas/cowork", "/v1/personas/cowork/enable"):
        body = client.post(path, json={"enabled": False}).json()
        assert body["ok"] is False and "always available" in body["error"]
    assert manager.personas.is_enabled("cowork") is True
    assert store.load("cowork-a").archived is False
    # …and unlike any other default, making something ELSE the default does not unlock
    # it (audit 2026-09-13): the general OpenWorker is the BASELINE, the floor every
    # fallback ends on, not merely whoever currently holds the default pointer.
    client.post("/v1/personas/code", json={"enabled": True, "default": True})
    assert manager.personas.default_id() == "code"
    body = client.post("/v1/personas/cowork", json={"enabled": False}).json()
    assert body["ok"] is False and "always available" in body["error"]
    assert manager.personas.is_enabled("cowork") is True
    assert store.load("cowork-a").archived is False  # a refused disable archives nothing


def test_connector_tool_settings_and_audit_rest(tmp_path):
    client = _client(tmp_path, [])
    connectors = {
        c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]
    }
    assert any(t["name"] == "browser_open_url" for t in connectors["browser"]["tools"])

    res = client.patch(
        "/v1/connectors/browser/tools", json={"enabled": {"browser_open_url": False}}
    ).json()
    assert res["ok"] is True
    connectors = {
        c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]
    }
    browser_tools = {t["name"]: t for t in connectors["browser"]["tools"]}
    assert browser_tools["browser_open_url"]["enabled"] is False

    assert client.get("/v1/audit", params={"session_id": "none"}).json()["events"] == []
    assert client.get("/v1/browser/state").json()["status"] in {
        "closed",
        "open",
        "error",
    }


def test_artifacts_list_and_read_previewable_files(tmp_path):
    (tmp_path / "brief.md").write_text("# Brief\n\nHello", encoding="utf-8")
    (tmp_path / "page.html").write_text("<h1>Preview</h1>", encoding="utf-8")
    (tmp_path / ".secret.md").write_text("hidden", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "noise.md").write_text("skip", encoding="utf-8")

    client = _client(tmp_path, [])
    artifacts = client.get("/v1/sessions/unknown/artifacts").json()["artifacts"]
    by_path = {a["path"]: a for a in artifacts}

    assert by_path["brief.md"]["kind"] == "markdown"
    assert by_path["page.html"]["kind"] == "html"
    assert ".secret.md" not in by_path
    assert "node_modules/noise.md" not in by_path

    md = client.get(
        "/v1/sessions/unknown/artifacts/read", params={"path": "brief.md"}
    ).json()
    assert md["ok"] is True
    assert md["kind"] == "markdown"
    assert md["content"].startswith("# Brief")

    html = client.get(
        "/v1/sessions/unknown/artifacts/read", params={"path": "page.html"}
    ).json()
    assert html["ok"] is True
    assert html["kind"] == "html"
    assert "<h1>Preview</h1>" in html["content"]


def test_artifact_read_folder_returns_listing(tmp_path):
    """A linked directory (e.g. a skill package dir) renders as a listing, never a dead
    'not found' (owner report 2026-07-27). Dirs first, then files, sizes on files only."""
    pkg = tmp_path / "directory-statistics"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("---\nname: x\n---\nbody", encoding="utf-8")
    (pkg / "stats.py").write_text("print(1)", encoding="utf-8")
    (pkg / "examples").mkdir()

    client = _client(tmp_path, [])
    res = client.get(
        "/v1/sessions/unknown/artifacts/read", params={"path": "directory-statistics"}
    ).json()
    assert res["ok"] is True and res["kind"] == "folder"
    names = [e["name"] for e in res["entries"]]
    assert names == ["examples", "SKILL.md", "stats.py"]  # dirs first, then files by name
    assert res["entries"][0]["dir"] is True
    assert res["entries"][2]["size"] > 0

    # A genuinely missing path keeps a friendly, non-jargon error.
    missing = client.get(
        "/v1/sessions/unknown/artifacts/read", params={"path": "nope.md"}
    ).json()
    assert missing["ok"] is False
    assert "moved or deleted" in missing["error"]


def test_artifact_read_rejects_path_escape(tmp_path):
    client = _client(tmp_path, [])
    escaped = client.get(
        "/v1/sessions/unknown/artifacts/read", params={"path": "../outside.md"}
    ).json()
    assert escaped["ok"] is False
    assert "escapes" in escaped["error"]


def test_sessions_hide_scheduled_internal_runs(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    manager.session_store.save(
        SessionRecord(
            session_id="normal",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "normal task"}],
            title="Normal task",
            agent="cowork",
        )
    )
    manager.session_store.save(
        SessionRecord(
            session_id="__run__daily-news-1",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "scheduled run"}],
            title="Daily news briefing",
            agent="cowork",
        )
    )
    manager.session_store.save(
        SessionRecord(
            session_id="__task__daily-news",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "scheduled task"}],
            title="Daily news briefing",
            agent="cowork",
        )
    )
    client = TestClient(create_app(manager))
    session_ids = {
        s["session_id"] for s in client.get("/v1/sessions").json()["sessions"]
    }
    assert "normal" in session_ids
    assert "__run__daily-news-1" not in session_ids
    assert "__task__daily-news" not in session_ids


def test_sessions_can_be_renamed_and_deleted(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    manager.session_store.save(
        SessionRecord(
            session_id="rename-me",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "original"}],
            title="Original title",
            agent="cowork",
        )
    )
    client = TestClient(create_app(manager))

    renamed = client.patch(
        "/v1/sessions/rename-me", json={"title": "  Better title  "}
    ).json()
    assert renamed["ok"] is True
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert any(
        s["session_id"] == "rename-me" and s["title"] == "Better title"
        for s in sessions
    )

    deleted = client.delete("/v1/sessions/rename-me").json()
    assert deleted["ok"] is True
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert all(s["session_id"] != "rename-me" for s in sessions)
    assert client.get("/v1/sessions/rename-me/messages").json()["messages"] == []


def test_sessions_can_be_pinned_and_archived(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    for sid in ("older", "newer"):
        manager.session_store.save(
            SessionRecord(
                session_id=sid,
                workspace=str(tmp_path),
                model="gpt-5.5",
                mode="interactive",
                messages=[{"role": "user", "content": sid}],
                agent="cowork",
            )
        )
    client = TestClient(create_app(manager))

    assert (
        client.patch("/v1/sessions/older", json={"pinned": True}).json()["ok"] is True
    )
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert sessions[0]["session_id"] == "older" and sessions[0]["pinned"] is True

    assert (
        client.patch("/v1/sessions/newer", json={"archived": True}).json()["ok"] is True
    )
    by_id = {s["session_id"]: s for s in client.get("/v1/sessions").json()["sessions"]}
    assert by_id["newer"]["archived"] is True

    assert (
        client.patch("/v1/sessions/older", json={"pinned": False}).json()["ok"] is True
    )
    assert (
        client.patch("/v1/sessions/newer", json={"archived": False}).json()["ok"]
        is True
    )
    by_id = {s["session_id"]: s for s in client.get("/v1/sessions").json()["sessions"]}
    assert by_id["older"]["pinned"] is False and by_id["newer"]["archived"] is False


# -- WebSocket ------------------------------------------------------------------


def _drain(ws, on_permission=None):
    """Collect event types until turn_done; optionally answer permission_required."""
    types = []
    while True:
        event = ws.receive_json()
        types.append(event["type"])
        if event["type"] == "permission_required" and on_permission:
            ws.send_json({"type": "approval", "decision": on_permission})
        if event["type"] == "turn_done":
            return types


def test_ws_simple_turn(tmp_path):
    client = _client(tmp_path, [_text("done thinking")])
    with client.websocket_connect("/ws/session/s1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hello"})
        types = _drain(ws)
        assert "assistant_message" in types
        assert "turn_end" in types


def test_ws_rejects_oversized_message(tmp_path):
    from coworker.server import app as app_mod
    from coworker.attachments import MAX_ATTACHMENTS

    client = _client(tmp_path, [_text("should not run")])
    with client.websocket_connect("/ws/session/big") as ws:
        assert ws.receive_json()["type"] == "ready"

        # Oversized text → single input-rejected frame, no turn runs.
        ws.send_json(
            {"type": "user_message", "text": "x" * (app_mod._MAX_MESSAGE_TEXT_CHARS + 1)}
        )
        evt = ws.receive_json()
        assert evt["type"] == "input_rejected"
        assert "too long" in evt["data"]["error"].lower()

        # The ingress cap is the same cap the attachment builder enforces.
        assert app_mod._MAX_ATTACHMENTS == MAX_ATTACHMENTS
        ws.send_json(
            {
                "type": "user_message",
                "text": "hi",
                "attachments": ["a"] * (app_mod._MAX_ATTACHMENTS + 1),
            }
        )
        evt = ws.receive_json()
        assert evt["type"] == "input_rejected"
        assert "attachment" in evt["data"]["error"].lower()

        # A normal message still works afterwards (the socket wasn't torn down).
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_done" in _drain(ws)


def test_ws_rejects_malformed_payloads_without_killing_socket(tmp_path):
    client = _client(tmp_path, [_text("normal")])
    with client.websocket_connect("/ws/session/malformed") as ws:
        assert ws.receive_json()["type"] == "ready"

        invalid = [
            [],
            {"type": "user_message", "text": ["not", "text"]},
            {"type": "user_message", "text": "x", "attachments": {}},
            {
                "type": "user_message",
                "text": "x",
                "attachments": [{"kind": "image", "data_url": "https://example.com/x"}],
            },
            {"type": "set_model", "model": {"unexpected": True}},
            {"type": "unknown"},
        ]
        for payload in invalid:
            ws.send_json(payload)
            evt = ws.receive_json()
            assert evt["type"] == "input_rejected"

        ws.send_json({"type": "user_message", "text": "still works"})
        assert "turn_done" in _drain(ws)


def test_ws_allows_only_one_inflight_turn_per_session(tmp_path):
    import threading
    import time

    class SlowProvider(ProviderClient):
        def __init__(self):
            self._lock = threading.Lock()
            self.active = 0
            self.max_active = 0

        def complete(self, *, model, messages, tools=None, **settings):
            # The fire-and-forget auto-title completion legitimately runs CONCURRENTLY
            # with the chat turn (it fires at turn start, owner catch 2026-08-24) — the
            # invariant under test is one CHAT turn at a time, so exclude title calls.
            if messages and "title chat sessions" in str(messages[0].get("content", "")):
                return _text("A Title")
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.08)
                return _text("done")
            finally:
                with self._lock:
                    self.active -= 1

        def capabilities(self, model):
            return ModelCapabilities()

    provider = SlowProvider()
    manager = SessionManager(workspace=tmp_path, provider=provider)
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/serialized") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "first"})
        ws.send_json({"type": "user_message", "text": "second"})

        types = []
        while "turn_done" not in types:
            types.append(ws.receive_json()["type"])

    assert "input_rejected" in types
    assert provider.max_active == 1
    engine = manager._engines["serialized"]
    user_messages = [m for m in engine.messages if m.get("role") == "user"]
    assert [m["content"] for m in user_messages] == ["first"]


def test_ws_rate_limits_inbound_frames(tmp_path):
    from coworker.server import app as app_mod
    from starlette.websockets import WebSocketDisconnect

    client = _client(tmp_path, [])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/session/rate") as ws:
            assert ws.receive_json()["type"] == "ready"
            for _ in range(app_mod._WS_RATE_LIMIT_COUNT):
                ws.send_json({"type": "unknown"})
                assert ws.receive_json()["type"] == "input_rejected"
            ws.send_json({"type": "unknown"})
            assert ws.receive_json()["type"] == "input_rejected"
            ws.receive_json()


def test_server_sets_explicit_websocket_frame_limit(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from coworker.server import run as server_run

    seen = {}
    fake_app = object()

    monkeypatch.setattr(server_run, "_ensure_ca_bundle", lambda: None)
    monkeypatch.setattr(server_run, "_exit_when_orphaned", lambda: None)
    monkeypatch.setattr(server_run, "build_app", lambda *args: fake_app)
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda app, **kwargs: seen.update(app=app, **kwargs)),
    )

    server_run.main(["--cwd", str(tmp_path), "--port", "8766"])

    assert seen["app"] is fake_app
    assert seen["ws_max_size"] == server_run._WS_MAX_FRAME_BYTES


def test_standalone_server_token_file_is_user_only(tmp_path, monkeypatch):
    import os

    from coworker.server import run as server_run

    monkeypatch.delenv("COWORKER_API_TOKEN", raising=False)
    path = server_run._ensure_api_token(9876)
    try:
        assert path == tmp_path / "coworker-state" / "sidecar-9876.token"
        assert path.read_text().strip() == os.environ["COWORKER_API_TOKEN"]
        assert len(path.read_text().strip()) == 64
        if sys.platform == "win32":
            # Windows has no POSIX mode bits (chmod only toggles read-only): the writer
            # restricts the ACL instead — inheritance stripped, current user alone.
            # encoding/errors: icacls prints in the console codepage (cp936 on a zh-CN
            # box), and decoding that as UTF-8 raises inside subprocess's reader thread,
            # losing stdout entirely.
            out = subprocess.run(
                ["icacls", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
            user = os.environ.get("USERNAME", "")
            assert user and user in out
            assert "NT AUTHORITY\SYSTEM" not in out
            assert "BUILTIN\Administrators" not in out
        else:
            assert (path.stat().st_mode & 0o777) == 0o600
    finally:
        path.unlink(missing_ok=True)
        os.environ.pop("COWORKER_API_TOKEN", None)


def test_ws_error_persists_notice_and_retry_reruns(tmp_path):
    class FlakyProvider(ProviderClient):
        def __init__(self):
            self.calls = 0

        def complete(self, *, model, messages, tools=None, **settings):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("outage")
            return _text("recovered")

        def capabilities(self, model):
            return ModelCapabilities()

    manager = SessionManager(workspace=tmp_path, provider=FlakyProvider())
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/flaky") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "error" in _drain(ws)
        # The error survives as a persisted notice (reload shows what happened)…
        messages = client.get("/v1/sessions/flaky/messages").json()["messages"]
        assert messages[-1]["role"] == "notice" and messages[-1]["kind"] == "error"
        # …and retry re-runs the turn without a new user message.
        ws.send_json({"type": "retry"})
        types = _drain(ws)
        assert "turn_start" in types and "assistant_message" in types
    messages = client.get("/v1/sessions/flaky/messages").json()["messages"]
    assert messages[-1]["role"] == "assistant" and messages[-1]["content"] == "recovered"
    assert sum(1 for m in messages if m["role"] == "user") == 1


# -- origin gate (local-API hardening): a browser page on a foreign origin must not be able to
# read the API cross-origin or open the driving WebSocket. -------------------------------------


def test_cors_rejects_foreign_origin(tmp_path):
    client = _client(tmp_path, [])
    # A random website's origin gets no ACAO header, so the browser blocks the read.
    resp = client.get("/v1/sessions", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
    # The desktop webview's own origin is allowed.
    ok = client.get("/v1/sessions", headers={"Origin": "tauri://localhost"})
    assert ok.headers.get("access-control-allow-origin") == "tauri://localhost"
    # Localhost dev/browser build is allowed too.
    dev = client.get("/v1/sessions", headers={"Origin": "http://localhost:1420"})
    assert dev.headers.get("access-control-allow-origin") == "http://localhost:1420"


def test_ws_rejects_foreign_origin(tmp_path):
    from starlette.websockets import WebSocketDisconnect as WSD

    client = _client(tmp_path, [_text("hi")])
    with pytest.raises(WSD) as e:
        with client.websocket_connect(
            "/ws/session/x", headers={"Origin": "https://evil.example"}
        ) as ws:
            ws.receive_json()
    assert e.value.code == 1008


def test_ws_allows_webview_origin(tmp_path):
    client = _client(tmp_path, [_text("hi")])
    with client.websocket_connect(
        "/ws/session/x", headers={"Origin": "http://tauri.localhost"}
    ) as ws:
        assert ws.receive_json()["type"] == "ready"


def test_sidecar_token_gates_rest_and_websockets(tmp_path, monkeypatch):
    from coworker.mcp.config import global_mcp_path
    from starlette.websockets import WebSocketDisconnect as WSD

    monkeypatch.setenv("COWORKER_API_TOKEN", "a" * 64)
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))

    assert client.get("/v1/health").json() == {"status": "ok"}
    assert client.get("/v1/sessions").status_code == 401
    assert client.get(
        "/v1/sessions", headers={"X-OpenWorker-Token": "wrong"}
    ).status_code == 401

    headers = {"X-OpenWorker-Token": "a" * 64}
    assert client.get("/v1/health", headers=headers).json()[
        "default_workspace"
    ] == str(tmp_path.resolve())
    assert client.get("/v1/sessions", headers=headers).status_code == 200

    rejected = client.post(
        "/v1/mcp",
        json={"name": "evil", "config": {"command": "sh", "args": ["-c", "id"]}},
    )
    assert rejected.status_code == 401
    assert not global_mcp_path().exists()

    with pytest.raises(WSD) as denied:
        with client.websocket_connect("/ws/session/tokenless") as ws:
            ws.receive_json()
    assert denied.value.code == 1008

    with client.websocket_connect(
        "/ws/session/authed", subprotocols=["openworker", "a" * 64]
    ) as ws:
        assert ws.accepted_subprotocol == "openworker"
        assert ws.receive_json()["type"] == "ready"

    with client.websocket_connect(
        "/ws/events", subprotocols=["openworker", "a" * 64]
    ) as ws:
        assert ws.accepted_subprotocol == "openworker"

    # Redirect callbacks remain tokenless, then enforce their own signed state.
    assert client.get(
        "/auth/callback", params={"code": "x", "state": "bad"}
    ).status_code == 400
    assert client.get("/mcp/oauth/callback").status_code == 400
    assert client.post("/oauth/callback", data={"app_state": "bad"}).status_code == 400


def test_ws_approval_round_trip(tmp_path):
    client = _client(
        tmp_path,
        [
            _tool("write_file", {"path": "made.py", "content": "print(1)\n"}),
            _text("wrote it"),
        ],
    )
    with client.websocket_connect("/ws/session/s2") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "create made.py"})
        types = _drain(ws, on_permission="once")
        assert "permission_required" in types
        assert "tool_finished" in types
    assert (tmp_path / "made.py").read_text() == "print(1)\n"


def test_ws_session_persisted_while_parked_on_approval(tmp_path):
    """A crash mid-turn must not eat the conversation: by the time the engine parks on an
    approval, the session (user message + assistant tool call) is already on disk."""
    manager = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider(
            [_tool("write_file", {"path": "x.py", "content": "1\n"}), _text("done")]
        ),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/persist1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "make x.py"})
        while ws.receive_json()["type"] != "permission_required":
            pass
        # Parked on the approval — nothing approved, turn far from done. Already saved?
        rec = manager.session_store.load("persist1")
        assert rec is not None
        roles = [m.get("role") for m in rec.messages]
        assert "user" in roles  # turn_start checkpoint
        assert "assistant" in roles  # iteration progress checkpoint
        ws.send_json({"type": "approval", "decision": "deny"})
        while ws.receive_json()["type"] != "turn_done":
            pass


def test_ws_browser_tool_audit_round_trip(tmp_path):
    # Browser tools are on-demand (OPE-XXX): the model loads them via load_browser_tools
    # before it can call browser_close — the engine re-reads registry.schemas() every
    # round-trip, so the tool is callable on the very next one.
    client = _client(
        tmp_path,
        [
            _tool("load_browser_tools", {}, call_id="call_0"),
            _tool("browser_close", {}),
            _text("closed"),
        ],
    )
    with client.websocket_connect("/ws/session/browser-audit?agent=cowork") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "close browser"})
        types = _drain(ws, on_permission="once")
        assert "permission_required" in types
        assert "tool_finished" in types

    rows = client.get(
        "/v1/audit", params={"session_id": "browser-audit", "connector": "browser"}
    ).json()["events"]
    assert any(
        r["tool"] == "browser_close" and r["stage"] == "approval_resolved" for r in rows
    )
    assert any(r["tool"] == "browser_close" and r["stage"] == "finished" for r in rows)


def test_open_and_recent_workspaces(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    client = _client(tmp_path, [])
    opened = client.post("/v1/workspaces/open", json={"path": str(proj)}).json()
    assert opened["ok"] is True
    recents = client.get("/v1/workspaces/recent").json()["workspaces"]
    assert any(w["path"] == str(proj.resolve()) for w in recents)


def test_workspace_command_trust_controls_live_engine(tmp_path):
    from urllib.parse import quote

    proj = tmp_path / "trusted-project"
    (proj / ".coworker").mkdir(parents=True)
    (proj / ".coworker" / "config.toml").write_text(
        'allowed_commands = ["pytest"]\nauto_allow = ["write_file"]\n'
    )
    manager = SessionManager(
        workspace=None, data_dir=tmp_path / "data", provider=ScriptedProvider([])
    )
    client = TestClient(create_app(manager))

    with client.websocket_connect(
        f"/ws/session/trust?workspace={quote(str(proj))}"
    ) as ws:
        ready = ws.receive_json()
        policy = ready["data"]["command_trust"]
        assert policy["required"] is True
        assert policy["requested_commands"] == ["pytest"]

        engine = manager._engines["trust"]
        before = engine.permissions.evaluate(
            "run_shell", {"command": "pytest -q"}, None
        )
        assert not before.allowed and before.needs_user
        # Workspace auto_allow remains ignored even after command trust.
        assert "write_file" not in engine.permissions.auto_allow_tools

        trusted = client.post(
            "/v1/workspaces/trust",
            json={"path": str(proj), "trusted": True},
        ).json()
        assert trusted["ok"] and trusted["trusted"]
        assert engine.permissions.evaluate(
            "run_shell", {"command": "pytest -q"}, None
        ).allowed

        listed = client.get("/v1/workspaces/trusted").json()["workspaces"]
        assert [item["workspace"] for item in listed] == [str(proj.resolve())]

        revoked = client.post(
            "/v1/workspaces/trust",
            json={"path": str(proj), "trusted": False},
        ).json()
        assert revoked["ok"] and not revoked["trusted"]
        after = engine.permissions.evaluate(
            "run_shell", {"command": "pytest -q"}, None
        )
        assert not after.allowed and after.needs_user

    manager.workspace_trust.set_trusted(proj, True)
    proj.rename(tmp_path / "moved-project")
    assert client.post(
        "/v1/workspaces/trust",
        json={"path": str(proj), "trusted": False},
    ).json()["ok"]
    assert manager.trusted_workspaces() == []


def test_recent_workspaces_exclude_scratch_dirs(tmp_path):
    # Scratch dirs get touched like any workspace, but must never show up as
    # "recent projects" in the folder gate (owner call, 2026-07-03).
    from coworker.server.manager import SessionManager

    proj = tmp_path / "real-project"
    proj.mkdir()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")
    scratch = mgr._provision_scratch("sess-1")
    mgr.session_store.touch_workspace(str(proj.resolve()))
    mgr.session_store.touch_workspace(scratch)
    paths = [w["path"] for w in mgr.recent_workspaces()]
    assert str(proj.resolve()) in paths
    assert scratch not in paths


def test_delete_session_removes_its_scratch_dir_only(tmp_path):
    # Deleting a session also deletes its per-conversation scratch dir (owner call,
    # 2026-07-03) — but NEVER a real project folder the user picked.
    from pathlib import Path

    from coworker.server.manager import SessionManager
    from coworker.sessions import SessionRecord

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")

    scratch = Path(mgr._provision_scratch("sess-scratch"))
    mgr.session_store.save(
        SessionRecord(
            session_id="sess-scratch",
            workspace=str(scratch),
            model="m",
            mode="interactive",
        )
    )
    assert mgr.delete_session("sess-scratch")["ok"]
    assert not scratch.exists()

    proj = tmp_path / "real-project"
    proj.mkdir()
    mgr.session_store.save(
        SessionRecord(
            session_id="sess-proj", workspace=str(proj), model="m", mode="interactive"
        )
    )
    assert mgr.delete_session("sess-proj")["ok"]
    assert proj.is_dir()  # user folders are sacred


def test_open_invalid_workspace(tmp_path):
    client = _client(tmp_path, [])
    bad = client.post(
        "/v1/workspaces/open", json={"path": str(tmp_path / "nope")}
    ).json()
    assert bad["ok"] is False


def test_open_workspace_create(tmp_path):
    client = _client(tmp_path, [])
    fresh = tmp_path / "fresh-project"
    assert not fresh.exists()
    res = client.post(
        "/v1/workspaces/open", json={"path": str(fresh), "create": True}
    ).json()
    assert res["ok"] is True
    assert fresh.is_dir()


def test_ws_requires_workspace_when_no_default(tmp_path):
    # Manager with no default workspace: a session with no folder is rejected.
    manager = SessionManager(
        workspace=None, data_dir=tmp_path, provider=ScriptedProvider([])
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/nofolder") as ws:
        first = ws.receive_json()
        assert first["type"] == "error"
        assert "workspace" in first["data"]["error"]


def test_ws_with_workspace_query(tmp_path):
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    manager = SessionManager(
        workspace=None,
        data_dir=tmp_path,
        provider=ScriptedProvider([_text("hi from proj")]),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect(f"/ws/session/s?workspace={quote(str(proj))}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["data"]["workspace"] == str(proj.resolve())
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_end" in _drain(ws)


def test_ws_removed_agent_id_falls_back_to_default(tmp_path):
    # Chat is removed (owner 2026-08-21): a stored session or deep link carrying
    # agent=chat resolves to the default persona instead of erroring.
    manager = SessionManager(
        workspace=None,
        data_dir=tmp_path,
        provider=ScriptedProvider([_text("hi")]),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/chat1?agent=chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["data"]["agent"] == "cowork"
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_end" in _drain(ws)


def test_ws_set_mode_auto_skips_approval(tmp_path):
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    manager = SessionManager(
        workspace=None,
        data_dir=tmp_path,
        provider=ScriptedProvider(
            [_tool("write_file", {"path": "a.py", "content": "x"}), _text("done")]
        ),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect(f"/ws/session/sm?workspace={quote(str(proj))}") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "set_mode", "mode": "auto"})
        ws.send_json({"type": "user_message", "text": "write a.py"})
        types = _drain(ws)  # no approval handler — would hang if it asked
        assert "permission_required" not in types
    assert (proj / "a.py").read_text() == "x"


def test_ws_session_resume_via_store(tmp_path):
    # First connection runs a turn and persists the session.
    client = _client(tmp_path, [_text("first answer")])
    with client.websocket_connect("/ws/session/keep") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "text": "remember this"})
        _drain(ws)
    # The session is now listed via REST.
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert any(s["session_id"] == "keep" and s["messages"] > 0 for s in sessions)


def test_ws_first_message_binds_then_midsession_switch_persists_notice(tmp_path):
    """The FIRST user_message's model binds the session silently (race-proof across
    reconnects — found 2026-07-04). Mid-session rebinds are ALLOWED (roadmap item 3,
    2026-07-22, supersedes the 07-04 lock): the switch lands as a persisted model_switch
    notice and a model_changed broadcast, and the next turn runs on the new model."""
    # 4 turns: 3 user turns + the autotitle's fire-and-forget complete() after turn 1.
    client = _client(
        tmp_path, [_text("ok"), _text("Session title"), _text("ok again"), _text("still ok")]
    )
    with client.websocket_connect("/ws/session/model-per-msg") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hi", "model": "zai:glm-5.2"})
        assert "model_changed" not in _drain(ws)  # first bind is silent
        # message WITHOUT a model keeps the bound one (no silent reset to default)
        ws.send_json({"type": "user_message", "text": "again"})
        _drain(ws)
        ws.send_json({"type": "set_model", "model": "kimi:kimi-k2.6"})
        changed = ws.receive_json()
        assert changed["type"] == "model_changed"
        assert changed["data"]["model"] == "kimi:kimi-k2.6"
        assert "Kimi" in changed["data"]["text"]
        ws.send_json({"type": "user_message", "text": "switched now"})
        _drain(ws)
    mgr = client.app.state.manager
    engine = mgr._engines["model-per-msg"]
    assert engine.model == "kimi:kimi-k2.6"
    # The marker is persisted between the turns; the provider never sees it.
    messages = client.get("/v1/sessions/model-per-msg/messages").json()["messages"]
    notices = [m for m in messages if m["role"] == "notice"]
    assert [n["kind"] for n in notices] == ["model_switch"]
    assert all(m.get("role") != "notice" for m in engine._outbound_messages())


def test_session_messages_prefers_the_live_engine(tmp_path):
    """Opening a RUNNING session (e.g. a scheduled automation's first turn) must show the live
    conversation: the persisted record may not exist yet mid-turn — reading only the store gave
    a blank transcript on first open (owner report, 2026-07-04)."""
    client = _client(tmp_path, [_text("ok")])
    mgr = client.app.state.manager
    engine = mgr.get_engine("__run__live", agent="chat")
    engine.messages.append({"role": "user", "content": "hi from a running automation"})

    msgs = client.get("/v1/sessions/__run__live/messages").json()["messages"]
    assert any(m.get("content") == "hi from a running automation" for m in msgs)


def test_pick_native_folder_paths(tmp_path, monkeypatch):
    """The sidecar-side folder picker (for browser GUIs): picked path round-trips; cancel and
    missing-picker degrade to ok:False without raising."""
    import subprocess
    from types import SimpleNamespace

    client = _client(tmp_path, [])
    mgr = client.app.state.manager

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="/tmp/picked\n", stderr=""
        ),
    )
    assert client.post("/v1/workspaces/pick").json() == {
        "ok": True,
        "path": "/tmp/picked",
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="", stderr="User canceled."
        ),
    )
    assert client.post("/v1/workspaces/pick").json()["ok"] is False

    def boom(*a, **k):
        raise OSError("no zenity")

    monkeypatch.setattr(subprocess, "run", boom)
    out = mgr.pick_native_folder()
    assert out["ok"] is False and "picker" in out["error"]


def test_provider_set_and_remove_roundtrip(tmp_path):
    """Settings ▸ Models "Remove key": DELETE /v1/providers/{name} forgets the stored
    profile so the provider reads unconfigured again; unknown names are a clean error.
    """
    client = _client(tmp_path, [])
    assert client.post(
        "/v1/providers", json={"name": "zai", "fields": {"api_key": "zk-test"}}
    ).json()["ok"]
    prov = {p["name"]: p for p in client.get("/v1/providers").json()}
    assert prov["zai"]["configured"] and prov["zai"]["key_set_at"]

    assert client.delete("/v1/providers/zai").json()["ok"]
    prov = {p["name"]: p for p in client.get("/v1/providers").json()}
    assert not prov["zai"]["configured"]
    assert not prov["zai"]["key_set_at"]

    assert not client.delete("/v1/providers/nope").json()["ok"]


def test_always_allow_grants_survive_restart(tmp_path):
    """"Always allow" is session-scoped, and the session outlives the process — a restart
    (fresh manager over the same store) must not re-ask for an approved command
    (owner-hit 2026-07-22 on the 0.1.6 walkthrough)."""

    def _shell_turns():
        return ScriptedProvider(
            [
                _tool("run_shell", {"command": "uname -a"}, call_id="c1"),
                _text("done"),
            ]
        )

    def _run_turn(client, expect_prompts):
        with client.websocket_connect("/ws/session/grants1?agent=cowork") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "user_message", "text": "run it"})
            asked = 0
            while True:
                ev = ws.receive_json()
                if ev["type"] == "permission_required":
                    asked += 1
                    ws.send_json({"type": "approval", "decision": "always_command"})
                if ev["type"] == "turn_done":
                    break
            assert asked == expect_prompts

    mgr = SessionManager(workspace=None, provider=_shell_turns())
    _run_turn(TestClient(create_app(mgr)), expect_prompts=1)

    # "Restart": new manager + engine rebuilt from the persisted record.
    mgr2 = SessionManager(workspace=None, provider=_shell_turns())
    _run_turn(TestClient(create_app(mgr2)), expect_prompts=0)


def test_google_one_click_paused_but_manual_alive(tmp_path):
    """CASA verification pending: Gmail/Calendar/Drive expose managed_paused (GUI badges
    "Coming soon"), the managed-connect route refuses, and the manual fields stay."""
    client = _client(tmp_path, [])
    connectors = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}
    for name in ("gmail", "google_calendar", "google_drive"):
        c = connectors[name]
        assert c["managed"] is True and c["managed_paused"] is True
        assert c["fields"], f"{name} lost its manual fields"
    assert connectors["slack"]["managed_paused"] is False  # only Google is paused

    refused = client.post("/v1/connectors/gmail/connect-managed", json={}).json()
    assert refused["ok"] is False and "coming soon" in refused["error"]


def test_set_provider_persists_extra_fields(tmp_path):
    """Non-secret descriptor extras (ollama's endpoint) round-trip: saved into the
    profile, echoed by get_providers for form prefill, cleared by an empty save."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    assert manager.set_provider("ollama", {"base_url": "http://127.0.0.1:9999"})["ok"]
    providers = {p["name"]: p for p in manager.get_providers()}
    assert providers["ollama"]["values"]["base_url"] == "http://127.0.0.1:9999"

    manager.set_provider("ollama", {"base_url": ""})
    providers = {p["name"]: p for p in manager.get_providers()}
    assert "base_url" not in providers["ollama"]["values"]


def test_custom_provider_display_name_overrides_the_title(tmp_path):
    """The one custom-endpoint field that never reaches the wire: the person's own label
    for it, threaded through get_providers into the row the gallery/card header render."""
    client = _client(tmp_path, [])
    assert client.post(
        "/v1/providers",
        json={
            "name": "custom",
            "fields": {
                "display_name": "Acme Gateway",
                "api_key": "ak-test",
                "base_url": "https://acme.example/v1",
            },
        },
    ).json()["ok"]
    prov = {p["name"]: p for p in client.get("/v1/providers").json()}
    assert prov["custom"]["title"] == "Acme Gateway"
    assert prov["custom"]["configured"]

    assert client.delete("/v1/providers/custom").json()["ok"]
    prov = {p["name"]: p for p in client.get("/v1/providers").json()}
    assert prov["custom"]["title"] == "Custom endpoint"  # back to the descriptor default
    assert not prov["custom"]["configured"]


def test_verify_custom_route_requires_the_endpoint_name_too(tmp_path):
    """display_name never reaches the wire, so the read-only credential probe can't catch
    it missing on its own — Test must still refuse (not silently pass, then have the
    auto-save that follows it no-op on the same field while the GUI flashes green)."""
    client = _client(tmp_path, [])
    res = client.post(
        "/v1/providers/verify",
        json={
            "name": "custom",
            "fields": {"api_key": "ak-test", "base_url": "https://acme.example/v1"},
        },
    ).json()
    assert res["ok"] is False and "Endpoint name" in res["error"]


def test_verify_custom_route_requires_endpoint_first(tmp_path):
    """The Test button's guard (no vendor default to fall back to) survives the full
    manager.verify_provider merge — an api_key with no base_url anywhere (form or stored
    profile) must not fall through to a network probe. display_name is filled in so this
    isolates the base_url guard from the "missing: Endpoint name" check above."""
    client = _client(tmp_path, [])
    res = client.post(
        "/v1/providers/verify",
        json={
            "name": "custom",
            "fields": {"display_name": "Acme Gateway", "api_key": "ak-test"},
        },
    ).json()
    assert res == {"ok": False, "error": "Enter the endpoint URL first."}


def test_verify_custom_route_forwards_the_typed_base_url(tmp_path, monkeypatch):
    """The Test button sends the whole form, including the not-yet-saved endpoint field —
    the route must probe THAT address, not a stale saved one."""
    from types import SimpleNamespace

    captured: dict = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("httpx.get", fake_get)
    client = _client(tmp_path, [])
    res = client.post(
        "/v1/providers/verify",
        json={
            "name": "custom",
            "fields": {
                "display_name": "Acme Gateway",
                "api_key": "ak-test",
                "base_url": "https://acme.example/v1",
            },
        },
    ).json()
    assert res == {"ok": True}
    assert captured["url"] == "https://acme.example/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer ak-test"


def test_mcp_connect_route_flags_authorizing_immediately(tmp_path, monkeypatch):
    """Owner-hit 2026-08-21: the Test button looked dead — the connect ran as a
    background task, and the GUI's first refresh landed before the task set
    `authorizing`, so the fast poll never armed. The route must flag it
    synchronously (and only for known servers, so nothing wedges)."""
    import asyncio

    from coworker.server import SessionManager

    mgr = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr(
        "coworker.server.manager.read_global", lambda: {"sales-db": {"command": "x"}}
    )
    mgr.begin_mcp_connect("sales-db")
    assert "sales-db" in mgr._mcp_authorizing
    mgr.begin_mcp_connect("nope")
    assert "nope" not in mgr._mcp_authorizing
    # An unmatched name clears the flag instead of wedging "Testing…" forever.
    monkeypatch.setattr("coworker.server.manager.load_mcp_servers", lambda *a, **k: [])
    res = asyncio.run(mgr.connect_mcp("sales-db"))
    assert not res["ok"] and "sales-db" not in mgr._mcp_authorizing


# -- live model-catalog refresh route --------------------------------------------


def test_providers_models_refresh_route(tmp_path, monkeypatch):
    """Settings ▸ Models' "Refresh" button: a stubbed successful pull round-trips through
    the route into the manager's cache-status shape."""
    monkeypatch.setattr(
        SessionManager,
        "_fetch_model_catalog",
        lambda self, name, fields=None: {
            "ok": True,
            "models": [
                {"id": "glm-5.2", "label": "GLM-5.2 · Z AI", "context_window": 128000}
            ],
        },
    )
    client = _client(tmp_path, [])
    # refresh_model_catalog refuses an unconfigured provider with no fields of its own
    # (nothing to fetch with) — configure the key first, same as a real Settings flow.
    assert client.post(
        "/v1/providers", json={"name": "zai", "fields": {"api_key": "zk"}}
    ).json()["ok"]
    res = client.post("/v1/providers/zai/models/refresh").json()
    assert res["ok"] is True and res["provider"] == "zai"
    assert res["catalog"]["live"] is True and res["catalog"]["count"] == 1
    assert "glm-5.2" in res["suggested_models"]


def test_providers_models_refresh_route_unknown_provider(tmp_path):
    client = _client(tmp_path, [])
    res = client.post("/v1/providers/nope/models/refresh").json()
    assert res == {"ok": False, "error": "unknown provider: nope"}


def test_providers_models_refresh_route_unsupported_provider(tmp_path):
    """Ark has no model-list API (its Test button uses a one-token Responses probe
    instead) — the refresh route must say so rather than pretending a pull happened."""
    client = _client(tmp_path, [])
    res = client.post("/v1/providers/ark/models/refresh").json()
    assert res["ok"] is False and res["unsupported"] is True


def test_relay_callback_success_kicks_the_gemini_catalog(tmp_path, monkeypatch):
    """Signing in to the company relay is what makes it answer `/v1beta/models`, so a
    completed sign-in pulls Gemini's catalog right away — a "not signed in" failure
    recorded minutes earlier must not sit out its retry window while Settings shows the
    built-in list. A failed exchange kicks nothing."""
    from coworker import relay_auth

    kicked: list[str] = []
    monkeypatch.setattr(
        SessionManager, "kick_catalog_refresh", lambda self, name: kicked.append(name)
    )
    monkeypatch.setattr(
        relay_auth,
        "deliver_callback",
        lambda secrets, code, state: {"ok": True, "email": "a@x.test", "name": "A"},
    )
    client = _client(tmp_path, [])
    res = client.get("/relay/callback", params={"code": "c", "state": "s"})
    assert res.status_code == 200 and kicked == ["gemini"]

    monkeypatch.setattr(
        relay_auth, "deliver_callback", lambda secrets, code, state: {"ok": False, "error": "x"}
    )
    kicked.clear()
    res = client.get("/relay/callback", params={"code": "c", "state": "s"})
    assert res.status_code == 400 and kicked == []


def test_ws_ready_reports_live_turn(tmp_path):
    # A reconnect can land mid-turn (sidebar revisit, relaunch, dropped socket). `ready`
    # must carry server truth on the running turn or the GUI loses Stop + the waiting row
    # (owner catch 2026-08-24, v0.2.0 walkthrough).
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/live1") as ws:
        assert ws.receive_json()["data"]["running"] is False

    manager.mark_running("live1")
    try:
        with client.websocket_connect("/ws/session/live1") as ws:
            assert ws.receive_json()["data"]["running"] is True
    finally:
        manager.mark_idle("live1")


def test_set_mode_persists_notice_once_then_markers(tmp_path):
    # Owner ruling 2026-08-24: the Auto-Approve explainer is server-authored and persisted
    # ONCE per session; later switches persist one-line markers. Restarts re-show nothing.
    # Owner ask 2026-09-02: on a DRAFT the banner still shows, but nothing reaches Recents
    # and the one-line markers only start once the conversation has (a user turn).
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/modes1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "set_mode", "mode": "auto-approve"})
        ev = ws.receive_json()
        assert ev["type"] == "mode_notice"
        assert ev["data"]["title"] == "Auto-approve is on."
        assert "uses a model" in ev["data"]["text"]
        # …followed by the chip-only echo every accepted change now carries (C3).
        assert ws.receive_json() == {
            "type": "mode_changed",
            "data": {"mode": "auto-approve"},
        }
        assert manager.session_store.load("modes1") is None  # a draft gets no row
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_done" in _drain(ws)
        ws.send_json({"type": "set_mode", "mode": "interactive"})
        assert ws.receive_json()["data"] == {"text": "Ask for approval is on."}
        assert ws.receive_json()["data"] == {"mode": "interactive"}
        # Re-entering auto-approve: marker, never the banner again.
        ws.send_json({"type": "set_mode", "mode": "auto-approve"})
        assert ws.receive_json()["data"] == {"text": "Auto-approve is on."}
        assert ws.receive_json()["data"] == {"mode": "auto-approve"}

    engine = manager._engines["modes1"]
    kinds = [m.get("kind") for m in engine.messages if m.get("role") == "notice"]
    assert kinds.count("mode_notice") == 1
    assert kinds.count("mode_switch") == 2


def test_connect_banners_a_session_already_in_auto_approve(tmp_path):
    from coworker.permissions import Mode

    manager = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider([_text("hi")]),
        mode=Mode("auto-approve"),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/modes2") as ws:
        assert ws.receive_json()["type"] == "ready"
        ev = ws.receive_json()
        assert ev["type"] == "mode_notice" and ev["data"]["title"] == "Auto-approve is on."
    # The banner alone is a setting, not activity: a never-used session stays out of
    # Recents (owner ask 2026-09-02) — the notice lives in the session's engine.
    assert manager.session_store.load("modes2") is None
    # A reconnect stays quiet: the banner is already in the transcript, not re-announced —
    # a set_mode echo of the SAME mode also stays silent (previous is new_mode). The
    # one-line marker needs a real turn first: on a draft the mode is just a setting.
    with client.websocket_connect("/ws/session/modes2") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_done" in _drain(ws)
        ws.send_json({"type": "set_mode", "mode": "interactive"})
        assert ws.receive_json()["data"] == {"text": "Ask for approval is on."}
    engine = manager._engines["modes2"]
    kinds = [m.get("kind") for m in engine.messages if m.get("role") == "notice"]
    assert kinds.count("mode_notice") == 1


def test_set_mode_on_a_draft_is_a_setting_not_history(tmp_path):
    # Owner ask 2026-09-02: a new session is ONE draft. Choosing a mode on it is a setting,
    # not history — no transcript marker, no Recents row; the first real turn writes the
    # single row that session ever gets, already carrying the chosen mode.
    from coworker.permissions import Mode

    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/draft1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "set_mode", "mode": "discuss"})
        # Chip-only echo (contract C3, audit 2026-09-13): the draft gets no mode_notice,
        # so this is the only frame that tells the client its pick landed.
        echo = ws.receive_json()
        assert echo["type"] == "mode_changed"
        assert echo["data"] == {"mode": "discuss"}
        ws.send_json({"type": "user_message", "text": "hello"})
        # The next frame is the turn itself — no mode_notice was ever broadcast.
        first = ws.receive_json()
        assert first["type"] == "turn_start"
        while ws.receive_json()["type"] != "turn_done":
            pass

    engine = manager._engines["draft1"]
    assert engine.permissions.mode is Mode.DISCUSS
    record = manager.session_store.load("draft1")
    assert record is not None and record.mode == "discuss"
    assert not any(m.get("kind") == "mode_switch" for m in engine.messages)
    assert [s["session_id"] for s in manager.list_sessions()].count("draft1") == 1


def test_draft_reconnect_retargets_the_same_session_id(tmp_path):
    # Owner ask 2026-09-02: picking another coworker/folder on a never-used session
    # re-targets THAT session instead of minting a new id — so the typed draft, the model
    # and the mode survive the pick.
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    manager = SessionManager(
        workspace=None, data_dir=tmp_path, provider=ScriptedProvider([_text("hi")])
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/d1?agent=cowork") as ws:
        assert ws.receive_json()["data"]["agent"] == "cowork"
        ws.send_json({"type": "set_model", "model": "other-model"})
        ws.send_json({"type": "set_mode", "mode": "discuss"})
    assert manager._engines["d1"].model == "other-model"  # both frames landed

    with client.websocket_connect(
        f"/ws/session/d1?agent=code&workspace={quote(str(proj))}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["data"]["agent"] == "code"
        assert ready["data"]["model"] == "other-model"
        assert ready["data"]["mode"] == "discuss"
        assert ready["data"]["workspace"] == str(proj.resolve())
    assert manager.session_store.load("d1") is None  # still a draft: no Recents row
    rebuilt = manager._engines["d1"]
    assert rebuilt.agent_name == "code"

    # Same target again: nothing differs, so the engine is reused, not rebuilt.
    with client.websocket_connect(
        f"/ws/session/d1?agent=code&workspace={quote(str(proj))}"
    ) as ws:
        assert ws.receive_json()["type"] == "ready"
    assert manager._engines["d1"] is rebuilt


def test_started_session_reconnect_keeps_its_record(tmp_path):
    # The re-target is for DRAFTS only: once a session has a user turn its record wins,
    # exactly as before — a stale query string can never repoint a real conversation.
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    manager = SessionManager(
        workspace=None, data_dir=tmp_path, provider=ScriptedProvider([_text("hi")])
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/d2?agent=cowork") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_done" in _drain(ws)
    started = manager._engines["d2"]

    with client.websocket_connect(
        f"/ws/session/d2?agent=code&workspace={quote(str(proj))}"
    ) as ws:
        assert ws.receive_json()["data"]["agent"] == "cowork"
    assert manager._engines["d2"] is started


def test_draft_retarget_keeps_shared_folder_and_early_record(tmp_path):
    # A shared folder writes a row before the first turn. Re-targeting the draft updates
    # THAT row in place (one session, one row) and carries the shared folder across.
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    manager = SessionManager(
        workspace=None, data_dir=tmp_path, provider=ScriptedProvider([_text("hi")])
    )
    client = TestClient(create_app(manager))
    assert client.post(
        "/v1/sessions/d3/roots", json={"path": str(shared), "writable": True}
    ).json()["ok"]
    assert manager.session_store.load("d3") is not None
    with client.websocket_connect("/ws/session/d3?agent=cowork") as ws:
        assert ws.receive_json()["data"]["agent"] == "cowork"

    with client.websocket_connect(
        f"/ws/session/d3?agent=code&workspace={quote(str(proj))}"
    ) as ws:
        assert ws.receive_json()["data"]["agent"] == "code"
    assert str(shared.resolve()) in [r["path"] for r in manager.get_roots("d3")]
    record = manager.session_store.load("d3")
    assert record is not None and record.agent == "code"
    assert [s["session_id"] for s in manager.list_sessions()].count("d3") == 1


def test_draft_retarget_rewrites_the_persisted_transcript(tmp_path):
    # The store appends BY COUNT, and a re-target swaps one system prompt for another —
    # same count. Without an explicit truncate the row said "code" while the stored
    # transcript still opened with the COWORK prompt, so every restart rebuilt the
    # session with the wrong persona's instructions (and the old folder's env block).
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    manager = SessionManager(
        workspace=None, data_dir=tmp_path, provider=ScriptedProvider([_text("hi")])
    )
    client = TestClient(create_app(manager))
    assert client.post(
        "/v1/sessions/d4/roots", json={"path": str(shared), "writable": True}
    ).json()["ok"]
    with client.websocket_connect("/ws/session/d4?agent=cowork") as ws:
        assert ws.receive_json()["data"]["agent"] == "cowork"
        # A mode pick on a draft that already HAS a record persists its bookkeeping —
        # the stored log now holds the cowork prompt at exactly the count a re-target
        # would leave it at.
        ws.send_json({"type": "set_mode", "mode": "auto-approve"})
        assert ws.receive_json()["type"] == "mode_notice"
    assert manager.session_store.load("d4").messages  # the draft's log is on disk

    with client.websocket_connect(
        f"/ws/session/d4?agent=code&workspace={quote(str(proj))}"
    ) as ws:
        assert ws.receive_json()["data"]["agent"] == "code"
    record, engine = manager.session_store.load("d4"), manager._engines["d4"]
    assert record is not None and record.agent == "code"
    assert len(record.messages) == len(engine.messages)
    assert record.messages[0].get("role") == "system"
    # What a restart would rebuild from IS what the re-targeted session is running.
    assert record.messages[0]["content"] == engine.messages[0]["content"]


def test_draft_with_only_a_record_still_honours_the_reconnect_picks(tmp_path):
    # The pick must win with NO cached engine too: sharing a folder before the first
    # connect writes a record (and a restart drops every engine), and get_engine's record
    # branch would otherwise hard-override the setup row's coworker and folder.
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    manager = SessionManager(
        workspace=None, data_dir=tmp_path, provider=ScriptedProvider([_text("hi")])
    )
    client = TestClient(create_app(manager))
    assert client.post(
        "/v1/sessions/d5/roots", json={"path": str(shared), "writable": True}
    ).json()["ok"]
    assert manager.session_store.load("d5").agent == "cowork"
    assert "d5" not in manager._engines  # nothing was ever built for this id

    with client.websocket_connect(
        f"/ws/session/d5?agent=code&workspace={quote(str(proj))}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["data"]["agent"] == "code"
        assert ready["data"]["workspace"] == str(proj.resolve())
    assert manager._engines["d5"].agent_name == "code"
    assert str(shared.resolve()) in [r["path"] for r in manager.get_roots("d5")]
    assert manager.session_store.load("d5").agent == "code"


def test_a_failed_rebuild_keeps_the_draft_picks(tmp_path):
    # The carry is the user's model/mode picks. A re-target whose rebuild BAILS — a
    # folder-gated coworker pointed at a folder that has since vanished — must not cost
    # them: the picks survive for the next connect that does succeed.
    manager = SessionManager(
        workspace=None, data_dir=tmp_path, provider=ScriptedProvider([_text("hi")])
    )
    engine = manager.get_engine("q1", agent="cowork")
    assert engine is not None
    engine.switch_model("picked-model")

    gone = str(tmp_path / "gone")
    assert manager.retarget_draft("q1", workspace=gone, agent="code") is True
    assert manager.get_engine("q1", workspace=gone, agent="code") is None
    assert "q1" not in manager._engines  # the old engine is gone, as intended

    recovered = manager.get_engine("q1", agent="cowork")
    assert recovered is not None and recovered.model == "picked-model"


def test_set_model_on_a_draft_is_a_setting_not_history(tmp_path):
    # The model half of the same rule (owner ask 2026-09-02). switch_model used to speak as
    # soon as the transcript held ANY non-system message, so a draft carrying only the
    # Auto-approve banner earned a "Model switched" marker AND a Recents row stamped now —
    # which boot then resumed. Notices are bookkeeping: the pick is still the first bind.
    from coworker.permissions import Mode

    manager = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider([_text("hi")]),
        mode=Mode("auto-approve"),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/dm1") as ws:
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive_json()["type"] == "mode_notice"  # the banner is a notice, not history
        ws.send_json({"type": "set_model", "model": "other-model"})
        # The echo is CHIP-ONLY — no `text`, so no transcript marker (contract C3, audit
        # 2026-09-13). Without it the client's "ready" handler reverted the pick and
        # nothing ever corrected it; the draft still earns no marker and no row.
        echo = ws.receive_json()
        assert echo["type"] == "model_changed"
        assert echo["data"] == {"model": "other-model"}
        ws.send_json({"type": "user_message", "text": "hello"})
        assert ws.receive_json()["type"] == "turn_start"
        _drain(ws)
    engine = manager._engines["dm1"]
    assert engine.model == "other-model"
    kinds = [m.get("kind") for m in engine.messages if m.get("role") == "notice"]
    assert "model_switch" not in kinds
    record = manager.session_store.load("dm1")
    assert record is not None and record.model == "other-model"  # persisted by the turn
    assert [s["session_id"] for s in manager.list_sessions()].count("dm1") == 1


def test_persona_default_pointer_round_trip(tmp_path):
    """C2 — POST /v1/personas/{id} with `default`: true sets, false CLEARS (back to the
    baseline, the pointer's zero value), and only when this persona actually holds the
    pointer; absent/null leaves it alone."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))
    reg = manager.personas

    def default_of(body):
        return next(p["id"] for p in body["personas"] if p["default"])

    body = client.post("/v1/personas/code", json={"default": True}).json()
    assert body["ok"] is True and default_of(body) == "code"
    # Making it the default enabled AND surfaced it — a default the picker never offers
    # is incoherent (Code ships unsurfaced).
    assert reg.is_enabled("code") and reg.is_surfaced("code")
    assert "code" in [a["name"] for a in client.get("/v1/agents").json()["agents"]]

    # A stale client sending default:false for a persona that is NOT the default must
    # never move anyone else's pointer.
    body = client.post("/v1/personas/ops", json={"default": False}).json()
    assert body["ok"] is True and default_of(body) == "code"
    # Same for null / absent.
    assert default_of(client.post("/v1/personas/code", json={"default": None}).json()) == "code"
    assert default_of(client.post("/v1/personas/code", json={"surfaced": True}).json()) == "code"

    # Clearing the real default returns to the baseline.
    body = client.post("/v1/personas/code", json={"default": False}).json()
    assert body["ok"] is True and default_of(body) == "cowork"
    assert reg.is_enabled("cowork") and reg.is_surfaced("cowork")
    # Clearing is not a disable: Code keeps running.
    assert reg.is_enabled("code") is True


def test_persona_clear_default_and_disable_in_one_body(tmp_path):
    """The settings UI sends whole rows, so "stop being the default AND switch off"
    arrives as one body. The default branch runs FIRST (audit 2026-09-13) — handled the
    other way round the disable is refused for being the default and the user has to
    click twice to express one intention."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))
    reg = manager.personas

    client.post("/v1/personas/ops", json={"default": True})
    assert reg.default_id() == "ops"

    body = client.post(
        "/v1/personas/ops", json={"enabled": False, "default": False}
    ).json()
    assert body["ok"] is True
    assert reg.default_id() == "cowork"
    assert reg.is_enabled("ops") is False


def test_persona_baseline_self_heals_end_to_end(tmp_path):
    """The whole invariant chain through REST: an expert holds the default, the baseline
    still refuses to be disabled, clearing the default brings the pointer home, and the
    baseline is STILL not disableable afterwards."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))
    reg = manager.personas

    client.post("/v1/personas/ops", json={"default": True})
    assert reg.default_id() == "ops"
    body = client.post("/v1/personas/cowork", json={"enabled": False}).json()
    assert body["ok"] is False and "always available" in body["error"]

    body = client.post("/v1/personas/ops", json={"default": False}).json()
    assert body["ok"] is True and reg.default_id() == "cowork"
    assert reg.is_enabled("cowork") is True

    body = client.post("/v1/personas/cowork", json={"enabled": False}).json()
    assert body["ok"] is False and "always available" in body["error"]
    assert reg.is_enabled("cowork") is True


def test_the_default_cannot_be_unsurfaced_over_rest(tmp_path):
    """A default the picker never offers is the same incoherent state set_default exists to
    prevent, reached from the other side. The baseline stays exempt (audit 2026-09-13)."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))
    reg = manager.personas

    client.post("/v1/personas/ops", json={"default": True})
    body = client.post("/v1/personas/ops", json={"surfaced": False}).json()
    assert body["ok"] is False
    assert body["code"] == "default_locked"  # what the GUI translates on
    assert "clear the default" in body["error"]  # …and the English fallback
    assert reg.is_surfaced("ops") is True

    # Hiding the general coworker is still the supported way to de-clutter the menu.
    assert client.post("/v1/personas/cowork", json={"surfaced": False}).json()["ok"]
    assert reg.is_surfaced("cowork") is False


def test_a_refusal_carries_a_stable_code_for_the_localized_ui(tmp_path):
    """The GUI shows a refused toggle's reason inline, and the owner's UI is Chinese —
    raw English prose is not translatable, so both refusals carry a machine code."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))

    body = client.post("/v1/personas/cowork", json={"enabled": False}).json()
    assert body["code"] == "baseline_locked"
    assert client.post("/v1/personas/ops", json={"default": True}).json()["ok"]
    body = client.post("/v1/personas/ops", json={"enabled": False}).json()
    assert body["code"] == "default_locked"
    # The dedicated enable route says the same thing (PersonaView's toggle uses it).
    body = client.post("/v1/personas/cowork/enable", json={"enabled": False}).json()
    assert body["code"] == "baseline_locked"
    body = client.post("/v1/personas/nope/enable", json={"enabled": False}).json()
    assert body["code"] == "unknown_persona"


# -- B1: connect off the loop, under a per-session lock; every applied setting echoes ----


def test_connect_flushes_a_queued_set_model_and_echoes_it(tmp_path):
    """Contract C3 (audit 2026-09-13). api.ts flushes queued frames the instant the socket
    opens and the server reads them only AFTER sending "ready", so the client's "ready"
    handler used to revert the user's pick. On a DRAFT the switch writes no transcript
    marker, so the only thing that can correct the client is a chip-only echo:
    model_changed WITHOUT `text`. Still a setting, not history — no marker, no row."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/flush1") as ws:
        # Sent before "ready" is even read — exactly what the client's outbox flush does.
        ws.send_json({"type": "set_model", "model": "picked-at-open"})
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive_json() == {
            "type": "model_changed",
            "data": {"model": "picked-at-open"},
        }
    engine = manager._engines["flush1"]
    assert engine.model == "picked-at-open"
    assert engine.model_pinned is True
    assert not any(m.get("kind") == "model_switch" for m in engine.messages)
    assert manager.session_store.load("flush1") is None  # a draft still earns no row
    assert [s["session_id"] for s in manager.list_sessions()].count("flush1") == 0


def test_redundant_set_model_broadcasts_nothing(tmp_path):
    """A pick the engine is already on is the NORMAL frame on a reconnect (the client
    re-sends outstanding picks on every open, contract C6). It must stay silent."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/same1") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        ws.send_json({"type": "set_model", "model": ready["data"]["model"]})
        ws.send_json({"type": "user_message", "text": "hello"})
        # No model_changed slipped in front of the turn.
        assert ws.receive_json()["type"] == "turn_start"
        # turn_start proves the redundant frame was consumed — and silent or not, it was
        # still a PICK: _apply_model pins BEFORE the early return, or the next Settings
        # default-model change would re-point a draft the user explicitly chose a model
        # for (set_default_model skips pinned engines; _draft_carry carries the pin).
        assert manager._engines["same1"].model_pinned is True
        _drain(ws)


def test_set_mode_echoes_the_canonical_value_on_a_draft_and_with_history(tmp_path):
    """Contract C3 + C4. mode_notice is the TRANSCRIPT channel and a draft deliberately
    has none, so mode_changed is the draft's only acknowledgement; it carries the server's
    CANONICAL Mode value, so a client that sent the legacy "auto" gets "bypass-approvals"
    back. A session with history keeps its mode_notice and gains the chip echo after it."""
    manager = SessionManager(
        workspace=tmp_path, provider=ScriptedProvider([_text("hi"), _text("ok")])
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/mc1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "set_mode", "mode": "auto"})  # legacy alias on the wire
        assert ws.receive_json() == {
            "type": "mode_changed",
            "data": {"mode": "bypass-approvals"},
        }
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_done" in _drain(ws)
        # Now the session HAS history: the transcript marker is back, echo follows it.
        ws.send_json({"type": "set_mode", "mode": "plan"})
        notice = ws.receive_json()
        assert notice["type"] == "mode_notice" and notice["data"]["text"]
        assert ws.receive_json() == {"type": "mode_changed", "data": {"mode": "plan"}}
    engine = manager._engines["mc1"]
    # The draft's pick left no marker; only the post-history one did.
    assert [
        m.get("kind") for m in engine.messages if m.get("role") == "notice"
    ].count("mode_switch") == 1


def test_engine_build_runs_off_the_event_loop(tmp_path):
    """The build is 100-250 ms of prompt assembly and up to ~20 s when a git spawn stalls
    (environment.py runs four commands at timeout=5). On the loop it froze every OTHER
    session, every REST call and the model-catalog poll for that whole window — the
    owner's "several seconds" report (audit 2026-09-13). Two proofs: get_engine sees no
    running loop in its thread, and a REST call lands while a slow build is in flight."""
    import asyncio as _asyncio
    import threading
    import time as _time

    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    real = manager.get_engine
    seen: dict[str, object] = {}
    building = threading.Event()
    build_done = threading.Event()

    def probe(*args, **kwargs):
        try:
            _asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        building.set()
        _time.sleep(0.5)
        build_done.set()
        return real(*args, **kwargs)

    manager.get_engine = probe
    # ONE portal (one event loop) for the socket and the REST call — outside this context
    # TestClient spins a fresh portal per connection and the race being tested cannot happen.
    with TestClient(create_app(manager)) as client:
        with client.websocket_connect("/ws/session/offloop") as ws:
            assert building.wait(5), "the connect never reached get_engine"
            assert client.get("/v1/health").status_code == 200
            # Causal, not a wall-clock budget: the REST call came back BEFORE the slow build
            # finished. A threshold cuts both ways — a broken (on-loop) build measures ~0.5 s
            # against a 0.4 s bar, so a 150 ms scheduling hiccup on the test thread would let
            # the very regression this pins slip through green.
            assert not build_done.is_set(), "/v1/health only returned after the build finished"
            assert ws.receive_json()["type"] == "ready"
    assert seen["on_loop"] is False


def test_two_rapid_connects_for_one_draft_never_interleave(tmp_path):
    """The connect sequence (retarget_draft → prepare_mcp_tools → get_engine) is NOT
    re-entrant: retarget drops the cached engine, so an interleaved pair builds twice and
    leaves the loser's engine cached. The GUI produces exactly this — a coworker pick bumps
    connectNonce, so the new socket opens while the old build is still running."""
    import threading
    import time as _time

    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    real = manager.get_engine
    guard = threading.Lock()
    state = {"inside": 0, "calls": 0, "overlapped": False}

    def probe(*args, **kwargs):
        with guard:
            state["calls"] += 1
            state["inside"] += 1
            if state["inside"] > 1:
                state["overlapped"] = True
        _time.sleep(0.2)  # wide enough for a second connect to interleave if unlocked
        try:
            return real(*args, **kwargs)
        finally:
            with guard:
                state["inside"] -= 1

    manager.get_engine = probe
    with TestClient(create_app(manager)) as client:
        with client.websocket_connect("/ws/session/dup?agent=cowork") as first:
            with client.websocket_connect("/ws/session/dup?agent=code") as second:
                assert first.receive_json()["type"] == "ready"
                assert second.receive_json()["type"] == "ready"
    assert state["calls"] == 2  # the re-target really did force a second build
    assert state["overlapped"] is False


def test_one_build_per_session_across_concurrent_async_callers(tmp_path, monkeypatch):
    """The WS connect is not the only builder: a durable Inbox resume and an out-of-band
    delivery (self-wake, channel, DM) build too, and they used to be safe only because
    every caller ran synchronously on the loop. Now the build goes to a worker thread, so
    the lock has to cover all of them or two live engines hold divergent message lists for
    one id and ConversationStore — which appends BY COUNT — splices one into the other
    (audit 2026-09-13)."""
    import asyncio as _asyncio
    import time as _time

    from coworker.server import manager as manager_mod

    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    real_build = manager_mod.build_engine
    calls = {"n": 0}

    def slow_build(*args, **kwargs):
        calls["n"] += 1
        _time.sleep(0.3)  # wide enough for a rival caller to slip in if unserialised
        return real_build(*args, **kwargs)

    monkeypatch.setattr(manager_mod, "build_engine", slow_build)

    async def drive():
        return await _asyncio.gather(
            manager.ensure_engine("race", workspace=str(tmp_path)),
            manager.ensure_engine("race", workspace=str(tmp_path)),
        )

    first, second = _asyncio.run(drive())
    assert calls["n"] == 1, "the session was built twice"
    assert first is second is manager._engines["race"]


def test_a_build_that_loses_the_cache_race_adopts_the_live_engine(tmp_path, monkeypatch):
    """Belt-and-braces behind the lock: the final cache write must never OVERWRITE an
    engine that appeared mid-build. The incumbent may already have a turn appended, so it
    wins and this build is discarded — with this caller's callbacks rebound onto it."""
    from coworker.server import manager as manager_mod

    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([_text("hi")]))
    rival = manager.get_engine("adopt", workspace=str(tmp_path))
    assert rival is not None
    manager._engines.pop("adopt")

    real_build = manager_mod.build_engine

    def plant(*args, **kwargs):
        engine = real_build(*args, **kwargs)
        manager._engines["adopt"] = rival  # a rival caller landed while we were building
        return engine

    monkeypatch.setattr(manager_mod, "build_engine", plant)

    def approver(*_a, **_k):
        return None

    got = manager.get_engine("adopt", workspace=str(tmp_path), approver=approver)
    assert got is rival
    assert manager._engines["adopt"] is rival  # the loser did not clobber the cache
    assert rival.approver is approver  # …and this connect's callbacks reached it
