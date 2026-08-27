# Neuropixels 数据分析

## 概览

一套使用来自 [SpikeInterface](https://spikeinterface.readthedocs.io/)、Allen
Institute 和 International Brain Laboratory(IBL)的当前最佳实践，分析
Neuropixels 高密度神经记录的工具包。它覆盖了从原始数据到可发表的、经过整理的
神经元单元(unit)的完整工作流程。

所有示例都使用真实的 SpikeInterface API(`spikeinterface.full as si`),
以及配套的整理(curation)模块(`spikeinterface.curation as sc`)。本技能在
`scripts/` 中提供可直接运行的脚本，在 `assets/` 中提供可复制修改的模板,
它们都是直接构建在 SpikeInterface 之上实现这套工作流程的——除了
[安装](#installation)一节中列出的依赖之外，不需要额外安装其他独立的软件包。

## 何时使用本技能

在以下情况下应当使用本技能:
- 处理 Neuropixels 记录(`.ap.bin`、`.lf.bin`、`.meta` 文件)
- 从 SpikeGLX、Open Ephys 或 NWB 格式加载数据
- 对神经记录做预处理(滤波、共同参考、坏通道检测)
- 检测并校正运动/漂移(motion/drift)
- 运行 spike sorting(Kilosort4、SpykingCircus2、Mountainsort5、Tridesclous2)
- 计算质量指标(SNR、ISI 违反率、存在比率、幅度截断)
- 对神经元单元(unit)做整理(基于阈值、基于模型、或 AI 辅助)
- 创建可视化图表并导出到 Phy 或 NWB

## 支持的硬件与格式

| 探针 | 电极数 | 通道数 | 备注 |
|-------|-----------|----------|-------|
| Neuropixels 1.0 | 960 | 384 | 使用 `phase_shift` 做 ADC 校正 |
| Neuropixels 2.0(单探针) | 1280 | 384 | 更密的几何排布 |
| Neuropixels 2.0(4 shank) | 5120 | 384 | 多脑区记录 |

| 格式 | 扩展名 | 读取器 |
|--------|-----------|--------|
| SpikeGLX | `.ap.bin`、`.lf.bin`、`.meta` | `si.read_spikeglx()` |
| Open Ephys | `.continuous`、`.oebin` | `si.read_openephys()` |
| NWB | `.nwb` | `si.read_nwb()` |

## 快速开始

### 导入并配置并行处理

```python
import spikeinterface.full as si

# Global job kwargs are reused by all parallelizable steps
si.set_global_job_kwargs(n_jobs=-1, chunk_duration="1s", progress_bar=True)
```

### 加载数据

```python
# Inspect available streams first
stream_names, stream_ids = si.get_neo_streams("spikeglx", "/path/to/run_g0/")
print(stream_names)  # e.g. ['imec0.ap', 'imec0.lf', 'nidq']

# SpikeGLX (most common) — select the AP stream by name
recording = si.read_spikeglx("/path/to/run_g0/", stream_name="imec0.ap", load_sync_channel=False)

# Open Ephys
recording = si.read_openephys("/path/to/Record_Node_101/")

# For quick iteration, slice the first 60 s
fs = recording.get_sampling_frequency()
recording_sub = recording.frame_slice(0, int(60 * fs))
```

### 完整流水线(打包脚本)

本仓库提供了一套构建在 SpikeInterface 之上的端到端流水线:

```bash
python scripts/neuropixels_pipeline.py /path/to/spikeglx/data output/ --sorter kilosort4 --curation allen
```

它依次执行加载 → 预处理 → 漂移检查 → 可选的运动校正 → sorting →
后处理 → 质量指标计算 → 整理(curation) → 导出。阅读下面的步骤可以交互式地
运行这些环节，或对流水线做定制。

## 标准分析工作流程

### 1. 预处理

推荐的处理链，遵循 SpikeInterface 的 Neuropixels 操作指南(IBL 风格的
destriping,即去除坏通道 + 共同参考):

```python
rec = si.highpass_filter(recording, freq_min=400.0)
bad_channel_ids, channel_labels = si.detect_bad_channels(rec)
rec = rec.remove_channels(bad_channel_ids)
rec = si.phase_shift(rec)  # ADC phase correction (Neuropixels 1.0)
rec = si.common_reference(rec, operator="median", reference="global")
```

保存预处理后的记录(Kilosort 需要一个二进制文件，而且这样做也能加快复用速度):

```python
rec = rec.save(folder="preprocessed/", format="binary")
```

### 2. 检查并校正漂移

在做 spike sorting 之前务必先检查漂移:

```python
from spikeinterface.sortingcomponents.peak_detection import detect_peaks
from spikeinterface.sortingcomponents.peak_localization import localize_peaks

noise_levels = si.get_noise_levels(rec, return_in_uV=False)
peaks = detect_peaks(rec, method="locally_exclusive", noise_levels=noise_levels,
                     detect_threshold=5, radius_um=50.0)
peak_locations = localize_peaks(rec, peaks, method="center_of_mass")

# Visualize the drift raster
si.plot_drift_raster_map(peaks=peaks, peak_locations=peak_locations,
                         recording=rec, clim=(-50, 50))
```

如有需要，应用校正(预设选项:`rigid_fast`、`kilosort_like`、
`nonrigid_accurate`、`nonrigid_fast_and_accurate`、`dredge`、`dredge_fast`):

```python
rec_corrected = si.correct_motion(rec, preset="nonrigid_fast_and_accurate", folder="motion/")
```

### 3. Spike sorting

```python
# Kilosort4 (recommended, requires a CUDA GPU)
sorting = si.run_sorter("kilosort4", rec_corrected, folder="ks4_output")

# CPU alternatives (internally developed, no external install)
sorting = si.run_sorter("spykingcircus2", rec_corrected, folder="sc2_output")
sorting = si.run_sorter("tridesclous2", rec_corrected, folder="tdc2_output")
sorting = si.run_sorter("mountainsort5", rec_corrected, folder="ms5_output")

# External sorters can run in containers without local install
sorting = si.run_sorter("kilosort2_5", rec_corrected, folder="ks25_output", docker_image=True)

print(si.installed_sorters())
```

> 注意:`run_sorter` 使用的是 `folder=` 参数。较旧的 `output_folder=` 已被弃用。

### 4. 后处理

```python
analyzer = si.create_sorting_analyzer(sorting, rec_corrected, sparse=True,
                                      format="binary_folder", folder="analyzer/")

analyzer.compute("random_spikes", method="uniform", max_spikes_per_unit=500)
analyzer.compute("waveforms", ms_before=1.0, ms_after=2.0)
analyzer.compute("templates", operators=["average", "std"])
analyzer.compute("noise_levels")
analyzer.compute("spike_amplitudes")
analyzer.compute("correlograms", window_ms=50.0, bin_ms=1.0)
analyzer.compute("unit_locations", method="monopolar_triangulation")
analyzer.compute("template_similarity")

metric_names = ["firing_rate", "presence_ratio", "snr", "isi_violation", "amplitude_cutoff"]
analyzer.compute("quality_metrics", metric_names=metric_names)
metrics = analyzer.get_extension("quality_metrics").get_data()
```

### 5. 按指标阈值做整理(curation)

```python
# Allen-style query (note: column is isi_violations_ratio)
query = "(amplitude_cutoff < 0.1) & (isi_violations_ratio < 0.5) & (presence_ratio > 0.9)"
good_unit_ids = metrics.query(query).index.values
```

如果需要可复用的、带 `allen` / `ibl` / `strict` 预设的多阈值逻辑，请使用
打包好的 `scripts/compute_metrics.py`。详情及 Bombcell / UnitMatch 工具见
[references/AUTOMATED_CURATION.md](references/AUTOMATED_CURATION.md)。

### 6. 基于模型的整理(UnitRefine)

SpikeInterface 可以通过 `spikeinterface.curation` 模块，应用来自 Hugging Face
的预训练机器学习分类器。UnitRefine 模型是在真实的 Neuropixels 数据(V1、SC、
ALM)上训练的:

```python
import spikeinterface.curation as sc

# 1) noise vs neural
noise_labels = sc.model_based_label_units(
    sorting_analyzer=analyzer,
    repo_id="SpikeInterface/UnitRefine_noise_neural_classifier",
    trust_model=True,
)
neural = analyzer.remove_units(noise_labels[noise_labels["prediction"] == "noise"].index)

# 2) single-unit (sua) vs multi-unit (mua) on the surviving units
sua_mua_labels = sc.model_based_label_units(
    sorting_analyzer=neural,
    repo_id="SpikeInterface/UnitRefine_sua_mua_classifier",
    trust_model=True,
)
```

每次调用都会返回一个 DataFrame,其中每个 unit 都有对应的 `prediction`(预测
结果)和 `probability`(置信度)。加载 `.skops` 模型需要设置
`trust_model=True`(或显式给出一个 `trusted=[...]` 列表)——只加载来自可信
来源的模型。在其他脑区/数据集上训练的模型可能无法很好地迁移；应针对手动
标注的子集做验证。

### 7. AI 辅助整理(用于不确定的单元)

当在 Cursor 或 Claude Code 这类智能体环境中运行时，智能体可以直接查看波形/
互相关图(correlogram plots),给出专家级的判断——无需任何 API 配置。生成
图表，并让智能体评估隔离质量(isolation quality)即可。

如需以编程方式访问视觉模型,**要从环境变量中读取 API 密钥——绝不要在分析
脚本中硬编码凭证**(它们会泄漏进版本控制系统和日志中):

```python
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])  # set this in your shell, not in code
```

完整模式(渲染一张单元摘要图像、构建提示词、解析响应)见
[references/AI_CURATION.md](references/AI_CURATION.md)。

### 8. 导出结果

```python
# Keep only good units, then export
analyzer_clean = analyzer.select_units(good_unit_ids, folder="analyzer_clean/", format="binary_folder")

# Phy for manual review
si.export_to_phy(analyzer_clean, output_folder="phy_export/",
                 compute_pc_features=True, compute_amplitudes=True)

# Figures report
si.export_report(analyzer_clean, "report/", format="png")

# NWB
from spikeinterface.exporters import export_to_nwb
export_to_nwb(analyzer_clean, "output.nwb")

# Metrics table
metrics.to_csv("quality_metrics.csv")
```

## 常见陷阱与最佳实践

1. **在做 spike sorting 之前务必检查漂移**——漂移超过约 10 μm 会显著降低质量。
2. **对 Neuropixels 1.0 使用 `phase_shift`** 来校正 ADC 采样偏移。
3. **用 `rec.save(folder=...)` 保存预处理后的记录**,以避免重复计算(Kilosort 也需要一个二进制文件)。
4. **对 Kilosort4 使用 GPU**——它比 CPU sorter 快得多。
5. **复核不确定的单元**——自动化/基于模型的整理只是起点，不是定论。
6. **组合使用多种方法**——明确的情况用阈值判断，边界情况用模型/AI 辅助判断。
7. **记录阈值和模型仓库 ID**,以保证可复现性。
8. **对关键实验导出到 Phy**——人工复核是有价值的。

## 需要调整的关键参数

### 预处理
- `freq_min`:高通滤波截止频率(典型值 300–400 Hz)
- `detect_bad_channels`:返回 `(bad_channel_ids, channel_labels)`

### 运动校正
- `preset`:`nonrigid_fast_and_accurate`(均衡)、`nonrigid_accurate`(严重漂移)、`dredge`(当前最先进方法)

### Spike Sorting(Kilosort4)
- `batch_size`:每批次的采样点数(默认 60000)
- `nblocks`:漂移分块数(记录时长较长、漂移较严重时应增大)
- `Th_universal` / `Th_learned`:检测阈值(越低检出的 spike 越多)

### 质量指标
- `snr`:信噪比截止值(典型值 3–5)
- `isi_violations_ratio`:不应期违反率(0.01–0.5)
- `presence_ratio`:记录覆盖率(0.5–0.95)

## 打包资源

### scripts/explore_recording.py
快速查看一份记录(数据流、通道、时长、坏通道):
```bash
python scripts/explore_recording.py /path/to/data
```

### scripts/preprocess_recording.py
自动化预处理:
```bash
python scripts/preprocess_recording.py /path/to/data --output preprocessed/
```

### scripts/run_sorting.py
运行 spike sorting:
```bash
python scripts/run_sorting.py preprocessed/ --sorter kilosort4 --output sorting/
```

### scripts/compute_metrics.py
计算质量指标并应用整理(curation):
```bash
python scripts/compute_metrics.py sorting/ preprocessed/ --output metrics/ --curation allen
```

### scripts/export_to_phy.py
导出到 Phy 以便手动整理:
```bash
python scripts/export_to_phy.py metrics/analyzer --output phy_export/
```

### scripts/neuropixels_pipeline.py
完整的端到端流水线(参见[快速开始](#full-pipeline-bundled-script))。

### assets/analysis_template.py
完整的、可编辑的分析模板。复制并定制:
```bash
cp assets/analysis_template.py my_analysis.py
# Edit the PARAMETERS section, then run
python my_analysis.py
```

## 详细参考指南

| 主题 | 参考文件 |
|-------|-----------|
| 完整工作流程 | [references/standard_workflow.md](references/standard_workflow.md) |
| API 参考(SpikeInterface) | [references/api_reference.md](references/api_reference.md) |
| 绘图指南 | [references/plotting_guide.md](references/plotting_guide.md) |
| 预处理 | [references/PREPROCESSING.md](references/PREPROCESSING.md) |
| Spike sorting | [references/SPIKE_SORTING.md](references/SPIKE_SORTING.md) |
| 运动校正 | [references/MOTION_CORRECTION.md](references/MOTION_CORRECTION.md) |
| 质量指标 | [references/QUALITY_METRICS.md](references/QUALITY_METRICS.md) |
| 自动化与基于模型的整理 | [references/AUTOMATED_CURATION.md](references/AUTOMATED_CURATION.md) |
| AI 辅助整理 | [references/AI_CURATION.md](references/AI_CURATION.md) |
| 波形分析 | [references/ANALYSIS.md](references/ANALYSIS.md) |

## 安装

需要 Python ≥ 3.10。推荐使用 [uv](https://docs.astral.sh/uv/)。

```bash
# Core packages (SpikeInterface bundles the curation/model tooling)
uv pip install "spikeinterface[full]" probeinterface neo

# Spike sorters
uv pip install kilosort          # Kilosort4 (CUDA GPU required)
uv pip install spykingcircus     # SpykingCircus (legacy; SpykingCircus2 ships with SpikeInterface)
uv pip install mountainsort5     # Mountainsort5 (CPU)

# Model-based curation (UnitRefine) downloads from Hugging Face
uv pip install "huggingface_hub" skops

# Optional: AI-assisted visual curation
uv pip install anthropic

# Optional: IBL tools and Bombcell
uv pip install ibl-neuropixel ibllib bombcell
```

为了保证环境的可复现性，建议锁定版本号(截至 2026-06 的当前版本:
`spikeinterface==0.104.3`、`kilosort==4.1.7`、`probeinterface==0.3.2`、
`neo==0.14.4`)。快速试验时不锁定版本没有问题，但在生产环境的流水线中应当
锁定版本。

## 项目结构

```
project/
├── raw_data/
│   └── recording_g0/
│       └── recording_g0_imec0/
│           ├── recording_g0_t0.imec0.ap.bin
│           └── recording_g0_t0.imec0.ap.meta
├── preprocessed/           # Saved preprocessed recording
├── motion/                 # Motion estimation results
├── sorting_output/         # Spike sorter output
├── analyzer/               # SortingAnalyzer (waveforms, metrics)
├── phy_export/             # For manual curation
├── ai_curation/            # AI analysis reports
└── results/
    ├── quality_metrics.csv
    ├── curation_labels.json
    └── output.nwb
```

## 其他资源

- **SpikeInterface 文档**: https://spikeinterface.readthedocs.io/
- **Neuropixels 教程**: https://spikeinterface.readthedocs.io/en/stable/how_to/analyze_neuropixels.html
- **基于模型的整理教程**: https://spikeinterface.readthedocs.io/en/stable/tutorials/curation/plot_1_automated_curation.html
- **UnitRefine 模型(Hugging Face)**: https://huggingface.co/SpikeInterface
- **Kilosort4 GitHub**: https://github.com/MouseLand/Kilosort
- **IBL Neuropixel 工具**: https://github.com/int-brain-lab/ibl-neuropixel
- **Allen Institute ecephys**: https://github.com/AllenInstitute/ecephys_spike_sorting
- **Bombcell(自动化质控)**: https://github.com/Julie-Fabre/bombcell
- **Awesome Neuropixels**: https://github.com/Julie-Fabre/awesome_neuropixels
