# COBRApy - 基于约束的重建与分析

## 概述

COBRApy 是一个用于代谢模型的基于约束的重建与分析(COBRA,constraint-based reconstruction and analysis)的 Python 库，是系统生物学研究中不可或缺的工具。可以用它来处理基因组尺度的代谢模型、对细胞代谢进行计算模拟、开展代谢工程分析，并预测表型行为。

**版本说明**: 示例针对 PyPI 上的 **cobra 0.31.1**(导入名为 `cobra`)。文档: [cobrapy.readthedocs.io](https://cobrapy.readthedocs.io/en/latest/)。仓库: [opencobra/cobrapy](https://github.com/opencobra/cobrapy)。

## 何时使用此技能

在以下情况使用此技能:
- 加载、构建或导出基因组尺度代谢模型(SBML、JSON、YAML)
- 在 COBRA 模型上运行 FBA、pFBA、FVA 或通量采样(flux sampling)
- 执行基因或反应敲除筛选，以及生产包络线(production envelope)分析
- 设计或优化生长培养基与交换约束
- 对不可行的模型进行缺口填补(gap-filling)或验证模型一致性

## 安装

```bash
uv pip install "cobra==0.31.1"
```

MATLAB 模型 I/O(可选):

```bash
uv pip install "cobra[array]==0.31.1"
```

COBRApy 使用 [optlang](https://optlang.readthedocs.io/) 来对接求解器。GLPK 会通过 `swiglpk` 自动安装。对于大型的 MILP/QP 问题,cobra 0.29+ 增加了一个**混合**（hybrid）求解器(HIGHS/OSQP);`model.solver = "osqp"` 现在会走混合求解器路径，并且在未来版本中可能在纯 LP 问题上报错——在可用时优先使用 `model.solver = "hybrid"`。

## 核心能力

COBRApy 提供了组织在几个关键领域中的一整套工具:

### 1. 模型管理

从仓库或文件中加载已有模型:
```python
from cobra.io import load_model

# Bundled locally (no network): textbook, iJO1366, salmonella
model = load_model("textbook")      # alias for e_coli_core (95 reactions)
model = load_model("e_coli_core")   # same core E. coli model
model = load_model("iJO1366")       # genome-scale E. coli (bundled)
model = load_model("salmonella")    # Salmonella iYS1720 (bundled)

# Remote (BiGG / BioModels; requires network, cached after first fetch)
model = load_model("iML1515")       # E. coli genome-scale on BiGG

# Load from files
from cobra.io import read_sbml_model, load_json_model, load_yaml_model
model = read_sbml_model("path/to/model.xml")
model = load_json_model("path/to/model.json")
model = load_yaml_model("path/to/model.yml")
```

以各种格式保存模型:
```python
from cobra.io import write_sbml_model, save_json_model, save_yaml_model
write_sbml_model(model, "output.xml")  # Preferred format
save_json_model(model, "output.json")  # For Escher compatibility
save_yaml_model(model, "output.yml")   # Human-readable
```

### 2. 模型结构与组件

访问并检查模型组件:
```python
# Access components
model.reactions      # DictList of all reactions
model.metabolites    # DictList of all metabolites
model.genes          # DictList of all genes

# Get specific items by ID or index
reaction = model.reactions.get_by_id("PFK")
metabolite = model.metabolites[0]

# Inspect properties
print(reaction.reaction)        # Stoichiometric equation
print(reaction.bounds)          # Flux constraints
print(reaction.gene_reaction_rule)  # GPR logic
print(metabolite.formula)       # Chemical formula
print(metabolite.compartment)   # Cellular location
```

### 3. 通量平衡分析(Flux Balance Analysis, FBA)

执行标准的 FBA 模拟:
```python
# Basic optimization
solution = model.optimize()
print(f"Objective value: {solution.objective_value}")
print(f"Status: {solution.status}")

# Access fluxes
print(solution.fluxes["PFK"])
print(solution.fluxes.head())

# Fast optimization (objective value only)
objective_value = model.slim_optimize()

# Change objective
model.objective = "ATPM"
solution = model.optimize()
```

简约 FBA(pFBA,最小化总通量):
```python
from cobra.flux_analysis import pfba
solution = pfba(model)
```

几何 FBA(geometric FBA,寻找中心解):
```python
from cobra.flux_analysis import geometric_fba
solution = geometric_fba(model)
```

### 4. 通量变异性分析(Flux Variability Analysis, FVA)

确定所有反应的通量范围:
```python
from cobra.flux_analysis import flux_variability_analysis

# Standard FVA
fva_result = flux_variability_analysis(model)

# FVA at 90% optimality
fva_result = flux_variability_analysis(model, fraction_of_optimum=0.9)

# Loopless FVA (eliminates thermodynamically infeasible loops)
fva_result = flux_variability_analysis(model, loopless=True)

# FVA for specific reactions
fva_result = flux_variability_analysis(
    model,
    reaction_list=["PFK", "FBA", "PGI"]
)
```

### 5. 基因与反应敲除研究

执行敲除分析:
```python
from cobra.flux_analysis import (
    single_gene_deletion,
    single_reaction_deletion,
    double_gene_deletion,
    double_reaction_deletion
)

# Single deletions
gene_results = single_gene_deletion(model)
reaction_results = single_reaction_deletion(model)

# Double deletions (uses multiprocessing)
double_gene_results = double_gene_deletion(
    model,
    processes=4  # Number of CPU cores
)

# Manual knockout using context manager
with model:
    model.genes.get_by_id("b0008").knock_out()
    solution = model.optimize()
    print(f"Growth after knockout: {solution.objective_value}")
# Model automatically reverts after context exit
```

### 6. 生长培养基与最小培养基

管理生长培养基:
```python
# View current medium
print(model.medium)

# Modify medium (must reassign entire dict)
medium = model.medium
medium["EX_glc__D_e"] = 10.0  # Set glucose uptake
medium["EX_o2_e"] = 0.0       # Anaerobic conditions
model.medium = medium

# Calculate minimal media
from cobra.medium import minimal_medium

# Minimize total import flux
min_medium = minimal_medium(model, minimize_components=False)

# Minimize number of components (uses MILP, slower)
min_medium = minimal_medium(
    model,
    minimize_components=True,
    open_exchanges=True
)
```

### 7. 通量采样(Flux Sampling)

对可行通量空间进行采样:
```python
from cobra.sampling import sample

# Sample using OptGP (default, supports parallel processing)
samples = sample(model, n=1000, method="optgp", processes=4)

# Sample using ACHR
samples = sample(model, n=1000, method="achr")

# Validate samples
from cobra.sampling import OptGPSampler
sampler = OptGPSampler(model, processes=4)
sampler.sample(1000)
validation = sampler.validate(sampler.samples)
print(validation.value_counts())  # Should be all 'v' for valid
```

### 8. 生产包络线(Production Envelopes)

计算表型相平面(phenotype phase plane):
```python
from cobra.flux_analysis import production_envelope

# Standard production envelope
envelope = production_envelope(
    model,
    reactions=["EX_glc__D_e", "EX_o2_e"],
    objective="EX_ac_e"  # Acetate production
)

# With carbon yield
envelope = production_envelope(
    model,
    reactions=["EX_glc__D_e", "EX_o2_e"],
    carbon_sources="EX_glc__D_e"
)

# Visualize (use matplotlib or pandas plotting)
import matplotlib.pyplot as plt
envelope.plot(x="EX_glc__D_e", y="EX_o2_e", kind="scatter")
plt.show()
```

### 9. 缺口填补(Gapfilling)

添加反应以使模型变得可行:
```python
from cobra.flux_analysis import gapfill

# Provide a universal reaction database (SBML/JSON); not bundled in cobra 0.31+
from cobra.io import read_sbml_model
universal = read_sbml_model("path/to/universal_reactions.xml")

# Perform gapfilling
with model:
    # Remove reactions to create gaps for demonstration
    model.remove_reactions([model.reactions.PGI])

    # Find reactions needed
    solution = gapfill(model, universal)
    print(f"Reactions to add: {solution}")
```

### 10. 模型构建

从零开始构建模型:
```python
from cobra import Model, Reaction, Metabolite

# Create model
model = Model("my_model")

# Create metabolites
atp_c = Metabolite("atp_c", formula="C10H12N5O13P3",
                   name="ATP", compartment="c")
adp_c = Metabolite("adp_c", formula="C10H12N5O10P2",
                   name="ADP", compartment="c")
pi_c = Metabolite("pi_c", formula="HO4P",
                  name="Phosphate", compartment="c")

# Create reaction
reaction = Reaction("ATPASE")
reaction.name = "ATP hydrolysis"
reaction.subsystem = "Energy"
reaction.lower_bound = 0.0
reaction.upper_bound = 1000.0

# Add metabolites with stoichiometry
reaction.add_metabolites({
    atp_c: -1.0,
    adp_c: 1.0,
    pi_c: 1.0
})

# Add gene-reaction rule
reaction.gene_reaction_rule = "(gene1 and gene2) or gene3"

# Add to model
model.add_reactions([reaction])

# Add boundary reactions
model.add_boundary(atp_c, type="exchange")
model.add_boundary(adp_c, type="demand")

# Set objective
model.objective = "ATPASE"
```

## 常见工作流

### 工作流 1:加载模型并预测生长

```python
from cobra.io import load_model

# Load model (textbook = fast tutorial; iJO1366 / iML1515 for genome-scale)
model = load_model("textbook")

# Run FBA
solution = model.optimize()
print(f"Growth rate: {solution.objective_value:.3f} /h")

# Show active pathways
print(solution.fluxes[solution.fluxes.abs() > 1e-6])
```

### 工作流 2:基因敲除筛选

```python
from cobra.io import load_model
from cobra.flux_analysis import single_gene_deletion

# Load model
model = load_model("textbook")
baseline = model.slim_optimize()

# Perform single gene deletions
results = single_gene_deletion(model)

# Find essential genes (growth < threshold)
essential_genes = results[results["growth"] < 0.01]
print(f"Found {len(essential_genes)} essential genes")

# Find genes with minimal impact
neutral_genes = results[results["growth"] > 0.9 * baseline]
```

### 工作流 3:培养基优化

```python
from cobra.io import load_model
from cobra.medium import minimal_medium

# Load model
model = load_model("textbook")

# Calculate minimal medium for 50% of max growth
target_growth = model.slim_optimize() * 0.5
min_medium = minimal_medium(
    model,
    target_growth,
    minimize_components=True
)

print(f"Minimal medium components: {len(min_medium)}")
print(min_medium)
```

### 工作流 4:通量不确定性分析

```python
from cobra.io import load_model
from cobra.flux_analysis import flux_variability_analysis
from cobra.sampling import sample

# Load model
model = load_model("textbook")

# First check flux ranges at optimality
fva = flux_variability_analysis(model, fraction_of_optimum=1.0)

# For reactions with large ranges, sample to understand distribution
samples = sample(model, n=1000)

# Analyze specific reaction
reaction_id = "PFK"
import matplotlib.pyplot as plt
samples[reaction_id].hist(bins=50)
plt.xlabel(f"Flux through {reaction_id}")
plt.ylabel("Frequency")
plt.show()
```

### 工作流 5:用上下文管理器做临时改动

使用上下文管理器进行临时修改:
```python
# Model remains unchanged outside context
with model:
    # Temporarily change objective
    model.objective = "ATPM"

    # Temporarily modify bounds
    model.reactions.EX_glc__D_e.lower_bound = -5.0

    # Temporarily knock out genes
    model.genes.b0008.knock_out()

    # Optimize with changes
    solution = model.optimize()
    print(f"Modified growth: {solution.objective_value}")

# All changes automatically reverted
solution = model.optimize()
print(f"Original growth: {solution.objective_value}")
```

## 关键概念

### DictList 对象
模型对反应、代谢物和基因使用 `DictList` 对象——其行为兼具列表和字典的特点:
```python
# Access by index
first_reaction = model.reactions[0]

# Access by ID
pfk = model.reactions.get_by_id("PFK")

# Query methods
atp_reactions = model.reactions.query("atp")
```

### 通量约束
反应边界(bounds)定义了可行的通量范围:
- **不可逆(Irreversible)**:`lower_bound = 0, upper_bound > 0`
- **可逆(Reversible)**:`lower_bound < 0, upper_bound > 0`
- 用 `.bounds` 同时设置上下两个边界，以避免出现不一致

### 基因-反应规则(Gene-Reaction Rules, GPR)
将基因与反应关联起来的布尔逻辑:
```python
# AND logic (both required)
reaction.gene_reaction_rule = "gene1 and gene2"

# OR logic (either sufficient)
reaction.gene_reaction_rule = "gene1 or gene2"

# Complex logic
reaction.gene_reaction_rule = "(gene1 and gene2) or (gene3 and gene4)"
```

### 交换反应(Exchange Reactions)
代表代谢物导入/导出的特殊反应:
- 按惯例以前缀 `EX_` 命名
- 正通量 = 分泌，负通量 = 摄取
- 通过 `model.medium` 字典进行管理

## 最佳实践

1. **使用上下文管理器**进行临时修改，以避免状态管理问题
2. **验证模型**——在分析前用 `model.slim_optimize()` 确保其可行
3. 优化之后**检查解的状态**——`optimal` 表示求解成功
4. 在需要考虑热力学可行性时,**使用无环(loopless)FVA**
5. 在 FVA 中适当地**设置 fraction_of_optimum**,以探索次优空间
6. **并行化**计算开销大的操作(采样、双重敲除)——在基因组尺度模型上从较小的 `n` 和 `processes=1` 开始
7. 模型交换与长期存储**优先使用 SBML 格式**
8. 只需要目标函数值时,**使用 slim_optimize()** 以提升性能
9. **验证通量样本**以确保数值稳定性
10. 在工作流示例中写出 CSV/PNG 文件之前,**确认输出路径**

## 故障排查

**不可行的解**:检查培养基约束、反应边界和模型一致性
**优化缓慢**:通过 `model.solver` 尝试不同的求解器(GLPK、CPLEX、Gurobi)
**无界的解**:核实交换反应是否设置了合适的上界
**导入错误**:确保文件格式正确、SBML 标识符有效

## 参考资料

关于详细的工作流和 API 用法，请参阅:
- `references/workflows.md` - 详尽的分步工作流示例
- `references/api_quick_reference.md` - 常用函数签名和用法模式

官方文档: https://cobrapy.readthedocs.io/en/latest/
