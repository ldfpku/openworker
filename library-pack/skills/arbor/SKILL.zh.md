# Arbor —— 通过假设树精化实现自主优化（Hypothesis Tree Refinement）

## 概述

本技能运行一个**自主优化**（Autonomous Optimization, AO）循环：从一个既有的产物（artifact）和一个可度量的目标出发，通过多轮实验与评估对其进行改进——不需要人工逐步监督，也不会对反馈信号产生过拟合。当瓶颈不在于写出一次好的改动，而在于*组织好几十次试验*，使经验得以积累而非流失时，这正是应该使用的工具。

它实现了来自 *Arbor*（Jin et al., 2026）的**假设树精化**（Hypothesis Tree Refinement, HTR）方法。其核心思想是：将研究状态保存在一棵持久化的**假设树**（hypothesis tree）中，而不是保存在对话历史里。每个节点都绑定一个假设、由该假设产生的提炼出的洞见（insight），以及一个指向实现该假设的产物版本的指针。你扮演的是长期存在的**协调者**（coordinator）角色，拥有这棵树并决定在哪里进行搜索；短期存在的**执行者**（executor）子代理各自在独立的 git worktree 中测试一个假设，并回报结果。一道**留出集（held-out）合并关卡**只会在改动在搜索过程中从未被优化针对的*测试*评估器上有所提升时才予以放行。正是这一点，把试错变成了可积累、可审计的研究过程。

对于所有的记录工作（创建节点、写入证据、传播洞见、剪枝、合并关卡、Observe 投影），使用 `scripts/tree.py` 状态管理器。它负责保持状态一致，让你能把判断力用在思考证据*意味着什么*上。

## 何时使用本技能

在任务是**在某个评估器（evaluator）之下对具体产物进行迭代式改进**时，选用 Arbor：
- 模型训练：调整优化器/架构/训练方案，以降低损失或用更少的步数达到目标。
- 工具箱（harness）/智能体工程：提高某个智能体循环、搜索工具箱或工具调用脚手架的通过率或准确率。
- 数据合成：改进由下游模型表现所评判的生成/过滤流水线。
- 基准优化：MLE-bench / Kaggle 风格的"改进提交结果"任务。
- 提示词/系统优化，且你能够自动为输出打分。

区分性的信号是：存在一个**你可以修改的产物**、一个**目标**、一种给候选方案**打分**的方式，并且你预期要运行**大量实验**。如果用户只想要一次性的修复或一次性的答案，这套流程就是杀鸡用牛刀——直接完成任务即可。如果他们想要的是没有评估器的开放式构思，请改用 `hypothesis-generation` 或 `scientific-brainstorming`。

## AO 设置——先把这个定下来

在进行任何实验之前，先确立任务元组 `(M_0, O, E_dev, E_test)`。把这一步做对，比之后任何决策都更重要，因此要明确地予以确认：

- **M_0 —— 初始材料（initial material）**：待改进的产物（一个代码仓库、一个脚本、一份配置、一段提示词）。确保它处于 git 管理之下，并且当前能够运行。
- **O —— 目标（objective）**：自然语言描述的目标，以及指标的*方向*（是最大化准确率，还是最小化损失/步数）。
- **E_dev —— 开发评估器（development evaluator）**：一条在搜索过程中可以自由运行、为候选方案打分的命令。要求快速、可重复。
- **E_test —— 留出集测试评估器（held-out test evaluator）**：一个*独立*的评估器（不同的随机种子、不同的数据划分，或更大规模的运行），仅在合并关卡处使用。它绝不能被用作搜索的判定标准（oracle）——这正是它存在的全部意义。

如果用户没有给出一个干净的 dev/test 划分，**自行构建一个，并明确说明这一点**。dev/test 分离正是捕捉过拟合的机制：一个在 dev 上获胜但在 test 上没有获胜的候选方案，不算是成功，而是一个警示——你正在利用反馈信号本身的漏洞。没有这一机制，自主搜索会可靠地走向过拟合。

初始化本次运行：

```bash
python scripts/tree.py init \
  --objective "Improve BrowseComp answer accuracy on the search harness" \
  --dev-eval "python eval.py --split dev --n 50" \
  --test-eval "python eval.py --split test --n 300" \
  --material "." --metric-direction max --branching 3 --max-depth 2 --budget 12
```

`--branching` 表示每个父节点下要提出多少个同级假设（sibling hypotheses）；`--max-depth 2` 将方向性想法保持在深度 1，将具体的干预措施保持在深度 2（这是论文中的默认设置）；`--budget` 是协调者循环的次数。从小规模开始（10-20 个循环）——结构化搜索胜过蛮力搜索，如果仍在取得进展，你可以再延长。

## 协调者循环

你要反复运行由六个步骤组成的循环。这是 HTR 的核心；不要把它坍缩成随意的编辑。每个循环运行一次 `python scripts/tree.py cycle` 来跟踪预算。

### 1. Observe（观察）
每个循环开始时，都要重新以树为依据，而不是依赖你对对话内容的记忆：

```bash
python scripts/tree.py observe
```

这会打印出目标、全局洞见、当前活跃的前沿（可供选择的假设）、已执行节点及其证据、已剪枝的经验教训（负面约束），以及当前最佳产物。把这棵树当作真相的来源，这正是在长时间运行、上下文被压缩丢弃细节之后，让你保持连贯的关键所在。

### 2. Ideate（构思）
挑选一个有前景的父节点，并在其下提出若干子假设。**以树中已有的证据为条件**——这正是 Arbor 与随机搜索的区别所在：
- 已验证的洞见是你可以在其之上继续构建的假设前提。
- 已剪枝的节点是应当避开的死路。
- 一个"部分正确"的结果是*一个更精确假设的起点*，而不是放弃这个方向的理由。

每个假设都应当是一个**关于改变产物将如何影响指标的可证伪的论断**，而不是一个模糊的意图。深度 1 的节点是宽泛的方向（"搜索工具箱丢失了它已经检索到的正确答案"）；深度 2 的节点是具体的、可执行的干预措施（"运行 K=5 次独立 rollout，并按证据档案汇总而非多数投票"）。

```bash
python scripts/tree.py add-node --parent n0 --hypothesis "Verification, not retrieval, is the bottleneck: candidates are found but discarded"
python scripts/tree.py add-node --parent n4 --hypothesis "Decompose the question into atomic constraints and verify each independently"
```

### 3. Select（选择）
选择接下来要运行哪些待处理的叶子节点。**选择并非纯粹的分数最大化**——选中一个假设，可能是因为它有较强的先验证据，可能是因为它能解决其同级节点所暴露出的某个含糊之处，也可能是因为它一旦失败会澄清某个重要假定。在延迟反馈的条件下，前沿控制奖励的是信息量大的实验，而不仅仅是看起来有前景的实验。

### 4. Dispatch（派发）
将每个被选中的假设作为**在独立 worktree 中运行的执行者子代理**来执行（使用带 `isolation: "worktree"` 的 Agent 工具，或让执行者自行用 `git worktree add` 创建一个）。隔离性很重要：并行运行的实验不能相互覆盖，也不能覆盖当前的最佳结果，探索性的改动在通过合并关卡之前都应保持隔离状态。

当各个同级假设彼此独立时，**并行**派发它们（在一条消息中发出多个 Agent 调用）——正是同一方向内的对比证据，才使得之后的剪枝与抽象成为可能。

给每个执行者提供一份紧凑的、**与假设绑定**的任务简报。完整模板见 `references/executor-brief.md`。使 HTR 得以成立的约定是：**当指标停滞不前时，执行者不得更改假设本身**。它可以修复自己的代码并重新运行，但 `h_n` 是固定不变的——否则返回的分数就不再是针对被指派节点的证据，整棵树的语义也会因此崩坏。执行者应恰好返回以下四项内容：
- **dev_score** —— 开发评估器的结果（用于选择）；
- **result** —— 关于发生了什么的事实性总结；
- **insight** —— 提炼出的、可复用的经验教训（*为什么*这个结果支持、削弱或界定了该假设）；
- **branch_ref** —— 保存该产物的 git 分支/提交/worktree 路径。

在派发之前将节点标记为 `running`（`tree.py set-status --node n5 --status running`），以使 Observe 投影保持准确。

### 5. Backpropagate（反向传播）
当某个执行者返回结果时，先将其报告写入该节点，然后**将经验教训向上抽象**：

```bash
python scripts/tree.py set-evidence --node n5 --dev-score 70.0 \
  --result "K=5 dossier aggregation recovers answers in minority rollouts" \
  --insight "Correct answers often appear in a minority of rollouts; aggregation beats majority vote" \
  --branch-ref "wt/n5"

python scripts/tree.py propagate --node n5 \
  --insight "Candidate coverage, not verification, limits this direction" --to-root
```

这一步正是使这棵树超越单纯日志记录的关键所在。一个叶子层面的观察结果（"数据接口不匹配"）应当被提升为方向层面的约束，如果它具有足够的普适性，还应进一步提升为塑造未来构思的全局先验。**洞见的传播是驱动 HTR 大部分收益的组件**——在论文的 MLE-Bench Lite 消融实验中，一棵*没有*洞见反馈的树，其表现甚至比完全没有树结构的扁平实验队列更差（54.5% 对比 63.6% 的任意奖牌率，而完整系统能达到 81.8%）。仅有层级结构是不够的：真正重要的是语义记忆。因此要在抽象这一步真正花心思，不要只是把叶子节点的洞见原样照抄到上层。

### 6. Decide（决策）
基于新的证据决定接下来怎么做：继续拓展某个方向、剪掉某个已被证伪的子树，或尝试合并某个候选方案。

- **剪枝**死路，并记录*原因*——这个原因会成为一条负面约束：
  ```bash
  python scripts/tree.py prune --node n7 --reason "search-augmented judge overfits dev questions; no test transfer"
  ```
- **合并关卡**——只有当某个候选方案在 `E_test` 上有所提升时，才将其提升为新的最佳结果。在一个*全新*的 worktree 中运行测试评估器（而非 dev worktree，以避免信息泄漏），然后：
  ```bash
  python scripts/tree.py merge --node n5 --test-score 67.67 --branch-ref "wt/n5"
  ```
  如果关卡拒绝了它，这本身就是有信息量的：一个在 dev 上高分、在 test 上低分的候选方案，恰恰说明这个方向可能是在利用 dev 信号的漏洞，而不是在产生可迁移的改进。要记录下这个经验教训，不要悄悄地照样把它提升上去。

重复此循环，直到预算用尽、前沿被穷尽，或进展明显已经停滞。

## 结束本次运行

当你停止时，请撰写一份简短的报告（参见 `references/report-template.md`），涵盖以下内容：
- 最终的最佳产物、其测试分数，以及相对于 `M_0` 的提升幅度；
- 这棵树（`python scripts/tree.py status`）作为已尝试内容的审计轨迹；
- 主要的假设转变——任务理解在整个运行过程中是如何加深的（早期节点测试宽泛的机制；后期节点发现这些机制的局限；祖先节点的洞见将这些经验压缩为最终设计背后的约束条件）；
- 已合并与已探索的对比：很多节点能提升 dev 表现，但通过测试关卡的节点要少得多——诚实地报告这一差距，而不要夸大 dev 上的胜利。

始终在一个命名分支上留下一个真实的、可运行的 `M_best`，并告诉用户如何检出（check out）它。

## 使这套方法奏效的原则（而非死板的规则）

这些内容来自论文的分析；理解*为什么*比机械地遵循它们更重要。

- **树是记忆所在，对话不是**。 在长时间的跨度中，你的上下文会被压缩。每个循环都要重新 Observe，使决策建立在持久的证据之上，而不是有损的摘要之上。
- **结构化搜索，而非更多采样**。 Arbor 的收益来自预算是如何被*组织*的——维持相互竞争的假设、比较同级节点、将经验教训延续下去——而不是来自花费更多的 token。不要漫无目的地铺开，每个实验都应当以树中已知的信息为条件。
- **Dev 指引方向，Test 决定录用**。 自由地使用 dev 反馈来引导探索，但绝不能让一个 dev 上的胜利在未经 test 确认的情况下进入最终产物。dev/test 之间的分歧本身就是一个值得解读的信号。
- **执行者受假设约束**。 局部的工程灵活性（编辑、调试、重新运行）没有问题；但为了追求更好的数字而悄悄更改假设是不行的——这会摧毁证据本身的意义。
- **失败是约束条件，而非噪声**。 一个被证伪的假设会告诉你解决方案必须避开什么。带着原因被剪枝，比被剪枝后就被遗忘更有价值。

## 参考文件

- `references/htr-methodology.md` —— 对 HTR、节点结构、六个步骤以及论文中经验教训（消融实验、迁移能力、成本）的更深入说明。当你想了解某个设计选择背后的理由时阅读。
- `references/executor-brief.md` —— 你交给每个执行者子代理的任务简报模板。
- `references/report-template.md` —— 最终报告的结构。
- `references/arbor-upstream.md` —— 如何安装并运行来自 RUC-NLPIR/Arbor 的独立 `arbor` CLI 工具，而非以原生方式对其进行编排，以及各自适用的场景。
