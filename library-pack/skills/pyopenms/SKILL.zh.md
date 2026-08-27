# PyOpenMS

## 概述

PyOpenMS 提供了 OpenMS 计算质谱库的 Python 绑定，可用于分析蛋白质组学和代谢组学数据。可以用它读写各类质谱文件格式、处理原始谱图、检测并定量特征（feature）、鉴定肽段和蛋白质，以及运行端到端的 LC-MS/MS 流水线。

**本技能在 `scripts/` 目录中随附了可直接运行的脚本**，覆盖了最常见的高层级工作流。应优先运行脚本，而不是重新编写代码——每个脚本都是一个带参数的命令行工具，负责数据加载、处理和导出。只有在没有合适脚本可用时，才需要直接使用 Python API（以及 `references/` 中的资料）。

## 安装

```bash
uv pip install pyopenms
```

验证安装（注意：`__version__` 可正常使用，但随附的二进制文件在导入时会打印一行内存状态提示，这是无害的）：

```python
import pyopenms as ms
print(ms.__version__)  # 3.5.0
```

## 脚本（从这里开始）

运行 `python scripts/<name>.py --help` 可查看完整选项。所有脚本都接受标准的质谱文件格式，并按需写出 featureXML/consensusXML/CSV/mzTab/PNG。

### 检查与转换
| 脚本 | 功能 |
|--------|--------------|
| `inspect_ms_data.py` | 汇总任意 mzML/mzXML/featureXML/consensusXML/idXML 文件（计数、RT/m/z 范围、TIC、元数据）；可选按谱图输出 CSV。 |
| `convert_format.py` | 在 mzML/mzXML/MGF 之间进行转换，可选按 MS 级别、RT、强度进行过滤。 |
| `process_spectra.py` | 可配置的信号处理链：平滑（Gauss/SGolay）、峰质心化（PeakPickerHiRes）、归一化、信噪比与强度阈值。 |

### 特征检测与定量
| 脚本 | 功能 |
|--------|--------------|
| `detect_features_metabo.py` | 非靶向代谢组学特征查找：MassTraceDetection → ElutionPeakDetection → FeatureFindingMetabo。 |
| `detect_features_centroided.py` | 通过 FeatureFinderAlgorithmPicked 进行肽段/质心化特征检测。 |
| `align_link_quantify.py` | 多样本流水线：检测（或加载）特征 → RT 对齐 → 共识（consensus）关联 → 输出定量矩阵 CSV。 |
| `consensus_to_matrix.py` | 将 consensusXML 转换为宽格式强度矩阵 + 元数据，可选中位数/分位数归一化及长格式输出。 |

### 注释
| 脚本 | 功能 |
|--------|--------------|
| `detect_adducts.py` | 将同一中性质量的加合物（adduct）/电荷变体归为一组（MetaboliteFeatureDeconvolution）。 |
| `accurate_mass_search.py` | 按精确质量将特征与 HMDB 进行比对注释（AccurateMassSearchEngine → mzTab/CSV）。 |
| `export_gnps_sirius.py` | 导出 GNPS FBMN 所需的输入（MGF + 定量表），或导出 SIRIUS 的 `.ms` 文件。 |

### 鉴定
| 脚本 | 功能 |
|--------|--------------|
| `process_identifications.py` | 针对 FASTA 重新建立索引、估算 FDR/q 值、按（FDR/长度/每谱图最佳匹配）进行过滤，导出 idXML + CSV。 |

### 化学计算
| 脚本 | 功能 |
|--------|--------------|
| `mass_calculator.py` | 计算肽段或化学式的单同位素/平均质量、带电荷 m/z、化学式，以及同位素分布模式。 |
| `digest_protein.py` | 对 FASTA/序列进行计算机模拟蛋白酶消化 → 生成带质量和 m/z 的理论肽段。 |
| `theoretical_spectrum.py` | 为某条肽段生成带注释的理论碎片谱图（b/y/a/c/x/z 离子系列、中性丢失）。 |

### 靶向分析与可视化
| 脚本 | 功能 |
|--------|--------------|
| `extract_chromatograms.py` | 为目标 m/z 构建 TIC/BPC 及 XIC 色谱轨迹（CSV + 可选绘图）。 |
| `plot_ms_data.py` | 快速绘图：单张谱图、TIC、二维特征图、MS1 信号图。 |

### 常用脚本套路

```bash
# Inspect a file
python scripts/inspect_ms_data.py sample.mzML --spectra-csv spectra.csv

# Untargeted metabolomics: features for one sample
python scripts/detect_features_metabo.py sample.mzML --out-csv features.csv

# Full multi-sample quantification study
python scripts/align_link_quantify.py s1.mzML s2.mzML s3.mzML --out-prefix study
python scripts/consensus_to_matrix.py study.consensusXML --out quant.csv --normalize median

# Peptide chemistry
python scripts/mass_calculator.py --peptide "PEPTIDEM(Oxidation)K" --charges 1 2 3 --isotopes 5
python scripts/digest_protein.py proteins.fasta --enzyme Trypsin --missed 2 --out peptides.csv

# Identification post-processing
python scripts/process_identifications.py search.idXML --fasta db.fasta --fdr 0.01 --out filtered.idXML --csv hits.csv
```

## 3.5.0 版本关键 API 变更说明

以下内容相较于旧版 OpenMS 已发生变化——较旧的教程和代码在这些地方会失效：

- **特征查找**：`FeatureFinder("centroided")` 已被**移除**。应改用
  `FeatureFinderAlgorithmPicked`（蛋白质组学/质心化数据）或
  `MassTraceDetection → ElutionPeakDetection → FeatureFindingMetabo` 流水线
  （代谢组学）。参见 `detect_features_*.py`。
- **idXML 读写**：`IdXMLFile().load/store` 在处理肽段鉴定结果时要求传入
  `ms.PeptideIdentificationList()`（传入普通的 Python `list` 会引发 "can not handle type" 错误）。蛋白质鉴定结果仍然使用普通的 list。
- **加合物脱电荷**：对应的类名为 `MetaboliteFeatureDeconvolution`，加合物使用
  `Elements:Charge:Probability` 语法（例如 `H:+:0.4`、`H-2O-1:0:0.05`）——而不是像 `[M+H]+` 这样的方括号记法。
- **DataFrame 列名**：`FeatureMap.get_df()` 使用小写的 `rt`/`mz`（而不是 `RT`）。
  `ConsensusMap` 提供 `get_intensity_df()` 和 `get_metadata_df()`。
- **随附数据的注意事项**：pip wheel 包中附带了 `HMDBMappingFile.tsv`，但没有附带
  `HMDB2StructMapping.tsv`；`accurate_mass_search.py` 会检测到这一情况，并说明如何补充提供该文件。

## 核心数据结构

- **MSExperiment** —— 谱图与色谱图的集合
- **MSSpectrum / MSChromatogram** —— 单张谱图 / 单条色谱轨迹
- **Feature / FeatureMap** —— 一个检测到的 LC-MS 峰 / 特征的集合
- **ConsensusMap** —— 跨样本关联后的特征（即定量表）
- **PeptideIdentification / ProteinIdentification** —— 检索（搜库）结果
- **AASequence / EmpiricalFormula** —— 序列与化学式相关的化学计算

**详情参见**：`references/data_structures.md`。

## 参数管理

大多数算法都暴露一个 OpenMS 的 `Param` 对象：

```python
algo = ms.FeatureFindingMetabo()
p = algo.getDefaults()
for key in p.keys():
    print(key.decode(), "=", p.getValue(key), "|", p.getDescription(key))
p.setValue("charge_lower_bound", 1)
algo.setParameters(p)
```

## 导出为 pandas

```python
fm = ms.FeatureMap(); ms.FeatureXMLFile().load("features.featureXML", fm)
df = fm.get_df()             # columns include lowercase rt, mz, intensity, charge, quality

cm = ms.ConsensusMap(); ms.ConsensusXMLFile().load("study.consensusXML", cm)
intensities = cm.get_intensity_df()   # features x samples
metadata = cm.get_metadata_df()       # rt, mz, charge, quality, ...
```

## 与其他工具的集成

Pandas（DataFrame）、NumPy（峰数组）、scikit-learn（机器学习）、Matplotlib/Seaborn
（绘图），以及通过导出对接下游工具：GNPS（FBMN）、SIRIUS 和 mzTab。

## 资源

- 官方文档（3.5.0 版）：https://pyopenms.readthedocs.io/en/release-3.5.0/
- OpenMS：https://www.openms.org
- GitHub：https://github.com/OpenMS/OpenMS

## 参考资料

- `references/file_io.md` —— 文件格式处理
- `references/signal_processing.md` —— 信号处理算法
- `references/feature_detection.md` —— 特征检测与关联
- `references/identification.md` —— 肽段与蛋白质鉴定
- `references/metabolomics.md` —— 代谢组学专属工作流
- `references/data_structures.md` —— 核心对象与数据结构
