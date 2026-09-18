# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the bundled `openworker-server` (desktop sidecar).

One-DIR bundle (exe + `_internal/` support folder) shipped via Tauri's `resources` slot.
It used to be a onefile binary in the externalBin slot, but onefile self-extracts its whole
archive to a temp dir on EVERY launch — 6-7s of "Starting coworker…" splash (measured; the
actual Python import is ~0.5s). The wrinkles handled here:
  - aisuite is a regular pip dependency (git-pinned in pyproject.toml); collect coworker +
    aisuite submodules from the venv.
  - uvicorn loads its protocol/lifespan impls dynamically → collect_all.
  - certifi's CA bundle must ship for TLS (OpenAI, web search, Telegram/Slack).
  - messaging extras (slack_bolt, telegram) are optional; collected if importable.

Cross-platform: paths are derived from this spec's own location (SPECPATH), never hardcoded,
so the same spec builds native binaries on macOS, Windows, and Linux. On Windows PyInstaller
appends `.exe` to `name`. The binary is built as a normal console app on every OS — a windowed
(console=False) build leaves sys.stdout/stderr as None, which breaks uvicorn's startup logging
and hangs the server. To avoid a console window flashing in the desktop app, the Tauri shell
spawns this sidecar with the Windows CREATE_NO_WINDOW flag (see src-tauri/src/lib.rs), which
hides the window while keeping stdio intact.
"""

import os
import runpy
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# SPECPATH is injected by PyInstaller and points at this file's directory
# (<repo>/packaging). Derive everything else from it — no hardcoded paths.
PACKAGING = SPECPATH
ROOT = os.path.dirname(PACKAGING)

# coworker/__init__.py reports its own version (used in the `openworker/<version>`
# User-Agent sent to Cloudflare AI Gateway) by importing the generated, gitignored
# coworker/_version.py — falling back to "dev" if it's absent. Stamp it here, from this
# spec's own path (not cwd, which PyInstaller may invoke from anywhere), so it exists
# before Analysis walks coworker/__init__.py — collect_submodules("coworker") below then
# picks up _version.py like any other module.
_write_version_ns = runpy.run_path(os.path.join(PACKAGING, "write_version.py"))
_tauri_conf = Path(ROOT) / "surfaces" / "gui" / "src-tauri" / "tauri.conf.json"
_app_version = _write_version_ns["read_app_version"](_tauri_conf)
_write_version_ns["write_version_module"](_app_version, Path(ROOT) / "coworker" / "_version.py")

IS_WINDOWS = sys.platform == "win32"

# Experimental (use-at-your-own-risk) connectors are excluded from official builds: the code
# is stripped, not just disabled. Self-builders opt in with COWORKER_EXPERIMENTAL=1; the
# loader in coworker/connectors/descriptors.py treats the missing package as a no-op.
INCLUDE_EXPERIMENTAL = os.environ.get("COWORKER_EXPERIMENTAL") == "1"

hiddenimports = []
datas = []
binaries = []

# segno renders the Weixin QR-login PNG; core dep, pure python — always bundled.
# openpyxl writes the .xlsx `write_spreadsheet` delivers (tools/office.py) and markdown_it
# parses the Markdown `write_document` turns into a .docx (tools/document.py); both are
# imported INSIDE the call so a build without them still starts — which is exactly the
# state a packaged app must never ship in, because the frozen backend is the only Python on
# a typical office PC. PyInstaller's analysis does find the lazy imports today; naming them
# here means a trimmed hook or a moved import cannot silently take the feature out of the
# app. (mdurl, markdown_it's one dependency, is a plain module the analysis always sees.)
for pkg in (
    "coworker",
    "aisuite",
    "mcp",
    "ddgs",
    "croniter",
    "docstring_parser",
    "segno",
    "openpyxl",
    "markdown_it",
):
    hiddenimports += collect_submodules(pkg)

# Builtin personas ship as DATA, not code: personas/builtin/<id>/manifest.md plus their
# skills/<name>/SKILL.md. collect_submodules only takes .py files, so without this the
# packaged sidecar starts with NO builtin coworkers — the picker comes up empty and every
# persona-scoped skill silently disappears. (pyproject's package-data covers pip installs;
# PyInstaller needs its own instruction.) Keep this even if the persona set changes — it
# collects whatever non-.py files the package carries.
datas += collect_data_files("coworker")

# The prebuilt library pack (expert prompts + skills, coworker/library/pack.py) ships
# as plain data — PyInstaller extracts it to sys._MEIPASS/library-pack at runtime, which
# is exactly where LibraryPack's bundle-mode lookup expects it. The pack is tracked in
# git, so its absence means a broken checkout — fail the build rather than silently
# shipping an installer whose Expert library comes up empty.
_LIBRARY_PACK = os.path.join(ROOT, "library-pack")
if not os.path.isdir(_LIBRARY_PACK):
    raise SystemExit(
        "library-pack/ not found — the expert library data pack must ship with the app"
    )
datas += [(_LIBRARY_PACK, "library-pack")]

if not INCLUDE_EXPERIMENTAL:
    hiddenimports = [
        m for m in hiddenimports if not m.startswith("coworker.connectors.experimental")
    ]

# `websockets` powers the managed Slack relay client (relay_client.py). It is
# lazy-imported inside a function, so PyInstaller's static analysis misses it —
# collect it explicitly or the packaged relay adapter fails to open its socket.
# `pypdf`/`pypdfium2` are lazy-imported the same way (pdf_support.py) — and pypdfium2
# carries the libpdfium binary, which collect_all is what actually stages.
# `socksio` is httpx's SOCKS transport, imported dynamically only when the user's env
# carries ALL_PROXY=socks5h://… (v2rayN/Clash). Static analysis never sees it, and
# without it EVERY outbound httpx call on such a machine dies with ImportError
# (measured 2026-08-28: sign-out, relay status, model calls — all 500).
# `docx` (python-docx) is the other half of `write_document` and needs collect_all rather
# than collect_submodules: the .docx it produces starts from the package's OWN
# docx/templates/default.docx, plus the .xml part templates beside it. Code-only collection
# imports fine and then raises PackageNotFoundError on the first call — a feature that
# passes every test in CI and fails on the user's machine, where there is no Python to fall
# back on. (pyinstaller-hooks-contrib's hook-docx collects the same data files today; this
# does not depend on that hook still being installed, or still doing it.)
for pkg in (
    "uvicorn",
    "certifi",
    "anyio",
    "websockets",
    "pypdf",
    "pypdfium2",
    "socksio",
    "docx",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Windows has no system tz database; tzdata ships the zoneinfo files the scheduler needs.
if IS_WINDOWS:
    try:
        d, b, h = collect_all("tzdata")
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# [bedrock] extra — boto3 is lazy-imported (bedrock_provider.py) so static analysis
# misses it, and botocore's service-model JSON data dir only ships via collect_all.
for pkg in ("boto3", "botocore"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# [messaging] extra — optional (cryptography decrypts inbound Weixin media)
for pkg in ("slack_bolt", "telegram", "cryptography"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

a = Analysis(
    [os.path.join(PACKAGING, "server_entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "PyQt5", "PySide6"]
    + ([] if INCLUDE_EXPERIMENTAL else ["coworker.connectors.experimental"]),
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="openworker-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Console on every OS: a windowed build nulls stdout/stderr and hangs uvicorn. The Tauri
    # shell hides the window on Windows via CREATE_NO_WINDOW when spawning the sidecar.
    console=True,
    # target_arch left unset → PyInstaller builds for the host architecture.
)
# Onedir: dist/openworker-server/{openworker-server[.exe], _internal/}. The build scripts stage
# this whole folder into src-tauri/binaries/sidecar/ for Tauri's `resources` bundling.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="openworker-server",
)
