# PyTorch Geometric (PyG)

PyG 是构建在 PyTorch 之上的图神经网络（Graph Neural Network）标准库。它提供了图的数据结构、
60 多种 GNN 层实现、可扩展的小批量训练，以及对异构图的支持。

## 安装

已针对 **torch-geometric 2.7.x**（2025 年 10 月）测试。需要 **Python 3.10+** 和 **PyTorch 2.6+**。

```bash
# 1. Install PyTorch first (match your CUDA/CPU setup — see https://pytorch.org/get-started/locally/)
uv pip install torch

# 2. 核心 PyG（基础用法不需要额外的扩展 wheel）
uv pip install torch_geometric
```

可选的加速算子（`pyg-lib`、`torch-scatter`、`torch-sparse`、`torch-cluster`）对于基础 PyG 用法
**并非必需**（自 PyG 2.3 起）。在确认你的 PyTorch 和 CUDA 版本后，从
[PyG wheel 索引](https://data.pyg.org/whl)安装与版本匹配的 wheel：

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda)"
# 然后为你的 torch+CUDA 组合安装对应的 wheel，例如：
uv pip install pyg-lib torch-scatter torch-sparse torch-cluster \
  -f https://data.pyg.org/whl/torch-2.8.0+cu128.html
```

检查你的版本：

```python
import torch_geometric
print(torch_geometric.__version__)
```

**Conda**： `pyg` conda 频道已不再为 PyTorch >2.5 维护——请改用上面的 `uv pip install`
和 wheel 索引。

### PyG 2.7 说明

PyG 2.7 已弃用对 Python 3.9 和 PyTorch ≤2.5 的支持。关于 PyTorch 2.6–2.8 的兼容性表，
参见 [2.7.0 发布说明](https://github.com/pyg-team/pytorch_geometric/releases/tag/2.7.0)。
`torch_geometric.distributed` 已弃用——请改用标准的 `torch.distributed` DDP
（见 `references/scaling.md`）。

## 核心概念

### 图数据：`Data` 与 `HeteroData`

一张图存放在一个 `Data` 对象中。关键属性如下：

```python
from torch_geometric.data import Data

data = Data(
    x=node_features,          # [num_nodes, num_node_features]
    edge_index=edge_index,     # [2, num_edges] — COO format, dtype=torch.long
    edge_attr=edge_features,   # [num_edges, num_edge_features]
    y=labels,                  # node-level [num_nodes, *] or graph-level [1, *]
    pos=positions,             # [num_nodes, num_dimensions] (for point clouds/spatial)
)
```

**`edge_index` 的格式至关重要**：它是一个 `[2, num_edges]` 的张量，其中 `edge_index[0]`
是源节点，`edge_index[1]` 是目标节点。它*不是*一个元组列表。如果你手头的边是按行排列的
节点对，需要先转置再调用 `.contiguous()`：

```python
# If edges are [[src1, dst1], [src2, dst2], ...] — transpose first:
edge_index = edge_pairs.t().contiguous()
```

对于无向图，需要包含两个方向：边 (0,1) 需要在 edge_index 中同时出现 `[0,1]` 和 `[1,0]`。

对于异构图，请使用 `HeteroData`——参见下方的"异构图"一节。

### 数据集

PyG 内置了许多标准数据集，可自动下载和预处理：

```python
from torch_geometric.datasets import Planetoid, TUDataset

# Single-graph node classification (Cora, Citeseer, Pubmed)
dataset = Planetoid(root='./data', name='Cora')
data = dataset[0]  # single graph with train/val/test masks

# Multi-graph classification (ENZYMES, MUTAG, IMDB-BINARY, etc.)
dataset = TUDataset(root='./data', name='ENZYMES')
# dataset[0], dataset[1], ... are individual graphs
```

按任务分类的常用数据集：
- **节点分类（Node classification）**：Planetoid（Cora/Citeseer/Pubmed）、OGB（ogbn-arxiv、ogbn-products、ogbn-mag）
- **图分类（Graph classification）**：TUDataset（MUTAG、ENZYMES、PROTEINS、IMDB-BINARY）、OGB（ogbg-molhiv）
- **链接预测（Link prediction）**：OGB（ogbl-collab、ogbl-citation2）
- **分子（Molecular）**：QM7、QM9、MoleculeNet
- **点云/网格（Point cloud/mesh）**：ShapeNet、ModelNet10/40、FAUST

### 变换（Transforms）

变换用于对图数据做预处理或增强，类似于 torchvision 的 transforms：

```python
import torch_geometric.transforms as T

# Common transforms
T.NormalizeFeatures()    # Row-normalize node features to sum to 1
T.ToUndirected()         # Add reverse edges to make graph undirected
T.AddSelfLoops()         # Add self-loop edges
T.KNNGraph(k=6)          # Build k-NN graph from point cloud positions
T.RandomJitter(0.01)     # Random noise augmentation on positions
T.Compose([...])         # Chain multiple transforms

# Apply as pre_transform (once, saved to disk) or transform (every access)
dataset = ShapeNet(root='./data', pre_transform=T.KNNGraph(k=6),
                   transform=T.RandomJitter(0.01))
```

## 构建 GNN 模型

### 快速开始：使用内置层

构建 GNN 最快的方式——从 `torch_geometric.nn` 中堆叠卷积层：

```python
import torch
import torch.nn.functional as F
from torch_geometric.nn import GCNConv

class GCN(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super().__init__()
        self.conv1 = GCNConv(in_channels, hidden_channels)
        self.conv2 = GCNConv(hidden_channels, out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index).relu()
        x = F.dropout(x, p=0.5, training=self.training)
        x = self.conv2(x, edge_index)
        return x
```

**重要**：PyG 的卷积层不包含激活函数——需要在每层之后自行应用。这是出于灵活性的设计考虑。

### 选择卷积层

根据你的任务和图结构进行选择：

| 层 | 最适用于 | 关键思想 |
|-------|----------|----------|
| `GCNConv` | 同构图、半监督节点分类 | 谱方法启发、按度归一化的聚合 |
| `GATConv` / `GATv2Conv` | 邻居重要性各不相同时 | 注意力加权的消息 |
| `SAGEConv` | 大规模图、归纳（inductive）场景 | 适合采样、可学习的聚合方式 |
| `GINConv` | 图分类、最大化表达能力 | 与 WL 测试同等强大 |
| `TransformerConv` | 丰富的边特征、复杂交互 | 带边特征的多头注意力 |
| `EdgeConv` | 点云、动态图 | 对边特征 (x_i, x_j - x_i) 使用 MLP |
| `RGCNConv` | 具有多种关系类型的异构图 | 关系专属的权重矩阵 |
| `HGTConv` | 异构图 | 类型专属的注意力 |

所有卷积层至少接受 `(x, edge_index)`。许多层还接受 `edge_attr` 作为边特征。

### 惰性初始化（Lazy Initialization）

使用 `-1` 作为输入通道数，可让 PyG 自动推断维度——对异构模型尤其有用：

```python
conv = SAGEConv((-1, -1), 64)  # Input dims inferred on first forward pass
# Initialize lazy modules:
with torch.no_grad():
    out = model(data.x, data.edge_index)
```

### 高层模型 API

对于常见架构，PyG 提供了现成的模型类：

```python
from torch_geometric.nn import GraphSAGE, GCN, GAT, GIN

model = GraphSAGE(
    in_channels=dataset.num_features,
    hidden_channels=64,
    out_channels=dataset.num_classes,
    num_layers=2,
)
```

### 通过 MessagePassing 自定义层

要实现一种新颖的 GNN 层，需继承 `MessagePassing`。该框架分为以下几步：

1. `propagate()` 负责编排消息传递
2. `message()` 定义沿每条边流动的信息内容（即 phi 函数）
3. `aggregate()` 在每个节点上汇聚消息（求和/求平均/取最大值）
4. `update()` 对汇聚结果做变换（即 gamma 函数）

```python
from torch_geometric.nn import MessagePassing
from torch_geometric.utils import add_self_loops, degree

class MyConv(MessagePassing):
    def __init__(self, in_channels, out_channels):
        super().__init__(aggr='add')  # "add", "mean", or "max"
        self.lin = torch.nn.Linear(in_channels, out_channels)

    def forward(self, x, edge_index):
        # Pre-processing before message passing
        x = self.lin(x)
        # Start message passing
        return self.propagate(edge_index, x=x)

    def message(self, x_j):
        # x_j: features of source nodes for each edge [num_edges, features]
        # The _j suffix auto-indexes source nodes, _i indexes target nodes
        return x_j
```

**`_i` / `_j` 约定**：传给 `propagate()` 的任何张量，都可以通过在 `message()` 的函数签名中
附加 `_i`（目标/中心节点）或 `_j`（源/邻居节点）后缀来自动索引。所以如果你把 `x=...`
传给 propagate，就可以在 message() 中访问 `x_i` 和 `x_j`。

完整的 GCN 和 EdgeConv 实现示例请阅读 `references/message_passing.md`。

## 特定任务模式

### 节点分类

```python
# Full-batch training on a single graph (e.g., Cora)
model.train()
for epoch in range(200):
    optimizer.zero_grad()
    out = model(data.x, data.edge_index)
    loss = F.cross_entropy(out[data.train_mask], data.y[data.train_mask])
    loss.backward()
    optimizer.step()

# Evaluation — train(False) puts the model in inference mode (disables dropout/BN)
model.train(False)
pred = model(data.x, data.edge_index).argmax(dim=1)
acc = (pred[data.test_mask] == data.y[data.test_mask]).float().mean()
```

### 图分类

多个图——使用 `DataLoader` 做小批量训练，用全局池化（global pooling）得到图级别的表示：

```python
from torch_geometric.loader import DataLoader
from torch_geometric.nn import GCNConv, global_mean_pool

loader = DataLoader(dataset, batch_size=32, shuffle=True)

class GraphClassifier(torch.nn.Module):
    def __init__(self, in_ch, hidden_ch, out_ch):
        super().__init__()
        self.conv1 = GCNConv(in_ch, hidden_ch)
        self.conv2 = GCNConv(hidden_ch, hidden_ch)
        self.lin = torch.nn.Linear(hidden_ch, out_ch)

    def forward(self, x, edge_index, batch):
        x = self.conv1(x, edge_index).relu()
        x = self.conv2(x, edge_index).relu()
        x = global_mean_pool(x, batch)  # [num_graphs_in_batch, hidden_ch]
        return self.lin(x)

# Training loop
for data in loader:
    out = model(data.x, data.edge_index, data.batch)
    loss = F.cross_entropy(out, data.y)
```

PyG 的 `DataLoader` 通过构造块对角邻接矩阵（block-diagonal adjacency matrices）来对多个图
进行批处理。`batch` 张量将每个节点映射到其所属的图索引。池化操作
（`global_mean_pool`、`global_max_pool`、`global_add_pool`）利用它按图聚合。

### 链接预测

将边划分为训练/验证/测试集，并使用负采样：

```python
from torch_geometric.transforms import RandomLinkSplit

transform = RandomLinkSplit(
    num_val=0.1,
    num_test=0.1,
    is_undirected=True,
    add_negative_train_samples=False,
)
train_data, val_data, test_data = transform(data)

# Encode nodes, then score edges
z = model.encode(train_data.x, train_data.edge_index)
# Positive edges
pos_score = (z[train_data.edge_label_index[0]] * z[train_data.edge_label_index[1]]).sum(dim=1)
```

完整的链接预测指南——GAE/VGAE 自编码器、完整训练循环、用于大规模图的
LinkNeighborLoader、异构链接预测，以及评估指标——请阅读 `references/link_prediction.md`。

## 扩展到大规模图

对于无法装入 GPU 显存的图，使用 `NeighborLoader` 进行邻居采样：

```python
from torch_geometric.loader import NeighborLoader

train_loader = NeighborLoader(
    data,
    num_neighbors=[15, 10],     # Sample 15 neighbors in hop 1, 10 in hop 2
    batch_size=128,              # Number of seed nodes per batch
    input_nodes=data.train_mask, # Which nodes to sample from
    shuffle=True,
)

for batch in train_loader:
    batch = batch.to(device)
    out = model(batch.x, batch.edge_index)
    # Only use first batch_size nodes for loss (these are the seed nodes)
    loss = F.cross_entropy(out[:batch.batch_size], batch.y[:batch.batch_size])
```

**关于 NeighborLoader 的要点**：
- `num_neighbors` 列表的长度应与 GNN 深度（消息传递层数）相匹配
- 种子节点（seed nodes）在输出中始终是前 `batch.batch_size` 个节点
- `batch.n_id` 将重新编号后的索引映射回原始节点 ID
- 同时适用于 `Data` 和 `HeteroData`
- 对于链接预测，请改用 `LinkNeighborLoader`
- 采样超过 2-3 跳通常是不可行的（指数级膨胀）

其他可扩展性选项：`ClusterLoader`（ClusterGCN）、`GraphSAINTSampler`、`ShaDowKHopSampler`。
关于多 GPU 训练、DDP、PyTorch Lightning 集成，以及 `torch.compile` 支持，
请阅读 `references/scaling.md`。

## 异构图

对于具有多种节点类型和边类型的图（社交网络、知识图谱、推荐系统）：

```python
from torch_geometric.data import HeteroData

data = HeteroData()

# Node features — indexed by node type string
data['user'].x = torch.randn(1000, 64)
data['movie'].x = torch.randn(500, 128)

# Edge indices — indexed by (src_type, edge_type, dst_type) triplet
data['user', 'rates', 'movie'].edge_index = torch.randint(0, 500, (2, 3000))
data['user', 'follows', 'user'].edge_index = torch.randint(0, 1000, (2, 5000))

# Access convenience dicts
data.x_dict        # {'user': tensor, 'movie': tensor}
data.edge_index_dict  # {('user','rates','movie'): tensor, ...}
data.metadata()    # ([node_types], [edge_types])
```

### 构建异构 GNN 的三种方式

**1. 用 `to_hetero()` 自动转换**——先写一个同构模型，再自动转换：

```python
from torch_geometric.nn import SAGEConv, to_hetero

class GNN(torch.nn.Module):
    def __init__(self, hidden_channels, out_channels):
        super().__init__()
        self.conv1 = SAGEConv((-1, -1), hidden_channels)
        self.conv2 = SAGEConv((-1, -1), out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index).relu()
        x = self.conv2(x, edge_index)
        return x

model = GNN(64, dataset.num_classes)
model = to_hetero(model, data.metadata(), aggr='sum')

# Now accepts dicts:
out = model(data.x_dict, data.edge_index_dict)
```

对于二部（bipartite）输入通道（源、目标可能不同），使用 `(-1, -1)`。惰性初始化会处理其余部分。

**2. `HeteroConv` 包装器**——为每种边类型使用不同的卷积：

```python
from torch_geometric.nn import HeteroConv, GCNConv, SAGEConv, GATConv

conv = HeteroConv({
    ('paper', 'cites', 'paper'): GCNConv(-1, 64),
    ('author', 'writes', 'paper'): SAGEConv((-1, -1), 64),
    ('paper', 'rev_writes', 'author'): GATConv((-1, -1), 64, add_self_loops=False),
}, aggr='sum')
```

**3. 原生的异构算子**，如 `HGTConv`：

```python
from torch_geometric.nn import HGTConv
conv = HGTConv(hidden_channels, hidden_channels, data.metadata(), num_heads=4)
```

**关于异构图的要点**：
- 使用 `T.ToUndirected()` 添加反向边类型，以实现双向消息流动
- 在二部（源/目标节点类型不同）卷积层中禁用 `add_self_loops`——改用跳跃连接
  （skip connections）：`conv(x, edge_index) + lin(x)`
- 对 HeteroData 使用 NeighborLoader 时，将 `input_nodes` 指定为 `('node_type', mask)` 元组
- `num_neighbors` 可以是按边类型区分的字典，以实现精细控制

包含训练循环及 HeteroData 上 NeighborLoader 用法的完整示例，请阅读 `references/heterogeneous.md`。

## 自定义数据集

将你自己的数据加载进 PyG：

- **快速方式（无需定义类）**：直接创建 `Data` 对象，并将列表传给 `DataLoader`
- **可复用方式（数据可放入内存）**：继承 `InMemoryDataset`——重写 `raw_file_names`、
  `processed_file_names`、`download()`、`process()`
- **大规模方式（依赖磁盘存储）**：继承 `Dataset`——同时还需重写 `len()` 和 `get()`
- **从 CSV 加载**：用 pandas 加载节点/边表，构建到连续索引的映射，再组装成
  `Data` 或 `HeteroData`
- **从 NetworkX 加载**：`from_networkx(G)` 可直接转换一个 NetworkX 图
- **从 scipy 稀疏矩阵加载**：`from_scipy_sparse_matrix(adj)` 提取 edge_index

包含所有模式的完整示例、带编码器的 CSV 加载，以及 MovieLens 演练，请阅读
`references/custom_datasets.md`。

## 可解释性

PyG 提供 `torch_geometric.explain` 用于解释 GNN 的预测：

```python
from torch_geometric.explain import Explainer, GNNExplainer

explainer = Explainer(
    model=model,
    algorithm=GNNExplainer(epochs=200),
    explanation_type='model',
    node_mask_type='attributes',
    edge_mask_type='object',
    model_config=dict(
        mode='multiclass_classification',
        task_level='node',
        return_type='log_probs',
    ),
)

explanation = explainer(data.x, data.edge_index, index=10)
explanation.visualize_graph()           # Important subgraph
explanation.visualize_feature_importance(top_k=10)  # Feature importance
```

可用算法：`GNNExplainer`（基于优化）、`PGExplainer`（参数化、需训练）、
`CaptumExplainer`（通过 Captum 实现的基于梯度的方法）、`AttentionExplainer`（注意力权重）。
对同构图和异构图均适用。

所有算法、异构图解释、评估指标，以及 PGExplainer 训练，请阅读 `references/explainability.md`。

## 常见陷阱

1. **edge_index 的形状**：必须是 `[2, num_edges]`，而不是 `[num_edges, 2]`。需要时请转置。
2. **忘记添加激活函数**：卷积层不包含 ReLU 等——需要手动添加。
3. **异构二部图中的自环（self-loops）**：当源节点类型和目标节点类型不同时，
   不要使用 `add_self_loops=True`。改用跳跃连接。
4. **NeighborLoader 的切片**：只有前 `batch.batch_size` 个节点是你的种子节点。
   预测值和标签应据此切片。
5. **无向图**：如果你的图是无向的，需要在 `edge_index` 中包含两个方向的边，
   或使用 `T.ToUndirected()`。
6. **惰性初始化**：输入通道为 `-1` 的模型，训练前需要先在 `torch.no_grad()` 下
   执行一次前向传播以初始化参数。
7. **图任务的全局池化**：使用 `global_mean_pool(x, batch)`（而不是手动 reshape）
   将节点特征聚合为图级别特征。
8. **num_neighbors 的对齐**：保持 `len(num_neighbors)` 等于 GNN 的层数。
   跳数多于层数会浪费计算；跳数少于层数则会浪费模型容量。
