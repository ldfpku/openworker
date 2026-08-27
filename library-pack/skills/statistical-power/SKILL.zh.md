# 统计功效与样本量（Statistical Power & Sample Size）

## 概述

功效分析（Power analysis）回答的是研究规划中最具决定性的问题之一：**要可靠地检测出某个特定大小的效应，需要多大的样本量？而以你能负担得起的样本量，又能检测出多大的效应**？ 功效不足的研究会浪费资源，并产生无定论或不可复现的结果；功效过高的研究则会浪费参与者、经费，并且（在临床研究中）让更多人暴露于不必要的风险之下。在数据收集*之前*把这件事做对，是一个项目中杠杆效应最大的统计决策。

对任意一项检验而言，以下四个量是彼此锁定的：**样本量（n）**、**效应量（effect size）**、**显著性水平**（α）以及**功效（power，即 1 − β）**。固定其中任意三个，第四个就随之确定。本技能中的每一次计算，本质上都是对这一关系的某种重排。

本技能涵盖两种进行功效分析的方式：
- **闭式解**（closed-form）公式（速度快，对标准检验给出精确解）——见 `references/closed_form_recipes.md`。
- **模拟/蒙特卡洛**（Simulation / Monte Carlo）方法（适用于任何你能够模拟和分析的设计或模型）——见 `references/simulation_based_power.md`。

关于如何选择和换算效应量——通常是最难的部分——见 `references/effect_sizes.md`。

## 何时使用本技能

- 在收集数据之前确定所需的样本量（先验功效分析，a priori power analysis）
- 在样本量已固定的情况下，求出最小可检测效应（minimum detectable effect，MDE）
- 为资助申请或研究方案绘制功效曲线（功效 vs. n，或功效 vs. 效应量）
- 为 IRB 提交材料、资助申请或预注册（pre-registration）论证样本量的合理性
- 为组间样本量不等或非 1:1 分配的设计确定功效
- 通过模拟来为没有教科书公式的设计确定功效（混合模型、逻辑/泊松回归、整群随机试验、生存分析、中介效应、交互作用）
- 在样本量估算中考虑多重比较、失访/脱落，或聚集效应（clustering）

## 安装

使用 **uv**。生产环境中应锁定版本；探索阶段不锁定也可以。

```bash
uv pip install "statsmodels>=0.14.6" "scipy>=1.11" "pingouin>=0.6" "numpy>=1.26" matplotlib pandas
# For simulation-based power of advanced models (optional, add as needed):
uv pip install lifelines            # survival
# mixed models and GLMs come with statsmodels
```

**兼容性说明**：请配合使用 `statsmodels>=0.14.6` 与 `scipy>=1.11`，以避免在 SciPy 1.16+
上出现 `_lazywhere` 导入错误。Pingouin 0.5+ 版本重命名了功效函数的参数名，与下文所用的名称一致。

---

## 决定一切的那一个决策：效应量

功效计算的可信度，取决于你输入的效应量本身是否可信。**不要凭空编造一个数字**。 按大致的优先顺序，应使用：

1. **最小重要效应（minimally important effect）**——真正会改变某项决策，或在科学/临床上确实重要的最小效应（即“感兴趣的最小效应量”，SESOI）。这是最站得住脚的依据：你是在为检测“真正重要的东西”而定功效，而不是为“你希望看到的东西”定功效。
2. **预实验或既往研究的估计值**，但要对其进行缩水（shrink）——发表出来的和预实验的效应量，往往会因发表偏倚（publication bias）和赢家的诅咒（winner's curse）而被夸大。直接以未经缩水的预实验估计值来定功效，往往会导致正式研究功效不足。
3. **约定俗成的取值**（Cohen 的小/中/大效应量），仅作为最后手段使用，且应明确说明你这样做了。

无论选用哪一种，都要进行**敏感性分析（sensitivity analysis）**：报告在一系列合理的效应量范围内，所需 n 是如何变化的，而不是只给一个单点数字。以单一数字呈现的功效分析，掩盖了其最大的不确定性来源。关于 d、f、r、η²、比值比（odds ratio）以及 Cohen 的 h/w 之间的基准值和换算方式，见 `references/effect_sizes.md`。

> **应避免事后（"观察到的"）功效（post-hoc / "observed" power）**。 用你刚刚估计出来的效应量去反算功效，这是循环论证：它是 p 值的一个确定性函数，没有提供任何新信息。如果一项研究已经完成，而你想知道它本可以检测出多大的效应，应报告**敏感性分析**（在已达到的 n 下的 MDE），或者更好的做法是，报告所观察到的效应量周围的置信区间。这是审稿人经常提出的意见——即使有人要求，也不要在不指出这个问题的情况下就直接给出观察到的功效。

---

## 快速用法（闭式解）

内置的 `scripts/power.py` 把 statsmodels 封装成一套统一的接口，这样你就不必记住每种检验分别对应哪个求解器。请从技能目录运行，或把 `scripts/` 添加到 `sys.path`。

```python
from power import sample_size, power, mde, power_curve

# 1. How many per group to detect Cohen's d = 0.5, two-sided, 80% power?
sample_size(test="t_ind", effect_size=0.5, power=0.80, alpha=0.05)
# -> required n per group

# 2. Two groups, 3:1 allocation (e.g. more controls than cases)
sample_size(test="t_ind", effect_size=0.5, power=0.80, ratio=3.0)

# 3. Fixed n=30/group — what's the minimum detectable d at 80% power?
mde(test="t_ind", nobs1=30, power=0.80, alpha=0.05)

# 4. One-way ANOVA, 4 groups, detect Cohen's f = 0.25
sample_size(test="anova", effect_size=0.25, k_groups=4, power=0.80)

# 5. Two proportions: 0.40 vs 0.55 (auto-converts to Cohen's h)
sample_size(test="two_proportions", prop1=0.40, prop2=0.55, power=0.80)

# 6. Correlation: detect r = 0.30
sample_size(test="correlation", effect_size=0.30, power=0.80)

# 7. Power curve for the grant figure
power_curve(test="t_ind", effect_size=0.5, n_range=range(10, 120, 5),
            save="power_curve.png")
```

支持的 `test=` 取值：`t_ind`（两独立均值）、`t_paired`/`t_one`（配对或单样本均值）、`anova`（单因素方差分析）、`two_proportions`、`one_proportion`、`correlation`、`chi2`（拟合优度/列联表检验，通过效应量 *w*）、`linear_regression`（R² 增量 / f²）。完整的参数表以及底层调用的 statsmodels 函数，见 `references/closed_form_recipes.md`。

---

## 没有公式时：用模拟

闭式解只存在于少数几类简单检验中。对于**逻辑/泊松回归、混合效应/重复测量模型、整群随机试验、生存分析、中介效应、多因素交互作用**，或任何非标准分析，正确的工具是模拟。其逻辑始终是相同的三个步骤：

1. **模拟**（Simulate）一份数据集，其生成过程基于你假设的真实情况（你想检测的效应，加上真实的噪声、基线率、聚集结构等）。
2. **分析**（Analyze）该数据集，使用你计划在真实数据上采用的*完全相同*的检验/模型。
3. **重复**（Repeat）多次（至少 1,000 次；若要在接近 80% 处得到稳定估计，需要 5,000–10,000 次）。功效即为多次重复中检验结果显著的比例。

`scripts/simulate_power.py` 提供了一个可复用的框架，以及若干已实现的示例（两组差异、逻辑回归、带 ICC 的整群随机试验、线性混合模型）。核心用法很简单：

```python
from simulate_power import simulate_power

def gen_and_test(n, rng):
    # build a dataset of size n under the assumed effect, run the planned test,
    # return True if the result is significant
    ...

est = simulate_power(gen_and_test, n=200, n_sims=2000, alpha=0.05)
print(f"Power at n=200: {est.power:.3f} (95% CI {est.ci_low:.3f}-{est.ci_high:.3f})")
```

请报告该估计值的**蒙特卡洛置信区间**（该框架会返回该值），这样读者才能判断 0.81 和 0.79 之间的差异是真实信号还是模拟噪声。关于完整的模式，包括如何搜索能达到目标功效的 n、以及如何对脱落和聚集效应建模，见 `references/simulation_based_power.md`。

---

## 容易被忽略的调整项

以下这些因素，往往是一项研究功效是否充足的关键分水岭。应显式地应用它们，并说明你确实这样做了。

- **多重比较（Multiple comparisons）**。 如果分析要检验 *m* 个假设，并采用 Bonferroni 类型的校正，就应在校正后的 α（例如 α/m）上为每个检验定功效，这会提高所需的 n。更好的做法是：直接通过模拟，针对整个族错误率（family-wise）或 FDR 控制流程来定功效。忽略这一点，会在不知不觉中让每个次要终点（secondary endpoint）都功效不足。
- **失访/脱落/不可用样本**。 功效计算给出的是你需要*完成分析*的 n。要相应地扩大*入组*的 n：`n_enroll = ceil(n_analyzed / (1 − dropout_rate))`。20% 的脱落率意味着入组人数应比公式给出的结果多 25%。
- **聚集效应（设计效应，design effect）**。 当观测值是嵌套结构时（例如患者嵌套在诊所中、细胞嵌套在动物个体中、重复测量嵌套在受试者中），有效样本量会小于原始计数。应按设计效应
  `DEFF = 1 + (m − 1)·ICC` 进行放大，其中 *m* 是簇（cluster）大小，ICC 是组内相关系数（intraclass correlation）。把聚集数据当作独立数据处理是**伪重复（pseudoreplication）**，会严重高估功效——对于整群随机设计，应改用模拟。
- **单侧 vs. 双侧**。 双侧检验是默认选项，几乎总是正确的选择；单侧检验之所以能"提高"功效，仅仅是因为它放弃了检测意料之外方向上的效应。任何单侧检验都需要给出理由。
- **不等分配**。 在总样本量固定的情况下，各组人数相等的效率最高。如果设计上分配比例是固定的（例如治疗组:对照组 = 2:1），应传入 `ratio=` 参数，使计算结果反映这一点。

---

## 工作流程

1. **说明研究设计以及计划采用的分析方法**。 你将要运行的检验决定了应采用哪种功效计算方法。如果分析是混合模型或广义线性模型（GLM），应直接采用模拟法。
2. **选择效应量**，其依据要站得住脚（SESOI > 经过缩水的预实验估计 > 约定俗成的取值），并写明理由。
3. **设定 α 和目标功效**。 常规默认值为 α = 0.05（双侧）、功效 = 0.80；在验证性/临床研究中常用 0.90。应说明所用的值。
4. **计算**，使用 `scripts/power.py`（闭式解）或 `scripts/simulate_power.py`（模拟）。
5. **敏感性分析**。 在一系列合理的效应量范围内重新计算，并绘制功效曲线。这才是最终交付物，而不是一个单一数字。
6. **应用调整**，针对脱落、聚集效应和多重性进行调整。
7. **报告**，按下面的模板进行。

---

## 报告模板

一份站得住脚的功效声明应包含所有输入，使读者能够复现它。请按需调整：

```
A priori power analysis was conducted to determine the sample size needed to detect
a [between-group difference of Cohen's d = 0.50], which we considered the smallest
effect of clinical interest. With α = .05 (two-sided) and power = .80, a two-sample
t-test requires n = 64 per group (128 total; computed with statsmodels 0.14).
Allowing for 20% attrition, we will enrol 160 participants. A sensitivity analysis
showed required n ranges from 45 to 105 per group across plausible effects
d = 0.40–0.60 (Figure X).
```

对于模拟法：还应说明数据生成过程所依据的假设（基线率、残差标准差、ICC、簇大小）、模拟次数以及蒙特卡洛置信区间。

---

## 常见误区

1. **凭空编造效应量**，或照搬一个被夸大的预实验估计值——这是功效分析出错最常见的方式。
2. **只报告单一的 n**，而不是敏感性区间/功效曲线。
3. **事后/观察到的功效**——这是循环论证，没有信息量；应改用敏感性分析或效应量的置信区间。
4. **忽略聚集效应**（伪重复）——把细胞/测量值当作彼此独立的受试者来计数。
5. **忘记考虑脱落**——按需要完成分析的 n 来定功效，但入组人数却与之相同。
6. **把 α 和功效混淆**，或把单侧和双侧混淆。
7. **只为主要终点定功效**，却同时报告需要远大得多的 n 才有意义的次要/交互作用检验。
8. **用一个你实际上不会去拟合的模型对应的 t 检验公式**（例如用基于均值的计算方法去规划一个逻辑回归研究）——应让功效计算方法与计划采用的分析方法相匹配。

---

## 资源

### 脚本
- `scripts/power.py` —— 统一的闭式解接口（`sample_size`、`power`、`mde`、`power_curve`），基于 statsmodels/pingouin，覆盖所有标准检验。
- `scripts/simulate_power.py` —— 蒙特卡洛功效计算框架，提供 `simulate_power()` 和 `find_sample_size()`，并附有已实现的示例（两组比较、逻辑回归、整群随机、线性混合模型）。

### 参考文档
- `references/closed_form_recipes.md` —— 逐检验的参数表和确切的 statsmodels/pingouin 调用方式，包括比例、卡方检验和回归。
- `references/simulation_based_power.md` —— GLM、混合模型、整群设计、生存分析和脱落处理的完整模拟模式。
- `references/effect_sizes.md` —— 效应量的选择（SESOI）、Cohen 的基准值，以及 d、f、r、η²/f²、OR、h、w 之间的换算。

### 相关技能
- **experimental-design** —— 在确定了 n 之后，用于规划具体的研究（随机化、区组、析因/DOE、交叉、序贯设计）。
- **statistical-analysis** —— 数据收集之后的假设检验前提检查、运行检验、效应量计算以及 APA 格式报告。
- **statsmodels** / **pymc** —— 用于拟合本文中提到的模型。

### 关键参考文献
- Cohen, J. (1988). *Statistical Power Analysis for the Behavioral Sciences* (2nd ed.).
- Lakens, D. (2022). *Sample Size Justification*. Collabra: Psychology, 8(1).
- Arnold, B. F. et al. (2011). Simulation methods to estimate design power. *BMC Medical Research Methodology*, 11:94.
