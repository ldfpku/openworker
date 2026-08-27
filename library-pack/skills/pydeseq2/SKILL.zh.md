# PyDESeq2

## 概览

PyDESeq2 是 DESeq2 的 Python 实现，用于对批量 RNA-seq 数据进行差异表达分析。设计并执行从数据加载到结果解读的完整工作流程，包括公式化(formulaic)的单因素与多因素设计、带多重检验校正的 Wald 检验、可选的 apeGLM 收缩(shrinkage),以及与 pandas 和 AnnData 的集成。

## 何时使用本技能

在以下情形应当使用本技能:
- 对批量 RNA-seq 计数数据进行差异表达分析
- 比较实验条件之间(例如处理组 vs 对照组)的基因表达
- 进行考虑批次效应或协变量的多因素设计
- 将基于 R 的 DESeq2 工作流程转换为 Python
- 将差异表达分析集成到基于 Python 的流水线中
- 用户提到 "DESeq2"、"differential expression"、"RNA-seq analysis" 或 "PyDESeq2"

## 快速开始工作流程

对于想要进行标准差异表达分析的用户:

```python
import pandas as pd
from pydeseq2.dds import DeseqDataSet
from pydeseq2.default_inference import DefaultInference
from pydeseq2.ds import DeseqStats

# 1. Load data
counts_df = pd.read_csv("counts.csv", index_col=0).T  # Transpose to samples × genes
metadata = pd.read_csv("metadata.csv", index_col=0)

# 2. Filter low-count genes
genes_to_keep = counts_df.columns[counts_df.sum(axis=0) >= 10]
counts_df = counts_df[genes_to_keep]

# 3. Make the reference level explicit and fit DESeq2
metadata["condition"] = pd.Categorical(
    metadata["condition"], categories=["control", "treated"]
)
inference = DefaultInference(n_cpus=4)
dds = DeseqDataSet(
    counts=counts_df,
    metadata=metadata,
    design="~condition",
    refit_cooks=True,
    inference=inference,
)
dds.deseq2()

# 4. Perform statistical testing
ds = DeseqStats(
    dds,
    contrast=["condition", "treated", "control"],
    inference=inference,
)
ds.summary()

# 5. Access results
results = ds.results_df
significant = results[results.padj < 0.05]
print(f"Found {len(significant)} significant genes")
```

## 核心工作流程步骤

六个步骤(含代码)见
[references/core_workflow_steps.md](references/core_workflow_steps.md):

1. **数据准备** —— 原始整数计数，基因作为列、样本作为行，并配有匹配的元数据。切勿将归一化或经过变换的值喂给 DESeq2。
2. **设计公式(design)指定** —— 设计因子，以及每个因子的参考水平(reference level)。
3. **DESeq2 拟合** —— 大小因子(size factors)、离散度(dispersions)以及 GLM 拟合。
4. **统计检验** —— 针对指定对照(contrast)进行 Wald 检验。
5. **可选的 LFC 收缩(shrinkage)** —— 用于排序和可视化。
6. **结果导出** —— 带有校正后 p 值的结果表。

多因素设计、对照设定以及交互项见
[references/analysis_patterns.md](references/analysis_patterns.md)。

## 使用分析脚本

本技能包含一个用于标准分析的完整命令行脚本:

```bash
# Basic usage
python scripts/run_deseq2_analysis.py \
  --counts counts.csv \
  --metadata metadata.csv \
  --design "~condition" \
  --contrast condition treated control \
  --output results/

# With additional options
python scripts/run_deseq2_analysis.py \
  --counts counts.csv \
  --metadata metadata.csv \
  --design "~batch + condition" \
  --contrast condition treated control \
  --output results/ \
  --min-counts 10 \
  --alpha 0.05 \
  --n-cpus 4 \
  --shrink-coeff "condition[T.treated]" \
  --plots
```

**脚本特性**:
- 自动数据加载与校验
- 基因和样本过滤
- 完整的 DESeq2 流水线执行
- 带可自定义参数的统计检验
- 结果导出(CSV 及可移植的 AnnData/H5AD)
- 显式支持 PyDESeq2 0.5.x 的 LFC 收缩系数
- 可选的可视化(火山图和 MA 图)

当用户需要独立的分析工具，或想要批量处理多个数据集时，把他们指向 `scripts/run_deseq2_analysis.py`。

## 结果解读

### 识别显著基因

```python
# Filter by adjusted p-value
significant = ds.results_df[ds.results_df.padj < 0.05]

# Filter by both significance and effect size
sig_and_large = ds.results_df[
    (ds.results_df.padj < 0.05) &
    (abs(ds.results_df.log2FoldChange) > 1)
]

# Separate up- and down-regulated
upregulated = significant[significant.log2FoldChange > 0]
downregulated = significant[significant.log2FoldChange < 0]

print(f"Upregulated: {len(upregulated)}")
print(f"Downregulated: {len(downregulated)}")
```

### 排序

```python
# Sort by adjusted p-value
top_by_padj = ds.results_df.sort_values("padj").head(20)

# Sort by absolute fold change (use shrunk values)
ds.lfc_shrink(coeff="condition[T.treated]")
ds.results_df["abs_lfc"] = abs(ds.results_df.log2FoldChange)
top_by_lfc = ds.results_df.sort_values("abs_lfc", ascending=False).head(20)

# Sort by a combined metric
ds.results_df["score"] = -np.log10(ds.results_df.padj) * abs(ds.results_df.log2FoldChange)
top_combined = ds.results_df.sort_values("score", ascending=False).head(20)
```

### 质量指标

```python
# Check normalization (size factors should be close to 1)
print("Size factors:", dds.obs["size_factors"])

# Examine dispersion estimates
import matplotlib.pyplot as plt
plt.hist(dds.var["dispersions"], bins=50)
plt.xlabel("Dispersion")
plt.ylabel("Frequency")
plt.title("Dispersion Distribution")
plt.show()

# Check p-value distribution (should be mostly flat with peak near 0)
plt.hist(ds.results_df.pvalue.dropna(), bins=50)
plt.xlabel("P-value")
plt.ylabel("Frequency")
plt.title("P-value Distribution")
plt.show()
```

## 可视化指南

### 火山图(Volcano Plot)

可视化显著性与效应量的关系:

```python
import matplotlib.pyplot as plt
import numpy as np

results = ds.results_df.copy()
results["-log10(padj)"] = -np.log10(results.padj)

plt.figure(figsize=(10, 6))
significant = results.padj < 0.05

plt.scatter(
    results.loc[~significant, "log2FoldChange"],
    results.loc[~significant, "-log10(padj)"],
    alpha=0.3, s=10, c='gray', label='Not significant'
)
plt.scatter(
    results.loc[significant, "log2FoldChange"],
    results.loc[significant, "-log10(padj)"],
    alpha=0.6, s=10, c='red', label='padj < 0.05'
)

plt.axhline(-np.log10(0.05), color='blue', linestyle='--', alpha=0.5)
plt.xlabel("Log2 Fold Change")
plt.ylabel("-Log10(Adjusted P-value)")
plt.title("Volcano Plot")
plt.legend()
plt.savefig("volcano_plot.png", dpi=300)
```

### MA 图(MA Plot)

展示倍数变化与平均表达量的关系:

```python
plt.figure(figsize=(10, 6))

plt.scatter(
    np.log10(results.loc[~significant, "baseMean"] + 1),
    results.loc[~significant, "log2FoldChange"],
    alpha=0.3, s=10, c='gray'
)
plt.scatter(
    np.log10(results.loc[significant, "baseMean"] + 1),
    results.loc[significant, "log2FoldChange"],
    alpha=0.6, s=10, c='red'
)

plt.axhline(0, color='blue', linestyle='--', alpha=0.5)
plt.xlabel("Log10(Base Mean + 1)")
plt.ylabel("Log2 Fold Change")
plt.title("MA Plot")
plt.savefig("ma_plot.png", dpi=300)
```

## 常见问题排查

### 数据格式问题

**问题**:「计数矩阵与元数据之间索引不匹配(Index mismatch between counts and metadata)」

**解决方法**: 确保样本名称完全一致
```python
print("Counts samples:", counts_df.index.tolist())
print("Metadata samples:", metadata.index.tolist())

# Take intersection if needed
common = counts_df.index.intersection(metadata.index)
counts_df = counts_df.loc[common]
metadata = metadata.loc[common]
```

**问题**:「所有基因的计数都为零(All genes have zero counts)」

**解决方法**: 检查数据是否需要转置
```python
print(f"Counts shape: {counts_df.shape}")
# If genes > samples, transpose is needed
if counts_df.shape[1] < counts_df.shape[0]:
    counts_df = counts_df.T
```

### 设计矩阵问题

**问题**:「设计矩阵不是满秩的(Design matrix is not full rank)」

**原因**: 变量存在混杂(例如所有处理组样本都在同一批次中)

**解决方法**: 移除存在混杂的变量，或添加交互项
```python
# Check confounding
print(pd.crosstab(metadata.condition, metadata.batch))

# Either simplify design or add interaction
design = "~condition"  # Remove batch
# OR
design = "~condition + batch + condition:batch"  # Model interaction
```

### 没有显著基因

**诊断方法**:
```python
# Check dispersion distribution
plt.hist(dds.var["dispersions"], bins=50)
plt.show()

# Check size factors
print(dds.obs["size_factors"])

# Look at top genes by raw p-value
print(ds.results_df.nsmallest(20, "pvalue"))
```

**可能的原因**:
- 效应量较小
- 生物学变异性较高
- 样本量不足
- 技术性问题(批次效应、离群值)

## 参考文档

如需超出本工作流导向指南的全面细节:

- **API 参考**(`references/api_reference.md`):PyDESeq2 类、方法和数据结构的完整文档。当需要详细的参数信息或理解对象属性时使用。

- **工作流程指南**(`references/workflow_guide.md`):深入的指南，涵盖完整的分析工作流程、数据加载模式、多因素设计、问题排查以及最佳实践。在处理复杂实验设计或遇到问题时使用。

在用户需要以下内容时，将这些参考文件加载到上下文中:
- 详细的 API 文档:`Read references/api_reference.md`
- 全面的工作流程示例:`Read references/workflow_guide.md`
- 问题排查指导:`Read references/workflow_guide.md`(见「问题排查」一节)

## 关键提醒

1. **数据朝向(orientation)很重要**: 计数矩阵通常以基因 × 样本的形式加载，但需要转换为样本 × 基因。如有需要，始终用 `.T` 进行转置。

2. **样本过滤**: 在分析之前移除缺少元数据的样本，以避免报错。

3. **基因过滤**: 过滤低计数基因(例如总 reads 数 < 10),以提高统计功效并减少计算时间。

4. **设计公式的顺序**: 把调整变量放在感兴趣变量之前(例如 `"~batch + condition"` 而不是 `"~condition + batch"`)。

5. **LFC 收缩的时机**: 在统计检验之后再应用收缩(shrinkage),且仅用于可视化/排序目的。p 值仍然基于未经收缩的估计值。

6. **结果解读**: 用 `padj < 0.05` 来判断显著性，而不是原始 p 值。Benjamini-Hochberg 程序用于控制错误发现率(false discovery rate)。

7. **对照(contrast)的指定方式**: 格式为 `[variable, test_level, reference_level]`,其中 test_level 会与 reference_level 进行比较。

8. **保存中间对象**: 优先使用 `dds.to_picklable_anndata().write_h5ad("dds_result.h5ad")` 以获得可移植的输出。只加载你自己创建、并且信任的 pickle 文件。

## 安装与依赖要求

```bash
uv pip install pydeseq2==0.5.4
```

**系统要求**:
- Python 3.11+
- PyDESeq2 0.5.4
- pandas 2.2.0+
- numpy 2.0.0+
- scipy 1.12.0+
- scikit-learn 1.4.0+
- anndata 0.11.0+
- formulaic 1.0.2+ 以及 formulaic-contrasts 0.2.0+

**可视化的可选依赖**:
- matplotlib
- seaborn

## 其他资源

- **官方文档**: https://pydeseq2.readthedocs.io
- **GitHub 仓库**: https://github.com/scverse/PyDESeq2
- **发表文献**: Muzellec et al. (2023) Bioinformatics, DOI: 10.1093/bioinformatics/btad547
- **原始 DESeq2(R 版本)**: Love et al. (2014) Genome Biology, DOI: 10.1186/s13059-014-0550-8
