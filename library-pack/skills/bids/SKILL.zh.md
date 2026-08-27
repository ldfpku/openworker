# 脑成像数据结构(Brain Imaging Data Structure,BIDS)

## 概述

脑成像数据结构(Brain Imaging Data Structure,BIDS)是一个用于组织和描述神经科学与生物医学研究数据集的社区标准。它定义了统一的文件命名约定、目录层级和元数据模式，使数据集对人和软件工具而言都能一目了然。BIDS 由 BIDS 规范(当前为 v1.11.x)管理，由社区通过 BIDS-Standard GitHub 组织维护。

BIDS 最初起源于 MRI,但如今已远远超出了神经影像的范畴。该规范目前涵盖 11 种模态，横跨影像学、电生理学和行为数据:

- **影像学**:MRI(结构像、功能像、弥散成像、场图、灌注/ASL)、PET、显微成像
- **电生理学**:EEG、MEG、iEEG(颅内脑电)、EMG
- **其他**:NIRS(近红外光谱)、动作捕捉、行为数据(不含影像)、MR 波谱

正在推进的 BEP(BIDS 扩展提案)正在进一步扩展 BIDS——其中 BEP032(微电极电生理)将为细胞外记录(包括 Neuropixels 探针)增加支持，把 BIDS 引入动物神经科学研究中的一种常用方法学(另见 neuropixels-analysis 技能)。

主要数据存储库(OpenNeuro、DANDI)、顶级期刊(NeuroImage、Human Brain Mapping、Scientific Data)以及资助机构(NIH、ERC)都要求或强烈鼓励采用 BIDS。

BIDS 的 Python 生态系统以 **PyBIDS**(`pybids`)为核心，用于查询和索引 BIDS 数据集；以 **bids-validator**(基于 Deno,可通过 PyPI 包 `bids-validator-deno` 或直接通过 Deno 获取)进行合规性检查。从 DICOM 转换通常使用 **HeuDiConv**、**dcm2bids** 或 **BIDScoin**。

## 何时使用本技能

在以下情况下使用本技能:
- 将原始神经科学数据(影像、电生理、行为)组织为符合 BIDS 规范的目录结构
- 查询现有 BIDS 数据集，按受试者(subject)、检查(session)、任务(task)、运行(run)或模态查找特定文件
- 在分享或提交前对照 BIDS 规范验证数据集
- 将来自扫描仪的 DICOM 数据转换为 BIDS 格式
- 编写或编辑 JSON 元数据附属文件(sidecar)
- 创建符合 BIDS 规范的衍生数据(derivatives,预处理数据、分析输出)
- 为新数据集设置 `dataset_description.json`
- 处理 BIDS 实体(entity,如 subject、session、task、acquisition、run 等)
- 配置 `.bidsignore` 以将文件排除在验证之外
- 为上传到 OpenNeuro、DANDI 或其他支持 BIDS 的存储库准备数据

## 安装

```bash
# 核心 BIDS 查询库
uv pip install pybids

# BIDS 验证器(基于 Deno,通过 PyPI 封装包安装)
uv pip install bids-validator-deno
# 备选方案:直接通过 Deno 安装
# deno install -g -A npm:bids-validator

# DICOM 转 BIDS 的转换工具(按需安装)
uv pip install heudiconv       # HeuDiConv - 基于启发式规则的 DICOM 转换
uv pip install dcm2bids        # dcm2bids - 基于配置文件的转换
# BIDScoin: uv pip install bidscoin

# 常用配套工具
uv pip install nibabel          # NIfTI 及其他神经影像文件的读写
uv pip install pydicom          # DICOM 文件读取(转换工具会用到)
```

## 核心工作流程

十二个工作流程领域，各自附带可运行的代码示例，记录在
[references/core_workflows.md](references/core_workflows.md) 中:

1. **BIDS 目录结构**——必需的目录布局，以及各模态应存放在哪里。
2. **`dataset_description.json`**——必填字段，以及如何生成它。
3. **使用 PyBIDS 查询**——`BIDSLayout`、实体过滤器、带自动继承的元数据附属文件，以及从实体构建路径。
4. **验证**——通过 PyPI 封装包(推荐)使用 `bids-validator`、直接通过 Deno 使用、旧版 Node 验证器，以及使用 `.bidsignore` 排除文件。
5. **实体与文件命名**——实体顺序与命名语法。
6. **DICOM 转 BIDS**——HeuDiConv(包括开箱即用的 ReproIn 路径，以及"侦察 → 启发式规则 → 转换"的流程)以及 dcm2bids(基于配置文件)。
7. **元数据附属文件**——各模态所需及推荐的 JSON 字段。
8. **事件文件**——任务态 fMRI 的事件计时与列约定。
9. **参与者文件**——`participants.tsv` 及其数据字典。
10. **衍生数据**——衍生数据的目录布局及其 `dataset_description.json`。
11. **进阶 PyBIDS**——索引缓存(包括衍生数据)、混淆变量回归量(confound regressors),以及 DataFrame 输出。
12. **BIDS-Apps**——标准调用方式，以及 fMRIPrep、MRIQC 和 QSIPrep。

尽早并频繁地验证:PyBIDS 在索引数据集时会验证结构，因此索引失败通常意味着命名或元数据问题，而不是代码本身的 bug。

## 参考材料

本技能包含详细的参考文档:

- **bids_schema.json**:机器可读的 BIDS 模式(来自 https://bids-specification.readthedocs.io/en/stable/schema.json )。这是实体定义、排序规则、文件名模板、每种数据类型允许的后缀，以及元数据字段要求的权威来源。特定 BEP 的模式位于 https://github.com/bids-standard/bids-schema/tree/main/BEPs 。
- **beps.yml**:所有 BIDS 扩展提案的当前列表，含标题、负责人、状态和链接(来自 [bids-website](https://github.com/bids-standard/bids-website/blob/main/data/beps/beps.yml))
- **bids_specification.md**:实体表、数据类型参考、目录结构规则、模板空间和规范变更日志的人类可读摘要
- **metadata_fields.md**:每种 BIDS 模态(anat、func、dwi、fmap、eeg、meg、pet 等)所需及推荐的 JSON 附属文件字段
- **conversion_tools.md**:HeuDiConv、dcm2bids 和 BIDScoin 的详细工作流程，含启发式规则/配置示例及故障排查

用以下命令更新模式和 BEP 列表:`python scripts/update_schema.py`

## 常见问题与解决方法

### 1. 验证器报告"Not a BIDS dataset"(不是 BIDS 数据集)
**原因**:根目录缺少 `dataset_description.json`。
**解决**:创建该文件，至少包含 `{"Name": "...", "BIDSVersion": "1.10.0"}`。

### 2. 受试者不一致警告
**原因**:并非所有受试者都拥有同一组文件(部分缺少 session、run 等)。
**解决**:这是一条警告，不是错误。如果是有意为之，使用 `--ignoreSubjectConsistency`。在 `participants.tsv` 或 `scans.tsv` 中记录缺失数据。

### 3. 缺少 SliceTiming
**原因**:`dcm2niix` 无法从 DICOM 头信息中提取层间时序(slice timing)。
**解决**:根据扫描协议确定层序，手动添加到 JSON 附属文件中。常见模式:顺序递增(ascending)、顺序递减(descending)、交叉采集(interleaved,奇数层优先或偶数层优先)。

### 4. 相位编码方向混淆
**原因**:轴标签(i/j/k 与 x/y/z 与 LR/AP/SI)容易混淆。
**解决**:在 BIDS 中，使用 NIfTI 图像的坐标轴:`i` 表示第一轴,`j` 表示第二轴,`k` 表示第三轴。`-` 表示负方向。对于标准的轴位采集:`j` 通常对应前后方向(anterior-posterior)。用采集协议加以核实。

### 5. PyBIDS 在大型数据集上速度慢
**原因**:每次调用 `BIDSLayout()` 都会进行完整的文件系统索引。
**解决**:使用 `database_path` 将索引缓存到 SQLite 文件:
```python
layout = BIDSLayout("/data", database_path="/data/.pybids_cache.db")
```

### 6. PyBIDS 找不到衍生数据(derivatives)
**原因**:衍生数据目录缺少自己的 `dataset_description.json`。
**解决**:每个衍生数据目录都必须有 `dataset_description.json`,其中包含 `"DatasetType": "derivative"`。

### 7. 事件文件的时间不对
**原因**:`onset`(起始时间)是相对于错误的参照点计算的(例如触发时刻而不是第一个采集帧)。
**解决**:起始时间必须以该次运行采集的第一个体积(volume)为参照，以秒为单位。如果丢弃了预扫描(dummy scans),需在计算中加以考虑。

### 8. TSV 文件验证失败
**原因**:编码或分隔符问题(用空格代替制表符、BOM 字符、Windows 换行符)。
**解决**:确保使用制表符分隔、UTF-8 编码，以及 Unix 换行符(`\n`)。缺失值一律用 `n/a`(不要用 `NA`、`NaN` 或空值)。

## 最佳实践

1. **尽早并频繁地验证**——每次转换或修改后都运行 BIDS 验证器。在错误累积之前就修正它们。

2. **使用元数据继承**——把共享的元数据(例如 `TaskName`、扫描仪参数)放在顶层的附属文件中，而不是在每个受试者的目录中重复写。

3. **保留 sourcedata**——将原始 DICOM(或其他原始)数据存放在 `sourcedata/` 下，以便转换过程可复现。把 `sourcedata/` 加入 `.bidsignore`。

4. **从一开始就使用一致的命名**——在数据采集之前就定义好你的 BIDS 命名方案。对扫描协议使用 ReproIn 命名约定，以便实现自动转换。

5. **为数据集撰写文档**——写一份详尽的 `README`,描述研究设计、采集参数、已知问题，以及任何与 BIDS 的偏离之处。

6. **使用 scans.tsv 记录 run 级别的元数据**——记录每次 run 的采集时间和质量备注:
   ```
   filename	acq_time	quality
   func/sub-01_task-rest_bold.nii.gz	2025-01-15T10:30:00	good
   ```

7. **为数据集做版本管理**——使用 `CHANGES` 文件记录数据集的修改。对于大型数据集，可考虑使用 DataLad 进行完整的版本控制。

8. **对解剖影像去标识化(deface)**——在分享之前，从 T1w/T2w 影像中去除面部特征(例如使用 `pydeface`、`mri_deface` 或 `afni_refacer`)。将去标识化后的版本存为主数据，或使用 `_defacemask` 文件。

9. **使用 BIDS URI 记录溯源**——在衍生数据中，使用 BIDS URI 引用源文件:`bids::sub-01/anat/sub-01_T1w.nii.gz`。

10. **优先使用社区工具**——尽可能使用成熟的 BIDS-Apps(fMRIPrep、MRIQC、QSIPrep),而不是自建流水线。它们能正确处理 BIDS 的输入输出，并生成符合 BIDS 规范的衍生数据。

11. **学习 bids-examples**——[bids-examples](https://github.com/bids-standard/bids-examples) 仓库是涵盖不同模态和用例(MRI、fMRI、DWI、EEG、MEG、iEEG、PET、ASL、遗传学、衍生数据等)的典型 BIDS 数据集的权威合集。可将其作为组织自己数据集时的参考、作为 BIDS 工具的测试数据，或用于理解某个特定模态应当如何组织。每个示例都能通过 BIDS 验证器的检查。

## BIDS 扩展提案(BIDS Extension Proposals,BEPs)

BEP 是社区驱动的提案，用于将 BIDS 扩展到新的模态、衍生数据或元数据。含状态、负责人和链接的完整列表位于 `references/beps.yml` 中(取自 [bids-website](https://github.com/bids-standard/bids-website/blob/main/data/beps/beps.yml))。特定 BEP 的模式预览渲染于 https://github.com/bids-standard/bids-schema/tree/main/BEPs 。

**当前的 BEP 列表**(截至模式更新时):

| BEP | 标题 | 内容类型 | 状态 |
|-----|-------|---------|--------|
| 004 | Susceptibility Weighted Imaging(磁敏感加权成像) | raw(原始数据) | 正在寻找新的负责人 |
| 011 | Structural preprocessing derivatives(结构像预处理衍生数据) | derivative(衍生数据) | 已有 PR(#518) |
| 012 | Functional preprocessing derivatives(功能像预处理衍生数据) | derivative(衍生数据) | 已有 PR(#519),模式已实现 |
| 014 | Affine transforms and nonlinear field warps(仿射变换与非线性场变形) | derivative(衍生数据) | X5 格式开发中 |
| 016 | Diffusion weighted imaging derivatives(弥散加权成像衍生数据) | derivative(衍生数据) | 已有 PR(#2211) |
| 017 | Generic BIDS connectivity data schema(通用 BIDS 连接组数据模式) | derivative(衍生数据) | 开发中 |
| 021 | Common Electrophysiological Derivatives(通用电生理衍生数据) | derivative(衍生数据) | 开发中 |
| 023 | PET Preprocessing derivatives(PET 预处理衍生数据) | derivative(衍生数据) | 开发中 |
| 024 | Computed Tomography scan(计算机断层扫描) | raw(原始数据) | 正在寻找贡献者 |
| 026 | Microelectrode Recordings(微电极记录) | raw(原始数据) | 正在寻找新的负责人 |
| 028 | Provenance(溯源) | metadata(元数据) | 已有 PR(#2099) |
| 032 | Microelectrode electrophysiology(微电极电生理) | raw(原始数据) | 已有 PR(#2307),已提供预览——涵盖 Neuropixels 及其他细胞外探针；与 neuropixels-analysis 技能相关 |
| 033 | Advanced Diffusion Weighted Imaging(进阶弥散加权成像) | raw(原始数据) | 正在寻找贡献者 |
| 034 | Computational modeling(计算建模) | derivative(衍生数据) | 已有 PR(#967) |
| 035 | Mega-analyses with non-compliant derivatives(含非合规衍生数据的大样本荟萃分析) | derivative(衍生数据) | 开发中 |
| 036 | Phenotypic Data Guidelines(表型数据指南) | raw(原始数据) | 社区审阅中 |
| 037 | Non-Invasive Brain Stimulation(非侵入性脑刺激) | raw(原始数据) | 开发中 |
| 039 | Dimensionality reduction-based networks(基于降维的网络) | raw(原始数据) | 开发中 |
| 040 | Functional Ultrasound(功能超声) | raw(原始数据) | 开发中 |
| 041 | Statistical Model Derivatives(统计模型衍生数据) | derivative(衍生数据) | 征集反馈中 |
| 043 | BIDS Term Mapping(BIDS 术语映射) | metadata(元数据) | 征集反馈中 |
| 044 | Stimuli(刺激材料) | raw(原始数据) | 已有 PR(#2022),社区审阅中 |
| 045 | Peripheral Physiological Recordings(外周生理记录) | raw(原始数据) | 已有 PR(#2267) |
| 046 | Diffusion Tractography(弥散纤维束成像) | derivative(衍生数据) | 开发中 |
| 047 | Audio/video recordings for behavioral experiments(行为实验的音视频记录) | raw(原始数据) | 已有 PR(#2231) |

**相关标准**:
- **BIDS-Stats Models**:用于定义基于 GLM 的神经影像分析的 JSON 规范
- **BIDS-Derivatives**(BEP003):预处理/分析输出的标准(已部分并入规范正文)

## 相关工具生态

| 工具 | 用途 |
|------|---------|
| **fMRIPrep** | fMRI 预处理(生成 BIDS 衍生数据) |
| **MRIQC** | MRI 质量控制(生成 BIDS 衍生数据) |
| **QSIPrep** | 弥散 MRI 预处理 |
| **TemplateFlow** | 具有类 BIDS 命名的神经影像模板与图谱 |
| **Fitlins** | BIDS Stats Models 的实现 |
| **DataLad** | 大型数据集的版本控制，与 BIDS 集成 |
| **OpenNeuro** | 免费的 BIDS 数据集存储库 |
| **DANDI** | 神经生理学数据档案库(部分模态使用 BIDS) |
| **HeuDiConv** | 基于启发式 Python 文件的 DICOM 转 BIDS 工具 |
| **dcm2bids** | 基于 JSON 配置的 DICOM 转 BIDS 工具 |
| **BIDScoin** | 带 GUI 和 YAML 配置的 DICOM 转 BIDS 工具 |
| **nwb2bids** | 将 NWB(Neurodata Without Borders)文件转换为 BIDS |
| **CuBIDS** | BIDS 数据集的整理与协调 |
| **bids2table** | 对 BIDS 数据集进行高效的表格化索引 |
| **bids-examples** | 涵盖所有模态的典型 BIDS 数据集权威合集 |

## 文档

- **BIDS 规范**:https://bids-specification.readthedocs.io/
- **BIDS 官网**:https://bids.neuroimaging.io/
- **PyBIDS 文档**:https://bids-standard.github.io/pybids/
- **BIDS 验证器**:https://github.com/bids-standard/bids-validator
- **BIDS 入门套件**:https://bids-standard.github.io/bids-starter-kit/
- **BIDS 示例**:https://github.com/bids-standard/bids-examples —— 涵盖每种 BIDS 模态的权威参考数据集；可用作模板和测试数据
- **HeuDiConv 文档**:https://heudiconv.readthedocs.io/
- **BIDS 原始论文**:Gorgolewski et al. (2016) Scientific Data, doi:10.1038/sdata.2016.44
