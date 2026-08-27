# Medchem

## 概述

Medchem 是来自 [datamol-io](https://github.com/datamol-io/medchem) 的一个 Python 库，用于药物发现中的分子过滤与优先级排序。它应用了源自文献的成药性(drug-likeness)规则、命名的警示结构集合、复杂度阈值、化学基团检测，以及一套自定义查询语言，用于大规模地对化合物库进行分级筛选。这些过滤器是与具体情境相关的指导原则——应结合领域专业知识和靶点知识一同使用。

**版本说明**: 示例针对的是 **medchem 2.0.5**(PyPI 稳定版,2024 年 11 月)。要求 **Python ≥3.9**。依赖 **datamol** 和 **RDKit**(会自动安装)。`RuleFilters` 及各结构过滤器类返回 **pandas DataFrame**。Lilly demerit 需要可选的原生二进制文件(`mamba install lilly-medchem-rules`)。

## 何时使用本 Skill

在以下情况下应使用本 skill:
- 对化合物库应用成药性规则(Lipinski、Veber、CNS、类先导化合物)
- 按结构警示、PAINS 或 NIBR 筛选文库规则对分子进行过滤
- 为苗头到先导(hit-to-lead)或先导优化对化合物进行优先级排序
- 依据 ZINC 衍生的阈值计算复杂度指标
- 检测官能团或命名的子结构集合
- 用 medchem 查询语言构建多标准过滤器

## 安装

```bash
uv pip install medchem datamol
```

可选——Eli Lilly demerit 过滤器(需要 conda-forge 原生二进制文件):

```bash
mamba install -c conda-forge lilly-medchem-rules
```

## 核心能力

### 1. 药物化学规则

通过 `medchem.rules` 应用已确立的成药性规则。

**列出可用规则**:

```python
import medchem as mc

mc.rules.RuleFilters.list_available_rules_names()
# ['rule_of_five', 'rule_of_five_beyond', 'rule_of_four', 'rule_of_three', ...]
```

**对单个分子应用单条规则**:

```python
import datamol as dm
import medchem as mc

smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"  # aspirin
mc.rules.basic_rules.rule_of_five(smiles)   # True
mc.rules.basic_rules.rule_of_cns(smiles)    # True
mc.rules.basic_rules.rule_of_veber(smiles)  # True
```

**用 `RuleFilters` 应用多条规则(返回一个 DataFrame):**

```python
import datamol as dm
import medchem as mc

mols = [dm.to_mol(s) for s in smiles_list]

rfilter = mc.rules.RuleFilters(
    rule_list=["rule_of_five", "rule_of_oprea", "rule_of_cns", "rule_of_leadlike_soft"]
)
df = rfilter(mols=mols, n_jobs=-1, progress=True, keep_props=False)

# Columns: mol, pass_all, pass_any, rule_of_five, rule_of_oprea, ...
passing = df[df["pass_all"]]
```

使用 `keep_props=True` 可以在结果中包含计算得到的描述符(`mw`、`clogp`、`tpsa` 等)。

### 2. 结构警示过滤器

用 `medchem.structural` 检测有问题的模式。这两个类都返回带有 `pass_filter`、`status` 和 `reasons` 列的 **DataFrame**。

**常见警示(源自 ChEMBL 的规则集)**:

```python
import medchem as mc

alert_filter = mc.structural.CommonAlertsFilters()
df = alert_filter(mols=mol_list, n_jobs=-1, progress=True)
# df columns: mol, pass_filter, status, reasons

clean = df[df["pass_filter"]]
```

**NIBR 过滤器(诺华筛选文库的整理规则)**:

```python
nibr_filter = mc.structural.NIBRFilters()
df = nibr_filter(mols=mol_list, n_jobs=-1, progress=True)
# df columns: mol, pass_filter, status, severity, reasons, n_covalent_motif, special_mol
```

`severity >= 10` 的化合物默认会被排除(参见 NIBR 论文)。

### 3. 命名的目录过滤器(PAINS、Brenk 等)

使用 `medchem.catalogs.NamedCatalogs` 获取 RDKit `FilterCatalog` 实例，或使用函数式 API:

```python
import medchem as mc

# List available named catalogs
mc.catalogs.list_named_catalogs()
# ['tox', 'pains', 'pains_a', 'brenk', 'nibr', 'zinc', ...]

# Functional API — True means molecule passes (no alert match)
passes = mc.functional.alert_filter(mols=mol_list, alerts=["pains"], n_jobs=-1)

# Or via catalog objects
passes = mc.functional.catalog_filter(
    mols=mol_list,
    catalogs=[mc.catalogs.NamedCatalogs.pains()],
    n_jobs=-1,
)
```

### 4. 函数式 API

`medchem.functional` 提供了返回布尔掩码(True = 通过)的一次调用式封装:

```python
import medchem as mc

mc.functional.rules_filter(mols=mol_list, rules=["rule_of_five", "rule_of_cns"], n_jobs=-1)
mc.functional.nibr_filter(mols=mol_list, max_severity=10, n_jobs=-1)
mc.functional.alert_filter(mols=mol_list, alerts=["pains", "brenk"], n_jobs=-1)
mc.functional.complexity_filter(mols=mol_list, complexity_metric="bertz", limit="99", n_jobs=-1)
```

其他辅助函数:`catalog_filter`、`chemical_group_filter`、`lilly_demerit_filter`(需要可选的二进制文件)、`macrocycle_filter`、`bredt_filter`、`protecting_groups_filter`,以及更多。

### 5. 化学基团

通过 `medchem.groups` 检测官能团以及经过整理的模式集合:

```python
import medchem as mc

# Browse available group collections
mc.groups.list_default_chemical_groups()
# ['privileged_scaffolds', 'common_warhead_covalent_inhibitors', 'rings_in_drugs', ...]

group = mc.groups.ChemicalGroup(groups=["privileged_scaffolds"])
group.has_match(mol)                          # bool
group.get_matches(mol)                        # dict of group → atom indices
group.filter(mols)                            # molecules matching the group

# Returns molecules that do NOT match the group
mc.functional.chemical_group_filter(mols=mol_list, chemical_group=group, n_jobs=-1)
```

可以通过 `groups_db` 从文件中加载自定义基团(CSV 文件，含 `smiles`/`smarts`、`name`、`group` 列)。

### 6. 分子复杂度

将复杂度指标与预先计算好的 ZINC-15 百分位阈值进行比较:

```python
import medchem as mc

# Single molecule
cf = mc.complexity.ComplexityFilter(limit="99", complexity_metric="bertz")
cf(mol)  # True if below 99th-percentile threshold

# Batch via functional API
mc.functional.complexity_filter(
    mols=mol_list,
    complexity_metric="bertz",  # also: sas, qed, whitlock, barone, smcm, twc
    limit="99",
    n_jobs=-1,
)

# Direct metric functions
mc.complexity.WhitlockCT(mol)
mc.complexity.BaroneCT(mol)
```

### 7. 骨架约束

`medchem.constraints.Constraints` 匹配一个核心骨架，并应用逐原子的约束函数——而不是简单的 MW/LogP 范围。对于属性范围限制，应使用 `RuleFilters`、通过 `mc.rules.list_descriptors()` 获取的描述符，或查询语言。

```python
import datamol as dm
import medchem as mc

core = dm.to_mol("c1ccccc1")
constraints = mc.constraints.Constraints(
    core=core,
    constraint_fns={"query": lambda mol, atom_idx, query: ...},
)
constraints(mol)
```

### 8. Medchem 查询语言

用 `medchem.query.QueryFilter` 构建多标准过滤器:

```python
import medchem as mc

# Rule + alert combination
qf = mc.query.QueryFilter('MATCHRULE("rule_of_five") AND NOT HASALERT("pains")')
mask = qf(mols=mol_list, n_jobs=-1)  # list[bool]

# CNS-like with property bounds
qf = mc.query.QueryFilter('MATCHRULE("rule_of_cns") AND HASPROP("tpsa", <=, 90)')
mask = qf(mols=mol_list, n_jobs=-1)
```

**查询语法**:
- `MATCHRULE("rule_of_five")` —— 应用一条命名规则
- `HASALERT("pains")` —— 匹配一个命名目录(`pains`、`brenk`、`nibr`、`tox` 等)
- `HASPROP("mw", <, 500)` —— 比较某个描述符(比较符不加引号)
- `HASGROUP("privileged_scaffolds")` —— 匹配一个化学基团
- `HASSUBSTRUCTURE("c1ccccc1")` —— 子结构匹配
- 运算符:`AND`、`OR`、`NOT`

列出可用的描述符:`mc.rules.list_descriptors()`

## 工作流模式

### 模式 1:化合物库的初步筛选

```python
import datamol as dm
import medchem as mc
import pandas as pd

df = pd.read_csv("compounds.csv")
mols = [dm.to_mol(s) for s in df["smiles"]]

# Drug-likeness rules
rules_df = mc.rules.RuleFilters(rule_list=["rule_of_five", "rule_of_veber"])(mols=mols, n_jobs=-1)

# PAINS + common alerts via query
qf = mc.query.QueryFilter('MATCHRULE("rule_of_five") AND NOT HASALERT("pains")')
pass_mask = qf(mols=mols, n_jobs=-1)

df["passes_rules"] = rules_df["pass_all"].values
df["drug_like"] = pass_mask
filtered_df = df[df["drug_like"]]
filtered_df.to_csv("filtered_compounds.csv", index=False)
```

### 模式 2:先导优化过滤

```python
import medchem as mc

rules_df = mc.rules.RuleFilters(rule_list=["rule_of_leadlike_soft"])(mols=candidates, n_jobs=-1)
nibr_df = mc.structural.NIBRFilters()(mols=candidates, n_jobs=-1)
complex_mask = mc.functional.complexity_filter(
    mols=candidates, complexity_metric="bertz", limit="95", n_jobs=-1
)

passes = (
    rules_df["pass_all"]
    & nibr_df["pass_filter"]
    & complex_mask
)
```

### 模式 3:检测官能团

```python
import medchem as mc

group = mc.groups.ChemicalGroup(groups=["common_warhead_covalent_inhibitors"])
matches = [group.has_match(mol) for mol in mol_list]
warhead_mols = [mol for mol, m in zip(mol_list, matches) if m]
```

## 最佳实践

1. **情境很重要**——已上市药物常常违反 Ro5;前药和天然产物是常见的例外情况。
2. **组合使用过滤器**——规则、警示目录和复杂度阈值搭配在一起效果最好。
3. **使用并行化**——对超过 1000 个分子的库，传入 `n_jobs=-1`。
4. **检查返回类型**——`RuleFilters` 和各结构类返回 DataFrame;函数式辅助函数返回布尔数组。
5. **Lilly demerit 是可选的**——需单独安装 `lilly-medchem-rules`;函数式 API 中默认的最大 demerit 值为 160。
6. **记录决策依据**——保留 `status`、`reasons` 和 `severity` 列，以便留存审计轨迹。

## 资源

### references/api_guide.md
按模块划分的 API 参考文档，含函数签名、返回类型和使用模式。

### references/rules_catalog.md
可用规则、警示集合、复杂度指标的目录，以及过滤器选择指南。

### scripts/filter_molecules.py
用于 CSV/TSV/SDF/SMILES 输入的批量过滤脚本，支持可配置的规则、警示和复杂度阈值。

```bash
uv run python scripts/filter_molecules.py input.csv \
  --rules rule_of_five,rule_of_cns --pains --nibr --output filtered.csv
```

## 文档

- 官方文档: https://medchem-docs.datamol.io/
- GitHub: https://github.com/datamol-io/medchem
- PyPI: https://pypi.org/project/medchem/ (2.0.5)
