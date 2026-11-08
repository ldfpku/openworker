"""Skill loading — Anthropic SKILL.md format with progressive disclosure.

A skill is a folder containing `SKILL.md` (YAML frontmatter: name, description,
optional allowed-tools) + a markdown body of instructions + optional resources/scripts.

Progressive disclosure: at session start only the catalog (name + description) is injected
into the agent's context; the full body is loaded on demand via the `load_skill` tool.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from stat import S_ISREG
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
    # Claude Code's `disable-model-invocation: true`: the author says this skill runs only
    # when a person asks for it (来源与升级 §3). It never enters the per-turn catalog and
    # load_skill only serves it after the user force-ran it.
    disable_model_invocation: bool = False


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1", "on")


class SkillLoader:
    """The parsed skill catalogue for a set of directories.

    Holds nothing per-session — every field is a pure function of what is on disk — which
    is what lets one loader be shared by every engine built over the same dirs
    (`shared_loader` below). Concurrent `rescan()`s are serialised by `_lock`; readers
    (`get`/`names`/`catalog`) take no lock because a rescan swaps the dict in one
    assignment rather than mutating it in place.
    """

    def __init__(self, dirs: list[str | Path]) -> None:
        self._dirs = [Path(d) for d in dirs]
        self._skills: dict[str, Skill] = {}
        # name → index in `_dirs` of the copy that won. Later dirs win, so a higher index
        # is a higher-priority layer; the catalog budget hands descriptions out by it.
        self._layer: dict[str, int] = {}
        self._fingerprint: Optional[tuple] = None
        self._lock = threading.Lock()
        self.rescan()

    def _dir_fingerprint(self) -> tuple:
        """(path, mtime, size) for every SKILL.md we would read. Cheap: one stat per skill,
        no file reads, no parsing. Catches creation, deletion and edits alike — size is in
        there because a loader now outlives the engine that built it (audit 2026-09-13),
        so an edit landing inside one filesystem mtime tick must not read as "unchanged"."""
        stamps: list[tuple[str, float, int]] = []
        for directory in self._dirs:
            # Runs before `_discover` on every turn, so the same EACCES guard applies here:
            # an unreadable dir is "no skills here", never an abort (upstream 24d51407).
            try:
                if not directory.is_dir():
                    continue
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for sub in entries:
                md = sub / "SKILL.md"
                try:
                    st = md.stat()
                except OSError:  # vanished between listing and stat — next scan sees it
                    continue
                if S_ISREG(st.st_mode):  # the stat we already took, not a second one
                    stamps.append((str(md), st.st_mtime, st.st_size))
        return tuple(stamps)

    def rescan(self, *, force: bool = False) -> None:
        """Re-read the skill dirs when something on disk actually changed.

        `agent.py` calls this once per TURN while building the <system-context> block, and
        once per engine BUILD (the loader is shared across builds, so this is the check
        that replaces the old fresh-loader-per-build full parse). Without the fingerprint
        every round trip re-read and re-parsed every SKILL.md — 163 files of frontmatter to
        produce bytes that are almost always identical. The stat-only check keeps the
        reason it is called per turn (a skill created after the engine was built must still
        be loadable) without paying for it every time. `force=True` skips the check for
        callers that just wrote a skill themselves."""
        with self._lock:
            fingerprint = self._dir_fingerprint()
            if not force and self._skills and fingerprint == self._fingerprint:
                return
            found: dict[str, Skill] = {}
            layer: dict[str, int] = {}
            for index, directory in enumerate(self._dirs):
                before = dict(found)
                self._discover(directory, found)
                for name, skill in found.items():
                    if before.get(name) is not skill:
                        layer[name] = index
            # One assignment each: lock-free readers never see a half-scan.
            self._skills = found
            self._layer = layer
            self._fingerprint = fingerprint

    def _discover(self, directory: Path, into: dict[str, Skill]) -> None:
        """Read one skill dir, best-effort.

        Every filesystem call here is guarded, because `rescan()` runs on EVERY TURN to
        rebuild the live skill menu: a dir that is merely unreadable must degrade to "no
        skills here", never abort the run. Seen in the wild with an agent running headless
        as an unprivileged user — a root-owned `.coworker/` appeared in the workspace
        mid-session and `is_dir()` raised EACCES (pathlib ignores ENOENT/ENOTDIR/EBADF/
        ELOOP but propagates EACCES). Long sessions died outright, some ~100 turns deep,
        over an OPTIONAL dir that was empty anyway.

        Per-skill parsing is guarded separately so one unreadable or malformed folder
        costs only that skill, not the rest of the dir.
        """
        try:
            if not directory.is_dir():
                return
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for sub in entries:
            try:
                md = sub / "SKILL.md"
                if not md.is_file():
                    continue
                skill = _parse_skill(md)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            into[skill.name] = skill

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def priority(self, name: str) -> int:
        """Index of the dir the winning copy came from (higher = higher priority)."""
        return self._layer.get(name, -1)

    def catalog(self) -> list[dict]:
        return [
            {"name": s.name, "description": s.description}
            for s in self._skills.values()
        ]


class LiveLoader:
    """A loader whose directory SET may change while a session runs.

    External sources (来源与升级 §1) are switched on and off in Settings; a session built
    before the switch must see the change from its next message, the same way a skill
    added to an existing dir already does. This delegates to the shared loader for
    whatever `dirs_fn()` returns right now — re-resolved only when the set changes, so the
    per-turn cost stays the stat fingerprint the plain loader already pays.
    """

    def __init__(self, dirs_fn: Callable[[], list]) -> None:
        self._dirs_fn = dirs_fn
        self._key: Optional[tuple[str, ...]] = None
        self._loader: Optional[SkillLoader] = None
        self._lock = threading.Lock()

    def _current(self) -> SkillLoader:
        key = tuple(str(Path(d)) for d in self._dirs_fn())
        with self._lock:
            if key != self._key or self._loader is None:
                self._loader = shared_loader(list(key))
                self._key = key
            return self._loader

    def rescan(self, *, force: bool = False) -> None:
        self._current().rescan(force=force)

    def names(self) -> list[str]:
        return self._current().names()

    def get(self, name: str) -> Optional[Skill]:
        return self._current().get(name)

    def priority(self, name: str) -> int:
        return self._current().priority(name)

    def catalog(self) -> list[dict]:
        return self._current().catalog()


# One loader per directory SET, shared across engine builds (audit 2026-09-13). Before
# this, every build constructed a fresh loader, and a fresh loader's mtime fingerprint can
# never short-circuit — so the draft re-target path re-parsed all 163 SKILL.md files on
# every coworker and folder pick. Sharing is safe precisely because the loader holds no
# per-session state: the per-session view is `skill_filter`, applied at read time.
_SHARED_LOADERS: dict[tuple[str, ...], SkillLoader] = {}
_SHARED_LOCK = threading.Lock()
# A process sees one state dir plus a handful of workspaces; the cap is only there so a
# long-lived server cannot accumulate catalogues for folders visited once.
_MAX_SHARED_LOADERS = 32


def shared_loader(dirs: list[str | Path]) -> SkillLoader:
    """The shared loader for `dirs`, rescanned so a skill written since the last build is
    already there. The cold construction runs under the lock on purpose: two builds racing
    on the same dirs should parse the library once, not twice."""
    key = tuple(str(Path(d)) for d in dirs)
    with _SHARED_LOCK:
        loader = _SHARED_LOADERS.get(key)
        if loader is None:
            if len(_SHARED_LOADERS) >= _MAX_SHARED_LOADERS:
                _SHARED_LOADERS.clear()
            loader = _SHARED_LOADERS[key] = SkillLoader(list(dirs))
            return loader  # __init__ already scanned
    loader.rescan()  # outside the lock — rescan has its own
    return loader


def reset_shared_loaders() -> None:
    """Drop every shared loader. Tests only: callers want the sharing."""
    with _SHARED_LOCK:
        _SHARED_LOADERS.clear()


def _parse_frontmatter(raw: str) -> Optional[dict]:
    """The frontmatter block as a mapping via YAML, or ``None`` when it does not parse
    as one (a hand-written file with a stray tab or an unquoted colon) — the caller then
    falls back to the forgiving line scanner that predates this."""
    try:
        import yaml

        data = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001 — any YAML error → line scanner
        return None
    return data if isinstance(data, dict) else None


def _unquote(value: str) -> str:
    """A frontmatter scalar as its author meant it: YAML-quoted values (the shipped
    library skills quote every description — `description: "How to use…"`) lose their
    quotes and `\"` escapes, so neither the catalog line nor the Settings editor shows
    them. Unquoted values pass through untouched."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        inner = value[1:-1]
        return inner.replace('\\"', '"') if value[0] == '"' else inner.replace("''", "'")
    return value


def _parse_skill(md: Path) -> Skill:
    # Author-written file: one saved in a legacy codepage (ANSI/GBK on a Chinese
    # Windows) must degrade to mojibake, never raise — _discover runs during engine
    # build, so a strict decode here fails every connect to that workspace.
    text = md.read_text(encoding="utf-8", errors="replace")
    name, description, allowed, body = md.parent.name, "", [], text
    manual_only = False
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            parsed = _parse_frontmatter(frontmatter)
            if parsed is not None:
                # Real YAML: folded/literal descriptions (`description: >` — the shipped
                # bids/onekgpd skills) read as their text, not as ">" (audit 2026-09-10).
                if parsed.get("name"):
                    name = str(parsed["name"]).strip() or name
                if parsed.get("description") is not None:
                    description = " ".join(str(parsed["description"]).split())
                tools = parsed.get("allowed-tools", parsed.get("allowed_tools"))
                if isinstance(tools, str):
                    allowed = [t.strip() for t in tools.split(",") if t.strip()]
                elif isinstance(tools, list):
                    allowed = [str(t).strip() for t in tools if str(t).strip()]
                flag = parsed.get(
                    "disable-model-invocation", parsed.get("disable_model_invocation", False)
                )
                manual_only = _truthy(flag)
            else:
                for line in frontmatter.splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key, value = key.strip().lower(), _unquote(value.strip())
                    if key == "name" and value:
                        name = value
                    elif key == "description":
                        description = value
                    elif key in ("allowed-tools", "allowed_tools"):
                        allowed = [t.strip() for t in value.split(",") if t.strip()]
                    elif key in ("disable-model-invocation", "disable_model_invocation"):
                        manual_only = _truthy(value)
    return Skill(
        name=name,
        description=description,
        instructions=body.strip(),
        path=str(md.parent),
        allowed_tools=allowed,
        disable_model_invocation=manual_only,
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


# Total size of the catalog lines (来源与升级 §4). The per-line cap above bounds one skill;
# this bounds what the user has switched on. External sources can bring dozens of skills
# at once, and every char here is paid on every round trip. Under the budget the output is
# exactly what it always was; over it, descriptions go to the highest-priority layers
# first (project → global → persona → external) and the rest are listed by name only —
# still loadable, just without the one-clause hint.
_CATALOG_BUDGET_CHARS = 4000
_CATALOG_HEADER = (
    "Available skills — call load_skill(name) to load one's full instructions when "
    "it's relevant to the task:\n"
)


def skill_catalog_text(
    loader: SkillLoader,
    allowed: Optional[set[str]] = None,
    *,
    budget: int = _CATALOG_BUDGET_CHARS,
) -> str:
    catalog = [
        c
        for c in loader.catalog()
        if (allowed is None or c["name"] in allowed)
        and not _manual_only(loader, c["name"])
    ]
    if not catalog:
        return ""
    lines = [_catalog_line(c["name"], c["description"]) for c in catalog]
    if sum(len(line) + 1 for line in lines) <= budget:
        return _CATALOG_HEADER + "\n".join(lines)
    priority = getattr(loader, "priority", None)
    order = sorted(
        range(len(catalog)),
        key=lambda i: (-(priority(catalog[i]["name"]) if priority else 0), i),
    )
    described: list[str] = []
    names_only: list[str] = []
    used = 0
    for i in order:
        line = lines[i]
        if not names_only and used + len(line) + 1 <= budget:
            described.append(line)
            used += len(line) + 1
        else:
            names_only.append(catalog[i]["name"])
    text = _CATALOG_HEADER + "\n".join(described)
    if names_only:
        text += (
            ("\n" if described else "")
            + "Also available (descriptions omitted to save space — call load_skill(name) "
            "if the name fits the task): "
            + ", ".join(names_only)
        )
    return text


def _manual_only(loader: SkillLoader, name: str) -> bool:
    skill = loader.get(name)
    return bool(skill is not None and skill.disable_model_invocation)


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
    loader: SkillLoader,
    allowed: AllowedSkills = None,
    roots: Optional[list] = None,
    annotate: Optional[Callable[[Skill], dict]] = None,
) -> list:
    """`allowed` gates load_skill: a set is a build-time snapshot; a CALLABLE is consulted
    on every call — the manager passes one so Settings disables apply to live sessions
    immediately, and skills created after the engine was built are still loadable
    (loader rescans on a miss).

    `annotate(skill)` may add fields to a successful result (the origin of an external
    skill, 来源与升级 §8).

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
        if annotate is not None:
            # e.g. origin=external + where it lives (来源与升级 §8): the model should
            # know these instructions came from another tool's folder, not the user.
            out.update(annotate(skill) or {})
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
