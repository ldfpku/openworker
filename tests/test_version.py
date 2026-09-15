"""packaging/write_version.py and coworker's `__version__` plumbing.

The Python backend's `openworker/<version>` User-Agent (see
`coworker/providers/aigateway_provider.py::_user_agent`) used to always say
`openworker/0.0.0` — `coworker/__init__.py` hardcoded it and nothing ever updated it.
The fix makes `surfaces/gui/src-tauri/tauri.conf.json` the single source of truth:
`packaging/write_version.py` reads it and stamps a generated, gitignored
`coworker/_version.py`, which `coworker/__init__.py` imports if present (falling back
to the literal `"dev"` for a plain, unpackaged checkout). These tests cover both the
stamping script directly and the packaged-build import path end to end.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import runpy
import sys
import types
from pathlib import Path

import pytest

import coworker

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REAL_TAURI_CONF = _REPO_ROOT / "surfaces" / "gui" / "src-tauri" / "tauri.conf.json"

# The repo's `packaging/` directory (build/release scripts) is NOT the well-known
# `packaging` PyPI library (version parsing, a near-ubiquitous transitive dependency —
# confirmed installed in this project's venv). A plain `import packaging.write_version`
# would resolve `packaging` to that real, unrelated site-packages distribution instead
# of this directory and fail with ModuleNotFoundError. Load the script by file path
# under a private module name to sidestep the name collision entirely.
_spec = importlib.util.spec_from_file_location(
    "_ow_write_version", _REPO_ROOT / "packaging" / "write_version.py"
)
_write_version_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_write_version_module)
read_app_version = _write_version_module.read_app_version
write_version_module = _write_version_module.write_version_module


def test_read_app_version_reads_the_real_tauri_conf():
    # The real file is the release pipeline's single source of truth (bump-and-tag.yml
    # writes it, release.yml gates the tag on it matching) — assert against it directly
    # rather than a fixture copy, so this test would fail if that file ever regressed
    # back to a placeholder.
    version = read_app_version(_REAL_TAURI_CONF)
    assert re.match(r"^\d+\.\d+\.\d+", version)
    assert version != "0.0.0"


def test_read_app_version_rejects_missing_or_malformed_version(tmp_path):
    bad_missing = tmp_path / "no_version.json"
    bad_missing.write_text(json.dumps({"productName": "OpenWorker"}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_app_version(bad_missing)

    bad_shape = tmp_path / "bad_version.json"
    bad_shape.write_text(json.dumps({"version": "not-a-semver"}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_app_version(bad_shape)

    # A match anchored only at the start (the old `.match()` behaviour) would accept
    # this — four dotted components — as a valid MAJOR.MINOR.PATCH prefix. `fullmatch`
    # must reject the trailing garbage.
    bad_extra_component = tmp_path / "extra_component_version.json"
    bad_extra_component.write_text(json.dumps({"version": "1.2.3.4"}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_app_version(bad_extra_component)

    bad_empty = tmp_path / "empty_version.json"
    bad_empty.write_text(json.dumps({"version": ""}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_app_version(bad_empty)


def test_read_app_version_accepts_semver_prerelease_and_build_suffixes(tmp_path):
    conf = tmp_path / "tauri.conf.json"
    conf.write_text(json.dumps({"version": "1.2.3-rc.1+build.5"}), encoding="utf-8")
    assert read_app_version(conf) == "1.2.3-rc.1+build.5"


def test_write_version_module_round_trips_and_stays_lf(tmp_path):
    target = tmp_path / "_version.py"
    write_version_module("1.2.3", target)

    raw = target.read_bytes()
    assert b"\r" not in raw  # LF only, matching the repo's .gitattributes convention

    namespace = runpy.run_path(str(target))
    assert namespace["__version__"] == "1.2.3"


def test_the_write_version_script_stamps_the_real_app_version_when_run(tmp_path, monkeypatch):
    # Exercise the script's own __main__ block (as `python packaging/write_version.py`
    # does) without touching the real, gitignored coworker/_version.py: point HOME-like
    # path resolution nowhere by running it as a subprocess-free `runpy` invocation
    # against a temp copy of the repo layout it expects (packaging/ + tauri.conf.json).
    fake_repo = tmp_path / "fake_repo"
    (fake_repo / "packaging").mkdir(parents=True)
    (fake_repo / "surfaces" / "gui" / "src-tauri").mkdir(parents=True)
    (fake_repo / "coworker").mkdir(parents=True)
    (fake_repo / "surfaces" / "gui" / "src-tauri" / "tauri.conf.json").write_text(
        json.dumps({"version": "9.8.7"}), encoding="utf-8"
    )
    script_copy = fake_repo / "packaging" / "write_version.py"
    script_copy.write_text(
        (_REPO_ROOT / "packaging" / "write_version.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    captured = {}
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.setdefault("printed", a))
    runpy.run_path(str(script_copy), run_name="__main__")

    assert captured["printed"] == ("9.8.7",)
    generated = fake_repo / "coworker" / "_version.py"
    assert generated.exists()
    ns = runpy.run_path(str(generated))
    assert ns["__version__"] == "9.8.7"


_REAL_VERSION_MODULE = _REPO_ROOT / "coworker" / "_version.py"
_REAL_VERSION_MODULE_BACKUP = _REAL_VERSION_MODULE.with_name("_version.py.review-bak")


@pytest.fixture
def _restore_coworker_version():
    """Reloading `coworker` to exercise the packaged-build import path mutates the
    real, shared `coworker` module object for every other test in the process — undo
    it by reloading again afterwards so later tests see the normal "dev" fallback.

    A real `coworker/_version.py` can genuinely be sitting on disk here — e.g. a
    developer ran `python packaging/write_version.py` or a PyInstaller build earlier in
    this checkout and never cleaned it up. `test_coworker_falls_back_to_dev_when_
    version_module_is_absent` needs the module to be ABSENT regardless, so this fixture
    always renames a pre-existing real file out of the way for the test's duration
    (`os.replace` — a single atomic rename, never a read+delete+rewrite) and renames it
    back afterwards, on top of the sys.modules / reload cleanup every test here needs.
    """
    real_file_was_present = _REAL_VERSION_MODULE.exists()
    if real_file_was_present:
        os.replace(_REAL_VERSION_MODULE, _REAL_VERSION_MODULE_BACKUP)
    try:
        yield
    finally:
        sys.modules.pop("coworker._version", None)
        if real_file_was_present:
            os.replace(_REAL_VERSION_MODULE_BACKUP, _REAL_VERSION_MODULE)
        importlib.reload(coworker)


def test_coworker_reports_the_stamped_version_when_version_module_is_present(
    _restore_coworker_version,
):
    # Simulates what a packaged build sees: coworker/_version.py exists (stamped by
    # packaging/write_version.py, per the spec's pre-Analysis step), so
    # coworker/__init__.py's `from ._version import __version__` succeeds instead of
    # falling back to "dev" — and that is what reaches the User-Agent string. Injected
    # via sys.modules rather than writing the real file, so this test doesn't depend on
    # (or disturb) whatever the fixture above did with any real _version.py on disk.
    sys.modules["coworker._version"] = types.SimpleNamespace(__version__="9.9.9")
    importlib.reload(coworker)
    assert coworker.__version__ == "9.9.9"

    from coworker.providers.aigateway_provider import _user_agent

    assert _user_agent() == "openworker/9.9.9"


def test_coworker_falls_back_to_dev_when_version_module_is_absent(_restore_coworker_version):
    # The fixture already guarantees coworker/_version.py is not on disk (moving aside
    # any real one a prior local `write_version.py`/PyInstaller run left behind), so
    # this assertion holds independent of the developer's working tree state.
    assert not _REAL_VERSION_MODULE.exists()
    sys.modules.pop("coworker._version", None)
    importlib.reload(coworker)
    assert coworker.__version__ == "dev"
