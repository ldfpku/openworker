# SMJAR 品牌资源

本目录 webp 已按**原稿 logo 复刻**（黑色粗体 SMJAR + 绿色线框地球，2026-08-21）：在品牌
仓库里由 `tools/make_brand_assets.py` 程序化生成，可复跑微调。如后续拿到官方矢量源文件
（AI/SVG），导出后**同名替换**即可，代码零改动。

> 这份是**供 openworker 使用的副本**。改完这里的图之后要跑一次
> `.venv\Scripts\python.exe gemini-relay\scripts\gen_brand_assets.py`，
> 它会重新生成两份 base64 内联副本——`gemini-relay/worker/src/brand.ts`（中转登录页 +
> 公开的 `/brand/` 地址）和 `coworker/brand_assets.py`（本机登录回调页）。GUI 侧直接
> `import` 本目录的 webp，不需要额外步骤。

| 文件 | 规格 | 用途 |
|---|---|---|
| `logo.webp` | 640×160，透明底，黑字 | 浅色界面顶栏、门户页眉、打印 |
| `logo-dark.webp` | 640×160，透明底，白字 | 深色界面顶栏（`<picture>` 或 CSS 按主题切换） |
| `logo-mark.webp` | 256×256，透明底 | 地球方标：卡片、列表、加载态 |
| `favicon.webp` | 64×64 | 浏览器标签图标（`<link rel="icon" type="image/webp">`） |
| `watermark.webp` | 512×512，透明底，整体 ≈16% 不透明度（地球 + SMJAR + 内部资料） | 阅读页平铺水印、PDF 发布盖章素材（docs/05 §7） |

品牌色（取自 logo，UI 令牌见 docs/09）：

| 色 | 值 | 来源 |
|---|---|---|
| 品牌绿 | `#1F7A3C` | 地球中间调 |
| 深绿 | `#0A3A1B` | 地球暗缘 |
| 浅绿 | `#58B96C` | 地球高光 |
| 墨黑 | `#111214` | 字标 |

注意事项：

1. 替换文件时保持文件名与路径不变（`/static/brand/...` 被模板与 PDF 盖章管线引用）。
2. `watermark.webp` 必须保持透明底 + 低不透明度（10–20%）；提供更浓素材时，可在盖章参数与 CSS 里再压。
3. 重新生成：`python tools/make_brand_assets.py`（需 Pillow、Windows 自带 Arial Black 与微软雅黑；配色/构图参数都在脚本顶部）。
