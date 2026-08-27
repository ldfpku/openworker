# Waypoint：Outpost Bio 的开放式微生物组基础模型

## 概述

Outpost Bio 以 Apache 2.0 协议开源了三项成果，详见
[Treloar et al., bioRxiv 2026.05.02.722381](https://www.biorxiv.org/content/10.64898/2026.05.02.722381v2)：

| 成果 | 内容 | Hugging Face |
| --- | --- | --- |
| **Waypoint** | 基于分类学 token 的 GPT-2 风格因果语言模型，参数量 600 万至 1.7 亿 | `outpost-bio/Waypoint-6m`、`-45m`、`-170m` |
| **Atlas** | 从 MGnify 抓取的 539,308 个微生物组样本（其中预训练用 485,377 个 / 基准测试用 53,931 个） | `outpost-bio/Atlas` |
| **Compass** | 覆盖四项研究的八个下游任务 | `outpost-bio/Compass` |

统一的核心思路是：一个微生物组样本就是一个*句子*。每个分类单元（taxon）就是一个 token，token 按丰度 z 分数降序排列，模型以"预测下一个 token"的方式进行训练。预训练好的模型随后可以为样本提供固定长度的嵌入向量，或作为预测任务的微调骨干网络。

以上全部功能都由一个统一的命令行工具 `waypoint` 驱动，它包含五个子命令：`prepare-dataset`、`embed`、`finetune`、`benchmark`、`pretrain`。

## 何时使用

- 将 16S/宏基因组分类学谱系数据嵌入为固定大小的向量，用于聚类、可视化，或作为下游分类器的输入。
- 微调一个 Waypoint 检查点，以根据群落组成预测表型、处理条件或某个连续指标。
- 在 Compass 上评测你自己的微生物组模型，使得到的分数能与论文中的结果进行比较。
- 在 Atlas 或你自己的语料上预训练一个分类学语言模型。
- 将分类器输出（MetaPhlAn、Kraken2/Bracken、QIIME 2、MGnify TSV）转换为这些工具所需的输入格式。

**在以下情况下不要使用本技能**：当你的带标签样本少于约 1,000 个时——见[科学层面的注意事项](#科学层面的注意事项)。在这种情况下，基于相对丰度的随机森林是更合适的工具，论文本身也是这么说的。

## 环境准备

```bash
pip install waypoint-bio       # installs the `waypoint` command
```

Atlas、Compass 以及每一个 Waypoint 检查点都是**受限访问**的。访问请求会被自动批准，但你必须先在每个仓库页面点击一次申请，然后完成身份验证：

1. 在你需要的每个仓库页面申请访问权限：[Waypoint-6m](https://huggingface.co/outpost-bio/Waypoint-6m)、
   [Waypoint-45m](https://huggingface.co/outpost-bio/Waypoint-45m)、
   [Waypoint-170m](https://huggingface.co/outpost-bio/Waypoint-170m)、
   [Atlas](https://huggingface.co/datasets/outpost-bio/Atlas)、
   [Compass](https://huggingface.co/datasets/outpost-bio/Compass)。
2. 在本地完成身份验证：

   ```bash
   hf auth login          # or: export HF_TOKEN=hf_...
   ```

任何子命令返回 401/403，几乎都意味着尚未在该具体仓库上申请过访问权限——光有 token 是不够的。请使用具有读取权限的 token。分词器（tokenizer）是通过 `trust_remote_code=True` 加载的，因此如果你需要在多次运行之间固定远程代码，请锁定某个 `revision`。

## waypoint 数据格式

除 `prepare-dataset` 外，其余所有命令消费的都是 **waypoint 格式**：一个 `.parquet` / `.csv` / `.tsv` 文件，每一行是一个样本，包含两个对齐的列表型列，外加你需要的任意标签列。

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `Taxa` | `list[str]` | 完整的谱系字符串，以 `;` 分隔：`k__Bacteria; p__Firmicutes; ...; g__Lactobacillus` |
| `Relative Abundances` | `list[float]` | 长度与 `Taxa` 相同，顺序一致 |
| *(任意)* | 标量 | 目标值、协变量，或一个 `Split` 列 |

优先使用 parquet 格式。CSV/TSV 会将列表以 `repr` 字符串的形式存储，并通过 `ast.literal_eval` 进行往返转换。

**要提供完整谱系，而不是裸名称**。 分词器会从每条谱系字符串中提取属（genus）一级的片段（`g__`），当属信息缺失时会回退到最具体的更高一级分类。裸名称会完全禁用这一回退机制。

## 工作流程

### 1. 将你的数据转换为 waypoint 格式

如果你已经拥有一个带谱系标签的 样本 × 分类单元（或 分类单元 × 样本）丰度矩阵：

```bash
waypoint prepare-dataset \
    --input abundance_matrix.tsv \
    --metadata sample_labels.csv \
    --output dataset.parquet
```

数据方向会根据首列表头自动判断（`taxonomy`、`lineage`、`taxon`、`otu`、
`#otu id` ⇒ 分类单元作为行）；也可用 `--orientation` 手动指定。除非传入 `--no_normalize`，否则每行会被归一化使其总和为 1；除非传入 `--keep_zeros`，否则零值会被丢弃。

`prepare-dataset` 无法直接读取分类器（profiler）的原始输出——MetaPhlAn 使用 `|` 作为分隔符，Kraken2 的报告用缩进来编码层级关系，而 QIIME 2/SILVA 使用域前缀 `d__` 而非 `k__`（分词器会默默忽略它）。针对这些情况，请使用随附的转换脚本：

```bash
python scripts/profiler_to_waypoint.py \
    --input merged_metaphlan.tsv --format metaphlan \
    --output dataset.parquet

python scripts/profiler_to_waypoint.py \
    --input reports/*.kreport --format kraken \
    --output dataset.parquet

python scripts/profiler_to_waypoint.py \
    --input feature-table.tsv --format qiime2 \
    --output dataset.parquet
```

各类输入格式、分类层级处理方式，以及 `d__`/`|` 相关的坑，详见 `references/data-preparation.md`。

### 2. 首先检查词表覆盖率

Waypoint 的词表是在预训练阶段基于 Atlas 固定下来的。词表之外的分类单元会变成 `<unk>`，并被 `waypoint embed` **悄悄丢弃**；论文将此列为该系列模型的主要局限性之一。若某个样本的所有分类单元都在词表之外，得到的将是一个退化的 `[BOS][EOS]` 嵌入。

```bash
python scripts/vocab_coverage.py --model outpost-bio/Waypoint-6m --data dataset.parquet
```

该脚本会报告按样本和按丰度加权的覆盖率，并标记出低于阈值的样本。若按丰度加权的覆盖率中位数低于约 0.8，应将其视为在信任任何下游结果之前，需要重新审视你的分类学标签的信号。

### 3. 嵌入样本

```bash
waypoint embed \
    --model outpost-bio/Waypoint-6m \
    --data dataset.parquet \
    --output embeddings.parquet
```

输出以样本 ID 为索引，包含列 `dim_0 … dim_{H-1}`（`H` 对 6m 模型为 256，对 45m 模型为 512，对 170m 模型为 768）。默认参数为：`--pooling last_token`、`--batch_size 32`、`--max_length 512`，设备自动检测（依次尝试 `cuda` → `mps` → `cpu`）。

除非有充分理由，否则应保持 `--pooling last_token`：它与检查点预训练时的方式，以及 `benchmark` 和 `finetune` 的池化方式相一致。对于无监督用途，`mean` 是一个合理的替代方案；`first_token`/`cls_token` 返回的是 BOS 位置，在因果语言模型中携带的信息很少。

### 4. 基于你的标签进行微调

```bash
# classification
waypoint finetune \
    --model outpost-bio/Waypoint-45m \
    --data dataset.parquet \
    --output_dir outputs/ft_disease \
    --task_type classification \
    --target "Disease Status" \
    --config configs/finetune_classification.yaml

# regression, with a categorical covariate one-hot appended to the pooled embedding
waypoint finetune \
    --model outpost-bio/Waypoint-45m \
    --data dataset.parquet \
    --output_dir outputs/ft_degradation \
    --task_type regression \
    --target "Degradation Rate" \
    --covariate_column Drug \
    --config configs/finetune_regression.yaml
```

配置文件路径是相对于随附的 `waypoint_bio/configs/` 目录树解析的，因此 `configs/...` 这样的路径无需克隆仓库、在任意目录下都能生效。

对于小数据集，以下默认值值得调整：`warmup_steps: 1000`（可降到约 50，以保证 warm-up 在早停触发之前就已完成）；随附配置中的 `num_epochs: 1`（应调高——真正终止训练的是基于验证损失的早停机制）；以及在显存紧张时启用 `use_lora: true`（大约只训练 1% 的参数；适配器会在保存前合并回原模型，因此检查点仍保持为一个普通的 `AutoModel`）。

数据切分默认为随机的 80/10/10。**只要样本之间存在相关性——重复测量、对同一供体多次采样、技术重复——就应将 `split_column` 设为一个 `Split` 列**，否则随机切分会造成数据泄漏，测试分数将失去意义。

输出会落在 `--output_dir` 中：`best_model/`（可被 `embed`/`benchmark` 加载）、
`test_metrics.json`、`training_log.csv` + `.html`，以及 `finetune_results.json`。

### 5. 在 Compass 上进行基准测试

```bash
waypoint benchmark --model outpost-bio/Waypoint-6m --output_dir outputs/benchmark
waypoint benchmark --model outputs/pretrain/best_model --tasks 1 6 --output_dir outputs/smoke
```

会为每个任务微调一个全新的输出头，并写出 `benchmark_results.json`。分类任务的评分指标为 macro-F1；唯一的回归任务评分指标为截断到 [0, 1] 范围内的 R²；`final_score` 是各任务分数的算术平均值。完整任务表、各指标字段说明，以及结果文件的结构，见 `references/compass-benchmark.md`。

### 6. 预训练

```bash
waypoint pretrain \
    --model_config configs/models/gpt2-45m.yaml \
    --pretrain_config configs/pretraining.yaml \
    --output_dir outputs/pretrain_45m
```

该命令会下载 Atlas，从语料中构建一个分类学分词器，为 z 分数排序计算每个 token 的丰度均值/标准差，然后以"预测下一个 token"的方式配合早停机制进行训练。加入 `--data my_corpus.parquet` 可改为在你自己的 waypoint 格式语料上进行预训练，加入 `--max_samples N` 可进行冒烟测试（smoke test）。

随附提供九种架构，从 `gpt2-6m.yaml`（8 层，隐藏层维度 256）到 `gpt2-170m.yaml`（24 层，隐藏层维度 768）；每个注意力头的维度全程固定为 64。完整表格及每个配置项，见 `references/cli-reference.md`。

## 科学层面的注意事项

以下内容是承重级别的关键信息。忽视它们会得到看起来正常、实际上毫无意义的结果。

- **在带标签样本少于约 1,000 个的情况下，Waypoint 的表现不如基于原始丰度的随机森林**。 论文中，相对于随机森林基线的交叉点位于约 **10,000** 个训练样本处。应先拟合基线模型；只有当 transformer 在你的数据上确实胜出时，才采用它。
- **词表外的分类单元只会被丢弃，而不会被标记出来**。 每个 Compass 数据集都或多或少存在这种情况。应运行 `scripts/vocab_coverage.py`，并在报告结果时一并给出覆盖率。
- **在基准测试中表现最好的是 45M 模型，而不是 170M 模型**。 预训练损失会随规模持续下降，但下游 Compass 分数并不会随之提升——应从 6m 或 45m 模型开始，只有在确实证明有帮助时才扩大规模。
- **默认采用属（genus）一级的分词方式**，因此种（species）一级的区分会被合并。若要更改 `taxon_rank`，需要重新进行预训练，而不仅仅是重新分词。
- **组成型数据（Compositional data）**。 相对丰度被约束为总和等于 1；某一个分类单元的变化会在其他分类单元上引起表面上的变化。这会影响对任何按分类单元归因结果的解读。
- **批次效应与研究效应在微生物组数据中占主导地位**。 Atlas 跨越了 MGnify v1.0–v5.0 多个版本的流水线，以及四种测序方式。切勿让研究边界或运行批次边界与你的标签边界重合。
- **本模型不是临床或诊断工具**。 模型卡（model card）中已明确说明这一点。

## 参考资料

- `references/cli-reference.md` —— 每个子命令的全部参数、每个配置项，以及模型规模对照表。
- `references/compass-benchmark.md` —— 八项任务、筛选条件、评估指标，以及 `benchmark_results.json` 的结构。
- `references/data-preparation.md` —— waypoint 格式、各类分类器输出的转换方式、分类学字符串规则。
- `references/python-api.md` —— 在 Python 中使用分词器、数据集、输出头及检查点的方式。

## 脚本

- `scripts/profiler_to_waypoint.py` —— 将 MetaPhlAn / Kraken2 / QIIME 2 / 通用谱系表转换为 waypoint 格式。
- `scripts/vocab_coverage.py` —— 针对某个 waypoint 格式文件生成分词器覆盖率报告。

## 上游项目

代码仓库 [github.com/Outpost-Bio/waypoint](https://github.com/Outpost-Bio/waypoint) ·
软件包 `waypoint-bio` ·
论文 [bioRxiv 2026.05.02.722381](https://www.biorxiv.org/content/10.64898/2026.05.02.722381v2) ·
社区 [Waypoint Slack](https://join.slack.com/t/outpostbio-waypoint/shared_invite/zt-3w6ivgtba-WJOCkdxiISxQpwVq9ZZxTA) ·
联系方式 `waypoint@outpost.bio`。

引用格式：Treloar, N. J., Ur-Rehman, S., Yang, J., & Outpost Bio (2026). *Learning the Language of the
Microbiome with Transformers.* bioRxiv. 各项成果各自的 DOI 见
[outpost.bio/citations](https://www.outpost.bio/citations)。
