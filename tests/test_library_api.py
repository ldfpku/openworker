"""GET /v1/library* — read-only browsing of the pre-built library data pack.

Follows the codebase's API convention: failures return ``{"ok": False, "error": …}``
bodies, matching every other /v1 management endpoint (see test_skills_api.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coworker.library import LibraryPack, set_pack_for_tests
from coworker.server import SessionManager, create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_INDEX = REPO_ROOT / "library-pack" / "index.json"


def _client(tmp_path: Path) -> TestClient:
    manager = SessionManager(workspace=tmp_path / "ws")
    return TestClient(create_app(manager))


def _build_pack(root: Path) -> Path:
    """A mini library-pack: 2 zh experts + 1 en expert (one id shared with zh, to
    exercise `pair`), and 1 skill with scripts/ + references/ resources."""
    root.mkdir(parents=True, exist_ok=True)

    zh_dir = root / "experts" / "zh" / "academic"
    en_dir = root / "experts" / "en" / "academic"
    zh_dir.mkdir(parents=True, exist_ok=True)
    en_dir.mkdir(parents=True, exist_ok=True)

    (zh_dir / "academic-geographer.md").write_text(
        "---\nname: 地理学家\ndescription: 研究地理\nemoji: 🌍\ncolor: blue\n---\n"
        "你是一名地理学家，擅长地形与气候分析。\n",
        encoding="utf-8",
    )
    (zh_dir / "academic-historian.md").write_text(
        "---\nname: 历史学家\ndescription: 研究历史\n---\n你是一名历史学家。\n",
        encoding="utf-8",
    )
    (en_dir / "academic-geographer.md").write_text(
        "---\nname: Geographer\ndescription: studies geography\nemoji: 🌍\ncolor: blue\n---\n"
        "You are a geographer skilled in terrain and climate analysis.\n",
        encoding="utf-8",
    )

    skill_dir = root / "skills" / "scanpy"
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts" / "preprocess.py").write_text("# preprocess\n", encoding="utf-8")
    (skill_dir / "references" / "notes.md").write_text("notes\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scanpy\ndescription: single-cell analysis toolkit\n---\n"
        "# scanpy\n\nUse scanpy for single-cell RNA-seq workflows.\n",
        encoding="utf-8",
    )

    index = {
        "version": 1,
        "generated": {
            "agency-agents": "abc123",
            "agency-agents-zh": "def456",
            "scientific-agent-skills": "ghi789",
        },
        "experts": {
            "zh": [
                {
                    "id": "academic/academic-geographer",
                    "category": "academic",
                    "categoryName": "学术研究",
                    "name": "地理学家",
                    "description": "研究地理",
                    "emoji": "🌍",
                    "color": "blue",
                    "pair": True,
                },
                {
                    "id": "academic/academic-historian",
                    "category": "academic",
                    "categoryName": "学术研究",
                    "name": "历史学家",
                    "description": "研究历史",
                    "emoji": "🤖",
                    "color": "#888",
                    "pair": False,
                },
            ],
            "en": [
                {
                    "id": "academic/academic-geographer",
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
                "scripts": 1,
                "references": 1,
                "assets": 0,
                "files": 2,
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
    """The routes read a module-level singleton — never leak one test's pack into the
    next."""
    set_pack_for_tests(None)
    yield
    set_pack_for_tests(None)


# -- overview -------------------------------------------------------------------------


def test_overview_counts(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get("/v1/library").json()
    assert res == {
        "ok": True,
        "version": 1,
        "experts": {"zh": 2, "en": 1},
        "skills": 1,
    }


# -- experts --------------------------------------------------------------------------


def test_experts_lib_zh_fields(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get("/v1/library/experts", params={"lib": "zh"}).json()
    assert res["ok"] is True
    assert res["experts"] == [
        {
            "id": "academic/academic-geographer",
            "category": "academic",
            "categoryName": "学术研究",
            "name": "地理学家",
            "description": "研究地理",
            "emoji": "🌍",
            "color": "blue",
            "pair": True,
        },
        {
            "id": "academic/academic-historian",
            "category": "academic",
            "categoryName": "学术研究",
            "name": "历史学家",
            "description": "研究历史",
            "emoji": "🤖",
            "color": "#888",
            "pair": False,
        },
    ]


def test_experts_default_lib_is_zh(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    default = client.get("/v1/library/experts").json()
    zh = client.get("/v1/library/experts", params={"lib": "zh"}).json()
    assert default == zh


def test_experts_en_lib_and_pair_false(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get("/v1/library/experts", params={"lib": "en"}).json()
    assert res["ok"] is True
    assert len(res["experts"]) == 1
    assert res["experts"][0]["pair"] is True  # shared id with zh


def test_experts_invalid_lib_rejected(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get("/v1/library/experts", params={"lib": "fr"}).json()
    assert res["ok"] is False and res["error"]


# -- expert-prompt ----------------------------------------------------------------------


def test_expert_prompt_strips_frontmatter(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get(
        "/v1/library/expert-prompt",
        params={"lib": "zh", "id": "academic/academic-geographer"},
    ).json()
    assert res["ok"] is True
    assert res["id"] == "academic/academic-geographer"
    assert res["name"] == "地理学家"
    assert "---" not in res["prompt"]
    assert "name:" not in res["prompt"]
    assert "你是一名地理学家" in res["prompt"]


def test_expert_prompt_unknown_id(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get(
        "/v1/library/expert-prompt", params={"lib": "zh", "id": "nope/nope"}
    ).json()
    assert res["ok"] is False and res["error"]


def test_expert_prompt_path_traversal_rejected(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get(
        "/v1/library/expert-prompt",
        params={"lib": "zh", "id": "../../../../etc/passwd"},
    ).json()
    assert res["ok"] is False and res["error"]


# -- skills -----------------------------------------------------------------------------


def test_skills_list(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get("/v1/library/skills").json()
    assert res["ok"] is True
    assert res["skills"] == [
        {
            "name": "scanpy",
            "description": "single-cell analysis toolkit",
            "category": "packages",
            "categoryName": "科学软件包",
            "scripts": 1,
            "references": 1,
            "assets": 0,
            "files": 2,
            "compatibility": "python>=3.9",
            "license": "BSD-3-Clause license",
        }
    ]


def test_skill_detail_includes_files_and_body(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get("/v1/library/skill", params={"name": "scanpy"}).json()
    assert res["ok"] is True
    assert res["name"] == "scanpy"
    assert res["description"] == "single-cell analysis toolkit"
    assert "---" not in res["skill_md"]
    assert "Use scanpy for single-cell RNA-seq workflows." in res["skill_md"]
    assert sorted(res["files"]) == [
        "references/notes.md",
        "scripts/preprocess.py",
    ]
    assert res["scripts"] == 1
    assert res["compatibility"] == "python>=3.9"
    assert res["license"] == "BSD-3-Clause license"


def test_skill_detail_unknown_name(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get("/v1/library/skill", params={"name": "ghost"}).json()
    assert res["ok"] is False and res["error"]


def test_skill_detail_path_traversal_rejected(tmp_path, pack_dir):
    set_pack_for_tests(LibraryPack(root=pack_dir))
    client = _client(tmp_path)
    res = client.get(
        "/v1/library/skill", params={"name": "../../../../etc"}
    ).json()
    assert res["ok"] is False and res["error"]


# -- missing pack ------------------------------------------------------------------------


def test_missing_pack_all_endpoints_report_not_found(tmp_path):
    missing = tmp_path / "no-such-library-pack"
    set_pack_for_tests(LibraryPack(root=missing))
    client = _client(tmp_path)
    checks = [
        ("GET", "/v1/library", {}),
        ("GET", "/v1/library/experts", {"lib": "zh"}),
        ("GET", "/v1/library/expert-prompt", {"lib": "zh", "id": "x/y"}),
        ("GET", "/v1/library/skills", {}),
        ("GET", "/v1/library/skill", {"name": "x"}),
    ]
    for method, path, params in checks:
        res = client.request(method, path, params=params).json()
        assert res == {"ok": False, "error": "library pack not found"}, path


# -- lazy-load robustness ----------------------------------------------------------------
# The routes are sync defs (threadpool), so the GUI's first library visit fires several
# requests into a cold LibraryPack concurrently. These pin the two properties that kept
# the shipped desktop app honest: no request may observe a half-initialized load, and a
# failed load must not be cached for the life of the process.


def test_concurrent_first_load_returns_data_to_every_thread(pack_dir, monkeypatch):
    import threading
    import time

    real_read_text = Path.read_text

    def slow_read_text(self, *args, **kwargs):
        text = real_read_text(self, *args, **kwargs)
        if self.name == "index.json":
            time.sleep(0.05)  # widen the parse window the way a cold first read does
        return text

    monkeypatch.setattr(Path, "read_text", slow_read_text)

    pack = LibraryPack(root=pack_dir)
    barrier = threading.Barrier(8)
    results: list[bool] = []

    def hit() -> None:
        barrier.wait()
        results.append(pack.experts("zh")["ok"])

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True] * 8


def test_failed_load_is_retried_not_cached(pack_dir):
    index = pack_dir / "index.json"
    hidden = pack_dir / "index.json.hidden"
    index.rename(hidden)

    pack = LibraryPack(root=pack_dir)
    assert pack.overview()["ok"] is False

    hidden.rename(index)
    assert pack.overview()["ok"] is True


# -- real pack smoke test (only when the packer has already run) ------------------------


@pytest.mark.skipif(not REAL_INDEX.is_file(), reason="library-pack not built yet")
def test_real_pack_smoke(tmp_path):
    set_pack_for_tests(LibraryPack(root=REAL_INDEX.parent))
    client = _client(tmp_path)

    overview = client.get("/v1/library").json()
    assert overview["ok"] is True
    assert overview["experts"]["zh"] > 0
    assert overview["skills"] >= 0

    experts = client.get("/v1/library/experts", params={"lib": "zh"}).json()
    assert experts["ok"] is True
    assert experts["experts"], "expected at least one zh expert in the real pack"
    sample = experts["experts"][0]

    prompt = client.get(
        "/v1/library/expert-prompt", params={"lib": "zh", "id": sample["id"]}
    ).json()
    assert prompt["ok"] is True
    assert prompt["prompt"].strip()
