# PPTX 的创建、编辑与分析

`.pptx` 是一个 XML 文件的 ZIP 归档。根据任务选择你的方法：

| 任务 | 方法 |
|---|---|
| **创建**新的演示文稿 | 编写 `pptxgenjs` 脚本 —— 见下方的坑 |
| **编辑**已有的演示文稿，或基于模板构建 | 解压 → 编辑 `ppt/slides/slideN.xml` → 打包 |
| **读取**内容 | `markitdown deck.pptx`（每张幻灯片一个内容块，位于 `<!-- Slide number: N -->` 标记之下）；可视化网格视图：`python scripts/thumbnail.py deck.pptx` |

## 脚本

路径均相对于本技能所在目录。其余部分都是普通的 Python、`node` 或 shell 脚本。

| 脚本 | 作用 |
|---|---|
| `scripts/thumbnail.py deck.pptx [prefix]` | 生成带编号的全部幻灯片网格图，便于挑选模板版式。仅支持 `.pptx`。请传入 `prefix` 参数 —— 默认值为 `thumbnails`，若同一目录下处理多个演示文稿会覆盖彼此的网格图 |
| `scripts/add_slide.py unpacked/ slide2.xml [--after slideN.xml]` | 复制一张幻灯片（或一个 `slideLayoutN.xml`），并完成全部包内登记工作。也可直接对 `.pptx` 操作，加上 `-o out.pptx` |
| `scripts/clean.py unpacked/` | 删除不再被引用的幻灯片、媒体文件与关系（rels）。需在 `<p:sldIdLst>` 最终确定**之后**运行 |
| `scripts/office/validate.py deck.pptx [--original src.pptx]` | 进行架构（schema）、关系、内容类型、图表与幻灯片检查；每一项失败都会指出对应的修复方法。对任何基于模板生成的演示文稿都应传入 `--original` —— 它会以模板本身为基准来校验架构检查，这样模板自身的 XSD 错误就不会被误判为你造成的问题 |
| `scripts/office/soffice.py --headless --convert-to pdf deck.pptx` | LibreOffice 的封装脚本 —— 裸调用 `soffice` 在此沙箱环境中会挂起 |

## 使用 pptxgenjs 创建时的注意事项（坑）

`pptxgenjs` 已预先安装 —— 不要先运行 `npm install`，直接编写脚本并 `require('pptxgenjs')` 即可。只有在该 `require` 失败时才执行：`npm install pptxgenjs`。模型本身了解该 API；以下是需要特别留意的坑：

- **在添加幻灯片之前设置 `pres.layout`。** 默认画布是 `LAYOUT_16x9` = **10" × 5.625"**，而不是 13.3" 宽。超出边界的坐标会被照写而不会被裁剪 —— 该形状只是不会出现在幻灯片上而已。（`LAYOUT_WIDE` 为 13.3" × 7.5"。）
- **十六进制颜色：绝不加 `#`，绝不使用 8 位。** 应写作 `color: "FF0000"`。无论是 `"#FF0000"` 还是把透明度编进十六进制里（`"00000020"`）都会**损坏文件**。要实现半透明效果：填充和图片上使用 `transparency: 0-100`，阴影上使用 `opacity: 0.0-1.0` —— 二者互不通用，用错的一方会被静默忽略。
- **pptxgenjs 会原地修改传入的选项对象**（首次使用时会把数值转换为 EMU 单位）。切勿在两次 `add*` 调用之间共享同一个 `shadow` / 选项对象 —— 每次都要重新构建一个新对象。
- **阴影的 `offset` 必须 ≥ 0** —— 负的 offset 会损坏文件。若想让阴影朝上投射，请使用 `angle: 270` 配合正的 offset。
- **`letterSpacing` 会被静默忽略** —— 真正生效的选项是 `charSpacing`。
- **列表**： 每一项都要设置 `bullet: true`，绝不要使用字面的 `•` 字符（会渲染出双重项目符号）。除数组最后一项外，每一项都要设置 `breakLine: true`。项目符号段落之间的间距要用 `paraSpaceAfter` 调整，而不是 `lineSpacing`（后者会产生巨大的间隙）。
- **每个输出文件对应一个 `new pptxgen()`** —— 切勿复用同一个实例。
- **`rectRadius` 只对 `ROUNDED_RECTANGLE` 生效**，对 `RECTANGLE` 无效。
- **不支持渐变填充** —— 请改用渐变图片作为背景。
- **文本框自带内部内边距** —— 只要文本需要与形状、线条或图标在同一 x 坐标对齐，就要设置 `margin: 0`。
- **演讲者备注应写在 `slide.addNotes("...")` 中**（纯文本，每张幻灯片一次），绝不要放进幻灯片上的文本框里。
- **让图表保持原生**。 对于 PowerPoint 能原生绘制的一切图表都使用 `addChart()`（组合图表可传入一个 `{type, data, options}` 数组）。对于该库没有暴露出来的 PowerPoint 原生特性（趋势线、误差线），要么自行计算额外的数据系列，要么对生成的 OOXML 进行后处理 —— 不要退而使用渲染出来的图片。只有 PowerPoint 完全没有原生形式的图表类型（桑基图、网络图、和弦图）才以图片形式插入。
- **默认生成的图表非常朴素** —— 没有标题、没有数据标签、配色也过时。请设置 `showTitle` + `title`、`showValue: true` + `dataLabelPosition`、来自你调色板的 `chartColors: [...]`，并让边框元素更安静（`catAxisLabelColor` / `valAxisLabelColor`、`valGridLine: { color, size }`、`catGridLine: { style: "none" }`，单一数据系列时设 `showLegend: false`）。
- **在堆叠条形图或柱形图上，`dataLabelPosition` 必须是 `ctr`、`inEnd` 或 `inBase` 之一。**`outEnd`**会损坏文件**。
- **使用 `secondaryValAxis` / `secondaryCatAxis` 的组合数据系列，图表选项中的 `valAxes` 和 `catAxes` 都必须提供，且各需两项。** 缺少它们时，pptxgenjs 会写出它从未声明过的坐标轴 *id*，PowerPoint 会**丢弃该图表**并把文件报告为已损坏。只提供 `valAxes` 是不够的。
- **调用 `writeFile()` 之后，运行 `python scripts/office/validate.py deck.pptx`。** 它会报告上述两类图表错误，以及 PowerPoint 拒绝接受的幻灯片 XML 缺陷，并为每一个都指出修复方法。请在生成器代码中修复，而不是手工编辑打包后的 XML。
- **切勿重新排列 `<p:presentation>` 的子元素顺序。** pptxgenjs 会把 `<p:notesMasterIdLst>` 紧跟在 `<p:sldIdLst>` 之后写入，并让两个母版都指向同一个主题（theme）部件。PowerPoint 能正常读取这种结构 —— 一旦移动了该元素，同一份文件就会变得无法打开。
- **图标**： 用 `react-icons` 渲染出 SVG（`ReactDOMServer.renderToStaticMarkup`），再用 `sharp` 以 ≥256px 栅格化，最后通过 `addImage({ data: "image/png;base64," + buf.toString("base64") })` 插入 —— 其中 `image/png;base64,` 前缀是必需的（`react-icons`、`react`、`react-dom` 和 `sharp` 均已预装 —— 只有当某个 `require` 失败时才执行 `npm install react-icons react react-dom sharp`）。

## 编辑已有的演示文稿与模板

先挑选版式：`python scripts/thumbnail.py template.pptx template-thumbs` 会生成一份带编号的全部幻灯片网格图，并打印出它所创建的文件 —— `template-thumbs.jpg`，超过 12 张幻灯片时会拆分为 `template-thumbs-N.jpg`。**务必传入第二个参数，并以该演示文稿命名**。 该参数默认值为 `thumbnails`，因此同一目录下生成两份演示文稿的缩略图会互相静默覆盖 —— 先生成的那份缩略图就此丢失（模板分析用途；真正的视觉 QA 需要 [转换为图片](#转换为图片) 一节中的全分辨率渲染图 —— 该脚本只接受 `.pptx`，所以要先把 `.potx` 复制为一个 `.pptx` 文件名）。将它与 `markitdown` 搭配使用，把每个内容小节对应到某张模板幻灯片上，并注意变换版式 —— 不要把所有内容小节都塞进同一种标题加要点的幻灯片里。

```bash
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall('unpacked')" deck.pptx
python scripts/add_slide.py unpacked/ slide2.xml --after slide2.xml   # 复制一张幻灯片（或 slideLayoutN.xml）；打印出新幻灯片的路径
# 重新排序 / 删除幻灯片 = 编辑 ppt/presentation.xml 中的 <p:sldIdLst>
python scripts/clean.py unpacked/                                     # 删除操作之后执行：清除孤立的幻灯片、媒体、关系
# 在 ppt/slides/slideN.xml 中编辑幻灯片内容
(cd unpacked && rm -f ../out.pptx && zip -Xr ../out.pptx .)           # 要从目录内部打包；先 rm，否则已删除的部件会残留在包内
python scripts/office/validate.py out.pptx --original deck.pptx
```

- **务必先完成全部结构性工作 —— 添加、删除、重新排序 —— 再去编辑任何一张幻灯片的内容**。`add_slide.py` 是逐字复制幻灯片文件的，所以在编辑之后再复制会把已编辑过的内容一并克隆；而 `clean.py` 会删除任何未出现在 `<p:sldIdLst>` 中的幻灯片，哪怕是你刚写好的那张。
- **切勿手动复制幻灯片文件** —— `add_slide.py` 会完成新幻灯片所需的全部登记工作，并报告它做了什么（`Created ppt/slides/slide17.xml from slide2.xml`）。它也可以直接对 `.pptx` 操作：`add_slide.py deck.pptx slide2.xml -o out.pptx` —— **务必传入 `-o`，否则它会就地覆写输入的演示文稿。** 被复制出来的幻灯片仍然*引用*着源幻灯片的图表 / SmartArt / 嵌入对象部件，而不是克隆它们，所以编辑其中一张幻灯片的图表会同时改变另一张的图表。
- **若使用 `python-pptx`**，有三件事它做不到：复制一张幻灯片（它唯一的入口是 `add_slide(layout)`）、通过 `text_frame.text = "..."` 保留格式（这会把段落坍缩为单个无样式的 run —— 应改为对 `run.text` 赋值）、以及读取大多数模板美术素材所使用的 SVG/EMF 格式（`add_picture` 会抛出 `UnidentifiedImageError`）。
- 旧版 `.ppt` 必须先转换：`python scripts/office/soffice.py --headless --convert-to pptx file.ppt`。`.potx` 模板的解包与打包方式与 `.pptx` 相同 —— 输出文件请保留 `.potx` 扩展名。
- 要复用模板中的某个图标或图片，可复制一张已包含该素材的幻灯片或版式。

在填充模板时：

- 若你用脚本进行 XML 转换，请用 `defusedxml.minidom` 解析 —— 通过 `xml.etree.ElementTree` 往返处理 OOXML 会重写命名空间前缀，从而损坏该演示文稿。
- **模板槽位 ≠ 源数据条目**。 如果模板展示了 4 名团队成员而你只有 3 名，应删除第 4 名成员的整个组（图片 + 文本框），而不仅仅是删掉文字 —— 之后要在 QA 中检查是否有遗留的孤立视觉元素。
- 每个列表项对应一个 `<a:p>` —— 切勿把多个条目拼接进同一个段落。复制相邻的 `<a:pPr>` 以保留间距，并在标题、小节标题和行内标签（`Status:`、`Owner:`）的 `<a:rPr>` 上加 `b="1"`。
- 让项目符号继承自版式；只有在需要覆盖时才添加 `<a:buChar>`、`<a:buAutoNum>`（编号列表）或 `<a:buNone>` —— 文本中切勿出现字面的 `•`。
- 有前导或尾随空格的文本需要在其 `<a:t>` 上加 `xml:space="preserve"`。

## 设计思路

**不要制作枯燥的幻灯片**。 白底加纯文字要点不会给任何人留下印象。为每张幻灯片参考下面这份清单中的思路。

### 动手之前

- **选定一个大胆的、与内容相契合的调色板**：这套配色应当让人感觉是专为*这个*主题设计的。如果把你的配色换到一份完全不同的演示文稿里依然"说得通"，那说明你的选择还不够具体。
- **主次分明，而非平均**：应有一种颜色占主导地位（占视觉权重的 60-70%），搭配 1-2 种辅助色调和一个鲜明的强调色。切勿让所有颜色权重相同。
- **深色/浅色对比**：标题页和结论页用深色背景，内容页用浅色（"三明治"结构）。或者从头到尾坚持深色风格，营造高级感。
- **确定一个视觉主题元素**：挑选*一个*独特的元素并重复使用 —— 圆角图片框、置于彩色圆圈中的图标等。让它贯穿每一张幻灯片。**不要把色带或强调条纹用作你的主题元素**（见下方的"避免事项"清单）。

### 调色板

选择与你的主题相匹配的颜色 —— 不要默认使用普通的蓝色。可参考下面这些配色方案作为灵感：

| 主题 | 主色 | 辅色 | 强调色 |
|-------|---------|-----------|--------|
| **午夜行政风（Midnight Executive）** | `1E2761`（海军蓝） | `CADCFC`（冰蓝） | `FFFFFF`（白色） |
| **森林与苔藓（Forest & Moss）** | `2C5F2D`（森林绿） | `97BC62`（苔藓绿） | `F5F5F5`（乳白色） |
| **珊瑚活力（Coral Energy）** | `F96167`（珊瑚色） | `F9E795`（金色） | `2F3C7E`（海军蓝） |
| **暖调赤陶（Warm Terracotta）** | `B85042`（赤陶色） | `E7E8D1`（沙色） | `A7BEAE`（鼠尾草绿） |
| **海洋渐变（Ocean Gradient）** | `065A82`（深蓝） | `1C7293`（青色） | `21295C`（午夜蓝） |
| **炭灰极简（Charcoal Minimal）** | `36454F`（炭灰色） | `F2F2F2`（灰白色） | `212121`（黑色） |
| **信赖青（Teal Trust）** | `028090`（青色） | `00A896`（海泡绿） | `02C39A`（薄荷绿） |
| **浆果与奶油（Berry & Cream）** | `6D2E46`（浆果色） | `A26769`（灰玫瑰色） | `ECE2D0`（奶油色） |
| **沉静鼠尾草（Sage Calm）** | `84B59F`（鼠尾草绿） | `69A297`（桉树绿） | `50808E`（石板灰） |
| **樱桃浓烈（Cherry Bold）** | `990011`（樱桃色） | `FCF6F5`（灰白色） | `2F3C7E`（海军蓝） |

### 针对每张幻灯片

**每张幻灯片都需要一个视觉元素** —— 图片、图表、图标或形状。纯文字的幻灯片让人过目即忘。

**版式选项**：
- 双栏布局（左侧文字、右侧插图）
- 图标 + 文字行（彩色圆圈内放图标，配粗体标题与下方描述）
- 2x2 或 2x3 网格（一侧放图片，另一侧放内容块网格）
- 半屏出血图片（左侧或右侧整面）叠加内容层

**数据展示**：
- 大号统计数字标注（60-72pt 的大数字，下方配小号标签）
- 对比栏（前后对比、优缺点对比、并排选项对比）
- 时间线或流程图（编号步骤、箭头）

**视觉打磨**：
- 在小节标题旁的小号彩色圆圈中放置图标
- 用斜体强调文字来突出关键数据或标语

### 排版

**你写入 `.pptx` 的字体名称是由用户的 PowerPoint 渲染的，而不是由本环境渲染的。** 你的视觉 QA 是通过 LibreOffice 渲染的，它会用自己拥有的字体去替换缺失的字体 —— 对某些字体来说，替代字体的字宽不同，因此你的 QA 预览可能会显示出真实文件中并不存在的文字溢出（或恰好合适的假象）。为了让你的 QA 结果可信：

- **安全字体**（在 QA 中渲染宽度与真实一致，*并且*随 Office 一同提供）：**Arial、Calibri、Cambria、Times New Roman、Courier New、Bookman Old Style、Century Schoolbook**。正文文字以及任何对"是否放得下"敏感的地方都应使用这些字体。
- **在零 QA 风险下获得个性化标题效果**：将安全字体清单中的衬线体标题字体（Cambria、Bookman Old Style、Century Schoolbook）与安全清单中的无衬线正文字体（Calibri 或 Arial）搭配使用。这样既能获得视觉对比，又不必放弃可靠的溢出检查。
- **若用户要求使用安全清单之外的字体**（例如 Georgia 或 Trebuchet MS）：在用户指定的位置使用它，但要给这些容器多留一些余量（约 10%），并且不要相信 QA 在这些元素上给出的文字是否放得下的判断 —— 该字体的预览结果只是近似值。若用户未指定，正文文字应优先选用安全清单中的字体。
- **QA 结果不可靠的字体**（替代字体的字宽不同 —— 溢出检查可能出错）：Georgia、Trebuchet MS、Impact、Arial Black、Garamond、Consolas、Palatino Linotype。Calibri Light 的替代字体因环境而异，应视为 QA 不可靠。用于标题/点缀元素并留出余量是可以的；但不要相信 QA 在这些元素上给出的文字适配判断。
- **切勿默认使用 Aptos** —— Office 2023 年后的默认字体在本环境中没有度量兼容的替代字体，*而且*在较旧版本的 Office 安装中根本不存在，因此在两端都不可靠。

| 元素 | 字号 |
|---------|------|
| 幻灯片标题 | 36-44pt 粗体 |
| 小节标题 | 20-24pt 粗体 |
| 正文文字 | 14-16pt |
| 说明文字 | 10-12pt 弱化色 |

### 间距

- 最小 0.5" 页边距
- 内容块之间 0.3-0.5"
- 留出呼吸空间 —— 不要填满每一寸空间

### 避免事项（常见错误）

- **不要重复使用同一种版式** —— 在各张幻灯片之间变换栏数、卡片和标注方式
- **不要将正文文字居中** —— 段落与列表左对齐；只有标题才居中
- **不要吝惜大小对比** —— 标题需要 36pt 以上才能从 14-16pt 的正文中脱颖而出
- **不要默认使用蓝色** —— 选择能反映具体主题的颜色
- **不要随意混用间距** —— 选定 0.3" 或 0.5" 的间隙并保持一致使用
- **不要只给一张幻灯片做设计而其余保持朴素** —— 要么彻底投入风格设计，要么全程保持简洁
- **不要制作纯文字幻灯片** —— 添加图片、图标、图表或视觉元素；避免"纯标题 + 要点"式的幻灯片
- **不要忘记文本框的内边距** —— 在将线条或形状与文字边缘对齐时，要么在文本框上设置 `margin: 0`，要么为该内边距预留形状偏移量
- **不要使用低对比度元素** —— 图标和文字都需要与背景形成强烈对比；避免浅色文字配浅色背景、或深色文字配深色背景
- **切勿在标题下方使用强调线** —— 这是 AI 生成幻灯片的典型标志；应改用留白或背景色
- **切勿添加装饰性色带或强调条纹** —— 包括：横跨幻灯片宽度的页眉/页脚色带、沿幻灯片一侧的竖直侧边条纹、沿卡片或内容块一侧的细条纹强调线，以及矩形的"单边边框"。这些都会被识别为 AI 生成的填充物。若想突出某张卡片，请使用微妙的背景色调、投影或图标 —— 而不是边缘条纹。
- **不要默认使用米色/杏色背景** —— 未指定背景时，使用白色（`FFFFFF`）或用户的品牌配色；避免使用 `F5F5DC`、`FAF0E6`、`FAEBD7`、`FFF8E1` 这类暖调中性色默认值
- **不要让文字溢出其所在形状** —— 若文字放不下，应缩小字号、拆分到多张幻灯片，或扩大容器；切勿让内容被截断或溢出边界

## QA（必需）

你的第一次渲染通常会出现一些真实问题 —— 重叠、溢出、错位。找出并修复这些问题，只重新渲染你改动过的幻灯片，然后停止。

### 内容 QA

```bash
markitdown output.pptx
```

检查是否有内容缺失、拼写错误、顺序错误。

**使用模板时，检查是否有遗留的占位文字**：

```bash
markitdown output.pptx | grep -iE "\bx{3,}\b|lorem|ipsum|\bTODO|\[insert|this.*(page|slide).*layout"
```

如果 grep 有结果返回，应先修复这些问题再宣布完成。

### 文件 QA（必需）

```bash
python scripts/office/validate.py output.pptx                      # 从零构建的情况
python scripts/office/validate.py output.pptx --original src.pptx  # 基于模板构建的情况
```

**如果该演示文稿来自模板，请务必传入 `--original`。** 模板本身可能就包含 XSD 会拒绝的部件，因此不带该参数的裸运行可能会报告一些并非你造成的失败 —— 而真正的回归问题也可能藏身其中难以分辨。`--original` 会以模板为基准来校验架构和幻灯片检查，从而抑制模板本身就存在的错误。
结构性检查 —— 关系、内容类型、图表 —— 不受 `--original` 影响，无论如何都会报告模板本身遗留的问题，因此这些结果要单独判断其是否成立。

pptxgenjs 会生成一些 PowerPoint 拒绝打开、而其他所有工具都能接受的图表 XML：python-pptx 能打开这些文件、LibreOffice 能渲染它们、XSD 校验也能通过。每一个失败都会指出对应的修复方法。请在生成器中修复后重新构建。

### 视觉 QA

将幻灯片转换为图片（见 [转换为图片](#转换为图片)）并逐一检查。盯着生成代码看久了容易只看到自己预期的样子而不是实际渲染出来的样子，所以要以新鲜的眼光去看这些图片（如果你有子代理可用，用子代理来做这件事效果不错）。需要留意的用户可见缺陷包括：

- **文字在边框或幻灯片边界处溢出或被截断 —— 首先检查这一项**。 这是最常见的缺陷，且总是用户可见的。（对于排版一节中提到的预览不可靠的字体，预览结果只是近似的：应相信你预留的约 10% 余量，而不是预览中看起来的适配情况。）
- 元素重叠（文字穿过形状、线条穿过文字、元素堆叠）
- 来源引用或页脚与上方内容发生碰撞
- 元素间距过近（< 0.3" 间隙）或卡片/小节几乎贴在一起
- 间距不均匀（某处留有大片空白，另一处却很拥挤）
- 与幻灯片边缘的边距不足（< 0.5"）
- 各栏或类似元素未能一致对齐
- 低对比度文字（例如浅灰色文字配乳白色背景）
- 文字替换后模板装饰元素位置错乱 —— 例如，标题下划线是按单行文字定位的，但替换后的标题换成了两行
- 低对比度图标（例如深色背景上的深色图标，且没有对比色圆圈衬托）
- 文本框过窄导致过度换行
- 遗留的占位内容

## 转换为图片

将演示文稿转换为独立的幻灯片图片以便进行视觉检查：

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg
pdftoppm -jpeg -r 150 output.pdf slide
ls -1 "$PWD"/slide-*.jpg
```

**将上面打印出的绝对路径直接传给查看工具**。 该 `rm` 命令会清除上一次运行遗留下来的旧图片。`pdftoppm` 会根据页数决定补零位数：文档少于 10 页时为 `slide-1.jpg`，10-99 页时为 `slide-01.jpg`，100 页以上时为 `slide-001.jpg`。

**修复问题后，重新执行以上全部四条命令** —— 必须先从修改后的 `.pptx` 重新生成 PDF,`pdftoppm` 才能反映出你的改动。

## 依赖

`pptxgenjs`（npm，已预装 —— 仅当 `require('pptxgenjs')` 失败时才安装） · `markitdown[pptx]`、`Pillow`、`defusedxml`、`lxml`（pip —— 用于文本导出、缩略图、清理、校验） · LibreOffice（`soffice`，通过 `scripts/office/soffice.py` 针对沙箱环境自动配置） · `pdftoppm`（Poppler）

---

*本技能由 [Anthropic](https://github.com/anthropics/skills/tree/main/skills/pptx) 创建并维护。此处按原样收录(vendored)，除 frontmatter 元数据外未作修改；条款详见 LICENSE.txt。*
