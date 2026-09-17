"""Workspace roots — the directories a session is allowed to touch.

A Cowork session is "orphan": it owns a per-conversation **scratch** dir (the primary root,
writable, the default save location) and may gain access to additional folders, each chosen
read-only or read-write. The same `list[RootDir]` object is shared by reference across the
PermissionEngine (scoping), the file toolkit (resolution), and the context injector (so the
agent is told which dirs it has), so Slice C can mutate it in place at runtime and all three
see the change. Index 0 is always the primary.

Two KINDS of root share the list. A ``folder`` root is a directory the USER chose — it is
listed in the roots context, shown in the GUI's Access panel, and persisted with the
session. A ``resource`` root is one a loaded skill brought with it (its bundled
references/scripts): read-only, added by ``load_skill``, and deliberately invisible
everywhere a *user's* folders are shown — it is not something the user granted, it should
not survive the session, and it should not pad the context. Both kinds are equally
readable, which is the whole point: before this, ``load_skill`` handed the agent a
``resources_path`` that ``read_file`` then refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

FOLDER_KIND = "folder"  # a directory the user granted
RESOURCE_KIND = "resource"  # a loaded skill's bundled files (read-only, session-local)


@dataclass
class RootDir:
    path: Path
    writable: bool = False
    label: str = ""  # display name; defaults to the dir's basename
    kind: str = FOLDER_KIND

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser().resolve()
        if not self.label:
            self.label = self.path.name or str(self.path)

    @property
    def is_resource(self) -> bool:
        return self.kind == RESOURCE_KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "writable": self.writable,
            "label": self.label,
            "kind": self.kind,
        }


def user_roots(roots: Iterable[Any] | None) -> list[Any]:
    """The user's own folders — everything except skill-resource roots. Use this wherever
    roots are shown to or saved for the user (Access panel, persistence, roots context)."""
    return [r for r in roots or [] if getattr(r, "kind", FOLDER_KIND) != RESOURCE_KIND]


def resolved_paths(roots: Iterable[Any] | None) -> list[Path]:
    """Just the resolved directories of a mixed roots list — for the read-side tools, which
    care where they may look, not who may write.

    Call this on EVERY resolution, never once at build time: the roots list is shared and
    mutated in place when the user grants a folder mid-session, while a tool closure lives
    as long as its (cached, per-session) engine. A snapshot goes stale the moment a grant
    lands, and the tool then refuses a folder the user just approved.
    """
    out: list[Path] = []
    for r in roots or []:
        if isinstance(r, dict):
            p = r.get("path", "")
        elif isinstance(r, (str, Path)):
            p = r
        else:  # duck-typed RootDir-like
            p = getattr(r, "path", "")
        if p:
            out.append(Path(str(p)).expanduser().resolve())
    return out


def normalize_roots(roots: Iterable[Any] | None) -> list[RootDir]:
    """Coerce a mixed list (RootDir | dict{path,writable,label} | str/Path) into RootDirs.
    Bare str/Path entries are treated as read-only; pass dicts/RootDirs to grant write.
    """
    out: list[RootDir] = []
    for r in roots or []:
        if isinstance(r, RootDir):
            out.append(r)
        elif isinstance(r, dict):
            out.append(
                RootDir(
                    path=r["path"],
                    writable=bool(r.get("writable", False)),
                    label=r.get("label", ""),
                    kind=str(r.get("kind") or FOLDER_KIND),
                )
            )
        elif isinstance(r, (str, Path)):
            out.append(RootDir(path=r, writable=False))
        else:  # duck-typed object with .path/.writable
            out.append(
                RootDir(
                    path=getattr(r, "path"),
                    writable=bool(getattr(r, "writable", False)),
                    kind=str(getattr(r, "kind", FOLDER_KIND) or FOLDER_KIND),
                )
            )
    return out


def render_context(roots: list[RootDir]) -> str:
    """The `<system-context>` body listing the dirs available this turn. Empty when no roots.

    Skill-resource roots are left out on purpose: `load_skill` already told the agent that
    skill's path and what it bundles, and repeating every loaded skill's folder here would
    grow a block that rides on EVERY turn.
    """
    roots = user_roots(roots)
    if not roots:
        return ""
    lines = ["Available directories (you may use file/shell tools within these):"]
    has_side_scratch = any(i > 0 and r.label == "scratch" for i, r in enumerate(roots))
    for i, r in enumerate(roots):
        access = "read-write" if r.writable else "read-only"
        if i == 0 and r.label == "scratch":
            tag = " — primary scratch, the default place to save files"
        elif i == 0:
            tag = " — the session's workspace (relative paths resolve here)"
        elif r.label == "scratch":
            tag = (
                " — your scratch directory: temporary files, and artifacts you don't "
                "want to leave inside the workspace"
            )
        else:
            tag = ""
        lines.append(f"- {r.path} [{access}]{tag}")
    if has_side_scratch:
        # Where files go is unchanged; what this block CLAIMS is not. It used to say
        # deliverables in scratch "appear in the user's Artifacts panel" while relative
        # paths quietly resolved to the workspace — so a model that wrote `report.csv`
        # left it in the workspace and then announced it had reached a panel that was, in
        # fact, empty. There is no sync tool and never was; the panel reads both
        # directories now (SessionManager.list_artifacts). Every turn pays for these lines
        # in full — they sit after the prompt-cache breakpoint — so each one earns its
        # place: where paths land, where deliverables go, what the panel does, and not
        # claiming a file no tool result confirmed.
        lines.append(
            "Relative paths resolve against the workspace and the shell starts there; use "
            "absolute paths elsewhere, scratch included. Writes need read-write access."
        )
        lines.append(
            "Put reports, analyses and other non-repo deliverables in scratch; use the "
            "workspace only for changes that belong in it."
        )
        lines.append(
            # "not code or JSON": outside scratch the panel keeps to documents and media —
            # a workspace is usually the user's own project (see
            # manager._SESSION_ARTIFACT_SUFFIXES).
            "The Artifacts panel lists documents (not code or JSON) you make this session "
            "in either directory; no sync or publish step exists."
        )
        lines.append(
            # Only `write_file` is wrapped to report an absolute path; `replace_in_file`
            # and the patch tools still answer with a workspace-relative name. So: always
            # GIVE an absolute path, and quote the tool's when the tool supplied one.
            "Give file locations as absolute paths, quoting the tool's own when it reports "
            "one. Never claim a file exists, or was copied or moved, unless a tool result "
            "confirms it; say so when a command fails."
        )
    else:
        lines.append(
            "Relative paths resolve against the primary directory; pass an absolute path to use "
            "another directory. Writes are only allowed in read-write directories. If the user "
            "cares where a deliverable lands, ask; otherwise save it in the primary scratch."
        )
    return "\n".join(lines)
