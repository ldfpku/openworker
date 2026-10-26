"""In-project files that run later, and OpenWorker's own settings, are matched regardless
of letter case where the file system ignores case (OPE-231).

Windows and macOS (by default) treat `.GIT/hooks` and `.git/hooks` as the same folder,
but `Path.resolve()` only restores the on-disk case for parts that already exist. A
target that doesn't exist yet keeps whatever case the agent typed, so the string match
has to fold case itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from coworker import permissions
from coworker.permissions import Mode, PermissionEngine, _is_protected_in_project

_MARKER_TARGETS = [
    ".git/hooks/pre-commit",
    ".github/workflows/ci.yml",
    ".gitlab-ci.yml",
    ".vscode/tasks.json",
    ".coworker/config.toml",
    # OPE-231: run by a build backend, env tool, git or a hook manager without being named
    "setup.py",
    ".envrc",
    ".gitattributes",
    ".pre-commit-config.yaml",
    "tox.ini",
    ".devcontainer/devcontainer.json",
    ".husky/pre-push",
    ".circleci/config.yml",
    # read into every session's system prompt (coworker/project.py)
    "AGENTS.md",
]


def _variants(path: str) -> list[str]:
    return [path, path.upper(), "".join(c.upper() if i % 2 else c for i, c in enumerate(path))]


def _gate(tmp_path: Path, mode: Mode = Mode.AUTO_APPROVE) -> PermissionEngine:
    return PermissionEngine(workspace_root=tmp_path, mode=mode)


@pytest.fixture
def case_insensitive(monkeypatch):
    monkeypatch.setattr(permissions, "_case_insensitive_fs", lambda: True)


@pytest.fixture
def case_sensitive(monkeypatch):
    monkeypatch.setattr(permissions, "_case_insensitive_fs", lambda: False)


@pytest.mark.parametrize("target", _MARKER_TARGETS)
def test_every_protected_target_is_human_only(tmp_path, target):
    d = _gate(tmp_path).evaluate("write_file", {"path": target, "content": "x"})
    assert not d.allowed and d.needs_user and d.human_only


@pytest.mark.parametrize("target", _MARKER_TARGETS)
def test_any_letter_case_is_protected_on_case_insensitive_file_systems(tmp_path, case_insensitive, target):
    # The targets don't exist on disk, which is exactly when resolve() can't fix the case.
    for variant in _variants(target):
        d = _gate(tmp_path).evaluate("write_file", {"path": variant, "content": "x"})
        assert d.human_only, variant


def test_existing_protected_folder_with_different_case_is_protected(tmp_path, case_insensitive):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    d = _gate(tmp_path).evaluate("write_file", {"path": ".GIT/Hooks/pre-commit", "content": "x"})
    assert d.human_only


def test_case_sensitive_file_systems_keep_exact_matching(tmp_path, case_sensitive):
    # On Linux `.GIT/hooks` is a different folder that git never runs, so it is an
    # ordinary write: no extra card.
    d = _gate(tmp_path).evaluate("write_file", {"path": ".GIT/hooks/pre-commit", "content": "x"})
    assert not d.human_only
    d = _gate(tmp_path).evaluate("write_file", {"path": ".git/hooks/pre-commit", "content": "x"})
    assert d.human_only


@pytest.mark.parametrize(
    "path",
    ["src/package.json.bak", "docs/setup.py.txt", "notes/my-pyproject.toml", "README.md", "src/app.py"],
)
def test_lookalike_names_are_ordinary_writes(tmp_path, case_insensitive, path):
    d = _gate(tmp_path).evaluate("write_file", {"path": path, "content": "x"})
    assert not d.human_only


@pytest.mark.parametrize(
    "path", ["package.json", "packages/web/package.json", "pyproject.toml", "setup.cfg"]
)
def test_package_manifests_stay_with_the_reviewer(tmp_path, case_insensitive, path):
    # Users edit these constantly (versions, dependencies), and the reviewer sees the
    # content, so a version bump the user asked for runs without a card while a new
    # install script can still be caught. Not human-only by design (OPE-231).
    d = _gate(tmp_path).evaluate("replace_in_file", {"path": path, "old": "1.4.1", "new": "1.4.2"})
    assert not d.allowed and d.needs_user and not d.human_only


def test_nested_setup_py_is_protected(tmp_path):
    d = _gate(tmp_path).evaluate("write_file", {"path": "packages/core/setup.py", "content": "x"})
    assert d.human_only


def test_patch_touching_a_protected_file_in_another_case_is_protected(tmp_path, case_insensitive):
    patch = "*** Begin Patch\n*** Add File: .Husky/pre-commit\n+echo hi\n*** End Patch"
    d = _gate(tmp_path).evaluate("apply_patch", {"patch": patch})
    assert d.human_only


@pytest.mark.parametrize("mode", [Mode.INTERACTIVE, Mode.AUTO_APPROVE, Mode.BYPASS_APPROVALS])
def test_protection_holds_in_every_asking_mode(tmp_path, case_insensitive, mode):
    d = _gate(tmp_path, mode).evaluate("write_file", {"path": ".ENVRC", "content": "x"})
    assert not d.allowed and d.human_only


def test_matcher_folds_case_only_when_asked(case_insensitive):
    assert _is_protected_in_project(Path("/w/.GITLAB-CI.YML"))
    assert _is_protected_in_project(Path("/w/.CoWorker/policy.toml"))


def test_matcher_is_exact_on_case_sensitive_systems(case_sensitive):
    assert not _is_protected_in_project(Path("/w/.GITLAB-CI.YML"))
    assert _is_protected_in_project(Path("/w/.gitlab-ci.yml"))


def test_own_settings_write_is_refused_in_any_case(tmp_path, monkeypatch, case_insensitive):
    # OpenWorker's own settings live outside the project; when a root does contain them,
    # a write must be refused whatever case the path is written in.
    state = tmp_path / "state"
    state.mkdir()
    settings = state / "config.toml"  # does not exist yet
    monkeypatch.setattr(permissions, "protected_paths", lambda: [settings])
    gate = PermissionEngine(workspace_root=tmp_path, mode=Mode.AUTO_APPROVE)
    d = gate.evaluate("write_file", {"path": "STATE/CONFIG.TOML", "content": "x"})
    assert not d.allowed and not d.needs_user
    assert "smjworker's own settings" in d.reason
