"""Git object hashing and GitHub tree listings for skill update checks (来源与升级 §6, §8).

``npx skills`` records each installed skill's folder as the GitHub *tree* SHA it came from
(``skillFolderHash``). Deciding "is there an update" is one tree listing per repository;
deciding "did the person change their copy" means comparing the local files with the
locked version's file list, blob by blob.

Two things make a byte-exact comparison lie on Windows, both seen on a real machine:

* a clone made with ``core.autocrlf`` writes text files with CRLF, so every blob differs
  although nobody touched them — each file is therefore also compared with CRLF folded
  to LF;
* executable bits do not exist on NTFS, so a locally recomputed tree SHA never matches a
  folder that ships a ``100755`` script. The local tree hash is only a shortcut that can
  prove "unchanged"; when it does not match, the per-file comparison decides.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from . import hygiene

LINK_MODE = "120000"
SUBMODULE_TYPE = "commit"


def blob_sha(data: bytes) -> str:
    """Git's blob id: sha1 over ``"blob <size>\\0" + content``."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def blob_matches(data: bytes, sha: str) -> bool:
    if blob_sha(data) == sha:
        return True
    return b"\r\n" in data and blob_sha(data.replace(b"\r\n", b"\n")) == sha


def safe_relpath(rel: str) -> bool:
    """A tree path we are willing to write under a skill folder."""
    if not rel or "\\" in rel or "\0" in rel:
        return False
    parts = PurePosixPath(rel).parts
    if PurePosixPath(rel).is_absolute() or not parts:
        return False
    return not any(p in ("", ".", "..") or ":" in p for p in parts)


@dataclass(frozen=True)
class RemoteFile:
    path: str  # relative to the skill folder, forward slashes
    sha: str
    size: int


def files_under(
    entries: list[dict], prefix: str
) -> tuple[dict[str, RemoteFile], list[str]]:
    """The blobs of a recursive tree listing that sit under ``prefix`` ("" = all), keyed
    by path relative to it, plus what was skipped and why. Links and submodules are never
    written into a skill folder (§8): a link can point anywhere on the machine."""
    base = prefix.strip("/")
    lead = base + "/" if base else ""
    files: dict[str, RemoteFile] = {}
    skipped: list[str] = []
    for entry in entries:
        path = str(entry.get("path", ""))
        if lead and not path.startswith(lead):
            continue
        rel = path[len(lead):]
        kind = entry.get("type")
        if kind == "tree":
            continue
        if kind == SUBMODULE_TYPE:
            skipped.append(f"{rel}（子模块）")
            continue
        if kind != "blob":
            continue
        if entry.get("mode") == LINK_MODE:
            skipped.append(f"{rel}（链接）")
            continue
        if not safe_relpath(rel):
            skipped.append(f"{rel}（路径不安全）")
            continue
        files[rel] = RemoteFile(rel, str(entry.get("sha", "")), int(entry.get("size") or 0))
    return files, skipped


def _walk(folder: Path):
    """(relpath, path) for every regular file, pruning hygiene-excluded directories
    (a locally installed node_modules can be tens of thousands of files)."""
    excluded = {d.lower() for d in hygiene.EXCLUDED_DIRS}
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if d.lower() not in excluded]
        for name in names:
            path = Path(root) / name
            if path.is_symlink():
                continue
            yield path.relative_to(folder).as_posix(), path


def compare(folder: Path, remote: dict[str, RemoteFile]) -> list[str]:
    """How the local folder differs from a remote file list, as short lines ("改动 x",
    "缺少 y", "新增 z"); empty means identical. Only skill content counts on both sides:
    build junk the hygiene gate would drop is ignored, so a local ``npm install`` or a
    ``__pycache__`` is not a modification. Local credential files DO count — an upgrade
    would move them into the backup, and the person must know before that happens."""
    wanted = {
        rel: f for rel, f in remote.items() if hygiene.classify(rel)[0] != hygiene.EXCLUDE
    }
    seen: set[str] = set()
    out: list[str] = []
    for rel, path in _walk(folder):
        if hygiene.classify(rel)[0] == hygiene.EXCLUDE:
            continue
        seen.add(rel)
        f = wanted.get(rel)
        if f is None:
            out.append(f"新增 {rel}")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            out.append(f"无法读取 {rel}")
            continue
        if not blob_matches(data, f.sha):
            out.append(f"改动 {rel}")
    out.extend(f"缺少 {rel}" for rel in sorted(set(wanted) - seen))
    return sorted(out)


def has_excluded_content(folder: Path) -> list[str]:
    """Top-level excluded dirs present locally (e.g. ``node_modules``): an upgrade swaps
    the folder whole, so these do not carry over and the result says so."""
    excluded = {d.lower() for d in hygiene.EXCLUDED_DIRS}
    try:
        return sorted(
            p.name for p in folder.iterdir() if p.is_dir() and p.name.lower() in excluded
        )
    except OSError:
        return []


def local_tree_sha(folder: Path, *, normalize: bool) -> Optional[str]:
    """The git tree SHA this folder would have if every file were mode 100644. Returns
    None when the folder cannot be reproduced as a tree (links inside, unreadable files).
    Only ever used to PROVE a folder unchanged; a mismatch proves nothing (see module
    docstring), so callers fall back to the per-file comparison."""
    result = _tree(folder, normalize)
    return None if result is None else (result or None)


def _tree(folder: Path, normalize: bool) -> Optional[str]:
    entries: list[tuple[bytes, bytes]] = []
    try:
        children = list(folder.iterdir())
    except OSError:
        return None
    for child in children:
        if child.name == ".git":
            continue
        if child.is_symlink():
            return None
        name = child.name.encode("utf-8")
        if child.is_dir():
            sub = _tree(child, normalize)
            if sub is None:
                return None
            if sub == "":
                continue  # git does not track empty directories
            entries.append((name + b"/", b"40000 " + name + b"\0" + bytes.fromhex(sub)))
        else:
            try:
                data = child.read_bytes()
            except OSError:
                return None
            if normalize:
                data = data.replace(b"\r\n", b"\n")
            entries.append((name, b"100644 " + name + b"\0" + bytes.fromhex(blob_sha(data))))
    if not entries:
        return ""
    entries.sort(key=lambda e: e[0])
    body = b"".join(e[1] for e in entries)
    return hashlib.sha1(b"tree %d\0" % len(body) + body).hexdigest()


def proves_unchanged(folder: Path, locked_sha: str) -> bool:
    """True when the folder hashes to `locked_sha` as-is or with CRLF folded to LF."""
    return any(local_tree_sha(folder, normalize=n) == locked_sha for n in (False, True))
