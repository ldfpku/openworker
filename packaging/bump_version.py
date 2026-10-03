#!/usr/bin/env python3
"""Increment the app version with a patch component in the range 1-9."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def next_version(current: str, bump: str = "patch") -> str:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.[1-9]", current):
        raise ValueError(f"invalid release-policy version: {current!r}")
    major, minor, patch = map(int, current.split("."))
    if bump == "major":
        major, minor, patch = major + 1, 0, 1
    elif bump == "minor":
        minor, patch = minor + 1, 1
    elif bump == "patch":
        if patch == 9:
            minor, patch = minor + 1, 1
        else:
            patch += 1
    else:
        raise ValueError(f"unknown bump: {bump!r}")
    return f"{major}.{minor}.{patch}"


def bump_config(path: Path, bump: str) -> str:
    text = path.read_text(encoding="utf-8")
    current = json.loads(text)["version"]
    version = next_version(current, bump)
    needle = f'"version": "{current}"'
    if text.count(needle) != 1:
        raise ValueError(f"expected exactly one version field in {path}")
    path.write_text(text.replace(needle, f'"version": "{version}"'), encoding="utf-8")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bump", choices=("patch", "minor", "major"), nargs="?", default="patch")
    parser.add_argument(
        "--config", type=Path,
        default=Path(__file__).resolve().parents[1] / "surfaces" / "gui" / "src-tauri" / "tauri.conf.json",
    )
    args = parser.parse_args()
    print(bump_config(args.config, args.bump))
