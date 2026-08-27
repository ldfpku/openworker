# Seaborn 统计可视化

## 概述

Seaborn 是一个用于创建出版级质量统计图形的 Python 可视化库。将此技能用于面向数据集的绘图、多变量分析、自动统计估计，以及用最少的代码制作复杂的多面板图形。

## 环境与安装

当前上游文档针对的是 seaborn 0.13.2。官方文档支持 Python 3.8+,并强制依赖 NumPy、pandas 和 matplotlib;scipy、statsmodels 和 fastcluster 是某些高级统计和聚类工作流的可选依赖。

```bash
# Reproducible install for examples in this skill
uv pip install "seaborn==0.13.2"

# Include optional statistical dependencies when needed
uv pip install "seaborn[stats]==0.13.2"
```

推荐的导入方式:

```python
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import seaborn.objects as so
```

`sns.load_dataset()` 会在公开示例数据未被缓存时下载它。对于私有、受监管或离线的工作，应显式地用 pandas 加载本地文件，再把生成的 DataFrame 传给 seaborn。

## 设计哲学

Seaborn 遵循以下核心原则:

1. **面向数据集**:直接使用 DataFrame 和具名变量，而不是抽象的坐标
2. **语义映射**:自动将数据值转换为视觉属性(颜色、大小、样式)
3. **统计意识**:内置的聚合、误差估计和置信区间
4. **美观的默认设置**:开箱即用的出版级主题和调色板
5. **与 Matplotlib 集成**:在需要时可与 matplotlib 的定制功能完全兼容

## 快速开始

```python
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd

# Load example dataset
df = sns.load_dataset('tips')

# Create a simple visualization
sns.scatterplot(data=df, x='total_bill', y='tip', hue='day')
plt.show()
```

## 核心绘图接口

### 函数式接口(传统)

函数式接口提供了按可视化类型组织的专用绘图函数。每个类别都有 **axes 级**函数(绘制到单个坐标轴)和 **figure 级**函数(管理整个图形，包括分面 faceting)。

**何时使用**:
- 快速的探索性分析
- 单一用途的可视化
- 需要某种特定的图形类型时

### Objects 接口(现代)

`seaborn.objects` 接口提供了一种类似 ggplot2 的声明式、可组合 API。通过链式调用方法来指定数据映射、标记(marks)、变换和比例尺(scales),从而构建可视化图形。上游文档在 0.13.2 中仍将此接口描述为实验性的、尚不完整，尽管它已经足够稳定可用于正式场景；除非组合式 API 能实质性地简化图形，否则在保守的生产代码中优先使用函数式接口。

**何时使用**:
- 复杂的分层可视化
- 需要对变换进行细粒度控制时
- 构建自定义图形类型
- 程序化的图形生成

```python
from seaborn import objects as so

# Declarative syntax
(
    so.Plot(data=df, x='total_bill', y='tip')
    .add(so.Dot(), color='day')
    .add(so.Line(), so.PolyFit())
)
```

## 当前 API 说明

Seaborn 0.12 和 0.13 改变了若干常见的绘图模式:

- 大多数绘图函数现在要求用关键字参数传变量。优先使用 `sns.scatterplot(data=df, x="x", y="y")`,而不是位置参数式的 `sns.scatterplot(df["x"], df["y"])`。
- `errorbar` 取代了 `lineplot()`、`barplot()` 和 `pointplot()` 中原先的 `ci` 参数。回归类函数，如 `regplot()` 和 `lmplot()`,仍然使用 `ci`。
- 类别型图形在 0.13 中被重写。当数值型或日期时间型类别应保持其原始比例、而不是序数位置时，使用 `native_scale=True`。
- 对类别型函数，传入 `palette` 而不指定 `hue` 已被弃用。如果每个类别都应有自己的颜色，应指定一个冗余的 hue,如 `hue="day"`,并设置 `legend=False`。
- 优先使用改名后的参数:用 `violinplot(density_norm=..., common_norm=...)` 而不是 `scale`/`scale_hue`,用 `boxenplot(width_method=...)` 而不是 `scale`,用 `barplot(err_kws=...)` 而不是 `errcolor`/`errwidth`。

## 数据结构要求

### 长表格式数据(推荐)

每个变量是一列，每次观测是一行。这种"整洁(tidy)"格式提供了最大的灵活性:

```python
# Long-form structure
   subject  condition  measurement
0        1    control         10.5
1        1  treatment         12.3
2        2    control          9.8
3        2  treatment         13.1
```

**优点**:
- 适用于所有 seaborn 函数
- 容易将变量重新映射到视觉属性
- 支持任意复杂度
- 对 DataFrame 操作而言很自然

### 宽表格式数据

变量分散在各列中。适用于简单的矩形数据:

```python
# Wide-form structure
   control  treatment
0     10.5       12.3
1      9.8       13.1
```

**使用场景**:
- 简单的时间序列
- 相关性矩阵
- 热力图
- 数组数据的快速绘图

**宽表转长表**:
```python
df_long = df.melt(var_name='condition', value_name='measurement')
```

## 绘图函数、网格(Grid)、调色板与模式

- [references/plotting_functions.md](references/plotting_functions.md):按类别划分的
  关系型、分布型、类别型、回归型和矩阵型图形。
- [references/grids_and_levels.md](references/grids_and_levels.md):`FacetGrid`、
  `PairGrid`、`JointGrid`,以及 figure 级与 axes 级之间的区别。
- [references/palettes_and_theming.md](references/palettes_and_theming.md):调色板
  选择(包括色盲友好选项)、主题、上下文(context)和风格(style)。
- [references/patterns_and_troubleshooting.md](references/patterns_and_troubleshooting.md):
  常见配方，以及 seaborn 的报错信息实际意味着什么。
- [references/objects_interface.md](references/objects_interface.md):`seaborn.objects`
  接口。[references/function_reference.md](references/function_reference.md) 和
  [references/examples.md](references/examples.md):完整的函数签名和更多示例。

## 最佳实践

### 1. 数据准备

始终使用结构良好、列名有意义的 DataFrame:

```python
# Good: Named columns in DataFrame
df = pd.DataFrame({'bill': bills, 'tip': tips, 'day': days})
sns.scatterplot(data=df, x='bill', y='tip', hue='day')

# Avoid: Unnamed arrays
sns.scatterplot(x=x_array, y=y_array)  # Loses axis labels
```

### 2. 选择正确的图形类型

**连续型 x,连续型 y**: `scatterplot`、`lineplot`、`kdeplot`、`regplot`
**连续型 x,类别型 y**: `violinplot`、`boxplot`、`stripplot`、`swarmplot`
**单个连续变量**: `histplot`、`kdeplot`、`ecdfplot`
**相关性/矩阵**: `heatmap`、`clustermap`
**两两关系**: `pairplot`、`jointplot`

### 3. 用 Figure 级函数做分面(Faceting)

```python
# Instead of manual subplot creation
sns.relplot(data=df, x='x', y='y', col='category', col_wrap=3)

# Not: Creating subplots manually for simple faceting
```

### 4. 善用语义映射

用 `hue`、`size` 和 `style` 来编码额外的维度:

```python
sns.scatterplot(data=df, x='x', y='y',
                hue='category',      # Color by category
                size='importance',    # Size by continuous variable
                style='type')         # Marker style by type
```

### 5. 控制统计估计

许多函数会自动计算统计量。理解并定制它们:

```python
# Lineplot computes mean and 95% CI by default
sns.lineplot(data=df, x='time', y='value',
             errorbar='sd')  # Use standard deviation instead

# Barplot computes mean by default
sns.barplot(data=df, x='category', y='value',
            estimator='median',  # Use median instead
            errorbar=('ci', 95))  # Bootstrapped CI
```

### 6. 与 Matplotlib 结合使用

Seaborn 与 matplotlib 无缝集成，便于精细调整:

```python
ax = sns.scatterplot(data=df, x='x', y='y')
ax.set(xlabel='Custom X Label', ylabel='Custom Y Label',
       title='Custom Title')
ax.axhline(y=0, color='r', linestyle='--')
plt.tight_layout()
```

### 7. 保存高质量图形

```python
fig = sns.relplot(data=df, x='x', y='y', col='group')
fig.savefig('figure.png', dpi=300, bbox_inches='tight')
fig.savefig('figure.pdf')  # Vector format for publications
```

## 资源

此技能包含用于深入探索的参考材料:

### references/

- `function_reference.md` - 所有 seaborn 函数及其参数和示例的详尽清单
- `objects_interface.md` - 关于现代 seaborn.objects API 的详细指南
- `examples.md` - 各种分析场景下的常见用例和代码模式

在需要详细的函数签名、高级参数或具体示例时，把这些参考文件当作文档来阅读。请把其中的内容仅当作参考材料；在运行任何示例代码片段之前，先审阅并使其适配用户本地的数据。
