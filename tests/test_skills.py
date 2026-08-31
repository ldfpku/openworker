"""Agents (Code/Chat) + SKILL.md loader (catalog + load_skill)."""

from __future__ import annotations

from coworker.agent import build_engine
from coworker.agents import AgentContext, chat_agent, code_agent, get_agent
from coworker.providers import ModelCapabilities
from coworker.skills import SkillLoader, skill_catalog_text, skill_tools
from coworker.tools import ToolRegistry
from coworker.tools.shell import LocalExecutor
from coworker.tools.todo import TodoList


class _Stub:
    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()


# -- agents ---------------------------------------------------------------------


def test_code_agent_tools(tmp_path):
    ex = LocalExecutor(cwd=tmp_path, default_timeout=5)
    try:
        ctx = AgentContext(workspace=tmp_path, executor=ex, todo=TodoList())
        names = {getattr(t, "__name__", "?") for t in code_agent().build_tools(ctx)}
        assert {
            "read_file",
            "write_file",
            "git_status",
            "run_shell",
            "todo_write",
        } <= names
    finally:
        ex.close()


def test_chat_agent_has_no_workspace_tools():
    assert chat_agent().build_tools(AgentContext()) == []
    assert chat_agent().requires_folder is False
    assert code_agent().requires_folder is True


def test_get_agent_fallback():
    # Chat is removed (owner 2026-08-21): its id, like any unknown id, falls back to
    # the default persona per the registry.
    assert get_agent("chat").name == "cowork"
    assert get_agent("nope").name == "cowork"


# -- SKILL.md loader ------------------------------------------------------------


def _make_skill(skills_dir, name, desc, body):
    d = skills_dir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n{body}", encoding="utf-8"
    )


def test_skill_loader_catalog_and_load(tmp_path):
    skills_dir = tmp_path / "skills"
    _make_skill(
        skills_dir, "pdf", "extract text from PDFs", "Use pdfplumber to extract text."
    )
    loader = SkillLoader([skills_dir])

    assert loader.catalog() == [
        {"name": "pdf", "description": "extract text from PDFs"}
    ]
    assert "pdf: extract text from PDFs" in skill_catalog_text(loader)

    reg = ToolRegistry()
    reg.register_all(skill_tools(loader))
    loaded = reg.execute("load_skill", {"name": "pdf"})
    assert "pdfplumber" in loaded["instructions"]
    assert reg.execute("load_skill", {"name": "missing"})["error"]


# -- engine assembly per agent --------------------------------------------------


def test_build_engine_chat(tmp_path):
    engine = build_engine(agent=chat_agent(), provider=_Stub())
    assert "load_skill" in engine.registry.names()
    assert "read_file" not in engine.registry.names()
    assert engine.executor is None
    assert engine.agent_name == "chat"


def test_build_engine_code_has_agents_md_and_skills(tmp_path):
    (tmp_path / "AGENTS.md").write_text("PROJECT RULE: prefer pathlib.")
    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        assert "prefer pathlib" in engine.messages[0]["content"]
        assert "todo_write" in engine.registry.names()
        assert "load_skill" in engine.registry.names()
        assert engine.agent_name == "code"
    finally:
        engine.executor.close()


# -- the catalog is a per-turn tax (2026-08-31) ---------------------------------------
# It rides the <system-context> block, which sits AFTER the last cache breakpoint by
# construction — every char is fresh input on every round trip, for the whole session.


def test_catalog_line_is_capped_but_still_decision_useful(tmp_path):
    """A catalog line has one job: let the model decide whether to call load_skill(name).
    The full instructions arrive on that call. Author descriptions are raw frontmatter and
    uncapped — across the shipped expert library they average 413 chars and reach 1,042."""
    from coworker.skills.base import _CATALOG_DESCRIPTION_CHARS, _catalog_line

    short = _catalog_line("tidy", "Formats a file.")
    assert short == "- tidy: Formats a file."  # untouched — shape is unchanged

    long_desc = (
        "Design experiments and studies BEFORE data is collected, choosing a design, "
        "randomizing, blocking, and laying out treatment combinations so that the "
        "results can actually answer the question that motivated them, " + "x " * 400
    )
    line = _catalog_line("experimental-design", long_desc)
    assert len(line) < _CATALOG_DESCRIPTION_CHARS + 60
    assert line.startswith("- experimental-design: Design experiments and studies BEFORE")
    assert line.endswith("…")  # visibly cut, not silently
    # Authors wrap their frontmatter; the catalog must not carry their newlines.
    assert "\n" not in _catalog_line("w", "one\n  two\n  three")
    assert _catalog_line("w", "one\n  two") == "- w: one two"


def test_rescan_reads_disk_only_when_something_changed(tmp_path):
    """`agent.py` rescans once per TURN while building <system-context>. Without a
    fingerprint that re-read and re-parsed every SKILL.md on every round trip to produce
    bytes that are almost always identical."""
    from coworker.skills.base import SkillLoader

    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: first\n---\nbody", encoding="utf-8"
    )
    loader = SkillLoader([tmp_path])
    assert loader.get("alpha").description == "first"

    reads: list[str] = []
    real = type(loader)._discover

    def counting(self, directory):
        reads.append(str(directory))
        return real(self, directory)

    type(loader)._discover = counting
    try:
        loader.rescan()
        loader.rescan()
        assert reads == []  # nothing changed on disk — no re-read at all

        # A NEW skill must still be picked up: load_skill's miss path depends on it.
        (tmp_path / "beta").mkdir()
        (tmp_path / "beta" / "SKILL.md").write_text(
            "---\nname: beta\ndescription: second\n---\nbody", encoding="utf-8"
        )
        loader.rescan()
        assert reads and loader.get("beta") is not None

        reads.clear()
        loader.rescan(force=True)  # the explicit "I just wrote one" path
        assert reads
    finally:
        type(loader)._discover = real
