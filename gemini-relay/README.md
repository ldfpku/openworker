# Gemini 中转方案（gemini-relay）

本文是什么、读者何时读：这是 `gemini-relay` 目录的入口文档，给第一次接触这套方案、想在几分钟内跑通中转链路的人看。设计决策、部署细节、接入方式、排错和安全评估分别在 `docs/` 目录的各篇文档里，本文只给主线。

## 一句话

不再依赖 v2rayN 本地代理：openworker 经由自己在 Cloudflare 上的自定义域名 `gemini.smjtools.com` 做反向代理，直连 Gemini API。v2 起中转面向公司内约 10 人共用：每人用自己的 Gemini API key，Worker 侧用 KV 名册（`sha256(key) → 邮箱`）做准入控制，并把每次请求的 token 用量按人记进 D1——同事那边**只需要填 API key**，不需要任何环境变量或脚本。

## 架构

```
openworker (google-genai 2.16.0, httpx 0.28.1)
   │  HTTPS 直连（SNI=gemini.smjtools.com，无需 v2rayN；中转地址内置在 provider 代码里）
   ▼
Cloudflare Worker @ gemini.smjtools.com   ← 自定义域名（Custom Domain），反向代理 + KV 名册准入 + D1 用量流水
   │  sha256(x-goog-api-key) 查 KV 名册 → 邮箱（未登记一律 403）
   │  fetch() → https://generativelanguage.googleapis.com + 原样 path/query（流式透传）
   │  响应流 tee()：客户端支路原样返回；记录支路后台解析 usageMetadata → 异步写 D1
   ▼
Gemini API（出口 IP 为 Cloudflare 边缘）
```

> 大陆对 Cloudflare 自定义域名的可达性是社区共识而非保证（`*.workers.dev` 有大量社区报告在大陆被污染/阻断，本仓库未实测），
> 未经本域名实测；置信度评级与回退方案见 [06-安全与风险.md](docs/06-安全与风险.md)。

## 前提条件

（以下都是**管理员**一次性要做的事；同事什么都不需要准备，只要有自己的 Gemini API key。）

- Cloudflare 账号，且 `smjtools.com` 已挂在 Cloudflare NS（已确认：`norm.ns.cloudflare.com` / `georgia.ns.cloudflare.com`）。
- 本机已装 Node.js + npm（`npx wrangler` 依赖 npm）。
- 一个自己的 Gemini API Key 用于验证：`GEMINI_API_KEY` 或 `GOOGLE_API_KEY` 环境变量，或项目根 `.env` 里的 `GEMINI_API_KEY=` 一行。

## 快速开始（管理员视角，4 步）

### 1. 部署 Worker（含 KV 名册与 D1 用量库的创建）

```powershell
cd gemini-relay\worker
npm install
Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:ALL_PROXY -ErrorAction SilentlyContinue   # 清掉 proxy-guard 遗留的代理变量，wrangler 直连 api.cloudflare.com（详见 docs/03）
npx wrangler login
npx wrangler kv namespace create ROSTER               # 输出的 id 填入 wrangler.jsonc 的 kv_namespaces
npx wrangler d1 create gemini_relay_usage             # 输出的 database_id 填入 wrangler.jsonc 的 d1_databases
npx wrangler d1 migrations apply gemini_relay_usage --remote   # 建 usage 表
npx wrangler deploy
```

**注意顺序敏感**：`wrangler deploy` 完成的那一刻起，未登记的 key 一律 403，所以部署后要先登记（第 3 步）再测试。逐步说明见 [docs/03-Worker部署指南.md](docs/03-Worker部署指南.md)。

### 2. 等 DNS/证书生效，验证健康检查

`routes` 里的 `custom_domain: true` 会在部署后自动建 DNS 记录和 TLS 证书，通常几分钟内生效（部署前 `gemini.smjtools.com` 是 NXDOMAIN，这是预期状态，不是故障）。

```powershell
curl https://gemini.smjtools.com/healthz
```

### 3. 登记自己的 key，用 SDK 脚本测非流式 + 流式

下面两条命令的路径都是相对仓库根目录写的，先切回仓库根（第 1 步的 `cd gemini-relay\worker` 之后仍在 worker 目录下）：

```powershell
cd ..\..
.\gemini-relay\scripts\roster.ps1 -Add 自己的邮箱@example.com    # 按提示安全输入 key，不回显、不进历史
& "C:\Users\liude\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" gemini-relay\scripts\test_relay.py
```

`test_relay.py` 用的 key 必须已经登记过，否则两个测试都会收到 `403 unregistered key`。

### 4. 登记同事，分发 openworker

```powershell
.\gemini-relay\scripts\roster.ps1 -Add 同事邮箱@example.com    # 每人一次
```

同事拿到 openworker 之后，只需在 Settings ▸ Models 里填自己的 Gemini API key——不需要设环境变量、不需要跑任何脚本，中转地址已经内置在代码里（见下节）。名册维护（登记/吊销/key 轮换）与用量报表见 [docs/07-多用户与用量统计.md](docs/07-多用户与用量统计.md)。

> 遗留脚本说明：`scripts\set-relay-env.ps1` 和 `scripts\start-openworker-cn.ps1` 是 v1 时代靠环境变量接线的产物，v2 已不需要。保留仅作调试用途——它们设置的 `GOOGLE_GEMINI_BASE_URL` 现在是**优先级高于内置常量的调试覆盖**，设了会盖住代码里的默认值，排错前记得清理（`set-relay-env.ps1 -Uninstall`）。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/01-背景与结论.md](docs/01-背景与结论.md) | 问题回顾（400 FAILED_PRECONDITION 实测、v2rayN 现状）、v1 研究结论记录、与正向代理方案的对比 |
| [docs/02-架构设计.md](docs/02-架构设计.md) | 设计目标与约束、请求生命周期（含名册准入、SSE、用量记录）、方案对比表（A/B/C/D）、Worker 设计决策逐条 |
| [docs/03-Worker部署指南.md](docs/03-Worker部署指南.md) | 部署步骤（含 KV 名册与 D1 用量库的创建）、免费额度对照表、更新与回滚 |
| [docs/04-OpenWorker接入.md](docs/04-OpenWorker接入.md) | v1 遗留：环境变量接线机制与四种接入方式。v2 已把中转地址内置进 provider 代码，本篇的环境变量现为调试通道 |
| [docs/05-验证与排错.md](docs/05-验证与排错.md) | 五级验证阶梯（DNS→TLS→REST→SDK→端到端）、排错矩阵表（含名册 403、用量记录排错） |
| [docs/06-安全与风险.md](docs/06-安全与风险.md) | 信任边界、名册准入与滥用面、PII 边界（邮箱）、平台与合规风险 |
| [docs/07-多用户与用量统计.md](docs/07-多用户与用量统计.md) | 名册模型（登记/吊销/key 轮换）、上线迁移顺序、用量报表（`usage_report.py` 与控制台 SQL）、数据保留 |

## 为什么同事只需要填 key

1. v2 把中转地址直接写进了 provider 代码：`coworker/providers/gemini_provider.py` 顶部有模块常量 `RELAY_BASE_URL = "https://gemini.smjtools.com"`，`_ensure_client()` 构造 `genai.Client` 时显式传 `http_options=types.HttpOptions(base_url=...)`——这是 google-genai SDK 优先级最高的一等入口，不再依赖环境变量这种隐式接线。
2. 实际生效地址由 `resolve_base_url()` 按三级优先级解析：**profile 隐藏 `base_url` 覆盖**（`registry.py` 的 `_build_gemini`，UI 不出现该字段）> **环境变量 `GOOGLE_GEMINI_BASE_URL`**（调试通道）> **内置常量 `RELAY_BASE_URL`**。环境变量从 v1 的接线机制降级为调试覆盖——不设任何东西时就是走中转，这正是"同事只填 key"的机制来源。
3. 中转不可用时**不回退**直连上游，这是设计决定：`generativelanguage.googleapis.com` 在大陆本就不可达，回退只会把失败换一种更难排查的方式呈现。v1 的环境变量机制细节保留在 [docs/04-OpenWorker接入.md](docs/04-OpenWorker接入.md)（现为遗留/调试参考）。

范围说明：本方案只覆盖原生 Gemini provider（`coworker/providers/gemini_provider.py`）。Vertex 家族在 `vertex_provider.py` 里自建 `genai.Client(vertexai=True)`，读的是另一个环境变量 `GOOGLE_VERTEX_BASE_URL`，不受这里的改动影响，也不在本方案范围内。

## 回退

v2 中 openworker 的 Gemini 流量固定走中转，中转不可用时请求直接失败（无回退是设计决定，见上节第 3 条）。紧急调试时可以用 `GOOGLE_GEMINI_BASE_URL` 环境变量临时把请求指向别处（它的优先级高于内置常量），但大陆环境下指回 Google 直连需要自行配合本地正向代理（v2rayN + proxy-guard，见 [docs/01-背景与结论.md](docs/01-背景与结论.md)）。如果本机还留着 v1 时代写入的环境变量，用 `.\gemini-relay\scripts\set-relay-env.ps1 -Uninstall` 清理。排错步骤见 [docs/05-验证与排错.md](docs/05-验证与排错.md)。
