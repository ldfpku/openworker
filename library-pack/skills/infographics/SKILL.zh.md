# 信息图(Infographics)

## 概述

信息图是信息、数据或知识的可视化呈现，旨在快速、清晰地展示复杂内容。**此技能使用 Nano Banana Pro AI 生成信息图，由 Gemini 3.6 Flash 进行质量审阅，并用 Perplexity Sonar 进行研究调研**。

**工作原理**:
- (可选)**研究阶段**:使用 Perplexity Sonar 收集准确的事实和统计数据
- 用自然语言描述你的信息图
- Nano Banana Pro 自动生成出版级质量的信息图
- **Gemini 3.6 Flash 依据文档类型阈值审阅质量**
- **智能迭代**:仅在质量低于阈值时才重新生成
- 数分钟内产出专业级成品
- 无需设计技能

**按文档类型划分的质量阈值**:
| 文档类型 | 阈值 | 说明 |
|---------------|-----------|-------------|
| marketing(营销) | 8.5/10 | 营销材料——必须有说服力 |
| report(报告) | 8.0/10 | 商业报告——专业质量 |
| presentation(演示) | 7.5/10 | 幻灯片、演讲——清晰且引人入胜 |
| social(社媒) | 7.0/10 | 社交媒体内容 |
| internal(内部) | 7.0/10 | 内部使用 |
| draft(草稿) | 6.5/10 | 工作草稿 |
| default(默认) | 7.5/10 | 通用场景 |

**只需描述你想要的内容,Nano Banana Pro 就会将其创建出来**。

## 快速开始

只需描述即可生成任意信息图:

```bash
# Generate a list infographic (default threshold 7.5/10)
python skills/infographics/scripts/generate_infographic.py \
  "5 benefits of regular exercise" \
  -o figures/exercise_benefits.png --type list

# Generate for marketing (highest threshold: 8.5/10)
python skills/infographics/scripts/generate_infographic.py \
  "Product features comparison" \
  -o figures/product_comparison.png --type comparison --doc-type marketing

# Generate with corporate style
python skills/infographics/scripts/generate_infographic.py \
  "Company milestones 2010-2025" \
  -o figures/timeline.png --type timeline --style corporate

# Generate with colorblind-safe palette
python skills/infographics/scripts/generate_infographic.py \
  "Heart disease statistics worldwide" \
  -o figures/health_stats.png --type statistical --palette wong

# Generate WITH RESEARCH for accurate, up-to-date data
python skills/infographics/scripts/generate_infographic.py \
  "Global AI market size and growth projections" \
  -o figures/ai_market.png --type statistical --research
```

**幕后发生的事情**:
1. **(可选)研究**:Perplexity Sonar 收集准确的事实、统计数据和资料
2. **第 1 次生成**:Nano Banana Pro 依据设计最佳实践创建初始信息图
3. **第 1 次审阅**:**Gemini 3.6 Flash** 依据文档类型的阈值评估质量
4. **决策**:如果质量 >= 阈值 → **完成**(不需要更多迭代!)
5. **若低于阈值**:基于评审意见改进提示词，重新生成
6. **重复**:直到质量达标，或达到最大迭代次数

**智能迭代的好处**:
- ✅ 如果第一次生成就足够好，可以节省 API 调用
- ✅ 营销材料的质量标准更高
- ✅ 草稿/内部用途的周转更快
- ✅ 每种使用场景都能获得恰当的质量

**输出**:带版本号的图片，加上一份详细的审阅日志，其中包含质量分数、评审意见以及提前停止的相关信息。

## 何时使用此技能

在以下情况使用 **infographics** 技能:
- 以可视化格式呈现数据或统计信息
- 为项目里程碑或历史沿革制作时间线可视化
- 讲解流程、工作流程或分步指南
- 并排比较不同选项、产品或概念
- 以引人入胜的可视化格式总结要点
- 制作基于地理位置或地图的数据可视化
- 构建层级结构图或组织架构图
- 设计社交媒体内容或营销材料

**以下场景请改用 scientific-schematics**:
- 技术流程图和电路图
- 生物学通路和分子示意图
- 神经网络架构图
- CONSORT/PRISMA 方法学图示

---

## 研究集成

### 自动数据收集(`--research`)

在创建需要准确、最新数据的信息图时，使用 `--research` 标志，自动通过 **Perplexity Sonar Pro** 收集事实和统计数据。

```bash
# Research and generate statistical infographic
python skills/infographics/scripts/generate_infographic.py \
  "Global renewable energy adoption rates by country" \
  -o figures/renewable_energy.png --type statistical --research

# Research for timeline infographic
python skills/infographics/scripts/generate_infographic.py \
  "History of artificial intelligence breakthroughs" \
  -o figures/ai_history.png --type timeline --research

# Research for comparison infographic
python skills/infographics/scripts/generate_infographic.py \
  "Electric vehicles vs hydrogen vehicles comparison" \
  -o figures/ev_hydrogen.png --type comparison --research
```

### 研究阶段提供什么

研究阶段会自动完成:

1. **收集关键事实**:关于该主题的 5-8 条相关事实和统计数据
2. **提供背景信息**:准确呈现所需的背景资料
3. **找出数据要点**:具体的数字、百分比和日期
4. **引用来源**:提及主要的研究或来源
5. **优先近期信息**:侧重于 2023-2026 年的信息

### 何时使用研究功能

**以下情形请启用研究功能(`--research`):**
- 需要准确数字的统计类信息图
- 市场数据、行业统计或趋势
- 科学或医学信息
- 时事或近期动态
- 任何准确性至关重要的主题

**以下情形请跳过研究功能**:
- 简单的概念性信息图
- 内部流程文档
- 你已在提示词中提供全部数据的主题
- 对速度要求较高的生成场景

### 研究输出

启用研究功能后，会额外创建以下文件:
- `{name}_research.json` - 原始研究数据和来源
- 研究内容会被自动纳入信息图的提示词中

---

## 信息图类型

通过 `--type` 支持十种类型:`statistical`(统计型)、`timeline`(时间线型)、`process`(流程型)、`comparison`(对比型)、
`list`(列表型)、`geographic`(地理型)、`hierarchical`(层级型)、`anatomical`(解剖型)、`resume`(简历型)以及 `social`(社媒型)。每种类型的用途、
所期望的数据形态，以及范例提示词，见
[references/infographic_type_catalog.md](references/infographic_type_catalog.md) 和
[references/infographic_types.md](references/infographic_types.md)。

## 样式预设

### 行业风格(`--style`)

| 风格 | 颜色 | 最适合 |
|-------|--------|----------|
| `corporate`(企业) | 藏青、钢蓝、金色 | 商业报告、金融 |
| `healthcare`(医疗) | 医疗蓝、青色、浅青色 | 医疗、健康养生 |
| `technology`(科技) | 科技蓝、板岩灰、紫罗兰 | 软件、数据、AI |
| `nature`(自然) | 森林绿、薄荷绿、大地棕 | 环境、有机主题 |
| `education`(教育) | 学院蓝、浅蓝、珊瑚色 | 学习、学术 |
| `marketing`(营销) | 珊瑚色、青绿、黄色 | 社交媒体、活动推广 |
| `finance`(金融) | 藏青、金色、绿/红 | 投资、银行 |
| `nonprofit`(非营利) | 暖橙、鼠尾草绿、沙色 | 社会公益事业、慈善 |

```bash
# Corporate style
python skills/infographics/scripts/generate_infographic.py \
  "Q4 Results" -o q4.png --type statistical --style corporate

# Healthcare style
python skills/infographics/scripts/generate_infographic.py \
  "Patient Journey" -o journey.png --type process --style healthcare
```

---

## 色盲友好调色板

### 可用调色板(`--palette`)

| 调色板 | 颜色 | 说明 |
|---------|--------|------|
| `wong` | 橙、天蓝、绿、蓝、朱红 | 最广泛推荐 |
| `ibm` | 群青、靛蓝、洋红、橙、金 | IBM 的无障碍调色板 |
| `tol` | 12 色扩展调色板 | 适用于类别较多的情形 |

```bash
# Wong's colorblind-safe palette
python skills/infographics/scripts/generate_infographic.py \
  "Survey results by category" -o survey.png --type statistical --palette wong
```

---

## 智能迭代优化与 CLI

生成-审阅-优化循环、每一个命令行选项以及配置说明，都在
[references/iterative_refinement.md](references/iterative_refinement.md) 中。

## 提示词编写技巧

### 具体说明内容

✓ **好的提示词**(具体、详细):
```
"5 benefits of meditation: reduces stress, improves focus, 
better sleep, lower blood pressure, emotional balance"
```

✗ **避免模糊的提示词**:
```
"meditation infographic"
```

### 包含数据要点

✓ **好的示例**:
```
"Market growth from $10B (2020) to $45B (2025), CAGR 35%"
```

✗ **模糊的示例**:
```
"market is growing"
```

### 明确指定视觉元素

✓ **好的示例**:
```
"Timeline showing 5 milestones with icons for each event"
```

---

## 参考文件

需要详细指导时，加载这些参考文件:

- **`references/infographic_types.md`**:所有 10 余种类型的扩展模板
- **`references/design_principles.md`**:视觉层级、布局、排版
- **`references/color_palettes.md`**:完整的调色板规格说明

---

## 故障排查

### 常见问题

**问题**:信息图中的文字无法辨认
- **解决方案**:减少文字内容；用 --type 指定布局类型

**问题**:颜色冲突或不便于无障碍访问
- **解决方案**:使用 `--palette wong` 获得色盲友好的颜色

**问题**:质量分数过低
- **解决方案**:用 `--iterations 3` 增加迭代次数；使用更具体的提示词

**问题**:生成的信息图类型不对
- **解决方案**:始终指定 `--type` 标志以获得一致的结果

---

## 与其他技能的集成

此技能能与以下技能协同工作:

- **scientific-schematics**:用于技术图表和流程图
- **market-research-reports**:用于商业报告的信息图
- **scientific-slides**:用于演示文稿中的信息图元素
- **generate-image**:用于非信息图类的视觉内容

---

## 快速参考核对清单

生成之前:
- [ ] 清晰、具体的内容描述
- [ ] 已选定信息图类型(`--type`)
- [ ] 风格与受众相符(`--style`)
- [ ] 已指定输出路径(`-o`)
- [ ] 已配置 API key

生成之后:
- [ ] 查看生成的图片
- [ ] 查阅审阅日志中的分数
- [ ] 如有需要，用更具体的提示词重新生成

---

使用此技能，借助 Nano Banana Pro AI 的强大能力和智能质量审阅，创建专业、无障碍且视觉上引人入胜的信息图。
