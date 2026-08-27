# 数据来源与许可声明

本目录（`library-pack/`）是 openworker 内置的专家库与技能库数据包，由
`packaging/gen_library.py` 从以下三个上游开源仓库自动抓取生成，随 openworker 源码一起分发。

## 上游仓库

| 内容 | 上游仓库 | 许可证 | 抓取时 commit |
|---|---|---|---|
| 英文专家库（`experts/en/`） | https://github.com/msitarzewski/agency-agents | MIT | `32230ec4790a24cfd187e08245cb3c6f28998b9d` |
| 中文专家库（`experts/zh/`） | https://github.com/jnMetaCode/agency-agents-zh | MIT | `972452cdedef8d04fed4a8dd1dc10623e33ed412` |
| 科学技能库（`skills/`） | https://github.com/K-Dense-AI/scientific-agent-skills | MIT | `390f5146bf3c1877cf15636a3dd7b775e4f0f185` |

## 版权声明

- agency-agents：`Copyright (c) 2025 AgentLand Contributors`
- agency-agents-zh（英文原版 + 中文汉化，双版权）：
  - `Copyright (c) 2025 Michael Sitarzewski (original English version)`
  - `Copyright (c) 2026 jnMetaCode (Chinese translation and localization)`
- scientific-agent-skills：`Copyright (c) 2025 K-Dense Inc.`

三者均以 MIT License 分发。完整许可证正文见各自仓库根目录的 `LICENSE` / `LICENSE.md`：

- https://github.com/msitarzewski/agency-agents/blob/main/LICENSE
- https://github.com/jnMetaCode/agency-agents-zh/blob/main/LICENSE
- https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/LICENSE.md

## 与本 fork 的关系

openworker 是 https://github.com/andrewyng/openworker 的一个公开 fork，本数据包随
https://github.com/ldfpku/openworker 一同分发。以上三个上游仓库的内容——专家库按原始
Markdown 文件（含 frontmatter）原样拷贝，技能库按目录整棵原样拷贝——未做任何实质性修改；
本 fork 新增的内容：生成/维护脚本（`packaging/gen_library.py`）、本说明文件，以及技能的中文译文层（各技能目录下的 `SKILL.zh.md` 与 index.json 中的 `description_zh` 字段，由本 fork 翻译生成，仅用于库内浏览展示；安装进全局技能目录的始终是上游英文原件）。

## 生成信息

- 生成时间（UTC）：`2026-08-27T04:03:04Z`
- 生成脚本：`packaging/gen_library.py`
