# DeepChem

## 概览

DeepChem 是一个综合性的 Python 库，用于将机器学习应用于化学、材料科学和
生物学领域。它通过专门的神经网络、分子特征化(featurization)方法和预训练
模型，实现分子性质预测、药物发现、材料设计，以及生物大分子分析。

**版本说明**: 示例针对的是 **deepchem 2.8.0**(PyPI 稳定版,2024 年 4
月)。要求 **Python 3.7–3.11**(PyPI 上为 `<3.12`)。核心工具(加载器、
特征化器、MoleculeNet)在没有深度学习后端的情况下也能工作;GNN 和
Transformer 模型需要匹配的附加组件(`torch`、`tensorflow` 或 `jax`)。
使用 GPU 构建时，应先安装对应的后端框架。

## 何时使用本技能

在以下情况下应当使用本技能:
- 加载和处理分子数据(SMILES 字符串、SDF 文件、蛋白质序列)
- 预测分子性质(溶解度、毒性、结合亲和力、ADMET 性质)
- 在化学/生物数据集上训练模型
- 使用 MoleculeNet 基准数据集(Tox21、BBBP、Delaney 等)
- 将分子转换为可供机器学习使用的特征(指纹、图表示、描述符)
- 为分子实现图神经网络(GCN、GAT、MPNN、AttentiveFP)
- 使用预训练模型(ChemBERTa、GROVER、MolFormer)做迁移学习
- 预测晶体/材料性质(带隙、生成能)
- 分析蛋白质或 DNA 序列

## 核心能力

八个能力领域，均附带可运行代码，详见
[references/core_capabilities.md](references/core_capabilities.md):

1. **分子数据加载与处理**——加载器、`NumpyDataset` / `DiskDataset`。
2. **分子特征化**——圆形指纹(circular fingerprints)、图卷积
   (graph convolution),以及描述符。
3. **数据切分**——随机切分、骨架(scaffold)切分、分层切分和 butina
   切分器，以及为什么骨架切分才是对分子数据来说诚实的默认选择。
4. **模型选择与训练**——各模型家族及其拟合方式。
5. **MoleculeNet 基准**——加载标准数据集及其发布的切分方式。
6. **迁移学习**——预训练与微调。
7. **模型评估**——适用于回归和分类任务的评估指标。
8. **做出预测**——将训练好的模型应用于新分子。

三个端到端的完整工作流程见
[references/typical_workflows.md](references/typical_workflows.md)。

## 示例脚本

本技能在 `scripts/` 目录下包含三个可直接用于生产的脚本:

### 1. `predict_solubility.py`
训练并评估溶解度预测模型。可用于 Delaney 基准数据，也可用于自定义 CSV
数据。

```bash
# Use Delaney benchmark
python scripts/predict_solubility.py

# Use custom data
python scripts/predict_solubility.py \
    --data my_data.csv \
    --smiles-col smiles \
    --target-col solubility \
    --predict "CCO" "c1ccccc1"
```

### 2. `graph_neural_network.py`
在分子数据上训练多种图神经网络架构。

```bash
# Train GCN on Tox21
python scripts/graph_neural_network.py --model gcn --dataset tox21

# Train AttentiveFP on custom data
python scripts/graph_neural_network.py \
    --model attentivefp \
    --data molecules.csv \
    --task-type regression \
    --targets activity \
    --epochs 100
```

### 3. `transfer_learning.py`
针对分子性质预测任务，对预训练模型(ChemBERTa、GROVER、MolFormer)做
微调。

```bash
# Fine-tune ChemBERTa on BBBP
python scripts/transfer_learning.py --model chemberta --dataset bbbp

# Fine-tune GROVER on custom data
python scripts/transfer_learning.py \
    --model grover \
    --data small_dataset.csv \
    --target activity \
    --task-type classification \
    --epochs 20
```

## 常见模式与最佳实践

### 模式 1:对分子数据始终使用骨架切分(Scaffold Splitting)
```python
# GOOD: Prevents data leakage
splitter = dc.splits.ScaffoldSplitter()
train, test = splitter.train_test_split(dataset)

# BAD: Similar molecules in train and test
splitter = dc.splits.RandomSplitter()
train, test = splitter.train_test_split(dataset)
```

### 模式 2:对特征和目标值做归一化
```python
transformers = [
    dc.trans.NormalizationTransformer(
        transform_y=True,  # Also normalize target values
        dataset=train
    )
]
for transformer in transformers:
    train = transformer.transform(train)
    test = transformer.transform(test)
```

### 模式 3:从简单开始，再逐步扩展规模
1. 先从随机森林(Random Forest)+ CircularFingerprint 开始(快速基线)
2. 如果 RF 效果不错，尝试 XGBoost/LightGBM
3. 如果样本量超过 5000,转向深度学习(MultitaskRegressor)
4. 如果样本量超过 10000,尝试 GNN
5. 对于小数据集或新颖骨架，使用迁移学习

### 模式 4:处理不均衡数据
```python
# Option 1: Balancing transformer
transformer = dc.trans.BalancingTransformer(dataset=train)
train = transformer.transform(train)

# Option 2: Use balanced metrics
metric = dc.metrics.Metric(dc.metrics.balanced_accuracy_score)
```

### 模式 5:避免内存问题
```python
# Use DiskDataset for large datasets
dataset = dc.data.DiskDataset.from_numpy(X, y, w, ids)

# Use smaller batch sizes
model = dc.models.GCNModel(batch_size=32)  # Instead of 128
```

## 常见陷阱

### 问题 1:药物发现中的数据泄漏
**问题**:使用随机切分会导致相似的分子同时出现在训练集和测试集中。
**解决方案**:对分子数据集始终使用 `ScaffoldSplitter`。

### 问题 2:GNN 表现不如指纹方法
**问题**:图神经网络的表现比简单的指纹方法更差。
**解决方案**:
- 确保数据集足够大(通常需要超过 10000 个样本)
- 增加训练轮数(50-100)
- 尝试不同的架构(用 AttentiveFP、DMPNN 代替 GCN)
- 使用预训练模型(GROVER)

### 问题 3:在小数据集上过拟合
**问题**:模型死记硬背训练数据。
**解决方案**:
- 使用更强的正则化(将 dropout 提高到 0.5)
- 使用更简单的模型(用随机森林代替深度学习)
- 应用迁移学习(ChemBERTa、GROVER)
- 收集更多数据

### 问题 4:导入错误
**问题**:出现 `No module named 'torch'` / `No module named 'tensorflow'`
警告，或模型类导入失败。
**解决方案**:DeepChem 采用惰性加载——安装与你所用模型匹配的后端，然后
添加对应的附加组件:
```bash
uv pip install deepchem              # loaders, featurizers, MoleculeNet only
uv pip install 'deepchem[torch]'       # GCN, GAT, AttentiveFP, HuggingFaceModel, GroverModel
uv pip install 'deepchem[tensorflow]'  # legacy Keras models
uv pip install 'deepchem[jax]'         # Haiku/JAX models
```
在使用 GPU 时，要**在**安装附加组件**之前**先安装正确 CUDA 版本的
PyTorch 或 TensorFlow。在 zsh 中要给附加组件加引号:`'deepchem[torch]'`。

**Conda + PyTorch 用户**: 如果 `import deepchem` 报错
`undefined symbol: iJIT_NotifyEvent`,应将 MKL 锁定在 2025 以下版本
(`conda install "mkl<2025"`)——PyTorch 的 wheel 包可能与 MKL 2025.0.0
不兼容。

## 参考文档

本技能包含全面的参考文档:

### `references/api_reference.md`
完整的 API 文档，包括:
- 所有数据加载器及其适用场景
- 数据集类及各自的使用时机
- 完整的特征化器目录及选型指南
- 按类别整理的模型目录(50+ 个模型)
- MoleculeNet 数据集说明
- 评估指标与评估函数
- 常见代码模式

**何时查阅**:当你需要具体的 API 细节、参数名称，或想探索有哪些可用选项
时，查阅这份文件。

### `references/workflows.md`
八个详细的端到端工作流程:
1. 从 SMILES 出发做分子性质预测
2. 使用 MoleculeNet 基准
3. 超参数优化
4. 使用预训练模型做迁移学习
5. 用 GAN 做分子生成
6. 材料性质预测
7. 蛋白质序列分析
8. 自定义模型集成

**何时查阅**:把这些工作流程当作实现完整解决方案时的模板来使用。

## 安装

核心包(数据加载器、特征化器、MoleculeNet、scikit-learn 包装器):

```bash
uv pip install deepchem
```

添加与你的模型后端匹配的附加组件(使用 GPU 构建时先安装
PyTorch/TensorFlow/JAX):

```bash
uv pip install 'deepchem[torch]'       # GNNs, TorchModel, HuggingFaceModel, GroverModel
uv pip install 'deepchem[tensorflow]'  # Keras/TensorFlow models
uv pip install 'deepchem[jax]'         # JAX/Haiku models
uv pip install 'deepchem[dqc]'         # Differentiable quantum chemistry (torch + xitorch)
```

每日构建版本:`uv pip install --pre deepchem`(附加组件用法相同，加上
`--pre` 即可)。

关于每类模型的可选依赖，参见
[安装指南](https://deepchem.readthedocs.io/en/latest/get_started/installation.html)
和 [软性依赖要求](https://deepchem.readthedocs.io/en/latest/requirements.html)。

## 其他资源

- 官方文档: https://deepchem.readthedocs.io/
- GitHub 仓库: https://github.com/deepchem/deepchem
- 教程: https://deepchem.readthedocs.io/en/latest/get_started/tutorials.html
- 论文: "MoleculeNet: A Benchmark for Molecular Machine Learning"
