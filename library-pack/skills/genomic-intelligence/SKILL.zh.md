# Genomic Intelligence —— DNA 序列模型

Genomic Intelligence(GI)在托管 GPU 上提供 transformer DNA 语言模型，覆盖六项序列分析任务。给它一个**基因符号(gene symbol)**、一个**基因组区域(genomic region)**,或一条 **DNA/FASTA 序列**;它会返回结构化的预测结果——启动子区域、剪接位点、增强子活性、染色质状态、表达量(log TPM),以及从头(de-novo)基因注释。全部计算都不在本地运行:没有模型权重、没有 GPU、没有笨重的 Python 技术栈。它只是托管的、有版本管理的推理 API 的一个轻量客户端。

**官方文档**: [docs.genomicintelligence.ai](https://docs.genomicintelligence.ai) ·
REST 契约见 [api.genomicintelligence.ai/v1/openapi.json](https://api.genomicintelligence.ai/v1/openapi.json) ·
托管的 MCP 服务器地址为 `https://mcp.genomicintelligence.ai/mcp`

## 何时使用本技能

当用户手上有 DNA 数据、想要一个模型预测结果时，使用 GI:

- 在基因组区域中**查找启动子(promoter)**(`promoter`)
- **预测剪接(splice)** 供体/受体位点(`splice`)
- **给增强子活性打分**——发育型与管家型(housekeeping)(`enhancer`)
- 在数百个track上**注释染色质状态**(`chromatin`)
- 根据序列 + 细胞类型背景**预测表达量**,即 log(TPM+1)(`expression`)
- 从头**注释基因/转录本**,无需参考基因组(`annotation`)
- **在某区域中查找基因，并预测每个基因的表达量**(组合任务)

不适用于本地比对、变异检测或文件读写——这些请使用本地工具(BioPython、bcftools)。GI 专注于**基于序列的模型推理**。

> 仅供研究与开发使用,**不用于临床或诊断决策**。

## 调用 GI 的两种方式

### 托管 MCP 服务器(最适合 AI 代理——无需密钥)

GI 在 `https://mcp.genomicintelligence.ai/mcp`(Streamable HTTP)上托管了一个 MCP 服务器。当你的代理宿主环境支持 MCP 时，优先使用它:它对上限封顶的公开演示配额**无需密钥**即可使用(零配置),而可选的 `gi_` bearer key 可以提高该配额。它暴露的获取(acquisition)工具会返回一个**序列句柄(sequence handle)**(`sequence_ref`),而 `predict_*` 工具则以该句柄作为输入——因此大型序列永远不会占满上下文。参见下方的 [MCP 工作流程](#基于句柄的-mcp-工作流程) 以及 `references/mcp.md`。

### REST API(通用)

使用 `requests` 对 `https://api.genomicintelligence.ai/v1` 发起普通 HTTP 请求。REST 路径**要求**提供 `GI_API_KEY`(一个 `gi_` bearer key)。适用于任何宿主环境、脚本，或者当你需要原始响应封装(envelope)时。参见 [核心 REST 工作流程](#核心-rest-工作流程)。

## 访问与身份验证

1. **托管的 MCP 演示无需密钥**——不设置任何东西即可直接尝试。
2. **REST `/v1` API 需要一个密钥**,以 `Authorization: Bearer <key>` 的形式发送。可在 [contact@genomicintelligence.ai](mailto:contact@genomicintelligence.ai) 申请获取。
3. **绝不要把密钥硬编码进代码**。 从 `GI_API_KEY` 环境变量(或通过 `python-dotenv` 读取的 `.env` 文件)中读取。绝不要把密钥提交到版本库。

```bash
export GI_API_KEY="gi_yourkeyhere"     # MCP 可选; REST 必需
export GI_BASE_URL="https://api.genomicintelligence.ai"   # 用于切换到预发布环境
```

密钥被限定在某个合作伙伴等级(partner tier)之下，受并发数和每分钟调用次数的上限约束。收到 `429` 说明触及了上限——退避重试，或申请 GI 提高你的等级。

## 六项任务

所有 REST 任务共用同一种形态:`POST /v1/tasks/{task}/predict`,请求体为 `{sequence, sequence_name, model?, options?}`,返回一个 `{data, meta}` 封装。每项任务的区别在于:

| 任务 | 模式 | 长度限制 | 说明 |
|---|---|---|---|
| `promoter` | 同步 | 1-500,000 bp | 滑动窗口式的启动子区域 |
| `splice` | 同步 | 1-500,000 bp | 供体/受体位点(长上下文 BigBird) |
| `enhancer` | 同步 | 1-500,000 bp | 发育型 + 管家型分数(DeepSTARR,*果蝇*) |
| `chromatin` | 同步 | 1-500,000 bp | 数百个 track(DeepSEA) |
| `expression` | 同步 | **恰好 9,198 bp** | log(TPM+1);需要细胞类型 `description` |
| `annotation` | **异步** | 1-500,000 bp | 从头转录本；提交后轮询 |

**省略 `model` 参数,API 会使用该任务的默认模型**——这是推荐的调用方式。默认模型 ID 有意**不**在此处写明:默认值会变化，且已下线的 ID 会直接调用失败，因此绝不要把某个 ID 硬编码写死。要固定某个模型，或者要选用非人类模型(有几项任务提供果蝇、酵母和拟南芥模型),请在调用时通过 `GET /v1/tasks/{task}/models`(REST)或 `list_models`(MCP)动态发现 ID——**绝不要臆造一个**。每项任务完整的输出结构见 `references/tasks.md`。

模型强制执行两条硬性规则:

- **`expression` 需要恰好 9,198 bp**,一个**以 TSS 为中心**的窗口(上游 4,599 bp + TSS + 下游 4,598 bp)。任何其他长度都会被拒绝。使用下方的获取辅助工具来构建该窗口——不要手动截取。
- **`expression` 需要一个 `description`**——一个细胞类型/检测方式的字符串(例如 `"K562 cells"`),通过 `options.description` 传入。

## 序列获取

你很少会直接从一条原始的 9,198 bp 字符串开始。请先获取序列:

- **从基因符号出发** → MCP `fetch_ensembl_sequence(gene=...)`;**从坐标出发** → `fetch_region(region=...)`。两者都获取公开的 Ensembl 参考序列(无需密钥)。REST 用户可以直接查询 Ensembl REST。(`find_genes` 是注释任务，不是获取工具。)
- **对于 `expression`** → 使用以 TSS 为中心的获取方式，使窗口恰好为 9,198 bp。MCP:`fetch_gene_for_expression`(会自动处理居中)。不要手动构建该窗口。
- **从本地 FASTA 出发** → MCP `store_inline_sequence`,或者在 REST 中自行读取文件。(`load_local_fasta` 仅存在于本地部署中，托管服务器上没有。)
- **示例序列** → MCP `load_demo_sequence(name=...)` 返回一个可直接使用的句柄(非常适合无密钥的冒烟测试);`name` 是必填项。

确切的 Ensembl 调用方式和表达量窗口的计算方法，参见 `references/sequence-acquisition.md`。

## 核心 REST 工作流程

同步任务(promoter、splice、enhancer、chromatin、expression)只需一次调用:

```python
import os, requests

BASE = os.environ.get("GI_BASE_URL", "https://api.genomicintelligence.ai")
HEADERS = {"Authorization": f"Bearer {os.environ['GI_API_KEY']}"}

def predict(task, sequence, sequence_name, model=None, options=None):
    body = {"sequence": sequence, "sequence_name": sequence_name}
    if model:   body["model"] = model
    if options: body["options"] = options
    r = requests.post(f"{BASE}/v1/tasks/{task}/predict", headers=HEADERS, json=body)
    r.raise_for_status()          # 400 无效; 401 无密钥或密钥错误; 413 过长; 429 限流
    return r.json()               # {"data": {...}, "meta": {...}}

# Promoter:
out = predict("promoter", seq, "TP53_region")
print(out["data"]["summary"])

# Expression —— 恰好 9,198 bp + 一个细胞类型描述:
out = predict("expression", tss_window_9198bp, "HBB",
              options={"description": "K562 cells"})
print(out["data"]["prediction"]["expression_log_tpm"])
```

### 异步任务:annotation

`annotation` 采用先提交后轮询的方式。发送 `Prefer: respond-async`,获取一个 `job_id`,轮询直至任务终止:

```python
import time

r = requests.post(f"{BASE}/v1/tasks/annotation/predict",
                  headers={**HEADERS, "Prefer": "respond-async"},
                  json={"sequence": seq, "sequence_name": "TP53"})
r.raise_for_status()              # 202 Accepted
job_id = r.json()["data"]["job_id"]

while True:
    j = requests.get(f"{BASE}/v1/tasks/jobs/{job_id}", headers=HEADERS)
    if j.status_code == 200:      # 终止状态: 响应体即最终的 {data, meta}
        break
    j.raise_for_status()          # 202 = 仍在运行(2xx,不会抛出异常)
    time.sleep(5)                 # 约 20 kb 序列典型耗时约 20 秒
transcripts = j.json()["data"]["transcripts"]
```

## 基于句柄的 MCP 工作流程

在支持 MCP 的宿主环境中，先获取一个句柄，再针对该句柄进行预测——序列本身不会进入上下文:

```
# 1. 获取一个序列句柄(每个调用都返回一个 sequence_ref):
load_demo_sequence(name="promoter_tp53")  # 无密钥冒烟测试; `name` 为必填项
fetch_ensembl_sequence(gene="TP53")       # 基因符号或 Ensembl ID -> 句柄
fetch_region(region="chr11:5,225,000-5,235,000")   # 坐标 -> 句柄
fetch_gene_for_expression(gene="HBB")     # 用于 expression 的、以 TSS 为中心的 9,198 bp 句柄

# 2. 针对该句柄进行预测:
predict_promoter(sequence_ref=<ref>)
predict_expression(sequence_ref=<ref>, description="K562 cells")
predict_splice(sequence_ref=<ref>)        # + predict_enhancer / predict_chromatin

# 3. MCP 上的 annotation 是 `find_genes`(不存在 predict_annotation)。
#    它接受的是句柄而不是区域,并在内部以异步方式运行:
find_genes(sequence_ref=<ref>)            # wait=True(默认)会直接返回结果
find_genes(sequence_ref=<ref>, wait=False)  # -> job_id; 轮询 get_job(job_id)

# 通过 list_models(task) 发现可用模型; 参考上下文位于
# gi://models、gi://docs/tasks 和 gi://account 这几个 MCP 资源中。
```

## 组合任务:先查找基因，再预测表达量

要回答"这个区域里有哪些基因，它们的表达情况如何?"这类问题，使用组合任务:

- **MCP**: `find_genes_and_predict_expression(sequence_ref=..., description=...)`
  ——接受的是**句柄，而不是区域**(需先用 `fetch_region` 获取一个句柄);`description` 是必填项。查找序列中的基因，并为每个基因返回一个表达量预测。
- **REST**: 先调用基因发现，再对每个基因循环调用 `expression`(通过获取辅助工具为每个基因构建以 TSS 为中心的 9,198 bp 窗口)。

## 错误

| 状态码 | 含义 | 处理方式 |
|---|---|---|
| 400 | 请求无效/序列有误 | 检查请求体;expression 必须恰好 9,198 bp,且需携带 `description` |
| 401 | 密钥缺失/无效(REST) | 设置 `GI_API_KEY`;或使用无需密钥的 MCP 演示 |
| 413 | 序列过长 | 保持在该任务的长度限制以内(≤500,000 bp) |
| 429 | 速率/并发上限 | 退避重试；申请 GI 提高你的等级 |
| 422 | 校验失败(`validation_failed`) | 最常见的失败原因:expression 长度不是恰好 9,198 bp,或序列长度低于模型所需的最小长度 |
| 5xx | 服务器错误 | 重试；如持续出现，联系支持团队 |

## 参考文件

- `references/tasks.md` —— 各任务的输出结构、模型注册表、异步 annotation 的契约。
- `references/api-and-auth.md` —— REST 端点、`{data, meta}` 封装、身份验证、base-URL 覆盖、等级说明。
- `references/mcp.md` —— 托管 MCP 的工具列表、基于句柄的流程，以及 `gi://` 资源。
- `references/sequence-acquisition.md` —— Ensembl 获取调用方式，以及 expression 窗口(9,198 bp,以 TSS 为中心)的计算方法。
