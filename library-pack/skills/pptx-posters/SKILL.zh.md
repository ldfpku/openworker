# PPTX posters（PPTX 科研海报）

## 适用范围

只有当请求的源文件/交付物是一份可编辑的 PowerPoint 海报时，才使用本技能。
不要仅仅因为 PowerPoint 可用，就把一个未指明格式的海报请求路由到这里。

2.0 版本从严格的本地 JSON 生成一份真正的单张幻灯片 `.pptx` 文件。它不使用
HTML 转换、外部模板、示意图/图像生成服务、API 密钥、环境文件、网络请求，
也不强制要求任何特定的图表样式。

## 硬性关口

当任何一项关口未被满足时，应停下而不是猜测：

1. 作者尚未提供确切的海报内容和来源记录。
2. 任何主张、数字、引用、作者、单位归属、资助声明、图表、许可证，
   或二维码目标尚未确定。
3. 当前的会议和打印方要求尚未得到确认。
4. 作者批准尚未绑定到当前清单内容的哈希值上。
5. 某项素材是远程的、位于清单目录之外、未计算哈希值，或未获批准。
6. 某个输入是 `.pptm`、包含宏/外部关系/OLE/嵌入文件，或是不受信任的模板。
7. 所请求的工作流需要自动打开或执行 PowerPoint。
8. 某个脚本报告了包、版式、DPI、对比度或输出计划方面的阻塞问题。

绝不能编造缺失的材料，也不能留下看似合理的占位内容。草稿应采取失败即中止
（fail closed）的策略。

## 安装精确版本的生成依赖

从技能目录下：

```bash
uv venv
uv pip install "python-pptx==1.0.2" "Pillow==12.3.0" "lxml==6.1.1"
```

生成过程要求精确使用以下版本：

```text
python-pptx==1.0.2
Pillow==12.3.0
lxml==6.1.1
```

所有 CLI 都使用惰性的可选导入，因此在没有安装这些包的情况下，
`python -B scripts/<tool>.py --help` 也能正常工作。使用 `-B` 以避免
产生字节码文件。

## 在排版之前先确定要求

分别记录以下内容：

- 物理成品尺寸（trim）宽/高及方向；
- 每条边的出血（bleed）量；
- 成品尺寸内的安全边距（safe margin）；
- PowerPoint 画布的宽/高；
- 统一的物理画板/画布打印比例；
- 会议方规定的最大尺寸及交付格式；
- 打印方对成品尺寸、出血、边距、缩放比例、色彩模式，以及打样的要求；
- 最终输出的字体和栅格化 DPI 阈值，每一项都应标注为经验法则，
  或与一个确切来源绑定。
- 所需的字体样式、工作站上的字体可用性、字体嵌入权限，
  以及替换/打样工作流。

不存在一个"放之四海而皆准"的海报尺寸。目前微软限制每个自定义 PowerPoint
尺寸在 1 到 56 英寸之间，且所有幻灯片使用统一尺寸。如果物理画板尺寸更大，
只有在打印方确认缩放方案的情况下，才使用一个成比例缩小的画布尺寸。

请阅读 `references/poster_layout_design.md`。

## 构建清单（Manifest）

将 `assets/poster_manifest_template.json` 复制到项目中。在每一个占位符、
每一处虚假确认，以及草稿批准都被解决之前，该模板刻意保持无效状态。

请遵循 `references/manifest_spec.md` 和 `references/poster_content_guide.md`。

该清单要求包含：

- 文档元数据、每个元素以及每项素材的确切来源 ID；
- 每个来源都标注 `author_verified: true`；
- 每个元素和素材都标注 `author_approved: true`；
- 本地 PNG/JPEG 路径及小写的 SHA-256 哈希值；
- 每一张可选图片的确切来源与许可证/授权信息；
- 已获批准的替代文本（alt text），以及在需要时与来源绑定的原生长描述；
- 明确的阅读顺序和设计矩形区域；
- 每个本地二维码图像可见的、确切的备用 URL/文本；
- 已确认的会议方/打印方规则；
- 所声明的 sRGB 对比度配对，以及冗余的数据编码方式；
- 与规范化清单内容绑定的批准记录。

在所有非批准相关字段都通过之后，获取内容哈希值：

```bash
python -B scripts/validate_manifest.py poster.json \
  --print-content-hash
```

将该份确切的清单和哈希值提供给作者。随后将 `approval.status` 设置为
`approved`，记录批准人和带时区偏移的时间戳，并复制该哈希值。任何
非批准相关的编辑都会使批准失效。

校验已批准的清单及本地素材：

```bash
python -B scripts/validate_manifest.py poster.json
```

## 在生成之前审计素材和配色方案

```bash
python -B scripts/inventory_images.py poster.json \
  --output poster.assets.json

python -B scripts/check_palette.py poster.json \
  --output poster.palette.json

python -B scripts/plan_export.py poster.json \
  --output poster.export-plan.json
```

有效 DPI 是像素数除以最终放置尺寸（英寸），而不是图像元数据中记录的 DPI。
该清单工具会完整解码有边界限制的图像，并阻止 EXIF/XMP/注释以及嵌入的
文本/应用程序元数据；应离线剥离这些内容，然后重新计算哈希值并重新获得批准。
对比度检查使用 WCAG 2.2 sRGB 数学方法；将这些数值应用到实体海报上是一个
设计目标，而不是一项独立的合规性声明。应保留颜色冗余的标签、标记、
形状、图案或线型。

如果打印方要求 CMYK 色彩模式，在存在一个经打印方批准的转换/配置文件
及打样之前，该计划将阻止"可打印"状态的确立。不要声称原生的 PowerPoint
PDF 符合 CMYK 规范。

请阅读 `references/poster_design_principles.md`。

## 生成 PPTX

使用一个新的输出路径：

```bash
python -B scripts/generate_poster.py poster.json \
  --output poster.pptx \
  --report poster.generation.json
```

生成过程会：

- 创建一个全新的空白演示文稿；它绝不会加载用户模板；
- 在添加内容之前先设置已批准的画布尺寸；
- 使用一个原生标题占位符、原生文本框，以及本地图片；
- 使用 `contain`（包含）适配方式保持图像宽高比；
- 禁用文本自动缩小；
- 按已批准的阅读顺序添加元素；
- 将已批准的图片替代描述和明确的文本语言写入 PresentationML；
- 不嵌入字体、音频、视频、OLE、ActiveX、链接或其他媒体；
- 移除默认的打印机设置二进制数据，并规范化包的时间戳；
- 在替代文本补丁前后都会检查该文件包；
- 拒绝重叠、超出边界的形状、过小的最终字号/DPI、不安全的文件包，
  以及已存在的目标位置。

它渲染的是清单中的确切文本。它不会撰写、总结、研究，或校正科学内容。

## 运行最终技术审计

```bash
python -B scripts/inspect_pptx.py poster.pptx \
  --output poster.package.json

python -B scripts/check_layout.py poster.pptx \
  --manifest poster.json \
  --output poster.layout.json
```

该包检查工具只读取有边界限制的 ZIP 元数据以及选定的 XML 内容。它绝不会
解压其中的成员文件，也不会打开/执行该演示文稿。它会拒绝以下情况：

- 任何非 `.pptx` 扩展名，包括 `.pptm`；
- 超出有边界限制的单张幻灯片生成器规范之外的文件包；
- 宏/VBA、ActiveX、自定义 UI、OLE、嵌入内容、可执行文件，以及二进制部件；
- 任何外部关系，包括远程链接的图片和超链接；
- 不安全/重复的 ZIP 路径、符号链接、加密、超大解压体积，
  以及过高的压缩比；
- 格式错误或含有实体（entity）的被检查 XML；
- 缺失的内部关系目标。

请阅读 `references/pptx_security.md`。

## 人工 PowerPoint 与无障碍访问关口

自动化流程无法认证无障碍访问性、文本渲染效果，或科学内容的准确性。
在一个已完全打过补丁的 PowerPoint 中：

1. 只打开生成好且技术上干净的文件。
2. 运行 审阅 > 检查辅助功能。
3. 检查阅读顺序（Reading Order）面板和对象名称。
4. 审阅每一处替代文本和原生长描述。
5. 测试键盘导航和屏幕阅读器导航。
6. 确认字体已安装/已获授权；检查字体嵌入方式的选择、替换方案、
   字形、公式、溢出情况、对比度，以及所有边缘部分。
7. 核实颜色绝不是唯一的编码方式。
8. 测试每个二维码及其可见的备用 URL/文本。
9. 就所有内容和引用获得作者的签字确认。

微软建议的 18 pt 幻灯片字号并不是海报的通用最小字号。应基于清单中
标注的依据和相应的打样结果，在最终物理输出尺寸下评估字号大小。

## 导出与打印

使用已批准的导出计划。当需要 PDF 时，从经过审阅的 PowerPoint 中以
"标准/高打印质量"而非"最小尺寸"选项导出。

独立地核实该 PDF：

- 页面/画板尺寸、方向、成品尺寸，以及出血；
- 若有要求，输出为单页；
- 字体、裁剪、字形、公式，以及图像重采样；
- 标签、阅读顺序、替代文本、语言，以及链接；
- RGB/CMYK 转换以及实体色彩打样；
- 会议方的命名规则、文件大小限制，以及上传规则。

打印一份缩小比例的打样，并获得打印方要求的打样确认。在任何改动之后，
重新运行全部检查。

发布签核时使用 `assets/poster_quality_checklist.md`。

## 内置 CLI 工具

- `validate_manifest.py` —— 严格的内容/来源溯源/批准状态校验器。
- `generate_poster.py` —— 使用精确锁定版本的本地 PPTX 生成器。
- `inspect_pptx.py` —— 不执行文件的 ZIP/XML 安全检查工具。
- `check_layout.py` —— 边界、重叠、阅读顺序，以及最终字号检查工具。
- `inventory_images.py` —— 素材哈希/元数据/有效 DPI 清单工具。
- `check_palette.py` —— WCAG 对比度及经验性配色方案报告工具。
- `plan_export.py` —— 尺寸、缩放比例、字体、色彩、媒体、导出，以及打印预检工具。

## 参考资料

- `references/manifest_spec.md`
- `references/poster_content_guide.md`
- `references/poster_design_principles.md`
- `references/poster_layout_design.md`
- `references/pptx_security.md`
- `references/security_validation.md`
- `references/source_ledger.md`
