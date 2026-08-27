# 不确定度与单位（Uncertainty and units）

## 适用范围

只要计算涉及物理单位，或者报告的数字需要不确定度，就应使用本技能。具体来说：

- 在单位之间转换，包括需要物理语境的转换
  （波长到光子能量、质量到物质的量、能量到温度）；
- 通过测量模型传播不确定度，无论输入之间是否存在相关性；
- 根据校准证书、规格说明和重复性数据构建 GUM 不确定度预算；
- 选择包含因子（coverage factor），并判断 `k = 2` 是否站得住脚；
- 对结果进行舍入并写出，使读者明白 `±` 代表什么；
- 从曲线拟合中提取参数不确定度而不丢弃相关性；
- 审查现有分析代码，找出隐藏的单位与不确定度缺陷；
- 检查一个量纲一致的答案是否也物理上可能——量级、无量纲群，
  以及它所暗示的所处状态区间（regime）。

本技能涵盖计量学以及实现它的两个库。它不涵盖统计推断、模型选择或研究设计——
参见 `statistical-analysis`、`statistical-power` 和 `experimental-design`。

## 当前发行版与安装

于 2026-07-26 核实：

- **pint 0.25.3**，发布于 2026-03-19；需要 Python 3.11+。
- **uncertainties 3.2.3**，发布于 2025-04-21；需要 Python 3.8+。
- **NumPy 2.5.1** 与 **SciPy 1.18.0**；两者都需要 Python 3.12+。
- SciPy 1.18.0 中的 `scipy.constants` 使用的是 **CODATA 2022**。SciPy 1.11 及更早版本
  使用的是 CODATA 2018，两者之间若干推荐值存在差异。

```bash
uv venv --python 3.13
source .venv/bin/activate
uv pip install "pint==0.25.3" "uncertainties==3.2.3" "numpy==2.5.1" "scipy==1.18.0"
```

`pint-pandas` 和 `pint-xarray` 分别为列（column）和数组添加了带单位感知的能力，
需要单独安装。

## 不可协商的工作流

1. **在输入处附加单位，只在输出处剥离**。 在函数边界用 `ureg.wraps` 或
   `m_as("unit")` 做转换，绝不在计算中途转换。
2. **在计算任何东西之前显式写出测量模型**，包括那些估计值为零的修正项。
   模型中遗漏的一项修正，会使其不确定度也从预算中遗漏。
3. **给每个输入四样东西**：一个估计值、一个标准不确定度、这个不确定度所来自的
   分布，以及它的自由度。
4. **用正确的除数转换 B 类不确定度陈述**。 证书上的扩展不确定度除以其声明的
   `k`；矩形限值除以 `sqrt(3)`。
5. **在合并之前先识别相关性**。 针对同一标准进行校准、在同一仪器上测量、
   或来自同一次拟合的输入是相关的。
6. **计算灵敏度系数**，从 `c_i * u(x_i)` 而不是原始不确定度中读出预算。
7. **检查线性化是否成立**。 在 GUM 框架旁并行运行蒙特卡洛，并应用
   JCGM 101 第 8 条的比较测试。当该测试失败时，报告蒙特卡洛结果。
8. **根据有效自由度而非习惯来选择 `k`。**
9. **先对不确定度舍入，再把数值舍入到同一小数位**。
10. **说明 `±` 究竟是什么**——标准不确定度还是扩展不确定度，附带 `k`、
    包含概率以及所用方法。
11. **在报告之前对量级做合理性核查**。 一个量纲一致的结果仍可能是不可能的。
    将其与已知尺度或无量纲群做对比，并确认你所依赖的每一条假设在该状态区间
    下依然成立。

## 本技能要防止的那些失败

以下每一段都能无错误运行，并产出一个看似合理的数字。

### 在未知尺度上被剥离的单位

```python
length = (12.7 * ureg.mm).magnitude          # 12.7 -- 什么的 12.7？
length = (12.7 * ureg.mm).m_as("m")          # 明确说明为 0.0127 米
```

`.magnitude` 返回的是该量当时所携带的任何数值。每次提取时都要在提取点
明确指出单位。

### 偏移温度算术

```python
Q(20, "degC") + Q(5, "degC")     # OffsetUnitCalculusError -- 正确地被拒绝
Q(20, "degC") + Q(5, "delta_degC")   # 25 degree_Celsius
Q(25, "degC") - Q(20, "degC")        # 5 delta_degree_Celsius
```

摄氏度和华氏度是区间标度（interval scale）。温度上的不确定度始终是一个差值，
应归入 `delta_` 单位：把 `20 ± 0.5 degC` 转换成华氏度得到
`68 degF ± 0.9 delta_degF`，一行代码里做了两种不同的转换。

### 相加即相乘的对数单位

```python
Q(10, "dBm") + Q(10, "dBm")   # 0.0001 kilogram**2 * meter**4 / second**6
```

那是 10 mW × 10 mW，既不是 20 mW，也不是 13 dBm。程序不会抛出任何错误。
在做任何算术运算之前，先转换成线性单位。

### 被往返转换摧毁的相关性

```python
x = ufloat(1.0, 0.1)
x - x                                     # 0.0+/-0
x - ufloat(x.nominal_value, x.std_dev)    # 0.00+/-0.14
```

从标称值和标准差重新构造一个变量，会创建出一个独立变量。任何经过一对
浮点数的序列化过程也会如此。要重建相关的一组变量，应使用
`correlated_values(values, covariance_matrix)`。

### 被悄悄重新缩放的协方差矩阵

```python
popt, pcov = curve_fit(f, x, y, sigma=sigma)                        # 默认
popt, pcov = curve_fit(f, x, y, sigma=sigma, absolute_sigma=True)
```

默认情况下会用约化卡方（reduced chi-square）对 `pcov` 做重新缩放，使得参数
不确定度吸收了拟合优度，其结果与完全不传 `sigma` 时相同。在一次合成的直线
拟合中，两者分别给出 `[0.0364, 0.2154]` 和 `[0.0477, 0.2820]`——相差 31%。
每当 `sigma` 中承载的是真实的标准不确定度时，都应传入
`absolute_sigma=True`。

### 从未被检验过的线性化

对于 `y = x²`，当 `x = 1.0 ± 0.5` 时，GUM 框架给出 `y = 1.0`、`u_c = 1.0`，
以及一个 95% 区间 `[-0.96, 2.96]`——对一个平方量来说，这个区间大部分是负值。
蒙特卡洛给出的均值为 1.25，`u_c = 1.06`，最短 95% 区间为 `[0, 3.32]`。
任何线性传播库都不会告诉你发生了这种情况。

## 内置本地 CLI 工具

所有辅助工具均离线运行，拒绝 URL 和符号链接，对输入做边界限制，以私有
权限原子性地写出结果，并且在没有 `--force` 时拒绝覆盖已有文件。

```bash
python skills/uncertainty-and-units/scripts/propagate_uncertainty.py --help
python skills/uncertainty-and-units/scripts/uncertainty_budget.py --help
python skills/uncertainty-and-units/scripts/format_result.py --help
python skills/uncertainty-and-units/scripts/convert_units.py --help
python skills/uncertainty-and-units/scripts/audit_units.py --help
python skills/uncertainty-and-units/scripts/check_plausibility.py --help
```

### propagate_uncertainty.py

在同一个模型上运行两种传播方法，并应用 JCGM 101 第 8 条的验证测试。

```bash
python skills/uncertainty-and-units/scripts/propagate_uncertainty.py \
  --expression "m / (pi * (d / 2) ** 2 * h)" \
  --variable "m=250.0,0.05" \
  --variable "d=20.0,0.02,rectangular" \
  --variable "h=40.0,0.05,rectangular" \
  --measurand density --unit "g/cm3" --format markdown
```

每个 `--variable` 的形式为 `name=value,standard_uncertainty[,distribution[,dof]]`，
其中 distribution（分布）取值为 `normal`、`rectangular`、`triangular`、
`arcsine` 或 `exact`，仅用于控制蒙特卡洛采样。相关性通过
`--correlation "a,b=0.9"` 传入。若模型需要长期保存，可用一个 JSON
的 `--spec` 文件保存同样的模型。

表达式会被解析成抽象语法树，并通过对 `+ - * / **` 及一组固定函数列表
的显式遍历来化简。它绝不会被编译或执行。

报告给出估计值、`u_c`、灵敏度系数、以百分比表示的预算、有效自由度、
`k`、`U`、两种蒙特卡洛包含区间，以及关于是否可以报告线性化结果的
结论。

### uncertainty_budget.py

以证书和数据表通常陈述不确定度分量的方式，将它们组合起来。

```bash
python skills/uncertainty-and-units/scripts/uncertainty_budget.py --template > budget.json
python skills/uncertainty-and-units/scripts/uncertainty_budget.py --spec budget.json --format markdown
```

每个分量指定一个 `distribution`，用以确定其除数——`expanded` 除以其
`coverage_factor`，`rectangular` 除以 `sqrt(3)`，`triangular` 除以
`sqrt(6)`，`arcsine` 除以 `sqrt(2)`，`normal` 除以 1——并可选携带
`sensitivity`、`dof` 和 `relative: true`。该工具计算 `u_c`、
Welch-Satterthwaite 有效自由度、由 t 分布得出的 `k`，以及 `U`，
并在以下情况给出警告：A 类分量没有自由度、`nu_eff` 小到使 `k = 2`
不成立、某一分量占主导地位，以及声明为 `normal` 的 B 类分量很可能是
一个未做除法的扩展不确定度。

### format_result.py

```bash
python skills/uncertainty-and-units/scripts/format_result.py \
  --value 12.34567 --uncertainty 0.02345 --unit mm \
  --coverage-factor 2.26 --coverage-probability 0.95
```

返回 `12.346 ± 0.023 mm`、`12.346(23) mm`、科学计数法与 LaTeX 形式，
以及必须随数字一起出现的那句说明。当被要求对以 1 或 2 开头的不确定度
只保留一位有效数字时，以及当不确定度超过估计值本身时，都会给出警告。

### convert_units.py

```bash
python skills/uncertainty-and-units/scripts/convert_units.py \
  --value 532 --unit nm --to eV --context spectroscopy --uncertainty 0.5

python skills/uncertainty-and-units/scripts/convert_units.py \
  --value 1.0 --unit g --to mol --context chemistry --context-parameter "mw=180.156 g/mol"
```

通过转换的局部导数把不确定度带过转换过程，这一点很重要，因为语境
（context）转换是倒数关系而非正比关系。当某个转换需要语境时，会在
错误信息中指明语境名称，并对偏移单位和对数单位加以标记。
`--list-contexts` 会显示该注册表中定义的全部内容。

### audit_units.py

对现有分析代码做静态审查。只解析，绝不导入或运行代码。

```bash
python skills/uncertainty-and-units/scripts/audit_units.py \
  --input analysis.py --format markdown --fail-on medium
```

| 规则 | 严重级别 | 检测内容 |
| --- | --- | --- |
| `UNIT001` | medium | 一个模块中出现第二个 `UnitRegistry`——跨注册表的 `ValueError` |
| `UNIT002` | medium | 存在偏移温度单位，却整个代码中没有任何 `delta_` 单位 |
| `UNIT003` | high | `.magnitude` 前面没有 `.to(...)` 或 `.m_as(...)` |
| `UNIT004` | medium | 对数单位，其 `+` 实际上是相乘 |
| `UNC001` | high | 使用 `curve_fit` 却没有 `absolute_sigma` |
| `UNC002` | medium | `np.std` / `np.var` 没有 `ddof` |
| `UNC003` | medium | 在使用了 `uncertainties` 的模块中出现 `math` 或 `numpy` 函数 |
| `UNC004` | high | 从 `.nominal_value` 和 `.std_dev` 重新构造出的 `ufloat` |
| `CONST001` | low | 一个字面量数值与某个 CODATA 常量相差在 0.1% 以内 |

当某条发现的严重级别达到 `--fail-on`（默认 `high`）时，退出状态为 1，
因此可以把它用作 pre-commit 或 CI 检查。

这些规则是启发式的，因此误报可以用一条指令注释来抑制——写在行尾以
覆盖本行，或单独一行以覆盖下一行：

```python
value = quantity.magnitude  # audit-units: ignore UNIT003 -- already converted upstream

# audit-units: ignore UNC003 -- the argument here is a plain float array
scaled = np.log10(counts)
```

`# audit-units: ignore-file CONST001` 会覆盖整个模块，不写规则名则会
抑制所有规则。抑制项会被计入报告而不是被隐藏，所以一个把所有检查都
静默掉的文件，报告中依然会如实说明这一点。

### check_plausibility.py

量纲一致不等于物理上可能。一个直径 2 米的细胞，和毛细管中雷诺数
4e7，二者都能通过每一项单位检查。这个工具把一组量与无量纲群、
特征尺度以及经过整理的量级范围做对比，并在给出数字之前先验证每个
公式的量纲。

```bash
python skills/uncertainty-and-units/scripts/check_plausibility.py \
  --quantity "density=1060 kg/m**3" --quantity "velocity=0.5 mm/s" \
  --quantity "length=8 um" --quantity "viscosity=3.5 mPa*s" \
  --group reynolds --format markdown
# Re = 0.001211 -- laminar (circular pipe, length = diameter)

python skills/uncertainty-and-units/scripts/check_plausibility.py \
  --quantity "diameter=2 m" --band "eukaryotic_cell_diameter=diameter"
# implausible: 4.3 decades outside the 5-100 um range
```

`--group` 计算 14 个无量纲群中的一个，并指出它把该系统置于哪个
状态区间；`--scale` 计算一个特征尺度，例如扩散时间、德拜长度
（Debye length）或斯托克斯沉降速度；`--band` 把给定的量与一个观测
范围做比较。`--list` 会打印整份目录，以及每个公式所需要的输入。

物理常量（`k_B`、`N_A`、`R_gas`、`g_earth` 等）对每个公式都是无需
额外提供、直接可用的，并且是在运行时从 `scipy.constants` 读取，
而非写成字面量，因此会跟随 SciPy 所附带的 CODATA 版本一起更新。

量纲检查才是关键所在。如果传入一个运动粘度（kinematic viscosity），
而公式需要的是动力粘度（dynamic viscosity）——二者都叫「粘度」，
都为水这种物质列有数值，却相差一个 ρ 因子——它会在计算出任何数字
之前就被拒绝：

```
error: viscosity must have dimensionality [mass] / ([length] * [time]),
       but m²/s is [length] ** 2 / [time]
```

当结论的严重程度达到 `--fail-on`（默认为 `implausible`；处于某个
范围一个数量级以内的值为 `questionable`）时，退出状态为 1。这些阈值
是有一定弹性的约定，并假定几何形状符合其相关公式最初拟合时所用的
条件——每种情形下应使用的特征长度参见
`references/plausibility-scales.md`。

## 选择传播方法

| 情形 | 方法 |
| --- | --- |
| 线性或近似线性模型，输入近似正态，自由度较大 | 仅用 GUM 框架 |
| 在某个输入的 ±2u 范围内存在任何非线性 | 两种方法都跑，并应用第 8 条测试 |
| 任一输入的相对不确定度高于约 20% | 蒙特卡洛 |
| 存在占主导地位的矩形分布或其他非正态分量 | 蒙特卡洛 |
| 输出有下界（方差、浓度、平方量） | 蒙特卡洛 |
| 输出分布不对称 | 蒙特卡洛，取最短包含区间 |
| 输入相关 | 两种方法均可，但需提供协方差矩阵，而非仅提供各自的标准不确定度 |

一个以矩形贡献为主的模型，即使它完全是线性的，也会未能通过第 8 条
测试：该框架给出的 `k = 1.96` 对一个近似梯形的输出而言覆盖过宽。
估计值和 `u_c` 依然是正确的；只是区间宽度不对。

## 常量

绝不要凭记忆敲出一个常量。2019 年的国际单位制（SI）重新定义把 `c`、
`h`、`e`、`k` 和 `N_A` 定为精确值，因此它们的相对标准不确定度为零；
其余所有常量都是测量值，会在不同的 CODATA 发行版之间变动。

```python
import scipy.constants as constants

constants.value("electron mass")        # 9.1093837139e-31
constants.unit("electron mass")         # kg
constants.precision("electron mass")    # 3.07e-10, relative standard uncertainty
constants.precision("Planck constant")  # 0.0, exact by definition
```

`precision` 返回的是*相对*标准不确定度；乘以数值本身才能得到绝对
不确定度。

## 参考文件

- `references/gum-methodology.md`——A 类与 B 类评估、各分布对应的除数、
  传播定律、Welch-Satterthwaite 方法、该框架何时失效、蒙特卡洛流程，
  以及第 8 条验证测试。
- `references/pint-recipes.md`——注册表、偏移单位与对数单位、语境
  （context）、用 `wraps` 和 `check` 做边界强制、与 NumPy 的互操作、
  自定义单位、格式化。
- `references/uncertainties-recipes.md`——变量身份与相关性、
  `correlated_values`、`umath` 与 `unumpy`、格式规范、拟合协方差
  矩阵，以及该包的局限。
- `references/domain-conversions.md`——能量阶梯、光谱学、浓度、压强、
  辐射与磁学、质谱、对数量，以及那些共享量纲却不共享含义的量对。
- `references/reporting-rules.md`——舍入、记法、必须随结果一起出现的
  那句说明、图中标准差（SD）与标准误（SEM）与置信区间（CI）的区分、
  未检出值（non-detects），以及符合性判定规则。
- `references/plausibility-scales.md`——如何选择特征长度、每个
  无量纲群及其所约束的建模假设、特征尺度、观测到的量级范围及其出处，
  以及每一条阈值的注意事项。

## 有日期标注的资料来源

于 2026-07-26 核实：

- [JCGM 100:2008, Evaluation of measurement data — Guide to the expression of
  uncertainty in measurement](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf)
- [JCGM 101:2008, Supplement 1 — Propagation of distributions using a Monte Carlo
  method](https://www.bipm.org/documents/20126/2071204/JCGM_101_2008_E.pdf)
- [NIST Technical Note 1297](https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote1297.pdf)
- [CODATA internationally recommended values](https://physics.nist.gov/cuu/Constants/)
- [Pint on PyPI](https://pypi.org/project/Pint/) —— 0.25.3，发布于 2026-03-19。
- [Pint documentation](https://pint.readthedocs.io/en/stable/)，包括
  [non-multiplicative units](https://pint.readthedocs.io/en/stable/user/nonmult.html)
  与 [contexts](https://pint.readthedocs.io/en/stable/user/contexts.html)。
- [uncertainties on PyPI](https://pypi.org/project/uncertainties/) —— 3.2.3，发布于
  2025-04-21。
- [uncertainties documentation](https://uncertainties.readthedocs.io/en/latest/)
- [scipy.constants reference](https://docs.scipy.org/doc/scipy/reference/constants.html)
