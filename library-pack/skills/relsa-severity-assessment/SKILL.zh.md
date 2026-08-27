# RELSA 严重程度评估与人道终点预测

## 概述

动物研究中的严重程度评估在法律上是强制性的，在科学上也是有实际分量的：
它驱动人道终点决策，而糟糕的福利监测会损害可重复性。
通常的做法是孤立地评估每一项指标——这里看体重减轻，那里看临床评分——
这使得很难说清一只动物实际上状况有多糟。

本技能实现了两套已发表的、用于解决这一问题的流程：

- **RELSA**（Talbot 等，2022）将多项结局指标合并为每只动物每个时间点的一个评分，
  该评分是*相对于一个已知负担程度的参考集*表达的。RELSA = 0 表示基线；
  RELSA = 1 表示该动物已达到参考集的最大偏差。
- **foRcast**（Lutscher 等，2026）对单只动物的 RELSA 轨迹拟合 ARIMA 模型，
  并以 95% 预测区间预测下一个评分，从而可以在动物真正走到人道终点之前
  识别出正朝该方向发展的动物。在 RELSA 量表上进行核密度估计，
  可为解释提供候选的*关注*区和*危险*区。

其要点在于**优化（refinement）**：更早关注高风险动物，同时避免安乐死那些本可以恢复的动物。
这两套流程都是严重程度评估的辅助工具，而不是决策规则——参见
[边界（Boundaries）](#边界报告时须说明这些)。

## 何时使用本技能

- 将体重减轻、体温、临床评分、生物标志物或遥测数据合并为单一的每只动物严重程度评分
- 判断队列中哪些动物有达到人道终点的风险，或预测未来某个时间点的严重程度评分
- 在一个共同的相对量表上比较不同处理组、干预措施或动物模型之间的严重程度
- 根据数据在严重程度量表上定义阈值或区间
- 撰写动物福利报告、3Rs/优化分析，或欧盟指令 2010/63/EU 申请中的严重程度评估部分

若要对非严重程度评分的时间序列做一般性预测，请使用
**timesfm-forecasting** 或 **statsmodels**。研究设计和样本量方面，请使用
**experimental-design** 和 **statistical-power**。

## 安装

```bash
uv pip install "numpy>=1.26" "pandas>=2.0" "scipy>=1.11" "statsmodels>=0.14" matplotlib
```

`relsa_score.py` 和 `kde_thresholds.py` 只需要 numpy/pandas/scipy；statsmodels 仅在预测时需要，
matplotlib 仅在绘图时需要。

## 数据格式

CSV 中每行对应一只动物在一个时间点的记录：

| id | treatment | condition | day | temp | weight | score | il6 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M01 | treated | endpoint | -1 | 37.15 | 25.17 | 0 | 35.1 |
| M01 | treated | endpoint | 0 | 37.26 | 25.25 | 0 | 39.5 |
| M01 | treated | endpoint | 1 | 35.83 | 23.12 | 4 | 162.0 |

- `id` 和一个时间列（`day`、`time`、`hour` 等）是必需的；`treatment` 和 `condition`
  是可选标签，用于分组以及选择参考集。
- 时间单位可以是天、小时或分钟——只需保证同一只动物内单调递增即可。RELSA 惯例
  将基线时间点编码为 `-1`。
- **每只动物每个时间点一行**。 先将每小时的遥测数据平均为每个区间一个值
  （已发表模型对心率、心率变异性和体温取平均，对活动量取总和）。
- 缺失的测量值留空。它们会从评分中被剔除，而不是被插补——将缺失值当作
  "无偏差"处理会使严重程度被系统性低估。

`assets/example_cohort.csv` 是一个小型的合成队列（6 只小鼠，9 天，包含体温、
体重、0–8 的临床评分，以及一个类似 IL-6 的生物标志物），下面每条命令都会用到它，
因此每条命令都可以按原样运行。

## 决定结果的四项抉择

必须明确做出这些抉择，并写入方法学部分。没有其他任何一点比这四项更重要。

**1. 方向性——哪些变量在病情恶化时会上升**？ 默认是下降（体重、活动量、
摄食量、掘穴行为、转轮运动）。会*上升*的变量必须声明为 `--turned`：
临床评分、炎症生物标志物、发热、心动过速。若搞错了这一点，该变量将悄无声息地
不产生任何贡献，因为"错误"方向上的偏差会被截断为零。体温取决于具体模型——
在脓毒症和内毒素血症模型中它*下降*，在发热模型中它*上升*。数据本身无法帮你
确定这一点：在已发表的脓毒症模型中，活动量合理地会比低于基线更多地高于基线，
因此只有一个从未按声明方向变化过的变量才能被检测出来，
`build_reference()` 会针对这种情况发出警告。

**2. 参考集——相对于什么**？ 没有参考集，RELSA 评分毫无意义。使用你的模型中
假定承受最大负担的那组（已发表研究使用最高剂量组或到达终点的处理组）。
参考过于温和会把每个评分都推到 1 以上；参考过于严重则会把一切压缩向 0。
用 `--save-reference` 保存它，并用 `--load-reference` 在后续队列中复用，
以保持量表一致。

**3. 基线为零的评分**。 健康动物的临床评分为 0，无法进行比率归一化——
`0/0` 是未定义的。改用 `--score-scale score=8` 来映射该评分的量表
（健康 → 100%，最差 → 200%），这同时也会将其标记为已翻转（turned）。
这种映射是一个建模选择，代表一个评分点相对于体重百分之一的分量；
应予以说明。另一种方案是将该评分排除在 RELSA 之外，将其作为独立的终点标准使用。

**4. 哪些变量是全程测量的**。 由于评分是对当时可用的所有变量取平均，
一个在轨迹中途出现或消失的变量会自行影响评分。在已发表的脓毒症数据中，
加入仅在安乐死当天记录的体重，会使该动物的终点评分从 0.93 降至 0.83，
而这没有任何生物学原因。`relsa_scores()` 会在成分发生变化时发出警告；
请只对全程都存在的变量进行评分。

## 工作流程

### 第一步——计算 RELSA 评分

```bash
python scripts/relsa_score.py assets/example_cohort.csv \
    --variables weight,temp,score,il6 \
    --normalize weight,temp,il6 \
    --turned il6 \
    --score-scale score=8 \
    --baseline-time -1 \
    --reference-group condition=endpoint \
    --save-reference reference.json \
    --out relsa_scores.csv
```

参考模型会被回显出来，以便量表可审计：

```
reference model: assets/example_cohort.csv [condition=endpoint]
  animals=2  rows=18  baseline_time=-1.0
  variable      turned   max reached   max delta
  weight            no         82.40       17.60
  temp              no         92.79        7.21
  score            yes        187.50       87.50
  il6              yes        797.72      697.72
```

`relsa_scores.csv` 中每个变量的权重会与评分一起给出，这正是使评分可解释的原因——
这里可以看到 M01 恶化直至终点，M03 在第 3 天达到峰值随后恢复：

```
 id  time  weight  temp  score  il6  n_vars  relsa
M01     1    0.46  0.49   0.57 0.52       4   0.51
M01     3    0.84  0.76   1.00 0.89       4   0.88
M01     5    1.00  1.00   1.00 1.00       4   1.00
M03     3    0.56  0.44   0.57 0.54       4   0.53
M03     5    0.35  0.26   0.43 0.32       4   0.35
M03     7    0.12  0.06   0.14 0.11       4   0.11
```

权重为 1.00 表示该变量达到了参考最大值；`n_vars` 表示该时间点有多少个变量
进入了该评分。

当需要操作对象时，也可以用 Python 完成同样的事情：

```python
import sys; sys.path.insert(0, "scripts")
from _common import read_relsa_table, score_to_percent
from relsa_score import prepare, build_reference, relsa_scores

frame = read_relsa_table("assets/example_cohort.csv")
frame["score"] = score_to_percent(frame["score"], max_score=8)   # 0-8 clinical score
VARS, TURNED = ["weight", "temp", "score", "il6"], ["score", "il6"]

prepared  = prepare(frame, normalize=["weight", "temp", "il6"], baseline_time=-1)
reference = build_reference(prepared[prepared.condition == "endpoint"],
                           variables=VARS, turned=TURNED, baseline_time=-1,
                           label="endpoint-reaching animals")
scores    = relsa_scores(prepared, reference)
```

### 第二步——预测终点

在终点*前一个*时间点为止的全部数据上训练，预测终点处的评分，并对该预测进行打分：

```bash
python scripts/forecast_relsa.py relsa_scores.csv \
    --animals M01,M02 --endpoints M01=5 --endpoints M02=6 \
    --group-col condition --plot-dir figs --endpoint-line 1.0
```

```
 id  time  predicted    lower    upper        model  actual
M01   5.0   0.932585 0.670443 1.194728 ARIMA(1,1,0)    1.00
M02   6.0   0.955696 0.748309 1.163084 ARIMA(1,1,0)    0.94

   group             id        model  n   rmse  picp  mpiw
endpoint            M01 ARIMA(1,1,0)  1 0.0674 100.0 0.524
endpoint            M02 ARIMA(1,1,0)  1 0.0157 100.0 0.415
endpoint -- endpoint --               2 0.0489 100.0 0.470
                OVERALL               2 0.0489 100.0 0.470
```

请将这三项指标一并报告。**RMSE** 是点预测精度，**PICP** 是实际值落在区间内的百分比，
**MPIW** 是以 RELSA 单位表示的平均区间宽度——一个模型可以通过把区间做得极宽、
以至于毫无信息量的方式使 PICP 达到 100%，论文中胰腺癌那一行数据正是如此
（PICP 100%，MPIW 7.35，即 RELSA 量程的 735%）。

如需实时监测，可改为在每个时间点都进行一步预测：

```bash
python scripts/forecast_relsa.py relsa_scores.csv --mode rolling --animals M03
```

在信任一次预测之前，有两点需要了解：

- **插值默认是开启的**（`--interpolate-step 0.1`），因为每天一次测量对 ARIMA 而言
  过于稀疏。它以牺牲诚实的不确定性为代价，换来可用的模型选择和更窄的区间。
  当测量频率允许时，可将 `--interpolate-step` 设为 0。
- **ARIMA 无法预测悬崖式的骤变**。 它假设平稳性和线性，因此在终点前最后几小时内
  发生的骤然崩溃，无法从此前平滑的轨迹中被预测出来——这也是论文自身给出的失败案例。
  应基于区间的*上界*采取行动，绝不能让偏低的预测值凌驾于一只看起来状态不佳的动物之上。

### 第三步——用严重程度区间给评分赋予背景

```bash
python scripts/kde_thresholds.py relsa_scores.csv \
    --group treatment=treated --n-thresholds 2 --plot zones.png --json zones.json
```

```
KDE on 33 RELSA scores  (bandwidth = 0.1502)
  candidate thresholds (density minima): 0.703
  density modes: 0.264, 0.866
  normal    [0.000, 0.703)  n=25 (75.8%)
  danger    >= 0.703  n=8 (24.2%)
```

阈值是评分密度的*极小值*——即评分聚类之间稀疏的谷底。应包含到达终点的动物、
存活动物以及假手术组：这些区间旨在区分这些不同状态，因此三者都必须有所体现。

**在相信某个阈值之前，先检查带宽**。 在已发表的脓毒症数据上，本实现在 0.355 和 0.655 处
找到极小值（已发表数值为 0.337 和 0.643）——但带宽增大 10% 就会使这两个极小值
完全消失。请运行 `references/thresholds-and-zones.md` 中的扫描分析，并报告整个扫描结果，
而不是一对孤零零的数字。空的阈值列表也是一个合理的结果：说明评分只形成一个聚类，
不存在由数据驱动的切分点。

## 边界：报告时须说明这些

- **RELSA 是严重程度评估的辅助工具，而不是决定性参数**。 一只 RELSA 评分较低但表现出
  其他痛苦迹象的动物，仍必须相应地加以处理。这两套流程都不是经过验证的死亡预测因子。
- **KDE 区间不是监管意义上的严重程度分级**。 欧盟指令 2010/63/EU 的类别
  （无恢复、轻度、中度、重度）是通过另一套流程前瞻性地评定的。论文明确指出，
  其阈值"不应与监管性严重程度分级相混淆"，且不能直接转换为后者。
- **不同参考集或不同模型之间的评分不可比**。 RELSA 在构造上是相对的，
  而临床评分在各实验室之间也未统一。应始终连同参考集一起报告评分。
- **已发表的证据只是概念验证**：七个模型共 13 只动物，其中五行数据仅依赖一到两只动物。
  总体 RMSE 为 0.069、PICP 为 96%，均来自 13 次终点预测。
- **低估评分是更危险的错误**，因为它会降低警觉性，可能延误安乐死决策；
  而高估评分至多只会促使给予额外照护。

## 报告清单

只有说明了以下全部内容，一次严重程度分析才是可重复的：

1. 结局指标、其单位，以及它们的**方向性**（哪些被翻转，为什么）。
2. **基线**时间点或时间窗口，以及哪些变量做了归一化。
3. 对有序变量所应用的任何**评分映射**及其量表。
4. **参考集**：哪些动物、哪个组、多少只，以及为何假定它们承受最大负担。
5. 研究中实际应用的人道终点标准，与 RELSA 评分分开说明。
6. 对于预测：插值步长、每只动物所选定的 ARIMA 阶数，以及 RMSE、PICP*和* MPIW。
7. 对于阈值：带宽、评分数量，以及带宽敏感性扫描结果。
8. 软件版本，以及"阈值是特定于该模型的、并非监管分级"的声明。

## 常见陷阱

1. **方向性错误**——一个上升的变量若未列在 `--turned` 中，会精确地贡献零，
   且悄无声息，除非它从未下降过，否则无法给出警告。请自行检查参考模型表：
   对于下降型变量，`max reached` 应低于 100；对于翻转型变量应高于 100；
   `max delta` 应是该指标的合理量级。
2. **对百分比重复归一化**——`bwc [%]` 和已映射的评分本身已经处于百分比量表上；
   将它们传给 `--normalize` 会把它们压平。
3. **基线为零**——临床评分为 0 会使比率未定义；该变量会变为全 NaN 并给出警告。
   应使用 `--score-scale`。
4. **参考集未能体现负担**——若某变量在参考集中从未偏离，会引发错误而不是除以零；
   若该变量偏离极小，则会使每个评分都被放大。
5. **轨迹中变量成分发生变化**——参见上文抉择 4。
6. **把 MPIW 误读为好事**——区间越宽，PICP 越高，但预测的实用性也随之被摧毁。
7. **报告 KDE 阈值时未附带宽**——阈值可能在带宽变化 10% 时就消失。
8. **把预测结果当作可以等待的许可**——模型无法预见骤然恶化，方案中的人道终点标准
   永远优先。
9. **在不同模型之间比较 RELSA 评分**——只在同一个参考系内才有效。

## 资源

### 脚本

- `scripts/relsa_score.py` —— RELSA 流程：`prepare()`、`build_reference()`、
  `relsa_scores()`、`relsa_weights()`，以及可序列化为 JSON 的 `ReferenceModel`。
  能将 R 包已发表的示例复现到小数点后两位。
- `scripts/forecast_relsa.py` —— foRcast 工具：`auto_arima()`（Hyndman–Khandakar
  逐步 AICc 选择法）、`forecast_animal()`、`predict_endpoint()`、`rolling_forecast()`、
  `forecast_indirect()`、`summarize()`，以及仿论文图 1 风格的绘图。
- `scripts/kde_thresholds.py` —— 严重程度区间：`bw_nrd0()`（R 语言的带宽选择法）、
  `density_curve()`、`find_thresholds()`、区间划分，以及仿论文图 3 风格的密度图。
- `scripts/_common.py` —— RELSA 格式的输入输出、校验、`score_to_percent()`、
  `percent_of_baseline()`，以及 `forecast_metrics()`（RMSE/PICP/MPIW）。

### 参考资料

- `references/relsa-method.md` —— 完整的四步流程、评分/零基线问题、
  变量成分陷阱、与 R 包的一致性说明，以及全部七个已发表模型的结局指标和终点标准。
- `references/forecasting.md` —— ARIMA 选择、为何插值是一种失真、直接预测与间接预测的
  对比、各项指标、已发表的表 1，以及本移植版本所复现的内容。
- `references/thresholds-and-zones.md` —— KDE 方法、已发表的阈值、带宽敏感性扫描、
  监管边界，以及 KDE 未给出结果时的替代方案。

### 资产

- `assets/example_cohort.csv` —— 6 只小鼠的合成队列，包含体温、体重、
  临床评分和一个生物标志物；仅用于示例，并非真实数据。

### 相关技能

- **experimental-design**、**statistical-power** —— 研究设计与分组样本量。
- **statsmodels**、**timesfm-forecasting** —— 一般性时间序列建模。
- **statistical-analysis**、**scientific-visualization** —— 组间比较与图表绘制。

### 关键参考文献

- Talbot, S. R. et al. (2022). RELSA — a multidimensional procedure for the comparative
  assessment of well-being and the quantitative determination of severity in experimental
  procedures. *Front. Vet. Sci.* 9:937711. R package: <https://github.com/mytalbot/RELSA>
- Lutscher, S. et al. (2026). Refining humane endpoint detection by time-series forecasting
  and threshold definition using a multivariate severity score. *Front. Physiol.* 17:1869563.
- Hyndman, R. J. & Khandakar, Y. (2008). Automatic time series forecasting: the forecast
  package for R. *J. Stat. Softw.* 27, 1–22.
- EU Commission (2010). Directive 2010/63/EU on the protection of animals used for scientific
  purposes.
