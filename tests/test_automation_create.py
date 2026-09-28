"""Tests for the GUI-driven `create_automation` path (the "New automation" / template flow).

No network and no LLM: this exercises validation + that a valid create lands in the task store
with a freshly provisioned scratch workspace.
"""

from __future__ import annotations

from pathlib import Path

from coworker.server.manager import SessionManager


def _manager(tmp_path, monkeypatch) -> SessionManager:
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    return SessionManager(data_dir=tmp_path / "data")


def test_create_automation_success(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    out = manager.create_automation(
        {
            "title": "Morning news briefing",
            "instructions": "Search the web and write a 5-bullet briefing.",
            "cron": "0 8 * * *",
        }
    )
    assert out["ok"] is True
    task = out["task"]
    assert task["title"] == "Morning news briefing"
    assert task["schedule"] == "每天 ~08:00"
    # it really landed in the store and is bound to a fresh scratch workspace
    saved = manager.task_store.get(task["id"])
    assert saved is not None
    assert saved.agent == "cowork"
    assert Path(saved.workspace).is_dir()


def test_create_automation_invalid_cron(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    out = manager.create_automation(
        {
            "title": "Bad",
            "instructions": "do something",
            "cron": "not-a-cron",
        }
    )
    assert out["ok"] is False
    assert "invalid cron" in out["error"]
    assert manager.task_store.list() == []


def test_create_automation_missing_instructions(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    out = manager.create_automation(
        {
            "title": "No instructions",
            "instructions": "  ",
            "cron": "0 8 * * *",
        }
    )
    assert out["ok"] is False
    assert "instructions" in out["error"]
    assert manager.task_store.list() == []


def test_create_automation_requires_schedule(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    out = manager.create_automation(
        {"title": "No schedule", "instructions": "do something"}
    )
    assert out["ok"] is False
    assert manager.task_store.list() == []


# -- workspace: a real folder instead of the private scratch dir -----------------
def test_create_automation_omitted_workspace_is_private(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    out = manager.create_automation(
        {
            "title": "Morning news briefing",
            "instructions": "brief me",
            "cron": "0 8 * * *",
        }
    )
    assert out["ok"] is True
    assert out["task"]["workspace_private"] is True
    saved = manager.task_store.get(out["task"]["id"])
    assert manager.is_temp_workspace(saved.workspace)


def test_create_automation_with_workspace_stores_resolved_and_recent(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    ledger = tmp_path / "ledger folder"
    ledger.mkdir()
    out = manager.create_automation(
        {
            "title": "Check the ledger",
            "instructions": "look at the ledger",
            "cron": "0 8 * * *",
            "workspace": str(ledger),
        }
    )
    assert out["ok"] is True
    assert out["task"]["workspace"] == str(ledger.resolve())
    assert out["task"]["workspace_private"] is False
    saved = manager.task_store.get(out["task"]["id"])
    assert saved.workspace == str(ledger.resolve())
    recent_paths = {r["path"] for r in manager.recent_workspaces()}
    assert str(ledger.resolve()) in recent_paths


def test_create_automation_relative_workspace_rejected(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    out = manager.create_automation(
        {
            "title": "Bad workspace",
            "instructions": "do something",
            "cron": "0 8 * * *",
            "workspace": "relative/path",
        }
    )
    assert out["ok"] is False
    assert "absolute" in out["error"]
    assert manager.task_store.list() == []


def test_create_automation_missing_workspace_rejected(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    out = manager.create_automation(
        {
            "title": "Bad workspace",
            "instructions": "do something",
            "cron": "0 8 * * *",
            "workspace": str(tmp_path / "does-not-exist"),
        }
    )
    assert out["ok"] is False
    assert "does not exist" in out["error"]
    assert manager.task_store.list() == []


def test_create_automation_file_workspace_rejected(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    a_file = tmp_path / "not-a-folder.txt"
    a_file.write_text("hi", encoding="utf-8")
    out = manager.create_automation(
        {
            "title": "Bad workspace",
            "instructions": "do something",
            "cron": "0 8 * * *",
            "workspace": str(a_file),
        }
    )
    assert out["ok"] is False
    assert "does not exist" in out["error"] or "not a directory" in out["error"]
    assert manager.task_store.list() == []
