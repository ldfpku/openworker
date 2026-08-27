# polars-bio

## 概述

polars-bio 是一个高性能的 Python 库，用于基于基因组区间的操作以及生物信息学文件的读写，构建于 Polars、Apache Arrow 和 Apache DataFusion 之上。它提供了一套以 DataFrame 为核心、使用者熟悉的 API，用于区间运算（overlap、nearest、merge、coverage、complement、subtract）以及常见生物信息学格式（BED、VCF、BAM、CRAM、GFF/GTF、FASTA、FASTQ）的读写。

核心价值主张：
- 在真实世界的基因组基准测试中，比 bioframe **快 6 到 38 倍**
- 通过 DataFusion 为大型基因组提供**流式/核外**（out-of-core）支持
- 具备**云原生**文件读写能力（S3、GCS、Azure），支持谓词下推（predicate pushdown）
- **两种 API 风格**：函数式（`pb.overlap(df1, df2)`）与方法链式（`df1.lazy().pb.overlap(df2)`）
- 通过 DataFusion SQL 引擎为基因组数据提供 **SQL 接口**

## 何时使用本技能

在以下情形使用本技能：
- 执行基因组区间操作（overlap、nearest、merge、coverage、complement、subtract）
- 读写生物信息学文件格式（BED、VCF、BAM、CRAM、GFF/GTF、FASTA、FASTQ）
- 处理内存装不下的大型基因组数据集（流式模式）
- 对基因组数据文件运行 SQL 查询
- 从 bioframe 迁移到一个更快的替代方案
- 从 BAM/CRAM 文件计算读取深度（read depth）/ 堆叠图（pileup）
- 处理包含基因组区间的 Polars DataFrame

## 快速入门

### 安装

需要 Python 3.11–3.14（详见 [PyPI](https://pypi.org/project/polars-bio/)）。

```bash
uv pip install "polars-bio==0.31.0"
```

若需 pandas 兼容性（pandas ≥3.0）：

```bash
uv pip install "polars-bio[pandas]==0.31.0"
```

### 基本 Overlap 示例

```python
import polars as pl
import polars_bio as pb

# Create two interval DataFrames
df1 = pl.DataFrame({
    "chrom": ["chr1", "chr1", "chr1"],
    "start": [1, 5, 22],
    "end":   [6, 9, 30],
})

df2 = pl.DataFrame({
    "chrom": ["chr1", "chr1"],
    "start": [3, 25],
    "end":   [8, 28],
})

# Functional API (returns LazyFrame by default)
result = pb.overlap(df1, df2)
result_df = result.collect()

# Get a DataFrame directly
result_df = pb.overlap(df1, df2, output_type="polars.DataFrame")

# Method-chaining API (via .pb accessor on LazyFrame)
result = df1.lazy().pb.overlap(df2)
result_df = result.collect()
```

### 读取 BED 文件

```python
import polars_bio as pb

# Eager read (loads entire file)
df = pb.read_bed("regions.bed")

# Lazy scan (streaming, for large files)
lf = pb.scan_bed("regions.bed")
result = lf.collect()
```

## 核心能力

### 1. 基因组区间操作

polars-bio 为基因组范围运算提供了 8 种核心区间操作。所有操作都接受带有 `chrom`、`start`、`end` 列（可配置）的 Polars DataFrame。所有操作默认返回一个 `LazyFrame`（若要立即求值的结果，使用 `output_type="polars.DataFrame"`）。

**操作**：
- `overlap` / `count_overlaps` —— 查找或统计两个集合之间的重叠区间（自 0.30.0 起，`overlap_output="left"` 仅返回 df1 一侧的命中结果）
- `nearest` —— 查找最近的区间（可通过 `k`、`overlap`、`distance` 参数配置）
- `merge` —— 合并同一集合内重叠或首尾相接（bookended）的区间
- `cluster` —— 为重叠区间分配簇（cluster）ID
- `coverage` —— 计算每个区间的覆盖计数（双输入操作）
- `complement` —— 查找基因组内区间之间的空隙
- `subtract` —— 移除与另一集合重叠的区间部分

**示例**：
```python
import polars_bio as pb

# Find overlapping intervals (returns LazyFrame)
result = pb.overlap(df1, df2, suffixes=("_1", "_2"))

# Count overlaps per interval
counts = pb.count_overlaps(df1, df2)

# Merge overlapping intervals
merged = pb.merge(df1)

# Find nearest intervals
nearest = pb.nearest(df1, df2)

# Collect any LazyFrame result to DataFrame
result_df = result.collect()
```

**参考资料**： 关于所有操作、参数、输出结构（schema）及性能考量的详细文档，参见 `references/interval_operations.md`。

### 2. 生物信息学文件读写

使用 `read_*`、`scan_*`、`write_*` 和 `sink_*` 函数读写常见的生物信息学格式。支持云存储（S3、GCS、Azure）以及压缩（GZIP、BGZF）。

**支持的格式**：
- **BED** —— 基因组区间（`read_bed`、`scan_bed`，写入通过通用 `write_*`）
- **VCF** —— 遗传变异（`read_vcf`、`scan_vcf`、`write_vcf`、`sink_vcf`）
- **VCF Zarr** —— 可供分析的 Zarr 存储（`read_vcf_zarr`、`scan_vcf_zarr`；本地目录路径）
- **BAM** —— 比对读段（`read_bam`、`scan_bam`、`write_bam`、`sink_bam`）
- **CRAM** —— 压缩比对结果（`read_cram`、`scan_cram`、`write_cram`、`sink_cram`）
- **GFF** —— 基因注释（`read_gff`、`scan_gff`）
- **GTF** —— 基因注释（`read_gtf`、`scan_gtf`）
- **FASTA** —— 参考序列（`read_fasta`、`scan_fasta`、`write_fasta`、`sink_fasta`）
- **FASTQ** —— 测序读段（`read_fastq`、`scan_fastq`、`write_fastq`、`sink_fastq`）
- **SAM** —— 文本格式比对结果（`read_sam`、`scan_sam`、`write_sam`、`sink_sam`）
- **Hi-C pairs** —— 染色质接触（`read_pairs`、`scan_pairs`）

**示例**：
```python
import polars_bio as pb

# Read VCF file
variants = pb.read_vcf("samples.vcf.gz")

# Lazy scan BAM file (streaming)
alignments = pb.scan_bam("aligned.bam")

# Read GFF annotations
genes = pb.read_gff("annotations.gff3")

# Cloud storage (individual params, not a dict)
df = pb.read_bed("s3://bucket/regions.bed",
                 allow_anonymous=True)
```

**参考资料**： 关于各格式的列结构（schema）、参数、云存储选项及压缩支持，参见 `references/file_io.md`。

### 3. SQL 数据处理

将生物信息学文件注册为数据表，并使用 DataFusion SQL 进行查询。将 SQL 的强大能力与 polars-bio 具备基因组感知能力的读取器结合起来。

```python
import polars as pl
import polars_bio as pb

# Register files as SQL tables (path first, name= keyword)
pb.register_vcf("samples.vcf.gz", name="variants")
pb.register_bed("target_regions.bed", name="regions")

# Query with SQL (returns LazyFrame)
result = pb.sql("SELECT chrom, start, end, ref, alt FROM variants WHERE qual > 30")
result_df = result.collect()

# Register a Polars DataFrame as a SQL table
pb.from_polars("my_intervals", df)
result = pb.sql("SELECT * FROM my_intervals WHERE chrom = 'chr1'").collect()
```

**参考资料**： 关于注册函数、SQL 语法及示例，参见 `references/sql_processing.md`。

### 4. Pileup（堆叠图）操作

通过支持 CIGAR 的深度计算，从 BAM/CRAM 文件中计算逐碱基（per-base）的读取深度。

```python
import polars_bio as pb

# Compute depth across a BAM file
depth_lf = pb.depth("aligned.bam")
depth_df = depth_lf.collect()

# With quality filter
depth_lf = pb.depth("aligned.bam", min_mapping_quality=20)
```

**参考资料**： 关于参数及集成模式，参见 `references/pileup_operations.md`。

## 关键概念

### 坐标系统

polars-bio 默认使用**基于 1**（1-based）的坐标（基因组学惯例）。可以全局更改：

```python
import polars_bio as pb

# Switch to 0-based half-open coordinates (default is 1-based / False)
pb.set_option("datafusion.bio.coordinate_system_zero_based", True)

# Switch back to 1-based (default)
pb.set_option("datafusion.bio.coordinate_system_zero_based", False)
```

I/O 函数也接受 `use_zero_based` 参数，用于在生成的 DataFrame 上设置坐标元数据：

```python
# Read BED with explicit 0-based metadata
df = pb.read_bed("regions.bed", use_zero_based=True)
```

**重要提示**： BED 文件在文件格式层面始终采用基于 0（0-based）的半开区间。polars-bio 在读取 BED 文件时会自动处理这一转换。坐标元数据由 I/O 函数附加到 DataFrame 上，并在各项操作中传播。

### 两种 API 风格

**函数式 API** —— 独立函数，输入显式传入：
```python
result = pb.overlap(df1, df2, suffixes=("_1", "_2"))
merged = pb.merge(df)
```

**方法链式 API** —— 通过 **LazyFrame**（而非 DataFrame）上的 `.pb` 访问器：
```python
result = df1.lazy().pb.overlap(df2)
merged = df.lazy().pb.merge()
```

**重要提示**： 用于区间操作的 `.pb` 访问器只在 `LazyFrame` 上可用。在 `DataFrame` 上，`.pb` 只提供写入操作（`write_bam`、`write_vcf` 等）。

方法链式写法便于构建流畅的处理管线：
```python
# Chain interval operations (note: overlap outputs suffixed columns,
# so rename before merge which expects chrom/start/end)
result = (
    df1.lazy()
    .pb.overlap(df2)
    .filter(pl.col("start_2") > 1000)
    .select(
        pl.col("chrom_1").alias("chrom"),
        pl.col("start_1").alias("start"),
        pl.col("end_1").alias("end"),
    )
    .pb.merge()
    .collect()
)
```

### Probe-Build 架构

对于双输入操作（overlap、nearest、count_overlaps、coverage），polars-bio 使用一种 probe-build 连接策略：
- **第一个** DataFrame 是 **probe**（被遍历的一方）
- **第二个** DataFrame 是 **build**（被建立索引以供查找的一方）

为了获得最佳性能，请将较大的 DataFrame 作为第一个参数（probe）传入，较小的作为第二个参数（build）传入。

### 列命名约定

polars-bio 默认要求列名为 `chrom`、`start`、`end`。可以通过列表指定自定义列名：

```python
result = pb.overlap(
    df1, df2,
    cols1=["chromosome", "begin", "finish"],
    cols2=["chr", "pos_start", "pos_end"],
)
```

### 返回类型与结果收集

所有区间操作以及 `pb.sql()` 默认都返回一个 **LazyFrame**。使用 `.collect()` 来实体化结果，或传入 `output_type="polars.DataFrame"` 以实现立即求值：

```python
# Lazy (default) - collect when needed
result_lf = pb.overlap(df1, df2)
result_df = result_lf.collect()

# Eager - get DataFrame directly
result_df = pb.overlap(df1, df2, output_type="polars.DataFrame")
```

### 流式与核外（Out-of-Core）处理

对于超出可用内存的数据集，使用 `scan_*` 函数及流式执行：

```python
# Scan files lazily
lf = pb.scan_bed("large_intervals.bed")

# Process with Polars streaming (requires polars ≥1.37, bundled with polars-bio)
result = lf.collect(engine="streaming")
```

针对区间操作，DataFusion 流式处理默认已启用，会分批处理数据，而不会将整个数据集加载进内存。

## 常见坑点

1. **`.pb` 访问器在 DataFrame 与 LazyFrame 上的区别：** 区间操作（overlap、merge 等）只存在于 `LazyFrame.pb` 上。`DataFrame.pb` 只有写入方法。在进行区间操作链式调用之前，使用 `.lazy()` 进行转换。

2. **LazyFrame 返回值**： 所有区间操作以及 `pb.sql()` 默认都返回 `LazyFrame`。不要忘记调用 `.collect()`，或使用 `output_type="polars.DataFrame"`。

3. **列名不匹配**： polars-bio 默认要求列名为 `chrom`、`start`、`end`。如果你的列名不同，使用 `cols1`/`cols2` 参数（以列表形式传入）。

4. **坐标系统元数据**： 区间操作会从 I/O 函数或 DataFrame 的 `config_meta` 中读取坐标元数据。对于手动构建的 DataFrame，需设置 `df.config_meta.set(coordinate_system_zero_based=True)`（0-based）或 `False`（1-based）。如果元数据缺失，polars-bio 会回退使用全局的 `datafusion.bio.coordinate_system_zero_based` 设置（并给出警告）。将 `pb.set_option("datafusion.bio.coordinate_system_check", True)` 设为 True 可改为抛出 `MissingCoordinateSystemError`。两个输入的坐标系统不一致时会抛出 `CoordinateSystemMismatchError`。

5. **Probe-build 顺序很重要**： 对于 overlap、nearest 和 coverage 操作，第一个 DataFrame 会被拿去对第二个进行探测（probe）。交换参数顺序会改变哪些区间出现在左侧还是右侧的输出列中，也可能影响性能。

6. **INT32 位置上限**： 基因组坐标以 32 位整数存储，将坐标限制在约 21 亿以内。这对所有已知基因组而言都是足够的，但对自定义坐标空间可能构成问题。

7. **BAM 索引要求**： `read_bam` 和 `scan_bam` 要求 BAM 文件旁边有一个 `.bai` 索引文件。如果缺失，使用 `samtools index` 创建一个。

8. **默认禁用并行执行**： DataFusion 的并行度默认是 1 个分区（partition）。对于大型数据集，请启用并行：
   ```python
   pb.set_option("datafusion.execution.target_partitions", 8)
   ```

9. **CRAM 有独立的函数**： 对 CRAM 文件使用 `read_cram`/`scan_cram`/`register_cram`（而非 `read_bam`）。CRAM 相关函数需要一个 `reference_path` 参数。

## 最佳实践

1. **对大文件使用 `scan_*`：** 对于超出可用内存的文件，优先使用 `scan_bed`、`scan_vcf` 等，而非 `read_*`。Scan 函数支持流式处理及谓词下推。

2. **为大型数据集配置并行度**：
   ```python
   import os
   pb.set_option("datafusion.execution.target_partitions", os.cpu_count())
   ```

3. **使用 BGZF 压缩**： BGZF 压缩的文件（`.bed.gz`、`.vcf.gz`）支持并行块解压缩，比普通 GZIP 明显更快。

4. **尽早选择所需列**： 当只需要特定列时，尽早选择它们以降低内存占用：
   ```python
   df = pb.read_vcf("large.vcf.gz").select("chrom", "start", "end", "ref", "alt")
   ```

5. **直接使用云路径**： 将 S3/GCS/Azure URI 直接传给 read/scan/register 函数，而不是先下载文件。经过身份验证的访问仅在访问这些云路径时才会使用你的云 SDK 凭证（`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`、`GOOGLE_APPLICATION_CREDENTIALS`、Azure 默认凭证）：
   ```python
   df = pb.read_bed("s3://my-bucket/regions.bed", allow_anonymous=True)
   ```

6. **单次操作优先使用函数式 API，构建管线时优先使用方法链式**： 对于一次性操作使用 `pb.overlap()`，在构建多步骤管线时使用 `.lazy().pb.overlap()`。

## 资源

### references/

针对各项主要能力的详细文档：

- **interval_operations.md** —— 全部 8 种区间操作，包含参数、示例、输出结构（schema）及性能技巧。是基因组范围运算的核心参考资料。

- **file_io.md** —— 支持格式一览表、各格式的列结构（schema）、云存储配置、压缩支持及常用参数。

- **sql_processing.md** —— 注册函数、DataFusion SQL 语法、将 SQL 与区间操作结合使用，以及示例查询。

- **pileup_operations.md** —— 从 BAM/CRAM 文件计算逐碱基读取深度、相关参数，以及与区间操作的集成方式。

- **configuration.md** —— 全局设置（并行度、坐标系统、流式模式）、日志记录及元数据管理。

- **bioframe_migration.md** —— 操作映射表、API 差异、性能对比、迁移代码示例，以及 pandas 兼容模式。
