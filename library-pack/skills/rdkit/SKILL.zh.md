# RDKit 化学信息学工具包

## 概述

RDKit 是一个全面的化学信息学库，提供用于分子分析和操作的 Python API。此技能为读写分子结构、
计算描述符、生成指纹（fingerprint）、子结构搜索、化学反应、二维/三维坐标生成以及分子可视化
提供指导。此技能适用于药物发现、计算化学及化学信息学研究任务。

**当前基准版本（核查于 2026-06-07）**： RDKit **2026.03.3** 是 GitHub/PyPI 上的最新发行版
（PyPI 上的 `rdkit` 2026.3.3）。官方安装文档仍然建议大多数用户使用 conda-forge，同时也在
`rdkit` 这一软件包名下发布了跨平台的 PyPI wheel 包。`rdkit-pypi` 是旧的 PyPI 软件包名称，
仅应在维护遗留环境时使用。

## 安装与配置

在现有 Python 环境中安装时使用 `uv`：

```bash
uv pip install rdkit
```

对于需要可复现的化学环境，尤其是在混用需要编译的科学计算软件包时，conda-forge 仍是上游
推荐的方式：

```bash
conda create -c conda-forge -n my-rdkit-env rdkit
conda activate my-rdkit-env
```

除非是刻意在调试打包相关的行为，否则应避免在同一个环境中同时安装 conda 版的 `rdkit`
和 PyPI 版的 `rdkit`/`rdkit-pypi`。混合安装可能导致难以判断实际导入的是哪个二进制扩展。

## 核心能力

[references/core_capabilities.md](references/core_capabilities.md) 中记录了十二个能力领域，
每个都配有可运行的代码：

| # | 领域 | 涵盖内容 |
| --- | --- | --- |
| 1 | 分子输入输出与创建 | SMILES、MOL 文件与文本块、InChI、SDF 与 SMILES 供应器（supplier）、多线程读取、写入器 |
| 2 | 净化（Sanitization）与验证 | 禁用自动净化、手动及部分净化、先行检测问题 |
| 3 | 分析与属性 | 原子和键的遍历、环信息与 SSSR、手性与立体化学、片段 |
| 4 | 描述符 | 分子量（MW）、LogP、TPSA、氢键供体/受体、可旋转键、芳香环、批量计算、类药性 |
| 5 | 指纹与相似性 | 拓扑指纹、经由 `rdFingerprintGenerator` 生成的 Morgan/ECFP、MACCS、原子对、扭转、Avalon；Tanimoto 及其他度量；Butina 聚类 |
| 6 | 子结构搜索 | SMARTS 查询、匹配结果获取，以及一个常见模式库 |
| 7 | 化学反应 | 反应 SMARTS、应用反应、反应指纹 |
| 8 | 二维与三维坐标 | 结构描绘（depiction）、模板对齐、ETKDG 嵌入、力场优化、RMSD、约束嵌入 |
| 9 | 可视化 | 单张与网格图像、子结构高亮、自定义绘图选项、Jupyter 集成、指纹位环境 |
| 10 | 分子修改 | 显式氢原子、开克库勒化（Kekulization）、芳香性、子结构替换、电荷中和 |
| 11 | 哈希与标准化 | Murcko 骨架与规范哈希、区域异构体哈希、用于数据增强的随机化 SMILES |
| 12 | 药效团与三维特征 | 特征工厂与特征提取 |

具体的工作流示例，以及性能、线程安全性和版本敏感性方面的说明，都在
[references/workflows_and_best_practices.md](references/workflows_and_best_practices.md) 中。

对于共享数据，应优先使用可移植的交换格式（SMILES、SDF）；对于本地缓存，RDKit 的
二进制分子表示方式可以避免使用通用的 pickle。

## 常见陷阱

1. **忘记检查是否为 None**： 解析后应始终验证分子对象
2. **净化失败**： 使用 `DetectChemistryProblems()` 进行调试
3. **氢原子缺失**： 在计算依赖氢原子的属性时使用 `AddHs()`
4. **二维与三维之分**： 在可视化或三维分析之前应生成合适的坐标
5. **SMARTS 匹配规则**： 请记住未指定的属性可以匹配任何内容
6. **MolSupplier 的线程安全性**： 不要在多个线程之间共享供应器（supplier）对象

## 资源

### references/

此技能包含详细的 API 参考文档：

- `api_reference.md` - 按功能组织的 RDKit 模块、函数和类的全面列表
- `descriptors_reference.md` - 可用分子描述符的完整列表及说明
- `smarts_patterns.md` - 官能团及结构特征的常见 SMARTS 模式

在需要具体 API 细节、参数信息或模式示例时加载这些参考文件。

只有 `references/` 和 `scripts/` 中列出的文件才是此技能随附的本地资源。诸如 `rdkit`、
`datamol`、`scipy` 和 `sklearn` 之类的名称指的是可安装的 Python 软件包，而不是此技能中的
本地文件。

### scripts/

常见 RDKit 工作流的示例脚本：

- `molecular_properties.py` - 计算全面的分子属性和描述符
- `similarity_search.py` - 执行基于指纹的相似性筛选
- `substructure_filter.py` - 按子结构模式筛选分子

这些脚本既可以直接运行，也可以作为自定义工作流的模板使用。
