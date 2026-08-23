# Cloudflare AI Gateway 手册

> **读者**：管理员（配置那一次）和所有使用者（选模型那一步）。
> **什么时候读**：想在 Gemini 之外用 GPT / Claude / Grok / DeepSeek 这些模型的时候。
> **和 Gemini 中转什么关系**：两套东西，各管各的，见下一节。

---

## 0 · 它和 Gemini 中转是两回事

| | Gemini 中转（`gemini.smjtools.com`） | Cloudflare AI Gateway |
| --- | --- | --- |
| 覆盖哪些模型 | 只有 Gemini | 除 Gemini 外的一大半：OpenAI、Claude、Grok、DeepSeek、Qwen、Kimi、MiniMax… |
| 同事要几样凭证 | 两样：登录（验证码）+ 他自己那把 Gemini key | 一样：一个 Cloudflare API token |
| 谁付钱 | 公司的 Google 账号，按 key 分人看 | 公司 Cloudflare 账号里的 AI Gateway 预付额度 |
| 我们写了多少代码 | 一整个 Worker（认人 / 转发 / 记账 / 限额） | 零。Cloudflare 自己就是那个 Worker |

**为什么留着两套**：Gemini 中转能做到「每人一把 key、按人限额」，那是我们自己写的闸门；
AI Gateway 现在是一个账号一本账，分不到人头。反过来 AI Gateway 一把 token 就能用十几家
模型，Gemini 中转做不到。所以模型选择器里 **Gemini 走中转、别家走网关**，
两边不重叠——同一个厂商出现两条路只会变成工单。

---

## 1 · 管理员：一次性配置

### 1.1 建网关

Cloudflare 控制台 ▸ **AI** ▸ **AI Gateway** ▸ Create Gateway。名字用 **`openworker-agw`**
（应用里预填的就是这个，改了的话每个同事都得手填）。

建议开的：

| 设置 | 值 | 为什么 |
| --- | --- | --- |
| Authenticated Gateway | 开 | 不开的话知道账号 ID 的人就能白嫖你的额度 |
| Cache TTL | `86400` | 同样的提问一天内不重复计费 |
| Rate limiting | `100 / 60s` | 有人的自动循环跑飞时的兜底 |
| Logs | 开 | 谁在什么时候调了什么模型，只能靠它 |

### 1.2 充值

**AI** ▸ **AI Gateway** ▸ **Billing** 里加信用卡并充值。第三方模型走的是 Unified Billing
（统一计费）：从这个余额里扣，**不需要给每家厂商配 key**。

顺手把 **Spending limit** 设上。额度是预付的，跑飞了就是真金白银。

### 1.3 建 API token

**My Profile** ▸ **API Tokens** ▸ **Create Token** ▸ Custom token。

- 权限只给一条：**Account ▸ Workers AI ▸ Run**（Edit 也行，但用不上）。
- Account Resources 限定到这一个账号。
- 建完只显示一次，存好。

> **这把 token 会发给同事。** 它能花账户里的额度，所以：权限只给 Workers AI Run（不要给
> Zone / Workers Scripts / R2 那些）、给 token 设过期时间、每人一把并按人命名，
> 这样 Cloudflare 后台能看到谁在用、要停谁的时候删掉那一把就行。
>
> 一把 token 全公司共用也能跑，但那样 Logs 里所有请求长得一模一样，出事查不出是谁。

### 1.4 找账号 ID

```bash
npx wrangler whoami
```

32 位十六进制那一串。控制台任意一个站点的 Overview 页面右下角也有。

---

## 2 · 同事：应用里怎么填

**设置 ▸ 模型 ▸ Cloudflare AI Gateway**，三个框：

| 框 | 填什么 |
| --- | --- |
| Cloudflare 账号 ID | 管理员给的那 32 位 |
| Cloudflare API token | 管理员发给你的那一把 |
| 网关名称 | 已预填 `openworker-agw`，不用动 |

点 **测试**。它会真的调一次最便宜的模型（不到一厘钱），所以测试通过就等于真能用——
不是只验证了 token 格式对不对。

然后在会话上方的模型选择器里挑一个「· via Cloudflare」结尾的模型。

---

## 3 · 能用哪些模型

下表每一行都在 2026-08-23 真调过一次，带工具定义，返回 200。

| 模型 | 网关 id | 上下文 | 看图 |
| --- | --- | --- | --- |
| GPT-5.6 Terra | `openai/gpt-5.6-terra` | 400k | ✅ |
| GPT-5.6 Luna | `openai/gpt-5.6-luna` | 400k | ✅ |
| GPT-5.5 | `openai/gpt-5.5` | 400k | ✅ |
| Claude Sonnet 4.6 | `anthropic/claude-sonnet-4.6` | 200k | ✅ |
| Claude Haiku 4.5 | `anthropic/claude-haiku-4.5` | 200k | ✅ |
| Grok 4.3 | `xai/grok-4.3` | 256k | |
| DeepSeek V4 Pro | `deepseek/deepseek-v4-pro` | 128k | |
| DeepSeek V4 Flash | `deepseek/deepseek-v4-flash` | 128k | |
| Kimi K2.6 | `moonshotai/kimi-k2.6` | 256k | |
| Kimi K3 | `moonshotai/kimi-k3` | 1M | |
| Qwen3 Max | `alibaba/qwen3-max` | 256k | |
| MiniMax M2.7 / M3 | `minimax/m2.7`、`minimax/m3` | — | |
| GLM-5.2 | `@cf/zai-org/glm-5.2` | 256k | |
| Kimi K2.7 Code | `@cf/moonshotai/kimi-k2.7-code` | 256k | |
| Qwen3.8 27B | `@cf/qwen/qwen3.8-27b` | 256k | |
| Nemotron 3 120B | `@cf/nvidia/nemotron-3-120b-a12b` | 256k | |
| Llama 4 Scout | `@cf/meta/llama-4-scout-17b-16e-instruct` | 131k | |
| Mistral Small 3.1 | `@cf/mistralai/mistral-small-3.1-24b-instruct` | 128k | |

`@cf/` 开头的是 Cloudflare 自己托管的（Workers AI），其余是转发给厂商的。用起来一样。

「看图」那列空着不等于不支持，只是**没实测过**，所以应用不会声称支持。PDF 一律走本地
转图片的老路（`pdf_support.py`），能看图的模型就能读 PDF。

### 上下文窗口那一列

数字来自对应厂商行或 Workers AI 目录自己的 `context_window`。MiniMax 两行留空是因为
没去核对厂商文档——宁可让界面上的上下文进度条隐藏，也不编一个分母出来。

---

## 4 · 为什么模型 id 长这样

`aigw:anthropic/claude-sonnet-4.6` 拆成三段：

- `aigw:` —— 应用内部的路由前缀，选择器里看不到。
- `anthropic` —— **厂商段**。它决定用哪种请求格式，不只是个标签。
- `claude-sonnet-4.6` —— Cloudflare 写法的模型名。**注意是点不是横杠**，Anthropic 自己写
  `claude-sonnet-4-6`。我们不做翻译，照抄 Cloudflare 的写法，翻译只会翻出 bug。

厂商段决定的那件事：网关虽然叫「OpenAI 兼容」，但只对一部分厂商成立。实测下来是三条线：

| 厂商段 | 走哪条 | 实测到的坑 |
| --- | --- | --- |
| `anthropic/` | Anthropic Messages | chat/completions 会把 OpenAI 格式的 `tools` 原样丢给 Anthropic，直接被拒 |
| `openai/` | OpenAI Responses | 整个 GPT-5.6 系列在 chat/completions 上一律 `Invalid value at input` |
| 其他（含 `@cf/`） | OpenAI Chat Completions | 正常 |

代码里就是 `coworker/providers/aigateway_provider.py` 的 `wire_for()`。

---

## 5 · 不在列表里的模型

选择器里没有的也可以手填（**添加自定义模型**），格式就是上表那种 `厂商/模型名`。
Cloudflare 的完整目录在 <https://developers.cloudflare.com/ai/models/>。

有三个明明在目录里、却调不通的，都是同一个原因——**旗舰型号不在统一计费范围内**：

```
openai/gpt-5.6-sol
anthropic/claude-fable-5
anthropic/claude-opus-4.8
thinkingmachines/inkling
```

调它们会返回 402，或者一句 `This model is not available via unified billing. Please use BYOK.`
应用会把这句翻成人话。**要用就得配 BYOK**：网关设置里存一把该厂商自己的 API key
（alias 必须叫 `default`，别的 alias 在统一计费这条路上不生效）。配好之后把上面的 id
手填进去就能用，代码不用改。

BytePlus / 火山方舟、Meta Muse Spark 那几个是**目录里根本没有**，不是配置问题。

---

## 6 · 看用量

**AI** ▸ **AI Gateway** ▸ `openworker-agw` ▸ Logs / Analytics。每条请求都有模型、token 数、
耗时、缓存命中。按 token 分不了人——除非 1.3 节说的「每人一把命名 token」你照做了。

费用在 Billing 页，和 Logs 是同一份数据的两种看法。

---

## 7 · 排错

| 现象 | 多半是 |
| --- | --- |
| 测试报「Cloudflare 拒绝了这个 token」 | token 抄错，或者建的时候没给 Workers AI Run 权限 |
| 测试报「Cloudflare 上没有这个账号 ID」 | 账号 ID 抄错。跑 `npx wrangler whoami` 对一下 |
| 测试报「没有 AI Gateway 额度」 | 去 Billing 充值 |
| 某个模型报 BYOK | 见第 5 节，这个型号不在统一计费里 |
| 报「共享容量已满」 | 统一计费是共享池，等一会儿再试；常用就配 BYOK 独占 |
| 调用成功但 Logs 里没有 | 网关名填错了，请求落到账号的 `default` 网关去了 |
| 一切正常但没走网关 | 同上。网关名留空就是有意用默认网关 |

---

## 相关文档

- [01-管理员初始化手册](./01-管理员初始化手册.md) —— Gemini 中转那一套
- [03-用户手册](./03-用户手册.md) —— 装应用、登录、日常使用
- Cloudflare 官方：[AI Gateway](https://developers.cloudflare.com/ai-gateway/)、
  [REST API](https://developers.cloudflare.com/ai-gateway/usage/rest-api/)、
  [Unified Billing](https://developers.cloudflare.com/ai-gateway/features/unified-billing/)
