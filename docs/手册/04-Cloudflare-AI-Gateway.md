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

> 这个域名已经写死在应用里当默认值（`coworker/providers/aigateway_provider.py` 的
> `DEFAULT_BASE_URL`），同事那边因此一个字都不用填。**换域名等于发版**：要么随新版
> 改这个常量，要么让同事临时设 `CLOUDFLARE_AIGW_BASE_URL` 环境变量顶过去。

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

## 2 · 同事：点一次登录

不用装任何东西，不用申请任何密钥，也没有任何要填的——网关地址已经内置在应用里。

1. **设置 ▸ 模型 ▸ Cloudflare AI Gateway**
2. 点卡片上的 **登录**。浏览器会弹出来走一次公司的 Access 登录，登完那个标签页会自己
   显示「登录成功」，回到应用就已经是「✓ 已登录」，常用的那款模型也自动进了选择器
3. 想确认真能用，点已登录卡片上的 **测试**——它会真的调一次最便宜的模型
   （不到一厘钱），所以测试通过就等于真能用
4. 在上方的模型选择器里挑一个 `· via Cloudflare` 结尾的模型

登录之后就不用再管了：应用后台每 15 分钟悄悄续一次令牌，**两周**之内不会再问你。
续签的每一次 Cloudflare 都会重新核对你还在不在允许名单里——所以两周这个时长是安全的，
一个人离职或被移出名单，最迟下一次续签就失效。

<details>
<summary>没有浏览器的机器（少数情况）</summary>

服务器、容器这类开不了浏览器的环境，用环境变量走旧办法：装一次
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)，

```bash
cloudflared access login https://gateway.smjtools.com
```

```bash
cloudflared access token -app=https://gateway.smjtools.com
```

把输出整串放进环境变量 `CLOUDFLARE_AIGW_ACCESS_TOKEN`（设置界面里已经没有粘贴框了；
要指到别的网关时再配 `CLOUDFLARE_AIGW_BASE_URL`）。**这种会话每天都会失效**，失效后
测试会报「Access 会话无效」，得重跑第二条命令换个新的。能登录就别用这条路。

两者同时存在时，应用优先用登录拿到的那个。
</details>

---

## 3 · 能用哪些模型

下表每一行都在 2026-08-23 通过 `gateway.smjtools.com` 真调过，带工具定义，返回 200。

| 模型 | 网关 id | 上下文 |
| --- | --- | --- |
| GPT-5.6 Sol | `openai/gpt-5.6-sol` | 1.05M |
| GPT-5.6 Terra | `openai/gpt-5.6-terra` | 400k |
| GPT-5.6 Luna | `openai/gpt-5.6-luna` | 1.05M |
| Claude Opus 5 | `anthropic/claude-opus-5` | 1M |
| Claude Sonnet 5 | `anthropic/claude-sonnet-5` | 1M |
| Claude Fable 5 | `anthropic/claude-fable-5` | 1M |
| Claude Haiku 4.5 | `anthropic/claude-haiku-4-5` | 200k |
| Gemini 3.6 Flash | `google-ai-studio/gemini-3.6-flash` | 1M |
| Gemini 3.1 Pro | `google-ai-studio/gemini-3.1-pro-preview` | 1M |
| Gemini 3.1 Flash-Lite | `google-ai-studio/gemini-3.1-flash-lite` | 1M |
| Gemini 3 Flash | `google-ai-studio/gemini-3-flash-preview` | 1M |

全部支持看图。PDF 走本地转图片的老路（`pdf_support.py`），能看图就能读 PDF。

上下文一列在 2026-09-15 对着 Cloudflare 自己的模型页核过一遍：Opus 5 和 Sonnet 5 都是
1M（此前留空），Sol 和 Luna 是 1.05M（此前照抄的 400k 偏小）。**只有 Terra 两边都查不到**
——模型页和文档搜索都没有这个数——所以它仍留着没核实的 400k。分母偏小只会让进度条早一点
变红、自动压缩早一点触发；照着兄弟型号猜一个大的，代价是一整轮对话直接失败。

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
| 点了登录，浏览器一直转 | 管理员没开动态客户端注册，注册端点会返回 404。见 1.4 |
| 报「本机 53682… 端口都被占用了」 | 别的程序占了回调端口。Cloudflare 只认注册过的端口，换不了，得先关掉占用的程序 |
| 登录完又变回「未登录」 | 授权被拒，或者你不在 Access 策略的允许名单里。找管理员 |
| 测试报「Access 会话无效」 | 粘贴的那种会话过期了（每天）。点「登录」换成会自动续期的 |
| 测试报「内置的网关地址没有像网关那样应答」 | 自定义域坏了或还没生效——管理员侧的问题，同事那边没有可改的 |
| 测试报「额度用完了」 | 去 Billing 充值 |
| `403 Your request was blocked.` | 边缘的「阻止 AI 机器人」打的，不是 Access。见 1.5 |
| 报「共享容量忙」 | 临时的，等几秒重试；天天撞就配 BYOK 独占一个池子 |
| 报「共享容量忙，同档备选也忙」 | 动态路由已经自动重发过一次还是没成——等几秒重试。括号里的路由名拿去第 8 节排错 |
| 模型报缺 Authorization | 这个模型不在统一计费覆盖里，见第 5 节 |
| 「用户洞察」是空的 | 流量没走自定义域，或者用的是 service token（它的身份是空的） |
| 调用成功但日志里没有 | 走到账号的 `default` 网关去了——只有自己拿 `CLOUDFLARE_AIGW_BASE_URL` 覆盖过地址才会发生 |

---

## 8 · 动态路由：429 的时候自动换同档的另一家

### 8.1 要解决的是什么

网关对**每个模型**按并发限流：同一个模型上一条慢请求还在路上，新请求会在 200～500 毫秒
内被拒，HTTP 429，正文就一句 `Rate limited`（SDK 转述成
`{'code': 2018, 'message': 'Wholesale Rate limited'}`）。到目前为止这个网关的 429 全部
集中在 `openai/gpt-5.6-sol`——两个人同时按回车就够了。

这不是额度用完，等几秒就好；但一轮对话已经失败了。动态路由的作用是：撞上这一下的时候，
把同一轮请求原样改发到**同档的另一家**，用户看到的是回答，不是「错误：429」。

### 8.2 档位对照

跨家配对的前提是两边能力相当。同档的两个模型互为备选：

| 档位 | anthropic | openai | 备注 |
| --- | --- | --- | --- |
| 旗舰·长上下文 | `anthropic/claude-fable-5`（1M） | `openai/gpt-5.6-sol`（1.05M） | Fable 的对家本来想用 `gpt-6-astra`，见 8.6 |
| 旗舰 | `anthropic/claude-opus-5`（1M） | `openai/gpt-5.6-sol`（1.05M） | 两个都在门禁的受限名单里 |
| 高阶/均衡 | `anthropic/claude-sonnet-5`（1M） | `openai/gpt-5.6-terra`（400k） | |
| 轻量 | `anthropic/claude-haiku-4-5`（200k） | `openai/gpt-5.6-luna`（1.05M） | **不建路由**，见 8.3 |

### 8.3 五条路由

路由名一律 `ow-<厂商>-<模型>`：点改横杠、全小写。每条路由在网关侧是一个小图：
Start → 主选模型（retries 1、timeout 20000）→ 成功就 End，出错或超时就走 fallback 模型 → End。

| 路由名 | 主选 | 备选 |
| --- | --- | --- |
| `ow-anthropic-claude-fable-5` | `anthropic/claude-fable-5` | `openai/gpt-5.6-sol` |
| `ow-openai-gpt-5-6-sol` | `openai/gpt-5.6-sol` | `anthropic/claude-opus-5` |
| `ow-anthropic-claude-opus-5` | `anthropic/claude-opus-5` | `openai/gpt-5.6-terra` |
| `ow-anthropic-claude-sonnet-5` | `anthropic/claude-sonnet-5` | `openai/gpt-5.6-terra` |
| `ow-openai-gpt-5-6-terra` | `openai/gpt-5.6-terra` | `anthropic/claude-sonnet-5` |

**轻量档（Haiku / Luna）故意不建。** 限流只发生在顶级池；而且 Haiku 是「测试」按钮的探测
模型和摘要模型，给它加一条路由会让「探测永远不失败」这件事更难讲清楚。

**备选的受限等级不得高于主选。** gateway-guard 把最贵的几个模型限定给特定角色；如果 429
能把一个人送到他本来没权限的模型上，那门禁就等于「挑个忙的时候再试一次」就能绕过。现在受限
的只有 `claude-fable-5` 和 `gpt-5.6-sol`，而这两个只在它们自己也受限的主选下面出现。

**这张表和 gateway-guard 的 `ROUTE_MODELS` 必须同日上线。** 门禁要能把
`dynamic/<路由名>` 还原成「主选 + 备选」两个模型才能继续判断权限；两张表哪一张先走一步，
中间那段时间要么门禁误拒，要么门禁形同虚设。

### 8.4 判 429 的责任在客户端

Cloudflare 的 fallback 边只有「出错或超时」一种语义，**没法指定只在 429 触发**。所以顺序
是反过来的：应用照常走各自的原生通道（Anthropic 走 `/anthropic`、GPT-5.6 走
`/openai/v1`），**只有**在收到「共享池忙」的错误时，才把这一轮改发到 `/compat`，模型写成
`dynamic/<路由名>`，由网关去挑活着的那个。

判定见 `coworker/providers/errors.py` 的 `is_gateway_busy()`：HTTP 429 且正文含
`rate limited`，或旧的 402 `wholesale rate limit exceeded`。别的错误一律不重发——模型 id
写错、被门禁拒、余额为零，在备选上会一模一样地失败，白搭一次往返。

**装不下对家的窗口就不重发。** 同档不等于同窗口：`claude-opus-5` 和 `claude-sonnet-5` 都是
1M，它们的对家 `gpt-5.6-terra` 只有 400k，而且 400k 是全表唯一一个没核实的数（见 8.2）。一轮
50 万 token 的会话在主选上放得下、在对家上必然溢出，重发只是买一次注定失败的往返——更糟的是
下面「抛第一次那个 429」的规矩会让用户看到「共享额度繁忙」，而真实原因是上下文超了，指向完全
错的方向。所以 `aigateway_provider.fits_the_stand_in()` 先用 `compaction.estimate_tokens()`
（chars/4）估一下这一轮，超过对家窗口的 90%（留 10% 给回复，以及中文字符的估算误差）就直接抛
原始 429、一次都不重发，日志里写明「装不下」。矩阵里查不到窗口的对家不设上限——没数就不臆造。

自动压缩本来就把会话压在 min(0.8 × 窗口, 25 万) 以下，所以这道闸平时不触发；它防的是压缩没
覆盖到的情况：一轮没压过的工具循环、一次巨大的粘贴、或者哪天矩阵把某个窗口改小。

**代价：重发那一次只能走 `/compat`。** 那是个 OpenAI 兼容翻译层，不是原生通道——
Responses 那条线独有的东西（比如 GPT-5.6 的推理强度档位）在这一轮拿不到。而且
chat/completions 拒绝「函数工具 + 非 none 的 reasoning_effort」，所以**只要路由的任意一端是
openai 档**（不只是主选），重发都会补一个 `reasoning_effort: "none"`。理由是客户端根本不知道
网关最后挑了哪一端：表里有一半是 anthropic 主选配 openai 对家（`claude-opus-5` →
`gpt-5.6-terra`），只看主选的话这些重发会不带 pin 打到 chat/completions 上，靠
`openai_provider` 的 `_param_fix_retry` 自愈——结果虽然对，却要在已经两次请求的这一轮上再加
第三次往返。反方向（anthropic 那端收到一个 `reasoning_effort`）依赖的是「兼容层只转发厂商
schema 认识的字段」，这个假设本来就撑着表里 openai 主选的那一半，并非新增风险；第一次真实
429 打到路由上之后，去网关 Logs 里确认一眼。

**流式已经吐出内容之后绝不重发。** 用户已经看到的文字不能再来一遍——`stream()` 因此改成了
生成器，只在「一个 chunk 都还没吐」的时候才换路由。

**两次都失败，抛出来的是第一次那个 429**，不是路由返回的错误：路由没建好和备选也忙，对用户
都是「这一档现在用不了」，而只有原始的 429 正文带着上面那个标记。错误文案里会附上试过的
路由名和对家。

> **已知局限（有意为之）**：如果重发那一路已经吐出几段文字才失败，那几段会留在屏幕上，而最后
> 抛的仍然是第一次那个 429——文案会说「同档备选也忙」，哪怕路由真正的死因是别的（网络抖动、
> 对家自己的限流）。换成报告第二个错，等于跟屏幕上已有的文字自相矛盾。碰到这种情况去网关
> Logs 里看那一轮的 `response_head`，不要信这句文案。

### 8.5 回滚开关

环境变量 `CLOUDFLARE_AIGW_DYNAMIC_ROUTING`：设成 `0`、`off`、`false`、`no` 就关掉重发，
回到「429 直接报错」的老行为；不设或设别的值都是开。**设置页里没有这一项**，它是运维用的
应急闸（比如某条路由被误删），不是偏好。

关掉之后，模型选择器上的「有备选」徽标也会一起消失——徽标承诺的行为不发生，就不该显示。

### 8.6 为什么没有 gpt-6-astra

`gpt-6-astra` 出现在网关的 `/compat/models` 清单里，但**没有接入统一计费**：直接探测
`/compat` 会返回 401「未提供 API key」，官方模型目录里也查不到它的文档页。清单里有 ≠ 能用。
所以本期不把它写进 `matrix.py`，Fable 的对家改用 `openai/gpt-5.6-sol`。等它真的接入统一
计费，再补一行矩阵和一条 `ow-openai-gpt-6-astra`。

### 8.7 验证与排错

- **网关侧建完先回读**：先建一条，`GET` 回来核对字段名，再批量建其余四条。
- **直连验一次**：`POST https://gateway.smjtools.com/compat/chat/completions`，
  头里带 `cf-access-token`（`cloudflared access token` 取）和 `cf-aig-skip-cache: true`
  （不加这个，网关会拿缓存里的旧答案糊弄你），body 里 `model` 写
  `dynamic/ow-anthropic-claude-fable-5`。看响应头 `cf-aig-model` / `cf-aig-provider`
  告诉你实际落到了谁身上。
- **人为触发一次回退**：把主选那个 Model 节点临时改成一个不存在的 id，再打一次，
  `cf-aig-model` 应该显示对家；或者给主选设一个 0 额度的 Spend Limit。
- **应用侧**：`CLOUDFLARE_AIGW_DYNAMIC_ROUTING=1` 时那一轮应该正常出回答；
  `=0` 时应该恢复成「错误：429」。
- **长会话撞 429 却没有重发**，先别当 bug：日志里如果有
  `does not fit the stand-in … (window …)`，那是 8.4 的窗口闸按设计拦下的——这一轮装不进
  对家。要么等主选空出来，要么先让会话压缩一次。
- **网关当前的限流配置**（2026-09 实测）：rate limiting 200 次/60 秒、spend limit
  $20/86400 秒、网关到上游 `retry_max_attempts=3` 指数退避。这些是网关到上游的重试，
  和这里说的客户端重发是两码事。

---

## 相关文档

- [01-管理员初始化手册](./01-管理员初始化手册.md) —— Gemini 中转那一套
- [03-用户手册](./03-用户手册.md) —— 装应用、登录、日常使用
- Cloudflare 官方：[AI Gateway](https://developers.cloudflare.com/ai-gateway/)、
  [Cloudflare Access](https://developers.cloudflare.com/ai-gateway/configuration/cloudflare-access/)、
  [自定义域](https://developers.cloudflare.com/ai-gateway/configuration/custom-domains/)、
  [Unified Billing](https://developers.cloudflare.com/ai-gateway/features/unified-billing/)
