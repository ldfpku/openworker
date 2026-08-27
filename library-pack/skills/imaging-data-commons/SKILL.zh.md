# Imaging Data Commons

## 概述

从美国国家癌症研究所影像数据共享库（National Cancer Institute Imaging Data Commons，IDC）查询并下载公开的癌症影像数据。访问数据无需身份验证。

**预期的网络访问**： IDC 元数据可通过三种途径获取——随 `idc-index` Python 包一同分发的本地 DuckDB 索引（无需联网）、或托管的 IDC 服务（通过 MCP 或 REST，`api.imaging.datacommons.cancer.gov`，无需身份验证）。文件下载使用公开的 GCS（`storage.googleapis.com`）和 AWS S3（`s3.amazonaws.com`）——无需身份验证。DICOMweb 访问可使用公开的 IDC 代理（`proxy.imaging.datacommons.cancer.gov`，无需验证）或 Google Cloud Healthcare API（`healthcare.googleapis.com`，需要 GCP 身份验证）。可选的 BigQuery 查询（`bigquery.googleapis.com`）同样需要 GCP 身份验证。本技能不会访问任何凭据或环境变量。

**当前 IDC 数据版本：v24**（务必核实——见*最佳实践*）

**先选定访问路径**。 没有单一的默认方案：最经济且正确的路径取决于会话环境和任务本身。

1. **当前会话已配置 IDC MCP 服务器**？ 将发现与元数据查询都交给它——见 *IDC MCP 服务器*。
2. **否则，是否已安装 `idc-index`？** 运行 `python scripts/check_version.py`。若通过，则全程使用 `idc-index`。
3. **未安装，且任务只涉及只读元数据**——计数、属性取值、集合查询、少于 10,000 行的 SQL、许可协议、引用格式、查看器 URL？**改用 REST API 配合 `curl`；不要安装任何东西。** 安装会带来约 77 MB 的打包索引数据，外加 pandas、pyarrow、duckdb，而一个元数据问题并不需要这些。参见*数据访问方式*。
4. **未安装，且任务超出元数据范畴**——需要下载文件、pandas 或绘图、pydicom/SimpleITK、病理切片分块、超过 10,000 行的结果，或需要用户反复运行的、版本锁定的脚本？安装 `idc-index`：`check_version.py` 会在版本不满足时以非零状态退出，并打印出适用于当前解释器的确切安装命令。建议使用虚拟环境，然后重启 Python。

`idc-index`（[GitHub](https://github.com/imagingdatacommons/idc-index)）仍然是能力最强的路径，也是唯一能真正搬运影像字节数据的路径；这条规则只是要求在任务确实需要之前不要为它付出代价。`check_version.py` 本身从不安装任何东西——它同时会提示是否存在更新的 `idc-index` 或技能版本。

**`idc-index` 路径的准备工作：**

```python
from idc_index import IDCClient
client = IDCClient()

# Verify IDC data version (should be "v24")
print(f"IDC data version: {client.get_idc_version()}")
```

**核心工作流**： 用 `client.sql_query()` 查询元数据 → 用 `client.download_from_selection()` 下载 → 用 `client.get_viewer_URL()` 可视化。下文的 Python 示例均基于此 `client`；*数据访问方式*一节给出了对应的 REST 用法。若需了解当前的数据规模，可运行 `references/sql_patterns.md` 中的汇总查询，或调用 `GET /v3/stats`。

## IDC MCP 服务器

IDC 在 `https://api.imaging.datacommons.cancer.gov/mcp` 运营着一个托管的 MCP 服务器（流式 HTTP，无需身份验证）。在可用的情况下，它是对下文 `idc-index` 工作流的补充——而非替代。

**识别方式**： 通过 MCP 资源 `idc://guide`，或通过工具名称 `build_cohort`、`get_cohort_urls`、`list_analysis_results`、`get_idc_version` 中至少三个的出现来判断。像 `run_sql` 这样的通用名称本身不能作为证据。若识别结果不确定，改用 `idc-index`。

**如果当前会话拥有该服务器**，将其视为发现与元数据方面的权威来源——IDC 版本、计数、属性取值、队列（cohort）构建、元数据 SQL——并遵循该服务器自身的指引，而不是从本文件重新推导。其数据版本以服务器实际报告的为准：调用 `get_idc_version`，而不要依赖本文件中固定的版本号。

**遇到该服务器不覆盖的场景时再回到本文档**： 下载文件、本地 pandas/notebook 分析、DICOMweb、BigQuery、数字病理学分块，以及可复现脚本。交接方式是把服务器给出的 SeriesInstanceUID 传给 `client.download_from_selection(...)`，并在此时运行 `scripts/check_version.py`。

**如果该服务器不可用**，同一服务可以零配置地通过 REST API 在 `https://api.imaging.datacommons.cancer.gov/v3` 访问——按*概述*中的路由准则，用它处理只读元数据，而不必安装 `idc-index`。最多建议用户连接一次 MCP 服务器，且仅在需要反复交互式发现时才建议，切勿自行更改用户的配置。

工具清单、交接模式与各宿主环境的注意事项见 `references/mcp_guide.md`。

## 何时使用本技能

- 查找公开可用的放射影像（CT、MR、PET）或病理（切片显微）影像
- 按癌症类型、影像模态、解剖部位或其他元数据筛选影像子集
- 从 IDC 下载 DICOM 数据
- 在研究或商业应用中使用数据前检查数据许可
- 无需本地 DICOM 查看软件即可在浏览器中可视化医学影像

## 快速导航

正文内已涵盖：MCP/REST 路由规则、IDC 数据模型、索引表及其连接方式、核心 API 模式（查询、下载、可视化、许可、引用）、最佳实践与故障排查。

**参考指南（按需加载）**：

| 指南 | 何时加载 |
|-------|--------------|
| `index_tables_guide.md` | 复杂 JOIN、模式（schema）发现、DataFrame 访问 |
| `use_cases.md` | 端到端工作流：训练数据集、批量下载、用 pydicom/SimpleITK 读取 DICOM、流水线集成 |
| `sql_patterns.md` | 用于筛选值发现、标注与分割查询、大小估算的常用 SQL 模式 |
| `clinical_data_guide.md` | 临床/表格数据、影像与临床数据的联接、取值映射 |
| `licensing_and_citation.md` | 商用相关问题、混合许可队列、引用格式 |
| `cloud_storage_guide.md` | 直接访问 S3/GCS、版本管理、UUID 映射 |
| `dicomweb_guide.md` | DICOMweb 端点、PACS 集成 |
| `digital_pathology_guide.md` | 切片显微（SM）、标注（ANN）、病理学工作流 |
| `bigquery_guide.md` | 完整 DICOM 元数据、私有元素（需要 GCP） |
| `cli_guide.md` | 命令行工具（`idc download`、清单文件） |
| `parquet_access_guide.md` | 通过 GCS 直接查询 Parquet（无需安装 idc-index） |
| `mcp_guide.md` | 托管的 IDC MCP 服务器：工具清单、识别方式、向 `idc-index` 的交接 |
| `rest_api_guide.md` | 托管的 IDC REST API：端点、过滤语法、通过 HTTP 执行 SQL、清单文件 |

## IDC 数据模型

在标准 DICOM 层级（Patient → Study → Series → Instance）之上，IDC 增加了两个分组层级：

- **collection_id**：按疾病、影像模态或研究方向对患者进行分组（如 `tcga_luad`、`nlst`）。每位患者恰好属于一个 collection。
- **analysis_result_id**：标识跨一个或多个原始 collection 的衍生对象（分割结果、标注、放射组学特征）。用它来查找 AI 生成或专家标注的数据，而 `collection_id` 用于查找原始影像数据（其本身也可能包含已存入的标注）。

**查询用的关键标识符**：
| 标识符 | 作用范围 | 用途 |
|------------|-------|---------|
| `collection_id` | 数据集分组 | 按项目/研究进行筛选 |
| `PatientID` | 患者 | 按患者对影像分组 |
| `StudyInstanceUID` | DICOM Study | 相关序列的分组、可视化 |
| `SeriesInstanceUID` | DICOM Series | 相关序列的分组、可视化 |

## 索引表

`idc-index` 包提供多张元数据索引表，可通过 SQL 或以 pandas DataFrame 的形式访问。REST API 通过 `GET /tables` 和 `POST /sql` 暴露同一批表。

**重要提示**： `client.indices_overview` 是当前表描述、可用列及其类型的权威来源——在编写 SQL 或探索数据结构时应查询它。它同样能回答"哪张表包含列 X"这类问题；相关检索方式与完整的模式发现流程见 `references/index_tables_guide.md`。

### 可用的表

在查询任何索引表之前，务必先调用 `client.fetch_index("table_name")`——对所有表（包括启动时已自动加载的表）而言，这个调用都是安全且幂等的。

| 系列 | 表 | 粒度 |
|--------|--------|-------------|
| 核心 | `index`（所有当前数据的主元数据表）、`collections_index`、`analysis_results_index` | 序列（series）/ collection / analysis result |
| 模态采集参数 | `ct_index`、`mr_index`、`pt_index`、`contrast_index` | 1 行 = 该模态的 1 个 series |
| 衍生对象 | `seg_index`、`rtstruct_index`、`ann_index`、`ann_group_index` | 1 行 = 1 个 series（或一组标注） |
| 显微镜检查 | `sm_index`、`sm_instance_index` | 1 行 = 1 个 SM series / instance |
| 几何、临床、历史 | `volume_geometry_index`、`clinical_index`、`version_metadata_index`、`prior_versions_index` | 见相应指南 |

`references/index_tables_guide.md` 中有完整清单，列出每张表所含的列及其内容——当你需要了解某张专用表究竟保存了什么时可加载它。

**`prior_versions_index` 仅用于可复现性。** 它包含从 IDC 中被永久*移除*的 series，与 `index` 完全没有重叠。仅在需要复现针对某个旧 IDC 版本所做的工作时才使用它。**不要**用它来回答版本历史或"有什么新内容"之类的问题——这类问题应使用主 `index` 表中的 `series_init_idc_version` / `series_revised_idc_version`，它们与本表的 `min_idc_version` / `max_idc_version` 并不等价。

### 连接（Joining）各表

**`SeriesInstanceUID` 是所有 series 级专用表的通用连接键：** `sm_index`、`sm_instance_index`、`seg_index`、`ann_index`、`ann_group_index`、`contrast_index`、`volume_geometry_index`、`rtstruct_index`、`ct_index`、`mr_index`、`pt_index`。这些表始终应通过 `SeriesInstanceUID` 与 `index` 连接。下表列出的例外情况使用不同的列名。

| 连接列 | 涉及的表 | 用途 |
|-------------|-------|---------|
| `collection_id` | index、prior_versions_index、collections_index、clinical_index | 将 series 关联到 collection 元数据或临床数据 |
| `analysis_result_id` | index、analysis_results_index | 将 series 关联到 analysis result 元数据（标注、分割结果） |
| `source_DOI` | index、analysis_results_index | 按论文 DOI 关联 |
| `segmented_SeriesInstanceUID` | seg_index → index | 将分割结果关联到其来源影像 series（`seg_index.segmented_SeriesInstanceUID = index.SeriesInstanceUID`） |
| `referenced_SeriesInstanceUID` | ann_index → index、rtstruct_index → index | 将标注或 RTSTRUCT 关联到其来源影像 series |

**注意**： `subjects`、`updated`、`description` 这几个字段在多张表中都出现，但含义不同（计数值 vs 标识符、不同的更新语境）。将 `prior_versions_index` 按 `SeriesInstanceUID` 与 `index` 连接永远会返回零行——见上文的警告。

详细的连接示例、模式发现方法、关键列参考及 DataFrame 访问方式，见 `references/index_tables_guide.md`。

### 临床数据访问

临床（非影像）属性——分期、人口统计学信息、治疗方案——保存在按 collection 分别建立的表中。`client.fetch_index("clinical_index")` 会加载一份"列 → collection"的映射字典；`client.get_clinical_table(name)` 则以 DataFrame 形式返回某一张表。

发现流程、编码值映射，以及如何将临床数据与影像数据联接，见 `references/clinical_data_guide.md`。

## 数据访问方式

| 方法 | 身份验证 | 最适用于 | 参考 |
|--------|------|----------|-----------|
| `idc-index` | 否 | 下载、pandas 分析、无行数限制的查询——能力最全面的路径 | 本文档 |
| IDC MCP 服务器 | 否 | 发现、队列构建、当前会话已配置该服务器时的元数据查询 | `mcp_guide.md` |
| IDC REST API | 否 | 无需安装即可从任意语言或 shell 获取元数据——`idc-index` 缺失时的默认方案 | `rest_api_guide.md` |
| 直接读取 Parquet（GCS） | 否 | 需要锁定版本的查询，或结果超出 REST 行数上限的情况 | `parquet_access_guide.md` |
| 云存储（S3/GCS） | 否 | 直接文件访问、批量传输、自定义流水线 | `cloud_storage_guide.md` |
| 经由 IDC 代理的 DICOMweb | 否 | 工具与 PACS 集成；有每日配额，适合测试和中等强度使用 | `dicomweb_guide.md` |
| 经由 Google Healthcare 的 DICOMweb | 是（GCP） | 同样的 DICOMweb API，可用于生产级流量，不受代理配额限制 | `dicomweb_guide.md` |
| SlicerIDCBrowser | 否 | 在 3D Slicer 中进行三维可视化与分析 | https://github.com/ImagingDataCommons/SlicerIDCBrowser |
| BigQuery | 是（GCP） | 完整 DICOM 元数据、私有元素、SR 测量值——最后选用的手段 | `bigquery_guide.md` |

**IDC 门户（<https://portal.imaging.datacommons.cancer.gov/>）仅供交互使用**——基于浏览器的浏览、手动队列选择与下载。与上表中所有其他选项不同，它没有可编程接口，因此只应引导用户到该门户自行浏览或点选数据；切勿将其作为脚本或工作流中的一个步骤。

**REST API——无需安装的元数据路径**

`https://api.imaging.datacommons.cancer.gov/v3`，无需身份验证：可用于发现、队列计数与清单、只读 SQL、临床数据表、查看器 URL、许可协议、引用格式。它与 MCP 服务器是同一个服务，只是走的是普通 HTTP，因此无需任何配置。它从不搬运影像字节数据——如需下载、获取 DataFrame，或结果超过 10,000 行，请改用 `idc-index`。

```bash
B=https://api.imaging.datacommons.cancer.gov/v3
curl -s $B/version   # idc_version, idc_index_data_version, api_version
curl -s $B/stats     # collections, patients, studies, series, instances, size_TB
curl -s "$B/attributes/Modality/values?limit=5"   # real filter values, with counts
curl -s $B/sql -H 'content-type: application/json' \
  -d '{"sql":"SELECT collection_id, COUNT(*) n FROM index GROUP BY 1 ORDER BY n DESC LIMIT 3"}'
curl -s $B/cohort/counts -H 'content-type: application/json' \
  -d '{"filters":{"terms":{"collection_id":["rider_pilot"]}}}'
```

**过滤对象始终放在 `filters` 之下**——无论是 `cohort/counts`、`cohort/manifest`、`cohort/manifest.txt`，还是 `licenses`、`citations`，皆是如此。裸露的过滤条件或无法识别的键会返回 422 并指明修正方式；未加过滤条件、会枚举全部 series 的请求会返回 400，而不是把整个存档都吐出来。每个经过过滤的响应都会回显 `filters_applied` 和 `warnings`——务必阅读这两项，因为它们会指出服务器丢弃了哪些谓词。若计数为零且 `warnings` 为空，说明过滤条件确实没有匹配到任何内容，而不是某个值大小写有误；大小写错误会产生相应说明的 warning。

`POST /sql` 接受一条只读的 `SELECT`/`WITH` 语句，作用于 `idc-index` 暴露的各表以及 `clinical.<table>`；`max_rows` 默认 5,000，上限为 10,000，`truncated` 标志会指出结果是否被截断。`GET /attributes` 列出 19 个可过滤属性——临床取值、被分割的解剖结构、以及采集参数不在其中，需要用 SQL 查询。没有速率限制或配额限制。**仅使用 v3**： V1 和 V2 已被取代，即将停用，因此如果用户带来了 `/v1/` 或 `Modality_btw` 风格的示例，请将其迁移到 v3，而不要在旧版本上继续扩展。

两侧都构建在 `idc-index-data` 之上，因此混用前应比较 API 的 `idc_index_data_version` 与本地的 `idc_index_data.__version__`：**主版本号对应 IDC 数据发行版**（`24.x.y` 对应 `v24`），因此次版本号/修订号不同时序列数据是一致的。如果 API 领先本地整整一个发行版，`idc-index` **将无法下载多出来的那些 series**——它会悄悄跳过自身索引未列出的数据——因此要么升级它（运行 `scripts/check_version.py` 获取正确的升级命令），要么用 `s5cmd --no-sign-request` 直接从存储桶传输。

端点参考、过滤条件的取值依据、限制条件以及基于清单文件的下载流程，见 `references/rest_api_guide.md`。

**云存储组织方式**

所有 DICOM 文件都保存在 AWS S3 与 GCS 之间镜像的公共存储桶中，按 CRDC UUID（而非 DICOM UID）组织，路径形如 `<crdc_series_uuid>/<crdc_instance_uuid>.dcm`。通过 AWS CLI、gsutil 或 s5cmd 以匿名方式访问是免费的（无出站流量费用）；使用 `series_aws_url` 列获取 S3 URL。注意 `idc-open-data-cr` / `idc-open-cr`（约占数据的 4%）受商业使用限制（CC BY-NC）。完整的存储桶清单与 UUID 映射见 `references/cloud_storage_guide.md`。

**DICOMweb 访问**

IDC 数据可通过 DICOMweb（Google Cloud Healthcare API）访问，用于 PACS 集成及兼容 DICOMweb 的各类工具：可使用公共代理（无需身份验证，有每日配额）用于测试和中等强度的查询，或使用 Google Healthcare（需要 GCP 身份验证）用于生产级流量。见 `references/dicomweb_guide.md`。

**直接访问 Parquet**

idc-index 的元数据表同时以 Parquet 格式发布在一个公共 GCS 存储桶（`idc-index-data-artifacts`）中，可用 DuckDB 或 pandas 查询。这种方式需要安装 DuckDB，且无法访问按 collection 分别建立的临床数据表，因此临时性的元数据查询建议优先使用 REST 的 `/sql`；若需要锁定某个数据版本，或结果超出 REST 的行数上限，则选用 Parquet。见 `references/parquet_access_guide.md`。

## 核心能力

以下这些模式，一旦凭记忆而非核实来使用，就最容易出错。每个方面的完整示例见正文中提到的各参考指南。

### 1. 发现——在筛选前先枚举取值

用猜测出来的 `Modality` 或 `BodyPartExamined` 字符串做过滤，是导致结果集为空的最常见原因。应先枚举：

```python
modalities = client.sql_query("""
    SELECT DISTINCT Modality, COUNT(*) as series_count
    FROM index
    GROUP BY Modality
    ORDER BY series_count DESC
""")
print(modalities)
```

同样的模式适用于任何过滤列，也可以再叠加另一个过滤条件进行细化——比如在某个 `Modality` 下限定 `BodyPartExamined`、`Manufacturer`、`collection_id`。在 REST 路径上，这一取值依据只需一次调用即可获得——`GET /attributes/{attr}/values` 会返回带计数的取值——而队列相关端点会在 `warnings` 中指出大小写错误的取值，而不是简单地返回空结果。

有两张索引表携带了 `index` 表本身不具备的、经过整理的 collection 级元数据，二者都需要先调用 `client.fetch_index(...)`：`collections_index`（癌症类型、肿瘤部位、物种、受试者数量）以及 `analysis_results_index`（衍生数据集——AI 分割结果、专家标注、放射组学特征——及其来源 collection 与模态）。

**癌症类型保存在 `collections_index.cancer_types` 中，而不在 `index` 中**——按癌症类型过滤需要进行连接：

```python
client.fetch_index("collections_index")
results = client.sql_query("""
    SELECT i.collection_id, i.PatientID, i.SeriesInstanceUID, i.Modality
    FROM index i
    JOIN collections_index c ON i.collection_id = c.collection_id
    WHERE c.cancer_types LIKE '%Breast%'
      AND i.Modality = 'MR'
    LIMIT 20
""")
```

`client.sql_query()` 返回一个 pandas DataFrame。在编写查询之前，用 `client.get_index_schema('index')` 或 `client.indices_overview` 核实列名，而不要凭假设行事。

过滤值发现、标注与分割查询、大小估算、临床数据关联，以及版本追踪（"vX 版本中新增了什么"——使用 `index` 表中的 `series_init_idc_version` / `series_revised_idc_version`，绝不要用 `prior_versions_index`），见 `references/sql_patterns.md`。

### 2. 下载 DICOM 文件

**两个下载方法的前两个参数顺序是相反的**。 这是 IDC 代码出错最常见的原因——应当去核实而不是凭记忆：

| 方法 | 第一个参数 | 第二个参数 | 适用场景 |
|--------|-----------|------------|----------|
| `download_from_selection` | `downloadDir`（必填） | 过滤关键字参数（可选） | 按 collection、患者、study 或 series 过滤 |
| `download_dicom_series` | `seriesInstanceUID`（必填） | `downloadDir`（必填） | 仅按 UID 下载指定 series |

**`download_from_selection` 接受的是过滤用的关键字参数，而不是 DataFrame。** "from_selection" 这个名字指的是按条件过滤 IDC 索引——而不是接受一个 pandas DataFrame。要下载查询结果，需先把 UID 提取成一个列表：

```python
# Step 1: Query for series UIDs
series_df = client.sql_query("""
    SELECT SeriesInstanceUID
    FROM index
    WHERE Modality = 'CT'
      AND BodyPartExamined = 'CHEST'
      AND collection_id = 'nlst'
    LIMIT 5
""")

# Step 2: Extract UIDs as a list from the DataFrame
uids = list(series_df['SeriesInstanceUID'].values)

# Step 3: Pass the list to download_from_selection (NOT the DataFrame itself)
client.download_from_selection(
    downloadDir="./data/lung_ct",
    seriesInstanceUID=uids       # list of strings, not a DataFrame
)

# Alternative: download_dicom_series has seriesInstanceUID as FIRST arg (different order!)
client.download_dicom_series(
    seriesInstanceUID=uids,      # FIRST arg here
    downloadDir="./data/lung_ct"
)

# Whole collection: downloadDir is still the FIRST positional argument
client.download_from_selection(downloadDir="./data/rider", collection_id="rider_pilot")
```

两个方法都默认从 AWS 拉取；传入 `source_bucket_location="gcs"` 即可改为从 Google Storage 拉取。

**下载下来的文件名为 `<crdc_instance_uuid>.dcm`，而不是按 SOPInstanceUID 命名。** DICOM UID 保存在文件元数据内部，而不体现在文件名中。使用 `crdc_instance_uuid` 列，可以将文件映射回它们所属的 series。

`idc download <collection|series-uid|manifest> --download-dir ./data` 可以在 shell 中完成同样的操作。`dirTemplate` 的目录层级选项（Python 默认值：`%collection_id/%PatientID/%StudyInstanceUID/%Modality_%SeriesInstanceUID`；`dirTemplate=""` 表示不分层、全部平铺）、支持断点续传的清单下载，以及试运行式的大小估算，见 `references/cli_guide.md`。

### 3. 可视化 IDC 影像

```python
viewer_url = client.get_viewer_URL(seriesInstanceUID=uid)        # one series
viewer_url = client.get_viewer_URL(studyInstanceUID=study_uid)   # all series in a study
```

返回一个浏览器 URL——不会下载任何内容。该方法会自动为放射影像选用 OHIF v3，为切片显微影像选用 SLIM。当单个 DICOM Study 内含多个 Series 时（例如一次 MRI 检查中的 T1、T2 和 DWI），按 study 查看会很有用。

### 4. 许可与引用——义务事项，而非可选步骤

IDC 数据附带许可条款与署名要求，这些要求会随数据一路延伸到任何下游出版物或产品，且无法从像素数据本身推断出来。**使用前先检查许可，并为你下载的一切内容生成引用**。

```python
# License breakdown for a selection
licenses = client.sql_query("""
    SELECT DISTINCT collection_id, license_short_name,
           COUNT(DISTINCT SeriesInstanceUID) as series_count
    FROM index GROUP BY collection_id, license_short_name
""")

# Citations for the same selection you downloaded (APA by default)
for citation in client.citations_from_selection(collection_id="rider_pilot"):
    print(citation)
```

IDC 数据中约 97% 为 CC BY（允许商业使用，但须署名），约 3% 为 CC BY-NC（仅限非商业用途）。**许可是附着在 series 上的，而不是附着在 collection 上**——176 个 collection 中有 39 个包含不止一种许可——因此应检查你实际打算使用的那个选择集，并注意在混合队列中，约束最严格的条款将适用于整体。

以上两项任务在全部三种访问路径中都可用，因此保持使用当前会话已在用的那种即可：如上所述的 `idc-index`；REST 方式的 `POST /v3/licenses` 与 `POST /v3/citations`；或 MCP 工具 `get_licenses` 与 `get_citations`。完整的许可清单、三条路径的具体用法、引用格式（APA、BibTeX、CSL JSON、RDF Turtle），以及发表时应包含的内容，见 `references/licensing_and_citation.md`。

### 5. 超出索引范围时

按*概述*中的路由准则选择访问路径；上文的*数据访问方式*即完整的路由表。

在动用 BigQuery（需要已开通计费的 GCP 账号）之前，先检查某张专用索引表中是否已经有你需要的那一列：先在 `client.indices_overview` 中搜索，再用 `client.fetch_index(...)` 拉取到本地免费查询。只有在需要私有 DICOM 元素、逐分割解剖结构（`segmentations`），以及预先提取的 SR 测量值（`quantitative_measurements`、`qualitative_measurements`）时才必须使用 BigQuery——这些内容在 idc-index 中没有对应项。

## 最佳实践

- **写查询之前先检查模式（schema）**——使用 `client.get_index_schema('index')`（读取缓存的元数据，不执行任何 SQL）或 `client.indices_overview` 查看所有可用列及其说明。主 `index` 表中用于版本追踪的列 `series_init_idc_version` 和 `series_revised_idc_version`，可以直接回答"有什么新内容/这是何时加入的"这类问题，而无需接触 `prior_versions_index`。
- **绝不要用网页搜索来回答关于 IDC 数据内容的问题**——始终直接查询 IDC 索引，本地用 `client.sql_query()`，或通过 HTTP 用 `POST /v3/sql`。网络来源（发行说明、博客文章、文档页面）常常已经过时，会给出错误答案。索引才是权威来源；即便网页搜索可用，也应使用索引。
- **在会话开始时核实 IDC 数据版本**——根据当前使用的路径，调用 `client.get_idc_version()`、`GET /v3/version`，或 MCP 的 `get_idc_version` 工具（当前为 v24）。若本地索引已过期，运行 `scripts/check_version.py` 并使用它打印出的升级命令。
- **检查许可并生成引用**——查询 `license_short_name` 并遵守 CC BY 与 CC BY-NC 的条款差异；使用 `citations_from_selection()` 基于 `source_DOI` 为出版物生成引用。
- **先小规模探索，再正式提交**——探索阶段使用 `LIMIT`（或较低的 `max_rows`），并在下载前检查 collection 的大小——部分 collection 有数太字节（TB）之巨。见 `references/cli_guide.md`。
- **保持下载可复现**——用 `dirTemplate`（例如 `%collection_id/%PatientID/%Modality`）组织目录结构，并为你构建的每个数据集妥善保存 Series UID 或清单文件。

## 故障排查

**问题：`ModuleNotFoundError: No module named 'idc_index'`**
- **原因**： 未安装 idc-index 包
- **解决方案**： 如果任务只涉及只读元数据，不要安装它——改用 REST API（见*数据访问方式*）。否则运行 `scripts/check_version.py` 并使用它打印出的安装命令，该命令针对当前运行的解释器，并锁定了经过验证的版本。若需进行数据分析，还应加装 pandas、numpy、pydicom（已在 pandas>=1.5、numpy>=1.23、pydicom>=2.3 下测试通过）。

**问题：下载因连接超时而失败**
- **原因**： 网络不稳定，或下载体量过大
- **解决方案**： 分成更小批次下载（10-20 个 series）；关于 `--use-s5cmd-sync` 的断点续传与重试指引见 `references/cli_guide.md`

**问题：`BigQuery quota exceeded` 或计费错误**
- **原因**： BigQuery 需要已开通计费的 GCP 项目
- **解决方案**： 简单查询改用 idc-index 的迷你索引（无需计费）；成本优化建议见 `references/bigquery_guide.md`

**问题：找不到 Series UID，或未返回任何数据**
- **原因**： UID 拼写错误、该数据不在当前 IDC 版本中，或字段名有误
- **解决方案**： 先用 `LIMIT 5` 测试，对照 `client.indices_overview` 核对字段名，并确认该 series 存在于当前版本中（部分旧数据已被废弃）

**问题：`index` 表中找不到某列（例如 `SliceThickness`、`PixelSpacing`、`KVP`、`EchoTime`、`InjectedDose`）**
- **原因**： `index` 表只包含 series 级别的元数据；模态专属的采集与重建参数保存在专用表中（`ct_index`、`mr_index`、`pt_index`）
- **解决方案**： 在 `client.indices_overview` 中搜索该列所在的表——具体检索方法见 `references/index_tables_guide.md` 中的*查找某列所在的表*一节——然后拉取该表并按 `SeriesInstanceUID` 连接：
  ```python
  client.fetch_index("ct_index")
  result = client.sql_query("""
      SELECT i.SeriesInstanceUID, i.Modality, c.SliceThickness, c.KVP, c.PixelSpacing_row_mm
      FROM index i
      JOIN ct_index c USING (SeriesInstanceUID)
      WHERE i.collection_id = 'your_collection'
  """)
  ```

**问题：下载下来的 DICOM 文件无法打开**
- **原因**： 下载已损坏，或该对象类型是查看器不支持的——SEG、RTSTRUCT、SR，以及切片显微数据都需要专用工具
- **解决方案**： 先检查 `Modality` 和 `SOPClassUID`，用 `pydicom.dcmread(file, force=True)` 进行校验，换一个查看器试试（3D Slicer，病理学可用 QuPath），然后重新下载

## 资源

各参考指南及其加载触发条件已在*快速导航*一节列出。

- **IDC 门户**：https://portal.imaging.datacommons.cancer.gov/explore/
- **文档**：https://learn.canceridc.dev/ —— **教程**：https://github.com/ImagingDataCommons/IDC-Tutorials
- **用户论坛**：https://discourse.canceridc.dev/ —— **idc-index**：https://github.com/ImagingDataCommons/idc-index
- **[indices_reference](https://idc-index.readthedocs.io/en/latest/indices_reference.html)** —— 外部的索引表文档（可能领先于当前所安装的版本）
- **引用格式**：Fedorov, A., et al. "National Cancer Institute Imaging Data Commons: Toward Transparency, Reproducibility, and Scalability in Imaging Artificial Intelligence." RadioGraphics 43.12 (2023). https://doi.org/10.1148/rg.230180
- **技能更新**：[发布页面](https://github.com/ImagingDataCommons/imaging-data-commons-skill/releases)；可关注该仓库（Watch → Custom → Releases）
