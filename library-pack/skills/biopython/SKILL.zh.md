# Biopython：用 Python 进行计算分子生物学

## 概述

Biopython 是一套面向生物计算的、完全免费的 Python 工具集合。它提供序列操作、文件 I/O、数据库访问、结构生物信息学、系统发育学以及其他众多生物信息学任务所需的功能。当前版本为 **Biopython 1.87**（发布于 2026 年 3 月 30 日）。它支持 **Python 3.10-3.14** 以及 PyPy3.10，并依赖 NumPy。Biopython 1.87 还修复了 `Bio.Entrez.Parser` 在解析不可信文件时存在的 **CVE-2025-68463** 漏洞，因此在解析外部提供的 Entrez XML 的工作流中，应优先使用 1.87 及以上版本。

## 何时使用此技能

在以下情况下使用此技能：

- 处理生物序列（DNA、RNA 或蛋白质）
- 读取、写入或转换生物文件格式（FASTA、GenBank、FASTQ、PDB、mmCIF 等）
- 通过 Entrez 访问 NCBI 数据库（GenBank、PubMed、Protein、Gene 等）
- 运行 BLAST 检索或解析 BLAST 结果
- 执行序列比对（成对比对或多序列比对）
- 分析来自 PDB 文件的蛋白质结构
- 创建、操作或可视化系统发育树
- 查找序列基序（motif）或分析基序模式
- 计算序列统计量（GC 含量、分子量、解链温度等）
- 执行结构生物信息学任务
- 处理群体遗传学数据
- 任何其他计算分子生物学任务

## 核心能力

Biopython 由多个模块化的子包组成，每个子包针对特定的生物信息学领域：

1. **序列处理** —— Bio.Seq 与 Bio.SeqIO 用于序列操作和文件 I/O
2. **比对分析** —— Bio.Align 与 Bio.AlignIO 用于成对比对和多序列比对
3. **数据库访问** —— Bio.Entrez 用于程序化访问 NCBI 数据库
4. **BLAST 操作** —— Bio.Blast 用于运行和解析 BLAST 检索
5. **结构生物信息学** —— Bio.PDB 用于处理三维蛋白质结构
6. **系统发育学** —— Bio.Phylo 用于系统发育树的操作与可视化
7. **进阶功能** —— 基序、群体遗传学、序列工具等

## 安装与设置

安装当前稳定版 Biopython，并显式锁定版本号以保证可复现性：

```bash
uv pip install "biopython==1.87"
```

若要访问 NCBI 数据库，请始终设置你的邮箱地址（NCBI 要求）。对于可复用的软件，应设置一个稳定的 `Entrez.tool` 值，并向 NCBI 注册该工具/邮箱。若要获得更高的速率限制（从 3 次/秒提升到 10 次/秒），只从环境变量中读取 `NCBI_API_KEY` —— 不要硬编码密钥，也不要加载无关的环境变量：

```python
import os
from Bio import Entrez

Entrez.email = "your.email@example.com"  # 必需 —— 使用你的真实邮箱
Entrez.tool = "your_tool_name"  # 可选,但对可复用的软件推荐设置

# 可选：在 https://www.ncbi.nlm.nih.gov/account/settings/ 注册
if api_key := os.environ.get("NCBI_API_KEY"):
    Entrez.api_key = api_key
```

## 使用此技能

此技能提供了按功能领域组织的完整文档。处理任务时，请查阅相应的参考文档：

### 1. 序列处理（Bio.Seq 与 Bio.SeqIO）

**参考文档**： `references/sequence_io.md`

适用于：
- 创建和操作生物序列
- 读写序列文件（FASTA、GenBank、FASTQ 等）
- 在各文件格式之间转换
- 从大文件中提取序列
- 序列翻译、转录和反向互补
- 处理 SeqRecord 对象

**快速示例**：
```python
from Bio import SeqIO

# 从 FASTA 文件读取序列
for record in SeqIO.parse("sequences.fasta", "fasta"):
    print(f"{record.id}: {len(record.seq)} bp")

# 将 GenBank 转换为 FASTA
SeqIO.convert("input.gb", "genbank", "output.fasta", "fasta")
```

### 2. 比对分析（Bio.Align 与 Bio.AlignIO）

**参考文档**： `references/alignment.md`

适用于：
- 成对序列比对（全局比对与局部比对）
- 读写多序列比对
- 使用替换矩阵（BLOSUM、PAM）
- 计算比对统计量
- 自定义比对参数

**快速示例**：
```python
from Bio import Align

# 成对比对
aligner = Align.PairwiseAligner()
aligner.mode = 'global'
alignments = aligner.align("ACCGGT", "ACGGT")
print(alignments[0])
```

### 3. 数据库访问（Bio.Entrez）

**参考文档**： `references/databases.md`

适用于：
- 检索 NCBI 数据库（PubMed、GenBank、Protein、Gene 等）
- 下载序列和记录
- 获取出版物信息
- 在各数据库之间查找相关记录
- 以适当的速率限制进行批量下载

**快速示例**：
```python
from Bio import Entrez
Entrez.email = "your.email@example.com"

# 检索 PubMed
handle = Entrez.esearch(db="pubmed", term="biopython", retmax=10)
results = Entrez.read(handle)
handle.close()
print(f"Found {results['Count']} results")
```

### 4. BLAST 操作（Bio.Blast）

**参考文档**： `references/blast.md`

适用于：
- 通过 NCBI 网络服务运行 BLAST 检索
- 运行本地 BLAST 检索
- 解析 BLAST XML 输出
- 按 E-value 或相似度过滤结果
- 提取命中序列

**快速示例**：
```python
from Bio.Blast import NCBIWWW, NCBIXML

# 运行 BLAST 检索
result_handle = NCBIWWW.qblast("blastn", "nt", "ATCGATCGATCG")
blast_record = NCBIXML.read(result_handle)

# 显示排名靠前的命中结果
for alignment in blast_record.alignments[:5]:
    print(f"{alignment.title}: E-value={alignment.hsps[0].expect}")
```

### 5. 结构生物信息学（Bio.PDB）

**参考文档**： `references/structure.md`

适用于：
- 解析 PDB 和 mmCIF 结构文件
- 遍历蛋白质结构层级（SMCRA：Structure/Model/Chain/Residue/Atom）
- 计算距离、键角和二面角
- 二级结构指派（DSSP）
- 结构叠合与 RMSD 计算
- 从结构中提取序列

**快速示例**：
```python
from Bio.PDB import PDBParser

# 解析结构
parser = PDBParser(QUIET=True)
structure = parser.get_structure("1crn", "1crn.pdb")

# 计算 α 碳原子之间的距离
chain = structure[0]["A"]
distance = chain[10]["CA"] - chain[20]["CA"]
print(f"Distance: {distance:.2f} Å")
```

### 6. 系统发育学（Bio.Phylo）

**参考文档**： `references/phylogenetics.md`

适用于：
- 读写系统发育树（Newick、NEXUS、phyloXML）
- 从距离矩阵或比对结果构建树
- 树的操作（修剪、重新定根、梯形排列）
- 计算系统发育距离
- 创建一致树（consensus tree）
- 树的可视化

**快速示例**：
```python
from Bio import Phylo

# 读取并可视化树
tree = Phylo.read("tree.nwk", "newick")
Phylo.draw_ascii(tree)

# 计算距离
distance = tree.distance("Species_A", "Species_B")
print(f"Distance: {distance:.3f}")
```

### 7. 进阶功能

**参考文档**： `references/advanced.md`

适用于：
- **序列基序**（Bio.motifs）—— 查找和分析基序模式
- **群体遗传学**（Bio.PopGen）—— GenePop 文件、Fst 计算、哈迪-温伯格检验
- **序列工具**（Bio.SeqUtils）—— GC 含量、解链温度、分子量、蛋白质分析
- **限制性酶切分析**（Bio.Restriction）—— 查找限制性内切酶位点
- **聚类**（Bio.Cluster）—— K-means 和层次聚类
- **基因组图谱**（GenomeDiagram）—— 基因组特征的可视化

**快速示例**：
```python
from Bio.SeqUtils import gc_fraction, molecular_weight
from Bio.Seq import Seq

seq = Seq("ATCGATCGATCG")
print(f"GC content: {gc_fraction(seq):.2%}")
print(f"Molecular weight: {molecular_weight(seq, seq_type='DNA'):.2f} g/mol")
```

## 通用工作流程指南

### 阅读文档

当用户询问某个具体的 Biopython 任务时：

1. **根据任务描述确定相关模块**
2. **使用 Read 工具阅读相应的参考文件**
3. **提取相关的代码模式**并将其调整以适应用户的具体需求
4. **在任务需要时组合使用多个模块**

参考文件的示例检索模式：
```bash
# 查找特定函数的相关信息
rg -n "SeqIO.parse" references/sequence_io.md

# 查找特定任务的示例
rg -n "BLAST" references/blast.md

# 查找特定概念的相关信息
rg -n "alignment" references/alignment.md
```

### 编写 Biopython 代码

编写 Biopython 代码时请遵循以下原则：

1. **显式导入模块**
   ```python
   from Bio import SeqIO, Entrez
   from Bio.Seq import Seq
   ```

2. **在使用 NCBI 数据库时设置 Entrez 邮箱**；若存在 `NCBI_API_KEY` 环境变量，只加载该变量
   ```python
   import os
   from Bio import Entrez

   Entrez.email = "your.email@example.com"
   Entrez.tool = "your_tool_name"
   if api_key := os.environ.get("NCBI_API_KEY"):
       Entrez.api_key = api_key
   ```

3. **使用合适的文件格式** —— 检查哪种格式最适合该任务
   ```python
   # 常见格式："fasta"、"genbank"、"fastq"、"clustal"、"phylip"
   ```

4. **妥善处理文件句柄** —— 使用后关闭句柄，或使用上下文管理器
   ```python
   with open("file.fasta") as handle:
       records = SeqIO.parse(handle, "fasta")
   ```

5. **对大文件使用迭代器** —— 避免把所有内容一次性载入内存
   ```python
   for record in SeqIO.parse("large_file.fasta", "fasta"):
       # 逐条处理记录
   ```

6. **妥善处理错误** —— 网络操作和文件解析都可能失败
   ```python
   from urllib.error import HTTPError

   try:
       handle = Entrez.efetch(db="nucleotide", id=accession)
   except HTTPError as e:
       print(f"Error: {e}")
   ```

## 常见模式

### 模式 1：从 GenBank 获取序列

```python
from Bio import Entrez, SeqIO

Entrez.email = "your.email@example.com"

# 获取序列
handle = Entrez.efetch(db="nucleotide", id="EU490707", rettype="gb", retmode="text")
record = SeqIO.read(handle, "genbank")
handle.close()

print(f"Description: {record.description}")
print(f"Sequence length: {len(record.seq)}")
```

### 模式 2：序列分析流水线

```python
from Bio import SeqIO
from Bio.SeqUtils import gc_fraction

for record in SeqIO.parse("sequences.fasta", "fasta"):
    # 计算统计量
    gc = gc_fraction(record.seq)
    length = len(record.seq)

    # 查找 ORF、翻译等
    protein = record.seq.translate()

    print(f"{record.id}: {length} bp, GC={gc:.2%}")
```

### 模式 3：BLAST 检索并获取排名靠前的命中结果

```python
from Bio.Blast import NCBIWWW, NCBIXML
from Bio import Entrez, SeqIO

Entrez.email = "your.email@example.com"

# 运行 BLAST
result_handle = NCBIWWW.qblast("blastn", "nt", sequence)
blast_record = NCBIXML.read(result_handle)

# 获取排名靠前的命中登录号
accessions = [aln.accession for aln in blast_record.alignments[:5]]

# 获取序列
for acc in accessions:
    handle = Entrez.efetch(db="nucleotide", id=acc, rettype="fasta", retmode="text")
    record = SeqIO.read(handle, "fasta")
    handle.close()
    print(f">{record.description}")
```

### 模式 4：从序列构建系统发育树

```python
from Bio import AlignIO, Phylo
from Bio.Phylo.TreeConstruction import DistanceCalculator, DistanceTreeConstructor

# 读取比对结果
alignment = AlignIO.read("alignment.fasta", "fasta")

# 计算距离
calculator = DistanceCalculator("identity")
dm = calculator.get_distance(alignment)

# 构建树
constructor = DistanceTreeConstructor()
tree = constructor.nj(dm)

# 可视化
Phylo.draw_ascii(tree)
```

## 最佳实践

1. **在编写代码之前，始终先阅读相关的参考文档**
2. **使用 grep 检索参考文件**以查找特定的函数或示例
3. **在解析之前验证文件格式**
4. **妥善处理缺失数据** —— 并非所有记录都包含全部字段
5. **缓存已下载的数据** —— 不要重复下载相同的序列
6. **遵守 NCBI 的速率限制** —— 使用 API 密钥、为可复用软件注册工具/邮箱值，并对大批量任务使用 Entrez 的历史记录/批处理功能
7. **先用小规模数据集测试**，再处理大文件
8. **保持 Biopython 处于最新版本**以获得最新功能和错误修复
9. **翻译时使用合适的遗传密码表**
10. **记录分析参数**以便结果可复现

## 常见问题排查

### 问题："No handlers could be found for logger 'Bio.Entrez'"
**解决方法**： 这只是一条警告。设置 Entrez.email 即可消除它。

### 问题：来自 NCBI 的 "HTTP Error 400"
**解决方法**： 检查 ID/登录号是否有效且格式正确。

### 问题：解析文件时出现 "ValueError: EOF"
**解决方法**： 确认文件格式与指定的格式字符串一致。

### 问题：比对失败并提示 "sequences are not the same length"
**解决方法**： 在使用 AlignIO 或 MultipleSeqAlignment 之前，确保序列已经过比对。

### 问题：BLAST 检索速度慢
**解决方法**： 对大规模检索使用本地 BLAST，或缓存结果。

### 问题：PDB 解析器发出警告
**解决方法**： 使用 `PDBParser(QUIET=True)` 抑制警告，或进一步调查结构质量问题。

### 问题：Bio.HMM、Bio.MarkovModel 或 Bio.Application 出现 ImportError
**解决方法**： 这些模块已在 Biopython 1.86 中被移除。请使用 [hmmlearn](https://pypi.org/project/hmmlearn/) 处理 HMM，并用标准库中的 `subprocess` 模块代替 `Bio.Application` 的命令行封装。

### 问题：升级到 1.86+ 后，PairwiseAligner 返回的比对结果变少了
**解决方法**： 默认的空位罚分（gap score）在 1.86 中从 0 变为 -1，从而消除了平凡的并列比对结果。如需恢复旧行为，可设置 `aligner.gap_score = 0`（详见 `references/alignment.md`）。

## 其他资源

- **官方文档**：https://biopython.org/docs/latest/
- **教程**：https://biopython.org/docs/latest/Tutorial/
- **Cookbook**：<https://biopython.org/docs/latest/Tutorial/>（进阶示例）
- **GitHub**：https://github.com/biopython/biopython
- **发布说明**：https://github.com/biopython/biopython/blob/master/NEWS.rst
- **已弃用的 API**：https://github.com/biopython/biopython/blob/master/DEPRECATED.rst
- **邮件列表**：biopython@biopython.org

## 快速参考

要在参考文件中定位信息，可使用以下检索模式：

```bash
# 检索特定函数
rg -n "function_name" references/*.md

# 查找特定任务的示例
rg -n "example" references/sequence_io.md

# 查找某个模块的全部出现位置
rg -n "Bio.Seq" references/*.md
```

## 总结

Biopython 为计算分子生物学提供了全面的工具。使用此技能时：

1. **确定任务所属领域**（序列、比对、数据库、BLAST、结构或进阶功能）
2. **查阅 `references/` 目录中相应的参考文件**
3. **将代码示例调整**以适应具体的使用场景
4. **在复杂工作流需要时组合使用多个模块**
5. **在文件处理、错误检查和数据管理方面遵循最佳实践**

模块化的参考文档确保了 Biopython 每一项主要能力都拥有详尽、可检索的信息。
