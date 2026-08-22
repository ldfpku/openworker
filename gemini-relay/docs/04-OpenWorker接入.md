# 04 - OpenWorker 接入

> 本文是什么：环境变量为什么能让 openworker 零改动接入中转，以及从零侵入到需要改代码的四种接入方式怎么选。读者何时读：完成 [03-Worker部署指南.md](./03-Worker部署指南.md) 的部署、跑通 [05-验证与排错.md](./05-验证与排错.md) 第③级 REST 裸调用之后，正式把中转接进 openworker 之前阅读。

> **v2 更新（2026-08）**：本篇是 v1 阶段写的接线机制说明，代码引用反映的是当时的仓库状态。
> 第 1 节引用的 `gemini_provider.py:429`（裸 `genai.Client(api_key=key)`，不传
> `http_options`）已在 v2 中改掉：`_ensure_client()` 现在显式传
> `http_options=types.HttpOptions(base_url=resolve_base_url(self._base_url))`，中转地址
> 作为内置默认（模块常量 `RELAY_BASE_URL`）写进 `coworker/providers/gemini_provider.py`，
> 环境变量 `GOOGLE_GEMINI_BASE_URL` 从接线机制降级为优先级最低的调试覆盖（`resolve_base_url()`
> 的优先级：profile 隐藏 `base_url` 覆盖 > 环境变量 `GOOGLE_GEMINI_BASE_URL` > 内置常量）。
> 也就是说下文的方式 A、方式 B（写 `GOOGLE_GEMINI_BASE_URL` 环境变量）在 v2 里不再是"接入
> 方式"，而是管理员排障用的调试手段。第 1 节及以下按 v1 原状保留，作为机制历史与调试通道参考。

> **v3 更新（2026-08）**：认证也变了，所以下文里凡是「一把 key 走 `x-goog-api-key`」的描述都
> 只反映 v1/v2。现在是**两把凭证**：登录令牌走 `Authorization: Bearer`（中转消费掉），本人的
> Gemini key 走 `x-goog-api-key`（原样转给 Google）。第 6 节那个 `x-relay-token` 自定义头的
> 设想没有采用——最终用的是标准的 `Authorization`。同事侧的实际操作（登录 + 填自己的 key）见
> [07-多用户与用量统计.md](./07-多用户与用量统计.md)「同事侧体验」。

## 1. 机制说明：为什么设一个环境变量就够了

openworker 的 `coworker/providers/gemini_provider.py:429`（在 `_ensure_client()` 内）是：

```python
self._client = genai.Client(api_key=key)
```

不传 `http_options`。google-genai SDK（本机确认版本 2.16.0，装在 hermes-agent venv 下）在
`google/genai/_base_url.py:34-50` 的 `get_base_url()` 里按下面顺序解析最终 base URL：

1. `HttpOptions.base_url`——构造 `genai.Client` 时显式传入的话，直接赢。
2. 进程内最近一次 `genai.set_default_base_urls()` 调用——全仓库没有任何地方调用这个函数。
3. 环境变量 `GOOGLE_GEMINI_BASE_URL`（Vertex 家族对应另一个变量，见第 6 节）。

第 1、2 级都不存在，`GOOGLE_GEMINI_BASE_URL` 因此直接生效——不用改 `gemini_provider.py` 一个字。
这个值在 `client.py:372-387` 里被折进 `http_options.base_url`，随后 `_api_client.py:807-811` 的
`patch_http_options()` 用它覆盖掉硬编码默认值 `https://generativelanguage.googleapis.com/`
（`_api_client.py:799-800`）。

同步 `generate_content` 与流式 `generate_content_stream` 走同一个 `_build_request()`
（`_api_client.py:1309-1414`；调用方分别是 `models.py:5028-5030` 与 `models.py:5136-5138`），
base_url 覆盖对两条路径完全等价，不存在"流式没生效"的分支。API key 只走 `x-goog-api-key`
请求头（`_api_client.py:803-806`），从不出现在 URL 里；请求路径固定是
`v1beta/models/{model}:generateContent` 与 `v1beta/models/{model}:streamGenerateContent?alt=sse`
（`_api_client.py:799-800` 的默认 `api_version='v1beta'`），与 Worker 的路径白名单、
[05-验证与排错.md](./05-验证与排错.md) 第③级裸调用完全对应。

## 2. 方式 A（推荐，零改动）

```powershell
scripts\set-relay-env.ps1 -Install
```

写入一个 User 级 Windows 环境变量 `GOOGLE_GEMINI_BASE_URL=https://gemini.smjtools.com`，并把
中转域名的 apex（`smjtools.com`）追加进 User 级 `NO_PROXY`（原因见第 6 节）。

这个变量对三种启动方式同等生效，因为 openworker 从不读取或转写它——纯粹靠进程继承，而 provider
是懒加载的（第一次调用 Gemini 模型时才 `_ensure_client()`），启动顺序不重要：

- CLI (`openworker`) / `openworker-server`：进程启动时直接从 shell 继承环境变量。
- 桌面版（Tauri sidecar）：`surfaces/gui/src-tauri/src/lib.rs:13-14` 的模块文档明确写着
  sidecar 继承本进程的环境变量（"The sidecar inherits this process's environment"）；
  `lib.rs:628-639` 的 `Command::new(server_bin())` 只显式 `.env()` 了
  `COWORKER_EXIT_WITH_PARENT`/`COWORKER_PARENT_PID`/`COWORKER_API_TOKEN` 三个变量，其余变量
  （包括 `GOOGLE_GEMINI_BASE_URL`）走的是子进程默认继承父进程环境这条路——只要启动桌面 app 的
  那个进程本身能看到这个 User 级变量，sidecar 就能看到。

重启对应进程（新开终端 / 重启 GUI）后生效，User 级环境变量不会让已经在运行的进程立刻看到新值。

**作用域警告**：这是 User 级，不是会话级。装完之后本机该 Windows 用户下**所有**使用
google-genai 的进程都会读到它，不只 openworker（同一台机器上的 hermes-agent 也在用这套 SDK）。
中转是透明透传，理论上不改变任何调用方的行为，但介意作用域扩大的话用方式 B。卸载：
`scripts\set-relay-env.ps1 -Uninstall`。

## 3. 方式 B（会话级）

```powershell
scripts\start-openworker-cn.ps1
```

只在当前 PowerShell 进程里设 `$env:GOOGLE_GEMINI_BASE_URL` 和 `$env:NO_PROXY`，不落盘、不写
任何持久环境变量，然后启动 `openworker` 并透传其余参数；加 `-Server` 改为启动
`openworker-server`。关掉这个终端窗口，覆盖随之消失——适合先验证效果、暂不想影响这台机器上
其他进程的场景。

## 4. 方式 C（薄包装，不动 `gemini_provider.py` 原文件）

只有两种情况需要这条路径：① **v1 历史场景**——v1 时代 Worker 若开启可选的 `RELAY_TOKEN`
共享密钥加固，google-genai SDK 不会自己发 `x-relay-token` 头，方式 A/B 单靠环境变量连不通，
就需要这层薄包装往请求里插自定义头。v2 已彻底删除 `RELAY_TOKEN`（准入控制现在是
[07-多用户与用量统计.md](./07-多用户与用量统计.md) 的 KV 名册：查的是 `x-goog-api-key` 本身
的哈希，不需要额外的头），下面代码示例里 `x-relay-token` 的注入在 v2 服务端已经没有对应机制，
纯作历史参考。② 想把中转配置做进 Settings ▸ Models 图形界面，而不是环境变量——这条理由在 v2
下依然成立。

新增一个继承自 `GeminiProvider` 的子类（示例代码，本仓库不落盘这个 `.py` 文件；真要用时自建
`coworker/providers/gemini_relay_provider.py`）：

```python
"""Wraps GeminiProvider to pin http_options at construction time instead of relying on
GOOGLE_GEMINI_BASE_URL — needed once RELAY_TOKEN is set, since the SDK never sends a
custom header on its own.
"""

from typing import Any, Optional

from coworker.providers.gemini_provider import GeminiProvider, resolve_api_key


class GeminiRelayProvider(GeminiProvider):
    def __init__(
        self,
        client: Any = None,
        *,
        default_model: str = "gemini-2.5-flash",
        api_key: Optional[str] = None,
        secrets: Any = None,
        relay_url: str = "https://gemini.smjtools.com",
        relay_token: Optional[str] = None,
    ):
        super().__init__(client, default_model=default_model, api_key=api_key, secrets=secrets)
        self._relay_url = relay_url
        self._relay_token = relay_token

    def _ensure_client(self) -> Any:
        if self._client is None:
            from google import genai

            key = self._api_key or resolve_api_key(self._secrets)
            if not key:
                raise RuntimeError(
                    "No Gemini API key configured. Set GEMINI_API_KEY in the environment, "
                    "or add your key in Manage -> Configure Models."
                )
            http_options: dict[str, Any] = {"base_url": self._relay_url}
            if self._relay_token:
                http_options["headers"] = {"x-relay-token": self._relay_token}
            self._client = genai.Client(api_key=key, http_options=http_options)
        return self._client
```

保留了 `GeminiProvider.__init__` 原本的四个参数（`client`、`default_model`、`api_key`、
`secrets`，见 `gemini_provider.py:402-416`）不变，只追加两个带默认值的关键字参数；
`_ensure_client()` 的懒加载结构和原实现（`gemini_provider.py:418-430`）完全一致，唯一区别是
多传了 `http_options`。

要让 registry 用上这个类，`coworker/providers/registry.py` 还需要两处最小改动：把
`_build_gemini`（`registry.py:144-147`，目前只读 `profile.get("api_key")`）换成读取
`relay_url`/`relay_token` 并构造 `GeminiRelayProvider`；再给 `gemini` 的 `ProviderDescriptor`
（`registry.py:368-383`，目前 `fields` 只有一个 `api_key`）追加对应的两个 `ProviderField`。这两
处改的是 `registry.py` 而不是 `gemini_provider.py` 本身，只有真正需要 `RELAY_TOKEN` 或配置界面
时才走这条路；否则方式 A/B 已经够用。

## 5. 方式 D（上游正规化，供提 PR 参考）

想把 Endpoint 做成 openworker 的一等公民配置项，可以照抄仓库里 OpenAI 兼容家族已经在用的 house
pattern：`_compat()`/`_responses_compat()`（`registry.py:244-322`）给每个 vendor 的
`ProviderDescriptor.fields` 加一个 `ProviderField("base_url", "Endpoint", required=False,
default=<官方地址>, ...)`（BytePlus Ark 就是这么接的，`registry.py:542-550`），对应的 `build()`
闭包（`_openai_compat`/`_openai_responses_compat`，`registry.py:191-241`）里做
`base_url = profile.get("base_url") or default_base_url` 再传进 provider 构造函数。把这个模式
套到 `gemini` descriptor 上需要：① 给 `GeminiProvider.__init__`（`gemini_provider.py:402-416`）
加一个 `base_url: Optional[str] = None` 参数，在 `_ensure_client()`
（`gemini_provider.py:418-430`）里按需拼 `http_options`；② 给 `registry.py:368-383` 的 `gemini`
descriptor 加一个 `base_url` 的 `ProviderField`；③ `_build_gemini`（`registry.py:144-147`）读
`profile.get("base_url")` 传下去。这条路径会真正改动 `gemini_provider.py`，因此列为"供提 PR
参考"，不是本方案的默认路径。

## 6. 常见误区与共存

| 误区 / 场景 | 事实 |
|---|---|
| 把 `GOOGLE_GEMINI_BASE_URL=...` 写进 `state_dir/.env` | 无效。`coworker/secrets.py:46-56` 的 `_load_dotenv()` 只把这个文件读成一个 dict，喂给 `SecretStore.resolve()`（`secrets.py:122-140`）解析存量 profile 里的 `${VAR}` 占位符——从不调用 `os.environ` 写入。必须用 `set-relay-env.ps1`（User 级）或 `start-openworker-cn.ps1`（会话级），不是任何 `.env` 文件。 |
| 和 proxy-guard / `HTTPS_PROXY` 共存 | httpx（google-genai 的传输层）默认 `trust_env=True`，会自动读 `HTTP_PROXY`/`HTTPS_PROXY`。如果本机同时装了 proxy-guard，发往 `gemini.smjtools.com` 的流量也会被拽进本地正向代理——`set-relay-env.ps1`/`start-openworker-cn.ps1` 都会自动把中转域名的 apex（`smjtools.com`）加进 `NO_PROXY`，就是为了排除这种情况；验证方法见 [05-验证与排错.md](./05-验证与排错.md)。 |
| `GEMINI_API_KEY` 要不要改 | 不用。key 解析（`gemini_provider.py:104-115` 的 `resolve_api_key()`：env `GEMINI_API_KEY` → `GOOGLE_API_KEY` → SecretStore）和 base_url 是两条独立逻辑，中转只接管请求目标，不接管认证来源。 |
| Vertex 家族会不会也走中转 | 不会，也不需要。`vertex_provider.py:160-174` 里 Vertex 的 `gemini/` 家族自己构造 `genai.Client(vertexai=True, ...)`（:166-173），再把这个现成的 `sdk` 以 `client=sdk` 传给 `GeminiProvider`（:174），完全绕过 `_ensure_client()`——本方案唯一的接管点。这条路径读的是 `GOOGLE_VERTEX_BASE_URL`，不是 `GOOGLE_GEMINI_BASE_URL`，本方案不覆盖它。 |
