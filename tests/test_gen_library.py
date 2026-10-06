"""packaging/gen_library.py — the library-pack generator, on a tiny four-repo fixture.

What the real pack relies on and nothing else checks:

* only the ``SCIENTIFIC_KEEP`` skills survive from scientific-agent-skills, re-categorized;
* knowledge-work-plugins is packed per Anthropic plugin, with partner-built / excluded /
  non-Anthropic plugins left out;
* skill ids are unique across both sources — a name shared by two plugins (or by a plugin
  and a kept scientific skill) gets the ``<plugin>-`` prefix AND its frontmatter ``name:``
  rewritten, because ``coworker/skills/base.py`` keys the catalog by that line;
* every copied skill carries a ``source:`` provenance line, links that climbed out to the
  plugin root point at in-folder copies, folded ``description: >`` scalars are read;
* a second run keeps the fork's zh layer and writes LF on every platform.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from coworker.skills.base import _parse_skill
from coworker.skills.store import validate_name

_SCRIPT = Path(__file__).resolve().parent.parent / "packaging" / "gen_library.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_library", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _skill(root: Path, name: str, description: str, body: str = "Do the thing.\n", extra_fm: str = "") -> Path:
    folder = root / name
    _write(folder / "SKILL.md", f"---\nname: {name}\ndescription: {description}\n{extra_fm}---\n\n# {name}\n\n{body}")
    return folder


def _plugin(kwp: Path, name: str, author: str = "Anthropic") -> Path:
    folder = kwp / name
    _write(
        folder / ".claude-plugin" / "plugin.json",
        json.dumps({"name": name, "version": "1.0.0", "description": f"{name} plugin", "author": {"name": author}}),
    )
    (folder / "skills").mkdir(parents=True, exist_ok=True)
    return folder


def _build_manufacturing(root: Path) -> Path:
    """Two self-authored (Chinese) skills; the real set is registered in MANUFACTURING_SKILLS."""
    mfg = root / "manufacturing-skills"
    _skill(mfg, "quality-weekly-report", "从检验记录生成质量周报。当用户说「写质量周报」时使用。", body="# 质量周报\n\n按车间汇总。\n")
    _skill(mfg, "delivery-risk-review", "排查交期风险。当用户说「哪些订单要延期」时使用。", body="# 交期风险\n\n交叉比对。\n")
    return mfg


def _build_sources(root: Path) -> Path:
    sources = root / "sources"
    # Experts: a zh/en pair in a dropped category (academic) and one in a kept category
    # (finance), so the pruning rule is exercised in both directions.
    _write(sources / "agency-agents" / "academic" / "geographer.md", "---\nname: Geographer\ndescription: maps\n---\nYou map.\n")
    _write(sources / "agency-agents-zh" / "academic" / "geographer.md", "---\nname: 地理学家\ndescription: 地图\n---\n你画地图。\n")
    _write(sources / "agency-agents" / "finance" / "finance-financial-analyst.md", "---\nname: Financial Analyst\ndescription: numbers\n---\nYou analyse.\n")
    _write(sources / "agency-agents-zh" / "finance" / "finance-financial-analyst.md", "---\nname: 财务分析师\ndescription: 数字\n---\n你分析。\n")
    _write(sources / "agency-agents-zh" / "finance" / "finance-hk-stock-compliance-reviewer.md", "---\nname: 港股合规\ndescription: 港股\n---\n合规。\n")
    _write(sources / "agency-agents" / "LICENSE", "MIT\n")
    _write(sources / "agency-agents-zh" / "LICENSE", "MIT\n")

    sci = sources / "scientific-agent-skills" / "skills"
    _skill(sci, "xlsx", '"Spreadsheets: create or edit .xlsx"', extra_fm="license: MIT\nmetadata:\n  description: nested, must not win\n")
    _skill(sci, "statistical-analysis", "Guided statistical analysis")
    _skill(sci, "scanpy", "single-cell toolkit")  # not in SCIENTIFIC_KEEP → dropped
    _write(sources / "scientific-agent-skills" / "LICENSE.md", "MIT\n")

    kwp = sources / "knowledge-work-plugins"
    _write(kwp / "LICENSE", "Apache License\nVersion 2.0\n")
    ops = _plugin(kwp, "operations")
    _write(ops / "CONNECTORS.md", "# Connectors\n")
    _skill(
        ops / "skills",
        "runbook",
        "Create a runbook. Use when ops needs a procedure.",
        body=(
            "> See [CONNECTORS.md](../../CONNECTORS.md).\n\n"
            "Also [ref](reference/x.md), [sibling](../capacity-plan/reference/notes.md) "
            "and [gone](../capacity-plan/reference/missing.md).\n"
        ),
        extra_fm="argument-hint: \"<task>\"\nallowed-tools: Read, WebFetch\n",
    )
    _write(ops / "skills" / "runbook" / "reference" / "x.md", "Voice: [profile](../../../shared/voice-profile.md)\n")
    _write(ops / "shared" / "voice-profile.md", "# Voice\n\nTone per [CONNECTORS](../CONNECTORS.md).\n")
    _skill(ops / "skills", "capacity-plan", "Plan capacity")
    # A sibling's reference file that itself links to the plugin root — copied files are
    # rewritten too.
    _write(ops / "skills" / "capacity-plan" / "reference" / "notes.md", "Notes. See [shared](../../../shared/voice-profile.md).\n")

    mk = _plugin(kwp, "marketing")
    _skill(mk / "skills", "competitive-brief", "Marketing competitive brief")
    # A sibling that names the renamed skill in prose, in its description and in a path —
    # all three must follow the rename; the unrelated `brand-voice` hyphen compound must not.
    _skill(
        mk / "skills",
        "brand-review",
        "Review content; run competitive-brief first.",
        body="Chain with `competitive-brief` (see skills/competitive-brief/SKILL.md), keep brand-voice.\n",
    )
    pm = _plugin(kwp, "product-management")
    _skill(pm / "skills", "competitive-brief", "PM competitive brief")

    data = _plugin(kwp, "data")
    _skill(data / "skills", "statistical-analysis", "Apply statistical methods")  # collides with the kept sci skill
    folded = data / "skills" / "explore-data"
    _write(
        folded / "SKILL.md",
        "---\nname: explore-data\ndescription: >\n  Profile a dataset to understand\n  its shape. Use when: you have a new file.\n---\n\n# explore\n",
    )

    prod = _plugin(kwp, "productivity")
    _skill(
        prod / "skills",
        "start",
        "Initialize the system",
        body="Copy it from `${CLAUDE_PLUGIN_ROOT}/skills/dashboard.html` to the working directory.\n",
    )
    _write(prod / "skills" / "dashboard.html", "<html></html>\n")

    # Excluded by name, by author, and by nesting under partner-built/.
    pdf = _plugin(kwp, "pdf-viewer")
    _skill(pdf / "skills", "view-pdf", "Interactive PDF viewer")
    apollo = _plugin(kwp / "partner-built", "apollo", author="Apollo.io")
    _skill(apollo / "skills", "prospect", "Find prospects")
    return sources


def _run(gen, sources: Path, out: Path) -> dict:
    argv = sys.argv
    sys.argv = [
        "gen_library", "--sources", str(sources), "--out", str(out),
        "--manufacturing", str(sources.parent / "manufacturing-skills"),
    ]
    try:
        gen.main()
    finally:
        sys.argv = argv
    return json.loads((out / "index.json").read_text(encoding="utf-8"))


def _reduced_keep(gen) -> dict:
    """The fixture ships two of the real keep-list skills; the script refuses to run when a
    listed skill is missing upstream (that is a test of its own below), so the list is
    narrowed to what the fixture has — with the real category tuples."""
    return {k: gen.SCIENTIFIC_KEEP[k] for k in ("xlsx", "statistical-analysis")}


def _reduced_manufacturing(gen) -> dict:
    return {k: gen.MANUFACTURING_SKILLS[k] for k in ("quality-weekly-report", "delivery-risk-review")}


@pytest.fixture
def built(gen, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "SCIENTIFIC_KEEP", _reduced_keep(gen))
    monkeypatch.setattr(gen, "MANUFACTURING_SKILLS", _reduced_manufacturing(gen))
    sources = _build_sources(tmp_path)
    _build_manufacturing(tmp_path)
    out = tmp_path / "library-pack"
    index = _run(gen, sources, out)
    return gen, sources, out, index


def test_skill_set_is_the_keep_list_plus_anthropic_plugins_with_unique_ids(built):
    gen, _sources, out, index = built
    ids = sorted(s["id"] for s in index["skills"])
    assert ids == [
        "brand-review",
        "capacity-plan",
        "data-statistical-analysis",
        "delivery-risk-review",
        "explore-data",
        "marketing-competitive-brief",
        "product-management-competitive-brief",
        "quality-weekly-report",
        "runbook",
        "start",
        "statistical-analysis",
        "xlsx",
    ]
    # Self-authored skills come first: the library page orders its category chips by first
    # appearance, and the manufacturing categories must lead.
    assert [s["id"] for s in index["skills"][:2]] == ["quality-weekly-report", "delivery-risk-review"]
    assert len({s["name"] for s in index["skills"]}) == len(ids)
    for s in index["skills"]:
        validate_name(s["name"])  # every id is an installable folder name
        assert s["name"] == s["id"]
        assert (out / "skills" / s["id"] / "SKILL.md").is_file()
        # The catalog key the agent sees is the frontmatter name — it must equal the folder.
        assert _parse_skill(out / "skills" / s["id"] / "SKILL.md").name == s["id"]
    # Dropped: a scientific skill outside the keep list, the Cowork-only plugin, the partner plugin.
    assert not (out / "skills" / "scanpy").exists()
    assert not (out / "skills" / "view-pdf").exists()
    assert not (out / "skills" / "prospect").exists()
    assert index["generated"].keys() == {"agency-agents", "agency-agents-zh", "scientific-agent-skills", "knowledge-work-plugins"}


def test_entries_carry_source_category_and_parsed_descriptions(built):
    gen, _sources, out, index = built
    by_id = {s["id"]: s for s in index["skills"]}
    sci = by_id["xlsx"]
    assert sci["source"] == gen.SCIENTIFIC_SOURCE and sci["author"] == gen.SCIENTIFIC_AUTHOR
    assert (sci["category"], sci["categoryName"]) == gen.SCIENTIFIC_KEEP["xlsx"][:2]
    assert sci["description"] == "Spreadsheets: create or edit .xlsx"  # quotes dropped, nested line ignored
    assert sci["license"] == "MIT" and "plugin" not in sci
    kwp = by_id["runbook"]
    assert kwp["source"] == gen.KWP_SOURCE and kwp["author"] == "Anthropic" and kwp["plugin"] == "operations"
    assert (kwp["category"], kwp["categoryName"]) == ("operations", gen.KWP_CATEGORY_NAMES["operations"])
    assert kwp["license"] == gen.KWP_LICENSE
    assert kwp["references"] == 1  # the `reference/` spelling counts too
    # A folded `description: >` is read as its text, not as ">".
    assert by_id["explore-data"]["description"] == "Profile a dataset to understand its shape. Use when: you have a new file."
    # The renamed skills keep their own descriptions and plugin.
    assert by_id["marketing-competitive-brief"]["plugin"] == "marketing"
    assert by_id["product-management-competitive-brief"]["description"] == "PM competitive brief"
    assert by_id["data-statistical-analysis"]["category"] == "data"
    assert by_id["statistical-analysis"]["source"] == gen.SCIENTIFIC_SOURCE
    # Self-authored: category from the registry, Chinese description doubles as description_zh.
    mfg = by_id["quality-weekly-report"]
    assert mfg["source"] == gen.MANUFACTURING_SOURCE and mfg["author"] == gen.MANUFACTURING_AUTHOR
    assert mfg["license"] == gen.MANUFACTURING_LICENSE and mfg["lang"] == "zh"
    assert (mfg["category"], mfg["categoryName"]) == ("quality-management", "质量管理")
    assert mfg["description_zh"] == mfg["description"] == "从检验记录生成质量周报。当用户说「写质量周报」时使用。"
    assert f"\nsource: {gen.MANUFACTURING_SOURCE}\n" in (out / "skills" / "quality-weekly-report" / "SKILL.md").read_text(encoding="utf-8")


def test_experts_are_pruned_by_category_and_id(built):
    gen, _sources, out, index = built
    zh = {e["id"]: e for e in index["experts"]["zh"]}
    en = {e["id"]: e for e in index["experts"]["en"]}
    # academic is not a kept category and geographer is not an exception → gone in both libs.
    assert "academic/geographer" not in zh and "academic/geographer" not in en
    assert not (out / "experts" / "zh" / "academic").exists()
    # finance is kept, except the explicitly dropped reviewer.
    assert zh["finance/finance-financial-analyst"]["pair"] is True
    assert en["finance/finance-financial-analyst"]["pair"] is True
    assert "finance/finance-hk-stock-compliance-reviewer" not in zh
    assert (out / "experts" / "zh" / "finance" / "finance-financial-analyst.md").is_file()
    assert not (out / "experts" / "zh" / "finance" / "finance-hk-stock-compliance-reviewer.md").exists()
    attribution = (out / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "中文库保留 1 / 3，英文库保留 1 / 2" in attribution


def test_real_expert_rules_are_well_formed(gen):
    """Every id in the exception lists has the `<category>/<file>` shape and the kept
    categories are real agency-agents category folders."""
    for sid in gen.EXPERT_KEEP_IDS | gen.EXPERT_DROP_IDS:
        category, _, rest = sid.partition("/")
        assert category and rest and "/" not in rest, sid
    assert gen.EXPERT_KEEP_IDS.isdisjoint(gen.EXPERT_DROP_IDS)
    # An exception id inside a kept category would be redundant — keep the lists honest.
    assert all(s.split("/")[0] not in gen.EXPERT_KEEP_CATEGORIES for s in gen.EXPERT_KEEP_IDS)
    assert all(s.split("/")[0] in gen.EXPERT_KEEP_CATEGORIES for s in gen.EXPERT_DROP_IDS)
    for cat in gen.EXPERT_KEEP_CATEGORIES:
        assert cat in gen.ZH_CATEGORY_NAMES or cat == "research", cat
    # The manufacturing registry: every skill maps to a declared category.
    for sid, cat in gen.MANUFACTURING_SKILLS.items():
        validate_name(sid)
        assert cat in gen.MANUFACTURING_CATEGORIES, sid


def test_copied_skills_are_executable_in_place(built):
    gen, _sources, out, _index = built
    runbook = out / "skills" / "runbook"
    md = runbook.joinpath("SKILL.md").read_text(encoding="utf-8")
    fm = md.split("\n---", 1)[0]
    assert f"\nsource: {gen.KWP_SOURCE}" in fm
    assert "argument-hint" in fm and "allowed-tools: Read, WebFetch" in fm  # untouched
    assert "[CONNECTORS.md](CONNECTORS.md)" in md and (runbook / "CONNECTORS.md").is_file()
    assert "[ref](reference/x.md)" in md  # in-skill links untouched
    # A sibling skill's reference file is copied under `<sibling>/` and the link follows;
    # one whose target does not exist upstream is left alone and reported.
    assert "[sibling](capacity-plan/reference/notes.md)" in md
    assert "[gone](../capacity-plan/reference/missing.md)" in md
    notes = (runbook / "capacity-plan" / "reference" / "notes.md").read_text(encoding="utf-8")
    assert "[shared](../../shared/voice-profile.md)" in notes  # copied file rewritten by its own depth
    ref = (runbook / "reference" / "x.md").read_text(encoding="utf-8")
    assert "[profile](../shared/voice-profile.md)" in ref and (runbook / "shared" / "voice-profile.md").is_file()
    # The copied shared file was itself rewritten (it linked the plugin root from depth 1).
    assert "[CONNECTORS](../CONNECTORS.md)" in (runbook / "shared" / "voice-profile.md").read_text(encoding="utf-8")
    start = out / "skills" / "start"
    assert "`dashboard.html`" in (start / "SKILL.md").read_text(encoding="utf-8")
    assert (start / "dashboard.html").is_file()
    # Renamed: the frontmatter name line follows the new id; the sci stamp keeps its name.
    renamed = (out / "skills" / "marketing-competitive-brief" / "SKILL.md").read_text(encoding="utf-8")
    assert renamed.startswith("---\nname: marketing-competitive-brief\n")
    # Prose references inside the same plugin follow the rename — and only whole names.
    sibling = (out / "skills" / "brand-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "description: Review content; run marketing-competitive-brief first." in sibling
    assert "Chain with `marketing-competitive-brief` (see skills/marketing-competitive-brief/SKILL.md), keep brand-voice." in sibling
    assert "competitive-brief" not in sibling.replace("marketing-competitive-brief", "")
    # A plugin with no renames gets no prose rewrites: `capacity-plan` still reads as upstream wrote it.
    assert "capacity-plan" in md and "operations-capacity-plan" not in md
    sci = (out / "skills" / "xlsx" / "SKILL.md").read_text(encoding="utf-8")
    assert sci.startswith("---\nname: xlsx\n") and f"\nsource: {gen.SCIENTIFIC_SOURCE}\n---" in sci
    assert "metadata:\n  description: nested, must not win" in sci  # other frontmatter preserved


def test_attribution_and_licenses_record_what_changed(built):
    gen, _sources, out, _index = built
    attribution = (out / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "https://github.com/anthropics/knowledge-work-plugins" in attribution
    assert "Apache-2.0" in attribution
    assert "`marketing/skills/competitive-brief` → `marketing-competitive-brief`" in attribution
    assert "`data/skills/statistical-analysis` → `data-statistical-analysis`" in attribution
    assert "`brand-review/SKILL.md`" in attribution  # the prose-reference rewrite is recorded
    assert "runbook/SKILL.md -> ../capacity-plan/reference/missing.md" in attribution
    assert "`pdf-viewer`" in attribution and "`partner-built/`" in attribution
    assert "| `xlsx` |" in attribution  # the keep list is printed
    licenses = sorted(p.name for p in (out / "LICENSES").iterdir())
    assert licenses == [
        "agency-agents-LICENSE.txt",
        "agency-agents-zh-LICENSE.txt",
        "knowledge-work-plugins-LICENSE.txt",
        "scientific-agent-skills-LICENSE.md",
    ]


def test_rerun_keeps_the_zh_layer_and_writes_lf(built):
    gen, sources, out, index = built
    # The fork's translation layer lives only in the pack: add some, rebuild, it must survive.
    _write(out / "skills" / "runbook" / "SKILL.zh.md", "---\nname: runbook\n---\n\n# 运行手册\n")
    for s in index["skills"]:
        if s["id"] == "runbook":
            s["description_zh"] = "创建运行手册"
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    again = _run(gen, sources, out)
    row = next(s for s in again["skills"] if s["id"] == "runbook")
    assert row["description_zh"] == "创建运行手册"
    assert "# 运行手册" in (out / "skills" / "runbook" / "SKILL.zh.md").read_text(encoding="utf-8")
    assert again["experts"] == index["experts"] and len(again["skills"]) == len(index["skills"])
    # Everything the script writes is LF, whatever the host's text-mode default is.
    for p in (out / "index.json", out / "ATTRIBUTION.md", out / "skills" / "runbook" / "SKILL.zh.md", out / "skills" / "runbook" / "SKILL.md"):
        assert b"\r\n" not in p.read_bytes(), p


def test_keep_list_entry_missing_upstream_is_an_error(gen, tmp_path, monkeypatch, capsys):
    sources = _build_sources(tmp_path)
    _build_manufacturing(tmp_path)
    monkeypatch.setattr(gen, "MANUFACTURING_SKILLS", _reduced_manufacturing(gen))
    keep = _reduced_keep(gen)
    keep["no-such-skill"] = ("office-docs", "办公文档", "test")
    monkeypatch.setattr(gen, "SCIENTIFIC_KEEP", keep)
    with pytest.raises(SystemExit):
        _run(gen, sources, tmp_path / "out")
    assert "no-such-skill" in capsys.readouterr().err


def test_unregistered_manufacturing_skill_is_an_error(gen, tmp_path, monkeypatch, capsys):
    sources = _build_sources(tmp_path)
    mfg = _build_manufacturing(tmp_path)
    _skill(mfg, "stray-skill", "没登记的技能。当用户说「x」时使用。")
    monkeypatch.setattr(gen, "SCIENTIFIC_KEEP", _reduced_keep(gen))
    monkeypatch.setattr(gen, "MANUFACTURING_SKILLS", _reduced_manufacturing(gen))
    with pytest.raises(SystemExit):
        _run(gen, sources, tmp_path / "out")
    assert "stray-skill" in capsys.readouterr().err


def test_real_keep_list_is_well_formed(gen):
    """The shipped list: unique ids that are valid folder names, four categories, a reason each."""
    assert len(gen.SCIENTIFIC_KEEP) >= 30
    categories = {}
    for sid, (cat, cat_name, reason) in gen.SCIENTIFIC_KEEP.items():
        validate_name(sid)
        assert reason.strip()
        categories.setdefault(cat, cat_name)
        assert categories[cat] == cat_name  # one display name per category id
    assert set(categories) == {"office-docs", "data-analysis", "engineering-quality", "research-decision"}
    for name, reason in gen.KWP_EXCLUDED_PLUGINS.items():
        assert validate_name(name) and reason.strip()
