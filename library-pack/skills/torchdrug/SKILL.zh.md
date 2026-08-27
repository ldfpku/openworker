# TorchDrug

将 TorchDrug 作为一个模块化的 PyTorch 图学习技术栈来使用：

1. 加载一个 `datasets.*` 数据集，
2. 选择一个 `models.*` 表征模型，
3. 将其封装到一个 `tasks.*` 目标任务中，
4. 使用 `core.Engine` 进行训练和评估。

当前的官方文档与最新发行版均为 **0.2.1**。应将更新的 Python 或 PyTorch
组合视为未经验证，而不是默认其兼容。

## 从版本检查开始

在生成或调试代码之前，先检查环境：

```bash
python --version
python -c "import torch; print(torch.__version__)"
python -c "import torchdrug; print(torchdrug.__version__)"
```

TorchDrug 0.2.1 所支持的版本矩阵为：

- Python 3.7 到 3.10
- PyTorch 1.8 到 2.0
- Linux、Windows 或 macOS
- Apple Silicon：PyTorch 1.13 或更高版本，仅支持 CPU；不支持 MPS

如果项目使用 Python 3.11+ 或 PyTorch 2.1+，应创建兼容的环境，
或明确测试源码构建方式。不得将此类组合当作受支持的组合呈现。

## 安装

优先使用专用的 Python 3.10 环境，并固定 TorchDrug 的发行版本：

```bash
uv venv --python 3.10
source .venv/bin/activate
uv pip install "torch==2.0.0"
```

按照
[官方安装页面](https://torchdrug.ai/docs/installation.html)，安装与确切的
PyTorch 及 CUDA 版本组合相匹配的 `torch-scatter` 和 `torch-cluster` wheel 包。对于
仅使用 CPU 的 PyTorch 2.0 环境，一个可复现的 wheel 组合示例是：

```bash
uv pip install "torch-scatter==2.1.1" "torch-cluster==1.6.1" \
  --find-links "https://data.pyg.org/whl/torch-2.0.0+cpu.html"
uv pip install "torchdrug==0.2.1"
```

不得在不同环境之间复用同一个 CUDA wheel 的 URL。必须让 PyTorch 版本、
CUDA 构建版本、Python ABI 及平台相互匹配。在 Apple Silicon 上，官方文档要求
从源码构建 `torch-scatter` 和 `torch-cluster`；应固定经过审查的源码版本，
并预期只能在 CPU 上执行。

## 标准的属性预测工作流

使用文档记载的 ClinTox → GIN → `PropertyPrediction` → `Engine` 模式：

```python
import torch
from torchdrug import core, datasets, models, tasks

dataset = datasets.ClinTox("~/molecule-datasets/")
lengths = [int(0.8 * len(dataset)), int(0.1 * len(dataset))]
lengths.append(len(dataset) - sum(lengths))
train_set, valid_set, test_set = torch.utils.data.random_split(dataset, lengths)

model = models.GIN(
    input_dim=dataset.node_feature_dim,
    hidden_dims=[256, 256, 256, 256],
    short_cut=True,
    batch_norm=True,
    concat_hidden=True,
)
task = tasks.PropertyPrediction(
    model,
    task=dataset.tasks,
    criterion="bce",
    metric=("auprc", "auroc"),
)

optimizer = torch.optim.Adam(task.parameters(), lr=1e-3)
solver = core.Engine(
    task,
    train_set,
    valid_set,
    test_set,
    optimizer,
    batch_size=1024,
)
solver.train(num_epoch=100)
solver.evaluate("valid")
```

仅在存在受支持的 CUDA 设备时才添加 `gpus=[0]`。若要在 CPU 上执行，
应省略 `gpus` 参数。

对于二分类任务，`task.predict(batch)` 返回的是 logits；若需要概率值，
应应用 `torch.sigmoid`。在 0.2.1 中，归一化的回归
预测结果会以原始目标尺度返回，这是相对于旧版本的一项破坏性变更。

## 选择官方工作流

### 分子属性预测

- 数据集：`datasets.ClinTox`、`BBBP`、`Tox21`、`QM9`，或其他文档记载的
  分子数据集。
- 模型：先从 `models.GIN` 开始；当所选的特征配置提供了边特征时，
  使用 `edge_input_dim`。
- 任务：`tasks.PropertyPrediction`。
- 阅读[分子属性预测](references/molecular_property_prediction.md)。

### 分子自监督预训练

- InfoGraph：用 `tasks.Unsupervised` 封装的
  `models.InfoGraph(gin_model, separate_model=False)`。
- 属性掩码（Attribute masking）：`tasks.AttributeMasking(model, mask_rate=0.15)`。
- 为微调（fine-tuning）重新创建同样的编码器，然后在训练
  `tasks.PropertyPrediction` 之前以 `strict=False` 加载检查点（checkpoint）。
- 阅读[分子属性预测](references/molecular_property_prediction.md)。

### 分子生成

- 数据集：`datasets.ZINC250k(..., kekulize=True, atom_feature="symbol")`。
- GCPN：用 `tasks.GCPNGeneration` 封装的 `models.RGCN` 编码器。
- GraphAF：用 `tasks.AutoregressiveGeneration` 封装的节点和边
  `models.GraphAF` 流（flow）。
- 教程中支持的优化任务为 `"qed"` 和 `"plogp"`；
  评判标准为 `"nll"` 和/或 `"ppo"`。
- 阅读[分子生成](references/molecular_generation.md)。

### 逆合成分析（Retrosynthesis）

- 创建两个同步的 `datasets.USPTO50k` 视图：用于反应中心识别的
  反应模式，以及用于合成子（synthon）补全的 `as_synthon=True`。
- 分别训练 `tasks.CenterIdentification` 和 `tasks.SynthonCompletion`。
- 用 `tasks.Retrosynthesis` 组合已训练好的任务；不要将原始模型直接
  传给端到端任务。
- 阅读[逆合成分析](references/retrosynthesis.md)。

### 知识图谱推理

- 嵌入式工作流：`datasets.FB15k237` → `models.RotatE` →
  `tasks.KnowledgeGraphCompletion`。
- 神经推理工作流：`models.NeuralLP` 配合 `fact_ratio=0.75`。
- 阅读[知识图谱推理](references/knowledge_graphs.md)。

### 蛋白质建模

- 使用 `data.Protein.from_sequence`、`from_pdb` 或
  `from_molecule` 构建蛋白质。
- 序列编码器包括 `models.ESM`、`ProteinCNN`、`ProteinResNet`、
  `ProteinLSTM` 和 `ProteinBERT`；结构编码器包括 `models.GearNet`。
- 应使用文档记载的图构建层，而不是并不存在的
  `protein.residue_graph()` 便捷方法。
- 阅读[蛋白质建模](references/protein_modeling.md)。

## 确保 TorchDrug 代码可靠的规则

1. **遵循 0.2.1 版 API**。 官方文档并非滚动更新到最新版本的站点。
2. **优先使用文档记载的特征名称**。 应使用 `atom_feature`、`bond_feature`、
   `residue_feature` 和 `mol_feature`；在相关数据集构造函数中，
   `node_feature`、`edge_feature` 和 `graph_feature` 均为已弃用的别名。
3. **让 `Engine` 预处理任务。** 若在不构建其求解器（solver）的情况下
   组合预训练任务，应手动调用每个任务的 `preprocess()`。
4. **保持配对的数据切分同步**。 对于逆合成分析，在切分反应数据集和
   合成子数据集之前，应重置为相同的随机种子。
5. **使用 TorchDrug 的整理（collation）方式**。 应使用 `data.graph_collate`
   或 `core.Engine`；通用的 PyTorch 整理方式不知道如何打包 TorchDrug 的图数据。
6. **将模型、任务及引擎参数区分开来**。 一个常见的臆造代码来源是
   将任务选项传给模型，或在需要组合任务的地方传入原始模型。
7. **验证生成的化学结构**。 应将模型输出视为候选结果，而非
   经过实验验证的有效或可合成的化合物。

## 故障排查

### 安装或导入失败

应将 Python、PyTorch、`torch-scatter` 和 `torch-cluster` 作为一个整体
兼容性组合来检查。大多数失败源于二进制 wheel 不匹配、
不受支持的 Python 版本，或尝试使用 MPS。

### 特征维度不匹配

应根据已加载的数据集来构建模型维度：

- `dataset.node_feature_dim`
- `dataset.edge_feature_dim`
- `dataset.num_bond_type`
- 对于知识图谱，使用 `dataset.num_entity` 和 `dataset.num_relation`

不得硬编码从不同特征配置中复制来的维度数值。

### 设备不匹配

若要进行受支持的 CUDA 执行，应向 `core.Engine` 传入 `gpus=[0]`。若为手动
预测，应先进行整理（collate），再用 `utils.cuda` 移动整个嵌套的批次数据。

### 检查点（Checkpoint）不匹配

应重新创建相同的模型和特征配置。对于从预训练到微调的迁移，
应以 `strict=False` 加载检查点中的 `"model"` 状态；对于完整的求解器，
应使用 `solver.save()` 和 `solver.load()`。

## 参考资料索引

- [核心概念与数据结构](references/core_concepts.md)
- [数据集](references/datasets.md)
- [模型与架构](references/models_architectures.md)
- [分子属性预测与预训练](references/molecular_property_prediction.md)
- [蛋白质建模](references/protein_modeling.md)
- [分子生成](references/molecular_generation.md)
- [逆合成分析](references/retrosynthesis.md)
- [知识图谱推理](references/knowledge_graphs.md)

## 上游来源

- [TorchDrug 0.2.1 文档](https://torchdrug.ai/docs/)
- [教程索引](https://torchdrug.ai/docs/tutorials/)
- [安装说明](https://torchdrug.ai/docs/installation.html)
- [软件包参考](https://torchdrug.ai/docs/api/)
- [TorchDrug 0.2.1 发行说明](https://github.com/DeepGraphLearning/torchdrug/releases/tag/v0.2.1)
