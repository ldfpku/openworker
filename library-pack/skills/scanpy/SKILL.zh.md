# Scanpy:单细胞分析

## 概览

Scanpy 是一个基于 AnnData 构建的、可扩展的 Python 单细胞 RNA-seq 数据分析工具包。将本技能应用于完整的单细胞工作流程，包括质量控制、归一化、降维、聚类、标记基因识别、可视化和轨迹分析。当前稳定版本:**scanpy 1.12.x**(2026 年 1 月)。

## 安装

需要 Python **3.12+**(scanpy 1.12 已放弃对 Python ≤3.11 的支持)以及 anndata **≥0.10**。

```bash
uv pip install "scanpy[leiden]"
```

`[leiden]` 附加组件会安装 `python-igraph` 和 `leidenalg`,这是 Leiden 聚类所必需的。为了环境可复现，建议锁定版本:`uv pip install "scanpy[leiden]==1.12.1"`。

对于大型或超出内存的数据集，许多函数支持 [Dask](https://docs.dask.org/) 数组(实验性功能):

```bash
uv pip install "scanpy[leiden]" dask
```

参见 [Using dask with Scanpy](https://scanpy.scverse.org/en/stable/tutorials/experimental/dask.html) 教程。若需要 GPU 加速的类 scanpy 操作，请使用独立的软件包 [rapids-singlecell](https://rapids-singlecell.readthedocs.io/)。

如果输入是 R 原生的单细胞对象(`.rds`、`.RData`、Seurat 或 SingleCellExperiment),应先用 R 工具将其转换为 `.h5ad`,再用 Scanpy 加载。阅读 `references/r_interop.md` 以获取在 macOS、Linux 和 Windows 上由代理执行的安装与转换说明。

关于 AnnData 结构和 I/O 细节，使用 **anndata** 技能。关于概率模型和批次校正，使用 **scvi-tools** 技能。

## 何时使用本技能

在以下情形应当使用本技能:
- 分析单细胞 RNA-seq 数据(.h5ad、10X、CSV 格式)
- 处理需要转换为 `.h5ad` 的 R 友好型单细胞数据集(`.rds`、`.RData`、Seurat、SingleCellExperiment)
- 对 scRNA-seq 数据集进行质量控制
- 创建 UMAP、t-SNE 或 PCA 可视化图
- 识别细胞簇并寻找标记基因
- 基于基因表达对细胞类型进行注释
- 进行轨迹推断或伪时间(pseudotime)分析
- 生成出版级质量的单细胞图表

## 脚本工具集(优先于从零手写代码)

本技能为每一个常见步骤在 `scripts/` 目录下打包了可直接运行的 CLI 脚本。**优先运行这些脚本，而不是手写 scanpy 代码**——它们会按扩展名处理文件加载、图形设置、合理的默认值、原始计数保留和进度日志记录。每个脚本都读写 `.h5ad`,因此可以链式串联，且每个脚本都有自己的 `--help`。只有当某项任务未被任何脚本覆盖，或需要特殊定制时，才降级为手写 scanpy 代码。

所有脚本共用 `scripts/_common.py` 辅助模块(加载、保存、图形配置)——请将其与其他脚本放在一起。从技能目录运行，或传入完整路径；图形默认输出到 `./figures/`。

| 脚本 | 用途 | 典型调用方式 |
|--------|---------|--------------|
| `run_pipeline.py` | **一条命令完成整个工作流**:加载 → QC → 归一化 → HVG → PCA →(批次)→ UMAP → Leiden → 标记基因 | `python scripts/run_pipeline.py raw.h5ad -o processed.h5ad` |
| `inspect_data.py` | 总结一个未知数据集(形状、obs/var、layers、已计算的内容、原始数据 vs 归一化数据) | `python scripts/inspect_data.py data.h5ad` |
| `convert.py` | 加载任意格式(10x 目录/.h5、csv、loom、mtx)并写出 `.h5ad` | `python scripts/convert.py 10x_dir/ -o data.h5ad` |
| `qc_analysis.py` | QC 指标、前后对比图、过滤、可选 Scrublet 双细胞检测 | `python scripts/qc_analysis.py raw.h5ad -o qc.h5ad --scrublet` |
| `preprocess.py` | 归一化、log1p、HVG、可选缩放/回归(保留 `counts` layer 和 `raw`) | `python scripts/preprocess.py qc.h5ad -o norm.h5ad` |
| `reduce_dimensions.py` | PCA + 方差图、近邻图、UMAP、可选 t-SNE | `python scripts/reduce_dimensions.py norm.h5ad -o red.h5ad` |
| `batch_correct.py` | 整合:harmony / bbknn / combat | `python scripts/batch_correct.py red.h5ad -o int.h5ad --method harmony --batch-key sample` |
| `cluster.py` | Leiden(或 louvain),支持单一或多个分辨率 | `python scripts/cluster.py red.h5ad -o clu.h5ad --resolution 0.3 0.6 1.0` |
| `find_markers.py` | `rank_genes_groups` + 各组 CSV + 标记基因图 | `python scripts/find_markers.py clu.h5ad --groupby leiden -o clu.h5ad` |
| `annotate.py` | 从 JSON/CSV 将聚类映射到细胞类型；可选标记参考点图(dotplot) | `python scripts/annotate.py clu.h5ad -o ann.h5ad --mapping map.json` |
| `score_genes.py` | 对基因特征集(JSON)和/或细胞周期时相打分 | `python scripts/score_genes.py ann.h5ad -o scored.h5ad --gene-sets sigs.json` |
| `pseudobulk.py` | 按样本 × 细胞类型汇总计数 → 供 pydeseq2 使用的矩阵 | `python scripts/pseudobulk.py ann.h5ad --by sample cell_type --out-prefix pb` |
| `subset.py` | 按 obs 值或基因列表取子集(可选清除过期的嵌入) | `python scripts/subset.py ann.h5ad -o tcells.h5ad --obs cell_type --keep "T cells"` |
| `plot.py` | 从已处理的对象生成 umap/tsne/pca/violin/dotplot/heatmap 等图 | `python scripts/plot.py ann.h5ad --kind dotplot --genes CD3D CD14 --groupby cell_type` |

### 一步到位的端到端运行

```bash
# 计数矩阵 → 已聚类、已做标记基因注释的对象 + 图形 + 标记基因 CSV
python scripts/run_pipeline.py raw.h5ad -o processed.h5ad \
    --resolution 0.5 --n-top-genes 2000 --scrublet
# 多样本整合:
python scripts/run_pipeline.py raw.h5ad -o processed.h5ad --batch-key sample --batch-method harmony
# 通过 JSON 实现可复现的参数(键名与标志名一致,用下划线代替连字符):
python scripts/run_pipeline.py raw.h5ad -o processed.h5ad --config params.json
```

### 分步链式执行(当你需要在各阶段之间检查/迭代时)

```bash
python scripts/qc_analysis.py        raw.h5ad  -o qc.h5ad   --scrublet
python scripts/preprocess.py         qc.h5ad   -o norm.h5ad --n-top-genes 2000
python scripts/reduce_dimensions.py  norm.h5ad -o red.h5ad  --n-pcs 40
python scripts/cluster.py            red.h5ad  -o clu.h5ad  --resolution 0.3 0.5 0.8
python scripts/find_markers.py       clu.h5ad  -o clu.h5ad  --groupby leiden --use-raw
# 查看 results/markers/*.csv,确定标签,写一个映射 JSON,然后:
python scripts/annotate.py           clu.h5ad  -o ann.h5ad  --mapping celltypes.json
```

以下各节记录了每个脚本背后所调用的底层 scanpy 函数——当需要在脚本参数之外做定制时，请阅读它们。

## 快速开始

### 基本导入与设置

```python
import scanpy as sc
import pandas as pd
import numpy as np

# 配置设置
sc.settings.verbosity = 3
sc.settings.set_figure_params(dpi=80, facecolor='white')
sc.settings.figdir = './figures/'
sc.settings.autosave = True  # 优先于逐图的 save=(在 scanpy 1.12 中已弃用)
```

### 加载数据

```python
# 来自 10X Genomics
adata = sc.read_10x_mtx('path/to/data/')
adata = sc.read_10x_h5('path/to/data.h5')

# 来自 h5ad(AnnData 格式)
adata = sc.read_h5ad('path/to/data.h5ad')

# 来自 CSV
adata = sc.read_csv('path/to/data.csv')
```

对于 R 原生文件，不要尝试在 Python 中直接解析 Seurat 的 `.rds`。请先转换:

```bash
# 关于安装 R 及转换软件包,参见 references/r_interop.md
Rscript convert_rds_to_h5ad.R input.rds output.h5ad
```

```python
adata = sc.read_h5ad('output.h5ad')
```

### 理解 AnnData 结构

AnnData 对象是 scanpy 中的核心数据结构:

```python
adata.X          # 表达矩阵(细胞 × 基因)
adata.obs        # 细胞元数据(DataFrame)
adata.var        # 基因元数据(DataFrame)
adata.uns        # 非结构化注释(dict)
adata.obsm       # 多维细胞数据(PCA、UMAP)
adata.raw        # 原始数据备份

# 访问细胞名和基因名
adata.obs_names  # 细胞条形码
adata.var_names  # 基因名称
```

## 标准分析工作流程

七个步骤(含代码及每一步中起决定作用的参数)见
[references/analysis_workflow.md](references/analysis_workflow.md):

1. **质量控制** —— 过滤细胞和基因；在选择阈值之前检查线粒体占比和计数，而不是照搬默认值。
2. **归一化与预处理** —— 归一化、对数变换、选择高变异基因(highly variable genes),并保留 `.raw` 以供后续绘图使用。
3. **降维** —— 先 PCA,再构建近邻图，再 UMAP。
4. **聚类** —— 以针对具体问题选定的分辨率(而非默认值)进行 Leiden 聚类。
5. **标记基因识别** —— 每个簇的排序基因。
6. **细胞类型注释** —— 根据标记基因将簇映射为细胞类型。
7. **保存结果** —— 写出已注释的 `AnnData`。

常见的后续任务——出版级图表、轨迹推断、条件之间的伪批量(pseudobulk)差异表达、基因集打分，以及批次校正——记录在同一份文件中。另请参阅 [references/standard_workflow.md](references/standard_workflow.md) 和
[references/plotting_guide.md](references/plotting_guide.md)。

## 需要调整的关键参数

### 质量控制
- `min_genes`:每个细胞的最小基因数(通常 200-500)
- `min_cells`:每个基因的最小细胞数(通常 3-10)
- `pct_counts_mt`:线粒体阈值(通常 5-20%)

### 归一化
- `target_sum`:每个细胞的目标计数(默认 1e4)

### 特征选择
- `n_top_genes`:HVG(高变异基因)的数量(通常 2000-3000)
- `min_mean`、`max_mean`、`min_disp`:HVG 选择参数

### 降维
- `n_pcs`:主成分数量(查看方差比例图)
- `n_neighbors`:近邻数量(通常 10-30)

### 聚类
- `resolution`:聚类粒度(0.4-1.2,数值越高簇越多)

## 常见陷阱与最佳实践

1. **始终保存原始计数**:在过滤基因之前执行 `adata.raw = adata`
2. **仔细检查 QC 图**:根据数据集质量调整阈值
3. **使用 Leiden 聚类**:`sc.tl.louvain` 在 scanpy 1.12 中已被弃用
4. **尝试多个聚类分辨率**:找到最优的粒度
5. **验证细胞类型注释**:使用多个标记基因
6. **在基因表达图中使用 `use_raw=True`**:显示来自 `.raw` 的归一化计数
7. **检查 PCA 方差比例**:确定最优的主成分数
8. **保存中间结果**:长流程可能中途失败
9. **对差异表达使用伪批量(pseudobulk)**:不要把 `rank_genes_groups` 的 p 值当作条件间严格的差异表达检验结果
10. **通过设置保存图表**:使用 `sc.settings.autosave`,而不是绘图函数上已弃用的 `save=`
11. **在 Scanpy 之前转换 R 对象**:使用 R 软件包将 Seurat 或 SingleCellExperiment 的 `.rds` 文件转换为 `.h5ad`,并保留计数、元数据和基因标识符

## 内置资源

### scripts/(CLI 工具集)
一套可组合的、`.h5ad` 输入/`.h5ad` 输出的脚本，覆盖整个工作流程，外加一个一条命令完成的端到端流水线。完整表格和链式调用示例见上方的「脚本工具集」一节。每个脚本都有 `--help`。文件列表:

- `_common.py` —— 供其他脚本导入的共享加载/保存/图形辅助函数(不是一个 CLI)
- `run_pipeline.py` —— 一条命令完成的完整流水线(通过标志参数或 `--config` JSON)
- `inspect_data.py`、`convert.py` —— 探查并加载/转换任意输入格式
- `qc_analysis.py`、`preprocess.py`、`reduce_dimensions.py`、`batch_correct.py`、`cluster.py` —— 流水线各步骤
- `find_markers.py`、`annotate.py`、`score_genes.py`、`pseudobulk.py` —— 标记基因、注释、打分、差异表达准备
- `subset.py`、`plot.py` —— 按元数据/基因取子集；生成任意标准图表

**在从零手写 scanpy 代码之前，优先使用这些脚本**。

### references/standard_workflow.md
完整的分步工作流程，含详细说明和代码示例，涵盖:
- 数据加载与设置
- 带可视化的质量控制
- 归一化与缩放
- 特征选择
- 降维(PCA、UMAP、t-SNE)
- 聚类(Leiden)
- 双细胞检测(scrublet)与伪批量聚合
- 标记基因识别
- 细胞类型注释
- 轨迹推断
- 差异表达

在从零进行一次完整分析时阅读此参考文件。

### references/api_reference.md
按模块组织的 scanpy 函数速查指南:
- 数据读写(`sc.read_*`、`adata.write_*`)
- 预处理(`sc.pp.*`)
- 工具(`sc.tl.*`)
- 绘图(`sc.pl.*`)
- AnnData 结构与操作
- 设置与实用工具

用于快速查阅函数签名和常用参数。

### references/plotting_guide.md
全面的可视化指南，包括:
- 质量控制图
- 降维可视化
- 聚类可视化
- 标记基因图(热图、点图、小提琴图)
- 轨迹与伪时间图
- 出版级质量的定制
- 多面板图形
- 配色方案与样式

在制作出版级图表时查阅本文件。

### references/r_interop.md
用于代理执行的操作手册，涵盖在 macOS、Linux 和 Windows 上安装 R、安装 CRAN/Bioconductor 转换软件包、检查 `.rds`/`.RData` 输入、将 Seurat 或 SingleCellExperiment 对象转换为 `.h5ad`,以及在 Scanpy 中验证转换结果。

### assets/analysis_template.py
完整的分析模板，提供从数据加载到细胞类型注释的完整工作流程。复制并定制此模板以用于新的分析:

```bash
cp assets/analysis_template.py my_analysis.py
# 编辑参数并运行
python my_analysis.py
```

该模板包含所有标准步骤，附有可配置参数和有用的注释。

### assets/ JSON 模板
编辑即用的模板，让你无需从零编写配置/映射文件:
- `assets/pipeline_config.json` —— 供 `run_pipeline.py --config` 使用的参数集
- `assets/celltype_mapping.json` —— 供 `annotate.py --mapping` 使用的簇 → 细胞类型映射
- `assets/gene_signatures.json` —— 供 `score_genes.py --gene-sets` 使用的基因集特征

## 其他资源

- **官方 scanpy 文档**:https://scanpy.scverse.org/en/stable/
- **Scanpy 教程**:https://scanpy.scverse.org/en/stable/tutorials/index.html
- **发布说明**:https://scanpy.scverse.org/en/stable/release-notes/index.html
- **scverse 生态系统**：<https://scverse.org/>（相关工具：squidpy、scvi-tools、cellrank）
- **R 互操作性**:https://www.bioconductor.org/packages/release/bioc/html/zellkonverter.html 和 https://mojaveazure.github.io/seurat-disk/
- **最佳实践**:Luecken & Theis(2019)"Current best practices in single-cell RNA-seq"

## 高效分析的建议

1. **从模板开始**:以 `assets/analysis_template.py` 作为起点
2. **先运行 QC 脚本**:使用 `scripts/qc_analysis.py` 进行初步过滤
3. **按需查阅参考文件**:将工作流程和 API 参考加载到上下文中
4. **迭代聚类**:尝试多种分辨率和可视化方法
5. **从生物学角度验证**:检查标记基因是否符合预期的细胞类型
6. **记录参数**:记录 QC 阈值和分析设置
7. **保存检查点**:在关键步骤写出中间结果
