# Adaptyv Bio Foundry API

Adaptyv Bio 是一个把蛋白质序列转化为实验数据的云端实验室。用户通过 API 或 UI 提交氨基酸序列;Adaptyv 的自动化实验室会运行相应的检测(结合、热稳定性、表达、荧光),并在约 21 天内交付结果。

**官方文档**: [docs.adaptyvbio.com/api-reference](https://docs.adaptyvbio.com/api-reference) · [llms.txt index](https://docs.adaptyvbio.com/llms.txt) · [OpenAPI spec](https://foundry-api-public.adaptyvbio.com/api/v1/openapi.json)

## 快速开始

**基础 URL**: `https://foundry-api-public.adaptyvbio.com/api/v1`

**身份认证**: 在 `Authorization` 请求头中携带 Bearer token。令牌可从 [foundry.adaptyvbio.com](https://foundry.adaptyvbio.com/) 的侧边栏获取。

编写代码时，务必从环境变量 `ADAPTYV_API_KEY` 或 `.env` 文件中读取 API 密钥——绝不要把令牌硬编码在代码里。先检查项目根目录下是否存在 `.env` 文件；如果存在，用类似 `python-dotenv` 的库来加载它。

[官方 API 文档](https://docs.adaptyvbio.com/api-reference/api-introduction)在 curl 示例中使用的是 `FOUNDRY_API_TOKEN`;那是同一个 bearer token——为了与 SDK 保持一致，在 Python 和新的 shell 脚本中优先使用 `ADAPTYV_API_KEY`。

```bash
export ADAPTYV_API_KEY="abs0_..."
curl https://foundry-api-public.adaptyvbio.com/api/v1/targets?limit=3 \
  -H "Authorization: Bearer $ADAPTYV_API_KEY"
```

除 `GET /openapi.json` 外，每一个请求都需要身份认证。要把令牌存放在环境变量或 `.env` 文件中——绝不要将其提交到源代码控制系统中。

## Python SDK

**版本说明**: `adaptyv-sdk` **0.1.0**(beta 版)尚未发布到 PyPI——需从 GitHub 安装:

```bash
uv pip install "git+https://github.com/adaptyvbio/adaptyv-sdk.git"
```

在带有 `pyproject.toml` 的项目中:

```bash
uv add "adaptyv-sdk @ git+https://github.com/adaptyvbio/adaptyv-sdk.git"
```

**环境变量**(在 shell 或 `.env` 文件中设置):

```bash
ADAPTYV_API_KEY=your_api_key
ADAPTYV_API_URL=https://foundry-api-public.adaptyvbio.com/api/v1
ADAPTYV_ORGANIZATION_ID=your_org_id  # optional
```

当未显式传入时,`@lab.experiment` 装饰器和 `FoundryClient` 都会从环境中读取 `ADAPTYV_API_KEY` 和 `ADAPTYV_API_URL`。

### 装饰器模式(Decorator Pattern)

```python
from adaptyv import lab

@lab.experiment(target="PD-L1", experiment_type="screening", method="bli")
def design_binders():
    return {"design_a": "MVKVGVNG...", "design_b": "MKVLVAG..."}

result = design_binders()
print(f"Experiment: {result.experiment_url}")
```

### 客户端模式(Client Pattern)

```python
import os
from adaptyv import FoundryClient

client = FoundryClient(
    api_key=os.environ["ADAPTYV_API_KEY"],
    base_url=os.environ.get(
        "ADAPTYV_API_URL",
        "https://foundry-api-public.adaptyvbio.com/api/v1",
    ),
)

# Browse targets
targets = client.targets.list(search="EGFR", selfservice_only=True)

# Estimate cost
estimate = client.experiments.cost_estimate({
    "experiment_spec": {
        "experiment_type": "screening",
        "method": "bli",
        "target_id": "target-uuid",
        "sequences": {"seq1": "EVQLVESGGGLVQ..."},
        "n_replicates": 3
    }
})

# Create and submit
exp = client.experiments.create({...})
client.experiments.submit(exp.experiment_id)

# Later: retrieve results
results = client.experiments.get_results(exp.experiment_id)
```

## 实验类型

| 类型 | 方法 | 测量内容 | 是否需要靶点 |
|---|---|---|---|
| `affinity`(亲和力) | `bli` 或 `spr` | KD、kon、koff 动力学参数 | 是 |
| `screening`(筛选) | `bli` 或 `spr` | 是否结合(Yes/no) | 是 |
| `thermostability`(热稳定性) | — | 熔解温度(Tm) | 否 |
| `expression`(表达) | — | 表达产量 | 否 |
| `fluorescence`(荧光) | — | 荧光强度 | 否 |

## 实验生命周期

```
Draft → WaitingForConfirmation → QuoteSent → WaitingForMaterials → InQueue → InProduction → DataAnalysis → InReview → Done
```

| 状态 | 由谁操作 | 说明 |
|---|---|---|
| `Draft`(草稿) | 你 | 可编辑，无成本承诺 |
| `WaitingForConfirmation`(等待确认) | Adaptyv | 正在审核，准备报价中 |
| `QuoteSent`(已发送报价) | 你 | 查看并确认报价 |
| `WaitingForMaterials`(等待物料) | Adaptyv | 基因片段和靶点已下单 |
| `InQueue`(排队中) | Adaptyv | 物料已到位，正在排队等待入实验室 |
| `InProduction`(生产中) | Adaptyv | 检测正在运行 |
| `DataAnalysis`(数据分析) | Adaptyv | 原始数据处理与质控 |
| `InReview`(审核中) | Adaptyv | 最终验证 |
| `Done`(已完成) | 你 | 结果已可获取 |
| `Canceled`(已取消) | 任一方 | 实验已取消 |

某个实验上的 `results_status` 字段追踪以下状态之一:`none`、`partial`,或 `all`。

## 常见工作流

### 1. 提交一次结合筛选(逐步说明)

```python
# 1. Find a target
targets = client.targets.list(search="EGFR", selfservice_only=True)
target_id = targets.items[0].id

# 2. Preview cost
estimate = client.experiments.cost_estimate({
    "experiment_spec": {
        "experiment_type": "screening",
        "method": "bli",
        "target_id": target_id,
        "sequences": {"seq1": "EVQLVESGGGLVQ...", "seq2": "MKVLVAG..."},
        "n_replicates": 3
    }
})

# 3. Create experiment (starts as Draft)
exp = client.experiments.create({
    "name": "EGFR binder screen batch 1",
    "experiment_spec": {
        "experiment_type": "screening",
        "method": "bli",
        "target_id": target_id,
        "sequences": {"seq1": "EVQLVESGGGLVQ...", "seq2": "MKVLVAG..."},
        "n_replicates": 3
    }
})

# 4. Submit for review
client.experiments.submit(exp.experiment_id)

# 5. Poll or use webhooks until Done
# 6. Retrieve results
results = client.experiments.get_results(exp.experiment_id)
```

### 2. 自动化流水线(跳过草稿状态 + 自动接受报价)

```python
exp = client.experiments.create({
    "name": "Auto pipeline run",
    "experiment_spec": {...},
    "skip_draft": True,
    "auto_accept_quote": True,
    "webhook_url": "https://my-server.com/webhook"
})
# Webhook fires on each status transition; poll or wait for Done
```

### 3. 使用 Webhook

在创建实验时传入 `webhook_url`。每当状态发生转变,Adaptyv 就会向该 URL 发起 POST 请求，携带实验 ID、之前的状态，以及新的状态。

## 序列

- 简单格式:`{"seq1": "EVQLVESGGGLVQPGGSLRLSCAAS"}`
- 富格式:`{"seq1": {"aa_string": "EVQLVESGGGLVQ...", "control": false, "metadata": {"type": "scfv"}}}`
- 多链:使用冒号分隔符——`"MVLS:EVQL"`
- 有效的氨基酸字母:A、C、D、E、F、G、H、I、K、L、M、N、P、Q、R、S、T、V、W、Y(不区分大小写，存储时统一为大写)
- 序列只能添加到处于 `Draft` 状态的实验中

## 过滤、排序与分页

所有列表端点都支持分页(`limit` 取值范围 1-100,默认 50;`offset`)、搜索(对名称字段的自由文本搜索),以及排序。

**过滤** 通过 `filter` 查询参数，使用 s-expression 语法:
- 比较运算:`eq(field,value)`、`neq`、`gt`、`gte`、`lt`、`lte`、`contains(field,substring)`
- 范围/集合:`between(field,lo,hi)`、`in(field,v1,v2,...)`
- 逻辑运算:`and(expr1,expr2,...)`、`or(...)`、`not(expr)`
- 空值:`is_null(field)`、`is_not_null(field)`
- JSONB:`at(field,key)`——例如 `eq(at(metadata,score),42)`
- 类型转换:`float()`、`int()`、`text()`、`timestamp()`、`date()`

**排序** 使用 `asc(field)` 或 `desc(field)`,以逗号分隔(最多 8 个):
```
sort=desc(created_at),asc(name)
```

**示例**: `filter=and(gte(created_at,2026-01-01),eq(status,done))`

## 错误处理

所有错误都返回:
```json
{
  "error": "Human-readable description",
  "request_id": "req_019462a4-b1c2-7def-8901-23456789abcd"
}
```
`request_id` 同样出现在 `x-request-id` 响应头中——联系技术支持时应附带它。

## 令牌管理

令牌使用基于 Biscuit 的加密衰减(attenuation)机制。你可以通过 `POST /tokens/attenuate` 创建按组织、资源类型、操作(read/create/update)和有效期限定范围的受限令牌。撤销一个令牌(`POST /tokens/revoke`)会撤销它以及它的所有派生令牌。

## 详细 API 参考

关于全部 32 个端点及其请求/响应 schema 的完整列表，阅读 `references/api-endpoints.md`。
