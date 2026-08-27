# Vaex

## 概述

Vaex 是一个高性能的 Python 库，专为惰性（lazy）、核外（out-of-core）DataFrame 而设计，用于处理和可视化那些大到无法装入内存的表格数据集。Vaex 每秒可处理超过十亿行数据，能够对拥有数十亿行的数据集进行交互式数据探索与分析。

## 安装

安装完整的元包（推荐做法）：

```bash
uv pip install vaex
```

最小化安装（只选择你所需要的部分）：

```bash
uv pip install vaex-core vaex-viz vaex-hdf5 vaex-ml
```

`vaex` 软件包是一个元包（meta-package），它会引入 `vaex-core`、`vaex-viz`、`vaex-hdf5`、`vaex-ml` 以及其他子包。Arrow 支持已内置于 `vaex-core` 中（独立的 `vaex-arrow` 包已被弃用）。`vaex-distributed` 已被弃用，取而代之的是 vaex-enterprise。

**版本说明（vaex 4.19.0+）**： Python 3.12 及 NumPy v2 要求 vaex 版本 >= 4.19.0。在 Windows 上，你可能需要 Python 开发头文件（dev headers）才能构建 `annoy` 依赖项。

## 何时使用本技能

在以下情形使用 Vaex：
- 处理超出可用内存大小的表格数据集（从数 GB 到数 TB）
- 对海量数据集执行快速的统计聚合
- 为大型数据集创建可视化图形及热力图
- 在大数据上构建机器学习流水线
- 在不同数据格式之间进行转换（CSV、HDF5、Arrow、Parquet）
- 需要惰性求值及虚拟列（virtual column）以避免内存开销
- 处理天文数据、金融时间序列，或其他大规模科学数据集

**Vaex 与其他方案的对比**： 当数据能够装入内存、且你需要最高的内存内运算速度时，使用 **polars**。当你需要在集群上分布式运行 pandas/NumPy 时，使用 **dask**。当你需要在单机上、通过内存映射的 HDF5/Arrow 文件对超出内存的表格数据进行核外分析时，使用 **vaex**。

## 核心能力

Vaex 提供六个主要能力领域，每个都在 references 目录下有详细文档：

### 1. DataFrame 与数据加载

从多种来源加载和创建 Vaex DataFrame，包括文件（HDF5、CSV、Arrow、Parquet）、pandas DataFrame、NumPy 数组以及字典。参阅 `references/core_dataframes.md`，了解：
- 高效地打开大型文件
- 从 pandas/NumPy/Arrow 转换
- 使用示例数据集
- 理解 DataFrame 的结构

### 2. 数据处理与操作

在不将全部数据加载进内存的情况下执行过滤、创建虚拟列、使用表达式，以及聚合数据。参阅 `references/data_processing.md`，了解：
- 过滤与选择
- 虚拟列与表达式
- Groupby 操作与聚合
- 字符串操作与日期时间处理
- 处理缺失数据

### 3. 性能与优化

利用 Vaex 的惰性求值、缓存策略以及内存高效的操作。参阅 `references/performance.md`，了解：
- 理解惰性求值
- 在执行多个操作时使用 `delay=True` 进行批处理
- 在需要时将列实体化（materialize）
- 缓存策略
- 异步操作

### 4. 数据可视化

为大型数据集创建交互式可视化，包括热力图、直方图及散点图。参阅 `references/visualization.md`，了解：
- 创建一维及二维图形
- 热力图可视化
- 使用选择（selection）
- 自定义图形及子图

### 5. 机器学习集成

使用转换器（transformer）、编码器（encoder）构建机器学习流水线，并与 scikit-learn、XGBoost 及其他框架集成。参阅 `references/machine_learning.md`，了解：
- 特征缩放与编码
- PCA 及降维
- K-means 聚类
- 与 scikit-learn/XGBoost/CatBoost 的集成
- 模型序列化与部署

### 6. I/O 操作

以最优性能读写多种格式的数据。参阅 `references/io_operations.md`，了解：
- 文件格式选择建议
- 导出策略
- 使用 Apache Arrow
- 大文件的 CSV 处理
- 服务器及远程数据访问

## 快速入门模式

对于大多数 Vaex 任务，遵循以下模式：

```python
import vaex

# 1. Open or create DataFrame
df = vaex.open('large_file.hdf5')  # or .csv, .arrow, .parquet
# OR
df = vaex.from_pandas(pandas_df)

# 2. Explore the data
print(df)  # Shows first/last rows and column info
df.describe()  # Statistical summary

# 3. Create virtual columns (no memory overhead)
df['new_column'] = df.x ** 2 + df.y

# 4. Filter with selections
df_filtered = df[df.age > 25]

# 5. Compute statistics (fast, lazy evaluation)
mean_val = df.x.mean()
stats = df.groupby('category').agg({'value': 'sum'})

# 6. Visualize (df.viz is the recommended accessor since vaex 4.0)
df.viz.heatmap(df.x, df.y, limits='99.7%', show=True)
# Legacy: df.plot1d() and df.plot() still work on the DataFrame

# 7. Export if needed
df.export_hdf5('output.hdf5')
```

## 参考文件的使用方式

参考文件包含每个能力领域的详细信息。根据具体任务将相应的参考文件加载进上下文：

- **基本操作**：从 `references/core_dataframes.md` 和 `references/data_processing.md` 开始
- **性能问题**：查看 `references/performance.md`
- **可视化任务**：使用 `references/visualization.md`
- **机器学习流水线**：参阅 `references/machine_learning.md`
- **文件 I/O**：查阅 `references/io_operations.md`

## 最佳实践

1. **使用 HDF5 或 Apache Arrow 格式**，以在大型数据集上获得最佳性能
2. **善用虚拟列**，而不是将数据实体化，以节省内存
3. 在执行多项计算时，**使用 `delay=True` 批量执行操作**
4. **导出为高效格式**，而不是一直将数据保存为 CSV
5. **使用表达式**进行复杂计算，避免中间存储
6. **使用 `df.describe()` 和 `df.nbytes` 进行性能分析**，以了解数据形状及内存占用情况

## 常见模式

### 模式：将大型 CSV 转换为 HDF5
```python
import vaex

# Open large CSV lazily (vaex 4.14+), or use from_csv to convert to HDF5
df = vaex.open('large_file.csv')
# df = vaex.from_csv('large_file.csv', convert='large_file.hdf5')

# Export to HDF5 for faster future access
df.export_hdf5('large_file.hdf5')

# Future loads are instant
df = vaex.open('large_file.hdf5')
```

### 模式：高效的聚合运算
```python
# Use delay=True to batch multiple operations
mean_x = df.x.mean(delay=True)
std_y = df.y.std(delay=True)
sum_z = df.z.sum(delay=True)

# Execute all at once
results = vaex.execute([mean_x, std_y, sum_z])
```

### 模式：用于特征工程的虚拟列
```python
# No memory overhead - computed on the fly
df['age_squared'] = df.age ** 2
df['full_name'] = df.first_name + ' ' + df.last_name
df['is_adult'] = df.age >= 18
```

## 资源

本技能在 `references/` 目录下包含以下参考文档：

- `core_dataframes.md` —— DataFrame 的创建、加载及基本结构
- `data_processing.md` —— 过滤、表达式、聚合及转换
- `performance.md` —— 优化策略及惰性求值
- `visualization.md` —— 绘图及交互式可视化
- `machine_learning.md` —— 机器学习流水线及模型集成
- `io_operations.md` —— 文件格式及数据导入/导出
