# Experimental Design（实验设计）

## 概述

一项研究的设计——实验单元如何被分配到各个条件、什么保持恒定、什么发生变化，以及以什么样的结构组织起来——决定了数据能够回答什么样的问题。事后的分析无法挽救一个存在混杂(confounded)或伪重复(pseudoreplicated)问题的设计。本技能关注的是数据采集*之前*所做的决策:选择一种能够分离出目标效应的设计、通过随机化来支持因果论断、通过分组(blocking)来消除已知的干扰变异，以及组织多因素实验使得各效应可被估计，而不是彼此纠缠在一起。

几乎所有优秀设计背后的三大理念(Fisher 的原则):
- **随机化(Randomization)** —— 随机地分配处理，使已知和未知的混杂因素在期望意义上保持平衡。正是这一点把一个比较变成了一个因果论断。
- **重复(Replication)** —— 在正确的层级上做独立重复，这样你才能估计变异性，而你观察到的效应也不会只是单个实验单元的偶然产物。最常见的致命错误是**伪重复(pseudoreplication)**:把同一个实验单元上的重复测量当作独立的重复样本来计数。
- **分组/局部控制(Blocking / local control)** —— 把相似的实验单元(按批次、日期、地点、窝别等)分组，并在组内做随机化，从而把这部分干扰变异从误差项中剔除，而不是任由它放大噪声。

本技能帮助你在各种设计类型中做选择，生成实际的随机化方案或 DOE(实验设计,Design of Experiments)布局(通过可复现的脚本),并避免那些让数据变得无法解读的结构性错误。

## 何时使用本技能

- 规划任何比较性实验或试验，并决定如何分配实验单元
- 把受试者/样本随机分配到各个组(简单随机化、分组随机化、分层随机化，或整群随机化)
- 通过分组或分层来消除干扰变异
- 设计多因素实验:全因子或部分因子设计、筛选设计
- 在连续因子上优化某个响应值(响应曲面设计)
- 受试者内/重复测量、交叉、裂区(split-plot),或拉丁方设计
- 整群随机化设计(按地点、诊所、班级、窝别分组)
- 决定重复样本的数量和层级，避免伪重复
- 带中期分析的序贯、组序贯或适应性设计
- 布局孔板/批次，并随机化运行顺序以对抗漂移

## 安装

```bash
uv pip install "numpy>=1.26" "pandas>=2.0" pyDOE3
```

`pyDOE3` 是 pyDOE/pyDOE2 的维护中继承者，提供全因子、部分因子、Plackett-Burman、中心复合(central-composite)、Box-Behnken 和拉丁超立方(Latin-hypercube)生成器。本技能内置的脚本对其进行了封装，以带命名列和随机化运行顺序、按真实因子单位返回设计方案。

---

## 选择设计

从你的问题和实验单元的结构出发，而不是从你偏好的某种设计出发。

```
What are you trying to learn?
│
├─ Compare a few predefined conditions (A vs B vs C)?
│   ├─ Units independent, possibly with a known nuisance factor (day, batch, site)?
│   │     → Completely randomized (no nuisance) or RANDOMIZED BLOCK design.
│   ├─ Each unit can receive every condition in sequence (washout possible)?
│   │     → CROSSOVER / repeated-measures design (more power, watch carry-over).
│   └─ You can only randomize groups, not individuals (schools, clinics)?
│         → CLUSTER-randomized design (analyze at the cluster level; see pseudoreplication).
│
├─ Screen MANY factors (5+) to find the few that matter?
│     → FRACTIONAL FACTORIAL or PLACKETT-BURMAN screening design.
│
├─ Quantify main effects AND interactions among a handful of factors?
│     → FULL 2^k FACTORIAL design.
│
├─ Find the settings that OPTIMIZE a response (curvature matters)?
│     → RESPONSE-SURFACE design: central composite or Box-Behnken.
│
└─ Explore a simulation/computer model over a continuous space?
      → SPACE-FILLING design: Latin hypercube.
```

各分支的详细指导:
- **随机化、分组、分层、对照** → `references/randomization_and_blocking.md`
- **因子设计、部分因子设计、筛选、响应曲面、DOE 概念(混叠、分辨率)** → `references/factorial_and_doe.md`
- **交叉、重复测量、裂区、拉丁方、整群、嵌套设计** → `references/design_types.md`
- **序贯、组序贯与适应性设计(中期分析)** → `references/sequential_and_adaptive.md`

---

## 生成设计方案

两个脚本可以生成即用型、可复现的方案布局。从本技能的 `scripts/` 目录运行它们，或将其加入 `sys.path`。所有内容都设有随机种子，这样确切的方案就可以被存档并重新生成——这是试验注册和良好实验室规范的一项要求。

### 随机化/分配方案 —— `scripts/randomization.py`

```python
from randomization import (
    simple_randomization, block_randomization,
    stratified_block_randomization, cluster_randomization,
    assign_factorial_runs, arm_balance,
)

# Permuted blocks keep the arms balanced throughout enrollment (use for n < ~100
# or sequential intake — simple randomization can drift out of balance with small n)
sched = block_randomization(n=60, arms=["treatment", "control"], seed=42)

# Balance a prognostic variable across arms by randomizing within each stratum
sched = stratified_block_randomization({"siteA": 30, "siteB": 30},
                                       arms=["drug", "placebo"], ratio=(2, 1), seed=42)

# Randomize whole clusters, not individuals (the cluster is the unit)
sched = cluster_randomization(["clinic1", "clinic2", "clinic3", "clinic4"], seed=42)

arm_balance(sched)            # sanity-check the counts per arm
sched.to_csv("allocation_schedule.csv", index=False)
```

如何在它们之间做选择:**simple**(简单随机化)在大样本量下没问题，但在小样本量下可能出现不平衡;**block**(分组随机化)在整个入组过程中都能保证平衡;**stratified block**(分层分组随机化)额外还能平衡某个已知的预后因子；当干预是在组这一层级实施时,**cluster**(整群随机化)是必须采用的方式。详见 `references/randomization_and_blocking.md`。

### DOE 矩阵 —— `scripts/doe_designs.py`

```python
from doe_designs import (
    full_factorial, two_level_factorial, fractional_factorial,
    plackett_burman, central_composite, box_behnken, latin_hypercube,
)

# Factors as real-world (low, high) ranges -> design comes back in real units
factors = {"temp_C": (20, 60), "conc_mM": (1, 10), "pH": (6, 8)}

# Full 2^3: all main effects + all interactions (8 runs), run order randomized
design = two_level_factorial(factors, seed=42)

# Screen 7 factors cheaply (main effects only)
many = {f"factor_{i}": (0, 1) for i in range(7)}
design = plackett_burman(many, seed=42)

# Optimize over 2 factors with curvature (response-surface)
design = central_composite({"temp_C": (20, 60), "conc_mM": (1, 10)}, seed=42)

design.to_csv("experimental_runs.csv", index=False)
```

默认会随机化运行顺序，以避免因子与时间/漂移(仪器预热、试剂老化)相混杂。关于如何选择生成元、如何解读混叠结构(alias structure)以及如何选择分辨率，参见 `references/factorial_and_doe.md`。

---

## 会毁掉研究的错误

这些都是结构性问题——它们无法在分析阶段被修复，只能在设计阶段避免。

1. **伪重复(Pseudoreplication)**。 把对同一个实验单元的重复测量当作独立的重复样本:3 只小鼠、每只测 100 个细胞，对于施加在小鼠身上的任何处理来说，样本量是 n = 3(小鼠数),而不是 n = 300(细胞数)。重复样本必须处于处理被随机化的那个层级上。这一个错误就会使很大一部分已发表的实验作废。要在正确的层级上做随机化和重复；分析时要尊重这种嵌套结构(混合模型,mixed model)。详见 `references/design_types.md`。
2. **由干扰变量导致的混杂**。 星期一跑所有处理组样本、星期二跑所有对照组样本，会让处理效应与日期相混杂。要在你能想到的每一个干扰因子(批次、日期、孔板、操作人员、仪器、位置)上做随机化，或对其进行分组。
3. **没有随机化，或随机化被破坏**。 按便利性分配(先到的分到处理组)会让混杂因素趁虚而入。使用设有种子的分配方案并严格遵循。
4. **没有恰当的对照**。 没有一个同期进行的对照组(以及在相关情况下的赋形剂/假处理组和盲法),你就无法把处理效应与时间效应、安慰剂效应或操作效应区分开来。
5. **把批次效应误认为是生物学效应**。 尤其是在组学研究中，要以随机化/分组的顺序跨批次处理样本；绝不能让批次与条件对齐。
6. **孔板上的边缘/位置效应**。 蒸发和温度梯度会让孔板边缘的情况有所不同。要对样品位置做随机化或分组；不要把所有对照都放在第 1 列。
7. **在部分因子设计中忽视混叠**。 低分辨率的部分因子设计会把主效应和交互效应混叠在一起；在得出"某因子没有效应"这个结论之前，先弄清楚你的混叠结构。
8. **在没有曲率的情况下做优化**。 两水平因子设计无法探测到有曲率的响应；你会错过一个内部最优点。此时应使用响应曲面设计。

---

## 工作流程

1. **明确问题、实验单元和响应变量**。 什么被随机化了?测量的是什么?在哪个层级上才算真正独立的重复样本?这决定了后续的一切。
2. **列出干扰因子**(批次、日期、地点、操作员、位置)——计划对每一个都做分组、分层或随机化处理。
3. **用决策树和参考文档选定设计**。
4. **在正确的层级上决定重复次数**(并从 **statistical-power** 技能获取所选设计对应的样本量 n)。
5. **用 `randomization.py` / `doe_designs.py` 生成布局方案，并设置随机种子。**
6. **随机化运行/处理顺序，以及孔板/批次位置**。
7. **记录文档**:设计方案、种子和排程表(如可能，做预注册),这样分析才具有确证性(confirmatory),布局也可被审计。
8. **让分析方式与设计相匹配**——分组、分层、整群和嵌套结构都必须在模型中体现出来(交给 **statistical-analysis** / **statsmodels** 处理)。

---

## 资源

### 脚本
- `scripts/randomization.py` —— 带随机种子的分配方案:`simple_randomization`、`block_randomization`、`stratified_block_randomization`、`cluster_randomization`、`assign_factorial_runs`、`arm_balance`。
- `scripts/doe_designs.py` —— 按真实单位表示的 DOE 矩阵:`full_factorial`、`two_level_factorial`、`fractional_factorial`、`plackett_burman`、`central_composite`、`box_behnken`、`latin_hypercube`。

### 参考文档
- `references/randomization_and_blocking.md` —— 随机化方法、分组、分层、对照、盲法、批次/孔板布局。
- `references/factorial_and_doe.md` —— 因子设计与部分因子设计、分辨率与混叠、筛选，以及响应曲面方法学。
- `references/design_types.md` —— 完全随机化、随机分组、交叉、重复测量、裂区、拉丁方、整群和嵌套设计；深入探讨伪重复问题。
- `references/sequential_and_adaptive.md` —— 组序贯设计、alpha 消耗(alpha spending)、中期停止规则，以及适应性样本量重新估计。

### 相关技能
- **statistical-power** —— 针对你所选设计所需的样本量/统计功效。
- **statistical-analysis** —— 数据采集完成后的分析运行与报告。
- **statsmodels** / **pymc** —— 拟合该设计所隐含的模型。

### 关键参考文献
- Fisher, R. A. (1935). *The Design of Experiments*.
- Montgomery, D. C. (2019). *Design and Analysis of Experiments* (10th ed.).
- Hurlbert, S. H. (1984). Pseudoreplication and the design of ecological field experiments. *Ecological Monographs*, 54(2), 187–211.
- Lazic, S. E. (2016). *Experimental Design for Laboratory Biologists*.
