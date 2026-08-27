# Ginkgo Cloud Lab

## 概述

Ginkgo Cloud Lab（<https://cloud.ginkgo.bio>）提供对 Ginkgo Bioworks 自主实验室基础设施的远程访问。各项实验方案在可重构自动化推车（Reconfigurable Automation Carts,RAC）上执行——这是一种模块化单元，配备机械臂、磁悬浮样本传输系统，以及覆盖 70 多台仪器的工业级软件。

该平台还包含 **EstiMate**,这是一个 AI 智能体，能够接受用自然语言描述的实验方案，并针对目录之外的定制化工作流，返回可行性评估和报价。

目录分为 **Expression & Purification（表达与纯化）（**体外/无细胞/大肠杆菌/毕赤酵母**）、Characterization & Assay（表征与检测）**、**Method & Target Onboarding（方法与靶点接入）**,以及 **Specialty（特色服务）**。请在下方选择一种实验方案，然后阅读其参考文件，了解输入、输出、自动化工作流程以及下单细节。

## 可用实验方案

### 表达与纯化 - 体外（In vitro）

| 实验方案 | 读出方式 | 价格 | 交付周期 | 状态 |
|---|---|---|---|---|
| [IVT mRNA/环状 RNA 合成](references/ivt-rna-synthesis-qpcr.md) | qPCR（mRNA 或环状 RNA,384 孔板） | 99 美元/样本 | 最长 12 个工作日 | 已认证 |

### 表达与纯化 - 无细胞（大肠杆菌 CFPS）

| 实验方案 | 读出方式 | 价格 | 交付周期 | 状态 |
|---|---|---|---|---|
| [验证序列表达](references/cell-free-protein-expression-validation.md) | 通过/不通过滴度 + 纯度（最长 1800 bp） | 39 美元/样本 | 最长 10 天 | 已认证 |
| [优化表达条件](references/cell-free-protein-expression-optimization.md) | 覆盖 24 种条件的实验设计（DoE） | 199 美元/样本 | 最长 11 天 | 已认证 |
| [表达 + 定量（HiBiT）](references/cell-free-protein-expression-hibit.md) | 发光检测，无需纯化 | 39 美元/样本 | 最长 11 天 | 已认证 |
| [表达 + 纯化（A280）](references/cfps-strep-tag-purification-a280.md) | Strep 标签,A280 产率 | 149 美元/样本 | 最长 11 天 | 已认证 |
| [表达 + 纯化 minibinder](references/minibinder-strep-tag-a280.md) | Strep 标签,A280,LabChip | 149 美元/样本 | 最长 11 天 | 已认证 |
| [表达 + 纯化（A280 + LabChip）](references/cfps-expression-purification-quantification.md) | Strep 标签,A280 + 纯度/大小 | 159 美元/样本 | 最长 12 天 | 已认证 |

### 表达与纯化 - 大肠杆菌（E. coli）

| 实验方案 | 读出方式 | 价格 | 交付周期 | 状态 |
|---|---|---|---|---|
| [表达 + 定量（HiBiT）](references/ecoli-protein-expression-hibit.md) | 发光检测（最多 384 个构建体） | 79 美元/样本 | 最长 3 周 | 已认证 |
| [表达 + 纯化（A280）](references/ecoli-protein-expression-histag-a280.md) | His 标签,A280 产率 | 199 美元/样本 | 最长 3 周 | 已认证 |
| [表达 + 纯化 minibinder](references/ecoli-minibinder-expression-histag-a280.md) | His 标签,A280 产率 | 199 美元/样本 | 最长 3 周 | 已认证 |
| [表达 + 纯化（A280 + LabChip）](references/ecoli-expression-purification-quantification.md) | His 标签,A280 + 纯度/大小 | 209 美元/样本 | 最长 3 周 | 已认证 |

### 表达与纯化 - 毕赤酵母（Pichia）

| 实验方案 | 读出方式 | 价格 | 交付周期 | 状态 |
|---|---|---|---|---|
| [表达 + 定量（LabChip）](references/pichia-protein-expression-labchip.md) | 分泌型蛋白，大小/纯度（最多 96 个） | 89 美元/样本 | 最长 4 周 | 已认证（新） |

### 表征与检测

| 实验方案 | 读出方式 | 价格 | 交付周期 | 状态 |
|---|---|---|---|---|
| [表达 + 热迁移](references/cfps-strep-purification-thermal-shift.md) | SYPRO Orange Tm（Tonset,TM1-3） | 159 美元/样本 | 最长 12 天 | 已认证 |
| [检测酶促产物（Echo-MS）](references/echo-ms-cfps-detection.md) | 通过 Echo-MS 检测底物/产物 | 44 美元/样本 | 最长 13 天 | 测试版 |

### 方法与靶点接入

| 实验方案 | 读出方式 | 价格 | 交付周期 | 状态 |
|---|---|---|---|---|
| [接入 Echo-MS 方法](references/echo-ms-method-onboarding.md) | 校准曲线,LOD/LOQ | 799 美元/分子 | 最长 3 周 | 已认证 |
| [接入 SPR 靶点](references/spr-target-onboarding.md) | 经验证的 SPR 捕获方法 | 1,399 美元/靶点 | 最长 4 周 | 测试版 |

### 特色服务

| 实验方案 | 读出方式 | 价格 | 交付周期 | 状态 |
|---|---|---|---|---|
| [生成荧光像素画](references/fluorescent-pixel-art-generation.md) | UV 照片,7 色大肠杆菌调色板 | 25 美元/板 | 最长 7 天 | 测试版 |

**即将推出**：蛋白质表达与结合亲和力表征（先表达 + 纯化，再针对某个靶点筛选结合亲和力）。

## 如何选择实验方案

- **想要快速筛查可表达性?** 无细胞 HiBiT（39 美元）或验证序列表达（39 美元）。
- **需要纯化后的蛋白 + 产率?** 选择 A280 档位（无细胞或大肠杆菌）；如需纯度/大小信息，再加上 LabChip。
- **难表达/膜蛋白/含二硫键/含辅因子的靶点?** 无细胞优化方案（24 种条件的实验设计,DoE）。
- **分泌型或真核靶点?** 毕赤酵母表达。
- **筛选全新设计的结合物/minibinder?** 无细胞或大肠杆菌 minibinder 档位，之后用 SPR 接入来测定动力学参数。
- **酶活性/生物催化?** Echo-MS 酶促检测（需先接入该分析物的方法）。
- **稳定性/可开发性排序?** 热迁移检测。
- **RNA（mRNA/环状 RNA）?** IVT 合成 + qPCR。

## 一般下单流程

1. 在 https://cloud.ginkgo.bio/protocols 选择一个实验方案
2. 配置参数（蛋白质/样本/分子/靶点数量、重复次数、板数）
3. 下载该实验方案的输入模板并上传输入内容（对序列类实验方案使用 FASTA/CSV/XLSX;对像素画使用 Design Tool;对接入类实验方案使用供应商目录编号）
4. 在 Additional Details（附加详情）字段中填写任何特殊要求
5. 提供邮箱地址，同意实验方案条款，并加入购物车/提交，以获取可行性报告和报价

对于上面未列出的实验方案，可使用 **EstiMate** 聊天工具（<https://cloud.ginkgo.bio/estimate>）,用自然语言描述定制化的实验方案，以获取兼容性评估和报价。

## 身份验证

访问 Ginkgo Cloud Lab: <https://cloud.ginkgo.bio>。可能需要创建账户或获得机构授权访问。有关访问方面的问题，请联系 Ginkgo,邮箱为 cloud@ginkgo.bio。

## 关键基础设施

- **RAC（可重构自动化推车）**： 模块化机器人单元，配备高精度机械臂和磁悬浮传输系统
- **Catalyst 软件**： 实验方案编排、调度、参数配置以及实时监控
- **70 多台集成仪器**： Agilent Bravo 液体处理器、Beckman/Labcyte Echo 声学分液仪、BMG PHERAstar / Tecan Spark 读板机、Revvity LabChip、Bio-Rad CFX Opus、Nicoya Alto SPR、SciEx Echo-MS、Inheco/Cytomat 培养箱等
- **Nebula**： Ginkgo 位于美国马萨诸塞州波士顿的自主实验室设施
