# Open Notebook

## 概述

Open Notebook 是一个开源、自托管的替代方案，用来替代 Google 的
NotebookLM，能让研究人员组织资料、生成 AI 驱动的洞见、制作播客,
并与自己的文档进行有上下文感知能力的对话——同时保持完整的数据
隐私性。

与没有面向企业版之外用户开放 API 的 Google NotebookLM 不同，
Open Notebook 提供了一套完善的 REST API，支持 16 个以上的 AI
提供商，并且完全运行在你自己的基础设施上。

**相比 NotebookLM 的主要优势**：
- 提供完整的 REST API，可用于编程访问和自动化
- 可在 16 个以上的 AI 提供商中自由选择（不局限于 Google 的模型）
- 支持 1 到 4 位可自定义说话人的多说话人播客生成（相比之下 NotebookLM
  限制为 2 位说话人）
- 通过自托管实现完整的数据主权
- 开源且完全可扩展（MIT 许可证）

**代码仓库**： https://github.com/lfnovo/open-notebook

## 快速开始

### 前置条件

- 已安装 Docker Desktop
- 至少一个 AI 提供商的 API 密钥（或使用本地 Ollama 以进行免费的
  本地推理）

### 安装

使用 Docker Compose 部署 Open Notebook：

```bash
# 下载 docker-compose 文件
curl -o docker-compose.yml https://raw.githubusercontent.com/lfnovo/open-notebook/main/docker-compose.yml

# 设置必需的加密密钥
export OPEN_NOTEBOOK_ENCRYPTION_KEY="your-secret-key-here"

# 启动各项服务
docker-compose up -d
```

访问该应用：
- **前端界面**： http://localhost:8502
- **REST API**： http://localhost:5055
- **API 文档**： http://localhost:5055/docs

### 配置 AI 提供商

启动之后，至少配置一个 AI 提供商：

1. 在界面中导航到 **Settings > API Keys**
2. 添加你所选用的提供商（OpenAI、Anthropic 等）的凭据
3. 测试连接并发现可用的模型
4. 注册模型，以便在整个平台中使用

也可以通过 REST API 进行配置：

```python
import requests

BASE_URL = "http://localhost:5055/api"

# 为某个 AI 提供商添加一个凭据
response = requests.post(f"{BASE_URL}/credentials", json={
    "provider": "openai",
    "name": "My OpenAI Key",
    "api_key": "sk-..."
})
credential = response.json()

# 发现可用的模型
response = requests.post(
    f"{BASE_URL}/credentials/{credential['id']}/discover"
)
discovered = response.json()

# 注册已发现的模型
requests.post(
    f"{BASE_URL}/credentials/{credential['id']}/register-models",
    json={"model_ids": [m["id"] for m in discovered["models"]]}
)
```

## 核心功能

### 笔记本（Notebooks）
把研究资料组织到不同的笔记本中，每个笔记本都包含来源、笔记和聊天
会话。

```python
import requests

BASE_URL = "http://localhost:5055/api"

# 创建一个笔记本
response = requests.post(f"{BASE_URL}/notebooks", json={
    "name": "Cancer Genomics Research",
    "description": "Literature review on tumor mutational burden"
})
notebook = response.json()
notebook_id = notebook["id"]
```

### 来源（Sources）
接收多种类型的内容，包括 PDF、视频、音频文件、网页，以及 Office
文档。来源会被处理以支持全文和向量搜索。

```python
# 添加一个网页 URL 来源
response = requests.post(f"{BASE_URL}/sources", data={
    "url": "https://arxiv.org/abs/2301.00001",
    "notebook_id": notebook_id,
    "process_async": "true"
})
source = response.json()

# 上传一个 PDF 文件
with open("paper.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/sources",
        data={"notebook_id": notebook_id},
        files={"file": ("paper.pdf", f, "application/pdf")}
    )
```

### 笔记（Notes）
创建和管理与笔记本相关联的笔记（人工撰写或 AI 生成）。

```python
# 创建一条人工撰写的笔记
response = requests.post(f"{BASE_URL}/notes", json={
    "title": "Key Findings",
    "content": "TMB correlates with immunotherapy response in NSCLC...",
    "note_type": "human",
    "notebook_id": notebook_id
})
```

### 具有上下文感知能力的聊天
与你的研究资料进行对话，AI 会引用来源。

```python
# 创建一个聊天会话
session = requests.post(f"{BASE_URL}/chat/sessions", json={
    "notebook_id": notebook_id,
    "title": "TMB Discussion"
}).json()

# 发送一条带有来源上下文的消息
response = requests.post(f"{BASE_URL}/chat/execute", json={
    "session_id": session["id"],
    "message": "What are the key biomarkers for immunotherapy response?",
    "context": {"include_sources": True, "include_notes": True}
})
```

### 搜索
使用全文搜索或向量（语义）搜索来跨所有资料进行检索。

```python
# 在知识库中进行向量搜索
results = requests.post(f"{BASE_URL}/search", json={
    "query": "tumor mutational burden immunotherapy",
    "search_type": "vector",
    "limit": 10
}).json()

# 提出一个问题，获得 AI 驱动的回答
answer = requests.post(f"{BASE_URL}/search/ask/simple", json={
    "query": "How does TMB predict checkpoint inhibitor response?"
}).json()
```

### 播客生成
根据研究资料生成带有 1 到 4 位可自定义说话人的专业多说话人播客。

```python
# 生成一集播客
job = requests.post(f"{BASE_URL}/podcasts/generate", json={
    "notebook_id": notebook_id,
    "episode_profile_id": episode_profile_id,
    "speaker_profile_ids": [speaker1_id, speaker2_id]
}).json()

# 检查生成状态
status = requests.get(f"{BASE_URL}/podcasts/jobs/{job['job_id']}").json()

# 生成完成后下载音频
audio = requests.get(
    f"{BASE_URL}/podcasts/episodes/{status['episode_id']}/audio"
)
```

### 内容变换
对内容应用自定义的、AI 驱动的变换，用于摘要、提取和分析。

```python
# 创建一个自定义变换
transform = requests.post(f"{BASE_URL}/transformations", json={
    "name": "extract_methods",
    "title": "Extract Methods",
    "description": "Extract methodology details from papers",
    "prompt": "Extract and summarize the methodology section...",
    "apply_default": False
}).json()

# 在一段文本上执行该变换
result = requests.post(f"{BASE_URL}/transformations/execute", json={
    "transformation_id": transform["id"],
    "input_text": "...",
    "model_id": "model_id_here"
}).json()
```

## 受支持的 AI 提供商

Open Notebook 通过 Esperanto 库支持 16 个以上的 AI 提供商：

| 提供商 | 大语言模型（LLM） | 嵌入（Embedding） | 语音转文本 | 文本转语音 |
|----------|-----|-----------|----------------|----------------|
| OpenAI | 是 | 是 | 是 | 是 |
| Anthropic | 是 | 否 | 否 | 否 |
| Google GenAI | 是 | 是 | 否 | 是 |
| Vertex AI | 是 | 是 | 否 | 是 |
| Ollama | 是 | 是 | 否 | 否 |
| Groq | 是 | 否 | 是 | 否 |
| Mistral | 是 | 是 | 否 | 否 |
| Azure OpenAI | 是 | 是 | 否 | 否 |
| DeepSeek | 是 | 否 | 否 | 否 |
| xAI | 是 | 否 | 否 | 否 |
| OpenRouter | 是 | 否 | 否 | 否 |
| ElevenLabs | 否 | 否 | 是 | 是 |
| Perplexity | 是 | 否 | 否 | 否 |
| Voyage | 否 | 是 | 否 | 否 |

## 环境变量

Docker 部署所需的关键配置变量：

| 变量 | 说明 | 默认值 |
|----------|-------------|---------|
| `OPEN_NOTEBOOK_ENCRYPTION_KEY` | **必需**。 用于加密已存储凭据的密钥 | 无 |
| `SURREAL_URL` | SurrealDB 连接 URL | `ws://surrealdb:8000/rpc` |
| `SURREAL_NAMESPACE` | 数据库命名空间 | `open_notebook` |
| `SURREAL_DATABASE` | 数据库名称 | `open_notebook` |
| `OPEN_NOTEBOOK_PASSWORD` | 可选的界面密码保护 | 无 |

## API 参考

REST API 位于 `http://localhost:5055/api`，交互式文档位于 `/docs`。

核心端点分组：
- `/api/notebooks` —— 笔记本的增删改查以及来源关联
- `/api/sources` —— 来源的接收、处理与检索
- `/api/notes` —— 笔记管理
- `/api/chat/sessions` —— 聊天会话管理
- `/api/chat/execute` —— 聊天消息执行
- `/api/search` —— 全文与向量搜索
- `/api/podcasts` —— 播客生成与管理
- `/api/transformations` —— 内容变换流水线
- `/api/models` —— AI 模型配置与发现
- `/api/credentials` —— 提供商凭据管理

完整的 API 参考（包含所有端点及请求/响应格式）参见
`references/api_reference.md`。

## 架构

Open Notebook 使用现代技术栈：
- **后端**： 基于 FastAPI 的 Python
- **数据库**： SurrealDB（文档型 + 关系型）
- **AI 集成**： LangChain 配合 Esperanto 多提供商库
- **前端**： 基于 React 的 Next.js
- **部署方式**： 带持久化卷的 Docker Compose

## 重要说明

- Open Notebook 需要 Docker 才能部署
- 至少必须配置一个 AI 提供商，AI 功能才能正常工作
- 若要进行免费的本地推理、不产生 API 费用，可使用 Ollama
- `OPEN_NOTEBOOK_ENCRYPTION_KEY` 必须在首次启动之前设置，并在多次
  重启之间保持一致
- 所有数据都存储在本地的 Docker 卷中，以实现完整的数据主权
