# SMJ 品牌资源

本目录使用 **SMJ 品牌识别系统 BIS v1.7** 的官方素材，源自 `D:\SMJ\BIS` 的 `01_Logo` 与 `02_Icon`。应用产品名为 **smjworker**，不再使用旧版 SMJAR 地球标志。

| 文件 | 规格 | 用途 |
|---|---|---|
| `logo.webp` | 640×235，透明底，橙蓝双色 | 浅色界面、登录页 |
| `logo-dark.webp` | 640×235，透明底，橙白双色 | 深色界面、登录页 |
| `logo-mark.webp` | 256×256，斯米伽蓝底双色 S 标 | 卡片、列表、加载态、App Launcher |
| `favicon.webp` | 64×64 | 浏览器标签图标 |

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
4. 桌面、任务栏与托盘图标保留 smjworker 自建星形底标，不使用 SMJ 图标，避免与其他系统混淆。
