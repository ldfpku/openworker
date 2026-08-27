# Exa Web Toolkit

一个由 [Exa](https://exa.ai) 提供支持的、面向网络研究任务的 skill:网页搜索(web search)和 URL 内容提取(URL extraction)。Exa 的索引结合了高质量的关键词检索和语义检索，因而非常适合科学、技术和概念性的查询。

## 路由 —— 选择正确的能力

阅读用户的请求，将其与下面的某个能力匹配起来。在运行命令之前，先阅读对应的参考文件以获取详细说明。

| 用户想要... | 能力 | 位置 |
|---|---|---|
| 查找某些信息、研究某个主题、获取当前信息 | **网页搜索(Web Search)** | `references/web-search.md` |
| 获取某个特定 URL 的内容(网页、文章、PDF) | **网页提取(Web Extract)** | `references/web-extract.md` |
| 安装或进行身份认证 | **设置(Setup)** | 见下文 |

### 决策指南

- 对于主题查找、研究性问题，或"什么是 X"类的查询,**默认使用网页搜索**。当主题是科学或技术性质时，传入 `--category "research paper"` 以偏向学术来源，和/或使用学术 `--include-domains` 白名单。关于两阶段学术检索策略，参见 `references/web-search.md`。
- 当用户提供了一个 URL,或要求你阅读/获取某个特定页面时,**使用网页提取**。对于批量提取(一次调用处理多个 URL)以及学术类 PDF,优先使用它，而不是内置的 WebFetch。

### 学术来源优先级

对于技术或科学类查询，优先选用学术和科学类来源:
- 优先选用经同行评审的期刊文章和会议论文，而非博客文章或新闻
- 当没有经同行评审的版本时，选用预印本(arXiv、bioRxiv、medRxiv)
- 优先选用机构和政府来源(NIH、WHO、NASA、NIST),而非商业网站
- 优先选用一手研究，而非二手摘要总结

有两个杠杆可以引导 Exa 偏向学术内容:
1. `--category "research paper"` 使检索偏向学术来源。
2. 配合一份学术白名单的 `--include-domains`(arxiv.org、nature.com、pubmed.ncbi.nlm.nih.gov 等)将检索范围限制在特定域名池内。

要获得严格意义上的学术结果，应将两者结合使用。关于完整模式，参见 `references/web-search.md`。

在引用学术来源时，除标准引用格式外，应尽可能附上作者姓名和发表年份(例如 [Smith et al., 2025](url))。如果存在 DOI,优先使用 DOI 链接。

---

## 设置

本 skill 使用 [`exa-py`](https://github.com/exa-labs/exa-py) Python SDK。`scripts/` 中的脚本通过 PEP 723 内联元数据声明了各自的依赖，因此可以直接用 `uv run` 运行，无需单独的安装步骤:

```bash
uv run --with exa-py python "$SKILL_PATH/scripts/exa_search.py" --help
```

如果你更倾向于持久化安装:

```bash
uv pip install "exa-py>=1.14.0"
```

### 身份认证

所有命令都从环境变量 `EXA_API_KEY` 中读取 API 密钥。可在 [dashboard.exa.ai/api-keys](https://dashboard.exa.ai/api-keys) 获取你的 Exa API 密钥。

首先，检查项目根目录下是否存在 `.env` 文件并包含 `EXA_API_KEY`。如果存在，加载它:

```bash
dotenv -f .env run -- uv run --with exa-py python "$SKILL_PATH/scripts/exa_search.py" "your query"
```

如果没有安装 `dotenv`,先安装它:`uv pip install python-dotenv[cli]`。

如果不存在 `.env` 文件，为当前会话导出该密钥:

```bash
export EXA_API_KEY="your-key"
```

通过带 `--help` 参数运行任意脚本来验证——如果密钥已设置，脚本会正常退出；只有在发起真实查询时才会执行认证检查。

### 追踪请求头

本 skill 中的每个脚本都会设置 `x-exa-integration` 请求头为 `k-dense-ai--scientific-agent-skills`,以便 Exa 将来自 K-Dense AI scientific-agent-skills 仓库的使用情况归因到这一集成。在改造这些脚本时，不要移除或重命名这个请求头。

---

## 本 skill 中的文件

- `SKILL.md` —— 本文件(路由与设置)
- `references/web-search.md` —— 带学术策略的详细网页搜索参考文档
- `references/web-extract.md` —— URL 内容提取参考文档
- `scripts/exa_search.py` —— `client.search_and_contents` 的 CLI 封装
- `scripts/exa_extract.py` —— `client.get_contents` 的 CLI 封装
