# Scientific Slides（科研幻灯片）

## 概述

科研演讲是交流研究成果、分享发现、与学术及专业受众互动的重要媒介。本技能提供制作高效科研演示文稿的全面指导，涵盖从结构与内容开发到视觉设计与演讲准备的方方面面。

**核心关注点**：面向会议、研讨会、答辩以及专业演讲的口头报告。

**关键设计理念**：科研演示文稿应当**视觉上引人入胜**并**有研究支撑**。要不惜一切代价避免枯燥、文字堆砌的幻灯片。优秀的科研演示文稿会结合以下要素：
- **引人注目的视觉效果**：高质量的图形、图片、图表（而不只是要点列表）
- **研究背景**：来自 research-lookup 的恰当引用，用以建立可信度
- **精简的文字**：要点仅作提示，由你本人口头进行讲解说明
- **专业的设计**：现代化的配色方案、强烈的视觉层次、充足的留白
- **叙事驱动**：清晰的叙事弧线，而非单纯的数据堆砌

**请牢记**：枯燥的演讲会被遗忘。在保持科学严谨性（通过恰当引用）的同时，让你的幻灯片在视觉上令人难忘。

## 何时使用本技能

在以下情形应使用本技能：
- 准备会议演讲（5-20 分钟）
- 制作学术研讨会内容（45-60 分钟）
- 制作学位论文答辩演示文稿
- 设计基金申请演示文稿
- 准备文献研讨会（journal club）演示文稿
- 在机构或公司进行研究报告
- 制作科学主题的教学或培训演示文稿

## 使用 Nano Banana Pro 生成幻灯片

**本技能使用 Nano Banana Pro AI 自动生成精美的演示幻灯片**。

根据输出格式的不同，有两种工作流程：

### 默认工作流：PDF 幻灯片（推荐）

使用 Nano Banana Pro 将每张幻灯片生成为一张完整的图像，然后合并为 PDF。这种方式能产生视觉效果最为惊艳的结果。

**工作原理**：
1. **规划演示文稿**：为每张幻灯片制定详细计划（标题、要点、视觉元素）
2. **生成幻灯片**：为每张幻灯片调用 Nano Banana Pro 以创建完整的幻灯片图像
3. **合并为 PDF**：将幻灯片图像组合成一份完整的 PDF 演示文稿

**第一步：规划每张幻灯片**

在生成之前，为你的演示文稿制定详细的计划：

```markdown
# Presentation Plan: Introduction to Machine Learning

## Slide 1: Title Slide
- Title: "Machine Learning: From Theory to Practice"
- Subtitle: "AI Conference 2025"
- Speaker: Dr. Jane Smith, University of XYZ
- Visual: Modern abstract neural network background

## Slide 2: Introduction
- Title: "Why Machine Learning Matters"
- Key points: Industry adoption, breakthrough applications, future potential
- Visual: Icons showing different ML applications (healthcare, finance, robotics)

## Slide 3: Core Concepts
- Title: "The Three Types of Learning"
- Content: Supervised, Unsupervised, Reinforcement
- Visual: Three-part diagram showing each type with examples

... (continue for all slides)
```

**第二步：生成每张幻灯片**

使用 `generate_slide_image.py` 脚本来创建每张幻灯片。

**关键：格式一致性协议**

为确保演示文稿中所有幻灯片的格式统一：

1. 在演示文稿开始时**定义一个格式目标（Formatting Goal）**，并将其包含在**每一条**提示词（prompt）中：
   - 配色方案（例如："深蓝色背景、白色文字、金色点缀"）
   - 字体风格（例如："粗体无衬线标题、简洁的正文字体"）
   - 视觉风格（例如："极简、专业、企业风美学"）
   - 布局方式（例如："充足的留白、内容左对齐"）

2. 在生成后续幻灯片时，**始终使用 `--attach` 附上上一张幻灯片**：
   - 这能让 Nano Banana Pro 看到并匹配现有的风格
   - 在整套演示文稿中创造视觉连续性
   - 确保颜色、字体和设计语言的一致性

3. **默认作者为 "K-Dense"**，除非另行指定其他姓名

4. 对于引用研究文献的幻灯片，**在提示词中直接包含引用**：
   - 在提示文本中加入引用，以使其出现在生成的幻灯片上
   - 使用格式："Include citation: (Author et al., Year)" 或 "Show reference: Author et al., Year"
   - 对于多个引用，将它们全部列出
   - 引用应以小字出现在幻灯片底部或相关内容附近

5. **为结果类幻灯片附上已有的图形/数据**（对于数据驱动的演示文稿至关重要）：
   - 制作关于结果的幻灯片时，**始终**检查以下位置是否存在现有图形：
     - 工作目录（例如 `figures/`、`results/`、`plots/`、`images/`）
     - 用户提供的输入文件或目录
     - 任何与演示文稿相关的数据可视化图表
   - 使用 `--attach` 引入这些图形，以便 Nano Banana Pro 能够将其纳入：
     - 为结果幻灯片附上实际的数据图形/图表
     - 为方法学幻灯片附上相关示意图
     - 为标题幻灯片附上机构徽标或图片
   - 附上数据图形时，在提示词中描述你想要的效果：
     - "Create a slide presenting the attached results chart with key findings highlighted"
     - "Build a slide around this attached figure, add title and bullet points explaining the data"
     - "Incorporate the attached graph into a results slide with interpretation"
   - **在生成结果幻灯片之前**：列出工作目录中的文件以找到相关图形
   - 可以附加多个图形：`--attach fig1.png --attach fig2.png`

**格式一致性、引用与图形附加的示例**：

```bash
# Title slide (first slide - establishes the style)
python scripts/generate_slide_image.py "Title slide for presentation: 'Machine Learning: From Theory to Practice'. Subtitle: 'AI Conference 2025'. Speaker: K-Dense. FORMATTING GOAL: Dark blue background (#1a237e), white text, gold accents (#ffc107), minimal design, sans-serif fonts, generous margins, no decorative elements." -o slides/01_title.png

# Content slide with citations (attach previous slide for consistency)
python scripts/generate_slide_image.py "Presentation slide titled 'Why Machine Learning Matters'. Three key points with simple icons: 1) Industry adoption, 2) Breakthrough applications, 3) Future potential. CITATIONS: Include at bottom in small text: (LeCun et al., 2015; Goodfellow et al., 2016). FORMATTING GOAL: Match attached slide style - dark blue background, white text, gold accents, minimal professional design, no visual clutter." -o slides/02_intro.png --attach slides/01_title.png

# Background slide with multiple citations
python scripts/generate_slide_image.py "Presentation slide titled 'Deep Learning Revolution'. Key milestones: ImageNet breakthrough (2012), transformer architecture (2017), GPT models (2018-present). CITATIONS: Show references at bottom: (Krizhevsky et al., 2012; Vaswani et al., 2017; Brown et al., 2020). FORMATTING GOAL: Match attached slide style exactly - same colors, fonts, minimal design." -o slides/03_background.png --attach slides/02_intro.png

# RESULTS SLIDE - Attach actual data figure from working directory
# First, check what figures exist: ls figures/ or ls results/
python scripts/generate_slide_image.py "Presentation slide titled 'Model Performance Results'. Create a slide presenting the attached accuracy chart. Key findings to highlight: 1) 95% accuracy achieved, 2) Outperforms baseline by 12%, 3) Consistent across test sets. CITATIONS: Include at bottom: (Our results, 2025). FORMATTING GOAL: Match attached slide style exactly." -o slides/04_results.png --attach slides/03_background.png --attach figures/accuracy_chart.png

# RESULTS SLIDE - Multiple figures comparison
python scripts/generate_slide_image.py "Presentation slide titled 'Before vs After Comparison'. Build a side-by-side comparison slide using the two attached figures. Left: baseline results, Right: our improved results. Add brief labels explaining the improvement. FORMATTING GOAL: Match attached slide style exactly." -o slides/05_comparison.png --attach slides/04_results.png --attach figures/baseline.png --attach figures/improved.png

# METHODOLOGY SLIDE - Attach existing diagram
python scripts/generate_slide_image.py "Presentation slide titled 'System Architecture'. Present the attached architecture diagram with brief explanatory bullet points: 1) Input processing, 2) Model inference, 3) Output generation. FORMATTING GOAL: Match attached slide style exactly." -o slides/06_architecture.png --attach slides/05_comparison.png --attach diagrams/system_architecture.png
```

**创建结果类幻灯片之前，重要提示，请始终**：
1. 列出工作目录中的文件：`ls -la figures/` 或 `ls -la results/`
2. 检查用户提供的目录中是否存在相关图形
3. 附加所有应出现在该幻灯片上的相关图形
4. 描述 Nano Banana Pro 应如何整合这些附加图形

**提示词模板**：

在每条提示词中包含以下要素（按需自定义）：
```
[Slide content description]
CITATIONS: Include at bottom: (Author1 et al., Year; Author2 et al., Year)
FORMATTING GOAL: [Background color], [text color], [accent color], minimal professional design, no decorative elements, consistent with attached slide style.
```

**第三步：合并为 PDF**

```bash
# Combine all slides into a PDF presentation
python scripts/slides_to_pdf.py slides/*.png -o presentation.pdf
```

### PPT 工作流：带生成式视觉素材的 PowerPoint

在制作 PowerPoint 演示文稿时，使用 Nano Banana Pro 为每张幻灯片生成图像和图形，然后使用 PPTX 技能单独添加文字。

**工作原理**：
1. **规划演示文稿**：为每张幻灯片制定内容计划
2. **生成视觉素材**：使用带 `--visual-only` 标志的 Nano Banana Pro 为幻灯片创建图像
3. **构建 PPTX**：使用 PPTX 技能（html2pptx 或基于模板的方式）创建带有生成的视觉素材和独立文字的幻灯片

**第一步：为每张幻灯片生成视觉素材**

```bash
# Generate a figure for the introduction slide
python scripts/generate_slide_image.py "Professional illustration showing machine learning applications: healthcare diagnosis, financial analysis, autonomous vehicles, and robotics. Modern flat design, colorful icons on white background." -o figures/ml_applications.png --visual-only

# Generate a diagram for the methods slide
python scripts/generate_slide_image.py "Neural network architecture diagram showing input layer, three hidden layers, and output layer. Clean, technical style with node connections. Blue and gray color scheme." -o figures/neural_network.png --visual-only

# Generate a conceptual graphic for results
python scripts/generate_slide_image.py "Before and after comparison showing improvement: left side shows cluttered data, right side shows organized insights. Arrow connecting them. Professional business style." -o figures/results_visual.png --visual-only
```

**第二步：使用 PPTX 技能构建 PowerPoint**

使用 PPTX 技能的 html2pptx 工作流来创建包含以下内容的幻灯片：
- 第一步中生成的图像
- 单独添加的标题与正文文字
- 专业的布局与格式

完整的 PPTX 制作文档见 `skills/pptx/SKILL.md`。

---

## 用科学示意图进行视觉增强

除了幻灯片生成之外，对于技术性图表，使用 **scientific-schematics** 技能：

**何时改用 scientific-schematics**：
- 复杂的技术图表（电路图、化学结构式）
- 用于论文的出版级质量图形（质量门槛更高）
- 需要科学准确性审查的图表

**如何生成示意图**：
```bash
python scripts/generate_schematic.py "your diagram description" -o figures/output.png
```

关于创建示意图的详细指导，请参阅 scientific-schematics 技能文档。

---

## 核心能力

演示文稿结构与组织、幻灯片设计原则、幻灯片数据可视化、演讲类型专属指导、实现方式（Beamer / PowerPoint / 生成式 PDF）、视觉审阅与迭代、时间安排与节奏，以及验证，均记录于 [references/slide_capabilities.md](references/slide_capabilities.md)。

分阶段开发流程——规划、设计与创建、内容开发、视觉验证、练习与打磨、最终准备——记录于 [references/presentation_workflow.md](references/presentation_workflow.md)。

针对完整幻灯片生成与纯视觉生成的提示词撰写指导见 [references/prompt_writing.md](references/prompt_writing.md)。每个内置脚本的参数与选项见 [references/script_reference.md](references/script_reference.md)。最常毁掉一场演讲的错误汇总见 [references/common_pitfalls.md](references/common_pitfalls.md)。

## 与其他技能的整合

**Research Lookup**（对科研演示文稿至关重要）：
- **背景开发**：检索文献以构建引言背景
- **引用收集**：查找演讲中需要引用的关键论文
- **空白识别**：确定尚未知晓的内容，以此作为研究动机
- **既往工作对比**：查找用于对比你研究成果的论文
- **支持性证据**：定位支持你的解读的文献
- **问答准备**：查找可能对问答环节有帮助的论文
- 在制作任何科研演示文稿时，**始终使用 research-lookup**，以确保恰当的背景与引用

**Scientific Writing**：
- 将论文内容转换为演示文稿格式
- 提取关键发现并加以简化
- 使用相同的图形（但针对幻灯片重新设计）
- 保持术语一致

**PPTX 技能**：
- 用于 PowerPoint 的创建与编辑
- 利用脚本实现模板化工作流
- 使用缩略图生成进行验证
- 参阅 html2pptx 以实现程序化创建

**数据可视化**：
- 创建适合演示文稿的图形
- 简化复杂的可视化内容
- 确保远距离可读性
- 使用渐进式呈现（progressive disclosure）

## 参考文件

针对具体方面的完整指南：

- **`references/presentation_structure.md`**：所有演讲类型的详细结构、时间分配、开场/结尾策略、过渡技巧
- **`references/slide_design_principles.md`**：字体排印、色彩理论、布局、无障碍性、视觉层次、设计工作流
- **`references/data_visualization_slides.md`**：简化图形、图表类型、渐进式呈现、常见错误、重制工作流
- **`references/talk_types_guide.md`**：针对会议、研讨会、答辩、基金申请、文献研讨会的具体指导及示例
- **`references/beamer_guide.md`**：完整的 LaTeX Beamer 文档、主题、自定义、高级功能、编译
- **`references/visual_review_workflow.md`**：PDF 转图像、系统性检查、问题记录、迭代改进

- **`references/slide_capabilities.md`**：演示文稿结构、设计原则、数据可视化、演讲类型、实现方式、视觉审阅、时间安排、验证
- **`references/presentation_workflow.md`**：从规划到最终准备的六个开发阶段
- **`references/prompt_writing.md`**：完整幻灯片与纯视觉生成的提示词模式
- **`references/script_reference.md`**：每个内置脚本的参数与选项
- **`references/common_pitfalls.md`**：应避免的内容、设计与时间安排错误

## 资源文件

### 模板

- **`assets/beamer_template_conference.tex`**：15 分钟会议演讲模板
- **`assets/beamer_template_seminar.tex`**：45 分钟学术研讨会模板
- **`assets/beamer_template_defense.tex`**：学位论文答辩模板

### 指南

- **`assets/powerpoint_design_guide.md`**：完整的 PowerPoint 设计与实现指南
- **`assets/timing_guidelines.md`**：全面的时间安排、节奏与练习策略

## 快速入门指南

### 针对 15 分钟会议演讲（PDF 工作流——推荐）

1. **研究与规划**（45 分钟）：
   - **使用 research-lookup** 查找 8-12 篇相关论文用于引用
   - 建立参考文献列表（背景资料、对比研究）
   - 梳理内容大纲（引言 → 方法 → 2-3 个关键结果 → 结论）
   - **为每张幻灯片制定详细计划**（标题、要点、视觉元素）
   - 目标为 15-18 张幻灯片

2. **使用 Nano Banana Pro 生成幻灯片**（1-2 小时）：

   **重要提示：使用一致的格式、附加上一张幻灯片，并包含引用**！

   ```bash
   # Title slide (establishes style - default author: K-Dense)
   python scripts/generate_slide_image.py "Title slide: 'Your Research Title'. Conference name, K-Dense. FORMATTING GOAL: [your color scheme], minimal professional design, no decorative elements, clean and corporate." -o slides/01_title.png

   # Introduction slide with citations (attach previous for consistency)
   python scripts/generate_slide_image.py "Slide titled 'Why This Matters'. Three key points with simple icons. CITATIONS: Include at bottom: (Smith et al., 2023; Jones et al., 2024). FORMATTING GOAL: Match attached slide style exactly." -o slides/02_intro.png --attach slides/01_title.png

   # Continue for each slide (always attach previous, include citations where relevant)
   python scripts/generate_slide_image.py "Slide titled 'Methods'. Key methodology points. CITATIONS: (Based on Chen et al., 2022). FORMATTING GOAL: Match attached slide style exactly." -o slides/03_methods.png --attach slides/02_intro.png

   # Combine to PDF
   python scripts/slides_to_pdf.py slides/*.png -o presentation.pdf
   ```

3. **审阅与迭代**（30 分钟）：
   - 打开 PDF 并审阅每张幻灯片
   - 重新生成任何需要改进的幻灯片
   - 重新合并为 PDF

4. **练习**（2-3 小时）：
   - 计时练习 3-5 次
   - 力求控制在 13-14 分钟（留出缓冲时间）
   - 录下自己的演讲并回看
   - **准备问答环节**（使用 research-lookup 预判问题）

5. **收尾**（30 分钟）：
   - 如有需要，生成备用/附录幻灯片
   - 保存多份副本
   - 在演讲用电脑上进行测试

总计耗时：约 5-6 小时，可制作出高质量的 AI 生成演示文稿

### 备选方案：PowerPoint 工作流

如果你需要可编辑的幻灯片（例如用于公司模板）：

1. 如上所述**规划幻灯片**
2. 使用 `--visual-only` 标志**生成视觉素材**：
   ```bash
   python scripts/generate_slide_image.py "diagram description" -o figures/fig1.png --visual-only
   ```
3. 使用 PPTX 技能配合生成的图像**构建 PPTX**
4. 使用 PPTX 工作流单独**添加文字**

完整的 PowerPoint 工作流见 `skills/pptx/SKILL.md`。

## 总结：关键原则

1. **视觉优先设计**：每张幻灯片都需要强有力的视觉元素（图形、图片、图表）——避免纯文字幻灯片
2. **研究支撑**：使用 research-lookup 查找 8-15 篇论文，在引言部分引用 3-5 篇，在讨论部分引用 3-5 篇
3. **现代美学**：选择与主题相符的当代配色方案，而非默认主题
4. **精简文字**：3-4 个要点，每条 4-6 个词（24-28pt 字号），让视觉内容讲述故事
5. **结构**：遵循叙事弧线，将 40-50% 的篇幅用于结果部分
6. **高对比度**：为达到专业外观，首选 7:1 的对比度
7. **多样化布局**：混合全图、双栏、视觉叠加等布局（而非全部使用要点列表）
8. **时间安排**：练习 3-5 次，大约每分钟一张幻灯片，切勿跳过结论部分
9. **验证**：使用视觉审阅工作流以捕获内容溢出与重叠问题
10. **留白**：幻灯片 40-50% 的区域保持空白，以留出视觉呼吸空间

**请牢记**：
- **枯燥 = 遗忘**：枯燥、堆砌文字的幻灯片无法传达你的科学成果
- **视觉 + 研究 = 影响力**：将引人注目的视觉效果与有研究支撑的背景相结合
- **你才是演讲本身，幻灯片只是视觉辅助**：它们应当为你的演讲增色，而非取而代之
