# Pi Agent

当用户想要操作 Pi 或基于 Pi 进行构建时，使用本技能。Pi 是一个极简的终端
编码工具(coding harness),可以通过 TypeScript 扩展、技能(skills)、
提示词模板、主题、软件包、自定义模型/提供商、SDK 集成、RPC 模式、JSON
事件流，以及 TUI 组件来扩展。

## 首先要做的决定

在回答问题或写代码之前，先选择对应的参考文件:

| 用户意图 | 阅读 |
|---|---|
| Pi 是什么、文档地图、安装方式 | `references/overview.md` |
| 安装、身份验证、首次运行 | `references/quickstart.md` |
| 日常 CLI 使用、命令、模式、参数标志、项目信任 | `references/usage.md` |
| 提供商身份验证、API 密钥、云端提供商配置 | `references/providers.md` |
| 自定义模型条目、本地模型、代理、兼容性标志 | `references/models.md` |
| 本地 llama.cpp 路由器、`/llama`、模型下载/加载 | `references/llama-cpp.md` |
| 配置项键名及默认值 | `references/settings.md` |
| `PI_*` 及其他环境变量 | `references/environment-variables.md` |
| 扩展开发、自定义工具、事件、命令 | `references/extensions.md` |
| 自定义提供商实现、OAuth、自定义流式传输 | `references/custom-provider.md` |
| 在 Node/TypeScript 中嵌入 Pi | `references/sdk.md` |
| 从另一个进程/语言集成 | `references/rpc.md` |
| 消费 JSONL 事件输出 | `references/json.md` |
| 构建终端 UI 组件 | `references/tui.md` |
| 打包扩展/技能/提示词/主题 | `references/packages.md` |
| 委托给子智能体、链式调用、并行运行、编排 | `references/pi-subagents.md` |
| 连接 MCP 服务器、MCP 工具发现/配置 | `references/pi-mcp-adapter.md` |
| 交互式问答表单、结构化用户输入 | `references/pi-interview.md` |
| 网络搜索、URL/PDF/仓库抓取、视频理解 | `references/pi-web-access.md` |
| 编写 Pi 技能 | `references/skills.md` |
| 提示词模板或主题 | `references/prompt-templates.md`、`references/themes.md` |
| 会话、分支、压缩、解析 JSONL | `references/sessions.md`、`references/compaction.md`、`references/session-format.md` |
| 安全性、沙箱、信任 | `references/security.md`、`references/containerization.md` |
| 键盘或终端相关问题 | `references/keybindings.md`、`references/terminal-setup.md`、`references/tmux.md`、`references/windows.md`、`references/termux.md`、`references/shell-aliases.md` |
| 参与 Pi 自身的开发 | `references/development.md` |

## 基于 Pi 构建时的默认选择

对于需要类型安全、直接状态访问、进程内自定义工具/扩展，或自定义资源加载
的 Node/TypeScript 应用，优先使用 SDK。单一稳定会话使用
`createAgentSession()`;当应用需要通过新建/恢复/分叉/克隆/导入等流程来
替换会话时，使用 `createAgentSessionRuntime()`。身份验证和模型查找都通过
`ModelRuntime.create()` 完成。

当客户端不是 Node.js、需要进程隔离，或希望使用与语言无关的 JSONL 协议时,
优先使用 RPC 模式。对于无状态的子进程集成，先从
`pi --mode rpc --no-session` 开始，当需要持久化时再添加会话相关的参数
标志。只按 `\n` 拆分记录——Node 的 `readline` 并不符合该协议规范。

对于只需要流式事件、不需要双向控制的一次性命令行流水线，优先使用 JSON
模式:`pi --mode json "prompt"`。

对于 Pi 原生行为，使用扩展(extensions):自定义工具、命令处理器、事件
钩子、提供商注册、自定义压缩、路径保护、项目信任策略、UI 提示、组件
(widgets),以及 TUI 组件。

在跨机器或跨项目共享或安装可复用的扩展、技能、提示词模板或主题时，使用
软件包(packages)。

## 安全默认设置

Pi 是本地运行的，默认不带沙箱。应把扩展、软件包、技能、shell 命令，以及
项目本地的 `.pi` 资源，都当作拥有 Pi 进程权限的代码来对待。项目信任
(project trust)只是守卫哪些项目输入会被加载——它不是一个沙箱。对于不
可信的仓库或无人值守的自动化场景，应使用 Docker、OpenShell、Gondolin、
虚拟机，或远程沙箱来做隔离。

不要把密钥存放在项目文件中。应优先使用环境变量、
`~/.pi/agent/auth.json`、通过 `/login` 进行的 OAuth,或在
`models.json`/提供商配置中使用基于命令的密钥查找方式。

## 常用命令

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi
pi -p "Summarize this codebase"
pi --mode json "List files"
pi --mode rpc --no-session
pi --provider anthropic --model claude-sonnet-4-5
pi --model sonnet:high "Solve this complex problem"
pi --tools read,grep,find,ls -p "Review this repository"
pi --tui-mode fullscreen
pi install npm:pi-subagents
pi update --all
```

## 来源覆盖范围

这些参考文件总结了截至 Pi **0.84.2** 版本时,`https://pi.dev/docs/latest`
上的 Pi 文档及其下的每一个文档页面(文档源码位于
`https://github.com/earendil-works/pi`〔原名 `pi-mono`〕中的
`packages/coding-agent/docs/`)。它们同时也覆盖了 `pi-subagents`、
`pi-mcp-adapter`、`pi-interview` 和 `pi-web-access` 在
`https://pi.dev/packages/` 上的软件包页面，并与已发布的 npm README 和
软件包文档做了交叉核对(`pi-web-access` 0.22.0、`pi-mcp-adapter`
2.25.0、`pi-subagents` 0.49.0、`pi-interview` 0.11.0)。当具体的 API
行为至关重要时，应优先参考所引用的参考页面，并查看安装在
`node_modules/@earendil-works/pi-coding-agent/dist/` 和
`node_modules/@earendil-works/pi-ai/dist/` 下的 TypeScript 类型定义。
