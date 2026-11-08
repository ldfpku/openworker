"""来源与升级 §5–§8 — update checks, upgrades, backups and rollbacks.

External skills run against a fake GitHub on httpx.MockTransport (no network): tree
SHAs are computed with git's real algorithm from the fixture files, so lock hashes,
listings and blob checks agree exactly the way the real service does. Library skills
run against the mini pack of tests/test_library_p2.py."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from coworker.library import LibraryPack, set_pack_for_tests
from coworker.server import SessionManager, create_app
from coworker.skills import backups, reset_shared_loaders
from coworker.skills.external import SourceRegistry, skill_home
from coworker.skills.gittree import blob_sha, local_tree_sha
from coworker.skills.github import GitHubClient
from coworker.skills.updates import ExternalUpdater
from tests.test_library_p2 import _build_pack

REPO = "acme/skills"
SECRET_TOKEN = "ghp_do_not_leak_0123456789"

V1 = {
    "skills/report/SKILL.md": b"---\nname: report\ndescription: Weekly report\n---\n\nv1 body\n",
    "skills/report/scripts/run.py": b"print('v1')\n",
    "skills/other/SKILL.md": b"---\nname: other\ndescription: o\n---\n\nother\n",
    "README.md": b"repo readme\n",
}
V2 = {
    **V1,
    "skills/report/SKILL.md": b"---\nname: report\ndescription: Weekly report\n---\n\nv2 body\n",
    "skills/report/templates/t.md": b"template\n",
}


class FakeGitHub:
    """Serves trees and raw files for a set of repository versions. HEAD = the last."""

    def __init__(self, *versions: dict[str, bytes]) -> None:
        self.trees: dict[str, list[dict]] = {}  # tree sha → recursive entries (relative)
        self.roots: list[str] = []
        self.files = versions[-1]
        self.calls: list[httpx.Request] = []
        self.rate_limited = False
        self.truncate_root = False
        for files in versions:
            self.roots.append(self._index(files))

    def _index(self, files: dict[str, bytes]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, data in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(data)
            dirs = {Path(rel).parent.as_posix() for rel in files} | {"."}
            for rel in list(dirs):
                parts = Path(rel).parts
                for i in range(1, len(parts)):
                    dirs.add(Path(*parts[:i]).as_posix())
            shas = {d: local_tree_sha(root / d, normalize=False) for d in dirs}
            for d, sha in shas.items():
                lead = "" if d == "." else d + "/"
                entries = []
                for sub, sub_sha in shas.items():
                    if sub != "." and sub.startswith(lead) and sub != d:
                        entries.append({"path": sub[len(lead):], "type": "tree", "sha": sub_sha, "mode": "040000"})
                for rel, data in files.items():
                    if rel.startswith(lead):
                        entries.append(
                            {"path": rel[len(lead):], "type": "blob", "sha": blob_sha(data), "size": len(data), "mode": "100644"}
                        )
                self.trees[sha] = entries
            return shas["."]

    def folder_sha(self, version: int, folder: str) -> str:
        root = self.roots[version]
        if not folder:
            return root
        hit = next(e for e in self.trees[root] if e["path"] == folder and e["type"] == "tree")
        return hit["sha"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = request.url
        if self.rate_limited and url.host == "api.github.com":
            return httpx.Response(
                403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1999999999"}
            )
        if url.host == "api.github.com":
            prefix = f"/repos/{REPO}/git/trees/"
            if not url.path.startswith(prefix):
                return httpx.Response(404)
            ref = url.path[len(prefix):]
            sha = self.roots[-1] if ref == "HEAD" else ref
            if sha not in self.trees:
                return httpx.Response(404)
            entries = self.trees[sha]
            recursive = request.url.params.get("recursive") == "1"
            if not recursive:
                entries = [e for e in entries if "/" not in e["path"]]
            truncated = recursive and self.truncate_root and sha == self.roots[-1]
            if truncated:
                entries = [e for e in entries if e["path"].count("/") == 0]
            return httpx.Response(200, json={"sha": sha, "tree": entries, "truncated": truncated})
        if url.host == "raw.githubusercontent.com":
            path = url.path.split("/", 4)[-1]
            if path in self.files:
                return httpx.Response(200, content=self.files[path])
            return httpx.Response(404)
        return httpx.Response(404)

    def factory(self, token: str = ""):
        return lambda: GitHubClient(transport=httpx.MockTransport(self.handler), token=token)


@pytest.fixture(autouse=True)
def _fresh():
    reset_shared_loaders()
    set_pack_for_tests(None)
    yield
    reset_shared_loaders()
    set_pack_for_tests(None)


def _install(home: Path, name: str, files: dict[str, bytes], folder: str, *, base: str = ".agents/skills", crlf=False) -> Path:
    target = home / base / name
    lead = folder + "/" if folder else ""
    for rel, data in files.items():
        if rel.startswith(lead):
            out = target / rel[len(lead):]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data.replace(b"\n", b"\r\n") if crlf else data)
    return target


def _lock(home: Path, entries: dict[str, dict]) -> Path:
    path = home / ".agents/.skill-lock.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 3, "skills": entries, "dismissed": {"x": True}, "lastSelectedAgents": ["codex"]}, indent=2),
        encoding="utf-8",
    )
    return path


def _entry(folder_hash: str, folder: str = "skills/report", **extra) -> dict:
    return {
        "source": REPO,
        "sourceType": "github",
        "sourceUrl": f"https://github.com/{REPO}.git",
        "skillPath": f"{folder}/SKILL.md" if folder else "SKILL.md",
        "skillFolderHash": folder_hash,
        "installedAt": "2026-10-01T00:00:00.000Z",
        "updatedAt": "2026-10-01T00:00:00.000Z",
        **extra,
    }


def _setup(gh: FakeGitHub, *, version: int, lock_version: int, crlf=False, edit: bytes | None = None):
    home = skill_home()
    files = V1 if version == 0 else V2
    target = _install(home, "report", files, "skills/report", crlf=crlf)
    if edit is not None:
        (target / "SKILL.md").write_bytes(edit)
    lock = _lock(home, {"report": _entry(gh.folder_sha(lock_version, "skills/report"))})
    reg = SourceRegistry()
    reg.set_enabled("agents", True)
    return home, target, lock, reg


def _check(gh, reg, token: str = ""):
    upd = ExternalUpdater(reg, client_factory=gh.factory(token))
    return upd, upd.check(reg.discover())


# -- check ------------------------------------------------------------------------------


def test_up_to_date_even_with_crlf_checkout():
    gh = FakeGitHub(V1, V2)
    _home, _t, _l, reg = _setup(gh, version=1, lock_version=1, crlf=True)
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "up_to_date"
    assert len([c for c in gh.calls if c.url.host == "api.github.com"]) == 1  # one per repo


def test_modified_without_update():
    gh = FakeGitHub(V1, V2)
    _h, _t, _l, reg = _setup(gh, version=1, lock_version=1, edit=b"---\nname: report\n---\nmine\n")
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "modified"
    assert res["report"]["changes"] == ["改动 SKILL.md"]


def test_update_available_and_untouched_needs_no_extra_call():
    gh = FakeGitHub(V1, V2)
    _h, _t, _l, reg = _setup(gh, version=0, lock_version=0)
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "available"
    assert res["report"]["current"] != res["report"]["latest"]
    assert len(gh.calls) == 1  # the local tree hash proved "unchanged" offline


def test_update_available_and_modified():
    gh = FakeGitHub(V1, V2)
    _h, target, _l, reg = _setup(gh, version=0, lock_version=0)
    (target / "notes.md").write_text("mine", encoding="utf-8")
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "modified_and_available"
    assert "新增 notes.md" in res["report"]["changes"]


def test_local_build_junk_is_not_a_modification():
    gh = FakeGitHub(V1, V2)
    _h, target, _l, reg = _setup(gh, version=0, lock_version=0)
    (target / "node_modules/pkg").mkdir(parents=True)
    (target / "node_modules/pkg/index.js").write_text("x", encoding="utf-8")
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "available"
    assert res["report"]["local_only_dirs"] == ["node_modules"]


def test_untracked_and_unsupported():
    gh = FakeGitHub(V1)
    home = skill_home()
    _install(home, "report", V1, "skills/report")
    _install(home, "other", V1, "skills/other")
    _lock(home, {"other": {**_entry("abc", "skills/other"), "sourceType": "local"}})
    reg = SourceRegistry()
    reg.set_enabled("agents", True)
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "untracked"
    assert res["other"]["status"] == "unsupported"
    assert gh.calls == []


def test_unknown_lock_version_is_unsupported():
    gh = FakeGitHub(V1)
    home = skill_home()
    _install(home, "report", V1, "skills/report")
    (home / ".agents/.skill-lock.json").write_text(json.dumps({"version": 99, "skills": {"report": _entry("x")}}), encoding="utf-8")
    reg = SourceRegistry()
    reg.set_enabled("agents", True)
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "unsupported"


def test_truncated_listing_walks_the_path():
    gh = FakeGitHub(V1, V2)
    gh.truncate_root = True
    _h, _t, _l, reg = _setup(gh, version=0, lock_version=0)
    _upd, res = _check(gh, reg)
    assert res["report"]["status"] == "available"
    assert res["report"]["latest"] == gh.folder_sha(1, "skills/report")[:7]


def test_rate_limit_is_reported_with_reset_time():
    gh = FakeGitHub(V1, V2)
    gh.rate_limited = True
    _h, _t, _l, reg = _setup(gh, version=0, lock_version=0)
    upd, res = _check(gh, reg)
    assert res["report"]["status"] == "error"
    assert "额度" in res["report"]["error"] and res["report"]["reset_at"] == 1999999999
    assert "GITHUB_TOKEN" in res["report"]["error"]
    assert upd.cached()["results"]["report"]["status"] == "error"


def test_token_is_sent_but_never_leaks(caplog):
    caplog.set_level(logging.DEBUG)
    gh = FakeGitHub(V1, V2)
    gh.rate_limited = True
    _h, _t, _l, reg = _setup(gh, version=0, lock_version=0)
    upd, res = _check(gh, reg, token=SECRET_TOKEN)
    assert gh.calls[0].headers["authorization"] == f"Bearer {SECRET_TOKEN}"
    assert SECRET_TOKEN not in json.dumps(res)
    assert SECRET_TOKEN not in upd.cache_path.read_text(encoding="utf-8")
    assert SECRET_TOKEN not in caplog.text
    assert "GITHUB_TOKEN" not in res["report"]["error"]  # already authenticated


def test_cache_marks_stale_after_a_day(monkeypatch):
    gh = FakeGitHub(V1, V2)
    _h, _t, _l, reg = _setup(gh, version=0, lock_version=0)
    upd, _res = _check(gh, reg)
    assert upd.cached()["stale"] is False
    import coworker.skills.updates as updates

    real = updates.time.time
    monkeypatch.setattr(updates.time, "time", lambda: real() + 25 * 3600)
    assert upd.cached()["stale"] is True


# -- apply / rollback ---------------------------------------------------------------------


def test_upgrade_swaps_files_writes_lock_and_rolls_back():
    gh = FakeGitHub(V1, V2)
    _h, target, lock, reg = _setup(gh, version=0, lock_version=0)
    upd = ExternalUpdater(reg, client_factory=gh.factory())
    (ext,) = reg.discover()
    res = upd.apply(ext, overwrite_modified=False)
    assert res["ok"] is True, res
    assert b"v2 body" in (target / "SKILL.md").read_bytes()
    assert (target / "templates/t.md").is_file()
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert data["skills"]["report"]["skillFolderHash"] == gh.folder_sha(1, "skills/report")
    assert data["skills"]["report"]["installedAt"] == "2026-10-01T00:00:00.000Z"  # untouched
    assert data["skills"]["report"]["updatedAt"].endswith("Z")
    assert data["dismissed"] == {"x": True} and data["lastSelectedAgents"] == ["codex"]
    assert upd.cached()["results"]["report"]["status"] == "up_to_date"
    # rollback
    assert upd.rollback("report")["ok"] is True
    assert b"v1 body" in (target / "SKILL.md").read_bytes()
    assert not (target / "templates").exists()
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert data["skills"]["report"]["skillFolderHash"] == gh.folder_sha(0, "skills/report")
    assert backups.latest("report", "external") is None
    # The old folder is back, so the list must say "update available" again at once.
    assert upd.cached()["results"]["report"]["status"] == "available"


def test_modified_needs_confirmation_and_old_copy_is_backed_up():
    gh = FakeGitHub(V1, V2)
    _h, target, _l, reg = _setup(gh, version=0, lock_version=0)
    (target / "notes.md").write_text("mine", encoding="utf-8")
    upd = ExternalUpdater(reg, client_factory=gh.factory())
    (ext,) = reg.discover()
    refused = upd.apply(ext, overwrite_modified=False)
    assert refused["ok"] is False and refused["code"] == "modified_requires_confirm"
    assert (target / "notes.md").is_file()
    done = upd.apply(ext, overwrite_modified=True)
    assert done["ok"] is True
    assert not (target / "notes.md").exists()
    backup = backups.latest("report", "external")
    assert (backup / "0" / "notes.md").read_text(encoding="utf-8") == "mine"


def test_secret_in_new_version_refuses_and_changes_nothing():
    v2 = {**V2, "skills/report/.env": b"KEY=1\n"}
    gh = FakeGitHub(V1, v2)
    _h, target, lock, reg = _setup(gh, version=0, lock_version=0)
    before = lock.read_text(encoding="utf-8")
    upd = ExternalUpdater(reg, client_factory=gh.factory())
    (ext,) = reg.discover()
    res = upd.apply(ext, overwrite_modified=False)
    assert res["ok"] is False and ".env" in res["error"]
    assert b"v1 body" in (target / "SKILL.md").read_bytes()
    assert lock.read_text(encoding="utf-8") == before


def test_tampered_download_is_refused():
    gh = FakeGitHub(V1, V2)
    gh.files = {**V2, "skills/report/SKILL.md": b"evil"}
    _h, target, _l, reg = _setup(gh, version=0, lock_version=0)
    upd = ExternalUpdater(reg, client_factory=gh.factory())
    (ext,) = reg.discover()
    res = upd.apply(ext, overwrite_modified=False)
    assert res["ok"] is False and "重新检查" in res["error"]
    assert b"v1 body" in (target / "SKILL.md").read_bytes()


def test_folder_in_use_leaves_everything_as_it_was(monkeypatch):
    gh = FakeGitHub(V1, V2)
    _h, target, lock, reg = _setup(gh, version=0, lock_version=0)
    before = lock.read_text(encoding="utf-8")
    upd = ExternalUpdater(reg, client_factory=gh.factory())
    (ext,) = reg.discover()
    real_rename = os.rename

    def held(src, dst):
        if Path(src) == target:
            raise PermissionError(13, "in use")
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", held)
    res = upd.apply(ext, overwrite_modified=False)
    assert res["ok"] is False and res["code"] == "in_use" and "report" in res["error"]
    assert b"v1 body" in (target / "SKILL.md").read_bytes()
    assert lock.read_text(encoding="utf-8") == before


def test_independent_copies_follow_only_when_identical():
    gh = FakeGitHub(V1, V2)
    home, target, _l, reg = _setup(gh, version=0, lock_version=0)
    same = _install(home, "report", V1, "skills/report", base=".claude/skills")
    edited = _install(home, "report", V1, "skills/report", base=".kiro/skills")
    (edited / "SKILL.md").write_bytes(b"---\nname: report\n---\nkiro edit\n")
    upd = ExternalUpdater(reg, client_factory=gh.factory())
    (ext,) = reg.discover()
    res = upd.apply(ext, overwrite_modified=False)
    assert res["ok"] is True
    assert b"v2 body" in (same / "SKILL.md").read_bytes()
    assert b"kiro edit" in (edited / "SKILL.md").read_bytes()
    assert any("Kiro" in k for k in res["kept"])
    upd.rollback("report")
    assert b"v1 body" in (same / "SKILL.md").read_bytes()


def test_backups_are_capped(monkeypatch):
    content = Path(tempfile.mkdtemp()) / "c"
    content.mkdir()
    (content / "SKILL.md").write_text("x", encoding="utf-8")
    target = skill_home() / ".agents/skills/cap"
    target.mkdir(parents=True)
    for _ in range(5):
        backups.install_with_backup("cap", [target], content, {"origin": "external"})
    assert len(list((backups.backups_root() / "cap").iterdir())) == backups.KEEP


# -- over HTTP ----------------------------------------------------------------------------


def _client(tmp_path, gh: FakeGitHub | None = None, pack_dir: Path | None = None):
    manager = SessionManager(workspace=tmp_path / "ws")
    if gh is not None:
        manager.external_updater = ExternalUpdater(manager.skill_sources, client_factory=gh.factory())
    if pack_dir is not None:
        set_pack_for_tests(LibraryPack(root=pack_dir))
    return TestClient(create_app(manager)), manager


def test_http_check_apply_rollback_roundtrip(tmp_path):
    gh = FakeGitHub(V1, V2)
    _setup(gh, version=0, lock_version=0)
    client, _m = _client(tmp_path, gh)
    first = client.get("/v1/skills/updates").json()
    assert first["checked_at"] is None and first["stale"] is True
    checked = client.post("/v1/skills/updates/check", json={}).json()
    assert checked["available_count"] == 1 and checked["stale"] is False
    row = {r["name"]: r for r in client.get("/v1/skills").json()["skills"]}["report"]
    assert row["update"]["status"] == "available" and row["can_rollback"] is False
    bad = client.post("/v1/skills/updates/apply", json={"items": []}).json()
    assert bad["ok"] is False
    res = client.post(
        "/v1/skills/updates/apply", json={"items": [{"name": "report", "origin": "external"}]}
    ).json()
    assert res["results"][0]["ok"] is True, res
    row = {r["name"]: r for r in client.get("/v1/skills").json()["skills"]}["report"]
    assert row["update"]["status"] == "up_to_date" and row["can_rollback"] is True
    back = client.post("/v1/skills/report/rollback", json={"origin": "external"}).json()
    assert back["ok"] is True
    none = client.post("/v1/skills/report/rollback", json={"origin": "external"}).json()
    assert none["ok"] is False


# -- library skills (来源与升级 §5 library half) ----------------------------------------------


def _library_row(client, name="scanpy"):
    return {r["name"]: r for r in client.get("/v1/skills").json()["skills"]}[name]


def test_library_install_records_baseline_and_detects_pack_update(tmp_path):
    pack = _build_pack(tmp_path / "library-pack")
    client, manager = _client(tmp_path, pack_dir=pack)
    assert client.post("/v1/library/install-skills", json={"names": ["scanpy"]}).json()["results"][0]["ok"]
    row = _library_row(client)
    assert row["origin"] == "library" and row["update"]["status"] == "up_to_date"
    # The app ships a newer pack.
    md = pack / "skills/scanpy/SKILL.md"
    md.write_text(md.read_text(encoding="utf-8") + "\nNew in v2.\n", encoding="utf-8")
    set_pack_for_tests(LibraryPack(root=pack))
    assert _library_row(client)["update"]["status"] == "available"
    res = client.post(
        "/v1/skills/updates/apply", json={"items": [{"name": "scanpy", "origin": "library"}]}
    ).json()
    assert res["results"][0]["ok"] is True
    installed = manager.skill_store.global_dir / "scanpy/SKILL.md"
    assert "New in v2." in installed.read_text(encoding="utf-8")
    row = _library_row(client)
    assert row["update"]["status"] == "up_to_date" and row["can_rollback"] is True
    assert client.post("/v1/skills/scanpy/rollback", json={"origin": "library"}).json()["ok"]
    assert "New in v2." not in installed.read_text(encoding="utf-8")
    assert _library_row(client)["update"]["status"] == "available"


def test_library_local_edit_is_modified_and_needs_confirm(tmp_path):
    pack = _build_pack(tmp_path / "library-pack")
    client, manager = _client(tmp_path, pack_dir=pack)
    client.post("/v1/library/install-skills", json={"names": ["scanpy"]})
    installed = manager.skill_store.global_dir / "scanpy/SKILL.md"
    installed.write_text("---\nname: scanpy\ndescription: mine\n---\nmine\n", encoding="utf-8")
    assert _library_row(client)["update"]["status"] == "modified"
    md = pack / "skills/scanpy/SKILL.md"
    md.write_text(md.read_text(encoding="utf-8") + "\nv2\n", encoding="utf-8")
    set_pack_for_tests(LibraryPack(root=pack))
    assert _library_row(client)["update"]["status"] == "modified_and_available"
    item = {"name": "scanpy", "origin": "library"}
    refused = client.post("/v1/skills/updates/apply", json={"items": [item]}).json()["results"][0]
    assert refused["ok"] is False and refused["code"] == "modified_requires_confirm"
    done = client.post(
        "/v1/skills/updates/apply", json={"items": [{**item, "overwrite_modified": True}]}
    ).json()["results"][0]
    assert done["ok"] is True
    backup = backups.latest("scanpy", "library")
    assert "mine" in (backup / "0/SKILL.md").read_text(encoding="utf-8")


def test_library_skill_installed_before_baselines(tmp_path):
    pack = _build_pack(tmp_path / "library-pack")
    client, manager = _client(tmp_path, pack_dir=pack)
    client.post("/v1/library/install-skills", json={"names": ["scanpy"]})
    manager.library_updater.path.unlink()  # an install from an older app version
    assert _library_row(client)["update"]["status"] == "up_to_date"  # equal → baseline back
    assert manager.library_updater.baseline("scanpy") is not None
    manager.library_updater.path.unlink()
    md = pack / "skills/scanpy/SKILL.md"
    md.write_text(md.read_text(encoding="utf-8") + "\nv2\n", encoding="utf-8")
    set_pack_for_tests(LibraryPack(root=pack))
    state = _library_row(client)["update"]
    assert state["status"] == "modified_and_available" and state["modified_unknown"] is True


def test_restore_original_is_backed_up_and_reversible(tmp_path):
    pack = _build_pack(tmp_path / "library-pack")
    client, manager = _client(tmp_path, pack_dir=pack)
    client.post("/v1/library/install-skills", json={"names": ["scanpy"]})
    installed = manager.skill_store.global_dir / "scanpy/SKILL.md"
    installed.write_text("---\nname: scanpy\ndescription: mine\n---\nmine\n", encoding="utf-8")
    res = client.post("/v1/library/install-skills", json={"names": ["scanpy"], "replace": True}).json()
    assert res["results"][0]["replaced"] is True
    assert "mine" not in installed.read_text(encoding="utf-8")
    assert client.post("/v1/skills/scanpy/rollback", json={}).json()["ok"] is True
    assert "mine" in installed.read_text(encoding="utf-8")
    assert _library_row(client)["update"]["status"] == "modified"


def test_own_skills_are_not_upgradable(tmp_path):
    client, _m = _client(tmp_path)
    client.post("/v1/skills", json={"name": "greet", "description": "d", "instructions": "x"})
    res = client.post(
        "/v1/skills/updates/apply", json={"items": [{"name": "greet", "origin": "own"}]}
    ).json()
    assert res["results"][0]["ok"] is False
    lib = client.post(
        "/v1/skills/updates/apply", json={"items": [{"name": "greet", "origin": "library"}]}
    ).json()
    assert lib["results"][0]["ok"] is False
