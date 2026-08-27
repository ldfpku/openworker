# Dask

## 概述

Dask 是一个用于并行与分布式计算的 Python 库，它提供三项关键能力：
- 在单机上进行**超出内存容量的执行（larger-than-memory execution）**，处理超过可用内存的数据
- **并行处理（parallel processing）**，跨多核提升计算速度
- **分布式计算（distributed computation）**，支持跨多台机器处理 TB 级数据集

Dask 可以从笔记本电脑（处理约 100 GiB）扩展到集群（处理约 100 TiB），同时保持我们熟悉的 Python API。

**当前上游版本**： dask **2026.3.0**（PyPI，2026 年 3 月）。文档：[docs.dask.org](https://docs.dask.org/en/stable/)。自 **2025.1.0** 版本起，基于表达式（expression-based）并带查询规划（query planning）的 DataFrame API 已成为唯一实现——不要再单独安装
`dask-expr`，也不要设置 `dataframe.query-planning: False`。

## 快速入门

### 安装

```bash
uv pip install "dask>=2025.1"
```

对于典型的、使用分布式调度器（distributed scheduler）和仪表盘（dashboard）的 pandas/NumPy 工作流：

```bash
uv pip install "dask[complete]"
```

远程对象存储（S3、GCS、Azure）：

```bash
uv pip install s3fs    # s3:// paths
uv pip install gcsfs   # gs:// paths
```

需要 **Python 3.10+**（对 3.9 的支持已在 2024.12 版本中移除）。DataFrame 的 I/O 需要
**PyArrow 16+**（截至 dask 2026.1.2 版本）。

## 何时使用本技能

在以下情况下应使用本技能：
- 处理超出可用内存的数据集
- 将 pandas 或 NumPy 操作扩展到更大的数据集
- 为提升性能而并行化计算
- 高效处理多个文件（CSV、Parquet、JSON、文本日志）
- 构建带有任务依赖关系的自定义并行工作流
- 将工作负载分布到多个核心或多台机器上

## 核心能力

Dask 提供五个主要组件，各自适用于不同的使用场景：

### 1. DataFrame —— 并行的 Pandas 操作

**用途**：通过并行处理将 pandas 操作扩展到更大的数据集。

**何时使用**：
- 表格数据超出可用内存
- 需要把多个 CSV/Parquet 文件放在一起处理
- pandas 操作太慢，需要并行化
- 从 pandas 原型扩展到生产环境

**参考文档**：关于 Dask DataFrame 的完整说明，请参阅 `references/dataframes.md`，其中包括：
- 数据读取（单文件、多文件、glob 模式）
- 常见操作（筛选、分组聚合、连接、聚合运算）
- 使用 `map_partitions` 进行自定义操作
- 性能优化技巧
- 常见模式（ETL、时间序列、多文件处理）

**快速示例**：
```python
import dask.dataframe as dd

# Read multiple files as single DataFrame
ddf = dd.read_csv('data/2024-*.csv')

# Operations are lazy until compute()
filtered = ddf[ddf['value'] > 100]
result = filtered.groupby('category').mean().compute()
```

**要点**：
- 操作是惰性的（构建任务图），直到调用 `.compute()` 才会真正执行
- 对自定义操作使用 `map_partitions` 以获得高效执行
- 在处理来自其他来源的结构化数据时，应尽早转换为 DataFrame

### 2. Array —— 并行的 NumPy 操作

**用途**：使用分块算法（blocked algorithms），将 NumPy 的能力扩展到超出内存容量的数据集。

**何时使用**：
- 数组超出可用内存
- NumPy 操作需要并行化
- 处理科学数据集（HDF5、Zarr、NetCDF）
- 需要并行的线性代数或数组运算

**参考文档**：关于 Dask Array 的完整说明，请参阅 `references/arrays.md`，其中包括：
- 创建数组（从 NumPy、随机生成、从磁盘读取）
- 分块（chunking）策略与优化
- 常见操作（算术运算、归约、线性代数）
- 使用 `map_blocks` 进行自定义操作
- 与 HDF5、Zarr、XArray 的集成

**快速示例**：
```python
import dask.array as da

# Create large array with chunks
x = da.random.random((100000, 100000), chunks=(10000, 10000))

# Operations are lazy
y = x + 100
z = y.mean(axis=0)

# Compute result
result = z.compute()
```

**要点**：
- 分块大小（chunk size）至关重要（目标是每个分块约 100 MB）
- 操作是在各个分块上并行执行的
- 需要时可对数据重新分块（rechunk）以获得高效运算
- 对于 Dask 中没有提供的操作，使用 `map_blocks`

### 3. Bag —— 非结构化数据的并行处理

**用途**：以函数式操作处理非结构化或半结构化数据（文本、JSON、日志）。

**何时使用**：
- 处理文本文件、日志或 JSON 记录
- 在做结构化分析之前进行数据清洗和 ETL
- 处理不适合数组/DataFrame 格式的 Python 对象
- 需要内存高效的流式处理

**参考文档**：关于 Dask Bag 的完整说明，请参阅 `references/bags.md`，其中包括：
- 读取文本和 JSON 文件
- 函数式操作（map、filter、fold、groupby）
- 转换为 DataFrame
- 常见模式（日志分析、JSON 处理、文本处理）
- 性能方面的考量

**快速示例**：
```python
import dask.bag as db
import json

# Read and parse JSON files
bag = db.read_text('logs/*.json').map(json.loads)

# Filter and transform
valid = bag.filter(lambda x: x['status'] == 'valid')
processed = valid.map(lambda x: {'id': x['id'], 'value': x['value']})

# Convert to DataFrame for analysis
ddf = processed.to_dataframe()
```

**要点**：
- 先用它做初步的数据清洗，然后再转换为 DataFrame/Array
- 使用 `foldby` 而不是 `groupby` 以获得更好的性能
- 操作是流式且内存高效的
- 对复杂操作，应转换为结构化格式（DataFrame）

### 4. Futures —— 基于任务的并行化

**用途**：构建自定义的并行工作流，对任务执行和依赖关系拥有细粒度的控制。

**何时使用**：
- 构建动态、不断演变的工作流
- 需要立即执行任务（而非惰性执行）
- 计算依赖于运行时条件
- 实现自定义的并行算法
- 需要有状态的计算

**参考文档**：关于 Dask Futures 的完整说明，请参阅 `references/futures.md`，其中包括：
- 搭建分布式客户端（distributed client）
- 提交任务并使用 futures
- 任务依赖关系与数据移动
- 高级协调机制（队列、锁、事件、actor）
- 常见模式（参数扫描、动态任务、迭代算法）

**快速示例**：
```python
from dask.distributed import Client

client = Client()  # Create local cluster

# Submit tasks (executes immediately)
def process(x):
    return x ** 2

futures = client.map(process, range(100))

# Gather results
results = client.gather(futures)

client.close()
```

**要点**：
- 需要分布式客户端（即使是在单机上运行）
- 任务在提交时立即执行
- 应预先将大数据集散播（scatter）出去，以避免反复传输
- 每个任务约有 1ms 的开销（不适合成百万个微小任务的场景）
- 对有状态的工作流使用 actor

### 5. Schedulers —— 执行后端

**用途**：控制 Dask 任务在何处、以何种方式执行（线程、进程、分布式）。

**如何选择调度器（Scheduler）**：
- **线程（Threads，默认）**：适合 NumPy/Pandas 操作、能释放 GIL 的库、可从共享内存中获益的场景
- **进程（Processes）**：适合纯 Python 代码、文本处理、受 GIL 限制的操作
- **同步（Synchronous）**：适合用 pdb 调试、性能分析、理解报错
- **分布式（Distributed）**：需要仪表盘、多机集群、高级特性时使用

**参考文档**：关于 Dask Schedulers 的完整说明，请参阅 `references/schedulers.md`，其中包括：
- 各调度器的详细说明和特性
- 配置方式（全局、上下文管理器、按单次计算配置）
- 性能方面的考量和开销
- 常见模式与故障排查
- 为获得最佳性能而进行的线程配置

**快速示例**：
```python
import dask
import dask.dataframe as dd

# Use threads for DataFrame (default, good for numeric)
ddf = dd.read_csv('data.csv')
result1 = ddf.mean().compute()  # Uses threads

# Use processes for Python-heavy work
import dask.bag as db
bag = db.read_text('logs/*.txt')
result2 = bag.map(python_function).compute(scheduler='processes')

# Use synchronous for debugging
dask.config.set(scheduler='synchronous')
result3 = problematic_computation.compute()  # Can use pdb

# Use distributed for monitoring and scaling
from dask.distributed import Client
client = Client()
result4 = computation.compute()  # Uses distributed with dashboard
```

**要点**：
- 线程：开销最低（约每任务 10 微秒），最适合数值计算
- 进程：避开 GIL（约每任务 10 毫秒），最适合 Python 代码
- 分布式：带监控仪表盘（约每任务 1 毫秒），可扩展到集群
- 可以按单次计算或全局切换调度器

## 最佳实践

关于全面的性能优化指导、内存管理策略以及需要避免的常见陷阱，请参阅
`references/best-practices.md`。核心原则包括：

### 先从更简单的方案入手
在使用 Dask 之前，先考虑：
- 更好的算法
- 更高效的文件格式（用 Parquet 代替 CSV）
- 编译型代码（Numba、Cython）
- 数据抽样

### 关键性能规则

**1. 不要先在本地加载数据再交给 Dask**
```python
# Wrong: Loads all data in memory first
import pandas as pd
df = pd.read_csv('large.csv')
ddf = dd.from_pandas(df, npartitions=10)

# Correct: Let Dask handle loading
import dask.dataframe as dd
ddf = dd.read_csv('large.csv')
```

**2. 避免反复调用 compute()**
```python
# Wrong: Each compute is separate
for item in items:
    result = dask_computation(item).compute()

# Correct: Single compute for all
computations = [dask_computation(item) for item in items]
results = dask.compute(*computations)
```

**3. 不要构建过大的任务图**
- 如果任务数达到百万级，就增大分块大小
- 使用 `map_partitions`/`map_blocks` 来融合操作
- 检查任务图大小：`len(ddf.__dask_graph__())`

**4. 选择合适的分块大小**
- 目标：每个分块约 100 MB（或每个核心在 worker 内存中对应 10 个分块）
- 太大：内存溢出
- 太小：调度开销过高

**5. 使用仪表盘**
```python
from dask.distributed import Client
client = Client()
print(client.dashboard_link)  # Monitor performance, identify bottlenecks
```

## 常见工作流模式

### ETL 流水线
```python
import dask.dataframe as dd

# Extract: Read data
ddf = dd.read_csv('raw_data/*.csv')

# Transform: Clean and process
ddf = ddf[ddf['status'] == 'valid']
ddf['amount'] = ddf['amount'].astype('float64')
ddf = ddf.dropna(subset=['important_col'])

# Load: Aggregate and save
summary = ddf.groupby('category').agg({'amount': ['sum', 'mean']})
summary.to_parquet('output/summary.parquet')
```

### 从非结构化到结构化的流水线
```python
import dask.bag as db
import json

# Start with Bag for unstructured data
bag = db.read_text('logs/*.json').map(json.loads)
bag = bag.filter(lambda x: x['status'] == 'valid')

# Convert to DataFrame for structured analysis
ddf = bag.to_dataframe()
result = ddf.groupby('category').mean().compute()
```

### 大规模数组计算
```python
import dask.array as da

# Load or create large array
x = da.from_zarr('large_dataset.zarr')

# Process in chunks
normalized = (x - x.mean()) / x.std()

# Save result (use mode= for overwrite; zarr_array_kwargs for compression)
da.to_zarr(normalized, 'normalized.zarr', mode='w')
```

### 自定义并行工作流
```python
from dask.distributed import Client

client = Client()

# Scatter large dataset once
data = client.scatter(large_dataset)

# Process in parallel with dependencies
futures = []
for param in parameters:
    future = client.submit(process, data, param)
    futures.append(future)

# Gather results
results = client.gather(futures)
```

## 选择合适的组件

用下面这份决策指南来选择合适的 Dask 组件：

**数据类型**：
- 表格数据 → **DataFrame**
- 数值数组 → **Array**
- 文本/JSON/日志 → **Bag**（之后转换为 DataFrame）
- 自定义 Python 对象 → **Bag** 或 **Futures**

**操作类型**：
- 标准的 pandas 操作 → **DataFrame**
- 标准的 NumPy 操作 → **Array**
- 自定义并行任务 → **Futures**
- 文本处理/ETL → **Bag**

**控制粒度**：
- 高层、自动化 → **DataFrame/Array**
- 底层、手动控制 → **Futures**

**工作流类型**：
- 静态计算图 → **DataFrame/Array/Bag**
- 动态、不断演变 → **Futures**

## 集成方面的考量

### 文件格式
- **高效**：Parquet、HDF5、Zarr（列式存储、压缩、对并行友好）
- **兼容但较慢**：CSV（仅用于初始数据摄取）
- **用于 Array**：HDF5、Zarr、NetCDF

### 各集合类型之间的转换
```python
# Bag → DataFrame
ddf = bag.to_dataframe()

# DataFrame → Array (for numeric data)
arr = ddf.to_dask_array(lengths=True)

# Array → DataFrame
ddf = dd.from_dask_array(arr, columns=['col1', 'col2'])
```

### 与其他库的集成
- **XArray**：为 Dask 数组附加带标签的维度（地理空间、影像）
- **Dask-ML**：提供与 scikit-learn 兼容 API 的机器学习功能
- **Distributed**：高级的集群管理与监控

## 调试与开发

### 迭代式开发工作流

1. **先用同步调度器在小数据上测试**：
```python
dask.config.set(scheduler='synchronous')
result = computation.compute()  # Can use pdb, easy debugging
```

2. **用线程在样本数据上验证**：
```python
sample = ddf.head(1000)  # Small sample
# Test logic, then scale to full dataset
```

3. **用分布式调度器扩展并进行监控**：
```python
from dask.distributed import Client
client = Client()
print(client.dashboard_link)  # Monitor performance
result = computation.compute()
```

### 常见问题

**内存错误**：
- 减小分块大小
- 有策略地使用 `persist()`，并在用完后删除
- 检查自定义函数中是否存在内存泄漏

**启动缓慢**：
- 任务图过大（增大分块大小）
- 使用 `map_partitions` 或 `map_blocks` 来减少任务数

**并行度不佳**：
- 分块过大（增加分区数量）
- 用线程处理 Python 代码（应改用进程）
- 数据依赖关系阻碍了并行执行

## 参考文件

以下所有参考文档文件都可以按需读取以获取详细信息：

- `references/dataframes.md` —— 完整的 Dask DataFrame 指南
- `references/arrays.md` —— 完整的 Dask Array 指南
- `references/bags.md` —— 完整的 Dask Bag 指南
- `references/futures.md` —— 完整的 Dask Futures 与分布式计算指南
- `references/schedulers.md` —— 完整的调度器选择与配置指南
- `references/best-practices.md` —— 全面的性能优化与故障排查指南

当用户需要了解本文所提供的快速指导之外的、关于特定 Dask 组件、操作或模式的详细信息时，加载这些文件。
