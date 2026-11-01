"""A routine can be trusted with a tool that has no target to bind.

"Always allow" on a run's approval card mints a standing rule on the task. That only
worked for external-risk calls naming a target, so a routine whose work is web search
asked the same question on every run: the session-scoped "always" dies with the run,
and each scheduled run is a fresh session. Egress ranks *below* external in the
engine's own strictness table, so the rule was being refused for the safer class.
"""

from __future__ import annotations

from coworker.automation.models import Schedule, ScheduledTask, TaskRun
from coworker.permissions import standing_tool_candidate
from coworker.providers import ModelCapabilities, ProviderClient
from coworker.server.manager import SessionManager


class NoTurnsProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("no model turns expected")

    def capabilities(self, model):
        return ModelCapabilities()


def test_only_egress_earns_a_target_less_grant():
    assert standing_tool_candidate("web_search") is True
    assert standing_tool_candidate("web_fetch") is True
    # Exec and local writes ask forever, as they do for target-bound rules.
    assert standing_tool_candidate("run_shell") is False
    assert standing_tool_candidate("write_file") is False


def _task_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data", provider=NoTurnsProvider())
    task = ScheduledTask(
        title="Daily watch",
        instructions="sweep",
        agent="watcher",
        workspace=str(tmp_path / "work"),
        schedule=Schedule(kind="cron", cron="0 7 * * *"),
    )
    manager.task_store.save(task)
    run = TaskRun(task_id=task.id)
    manager.task_store.add_run(run)
    return manager, task, run


def test_web_search_grant_persists_on_the_task(tmp_path, monkeypatch):
    manager, task, run = _task_manager(tmp_path, monkeypatch)

    assert manager.mint_task_rule(run.session_id, "web_search", {"query": "anything"})
    # Minting twice is a no-op, not a duplicate entry.
    assert not manager.mint_task_rule(run.session_id, "web_search", {"query": "again"})

    fresh = manager.task_store.get(task.id)
    assert fresh.always_allowed_tools == ["web_search"]
    assert "web_search" in fresh.name_allowed_tools()
    # A name-only entry is revocable like any other, and reads back on the API shape.
    entry = [r for r in fresh.public()["always_allowed"] if r["tool"] == "web_search"][0]
    assert entry["target"] is None
    assert fresh.revoke_rule(entry["entry"]) is True


def test_always_task_resolution_on_web_search_is_kept(tmp_path, monkeypatch):
    manager, task, run = _task_manager(tmp_path, monkeypatch)

    class _Request:
        tool_name = "web_search"
        arguments = {"query": "news"}
        metadata = None

    manager.approval_outcome("always_task", _Request(), run.session_id)
    assert manager.task_store.get(task.id).always_allowed_tools == ["web_search"]


def test_shell_still_asks_every_time(tmp_path, monkeypatch):
    manager, task, run = _task_manager(tmp_path, monkeypatch)

    assert manager.mint_task_rule(run.session_id, "run_shell", {"command": "ls"}) is False
    assert manager.task_store.get(task.id).always_allowed_tools == []
