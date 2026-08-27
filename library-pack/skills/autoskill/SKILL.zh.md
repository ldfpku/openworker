# autoskill

> **需要一个正在运行的 [screenpipe](https://github.com/screenpipe/screenpipe) 守护进程**。 本技能没有其他数据来源——它只从本地 screenpipe HTTP API（默认为 `http://localhost:3030`）读取数据。如果该守护进程未运行，`run()` 会抛出 `ScreenpipeUnreachable` 异常并给出安装说明。

> **网络访问与环境变量**。 本技能会向以下两处发起经过身份验证的 HTTP 请求：(a) 用户本地环回地址上的 screenpipe 守护进程，以及 (b) 用户配置的 LLM 后端——即 `http://localhost:1234/v1`（LM Studio，默认）、`https://api.anthropic.com`（可选启用的 Claude），或用户自行提供的 BYOK Foundry 网关三者之一。本技能会读取三个环境变量——`SCREENPIPE_TOKEN`、`ANTHROPIC_API_KEY`、`FOUNDRY_API_KEY`——且每个变量只用于向其名称所对应的那一个端点进行身份验证。不存在其他网络目的地，没有遥测数据上报，也不会向任何第三方泄露数据。

## 概述

将用户自身的工作流历史——由本地 [screenpipe](https://github.com/screenpipe/screenpipe) 守护进程被动记录——转化为新的技能。本技能是按需触发的：用户以一个时间窗口调用它，它会查询 screenpipe 的本地 HTTP API，对重复出现的工作流模式进行聚类，将每个模式与本仓库中现有的技能进行比对，并生成一个暂存文件夹，其中包含可供用户审阅、编辑和转正（promote）的提案。

## 何时使用本技能

在用户提出以下请求时调用本技能：
- "分析我过去 4 小时/一天/一周的工作，并提出新技能建议。"
- "看看我最近做了什么，告诉我哪些还没有被覆盖到。"
- "根据我最近的工作流起草一个技能。"
- "为我重复做的工作流找出组合方案（composition recipe）。"

**不要**在以下情况下调用本技能：针对 screenpipe 本身的一次性提问、实时屏幕查询，或没有用户明确请求的情况——本技能分析的是敏感的本地内容，必须始终由用户显式触发。

## 隐私姿态

- **screenpipe 在采集时就负责应用/窗口过滤**。 通过把 `references/screenpipe-config.yaml` 复制到用户的 screenpipe 配置中，可安装一份初始的拒绝清单（deny-list）。敏感应用（密码管理器、即时通讯、银行类应用）从一开始就不会被做 OCR 识别。
- **原始 OCR 内容永远不会离开本机**。 `scripts/fetch_window.py` 通过 localhost HTTP 拉取数据。`scripts/cluster.py` 将时间线压缩为应用/时长/标题的摘要。`scripts/redact.py` 会在任何聚类摘要送达 LLM 之前，清除电子邮件、API 密钥、bearer 令牌以及电话号码，作为纵深防御手段。
- **LLM 后端默认使用 `local`（本地）。** 推荐的配置是运行 `Gemma-4-31B-it` 的 [LM Studio](https://lmstudio.ai/)——它在大多数工作站 GPU 都能容纳的体量下具备强大的推理能力，且数据永远不会离开你的机器。云端后端（`claude`、`foundry`）是可选启用的，并在 `config.yaml` 中为明确需要它们的用户提供了文档说明。无论选择哪种后端，检测和嵌入计算始终在本地进行。
- **演练模式（Dry-run mode）**（`--plan`）会在发起任何 LLM 调用之前，打印出即将被分析的确切时间线。
- **面向 localhost 的 TLS**（可选，适用于有企业策略要求的场景）：Caddy 配置模式参见 `references/https-proxy.md`。

## 前置条件

### 1. Screenpipe 守护进程

既可以安装官方发行版，也可以从源码构建。无论哪种方式，该守护进程默认都会在 `localhost:3030` 上绑定 HTTP。

**从源码构建**（如果你只想要 CLI 守护进程而不想要桌面 GUI，推荐此方式）：

```bash
git clone --depth 1 https://github.com/mediar-ai/screenpipe.git
cd screenpipe
cargo build -p screenpipe-engine --release
# System deps (macOS): cmake + full Xcode.app (not just Command Line Tools).
#   brew install cmake
#   # if xcodebuild plug-ins error: sudo xcodebuild -runFirstLaunch
./target/release/screenpipe doctor   # confirm permissions + ffmpeg
./target/release/screenpipe record --disable-audio --use-pii-removal
```

首次运行会提示请求 macOS 屏幕录制权限。授予权限后重新启动。

### 2. Screenpipe API 令牌

本地 API 现在要求使用 bearer 身份验证。获取你的令牌并将其导出：

```bash
export SCREENPIPE_TOKEN=$(screenpipe auth token)
```

（或者直接在 `config.yaml` 中设置 `screenpipe.token`——但更推荐使用环境变量，这样可以让密钥不出现在版本控制中。）

### 3. Python 环境

从仓库根目录，通过 `pipenv` 安装：

```bash
pipenv install httpx pyyaml sentence-transformers
```

嵌入模型（`sentence-transformers/all-MiniLM-L6-v2`，约 80 MB）会在首次运行时下载。

### 4. 本地 LLM（默认路径）——LM Studio

- 安装 [LM Studio](https://lmstudio.ai/)。
- 下载 `Gemma-4-31B-it`（或另一个具备强大推理能力的模型；相应调整 `config.yaml` 中的 `local.model`）。
- 通过 CLI 加载它以便无 GUI 使用：

```bash
lms load gemma-4-31b-it --context-length 131072 --gpu max -y
lms status   # confirm server running on :1234
```

### 5. 云端 LLM 后端（可选，需主动启用）

仅在你明确选择不使用本地方案时才需要：
- `claude`：设置 `ANTHROPIC_API_KEY`，将 `config.yaml` 中的 `backend` 切换为 `claude`。
- `foundry`：设置 `FOUNDRY_API_KEY`，将 `backend` 切换为 `foundry`，并将 `foundry.endpoint` 设置为你所在企业的网关 URL。

## 架构

```
screenpipe daemon (user-installed)
        │  HTTP on localhost:3030
        ▼
scripts/fetch_window.py    → normalized timeline events
scripts/redact.py          → regex scrub (defense-in-depth)
scripts/cluster.py         → sessions + clusters (local only)
scripts/match_skills.py    → top-k vs existing 135 skills (local embeddings)
scripts/synthesize.py      → LLM judge: reuse / compose / novel
        │
        ▼
~/.autoskill/proposed/<timestamp>/        (default; override with --out)
  ├── report.md
  ├── composition-recipes/<name>/SKILL.md
  └── new-skills/<name>/SKILL.md

scripts/promote.py         → user-approved proposal → skills/<name>/
```

## 工作流程

本技能提供了一个统一的 CLI，位于 `scripts/autoskill.py`，含有三个子命令：

```bash
python scripts/autoskill.py doctor   --config config.yaml --skills-dir ../
python scripts/autoskill.py run      --start ... --end ... --config config.yaml
python scripts/autoskill.py promote  --proposed ~/.autoskill/proposed/<ts> --skills-dir ../ --name <skill>
```

### 0. 用 `doctor` 做预检

在一次完整运行之前，一次性核实每一项依赖：

```bash
python scripts/autoskill.py doctor \
  --config skills/autoskill/config.yaml \
  --skills-dir skills
```

该报告涵盖 `config`（后端选择是否有效）、`skills_dir`（是否存在）、`screenpipe`（是否可访问且已通过身份验证），以及 `llm`（LM Studio 是否在提供服务，或 API 密钥是否存在）。任何一项失败都会以非零状态码退出，出问题的那一行会标记为 `error`。

### 1. 运行流水线

```bash
export SCREENPIPE_TOKEN=$(screenpipe auth token)
python scripts/autoskill.py run \
  --start "2026-04-17T00:00:00Z" \
  --end   "2026-04-17T23:59:59Z" \
  --config skills/autoskill/config.yaml \
  --skills-dir skills
```

提案默认落在 `~/.autoskill/proposed/<timestamp>/` 中，从而使实验性输出保留在技能仓库之外。传入 `--out PATH` 可覆盖该默认位置。

内部流程如下：
1. **获取（Fetch）**——`fetch_window` 对 screenpipe 的 `/search` 端点进行分页请求，将事件归一化为 `{ts, app, window_title, text, content_type}`。
2. **脱敏（Redact）**——`redact` 从 OCR 文本和窗口标题中清除电子邮件、API 密钥、bearer 令牌和电话号码，作为叠加在 screenpipe 自身 PII 清除机制之上的纵深防御。
3. **聚类（Cluster）**——`segment_sessions` 按空闲间隔（默认 10 分钟）切分，并丢弃过短的会话；`cluster_sessions` 按应用签名对会话进行分组，并保留大小达到 `min_cluster_size`（默认 2）的聚类。
4. **匹配（Match）**——`load_skill_descriptions` 从 `skills/` 目录下每个 `SKILL.md` 中读取 frontmatter；`top_k_matches` 使用本地的 `sentence-transformers` 嵌入（余弦相似度）为每个聚类在全部技能中排序。
5. **综合（Synthesize）**——`synthesize` 提示已配置的 LLM 后端将每个聚类分类为 `reuse`（复用）、`compose`（组合）或 `novel`（新颖），并在适当的情况下生成一份 SKILL.md 正文。
6. **报告（Report）**——写出 `<out_dir>/<ts>/report.md`，并为每个提案写出 `new-skills/<name>/SKILL.md` 或 `composition-recipes/<name>/SKILL.md`。

添加 `--dry-run` 会在聚类之后就停止；这会跳过 LLM 调用（以及 sentence-transformers 的加载），只写出 `plan.md` 供查看。

### 2. 审阅并转正

打开 `~/.autoskill/proposed/<ts>/report.md`，就地编辑草稿，删除任何不想要的内容。然后：

```bash
python scripts/autoskill.py promote \
  --proposed ~/.autoskill/proposed/2026-04-17T14-30-00 \
  --skills-dir skills \
  --name zotero-pubmed-helper
```

`promote` 会把该目录移动到 `skills/<name>/` 下，并拒绝覆盖已存在的技能。如果找不到该提案，或者目标已经存在，会以非零状态码退出，并给出友好的错误提示。

## 配置

完整结构见 `config.yaml`。默认值（本地优先）：

```yaml
backend: local
local:
  endpoint: http://localhost:1234/v1   # LM Studio's Developer server
  model: Gemma-4-31B-it

screenpipe:
  url: http://localhost:3030           # or https://screenpipe.local via Caddy

cluster:
  min_session_minutes: 5
  idle_gap_minutes: 10
  min_cluster_size: 2
```

要启用某个云端后端：

```yaml
backend: claude                         # or foundry
claude:
  model: claude-opus-4-7
```

## 组合方案（Composition recipes）与新技能

- **compose（组合）**：LLM 判断认为串联现有技能就能覆盖该工作流。生成的 SKILL.md 有意保持精简——只有 frontmatter 加上一个按顺序调用现有技能的"Workflow"部分。发现该技能的同一个 agent 运行环境随后就可以端到端地调用它。
- **novel（新颖）**：没有任何现有技能的组合能够覆盖该工作流。这种情况下会起草一份更完整的 SKILL.md，仍然遵循本仓库的惯例（frontmatter、Overview、When to Use、Workflow）。用户在转正新技能草稿之前，应始终先进行审阅。

## 测试

本技能由仓库根目录下 `tests/autoskill/` 中一个小型的 pytest 套件覆盖。每个脚本都通过依赖注入（模拟 HTTP 传输、存根后端、存根嵌入器）进行独立的单元测试：

```bash
python -m pytest tests/autoskill -v
```

## 与本仓库中其他技能的组合

autoskill 的嵌入索引覆盖了全部 135 个同级技能。看起来像科学写作的工作流会匹配到 `scientific-writing` / `literature-review` / `citation-management`；图表相关的工作会匹配到 `scientific-schematics` / `generate-image` / `infographics`；幻灯片准备工作会匹配到 `scientific-slides` / `pptx`；等等。当某个聚类对两到三个同级技能的得分都很高时，生成的组合方案会明确点出它们的名字，从而让用户未来的 agent 调用能够直接使用本仓库中已经记录好的优化路径。
