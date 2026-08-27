# PathML

## 适用范围与安全边界

请将 PathML 用于**本地计算病理学研究**。它是测试版（beta）研究软件，不是经过验证的医疗器械、诊断系统、临床决策支持工具，也不能替代病理医师。不要将其输出用于对患者进行诊断、分级、分期或治疗。

病理学文件可能包含人脸、标签、送检号、患者标识符、DICOM 标签、文件名，或关联的临床数据。在处理之前：

1. 确认已获得授权、知情同意/豁免、数据使用条款以及机构政策的许可。
2. 对像素数据和元数据进行去标识化；将重新识别所需的密钥保存在分析工作区之外。
3. 使用假名化的 `patient_id`、`slide_id` 和 `specimen_id` 取值。不要将直接标识符放入文件名、日志、`.h5path` 标签、模型卡（model card）或报告中。
4. 将输入、中间产物和输出全部保存在经批准的本地加密存储中。
5. 在进行任何切片分块（tiling）或拟合任何预处理步骤之前，先按患者（再按切片）划分数据集。

## 版本基线，核实于 2026-07-23

- **可安装的稳定发行版**： PyPI 上的 `pathml==3.0.5`，发布于 2026-03-24。
- v3.0.5 的发行说明指出支持 Python **3.10-3.12**，并终止对 3.9 的支持。
  PyPI 元数据中未声明 `Requires-Python`，且仍带有一个过时的 3.8 分类标签，因此应以发行说明为准，并在实际使用的确切环境中进行测试。
- GitHub 上存在 v3.0.6（2026-04-14）和 v3.0.7（2026-07-09）两个发行版，但截至本次核查，PyPI 上尚无与之对应的构建产物。v3.0.7 更新了 Torch/TorchVision/
  torch-geometric 以及 ONNX 导出代码。不要将这些源码依赖与 3.0.5 的 wheel 包混用。
- ReadTheDocs 的 `/latest` 页面自称版本为 3.0.5。本文中的示例是对照 v3.0.5 的 tag 及 PyPI wheel 元数据核实过的，而非未标注版本的片段。
- 本技能采用 MIT 许可。PathML 本身采用 GPL-2.0 许可，同时上游也提供商业授权选项；在进行再分发之前，请审阅上游条款。

## 可复现的安装方式

除非项目已测试过其他受支持的解释器版本，否则请使用 Python 3.11：

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install "pathml==3.0.5"
python -c "import importlib.metadata as m; print(m.version('pathml'))"
```

PathML 3.0.5 未声明任何软件包附加依赖集（extras）：**不要**使用 `pathml[all]`。其基础发行版锁定了一套庞大的科学计算/机器学习依赖栈，包括 Torch 2.8.0、ONNX 1.17.0、
ONNX Runtime 1.17.x、OpenSlide Python 1.3.1、python-bioformats 4.1.0，以及
python-javabridge 4.0.4。

在执行 uv 命令之前，先安装原生前置依赖：

```bash
# Debian/Ubuntu
sudo apt-get install openslide-tools gcc g++ libblas-dev liblapack-dev openjdk-17-jdk

# macOS
brew install openslide openjdk@17

# Windows OpenSlide option documented upstream
vcpkg install openslide
```

Java/Bio-Formats 是支持广泛多维格式后端所必需的。OpenSlide 能更高效地处理常见的明场全切片图像（WSI）格式。CUDA 是可选项，且必须与锁定的 PyTorch 构建版本匹配；应遵循 PyTorch 官方的平台选择器，而不要凭猜测选用某个 CUDA wheel。参见 `references/image_loading.md`。

## 稳定的最小化工作流

PathML 3.0.5 使用切片便捷类以及 `SlideData.run()`。它并不提供 `SlideData.from_slide()`，`Pipeline` 也没有 `run()` 方法：

```python
from pathml.core import HESlide
from pathml.preprocessing import BoxBlur, Pipeline, TissueDetectionHE

slide = HESlide("data/pseudonymous_slide.svs", backend="openslide")
pipeline = Pipeline(
    [
        BoxBlur(kernel_size=5),
        TissueDetectionHE(mask_name="tissue", min_region_size=5000),
    ]
)
slide.run(
    pipeline,
    distributed=False,
    tile_size=512,
    tile_stride=512,
    level=0,
    tile_pad=False,
)
slide.write("derived/pseudonymous_slide.h5path")
```

在进行完整运行之前，先从一个有边界限制的人工采样开始：

```python
from itertools import islice

for tile in islice(slide.generate_tiles(shape=512, stride=512, level=0), 8):
    pipeline.apply(tile)
    assert tile.masks["tissue"].shape[:2] == tile.image.shape[:2]
```

切片分块使用所选金字塔层级下的 `(i, j)` = `(行, 列)` 坐标。对于 OpenSlide，PathML 会在内部将其映射为第 0 层（level-0）坐标。应记录层级和降采样倍率；在下游需要时，显式转换为 `(x, y)` 坐标或微米单位。

## 研究工作流

1. **在本地建立数据清单**。 校验清单文件，拒绝 URL/符号链接，仅检查白名单内的技术元数据，并移除标识符。
2. **冻结数据划分**。 在生成有重叠的切片分块、图结构、归一化参考，或特征之前，先将每位患者及其全部切片分配到某一个划分（split）中。
3. **规划边界**。 预估切片分块数量、内存占用、输出大小以及流水线各阶段。
4. **试点预处理**。 在具有代表性的训练切片上检查组织掩膜、空白区域/伪影标签、染色表现、边缘补齐（padding）以及空掩膜的情况。不要基于测试切片进行调参。
5. **运行并保留坐标信息**。 保留切片层级、`(i, j)`、降采样倍率、每像素微米数（MPP）、掩膜名称、质控（QC）决策，以及失败/被跳过的切片分块。
6. **审慎地构建空间数据**。 校验通道顺序、物理单位、实例标签、节点特征对齐、图的边，以及细胞与组织的对应关系。
7. **以有边界的批次进行推理**。 在不加载未知 pickle 检查点的前提下核实模型来源和校验和。让预测结果始终与切片/分块坐标保持关联，并按照有明文记录的规则拼接重叠区域。
8. **报告数据来源与局限性**。 应包含依赖锁定文件、源码哈希、扫描仪型号、染色方式、参数、随机种子、数据划分清单、模型卡、排除项以及质控信息。

## 默认不联网与显式同意关卡

除非用户在获知端点信息和披露内容后明确表示同意，否则不要实例化具备下载能力的类，也不要将数据集的 `download=True`：

- `SegmentMIFRemote` 在构造时会从
  `https://huggingface.co/pathml/test/resolve/main/mesmer.onnx` 下载一个 ONNX 文件，随后在本地运行推理。稳定版源码**不会**上传图像像素数据。
  但该请求仍会泄露诸如 IP 地址和请求头之类的网络元数据，并会创建 `temp.onnx` 文件；该功能没有内置的校验和检查或离线模式开关。
- 已弃用的 `SegmentMIF` 会导入本地的 DeepCell Mesmer，但 DeepCell 模型初始化可能需要单独准备权重文件。它不是 PathML 的附加功能，也不是首选的稳定 API。
- `RemoteTestHoverNet` 会从 Hugging Face 下载模型。
- `PanNukeDataModule(download=True)` 会联系 Warwick 大学；`DeepFocusDataModule`
  会联系 Zenodo。二者默认均为 `download=False`。

在未来任何一次调用托管预测服务之前，应说明确切的目标地址、涉及的像素通道/区域、元数据、标识符、保留期限、法律依据以及安全防护措施；获得明确同意；并且默认绝不发送受保护健康信息（PHI）。应优先使用经过审查、带校验和的本地模型文件，并在本地进行推理。

## 模型代码安全

- PyTorch 的 `model.eval()` 指的是让模块进入**评估模式（evaluation mode）**；它不是 Python 那个危险的内置求值函数。绝不要使用 Python 的动态求值或执行功能。
- 不要将本地文件命名为 `pathml.py`、`torch.py`、`onnx.py`，或与标准库同名；被遮蔽（shadow）的模块可能会悄悄改变导入行为。
- PathML 的 `EntityDataset` 在加载 `.pt` 对象时使用的是 `weights_only=False`。绝不要打开不可信的图结构/检查点文件。应将基于 pickle 的流水线和 `.pt` 文件都视为可执行代码来对待。
- ONNX 比 pickle 更安全，但并非天然可信。应核实来源、SHA-256 校验和、预期的输入/输出模式（schema）、文件大小以及运行时限制；对第三方模型应使用隔离环境运行。

## 随附的本地命令行工具

以下所有辅助工具都会拒绝 URL 和符号链接，对输入/工作量设有上限，使用严格的 JSON 格式，避免任何网络访问，并且执行 `--help` 时不需要导入 PathML：

```bash
python scripts/slide_manifest.py validate --manifest manifest.csv --root .
python scripts/slide_manifest.py inspect --slide data/example.svs --root .
python scripts/plan_pipeline.py --width 100000 --height 80000 --tile-size 512 --stride 512
python scripts/image_qc.py synthetic --width 256 --height 256
python scripts/validate_spatial_schema.py graph --input graph.json --root .
python scripts/validate_spatial_schema.py multiplex --input cells.csv --root .
python scripts/plan_inference.py --tile-count 4000 --batch-size 16 --height 256 --width 256
```

推理规划工具只读取数字参数或一个有边界限制的 JSON 模型卡；它绝不会导入任何模型框架，也不会打开任何检查点文件。

## 详细参考资料

- `references/image_loading.md` —— 切片类、后端、格式、层级、
  坐标、技术元数据以及隐私相关内容。
- `references/preprocessing.md` —— 稳定版本的变换操作、掩膜/质控、染色处理、
  流水线执行，以及防止数据泄漏的方法。
- `references/data_management.md` —— `.h5path`、清单文件、数据集、数据溯源、
  数据划分，以及安全下载方式。
- `references/multiparametric.md` —— 多维数据布局、CODEX/Vectra、
  定量分析、AnnData、DeepCell/Mesmer,以及网络访问披露事项。
- `references/graphs.md` —— 实例映射、特征对齐、KNN/RAG/HACT 图结构、
  空间单位、模式（schema）以及校验方法。
- `references/machine_learning.md` —— HoVer-Net/HACTNet、本地 ONNX 推理、
  批处理、检查点信任问题、评估方法，以及模型来源溯源。

## 主要来源

以下资料均已于 2026-07-23 核实：

- PyPI 元数据：https://pypi.org/project/pathml/3.0.5/
- 稳定版源码 tag：https://github.com/Dana-Farber-AIOS/pathml/tree/v3.0.5
- 发行版列表：https://github.com/Dana-Farber-AIOS/pathml/releases
- 稳定版文档：https://pathml.readthedocs.io/en/stable/
- Rosenthal et al. (2022)，PathML 工具包论文：
  https://doi.org/10.1158/1541-7786.MCR-21-0665
- Omar et al. (2025)，多重染色工作流论文：
  https://doi.org/10.1016/j.labinv.2025.104220
