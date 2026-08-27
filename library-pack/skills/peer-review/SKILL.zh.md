# 同行评审（Peer Review）

支持一位负责任的人类评审人做出严谨、公正、可操作的评估。将每一份未发表的投稿和评审都视为机密。

## 强制性安全边界

在阅读或分析未发表的内容之前：

1. 确认用户已获得出版方、编辑、作者或其他材料所有者的授权。
2. 检查目标期刊/会议（venue）在评审、保密、共同评审、留存以及 AI/工具使用方面的政策。
3. 记录利益冲突、能力限制、请求的范围以及是否需要专家评审。
4. 默认仅进行本地处理。

如果授权情况不明确，不得查看或引用稿件内容。应要求确认，或仅使用随附的本地 CLI 工具——其报告不会回显稿件文本。

绝不可以：

- 在没有出版方/作者明确授权及期刊/会议许可的情况下，将未发表的稿件、补充材料、评审意见或编辑往来文本发送给外部服务
- 将机密内容上传至公共模型、搜索引擎、引文服务、语法检查工具、查重工具或图像服务
- 将内容重新用于训练、基准测试、产品改进或无关研究
- 读取大范围的环境状态、`.env` 文件、API 密钥或凭据
- 从随附工具中调用网络、LLM 或图像 API
- 自动调用其他技能或 PDF/图像处理流水线
- 冒充受指派的评审人、编辑、期刊/会议或作者
- 捏造稿件细节、评审结论、引文、分析、实验、复现结果或编辑决定
- 宣布本应由编辑或评审小组做出的决定

在政策要求时删除本地副本及其衍生内容；否则仅保留受管控政策所允许保留的内容。记录删除或留存情况时，不得将机密内容抄录进记录中。

处理机密材料前请先阅读 `references/ethical_review_practice.md`。

## 人类问责

将生成的文本标注为工作草稿。负责任的人类评审人必须：

- 阅读完整的、获得授权的投稿及相关补充材料
- 核实每一项事实陈述、计算、引文及在稿件中的位置
- 处理利益冲突，并按要求披露所获协助
- 用自己的专业判断重新撰写评语
- 通过获得授权的渠道提交

自动化的覆盖度、一致性或代码检查（lint）结果并不构成同行评审，也不能确立稿件的学术价值。

## 准入关口

复制并填写 `assets/review_intake_template.json`，然后运行：

```bash
python3 scripts/validate_review_intake.py completed-intake.json
```

只有当状态为 `READY_FOR_LOCAL_REVIEW` 时才可继续。

验证工具会拦截以下情况：

- 未记录的授权
- 缺失的人类问责
- 未评估或未解决的利益冲突
- 未知的评审模式或未核实的期刊/会议政策
- 未经授权的 AI 协助
- 使用外部服务
- 数据重用
- 缺失删除/留存规划

它验证的是声明本身，而非声明的真实性。

## 评审工作流

### 1. 确立范围与可用证据

记录：

- 投稿类型及所处阶段
- 评审问题及请求关注的重点
- 目标期刊/会议及评审模式
- 实际可用的材料：稿件、补充材料、方案（protocol）、注册记录、分析计划、数据/代码声明、既往决定或回复信
- 能力所及的领域及其限制
- 妨碍评估的缺失材料

不得推断缺失的内容。应使用"未报告"或"评审时不可获得"这样的表述。

### 2. 先定位而不下结论

创建一份简短的中立地图：

- 研究问题
- 研究人群或系统
- 设计与分析单位
- 干预、暴露、检测或模型
- 对照/参照
- 结局指标及其时间点
- 主要主张

不得撰写接受/拒绝的建议。应识别评估每项主张所需的证据。

### 3. 选择报告指南

复制 `assets/study_profile_template.json` 并运行：

```bash
python3 scripts/select_reporting_guidelines.py local-profile.json
```

若需要核对表覆盖度检查：

```bash
python3 scripts/select_reporting_guidelines.py \
  local-profile.json \
  --coverage local-coverage.csv
```

使用当前的基础指南、扩展说明文件（explanation/elaboration）、适用的扩展版本以及目标期刊/会议的政策。参见 `references/reporting_standards.md`。

**关键区别**： 报告完整性不等于设计质量、偏倚风险、有效性或学术价值。绝不能把缺失项自动转换为评分或发表判断。

### 4. 将主张映射到证据

优先处理核心的、因果性的、机制性的、安全性的、诊断性的、预测性的以及可推广性方面的主张。

对每项主张记录：

- 位置及主张 ID
- 支持性的结果、图、表、分析或引文 ID
- 方向、幅度、人群、结局指标、时间点及不确定性是否一致
- 局限性或替代解释
- 有明确边界的、请求作者采取的行动

运行：

```bash
python3 scripts/validate_claim_evidence.py local-claim-matrix.csv
```

以 `assets/claim_evidence_matrix_template.csv` 为起点。该报告输出的是 ID 和计数，而非主张文本本身。

### 5. 评审方法与统计

按以下顺序评估：

1. 问题与目标量
2. 设计与推断单位
3. 抽样、分配、对照、盲法及时间安排
4. 样本量或精度的确定依据
5. 纳入、排除、失访及缺失情况
6. 分析与设计的匹配度及假设条件
7. 多重性与预先规定
8. 效应估计、不确定性、分母及危害
9. 解读、因果关系及可推广性

参考 `references/common_issues.md` 和 `references/statistical_reproducibility.md`。

如需结构化的本地审计：

```bash
python3 scripts/audit_statistics_reproducibility.py \
  local-statistics-reproducibility.json
```

以 `assets/statistical_reproducibility_template.json` 为起点。当某项核心方法超出自身能力范围时，应请求专家评审；不得把不确定性掩藏在笼统的批评之下。

### 6. 评审可复现性与透明度

酌情检查：

- 方案（protocol）、注册记录、修订及分析计划的一致性
- 数据来源（provenance）、排除条件、转换过程及登录号（accession ID）
- 软件、软件包、模型及参数的版本
- 代码、运行环境、随机种子、运行说明及测试
- 数据、代码、材料及模型的可获得性，或有正当理由的限制
- 领域内元数据标准

除非确实以获得授权的输入并按记录在案的命令、环境和输出实际运行过，否则不得声称已进行复现。

### 7. 评审伦理与诚信

检查适用的审批、知情同意、福利、隐私、社区治理、资助、赞助方角色、利益冲突、作者身份/贡献、注册、生物安全及双重用途方面的问题。

描述可观察到的证据及不确定性。不得指控作者或对其进行调查。可信的诚信问题应通过期刊/会议政策规定的机密编辑渠道上报。

### 8. 评审图、表和引文

对图和表，评估：

- 与正文及补充材料的一致性
- 分母、单位、坐标轴、比例尺、不确定性及图例
- 是否采用了无障碍的编码方式及充分的说明
- 图像采集/处理的披露情况及原始数据政策

此技能没有图像生成或 PDF 转换工作流。只能使用用户已授权的本地制品和工具。

对于 Pandoc 风格的引用（如 `[@ref-id]`）：

```bash
python3 scripts/audit_citations.py local-manuscript.md local-references.csv
```

以 `assets/citation_references_template.csv` 为起点。此项仅检查键值一致性和标识符格式；不验证来源是否真实存在或是否支持该主张。

### 9. 起草可操作的评语

只有在准入检查通过后，才生成私密的评审骨架：

```bash
python3 scripts/generate_review_scaffold.py \
  completed-intake.json \
  -o private-review.md
```

每条主要/次要评语都应包含：

- **位置（Location）**
- **观察（Observation）**
- **证据或标准（Evidence or criterion）**
- **为何重要（Why it matters）**
- **请求采取的行动（Requested action）**

优先关注：

- 主张与证据的一致性
- 方法与统计的有效性
- 可复现性与透明度
- 伦理及受试者/动物保护
- 评估所需的报告事项
- 图、表、局限性及引文

要求作者开展新工作时，必须是支持核心主张所必需的，且与评审范围相称。若缩小范围、澄清、敏感性分析、更正或补充局限性表述已足够，应优先提出这些方案。

### 10. 保持渠道分离

**致作者的评语**包含科学性的评审意见、优点、主要/次要评语及局限性。

**致编辑的机密评语**仅包含符合政策要求的利益冲突、能力限制、协助情况披露、专家评审请求，或需要走单独渠道的、有充分证据的诚信/流程方面的担忧。

不得把普通的批评意见只放在机密备注中。在匿名评审流程下不得泄露评审人身份。

### 11. 代码检查（Lint）与定稿

```bash
python3 scripts/lint_review.py private-review.md
```

该检查工具会核查渠道分离、未解决的占位符、一个范围有限的辱骂性用语词库、角色/决定类措辞，以及必需的可操作性字段。它输出的是行号和规则 ID，而非评审文本本身。人性化的语气和科学性的评审内容仍是强制要求。

在交付之前：

- 核实所有位置和证据。
- 删除没有依据或推测性的批评。
- 确认语言专业、无辱骂性内容。
- 说明评审的局限性及是否需要专家评审。
- 披露获得许可的协助情况。
- 删除所有占位符。
- 确保没有捏造的引文、实验、重新分析或结论。
- 遵循已记录在案的删除/留存规则。

## 本地工具索引

- `scripts/validate_review_intake.py` —— 范围、授权、利益冲突、政策、处理方式
- `scripts/select_reporting_guidelines.py` —— 带日期的选择器及非评分性覆盖度审计
- `scripts/validate_claim_evidence.py` —— 主张/证据一致性矩阵
- `scripts/audit_statistics_reproducibility.py` —— 方法/统计/可复现性核对表
- `scripts/audit_citations.py` —— 本地引文/参考文献一致性检查
- `scripts/generate_review_scaffold.py` —— 渠道分离的私密 Markdown 骨架
- `scripts/lint_review.py` —— 语气、渠道及可操作性检查

完整的模式（schema）及退出码：`references/tool_reference.md`。

## 参考资料与资产

- `references/ethical_review_practice.md` —— COPE/ICMJE 职责、保密性、AI、渠道
- `references/reporting_standards.md` —— 当前主要指南及经核实的领域标准
- `references/statistical_reproducibility.md` —— 方法、统计及可复现性评审
- `references/common_issues.md` —— 常见问题模式及建设性回应
- `references/security_validation.md` —— 基线修复措施及本地扫描结果
- `assets/source_ledger.csv` —— 于 2026-07-23 核实的权威来源
- `assets/reporting_guidelines.json` —— 本地选择器目录
- `assets/review_scaffold_template.md` —— 私密结构化草稿

来源清单是带日期的。在后续评审中应重新核查最新的一手来源以及目标期刊/会议的政策，且不得在搜索查询中泄露机密的稿件文本。
