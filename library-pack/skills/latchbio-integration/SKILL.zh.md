# LatchBio 集成

## 当前基线版本

此技能针对 **Latch SDK 2.76.8**(发布于 2026 年 7 月 10 日)。该软件包的元数据支持 Python 3.9-3.12,并声明支持 Python 3.9+。

当某份指南与 SDK 实际情况不符时，应以已安装的软件包及其变更日志(changelog)为准。部分 Latch 指南仍保留着较旧的 Python 版本范围，或针对兼容性锁定的预发布版本，尤其是 Snakemake v2 教程。切勿在未核实版本要求的情况下，把不同轨道(track)的命令或导入语句混用。

## 何时使用

在以下情况下使用此技能：

- 创建或维护 Python SDK 工作流和任务图(task graph)
- 打包并注册 Python、Nextflow 或 Snakemake 流水线
- 配置任务的 CPU、内存、存储、GPU、缓存、重试与超时
- 通过 `LPath`、`LatchFile`、`LatchDir` 或 CLI 处理 Latch Data
- 读取或更新 Latch Registry 中的项目、表格和记录
- 设计工作流表单、启动计划(launch plan)、样本表(samplesheet)、消息与结果链接
- 使用 `latch register --staging` 和 `latch develop` 暂存并调试工作流镜像
- 通过 Python 或 Latch MCP 启动并监控工作流
- 发现并使用可直接运行的 Latch 工作流

## 找到正确的参考文档

只阅读任务所需的参考文档：

| 需求 | 参考文档 |
|---|---|
| Python 工作流、任务、map、条件、缓存 | `references/workflow-creation.md` |
| `LPath`、旧版文件类型、Latch URL、data CLI | `references/data-management.md` |
| Registry 读取、事务、样本表 | `references/registry.md` |
| CPU、内存、存储、GPU、动态资源 | `references/resource-configuration.md` |
| Nextflow 和 Snakemake 打包 | `references/nextflow-snakemake.md` |
| 元数据、表单、启动计划、消息、自动化 | `references/ui-and-automation.md` |
| 注册、开发、执行、监控 | `references/operations-and-debugging.md` |
| 可直接使用的工作流与 `latch.verified` | `references/verified-workflows.md` |
| 远程 MCP 设置与工具工作流 | `references/latch-mcp.md` |

在依赖某个符号(symbol)之前，先针对目标 SDK 版本运行 `scripts/inspect_latch_sdk.py`。它只执行本地导入，不进行身份验证，也不发起网络请求。

## 安装与身份验证

要建立一个可复现的环境：

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install "latch==2.76.8"
```

在 Windows 上，应使用 WSL 来运行文档所描述的 Linux 工作流工具链。

通过受支持的 OAuth 流程进行身份验证；不要手动读取、打印、复制或解析 `~/.latch/token`：

```bash
latch login
latch workspace
```

当已知工作区(workspace)的数字 ID 时，可非交互式地选定它：

```bash
latch workspace --id 12345
```

`latch login` 的凭据是供 SDK 和 CLI 使用的。Latch MCP 使用一套独立的 OAuth 授权，其凭据无法复用于一般的 SDK 访问。

## 快速上手路径

创建并远程注册官方维护的 subprocess 模板：

```bash
latch init covid-wf --template subprocess
latch register --yes --open covid-wf
```

远程镜像构建是默认方式。只有在本地 Docker 守护进程可用、且确实有意进行本地构建时，才使用 `--no-remote`。

## 最简 Python 工作流

保持工作流主体是声明式的:调用各个任务，并返回它们的 promise。计算逻辑和副作用应放在任务内部执行。

```python
from latch import small_task, workflow


@small_task
def reverse_complement(sequence: str) -> str:
    table = str.maketrans("ACGTacgt", "TGCAtgca")
    return sequence.translate(table)[::-1]


@workflow
def reverse_complement_workflow(sequence: str) -> str:
    """Return the reverse complement of a DNA sequence."""
    return reverse_complement(sequence=sequence)
```

当生成的界面需要自定义标签、分区、校验规则、样本表或文档链接时，使用 `@workflow(metadata)`。若需要自动的任务输入暂存和输出上传，使用 `LatchFile` 或 `LatchDir`;若需要命令式的远程路径操作，使用 `LPath`。

## 推荐的开发生命周期

1. **检查兼容性**
   - 确认已安装的 SDK 和 Python 版本。
   - 判断该项目属于 Python、Nextflow、旧版 Snakemake flag 路径，还是单独锁定版本的 Snakemake v2 教程轨道。

2. **定义带类型的接口**
   - 为每一个工作流和任务的输入、输出都加上类型注解。
   - 保持模块导入阶段不含网络调用、数据变更或密钥获取。对于像 `workflow_reference` 这样有文档记录的例外(它会在其装饰器被求值时解析出当前激活的工作区),应将其隔离处理。
   - 使用 dataclass 和枚举来表达结构化参数。

3. **配置元数据与资源**
   - 让 metadata 的参数键与工作流的函数签名相匹配。
   - 先从具名的任务装饰器开始，只有在经过实测的需求确实合理时，才使用 `custom_task`。

4. **在执行镜像中验证**

   全新的 Nextflow 和 Snakemake 项目必须先生成与版本兼容的 Python 入口点(entrypoint),才能进行暂存。在 SDK 2.76.8 中，暂存分支不会从 `--nf-script` 或 `--snakefile` 自动生成该入口点。

   ```bash
   latch register --staging .
   latch develop .
   ```

   在修改 Dockerfile 或依赖项之后，应重新运行暂存注册。在开发容器内部所做的编辑不会同步回本地。

5. **审慎地进行注册**

   ```bash
   latch register --yes --open .
   ```

   有用的控制选项：

   ```bash
   latch register --workspace-id 12345 .
   latch register --mark-as-release .
   latch register --workflow-module wf.custom_entrypoint .
   ```

   重复注册会以状态码 `2` 退出；这与构建失败并不是一回事。

6. **只有在审查过成本和参数之后才启动运行**
   - 对于交互式操作，优先使用 Console 或 Latch MCP。
   - 对于 Python 自动化，优先使用 `latch_cli.services.launch.launch_v2`。
   - 不要把已废弃的 `latch launch` CLI 当作新的集成方式来使用。

7. **监控与验证**
   - 检查终端状态、任务日志、结果链接以及科学产出结果。
   - 应把编排成功视为科学验证的必要条件，而非充分条件。

## 操作安全

- 在启动付费计算(尤其是 GPU 或大批量运行)之前，应先请求确认。
- 在执行 `LPath.rmr`、`latch rmr`、Registry 删除，或覆盖共享目标位置之前，应先请求确认。
- 切勿记录密钥、SDK 令牌、签名 URL 或其他机密值。
- 只在任务内部调用 `get_secret()`,返回值仅用于其预期的目标服务，且绝不能把它作为工作流的输出返回。
- 不要把不可信的字符串直接传入 shell 命令。应优先使用参数列表形式的 `subprocess.run(..., check=True)`。
- 发布版本应锁定 SDK 及工作流依赖的版本。只有在审查过变更日志并重新运行暂存测试之后，才进行升级。
- 把生成的文件当作生成物来对待:应自定义有文档说明的扩展文件，而不是编辑那些会被 CLI 覆盖的输出文件。

## 检查已安装的 SDK

从此技能所在目录：

```bash
uv run --no-project --python 3.12 --with "latch==2.76.8" \
  python scripts/inspect_latch_sdk.py
```

使用 JSON 输出以便进行自动化比对：

```bash
uv run --no-project --python 3.12 --with "latch==2.76.8" \
  python scripts/inspect_latch_sdk.py --json
```

## 权威信息来源

- 文档索引:https://wiki.latch.bio/llms.txt
- 工作流与 SDK 指南:https://wiki.latch.bio/workflows/overview
- SDK API 参考:https://wiki.latch.bio/reference/sdk
- PyPI 软件包:https://pypi.org/project/latch/
- SDK 2.76.8 发布源码:https://github.com/latchbio/latch/tree/0faa9dcd8186444ac008f50adf95d43f0fa30e06
- SDK 变更日志:https://github.com/latchbio/latch/blob/0faa9dcd8186444ac008f50adf95d43f0fa30e06/CHANGELOG.md
- Latch Console:https://console.latch.bio
