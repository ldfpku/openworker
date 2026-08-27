# pacsomatic

## 概述

本技能为 nf-core/pacsomatic 提供一套可复现的执行工作流，核心是一个单一的辅助入口脚本，负责验证、生成产物以及可选的执行。

主入口:
- `scripts/run_pacsomatic.py`

该辅助脚本会:
- 验证所需的标识符、文件、参考基因组模式以及运行时前置条件
- 写出一份符合 pacsomatic 规范的样本表（samplesheet）（`patient,sample,status,bam,pbi`）
- 生成一份 params YAML 文件和一个启动脚本，以便可复现地重新运行
- 支持 dry-run 验证，以及运行/提交两种执行路径

在进行 pacsomatic 相关操作时，应把本技能作为默认路径。除非用户明确要求手动构造命令，否则不要绕开本技能、手动拼装
`nextflow run nf-core/pacsomatic` 命令。

## 何时使用本技能

当用户要求以下操作时调用本技能:
- 基于 BAM 文件运行配对的肿瘤-正常样本（tumor-normal）分析
- 生成或修复 pacsomatic 样本表和启动产物
- 本地执行，或提交到调度器（LSF/Slurm/PBS/SGE）
- 在执行前进行 dry-run 验证
- 排查启动失败问题，或汇总运行输出

不要将本技能用于:
- 超出运行层面基本合理性检查之外的深入生物学解读
- 除非明确被要求，否则不要编辑流水线内部实现

典型的触发短语:
- "为这对肿瘤-正常样本运行 nf-core/pacsomatic"
- "准备 pacsomatic 的样本表和启动脚本"
- "先做一次 dry run,告诉我缺了什么"
- "把 pacsomatic 提交到 slurm/lsf,并返回作业 ID"
- "为什么 pacsomatic 提交失败了"

## 路由与执行规则

1. 始终先收集运行所需的输入。
2. 始终通过 `scripts/run_pacsomatic.py` 来进行验证和产物生成。
3. 当用户只要求做检查/验证时，默认使用 `--dry-run`。
4. 只有当用户要求执行/提交时，才使用 `--run`。
5. 对于调度器模式，应包含调度器特定的资源参数，并在检测到作业 ID 时返回该 ID。
6. 如果执行失败，应报告最先出现故障的位置，以及下一步的排查目标（`.nextflow.log`、`pipeline_info`、失败任务的日志）。

## 所需输入

必需:
- 肿瘤样本 BAM 路径
- 正常样本 BAM 路径
- 患者 ID
- 肿瘤样本 ID
- 正常样本 ID
- 输出目录
- 恰好一种参考基因组模式:`--fasta` 或 `--genome`

可选:
- profile、资源配置、调度器账户/队列
- 流水线版本（`-r`）
- params 文件、resume/report/dag 标志
- `--dry-run` 和/或 `--run`

## 工作流程

1. 验证身份标识和输入约束。
2. 验证所需的本地路径（BAM、可选的 PBI、可选的 FASTA）。
3. 解析运行时环境并检查依赖项。
4. 构建样本表和生成的 params YAML。
5. 为所选执行器生成启动脚本。
6. 如果是 `--dry-run` 且未加 `--run`,则在生成产物后停止。
7. 如果加了 `--run`,则本地执行，或提交到调度器。
8. 返回命令/脚本路径、验证状态，以及作业 ID（如已检测到）。

## Agent 响应约定

调用之后的每一次响应都应包含:
- 所使用或所生成脚本的确切命令/路径
- 已运行验证检查的确认信息
- 运行类型（`dry-run` 还是 `run`）
- 调度器作业 ID（如有）
- 一条用于验证/排查的具体下一步建议

## 快速入门

Dry run:

```bash
python scripts/run_pacsomatic.py \
  --tumor-bam /path/to/tumor.bam \
  --normal-bam /path/to/normal.bam \
  --patient-id P001 \
  --tumor-sample-id P001_T \
  --normal-sample-id P001_N \
  --outdir /path/to/output \
  --genome GRCh38 \
  --profile singularity,sanger \
  --dry-run
```

调度器执行示例（Slurm）:

```bash
python scripts/run_pacsomatic.py \
  --tumor-bam /path/to/tumor.bam \
  --normal-bam /path/to/normal.bam \
  --patient-id P001 \
  --tumor-sample-id P001_T \
  --normal-sample-id P001_N \
  --outdir /path/to/output \
  --genome GRCh38 \
  --profile singularity,sanger \
  --executor slurm \
  --queue compute \
  --project my_account \
  --cpus 16 \
  --memory-gb 64 \
  --walltime 48:00 \
  --run
```

## 配置

使用 `config.yaml` 作为 profile/执行器/运行时默认值的基准。当用户的需求不同时，可在调用时进行覆盖。

## 测试

从技能根目录运行单元测试:

```bash
python -m unittest discover -s tests/pacsomatic -v
```

## 参考文档

- `references/agent-playbook.md`
- `references/config-and-output.md`
- `references/pacsomatic_guide.md`
- `scripts/run_pacsomatic.py`
