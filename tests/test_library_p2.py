"""P2 — /v1/library/install-expert, /activate-expert, /install-skills, /status.

Reuses the P0 mini-pack fixture shape (test_library_api.py) plus a real SessionManager
+ TestClient (test_skills_api.py) so install-expert/install-skills exercise the actual
PersonaRegistry / SkillStore, not a mock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coworker.library import LibraryPack, register_library_routes, set_pack_for_tests
from coworker.library.convert import WORKER_PREAMBLE
from coworker.personas.manifest import load_manifest_file
from coworker.server import SessionManager, create_app

# -- fixture pack --------------------------------------------------------------------
#
# zh experts:
#   academic/geographer   — description carries an English colon + quotes, to exercise
#                            the YAML round-trip.
#   academic/historian    — plain.
#   history/artifact-analyst, science/artifact-analyst — SAME basename
#     ("artifact-analyst") in two different categories, to exercise the category-prefix
#     collision rule.
# en experts:
#   academic/geographer   — the zh entry's translation pair.
# skills:
#   scanpy                — one installable skill.


def _write_expert(root: Path, lib: str, pack_id: str, body: str) -> None:
    path = root / "experts" / lib / f"{pack_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: placeholder\n---\n{body}\n", encoding="utf-8")


def _build_pack(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)

    _write_expert(root, "zh", "academic/geographer", "你是一名地理学家，擅长地形与气候分析。")
    _write_expert(root, "zh", "academic/historian", "你是一名历史学家。")
    _write_expert(root, "zh", "history/artifact-analyst", "你从历史脉络鉴定文物。")
    _write_expert(root, "zh", "science/artifact-analyst", "你用科学方法分析文物成分。")
    _write_expert(root, "en", "academic/geographer", "You are a geographer.")

    skill_dir = root / "skills" / "scanpy"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scanpy\ndescription: single-cell analysis toolkit\n---\n"
        "# scanpy\n\nUse scanpy for single-cell RNA-seq workflows.\n",
        encoding="utf-8",
    )
    (skill_dir / "__pycache__").mkdir(parents=True, exist_ok=True)
    (skill_dir / "__pycache__" / "stale.pyc").write_text("junk", encoding="utf-8")

    index = {
        "version": 1,
        "generated": {},
        "experts": {
            "zh": [
                {
                    "id": "academic/geographer",
                    "category": "academic",
                    "categoryName": "学术研究",
                    "name": "地理学家",
                    "description": '研究地理：地形与"气候"系统 (English: terrain analysis)',
                    "emoji": "🌍",
                    "color": "blue",
                    "pair": True,
                },
                {
                    "id": "academic/historian",
                    "category": "academic",
                    "categoryName": "学术研究",
                    "name": "历史学家",
                    "description": "研究历史",
                    "emoji": "📜",
                    "color": "#888",
                    "pair": False,
                },
                {
                    "id": "history/artifact-analyst",
                    "category": "history",
                    "categoryName": "历史学",
                    "name": "文物分析师",
                    "description": "从历史脉络鉴定文物",
                    "emoji": "🏺",
                    "color": "#888",
                    "pair": False,
                },
                {
                    "id": "science/artifact-analyst",
                    "category": "science",
                    "categoryName": "科学",
                    "name": "文物科学家",
                    "description": "用科学方法分析文物成分",
                    "emoji": "🔬",
                    "color": "#888",
                    "pair": False,
                },
            ],
            "en": [
                {
                    "id": "academic/geographer",
                    "category": "academic",
                    "categoryName": "Academic",
                    "name": "Geographer",
                    "description": "studies geography",
                    "emoji": "🌍",
                    "color": "blue",
                    "pair": True,
                },
            ],
        },
        "skills": [
            {
                "name": "scanpy",
                "description": "single-cell analysis toolkit",
                "category": "packages",
                "categoryName": "科学软件包",
                "scripts": 0,
                "references": 0,
                "assets": 0,
                "files": 1,
                "compatibility": "python>=3.9",
                "license": "BSD-3-Clause license",
            }
        ],
    }
    (root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return root


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


# -- install-expert -------------------------------------------------------------------


def test_install_expert_solo_lands_disabled_with_consent(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    res = client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "academic/geographer", "worker": False},
    ).json()
    assert res["ok"] is True
    assert res["persona_id"] == "geographer"
    assert isinstance(res["consent"], list) and len(res["consent"]) == 1
    assert res["consent"][0]["id"] == "geographer"

    entry = manager.personas.get("geographer")
    assert entry is not None
    assert manager.personas.is_enabled("geographer") is False


def test_install_expert_manifest_parses_with_correct_tools(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "academic/geographer"},
    )
    snapshot = manager.personas.installed_dir / "geographer" / "manifest.md"
    assert snapshot.is_file()
    m = load_manifest_file(snapshot)
    assert m.id == "geographer"
    assert m.name == "地理学家"
    assert m.tools == ["files", "search", "shell", "todo"]
    assert m.team is None
    assert "你是一名地理学家" in m.system_prompt


def test_install_expert_description_with_colon_and_quotes_round_trips(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "academic/geographer"},
    )
    snapshot = manager.personas.installed_dir / "geographer" / "manifest.md"
    m = load_manifest_file(snapshot)
    assert m.description == '研究地理：地形与"气候"系统 (English: terrain analysis)'


def test_install_expert_worker_variant_has_team_and_preamble(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "academic/geographer", "worker": False},
    )
    res = client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "academic/geographer", "worker": True},
    ).json()
    assert res["ok"] is True
    assert res["persona_id"] == "geographer-worker"

    snapshot = manager.personas.installed_dir / "geographer-worker" / "manifest.md"
    m = load_manifest_file(snapshot)
    assert m.team == "worker"
    assert m.name == "地理学家（组员）"
    assert m.system_prompt.startswith(WORKER_PREAMBLE)
    assert "你是一名地理学家" in m.system_prompt

    # solo and worker are independent installs, both present.
    assert manager.personas.get("geographer") is not None
    assert manager.personas.get("geographer-worker") is not None


def test_install_expert_basename_collision_uses_category_prefix(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    hist = client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "history/artifact-analyst"},
    ).json()
    sci = client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "science/artifact-analyst"},
    ).json()
    assert hist["ok"] is True and sci["ok"] is True
    assert hist["persona_id"] == "history-artifact-analyst"
    assert sci["persona_id"] == "science-artifact-analyst"
    assert manager.personas.get("history-artifact-analyst") is not None
    assert manager.personas.get("science-artifact-analyst") is not None


def test_install_expert_unknown_id_or_lib(tmp_path, pack_dir):
    client, _manager = _client(tmp_path, pack_dir)
    bad_id = client.post(
        "/v1/library/install-expert", json={"lib": "zh", "id": "nope/nope"}
    ).json()
    assert bad_id["ok"] is False and bad_id["error"]
    bad_lib = client.post(
        "/v1/library/install-expert", json={"lib": "fr", "id": "academic/geographer"}
    ).json()
    assert bad_lib["ok"] is False and bad_lib["error"]


def test_install_expert_manager_unavailable():
    app = FastAPI()
    register_library_routes(app, manager=None, pack=LibraryPack(root=Path("nope")))
    client = TestClient(app)
    res = client.post(
        "/v1/library/install-expert", json={"lib": "zh", "id": "academic/geographer"}
    ).json()
    assert res == {"ok": False, "error": "library install unavailable"}


# -- activate-expert --------------------------------------------------------------------


def test_activate_expert_enables_and_stays_unsurfaced(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    install = client.post(
        "/v1/library/install-expert", json={"lib": "zh", "id": "academic/geographer"}
    ).json()
    persona_id = install["persona_id"]

    res = client.post(
        "/v1/library/activate-expert", json={"persona_id": persona_id}
    ).json()
    assert res == {"ok": True, "enabled": True}
    assert manager.personas.is_enabled(persona_id) is True
    assert manager.personas.is_surfaced(persona_id) is False


def test_activate_expert_rejects_non_library_persona(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    # A builtin persona was never installed from the library staging dir.
    res = client.post("/v1/library/activate-expert", json={"persona_id": "cowork"}).json()
    assert res["ok"] is False

    # Nor was a persona installed through the ordinary /v1/personas/install path.
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "sec-review.md").write_text(
        "---\nid: sec-review\nname: Sec\ntools: [files]\n---\nReview things.\n",
        encoding="utf-8",
    )
    manager.personas.install_from_dir(vendor)
    res2 = client.post(
        "/v1/library/activate-expert", json={"persona_id": "sec-review"}
    ).json()
    assert res2["ok"] is False
    assert manager.personas.is_enabled("sec-review") is False


def test_activate_expert_unknown_persona(tmp_path, pack_dir):
    client, _manager = _client(tmp_path, pack_dir)
    res = client.post(
        "/v1/library/activate-expert", json={"persona_id": "ghost"}
    ).json()
    assert res["ok"] is False


# -- install-skills -----------------------------------------------------------------------


def test_install_skills_lands_skill_md_and_excludes_pycache(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)
    res = client.post("/v1/library/install-skills", json={"names": ["scanpy"]}).json()
    assert res == {"ok": True, "results": [{"name": "scanpy", "ok": True}]}
    dest = manager.skill_store.global_dir / "scanpy"
    assert (dest / "SKILL.md").is_file()
    assert not (dest / "__pycache__").exists()


def test_install_skills_keeps_zh_translation_out_of_global_dir(tmp_path, pack_dir):
    # SKILL.zh.md 是库内浏览用的译文层——安装进全局技能目录的必须是英文原件，
    # agent 消费面不因翻译而改变。
    (pack_dir / "skills" / "scanpy" / "SKILL.zh.md").write_text(
        "# scanpy\n\n中文说明。\n", encoding="utf-8"
    )
    client, manager = _client(tmp_path, pack_dir)
    res = client.post("/v1/library/install-skills", json={"names": ["scanpy"]}).json()
    assert res["ok"] is True
    dest = manager.skill_store.global_dir / "scanpy"
    assert (dest / "SKILL.md").is_file()
    assert not (dest / "SKILL.zh.md").exists()


def test_install_skills_duplicate_invalid_and_unknown(tmp_path, pack_dir):
    client, _manager = _client(tmp_path, pack_dir)
    client.post("/v1/library/install-skills", json={"names": ["scanpy"]})
    res = client.post(
        "/v1/library/install-skills",
        json={"names": ["scanpy", "../evil", "no-such-skill"]},
    ).json()
    assert res["ok"] is True
    by_name = {r["name"]: r for r in res["results"]}
    assert by_name["scanpy"]["ok"] is False
    assert "already installed" in by_name["scanpy"]["error"]
    assert by_name["../evil"]["ok"] is False
    assert by_name["no-such-skill"]["ok"] is False
    assert "unknown skill" in by_name["no-such-skill"]["error"]


def test_install_skills_bad_body_shape(tmp_path, pack_dir):
    client, _manager = _client(tmp_path, pack_dir)
    res = client.post("/v1/library/install-skills", json={}).json()
    assert res["ok"] is False


# -- status -----------------------------------------------------------------------------


def test_status_reflects_installs(tmp_path, pack_dir):
    client, manager = _client(tmp_path, pack_dir)

    empty = client.get("/v1/library/status").json()
    assert empty == {"ok": True, "experts": {}, "skills": []}

    install = client.post(
        "/v1/library/install-expert", json={"lib": "zh", "id": "academic/geographer"}
    ).json()
    persona_id = install["persona_id"]
    client.post("/v1/library/activate-expert", json={"persona_id": persona_id})
    client.post(
        "/v1/library/install-expert",
        json={"lib": "zh", "id": "academic/geographer", "worker": True},
    )
    client.post("/v1/library/install-skills", json={"names": ["scanpy"]})

    res = client.get("/v1/library/status").json()
    assert res["ok"] is True
    key = "zh:academic/geographer"
    assert key in res["experts"]
    assert res["experts"][key]["solo"] == {"persona_id": "geographer", "enabled": True}
    assert res["experts"][key]["worker"] == {
        "persona_id": "geographer-worker",
        "enabled": False,
    }
    # Never-installed experts are simply absent (not an empty dict).
    assert "zh:academic/historian" not in res["experts"]
    assert res["skills"] == ["scanpy"]


def test_status_manager_unavailable():
    app = FastAPI()
    register_library_routes(app, manager=None, pack=LibraryPack(root=Path("nope")))
    client = TestClient(app)
    res = client.get("/v1/library/status").json()
    assert res == {"ok": False, "error": "library install unavailable"}
