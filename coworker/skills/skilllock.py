"""Read and update the ``npx skills`` global lock file (``~/.agents/.skill-lock.json``).

来源与升级 §5–§8. The lock is another tool's file, so this module is deliberately narrow:

* Reading never raises. An unknown ``version`` or an unreadable file marks every entry
  unsupported instead of guessing at a format we have not seen.
* Writing changes exactly two fields of exactly one entry (``skillFolderHash``,
  ``updatedAt``). The file is re-read right before the write so a concurrent
  ``npx skills`` run is not clobbered, every other key survives untouched, and the result
  lands through a temp file + ``os.replace``.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SUPPORTED_VERSIONS = frozenset({3})
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GITHUB_URL_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_LOCK = threading.Lock()


def lock_path(home: Path) -> Path:
    return home / ".agents" / ".skill-lock.json"


def now_iso() -> str:
    """The lock's own timestamp format (JavaScript's toISOString): ms precision, Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


@dataclass
class LockEntry:
    name: str
    source_type: str
    repo: Optional[str]  # owner/repo when it is a GitHub source we can reach
    folder: str  # skill folder inside the repo, "" = repo root
    folder_hash: str
    ref: str = "HEAD"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def supported(self) -> bool:
        return self.source_type == "github" and bool(self.repo) and bool(self.folder_hash)


@dataclass
class LockFile:
    path: Path
    version: Any = None
    entries: dict[str, LockEntry] = field(default_factory=dict)
    supported: bool = False
    error: str = ""


def _repo_of(raw: dict[str, Any]) -> Optional[str]:
    source = str(raw.get("source") or "").strip()
    if _REPO_RE.match(source):
        return source
    match = _GITHUB_URL_RE.match(str(raw.get("sourceUrl") or "").strip())
    return match.group(1) if match else None


def folder_of(skill_path: str) -> str:
    """``skills/wrangler/SKILL.md`` → ``skills/wrangler``; ``SKILL.md`` → ``""`` (the
    whole repository is the skill)."""
    path = str(skill_path or "").strip().strip("/")
    if path.endswith("SKILL.md"):
        path = path[: -len("SKILL.md")]
    return path.strip("/")


def read_lock(path: Path) -> LockFile:
    out = LockFile(path=path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        out.error = "missing"
        return out
    except (OSError, ValueError) as exc:
        out.error = f"无法读取 {path.name}：{exc}"
        return out
    if not isinstance(data, dict):
        out.error = f"{path.name} 格式不对"
        return out
    out.version = data.get("version")
    out.supported = out.version in SUPPORTED_VERSIONS
    skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    for name, raw in skills.items():
        if not isinstance(raw, dict):
            continue
        ref = str(raw.get("ref") or "").strip()
        out.entries[str(name)] = LockEntry(
            name=str(name),
            source_type=str(raw.get("sourceType") or ""),
            repo=_repo_of(raw),
            folder=folder_of(str(raw.get("skillPath") or "")),
            folder_hash=str(raw.get("skillFolderHash") or ""),
            ref=ref if _REF_RE.match(ref) and ".." not in ref else "HEAD",
            raw=dict(raw),
        )
    if not out.supported:
        out.error = f"不认识的 lock 版本：{out.version!r}"
    return out


def update_entry(
    path: Path, name: str, *, folder_hash: str, updated_at: Optional[str] = None
) -> dict[str, Any]:
    """Point one entry at a new folder hash. Returns the entry as it was BEFORE (for the
    backup's meta, so a rollback can put it back). Raises ValueError when the entry is
    gone or the file is no longer a lock we understand — the caller then reports, the
    skill folder having already been swapped is fine (the next check shows the truth)."""
    with _LOCK:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("version") not in SUPPORTED_VERSIONS:
            raise ValueError("lock 文件的格式变了，没有写回。")
        entry = (data.get("skills") or {}).get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"lock 文件里已经没有 {name} 这一条，没有写回。")
        before = dict(entry)
        entry["skillFolderHash"] = folder_hash
        entry["updatedAt"] = updated_at or now_iso()
        indent = 2
        match = re.search(r"\n( +)\"", text)
        if match:
            indent = len(match.group(1))
        out = json.dumps(data, indent=indent, ensure_ascii=False)
        if text.endswith("\n"):
            out += "\n"
        if "\r\n" in text:
            out = out.replace("\n", "\r\n")
        tmp = path.with_name(path.name + ".openworker.tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
        os.replace(tmp, path)
        return before


def restore_entry(path: Path, name: str, before: dict[str, Any]) -> None:
    """Rollback: put back the two fields `update_entry` changed."""
    update_entry(
        path,
        name,
        folder_hash=str(before.get("skillFolderHash") or ""),
        updated_at=str(before.get("updatedAt") or now_iso()),
    )
