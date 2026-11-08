# SMJ 品牌资源

本目录使用 **SMJ 品牌识别系统 BIS v1.7** 的官方素材，源自 `D:\SMJ\BIS` 的 `01_Logo` 与 `02_Icon`。应用产品名为 **smjworker**，不再使用旧版 SMJAR 地球标志。

| 文件 | 规格 | 用途 |
|---|---|---|
| `logo.webp` | 640×235，透明底，橙蓝双色 | 浅色界面、登录页 |
| `logo-dark.webp` | 640×235，透明底，橙白双色 | 深色界面、登录页 |
| `logo-mark.webp` | 256×256，斯米伽蓝底双色 S 标 | 卡片、列表、加载态、App Launcher |
| `favicon.webp` | 64×64 | 中转登录页、本机登录回调页的标签图标（应用自己的标签图标见下方第 4 条） |

品牌色：

| 色 | 值 |
|---|---|
| 斯米伽蓝 | `#034FBC` |
| 深井蓝 | `#0A1F54` |
| 信号橙 | `#FA8C1F` |

维护规则：

1. 替换文件时保持文件名与路径不变，GUI 会直接引用这些 webp。
2. 官方素材更新后，以相同宽高比导出并同名替换，不要拉伸或改变标志颜色。
3. 更新后运行 `.venv\Scripts\python.exe gemini-relay\scripts\gen_brand_assets.py`，同步生成中转登录页和本机登录回调页的内联副本及 PNG 版本。
4. 应用自己的图标（桌面、任务栏、安装包、浏览器标签）用 SMJ 应用图标家族里的 openworker 套件（「W＋交付对勾」），源目录 `D:\smj-apps\app-icons\openworker`，规范见该目录的 README.md / DESIGN.md：
   - `src-tauri/icons/icon.ico`、`icon.icns` 直接用套件里的 `app-icon.ico`、`app-icon.icns`（ICO 的 16 px 帧是专门画的像素版）；
   - `src-tauri/icons/` 下的各尺寸 PNG 用 `npx tauri icon <套件>/app-icon-desktop-1024.png -o <临时目录>` 生成后，只拷回已有的同名文件；
   - 浏览器标签图标在 `app/`（`favicon.ico`、`favicon.svg`、`favicon-16.svg`、`apple-touch-icon.png`），由 `index.html` 引用。
5. 应用图标不是公司标志：界面里的 S 标、登录页的完整标志仍按上表使用 BIS 官方素材。托盘图标（`src-tauri/icons/tray.*`，单色模板图）不在应用图标套件范围内，暂保持原样，不要拿彩色应用图标代替。
