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

For the same reason the rendered block must stay byte-identical across sessions on one
workspace: nothing per-session may enter it. The memo below (`gitprobe`) leans on that —
it is keyed by workspace alone, because two sessions on one workspace are entitled to
exactly the same bytes.
"""

from __future__ import annotations

import os
import platform as _platform
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from .gitprobe import TTLCache

# One rendered block per resolved workspace. The picker rebuilds the engine on every
# coworker/folder pick (audit 2026-09-13); re-running git for each of those clicks bought
# nothing but latency.
_CONTEXT_CACHE = TTLCache()


def _run(workspace: Path, *args: str) -> Optional[tuple[int, str, str]]:
    """`(returncode, stdout, stderr)`, or None when git could not be run at all."""
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
            # _git_snapshot tells "not a repo" apart from "something broke" by matching
            # git's English stderr, and gettext translates those fatals wherever catalogs
            # are installed (distro git packages ship git.mo; Git for Windows ships none).
            # Pin the message locale so an ordinary non-repo folder cannot read as a
            # tooling failure. LANGUAGE too: it overrides LC_ALL for gettext.
            env={**os.environ, "LC_ALL": "C", "LANG": "C", "LANGUAGE": ""},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.returncode, out.stdout or "", out.stderr or ""


def _git(workspace: Path, *args: str) -> Optional[str]:
    out = _run(workspace, *args)
    if out is None or out[0] != 0:
        return None
    return out[1].strip()


_NO_COMMITS = "No commits yet on "


def _branch_from_header(header: str) -> str:
    """The branch out of porcelain's `## …` header line.

    Four shapes to survive: `## main`, `## main...origin/main [ahead 1]` (upstream +
    divergence), `## HEAD (no branch)` (detached), `## No commits yet on main` (a fresh
    repo — where the old `rev-parse --abbrev-ref HEAD` used to fail outright and the block
    said "(unknown)").
    """
    name = header[3:].strip() if header.startswith("## ") else header.strip()
    if name.startswith(_NO_COMMITS):
        name = name[len(_NO_COMMITS) :].strip()
    if name.startswith("HEAD (no branch)"):
        return "HEAD (detached)"
    # A ref name can never contain "..", so splitting on the upstream separator is safe.
    return name.split("...", 1)[0].strip() or "(unknown)"


def _git_snapshot(workspace: Path) -> list[str]:
    # ONE spawn for branch + dirty state + is-this-a-repo (audit 2026-09-13): this used to
    # be three (`rev-parse --is-inside-work-tree`, `rev-parse --abbrev-ref HEAD`,
    # `status --porcelain`), and process spawn — not git's work — was the cost on Windows.
    out = _run(workspace, "status", "--porcelain=v1", "-b")
    if out is None:
        return ["Git: state unavailable"]  # no git on PATH, or it timed out
    code, stdout, stderr = out
    if code != 0:
        # Be honest about which failure this was: "not a repo" is a fact about the
        # workspace the agent can act on; anything else (a stale index.lock, a broken
        # repo) is not, and claiming it is would send the agent down the wrong path.
        low = stderr.lower()
        if (
            "not a git repository" in low
            # `fatal: cannot change to '<path>': No such file or directory` — the workspace
            # itself is gone. Matched on the FIRST half only: a bare "no such file or
            # directory" also comes back from a corrupt repo (`could not open
            # '.git/index'`), which is exactly the case the branch below exists to keep
            # separate (audit 2026-09-13).
            or "cannot change to" in low
        ):
            return ["Git: not a git repository"]
        return ["Git: state unavailable"]

    lines: list[str] = []
    rows = stdout.splitlines()
    header = rows[0] if rows and rows[0].startswith("## ") else ""
    changed = rows[1:] if header else rows
    lines.append(f"Git branch: {_branch_from_header(header) if header else '(unknown)'}")
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
    """A system-prompt block describing the session's environment and git state.

    Memoised per resolved workspace for `gitprobe.TTL_SECONDS` — see the module docstring
    for why that is safe (the block holds nothing per-session by construction).
    """
    ws = Path(workspace).expanduser().resolve()
    return _CONTEXT_CACHE.get(str(ws), lambda: _render(ws))


def _render(ws: Path) -> str:
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
