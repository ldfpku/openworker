"""Update checks and upgrades for external skills installed by ``npx skills``.

来源与升级 §5–§8. The source of truth for "where did this skill come from" is the
``npx skills`` global lock (``skilllock.py``); GitHub is asked once per repository for its
current tree (``github.py``); local changes are detected per file (``gittree.py``); the
swap itself goes through ``backups.py``.

Check results are cached in ``state_dir()/skills-update-cache.json`` together with the
file lists of locked versions (a tree SHA never changes, so those are kept for good —
bounded in number).
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..secrets import state_dir
from . import backups, gittree, hygiene, skilllock
from .base import _parse_skill
from .external import ExternalSkill, SourceRegistry
from .github import GitHubClient, GitHubError

STALE_AFTER = 24 * 3600
_MAX_CACHED_TREES = 300
_MAX_WORKERS = 4
_SHOWN_CHANGES = 20

UP_TO_DATE = "up_to_date"
AVAILABLE = "available"
MODIFIED = "modified"
BOTH = "modified_and_available"
UNTRACKED = "untracked"
UNSUPPORTED = "unsupported"
UNCHECKED = "unchecked"
ERROR = "error"
UPGRADABLE = frozenset({AVAILABLE, BOTH})


@dataclass
class _Remote:
    sha: str
    files: dict[str, gittree.RemoteFile]
    skipped: list[str] = field(default_factory=list)


def _files_to_json(remote: _Remote) -> dict[str, Any]:
    return {
        "files": {r: [f.sha, f.size] for r, f in remote.files.items()},
        "skipped": remote.skipped,
    }


def _files_from_json(sha: str, data: dict[str, Any]) -> _Remote:
    files = {
        rel: gittree.RemoteFile(rel, str(v[0]), int(v[1]))
        for rel, v in (data.get("files") or {}).items()
        if isinstance(v, list) and len(v) == 2
    }
    return _Remote(sha, files, list(data.get("skipped") or []))


class ExternalUpdater:
    def __init__(
        self,
        sources: SourceRegistry,
        *,
        client_factory: Optional[Callable[[], GitHubClient]] = None,
    ) -> None:
        self.sources = sources
        self._client_factory = client_factory or GitHubClient
        self._lock = threading.Lock()

    # -- paths / cache ----------------------------------------------------------------
    @property
    def cache_path(self) -> Path:
        return state_dir() / "skills-update-cache.json"

    @property
    def lock_path(self) -> Path:
        return skilllock.lock_path(self.sources.home)

    def _read_cache(self) -> dict[str, Any]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("checked_at", None)
        data.setdefault("results", {})
        data.setdefault("trees", {})
        return data

    def _write_cache(self, data: dict[str, Any]) -> None:
        trees = data.get("trees") or {}
        if len(trees) > _MAX_CACHED_TREES:
            data["trees"] = dict(list(trees.items())[-_MAX_CACHED_TREES:])
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_name(self.cache_path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.cache_path)

    def cached(self) -> dict[str, Any]:
        """{checked_at, stale, results} — what Settings shows before (or instead of) a
        fresh check."""
        data = self._read_cache()
        checked = data.get("checked_at")
        stale = not isinstance(checked, (int, float)) or time.time() - checked > STALE_AFTER
        return {"checked_at": checked, "stale": stale, "results": dict(data["results"])}

    # -- local folder resolution ------------------------------------------------------
    def canonical(self, name: str, fallback: Optional[Path] = None) -> Optional[Path]:
        """The folder the lock entry describes: ``~/.agents/skills/<name>`` when it
        exists (where ``npx skills`` keeps its copy), else the folder we found."""
        folder = self.sources.home / ".agents" / "skills" / name
        if (folder / "SKILL.md").is_file():
            return folder.resolve()
        return fallback.resolve() if fallback is not None else None

    # -- remote -----------------------------------------------------------------------
    def _resolve(
        self, client: GitHubClient, repo: str, ref: str, root: dict[str, Any], folder: str
    ) -> Optional[_Remote]:
        """The skill folder's tree SHA and files from a repo's root listing, walking path
        segments when GitHub truncated the recursive listing (huge repositories)."""
        entries = root["tree"]
        truncated = bool(root.get("truncated"))
        if not folder:
            sha = str(root.get("sha") or "")
        else:
            hit = next(
                (e for e in entries if e.get("path") == folder and e.get("type") == "tree"),
                None,
            )
            sha = str(hit["sha"]) if hit else ""
            if not hit and truncated:
                current = str(root.get("sha") or "")
                for segment in folder.split("/"):
                    listing = client.tree(repo, current, recursive=False)
                    step = next(
                        (
                            e
                            for e in listing["tree"]
                            if e.get("path") == segment and e.get("type") == "tree"
                        ),
                        None,
                    )
                    if step is None:
                        return None
                    current = str(step["sha"])
                sha = current
        if not sha:
            return None
        if truncated:
            sub = client.tree(repo, sha, recursive=True)
            if sub.get("truncated"):
                raise GitHubError("too_large", f"{repo} 里的这个技能文件太多，无法检查。")
            files, skipped = gittree.files_under(sub["tree"], "")
        else:
            files, skipped = gittree.files_under(entries, folder)
        return _Remote(sha, files, skipped)

    def _locked_files(
        self, client: GitHubClient, repo: str, sha: str, cache: dict[str, Any]
    ) -> Optional[_Remote]:
        hit = cache["trees"].get(sha)
        if isinstance(hit, dict):
            return _files_from_json(sha, hit)
        try:
            listing = client.tree(repo, sha, recursive=True)
        except GitHubError as exc:
            if exc.kind == "not_found":
                return None
            raise
        if listing.get("truncated"):
            return None
        files, skipped = gittree.files_under(listing["tree"], "")
        remote = _Remote(sha, files, skipped)
        cache["trees"][sha] = _files_to_json(remote)
        return remote

    def _judge(
        self,
        client: GitHubClient,
        entry: skilllock.LockEntry,
        folder: Path,
        remote: _Remote,
        cache: dict[str, Any],
    ) -> dict[str, Any]:
        locked = entry.folder_hash
        out: dict[str, Any] = {
            "origin": "external",
            "repo": entry.repo,
            "current": locked[:7],
            "latest": remote.sha[:7],
            "changes": [],
            "changes_count": 0,
            "local_only_dirs": gittree.has_excluded_content(folder),
        }
        if remote.sha == locked:
            cache["trees"].setdefault(locked, _files_to_json(remote))
            unchanged = gittree.proves_unchanged(folder, locked)
            changes = [] if unchanged else gittree.compare(folder, remote.files)
            out["status"] = MODIFIED if changes else UP_TO_DATE
        elif gittree.proves_unchanged(folder, locked):
            changes = []
            out["status"] = AVAILABLE
        else:
            old = self._locked_files(client, entry.repo or "", locked, cache)
            if old is None:
                changes = ["无法取得已装版本的文件清单，不能确认本地是否改过"]
                out["modified_unknown"] = True
            else:
                changes = gittree.compare(folder, old.files)
            out["status"] = BOTH if changes else AVAILABLE
        out["changes"] = changes[:_SHOWN_CHANGES]
        out["changes_count"] = len(changes)
        return out

    # -- check ------------------------------------------------------------------------
    def check(self, skills: list[ExternalSkill]) -> dict[str, dict[str, Any]]:
        """Check every given external skill; returns name → state and caches it."""
        lock = skilllock.read_lock(self.lock_path)
        now = time.time()
        results: dict[str, dict[str, Any]] = {}
        groups: dict[tuple[str, str], list[tuple[skilllock.LockEntry, Path]]] = {}
        for skill in skills:
            entry = lock.entries.get(skill.name)
            base = {"origin": "external", "checked_at": now}
            if entry is None:
                results[skill.name] = {**base, "status": UNTRACKED}
                continue
            if not lock.supported:
                results[skill.name] = {**base, "status": UNSUPPORTED, "error": lock.error}
                continue
            if not entry.supported:
                results[skill.name] = {
                    **base,
                    "status": UNSUPPORTED,
                    "error": f"来源类型 {entry.source_type or '未知'} 暂不支持检查更新。",
                }
                continue
            folder = self.canonical(skill.name, skill.real_path)
            if folder is None:
                results[skill.name] = {**base, "status": UNTRACKED}
                continue
            groups.setdefault((entry.repo or "", entry.ref), []).append((entry, folder))

        with self._lock:
            cache = self._read_cache()
            if groups:
                with self._client_factory() as client:

                    def run(key):
                        repo, ref = key
                        out: dict[str, dict[str, Any]] = {}
                        try:
                            root = client.tree(repo, ref, recursive=True)
                        except GitHubError as exc:
                            for entry, _folder in groups[key]:
                                out[entry.name] = {
                                    "origin": "external",
                                    "status": ERROR,
                                    "error": str(exc),
                                    "reset_at": exc.reset_at,
                                    "repo": repo,
                                }
                            return out
                        for entry, folder in groups[key]:
                            try:
                                remote = self._resolve(client, repo, ref, root, entry.folder)
                                if remote is None:
                                    out[entry.name] = {
                                        "origin": "external",
                                        "status": ERROR,
                                        "repo": repo,
                                        "error": f"{repo} 里已经没有这个技能（{entry.folder or '/'}）。",
                                    }
                                    continue
                                out[entry.name] = self._judge(client, entry, folder, remote, cache)
                            except GitHubError as exc:
                                out[entry.name] = {
                                    "origin": "external",
                                    "status": ERROR,
                                    "error": str(exc),
                                    "reset_at": exc.reset_at,
                                    "repo": repo,
                                }
                        return out

                    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                        for part in pool.map(run, list(groups)):
                            results.update(part)
            for name, state in results.items():
                state.setdefault("checked_at", now)
                cache["results"][name] = state
            cache["checked_at"] = now
            self._write_cache(cache)
        return results

    # -- apply ------------------------------------------------------------------------
    def apply(self, skill: ExternalSkill, *, overwrite_modified: bool) -> dict[str, Any]:
        """Upgrade one external skill to the remote's current version (来源与升级 §7)."""
        name = skill.name
        lock = skilllock.read_lock(self.lock_path)
        entry = lock.entries.get(name)
        if entry is None or not lock.supported or not entry.supported:
            return {"ok": False, "code": UNSUPPORTED, "error": f"技能 {name} 没有可用的来源记录，不能升级。"}
        target = self.canonical(name, skill.real_path)
        if target is None or not self._inside_a_source(target):
            return {"ok": False, "code": UNSUPPORTED, "error": f"找不到技能 {name} 的安装位置。"}
        with self._lock:
            cache = self._read_cache()
            try:
                with self._client_factory() as client:
                    root = client.tree(entry.repo or "", entry.ref, recursive=True)
                    remote = self._resolve(client, entry.repo or "", entry.ref, root, entry.folder)
                    if remote is None:
                        return {"ok": False, "code": ERROR, "error": f"{entry.repo} 里已经没有这个技能。"}
                    state = self._judge(client, entry, target, remote, cache)
                    if state["status"] in (UP_TO_DATE, MODIFIED):
                        cache["results"][name] = {**state, "checked_at": time.time()}
                        self._write_cache(cache)
                        return {"ok": True, "unchanged": True, "status": state["status"]}
                    if state["status"] == BOTH and not overwrite_modified:
                        return {
                            "ok": False,
                            "code": "modified_requires_confirm",
                            "error": f"技能 {name} 本地改过，确认覆盖后才能升级（旧版本会备份）。",
                            "changes": state["changes"],
                        }
                    staged, skipped = self._download(client, entry, remote)
                    old = self._locked_files(client, entry.repo or "", entry.folder_hash, cache)
            except GitHubError as exc:
                return {"ok": False, "code": ERROR, "error": str(exc)}
            except hygiene.ImportRefused as exc:
                return {"ok": False, "code": "refused", "error": str(exc)}
            try:
                return self._swap(skill, entry, target, staged, skipped, remote, old, cache)
            finally:
                shutil.rmtree(staged, ignore_errors=True)

    def _inside_a_source(self, folder: Path) -> bool:
        for source in self.sources.sources():
            try:
                base = source.path.resolve()
            except OSError:
                continue
            if base in folder.parents:
                return True
        return False

    def _download(
        self, client: GitHubClient, entry: skilllock.LockEntry, remote: _Remote
    ) -> tuple[Path, list[str]]:
        """Fetch every file of the new version into a staging dir, through the same gate
        as an upload: credentials refuse the whole skill, junk is dropped and reported,
        size/count/depth ceilings apply, and each file must hash to what the tree says."""
        keep: list[gittree.RemoteFile] = []
        skipped: list[str] = list(remote.skipped)
        secrets: list[str] = []
        for rel, f in sorted(remote.files.items()):
            verdict, _reason = hygiene.classify(rel)
            if verdict == hygiene.SECRET:
                secrets.append(Path(rel).name)
            elif verdict == hygiene.EXCLUDE:
                skipped.append(rel)
            else:
                keep.append(f)
        hygiene.refuse_secrets(secrets)
        if not any(f.path == "SKILL.md" for f in keep):
            raise hygiene.ImportRefused("新版本里没有 SKILL.md，不像一个技能，没有升级。")
        total = 0
        for f in keep:
            hygiene.check_depth(f.path)
            hygiene.check_file(f.path, f.size)
            total += f.size
        hygiene.check_totals(len(keep), total)
        staged = state_dir() / "skills-staged" / uuid.uuid4().hex
        staged.mkdir(parents=True, exist_ok=True)
        lead = entry.folder + "/" if entry.folder else ""
        try:
            for f in keep:
                data = client.raw(
                    entry.repo or "",
                    entry.ref,
                    lead + f.path,
                    max_bytes=hygiene.LIMITS.max_file_bytes,
                )
                if gittree.blob_sha(data) != f.sha:
                    raise GitHubError(
                        "http", "远端在检查之后又变了，请重新检查更新后再升级。"
                    )
                out = staged / f.path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return staged, skipped

    def _copies(
        self, name: str, target: Path, old: Optional[_Remote]
    ) -> tuple[list[Path], list[str]]:
        """Independent copies of the skill in the other known/custom source folders. A
        link to `target` moves with it; a copy identical to the old version is upgraded
        along; anything else is left alone and reported."""
        update: list[Path] = []
        kept: list[str] = []
        for source in self.sources.sources():
            candidate = source.path / name
            if not (candidate / "SKILL.md").is_file():
                continue
            try:
                real = candidate.resolve()
            except OSError:
                continue
            if real == target or real in update:
                continue
            same = gittree.proves_unchanged(real, old.sha) if old is not None else False
            if not same and old is not None:
                same = not gittree.compare(real, old.files)
            if same:
                update.append(real)
            else:
                kept.append(f"{source.label}：{candidate}（内容和旧版本不同，没有改动）")
        return update, kept

    def _swap(
        self,
        skill: ExternalSkill,
        entry: skilllock.LockEntry,
        target: Path,
        staged: Path,
        skipped: list[str],
        remote: _Remote,
        old: Optional[_Remote],
        cache: dict[str, Any],
    ) -> dict[str, Any]:
        name = skill.name
        installed = _parse_skill(target / "SKILL.md").name
        incoming = _parse_skill(staged / "SKILL.md").name
        if installed != incoming:
            return {
                "ok": False,
                "code": "renamed",
                "error": f"远端技能改名了（{installed} → {incoming}），请用原工具重新安装。",
            }
        copies, kept = self._copies(name, target, old)
        try:
            backup = backups.install_with_backup(
                name,
                [target, *copies],
                staged,
                {
                    "origin": "external",
                    "old_hash": entry.folder_hash,
                    "new_hash": remote.sha,
                    "lock_path": str(self.lock_path),
                },
            )
        except ValueError as exc:
            return {"ok": False, "code": "in_use", "error": str(exc)}
        result: dict[str, Any] = {
            "ok": True,
            "skipped": hygiene.summarize_excluded(skipped) or skipped,
            "copies": [str(c) for c in copies],
            "kept": kept,
            "backup": str(backup),
        }
        try:
            before = skilllock.update_entry(self.lock_path, name, folder_hash=remote.sha)
            meta = backups.read_meta(backup)
            meta["lock_before"] = before
            (backup / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            result["warning"] = f"技能已升级，但 lock 文件没有写回：{exc}"
        cache["results"][name] = {
            "origin": "external",
            "status": UP_TO_DATE,
            "repo": entry.repo,
            "current": remote.sha[:7],
            "latest": remote.sha[:7],
            "changes": [],
            "changes_count": 0,
            "checked_at": time.time(),
        }
        self._write_cache(cache)
        return result

    # -- rollback ---------------------------------------------------------------------
    def rollback(self, name: str) -> dict[str, Any]:
        backup = backups.latest(name, "external")
        if backup is None:
            return {"ok": False, "error": f"技能 {name} 没有可回滚的备份。"}
        meta = backups.restore(name, backup)
        result: dict[str, Any] = {"ok": True}
        before = meta.get("lock_before")
        lock = Path(meta.get("lock_path") or self.lock_path)
        if isinstance(before, dict) and before.get("skillFolderHash"):
            try:
                skilllock.restore_entry(lock, name, before)
            except (OSError, ValueError) as exc:
                result["warning"] = f"文件已回滚，但 lock 文件没有恢复：{exc}"
        with self._lock:
            cache = self._read_cache()
            cache["results"].pop(name, None)
            self._write_cache(cache)
        return result
