# Scientific Visualization（科学可视化）

用 Matplotlib、Seaborn 或 Plotly 构建保留了科学含义、并在此基础上优化外观的图表。要将普遍适用的原则与已经过时的出版商规则区分开，保留原始数据与各项变换，冗余地使用颜色编码，并且要检查实际交付的文件本身，而不是相信绘图库的默认设置。

## 不可妥协的底线

- 绝不为了让图表更好看而改动、隐藏、编造或选择性地强化数据。
- 保留原始表格/图像、剔除的数据点、缺失值编码方式、分析代码、归一化方法、分箱（binning）方式、图像调整以及随机种子。
- 不要凭空推测期刊的要求。明确目标期刊、文章类型、图表类型和投稿阶段，并核实其现行的官方指南。
- 不要声称某种配色方案、DPI 数值、文件格式或自动化报告能使一张图具备可访问性或符合期刊要求。
- 不要悄悄地连接缺失的观测点、隐藏不利的数据点、把图像上采样后当作细节增加了，也不要通过调整坐标轴/双坐标轴来夸大某个结论。
- 将交互式输出和静态输出作为两种独立的交付物来对待。交互式悬停提示不能替代标签、替代文字（alt text）、键盘可访问性、可访问的数据表格，或一份静态版本的备份。

关于欺骗性编码和诚信性检查，请阅读 `references/publication_guidelines.md`。只有在明确了目标期刊和投稿阶段之后，才去阅读 `references/journal_requirements.md`。

## 工作流程

### 1. 明确证据内容与投放目的地

记录以下内容：

- 受众和媒介：手稿、网页、幻灯片、海报，还是补充材料；
- 确切的出版商/期刊、文章类型、投稿阶段，以及最终打算使用的宽度；
- 变量的语义、单位、样本/重复的结构、缺失/删失（censored）值；
- 所用的估计量及不确定性的定义；
- 各项变换：筛选、聚合、归一化、平滑、分箱、图像处理；
- 源数据的路径/标识符，以及输出结果的来源信息（provenance）。

如果要求尚不明确，先创建一份临时的通用版图表，并将所有与出版商相关的选择标注为"待核实"。

### 2. 选择诚实的编码方式

优先使用同一尺度上的位置来编码数据。在编码之前先检查以下事项：

- **柱状图/面积图**： 通常应包含零点，因为长度/面积是从某个基线量起的。
- **点图/线图**： 非零的坐标轴范围也可以是合理的；应展示上下文并说明坐标轴断点。
- **不确定性**： 明确标注是 SD（标准差）、SE（标准误）、CI（置信区间）、百分位数、后验分布，还是其他类型的区间；并说明 `n` 和重复的计量单位。
- **原始观测值**： 尽可能展示原始观测点；不要让抖动（jitter）掩盖了类别/数值信息。
- **缺失数据**： 区分缺失、零值、删失和被剔除这几种情况；使用留白或明确的模型/插值样式来标示。
- **面积/体积**： 应对面积/体积本身进行缩放，而不是对半径/直径进行缩放；避免使用装饰性的 3D 效果。
- **对数坐标轴**： 标注所用的底数/变换方式，并说明零值/负值是如何处理的。
- **分箱/平滑**： 记录分箱边界、带宽/窗口大小、所用方法，以及对参数的敏感性。
- **归一化**： 说明所用公式/参照基准，并在相互比较的各个子图之间保持一致的坐标轴范围。
- **双坐标轴**： 优先使用对齐的多个子图；如果确实无法避免使用双轴，需说明所用单位的合理性，且不得刻意制造表面上的相关性。
- **图像**： 保留原始图像、公开说明对整幅图像所做的调整、展示比例尺，并避免裁切或抹除背景。

### 3. 从一开始就将可访问性纳入设计，而非事后补救

- 同时使用颜色加标记形状、线型、阴影填充、直接标注或子图分隔等多重编码方式。
- 根据数据的语义选择定性（qualitative）、顺序（sequential）、发散（diverging）或循环（cyclic）配色方案。
- 在实际渲染尺寸下核查前景/背景的对比度。
- 明确标示缺失值和超出范围的数值。
- 为网页发布的图表提供替代文字（alt text）、针对复杂图表的更详细说明，以及底层数据。
- 将 WCAG 2.2 视为网页方面的指导标准：普通文字需要 4.5:1、大号文字需要 3:1，理解图表所必需的图形对象也需要 3:1 的对比度；颜色不能是唯一的辨识线索。适用范围和例外情形也需留意。

参见 `references/color_palettes.md`。灰度屏幕测试很有用，但它并不是一套完整的色觉或可访问性测试。

### 4. 用作用域受限的样式来实现

使用 Matplotlib 的面向对象 API 以及临时的样式上下文（style context）：

```python
import matplotlib.pyplot as plt

from style_presets import style_context

with style_context("default", palette_name="okabe_ito_on_white"):
    fig, ax = plt.subplots(
        figsize=(89 / 25.4, 60 / 25.4),
        layout="constrained",
    )
    ax.plot(x, y, marker="o", label="Observed")
    ax.set(xlabel="Time (hours)", ylabel="Response (unit)")
    ax.legend()
```

`layout="constrained"` 支持颜色条（colorbar）、嵌套 GridSpec、子图集合（subfigures）,以及 `subplot_mosaic`。之后不要再调用 `tight_layout()`；它会禁用 constrained layout。

如果需要精确的物理尺寸，除非有意想改变页面大小，否则不要使用 `bbox_inches="tight"`。

#### 颜色归一化

```python
import matplotlib as mpl

norm = mpl.colors.TwoSlopeNorm(vmin=-2, vcenter=0, vmax=5)
cmap = mpl.colormaps["RdBu_r"].with_extremes(bad="#777777")
image = ax.imshow(values, norm=norm, cmap=cmap, interpolation="nearest")
fig.colorbar(image, ax=ax, label="Change (unit)")
```

只有当 `LogNorm`、`CenteredNorm`、`SymLogNorm`、`BoundaryNorm` 或 `TwoSlopeNorm` 的映射方式与科学含义相符时才使用它们。

#### Seaborn

Seaborn 0.13.2 使用当前的 `errorbar` API：

```python
sns.lineplot(
    data=frame,
    x="time",
    y="response",
    hue="treatment",
    style="treatment",
    markers=True,
    errorbar=("ci", 95),
    n_boot=5000,
    seed=20260723,
    ax=ax,
)
```

坐标轴层级（axes-level）的函数适配自定义的 Matplotlib 版面；图形层级（figure-level）的函数会创建自己的图形/分面（facet）。不要把 Seaborn 内部的 artist 列表当作稳定的 API 来自定义。

#### Plotly

- 交互式输出使用 `write_html()`，静态输出使用 `write_image()`/`plotly.io.write_images()`。
- Kaleido 1.3.0 需要 Chrome/Chromium；它不再内置捆绑 Chrome。
- 当前支持的静态格式：PNG、JPEG、WebP、SVG、PDF。EPS 仅在 Kaleido v0 中支持。
- 不要传入已弃用的 `engine=` 参数，也不要使用 Orca 或 `plotly.io.kaleido.scope`。
- `width`、`height` 和 `scale` 控制的是像素数；`scale=3` 并不天然等同于"300 DPI"。
- WebGL 轨迹（trace）在导出为 PDF/SVG 时会内嵌栅格内容。
- 当图表引用了 MathJax/topojson/瓦片图（tiles）时，要实现完全离线导出还需要本地的外部资源文件。

### 5. 显式导出并记录来源信息（provenance）

```python
from figure_export import export_figure

report = export_figure(
    fig,
    "outputs/figure1",
    formats=["pdf", "png"],
    dpi=600,
    bbox_inches=None,  # preserve figure page dimensions
    provenance={
        "raw_data": "data/source.csv",
        "transformations": ["predeclared QC filter", "group mean"],
        "uncertainty": "95% bootstrap CI; seed 20260723",
        "missing_data": "retained as gaps",
    },
    write_manifest=True,
)
```

该导出工具拒绝隐式覆盖已有文件、以原子方式写入、为内嵌的栅格图像保留矢量级 DPI、使用 TIFF LZW 压缩，并且可以使用 PDF/PS 的 Type 42 字体。它不会校验科学内容的正确性，也不会校验是否符合出版商的要求。

关于可编辑字体：

- PDF/PS 的 Type 42 会内嵌 TrueType 字体。
- `svg.fonttype="none"` 会使文字保持可编辑/可搜索，但不会内嵌字体；显示效果取决于系统已安装的字体。
- `svg.fonttype="path"` 会将字形外观保留为路径，但会失去可编辑/可搜索的文字。

除非确实需要透明效果，否则请使用明确的不透明背景；与其他背景叠加混合会改变表观对比度。

### 6. 检查、比对与复核

1. 检查文件的元数据。
2. 审核配色方案的对比度/灰度区分度。
3. 与某个有明确日期的出版商规范快照进行比对。
4. 在手稿/网页的实际使用场景中，以最终尺寸查看效果。
5. 人工复核字体、内嵌的栅格图像、裁切情况、图例、比例尺、图像完整性、图注、替代文字以及源数据。
6. 在上传之前，立即重新查看目标期刊当前的官方页面。

## 固定的版本快照

示例和冒烟测试（smoke test）使用截至 2026-07-23 的直接依赖固定版本：

```bash
uv run --isolated --no-project --python 3.13 \
  --with "matplotlib==3.11.1" \
  --with "seaborn==0.13.2" \
  --with "plotly==6.9.0" \
  --with "kaleido==1.3.0" \
  --with "pillow==12.3.0" \
  --with "pypdf==6.14.2" \
  python your_figure.py
```

这只是一份有明确日期的直接依赖快照，而不是一份传递依赖（transitive）锁定文件。若要精确复现，请使用项目自身的 uv lock 文件；本技能有意不附带依赖锁定文件。

## 附带的命令行工具（CLI）

所有辅助工具都是确定性的、不联网的、有边界限制的，在相关场景下会拒绝符号链接（symlink）形式的输入/输出路径，并且除非显式传入 `--force`，否则会拒绝覆盖已有文件。

### 检查栅格/矢量图元数据

```bash
uv run --isolated --no-project --python 3.13 \
  --with "pillow==12.3.0" \
  python scripts/image_metadata.py figure.tiff \
  --format tiff --mode RGB --min-dpi 300 --target-width-mm 85 \
  --alpha-policy forbid
```

支持栅格图像（Pillow）、SVG、PDF（pypdf）以及 EPS/PS。报告内容包括尺寸、DPI/有效 DPI、色彩模式、alpha 通道、ICC 配置文件是否存在、压缩方式、页面大小，以及较为保守的 PDF 首页字体资源信息。它不会检查矢量容器中每一个内嵌的栅格图像。

### 审核配色方案的对比度与灰度表现

```bash
uv run --isolated --no-project --python 3.13 \
  python scripts/palette_audit.py \
  --palette okabe_ito_on_white \
  --background FFFFFF \
  --role graphical
```

报告精确的 WCAG sRGB 对比度，以及成对比较的 CIE L* 灰度筛查结果。灰度阈值是一种经验性的启发式判断，而非一项标准。

### 规划/筛查出版商导出要求

```bash
uv run --isolated --no-project --python 3.13 \
  python scripts/export_plan.py \
  --publisher nature \
  --figure-type combination \
  --width single \
  --phase final
```

加上 `--input figure.pdf` 可筛查机器可读的属性。这些配置文件是截至 2026-07-23 访问的官方来源快照，而不是自动合规规则。

### 预览样式

```bash
uv run --isolated --no-project --python 3.13 \
  --with "matplotlib==3.11.1" \
  python scripts/style_preview.py \
  --output outputs/style-preview \
  --style default \
  --palette okabe_ito_on_white \
  --formats png,svg
```

### 检查/写入样式，以及导出冒烟测试

```bash
uv run --isolated --no-project --python 3.13 \
  python scripts/style_presets.py --list
uv run --isolated --no-project --python 3.13 \
  python scripts/style_presets.py --show nature
uv run --isolated --no-project --python 3.13 \
  --with "matplotlib==3.11.1" \
  python scripts/figure_export.py --demo outputs/export-smoke --manifest
```

## 附带资源（Assets）

- `assets/publication.mplstyle`：通用的印刷版起始样式。
- `assets/nature.mplstyle`：一份有明确日期的、以 Nature 旗舰视觉风格为起点的样式，并非合规预设。
- `assets/presentation.mplstyle`：适用于投影显示的更大字号样式。
- `assets/color_palettes.py`：可导入的 Okabe-Ito 和 Paul Tol 配色数值，及其元数据。
- `assets/publisher_profiles.json`：有明确日期的、机器可读的规划快照。

Matplotlib 样式文件中的十六进制颜色省略了 `#` 前缀，因为在 `.mplstyle` 解析规则中 `#` 表示注释的开始。

## 参考文档

- `references/publication_guidelines.md`：诚信性、欺骗性编码、可访问性、静态/交互式输出。
- `references/color_palettes.md`：配色方案的语义、精确数值、WCAG 对比度、灰度注意事项、色彩管理。
- `references/journal_requirements.md`：按投稿阶段划分的官方出版商快照。
- `references/matplotlib_examples.md`：当前可运行的 Matplotlib/Seaborn/Plotly 代码模式。
- `references/sources.md`：官方链接、日期、版本号，以及依据的研究资料。

## 最终复核清单

- [ ] 原始数据/图像和变换代码均已保留。
- [ ] 缺失值、剔除项、分箱、归一化方式，以及不确定性均已明确标示。
- [ ] 基线、坐标轴刻度、坐标范围，以及面积/体积编码均是诚实的。
- [ ] 颜色编码具有冗余性，且已核查渲染后的对比度。
- [ ] 在适用的情况下，图表配有可访问的说明/数据替代方案。
- [ ] 导出后已检查物理尺寸、DPI、文件格式、字体、透明度和文件大小。
- [ ] 已针对确切的目标期刊和投稿阶段核实了出版商的规则。
- [ ] 没有把任何自动化报告当作科学性、可访问性或合规性的认证依据来呈现。
