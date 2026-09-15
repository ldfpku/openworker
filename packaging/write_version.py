#!/usr/bin/env python3
"""Stamp `coworker/_version.py` from the Tauri app version at packaging time.

`surfaces/gui/src-tauri/tauri.conf.json`'s `"version"` field is the single source of
truth for the app's version (the release pipeline's `bump-and-tag.yml` writes it, and
`release.yml` gates on the tag matching it — see those workflows). The Python backend
never had its own copy: `coworker/__init__.py` shipped a hardcoded `__version__ =
"0.0.0"`, so the `openworker/<version>` User-Agent sent to Cloudflare AI Gateway
(`coworker/providers/aigateway_provider.py::_user_agent`) always reported `0.0.0` in
packaged builds, and every session in the gateway's own logs looked identical.

This script reads the Tauri version and writes it into `coworker/_version.py`, a
generated, gitignored module that `coworker/__init__.py` imports if present, falling
back to `"dev"` in an unpackaged checkout. Run manually for a quick check, or invoked
from `packaging/openworker-server.spec` so PyInstaller bundles a real version into
every packaged sidecar.

    python packaging/write_version.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# MAJOR.MINOR.PATCH with optional semver pre-release (-rc.1) and/or build (+build.5)
# suffixes, e.g. "1.2.3-rc.1+build.5". fullmatch (not match) so trailing garbage like
# "1.2.3.4" is rejected rather than accepted on a partial prefix match.
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

_GENERATED_HEADER = (
    "# 由 packaging/write_version.py 在打包时生成，勿手改、勿提交。\n"
)


def read_app_version(tauri_conf: Path) -> str:
    """Return the app version string from a Tauri config file.

    Raises ValueError if the file has no non-empty `version`, or if it does not look
    like a semantic version (`MAJOR.MINOR.PATCH[...]`) — a malformed or missing version
    here means the release pipeline's single source of truth is broken, so failing loud
    beats silently stamping a bogus/empty value into the packaged backend.
    """
    data = json.loads(tauri_conf.read_text(encoding="utf-8"))
    version = data.get("version")
    if not version or not isinstance(version, str):
        raise ValueError(f"{tauri_conf}: missing or empty \"version\"")
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(
            f"{tauri_conf}: version {version!r} does not look like MAJOR.MINOR.PATCH"
        )
    return version


def write_version_module(version: str, target: Path) -> None:
    """Write `target` as a Python module defining `__version__ = "<version>"`.

    Written with explicit UTF-8 and `\\n` line endings regardless of platform, so the
    generated file matches this repo's `.gitattributes` LF convention even though it is
    gitignored (a packaged build's diagnostics/tests may still diff it).
    """
    content = f'{_GENERATED_HEADER}__version__ = "{version}"\n'
    target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    _TAURI_CONF = _REPO_ROOT / "surfaces" / "gui" / "src-tauri" / "tauri.conf.json"
    _TARGET = _REPO_ROOT / "coworker" / "_version.py"

    _version = read_app_version(_TAURI_CONF)
    write_version_module(_version, _TARGET)
    print(_version)
