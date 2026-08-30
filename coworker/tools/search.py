"""Fast code search (`grep`) — ripgrep when available, a Python walk otherwise.

ripgrep respects `.gitignore`, so it skips `node_modules`/`target`/`dist` automatically; the
fallback skips a hardcoded set of heavy dirs. Read-only, workspace-scoped. Returns file:line:text.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import aisuite as ai

# Per-OS application data directories. These are not build noise: on macOS 14+ merely
# *descending* into ~/Library/Application Support (other apps' containers) trips the App
# Data TCC protection and macOS shows "would like to access data from other apps" — an
# alarming prompt the user never asked for, reachable whenever the workspace is a home
# directory. Never traversed; a workspace under one of these is still searched normally,
# because the guard matches directory NAMES encountered during a walk.
OS_DATA_DIRS = {
    "Library",  # macOS
    "AppData",  # Windows
    "Application Data",  # Windows (legacy junction)
}

_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
} | OS_DATA_DIRS

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "grep",
        "description": (
            "Search the workspace for a regular-expression pattern and return matching lines as "
            "file:line:text. Fast and .gitignore-aware (skips node_modules, build dirs, etc.). "
            "Prefer this over reading files blindly to locate code. Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Subdirectory to search (default: whole workspace).",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional filename glob filter, e.g. '*.py'.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max matches (default 100, max 1000).",
                },
            },
            "required": ["pattern"],
        },
    },
}


def search_tools(workspace: str) -> list:
    root = Path(workspace).resolve()

    def grep(
        pattern: str,
        path: str = ".",
        glob: Optional[str] = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        n = max_results if isinstance(max_results, int) and max_results > 0 else 100
        n = min(n, 1000)
        base = (root / (path or ".")).resolve()
        try:
            base.relative_to(root)  # keep searches inside the workspace
        except ValueError:
            return {"error": "path escapes the workspace"}
        # ripgrep is run from inside the directory it searches (see below), so settle the
        # target here: `cwd` must be a real directory, and a missing path should read as
        # such rather than as a raw, localised spawn failure.
        if base.is_dir():
            cwd, target = base, "."
        elif base.is_file():
            cwd, target = base.parent, base.name  # `path` may still name a single file
        else:
            return {"error": f"no such file or directory: {path}"}

        rg = shutil.which("rg")
        if rg:
            # `--json`, not the default text output: a `path:line:text` line cannot be
            # taken apart reliably on Windows, where an absolute path opens with a drive
            # prefix (`C:`) that the first split on ":" swallows.
            cmd = [
                rg,
                "--json",
                "--line-number",
                "--max-count",
                str(n),
                "-e",
                pattern,
            ]
            if glob:
                cmd += ["--glob", glob]
            # Do not rely solely on a workspace's .gitignore: the Python fallback
            # always omits these generated/dependency directories too. Exclusions come
            # last because ripgrep resolves conflicting globs with the later one winning.
            for ignored in sorted(_IGNORE_DIRS):
                cmd += ["--glob", f"!**/{ignored}/**"]
            # Search a relative target from inside `cwd` so those exclusions are matched
            # against base-relative paths, the way the fallback's os.walk only ever sees
            # directory names below `base`. Handing rg an absolute path instead would test
            # them against the whole prefix too, so a workspace living *under* one of the
            # ignored names would exclude itself: on Windows nothing below
            # %APPDATA%/%LOCALAPPDATA% — this app's own data dir included — could be
            # searched at all.
            cmd.append(target)
            try:
                out = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    # ripgrep emits UTF-8 whatever the console codepage is; letting Python
                    # decode with the locale's (cp936 on zh-CN Windows) would mangle the
                    # JSON and silently drop every match.
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    cwd=str(cwd),
                )
            except Exception as exc:
                return {"error": f"grep failed: {exc}"}
            if out.returncode not in (0, 1):  # 1 = no matches
                return {"error": (out.stderr or "ripgrep error").strip()[:300]}
            return {"engine": "ripgrep", **_parse_rg(out.stdout, root, cwd, n)}

        return {"engine": "python", **_py_grep(root, base, pattern, glob, n)}

    grep.__name__ = "grep"
    grep.__doc__ = _SCHEMA["function"]["description"]
    grep.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="grep",
        category="search",
        risk_level="low",
        capabilities=["search"],
        requires_approval=False,
    )
    grep.__coworker_schema__ = _SCHEMA
    return [grep]


def _rel(path: str, root: Path, base: Optional[Path] = None) -> str:
    try:
        p = Path(path)
        if base is not None and not p.is_absolute():
            p = base / p  # ripgrep runs with cwd=base, so it reports paths relative to it
        return str(p.resolve().relative_to(root))
    except (ValueError, OSError):
        return path


def _rg_str(field: Any) -> Optional[str]:
    """Read one ripgrep JSON string: `{"text": ...}`, or `{"bytes": <base64>}` when the
    original bytes were not valid UTF-8 (a path or line in some other encoding)."""
    if not isinstance(field, dict):
        return None
    if isinstance(field.get("text"), str):
        return field["text"]
    raw = field.get("bytes")
    if isinstance(raw, str):
        try:
            return base64.b64decode(raw).decode("utf-8", "replace")
        except ValueError:
            return None
    return None


def _parse_rg(stdout: str, root: Path, base: Optional[Path], n: int) -> dict[str, Any]:
    """Parse ripgrep's `--json` event stream — one JSON object per line.

    Not the text output: splitting `path:line:text` on ":" mangles every Windows absolute
    path, whose `C:` drive prefix is taken for the filename (the line then parses as file
    "C", line 0, and a text field still carrying the real line number). The JSON events
    keep path, line number and text apart whatever any of them contains.
    """
    matches: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue  # one unreadable line must not throw away the whole result
        if not isinstance(event, dict) or event.get("type") != "match":
            continue  # begin/end/context/summary events carry no match
        data = event.get("data") or {}
        f = _rg_str(data.get("path"))
        if f is None:
            continue
        ln = data.get("line_number")
        matches.append(
            {
                "file": _rel(f, root, base),
                "line": ln if isinstance(ln, int) else 0,
                "text": (_rg_str(data.get("lines")) or "").rstrip("\r\n")[:300],
            }
        )
        if len(matches) >= n:
            break
    return {"count": len(matches), "matches": matches}


def _py_grep(
    root: Path, base: Path, pattern: str, glob: Optional[str], n: int
) -> dict[str, Any]:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"error": f"invalid regex: {exc}", "count": 0, "matches": []}
    matches: list[dict[str, Any]] = []
    walk = os.walk(base) if base.is_dir() else [(str(base.parent), [], [base.name])]
    for dirpath, dirs, files in walk:
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for fn in files:
            if glob and not fnmatch.fnmatch(fn, glob):
                continue
            fp = Path(dirpath) / fn
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            matches.append(
                                {
                                    "file": _rel(str(fp), root),
                                    "line": i,
                                    "text": line.rstrip()[:300],
                                }
                            )
                            if len(matches) >= n:
                                return {"count": len(matches), "matches": matches}
            except OSError:
                continue
    return {"count": len(matches), "matches": matches}
