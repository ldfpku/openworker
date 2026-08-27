# scVelo —— RNA 速率分析

## 概览

scVelo 是用于单细胞 RNA-seq 数据 RNA 速率(RNA velocity)分析的领先 Python 软件包。它通过对 mRNA 剪接动力学建模来推断细胞状态转变——利用未剪接(前 mRNA)与已剪接(成熟 mRNA)丰度的比例，判断某个基因在每个细胞中是被上调还是下调。这使得在不需要时间序列数据的情况下，重建发育轨迹并识别细胞命运决策成为可能。

**安装**: `uv pip install scvelo`

**关键资源**:
- 文档:https://scvelo.readthedocs.io/
- GitHub:https://github.com/theislab/scvelo
- 论文:Bergen et al. (2020) Nature Biotechnology. PMID: 32747759

## 何时使用本技能

在以下情形使用 scVelo:

- **从快照数据进行轨迹推断**:确定细胞正朝哪个方向分化
- **细胞命运预测**:识别祖细胞及其下游命运
- **驱动基因识别**:找出其动力学最能解释所观测轨迹的基因
- **发育生物学**:对造血、神经发生、上皮-间质转化建模
- **潜在时间(latent time)估计**:根据剪接动力学推导出的伪时间对细胞排序
- **作为 Scanpy 的补充**:为 UMAP 嵌入添加方向性信息

## 前提条件

scVelo 需要**未剪接**（unspliced）和**已剪接**（spliced）两种 RNA 的计数矩阵。这些数据由以下工具生成:
1. **STARsolo** 或使用 `lamanno` 模式的 **kallisto|bustools**
2. **velocyto** CLI:`velocyto run10x` / `velocyto run`
3. 输出剪接/未剪接数据的 **alevin-fry** / **simpleaf**

数据存储在一个 `AnnData` 对象中，包含 `layers["spliced"]` 和 `layers["unspliced"]`。

## 标准 RNA 速率工作流程

### 1. 设置与数据加载

```python
import scvelo as scv
import scanpy as sc
import numpy as np
import matplotlib.pyplot as plt

# Configure settings
scv.settings.verbosity = 3       # Show computation steps
scv.settings.presenter_view = True
scv.settings.set_figure_params('scvelo')

# Load data (AnnData with spliced/unspliced layers)
# Option A: Load from loom (velocyto output)
adata = scv.read("cellranger_output.loom", cache=True)

# Option B: Merge velocyto loom with Scanpy-processed AnnData
adata_processed = sc.read_h5ad("processed.h5ad")  # Has UMAP, clusters
adata_velocity = scv.read("velocyto.loom")
adata = scv.utils.merge(adata_processed, adata_velocity)

# Verify layers
print(adata)
# obs × var: N × G
# layers: 'spliced', 'unspliced' (required)
# obsm['X_umap'] (required for visualization)
```

### 2. 预处理

```python
# Filter and normalize. As of scVelo 0.3, filter_and_normalize() only filters
# genes and normalizes per cell -- it no longer takes n_top_genes and no longer
# log-transforms, so the log step and HVG selection come from Scanpy.
scv.pp.filter_and_normalize(
    adata,
    min_shared_counts=20    # Minimum counts in spliced+unspliced
)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000, subset=True)

# Compute first and second order moments (means and variances)
# knn_connectivities must be computed first
sc.pp.neighbors(adata, n_neighbors=30, n_pcs=30)
scv.pp.moments(
    adata,
    n_pcs=30,
    n_neighbors=30
)
```

### 3. 速率估计 —— 随机模型(Stochastic Model)

随机模型速度快，适合探索性分析:

```python
# Stochastic velocity (faster, less accurate)
scv.tl.velocity(adata, mode='stochastic')
scv.tl.velocity_graph(adata)

# Visualize
scv.pl.velocity_embedding_stream(
    adata,
    basis='umap',
    color='leiden',
    title="RNA Velocity (Stochastic)"
)
```

### 4. 速率估计 —— 动力学模型(Dynamical Model,推荐)

动力学模型拟合完整的剪接动力学，精度更高:

```python
# Recover dynamics (computationally intensive; ~10-30 min for 10K cells)
scv.tl.recover_dynamics(adata, n_jobs=4)

# Compute velocity from dynamical model
scv.tl.velocity(adata, mode='dynamical')
scv.tl.velocity_graph(adata)
```

### 5. 潜在时间(Latent Time)

动力学模型能够计算出一个共享的潜在时间(伪时间):

```python
# Compute latent time
scv.tl.latent_time(adata)

# Visualize latent time on UMAP
scv.pl.scatter(
    adata,
    color='latent_time',
    color_map='gnuplot',
    size=80,
    title='Latent time'
)

# Identify top genes ordered by latent time
top_genes = adata.var['fit_likelihood'].sort_values(ascending=False).index[:300]
scv.pl.heatmap(
    adata,
    var_names=top_genes,
    sortby='latent_time',
    col_color='leiden',
    n_convolve=100
)
```

### 6. 驱动基因分析

```python
# Identify genes with highest velocity fit
scv.tl.rank_velocity_genes(adata, groupby='leiden', min_corr=0.3)
df = scv.DataFrame(adata.uns['rank_velocity_genes']['names'])
print(df.head(10))

# Speed and coherence
scv.tl.velocity_confidence(adata)
scv.pl.scatter(
    adata,
    c=['velocity_length', 'velocity_confidence'],
    cmap='coolwarm',
    perc=[5, 95]
)

# Phase portraits for specific genes
scv.pl.velocity(adata, ['Cpe', 'Gnao1', 'Ins2'],
               ncols=3, figsize=(16, 4))
```

### 7. 速率箭头与伪时间

```python
# Arrow plot on UMAP
scv.pl.velocity_embedding(
    adata,
    arrow_length=3,
    arrow_size=2,
    color='leiden',
    basis='umap'
)

# Stream plot (cleaner visualization)
scv.pl.velocity_embedding_stream(
    adata,
    basis='umap',
    color='leiden',
    smooth=0.8,
    min_mass=4
)

# Velocity pseudotime (alternative to latent time)
scv.tl.velocity_pseudotime(adata)
scv.pl.scatter(adata, color='velocity_pseudotime', cmap='gnuplot')
```

### 8. PAGA 轨迹图

```python
# PAGA graph with velocity-informed transitions
scv.tl.paga(adata, groups='leiden')
df = scv.get_df(adata, 'paga/transitions_confidence', precision=2).T
df.style.background_gradient(cmap='Blues').format('{:.2g}')

# Plot PAGA with velocity
scv.pl.paga(
    adata,
    basis='umap',
    size=50,
    alpha=0.1,
    min_edge_width=2,
    node_size_scale=1.5
)
```

## 完整工作流程脚本

```python
import scvelo as scv
import scanpy as sc

def run_rna_velocity(adata, n_top_genes=2000, mode='dynamical', n_jobs=4):
    """
    Complete RNA velocity workflow.

    Args:
        adata: AnnData with 'spliced' and 'unspliced' layers, UMAP in obsm
        n_top_genes: Number of top HVGs for velocity
        mode: 'stochastic' (fast) or 'dynamical' (accurate)
        n_jobs: Parallel jobs for dynamical model

    Returns:
        Processed AnnData with velocity information
    """
    scv.settings.verbosity = 2

    # 1. Preprocessing (scVelo 0.3 dropped log/HVG from filter_and_normalize)
    scv.pp.filter_and_normalize(adata, min_shared_counts=20)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=n_top_genes, subset=True)

    if 'neighbors' not in adata.uns:
        sc.pp.neighbors(adata, n_neighbors=30)

    scv.pp.moments(adata, n_pcs=30, n_neighbors=30)

    # 2. Velocity estimation
    if mode == 'dynamical':
        scv.tl.recover_dynamics(adata, n_jobs=n_jobs)

    scv.tl.velocity(adata, mode=mode)
    scv.tl.velocity_graph(adata)

    # 3. Downstream analyses
    if mode == 'dynamical':
        scv.tl.latent_time(adata)
        scv.tl.rank_velocity_genes(adata, groupby='leiden', min_corr=0.3)

    scv.tl.velocity_confidence(adata)
    scv.tl.velocity_pseudotime(adata)

    return adata
```

## AnnData 中的关键输出字段

运行完工作流程后，会添加以下字段:

| 位置 | 键 | 说明 |
|----------|-----|-------------|
| `adata.layers` | `velocity` | 每个细胞每个基因的 RNA 速率 |
| `adata.layers` | `fit_t` | 每个细胞每个基因拟合出的潜在时间 |
| `adata.obsm` | `velocity_umap` | UMAP 上的二维速率向量 |
| `adata.obs` | `velocity_pseudotime` | 由速率推导出的伪时间 |
| `adata.obs` | `latent_time` | 来自动力学模型的潜在时间 |
| `adata.obs` | `velocity_length` | 每个细胞的速度 |
| `adata.obs` | `velocity_confidence` | 每个细胞的置信度分数 |
| `adata.var` | `fit_likelihood` | 基因层面的模型拟合质量 |
| `adata.var` | `fit_alpha` | 转录速率 |
| `adata.var` | `fit_beta` | 剪接速率 |
| `adata.var` | `fit_gamma` | 降解速率 |
| `adata.uns` | `velocity_graph` | 细胞间转变概率矩阵 |

## 速率模型比较

| 模型 | 速度 | 准确度 | 适用场景 |
|-------|-------|----------|-------------|
| `stochastic`(随机模型) | 快 | 中等 | 探索性分析；大型数据集 |
| `deterministic`(确定性模型) | 中等 | 中等 | 简单的线性动力学 |
| `dynamical`(动力学模型) | 慢 | 高 | 出版级质量；可识别驱动基因 |

## 最佳实践

- **先从随机模型开始**进行探索；最终分析时再切换到动力学模型
- **需要良好的未剪接 reads 覆盖度**:短 reads(< 100 bp)可能会漏掉内含子覆盖
- **至少 2,000 个细胞**:细胞数过少时 RNA 速率会有很大噪声
- **速率应当具有一致性**:箭头方向应符合已知的生物学规律；呈随机状态则说明存在问题
- **k-NN 带宽很重要**:近邻数过少 → 速率有噪声；近邻数过多 → 过度平滑
- **合理性检查**:根细胞(祖细胞)在标记基因上应具有较高的未剪接/已剪接比例
- **动力学模型需要明确区分的动力学状态**:对于分化过程清晰的场景效果最好

## 问题排查

| 问题 | 解决方法 |
|---------|---------|
| 缺少未剪接层(unspliced layer) | 重新运行 velocyto,或使用带 `--soloFeatures Gene Velocyto` 的 STARsolo |
| 速率基因数量非常少 | 降低 `min_shared_counts`;检查测序深度 |
| 箭头看起来是随机的 | 尝试不同的 `n_neighbors` 或不同的速率模型 |
| 动力学模型出现内存错误 | 设置 `n_jobs=1`;减少 `n_top_genes` |
| 到处都是负速率 | 检查 spliced/unspliced 两层是否被互换 |

## 其他资源

- **scVelo 文档**:https://scvelo.readthedocs.io/
- **教程 notebook**:https://scvelo.readthedocs.io/tutorials/
- **GitHub**:https://github.com/theislab/scvelo
- **论文**:Bergen V et al. (2020) Nature Biotechnology. PMID: 32747759
- **velocyto**(预处理):http://velocyto.org/
- **CellRank**(命运预测，是 scVelo 的扩展):https://cellrank.readthedocs.io/
- **dynamo**(代谢标记法的替代方案):https://dynamo-release.readthedocs.io/
