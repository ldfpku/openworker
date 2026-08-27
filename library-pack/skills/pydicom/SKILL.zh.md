# pydicom

使用 pydicom 进行 DICOM 数据集的 I/O 与像素处理。这里评审的是当前的稳定版本 3.0.2。它修复了 CVE-2026-32711,一个精心构造的 DICOMDIR 路径穿越（path-traversal）问题。pydicom 3.0.2 声明所需 Python 版本为 `>=3.10`;其内置的 DICOM 字典版本为 2024c,而现行的 DICOM Standard 可能更新。

## 强制性安全边界

- 只处理用户获得授权可访问的本地数据。
- DICOM 元数据、文件名、私有元素、叠加层（overlays）、结构化内容和像素，都可能包含受保护的健康信息（PHI）。
- 绝不默认 `print(Dataset)`、导出完整的元数据/JSON,或把元素值记入日志。要使用一份有文档记录的白名单，并对输出做聚合处理。
- pydicom 是一个通用的 DICOM 框架，不是诊断查看器。像素输出、校验、格式转换以及插件的可用性，都不构成诊断结论。
- 去标识化（de-identification）是与具体的 profile、用途、接收方、司法辖区以及威胁场景相关的。它需要隐私/DICOM 专家进行核实。
- 绝不能声称某个标签移除脚本符合 DICOM PS3.15、HIPAA、GDPR 或其他合规要求。要保留原始文件，并对衍生输出进行审计。
- 将确定性的假名化密钥和 UID 映射表当作可用于重新识别身份的秘密来对待:遵循最小权限原则，使用加密的/受管理的密钥存储，绝不将其提交到代码库、同步、记入日志，或与衍生产物一起分享；并制定备份、轮换、撤销与销毁流程。密钥一旦泄露，就会破坏原本预期的隔离性；而轮换密钥也会改变确定性映射关系。
- 在解析不受信任或体量异常大的数据集之前，明确设定输入文件数、文件数量、帧数、解码字节数以及输出的限制。

## 安装

创建或激活一个隔离环境，然后安装经过评审的确切版本:

```bash
uv pip install "pydicom==3.0.2"
```

未压缩像素数组与图像渲染所需:

```bash
uv pip install "pydicom==3.0.2" "numpy==2.5.1" "Pillow==12.3.0"
```

只安装部署所需的传输语法（transfer-syntax）插件:

```bash
# JPEG/JPEG-LS, JPEG 2000/HTJ2K, and faster RLE through pylibjpeg
uv pip install "numpy==2.5.1" "pylibjpeg==2.1.0" \
  "pylibjpeg-libjpeg==2.4.0" "pylibjpeg-openjpeg==2.5.0" \
  "pylibjpeg-rle==2.2.0"

# JPEG-LS encoder/decoder
uv pip install "numpy==2.5.1" "pyjpegls==1.5.1"

# Alternative decoder with platform-specific wheels
uv pip install "python-gdcm==3.2.6"
```

不同插件的许可证和 wheel 包因软件包/平台而异；部署前请自行审阅。Pillow 有文档记录的解码限制,pydicom 也提醒:插件的输出结果必须独立进行核验。

原生编解码器 wheel 会扩大供应链和内存安全方面的风险边界。对于受控部署，应在可信的构建主机上锁定这些确切版本号，锁定并校验 wheel 的哈希值/来源，在内部镜像已批准的构件，进行扫描，并以哈希强制校验的方式安装，而不是在运行时从公共索引解析。

## 选择工作流

1. 需要一份聚合概览:运行 `scripts/extract_metadata.py`。
2. 需要有边界限定的技术检查:运行 `scripts/dicom_inventory.py`。
3. 需要编解码器部署前的预检:运行 `scripts/transfer_syntax_inspector.py`。
4. 需要帧/内存规划:运行 `scripts/pixel_frame_planner.py`。
5. 需要渲染出一帧非诊断用途的图像:运行 `scripts/dicom_to_image.py`。
6. 需要一份假名化的衍生数据:先阅读去标识化一节，创建一份经站点评审的行动 profile,然后运行 `scripts/anonymize_dicom.py` 和 `scripts/deidentification_audit.py`。
7. 需要检查一份敏感的 UID 映射表:运行 `scripts/uid_mapping_validator.py`。

## 安全地读取数据集

`dcmread()` 返回一个 `FileDataset`,它是带有 File Format 状态(如 `file_meta`、preamble 以及原始编码)的 `Dataset` 子类。

```python
from pathlib import Path
import pydicom

path = Path("authorized/input.dcm")
ds = pydicom.dcmread(
    path,
    stop_before_pixels=True,
    specific_tags=[
        "SOPClassUID",
        "Modality",
        "Rows",
        "Columns",
        "NumberOfFrames",
    ],
)

technical = {
    "sop_class": ds.get("SOPClassUID"),
    "modality": ds.get("Modality"),
    "rows": ds.get("Rows"),
    "columns": ds.get("Columns"),
}
```

请使用:

- 只处理元数据时用 `stop_before_pixels=True`。
- 需要最小化白名单时用 `specific_tags=[...]`。
- 后续写入需要保留大体积值时用 `defer_size="1 MiB"`。
- `force=False`(默认值)。`force=True` 只是绕过 File Format 的文件头检查；它并不能证明这些字节确实是合法的 DICOM。

不要对临床数据调用 `print(ds)`、`repr(ds)`,或把值迭代记入日志。

## Dataset、DataElement 与序列（sequences）

按关键字访问标准元素，并检查其是否存在:

```python
modality = ds.get("Modality", "UNSPECIFIED")
if "ReferencedImageSequence" in ds:
    for item in ds.ReferencedImageSequence:
        referenced_class = item.get("ReferencedSOPClassUID")
```

按标签访问，比如 `ds[0x0010, 0x0010]`,返回的是一个 `DataElement`;它的 `.value` 是独立的属性。`Sequence` 的行为类似于一个由嵌套 `Dataset` 条目组成的列表。隐私相关的处理动作必须递归遍历每一个序列条目，而不仅仅是顶层。

创建文件时，对 group `0002` 使用 `FileMetaDataset`,保持 dataset 与 file-meta 中的 SOP UID 一致，设置 Transfer Syntax UID,并以强制的 File Format 写入:

```python
from pydicom import dcmwrite
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

meta = FileMetaDataset()
meta.MediaStorageSOPClassUID = CTImageStorage
meta.MediaStorageSOPInstanceUID = generate_uid()
meta.TransferSyntaxUID = ExplicitVRLittleEndian

ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
ds.SOPClassUID = meta.MediaStorageSOPClassUID
ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
# Add all attributes required by the selected IOD before writing.
dcmwrite("new.dcm", ds, enforce_file_format=True, overwrite=False)
```

`write_like_original` 在 pydicom 3.0 中已被弃用；改用 `enforce_file_format`。写入成功并不代表完全符合 PS3.3 IOD 规范。

## UID 与传输语法（transfer syntax）

File Meta Information 中的 Transfer Syntax UID 控制着数据集编码方式和像素压缩方式:

```python
ts = ds.file_meta.TransferSyntaxUID
summary = {
    "uid": str(ts),
    "name": ts.name,
    "compressed": ts.is_compressed,
    "implicit_vr": ts.is_implicit_VR,
    "little_endian": ts.is_little_endian,
}
```

pydicom 3.0 在选择写入编码时，优先依据 Transfer Syntax UID,而非旧版的数据集标志位。在假名化过程中，不要替换结构性 UID(Transfer Syntax、SOP Class 或编码方案 UID)。实例/引用 UID 的替换必须是一一对应的，并且在整个声明的作用范围内保持一致。

在进行压缩、解压缩或封装(encapsulation)之前，请阅读 [references/transfer_syntaxes.md](references/transfer_syntaxes.md)。

## 像素数据与帧

稳定的 `pydicom.pixels` API 支持基于路径的、按帧解码:

```python
from pydicom.pixels import pixel_array

# Reads only the selected frame where the source permits it.
frame = pixel_array("authorized/image.dcm", index=0, raw=False)
```

形状（shape）含义:

- 灰度单帧:`(rows, columns)`
- 灰度多帧:`(frames, rows, columns)`
- 彩色单帧:`(rows, columns, samples)`
- 彩色多帧:`(frames, rows, columns, samples)`

`raw=False` 会在可能的情况下将 YCbCr 像素数据转换为 RGB;`raw=True` 则在经过强制性的最小处理后，保留解码出来的原始色彩空间。要进行有边界限定的多帧迭代，使用 `iter_pixels(path, indices=[...])`。

对于灰度显示，应按以下顺序应用变换:

```python
from pydicom.pixels import apply_modality_lut, apply_voi_lut

modality_values = apply_modality_lut(frame, ds)
display_values = apply_voi_lut(modality_values, ds, index=0)
```

Modality LUT/rescale 以及 VOI/windowing 会改变显示/数值的语义。MONOCHROME1 可能需要做呈现反转(presentation inversion)。Palette Color 需要用 `apply_color_lut()`。呈现状态(presentation states)和 ICC 行为可能需要经过验证的查看器来处理。绝不要在定量分析中使用逐帧的最小/最大值归一化。

## 压缩、解压缩与封装

- 访问 `pixel_array` 会按需解码，但不会改变数据集本身。
- `Dataset.decompress()` 会原地改变 Pixel Data,将其设为 Explicit VR Little Endian,更新图像元数据，并且默认会生成一个新的 SOP Instance UID。
- `Dataset.compress(uid)` 会原地改变 Pixel Data 和 Transfer Syntax,并且默认会生成一个新的 SOP Instance UID。
- pydicom 3.0 内置/可发现的编码器覆盖了稳定插件矩阵中记录的 RLE Lossless、JPEG-LS 以及 JPEG 2000 组合。
- 每一个压缩帧都是单独编码后再进行封装的。对于外部编码的帧，使用 `encapsulate()` 或 `encapsulate_extended()`。
- 用当前的 `pydicom.encaps.generate_frames()` 或 `get_frame()` 来读取帧；旧版的封装生成器名称在 pydicom 4 中已被弃用。

始终先检查功能可用性，限制解码的字节数/帧数，并独立验证像素的正确性。有损压缩是否可接受，超出了 pydicom 和 DICOM 编码规范本身所能判定的范围。

## DICOM JSON 与私有元素

`Dataset.to_json()`、`to_json_dict()` 以及 `Dataset.from_json()` 实现了 DICOM JSON Model,但 pydicom 的文档将 JSON 支持标记为 beta 阶段。完整 JSON 可能会内联二进制数据，并暴露出每一个标识符和像素负载。不要把它当作元数据报告输出。`BulkDataURI` 处理器会引入独立的存储、授权和检索方面的义务。

私有元素并未被标准化，可能包含 PHI:

```python
# Recursive removal, but not sufficient de-identification by itself.
ds.remove_private_tags()
```

只有在明确的、经过评审的安全私有(safe-private)策略之下，才保留私有元素。关于标签访问、隐私分类以及标准指引，请阅读 [references/common_tags.md](references/common_tags.md)。

## 去标识化工作流

DICOM PS3.15 附录 E 明确指出，保密 profile 并不保证移除所有可识别身份的信息，也不能替代一个完整的去标识化流程。

1. 明确用途、接收方、关联(linkage)需求、适用法规、威胁模型，以及可接受的重新识别风险。
2. 选择 Basic Application Level Confidentiality Profile 以及所需的选项(像素、可识别的视觉特征、图形、结构化内容、描述符、时间信息、患者特征、设备、机构、UID,以及安全私有数据)。
3. 在受控存储中保留源对象、不做改动。
4. 递归地应用每一个操作，包括嵌套的序列。
5. 在整个作用范围内一致地替换实例/引用 UID;保留结构性 UID 不变。
6. 明确决定日期/时间的处理方式。固定的时间偏移可以保留时间间隔，但部分日期、时区、独立的时间字段、闰日、纵向关联，以及外部事件，都需要经过评审的策略来处理。
7. 检查像素、叠加层、图形、结构化内容以及可识别的视觉特征。不要仅凭元数据缺失就推断像素是"干净"的，也不要在未经核实的情况下将 `BurnedInAnnotation` 设为 `NO`。
8. 重建 File Meta Information 和 preamble,以防止信息泄露。
9. 运行技术校验和去标识化审计，然后进行专家核实和有文档记录的风险评审。

随附脚本刻意将 `PatientIdentityRemoved` 设为 `NO`,因为它无法确认去标识化已成功完成。

## 辅助 CLI 工具

所有 `--help` 路径都不依赖外部库。这些工具不进行任何网络访问，也不会输出超出狭义技术白名单范围的 DICOM 值。

随附内容包括这两份链接的参考文档、有文档记录的辅助脚本，以及合成测试数据。pydicom 运行时依赖是从锁定版本的 PyPI 发行版安装的。

```bash
# Redacted aggregate metadata
python scripts/extract_metadata.py authorized/ --recursive

# Metadata-only technical inventory
python scripts/dicom_inventory.py authorized/ --recursive

# Installed codec/plugin capabilities
python scripts/transfer_syntax_inspector.py --input authorized/image.dcm

# Frame shape, byte, and transform plan
python scripts/pixel_frame_planner.py authorized/image.dcm --frames 0,2-4

# One non-diagnostic frame
python scripts/dicom_to_image.py authorized/image.dcm frame.png \
  --acknowledge-pixel-phi

# Create a secret key, then a scoped pseudonymized derivative plus audit
python scripts/anonymize_dicom.py --generate-uid-key project.key
python scripts/anonymize_dicom.py authorized/in.dcm derived/out.dcm \
  --uid-key-file project.key --uid-scope export-v1 \
  --audit-report derived/out.audit.json

# Audit candidate metadata; no pixel decompression
python scripts/deidentification_audit.py derived/out.dcm

# Validate an explicitly requested sensitive UID mapping
python scripts/uid_mapping_validator.py derived/uid-map.json \
  --uid-key-file project.key --uid-scope export-v1
```

生成的原始密钥文件只是一种受控的本地便利手段，创建时权限仅限于所有者本人。在生产环境中，应从经批准的密钥管理器中把密钥字节实体化到一个已锁定的临时文件中，把访问权限限制在去标识化服务范围内，并在事后安全地删除它。任何可选的 UID 映射表都应与衍生数据分开存储；它直接把原始标识符和替换标识符关联了起来。

## pydicom 3.0 迁移说明

- `read_file()` 和 `write_file()` 已被移除；改用 `dcmread()` 和 `dcmwrite()`。
- `write_like_original` 已被弃用；改用 `enforce_file_format`。
- `pydicom.pixel_data_handlers` 已被标记为将在 v4 中移除；改用 `pydicom.pixels`。
- `Dataset.pixel_array` 默认使用新的 pixels 后端，并在可能的情况下将 YCbCr 转换为 RGB。
- `JPEGLossless` 现在指的是 UID `1.2.840.10008.1.2.4.57`;`JPEGLosslessSV1` 是 `.70`。
- `Dataset.is_little_endian` 和 `is_implicit_VR` 已被标记为将在 v4 中弃用。

## 参考来源(已于 2026-07-23 核实)

- [pydicom 3.0.2 on PyPI](https://pypi.org/project/pydicom/) —— 发布于 2026-03-19;要求 Python `>=3.10`。
- [pydicom releases](https://github.com/pydicom/pydicom/releases) —— 3.0.2 版本及 CVE-2026-32711 详情。
- [Stable release notes](https://pydicom.github.io/pydicom/stable/release_notes/index.html)
- [Stable installation guide](https://pydicom.github.io/pydicom/stable/tutorials/installation.html)
- [Dataset basics](https://pydicom.github.io/pydicom/stable/tutorials/dataset_basics.html)
- [Stable pixel tutorial](https://pydicom.github.io/pydicom/stable/tutorials/pixel_data/introduction.html)
- [Stable pixel plugins](https://pydicom.github.io/pydicom/stable/guides/user/image_data_handlers.html)
- [Stable compression tutorial](https://pydicom.github.io/pydicom/stable/tutorials/pixel_data/compressing.html)
- [Stable DICOM JSON tutorial](https://pydicom.github.io/pydicom/stable/tutorials/dicom_json.html)
- [Stable private-element guide](https://pydicom.github.io/pydicom/stable/guides/user/private_data_elements.html)
- [Current DICOM Standard](https://www.dicomstandard.org/current)
- [DICOM PS3.3](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/PS3.3.html),
  [PS3.5](https://dicom.nema.org/medical/dicom/current/output/chtml/part05/PS3.5.html),
  [PS3.6](https://dicom.nema.org/medical/dicom/current/output/chtml/part06/PS3.6.html),
  and [PS3.15](https://dicom.nema.org/medical/dicom/current/output/html/part15.html)
