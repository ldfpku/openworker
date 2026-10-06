#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_library.py — 生成 openworker 内置专家库 / 技能库数据包（library-pack/）。

从四个已浅克隆到本地的上游仓库抓取数据，产出统一结构的 `library-pack/` 目录，
随 openworker 一起分发（详见 library-pack/ATTRIBUTION.md）。

用法：
    python packaging/gen_library.py --sources <目录> [--out <目录>]

--sources <目录>   必填。其下必须有四个子目录：
                     agency-agents            （英文专家库）
                     agency-agents-zh          （中文专家库）
                     scientific-agent-skills   （科学技能库，只打包 SCIENTIFIC_KEEP 清单里的）
                     knowledge-work-plugins    （Anthropic 知识工作插件库，按插件分类打包）
--out <目录>       输出目录，默认 <repo>/library-pack。
                     若目录已存在：只清空 experts/ skills/ LICENSES/ index.json
                     ATTRIBUTION.md 这几项后重建（幂等）；若目录存在、非空、但没有
                     index.json（看起来不像是本脚本之前的输出），则报错退出，不做任何
                     删除，防止误删。
                     技能的中文译文层（skills/<id>/SKILL.zh.md 与 index.json 里的
                     description_zh）是本 fork 生成的内容，重建时自动快照并放回。

整个数据包面向生产制造企业（从生产管理到研发），四条口径（详见 ATTRIBUTION.md 的
「与本 fork 的关系」）：

* 专家库只打包与制造企业经营、生产、研发相关的专家（EXPERT_KEEP_CATEGORIES /
  EXPERT_KEEP_IDS / EXPERT_DROP_IDS），学术人文、游戏、GIS、空间计算、社媒营销等一律不打包。
* scientific-agent-skills 只保留与生产制造业管理相关的技能（SCIENTIFIC_KEEP），并按
  用途重新分类；表外的一律不打包。
* knowledge-work-plugins 只打包 plugin.json 作者为 Anthropic 的插件（KWP_EXCLUDED_PLUGINS
  里点名排除的除外），每个插件就是一个分类。为了让技能在 openworker 里能直接安装、执行，
  对拷贝件做了几处有记录的改动：frontmatter 追加 `source:` 来源标记；跨插件重名的技能
  改名为 `<插件>-<技能>`；指向插件根目录的相对链接改指向技能目录内的副本。
* 本库自编的制造企业技能（仓库内 library-src/manufacturing-skills/，中文正文）作为第五个
  来源打包，分类见 MANUFACTURING_CATEGORIES / MANUFACTURING_SKILLS；目录可用
  --manufacturing 覆盖（测试用）。

只依赖标准库；PyYAML 可选（有则用来读 `description: >` 这类折叠标量，没有就按行扫）。
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
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

SCRIPT_EXTS = {".py", ".sh"}

# frontmatter 里的折叠/块标量指示符——逐行扫只能扫出这个符号本身，真正的值在下面几行。
_FOLDED_INDICATORS = {">", "|", ">-", "|-", ">+", "|+"}

# --------------------------------------------------------------------------
# 技能库 ①：scientific-agent-skills 的保留清单
# --------------------------------------------------------------------------

SCIENTIFIC_SOURCE = "K-Dense-AI/scientific-agent-skills"
SCIENTIFIC_AUTHOR = "K-Dense AI"

# 上游 160 多个技能绝大多数面向生物、化学、基因组、天文、量子、临床等基础科研场景，
# 与生产制造业管理无关。只保留这张表里的——装备制造企业的质量、生产计划、设备、工艺、
# 研发岗位用得上的——并按用途重新分类；表外的一律不打包。
# 值：(category, categoryName, 保留理由)。增删只改这张表，再跑一次脚本。
SCIENTIFIC_KEEP: dict[str, tuple[str, str, str]] = {
    # 办公文档
    "docx": ("office-docs", "办公文档", "Word 文档的读写、排版与批注"),
    "xlsx": ("office-docs", "办公文档", "Excel 表格的读写、公式与格式"),
    "pptx": ("office-docs", "办公文档", "PowerPoint 演示文稿制作与读取"),
    "pdf": ("office-docs", "办公文档", "PDF 读取、合并、拆分、填表、OCR"),
    "markitdown": ("office-docs", "办公文档", "各类文档批量转 Markdown"),
    "liteparse": ("office-docs", "办公文档", "本地解析 PDF/Office/图片里的文字和表格"),
    "markdown-mermaid-writing": ("office-docs", "办公文档", "Markdown 报告与 Mermaid 流程图写作"),
    # 数据分析与预测
    "exploratory-data-analysis": ("data-analysis", "数据分析与预测", "CSV/JSON 数据的探索性分析"),
    "statistical-analysis": ("data-analysis", "数据分析与预测", "组间比较、假设检验、效应量"),
    "statistical-power": ("data-analysis", "数据分析与预测", "样本量与检验功效计算"),
    "scikit-learn": ("data-analysis", "数据分析与预测", "通用机器学习（分类、回归、聚类）"),
    "statsmodels": ("data-analysis", "数据分析与预测", "回归、GLM、ARIMA 等统计模型"),
    "polars": ("data-analysis", "数据分析与预测", "高性能表格数据处理与 ETL"),
    "matplotlib": ("data-analysis", "数据分析与预测", "基础绘图"),
    "seaborn": ("data-analysis", "数据分析与预测", "统计图表"),
    "scientific-visualization": ("data-analysis", "数据分析与预测", "可直接出版的图表设计与审校"),
    "shap": ("data-analysis", "数据分析与预测", "模型解释（特征归因）"),
    "aeon": ("data-analysis", "数据分析与预测", "时间序列分类与异常检测（传感器、设备数据）"),
    "timesfm-forecasting": ("data-analysis", "数据分析与预测", "零样本时间序列预测（需求、能耗、销量）"),
    "scikit-survival": ("data-analysis", "数据分析与预测", "失效时间/生存分析（设备可靠性）"),
    # 工程与质量
    "experimental-design": ("engineering-quality", "工程与质量", "试验设计（DOE）与随机化方案"),
    "simpy": ("engineering-quality", "工程与质量", "离散事件仿真（产线、排队、库存）"),
    "pymoo": ("engineering-quality", "工程与质量", "多目标优化（排产、参数、结构设计）"),
    "uncertainty-and-units": ("engineering-quality", "工程与质量", "物理单位换算与测量不确定度（GUM）"),
    "lab-hardware-cad": ("engineering-quality", "工程与质量", "参数化 CAD 建模并导出 STEP/STL/DXF"),
    "analytical-method-validation": ("engineering-quality", "工程与质量", "检测方法验证（ICH/USP/ISO 17025）"),
    "iso-standards-readiness": ("engineering-quality", "工程与质量", "ISO 13485/14971/17025 等体系就绪度评估"),
    # 研究与决策
    "what-if-oracle": ("research-decision", "研究与决策", "多分支「假设情景」推演"),
    "market-research-reports": ("research-decision", "研究与决策", "市场研究与市场规模测算报告"),
    "literature-review": ("research-decision", "研究与决策", "系统性文献综述"),
    "paper-lookup": ("research-decision", "研究与决策", "多源学术文献检索（研发立项、先行技术）"),
    "citation-management": ("research-decision", "研究与决策", "参考文献管理与引用校验"),
}

# --------------------------------------------------------------------------
# 技能库 ②：anthropics/knowledge-work-plugins
# --------------------------------------------------------------------------

KWP_SOURCE = "anthropics/knowledge-work-plugins"
KWP_LICENSE = "Apache-2.0"
# 只打包 plugin.json 里 author.name 是这些的插件——partner-built/ 下的合作方插件
# （Apollo、Zoom、Salesforce……）作者不是 Anthropic，标成 anthropics 来源就是张冠李戴。
KWP_ALLOWED_AUTHORS = {"Anthropic"}
# 作者是 Anthropic、但点名不打包的插件：{插件目录名: 原因}。改这里即可增删。
KWP_EXCLUDED_PLUGINS = {
    "cowork-plugin-management": "只在 Claude Cowork 里生成/定制插件，openworker 没有对应运行时",
    "pdf-viewer": "依赖 Cowork 自带的 PDF 查看器界面（打开/批注/签名命令），openworker 无法执行",
    "bio-research": "生命科学研发工具链（基因组、单细胞、Nextflow），与生产制造业管理无关，"
    "与科学技能库的裁剪口径一致",
}
# 插件目录名 -> 中文分类名（缺省用 title_case 的目录名）。
KWP_CATEGORY_NAMES = {
    "productivity": "个人效率",
    "sales": "销售",
    "customer-support": "客户支持",
    "product-management": "产品管理",
    "marketing": "市场营销",
    "legal": "法务",
    "finance": "财务",
    "data": "数据分析",
    "enterprise-search": "企业检索",
    "engineering": "软件工程",
    "design": "设计",
    "human-resources": "人力资源",
    "operations": "运营管理",
    "small-business": "小微企业经营",
}

# 上游仓库根目录的许可证文件名候选；找到第一个就拷进 library-pack/LICENSES/。
LICENSE_CANDIDATES = ("LICENSE", "LICENSE.md", "LICENSE.txt")

# --------------------------------------------------------------------------
# 技能库 ③：本库自编的制造企业技能（library-src/manufacturing-skills/）
# --------------------------------------------------------------------------

MANUFACTURING_SOURCE = "ldfpku/openworker"
MANUFACTURING_AUTHOR = "OpenWorker 中文版"
MANUFACTURING_LICENSE = "MIT"

# 分类 id -> 中文分类名。
MANUFACTURING_CATEGORIES = {
    "production-delivery": "生产计划与交付",
    "quality-management": "质量管理",
    "equipment-spares": "设备与备件",
    "service-assets": "售后与工具资产",
    "process-engineering": "工艺与工装",
    "rd-ip": "研发与知识产权",
    "ehs": "安全环保",
}

# 技能目录名 -> 分类 id。目录里有、表里没有，或表里有、目录里没有，都报错——自编技能
# 不多不少正好是这张表。新写一个技能：建目录、写 SKILL.md、在这里登记。
MANUFACTURING_SKILLS = {
    "delivery-risk-review": "production-delivery",
    "production-scheduling": "production-delivery",
    "production-daily-report": "production-delivery",
    "material-shortage-tracking": "production-delivery",
    "quality-weekly-report": "quality-management",
    "ncr-8d-report": "quality-management",
    "root-cause-analysis": "quality-management",
    "spc-process-capability": "quality-management",
    "pfmea": "quality-management",
    "control-plan-inspection": "quality-management",
    "supplier-quality-audit": "quality-management",
    "qms-internal-audit": "quality-management",
    "equipment-inspection-review": "equipment-spares",
    "preventive-maintenance-plan": "equipment-spares",
    "spare-parts-stocktake": "equipment-spares",
    "repair-return-tracking": "service-assets",
    "returned-tool-inspection": "service-assets",
    "rental-ledger-review": "service-assets",
    "field-tools-weekly-report": "service-assets",
    "field-failure-analysis": "service-assets",
    "process-routing-card": "process-engineering",
    "heat-treatment-process": "process-engineering",
    "tooling-fixture-design": "process-engineering",
    "design-review-dfm": "rd-ip",
    "test-validation-plan": "rd-ip",
    "engineering-change-ecn": "rd-ip",
    "rd-project-proposal": "rd-ip",
    "patent-disclosure": "rd-ip",
    "ehs-hazard-inspection": "ehs",
}

# --------------------------------------------------------------------------
# 专家库：只打包与制造企业相关的专家
# --------------------------------------------------------------------------

# 整个分类保留（zh / en 共用，按 id 判断所以中英配对不会散）。
EXPERT_KEEP_CATEGORIES = {
    "company",          # 公司经营：CEO/CFO/COO/CTO……
    "finance",          # 财务金融
    "hr",               # 人力资源
    "legal",            # 法务
    "sales",            # 销售（B2B 售前、投标、赢单）
    "supply-chain",     # 供应链
    "support",          # 运营支持（数据分析、高管摘要、客服）
    "security",         # 企业 IT 安全
    "research",         # 研究综合
}
# 保留分类里仍然不要的个别专家。
EXPERT_DROP_IDS = {
    "finance/finance-hk-stock-compliance-reviewer",   # 港股合规
    "security/security-blockchain-security-auditor",  # 区块链
}
# 其余分类整体不打包（学术人文、设计、游戏、GIS、空间计算、付费媒体、社媒营销、
# 软件产品/测试、杂项专业服务），只按 id 捡回与制造企业经营、生产、研发、企业 IT 相关的。
EXPERT_KEEP_IDS = {
    "academic/academic-statistician",
    "design/design-brand-guardian",
    # engineering：工业/OT、企业 IT 与常用集成
    "engineering/engineering-mechanical-design-engineer",
    "engineering/engineering-pc-host-engineer",
    "engineering/engineering-embedded-firmware-engineer",
    "engineering/engineering-embedded-linux-driver-engineer",
    "engineering/engineering-fpga-digital-design-engineer",
    "engineering/engineering-iot-solution-architect",
    "engineering/engineering-iot-fleet-engineer",
    "engineering/engineering-it-service-manager",
    "engineering/engineering-network-engineer",
    "engineering/engineering-network-engineer-china",
    "engineering/engineering-security-engineer",
    "engineering/engineering-data-engineer",
    "engineering/engineering-data-visualization-engineer",
    "engineering/engineering-database-optimizer",
    "engineering/engineering-devops-automator",
    "engineering/engineering-sre",
    "engineering/engineering-incident-response-commander",
    "engineering/engineering-software-architect",
    "engineering/engineering-senior-developer",
    "engineering/engineering-code-reviewer",
    "engineering/engineering-desktop-app-engineer",
    "engineering/engineering-technical-writer",
    "engineering/engineering-ai-engineer",
    "engineering/engineering-prompt-engineer",
    "engineering/engineering-dingtalk-integration-developer",
    "engineering/engineering-feishu-integration-developer",
    "engineering/engineering-wechat-mini-program-developer",
    # marketing：面向工业品 B2B 的传播与内容
    "marketing/marketing-pr-communications-manager",
    "marketing/marketing-content-creator",
    "marketing/marketing-seo-specialist",
    "marketing/marketing-baidu-seo-specialist",
    "marketing/marketing-email-strategist",
    "marketing/marketing-wechat-official-account",
    "marketing/marketing-wechat-operator",
    "marketing/marketing-weixin-channels-strategist",
    "marketing/marketing-linkedin-content-creator",
    "marketing/marketing-cross-border-ecommerce",
    "marketing/marketing-daily-news-briefing",
    "marketing/marketing-social-media-strategist",
    "marketing/marketing-douyin-strategist",
    "marketing/marketing-zhihu-strategist",
    "marketing/marketing-short-video-editing-coach",
    "marketing/marketing-video-optimization-specialist",
    # product / project-management
    "product/product-manager",
    "product/product-feedback-synthesizer",
    "product/product-trend-researcher",
    "project-management/project-manager-senior",
    "project-management/project-management-project-shepherd",
    "project-management/project-management-meeting-notes-specialist",
    "project-management/project-management-jira-workflow-steward",
    # specialized：企业经营与职能
    "specialized/accounts-payable-agent",
    "specialized/business-strategist",
    "specialized/change-management-consultant",
    "specialized/corporate-training-designer",
    "specialized/customer-success-manager",
    "specialized/customer-service",
    "specialized/data-consolidation-agent",
    "specialized/data-privacy-officer",
    "specialized/esg-sustainability-officer",
    "specialized/grant-writer",
    "specialized/hr-onboarding",
    "specialized/language-translator",
    "specialized/technical-translator-agent",
    "specialized/legal-document-review",
    "specialized/ma-integration-manager",
    "specialized/operations-manager",
    "specialized/organizational-psychologist",
    "specialized/recruitment-specialist",
    "specialized/report-distribution-agent",
    "specialized/sales-data-extraction-agent",
    "specialized/sales-outreach",
    "specialized/specialized-chief-of-staff",
    "specialized/specialized-document-generator",
    "specialized/specialized-meeting-assistant",
    "specialized/specialized-pricing-analyst",
    "specialized/specialized-pricing-optimizer",
    "specialized/specialized-risk-assessor",
    "specialized/specialized-strategy-duel-agent",
    "specialized/specialized-workflow-architect",
    "specialized/specialized-master-plan-architect",
    "specialized/supply-chain-strategist",
    "specialized/prompt-engineer",
    # testing：嵌入式测试与通用的流程/工具评估
    "testing/testing-embedded-qa-engineer",
    "testing/testing-workflow-optimizer",
    "testing/testing-tool-evaluator",
    "testing/testing-test-results-analyzer",
}


def keep_expert(entry: dict) -> bool:
    """一个专家（zh 或 en，按 id）要不要打包。"""
    if entry["id"] in EXPERT_KEEP_IDS:
        return True
    return entry["category"] in EXPERT_KEEP_CATEGORIES and entry["id"] not in EXPERT_DROP_IDS


def prune_experts(raw: list[dict]) -> tuple[list[dict], list[str]]:
    """返回 (保留的条目, 去掉的 id 列表)。"""
    kept = [e for e in raw if keep_expert(e)]
    dropped = [e["id"] for e in raw if not keep_expert(e)]
    return kept, dropped


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
        if ":" not in line or line[:1] in (" ", "\t"):
            # 缩进行是嵌套块里的子字段（`metadata:` / 环境变量说明里的 `description:`），
            # 不是技能自己的 description——拿它覆盖顶层值就会把说明文字换成别的东西。
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key not in FRONTMATTER_KEYS or key in result:
            continue  # 只认第一次出现的顶层 key
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1].strip()
        if value:
            result[key] = value
    folded = {k for k, v in result.items() if v in _FOLDED_INDICATORS}
    if folded:
        result.update(_yaml_scalars(frontmatter, folded))
    return result


def _yaml_scalars(frontmatter: str, keys: set[str]) -> dict[str, str]:
    """`description: >` 这类折叠/块标量（knowledge-work-plugins 里三十来个技能这么写）
    逐行扫只能扫出 `>`；有 PyYAML（openworker 本身的依赖）就用它把这几个 key 读出来，
    值里的换行折成空格。没有 PyYAML 或解析失败则原样留着，统计里会点名。"""
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(frontmatter)
    except Exception:  # noqa: BLE001 — 任何 YAML 错误都退回逐行扫的结果
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = " ".join(value.split())
    return out


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

def scan_kwp_plugins(kwp_root: Path) -> tuple[list[dict], list[tuple[str, str]]]:
    """knowledge-work-plugins 仓库根目录下的插件：每个顶层目录带 `.claude-plugin/plugin.json`
    的就是一个插件（`partner-built/` 本身没有清单，其下的合作方插件嵌套一层、作者也不是
    Anthropic，两道门都进不来）。返回 (打包的插件列表, 跳过的 [(插件, 原因)])。"""
    plugins: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for top in sorted(p for p in kwp_root.iterdir() if p.is_dir()):
        if top.name.startswith("."):
            continue
        manifest = top / ".claude-plugin" / "plugin.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped.append((top.name, "plugin.json 读不出来"))
            continue
        author = str((data.get("author") or {}).get("name") or "").strip()
        if author not in KWP_ALLOWED_AUTHORS:
            skipped.append((top.name, f"作者不是 Anthropic（{author or '未填'}）"))
            continue
        if top.name in KWP_EXCLUDED_PLUGINS:
            skipped.append((top.name, KWP_EXCLUDED_PLUGINS[top.name]))
            continue
        if not (top / "skills").is_dir():
            skipped.append((top.name, "没有 skills/ 目录"))
            continue
        plugins.append(
            {
                "name": top.name,
                "dir": top,
                "author": author,
                "version": str(data.get("version") or ""),
                "description": str(data.get("description") or ""),
            }
        )
    return plugins, skipped


def resolve_kwp_ids(
    plugin_skills: list[tuple[str, Path]], reserved: set[str]
) -> dict[tuple[str, str], str]:
    """每个 (插件, 技能目录) 在 library-pack 里的 id。openworker 的技能目录是扁平的、
    按技能名索引（coworker/skills/base.py 用 frontmatter name 做 key，install 按 name
    拷目录），所以 id 必须在 knowledge-work-plugins 全库 + 保留的科学技能里唯一。
    只在撞名时加 `<插件>-` 前缀：技能正文互相引用用的是裸名（`inventory-planner`、
    `rep-context`……），全部加前缀会把这些引用悄悄打断。"""
    counts: dict[str, int] = {}
    for _plugin, skill_dir in plugin_skills:
        counts[skill_dir.name] = counts.get(skill_dir.name, 0) + 1
    ids: dict[tuple[str, str], str] = {}
    used = set(reserved)
    for plugin, skill_dir in plugin_skills:
        base = skill_dir.name
        skill_id = base if counts[base] == 1 and base not in reserved else f"{plugin}-{base}"
        if skill_id in used:
            print(f"ERROR: 技能 id 撞车且加前缀也解不开：{skill_id}", file=sys.stderr)
            sys.exit(1)
        used.add(skill_id)
        ids[(plugin, base)] = skill_id
    return ids


# markdown 链接目标里的相对路径（不是 http(s)/mailto/锚点/绝对路径）。
_RELATIVE_LINK_RE = re.compile(r"\]\((?!(?:[a-z][a-z0-9+.-]*:|#|/))([^)\s]+)\)", re.IGNORECASE)
# `${CLAUDE_PLUGIN_ROOT}/skills/dashboard.html`：Claude Code 插件约定的插件根目录变量。
_PLUGIN_ROOT_VAR_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s`'\")]+)")


def _plugin_dest_rel(resolved: str) -> str:
    """插件内相对路径 -> 技能目录内副本的相对路径：`skills/<其他技能>/x` 放到 `<其他技能>/x`，
    插件根目录的文件（`CONNECTORS.md`、`shared/*`）按原路径放。"""
    return resolved[len("skills/"):] if resolved.startswith("skills/") else resolved


def _rewrite_plugin_refs(
    text: str, orig_rel: str, new_rel: str, plugin_dir: Path, skill_root: str
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """把一个 md 文件里跳出本技能目录的相对链接改成指向技能目录内的副本。

    `orig_rel` 是该文件在上游插件目录里的相对路径（链接按它解析——副本可能被放到和
    上游不同的深度，`../` 的个数只对原位置有意义）；`new_rel` 是副本在目标技能目录里的
    相对路径（改写后的链接按它计算）；`skill_root` 是上游技能目录相对插件根的路径
    （`skills/<name>`）。链接落在技能目录内的不动（整棵拷过来了）；落在插件内其他地方
    （根目录的 CONNECTORS.md、shared/*.md、别的技能的 reference/*.md）且目标存在的，
    记入要拷贝的副本并改写；目标不存在或跳出插件的，原样保留并点名。
    返回 (改写后文本, [(插件内相对路径, 技能目录内相对路径)], 悬空链接)。"""
    copies: list[tuple[str, str]] = []
    dangling: list[str] = []
    orig_dir = posixpath.dirname(orig_rel)
    new_dir = posixpath.dirname(new_rel)

    def _link(m: re.Match) -> str:
        target = m.group(1)
        path_part, _, anchor = target.partition("#")
        if not path_part:
            return m.group(0)
        resolved = posixpath.normpath(posixpath.join(orig_dir, path_part)) if orig_dir else posixpath.normpath(path_part)
        if resolved == skill_root or resolved.startswith(skill_root + "/"):
            return m.group(0)  # 技能目录内部
        if resolved.startswith("../") or not (plugin_dir / resolved).is_file():
            if target.startswith("../"):
                dangling.append(target)
            return m.group(0)
        dest_rel = _plugin_dest_rel(resolved)
        copies.append((resolved, dest_rel))
        new_link = posixpath.relpath(dest_rel, new_dir or ".")
        return f"]({new_link}{'#' + anchor if anchor else ''})"

    def _var(m: re.Match) -> str:
        rel = m.group(1)
        if not (plugin_dir / rel).is_file():
            return m.group(0)
        # `skills/<file>` 是插件 skills/ 目录下的散文件，在技能目录里就叫它的文件名。
        dest_rel = _plugin_dest_rel(rel)
        copies.append((rel, dest_rel))
        return posixpath.relpath(dest_rel, new_dir or ".")

    text = _RELATIVE_LINK_RE.sub(_link, text)
    text = _PLUGIN_ROOT_VAR_RE.sub(_var, text)
    return text, copies, dangling


def _edit_frontmatter(md: Path, *, name: str | None, source: str) -> None:
    """在现成的 frontmatter 块里改 `name:`（仅重名改名时）并写入 `source:` 来源行，
    其余行与文件的行尾符原样保留（思路同 coworker/skills/store.py 的 _stamp_source）。
    `source:` 是 openworker 读的 provenance 键：安装后 设置 ▸ 技能 把它显示成徽标。"""
    with open(md, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    if not text.startswith("---"):
        raise ValueError(f"{md}: 没有 frontmatter，无法标记来源")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError(f"{md}: frontmatter 没有闭合")
    crlf = end > 0 and text[end - 1] == "\r"
    sep = "\r\n" if crlf else "\n"
    at = end - 1 if crlf else end
    lines = text[3:at].split(sep)  # lines[0] 是开头 --- 后面的空串
    out: list[str] = []
    stamped = False
    for line in lines:
        key = line.split(":", 1)[0].strip().lower() if ":" in line else ""
        nested = line.startswith((" ", "\t"))
        if name is not None and key == "name" and not nested:
            out.append(f"name: {name}")
        elif key == "source" and not nested:
            out.append(f"source: {source}")
            stamped = True
        else:
            out.append(line)
    if not stamped:
        out.append(f"source: {source}")
    with open(md, "w", encoding="utf-8", newline="") as fh:
        fh.write("---" + sep.join(out) + text[at:])


def _rename_references(text: str, renames: dict[str, str]) -> str:
    """同一插件里被改名技能的裸名引用（`route to lead-triage`、`` `lead-triage` ``、
    `skills/lead-triage/`）换成新 id——agent 照正文 load_skill(旧名) 会找不到。前后不能
    是字母、数字、下划线或连字符：`\\b` 会在新名字 `sales-lead-triage` 内部再命中一次。"""
    for old, new in renames.items():
        text = re.sub(rf"(?<![\w-]){re.escape(old)}(?![\w-])", new, text)
    return text


def copy_kwp_skill(
    skill_dir: Path,
    plugin_dir: Path,
    dest_dir: Path,
    skill_id: str,
    renames: dict[str, str] | None = None,
) -> dict:
    """把一个 knowledge-work-plugins 技能整棵拷到 dest_dir 并做可执行化改动：链接改写、
    插件根目录文件拷入、同插件改名技能的引用改写、frontmatter 改名 + 来源标记。
    `renames` 是本插件内 {旧技能名: 新 id}。返回 {"copied", "dangling", "renamed_refs"}。"""
    copy_skill_dir(skill_dir, dest_dir)
    copied: list[str] = []
    dangling: list[str] = []
    skill_root = f"skills/{skill_dir.name}"
    # 队列元素：(副本路径, 上游插件内相对路径)。拷进来的 md 副本（shared/*.md、别的技能的
    # reference/*.md）自己也可能带跳出目录的链接，所以也要过一遍，链接按它们的上游位置解析。
    queue: list[tuple[Path, str]] = [
        (p, f"{skill_root}/{p.relative_to(dest_dir).as_posix()}")
        for p in sorted(_walk_files(dest_dir))
        if p.suffix.lower() == ".md"
    ]
    seen: set[Path] = set()
    while queue:
        md, orig_rel = queue.pop(0)
        if md in seen:
            continue
        seen.add(md)
        new_rel = md.relative_to(dest_dir).as_posix()
        with open(md, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        new_text, copies, missing = _rewrite_plugin_refs(text, orig_rel, new_rel, plugin_dir, skill_root)
        for src_rel, dest_rel in copies:
            dst = dest_dir / dest_rel
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(plugin_dir / src_rel, dst)
                copied.append(dest_rel)
                if dst.suffix.lower() == ".md":
                    queue.append((dst, src_rel))
        if new_text != text:
            with open(md, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_text)
        dangling.extend(f"{new_rel} -> {link}" for link in missing)
    renamed_refs: list[str] = []
    if renames:
        # 第二遍重新遍历：刚拷进来的 shared/*.md 也会引用改名的技能。
        for md in sorted(p for p in _walk_files(dest_dir) if p.suffix.lower() == ".md"):
            with open(md, "r", encoding="utf-8", newline="") as fh:
                text = fh.read()
            new_text = _rename_references(text, renames)
            if new_text != text:
                with open(md, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new_text)
                renamed_refs.append(md.relative_to(dest_dir).as_posix())
    renamed = skill_id != skill_dir.name
    _edit_frontmatter(dest_dir / "SKILL.md", name=skill_id if renamed else None, source=KWP_SOURCE)
    return {"copied": copied, "dangling": dangling, "renamed_refs": renamed_refs}


def copy_licenses(out_dir: Path, sources: dict[str, Path]) -> list[str]:
    """把每个上游仓库根目录的许可证全文拷到 LICENSES/<仓库>-LICENSE<后缀>——Apache-2.0
    §4(a) 要求再分发时附上许可证副本，MIT 也要求保留，光给链接不算。"""
    dest = out_dir / "LICENSES"
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name, root in sources.items():
        for cand in LICENSE_CANDIDATES:
            src = root / cand
            if src.is_file():
                target = dest / f"{name}-LICENSE{src.suffix or '.txt'}"
                shutil.copy2(src, target)
                copied.append(target.name)
                break
        else:
            print(f"注意：{name} 仓库根目录没有找到许可证文件（{'/'.join(LICENSE_CANDIDATES)}）")
    return copied


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


def build_skill_entry(
    skill_dir: Path,
    *,
    skill_id: str,
    category: str,
    category_name: str,
    source: str,
    author: str,
    license_default: str = "",
    plugin: str = "",
) -> dict:
    """index.json 里的一条技能。在**拷贝后的**目录上算（frontmatter 已改名、副本已拷入），
    所以 `files` 数的是真正随包分发的文件；`name` 必须等于目录名（install 按它拷目录）。"""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm.get("name", skill_id) != skill_id:
        print(f"注意：{skill_id} 的 frontmatter name 是 {fm['name']!r}，索引按目录名记")
    entry = {
        "id": skill_id,
        "category": category,
        "categoryName": category_name,
        "name": skill_id,
        "description": fm.get("description", DEFAULT_DESCRIPTION),
        "emoji": fm.get("emoji", DEFAULT_EMOJI),
        "color": fm.get("color", DEFAULT_COLOR),
        "license": fm.get("license", "") or license_default,
        "compatibility": fm.get("compatibility", ""),
        "source": source,
        "author": author,
        "scripts": count_files(skill_dir / "scripts", SCRIPT_EXTS),
        # 上游两种拼法都有（scientific 用 references/，small-business 用 reference/）。
        "references": count_files(skill_dir / "references") + count_files(skill_dir / "reference"),
        "assets": count_files(skill_dir / "assets"),
        "files": count_files(skill_dir),
    }
    if plugin:
        entry["plugin"] = plugin
    return entry


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

MANAGED_ENTRIES = ("experts", "skills", "LICENSES", "index.json", "ATTRIBUTION.md")


def snapshot_zh_layer(out_dir: Path) -> dict[str, dict]:
    """技能的中文译文层（skills/<id>/SKILL.zh.md 与 index.json 里的 description_zh）
    是本 fork 生成的内容、不来自上游——重建前先快照，重建后按技能 id 原样放回，
    否则每次再生成都会抹掉全部译文。返回 {技能 id: {"skill_md": 译文, "description_zh": 描述}}。"""
    saved: dict[str, dict] = {}
    index_path = out_dir / "index.json"
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            for row in data.get("skills", []) or []:
                sid = row.get("id") or row.get("name")
                if sid and row.get("description_zh"):
                    saved.setdefault(sid, {})["description_zh"] = row["description_zh"]
        except (OSError, ValueError):
            pass
    skills_dir = out_dir / "skills"
    if skills_dir.is_dir():
        for d in skills_dir.iterdir():
            zh = d / "SKILL.zh.md"
            if d.is_dir() and zh.is_file():
                try:
                    saved.setdefault(d.name, {})["skill_md"] = zh.read_text(encoding="utf-8")
                except OSError:
                    pass
    return saved


def restore_zh_layer(
    out_dir: Path, skill_entries: list[dict], saved: dict[str, dict]
) -> None:
    """把快照的译文层放回重建后的技能目录与索引条目；新技能没有译文时点名提示。"""
    no_description: list[str] = []
    no_body: list[str] = []
    for entry in skill_entries:
        if entry.get("lang") == "zh":
            continue  # 正文和描述本来就是中文（本库自编），没有译文层这回事
        zh = saved.get(entry["id"], {})
        if zh.get("skill_md"):
            # newline="\n"：Windows 上文本模式默认把 \n 写成 \r\n，而仓库按 .gitattributes
            # 存 LF、打包时直接拿工作区文件——不显式指定，每次在 Windows 重建都会把译文层
            # 和索引写成 CRLF（git 提交时虽会规范化，但随安装包分发的是工作区那份）。
            (out_dir / "skills" / entry["id"] / "SKILL.zh.md").write_text(
                zh["skill_md"], encoding="utf-8", newline="\n"
            )
        else:
            no_body.append(entry["id"])
        if zh.get("description_zh"):
            entry["description_zh"] = zh["description_zh"]
        else:
            no_description.append(entry["id"])
    # 两条分开报：卡片上的 description_zh 每个技能都应该有，少一个就是译文丢了；
    # 正文 SKILL.zh.md 只有科学技能库那批有（knowledge-work-plugins 的正文没翻译，
    # 详情页回退英文），一直缺是预期内的，只报个数。
    if no_description:
        print(
            f"注意：{len(no_description)} 个技能缺 description_zh（卡片将显示英文）："
            + "、".join(no_description)
        )
    if no_body:
        print(f"提示：{len(no_body)} 个技能没有 SKILL.zh.md（详情正文显示英文原件）")


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
`packaging/gen_library.py` 从以下四个上游开源仓库自动抓取生成，随 openworker 源码一起分发。

## 上游仓库

| 内容 | 上游仓库 | 许可证 | 抓取时 commit |
|---|---|---|---|
| 英文专家库（`experts/en/`） | https://github.com/msitarzewski/agency-agents | MIT | `{en_commit}` |
| 中文专家库（`experts/zh/`） | https://github.com/jnMetaCode/agency-agents-zh | MIT | `{zh_commit}` |
| 科学技能库（`skills/`，按保留清单裁剪） | https://github.com/K-Dense-AI/scientific-agent-skills | MIT | `{skills_commit}` |
| 知识工作技能库（`skills/`，Anthropic 官方插件） | https://github.com/anthropics/knowledge-work-plugins | Apache-2.0 | `{kwp_commit}` |
| 制造企业技能（`skills/`，本库自编，中文） | 本仓库 `library-src/manufacturing-skills/` | MIT（随本仓库） | — |

## 版权声明

- agency-agents：`Copyright (c) 2025 AgentLand Contributors`
- agency-agents-zh（英文原版 + 中文汉化，双版权）：
  - `Copyright (c) 2025 Michael Sitarzewski (original English version)`
  - `Copyright (c) 2026 jnMetaCode (Chinese translation and localization)`
- scientific-agent-skills：`Copyright (c) 2025 K-Dense Inc.`
- knowledge-work-plugins：Anthropic（各插件 `plugin.json` 的 author 均为 Anthropic；仓库
  LICENSE 是 Apache License 2.0 原文，未填写版权年份）

前三者以 MIT License 分发，knowledge-work-plugins 以 Apache License 2.0 分发。各许可证全文
随本目录一同分发在 `LICENSES/` 下：

{license_lines}

原始出处：

- https://github.com/msitarzewski/agency-agents/blob/main/LICENSE
- https://github.com/jnMetaCode/agency-agents-zh/blob/main/LICENSE
- https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/LICENSE.md
- https://github.com/anthropics/knowledge-work-plugins/blob/main/LICENSE

## 与本 fork 的关系

openworker 是 https://github.com/andrewyng/openworker 的一个公开 fork，本数据包随
https://github.com/ldfpku/openworker 一同分发。

整个数据包面向生产制造企业（从生产管理到研发）裁剪，口径如下。

**专家库**按原始 Markdown 文件（含 frontmatter）原样拷贝，未做修改，但只打包与制造企业
经营、生产、研发、企业 IT 相关的专家（规则在 `packaging/gen_library.py` 的
`EXPERT_KEEP_CATEGORIES` / `EXPERT_KEEP_IDS` / `EXPERT_DROP_IDS`，按专家 id 判断，中英
配对不会散）：中文库保留 {zh_kept} / {zh_total}，英文库保留 {en_kept} / {en_total}。整类保留的：
公司经营、财务金融、人力资源、法务、销售、供应链、运营支持、安全、研究；整类不打包、只按 id
捡回个别专家的：学术研究、设计、工程开发（只留工业/OT 与企业 IT）、市场营销（只留 B2B 传播
与内容）、产品、项目管理、专业服务、质量测试；整类不打包的：游戏开发、GIS、空间计算、付费
媒体、医疗。

**本库自编技能**（`library-src/manufacturing-skills/`，{mfg_kept} 个，中文正文）面向油田井下
工具制造企业的生产计划与交付、质量管理、设备与备件、售后与工具资产、工艺与工装、研发与
知识产权、安全环保七类场景，来源标记 `{mfg_source}`，随本仓库以 MIT 分发。

**上游技能库**按目录整棵拷贝。为了让技能在 openworker 里能直接安装、执行，对拷贝件做了下面
几处**有记录的改动**（Apache License 2.0 §4(b) 要求的修改声明）：

- **来源标记**：每个技能的 `SKILL.md` frontmatter 追加一行 `source: <上游仓库>`
  （`{kwp_source}` 或 `{sci_source}`）；安装后在 设置 ▸ 技能 里显示为来源徽标。
  index.json 里对应 `source` / `author` / `plugin` 字段。
- **重名改名**：openworker 的技能目录是扁平的、按技能名索引，knowledge-work-plugins 里
  不同插件间重名的技能（以及与保留的科学技能重名的）改为 `<插件名>-<技能名>`，并同步
  改写其 `SKILL.md` 的 `name:`；其余技能保持上游原名：
{renamed_lines}
  同一插件里其他技能正文对这些旧名的裸名引用（`route to lead-triage` 之类）也一并换成
  新 id，否则 agent 照正文去加载会找不到；本次改写了 {renamed_refs_count} 个文件：
{renamed_refs_lines}
- **链接改写**：技能正文里指向插件根目录的相对链接（`../../CONNECTORS.md`、small-business
  的 `../../shared/*.md`）改为指向技能目录内的副本，副本一并拷入（`CONNECTORS.md`、
  `shared/`）；指向同插件其他技能参考资料的链接（`../<技能>/reference/*.md`）同样拷入
  本技能目录的 `<技能>/` 子目录并改写；productivity/start 引用的
  `${{CLAUDE_PLUGIN_ROOT}}/skills/dashboard.html` 拷为技能目录内的 `dashboard.html`。
- **未改动**：`$ARGUMENTS`、`~~连接器占位符`、`allowed-tools`、`argument-hint`、
  `user-invocable`、`triggers` 等 Claude Code / Cowork 约定原样保留——openworker 只读
  `name` / `description` / `source`，忽略其余字段。目标文件在上游就不存在、无法拷入的
  链接（{dangling_count} 处）原样保留：
{dangling_lines}

### 未打包的 knowledge-work-plugins 内容

{excluded_lines}
- `partner-built/` 下的合作方插件（作者不是 Anthropic）一律不打包。
- 各插件的 `.mcp.json`、`commands/`、`README.md`、`CONNECTORS.md` 本身不单独打包
  （`CONNECTORS.md` 只作为技能目录内的副本随技能走）。

### 科学技能库的保留清单

scientific-agent-skills 共 {sci_total} 个技能，只保留与生产制造业管理相关的 {sci_kept} 个，
并按用途重新分类（清单在 `packaging/gen_library.py` 的 `SCIENTIFIC_KEEP`，增删改表即可）：

| 技能 | 分类 | 保留理由 |
|---|---|---|
{keep_lines}

本 fork 新增的内容：生成/维护脚本（`packaging/gen_library.py`）、本说明文件、`LICENSES/`
目录，以及技能的中文译文层（各技能目录下的 `SKILL.zh.md` 与 index.json 中的
`description_zh` 字段，由本 fork 翻译生成，仅用于库内浏览展示；安装进全局技能目录的始终
是上游英文原件加上述来源标记）。

## 生成信息

- 生成时间（UTC）：`{generated_at}`
- 生成脚本：`packaging/gen_library.py`
"""


def write_attribution(path: Path, generated: dict, report: dict) -> None:
    renamed = report.get("renamed") or []
    renamed_lines = "\n".join(
        f"  - `{plugin}/skills/{old}` → `{new}`" for plugin, old, new in renamed
    ) or "  - （本次没有重名）"
    dangling = report.get("dangling") or []
    dangling_lines = "\n".join(f"  - `{d}`" for d in dangling) or "  - （无）"
    renamed_refs = report.get("renamed_refs") or []
    renamed_refs_lines = "\n".join(f"  - `{r}`" for r in renamed_refs) or "  - （无）"
    excluded_lines = "\n".join(
        f"- `{name}`：{reason}" for name, reason in (report.get("kwp_skipped") or [])
    ) or "- （无）"
    keep_lines = "\n".join(
        f"| `{sid}` | {cat_name} | {reason} |"
        for sid, (_cat, cat_name, reason) in SCIENTIFIC_KEEP.items()
    )
    license_lines = "\n".join(f"- `LICENSES/{name}`" for name in (report.get("licenses") or []))
    experts_total = report.get("experts_total") or {}
    experts_kept = report.get("experts_kept") or {}
    content = ATTRIBUTION_TEMPLATE.format(
        en_commit=generated.get("agency-agents", "unknown"),
        zh_commit=generated.get("agency-agents-zh", "unknown"),
        skills_commit=generated.get("scientific-agent-skills", "unknown"),
        kwp_commit=generated.get("knowledge-work-plugins", "unknown"),
        kwp_source=KWP_SOURCE,
        sci_source=SCIENTIFIC_SOURCE,
        mfg_source=MANUFACTURING_SOURCE,
        mfg_kept=report.get("mfg_kept", 0),
        zh_total=experts_total.get("zh", 0),
        zh_kept=experts_kept.get("zh", 0),
        en_total=experts_total.get("en", 0),
        en_kept=experts_kept.get("en", 0),
        renamed_lines=renamed_lines,
        renamed_refs_count=len(renamed_refs),
        renamed_refs_lines=renamed_refs_lines,
        dangling_count=len(dangling),
        dangling_lines=dangling_lines,
        excluded_lines=excluded_lines,
        sci_total=report.get("sci_total", 0),
        sci_kept=report.get("sci_kept", 0),
        keep_lines=keep_lines,
        license_lines=license_lines,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    path.write_text(content, encoding="utf-8", newline="\n")


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


def print_stats(en_entries, zh_entries, skill_entries, out_dir: Path, report: dict) -> None:
    pair_count = sum(1 for e in zh_entries if e["pair"])
    print("=" * 60)
    print("生成完成，统计如下：")
    totals = report.get("experts_total") or {}
    print(f"  英文专家（en）    : {len(en_entries)}（上游 {totals.get('en', '?')}）")
    print(f"  中文专家（zh）    : {len(zh_entries)}（上游 {totals.get('zh', '?')}）")
    print(f"  中英配对（pair）  : {pair_count}")
    print(f"  技能（skills）    : {len(skill_entries)}")
    print(f"    本库自编制造技能 : {report.get('mfg_kept', 0)}")
    print(
        f"    科学技能库       : 保留 {report.get('sci_kept', 0)} / {report.get('sci_total', 0)}"
    )
    print(
        f"    知识工作技能库   : {report.get('kwp_kept', 0)} 个技能，"
        f"来自 {report.get('kwp_plugins', 0)} 个插件"
    )
    for name, reason in report.get("kwp_skipped") or []:
        print(f"      跳过插件 {name:26s} {reason}")
    for plugin, old, new in report.get("renamed") or []:
        print(f"      重名改名 {plugin}/{old} -> {new}")
    for r in report.get("renamed_refs") or []:
        print(f"      正文引用随改名更新 {r}")
    for d in report.get("dangling") or []:
        print(f"      未改写的跨技能链接 {d}")
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


def default_manufacturing_dir() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "library-src" / "manufacturing-skills"


def build_manufacturing_skills(src_dir: Path, out_dir: Path, reserved: set[str]) -> list[dict]:
    """本库自编技能：目录与 MANUFACTURING_SKILLS 必须一一对应；拷贝、打来源标记，
    description_zh 直接取 description（正文就是中文）。"""
    dirs = {d.name: d for d in scan_skill_dirs(src_dir)}
    unknown = sorted(set(dirs) - set(MANUFACTURING_SKILLS))
    missing = sorted(set(MANUFACTURING_SKILLS) - set(dirs))
    if unknown or missing:
        if unknown:
            print(f"ERROR: {src_dir} 里有未登记的技能目录：{'、'.join(unknown)}（登记到 MANUFACTURING_SKILLS）", file=sys.stderr)
        if missing:
            print(f"ERROR: MANUFACTURING_SKILLS 登记了但目录不存在：{'、'.join(missing)}", file=sys.stderr)
        sys.exit(1)
    entries: list[dict] = []
    for skill_id, category in MANUFACTURING_SKILLS.items():
        if skill_id in reserved:
            print(f"ERROR: 自编技能 {skill_id} 与上游技能重名，请改目录名", file=sys.stderr)
            sys.exit(1)
        category_name = MANUFACTURING_CATEGORIES.get(category)
        if category_name is None:
            print(f"ERROR: 技能 {skill_id} 的分类 {category} 不在 MANUFACTURING_CATEGORIES 里", file=sys.stderr)
            sys.exit(1)
        dest = out_dir / "skills" / skill_id
        copy_skill_dir(dirs[skill_id], dest)
        _edit_frontmatter(dest / "SKILL.md", name=None, source=MANUFACTURING_SOURCE)
        entry = build_skill_entry(
            dest,
            skill_id=skill_id,
            category=category,
            category_name=category_name,
            source=MANUFACTURING_SOURCE,
            author=MANUFACTURING_AUTHOR,
            license_default=MANUFACTURING_LICENSE,
        )
        entry["lang"] = "zh"
        entry["description_zh"] = entry["description"]
        entries.append(entry)
    return entries


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="生成 openworker 内置专家库 / 技能库数据包（library-pack/）",
    )
    p.add_argument(
        "--sources", required=True,
        help=(
            "源目录，其下必须有 agency-agents / agency-agents-zh / scientific-agent-skills / "
            "knowledge-work-plugins 四个子目录"
        ),
    )
    p.add_argument(
        "--out", default=None,
        help="输出目录，默认 <repo>/library-pack",
    )
    p.add_argument(
        "--manufacturing", default=None,
        help="本库自编技能的源目录，默认 <repo>/library-src/manufacturing-skills（测试用）",
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
    manufacturing_dir = (
        Path(args.manufacturing).resolve() if args.manufacturing else default_manufacturing_dir()
    )
    if not manufacturing_dir.is_dir():
        print(f"ERROR: 自编技能目录不存在：{manufacturing_dir}", file=sys.stderr)
        sys.exit(1)

    en_root = sources / "agency-agents"
    zh_root = sources / "agency-agents-zh"
    skills_repo_root = sources / "scientific-agent-skills"
    skills_root = skills_repo_root / "skills"
    kwp_root = sources / "knowledge-work-plugins"

    source_roots = {
        "agency-agents": en_root,
        "agency-agents-zh": zh_root,
        "scientific-agent-skills": skills_repo_root,
        "knowledge-work-plugins": kwp_root,
    }
    for name, p in source_roots.items():
        if not p.is_dir():
            print(f"ERROR: --sources 下缺少 {name}（期望路径：{p}）", file=sys.stderr)
            sys.exit(1)

    zh_layer = snapshot_zh_layer(out_dir)
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

    en_all = scan_experts(en_root, en_category_name)
    zh_all = scan_experts(zh_root, zh_category_name)
    en_raw, en_dropped = prune_experts(en_all)
    zh_raw, zh_dropped = prune_experts(zh_all)

    en_ids = {e["id"] for e in en_raw}
    zh_ids = {e["id"] for e in zh_raw}

    en_entries = finalize_expert_entries(en_raw, zh_ids)
    zh_entries = finalize_expert_entries(zh_raw, en_ids)

    copy_experts(en_raw, out_dir / "experts" / "en")
    copy_experts(zh_raw, out_dir / "experts" / "zh")

    # ---- 技能库 ①：scientific-agent-skills，只要保留清单里的 ----
    sci_dirs = scan_skill_dirs(skills_root)
    sci_entries: list[dict] = []
    for d in sci_dirs:
        keep = SCIENTIFIC_KEEP.get(d.name)
        if keep is None:
            continue
        category, category_name, _reason = keep
        dest = out_dir / "skills" / d.name
        copy_skill_dir(d, dest)
        _edit_frontmatter(dest / "SKILL.md", name=None, source=SCIENTIFIC_SOURCE)
        sci_entries.append(
            build_skill_entry(
                dest,
                skill_id=d.name,
                category=category,
                category_name=category_name,
                source=SCIENTIFIC_SOURCE,
                author=SCIENTIFIC_AUTHOR,
            )
        )
    missing_keep = sorted(set(SCIENTIFIC_KEEP) - {e["id"] for e in sci_entries})
    if missing_keep:
        # 保留清单点名的技能上游已经没有了——清单该改，不能悄悄少打包。
        print(f"ERROR: SCIENTIFIC_KEEP 里这些技能在上游找不到：{'、'.join(missing_keep)}", file=sys.stderr)
        sys.exit(1)

    # ---- 技能库 ②：knowledge-work-plugins，每个插件一个分类 ----
    plugins, kwp_skipped = scan_kwp_plugins(kwp_root)
    plugin_skills = [(p["name"], d) for p in plugins for d in scan_skill_dirs(p["dir"] / "skills")]
    kwp_ids = resolve_kwp_ids(plugin_skills, reserved={e["id"] for e in sci_entries})
    kwp_entries: list[dict] = []
    renamed: list[tuple[str, str, str]] = []
    dangling: list[str] = []
    renamed_refs: list[str] = []
    for p in plugins:
        category_name = KWP_CATEGORY_NAMES.get(p["name"]) or title_case(p["name"])
        plugin_renames = {
            old: new for (plugin, old), new in kwp_ids.items() if plugin == p["name"] and new != old
        }
        for d in scan_skill_dirs(p["dir"] / "skills"):
            skill_id = kwp_ids[(p["name"], d.name)]
            dest = out_dir / "skills" / skill_id
            notes = copy_kwp_skill(d, p["dir"], dest, skill_id, plugin_renames)
            if skill_id != d.name:
                renamed.append((p["name"], d.name, skill_id))
            dangling.extend(f"{skill_id}/{x}" for x in notes["dangling"])
            renamed_refs.extend(f"{skill_id}/{x}" for x in notes["renamed_refs"])
            kwp_entries.append(
                build_skill_entry(
                    dest,
                    skill_id=skill_id,
                    category=p["name"],
                    category_name=category_name,
                    source=KWP_SOURCE,
                    author=p["author"],
                    license_default=KWP_LICENSE,
                    plugin=p["name"],
                )
            )

    # ---- 技能库 ③：本库自编的制造企业技能，排在最前（专家库页面的分类顺序跟它走） ----
    mfg_entries = build_manufacturing_skills(
        manufacturing_dir, out_dir, reserved={e["id"] for e in sci_entries + kwp_entries}
    )

    skill_entries = mfg_entries + sci_entries + kwp_entries
    unparsed = [e["id"] for e in skill_entries if not e["description"] or e["description"] in _FOLDED_INDICATORS]
    if unparsed:
        print(f"注意：{len(unparsed)} 个技能的 description 没读出来（折叠标量需要 PyYAML）：" + "、".join(unparsed))
    restore_zh_layer(out_dir, skill_entries, zh_layer)

    report = {
        "experts_total": {"zh": len(zh_all), "en": len(en_all)},
        "experts_kept": {"zh": len(zh_raw), "en": len(en_raw)},
        "experts_dropped": {"zh": zh_dropped, "en": en_dropped},
        "mfg_kept": len(mfg_entries),
        "sci_total": len(sci_dirs),
        "sci_kept": len(sci_entries),
        "kwp_plugins": len(plugins),
        "kwp_kept": len(kwp_entries),
        "kwp_skipped": kwp_skipped,
        "renamed": renamed,
        "renamed_refs": renamed_refs,
        "dangling": dangling,
        "licenses": copy_licenses(out_dir, source_roots),
    }

    # ---- commit ----
    generated = {name: git_commit(root) for name, root in source_roots.items()}

    # ---- index.json ----
    index = {
        "version": 1,
        "generated": generated,
        "experts": {"zh": zh_entries, "en": en_entries},
        "skills": skill_entries,
    }
    with (out_dir / "index.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # ---- ATTRIBUTION.md ----
    write_attribution(out_dir / "ATTRIBUTION.md", generated, report)

    print_stats(en_entries, zh_entries, skill_entries, out_dir, report)


if __name__ == "__main__":
    main()
