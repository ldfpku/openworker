# 数据来源与许可声明

本目录（`library-pack/`）是 openworker 内置的专家库与技能库数据包，由
`packaging/gen_library.py` 从以下四个上游开源仓库自动抓取生成，随 openworker 源码一起分发。

## 上游仓库

| 内容 | 上游仓库 | 许可证 | 抓取时 commit |
|---|---|---|---|
| 英文专家库（`experts/en/`） | https://github.com/msitarzewski/agency-agents | MIT | `32230ec4790a24cfd187e08245cb3c6f28998b9d` |
| 中文专家库（`experts/zh/`） | https://github.com/jnMetaCode/agency-agents-zh | MIT | `972452cdedef8d04fed4a8dd1dc10623e33ed412` |
| 科学技能库（`skills/`，按保留清单裁剪） | https://github.com/K-Dense-AI/scientific-agent-skills | MIT | `390f5146bf3c1877cf15636a3dd7b775e4f0f185` |
| 知识工作技能库（`skills/`，Anthropic 官方插件） | https://github.com/anthropics/knowledge-work-plugins | Apache-2.0 | `8444efcd48f7012f09797778a36a33e73d0861f4` |
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

- `LICENSES/agency-agents-LICENSE.txt`
- `LICENSES/agency-agents-zh-LICENSE.txt`
- `LICENSES/scientific-agent-skills-LICENSE.md`
- `LICENSES/knowledge-work-plugins-LICENSE.txt`

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
配对不会散）：中文库保留 127 / 276，英文库保留 103 / 273。整类保留的：
公司经营、财务金融、人力资源、法务、销售、供应链、运营支持、安全、研究；整类不打包、只按 id
捡回个别专家的：学术研究、设计、工程开发（只留工业/OT 与企业 IT）、市场营销（只留 B2B 传播
与内容）、产品、项目管理、专业服务、质量测试；整类不打包的：游戏开发、GIS、空间计算、付费
媒体、医疗。

**本库自编技能**（`library-src/manufacturing-skills/`，29 个，中文正文）面向油田井下
工具制造企业的生产计划与交付、质量管理、设备与备件、售后与工具资产、工艺与工装、研发与
知识产权、安全环保七类场景，来源标记 `ldfpku/openworker`，随本仓库以 MIT 分发。

**上游技能库**按目录整棵拷贝。为了让技能在 openworker 里能直接安装、执行，对拷贝件做了下面
几处**有记录的改动**（Apache License 2.0 §4(b) 要求的修改声明）：

- **来源标记**：每个技能的 `SKILL.md` frontmatter 追加一行 `source: <上游仓库>`
  （`anthropics/knowledge-work-plugins` 或 `K-Dense-AI/scientific-agent-skills`）；安装后在 设置 ▸ 技能 里显示为来源徽标。
  index.json 里对应 `source` / `author` / `plugin` 字段。
- **重名改名**：openworker 的技能目录是扁平的、按技能名索引，knowledge-work-plugins 里
  不同插件间重名的技能（以及与保留的科学技能重名的）改为 `<插件名>-<技能名>`，并同步
  改写其 `SKILL.md` 的 `name:`；其余技能保持上游原名：
  - `data/skills/statistical-analysis` → `data-statistical-analysis`
  - `marketing/skills/competitive-brief` → `marketing-competitive-brief`
  - `product-management/skills/competitive-brief` → `product-management-competitive-brief`
  - `sales/skills/lead-triage` → `sales-lead-triage`
  - `small-business/skills/lead-triage` → `small-business-lead-triage`
  同一插件里其他技能正文对这些旧名的裸名引用（`route to lead-triage` 之类）也一并换成
  新 id，否则 agent 照正文去加载会找不到；本次改写了 34 个文件：
  - `data-statistical-analysis/SKILL.md`
  - `marketing-competitive-brief/SKILL.md`
  - `product-management-competitive-brief/SKILL.md`
  - `inbox-sweep/SKILL.md`
  - `sales-lead-triage/SKILL.md`
  - `route-lead/SKILL.md`
  - `ad-manager/shared/voice-profile.md`
  - `ap-processor/shared/voice-profile.md`
  - `brand-style/smb-onboard/reference/onboard-checklist.md`
  - `build-agent/shared/voice-profile.md`
  - `call-list/SKILL.md`
  - `crm-autopilot/shared/voice-profile.md`
  - `grant-rfp-writer/shared/voice-profile.md`
  - `hiring-screener/shared/voice-profile.md`
  - `inbox-manager/shared/voice-profile.md`
  - `inventory-planner/shared/voice-profile.md`
  - `invoice-chase/shared/voice-profile.md`
  - `small-business-lead-triage/reference/gotchas.md`
  - `small-business-lead-triage/reference/hubspot-scoring.md`
  - `small-business-lead-triage/shared/voice-profile.md`
  - `small-business-lead-triage/SKILL.md`
  - `marketing-monday/SKILL.md`
  - `outreach-composer/shared/voice-profile.md`
  - `proposal-builder/shared/voice-profile.md`
  - `review-reputation/shared/voice-profile.md`
  - `seo-ai-visibility/shared/voice-profile.md`
  - `smb-onboard/reference/onboard-checklist.md`
  - `smb-onboard/SKILL.md`
  - `smb-router/reference/connector-map.md`
  - `smb-router/SKILL.md`
  - `social-content-engine/shared/voice-profile.md`
  - `speed-to-lead/shared/voice-profile.md`
  - `speed-to-lead/SKILL.md`
  - `ticket-deflector/shared/voice-profile.md`
- **链接改写**：技能正文里指向插件根目录的相对链接（`../../CONNECTORS.md`、small-business
  的 `../../shared/*.md`）改为指向技能目录内的副本，副本一并拷入（`CONNECTORS.md`、
  `shared/`）；指向同插件其他技能参考资料的链接（`../<技能>/reference/*.md`）同样拷入
  本技能目录的 `<技能>/` 子目录并改写；productivity/start 引用的
  `${CLAUDE_PLUGIN_ROOT}/skills/dashboard.html` 拷为技能目录内的 `dashboard.html`。
- **未改动**：`$ARGUMENTS`、`~~连接器占位符`、`allowed-tools`、`argument-hint`、
  `user-invocable`、`triggers` 等 Claude Code / Cowork 约定原样保留——openworker 只读
  `name` / `description` / `source`，忽略其余字段。目标文件在上游就不存在、无法拷入的
  链接（0 处）原样保留：
  - （无）

### 未打包的 knowledge-work-plugins 内容

- `bio-research`：生命科学研发工具链（基因组、单细胞、Nextflow），与生产制造业管理无关，与科学技能库的裁剪口径一致
- `cowork-plugin-management`：只在 Claude Cowork 里生成/定制插件，openworker 没有对应运行时
- `pdf-viewer`：依赖 Cowork 自带的 PDF 查看器界面（打开/批注/签名命令），openworker 无法执行
- `partner-built/` 下的合作方插件（作者不是 Anthropic）一律不打包。
- 各插件的 `.mcp.json`、`commands/`、`README.md`、`CONNECTORS.md` 本身不单独打包
  （`CONNECTORS.md` 只作为技能目录内的副本随技能走）。

### 科学技能库的保留清单

scientific-agent-skills 共 163 个技能，只保留与生产制造业管理相关的 32 个，
并按用途重新分类（清单在 `packaging/gen_library.py` 的 `SCIENTIFIC_KEEP`，增删改表即可）：

| 技能 | 分类 | 保留理由 |
|---|---|---|
| `docx` | 办公文档 | Word 文档的读写、排版与批注 |
| `xlsx` | 办公文档 | Excel 表格的读写、公式与格式 |
| `pptx` | 办公文档 | PowerPoint 演示文稿制作与读取 |
| `pdf` | 办公文档 | PDF 读取、合并、拆分、填表、OCR |
| `markitdown` | 办公文档 | 各类文档批量转 Markdown |
| `liteparse` | 办公文档 | 本地解析 PDF/Office/图片里的文字和表格 |
| `markdown-mermaid-writing` | 办公文档 | Markdown 报告与 Mermaid 流程图写作 |
| `exploratory-data-analysis` | 数据分析与预测 | CSV/JSON 数据的探索性分析 |
| `statistical-analysis` | 数据分析与预测 | 组间比较、假设检验、效应量 |
| `statistical-power` | 数据分析与预测 | 样本量与检验功效计算 |
| `scikit-learn` | 数据分析与预测 | 通用机器学习（分类、回归、聚类） |
| `statsmodels` | 数据分析与预测 | 回归、GLM、ARIMA 等统计模型 |
| `polars` | 数据分析与预测 | 高性能表格数据处理与 ETL |
| `matplotlib` | 数据分析与预测 | 基础绘图 |
| `seaborn` | 数据分析与预测 | 统计图表 |
| `scientific-visualization` | 数据分析与预测 | 可直接出版的图表设计与审校 |
| `shap` | 数据分析与预测 | 模型解释（特征归因） |
| `aeon` | 数据分析与预测 | 时间序列分类与异常检测（传感器、设备数据） |
| `timesfm-forecasting` | 数据分析与预测 | 零样本时间序列预测（需求、能耗、销量） |
| `scikit-survival` | 数据分析与预测 | 失效时间/生存分析（设备可靠性） |
| `experimental-design` | 工程与质量 | 试验设计（DOE）与随机化方案 |
| `simpy` | 工程与质量 | 离散事件仿真（产线、排队、库存） |
| `pymoo` | 工程与质量 | 多目标优化（排产、参数、结构设计） |
| `uncertainty-and-units` | 工程与质量 | 物理单位换算与测量不确定度（GUM） |
| `lab-hardware-cad` | 工程与质量 | 参数化 CAD 建模并导出 STEP/STL/DXF |
| `analytical-method-validation` | 工程与质量 | 检测方法验证（ICH/USP/ISO 17025） |
| `iso-standards-readiness` | 工程与质量 | ISO 13485/14971/17025 等体系就绪度评估 |
| `what-if-oracle` | 研究与决策 | 多分支「假设情景」推演 |
| `market-research-reports` | 研究与决策 | 市场研究与市场规模测算报告 |
| `literature-review` | 研究与决策 | 系统性文献综述 |
| `paper-lookup` | 研究与决策 | 多源学术文献检索（研发立项、先行技术） |
| `citation-management` | 研究与决策 | 参考文献管理与引用校验 |

本 fork 新增的内容：生成/维护脚本（`packaging/gen_library.py`）、本说明文件、`LICENSES/`
目录，以及技能的中文译文层（各技能目录下的 `SKILL.zh.md` 与 index.json 中的
`description_zh` 字段，由本 fork 翻译生成，仅用于库内浏览展示；安装进全局技能目录的始终
是上游英文原件加上述来源标记）。

## 生成信息

- 生成时间（UTC）：`2026-10-06T07:01:25Z`
- 生成脚本：`packaging/gen_library.py`
