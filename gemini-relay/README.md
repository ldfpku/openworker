# Gemini 中转方案（gemini-relay）

本文是什么、读者何时读：这是 `gemini-relay` 目录的入口文档，给第一次接触这套方案、想在几分钟内跑通中转链路的人看。设计决策、部署细节、接入方式、排错和安全评估分别在 `docs/` 目录的各篇文档里，本文只给主线。

## 一句话

不再依赖 v2rayN 本地代理：openworker 经由自己在 Cloudflare 上的自定义域名 `gemini.smjtools.com` 做反向代理，直连 Gemini API。中转面向公司十来人共用，同事需要两样东西，**都由管理员发放**：一个在允许名单里的公司邮箱（走 Cloudflare Access 一次性验证码登录，Worker 校验通过后签发一个只对本中转有效的登录令牌），和一把以他本人命名的 Gemini API key。**中转自己一把 key 都不存**——它只在转发的瞬间经手。每次请求的 token 用量按登录邮箱记进 D1。

## 架构

```
openworker (google-genai 2.16.0, httpx 0.28.1)
   │  登录：系统浏览器 → /login/<sid> → Cloudflare Access 一次性验证码
   │        → 302 回本机回环 → 换到登录令牌 owr_…（存本机 secrets.json）
   │  调用：HTTPS 直连（SNI=gemini.smjtools.com，无需 v2rayN；中转地址内置在 provider 代码里）
   │        authorization: Bearer owr_…（登录令牌）+ x-goog-api-key: AIza…（他专属的那把 key）
   ▼
Cloudflare Worker @ gemini.smjtools.com   ← 自定义域名，反向代理 + 令牌准入 + 按人限额 + D1 用量流水
   │  /login/*      ← 被 Access 保护（唯一一条），验签 Access JWT 取邮箱，查 KV 名单，签发令牌
   │  /auth/*       ← 公开，一次性 code + PKCE 兑换令牌；/auth/whoami 还回今天的限额读数
   │  /v1beta/*     ← 公开，凭令牌准入：KV 查 t:<sha256(令牌)> → 邮箱 → 名单（未登录 401 / 被吊销 403）
   │                  再按邮箱查限额闸门（超了 429），最后剥掉 authorization，
   │                  x-goog-api-key 原样透传——中转自己一把 key 都没有
   │  fetch() → https://generativelanguage.googleapis.com + 原样 path/query（流式透传）
   │  响应流 tee()：客户端支路原样返回；记录支路后台解析 usageMetadata → 异步写 D1
   ▼
Gemini API（出口 IP 为 Cloudflare 边缘）
```

> 大陆对 Cloudflare 自定义域名的可达性是社区共识而非保证（`*.workers.dev` 有大量社区报告在大陆被污染/阻断，本仓库未实测），
> 未经本域名实测；置信度评级与回退方案见 [06-安全与风险.md](docs/06-安全与风险.md)。

## 前提条件

（以下都是**管理员**一次性要做的事；同事需要两样，都由你给：一个在允许名单里的邮箱，和一把以他名字命名的 Gemini API key。）

- Cloudflare 账号，`smjtools.com` 这个 zone 和 gemini-relay 这个 Worker 都在这个账号下（`norm.ns.cloudflare.com` / `georgia.ns.cloudflare.com`）。整套信任模型的地基就是这一条。
- 已开通 Cloudflare Zero Trust（免费方案够用），用来做 Access 一次性验证码登录。
- 本机已装 Node.js + npm（`npx wrangler` 依赖 npm）。
- 一个能开 Gemini API 的 **Google 账号**：全公司的 key 都从它签发，账单也记在它头上。
  **中转本身不需要放任何 key**——它只在转发的瞬间经手，不存储。

## 快速开始（管理员视角）

### 1. 配好 Cloudflare Access 登录

整套 Zero Trust 配置（打开 One-time PIN、建只保护 `/login` 的自托管应用、把允许名单填进策略、取 AUD 填进 `wrangler.jsonc`）见 **[docs/08-Access登录配置.md](docs/08-Access登录配置.md)**。这是 v3 唯一新增的一次性配置，必须先做。

### 2. 部署 Worker（含 KV 名单与 D1 用量库）

```powershell
cd gemini-relay\worker
npm install
Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:ALL_PROXY -ErrorAction SilentlyContinue   # 清掉 proxy-guard 遗留的代理变量，wrangler 直连 api.cloudflare.com（详见 docs/03）
npx wrangler login
npx wrangler kv namespace create ROSTER               # 首次；输出的 id 填入 wrangler.jsonc 的 kv_namespaces
npx wrangler d1 create gemini_relay_usage             # 首次；输出的 database_id 填入 wrangler.jsonc 的 d1_databases
npx wrangler d1 migrations apply gemini_relay_usage --remote   # 建 usage / auth_events / quota 表
npx wrangler deploy
```

**这个 Worker 没有任何机密**——每个调用方带自己的 Gemini key，中转原样转发、一把都不存，所以没有 `wrangler secret` 这一步。要填的只有 `wrangler.jsonc` 里的两个 Access 坐标和三个限额默认值（`QUOTA_RPM`/`QUOTA_RPD`/`QUOTA_TPD`）。

**注意顺序敏感**：`wrangler deploy` 完成的那一刻起，没有登录令牌的请求一律 401，所以部署后要先登记名单（第 4 步）再测试。逐步说明见 [docs/03-Worker部署指南.md](docs/03-Worker部署指南.md)。

### 3. 等 DNS/证书生效，验证健康检查

`routes` 里的 `custom_domain: true` 会在部署后自动建 DNS 记录和 TLS 证书，通常几分钟内生效（部署前 `gemini.smjtools.com` 是 NXDOMAIN，这是预期状态，不是故障）。

```powershell
curl https://gemini.smjtools.com/healthz
```

### 4. 登记名单，自己先登录一次

真实名单在 `gemini-relay\scripts\roster.csv`（四列必填 `email,name,dept,role`，三列选填 `rpm,rpd,tpd` 用来覆盖限额）。这个文件**不进 git**——本仓库是公开 fork，同事的姓名和私人邮箱只留在管理员本机；仓库里只有占位用的 `roster.example.csv`。

```powershell
cd ..\..
.\gemini-relay\scripts\roster.ps1 -Import      # 从 CSV 批量登记
.\gemini-relay\scripts\roster.ps1 -AccessList  # 打印该贴进 Access 策略的邮箱列表
```

然后打开 openworker，**设置 ▸ 模型 ▸ Gemini ▸ 登录**，走一遍浏览器验证码流程。登录成功后跑冒烟测试（它会自动从本机 secrets.json 里读刚拿到的令牌）：

```powershell
& "C:\Users\liude\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" gemini-relay\scripts\test_relay.py
```

### 5. 分发 openworker

同事拿到 openworker 之后要做两件事，都在 **设置 ▸ 模型 ▸ Gemini** 这一页：点「登录」用公司邮箱收验证码，再填上你发给他的 Gemini API key。不需要设环境变量、不需要跑任何脚本。名单维护（加人/删人/调额度/查用量）见 [docs/07-多用户与用量统计.md](docs/07-多用户与用量统计.md)。

> 遗留脚本说明：`scripts\set-relay-env.ps1` 和 `scripts\start-openworker-cn.ps1` 是 v1 时代靠环境变量接线的产物，v2 起已不需要。保留仅作调试用途——它们设置的 `GOOGLE_GEMINI_BASE_URL` 现在是**优先级高于内置常量的调试覆盖**，设了会盖住代码里的默认值，排错前记得清理（`set-relay-env.ps1 -Uninstall`）。

## 文档索引

按角色分的四本手册在 [docs/手册/](../docs/手册/)（管理员初始化 / 运维 / 用户 / Cloudflare AI Gateway）。下面这些是深度文档：

| 文档 | 内容 |
| --- | --- |
| [docs/01-背景与结论.md](docs/01-背景与结论.md) | 问题回顾（400 FAILED_PRECONDITION 实测、v2rayN 现状）、v1 研究结论记录、与正向代理方案的对比 |
| [docs/02-架构设计.md](docs/02-架构设计.md) | 设计目标与约束、请求生命周期（含登录、准入、SSE、用量记录）、方案对比表（A/B/C/D）、Worker 设计决策逐条 |
| [docs/03-Worker部署指南.md](docs/03-Worker部署指南.md) | 部署步骤（含 KV 名单、D1 用量库与限额表的创建）、免费额度对照表、更新与回滚 |
| [docs/04-OpenWorker接入.md](docs/04-OpenWorker接入.md) | v1 遗留：环境变量接线机制与四种接入方式。v2 起已把中转地址内置进 provider 代码，本篇的环境变量现为调试通道 |
| [docs/05-验证与排错.md](docs/05-验证与排错.md) | 五级验证阶梯（DNS→TLS→REST→SDK→端到端）、排错矩阵表（含登录失败、令牌失效、Bot 挑战、用量记录排错） |
| [docs/06-安全与风险.md](docs/06-安全与风险.md) | 信任边界、两把凭证各自的安全含义、限额闸门为什么这么设计、PII 边界（邮箱与姓名）、平台与合规风险 |
| [docs/07-多用户与用量统计.md](docs/07-多用户与用量统计.md) | 名单模型（加人/删人/调额度/令牌生命周期）、迁移顺序、限额闸门怎么看、用量报表（`usage_report.py` 与控制台 SQL）、数据保留 |
| **[docs/08-Access登录配置.md](docs/08-Access登录配置.md)** | **一次性配置手册：Zero Trust One-time PIN、只保护 `/login` 的 Access 应用、允许名单策略、AUD 与 team domain、限额默认值、Bot 挑战放行** |

## 两把凭证，各管一件事

每个请求同时带两样东西，拆开是有意的：

| 头 | 内容 | 谁消费 |
| --- | --- | --- |
| `Authorization: Bearer owr_...` | 登录令牌，只对本中转有效 | 中转自己，转发前剥掉 |
| `x-goog-api-key: AIza...` | **这个人专属的** Gemini key（管理员签发，以他名字命名） | Google，中转原样转发、不改不存 |

**为什么不合成一把。** 中转要能回答「这次调用是谁发的」——用于记账，也用于按人限额。如果凭证就是 Gemini key，那么换一把 key 就换了个身份，计数器归零，限额形同虚设。

**为什么 key 一人一把而不是全公司共享一把。** 共享一把的话，Google 那边只看得到一个总数，吊销任何人都要全员换 key，而且中转就得代持一个可以被一次性偷走的东西。一人一把命名 key 换来：Google 后台按 key 显示用量（一本独立于我们 D1 的第二本账）、删一把正好切断一个人、中转仍然什么都不存。

实现上：

1. **地址是内置的**：`coworker/providers/gemini_provider.py` 顶部有模块常量 `RELAY_BASE_URL = "https://gemini.smjtools.com"`，`_ensure_client()` 构造 `genai.Client` 时显式传 `http_options=types.HttpOptions(base_url=...)`——这是 google-genai SDK 优先级最高的一等入口，不依赖环境变量这种隐式接线。实际生效地址由 `resolve_base_url()` 按三级优先级解析：**profile 隐藏 `base_url` 覆盖** > **环境变量 `GOOGLE_GEMINI_BASE_URL`**（调试通道）> **内置常量**。
2. **登录令牌走 `HttpOptions.headers`**：`coworker/relay_auth.py` 走一遍「浏览器验证码 → 一次性 code + PKCE → 令牌」，存进 SecretStore 的 `provider:gemini.relay_token`。SDK 只有一个凭证槽（`api_key` → `x-goog-api-key`），而那个槽归 Google，所以令牌只能另走一个头。
3. **自己的 key 走 `api_key`**：也就是 provider 本来就读的位置（`resolve_api_key()`，env 优先，和 Anthropic/OpenAI 的约定一致）。中转把它原样转给 Google，不改、不存、不记日志。
4. **限额按邮箱算**：`worker/src/quota.ts`，计数器在 D1，桶按北京时间切。上限的解析顺序是「名单条目 → `wrangler.jsonc` 的 `QUOTA_*`」，`-1` 不限、`0` 停用。人能在应用里看到自己今天用了多少。
5. **中转不可用时不回退**直连上游，这是设计决定：`generativelanguage.googleapis.com` 在大陆本就不可达，回退只会把失败换一种更难排查的方式呈现。

范围说明：本方案只覆盖原生 Gemini provider（`coworker/providers/gemini_provider.py`）。Vertex 家族在 `vertex_provider.py` 里自建 `genai.Client(vertexai=True)`，读的是另一个环境变量 `GOOGLE_VERTEX_BASE_URL`，不受这里的改动影响，也不在本方案范围内。

## 回退

v3 中 openworker 的 Gemini 流量固定走中转，中转不可用时请求直接失败（无回退是设计决定，见上节第 4 条）。紧急调试时可以用 `GOOGLE_GEMINI_BASE_URL` 环境变量临时把请求指向别处（它的优先级高于内置常量），但注意：**登录令牌只对本中转有效**，指向别处就得配一个真的 Gemini key，而 `resolve_api_key()` 在已登录时会优先用令牌——所以调试前要先在应用里「退出登录」，环境变量里的 key 才会生效。大陆环境下指回 Google 直连还需要自行配合本地正向代理（v2rayN + proxy-guard，见 [docs/01-背景与结论.md](docs/01-背景与结论.md)）。排错步骤见 [docs/05-验证与排错.md](docs/05-验证与排错.md)。
