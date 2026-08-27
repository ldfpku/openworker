# scikit-bio

## 概述

scikit-bio 是一个用于处理生物数据的综合性 Python 库。当需要进行涵盖序列操作、比对、系统发生学（phylogenetics）以及微生物生态学和多变量统计的生物信息学分析时，应用此技能。

## 何时使用此技能

当用户出现以下情况时应使用此技能：
- 处理生物序列（DNA、RNA、蛋白质）
- 需要读写生物文件格式（FASTA、FASTQ、GenBank、Newick、BIOM 等）
- 执行序列比对或搜索基序（motif）
- 构建或分析系统发生树（phylogenetic tree）
- 计算多样性指标（alpha/beta 多样性、UniFrac 距离）
- 执行排序分析（PCoA、CCA、RDA）
- 对生物学/生态学数据运行统计检验（PERMANOVA、ANOSIM、Mantel）
- 分析微生物组或群落生态学数据
- 处理来自语言模型的蛋白质嵌入（embedding）
- 需要操作生物数据表

## 核心能力

### 1. 序列操作

使用针对 DNA、RNA 和蛋白质数据的专用类来处理生物序列。

**关键操作**：
- 从 FASTA、FASTQ、GenBank、EMBL 格式读写序列
- 序列切片、拼接和搜索
- 反向互补（reverse complement）、转录（DNA→RNA）和翻译（RNA→蛋白质）
- 使用正则表达式查找基序和模式
- 计算距离（Hamming、基于 k-mer）
- 处理序列质量分数和元数据

**常见用法**：
```python
import skbio

# Read sequences from file
seq = skbio.DNA.read('input.fasta')

# Sequence operations
rc = seq.reverse_complement()
rna = seq.transcribe()
protein = rna.translate()

# Find motifs
motif_positions = seq.find_with_regex('ATG[ACGT]{3}')

# Check for properties
has_degens = seq.has_degenerates()
seq_no_gaps = seq.degap()
```

**重要说明**：
- 使用 `DNA`、`RNA`、`Protein` 类来处理带语法（grammared）验证的序列
- 使用 `Sequence` 类来处理不限制字母表的通用序列
- 质量分数会自动从 FASTQ 文件加载到位置元数据（positional metadata）中
- 元数据类型：序列级（ID、描述）、位置级（每个碱基）、区间级（区域/特征）

### 2. 序列比对

使用 `pair_align` 引擎（在 scikit-bio 0.7.0 中引入）执行成对（pairwise）和多序列比对，这是一个多功能且高效的动态规划比对器。

**关键能力**：
- 在一个函数中提供全局（global）、局部（local）和半全局（semi-global，端点可配置）比对
- 便捷封装函数 `pair_align_nucl`（类 BLASTN）和 `pair_align_prot`（类 BLASTP）
- 可配置打分方式：匹配/错配元组或命名的替换矩阵；线性或仿射（affine）罚分
- `PairAlignPath` 结果携带 CIGAR 字符串，并可转换为已比对序列
- 使用 `TabularMSA` 进行多序列比对存储和操作

**常见用法**：
```python
from skbio import DNA, Protein
from skbio.alignment import pair_align_nucl, pair_align_prot, pair_align, TabularMSA

# Nucleotide alignment with BLASTN-like defaults
seq1, seq2 = DNA('ACTACCAGATTACTTACGGATCAGG'), DNA('CGAAACTACTAGATTACGGATCTTA')
aln = pair_align_nucl(seq1, seq2)
aln.score                                  # alignment score (float)
path = aln.paths[0]                        # PairAlignPath (repr shows CIGAR)
aligned_seqs = path.to_aligned((seq1, seq2))  # list of gapped strings

# Build a TabularMSA from the alignment path + original sequences
msa = TabularMSA.from_path_seqs(path, (seq1, seq2))

# Customize the algorithm via pair_align (default mode='global')
aln = pair_align(seq1, seq2, mode='local')                       # Smith-Waterman
aln = pair_align(seq1, seq2, sub_score=(2, -3), gap_cost=(5, 2)) # affine gaps
aln = pair_align(seq1, seq2, sub_score='NUC.4.4', gap_cost=3)    # substitution matrix, linear gap

# Protein alignment (BLASTP-like, BLOSUM62)
aln = pair_align_prot(Protein('HEAGAWGHEE'), Protein('PAWHEAE'))

# Read a multiple alignment from file and summarize
msa = TabularMSA.read('alignment.fasta', constructor=DNA)
consensus = msa.consensus()
```

**重要说明**：
- `pair_align` 取代了已移除的 SSW 封装（`local_pairwise_align_ssw`、`StripedSmithWaterman`）以及已弃用的纯 Python 比对器（`global_pairwise_align`、`local_pairwise_align_nucleotide` 等）
- 结果是一个 `PairAlignResult`，同时可解包为 `score, paths, matrices`（使用 `keep_matrices=True` 保留动态规划矩阵）
- `sub_score` 接受 `(match, mismatch)` 元组或矩阵名称（例如 `'NUC.4.4'`、`'BLOSUM62'`）；`gap_cost` 接受单个数值（线性）或 `(open, extend)` 元组（仿射）
- 使用 `PairAlignPath.from_cigar('1I8M2D5M2I')` 解析外部 CIGAR 字符串；用 `align_score(...)` 为已有比对打分，用 `align_dists(...)` 从 MSA 构建距离矩阵

### 3. 系统发生树

构建、操作和分析表示进化关系的系统发生树（phylogenetic tree）。

**关键能力**：
- 从距离矩阵构建树（UPGMA/WPGMA、邻接法 Neighbor Joining、GME、BME）
- 使用最近邻交换（`nni`）进行树的重排
- 树操作（剪枝、重新生根、遍历）
- 距离计算（通过 `cophenet` 计算亲缘距离 patristic，通过 `compare_rfd` 计算 Robinson-Foulds 距离）
- ASCII 可视化
- Newick 格式的读写

**常见用法**：
```python
from skbio import TreeNode
from skbio.tree import nj, upgma, gme, bme, rf_dists

# Read tree from file
tree = TreeNode.read('tree.nwk')

# Construct tree from distance matrix
tree = nj(distance_matrix)

# Tree operations
subtree = tree.shear(['taxon1', 'taxon2', 'taxon3'])
tips = [node for node in tree.tips()]
lca = tree.lca(['taxon1', 'taxon2'])

# Calculate distances
patristic_dist = tree.find('taxon1').distance(tree.find('taxon2'))
cophenetic_dm = tree.cophenet()           # patristic distance matrix among tips

# Compare two trees (Robinson-Foulds)
rf_distance = tree.compare_rfd(other_tree)
# Pairwise RF distances among many trees -> DistanceMatrix
rf_dm = rf_dists([tree, other_tree, third_tree])
```

**重要说明**：
- 使用 `nj()` 进行邻接法（neighbor joining，经典的系统发生学方法）
- 使用 `upgma()` 进行 UPGMA/WPGMA（假设存在分子钟）
- GME 和 BME 对大型树具有高度可扩展性；用 `nni()` 优化拓扑结构
- `cophenet()`（原名 `tip_tip_distances`）返回亲缘距离矩阵；`compare_rfd()` 是 Robinson-Foulds 方法（`compare_wrfd`/`compare_cophenet` 分别对应加权/协表型变体）
- `lca()` 是最近共同祖先（lowest common ancestor）；`lowest_common_ancestor` 仍作为别名保留
- 树可以是有根的或无根的；某些指标需要特定的生根方式

### 4. 多样性分析

为微生物生态学和群落分析计算 alpha 和 beta 多样性指标。

**关键能力**：
- Alpha 多样性：丰富度（`sobs`、`observed_features`、`chao1`、`ace`）、Shannon 指数、Simpson 指数、Hill 数（`hill`）、Faith's PD、广义 PD（`phydiv`）、Pielou 均匀度
- Beta 多样性：Bray-Curtis、Jaccard、加权/非加权 UniFrac、欧氏距离
- 系统发生多样性指标（需要输入树）
- 稀释化（rarefaction）和子抽样
- 与排序分析和统计检验的集成

**常见用法**：
```python
from skbio.diversity import alpha_diversity, beta_diversity

# Alpha diversity (phylogenetic metrics take taxa= for tip-name mapping)
alpha = alpha_diversity('shannon', counts_matrix, ids=sample_ids)
faith_pd = alpha_diversity('faith_pd', counts_matrix, ids=sample_ids,
                           tree=tree, taxa=feature_ids)

# Beta diversity
bc_dm = beta_diversity('braycurtis', counts_matrix, ids=sample_ids)
unifrac_dm = beta_diversity('unweighted_unifrac', counts_matrix,
                            ids=sample_ids, tree=tree, taxa=feature_ids)

# Get available metrics
from skbio.diversity import get_alpha_diversity_metrics
print(get_alpha_diversity_metrics())
```

**重要说明**：
- 计数值必须是表示丰度的整数，而非相对频率
- 系统发生学指标的参数名为 `taxa=`（在 0.6.0 中由 `otu_ids` 重命名而来，旧名称作为已弃用别名保留）；`observed_otus` 现已改名为 `observed_features`（或 `sobs`）
- `counts_matrix` 可以通过分派（dispatch）系统接受任意类表格输入（NumPy 数组、pandas/polars DataFrame、BIOM `Table` 或 AnnData）
- 系统发生学指标（Faith's PD、UniFrac）需要提供树以及分类单元到树尖（tip）的映射
- 对特定样本对使用 `partial_beta_diversity()`，对大型分块计算使用 `block_beta_diversity()`
- Alpha 多样性返回 `pandas.Series`，beta 多样性返回 `DistanceMatrix`

### 5. 排序方法

将高维生物数据降维到可可视化的低维空间。

**关键能力**：
- 从距离矩阵进行 PCoA（主坐标分析，Principal Coordinate Analysis）
- 针对列联表的 CA（对应分析，Correspondence Analysis）
- 带环境约束的 CCA（典范对应分析，Canonical Correspondence Analysis）
- 用于线性关系的 RDA（冗余分析，Redundancy Analysis）
- 用于特征解释的双标图（biplot）投影

**常见用法**：
```python
from skbio.stats.ordination import pcoa, cca
import skbio

# PCoA from distance matrix (limit dimensions for large matrices)
pcoa_results = pcoa(distance_matrix, dimensions=3)
pc1 = pcoa_results.samples['PC1']
pc2 = pcoa_results.samples['PC2']

# Built-in scatter plot colored by a metadata column
fig = pcoa_results.plot(sample_metadata, column='bodysite')

# CCA with environmental variables
cca_results = cca(species_matrix, environmental_matrix)

# Save/load ordination results
pcoa_results.write('ordination.txt')
results = skbio.OrdinationResults.read('ordination.txt')
```

**重要说明**：
- PCoA 可用于任意距离/差异（dissimilarity）矩阵；`dimensions` 参数可传入整数（数量）或 (0, 1] 之间的浮点数（要保留的累计方差比例）
- `OrdinationResults` 提供基于 pandas 的属性：`samples`、`features`、`eigvals`、`proportion_explained`、`biplot_scores`、`sample_constraints`
- CCA 可揭示驱动群落组成的环境因素
- `OrdinationResults.plot()` 生成 matplotlib 图形；结果也可与 seaborn/plotly 集成

### 6. 统计检验

对生态学和生物学数据执行专用的假设检验。

**关键能力**：
- PERMANOVA：使用距离矩阵检验组间差异
- ANOSIM：检验组间差异的另一种方法
- PERMDISP：检验组间离散度的同质性
- Mantel 检验：距离矩阵之间的相关性
- Bioenv：寻找与距离相关的环境变量
- 差异丰度分析：`skbio.stats.composition` 中的 `ancom`、`dirmult_ttest` 以及（纵向混合效应的）`dirmult_lme`

**常见用法**：
```python
from skbio.stats.distance import permanova, anosim, mantel

# Test if groups differ significantly
permanova_results = permanova(distance_matrix, grouping, permutations=999)
print(f"p-value: {permanova_results['p-value']}")

# ANOSIM test
anosim_results = anosim(distance_matrix, grouping, permutations=999)

# Mantel test between two distance matrices
mantel_results = mantel(dm1, dm2, method='pearson', permutations=999)
print(f"Correlation: {mantel_results[0]}, p-value: {mantel_results[1]}")

# Differential abundance on a feature table (raw counts recommended)
from skbio.stats.composition import dirmult_ttest
da = dirmult_ttest(counts_table, grouping, treatment='caseA', reference='control')
```

**重要说明**：
- 置换检验提供非参数的显著性检验
- 使用 999 次以上的置换以获得稳健的 p 值
- PERMANOVA 对离散度差异敏感；应与 PERMDISP 配合使用
- Mantel 检验评估矩阵之间的相关性（例如地理距离与遗传距离）
- 为保留数量级信息，差异丰度检验应提供原始计数值，而非预先归一化的比例

### 7. 文件输入输出与格式转换

支持 19 种以上生物文件格式的读写，并具备自动格式检测功能。

**支持的格式**：
- 序列：FASTA、FASTQ、GenBank、EMBL、QSeq
- 比对：Clustal、PHYLIP、Stockholm
- 树：Newick
- 表格：BIOM（HDF5 和 JSON）
- 距离：分隔符分隔的方阵
- 分析：BLAST+6/7、GFF3、排序结果
- 元数据：带校验的 TSV/CSV

**常见用法**：
```python
import skbio

# Read with automatic format detection
seq = skbio.DNA.read('file.fasta', format='fasta')
tree = skbio.TreeNode.read('tree.nwk')

# Write to file
seq.write('output.fasta', format='fasta')

# Generator for large files (memory efficient)
for seq in skbio.io.read('large.fasta', format='fasta', constructor=skbio.DNA):
    process(seq)

# Convert formats
seqs = list(skbio.io.read('input.fastq', format='fastq', constructor=skbio.DNA))
skbio.io.write(seqs, format='fasta', into='output.fasta')
```

**重要说明**：
- 对大文件使用生成器（generator）以避免内存问题
- 指定 `into` 参数时可自动检测格式
- 部分对象可以写入多种格式
- 支持通过 `verify=False` 进行 stdin/stdout 管道传输

### 8. 距离矩阵

使用统计方法创建和操作距离/差异（dissimilarity）矩阵。

**关键能力**：
- 存储对称矩阵（`DistanceMatrix`，对角线为零）或一般成对（`PairwiseMatrix`）数据
- 基于 ID 的索引和切片
- 与多样性分析、排序分析和统计检验集成
- 分隔符分隔文本格式的读写

**常见用法**：
```python
from skbio import DistanceMatrix
import numpy as np

# Create from array
data = np.array([[0, 1, 2], [1, 0, 3], [2, 3, 0]])
dm = DistanceMatrix(data, ids=['A', 'B', 'C'])

# Access distances
dist_ab = dm['A', 'B']
row_a = dm['A']

# Read from file
dm = DistanceMatrix.read('distances.txt')

# Use in downstream analyses
pcoa_results = pcoa(dm)
permanova_results = permanova(dm, grouping)
```

**重要说明**：
- `DistanceMatrix` 强制要求对称性和零（中空）对角线；它是 `SymmetricMatrix` 的子类
- `PairwiseMatrix`（由 `DissimilarityMatrix` 重命名而来，后者作为已弃用别名保留）允许一般/非对称数值
- ID 便于与元数据和生物学知识集成
- 与 pandas、numpy 和 scikit-learn 兼容

### 9. 生物学表格

处理微生物组研究中常见的特征表（OTU/ASV 表）。

**关键能力**：
- 通过原生 `Table` 类实现 BIOM 格式（HDF5 和 JSON）的读写
- 表格分派（dispatch）系统（0.7.0 及以上版本）：函数可接受任意 `table_like` 输入——BIOM `Table`、pandas/polars DataFrame、NumPy 数组或 AnnData——无需显式转换
- 数据增强技术（`phylomix`、`mixup`、`aitchison_mixup`、`compos_cutmix`）
- 样本/特征的筛选和归一化
- 元数据集成

**常见用法**：
```python
from skbio import Table
from skbio.diversity import beta_diversity

# Read BIOM table
table = Table.read('table.biom')

# Access data
sample_ids = table.ids(axis='sample')
feature_ids = table.ids(axis='observation')
counts = table.matrix_data

# Filter
filtered = table.filter(sample_ids_to_keep, axis='sample')

# Pass table-like objects directly to scikit-bio drivers (dispatch system)
import pandas as pd
df = pd.read_table('data.tsv', index_col=0)   # samples x features
bdiv = beta_diversity('braycurtis', df)         # no manual conversion needed
```

**重要说明**：
- BIOM 表是 QIIME 2 工作流中的标准格式
- 行通常代表样本，列通常代表特征（OTU/ASV）
- 支持稀疏和密集两种表示方式
- 借助分派系统，函数返回与其输入相同的格式，或用户指定的输出格式

### 10. 蛋白质嵌入

处理来自蛋白质语言模型的嵌入（embedding），用于下游分析。

**关键能力**：
- 存储来自蛋白质语言模型（ESM、ProtTrans 等）的嵌入
- 将嵌入转换为距离矩阵
- 生成用于可视化的排序对象
- 导出为 numpy/pandas 供机器学习工作流使用

**常见用法**：
```python
from skbio.embedding import ProteinEmbedding, ProteinVector

# Create embedding from array
embedding = ProteinEmbedding(embedding_array, sequence_ids)

# Convert to distance matrix for analysis
dm = embedding.to_distances(metric='euclidean')

# PCoA visualization of embedding space
pcoa_results = embedding.to_ordination(metric='euclidean', method='pcoa')

# Export for machine learning
array = embedding.to_array()
df = embedding.to_dataframe()
```

**重要说明**：
- 嵌入在蛋白质语言模型与传统生物信息学之间架起桥梁
- 与 scikit-bio 的距离/排序/统计生态系统兼容
- SequenceEmbedding 和 ProteinEmbedding 提供专门的功能
- 适用于序列聚类、分类和可视化

## 最佳实践

### 安装
```bash
uv pip install scikit-bio
```
需要 Python 3.10+ 和 NumPy 2.0+。自 0.7.0 版本起每个发行版都会发布预编译的 wheel 包，因此大多数平台无需编译器即可安装。Conda 用户也可以运行 `conda install -c conda-forge scikit-bio`。

### 性能考量
- 对大型序列文件使用生成器以最小化内存占用
- 对于超大型系统发生树，优先使用 GME 或 BME 而非 NJ
- Beta 多样性计算可以通过 `partial_beta_diversity()` 并行化
- BIOM 格式（HDF5）对大型表格比 JSON 更高效

### 与生态系统的集成
- 序列通过标准格式与 Biopython 互操作
- 表格与 pandas、polars 和 AnnData 集成
- 距离矩阵与 scikit-learn 兼容
- 排序结果可用 matplotlib/seaborn/plotly 可视化
- 与 QIIME 2 制品（BIOM、树、距离矩阵）无缝协作

### 常见工作流
1. **微生物组多样性分析**：读取 BIOM 表 → 计算 alpha/beta 多样性 → 排序分析（PCoA）→ 统计检验（PERMANOVA）
2. **系统发生分析**：读取序列 → 比对 → 构建距离矩阵 → 构建树 → 计算系统发生距离
3. **序列处理**：读取 FASTQ → 质量过滤 → 修剪/清洗 → 查找基序 → 翻译 → 写出 FASTA
4. **比较基因组学**：读取序列 → 成对比对 → 计算距离 → 构建树 → 分析分支（clade）

## 参考文档

有关详细的 API 信息、参数规范和进阶用法示例，请参阅 `references/api_reference.md`，其中包含以下全面的文档：
- 所有功能的完整方法签名和参数
- 复杂工作流的扩展代码示例
- 常见问题的排查方法
- 性能优化技巧
- 与其他库的集成模式

## 附加资源

- 官方文档：https://scikit.bio/docs/latest/
- GitHub 仓库：https://github.com/scikit-bio/scikit-bio
- 更新日志：https://github.com/scikit-bio/scikit-bio/blob/main/CHANGELOG.md
- 参考论文："scikit-bio: a fundamental Python library for biological omic data," *Nature Methods* (2025), https://www.nature.com/articles/s41592-025-02981-z
- 论坛支持：<https://forum.qiime2.org>（scikit-bio 是 QIIME 2 生态系统的一部分）
