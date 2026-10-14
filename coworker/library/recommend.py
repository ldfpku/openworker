"""Catalog recommender for the pre-flight check (coworker/guidance.py).

Given the user's first message, rank the library's skills, the library's experts and the
built-in personas by lexical overlap, so the diagnosis model gets a SHORT list of candidates
to confirm instead of the whole 233-skill catalog. Pure functions, no I/O: the manager
assembles the rows (`SessionManager.recommend_for`) and this module only scores them.

Scoring is deliberately simple — Chinese character bigrams plus lowercase ASCII words,
weighted by field (name > category > description) and by inverse document frequency over
the supplied rows (so 「的」「用户」「生成」 stop dominating), length-normalised so a long
description does not outrank a short exact name. It is a pre-filter, not the decision: the
diagnosis model picks from these candidates and code validates the pick against them.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal

_ASCII_WORD = re.compile(r"[a-z0-9][a-z0-9_]+")
_CJK = re.compile(r"[㐀-鿿]")

# Query-side stop bigrams: the connective tissue of a Chinese request (「帮我做个…」「分析一下
# 这个…」) that every skill description also contains in passing. Dropped from the QUERY only;
# documents keep them so idf still sees them.
_STOP = frozenset(
    "帮我 我做 做个 做一 一下 一个 一份 这个 这份 这是 这根 什么 为什么 怎么 可以 请你 你好 "
    "我想 我要 需要 给我 看看 一看 下这 个的 的一 的这 以及 或者 还是 然后".split()
)


def tokenize(text: str, *, query: bool = False) -> set[str]:
    """Character bigrams for runs of CJK text, lowercase words (≥2 chars) for ASCII.
    「质量周报」 → {质量, 量周, 周报}; "quality-weekly-report" → {quality, weekly, report}.
    `query=True` also drops the request's filler bigrams (`_STOP`)."""
    if not text:
        return set()
    toks = _tokenize(text)
    return toks - _STOP if query else toks


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    lowered = text.lower()
    out.update(_ASCII_WORD.findall(lowered))
    run: list[str] = []
    for ch in lowered + " ":
        if _CJK.match(ch):
            run.append(ch)
            continue
        if len(run) >= 2:
            out.update(run[i] + run[i + 1] for i in range(len(run) - 1))
        elif len(run) == 1:
            out.add(run[0])
        run = []
    return out


@dataclass(frozen=True)
class SkillHit:
    id: str
    name: str
    category_name: str
    description: str
    installed: bool
    score: float


@dataclass(frozen=True)
class ExpertHit:
    id: str
    name: str
    kind: Literal["library", "persona"]
    description: str
    score: float


@dataclass(frozen=True)
class _Doc:
    key: str
    fields: tuple[tuple[set[str], float], ...]  # (tokens, weight)
    size: int  # distinct tokens across fields, for length normalisation


def _doc(key: str, parts: Iterable[tuple[str, float]]) -> _Doc:
    fields = []
    everything: set[str] = set()
    for text, weight in parts:
        toks = tokenize(str(text or ""))
        if toks:
            fields.append((toks, weight))
            everything |= toks
    return _Doc(key=key, fields=tuple(fields), size=max(1, len(everything)))


def _score(query: set[str], doc: _Doc, idf: dict[str, float]) -> float:
    if not query or not doc.fields:
        return 0.0
    total = 0.0
    for toks, weight in doc.fields:
        for tok in query & toks:
            total += weight * idf.get(tok, 1.0)
    # Length normalisation: log, not sqrt — a 150-character description must still be able
    # to outrank a bare name, it just must not win on bulk alone.
    return total / math.log(2 + doc.size)


def _idf(docs: Iterable[_Doc]) -> dict[str, float]:
    df: dict[str, int] = {}
    for doc in docs:
        seen: set[str] = set()
        for toks, _ in doc.fields:
            seen |= toks
        for tok in seen:
            df[tok] = df.get(tok, 0) + 1
    return {tok: 1.0 / math.log(2 + n) for tok, n in df.items()}


def _skill_doc(row: dict[str, Any]) -> _Doc:
    name = str(row.get("name") or row.get("id") or "")
    return _doc(
        name,
        (
            (name.replace("-", " "), 3.0),
            (row.get("categoryName") or "", 2.0),
            (row.get("description_zh") or row.get("description") or "", 1.0),
        ),
    )


def _expert_doc(row: dict[str, Any]) -> _Doc:
    return _doc(
        str(row.get("id") or ""),
        (
            (row.get("name") or "", 3.0),
            (row.get("categoryName") or "", 2.0),
            (row.get("description") or "", 1.0),
        ),
    )


def _persona_doc(row: dict[str, Any]) -> _Doc:
    return _doc(
        str(row.get("id") or ""),
        (
            (row.get("name") or "", 3.0),
            (row.get("tagline") or "", 2.0),
            (row.get("description") or "", 1.0),
        ),
    )


def recommend(
    query: str,
    *,
    library_skills: list[dict[str, Any]],
    installed: set[str],
    library_experts: list[dict[str, Any]],
    personas: list[dict[str, Any]],
    top_skills: int = 5,
    top_experts: int = 3,
    min_score: float = 0.3,
) -> dict[str, list[dict[str, Any]]]:
    """Top candidates for `query` as plain dicts: `{"skills": [SkillHit…], "experts":
    [ExpertHit…]}`, best first. `installed` is the session's effective skill menu (names);
    `personas` rows come from `PersonaRegistry.list_all()` (+ a `description`)."""
    q = tokenize(query, query=True)
    if not q:
        return {"skills": [], "experts": []}

    skill_rows = [r for r in library_skills if isinstance(r, dict)]
    skill_docs = [_skill_doc(r) for r in skill_rows]
    expert_rows = [r for r in library_experts if isinstance(r, dict)]
    persona_rows = [r for r in personas if isinstance(r, dict)]
    expert_docs = [_expert_doc(r) for r in expert_rows] + [
        _persona_doc(r) for r in persona_rows
    ]
    idf = _idf(skill_docs + expert_docs)

    scored_skills = sorted(
        (
            (_score(q, d, idf), r, d)
            for r, d in zip(skill_rows, skill_docs)
        ),
        key=lambda t: -t[0],
    )
    skills: list[SkillHit] = []
    for score, row, doc in scored_skills:
        if score < min_score or len(skills) >= top_skills:
            break
        skills.append(
            SkillHit(
                id=doc.key,
                name=doc.key,
                category_name=str(row.get("categoryName") or ""),
                description=str(row.get("description_zh") or row.get("description") or ""),
                installed=doc.key in installed,
                score=round(score, 4),
            )
        )

    kinds: list[Literal["library", "persona"]] = ["library"] * len(expert_rows) + [
        "persona"
    ] * len(persona_rows)
    scored_experts = sorted(
        (
            (_score(q, d, idf), r, d, k)
            for r, d, k in zip(expert_rows + persona_rows, expert_docs, kinds)
        ),
        key=lambda t: -t[0],
    )
    experts: list[ExpertHit] = []
    for score, row, doc, kind in scored_experts:
        if score < min_score or len(experts) >= top_experts:
            break
        experts.append(
            ExpertHit(
                id=doc.key,
                name=str(row.get("name") or doc.key),
                kind=kind,
                description=str(row.get("description") or row.get("tagline") or ""),
                score=round(score, 4),
            )
        )
    return {"skills": [asdict(h) for h in skills], "experts": [asdict(h) for h in experts]}
