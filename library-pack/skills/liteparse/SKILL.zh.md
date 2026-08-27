# LiteParse —— 本地文档解析

## 概述

LiteParse 是一个快速、开源的文档解析器（Rust 核心，提供 Python/Node 绑定），专注于**本地、具备版面感知能力**的文本提取，并附带边界框（bounding box）。它不生成 Markdown，也不调用云端 LLM。输出为**纯文本**（保留版面结构）或带有每页 `text_items` 的**结构化 JSON**（包含位置、字体元数据、可选的置信度）。

**版本说明**： 示例基于 **liteparse 2.0.0**（PyPI，2026 年 5 月）。上游的 V1 分支已过时；本技能仅记录 **V2 / main** 分支。

关于与 MarkItDown、`pdf` 技能或 LlamaParse 之间的解析器选型对比，见 `references/choosing_a_parser.md`。

## 何时使用本技能

在需要以下功能时使用 LiteParse：

- 对 PDF 或经转换的 Office/图像文件进行**快速本地解析**，不依赖云服务
- 需要带边界框的**空间化文本**，用于具备版面感知能力的 RAG、引用溯源，或图/表区域相关逻辑
- 对扫描版 PDF 或图像进行 **OCR**（内置 Tesseract，或用户自行运行的 HTTP OCR 服务）
- 为需要"看到"图表、插图或手写内容的多模态 agent 生成**页面截图**（PNG）
- **批量摄取**文献文件夹、补充材料 PDF 或实验方案文库
- 处理**指定页面子集**或**受密码保护**的 PDF

## 何时不使用

| 任务 | 改用 |
|------|-------------|
| 面向 LLM 输入的 Markdown（EPUB、音频、YouTube、HTML） | `markitdown` 技能 |
| 合并/拆分 PDF、表单、水印、旋转 | `pdf` 技能 |
| 密集表格、手写内容、生产级云端流水线 | [LlamaParse](https://docs.cloud.llamaindex.ai/llamaparse/overview)（云服务；需另行注册） |

## 安装

```bash
uv pip install "liteparse==2.0.0"
```

这会安装 Python 绑定以及 **`lit`** 命令行工具。验证安装：

```bash
lit --help
python -c "import liteparse; print(liteparse.__version__)"
```

**可选的系统工具**（用于非 PDF 输入）：

- **LibreOffice** —— Word、Excel、PowerPoint、OpenDocument、CSV/TSV
- **ImageMagick** —— PNG、JPEG、TIFF、WebP、SVG 等

安装命令见 `references/ocr_and_formats.md`。

**Node.js / TypeScript**（可选）：`npm i @llamaindex/liteparse` —— 见 `references/api_reference.md`。

---

## 快速开始

### Python

```python
from liteparse import LiteParse

parser = LiteParse(quiet=True)
result = parser.parse("paper.pdf")
print(result.text)

for page in result.pages:
    print(f"Page {page.page_num}: {len(page.text_items)} items")
```

### CLI

```bash
# Layout-preserved text (default)
lit parse paper.pdf

# Structured JSON with bounding boxes
lit parse paper.pdf --format json -o paper.json

# Disable OCR on text-native PDFs (faster)
lit parse paper.pdf --no-ocr
```

---

## 核心工作流

### 1. 解析为保留版面结构的文本

最适合快速获取整篇文档的文本，或供不需要坐标信息的分块（chunker）工具使用。

```python
parser = LiteParse(ocr_enabled=True, quiet=True)
result = parser.parse("document.pdf")
full_text = result.text
```

```bash
lit parse document.pdf -o output.txt
```

### 2. 解析为结构化 JSON（带边界框）

适用于构建具备版面感知能力的 RAG、高亮标注来源区域，或将文本与截图相关联的场景。

```python
import json
from liteparse import LiteParse

parser = LiteParse(output_format="json", quiet=True)
result = parser.parse("document.pdf")

# Programmatic access
for page in result.pages:
    for item in page.text_items:
        bbox = (item.x, item.y, item.width, item.height)
        # item.text, item.confidence, item.font_name, item.font_size
```

```bash
lit parse document.pdf --format json -o document.json
```

JSON 字段结构见 `references/output_formats.md`。

### 3. 解析指定页面

```python
parser = LiteParse(target_pages="1-5,10,15-20", quiet=True)
result = parser.parse("long_paper.pdf")
```

```bash
lit parse long_paper.pdf --target-pages "1-5,10"
```

### 4. 从字节数据或标准输入解析

适用于文件上传、S3 下载，或对远程 PDF 进行管道处理的场景。

```python
with open("document.pdf", "rb") as f:
    result = parser.parse(f.read())
```

```bash
curl -sL https://example.com/report.pdf | lit parse -
```

### 5. 为多模态 agent 生成页面截图

截图能够捕捉纯文本提取遗漏的视觉内容（插图、复杂表格、手写内容）。

```python
from pathlib import Path

parser = LiteParse(dpi=150, quiet=True)
shots = parser.screenshot("document.pdf", page_numbers=[1, 2, 3])
out = Path("screenshots")
out.mkdir(exist_ok=True)
for s in shots:
    (out / f"page_{s.page_num}.png").write_bytes(s.image_bytes)
```

```bash
lit screenshot document.pdf --target-pages "1,3,5" -o ./screenshots
lit screenshot document.pdf --dpi 300 -o ./screenshots
```

当某个 agent 需要同时获取相同页面的坐标信息和像素图像时，可结合使用 **JSON 解析 + 截图**。

### 6. 批量解析整个目录

对于大规模语料库，优先使用 CLI（支持并行 OCR 工作进程）或随附的脚本。

```bash
lit batch-parse ./papers ./parsed --format json --recursive
lit batch-parse ./papers ./parsed --extension .pdf --no-ocr
```

```bash
python scripts/batch_parse_dir.py ./papers ./parsed --format json --recursive
```

关于不涉及任何网络调用的 Python 批处理封装脚本，见 `scripts/batch_parse_dir.py`。

### 7. OCR 配置

OCR **默认开启**。Tesseract 已内置；基础的英文 OCR 无需额外安装。

```python
parser = LiteParse(
    ocr_enabled=True,
    ocr_language="eng",       # Tesseract codes: fra, deu, etc.
    num_workers=4,            # parallel OCR (default: CPU cores - 1)
    dpi=150,                  # higher DPI → better OCR, slower
)
```

```bash
lit parse scan.pdf --ocr-language fra
lit parse scan.pdf --no-ocr
lit parse scan.pdf --ocr-server-url http://localhost:8080/ocr
```

**离线/隔离网络环境**： 将 `TESSDATA_PREFIX` 设置为存放 `.traineddata` 文件的目录，或传入 `--tessdata-path`。详情见 `references/ocr_and_formats.md`。

### 8. 加密 PDF

```python
parser = LiteParse(password="secret", quiet=True)
result = parser.parse("protected.pdf")
```

```bash
lit parse protected.pdf --password secret
```

### 9. 按短语搜索文本条目

合并相邻的条目，并为某个短语（例如章节标题）返回合并后的边界框。

```python
from liteparse import search_items

page = result.get_page(1)
matches = search_items(page.text_items, "Materials and Methods", case_sensitive=False)
```

---

## 多格式输入支持

| 类别 | 扩展名（举例） | 依赖要求 |
|----------|----------------------|-------------|
| PDF | `.pdf` | 原生支持 |
| Office | `.docx`、`.xlsx`、`.pptx`、`.doc`、`.odt`、… | LibreOffice |
| 图像 | `.png`、`.jpg`、`.tiff`、`.webp`、`.svg`、… | ImageMagick |

这些文件会在内部先被转换为 PDF，然后再进行解析。如果转换所需的工具缺失，解析会失败并给出可据以行动的错误信息——安装相应依赖后重试即可。

---

## 性能建议

- 对原生数字 PDF 使用 **`--no-ocr`** —— 提速效果最显著
- 使用 **`target_pages`** —— 只解析方法/补充材料部分
- 使用 **`num_workers`** —— 在多个 CPU 核心上并行扩展 OCR
- 使用 **`max_pages`** —— 限制超大文件的处理规模（默认 1000）
- 使用 **`lit batch-parse`** —— 配合 `--recursive` 和 `--extension` 进行目录级批量任务
- 在 OCR 质量已经足够的情况下，降低 **`dpi`**（例如设为 100）

---

## 参考文件

| 文件 | 何时阅读 |
|------|-----------|
| `references/choosing_a_parser.md` | 不确定该用 LiteParse、MarkItDown、pdf 还是 LlamaParse 时 |
| `references/api_reference.md` | Python/TypeScript API、类型定义、`search_items` |
| `references/cli_reference.md` | `lit` 命令的完整参数列表 |
| `references/output_formats.md` | JSON 模式（schema）、边界框、置信度分数 |
| `references/ocr_and_formats.md` | Tesseract、HTTP OCR、LibreOffice、ImageMagick |

---

## 故障排查

| 问题 | 解决方法 |
|-------|-----|
| Office 文件解析失败 | 安装 LibreOffice；确保 `soffice` 在 PATH 中（Windows 上需添加 LibreOffice 的 `program` 目录） |
| 图像解析失败 | 安装 ImageMagick；核实 `convert` 或 `magick` 命令可正常运行 |
| OCR 质量不佳 | 提高 `--dpi`；尝试指定 `--ocr-language`；或改用 HTTP OCR 服务 |
| OCR 速度过慢 | 若不需要则使用 `--no-ocr`；减少页数；提高 `num_workers` |
| 隔离网络环境下的 OCR | `export TESSDATA_PREFIX=/path/to/tessdata`，或使用 `--tessdata-path` |
| 传入字节数据时出现 `ParseError` | 确认输入是有效的 PDF 字节数据（Office 文件的字节数据需要文件路径 + 转换步骤） |

---

## 资源

- **GitHub**：https://github.com/run-llama/liteparse
- **文档**：https://developers.llamaindex.ai/liteparse/
- **PyPI**：https://pypi.org/project/liteparse/2.0.0/
- **npm**：https://www.npmjs.com/package/@llamaindex/liteparse
- **OCR API 规范**：https://github.com/run-llama/liteparse/blob/main/OCR_API_SPEC.md
