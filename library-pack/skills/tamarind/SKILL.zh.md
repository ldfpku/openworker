# Tamarind Bio

Tamarind Bio 是一个云平台，在托管的 GPU 上运行计算生物学工具——结构预测、蛋白质与抗体设计、对接(docking)、结合亲和力预测，以及分子动力学。用户提交序列或结构，即可获得预测的结构、设计方案和生物物理学评分，无需自建硬件。它通过一个统一的任务(job)API 暴露了数百个工具(AlphaFold、Boltz-2、Chai-1、RFdiffusion、ProteinMPNN、BoltzGen、ESMFold2、DiffDock、Autodock Vina 等等)。

**官方文档**: [app.tamarind.bio/api-docs](https://app.tamarind.bio/api-docs) · 平台界面位于 [app.tamarind.bio](https://app.tamarind.bio)

## 权威信息来源——请实时抓取，不要依赖过时的副本

Tamarind 发布了实时的、机器可读的信息源。相比信任任何硬编码的列表，优先在运行时抓取这些信息源——工具名称、模式(schema)和端点变化频繁:

- **`https://app.tamarind.bio/llms.txt`** —— LLM 索引:链接到规范说明、API 文档和 MCP 指南。
- **`https://app.tamarind.bio/openapi.yaml`** —— 针对 8 个核心任务端点的 OpenAPI 3.0 规范(submit-job/-batch、jobs、result、upload、files、delete-job/-file;鉴权方式为 `ApiKeyAuth`)。要获取这些端点的确切形状(shape),请抓取此文件。发现/管理类端点(`/tools`、`/usage-statistics`、pipelines 等)不在其中——请使用 MCP/REST 的发现类工具。
- **`https://docs.tamarind.bio/llms.txt`** —— 文档索引；每个页面都有对应的 `.md` 形式(例如 `docs.tamarind.bio/tamarind/batch.md`、`/tamarind/api.md`、`/tamarind/pipelines.md`)。
- **实时工具发现** —— `GET /tools`(REST)或 MCP 的 `getAvailableTools` + `getJobSchema(jobType)` 是了解有哪些工具及其参数的权威信息源。

这份 skill 讲解的是这些信息源没有明说的接口表面 + 非直观行为(见参考文件)。当对某个形状(shape)有疑问时，请抓取 `openapi.yaml`。

## 何时使用此技能

当用户希望做以下事情时使用 Tamarind:

- **预测结构**:蛋白质、复合物或蛋白质-配体体系的结构(AlphaFold、Boltz-2、Chai-1、ESMFold2、Chai/Boltz 共折叠)
- **设计蛋白质或结合体(binder)**(RFdiffusion、BoltzGen、BindCraft、ProteinMPNN/LigandMPNN 逆折叠)
- **设计或表征抗体/纳米抗体**(序列生成、人源化、可开发性、免疫原性)
- **将小分子对接**到蛋白质上(DiffDock、Autodock Vina)或预测**结合亲和力**
- **生成 MSA**(多序列比对)用于下游折叠
- **运行分子动力学**或其他生物物理学工作流，均在托管 GPU 上完成
- **批量筛选**大量序列或设计方案，通过同一个工具处理
- **将多个工具串联**成流水线(例如设计 → 折叠 → 打分),把一个任务的输出作为下一个任务的输入

当工作应当在 Tamarind 的托管云端而非本地安装上运行时，这份技能是合适的选择。对于纯本地的化学信息学或一次性的序列 I/O,应改用本地库(RDKit、BioPython)。

## 访问与鉴权

1. 在 [app.tamarind.bio](https://app.tamarind.bio) 登录，并从账户/API 设置中创建一个 API key。
2. 每一个 REST 请求都通过 `x-api-key` 请求头进行鉴权。
3. **绝不要硬编码这个 key**。 从 `TAMARIND_API_KEY` 环境变量或 `.env` 文件中读取(使用 `python-dotenv`)。绝不要把 key 提交到源代码仓库中。

**定价**: 每个用户都获得 **10 个免费任务**。若需要更大用量，请联系 [info@tamarind.bio](mailto:info@tamarind.bio) 购买订阅。

```bash
export TAMARIND_API_KEY="your_api_key"
# List available tools
curl https://app.tamarind.bio/api/tools \
  -H "x-api-key: $TAMARIND_API_KEY"
```

**基础 URL**: `https://app.tamarind.bio/api/`

**没有官方的 Python SDK**——PyPI 上名为 `tamarind` 的包是一个不相关的 Neo4j 工具。不要 `uv pip install tamarind`。请针对 REST API 编写纯粹的 `requests` 调用(端点形状在 `openapi.yaml` 中),或者对于智能体宿主(agent host)使用 MCP 服务器。

## 调用 Tamarind 的两种方式

### MCP 服务器(最适合 AI 智能体)

Tamarind 在 `https://mcp.tamarind.bio/mcp` 托管了一个 MCP 服务器(通过 `X-API-Key` 请求头进行 API key 鉴权)。当你的智能体宿主支持 MCP 时，优先使用它——这些工具镜像了 REST API,并提供对智能体更友好的模式(schema):

- `listModalities()` / `listTags()` —— 实时的过滤词表(分子类型/功能),带有标签和工具计数；调用这些来获知有效的 `modality`/`function` 取值，而不是硬编码
- `getAvailableTools(modality?, function?, search?, custom?)` —— 发现工具(`category`/`tag` 是已弃用但仍受支持的别名)
- `getJobSchema(jobType)` —— 某个工具的精确参数模式，以及一个可用作起始负载(payload)的 `exampleJob`(提交前先验证它)
- `validateJob(jobName, type, settings)` —— 提交前的试运行验证(dry-run)
- `submitJob(jobName, type, settings)` / `submitBatch(batchName, type, settings[], jobNames[])`
- `getJobs(jobName?, batch?, limit?, includeSequences?)` —— 列出/查看任务及其状态(默认会省略体积较大的逐任务输入数据块；传入 `includeSequences=true` 以保留它)
- `getJobLogs(jobName)` —— 获取输出日志用于调试
- `listJobFiles(jobName)` —— 列出输出文件(返回 `s3Path` 以便链式调用)
- `getResult(jobName, fileName?)` —— 下载结果
- `uploadFile(filename)` —— 预签名(presigned)上传 URL;或者用 `uploadFileContent(filename, content, encoding?)` 在宿主无法访问 S3 时(沙盒化的智能体)通过 MCP 通道发送文件内容

作用域说明:MCP 查询类工具(`getJobs`、`getResult`、`listJobFiles` 等)的作用域限定于已鉴权的账户。

### REST API(通用)

使用 `requests` 发出纯 HTTP 请求——端点形状在 `openapi.yaml` 中。核心循环见下方;`references/workflows.md` 中有完整的示例配方(recipe)。

## 核心工作流

始终遵循"发现 → 模式 → 验证 → 提交 → 轮询 → 结果"这个顺序。不要硬编码工具名称或设置——目录变化频繁。

```python
import os, time, requests

BASE = "https://app.tamarind.bio/api"
HEADERS = {"x-api-key": os.environ["TAMARIND_API_KEY"]}

# 1. Discover tools. REST /tools returns the full list; filter client-side.
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()
alphafold = next(t for t in tools if t["name"] == "alphafold")

# 2. Get the exact schema for the chosen tool.
#    REST: each /tools entry already includes its inline `settings` schema
#          (parameter list) — find the entry whose name == your job type.
#    MCP:  getJobSchema(jobType) returns the same per-tool detail.

# 3. Submit a job. `settings` is tool-specific — match the schema exactly.
payload = {
    "jobName": "my-alphafold-run",          # ^[a-zA-Z0-9_-]+$, <=100 chars, unique
    "type": "alphafold",
    "settings": {
        "sequence": "MKTVRQERLKSIVRILERSKEPVSGAQLAEELSVSRQVIVQDIAYLRSLGYNIVATPRGYVLAGG",
        "numRecycles": 3,
    },
}
resp = requests.post(f"{BASE}/submit-job", headers=HEADERS, json=payload)
resp.raise_for_status()   # 200 ok; 400 bad request; 403 budget exceeded; 401 unauthorized

# 4. Poll for completion.
#    NOTE the response shape: GET /jobs?jobName=<name> returns the job ROW
#    directly (no "jobs" wrapper); the list query (no jobName) returns
#    {"jobs": [...]}. Don't index ["jobs"][0] on the by-name response.
while True:
    job = requests.get(f"{BASE}/jobs", headers=HEADERS,
                       params={"jobName": "my-alphafold-run"}).json()
    if job["JobStatus"] in ("Complete", "Stopped", "Deleted"):
        break
    time.sleep(30)

# 5. Retrieve results. POST /result returns a presigned URL *string*;
#    GET that URL to download the actual results zip (two-step).
url = requests.post(f"{BASE}/result", headers=HEADERS,
                    json={"jobName": "my-alphafold-run"}).text.strip('"')
open("my-alphafold-run.zip", "wb").write(requests.get(url).content)
```

关于使用 MCP 工具的智能体版本循环，以及更丰富的示例，见 `references/workflows.md`。

## 发现工具

目录中有数百个工具。始终在运行时枚举——绝不要依赖硬编码的列表。

**REST** 的 `GET /tools` 返回**完整列表**(它不做服务端过滤);每一项是 `{name, displayName, github, paper, description, settings}`,其中 `settings` 是该工具内联的参数模式。在客户端进行过滤:

```python
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()   # a list
boltz = [t for t in tools if "boltz" in t["name"].lower()]
```

注意:两个接口表面都是每个工具名称返回一行——REST 的 `/tools` 和 MCP 的 `getAvailableTools` 都做了去重(MCP 保留最新的工具版本),所以名称匹配会返回单独一行。

**MCP** 的 `getAvailableTools(search=..., modality=..., function=...)` 在服务端进行过滤，并为每个工具附加 `categories`/`tags`(`category`/`tag` 是 `modality`/`function` 的已弃用别名，仍受支持)。不要硬编码这些词表——它们会漂移(drift)。请从 `listModalities()` / `listTags()` 获取实时取值(每一个都返回 `value`、`label`、`description` 和 `toolCount`),或读取每次 `getAvailableTools` 响应中返回的 `availableCategories` / `availableTags` 分面(facet)数组。modality 是分子类型(蛋白质、抗体、肽、小分子、核酸……);function 是工具的功能(结构预测 structure-prediction、结合体设计 binder-design、蛋白质-配体对接 protein-ligand-docking……)。

一组具有代表性、被广泛使用的工具(以 `/tools` 为准进行核实):`alphafold`、`boltz`(Boltz-2)、`chai`(Chai-1)、`esmfold` / `esmfold2`、`rfdiffusion`、`proteinmpnn`、`ligandmpnn`、`boltzgen`、`bindcraft`、`diffdock`。完整的类别/标签映射以及如何读取工具元数据，见 `references/tool_catalog.md`。

## 选择合适的工具

目录中每个任务都有很多工具;**不要硬编码一个偏好的工具——先按 `function`(以及 `modality`)过滤，然后阅读每个候选工具的 `description`,并将其与用户的实际目标相匹配**(你已有的输入、你需要的输出、诸如速度或"不需要 MSA"之类的约束)。`description` 和 `tags` 字段是公开的"这是用来做什么的"信号；让它们再加上 `validateJob` 来引导你的选择。按任务的快速导览:

- **折叠单个蛋白质/复合物**(`function=structure-prediction`):AlphaFold3 一类的复现实现——`boltz`/`chai`/`openfold`/`protenix`/`intfold`——是**几乎所有情况**下(包括纯蛋白质体系)准确度上的默认选择；它们也能处理**核酸 + 小分子复合物**,所以只要体系里包含配体/RNA/DNA,就应优先考虑它们(而且 `boltz` 还附带结合亲和力预测)。`alphafold`(AF2)对于单体和多聚体(用 `:` 连接链)仍然是可靠的选择。`esmfold` 是单序列(不需要 MSA)且速度快——想要速度、又没有 MSA 时用它;`esmfold2` 更新一些，默认基于 MSA 进行条件化(其 `model` 设置提供了更快的单序列模式)。还存在针对抗体(`abodybuilder`、`immunebuilder`)、环肽(`highfold`)以及构象系综(`afcluster`、`alphaflow`)的专用折叠器——请过滤并阅读描述。
- **设计结合体(binder)**(`function=binder-design`):`bindcraft`(从头设计的迷你蛋白结合体)和 `boltzgen`(针对蛋白质**和**小分子靶标的结合体，包括纳米抗体/抗体/肽)是首选的从头结合体设计工具;`rfdiffusion` 也能做结合体设计，是**基序支架化(motif scaffolding)**/在已有骨架基础上做多样化设计的首选。抗体专用的生成器位于 `function=antibody-design` 之下。
- **为已知骨架设计序列**(`function=inverse-folding`):`proteinmpnn`(通用)、`ligandmpnn`(配体感知),以及热稳定/可溶/抗体专用的 MPNN 变体。逆折叠接受一个**结构**、输出**序列**——将其重新折叠以进行验证(见链式调用)。
- **对接小分子**(`function=protein-ligand-docking`):优先使用 `boltz`/`chai`——它们把配体共折叠进复合物中并预测结合后的结构，而不是对接进一个固定的口袋(pocket);当你需要针对已知口袋进行快速、大规模筛选时，再使用 `autodock-vina`。
- **预测结合亲和力**(`function=binding-affinity`)或**生成 MSA**(搜索 `msa`)——过滤并阅读描述。

当用户指名了某个具体工具时，评估该工具**并且**顺带核对同一 `tag` 分组下的其他候选——往往存在更快或更合适的同类工具。当不确定时，用 `getJobSchema`/`validateJob` 来确认某个候选确实能接受你手头的输入，再决定使用它。

## 任务设置、模式与验证

每个工具都有自己的 `settings` 模式。在提交之前先获取它:

- **REST** 的 `/tools` 条目:每个 `settings` 参数是一个**精简过**的字典。只有 `name` 和 `required` 始终存在;`type`、`default`、`description`、`options` 只在相关时才出现(约 60% 有 `type`)——所以要用 `param.get("type")`,而不是 `param["type"]`。高级的门控键(`exclude`、`conditionals`)**完全不在** REST 响应中。
- **MCP** 的 `getJobSchema(jobType)`:**完整**的模式，包括 `exclude`、`conditionals` 和边界值。当你需要推理这些门控键时使用 MCP。(`restrictOrgs` 在两个接口表面上都被剥离——一个你无法使用的组织限定参数会被直接省略；见 `references/api_reference.md`。)

**提交前始终 `validateJob`(MCP)**——这是可靠的防护措施。它执行与 `/submit-job` 相同的验证但不实际提交，并给出第一个缺失/无效的字段。不要试图从模式的键中手动推导应剥离哪些字段(在 REST 上你根本看不到这些键)——让 `validateJob` 来告诉你。(响应中可能包含一个 `source` 字段，例如 `"static-fallback"`——这是关于模式来源的内部说明，而不是校验器是否可达的说明;`valid: true/false` 才是你应据以行动的信号。)

`validateJob` 会回显一个填好默认值的 `normalized` 视图。提交时用你验证过的那份干净 `settings`;把 `normalized` 视为仅供参考(它可能带有你未设置的默认值，对某些工具还可能带有平台管理的字段),所以应从你自己的 settings 而不是 normalized 数据块来构建提交内容。

**序列**: 氨基酸字符串；多聚体的多条链之间用冒号(`:`)分隔，例如 `"MVLS...:EVQL..."`。注意有些工具(例如 `boltz`、`chai`)需要的不止 `sequence`——`boltz` 还需要 `inputFormat`(并且接受 `yamlFile`/`molecules`)。始终用 `getJobSchema`/`validateJob` 来了解某个工具的必填字段；不要假设只有 `sequence` 就够了。

**平台内部字段**——绝不要自己设置这些，平台拥有它们:`submit_method`、`monomer_msa`、`msa`。完整的字段处理规则见 `references/api_reference.md`。

**在提交前把有实际影响的选择呈现出来，不要静默地采用默认值**。 当请求已经完全指明了要运行什么时，直接进行即可。但当请求是开放式的，或者某个设置会实质性地改变结果、运行时间或成本(模型/变体、样本或种子数量、MSA 开/关、GPU 档位、批大小)时，应在提交**之前**呈现有意义的选项以及你原本会采用的默认值，让用户来选——而不是静默选择、等任务已排队后才汇报。`getJobSchema` 以及 `validateJob` 的 `normalized` 会精确显示出你正在代替用户填写哪些旋钮，这样你就能标出值得快速确认的少数几项。这一点对**批处理**尤为重要，因为一个共享设置的选择会在每个任务上被放大。

## 文件输入(PDB、CIF、SDF……)

带有文件参数的工具接受三种方式的输入:

1. **先上传，然后用裸文件名引用**。 `PUT /upload/{filename}`,或用 MCP 的 `uploadFile` → 预签名 URL → `curl -X PUT -T file "<url>"`。如果你的宿主无法访问 S3(一个没有出站网络的沙盒化智能体),改用 MCP 的 `uploadFileContent(filename, content, encoding?)`,通过 MCP 通道发送文件内容——默认是文本，二进制用 `encoding="base64"`。对象会落在 S3 键 `{email}/{filename}` 上,**但你在 `settings` 中引用它时只用裸 `filename`**(例如 `"targetFile": "GLP1R_ECD.pdb"`)——平台会自动把它限定到你的账户范围。**不要加上 email 前缀**:传入 `{email}/{filename}` 会使查找被加了两次前缀,`submit-job` 会返回 400 并报 `"The following files have not been uploaded: <email>/<file>"`。用 MCP 的 `getFiles(search=...)` / REST 的 `GET /files`(一个裸名称的扁平列表)来确认存储中登记的确切名称。
2. **通过路径引用先前任务的输出**:`JobName/path/to/file.ext`(这就是链式调用任务的方式——见下方)。
3. **内联内容**。 直接将文件的文本内容作为字段值发送。

**坑点**: 对于文件类型的参数,**纯字符串值会被当作内联文件内容处理**,而不是当作指向已有对象的路径。要指向一个已经上传的文件，请使用裸 `filename`(而不是 `{email}/...` 这种 S3 键),或者对于先前任务的输出，使用 `JobName/...` 路径形式——而不是你期望被解析为新内容的裸字符串。

**关于 `validateJob` 的说明。** 响应中可能带有一个 `source` 字段(例如 `"static-fallback"`)——它标注的是该工具的*模式*是如何被解析出来的(内置工具总是报告 `static-fallback`),**而不是**校验器是否可达，所以应据以行动的是 `valid`,而不是 `source`。对于文件参数:通过**裸文件名**(如上)引用一个已上传的文件——裸名称会被解析为你账户范围内的对象，而一个带 email 前缀的字符串可能被当作内联内容读取，并导致文件类型检查失败(`"... must contain ATOM records"`)。此外，传入**内联**文件内容会使 `validateJob` 在验证之前同步上传该内容，这可能会很慢；优先按名称引用已上传的文件(如上)。如果一次 dry-run 很慢，可以跳过它，让 `submit-job` 来做验证。

## 将任务串联成流水线

一个已完成任务的输出会成为下一个任务的输入——无需下载再重新上传。**要匹配下一个工具真正需要的输入类型**: 一个序列设计工具(ProteinMPNN)输出的是*序列*,所以你把每一条作为 `sequence` 传入来折叠它们；一个接受*文件*参数的工具则需要一个路径。

最简洁的"设计 → 折叠"链式调用是 MCP 的 `submitBatch(fromJob=...)`,它读取一个已完成的设计任务生成的序列，并把每一条都作为一个任务进行折叠:

```
# ProteinMPNN designs sequences -> fold every one with AlphaFold, one call:
submitBatch(batchName="verify-designs", type="alphafold", fromJob="my-proteinmpnn-job")
```

对于**文件**输入(例如某个接受 `.pdb`/`.cif` 的工具),在该文件参数中通过路径形式 `JobName/path/to/file.ext` 引用先前任务的输出。有两点需要注意，均已通过验证确认:(1) 匹配该参数所需的**文件类型**——例如 AlphaFold 的 `templateFiles` 只接受 `.cif` 且是一个列表，并且被门控在 `templateMode: "custom"` 之下;(2) `templateFiles` 是用于*结构模板*的，不是用来"折叠这个设计出的序列"的——要折叠一条序列，请传入 `sequence`。在链式调用某个文件参数之前，始终用 `getJobSchema`/`validateJob` 来确认它的文件类型/条件。

要发现一个任务确切的输出路径，使用 MCP 的 `listJobFiles(job1)`——它返回每个文件的 `s3Path`,可以直接用于下一次 `submitJob`。(REST 的 `GET /files` 列出的是你账户下*已上传*的文件、一个扁平的名称列表；它不会枚举某个任务的输出。)Tamarind 还支持已保存的**流水线(pipelines)**:在 UI 中构建一个流水线，然后用 `/run-pipeline`(`{pipelineName, initialInputs, inputs}`)驱动它，或者通过 `/submit-pipeline` 内联定义 `stages[]`(每个 stage 指定一个 `task` + `toolSettings`,用 `"pdbFile": "pipe"` 把一个 stage 的输出串到下一个)。见 `references/workflows.md`。

## 批量提交

在一次调用中提交**同一个工具**的多个任务。Python 形式使用等长的并行数组 `settings[]` 和 `jobNames[]`(长度相同，最多 100 个):

```python
requests.post(f"{BASE}/submit-batch", headers=HEADERS, json={
    "batchName": "egfr-binder-screen",
    "type": "alphafold",
    "jobNames": ["seq1", "seq2", "seq3"],
    "settings": [{"sequence": "..."}, {"sequence": "..."}, {"sequence": "..."}],
    # optional: "maxRuntimeSeconds": 3600, "weightedHoursBudget": 100,
    # (some accounts also accept an optional "gpuType" — confirm with support)
})
```

**轮询批处理的*父任务*的 `batchStatus`,而不是子任务的 `JobStatus`。** 一次批处理会创建一个父任务(`Type: "batch"`)加若干子任务。子任务一旦计算完成就会翻转为 `Complete`,但随后批处理还需要花几分钟把结果**聚合**（aggregating）成最终可下载的输出。按名称获取父任务并监视 `batchStatus`:

```python
import time
while True:
    # ?jobName= returns the parent ROW directly (no "jobs" wrapper)
    parent = requests.get(f"{BASE}/jobs", headers=HEADERS,
                          params={"jobName": "egfr-binder-screen"}).json()
    bs = parent.get("batchStatus")
    if bs == "Complete":
        break
    if bs in ("Stopped", "AggregationFailed"):
        raise RuntimeError(parent.get("AggregationError", bs))
    time.sleep(15)   # Running / Aggregating -> keep waiting
# When Complete, the parent carries a presigned `resultUrl` and a `statuses`
# subjob tally ({Complete, Running, In Queue, Stopped}).
open("batch.zip", "wb").write(requests.get(parent["resultUrl"]).content)
```

在 `GET /jobs?batch=<name>` 上加 `includeSubjobs=true`,以列出各个子任务行。

## 任务状态生命周期

单个任务报告 `JobStatus`;批处理父任务报告 `batchStatus`(批处理请轮询它——见上文)。

| 状态 | 含义 |
|---|---|
| `In Queue` | 已接受，等待算力 |
| `Running` | 正在某个 worker 上执行 |
| `Complete` | 成功完成——结果可用 |
| `Stopped` | 已停止(失败、超时、手动停止，或预算原因) |
| `Deleted` | 任务被带外(out-of-band)删除 |
| `Aggregating` | (仅批处理父任务)子任务已完成；正在构建最终输出 |
| `AggregationFailed` | (仅批处理父任务)聚合步骤失败 |

已完成的任务带有一个 `Score`(工具特定的指标，例如折叠任务的 pLDDT/pTM/ipTM)和 `WeightedHours`。把 `Complete`/`Stopped`/`Deleted`(以及批处理的 `AggregationFailed`)视为终止状态；以 15-30 秒的间隔轮询。**在遇到任何终止状态时都要跳出轮询循环，而不仅仅是 `Complete`/`Stopped`**——否则一个在轮询中途变为 `Deleted` 的任务会导致无限循环。对于 `Stopped` 的任务，获取 `getJobLogs(jobName)` 来查看原因。`WeightedHours` 是按任务计费的使用量单位；用 `weightedHoursBudget` 为一次批处理设置上限，提交时收到 `403` 意味着触发了某个预算(见 `references/api_reference.md` 和 `/usage-statistics` 端点)。

## 错误处理

| 代码 | 含义 | 应对措施 |
|---|---|---|
| 400 | 错误请求 / 无效设置 | 对照模式重新检查；先运行 `validateJob` |
| 401 | 未鉴权 | 检查 `x-api-key` |
| 403 | 预算超限(组织/团队) | 缩小范围或提高预算 |
| 429 | 触发限流 | 退避后重试 |
| 500 | 服务器错误 | 重试；若持续出现，联系支持团队 |

## 参考文件

`openapi.yaml` 规范是端点形状的权威信息源；下面这些文件补充了规范没有讲明的行为和坑点:

- `references/examples.md` —— 针对常见工具(alphafold/boltz/diffdock/autodock-vina/proteinmpnn/batch)**经过验证**的 `settings` 负载、一份可直接复制粘贴的自检清单、"会失败的情形及确切报错"列表，以及输出形状说明。要一份可用的负载，从这里开始。
- `references/api_reference.md` —— 端点速查表 + 非直观的形状:`/jobs` 按名称查询返回的是裸行(而不是 `{jobs:[...]}`)、`/result` 是两步下载、批处理父任务要轮询 `batchStatus`、`/files` 是一个扁平的名称列表、`settings` 字段的处理规则。
- `references/tool_catalog.md` —— 类别/标签映射、如何读取工具+参数元数据、常见工具家族。
- `references/workflows.md` —— 端到端配方:折叠一条序列、提交前先验证、上传并引用一个文件、设计→折叠链式调用、带聚合轮询的批量筛选、用量统计、分页，以及针对长任务的"现在提交、稍后检查"的非阻塞模式。
