# Cloudflare AI Gateway 手册

> **读者**：管理员（配置那一次）和所有使用者（登录那一步）。
> **什么时候读**：想用 GPT / Claude / Gemini 而不想自己配 API key 的时候。
> **同事要准备什么**：工作邮箱。没了。

---

## 0 · 它和 Gemini 中转是两回事

| | Gemini 中转（`gemini.smjtools.com`） | AI Gateway（`gateway.smjtools.com`） |
| --- | --- | --- |
| 覆盖哪些模型 | 只有 Gemini，但是全系 | GPT、Claude、Gemini（3.x 的一部分） |
| 同事要几样凭证 | 两样：登录 + 他自己那把 Gemini key | 一样：登录 |
| 谁付钱 | 公司的 Google 账号 | 公司 Cloudflare 账号的预付额度 |
| 按人统计 | 我们自己写的记账表 | Cloudflare 的「用户洞察」，Access 自动带身份 |
| 我们写了多少代码 | 一整个 Worker（认人 / 转发 / 记账 / 限额） | 零。Cloudflare 自己就是那个 Worker |

**为什么两边都有 Gemini**：中转那条是给有个人优惠的人用的，也更全；网关这条统一计费只覆盖
Gemini 3.x 的一部分（见第 3 节）。模型选择器里两条都在，标签结尾不一样——
`· Google` 是直连，`· via Cloudflare` 是网关。

---

## 1 · 管理员：一次性配置

同事一侧的「零配置」，代价是管理员这边要把下面五件都做完。做完之后加人只是往 Access
策略里加一个邮箱。

### 1.1 网关和自定义域

Cloudflare 控制台 ▸ **AI** ▸ **AI Gateway** ▸ Create Gateway，名字 **`openworker-agw`**。

然后在这个网关的 **域名** 页 ▸ **Add Domain**，挂一个自己 zone 上的子域，
例如 `gateway.smjtools.com`。**自定义域不是可选项**，是整套方案的地基：
Access 只能保护自己 zone 上的主机名，而 Access 是这里唯一的认证方式。

建议开的：

| 设置 | 值 | 为什么 |
| --- | --- | --- |
| Logs | 开 | 谁在什么时候调了什么模型，只能靠它 |
| Rate limiting | `100 / 60s` | 有人的自动循环跑飞时的兜底 |
| 成本限制 | 按人头设 | 见 6.2 |
| 缓存 | **调试期关掉** | 见下面的警告 |

> **缓存会把排查引到沟里。** 开着缓存时，同样的请求第二次直接返回上一次的答案，日志里
> `cached: true`、成本 0、输出 0 token。探测一个模型能不能用时这会给出假的成功。
> 排查期间要么关掉，要么每个请求带 `cf-aig-skip-cache: true`。

### 1.2 充值

**AI** ▸ **AI Gateway** ▸ **Billing** 加信用卡并充值。第三方模型走 Unified Billing
（统一计费）：从这个余额扣，**不需要给每家厂商配 key**。买额度时收 5% 手续费，
推理单价与直连各家一致、无加价。

### 1.3 Access 应用

网关的 **Access** 页会引导你给这个域名建一个 Access 应用，或者去
**Zero Trust ▸ Access controls ▸ Applications** 建一个 self-hosted 应用，
目标填 `gateway.smjtools.com`，策略挂公司的员工邮箱名单。

这一步之后，**同事就不需要任何 Cloudflare API token 了**。官方文档的原话：

> The client does not need to send an AI Gateway token for that request.

Access 通过之后，网关会把登录者的身份写进请求元数据（`cf.user_id`），
「用户洞察」和按人预算就是靠它，客户端一个字都不用传。

### 1.4 打开动态客户端注册

**不做这一步，同事那边的「登录」按钮就是废的**——注册端点会一直返回 404，浏览器转个
不停，而且报错完全指不到这里。

这一步分两半：能在控制台点的，和**只能走 API** 的。

**先在控制台点：Zero Trust ▸ Access controls ▸ Applications ▸ 该应用 ▸ 右侧三个点 ▸
Edit ▸ 其他设置**（中文界面把 Advanced settings 译成「其他设置」，是顶部那个标签，
不是下面「全部 / 目标 / 策略 …」那排筛选条）**▸ 托管 OAuth**：

| 开关 | 设成 | 为什么 |
| --- | --- | --- |
| 托管 OAuth | 开 | 桌面端要走 OAuth，不是浏览器 Cookie |
| 允许 localhost 客户端 | 开 | 桌面应用的回调落在 `localhost` |
| 允许回环客户端 | 开 | 同上，`127.0.0.1` |
| 允许的重定向 URI | **留空** | 见下 |
| 访问令牌有效期 | `15 minutes` | 短命令牌 + 自动续期，Cloudflare 对 CLI 的推荐 |
| 授权会话持续时间 | 下拉框里最接近两周的一档 | 见下 |

> **Allowed redirect URIs 留空。** 桌面应用每次回调用的是随机端口，写死一个 URI 不管用；
> 而 localhost / loopback 两个开关就是为这个场景准备的。
> 尤其**不要**把 `https://playground.ai.cloudflare.com/*` 加进去——那等于允许
> Cloudflare 的公开 playground 替你的网关拿令牌。官方文档的示例里有这一行，别照抄。

**然后必须走一次 API。** 控制台**不暴露** `dynamic_client_registration.enabled`
这个字段——上面那些开关只写了 `allow_any_on_localhost` / `allow_any_on_loopback`，
主开关仍是 `false`，注册端点会一直返回 `404`。这一步只能用 API 补。

Access 应用只有 `PUT`，没有 `PATCH`，而 **`PUT` 是整体替换**：
body 必须带上 `GET` 回来的所有字段。**尤其是 `policies`——漏了它，应用就没有 Allow
策略了，默认拒绝，所有人（包括你自己）当场被锁在外面。**

```bash
curl "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/apps/$APP_ID" \
  --request GET --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
```

把上面 `GET` 到的字段原样填进 `PUT`，只改 `oauth_configuration`：

```json
{
  "oauth_configuration": {
    "enabled": true,
    "dynamic_client_registration": {
      "enabled": true,
      "allow_any_on_localhost": true,
      "allow_any_on_loopback": true
    },
    "grant": { "session_duration": "336h", "access_token_lifetime": "15m" }
  }
}
```

token 需要 `Access: Apps and Policies Write` 权限（AI Gateway 作用域的 token 用不了）。

顺带一提：`336h`（两周）在控制台下拉框里通常没有这一档，但 API 接受任意时长。
Cloudflare 对 CLI / agent 场景的建议就是 1–2 周。

验证——注册端点该从 `404` 变成 `201` 并带回一个 `client_id`：

```bash
curl -s -w "\n%{http_code}\n" -X POST \
  "https://<团队名>.cloudflareaccess.com/cdn-cgi/access/oauth/registration" \
  -H "Content-Type: application/json" \
  -d '{"client_name":"probe","redirect_uris":["http://localhost:53682/callback"],
       "grant_types":["authorization_code","refresh_token"],
       "response_types":["code"],"token_endpoint_auth_method":"none"}'
```

> 这个探测会**真的注册出一个客户端**，而且 Cloudflare 没有列出或删除已注册客户端的 API，
> 删不掉。它是公共客户端，没人走浏览器授权就什么也做不了，但心里有数。

改完记得确认 `aud` 没变——变了的话所有已签发的 JWT 会一起失效。

### 1.5 给网关域名开「AI 机器人」例外

**这一条不做的话，用标准 SDK 的客户端一定连不上，而且报错完全指不到原因。**

OpenAI 和 Anthropic 的 Python SDK 默认 User-Agent 是 `OpenAI/Python 1.2.3` 这种形状，
正好命中 Cloudflare 的 AI 爬虫特征，请求在**边缘**就被打回
`403 Your request was blocked.`，Access、网关、模型统统还没轮到。

拦它的是 **Security ▸ Bots ▸ 阻止 AI 机器人**（zone 设置 `ai_bots_protection`），
既不是 WAF 托管规则集，也不是 Bot Fight Mode——认清这点很重要，因为
[Bot Fight Mode 不走规则引擎，Skip 对它无效](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/#rules)，
而 AI 机器人拦截走，能 Skip。两个特征可以认它：响应体是 25 字节纯文本
（不是 WAF 那张 HTML 拦截页），以及拿 `GPTBot/1.0` 试一下会跟 SDK 的 UA 一起被拦。

别关 zone 级的开关——同一个 zone 上通常还挂着真站点。只给网关域名开口子：

**Security ▸ Security rules ▸ Create rule ▸ Custom rules**

| 字段 | 值 |
| --- | --- |
| Rule name | `Skip AI-bot block for AI Gateway` |
| 表达式 | `(http.host eq "gateway.smjtools.com")` |
| 动作 | Skip ▸ **All Super Bot Fight Mode rules** |
| Place at | First |

只勾 Super Bot Fight Mode 这一项就够（AI 机器人拦截跑在 `http_request_sbfm` 阶段）。
别顺手把 `waf`、`rateLimit`、`bic` 一起跳了，网关用不着放这么宽。

验证：下面这条该从 `403` 变成 `401`。`401` 表示已经穿过边缘、到了 Access——
这个域名上 `401` 是正常的「还没给凭据」，不是错误。

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://gateway.smjtools.com/ -H "User-Agent: GPTBot/1.0"
```

顺带确认作用域没写宽：同 zone 的其它主机拿同样的 UA 试，应该**仍然**是 `403`。

应用这边同时也把 UA 改成了 `openworker/<版本>`，两道保险：规则万一被删客户端仍然能跑，
而且网关日志里的 UA 会直接告诉你请求是哪个客户端发的。

---

## 2 · 同事：填一个地址，点一次登录

不用装任何东西，不用申请任何密钥，不用粘贴任何字符串。

1. **设置 ▸ 模型 ▸ Cloudflare AI Gateway**
2. 「网关地址」填管理员给的域名，例如 `https://gateway.smjtools.com`。**只填主机名**，
   后面的路径应用自己会加
3. 点卡片上的 **登录**。浏览器会弹出来走一次公司的 Access 登录，登完那个标签页会自己
   显示「登录成功」，回到应用就已经是「✓ 已登录」了
4. 点 **测试**——它会真的调一次最便宜的模型（不到一厘钱），所以测试通过就等于真能用
5. 在上方的模型选择器里挑一个 `· via Cloudflare` 结尾的模型

登录之后就不用再管了：应用后台每 15 分钟悄悄续一次令牌，**两周**之内不会再问你。
续签的每一次 Cloudflare 都会重新核对你还在不在允许名单里——所以两周这个时长是安全的，
一个人离职或被移出名单，最迟下一次续签就失效。

> **登录按钮是灰的**，说明网关地址还没填。登录就是往那个地址去的，先填地址。

<details>
<summary>没有浏览器的机器（少数情况）</summary>

服务器、容器这类开不了浏览器的环境，还可以用旧办法：装一次
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)，

```bash
cloudflared access login https://gateway.smjtools.com
```

```bash
cloudflared access token -app=https://gateway.smjtools.com
```

把输出整串粘进「Access 会话」那个框。**这种会话每天都会失效**，失效后测试会报
「Access 会话无效」，得重跑第二条命令再粘一次。能登录就别用这条路。

两者同时存在时，应用优先用登录拿到的那个。
</details>

---

## 3 · 能用哪些模型

下表每一行都在 2026-08-23 通过 `gateway.smjtools.com` 真调过，带工具定义，返回 200。

| 模型 | 网关 id | 上下文 |
| --- | --- | --- |
| GPT-5.6 Sol | `openai/gpt-5.6-sol` | 400k |
| GPT-5.6 Terra | `openai/gpt-5.6-terra` | 400k |
| GPT-5.6 Luna | `openai/gpt-5.6-luna` | 400k |
| Claude Opus 5 | `anthropic/claude-opus-5` | — |
| Claude Sonnet 5 | `anthropic/claude-sonnet-5` | — |
| Claude Fable 5 | `anthropic/claude-fable-5` | 1M |
| Claude Haiku 4.5 | `anthropic/claude-haiku-4-5` | 200k |
| Gemini 3.6 Flash | `google-ai-studio/gemini-3.6-flash` | 1M |
| Gemini 3.1 Pro | `google-ai-studio/gemini-3.1-pro-preview` | 1M |
| Gemini 3.1 Flash-Lite | `google-ai-studio/gemini-3.1-flash-lite` | 1M |
| Gemini 3 Flash | `google-ai-studio/gemini-3-flash-preview` | 1M |

全部支持看图。PDF 走本地转图片的老路（`pdf_support.py`），能看图就能读 PDF。

Opus 5 和 Sonnet 5 的上下文留空，是因为没去核对厂商文档——宁可让界面上的上下文进度条
隐藏，也不编一个分母出来。

**Gemini 只有四个，而且比直连那条少。** 统一计费在网关这条路上只覆盖 Gemini 的一部分：
`gemini-3.7-flash`、`3.5-flash`、`3.5-flash-lite`、`3-flash`、`3.1-pro`（不带 `-preview`
的写法）都不覆盖。要全系 Gemini 就用直连那条（`· Google` 结尾的那些）。

---

## 4 · 模型 id 为什么长这样

`aigw:anthropic/claude-haiku-4-5` 拆成三段：

- `aigw:` —— 应用内部的路由前缀，选择器里看不到。
- `anthropic` —— **厂商段**。它决定用哪种请求格式，不只是个标签。
- `claude-haiku-4-5` —— **厂商自己的写法**。

第三段有个坑：Cloudflare 的 REST API 把这个模型叫 `claude-haiku-4.5`（点），
但自定义域这条路是把模型名**原样**转给厂商的，所以要用 Anthropic 自己的
`claude-haiku-4-5`（横杠）。写错了 Anthropic 会亲自提醒你：
`model: claude-sonnet-4.6 was not found. Did you mean claude-sonnet-4-6?`

厂商段决定的那件事——实测下来是三条线：

| 厂商段 | 走哪条 | 前缀 | 实测到的坑 |
| --- | --- | --- | --- |
| `anthropic/` | `…/anthropic` + Messages | 剥掉 | — |
| `openai/` | `…/openai/v1` + Responses | 剥掉 | GPT-5.6 带工具时 chat/completions 会被 OpenAI 自己拒绝 |
| 其他 | `…/compat` + Chat Completions | **保留** | 没有前缀会得到 `2008 Invalid provider` |

`/compat` 是真正的 OpenAI 兼容翻译层：OpenAI 形状的 `tools` 进去，标准 `tool_calls`
出来，Anthropic 和 Gemini 都如此，`stream: true` 也是标准 SSE。

代码里就是 `coworker/providers/aigateway_provider.py` 的 `wire_for()` 和
`upstream_model()`。

---

## 5 · 不在列表里的模型

选择器里没有的也可以手填（**添加自定义模型**），格式就是上表那种 `厂商/模型名`。
Cloudflare 的完整目录在 <https://developers.cloudflare.com/ai/models/>。

但**目录里有不等于这条路上能用**。判断的唯一可靠办法是看网关日志里的 `wholesale` 字段：

- `wholesale: true` —— 这次请求走了统一计费，能用。
- `wholesale: false` —— 网关决定不替这个模型付钱，于是把请求裸转给厂商，
  厂商回一句缺凭据的错。**这是覆盖范围的问题，不是你配置错了**，配 BYOK 才能用。

Gemini 那句 `Missing or invalid Authorization header` 就是这么来的——听着像鉴权问题，
实际是覆盖问题。

### ⚠ 三种误读探测结果的方式

判断一个模型能不能用时，这三个都踩过：

| 现象 | 看着像 | 实际是 |
| --- | --- | --- |
| 402 `Wholesale rate limit exceeded` | 不覆盖 | 共享池忙，等几秒重试 |
| 402 `not available via unified billing` | 同上 | 这个才是真不覆盖 |
| 2002 `Failed to parse model output` | 模型坏了 | 空补全。Gemini 会先思考再回答，`max_tokens` 给小了就没输出，给 800 再试 |
| 400 `User Input Error`（图片） | 不支持看图 | 图片本身的问题，1×1 的 PNG 会被直接拒 |
| 200 但 `cached: true` | 成功 | 缓存重放，这次请求根本没发生 |

统一计费的池子是**按模型共享**的，越贵越热门越容易撞。所以**探测要一个一个慢慢来**，
密集打会把好模型测成坏的。正文在网关日志里存着（Logs ▸ 点开某条 ▸ `response_head`）。

---

## 6 · 看用量

### 6.1 按人看花了多少

**AI** ▸ **AI Gateway** ▸ `openworker-agw` ▸ **用户洞察**。因为流量是从 Access 保护的
自定义域进来的，每条请求都带着登录者的身份，这一页会直接列出每个人的花费、token 数、
最常用的模型。不需要客户端上报任何东西。

**日志** 页可以按同样的身份筛选。

### 6.2 给每个人单独的预算

网关的 **成本限制** ▸ 新增规则 ▸ **Limit by metadata**，键填 `cf.user_id`，
选 **Split by value**，然后设金额和时间窗。这样每个人拿到的是各自独立的预算，
不是大家抢一个池子。

> 注意语义会变：原来 `$X/天` 是全员合计，改成 split 之后是**每人** `$X/天`。
> 别直接沿用旧数字。

---

## 7 · 排错

| 现象 | 多半是 |
| --- | --- |
| 「登录」按钮是灰的 | 网关地址还没填。登录就是往那个地址去的 |
| 点了登录，浏览器一直转 | 管理员没开动态客户端注册，注册端点会返回 404。见 1.4 |
| 报「本机 53682… 端口都被占用了」 | 别的程序占了回调端口。Cloudflare 只认注册过的端口，换不了，得先关掉占用的程序 |
| 登录完又变回「未登录」 | 授权被拒，或者你不在 Access 策略的允许名单里。找管理员 |
| 测试报「Access 会话无效」 | 粘贴的那种会话过期了（每天）。点「登录」换成会自动续期的 |
| 测试报「这个地址上没有网关」 | 网关地址抄错，或者自定义域还没生效 |
| 测试报「额度用完了」 | 去 Billing 充值 |
| `403 Your request was blocked.` | 边缘的「阻止 AI 机器人」打的，不是 Access。见 1.5 |
| 报「共享容量忙」 | 临时的，等几秒重试；天天撞就配 BYOK 独占一个池子 |
| 模型报缺 Authorization | 这个模型不在统一计费覆盖里，见第 5 节 |
| 「用户洞察」是空的 | 流量没走自定义域，或者用的是 service token（它的身份是空的） |
| 调用成功但日志里没有 | 走到账号的 `default` 网关去了——地址填错了 |

---

## 相关文档

- [01-管理员初始化手册](./01-管理员初始化手册.md) —— Gemini 中转那一套
- [03-用户手册](./03-用户手册.md) —— 装应用、登录、日常使用
- Cloudflare 官方：[AI Gateway](https://developers.cloudflare.com/ai-gateway/)、
  [Cloudflare Access](https://developers.cloudflare.com/ai-gateway/configuration/cloudflare-access/)、
  [自定义域](https://developers.cloudflare.com/ai-gateway/configuration/custom-domains/)、
  [Unified Billing](https://developers.cloudflare.com/ai-gateway/features/unified-billing/)
