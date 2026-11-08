"""Swap skill folders with a backup, and put a backup back (来源与升级 §7).

An upgrade replaces a whole folder; this is the one place that does it, for external
skills (``~/.agents/skills/<name>`` and its independent copies) and library skills alike.

The order of operations is what keeps "all or nothing" true on Windows, where a folder
cannot be renamed while any file in it is open:

1. every target is RENAMED into the backup first — the rename is the gate, it either
   moves the folder whole or fails before a single file is touched;
2. the new content is copied next to its destination and renamed into place;
3. on any failure, whatever was already moved is moved back.

Backups live in ``state_dir()/skills-backups/<name>/<stamp>/`` as numbered folders plus
``meta.json`` (targets, origin, the lock/baseline entry before the change). The newest
``KEEP`` per skill survive.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ..secrets import state_dir
from .store import _delete_refused, _make_deletable

KEEP = 3


def backups_root() -> Path:
    return state_dir() / "skills-backups"


def _cross_volume(exc: OSError) -> bool:
    return exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17


def _remove_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return
    _make_deletable(path)
    shutil.rmtree(path, ignore_errors=True)


def _move(src: Path, dst: Path) -> None:
    """Rename `src` to `dst`; across volumes, copy then rename the original aside and
    delete it. Raises OSError with `src` untouched when the rename is refused (in use)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
        return
    except OSError as exc:
        if not _cross_volume(exc):
            raise
    shutil.copytree(src, dst, symlinks=True)
    aside = src.parent / f".{src.name}.openworker-old-{uuid.uuid4().hex[:8]}"
    try:
        os.rename(src, aside)  # the in-use gate, on the source volume
    except OSError:
        _remove_tree(dst)
        raise
    _remove_tree(aside)


def _place(content: Path, target: Path) -> None:
    """Copy `content` into `target` (which must not exist). The copy is made next to the
    target and renamed in, so the target never exists half-written."""
    tmp = target.parent / f".{target.name}.openworker-new-{uuid.uuid4().hex[:8]}"
    shutil.copytree(content, tmp)
    try:
        os.rename(tmp, target)
    except OSError:
        _remove_tree(tmp)
        raise


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]


def install_with_backup(
    name: str,
    targets: list[Path],
    content: Path,
    meta: dict[str, Any],
) -> Path:
    """Replace every folder in `targets` with a copy of `content`, keeping the old ones in
    a new backup. Missing targets are simply created. Returns the backup dir. Raises
    ValueError (message shown verbatim) with every target as it was."""
    backup = backups_root() / name / _stamp()
    backup.mkdir(parents=True, exist_ok=True)
    parked: list[tuple[Path, Optional[Path]]] = []
    placed: list[Path] = []
    try:
        for i, target in enumerate(targets):
            if target.exists() or target.is_symlink():
                spot = backup / str(i)
                try:
                    _move(target, spot)
                except OSError as exc:
                    raise _delete_refused(name, target, exc, "替换") from exc
                parked.append((target, spot))
            else:
                parked.append((target, None))
            _place(content, target)
            placed.append(target)
    except (OSError, ValueError) as exc:
        for target in placed:
            _remove_tree(target)
        for target, spot in reversed(parked):
            if spot is not None and spot.exists():
                try:
                    _move(spot, target)
                except OSError:
                    pass  # left in the backup dir; the message below says where
        if not any(backup.iterdir()):
            shutil.rmtree(backup, ignore_errors=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"技能 {name} 没有升级成功：{exc}。原文件未改动。") from exc
    record = dict(meta)
    record.update(
        {
            "name": name,
            "created_at": time.time(),
            "targets": [
                {"path": str(t), "backup": (spot.name if spot is not None else None)}
                for t, spot in parked
            ],
        }
    )
    (backup / "meta.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    prune(name)
    return backup


def _dirs(name: str) -> list[Path]:
    root = backups_root() / name
    try:
        return sorted((p for p in root.iterdir() if (p / "meta.json").is_file()), reverse=True)
    except OSError:
        return []


def read_meta(backup: Path) -> dict[str, Any]:
    try:
        data = json.loads((backup / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def latest(name: str, origin: str) -> Optional[Path]:
    for backup in _dirs(name):
        if read_meta(backup).get("origin") == origin:
            return backup
    return None


def prune(name: str, keep: int = KEEP) -> None:
    for old in _dirs(name)[keep:]:
        _remove_tree(old)


def restore(name: str, backup: Path) -> dict[str, Any]:
    """Put `backup` back over its targets and delete it. The current folders are thrown
    away — they are what an upgrade produced and can be fetched again. Returns the meta.
    Raises ValueError with every target as it was when any of them is in use."""
    meta = read_meta(backup)
    targets = [(Path(t["path"]), t.get("backup")) for t in meta.get("targets") or []]
    if not targets:
        raise ValueError(f"技能 {name} 的备份不完整，无法回滚。")
    tomb_root = state_dir() / "skills-deleted"
    tombs: list[tuple[Path, Path]] = []
    try:
        for target, _spot in targets:
            if target.exists() or target.is_symlink():
                tomb = tomb_root / uuid.uuid4().hex
                try:
                    _move(target, tomb)
                except OSError as exc:
                    raise _delete_refused(name, target, exc, "回滚") from exc
                tombs.append((target, tomb))
        for target, spot in targets:
            if spot is not None:
                _move(backup / spot, target)
    except (OSError, ValueError) as exc:
        for target, tomb in reversed(tombs):
            if not target.exists():
                try:
                    _move(tomb, target)
                except OSError:
                    pass
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"技能 {name} 回滚失败：{exc}。") from exc
    for _target, tomb in tombs:
        _remove_tree(tomb)
    _remove_tree(backup)
    return meta
