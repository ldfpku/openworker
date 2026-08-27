# Rowan:云原生分子建模与药物设计工作流

## 概述

Rowan 是一个面向分子模拟、药物化学(medicinal chemistry)和基于结构的设计的云原生工作流平台。其 Python API 提供了统一的接口，涵盖小分子建模、性质预测、对接(docking)、分子动力学以及 AI 结构预测工作流。

当你希望以编程方式运行药物化学或分子设计工作流，而不想维护本地 HPC 基础设施、GPU 资源配置或一堆分散的建模工具时，就该使用 Rowan。Rowan 负责处理全部基础设施、结果管理和计算规模扩展。

## 何时使用 Rowan

**Rowan 适合以下场景**:

- 量子化学、半经验方法(semiempirical methods)或神经网络势(neural network potentials)
- 批量性质预测(pKa、描述符、渗透性、溶解度)
- 构象异构体(conformer)与互变异构体(tautomer)集合的生成
- 对接工作流(单配体、类似物系列、位姿精修)
- 蛋白质-配体共折叠(cofolding)与 MSA 生成
- 多步骤化学流水线(例如:互变异构体搜索 → 对接 → 位姿分析)
- 需要一致、可扩展基础设施的批量药物化学项目

**Rowan 不适合以下场景**:
- 简单的分子输入输出(直接用 RDKit)
- 后 Hartree-Fock(post-HF)的从头算(*ab initio*)量子化学或相对论计算

## 快速开始

```bash
uv pip install rowan-python
```

```python
import rowan
rowan.api_key = "your_api_key_here"  # 或设置环境变量 ROWAN_API_KEY

# 提交一个描述符工作流——不到一分钟即可完成
wf = rowan.submit_descriptors_workflow("CC(=O)Oc1ccccc1C(=O)O", name="aspirin")
result = wf.result()

print(result.descriptors['MW'])    # 180.16
print(result.descriptors['SLogP']) # 1.19
print(result.descriptors['TPSA'])  # 59.44
```

如果这段代码无误地打印出结果，说明配置正确。

## 安装

```bash
uv pip install rowan-python
# 或者: uv pip install rowan-python
```

## 用户与 Webhook 管理

### 身份验证

通过环境变量设置 API key(推荐):

```bash
export ROWAN_API_KEY="your_api_key_here"
```

或直接在 Python 中设置:

```python
import rowan
rowan.api_key = "your_api_key_here"
```

验证身份认证:

```python
import rowan
user = rowan.whoami()  # 若已通过身份验证,返回用户信息
print(f"User: {user.email}")
print(f"Credits available: {user.credits_available_string}")
```

## 分子输入格式

Rowan 接受以下格式的分子输入:

- **SMILES**(首选):`"CCO"`、`"c1ccccc1O"`
- **SMARTS 模式**(用于部分工作流):用于子结构匹配的 SMARTS 子集
- **InChI**(若你的 API 版本支持):`"InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3"`

API 会对输入进行验证，如果分子无法解析，会抛出 `rowan.ValidationError`。为保证可复现性，请始终使用规范化(canonicalized)的 SMILES。

**提示**: 提交前用 RDKit 验证 SMILES:

```python
from rdkit import Chem
smiles = "CCO"
mol = Chem.MolFromSmiles(smiles)
if mol is None:
    raise ValueError(f"Invalid SMILES: {smiles}")
```

## 核心使用模式

大多数 Rowan 任务都遵循相同的三步模式:

1. **提交(Submit)** 一个工作流
2. **等待(Wait)** 完成(可选流式返回)
3. **获取(Retrieve)** 带便捷属性的类型化结果

```python
import rowan

# 1. 提交 —— 使用具体的工作流函数(而不是通用的 submit_workflow)
workflow = rowan.submit_descriptors_workflow(
    "CC(=O)Oc1ccccc1C(=O)O",
    name="aspirin descriptors",
)

# 2. & 3. 等待并获取
result = workflow.result()  # 阻塞直到完成(默认: wait=True, poll_interval=5)
print(result.data)              # 原始字典
print(result.descriptors['MW']) # 180.16 —— 使用 result.descriptors 字典,而不是 result.molecular_weight
```

对于运行时间较长的工作流，使用流式返回:

```python
for partial in workflow.stream_result(poll_interval=5):
    print(f"Progress: {partial.complete}%")
    print(partial.data)
```

### result() 与 stream_result() 的对比

| 模式 | 使用场景 | 耗时 |
|---------|----------|------|
| `result()` | 可以等待完整结果时 | 典型情况 <5 分钟 |
| `stream_result()` | 需要进度反馈，或需要提前获取部分结果时 | >5 分钟，或交互式使用 |

**准则**: 对描述符、pKa 使用 `result()`。对构象异构体搜索、对接、共折叠使用 `stream_result()`。

## 处理结果

Rowan 的 API 包含带便捷属性的**类型化工作流结果对象**。

### 使用类型化属性与 .data

结果有两种访问方式:

1. **便捷属性**(优先推荐):`result.descriptors`、`result.best_pose`、`result.conformer_energies`
2. **原始数据兜底**:`result.data` —— 来自 API 的原始字典

示例:

```python
result = rowan.submit_descriptors_workflow(
    "CCO",
    name="ethanol",
).result()

# 便捷属性(返回包含所有描述符的字典):
print(result.descriptors['MW'])   # 46.042
print(result.descriptors['SLogP'])  # -0.001
print(result.descriptors['TPSA'])   # 57.96

# 原始数据兜底(描述符嵌套在 'descriptors' 键下):
print(result.data['descriptors'])
# {'MW': 46.042, 'SLogP': -0.001, 'TPSA': 57.96, 'nHBDon': 1.0, 'nHBAcc': 1.0, ...}
```

**注意**: `DescriptorsResult` **没有** `molecular_weight` 属性。描述符的键使用简短名称(`MW`、`SLogP`、`nHBDon`),而不是完整拼写的名称。

### 缓存失效

部分结果属性是惰性加载(lazily loaded)的(例如构象异构体几何结构、蛋白质结构)。若要刷新:

```python
result.clear_cache()
new_structures = result.conformer_molecules  # 重新获取
```

## 项目、文件夹与组织方式

对于非平凡规模的项目，使用项目(projects)和文件夹(folders)来保持工作有条理。

### 项目(Projects)

```python
import rowan

# 创建一个项目
project = rowan.create_project(name="CDK2 lead optimization")
rowan.set_project("CDK2 lead optimization")

# 此后提交的所有工作流都会归入该项目
wf = rowan.submit_descriptors_workflow("CCO", name="test compound")

# 之后获取
project = rowan.retrieve_project("CDK2 lead optimization")
workflows = rowan.list_workflows(project=project, size=50)
```

### 文件夹(Folders)

```python
# 创建层级化的文件夹结构
folder = rowan.create_folder(name="docking/batch_1/screening")

wf = rowan.submit_docking_workflow(
    # ... 对接参数 ...
    folder=folder,
    name="compound_001",
)

# 列出某文件夹下的工作流
results = rowan.list_workflows(folder=folder)
```

## 工作流决策树

### pKa 与 MacropKa 的选择

**以下情况使用微观 pKa(microscopic pKa)**:

- 只需要单个可电离基团的 pKa
- 关注酸碱转变和质子化热力学
- 分子只有一到两个可电离位点
- 速度至关重要(更快，消耗更少 credits)

**以下情况使用 macropKa**:

- 需要在具有生理相关性的 pH 范围内(例如 0-14)获得依赖 pH 的行为
- 需要跨 pH 的聚合电荷及质子化状态分布
- 分子具有多个存在耦合关系的可电离基团
- 需要不同 pH 下的下游性质，如水溶性

**决策示例**:

```text
苯酚(pKa ~10):使用微观 pKa
胺(pKa ~9-10):使用微观 pKa
多可电离位点药物(N、O、酸性基团):使用 macropKa
跨消化道 pH 的 ADME 评估:使用 macropKa
```

### 构象异构体搜索与互变异构体搜索的选择

**以下情况使用构象异构体搜索(conformer search)**:

- 已知单一的互变异构体形式
- 需要用于对接、分子动力学或构效关系(SAR)分析的多样化 3D 构象集合
- 可旋转键主导化学空间

**以下情况使用互变异构体搜索(tautomer search)**:

- 互变异构平衡不确定(例如杂环、酮-烯醇体系)
- 需要对所有相关的质子化异构体建模
- 下游计算(对接、pKa)依赖于互变异构体形式

**组合工作流**:

```python
# 第一步:找出最佳互变异构体
taut_wf = rowan.submit_tautomer_search_workflow(
    initial_molecule="O=c1[nH]ccnc1",
    name="imidazole tautomers",
)
best_taut = taut_wf.result().best_tautomer

# 第二步:从最佳互变异构体生成构象异构体
conf_wf = rowan.submit_conformer_search_workflow(
    initial_molecule=best_taut,
    name="imidazole conformers",
)
```

### 对接、类似物对接与共折叠的选择

| 工作流 | 使用场景 | 输入 | 输出 |
|----------|----------|-------|--------|
| 对接(Docking) | 单配体、已知口袋 | 蛋白质 + SMILES + 口袋坐标 | 位姿、打分、dG |
| 类似物对接(Analogue docking) | 5-100+ 个相关化合物 | 蛋白质 + SMILES 列表 + 参照配体 | 所有位姿，以参照对齐 |
| 蛋白质-配体共折叠(Cofolding) | 只有序列 + 配体，无晶体结构 | 蛋白质序列 + SMILES | 机器学习预测的结合复合物 |

## 蛋白质相关工具

### 上传蛋白质

```python
# 从本地 PDB 文件
protein = rowan.upload_protein(
    name="egfr_kinase_domain",
    file_path="egfr_kinase.pdb",
)

# 从 PDB 数据库
protein_from_pdb = rowan.create_protein_from_pdb_id(
    name="CDK2 (1M17)",
    code="1M17",
)

# 获取此前上传过的蛋白质
protein = rowan.retrieve_protein("protein-uuid")

# 列出所有蛋白质
my_proteins = rowan.list_proteins()
```

### 蛋白质准备指南

- **文件格式**:PDB、mmCIF(Rowan 会自动检测)
- **水分子**:Rowan 通常会保留相关的水分子；如需要，可在上传前去除大量水分子
- **杂原子**:辅因子、离子和结合的配体通常会被保留；上传前应去除不需要的杂原子
- **多链蛋白质**:完全支持
- **分辨率**:支持 NMR 结构、同源模建结构(homology models)和冷冻电镜(cryo-EM)结构；质量会影响下游预测结果
- **验证**:Rowan 会验证 PDB 语法；严重畸形的文件可能会被拒绝

## 工作流目录

九种常见工作流类别——描述符、微观 pKa、MacropKa、构象异构体搜索、互变异构体搜索、对接、类似物对接、MSA 生成，以及蛋白质-配体共折叠——各自附带提交代码和结果结构，再加上每种受支持工作流类型的完整清单(核心建模、基于结构的设计、进阶计算化学、反应化学、进阶性质预测、结合自由能，以及序列与结构生物学),详见
[references/workflow_catalog.md](references/workflow_catalog.md)。

## 批量提交、Webhook 与异步工作

批量提交/轮询/获取、非阻塞的"提交后检查"(fire-and-check)模式、Webhook 设置、密钥的创建与轮换、载荷与签名验证(附 FastAPI 处理示例),以及 Webhook 最佳实践，详见
[references/batch_and_webhooks.md](references/batch_and_webhooks.md)。

## 访问权限、定价与 Credits

免费层级的限制、每种工作流的 credit 消耗量，以及典型成本估算，详见
[references/access_and_pricing.md](references/access_and_pricing.md)。

## 完整示例与故障排查

一个完整的先导化合物优化(lead-optimization)项目案例——项目搭建、互变异构体、跨类似物系列的 pKa、结果收集，以及后续对接——详见
[references/end_to_end_example.md](references/end_to_end_example.md)。

常见错误及其修复方法，以及调试技巧，详见
[references/troubleshooting.md](references/troubleshooting.md)。

## 推荐使用模式

- **优先使用 Rowan 原生工作流**,而不是在有现成方案时手工拼装底层调用
- 对任何非平凡规模的项目(超过 5 个工作流),**使用项目和文件夹**
- **使用 `result()` 阻塞等待直至完成**(默认:`wait=True, poll_interval=5`)
- **优先使用类型化的结果属性**,对未映射的字段再回退到 `.data`
- 对化合物库或类似物系列,**使用批量提交**
- 对多步骤化学项目,**串联工作流**:
  - `pKa → macropKa → permeability`(渗透性)(ADME 评估)
  - `互变异构体搜索 → 对接 → 位姿分析 MD`(位姿精修)
  - `MSA 生成 → 蛋白质-配体共折叠`(AI 结构预测)
- 对长时间运行的项目(超过 50 个工作流)或异步流水线,**使用 Webhook**
- 对大规模构象异构体/对接搜索的交互式反馈,**使用流式返回**

## 小结

当你的工作流需要为分子设计任务提供云端执行能力时，尤其是当你希望在小分子建模、蛋白质、对接、ADME 预测和机器学习结构生成之间使用统一的 API 和一致的结果处理方式时，请使用 Rowan。

Rowan 是一个分子设计工作流平台，而不仅仅是一个远程化学计算引擎。它负责基础设施扩展、结果持久化和多步骤流水线编排，让你可以专注于科学本身。
