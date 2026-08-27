# 药代动力学与药效动力学建模（Pharmacokinetic and Pharmacodynamic Modelling）

## 何时使用

任何关于"身体对药物做了什么"或"药物对身体做了什么"的问题:从浓度-时间数据推导暴露量指标、拟合结构模型、构建或检查群体分析、选择剂量或给药方案、将暴露量与效应关联、比较制剂，或向新人群外推。

## 三条准则

**1. 在计算任何东西之前，先确定暴露量指标和分析人群**。 AUC(0-t)、AUC(0-inf)、稳态下的 AUC(0-tau) 和 Cavg 是不同的量，回答的是不同的问题。基于观测 Clast 与基于预测 Clast 的 AUCinf 也是如此。看到数字之后再做选择，正是一项阴性研究变成阳性研究的方式。

**2. 结构模型、变异性模型和协变量模型是三个独立的决策**。 它们经常被混为一谈——为了吸收实际上是未建模的场合间变异性而加了一个额外的房室、为了修正实际上是吸收模型设定错误的问题而加了一个协变量。在改动任何一个之前，先诊断出到底是哪一个错了。

**3. 收敛不等于可辨识性(identifiability)**。 一个拟合即使收敛了，但某参数的相对标准误(relative standard error)高达 200%,或两个参数之间的相关性达到 0.99,这说明数据无法把它们区分开。这里的每一个拟合脚本都会同时报告并标记这两种情况，因为恰恰在这种情形下，单看参数表反而显得一切正常。

## 范围

本技能负责计算、诊断和结构化整理。它**不会**判定某个制剂是否生物等效、为某项试验选定剂量、为某位患者推荐剂量、断言某药物没有 QT 风险，也不能替代合格的药代动力学统计学家(pharmacometrician)、临床药理学家或监管审评。这些脚本只负责报告，任何一个都不下结论。`tdm_bayes.py` 尤其如此——它是一个建模辅助工具，对患者给药方案的任何调整都是主治临床医生的决定。

## 脚本

```bash
cd skills/pkpd-modeling/scripts
```

| 脚本 | 回答的问题 |
| --- | --- |
| `nca.py` | 暴露量指标是什么，末端相拟合是否足够可靠以报告这些指标? |
| `fit_compartmental.py` | 这些数据支持哪种结构模型，其参数是否可辨识? |
| `simulate_regimen.py` | 该给药方案在稳态下的表现如何，人群中有多大比例能达到目标? |
| `check_popk_dataset.py` | NONMEM 会按我设想的方式读取这个数据集吗? |
| `exposure_response.py` | 是否存在暴露量-效应关系，数据中是否观察到了平台期? |
| `bioequivalence.py` | 90% 置信区间是否满足判定标准，适用的是哪一条标准? |
| `allometry_and_fih.py` | 起始剂量是多少，或在更小/更年幼人群中的剂量是多少? |
| `ddi_static.py` | 体外数据是否触发 ICH M12 下的临床药物相互作用(DDI)研究? |
| `tdm_bayes.py` | 根据该患者的实测血药浓度水平，其个体化参数是多少? |

所有脚本都支持 `--format table|tsv|json`。数据输出到 stdout,溯源信息和发现事项输出到 stderr,因此 `> out.tsv` 可以把二者分开。退出码为 `0` 表示无发现事项,`1` 表示提出了发现事项,`2` 表示输入有误，因此任何一个脚本都可以用来作为工作流的门禁。

两个私有模块承载共用机制:`_models.py`(线性乳突状(mammillary)模型的解析解，加上积分形式的 Michaelis-Menten、TMDD 和间接效应结构)和 `_common.py`(输入输出与报告)。请导入(import)它们，而不要重新推导 Bateman 函数。

## 工作流程

### 1. 非房室分析(Non-compartmental analysis)

```bash
python3 nca.py -i profile.csv --dose 100 --route extravascular --partial-auc 0-24
```

有四个选择决定了最终答案，但通常被隐性地默认处理。本脚本把这四个都显式化:`--auc-method`(默认 `linup-logdown`)、`--blq-rule`、`--lambda-z-points` 或显式的 `--lambda-z-window`,以及你要报告 `auc_inf_obs` 还是 `auc_inf_pred`。

Lambda_z 的选取采用标准规则:从最后三个可定量点开始，向前扩展，只有当**校正后**的 r 平方(adjusted r-squared)提升超过 0.0001 时才保留更长的窗口。普通 r 平方只会随点数增加而上升，所以它总会选中最长的窗口。Tmax 及其之前的点永不纳入——把 Tmax 纳入会拟合到吸收相的尾部，使半衰期、Vz 和 AUCinf 系统性偏低。

在一个无噪声的模拟单房室口服给药曲线上，设 CL/F = 5、V/F = 20、ka = 1.2:

```
id  cmax     tmax  auc_last  lambda_z  t_half   r2_adj  auc_inf_obs  pct_auc_extrap  cl_f     vz_f
1   3.29678  1.5   19.8737   0.25      2.77259  1       19.8739      0.000781037     5.03173  20.1269
```

CL/F 被高估了 0.6%,这不是一个错误，而是梯形法则在稀疏采样吸收相上的固有偏差——这是该采样方案下 NCA 不可避免的偏差，也是为什么 NCA 与房室模型估计的清除率永远不会完全一致。

发现事项才是重点。一条在 tau 处被截断的稳态曲线会产生:

```
finding: subject A: 25.2% of AUCinf is extrapolated (above 20%); AUCinf is driven by the
         lambda_z fit, not by data
finding: subject A: lambda_z window spans 0.58 half-lives (below 2.0); the terminal phase may
         not have been reached
```

这两条都是正确的，但都经常被忽视。在稳态下，应当报告的暴露量指标是 AUC(0-tau),而不是 AUCinf;脚本仍然会计算 AUCinf,但会提示你不要信任它。

### 2. 房室模型拟合与模型选择

```bash
python3 fit_compartmental.py -i profile.csv --dose 500 --route iv-bolus --compare 1cmt,2cmt,3cmt
```

参数是在对数尺度上估计的，因此不会取负值，其置信区间也因此是不对称的。加权默认使用 `1/y2`(恒定 CV),这对 PK 是正确的默认设置，但对同方差(homoscedastic)的 PD 终点则是错误的。

对模拟的双房室数据进行拟合(CL 4、V1 12、Q 6、V2 40,8% 比例误差):

```
model  parameters  wssr       aic       bic       f_vs_simpler  f_p_value    compared_with
1cmt   2           3.13201    -19.4956  -18.0795  n/a           n/a          n/a
2cmt   4           0.0309579  -84.7477  -81.9155  550.936       9.38016e-12  1cmt
3cmt   6           0.0232859  -85.0193  -80.771   1.4826        0.27762      2cmt
```

**AIC 选中了三房室模型。BIC 和 F 检验都拒绝了它**。 AIC 每个参数固定罚 2 分，在这个样本量下惩罚力度偏弱，因此它比从业者预期的更频繁地选中过度参数化的模型。参数表给出了定论:

```
finding: fit: Q3 has 98% RSE - not estimable from these data at this model size
finding: fit: V3 has 71% RSE - not estimable from these data at this model size
```

与此同时，单房室拟合得到:

```
finding: fit: residual signs are not random (runs test p = 0.0036) - a structural
         misspecification, which no amount of reweighting will fix
```

这个区分——结构设定错误 versus 误差模型错误——是必须弄清楚的关键点。残差对时间作图若出现同号连续游程(runs),说明*模型形状*错了。异方差(heteroscedastic)但符号随机的残差说明是*加权*错了。对第一种情况重新加权只是掩盖了问题，并没有解决它。

### 3. 群体药代动力学(Population PK)

在运行任何东西之前先检查数据集。这才是真正耗费时间的地方。

```bash
python3 check_popk_dataset.py -i nmdata.csv --covariates WT,CRCL --time-varying WT
```

真正要命的缺陷都是无声的。NM-TRAN 不会拒绝非数值的 DV——它会把 `BLQ` 读作零，并将其当作真实的零浓度来拟合。空白的协变量会变成 0,所以缺失的体重会变成一个 0 千克的患者。`ADDL` 没有配 `II` 时不会安插任何额外剂量。共享同一时间戳的记录按文件中的先后顺序应用，所以一个血药浓度水平算给药前还是给药后取决于哪一行排在前面。这些问题都不会中止运行。

```
severity  check                            detail
error     non-numeric DV                   DV contains text... NM-TRAN reads them as 0
error     subject with no dose             1 subject(s) have observations but no dose: 2
error     TIME not sorted                  1 subject(s) have out-of-order TIME: 1
error     covariate WT missing             1 record(s) have no value...
warning   duplicate TIME within a subject  NONMEM applies them in file order...
```

对于估计本身，本技能不会重新实现 NLME——估计方法、BLQ 的 M1-M7 处理方法、协变量模型构建，以及判断模型是否可接受的诊断方法，请见 `references/population-pk.md`;该用哪个工具，请见 `references/software-ecosystem.md`。

### 4. 模拟与给药方案选择

```bash
python3 simulate_regimen.py --cl 5 --v 40 --dose 500 --interval 12 --n-doses 10 --steady-state
python3 simulate_regimen.py --cl 5 --v 40 --dose 500 --interval 12 --n-doses 10 \
    --simulate 2000 --omega-cl 0.35 --omega-v 0.25 --target-trough 4.0
```

确定性模拟回答的是"典型患者会是什么样子",而这几乎从来不是真正要问的问题:

```
metric             p5        p25      median   p75      p95      geo_mean
peak               11.861    14.6018  16.6702  19.1476  22.9339  16.6453
trough             0.863226  2.15191  3.64412  5.49655  9.21053  3.27035

target       fraction_attaining
trough >= 4  0.444
```

典型谷浓度是 3.6,目标是 4,于是**只有 44% 的人群能达到目标**。基于典型患者调优的给药方案会让大约一半的人群处在目标的错误一侧。这里报告的达标率甚至还偏乐观，因为只考虑了个体间变异性(between-subject variability),没有纳入残差变异或场合间变异(between-occasion)成分。

线性模型是解析求解并叠加(superposed)的，这是精确的。`--nonlinear` 会切换到积分形式的 Michaelis-Menten 消除，此时叠加原理不再成立，多剂量的行为也完全无法从单剂量数据推断出来。

### 5. 暴露量-效应关系(Exposure-response)

```bash
python3 exposure_response.py --emax -i er.csv --sigmoid
python3 exposure_response.py --cqtc -i qt.csv --cmax 250
```

Emax 拟合会报告 `fraction_of_emax_reached`,并对平台期落在数据范围之外的拟合发出标记。当观测到的最高暴露量只达到估计 Emax 的三分之一时,Emax 和 EC50 就是外推值，二者高度相关；把它们作为独立估计值来引用是站不住脚的，而所谓"线性"的暴露量-效应关系，不过是同一条曲线在低浓度端的一段肢体。

`--cqtc` 评估的是预测的、经安慰剂校正的基线变化 QTc 的**双侧 90% 置信区间上限**,与 10 ms 阈值比较，这正是 ICH E14 真正要问的问题。点估计，或者 95% 区间，回答的是另一个不同的问题。内置模型是用于筛选的普通线性回归；一份达到申报标准的 C-QTc 分析需要一个带受试者内随机截距和斜率的混合效应模型。

每种模式都带有同一条提醒，因为它最容易被遗忘:患者被随机分配到的是**剂量**,而不是**暴露量**。即便在一项随机试验内部，按暴露量分位数划分的暴露量-效应关系仍然是观察性的，可能反映的是驱动清除率的协变量。

### 6. 生物等效性(Bioequivalence)

```bash
python3 bioequivalence.py -i be.csv --design 2x2 --metric AUC
python3 bioequivalence.py -i be.csv --design replicate --metric Cmax --scaling both
python3 bioequivalence.py --power --cv 0.30 --gmr 0.95 --target-power 0.80
```

三种判定标准共用"生物等效性"这个词，却不能互换:平均 BE(90% 置信区间落在 80.00-125.00% 以内)、EMA 的 ABEL(限值随 CVwR 变化而放宽，上限为 69.84-143.19%,点估计仍需落在 80-125% 以内),以及 FDA 的 RSABE(通过 Hyslop 方法得到的按比例缩放的线性化界限，根本不是一个区间)。`--scaling` 在 2x2 设计上拒绝运行:

```
error: reference-scaling requires --design replicate. High observed variability in a 2x2 study
does not license widening: without replicated reference administrations there is no estimate of
within-subject reference variability to scale to.
```

样本量计算能精确复现已发表的表格数值(CV 30%、GMR 0.95、80% 功效 → 2x2 设计下 N = 40)。功效是通过对估计标准差的抽样分布进行积分来计算的，而不是把标准误当作已知量处理——在现实样本量下，正态近似会高估功效。需要注意的是,**N 受假设的 GMR 影响远大于受 CV 的影响**;假设 1.00 而不是 0.95,会使计算出的 N 大致减半，这也是 BE 研究功效不足的常见原因。

### 7. 体型外推、儿科与首次人体试验(First-in-human)

```bash
python3 allometry_and_fih.py --scale --cl 5 --weight-from 70 --weight-to 6 --pma-weeks 44
python3 allometry_and_fih.py --fih --noael rat=50,dog=10 --safety-factor 10
```

在大约 2 岁以下，仅按体型进行外推会高估清除率，对新生儿而言可能高估达数倍之多，因为清除率主要受酶和肾脏成熟度限制，而非体型。提供 `--pma-weeks` 会加入 Anderson-Holford S 形成熟度校正项；在 20 kg 以下省略该参数会触发一条发现事项。

```
parameter  reference  exponent  size_scaled  maturation_factor  final
CL         5          0.75      0.792063     0.30634            0.242641
V          40         1         3.42857      1                  3.42857
```

仅按体型预测会得到 0.79 L/h;加入 44 周孕后龄(post-menstrual age)的成熟度校正后为 0.24 L/h,相差 3.3 倍。分布容积不需要成熟度校正——成熟度描述的是清除能力，而不是分布空间。

`--fih` 使用 FDA 2005 年最大安全起始剂量指南中的体表面积换算方法，并且总会给出一条发现事项:对于激动型免疫调节剂，单纯由 NOAEL 推导的 MRSD 是不够的——用 `--mabel` 计算 MABEL,并取二者中较低的值。

### 8. 药物相互作用(Drug interactions)

```bash
python3 ddi_static.py --basic --ki 0.5 --imax 2.0 --fu 0.05 --dose 0.4
python3 ddi_static.py --msm --ki 0.5 --imax 2.0 --fu 0.05 --dose 0.4 --fm 0.9 --fg 0.7
```

带有各自判定阈值的 ICH M12 基础模型(R1 ≥ 1.02 为肝脏、≥ 11 为肠道;R2 ≥ 1.25 为时间依赖性抑制 TDI;R3 ≤ 0.8 为诱导；转运体阈值按部位划分),外加机制静态模型(mechanistic static model)。这些基础模型有意设计得保守:阴性结果是有意义的，阳性结果只是触发进一步研究的信号，而不是对临床量级的预测。

机制静态模型在给出预测的同时也会报告上限:

```
note: With fm = 0.9, no inhibitor of this pathway can raise the victim AUC above 10.00-fold. If
the prediction approaches that ceiling, fm is doing more work than the inhibition constants.
```

`fm` 和 `Fg` 对答案的影响远大于抑制常数，而它们通常也是计算中最不可靠的数字。

### 9. 治疗药物监测(Therapeutic drug monitoring)

```bash
python3 tdm_bayes.py --model vancomycin-adult --weight 80 --crcl 75 \
    --dose 1500 --interval 12 --level 18.2@11.5 --level 42@2 --target-auc24 500
```

MAP 贝叶斯估计在数据信息量不足时向群体值收缩，在数据信息量充足时则跟随数据走，这就是为什么它优于"用群体参数解读单次谷浓度"和"两点对数线性回归"这两种做法。单次血药浓度水平会触发一条发现事项:它无法把清除率和分布容积区分开，该样本对哪个参数信息不足，那个参数就只是简单地回到了先验值。

内置的万古霉素参数化模型明确标注为示例性质。在结果真正有意义之前，请替换为已在你所在人群中验证过的模型。

## 软件生态

已于 2026-07-27 对照实时来源核实；完整图谱见 `references/software-ecosystem.md`,溯源信息见 `references/source-ledger.md`。

- **Pharmpy 2.1.1**(2026-05-19)是实用的 Python 入口——与具体模型无关(model-agnostic),可驱动 NONMEM/nlmixr2/rxode2,并附带 19 个 `run_*` 工具，包括 `run_amd`、`run_modelsearch`、`run_covsearch`、`run_structsearch`、`run_pdsearch`、`run_modelrank`、`run_vpc` 和 `run_qa`。有两个近期的破坏性变更需要留意:**2.0.0(2026-02-12)将数据集行索引改为从 1 开始**,**2.1.0(2026-05-08)将 `add_placebo_model` 重命名为 `set_placebo_model`**,且现在要求 numpy ≥ 2。
- **NONMEM 7.6**(用户指南日期为 2025 年 11 月)仍是监管领域的默认选择。相较 7.5 版新增:ADVAN16(用于刚性延迟微分方程的 RADAR5 隐式龙格-库塔法)、ADVAN17(刚性延迟微分代数方程)、NUTS 贝叶斯采样，以及 SAEM 个体样本存储。
- **nlmixr2**(要求 rxode2 ≥ 5.0.0)是可信的开源 NLME 替代方案;`babelmixr2` 和 `monolix2rx` 可在它、NONMEM 和 Monolix 之间转换模型。
- **PKPy**(PeerJ,2025)是一个 Python 群体 PK 框架，但**仅在 GitHub 上——不在 PyPI 上**,因此 `uv pip install pkpy` 会失败。`chi-drm`(1.0.3)在 PyPI 上，用于贝叶斯 PKPD。
- **Open Systems Pharmacology Suite v12**(PK-Sim/MoBi)是开源的 PBPK 平台;Simcyp 和 GastroPlus 是商业平台。`ospsuite` 仅支持 R,且需要 .NET 8。

Python 目前没有具备监管认可地位的成熟 NCA 或 NLME 包。正是这个缺口，促使本技能自带经过验证的 NCA 和拟合实现，而不是去封装某个现成的包。

## 本技能旨在防止的问题

1. 用普通 r 平方选取 lambda_z,或把拟合窗口延伸到了 Tmax 之内。
2. 从一条 25% 被外推的曲线中报告 AUCinf。
3. 让 AIC 选中一个房室间清除率 RSE 高达 98% 的模型。
4. 用重新加权去修补本质上是结构问题的非随机残差。
5. 让 `BLQ` 留在 DV 列中，而 NM-TRAN 会把它读作真实的零值。
6. 只基于典型患者选定给药方案，而没有给出人群达标率估计。
7. 在从未观察到平台期的情况下，把 Emax 和 EC50 当作独立估计值来引用。
8. 把参考值校正(reference-scaled)的生物等效性限值套用到 2x2 研究上。
9. 对新生儿做体型外推却不加成熟度校正项。
10. 把基于 NOAEL 得到的 MRSD 直接用作激动型免疫调节剂的起始剂量。

## 参考资料

- `references/nca-conventions.md` —— 参数定义、lambda_z 规则、BLQ 处理、稳态
- `references/structural-models.md` —— 闭式解、参数化方式、NONMEM ADVAN/TRANS 对照表
- `references/population-pk.md` —— NLME 估计、协变量模型构建、BLQ M1-M7、诊断、VPC
- `references/pd-and-exposure-response.md` —— Emax、间接效应模型、效应室、暴露量-效应分析
- `references/tmdd-and-biologics.md` —— TMDD 近似方法、单克隆抗体 PK、免疫原性
- `references/pbpk.md` —— PBPK 何时值得投入、平台选择，以及验证需要什么
- `references/bioequivalence.md` —— 设计方案、ABE/ABEL/RSABE、ICH M13 系列、高变异性药物
- `references/special-populations.md` —— 儿科、肾功能与肝功能损害、肥胖、妊娠
- `references/dataset-standards.md` —— CDISC PC/PP 与 ADPC/ADPP、NONMEM 数据项、常见缺陷
- `references/ddi-and-qt.md` —— ICH M12 分步评估、静态模型、ICH E14/S7B C-QTc
- `references/antimicrobial-and-tdm.md` —— PK/PD 指标、PTA/CFR、万古霉素 AUC 导向给药、MIPD
- `references/software-ecosystem.md` —— 每个工具的用途、许可方式，以及经核实的版本号
- `references/regulatory-guidance.md` —— 监管指南台账，含日期、状态，以及各自的要求
- `references/source-ledger.md` —— 本技能中每一项论断的溯源信息与调研日期

## 资产

- `assets/popk-analysis-plan.md` —— 群体分析计划的结构，把各项决策前置写明
- `assets/nca-reporting-checklist.md` —— NCA 报告中数字要想可解读，必须写明哪些内容
