# Polars

## 概述

Polars 是一个基于 Apache Arrow 构建的、面向 Python 和 Rust 的极速 DataFrame 库。使用 Polars 基于表达式(expression-based)的 API、惰性求值(lazy evaluation)框架，以及高性能数据操作能力，来实现高效的数据处理、pandas 迁移，以及数据流水线优化。

## 快速开始

### 安装与基本用法

安装本次更新时验证过的当前稳定版 Polars:
```bash
uv pip install "polars==1.41.2"
```

只在需要时安装可选的集成组件:
```bash
uv pip install "polars[excel,database,fsspec,pandas,numpy]==1.41.2"
```

基础的 DataFrame 创建与操作:
```python
import polars as pl

# Create DataFrame
df = pl.DataFrame({
    "name": ["Alice", "Bob", "Charlie"],
    "age": [25, 30, 35],
    "city": ["NY", "LA", "SF"]
})

# Select columns
df.select("name", "age")

# Filter rows
df.filter(pl.col("age") > 25)

# Add computed columns
df.with_columns(
    age_plus_10=pl.col("age") + 10
)
```

## 核心概念

### 表达式(Expressions)

表达式是 Polars 操作的基础构建单元。它们描述对数据的变换，可以被组合、复用和优化。

**关键原则**:
- 用 `pl.col("column_name")` 来引用列
- 链式调用方法来构建复杂的变换
- 表达式是惰性的，只在特定上下文中(select、with_columns、filter、group_by)才会执行

**示例**:
```python
# Expression-based computation
df.select(
    pl.col("name"),
    (pl.col("age") * 12).alias("age_in_months")
)
```

### 惰性(Lazy)与即时(Eager)求值

**即时求值(DataFrame)**: 操作会立即执行
```python
df = pl.read_csv("file.csv")  # Reads immediately
result = df.filter(pl.col("age") > 25)  # Executes immediately
```

**惰性求值(LazyFrame)**: 操作先构建一个查询计划，在执行前进行优化
```python
lf = pl.scan_csv("file.csv")  # Doesn't read yet
result = lf.filter(pl.col("age") > 25).select("name", "age")
df = result.collect()  # Now executes optimized query
```

**何时使用惰性求值**:
- 处理大型数据集时
- 复杂的查询流水线
- 只需要部分列/行时
- 性能至关重要时

**惰性求值的好处**:
- 自动查询优化
- 谓词下推(Predicate pushdown)
- 投影下推(Projection pushdown)
- 并行执行

关于详细概念，加载 `references/core_concepts.md`。

## 常见操作

### Select
选择并操作列:
```python
# Select specific columns
df.select("name", "age")

# Select with expressions
df.select(
    pl.col("name"),
    (pl.col("age") * 2).alias("double_age")
)

# Select all columns matching a pattern
df.select(pl.col("^.*_id$"))
```

### Filter
按条件过滤行:
```python
# Single condition
df.filter(pl.col("age") > 25)

# Multiple conditions (cleaner than using &)
df.filter(
    pl.col("age") > 25,
    pl.col("city") == "NY"
)

# Complex conditions
df.filter(
    (pl.col("age") > 25) | (pl.col("city") == "LA")
)
```

### With Columns
在保留已有列的同时添加或修改列:
```python
# Add new columns
df.with_columns(
    age_plus_10=pl.col("age") + 10,
    name_upper=pl.col("name").str.to_uppercase()
)

# Parallel computation (all columns computed in parallel)
df.with_columns(
    pl.col("value") * 10,
    pl.col("value") * 100,
)
```

### Group By 与聚合
对数据分组并计算聚合结果:
```python
# Basic grouping
df.group_by("city").agg(
    pl.col("age").mean().alias("avg_age"),
    pl.len().alias("count")
)

# Multiple group keys
df.group_by("city", "department").agg(
    pl.col("salary").sum()
)

# Conditional aggregations
df.group_by("city").agg(
    (pl.col("age") > 30).sum().alias("over_30")
)
```

关于详细的操作模式，加载 `references/operations.md`。

## 聚合与窗口函数

### 聚合函数
`group_by` 上下文中常见的聚合方式:
- `pl.len()` - 统计行数
- `pl.col("x").sum()` - 求和
- `pl.col("x").mean()` - 求平均值
- `pl.col("x").min()` / `pl.col("x").max()` - 极值
- `pl.first()` / `pl.last()` - 首个/末个值

### 用 `over()` 实现窗口函数
在保留行数的同时应用聚合:
```python
# Add group statistics to each row
df.with_columns(
    avg_age_by_city=pl.col("age").mean().over("city"),
    rank_in_city=pl.col("salary").rank().over("city")
)

# Multiple grouping columns
df.with_columns(
    group_avg=pl.col("value").mean().over("category", "region")
)
```

**映射策略**:
- `group_to_rows`(默认):保留原始行顺序
- `explode`:更快，但会把行归并到一起
- `join`:创建 list 类型的列

## 数据 I/O

### 支持的格式
Polars 支持读写:
- CSV、Parquet、JSON、Excel
- 数据库(通过连接器)
- 云存储(S3、Azure、GCS)
- Google BigQuery
- 多文件/分区文件

### 常见 I/O 操作

**CSV**:
```python
# Eager
df = pl.read_csv("file.csv")
df.write_csv("output.csv")

# Lazy (preferred for large files)
lf = pl.scan_csv("file.csv")
result = lf.filter(...).select(...).collect()
```

**Parquet(推荐用于提升性能)**:
```python
df = pl.read_parquet("file.parquet")
df.write_parquet("output.parquet")
```

**JSON**:
```python
df = pl.read_json("file.json")
df.write_json("output.json")
```

关于全面的 I/O 文档，加载 `references/io_guide.md`。

## 变换

### Joins(连接)
合并 DataFrame:
```python
# Inner join
df1.join(df2, on="id", how="inner")

# Left join
df1.join(df2, on="id", how="left")

# Join on different column names
df1.join(df2, left_on="user_id", right_on="id")
```

### 拼接(Concatenation)
堆叠 DataFrame:
```python
# Vertical (stack rows)
pl.concat([df1, df2], how="vertical")

# Horizontal (add columns)
pl.concat([df1, df2], how="horizontal")

# Diagonal (union with different schemas)
pl.concat([df1, df2], how="diagonal")
```

### Pivot 与 Unpivot
重塑数据形状:
```python
# Pivot (wide format)
df.pivot(on="product", values="sales", index="date")

# Unpivot (long format)
df.unpivot(index="id", on=["col1", "col2"])
```

关于详细的变换示例，加载 `references/transformations.md`。

## 从 Pandas 迁移

相较于 pandas,Polars 提供了显著的性能提升，以及更简洁的 API。关键差异如下:

### 概念上的差异
- **没有索引(index)**:Polars 只使用整数位置
- **严格的类型系统**:不存在静默的类型转换
- **惰性求值**:通过 LazyFrame 提供
- **默认并行**:操作会自动并行化

### 常见操作对照表

| 操作 | Pandas | Polars |
|-----------|--------|--------|
| 选择列 | `df["col"]` | `df.select("col")` |
| 过滤 | `df[df["col"] > 10]` | `df.filter(pl.col("col") > 10)` |
| 添加列 | `df.assign(x=...)` | `df.with_columns(x=...)` |
| 分组 | `df.groupby("col").agg(...)` | `df.group_by("col").agg(...)` |
| 窗口 | `df.groupby("col").transform(...)` | `df.with_columns(...).over("col")` |

### 关键语法模式

**Pandas 顺序执行(较慢)**:
```python
df.assign(
    col_a=lambda df_: df_.value * 10,
    col_b=lambda df_: df_.value * 100
)
```

**Polars 并行执行(较快)**:
```python
df.with_columns(
    col_a=pl.col("value") * 10,
    col_b=pl.col("value") * 100,
)
```

关于全面的迁移指南，加载 `references/pandas_migration.md`。

## 最佳实践

### 性能优化

1. **对大型数据集使用惰性求值**:
   ```python
   lf = pl.scan_csv("large.csv")  # Don't use read_csv
   result = lf.filter(...).select(...).collect()
   ```

2. **避免在热路径中使用 Python 函数**:
   - 保持在表达式 API 之内以获得并行化
   - 只在必要时使用 `.map_elements()`
   - 优先使用 Polars 原生操作

3. **对非常大的数据使用流式处理**:
   ```python
   lf.collect(engine="streaming")
   ```

4. **尽早只选取所需的列**:
   ```python
   # Good: Select columns early
   lf.select("col1", "col2").filter(...)

   # Bad: Filter on all columns first
   lf.filter(...).select("col1", "col2")
   ```

5. **使用恰当的数据类型**:
   - 对低基数(low-cardinality)字符串使用 Categorical 类型
   - 使用合适的整数位宽(i32 与 i64)
   - 对时间数据使用 Date 类型

### 表达式模式

**条件操作**:
```python
pl.when(condition).then(value).otherwise(other_value)
```

**跨多列的列操作**:
```python
df.select(pl.col("^.*_value$") * 2)  # Regex pattern
```

**空值处理**:
```python
pl.col("x").fill_null(0)
pl.col("x").is_null()
pl.col("x").drop_nulls()
```

关于更多最佳实践和使用模式，加载 `references/best_practices.md`。

## 资源

本 skill 包含全面的参考文档:

### references/
- `core_concepts.md` - 关于表达式、惰性求值和类型系统的详细说明
- `operations.md` - 涵盖所有常见操作及示例的完整指南
- `pandas_migration.md` - 从 pandas 迁移到 Polars 的完整指南
- `io_guide.md` - 所有支持格式的数据 I/O 操作
- `transformations.md` - 连接(join)、拼接、透视表(pivot)以及重塑操作
- `best_practices.md` - 性能优化建议和常见模式

在用户需要了解特定主题的详细信息时，按需加载这些参考文档。
