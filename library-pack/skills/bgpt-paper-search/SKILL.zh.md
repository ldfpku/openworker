# BGPT Paper Search（BGPT 论文检索）

## 概述

BGPT 是一个远程 MCP 服务器，用于检索一个精心构建的科学论文数据库，该数据库由从全文研究中提取出的原始实验数据构建而成。与只返回标题和摘要的传统文献数据库不同，BGPT 会返回从论文实际内容中提取出的结构化数据——方法、定量结果、样本量、质量评估，以及每篇论文 25 个以上的元数据字段。

## 何时使用本技能

在以下情形使用本技能：
- 检索带有具体实验细节的科学论文
- 开展系统性或范围性的文献综述
- 在多项研究中查找定量结果、样本量或效应量
- 比较不同研究中使用的方法学
- 查找带有质量评分或证据分级的论文
- 需要来自全文论文的结构化数据（而不仅仅是摘要）
- 为荟萃分析（meta-analyses）或临床指南构建证据表

## 环境设置

BGPT 是一个远程 MCP 服务器——无需本地安装。使用前请先在你的代理（agent）的 MCP 设置中进行配置；本技能指示代理调用 `search_papers` 这个 MCP 工具，但本技能本身并不会启用 MCP 访问权限。

### Claude Desktop / Claude Code

添加到你的 MCP 配置中：

```json
{
  "mcpServers": {
    "bgpt": {
      "command": "npx",
      "args": ["mcp-remote", "https://bgpt.pro/mcp/sse"]
    }
  }
}
```

### npm（备选方式）

```bash
npx bgpt-mcp
```

## 使用方法

配置好 BGPT MCP 服务器后，通过代理的 MCP 接口（而非通过 Bash）调用其 `search_papers` 工具：

```
Search for papers about: "CRISPR gene editing efficiency in human cells"
```

服务器会返回结构化的结果，包括：
- **标题、作者、期刊、年份、DOI**
- **方法**：实验技术、模型、方案
- **结果**：包含定量数据的关键发现
- **样本量**：受试者/样本数量
- **质量评分**：研究质量评估
- **结论**：作者的结论及其意义

## 定价

- **免费档位**：每个网络 50 次检索，无需 API key
- **付费档位**：使用来自 [bgpt.pro/mcp](https://bgpt.pro/mcp) 的 API key，每条结果 $0.01
