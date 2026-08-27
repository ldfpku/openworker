# DOCX 的创建、编辑与分析

一个 `.docx` 文件本质上是一个包含 XML 文件的 ZIP 归档。请根据任务选择相应的处理方式:

| 任务 | 处理方式 |
|---|---|
| **创建**新文档 | 编写一个 `docx`(npm)脚本——注意事项见下文 |
| **编辑**已有文档 | `unzip` → 编辑 `word/document.xml` → `zip`(docx-js 无法打开已有文件) |
| **读取**内容 | `pandoc -t markdown file.docx` |

> 下文中的脚本路径均相对于本技能所在目录。

## 使用 docx-js 创建文档——注意事项

`docx` 已经预先安装——不要先运行 `npm install`;直接编写脚本并 `require('docx')`。只有在该 require 失败时，才执行 `npm install docx`。模型本身了解该 API;以下是一些容易踩的坑:

- **页面大小默认是 A4**。 对于美式信纸(US Letter),需设置 `page: { size: { width: 12240, height: 15840 } }`(单位为 DXA;1440 = 1 英寸)。
- **横向布局(Landscape)**: 传入纵向的尺寸，并设置 `orientation: PageOrientation.LANDSCAPE`——docx-js 会在内部自动交换宽高。
- **表格需要双重宽度设置**: 既要在表格上设置 `columnWidths`,也要在每个单元格上设置 `width`,两者都使用 `WidthType.DXA`(使用 PERCENTAGE 会在 Google Docs 中出错)。各列宽度之和必须等于表格宽度。
- **表格底纹**: 使用 `ShadingType.CLEAR`,绝不要使用 `SOLID`(会渲染成黑色)。
- **列表**: 绝不要直接插入字面量的 `•` 符号；应使用带有 `LevelFormat.BULLET` 的 `numbering` 配置。
- **`ImageRun` 需要指定 `type:`**(如 `"png"`、`"jpg"` 等)。
- **`PageBreak` 必须位于一个 `Paragraph` 内部。**
- **绝不要使用 `\n`**——应使用单独的 `Paragraph` 元素。
- **目录(TOC)**: 标题必须使用内置的 `HeadingLevel.*`;自定义标题样式需要设置 `outlineLevel`,否则不会出现在目录中。
- **不要用表格来充当水平分隔线**——应改用段落的下边框。
- **点状引导线/同一行内右对齐**: 在 `TextRun` 内使用 `PositionalTab`(`alignment: PositionalTabAlignment.RIGHT`、`leader: PositionalTabLeader.DOT`),而不是用字面量的 `.` 或空格填充。

## 校验输出结果

写出一个 `.docx` 文件后，渲染它并实际查看:

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.docx
pdftoppm -jpeg -r 100 output.pdf page
ls page-*.jpg   # then Read the images
```

`pdftoppm` 会将页码按页数的位数补零对齐(`page-01.jpg`……`page-12.jpg`)。

## 编辑已有文档

旧版 `.doc` 文件必须先转换:`python scripts/office/soffice.py --headless --convert-to docx file.doc`。

```bash
unzip -q doc.docx -d unpacked/
find unpacked -type l -delete   # strip symlink entries — docx from external parties is untrusted
python scripts/merge_runs.py unpacked/   # coalesce fragmented runs so text is findable
# edit unpacked/word/document.xml in place — do NOT reformat or pretty-print
(cd unpacked && rm -f ../out.docx && zip -Xr ../out.docx .)
python scripts/office/validate.py out.docx --original doc.docx   # XSD checks; --auto-repair fixes common issues
# redlining? add --author "<the name you redlined under>" to check every edit is tracked
```

Word 会把文本拆分到许多个 `<w:r>` run 中(修订 ID、拼写检查标记),因此文档中肉眼可见的一段短语，在 XML 里往往并不是一个连续的字符串。`merge_runs.py` 会在不改变内容或渲染效果的前提下，合并 `word/document.xml` 中相邻且格式相同的 run;它也可以直接接受一个 `.docx` 文件(`python scripts/merge_runs.py doc.docx -o merged.docx`)。

**修订痕迹(Tracked changes)**: 在进行修订(redlining)时，使用 `--author "<the name you redlined under>"` 进行校验(需要配合 `--original`)——它会报告任何你修改了却没有用 `<w:ins>`/`<w:del>` 包裹的文本，这种情况很容易在不经意间发生，而且在「已接受」视图下是看不出来的。用带有 `w:id`、`w:author`、`w:date` 属性的 `<w:ins>`/`<w:del>` 包裹相应的 run。在 `<w:del>` 内部，文本元素是 `<w:delText>`,而不是 `<w:t>`。一个被删除的段落标记(`<w:pPr><w:rPr><w:del w:id=".." w:author=".." w:date=".."/></w:rPr></w:pPr>`)的含义是「把本段合并进下一段」——因此，要彻底删除一个段落，除了这个标记之外，还需要用 `<w:del>` 包裹段内的每一个 run。`<w:del/>` 必须出现在 rPr 其他子元素之前；它们的顺序是由 schema 强制规定的。

要生成一份已接受全部修订痕迹的干净副本:`python scripts/accept_changes.py in.docx out.docx`。

接受一个被删除的段落标记，应当会把该段落与下一段合并，因此一个其内所有 run 都被删除的段落应当整个消失。Word 会这样处理；但 `accept_changes.py` 和 `pandoc --track-changes=accept` 并不总是如此。二者失败的方式是一样的——它们会去除被删除的文本，但会遗留下已经清空的段落，如果该段落原本是自动编号的项目符号，这就会显得像一个多余的空白项目符号:

- `pandoc --track-changes=accept` 从不合并段落。
- `accept_changes.py`(LibreOffice)会正确地合并段落，除非被删除的段落后面紧跟着一个空的间隔段落。

在任意一种视图下出现的空白项目符号，都是该视图本身产生的伪影(artifact),而不是文档本身的缺陷。请在 XML 中检查段落删除的情况。

## 批注(Comments)

批注需要六个相互链接的文件。使用辅助脚本——如果你同时还要编辑 `document.xml`,使用目录模式(可以省去一次 unzip/rezip 循环),否则使用直接对 `.docx` 操作的模式:

```bash
# Against an already-unpacked directory (preferred when also placing markers)
python scripts/comment.py unpacked/ "Fees & expenses cap is too low"
python scripts/comment.py unpacked/ "Agreed" --parent 0

# Against a .docx directly
python scripts/comment.py contract.docx "This cap is too low" -o annotated.docx
```

该脚本会写出 `comments.xml`、`commentsExtended.xml`、`commentsIds.xml`、`commentsExtensible.xml`,以及对应的关系文件(relationships)和内容类型覆盖(content-type overrides)。批注 ID 会自动分配。随后它会打印出 `<w:commentRangeStart>`/`<w:commentRangeEnd>`/`<w:commentReference>` 片段，供你添加到 `word/document.xml` 中，使批注锚定到具体文本上——在你放置这些标记之前，批注虽然已经存在，但是不可见的。

## 依赖项

`docx`(npm,已预先安装——仅在 `require('docx')` 失败时才安装)· `pandoc` · LibreOffice(`soffice`)· `pdftoppm`(Poppler)

---

*本技能由 [Anthropic](https://github.com/anthropics/skills/tree/main/skills/docx) 创建并维护。此处按原样收录(vendored),除 frontmatter 元数据外未作修改；条款详见 LICENSE.txt。*
