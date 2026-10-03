from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("_ow_bump_version", _ROOT / "packaging" / "bump_version.py")
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


@pytest.mark.parametrize(
    "current,bump,expected",
    [
        ("0.7.1", "patch", "0.7.2"),
        ("0.7.8", "patch", "0.7.9"),
        ("0.7.9", "patch", "0.8.1"),
        ("0.9.9", "patch", "0.10.1"),
        ("0.19.9", "patch", "0.20.1"),
        ("0.7.4", "minor", "0.8.1"),
        ("0.7.4", "major", "1.0.1"),
    ],
)
def test_next_version(current, bump, expected):
    assert _MODULE.next_version(current, bump) == expected


@pytest.mark.parametrize("current", ["0.6.14", "0.7.0", "0.7.10", "0.07.1", "0.7.1-rc.1", "x", "0.7.1.2", "0.1\u0662.1"])
def test_invalid_release_policy_version_is_rejected(current):
    with pytest.raises(ValueError):
        _MODULE.next_version(current)


def test_unknown_bump_is_rejected():
    with pytest.raises(ValueError):
        _MODULE.next_version("0.7.1", "automatic")


def test_bump_preserves_config_format(tmp_path):
    path = tmp_path / "tauri.conf.json"
    text = '{\n  "version": "0.7.9",\n  "productName": "OpenWorker"\n}\n'
    path.write_text(text, encoding="utf-8")
    assert _MODULE.bump_config(path, "patch") == "0.8.1"
    assert path.read_text(encoding="utf-8") == text.replace("0.7.9", "0.8.1")
    assert json.loads(path.read_text(encoding="utf-8"))["productName"] == "OpenWorker"
