# PrimeKG 知识图谱技能

## 概述

PrimeKG 是一个精准医学知识图谱，把 20 多个主要数据库以及高质量的
科学文献整合到一个统一的资源中。它包含超过 100,000 个节点、
400 万条边，涵盖 29 种关系类型，包括药物-靶点、疾病-基因，以及
表型-疾病关联。

**核心能力**：
- 搜索节点（基因、蛋白质、药物、疾病、表型）
- 检索直接邻居（相关实体与临床证据）
- 分析局部疾病语境（相关基因、药物、表型）
- 识别药物-疾病路径（潜在的药物重定位机会）

**数据访问**： 通过 `query_primekg.py` 进行编程访问。数据存储在
`C:\Users\eamon\Documents\Data\PrimeKG\kg.csv`。

## 何时使用本技能

在以下情况下应使用本技能：

- **基于知识的药物发现**： 识别针对某种疾病的靶点和机制。
- **药物重定位**： 寻找可能有证据支持新适应症的现有药物。
- **表型分析**： 理解症状/表型与疾病及基因之间的关系。
- **多尺度生物学**： 在分子靶点（基因）与临床结局（疾病）之间架起
  桥梁。
- **网络药理学**： 研究药物-靶点相互作用更广泛的网络效应。

## 核心工作流

### 1. 搜索实体

查找基因、药物或疾病的标识符。

```python
from scripts.query_primekg import search_nodes

# 搜索阿尔茨海默病相关节点
results = search_nodes("Alzheimer", node_type="disease")
# Returns: [{"id": "EFO_0000249", "type": "disease", "name": "Alzheimer's disease", ...}]
```

### 2. 获取邻居（直接关联）

检索所有相连的节点及其关系类型。

```python
from scripts.query_primekg import get_neighbors

# 获取某个特定疾病 ID 的所有邻居
neighbors = get_neighbors("EFO_0000249")
# Returns: List of neighbors like {"neighbor_name": "APOE", "relation": "disease_gene", ...}
```

### 3. 分析疾病语境

一个高层级的函数，用于汇总某种疾病的各类关联信息。

```python
from scripts.query_primekg import get_disease_context

# 某种疾病的综合摘要
context = get_disease_context("Alzheimer's disease")
# Access: context['associated_genes'], context['associated_drugs'], context['phenotypes']
```

## PrimeKG 中的关系类型

该图谱包含若干关键关系类型，包括：
- `protein_protein`：物理上的蛋白质-蛋白质相互作用（PPI）
- `drug_protein`：药物靶点/机制关联
- `disease_gene`：遗传关联
- `drug_disease`：适应症与禁忌症
- `disease_phenotype`：临床体征与症状
- `gwas`：全基因组关联研究证据

## 最佳实践

1. **使用具体的 ID**： 在使用 `get_neighbors` 时，要确保拥有从
   `search_nodes` 得到的正确 ID。
2. **先看语境**： 在深入研究具体的基因或药物之前，先用
   `get_disease_context` 获得一个宽泛的概览。
3. **过滤关系**： 使用 `get_neighbors` 中的 `relation_type`
   过滤条件，聚焦于特定证据（例如只看 `drug_protein`）。
4. **多尺度整合**： 与 `OpenTargets` 结合以获得更深入的遗传学证据，
   或与 `Semantic Scholar` 结合以获得最新的文献语境。

## 资源

### 脚本
- `scripts/query_primekg.py`：用于搜索和查询该知识图谱的核心函数。

### 数据路径
- 数据：`kg.csv`，下载自
  [PrimeKG Harvard Dataverse](https://dataverse.harvard.edu/dataverse/primekg)。
- 用 `export PRIMEKG_DATA=/path/to/kg.csv` 让脚本指向该数据
  （默认：`data/PrimeKG/kg.csv`）。
- 节点总数：约 129,000 个
- 边总数：约 4,000,000 条
- 数据库：基于 CSV，针对 pandas 查询做了优化。
