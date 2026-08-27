# LaTeX 学术海报

## 概述

学术海报是在会议、研讨会和学术活动中进行科学交流的重要媒介。本技能提供了使用 LaTeX 宏包制作专业、视觉效果出色的学术海报的完整指导。可以生成排版规范、色彩搭配得当、视觉层次分明的、达到出版质量的海报。

## 何时使用本技能

在以下情况下应使用本技能：
- 为会议、研讨会或海报展示环节制作学术海报
- 为高校活动或论文答辩设计学术海报
- 为面向公众的科普传播准备研究成果的视觉摘要
- 将科学论文转换为海报格式
- 为课题组或院系制作模板海报
- 设计符合特定会议尺寸要求（A0、A1、36×48 英寸等）的海报
- 搭建包含复杂多栏布局的海报
- 在海报中整合图表、表格、公式与引用文献

## AI 驱动的视觉元素生成

**标准工作流：在制作 LaTeX 海报之前，先用 AI 生成全部主要视觉元素**。

这是制作视觉效果出色的海报所推荐的方法：
1. 规划所需的全部视觉元素（标题、引言、方法、结果、结论）
2. 使用 scientific-schematics 或 Nano Banana Pro 生成每个元素
3. 将生成的图像组装进 LaTeX 模板
4. 在视觉元素周围补充文字内容

**目标：海报面积的 60-70% 应为 AI 生成的视觉元素，30-40% 为文字**。

---

### 硬性限制（不可超出）

以下是限制，而非建议。违反这些限制是海报制作失败最常见的原因。完整的原理说明、按图形类型分类的表格及实操示例，见
[references/ai_graphics_for_posters.md](references/ai_graphics_for_posters.md)。

| 约束项 | 限制 |
| --- | --- |
| 每张 AI 生成图形中的元素数量 | **最多 3-4 个**（理想为 3 个） |
| 每张图形中的字数 | **最多 10 个词** |
| 每张图形的留白比例 | **最低 50%**（60% 更佳） |
| 关键数字/指标 | **120pt 以上** |
| 标签 | **80pt 以上** |
| 海报正文文字 | **24pt 以上** |
| 内容板块数量（A0） | **最多 5-6 个** |
| 海报总字数 | **300-800 词** |
| 图形宽度 | `0.85\linewidth`，绝不使用 `1.0` |

每条图形生成提示词都必须包含：`POSTER FORMAT for A0`、明确的元素或字数限制（如 `ONLY 3 icons`、`3 words total`）、字号（如 `GIANT (120pt+)`）、`60% white space`，以及观看距离（如 `readable from 10-12 feet`）。

**两道强制性审核关卡**。 跳过任何一道，都会导致海报无法辨识：

- **生成之前**——对每一张计划中的图形，确认其元素数在 3-4 个之间、只对应一条提示消息、字数在 10 词以内，且不是一个 5 个阶段以上的流程。若不满足，则拆分为多张图形。
- **生成之后、组装之前**——以 25% 缩放比例查看每张图形。所有文字都清晰可读、元素不超过 4 个、留白达到 50% 以上、能在 2 秒内看懂。任何一项不达标，就应重新生成或拆分。绝不要用未通过检验的图形来组装海报。

以下模式必定会失败：`7-stage workflow`（七阶段流程）、`timeline with annual milestones`（带逐年里程碑的时间线）、`3 case studies in one graphic`（一张图里放 3 个案例）、`comparison of 5+ methods`（5 种以上方法的对比）、`architecture with all layers`（包含全部层级的架构图）。应将每一项压缩为 3 个高层级要点，或拆分为多张独立的图形。

**溢出是一种错误，而不是警告**。 编译完成后，运行 `grep -i overfull poster.log`，并以 100% 缩放比例检查四条边缘。参见
[references/compilation_and_quality_control.md](references/compilation_and_quality_control.md)。

## 与 Scientific Schematics 的集成

关于制作示意图的详细指导，请参阅 **scientific-schematics** 技能的文档。

**关键能力**：
- Nano Banana Pro 可自动生成、审核并优化图表
- 生成排版规范、达到出版质量的图像
- 保证可访问性（对色盲友好、高对比度）
- 支持对复杂图表进行迭代优化

---

## 核心能力

本技能支持三个海报宏包——**beamerposter（**Beamer 语法，含机构主题**）、tikzposter**（现代、色彩丰富、灵活）以及 **baposter**（结构化多栏布局）。宏包对比、布局与网格系统、设计原则、标准尺寸、各宏包的模板、图像整合、配色方案、排版及二维码，均记录于
[references/latex_poster_reference.md](references/latex_poster_reference.md)。

可复用的分节内容模式、可访问性要求以及展示当天的注意事项，见
[references/poster_patterns_and_presentation.md](references/poster_patterns_and_presentation.md)。

## 海报制作工作流

### 第一阶段：规划与内容构建

1. **确定海报要求**：
   - 会议尺寸规格（A0、36×48 英寸等）
   - 方向（竖版还是横版）
   - 提交截止日期与格式要求

2. **梳理内容大纲**：
   - 确定 1-3 条核心信息
   - 挑选关键图表（通常为 3-6 张主要视觉图）
   - 为每个板块起草简明文字（优先使用要点式列表）
   - 总字数争取控制在 300-800 词

3. **选择 LaTeX 宏包**：
   - beamerposter：若熟悉 Beamer、需要机构主题
   - tikzposter：需要现代、色彩丰富且灵活的设计
   - baposter：需要结构化、专业的多栏布局

### 第二阶段：生成视觉元素（AI 驱动）

**关键：生成内容极简的简单图形。每张图形对应一条生成消息**。

**内容限制**：
- 每张图形最多 4-5 个元素
- 每张图形总字数最多 15 词
- 留白比例最低 50%
- 巨大字号（标签 80pt 以上，关键数字 120pt 以上）

1. **创建图形目录**：
   ```bash
   mkdir -p figures
   ```

2. **生成简单的视觉元素**：
   ```bash
   # Introduction - ONLY 3 icons/elements
   python scripts/generate_schematic.py "POSTER FORMAT for A0. SIMPLE visual with ONLY 3 elements: [icon1] [icon2] [icon3]. ONE word labels (80pt+). 50% white space. Readable from 8 feet." -o figures/intro.png
   
   # Methods - ONLY 4 steps maximum
   python scripts/generate_schematic.py "POSTER FORMAT for A0. SIMPLE flowchart with ONLY 4 boxes: STEP1 → STEP2 → STEP3 → STEP4. GIANT labels (100pt+). 50% white space. NO sub-steps." -o figures/methods.png
   
   # Results - ONLY 3 bars/comparisons
   python scripts/generate_schematic.py "POSTER FORMAT for A0. SIMPLE chart with ONLY 3 bars. GIANT percentages ON bars (120pt+). NO axis, NO legend. 50% white space." -o figures/results.png
   
   # Conclusions - EXACTLY 3 items with GIANT numbers
   python scripts/generate_schematic.py "POSTER FORMAT for A0. EXACTLY 3 key findings: '[NUMBER]' (150pt) '[LABEL]' (60pt) for each. 50% white space. NO other text." -o figures/conclusions.png
   ```

3. **审核生成的图形——检查是否溢出**：
   - **以 25% 缩放比例查看**：所有文字是否仍然清晰可读？
   - **清点元素数量**：超过 5 个？→ 重新生成更简单的版本
   - **检查留白比例**：低于 40%？→ 在提示词中加入 "60% white space"
   - **字号过小**？：加入 "EVEN LARGER"，或提高 pt 数值
   - **仍然溢出**？：把元素数减到 3 个，而非 4-5 个

### 第三阶段：设计与布局

1. **选择或创建模板**：
   - 从 `assets/` 目录中提供的模板开始
   - 将配色方案调整为符合品牌形象
   - 配置页面尺寸与方向

2. **设计布局结构**：
   - 规划栏结构（2 栏、3 栏或 4 栏）
   - 规划内容走向（通常为从左到右、从上到下）
   - 分配空间：标题（10-15%）、内容（70-80%）、页脚（5-10%）

3. **设置排版**：
   - 为不同层级配置对应字号
   - 确保正文字号不低于 24pt
   - 在 4-6 英尺的距离测试可读性

### 第四阶段：内容整合

1. **制作海报页眉**：
   - 标题（简洁、有描述力，10-15 词）
   - 作者及所属机构
   - 机构 logo（高分辨率）
   - 如有要求，加入会议 logo

2. **整合 AI 生成的图形**：
   - 将第二阶段生成的全部图形添加到相应板块
   - 使用 `\includegraphics` 并设置合适的尺寸
   - 确保图形在每个板块中占据主导地位（视觉元素优先，文字其次）
   - 在板块内将图形居中排布，以增强视觉冲击力

3. **添加最少量的辅助文字**：
   - 保持文字精简、易于快速浏览（总字数 300-800 词）
   - 使用要点式列表，而不是大段段落
   - 使用主动语态书写
   - 文字应与图形互为补充，而不是重复图形内容

4. **添加补充元素**：
   - 用于补充材料的二维码
   - 参考文献（只引用关键论文，通常 5-10 篇）
   - 联系方式与致谢

### 第五阶段：优化与测试

1. **审阅与迭代**：
   - 检查拼写错误
   - 核实所有图形均为高分辨率
   - 确保格式统一一致
   - 确认配色方案整体协调

2. **测试可读性**：
   - 以 25% 比例打印，在 2-3 英尺距离阅读（模拟实际海报在 8-12 英尺距离的观看效果）
   - 在不同显示器上检查颜色
   - 核实二维码功能正常
   - 请同事帮忙审阅

3. **优化以便印刷**：
   - 在 PDF 中嵌入所有字体
   - 核实图像分辨率
   - 检查文件大小是否符合提交要求
   - 如有需要，加入出血位（bleed area）

### 第六阶段：编译与交付

1. **编译最终 PDF**：
   ```bash
   pdflatex poster.tex
   # Or for better font support:
   lualatex poster.tex
   ```

2. **核实输出质量**：
   - 检查所有元素是否可见且位置正确
   - 放大到 100% 检查图形质量
   - 核实颜色是否符合预期
   - 确认 PDF 在不同查看器中都能正常打开

3. **准备印刷**：
   - 如有要求，导出为 PDF/X-1a 格式
   - 保存备份副本
   - 先在普通纸张上试印
   - 在截止日期前 2-3 天下单专业印刷

4. **制作补充材料**：
   - 保存用于社交媒体的 PNG/JPG 版本
   - 制作讲义版本（8.5×11 英寸摘要）
   - 准备用于邮件分享的数字版本

## 与其他技能的配合

本技能可与以下技能有效配合使用：
- **Scientific Schematics**：关键——用于生成海报中的全部示意图与流程图
- **Generate Image / Nano Banana Pro**：用于风格化图形、概念性插图和摘要性视觉元素
- **Scientific Writing**：用于根据论文构建海报内容
- **Literature Review**：用于对研究进行背景铺垫
- **Data Analysis**：用于制作结果图表

**推荐工作流**：在制作 LaTeX 海报之前，始终先使用 scientific-schematics 和 generate-image 技能生成全部视觉元素。

## 应避免的常见误区

**AI 生成图形方面的错误（最常见）**：
- ❌ 单张图形中元素过多（10 个以上）→ 应控制在 3-5 个以内
- ❌ AI 生成图形中的文字过小 → 应指定 "GIANT (100pt+)" 或 "HUGE (150pt+)"
- ❌ 提示词中的细节过多 → 应使用 "SIMPLE" 与 "ONLY X elements"
- ❌ 未指定留白比例 → 应在每条提示词中加入 "50% white space"
- ❌ 8 步以上的复杂流程图 → 应限制在最多 4-5 步
- ❌ 6 项以上的对比图表 → 应限制在最多 3 项
- ❌ 5 项以上指标的关键发现 → 只展示前 3 项

**修复 AI 图形的溢出问题**：
如果 AI 生成的图形出现溢出或文字过小：
1. 在提示词中加入 "SIMPLER" 或 "ONLY 3 elements"
2. 提高字号："150pt+" 而不是 "80pt+"
3. 加入 "60% white space" 而不是 "50%"
4. 去掉次要细节："NO sub-steps"、"NO axis labels"、"NO legend"
5. 用更少的元素重新生成

**设计方面的错误**：
- ❌ 文字过多（超过 1000 词）
- ❌ 字号过小（正文低于 24pt）
- ❌ 低对比度的配色组合
- ❌ 布局杂乱、缺乏留白
- ❌ 各板块之间风格不统一
- ❌ 图像质量低劣或出现像素化

**内容方面的错误**：
- ❌ 没有清晰的叙事线索或核心信息
- ❌ 研究问题或目标过多
- ❌ 过度使用未加解释的专业术语
- ❌ 结果缺少背景说明或解读
- ❌ 缺少作者联系方式

**技术方面的错误**：
- ❌ 海报尺寸与会议要求不符
- ❌ RGB 颜色送到 CMYK 印刷机（导致色差）
- ❌ 字体未嵌入 PDF
- ❌ 文件体积超出提交系统的限制
- ❌ 二维码过小或未经测试

**最佳实践**：
- ✅ 生成元素数不超过 3-5 个的简单 AI 图形
- ✅ 图形中的关键数字使用巨大字号（100pt 以上）
- ✅ 在每条 AI 提示词中指定 "50% white space"
- ✅ 严格遵循会议的尺寸规格
- ✅ 正式印刷前先以缩小比例试印
- ✅ 使用高对比度、具备可访问性的配色方案
- ✅ 保持文字精简、便于快速浏览
- ✅ 附上清晰的联系方式与二维码
- ✅ 仔细校对（海报会放大任何错误！）

## 宏包安装

确保已安装所需的 LaTeX 宏包：

```bash
# For TeX Live (Linux/Mac)
tlmgr install beamerposter tikzposter baposter

# For MiKTeX (Windows)
# Packages typically auto-install on first use

# Additional recommended packages
tlmgr install qrcode graphics xcolor tcolorbox subcaption
```

## 脚本与自动化

`scripts/` 目录中提供的辅助脚本：

- `review_poster.sh`：海报审核与校验
- `generate_schematic.py`：生成科学示意图与图表

## 参考资料

- [references/ai_graphics_for_posters.md](references/ai_graphics_for_posters.md)：完整的 AI
  图形规则、按类型分类的限制、实操提示词示例，以及审核关卡说明。
- [references/latex_poster_reference.md](references/latex_poster_reference.md)：宏包、
  布局、设计、尺寸、模板、图形、配色、排版、二维码。
- [references/compilation_and_quality_control.md](references/compilation_and_quality_control.md)：
  编译引擎及完整的印前质量检查流程。
- [references/poster_patterns_and_presentation.md](references/poster_patterns_and_presentation.md)：
  内容模式、可访问性、展示技巧。
- [references/latex_poster_packages.md](references/latex_poster_packages.md)：beamerposter、
  tikzposter 和 baposter 的详细对比及示例。
- [references/poster_layout_design.md](references/poster_layout_design.md)：布局
  原则、网格系统与视觉流向。
- [references/poster_design_principles.md](references/poster_design_principles.md)：
  排版、色彩理论、视觉层次与可访问性。
- [references/poster_content_guide.md](references/poster_content_guide.md)：内容
  组织方式、写作风格及分节指导。

## 模板

`assets/` 目录中提供的开箱即用海报模板：

- beamerposter 模板（经典、现代、彩色）
- tikzposter 模板（默认、rays、wave、envelope）
- baposter 模板（竖版、横版、极简）
- 来自各科学学科的海报示例
- 配色方案定义及机构模板

加载这些模板，并根据你的具体研究和会议要求进行定制。
