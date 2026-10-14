"""coworker/library/recommend.py — the catalog pre-filter behind 开工前核对, run against the
real library pack and the built-in personas (the four training scenarios in docs/培训)."""

import json
import re
from pathlib import Path

import pytest

from coworker.library.recommend import recommend, tokenize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    index = json.loads((ROOT / "library-pack" / "index.json").read_text(encoding="utf-8"))
    personas = []
    for manifest in (ROOT / "coworker" / "personas" / "builtin").glob("*/manifest.md"):
        front = manifest.read_text(encoding="utf-8").split("---")[1]
        row = {}
        for line in front.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                row[key.strip()] = value.strip()
        personas.append(
            {
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "tagline": row.get("tagline", ""),
                "description": row.get("description", ""),
            }
        )
    return index["skills"], index["experts"]["zh"], personas


def test_tokenize_bigrams_cjk_and_words_ascii():
    assert tokenize("质量周报") == {"质量", "量周", "周报"}
    assert tokenize("quality-weekly-report v2") == {"quality", "weekly", "report", "v2"}
    q = tokenize("帮我做个质量周报", query=True)
    assert {"质量", "量周", "周报"} <= q and not ({"帮我", "我做", "做个"} & q)
    assert tokenize("") == set()


@pytest.mark.parametrize(
    "query, top_skill",
    [
        ("帮我做个质量周报", "quality-weekly-report"),
        ("读所有服务中心的返厂维修记录，分析高频故障", "repair-return-tracking"),
        ("分析一下这根震击器为什么下井没震开", "field-failure-analysis"),
        ("Write a quality weekly report from the inspection records", "quality-weekly-report"),
    ],
)
def test_training_scenarios_rank_the_matching_skill_first(catalog, query, top_skill):
    skills, experts, personas = catalog
    out = recommend(query, library_skills=skills, installed=set(), library_experts=experts, personas=personas)
    assert out["skills"], query
    assert out["skills"][0]["id"] == top_skill


def test_quote_request_surfaces_a_pricing_expert(catalog):
    skills, experts, personas = catalog
    out = recommend(
        "这是螺杆钻具的成本数据，帮我做个报价分析",
        library_skills=skills, installed=set(), library_experts=experts, personas=personas,
    )
    assert any(re.search(r"pricing|报价", f"{e['id']} {e['name']}") for e in out["experts"])


def test_installed_flag_and_persona_kind(catalog):
    skills, experts, personas = catalog
    out = recommend(
        "帮我做个质量周报",
        library_skills=skills, installed={"quality-weekly-report"},
        library_experts=experts, personas=personas,
    )
    assert out["skills"][0]["installed"] is True
    hits = recommend(
        "失效分析工程师：断口、金相、硬度，判到根因",
        library_skills=skills, installed=set(), library_experts=experts, personas=personas,
    )["experts"]
    assert any(h["kind"] == "persona" and h["id"] == "failure-analysis" for h in hits)


def test_greetings_and_filler_recommend_nothing(catalog):
    skills, experts, personas = catalog
    for text in ("你好", "帮我看看这个", ""):
        out = recommend(text, library_skills=skills, installed=set(), library_experts=experts, personas=personas)
        assert out == {"skills": [], "experts": []}, text
