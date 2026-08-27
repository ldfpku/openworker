# PyMC 贝叶斯建模

## 概览

PyMC 是一个用于贝叶斯建模和概率编程的 Python 库。使用 PyMC 现代版 API
(6.x 及以上版本),可以构建、拟合、验证和比较贝叶斯模型，包括分层模型、
MCMC 采样(NUTS)、变分推断(variational inference)、后验预测检查
(posterior predictive checks),以及模型比较(LOO、WAIC)。

## 当前版本与环境搭建

截至 2026 年 6 月,PyMC 6.0.1 是当前的稳定发行版。它要求 Python 3.12+,
使用 PyTensor 3 作为计算图后端，并默认使用 Numba 等编译后端。为了保证本地
环境可复现，应锁定版本:

```bash
uv pip install "pymc[nutpie]==6.0.1"
```

`nutpie` 附加组件启用的是更快的 Rust/Numba NUTS 实现。如果要使用
NumPyro 或 BlackJAX,应在同一环境中安装这些可选的采样器依赖，并在项目
锁定文件中固定它们的版本。

## 何时使用本技能

在以下情况下应当使用本技能:
- 构建贝叶斯模型(线性/逻辑回归、分层模型、时间序列等)
- 执行 MCMC 采样或变分推断
- 进行先验/后验预测检查
- 诊断采样问题(发散、收敛性、有效样本量 ESS)
- 使用信息准则(LOO、WAIC)比较多个模型
- 通过贝叶斯方法实现不确定性量化
- 处理分层/多层次数据结构
- 以有原则的方式处理缺失数据或测量误差

## 标准贝叶斯工作流程

绝不要先采样、再检查。这套八步工作流程——附带代码的完整说明见
[references/standard_workflow.md](references/standard_workflow.md)——是:

1. **数据准备**——包括标准化预测变量，使先验更容易解释。
2. **模型构建**——在 `pm.Model` 上下文中定义先验和似然。
3. **先验预测检查**——在拟合*之前*先确认先验隐含的数据是否合理。
4. **拟合模型**——用带显式随机种子的 `pm.sample()`。
5. **检查诊断信息**——R-hat、ESS、发散(divergences)。发散会使拟合结果
   失效；应修正模型或做重参数化，而不是抬高 `target_accept` 碰运气。
6. **后验预测检查**——拟合后的模型能否重现观测到的数据?
7. **分析结果**——从后验分布中给出摘要和区间估计。
8. **做出预测**——通过 `pm.set_data` 和后验预测采样，对新数据做预测。

可复用的模型结构和模型比较方法，见
[references/model_patterns.md](references/model_patterns.md)。

## 分布选型指南

### 用于先验

**尺度参数**(σ、τ):
- `pm.HalfNormal('sigma', sigma=1)` —— 默认选择
- `pm.Exponential('sigma', lam=1)` —— 备选方案
- `pm.Gamma('sigma', alpha=2, beta=1)` —— 信息量更强

**无界参数**:
- `pm.Normal('theta', mu=0, sigma=1)` —— 用于标准化后的数据
- `pm.StudentT('theta', nu=3, mu=0, sigma=1)` —— 对异常值稳健

**正值参数**:
- `pm.LogNormal('theta', mu=0, sigma=1)`
- `pm.Gamma('theta', alpha=2, beta=1)`

**概率值**:
- `pm.Beta('p', alpha=2, beta=2)` —— 弱信息先验
- `pm.Uniform('p', lower=0, upper=1)` —— 无信息先验(应谨慎使用)

**相关性矩阵**:
- `pm.LKJCholeskyCov('chol', n=n_vars, eta=2, sd_dist=pm.HalfNormal.dist(1))` —— 首选的协方差先验
- `pm.LKJCorr('corr', n=n_vars, eta=2)` —— 仅相关性的先验;eta=1 为均匀分布,eta>1 偏向单位矩阵

### 用于似然

**连续型结局**:
- `pm.Normal('y', mu=mu, sigma=sigma)` —— 连续数据的默认选择
- `pm.StudentT('y', nu=nu, mu=mu, sigma=sigma)` —— 对异常值稳健

**计数数据**:
- `pm.Poisson('y', mu=lambda)` —— 等离散(equidispersed)计数
- `pm.NegativeBinomial('y', mu=mu, alpha=alpha)` —— 过离散(overdispersed)计数
- `pm.ZeroInflatedPoisson('y', psi=psi, mu=mu)` —— 零值过多
- `pm.HurdleNegativeBinomial('y', psi=psi, mu=mu, alpha=alpha)` —— 零值过多且存在过离散

**二元结局**:
- `pm.Bernoulli('y', p=p)` 或 `pm.Bernoulli('y', logit_p=logit_p)`

**分类结局**:
- `pm.Categorical('y', p=probs)`

**参见**: `references/distributions.md` 获取完整的分布参考

## 采样与推断

### 使用 NUTS 做 MCMC

大多数模型的默认且推荐方式:

```python
idata = pm.sample(
    draws=2000,
    tune=1000,
    chains=4,
    target_accept=0.9,
    random_seed=42
)
```

**需要时可做的调整**:
- 出现发散 → 将 `target_accept` 提高到 `0.95` 或更高
- 采样过慢 → 使用 ADVI 做初始化
- 离散参数 → 对离散变量使用 `pm.Metropolis()`

### 变分推断

用于探索或初始化的快速近似方法:

```python
with model:
    approx = pm.fit(n=20000, method='advi')

    # Use for initialization
    initvals = approx.sample(return_inferencedata=False)[0]
    idata = pm.sample(initvals=initvals)
```

**权衡取舍**:
- 比 MCMC 快得多
- 是一种近似(可能低估不确定性)
- 适合大模型或快速探索

**参见**: `references/sampling_inference.md` 获取详细的采样指南

## 诊断脚本

### 全面诊断

```python
from scripts.model_diagnostics import create_diagnostic_report

create_diagnostic_report(
    idata,
    var_names=['alpha', 'beta', 'sigma'],
    output_dir='diagnostics/'
)
```

会生成:
- 迹图(Trace plots)
- 秩图(Rank plots,用于检查混合情况)
- 自相关图
- 能量图(Energy plots)
- 局部 ESS 图
- 汇总统计量 CSV

### 快速诊断检查

```python
from scripts.model_diagnostics import check_diagnostics

results = check_diagnostics(idata)
```

检查 R-hat、ESS、发散，以及树深度(tree depth)。

## 常见问题与解决方案

### 发散(Divergences)

**症状**: `idata.sample_stats.diverging.sum() > 0`

**解决方案**:
1. 将 `target_accept` 提高到 `0.95` 或 `0.99`
2. 使用非中心化参数化(non-centered parameterization,适用于分层模型)
3. 增加更强的先验以约束参数
4. 检查是否存在模型设定错误

### 有效样本量偏低

**症状**: `ESS < 400`

**解决方案**:
1. 增加采样次数:`draws=5000`
2. 重参数化以降低后验相关性
3. 对存在相关预测变量的回归，使用 QR 分解

### R-hat 偏高

**症状**: `R-hat > 1.01`

**解决方案**:
1. 运行更长的链:`tune=2000, draws=5000`
2. 检查是否存在多峰性(multimodality)
3. 用 ADVI 改进初始化

### 采样速度慢

**解决方案**:
1. 使用 ADVI 初始化
2. 降低模型复杂度
3. 提高并行度:`cores=8, chains=8`
4. 在合适的情况下使用变分推断

## 最佳实践

### 模型构建

1. **始终标准化预测变量**,以获得更好的采样效果
2. **使用弱信息先验**(而不是平坦先验)
3. **使用命名维度**(`dims`)以提高清晰度
4. 对分层模型使用**非中心化参数化**
5. 在拟合之前**检查先验预测**

### 采样

1. **运行多条链**(至少 4 条)以判断收敛性
2. **以 `target_accept=0.9`** 作为基线(需要时可调高)
3. 为模型比较**包含 `log_likelihood=True`**
4. **设置随机种子**以保证可复现性

### 验证

1. 在解读结果之前**检查诊断信息**(R-hat、ESS、发散)
2. 进行**后验预测检查**以验证模型
3. 适当情况下**比较多个模型**
4. **报告不确定性**(HDI 区间，而不仅仅是点估计)

### 工作流程

1. 从简单模型开始，逐步增加复杂度
2. 先验预测检查 → 拟合 → 诊断 → 后验预测检查
3. 根据检查结果迭代调整模型设定
4. 记录假设和先验选择的依据

## 资源

本技能包含:

### 参考文件(`references/`)

- **`distributions.md`**:按类别(连续型、离散型、多元型、混合型、时间
  序列)整理的 PyMC 分布完整目录。在选择先验或似然时使用。

- **`sampling_inference.md`**:关于采样算法(NUTS、Metropolis、SMC)、
  变分推断(ADVI、SVGD)以及处理采样问题的详细指南。在遇到收敛问题或需要
  选择推断方法时使用。

- **`workflows.md`**:针对常见模型类型、数据准备、先验选择和模型验证的
  完整工作流程示例与代码模式。可作为标准贝叶斯分析的参考手册使用。

### 脚本(`scripts/`)

- **`model_diagnostics.py`**:自动化的诊断检查与报告生成。函数:
  `check_diagnostics()` 用于快速检查,`create_diagnostic_report()` 用于
  带图表的全面分析。

- **`model_comparison.py`**:构建在 PSIS-LOO ELPD 之上的模型比较工具,
  这也是 ArviZ 1.x 的 `compare()` 用来排序的唯一标准。函数:
  `compare_models()`、`check_loo_reliability()`、`model_averaging()`。

### 模板(`assets/`)

- **`linear_regression_template.py`**:贝叶斯线性回归的完整模板，包含
  完整工作流程(数据准备、先验检查、拟合、诊断、预测)。

- **`hierarchical_model_template.py`**:分层/多层次模型的完整模板，使用
  非中心化参数化并包含组层面的分析。

## 快速参考

### 模型构建
```python
with pm.Model(coords={'var': names}) as model:
    # Priors
    param = pm.Normal('param', mu=0, sigma=1, dims='var')
    # Likelihood
    y = pm.Normal('y', mu=..., sigma=..., observed=data)
```

### 采样
```python
idata = pm.sample(draws=2000, tune=1000, chains=4, target_accept=0.9)
```

### 诊断
```python
from scripts.model_diagnostics import check_diagnostics
check_diagnostics(idata)
```

### 模型比较
```python
from scripts.model_comparison import compare_models
compare_models({'m1': idata1, 'm2': idata2}, ic='loo')
```

### 预测
```python
with model:
    pm.set_data({'X_data': X_new})
    pred = pm.sample_posterior_predictive(idata, predictions=True)
```

## 补充说明

- PyMC 与 ArviZ 集成，用于可视化和诊断;PyMC 6 / ArviZ 1 使用 xarray
  `DataTree`,同时保留了 `.posterior`、`.posterior_predictive` 等熟悉的
  分组方式
- 使用 `pm.model_to_graphviz(model)` 可视化模型结构
- 用 `idata.to_netcdf('results.nc')` 保存结果
- 用 `az.from_netcdf('results.nc')` 加载结果
- 对于非常大的模型，可以考虑使用 minibatch ADVI 或数据子采样
