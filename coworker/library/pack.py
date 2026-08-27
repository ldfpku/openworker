"""Read-only access to the pre-built library data pack (library-pack/).

The pack ships pre-packaged expert prompts (agency-agents / agency-agents-zh) and
skills (scientific-agent-skills) for browsing inside coworker — see
library-pack/index.json and library-pack/ATTRIBUTION.md for provenance. This module
only reads the pack; nothing here writes to it (the pack is built by a separate script).

Location resolution order:
  1. ``OPENWORKER_LIBRARY_DIR`` env var (tests, dev overrides)
  2. PyInstaller bundle: ``sys._MEIPASS/library-pack``
  3. dev checkout: ``<coworker package dir>/../library-pack`` (repo root)

index.json is loaded lazily and, once it parses, cached for the instance's lifetime.
Only success is cached: a missing or unreadable index is re-tried on the next request,
so a transient failure never poisons a long-lived process. The module-level singleton
in ``api.py`` lives for the process — tests that need a different pack construct their
own ``LibraryPack`` and swap it in via ``set_pack_for_tests``/
``register_library_routes(app, pack=...)``.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

_LIBS = ("zh", "en")


def _default_pack_dir() -> Optional[Path]:
    env = os.environ.get("OPENWORKER_LIBRARY_DIR")
    if env:
        return Path(env)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "library-pack"
        if candidate.is_dir():
            return candidate
    # coworker/library/pack.py -> coworker/library -> coworker -> repo root
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "library-pack"


def _strip_frontmatter(text: str) -> str:
    """Split a leading ``---\\n...\\n---`` YAML block off a markdown file's body. No
    frontmatter (or an unterminated one) → the text is returned as-is, just stripped."""
    if not text.startswith("---"):
        return text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return text.strip()
    body = text[end + 4 :]
    return body.strip()


class LibraryPack:
    """Lazily-loaded read-only view over one library-pack directory."""

    def __init__(self, root: Optional[str | Path] = None) -> None:
        self.root: Optional[Path] = Path(root) if root is not None else _default_pack_dir()
        self._index: Optional[dict[str, Any]] = None
        self._loaded = False
        self._lock = threading.Lock()

    # -- loading --------------------------------------------------------------------
    def _load(self) -> Optional[dict[str, Any]]:
        # The /v1/library routes are sync defs, so FastAPI runs them in a threadpool and
        # the GUI's first visit fires several of them into this lazy load concurrently.
        # The lock makes late arrivals wait for the winner's parse instead of observing
        # a half-initialized instance (the shipped desktop app's "pack missing" ghost);
        # caching only success means a missing or unreadable index is re-tried on the
        # next request rather than pinning the process to a one-off read failure.
        with self._lock:
            if self._loaded:
                return self._index
            if self.root is None:
                return None
            index_path = self.root / "index.json"
            try:
                self._index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._index = None
                return None
            self._loaded = True
            return self._index

    @staticmethod
    def _missing() -> dict[str, Any]:
        return {"ok": False, "error": "library pack not found"}

    def _safe_path(self, base: Optional[Path], relative: str) -> Optional[Path]:
        """Resolve ``relative`` under ``base``; ``None`` if it escapes ``base`` (path
        traversal) or ``base`` itself is unset."""
        if base is None:
            return None
        try:
            base_resolved = base.resolve()
            candidate = (base / relative).resolve()
        except OSError:
            return None
        if base_resolved != candidate and base_resolved not in candidate.parents:
            return None
        return candidate

    # -- queries --------------------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        index = self._load()
        if index is None:
            return self._missing()
        experts = index.get("experts", {}) or {}
        return {
            "ok": True,
            "version": index.get("version", 1),
            "experts": {
                lib: len(experts.get(lib, []) or []) for lib in _LIBS
            },
            "skills": len(index.get("skills", []) or []),
        }

    def experts(self, lib: str = "zh") -> dict[str, Any]:
        index = self._load()
        if index is None:
            return self._missing()
        lib = (lib or "zh").strip()
        if lib not in _LIBS:
            return {"ok": False, "error": f"Unknown library: {lib}"}
        rows = (index.get("experts", {}) or {}).get(lib, []) or []
        return {"ok": True, "experts": rows}

    def expert_prompt(self, lib: str, expert_id: str) -> dict[str, Any]:
        index = self._load()
        if index is None:
            return self._missing()
        lib = (lib or "zh").strip()
        if lib not in _LIBS:
            return {"ok": False, "error": f"Unknown library: {lib}"}
        expert_id = (expert_id or "").strip()
        rows = (index.get("experts", {}) or {}).get(lib, []) or []
        entry = next((r for r in rows if r.get("id") == expert_id), None)
        if entry is None or not expert_id:
            return {"ok": False, "error": f"Unknown expert: {expert_id}"}
        base = (self.root / "experts" / lib) if self.root is not None else None
        path = self._safe_path(base, f"{expert_id}.md")
        if path is None or not path.is_file():
            return {"ok": False, "error": f"Unknown expert: {expert_id}"}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {"ok": False, "error": f"Unknown expert: {expert_id}"}
        return {
            "ok": True,
            "id": expert_id,
            "name": entry.get("name", ""),
            "prompt": _strip_frontmatter(text),
        }

    def skills(self) -> dict[str, Any]:
        index = self._load()
        if index is None:
            return self._missing()
        return {"ok": True, "skills": index.get("skills", []) or []}

    def skill(self, name: str) -> dict[str, Any]:
        index = self._load()
        if index is None:
            return self._missing()
        name = (name or "").strip()
        rows = index.get("skills", []) or []
        entry = next((r for r in rows if r.get("name") == name), None)
        if entry is None or not name:
            return {"ok": False, "error": f"Unknown skill: {name}"}
        base = (self.root / "skills") if self.root is not None else None
        skill_dir = self._safe_path(base, name)
        if skill_dir is None or not skill_dir.is_dir():
            return {"ok": False, "error": f"Unknown skill: {name}"}
        md_path = skill_dir / "SKILL.md"
        if not md_path.is_file():
            return {"ok": False, "error": f"Unknown skill: {name}"}
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            return {"ok": False, "error": f"Unknown skill: {name}"}
        files = sorted(
            str(p.relative_to(skill_dir)).replace("\\", "/")
            for p in skill_dir.rglob("*")
            if p.is_file() and p.name != "SKILL.md"
        )
        return {
            "ok": True,
            "name": entry.get("name", name),
            "description": entry.get("description", ""),
            "skill_md": _strip_frontmatter(text),
            "files": files,
            "scripts": entry.get("scripts", 0),
            "compatibility": entry.get("compatibility", ""),
            "license": entry.get("license", ""),
        }
