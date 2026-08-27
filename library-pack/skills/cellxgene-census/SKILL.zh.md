# CZ CELLxGENE Census

## 概览

CZ CELLxGENE Census 提供对来自 CZ CELLxGENE Discover 的、经过标准化的单细胞与空间转录组学数据的、全面且带版本管理的程序化访问。本技能能够在无需先下载整个数据集的情况下，高效地查询和分析公开的 Census 发布版本。

Census 包含:
- 2025-11-08 稳定 LTS 版本中共 **2.17 亿+ 个细胞**,其中**1.25 亿+ 个唯一细胞**
- 2025-11-08 稳定 LTS 版本中的 **1,845 个数据集**
- 当前 schema 中包含**人类、小鼠、狨猴、恒河猴和黑猩猩**数据
- **标准化元数据**(细胞类型、组织、疾病、供体)
- **原始基因表达**矩阵及源 H5AD 查找/下载辅助工具
- **预先计算好的汇总计数、嵌入(embeddings)和空间数据**
- **与 AnnData、Scanpy、TileDB-SOMA、TileDB-SOMA-ML 及其他分析工具的集成**

## 何时使用本技能

在以下情形应当使用本技能:
- 按细胞类型、组织或疾病查询单细胞表达数据
- 探索可用的单细胞数据集和元数据
- 在单细胞数据上训练机器学习模型
- 进行大规模的跨数据集分析
- 将 Census 数据与 scanpy 或其他分析框架集成
- 在数百万个细胞上计算统计量
- 访问预先计算好的嵌入或模型预测结果

## 安装与设置

安装 Census API:
```bash
uv pip install "cellxgene-census==1.17.*"
```

对于空间工作流程:
```bash
uv pip install "cellxgene-census[spatial]==1.17.*" "spatialdata[extra]>=0.2.5"
```

对于 PyTorch 模型训练，使用 TileDB-SOMA-ML。旧的 `cellxgene_census.experimental.ml` 加载器已被弃用:

```bash
uv pip install "cellxgene-census==1.17.*" tiledbsoma-ml
```

## 核心工作流程模式

八种模式，各附代码，见
[references/core_workflow_patterns.md](references/core_workflow_patterns.md):

1. **打开 Census** —— 始终锁定 `census_version`,使分析保持可复现。
2. **探索 Census 信息** —— 可用数据集、细胞计数和汇总表。
3. **查询表达数据** —— 中小规模数据，加载为 `AnnData`。
4. **大规模查询** —— 当数据切片无法装入内存时，使用超出内存(out-of-core)处理。
5. **使用 PyTorch 进行机器学习** —— Census 数据加载器。
6. **空间 Census 数据** —— 访问空间检测数据。
7. **与 Scanpy 集成** —— 将 Census 切片交给标准的 Scanpy 工作流程。
8. **多数据集整合** —— 合并多个数据集并处理批次效应。

## 关键概念与最佳实践

### 始终过滤仅保留一手数据(Primary Data)
除非要分析重复数据，否则务必在查询中包含 `is_primary_data == True`,以避免重复计数同一细胞:
```python
obs_value_filter="cell_type == 'B cell' and is_primary_data == True"
```

### 为可复现性指定 Census 版本
在正式分析中，始终显式指定 Census 版本:
```python
census = cellxgene_census.open_soma(census_version="2025-11-08")
```

### 加载前先估算查询规模
对于大型查询，先检查细胞数量以避免内存问题:
```python
# Get cell count
metadata = cellxgene_census.get_obs(
    census, "homo_sapiens",
    value_filter="tissue_general == 'brain' and is_primary_data == True",
    column_names=["soma_joinid"]
)
n_cells = len(metadata)
print(f"Query will return {n_cells:,} cells")

# If too large (>100k), use out-of-core processing
```

### 使用 tissue_general 进行更粗粒度的分组
`tissue_general` 字段提供比 `tissue` 更粗的分类，适用于跨组织分析:
```python
# Broader grouping
obs_value_filter="tissue_general == 'immune system'"

# Specific tissue
obs_value_filter="tissue == 'peripheral blood mononuclear cell'"
```

### 只选择需要的列
通过只指定所需的元数据列来减少数据传输量:
```python
obs_column_names=["cell_type", "tissue_general", "disease"]  # Not all columns
```

### 对特定基因的查询检查数据集覆盖情况
在分析特定基因时，验证哪些数据集测量了这些基因:
```python
presence = cellxgene_census.get_presence_matrix(
    census,
    "homo_sapiens",
    var_value_filter="feature_name in ['CD4', 'CD8A']"
)
```

### 两步走的工作流程:先探索，后查询
先探索元数据以了解可用数据，再查询表达数据:
```python
# Step 1: Explore what's available
metadata = cellxgene_census.get_obs(
    census, "homo_sapiens",
    value_filter="disease == 'COVID-19' and is_primary_data == True",
    column_names=["cell_type", "tissue_general"]
)
print(metadata.value_counts())

# Step 2: Query based on findings
adata = cellxgene_census.get_anndata(
    census=census,
    organism="Homo sapiens",
    obs_value_filter="disease == 'COVID-19' and cell_type == 'T cell' and is_primary_data == True",
)
```

## 可用的元数据字段

### 细胞元数据(obs)
用于过滤的关键字段:
- `cell_type`、`cell_type_ontology_term_id`
- `tissue`、`tissue_general`、`tissue_ontology_term_id`
- `disease`、`disease_ontology_term_id`
- `assay`、`assay_ontology_term_id`
- `donor_id`、`sex`、`self_reported_ethnicity`
- `development_stage`、`development_stage_ontology_term_id`
- `dataset_id`
- `is_primary_data`(布尔值:True = 唯一细胞)

当前 schema 包含人类和小鼠之外的其他物种集合。使用 `list(census["census_data"].keys())` 确认所选发布版本中的可用物种。

### 基因元数据(var)
- `feature_id`(Ensembl 基因 ID,例如 "ENSG00000161798")
- `feature_name`(基因符号，例如 "FOXP2")
- `feature_type`
- `feature_length`(基因长度，以碱基对为单位)
- `nnz`、`n_measured_obs`(可用性汇总信息，便于检查稀疏度和覆盖率)

## 参考文档

本技能包含详细的参考文档:

### references/census_schema.md
全面文档，涵盖:
- Census 数据结构与组织方式
- 所有可用的元数据字段
- 值过滤器(value filter)语法与运算符
- SOMA 对象类型
- 数据收录标准

**何时阅读**: 当你需要详细的 schema 信息、完整的元数据字段列表，或复杂的过滤器语法时。

### references/common_patterns.md
以下方面的示例与模式:
- 探索性查询(仅元数据)
- 中小规模查询(AnnData)
- 大规模查询(超出内存处理)
- PyTorch 集成
- 空间 Census 访问模式
- Scanpy 集成工作流程
- 多数据集整合
- 最佳实践与常见陷阱

**何时阅读**: 在实现特定的查询模式、寻找代码示例，或排查常见问题时。

## 常见用例

### 用例 1:探索某个组织中的细胞类型
```python
with cellxgene_census.open_soma() as census:
    cells = cellxgene_census.get_obs(
        census, "homo_sapiens",
        value_filter="tissue_general == 'lung' and is_primary_data == True",
        column_names=["cell_type"]
    )
    print(cells["cell_type"].value_counts())
```

### 用例 2:查询标记基因表达
```python
with cellxgene_census.open_soma() as census:
    adata = cellxgene_census.get_anndata(
        census=census,
        organism="Homo sapiens",
        var_value_filter="feature_name in ['CD4', 'CD8A', 'CD19']",
        obs_value_filter="cell_type in ['T cell', 'B cell'] and is_primary_data == True",
    )
```

### 用例 3:训练细胞类型分类器
```python
import tiledbsoma as soma
from tiledbsoma_ml import ExperimentDataset, experiment_dataloader

with cellxgene_census.open_soma() as census:
    experiment = census["census_data"]["homo_sapiens"]
    with experiment.axis_query(
        measurement_name="RNA",
        obs_query=soma.AxisQuery(value_filter="is_primary_data == True"),
    ) as query:
        dataset = ExperimentDataset(
            query=query,
            layer_name="raw",
            obs_column_names=["cell_type"],
            batch_size=128,
            shuffle=True,
        )
        dataloader = experiment_dataloader(dataset)

        for X, obs in dataloader:
            labels = obs["cell_type"]
            # Training logic
            pass
```

### 用例 4:跨组织分析
```python
with cellxgene_census.open_soma() as census:
    adata = cellxgene_census.get_anndata(
        census=census,
        organism="Homo sapiens",
        obs_value_filter="cell_type == 'macrophage' and tissue_general in ['lung', 'liver', 'brain'] and is_primary_data == True",
    )

    # Analyze macrophage differences across tissues
    sc.tl.rank_genes_groups(adata, groupby="tissue_general")
```

## 问题排查

### 查询返回过多细胞
- 添加更具体的过滤条件以缩小范围
- 使用 `tissue` 而非 `tissue_general` 以获得更细的粒度
- 若已知具体的 `dataset_id`,按其过滤
- 对大型查询切换到超出内存处理

### 内存错误
- 用更严格的过滤条件缩小查询范围
- 用 `var_value_filter` 选择更少的基因
- 使用 `axis_query()` 进行超出内存处理
- 分批处理数据

### 结果中出现重复细胞
- 始终在过滤条件中包含 `is_primary_data == True`
- 检查是否是有意跨多个数据集进行查询

### 找不到基因
- 核实基因名称拼写(区分大小写)
- 尝试改用 `feature_id` 对应的 Ensembl ID,而非 `feature_name`
- 查看数据集覆盖矩阵(presence matrix),确认该基因是否被测量过
- 某些基因可能在 Census 构建过程中被过滤掉了

### 版本不一致
- 始终显式指定 `census_version`
- 在所有分析中使用同一版本
- 查看发布说明以了解特定版本的变更
