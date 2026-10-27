"""Workspace-local search ignores.

Opening a real project may create a standard ``.ignore`` file so ripgrep and other
search tools skip dependency trees, build output and local secrets. Existing user-owned
``.ignore`` / ``.rgignore`` files are never changed. The Python search/list fallbacks
use the same files through :class:`WorkspaceIgnore`; explicit file reads stay unaffected.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Optional

import pathspec

IGNORE_FILENAMES = (".rgignore", ".ignore")

_BASE_RULES = (
    ".git/",
    "**/__pycache__/",
    "**/.pytest_cache/",
    "**/.mypy_cache/",
    "**/.ruff_cache/",
    "**/node_modules/",
    "**/dist/",
    "**/build/",
    "**/target/",
    "**/coverage/",
    "**/*.min.js",
    "**/*.map",
    ".env",
    ".env.*",
    "!.env.example",
    "!.env.*.example",
)

# Only root markers are inspected: project detection must never become the recursive
# walk that this feature is meant to avoid.
_STACK_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("pyproject.toml", "requirements.txt", "setup.py"),
        (".venv/", "venv/", "*.egg-info/", ".tox/", ".nox/"),
    ),
    (
        ("package.json",),
        (".next/", ".nuxt/", ".turbo/", ".vite/", "test-results/", "playwright-report/"),
    ),
    (("Cargo.toml",), ("target/",)),
    (("pom.xml", "build.gradle", "build.gradle.kts"), (".gradle/", "target/", "build/")),
    (("*.sln", "*.csproj"), ("bin/", "obj/")),
    (("settings.gradle", "settings.gradle.kts", "Podfile", "*.xcodeproj"), (".gradle/", "build/", "DerivedData/")),
)


def _has_marker(root: Path, marker: str) -> bool:
    if any(ch in marker for ch in "*?["):
        # scandir is deliberately one level only; Path.glob would also accept a
        # recursive marker if one were added here later by mistake.
        import fnmatch

        try:
            return any(fnmatch.fnmatch(entry.name, marker) for entry in os.scandir(root))
        except OSError:
            return False
    return (root / marker).exists()


def generated_rules(root: Path) -> list[str]:
    """Rules for the project's root manifests, in stable order and without duplicates."""
    rules = list(_BASE_RULES)
    for markers, additions in _STACK_RULES:
        if any(_has_marker(root, marker) for marker in markers):
            rules.extend(additions)
    return list(dict.fromkeys(rules))


def ensure_workspace_ignore(workspace: str | Path, *, enabled: bool = True) -> dict[str, Any]:
    """Create ``<workspace>/.ignore`` once, without touching existing ignore files.

    The return value is suitable for the workspace-open REST response. Failure is
    non-fatal to opening the folder and is reported as ``status='unavailable'``.
    """
    root = Path(workspace)
    path = root / ".ignore"
    if not enabled:
        return {"path": str(path), "status": "disabled"}
    for name in IGNORE_FILENAMES:
        existing = root / name
        if existing.exists():
            return {"path": str(existing), "status": "existing"}
    content = (
        "# Created by smjworker to reduce search noise; does not affect Git or builds.\n"
        "# Explicit file reads remain available. Edit or delete this file as needed.\n"
        + "\n".join(generated_rules(root))
        + "\n"
    )
    try:
        # Exclusive creation is idempotent across two simultaneous workspace-open calls
        # and guarantees that a user file appearing after the exists() check is not lost.
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError:
        return {"path": str(path), "status": "existing"}
    except OSError as exc:
        return {"path": str(path), "status": "unavailable", "error": str(exc)}
    return {"path": str(path), "status": "created"}


def ignore_files(root: str | Path) -> list[Path]:
    """Existing root ignore files, in ripgrep's precedence order (lowest first)."""
    base = Path(root)
    return [base / name for name in reversed(IGNORE_FILENAMES) if (base / name).is_file()]


class WorkspaceIgnore:
    """A cached root-level ``.ignore`` / ``.rgignore`` matcher for Python walkers.

    ``pathspec`` implements gitwildmatch syntax, including rooted patterns, ``**`` and
    negation. Invalid or unreadable files degrade to the built-in skip lists only.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        lines: list[str] = []
        for path in ignore_files(self.root):
            try:
                lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
        self._spec = pathspec.GitIgnoreSpec.from_lines(lines) if lines else None

    def matches(self, path: str | Path, *, directory: bool = False) -> bool:
        if self._spec is None:
            return False
        try:
            relative = Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except (OSError, ValueError):
            return False
        if directory and relative != ".":
            relative += "/"
        return self._spec.match_file(relative)

    def prune(self, dirpath: str | Path, dirs: Iterable[str]) -> list[str]:
        base = Path(dirpath)
        return [
            name
            for name in dirs
            if not self.matches(base / name, directory=True)
        ]
