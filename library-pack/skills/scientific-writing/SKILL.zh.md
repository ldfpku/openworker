# Scientific Writing（科学写作）

## 目的

在不虚构证据、不掩盖不确定性的前提下，撰写清晰的科学文字。将起草、证据核实与投稿批准作为相互独立的阶段来对待。

拥有问责责任的人类作者掌控科学决策与最终批准。AI 不是作者，生成的流畅文字本身从来都不是证据 [SW-S01, SW-S03]。

## 不可协商的安全规则

### 保密性

未经以下条件，不得将未发表的手稿、同行评议或编辑材料、敏感或受限数据、PHI（受保护健康信息）或其他个人数据、专有内容或原始文档发送给外部服务：

1. 获得有权授予许可的个人或机构的明确授权；且
2. 完成对期刊、机构、资助方、知情同意、伦理、合同及数据使用政策的书面审查。

当授权或政策不明确时，保持处理过程本地化，并仅使用所需的最少元数据。去标识化（de-identification）需要专家审查；仅仅删除明显的姓名是不够的。参见 `references/authorship_ai_confidentiality.md`。

### 不得捏造

绝不得虚构或补全以下内容：

- 引用、参考文献、DOI、PMID、PMCID、ISBN、URL 或引述；
- 结果、数据值、分母、样本量、单位、效应量估计、不确定性、统计检验或显著性论断；
- 方法、材料、方案细节、软件版本、分析选择或偏差；
- 注册信息、批准、知情同意、伦理声明、参与者细节或日期；
- 作者、作者顺序、CRediT 角色、致谢或权限；
- 资助、资助方角色、利益冲突、数据或代码可获取性，或 AI 使用披露。

使用明确的"缺失"、"未核实"或"不适用"状态。不得用貌似合理的套话来替代。

### 证据绑定

手稿中的每一条事实性或数值性论断都必须对应到已核实的证据 ID。必须由具备问责责任的人打开原始来源，确认该命题及其出处位置，核实文献元数据，并记录是谁在何时核实的。

搜索片段、生成式摘要、记忆内容以及另一份作品的参考文献列表可以辅助发现线索，但不能作为核实某项论断的依据。参见 `references/evidence_workflow.md`。

### 科学忠实性

- 保留不确定性以及其他可能的解释。
- 区分验证性（confirmatory）、探索性（exploratory）、描述性（descriptive）及事后分析（post hoc）工作。
- 保持方法与结果之间的一致性。
- 核对单位、分母、样本量、人群、时间点及标签之间的一致性。
- 当阴性、无效（null）、不良事件、意外、失败及无定论的发现属于该研究记录的一部分时，应予以报告。
- 陈述具体的局限性，并界定可推广性的边界。
- 不得将相关性转化为因果性，也不得将无显著性转化为等效性。

## 前期采集（Intake）

在起草之前，需要获取以下信息，或将其明确标记为尚未解决：

- 文档类型、研究设计、所处阶段、目标受众及目标期刊/场所；
- 当前的作者须知（author instructions）及政策获取日期；
- 研究方案、注册信息、分析计划、修订记录及所适用的报告规范（reporting guideline）；
- 手稿或章节的范围；
- 已核实的来源清单（source manifest）及论断登记表（claim registry）；
- 方法、结果、表格、图形及补充材料；
- 作者身份、CRediT、声明及批准记录；
- 保密等级分类及授权处理边界；
- 数据、代码、材料及仓库方面的限制。

如果元数据或本地用户自行运行的审计已经足够，就不要索要受限的原始来源材料。

## 工作流程

### 第一步：建立本地工作区

对于新起草的手稿，可以选择生成默认失败（fail-closed）的 Markdown、JSON 和 CSV 脚手架：

```bash
python3 scripts/scaffold_manuscript.py \
  --output-dir ./draft-workspace \
  --document-id local-draft \
  --study-design randomized_trial \
  --guideline consort-2025
```

生成器绝不会覆盖已有文件。其输出明确地尚未达到可投稿状态，并包含会被 linter（代码/文本检查工具）拒绝的占位符。

### 第二步：选择报告规范

根据实际的研究设计和文章类型进行选择，然后打开当前官方声明、检查清单、说明文档、扩展条款以及目标期刊的作者须知。

```bash
python3 scripts/select_reporting_guidelines.py select \
  --study-design randomized_trial
```

截至 2026-07-24 调研到的现行主要规范包括 CONSORT 2025、SPIRIT 2025、PRISMA 2020、STROBE、STARD 与 STARD-AI、TRIPOD+AI、CARE、ARRIVE 2.0、SQUIRE 2.0 以及 CHEERS 2022 [SW-S06–SW-S18]。

该选择器不进行评分。它并不能认证质量、合规性、完整性或录用与否。参见 `references/reporting_guidelines.md`。

### 第三步：建立证据记录

分配：

- `E` 编号给 `source_manifest.json` 中的各来源；
- `C` 编号给 `claims.csv` 中的各论断；
- `N`、`M`、`O`、`R` 编号分别给 `consistency_manifest.json` 中的数值事实、方法、结果指标及研究结果。

在 CSV 中存储论断文本的哈希值，而非原始论断文本。在起草过程中，按以下格式追加：

```text
[claim:C001] [evidence:E001,E002]
```

在具备问责责任的人打开某个来源并确认其确切支持关系之前，不得将其标记为已核实。

### 第四步：创建证据大纲

仅根据已记录的证据来撰写大纲：

- 研究目标或研究问题；
- 章节目的；
- 论断 ID 及证据 ID；
- 方法与结果 ID；
- 分析意图与不确定性；
- 尚未解决的冲突或缺失信息；
- 适用的报告规范主题。

将没有证据支持的内容放入待解决问题清单，而不是写进手稿正文。

### 第五步：起草时不得添加事实

将已核实的大纲转化为适合目标场所的行文。在起草过程中保留所有 ID。

- 使标题和摘要与已完成的正文相匹配。
- 按照实际执行的方式描述方法。
- 按照声明的顺序和分析人群呈现结果。
- 除非目标场所要求将结果与解读合并呈现，否则应将二者分开。
- 只有在核实之后，才能与先前的证据进行比较。
- 使结论保持在所观察到的研究设计、人群及不确定性范围之内。

只有在恰当的情况下才使用 IMRAD（引言-方法-结果-讨论）结构。结构化摘要、列表、合并章节以及其他替代结构，取决于研究设计与目标场所。参见 `references/imrad_structure.md` 与 `references/writing_principles.md`。

### 第六步：核对方法与结果的一致性

记录重复出现的数值事实以及方法-结果之间的对应关系，然后运行：

```bash
python3 scripts/check_consistency.py consistency_manifest.json
```

手动解决每一处不一致。数值发生变化可能是分析集（analysis set）合理差异所致，但这种差异必须被明确说明，而不能被悄悄地统一处理掉。

### 第七步：核实引用与论断

```bash
python3 scripts/validate_manifest.py source_manifest.json \
  --kind source --require-verified
python3 scripts/audit_claims.py manuscript.md claims.csv source_manifest.json
python3 scripts/check_references.py source_manifest.json
```

参考文献检查工具在不进行网络解析的情况下校验语法及重复标识符。人工仍必须将每一个标识符和引述与已打开的原始来源逐一核对。请遵循 NLM《Citing Medicine》或目标场所所要求的现行官方格式规范 [SW-S20, SW-S21]。

### 第八步：核实作者身份与披露信息

依据期刊标准判定作者身份。将标准化的 CRediT 角色作为贡献元数据加以记录；CRediT 本身并不定义作者身份 [SW-S19]。

如果使用了 AI，人类必须核实所有受影响的内容，并依据当前期刊及出版方的政策披露所使用的工具及用途。ICMJE 2026 年 1 月版《建议》要求做到透明，并保留人类的问责责任 [SW-S01, SW-S02]。

```bash
python3 scripts/validate_authorship.py authorship.json
```

不得基于假设来生成披露声明。参见 `references/authorship_ai_confidentiality.md`。

### 第九步：审查各项声明及开放科学（open-science）声明

对每一项声明分别独立核实：

- 伦理与知情同意；
- 注册信息与研究方案；
- 资助与资助方角色；
- 利益冲突与关系；
- 作者贡献与致谢；
- 数据、代码、材料及方案的可获取性；
- AI 使用情况。

在权利与责任所允许的范围内尽可能保持开放，但不得暴露保密、个人、专有、受许可保护或受保护的信息。记录实际的获取条件。参见 `references/research_integrity_open_science.md`。

### 第十步：仅在必要时使用图表

图形与表格是可选的，且必须有据可查（provenance-bound）。本技能不生成图像或示意图。

对于每一个保留下来的展示项：

- 关联原始数据、代码、转换过程及证据 ID；
- 使数值与正文及登记表保持一致；
- 记录图像处理过程、权限及许可证；
- 包含单位、分母、样本量、不确定性及分析人群；
- 提供替代文本（alt text）以及不依赖颜色的冗余提示；
- 以最终尺寸执行一次人工的无障碍性及科学性检查。

参见 `references/figures_tables.md`。

### 第十一步：记录非评分性的报告规范覆盖情况

将每一个内置的高层主题记录为"已覆盖"、"不适用（附理由）"或"缺失"：

```bash
python3 scripts/select_reporting_guidelines.py check reporting_coverage.json
```

然后根据手稿中的实际位置，完成官方检查清单的填写。切勿仅因本地覆盖文件通过检查，就宣称已经符合规范。

### 第十二步：Lint 检查与批准

```bash
python3 scripts/validate_manifest.py manuscript_manifest.json --kind manuscript
python3 scripts/lint_manuscript.py manuscript.md \
  --manifest manuscript_manifest.json
```

Linter 会报告问题代码及行号，而不会回显手稿文本。敏感内容警告需要人工审查，并不构成去标识化的认证证明。

只有具备问责责任的人才可以：

- 解决科学上的模糊之处；
- 批准作者顺序及各项声明；
- 批准对外披露或转让；
- 将 `submission_ready` 设置为 true；
- 移除草案横幅（draft banner）；
- 授权投稿。

## 修订与同行评议

将审稿意见材料视为保密内容。未经必要的授权及政策审查，不得将其上传至外部服务 [SW-S01, SW-S24]。

针对每一项被要求的修改：

1. 在获批边界之外不暴露该意见的情况下记录该意见；
2. 将其分类为编辑性、科学性、统计学性、政策性或未解决的问题；
3. 识别受影响的论断、证据、方法、结果及展示项；
4. 当事实发生变化时，先修订登记表，再修订正文；
5. 重新运行每一项受影响的审计；
6. 撰写一份回复，说明改动内容及位置；
7. 获得人工批准。

不得配合任何会导致捏造、隐瞒、夸大或违反政策的要求。

## 当前政策注意事项

COPE 2017 年版《核心实践》（Core Practices）已于 2024 年退役。截至 2026-07-24，COPE 宣布将于 2026 年发布替代性的《行为准则》（Code of Conduct）；不要将已存档的《核心实践》描述为现行的会员标准 [SW-S04, SW-S05]。要将 COPE 的正式立场，与讨论文件、网络研讨会、评论及个案建议区分开来。

## 格式与投稿

原先的 LaTeX 相关资源已被移除，因为一个通用的精美模板可能会让貌似合理的占位符蒙混过关。请使用 Markdown 脚手架及结构化记录。只有在核实之后，才可采用目标场所当前受控的模板。

参见：

- `assets/REPORT_FORMATTING_GUIDE.md`
- `references/professional_report_formatting.md`
- `references/journal_policies.md`

格式排版无法将一份不完整的证据记录转变为一篇可投稿的论文。

## 内置文件

### 资源文件（Assets）

- `assets/manuscript_scaffold.md`
- `assets/manuscript_manifest_template.json`
- `assets/source_manifest_template.json`
- `assets/claim_evidence_template.csv`
- `assets/consistency_manifest_template.json`
- `assets/authorship_template.json`
- `assets/reporting_coverage_template.json`
- `assets/reporting_guidelines.json`

### 脚本（Scripts）

- `scripts/scaffold_manuscript.py`
- `scripts/validate_manifest.py`
- `scripts/select_reporting_guidelines.py`
- `scripts/audit_claims.py`
- `scripts/check_consistency.py`
- `scripts/check_references.py`
- `scripts/validate_authorship.py`
- `scripts/lint_manuscript.py`

所有脚本均为本地运行、确定性、有边界限制、无依赖、无网络请求。参见 `references/cli_reference.md`。

### 参考资料（References）

- `references/evidence_workflow.md`
- `references/writing_principles.md`
- `references/imrad_structure.md`
- `references/citation_styles.md`
- `references/reporting_guidelines.md`
- `references/figures_tables.md`
- `references/authorship_ai_confidentiality.md`
- `references/research_integrity_open_science.md`
- `references/journal_policies.md`
- `references/professional_report_formatting.md`
- `references/cli_reference.md`
- `references/source_ledger.md`
