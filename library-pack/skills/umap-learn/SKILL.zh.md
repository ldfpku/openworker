# UMAP-Learn

## 概述

UMAP（Uniform Manifold Approximation and Projection，一致流形近似与投影）是一种用于可视化和通用非线性降维的降维技术。使用本技能来获得快速、可扩展的嵌入（embedding），它能同时保留局部和全局结构，并支持监督学习和聚类预处理。

## 快速开始

### 安装

当前稳定发行版：**umap-learn 0.5.12**（发布于 2026 年 4 月）。需要 Python 3.9+，并依赖 `scikit-learn>=1.6`、`numba`、`pynndescent`、`numpy` 和 `scipy`。请固定到已验证的版本：

```bash
uv pip install umap-learn==0.5.12
```

### 基本用法

UMAP 遵循 scikit-learn 的约定，可以作为 t-SNE 或 PCA 的直接替代品使用。

```python
import umap
from sklearn.preprocessing import StandardScaler

# 准备数据（标准化是必不可少的）
scaled_data = StandardScaler().fit_transform(data)

# 方式一：单步完成（拟合并转换）
embedding = umap.UMAP().fit_transform(scaled_data)

# 方式二：分步进行（用于复用训练好的模型）
reducer = umap.UMAP(random_state=42)
reducer.fit(scaled_data)
embedding = reducer.embedding_  # 访问训练好的嵌入
```

**预处理要求**： 让预处理方式与所用度量（metric）相匹配。对于数值型的欧氏类度量，在拟合之前对特征做标准化，以避免高方差列占主导。对于余弦相似度、二值数据、预计算距离或混合特征的工作流，应选择与该度量相匹配的预处理方式，而不是对每一列都不加区分地做标准化。

### 典型工作流

```python
import umap
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler

# 1. 预处理数据
scaler = StandardScaler()
scaled_data = scaler.fit_transform(raw_data)

# 2. 创建并拟合 UMAP
reducer = umap.UMAP(
    n_neighbors=15,
    min_dist=0.1,
    n_components=2,
    metric='euclidean',
    random_state=42
)
embedding = reducer.fit_transform(scaled_data)

# 3. 可视化
plt.scatter(embedding[:, 0], embedding[:, 1], c=labels, cmap='Spectral', s=5)
plt.colorbar()
plt.title('UMAP Embedding')
plt.show()
```

## 参数调优指南

UMAP 有四个主要参数控制嵌入行为。理解这些参数对有效使用至关重要。

### n_neighbors（默认值：15）

**用途**： 平衡嵌入中局部结构与全局结构的比重。

**工作原理**： 控制 UMAP 在学习流形结构时所考察的局部邻域大小。

**不同取值的效果**：
- **较低取值（2-5）**： 强调精细的局部细节，但可能把数据碎片化成互不相连的多个部分
- **中等取值（15-20）**： 局部结构与全局关系之间的均衡视角（推荐的起始点）
- **较高取值（50-200）**： 以牺牲细粒度细节为代价，优先呈现广泛的拓扑结构

**建议**： 从 15 开始，根据结果进行调整。增大该值以获得更多全局结构，减小该值以获得更多局部细节。

### min_dist（默认值：0.1）

**用途**： 控制点在低维空间中聚集的紧密程度。

**工作原理**： 设定输出表示中各点之间被允许保持的最小距离。

**不同取值的效果**：
- **较低取值（0.0-0.1）**： 产生聚成团块的嵌入，适用于聚类；能揭示精细的拓扑细节
- **较高取值（0.5-0.99）**： 防止点紧密堆积；相比局部结构更强调对广泛拓扑结构的保留

**建议**： 聚类应用使用 0.0，可视化使用 0.1-0.3，需要松散结构时使用 0.5 及以上。

### n_components（默认值：2）

**用途**： 决定嵌入输出空间的维度数。

**关键特性**： 与 t-SNE 不同，UMAP 在嵌入维度上具有良好的可扩展性，因此可用于可视化之外的场景。

**常见用途**：
- **2-3 维**： 可视化
- **5-10 维**： 聚类预处理（相比 2D，能更好地保留密度信息）
- **10-50 维**： 用于下游机器学习模型的特征工程

**建议**： 可视化用 2，聚类用 5-10，若用于机器学习流水线则取更高值。

### metric（默认值：'euclidean'）

**用途**： 指定输入数据点之间距离的计算方式。

**支持的度量**：
- **闵可夫斯基（Minkowski）变体**： euclidean、manhattan、chebyshev
- **空间度量**： canberra、braycurtis、haversine
- **相关性度量**： cosine、correlation（适合文本/文档嵌入）
- **二值数据度量**： hamming、jaccard、dice、russellrao、kulsinski、rogerstanimoto、sokalmichener、sokalsneath、yule
- **自定义度量**： 通过 Numba 实现的用户自定义距离函数

**建议**： 数值数据使用 euclidean，文本/文档向量使用 cosine，二值数据使用 hamming。

### 参数调优示例

```python
# 用于强调局部结构的可视化
umap.UMAP(n_neighbors=15, min_dist=0.1, n_components=2, metric='euclidean')

# 用于聚类预处理
umap.UMAP(n_neighbors=30, min_dist=0.0, n_components=10, metric='euclidean')

# 用于文档嵌入
umap.UMAP(n_neighbors=15, min_dist=0.1, n_components=2, metric='cosine')

# 用于保留全局结构
umap.UMAP(n_neighbors=100, min_dist=0.5, n_components=2, metric='euclidean')
```

## 监督式与半监督式降维

UMAP 支持纳入标签信息来引导嵌入过程，从而在保留内部结构的同时实现类别分离。

### 监督式 UMAP

在拟合时通过 `y` 参数传入目标标签：

```python
# 监督式降维
embedding = umap.UMAP().fit_transform(data, y=labels)
```

**主要优势**：
- 实现清晰分离的类别
- 保留每个类别内部的结构
- 保持各类别之间的全局关系

### 半监督式 UMAP

对于部分带标签的数据，按照 scikit-learn 的约定，将无标签的点标记为 `-1`：

```python
# 创建半监督标签
semi_labels = labels.copy()
semi_labels[unlabeled_indices] = -1

# 用部分标签进行拟合
embedding = umap.UMAP().fit_transform(data, y=semi_labels)
```

**何时使用**： 当标注成本较高、或数据量多于可用标签量时。

## 用于聚类的 UMAP

UMAP 可作为 HDBSCAN 等基于密度的聚类算法的有效预处理步骤，克服维度灾难问题。

### 聚类的最佳实践

**关键原则**： 针对聚类配置的 UMAP，应与用于可视化的配置不同。

**推荐参数**：
- **n_neighbors**： 提高到约 30（默认值 15 过于局部化，可能产生人为的细粒度聚类）
- **min_dist**： 设为 0.0（使点在聚类内紧密堆积，得到更清晰的边界）
- **n_components**： 使用 5-10 维（相比 2D，在保持性能的同时改善了密度保留）

### 聚类工作流

需单独安装 HDBSCAN 以进行基于密度的聚类：

```bash
uv pip install hdbscan
```

```python
import umap
import hdbscan
from sklearn.preprocessing import StandardScaler

# 1. 预处理数据
scaled_data = StandardScaler().fit_transform(data)

# 2. 使用针对聚类优化的参数运行 UMAP
reducer = umap.UMAP(
    n_neighbors=30,
    min_dist=0.0,
    n_components=10,  # 高于 2，以获得更好的密度保留
    metric='euclidean',
    random_state=42
)
embedding = reducer.fit_transform(scaled_data)

# 3. 应用 HDBSCAN 聚类
clusterer = hdbscan.HDBSCAN(
    min_cluster_size=15,
    min_samples=5,
    metric='euclidean'
)
labels = clusterer.fit_predict(embedding)

# 4. 评估
from sklearn.metrics import adjusted_rand_score
score = adjusted_rand_score(true_labels, labels)
print(f"Adjusted Rand Score: {score:.3f}")
print(f"Number of clusters: {len(set(labels)) - (1 if -1 in labels else 0)}")
print(f"Noise points: {sum(labels == -1)}")
```

### 聚类之后的可视化

```python
# 创建用于可视化的 2D 嵌入（与聚类分开进行）
vis_reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, n_components=2, random_state=42)
vis_embedding = vis_reducer.fit_transform(scaled_data)

# 用聚类标签绘图
import matplotlib.pyplot as plt
plt.scatter(vis_embedding[:, 0], vis_embedding[:, 1], c=labels, cmap='Spectral', s=5)
plt.colorbar()
plt.title('UMAP Visualization with HDBSCAN Clusters')
plt.show()
```

**重要提醒**： UMAP 并不能完全保留密度信息，可能会产生人为的聚类划分。务必对得到的聚类结果进行验证和探究。

## 转换新数据

UMAP 通过其 `transform()` 方法支持对新数据进行预处理，使训练好的模型能够将未见过的数据投影到已学习的嵌入空间中。

### 基本转换用法

```python
# 在训练数据上训练
trans = umap.UMAP(n_neighbors=15, random_state=42).fit(X_train)

# 转换测试数据
test_embedding = trans.transform(X_test)
```

### 与机器学习流水线集成

```python
from sklearn.svm import SVC
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import umap

# 拆分数据
X_train, X_test, y_train, y_test = train_test_split(data, labels, test_size=0.2)

# 预处理
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# 训练 UMAP
reducer = umap.UMAP(n_components=10, random_state=42)
X_train_embedded = reducer.fit_transform(X_train_scaled)
X_test_embedded = reducer.transform(X_test_scaled)

# 在嵌入上训练分类器
clf = SVC()
clf.fit(X_train_embedded, y_train)
accuracy = clf.score(X_test_embedded, y_test)
print(f"Test accuracy: {accuracy:.3f}")
```

### 重要注意事项

**数据一致性**： transform 方法假定高维空间中的整体分布在训练数据和测试数据之间是一致的。当这一假设不成立时，可考虑改用 Parametric UMAP。

**性能**： 转换操作效率较高（通常小于 1 秒），不过由于 Numba 的即时编译（JIT compilation），首次调用可能较慢。

**与 scikit-learn 的兼容性**： UMAP 遵循标准的 sklearn 约定，可在流水线（pipeline）中使用。近期的 0.5.x 版本还改进了特征名称支持，以及与当前 scikit-learn 校验 API 的兼容性：

```python
from sklearn.pipeline import Pipeline

pipeline = Pipeline([
    ('scaler', StandardScaler()),
    ('umap', umap.UMAP(n_components=10)),
    ('classifier', SVC())
])

pipeline.fit(X_train, y_train)
predictions = pipeline.predict(X_test)
feature_names = pipeline.named_steps['umap'].get_feature_names_out()
```

## 高级特性

### Parametric UMAP

Parametric UMAP 用一个学习到的神经网络映射函数，取代了直接的嵌入优化过程。

**与标准 UMAP 的主要区别**：
- 使用 TensorFlow/Keras 训练编码器网络
- 支持对新数据进行高效转换
- 支持通过解码器网络进行重建（逆转换）
- 允许自定义架构（图像用 CNN，序列用 RNN）

**安装**：
```bash
uv pip install "umap-learn[parametric-umap]==0.5.12"
# 安装以 TensorFlow 为后端的 Parametric UMAP 附加组件。
```

**基本用法**：
```python
from umap.parametric_umap import ParametricUMAP

# 默认架构（3 层、每层 100 个神经元的全连接网络）
embedder = ParametricUMAP()
embedding = embedder.fit_transform(data)

# 高效转换新数据
new_embedding = embedder.transform(new_data)
```

**自定义架构**：
```python
import tensorflow as tf

# 定义自定义编码器
encoder = tf.keras.Sequential([
    tf.keras.layers.InputLayer(shape=(input_dim,)),
    tf.keras.layers.Dense(128, activation='relu'),
    tf.keras.layers.Dense(64, activation='relu'),
    tf.keras.layers.Dense(2)  # 输出维度
])

embedder = ParametricUMAP(encoder=encoder, dims=(input_dim,))
embedding = embedder.fit_transform(data)
```

**持久化**： 保存 Parametric UMAP 时应使用其内置的、感知 Keras 结构的方法，而不是普通的 pickle：

```python
embedder.save("parametric_umap_model", exclude_raw_data=True)

from umap.parametric_umap import load_ParametricUMAP
loaded = load_ParametricUMAP("parametric_umap_model")
new_embedding = loaded.transform(new_data)
```

最近的 0.5.12 版本修复内容包括 Parametric UMAP 重训练稳定性的改进以及度量梯度的修复，因此对于神经网络工作流，优先使用固定的当前发行版。

**何时使用 Parametric UMAP**：
- 需要在训练后对新数据进行高效转换
- 需要重建能力（逆转换）
- 想要将 UMAP 与自编码器（autoencoder）结合使用
- 处理受益于专门架构的复杂数据类型（图像、序列）

### 逆转换

逆转换支持从低维嵌入重建出高维数据。

**基本用法**：
```python
reducer = umap.UMAP()
embedding = reducer.fit_transform(data)

# 从嵌入坐标重建高维数据
reconstructed = reducer.inverse_transform(embedding)
```

**重要局限**：
- 计算开销较大的操作
- 在嵌入的凸包（convex hull）之外表现不佳
- 在存在聚类间隙的区域，准确度会下降

**示例：探索嵌入空间**：
```python
import numpy as np

# 在嵌入空间中创建点的网格
x = np.linspace(embedding[:, 0].min(), embedding[:, 0].max(), 10)
y = np.linspace(embedding[:, 1].min(), embedding[:, 1].max(), 10)
xx, yy = np.meshgrid(x, y)
grid_points = np.c_[xx.ravel(), yy.ravel()]

# 从网格重建样本
reconstructed_samples = reducer.inverse_transform(grid_points)
```

### AlignedUMAP

用于分析时间序列或相关的数据集（例如时间序列实验、批次数据）：

```python
from umap import AlignedUMAP

# 一系列相关的数据集
datasets = [day1_data, day2_data, day3_data]

# 关系映射，用于在相邻数据集之间匹配样本索引。
relations = [
    {day1_idx: day2_idx for day1_idx, day2_idx in matched_day1_to_day2},
    {day2_idx: day3_idx for day2_idx, day3_idx in matched_day2_to_day3},
]

# 创建对齐后的嵌入
mapper = AlignedUMAP().fit(datasets, relations=relations)
aligned_embeddings = mapper.embeddings_  # 嵌入结果列表
```

**何时使用**： 在跨相关数据集比较嵌入的同时，保持坐标系统的一致性。要获得有意义的对齐，`relations` 是必需的；每个字典描述的是一个数据集中的样本与下一个数据集中样本的对应关系。

## 可复现性

为确保结果可复现，请始终设置 `random_state` 参数：

```python
reducer = umap.UMAP(random_state=42)
```

UMAP 使用随机优化，因此在没有固定随机种子的情况下，多次运行的结果会略有不同。

设置 `random_state` 会优先保证输出的确定性。当吞吐量比精确的可重复性更重要时，可以不设置它，因为在没有固定种子的情况下，UMAP 能够使用更多并行度。

## 常见问题与解决方案

**问题**： 出现互不相连的部分或碎片化的聚类
- **解决方案**： 增大 `n_neighbors`，以强调更多全局结构

**问题**： 聚类过于分散或分离不明显
- **解决方案**： 减小 `min_dist`，以允许更紧密的堆积

**问题**： 聚类结果不佳
- **解决方案**： 使用针对聚类的专用参数（n_neighbors=30、min_dist=0.0、n_components=5-10）

**问题**： 转换结果与训练结果差异明显
- **解决方案**： 确保测试数据的分布与训练数据一致，或改用 Parametric UMAP

**问题**： 在大数据集上性能缓慢
- **解决方案**： 设置 `low_memory=True`（默认值），或考虑先用 PCA 做降维

**问题**： 输入数据中存在 NaN 或 inf 值
- **解决方案**： 在拟合之前对无效行进行插补或删除。当前的 UMAP 在 `fit()` 和 `update()` 中使用了类似 scikit-learn 风格的有限值检查（`ensure_all_finite`），因此干净的数值输入是最安全的默认做法

**问题**： 所有点都坍缩到单一聚类中
- **解决方案**： 检查数据预处理（确保缩放正确），增大 `min_dist`

**问题**： 导入解析到了本地文件而非真正的包
- **解决方案**： 不要在笔记本或脚本旁边保留名为 `umap.py`、`sklearn.py`、`hdbscan.py` 或 `tensorflow.py` 的项目文件。这些名称会遮蔽已安装的包，破坏示例代码或使其产生误导。

## 资源

### 官方文档

- [UMAP user guide](https://umap-learn.readthedocs.io/en/latest/)
- [Release notes](https://umap-learn.readthedocs.io/en/latest/release_notes.html)
- [PyPI package](https://pypi.org/project/umap-learn/)（当前稳定版：0.5.12）
- [GitHub repository](https://github.com/lmcinnes/umap)

### references/ 目录

包含详细的 API 文档：
- `api_reference.md`：完整的 UMAP 类参数与方法

在需要详细参数信息或高级方法用法时，加载这些参考文件。
