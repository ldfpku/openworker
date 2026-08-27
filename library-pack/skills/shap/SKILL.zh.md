# SHAP

使用 SHAP 来描述一个已拟合的预测模型是如何将输入映射到输出的。基于现代的 `shap.Explanation` API 开展工作，明确指出被解释的输出以及背景分布(background distribution),并在解读任何解释结果之前先对其进行校验。

本 skill 与 **SHAP 0.52.0**(发布于 2026-05-28)保持一致。该版本要求 Python 3.12 或更高版本。

## 操作规则

1. 解释的是一个固定的、已评估过的模型；不要把 SHAP 当作预测性验证的替代品。
2. 使用留出集(held-out)或有明确标注的分析行来进行解释。背景数据行只能从恰当的训练集或参考总体中选取。
3. 明确说明被解释的输出是什么:回归值、原始 margin、概率、log loss、logit,还是其他模型方法的输出。
4. 让解释结果保持为 `shap.Explanation` 对象。调用 `explainer(X)`;只有在维护旧版代码时才使用 `.shap_values(X)`。
5. 对于多输出模型，在使用表格类图表之前先选定一个输出:`explanation[..., output_index]`。
6. 用 `base_values + values.sum(...)` 去核对被解释的确切模型输出。
7. 把 SHAP 当作是在某种掩码(masking)/背景数据选择之下，对模型行为的一种描述。它并不能确立因果关系、公平性、可申诉性(recourse),或科学机制。
8. 在检查过输入形状、预处理、模型版本、输出空间以及行的顺序之前，绝不要压制加性(additivity)失败的问题。
9. 不要加载不受信任的 pickle、joblib、模型或 explainer 构件；这些格式在反序列化时可能执行代码。

## 安装

创建一个隔离环境，并锁定文档记录的版本:

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install "shap[plots]==0.52.0"
```

`shap[plots]` 会安装绘图相关的依赖。要按照与项目兼容的版本添加已拟合模型所属的软件包。如需兼容更旧的 Python 版本，请阅读 [references/migration.md](references/migration.md),而不是悄悄安装一个不同的 SHAP 版本。

在调试 API 不匹配问题之前，先确认运行环境:

```python
import platform
import shap

print("Python:", platform.python_version())
print("SHAP:", shap.__version__)
```

## 标准工作流

### 1. 明确解释目标

需要记录:

- 模型及预处理的版本;
- 被解释的确切可调用对象或模型方法;
- 输出的名称/索引及单位;
- 评估用的数据行;
- 背景/参考总体;
- 所用的 masker 和 explainer 算法;
- SHAP 及模型库的版本。

对于分类器，要决定该任务需要的是原始 margin 还是概率。不同模型家族的默认设置各不相同；绝不要凭图表颜色或符号来推断单位。

### 2. 选择 explainer 和 masker

当自动分派已经足够时，从 `shap.Explainer(model, masker)` 开始。当某个专用 explainer 的假设条件或输出控制方式很重要时，再实例化该专用 explainer。

| 情形 | 推荐选择 | 重要约束 |
|---|---|---|
| 受支持的树集成模型 | `TreeExplainer` | `model_output="probability"` 和 `"log_loss"` 要求使用干预式掩码（interventional masking）并提供背景数据 |
| 线性模型 | `LinearExplainer` | masker 决定了是干预式行为还是关联感知式（correlation-aware）行为 |
| 小规模特征空间 | `ExactExplainer` | 成本随不受约束的特征数量快速增长 |
| 通用的表格类可调用对象 | `PermutationExplainer` | 至少要为一次完整的正向/反向置换预留预算 |
| 分层特征组、文本或图像 | `PartitionExplainer` | 分区树(partition tree)会改变这个合作博弈本身 |
| 可微的神经网络 | `DeepExplainer` 或 `GradientExplainer` | 框架支持情况、输出形状，以及背景数据的选择都需要测试 |
| 传统的 Kernel SHAP 工作流 | `KernelExplainer` | 通常比特定于模型的方法慢得多 |

详细的决策指南参见 [references/explainers.md](references/explainers.md)。当特征存在相关性、结构化、稀疏，或具有语义分组时，参见 [references/data-maskers.md](references/data-maskers.md)。

### 3. 计算一个现代形式的 `Explanation`

下面这个完整的二分类示例使用了明确的背景数据，并选取了正类的输出:

```python
import numpy as np
import shap
from sklearn.datasets import load_breast_cancer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

X, y = load_breast_cancer(as_frame=True, return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    stratify=y,
    random_state=7,
)

model = RandomForestClassifier(
    n_estimators=200,
    min_samples_leaf=3,
    random_state=7,
    n_jobs=-1,
).fit(X_train, y_train)

background = shap.sample(X_train, 100, random_state=7)
explainer = shap.Explainer(model, background, algorithm="tree")
all_outputs = explainer(X_test)

# sklearn tree classifiers expose one output per class.
positive = all_outputs[..., 1]
assert positive.values.shape == X_test.shape

reconstructed = np.asarray(positive.base_values) + positive.values.sum(axis=1)
expected = model.predict_proba(X_test)[:, 1]
np.testing.assert_allclose(reconstructed, expected, rtol=1e-5, atol=1e-6)

shap.plots.beeswarm(positive, max_display=15)
shap.plots.waterfall(positive[0], max_display=15)
```

输出的形状取决于具体模型:

- 单一表格类输出:`(samples, features)`;
- 多个表格类输出:`(samples, features, outputs)`;
- 多个模型输入:通常是数组或 explanation 组成的列表;
- 图像/文本类解释:特征轴的排布跟随输入的表示方式，若存在输出选择维度，则在最后一个轴上。

对于现代的多输出数组，不要使用 0.45 版之前的模式 `values[class_index]`。应使用 `values[..., class_index]`,或直接对 `Explanation` 本身进行切片。

### 4. 在需要时控制树模型输出的语义

对于受支持的树分类器，概率空间的解释必须显式指定:

```python
background = shap.sample(X_train, 200, random_state=7)

explainer = shap.TreeExplainer(
    model,
    data=background,
    feature_perturbation="interventional",
    model_output="probability",
)
probability_exp = explainer(X_test)
```

在 SHAP 0.52 中:

- 当提供了背景数据时,`feature_perturbation="auto"` 使用干预式语义，否则使用依赖树路径(tree-path-dependent)的语义;
- 概率和 log-loss 输出模式仅在干预式语义下受支持;
- 如果确实要有意使用保真度较低的树近似方法，请将 `approximate=True` 传给 `explainer(X, approximate=True)`;不要将其传给构造函数。

### 5. 有意识地使用一个与模型无关的可调用对象

传入将要被解释其输出的那个确切的可调用对象:

```python
masker = shap.maskers.Independent(background, max_samples=100)
explainer = shap.Explainer(
    model.predict_proba,
    masker,
    algorithm="permutation",
    output_names=[str(label) for label in model.classes_],
    seed=7,
)

budget = 2 * X_test.shape[1] + 1
all_outputs = explainer(X_test.iloc[:20], max_evals=budget)
positive = all_outputs[..., 1]
```

当估计结果不稳定时，增大 `max_evals`,以在更多次置换上取平均。要在报告中保留随机种子、背景数据样本，以及评估预算。

### 6. 针对问题本身来做可视化，而不只是选用现成的图表

| 问题 | 图表 |
|---|---|
| 哪些特征的平均归因幅度最大? | `shap.plots.bar(exp)` |
| 方向、幅度和观测值在全局层面如何变化? | `shap.plots.beeswarm(exp)` |
| 为什么某一个预测会偏离其基线? | `shap.plots.waterfall(exp[i])` |
| 某个特征的归因值如何随其取值变化? | `shap.plots.scatter(exp[:, feature])` |
| 各解释是否呈现出样本层面的模式? | `shap.plots.heatmap(exp)` |
| 预先定义的各群组之间在描述统计上有何差异? | `shap.plots.bar(exp.cohorts(labels).abs.mean(0))` |
| 哪些词元(token)或图像区域对某个输出有贡献? | `shap.plots.text(exp)` 或 `shap.plots.image(exp)` |

在定制或保存图表之前，请阅读 [references/plots.md](references/plots.md)。

### 7. 汇报结果时一并说明局限性

至少应报告以下内容:

- 输出及其单位;
- 基线/参考总体;
- 所用的 explainer 和 masker;
- 样本数量及其选取方式;
- 输出的索引/名称;
- 加性误差(additivity error)或适用的近似诊断信息;
- 已知的相关/分组特征;
- 结果是局部的、聚合的，还是特定于某个群组的;
- 一句明确的"非因果"声明。

## 常见任务

### 全局与局部分析

用全局图表来定位重要模式，用散点图来细看这些模式，用局部图表来调查所选定的数据行。不要在未记录选取规则的情况下，只挑选那些视觉上显眼的行。

### 多分类模型

尽可能设置 `output_names`,检查 `explanation.output_names`,并在绘图之前先对某个输出进行切片:

```python
class_exp = explanation[..., "class_name"]
# or
class_exp = explanation[..., class_index]
```

绝不要跨类别对带符号的归因值求平均。要进行跨类别比较，须保持相同的模型、相同的数据行、相同的背景数据、相同的输出空间，以及相同的聚合方式。

### 群组、子群分析与公平性

SHAP 可以比较模型在不同群组间是如何使用特征的，但这并不是一种公平性检验。某个受保护特征的 SHAP 幅度很小，并不能排除代理歧视(proxy discrimination)的存在；移除某个受保护特征，也不能确立公平性。要把归因分析与性能、校准度、错误率，以及适合该领域的公平性指标结合起来使用。

关于群组构建、模型比较、误差分析、log-loss 解释、监控以及生产环境记录，参见 [references/workflows.md](references/workflows.md)。

### 文本与图像

使用特定领域的 masker,而不要把词元或像素当作普通的独立列来处理:

- 对词元分组，使用 `shap.maskers.Text(tokenizer)` 搭配 `PartitionExplainer`;
- 对图像区域，使用 `shap.maskers.Image(...)` 搭配 `PartitionExplainer`;
- 对开销较大的多输出模型，用 `outputs=...` 加以限制。

关于当前的示例及输出形状方面的指导，参见 [references/modalities.md](references/modalities.md)。

## 排障顺序

1. 打印 Python、SHAP、模型所属库、NumPy,以及所用框架的版本。
2. 核实模型接收到的，与拟合时使用的完全是同一批经过转换的列、相同的顺序、相同的数据类型，以及相同的缺失值表示方式。
3. 打印 `values.shape`、`base_values.shape`、`data.shape`、`feature_names` 和 `output_names`。
4. 确认所选取的输出及其单位。
5. 在相同的数据行、相同的顺序下重新计算一次预测结果。
6. 用一个更小的批次以及有代表性的背景数据进行测试。
7. 只有到这一步之后，才去排查特定软件包的兼容性问题或近似设置。

关于加性失败、形状不匹配、类别型特征、pipeline、深度学习框架、绘图以及性能方面的问题，参见 [references/troubleshooting.md](references/troubleshooting.md)。

## 随附脚本

运行一个确定性的、自包含的表格类示例，它会写出重要性数据、元数据和图表:

```bash
uv run --no-project --python 3.12 --with "shap[plots]==0.52.0" \
  skills/shap/scripts/tabular_report.py --output-dir /tmp/shap-report
```

该脚本不会下载数据，也不会反序列化模型。把它当作一个模板来阅读，然后在保留输出选择和加性校验逻辑的前提下，替换掉内置的数据集和模型。

## 参考文件索引

| 文件 | 在何时加载 |
|---|---|
| [references/explainers.md](references/explainers.md) | 选择或配置 explainer 时 |
| [references/data-maskers.md](references/data-maskers.md) | 选择背景数据、掩码语义，或特征分组时 |
| [references/plots.md](references/plots.md) | 选择、组合或保存可视化图表时 |
| [references/workflows.md](references/workflows.md) | 开展审计、比较、群组分析、监控或生产环境工作流时 |
| [references/modalities.md](references/modalities.md) | 解释文本、图像或深度模型时 |
| [references/migration.md](references/migration.md) | 更新旧版 SHAP 代码，或需要支持更旧的 Python 时 |
| [references/theory.md](references/theory.md) | 需要解释估计量（estimand）、保证性质、依赖关系、交互作用以及局限性时 |
| [references/troubleshooting.md](references/troubleshooting.md) | 诊断运行时、形状、加性以及兼容性方面的问题时 |

## 主要来源

- Documentation: https://shap.readthedocs.io/en/latest/
- API reference: https://shap.readthedocs.io/en/latest/api.html
- Release notes: https://shap.readthedocs.io/en/latest/release_notes.html
- Repository: https://github.com/shap/shap
