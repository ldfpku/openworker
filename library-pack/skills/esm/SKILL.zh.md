# ESM: Evolutionary Scale Modeling

## 概述

ESM 提供了用于理解、生成和设计蛋白质的蛋白质语言模型。将本 skill 用于当前的 EvolutionaryScale/Biohub 工作流:用于生成式设计的 ESM3、用于表示学习和嵌入(embedding)的 ESMC、托管的 Forge/Biohub 推理服务，以及 ESMFold2 全原子结构预测。

## 核心能力

### 1. 用 ESM3 生成蛋白质序列

使用多模态生成式建模，生成具有期望性质的新型蛋白质序列。

**何时使用**:
- 设计具有特定功能属性的蛋白质
- 补全部分蛋白质序列
- 生成已有蛋白质的变体
- 创建具有期望结构特征的蛋白质

**基本用法**:

```python
from esm.models.esm3 import ESM3
from esm.sdk.api import ESM3InferenceClient, ESMProtein, GenerationConfig

# Load local open weights after accepting the license on Hugging Face.
model: ESM3InferenceClient = ESM3.from_pretrained("esm3-open").to("cuda")

# Create protein prompt
protein = ESMProtein(sequence="MPRT___KEND")  # '_' represents masked positions

# Generate completion
protein = model.generate(protein, GenerationConfig(track="sequence", num_steps=8))
print(protein.sequence)
```

**通过 Forge API 进行远程/云端使用**:

```python
import os
import esm
from esm.sdk.api import ESMProtein, GenerationConfig

# Same interface as local ESM3; token from ESM_API_KEY (see Authentication)
model = esm.sdk.client("esm3-medium-2024-08", token=os.environ["ESM_API_KEY"])

# Generate
protein = model.generate(protein, GenerationConfig(track="sequence", num_steps=8))
```

关于 ESM3 模型的详细规格、进阶生成配置以及多模态提示示例，参见 `references/esm3-api.md`。

### 2. 结构预测与逆向折叠(Inverse Folding)

使用 ESM3 的结构轨道(structure track),实现从序列预测结构，或逆向折叠(从结构设计序列)。

**结构预测**:

```python
from esm.sdk.api import ESM3InferenceClient, ESMProtein, GenerationConfig

# Predict structure from sequence
protein = ESMProtein(sequence="MPRTKEINDAGLIVHSP...")
protein_with_structure = model.generate(
    protein,
    GenerationConfig(track="structure", num_steps=protein.sequence.count("_"))
)

# Access predicted structure
coordinates = protein_with_structure.coordinates  # 3D coordinates
pdb_string = protein_with_structure.to_pdb()
```

**逆向折叠(从结构生成序列)**:

```python
# Design sequence for a target structure
protein_with_structure = ESMProtein.from_pdb("target_structure.pdb")
protein_with_structure.sequence = None  # Remove sequence

# Generate sequence that folds to this structure
designed_protein = model.generate(
    protein_with_structure,
    GenerationConfig(track="sequence", num_steps=50, temperature=0.7)
)
```

### 3. 用 ESM C 生成蛋白质嵌入(Embeddings)

为函数预测、分类或相似性分析等下游任务生成高质量嵌入。

**何时使用**:
- 为机器学习提取蛋白质表示
- 计算序列相似度
- 为蛋白质分类提取特征
- 蛋白质相关任务的迁移学习

**基本用法**:

```python
from esm.models.esmc import ESMC
from esm.sdk.api import ESMProtein, LogitsConfig

# Load ESM C model
model = ESMC.from_pretrained("esmc_300m").to("cuda")

# Get embeddings
protein = ESMProtein(sequence="MPRTKEINDAGLIVHSP...")
protein_tensor = model.encode(protein)
logits_output = model.logits(
    protein_tensor,
    LogitsConfig(sequence=True, return_embeddings=True),
)
embeddings = logits_output.embeddings
```

**批处理**:

```python
# Encode multiple proteins
proteins = [
    ESMProtein(sequence="MPRTKEIND..."),
    ESMProtein(sequence="AGLIVHSPQ..."),
    ESMProtein(sequence="KTEFLNDGR...")
]

embeddings_list = [
    model.logits(
        model.encode(p),
        LogitsConfig(sequence=True, return_embeddings=True),
    ).embeddings
    for p in proteins
]
```

关于 ESM C 模型细节、效率比较以及进阶嵌入策略，参见 `references/esm-c-api.md`。

### 4. 功能条件化生成与注释

使用 ESM3 的功能轨道(function track),生成带有特定功能注释的蛋白质，或从序列预测功能。

**功能条件化生成**:

```python
from esm.sdk.api import ESMProtein, FunctionAnnotation, GenerationConfig

# Create protein with desired function
protein = ESMProtein(
    sequence="_" * 200,  # Generate 200 residue protein
    function_annotations=[
        FunctionAnnotation(label="fluorescent_protein", start=50, end=150)
    ]
)

# Generate sequence with specified function
functional_protein = model.generate(
    protein,
    GenerationConfig(track="sequence", num_steps=200)
)
```

### 5. 思维链(Chain-of-Thought)生成

使用 ESM3 的思维链生成方式，对蛋白质设计进行迭代式优化。

```python
from esm.sdk.api import GenerationConfig

# Multi-step refinement
protein = ESMProtein(sequence="MPRT" + "_" * 100 + "KEND")

# Step 1: Generate initial structure
config = GenerationConfig(track="structure", num_steps=50)
protein = model.generate(protein, config)

# Step 2: Refine sequence based on structure
config = GenerationConfig(track="sequence", num_steps=50, temperature=0.5)
protein = model.generate(protein, config)

# Step 3: Predict function
config = GenerationConfig(track="function", num_steps=20)
protein = model.generate(protein, config)
```

### 6. 使用 Forge API 进行批处理

使用 Forge 的异步方法高效处理多个蛋白质。

```python
import os
import asyncio
import esm
from esm.sdk.api import ESMProtein, GenerationConfig

client = esm.sdk.client("esm3-medium-2024-08", token=os.environ["ESM_API_KEY"])

# Async batch processing
async def batch_generate(proteins_list):
    tasks = [
        client.async_generate(protein, GenerationConfig(track="sequence"))
        for protein in proteins_list
    ]
    return await asyncio.gather(*tasks)

# Execute
proteins = [ESMProtein(sequence=f"MPRT{'_' * 50}KEND") for _ in range(10)]
results = asyncio.run(batch_generate(proteins))
```

关于 Forge API 的详细文档、身份认证、速率限制以及批处理模式，参见 `references/forge-api.md`。

## 模型选择指南

**ESM3 模型(生成式)**:
- `esm3-open`(14 亿参数)—— 开放权重，接受 Hugging Face 许可后可本地使用
- `esm3-medium-2024-08`(70 亿参数)—— 质量与速度的最佳平衡(仅限 Forge)
- `esm3-large-2024-03`(980 亿参数)—— 质量最高，速度较慢(仅限 Forge)

**ESM C 模型(嵌入)**:
- `esmc_300m` / `esmc-300m-2024-12`(30 层)—— 轻量级，推理速度快(开放权重，可本地使用)
- `esmc_600m` / `esmc-600m-2024-12`(36 层)—— 性能均衡(开放权重，可本地使用)
- `esmc-6b-2024-12`(80 层)—— 质量最高(Forge API;本地使用 6B 权重需要 Forge 或 SageMaker)

本地的 `ESMC.from_pretrained()` 示例使用带下划线的别名(`esmc_300m`、`esmc_600m`)。托管的 API 客户端使用带日期的模型 id,例如 `esmc-600m-2024-12`。

**选择标准**:
- **本地开发/测试**: 使用 `esm3-open` 或 `esmc_300m`
- **生产环境质量**: 通过 Forge 使用 `esm3-medium-2024-08`
- **最高精度**: 通过 Forge 使用 `esm3-large-2024-03` 或 `esmc-6b-2024-12`
- **高吞吐量**: 使用 Forge 或 Biohub API,并明确设置异步并发上限
- **成本优化**: 使用更小的模型，实施缓存策略

## 安装

从 PyPI 安装(EvolutionaryScale 发布的 [`esm` on PyPI](https://pypi.org/project/esm/))。当前 PyPI 发行版本:**3.2.3**(2025 年 10 月 14 日)。要求 **Python >=3.12,<3.13**。

**基础安装**:

```bash
uv pip install "esm==3.2.3"
```

**搭配 Flash Attention(推荐用于 NVIDIA GPU 上更快的推理)**:

```bash
uv pip install "esm==3.2.3"
uv pip install flash-attn --no-build-isolation
```

Forge 客户端已随 `esm` 软件包一同分发——使用 ESM3 或 ESMC 的 Forge 推理无需额外安装。

## 身份认证

Forge API 的访问需要一个 API 密钥。绝不要把令牌硬编码在脚本中，也不要将其提交到版本控制系统中。

1. 检查环境中是否已经设置了 `ESM_API_KEY`。
2. 如果没有，检查本地 `.env` 文件中是否只含 `ESM_API_KEY`(不要加载与之无关的其他密钥)。
3. 如果仍然缺失，针对 Biohub API 在 [Biohub developer console](https://biohub.ai/developer-console/api-keys) 创建密钥，或针对旧版 Forge 托管的 ESM3/ESMC 访问在 [Forge](https://forge.evolutionaryscale.ai) 创建密钥。

```python
import os

token = os.environ["ESM_API_KEY"]  # raises KeyError if unset
```

当省略 `token` 参数时,`esm.sdk.client()` 会自动读取 `ESM_API_KEY`。要把端点 URL 固定在受信任的主机上，如 `https://forge.evolutionaryscale.ai` 或 `https://biohub.ai`;不要从不受信任的用户输入中获取 API 主机地址。

**Biohub 平台**: EvolutionaryScale 和 Forge 目前通过 [biohub.ai](https://biohub.ai) 呈现当前的托管模型。SDK 中的类名可能仍然引用 "Forge"。关于 ESMFold2 以及 Biohub 特有的设置，参见 `references/biohub-platform.md`。

## 常见工作流

关于详细示例和完整工作流，参见 `references/workflows.md`,其中包括:
- 借助思维链方式进行新型 GFP 设计
- 蛋白质变体生成与筛选
- 基于结构的序列优化
- 功能预测流水线
- 基于嵌入的聚类与分析

## 参考文档

本 skill 包含全面的参考文档:

- `references/esm3-api.md` —— ESM3 模型架构、API 参考、生成参数，以及多模态提示
- `references/esm-c-api.md` —— ESM C 模型细节、嵌入策略，以及性能优化
- `references/forge-api.md` —— Forge 平台文档、身份认证、批处理，以及部署
- `references/biohub-platform.md` —— Biohub API 迁移、ESMFold2 结构预测，以及 developer-console 身份认证
- `references/workflows.md` —— 完整示例与常见工作流模式

这些参考文档包含详细的 API 规格、参数说明，以及进阶用法模式。根据具体任务的需要按需加载。

## 最佳实践

**对于生成任务**:
- 原型开发阶段先从较小的模型开始(`esm3-open`)
- 使用 temperature 参数控制多样性(0.0 = 确定性,1.0 = 多样化)
- 对复杂设计，使用思维链方式实施迭代式优化
- 用结构预测或湿实验(wet-lab experiments)校验生成的序列

**对于嵌入任务**:
- 尽可能对序列进行批处理以提升效率
- 对重复分析的嵌入结果进行缓存
- 在计算相似度时对嵌入向量做归一化
- 根据下游任务需求选用合适的模型规模

**对于生产环境部署**:
- 使用 Forge API 以获得可扩展性和最新模型
- 为 API 调用实现错误处理和重试逻辑
- 监控 token 使用量并实施速率限制
- 可考虑使用 AWS SageMaker 部署以获得专用基础设施

## 资源与文档

- **GitHub 仓库**: <https://github.com/Biohub/esm>（当前的 ESMC/ESMFold2/Biohub 文档；ESM3 文档仍可从该仓库中链接访问）
- **Forge 平台**: https://forge.evolutionaryscale.ai
- **Biohub 平台**: https://biohub.ai
- **科学论文**: Hayes et al., Science (2025) - https://www.science.org/doi/10.1126/science.ads0018
- **博客文章**:
  - ESM3 发布:https://www.evolutionaryscale.ai/blog/esm3-release
  - ESM C 发布:https://www.evolutionaryscale.ai/blog/esm-cambrian
- **社区**: Slack 社区,https://bit.ly/3FKwcWd
- **模型权重**: Hugging Face 上的 EvolutionaryScale 和 Biohub 组织

## 负责任的使用

ESM 旨在用于蛋白质工程、药物发现和科学研究中的有益应用。在设计新型蛋白质时，请遵循 Responsible Biodesign Framework（<https://responsiblebiodesign.ai/>）以及 Biohub Acceptable Use Policy（<https://biohub.org/acceptable-use-policy/>）。在开展实验验证之前，请充分考虑蛋白质设计的生物安全和伦理影响。
