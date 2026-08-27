# 文献综述（Literature Review）

## 概述

按照严谨的学术方法论，开展系统性的、全面的文献综述。检索多个文献数据库、按主题综合各方发现、核实所有引用的准确性，并生成 markdown 和 PDF 格式的专业输出文档。

本技能使用 **parallel-web 技能**（`parallel-cli search`）作为进行广泛学术文献发现的主要网络检索工具，并辅以专门的数据库访问技能（gget、bioservices、datacommons-client）加以补充。它还提供了用于引用核实、结果汇总和文档生成的专用工具。

## 何时使用本技能

在以下情况下使用本技能:
- 为研究或发表撰写系统性文献综述
- 就某一特定主题，跨多个来源综合当前的知识现状
- 进行 meta 分析或范围综述（scoping review）
- 撰写研究论文或学位论文中的文献综述部分
- 调研某一研究领域的最新进展（state of the art）
- 识别研究空白和未来方向
- 需要经过核实的引用和专业的排版格式

## 用科学示意图进行视觉增强

**⚠️ 强制要求:每一份文献综述都必须使用 scientific-schematics 技能，包含至少 1-2 张 AI 生成的图**。

这不是可选项。没有视觉元素的文献综述是不完整的。在最终定稿任何文档之前:
1. 至少生成一张示意图或图表（例如，系统综述使用的 PRISMA 流程图）
2. 对于全面的综述，建议使用 2-3 张图（检索策略流程图、主题综合示意图、概念框架图）

**如何生成图**:
- 使用 **scientific-schematics** 技能来生成 AI 驱动的、达到出版级质量的示意图
- 只需用自然语言描述你想要的图
- Nano Banana Pro 会自动生成、审阅并优化该示意图

**如何生成示意图**:
```bash
python scripts/generate_schematic.py "your diagram description" -o figures/output.png
```

AI 将自动:
- 创建格式规范、达到出版级质量的图像
- 通过多轮迭代进行审阅和优化
- 确保无障碍性（对色盲友好、高对比度）
- 将输出保存到 figures/ 目录中

**何时添加示意图**:
- 系统综述所用的 PRISMA 流程图
- 文献检索策略流程图
- 主题综合示意图
- 研究空白可视化地图
- 引用网络图
- 概念框架图示
- 任何能从可视化中获益的复杂概念

关于创建示意图的详细指导，请参阅 scientific-schematics 技能文档。

---

## 核心工作流程

一份文献综述分七个阶段进行，完整的命令和模板记录在
[references/core_workflow.md](references/core_workflow.md) 中:

1. **规划与界定范围** —— 确定研究问题、纳入和排除标准以及范围。
2. **系统性文献检索** —— 跨多个数据库检索，并记录所用的检索式。
3. **筛选与选择** —— 先进行标题/摘要筛选，再进行全文筛选，并保留各阶段的计数以用于 PRISMA 流程图。
4. **数据提取与质量评估** —— 结构化提取，以及偏倚风险或质量评价。
5. **综合与分析** —— 跨研究进行主题性或定量性的综合。
6. **引用核实** —— 每一条引用都要对照实际来源进行核实。
7. **文档生成** —— 汇总成完整的综述，并附带完整的参考文献列表。

在进行过程中要记录每一条检索式和检索日期:一份无法复现自身检索过程的综述，称不上是系统性的。按数据库划分的检索指南和引用格式见
[references/search_and_citation.md](references/search_and_citation.md),完整的实例综述见
[references/example_workflow.md](references/example_workflow.md)。

## 最佳实践

### 检索策略
1. **从 parallel-web 开始**:在查询专门数据库之前，先用限定学术域名的 `parallel-cli search` 进行初步的广泛覆盖检索
2. **使用多个数据库**（至少 3 个）:确保覆盖全面——parallel-web 算作一个来源
3. **纳入预印本服务器**:捕获尚未正式发表的最新研究成果
4. **记录一切**:检索式、日期、结果数量，以确保可复现性——把所有 parallel-cli 的输出保存到 `sources/`
5. **测试并改进**:先做试探性检索，审阅结果，再调整检索词
6. **按引用量排序**:在有相关数据时，按引用次数对检索结果排序，优先呈现有影响力的工作
7. **使用 parallel-cli extract**:从检索中发现的有价值的 URL 中抓取完整内容，在进入全文筛选前先核实其相关性

### 筛选与选择
1. **使用多个数据库**（至少 3 个）:确保覆盖全面
2. **纳入预印本服务器**:捕获尚未正式发表的最新研究成果
3. **记录一切**:检索式、日期、结果数量，以确保可复现性
4. **测试并改进**:先做试探性检索，审阅结果，再调整检索词

### 筛选与选择
1. **使用清晰的标准**:在筛选之前先记录好纳入/排除标准
2. **系统性地筛选**:标题 → 摘要 → 全文
3. **记录排除情况**:记录排除某项研究的原因
4. **考虑双人筛选**:对于系统综述，应由两名审阅者独立筛选

### 综合
1. **按主题组织**:按主题分组，而不是按单篇研究罗列
2. **跨研究综合**:进行比较、对照，识别模式
3. **保持批判性**:评估证据的质量和一致性
4. **识别空白**:注明哪些方面缺失或研究不足

### 质量与可复现性
1. **评估研究质量**:使用合适的质量评估工具
2. **核实所有引用**:运行 verify_citations.py 脚本
3. **记录方法论**:提供足够的细节，使他人能够复现
4. **遵循指南**:系统综述应使用 PRISMA

### 写作
1. **保持客观**:公正地呈现证据，承认局限性
2. **保持系统性**:遵循结构化模板
3. **保持具体**:尽可能给出数字、统计量、效应量
4. **保持清晰**:使用清晰的标题、合理的行文逻辑、按主题组织

## 需要避免的常见陷阱

1. **只检索单一数据库**:会遗漏相关论文；应始终检索多个数据库
2. **没有检索记录**:会使综述无法复现；应记录所有检索过程
3. **逐篇研究罗列式总结**:缺乏综合；应改为按主题组织
4. **未经核实的引用**:会导致错误；应始终运行 verify_citations.py
5. **检索范围过宽**:会产生成千上万条不相关的结果；应用更具体的检索词加以细化
6. **检索范围过窄**:会遗漏相关论文；应纳入同义词和相关术语
7. **忽略预印本**:会遗漏最新发现；应纳入 bioRxiv、medRxiv、arXiv
8. **没有质量评估**:会把所有证据一视同仁；应评估并报告质量
9. **发表偏倚**:只有阳性结果被发表；应注明潜在的偏倚
10. **检索结果过时**:该领域发展迅速；应清楚说明检索日期

## 与其他技能的集成

本技能可与其他科学类技能无缝协作:

### 网络检索与内容提取（parallel-web 技能 —— 主要工具)
- **parallel-cli search**:带域名过滤的广泛学术与通用网络检索——用于初步的范围界定、查找论文、引用链追溯以及补充检索
- **parallel-cli extract**:从论文 URL、期刊网站和预印本服务器抓取完整内容——用于阅读摘要、提取参考文献列表以及核实论文细节
- **parallel-cli search --include-domains**:面向学术领域的检索，限定在学术域名范围内（arxiv.org、pubmed、nature.com 等)

### 数据库访问技能
- **gget**:PubMed、bioRxiv、COSMIC、AlphaFold、Ensembl、UniProt
- **bioservices**:ChEMBL、KEGG、Reactome、UniProt、PubChem
- **datacommons-client**:人口统计、经济、健康统计数据

### 分析技能
- **pydeseq2**:RNA-seq 差异表达分析（用于方法部分)
- **scanpy**:单细胞分析（用于方法部分)
- **anndata**:单细胞数据（用于方法部分)
- **biopython**:序列分析（用于背景介绍部分)

### 可视化技能
- **matplotlib**:为综述生成图和图表
- **seaborn**:统计可视化

### 写作技能
- **brand-guidelines**:为 PDF 应用机构品牌样式
- **internal-comms**:为不同受众调整综述内容
- **venue-templates**:在为发表准备综述时，查阅特定期刊/会议的写作风格指南

### 特定发表场所的写作风格

在为特定期刊准备文献综述时，可查阅 **venue-templates** 技能获取写作风格指导:
- `venue_writing_styles.md`:各发表场所的风格对比总表
- `nature_science_style.md`:Nature/Science 的流畅摘要风格、故事驱动式结构
- `cell_press_style.md`:Cell Press 的图文摘要（graphical abstracts）、Highlights 格式
- `medical_journal_styles.md`:NEJM/Lancet/JAMA 的结构化摘要、PRISMA 合规性要求

这些指南有助于把你综述的语气、摘要格式和结构，调整到符合目标发表场所的要求。

## 资源

### 内置资源

**脚本**:
- `scripts/verify_citations.py`:核实 DOI 并生成格式化引用
- `scripts/generate_pdf.py`:将 markdown 转换为专业排版的 PDF
- `scripts/search_databases.py`:处理、去重并格式化检索结果

**参考文档**:
- `references/citation_styles.md`:详细的引用格式指南（APA、Nature、Vancouver、Chicago、IEEE)
- `references/database_strategies.md`:全面的数据库检索策略

**资源文件**:
- `assets/review_template.md`:包含全部章节的完整文献综述模板

### 外部资源

**指南**:
- PRISMA（系统综述）: http://www.prisma-statement.org/
- Cochrane 手册: https://training.cochrane.org/handbook
- AMSTAR 2（综述质量）: https://amstar.ca/

**工具**:
- MeSH Browser: https://meshb.nlm.nih.gov/search
- PubMed 高级检索: https://pubmed.ncbi.nlm.nih.gov/advanced/
- 布尔检索指南: https://www.ncbi.nlm.nih.gov/books/NBK3827/

**引用格式**:
- APA 格式: https://apastyle.apa.org/
- Nature Portfolio: https://www.nature.com/nature-portfolio/editorial-policies/reporting-standards
- NLM/Vancouver: https://www.nlm.nih.gov/bsd/uniform_requirements.html

## 依赖项

### 所需的 CLI 工具
```bash
# parallel-cli (PRIMARY — for web search and URL extraction)
curl -fsSL https://parallel.ai/install.sh | bash
# Or: uv tool install "parallel-web-tools[cli]"
# Authenticate: parallel-cli auth
```

### 所需的 Python 包
```bash
uv pip install requests  # For citation verification
```

### 所需的系统工具
```bash
# For PDF generation
brew install pandoc  # macOS
apt-get install pandoc  # Linux

# For LaTeX (PDF generation)
brew install --cask mactex  # macOS
apt-get install texlive-xetex  # Linux
```

检查依赖项:
```bash
python scripts/generate_pdf.py --check-deps
```

## 小结

本 literature-review 技能提供:

1. 遵循学术最佳实践的**系统性方法论**
2. 由 **parallel-web 驱动的检索**,使用 `parallel-cli search`,借助学术域名过滤实现快速、广泛的学术文献发现
3. 通过现有科学类技能（gget、bioservices、datacommons-client）实现的**多数据库集成**
4. 确保准确性与可信度的**引用核实**
5. markdown 和 PDF 格式的**专业输出**
6. 覆盖整个综述流程的**全面指导**
7. 带有核实与验证工具的**质量保证**
8. 通过详尽的文档要求实现的**可复现性**

在任何领域中，都能开展符合学术标准、对当前知识现状进行全面综合的、严谨扎实的文献综述。
