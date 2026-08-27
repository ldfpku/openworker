# Statistical Analysis（统计分析）

## 概述

进行假设检验（t 检验、方差分析 ANOVA、卡方检验）、回归、相关性分析和贝叶斯分析，并系统地检查前提假设、给出效应量、按 APA 格式撰写报告。目标是产出一份评审者挑不出毛病的分析：正确的检验方法、经过验证的前提假设、诚实的效应量，以及完整的报告。

## 何时使用本技能

在以下情况使用本技能:
- 进行统计假设检验（t 检验、ANOVA、卡方检验、非参数检验）
- 进行回归或相关性分析
- 运行贝叶斯统计分析
- 检查统计前提假设并做诊断
- 计算效应量并进行功效分析（power analysis）
- 以 APA 格式报告统计结果
- 为研究分析实验数据或观测数据

---

## 安装

使用 **uv** 安装本技能所用的库。生产环境中请固定版本号；探索阶段不固定版本也没问题。

```bash
# 核心频率派（frequentist）工具栈（Python 3.10+；推荐 3.12+ 以获得最新的 SciPy/ArviZ）
uv pip install "pingouin>=0.6" "scipy>=1.11" "statsmodels>=0.14.6" pandas matplotlib seaborn

# 贝叶斯建模（PyMC 5 + ArviZ）
uv pip install "pymc>=5.0" "arviz>=1.0"
```

**兼容性说明（已针对 pingouin 0.6.1、statsmodels 0.14.6、arviz 1.2，2026 年验证通过）**：

- **Pingouin 0.6.0** 将输出列名中的特殊字符去掉了：`p_val`、`cohen_d`、`CI95`、`p_unc`（此前在 0.5.x 中分别是 `p-val`、`cohen-d`、`CI95%`、`p-unc`）。下面的示例使用的是当前的列名；如果你还停留在 0.5.x，请改用带连字符的形式。
- **statsmodels + SciPy**：请配合使用 `statsmodels>=0.14.6` 与 `scipy>=1.11`，以避免在 SciPy 1.16+ 上出现 `_lazywhere` 导入错误。
- **ArviZ 1.x**：`az.summary()` 现在默认使用 **89% 区间**（`eti89` 列），宽度参数是 `ci_prob`（而非 `hdi_prob`）。要报告常规的 95% 可信区间，请传入 `az.summary(trace, ci_prob=0.95)`。
- **单侧贝叶斯因子（Bayes Factor）已从 Pingouin 中移除**：`pg.ttest(..., alternative='greater')` 会悄悄丢弃 `BF10` 列，而 `pg.bayesfactor_ttest` 在传入单侧备择假设时会抛出异常。对于单侧贝叶斯检验，请直接使用 PyMC（计算方向性假设的后验概率）或 JASP/R 的 BayesFactor 包。

模型层面的 API（OLS、GLM、ARIMA）请参见 **statsmodels** 技能。PyMC 工作流请参见 **pymc** 技能。

---

## 分析工作流程

每一次严谨的分析都遵循同一个流程弧线。跳过步骤正是分析最终被撤回的原因，所以请按顺序逐步完成，并在每一步说明你做了什么。

1. **在接触数据之前先明确问题**。 陈述假设、结局变量（outcome）和预测变量（predictor）,以及研究设计（独立组还是配对、组数）。此时就要确定计划要用的检验方法——先看结果再挑检验方法就是 p 值篡改（p-hacking），即便是无意为之也是如此。
2. **检视数据**。 按组统计：样本量 n、均值、标准差 SD、中位数、缺失值。在做任何检验之前先绘制原始数据图（直方图或箱线图）。组间样本量不等、缺失数据、天花板/地板效应，以及离群值都会改变哪种检验是合适的——把这些情况呈现给用户，而不是悄悄自行处理。
3. **选择检验方法**，参考下面的速查表，或对于超出基础范畴的设计（计数、生存时间/事件、信度、析因设计）参考 `references/test_selection_guide.md`。
4. **用 `scripts/assumption_checks.py` 检查前提假设。** 如果某项假设不成立，改用备选检验方法（见下表），并同时报告原计划和所做的变更。
5. **运行检验**，并始终同时计算效应量——p 值只说明效应是否存在；效应量才说明是否有人应该在意。
6. **报告结果**，使用下面的 APA 模板，内容包括描述性统计、精确统计量、带置信区间的效应量，以及所做的前提假设检查。

如果用户只需要其中一步（例如"我需要多少参与者？"），可以直接跳到对应部分——但仍要确认该计算所依赖的设计假设。

---

## 检验方法选择指南

### 速查表：选择正确的检验方法

关于全面的指导（计数、生存分析、信度、析因设计），请使用 `references/test_selection_guide.md`。速查表：

**比较两组**：
- 独立、连续型、正态 → 独立样本 t 检验
- 独立、连续型、非正态 → Mann-Whitney U 检验
- 配对、连续型、正态 → 配对 t 检验
- 配对、连续型、非正态 → Wilcoxon 符号秩检验
- 二元结局 → 卡方检验或 Fisher 精确检验

**比较 3 组及以上**：
- 独立、连续型、正态 → 单因素方差分析（One-way ANOVA）
- 独立、连续型、非正态 → Kruskal-Wallis 检验
- 配对、连续型、正态 → 重复测量方差分析
- 配对、连续型、非正态 → Friedman 检验

**关系型**：
- 两个连续型变量 → Pearson 相关（正态）或 Spearman 相关（非正态）
- 连续型结局 + 预测变量 → 线性回归
- 二元结局 + 预测变量 → 逻辑回归

**贝叶斯替代方法**：
所有检验都有对应的贝叶斯版本，可以对假设给出直接的概率陈述、量化证据强度的贝叶斯因子，以及支持零假设（null）的能力。参见 `references/bayesian_statistics.md`。

---

## 前提假设检查

**在解读检验结果之前，务必先检查前提假设**，并报告检查结果——评审者会留意这些内容。

使用附带的 `scripts/assumption_checks.py` 模块。从技能目录（`skills/statistical-analysis/`）运行 Python，或将 `scripts/` 加入 `sys.path`：

```python
from assumption_checks import comprehensive_assumption_check

# 离群值 + 正态性（按组）+ 方差齐性，并附带图形
results = comprehensive_assumption_check(
    data=df,
    value_col='score',
    group_col='group',  # 可选：用于组间比较
    alpha=0.05
)
```

如需针对性检查，可导入单个函数：

```python
from assumption_checks import (
    check_normality,                # Shapiro-Wilk 检验 + Q-Q 图 + 直方图
    check_normality_per_group,
    check_homogeneity_of_variance,  # Levene 检验 + 箱线图
    check_linearity,                # 简单回归的散点图 + 残差图
    check_regression_diagnostics,   # 完整的 OLS 诊断（见下方"回归"部分）
    detect_outliers                 # IQR 或 z 分数方法
)

result = check_normality(data=df['score'], name='Test Score', alpha=0.05, plot=True)
print(result['interpretation'])
print(result['recommendation'])
```

### 前提假设不成立时该怎么办

**正态性不成立**：
- 轻微偏离 + 每组 n > 30 → 继续使用参数检验（稳健）
- 中度偏离 → 使用非参数替代方法
- 严重偏离 → 转换数据或使用非参数检验

**方差齐性不成立**：
- 对 t 检验 → 使用 Welch t 检验（`pg.ttest` 在 `correction='auto'` 时会自动应用）
- 对 ANOVA → 使用 Welch ANOVA（`pg.welch_anova`）或 Brown-Forsythe 检验
- 对回归 → 使用稳健标准误或加权最小二乘法

**线性关系不成立（回归）**：
- 添加多项式项、转换变量，或使用非线性模型 / GAM

随着 n 增大，形式化检验会变得过度敏感：当 n ≥ 100 时，应更看重 Q-Q 图而不是 Shapiro-Wilk 的 p 值。完整指导参见 `references/assumptions_and_diagnostics.md`。

---

## 运行统计检验

主要使用的库：
- **pingouin**：易用的检验方法，默认返回效应量——标准检验优先使用它
- **scipy.stats**：核心统计检验
- **statsmodels**：回归、诊断、功效分析
- **pymc** + **arviz**：贝叶斯建模与诊断

### 附完整报告的 T 检验

```python
import pingouin as pg

# correction='auto' 会在方差不等时自动应用 Welch 校正
result = pg.ttest(group_a, group_b, correction='auto')

# Pingouin >= 0.6 的列名
t_stat = result['T'].values[0]
df = result['dof'].values[0]
p_value = result['p_val'].values[0]
cohens_d = result['cohen_d'].values[0]
ci_lower, ci_upper = result['CI95'].values[0]  # 均值差的置信区间

print(f"t({df:.0f}) = {t_stat:.2f}, p = {p_value:.3f}, d = {cohens_d:.2f}")
```

### 带事后检验的方差分析（ANOVA）

```python
import pingouin as pg

aov = pg.anova(dv='score', between='group', data=df, detailed=True)
print(aov)

# 效应量：偏 eta 方 (partial eta-squared)
eta_p2 = aov['np2'].values[0]

# 如果显著，进行事后检验（Tukey HSD 可控制族系误差率）
if aov['p_unc'].values[0] < 0.05:
    posthoc = pg.pairwise_tukey(dv='score', between='group', data=df)
    print(posthoc)  # 每对比较都包含 Hedges' g
```

### 带诊断的线性回归

```python
import statsmodels.api as sm
from assumption_checks import check_regression_diagnostics

X = sm.add_constant(X_predictors)  # 添加截距项
model = sm.OLS(y, X).fit()
print(model.summary())

# 4 面板残差图 + Shapiro-Wilk、Breusch-Pagan、Durbin-Watson、VIF
diag = check_regression_diagnostics(model)
print(diag['interpretation'])
print(diag['vif'])

# 如果检测到异方差，改为报告稳健标准误
robust = model.get_robustcov_results('HC3')
```

### 贝叶斯 T 检验

```python
import pymc as pm
import arviz as az
import numpy as np

with pm.Model() as model:
    # 先验
    mu1 = pm.Normal('mu_group1', mu=0, sigma=10)
    mu2 = pm.Normal('mu_group2', mu=0, sigma=10)
    sigma = pm.HalfNormal('sigma', sigma=10)

    # 似然
    y1 = pm.Normal('y1', mu=mu1, sigma=sigma, observed=group_a)
    y2 = pm.Normal('y2', mu=mu2, sigma=sigma, observed=group_b)

    # 派生量
    diff = pm.Deterministic('difference', mu1 - mu2)

    trace = pm.sample(2000, tune=1000)

# ArviZ 1.x 默认使用 89% 区间；报告时需显式请求 95%
print(az.summary(trace, var_names=['difference'], ci_prob=0.95))

# 直接的概率陈述（这正是单侧问题所转化成的形式）
prob_greater = np.mean(trace.posterior['difference'].values > 0)
print(f"P(mu1 > mu2 | data) = {prob_greater:.3f}")

# ArviZ 1.x 移除了 az.plot_posterior；请改用 plot_dist（在 0.x 上 plot_posterior 仍可用）
az.plot_dist(trace, var_names=['difference'], ci_prob=0.95)
```

请根据数据来缩放先验（例如，`sigma=10` 适用于 SD 接近 10 的结局；可以观测到的 SD 作为参考），并在报告中说明所用的先验。

---

## 效应量

**效应量量化的是幅度大小；p 值只表明效应是否存在**。 每个检验都应报告一个效应量。完整指南参见 `references/effect_sizes_and_power.md`。

### 速查表：常见效应量

| 检验 | 效应量 | 小 | 中 | 大 |
|------|-------------|-------|--------|-------|
| T 检验 | Cohen's d | 0.20 | 0.50 | 0.80 |
| ANOVA | η²_p | 0.01 | 0.06 | 0.14 |
| 相关性 | r | 0.10 | 0.30 | 0.50 |
| 回归 | R² | 0.02 | 0.13 | 0.26 |
| 卡方检验 | Cramér's V | 0.07 | 0.21 | 0.35 |

这些基准是约定俗成的惯例，而非铁律——一个"小"效应也可能事关重大（例如药物副作用），而一个"大"效应也可能无关紧要。需要结合具体情境解读。

### 计算效应量

Pingouin 在其检验中会一并返回效应量（`pg.ttest` 返回 `cohen_d`、`pg.anova` 返回 `np2`、`pg.pairwise_tukey` 返回 `hedges`；`pg.corr` 返回的 `r` 本身就是一种效应量）。

### 效应量的置信区间

报告效应量的置信区间以展示其精度。使用 `pg.compute_esci`（注意：`pg.compute_effsize_from_t` 只返回点估计——它**不**返回置信区间）：

```python
import pingouin as pg

d = pg.compute_effsize(group_a, group_b, eftype='cohen')
ci_lower, ci_upper = pg.compute_esci(stat=d, nx=len(group_a), ny=len(group_b),
                                     eftype='cohen', confidence=0.95)
print(f"d = {d:.2f}, 95% CI [{ci_lower:.2f}, {ci_upper:.2f}]")
```

---

## 功效分析（Power Analysis）

### 先验功效分析（研究设计阶段）

在数据收集之前确定所需的样本量：

```python
from statsmodels.stats.power import tt_ind_solve_power, FTestAnovaPower

# T 检验：要检测出 d = 0.5，每组需要多大的 n？
n_required = tt_ind_solve_power(
    effect_size=0.5,
    alpha=0.05,
    power=0.80,
    ratio=1.0,
    alternative='two-sided'
)
print(f"Required n per group: {n_required:.0f}")

# 单因素方差分析：要检测出 Cohen's f = 0.25，需要多大的 n？
# 说明：参数是 k_groups；effect_size 是 Cohen's f（f = sqrt(eta2/(1-eta2)));
# 且 solve_power 返回的是总样本量，而不是每组的样本量
import math
anova_power = FTestAnovaPower()
n_total = anova_power.solve_power(
    effect_size=0.25,
    k_groups=3,
    alpha=0.05,
    power=0.80
)
print(f"Required total N: {math.ceil(n_total)} ({math.ceil(n_total / 3)} per group)")
```

### 敏感性分析（研究完成后）

确定该研究能够检测到的效应量：

```python
# 每组 n=50 时，在 80% 功效下能检测出多大的效应？
detectable_d = tt_ind_solve_power(
    effect_size=None,  # 求解此项
    nobs1=50,
    alpha=0.05,
    power=0.80,
    ratio=1.0,
    alternative='two-sided'
)
print(f"Study could detect d >= {detectable_d:.2f}")
```

**注意**：事后的"观测功效（observed power）"（根据观测到的效应量计算功效）是循环论证且具有误导性的——它只是 p 值的一个确定性函数。如果研究已经完成，有人问及功效，应改为进行敏感性分析。

详细指导参见 `references/effect_sizes_and_power.md`。

---

## 报告结果

请遵循 `references/reporting_standards.md` 中的 APA 格式规范。每份报告都需要包含：

1. **描述性统计**：所有组/变量的 M（均值）、SD、n
2. **检验统计量**：检验名称、统计量、自由度 df、精确的 p 值（写作 `p = .034`，而不是 `p < .05`；只有低于 .001 时才使用 `p < .001`）
3. **效应量**：附带置信区间
4. **前提假设检查**：运行了哪些检验、结果如何、采取了什么应对措施
5. **所有计划中的分析**：包括不显著的发现——省略它们就是"挑樱桃式"选择性报告（cherry-picking）

### 报告模板示例

#### 独立样本 T 检验

```
Group A (n = 48, M = 75.2, SD = 8.5) scored significantly higher than
Group B (n = 52, M = 68.3, SD = 9.2), t(98) = 3.82, p < .001, d = 0.77,
95% CI [0.36, 1.18], two-tailed. Assumptions of normality (Shapiro-Wilk:
Group A W = 0.97, p = .18; Group B W = 0.96, p = .12) and homogeneity
of variance (Levene's F(1, 98) = 1.23, p = .27) were satisfied.
```

#### 单因素方差分析（ANOVA）

```
A one-way ANOVA revealed a significant main effect of treatment condition
on test scores, F(2, 147) = 8.45, p < .001, η²_p = .10. Post hoc
comparisons using Tukey's HSD indicated that Condition A (M = 78.2,
SD = 7.3) scored significantly higher than Condition B (M = 71.5,
SD = 8.1, p = .002, d = 0.87) and Condition C (M = 70.1, SD = 7.9,
p < .001, d = 1.07). Conditions B and C did not differ significantly
(p = .52, d = 0.18).
```

#### 多元回归

```
Multiple linear regression was conducted to predict exam scores from
study hours, prior GPA, and attendance. The overall model was significant,
F(3, 146) = 45.2, p < .001, R² = .48, adjusted R² = .47. Study hours
(B = 1.80, SE = 0.31, β = .35, t = 5.78, p < .001, 95% CI [1.18, 2.42])
and prior GPA (B = 8.52, SE = 1.95, β = .28, t = 4.37, p < .001,
95% CI [4.66, 12.38]) were significant predictors, while attendance was
not (B = 0.15, SE = 0.12, β = .08, t = 1.25, p = .21, 95% CI [-0.09, 0.39]).
Multicollinearity was not a concern (all VIF < 1.5).
```

#### 贝叶斯分析

```
A Bayesian independent samples t-test was conducted using weakly
informative priors (Normal(0, 10) for group means). The posterior
distribution indicated that Group A scored higher than Group B
(M_diff = 6.8, 95% credible interval [3.2, 10.4]), with a 99.8%
posterior probability that Group A's mean exceeded Group B's mean.
Convergence diagnostics were satisfactory (all R-hat < 1.01, ESS > 1000).
```

如果使用的是非参数检验，应报告中位数而非均值、U/W/H 统计量，以及基于秩的效应量（例如秩双列相关，rank-biserial correlation，由 `pg.mwu` 以 `RBC` 返回）。

---

## 贝叶斯统计

在以下情况下考虑采用贝叶斯方法：
- 你有先验信息可以纳入分析
- 你希望对假设给出直接的概率陈述（"该效应有 95% 的概率落在此区间内"）
- 样本量较小，或数据是按顺序收集的（不需要为可选停止 optional stopping 做校正）
- 你需要量化*支持*零假设的证据
- 模型较为复杂（分层结构、缺失数据）

关于先验设定、贝叶斯因子、可信区间、分层模型，以及收敛性检查（R-hat < 1.01、足够的有效样本量 ESS、后验预测检查），参见 `references/bayesian_statistics.md`。

---

## 附带资源

### 参考文档（`references/`）

- **test_selection_guide.md**：涵盖组间比较、关系型分析、计数、生存时间/事件、信度/一致性，以及分类变量分析的决策树
- **assumptions_and_diagnostics.md**：关于检查和处理前提假设违反情况的详细指导
- **effect_sizes_and_power.md**：效应量的计算、解读与报告；功效分析
- **bayesian_statistics.md**：先验、贝叶斯因子、可信区间、分层模型、诊断
- **reporting_standards.md**：附带完整示例的 APA 风格报告指南

### 脚本（`scripts/`）

- **assumption_checks.py**：带可视化的自动化前提假设检查
  - `comprehensive_assumption_check()`：一次调用完成离群值 + 正态性 + 方差齐性检查
  - `check_normality()`、`check_normality_per_group()`：带 Q-Q 图的 Shapiro-Wilk 检验
  - `check_homogeneity_of_variance()`：带箱线图的 Levene 检验
  - `check_regression_diagnostics()`：针对已拟合的 OLS 模型的 4 面板残差图 + Shapiro-Wilk、Breusch-Pagan、Durbin-Watson、VIF
  - `check_linearity()`、`detect_outliers()`

---

## 统计诚信

以下是保证分析立得住的实践准则。它们之所以重要，是因为最常见的统计失误往往不是计算错误——而是隐性的随意性（不断尝试直到得到想要的结果）和选择性报告。

1. **区分验证性分析与探索性分析**。 在运行分析之前先陈述计划中的分析；将过程中发现的其他内容标记为探索性发现。
2. **不要"购物式"地寻找显著性**。 如果计划中的检验不显著，那就是结果。反复尝试其他检验、子组划分或离群值剔除方案直到 p < .05，会使 p 值失效。
3. **在运行一系列检验时，对多重比较进行校正**（事后 ANOVA 用 Tukey HSD；其他情形用 Holm 或 Benjamini-Hochberg 错误发现率 FDR 校正），并说明使用了哪种校正方法。
4. **不显著的结果不等于没有效应的证据**。 当 n 较小时，研究很可能只是功效不足（underpowered）——应进行敏感性分析，或使用贝叶斯分析/等效性检验来真正量化对零假设的支持程度。
5. **统计显著性不等于实际重要性**。 当 n 较大时，微不足道的效应也能达到 p < .001。解读时应以效应量为主导。
6. **在删除数据行之前先理解缺失数据的机制**。 列表式删除（listwise deletion）只有在数据完全随机缺失（MCAR）时才是安全的；否则应考虑多重插补（multiple imputation），并说明所采取的处理方式。
7. **让分析可复现**。 设置随机种子，为基于模拟的方法报告库版本，并将分析保存为可运行的脚本。
