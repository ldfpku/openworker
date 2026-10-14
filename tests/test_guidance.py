"""开工前核对 — the pure parts of coworker/guidance.py: parsing the diagnosis, deciding what
to ask, rendering the brief. The engine round-trip lives in test_guidance_engine.py."""

import json

from coworker import guidance as g
from coworker.tools.ask import MAX_GROUPED_QUESTIONS, PREFLIGHT_SKIP, answer_result

CANDS = {
    "skills": [
        {"id": "quality-weekly-report", "name": "quality-weekly-report", "installed": True,
         "category_name": "质量管理", "description": "质量周报", "score": 1.0},
        {"id": "ncr-8d-report", "name": "ncr-8d-report", "installed": False,
         "category_name": "质量管理", "description": "8D 报告", "score": 0.5},
    ],
    "experts": [
        {"id": "quality-system", "name": "质量体系", "kind": "persona", "description": "", "score": 0.4}
    ],
}


def diag(**over):
    base = {
        "is_task": True,
        "task_kind": "数据整理汇总",
        "domain": "质量管理",
        "scores": {"deliverable": 2, "audience": 2, "sources": 2, "rules": 2},
        "known": {"deliverable": "周报", "audience": "", "sources": "", "rules": ""},
        "options": {"deliverable": [], "audience": [], "sources": [], "rules": []},
        "noise": False,
        "layman_flaw": "",
        "matched_skills": [],
        "matched_experts": [],
    }
    base.update(over)
    return g.normalize_diagnosis(base, CANDS)


# -- parsing ------------------------------------------------------------------


def test_parse_diagnosis_accepts_fenced_and_prose_wrapped_json():
    body = json.dumps({"is_task": True, "scores": {"deliverable": 1}})
    assert g.parse_diagnosis(f"```json\n{body}\n```")["is_task"] is True
    assert g.parse_diagnosis(f"Here you go: {body} — done.")["scores"] == {"deliverable": 1}
    assert g.parse_diagnosis("") is None
    assert g.parse_diagnosis("not json at all") is None
    assert g.parse_diagnosis("[1, 2]") is None  # a list is not a diagnosis


def test_normalize_clamps_scores_filters_ids_and_caps_options():
    d = g.normalize_diagnosis(
        {
            "is_task": "yes",
            "task_kind": "unknown kind",
            "domain": "质量管理",
            "scores": {"deliverable": 7, "audience": -1, "sources": "1.6", "rules": None},
            "options": {
                "deliverable": ["A", "B", "C", "D", {"label": "A"}],
                "audience": [{"label": "", "description": "blank"}],
            },
            "matched_skills": ["quality-weekly-report", "made-up-skill", 42],
            "matched_experts": ["nobody", "quality-system"],
            "layman_flaw": "x" * 500,
        },
        CANDS,
    )
    assert d["is_task"] is True
    assert d["task_kind"] == "其他" and d["domain"] == "质量管理"
    assert d["scores"] == {"deliverable": 2, "audience": 0, "sources": 2, "rules": 0}
    assert [o["label"] for o in d["options"]["deliverable"]] == ["A", "B", "C"]
    assert d["options"]["audience"] == []
    assert d["matched_skills"] == ["quality-weekly-report"]
    assert d["matched_experts"] == ["quality-system"]
    assert len(d["layman_flaw"]) <= 160


def test_diagnosis_messages_carry_every_section_and_the_marker(tmp_path):
    (tmp_path / "检验记录.xlsx").write_text("", encoding="utf-8")
    (tmp_path / ".hidden").write_text("", encoding="utf-8")
    inputs = g.build_inputs(
        user_text="帮我做个质量周报",
        prior_user_texts=["你好"],
        attachment_names=["上周周报.docx"],
        memories="Known memories:\n- 周报给生产部长",
        rules="写中文",
        roots=[str(tmp_path)],
        skills_catalog="Available skills — …\n- quality-weekly-report: 质量周报",
        candidates=CANDS,
    )
    msgs = g.diagnosis_messages(inputs)
    assert msgs[0]["role"] == "system" and msgs[0]["content"].startswith(g.DIAGNOSIS_MARKER)
    user = msgs[1]["content"]
    for needle in ("帮我做个质量周报", "你好", "上周周报.docx", "生产部长", "写中文",
                   "检验记录.xlsx", "quality-weekly-report", "质量体系", "installed"):
        assert needle in user, needle
    assert ".hidden" not in user  # dotfiles are not listed
    assert g.shallow_listing(str(tmp_path / "nope")) == []


# -- deciding ------------------------------------------------------------------


def test_not_a_task_or_all_clear_asks_nothing():
    assert g.decide(diag(is_task=False)) == []
    assert g.decide(diag()) == []
    # one installed match on a clear brief: no card, the brief names the skill instead
    assert g.decide(diag(), installed_matches=[{"name": "quality-weekly-report"}]) == []


def test_weak_dimensions_become_questions_worst_first_with_recommended_defaults():
    d = diag(
        scores={"deliverable": 1, "audience": 0, "sources": 2, "rules": 1},
        options={
            "deliverable": [{"label": "Word 周报", "description": "沿用上周格式"}],
            "audience": [{"label": "生产部长"}],
            "sources": [],
            "rules": [],
        },
    )
    qs = g.decide(d, installed_matches=[{"name": "quality-weekly-report", "description": "质量周报"}])
    assert [q["header"] for q in qs] == ["给谁看", "要什么", "口径标准", "技能"]
    assert len(qs) <= MAX_GROUPED_QUESTIONS
    audience, deliverable, rules, skill = qs
    assert audience["options"][0] == {"label": "生产部长", "description": "", "recommended": True}
    assert deliverable["options"][0]["label"] == "Word 周报" and deliverable["allow_text"] is True
    # no model options for rules → the fallback set, 按常规口径 recommended
    assert rules["options"][0]["label"] == g.DEFAULT_RULES_LABEL and rules["options"][0]["recommended"]
    assert skill["options"][0] == {"label": "quality-weekly-report", "description": "质量周报", "recommended": True}
    assert skill["options"][-1]["label"] == g.NO_SKILL_LABEL and skill["allow_text"] is False
    assert not any(q["multi"] for q in qs)


def test_sources_is_the_only_multi_select_and_the_card_never_exceeds_four():
    d = diag(scores={"deliverable": 0, "audience": 0, "sources": 0, "rules": 0})
    qs = g.decide(d, installed_matches=[{"name": "a"}, {"name": "b"}])
    assert len(qs) == MAX_GROUPED_QUESTIONS
    assert [q["header"] for q in qs] == ["要什么", "给谁看", "依据在哪", "技能"]
    assert [q["multi"] for q in qs] == [False, False, True, False]
    # without a skill question all three worst dimensions fit, plus nothing else
    assert [q["header"] for q in g.decide(d)] == ["要什么", "给谁看", "依据在哪"]


def test_two_installed_matches_on_a_clear_brief_still_ask_which_skill():
    qs = g.decide(diag(), installed_matches=[{"name": "a"}, {"name": "b"}])
    assert [q["header"] for q in qs] == ["技能"]
    assert [o["label"] for o in qs[0]["options"]] == ["a", "b", g.NO_SKILL_LABEL]


# -- the brief -------------------------------------------------------------------


def test_brief_marks_confirmed_known_and_default_dimensions():
    d = diag(
        scores={"deliverable": 2, "audience": 0, "sources": 1, "rules": 1},
        known={"deliverable": "质量周报", "audience": "", "sources": "", "rules": ""},
        matched_skills=["quality-weekly-report", "ncr-8d-report"],
        matched_experts=["quality-system"],
        layman_flaw="合格率与一次合格率混用",
    )
    meta = g.brief_meta(d, CANDS, installed={"quality-weekly-report"})
    args = g.ask_args(g.decide(d), meta)
    assert args["preflight"] is True and args["brief"]["skills"][0]["installed"] is True
    result = answer_result(
        args["questions"],
        json.dumps({"给谁看": "生产部长", "依据在哪": ["检验记录", "不良品处理单"], "技能": "quality-weekly-report"}),
    )
    out = g.finish_preflight(args, result)
    brief = out["brief"]
    assert brief.startswith("<task-brief>") and brief.endswith("</task-brief>")
    assert "要什么：质量周报（已明确）" in brief
    assert "给谁看：生产部长（已确认）" in brief
    assert "依据在哪：检验记录、不良品处理单（已确认）" in brief
    assert "口径标准：未说明（默认口径）" in brief
    assert 'load_skill("quality-weekly-report")' in brief
    assert "推荐但未安装的技能：ncr-8d-report" in brief
    assert "推荐专家：质量体系（内置协作代理）" in brief
    assert "可能的误区：合格率与一次合格率混用" in brief
    assert out["answers"]["依据在哪"] == ["检验记录", "不良品处理单"]


def test_skipped_card_authorizes_defaults_and_tolerates_a_missing_brief():
    result = answer_result([{"question": "q", "header": "要什么"}], PREFLIGHT_SKIP)
    assert result == {"answers": {}, "skipped": True}
    out = g.finish_preflight({"questions": []}, result)  # no `brief` meta at all
    assert "跳过" in out["brief"] and "前置假设" in out["brief"]
    assert out["skipped"] is True
    # garbage meta/result never raise
    assert "<task-brief>" in g.render_brief("nope", None)


def test_no_skill_choice_is_recorded():
    meta = g.brief_meta(diag(matched_skills=["quality-weekly-report"]), CANDS)
    brief = g.render_brief(meta, {"answers": {"技能": g.NO_SKILL_LABEL}})
    assert "用户选择不用技能" in brief and "load_skill" not in brief
