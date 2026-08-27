# AnnData

## 概述

AnnData 是一个用于处理带注释的数据矩阵的 Python 包，将实验测量值(X)与观测(observation)元数据(obs)、变量(variable)元数据(var),以及多维注释(obsm、varm、obsp、varp、uns)一起存储。它最初是为通过 Scanpy 进行单细胞基因组学而设计的，如今已成为一个通用框架，适用于任何需要高效存储、操作和分析的带注释数据。

## 何时使用此技能

在以下情况使用此技能:
- 创建、读取或写入 AnnData 对象
- 处理 h5ad、zarr 或其他基因组学数据格式
- 执行单细胞 RNA-seq 分析
- 用稀疏矩阵或后端(backed)模式管理大型数据集
- 拼接多个数据集或实验批次
- 对带注释的数据进行子集提取、过滤或变换
- 与 scanpy、scvi-tools 或其他 scverse 生态系统工具集成

## 安装

需要 Python 3.11+。当前稳定版本:0.12.16(发布于 2026-05-18)。

```bash
uv pip install "anndata==0.12.16"

# Lazy I/O and dask-backed operations
uv pip install "anndata[dask,lazy]==0.12.16"

# Development / docs (contributors)
uv pip install "anndata[dev,test,doc]==0.12.16"
```

仅在有意跟踪最新的兼容版本时才使用不锁定版本号的安装方式。

当前 API 说明:
- 对于非原生的 `read_*` 和 `write_*` 辅助函数，使用 `anndata.io`。顶层的 `anndata.read_h5ad` 和 `anndata.read_zarr` 仍然受支持。
- 避免使用已弃用的 API:`ad.read`、`AnnData.concatenate()`、`AnnData.*_keys()`,以及 `anndata.__version__`。优先使用 `ad.read_h5ad`、`ad.concat`、映射的 `.keys()`,以及 `importlib.metadata.version("anndata")`。
- 把 `anndata.experimental` 系列 API 当作有用但不稳定的功能来对待。仅在其当前的注意事项可以接受的情况下，才在大数据工作流中优先使用它们。

## 快速开始

### 创建一个 AnnData 对象
```python
import anndata as ad
import numpy as np
import pandas as pd

# Minimal creation
X = np.random.rand(100, 2000)  # 100 cells × 2000 genes
adata = ad.AnnData(X)

# With metadata
obs = pd.DataFrame({
    'cell_type': ['T cell', 'B cell'] * 50,
    'sample': ['A', 'B'] * 50
}, index=[f'cell_{i}' for i in range(100)])

var = pd.DataFrame({
    'gene_name': [f'Gene_{i}' for i in range(2000)]
}, index=[f'ENSG{i:05d}' for i in range(2000)])

adata = ad.AnnData(X=X, obs=obs, var=var)
```

### 读取数据
```python
# Native formats (read_h5ad/read_zarr remain at top-level)
adata = ad.read_h5ad('data.h5ad')
adata = ad.read_h5ad('large_data.h5ad', backed='r')  # lazy load for large files
adata = ad.read_zarr('data.zarr')

# Other formats: prefer anndata.io (top-level imports are deprecated)
from anndata.io import read_csv, read_loom, read_mtx

adata = read_csv('data.csv')
adata = read_loom('data.loom')

# 10X Genomics: use scanpy (not anndata) — see scanpy skill
import scanpy as sc
adata = sc.read_10x_h5('filtered_feature_bc_matrix.h5')
adata = sc.read_10x_mtx('filtered_feature_bc_matrix/')
```

### 写入数据
```python
# Write h5ad file
adata.write_h5ad('output.h5ad')

# Write with compression
adata.write_h5ad('output.h5ad', compression='gzip')

# Write other formats
adata.write_zarr('output.zarr')
adata.write_csvs('output_dir/')
```

### 基本操作
```python
# Subset by conditions
t_cells = adata[adata.obs['cell_type'] == 'T cell']

# Subset by indices
subset = adata[0:50, 0:100]

# Add metadata
adata.obs['quality_score'] = np.random.rand(adata.n_obs)
adata.var['highly_variable'] = np.random.rand(adata.n_vars) > 0.8

# Access dimensions
print(f"{adata.n_obs} observations × {adata.n_vars} variables")
```

## 核心能力

### 1. 数据结构

理解 AnnData 对象的结构，包括 X、obs、var、layers、obsm、varm、obsp、varp、uns 以及 raw 组件。

**参见**:`references/data_structure.md`,获取以下内容的全面说明:
- 核心组件(X、obs、var、layers、obsm、varm、obsp、varp、uns、raw)
- 从各种来源创建 AnnData 对象
- 访问和操作数据组件
- 内存高效的实践方法

### 2. 输入/输出操作

以各种格式读写数据，支持压缩、后端模式和云存储。

**参见**:`references/io_operations.md`,了解以下细节:
- 原生格式(h5ad、zarr)
- 其他格式(CSV、MTX、Loom、10X、Excel)
- 面向大型数据集的后端模式
- 远程数据访问
- 格式转换
- 性能优化

常用命令:
```python
from anndata.io import read_mtx

# Read/write h5ad
adata = ad.read_h5ad('data.h5ad', backed='r')
adata.write_h5ad('output.h5ad', compression='gzip')

# 10X Genomics (via scanpy)
import scanpy as sc
adata = sc.read_10x_h5('filtered_feature_bc_matrix.h5')

# Read MTX format
adata = read_mtx('matrix.mtx').T
```

### 3. 拼接(Concatenation)

沿观测或变量方向，以灵活的连接策略合并多个 AnnData 对象。

**参见**:`references/concatenation.md`,获取以下内容的全面覆盖:
- 基本拼接(axis=0 用于观测,axis=1 用于变量)
- 连接类型(inner、outer)
- 合并策略(same、unique、first、only)
- 用标签跟踪数据来源
- 惰性拼接(AnnCollection)
- 面向大型数据集的磁盘上拼接

常用命令:
```python
# Concatenate observations (combine samples)
adata = ad.concat(
    [adata1, adata2, adata3],
    axis=0,
    join='inner',
    label='batch',
    keys=['batch1', 'batch2', 'batch3']
)

# Concatenate variables (combine modalities)
adata = ad.concat([adata_rna, adata_protein], axis=1)

# Lazy collection over backed AnnData objects (experimental)
from anndata.experimental import AnnCollection

backed_adatas = [
    ad.read_h5ad(path, backed='r')
    for path in ['data1.h5ad', 'data2.h5ad']
]
collection = AnnCollection(
    backed_adatas,
    join_obs='outer',
    join_vars='inner',
    label='dataset'
)
```

### 4. 数据操作

高效地变换、提取子集、过滤和重组数据。

**参见**:`references/manipulation.md`,获取以下方面的详细指导:
- 子集提取(按索引、名称、布尔掩码、元数据条件)
- 转置
- 复制(完整拷贝 vs 视图)
- 重命名(观测、变量、类别)
- 类型转换(字符串转为分类变量、稀疏/稠密互转)
- 添加/移除数据组件
- 重新排序
- 质量控制过滤

常用命令:
```python
# Subset by metadata
filtered = adata[adata.obs['quality_score'] > 0.8]
hv_genes = adata[:, adata.var['highly_variable']]

# Transpose
adata_T = adata.T

# Copy vs view
view = adata[0:100, :]  # View (lightweight reference)
copy = adata[0:100, :].copy()  # Independent copy

# Convert strings to categoricals
adata.strings_to_categoricals()
```

### 5. 最佳实践

遵循内存效率、性能与可重复性方面的推荐模式。

**参见**:`references/best_practices.md`,了解以下方面的指导原则:
- 内存管理(稀疏矩阵、分类变量、后端模式)
- 视图 vs 拷贝
- 数据存储优化
- 性能优化
- 处理 raw 数据
- 元数据管理
- 可重复性
- 错误处理
- 与其他工具的集成
- 常见坑点及解决方案

关键建议:
```python
# Use sparse matrices for sparse data
from scipy.sparse import csr_matrix
adata.X = csr_matrix(adata.X)

# Convert strings to categoricals
adata.strings_to_categoricals()

# Use backed mode for large files
adata = ad.read_h5ad('large.h5ad', backed='r')

# Store raw before filtering
adata.raw = adata.copy()
adata = adata[:, adata.var['highly_variable']]
```

## 与 Scverse 生态系统的集成

AnnData 是 scverse 生态系统的基础数据结构:

### Scanpy(单细胞分析)
```python
import scanpy as sc

# Preprocessing
sc.pp.filter_cells(adata, min_genes=200)
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)

# Dimensionality reduction
sc.pp.pca(adata, n_comps=50)
sc.pp.neighbors(adata, n_neighbors=15)
sc.tl.umap(adata)
sc.tl.leiden(adata)

# Visualization
sc.pl.umap(adata, color=['cell_type', 'leiden'])
```

### Muon(多模态数据)
```python
import muon as mu

# Combine RNA and protein data
mdata = mu.MuData({'rna': adata_rna, 'protein': adata_protein})
```

### PyTorch 集成
```python
from anndata.experimental import AnnLoader

# Create DataLoader for deep learning
dataloader = AnnLoader(adata, batch_size=128, shuffle=True)

for batch in dataloader:
    X = batch.X
    # Train model
```

## 常见工作流

### 单细胞 RNA-seq 分析
```python
import anndata as ad
import scanpy as sc

# 1. Load data (10X via scanpy; anndata handles h5ad/zarr natively)
adata = sc.read_10x_h5('filtered_feature_bc_matrix.h5')

# 2. Quality control
adata.obs['n_genes'] = (adata.X > 0).sum(axis=1)
adata.obs['n_counts'] = adata.X.sum(axis=1)
adata = adata[adata.obs['n_genes'] > 200]
adata = adata[adata.obs['n_counts'] < 50000]

# 3. Store raw
adata.raw = adata.copy()

# 4. Normalize and filter
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
adata = adata[:, adata.var['highly_variable']]

# 5. Save processed data
adata.write_h5ad('processed.h5ad')
```

### 批次整合
```python
# Load multiple batches
adata1 = ad.read_h5ad('batch1.h5ad')
adata2 = ad.read_h5ad('batch2.h5ad')
adata3 = ad.read_h5ad('batch3.h5ad')

# Concatenate with batch labels
adata = ad.concat(
    [adata1, adata2, adata3],
    label='batch',
    keys=['batch1', 'batch2', 'batch3'],
    join='inner'
)

# Apply batch correction
import scanpy as sc
sc.pp.combat(adata, key='batch')

# Continue analysis
sc.pp.pca(adata)
sc.pp.neighbors(adata)
sc.tl.umap(adata)
```

### 处理大型数据集
```python
# Open in backed mode
adata = ad.read_h5ad('100GB_dataset.h5ad', backed='r')

# Filter based on metadata (no data loading)
high_quality = adata[adata.obs['quality_score'] > 0.8]

# Load filtered subset
adata_subset = high_quality.to_memory()

# Process subset
process(adata_subset)

# Or process in chunks
chunk_size = 1000
for i in range(0, adata.n_obs, chunk_size):
    chunk = adata[i:i+chunk_size, :].to_memory()
    process(chunk)
```

## 故障排查

### 内存不足错误
使用后端模式，或转换为稀疏矩阵:
```python
# Backed mode
adata = ad.read_h5ad('file.h5ad', backed='r')

# Sparse matrices
from scipy.sparse import csr_matrix
adata.X = csr_matrix(adata.X)
```

### 文件读取缓慢
使用压缩和恰当的格式:
```python
# Optimize for storage
adata.strings_to_categoricals()
adata.write_h5ad('file.h5ad', compression='gzip')

# Use Zarr for cloud storage; v3 writes are opt-in in anndata 0.12
import anndata as ad

ad.settings.zarr_write_format = 3
ad.settings.auto_shard_zarr_v3 = True  # experimental; independent of zarr_write_format
adata.write_zarr('file.zarr', chunks=(1000, 1000))
```

### 索引对齐问题
始终按索引对齐外部数据:
```python
# Wrong
adata.obs['new_col'] = external_data['values']

# Correct
adata.obs['new_col'] = external_data.set_index('cell_id').loc[adata.obs_names, 'values']
```

## 更多资源

- **官方文档**: https://anndata.readthedocs.io/
- **Scanpy 教程**: https://scanpy.readthedocs.io/
- **Scverse 生态系统**: https://scverse.org/
- **GitHub 仓库**: https://github.com/scverse/anndata
