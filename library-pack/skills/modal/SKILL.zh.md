# Modal

## 概述

Modal 是一个用于以无服务器（serverless）方式运行 Python 代码的云平台，重点面向 AI/ML 工作负载。核心能力包括：
- 按需的 **GPU 算力**（T4、L4、A10、L40S、A100、H100、H200、B200）
- **无服务器函数**，可从零自动扩缩容到数千个容器
- 完全用 Python 代码构建的 **自定义容器镜像**
- 通过 Volume 实现的、用于模型权重和数据集的 **持久化存储**
- 用于提供模型和 API 服务的 **Web 端点**
- 通过 cron 或固定间隔运行的 **定时任务**
- 面向低延迟推理的 **亚秒级冷启动**

在 Modal 中，一切都以代码的形式定义——不需要 YAML，也不需要 Dockerfile（不过两者都受支持）。

## 何时使用本技能

在以下情况下使用本技能：
- 在云端部署或提供 AI/ML 模型服务
- 运行 GPU 加速的计算（训练、推理、微调）
- 创建无服务器的 Web API 或端点
- 并行扩展批处理任务
- 调度周期性任务（数据流水线、重新训练、爬取）
- 需要用于模型权重或数据集的持久化云存储
- 想要在自定义容器环境中运行代码
- 构建任务队列或异步任务处理系统

## 安装与认证

### 安装

```bash
uv pip install modal
```

Modal 的 Python SDK 支持 Python 3.10–3.14。本技能针对的是稳定的 `modal>=1.0` API（当前发行版：1.4.x）。

### 认证

在创建新凭据之前，优先使用已有凭据。只需关注下面这两个 Modal 专用变量——不要读取、加载或暴露任何其他环境变量或
`.env` 文件内容：

1. 检查当前环境中是否已经设置了 `MODAL_TOKEN_ID` 和 `MODAL_TOKEN_SECRET`。
2. 如果没有，则只在本地 `.env` 文件中查找这两个键（忽略所有其他条目），并在适合当前工作流的情况下加载它们。
3. 只有在两个来源都无法提供这两个值时，才回退到交互式的 `modal setup` 或生成新令牌。

```bash
modal setup
```

这会打开浏览器进行身份验证。对于 CI/CD 或无图形界面（headless）环境，请使用环境变量：

```bash
export MODAL_TOKEN_ID=<your-token-id>
export MODAL_TOKEN_SECRET=<your-token-secret>
```

如果环境或 `.env` 中尚不存在这些令牌，可在 https://modal.com/settings 生成。

Modal 提供每月 30 美元额度的免费套餐。

**参考资料**：详细的搭建流程和第一个应用的走查参见 `references/getting-started.md`。

## 核心概念

### App 与 Functions

一个 Modal `App` 会把相关的函数分组。使用 `@app.function()` 装饰的函数会在云端远程运行：

```python
import modal

app = modal.App("my-app")

@app.function()
def square(x):
    return x ** 2

@app.local_entrypoint()
def main():
    # .remote() 在云端运行
    print(square.remote(42))
```

用 `modal run script.py` 运行。用 `modal deploy script.py` 部署。

**参考资料**：生命周期钩子、类、`.map()`、`.spawn()` 等内容参见 `references/functions.md`。

### 容器镜像

Modal 从 Python 代码构建容器镜像。推荐使用 `uv` 作为包安装器：

```python
image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install("torch==2.12.0", "transformers==5.9.0", "accelerate==1.13.0")
    .apt_install("git")
)

@app.function(image=image)
def inference(prompt):
    from transformers import pipeline
    pipe = pipeline("text-generation", model="meta-llama/Llama-3-8B")
    return pipe(prompt)
```

镜像的关键方法：
- `.uv_pip_install()` —— 用 uv 安装 Python 包（推荐）
- `.pip_install()` —— 用 pip 安装（备选方案）
- `.apt_install()` —— 安装系统包
- `.run_commands()` —— 在构建期间运行 shell 命令
- `.run_function()` —— 在构建期间运行 Python 代码（例如下载模型权重）
- `.add_local_python_source()` —— 添加本地模块
- `.env()` —— 设置环境变量

**参考资料**：Dockerfile、micromamba、缓存、GPU 构建步骤参见 `references/images.md`。

### GPU 算力

通过 `gpu` 参数请求 GPU：

```python
@app.function(gpu="H100")
def train_model():
    import torch
    device = torch.device("cuda")
    # GPU 训练代码写在这里

# 多个 GPU
@app.function(gpu="H100:4")
def distributed_training():
    ...

# GPU 回退链（fallback chain）
@app.function(gpu=["H100", "A100-80GB", "A100-40GB"])
def flexible_inference():
    ...
```

可用的 GPU：T4、L4、A10、L40S、A100-40GB、A100-80GB、RTX-PRO-6000、H100、H200、B200、B200+

- GPU 一律以**字符串**形式指定（例如 `gpu="H100"`、`gpu="H100:4"`）。旧的 `modal.gpu.*` 对象自 v0.73.31 起已废弃。
- 每个容器最多 8 个 GPU（A10 除外，最多 4 个）
- 推荐 L40S 用于推理（成本/性能均衡，48 GB 显存）
- H100/A100 可在不产生额外费用的情况下自动升级到 H200/A100-80GB
- 使用 `gpu="H100!"` 以阻止自动升级

**参考资料**：GPU 选型指南与多 GPU 训练参见 `references/gpu.md`。

### Volume（持久化存储）

Volume 提供分布式、持久化的文件存储：

```python
vol = modal.Volume.from_name("model-weights", create_if_missing=True)

@app.function(volumes={"/data": vol})
def save_model():
    # 写入挂载路径
    with open("/data/model.pt", "wb") as f:
        torch.save(model.state_dict(), f)

@app.function(volumes={"/data": vol})
def load_model():
    model.load_state_dict(torch.load("/data/model.pt"))
```

- 针对「一次写入、多次读取」的工作负载做了优化（模型权重、数据集）
- CLI 访问方式：`modal volume ls`、`modal volume put`、`modal volume get`
- 每隔几秒后台自动提交
- 可用 `vol.with_mount_options(read_only=True, sub_path="subset")` 以只读方式挂载，或限定挂载到某个子目录

**参考资料**：v2 版本 Volume、并发写入及最佳实践参见 `references/volumes.md`。

### Secret（密钥）

安全地把凭据传递给函数：

```python
@app.function(secrets=[modal.Secret.from_name("my-api-keys")])
def call_api():
    import os
    api_key = os.environ["API_KEY"]
    # 使用该密钥
```

通过 CLI 创建密钥：`modal secret create my-api-keys API_KEY=sk-xxx`

或者从一个 `.env` 文件创建：`modal.Secret.from_dotenv()`

**参考资料**：仪表盘设置、多个密钥以及模板参见 `references/secrets.md`。

### Web 端点

以 Web 端点的形式提供模型和 API 服务：

```python
@app.function()
@modal.fastapi_endpoint()
def predict(text: str):
    return {"result": model.predict(text)}
```

- `modal serve script.py` —— 带热重载和临时 URL 的开发模式
- `modal deploy script.py` —— 带永久 URL 的生产部署
- 支持 FastAPI、ASGI（Starlette、FastHTML）、WSGI（Flask、Django）、WebSocket
- 请求体最大 4 GiB，响应体大小不受限制

**参考资料**：ASGI/WSGI 应用、流式传输、鉴权和 WebSocket 参见 `references/web-endpoints.md`。

### 定时任务

按计划运行函数：

```python
@app.function(schedule=modal.Cron("0 9 * * *"))  # 每天 UTC 上午 9 点
def daily_pipeline():
    # ETL、重新训练、爬取等
    ...

@app.function(schedule=modal.Period(hours=6))
def periodic_check():
    ...
```

用 `modal deploy script.py` 部署以激活该计划。

- `modal.Cron("...")` —— 标准 cron 语法，在多次部署间保持稳定
- `modal.Period(hours=N)` —— 固定间隔，重新部署时会重置
- 在 Modal 仪表盘中监控运行情况

**参考资料**：cron 语法与管理方式参见 `references/scheduled-jobs.md`。

### 扩缩容与并发

Modal 会自动对容器进行扩缩容。可配置上下限：

```python
@app.function(
    max_containers=100,    # 上限
    min_containers=2,      # 保持热启动以降低延迟
    buffer_containers=5,   # 预留容量
    scaledown_window=300,  # 关闭前的空闲秒数
)
def process(data):
    ...
```

用 `.map()` 并行处理输入：

```python
results = list(process.map([item1, item2, item3, ...]))
```

通过 `@modal.concurrent` 为每个容器启用并发请求处理。将 `target_inputs`
（自动扩缩容器的每容器目标值）设置得低于 `max_inputs`（硬上限），以便在扩容时
保留余量：

```python
@app.function()
@modal.concurrent(max_inputs=10, target_inputs=8)
async def handle_request(req):
    ...
```

使用 `Function.with_options()` / `Function.with_concurrency()` /
`Function.with_batching()`（以及 `Cls.with_options()`）可以在调用时重新配置一个
已部署的 Function 或 Cls，而无需重新部署：

```python
Model = modal.Cls.from_name("my-app", "Model")
fast = Model.with_options(gpu="H200", max_containers=20)
fast().generate.remote(prompt)
```

**参考资料**：`.map()`、`.starmap()`、`.spawn()` 及各项限制参见 `references/scaling.md`。

### 资源配置

```python
@app.function(
    cpu=4.0,              # 物理核心数（非 vCPU）
    memory=16384,         # MiB
    ephemeral_disk=51200, # MiB（最多 3 TiB）
    timeout=3600,         # 秒
)
def heavy_computation():
    ...
```

默认值：0.125 个 CPU 核心，128 MiB 内存。按 max(请求值, 实际使用量) 计费。

**参考资料**：限制与计费细节参见 `references/resources.md`。

## 带生命周期钩子的类

用于有状态的工作负载（例如只加载一次模型、然后为多个请求提供服务）：

```python
@app.cls(gpu="L40S", image=image)
class Predictor:
    @modal.enter()
    def load_model(self):
        self.model = load_heavy_model()  # 只在容器启动时运行一次

    @modal.method()
    def predict(self, text: str):
        return self.model(text)

    @modal.exit()
    def cleanup(self):
        ...  # 在容器关闭时运行
```

调用方式：`Predictor().predict.remote("hello")`

## Sandbox（沙箱）

对于运行不受信任或动态生成的代码（例如 AI 智能体输出的代码，或代码解释器），
使用 `modal.Sandbox`——一个由你以编程方式创建和控制的隔离容器，而不是一个被
装饰的 Function：

```python
app = modal.App.lookup("sandbox-demo", create_if_missing=True)

# 隔离容器；为不受信任的工作负载限制出站流量
sb = modal.Sandbox.create(
    app=app,
    image=modal.Image.debian_slim(),
    outbound_cidr_allowlist=["10.0.0.0/8"],
)

# 通过文件系统 API（beta）在容器内外传输文件
sb.filesystem.write_text("print(2 ** 10)\n", "/tmp/job.py")
contents = sb.filesystem.read_text("/tmp/job.py")

sb.terminate()
```

- 使用其 `exec` 方法在沙箱内部运行命令（例如运行 `python /tmp/job.py`），并从返回的进程句柄读取标准输出——参见
  `references/api_reference.md`
- 使用 `outbound_cidr_allowlist=[...]` / `inbound_cidr_allowlist=[...]` 限制连接性
- 用 `sb.snapshot_filesystem()` 对文件系统做快照，以便作为基础镜像复用
- 非常适合代码解释器、智能体工具执行以及按用户隔离的场景

## 常见工作流模式

### GPU 模型推理服务

```python
import modal

app = modal.App("llm-service")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install("vllm")
)

@app.cls(gpu="H100", image=image, min_containers=1)
class LLMService:
    @modal.enter()
    def load(self):
        from vllm import LLM
        self.llm = LLM(model="meta-llama/Llama-3-70B")

    @modal.method()
    @modal.fastapi_endpoint(method="POST")
    def generate(self, prompt: str, max_tokens: int = 256):
        outputs = self.llm.generate([prompt], max_tokens=max_tokens)
        return {"text": outputs[0].outputs[0].text}
```

### 批处理流水线

```python
app = modal.App("batch-pipeline")
vol = modal.Volume.from_name("pipeline-data", create_if_missing=True)

@app.function(volumes={"/data": vol}, cpu=4.0, memory=8192)
def process_chunk(chunk_id: int):
    import pandas as pd
    df = pd.read_parquet(f"/data/input/chunk_{chunk_id}.parquet")
    result = heavy_transform(df)
    result.to_parquet(f"/data/output/chunk_{chunk_id}.parquet")
    return len(result)

@app.local_entrypoint()
def main():
    chunk_ids = list(range(100))
    results = list(process_chunk.map(chunk_ids))
    print(f"Processed {sum(results)} total rows")
```

### 定时数据流水线

```python
app = modal.App("etl-pipeline")

@app.function(
    schedule=modal.Cron("0 */6 * * *"),  # 每 6 小时一次
    secrets=[modal.Secret.from_name("db-credentials")],
)
def etl_job():
    import os
    db_url = os.environ["DATABASE_URL"]
    # 抽取、转换、加载
    ...
```

## CLI 参考

| 命令 | 说明 |
|---------|-------------|
| `modal setup` | 对 Modal 进行身份验证 |
| `modal run script.py` | 运行脚本的本地入口点 |
| `modal serve script.py` | 带热重载的开发服务器 |
| `modal deploy script.py` | 部署到生产环境 |
| `modal volume ls <name>` | 列出某个 Volume 中的文件 |
| `modal volume put <name> <file>` | 把文件上传到 Volume |
| `modal volume get <name> <file>` | 从 Volume 下载文件 |
| `modal secret create <name> K=V` | 创建一个密钥 |
| `modal secret list` | 列出密钥 |
| `modal app list` | 列出已部署的应用 |
| `modal app stop <name>` | 停止一个已部署的应用 |

## 安全说明

- **凭据**： 只需要 `MODAL_TOKEN_ID` 和 `MODAL_TOKEN_SECRET` 即可完成身份验证。不要读取、记录或转发任何其他环境变量或 `.env` 条目。
- **子进程 / 自定义服务器**： 这里的一些模式（多 GPU 训练启动器、`@modal.web_server` 应用）会在构建过程中调用 `subprocess.run`/`subprocess.Popen` 或 shell 命令。参数列表要保持固定且硬编码。绝不要用未经清理的用户输入来构造子进程或 shell 参数——把不受信任的值当作数据（文件、环境变量、标准输入）传递，而不是当作命令参数。
- **不受信任的代码**： 在 `modal.Sandbox`（见上文）中运行用户或模型生成的代码，而不是在常规 Function 中运行，并用 CIDR 白名单限制网络访问。

## 参考文件

各主题的详细文档：

- `references/getting-started.md` —— 安装、认证、第一个应用
- `references/functions.md` —— 函数、类、生命周期钩子、远程执行
- `references/images.md` —— 容器镜像、包安装、缓存
- `references/gpu.md` —— GPU 类型、选型、多 GPU、训练
- `references/volumes.md` —— 持久化存储、文件管理、v2 版本 Volume
- `references/secrets.md` —— 凭据、环境变量、dotenv
- `references/web-endpoints.md` —— FastAPI、ASGI/WSGI、流式传输、鉴权、WebSocket
- `references/scheduled-jobs.md` —— Cron、周期性计划、管理
- `references/scaling.md` —— 自动扩缩容、并发、.map()、限制
- `references/resources.md` —— CPU、内存、磁盘、超时配置
- `references/examples.md` —— 常见用例与模式
- `references/api_reference.md` —— 关键 API 类与方法

当需要超出本概述的详细信息时，请阅读这些文件。
