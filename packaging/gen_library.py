#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_library.py — 生成 openworker 内置专家库 / 技能库数据包（library-pack/）。

从三个已浅克隆到本地的上游仓库抓取数据，产出统一结构的 `library-pack/` 目录，
随 openworker 一起分发（详见 library-pack/ATTRIBUTION.md）。

用法：
    python packaging/gen_library.py --sources <目录> [--out <目录>]

--sources <目录>   必填。其下必须有三个子目录：
                     agency-agents            （英文专家库）
                     agency-agents-zh          （中文专家库）
                     scientific-agent-skills   （科学技能库，skills/ + docs/skills.md）
--out <目录>       输出目录，默认 <repo>/library-pack。
                     若目录已存在：只清空 experts/ skills/ index.json ATTRIBUTION.md
                     这几项后重建（幂等）；若目录存在、非空、但没有 index.json（看起来
                     不像是本脚本之前的输出），则报错退出，不做任何删除，防止误删。

纯标准库实现，不引入第三方依赖。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

# 专家库扫描时跳过的顶层目录（以及任何以 "." 开头的目录）
EXCLUDE_EXPERT_TOP_DIRS = {
    ".git", ".github", "node_modules", "scripts", "examples",
    "integrations", "strategy", "assets", "docs", "tests",
}

FRONTMATTER_KEYS = {"name", "description", "emoji", "color", "license", "compatibility"}

DEFAULT_EMOJI = "🤖"
DEFAULT_COLOR = "#888"
DEFAULT_DESCRIPTION = ""

# 中文专家库固定分类名映射（缺省用原目录名）
ZH_CATEGORY_NAMES = {
    "academic": "学术研究",
    "design": "设计",
    "engineering": "工程开发",
    "finance": "财务金融",
    "game-development": "游戏开发",
    "gis": "GIS 地理信息",
    "healthcare": "医疗健康",
    "marketing": "市场营销",
    "paid-media": "付费媒体",
    "product": "产品",
    "project-management": "项目管理",
    "research": "研究",
    "sales": "销售",
    "security": "安全",
    "spatial-computing": "空间计算",
    "specialized": "专业服务",
    "support": "运营支持",
    "testing": "质量测试",
    "company": "公司经营",
    "hr": "人力资源",
    "legal": "法务",
    "supply-chain": "供应链",
}

# docs/skills.md 二级标题 -> (category, categoryName) 的分类规则
SKILL_HEADING_RULES = [
    ("Databases", ("databases", "科学数据库")),
    ("Integrations", ("integrations", "平台集成")),
    ("Packages", ("packages", "科学软件包")),
]
SKILL_OTHER = ("other", "其他")

LINK_LINE_RE = re.compile(r"^\s*-\s+\*\*\[(.*?)\]\((.*?)\)\*\*")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
SCRIPT_EXTS = {".py", ".sh"}


# --------------------------------------------------------------------------
# frontmatter 解析（手写、容错；风格参照 coworker/skills/base.py 的 _parse_skill）
# --------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict:
    """从形如

        ---
        name: Foo
        description: "..."
        emoji: 🤖
        color: "#123456"
        ---

    的文本里抠出 frontmatter。只认 name/description/emoji/color/license/compatibility，
    其余（含嵌套块，如 `metadata:` 下面的子字段）一律忽略——嵌套行的 key 在 strip 之后
    不会等于这几个允许的 key，天然不会互相覆盖。
    """
    result: dict[str, str] = {}
    if not text.startswith("---"):
        return result
    end = text.find("\n---", 3)
    if end == -1:
        return result
    frontmatter = text[3:end]
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key not in FRONTMATTER_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1].strip()
        if value:
            result[key] = value
    return result


# --------------------------------------------------------------------------
# 专家库扫描
# --------------------------------------------------------------------------

def is_excluded_expert_dir(name: str) -> bool:
    return name.startswith(".") or name in EXCLUDE_EXPERT_TOP_DIRS


def scan_experts(lib_root: Path, category_name_fn) -> list[dict]:
    """遍历 lib_root 下的专家 md 文件（跳过排除目录），返回原始条目列表
    （含 relpath，供后续复制文件 / 计算 id 用）。"""
    raw: list[dict] = []
    for top in sorted(p for p in lib_root.iterdir() if p.is_dir()):
        if is_excluded_expert_dir(top.name):
            continue
        category = top.name
        category_name = category_name_fn(category)
        for md in sorted(top.rglob("*.md")):
            text = md.read_text(encoding="utf-8")
            fm = parse_frontmatter(text)
            if "name" not in fm:
                continue  # 没有 frontmatter name（README 等）——不是专家文件
            relpath = md.relative_to(lib_root).as_posix()
            entry_id = relpath[:-3] if relpath.endswith(".md") else relpath
            raw.append({
                "id": entry_id,
                "relpath": relpath,
                "abspath": md,
                "category": category,
                "categoryName": category_name,
                "name": fm["name"],
                "description": fm.get("description", DEFAULT_DESCRIPTION),
                "emoji": fm.get("emoji", DEFAULT_EMOJI),
                "color": fm.get("color", DEFAULT_COLOR),
            })
    return raw


def finalize_expert_entries(raw: list[dict], other_ids: set[str]) -> list[dict]:
    entries = []
    for e in raw:
        entries.append({
            "id": e["id"],
            "category": e["category"],
            "categoryName": e["categoryName"],
            "name": e["name"],
            "description": e["description"],
            "emoji": e["emoji"],
            "color": e["color"],
            "pair": e["id"] in other_ids,
        })
    return entries


def copy_experts(raw: list[dict], out_lang_dir: Path) -> None:
    for e in raw:
        dest = out_lang_dir / e["relpath"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(e["abspath"], dest)


def title_case(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split("-"))


def load_divisions(divisions_json: Path) -> dict:
    if not divisions_json.is_file():
        return {}
    with divisions_json.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("divisions", {})


# --------------------------------------------------------------------------
# 技能库扫描
# --------------------------------------------------------------------------

def classify_skill_heading(title: str) -> tuple[str, str] | None:
    for needle, result in SKILL_HEADING_RULES:
        if needle in title:
            return result
    if "Thinking" in title or "Analysis" in title:
        return ("analysis", "科研写作与分析")
    return None


def parse_skills_doc(doc_path: Path) -> dict[str, tuple[str, str]]:
    """解析 docs/skills.md 的二级标题分段，返回 {技能目录名: (category, categoryName)}。
    技能目录名直接取自粗体链接行里的相对路径（../skills/<dirname>/）——这与"用技能名
    匹配目录名"是同一件事的更稳妥做法：显示名可能和目录名对不上（如 Zarr -> zarr-python），
    但链接路径里已经写死了目录名，不需要再去猜测归一化规则。
    """
    mapping: dict[str, tuple[str, str]] = {}
    if not doc_path.is_file():
        return mapping
    current: tuple[str, str] | None = None
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        h2 = H2_RE.match(line)
        if h2:
            current = classify_skill_heading(h2.group(1))
            continue
        if current is None:
            continue
        m = LINK_LINE_RE.match(line)
        if not m:
            continue
        link_path = m.group(2).strip()
        dirname = link_path.rstrip("/").rsplit("/", 1)[-1]
        if dirname and dirname not in mapping:
            mapping[dirname] = current
    return mapping


def _walk_files(root: Path):
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".git")]
        for fn in filenames:
            if fn.startswith(".git"):
                continue
            yield Path(dirpath) / fn


def count_files(root: Path, exts: set[str] | None = None) -> int:
    n = 0
    for p in _walk_files(root):
        if exts is None or p.suffix.lower() in exts:
            n += 1
    return n


def scan_skill_dirs(skills_root: Path) -> list[Path]:
    if not skills_root.is_dir():
        return []
    return sorted(
        p for p in skills_root.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    )


def build_skill_entry(skill_dir: Path, doc_map: dict[str, tuple[str, str]]) -> dict:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    category, category_name = doc_map.get(skill_dir.name, SKILL_OTHER)
    return {
        "id": skill_dir.name,
        "category": category,
        "categoryName": category_name,
        "name": fm.get("name", skill_dir.name),
        "description": fm.get("description", DEFAULT_DESCRIPTION),
        "emoji": fm.get("emoji", DEFAULT_EMOJI),
        "color": fm.get("color", DEFAULT_COLOR),
        "license": fm.get("license", ""),
        "compatibility": fm.get("compatibility", ""),
        "scripts": count_files(skill_dir / "scripts", SCRIPT_EXTS),
        "references": count_files(skill_dir / "references"),
        "assets": count_files(skill_dir / "assets"),
        "files": count_files(skill_dir),
    }


def _copytree_ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n == "__pycache__" or n.startswith(".git")}


def copy_skill_dir(skill_dir: Path, dest_dir: Path) -> None:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(skill_dir, dest_dir, ignore=_copytree_ignore)


# --------------------------------------------------------------------------
# git commit
# --------------------------------------------------------------------------

def git_commit(repo_dir: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    commit = proc.stdout.strip()
    return commit if commit else "unknown"


# --------------------------------------------------------------------------
# 输出目录准备（幂等 + 防呆）
# --------------------------------------------------------------------------

MANAGED_ENTRIES = ("experts", "skills", "index.json", "ATTRIBUTION.md")


def prepare_out_dir(out_dir: Path) -> None:
    if out_dir.exists():
        if not out_dir.is_dir():
            print(f"ERROR: --out 路径已存在且不是目录：{out_dir}", file=sys.stderr)
            sys.exit(1)
        existing = list(out_dir.iterdir())
        index_path = out_dir / "index.json"
        if existing and not index_path.is_file():
            print(
                f"ERROR: 输出目录 {out_dir} 已存在且非空，但里面没有 index.json，"
                "看起来不是本脚本之前生成的产物。为防止误删，已中止，不做任何改动。"
                "如确认可以清空，请手动清理后重试。",
                file=sys.stderr,
            )
            sys.exit(1)
        for name in MANAGED_ENTRIES:
            p = out_dir / name
            if p.is_dir():
                shutil.rmtree(p)
            elif p.is_file():
                p.unlink()
    else:
        out_dir.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# ATTRIBUTION.md
# --------------------------------------------------------------------------

ATTRIBUTION_TEMPLATE = """# 数据来源与许可声明

本目录（`library-pack/`）是 openworker 内置的专家库与技能库数据包，由
`packaging/gen_library.py` 从以下三个上游开源仓库自动抓取生成，随 openworker 源码一起分发。

## 上游仓库

| 内容 | 上游仓库 | 许可证 | 抓取时 commit |
|---|---|---|---|
| 英文专家库（`experts/en/`） | https://github.com/msitarzewski/agency-agents | MIT | `{en_commit}` |
| 中文专家库（`experts/zh/`） | https://github.com/jnMetaCode/agency-agents-zh | MIT | `{zh_commit}` |
| 科学技能库（`skills/`） | https://github.com/K-Dense-AI/scientific-agent-skills | MIT | `{skills_commit}` |

## 版权声明

- agency-agents：`Copyright (c) 2025 AgentLand Contributors`
- agency-agents-zh（英文原版 + 中文汉化，双版权）：
  - `Copyright (c) 2025 Michael Sitarzewski (original English version)`
  - `Copyright (c) 2026 jnMetaCode (Chinese translation and localization)`
- scientific-agent-skills：`Copyright (c) 2025 K-Dense Inc.`

三者均以 MIT License 分发。完整许可证正文见各自仓库根目录的 `LICENSE` / `LICENSE.md`：

- https://github.com/msitarzewski/agency-agents/blob/main/LICENSE
- https://github.com/jnMetaCode/agency-agents-zh/blob/main/LICENSE
- https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/LICENSE.md

## 与本 fork 的关系

openworker 是 https://github.com/andrewyng/openworker 的一个公开 fork，本数据包随
https://github.com/ldfpku/openworker 一同分发。以上三个上游仓库的内容——专家库按原始
Markdown 文件（含 frontmatter）原样拷贝，技能库按目录整棵原样拷贝——未做任何实质性修改；
本 fork 新增的只有生成/维护脚本（`packaging/gen_library.py`）与本说明文件。

## 生成信息

- 生成时间（UTC）：`{generated_at}`
- 生成脚本：`packaging/gen_library.py`
"""


def write_attribution(path: Path, generated: dict) -> None:
    content = ATTRIBUTION_TEMPLATE.format(
        en_commit=generated.get("agency-agents", "unknown"),
        zh_commit=generated.get("agency-agents-zh", "unknown"),
        skills_commit=generated.get("scientific-agent-skills", "unknown"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------
# 统计信息
# --------------------------------------------------------------------------

def dir_size_bytes(root: Path) -> int:
    total = 0
    for p in _walk_files(root):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def count_by(entries: list[dict], key: str = "category") -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e[key]] = counts.get(e[key], 0) + 1
    return counts


def print_stats(en_entries, zh_entries, skill_entries, out_dir: Path) -> None:
    pair_count = sum(1 for e in zh_entries if e["pair"])
    print("=" * 60)
    print("生成完成，统计如下：")
    print(f"  英文专家（en）    : {len(en_entries)}")
    print(f"  中文专家（zh）    : {len(zh_entries)}")
    print(f"  中英配对（pair）  : {pair_count}")
    print(f"  技能（skills）    : {len(skill_entries)}")
    print()
    print("  英文专家分类计数：")
    for cat, n in sorted(count_by(en_entries).items()):
        print(f"    {cat:24s} {n}")
    print("  中文专家分类计数：")
    for cat, n in sorted(count_by(zh_entries).items()):
        print(f"    {cat:24s} {n}")
    print("  技能分类计数：")
    for cat, n in sorted(count_by(skill_entries).items()):
        print(f"    {cat:24s} {n}")
    print()
    total_bytes = dir_size_bytes(out_dir)
    print(f"  输出目录总字节数  : {total_bytes} ({total_bytes / 1024 / 1024:.2f} MiB)")
    print(f"  输出目录          : {out_dir}")
    print("=" * 60)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def default_out_dir() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "library-pack"


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="生成 openworker 内置专家库 / 技能库数据包（library-pack/）",
    )
    p.add_argument(
        "--sources", required=True,
        help="源目录，其下必须有 agency-agents / agency-agents-zh / scientific-agent-skills 三个子目录",
    )
    p.add_argument(
        "--out", default=None,
        help="输出目录，默认 <repo>/library-pack",
    )
    return p


def main() -> None:
    # Windows 控制台默认代码页常常不是 UTF-8（如 cp936），这里的统计信息全是中文，
    # 显式切到 UTF-8（errors="replace" 兜底）避免在裸 cmd/PowerShell 下打印时崩掉。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_argparser().parse_args()
    sources = Path(args.sources).resolve()
    out_dir = Path(args.out).resolve() if args.out else default_out_dir()

    en_root = sources / "agency-agents"
    zh_root = sources / "agency-agents-zh"
    skills_repo_root = sources / "scientific-agent-skills"
    skills_root = skills_repo_root / "skills"
    docs_path = skills_repo_root / "docs" / "skills.md"

    for name, p in (
        ("agency-agents", en_root),
        ("agency-agents-zh", zh_root),
        ("scientific-agent-skills", skills_repo_root),
    ):
        if not p.is_dir():
            print(f"ERROR: --sources 下缺少 {name}（期望路径：{p}）", file=sys.stderr)
            sys.exit(1)

    prepare_out_dir(out_dir)
    (out_dir / "experts" / "en").mkdir(parents=True, exist_ok=True)
    (out_dir / "experts" / "zh").mkdir(parents=True, exist_ok=True)
    (out_dir / "skills").mkdir(parents=True, exist_ok=True)

    # ---- 专家库 ----
    divisions = load_divisions(en_root / "divisions.json")

    def en_category_name(cat: str) -> str:
        label = divisions.get(cat, {}).get("label")
        return label if label else title_case(cat)

    def zh_category_name(cat: str) -> str:
        return ZH_CATEGORY_NAMES.get(cat, cat)

    en_raw = scan_experts(en_root, en_category_name)
    zh_raw = scan_experts(zh_root, zh_category_name)

    en_ids = {e["id"] for e in en_raw}
    zh_ids = {e["id"] for e in zh_raw}

    en_entries = finalize_expert_entries(en_raw, zh_ids)
    zh_entries = finalize_expert_entries(zh_raw, en_ids)

    copy_experts(en_raw, out_dir / "experts" / "en")
    copy_experts(zh_raw, out_dir / "experts" / "zh")

    # ---- 技能库 ----
    doc_map = parse_skills_doc(docs_path)
    skill_dirs = scan_skill_dirs(skills_root)
    skill_entries = []
    for d in skill_dirs:
        skill_entries.append(build_skill_entry(d, doc_map))
        copy_skill_dir(d, out_dir / "skills" / d.name)

    # ---- commit ----
    generated = {
        "agency-agents": git_commit(en_root),
        "agency-agents-zh": git_commit(zh_root),
        "scientific-agent-skills": git_commit(skills_repo_root),
    }

    # ---- index.json ----
    index = {
        "version": 1,
        "generated": generated,
        "experts": {"zh": zh_entries, "en": en_entries},
        "skills": skill_entries,
    }
    with (out_dir / "index.json").open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # ---- ATTRIBUTION.md ----
    write_attribution(out_dir / "ATTRIBUTION.md", generated)

    print_stats(en_entries, zh_entries, skill_entries, out_dir)


if __name__ == "__main__":
    main()
