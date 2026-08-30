"""Session environment context — injected into the system prompt at engine build.

Saves the agent a few discovery tool calls every session (uname, git status, git log) by
telling it up front what state the workspace is in. The git snapshot is point-in-time; the
prompt labels it as such so the agent re-checks before relying on it.

The workspace path is deliberately NOT interpolated here — it already lives in the per-turn
<system-context> block ("Available directories"). Cowork sessions embed a per-session id in
that path, so putting it in the system prompt would make the system prompt differ byte-for-byte
on every new session, defeating the provider prompt cache (tools+system prefix) that's meant to
be shared across sessions: per-session bytes in the system prompt get priced at full cache-write
rates on every new session instead of hitting a shared cache.
"""

from __future__ import annotations

import platform as _platform
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional


def _git(workspace: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            # Git emits UTF-8; without an explicit encoding, Windows decodes with the
            # locale codepage (GBK on zh-CN), and one invalid byte kills subprocess's
            # reader thread — stdout comes back None and the whole engine build (and
            # its WebSocket) dies with it. errors="replace" keeps a stray byte cosmetic.
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return (out.stdout or "").strip()


def _git_snapshot(workspace: Path) -> list[str]:
    if _git(workspace, "rev-parse", "--is-inside-work-tree") != "true":
        return ["Git: not a git repository"]

    lines = []
    branch = _git(workspace, "rev-parse", "--abbrev-ref", "HEAD") or "(unknown)"
    lines.append(f"Git branch: {branch}")

    status = _git(workspace, "status", "--porcelain")
    if status is not None:
        changed = status.splitlines()
        if not changed:
            lines.append("Git status: clean")
        else:
            shown = "\n".join(changed[:20])
            more = f"\n… and {len(changed) - 20} more" if len(changed) > 20 else ""
            lines.append(f"Git status ({len(changed)} changed):\n{shown}{more}")

    log = _git(workspace, "log", "-n5", "--pretty=format:%h %s")
    if log:
        lines.append(f"Recent commits:\n{log}")
    return lines


def environment_context(workspace: str | Path) -> str:
    """A system-prompt block describing the session's environment and git state."""
    ws = Path(workspace).expanduser().resolve()
    mac = _platform.mac_ver()[0]
    os_name = f"macOS {mac}" if mac else f"{_platform.system()} {_platform.release()}"
    lines = [
        "Workspace: see 'Available directories' in <system-context> (the primary entry is "
        "the workspace)",
        f"Platform: {sys.platform} ({os_name})",
        f"Today's date: {date.today().isoformat()}",
        *_git_snapshot(ws),
    ]
    body = "\n".join(lines)
    return (
        "Environment (snapshot from session start — verify before relying on git "
        f"state):\n<environment>\n{body}\n</environment>\n"
        "Folder scope: work inside the workspace and any folders the user has granted. Do not "
        "read or list other locations (home directory sweeps, ~/Desktop, ~/Downloads, photo "
        "libraries, etc.) — not even via shell commands like find/ls/grep. On macOS every such "
        "touch fires an OS permission prompt the user can't connect to any action they took. "
        "If a task needs files elsewhere, ask first with request_directory."
    )
