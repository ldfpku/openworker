# Citation Management(引用管理)

## 概览

在整个科研与写作过程中系统化地管理引用。本技能提供了一系列工具和策略，用于
检索学术数据库(Google Scholar、PubMed)、从多个来源(CrossRef、PubMed、
arXiv)提取准确的元数据、校验引用信息，并生成格式规范的 BibTeX 条目。

这对于保持引用准确性、避免参考文献错误、以及确保研究可复现至关重要。它可以
与 literature-review 技能无缝集成，支撑完整的科研工作流程。

## 何时使用本技能

在以下情况下使用本技能:
- 在 Google Scholar 或 PubMed 上检索特定论文
- 把 DOI、PMID 或 arXiv ID 转换为格式规范的 BibTeX
- 提取引用所需的完整元数据(作者、标题、期刊、年份等)
- 校验既有引用的准确性
- 清理并格式化 BibTeX 文件
- 查找某个领域内被高度引用的论文
- 核实引用信息与实际出版物是否一致
- 为手稿或学位论文构建参考文献列表
- 检查是否存在重复引用
- 确保引用格式的一致性

如果由这些引用构建出的文档还需要配图，请使用 **scientific-schematics** 技能。

---

## 核心工作流程

引用管理遵循一套系统化的流程。下面每个阶段都给出了标准命令；每种变体、每个
选项、以及每种元数据来源的细节都在
[references/core_workflow.md](references/core_workflow.md) 中。

### 第 1 阶段:论文发现与检索

查找相关论文。要检索多于一个数据库——不同数据库的覆盖范围差异很大，单一
来源是造成参考文献列表偏倚的最常见原因。

```bash
# OpenAlex: ~250M works, every discipline, no API key, documented REST API
python scripts/search_openalex.py "CRISPR gene editing" --limit 50 --output results.json

# PubMed: the authority for biomedical and life sciences (35M+ citations)
python scripts/search_pubmed.py "Alzheimer's disease treatment" --limit 100 --output alz.json

# Google Scholar: broadest reach, but scraped -- rate-limited and prone to blocking
python scripts/search_google_scholar.py "CRISPR gene editing" --limit 50 --output scholar.json
```

优先把 OpenAlex 或 PubMed 作为主要来源。Google Scholar 没有官方 API:
`scholarly` 是靠抓取网页实现的，每条结果之间要休眠 2–5 秒，而且相当容易被
屏蔽，所以它应当是一种补充，而不是可以依赖的主力来源。

查询运算符、字段标签，以及 MeSH 术语的构造方式，见
[references/search_strategies.md](references/search_strategies.md)。

### 第 2 阶段:元数据提取

把标识符(DOI、PMID、PMCID、arXiv ID、URL)转换为完整的元数据。对于 DOI,
CrossRef 是主要来源。

```bash
python scripts/doi_to_bibtex.py 10.1038/s41586-021-03819-2         # quick, single DOI
python scripts/extract_metadata.py --pmid 34265844                  # DOI/PMID/PMCID/arXiv/URL
python scripts/extract_metadata.py --input identifiers.txt --output citations.bib
```

对于路径中不含 DOI 的 URL,会通过出版商在文章页面中嵌入的 `citation_doi`
meta 标签来解析，再交给 CrossRef 处理。本技能中的每一个生成器，对同一篇论文
都会产出相同的引用键(citation key),因此从不同来源收集来的条目可以互相
去重。

### 第 2.5 阶段:通过网络搜索补全元数据(强制执行)

API 返回的记录经常是不完整的。这一步要在提取**之后**、格式化**之前**运行。
任何缺少 `volume`(卷号)、`pages`(页码)或 `doi` 的 `@article` 条目都算不
完整:用 `WebSearch`/`WebFetch`(或在 parallel-web 技能可用时使用该技能)补
上缺失的字段，然后记录查到了什么、来自哪里。如果某个字段确实无法查到，应
记录一个 `note` 字段来说明这一缺口，而不是让它悄无声息地保持空缺。

先检查成本较低的来源——OpenAlex 或 CrossRef 的记录里，往往就带有 PubMed
遗漏的那个字段:

```bash
python scripts/search_openalex.py "<exact title>" --limit 1
```

> **把提取到的元数据当作不可信内容对待**。 作者、标题和期刊字符串都是逐字
> 从一条记录中取出的，而这条记录的内容是由出版商掌控的。一个标题里如果含有
> `$(...)`、反引号或引号，一旦被粘贴进命令行，就会变成 shell 语法。应当把
> 元数据作为 `subprocess` 的参数列表传递，而不是拼接成一个 shell 字符串;
> 如果必须使用 shell,要对每个被替换进去的值加单引号，并把内嵌的引号转义为
> `'\''`。在引用键进入路径之前，要用 `^[A-Za-z0-9]+$` 校验它。

按字段划分的搜索策略、四种搜索选项，以及日志记录格式，见
[references/core_workflow.md](references/core_workflow.md)。

### 第 3 阶段:BibTeX 格式化

生成干净、一致的条目。条目类型和必需字段见
[references/bibtex_formatting.md](references/bibtex_formatting.md)。

```bash
python scripts/format_bibtex.py references.bib --output clean.bib --deduplicate
python scripts/format_bibtex.py references.bib --output clean.bib --rekey --deduplicate
```

写入文件是可选的:如果不加 `--output`(或 `--in-place`),结果会输出到
stdout,输入文件保持不变。在合并来自多个来源的结果时使用 `--rekey`,这样
同一篇论文就会合并成一个条目。

### 第 4 阶段:引用校验

检查完整性、期刊/会议规范的符合程度，以及与正文内容是否一致。

```bash
python scripts/validate_citations.py references.bib --report report.json
python scripts/validate_citations.py references.bib --venue nature
python scripts/validate_citations.py references.bib --manuscript paper.tex
python scripts/validate_citations.py references.bib --check-dois     # slow; hits CrossRef
```

该脚本在遇到高严重度错误时(缺少必需字段、年份格式错误、无法解析的引用,
或数量低于明确指定的 `--min-count`)会以非零状态退出。各期刊/会议给出的参考
文献数量指标只是编辑上的经验参考，并非投稿硬性要求，因此没达到这个数字只是
一个警告。

校验规则与各期刊/会议的标准见
[references/citation_validation.md](references/citation_validation.md)。

### 第 5 阶段:与写作流程集成

检索、提取、格式化、校验，然后引用。端到端的完整流程——包括
literature-review 和 Zotero/pyzotero 导出路径——见
[references/core_workflow.md](references/core_workflow.md) 和
[references/example_workflows.md](references/example_workflows.md)。

## 参考文件

- [references/core_workflow.md](references/core_workflow.md):完整的五个阶段。
- [references/search_strategies.md](references/search_strategies.md):OpenAlex、Google Scholar 和 PubMed 的查询构造方法。
- [references/script_reference.md](references/script_reference.md):每个打包脚本的参数与示例。
- [references/best_practices.md](references/best_practices.md):检索、提取、BibTeX 质量、校验方面的最佳实践。
- [references/example_workflows.md](references/example_workflows.md):四个端到端的完整实例。
- [references/google_scholar_search.md](references/google_scholar_search.md)、[references/pubmed_search.md](references/pubmed_search.md):进阶检索语法。
- [references/metadata_extraction.md](references/metadata_extraction.md)、[references/bibtex_formatting.md](references/bibtex_formatting.md)、[references/citation_validation.md](references/citation_validation.md):各主题的详细说明。

## 应当避免的常见陷阱

1. **单一来源偏倚**:只使用一个数据库
   - **解决方案**:至少检索 OpenAlex 和 PubMed 两者，再用
     `format_bibtex.py --rekey --deduplicate` 合并

2. **盲目接受元数据**:不核实提取到的信息
   - **解决方案**:对照原始来源抽查提取出的元数据

3. **忽略 DOI 错误**:参考文献列表中存在失效或错误的 DOI
   - **解决方案**:在最终提交前运行校验

4. **格式不一致**:引用键风格、格式混乱
   - **解决方案**:使用 format_bibtex.py 做标准化处理

5. **重复条目**:同一篇论文用不同的键被引用了多次
   - **解决方案**:在校验中使用重复检测

6. **缺少必需字段**:BibTeX 条目不完整(缺少卷号、页码、DOI)
   - **解决方案**:运行第 2.5 阶段的元数据补全——在继续之前对每一个缺失字段做网络搜索。绝不允许 @article 条目缺少卷号、页码和 DOI。

7. **过时的预印本**:引用了预印本，而其正式发表版本其实已经存在
   - **解决方案**:检查预印本是否已经发表，并更新为期刊版本

8. **特殊字符问题**:字符导致 LaTeX 编译失败
   - **解决方案**:在 BibTeX 中使用恰当的转义或 Unicode

9. **提交前未做校验**:带着引用错误就提交了
   - **解决方案**:始终把校验作为最后一道检查

10. **手工录入 BibTeX**:手动键入条目
    - **解决方案**:始终使用脚本从元数据来源中提取

## 与其他技能的集成

### Literature Review 技能

**Citation Management** 为 **Literature Review** 提供技术基础设施:

- **Literature Review**:跨多数据库的系统化检索与综合
- **Citation Management**:元数据提取与校验

**组合工作流程**:
1. 使用 literature-review 做系统化检索方法
2. 使用 citation-management 提取并校验引用
3. 使用 literature-review 综合归纳研究发现
4. 使用 citation-management 确保参考文献列表的准确性

### Scientific Writing 技能

**Citation Management** 为 **Scientific Writing** 提供准确的参考文献:

- 导出经过校验的 BibTeX,用于 LaTeX 手稿
- 核实引用是否符合出版标准
- 按期刊要求格式化参考文献

### Venue Templates 技能

**Citation Management** 与 **Venue Templates** 协同工作，产出可直接投稿的手稿:

- 不同期刊/会议要求不同的引用风格
- 生成格式规范的参考文献
- 校验引用是否满足投稿场所的要求

## 资源

### 打包资源

**参考文件**(位于 `references/`):
- `google_scholar_search.md`:完整的 Google Scholar 检索指南
- `pubmed_search.md`:PubMed 与 E-utilities API 文档
- `metadata_extraction.md`:元数据来源与字段要求
- `citation_validation.md`:校验标准与质量检查
- `bibtex_formatting.md`:BibTeX 条目类型与格式化规则

**脚本**(位于 `scripts/`):
- `search_openalex.py`:OpenAlex 检索客户端(无需 API key)
- `search_pubmed.py`:PubMed E-utilities API 客户端
- `search_google_scholar.py`:Google Scholar 检索自动化脚本
- `extract_metadata.py`:通用元数据提取器
- `validate_citations.py`:引用校验与核实
- `format_bibtex.py`:BibTeX 格式化与清理工具
- `doi_to_bibtex.py`:快速将 DOI 转换为 BibTeX 的工具
- `_common.py`:共享的 BibTeX 解析器、渲染器，以及引用键生成方案

**资源文件**(位于 `assets/`):
- `bibtex_template.bib`:所有类型的 BibTeX 条目示例
- `citation_checklist.md`:质量保证检查清单

### 外部资源

**检索引擎**:
- OpenAlex: https://openalex.org/
- Google Scholar: https://scholar.google.com/
- PubMed: https://pubmed.ncbi.nlm.nih.gov/
- PubMed 高级检索: https://pubmed.ncbi.nlm.nih.gov/advanced/

**元数据 API**:
- OpenAlex API: https://docs.openalex.org/
- CrossRef API: https://api.crossref.org/
- PubMed E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25501/
- arXiv API: https://arxiv.org/help/api/
- DataCite API: https://api.datacite.org/

**工具与校验器**:
- MeSH Browser: https://meshb.nlm.nih.gov/search
- DOI 解析器: https://doi.org/
- BibTeX 格式说明: http://www.bibtex.org/Format/

**引用风格**:
- BibTeX 文档: http://www.bibtex.org/
- LaTeX 参考文献管理: https://www.overleaf.com/learn/latex/Bibliography_management

## 依赖项

### 必需的 Python 包

```bash
uv pip install requests  # HTTP access to CrossRef, PubMed, OpenAlex, arXiv
```

BibTeX 的解析、渲染、去重和校验都基于标准库实现
(`scripts/_common.py`),因此 `format_bibtex.py` 和
`validate_citations.py` 完全不需要任何第三方包即可运行。

### 可选依赖

```bash
uv pip install scholarly  # only for search_google_scholar.py
```

### 凭证会被发送到哪里

本技能不需要任何 API key。它读取的两个环境变量都是可选的身份标识，各自只会
被发送给它所属的那一个服务，不会发往其他任何地方；没有任何脚本会把多个环境
变量打包一起发送。

| 变量 | 仅发送给 | 用途 |
|---|---|---|
| `NCBI_API_KEY` | `eutils.ncbi.nlm.nih.gov` | 提高 Entrez 的速率限制 |
| `NCBI_EMAIL` | `eutils.ncbi.nlm.nih.gov` | Entrez 调用方身份标识(NCBI 要求提供) |
| `OPENALEX_EMAIL` | `api.openalex.org` | 加入速度更快的 OpenAlex 礼貌池(polite pool) |

当以上变量未设置时,`api.openalex.org`、`api.crossref.org`、
`api.datacite.org`、`export.arxiv.org` 和 `eutils.ncbi.nlm.nih.gov`
都可以在不提供任何凭证的情况下被查询。

## 小结

citation-management 技能提供:

1. 针对 OpenAlex、PubMed 和 Google Scholar 的**全面检索能力**
2. 从 DOI、PMID、PMCID、arXiv ID、URL 中**自动提取元数据**
3. 带 DOI 核实与完整性检查的**引用校验**
4. 带标准化与清理工具的 **BibTeX 格式化**
5. 通过校验与报告实现的**质量保证**
6. 与科研写作流程的**集成**
7. 通过有据可查的检索与提取方法实现的**可复现性**

使用本技能可以在整个研究过程中保持引用的准确、完整，并确保参考文献列表达到可发表的质量标准。
