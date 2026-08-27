# Arboreto

## 概述

Arboreto 是一个由 [Aerts Lab](https://github.com/aertslab/arboreto) 开发的 Python 库，用于从基因表达数据推断基因调控网络（gene regulatory networks, GRNs）。它借助 [Dask](https://distributed.dask.org/) 在本地多核或远程集群上并行执行基于树的集成回归算法（GRNBoost2、GENIE3）。

**核心能力**：根据跨观测样本（细胞、样本、条件）的表达模式，识别哪些转录因子（transcription factors, TF）调控哪些靶基因。

**上游项目**：PyPI **0.1.6**（2021-02-09，最新版本）。文档：[arboreto.readthedocs.io](https://arboreto.readthedocs.io/en/latest/)。主要下游使用者：[pySCENIC](https://github.com/aertslab/pySCENIC)。

## 快速入门

安装 arboreto：
```bash
uv pip install arboreto
```

基本的 GRN 推断：
```python
import pandas as pd
from arboreto.algo import grnboost2

if __name__ == '__main__':
    # Load expression data (genes as columns)
    expression_matrix = pd.read_csv('expression_data.tsv', sep='\t')

    # Infer regulatory network
    network = grnboost2(expression_data=expression_matrix)

    # Save results (TF, target, importance)
    network.to_csv('network.tsv', sep='\t', index=False, header=False)
```

**关键点**：始终使用 `if __name__ == '__main__':` 保护语句，因为 Dask 会派生（spawn）新进程。

## 核心能力

### 1. 基本 GRN 推断

用于标准的 GRN 推断工作流，包括：
- 输入数据准备（Pandas DataFrame 或 NumPy 数组）
- 使用 GRNBoost2 或 GENIE3 运行推断
- 按转录因子进行过滤
- 输出格式及结果解读

**参见**：`references/basic_inference.md`

**使用现成可运行的脚本**：对于标准的推断任务，使用 `scripts/basic_grn_inference.py`：
```bash
python scripts/basic_grn_inference.py expression_data.tsv output_network.tsv --tf-file tfs.txt --seed 777 --limit 5000
```

### 2. 算法选择

Arboreto 提供两种算法：

**GRNBoost2（推荐）**：
- 基于梯度提升（gradient boosting）的快速推断
- 针对大型数据集（1万+ 观测样本）进行了优化
- 大多数分析场景下的默认选择

**GENIE3**：
- 基于随机森林（Random Forest）的推断
- 最初提出的多元回归方法
- 用于比较或验证

快速对比：
```python
from arboreto.algo import grnboost2, genie3

# Fast, recommended
network_grnboost = grnboost2(expression_data=matrix)

# Classic algorithm
network_genie3 = genie3(expression_data=matrix)
```

**关于详细的算法对比、参数说明及选择指导**：`references/algorithms.md`

### 3. 分布式计算

将推断规模从本地多核扩展到集群环境：

**本地（默认）** —— 自动使用所有可用的核心：
```python
network = grnboost2(expression_data=matrix)
```

**自定义本地客户端** —— 控制资源用量：
```python
from distributed import LocalCluster, Client

local_cluster = LocalCluster(n_workers=10, memory_limit='8GB')
client = Client(local_cluster)

network = grnboost2(expression_data=matrix, client_or_address=client)

client.close()
local_cluster.close()
```

**集群计算** —— 连接到远程 Dask 调度器：
```python
from distributed import Client

client = Client('tcp://scheduler:8786')
network = grnboost2(expression_data=matrix, client_or_address=client)
```

**关于集群搭建、性能优化及大规模工作流**：`references/distributed_computing.md`

## 安装

```bash
uv pip install arboreto
```

Conda（Bioconda）：

```bash
conda install -c bioconda arboreto
```

**依赖项**（来自上游的 `requirements.txt`）：`dask[complete]`、`distributed`、`numpy`、`pandas`、`scikit-learn`、`scipy`

**输入格式**：pandas DataFrame、稠密的 `numpy.ndarray`，或稀疏的 `scipy.sparse.csc_matrix`（行 = 观测样本，列 = 基因）。对于数组/矩阵形式的输入，需要显式传入 `gene_names`。

## 常见用例

### 单细胞 RNA-seq 分析
```python
import pandas as pd
from arboreto.algo import grnboost2

if __name__ == '__main__':
    # Load single-cell expression matrix (cells x genes)
    sc_data = pd.read_csv('scrna_counts.tsv', sep='\t')

    # Infer cell-type-specific regulatory network
    network = grnboost2(expression_data=sc_data, seed=42)

    # Filter high-confidence links
    high_confidence = network[network['importance'] > 0.5]
    high_confidence.to_csv('grn_high_confidence.tsv', sep='\t', index=False)
```

### 带转录因子过滤的 Bulk RNA-seq
```python
from arboreto.utils import load_tf_names
from arboreto.algo import grnboost2

if __name__ == '__main__':
    # Load data
    expression_data = pd.read_csv('rnaseq_tpm.tsv', sep='\t')
    tf_names = load_tf_names('human_tfs.txt')

    # Infer with TF restriction
    network = grnboost2(
        expression_data=expression_data,
        tf_names=tf_names,
        seed=123
    )

    network.to_csv('tf_target_network.tsv', sep='\t', index=False)
```

### 对比分析（多种条件）
```python
from arboreto.algo import grnboost2

if __name__ == '__main__':
    # Infer networks for different conditions
    conditions = ['control', 'treatment_24h', 'treatment_48h']

    for condition in conditions:
        data = pd.read_csv(f'{condition}_expression.tsv', sep='\t')
        network = grnboost2(expression_data=data, seed=42)
        network.to_csv(f'{condition}_network.tsv', sep='\t', index=False)
```

## 输出结果解读

Arboreto 返回一个包含调控关系连边的 DataFrame：

| 列 | 说明 |
|--------|-------------|
| `TF` | 转录因子（调控因子） |
| `target` | 靶基因 |
| `importance` | 调控重要性分数（越高表示调控关系越强） |

**过滤策略**：
- 在推断时使用 `limit=N`（在全局范围内返回排名前 N 的连边）
- 事后设定重要性阈值（例如 > 0.5）
- 通过 `groupby('target')` 获取每个靶基因的最佳连边
- 统计显著性检验（置换检验、外部工具）

## 与 pySCENIC 的集成

Arboreto 驱动着 [pySCENIC](https://github.com/aertslab/pySCENIC) 中的 GRN 推断步骤。pySCENIC 0.11+ 将稀疏表达矩阵传递给 `grnboost2` / `genie3`；pySCENIC 0.12+ 出于兼容性考虑，默认使用 `arboreto_with_multiprocessing.py`（不使用 Dask）——当你需要 Dask 扩展能力时，请使用独立的 arboreto。

```python
# Standalone: infer co-expression modules before pySCENIC cisTarget pruning
from arboreto.algo import grnboost2

network = grnboost2(expression_data=expression_df, tf_names=tf_list, limit=5000)

# Downstream: pySCENIC ctx pruning, regulon definition, AUCell (see pySCENIC docs)
```

直接将 AnnData 转换为 arboreto 所需的 DataFrame：

```python
expression_df = adata.to_df()  # cells x genes
```

## 可复现性

始终设置随机种子（seed）以获得可复现的结果：
```python
network = grnboost2(expression_data=matrix, seed=777)
```

运行多个随机种子以进行稳健性分析：
```python
from distributed import LocalCluster, Client

if __name__ == '__main__':
    client = Client(LocalCluster())

    seeds = [42, 123, 777]
    networks = []

    for seed in seeds:
        net = grnboost2(expression_data=matrix, client_or_address=client, seed=seed)
        networks.append(net)

    # Consensus: links recurring across runs (example: mean importance per TF-target pair)
    import pandas as pd
    combined = pd.concat(networks)
    consensus = (
        combined.groupby(['TF', 'target'], as_index=False)['importance']
        .mean()
        .query('importance > 0.5')
    )
```

## 常见问题排查

**内存错误**：通过过滤低方差基因来缩减数据集规模，或使用分布式计算

**性能缓慢**：使用 GRNBoost2 而非 GENIE3，启用分布式客户端，过滤转录因子列表

**Dask 错误**：确保脚本中存在 `if __name__ == '__main__':` 保护语句（在使用基于 spawn 的多进程机制的 Windows/macOS 上是必需的）

**结果为空**：检查数据格式（基因应作为列），核实转录因子名称与表达矩阵中的列名相匹配

**稀疏数据**：使用 `scipy.sparse.csc_matrix` 并传入相匹配的 `gene_names`；自 arboreto 0.1.6 / pySCENIC 0.11 起支持
