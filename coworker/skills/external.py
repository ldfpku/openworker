"""External skill sources — skills other agent tools installed on this machine.

来源与升级 §1–§3 (docs/规划/2026-11-08-本机技能接入与升级方案.md). People who use
``npx skills``, Claude Code, Kiro, Codex… already have skills under their home folder.
This module lets the app use those folders IN PLACE, read-only:

* Only user-level folders are scanned (``~/.agents/skills``, ``~/.claude/skills``, …) plus
  folders the person adds. Project folders such as ``<repo>/.claude/skills`` are never
  scanned: anyone's repository could plant instructions there.
* Every source starts OFF. Switching one on is the person's decision.
* The same skill reached through several sources (``~/.claude/skills/x`` is often a link
  to ``~/.agents/skills/x``) counts once; a different skill with a name already taken by
  an earlier source is shadowed.
* External skills default to manual invocation — they stay out of the per-turn catalog
  and only load when the user force-runs them — because a folder of 30 skills someone
  installed for a coding agent should not cost every conversation here 5,000 chars.

State lives in ``state_dir()/skill-sources.json``: which sources are on, the custom
folders, and each skill's invocation mode. Nothing here ever writes into a source folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..secrets import state_dir
from .base import shared_loader

AUTO = "auto"
MANUAL = "manual"
_MODES = (AUTO, MANUAL)


@dataclass(frozen=True)
class SourceInfo:
    id: str
    label: str
    path: Path
    custom: bool = False


# Global skill folders per agent, from vercel-labs/skills docs/agents.md. Order is the
# priority among external sources (来源与升级 §2): the shared `.agents` folder first, since
# it is where `npx skills` keeps the canonical copy the others usually link to.
KNOWN_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("agents", "Agents (npx skills)", ".agents/skills"),
    ("claude-code", "Claude Code", ".claude/skills"),
    ("kiro", "Kiro", ".kiro/skills"),
    ("codex", "Codex", ".codex/skills"),
    ("cursor", "Cursor", ".cursor/skills"),
    ("gemini-cli", "Gemini CLI", ".gemini/skills"),
    ("opencode", "OpenCode", ".config/opencode/skills"),
)


def skill_home() -> Path:
    """The home folder the known sources hang off. `COWORKER_SKILL_HOME` exists for tests
    and sandboxes, which must never read the developer's real agent folders."""
    override = os.environ.get("COWORKER_SKILL_HOME")
    return Path(override).expanduser() if override else Path.home()


@dataclass
class ExternalSkill:
    name: str
    description: str
    path: Path  # the folder as found under its source
    real_path: Path  # links resolved — the identity used for de-duplication
    source_id: str
    source_label: str
    disable_model_invocation: bool = False
    also_in: list[str] = field(default_factory=list)  # other sources reaching the same folder
    shadows: list[str] = field(default_factory=list)  # later sources whose same-name copy lost


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def _count_skills(directory: Path) -> int:
    try:
        if not directory.is_dir():
            return 0
        return sum(1 for sub in directory.iterdir() if (sub / "SKILL.md").is_file())
    except OSError:
        return 0


class SourceRegistry:
    """Known + custom sources, their on/off state, and per-skill invocation modes."""

    def __init__(
        self,
        path: Optional[str | Path] = None,
        *,
        home: Optional[str | Path] = None,
    ) -> None:
        self.path = Path(path) if path else state_dir() / "skill-sources.json"
        self._home = Path(home) if home else None
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()

    @property
    def home(self) -> Path:
        return self._home if self._home is not None else skill_home()

    # -- persistence ----------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        enabled = data.get("enabled") if isinstance(data.get("enabled"), dict) else {}
        custom = data.get("custom") if isinstance(data.get("custom"), list) else []
        invocation = data.get("invocation") if isinstance(data.get("invocation"), dict) else {}
        return {
            "enabled": {str(k): bool(v) for k, v in enabled.items()},
            "custom": [
                {"id": str(c["id"]), "label": str(c.get("label") or ""), "path": str(c["path"])}
                for c in custom
                if isinstance(c, dict) and c.get("id") and c.get("path")
            ],
            "invocation": {
                str(k): str(v) for k, v in invocation.items() if str(v) in _MODES
            },
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- sources --------------------------------------------------------------------
    def sources(self) -> list[SourceInfo]:
        home = self.home
        out = [SourceInfo(sid, label, home / rel) for sid, label, rel in KNOWN_SOURCES]
        for c in self._data["custom"]:
            path = Path(c["path"])
            out.append(SourceInfo(c["id"], c["label"] or path.name, path, custom=True))
        return out

    def get(self, source_id: str) -> Optional[SourceInfo]:
        return next((s for s in self.sources() if s.id == source_id), None)

    def is_enabled(self, source_id: str) -> bool:
        return bool(self._data["enabled"].get(source_id, False))

    def set_enabled(self, source_id: str, enabled: bool) -> SourceInfo:
        source = self.get(source_id)
        if source is None:
            raise ValueError(f"没有这个技能来源：{source_id}")
        with self._lock:
            if enabled:
                self._data["enabled"][source_id] = True
            else:
                self._data["enabled"].pop(source_id, None)
            self._save()
        return source

    def add_custom(self, path: str, label: str = "") -> SourceInfo:
        raw = str(path or "").strip()
        if not raw:
            raise ValueError("请选择一个文件夹。")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("请填写完整路径（绝对路径）。")
        if not candidate.is_dir():
            raise ValueError(f"文件夹不存在：{raw}")
        resolved = _safe_resolve(candidate)
        if resolved.parent == resolved:
            raise ValueError("不能把整个磁盘设为技能来源，请选具体的技能文件夹。")
        if resolved == _safe_resolve(self.home):
            raise ValueError("不能把整个用户目录设为技能来源，请选具体的技能文件夹。")
        own = _safe_resolve(state_dir())
        if resolved == own or own in resolved.parents or resolved in own.parents:
            raise ValueError("这是本程序自己的数据目录，里面的技能已经在用了。")
        for existing in self.sources():
            if _safe_resolve(existing.path) == resolved:
                raise ValueError(f"这个文件夹已经是技能来源了：{existing.label}")
        source_id = "custom-" + hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
        clean_label = " ".join(str(label or "").split())[:60] or resolved.name
        with self._lock:
            self._data["custom"].append(
                {"id": source_id, "label": clean_label, "path": str(resolved)}
            )
            # Adding a folder by hand is already the person's opt-in.
            self._data["enabled"][source_id] = True
            self._save()
        return SourceInfo(source_id, clean_label, resolved, custom=True)

    def remove_custom(self, source_id: str) -> None:
        with self._lock:
            before = len(self._data["custom"])
            self._data["custom"] = [c for c in self._data["custom"] if c["id"] != source_id]
            if len(self._data["custom"]) == before:
                if self.get(source_id) is not None:
                    raise ValueError("内置来源不能移除，可以把它关掉。")
                raise ValueError(f"没有这个技能来源：{source_id}")
            self._data["enabled"].pop(source_id, None)
            self._save()

    def enabled_sources(self) -> list[SourceInfo]:
        return [s for s in self.sources() if self.is_enabled(s.id)]

    def enabled_dirs(self) -> list[Path]:
        """Enabled source folders, highest external priority FIRST."""
        return [s.path for s in self.enabled_sources()]

    def loader_dirs(self) -> list[Path]:
        """Enabled source folders in loader order: lowest priority first, because the
        loader lets later dirs overwrite earlier ones (来源与升级 §2)."""
        return list(reversed(self.enabled_dirs()))

    def describe(self) -> list[dict[str, Any]]:
        """Rows for Settings. Counts are a stat-only scan, also for sources that are off —
        the person needs to see what switching one on would bring in."""
        rows = []
        for s in self.sources():
            try:
                exists = s.path.is_dir()
            except OSError:
                exists = False
            rows.append(
                {
                    "id": s.id,
                    "label": s.label,
                    "path": str(s.path),
                    "exists": exists,
                    "count": _count_skills(s.path) if exists else 0,
                    "enabled": self.is_enabled(s.id),
                    "custom": s.custom,
                }
            )
        return rows

    # -- skills ---------------------------------------------------------------------
    def discover(self) -> list[ExternalSkill]:
        """The effective external skills of the enabled sources, de-duplicated by real
        path, first source wins on a name clash. Parsing goes through the shared loader
        per folder, so repeated calls cost a stat fingerprint, not a re-parse."""
        by_name: dict[str, ExternalSkill] = {}
        by_real: dict[Path, ExternalSkill] = {}
        for source in self.enabled_sources():
            try:
                loader = shared_loader([source.path])
            except OSError:
                continue
            for name in loader.names():
                skill = loader.get(name)
                if skill is None or not skill.path:
                    continue
                folder = Path(skill.path)
                real = _safe_resolve(folder)
                seen = by_real.get(real)
                if seen is not None:
                    if source.id not in seen.also_in and source.id != seen.source_id:
                        seen.also_in.append(source.id)
                    continue
                if name in by_name:
                    winner = by_name[name]
                    if source.id not in winner.shadows:
                        winner.shadows.append(source.id)
                    continue
                entry = ExternalSkill(
                    name=name,
                    description=skill.description,
                    path=folder,
                    real_path=real,
                    source_id=source.id,
                    source_label=source.label,
                    disable_model_invocation=skill.disable_model_invocation,
                )
                by_name[name] = entry
                by_real[real] = entry
        return list(by_name.values())

    def find(self, name: str) -> Optional[ExternalSkill]:
        return next((s for s in self.discover() if s.name == name), None)

    # -- invocation modes (来源与升级 §3) ----------------------------------------------
    def invocation(self, name: str) -> str:
        return self._data["invocation"].get(name, MANUAL)

    def set_invocation(self, name: str, mode: str) -> None:
        mode = str(mode or "").strip()
        if mode not in _MODES:
            raise ValueError("调用方式只能是 auto 或 manual。")
        with self._lock:
            if mode == MANUAL:
                self._data["invocation"].pop(name, None)  # manual is the default
            else:
                self._data["invocation"][name] = mode
            self._save()
