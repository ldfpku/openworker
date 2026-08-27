# Phylogenetics（系统发育分析）

## 概述

系统发育分析（Phylogenetic analysis）通过推断生物序列（基因、蛋白质、基因组）的分支演化模式，重建其进化历史。本技能涵盖以下标准流程：

1. **MAFFT** — 多序列比对（Multiple sequence alignment）
2. **IQ-TREE 2** — 带模型选择的最大似然（maximum likelihood）建树
3. **FastTree** — 快速近似最大似然法（适用于大规模数据集）
4. **ETE3** — 用于树操作与可视化的 Python 库

**安装**：
```bash
# Conda（推荐用于命令行工具）
conda install -c bioconda mafft iqtree fasttree
uv pip install ete3

# ete3 的 TreeStyle/NodeStyle 渲染依赖其 Qt 后端，因此图像输出
# 还需要 PyQt5；树的解析与统计功能则不需要它
uv pip install PyQt5
```

## 何时使用本技能

在以下情况使用系统发育分析：

- **进化关系**：哪种生物/基因与我的序列亲缘关系最近？
- **病毒系统动力学（phylodynamics）**：追溯疫情传播路径，估计传播时间
- **蛋白质家族分析**：推断某个基因家族内部的进化关系
- **水平基因转移（horizontal gene transfer）检测**：识别物种树与基因树不一致的基因
- **祖先序列重建**：推断祖先蛋白质序列
- **分子钟（molecular clock）分析**：利用时序采样估计分歧时间
- **GWAS 的配套分析**：将变异放入进化背景中考察（例如 SARS-CoV-2 变异株）
- **微生物学**：基于 16S rRNA 的物种系统发育或核心基因组系统发育

## 标准工作流程

### 1. 使用 MAFFT 进行多序列比对

```python
import subprocess
import os

def run_mafft(input_fasta: str, output_fasta: str, method: str = "auto",
               n_threads: int = 4) -> str:
    """
    Align sequences with MAFFT.

    Args:
        input_fasta: Path to unaligned FASTA file
        output_fasta: Path for aligned output
        method: 'auto' (auto-select), 'einsi' (accurate), 'linsi' (accurate, slow),
                'fftnsi' (medium), 'fftns' (fast), 'retree2' (fast)
        n_threads: Number of CPU threads

    Returns:
        Path to aligned FASTA file
    """
    methods = {
        "auto": ["mafft", "--auto"],
        "einsi": ["mafft", "--genafpair", "--maxiterate", "1000"],
        "linsi": ["mafft", "--localpair", "--maxiterate", "1000"],
        "fftnsi": ["mafft", "--fftnsi"],
        "fftns": ["mafft", "--fftns"],
        "retree2": ["mafft", "--retree", "2"],
    }

    cmd = methods.get(method, methods["auto"])
    cmd += ["--thread", str(n_threads), "--inputorder", input_fasta]

    with open(output_fasta, 'w') as out:
        result = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"MAFFT failed:\n{result.stderr}")

    # Count aligned sequences
    with open(output_fasta) as f:
        n_seqs = sum(1 for line in f if line.startswith('>'))
    print(f"MAFFT: aligned {n_seqs} sequences → {output_fasta}")

    return output_fasta

# MAFFT method selection guide:
# Few sequences (<200), accurate: linsi or einsi
# Many sequences (<1000), moderate: fftnsi
# Large datasets (>1000): fftns or auto
# Ultra-fast (>10000): mafft --retree 1
```

### 2. 修剪比对结果（可选，但推荐）

```python
def trim_alignment_trimal(aligned_fasta: str, output_fasta: str,
                            method: str = "automated1") -> str:
    """
    Trim poorly aligned columns with TrimAl.

    Methods:
    - 'automated1': Automatic heuristic (recommended)
    - 'gappyout': Remove gappy columns
    - 'strict': Strict gap threshold
    """
    cmd = ["trimal", f"-{method}", "-in", aligned_fasta, "-out", output_fasta, "-fasta"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"TrimAl warning: {result.stderr}")
        # Fall back to using the untrimmed alignment
        import shutil
        shutil.copy(aligned_fasta, output_fasta)
    return output_fasta
```

### 3. IQ-TREE 2 —— 最大似然树

```python
def run_iqtree(aligned_fasta: str, output_prefix: str,
                model: str = "TEST", bootstrap: int = 1000,
                n_threads: int = 4, extra_args: list = None) -> dict:
    """
    Build a maximum likelihood tree with IQ-TREE 2.

    Args:
        aligned_fasta: Aligned FASTA file
        output_prefix: Prefix for output files
        model: 'TEST' for automatic model selection, or specify (e.g., 'GTR+G' for DNA,
               'LG+G4' for proteins, 'JTT+G' for proteins)
        bootstrap: Number of ultrafast bootstrap replicates (1000 recommended)
        n_threads: Number of threads ('AUTO' to auto-detect)
        extra_args: Additional IQ-TREE arguments

    Returns:
        Dict with paths to output files
    """
    cmd = [
        "iqtree2",
        "-s", aligned_fasta,
        "--prefix", output_prefix,
        "-m", model,
        "-B", str(bootstrap),   # Ultrafast bootstrap
        "-T", str(n_threads),
        "--redo"                # Overwrite existing results
    ]

    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"IQ-TREE failed:\n{result.stderr}")

    # Print model selection result
    log_file = f"{output_prefix}.log"
    if os.path.exists(log_file):
        with open(log_file) as f:
            for line in f:
                if "Best-fit model" in line:
                    print(f"IQ-TREE: {line.strip()}")

    output_files = {
        "tree": f"{output_prefix}.treefile",
        "log": f"{output_prefix}.log",
        "iqtree": f"{output_prefix}.iqtree",  # Full report
        "model": f"{output_prefix}.model.gz",
    }

    print(f"IQ-TREE: Tree saved to {output_files['tree']}")
    return output_files

# IQ-TREE model selection guide:
# DNA:     TEST → GTR+G, HKY+G, TrN+G
# Protein: TEST → LG+G4, WAG+G, JTT+G, Q.pfam+G
# Codon:   TEST → MG+F3X4

# For temporal (molecular clock) analysis, add:
# extra_args = ["--date", "dates.txt", "--clock-test", "--date-CI", "95"]
```

### 4. FastTree —— 快速近似最大似然法

适用于 IQ-TREE 处理起来过慢的大规模数据集（超过 1000 条序列）：

```python
def run_fasttree(aligned_fasta: str, output_tree: str,
                  sequence_type: str = "nt", model: str = "gtr",
                  n_threads: int = 4) -> str:
    """
    Build a fast approximate ML tree with FastTree.

    Args:
        sequence_type: 'nt' for nucleotide or 'aa' for amino acid
        model: For nt: 'gtr' (recommended) or 'jc'; for aa: 'lg', 'wag', 'jtt'
    """
    if sequence_type == "nt":
        cmd = ["FastTree", "-nt", "-gtr"]
    else:
        cmd = ["FastTree", f"-{model}"]

    cmd += [aligned_fasta]

    with open(output_tree, 'w') as out:
        result = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FastTree failed:\n{result.stderr}")

    print(f"FastTree: Tree saved to {output_tree}")
    return output_tree
```

### 5. 使用 ETE3 进行树分析与可视化

```python
from ete3 import Tree, TreeStyle, NodeStyle, TextFace, PhyloTree
import matplotlib.pyplot as plt

def load_tree(tree_file: str) -> Tree:
    """Load a Newick tree file."""
    t = Tree(tree_file)
    print(f"Tree: {len(t)} leaves, {len(list(t.traverse()))} nodes")
    return t

def basic_tree_stats(t: Tree) -> dict:
    """Compute basic tree statistics."""
    leaves = t.get_leaves()
    distances = [t.get_distance(l1, l2) for l1 in leaves[:min(50, len(leaves))]
                 for l2 in leaves[:min(50, len(leaves))] if l1 != l2]

    stats = {
        "n_leaves": len(leaves),
        "n_internal_nodes": len(t) - len(leaves),
        "total_branch_length": sum(n.dist for n in t.traverse()),
        "max_leaf_distance": max(distances) if distances else 0,
        "mean_leaf_distance": sum(distances)/len(distances) if distances else 0,
    }
    return stats

def find_mrca(t: Tree, leaf_names: list) -> Tree:
    """Find the most recent common ancestor of a set of leaves."""
    return t.get_common_ancestor(*leaf_names)

def visualize_tree(t: Tree, output_file: str = "tree.png",
                    show_branch_support: bool = True,
                    color_groups: dict = None,
                    width: int = 800) -> None:
    """
    Render phylogenetic tree to image.

    Args:
        t: ETE3 Tree object
        color_groups: Dict mapping leaf_name → color (for coloring taxa)
        show_branch_support: Show bootstrap values
    """
    ts = TreeStyle()
    ts.show_leaf_name = True
    ts.show_branch_support = show_branch_support
    ts.mode = "r"  # 'r' = rectangular, 'c' = circular

    if color_groups:
        for node in t.traverse():
            if node.is_leaf() and node.name in color_groups:
                nstyle = NodeStyle()
                nstyle["fgcolor"] = color_groups[node.name]
                nstyle["size"] = 8
                node.set_style(nstyle)

    t.render(output_file, tree_style=ts, w=width, units="px")
    print(f"Tree saved to: {output_file}")

def midpoint_root(t: Tree) -> Tree:
    """Root tree at midpoint (use when outgroup unknown)."""
    t.set_outgroup(t.get_midpoint_outgroup())
    return t

def prune_tree(t: Tree, keep_leaves: list) -> Tree:
    """Prune tree to keep only specified leaves."""
    t.prune(keep_leaves, preserve_branch_length=True)
    return t
```

### 6. 完整分析脚本

```python
import subprocess, os
from ete3 import Tree

def full_phylogenetic_analysis(
    input_fasta: str,
    output_dir: str = "phylo_results",
    sequence_type: str = "nt",
    n_threads: int = 4,
    bootstrap: int = 1000,
    use_fasttree: bool = False
) -> dict:
    """
    Complete phylogenetic pipeline: align → trim → tree → visualize.

    Args:
        input_fasta: Unaligned FASTA
        sequence_type: 'nt' (nucleotide) or 'aa' (amino acid/protein)
        use_fasttree: Use FastTree instead of IQ-TREE (faster for large datasets)
    """
    os.makedirs(output_dir, exist_ok=True)
    prefix = os.path.join(output_dir, "phylo")

    print("=" * 50)
    print("Step 1: Multiple Sequence Alignment (MAFFT)")
    aligned = run_mafft(input_fasta, f"{prefix}_aligned.fasta",
                         method="auto", n_threads=n_threads)

    print("\nStep 2: Tree Inference")
    if use_fasttree:
        tree_file = run_fasttree(
            aligned, f"{prefix}.tree",
            sequence_type=sequence_type,
            model="gtr" if sequence_type == "nt" else "lg"
        )
    else:
        model = "TEST" if sequence_type == "nt" else "TEST"
        iqtree_files = run_iqtree(
            aligned, prefix,
            model=model,
            bootstrap=bootstrap,
            n_threads=n_threads
        )
        tree_file = iqtree_files["tree"]

    print("\nStep 3: Tree Analysis")
    t = Tree(tree_file)
    t = midpoint_root(t)

    stats = basic_tree_stats(t)
    print(f"Tree statistics: {stats}")

    print("\nStep 4: Visualization")
    visualize_tree(t, f"{prefix}_tree.png", show_branch_support=True)

    # Save rooted tree
    rooted_tree_file = f"{prefix}_rooted.nwk"
    t.write(format=1, outfile=rooted_tree_file)

    results = {
        "aligned_fasta": aligned,
        "tree_file": tree_file,
        "rooted_tree": rooted_tree_file,
        "visualization": f"{prefix}_tree.png",
        "stats": stats
    }

    print("\n" + "=" * 50)
    print("Phylogenetic analysis complete!")
    print(f"Results in: {output_dir}/")
    return results
```

## IQ-TREE 模型指南

### DNA 模型

| 模型 | 说明 | 适用场景 |
|-------|-------------|---------|
| `GTR+G4` | 广义时间可逆模型（General Time Reversible）+ Gamma 分布 | 最灵活的 DNA 模型 |
| `HKY+G4` | Hasegawa-Kishino-Yano 模型 + Gamma 分布 | 双速率模型（常用） |
| `TrN+G4` | Tamura-Nei 模型 | 转换（transition）速率不等 |
| `JC` | Jukes-Cantor 模型 | 最简单；所有速率相等 |

### 蛋白质模型

| 模型 | 说明 | 适用场景 |
|-------|-------------|---------|
| `LG+G4` | Le-Gascuel 模型 + Gamma 分布 | 平均表现最佳的蛋白质模型 |
| `WAG+G4` | Whelan-Goldman 模型 | 广泛使用 |
| `JTT+G4` | Jones-Taylor-Thornton 模型 | 经典模型 |
| `Q.pfam+G4` | 基于 pfam 训练 | 适用于类 Pfam 蛋白质家族 |
| `Q.bird+G4` | 鸟类专用 | 脊椎动物蛋白质 |

**提示**： 使用 `-m TEST` 让 IQ-TREE 自动选择最佳模型。

## 最佳实践

- **比对质量优先**：比对质量差 → 树的结果不可靠；应人工检查比对结果
- **小规模比对（<200 条序列）使用 `linsi`，大规模比对使用 `fftns` 或 `auto`**
- **模型选择**：除非有特定理由，否则始终对 IQ-TREE 使用 `-m TEST`
- **Bootstrap（自助法）**：使用 ≥1000 次超快速 bootstrap（`-B 1000`）来获得分支支持度
- **给树定根（root）**：无根树可能产生误导；应使用外类群（outgroup）或中点法定根
- **超过 5000 条序列时使用 FastTree**：IQ-TREE 会变得很慢；FastTree 快 10–100 倍
- **修剪较长的比对结果**：TrimAl 会去除不可靠的列，从而提高树的准确性
- **在建树之前检查病毒/细菌序列中是否存在重组（recombination）**（`RDP4`、`GARD`）

## 其他资源

- **MAFFT**：https://mafft.cbrc.jp/alignment/software/
- **IQ-TREE 2**：http://www.iqtree.org/ | 教程：https://www.iqtree.org/workshop/molevol2022
- **FastTree**：http://www.microbesonline.org/fasttree/
- **ETE3**：http://etetoolkit.org/
- **FigTree**（图形界面可视化）：https://tree.bio.ed.ac.uk/software/figtree/
- **iTOL**（网页版可视化）：https://itol.embl.de/
- **MUSCLE**（替代比对工具）：https://www.drive5.com/muscle/
- **TrimAl**（比对修剪工具）：https://vicfero.github.io/trimal/
