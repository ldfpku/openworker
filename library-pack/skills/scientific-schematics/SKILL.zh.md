# Scientific Schematics and Diagrams（科学示意图与图表）

## 概述

科学示意图和图表将复杂的概念转化为清晰的可视化表达，用于发表。**本技能使用 Nano Banana 2 AI 生成图表，并由 Gemini 3.6 Flash 进行质量评审**。

**工作原理**：
- 用自然语言描述你想要的图表
- Nano Banana 2 自动生成出版质量的图像
- **Gemini 3.6 Flash 依据文档类型的阈值评审质量**
- **智能迭代**：只有当质量低于阈值时才重新生成
- 几分钟内产出可用于发表的成果
- 无需编写代码、无需模板、无需手工绘制

**按文档类型划分的质量阈值**：
| 文档类型 | 阈值 | 说明 |
|---------------|-----------|-------------|
| journal（期刊） | 8.5/10 | Nature、Science 等同行评审期刊 |
| conference（会议） | 8.0/10 | 会议论文 |
| thesis（学位论文） | 8.0/10 | 学位论文、毕业论文 |
| grant（基金申请） | 8.0/10 | 基金申请书 |
| preprint（预印本） | 7.5/10 | arXiv、bioRxiv 等 |
| report（报告） | 7.5/10 | 技术报告 |
| poster（海报） | 7.0/10 | 学术海报 |
| presentation（演示） | 6.5/10 | 幻灯片、演讲 |
| default（默认） | 7.5/10 | 通用场景 |

**只需描述你想要的内容，Nano Banana 2 就会为你创建它**。 所有图表都存储在 figures/ 子文件夹中，并在论文/海报中被引用。

**输出内容是什么**： 一张按图像模型返回的分辨率生成的位图 PNG。本技能不提供矢量路径，也不提供 DPI 控制——如果期刊要求 PDF、EPS 或 300 dpi TIFF，需要在后续流程中转换 PNG，并在最终印刷尺寸下核对结果。

## 快速上手：生成任意图表

只需描述你想要的图表即可创建任意科学图表。Nano Banana 2 通过**智能迭代**自动处理一切：

```bash
# 为期刊论文生成（最高质量阈值：8.5/10）
python scripts/generate_schematic.py "CONSORT participant flow diagram with 500 screened, 150 excluded, 350 randomized" -o figures/consort.png --doc-type journal

# 为演示文稿生成（较低阈值：6.5/10 - 更快）
python scripts/generate_schematic.py "Transformer encoder-decoder architecture showing multi-head attention" -o figures/transformer.png --doc-type presentation

# 为海报生成（中等阈值：7.0/10）
python scripts/generate_schematic.py "MAPK signaling pathway from EGFR to gene transcription" -o figures/mapk_pathway.png --doc-type poster

# 自定义最大迭代次数（最多 2 次）
python scripts/generate_schematic.py "Complex circuit diagram with op-amp, resistors, and capacitors" -o figures/circuit.png --iterations 2 --doc-type journal
```

**幕后发生了什么**：
1. **第 1 次生成**：Nano Banana 2 按照科学图表的最佳实践创建初始图像
2. **第 1 次评审**：**Gemini 3.6 Flash** 依据文档类型阈值评估质量
3. **判断**：如果质量 >= 阈值 → **完成**（无需更多迭代！）
4. **如果低于阈值**：根据评语改进提示词，重新生成
5. **重复**：直到质量达到阈值，或达到最大迭代次数

**智能迭代的好处**：
- ✅ 如果首次生成就已足够好，可节省 API 调用
- ✅ 对期刊论文采用更高的质量标准
- ✅ 对演示文稿/海报可更快出结果
- ✅ 针对每种用途给出恰当的质量水平

**输出内容**：带版本号的图像（`name_v1.png`、`name_v2.png`）、一份最优结果的副本存放在你指定的路径下，以及记录每次迭代的分数、评语和提前停止原因的 `name_review_log.json`。

**评审无法运行时**——遇到速率限制、内容过滤，或评审模型以某种意料之外的形式作答——图像仍会被生成并保存，但不会为其臆造一个分数。日志会记录 `"score": null` 和 `"reviewed": false`，原因写在 `"review_error"` 中，运行时会打印 `Review unavailable — image kept, quality not verified`（评审不可用——图像已保留，质量未经验证）。请将这类图像视为未经检查，自行查看核实；由于该类失败通常是暂时性的，值得重新运行一次。

### 配置

设置你的 OpenRouter API 密钥：
```bash
export OPENROUTER_API_KEY='your_api_key_here'
```

在此获取 API 密钥：https://openrouter.ai/keys

**数据会离开本机**。 你的提示词会被发送到 OpenRouter 以生成图像，生成的图像也会被发送回 OpenRouter 进行质量评审。这两者都受 OpenRouter 及其底层模型供应商的数据政策约束。请不要在提示词中描述未发表的数据、患者信息，或任何处于保密期（embargo）的内容。

### AI 生成最佳实践

**科学图表的有效提示词**：

✓ **好的提示词**（具体、详尽）：
- "CONSORT flowchart showing participant flow from screening (n=500) through randomization to final analysis"
- "Transformer neural network architecture with encoder stack on left, decoder stack on right, showing multi-head attention and cross-attention connections"
- "Biological signaling cascade: EGFR receptor → RAS → RAF → MEK → ERK → nucleus, with phosphorylation steps labeled"
- "Block diagram of IoT system: sensors → microcontroller → WiFi module → cloud server → mobile app"

✗ **应避免模糊的提示词**：
- "Make a flowchart"（太笼统）
- "Neural network"（哪种类型？包含什么组件？）
- "Pathway diagram"（哪条通路？涉及哪些分子？）

**应包含的关键要素**：
- **类型**：流程图、架构图、通路图、电路图等
- **组件**：需要包含的具体元素
- **流向/方向**：元素之间如何连接（从左到右、从上到下）
- **标签**：需要包含的关键注释或文字
- **风格**：任何具体的视觉要求

**科学质量准则**（自动应用）：
- 干净的白色/浅色背景
- 高对比度以保证可读性
- 清晰、易读的标签（最小 10pt）
- 专业的排版（无衬线字体）
- 色盲友好的配色（Okabe-Ito 调色板）
- 恰当的间距以避免拥挤
- 适当位置的比例尺、图例、坐标轴

## 何时使用本技能

在以下情况应使用本技能：
- 创建神经网络架构图（Transformer、CNN、RNN 等）
- 绘制系统架构图和数据流图
- 绘制研究设计的方法学流程图（CONSORT、PRISMA）
- 可视化算法工作流程和处理流水线
- 创建电路图和电气原理图
- 描绘生物学通路和分子相互作用
- 生成网络拓扑图和层级结构图
- 阐释概念框架和理论模型
- 为技术论文设计框图

## 如何使用本技能

**只需用自然语言描述你的图表**。 Nano Banana 2 会自动生成它：

```bash
python scripts/generate_schematic.py "your diagram description" -o output.png
```

**就这么简单**！ AI 会自动处理：
- ✓ 版面布局与构图
- ✓ 标签与注释
- ✓ 颜色与样式
- ✓ 质量评审与优化
- ✓ 达到出版质量的输出

**适用于所有类型的图表**：
- 流程图（CONSORT、PRISMA 等）
- 神经网络架构图
- 生物学通路图
- 电路图
- 系统架构图
- 框图
- 任何科学可视化内容

**无需编写代码、无需模板、无需手工绘制**。

---

# AI 生成模式（Nano Banana 2 + Gemini 3.6 Flash 评审）

## 智能迭代优化、进阶用法与示例

生成-评审-优化循环、Python API 与命令行选项、提示词工程指导，以及四个完整示例（CONSORT 流程图、神经网络架构图、生物学通路图、系统架构图），都在
[references/iterative_refinement.md](references/iterative_refinement.md) 中。

一旦评审通过，循环就会立即停止，所以一张简单的图表通常只需一次迭代；只有复杂的图才会用满完整的预算。

## 命令行用法

生成科学示意图的主入口：

```bash
# 基本用法
python scripts/generate_schematic.py "diagram description" -o output.png

# 自定义迭代次数（最多 2 次）
python scripts/generate_schematic.py "complex diagram" -o diagram.png --iterations 2

# 详细模式
python scripts/generate_schematic.py "diagram" -o out.png -v
```

**注意**： Nano Banana 2 AI 生成系统在其迭代优化过程中包含自动质量评审。每一次迭代都会针对科学准确性、清晰度和可访问性进行评估。

## 最佳实践总结

### 设计原则——在提示词中要求这些

1. **清晰优先于复杂** - 简化、去除不必要的元素
2. **样式一致** - 在一篇论文的各个图之间描述相同的视觉惯例
3. **色盲可访问性** - 要求使用 Okabe-Ito 调色板并采用冗余编码
4. **恰当的排版** - 无衬线字体，字号足够大的标签
5. **合理的流向** - 明确说明方向（从左到右、从上到下）

生成器默认会应用以上所有原则，但针对具体图表用你自己的话再次点明，效果会比单纯依赖内置准则更好。

### 该流程无法做到的事

1. **矢量输出** - 仅输出 PNG；不会生成 PDF、SVG 或 EPS
2. **分辨率控制** - 由图像模型自行决定；没有 DPI 参数
3. **色彩空间** - 仅 RGB；如需 CMYK 印刷流程需在后续自行转换
4. **精确的线宽或字号** - 需要在提示词中描述，然后用肉眼核实

对于要求矢量图或 300+ dpi TIFF 的期刊，需要在生成之后转换 PNG，并在其实际印刷尺寸下核对结果。

### 集成指南

1. **在 LaTeX 中引入** - 对生成的图像使用 `\includegraphics{}`
2. **图注要详尽** - 描述所有元素和缩写
3. **在正文中引用** - 在叙述行文中说明该图表
4. **保持一致性** - 论文中所有图使用同一风格
5. **版本控制** - 将提示词和生成的图像保存在仓库中

## 常见问题排查

生成过程是随机的，且迭代次数上限为 2 次，因此真正能影响结果的杠杆是提示词、文档类型和重新运行。本技能没有后处理步骤，也没有质量检查库：你能检查的一切都在生成的 PNG 和 `<name>_review_log.json` 中。

### 图表有问题

**文字重叠、元素拥挤，或箭头没有指向正确目标**
- 在提示词中明确指定版面布局："vertical flow, one box per row, generous spacing between stages"
- 明确指定连接关系："arrow from RAF to MEK labelled phosphorylation"，而不是笼统地说 "show the cascade"
- 重新运行。同一提示词的两次运行结果不同，糟糕的版面往往只是运气不佳

**内容在科学上是错误的，或缺少某个组件**
- 明确列出所有组件，附上数量和标签——模型不会自行推断
- 阅读评审日志中的 `critique` 字段：评审模型通常会指明它看到缺失的内容

**标签中的文字错误，或图像中烧入了图号**
- 提示词中已经禁止出现 "Figure 1:" 之类的图注；如果仍然出现，请重新运行
- 标签拼写错误是图像模型最常见的失败模式。使用前请核对每一个标签

### 分数似乎不对

**分数低于图表应得的水平**
- 重新运行之前先阅读评语；评审模型的意见往往是合理且具体的
- 决定是否迭代的是阈值，而不是分数——`--doc-type journal` 要求 8.5 分

**某次运行停在低于阈值的分数上**
- 这是迭代次数上限的结果。`--iterations 2` 是最大值；最后一张图像会被保留，并报告其真实分数

**日志中出现 `"score": null` 和 `"reviewed": false`**
- 评审调用失败，或返回了无法解析的形式。图像本身没问题、已被保留；只是其质量从未被测量过。请检查 `"review_error"`，亲自查看图像，并重新运行

### 环境设置

**`Error: OPENROUTER_API_KEY not found`**
- `export OPENROUTER_API_KEY='sk-or-v1-...'`，或将其加入 `.env` 文件，或通过 `--api-key` 传入

**`Error: requests library not found`**
- `uv pip install requests`

**任何 API 错误** —— 使用 `-v` 运行以查看请求内容、模型标识（model slug）和完整的错误信息

## 资源与参考文档

### 详细参考文档

如需了解具体主题的完整信息，请加载以下文件：

- **`references/iterative_refinement.md`** - 生成-评审-优化循环、Python API、每一个命令行选项、提示词工程指导，以及四个完整示例
- **`references/best_practices.md`** - 撰写提示词与评判结果时可参考的出版标准与可访问性指南

### 外部资源

**出版标准**
- Nature 图表规范：https://www.nature.com/nature/for-authors/final-submission
- Science 图表规范：https://www.science.org/content/page/instructions-preparing-initial-manuscript
- CONSORT 图：http://www.consort-statement.org/consort-statement/flow-diagram

## 与其他技能的集成

本技能可与以下技能协同工作：

- **Scientific Writing（科学写作）** - 图表遵循图片最佳实践
- **Scientific Visualization（科学可视化）** - 共享配色方案与样式
- **LaTeX Posters（LaTeX 海报）** - 为海报展示生成图表
- **Research Grants（研究基金）** - 为申请书生成方法学图表
- **Peer Review（同行评审）** - 评估图表的清晰度与可访问性

## 快速参考清单

提交图表之前，请核对以下各项：

### 阅读评审日志（这是唯一的自动化检查）
- [ ] `<name>_review_log.json` 存在，且最后一次迭代的 `"reviewed"` 为 `true`
- [ ] `"final_score"` 是一个真实的数字（而非 `null`），并达到了你所选文档类型的阈值
- [ ] 阅读 `"critique"`——即便分数达标，评审模型指出的遗留问题也会列在其中
- [ ] 如果生成了不止一个版本，比较 `_v1` 和 `_v2`，保留更好的那个

### 亲自查看图像
- [ ] 每个标签的拼写都是正确的——图像模型会拼错文字，本技能中没有任何自动化检查能捕捉到这一点
- [ ] 没有文字重叠或被裁切
- [ ] 所有箭头都连接到了它们应该连接的元素上
- [ ] 科学内容正确：组件正确、方向正确、没有臆造的内容
- [ ] 单位和数量与你的要求一致

### 可访问性（凭肉眼判断，或使用外部检查工具）
- [ ] 色盲安全的配色方案，且编码方式不仅仅依赖颜色
- [ ] 转换为灰度后依然可读
- [ ] 相邻元素之间有足够的对比度

### 出版适配度
- [ ] 与稿件中其他图保持一致的风格
- [ ] 在实际印刷的栏宽下依然清晰可读
- [ ] 如果期刊不接受 PNG，已转换为期刊要求的格式
- [ ] 图注已撰写，所有缩写均已给出定义
- [ ] 已在稿件正文中引用

### 版本控制
- [ ] 提示词已被记录（评审日志中会逐字保存）
- [ ] 评审日志与图像一并提交，以便分数可被审计
- [ ] 重新生成该图所需的命令已被记录下来

### 最终集成检查
- [ ] 图在编译完成的稿件中正确显示
- [ ] 交叉引用正常工作（`\ref{}` 指向正确的图）
- [ ] 图号与正文中的引用一致
- [ ] 图注相对于图片出现在正确的页面上
- [ ] 没有与图相关的编译警告或错误

## 环境设置

```bash
# 必需
export OPENROUTER_API_KEY='your_api_key_here'

# 在此获取密钥：https://openrouter.ai/keys
```

## 快速上手

**最简单的用法**：
```bash
python scripts/generate_schematic.py "your diagram description" -o output.png
```

---

使用本技能来创建清晰、可访问、达到出版质量的图表，从而有效传达复杂的科学概念。这套具备迭代优化能力的 AI 驱动工作流可确保图表符合专业标准。
