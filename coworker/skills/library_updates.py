"""Version baseline and upgrades for skills installed from the built-in library.

来源与升级 §5, §7. The library pack ships with the app and changes with every release; an
installed library skill is a COPY in the global skills dir. Without a record of what was
copied, "the app's library has a newer version" and "the person edited their copy" look
identical. So every install writes a baseline (``state_dir()/skills-library-lock.json``:
the per-file blob SHAs of what landed), and the state of a skill is the comparison of
three file lists — installed, baseline, current pack. No network involved.

A skill installed before baselines existed has none: if it equals the current pack the
baseline is written silently; otherwise it is reported as "update available, may be
modified" and goes through the confirm step like any modified skill.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .. import __version__ as APP_VERSION
from ..secrets import state_dir
from . import backups, gittree, hygiene
from .updates import AVAILABLE, BOTH, MODIFIED, UP_TO_DATE

_TRANSLATION = "SKILL.zh.md"  # library-browsing layer, never installed


def manifest(folder: Path) -> dict[str, str]:
    """rel → blob SHA under the SAME rules the library install copies with: hygiene's
    copytree ignore (junk dirs/files, credentials) plus the translation layer."""
    excluded_dirs = {d.lower() for d in hygiene.EXCLUDED_DIRS}
    out: dict[str, str] = {}
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d.lower() not in excluded_dirs)
        for name in names:
            if name == _TRANSLATION:
                continue
            if hygiene._name_matches(name, hygiene.EXCLUDED_FILES) or hygiene._name_matches(
                name, hygiene.SECRET_FILES
            ):
                continue
            path = Path(root) / name
            if path.is_symlink():
                continue
            try:
                out[path.relative_to(folder).as_posix()] = gittree.blob_sha(path.read_bytes())
            except OSError:
                continue
    return out


def _diff(have: dict[str, str], want: dict[str, str]) -> list[str]:
    out = [f"改动 {r}" for r in sorted(set(have) & set(want)) if have[r] != want[r]]
    out += [f"新增 {r}" for r in sorted(set(have) - set(want))]
    out += [f"缺少 {r}" for r in sorted(set(want) - set(have))]
    return out


def ignore_for_install():
    base = hygiene.copytree_ignore()

    def _ignore(directory: str, names: list[str]) -> set[str]:
        return base(directory, names) | {n for n in names if n == _TRANSLATION}

    return _ignore


class LibraryUpdater:
    def __init__(self, global_dir: Path) -> None:
        self.global_dir = Path(global_dir)
        self._lock = threading.Lock()
        self._pack_cache: dict[tuple[str, int], dict[str, str]] = {}

    @property
    def path(self) -> Path:
        return state_dir() / "skills-library-lock.json"

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
            data = {"version": 1, "skills": {}}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def baseline(self, name: str) -> Optional[dict[str, Any]]:
        entry = self._read()["skills"].get(name)
        return entry if isinstance(entry, dict) else None

    def record(self, name: str, folder: Path) -> dict[str, Any]:
        """Write the baseline for what is installed at `folder` right now. Returns the
        entry it replaced (None when there was none) — the backup keeps it for rollback."""
        with self._lock:
            data = self._read()
            before = data["skills"].get(name)
            data["skills"][name] = {
                "files": manifest(folder),
                "installed_at": time.time(),
                "app_version": APP_VERSION,
            }
            self._write(data)
            return before

    def restore_baseline(self, name: str, before: Optional[dict[str, Any]]) -> None:
        with self._lock:
            data = self._read()
            if before is None:
                data["skills"].pop(name, None)
            else:
                data["skills"][name] = before
            self._write(data)

    def _pack_manifest(self, pack_root: Path, name: str) -> Optional[dict[str, str]]:
        """The pack copy's manifest, re-hashed only when a file in it changed (a stat walk
        per call; the pack is read-only, so in practice this hashes once per app run)."""
        src = pack_root / "skills" / name
        if not (src / "SKILL.md").is_file():
            return None
        stamps: list[tuple[str, int, int]] = []
        for root, _dirs, files in os.walk(src):
            for f in files:
                try:
                    st = (Path(root) / f).stat()
                except OSError:
                    continue
                stamps.append((os.path.join(root, f), st.st_mtime_ns, st.st_size))
        key = (str(src), hash(tuple(sorted(stamps))))
        hit = self._pack_cache.get(key)
        if hit is None:
            hit = manifest(src)
            if len(self._pack_cache) > 512:
                self._pack_cache.clear()
            self._pack_cache[key] = hit
        return hit

    def states(self, pack_root: Optional[Path], names: set[str]) -> dict[str, dict[str, Any]]:
        """name → state for every installed skill that the pack also ships."""
        if pack_root is None:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for name in sorted(names):
            folder = self.global_dir / name
            if not (folder / "SKILL.md").is_file():
                continue
            pack = self._pack_manifest(pack_root, name)
            if pack is None:
                continue
            installed = manifest(folder)
            state: dict[str, Any] = {"origin": "library", "changes": [], "changes_count": 0}
            if installed == pack:
                base = self.baseline(name)
                if base is None or base.get("files") != pack:
                    self.record(name, folder)
                state["status"] = UP_TO_DATE
                out[name] = state
                continue
            base = self.baseline(name)
            if base is None:
                state["status"] = BOTH
                state["modified_unknown"] = True
                changes = ["这个技能安装时还没有版本记录，不能确认本地是否改过"]
            else:
                files = base.get("files") or {}
                modified = installed != files
                available = pack != files
                changes = _diff(installed, files) if modified else []
                state["status"] = (
                    BOTH if modified and available else MODIFIED if modified else AVAILABLE
                )
            state["changes"] = changes[:20]
            state["changes_count"] = len(changes)
            out[name] = state
        return out

    def install(self, name: str, src: Path, *, replace: bool) -> dict[str, Any]:
        """Copy the pack's `src` into the global dir. An existing copy is replaced through
        a backup (so "restore the original" and "upgrade" can both be rolled back), and
        the baseline is rewritten. Raises ValueError with the folder untouched when the
        old copy cannot be moved (in use)."""
        dest = self.global_dir / name
        staged = state_dir() / "skills-staged" / uuid.uuid4().hex
        shutil.copytree(src, staged, ignore=ignore_for_install())
        try:
            if dest.exists() or dest.is_symlink():
                if not replace:
                    raise ValueError("already installed")
                before = self.baseline(name)
                backup = backups.install_with_backup(
                    name, [dest], staged, {"origin": "library", "baseline_before": before}
                )
                self.record(name, dest)
                return {"ok": True, "replaced": True, "backup": str(backup)}
            self.global_dir.mkdir(parents=True, exist_ok=True)
            backups._place(staged, dest)
            self.record(name, dest)
            return {"ok": True}
        finally:
            shutil.rmtree(staged, ignore_errors=True)

    def rollback(self, name: str) -> dict[str, Any]:
        backup = backups.latest(name, "library")
        if backup is None:
            return {"ok": False, "error": f"技能 {name} 没有可回滚的备份。"}
        meta = backups.restore(name, backup)
        self.restore_baseline(name, meta.get("baseline_before"))
        return {"ok": True}
