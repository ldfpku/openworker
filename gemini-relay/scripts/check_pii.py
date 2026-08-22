"""提交前检查：别把同事的真实姓名和邮箱推进公开仓库。

这个仓库是 andrewyng/openworker 的**公开** fork，同时装着公司内部的东西（中转名单、
部门信息）。真实姓名配真实邮箱一旦进了公开 git 历史，基本清不掉——改文件没用，历史还在。

用 `roster.csv`（不进 git 的那份真实名单）当黑名单，扫一遍**即将被提交**的所有文件。
2026-08-22 首次运行就在 `tests/test_relay_auth.py` 的测试夹具里抓到一个真实邮箱+姓名，
那是上一轮写测试时顺手拿真人当例子留下的——所以这个脚本不是形式主义。

用法（在仓库根目录）：

    C:\\Users\\liude\\github\\openworker\\.venv\\Scripts\\python.exe gemini-relay\\scripts\\check_pii.py

退出码：0 = 干净；1 = 发现疑似 PII（会列出文件和命中的字符串）；2 = 没法检查（缺 roster.csv）。
"""

from __future__ import annotations

import io
import os
import subprocess
import sys

ROSTER = "gemini-relay/scripts/roster.csv"

# 这些是占位符，本来就该出现在仓库里，命中了也不算问题。
ALLOWED = {"alice@example.com", "bob@example.com", "admin@example.com"}


def denylist() -> set[str]:
    """真实名单里的邮箱和姓名。名单本身不进 git，所以它是最可靠的黑名单来源。"""
    if not os.path.isfile(ROSTER):
        sys.stderr.write(
            "找不到 %s —— 没有黑名单就没法检查。\n"
            "如果这台机器本来就没有真实名单，这个检查跳过即可。\n" % ROSTER
        )
        raise SystemExit(2)
    names: set[str] = set()
    for line in io.open(ROSTER, encoding="utf-8-sig").read().splitlines()[1:]:
        cells = [c.strip() for c in line.split(",")]
        if not cells or not cells[0] or cells[0].startswith("#"):
            continue
        names.add(cells[0].lower())          # 邮箱
        if len(cells) > 1 and cells[1]:
            names.add(cells[1])              # 姓名
    return {n for n in names if n not in ALLOWED}


def tracked_and_staged() -> list[str]:
    """所有会被 `git add -A` 收进去的文件（已跟踪的 + 未忽略的新文件）。"""
    out = subprocess.run(
        ["git", "add", "-An"], capture_output=True, text=True, encoding="utf-8"
    ).stdout
    added = [
        line.split(" ", 1)[1].strip().strip("'\"")
        for line in out.splitlines()
        if line.startswith("add ")
    ]
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, encoding="utf-8"
    ).stdout.splitlines()
    return sorted(set(added) | set(tracked))


def main() -> int:
    needles = denylist()
    hits: list[tuple[str, str]] = []
    scanned = 0
    for path in tracked_and_staged():
        if not os.path.isfile(path):
            continue
        try:
            text = io.open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        scanned += 1
        for needle in needles:
            if needle in text:
                hits.append((path, needle))

    print("黑名单条目 %d（来自 %s）；扫描文件 %d 个" % (len(needles), ROSTER, scanned))
    if not hits:
        print("干净：没有真实姓名或邮箱出现在会被提交的文件里。")
        return 0
    print("\n发现 %d 处疑似 PII —— 提交前必须改掉：" % len(hits))
    for path, needle in hits:
        print("  %s  ←  %s" % (path, needle))
    print("\n改成占位符（alice@example.com / 张三 之类）再提交。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
