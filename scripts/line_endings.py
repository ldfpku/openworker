# ///
# Line-ending handling for cross-platform (Windows / macOS / Linux) text I/O.
#
# Modes (mirrors VS Code's `files.eol` + Git `eol` attribute):
#   - "auto"   : detect on read, write back whatever was detected
#   - "lf"     : normalise to LF (\n)            — Git / macOS / Linux
#   - "crlf"   : normalise to CRLF (\r\n)        — Windows
#   - "cr"     : normalise to CR (\r)            — classic Mac (rare)
#
# Usage (any of the modes):
#   python -m scripts.line_endings <file> [--eol auto|lf|crlf|cr] [--dry-run]
#
# Or import:
#   from scripts.line_endings import normalize, detect_eol
#
# Do NOT edit existing files with this module — it is reference code.
# The point is to adopt ONE consistent mode across the repo.
# ///

from __future__ import annotations

import sys
from pathlib import Path

# Extensions we know are binary and never touch (defence in depth on top of the
# `.gitattributes binary` list). detect_eol is byte-based and would happily
# "normalise" a PNG by rewriting its header bytes — so scan_tracked refuses
# to touch these even if the byte heuristic below slips through.
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".icns",
    ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".pdf",
    ".zip", ".tar", ".gz", ".bin", ".pyc",
    ".tiff", ".tif", ".bmp", ".mp3", ".mp4", ".wav", ".ogg",
    ".sqlite", ".db", ".pyd", ".dll", ".exe",
}


def looks_binary(path: str | Path) -> bool:
    """True if *path* is binary by extension or by its leading magic bytes."""
    ext = Path(path).suffix.lower()
    if ext in BINARY_EXT:
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except OSError:
        return True
    # NUL byte in the first block → binary (text files never contain NUL).
    if b"\x00" in head[:16]:
        return True
    # Well-known binary magic bytes.
    magic = (b"%PDF", b"\x1f\x8b", b"PK\x03\x04", b"BM", b"\x89PNG",
             b"RIFF", b"OggS", b"ftyp", b"\x4d\x58", b"ID\x03")
    if any(head.startswith(m) for m in magic):
        return True
    return False


# --- detection ---------------------------------------------------------------

def detect_eol(path: str | Path) -> str:
    """Detect line-ending style of a file. Returns 'lf', 'crlf', 'cr' or 'mixed'."""
    p = Path(path)
    raw = p.read_bytes()[:4096]  # first 4 KB is enough to decide
    if b"\r\n" in raw:
        return "crlf"
    if b"\r" in raw:
        return "cr"
    if b"\n" in raw:
        return "lf"
    return "lf"  # single line, no newline — default to LF


def is_mixed(path: str | Path) -> bool:
    """True if the file has more than one line-ending style."""
    raw = Path(path).read_bytes()
    has_crlf = b"\r\n" in raw
    has_lf_only = b"\n" in raw.replace(b"\r\n", b"")
    has_cr_only = b"\r" in raw.replace(b"\r\n", b"")
    return (has_crlf and (has_lf_only or has_cr_only)) or (has_cr_only and (has_lf_only and not has_crlf))


# --- normalisation -----------------------------------------------------------

def normalize(path: str | Path, eol: str = "lf") -> bool:
    """Rewrite *path* in place to the requested line-ending style.

    eol:  "lf" | "crlf" | "cr"
    Returns True if the file was rewritten, False if it was skipped (binary).
    """
    if looks_binary(path):
        return False
    raw = Path(path).read_bytes()
    # Split into logical lines (no terminator)
    lines = raw.split(b"\n")
    # Strip trailing CR from each line
    lines = [line.rstrip(b"\r") for line in lines]
    if lines and lines[-1] == b"":
        lines.pop()  # drop the empty segment after the final newline

    delim = {"lf": b"\n", "crlf": b"\r\n", "cr": b"\r"}[eol]
    body = delim.join(lines)
    # Always end with the chosen terminator (unless the file was empty)
    if lines:
        body += delim
    Path(path).write_bytes(body)


def to_lf(path: str | Path) -> None:
    """Convert to LF (Git / macOS / Linux convention)."""
    normalize(path, "lf")


def to_crlf(path: str | Path) -> None:
    """Convert to CRLF (Windows convention)."""
    normalize(path, "crlf")


# --- read / write helpers -----------------------------------------------------

def read_text_universal(path: str | Path) -> str:
    """Read a file, translating any line-ending to \\n (Python universal newlines).

    This is what Python's text mode does by default; here it is explicit.
    """
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str | Path, content: str, eol: str = "lf") -> None:
    """Write *content* to *path*, translating every \\n to the chosen eol.

    For LF, no translation is needed.
    For CRLF / CR, the \\n characters in *content* are rewritten.
    """
    text = content.replace("\r\n", "\n").replace("\r", "\n")  # normalise input first
    delim = {"lf": "\n", "crlf": "\r\n", "cr": "\r"}[eol]
    lines = text.split("\n")
    body = delim.join(lines)
    if lines and lines[-1] == "":
        lines.pop()
        body = delim.join(lines)
    if lines:
        body += delim
    Path(path).write_bytes(body.encode("utf-8"))


# --- VS Code settings / .gitattributes ----------------------------------------

VSCODE_SETTINGS = {
    "files.eol": "lf",  # "auto" | "lf" | "crlf" | "cr"
}

GITATTRIBUTES = """\
# Normalise line endings in the Git repo to LF.
# VS Code and git will convert on checkout for Windows.
* text=auto eol=lf
"""


def write_vscode_settings(workspace: str | Path) -> None:
    """Create .vscode/settings.json with LF line endings."""
    vs = Path(workspace) / ".vscode"
    vs.mkdir(parents=True, exist_ok=True)
    import json
    (vs / "settings.json").write_text(json.dumps(VSCODE_SETTINGS, indent=2) + "\n")


def write_gitattributes(workspace: str | Path) -> None:
    """Create .gitattributes with LF normalization."""
    (Path(workspace) / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")


# --- CLI -----------------------------------------------------------------------

def scan_tracked(dry_run: bool = True, eol: str = "lf") -> None:
    """Scan all git-tracked files; report CRLF/mixed, optionally normalize to LF.

    Skips nothing by default — `.gitattributes` marks binaries `binary`, and
    binary files have no line endings to touch, so detect_eol just returns
    'lf' for them harmlessly. Run it from the repo root.
    """
    import subprocess
    import os

    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad_crlf: list[str] = []
    bad_mixed: list[str] = []
    for f in tracked:
        if not os.path.isfile(f):
            continue
        if looks_binary(f):
            continue  # never touch binary assets
        if is_mixed(f):
            bad_mixed.append(f)
        elif detect_eol(f) == "crlf":
            bad_crlf.append(f)
    print(f"CRLF files: {len(bad_crlf)}")
    for x in bad_crlf[:100]:
        print("  ", x)
    print(f"MIXED files: {len(bad_mixed)}")
    for x in bad_mixed[:100]:
        print("  ", x)
    if not dry_run:
        for f in bad_crlf + bad_mixed:
            if os.path.isfile(f):
                normalize(f, eol)
    return


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Detect / normalise line endings.")
    parser.add_argument("paths", nargs="*", help="file(s) to process")
    parser.add_argument(
        "--eol", choices=("auto", "lf", "crlf", "cr"), default="lf",
        help="target line-ending style (default: lf)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="only report, do not rewrite",
    )
    parser.add_argument(
        "--workspace", default=None,
        help="write .vscode/settings.json and .gitattributes for this workspace root",
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="scan all git-tracked files (report CRLF/mixed, or normalize to --eol)",
    )
    args = parser.parse_args(argv)

    if args.scan:
        scan_tracked(dry_run=args.dry_run, eol=args.eol)
        return 0

    if not args.paths and not args.workspace:
        parser.print_usage()
        print("\nhint: pass file paths, --scan, or --workspace <root>")
        return 2
    if args.workspace:
        write_vscode_settings(args.workspace)
        write_gitattributes(args.workspace)
        print(f"wrote .vscode/settings.json and .gitattributes in {args.workspace}")

    for path_str in args.paths:
        p = Path(path_str)
        detected = detect_eol(p)
        mixed = is_mixed(p)
        print(f"{p}\t{detected}\t{'mixed' if mixed else 'clean'}")
        if not args.dry_run and args.eol != "auto":
            if detected != args.eol or mixed:
                normalize(p, args.eol)
                print(f"  → normalised to {args.eol}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
