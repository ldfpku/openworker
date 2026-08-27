# 学术评价

## 目的

对**学术成果**（scholarly work）提供具有发展性、可追溯证据的反馈：论文、
草稿、方案、文献综述，或研究构想。优先使用定性判断。可选的评分
仅描述所提交的证据与预先声明的有界评分标准之间的映射关系。

本技能还审计一项低风险评估流程是否记录了其构念、来源、评分者质量、
不确定性、可追溯性、敏感性、公平性、无障碍性、隐私，以及人工治理。

## 硬性安全边界

切勿使用本技能来自动化、推荐、实质性影响或评分以下事项：

- 招聘、晋升或终身教职；
- 招生；
- 资助或其他形式的经费；
- 奖项、荣誉或奖励；
- 处分、解聘或制裁；或
- 任何其他具有重大影响的人事决定。

切勿对人进行排名。切勿将一个人简化为一个综合分数。切勿推断能力、
品格、诚信、受保护特征、未来表现或价值。名义上的人工介入并不能
解除这一边界限制。

如果被要求用于被禁止的用途，应当停止。可以就学术成果提供发展性
意见，或者进行不处理申请材料、不比较人员、不推荐结果、也不建议
决定的纯流程审计。

不得作出可发表性、录用/拒绝，或"顶级"之类的判断。

在任何组织层面的使用之前，请阅读 `references/responsible_assessment.md`。

## ScholarEval 状态

本文引用的 ScholarEval 项目是一个**实验性的、基于文献的研究构想评估
框架**，并非经过验证的心理测量学方法。

已核实的主要记录是 Moussa et al., *ScholarEval: Research Idea
Evaluation Grounded in Literature*, arXiv:2510.16234v2，修订于 2026-02-28。
该文献报告了一个检索增强的合理性/贡献度评估框架、一个涵盖四个学科、
包含 117 个研究构想的数据集、覆盖率实验，以及一项用户研究。

不要将这些结果推广到人员评估、重大决策、所有学科，或本技能的评分
标准之上。在本次注明日期的评审过程中，未核实其是否具有同行评审
发表状态。参见 `references/source_ledger.md`。

## 指标与声望政策

不得依据以下内容评分或推断质量：

- 期刊影响因子（Journal Impact Factor）或其他期刊指标；
- h 指数、发表数量，或引用次数；
- 替代计量指标（altmetrics）或关注度；
- 期刊、会议、发表平台、机构、雇主，或地域声望；
- 作者所属单位、声誉、人脉，或职业发展路径。

评分标准验证器会拒绝常见的代理指标类标准项。

如果合格的评审人在评分工具之外以描述性方式提及某项指标，应记录
其确切用途、来源、覆盖范围、学科与时间效应、不确定性、缺失情况、
偏差、被操纵风险，以及它为何不能直接衡量质量。切勿将指标隐藏在
不透明的综合分数中。

## 数据边界

随附脚本只接受严格的本地 JSON/CSV 文件，其中只包含假名化 ID、有界
评分、状态、不确定性，以及本地引用。

不得在输入、输出、日志、示例或提示词中放入原始的私密申请材料、
简历、推荐信、评审人身份、联系方式、受保护属性，或源文档正文。
应将源内容保留在受权限管控的记录系统中，并使用不透明的本地引用。

允许使用的分类如下：

- `synthetic`
- `public_scholarly_work`
- `deidentified_low_stakes`

没有任何脚本会搜索网络、加载环境文件、读取凭据、调用模型、执行
传入的文本、反序列化可执行对象，或启动进程。

仅可使用 Bash 来调用文档中说明的本地 `python3` 命令。

## 工作流程

### 1. 确认允许的用途与授权

记录以下内容：

- 发展性目的；
- 评估单元：`scholarly_work`；
- 成果类型、阶段、学科、语言，以及受众；
- 已获授权的来源位置与数据分类；
- 负责问责的委员会所有者；
- 利益冲突与回避；
- 无障碍与合理便利流程；
- 申诉或更正途径；以及
- 数据用途、访问权限、留存期限，以及删除方式。

如遇被禁止的决策场景，或不必要的私密数据，应停止。

### 2. 先界定构念，再制定标准项

说明以下内容：

- 所考察的是何种质量或支持；
- 被排除在外的构念；
- 预期的解读方式；
- 该解读不适用的情境；
- 证据要求；以及
- 已知的局限性。

应从价值观与学科背景出发，而非从现有可得的指标出发。

### 3. 调整并验证评分标准

从 `assets/rubric_template.json` 开始，然后获取具备资质的学科专家、
评估方法专家、利益相关方、无障碍专家、隐私专家，以及公平性方面的
评审意见。

该模板刻意将内容效度记录为 `not_established`。未经针对确切预期
用途的书面证据支持，不得更改该状态。

验证结构：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_rubric.py \
  --rubric assets/rubric_template.json
```

关于构念、锚点、效度，以及评分者指引，请阅读
`references/evaluation_framework.md`。

### 4. 建立可追溯的证据记录

评审人可以在脚本之外阅读已获授权的成果。仅在
`assets/evidence_manifest_template.json` 中记录稳定的本地定位符与
引用出处。

对每个标准项，都应区分：

- 观察到的证据与解读之间的区别；
- 支持性证据与相反证据之间的区别；
- 可获得的证据与不可获得的证据之间的区别；
- `missing` 与 `not_applicable` 之间的区别；以及
- 不确定性与证据缺失之间的区别。

未能找到已有研究，并不能证明新颖性。

### 5. 独立评分

使用 `assets/evaluation_template.json`。每个标准项必须处于以下状态
之一：

- `rated`（已评分）：附带锚点分数、有界不确定性、证据 ID，以及本地
  依据引用；
- `missing`（缺失）：分数/不确定性为空，并附带依据引用；或
- `not_applicable`（不适用）：分数/不确定性为空，并附带依据引用。

不得将缺失或不适用编码为零分。评分者应接受培训、进行校准、披露
利益冲突、独立评分，并记录分歧。

### 6. 运行本地质量检查

有界评分，不含标签或建议：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/calculate_scores.py \
  --rubric assets/rubric_template.json \
  --evaluation assets/evaluation_template.json
```

证据可追溯性：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_traceability.py \
  --rubric assets/rubric_template.json \
  --evaluation assets/evaluation_template.json \
  --evidence assets/evidence_manifest_template.json
```

评分者间一致性：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/summarize_agreement.py \
  --rubric assets/rubric_template.json \
  --ratings assets/ratings_template.csv
```

权重敏感性分析需要两份或以上不同的学术成果评分文件：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/weight_sensitivity.py \
  --rubric assets/rubric_template.json \
  --evaluation /tmp/work-a-evaluation.json \
  --evaluation /tmp/work-b-evaluation.json
```

流程控制：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_process.py \
  --process assets/process_checklist_template.json
```

该检查清单模板刻意保持未确认状态，并采用失败即拒绝的原则。具体
说明与精确模式请见 `references/local_tooling.md`。

### 7. 综合定性结论

以标准项层面的证据为主，而非综合分数。对每个标准项：

1. 引用证据出处；
2. 说明其状态为 `rated`、`missing`，或 `not_applicable`；
3. 解释锚点的含义；
4. 仅在已评分时才报告分数与不确定性；
5. 记录分歧与相关背景；
6. 指出优势与局限；以及
7. 提供非指令性的改进建议选项。

如有需要，可生成一个空引用的脚手架：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/generate_report_scaffold.py \
  --rubric assets/rubric_template.json \
  --evaluation assets/evaluation_template.json \
  --output /tmp/developmental-report-scaffold.json
```

该脚手架不会读取源文档，也不会起草结论。

### 8. 人工评审与发布

在发布面向组织的报告之前，一个具备资质、承担问责的人工委员会必须
核实：

- 构念与评分标准的来源；
- 内容效度证据及其局限；
- 评分者培训、一致性、评分者间信度证据，以及漂移情况；
- 证据可追溯性与来源可访问性；
- 缺失情况、不适用理由，以及不确定性；
- 权重敏感性与顺序不稳定性；
- 学科与子群体偏差评审；
- 利益冲突与回避；
- 无障碍与合理便利；
- 隐私、数据最小化、留存，以及输出管控；以及
- 更正或申诉信息。

应记录不同意见。不得暗示超出证据支持范围的共识、效度或精确度。
应定期评估该评估流程本身，并淘汰有害的标准项。

## 解读规则

- 分数是一种顺序型评分标准汇总结果，而非自然测量值。
- 归一化并不能弥补不完整的证据。
- 附带的不确定性区间并非置信区间。
- 一致性并不能确立信度、效度、公平性，或正确性。
- 在测试过的权重下结果保持稳定，并不能确立效度。
- 总体分数绝不能凌驾于标准项证据或合格判断之上。
- 任何输出都不是决策建议。

## 随附资源

- `references/responsible_assessment.md` —— 安全性、指标、治理、
  无障碍、隐私，以及偏差。
- `references/evaluation_framework.md` —— ScholarEval 的边界、构念、
  标准项、锚点、效度，以及解读方式。
- `references/local_tooling.md` —— 严格的模式、计算公式、命令，
  以及输出行为。
- `references/source_ledger.md` —— 权威来源，以及注明日期为
  2026-07-23 的发表状态核实记录。
- `references/security_validation.md` —— 基线修复、验证，以及残留
  安全扫描记录。
- `assets/rubric_template.json` —— 有界评分标准模板。
- `assets/evaluation_template.json` —— 评分模板。
- `assets/evidence_manifest_template.json` —— 可追溯性模板。
- `assets/process_checklist_template.json` —— 失败即拒绝的流程检查
  清单。
- `assets/ratings_template.csv` —— 用于一致性分析的合成数据。
