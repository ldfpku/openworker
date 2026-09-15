"""UX-029 — temporary workspaces for code-family sessions.

"Start in a temporary folder": the dir is created at SEND time via POST /v1/workspaces/temp
(git-init'd for code work), flagged in the `ready` event as `temp_workspace`, and can later be
moved to a real location via "Save as project…" (POST /v1/sessions/{id}/save-as-project).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from coworker.providers import ModelCapabilities, ProviderClient
from coworker.server import create_app
from coworker.server.manager import SessionManager
from coworker.sessions import SessionRecord


class ScriptedProvider(ProviderClient):
    def __init__(self, turns=None):
        self._turns = list(turns or [])

    def complete(self, *, model, messages, tools=None, **settings):
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def _mgr(tmp_path, monkeypatch) -> SessionManager:
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")
    return mgr


def test_provision_temp_workspace_creates_dir_with_git(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    client = TestClient(create_app(mgr))

    res = client.post("/v1/workspaces/temp", json={"session_id": "abc123", "git": True}).json()
    assert res["ok"] is True
    d = Path(res["path"])
    assert d.is_dir()
    assert d.parent == (tmp_path / "scratch").resolve()
    assert res["git"] is True and (d / ".git").is_dir()

    # Idempotent — a re-send against the existing dir is a no-op.
    again = client.post("/v1/workspaces/temp", json={"session_id": "abc123"}).json()
    assert again["ok"] is True and again["path"] == res["path"]

    # It IS a temp workspace, and never appears in the recents (project) list.
    assert mgr.is_temp_workspace(res["path"]) is True
    mgr.session_store.touch_workspace(res["path"])
    assert res["path"] not in [w["path"] for w in mgr.recent_workspaces()]


def test_provision_temp_workspace_rejects_bad_ids(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    client = TestClient(create_app(mgr))
    for bad in ["", "../evil", "a/b", ".."]:
        assert client.post("/v1/workspaces/temp", json={"session_id": bad}).json()["ok"] is False


def test_save_temp_as_project_moves_and_rebinds(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    client = TestClient(create_app(mgr))

    src = Path(client.post("/v1/workspaces/temp", json={"session_id": "sess1"}).json()["path"])
    (src / "notes.txt").write_text("hello", encoding="utf-8")
    mgr.session_store.save(
        SessionRecord(
            session_id="sess1",
            workspace=str(src),
            model="m",
            mode="interactive",
            messages=[{"role": "user", "content": "hi"}],
            agent="code",
        )
    )

    dest = tmp_path / "projects" / "myproj"
    res = client.post("/v1/sessions/sess1/save-as-project", json={"path": str(dest)}).json()
    assert res["ok"] is True
    moved = Path(res["path"])
    assert moved == dest.resolve()
    assert (moved / "notes.txt").read_text(encoding="utf-8") == "hello"
    assert not src.exists()
    assert mgr.session_store.load("sess1").workspace == str(moved)
    assert mgr.is_temp_workspace(str(moved)) is False


def test_save_temp_as_project_guards(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    client = TestClient(create_app(mgr))

    # Not a temp workspace → refused.
    real = tmp_path / "realproj"
    real.mkdir()
    mgr.session_store.save(
        SessionRecord(session_id="s2", workspace=str(real), model="m", mode="interactive", agent="code")
    )
    res = client.post("/v1/sessions/s2/save-as-project", json={"path": str(tmp_path / "x")}).json()
    assert res["ok"] is False

    # Non-empty destination → refused, source untouched.
    src = Path(client.post("/v1/workspaces/temp", json={"session_id": "s3"}).json()["path"])
    mgr.session_store.save(
        SessionRecord(session_id="s3", workspace=str(src), model="m", mode="interactive", agent="code")
    )
    full = tmp_path / "full"
    full.mkdir()
    (full / "occupied.txt").write_text("x", encoding="utf-8")
    res = client.post("/v1/sessions/s3/save-as-project", json={"path": str(full)}).json()
    assert res["ok"] is False and src.is_dir()


# -- Item 6: scratch base created eagerly, not lazily on first session ----------


def test_scratch_base_default_resolves_and_created_at_startup(tmp_path, monkeypatch):
    """No prefs, no env override: the default (~/OpenWorker) is created immediately at
    construction (not lazily on first session), and construction is idempotent — a second
    manager over the same env doesn't fail or duplicate anything."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    # The conftest autouse fixture points every test at an isolated scratch dir so tests
    # never touch the real ~/OpenWorker — this test is specifically about the *default*
    # resolution path, so it must undo that override.
    monkeypatch.delenv("COWORKER_SCRATCH_BASE", raising=False)

    mgr = SessionManager(data_dir=tmp_path / "data")
    expected = home / "OpenWorker"
    assert expected.is_dir()  # created at construction, before any session exists
    settings = mgr.get_settings()
    assert settings["scratch_base"] == "~/OpenWorker"
    assert Path(settings["scratch_base_effective"]) == expected.resolve()
    assert settings["scratch_base_error"] is None

    # Idempotent: a second manager over the same (already-provisioned) default doesn't
    # error or complain either.
    mgr2 = SessionManager(data_dir=tmp_path / "data2")
    assert expected.is_dir()
    assert mgr2.get_settings()["scratch_base_error"] is None


def test_scratch_base_chinese_path_roundtrips(tmp_path, monkeypatch):
    """Windows path handling (item 6 step 7): a non-ASCII scratch-base setting is created,
    persisted, and provisions session dirs under it exactly like any other path."""
    mgr = _mgr(tmp_path, monkeypatch)
    client = TestClient(create_app(mgr))

    base = tmp_path / "我的协作文件"
    resp = client.post("/v1/settings/scratch-base", json={"path": str(base)}).json()
    assert resp["ok"] is True and base.is_dir()

    scratch = mgr._provision_scratch("会话一")
    assert Path(scratch) == (base / "会话一").resolve() and Path(scratch).is_dir()
