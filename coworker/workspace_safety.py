"""What code can establish about a workspace write without asking a model (OPE-233).

Auto-Approve lets a write skip the reviewer when undoing it is easy and nothing about it
can execute later: an inert file type, a name and content that don't look secret, and a
target that is new, git-tracked with no uncommitted changes, or written by the agent
earlier in this session. Every check fails toward "ask the reviewer": an unknown file type,
an unreadable git state or a doubtful name keeps today's behaviour.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from . import procutil

# Plain documents, data and raster images: nothing here is loaded and run by a build,
# test runner, package manager, shell or browser. Formats that can carry script are NOT
# here, however document-like: .html/.htm and .svg run JavaScript when opened, .xml can
# pull in a stylesheet that does, and .pdf supports JavaScript in many readers. A live
# run showed why (2026-10-26): refused an upload, the agent wrote an .html page whose
# script did the upload, then tried to open it.
_DOCUMENT_SUFFIXES = frozenset({
    ".md", ".markdown", ".txt", ".rst", ".csv", ".tsv", ".log",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
})
# Structured data is inert unless a tool reads it to decide what to run. Those files are
# dotfiles (`.eslintrc.json`, `.gitpod.yml`) or have well-known names, listed below.
_DATA_SUFFIXES = frozenset({".json", ".jsonl", ".yaml", ".yml"})
_TOOL_CONFIG_NAMES = frozenset({
    # package managers and task runners: scripts, tasks, hooks
    "package.json", "package-lock.json", "composer.json", "deno.json", "deno.jsonc",
    "turbo.json", "nx.json", "lerna.json", "taskfile.yml", "taskfile.yaml",
    # build and transpile configs that load plugins
    "babel.config.json", "tsconfig.json", "jsconfig.json", "angular.json", "project.json",
    # containers and deploy targets
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "vercel.json", "now.json", "firebase.json", "app.json", "app.yaml", "serverless.yml",
    "serverless.yaml", "cloudbuild.yaml", "cloudbuild.yml", "fly.toml",
    # CI systems not covered by the protected list
    "azure-pipelines.yml", "bitbucket-pipelines.yml", "appveyor.yml", "codemagic.yaml",
    "mkdocs.yml", "renovate.json",
})

_SENSITIVE_NAME = re.compile(
    r"^\.env(\..*)?$"
    r"|\.(pem|key|p12|pfx|kdbx|keystore|jks|ppk|gpg|asc)$"
    r"|^id_(rsa|dsa|ecdsa|ed25519)"
    r"|(^|[._-])(secret|secrets|credential|credentials|password|passwd|token|tokens"
    r"|apikey|api[_-]key|private[_-]key)([._-]|$)"
    r"|^\.(netrc|npmrc|pypirc|pgpass)$",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\b(AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\b(api[_-]?key|secret|token|password|passwd|access[_-]?key)\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+=]{16,}",
    re.IGNORECASE,
)

# Git states this module reports for an existing file.
TRACKED_CLEAN = "tracked_clean"
TRACKED_MODIFIED = "tracked_modified"
UNTRACKED = "untracked"
IGNORED = "ignored"
UNKNOWN = "unknown"


def is_inert_name(name: str) -> bool:
    lowered = name.lower()
    suffix = os.path.splitext(lowered)[1]
    if suffix in _DOCUMENT_SUFFIXES:
        return True
    if suffix in _DATA_SUFFIXES:
        return not lowered.startswith(".") and lowered not in _TOOL_CONFIG_NAMES
    return False


def is_sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME.search(name))


def _strings(value: Any, depth: int = 0) -> list[str]:
    """Every string inside the arguments, raw (not JSON-escaped, so quotes and newlines
    look the way they will on disk)."""
    if depth > 6:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v, depth + 1)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v, depth + 1)]
    return []


def has_secret_value(arguments: dict[str, Any]) -> bool:
    return any(_SECRET_VALUE.search(text) for text in _strings(arguments))


def _git(args: list[str], cwd: Path) -> Optional[subprocess.CompletedProcess]:
    exe = shutil.which("git")
    if exe is None:
        return None
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}  # never take the index lock to look
    try:
        return subprocess.run(
            [exe, *args], cwd=str(cwd), capture_output=True, timeout=5, env=env, check=False,
            **procutil.popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_file_state(path: Path) -> str:
    """State of an EXISTING file: tracked_clean, tracked_modified, untracked, ignored, or
    unknown (no git, not a repository, or git failed)."""
    folder = path.parent
    top = _git(["rev-parse", "--show-toplevel"], folder)
    if top is None or top.returncode != 0:
        return UNKNOWN
    root = Path(top.stdout.decode("utf-8", "replace").strip())
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return UNKNOWN
    tracked = _git(["ls-files", "--error-unmatch", "--", rel], root)
    if tracked is None:
        return UNKNOWN
    status = _git(["status", "--porcelain=v1", "--untracked-files=all", "--ignored", "--", rel], root)
    if status is None or status.returncode != 0:
        return UNKNOWN
    lines = [ln for ln in status.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    if tracked.returncode == 0:
        return TRACKED_CLEAN if not lines else TRACKED_MODIFIED
    if any(ln.startswith("!!") for ln in lines):
        return IGNORED
    return UNTRACKED


def inert_write_check(
    arguments: dict[str, Any],
    targets: list[Path],
    *,
    agent_wrote: Optional[Callable[[Path], bool]] = None,
) -> tuple[bool, str]:
    """(eligible, detail) for a write whose targets already passed the gate's floors (in a
    writable root, not protected). `detail` says what made it eligible, for the audit row."""
    if not targets:
        return False, ""
    if has_secret_value(arguments):
        return False, ""
    parts: list[str] = []
    for target in targets:
        name = target.name
        if not is_inert_name(name) or is_sensitive_name(name):
            return False, ""
        if not target.exists():
            parts.append(f"new file {name}")
        elif agent_wrote is not None and agent_wrote(target):
            parts.append(f"{name} written by the agent this session")
        elif git_file_state(target) == TRACKED_CLEAN:
            parts.append(f"{name} unchanged in git")
        else:
            return False, ""
    return True, "; ".join(parts)
