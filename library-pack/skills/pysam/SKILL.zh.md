# pysam

## 概览

将 pysam 用于对 HTSlib 支持的基因组文件格式做底层、流式访问:

- `AlignmentFile` 和 `AlignedSegment` 用于 SAM/BAM/CRAM
- `VariantFile`、`VariantHeader` 和 `VariantRecord` 用于 VCF/BCF
- `FastaFile` 用于带索引的 FASTA,`FastxFile` 用于顺序读取的 FASTA/FASTQ
- `TabixFile` 用于 BGZF 压缩、带 tabix 索引的 BED/GFF/GTF/自定义表格
- `pysam.samtools` 和 `pysam.bcftools` 用于封装的命令调度器

当前上游基准版本:**pysam 0.24.0**(2026 年 4 月 27 日),封装的是
HTSlib/samtools/bcftools 1.23.1。在更新任何与版本相关的指导内容之前，先
阅读 `references/sources.md`。

## 安装

用于可复现工作的锁定版本安装方式:

```bash
uv pip install "pysam==0.24.0"
```

确认运行时版本:

```python
import pysam

print(pysam.__version__)           # 0.24.0
print(pysam.__samtools_version__)  # 1.23.1
```

在受支持的 macOS 和 Linux 平台上有预构建的 wheel 包可用。源码构建需要 C
编译器和 HTSlib 的构建依赖；请阅读 `references/sources.md` 中链接的官方
安装指南。

## 先做出决定

在写代码之前:

1. 确认真实的格式、压缩方式、排序顺序，以及可用的索引。
2. 确定坐标使用的是数值型 Python 坐标，还是区域字符串(region string)。
   不要把两者混用。
3. 对于 CRAM,要确认精确的参考基因组组装版本和 FASTA 文件。
4. 优先使用带索引的区域访问；只有在确有此意时才使用顺序遍历。
5. 写入时要保留文件头(header),并默认写入到一个新路径。
6. 明确过滤语义:比对/碱基质量、标志位(flags)、重叠处理方式、重复序列
   处理方式，以及 pileup 深度上限。

对于不熟悉的文件，先用打包好的只读检查器查看:

```bash
python scripts/inspect_hts.py sample.bam
python scripts/inspect_hts.py cohort.vcf.gz
python scripts/inspect_hts.py reference.fa
```

## 打包脚本

| 脚本 | 用途 | 典型调用方式 |
|---|---|---|
| `scripts/inspect_hts.py` | 仅查看元数据，适用于比对、变异、FASTA、FASTQ 和 tabix 文件 | `python scripts/inspect_hts.py sample.cram --reference ref.fa` |
| `scripts/alignment_qc.py` | 以流式方式汇总读段/QC 计数，输出为 JSON | `python scripts/alignment_qc.py sample.bam --max-records 100000` |
| `scripts/variant_summary.py` | 以流式方式汇总变异、FILTER 和基因型信息，输出为 JSON | `python scripts/variant_summary.py cohort.vcf.gz --region chr1:1-1000000` |
| `scripts/filter_alignments.py` | 在不改变记录顺序的前提下过滤 SAM/BAM/CRAM | `python scripts/filter_alignments.py input.bam output.bam --exclude-secondary` |

所有脚本都拒绝覆盖已存在的输出文件。对每个脚本运行 `--help` 可查看坐标、
索引和隐私方面的说明。

## 坐标约定

**pysam API 所接受的数值型坐标是 0 起始、半开区间(half-open)的**。 这
包括数值型的 `AlignmentFile.fetch()`、`VariantFile.fetch()`、
`FastaFile.fetch()`、`TabixFile.fetch()` 和 `pileup()` 的参数。

**区域字符串采用 samtools 风格:1 起始、闭区间(inclusive)**。

```python
# The same 100 bases:
bam.fetch("chr1", 99, 199)          # [99, 199)
bam.fetch(region="chr1:100-199")    # 1-based inclusive
```

VCF 文本使用 1 起始的 `POS`,而记录属性则同时暴露两套坐标体系:

```python
record.pos    # 1-based
record.start  # 0-based inclusive
record.stop   # 0-based exclusive
```

格式转换、重叠语义、索引选择，以及 contig 名称检查，详见
`references/coordinates_and_indexing.md`。

## 比对文件(Alignment Files)

使用上下文管理器，并显式指定模式:

```python
import pysam

with pysam.AlignmentFile("sample.bam", "rb", threads=4) as bam:
    for read in bam.fetch("chr1", 1_000, 2_000):
        if (
            not read.is_unmapped
            and not read.is_secondary
            and not read.is_supplementary
            and read.mapping_quality >= 30
        ):
            print(read.query_name, read.reference_start, read.cigarstring)
```

使用 `fetch(until_eof=True)` 可以按文件顺序流式读取每一条记录，包括未定位
的未比对读段(unplaced unmapped reads),且无需索引:

```python
with pysam.AlignmentFile("sample.bam", "rb") as bam:
    for read in bam.fetch(until_eof=True):
        ...
```

需要注意的重要区别:

- `fetch()` 返回与某个区域重叠的比对记录。
- `count()` 对记录计数，默认使用 `read_callback="nofilter"`。
- `count_coverage()` 返回 A/C/G/T 碱基计数，默认使用碱基质量 15,并搭配
  `read_callback="all"`。
- `pileup()` 暴露的是逐列(per-column)的读段信息，它有自己独立的过滤、
  碱基质量、重叠、孤儿读段(orphan)处理方式，以及 `max_depth=8000` 的
  默认值。

对于精确区间的 pileup,要设置 `truncate=True` 并显式指定过滤条件:

```python
with pysam.FastaFile("reference.fa") as fasta, pysam.AlignmentFile(
    "sample.bam", "rb"
) as bam:
    for column in bam.pileup(
        "chr1",
        1_000,
        2_000,
        truncate=True,
        stepper="samtools",
        fastafile=fasta,
        min_mapping_quality=20,
        min_base_quality=20,
        max_depth=100_000,
    ):
        print(column.reference_pos, column.get_num_aligned())
```

标志位(flags)、CIGAR 操作、标签(tags)、修饰碱基(modified bases)、
写入记录、pileup 细节，以及迭代器生命周期，详见
`references/alignment_files.md`。

## 变异文件(Variant Files)

输入格式会被自动检测。数值型的 fetch 坐标仍然是 0 起始的:

```python
import pysam

with pysam.VariantFile("cohort.vcf.gz", threads=4) as variants:
    for record in variants.fetch("chr1", 999_999, 2_000_000):
        print(record.contig, record.pos, record.ref, record.alts)
        for sample_name, call in record.samples.items():
            print(sample_name, call.get("GT"))
```

要**在获取记录之前**先做样本子集筛选:

```python
with pysam.VariantFile("cohort.bcf") as variants:
    variants.subset_samples(["sample_A", "sample_B"])
    for record in variants:
        ...
```

在更改文件头时，要先复制每条记录并将其转换到目标文件头，然后再赋值新声明
的 INFO/FORMAT/FILTER 字段。不要手动清空并重建 `header.samples`。

安全的文件头处理方式、写入方式、样本子集筛选、缺失基因型、符号等位基因
(symbolic alleles)、过滤、转换，以及索引，详见
`references/variant_files.md`。

## FASTA、FASTQ 与 Tabix

带索引的 FASTA 使用数值型的 0 起始坐标:

```python
with pysam.FastaFile("reference.fa") as fasta:
    sequence = fasta.fetch("chr1", 999, 1_099)
```

`FastxFile` 是顺序读取的。`persist=False` 速度更快，但产出的记录在迭代
前进之后就会失效:

```python
with pysam.FastxFile("reads.fastq.gz", persist=False) as reads:
    for read in reads:
        qualities = read.get_quality_array()
        ...
```

Tabix 的输入必须是按坐标排好序、经过 BGZF 压缩的，而不是普通的 gzip。使用
下面这种非破坏性的两步工作流程:

```python
pysam.tabix_compress("regions.bed", "regions.bed.gz")
pysam.tabix_index("regions.bed.gz", preset="bed")

with pysam.TabixFile("regions.bed.gz", parser=pysam.asBed()) as tbx:
    for interval in tbx.fetch("chr1", 1_000, 2_000):
        print(interval.contig, interval.start, interval.end)
```

FASTA/FASTQ 记录以及安全创建 tabix 索引的方式，详见
`references/sequence_files.md`。

## CRAM、远程 I/O 与多线程

pysam 0.24 改变了继承自 HTSlib 的一些行为:

- 新写入的 CRAM 默认使用 CRAM 3.1,而不是 3.0。
- HTSlib 默认不再联系 EBI 参考服务器。
- 优先使用 `reference_filename="reference.fa"` 以获得确定性的本地读写
  行为。

```python
with pysam.AlignmentFile(
    "sample.cram",
    "rc",
    reference_filename="reference.fa",
    threads=4,
) as cram:
    for read in cram.fetch("chr1", 1_000, 2_000):
        ...
```

只有在确实需要按 MD5 值查找参考序列时，才配置 `REF_PATH`/`REF_CACHE`。
不要假定一个 CRAM 文件是自包含的。`threads=` 加速的是压缩/解压过程；它
不会让 Python 层面的分析并行化。

在做 CRAM 转换、远程访问或并发迭代之前，先阅读
`references/cram_and_performance.md`。

## 封装的 samtools 与 bcftools

要显式导入对应的命令模块。将每一个命令行参数都作为单独的字符串传入:

```python
import pysam.samtools
import pysam.bcftools

pysam.samtools.sort(
    "-@", "4", "-o", "sorted.bam", "input.bam", catch_stdout=False
)
pysam.samtools.index("-@", "4", "sorted.bam", catch_stdout=False)

pysam.bcftools.index("--csi", "variants.vcf.gz", catch_stdout=False)
```

调度器默认会捕获标准输出(stdout)。对于体积较大或二进制的输出，应使用
工具自身的 `-o` 选项并配合 `catch_stdout=False`,或使用
`save_stdout=...`,而不要把完整输出全部保留在内存中。

```python
try:
    pysam.samtools.quickcheck("-v", "sample.bam")
except pysam.SamtoolsError as error:
    messages = pysam.samtools.quickcheck.get_messages()
    raise RuntimeError(messages or str(error)) from error
```

对于记录级别的逻辑使用 Python API,对于诸如 sort、index、merge、view 和
归一化(normalization)这类成熟的批量操作使用调度器。绝不要通过拆分一段
不可信的 shell 命令来拼装调度器的参数。

## 写入规则

- 在打开输出文件之前，先复制或构造一个有效的文件头。
- 写入到一个新路径；除非确实明确要替换原文件，否则不要使用
  `force=True`。
- 如果输出文件之后要建索引，要保留排序顺序。
- 在设置 `query_qualities` 之前先设置 `query_sequence`。
- 优先使用 `pysam.CIGAR_OPS` 枚举成员；像 `pysam.CMATCH` 这样的顶层常量
  只是为了兼容而保留的别名，计划在未来版本中移除。
- 对比对结果使用 `pysam.samtools.quickcheck()` 做校验，并在下游使用之前
  重新打开变异/序列输出文件加以确认。
- 当参考序列或坐标超出旧版索引的限制时，使用 CSI 而不是 BAI/TBI。

## 参考文件索引

| 需求 | 阅读 |
|---|---|
| 比对 API、标志位、CIGAR、pileup、修饰碱基 | `references/alignment_files.md` |
| VCF/BCF 文件头、记录、样本、写入 | `references/variant_files.md` |
| FASTA/FASTQ 和带 tabix 索引的表格 | `references/sequence_files.md` |
| 坐标转换与索引选择 | `references/coordinates_and_indexing.md` |
| CRAM 参考序列、远程 I/O、多线程、性能 | `references/cram_and_performance.md` |
| 正确的综合分析模式 | `references/common_workflows.md` |
| 当前 API 签名和默认值的简明参考 | `references/api_reference.md` |
| 针对现有环境的升级说明 | `references/migration_to_0_24.md` |
| 官方文档、规范和发布来源 | `references/sources.md` |

## 常见的失败模式

- 把数值型的 `VariantFile.fetch()` 坐标当作 1 起始来处理
- 在需要 BGZF 加 tabix/CSI 的场景下使用普通 gzip
- 在没有索引的情况下调用区域 fetch
- 假定 `fetch()` 会包含未定位的未比对比对记录
- 在需要精确 pileup 区间时忘记设置 `truncate=True`
- 忽略 pileup 的默认值，例如碱基质量 13 和深度上限 8000
- 在多个活跃的迭代器或线程之间共享同一个文件句柄
- 在没有精确参考序列的情况下解码 CRAM
- 在输出文件头中声明之前就为一个新的 VCF 字段赋值
- 把体量很大的 samtools/bcftools 输出捕获到内存中
- 对插入缺失(indel)或符号等位基因使用为 SNP 设计的碱基计数方法
