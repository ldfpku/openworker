# scikit-survival

## 适用范围

在以下涉及 scikit-survival 0.28.0 的工作流中使用本技能：

- 右删失（right-censored）的结构化结局数据；
- Cox PH、Coxnet、IPC ridge、生存树、随机森林、提升法（boosting）以及 SVM；
- 判别能力（discrimination）、预测误差、面向校准的检验，以及随时间变化的预测；
- 带竞争风险（competing risks）的非参数累积发生率（cumulative incidence）；
- scikit-learn 流水线（pipelines）、嵌套模型选择，以及可重复的报告。

scikit-survival 主要用于建模右删失结局。其内置的竞争风险支持是非参数的
累积发生率方法；它不提供 Fine-Gray 回归。不要将模型输出呈现为临床建议、
因果证据，或临床实用性的证明。

## 当前版本与安装

截至 2026-07-23 验证：

- 最新稳定版：**scikit-survival 0.28.0**，发布于 2026-07-05。
- Python：**3.11 或更高版本**；PyPI wheel 覆盖 Linux x86-64、
  macOS x86-64/ARM64 以及 Windows x86-64 上的 CPython 3.11-3.14。
- 运行时依赖版本范围：NumPy >=2.0.0、pandas >=2.2.0、SciPy >=1.13.0、
  scikit-learn >=1.9.0,<1.10、OSQP >=1.0.2、narwhals >=2.0.1。
- 0.28 通过 narwhals 增加了对 pandas/Polars 估计器的支持，并从
  `GradientBoostingSurvivalAnalysis` 中移除了 `criterion` 参数。

创建一个隔离环境，并安装经过测试的版本快照：

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install \
  "scikit-survival==0.28.0" \
  "scikit-learn==1.9.0" \
  "numpy==2.4.6" \
  "pandas==3.0.5" \
  "scipy==1.17.1" \
  "ecos==2.0.14" \
  "osqp==1.1.3" \
  "joblib==1.5.3" \
  "numexpr==2.14.2" \
  "narwhals==2.24.0"
```

优先使用二进制 wheel。从源码构建需要 C/C++ 编译器；OSQP 可能还需要 CMake。
本技能采用 MIT 许可证；上游的 scikit-survival 软件包采用 GPL-3.0-or-later
许可证，因此在再分发之前请先审查上游许可条款。

## 不可协商的工作流程

1. **明确估计目标和事件编码方式**。 确定目标是全事件生存、特定原因风险（cause-specific hazard），
   还是特定原因累积发生率。
2. **校验结局数据**。 标准估计器需要一个双字段的结构化数组：先是布尔型的事件字段，
   后是观察到的时间字段。竞争风险 CIF 则需要一个单独的整数型事件向量：
   0=删失，1..K=各原因。
3. **先划分数据集，再做学习型预处理**。 绝不能在划分数据集之前，
   就用全部数据行拟合插补器、编码器、缩放器、特征选择器，或选定 alpha 值。
4. **在流水线内部拟合预处理步骤**。 未知类别和缺失值必须只用训练折（training fold）
   内的状态来处理。
5. **调参时不要重复使用评估数据**。 报告经过交叉验证的调参后性能时，使用嵌套交叉验证
   （nested CV），或者保留一份真正未被触碰过的最终留出集（holdout）。
6. **在训练数据上拟合删失分布**。 IPCW 一致性指数（concordance）、动态 AUC，
   以及 Brier 指标接收的是 `survival_train`，而绝不是训练集加测试集混合后的结局。
7. **限定评估时间点**。 使用一个严格递增的时间网格，该网格须落在测试集随访期内，
   并低于训练支持集（training support）的末端——在这个范围内，估计出的
   删失生存概率仍保持为正值。
8. **让预测值与评估指标相匹配**。 一致性指数/动态 AUC 接收的是"数值越高风险越大"的分数。
   Brier 指标接收的是形状为 `(n_test, n_times)` 的生存概率，而不是风险分数，
   也不是未经求值的阶跃函数。
9. **明确处理竞争性原因（competing causes）**。 标准生存概率和 CIF 回答的是不同的问题。
   绝不能在把竞争性事件当作删失处理的同时，用 `1 - Kaplan-Meier` 来估计
   特定事件的概率。
10. **报告局限性**。 将判别能力、校准、预测误差和累积发生率分开报告。
    这些指标单独都不能确立决策效用或临床实用性。

## 结局数据的构造

```python
from sksurv.util import Surv

y = Surv.from_arrays(event=event_bool, time=observed_time)
# Equivalent for pandas or Polars:
y = Surv.from_dataframe("event", "time", frame)
```

第一个字段是布尔型（`True`=发生事件，`False`=右删失）；第二个字段是浮点型的时间。
字段名称可以不同，但字段顺序和含义不能改变。在加载自定义数据或竞争风险数据之前，
请先阅读 `references/data-handling.md`。

## 无数据泄漏的流水线

```python
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sksurv.linear_model import CoxPHSurvivalAnalysis

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, stratify=y["event"], random_state=20260723
)

preprocess = ColumnTransformer(
    [
        ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), numeric),
        (
            "cat",
            make_pipeline(
                SimpleImputer(strategy="most_frequent"),
                OneHotEncoder(handle_unknown="ignore", drop="first", sparse_output=False),
            ),
            categorical,
        ),
    ],
    sparse_threshold=0.0,
)
model = make_pipeline(preprocess, CoxPHSurvivalAnalysis(alpha=0.1, ties="efron"))
model.fit(X_train, y_train)
risk = model.predict(X_test)
```

数据划分应先于每一步学习型变换。对于存在重复或分组记录的情况，
应使用分组感知（group-aware）的划分方式；对于按时间部署的场景，
应使用尊重时间顺序的划分方式。

## 模型选择

- `CoxPHSurvivalAnalysis`：在比例风险（proportional hazards）假设下，
  给出可解释的对数风险系数；`alpha` 是岭回归收缩系数，`ties` 可取
  `"breslow"` 或 `"efron"`。
- `CoxnetSurvivalAnalysis`：面向高维数据的 LASSO/弹性网（elastic-net）路径。
  `l1_ratio` 取值范围为 `(0, 1]`；在请求生存函数或累积风险函数之前，
  需使用 `fit_baseline_model=True`。
- `IPCRidge`：IPC 加权的岭回归 AFT 模型；预测结果处于时间/对数时间尺度上，
  而不是 Cox 风险分数。
- `RandomSurvivalForest` / `ExtraSurvivalTrees`：非线性的生存和累积风险预测；
  应使用置换重要性（permutation importance），而不是不纯度重要性
  （impurity importance）。
- `GradientBoostingSurvivalAnalysis`：使用 `"coxph"`、`"squared"` 或
  `"ipcwls"` 损失函数的树提升方法。`criterion` 参数已在 0.28 中被移除。
- `ComponentwiseGradientBoostingSurvivalAnalysis`：稀疏的、按分量进行的
  线性提升方法。
- `FastSurvivalSVM` / `FastKernelSurvivalSVM`：排序或回归目标函数。
  只有 `rank_ratio=1` 才会直接返回"数值越高风险越大"的分数；SVM 不会
  产生可用于 Brier 指标的生存概率。

在解读系数或预测结果之前，请阅读相应模型的参考文档：
`references/cox-models.md`、`references/ensemble-models.md` 或
`references/svm-models.md`。

## 预测与评估指标的约定

```python
import numpy as np
from sksurv.metrics import (
    brier_score,
    concordance_index_ipcw,
    cumulative_dynamic_auc,
    integrated_brier_score,
)

risk = model.predict(X_test)  # (n_test,), higher means higher event risk
uno_c = concordance_index_ipcw(y_train, y_test, risk, tau=times[-1])[0]
auc_t, mean_auc = cumulative_dynamic_auc(y_train, y_test, risk, times)

surv_fns = model.predict_survival_function(X_test)
surv_prob = np.vstack([fn(times) for fn in surv_fns])  # (n_test, n_times)
_, brier_t = brier_score(y_train, y_test, surv_prob, times)
ibs = integrated_brier_score(y_train, y_test, surv_prob, times)
```

- Harrell C 和 Uno C 度量的是排序判别能力，而不是校准度。
- 累积/动态 AUC 度量的是在选定时间点上的判别能力，接受一维或随时间变化的
  二维风险分数；它不接受生存概率。
- Brier 分数是经删失加权的概率误差，同时反映判别能力和校准度。
  它不是一条独立的校准曲线。
- 校准度评估需要在独立数据上，针对特定时间点做"预测值 vs. 观测值"的检验。
  scikit-survival 0.28 没有专门的校准曲线 API。

关于假设条件、原始文献、安全的时间网格构造方式，以及评分器（scorer）包装类，
请参见 `references/evaluation-metrics.md`。

## 流水线、元数据路由与调参

普通的 `Pipeline.fit(X, y)` 不需要任何元数据路由（metadata-routing）设置。
诸如 `as_concordance_index_ipcw_scorer` 这样的指标包装器是估计器包装类，
而不是 `scoring=` 可调用对象：

```python
from sklearn.model_selection import GridSearchCV
from sksurv.metrics import as_concordance_index_ipcw_scorer

wrapped = as_concordance_index_ipcw_scorer(model, tau=tau)
search = GridSearchCV(
    wrapped,
    {"estimator__coxphsurvivalanalysis__alpha": [0.01, 0.1, 1.0]},
    cv=inner_splits,
)
```

该包装器会从每个训练折中学习删失分布。被包装的参数需加上 `estimator__` 前缀。
仅在通过元估计器（meta-estimator）传递额外元数据时才启用 scikit-learn 的
元数据路由。举例来说，Coxnet 的 `set_predict_request(alpha=True)` 只有在
配合 `sklearn.set_config(enable_metadata_routing=True)` 路由 `alpha` 预测参数时
才有意义。

内层调参之后，使用外层交叉验证循环获得无偏的交叉验证性能估计。
不要用同一批折数既选择参数又报告性能，把它当成外部验证结果。

## 竞争风险

```python
from sksurv.nonparametric import cumulative_incidence_competing_risks

# status: integer array, 0=censored, 1..K=mutually exclusive causes
time, cif = cumulative_incidence_competing_risks(status, observed_time)
total_cif = cif[0]
cause_1_cif = cif[1]
```

`cif` 的形状为 `(K + 1, n_times)`；第 0 行是总体风险，第 1..K 行是
特定原因的累积发生率。特定原因的 Cox 模型将其他原因视为删失来估计
特定原因的风险，但这类模型的 `1 - survival` 并不等于特定原因的 CIF。
参见 `references/competing-risks.md`。

## 内置的本地 CLI 工具

当没有提供输入时，所有辅助工具都使用确定性的合成数据。它们不发起任何网络请求，
拒绝 URL 和符号链接，对文件/行数/特征数设有上限，避免不安全的 pickle 加载，
并延迟导入科学计算相关的包。

```bash
python skills/scikit-survival/scripts/validate_survival_csv.py --help
python skills/scikit-survival/scripts/train_survival_model.py --help
python skills/scikit-survival/scripts/evaluate_survival_metrics.py --help
python skills/scikit-survival/scripts/competing_risk_cif.py --help
python skills/scikit-survival/scripts/model_report.py --help
```

典型的本地工作流程：

```bash
python skills/scikit-survival/scripts/validate_survival_csv.py \
  --input data.csv --event-column event --time-column time \
  --feature-columns age,group,measurement --structured-output outcome.npy

python skills/scikit-survival/scripts/train_survival_model.py \
  --input data.csv --event-column event --time-column time \
  --numeric-columns age,measurement --categorical-columns group \
  --model coxph --tune --prediction-output predictions.npz \
  --output training-summary.json

python skills/scikit-survival/scripts/evaluate_survival_metrics.py \
  --input predictions.npz --output metrics-summary.json

python skills/scikit-survival/scripts/model_report.py \
  --training-summary training-summary.json \
  --metrics-summary metrics-summary.json --output model-report.md
```

只使用经过去标识化处理、获得授权的本地数据。所捆绑的测试数据仅包含
合成记录，不含任何患者数据或 PHI（受保护健康信息）。

## 安全性排查

`SECURITY.md` 此前曾声称本技能捆绑了名为 `sklearn.py` 和 `sksurv.py`
的包遮蔽（package-shadowing）文件。2026-07-23 的盘点确认这些文件
并不存在；该说法是一个虚假的分析器发现。此次更新只增加了具有描述性
命名的辅助脚本，没有影子模块（shadow module）、环境变量读取，或网络调用。

绝不要用某个被导入的包的名字来命名项目脚本（包括 `sklearn.py`、
`sksurv.py`、`numpy.py` 或 `pandas.py`），因为 Python 可能会导入
本地文件而不是已安装的库。在执行从不可信来源复制来的示例代码之前，
先检查工作目录。

## 参考文件

- `references/data-handling.md` —— 结构化数组、数据集、模式（schema）校验、
  pandas/Polars 预处理，以及无数据泄漏的划分方式。
- `references/cox-models.md` —— Cox PH、Coxnet、IPCRidge、假设条件与调参。
- `references/ensemble-models.md` —— 随机森林、决策树、提升法、预测，
  以及置换重要性。
- `references/svm-models.md` —— SVM 目标函数、预测方向、缩放、核函数，
  以及局限性。
- `references/evaluation-metrics.md` —— 指标输入、删失相关假设、时间网格、
  校准、嵌套交叉验证，以及原始文献。
- `references/competing-risks.md` —— 整数型事件编码、CIF API、内置数据集、
  特定原因风险，以及不支持的 Fine-Gray 回归。

## 标注日期的来源

官方 API 与兼容性来源，核查于 2026-07-23：

- [PyPI 0.28.0](https://pypi.org/project/scikit-survival/) —— 发布于 2026-07-05。
- [GitHub v0.28.0 release](https://github.com/sebp/scikit-survival/releases/tag/v0.28.0)
  —— 发布于 2026-07-05。
- [0.28 发布说明](https://scikit-survival.readthedocs.io/en/stable/release_notes/v0.28.html)。
- [安装指南](https://scikit-survival.readthedocs.io/en/stable/install.html)。
- [稳定版用户指南](https://scikit-survival.readthedocs.io/en/stable/user_guide/index.html)。
- [稳定版 API 参考](https://scikit-survival.readthedocs.io/en/stable/api/index.html)。
