"""P4 — the machine-local layer over the library pack (coworker/library/local.py):
editing a pack expert in place, writing a new one, restoring the original, and keeping an
installed coworker in step with what was saved.

Reuses the P2 mini-pack fixture (test_library_p2.py) + a real SessionManager so the
re-install path exercises the actual PersonaRegistry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coworker.library import LibraryPack, set_pack_for_tests
from coworker.library.local import LibraryOverlay, LocalLibrary, split_frontmatter
from coworker.personas.manifest import load_manifest_file
from coworker.secrets import state_dir
from coworker.server import SessionManager, create_app
from tests.test_library_p2 import _build_pack


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    return _build_pack(tmp_path / "library-pack")


@pytest.fixture(autouse=True)
def _reset_pack_singleton():
    set_pack_for_tests(None)
    yield
    set_pack_for_tests(None)


def _client(tmp_path: Path, pack_dir: Path):
    manager = SessionManager(workspace=tmp_path / "ws")
    set_pack_for_tests(LibraryPack(root=pack_dir))
    return TestClient(create_app(manager)), manager


# -- the local store itself -----------------------------------------------------------


def test_local_library_round_trips_frontmatter_and_keeps_hand_added_keys(tmp_path):
    local = LocalLibrary(tmp_path / "local")
    row = local.write(
        "zh",
        "academic/geographer",
        {"name": "地理学家：改", "description": 'a "quoted" desc', "emoji": "🌍", "category": "academic", "categoryName": "学术研究"},
        "你是改过的地理学家。\r\n第二行。",
    )
    assert row["name"] == "地理学家：改" and row["prompt"] == "你是改过的地理学家。\n第二行。"
    path = local.path_for("zh", "academic/geographer")
    assert path.is_file() and path.parent == tmp_path / "local" / "experts" / "zh" / "academic"
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["name"] == "地理学家：改" and meta["description"] == 'a "quoted" desc'
    assert body == "你是改过的地理学家。\n第二行。"

    # A key someone added by hand survives the next save from the app.
    path.write_text(path.read_text(encoding="utf-8").replace("---\n\n", "---\n\n", 1), encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    text = text.replace("\n---\n\n", "\nauthor: me\n---\n\n", 1)
    path.write_text(text, encoding="utf-8")
    local.write("zh", "academic/geographer", {"name": "地理学家：再改"}, "第三版")
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["author"] == "me" and meta["name"] == "地理学家：再改" and body == "第三版"


def test_local_library_refuses_bad_ids_and_empty_fields(tmp_path):
    from coworker.library.local import LocalLibraryError

    local = LocalLibrary(tmp_path / "local")
    for bad in ("../x", "a/../b", "A/B", "", "x/", "/x", "a b"):
        with pytest.raises(LocalLibraryError):
            local.write("zh", bad, {"name": "n"}, "p")
    with pytest.raises(LocalLibraryError):
        local.write("zh", "local/x", {"name": ""}, "p")
    with pytest.raises(LocalLibraryError):
        local.write("zh", "local/x", {"name": "n"}, "   ")
    with pytest.raises(LocalLibraryError):
        local.write("fr", "local/x", {"name": "n"}, "p")
    assert local.read("zh", "../x") is None


def test_new_ids_never_collide_with_pack_basenames(tmp_path):
    local = LocalLibrary(tmp_path / "local")
    taken = {"geographer", "historian"}
    assert local.new_id("zh", "Geographer", taken) == "local/geographer-2"
    assert local.new_id("zh", "New Expert!", taken) == "local/new-expert"
    # A Chinese name slugifies to nothing → a stable hash-based slug, still unique.
    first = local.new_id("zh", "生产计划员", taken)
    assert first.startswith("local/expert-") and len(first) == len("local/expert-") + 8
    local.write("zh", first, {"name": "生产计划员"}, "p")
    assert local.new_id("zh", "生产计划员", taken) == first + "-2"


# -- the overlay: listing + prompt --------------------------------------------------


def test_overlay_lists_overrides_and_local_experts(tmp_path, pack_dir):
    pack = LibraryPack(root=pack_dir)
    local = LocalLibrary(tmp_path / "local")
    view = LibraryOverlay(pack, local)

    # Untouched: every row says so.
    rows = view.experts("zh")["experts"]
    assert all(r["local"] is False and r["modified"] is False for r in rows)
    assert view.expert_prompt("zh", "academic/geographer")["modified"] is False

    # An override shows through the listing (renamed) and the prompt, with the original kept.
    local.write("zh", "academic/geographer", {"name": "地理学家（改）", "category": "academic"}, "改过的提示词")
    row = next(r for r in view.experts("zh")["experts"] if r["id"] == "academic/geographer")
    assert row["modified"] is True and row["local"] is False and row["name"] == "地理学家（改）"
    assert row["categoryName"] == "学术研究"  # pack keeps the category
    prompt = view.expert_prompt("zh", "academic/geographer")
    assert prompt["prompt"] == "改过的提示词" and prompt["modified"] is True
    assert "你是一名地理学家" in prompt["pack_prompt"]

    # A local expert is appended, flagged, and its prompt comes straight from its file.
    local.write("zh", "local/planner", {"name": "排产员", "category": "ops", "categoryName": "运营"}, "你是排产员。")
    rows = view.experts("zh")["experts"]
    mine = next(r for r in rows if r["id"] == "local/planner")
    assert mine["local"] is True and mine["categoryName"] == "运营" and mine["pair"] is False
    assert view.expert_prompt("zh", "local/planner")["prompt"] == "你是排产员。"
    assert view.expert_prompt("zh", "local/nope")["ok"] is False
    assert view.overview()["experts"]["zh"] == 5  # 4 pack + 1 local


# -- the routes -----------------------------------------------------------------------


def test_save_route_creates_a_local_expert_that_installs_like_any_other(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    res = client.post(
        "/v1/library/expert",
        json={
            "lib": "zh",
            "name": "排产专家",
            "description": "为交期负责",
            "emoji": "📅",
            "category": "ops",
            "categoryName": "运营",
            "prompt": "你是排产专家。",
        },
    ).json()
    assert res["ok"] is True and res["created"] is True
    expert_id = res["id"]
    assert expert_id.startswith("local/")
    assert res["expert"]["local"] is True and res["expert"]["name"] == "排产专家"
    assert Path(res["path"]).is_file()
    assert Path(res["path"]).resolve().is_relative_to((state_dir() / "library-local").resolve())

    # It is listed, readable, and installable exactly like a pack expert.
    listed = client.get("/v1/library/experts?lib=zh").json()["experts"]
    assert any(r["id"] == expert_id and r["local"] for r in listed)
    assert client.get(f"/v1/library/expert-prompt?lib=zh&id={expert_id}").json()["prompt"] == "你是排产专家。"
    inst = client.post("/v1/library/install-expert", json={"lib": "zh", "id": expert_id}).json()
    assert inst["ok"] is True
    m = load_manifest_file(manager.personas.installed_dir / inst["persona_id"] / "manifest.md")
    assert m.name == "排产专家" and m.system_prompt.strip() == "你是排产专家。"
    status = client.get("/v1/library/status").json()
    assert f"zh:{expert_id}" in status["experts"]


def test_save_route_edits_a_pack_expert_in_place_and_refreshes_its_coworker(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    # Installed + enabled from the pack text first.
    inst = client.post("/v1/library/install-expert", json={"lib": "zh", "id": "academic/geographer"}).json()
    assert inst["ok"] is True
    client.post("/v1/library/activate-expert", json={"persona_id": "geographer"})
    assert manager.personas.is_enabled("geographer") is True
    assert "你是一名地理学家" in manager.personas.get("geographer").manifest.system_prompt

    res = client.post(
        "/v1/library/expert",
        json={"lib": "zh", "id": "academic/geographer", "name": "地理学家 Pro", "prompt": "你是升级版地理学家。"},
    ).json()
    assert res["ok"] is True and res["created"] is False
    assert res["expert"]["modified"] is True and res["expert"]["name"] == "地理学家 Pro"
    assert res["reinstalled"] == ["geographer"]

    # The installed coworker now runs on the edited text, still enabled, same id.
    entry = manager.personas.get("geographer")
    assert entry.manifest.system_prompt.strip() == "你是升级版地理学家。"
    assert entry.name == "地理学家 Pro"
    assert manager.personas.is_enabled("geographer") is True
    # The pack file itself is untouched.
    assert "你是一名地理学家" in (pack_dir / "experts" / "zh" / "academic" / "geographer.md").read_text(encoding="utf-8")
    assert "升级版" not in (pack_dir / "experts" / "zh" / "academic" / "geographer.md").read_text(encoding="utf-8")

    # Restore the original: the override goes, the coworker is rebuilt from the pack.
    gone = client.delete("/v1/library/expert?lib=zh&id=academic/geographer").json()
    assert gone["ok"] is True and gone["restored"] is True and gone["reinstalled"] == ["geographer"]
    assert "你是一名地理学家" in manager.personas.get("geographer").manifest.system_prompt
    row = next(r for r in client.get("/v1/library/experts?lib=zh").json()["experts"] if r["id"] == "academic/geographer")
    assert row["modified"] is False and row["name"] == "地理学家"
    # Nothing left to restore → an error body, not a 500.
    assert client.delete("/v1/library/expert?lib=zh&id=academic/geographer").json()["ok"] is False


def test_save_route_rejects_unknown_ids_and_bad_input(tmp_path, pack_dir):
    client, _ = _client(tmp_path, pack_dir)
    assert client.post("/v1/library/expert", json={"lib": "zh", "id": "nope/x", "name": "n", "prompt": "p"}).json()["ok"] is False
    assert client.post("/v1/library/expert", json={"lib": "zh", "name": "", "prompt": "p"}).json()["ok"] is False
    assert client.post("/v1/library/expert", json={"lib": "zh", "name": "n", "prompt": ""}).json()["ok"] is False
    assert client.post("/v1/library/expert", json={"lib": "xx", "name": "n", "prompt": "p"}).json()["ok"] is False
    assert client.post("/v1/library/expert", json={"lib": "zh", "id": "../../etc", "name": "n", "prompt": "p"}).json()["ok"] is False


def test_delete_route_removes_a_local_expert(tmp_path, pack_dir):
    client, _ = _client(tmp_path, pack_dir)
    res = client.post("/v1/library/expert", json={"lib": "zh", "name": "临时", "prompt": "p"}).json()
    expert_id = res["id"]
    gone = client.delete(f"/v1/library/expert?lib=zh&id={expert_id}").json()
    assert gone["ok"] is True and gone["deleted"] is True
    assert not Path(res["path"]).exists()
    assert not any(r["id"] == expert_id for r in client.get("/v1/library/experts?lib=zh").json()["experts"])


def test_install_skills_replace_restores_the_shipped_copy(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    assert client.post("/v1/library/install-skills", json={"names": ["scanpy"]}).json()["results"][0]["ok"] is True
    md = manager.skill_store.global_dir / "scanpy" / "SKILL.md"
    md.write_text("---\nname: scanpy\ndescription: edited\n---\nedited body\n", encoding="utf-8")
    again = client.post("/v1/library/install-skills", json={"names": ["scanpy"]}).json()["results"][0]
    assert again["ok"] is False and again["error"] == "already installed"
    replaced = client.post("/v1/library/install-skills", json={"names": ["scanpy"], "replace": True}).json()["results"][0]
    assert replaced["ok"] is True and replaced["replaced"] is True
    assert "single-cell analysis toolkit" in md.read_text(encoding="utf-8")


# -- audit 2026-09-10 hardening ---------------------------------------------------------


def test_new_local_expert_never_takes_a_coworkers_id(tmp_path, pack_dir):
    """A local expert named like a built-in coworker ("Security") or like an installed
    expert must get its own id — persona ids are app-wide and basenames become them."""
    client, manager = _client(tmp_path, pack_dir)
    res = client.post("/v1/library/expert", json={"lib": "en", "name": "Security", "prompt": "p"}).json()
    assert res["ok"] is True and res["id"] != "local/security"
    assert res["id"].startswith("local/security-")
    inst = client.post("/v1/library/install-expert", json={"lib": "en", "id": res["id"]}).json()
    assert inst["ok"] is True and inst["persona_id"] != "security"
    assert manager.personas.get("security").builtin is True

    # A team member's id is guarded too (a local "Design" must not become design-worker).
    res = client.post("/v1/library/expert", json={"lib": "en", "name": "Design", "prompt": "p"}).json()
    assert res["id"] != "local/design"
    # And the pack's own basenames across BOTH languages.
    res = client.post("/v1/library/expert", json={"lib": "en", "name": "Historian", "prompt": "p"}).json()
    assert res["id"] == "local/historian-2"


def test_install_refuses_to_replace_a_coworker_the_library_did_not_install(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    local = client.post("/v1/library/expert", json={"lib": "zh", "name": "x", "prompt": "p"}).json()
    # Hand the local expert an id that collides with a built-in by writing the file directly.
    from coworker.library.api import _get_local

    _get_local().write("zh", "local/ops", {"name": "Ops"}, "p")
    res = client.post("/v1/library/install-expert", json={"lib": "zh", "id": "local/ops"}).json()
    assert res["ok"] is False and "not installed from the library" in res["error"]
    assert manager.personas.get("ops").builtin is True
    assert local["ok"] is True  # the earlier, properly named one is unaffected


def test_resync_only_touches_the_language_that_was_installed(tmp_path, pack_dir):
    """A zh/en pair shares one coworker id. Editing the zh text must not rewrite a
    coworker that was installed from the en text."""
    client, manager = _client(tmp_path, pack_dir)
    inst = client.post("/v1/library/install-expert", json={"lib": "en", "id": "academic/geographer"}).json()
    assert inst["ok"] is True and inst["persona_id"] == "geographer"
    assert "You are a geographer" in manager.personas.get("geographer").manifest.system_prompt

    res = client.post(
        "/v1/library/expert",
        json={"lib": "zh", "id": "academic/geographer", "name": "地理学家", "prompt": "中文改版"},
    ).json()
    assert res["ok"] is True and res["reinstalled"] == []
    assert "You are a geographer" in manager.personas.get("geographer").manifest.system_prompt

    # Editing the en text does reach it.
    res = client.post(
        "/v1/library/expert",
        json={"lib": "en", "id": "academic/geographer", "name": "Geographer", "prompt": "English v2"},
    ).json()
    assert res["reinstalled"] == ["geographer"]
    assert manager.personas.get("geographer").manifest.system_prompt.strip() == "English v2"


def test_deleting_a_local_expert_uninstalls_its_coworkers(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    res = client.post("/v1/library/expert", json={"lib": "zh", "name": "临时专家", "prompt": "p"}).json()
    expert_id = res["id"]
    solo = client.post("/v1/library/install-expert", json={"lib": "zh", "id": expert_id}).json()["persona_id"]
    team = client.post("/v1/library/install-expert", json={"lib": "zh", "id": expert_id, "worker": True}).json()["persona_id"]
    assert manager.personas.get(solo) is not None and manager.personas.get(team) is not None

    gone = client.delete(f"/v1/library/expert?lib=zh&id={expert_id}").json()
    assert gone["ok"] is True and sorted(gone["uninstalled"]) == sorted([solo, team])
    assert manager.personas.get(solo) is None and manager.personas.get(team) is None
    assert not (manager.personas.installed_dir / solo).exists()


def test_skill_folded_description_reads_as_text_and_survives_an_edit(tmp_path):
    from coworker.skills import SkillLoader, SkillStore

    store = SkillStore(tmp_path / "skills")
    folder = store.global_dir / "bids"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: bids\ndescription: >\n  Brain imaging data structure,\n  folded over two lines.\nlicense: MIT\n---\n\nBody.\n",
        encoding="utf-8",
    )
    assert SkillLoader([store.global_dir]).get("bids").description == "Brain imaging data structure, folded over two lines."
    store.update("bids", description="Edited summary", instructions="New body.")
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert "folded over" not in text and "license: MIT" in text
    assert SkillLoader([store.global_dir]).get("bids").description == "Edited summary"
