"""What may enter a skill folder — one gate, shared by every import path.

Three import paths land files in the skills dir: the library pack's install (a copytree
out of the shipped pack), a user's ``.zip``, and a user's folder pick. They must agree on
what is skill content and what is build junk, or they drift — the library install already
carried a hardcoded ``ignore_patterns("__pycache__", ...)`` that the upload path knew
nothing about.

Three verdicts:

* ``KEEP`` — real skill content.
* ``EXCLUDE`` — build/editor/VCS noise (``__pycache__``, ``node_modules``, ``.git``,
  ``*.pyc``, ``.DS_Store``…). Dropped, and **reported**: a silent filter is how a user
  ends up believing they installed something they did not. Nobody hand-curates a folder
  before zipping it, so this has to be automatic — but never invisible.
* ``SECRET`` — ``.env``, private keys, credential files. **Refused outright**, whole
  import. Someone zipping a project folder is not trying to publish their keys, and a
  skill folder is a thing people share.

Plus hard limits (a skill is instructions and a few helper scripts, not a dataset), which
also close the zip-bomb hole: the previous upload path decompressed an archive of any size
straight into memory with no ceiling at all.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

KEEP = "keep"
EXCLUDE = "exclude"
SECRET = "secret"

# Directory NAMES — matched at any depth, and the whole subtree goes with them.
EXCLUDED_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".ipynb_checkpoints",
        ".idea",
        ".vscode",
        ".next",
        "dist",
        "build",
        "__MACOSX",  # Finder's "Compress" shadow tree
        ".Trash",
        ".cache",
    }
)

# File name globs — compiled artifacts, editor/OS droppings, logs.
EXCLUDED_FILES = (
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.class",
    "*.o",
    "*.obj",
    ".DS_Store",
    "._*",
    "Thumbs.db",
    "desktop.ini",
    "*.swp",
    "*.swo",
    "*~",
    "*.log",
    "*.tmp",
    "*.bak",
    ".gitignore",
    ".gitattributes",
)

# Credentials. These do not get quietly dropped — they abort the import, by name, so the
# user learns their secret was in the folder they were about to share.
SECRET_FILES = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "service-account*.json",
    ".htpasswd",
)


@dataclass(frozen=True)
class Limits:
    """Sized off the shipped library: its biggest skill is ~2 MB / 32 files, the most
    files in one skill is 82, and its largest single file is ~1 MB. Every ceiling here
    clears the real worst case several times over, so hitting one means the import is
    not a skill — it is a folder that happens to contain one."""

    max_files: int = 300
    max_total_bytes: int = 20 * 1024 * 1024
    max_file_bytes: int = 5 * 1024 * 1024
    max_archive_bytes: int = 25 * 1024 * 1024
    max_ratio: int = 100  # uncompressed:compressed — the zip-bomb ceiling
    max_depth: int = 8


LIMITS = Limits()


class ImportRefused(ValueError):
    """The import cannot proceed. The message is shown to the user verbatim."""


def _name_matches(name: str, patterns: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)


def classify(relpath: str) -> tuple[str, str]:
    """Verdict + a short human reason for one path relative to the skill root.

    Accepts either separator; matching is case-insensitive because the same file is
    ``.DS_Store`` on one machine and ``.ds_store`` on another.
    """
    parts = PurePosixPath(str(relpath).replace("\\", "/")).parts
    if not parts:
        return EXCLUDE, "empty path"
    for part in parts[:-1]:
        if part.lower() in {d.lower() for d in EXCLUDED_DIRS}:
            return EXCLUDE, part
    name = parts[-1]
    if name.lower() in {d.lower() for d in EXCLUDED_DIRS}:
        return EXCLUDE, name
    if _name_matches(name, SECRET_FILES):
        return SECRET, name
    if _name_matches(name, EXCLUDED_FILES):
        return EXCLUDE, name
    return KEEP, ""


def copytree_ignore():
    """An ``ignore=`` callable for :func:`shutil.copytree` applying the same rules.

    Written as a callable rather than ``shutil.ignore_patterns`` so directory names and
    file globs share one source of truth with the archive path. Secrets are *skipped*
    here rather than raising: this is the library-pack install, copying content we ship,
    where a match would be our packaging bug and not a user's key.
    """

    def _ignore(directory: str, names: list[str]) -> set[str]:
        drop = set()
        for name in names:
            full = Path(directory) / name
            if full.is_dir():
                if name.lower() in {d.lower() for d in EXCLUDED_DIRS}:
                    drop.add(name)
            elif _name_matches(name, EXCLUDED_FILES) or _name_matches(name, SECRET_FILES):
                drop.add(name)
        return drop

    return _ignore


def _fmt_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / 1024:.0f} KB"


def check_depth(relpath: str, limits: Limits = LIMITS) -> None:
    depth = len(PurePosixPath(str(relpath).replace("\\", "/")).parts)
    if depth > limits.max_depth:
        raise ImportRefused(
            f"Path nested too deeply ({depth} levels, limit {limits.max_depth}): {relpath}"
        )


def check_file(relpath: str, size: int, limits: Limits = LIMITS) -> None:
    if size > limits.max_file_bytes:
        raise ImportRefused(
            f"'{relpath}' is {_fmt_bytes(size)} — over the "
            f"{_fmt_bytes(limits.max_file_bytes)} limit for a single file in a skill."
        )


def check_totals(count: int, total: int, limits: Limits = LIMITS) -> None:
    if count > limits.max_files:
        raise ImportRefused(
            f"{count} files after filtering — over the {limits.max_files}-file limit "
            "for one skill."
        )
    if total > limits.max_total_bytes:
        raise ImportRefused(
            f"{_fmt_bytes(total)} after filtering — over the "
            f"{_fmt_bytes(limits.max_total_bytes)} limit for one skill."
        )


def check_archive_size(compressed: int, limits: Limits = LIMITS) -> None:
    if compressed > limits.max_archive_bytes:
        raise ImportRefused(
            f"The archive is {_fmt_bytes(compressed)} — over the "
            f"{_fmt_bytes(limits.max_archive_bytes)} upload limit."
        )


def check_ratio(compressed: int, uncompressed: int, limits: Limits = LIMITS) -> None:
    """Zip-bomb guard: a genuinely text-heavy skill compresses maybe 5-10x."""
    if compressed > 0 and uncompressed > limits.max_ratio * compressed:
        raise ImportRefused(
            f"The archive expands {uncompressed // max(compressed, 1)}x "
            f"({_fmt_bytes(compressed)} → {_fmt_bytes(uncompressed)}). Refusing to unpack it."
        )


def refuse_secrets(found: list[str]) -> None:
    if not found:
        return
    shown = ", ".join(found[:5]) + (f" (+{len(found) - 5} more)" if len(found) > 5 else "")
    raise ImportRefused(
        f"This skill contains credential files: {shown}. Remove them and import again — "
        "a skill folder is meant to be shared."
    )


def summarize_excluded(paths: list[str]) -> list[str]:
    """Collapse dropped paths into lines a person can scan: one line per excluded
    directory with its file count, then individually-dropped files by name."""
    dirs: dict[str, int] = {}
    loose: list[str] = []
    for p in paths:
        verdict, reason = classify(p)
        if verdict != EXCLUDE:
            continue
        parts = PurePosixPath(p.replace("\\", "/")).parts
        hit = next(
            (
                "/".join(parts[: i + 1])
                for i, part in enumerate(parts[:-1])
                if part.lower() in {d.lower() for d in EXCLUDED_DIRS}
            ),
            None,
        )
        if hit:
            dirs[hit + "/"] = dirs.get(hit + "/", 0) + 1
        else:
            loose.append(p)
    out = [f"{d} ({n} file{'s' if n != 1 else ''})" for d, n in sorted(dirs.items())]
    out += sorted(loose)
    return out
