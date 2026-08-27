# Paperzilla

当你想与你的代理讨论 Paperzilla 中的项目、推荐内容和规范论文(canonical paper)时，使用此技能。

## 你可以询问的内容

- "把项目 X 最新的推荐给我看看。"
- "打开推荐 Y,并解释一下它为什么重要。"
- "把规范论文 Z 以 markdown 形式取出来，并总结一下。"
- "告诉我这篇论文与我的研究有什么关联。"
- "给我看看项目 X 的信息流(feed)。"
- "对某条推荐留下反馈。"
- "把这篇论文、这条推荐，或这个信息流导出为 JSON。"

这是 Paperzilla 的核心技能。它让你的代理能够直接访问 Paperzilla 的数据，但它本身并不强加某种工作流或外部投递集成方式。

## 访问方式

本仓库中目前大多数配置文件(profile)都使用 `pz` CLI。

如果当前的配置文件附带了针对特定代理的额外说明，也应一并遵循。

## 安装

### macOS
```bash
brew install paperzilla-ai/tap/pz
```

### Windows(Scoop)
```bash
scoop bucket add paperzilla-ai https://github.com/paperzilla-ai/scoop-bucket
scoop install pz
```

### Linux
使用官方的 Linux 安装指南：

- https://docs.paperzilla.ai/guides/cli-getting-started

### 从源码构建(Go 1.23+)
关于从源码构建，参见 CLI 仓库：

- https://github.com/paperzilla-ai/pz

## 更新

检查你的 CLI 是否为最新版本，并获取针对具体安装方式的升级步骤：

```bash
pz update
```

若自动检测结果不明确，可显式覆盖它：

```bash
pz update --install-method homebrew
pz update --install-method scoop
pz update --install-method release
pz update --install-method source
```

支持的取值为 `auto`、`homebrew`、`scoop`、`release` 和 `source`。

## 身份验证

```bash
pz login
```

## CLI 参考

如果当前配置文件使用的是 `pz`,以下是核心命令。

### 列出项目
```bash
pz project list
```

### 查看单个项目
```bash
pz project <project-id>
```

### 浏览项目信息流
```bash
pz feed <project-id>
```

有用的参数：
- `--must-read`
- `--since YYYY-MM-DD`
- `--limit N`
- `--json`
- `--atom`

示例：
```bash
pz feed <project-id> --must-read --since 2026-03-01 --limit 5
pz feed <project-id> --json
pz feed <project-id> --atom
```

信息流的输出中可能包含已有的推荐反馈标记：

- `[↑]` 赞
- `[↓]` 踩
- `[★]` 收藏

### 阅读一篇规范论文
```bash
pz paper <paper-id>
pz paper <paper-id> --json
pz paper <paper-id> --markdown
pz paper <paper-id> --project <project-id>
```

### 打开你某个项目中的一条推荐
```bash
pz rec <project-paper-id>
pz rec <project-paper-id> --json
pz rec <project-paper-id> --markdown
```

### 对推荐留下反馈
```bash
pz feedback <project-paper-id> upvote
pz feedback <project-paper-id> star
pz feedback <project-paper-id> downvote --reason not_relevant
pz feedback clear <project-paper-id>
```

## 输出与自动化

- 面向机器解析时，优先使用 `--json`。
- `pz paper --markdown` 只有在 markdown 已经准备好的情况下才会返回它。
- `pz rec --markdown` 可以将 markdown 生成任务加入队列，并在其仍在准备过程中打印一条友好的重试提示信息。
- `--atom` 会返回一个供阅读器使用的个人信息流 URL。

## 配置

```bash
export PZ_API_URL="https://paperzilla.ai"
```

## 参考资料

- 文档:https://docs.paperzilla.ai/guides/cli
- 快速入门:https://docs.paperzilla.ai/guides/cli-getting-started
- 仓库:https://github.com/paperzilla-ai/pz
