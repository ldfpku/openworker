"""Project context — AGENTS.md ingestion (root + global) into the system prompt."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .secrets import state_dir


def default_global_agents_path() -> Path:
    return state_dir() / "AGENTS.md"


def load_agents_md(
    workspace: str | Path, *, global_path: Optional[str | Path] = None
) -> str:
    """Return a system-prompt block from the global and project AGENTS.md files.

    v1 loads global (`<state-dir>/AGENTS.md`) + project-root `AGENTS.md` only;
    nested discovery is a fast-follow.
    """
    parts: list[tuple[str, str]] = []

    # errors="replace" on both reads: these are hand-written files, and one saved in a
    # legacy codepage (ANSI/GBK on a Chinese Windows) would otherwise raise mid-build
    # and fail every session connect to that workspace.
    g = Path(global_path) if global_path is not None else default_global_agents_path()
    if g.is_file():
        parts.append(("global", g.read_text(encoding="utf-8", errors="replace")))

    root = Path(workspace).expanduser().resolve() / "AGENTS.md"
    if root.is_file():
        parts.append(("project", root.read_text(encoding="utf-8", errors="replace")))

    if not parts:
        return ""

    blocks = [
        f"<{label} AGENTS.md>\n{text.strip()}\n</{label} AGENTS.md>"
        for label, text in parts
    ]
    return "Project conventions:\n" + "\n\n".join(blocks)
