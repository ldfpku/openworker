# 03 · Worker 部署指南

> 本文讲解如何把 `worker/` 目录部署为 Cloudflare Worker（含 v2 新增的 KV 名册命名空间与 D1 用量数据库的创建），并绑定自定义域名 `gemini.smjtools.com`。首次部署或更新 Worker 代码时阅读本文。部署完成后请转到 [05-验证与排错.md](./05-验证与排错.md) 做端到端验证；名册维护与用量报表见 [07-多用户与用量统计.md](./07-多用户与用量统计.md)。

## 前置条件

- 一个 Cloudflare 账号，且能管理 `smjtools.com` 这个 zone。
- `smjtools.com` 已经在 Cloudflare 的 NS 上——本仓库撰写时用 `Resolve-DnsName smjtools.com -Type NS` 实测确认，返回的两条 NS 记录是 `norm.ns.cloudflare.com` 和 `georgia.ns.cloudflare.com`，证明该 zone 已经托管在 Cloudflare。同时 `gemini.smjtools.com` 当时还没有任何记录（`Resolve-DnsName gemini.smjtools.com` 返回 NXDOMAIN），apex `smjtools.com` 也只有 SOA、没有 A/AAAA/CNAME——也就是说这个子域名要靠下面的 Custom Domain 步骤从零建立。
- 本机已装 Node.js 和 npm。

## 部署步骤

1. 安装依赖：

   ```powershell
   cd gemini-relay\worker
   npm install
   ```

2. **先清掉本会话的代理环境变量**（proxy-guard/v2rayN 留下的 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 会让 wrangler 走本地代理发 API 请求——代理没在跑时直接 `fetch failed`，提示 "Proxy environment variables detected"。`api.cloudflare.com` 从大陆直连可达，部署不需要代理）：

   ```powershell
   Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:ALL_PROXY -ErrorAction SilentlyContinue
   ```

3. 登录 Cloudflare（会打开浏览器完成 OAuth）：

   ```powershell
   npx wrangler login
   ```

4. 创建 KV 名册命名空间（v2 的准入控制，存 `sha256(api key) → 邮箱`）：

   ```powershell
   npx wrangler kv namespace create ROSTER
   ```

   命令输出一个 `id`（32 位十六进制），把它填进 `worker/wrangler.jsonc` 的
   `kv_namespaces[0].id`，替换掉 `TODO-run-wrangler-kv-namespace-create` 占位符。

5. 创建 D1 用量数据库（v2 的按人用量流水）：

   ```powershell
   npx wrangler d1 create gemini_relay_usage
   ```

   命令输出一个 `database_id`（UUID），把它填进 `worker/wrangler.jsonc` 的
   `d1_databases[0].database_id`，替换掉 `TODO-run-wrangler-d1-create` 占位符
   （`database_name` 和 `migrations_dir` 已经写好，不用动）。

6. 应用 D1 迁移，建出 `usage` 表（schema 见 `worker/migrations/0001_init.sql`）：

   ```powershell
   npx wrangler d1 migrations apply gemini_relay_usage --remote
   ```

   `--remote` 作用于线上数据库，不是本地模拟存储——漏掉它的话线上表不存在，Worker 的
   用量写入会持续失败（`wrangler tail` 里可见报错，见 [05-验证与排错.md](./05-验证与排错.md)）。

7. 部署：

   ```powershell
   npx wrangler deploy
   ```

   `wrangler deploy` 依据 `wrangler.jsonc` 里的 `routes: [{ "pattern": "gemini.smjtools.com", "custom_domain": true }]` 创建/更新一个 **Custom Domain**。这是 Cloudflare 文档里专门为「Worker 本身就是源站」这种场景设计的绑定方式：只要写 `pattern` + `custom_domain: true`，Cloudflare 会自动创建 DNS 记录并签发 TLS 证书，不需要手工管理 DNS 或证书；这一点和 `routes`（Worker 作为中间件、后面还有另一个源站）是两码事，后者要求域名已有 DNS 记录。

   **从这一刻起，未登记的 key 一律 403**（v2 没有"先放行、后收紧"的过渡态），所以部署完的第一件事就是下一步——把自己的 key 登记进名册。

8. 登记自己的邮箱和 key（名册准入，详见 [07-多用户与用量统计.md](./07-多用户与用量统计.md)）：

   ```powershell
   ..\scripts\roster.ps1 -Add 自己的邮箱@example.com
   ```

   脚本会安全提示输入 key（不回显、不进命令历史），本地算 SHA-256 后只把哈希和邮箱写进 KV。

9. 去 Cloudflare 控制台确认 Custom Domain 状态变成 Active（写作时入口为 Workers & Pages → gemini-relay → Settings → Domains & Routes，具体位置可能随控制台改版变化）。DNS 记录创建加证书签发通常需要几分钟，不是瞬时生效。

10. 验证 DNS 已经指向 Worker：

    ```powershell
    Resolve-DnsName gemini.smjtools.com
    ```

    部署前这条命令会报 NXDOMAIN（见上文前置条件）；部署且 Custom Domain 变 Active 后应该能解析出 Cloudflare 的边缘 IP。

11. 验证健康检查：

    ```powershell
    curl.exe https://gemini.smjtools.com/healthz
    ```

    预期返回 `ok`（对应 `worker/src/index.ts` 里 `url.pathname === "/healthz"` 分支）。

## 准入控制：KV 名册（v2，取代已删除的 RELAY_TOKEN）

v1 的可选 `RELAY_TOKEN` 共享密钥机制在 v2 中已彻底移除——`worker/src/index.ts` 的 `Env` 接口里没有这个字段，也没有 `x-relay-token` 分支。准入控制现在由 KV 名册承担：Worker 对每个请求的 `x-goog-api-key` 做 SHA-256、查名册得邮箱，查不到直接 `403 unregistered key`。登记/吊销/key 轮换的操作流程、`roster.ps1` 的用法和名册模型的设计依据，见 [07-多用户与用量统计.md](./07-多用户与用量统计.md)。

如果还想进一步限流，可以在 Cloudflare 控制台的 Security → WAF 里给 `gemini.smjtools.com` 配置速率限制规则；具体阈值要按自己的实际调用量定，本规格没有验证过具体参数，仅作为可选建议列出。

## 免费额度对照表

Worker 走的是 Cloudflare Workers Free 计划，以下数值除注明外均来自 Cloudflare 官方文档：

| 额度项 | Free 计划数值 | 对中转的含义 |
| --- | --- | --- |
| 请求数 | 100,000 次/天（UTC 0 点重置，超限返回 Cloudflare 1027 错误页——1027 是 Cloudflare 错误码，不是 HTTP 状态码） | 10 人团队使用基本不会碰到 |
| CPU 时间 | 10ms/次调用（只算 JS 执行时间，不含等待上游响应的时间） | 客户端方向只转发头和流式转发 body；记录支路会解析 usageMetadata，但做了大 body 保护（≥1MB 尾部提取、单 SSE 事件 >4MB 跳过），没有单独做过基准测试 |
| 请求体大小 | 100MB | 覆盖 Gemini 的 inline_data 图片/PDF 场景绰绰有余 |
| 单次调用外部子请求数 | 50 个（另有 1,000 个 Cloudflare 内部子请求额度） | 一次 Gemini 调用 = Worker 发起 1 次 `fetch()` 到 `generativelanguage.googleapis.com` = 1 个外部子请求，远低于上限 |
| D1 写入（用量流水） | 100,000 行/天，总存储 5GB（2026-08 设计阶段查证） | 一次请求写一行；10 人规模远低于上限，5GB 免费额度够存多年流水，数据永久保留 |
| KV 读取（名册查询） | 免费计划额度内（具体数值未在本仓库单独核实） | 查询带 `cacheTtl: 300` 边缘缓存，绝大多数请求命中边缘、不触达 KV 中心存储 |

## 更新与回滚

- 改完 `worker/src/index.ts` 后重新 `npx wrangler deploy` 即可；重复执行只是再发一次相同版本，不会破坏已有配置。KV/D1 资源创建是一次性的，更新部署不需要重跑；新增迁移文件时才需要再跑一次 `wrangler d1 migrations apply`。
- 想回滚，去控制台 Deployments 列表选中旧版本重新激活，或者本地 `git checkout` 到旧版本源码后再 `wrangler deploy`。注意回滚到 v1 代码等于同时撤掉名册准入和用量记录。
- `npx wrangler tail` 可以看实时请求日志；`worker/src/index.ts` 不打印请求头、请求体或 API key——代码里唯一的日志输出是 D1 写入/记录支路失败时的 `console.error`（行内只有错误对象，没有请求内容），排查用量记录问题时正好用它，见 [05-验证与排错.md](./05-验证与排错.md)。

## 参考链接

- Custom Domains vs Routes：<https://developers.cloudflare.com/workers/configuration/routing/custom-domains/>、<https://developers.cloudflare.com/workers/configuration/routing/routes/>
- wrangler 配置语法：<https://developers.cloudflare.com/workers/wrangler/configuration/>
- 子请求额度变更日志：<https://developers.cloudflare.com/changelog/post/2026-02-11-subrequests-limit/>
- Workers 平台限制（CPU 时间、请求体大小等）：<https://developers.cloudflare.com/workers/platform/limits/>
- Workers 定价（Free 计划请求数）：<https://developers.cloudflare.com/workers/platform/pricing/>
- D1 定价与免费额度：<https://developers.cloudflare.com/d1/platform/pricing/>
- Workers KV 限制：<https://developers.cloudflare.com/kv/platform/limits/>
