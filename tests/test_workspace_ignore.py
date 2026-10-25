"""Project-open .ignore creation and its shared search/list semantics."""

from __future__ import annotations

from coworker.server.manager import SessionManager
from coworker.tools.files import file_tools
from coworker.tools.search import _py_grep, search_tools
from coworker.workspace_ignore import ensure_workspace_ignore, generated_rules

from test_code_tools import _seed


def test_generated_rules_use_only_root_project_markers(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    (tmp_path / "App.csproj").write_text("<Project />", encoding="utf-8")

    rules = generated_rules(tmp_path)

    assert ".venv/" in rules
    assert ".next/" in rules
    assert "target/" in rules
    assert "bin/" in rules and "obj/" in rules
    assert "!.env.example" in rules
    assert len(rules) == len(set(rules))


def test_creation_is_idempotent_and_existing_user_files_win(tmp_path):
    created = ensure_workspace_ignore(tmp_path)
    assert created["status"] == "created"
    first = (tmp_path / ".ignore").read_text(encoding="utf-8")
    assert ensure_workspace_ignore(tmp_path)["status"] == "existing"
    assert (tmp_path / ".ignore").read_text(encoding="utf-8") == first

    (tmp_path / ".ignore").write_text("# user rules\n", encoding="utf-8")
    assert ensure_workspace_ignore(tmp_path)["status"] == "existing"
    assert (tmp_path / ".ignore").read_text(encoding="utf-8") == "# user rules\n"

    other = tmp_path / "other"
    other.mkdir()
    (other / ".rgignore").write_text("vendor/\n", encoding="utf-8")
    assert ensure_workspace_ignore(other)["status"] == "existing"
    assert not (other / ".ignore").exists()


def test_creation_can_be_disabled(tmp_path):
    assert ensure_workspace_ignore(tmp_path, enabled=False)["status"] == "disabled"
    assert not (tmp_path / ".ignore").exists()


def test_workspace_open_creates_ignore_and_setting_disables_it(tmp_path):
    mgr = SessionManager(workspace=tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    result = mgr.open_workspace(str(project))
    assert result["ok"] and result["ignore_file"]["status"] == "created"
    assert (project / ".ignore").is_file()
    assert mgr.get_settings()["auto_workspace_ignore"] is True

    assert mgr.set_auto_workspace_ignore(False)["ok"]
    disabled = tmp_path / "disabled"
    disabled.mkdir()
    result = mgr.open_workspace(str(disabled))
    assert result["ignore_file"]["status"] == "disabled"
    assert not (disabled / ".ignore").exists()


def _ignored_tree(tmp_path):
    _seed(tmp_path)
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "noise.txt").write_text("hello generated\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=hello\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("SECRET=hello-example\n", encoding="utf-8")
    (tmp_path / ".ignore").write_text("generated/\n.env\n.env.*\n!.env.example\n", encoding="utf-8")


def test_python_grep_honours_ignore_files_but_explicit_files_remain_readable(tmp_path):
    _ignored_tree(tmp_path)

    result = _py_grep(tmp_path.resolve(), tmp_path.resolve(), "hello", None, 100)
    files = {match["file"] for match in result["matches"]}
    assert "a.py" in files and "b.txt" in files
    assert ".env.example" in files
    assert not any("generated" in name or name == ".env" for name in files)

    explicit = search_tools(str(tmp_path))[0](pattern="SECRET", path=".env")
    assert explicit["count"] == 1


def test_list_files_prunes_ignored_directories_and_files(tmp_path):
    _ignored_tree(tmp_path)
    listing = file_tools(str(tmp_path))[1](path=".", recursive=True)

    assert "a.py" in listing and ".env.example" in listing
    assert not any(name.startswith("generated") for name in listing)
    assert ".env" not in listing
    assert not any("node_modules" in name for name in listing)


def test_subdirectory_search_passes_root_ignore_file_to_ripgrep(tmp_path, monkeypatch):
    import coworker.tools.search as search
    from types import SimpleNamespace

    _ignored_tree(tmp_path)
    (tmp_path / "src").mkdir()
    commands = []
    monkeypatch.setattr(search.shutil, "which", lambda name: "rg")
    monkeypatch.setattr(
        search.subprocess,
        "run",
        lambda cmd, **kwargs: commands.append(cmd)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    search_tools(str(tmp_path))[0](pattern="hello", path="src")

    command = commands[0]
    index = command.index("--ignore-file")
    assert command[index + 1] == str(tmp_path / ".ignore")
