# ETE Toolkit 4

## 范围

使用 ETE 4 来处理一棵已有的树:

- 读取 Newick/Nexus 格式，然后对 Newick 树进行检查、注释、变换、设根(root)、修剪(prune)和写出
- 比较拓扑结构并计算系统发育距离
- 使用 `TreePattern` 查找重复出现的子树拓扑
- 使用 `PhyloTree` 分析基因树
- 查询本地的 NCBI 或 GTDB 分类学数据库
- 使用 SmartView 交互式地探索大型树
- 使用 SmartView 渲染 PNG,或使用可选的 Qt treeview 渲染 PNG/PDF/SVG

ETE 不能替代序列比对或系统发育推断软件。对于原始序列，请先使用 MAFFT 或其他比对工具，以及 IQ-TREE 2、FastTree 或其他推断工具；然后再把得到的树载入 ETE。

## 当前目标版本

本技能面向 **ETE 4.4.0**,该版本发布于 2025 年 9 月 3 日，并已于 2026 年 7 月 23 日核实为当前的 PyPI 发行版本。

ETE 4 的文档请使用 `https://etetoolkit.github.io/ete/`。`etetoolkit.org/docs/latest` 这些页面尽管 URL 名称如此，实际上是旧版 ETE 3 的文档。

不要不假思索地把下列示例照搬回 ETE 3 的写法:

- 包与导入:是 `ete4`,不是 `ete3`
- 文件输入:传入一个已打开的文件对象；字符串仅用于 Newick 文本，不要依赖 ETE 4.4.0 中残留的路径字符串启发式判断
- Newick 选择:用 `parser=`,不是 `format=`
- 节点元数据:`props`、`add_prop()` 和 `add_props()`
- 遍历:`leaves()`、`descendants()` 及相关方法返回的是迭代器
- 谓词:`node.is_leaf` 和 `node.is_root` 是属性(property),不是方法
- 节点查找:`tree["name"]`,不是 `tree & "name"`

如需迁移旧代码，加载
[`references/migration-ete3-to-ete4.md`](references/migration-ete3-to-ete4.md)。

## 安装

安装指定版本的基础包:

```bash
uv pip install "ete4==4.4.0"
```

只添加工作流程所需的可视化 extra:

```bash
# SmartView 静态 PNG 截图
uv pip install "ete4[render-sm]==4.4.0"

# 用于 PNG、PDF 和 SVG 的传统 Qt 渲染器
uv pip install "ete4[treeview]==4.4.0"
```

确认当前使用的环境:

```bash
uv run --with "ete4==4.4.0" python -c "import ete4; print(ete4.__version__)"
```

不需要任何凭据。NCBI 和 GTDB 相关工作流会下载公开的分类学数据，可能占用大量磁盘空间；首次更新前请参见
[`references/taxonomy.md`](references/taxonomy.md)。

## 快速开始

```python
from pathlib import Path

from ete4 import Tree

# 文件请使用已打开的文件对象;字符串仅保留给 Newick 文本本身使用。
with Path("tree.nw").open(encoding="utf-8") as handle:
    tree = Tree(handle, parser=1)  # parser 1: 带内部节点名称

print(tree.to_str(props=["name", "dist"], compact=True))
print("Leaves:", list(tree.leaf_names()))

# 搜索并添加注释。
focal = tree["species1"]
focal.add_props(host="human", status="focal")

# 保留选定的叶节点,同时保持两两之间的分支长度距离不变。
tree.prune(
    ["species1", "species2", "species3"],
    preserve_branch_length=True,
)

# 显式地设根并序列化输出。
tree.set_midpoint_outgroup()
tree.write(
    outfile="processed.nw",
    parser=1,
    props=["host", "status"],
)
```

请审慎选择 parser。parser 不匹配是导致 `NewickError`、内部标签丢失，或支持值被误读作名称的最常见原因。参见
[`references/api_reference.md`](references/api_reference.md)。

## 核心工作流程

### 检查并变换一棵树

```python
from ete4 import Tree

tree = Tree("((A:1,B:1)CladeAB:0.4,C:2)Root;", parser=1)

for node in tree.traverse("preorder"):
    label = node.name if node.name is not None else node.id
    print(label, node.level, node.is_leaf, node.dist)

tree["A"].add_prop("group", "case")
tree["B"].add_prop("group", "control")

mrca = tree.common_ancestor("A", "B")
print(mrca.name)

tree.write(
    outfile="annotated.nhx",
    parser=1,
    props=["group"],
    format_root_node=True,
)
```

节点名称不要求唯一。`tree["A"]` 返回第一个匹配项；如果可能存在重复，请使用
`list(tree.search_nodes(name="A"))` 并核实匹配数量。

### 比较两个拓扑结构

```python
from ete4 import Tree

tree_a = Tree("((A,B),(C,D));")
tree_b = Tree("((A,C),(B,D));")

(
    rf,
    max_rf,
    common_leaves,
    edges_a,
    edges_b,
    discarded_a,
    discarded_b,
) = tree_a.robinson_foulds(tree_b)

normalized_rf = rf / max_rf if max_rf else 0.0
print(rf, max_rf, normalized_rf, sorted(common_leaves))
```

RF 比较依赖共享的叶节点标签，需要这些名称有意义，并且最好是唯一的。要明确决定采用有根还是无根比较在科学上更为恰当。

### 检测复制(duplication)与物种形成(speciation)事件

```python
from ete4 import PhyloTree

gene_tree = PhyloTree(
    "((Hsa|g1,Ptr|g1),(Hsa|g2,Mmu|g1));",
    sp_naming_function=lambda name: name.split("|", 1)[0],
)

for event in gene_tree.get_descendant_evol_events(sos_thr=0.0):
    relationship = "speciation/orthology" if event.etype == "S" else "duplication/paralogy"
    print(relationship, sorted(event.in_seqs), sorted(event.out_seqs))
```

物种重叠(species-overlap)判定是基于给定拓扑结构和命名函数所做的推断，并不是直系同源关系(orthology)的独立证据。请显式传入命名函数，并使用一棵有根的、完全二叉分支的基因树。若需要严格的物种树-基因树协调(reconciliation),请使用一棵经过审校的物种树，以及
`gene_tree.reconcile(species_tree)`。

### 查询分类学信息

```python
from ete4 import NCBITaxa

ncbi = NCBITaxa()
names = ["Homo sapiens", "Pan troglodytes", "Mus musculus"]
name_to_taxids = ncbi.get_name_translator(names)

missing = [name for name in names if name not in name_to_taxids]
if missing:
    raise ValueError(f"Names not resolved by NCBI taxonomy: {missing}")

taxids = [name_to_taxids[name][0] for name in names]
taxonomy_tree = ncbi.get_topology(taxids)
print(taxonomy_tree.to_str(props=["sci_name", "rank"]))
```

ETE 4 还提供了 `GTDBTaxa`,用于以基因组为中心的细菌和古菌分类学。不要把 NCBI 的数字 TaxID 和 GTDB 的字符串标识符混用。

### 可视化

交互式 SmartView:

```python
from ete4 import Tree

tree = Tree("((A:1,B:1)90:0.2,C:1);", parser="support")
tree.explore()
```

静态 SmartView 截图:

```python
tree.render_sm("tree.png", w=1200, h=800)
```

`render_sm()` 生成的是 PNG 截图数据；当交付物必须是矢量的 PDF 或 SVG 时，请使用 Qt treeview 渲染器。布局、faces、远程探索以及渲染器选择方面的内容，请加载
[`references/visualization.md`](references/visualization.md)。

## 内置脚本

从本技能所在目录运行。以下命令都通过 `uv run --with` 使用一个版本固定的、隔离的 ETE 4 运行时。

### 树操作

```bash
uv run --with "ete4==4.4.0" python scripts/tree_operations.py \
  stats tree.nw --parser 1
uv run --with "ete4==4.4.0" python scripts/tree_operations.py \
  ascii tree.nw --parser 1 --props name,dist
uv run --with "ete4==4.4.0" python scripts/tree_operations.py \
  convert tree.nw output.nw \
  --input-parser 1 --output-parser 1
uv run --with "ete4==4.4.0" python scripts/tree_operations.py \
  reroot tree.nw rooted.nw \
  --parser 1 --midpoint
uv run --with "ete4==4.4.0" python scripts/tree_operations.py \
  prune tree.nw pruned.nw \
  --parser 1 --keep species1 species2 species3
uv run --with "ete4==4.4.0" python scripts/tree_operations.py \
  compare tree_a.nw tree_b.nw
```

若要每行一个类群(taxon),使用 `--keep-file taxa.txt` 代替 `--keep ...`。
该脚本会拒绝处理有歧义或缺失的指定名称，而不是悄悄生成一棵不完整的树。

### 可视化

```bash
# 交互式 SmartView
uv run --with "ete4==4.4.0" python scripts/quick_visualize.py \
  tree.nw --parser 1

# SmartView PNG(需要 ete4[render-sm])
uv run --with "ete4[render-sm]==4.4.0" python scripts/quick_visualize.py \
  tree.nw tree.png \
  --parser support --mode circular --show-support --color-by-support

# 通过 Qt treeview 输出矢量图(需要 ete4[treeview])
uv run --with "ete4[treeview]==4.4.0" python scripts/quick_visualize.py \
  tree.nw tree.svg \
  --parser 1 --engine treeview --title "Species phylogeny"
```

## 质量与解读检查

在报告结果之前:

1. 确认 parser 保留了预期的内部节点名称、支持值和分支长度。
2. 在基于名称的查找或 RF 比较之前，检查是否存在空的或重复的叶节点名称。
3. 明确说明该树被当作有根树还是无根树处理。
4. 只有当保留的两两距离需要保持不变时，才在修剪时保留分支长度。
5. 把任意的多分支(polytomy)解析当作显示/算法上的便利处理，而不是进化证据。
6. 在可复现的分析中，记录 ETE 版本、parser、设根方法、修剪集合，以及分类学数据库的快照版本。
7. 对大型树优先使用迭代器，对重复的子代内容查询优先使用 `get_cached_content()`。

## 参考资料索引

按需只加载任务所需的参考资料:

- [`references/api_reference.md`](references/api_reference.md) —— ETE 4 核心类、parser、属性、遍历、输入输出、拓扑与比较
- [`references/workflows.md`](references/workflows.md) —— 完整的分析模式、校验、协调(reconciliation)、批处理与大型树处理
- [`references/visualization.md`](references/visualization.md) —— SmartView、布局/faces、PNG 截图与 Qt 矢量渲染
- [`references/taxonomy.md`](references/taxonomy.md) —— NCBI 与 GTDB 设置、转换、拓扑、注释与可复现性
- [`references/migration-ete3-to-ete4.md`](references/migration-ete3-to-ete4.md)
  —— 破坏性 API 变更与迁移清单

## 权威上游来源

- 文档:https://etetoolkit.github.io/ete/
- ETE 3 到 ETE 4 迁移指南:https://etetoolkit.github.io/ete/3to4.html
- 发行版本:https://github.com/etetoolkit/ete/releases
- PyPI:https://pypi.org/project/ete4/
- 源码:https://github.com/etetoolkit/ete
- 可视化图库:https://github.com/etetoolkit/ete-gallery
