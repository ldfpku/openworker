# 08 · Cloudflare Access 登录配置

> 本文是什么：把 gemini-relay 的登录接到 Cloudflare Access「一次性验证码」（One-time PIN）上的一次性配置手册，管理员读。做完这一套，同事在 openworker 里点「登录」→ 收验证码 → 填码，再填上**你发给他的** Gemini API key，就能用。
>
> 名单本身怎么增删见 [07-多用户与用量统计.md](./07-多用户与用量统计.md)；这里只讲让登录跑起来的那一次配置。

## 一句话

登录解决「你是谁」，不解决「拿什么调 Google」。同事证明自己拥有某个**在允许名单里的邮箱**（Cloudflare 发一次性验证码到那个邮箱），Worker 才签发一个**只对本中转有效**的登录令牌；调用时他还要带上一把 Gemini API key——**由管理员在一个公司 Google 账号里为每个人单独签发、以他的名字命名**，中转原样转发给 Google，自己一把都不存。

这么拆的好处是限额闸门有意义了：额度按验证过的邮箱算，换一把 key 也重置不了计数器。而 key 一人一把且带名字，Google 后台的按 key 用量就成了一本独立的第二本账。所以配置分两半——本文配登录，限额默认值在 `wrangler.jsonc` 的 `QUOTA_*`、每人的覆盖值在名单 CSV 里（步骤 5）。

## 请求流

```
openworker 桌面端
   │  ① POST /auth/session {callback, challenge}        ← 公开路径，不过 Access
   │     → {sid, login_url}
   │  ② 打开系统浏览器 → https://gemini.smjtools.com/login/<sid>
   ▼
Cloudflare Access（One-time PIN）                        ← 只保护 /login 这一条路径
   │  同事填邮箱 → Cloudflare 发验证码 → 填码 → 放行
   │  放行后才把请求交给 Worker，并带上签名过的 cf-access-jwt-assertion
   ▼
Worker /login/<sid>
   │  校验 Access JWT（JWKS 验签 + iss + aud）→ 拿到 email
   │  查 KV 名单 u:<email> → 不在名单就 403（Access 和 KV 是两道闸）
   │  签发一次性 code，302 回 http://127.0.0.1:<port>/relay/callback
   ▼
openworker
   │  ③ POST /auth/token {code, verifier}                ← 公开路径，不过 Access
   │     → {token: "owr_…", email, name, dept, role}
   │  把令牌存进本机 secrets.json 的 provider:gemini.relay_token
   ▼
后续每次 Gemini 调用，两个头一起走
      authorization:  Bearer owr_…   → Worker 查令牌得邮箱 → 查限额 → 剥掉这个头
      x-goog-api-key: AIza…（他自己的）→ 原样转给上游
```

为什么参数用路径里的 `sid` 带、而不是 query string：Cloudflare Access 做路径匹配时**不看 query string**，登录跳转过程中也可能把它改写掉，所以任何关键参数都不能挂在 query 上过 Access 这道闸。

为什么已经是回环地址了还要 PKCE：本机上任何进程都能抢先占住那个回环端口。把 code 绑到 `sha256(verifier)` 上，只有真正发起这次登录的那个 openworker 进程能兑换。

## 前置

- `smjtools.com` 已经在 Cloudflare 上（v2 就已满足）。
- 已经开通 Cloudflare Zero Trust（免费方案就够，本名单 12 人；席位上限以 [Cloudflare 定价页](https://www.cloudflare.com/plans/zero-trust-services/) 当前口径为准）。
- 记下你的 **team domain**：`https://<团队名>.cloudflareaccess.com`。团队名在 Zero Trust ▸ Settings 里。

> Cloudflare 会不定期改 Zero Trust 控制台的分区名字。下面写的路径是本文成稿时的叫法，找不到的时候按关键词（One-time PIN / Applications / Application Audience）搜一下控制台即可。

## 只能在控制台做（`wrangler login` 的令牌不够）

步骤 1–3 必须在 Zero Trust 控制台点，**不能用 API 脚本代替**。2026-08-23 实测：
`wrangler login` 拿到的 OAuth 令牌可以**读** Access 接口（`GET /access/apps`、
`GET /access/identity_providers` 都返回 200），但任何**写**操作一律

```json
{"code": 1010, "error": "auth.forbidden"}
```

建身份源、建应用都一样。注意这个错误**没有 message 字段**，光看 code 容易误判成参数校验
错误——判断依据是 `error` 那一项写着 `auth.forbidden`。`GET /access/organizations` 更直接，
回的是 `10000 Authentication error`。

想脚本化的话得自己在控制台建一个带 **Account ▸ Cloudflare One (Zero Trust) ▸ Edit** 权限的
API Token。为了三个只做一次的对象去建一个长期有效的高权限令牌，不划算——直接点完更省事。

控制台做完之后，把两个值交给收尾脚本，它会填配置、部署、跑验证：

```powershell
.\gemini-relay\scripts\finish_access.ps1 -TeamDomain 你的团队名 -Aud <64位十六进制>
```

## 步骤 1：打开 One-time PIN 登录方式

Zero Trust ▸ **Integrations ▸ Identity providers** ▸ Add new ▸ **One-time PIN**。

不需要接任何 IdP。验证码由 Cloudflare 直接发到邮箱，**10 分钟过期、只能用一次**，重新申请会让上一封作废。

## 步骤 2：建一个自托管 Access 应用，**只**保护 `/login`

Zero Trust ▸ **Access controls ▸ Applications** ▸ Add an application ▸ **Self-hosted**。

| 字段 | 值 |
| --- | --- |
| Application name | `gemini-relay-login` |
| Session Duration | 24 小时（够长，令牌本身有自己的 30 天有效期） |
| Subdomain | `gemini` |
| Domain | `smjtools.com` |
| **Path** | **`login/*`** |

**Path 一定要填 `login/*`，那个星号不能少。** Cloudflare 的
[Application paths](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/)
说得很明确：不带通配符的 Path 是**精确匹配**。填 `login` 只会保护 `/login` 这一个 URL，
而我们真正需要保护的是 `/login/<sid>`——那才是签发一次性授权码的地方。

填错的后果还特别不好查：Access 根本不介入 `/login/<sid>`，于是没有 `cf-access-jwt-assertion`
头，Worker 验签失败，同事看到的是「身份校验没通过」，而控制台里一切看起来都正常。

反过来，通配符**不覆盖父路径**，所以 `/login`（不带 sid）不受保护。这没问题：那个 URL 只会
返回一句「请从 OpenWorker 里发起登录」的提示页，不签发任何东西。

`/auth/*`、`/v1beta/*`、`/healthz` 都不在 `/login/` 底下，保持公开——这正是我们要的：

- `/login/*` 是**浏览器**流量，需要 Access 拦下来做验证码。
- `/v1beta/*` 是 google-genai SDK 发的**程序化**流量。要是它也被 Access 保护，SDK 会收到一个 302 到登录页，然后以各种难懂的方式失败。
- `/auth/session`、`/auth/token` 同理，是 openworker 后台直接调的，没有浏览器去过验证码。

这三条路径的准入不靠 Access，靠 Worker 自己：`/v1beta/*` 要令牌，`/auth/token` 要一次性 code + PKCE verifier。

## 步骤 3：策略就是允许名单

在这个应用里 Add a policy：

| 字段 | 值 |
| --- | --- |
| Policy name | `roster` |
| Action | **Allow** |
| Include | Selector = **Emails**，把名单里的邮箱一个个加进去 |

要贴的邮箱列表可以直接从 KV 名单生成，不用手抄：

```powershell
.\gemini-relay\scripts\roster.ps1 -AccessList
```

> Access 策略是**默认拒绝**的：没有命中 Allow 的邮箱收不到验证码，登录页也过不去。

> ⚠️ **一个邮箱一条 Include 规则，不要拼成逗号串。**
> `Emails` 选择器精确匹配**单个**地址。把 `a@x.com, b@y.com, …` 整串粘进同一个框，Cloudflare 会
> 原样存成一个谁都匹配不上的字面值 —— 全员收不到验证码，**而且不报任何错**：登录页照样显示
> 「A code has been emailed to you」。这是[官方行为](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)：
> 被拒的用户不会收到邮件，页面文案不变。

控制台会把多条规则渲染成一行逗号列表，肉眼分不出对错，所以配完**用 API 核一遍** `include` 的形状
（`GET /accounts/{account_id}/access/apps/{app_id}/policies`）：

```jsonc
// 对：一个邮箱一个对象
"include": [ { "email": { "email": "a@x.com" } }, { "email": { "email": "b@y.com" } } ]

// 错：一个对象塞了一整串 —— 这条规则谁都匹配不上，等于名单是空的
"include": [ { "email": { "email": "a@x.com, b@y.com" } } ]
```

## 步骤 3.5：给登录页挂上公司 logo（可选但建议）

同事真正会盯着看的页面是 Cloudflare 的验证码登录页——默认长着 Cloudflare 的样子，没有
任何公司标识，收到验证码的人很容易怀疑是不是钓鱼。

Zero Trust ▸ **Settings ▸ Custom Pages ▸ Login page**（控制台改版后可能叫别的名字，按
「Custom Pages」或「Login page appearance」搜）里可以设 logo、背景色和页头文字：

| 字段 | 填什么 |
| --- | --- |
| Logo | `https://gemini.smjtools.com/brand/logo.png` |
| Background color | `#1F7A3C`（品牌绿；深绿 `#0A3A1B`、浅绿 `#58B96C` 见 `surfaces/gui/src/brand/README.md`） |

> **一定要用 `.png`，不能用 `.webp`。** Cloudflare 的 logo 字段校验文件扩展名，webp 直接被拒：
> `logo_url must match the following: "/[^]+(.png|.svg|.jpg|.jpeg)$/"`。它连图片都不会去取，
> 所以这不是"图挂了"而是"格式不收"。App Launcher 那个 logo 字段同样如此。

Logo 那一栏要的是 URL 而不是上传，所以 Worker 直接把品牌图片公开在 `/brand/` 下
（`worker/src/brand.ts`，同一份字节也内联在 Worker 自己的提示页里）。每个标记都有 webp 和
png 两份，**给 Cloudflare 填的一律用 png**：

```
https://gemini.smjtools.com/brand/logo.png         # 640x160 黑字，浅色底 —— 登录页用这个
https://gemini.smjtools.com/brand/logo-mark.png    # 256x256 方形 —— App Launcher 用这个
https://gemini.smjtools.com/brand/logo-dark.png    # 640x160 白字，深色底
https://gemini.smjtools.com/brand/favicon.png      # 64x64
```

（`.webp` 同名地址也在，体积更小，供我们自己的页面用。）

换 logo 的流程：替换 `surfaces/gui/src/brand/` 下的同名 webp，跑一次
`.venv\Scripts\python.exe gemini-relay\scripts\gen_brand_assets.py`——它会顺带把 png
转出来，不需要你自己维护第二套源文件——再 `wrangler deploy`。URL 不变，Access 那边不用动
（边缘缓存 1 天）。生成脚本需要 Pillow：
`uv pip install --python .venv/Scripts/python.exe pillow`。

## 步骤 4：把 team domain 和 AUD 填进 wrangler.jsonc

应用建好后，进 Configure ▸ **Additional settings**，复制 **Application Audience (AUD) Tag**。

编辑 `gemini-relay/worker/wrangler.jsonc`，替换两个 `TODO` 占位符：

```jsonc
"vars": {
    "ACCESS_TEAM_DOMAIN": "https://你的团队名.cloudflareaccess.com",
    "ACCESS_AUD": "刚复制的那串 AUD"
},
```

两个都不是机密（team domain 出现在每次登录跳转里，AUD 出现在每个签发的令牌里），所以放 `vars` 而不是 `wrangler secret`。

Worker 拿到请求后会用 `ACCESS_TEAM_DOMAIN + /cdn-cgi/access/certs` 上的公钥验签，并核对 `iss` 和 `aud`——**只看 header 存在与否是不够的**（Cloudflare 官方也这么要求）。这一步还顺带兜住了配置漂移：万一哪天 Access 应用被删了、或者 Path 被人从 `login` 改宽了，验签失败会让登录直接 403，而不是悄悄变成一个「谁填什么邮箱都认」的表单。

## 步骤 5：定限额（没有机密要放）

**这个 Worker 不需要任何 `wrangler secret`。** 没有共享 key，每个人带自己的——所以这一步只是定几个数字。

`worker/wrangler.jsonc` 的 `vars` 里三个默认值，按需要改：

```jsonc
"QUOTA_RPM": "30",        // 每分钟请求数：防自动循环跑飞用的，别调太高
"QUOTA_RPD": "1200",      // 每天请求数
"QUOTA_TPD": "5000000"    // 每天 token 数
```

要给某个人开小灶，写进 `scripts\roster.csv` 的 `rpm,rpd,tpd` 三列（留空=用上面的默认值，`-1`=不限，`0`=停用）。示例文件里已经把管理员和总经理设成日上限不限、rpm 保留默认——**rpm 那道闸不建议对任何人关掉**，它拦的是失控循环，不是省钱。

三档各自的用意和「为什么读失败时放行」的取舍见 [06-安全与风险.md](./06-安全与风险.md)。

> 如果这个 Worker 之前部署过带共享 key 的版本，顺手清掉那个已经不再被读取的机密：
> `npx wrangler secret delete GEMINI_API_KEY`。

## 步骤 6：建表、登记名单、部署

```powershell
cd gemini-relay\worker
npm install                                                     # jose 依赖（验 Access JWT）
npx wrangler d1 migrations apply gemini_relay_usage --remote     # 0002_login.sql + 0003_quota.sql
npx wrangler deploy
cd ..\..
.\gemini-relay\scripts\roster.ps1 -Import                        # 从 scripts\roster.csv 批量登记
```

`deploy` 会一并注册每天 03:17 UTC（北京时间 11:17）的定时任务，用来清理三天前的限额计数桶——不用单独配置，`wrangler.jsonc` 里的 `triggers.crons` 就是它。

**顺序敏感**：`wrangler deploy` 生效那一刻起，旧版客户端全部失效——它们把登录令牌塞在 `x-goog-api-key` 里，现在那个位置要的是真 key，会收到一条「客户端版本过旧」的 400。所以部署完要马上 `-Import`，自己先登录一次验证，再让同事升级客户端。

## 步骤 7：告诉同事要做两件事

登录之后应用里会显示「还差一步：填 Gemini API key」，但最好提前说清楚，免得有人卡在这儿：

1. **登录**：设置 ▸ 模型 ▸ Gemini ▸ 用工作邮箱收验证码。
2. **填你发给他的 key**：一对一给（别群发），填进同一个页面下方的 API key 输入框。

两件都做完，那一栏才会真正可用。只做第一件的话，第一条消息会收到一条中文的 400，明确告诉他缺哪一半。

给 key 的时候连着说三句：这是公司的凭证不是他的；别转给别人别贴群里；泄露了第一时间说，
换一把是几分钟的事、不追究。第三句最要紧——瞒着不报才是真会出事的情形。

## 别忘了：Bot 挑战要放行

zone 上的 Bot Fight Mode / Super Bot Fight Mode 会把 openworker 这种非浏览器的程序化请求判成可疑流量，返回一整页 `Just a moment...` 的挑战 HTML 而不是 Worker 的响应——请求根本到不了 Worker。`/login/*` 是真浏览器，不受影响；**`/auth/*` 和 `/v1beta/*` 会被打死**。

排查特征和具体放行做法（Security ▸ Bots 关掉，或建一条 `Hostname equals gemini.smjtools.com` 的 Skip 规则）见 [05-验证与排错.md](./05-验证与排错.md) 排错矩阵里对应的那一行。

## 验证

```powershell
curl https://gemini.smjtools.com/healthz                      # ok（公开）
curl -i https://gemini.smjtools.com/v1beta/models             # 401 UNAUTHENTICATED（公开但要登录令牌）
curl -i https://gemini.smjtools.com/login/whatever            # 302 到 Cloudflare 登录页（被 Access 保护）
```

登录之后还可以直接问中转「我是谁、今天用了多少」：

```powershell
curl -H "authorization: Bearer $env:OPENWORKER_RELAY_TOKEN" https://gemini.smjtools.com/auth/whoami
```

返回里的 `quota.limits` 是解析后的最终上限（名单覆盖值 → `QUOTA_*` 默认值），`quota.used` 是今天（北京时间）已用的量。

第三条要是返回 200 或者 404 而不是跳转，说明 Access 应用的 Path 没生效——回步骤 2 检查。

然后在 openworker 里走一遍真流程：设置 ▸ 模型 ▸ Gemini ▸ 登录 → 浏览器收码 → 填码 → 应用里显示「✓ 已登录 + 姓名/部门」。最后跑冒烟测试：

```powershell
& "C:\Users\liude\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" gemini-relay\scripts\test_relay.py
```

它会自动从 openworker 的 secrets.json 里拿刚才登录得到的令牌。

## 名单变更：两边都要动

| 操作 | KV 名单（`roster.ps1`） | Access 策略（控制台） |
| --- | --- | --- |
| 加人 | `-Import` 或 `-Add` | 把邮箱加进 Include ▸ Emails |
| 删人 | `-Remove` | 从 Include ▸ Emails 里删掉 |
| 改额度 | `-Add <同一个邮箱> -Rpd 3000`（重复登记即覆盖） | 不用动 |
| 临时停用 | `-Add <同一个邮箱> -Rpd 0` | 不用动 |

改额度和停用只碰左边一列——这正是把停用做成 `0` 而不是删人的原因：不用动 Access 策略，也就不会留下「删了一半」的状态。

两道闸各管一段，所以只动一边会得到两种不同的半通状态：

- **只加 Access、没加 KV**：能收到验证码、能过登录页，但换不到令牌，看到「这个邮箱不在允许名单里」。
- **只加 KV、没加 Access**：连验证码都收不到。
- **只删 KV、没删 Access**（最常见的疏漏）：他名下的令牌 5 分钟内全部失效，实际已经用不了了——但他仍然能收到验证码走到登录页。**这不是安全漏洞**（拿不到令牌就调不了 Gemini），只是体验上会让人困惑。

`roster.ps1` 每次写完名单都会把该同步的邮箱列表打出来提醒你。

## 常见问题

**同事说没收到验证码。** 先确认邮箱在 Access 策略的 Include 列表里——被拒的人**不会**收到邮件，但登录页仍然显示「验证码已发送」（Cloudflare 故意不泄露谁在名单里）。其次看垃圾箱：名单里有几个 QQ 邮箱。

**验证码填进去说「已被使用」。** 企业邮箱的安全网关会先替用户点一遍邮件里的链接，把一次性码消费掉。让同事改用「手动输入 6 位码」而不是点链接；实在不行换一个邮箱。

**登录成功但应用里还是「未登录」。** 浏览器回跳的是 `http://127.0.0.1:<端口>/relay/callback`，端口是桌面端启动时随机绑的。如果本机装了拦截回环请求的安全软件，这一跳会失败。看那个标签页停在什么页面——OpenWorker 的成功卡片说明回跳到位了。

**换了台电脑要重新登录吗。** 要。令牌是按设备存的（存在本机 `secrets.json` 里），一人可以同时在多台设备登录，`roster.ps1 -List` 会显示当前活跃令牌总数。

**令牌多久过期。** 30 天，过期后应用会提示重新登录。管理员 `-Remove` 一个人，他所有设备上的令牌最多 5 分钟内失效（KV 边缘缓存 TTL）。

**同事没有 Gemini API key 怎么办。** 你给他。在 https://aistudio.google.com/apikey 用公司 Google 账号 Create API key，**改名成他的名字**（和名单里的 `name` 一致），一对一发给他。中转不代持任何 key——它只在转发的瞬间经手，不存储，所以这边没有一个可以被一次性偷走的凭证集合。

**为什么不让每个人自己申请。** 名单里多数同事没有能用的 Google 账号，也不该为这件事去折腾一个；而且各自申请的话，Google 侧就没有一本能对上人的账。一人一把命名 key 换来的是：Google 后台按 key 看得到谁花了多少，吊销一把正好切断一个人。

**有人可能拿 key 绕过中转直接调 Google 吗。** 可以，中转拦不住——限额闸门在中转里，那条路不经过它。约束是可见性：key 带名字，Google 用量页显示是哪一把在花钱。每月拿 Google 的数字和 `usage_report.py` 的数字对一遍，明显对不上就是这件事。

**改完额度多久生效。** 立刻。上限是每次请求现查名单的（KV 带 5 分钟边缘缓存，所以最长 5 分钟），计数器本身在 D1 里实时读写。

**有人说被 429 了，但他今天没用几次。** 先看是哪一档：错误文案会写明是每分钟还是每天。每分钟那档很容易在一次带工具调用的复杂任务里撞上（一轮 agent 循环十几次请求是常态），这时候要么等一分钟，要么把他的 rpm 调高一点。用 `usage_report.py --quota` 看当天的实际读数，`peak_per_min` 那列能直接告诉你他今天最高峰打了多少。

**同事的额度还剩多少，他自己看得到吗。** 看得到。设置 ▸ 模型 ▸ Gemini 的登录卡片上有一行「今日 12/1200 次请求 · 34k/5M tokens」，用到 90% 会变红。不想让人撞墙才知道有墙。
