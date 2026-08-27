# 通路富集分析(Pathway Enrichment)

## 概述

富集分析回答的问题是"我的基因中有哪些生物学功能被过度表征(over-represented)?"这是差异表达分析、筛选或聚类之后的标准最后一步。核心方法有两种，正确选择方法是最重要的决策:

- **ORA(over-representation analysis,过表征分析)** —— 取一份*经过阈值筛选*的基因列表(例如 padj < 0.05),用 Fisher 精确检验 / 超几何检验来检验它与哪些基因集的重叠程度超出随机水平。工具:Enrichr、g:Profiler。
- **GSEA(gene set enrichment analysis,基因集富集分析)** —— 取*整份排序的*基因列表(不设阈值),检验每个基因集是否在排序的顶部或底部富集。预排序(Preranked)GSEA 使用每个基因的一个分数(例如 DESeq2 的 `stat`)。当效应广泛而微弱时效果更好。

这份技能负责编排这些分析、支撑它们的基因集数据库，以及会使结果出错或无法发表的解读陷阱。

## 何时使用此技能

在用户想要做以下事情时使用此技能:
- 在一份基因列表中找到富集的 GO 词条 / KEGG / Reactome / WikiPathways / MSigDB Hallmark 基因集。
- 在 DESeq2、edgeR、limma 或 Scanpy 的 `rank_genes_groups` 输出上运行 GSEA / 预排序 GSEA。
- 对每个样本/细胞的通路活性打分(ssGSEA、GSVA)。
- 解读、去重并可视化富集结果，或构建发表用的表格/图。
- 在 ORA 与 GSEA 之间做选择、挑选基因集库、选择背景集合，或修复基因 ID 问题。

对于快速的一次性 Enrichr 查询,`gget` 技能(`gget enrichr`)更轻量；对于原始的通路/相互作用 API(Reactome、KEGG、STRING),见 `database-lookup` 技能。要做完整的、经得起推敲的富集分析工作流，请使用**这个**技能。

## 选择合适的方法

| 情形 | 方法 | 工具/入口 |
|-----------|--------|--------------------|
| 你有一份离散的命中列表(DE 基因、筛选命中、簇标记基因) | **ORA** | `gp.enrichr(...)` 或 g:Profiler |
| 你有一份完整的排序列表(每个被检验的基因 + 一个分数) | **预排序 GSEA** | `gp.prerank(...)` |
| 你有一个表达矩阵 + 分组标签 | **GSEA** | `gp.gsea(...)` |
| 你想要每个样本/细胞的一个通路分数 | **ssGSEA / GSVA** | `gp.ssgsea(...)`、`gp.gsva(...)` |
| 你需要自定义背景，或涉及 500+ 个物种 | **带自定义域的 ORA** | g:Profiler(`domain_scope='custom'`) |
| 你想要 TF / 信号通路*活性*(PROGENy、DoRothEA) | 活性推断 | 见 `references/databases-and-gene-sets.md`(decoupler) |

拿不准时:有阈值的列表 → ORA;带分数的排序表 → GSEA。绝不要先对一份列表设阈值，再把它喂给 GSEA——那会丢弃掉 GSEA 所依赖的排序信息。

## 环境设置

```bash
uv pip install gseapy gprofiler-official
# gseapy pulls pandas, numpy, scipy, matplotlib. Network access is needed for
# Enrichr, g:Profiler, and MSigDB downloads. For fully offline ORA, use a local
# GMT file with gp.enrich() (see references/gseapy.md).
```

核实并列出可用的基因集库(库名会随时间变化——绝不要盲目硬编码):

```python
import gseapy as gp
names = gp.get_library_name(organism="human")   # 200+ Enrichr libraries
print([n for n in names if "Reactome" in n or "KEGG" in n or "Hallmark" in n])
```

## 快速开始

### 在命中列表上做 ORA(gseapy + Enrichr)

```python
import gseapy as gp

# Enrichr libraries expect HGNC gene SYMBOLS (human: UPPERCASE). Map IDs first if needed.
genes = [g.strip() for g in open("deg_symbols.txt") if g.strip()]

enr = gp.enrichr(
    gene_list=genes,
    gene_sets=["MSigDB_Hallmark_2020", "GO_Biological_Process_2023",
               "KEGG_2021_Human", "Reactome_2022"],
    organism="human",
    outdir=None,            # in-memory; set a path to also write tables/plots
)
res = enr.results
sig = res[res["Adjusted P-value"] < 0.05].sort_values("Adjusted P-value")
print(sig[["Gene_set", "Term", "Overlap", "Adjusted P-value", "Combined Score", "Genes"]].head(20))
```

### 从 DESeq2 结果做预排序 GSEA

```python
import gseapy as gp
import pandas as pd

res = pd.read_csv("deseq2_results.csv", index_col=0)   # index = gene symbols
# Rank by the test statistic (sign = direction, magnitude = evidence). This is
# more stable than ranking by log2FoldChange, which is noisy for low-count genes.
rnk = res["stat"].dropna().sort_values(ascending=False)
rnk.index = rnk.index.str.upper()
rnk = rnk[~rnk.index.duplicated(keep="first")]

pre = gp.prerank(
    rnk=rnk,
    gene_sets=["MSigDB_Hallmark_2020", "GO_Biological_Process_2023"],
    min_size=15, max_size=500,        # drop tiny/huge sets (noisy or generic)
    permutation_num=1000, seed=123,   # seed = reproducible p-values
    threads=4, outdir=None,
)
out = pre.res2d.sort_values("FDR q-val")
print(out[["Term", "ES", "NES", "NOM p-val", "FDR q-val", "Lead_genes"]].head(20))
```

如果你没有 `stat` 列，可以用 `sign(log2FoldChange) * -log10(pvalue)` 构建排序分数。

## 核心工作流

要做出一个经得起推敲的分析，请按以下步骤逐一进行。中间几步(ID 类型、背景集合)是结果最容易悄悄出错的地方。

### 第 1 步——确定输入并选择方法
明确:哪些基因、什么物种、是否有每个基因的分数(→ GSEA)还是仅有一份列表(→ ORA),以及它们代表什么比较(方向性会影响解读)。

### 第 2 步——把基因 ID 转换到正确的命名空间
Enrichr/MSigDB 的基因集库以**基因符号**（gene symbols）为键(人类为大写，小鼠为首字母大写)。如果你手头是 Ensembl/Entrez ID,请先转换。见 `references/databases-and-gene-sets.md` 中关于 `gp.Biomart`、g:Profiler 的 `g:Convert` 以及 `mygene` 的说明。ID 的悄然不匹配是导致"什么都不显著"的头号原因。

### 第 3 步——选择与问题匹配的基因集库
Hallmark(宽泛主题)→ GO:BP(机制)→ KEGG/Reactome/WikiPathways(精编通路)→ C7(免疫)等。不要一口气跑 50 个库；挑选 2-4 个与生物学问题相符的库。目录与选择指南见 `references/databases-and-gene-sets.md`。

### 第 4 步——设置背景集合(仅 ORA)
背景集合必须是你的检测中*有可能*被检出的那些基因(例如所有被表达/被检测的基因),而不是整个基因组。错误的背景会使显著性虚高。Enrichr 使用固定的背景；当背景很重要时，用 g:Profiler 的 `domain_scope='custom'` + 你的 `background`,或者用 `gp.enrich()` 加显式背景。原理见 `references/interpretation.md`。

### 第 5 步——运行分析
使用"快速开始"中的模式，或使用打包好的 `scripts/run_enrichment.py`。对于 GSEA,始终设置一个 `seed`,并报告 `permutation_num`。

### 第 6 步——按校正后的 p 值过滤
使用 `Adjusted P-value`(ORA,Benjamini–Hochberg 校正)或 `FDR q-val`(GSEA),而不是原始 p 值。典型阈值是 0.05;同时也要检查重叠/基因数量，以免出现"命中"实际只是 1 个基因落在一个 2000 个基因的基因集里这种情况。

### 第 7 步——可视化
点图(dotplot)、条形图、富集图(enrichment map)以及 GSEA 的运行分数图,gseapy 都内置了(`gp.dotplot`、`gp.barplot`、`gp.enrichment_map`、`gp.gseaplot`)。见 `references/gseapy.md`。

### 第 8 步——降低冗余并解读
GO 尤其会返回许多近乎重复的词条。用富集图(词条-词条相似度)、leading-edge 重叠或父词条来做合并，并报告有代表性的词条。解读框架和发表用表格格式见 `references/interpretation.md`。

## 辅助脚本

`scripts/run_enrichment.py` 端到端地运行 ORA 或 GSEA,并输出一份结果表加一张点图，处理了所有琐碎工作(符号清理、去重、去除 NA、从 DESeq2 表构建排序，以及按库过滤 FDR)。

```bash
# ORA from a hit list (one gene symbol per line)
python scripts/run_enrichment.py ora \
  --genes deg_symbols.txt \
  --libraries MSigDB_Hallmark_2020 GO_Biological_Process_2023 KEGG_2021_Human \
  --organism human --outdir results/

# Preranked GSEA from a DESeq2 results CSV (auto-builds the rank from `stat`)
python scripts/run_enrichment.py gsea \
  --deseq2 deseq2_results.csv \
  --libraries MSigDB_Hallmark_2020 GO_Biological_Process_2023 \
  --organism human --outdir results/ --seed 123

# Preranked GSEA from an explicit 2-column rank file (gene,score)
python scripts/run_enrichment.py gsea --rnk ranked_genes.csv --outdir results/
```

运行 `python scripts/run_enrichment.py --help` 查看所有选项(背景文件、FDR 阈值、最小/最大集合大小、置换次数)。

## 常见坑点

以下情形是导致结果错误或不可复现的主要原因:

1. **基因 ID / 物种不匹配** —— 符号 vs Ensembl、人类 vs 小鼠的大小写。要正确地转换 ID 并设置 `organism`,否则匹配会悄悄地降到接近零。
2. **背景错误(ORA)** —— 用整个基因组代替被检测/被表达的基因集会使 p 值虚高。当背景重要时，设置自定义背景。
3. **在 GSEA 之前设阈值** —— GSEA 需要的是*完整的*排序列表；只有 ORA 才使用被截断的列表。
4. **仅用 log2FoldChange 对 GSEA 排序** —— 对低表达量基因不稳定；优先使用 `stat` 或 `sign(LFC) * -log10(p)`。
5. **跨多个库的多重检验** —— FDR 是在*单个*库*内部*计算的；跑多个库相当于放大了检验次数。按库报告 FDR,并保持保守。
6. **冗余的 GO 词条** —— 不要报告同一个词条的 40 个变体；进行合并并展示代表性词条。
7. **显著≠相关** —— 检查重叠数量和基因集大小；很小的基因集很容易凭借偶然达到显著。
8. **列表对 ORA 而言太短/太长** —— 少于 10 个基因效力不足；超过 2000 个会失去特异性(此时应考虑 GSEA)。
9. **没有可重复性元数据** —— Enrichr/GO 的库是有版本、且随时间漂移的。记录库名+日期，并为 GSEA 设置 `seed`。

## 与其他技能的集成

- **上游(基因来自哪里)**: `pydeseq2`(DE 基因 + 用于 GSEA 的 `stat`)、`scanpy`(`rank_genes_groups` 标记基因/分数)、`depmap`/`pytdc`(筛选命中)、蛋白质组学技能(`pyopenms`、`matchms`)。
- **数据库/ID**: `database-lookup`(Reactome、KEGG、STRING、Gene Ontology API)、`gget`(`gget enrichr` 快速路径、`gget info` 用于 ID 映射)、`bioservices`。
- **下游**: `scientific-visualization`(定制图表)、`networkx`(富集图的图结构)、`scientific-writing` / `literature-review`(解读与引用)、`statistical-analysis`(多重检验细节)。

## 参考文件

需要深入时阅读相应的文件:

- `references/gseapy.md` —— 完整的 gseapy API:`enrichr`、离线的 `enrich`、`prerank`、`gsea`、`ssgsea`、`gsva`、`Msigdb`、`Biomart`、`get_library_name`/`read_gmt`、每一种图、结果列的含义、GMT/离线用法，以及故障排查(限流、空结果)。
- `references/databases-and-gene-sets.md` —— GO、KEGG、Reactome、WikiPathways、MSigDB 各集合、Enrichr 库命名、g:Profiler 数据来源、物种处理、基因 ID 转换、按问题选库，以及指向 Reactome/STRING API 和 decoupler 活性推断的指引。
- `references/interpretation.md` —— ORA vs GSEA 的统计学、背景集合的选择、多重检验方法(BH vs g:SCS vs Bonferroni)、leading-edge 基因、冗余度削减、效应量 vs 显著性、发表用表格模板，以及可重复性核对清单。

## 资源

- gseapy 文档: https://gseapy.readthedocs.io/ · 仓库: https://github.com/zqfang/GSEApy
- g:Profiler: https://biit.cs.ut.ee/gprofiler/ · Python 客户端: https://pypi.org/project/gprofiler-official/
- Enrichr: https://maayanlab.cloud/Enrichr/ · MSigDB: https://www.gsea-msigdb.org/gsea/msigdb/
- GSEA 方法: Subramanian et al. (2005) PNAS, DOI: 10.1073/pnas.0506580102
