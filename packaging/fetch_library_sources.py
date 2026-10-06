#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_library_sources.py — 把 library-pack 的四个上游仓库按固定 commit 浅克隆到本地。

用法：
    python packaging/fetch_library_sources.py [--dest <目录>] [--force]

--dest <目录>   克隆到哪里，默认 <repo 的上一级>/openworker-library-sources
                （本仓库在 D:/smj-apps/openworker 时即 D:/smj-apps/openworker-library-sources）。
--force         已存在的仓库也重新 fetch 并强制检出到固定 commit（本地改动会被丢弃）。

之后生成数据包：
    python packaging/gen_library.py --sources <目录>

要升级某个上游，改下面 SOURCES 里的 commit，重新跑本脚本（加 --force）和 gen_library.py，
再把 library-pack/ATTRIBUTION.md 里记录的 commit 一起提交。

每个仓库都以 core.autocrlf=false 检出：仓库按 .gitattributes 存 LF、打包直接拿工作区文件，
Windows 上默认的 autocrlf=true 会把所有拷贝件写成 CRLF。只依赖标准库和 git 命令。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 名称 -> (仓库地址, 固定 commit)。与 library-pack/ATTRIBUTION.md 的「抓取时 commit」一致。
SOURCES: dict[str, tuple[str, str]] = {
    "agency-agents": (
        "https://github.com/msitarzewski/agency-agents",
        "32230ec4790a24cfd187e08245cb3c6f28998b9d",
    ),
    "agency-agents-zh": (
        "https://github.com/jnMetaCode/agency-agents-zh",
        "972452cdedef8d04fed4a8dd1dc10623e33ed412",
    ),
    "scientific-agent-skills": (
        "https://github.com/K-Dense-AI/scientific-agent-skills",
        "390f5146bf3c1877cf15636a3dd7b775e4f0f185",
    ),
    "knowledge-work-plugins": (
        "https://github.com/anthropics/knowledge-work-plugins",
        "8444efcd48f7012f09797778a36a33e73d0861f4",
    ),
}


def default_dest() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root.parent / "openworker-library-sources"


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def fetch_one(name: str, url: str, commit: str, dest: Path, force: bool) -> str:
    repo = dest / name
    if (repo / ".git").is_dir():
        head = git("rev-parse", "HEAD", cwd=repo)
        if head == commit and not force:
            return f"{name}: 已在 {commit[:7]}，跳过"
        git("config", "core.autocrlf", "false", cwd=repo)
        git("fetch", "--depth", "1", "origin", commit, cwd=repo)
        git("checkout", "-q", "--force", "FETCH_HEAD", cwd=repo)
        return f"{name}: {head[:7]} -> {commit[:7]}"
    repo.mkdir(parents=True, exist_ok=True)
    git("init", "-q", str(repo))
    git("config", "core.autocrlf", "false", cwd=repo)
    git("remote", "add", "origin", url, cwd=repo)
    git("fetch", "--depth", "1", "origin", commit, cwd=repo)
    git("checkout", "-q", "FETCH_HEAD", cwd=repo)
    return f"{name}: 克隆到 {commit[:7]}"


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="按固定 commit 浅克隆 library-pack 的上游仓库")
    parser.add_argument("--dest", default=None, help="目标目录，默认 <repo 上一级>/openworker-library-sources")
    parser.add_argument("--force", action="store_true", help="已存在的仓库也强制检出到固定 commit")
    args = parser.parse_args()
    dest = Path(args.dest).resolve() if args.dest else default_dest()
    dest.mkdir(parents=True, exist_ok=True)
    failed = False
    for name, (url, commit) in SOURCES.items():
        try:
            print(fetch_one(name, url, commit, dest, args.force))
        except RuntimeError as e:
            failed = True
            print(f"ERROR: {e}", file=sys.stderr)
    print(f"源目录：{dest}")
    print(f"下一步：python packaging/gen_library.py --sources \"{dest}\"")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
