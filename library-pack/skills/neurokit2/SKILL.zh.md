# NeuroKit2

## 适用范围与证据截止时间

将本 skill 用于基于 NeuroKit2 的、方法感知（method-aware）的可复现生物信号研究。该快照于 **2026-07-23** 核对自以下内容:

- 稳定版 PyPI **0.2.13**,发布于 2026-03-02;
- Python 元数据(`>=3.10`;分类器 3.10-3.14)以及 wheel 依赖;
- GitHub 发布说明/标签、`NEWS.rst`,以及标签 `v0.2.13` 处的源码;
- 官方 API 页面/示例(实时站点自我标识为 `0.2.13.dev214`);以及
- 锁定版本 0.2.13 的运行时签名和合成输出 schema。

在线文档可能领先于稳定版 wheel。对于需要可复现性的工作，优先使用锁定版本的运行时；若查阅开发版文档，需同时注明两个版本号。

## 边界

NeuroKit2 是一个研究与教学用工具箱。**不得**将其输出呈现为:

- 诊断结论、治疗建议、患者监护决策或警报;
- 医疗器械的验证、认证或监管证据；或
- 证明某个生理构念在新的传感器、方案、环境、人群或疾病组中被有效测量了。

需针对预期研究，对采集硬件、电极/光极放置、单位、采样及时钟精度、预处理、检测器/分解方法、人群、任务和结局进行验证。保留原始数据以及可审计的排除记录(exclusion log)。仅使用已去标识化的本地文件；不要将 PHI 放入提示词、日志、示例或随附的测试数据(fixtures)中。

## 可复现的安装方式

```bash
uv pip install "neurokit2==0.2.13"
```

对于可选功能，创建一个 uv 项目，只添加实际需要的、经过审阅的确切版本的软件包，并在 `uv sync --locked` 之前提交/审阅生成的 `uv.lock`。NeuroKit2 提供了一个上游的 `full` extra,但本 skill 有意不在自动化工作流中安装那一套浮动的传递依赖集合。部分可选功能可能需要 MNE、cvxopt、Plotly、PyEMD、pyRQA、Pillow、OpenCV,或其他文件读取器。要把已解析的运行环境和分析结果一起记录下来。任何 MNE 数据/模板下载，都应作为一项明确的、带校验和的研究输入来配置。不要为一项需要可复现性的研究安装一个持续变动的开发分支。

## 必需的数据契约

在处理数据之前，需要记录:

1. 信号身份以及传感器/通道配置;
2. 原生采样率(单位 Hz)以及物理单位(或明确标注为 `arbitrary_unit`);
3. 时钟、时间戳原点、漂移校正，以及同步性证据;
4. 极性/朝向，以及采集端的滤波器/增益;
5. 缺失样本、不连续点、饱和、平线段(flatlines)、运动伪影，以及标注;
6. 事件起始点(event onsets)究竟是从 0 开始的采样点索引，还是以秒为单位;
7. 计划中的预处理顺序、方法、参数、排除规则，以及输出内容；以及
8. 为防止后续统计分析中出现数据泄漏(leakage)所需的参与者层级分组。

绝不要从列名推断单位。不要在未加说明的情况下，把采样点当作毫秒、把数值当作伏特、微西门子或任意单位来静默处理。

## 核心工作流

### 1. 转换之前先检查

```bash
python skills/neurokit2/scripts/inspect_signal.py \
  --input recording.csv --root . --deidentified \
  --columns ECG,RSP,EDA --time-column time_s \
  --units ECG=mV,RSP=a.u.,EDA=uS
```

该检查工具是有边界限定的，不会输出任何行数据或路径信息。在进行滤波之前，先解决非单调递增的时间戳、重复采样点、间隙、非有限值、平线段，以及采样率不一致的问题。

### 2. 保持预处理的顺序

使用以下默认的推理顺序，并根据具体的采集方式和所引用的方法进行调整:

1. 保留不可变的原始信号和标注;
2. 校验时间基准、单位、极性、截幅(clipping)、间隙，以及伪影;
3. 在长间隙处进行分段；只在有明确声明的策略下对短间隙进行插值;
4. 在原生采样率下应用特定模态的清洗;
5. 检测波峰/起始点，或对成分进行分解;
6. 检查质量输出以及叠加在原始信号上的效果;
7. 只在有记录的类别和敏感性检查下，才对波峰进行校正;
8. 推导速率/特征;
9. 在一个明确声明的公共时间网格上对齐各连续模态；以及
10. 将事件索引映射到该网格上，进行分段(epoch)、基线校正与分析。

不要把二值标记或波峰索引数组当作普通连续信号来重采样。应把它们的时间戳映射到目标网格上。滤波和插值可能产生边缘伪影和虚假精度；要为填充、缺失和被剔除的区域保留掩码(mask)。

### 3. 把 schema 当作运行时观测结果来对待

返回列取决于 NeuroKit2 的版本、函数、方法、信号可用性，以及分析模式。绝不要声称某一份列清单是通用的。

```python
signals, info = nk.ecg_process(ecg, sampling_rate=250)
observed_schema = {
    "columns": list(signals.columns),
    "info_keys": sorted(info),
}
```

要把观测到的 schema 与包版本、方法参数、采样率，以及质量/排除摘要一起持久化保存。参考文件列出的是 0.2.13 已验证的默认 schema,并非对每种方法都成立的保证。

## 现行模式

### ECG、经校正的波峰，以及考虑时长的 HRV

在稳定版 0.2.13 中,`ecg_process()` 会执行清洗、带 `correct_artifacts=True` 的 R 波峰检测、速率计算、默认的 `averageQRS` 质量评估、DWT 界定(delineation),以及相位计算。

```python
signals, info = nk.ecg_process(ecg, sampling_rate=250, method="neurokit")
time_hrv = nk.hrv_time(info, sampling_rate=250)
```

要检查 `ECG_R_Peaks_Uncorrected` 和 `ECG_fixpeaks_*`;一个经过校正的序列不会自动成为一个有效的 NN 序列。对于频域/非线性 HRV,应强制执行特定指标所要求的时长和心搏数要求。5 分钟是短程记录的惯例参考值;ULF 是长记录的度量指标，从短记录中解读 VLF 是不安全的。不要把 LF/HF 直接解读为交感-迷走神经平衡。PPG 脉搏率变异性(PRV)不能与 ECG 的 HRV 互换使用。

使用有边界限定的流水线:

```bash
python skills/neurokit2/scripts/ecg_hrv_pipeline.py \
  --synthetic --sampling-rate 250 --duration 300 \
  --domains time,frequency,nonlinear
```

### 带有明确分解方式的 EDA

稳定版默认的 `eda_process(method="neurokit")` 使用的是高通滤波的紧张性/时相性(tonic/phasic)分解，而不是 cvxEDA。应明确选择并报告所用的分解方式:

```python
clean = nk.eda_clean(eda, sampling_rate=100, method="neurokit")
components = nk.eda_phasic(clean, sampling_rate=100, method="highpass")
markers, info = nk.eda_peaks(
    components["EDA_Phasic"],
    sampling_rate=100,
    method="neurokit",
    amplitude_min=0.1,
)
```

对于 `neurokit`/`kim2004` 方法,`amplitude_min` 是相对于检测到的最大反应值而言的；它不是一个绝对的微西门子阈值。cvxEDA 需要可选依赖 `cvxopt`。

```bash
python skills/neurokit2/scripts/eda_pipeline.py \
  --synthetic --sampling-rate 100 --duration 60 \
  --phasic-method highpass --peak-method neurokit
```

### 事件、分段(epoch)与基线

`events_find()` 报告的是从 0 开始的采样点起始位置；持续时间/间隔参数以采样点为单位。`epochs_create()` 的分段边界参数以秒为单位。

```python
events = nk.events_find(trigger, threshold=0.5, duration_min=2)
epochs = nk.epochs_create(
    signals,
    events,
    sampling_rate=100,
    epochs_start=-0.2,
    epochs_end=0.8,
    baseline_correction=False,
)
```

先规划出精确到采样点的时间窗:

```bash
python skills/neurokit2/scripts/plan_epochs.py \
  --events 1000,2500,4000 --event-unit samples \
  --sampling-rate 100 --recording-samples 5000 \
  --epoch-start -0.2 --epoch-end 0.8 \
  --baseline-start -0.2 --baseline-end 0
```

在 0.2.13 中，分段的切片是右端不包含的(end-exclusive),但生成的浮点时间索引却包含 `epochs_end`。内置的基线校正，是用从起始点到 `t=0` 这段区间的分段均值来做减法；若需要更窄的、预先设定的基线，则要手动进行校正。边界处的分段会被填充，可能包含 NaN。分析之前要先决定是丢弃、填充还是报错。

### RSA 与多模态处理

`bio_process()` 假定所有输入信号已经共享同一个采样率并已对齐。它不会做重采样、同步、漂移估计，也不会创建嵌套的模态字典；其 `info` 输出是扁平的。长度不一致的信号会按索引拼接，可能引入 NaN。只有当同步的 ECG 和 RSP 信号同时存在时，才会加入 RSA。

在调用它之前，先校验一份严格的本地清单(manifest):

```bash
python skills/neurokit2/scripts/validate_multimodal.py \
  --manifest streams.json --root . --deidentified
```

在独立完成各模态的 QC 和对齐之后:

```python
bio_signals, bio_info = nk.bio_process(
    ecg=ecg_aligned,
    rsp=rsp_aligned,
    eda=eda_aligned,
    sampling_rate=common_rate,
)
rsa_summary = nk.hrv_rsa(
    bio_signals,
    bio_signals,
    rpeaks=bio_info,
    sampling_rate=common_rate,
    continuous=False,
)
```

摘要形式的 RSA 是一个字典；在已验证的默认工作流中,`continuous=True` 会返回一个带有 `RSA_P2T` 和 `RSA_Gates` 的 DataFrame。要同步记录呼吸数据，并报告其速率/深度/情境;RSA 并不是一个脱离情境的、直接的迷走神经张力度量指标。

### 复杂度(Complexity)返回的是数值加元数据

在 0.2.13 中，大多数复杂度函数返回的是 `(value, info)`。便捷函数同样返回两个对象:

```python
features, details = nk.complexity(signal)  # default which="makowski2022"
sampen, sampen_info = nk.entropy_sample(signal)
dfa, dfa_info = nk.fractal_dfa(signal)
```

默认的便捷选择集合并不等于"全部指标"。复杂度估计对长度、平稳性、归一化方式、延迟(delay)、维度、容差、尺度，以及具体实现都很敏感。应预先设定这些参数，并进行敏感性分析/替代数据(surrogate)分析。

## 随附的命令行辅助工具

所有辅助工具都会拒绝 URL、路径穿越以及符号链接；对字节数/行数/通道数设有边界限制；除非指定 `--force` 否则拒绝覆盖；使用惰性的科学计算库导入方式，使 `--help` 无需 NeuroKit2 即可运行；从不使用 pickle;并产生确定性的 JSON/CSV 输出。处理真实数据的命令要求带上 `--deidentified`。

| 辅助工具 | 用途 |
|---|---|
| `scripts/generate_synthetic.py` | 不依赖外部库的确定性 CSV 测试数据生成器 |
| `scripts/inspect_signal.py` | 有边界限定的 CSV/时间/间隙/平线段检查工具 |
| `scripts/ecg_hrv_pipeline.py` | 锁定版本的 ECG、质量评估、波峰校正、HRV 工作流 |
| `scripts/eda_pipeline.py` | 明确的清洗、分解、SCR 检测工作流 |
| `scripts/plan_epochs.py` | 精确到采样点的事件、边界、基线规划工具 |
| `scripts/validate_multimodal.py` | 严格的单位/速率/时钟/对齐 schema 校验工具 |

在不暴露参与者数据的前提下生成测试数据:

```bash
python skills/neurokit2/scripts/generate_synthetic.py \
  --output synthetic.csv --root . --duration 30 \
  --sampling-rate 250 --seed 42
```

## 安全说明

没有任何示例或辅助工具使用 Python 的 `eval()` 或 `exec()`。NeuroKit2 中诸如 `eeg_*`、`events_*` 和 `*_eventrelated()` 这样的名称都是普通的库函数调用。如果某个静态扫描工具基于子字符串匹配报告了一个 eval/exec 模式，应检查具体那一行代码，只有在确认不存在动态执行之后，才能将其记录为扫描工具的误报。

## 参考文档

只阅读与所处理的模态或决策相关的文件:
下面列出的所有随附 Markdown 路径都位于 `references/` 目录下；本 skill 没有 `templates/` 或 `assets/` 路径下的参考文件。

| 文件 | 内容 |
|---|---|
| `references/signal_processing.md` | 滤波器、间隙、重采样、波峰检测、PSD、schema |
| `references/epochs_events.md` | 事件索引、分段边界、基线 |
| `references/ecg_cardiac.md` | ECG 处理、质量评估、界定(delineation)、波峰校正 |
| `references/hrv.md` | HRV/RSA 输入、时长、异位搏动(ectopy)、结果解读 |
| `references/eda.md` | 清洗、分解、SCR 检测 |
| `references/emg.md` | EMG 清洗、幅值、激活 |
| `references/eog.md` | EOG 极性、MNE 默认值、眨眼特征 |
| `references/eeg.md` | EEG/MNE 辅助工具、功率、QC、微状态(microstates) |
| `references/ppg.md` | PPG 方法、质量语义、PRV 局限性 |
| `references/rsp.md` | 呼吸极性、速率、RRV/RVT/RAV |
| `references/bio_module.md` | 多模态对齐与 `bio_*` schema |
| `references/complexity.md` | 元组返回值、参数敏感性、RQA |

## 已于 2026-07-23 核实的主要来源

- [PyPI 0.2.13](https://pypi.org/project/neurokit2/)
- [Official documentation](https://neuropsychology.github.io/NeuroKit/)
- [API index](https://neuropsychology.github.io/NeuroKit/functions/index.html)
- [GitHub releases](https://github.com/neuropsychology/NeuroKit/releases)
- [Makowski et al. (2021), NeuroKit2](https://doi.org/10.3758/s13428-020-01516-y)
- [Pham et al. (2021), HRV tutorial](https://doi.org/10.3390/s21123998)
- [Makowski et al. (2022), complexity comparison](https://doi.org/10.3390/e24081036)
- [SPR guideline index](https://sprweb.org/guidelines-papers)
- [Quigley et al. (2024), HR/HRV guidelines](https://doi.org/10.1111/psyp.14604)
