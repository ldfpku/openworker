# 03 · Worker 部署指南

> 本文讲解如何把 `worker/` 目录部署为 Cloudflare Worker（含 KV 名单命名空间、D1 用量数据库和限额计数表的创建），并绑定自定义域名 `gemini.smjtools.com`。首次部署或更新 Worker 代码时阅读本文。这个 Worker **没有任何机密**——每个调用方带自己的 Gemini key，中转只转发。
>
> **先决条件（v3 新增）**：登录依赖 Cloudflare Access，那套一次性配置在 [08-Access登录配置.md](./08-Access登录配置.md)，**要在本文第 7 步 `wrangler deploy` 之前做完**。部署完成后转到 [05-验证与排错.md](./05-验证与排错.md) 做端到端验证；名单维护与用量报表见 [07-多用户与用量统计.md](./07-多用户与用量统计.md)。

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

4. 创建 KV 名单命名空间（准入控制，存 `u:<邮箱>` 名单条目和 `t:<令牌哈希>` 登录令牌）：

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

6. 应用 D1 迁移，建出 `usage` 和 `auth_events` 两张表（schema 见 `worker/migrations/`）：

   ```powershell
   npx wrangler d1 migrations apply gemini_relay_usage --remote
   ```

   `--remote` 作用于线上数据库，不是本地模拟存储——漏掉它的话线上表不存在，Worker 的
   用量写入会持续失败（`wrangler tail` 里可见报错，见 [05-验证与排错.md](./05-验证与排错.md)）。

7. 确认 `wrangler.jsonc` 的 `vars` 填好了。这一步不需要 `wrangler secret`——**这个 Worker
   一个机密都没有**：调用方各带各的 Gemini key，中转原样转发、不留存，所以没有需要保管
   或轮换的凭证。要填的是两个 Access 坐标加三个限额默认值：

   | 变量 | 说明 |
   | --- | --- |
   | `ACCESS_TEAM_DOMAIN` / `ACCESS_AUD` | 按 [08-Access登录配置.md](./08-Access登录配置.md) 取值；还是 `TODO-…` 的话登录路径会因为拿不到可验证的 Access 断言而一律 403 |
   | `QUOTA_RPM` / `QUOTA_RPD` / `QUOTA_TPD` | 每人每分钟请求数 / 每天请求数 / 每天 token 数的**默认**上限，名单里可以逐人覆盖（`-1` 不限，`0` 停用） |

   如果这个 Worker 之前部署过带共享 key 的版本，顺手清掉那个已经不再被读取的机密：
   `npx wrangler secret delete GEMINI_API_KEY`。

8. 部署：

   ```powershell
   npx wrangler deploy
   ```

   `wrangler deploy` 依据 `wrangler.jsonc` 里的 `routes: [{ "pattern": "gemini.smjtools.com", "custom_domain": true }]` 创建/更新一个 **Custom Domain**。这是 Cloudflare 文档里专门为「Worker 本身就是源站」这种场景设计的绑定方式：只要写 `pattern` + `custom_domain: true`，Cloudflare 会自动创建 DNS 记录并签发 TLS 证书，不需要手工管理 DNS 或证书；这一点和 `routes`（Worker 作为中间件、后面还有另一个源站）是两码事，后者要求域名已有 DNS 记录。

   **从这一刻起，没有登录令牌的请求一律 401**（没有"先放行、后收紧"的过渡态；从 v2 升级的话，各人原有的 Gemini API key 在这一刻同时作废），所以部署完的第一件事就是下一步——把名单登记上去，然后自己先登录一次。

9. 登记名单（详见 [07-多用户与用量统计.md](./07-多用户与用量统计.md)）。真实名单在 `gemini-relay/scripts/roster.csv`（四列 `email,name,dept,role`），这个文件不进 git——本仓库是公开 fork，仓库里只有占位用的 `roster.example.csv`：

   ```powershell
   ..\scripts\roster.ps1 -Import
   ..\scripts\roster.ps1 -AccessList
   ```

   `-Import` 幂等，改完 CSV 重跑即可；`-AccessList` 打印该贴进 Access 策略 Include ▸ Emails
   的邮箱列表——**两边都加上人才算数**（KV 名单决定能不能换到令牌，Access 策略决定能不能
   收到验证码）。这一步不再需要任何人的 Gemini API key。

10. 去 Cloudflare 控制台确认 Custom Domain 状态变成 Active（写作时入口为 Workers & Pages → gemini-relay → Settings → Domains & Routes，具体位置可能随控制台改版变化）。DNS 记录创建加证书签发通常需要几分钟，不是瞬时生效。

11. 验证 DNS 已经指向 Worker：

    ```powershell
    Resolve-DnsName gemini.smjtools.com
    ```

    部署前这条命令会报 NXDOMAIN（见上文前置条件）；部署且 Custom Domain 变 Active 后应该能解析出 Cloudflare 的边缘 IP。

12. 验证健康检查，以及三条路径各自的准入状态：

    ```powershell
    curl.exe https://gemini.smjtools.com/healthz          # ok —— 公开
    curl.exe -i https://gemini.smjtools.com/v1beta/models # 401 —— 公开但要令牌
    curl.exe -i https://gemini.smjtools.com/login/x       # 302 到 Cloudflare 登录页 —— 被 Access 保护
    ```

    第一条对应 `worker/src/index.ts` 里 `url.pathname === "/healthz"` 分支。第三条如果返回
    200 或 404 而不是跳转，说明 Access 应用的 Path 没生效，回 [08-Access登录配置.md](./08-Access登录配置.md) 检查。

13. 最后在 openworker 里走一遍真登录：**设置 ▸ 模型 ▸ Gemini ▸ 登录**，然后跑冒烟测试
    （它会自动从本机 secrets.json 里读刚拿到的令牌）：

    ```powershell
    & "C:\Users\liude\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" gemini-relay\scripts\test_relay.py
    ```

## 准入控制：登录令牌（v3，取代 v2 的 key 哈希名册与 v1 的 RELAY_TOKEN）

两个旧机制都已彻底移除：`Env` 里既没有 `RELAY_TOKEN` 字段，代码里也没有 `k:<hash>` 名册分支。准入现在是四步：

1. 从 `Authorization: Bearer` 取登录令牌（**只认这一个头**），查 `t:<sha256(令牌)>` 得邮箱，
   再查 `u:<邮箱>` 确认还在名单里。令牌由 `/login` 路径签发，那条路径由 Cloudflare Access
   的一次性验证码守着。
2. 从 `x-goog-api-key`（其次 `?key=`）取**调用方自己的** Gemini key，没有就 400。
3. 按邮箱查限额闸门，超了就 429。
4. 剥掉 `Authorization` 再转发，`x-goog-api-key` 原样带过去。

配置侧要填的都在 `wrangler.jsonc` 的 `vars` 里，没有机密：

| 变量 | 怎么设 |
| --- | --- |
| `ACCESS_TEAM_DOMAIN` | Zero Trust 团队域名，形如 `https://<团队名>.cloudflareaccess.com` |
| `ACCESS_AUD` | Access 应用的 Application Audience (AUD) Tag |
| `QUOTA_RPM` / `QUOTA_RPD` / `QUOTA_TPD` | 限额默认值，名单里可逐人覆盖 |

前两个不是机密（团队域名出现在每次登录跳转里，AUD 出现在每个签发的令牌里），后三个是公开的规则本身——把「你每天有 1200 次」告诉适用的人正是重点。取值步骤和 Access 应用本身的建法见 [08-Access登录配置.md](./08-Access登录配置.md)；名单操作和设计依据见 [07-多用户与用量统计.md](./07-多用户与用量统计.md)。

Worker 里的闸门按**人**限流。如果还想再按**来源 IP** 加一层（两者互补），可以在 Cloudflare 控制台的 Security → WAF 里给 `gemini.smjtools.com` 配置速率限制规则；具体阈值要按自己的实际调用量定，本规格没有验证过具体参数，仅作为可选建议列出。

## 免费额度对照表

Worker 走的是 Cloudflare Workers Free 计划，以下数值除注明外均来自 Cloudflare 官方文档：

| 额度项 | Free 计划数值 | 对中转的含义 |
| --- | --- | --- |
| 请求数 | 100,000 次/天（UTC 0 点重置，超限返回 Cloudflare 1027 错误页——1027 是 Cloudflare 错误码，不是 HTTP 状态码） | 10 人团队使用基本不会碰到 |
| CPU 时间 | 10ms/次调用（只算 JS 执行时间，不含等待上游响应的时间） | 客户端方向只转发头和流式转发 body；记录支路会解析 usageMetadata，但做了大 body 保护（≥1MB 尾部提取、单 SSE 事件 >4MB 跳过），没有单独做过基准测试 |
| 请求体大小 | 100MB | 覆盖 Gemini 的 inline_data 图片/PDF 场景绰绰有余 |
| 单次调用外部子请求数 | 50 个（另有 1,000 个 Cloudflare 内部子请求额度） | 一次 Gemini 调用 = Worker 发起 1 次 `fetch()` 到 `generativelanguage.googleapis.com` = 1 个外部子请求，远低于上限 |
| D1 写入（用量流水） | 100,000 行/天，总存储 5GB（2026-08 设计阶段查证） | 一次请求写一行；10 人规模远低于上限，5GB 免费额度够存多年流水，数据永久保留 |
| KV 读取（令牌 + 名单查询） | 免费计划额度内（具体数值未在本仓库单独核实） | 每个请求两次读（`t:` 然后 `u:`），都带 `cacheTtl: 300` 边缘缓存，绝大多数请求命中边缘、不触达 KV 中心存储 |

## 更新与回滚

- 改完 `worker/src/index.ts` 后重新 `npx wrangler deploy` 即可；重复执行只是再发一次相同版本，不会破坏已有配置。KV/D1 资源创建是一次性的，更新部署不需要重跑；新增迁移文件时才需要再跑一次 `wrangler d1 migrations apply`。
- 想回滚，去控制台 Deployments 列表选中旧版本重新激活，或者本地 `git checkout` 到旧版本源码后再 `wrangler deploy`。注意版本之间准入机制不同：回滚到 v2 代码，同事手上的登录令牌会全部失效、要改回各人自己的 API key（而且要重新登记进 `k:` 名册）；回滚到 v1 等于同时撤掉准入和用量记录。D1 迁移不会自动回滚，多出来的列和表对旧代码无害。
- `npx wrangler tail` 可以看实时请求日志；`worker/src/index.ts` 不打印请求头、请求体或 API key——代码里唯一的日志输出是 D1 写入/记录支路失败时的 `console.error`（行内只有错误对象，没有请求内容），排查用量记录问题时正好用它，见 [05-验证与排错.md](./05-验证与排错.md)。

## 参考链接

- Custom Domains vs Routes：<https://developers.cloudflare.com/workers/configuration/routing/custom-domains/>、<https://developers.cloudflare.com/workers/configuration/routing/routes/>
- wrangler 配置语法：<https://developers.cloudflare.com/workers/wrangler/configuration/>
- 子请求额度变更日志：<https://developers.cloudflare.com/changelog/post/2026-02-11-subrequests-limit/>
- Workers 平台限制（CPU 时间、请求体大小等）：<https://developers.cloudflare.com/workers/platform/limits/>
- Workers 定价（Free 计划请求数）：<https://developers.cloudflare.com/workers/platform/pricing/>
- D1 定价与免费额度：<https://developers.cloudflare.com/d1/platform/pricing/>
- Workers KV 限制：<https://developers.cloudflare.com/kv/platform/limits/>
