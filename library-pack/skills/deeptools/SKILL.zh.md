# deepTools：NGS 数据分析工具包

## 概述

deepTools 是一套全面的 Python 命令行工具，专为处理和分析高通量测序数据而设计。使用 deepTools 可以对 ChIP-seq、RNA-seq、ATAC-seq、MNase-seq 及其他 NGS 实验进行质量控制、数据归一化、样本比较，并生成出版级质量的可视化图形。

**核心能力**：
- 将 BAM 比对结果转换为归一化的覆盖度轨迹（bigWig/bedGraph）
- 质量控制评估（fingerprint、相关性、覆盖度）
- 样本比较与相关性分析
- 围绕基因组特征生成热图和轮廓图（profile plot）
- 富集分析与峰区域可视化

## 何时使用此技能

在以下情况应使用此技能：

- **文件转换**："将 BAM 转换为 bigWig"、"生成覆盖度轨迹"、"归一化 ChIP-seq 数据"
- **质量控制**："检查 ChIP 质量"、"比较重复样本"、"评估测序深度"、"QC 分析"
- **可视化**："在 TSS 周围创建热图"、"绘制 ChIP 信号"、"可视化富集情况"、"生成轮廓图"
- **样本比较**："比较处理组与对照组"、"样本相关性分析"、"PCA 分析"
- **分析工作流**："分析 ChIP-seq 数据"、"RNA-seq 覆盖度"、"ATAC-seq 分析"、"完整工作流"
- **处理特定文件类型**：基因组学场景下的 BAM 文件、bigWig 文件、BED 区域文件

## 快速开始

对于初次使用 deepTools 的用户，应从文件验证和常见工作流开始：

### 1. 验证输入文件

在运行任何分析之前，使用验证脚本验证 BAM、bigWig 和 BED 文件：

```bash
python scripts/validate_files.py --bam sample1.bam sample2.bam --bed regions.bed
```

此操作会检查文件是否存在、BAM 索引以及格式的正确性。

### 2. 生成工作流模板

对于标准分析，使用工作流生成器创建定制化脚本：

```bash
# List available workflows
python scripts/workflow_generator.py --list

# Generate ChIP-seq QC workflow
python scripts/workflow_generator.py chipseq_qc -o qc_workflow.sh \
    --input-bam Input.bam --chip-bams "ChIP1.bam ChIP2.bam" \
    --genome-size 2913022398

# Make executable and run
chmod +x qc_workflow.sh
./qc_workflow.sh
```

### 3. 最常见的操作

参见 `assets/quick_reference.md`，获取常用命令和参数。

## 安装

```bash
uv pip install deepTools==3.5.6
```

上游推荐使用 conda/bioconda 以获得完整的依赖解析，尤其是在共享的 HPC 系统上：

```bash
conda install -c conda-forge -c bioconda deeptools
```

在 Apple Silicon 上，当原生 conda 软件包不可用时，上游文档中说明了两种方案：使用上述 PyPI 途径，或使用 `osx-64` conda 环境。

## 核心工作流与工具类别

针对 ChIP-seq QC、完整 ChIP-seq 分析、RNA-seq 覆盖度以及 ATAC-seq 分析的完整命令序列——以及 BAM/bigWig 处理、质量控制和可视化工具类别——请参阅
[references/core_workflows.md](references/core_workflows.md) 和
[references/workflows.md](references/workflows.md)。各工具的具体选项参见
[references/tools_reference.md](references/tools_reference.md)。

## 归一化方法

选择正确的归一化方法对于有效的比较至关重要。全面的指导请参阅 `references/normalization_methods.md`。

**快速选择指南**：

- **ChIP-seq 覆盖度**：使用 RPGC 或 CPM
- **ChIP-seq 比较**：使用 bamCompare，并搭配 log2 和 readCount
- **RNA-seq 分箱（bin）**：使用 CPM
- **RNA-seq 基因**：使用 RPKM（考虑基因长度）
- **ATAC-seq**：使用 RPGC 或 CPM

**归一化方法**：
- **RPGC**：1× 基因组覆盖度（需要 --effectiveGenomeSize）
- **CPM**：每百万比对读段的计数（Counts per million mapped reads）
- **RPKM**：每千碱基每百万读段数（按 bin 长度和文库大小进行缩放）
- **BPM**：每百万 bin 数，类似于对分箱信号进行 TPM 风格的缩放
- **None**：原始计数（不建议用于比较）

完整说明：`references/normalization_methods.md`

## 有效基因组大小

RPGC 归一化需要有效基因组大小。常见数值如下：

| 物种 | 组装版本 | 大小 | 用法 |
|----------|----------|------|-------|
| 人类 | GRCh38/hg38 | 2,913,022,398 | `--effectiveGenomeSize 2913022398` |
| 人类 | T2T/CHM13CAT_v2 | 3,117,292,070 | `--effectiveGenomeSize 3117292070` |
| 小鼠 | GRCm39/mm39 | 2,654,621,783 | `--effectiveGenomeSize 2654621783` |
| 小鼠 | GRCm38/mm10 | 2,652,783,500 | `--effectiveGenomeSize 2652783500` |
| 斑马鱼 | GRCz11 | 1,368,780,147 | `--effectiveGenomeSize 1368780147` |
| *果蝇（Drosophila）* | dm6 | 142,573,017 | `--effectiveGenomeSize 142573017` |
| *秀丽隐杆线虫（C. elegans）* | ce10/ce11 | 100,286,401 | `--effectiveGenomeSize 100286401` |

按读段长度细分的完整表格：`references/effective_genome_sizes.md`

## 各工具通用的参数

许多 deepTools 命令共享以下选项：

**性能**：
- `--numberOfProcessors, -p`：启用并行处理（应始终使用可用的全部核心）
- `max` / `max/2`：`--numberOfProcessors` 支持的取值；在调度系统下很有用，因为较新版本的 deepTools 会更细致地检测 CPU 亲和性（affinity）
- `--region`：处理特定区域以便测试（例如 `chr1:1-1000000`）

**读段过滤**：
- `--ignoreDuplicates`：移除 PCR 重复读段（多数分析中推荐使用）
- `--minMappingQuality`：按比对质量过滤（例如 `--minMappingQuality 10`）
- `--minFragmentLength` / `--maxFragmentLength`：片段长度上下限
- `--samFlagInclude` / `--samFlagExclude`：SAM 标志过滤

**读段处理**：
- `--extendReads`：延伸至片段长度（ChIP-seq：是，RNA-seq：否）
- `--centerReads`：以片段中点为中心，获得更清晰的信号

## 最佳实践

### 文件验证
**务必首先验证文件**，使用 `scripts/validate_files.py` 检查：
- 文件是否存在及可读性
- 是否存在 BAM 索引（.bai 文件）
- BED 格式的正确性
- 文件大小是否合理

### 分析策略

1. **从 QC 开始**：在继续之前先运行相关性、覆盖度和 fingerprint 分析
2. **在小区域上测试**：使用 `--region chr1:1-10000000` 进行参数测试
3. **记录命令**：保存完整命令行以保证可复现性
4. **使用一致的归一化方法**：在比较中的所有样本上应用相同方法
5. **验证基因组组装版本**：确保 BAM 和 BED 文件使用一致的基因组构建版本

### ChIP-seq 专项

- 对 ChIP-seq **务必延伸读段**：`--extendReads 200`
- **移除重复读段**：大多数情况下使用 `--ignoreDuplicates`
- **先检查富集情况**：在详细分析前运行 plotFingerprint
- **GC 校正**：仅在检测到显著偏差时才应用；GC 校正之后切勿再使用 `--ignoreDuplicates`

### RNA-seq 专项

- 对 RNA-seq **切勿延伸读段**（会跨越剪接位点）
- **链特异性**：对常见的 dUTP 型链特异性文库使用 `--filterRNAstrand forward/reverse`；在解读链标签之前先确认文库方向
- **归一化**：分箱用 CPM，基因用 RPKM

### ATAC-seq 专项

- **应用 Tn5 校正**：使用带 `--ATACshift` 的 alignmentSieve
- **移位时只使用正确配对**：`--ATACshift` 等效于 `--shift 4 -5 5 -4`，且只筛选正确配对的片段
- **片段过滤**：设置合适的最小/最大片段长度
- **检查核小体模式**：片段大小图应呈现阶梯状模式

### 性能优化

1. **使用多个处理器**：`--numberOfProcessors 8`（或可用核心数）
2. **增大 bin 大小**以加快处理速度并减小文件体积
3. 对内存受限的系统**分别处理各染色体**
4. **预先过滤 BAM 文件**，使用 alignmentSieve 创建可重复使用的过滤后文件
5. **优先使用 bigWig 而非 bedGraph**：经过压缩且处理更快

## 故障排查

### 常见问题

**BAM 索引缺失**：
```bash
samtools index input.bam
```

**内存不足**：
使用 `--region` 逐个染色体处理：
```bash
bamCoverage --bam input.bam -o chr1.bw --region chr1
```

**处理速度慢**：
增大 `--numberOfProcessors` 和/或增大 `--binSize`

**bigWig 文件过大**：
增大 bin 大小：`--binSize 50` 或更大

### 验证错误

运行验证脚本以定位问题：
```bash
python scripts/validate_files.py --bam *.bam --bed regions.bed
```

脚本输出中会解释常见错误及解决方法。

## 参考文档

此技能包含全面的参考文档：

### references/tools_reference.md
按类别组织的所有 deepTools 命令的完整文档：
- BAM 和 bigWig 处理工具（9 个工具）
- 质量控制工具（6 个工具）
- 可视化工具（3 个工具）
- 其他工具（3 个工具，包括 `bigwigAverage`）

每个工具都包含：
- 用途和概述
- 关键参数说明
- 用法示例
- 重要说明与最佳实践

**使用此参考的场景**： 用户询问特定工具、参数或详细用法时。

### references/workflows.md
常见分析的完整工作流示例：
- ChIP-seq 质量控制工作流
- ChIP-seq 完整分析工作流
- RNA-seq 覆盖度工作流
- ATAC-seq 分析工作流
- 多样本比较工作流
- 峰区域分析工作流
- 故障排查与性能提升技巧

**使用此参考的场景**： 用户需要完整的分析流水线或工作流示例时。

### references/normalization_methods.md
归一化方法的全面指南：
- 每种方法的详细说明（RPGC、CPM、RPKM、BPM 等）
- 何时使用每种方法
- 公式与解读
- 按实验类型划分的选择指南
- 常见陷阱与解决方法
- 快速参考表

**使用此参考的场景**： 用户询问归一化、样本比较或应使用哪种方法时。

### references/effective_genome_sizes.md
有效基因组大小数值与用法：
- 常见物种数值（人类、小鼠、果蝇、线虫、斑马鱼）
- 按读段长度细分的数值
- 计算方法
- 命令中何时以及如何使用
- 自定义基因组的计算说明

**使用此参考的场景**： 用户需要用于 RPGC 归一化或 GC 偏差校正的基因组大小时。

## 辅助脚本

### scripts/validate_files.py

为 deepTools 分析验证 BAM、bigWig 和 BED 文件。检查文件是否存在、索引以及格式。

**用法**：
```bash
python scripts/validate_files.py --bam sample1.bam sample2.bam \
    --bed peaks.bed --bigwig signal.bw
```

**何时使用**： 在开始任何分析之前，或在排查错误时。

### scripts/workflow_generator.py

为常见的 deepTools 工作流生成可定制的 bash 脚本模板。

**可用工作流**：
- `chipseq_qc`：ChIP-seq 质量控制
- `chipseq_analysis`：完整 ChIP-seq 分析
- `rnaseq_coverage`：链特异性 RNA-seq 覆盖度
- `atacseq`：带 Tn5 校正的 ATAC-seq

**用法**：
```bash
# List workflows
python scripts/workflow_generator.py --list

# Generate workflow
python scripts/workflow_generator.py chipseq_qc -o qc.sh \
    --input-bam Input.bam --chip-bams "ChIP1.bam ChIP2.bam" \
    --genome-size 2913022398 --threads 8

# Run generated workflow
chmod +x qc.sh
./qc.sh
```

**何时使用**： 用户请求标准工作流，或需要可供定制的模板脚本时。

## 资产

### assets/quick_reference.md

快速参考卡，包含最常用的命令、有效基因组大小以及典型的工作流模式。

**何时使用**： 用户需要快速的命令示例，而非详细文档时。

## 处理用户请求

### 面向新用户

1. 从安装验证开始
2. 使用 `scripts/validate_files.py` 验证输入文件
3. 根据实验类型推荐合适的工作流
4. 使用 `scripts/workflow_generator.py` 生成工作流模板
5. 指导用户完成定制和执行

### 面向有经验的用户

1. 为所请求的操作提供具体的工具命令
2. 参考 `references/tools_reference.md` 中的相应章节
3. 提出优化建议和最佳实践
4. 为问题提供故障排查

### 针对特定任务

**"将 BAM 转换为 bigWig"**：
- 使用带合适归一化方法的 bamCoverage
- 根据使用场景推荐 RPGC 或 CPM
- 提供该物种的有效基因组大小
- 建议相关参数（extendReads、ignoreDuplicates、binSize）

**"检查 ChIP 质量"**：
- 运行完整的 QC 工作流，或专门使用 plotFingerprint
- 解释结果的解读方式
- 根据结果建议后续操作

**"创建热图"**：
- 指导完成两步流程：computeMatrix → plotHeatmap
- 帮助选择合适的矩阵模式（reference-point 还是 scale-regions）
- 建议可视化参数和聚类选项

**"比较样本"**：
- 对两样本比较推荐使用 bamCompare
- 对多样本推荐使用 multiBamSummary + plotCorrelation
- 指导归一化方法的选择

### 引用文档

当用户需要详细信息时：
- **工具细节**：指向 `references/tools_reference.md` 中的具体章节
- **工作流**：使用 `references/workflows.md` 获取完整的分析流水线
- **归一化**：查阅 `references/normalization_methods.md` 进行方法选择
- **基因组大小**：参考 `references/effective_genome_sizes.md`

## 交互示例

**用户："我需要分析我的 ChIP-seq 数据"**

回应方式：
1. 询问可用的文件（BAM 文件、峰、基因）
2. 使用验证脚本验证文件
3. 生成 chipseq_analysis 工作流模板
4. 根据其具体文件和物种进行定制
5. 在脚本运行时解释每个步骤

**用户："我应该使用哪种归一化方法？"**

回应方式：
1. 询问实验类型（ChIP-seq、RNA-seq 等）
2. 询问比较目标（样本内还是样本间）
3. 查阅 `references/normalization_methods.md` 的选择指南
4. 推荐合适的方法并说明理由
5. 提供带参数的命令示例

**用户："在 TSS 周围创建热图"**

回应方式：
1. 确认已有可用的 bigWig 和基因 BED 文件
2. 在 TSS 处使用 reference-point 模式的 computeMatrix
3. 使用合适的可视化参数生成 plotHeatmap
4. 若数据集较大，建议进行聚类
5. 建议增加轮廓图（profile plot）作为补充

## 关键提醒

- **先验证文件**：分析前务必先验证输入文件
- **归一化很关键**：根据比较类型选择合适的方法
- **谨慎延伸读段**：ChIP-seq 需要，RNA-seq 不需要
- **使用全部核心**：将 `--numberOfProcessors` 设置为可用核心数
- **在区域上测试**：使用 `--region` 进行参数测试
- **先检查 QC**：在详细分析前先运行质量控制
- **记录一切**：保存命令以保证可复现性
- **参考文档**：使用全面的参考资料获取详细指导
