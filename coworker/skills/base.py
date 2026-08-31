"""Skill loading — Anthropic SKILL.md format with progressive disclosure.

A skill is a folder containing `SKILL.md` (YAML frontmatter: name, description,
optional allowed-tools) + a markdown body of instructions + optional resources/scripts.

Progressive disclosure: at session start only the catalog (name + description) is injected
into the agent's context; the full body is loaded on demand via the `load_skill` tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

import aisuite as ai

from ..roots import RESOURCE_KIND, RootDir


@dataclass
class Skill:
    name: str
    description: str
    instructions: str = ""  # full body — loaded on demand
    path: Optional[str] = None
    allowed_tools: list[str] = field(default_factory=list)


class SkillLoader:
    def __init__(self, dirs: list[str | Path]) -> None:
        self._dirs = [Path(d) for d in dirs]
        self._skills: dict[str, Skill] = {}
        self._fingerprint: Optional[tuple] = None
        self.rescan()

    def _dir_fingerprint(self) -> tuple:
        """(path, mtime) for every SKILL.md we would read. Cheap: one stat per skill, no
        file reads, no parsing. Catches creation, deletion and edits alike."""
        stamps: list[tuple[str, float]] = []
        for directory in self._dirs:
            if not directory.is_dir():
                continue
            for sub in sorted(directory.iterdir()):
                md = sub / "SKILL.md"
                try:
                    if md.is_file():
                        stamps.append((str(md), md.stat().st_mtime))
                except OSError:  # vanished between listing and stat — next scan sees it
                    continue
        return tuple(stamps)

    def rescan(self, *, force: bool = False) -> None:
        """Re-read the skill dirs when something on disk actually changed.

        `agent.py` calls this once per TURN while building the <system-context> block, so
        without the fingerprint every round trip re-read and re-parsed every SKILL.md —
        163 files of frontmatter to produce bytes that are almost always identical. The
        stat-only check keeps the reason it is called per turn (a skill created after the
        engine was built must still be loadable) without paying for it every time.
        `force=True` skips the check for callers that just wrote a skill themselves."""
        fingerprint = self._dir_fingerprint()
        if not force and self._skills and fingerprint == self._fingerprint:
            return
        self._skills = {}
        for directory in self._dirs:
            self._discover(directory)
        self._fingerprint = fingerprint

    def _discover(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for sub in sorted(directory.iterdir()):
            md = sub / "SKILL.md"
            if md.is_file():
                skill = _parse_skill(md)
                self._skills[skill.name] = skill

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def catalog(self) -> list[dict]:
        return [
            {"name": s.name, "description": s.description}
            for s in self._skills.values()
        ]


def _parse_skill(md: Path) -> Skill:
    # Author-written file: one saved in a legacy codepage (ANSI/GBK on a Chinese
    # Windows) must degrade to mojibake, never raise — _discover runs during engine
    # build, so a strict decode here fails every connect to that workspace.
    text = md.read_text(encoding="utf-8", errors="replace")
    name, description, allowed, body = md.parent.name, "", [], text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            for line in frontmatter.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key, value = key.strip().lower(), value.strip()
                if key == "name" and value:
                    name = value
                elif key == "description":
                    description = value
                elif key in ("allowed-tools", "allowed_tools"):
                    allowed = [t.strip() for t in value.split(",") if t.strip()]
    return Skill(
        name=name,
        description=description,
        instructions=body.strip(),
        path=str(md.parent),
        allowed_tools=allowed,
    )


# The catalog rides the per-turn <system-context> block, which sits AFTER the last cache
# breakpoint by construction — so every char here is fresh input on every single round
# trip, for the whole session. It also scales linearly with what the user has installed:
# the description is the author's raw frontmatter line, and across the shipped expert
# library those average 413 chars (max 1,042). Install a 163-skill pack and the catalog
# alone would be ~17K tokens per turn — more than the system prompt and the entire tool
# catalogue combined.
#
# A catalog line has exactly one job: let the model decide whether to call
# load_skill(name). The full instructions arrive on that call. One clause is enough for
# that decision; the rest is paid every turn to say nothing new.
_CATALOG_DESCRIPTION_CHARS = 160


def _catalog_line(name: str, description: str) -> str:
    text = " ".join((description or "").split())  # authors wrap; the catalog shouldn't
    if len(text) > _CATALOG_DESCRIPTION_CHARS:
        cut = text.rfind(" ", 0, _CATALOG_DESCRIPTION_CHARS)
        text = text[: cut if cut > _CATALOG_DESCRIPTION_CHARS // 2 else _CATALOG_DESCRIPTION_CHARS] + "…"
    return f"- {name}: {text}"  # shape unchanged from before the cap — only length


def skill_catalog_text(
    loader: SkillLoader, allowed: Optional[set[str]] = None
) -> str:
    catalog = [
        c for c in loader.catalog() if allowed is None or c["name"] in allowed
    ]
    if not catalog:
        return ""
    lines = [_catalog_line(c["name"], c["description"]) for c in catalog]
    return (
        "Available skills — call load_skill(name) to load one's full instructions when "
        "it's relevant to the task:\n" + "\n".join(lines)
    )


AllowedSkills = Union[set, Callable[[], set], None]


_MAX_LISTED_FILES = 200


def _bundled_files(folder: Path) -> list[str]:
    """The skill's bundled resources, relative and forward-slashed. SKILL.md itself is
    excluded (its body is already in the result) and the list is capped — a skill with
    hundreds of assets must not turn one tool result into a wall of filenames."""
    try:
        found = sorted(
            p.relative_to(folder).as_posix()
            for p in folder.rglob("*")
            if p.is_file() and p.name not in ("SKILL.md", "SKILL.zh.md")
        )
    except OSError:
        return []
    return found[:_MAX_LISTED_FILES]


def skill_tools(
    loader: SkillLoader, allowed: AllowedSkills = None, roots: Optional[list] = None
) -> list:
    """`allowed` gates load_skill: a set is a build-time snapshot; a CALLABLE is consulted
    on every call — the manager passes one so Settings disables apply to live sessions
    immediately, and skills created after the engine was built are still loadable
    (loader rescans on a miss).

    `roots` is the session's shared roots list. Loading a skill appends that skill's
    folder to it as a read-only RESOURCE root, which is what makes the bundled
    references/scripts actually readable: before this, load_skill returned a
    `resources_path` outside every root, so the very next `read_file` on it answered
    "path escapes the session's directories" and the skill's own instructions were
    unfollowable. Only the skill the agent actually loaded is mounted — not the skills
    directory — and resource roots are never persisted or shown as user folders.
    """

    def _allowed_now() -> Optional[set]:
        return allowed() if callable(allowed) else allowed

    def _mount(folder: Path) -> bool:
        """Add the skill's folder as a read-only resource root. False when there is no
        roots list to mount into (a surface without one) — the caller then says so."""
        if roots is None:
            return False
        resolved = folder.expanduser().resolve()
        for r in roots:
            if Path(str(getattr(r, "path", r))).expanduser().resolve() == resolved:
                return True  # already mounted (this skill was loaded before)
        roots.append(
            RootDir(
                path=resolved,
                writable=False,
                label=f"skill:{resolved.name}",
                kind=RESOURCE_KIND,
            )
        )
        return True

    def load_skill(name: str) -> dict:
        """Load a skill's full instructions + resources path by name. Call this when a
        skill from the catalog is relevant to the current task."""
        skill = loader.get(name)
        if skill is None:
            # Created after this session started? Pick it up now. Forced past the
            # fingerprint check: a miss is the one moment we positively expect the disk
            # to have changed, and a same-second write can land on an unchanged mtime.
            loader.rescan(force=True)
            skill = loader.get(name)
        gate = _allowed_now()
        if skill is None or (gate is not None and name not in gate):
            available = sorted(
                n for n in loader.names() if gate is None or n in gate
            )
            return {"error": f"unknown skill: {name}", "available": available}
        out: dict = {
            "name": skill.name,
            "instructions": skill.instructions,
            "resources_path": skill.path,
        }
        if skill.path:
            folder = Path(skill.path)
            files = _bundled_files(folder)
            if files:
                out["files"] = files
                out["note"] = (
                    "The paths in `files` are relative to `resources_path`; join them "
                    "onto it and read them like any other file."
                )
            if not _mount(folder):
                out["note"] = (
                    "This surface has no directory list, so the bundled files under "
                    "`resources_path` may not be readable with the file tools."
                )
        return out

    return [
        ai.tool(
            load_skill,
            metadata=ai.ToolMetadata(
                category="skills", risk_level="low", capabilities=["load_skill"]
            ),
        )
    ]
