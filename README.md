# OpenWorker 中文版

> **English** — A Simplified-Chinese build of **[andrewyng/openworker](https://github.com/andrewyng/openworker)**, with model access routed through Cloudflare so it works from mainland China. For the original English app, go upstream.

**OpenWorker 是一个装在你自己电脑上的 AI 助手。** 它读写你授权的文件夹、用你连上的工具、多步骤地把一件事做完——交给你的是**成品**：一份排好版的文档、一条带数字的回复、一张理顺的日程，而不是一段对话。

界面是简体中文的，模型走公司统一的通路，你不需要自己申请任何海外账号。

---

## 能做什么

- **出成品。** 文档、表格、报告、网页，直接落成文件，能打开、能发出去。
- **专家上阵。** 内置 270+ 位中文专家和 160+ 个科研技能，即点即用；也能勾几位组一支专家团，分工协作把大活干完。
- **用你每天用的工具。** GitHub、Slack、Jira、Notion、Linear、HubSpot、Outlook、monday.com、Gmail、Google 日历等 40 个连接器，加上**你的终端和本地文件**。任何支持 [MCP](https://modelcontextprotocol.io/) 的工具也能接进来，逐个授权。
- **在 Slack 里使唤它。** 在频道里 `@OpenWorker`，它在你桌面上开一个会话干活，答案回到原来的话题串里。
- **定时干活。** 早报、周报、盯着某个频道——按时跑，结果连完整过程一起留在应用里。
- **动手前先问你。** 写文件、发消息、执行命令都要你点头。无人值守时它把要问的事攒进收件箱，不会自作主张。

---

## 安装

> ⚠️ **v0.1.8 还是草稿 Release，尚未发布**，下面的链接暂时取不到东西。发布后即可下载。

**[github.com/ldfpku/openworker/releases](https://github.com/ldfpku/openworker/releases)**

| 系统 | 装哪个 |
| --- | --- |
| Windows 10/11 (x64) | `OpenWorker-windows-setup.exe` |
| macOS (Apple 芯片) | `OpenWorker-macos-arm64.dmg` |
| macOS (Intel) | `OpenWorker-macos-x64.dmg` |

**首次打开会被系统拦一下，这是正常的**——安装包没有买代码签名证书：

- **Windows**：弹出「Windows 已保护你的电脑」，点 **「更多信息」→「仍要运行」**。
- **macOS**：先在终端跑一次 `xattr -cr /Applications/OpenWorker.app`，然后正常打开。

装好之后应用会自己更新，不用再手动下载。

> **别去 `download.openworker.com` 下载。** 那是上游的英文原版；装上之后它的自动更新会把中文版覆盖掉。

---

## 第一次使用

### 你需要管理员给你什么

| | |
| --- | --- |
| **一个登记过的公司邮箱** | 用来证明「你是名单里的人」。就是管理员发安装包给你时用的那个。 |
| **一把以你名字命名的 Gemini API key** | 调用 Google 模型的凭证，管理员发给你，不用自己申请。 |

**这两样都是 Gemini 用的，缺一样都不行**——只登录不填 key、或只填 key 不登录，都会报错：登录说明你是谁，key 才是真正去调模型的凭证。GPT / Claude 那条线（Cloudflare AI Gateway）**什么都不用要**，登录就行（见下）。

> 发给你的 key **是公司的**：别转给别人、别贴进群聊、别提交进任何代码仓库。它以你的名字命名，用了多少一目了然；真出事对得上号的就是你那一把。

### 配置模型

打开 **设置 ▸ 模型**，两条路按需要选：

| | **Gemini** | **GPT / Claude / 其他** |
| --- | --- | --- |
| 怎么开通 | 点「登录」→ 浏览器收验证码 → 再填上管理员给你的 key | 点「登录」→ 浏览器里验明身份，完事 |
| 要填东西吗 | 要填那把 key | **什么都不填**——网关地址内置在应用里 |
| 之后 | 令牌到期会提示重新登录 | 两周内自动续期，不用管 |

两条路都不需要你安装任何额外软件，也不需要你自己的任何 Cloudflare 账号。

另有一张 **NVIDIA (NIM)** 卡：端点已内置，向管理员索要一把 `nvapi-` 开头的 key 粘进去，即可使用英伟达线上的 Kimi K3。

**能用哪些模型**：精选清单里 70 个型号，覆盖 OpenAI、Anthropic、Google Gemini、DeepSeek、Kimi、通义千问、MiniMax、Z.ai (GLM)、xAI Grok、Mistral、火山方舟等，也可以指向本机的 **Ollama** 完全离线跑。清单之外的模型串也能手填，效果自负。

---

## 专家库

侧栏 **账户菜单 ▸ 专家库**：内置 270+ 位中文专家（另有英文库）和 160+ 个科研技能，全部离线可用，不需要联网下载。

- **拿来就用**：搜索、按分类筛选，「查看提示词」「复制提示词」不用安装任何东西。
- **让专家干活**：点专家卡上的「开会话」，确认能力披露后，立刻开一个由该专家主持的会话。装过的专家不会挤进角色选择器——入口始终在专家库里。
- **装科研技能**：技能页点「安装技能」，装完在任何会话里输入 `/技能名` 使用，模型也会在相关任务里自己想起它。部分技能带可执行脚本，模型运行任何脚本前都会先征求你的同意。
- **组建专家团**：专家页点「组建专家团」，勾选 2–6 位专家，写一句目标——应用会把他们安装成组员，交给内置的「专家团队长」分解任务、向你提名团队；你批准后，团队在看板上协作，直到交出成品。

专家与技能内容来自开源库 agency-agents(-zh) 与 scientific-agent-skills，随应用版本更新。

---

## 界面语言

**设置 ▸ 通用 ▸ 语言**：自动 / English / 中文。

默认「自动」跟随系统语言——系统是中文就是中文界面。选择只影响这台机器。

---

## 语音输入

点输入框旁边的麦克风说话即可，**中英文自动识别**，不用先选语种。语音识别在你自己电脑上跑，录音不上传。

首次使用会下载一次识别模型（约 148 MB），走国内镜像，一般一两分钟。

---

## 微信接入

**连接器 ▸ 个人微信**：用手机微信扫码，就能在微信里跟你的 agent 双向聊天（走腾讯官方 iLink Bot API，不是外挂协议）。

1. 打开 **连接器**，找到「个人微信」，点连接，选「扫码连接」，用手机微信扫码并确认。
2. 扫码后微信里会出现一个**机器人会话**（独立身份，不是你自己的账号）。给它发私聊即可。
3. 首个发信人会先出现在连接器页的「待允许」里——点允许后消息才会进入会话（默认谁都不放行，安全起见）。
4. 在 **收件箱 ▸ 配置 ▸ 私信** 里选一个会话作为微信消息的接收会话，agent 的回复会自动发回微信。

要点：

- **只有私聊可靠**。机器人是独立身份，普通微信群一般加不进去、群消息也收不到——这是腾讯侧的限制。
- 消息**只在应用运行期间**接收；对方发来的图片、文件会自动解密保存到本机，agent 能直接读。
- 登录凭据只存在本机；会话过期时断开重连、重新扫码即可。

- **托盘菜单改语言后要重启**才会变。
- **日期和时间跟随系统语言**，不跟应用内的语言设置走。
- **Windows 安装向导是英文的**，一路 Next 即可。

---

## 出了问题怎么办

先翻 **[用户手册](docs/手册/03-用户手册.md)**——常见的九种情况都在里面，大多数自己两下就能解决。

还是不行就找管理员，或者在 **[Issues](https://github.com/ldfpku/openworker/issues)** 里提。

**完整文档**（[docs/手册/](docs/手册/)）：

| 手册 | 谁读 |
| --- | --- |
| [01-管理员初始化手册](docs/手册/01-管理员初始化手册.md) | 从零把这套东西搭起来的人 |
| [02-运维手册](docs/手册/02-运维手册.md) | 日常加人删人、调额度、查用量的人 |
| [03-用户手册](docs/手册/03-用户手册.md) | **所有使用者** |
| [04-Cloudflare-AI-Gateway](docs/手册/04-Cloudflare-AI-Gateway.md) | 想用 Gemini 以外的模型 |

---

## 从源码运行

前置：Python 3.10+、Node 20、Rust 工具链（[rustup](https://rustup.rs/)）。

```shell
git clone https://github.com/ldfpku/openworker
cd openworker
```

建 Python 环境——**Windows 用 uv**（`packaging/setup_dev_env.sh` 只能在 macOS / Linux 上跑）：

```powershell
uv sync --extra messaging --extra dev
```

（两个 `--extra` 是消息接入和测试依赖，对应 macOS 脚本装的 `[messaging,dev]`——`uv sync` 光秃秃跑不装 extras，之后跑测试会找不到 pytest。）

macOS / Linux：

```shell
bash packaging/setup_dev_env.sh
```

然后起服务端和界面：

```shell
# 1. 本地 agent 服务
.venv/bin/openworker-server --cwd ~/some/project --port 8765
#    Windows: .venv\Scripts\openworker-server.exe

# 2. 另开一个终端
cd surfaces/gui
npm install
npm run dev            # 浏览器界面
npm run tauri dev      # 或者完整桌面应用
```

测试：后端 `pytest tests`；界面在 `surfaces/gui` 下 `npm test` 和 `npm run e2e`。

---

## 隐私

会话内容、连接器令牌、模型 key 都只存在你自己电脑上。

两处例外，值得你知道：**模型请求会经过公司的 Cloudflare 中转和网关**——中转会按你的邮箱记录每次请求用了多少 token（用来分摊成本和限额），但**不记录请求和回复的内容**。具体记了什么、留多久，写在[用户手册](docs/手册/03-用户手册.md)里。

---

## 许可

MIT，版权归 Andrew Ng (2024)，见 [LICENSE](LICENSE)。
