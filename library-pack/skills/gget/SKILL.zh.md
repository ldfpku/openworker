# gget

## 概述

gget 是一个命令行生物信息学工具及 Python 包，为 20 多个基因组数据库
和分析方法提供统一的访问方式。可以通过一致的接口查询基因信息、序列
分析、蛋白质结构、表达数据、疾病关联，以及小鼠组织/细胞特异性指标。
大多数 gget 模块既可以作为命令行工具使用，也可以作为 Python 函数
使用。

**重要提示**：gget 所查询的数据库处于持续更新中，有时会改变其结构。
本文档针对的是 gget 0.30.5（截至 2026-06-07 PyPI 上的当前版本）。
对于需要可复现的工作，请锁定 `gget==0.30.5`；对于失效的上游数据库
适配器，在查看发行说明后再更新 gget。

## 安装

在一个干净的虚拟环境中安装 gget，以避免冲突：

```bash
# 针对本技能的可复现安装
uv venv .venv
source .venv/bin/activate
uv pip install "gget==0.30.5"

# 在 Python/Jupyter 中
import gget
```

## 快速开始

所有模块的基本使用模式：

```bash
# 命令行
gget <module> [arguments] [options]

# Python
gget.module(arguments, options)
```

大多数模块的返回结果为：
- **命令行**：JSON（默认）或带 `-csv` 标志时为 CSV
- **Python**：DataFrame 或字典

各模块间的常见标志：
- `-o/--out`：把结果保存到文件
- `-q/--quiet`：抑制进度信息
- `-csv`：返回 CSV 格式（仅限命令行）

Python 中的参数名通常与不带前导短横线的长格式 CLI 选项一致。
例如，`--census_version` 对应 `census_version=...`。使用
`gget <module> --help` 可查看确切的当前签名。

## 模块分类

gget 提供分属六大类别的 23 个模块。每个模块的参数、CLI 和 Python
示例，以及返回值形状，都在
[references/module_catalog.md](references/module_catalog.md) 中；
更完整的逐参数文档在
[references/module_reference.md](references/module_reference.md) 中。

| 类别 | 模块 |
| --- | --- |
| 1. 参考序列与基因信息 | `ref`（Ensembl 参考下载）、`search`（基因搜索）、`info`（基因/转录本详情）、`seq`（核酸与蛋白质序列） |
| 2. 序列分析与比对 | `blast`、`blat`、`muscle`（多序列比对）、`diamond`（局部比对） |
| 3. 结构与蛋白质分析 | `pdb`（结构与元数据）、`alphafold`（结构预测）、`elm`（线性基序） |
| 4. 表达与疾病数据 | `archs4`（相关性、组织表达）、`cellxgene`（单细胞）、`enrichr`（富集分析）、`bgee`（直系同源与表达）、`opentargets`（疾病与药物）、`cbio`（癌症基因组学）、`cosmic`（突变） |
| 5. 病毒与小鼠特异性 | `virus`（病毒序列）、`8cube`（小鼠特异性与表达） |
| 6. 其他工具 | `mutate`（突变序列）、`gpt`（文本生成）、`setup`（安装模块依赖） |

有几个模块在首次使用前需要执行一次性的 `gget setup`
（`alphafold`、`elm`、`cellxgene`），而 `cosmic` 会提示输入 COSMIC
凭据以下载其数据库。

## 常见工作流

若干经过实际操作的多模块流水线——基因表征、结构比较、表达与富集
分析、疾病与药物关联、直系同源比较，以及为 kallisto 或比对准备
参考文件——收录在
[references/common_workflows.md](references/common_workflows.md)
中，更完整的版本在
[references/workflows.md](references/workflows.md) 中。

## 最佳实践

### 数据检索
- 对大型查询使用 `--limit` 来控制结果规模
- 用 `-o/--out` 保存结果，以保证可复现性
- 检查数据库版本/发行版，以保证分析间的一致性
- 在生产脚本中使用 `--quiet` 以减少输出

### 序列分析
- 对于 BLAST/BLAT，先从默认参数开始，再调整灵敏度
- 使用 `gget diamond` 配合 `--threads` 以加快局部比对速度
- 使用 `--diamond_db` 保存 DIAMOND 数据库，以便重复查询
- 对于多序列比对，大型数据集使用 `-s5/--super5`

### 表达与疾病数据
- 在 cellxgene 中，基因符号区分大小写（例如 'PAX7' 与 'Pax7'）
- 在首次使用 alphafold、cellxgene、elm、gpt 之前先运行
  `gget setup`
- 对于富集分析，可使用数据库快捷方式以求方便
- 用 `-dd` 缓存 cBioPortal 数据，以避免重复下载
- 对于 OpenTargets，在编写过滤条件之前先检查返回的列名；
  gget 0.30.5 遵循较新的 OpenTargets API 模式

### 结构预测
- AlphaFold 多聚体（multimer）预测：使用 `-mr 20` 以获得更高准确度
- 对最终结构使用 `-r` 标志进行 AMBER 弛豫（relaxation）
- 在 Python 中用 `plot=True` 可视化结果
- 在运行 AlphaFold 预测之前，先查看 PDB 数据库

### 病毒数据
- 在向 `gget virus` 请求大范围的病毒数据集之前，先使用限制性
  过滤条件
- 保留 `command_summary.txt` 与下游结果一起，以便在部分下载后
  实现可复现性和恢复
- 使用 `--baseline` 和 `--merge-results` 来恢复中断的病毒元数据/
  序列下载

### 错误处理
- 数据库结构会发生变化；当某个适配器失效时，检查上游的发行说明，
  并明确锁定较新的、已修复的版本
- 对于可复现的环境，锁定已知可用的版本：
  `uv pip install "gget==0.30.5"`
- 用 gget info 一次最多处理约 1000 个 Ensembl ID
- 对于大规模分析，为 API 查询实现限速
- 使用虚拟环境以避免依赖冲突
- 把 COSMIC 和 OpenAI 凭据保存在具名环境变量或交互式提示中；不要
  把真实凭据写进示例、笔记本或日志中

## 输出格式

### 命令行
- 默认：JSON
- CSV：添加 `-csv` 标志
- FASTA：gget seq、gget mutate
- PDB：gget pdb、gget alphafold
- PNG：gget cbio plot
- FASTA/CSV/JSONL 文件夹：gget virus

### Python
- 默认：DataFrame 或字典
- JSON：添加 `json=True` 参数
- 保存到文件：添加 `save=True`，或指定 `out="filename"`
- AnnData：gget cellxgene
- DataFrame/JSON：gget 8cube specificity、psi_block、expression

## 资源

本技能包含用于了解模块详情的参考文档：

### references/
- `module_reference.md` —— 所有模块的完整参数参考
- `database_info.md` —— 所查询数据库及其更新频率的信息
- `workflows.md` —— 扩展的工作流示例与使用场景

如需更多帮助：
- 官方文档：https://pachterlab.github.io/gget/
- GitHub issues：https://github.com/pachterlab/gget/issues
- 引用格式：Luebbert, L. & Pachter, L. (2023). Efficient querying of genomic reference databases with gget. Bioinformatics. https://doi.org/10.1093/bioinformatics/btac836
