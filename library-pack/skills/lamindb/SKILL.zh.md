# LaminDB

## 概述

LaminDB 是一个开源的、以血缘为核心(lineage-native)的生物学湖仓(lakehouse)系统。它让数据集和模型变得可查询、可追溯、可验证、可复现，并符合 FAIR 原则(可发现 Findable、可访问 Accessible、可互操作 Interoperable、可复用 Reusable),同时以开放格式将数据存储在本地文件系统、S3、GCS、Hugging Face、SQLite 和 Postgres 之中。

**核心价值主张**:
- **可查询性(Queryability)**:对工件(artifacts)、记录、运行(runs)、特征(features)、模式(schemas)和集合(collections)进行搜索和过滤
- **可追溯性(Traceability)**:跟踪笔记本、脚本、函数和流水线的输入、输出、参数、源代码和运行环境
- **验证(Validation)**:使用模式(schema)对 DataFrame、AnnData、SpatialData、TileDB-SOMA、Parquet、Zarr 等生物学数据格式进行整理(curate)
- **符合 FAIR 标准**:借助 Bionty 支持的本体(ontology)以及自定义注册表来标准化标注
- **变更管理**:通过项目(project)、分支(branch)、空间(space)、集合(collection)以及保存的笔记或计划来组织工作

## 何时使用本技能

在以下情形下使用本技能:

- **管理生物学数据集**:单细胞 RNA 测序(scRNA-seq)、批量 RNA 测序(bulk RNA-seq)、空间转录组学、流式细胞术、多模态数据、电子健康档案(EHR)数据
- **跟踪计算工作流**:笔记本、脚本、函数、shell 脚本，以及流水线执行(Nextflow、Snakemake、Redun)
- **整理与验证数据**:模式验证、标准化、基于本体的标注
- **处理生物学本体**:基因、蛋白质、细胞类型、组织、疾病、通路(通过 Bionty)
- **构建数据湖仓**:跨多个数据集的统一查询接口
- **保证可复现性**:自动版本管理、血缘追踪、运行环境捕获
- **集成机器学习流水线**:与 Weights & Biases、MLflow、Hugging Face、Lightning、scVI-tools 对接
- **部署数据基础设施**:搭建本地或云端的数据管理系统
- **协作处理数据集**:共享经过整理、标注、元数据标准化的数据

## 核心能力

LaminDB 提供六个相互关联的能力领域，每个领域都在 references 文件夹中有详细文档。

### 1. 核心概念与数据血缘

**核心实体**:
- **工件(Artifacts)**:带版本的数据集(DataFrame、AnnData、Parquet、Zarr 等)
- **记录与 ULabel(Records & ULabels)**:实验实体、带类型的记录，以及简单标签
- **集合(Collections)**:带版本、不可变的工件集
- **运行与转换(Runs & Transforms)**:计算血缘追踪(哪段代码产生了哪些数据)
- **特征(Features)**:用于标注和查询的带类型元数据字段
- **项目、分支与空间(Projects, Branches & Spaces)**:项目分组、变更管理与访问边界

**关键工作流**:
- 从文件或 Python 对象创建并对工件做版本管理
- 用 `ln.track()` 和 `ln.finish()` 跟踪笔记本/脚本的执行
- 用 `@ln.flow()` 和 `@ln.step()` 跟踪函数工作流
- 用记录、ulabel、项目和带类型特征来标注工件
- 用 `artifact.view_lineage()` 可视化数据血缘图
- 按来源(provenance)查询(找出由特定代码/输入产生的所有输出)

**参考文档**: `references/core-concepts.md` —— 关于工件、记录、运行、转换、特征、版本管理及血缘追踪的详细信息，请阅读此文档。

### 2. 数据管理与查询

**查询能力**:
- 带自动补全的注册表浏览与查找
- 用 `get()`、`one()`、`one_or_none()` 检索单条记录
- 用比较运算符做过滤(`__gt`、`__lte`、`__contains`、`__startswith`)
- 基于特征的查询，包括使用 `Feature` 对象的表达式风格查询
- 用双下划线语法做跨注册表遍历
- 跨注册表的全文搜索
- 用 `ln.Q` 对象做高级逻辑查询(AND、OR、NOT)
- 无需加载进内存即可流式处理大型数据集

**关键工作流**:
- 用过滤条件和排序浏览工件
- 按特征、创建日期、创建者、大小等查询
- 分块或用数组切片方式流式读取大文件
- 用层级化的键(key)组织数据
- 把工件分组进集合

**参考文档**: `references/data-management.md` —— 关于全面的查询模式、过滤示例、流式处理策略及数据组织最佳实践，请阅读此文档。

### 3. 标注与验证

**整理(Curation)流程**:
1. **验证(Validation)**:确认数据集符合期望的模式
2. **标准化(Standardization)**:修正拼写错误，把同义词映射到规范术语
3. **标注(Annotation)**:将数据集与元数据实体关联以便可查询

**模式类型**:
- **灵活模式(Flexible schemas)**:只验证已知的列，允许附加元数据
- **最小必需模式(Minimal required schemas)**:指定必需的列，允许额外内容
- **严格模式(Strict schemas)**:对结构和取值进行完全控制

**支持的数据类型**:
- DataFrame(Parquet、CSV)
- AnnData(单细胞基因组学)
- MuData(多模态)
- SpatialData(空间转录组学)
- TileDB-SOMA(可扩展数组)

**关键工作流**:
- 为数据验证定义特征和模式
- 使用 `DataFrameCurator`、`AnnDataCurator`、`SpatialDataCurator` 或 `TiledbsomaExperimentCurator` 做验证
- 用 `.cat.standardize()` 标准化取值
- 用 `.cat.add_ontology()` 映射到本体
- 保存带模式关联的整理后工件
- 按特征查询已验证的数据集

**参考文档**: `references/annotation-validation.md` —— 关于详细的整理工作流、模式设计模式、验证错误处理及最佳实践，请阅读此文档。

### 4. 生物学本体

**可用本体(通过 Bionty)**:
- 基因(Ensembl)、蛋白质(UniProt)
- 细胞类型(CL)、细胞系(CLO)
- 组织(Uberon)、疾病(Mondo、DOID)
- 表型(HPO)、通路(GO)
- 实验因子(EFO)、发育阶段
- 物种(NCBItaxon)、药物(DrugBank)

**关键工作流**:
- 用 `bt.CellType.import_source()` 导入公共本体
- 用关键词或精确匹配搜索本体
- 用同义词映射标准化术语
- 探索层级关系(父级、子级、祖先)
- 对照本体术语验证数据
- 用本体记录标注数据集
- 创建自定义术语和层级结构
- 处理多物种场景(人类、小鼠等)

**参考文档**: `references/ontologies.md` —— 关于全面的本体操作、标准化策略、层级导航及标注工作流，请阅读此文档。

### 5. 集成

**工作流管理器**:
- Nextflow:跟踪流水线的处理步骤和输出
- Snakemake:集成进 Snakemake 规则
- Redun:与 Redun 任务跟踪结合
- Lightning:持久化检查点和训练元数据

**MLOps 平台**:
- Weights & Biases:将实验与数据工件关联
- MLflow:跟踪模型和实验
- Hugging Face:跟踪模型微调
- scVI-tools:单细胞分析工作流

**存储系统**:
- 本地文件系统、AWS S3、Google Cloud Storage
- 兼容 S3 的存储(MinIO、Cloudflare R2)
- HTTP/HTTPS 端点(只读)
- HuggingFace 数据集

**数组存储**:
- TileDB-SOMA(支持 cellxgene)
- 用于对 Parquet 文件做 SQL 查询的 DuckDB

**可视化**:
- 用于交互式空间/单细胞可视化的 Vitessce

**版本控制**:
- 用于源代码跟踪的 Git 集成

**参考文档**: `references/integrations.md` —— 关于与第三方系统的集成模式、代码示例及故障排查，请阅读此文档。

### 6. 环境搭建与部署

**安装**:
- 当前稳定基线版本:`lamindb==2.5.1`(发布于 2026-06-01;Python >=3.10, <=3.14)
- 基础安装:`uv pip install 'lamindb==2.5.1'`
- 带附加组件:`uv pip install 'lamindb[gcp,zarr-v2,fcs]==2.5.1'`
- 仅最小命名空间:`uv pip install 'lamindb-core==2.5.1'`
- Bionty 模块:已包含在 LaminDB 文档中，也可通过 `uv pip install 'bionty==2.4.0'` 获取
- 可选模块:对于 wetlab 或临床模式模块，固定使用经过审查的发布版本，而不要安装浮动的最新版

**实例类型**:
- 本地 SQLite(开发环境)
- 云存储 + SQLite(小团队)
- 云存储 + PostgreSQL(生产环境)

**存储选项**:
- 本地文件系统
- 支持配置区域和权限的 AWS S3
- Google Cloud Storage
- 兼容 S3 的端点(MinIO、Cloudflare R2)

**配置**:
- 云端文件的缓存管理
- 多用户系统配置
- Git 仓库同步
- 用于凭据和连接 URL 的命名环境变量

**部署模式**:
- 本地开发到云端生产环境的迁移
- 多区域部署
- 共享存储配合个人实例

**参考文档**: `references/setup-deployment.md` —— 关于详细的安装、配置、存储搭建、数据库管理、安全最佳实践及故障排查，请阅读此文档。

## 安全与安全默认设置

在协助 LaminDB 的搭建或集成工作时:

- 永远不要显示、记录或传输真实的 API 密钥、云凭据、数据库密码，或包含机密内容的完整连接字符串。
- 优先使用 IAM 角色、工作负载身份(workload identity)、密钥管理器，或诸如 `LAMIN_DB_URL`、`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`GOOGLE_APPLICATION_CREDENTIALS` 这样的命名环境变量；只检查某个命名变量是否存在，而不检查其取值。
- 在保存来自 REST API、外部数据库或用户提供文件的内容之前，用明确的模式(schema)或整理器(curator)对其进行验证和清洗。
- 为了保证安装的可复现性，固定软件包版本或使用锁文件(lock file)。只有当用户明确希望使用最新的上游发行版时，才可以使用浮动版本安装。

## 常见用例工作流

### 用例 1:带本体验证的单细胞 RNA 测序分析

```python
import lamindb as ln
import bionty as bt
import anndata as ad

# Start tracking a notebook/script run
ln.track(params={"analysis": "scRNA-seq QC and annotation"})

# Import cell type ontology
bt.CellType.import_source()

# Load data
adata = ad.read_h5ad("raw_counts.h5ad")

# Validate and standardize cell types
adata.obs["cell_type"] = bt.CellType.standardize(adata.obs["cell_type"])

# Curate with schema
curator = ln.curators.AnnDataCurator(adata, schema)
curator.validate()
artifact = curator.save_artifact(key="scrna/validated.h5ad")

# Link ontology-backed annotations for queryability
cell_types = bt.CellType.from_values(adata.obs["cell_type"])
artifact.cell_types.add(*cell_types)

ln.finish()
```

### 用例 2:构建可查询的数据湖仓

```python
import lamindb as ln

# Register multiple experiments
for i, file in enumerate(data_files):
    artifact = ln.Artifact.from_anndata(
        ad.read_h5ad(file),
        key=f"scrna/batch_{i}.h5ad",
        description=f"scRNA-seq batch {i}"
    ).save()

    # Annotate with features
    artifact.features.set_values({
        "batch": i,
        "tissue": tissues[i],
        "condition": conditions[i]
    })

# Query across all experiments by annotated features
immune_datasets = ln.Artifact.filter(
    key__startswith="scrna/",
    tissue="PBMC",
    condition="treated"
).to_dataframe()

# Load specific datasets
for artifact in immune_datasets:
    adata = artifact.load()
    # Analyze
```

### 用例 3:带 W&B 集成的机器学习流水线

```python
import lamindb as ln
import wandb

# Initialize both systems
wandb.init(project="drug-response", name="exp-42")
ln.track(params={"model": "random_forest", "n_estimators": 100})

# Load training data from LaminDB
train_artifact = ln.Artifact.get(key="datasets/train.parquet")
train_data = train_artifact.load()

# Train model
model = train_model(train_data)

# Log to W&B
wandb.log({"accuracy": 0.95})

# Save model in LaminDB with W&B linkage
import joblib
joblib.dump(model, "model.pkl")
model_artifact = ln.Artifact("model.pkl", key="models/exp-42.pkl").save()
model_artifact.features.set_values({"wandb_run_id": wandb.run.id})

ln.finish()
wandb.finish()
```

### 用例 4:Nextflow 流水线集成

```python
# In Nextflow process script
import lamindb as ln

ln.track()

# Load input artifact
input_artifact = ln.Artifact.get(key="raw/batch_${batch_id}.fastq.gz")
input_path = input_artifact.cache()

# Process (alignment, quantification, etc.)
# ... Nextflow process logic ...

# Save output
output_artifact = ln.Artifact(
    "counts.csv",
    key="processed/batch_${batch_id}_counts.csv"
).save()

ln.finish()
```

对于原生 Nextflow 项目，在可用的情况下优先使用 `nf-lamin` 插件和当前的 `nextflow.config` 模式；对于小型或自定义的流水线步骤，可使用内联的 Python 跟踪方式。

## 入门检查清单

要有效地开始使用 LaminDB:

1. **安装与搭建**(`references/setup-deployment.md`)
   - 安装固定版本的 LaminDB 及所需的附加组件
   - 用 `lamin login` 进行身份验证
   - 用 `lamin init --storage ...` 初始化实例

2. **学习核心概念**(`references/core-concepts.md`)
   - 理解工件(Artifacts)、记录(Records)、运行(Runs)、转换(Transforms)
   - 练习创建和检索工件
   - 在工作流中实现 `ln.track()`/`ln.finish()` 或 `@ln.flow()`/`@ln.step()`

3. **掌握查询**(`references/data-management.md`)
   - 练习过滤和搜索注册表
   - 学习基于特征的查询与表达式风格的过滤
   - 尝试流式处理大文件

4. **建立验证机制**(`references/annotation-validation.md`)
   - 定义与研究领域相关的特征
   - 为数据类型创建模式
   - 练习整理工作流

5. **集成本体**(`references/ontologies.md`)
   - 导入相关的生物学本体(基因、细胞类型等)
   - 验证已有的标注
   - 用本体术语标准化元数据

6. **连接工具**(`references/integrations.md`)
   - 与现有的工作流管理器集成
   - 关联机器学习平台以做实验跟踪
   - 配置云存储和计算资源

## 关键原则

在使用 LaminDB 时遵循以下原则:

1. **一切都要跟踪**:在每次分析开始时使用 `ln.track()`,以实现自动的血缘捕获

2. **尽早验证**:在开展大量分析之前先定义模式并验证数据

3. **使用本体**:借助公共生物学本体进行标准化标注

4. **用键组织**:分层次地构建工件的键(key)(例如 `project/experiment/batch/file.h5ad`)

5. **先查询元数据**:在加载大文件之前先做过滤和搜索

6. **做版本管理，不要重复保存**:使用内置的版本管理，而不是为修改内容创建新的键

7. **用特征做标注**:定义带类型的特征，并用 `artifact.features.set_values()` 生成可查询的元数据

8. **详尽记录文档**:为工件、模式和转换添加描述

9. **善用血缘信息**:用 `view_lineage()` 理解数据的来源

10. **从本地起步，向云端扩展**:用 SQLite 在本地开发，用 PostgreSQL 部署到云端

## 参考文件

本技能包含按能力领域组织的详尽参考文档:

- **`references/core-concepts.md`** —— 工件、记录、运行、转换、特征、版本管理、血缘
- **`references/data-management.md`** —— 查询、过滤、搜索、流式处理、数据组织
- **`references/annotation-validation.md`** —— 模式设计、整理工作流、验证策略
- **`references/ontologies.md`** —— 生物学本体管理、标准化、层级结构
- **`references/integrations.md`** —— 工作流管理器、MLOps 平台、存储系统、工具
- **`references/setup-deployment.md`** —— 安装、配置、部署、故障排查

根据手头任务所需的具体 LaminDB 能力，阅读相应的参考文件。

## 其他资源

- **官方文档**:https://docs.lamin.ai
- **API 参考**:https://docs.lamin.ai/api
- **GitHub 仓库**:https://github.com/laminlabs/lamindb
- **教程**:https://docs.lamin.ai/tutorial
- **常见问题**:https://docs.lamin.ai/faq
