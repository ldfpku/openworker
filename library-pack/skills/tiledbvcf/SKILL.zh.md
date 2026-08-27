# TileDB-VCF

## 概述

TileDB-VCF 是一个高性能的 C++ 库，带有 Python 和 CLI 接口，用于高效存储与检索基因组变异调用数据。它构建在 TileDB 的稀疏数组技术之上，支持对 VCF/BCF 文件进行可扩展的摄入(ingestion)、无需昂贵合并操作的增量样本添加，以及对存储在本地或云端的变异数据进行高效并行查询。

## 何时使用本 Skill

在以下情况下应使用本 skill:
- 学习 TileDB-VCF 的概念和工作流
- 对基因组学分析与流水线进行原型开发
- 处理中小规模数据集(少于 1000 个样本)
- 需要向已有数据集增量添加新样本
- 需要对众多样本上的特定基因组区域进行高效查询
- 处理存储在云端的变异数据(S3、Azure、GCS)
- 需要导出大型 VCF 数据集的子集
- 为队列研究(cohort studies)构建变异数据库
- 教学项目和方法开发
- 对变异数据操作而言性能至关重要

## 快速开始

### 安装

**首选方式:Conda/Mamba**
```bash
# Enter the following two lines if you are on a M1 Mac
CONDA_SUBDIR=osx-64
conda config --env --set subdir osx-64

# Create the conda environment
conda create -n tiledb-vcf "python<3.10"
conda activate tiledb-vcf

# Mamba is a faster and more reliable alternative to conda
conda install -c conda-forge mamba

# Install TileDB-Py and TileDB-VCF, align with other useful libraries
mamba install -y -c conda-forge -c bioconda -c tiledb tiledb-py tiledbvcf-py pandas pyarrow numpy
```

**替代方式:Docker 镜像**
```bash
docker pull tiledb/tiledbvcf-py     # Python interface
docker pull tiledb/tiledbvcf-cli    # Command-line interface
```

### 基础示例

**创建并填充一个数据集**:
```python
import tiledbvcf

# Create a new dataset
ds = tiledbvcf.Dataset(uri="my_dataset", mode="w",
                      cfg=tiledbvcf.ReadConfig(memory_budget=1024))

# Ingest VCF files (must be single-sample with indexes)
# Requirements:
# - VCFs must be single-sample (not multi-sample)
# - Must have indexes: .csi (bcftools) or .tbi (tabix)
ds.ingest_samples(["sample1.vcf.gz", "sample2.vcf.gz"])
```

**查询变异数据**:
```python
# Open existing dataset for reading
ds = tiledbvcf.Dataset(uri="my_dataset", mode="r")

# Query specific regions and samples
df = ds.read(
    attrs=["sample_name", "pos_start", "pos_end", "alleles", "fmt_GT"],
    regions=["chr1:1000000-2000000", "chr2:500000-1500000"],
    samples=["sample1", "sample2", "sample3"]
)
print(df.head())
```

**导出为 VCF**:
```python
import os

# Export two VCF samples
ds.export(
    regions=["chr21:8220186-8405573"],
    samples=["HG00101", "HG00097"],
    output_format="v",
    output_dir=os.path.expanduser("~"),
)
```

## 核心能力

### 1. 数据集创建与摄入(Ingestion)

创建 TileDB-VCF 数据集，并从多个 VCF/BCF 文件中增量摄入变异数据。这适用于构建群体基因组学数据库和开展队列研究。

**要求**:
- **仅支持单样本 VCF**:不支持多样本 VCF
- **需要索引文件**:VCF/BCF 文件必须带有索引(.csi 或 .tbi)

**常见操作**:
- 用经过优化的数组模式(array schema)创建新数据集
- 并行摄入单个或多个 VCF/BCF 文件
- 增量添加新样本，而无需重新处理已有数据
- 配置内存占用和压缩设置
- 处理各种 VCF 格式以及 INFO/FORMAT 字段
- 恢复中断的摄入过程
- 在摄入过程中校验数据完整性


### 2. 高效的查询与过滤

对基因组区域、样本以及变异属性进行高性能查询。这适用于关联研究、变异发现和群体分析。

**常见操作**:
- 查询特定的基因组区域(单个或多个)
- 按样本名或样本分组进行过滤
- 提取特定的变异属性(位置、等位基因、基因型、质量)
- 高效访问 INFO 和 FORMAT 字段
- 结合空间过滤与基于属性的过滤
- 对大型查询结果进行流式处理
- 跨样本或跨区域执行聚合运算


### 3. 数据导出与互操作性

将数据导出为多种格式，以供下游分析或与其他基因组学工具集成。这适用于共享数据集、创建分析子集，或喂给其他流水线。

**常见操作**:
- 导出为标准的 VCF/BCF 格式
- 生成带有所选字段的 TSV 文件
- 创建特定于样本/区域的子集
- 保留数据溯源信息和元数据
- 无损数据导出，保留全部注释
- 压缩输出格式
- 对大型数据集进行流式导出


### 4. 群体基因组学工作流

TileDB-VCF 尤其擅长大规模群体基因组学分析，这类分析需要跨众多样本和基因组区域高效访问变异数据。

**常见工作流**:
- 全基因组关联研究(GWAS)数据准备
- 罕见变异负荷检验(rare variant burden testing)
- 群体分层分析
- 跨群体的等位基因频率计算
- 大型队列的质量控制
- 变异注释与过滤
- 跨群体比较分析


## 关键概念

### 数组模式与数据模型

**TileDB-VCF 数据模型**:
- 变异以稀疏数组形式存储，基因组坐标作为维度
- 样本以属性形式存储，支持高效的按样本查询
- INFO 和 FORMAT 字段以原始数据类型保留
- 为获得最优存储而自动进行压缩和分块(chunking)

**模式配置**:
```python
# Custom schema with specific tile extents
config = tiledbvcf.ReadConfig(
    memory_budget=2048,  # MB
    region_partition=(0, 3095677412),  # Full genome
    sample_partition=(0, 10000)  # Up to 10k samples
)
```

### 坐标系统与区域

**关键点**: TileDB-VCF 遵循 VCF 标准，使用**基于 1 的基因组坐标(1-based genomic coordinates)**:
- 位置从 1 开始计数(第一个碱基的位置是 1)
- 区间的两端都是闭区间
- 区域 "chr1:1000-2000" 包含位置 1000 到 2000(共计 1001 个碱基)

**区域指定格式**:
```python
# Single region
regions = ["chr1:1000000-2000000"]

# Multiple regions
regions = ["chr1:1000000-2000000", "chr2:500000-1500000"]

# Whole chromosome
regions = ["chr1"]

# BED-style (0-based, half-open converted internally)
regions = ["chr1:999999-2000000"]  # Equivalent to 1-based chr1:1000000-2000000
```

### 内存管理

**性能考量**:
1. **根据可用系统内存设置合适的内存预算**
2. 对非常大的结果集**使用流式查询**
3. **对大型摄入任务进行分区**,以避免内存耗尽
4. 为重复的区域访问**配置 tile 缓存**
5. 对多个文件**使用并行摄入**
6. 通过合并相邻区域来**优化区域查询**

### 云存储集成

TileDB-VCF 可以无缝对接云存储:
```python
# S3 dataset
ds = tiledbvcf.Dataset(uri="s3://bucket/dataset", mode="r")

# Azure Blob Storage
ds = tiledbvcf.Dataset(uri="azure://container/dataset", mode="r")

# Google Cloud Storage
ds = tiledbvcf.Dataset(uri="gcs://bucket/dataset", mode="r")
```

## 常见陷阱

1. **摄入过程中内存耗尽**: 对大型 VCF 文件使用合适的内存预算和批处理
2. **低效的区域查询**: 合并相邻区域，而不是发起多个独立查询
3. **样本名缺失**: 确保 VCF 文件头中的样本名与查询中指定的样本一致
4. **坐标系统混淆**: 记住 TileDB-VCF 和 VCF 标准一样使用基于 1 的坐标
5. **大型结果集**: 对会返回数百万个变异的查询，使用流式处理或分页
6. **云端权限**: 确保云存储访问具备正确的身份认证
7. **并发访问**: 对同一数据集的多个写入方可能导致数据损坏——需使用恰当的加锁机制

## CLI 用法

TileDB-VCF 提供了一个带有以下子命令的命令行接口:

**可用子命令**:
- `create` —— 创建一个空的 TileDB-VCF 数据集
- `store` —— 将样本摄入到 TileDB-VCF 数据集中
- `export` —— 从 TileDB-VCF 数据集中导出数据
- `list` —— 列出 TileDB-VCF 数据集中存在的所有样本名
- `stat` —— 打印关于 TileDB-VCF 数据集的高层统计信息
- `utils` —— 用于操作 TileDB-VCF 数据集的实用工具
- `version` —— 打印版本信息并退出

```bash
# Create empty dataset
tiledbvcf create --uri my_dataset

# Ingest samples (requires single-sample VCFs with indexes)
tiledbvcf store --uri my_dataset --samples sample1.vcf.gz,sample2.vcf.gz

# Export data
tiledbvcf export --uri my_dataset \
  --regions "chr1:1000000-2000000" \
  --sample-names "sample1,sample2"

# List all samples
tiledbvcf list --uri my_dataset

# Show dataset statistics
tiledbvcf stat --uri my_dataset
```

## 高级特性

### 等位基因频率分析
```python
# Calculate allele frequencies
af_df = tiledbvcf.read_allele_frequency(
    uri="my_dataset",
    regions=["chr1:1000000-2000000"],
    samples=["sample1", "sample2", "sample3"]
)
```

### 样本质量控制
```python
# Perform sample QC
qc_results = tiledbvcf.sample_qc(
    uri="my_dataset",
    samples=["sample1", "sample2"]
)
```

### 自定义配置
```python
# Advanced configuration
config = tiledbvcf.ReadConfig(
    memory_budget=4096,
    tiledb_config={
        "sm.tile_cache_size": "1000000000",
        "vfs.s3.region": "us-east-1"
    }
)
```


## 资源

## 获取帮助

### 开源 TileDB-VCF 资源

**开源文档**:
- TileDB Academy: https://cloud.tiledb.com/academy/
- Population Genomics Guide: https://cloud.tiledb.com/academy/structure/life-sciences/population-genomics/
- TileDB-VCF GitHub: https://github.com/TileDB-Inc/TileDB-VCF

### TileDB-Cloud 资源

**面向大规模/生产环境基因组学工作**:
- TileDB-Cloud Platform: https://cloud.tiledb.com
- TileDB Academy(全部文档): https://cloud.tiledb.com/academy/

**开始使用**:
- 免费账号注册: https://cloud.tiledb.com
- 联系方式: sales@tiledb.com,用于企业需求

## 扩展到 TileDB-Cloud

当你的基因组学工作负载超出单机处理能力时,TileDB-Cloud 为生产级基因组学流水线提供了企业级能力。

**注意**:本节内容基于现有文档介绍 TileDB-Cloud 的能力。完整的 API 细节和当前功能，请查阅官方 TileDB-Cloud 文档和 API 参考。

### 设置 TileDB-Cloud

**1. 创建账号并获取 API 令牌**
```bash
# Sign up at https://cloud.tiledb.com
# Generate API token in your account settings
```

**2. 安装 TileDB-Cloud Python 客户端**
```bash
# Base installation
uv pip install tiledb-cloud

# With genomics-specific functionality
uv pip install tiledb-cloud[life-sciences]
```

**3. 配置身份认证**
```bash
# Set environment variable with your API token
export TILEDB_REST_TOKEN="your_api_token"
```

```python
import tiledb.cloud

# Authentication is automatic via TILEDB_REST_TOKEN
# No explicit login required in code
```

### 从开源版本迁移到 TileDB-Cloud

**大规模摄入**
```python
# TileDB-Cloud: Distributed VCF ingestion
import tiledb.cloud.vcf

# Use specialized VCF ingestion module
# Note: Exact API requires TileDB-Cloud documentation
# This represents the available functionality structure
tiledb.cloud.vcf.ingestion.ingest_vcf_dataset(
    source="s3://my-bucket/vcf-files/",
    output="tiledb://my-namespace/large-dataset",
    namespace="my-namespace",
    acn="my-s3-credentials",
    ingest_resources={"cpu": "16", "memory": "64Gi"}
)
```

**分布式查询处理**
```python
# TileDB-Cloud: VCF querying across distributed storage
import tiledb.cloud.vcf
import tiledbvcf

# Define the dataset URI
dataset_uri = "tiledb://TileDB-Inc/gvcf-1kg-dragen-v376"

# Get all samples from the dataset
ds = tiledbvcf.Dataset(dataset_uri, tiledb_config=cfg)
samples = ds.samples()

# Define attributes and ranges to query on
attrs = ["sample_name", "fmt_GT", "fmt_AD", "fmt_DP"]
regions = ["chr13:32396898-32397044", "chr13:32398162-32400268"]

# Perform the read, which is executed in a distributed fashion
df = tiledb.cloud.vcf.read(
    dataset_uri=dataset_uri,
    regions=regions,
    samples=samples,
    attrs=attrs,
    namespace="my-namespace",  # specifies which account to charge
)
df.to_pandas()
```

### 企业级特性

**数据共享与协作**
```python
# TileDB-Cloud provides enterprise data sharing capabilities
# through namespace-based permissions and group management

# Access shared datasets via TileDB-Cloud URIs
dataset_uri = "tiledb://shared-namespace/population-study"

# Collaborate through shared notebooks and compute resources
# (Specific API requires TileDB-Cloud documentation)
```

**成本优化**
- **无服务器计算(Serverless Compute)**:只为实际计算时间付费
- **自动扩缩容(Auto-scaling)**:根据工作负载自动扩容/缩容
- **竞价实例(Spot Instances)**:为批处理任务使用成本优化的计算资源
- **数据分层(Data Tiering)**:自动进行热/冷存储管理

**安全与合规**
- **端到端加密**:数据在传输和静态存储时均加密
- **访问控制**:细粒度权限与审计日志
- **HIPAA/SOC2 合规**:企业级安全标准
- **VPC 支持**:可在私有云环境中部署

### 何时迁移检查清单

✅ **在以下情况下迁移到 TileDB-Cloud**:
- [ ] 数据集样本数超过 1000
- [ ] 需要处理超过 100GB 的 VCF 数据
- [ ] 需要分布式计算
- [ ] 多个团队成员需要访问权限
- [ ] 需要企业级安全/合规
- [ ] 希望使用成本优化的无服务器计算
- [ ] 需要 7x24 小时的生产环境可用性

### 开始使用 TileDB-Cloud

1. **免费开始**:TileDB-Cloud 提供免费层供评估使用
2. **迁移支持**:TileDB 团队提供迁移协助
3. **培训**:可获取基因组学专项教程和示例
4. **专业服务**:定制化部署与优化

**下一步**:
- 访问 https://cloud.tiledb.com 创建账号
- 查阅 https://cloud.tiledb.com/academy/ 上的文档
- 企业需求请联系 sales@tiledb.com
