"""开工前核对 — the engine's pre-flight check on a session's first task message.

Before the main model gets its first call, the engine makes ONE cheap structured call to a
utility model (`diagnose`): is this a task at all, what kind, which domain, and how complete
is the brief on the three elements the in-app help teaches (要什么 / 给谁看 / 依据在哪) plus
the calculation/standard dimension (口径标准) that quantitative work cannot start without.
Deterministic code (`decide`) then turns the weak dimensions into ≤4 grouped multiple-choice
questions in the Claude-Code AskUserQuestion shape the existing `ask_user` plumbing renders,
and `render_brief` folds the confirmed answers into a `<task-brief>` the model treats as the
highest-priority statement of the job.

Everything here is pure except `diagnose` (one provider call). The engine owns the gate
(first task message, attended, not a /skill force-run) and the failure policy (any error →
no guidance, the turn proceeds). The manager owns model choice and the catalog candidates.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Optional

from .tools.ask import MAX_GROUPED_QUESTIONS

logger = logging.getLogger("coworker.guidance")

# -- vocabulary -------------------------------------------------------------------

DIMENSIONS = ("deliverable", "audience", "sources", "rules")
HEADERS = {
    "deliverable": "要什么",
    "audience": "给谁看",
    "sources": "依据在哪",
    "rules": "口径标准",
}
SKILL_HEADER = "技能"
QUESTIONS = {
    "deliverable": "这次要交付什么？",
    "audience": "成果主要给谁看？",
    "sources": "依据哪些资料来做？",
    "rules": "按什么口径或标准来做？",
}
SKILL_QUESTION = "用哪个已安装的技能来做？"
DEFAULT_RULES_LABEL = "按常规口径处理"
NO_SKILL_LABEL = "不用技能"

TASK_KINDS = ("归因诊断", "定量核算", "文档生成", "审查纠偏", "数据整理汇总", "其他")
DOMAINS = (
    "生产计划与交付",
    "质量管理",
    "设备与备件",
    "售后与工具资产",
    "工艺与工装",
    "研发与知识产权",
    "安全环保",
    "财务",
    "人事",
    "法务",
    "销售商务",
    "其他",
)

# Shown when the diagnosis names a weak dimension but offers no usable options of its own.
FALLBACK_OPTIONS: dict[str, list[dict[str, str]]] = {
    "deliverable": [
        {"label": "Word 文档", "description": "排好版的成品文件，可直接发出去"},
        {"label": "Excel 表格", "description": "带公式和汇总的数据表"},
        {"label": "聊天里直接回答", "description": "不落文件，先看结论"},
    ],
    "audience": [
        {"label": "自己用或内部同事", "description": "口径直白，细节尽量全"},
        {"label": "部门负责人或管理层", "description": "结论先行，关注成本与风险"},
        {"label": "客户或外部单位", "description": "商务得体，凸显我方可靠与改进"},
    ],
    "sources": [
        {"label": "工作文件夹里的文件", "description": "从已授权的文件夹里读"},
        {"label": "我稍后上传或粘贴", "description": "先按说明开工，资料随后给"},
        {"label": "不需要资料", "description": "凭通用知识与经验完成"},
    ],
    "rules": [
        {"label": DEFAULT_RULES_LABEL, "description": "按公司与行业常规处理，开工前列出假设"},
        {"label": "我来补充", "description": "在下面输入公式、标准或红线"},
    ],
}

DIAGNOSIS_MARKER = "你是「开工前核对」体检员"
DEFAULT_TIMEOUT = 20.0
_MAX_LABEL = 40
_MAX_OPTIONS = 3
_MAX_FIELD = 4000  # chars of any one input section sent to the diagnosis model


# -- inputs -------------------------------------------------------------------------


def shallow_listing(path: str, limit: int = 40) -> list[str]:
    """Top-level names of a root (no dotfiles, sorted, capped) — enough for the diagnosis
    to know whether 「本周的检验记录」 is actually there. Any OS error → []."""
    try:
        with os.scandir(path) as it:
            names = sorted(
                e.name + ("/" if e.is_dir(follow_symlinks=False) else "")
                for e in it
                if not e.name.startswith(".")
            )
    except OSError:
        return []
    return names[:limit]


def build_inputs(
    *,
    user_text: str,
    prior_user_texts: Optional[list[str]] = None,
    attachment_names: Optional[list[str]] = None,
    memories: str = "",
    rules: str = "",
    roots: Optional[list[str]] = None,
    skills_catalog: str = "",
    candidates: Optional[dict[str, list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """The diagnosis call's inputs, with roots expanded to a shallow listing."""
    return {
        "user_text": str(user_text or ""),
        "prior_user_texts": [str(t) for t in (prior_user_texts or []) if str(t).strip()],
        "attachment_names": [str(n) for n in (attachment_names or [])],
        "memories": str(memories or ""),
        "rules": str(rules or ""),
        "roots": [
            {"path": str(r), "listing": shallow_listing(str(r))} for r in (roots or [])
        ],
        "skills_catalog": str(skills_catalog or ""),
        "candidates": {
            "skills": list((candidates or {}).get("skills") or []),
            "experts": list((candidates or {}).get("experts") or []),
        },
    }


# -- the diagnosis call -----------------------------------------------------------

_SYSTEM_PROMPT = (
    DIAGNOSIS_MARKER
    + """。一位制造企业的员工刚把一件活交给 AI 协作代理，你在代理开工之前体检这条交代
是否完整。只输出一个 JSON 对象，不要任何解释、不要 Markdown 围栏。

判断四个要素，每个打分 0–2：
- deliverable（要什么）：交付物与格式是否明确。0 = 没说要什么；1 = 说了方向但没说形式/范围；2 = 清楚。
- audience（给谁看）：受众是否明确（自己/内部/管理层/客户）。
- sources（依据在哪）：依据的文件、数据、附件是否明确或在工作文件夹里能找到。
- rules（口径标准）：计算公式、评判标准、分类口径是否给了。文档生成类按行业常规即可给 2；
  定量核算类（算工资、报价、成本、排产）没给公式/单价/比例时给 0。

规则：
1. 「记忆」「用户规则」里已经写明的事实算作已知：对应要素直接给 2，并把它写进 known。
2. 「工作文件夹」清单里能对上的资料算作已知依据。
3. 弱项（分数 ≤1）要给 1–3 个候选选项（label ≤ 20 字，可带一句 description），
   选项必须来自记忆、文件夹清单、技能描述或行业常规，推荐的放第一个。分数为 2 的要素 options 给空数组。
4. matched_skills 只能从「候选技能」的 id 里选（最多 3 个、按相关度排序），没有合适的给空数组；
   matched_experts 同理只能从「候选专家」的 id 里选（最多 2 个）。
5. 「先前消息」只用来判断这条消息是不是新任务；问候、闲聊、追问上一轮的结果（「改一下格式」）
   都不是任务：is_task 给 false，其余字段可省略。
6. 题干与选项跟随用户消息的语言（中文消息用中文）。
7. layman_flaw：从制造业管理、财务核算或工程专业角度看，交代里是否有明显外行错误（如把固定折旧
   与变动材料混为一谈）；没有给空字符串。noise：材料里是否混杂了明显无关的内容。

JSON 形状：
{"is_task": true, "task_kind": "<归因诊断|定量核算|文档生成|审查纠偏|数据整理汇总|其他>",
 "domain": "<生产计划与交付|质量管理|设备与备件|售后与工具资产|工艺与工装|研发与知识产权|安全环保|财务|人事|法务|销售商务|其他>",
 "scores": {"deliverable": 0, "audience": 0, "sources": 0, "rules": 0},
 "known": {"deliverable": "", "audience": "", "sources": "", "rules": ""},
 "options": {"deliverable": [{"label": "", "description": ""}], "audience": [], "sources": [], "rules": []},
 "noise": false, "layman_flaw": "", "matched_skills": [], "matched_experts": []}"""
)


def _clip(text: str, limit: int = _MAX_FIELD) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "\n…（已截断）"


def diagnosis_messages(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """System + one user message carrying the labelled input sections."""
    sections: list[str] = []
    prior = inputs.get("prior_user_texts") or []
    if prior:
        sections.append("【先前消息（本会话更早的用户消息，仅作判断是否新任务）】\n" + _clip("\n---\n".join(prior), 1500))
    sections.append("【这条消息】\n" + _clip(inputs.get("user_text", "")))
    names = inputs.get("attachment_names") or []
    if names:
        sections.append("【附件】\n" + "\n".join(f"- {n}" for n in names[:20]))
    if inputs.get("memories"):
        sections.append("【记忆（之前会话里记下的事实）】\n" + _clip(inputs["memories"]))
    if inputs.get("rules"):
        sections.append("【用户规则】\n" + _clip(inputs["rules"], 2000))
    roots = inputs.get("roots") or []
    if roots:
        lines = []
        for r in roots[:4]:
            listing = r.get("listing") or []
            lines.append(f"- {r.get('path')}: " + ("、".join(listing) if listing else "（空或不可读）"))
        sections.append("【工作文件夹】\n" + "\n".join(lines))
    if inputs.get("skills_catalog"):
        sections.append("【已安装技能目录】\n" + _clip(inputs["skills_catalog"], 3000))
    cands = inputs.get("candidates") or {}
    skills = cands.get("skills") or []
    if skills:
        sections.append(
            "【候选技能（按相关度；installed 表示已安装）】\n"
            + "\n".join(
                f"- {s.get('id')} [{'installed' if s.get('installed') else 'not installed'}]"
                f"（{s.get('category_name', '')}）: {_clip(str(s.get('description', '')), 160)}"
                for s in skills[:8]
            )
        )
    experts = cands.get("experts") or []
    if experts:
        sections.append(
            "【候选专家】\n"
            + "\n".join(
                f"- {e.get('id')}（{e.get('name', '')}，{'内置协作代理' if e.get('kind') == 'persona' else '专家库'}）: "
                f"{_clip(str(e.get('description', '')), 120)}"
                for e in experts[:5]
            )
        )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(sections)},
    ]


def parse_diagnosis(text: str) -> Optional[dict[str, Any]]:
    """The model's reply as a dict, or None. Strips one ``` fence (reviewer.py precedent),
    falls back to the first {…} span, requires a JSON object."""
    raw = (text or "").strip()
    if not raw:
        return None
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def _score(value: Any) -> int:
    try:
        return max(0, min(2, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _label(value: Any, limit: int = _MAX_LABEL) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _options(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for opt in value if isinstance(value, list) else []:
        if isinstance(opt, dict):
            label = _label(opt.get("label"))
            desc = _label(opt.get("description"), 80)
        else:
            label, desc = _label(opt), ""
        if not label or label in seen:
            continue
        seen.add(label)
        out.append({"label": label, "description": desc})
        if len(out) >= _MAX_OPTIONS:
            break
    return out


def normalize_diagnosis(
    data: Optional[dict[str, Any]],
    candidates: Optional[dict[str, list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """A diagnosis dict every consumer can trust: scores clamped to 0–2, ≤3 options per
    dimension, unknown skill/expert ids dropped, vocabulary coerced to the fixed lists."""
    data = data if isinstance(data, dict) else {}
    cands = candidates or {}
    skill_ids = {str(s.get("id") or s.get("name")) for s in cands.get("skills") or []}
    expert_ids = {str(e.get("id")) for e in cands.get("experts") or []}
    scores_in = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    known_in = data.get("known") if isinstance(data.get("known"), dict) else {}
    options_in = data.get("options") if isinstance(data.get("options"), dict) else {}
    task_kind = _label(data.get("task_kind"))
    domain = _label(data.get("domain"))
    return {
        "is_task": bool(data.get("is_task", False)),
        "task_kind": task_kind if task_kind in TASK_KINDS else "其他",
        "domain": domain if domain in DOMAINS else "其他",
        "scores": {d: _score(scores_in.get(d)) for d in DIMENSIONS},
        "known": {d: _label(known_in.get(d), 120) for d in DIMENSIONS},
        "options": {d: _options(options_in.get(d)) for d in DIMENSIONS},
        "noise": bool(data.get("noise", False)),
        "layman_flaw": _label(data.get("layman_flaw"), 160),
        "matched_skills": [
            str(s)
            for s in (data.get("matched_skills") or [])
            if isinstance(s, str) and s in skill_ids
        ][:3],
        "matched_experts": [
            str(e)
            for e in (data.get("matched_experts") or [])
            if isinstance(e, str) and e in expert_ids
        ][:2],
    }


def diagnose(
    provider: Any,
    model: str,
    inputs: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[dict[str, Any]]:
    """One non-streaming completion (same knobs as the auto-title call) → normalized
    diagnosis, or None when the reply is unusable. Raises nothing of its own: provider
    errors propagate so the engine can log and skip."""
    # No `temperature`: the Anthropic sub-client rejects it when a gateway provider is
    # called directly (headless use); the fixed JSON shape + effort "none" is enough.
    turn = provider.complete(
        model=model,
        messages=diagnosis_messages(inputs),
        max_tokens=1200,
        reasoning_effort="none",
        timeout=timeout,
    )
    parsed = parse_diagnosis(getattr(turn, "text", None) or "")
    if parsed is None:
        return None
    return normalize_diagnosis(parsed, inputs.get("candidates"))


# -- deciding what to ask -------------------------------------------------------------


def _question(dim: str, diagnosis: dict[str, Any]) -> dict[str, Any]:
    opts = [dict(o) for o in diagnosis["options"].get(dim) or []]
    if not opts:
        opts = [dict(o) for o in FALLBACK_OPTIONS[dim]]
    elif dim == "rules" and all(o["label"] != DEFAULT_RULES_LABEL for o in opts):
        opts = opts[: _MAX_OPTIONS] + [dict(FALLBACK_OPTIONS["rules"][0])]
    opts[0]["recommended"] = True
    return {
        "question": QUESTIONS[dim],
        "header": HEADERS[dim],
        "options": opts,
        "allow_text": True,
        "multi": dim == "sources",
    }


def decide(
    diagnosis: dict[str, Any],
    *,
    installed_matches: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """The grouped `ask_user` questions the brief needs, or [] when the model can just start.

    Weak dimensions (score ≤ 1) are asked worst-first, at most 3 (2 when a skill question
    is also due) so the card never exceeds MAX_GROUPED_QUESTIONS. The skill question is
    asked when a weak dimension exists or when 2+ installed skills match; a fully clear
    brief with one obvious installed match skips the card and the brief names the skill."""
    if not diagnosis.get("is_task"):
        return []
    installed = [m for m in (installed_matches or []) if m.get("name")]
    scores = diagnosis.get("scores") or {}
    weak = sorted(
        (d for d in DIMENSIONS if scores.get(d, 0) <= 1),
        key=lambda d: (scores.get(d, 0), DIMENSIONS.index(d)),
    )
    ask_skill = bool(installed) and (bool(weak) or len(installed) >= 2)
    budget = MAX_GROUPED_QUESTIONS - (1 if ask_skill else 0)
    questions = [_question(d, diagnosis) for d in weak[: min(3, budget)]]
    if ask_skill:
        opts = [
            {
                "label": str(m["name"]),
                "description": _label(m.get("description"), 80),
                **({"recommended": True} if i == 0 else {}),
            }
            for i, m in enumerate(installed[:3])
        ]
        opts.append({"label": NO_SKILL_LABEL, "description": "按通用做法直接做"})
        questions.append(
            {
                "question": SKILL_QUESTION,
                "header": SKILL_HEADER,
                "options": opts,
                "allow_text": False,
                "multi": False,
            }
        )
    return questions


def brief_meta(
    diagnosis: dict[str, Any],
    candidates: Optional[dict[str, list[dict[str, Any]]]] = None,
    *,
    installed: Optional[set[str]] = None,
) -> dict[str, Any]:
    """The compact, model-visible metadata persisted in the synthetic tool call (ids and
    short labels only — it is replayed with the history every turn)."""
    cands = candidates or {}
    by_skill = {str(s.get("id") or s.get("name")): s for s in cands.get("skills") or []}
    by_expert = {str(e.get("id")): e for e in cands.get("experts") or []}
    installed = installed or set()
    return {
        "task_kind": diagnosis.get("task_kind", "其他"),
        "domain": diagnosis.get("domain", "其他"),
        "scores": dict(diagnosis.get("scores") or {}),
        "known": {k: v for k, v in (diagnosis.get("known") or {}).items() if v},
        "layman_flaw": diagnosis.get("layman_flaw", ""),
        "noise": bool(diagnosis.get("noise")),
        "skills": [
            {
                "name": sid,
                "installed": bool(by_skill.get(sid, {}).get("installed")) or sid in installed,
            }
            for sid in diagnosis.get("matched_skills") or []
        ],
        "experts": [
            {
                "id": eid,
                "name": str(by_expert.get(eid, {}).get("name") or eid),
                "kind": str(by_expert.get(eid, {}).get("kind") or "library"),
            }
            for eid in diagnosis.get("matched_experts") or []
        ],
    }


def ask_args(
    questions: list[dict[str, Any]], meta: dict[str, Any]
) -> dict[str, Any]:
    """Arguments of the synthetic `ask_user` call: the questions the card renders plus the
    brief metadata `finish_preflight` needs on the way back (also on a durable resume)."""
    return {"questions": questions, "preflight": True, "brief": meta}


# -- the brief ---------------------------------------------------------------------------


def _answer_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(v) for v in value if str(v).strip())
    return str(value or "").strip()


def render_brief(meta: Optional[dict[str, Any]], result: Optional[dict[str, Any]]) -> str:
    """The `<task-brief>` block. Each dimension is tagged 已确认 (the user picked or typed
    it), 已明确 (the diagnosis found it clear — from the message, memory, the folder or a
    skill description, so not necessarily the user's own words) or 默认口径 (not asked, or
    the user skipped the card). Tolerates a missing or malformed `meta`."""
    meta = meta if isinstance(meta, dict) else {}
    result = result if isinstance(result, dict) else {}
    answers = result.get("answers") if isinstance(result.get("answers"), dict) else {}
    skipped = bool(result.get("skipped"))
    known = meta.get("known") if isinstance(meta.get("known"), dict) else {}
    scores = meta.get("scores") if isinstance(meta.get("scores"), dict) else {}

    lines = [
        "<task-brief>",
        "开工前核对：引擎在你开工前与用户核对了任务要素。标「已确认」的内容是用户的决定，"
        "优先级高于你自己的推断；标「默认口径」的要素按公司与行业常规处理，并在开工时先用一行列出前置假设。",
        f"任务类型：{meta.get('task_kind', '其他')} · 领域：{meta.get('domain', '其他')}",
    ]
    for dim in DIMENSIONS:
        header = HEADERS[dim]
        answered = _answer_text(answers.get(header))
        if answered:
            lines.append(f"{header}：{answered}（已确认）")
        elif known.get(dim):
            lines.append(f"{header}：{known[dim]}（已明确）")
        elif scores.get(dim, 0) >= 2:
            continue
        else:
            lines.append(f"{header}：未说明（默认口径）")

    skill_pick = _answer_text(answers.get(SKILL_HEADER))
    skills = [s for s in (meta.get("skills") or []) if isinstance(s, dict)]
    installed = [s["name"] for s in skills if s.get("installed") and s.get("name")]
    not_installed = [s["name"] for s in skills if not s.get("installed") and s.get("name")]
    if skill_pick and skill_pick != NO_SKILL_LABEL:
        lines.append(f'技能：先调用 load_skill("{skill_pick}") 再开工（已确认）')
    elif skill_pick == NO_SKILL_LABEL:
        lines.append("技能：用户选择不用技能（已确认）")
    elif installed:
        lines.append(f'技能：先调用 load_skill("{installed[0]}") 再开工（已安装、与任务匹配）')
    if not_installed:
        lines.append(
            "推荐但未安装的技能：" + "、".join(not_installed) + "（用户可在 专家库 ▸ 技能 安装；提一句即可，不要替用户安装）"
        )
    experts = [e for e in (meta.get("experts") or []) if isinstance(e, dict) and e.get("name")]
    if experts:
        lines.append(
            "推荐专家："
            + "、".join(
                f"{e['name']}（{'内置协作代理' if e.get('kind') == 'persona' else '专家库'}）"
                for e in experts
            )
            + "——如任务更适合由专家主持，提一句用户可新开会话选用"
        )
    if meta.get("layman_flaw"):
        lines.append(f"可能的误区：{meta['layman_flaw']}——开工前向用户核对口径，不要默默沿用")
    if meta.get("noise"):
        lines.append("材料里可能混有与本任务无关的内容：只用与任务相关的部分，并说明忽略了什么")
    if skipped:
        lines.append(
            "用户选择「跳过，按默认口径直接做」：以上未确认的要素一律按常规处理，开工时先列出前置假设，不要再追问。"
        )
    lines.append("</task-brief>")
    return "\n".join(lines)


def finish_preflight(args: Optional[dict[str, Any]], result: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The tool result the model sees for a pre-flight ask: the answers plus the rendered
    brief. Runs on the persisted arguments too (durable resume), so it must cope with a
    missing or malformed `brief`."""
    args = args if isinstance(args, dict) else {}
    result = dict(result) if isinstance(result, dict) else {}
    result["brief"] = render_brief(args.get("brief"), result)
    return result


PreflightRecommender = Callable[[str], dict[str, list[dict[str, Any]]]]
