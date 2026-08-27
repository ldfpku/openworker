# Molfeat - 分子特征化中心

## 概述

Molfeat 是一个功能全面的分子特征化 Python 库，统一整合了 100 多种预训练嵌入模型和手工设计的特征化方法。它可将化学结构（SMILES 字符串或 RDKit 分子对象）转换为数值表示，用于机器学习任务，包括 QSAR 建模、虚拟筛选、相似性搜索以及深度学习应用。具备快速并行处理、与 scikit-learn 兼容的转换器，以及内置缓存机制。

**版本说明**： 示例基于 **molfeat 0.11.0**（PyPI 稳定版，2025 年 5 月）。需要 **Python 3.9–3.10**（`requires-python` 限制在 3.11 以下）。依赖 **datamol ≥0.8.0** 和 **PyTorch ≥1.13**。自 0.8.7 版本起，建议优先使用 datamol 的 `Mol` 对象，而非原始的 `rdkit.Chem.Mol`。自 0.10.1 版本起，指纹计算器在内部改用 RDKit 的 `rdFingerprintGenerator` API。自 0.11.0 版本起，预训练模型会加载到内存中，且基础模型会自动设为 PyTorch 的评估（evaluation）模式。

## 何时使用本技能

在处理以下工作时应使用本技能：
- **分子机器学习**：构建 QSAR/QSPR 模型、性质预测
- **虚拟筛选**：为化合物库的生物活性排序
- **相似性搜索**：查找结构相似的分子
- **化学空间分析**：聚类、可视化、降维
- **深度学习**：在分子数据上训练神经网络
- **特征化流水线**：将 SMILES 转换为可用于机器学习的表示
- **化学信息学**：任何需要提取分子特征的任务

## 安装

请使用 Python 3.9 或 3.10 环境（截至 0.11.0 版本，molfeat 无法在 3.11 及以上版本安装）：

```bash
uv pip install "molfeat==0.11.0"

# With all pip-installable optional dependencies
uv pip install "molfeat[all]==0.11.0"
```

**可选依赖附加集（PyPI）**：
- `molfeat[dgl]` — GNN 模型（GIN 系列变体）；上游建议使用 `dgl<=2.0`（更新版本的 DGL 存在 graphbolt 相关问题）
- `molfeat[graphormer]` — Graphormer 模型
- `molfeat[transformer]` — ChemBERTa、ChemGPT、MolT5
- `molfeat[fcd]` — FCD 描述符
- `molfeat[pyg]` — PyTorch Geometric 特征化器
- `molfeat[viz]` — NGLView 可视化控件

**外部特征化器**： MAP4 并未包含在 molfeat 的附加依赖集中——需从 [reymond-group/map4](https://github.com/reymond-group/map4) 单独安装。部分较重的依赖项（DGL、dgllife、graphormer-pretrained）通过 conda-forge 安装更为方便；详见[可选依赖说明](https://molfeat-docs.datamol.io/stable/)。

## 核心概念

Molfeat 将特征化过程组织为三个层级化的类别：

### 1. 计算器（`molfeat.calc`）

将单个分子转换为特征向量的可调用对象。可接受 RDKit 的 `Chem.Mol` 对象或 SMILES 字符串。

**在以下情况下使用计算器**：
- 单个分子的特征化
- 自定义处理循环
- 直接进行特征计算

**示例**：
```python
from molfeat.calc import FPCalculator

calc = FPCalculator("ecfp", radius=3, fpSize=2048)
features = calc("CCO")  # Returns numpy array (2048,)
```

### 2. 转换器（`molfeat.trans`）

与 scikit-learn 兼容的转换器，对计算器进行封装，支持带并行化的批量处理。

**在以下情况下使用转换器**：
- 对分子数据集进行批量特征化
- 与 scikit-learn 流水线集成
- 并行处理（自动利用 CPU 资源）

**示例**：
```python
from molfeat.trans import MoleculeTransformer
from molfeat.calc import FPCalculator

transformer = MoleculeTransformer(FPCalculator("ecfp"), n_jobs=-1)
features = transformer(smiles_list)  # Parallel processing
```

### 3. 预训练转换器（`molfeat.trans.pretrained`）

专为深度学习模型设计的转换器，支持批量推理和缓存。

**在以下情况下使用预训练转换器**：
- 获取最先进的分子嵌入
- 从大规模化学数据集进行迁移学习
- 深度学习特征提取

**示例**：
```python
from molfeat.trans.pretrained import PretrainedMolTransformer

transformer = PretrainedMolTransformer("ChemBERTa-77M-MLM", n_jobs=-1)
embeddings = transformer(smiles_list)  # Deep learning embeddings
```

## 快速上手工作流

### 基础特征化

```python
import datamol as dm
from molfeat.calc import FPCalculator
from molfeat.trans import MoleculeTransformer

# Load molecular data
smiles = ["CCO", "CC(=O)O", "c1ccccc1", "CC(C)O"]

# Create calculator and transformer
calc = FPCalculator("ecfp", radius=3)
transformer = MoleculeTransformer(calc, n_jobs=-1)

# Featurize molecules
features = transformer(smiles)
print(f"Shape: {features.shape}")  # (4, 2048)
```

### 保存与加载配置

```python
# Save featurizer configuration for reproducibility
transformer.to_state_yaml_file("featurizer_config.yml")

# Reload exact configuration
loaded = MoleculeTransformer.from_state_yaml_file("featurizer_config.yml")
```

### 优雅地处理错误

```python
# Process dataset with potentially invalid SMILES
transformer = MoleculeTransformer(
    calc,
    n_jobs=-1,
    ignore_errors=True,  # Continue on failures
    verbose=True          # Log error details
)

features = transformer(smiles_with_errors)
# Returns None for failed molecules
```

## 选择特征化器与常见工作流

按任务类型（传统机器学习——随机森林、SVM、XGBoost，深度学习，相似性搜索，以及基于药效团的方法）选择特征化器，以及构建 QSAR 模型、虚拟筛选、相似性搜索、与 scikit-learn 流水线集成、比较多种特征化器等实操工作流，均见
[references/choosing_a_featurizer.md](references/choosing_a_featurizer.md)。

完整的特征化器列表见
[references/available_featurizers.md](references/available_featurizers.md)；更多示例见 [references/examples.md](references/examples.md)。

## 发现可用的特征化器

使用 ModelStore 来探索所有可用的特征化器：

```python
from molfeat.store.modelstore import ModelStore

store = ModelStore()

# List all available models
all_models = store.available_models
print(f"Total featurizers: {len(all_models)}")

# Search for specific models
chemberta_models = store.search(name="ChemBERTa")
for model in chemberta_models:
    print(f"- {model.name}: {model.description}")

# Get usage information
model_card = store.search(name="ChemBERTa-77M-MLM")[0]
model_card.usage()  # Display usage examples

# Load model
transformer = store.load("ChemBERTa-77M-MLM")
```

## 进阶特性

### 自定义预处理

```python
class CustomTransformer(MoleculeTransformer):
    def preprocess(self, mol):
        """Custom preprocessing pipeline"""
        if isinstance(mol, str):
            mol = dm.to_mol(mol)
        mol = dm.standardize_mol(mol)
        mol = dm.remove_salts(mol)
        return mol

transformer = CustomTransformer(FPCalculator("ecfp"), n_jobs=-1)
```

### 分块处理大规模数据集

```python
import numpy as np

def featurize_in_chunks(smiles_list, transformer, chunk_size=10000):
    """Process large datasets in chunks to manage memory"""
    all_features = []
    for i in range(0, len(smiles_list), chunk_size):
        chunk = smiles_list[i:i+chunk_size]
        features = transformer(chunk)
        all_features.append(features)
    return np.vstack(all_features)
```

### 缓存开销较大的嵌入结果

在可行的情况下，优先使用 molfeat 内置的预训练模型缓存机制。若需要自定义嵌入缓存，请使用 NumPy 数组而非 pickle（pickle 在加载不可信文件时可能执行任意代码）：

```python
import numpy as np
from pathlib import Path

cache_file = Path("embeddings_cache.npz")  # fixed path under your project
transformer = PretrainedMolTransformer("ChemBERTa-77M-MLM", n_jobs=-1)

if cache_file.exists():
    embeddings = np.load(cache_file)["embeddings"]
else:
    embeddings = transformer(smiles_list)
    np.savez(cache_file, embeddings=embeddings)
```

## 性能建议

1. **使用并行化**：设置 `n_jobs=-1` 以利用全部 CPU 核心
2. **批量处理**：一次处理多个分子，而不是使用循环逐个处理
3. **选择合适的特征化器**：指纹方法比深度学习模型更快
4. **缓存预训练模型**：重复使用时利用内置缓存机制
5. **使用 float32**：在精度允许的情况下设置 `dtype=np.float32`
6. **高效处理错误**：对大规模数据集使用 `ignore_errors=True`

## 常用特征化器参考

**常用特征化器快速参考**：

| 特征化器 | 类型 | 维度 | 速度 | 适用场景 |
|------------|------|------------|-------|----------|
| `ecfp` | 指纹 | 2048 | 快 | 通用场景 |
| `maccs` | 指纹 | 167 | 非常快 | 骨架相似性 |
| `desc2D` | 描述符 | 200+ | 快 | 可解释模型 |
| `mordred` | 描述符 | 1800+ | 中等 | 全面的特征集 |
| `map4` | 指纹 | 1024 | 快 | 大规模筛选 |
| `ChemBERTa-77M-MLM` | 深度学习 | 768 | 慢* | 迁移学习 |
| `gin-supervised-masking` | GNN | 可变 | 慢* | 基于图的模型 |

*首次运行较慢；后续运行可受益于缓存机制

## 资源

本技能附带完整的参考文档：

### references/api_reference.md
完整的 API 文档，涵盖：
- `molfeat.calc` - 所有计算器类及其参数
- `molfeat.trans` - 转换器类及其方法
- `molfeat.store` - ModelStore 的用法
- 常见模式与集成示例
- 性能优化建议

**何时加载**： 在实现具体的计算器、理解转换器参数，或与 scikit-learn/PyTorch 集成时参考此文档。

### references/available_featurizers.md
按类别整理的全部 100 多种特征化器的完整目录：
- 基于 Transformer 的语言模型（ChemBERTa、ChemGPT）
- 图神经网络（GIN、Graphormer）
- 分子描述符（RDKit、Mordred）
- 指纹（ECFP、MACCS、MAP4 及其他 15 种以上）
- 药效团描述符（CATS、Gobbi）
- 形状描述符（USR、ElectroShape）
- 基于骨架的描述符

**何时加载**： 在为特定任务挑选最优特征化器、探索可用选项，或了解各特征化器特点时参考此文档。

**检索技巧**： 使用 grep 查找特定类型的特征化器：
```bash
grep -i "chembert" references/available_featurizers.md
grep -i "pharmacophore" references/available_featurizers.md
```

### references/examples.md
针对常见场景的实用代码示例：
- 安装与快速上手
- 计算器与转换器示例
- 预训练模型的使用
- 与 scikit-learn 和 PyTorch 的集成
- 虚拟筛选工作流
- QSAR 模型构建
- 相似性搜索
- 故障排查与最佳实践

**何时加载**： 在实现具体工作流、排查问题，或学习 molfeat 使用模式时参考此文档。

## 故障排查

### 无效分子
启用错误处理以跳过无效的 SMILES：
```python
transformer = MoleculeTransformer(
    calc,
    ignore_errors=True,
    verbose=True
)
```

### 大规模数据集的内存问题
对超过 10 万个分子的数据集，采用分块处理或流式处理方式。

### 预训练模型的依赖项
部分模型需要额外的软件包。安装相应的附加依赖集（为可复现性锁定版本）：
```bash
uv pip install "molfeat[transformer]==0.11.0"  # For ChemBERTa/ChemGPT
uv pip install "molfeat[dgl]==0.11.0"          # For GIN models
uv pip install "molfeat[graphormer]==0.11.0"   # For Graphormer
```

### 可复现性
保存精确的配置并记录版本信息：
```python
transformer.to_state_yaml_file("config.yml")
import molfeat
print(f"molfeat version: {molfeat.__version__}")
```

## 其他资源

- **官方文档**：https://molfeat-docs.datamol.io/
- **GitHub 仓库**：https://github.com/datamol-io/molfeat
- **PyPI 软件包**：https://pypi.org/project/molfeat/
- **教程**：https://portal.valencelabs.com/datamol/post/types-of-featurizers-b1e8HHrbFMkbun6
