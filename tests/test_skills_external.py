"""来源与升级 §1–§3 — external skill sources: detection, opt-in, de-duplication, shadowing,
custom folders, invocation modes. Everything runs under a fake home (conftest sets
COWORKER_SKILL_HOME), never the developer's real ~/.agents."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from coworker.skills import reset_shared_loaders
from coworker.skills.external import MANUAL, SourceRegistry, skill_home


def _skill(folder: Path, name: str, description: str = "d", extra: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nBody of {name}.\n",
        encoding="utf-8",
    )
    return folder


def _link(target: Path, link: Path) -> None:
    """A directory link the way agent installers make one: a symlink, or a junction on
    Windows without symlink privilege. Skips the test when neither is possible."""
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        import _winapi

        try:
            _winapi.CreateJunction(str(target), str(link))
            return
        except OSError:
            pass
    pytest.skip("directory links are not available here")


@pytest.fixture(autouse=True)
def _fresh_loaders():
    reset_shared_loaders()
    yield
    reset_shared_loaders()


@pytest.fixture
def home() -> Path:
    h = skill_home()
    h.mkdir(parents=True, exist_ok=True)
    return h


def test_home_is_isolated_for_tests(home):
    assert "skill-home" in str(home)


def test_detects_sources_and_counts_but_everything_starts_off(home):
    _skill(home / ".agents/skills/alpha", "alpha")
    _skill(home / ".agents/skills/beta", "beta")
    _skill(home / ".kiro/skills/gamma", "gamma")
    (home / ".agents/skills/not-a-skill").mkdir()
    reg = SourceRegistry()
    rows = {r["id"]: r for r in reg.describe()}
    assert rows["agents"]["exists"] and rows["agents"]["count"] == 2
    assert rows["kiro"]["count"] == 1
    assert rows["codex"]["exists"] is False and rows["codex"]["count"] == 0
    assert not any(r["enabled"] for r in rows.values())
    assert reg.discover() == []  # off means not scanned for use


def test_enable_persists_and_discovers(home):
    _skill(home / ".agents/skills/alpha", "alpha", "first")
    reg = SourceRegistry()
    reg.set_enabled("agents", True)
    again = SourceRegistry()  # a restart
    assert again.is_enabled("agents")
    found = again.discover()
    assert [s.name for s in found] == ["alpha"]
    assert found[0].source_id == "agents" and found[0].description == "first"
    again.set_enabled("agents", False)
    assert SourceRegistry().discover() == []


def test_unknown_source_rejected():
    with pytest.raises(ValueError):
        SourceRegistry().set_enabled("nope", True)


def test_same_folder_through_a_link_counts_once(home):
    real = _skill(home / ".agents/skills/shared", "shared")
    _link(real, home / ".claude/skills/shared")
    reg = SourceRegistry()
    reg.set_enabled("agents", True)
    reg.set_enabled("claude-code", True)
    found = reg.discover()
    assert len(found) == 1
    assert found[0].source_id == "agents" and found[0].also_in == ["claude-code"]


def test_link_only_source_reports_the_real_path(home):
    real = _skill(home / ".agents/skills/shared", "shared")
    _link(real, home / ".claude/skills/shared")
    reg = SourceRegistry()
    reg.set_enabled("claude-code", True)
    (entry,) = reg.discover()
    assert entry.source_id == "claude-code"
    assert entry.real_path == real.resolve()


def test_same_name_different_content_first_source_wins(home):
    _skill(home / ".agents/skills/dup", "dup", "from agents")
    _skill(home / ".kiro/skills/dup", "dup", "from kiro")
    reg = SourceRegistry()
    reg.set_enabled("kiro", True)
    reg.set_enabled("agents", True)
    (entry,) = reg.discover()
    assert entry.description == "from agents" and entry.shadows == ["kiro"]
    # Loader order is lowest priority first, so the same winner comes out of a loader.
    assert reg.loader_dirs() == [home / ".kiro/skills", home / ".agents/skills"]


def test_custom_folder_validation(home, tmp_path):
    reg = SourceRegistry()
    for bad in ("", "relative/path", str(tmp_path / "missing"), str(home)):
        with pytest.raises(ValueError):
            reg.add_custom(bad)
    with pytest.raises(ValueError):
        reg.add_custom(str(Path(tmp_path.anchor)))  # a drive / filesystem root
    state = Path(os.environ["COWORKER_STATE_DIR"])
    (state / "skills").mkdir(parents=True)
    with pytest.raises(ValueError):
        reg.add_custom(str(state / "skills"))
    with pytest.raises(ValueError):
        (home / ".agents/skills").mkdir(parents=True)
        reg.add_custom(str(home / ".agents/skills"))  # already a known source


def test_custom_folder_roundtrip(tmp_path):
    folder = tmp_path / "team-skills"
    _skill(folder / "team-one", "team-one")
    reg = SourceRegistry()
    added = reg.add_custom(str(folder), "团队技能")
    assert added.custom and reg.is_enabled(added.id)  # adding is the opt-in
    assert [s.name for s in SourceRegistry().discover()] == ["team-one"]
    with pytest.raises(ValueError):
        reg.remove_custom("agents")  # built-ins can only be switched off
    reg.remove_custom(added.id)
    assert all(not s.custom for s in SourceRegistry().sources())


def test_unreadable_source_degrades_to_no_skills(home, monkeypatch):
    _skill(home / ".agents/skills/alpha", "alpha")
    reg = SourceRegistry()
    reg.set_enabled("agents", True)
    real_iterdir = Path.iterdir

    def boom(self):
        if self == home / ".agents/skills":
            raise PermissionError(13, "denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    reset_shared_loaders()
    assert reg.discover() == []
    assert {r["id"]: r for r in reg.describe()}["agents"]["count"] == 0


def test_invocation_defaults_to_manual_and_persists():
    reg = SourceRegistry()
    assert reg.invocation("x") == MANUAL
    reg.set_invocation("x", "auto")
    assert SourceRegistry().invocation("x") == "auto"
    reg.set_invocation("x", "manual")
    assert SourceRegistry().invocation("x") == MANUAL
    with pytest.raises(ValueError):
        reg.set_invocation("x", "sometimes")


def test_disable_model_invocation_is_parsed(home):
    _skill(home / ".agents/skills/locked", "locked", extra="disable-model-invocation: true\n")
    reg = SourceRegistry()
    reg.set_enabled("agents", True)
    (entry,) = reg.discover()
    assert entry.disable_model_invocation is True
