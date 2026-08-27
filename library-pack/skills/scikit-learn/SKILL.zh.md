# Scikit-learn

## 概述

此技能为使用 scikit-learn(用于经典机器学习的行业标准 Python 库)完成机器学习任务提供了全面的指导。将此技能用于分类、回归、聚类、降维、预处理、模型评估，以及构建生产级的 ML 流水线(pipeline)。

## 安装

针对 **scikit-learn 1.8.0**(稳定版;2025 年 12 月)进行了测试。需要 **Python 3.11–3.14**(1.8+ 版本提供了自由线程 free-threaded CPython 3.14 的轮子包)。

安装 PyPI 上的包 **`scikit-learn`**(而不是 PyPI 上已弃用的 `sklearn` 包)。在代码中以 `sklearn` 导入。

```bash
# Install scikit-learn using uv
uv pip install "scikit-learn>=1.7"

# Optional: plotting utilities and bundled script dependencies
uv pip install "scikit-learn[plots]" matplotlib seaborn

# Commonly used with
uv pip install pandas numpy
```

检查你的版本:

```python
import sklearn
print(sklearn.__version__)
```

## 何时使用此技能

在以下情况使用 scikit-learn 技能:

- 构建分类或回归模型
- 执行聚类或降维
- 为机器学习预处理和变换数据
- 用交叉验证评估模型性能
- 用网格搜索或随机搜索调优超参数
- 为生产工作流创建 ML 流水线
- 比较不同算法在某任务上的表现
- 处理结构化(表格型)数据和文本数据
- 需要可解释的经典机器学习方法

## 快速开始

### 分类示例

```python
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

# Split data
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)

# Preprocess
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Train model
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train_scaled, y_train)

# Evaluate
y_pred = model.predict(X_test_scaled)
print(classification_report(y_test, y_pred))
```

### 处理混合数据类型的完整流水线

```python
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.ensemble import GradientBoostingClassifier

# Define feature types
numeric_features = ['age', 'income']
categorical_features = ['gender', 'occupation']

# Create preprocessing pipelines
numeric_transformer = Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('scaler', StandardScaler())
])

categorical_transformer = Pipeline([
    ('imputer', SimpleImputer(strategy='most_frequent')),
    ('onehot', OneHotEncoder(handle_unknown='ignore'))
])

# Combine transformers
preprocessor = ColumnTransformer([
    ('num', numeric_transformer, numeric_features),
    ('cat', categorical_transformer, categorical_features)
])

# Full pipeline
model = Pipeline([
    ('preprocessor', preprocessor),
    ('classifier', GradientBoostingClassifier(random_state=42))
])

# Fit and predict
model.fit(X_train, y_train)
y_pred = model.predict(X_test)
```

## 核心能力

五个能力领域在
[references/core_capabilities.md](references/core_capabilities.md) 中有文档说明，各主题的具体细节
分别在 [references/supervised_learning.md](references/supervised_learning.md)、
[references/unsupervised_learning.md](references/unsupervised_learning.md)、
[references/model_evaluation.md](references/model_evaluation.md)、
[references/preprocessing.md](references/preprocessing.md) 以及
[references/pipelines_and_composition.md](references/pipelines_and_composition.md) 中:

1. **监督学习** —— 分类和回归的估计器(estimator)家族。
2. **无监督学习** —— 聚类、分解和流形学习(manifold learning)。
3. **模型评估与选择** —— 评价指标、交叉验证和超参数搜索。
4. **数据预处理** —— 缩放、编码、插补和特征选择。
5. **流水线与组合** —— `Pipeline` 和 `ColumnTransformer`。

始终在 `Pipeline` 内部拟合预处理步骤，这样每一个交叉验证折(fold)都会重新拟合它;
在切分数据之前进行缩放或插补，会让测试信息泄漏到训练过程中。

两个完整的工作流示例见
[references/common_workflows.md](references/common_workflows.md)。

## 示例脚本

### 分类流水线

运行一个包含预处理、模型比较、超参数调优和评估的完整分类工作流:

```bash
uv run python scripts/classification_pipeline.py
```

此脚本演示了:
- 处理混合数据类型(数值型和类别型)
- 用交叉验证进行模型比较
- 用 GridSearchCV 进行超参数调优
- 用多种指标进行全面评估
- 特征重要性分析

### 聚类分析

执行聚类分析，包括算法比较和可视化:

```bash
uv run python scripts/clustering_analysis.py
```

此脚本演示了:
- 寻找最优簇数(肘部法则、轮廓系数分析)
- 比较多种聚类算法(K-Means、DBSCAN、层次聚类、高斯混合模型)
- 在没有真实标签的情况下评估聚类质量
- 用 PCA 投影来可视化结果

## 参考文档

此技能包含涵盖具体主题深入内容的全面参考文件:

### 快速参考
**文件**: `references/quick_reference.md`
- 常见的导入模式和安装说明
- 常见任务的快速工作流模板
- 算法选择速查表
- 常见模式与坑点
- 性能优化技巧

### 监督学习
**文件**: `references/supervised_learning.md`
- 线性模型(回归和分类)
- 支持向量机
- 决策树和集成方法
- K 近邻、朴素贝叶斯、神经网络
- 算法选择指南

### 无监督学习
**文件**: `references/unsupervised_learning.md`
- 所有聚类算法及其参数和使用场景
- 降维技术
- 离群点(outlier)与新颖点(novelty)检测
- 高斯混合模型
- 方法选择指南

### 模型评估
**文件**: `references/model_evaluation.md`
- 交叉验证策略
- 超参数调优方法
- 分类、回归和聚类的评价指标
- 学习曲线与验证曲线
- 模型选择的最佳实践

### 预处理
**文件**: `references/preprocessing.md`
- 特征缩放和归一化
- 类别变量编码
- 缺失值插补
- 特征工程技术
- 自定义变换器

### 流水线与组合
**文件**: `references/pipelines_and_composition.md`
- Pipeline 的构建和使用
- ColumnTransformer 处理混合数据类型
- FeatureUnion 实现并行变换
- 完整的端到端示例
- 最佳实践

## 最佳实践

### 始终使用流水线(Pipeline)
流水线能防止数据泄漏并确保一致性:
```python
# Good: Preprocessing in pipeline
pipeline = Pipeline([
    ('scaler', StandardScaler()),
    ('model', LogisticRegression())
])

# Bad: Preprocessing outside (can leak information)
X_scaled = StandardScaler().fit_transform(X)
```

### 仅在训练数据上拟合
绝不要在测试数据上拟合:
```python
# Good
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)  # Only transform

# Bad
scaler = StandardScaler()
X_all_scaled = scaler.fit_transform(np.vstack([X_train, X_test]))
```

### 分类任务使用分层切分(Stratified Splitting)
保持类别分布不变:
```python
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)
```

### 设置随机种子以保证可重复性
```python
model = RandomForestClassifier(n_estimators=100, random_state=42)
```

### 选择合适的评价指标
- 平衡数据:准确率(Accuracy)、F1 分数
- 不平衡数据:精确率(Precision)、召回率(Recall)、ROC AUC、平衡准确率(Balanced Accuracy)
- 代价敏感场景:定义自定义评分器(scorer)

### 在需要时缩放特征
需要特征缩放的算法:
- SVM、KNN、神经网络
- PCA、带正则化的线性/逻辑回归
- K-Means 聚类

不需要缩放的算法:
- 基于树的模型(决策树、随机森林、梯度提升)
- 朴素贝叶斯

## 常见问题故障排查

### ConvergenceWarning(收敛警告)
**问题**: 模型未收敛
**解决方案**: 增加 `max_iter`,或对特征进行缩放
```python
model = LogisticRegression(max_iter=1000)
```

### 测试集上表现不佳
**问题**: 过拟合
**解决方案**: 使用正则化、交叉验证，或更简单的模型
```python
# Add regularization
model = Ridge(alpha=1.0)

# Use cross-validation
scores = cross_val_score(model, X, y, cv=5)
```

### 大型数据集出现内存错误
**解决方案**: 使用为大数据设计的算法
```python
# Use SGD for large datasets
from sklearn.linear_model import SGDClassifier
model = SGDClassifier()

# Or MiniBatchKMeans for clustering
from sklearn.cluster import MiniBatchKMeans
model = MiniBatchKMeans(n_clusters=8, batch_size=100)
```

## 更多资源

- 官方文档: https://scikit-learn.org/stable/
- 用户指南: https://scikit-learn.org/stable/user_guide.html
- API 参考: https://scikit-learn.org/stable/api/index.html
- 示例陈列馆: https://scikit-learn.org/stable/auto_examples/index.html
