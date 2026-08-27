# 分析方法验证(Analytical Method Validation)

## 何时使用

任何时候，只要问题是"某个分析规程是否适合其预期用途":设计验证研究、评估验证数据、核查药典规程(compendial procedure)、将规程转移到另一个实验室或仪器，或在报告中为上述任一事项进行论证说明。

## 两条准则

**1. 在设计任何内容之前，先确定适用的框架**。 同一个检测方法在 ICH Q2(R2)、USP <1225>、ICH M10、CLSI EP 和 ISO/IEC 17025 下的验证方式各不相同。它们在要求哪些特性、研究如何编排，乃至是否给出数值判定标准这些方面都存在差异。把它们混在一起，得到的方案哪一个都不满足。

**2. 在采集数据之前先确定判定标准**。 看到结果之后才选定的标准不是判定标准，事后再决定属于审计中会被记录的标准问题。ICH Q2(R2) 有意几乎不提供数值标准——它们必须来自质量标准(specification)、分析目标概况(analytical target profile,ICH Q14 第 3 节)或开发数据。ICH M10 是例外:它给出了明确的数字，且色谱类检测方法与配体结合检测方法(ligand binding assay)之间的数字并不相同。

## 范围

本技能负责规划研究、正确计算统计量，以及整理文档结构。它**不会**判定某个规程已通过验证、放行某批次、接受或拒绝某次运行、结案某项调查，也不能替代分析人员、技术审核人员、质量部门或监管机构。每个脚本只负责报告，任何一个都不下结论。

## 版权边界

ICH 指南是公开发布的，并许可在注明来源的前提下重用，因此其要求被直接编码进了本技能中。**USP 通用章节、CLSI EP 文档和 ISO 标准是受版权保护且需付费获取的**。 对于这些内容，本技能只提供编号、适用范围以及获取授权副本的途径——绝不提供正文内容，也绝不臆造阈值。不要让代理去检索、转录或重构这些文档的内容。如果某个数字很重要而它出自一份付费文档，请从授权副本中读取。

## 框架

```bash
cd skills/analytical-method-validation/scripts
python3 plan_validation.py --list-frameworks
```

| 键 | 管辖范围 | 是否提供数值标准 |
| --- | --- | --- |
| `ich-q2r2` | 原料药和制剂的放行与稳定性检测 | 几乎没有——需自行推导 |
| `ich-m10` | 生物分析浓度测定(PK、TK、BE) | 有，且按检测模式不同而不同 |
| `usp-1220` | 药典规程生命周期，三个阶段 | 付费获取 |
| `usp-1225` / `usp-1226` | 药典规程的验证/核查 | 付费获取 |
| `clsi` | 临床实验室测量规程(EP 系列) | 付费获取 |
| `iso-17025` | 认可体系下实验室自建及修改方法 | 无——"在必要范围内" |

**Q2(R2) 于 2023 年 11 月取代了 Q2(R1),并重新组织了特性结构**。 范围(Range)现在是父级特性(3.2 节),包含*响应*(线性)和*较低范围限值的验证*(DL/QL)。准确度和精密度是 3.3 节，可以合并针对单一标准进行评价。稳健性(Robustness)被视为开发活动，并交叉引用 ICH Q14。多变量规程被明确论及(2.5 节和 3.2.2.3 节),附录 2 新增了 Q2(R1) 从未涵盖的技术示例——定量 ¹H-NMR、NIR、定量 LC/MS、qPCR、生物学检测和粒度分析。一份按 Q2(R1) 结构组织的方案——线性、范围、准确度、精密度、专属性、LOD、LOQ、稳健性的平铺清单——已经过时。另外还要注意 2023 年 11 月 30 日对表 5 及表 6-11 的勘误。

## 脚本

```bash
cd skills/analytical-method-validation/scripts
```

| 脚本 | 回答的问题 |
| --- | --- |
| `plan_validation.py` | 适用哪个框架、需要哪些特性、研究如何编排、方案如何撰写? |
| `check_response.py` | 校准模型在整个范围内是否真正成立? |
| `check_accuracy_precision.py` | 回收率是多少，有多少变异性来自天间差异? |
| `check_detection_limits.py` | 按各种允许的方法计算,DL 和 QL 各是多少，能否满足报告阈值的要求? |
| `check_bioanalytical_run.py` | 这次运行是否满足该检测模式下的 ICH M10 要求? |
| `compare_methods.py` | 在预先设定的界值下，两个规程是否等效? |

所有脚本都支持 `--format table|tsv|json`。溯源信息、指南引用和注意事项输出到 stderr;数据输出到 stdout,因此 `> out.tsv` 可以把二者分开。退出码为 `0` 表示无发现事项,`1` 表示提出了发现事项,`2` 表示输入有误——因此任何一个脚本都可以用来作为工作流的门禁。

## 工作流程

### 1. 确定框架与所需特性

```bash
python3 plan_validation.py --framework ich-q2r2 --attribute assay --technique hplc --range-use assay
```

Q2(R2) 表 1 是根据*被测属性*而不是技术手段来决定要求什么。对于含量测定(assay):专属性、响应、准确度、重复性(repeatability)、中间精密度(intermediate precision)。对于限度试验:仅需专属性和 DL。对于鉴别试验:仅需专属性。可接受的属性包括 `assay`、`impurity`(定量)、`impurity-limit` 和 `identity`。

可报告范围来自质量标准。Q2(R2) 表 2 给出了实例——含量测定为标示含量的 80-120%,含量均匀度为 70-130%,杂质的报告阈值到质量标准的 120%。

### 2. 生成方案并填写判定标准

```bash
python3 plan_validation.py --framework ich-q2r2 --attribute impurity --protocol > protocol.md
```

每一个方括号字段都是一项需要在采集数据*之前*做出并记录下来的决定。方案骨架有意不预填 Q2(R2) 工作的判定标准，因为没有站得住脚的默认值。

### 3. 评估响应

```bash
python3 check_response.py -i calibration.csv --max-back-calc-error 2
```

输入为 `level,response`,每次进样一行；同一水平的重复行即为复测，提供这些复测数据正是线性检验得以进行的前提。

来自一条曲线的真实输出——决定系数会让它蒙混过关:

```
statistic                           value
distinct levels                     5
slope                               166.6000
intercept                           2495.0000
intercept CI includes 0             no
coefficient of determination (r2)   0.9830
lack-of-fit F                       469.5294
lack-of-fit p                       1.5139e-06
runs test p                         0.0492

level     n  mean_response  mean_back_calculated  relative_error_pct
50.0000   2  10075.0000     45.4982               -9.0036
75.0000   2  15150.0000     75.9604               1.2805
100.0000  2  20050.0000     105.3721              5.3721
125.0000  2  24050.0000     129.3818              3.5054
150.0000  2  26450.0000     143.7875              -4.1417
```

r² = 0.983,而这个模型根本不能用:范围下限处反算误差达 -9.0%,失拟(lack-of-fit)F 检验 p = 1.5 × 10⁻⁶,残差符号非随机。**r² 不是线性的证据**——它随范围增大而升高，对曲率几乎不敏感。真正的证据是相对纯误差(pure error)的失拟 F 检验和残差模式，这正是为什么 Q2(R2) 3.2.2.1 要求分析各点相对于直线的偏差，而不是仅凭一个相关系数。

对于宽范围曲线，加上 `--weight 1/x2`。当范围上三分之一区段的残差方差超过下三分之一区段的 10 倍以上时，脚本会标记出异方差性，因为不加权的拟合恰恰会使报告阈值所在的低端出现偏差。

### 4. 评估准确度和精密度

```bash
python3 check_accuracy_precision.py -i ap.csv --accuracy-limit 2 --rsd-limit 1.0 --design-check assay
```

输入为 `level,measured,group`,其中 `group` 是中间精密度因子——天、分析人员或仪器。

```
level  component                       sd      rsd_pct  df      ci90_low_sd  ci90_high_sd
100    repeatability (within group)    0.0707  0.0707   3       0.0438       0.2065
100    between-group                   1.6515  1.6515   2       n/a          n/a
100    intermediate precision (total)  1.6530  1.6530   2.0037  0.9554       7.2821
```

重复性 RSD 为 0.07%,看起来非常出色；而中间精密度是 1.65%,是前者的二十三倍，因为变异性全部来自天间差异。若把组内(within-day)数字当作该规程的精密度来报告，会把日常表现低估一个数量级以上。这正是为什么脚本拟合的是单因素随机效应模型，而不是简单地合并数据。

脚本为你处理了两个陷阱:

- **精密度是在每个水平内分别估计的，绝不跨水平合并**。 把 80/100/120% 的结果合并成一个标准差，会把范围本身变成表观上的不精密。脚本按水平分别报告，同时给出一个与水平无关的、以标称值百分比表示的视图。
- **`--require-ci-within-limit`** 强制要求整个置信区间都落在限值以内，而不只是均值。Q2(R2) 3.3.1.4 要求区间与判定标准*相容(compatible with)*;六次重复中均值勉强落在界内，并不能说明太多问题。

### 5. 确定 DL 和 QL,并加以确认

```bash
python3 check_detection_limits.py --calibration lowcal.csv --blanks blanks.csv \
    --confirm-ql 0.05 --confirm-data ql_check.csv --reporting-threshold 0.05
```

```
approach                                          sigma   slope      DL      QL
sd-and-slope (sigma = residual SD of regression)  7.2816  5033.3490  0.0048  0.0145
sd-and-slope (sigma = SD of y-intercept)          4.3303  5033.3490  0.0028  0.0086
sd-and-slope (sigma = SD of 8 blanks)             3.7702  5033.3490  0.0025  0.0075
```

同一份数据得出的 QL 估计值跨度达 1.9 倍，单纯是因为 σ 的选取不同。因此 Q2(R2) 3.2.3.5 要求同时报告限值**以及用于确定该限值的方法**,并要求用接近该限值的样品对估计限值加以确认。对于杂质规程,QL 必须等于或低于报告阈值。不假思索地套用 `3.3σ/slope`、只报告一个数字而不注明所用方法，以及从不进行确认——这是三个各自独立的发现事项。

### 6. ICH M10 下的生物分析运行

```bash
python3 check_bioanalytical_run.py --modality chromatographic --run run1.csv
python3 check_bioanalytical_run.py --modality lba --isr isr.csv
python3 check_bioanalytical_run.py --modality lba --criteria
```

`--modality` 是必填项且无默认值，因为判定标准确实不同:

| | 色谱法(Chromatographic) | 配体结合检测(Ligand binding assay) |
| --- | --- | --- |
| 校准容许限 | ±15%,LLOQ 处 ±20% | ±20%,LLOQ 和 ULOQ 处 ±25% |
| 准确度/精密度 | ±15% / ≤15% CV(LLOQ 处 ±20% / ≤20%) | ±20% / ≤20% CV(LLOQ 和 ULOQ 处 ±25% / ≤25%) |
| A&P 设计 | 4 个 QC 水平，每次运行 5 个复测,≥3 次运行跨 ≥2 天 | 5 个 QC 水平，每次运行 3 个复测,≥6 次运行跨 ≥2 天 |
| 总误差 | 无此判定标准 | ≤30%,LLOQ 和 ULOQ 处 ≤40% |
| ISR 一致性 | ≥2/3 复测落在 ±20% 以内 | ≥2/3 复测落在 ±30% 以内 |

把 ±15% 的色谱法数字套用到配体结合检测上，或者把 LBA 的总误差标准搬到色谱法方法中，这两种做法都很常见，也都是错的。

运行检查会强制执行一条容易被漏掉的分水平规则:*所有* QC 中至少 2/3 达标,**且**每个水平至少达到 50%。一次运行可能整体比例达标，但某个单一水平却完全不达标。

```
finding: QC level high: 0/2 within tolerance (0%); M10 requires at least 50% at each level
```

### 7. 转移与方法比较

```bash
python3 compare_methods.py -i paired.csv --margin 2 --relative --slope-tolerance 0.05
```

```
mean difference (%)                       1.4646
TOST margin                               2.0000
TOST p-value                              1.0528e-13
90% CI (TOST)                             1.44127 to 1.48797
equivalent at stated margin               yes
--- for contrast only ---
paired t-test p (NOT equivalence)         0.0000
OLS slope (biased here)                   1.0396
Deming slope                              1.0398
Passing-Bablok slope                      1.0351
```

本脚本要纠正的两个错误:

- **"p > 0.05,无显著差异，因此两种方法等效。"** 未能检测出差异并不是等效的证据，而在一个小规模转移数据集上，这样的结果几乎是必然的。TOST 检验的才是真正要问的假设——真实差异落在预先设定的界值以内。这里 t 检验说差异高度显著,*而* TOST 说两种方法在 ±2% 界值下等效；两者都对，但只有一个回答了真正的问题。
- **用普通最小二乘法(OLS)做方法比较**。 OLS 假设参照值不含误差，而在比较两个规程时这一假设并不成立，会使斜率向零偏移。Deming 回归(需给定误差方差比)和 Passing-Bablok 回归(非参数、抗离群值)才是恰当的回归方法，脚本会将它们与 OLS 并列报告以作对比。

脚本还会标记比例偏倚(proportional bias)——当差异随浓度呈趋势性变化时，无论单一均值偏倚及其一致性界限(limits of agreement)看起来多么紧凑，都是具有误导性的。

## 本技能旨在防止的问题

1. 在 Q2(R2) 取代 Q2(R1) 三年之后，仍按 ICH Q2(R1) 的结构进行验证。
2. 看到数据之后才写下的判定标准。
3. 把 r² 当作线性的证据来展示。
4. 把重复性当作该规程的精密度来报告，天间差异成分不可见。
5. 只给出一个 DL/QL 数字，不注明所用方法，也未加以确认。
6. 把色谱法的 M10 判定标准套用到配体结合检测上，或反之。
7. 在方法转移中把 t 检验的不显著结果当作等效性来呈现。

## 参考资料

- `references/framework-selection.md` —— 适用哪个框架，以及决定这一点的问题
- `references/ich-q2r2.md` —— 结构、表 1 和表 2、各特性的推荐数据
- `references/ich-m10-bioanalytical.md` —— 色谱法与 LBA 的完整判定标准并列对照
- `references/compendial-and-clsi.md` —— USP、CLSI 和 ISO 的编号、适用范围，以及如何引用它们
- `references/statistics.md` —— 各统计方法，为何使用它们，以及常见错误
- `references/source-ledger.md` —— 本技能中每一项论断的溯源信息与调研日期

## 资产

- `assets/validation-protocol-template.md` —— 方案结构，判定标准前置写明
- `assets/validation-report-template.md` —— 报告结构，含原始数据可追溯性
