# scvi-tools

## 概述

scvi-tools 是一个功能全面的 Python 框架，用于单细胞基因组学中的概率模型。它构建于 PyTorch 和 PyTorch Lightning 之上，使用变分推断(variational inference)提供深度生成模型，用于分析多种多样的单细胞数据模态(modality)。当前稳定版本:**scvi-tools 1.4.3**(2026 年 5 月)。

**模型命名空间很重要**: 核心模型(scVI、scANVI、totalVI、MultiVI、PeakVI、AUTOZI、CondSCVI、DestVI、LinearSCVI、AmortizedLDA、JaxSCVI)位于 `scvi.model` 之下。大多数其他模型(VeloVI、contrastiveVI、CellAssign、PoissonVI、scBasset、MrVI、MethylVI/MethylANVI、CytoVI、SysVI、Decipher、gimVI、scVIVA、ResolVI、Stereoscope、Solo、totalANVI、DIAGVI)位于 `scvi.external` 之下。各参考文件中说明了每个模型所对应的正确命名空间。

## 何时使用此技能

在以下情况使用此技能:
- 分析单细胞 RNA-seq 数据(降维、批次校正、整合)
- 处理单细胞 ATAC-seq 或染色质可及性数据
- 整合多模态数据(CITE-seq、multiome、配对/非配对数据集)
- 分析空间转录组数据(反卷积、空间映射)
- 对单细胞数据执行差异表达分析
- 开展细胞类型注释或迁移学习任务
- 处理专门的单细胞数据模态(甲基化、细胞术、RNA 速度 velocity)
- 为单细胞分析构建自定义概率模型

## 核心能力

scvi-tools 按数据模态组织提供模型:

### 1. 单细胞 RNA-seq 分析
用于表达分析、批次校正和整合的核心模型。见 `references/models-scrna-seq.md`:
- **scVI**:无监督降维和批次校正
- **scANVI**:半监督细胞类型注释和整合
- **AUTOZI**:零膨胀(zero-inflation)检测与建模
- **VeloVI**:RNA 速度(velocity)分析
- **contrastiveVI**:分离扰动效应(perturbation effect)

### 2. 染色质可及性(ATAC-seq)
用于分析单细胞染色质数据的模型。见 `references/models-atac-seq.md`:
- **PeakVI**:基于峰(peak)的 ATAC-seq 分析与整合
- **PoissonVI**:定量的片段计数建模
- **scBasset**:带有基序(motif)分析的深度学习方法

### 3. 多模态与多组学整合
多种数据类型的联合分析。见 `references/models-multimodal.md`:
- **totalVI**:CITE-seq 蛋白质与 RNA 联合建模
- **totalANVI**:半监督的 CITE-seq(带细胞类型标签的 totalVI)
- **MultiVI**:配对与非配对的多组学整合(基于 MuData)
- **MrVI**:多分辨率的跨样本分析
- **DIAGVI**:非配对单细胞数据集的对角整合(diagonal integration,1.4.3 中新增)

### 4. 空间转录组学
空间分辨的转录组学分析。见 `references/models-spatial.md`:
- **DestVI**:多分辨率空间反卷积
- **Stereoscope**:细胞类型反卷积
- **Tangram**:空间映射与整合
- **scVIVA**:细胞-环境关系分析

### 5. 专门的数据模态
额外的专门分析工具。见 `references/models-specialized.md`:
- **MethylVI/MethylANVI**:单细胞甲基化分析
- **CytoVI**:流式/质谱细胞术的批次校正
- **Solo**:双细胞(doublet)检测
- **CellAssign**:基于标记基因的细胞类型注释

## 典型工作流

所有 scvi-tools 模型都遵循一致的 API 模式:

```python
# 1. Load and preprocess data (AnnData format)
import scvi
import scanpy as sc

adata = scvi.data.heart_cell_atlas_subsampled()
sc.pp.filter_genes(adata, min_counts=3)
sc.pp.highly_variable_genes(adata, n_top_genes=1200)

# 2. Register data with model (specify layers, covariates)
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",  # Use raw counts, not log-normalized
    batch_key="batch",
    categorical_covariate_keys=["donor"],
    continuous_covariate_keys=["percent_mito"]
)

# 3. Create and train model
model = scvi.model.SCVI(adata)
model.train()

# 4. Extract latent representations and normalized values
latent = model.get_latent_representation()
normalized = model.get_normalized_expression(library_size=1e4)

# 5. Store in AnnData for downstream analysis
adata.obsm["X_scVI"] = latent
adata.layers["scvi_normalized"] = normalized

# 6. Downstream analysis with scanpy
sc.pp.neighbors(adata, use_rep="X_scVI")
sc.tl.umap(adata)
sc.tl.leiden(adata)
```

**关键设计原则**:
- **需要原始计数**:模型期望的是未归一化的计数数据，以获得最佳性能
- **统一的 API**:所有模型之间一致的接口(注册 → 训练 → 提取)
- **以 AnnData 为中心**:与 scanpy 生态系统无缝集成
- **GPU 加速**:自动利用可用的 GPU
- **批次校正**:通过协变量(covariate)注册来处理技术性变异

## 常见分析任务

### 差异表达分析
使用已学习的生成模型进行概率化的差异表达分析:

```python
de_results = model.differential_expression(
    groupby="cell_type",
    group1="TypeA",
    group2="TypeB",
    mode="change",  # Use composite hypothesis testing
    delta=0.25      # Minimum effect size threshold
)
```

详细的方法学和解读方式见 `references/differential-expression.md`。

### 模型持久化(Model Persistence)
保存和加载已训练的模型:

```python
# Save model
model.save("./model_directory", overwrite=True)

# Load model
model = scvi.model.SCVI.load("./model_directory", adata=adata)
```

### 批次校正与整合
跨批次或跨研究整合数据集:

```python
# Register batch information
scvi.model.SCVI.setup_anndata(adata, batch_key="study")

# Model automatically learns batch-corrected representations
model = scvi.model.SCVI(adata)
model.train()
latent = model.get_latent_representation()  # Batch-corrected
```

## 理论基础

scvi-tools 构建于以下基础之上:
- **变分推断**:为可扩展的贝叶斯推断近似后验分布
- **深度生成模型**:学习复杂数据分布的 VAE 架构
- **摊销推断(Amortized inference)**:跨细胞高效学习的共享神经网络
- **概率建模**:有理论依据的不确定性量化和统计检验

详细的数学框架背景见 `references/theoretical-foundations.md`。

## 更多资源

- **工作流**:`references/workflows.md` 中包含常见工作流、最佳实践、超参数调优和 GPU 优化
- **模型参考**:`references/` 目录中各模型类别的详细文档
- **官方文档**: https://docs.scvi-tools.org/en/stable/
- **教程**: https://docs.scvi-tools.org/en/stable/tutorials/index.html
- **API 参考**: https://docs.scvi-tools.org/en/stable/api/index.html

## 安装

需要 Python **3.12+**(scvi-tools 1.4 已停止支持更早的版本)。

```bash
uv pip install scvi-tools
# For GPU support
uv pip install "scvi-tools[cuda]"
```

为获得可重复的环境，请锁定版本:`uv pip install scvi-tools==1.4.3`。

**计算后端**: 训练默认使用 PyTorch(CPU/GPU/TPU)。对于部分模型，还提供
JAX 后端(`scvi.model.JaxSCVI`)以及面向 Apple silicon 的实验性 MLX 后端
(`scvi.model.mlxSCVI`)。

## 最佳实践

1. **使用原始计数**:始终向模型提供未归一化的计数数据
2. **过滤基因**:分析前去除低计数的基因(例如 `min_counts=3`)
3. **注册协变量**:在 `setup_anndata` 中包含已知的技术性因素(批次、供体等)
4. **特征选择**:使用高变基因(highly variable genes)以提升性能
5. **模型保存**:始终保存已训练的模型，以避免重新训练
6. **GPU 使用**:对大型数据集启用 GPU 加速(`accelerator="gpu"`)
7. **Scanpy 集成**:将输出存放在 AnnData 对象中，供下游分析使用
