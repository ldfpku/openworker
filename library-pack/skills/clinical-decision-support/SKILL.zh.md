# 临床决策支持研究与评估

## 硬性安全边界

此技能**仅**用于生成研究、评估、文档和治理相关的制品（artifact）。

绝不可用于：

- 对某个人进行诊断或分类；
- 推荐、选择、排序、启动、停止或修改治疗方案；
- 计算或告知针对特定患者的剂量；
- 分诊、优先级排序、报警、提醒或判定紧急程度；
- 做出或自动化针对特定患者的临床决策；
- 支持床旁、诊疗现场（point-of-care）或实时临床运行；
- 替代专业判断，或替代经过验证并获得授权的临床系统；
- 声称获得 FDA 授权、符合监管要求、符合 HIPAA 合规或符合法律合规。

如果某个请求可能影响对某个人的医疗照护，应停止该工作流，并将该事项转交给持证医疗专业人员，使用经过本地验证且获得适当授权的系统处理。不要为了针对特定患者的照护而转向其他技能。

## 适用范围

- 研究制品的预期用途和局限性声明
- 带披露控制的聚合队列表格骨架
- 统计分析计划及生存分析计划审查
- 聚合模型或生物标志物性能评估
- 透明的 GRADE 证据分级核对表
- 证据来源与决策逻辑的可追溯性
- 去标识化流程核对表
- 公平性、亚组、校准、不确定性、外部验证、监测、变更控制、审计和人因工程文档

在合格人员批准之前，输出始终为草稿状态。报告指南可提升透明度；但它并不确立研究质量、临床实用性、安全性、有效性、授权或合规性。

## 数据关口

在运行任何脚本之前：

1. 确认输入数据是合成的或聚合的。
2. 拒绝患者行、记录、叙述文本、标识符、自由文本、与个人相关的日期、图像、波形或基因组序列。
3. 源文件应保留在本地。不得抓取 URL、调用 API、读取环境变量或将数据发送给模型。
4. 在生成表格之前设定披露阈值。
5. 记录数据来源（provenance）、数据截止日期、人群、排除条件、缺失情况和数据转换过程。

脚本对文件大小、组数、行数和文本长度设有上限。它们会拒绝类似 URL 的路径以及常见的行级密钥。这些控制措施是为了降低误用风险，并不构成隐私合规性判定。

## 必需的制品头部信息

每个制品必须明确包含以下内容：

- `artifact_type`、标题、版本、状态、所有者、日期和变更摘要；
- 预期目的、预期用户、聚合人群范围和决策角色；
- 硬性边界中列出的全部禁止用途；
- 数据级别，以及确认未提供 PHI 或原始行数据的声明；
- 局限性、不确定性和可预见的失败模式；
- 外部验证和亚组适用性状态；
- 人工审查角色、完成状态和批准边界；
- 带版本或日期的来源引用；
- 监测、变更控制、退役和审计的预期要求；
- 声明：**不用于患者照护或实时临床用途**。

请以 `assets/artifact_intended_use_template.json` 为起点。

## 工作流

### 1. 确立研究问题

- 在查看结果之前先定义估计目标（estimand）或评估目标。
- 区分描述性、预后性、预测性、诊断准确性和因果关系问题。
- 预先规定结局指标、时间起点、时间跨度、亚组、切点、缺失数据处理方式、多重性以及敏感性分析。
- 将探索性发现与验证性分析区分开。

### 2. 选择制品

| 需求 | 资产（Asset） | 脚本（Script） |
|---|---|---|
| 预期用途/治理审查 | `assets/artifact_intended_use_template.json` | `scripts/validate_cds_artifact.py` |
| GRADE 证据分级 | `assets/evidence_profile_template.json` | `scripts/evidence_profile_check.py` |
| 聚合模型/生物标志物评估 | `assets/aggregate_model_evaluation_template.json` | `scripts/model_biomarker_evaluation.py` |
| 聚合队列表格 | `assets/aggregate_cohort_table_template.json` | `scripts/cohort_table_generator.py` |
| 生存分析计划 | `assets/survival_analysis_plan_template.json` | `scripts/survival_plan_validator.py` |
| 逻辑可追溯性矩阵 | `assets/decision_logic_traceability_template.json` | `scripts/decision_logic_traceability.py` |
| 去标识化流程审查 | `assets/deidentification_checklist_template.json` | `scripts/deidentification_checklist.py` |

### 3. 本地运行

所有辅助工具均无外部依赖：

```bash
python3 scripts/validate_cds_artifact.py --help
python3 scripts/evidence_profile_check.py --help
python3 scripts/model_biomarker_evaluation.py --help
python3 scripts/cohort_table_generator.py --help
python3 scripts/survival_plan_validator.py --help
python3 scripts/decision_logic_traceability.py --help
python3 scripts/deidentification_checklist.py --help
```

仅将输出写入经过审查的本地目录。切勿将生成的报告放入电子病历（EHR）、报警系统、临床门户或设备工作流中。

### 4. 人工审查

要求进行与制品相匹配的审查：

- 由方法学家/统计学家负责设计和分析；
- 由领域专家负责临床科学背景；
- 由隐私官或合格专家负责披露决定；
- 由监管或法律顾问负责特定司法管辖区的解读；
- 由人因工程专家负责用户研究；
- 由获得授权的治理负责人负责发布和变更控制。

脚本运行成功仅意味着声明的字段和内部一致性检查已通过。

## GRADE 证据分级

不得从文章文本、单纯的研究设计、p 值或关键词中推断出确定性等级。不得将旧式的 `1A/2B` 简写当作通用的 GRADE 输出结果来使用。

对于每一项重要结局指标，人工评审小组必须记录：

- 偏倚风险；
- 不一致性；
- 间接性；
- 不精确性；
- 发表偏倚；
- 任何适用的升级考量因素；
- 效应估计值及其不确定性；
- 每项判断的理由和来源 ID；
- 最终的确定性判断及负责该判断的角色名称。

检查工具仅验证完整性和引用链接。它绝不计算确定性或推荐强度。参见 `references/evidence_profiles.md`。

## 聚合模型与生物标志物评估

不得推导阈值、分配分子或疾病分类、匹配治疗方案，或输出针对个体的预测结果。

评估工具仅接受聚合的混淆矩阵计数和校准分箱（bin）。它会报告带 Wilson 区间的有界描述性指标、校准差距、亚组差异以及明确的抑制（suppression）处理。它不判定公平性、临床实用性或适用性。要求提供：

- 锁定的模型/检测方法/版本，以及预先规定的阈值来源；
- 具有代表性的内部验证以及独立的外部验证；
- 与目标相符的校准度和判别度；
- 带不确定性和样本量的亚组性能；
- 缺失情况、谱系/选择偏倚、数据集漂移和检测方法的变异性；
- 相关情况下的人因工程和前瞻性评估；
- 监测、变更控制、回滚和退役标准。

参见 `references/model_biomarker_evaluation.md`。

## 队列表格

仅使用聚合单元格数据。不得向生成器提供行级数据。

- 在获批的披露政策下选定最小单元格阈值。
- 应用主要抑制和补充抑制措施。
- 报告分母和缺失情况。
- 避免将基线显著性检验作为平衡性诊断手段。
- 标注调整后、未调整、预先规定和探索性结果。
- 不得将关联关系解读为因果关系或临床可操作性。

默认阈值是一项操作性安全措施，并非 HIPAA 规则或合规保证。参见 `references/cohort_evaluation.md` 和 `references/privacy_and_disclosure.md`。

## 生存分析计划

应共同定义时间零点、事件、竞争事件、删失（censoring）、伴发事件（intercurrent event）、估计目标、时间跨度、效应度量以及分析人群。

- 在将风险比（hazard ratio）视为恒定之前，先评估比例风险假设。
- 预先规定替代方案，例如时变效应或限制性平均生存时间（RMST）。
- 当竞争事件重要时，使用累积发生率方法。
- 处理不朽时间偏倚（immortal-time）、信息性删失、延迟进入、缺失数据和多重性风险。
- 纳入敏感性分析和不确定性，而不仅仅是 p 值。

随附的辅助工具用于验证计划，而非分析生存数据本身。参见 `references/survival_analysis.md`。

## 决策逻辑

仅记录研究或治理相关的逻辑，例如证据纳入、验证关口、发布暂停以及人工审查检查点。每个节点必须关联到来源 ID、测试、负责人、版本和状态。

不得编码诊疗路径、紧急程度、用药操作、诊断规则、报警或面向患者的输出。参见 `references/decision_logic_traceability.md`。

## 隐私与去标识化

HHS 认可的方法是专家判定法（Expert Determination）和安全港法（Safe Harbor）。核对表本身无法独立完成这两种方法中的任何一种。不得声称移除某个字段列表、对标识符进行哈希处理、使用最小单元格数量，或通过此脚本检查即可证明已完成去标识化或符合 HIPAA。

该辅助工具只是对已记录的人工工作进行清点。它绝不读取数据集本身。应将未解决的事项、自由文本、日期、地理信息、罕见组合、关联风险、基因组学数据和纵向模式上报给合格的隐私审查人员。

## 报告指南选择

- 队列研究/病例对照研究/横断面研究：STROBE；对常规收集数据应补充 RECORD。
- 预测模型的开发/评估：TRIPOD+AI 和 PROBAST+AI。
- 肿瘤预后标志物研究：REMARK。
- AI 诊断准确性：STARD-AI 结合 STARD。
- AI 试验方案：SPIRIT-AI 结合当前的 SPIRIT 基础声明。
- AI 随机试验报告：CONSORT-AI 结合当前的 CONSORT 基础声明。
- 早期实时 AI 评估：DECIDE-AI——但实时评估不在此技能的执行范围内。

这些是报告或评审工具，而非自动化的质量评分。参见 `references/study_reporting.md`。

## 监管与治理背景

FDA 器械（device）身份的判定依据是预期用途和功能，而非文档上的标签。FDA 2026 年 1 月发布的 CDS 指南区分了某些非器械 CDS 功能与器械软件功能；其中的示例并非自我认证核对表。ONC HTI-1 要求适用于所定义的认证范围内。ICH E6(R3) 和 E9/E9(R1) 为试验治理和统计计划提供参考，但并不能使某个制品因此就合规。

带日期的背景信息参见 `references/regulatory_and_governance.md`。针对实际产品、研究、申报、部署或司法管辖区，请获取合格的专业建议。

## 验证

在此技能目录下：

```bash
python3 -m unittest discover -s tests/clinical-decision-support -p 'test_*.py'
```

在不生成字节码的情况下运行 AST 编译检查：

```bash
python3 -c "import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('scripts').glob('*.py')]"
```

## 参考文档索引

- `references/README.md` —— 范围与导航
- `references/safety_and_scope.md` —— 拒绝与上报规则
- `references/regulatory_and_governance.md` —— FDA、ONC、ICH 背景
- `references/evidence_profiles.md` —— 人工 GRADE 工作流
- `references/study_reporting.md` —— EQUATOR 和 PROBAST+AI 的选择
- `references/cohort_evaluation.md` —— 聚合队列方法
- `references/survival_analysis.md` —— 事件发生时间（time-to-event）规划
- `references/model_biomarker_evaluation.md` —— 模型/生物标志物评估
- `references/privacy_and_disclosure.md` —— 去标识化与抑制
- `references/decision_logic_traceability.md` —— 治理逻辑
- `references/sources.md` —— 带日期的权威来源清单
- `references/security_validation.md` —— 扫描结果与已接受的 LOW 级发现
