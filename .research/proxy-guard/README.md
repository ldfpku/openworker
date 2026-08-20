# proxy-guard

一个**单文件、零配置**的 PowerShell 脚本，让本机所有程序自动走本地代理，解决
Hermes agent / OpenWorker 等通过 API 调用 Gemini 等国外模型时报

```
400 FAILED_PRECONDITION
User location is not supported for the API use.
```

的问题；同时保证**国内流量不被中转**。

脚本：[`proxy-guard.ps1`](proxy-guard.ps1)　背景排查见上级目录 [`../README.md`](../README.md)

---

## 一、给同事的操作指引（三步）

> 前提：本机已经装好并启动了任意一个代理客户端（v2rayN / Clash / Clash Verge /
> sing-box / NekoRay 都行），浏览器能正常访问 Google 即可。**不需要管理员权限。**

**第 1 步**：把 `proxy-guard.ps1` 一个文件拷到本机任意目录（比如 `D:\tools\proxy-guard.ps1`）。
放哪都行，脚本不依赖任何固定路径。

**第 2 步**：在该目录打开 PowerShell（地址栏输入 `powershell` 回车），执行：

```bash
powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Install
```

看到 `自启已就绪` 就成了。脚本会自动探测你用的是哪个代理客户端、哪个端口，
写入环境变量，并配置成开机自启。

**第 3 步**：**重启** Hermes agent / OpenWorker / 已打开的终端。

> 环境变量只对"之后新启动"的进程生效，已经在跑的程序必须重启才能拿到。

验证是否成功：

```bash
powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Test
```

看到 `代理出口在 US/JP/SG…，可绕过地区限制` 和 `大陆流量…未绕境外` 两条结论就没问题了。

### 常见问题

| 现象 | 处理 |
|---|---|
| `没有探测到可用的本地代理端口` | 先把代理客户端打开；或用 `-Port 7890` 手动指定端口 |
| `代理出口仍被判为 CN` | 代理节点本身就在国内，换一个境外节点 |
| 装完还是报地区限制 | 没重启程序。Hermes agent / OpenWorker 必须重启 |
| 公司电脑装不上计划任务 | 正常，脚本会自动改用"登录自启的常驻进程"，效果一样 |
| 想卸载 | `powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Uninstall` |

---

## 二、原理（为什么不用改代码）

`google-genai`、`openai`、`anthropic` 这些 SDK 底层都是 `httpx`，而 httpx 默认
`trust_env=True`，会自动读取这四个环境变量：

```
HTTP_PROXY  = http://127.0.0.1:<port>
HTTPS_PROXY = http://127.0.0.1:<port>
ALL_PROXY   = http://127.0.0.1:<port>
NO_PROXY    = localhost,127.0.0.1,::1,...,.cn,baidu.com,aliyun.com,...   （共 80 条）
```

所以只要让进程的环境里有它们，**不用改任何一行业务代码**，Hermes agent、OpenWorker、
python/httpx、curl、git、pip、npm 就都自动走代理了。

优先用 `http://` 而不是 `socks5://`：很多客户端的"混合端口"同一个端口两种协议都收，
而 HTTP 代理的工具兼容性最好（git / npm / go / .NET 都认，也不依赖 Python 的 `socksio` 包）。

### 端口是怎么自动找到的

按这个顺序找，每个候选端口都做**真实握手探测**（HTTP CONNECT / SOCKS5），握手过了才采用：

1. 命令行 `-Port` 指定的
2. 上次探测成功的端口
3. **系统代理设置** —— 包括 PAC 模式：会把 PAC 服务的正文抓下来，
   从里面解析出 `PROXY 127.0.0.1:xxxx`（PAC 服务自己的端口不是代理端口，这点很容易搞错）
4. 已知代理客户端进程（v2rayN / xray / clash / mihomo / sing-box / nekoray …）占用的监听端口
5. 常见端口兜底：7890、7897、10808、10809、1080、2080 …

所以同事用什么客户端、什么端口都不用改脚本。

---

## 三、国内流量为什么不会被中转

两层，各自独立生效：

**第 1 层 · `NO_PROXY`（请求根本不进代理）**
本机与内网（`localhost`、`127.0.0.1`、`::1`、`10/8`、`172.16/12`、`192.168/16`、
`169.254/16`、`.local`、`host.docker.internal`），加上 `.cn` 全后缀和约 60 个大陆常用
域名（阿里/腾讯/百度/字节系、B站知乎微博、npmmirror、gitee、deepseek 等）。
`.cn` 一条就覆盖了 `com.cn`/`edu.cn`/`gov.cn`，以及清华、中科大等镜像源。

**第 2 层 · 代理客户端自身路由（兜底）**
主流客户端默认都是"绕过大陆"：`geosite:cn` / `geoip:cn` / `geoip:private` → `direct`。
即便某个大陆域名不在 `NO_PROXY` 里，客户端也会直连出去。

`-Test` 会实测这一点 —— 同一个国内站点分别直连和经代理各问一次，出口 IP 应完全一致：

```
直连  访问 ipip.net: 当前 IP：104.28.208.150  来自于：中国 北京 北京
代理  访问 ipip.net: 当前 IP：104.28.208.150  来自于：中国 北京 北京   ← 一致
结论: 两者出口一致 -> 大陆流量被判为直连，未绕境外。
```

要加自己的直连域名，写进 `%LOCALAPPDATA%\proxy-guard\extra-noproxy.txt`（每行一条，
`#` 开头是注释），换新版脚本也不会覆盖。

---

## 四、自启与自愈

`-Install` 会依次尝试三种自启方式，**每种都真实触发一次做验证**，跑得起来才算数：

| 顺序 | 方式 | 说明 |
|---|---|---|
| 1 | 计划任务 + `conhost --headless` | 无窗口，不闪黑框 |
| 2 | 计划任务 + `powershell -WindowStyle Hidden` | 兼容模式，可能一闪 |
| 3 | 登录自启的**隐藏常驻进程** | 不经过计划任务，只在登录时启动一次，无窗口 |

部分受管企业终端（装了 SCCM/Intune 端点防护的）会**拦截由计划任务派生的 PowerShell**
——表现为任务退出码 0 或 `0xFFFD0000`、脚本压根没跑。这种机器上前两种会验证失败，
脚本自动落到第 3 种（启动项是用 COM 生成的 `.lnk`，不落任何脚本文件）。

不论哪种方式，行为都一样，而且是**自愈**的：

- 代理端口通 → 写入环境变量
- 代理端口断 → **清除**环境变量，回落直连

第二条是关键的安全设计：如果只是无脑写死代理，代理客户端一关，所有程序都会往一个死端口
发请求，整机断网。现在最坏情况只是恢复到"直连 + 被 Google 拒"，其它一切照常。

---

## 五、命令一览

```bash
powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1            # 看状态
powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Install   # 安装（含开机自启）
powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Test      # 连通性自检
powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Uninstall # 卸载并清除环境变量
```

让**当前这个终端**立刻生效（注意开头的「点 + 空格」= dot-source）：

```bash
. .\proxy-guard.ps1 -Apply
```

常用参数：`-Port 7890`、`-Scheme auto|http|socks5`、`-IntervalMinutes 5`、
`-ExtraNoProxy 'a.com','b.com'`、`-GeminiKey <key>`、`-EnsureClientRunning`（代理客户端
没开时自动拉起，默认关）。

日志在 `%LOCALAPPDATA%\proxy-guard\proxy-guard.log`。

---

## 六、关于 Cloudflare WARP / Cloudflare One

**替代不了代理客户端。** 实测（`https://www.cloudflare.com/cdn-cgi/trace`）：

| 链路 | 出口 IP | Cloudflare 机房 | `loc`（地理服务看到的国家） | Gemini |
|---|---|---|---|---|
| 直连（经 WARP） | 104.28.208.150 | **LAX**（洛杉矶） | **CN** | ❌ 400 FAILED_PRECONDITION |
| 经本地代理 | 129.146.47.135 | LAX | **US** | ✅ |

WARP 明明接的是洛杉矶机房，`loc` 却仍是 `CN` —— Cloudflare 在 geofeed 里把 WARP 出口 IP
标回用户的真实国家，这是设计而非开关。要改出口地区需要 Zero Trust 的
**Egress Policies + Dedicated Egress IPs**（付费加购，且需组织管理员在控制台配置）。
关掉 WARP 也没用，那样出口就是本地 ISP 的中国 IP，照样被拒。

---

## 七、已知限制

1. **环境变量只对之后新启动的进程生效。** 已经在跑的程序需重启。脚本每次写入时都会提示，
   并广播 `WM_SETTINGCHANGE`，让 Explorer 之后启动的程序立刻拿到新值。
2. 代理客户端关掉后，环境变量最多 `-IntervalMinutes` 分钟后才被清除。
3. Electron / Node 应用不一定读 `HTTPS_PROXY`，需要各自配置。
4. 脚本路径写在自启项里。移动脚本后要重新跑一次 `-Install`。
5. 仅 Windows。

---

## 八、踩过的坑（都已修）

- **`.vbs` 中转启动器**：`%LOCALAPPDATA%` 下的 vbs 调 `powershell -ExecutionPolicy Bypass`
  是杀软的典型特征，文件被清掉后计划任务每次触发弹「无法找到脚本文件」。已改为不落任何
  脚本文件（计划任务直接执行 / 启动项用 COM 生成 `.lnk`），并会清理历史残留。
- **计划任务派生的 PowerShell 被端点防护拦截**：退出码 0 或 `0xFFFD0000`，脚本没跑。
  所以 `-Install` 会真实触发验证，失败就换方式，而不是装完就宣称成功。
- **PowerShell 逗号比 `+` 结合更紧**：`@('a','b','c' + $x)` 会被解析成 `('a','b','c') + $x`。
- **`[TimeSpan]::MaxValue` 做 `-RepetitionDuration`**：生成 `P99999999DT23H59M59S`，
  任务计划 XML schema 不收；省略 `Duration` 才是"无限重复"的正确写法。
- **函数 `return @(...)` 会拆包**：单元素时不再是数组，StrictMode 下 `.Count` 直接报错，
  要在调用侧写 `@(Get-Xxx).Count`。
- **Windows 自带 curl 用 Schannel**：查不到 CRL/OCSP 时直接报
  `CRYPT_E_REVOCATION_OFFLINE`，自检里加了 `--ssl-revoke-best-effort`（只跳过吊销状态
  查不到，证书本身照常校验）。
- **PowerShell 5.1 把 JSON 传给原生 exe 时会吃掉双引号**：Gemini 自检的请求体改走
  `--data-binary @临时文件`。
- **`$ErrorActionPreference = 'Stop'` + 原生命令 stderr**：curl 只要往 stderr 写一个字，
  管道取回来就变成终止性错误、正文全丢。改为 `curl -o 临时文件` 再读回。
