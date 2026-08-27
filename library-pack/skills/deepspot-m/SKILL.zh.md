# DeepSpot-M

## 概述

DeepSpot-M 是一个多模态基础模型，能够把一张 224x224 的 H&E 组织学切片图块(tile)映射为 log1p-CPM 形式的空间基因表达。其输出是虚拟空间转录组学(virtual spatial transcriptomics)数据:每个被查询的基因在每个图块上对应一个数值，按图块原本所在的网格排布。

一个经过 LoRA 适配的病理学基础模型骨干网络(Midnight)对图块进行分词(tokenise)。一个交叉注意力(cross-attention)基因解码器让每个基因查询都能关注到图块的 token,而一个基因路由(gene router)超网络则从冻结的生物学嵌入(Evo 2、Orthrus、ProtT5、scGPT、Apertus)中构建出特定于基因的投影。基因是作为可查询的嵌入进入模型的，而不是固定的输出槽位，所以已发布的模型覆盖了一个约 1.9 万个蛋白质编码基因的基因面板(panel),其中包括训练时未见过的基因。该面板随权重一起发布，以 `tokens.csv` 的形式提供，并通过 `model.gene_names` 暴露出来；不在该面板中的基因在本版本中无法被查询。

将该模型应用于 TCGA 数据集后，产出了一个覆盖 32 种癌症类型、共 28,664 张切片的虚拟空间转录组学图谱。

## 许可协议

代码采用 PolyForm Noncommercial 1.0.0 协议，权重采用 CC-BY-NC-SA-4.0 协议。仅可将其用于非商业性研究，并在重新分发输出结果之前检查这两份许可协议。

## 安装

```bash
uv pip install deepspotm==1.0.0
```

1.0.0 版本面向 Python 3.10 到 3.13,并会引入 PyTorch。如果想要使用 GPU 推理，请先安装与你的 CUDA 版本相匹配的 PyTorch 构建版本。

## 模型访问

权重是受限访问(gated)的:

1. 打开 <https://huggingface.co/ratschlab/DeepSpotM> 并申请访问权限。
2. 一旦获得访问权限，为将要下载权重的机器完成身份验证:

```bash
huggingface-cli login
```

`from_pretrained` 会读取该缓存的令牌(token),所以每台机器只需要登录一次。

## 快速开始

```python
from deepspotm import DeepSpotM

model, image_processor = DeepSpotM.from_pretrained("ratschlab/DeepSpotM", source="scgpt")

vals = model.predict_genes(image_processor(pil_tile).unsqueeze(0), ["EPCAM", "CD3D"])
```

`pil_tile` 是一张精确为 224x224 像素的 PIL 图像。`image_processor` 把它转换为张量,`unsqueeze(0)` 添加批次维度，而 `predict_genes` 接收该批次数据以及一份 HGNC 基因符号列表。返回的数值是 log1p-CPM 形式，并与你传入的基因列表一一对应，所以要把这份列表和输出结果放在一起，以保持每一列都有标签可查。基因符号必须在已发布的约 1.9 万基因面板中(`model.gene_names`);未知的符号会引发 `KeyError`,并在其中指出是哪些基因出了问题。

## 图块要求

图块必须是 224x224 的 RGB 图像，放大倍率大约为 20 倍(约每像素 0.5 微米)。应在你流水线的边界处检查图块尺寸，而不是把未经检查的裁剪图直接传入:

```python
TILE_PX = 224

def require_tile(tile):
    """Return an RGB 224x224 tile, or raise if the crop is the wrong size."""
    if tile.size != (TILE_PX, TILE_PX):
        raise ValueError(
            f"DeepSpot-M expects a {TILE_PX}x{TILE_PX} tile at about 20x "
            f"(~0.5 microns per pixel); got {tile.size[0]}x{tile.size[1]}. "
            "Re-tile at the matching level or resample the crop."
        )
    return tile.convert("RGB")
```

在分辨率最接近每像素 0.5 微米的那一级切片层级上提取图块，然后在该层级上裁剪为 224x224。从更粗糙的层级重采样会改变骨干网络所读取到的纹理特征。

## 保持该依赖为可选项

`deepspotm` 及其权重是一个体积较大、受限访问的依赖项。应在需要它的函数内部导入它，这样周边项目在没有它的情况下也能正常安装、导入和测试，并把 `ImportError` 转换为一条列出每个所需步骤的提示信息:

```python
DEEPSPOTM_HELP = (
    "DeepSpot-M is unavailable. Install it with `uv pip install deepspotm==1.0.0`, request "
    "access to the gated weights at https://huggingface.co/ratschlab/DeepSpotM, then "
    "authenticate with `huggingface-cli login`."
)

def load_deepspotm(source="scgpt"):
    try:
        from deepspotm import DeepSpotM
    except ImportError as exc:
        raise RuntimeError(DEEPSPOTM_HELP) from exc
    return DeepSpotM.from_pretrained("ratschlab/DeepSpotM", source=source)
```

## 嵌入来源

`source` 参数决定路由从哪一种冻结的基因嵌入来构建投影。它是以下五个值之一:

| `source`  | 基因嵌入                    |
| --------- | --------------------------------- |
| `evo2`    | 基因组序列                  |
| `orthrus` | RNA                                |
| `prott5`  | 蛋白质序列                  |
| `scgpt`   | 单细胞表达                  |
| `apertus` | 语言模型                    |

每一种都提供了基因身份的一种不同视角。每次运行选一种，当选择对你的分析结果有影响时，用同一批图块分别跑多个来源做对比。关于完整的调用接口、批处理和设备放置、基因符号处理以及输出单位，参见 `references/api.md`。

## 全切片工作流

预测是逐图块进行的，所以一次切片规模的运行等于"切图"步骤加上批量推理:

1. 用 `histolab` 技能按网格提取 224x224 的图块，并保留每个图块的坐标。
2. 用 `torch.stack` 处理图块并将其堆叠成批次。
3. 用同一份基因列表，对每个批次调用一次 `predict_genes`。
4. 把各批次的结果拼接成一个"图块 x 基因"矩阵，并附上坐标信息。

这个矩阵就是该切片的虚拟空间转录组学图谱，可以直接放入 `AnnData` 中供下游空间分析使用。`references/whole_slide.md` 中提供了一个完整的示例循环、批大小设置，以及 `AnnData` 组装步骤。

## 常见用例

- 为肿瘤切片中的标志物基因绘制空间表达图谱。
- 在没有配套实验数据的切片队列上进行全转录组预测。
- 按符号查询约 1.9 万基因面板中的任意基因，包括训练时未见过的基因——远远超出典型空间分析面板中的几百个基因。
- 为纯形态学的组织学流水线增加一个表达通道。
- 构建切片级的队列图谱，正如在 TCGA 数据集上所做的那样。

## 详细参考文档

- `references/api.md`:完整的 `from_pretrained` 和 `predict_genes` 说明、五种嵌入来源及其选择方式、批处理、设备放置、基因符号处理，以及 log1p-CPM 输出的转换方式。
- `references/whole_slide.md`:用 histolab 做切图、一个切片规模的预测循环、组装并存储"图块 x 基因"矩阵，以及队列规模的运行方式。

## 主要来源

- 论文:<https://doi.org/10.64898/2026.06.19.26356060>(medRxiv,发布于 2026 年 6 月 22 日)
- 代码:<https://github.com/ratschlab/DeepSpotM>
- 权重:<https://huggingface.co/ratschlab/DeepSpotM>
- PyPI:<https://pypi.org/project/deepspotm/>
