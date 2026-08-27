# 期刊/会议模板（Venue Templates）

在准备发表和资助相关文档时，避免把过时的格式细节当作权威依据。此技能整合了以下内容：

- 一套以核实当前期刊/会议规则为先的工作流；
- 针对一小部分明确文档类型的随附 LaTeX 骨架；
- 写作风格及评审人预期指南；以及
- 用于发现、复制和检查模板的本地辅助工具。

## 强制性时效规则

期刊/会议的要求具有时效性。在给出确切的页数限制、截止日期、样式文件名称、匿名规则或必需章节之前：

1. 明确具体的期刊/会议、年份或资助周期、赛道（track）以及文章或提案类型。
2. 打开官方的作者须知、征稿通知、招标说明（solicitation）、资助机会通知（NOFO）或政策指南。
3. 记录来源 URL 及核查日期。
4. 区分初次投稿、修订/答辩（rebuttal）以及最终定稿（camera-ready）阶段的规则。
5. 除非此技能明确说明随附文件是官方模板的副本，否则应将其视为骨架（scaffold）。

绝不能通过修改旧文件名中的年份来推断当前的样式文件名称。绝不能把通用骨架当作官方期刊/会议模板呈现给用户。

## 何时使用

在以下情况使用此技能：

- 查找官方期刊或会议的作者须知；
- 检查页数限制、必需章节、匿名要求、补充材料规则或引用格式；
- 选择并定制随附的 LaTeX 骨架；
- 准备 NSF、NIH、DOE、DARPA 或基金会的提案文档；
- 在核查活动专属尺寸之后设计研究海报；
- 使文章风格适配特定期刊/会议的受众及评审人预期；或
- 检查 PDF 的页数和内嵌字体。

## 以核实为先的工作流

### 1. 明确具体目标

询问或推断以下信息：

- 期刊/会议或资助机构；
- 年份/周期及赛道；
- 文档类型，例如研究论文、短文、主赛道、R01 或 R21；
- 投稿阶段；以及
- 撰写格式，例如 LaTeX 或 Word。

不得将名称相似的不同期刊/会议或赛道的规则混用。

### 2. 查阅正确的参考资料

| 需求 | 参考资料 |
|---|---|
| 期刊投稿及官方出版方资源 | `references/journals_formatting.md` |
| 会议规则及 2026 年经核实的快照 | `references/conferences_formatting.md` |
| 海报尺寸、排版及无障碍性 | `references/posters_guidelines.md` |
| NSF、NIH、DOE、DARPA 及基金会提案 | `references/grants_requirements.md` |
| 跨期刊/会议的写作风格对比 | `references/venue_writing_styles.md` |
| Nature 与 Science 的写作风格 | `references/nature_science_style.md` |
| Cell Press 的写作风格 | `references/cell_press_style.md` |
| 医学期刊的写作风格 | `references/medical_journal_styles.md` |
| 机器学习及计算机视觉会议的写作风格 | `references/ml_conference_style.md` |
| ACL、EMNLP、CHI 及其他计算机科学类写作风格 | `references/cs_conference_style.md` |
| 评审标准与答辩（rebuttal） | `references/reviewer_expectations.md` |

参考文件对规则进行了归纳总结，但不能取代当前的官方来源。

### 3. 记录一份合规性说明

在开始编辑之前，在工作文档或任务日志中撰写一份简短说明：

```text
Target: ICML 2026 main track, initial submission
Official source: https://icml.cc/Conferences/2026/AuthorInstructions
Checked: 2026-07-20
Main-text limit: 8 pages
References/appendices: additional pages allowed in the same PDF
Anonymity: required
Official template: ICML 2026 style package linked by the author instructions
```

这样可以使后续的验证过程具有可复现性。

### 4. 从官方模板开始

对于年度会议及由出版方管理的工作流：

1. 从官方来源下载模板。
2. 保持其 class/style 文件不变。
3. 添加内容时不得覆盖页边距、字号、间距或页眉页脚。
4. 仅在起草阶段使用随附骨架，或在官方来源明确许可的情况下使用。

对于资助提案，许多组成部分是分开填写或上传的。不得将合并后的随附 `.tex` 文件当作机构颁发的表格来提交。

### 5. 人工与自动化双重验证

至少应验证以下事项：

- 正文及全文件的页数规则；
- 字体、页边距、行距及纸张尺寸规则；
- 匿名性及元数据；
- 必需的章节、声明、核对表及披露事项；
- 图/表的排版及无障碍性；
- 参考文献及补充材料的处理方式；以及
- 源文件包及 PDF 的要求。

该辅助工具可以检查总页数和内嵌字体，但无法证明页边距、字号、被排除的章节或隐藏元数据是否合规。

## 随附资产

此代码库刻意只随附以下模板。参考资料中列出的其他期刊/会议需要使用官方的外部模板。

### 期刊与会议骨架

| 文件 | 状态 |
|---|---|
| `assets/journals/nature_article.tex` | 面向 Nature 风格的通用写作骨架；不是官方 Nature 模板 |
| `assets/journals/plos_one.tex` | 面向 PLOS ONE 风格的骨架；请与当前官方 PLOS LaTeX 软件包对比 |
| `assets/journals/neurips_article.tex` | NeurIPS 2026 封装文件；需要官方的 `neurips_2026.sty` |
| `assets/journals/elsarticle-template-num.tex` | Elsevier `elsarticle` 数字引用示例 |
| `assets/journals/elsarticle-template-num-names.tex` | Elsevier `elsarticle` 编号/作者名示例 |
| `assets/journals/elsarticle-template-harv.tex` | Elsevier `elsarticle` 作者-年份示例 |

对应的 Elsevier `.bst` 文件位于 `assets/journals/` 中。

### 资助提案骨架

| 文件 | 状态 |
|---|---|
| `assets/grants/nsf_proposal_template.tex` | 用于常见 NSF 叙述性组成部分的规划骨架；各组成部分需分别上传 |
| `assets/grants/nih_specific_aims.tex` | 用于 NIH Specific Aims 一页附件的写作骨架 |

在需要的地方应使用 SciENcv 及机构提供的通用表格。不得用 LaTeX 重新制作个人简历（biosketch）或当前资助情况表格。

### 海报骨架

| 文件 | 状态 |
|---|---|
| `assets/posters/beamerposter_academic.tex` | 与具体期刊/会议无关的通用 beamerposter 骨架；应根据活动当前的报告人须知设置尺寸 |

## 常见工作流

### 年度会议论文

1. 打开 `references/conferences_formatting.md`。
2. 依照官方链接查看确切年份和赛道的信息。
3. 下载官方作者工具包（author kit）。
4. 在官方模板中起草。
5. 在双盲评审的情况下，确保每个提交文件中都不含身份识别信息。
6. 分别检查论文核对表、补充材料、答辩（rebuttal）及最终定稿（camera-ready）规则。

对于 NeurIPS 2026，在下载官方样式文件之后可以复制随附的封装文件：

```bash
python scripts/customize_template.py \
  --template neurips_article.tex \
  --output my_neurips_2026_paper.tex
```

### 期刊稿件

1. 明确具体的期刊及文章类型。
2. 确定初次投稿是否格式灵活。
3. 在需要时使用该期刊的官方模板或投稿格式。
4. 应用相应的写作风格参考资料。
5. 仅在被接受或需要修订之后，才重新核查最终制作阶段的说明。

当期刊有自己的《作者指南》（Guide for Authors）时，不得套用出版方通用的模板。

### 资助提案

1. 在参考机构总体指南之前，先阅读招标说明或 NOFO。
2. 确认当前有效的政策指南和表格组合。
3. 将每个必需的组成部分与其页数限制及上传字段对应起来。
4. 使用机构系统和通用表格来处理个人简历及资助情况披露。
5. 仅将随附的 `.tex` 文件用作起草辅助。
6. 让所在机构的资助研究办公室审查最终材料包。

### 研究海报

1. 阅读活动的报告人须知。
2. 确认物理尺寸、方向、文件格式及上传截止日期。
3. 在骨架中设置海报尺寸。
4. 使用清晰易读的字体、高对比度、不依赖颜色区分的编码方式，以及合理的阅读顺序。
5. 按最终尺寸导出并检查 PDF。

## 辅助脚本

从此技能所在目录运行脚本。

### 列出随附模板

```bash
python scripts/query_template.py --list-all
python scripts/query_template.py --venue NeurIPS --requirements
python scripts/query_template.py --type grants
```

该查询工具仅报告此技能中实际存在的资产，并附带来源/时效性说明。

### 复制并定制骨架

```bash
python scripts/customize_template.py \
  --template nature_article.tex \
  --title "Your Paper Title" \
  --authors "First Author, Second Author" \
  --affiliations "Institution Name" \
  --output my_paper.tex
```

在添加大量内容之前，应审查每一处替换内容并进行编译。用户提供的文本可能需要进行 LaTeX 转义。

### 检查 PDF

使用已验证的预设：

```bash
python scripts/validate_format.py \
  --file paper.pdf \
  --venue icml-2026 \
  --content-pages 8 \
  --check page-count,fonts
```

或提供明确的页数限制和来源：

```bash
python scripts/validate_format.py \
  --file proposal.pdf \
  --max-pages 15 \
  --content-pages 15 \
  --source-url "https://www.nsf.gov/policies/pappg" \
  --check page-count,fonts \
  --report validation.txt
```

`--content-pages` 必须按照官方规则计算。该脚本不会自行推断参考文献或附录从何处开始。

## 最终合规性核对表

- [ ] 已明确具体的期刊/会议、年份/周期、赛道、文章类型及阶段
- [ ] 已记录官方来源 URL 及核查日期
- [ ] 在需要时已使用官方模板或表格
- [ ] 已理解页数限制的适用范围，包括被排除的章节
- [ ] 已包含必需的声明、核对表及披露事项
- [ ] 已检查双盲评审文件及 PDF 元数据是否泄露身份信息
- [ ] 图和表清晰可读且具备无障碍性
- [ ] 参考文献、附录及补充材料遵循当前规则
- [ ] PDF 及源文件包可正常编译
- [ ] 已在最终提交前查看投稿系统的预览效果

## 维护

此技能于 2026-07-20 完成审查。年度会议的快照均标注了对应年份。更新时应：

1. 仅在核查官方来源之后才替换特定年份的相关内容；
2. 避免添加指向未随附资产的链接；
3. 将通用指导内容与官方要求区分开；
4. 同步更新辅助工具的预设和示例；以及
5. 递增 `metadata.version`。
