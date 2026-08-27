# Pyzotero

Pyzotero 是 [Zotero API v3](https://www.zotero.org/support/dev/web_api/v3/start) 的一个 Python 封装库。用它来以编程方式管理 Zotero 文献库:读取条目和文集(collection)、创建和更新参考文献、上传附件、管理标签，以及导出引文。

**当前上游版本**: pyzotero 1.13.0(PyPI,2026 年 5 月)。文档:[pyzotero.readthedocs.io](https://pyzotero.readthedocs.io/en/latest/)。

## 身份验证配置

**所需凭据**——从 https://www.zotero.org/settings/keys 获取:
- **User ID(用户 ID)**:显示为 "Your userID for use in API calls"
- **API Key(API 密钥)**:在 https://www.zotero.org/settings/keys/new 创建
- **Library ID(文献库 ID)**:对于群组文献库，是群组 URL 中 `/groups/` 后面的那个整数

把凭据存储在环境变量或 `.env` 文件中:
```
ZOTERO_LIBRARY_ID=your_user_id
ZOTERO_API_KEY=your_api_key
ZOTERO_LIBRARY_TYPE=user  # or "group"
```

完整的配置细节参见 [references/authentication.md](references/authentication.md)。

## 安装

```bash
uv add pyzotero              # Web API client
uv add "pyzotero[cli]"       # + local CLI (Zotero 7)
uv add "pyzotero[mcp]"       # + MCP server for LLM clients (Zotero 7)
```

## 快速开始

```python
import os
from pyzotero import Zotero

zot = Zotero(
    library_id=os.environ['ZOTERO_LIBRARY_ID'],
    library_type=os.environ.get('ZOTERO_LIBRARY_TYPE', 'user'),
    api_key=os.environ['ZOTERO_API_KEY'],
)

# Retrieve top-level items (returns 100 by default)
items = zot.top(limit=10)
for item in items:
    print(item['data']['title'], item['data']['itemType'])

# Search by keyword
results = zot.items(q='machine learning', limit=20)

# Retrieve all items (use everything() for complete results)
all_items = zot.everything(zot.items())
```

## 核心概念

- 一个 `Zotero` 实例绑定到单个文献库(用户库或群组库)。所有方法都作用于该文献库。
- 条目数据存放在 `item['data']` 中。通过 `item['data']['title']`、`item['data']['creators']` 这样的方式访问字段。
- Pyzotero 默认返回 100 个条目(API 本身的默认值是 25)。使用 `zot.everything(zot.items())` 获取全部条目。
- 写操作方法在成功时返回 `True`,失败则抛出 `ZoteroError`。

## 参考文件

| 文件 | 内容 |
|------|------|
| [references/authentication.md](references/authentication.md) | 凭据、文献库类型、本地模式 |
| [references/read-api.md](references/read-api.md) | 检索条目、文集、标签、群组 |
| [references/search-params.md](references/search-params.md) | 过滤、排序、搜索参数 |
| [references/write-api.md](references/write-api.md) | 创建、更新、删除条目 |
| [references/collections.md](references/collections.md) | 文集的增删改查操作 |
| [references/tags.md](references/tags.md) | 标签的访问与管理 |
| [references/files-attachments.md](references/files-attachments.md) | 文件下载与附件上传 |
| [references/exports.md](references/exports.md) | BibTeX、CSL-JSON、参考文献列表导出 |
| [references/pagination.md](references/pagination.md) | follow()、everything()、生成器 |
| [references/full-text.md](references/full-text.md) | 全文内容索引与访问 |
| [references/saved-searches.md](references/saved-searches.md) | 已保存搜索的管理 |
| [references/cli.md](references/cli.md) | 命令行接口(本地 Zotero 7) |
| [references/mcp.md](references/mcp.md) | 面向 LLM 客户端的 MCP 服务器(本地 Zotero 7) |
| [references/error-handling.md](references/error-handling.md) | 错误与异常处理 |

## 常见用法模式

### 获取并修改一个条目
```python
item = zot.item('ITEMKEY')
item['data']['title'] = 'New Title'
zot.update_item(item)
```

### 从模板创建一个条目
```python
template = zot.item_template('journalArticle')
template['title'] = 'My Paper'
template['creators'][0] = {'creatorType': 'author', 'firstName': 'Jane', 'lastName': 'Doe'}
zot.create_items([template])
```

### 导出为 BibTeX
```python
zot.add_parameters(format='bibtex')
bibtex = zot.top(limit=50)
# bibtex is a bibtexparser BibDatabase object
print(bibtex.entries)
```

### 本地模式(只读，无需 API 密钥)
```python
zot = Zotero(library_id='123456', library_type='user', local=True)
items = zot.items()
```

### 本地 Zotero 7(CLI 或 MCP,无需 API 密钥)

对于搜索本地正在运行的 Zotero 桌面应用(包括全文 PDF 搜索),应使用 CLI 或 MCP 服务器，而不是 Web API。两者都要求启用了本地 API 访问的 Zotero 7。参见 [references/cli.md](references/cli.md) 和 [references/mcp.md](references/mcp.md)。
