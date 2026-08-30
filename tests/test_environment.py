"""Tests for the session environment context block (system-prompt injection)."""

from __future__ import annotations

import locale
import subprocess
import sys

import pytest

from coworker.environment import environment_context


def _git_repo(tmp_path):
    ws = tmp_path / "repo"
    ws.mkdir()
    run = lambda *a: subprocess.run(
        ["git", "-C", str(ws), *a], capture_output=True, check=True
    )
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@t.io")
    run("config", "user.name", "T")
    (ws / "f.txt").write_text("1", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "first commit")
    return ws


def test_context_includes_workspace_platform_and_date(tmp_path):
    block = environment_context(tmp_path)
    # The workspace path itself is NOT interpolated (kept out so the system prompt stays
    # byte-stable across sessions for provider prompt caching) — it points at the per-turn
    # <system-context> block instead, where the live roots list renders the actual path.
    assert str(tmp_path.resolve()) not in block
    assert "<system-context>" in block
    assert sys.platform in block
    assert "Today's date:" in block
    assert "<environment>" in block and "</environment>" in block


def test_context_outside_git_repo(tmp_path):
    assert "not a git repository" in environment_context(tmp_path)


def test_context_with_git_repo(tmp_path):
    ws = _git_repo(tmp_path)
    block = environment_context(ws)
    assert "Git branch: main" in block
    assert "Git status: clean" in block
    assert "first commit" in block


def test_context_shows_dirty_status(tmp_path):
    ws = _git_repo(tmp_path)
    (ws / "f.txt").write_text("2", encoding="utf-8")
    (ws / "new.txt").write_text("x", encoding="utf-8")
    block = environment_context(ws)
    assert "Git status (2 changed):" in block
    assert "f.txt" in block and "new.txt" in block


def test_git_snapshot_ignores_locale_encoding(tmp_path, monkeypatch):
    """zh-CN Windows regression (owner-hit 2026-08-30): git emits UTF-8, but text=True
    without an explicit encoding decodes with the locale codepage (GBK). One invalid
    byte killed subprocess's reader thread, stdout came back None, and the resulting
    AttributeError took down every WebSocket connect to that workspace — a permanently
    dead Send button. The snapshot must decode git output as UTF-8 regardless of locale.
    """
    if sys.flags.utf8_mode:
        pytest.skip("UTF-8 mode bypasses locale decoding, so the old bug can't show")
    ws = _git_repo(tmp_path)
    (ws / "更新.txt").write_text("内容", encoding="utf-8")
    subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
    # "一)" is the trap: UTF-8 E4 B8 80 29 — after the valid GBK pair E4 B8, the 0x80
    # byte is below GBK's lead range, so a locale decode raises mid-stream.
    subprocess.run(
        ["git", "-C", str(ws), "commit", "-qm", "中文提交一)含 GBK 解不了的字节"],
        capture_output=True,
        check=True,
    )
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "gbk")
    block = environment_context(ws)
    assert "中文提交一)含 GBK 解不了的字节" in block


class _Stub:
    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        from coworker.providers import ModelCapabilities

        return ModelCapabilities()


def test_build_engine_injects_environment(tmp_path):
    from coworker.agent import build_engine
    from coworker.agents import code_agent

    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        system = engine.messages[0]
        assert system["role"] == "system"
        assert "<environment>" in system["content"]
        # Workspace path lives in the per-turn <system-context> block (roots list), not here —
        # keeps the system prompt byte-stable across sessions for provider prompt caching.
        assert str(tmp_path.resolve()) not in system["content"]
    finally:
        engine.executor.close()
