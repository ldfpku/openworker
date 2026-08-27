# Clinical Reports(临床报告)

## 目的

从经过核实的、被授权使用的事实出发，准备**草稿性报告结构**、汇总表格，以及
评审清单(review manifest)。把每一份产出物路由到正确的报告规范，保留可溯源
信息，并在来源支持不足或缺少合格评审时停止。

本技能不构成法律、监管、伦理、期刊、认证或机构层面的合规认定。其脚本仅检查
结构和内部一致性。

## 不可协商的边界

绝不可以:

- 做出诊断、给出治疗建议、选择或更改剂量、分诊(triage),或提供复诊注意事项;
- 解读影像、标本、原始实验室结果、症状或其他临床观察结果;
- 编造、推断、归一化、"补全",或悄悄地调和(reconcile)观察结果、检验结果、
  日期、单位、分母、因果关系、可预期性、严重程度、结局或结论;
- 从患者层面的叙述性文本中创建个体病例安全报告，或决定其是否需要上报;
- 签署、证明、批准、归档、传送、提交、修改一份源记录，或代行执业临床医生、
  病理科医生、放射科医生、检验人员、安全医师、统计学家、隐私官、律师或监管
  专业人员的职能;
- 在示例、资源文件、测试、提示词、日志或外部服务中使用真实的受保护健康信息
  (PHI);
- 调用外部 LLM、图像服务、API,或另一个技能。

所有生成的产出物必须始终保留以下明显标记:

> DRAFT — NOT FOR CLINICAL USE, SIGNATURE, FILING, OR SUBMISSION. Populate only from verified authorized source records. Qualified review and sign-off are required.
>
> (草稿——不得用于临床用途、签署、归档或提交。只能使用经核实、获授权的源记录来填充。必须经过合格评审并签字确认。)

如果请求触碰了边界，应停止其中不安全的部分。可以提供一份空白的结构化模板、
一份源事实清单(source-fact manifest),或一次确定性的结构检查。涉及直接的
临床或监管决策，应交由负责的合格专业人员处理。

## 输入门槛

只有在以下全部条件都成立时才可以继续:

1. **目的明确**:出版用草稿、诊断报告框架、试验结果手稿、方案报告评审、
   CSR 草稿、汇总安全性表格，或汇总性研究摘要。
2. **数据类别属于允许范围**:`synthetic`(合成)、`deidentified`(去标识)
   或 `aggregate`(汇总)。
3. **权限已有据可查**:请求方被授权为所述目的使用这些记录。
4. **本地化处理是可行的**:不需要上传、远程 API、遥测或凭证。
5. **最小必要原则已明确界定**:排除产出物不需要的字段。
6. **可溯源性存在**:每一个已填充的字段或声明，都对应到一个或多个经核实的
   源事实(source-fact)ID。
7. **评审责任人已确定**:视情况需要合格的临床、统计、安全性、隐私、法律、
   期刊和/或监管评审。

当可以提供结构化的源事实清单时，不要接受原始的患者自由文本记录。不要把直接
标识符复制进本技能的模板或脚本中。

## 起草前先路由

| 产出物 | 主要依据 | 重要边界 |
|---|---|---|
| 用于发表的病例报告 | CARE 2013 核对清单及 2017 版说明 | 出版同意书、隐私、期刊政策和临床准确性都需要人工核实 |
| 放射科草稿框架 | ACR 2025 沟通实践参数，加上按模态划分的 ACR 相关资料 | 由合格的放射科医生撰写"所见/印象",并处理非常规沟通事项 |
| 病理科草稿框架 | 适用时，采用当前特定标本类型的 CAP Cancer Protocol | 由合格的病理科医生选择相应的方案/版本并撰写诊断 |
| 实验室草稿框架 | 42 CFR 493.1291 及实验室政策 | 由执行检测的实验室掌控结果、参考区间、更正和发放 |
| 随机对照试验结果报告 | CONSORT 2025,加上每一项适用的现行扩展条款 | CONSORT 是报告规范，不是实施或提交标准 |
| 随机对照试验方案报告 | SPIRIT 2025 及适用的扩展条款 | SPIRIT 针对的是方案，不是结果或 CSR |
| 临床研究报告(Clinical Study Report) | ICH E3 及 E3 问答文件；可参考 ICH E6(R3) 及地区性要求 | E3 是可灵活调整的指南，不是僵化的通用模板 |
| 上市前安全性报告 | ICH E2A;电子 ICSR 数据用 E2B(R3);及适用的地区法律/指南 | 上报与否及时限由合格的申办方/研究者安全性评估掌控 |
| 上市后个体安全性报告 | ICH E2D(R1)、E2B(R3),及地区性要求 | 不得自动化病例评估、编码或提交 |
| 汇总安全性报告 | 方案/统计分析计划(SAP)、ICH E3、CONSORT Harms,及适用的 FDA/ICH 指南 | 汇总表格从不用于判定个体病例是否需要上报 |
| 汇总研究摘要 | 特定研究设计的报告规范及原始方案/SAP | 严格按已核实的内容陈述人群、估计目标(estimand)、分母、缺失情况和局限性 |

在选择路径之前先阅读 `references/report_type_routing.md`。使用
`references/sources.md` 中带日期的权威来源清单；当要求可能已经变化时，应
核对官方来源的最新版本。

## 安全起草工作流程

### 1. 创建源事实清单(source-fact manifest)

使用 `assets/provenance_manifest_template.json`。只记录本地记录定位符、
字段路径、核实状态、核实人角色、核实日期，以及一个 SHA-256 值哈希。不要
复制源内容或直接标识符。

每一条草稿声明或已填充字段，都必须引用一个或多个事实 ID。没有支持依据的
内容应保持为 `null` 或 `missing`;绝不能用看似合理的文字去替代它。

### 2. 生成正确的模板

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/generate_report_template.py --list
PYTHONDONTWRITEBYTECODE=1 python3 scripts/generate_report_template.py \
  --type case-report \
  --output ./case-report-draft.json
```

生成器复制的是一个默认失败关闭(fail-closed)的 JSON 模板。它不会填充临床
内容、创建目录、默认覆盖已有文件，也不会认证任何内容"已准备就绪"。

### 3. 只填充经核实的字段

- 保持 `draft_status` 不变。
- 只有在有经核实的事实 ID 支持时，才把 `null` 替换掉。
- 精确保留不确定性和"尚未评估(not assessed)"的记录方式。
- 不要把一条原始观察结果转译成诊断、编码、分级、分期、严重程度、因果关系、
  可预期性，或建议。
- 只有在合格评审人提供了理由时，才使用 `not_applicable_with_rationale`。
- 让源记录与草稿保持相互独立。

### 4. 运行确定性检查

CARE 结构检查:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_case_report.py \
  ./case-report-draft.json
```

ICH E3、CONSORT 2025 或 SPIRIT 2025 结构检查:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_trial_report.py \
  ./trial-report-manifest.json
```

汇总不良事件表格:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/format_adverse_events.py \
  ./aggregate-ae.csv --metadata ./safety-aggregate.json \
  --output ./aggregate-ae-table.md
```

术语学模式(terminology schema)检查:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/terminology_validator.py \
  ./terminology-manifest.json
```

去标识化流程文档检查:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_deidentification.py \
  ./deidentification-process.json
```

可溯源性与一致性检查:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/provenance_validator.py ./provenance.json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/consistency_checker.py ./consistency.json
```

这些工具只使用 Python 标准库和本地的有边界文件，不涉及网络访问、动态求值、
序列化代码执行，也不做患者记录提取。即便检查全部通过，依然要说明仍需人工
评审。

### 5. 应用恰当的评审

至少要满足:

- 临床事实和解读:由该专科的合格临床医生评审;
- 统计结果、人群、估计目标(estimand)、分母和缺失情况:由合格的统计学家
  评审;
- 安全性编码、严重程度、因果关系、可预期性和是否需要上报:由合格的安全性
  专业人员评审;
- HIPAA、知情同意、授权和信息披露:由隐私/法律/机构评审;
- CSR 或监管性安全产出物:由申办方的监管与医学评审;
- 出版物:由全体负责的作者以及目标期刊的相关检查完成评审。

绝不能代替他人签字或提交。

## 病例报告

使用 `assets/case_report_template.json` 和
`references/case_report_guidelines.md`。

- CARE 当前的核心核对清单仍然是 2013 版清单。
- 只报告经核实记录所支持的内容。
- 不要把一个病例变成临床建议，也不要从单个病例推广出因果结论。
- 患者视角和知情同意状态必须被准确记录；不要起草虚假的同意声明。
- 去标识化和知情同意是两种独立的控制手段。知情同意并不能消除隐私风险。

## 诊断报告框架

使用放射科、病理科或实验室的 JSON 资源文件，以及
`references/diagnostic_reports_standards.md`。

- 这些资源文件是字段映射表，不是诊断撰写系统。
- 绝不生成"所见"、"印象"、诊断、分级、分期、参考区间、危急值阈值，或
  随访建议。
- 保留初步/最终/更正状态，以及源系统版本信息。
- 针对该标本使用当前、精确的 CAP 方案及版本；不要维持一个通用的癌症分期
  默认值。
- 沟通和更正行为仍归属于负责的临床科室。

此前的 SOAP、病史与体格检查(H&P)、会诊和出院小结接口已被移除。不要重新
创建患者诊疗记录、用药方案、分诊指导、账单支持，或处置建议。

## 试验、CSR 与安全性报告

阅读 `references/clinical_trial_reporting.md` 和
`references/safety_reporting.md`。

- CONSORT 2025 对随机对照试验结果报告规定了 30 项最低条目；应从当前官方
  目录中选取相关的扩展条款。
- SPIRIT 2025 对随机对照试验方案报告规定了 34 项最低条目，并取代
  SPIRIT 2013。
- ICH E3 仍是 CSR 的编写基础；其 2012 版问答文件明确允许有正当理由的调整。
- ICH E6(R3) 整合后的原则、附件 1 和附件 2 已于 2026 年 6 月 16 日通过;
  各地区的落地实施可能有所不同。
- 要区分"严重程度(seriousness)"与"严重度(severity)",以及"不良事件"
  与"可疑不良反应"。
- ICH E2B(R3) 定义的是电子化 ICSR 数据/报文结构；它不是汇总表格式，也不是
  上报与否的判定规则。
- 于 2025 年 9 月 15 日通过的 ICH E2D(R1),针对的是上市后个体病例安全性
  报告；定期汇总报告另有规定。
- FDA 的要求和电子提交渠道因角色、产品、研究和日期而异。本技能绝不进行
  归档或提交。

## 隐私

阅读 `references/privacy_and_deidentification.md`。

- 本地只处理最小必要数据。
- 依据 45 CFR 164.514(b),HHS 认可安全港(Safe Harbor)和专家判定
  (Expert Determination)两种方法。
- 安全港方法还要求不存在"实际知晓剩余信息可用于识别个人身份"的情况。
- 专家判定必须由具备适当资质的专家执行并留档。
- 一次清单核对或模式扫描无法确立去标识化状态或 HIPAA 合规性。
- 罕见病症、小样本单元、日期、自由文本、图像、元数据，以及准标识符的组合,
  仍可能保留重新识别的风险。

## 资源文件(Assets)

所有资源文件都只包含合成的模式(schema),并且默认处于阻塞(blocked)状态:

- `assets/case_report_template.json`
- `assets/radiology_report_template.json`
- `assets/pathology_report_template.json`
- `assets/lab_report_template.json`
- `assets/clinical_trial_csr_template.json`
- `assets/clinical_trial_results_template.json`
- `assets/trial_protocol_reporting_checklist.json`
- `assets/clinical_trial_safety_aggregate_template.json`
- `assets/adverse_event_aggregate_input_template.csv`
- `assets/research_summary_template.json`
- `assets/deidentification_process_checklist.json`
- `assets/quality_review_checklist.json`
- `assets/provenance_manifest_template.json`
- `assets/terminology_manifest_template.json`
- `assets/consistency_manifest_template.json`

## 参考文件

- `references/README.md` —— 安全使用说明与文件索引
- `references/report_type_routing.md` —— 产出物到规范依据的路由对照
- `references/case_report_guidelines.md` —— CARE 结构与出版方面的防护措施
- `references/diagnostic_reports_standards.md` —— ACR、CAP 与 CLIA 边界
- `references/clinical_trial_reporting.md` —— CONSORT 2025、SPIRIT 2025、ICH E3/E6(R3)
- `references/safety_reporting.md` —— ICH E2/FDA 安全性相关的区分要点
- `references/privacy_and_deidentification.md` —— HHS 的方法与局限性
- `references/medical_terminology.md` —— 带版本号的术语学与模式检查
- `references/data_presentation.md` —— 分母、单位、缺失情况与汇总表格
- `references/professional_review.md` —— 伦理、问责与签字确认
- `references/sources.md` —— 官方来源清单，核对于 2026-07-23

## 最终交付说明

要说明:

1. 产出物类型，以及所使用的确切规范/版本;
2. 允许的数据类别，以及是否做到了仅本地处理;
3. 未解决的 `null`、`missing`、冲突，以及缺乏支持的声明;
4. 可溯源性和确定性检查的结果;
5. 需要哪些合格评审人员;
6. 草稿性质/不可提交的警示声明。

绝不能说"合规(compliant)""符合 HIPAA(HIPAA-safe)""已通过临床验证
(validated clinically)""已批准(approved)""可以归档(ready to file)"
或"可以提交(ready to submit)"。
