# Geniml

在基因组区间（genomic interval）集合上进行机器学习和统计工作流时使用 Geniml。
将坐标、基因组组装版本（assembly）、词元词汇表（token vocabulary）、模型产物
以及样本分组都视为需要明确约定的契约。本技能内置的脚本只负责校验或规划；
它们不会导入 Geniml、联系任何外部服务、反序列化模型，也不会执行训练。

`Bash` 仅用于声明本指南中展示的、经用户明确批准的 `uv`、Python、Geniml、
Gtars、Git 以及原生 CLI 命令；内置的 Python 辅助脚本不会派生子进程。
`data/`、`refs/`、`work/` 和 `models/` 目录下的示例路径是用户自行提供的
项目占位符，并非缺失的内置文件。

## 已验证的发布版本快照

- 截至 2026-07-23 的最新稳定 PyPI 版本：`geniml==0.8.4`（发布于 2026-01-14）。
- PyPI 没有声明 `Requires-Python`；其分类器（classifier）列出的是 Python
  3.10-3.14。建议优先使用 Python 3.11 或 3.12，以确保所有原生/ML wheel 都能解析成功。
- `geniml==0.8.4` 接受 `gtars>=0.2.5`；本次验证所用的基础冒烟测试使用的是
  当前的 `gtars==0.9.2`（2026-06-17，Python >=3.10）。
- 可选依赖组（extras）为 `ml` 和 `test`。基础安装不包含 Torch、Gensim、
  Scanpy、Hugging Face Hub、pyBigWig 以及 HMM 相关依赖。
- 上游文档中包含过时的示例。当二者存在冲突时，以发布源码和已安装版本的
  `--help` 输出为准。

## 可重现地安装

使用一个项目专属环境，并提交其生成的锁文件：

```bash
uv venv --python 3.12
uv pip install "geniml==0.8.4" "gtars==0.9.2"
```

对于需要 ML 库的 Region2Vec、scEmbed、评估或 universe 相关方法：

```bash
uv pip install "geniml[ml]==0.8.4" "gtars==0.9.2"
```

对于需要长期维护的项目，建议使用：

```bash
uv add "geniml[ml]==0.8.4" "gtars==0.9.2"
uv lock
```

不要安装未锁定版本的 Git 分支。应记录 Python 版本、操作系统/架构、
已解析的锁文件，以及 PyPI 产物的摘要值。Geniml 本身采用 BSD-2-Clause
许可证；frontmatter 中的 `MIT` 值是针对本技能内容本身的许可证。

## 从安全关口开始

在导入 Geniml 或运行外部二进制文件之前：

1. 仅处理明确的本地普通文件。拒绝 URL、FIFO、设备文件，以及符号链接，
   除非用户主动更改此策略。
2. 对照一份可信的本地染色体大小文件，校验 BED 结构和声明的基因组组装版本。
3. 限定文件数量、字节数、行数、工作进程数、训练轮数（epoch）以及输出大小的上限。
4. 按患者、供体、生物学重复样本或其他独立单元来划分训练/验证/测试集——
   而不是仅按 BED 行或细胞来划分。
5. 对 universe、分词器（tokenizer）、模型、配置、输入、元数据清单以及原生
   二进制文件进行清点并计算校验和。
6. 在进行任何 BEDbase 或 Hugging Face 下载之前，获得明确的批准。绝不能
   从某个模型 ID 或 BEDbase 标识符推断出已获批准。
7. 保持日志聚合且有边界限制。BED 文件名、样本 ID、表型、标签、条形码
   （barcode）以及基因组区间都可能是敏感信息。

## 坐标与基因组组装约定

BED 区间通常是**从 0 开始、半开区间**（half-open）的 `[start, end)`：
start 包含在内，end 不包含在内，长度为 `end - start`。不要将其与
来自 VCF/GFF 或面向用户的基因组浏览器的从 1 开始的闭区间坐标混用。

对每一份语料库（corpus）和产物，都应记录：

- 基因组组装版本及其补丁/存取号（accession）（尽可能记录，例如 GRCh38
  与 GRCh38.p14 的区别），以及染色体大小文件的校验和；
- 重叠群（contig）命名惯例（`chr1` 还是 `1`）、备用/随机/诱饵序列（decoy）
  处理策略，以及线粒体命名方式；
- 坐标约定、排序方式、重复/重叠处理策略，以及 BED 的链信息（strand）是否有意义；
- liftover（基因组版本转换）工具、chain 文件摘要、源/目标基因组组装版本、
  未能映射的比例，以及 liftover 之后的校验结果。

拒绝负坐标、`end <= start`、整数溢出、未知重叠群、超出重叠群长度的终点、
格式错误的列、混用的基因组组装版本，以及静默的重叠群重命名。排序和归一化
永远无法修复基因组组装版本不匹配的问题。BED3 没有链信息；当第 6 列存在时，
除非该测定的契约另有规定，否则应保留 `+`、`-` 或 `.`。

在分析之前，先运行一次有边界限制的校验和归一化**规划**：

```bash
python skills/geniml/scripts/bed_validator.py \
  --input data/peaks.bed \
  --assembly GRCh38 \
  --chrom-sizes refs/GRCh38.chrom.sizes
```

该校验器只报告建议采取的操作，绝不会改写 BED 文件本身。

## 当前的 API 一览

### 区间与分词器的输入输出

对于新的区间/分词器代码，优先使用 Gtars：

```python
from gtars.models import Region, RegionSet
from gtars.tokenizers import Tokenizer

regions = RegionSet("data/peaks.bed")
tokenizer = Tokenizer.from_bed("refs/universe.bed")
encoded = tokenizer(regions)
input_ids = encoded["input_ids"]
```

在某些构造方法中，`RegionSet` 和 `Tokenizer` 也接受远程输入；
除非已明确获得网络访问批准，否则本技能只允许使用本地路径。
`geniml.io.RegionSet(regions, backed=False)` 作为旧版 Python 实现仍然可用；
文件支持（backed）的集合是可迭代的，但不可索引。`geniml.io.Region` 使用
`stop` 字段，而 `gtars.models.Region` 使用 `end` 字段。

在 gtars 0.9.2 中，会向 BED 词汇表添加七个特殊词元（special token）。
因此 `len(tokenizer)` 并不简单地等于 universe 的行数。应保留 universe
的行顺序以及精确的特殊词元映射表。

### Region2Vec

现代版本的类位于一个具体的模块路径下：

```python
from geniml.region2vec.main import Region2VecExModel
from geniml.region2vec.utils import Region2VecDataset
from gtars.tokenizers import Tokenizer

tokenizer = Tokenizer.from_bed("refs/universe.bed")
dataset = Region2VecDataset("work/tokens.parquet", shuffle=True)
model = Region2VecExModel(tokenizer=tokenizer, embedding_dim=100)
model.train(dataset, epochs=10, window_size=5, num_cpus=4, seed=42)
```

Parquet 输入必须包含一个值为列表类型的 `tokens` 列，每行对应一份文档。
关于导出、编码、旧版 CLI 以及评估方面的细节，请参见
[references/region2vec.md](references/region2vec.md)。

### scEmbed

从 `geniml.scembed.main` 导入 `ScEmbed`。AnnData 的 `.var` 必须包含
`chr`、`start` 和 `end` 字段；行对应细胞，非零特征标识可及区域
（accessible region）。应先预分词为一个 Parquet 的 `tokens` 列，
并在训练和推理中使用同一个 Tokenizer。参见
[references/scembed.md](references/scembed.md)。

### BEDspace

BEDspace 在 0.8.4 中仍然保留，它会调用一个外部的 StarSpace 可执行文件。
StarSpace 项目已被归档，上游 Geniml 也没有锁定一个兼容的版本。
应将 BEDspace 视为一条用于旧版复现的路径，而不是新系统的默认选项。
关于确切的稳定 CLI 写法，以及一个不可变的、明确未经验证的构建基线，
请参见 [references/bedspace.md](references/bedspace.md)。

### 共识 universe 与评估

已安装的 0.8.4 CLI 使用方式如下：

```text
geniml build-universe {cc,ccf,ml,hmm} ...
geniml assess-universe ...
geniml eval {gdst,npt,ctt,rct,bin-gen} ...
```

CC/CCF/ML/HMM 方法消费的是预先计算好的覆盖度 bigWig 文件。在所有 BED
文件都通过同一个基因组组装契约的校验之前，不要拼接或生成覆盖度数据。
评估指标和嵌入（embedding）指标是不同的：`assess-universe` 衡量的是
某个 universe 对区间集合的拟合程度，而 `eval` 实现了用于嵌入的
CTT、RCT、GDST 和 NPT 指标。参见
[references/consensus_peaks.md](references/consensus_peaks.md) 和
[references/utilities.md](references/utilities.md)。

## 0.8.4 迁移的重要说明

- 0.7.0 的更新日志已将新的 RegionSet/分词器相关工作转移到了 Gtars 中。
- 0.4.0 中的 `TreeTokenizer` 和 `AnnDataTokenizer` 名称已成为历史；
  当前的 Gtars API 暴露的是 `Tokenizer`。
- 在 0.8.4 的 wheel 包中，`geniml.region2vec` 和 `geniml.scembed`
  不会重新导出它们的现代类/函数。请使用上文给出的具体模块路径。
- `geniml tokenize` 和 `geniml region2vec` 这两个调用名称已不再由
  其包的 `__init__` 文件导出；在没有针对已安装版本做冒烟测试的情况下，
  不要围绕这些 CLI 路径构建新的工作流。
- `geniml scembed` 会解析旧版 MatrixMarket 相关选项，但其命令主体在
  0.8.4 中是一个空操作（no-op）。请使用 `geniml.scembed.main.ScEmbed`。
- 官方页面仍然显示的是 `geniml assess`；而发布版本中的命令实际是
  `geniml assess-universe`。
- `.gtok` 在旧版数据集中仍然存在，但上游 issue #14 提议弃用
  多文件的 `.gtok` 工作流。建议优先使用单一的、有边界限制的 Parquet 语料库。
- 配置项 `embedding_size` 仅为向后兼容而被接受；请使用 `embedding_dim`。

## 模型与 universe 的兼容性

只有当以下各项都相互一致时，一个 Region2Vec/scEmbed 推理包才是有效的：

- 模型 `config.yaml` 中的 `vocab_size` 和 `embedding_dim`；
- 精确的 `universe.bed` 字节内容/顺序及基因组组装版本；
- 分词器的实现/版本，以及特殊词元的 ID；
- 检查点（checkpoint）张量的形状以及池化（pooling）策略；
- Geniml/Gtars 的版本，以及任何分词参数。

Geniml 0.8.4 默认使用 `checkpoint.pt`、`config.yaml` 和 `universe.bed`。
其加载器使用 `torch.load(..., weights_only=True)`，但 `.pt`、Gensim 的
`.model`、pickle、joblib，以及原生二进制文件仍然属于不受信任的输入。
在加载之前先检查产物并计算校验和；使用隔离环境，并且绝不能仅仅为了
查看元数据就去加载一个检查点。

```bash
python skills/geniml/scripts/model_artifact_inspector.py \
  --model-dir models/region2vec

python skills/geniml/scripts/tokenizer_compatibility.py \
  --model-dir models/region2vec \
  --universe refs/universe.bed \
  --assembly GRCh38
```

`Region2VecExModel(model_path="org/repo")`、`ScEmbed(model_path="org/repo")`，
以及 Gtars 的 `Tokenizer.from_pretrained(...)` 都可以从 Hugging Face 下载内容。
本地的 `from_pretrained("models/local")` 会加载一个本地的模型包。当用户批准
下载时，应锁定 Hub 的具体版本（revision）以及预期的哈希值；随后就可以
离线使用经过验证的缓存内容工作。

## BEDbase 下载与缓存

`BBClient.load_bed`、`load_bedset` 以及词元缓存相关操作可能会联系
`https://api.bedbase.org`。默认缓存位置是 `$BBCLIENT_CACHE` 或
`~/.bbcache`；`BEDBASE_API` 可以更改该端点。不要读取不相关的环境变量。
应设置一个明确的项目专属缓存位置，估算大小，批准标识符/端点，
并在使用前验证返回的校验和。

本地检查命令更为安全：

```text
geniml bbclient seek ID --cache-folder /absolute/project/cache
geniml bbclient inspect-bedfiles --cache-folder /absolute/project/cache
geniml bbclient inspect-bedsets --cache-folder /absolute/project/cache
```

`cache-bed`、`cache-bedset` 和 `cache-tokens` 子命令可能会使用网络。
不要隐式地运行它们，也不要在上传/缓存工作流中包含敏感的本地 BED 文件。

## 本地审计与规划用 CLI

所有脚本都只依赖标准库，且默认输出经过脱敏处理的 JSON：

```bash
# Audit manifest paths, checksums, assemblies, and patient/donor leakage
python skills/geniml/scripts/corpus_auditor.py \
  --manifest data/manifest.tsv --assembly-column assembly \
  --group-column patient_id --split-column split

# Plan tokenizer/model compatibility checks
python skills/geniml/scripts/tokenizer_compatibility.py \
  --model-dir models/r2v --universe refs/universe.bed --assembly GRCh38

# Plan consensus construction; does not execute Geniml or coverage tools
python skills/geniml/scripts/consensus_plan.py \
  --manifest data/manifest.tsv --chrom-sizes refs/GRCh38.chrom.sizes \
  --assembly GRCh38 --method cc --output-dir work/consensus

# Plan an embedding run; does not import ML libraries
python skills/geniml/scripts/embedding_plan.py \
  --mode region2vec --data work/tokens.parquet \
  --universe refs/universe.bed --output-dir work/r2v \
  --assembly GRCh38
```

使用 `--help` 查看资源限制以及明确的路径披露控制选项。

## 参考资料

- [Region2Vec](references/region2vec.md)：现代 API、产物、CLI 漂移、
  训练、编码，以及评估。
- [scEmbed](references/scembed.md)：AnnData/词元准备、训练、推理、
  注释、隐私，以及数据泄漏。
- [BEDspace](references/bedspace.md)：元数据模式（schema）、精确的旧版
  CLI、StarSpace 的现状、产物，以及检索方式。
- [Consensus peaks](references/consensus_peaks.md)：覆盖度前置条件、
  CC/CCF/ML/HMM、评估，以及基因组组装版本的防护措施。
- [Utilities](references/utilities.md)：输入输出、Gtars 分词器、
  BBClient、评估、模型安全性、迁移，以及标注日期的来源。

来源快照及原始论文链接均标注了日期，详见
[references/utilities.md](references/utilities.md)。在更改所锁定的版本
之前，请重新核查发布版本的元数据以及已安装版本的签名信息。
