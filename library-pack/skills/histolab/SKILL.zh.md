# Histolab

## 概述

Histolab 是一个用于处理数字病理学中全视野切片图像（whole slide image,WSI）的 Python 库。它能自动完成组织检测，从千兆像素级图像中提取信息丰富的图块（tile）,并为深度学习流水线准备数据集。该库支持多种 WSI 格式，实现了精细的组织分割，并提供了灵活的图块提取策略。

## 安装

先安装 OpenSlide 系统库（[OpenSlide 下载](https://openslide.org/download/)）,然后再安装 histolab:

```bash
uv pip install histolab
```

若要通过 `histolab.data` 使用内置的 TCGA 示例切片，还需安装 pooch:

```bash
uv pip install pooch
```

Histolab 0.7.0（最新稳定版）支持 Linux 和 macOS 上的 Python 3.8–3.11。截至 0.7.0,不支持 Windows。

## 快速入门

从全视野切片图像中提取图块的基本工作流程:

```python
from histolab.slide import Slide
from histolab.tiler import RandomTiler

# Load slide
slide = Slide("slide.svs", processed_path="output/")

# Configure tiler
tiler = RandomTiler(
    tile_size=(512, 512),
    n_tiles=100,
    level=0,
    seed=42
)

# Preview tile locations
tiler.locate_tiles(slide, n_tiles=20)

# Extract tiles
tiler.extract(slide)
```

## 核心能力

以下六个能力领域，均配有对应的示例代码，详细记录在
[references/core_capabilities.md](references/core_capabilities.md) 中:

1. **切片管理** —— 打开切片、属性、层级（level）、缩略图以及缩放后的图像。
2. **组织检测与掩膜** —— `TissueMask` 和 `BiggestTissueBoxMask`,以及自定义掩膜。
3. **图块提取** —— 支持随机、网格以及基于评分的图块提取器（tiler）,可控制大小、层级和组织占比。
4. **滤镜与预处理** —— 图像滤镜与形态学滤镜，以及它们的组合方式。
5. **染色归一化** —— 相对于目标图像进行 Reinhard 和 Macenko 归一化。
6. **可视化** —— 在切片上定位图块，并检查掩膜和提取结果。

五个端到端工作流见
[references/typical_workflows.md](references/typical_workflows.md)。各主题的详细内容分别位于
[references/slide_management.md](references/slide_management.md)、
[references/tissue_masks.md](references/tissue_masks.md)、
[references/tile_extraction.md](references/tile_extraction.md)、
[references/filters_preprocessing.md](references/filters_preprocessing.md) 以及
[references/visualization.md](references/visualization.md)。

## 最佳实践

### 切片加载与检查
1. 在处理之前，始终先检查切片属性
2. 使用 `slide.thumbnail.save()` 保存缩略图，以便快速目视检查
3. 检查金字塔层级和尺寸
4. 用缩略图确认组织确实存在

### 组织检测
1. 在提取之前，先用 `locate_mask()` 预览掩膜
2. 多个切片区域用 `TissueMask`,单个切片区域用 `BiggestTissueBoxMask`
3. 针对特定染色方式（H&E vs IHC）自定义滤镜
4. 用自定义掩膜处理笔迹标注
5. 在多种不同的切片上测试掩膜

### 图块提取
1. **在提取之前，始终先用 `locate_tiles()` 预览**
2. 选择合适的图块提取器（tiler）:
   - RandomTiler:用于抽样和探索
   - GridTiler:用于完整覆盖
   - ScoreTiler:用于基于质量的选取
3. 设置合适的 `tissue_percent` 阈值（通常为 70-90%）
4. 在 RandomTiler 中使用固定的随机种子以保证可复现性
5. 按分析所需的分辨率，在合适的金字塔层级上提取
6. 对于大型数据集，启用日志记录

### 性能
1. 在较低层级（1、2）提取以加快处理速度
2. 在合适的情况下，优先使用 `BiggestTissueBoxMask` 而非 `TissueMask`
3. 调整 `tissue_percent` 以减少无效的图块尝试
4. 在初步探索阶段限制 `n_tiles`
5. 对非重叠网格使用 `pixel_overlap=0`

### 质量控制
1. 验证图块质量（检查模糊、伪影、对焦情况）
2. 检查 ScoreTiler 的评分分布
3. 检查评分最高和最低的图块
4. 监控组织覆盖率统计信息
5. 如有需要，用额外的质量指标对已提取的图块进行过滤

## 常见使用场景

### 训练深度学习模型
- 在多个切片上使用 RandomTiler 提取均衡的数据集
- 使用配合 NucleiScorer 的 ScoreTiler,聚焦于富含细胞的区域
- 以一致的分辨率提取（层级 0 或层级 1）
- 生成 CSV 报告以追踪图块元数据

### 全切片分析
- 使用 GridTiler 实现完整的组织覆盖
- 在多个金字塔层级上提取，以进行分层分析
- 通过网格位置保持空间关系
- 使用 `pixel_overlap` 实现滑动窗口方式

### 组织表征
- 用 RandomTiler 对多样化区域进行采样
- 用掩膜量化组织覆盖率
- 用 HED 分解提取染色特异性信息
- 跨切片比较组织模式

### 质量评估
- 用 ScoreTiler 识别最佳对焦区域
- 用自定义掩膜和滤镜检测伪影
- 评估整个切片集合中的染色质量
- 标记有问题的切片以供人工复查

### 数据集整理
- 用 ScoreTiler 优先选取信息量大的图块
- 按组织占比过滤图块
- 生成包含图块评分和元数据的报告
- 跨切片和组织类型创建分层数据集

## 故障排查

### 未提取到任何图块
- 降低 `tissue_percent` 阈值
- 确认切片中确实含有组织（检查缩略图）
- 确保 extraction_mask 覆盖了组织区域
- 检查 tile_size 是否与切片分辨率相匹配

### 出现大量背景图块
- 启用 `check_tissue=True`
- 提高 `tissue_percent` 阈值
- 使用合适的掩膜（TissueMask vs BiggestTissueBoxMask）
- 自定义掩膜滤镜以更好地检测组织

### 提取速度非常慢
- 在较低的金字塔层级提取（level=1 或 2）
- 对 RandomTiler/ScoreTiler 减少 `n_tiles`
- 抽样时使用 RandomTiler 而非 GridTiler
- 使用 BiggestTissueBoxMask 而非 TissueMask

### 图块中出现伪影
- 实现自定义的标注排除掩膜
- 调整滤镜参数以去除伪影
- 提高小对象去除的阈值
- 应用提取后的质量过滤

### 各切片之间结果不一致
- 对 RandomTiler 使用相同的随机种子
- 用 `MacenkoStainNormalizer` 或 `ReinhardStainNormalizer` 对染色进行归一化
- 按染色质量调整 `tissue_percent`
- 实现针对特定切片的掩膜自定义

## 资源

本技能在 `references/` 目录中包含详细的参考文档:

### references/slide_management.md
关于加载、检查和处理全视野切片图像的完整指南:
- 切片初始化与配置
- 内置示例数据集
- 切片属性与元数据
- 缩略图生成与可视化
- 处理金字塔层级
- 多切片处理工作流
- 最佳实践与常见模式

### references/tissue_masks.md
关于组织检测与掩膜处理的完整文档:
- TissueMask、BiggestTissueBoxMask、BinaryMask 类
- 组织检测滤镜的工作原理
- 用滤镜链自定义掩膜
- 可视化掩膜
- 创建自定义矩形掩膜和标注排除掩膜
- 与图块提取的集成
- 最佳实践与故障排查

### references/tile_extraction.md
关于图块提取策略的详细说明:
- RandomTiler、GridTiler、ScoreTiler 的对比
- 可用的评分器（NucleiScorer、CellularityScorer,以及自定义评分器）
- 通用参数与策略特有参数
- 用 locate_tiles() 预览图块
- 提取工作流与 CSV 报告
- 高级模式（多层级、分层)
- 性能优化
- 常见问题的故障排查

### references/filters_preprocessing.md
完整的滤镜参考与预处理指南:
- 图像滤镜（颜色转换、阈值处理、对比度)
- 形态学滤镜（膨胀、腐蚀、开运算、闭运算)
- 滤镜的组合与链式调用
- 内置的染色归一化（Macenko、Reinhard）以及基于滤镜的替代方案
- 常见的预处理流水线
- 对图块应用滤镜
- 自定义掩膜滤镜
- 质量控制滤镜
- 最佳实践与故障排查

### references/visualization.md
全面的可视化指南:
- 切片缩略图的显示与保存
- 掩膜可视化技巧
- 图块位置预览
- 显示已提取的图块并创建拼接图（mosaic）
- 质量评估可视化
- 多切片对比
- 滤镜效果可视化
- 导出高分辨率图和 PDF
- 在 Jupyter notebook 中进行交互式可视化

**使用方式**： 参考文件包含深入的信息，用于支持本主技能文档中所描述的工作流程。按需加载具体的参考文件，以获取详细的实现指导、故障排查方法或高级功能说明。
