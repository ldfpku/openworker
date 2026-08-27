# Nextflow

## 概述

Nextflow 是一门用于构建**可复现、可移植、可扩展**数据流水线的工作流语言及运行时环境。它在生物信息学领域占据主导地位，但同样适用于任何数据密集型计算。nf-core 是一个社区项目，负责维护生产级质量的 Nextflow 流水线、可复用模块，以及构建于 Nextflow 之上的 `nf-core` 工具链。

核心理念：
- **数据流编程（Dataflow programming）**：流水线由通过**通道**（channel）相互连接的 `process` 任务组成。Nextflow 会根据数据依赖关系自动推断执行顺序与并行度——无需编写显式的调度逻辑。
- **一次编写，随处运行**：同一份流水线只需更改配置/profile，而无需更改代码，即可在本地、HPC（SLURM、SGE、LSF、PBS）以及云端（AWS Batch、Google Batch、Azure Batch、Kubernetes）上运行。
- **可复现性**：通过按任务隔离的容器（Docker/Singularity/Apptainer/Conda/Wave）+ `-resume` 缓存 + 固定版本的流水线版本来实现。
- **DSL2** 是现代的、必需使用的语法：模块化的 `process`/`workflow`/`include` 定义方式。

本技能既涵盖**运行**现有流水线，也涵盖**开发**你自己的流水线（Nextflow 语言 + nf-core 惯例、使用 nf-test 进行测试、配置以及部署）。

## 何时使用本技能

在用户想要以下操作时使用本技能：
- 运行某个 nf-core 或自定义 Nextflow 流水线，或调试一次失败/需要恢复的运行。
- 编写或修改 `.nf` 脚本、`nextflow.config`、profile，或 `nextflow_schema.json`。
- 编写或测试 nf-core 风格的模块/子工作流（`main.nf`、`meta.yml`、`tests/`、nf-test）。
- 配置执行器（executor）、容器或资源；扩展至 HPC 或云端。
- 构建一个可复现的科学/生物信息学工作流（即便没有明确提到"Nextflow"这个词）。
- 理解进程（process）、通道（channel）、算子（operator）、`take`/`emit`、`publishDir`、`ext.args`、meta map。

## 环境设置

Nextflow 需要 **Bash** 以及 **Java 17 或更新版本**（支持 17-25）。用 `java -version` 进行验证。

```bash
# Install Nextflow (self-contained launcher)
curl -s https://get.nextflow.io | bash      # creates ./nextflow
sudo mv nextflow /usr/local/bin/             # put on PATH
nextflow info                                # verify

# Or via conda/bioconda (also gets a managed Java)
conda create -n nf -c bioconda -c conda-forge nextflow nf-core
```

```bash
# nf-core tools (Python) for creating/linting/running nf-core assets
uv pip install nf-core            # or: conda install -c bioconda nf-core
nf-core --version
```

为了可复现性，请固定引擎版本：`export NXF_VER=24.10.0`（只有在需要时才使用 [edge] 预发布版本）。关于离线/HPC 环境，参见 `references/running-pipelines.md`（离线模式）以及 `references/configuration.md`。

## 两种工作模式

先判断用户处于哪条路径——这会改变一切：

| 目标 | 从这里开始 |
|------|-----------|
| **运行**一个现有流水线（nf-core 或你拿到的某个 `.nf` 文件） | `references/running-pipelines.md` |
| **开发**一个新的流水线/模块/子工作流 | `references/language.md` + `references/developing.md` |
| **配置/扩展**（HPC、云端、容器、资源） | `references/configuration.md` + `references/containers.md` |
| **测试**模块/流水线 | `references/testing.md` |

## 快速入门

### 运行一个 nf-core 流水线

始终先使用内置的 `test` profile 进行冒烟测试；它使用极小规模的数据，用于证明你的环境是正常工作的。

```bash
# 1. Confirm setup works (downloads pipeline + tiny test data)
nextflow run nf-core/rnaseq -profile test,docker --outdir results

# 2. Real run: pin a revision (-r), pick a container engine, pass inputs
nextflow run nf-core/rnaseq -r 3.14.0 \
  -profile docker \
  --input samplesheet.csv \
  --genome GRCh38 \
  --outdir results \
  -resume
```

- `-profile`（单短横线）用于选择内置的配置 profile；用逗号**组合**多个 profile，例如 `test,docker`。容器/基础设施类的 profile（`docker`、`singularity`、`conda`）彼此互斥——只能选一个。
- `--input`、`--genome`、`--outdir`（双短横线）是**流水线**层面的参数。nf-core 流水线接受的是一份 **samplesheet CSV** 文件，而不是零散的文件。
- `-resume` 会复用上一次运行留下的缓存结果。`-r <version>` 用于固定某个版本，以保证可复现性。

使用 `nf-core pipelines launch <name>` 可以以交互式、基于 schema 校验的方式构建命令及 `-params-file`。参见 `references/running-pipelines.md`。

### 编写一个最简流水线

```nextflow
#!/usr/bin/env nextflow

process SAYHELLO {
    tag "$greeting"
    publishDir "results", mode: 'copy'

    input:
    val greeting

    output:
    path "${greeting}.txt"

    script:
    """
    echo '$greeting world' > ${greeting}.txt
    """
}

workflow {
    channel.of('hello', 'bonjour', 'hola') | SAYHELLO
}
```

```bash
nextflow run main.nf            # add -resume on reruns
```

完整的语言说明（进程、通道、算子，带有 `take`/`main`/`emit` 的 DSL2 工作流、模块）见 `references/language.md`。

## 核心概念一览

- **Process（进程）**：一个执行某段脚本（默认为 Bash）的工作单元。它声明 `input:`、`output:`，以及可选的 `directives`（资源、容器、`publishDir`、`tag`、`errorStrategy`），还有一个 `script:`/`shell:`/`exec:` 代码块。每个任务都在其自己独立隔离的工作目录（`work/xx/yy…`）中运行。
- **Channel（通道）**：连接各个进程的异步队列。**队列通道**（Queue channels）是可被消费的数据流；**值通道**（value channels）保存一个可反复使用的单一值。可通过 `channel.of`、`channel.fromPath`、`channel.fromFilePairs`、`channel.value` 等工厂方法创建。
- **Operator（算子）**：对通道进行转换/组合——`map`、`filter`、`collect`、`groupTuple`、`join`、`combine`、`mix`、`flatten`、`branch`、`multiMap`、`splitCsv`、`view`、`set`。
- **Workflow（工作流）**：由多个进程组合而成。DSL2 工作流可以声明 `take:`（输入）、`main:`（逻辑）、`emit:`（命名输出），并可通过 `include` 作为子工作流被引入。未命名的 `workflow {}` 是入口点。
- **Module（模块）**：一个通过 `include { NAME } from './path'` 暴露进程/工作流的 `.nf` 文件（支持 `as` 别名）。
- **Configuration（配置）**：`nextflow.config` 用于设置 `params`、`process` 指令（directives）、`executor`、容器引擎以及命名的 `profiles`。选择器 `withName:`/`withLabel:` 用于定位到具体的进程。参见 `references/configuration.md`。
- **meta map**（nf-core 惯例）：在输入/输出元组（tuple）中，将文件与一个元数据映射（`[ id:'sample1', single_end:false ]`）一并携带的惯例做法，以便样本在整个流水线中始终带有标签。参见 `references/developing.md`。

## nf-core tools CLI

nf-core tools（v3+）将各子命令分组归类到 `pipelines`、`modules` 和 `subworkflows` 之下。（像 `nf-core lint` 这样的裸命令形式仍然可用，但会给出警告——建议优先使用分组后的形式。）

| 命令 | 用途 |
|---------|---------|
| `nf-core pipelines list` | 列出/搜索 nf-core 流水线（`--json`、关键词） |
| `nf-core pipelines create` | 依据 nf-core 模板搭建一个新流水线的脚手架 |
| `nf-core pipelines launch <name>` | 以交互式、基于 schema 驱动的方式构建运行命令及参数文件 |
| `nf-core pipelines download <name>` | 下载流水线及容器，供离线/HPC 环境使用 |
| `nf-core pipelines lint` | 依据 nf-core 标准对流水线进行 lint 检查（在仓库根目录运行） |
| `nf-core pipelines schema build` | 通过网页 GUI 构建/编辑 `nextflow_schema.json` |
| `nf-core pipelines create-params-file <name>` | 生成一份带说明文档的 YAML 参数文件 |
| `nf-core pipelines bump-version` / `sync` | 升级版本号 / 与模板更新同步 |
| `nf-core modules list/info/install/update/remove` | 管理来自 nf-core/modules 的模块 |
| `nf-core modules create` / `lint` / `test` | 编写、lint 检查并对某个模块进行 nf-test 测试 |
| `nf-core modules patch` / `bump-versions` | 修补已安装的模块 / 升级工具版本 |
| `nf-core subworkflows install/create/lint/test` | 针对子工作流的相同生命周期操作 |

完整的命令参考、标志位及示例见：`references/nf-core-tools.md`。

## 必备的 `nextflow` CLI 命令

| 命令 | 用途 |
|---------|---------|
| `nextflow run <pipeline> -profile <p> --outdir <dir>` | 运行一个流水线（路径、`.nf` 文件，或 `user/repo`） |
| `-resume` | 复用之前运行留下的缓存结果 |
| `-r <rev>` | 运行某个特定的 git 版本/标签/分支 |
| `-params-file params.yml` | 从 YAML/JSON 文件提供参数 |
| `-c custom.config` | 叠加一个额外的配置文件 |
| `-with-report -with-trace -with-timeline -with-dag flow.html` | 执行报告、跟踪记录、时间线、DAG（有向无环图） |
| `-stub-run` | 只运行 `stub:` 代码块（干跑，仅验证流程连接） |
| `nextflow log` | 查看过往运行记录 |
| `nextflow clean -f -before <run>` | 删除旧的 `work/` 数据 |
| `nextflow pull / drop / list / info <repo>` | 管理已缓存的远程流水线 |

配置、执行器、缓存内部机制及跟踪细节见：`references/configuration.md`。

## 最佳实践（高价值习惯）

- **始终先做 `test`**：在处理真实数据之前，先运行 `-profile test,docker`（或 `singularity`/`conda`）——速度快，且能及早发现环境问题。
- **固定一切版本**：流水线版本（`-r`）、`NXF_VER`，以及工具版本（容器）。不要对将要发表的科学工作使用 `latest`。
- **使用 `-resume`** 并理解其缓存机制：当某个任务的输入、脚本或容器发生变化时，该任务会重新运行。关于缓存调试，参见 `references/configuration.md`。
- **通过配置/参数文件进行参数化**，而不是硬编码路径。将 `params` 与各个 profile 保存在 `nextflow.config` 中。
- **每个进程使用一个独立的容器/conda 环境**；永远不要依赖宿主机上已安装的工具。
- **针对 nf-core 开发**：在编写新模块之前，先复用现有模块（`nf-core modules install`）；通过 `ext.args`（而非在脚本中硬编码）传递工具的命令行参数；始终包含 `stub:` 代码块及 nf-test 测试；提交代码前运行 `nf-core pipelines lint` 与 `prettier`。
- **合理配置资源规模**，使用 `process_low/medium/high` 标签，并配合动态的 `task.attempt` 递增比例设置 `errorStrategy 'retry'`，而不是一次性申请一份巨大的资源。
- **编写向前兼容的语法**：严格语法（strict-syntax）解析器将在 Nextflow 26.04 中成为默认设置。优先使用小写的 `channel.of(...)`、显式的闭包参数（`{ v -> ... }`）、对所有变量使用 `def`，以及使用 `emit:` 命名输出。可用 `nextflow lint` 进行检查。

## 参考文件

在需要深入了解时阅读对应的文件——每份文件都是自成一体的：

- `references/language.md` —— DSL2 语言：进程、指令（directives）、通道、算子、工作流（`take`/`emit`）、模块、动态资源、错误处理。
- `references/configuration.md` —— `nextflow.config`、各个作用域（scope）、`profiles`、`withName`/`withLabel` 选择器、执行器（本地/SLURM/云端）、缓存/`-resume` 内部机制、跟踪记录/报告、`nextflow` CLI。
- `references/containers.md` —— Docker、Singularity/Apptainer、Podman、Conda、Wave 容器；引擎的选择与启用；常见坑点。
- `references/running-pipelines.md` —— 查找/运行 nf-core 流水线、samplesheet、参数文件、参考基因组（iGenomes）、离线运行、机构级配置、Seqera Platform。
- `references/nf-core-tools.md` —— 完整的 `nf-core` CLI 参考（pipelines/modules/subworkflows）、标志位及工作流。
- `references/developing.md` —— 编写 nf-core 流水线与模块：模板结构、模块的 `main.nf`/`meta.yml`、meta map、`ext.args`/`modules.config`、子工作流、资源标签、lint 检查及 Harshil 对齐风格（Harshil alignment style）。
- `references/testing.md` —— 针对模块/子工作流/流水线的 nf-test：测试结构、断言、快照（snapshot）、标签（tag）、测试运行、CI。

官方文档：Nextflow https://www.nextflow.io/docs/latest/ · nf-core https://nf-co.re/docs/ · 培训 https://training.nextflow.io/
