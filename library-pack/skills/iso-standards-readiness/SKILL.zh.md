# ISO 标准就绪度证据准备（ISO Standards Readiness Evidence Preparation）

## 目的

使用本技能来组织针对某一指定标准、供正式人工审查使用的声明范围、受控文件、实施记录、可追溯性以及就绪度证据。它对流程工作流进行归纳总结，并提供确定性的本地检查。它不包含条款正文，也不执行审核。

这是一个路由器（router）。`SKILL.md` 承载边界、赛道纪律（lane discipline）、共享工作流和 CLI 契约。各标准专属的深入内容存放在 `references/` 中。

## 不可逾越的边界

本技能不能：

- 对任何事物进行认证或认可（certify or accredit），签发或验证证书、认可范围（accreditation schedule）或许可证，或承诺审核、评估或检查的结果；
- 确定法律/法规适用性、器械分类、可报告性、符合性路径、产品授权、市场准入、执业许可、人员资质或合规性；
- 取代授权管理层、管理者代表、实验室主任、质量经理、授权签字人、RA/QA（法规事务/质量保证）、法律顾问、法规/主管机关、公告机构（notified body）、MDSAP 审核机构（Auditing Organization）、认可机构、评审员，或认证机构；
- 验证某一方法、计算或批准测量不确定度、建立计量学溯源性、设定风险可接受性标准，或判断某项风险、决策规则或参考区间是否适用；或
- 从模板、检查清单、文件名、关键词、文件数量、百分比或脚本运行结果中推断实施情况、能力、符合性、合规性或就绪度。

始终将输出标注为**供授权人员审查使用的证据准备草案材料**。将未解决的决策保留为阻塞项（blocker），而不是自行解决。

## ISO 与 IEC 版权

ISO 与 IEC 标准均受版权保护。请从 [ISO](https://www.iso.org/standards.html)、IEC、ISO 国家成员机构或其他授权渠道获取每一份标准。不得检索、粘贴、复制或生成条款正文。请对组织自身的流程进行总结说明，并引用受控的授权副本。参见 [ISO copyright](https://www.iso.org/copyright.html)。引用具体要求内容的认可机构、CAP 及各类体系检查清单是单独授权的——同样不得纳入共享代码仓库或提示词中。

## 涵盖的标准

在准备证据**之前**，请先阅读对应标准的参考文件。每份标准都有其自身当前有效版本、所属赛道（lane）、领域术语和常见失效模式。

| 标准 | Profile 键 | 赛道 | 参考文件 |
| --- | --- | --- | --- |
| ISO 13485 医疗器械 QMS | `iso-13485` | 认证（Certification） | `references/iso-13485.md` |
| ISO 14971 器械风险管理 | `iso-14971` | 无独立赛道 | `references/iso-14971.md` |
| ISO/IEC 17025 检测和校准实验室 | `iso-17025` | 认可（Accreditation） | `references/iso-17025.md` |
| ISO 15189 医学实验室 | `iso-15189` | 认可（Accreditation） | `references/iso-15189.md` |

不在此表中的标准超出内置检查的范围。不要将某个 profile 挪用于其未命名的标准——借用另一标准的领域术语会生成一份看似完整、实则毫无意义的报告。

## 当前基线（在做出任何时效性陈述之前，先阅读记录台账）

- **ISO 13485:2016** 第 3 版，已在其 2025 年系统性复审后确认有效。**EN ISO 13485:2016/A11:2021** 是一项欧洲修正案，并非 ISO 国际层面的"Amendment 1:2021"。
- **ISO 14971:2019** 第 3 版，已于 2025 年确认，其配套的信息性指导文件为 **ISO/TR 24971:2020**。ISO 14971 不存在所谓的证书。
- **ISO/IEC 17025:2017** 第 3 版仍为现行版本；尚未发现后续新版本。
- **ISO 15189:2022** 第 4 版取代了 2012 版，吸收了原本属于 ISO 22870 的 POCT（即时检验）相关要求，其认可过渡期已于 **2025 年 12 月**结束——已经落地实施，而非即将到来。
- **FDA QMSR** 自 **2026-02-02** 起生效并被执行；Part 820 的标题为 *Quality Management System Regulation*（质量管理体系法规）；QSIT 已退役，由合规计划（Compliance Program）**7382.850** 取而代之。
- **MDSAP** 当前的审核方法（Audit Approach）为 **MDSAP AU P0002.010**，版本日期为 **2026-02-02**。
- **认可资质互认（Accreditation recognition）**： Global Accreditation Cooperation Incorporated 已于 **2026-01-01** 开始全面运作，取代了 ILAC 与 IAF，并拥有其自己的 MRA（多边互认协议）；原有的 IAF MLA / ILAC MRA 输出结果在过渡期内继续保持被认可状态。
- **欧盟**： 使用现行的 MDR/IVDR 合并文本、现行的 OJEU（欧盟公报）协调标准决定、现行的 MDCG 指南，以及针对具体产品的符合性评定路径。

在做出任何时效性陈述之前，请阅读 `references/source-ledger.md`。其中记录了来源的局限性，包括哪些条目仍需对照 ISO 目录进行确认。

## 保持各保证赛道（assurance lanes）彼此分离

导致此处大多数实质性错误的原因是赛道混淆，而非文件缺失。认证、认可、监管机构检查、强制性执业许可、监管审核计划以及产品符合性评定，是由不同机构依据不同基础做出的决定，彼此之间不可互相替代。以下两条规则经常被违反：

- 组织机构接受的是**认证（certified）**；实验室接受的是**认可（accredited）**。"ISO 17025 certified" 和 "ISO 15189 certified" 都是概念性错误。
- 证书永远不能取代监管机构。ISO 13485 认证并不能豁免任何人接受 FDA 检查，ISO 15189 认可也不能满足 CLIA 的要求。

关于完整的赛道对照表、范围声明的限制以及命名规则，请阅读 `references/assurance-lanes.md`。

## 核心工作流

### 第一步：声明标准、目的及授权责任人

明确标准名称、本次工作所支持的赛道，以及各责任人：管理者代表或实验室主任、质量责任人、法律/适用性责任人、流程或技术责任人、批准人及升级路径。赛道是一项声明性输入，绝不是推断得出的。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_scope_intake.py \
  assets/templates/scope-intake-template.json --standard iso-13485
```

使用匹配的模板与 profile：

| Profile | 模板 |
| --- | --- |
| `iso-13485`、`iso-14971` | `assets/templates/scope-intake-template.json` |
| `iso-17025` | `assets/templates/laboratory-scope-intake-template.json` |
| `iso-15189` | `assets/templates/medical-laboratory-scope-intake-template.json` |

`--standard` 默认值为 `iso-13485`。每一个分发的模板都被有意设计为默认失败（fail closed）；请将其复制到技能之外，并用受控的组织证据加以填写。适用性未确定时会触发 `HUMAN_DECISION_REQUIRED`——请将其保留为一个阻塞项。

### 第二步：冻结来源/版本证据

对于每一份标准、法规、指南、体系文件、审核模型和产品来源，都需记录出版方、官方标题、版本/版次/日期、授权存放位置、访问及时效复核日期、范围/适用性责任人、影响评估、状态、证据以及批准情况。

不得将搜索得到的片段用作受控要求。不得在出版方发布新版本时静默更新已被采纳的版本——FDA 采纳的是某一特定版本的 ISO 13485，之后 ISO 或 EN 发布的新版本并不会改变这一点。

### 第三步：清点受控文件与记录

不要仅仅统计已命名的程序文件数量或扫描关键词。要建立一份明确的登记表，将文件、记录、来源版本、责任人、批准情况、生效日期、留存依据、培训及变更记录一一关联起来。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit_document_records.py \
  assets/templates/document-register-template.json
```

此项检查与具体标准无关（standard-agnostic）。证据架构请阅读 `references/evidence-architecture.md`。

### 第四步：审查流程实施情况

针对你所用 profile 声明的各个领域（各标准专属参考文件中会列出这些领域），评估受控程序文件**以及抽样记录**。每一项都需要有责任人、状态、证据编号、来源/版本、批准情况以及未结事项（open-gap）链接。

一份描述某项活动的程序文件，并不能作为该活动确实已经发生的证据。请在你所报告的每一个领域内都抽取记录样本，并说明你抽取了哪些样本、未抽取哪些样本。

### 第五步：运行适用于该赛道的针对性检查

器械类赛道（`iso-13485`、`iso-14971`）——风险/设计/生产/上市后链条：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_traceability.py \
  assets/templates/traceability-matrix-template.json
```

所有标准通用——纠正措施及有效性：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_capa.py \
  assets/templates/capa-record-template.json
```

所有标准通用——供应商及外部提供的产品和服务，包括校准服务提供方、标准物质供应商，以及转诊或分包检测的实验室：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_supplier_controls.py \
  assets/templates/supplier-controls-template.json
```

待处理或尚未证实有效的 CAPA 有效性证据会阻止该事项结案。关键供应商控制措施在基于风险的控制及批准得到证实之前，将持续处于阻塞状态。

请注意，`check_traceability.py` 涉及的是设计与风险的可追溯性，**并非**计量学意义上的溯源性——这两个词语容易混淆，用它来处理实验室工作是用错了工具。

### 第六步：单独处理赛道专属的监管证据

仅针对美国器械赛道：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_qmsr_transition.py \
  assets/templates/qmsr-transition-template.json
```

审查当前 Part 820/FDA 依据来源、补充条款、过时的 QSR/QSIT 引用、生效日期之前的记录、可供检查机构调阅的管理/质量/供应商审核记录、当前的检查流程培训、投诉及维修服务记录、标签/包装控制措施、供应商/软件/变更证据，以及被禁止的证书等同性声明（certificate-equivalence claims）。不要把旧版 820 到 ISO 条款的映射当作当前的控制框架来构建。

实验室类赛道目前没有对应的内置检查。CLIA、执业许可及国家层面的检查证据仍由授权的合规责任人负责，参见 `references/iso-15189.md`。

### 第七步：组装一份边界明确的就绪度证据清单（manifest）

将证据模板复制到技能之外。仅使用指向本地 `.json`、`.md` 或 `.markdown` 证据文件的相对路径，并且每份清单只声明一个赛道用途。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_evidence_manifest.py \
  /path/to/evidence-manifest.json \
  --standard iso-17025 \
  --base-dir /path/to/controlled-export \
  --verify-files \
  --output /path/to/manifest-report.json
```

然后针对同一 profile 生成一份领域层面的差距（gap）视图：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/gap_analyzer.py \
  /path/to/evidence-manifest.json \
  --standard iso-17025 \
  --base-dir /path/to/controlled-export \
  --verify-files \
  --output /path/to/gap-report.json
```

该分析器使用的是明确的清单标签。它不会从文件名、关键词或专有标准文本中推断证据，也不会计算合规评分。`expected_domains` 中未列出的领域会被报告为 `not-assessed`（未评估），这**并非**表示"不适用"的判定。

关于默认失败（fail-closed）的证据审查问题清单，请阅读 `references/gap-analysis-checklist.md`。

### 第八步：人工审查与受控交接

呈现以下内容：

- 已声明的标准、范围、保证赛道，以及尚未解决的适用性决策；
- 确切的来源/版本基线；
- 已抽样的证据及该样本的局限性；
- 按流程与风险分类整理的结构性发现；
- 各项行动、变更及 CAPA 的责任人与日期；
- 批准状态；以及
- 负责下一步决策的授权责任方。

切勿将结果命名为"证书"（certificate）、"认可"（accreditation）、"合规报告"（compliance report）、"审核通过"（audit pass）、"视同符合"（deemed status）或"已备妥接受检查"（ready for inspection）。恰当的标题应为**供授权人员评估使用的草案证据审查**（Draft evidence review for authorized human assessment），并注明其所准备针对的赛道。

## CLI 行为与安全性

所有内置 CLI：

- 仅使用 Python 标准库；
- 不执行任何网络请求；
- 接受有边界限制的本地 JSON 输入；可选的证据验证仅接受有边界限制的本地 JSON/Markdown；
- 拒绝符号链接输入、重复的 JSON 键、非有限数值、超出限制的体积/嵌套深度/条目数量，以及不安全的证据路径；
- 拒绝未在列表中的 `--standard` 值，而不是回退使用默认值；
- 不使用动态求值、可执行反序列化、pickle 或 shell 执行；
- 除非明确指定 `--force`，否则拒绝覆盖已有报告；以及
- 生成确定性的、经过排序的 JSON 输出。

请将证据清单本身视为一份受控的组织记录。可选的 SHA-256 比对仅用于检测本地文件是否存在不一致，并不能确立用户提供的清单的来源、真实性、充分性或可信度。JSON 中 `local_path` 与 `evidence.location` 字段的值指向的是用户自己受控的导出内容，而非技能内置的资源；未解析的占位符绝不能被打开使用。

退出代码：

- `0`：所提供字段未发现结构性问题；**这并非合规、符合性、能力或认可方面的结论**；
- `1`：发现结构性/证据方面的差距；
- `2`：输入/输出无效或不安全，包括使用了未列出的标准。

针对每个接口，运行 `python3 scripts/<name>.py --help` 查看说明。

## 模板

范围采集（scope intake），按 profile 划分：

- `assets/templates/scope-intake-template.json` —— 器械生命周期
- `assets/templates/laboratory-scope-intake-template.json` —— 检测/校准
- `assets/templates/medical-laboratory-scope-intake-template.json` —— 检验（examinations）

共享的登记表与记录：

- `assets/templates/document-register-template.json`
- `assets/templates/capa-record-template.json`
- `assets/templates/traceability-matrix-template.json`
- `assets/templates/supplier-controls-template.json`
- `assets/templates/evidence-manifest-template.json`
- `assets/templates/qmsr-transition-template.json` —— 仅限美国器械赛道

管理体系文档：

- `assets/templates/quality-manual-template.md`
- `assets/templates/procedures/CAPA-procedure-template.md`
- `assets/templates/procedures/document-control-procedure-template.md`

每份模板都被有意设计为 `draft`/`pending`（草案/待定）状态，使用占位符，并包含责任人/状态/证据/批准等字段。请复制并对其进行受控管理；切勿将分发的模板直接编辑成一份所谓已批准的记录。

## 参考资料

共享内容：

- `references/assurance-lanes.md` —— 各赛道分别决定什么、以及命名规则
- `references/source-ledger.md` —— 带日期的权威来源基线及来源局限性
- `references/evidence-architecture.md` —— 文档与记录架构
- `references/gap-analysis-checklist.md` —— 默认失败的证据审查问题清单
- `references/quality-manual-guide.md` —— 受控手册的编制

按标准划分：

- `references/iso-13485.md` —— 器械 QMS 流程/证据框架、QMSR、MDSAP、欧盟
- `references/iso-14971.md` —— 风险管理链条及缺失环节的失效模式
- `references/iso-17025.md` —— 实验室能力、溯源性、不确定度及决策规则
- `references/iso-15189.md` —— 医学实验室、POCT、报告，以及 CLIA 赛道
