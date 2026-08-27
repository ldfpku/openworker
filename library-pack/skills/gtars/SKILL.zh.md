# Gtars

Gtars 为基因组区间（genomic interval）和参考序列（reference-sequence）相关工作
提供了原生的 Rust 实现、Python 绑定，以及一个通过特性开关（feature-gated）控制的
`gtars` 二进制文件。请先从内置的本地检查工具开始；只有在数据契约、来源、
资源边界和副作用都已明确之后，才调用上游代码。

## 已验证的快照（2026-07-23）

- Python：[`gtars==0.9.2`](https://pypi.org/project/gtars/)，发布于
  2026-06-17，`Requires-Python >=3.10`。
- Rust 元 crate（meta-crate）：[`gtars=0.9.0`](https://crates.io/crates/gtars)，
  发布于 2026-06-15。其默认特性集为空。
- CLI crate/二进制文件：[`gtars-cli=0.9.0`](https://crates.io/crates/gtars-cli)；
  安装后的二进制文件名为 `gtars`。
- 直接的 refget crate：[`gtars-refget=0.9.1`](https://crates.io/crates/gtars-refget)，
  发布于 2026-06-17。`gtars=0.9.0` 本身锁定了其组件的发布版本集合，
  其中包括 refget 0.9.0。
- 上游有意让工作区（workspace）中的各个 crate、Python 绑定和 CLI 独立地进行版本管理。
  不要想当然地认为版本号一致就意味着产物一致。
- 已发布的文档更新日志停留在 0.5.1。本文中的 API 示例是对照 0.9.2 的 Python
  存根/运行时以及 `v0.9.0` 的 CLI/Rust 源码检查过的。

`license: MIT` 字段涵盖的是本技能本身。已发布的 `gtars` crate 声明为 MIT 许可证，
而 GitHub 仓库目前在根目录显示的是 BSD-2-Clause；在再分发之前，请核实
具体产物的确切许可证。

## 原生代码信任关口与精确版本锁定

该 Python wheel 中包含一个 PyO3 原生扩展。通过 Cargo 安装会编译出一个原生二进制文件，
并可能运行依赖项的构建脚本。应将这两条路径都视为代码执行行为：

1. 确认官方的 PyPI/crates.io/GitHub 所有者身份，以及不可变的版本号。
2. 审查文件名、平台标签、发布来源、许可证以及 SHA-256 值。GitHub 的
   v0.9.0 二进制发布版本为每个压缩包都附带了 `.sha256` 校验文件。
3. 绝不运行不受信任的预构建二进制文件、wheel、源码树、Cargo 构建脚本，
   或压缩包安装程序。使用隔离环境，并限定 CPU/内存/磁盘/时间。
4. 将锁文件和产物哈希值与分析清单一并保存。

完成上述审查之后，创建一个隔离的 Python 环境：

```bash
uv venv --python 3.11 .venv-gtars
uv pip install --dry-run --python .venv-gtars/bin/python "gtars==0.9.2"
uv pip install --python .venv-gtars/bin/python "gtars==0.9.2"
.venv-gtars/bin/python -c \
  "import gtars; assert gtars.__version__ == '0.9.2'; print(gtars.__version__)"
```

对于已审查的 CLI 源码发布版本：

```bash
cargo install gtars-cli --version 0.9.0 --locked
gtars --version
gtars --help
```

对于一个 Rust 项目，应精确锁定该依赖包，并只启用所需的特性：

```toml
[dependencies]
gtars = { version = "=0.9.0", default-features = false, features = [
  "core", "overlaprs", "uniwig", "tokenizers", "refget"
] }
```

只有在确实需要使用更新的直接组件 API，并且已经测试过兼容性时，
才直接使用 `gtars-refget = "=0.9.1"`。不要用某个 Git 分支或未经审查的
发布版本来替换这些锁定的版本号。

## 基因组数据契约

在每一次操作之前都应遵循以下契约：

1. **坐标**： BED 区间是从 0 开始、半开区间的：`[start, end)`。
   要求 `0 <= start < end <= contig_length`。Gtars 的坐标类型为 `u32`，
   因此应拒绝超过 `4,294,967,295` 的值。
2. **基因组组装版本**： 记录一个基因组组装的存取号/版本号，以及
   精确的染色体大小文件或 refget 序列集合元数据的 SHA-256 值。
   绝不能从文件名或 `chr` 前缀来推断基因组组装版本。
3. **重叠群（Contig）**： 精确比对名称。`1` 和 `chr1`、备用基因座
   （alternate loci）、诱饵序列（decoy），以及线粒体别名，彼此之间
   不可互换。重命名或 liftover（基因组版本转换）只能作为一个单独经过
   审查的转换步骤来进行。
4. **排序**： 保留原始文件，然后在操作需要时，对一份副本按染色体大小
   顺序及数值型的起止位置进行排序。目前 Python 的 `RegionSet(path)`
   在加载时会按重叠群和起始位置进行字典序排序；此后不要依赖原始的行顺序。
5. **链信息（Strand）**： BED6 使用 `+`、`-` 或 `.`。`Region.rest`
   保留了 BED 文件末尾的字段，但目前基于文件的 Python `RegionSet`
   会将其独立的 `strands` 向量初始化为 `*`。若干集合运算会丢失链信息。
   当链信息在科学上有意义时，应在外部另行保留和校验。
6. **重复/相邻性**： 应明确选择处理策略。`reduce()` 和共识（consensus）
   运算会合并重叠**以及相邻**的区间；普通的半开区间重叠判定不会将
   `[0,10)` 和 `[10,20)` 视为重叠。

首先运行本地校验器：

```bash
python3 -B scripts/bed_validator.py \
  --input data.bed.gz \
  --assembly GRCh38.p14 \
  --chrom-sizes GRCh38.p14.chrom.sizes \
  --require-sorted
```

## 安全的本地工作流程

1. 对本地文件、校验和、基因组组装版本、重叠群字典、坐标系统、
   链信息处理策略、患者/重复样本分组，以及预期输出进行清点。
2. 校验 BED/片段数据，并估算工作量。先在一个小型合成文件上试运行。
3. 从文档记载的接口中选择使用 Python、CLI 还是 Rust；不要凭猜测
   翻译 API 名称。
4. 为输入字节数/记录数/文件数、线程数/任务数、内存、临时磁盘空间、
   输出大小以及运行时长设置硬性上限。
5. 在一个专用的输出目录中运行。除非明确批准覆盖，否则拒绝写入冲突。
6. 重新校验输出的排序、边界、行数、校验和以及来源信息。

## 当前的 Python 核心接口

导入路径来自子模块，而不是 `gtars` 顶层：

```python
from gtars.models import Region, RegionSet

query = RegionSet.from_regions(
    [
        Region(chr="chr1", start=100, end=200, rest=None),
        Region(chr="chr1", start=300, end=400, rest=None),
    ],
    strands=["+", "-"],
)
universe = RegionSet.from_vectors(
    ["chr1", "chr1"],
    [150, 500],
    [350, 600],
)

counts = query.count_overlaps(universe)       # one count per query region
flags = query.any_overlaps(universe)          # one bool per query region
indices = query.find_overlaps(universe)       # indices into universe
pieces = query.intersect_all(universe)        # all intersection fragments
fraction = query.coverage(universe)           # fraction of query bp covered
```

`RegionSet.sort()` 是原地修改（mutate）并返回 `None`。集合运算包括
`reduce`、`setdiff`、`pintersect`（按索引配对）、`concat`、`union`、
`jaccard`、`coverage`、`overlap_coefficient`、`intersect_all`、
`closest`、`cluster` 和 `gaps`。在依赖顺序或链信息之前，
请先阅读 `references/python-api.md`。

共识（Consensus）是位于另一个模块中的 Python 绑定：

```python
from gtars.genomic_distributions import consensus

rows = consensus([query, universe])
# rows: [{"chr": ..., "start": ..., "end": ..., "count": ...}, ...]
```

在 Python 0.9.2 中，信号轨道（signal-track）生成功能**没有**作为
`gtars.uniwig` 暴露出来；应使用经过审查的 CLI 或 Rust API。
`RegionSet.coverage()` 是一个碱基对（base-pair）集合层面的度量指标，
而不是一个 WIG/bigWig 生成器。

## 分词器、片段与参考序列存储

默认只使用本地构造方法：

```python
from gtars.models import RegionSet
from gtars.tokenizers import Tokenizer

tokenizer = Tokenizer.from_bed("reviewed-universe.bed")
regions = RegionSet("local-query.bed")
tokens = tokenizer.tokenize(regions)
encoding = tokenizer(regions)
ids = encoding["input_ids"]
```

当参数不是一个已存在的本地目录时，`Tokenizer.from_pretrained(name)`
会联系 Hugging Face 并写入其缓存；它不暴露版本（revision）或缓存参数。
应先获得明确批准，通过经过审查的机制获取一个不可变的版本，
校验其校验和，然后再传入该本地快照目录。参见
`references/tokenizers.md`。

对于 refget，优先使用 `RefgetStore.in_memory()` 或
`RefgetStore.open_local(path)`。`open_remote(cache_path, remote_url)`
会联系一个远程服务、创建/使用一个本地缓存，并执行按需的区间读取。
参见 `references/refget.md`。

## 网络与缓存关口

本技能中不会隐式地进行任何下载或缓存写入。在任何有能力发起网络请求的
上游调用之前：

- 就确切的主机、端点、数据以及缓存位置获得用户的明确批准；
- 将 HTTPS 主机列入允许清单，并拒绝未经审查的重定向；
- 记录不可变的版本/标识符、获取时间、预期的 SHA-256 和域名摘要、
  基因组组装存取号、大小配额，以及来源信息；
- 披露可能离开已获批准环境的敏感 BED 坐标、条形码（barcode）、
  样本标签以及参考序列选择；
- 在使用之前，将下载的内容视为不受信任的输入进行校验。

需要注意的重要副作用：

- `RegionSet(path)` 支持 HTTP；一个不存在的本地字符串可能会被当作
  URL 处理。在构造之前应检查本地路径是否存在。
- `Tokenizer.from_pretrained` 可能会将 `universe.bed.gz` 下载到
  Hugging Face 的缓存中。
- `RefgetStore.on_disk` 会创建/写入一个存储。`open_remote` 会加载
  远程元数据，并且默认启用持久化。
- 即使只是构造客户端，`gtars bbcache` 也会创建缓存目录。缓存/下载相关
  命令使用 `BBCLIENT_CACHE`（默认为 `~/.bbcache`）和 `BEDBASE_API`
  （默认为 `https://api.bedbase.org`）。

## 敏感元数据与数据泄漏

基因组区间、罕见基因座、条形码、样本名称、表型以及基因组组装版本的选择
都可能具有身份识别性。应将完整路径和原始坐标排除在日志之外；
内置报告默认对路径进行脱敏处理，仅输出计数/校验和。

应先按患者/供体冻结数据划分，然后将所有技术性和生物学重复样本保留在
同一个划分中。共识集合、universe、分词器、缩放（scaling）、阈值，
以及质控（QC）规则，都只应在训练数据上进行拟合。不要先用全部样本
构建一个 universe 再进行划分：那样会造成验证集/测试集基因座支持度的
数据泄漏。应单独记录被排除的样本以及重复样本的聚合方式。

## 内置的确定性 CLI 工具

全部六个辅助工具都会拒绝 URL、路径穿越、符号链接和特殊文件；
对字节数、记录数、文件数、坐标以及工作进程数设有上限；不使用网络，
也不导入 gtars；并且不写入任何输出文件。规划结果只包含固定的
argv 模板，从不会启动它们。

```bash
python3 -B scripts/bed_validator.py --help
python3 -B scripts/execution_plan.py --help
python3 -B scripts/tokenizer_manifest.py --help
python3 -B scripts/refget_digest_plan.py --help
python3 -B scripts/coverage_preflight.py --help
python3 -B scripts/artifact_inspector.py --help
```

不生成字节码地运行合成测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tests/gtars -p 'test_*.py' -v
```

## 1.1 版本中已移除的迁移陷阱

不要使用包含 `gtars.RegionSet`、`RegionSet.from_bed`、`TreeTokenizer`、
`gtars.igd.build_index`、`gtars.uniwig.coverage_from_bed`、
`gtars.RefgetStore`、全局的 `set_option`/`set_log_level`、
`parallel_apply`，或臆造出的异常类的过时示例。诸如
`uniwig generate`、`igd build`、`scoring score` 和
`fragsplit cluster-split` 这样的 CLI 形式，在 0.9.0 中也已过时。

上游已发布的文档和存根文件存在一定程度的漂移（例如较旧的
`GlobalRefgetStore` 教程，以及不完整的 0.9.2 存根文件）。
当两者存在冲突时，优先信任已安装版本的签名冒烟测试，
以及带有不可变标签的源码。

## 内置参考资料

以下是唯一的六份内置参考资料；所有链接均为本地链接且确实存在：

- `references/python-api.md` —— 精确的 Python 0.9.2 导入方式与行为
- `references/overlap.md` —— 重叠/计数/集合运算及共识语义
- `references/coverage.md` —— uniwig、bigWig、覆盖度、排序，以及所需资源
- `references/tokenizers.md` —— 分词器/universe 及片段兼容性
- `references/refget.md` —— 摘要值、存储、BEDbase、网络/缓存控制
- `references/cli.md` —— CLI 0.9.0 的命令、特性，以及迁移说明
