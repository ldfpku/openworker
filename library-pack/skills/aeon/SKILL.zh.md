# Aeon 时间序列机器学习

## 概述

Aeon 是一个与 scikit-learn 兼容的时间序列机器学习 Python 工具包（[aeon-toolkit.org](https://www.aeon-toolkit.org/)）。它提供了涵盖分类、回归、聚类、预测、异常检测、分割、相似性搜索、距离度量、变换、基准测试和可视化的算法——所有算法都使用一致的估计器（estimator）API。

**版本说明**： 示例针对 **aeon 1.x**（稳定文档版本：v1.4.0，2026 年 3 月）。v1.0 版本重构了预测（forecasting）和变换（transformations）模块；导入路径与 aeon 0.x/sktime 时代的代码不同。

## 何时使用此技能

在以下情况应用此技能：
- 对时间序列数据进行分类或预测
- 检测时间序列中的异常或变化点
- 对相似的时间序列模式进行聚类
- 预测未来数值
- 寻找重复出现的模式（基序，motif）或异常的子序列（discord）
- 使用专门的距离度量比较时间序列
- 从时间数据中提取特征

## 安装

需要 **Python 3.10+**（推荐 3.11+）。为保证可复现性，请固定 1.x 版本：

```bash
uv pip install "aeon>=1.4,<2"
```

对于深度学习预测器/分类器及其他可选估计器：

```bash
uv pip install "aeon[all_extras]>=1.4,<2"
```

在 zsh 中，请为 extras 部分加上引号：`uv pip install "aeon[all_extras]>=1.4,<2"`。

### 实验性模块

上游将 **forecasting（**预测**）、anomaly_detection（**异常检测**）、segmentation（**分割**）、similarity_search**（相似性搜索）和 **visualisation**（可视化）视为实验性模块——接口可能在小版本发布之间发生变化。除非需要这些具体任务，否则生产流水线应优先使用稳定模块（分类、回归、聚类、距离、变换）。

## 核心能力

### 1. 时间序列分类

将时间序列归类到预定义的类别中。完整算法目录参见 `references/classification.md`。

**快速开始**：
```python
from aeon.classification.convolution_based import RocketClassifier
from aeon.datasets import load_classification

# Load data
X_train, y_train = load_classification("GunPoint", split="train")
X_test, y_test = load_classification("GunPoint", split="test")

# Train classifier
clf = RocketClassifier(n_kernels=10000)
clf.fit(X_train, y_train)
accuracy = clf.score(X_test, y_test)
```

**算法选择**：
- **速度 + 性能**：`MiniRocketClassifier`、`Arsenal`
- **最高精度**：`HIVECOTEV2`、`InceptionTimeClassifier`
- **可解释性**：`ShapeletTransformClassifier`、`Catch22Classifier`
- **小数据集**：使用 DTW 距离的 `KNeighborsTimeSeriesClassifier`

### 2. 时间序列回归

从时间序列预测连续数值。算法参见 `references/regression.md`。

**快速开始**：
```python
from aeon.regression.convolution_based import RocketRegressor
from aeon.datasets import load_regression

X_train, y_train = load_regression("Covid3Month", split="train")
X_test, y_test = load_regression("Covid3Month", split="test")

reg = RocketRegressor()
reg.fit(X_train, y_train)
predictions = reg.predict(X_test)
```

### 3. 时间序列聚类

在没有标签的情况下对相似的时间序列进行分组。方法参见 `references/clustering.md`。

**快速开始**：
```python
from aeon.clustering import TimeSeriesKMeans

clusterer = TimeSeriesKMeans(
    n_clusters=3,
    distance="dtw",
    averaging_method="ba"
)
labels = clusterer.fit_predict(X_train)
centers = clusterer.cluster_centers_
```

### 4. 预测（Forecasting）

预测未来的时间序列数值（在 aeon 1.x 中为实验性模块）。预测器参见 `references/forecasting.md`。

**快速开始**：
```python
import numpy as np
from aeon.forecasting import NaiveForecaster
from aeon.forecasting.stats import ARIMA

y_train = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])

# Set horizon in the constructor; predict passes the series to forecast from
naive = NaiveForecaster(strategy="last", horizon=5)
naive.fit(y_train)
y_pred = naive.predict(y_train)

# ARIMA uses p/d/q (not order=); multi-step via iterative_forecast
arima = ARIMA(p=1, d=1, q=1)
arima.fit(y_train)
y_pred = arima.iterative_forecast(y_train, prediction_horizon=5)
```

### 5. 异常检测

识别异常模式或离群值。检测器参见 `references/anomaly_detection.md`。

**快速开始**：
```python
from aeon.anomaly_detection import STOMP

detector = STOMP(window_size=50)
anomaly_scores = detector.fit_predict(y)

# Higher scores indicate anomalies
threshold = np.percentile(anomaly_scores, 95)
anomalies = anomaly_scores > threshold
```

### 6. 分割（Segmentation）

将时间序列划分为带变化点的多个区域。参见 `references/segmentation.md`。

**快速开始**：
```python
from aeon.segmentation import ClaSPSegmenter

segmenter = ClaSPSegmenter()
change_points = segmenter.fit_predict(y)
```

### 7. 相似性搜索

在单条或多条时间序列中寻找相似模式。参见 `references/similarity_search.md`。

**快速开始**：
```python
from aeon.similarity_search import StompMotif

# Find recurring patterns
motif_finder = StompMotif(window_size=50, k=3)
motifs = motif_finder.fit_predict(y)
```

## 特征提取与变换

为特征工程对时间序列进行变换。参见 `references/transformations.md`。

**ROCKET 特征**：
```python
from aeon.transformations.collection.convolution_based import RocketTransformer

rocket = RocketTransformer()
X_features = rocket.fit_transform(X_train)

# Use features with any sklearn classifier
from sklearn.ensemble import RandomForestClassifier
clf = RandomForestClassifier()
clf.fit(X_features, y_train)
```

**统计特征**：
```python
from aeon.transformations.collection.feature_based import Catch22

catch22 = Catch22()
X_features = catch22.fit_transform(X_train)
```

**预处理**：
```python
from aeon.transformations.collection import MinMaxScaler, Normalizer

scaler = Normalizer()  # Z-normalization
X_normalized = scaler.fit_transform(X_train)
```

## 距离度量

专门用于时间维度的距离度量。完整目录参见 `references/distances.md`。

**用法**：
```python
from aeon.distances import dtw_distance, dtw_pairwise_distance

# Single distance
distance = dtw_distance(x, y, window=0.1)

# Pairwise distances
distance_matrix = dtw_pairwise_distance(X_train)

# Use with classifiers
from aeon.classification.distance_based import KNeighborsTimeSeriesClassifier

clf = KNeighborsTimeSeriesClassifier(
    n_neighbors=5,
    distance="dtw",
    distance_params={"window": 0.2}
)
```

**可用的距离**：
- **弹性（Elastic）**：DTW、DDTW、WDTW、ERP、EDR、LCSS、TWE、MSM
- **锁步（Lock-step）**：欧氏距离（Euclidean）、曼哈顿距离（Manhattan）、闵可夫斯基距离（Minkowski）
- **基于形状（Shape-based）**：Shape DTW、SBD

## 深度学习网络

用于时间序列的神经网络架构。参见 `references/networks.md`。

**架构**：
- 卷积类：`FCNClassifier`、`ResNetClassifier`、`InceptionTimeClassifier`
- 循环类：`RecurrentNetwork`、`TCNNetwork`
- 自编码器：`AEFCNClusterer`、`AEResNetClusterer`

**用法**：
```python
from aeon.classification.deep_learning import InceptionTimeClassifier

clf = InceptionTimeClassifier(n_epochs=100, batch_size=32)
clf.fit(X_train, y_train)
predictions = clf.predict(X_test)
```

## 数据集与基准测试

加载标准基准数据集并评估性能。参见 `references/datasets_benchmarking.md`。

**加载数据集**：
```python
from aeon.datasets import load_classification, load_gunpoint, load_regression

# Classification (generic loader or dataset-specific helper)
X_train, y_train = load_classification("GunPoint", split="train")
X_train, y_train = load_gunpoint(split="train")  # same UCR dataset

# Regression
X_train, y_train = load_regression("Covid3Month", split="train")
```

**基准测试**：
```python
from aeon.benchmarking import get_estimator_results

# Compare with published results
published = get_estimator_results("ROCKET", "GunPoint")
```

## 常见工作流

### 分类流水线

```python
from aeon.transformations.collection import Normalizer
from aeon.classification.convolution_based import RocketClassifier
from sklearn.pipeline import Pipeline

pipeline = Pipeline([
    ('normalize', Normalizer()),
    ('classify', RocketClassifier())
])

pipeline.fit(X_train, y_train)
accuracy = pipeline.score(X_test, y_test)
```

### 特征提取 + 传统机器学习

```python
from aeon.transformations.collection import RocketTransformer
from sklearn.ensemble import GradientBoostingClassifier

# Extract features
rocket = RocketTransformer()
X_train_features = rocket.fit_transform(X_train)
X_test_features = rocket.transform(X_test)

# Train traditional ML
clf = GradientBoostingClassifier()
clf.fit(X_train_features, y_train)
predictions = clf.predict(X_test_features)
```

### 带可视化的异常检测

```python
from aeon.anomaly_detection import STOMP
import matplotlib.pyplot as plt

detector = STOMP(window_size=50)
scores = detector.fit_predict(y)

plt.figure(figsize=(15, 5))
plt.subplot(2, 1, 1)
plt.plot(y, label='Time Series')
plt.subplot(2, 1, 2)
plt.plot(scores, label='Anomaly Scores', color='red')
plt.axhline(np.percentile(scores, 95), color='k', linestyle='--')
plt.show()
```

## 最佳实践

### 数据准备

1. **归一化**：大多数算法都受益于 Z 归一化
   ```python
   from aeon.transformations.collection import Normalizer
   normalizer = Normalizer()
   X_train = normalizer.fit_transform(X_train)
   X_test = normalizer.transform(X_test)
   ```

2. **处理缺失值**：分析前先进行插补
   ```python
   from aeon.transformations.collection import SimpleImputer
   imputer = SimpleImputer(strategy='mean')
   X_train = imputer.fit_transform(X_train)
   ```

3. **检查数据格式**：集合（collection）使用 `(n_cases, n_channels, n_timepoints)`；单条序列使用 `(n_channels, n_timepoints)`（参见[数据格式](https://www.aeon-toolkit.org/en/stable/api_reference/data_format.html)）

### 模型选择

1. **从简单开始**：在使用深度学习之前先尝试 ROCKET 变体
2. **使用验证集**：将训练数据切分出一部分用于超参数调优
3. **对比基线**：与简单方法（1-NN 欧氏距离、朴素方法）进行比较
4. **考虑资源限制**：追求速度用 ROCKET，若有 GPU 可用则考虑深度学习

### 算法选择指南

**快速原型开发**：
- 分类：`MiniRocketClassifier`
- 回归：`MiniRocketRegressor`
- 聚类：使用欧氏距离的 `TimeSeriesKMeans`

**追求最高精度**：
- 分类：`HIVECOTEV2`、`InceptionTimeClassifier`
- 回归：`InceptionTimeRegressor`
- 预测：`AutoARIMA`、`AutoETS`、`TCNForecaster`（深度学习需要 `[all_extras]`）

**追求可解释性**：
- 分类：`ShapeletTransformClassifier`、`Catch22Classifier`
- 特征：`Catch22`、`TSFresh`

**小数据集**：
- 基于距离的方法：使用 DTW 的 `KNeighborsTimeSeriesClassifier`
- 应避免：深度学习（需要大量数据）

## 参考文档

`references/` 中提供了详细信息：
- `classification.md` - 所有分类算法
- `regression.md` - 回归方法
- `clustering.md` - 聚类算法
- `forecasting.md` - 预测方法
- `anomaly_detection.md` - 异常检测方法
- `segmentation.md` - 分割算法
- `similarity_search.md` - 模式匹配与基序发现
- `transformations.md` - 特征提取与预处理
- `distances.md` - 时间序列距离度量
- `networks.md` - 深度学习架构
- `datasets_benchmarking.md` - 数据加载与评估工具

## 附加资源

- 文档：https://www.aeon-toolkit.org/
- GitHub：https://github.com/aeon-toolkit/aeon
- 示例：https://www.aeon-toolkit.org/en/stable/examples.html
- API 参考：https://www.aeon-toolkit.org/en/stable/api_reference.html
