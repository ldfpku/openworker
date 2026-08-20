# Gemini API "User location is not supported" 排查与解决方案

> OpenWorker v0.1.7 · Windows · 研究目录(不改动项目代码)
> 日期:2026-08-17

## 一、问题现象

调用 Gemini 时返回:

```
400 FAILED_PRECONDITION
{'message': 'User location is not supported for the API use.', 'status': 'FAILED_PRECONDITION'}
```

而浏览器访问 Gemini 网站正常。

## 二、根因

Google 按**请求来源 IP 的地理位置**做地区限制,直接连接时服务器出口 IP 落在受限地区,
被拒绝。浏览器之所以正常,是因为流量走了 v2rayN 代理(SOCKS5 `127.0.0.1:10808`),
出口 IP 变为受限地区之外。

**代码层面**:OpenWorker 的 Gemini provider 创建客户端时没有配置任何代理/HTTP 选项,
因此底层 `httpx` 只能直连。

```python
# coworker/providers/gemini_provider.py — _ensure_client()
self._client = genai.Client(api_key=key)   # ← 无 proxy / http_options
```

## 三、SDK 机制(为什么环境变量方案能生效)

- 底层 SDK `google-genai 2.16.0` 同步路径用 `SyncHttpxClient`(`httpx.Client` 子类)
- httpx 默认 `trust_env=True`,即**自动读取** `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` 环境变量
- 本项目 httpx `0.28.1`,且 `socksio 1.0.0` 已安装 → SOCKS5 代理开箱即用,无需额外装包

因此**不改任何代码**,只要让 OpenWorker 进程的环境里有这几个代理变量即可。

## 四、实测结果(已验证)

测试脚本:`test_proxy.py`(读项目 `.env` 的 key,用 `gemini-2.5-flash` 发一次 "hi")

| 代理设置 | 结果 |
|---|---|
| 无代理(直连) | ❌ `400 FAILED_PRECONDITION` User location is not supported(**复现**) |
| `socks5://127.0.0.1:10808` | ✅ 成功,3.6s 返回 "Word" |
| `http://127.0.0.1:10809` | ❌ 连接拒绝(v2rayN 未启用 HTTP 端口) |

> 说明:你的 v2rayN 只开了 SOCKS5(10808),HTTP 端口没开。用 SOCKS5 即可。

## 五、解决方案(按推荐度排序)

### 方案 A(推荐,零代码改动):启动前设置环境变量

**PowerShell(当前会话有效):**

```powershell
$env:HTTPS_PROXY = "socks5://127.0.0.1:10808"
$env:HTTP_PROXY  = "socks5://127.0.0.1:10808"
$env:ALL_PROXY   = "socks5://127.0.0.1:10808"
# 然后再启动 OpenWorker
```

**永久(系统级,对所有终端生效):**

```powershell
[Environment]::SetEnvironmentVariable("HTTPS_PROXY", "socks5://127.0.0.1:10808", "User")
[Environment]::SetEnvironmentVariable("HTTP_PROXY",  "socks5://127.0.0.1:10808", "User")
[Environment]::SetEnvironmentVariable("ALL_PROXY",   "socks5://127.0.0.1:10808", "User")
```

(设置后需重开终端 / 应用窗口才生效。)

### 方案 B(更可控):让 v2rayN 同时开启 HTTP 端口

在 v2rayN 里把"混合端口 / HTTP 端口"打开(常见 `10809`),然后用
`http://127.0.0.1:10809`。这样不依赖 socksio,兼容性最好。

### 方案 C(需改代码,供上游参考):在 provider 里注入代理

如果希望把代理写进配置、且不走全局环境变量,可在 `_ensure_client()` 中:

```python
import os
proxy = os.environ.get("GEMINI_PROXY")
http_options = {}
if proxy:
    http_options = {"client_args": {"proxy": proxy}}
self._client = genai.Client(api_key=key, http_options=http_options or None)
```

注意:SDK 的 `_ensure_httpx_ssl_ctx` 会按 `httpx.Client.__init__` 签名过滤参数,
httpx 0.28 的 `proxy` 参数会被保留,因此该写法可用。此为可选的正式修复,非必需。

## 六、快速自检命令

```powershell
$env:HTTPS_PROXY="socks5://127.0.0.1:10808"
python c:\Users\liude\github\openworker\.research\test_proxy.py
```

看到 `[socks5-10808] OK` 即代表代理链路通,Gemini 调用即可正常工作。

## 七、相关文件

- `test_proxy.py` — 三方案实测脚本(无代理 / socks5 / http)
- `scan_sdk.py` / `scan_sdk2.py` — 排查 SDK httpx 构造逻辑的工具脚本
- `coworker/providers/gemini_provider.py` — 触发点(未修改)
