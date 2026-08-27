# DiffDock：基于扩散模型的分子对接

## 概述

DiffDock 是一款基于扩散模型的深度学习分子对接工具，用于预测小分子配体与蛋白质靶点的三维结合姿态（binding pose）。它代表了计算对接领域的最先进水平，对基于结构的药物发现和化学生物学至关重要。

**核心能力**：
- 利用深度学习高精度预测配体结合姿态
- 支持蛋白质结构（PDB 文件）或序列（通过 ESMFold）
- 处理单个复合物或批量虚拟筛选活动
- 生成置信度分数以评估预测的可靠性
- 处理多种配体输入格式（SMILES、SDF、MOL2）

**关键区别**： DiffDock 预测的是**结合姿态**（三维结构）和**置信度（**预测确定性**），不是**结合亲和力（ΔG、Kd）。若需评估亲和力，应始终结合打分函数（GNINA、MM/GBSA）一起使用。

## 何时使用此技能

在以下情况应使用此技能：

- "对接这个配体到蛋白质上" 或 "预测结合姿态"
- "运行分子对接" 或 "执行蛋白质-配体对接"
- "虚拟筛选" 或 "筛选化合物库"
- "这个分子结合在哪里？" 或 "预测结合位点"
- 基于结构的药物设计或先导化合物优化任务
- 涉及 PDB 文件 + SMILES 字符串或配体结构的任务
- 多个蛋白质-配体对的批量对接

## 安装与环境搭建

### 检查环境状态

在进行 DiffDock 任务之前，请先验证环境搭建情况：

```bash
# Use the provided setup checker
python scripts/setup_check.py
```

此脚本会验证 Python 版本、带 CUDA 的 PyTorch、PyTorch Geometric、RDKit、ESM 以及其他依赖项。

### 安装选项

**选项 1：Conda（推荐）**
```bash
git clone https://github.com/gcorso/DiffDock.git
cd DiffDock
conda env create --file environment.yml
conda activate diffdock
```

**选项 2：Docker**
```bash
docker pull rbgcsail/diffdock
docker run -it --gpus all --entrypoint /bin/bash rbgcsail/diffdock
micromamba activate diffdock
```

**重要说明**：
- 强烈建议使用 GPU（相比 CPU 可提速 10-100 倍）
- 首次运行会预先计算 SO(2)/SO(3) 查找表（约需 2-5 分钟）
- 若模型检查点（约 500MB）尚不存在，会自动下载
- 当前上游发行版本是 DiffDock v1.1.3；DiffDock-L 是 `default_inference_args.yaml` 中默认使用的模型系列

## 核心工作流

### 工作流 1：单个蛋白质-配体对接

**使用场景**： 将一个配体对接到一个蛋白质靶点上

**输入要求**：
- 蛋白质：PDB 文件 或 氨基酸序列
- 配体：SMILES 字符串 或 结构文件（SDF/MOL2）

**命令**：
```bash
python -m inference \
  --config default_inference_args.yaml \
  --protein_path protein.pdb \
  --ligand_description "CC(=O)Oc1ccccc1C(=O)O" \
  --out_dir results/single_docking/
```

**替代方案（蛋白质序列）**：
```bash
python -m inference \
  --config default_inference_args.yaml \
  --protein_sequence "MSKGEELFTGVVPILVELDGDVNGHKF..." \
  --ligand_description ligand.sdf \
  --out_dir results/sequence_docking/
```

**输出结构**：
```
results/single_docking/
└── complex_0/
    ├── rank1.sdf                    # Convenience copy of top-ranked pose
    ├── rank1_confidence0.87.sdf     # Top-ranked pose with confidence in filename
    ├── rank2_confidence0.42.sdf     # Second-ranked pose
    ├── ...
    └── rank10_confidence-1.23.sdf   # 10th pose (default: 10 samples)
```

当前 `inference.py` 为单复合物运行注册了 `--ligand_description` 参数。部分上游 README 文本中仍写作 `--ligand`；除非你本地检出的代码明确支持 `--ligand` 别名，否则请使用 `--ligand_description`。

### 工作流 2：批量处理多个复合物

**使用场景**： 将多个配体对接到蛋白质上，或进行虚拟筛选活动

**步骤 1：准备批量 CSV**

使用提供的脚本创建或验证批量输入：

```bash
# Create template
python scripts/prepare_batch_csv.py --create --output batch_input.csv

# Validate existing CSV
python scripts/prepare_batch_csv.py my_input.csv --validate
```

**CSV 格式**：
```csv
complex_name,protein_path,ligand_description,protein_sequence
complex1,protein1.pdb,CC(=O)Oc1ccccc1C(=O)O,
complex2,,COc1ccc(C#N)cc1,MSKGEELFT...
complex3,protein3.pdb,ligand3.sdf,
```

**必需列**：
- `complex_name`：唯一标识符
- `protein_path`：PDB 文件路径（若使用序列则留空）
- `ligand_description`：SMILES 字符串或配体文件路径
- `protein_sequence`：氨基酸序列（若使用 PDB 则留空）

**步骤 2：运行批量对接**

```bash
python -m inference \
  --config default_inference_args.yaml \
  --protein_ligand_csv batch_input.csv \
  --out_dir results/batch/ \
  --batch_size 10
```

**用于大规模虚拟筛选（>100 个化合物）**：

预先计算蛋白质嵌入以加快处理速度：
```bash
# Pre-compute embeddings
python datasets/esm_embedding_preparation.py \
  --protein_ligand_csv screening_input.csv \
  --out_file protein_embeddings.pt

# Run with pre-computed embeddings
python -m inference \
  --config default_inference_args.yaml \
  --protein_ligand_csv screening_input.csv \
  --esm_embeddings_path protein_embeddings.pt \
  --out_dir results/screening/
```

### 工作流 3：分析结果

对接完成后，分析置信度分数并对预测结果进行排序：

```bash
# Analyze all results
python scripts/analyze_results.py results/batch/

# Show top 5 per complex
python scripts/analyze_results.py results/batch/ --top 5

# Filter by confidence threshold
python scripts/analyze_results.py results/batch/ --threshold 0.0

# Export to CSV
python scripts/analyze_results.py results/batch/ --export summary.csv

# Show top 20 predictions across all complexes
python scripts/analyze_results.py results/batch/ --best 20
```

该分析脚本会：
- 解析所有预测结果中的置信度分数
- 将结果分类为高（>0）、中等（-1.5 到 0）或低（<-1.5）
- 在单个复合物内部及跨复合物之间对预测结果排序
- 生成统计摘要
- 将结果导出为 CSV 以供下游分析使用

## 置信度分数解读

**理解分数**：

| 分数区间 | 置信度等级 | 解读 |
|------------|------------------|----------------|
| **> 0** | 高 | 预测结果较强，可能准确 |
| **-1.5 到 0** | 中等 | 合理的预测结果，需仔细验证 |
| **< -1.5** | 低 | 不确定的预测结果，需要验证 |

**关键说明**：
1. **置信度 ≠ 亲和力**：高置信度意味着模型对结构的确定性，**不**意味着较强的结合力
2. **需结合上下文考量**：请针对以下情况调整预期：
   - 较大配体（>500 Da）：预计置信度较低
   - 多条蛋白质链：可能降低置信度
   - 新型蛋白质家族：可能表现欠佳
3. **多个样本**：应查看排名前 3-5 的预测结果，寻找共识（consensus）

**详细指南**： 使用 Read 工具阅读 `references/confidence_and_limitations.md`

## 参数定制

### 使用自定义配置

针对特定使用场景创建自定义配置：

```bash
# Copy template
cp assets/custom_inference_config.yaml my_config.yaml

# Edit parameters (see template for presets)
# Then run with custom config
python -m inference \
  --config my_config.yaml \
  --protein_ligand_csv input.csv \
  --out_dir results/
```

### 需调整的关键参数

**采样密度**：
- `samples_per_complex: 10` → 对于较难的情况可提高到 20-40
- 更多样本 = 覆盖更全面，但运行时间更长

**推理步数**：
- `inference_steps: 20` → 可提高到 25-30 以获得更高精度
- 更多步数 = 质量可能更好，但速度更慢

**温度参数（控制多样性）**：
- `temp_sampling_tor: 7.04` → 对于柔性配体可提高该值（8-10）
- `temp_sampling_tor: 7.04` → 对于刚性配体可降低该值（5-6）
- 温度越高 = 姿态越多样

**模板中可用的预设**：
1. 高精度：更多样本 + 更多步数，更低温度
2. 快速筛选：更少样本，速度更快
3. 柔性配体：提高扭转温度
4. 刚性配体：降低扭转温度

**完整参数参考**： 使用 Read 工具阅读 `references/parameters_reference.md`

## 进阶技巧

### 集成对接（蛋白质柔性）

对于已知具有柔性的蛋白质，可对接到多个构象上：

```python
# Create ensemble CSV
import pandas as pd

conformations = ["conf1.pdb", "conf2.pdb", "conf3.pdb"]
ligand = "CC(=O)Oc1ccccc1C(=O)O"

data = {
    "complex_name": [f"ensemble_{i}" for i in range(len(conformations))],
    "protein_path": conformations,
    "ligand_description": [ligand] * len(conformations),
    "protein_sequence": [""] * len(conformations)
}

pd.DataFrame(data).to_csv("ensemble_input.csv", index=False)
```

以更高的采样量运行对接：
```bash
python -m inference \
  --config default_inference_args.yaml \
  --protein_ligand_csv ensemble_input.csv \
  --samples_per_complex 20 \
  --out_dir results/ensemble/
```

### 与打分函数的集成

DiffDock 生成姿态；若需评估亲和力，应结合其他工具使用：

**GNINA（快速神经网络打分）**：
```bash
for pose in results/single_docking/complex_0/*confidence*.sdf; do
    gnina -r protein.pdb -l "$pose" --score_only
done
```

**MM/GBSA（更精确，但更慢）**：
能量最小化后使用 AmberTools 的 MMPBSA.py 或 gmx_MMPBSA

**自由能计算（最精确）**：
使用 OpenMM + OpenFE 或 GROMACS 进行 FEP/TI 计算

**推荐工作流**：
1. DiffDock → 生成带置信度分数的姿态
2. 目视检查 → 检验结构合理性
3. GNINA 或 MM/GBSA → 按亲和力重新打分并排序
4. 实验验证 → 生化实验

## 局限性与适用范围

**DiffDock 的设计适用场景**：
- 小分子配体（通常 100-1000 Da）
- 类药有机化合物
- 小型肽段（<20 个残基）
- 单链或多链蛋白质

**DiffDock 不适用于**：
- 大型生物大分子（蛋白质-蛋白质对接）→ 使用 DiffDock-PP 或 AlphaFold-Multimer
- 大型肽段（>20 个残基）→ 使用其他替代方法
- 共价对接 → 使用专门的共价对接工具
- 结合亲和力预测 → 需结合打分函数使用
- 膜蛋白 → 未经专门训练，请谨慎使用

**完整局限性说明**： 使用 Read 工具阅读 `references/confidence_and_limitations.md`

## 故障排查

### 常见问题

**问题：所有预测结果的置信度分数都很低**
- 原因：配体过大/不常见、结合位点不明确、蛋白质柔性
- 解决方案：提高 `samples_per_complex`（20-40）、尝试集成对接、验证蛋白质结构

**问题：内存不足错误**
- 原因：GPU 显存不足以支撑该批量大小
- 解决方案：减小 `--batch_size 2`，或一次处理更少的复合物

**问题：性能缓慢**
- 原因：在 CPU 而非 GPU 上运行
- 解决方案：用 `python -c "import torch; print(torch.cuda.is_available())"` 验证 CUDA，使用 GPU

**问题：结合姿态不合理**
- 原因：蛋白质准备不当、配体过大、结合位点错误
- 解决方案：检查蛋白质是否缺失残基、移除远处的水分子、考虑指定结合位点

**问题："Module not found" 错误**
- 原因：缺少依赖项或环境错误
- 解决方案：运行 `python scripts/setup_check.py` 进行诊断

### 性能优化

**获得最佳结果的方法**：
1. 使用 GPU（实际使用中必不可少）
2. 对重复使用的蛋白质预先计算 ESM 嵌入
3. 将多个复合物一起批量处理
4. 先使用默认参数，再根据需要调整
5. 验证蛋白质结构（解决残基缺失问题）
6. 对配体使用规范化（canonical）SMILES

## 图形用户界面

如需交互式使用，可启动 Web 界面：

```bash
python app/main.py
# Navigate to http://localhost:7860
```

或使用无需安装的在线演示：
- https://huggingface.co/spaces/reginabarzilaygroup/DiffDock-Web

## 资源

### 辅助脚本（`scripts/`）

**`prepare_batch_csv.py`**：创建和验证批量输入 CSV 文件
- 创建带示例条目的模板
- 验证文件路径和 SMILES 字符串
- 检查必需列和格式问题

**`analyze_results.py`**：分析置信度分数并对预测结果排序
- 解析单次或批量运行的结果
- 生成统计摘要
- 导出为 CSV 以供下游分析
- 识别跨复合物的最佳预测结果

**`setup_check.py`**：验证 DiffDock 环境搭建情况
- 检查 Python 版本和依赖项
- 验证 PyTorch 和 CUDA 可用性
- 测试 RDKit 和 PyTorch Geometric 的安装情况
- 如有需要提供安装说明

### 参考文档（`references/`）

**`parameters_reference.md`**：完整参数文档
- 所有命令行选项和配置参数
- 默认值和可接受范围
- 用于控制多样性的温度参数
- 模型检查点位置和版本标志

在用户需要以下内容时阅读此文件：
- 详细的参数说明
- 针对特定系统的调优指导
- 其他采样策略

**`confidence_and_limitations.md`**：置信度分数解读与工具局限性
- 详细的置信度分数解读
- 何时可以信任预测结果
- DiffDock 的适用范围与局限性
- 与互补工具的集成
- 预测质量的故障排查

在用户需要以下内容时阅读此文件：
- 帮助解读置信度分数
- 了解何时**不应**使用 DiffDock
- 与其他工具结合使用的指导
- 验证策略

**`workflows_examples.md`**：全面的工作流示例
- 详细的安装说明
- 所有工作流的分步示例
- 进阶集成模式
- 常见问题排查
- 最佳实践与优化技巧

在用户需要以下内容时阅读此文件：
- 带代码的完整工作流示例
- 与 GNINA、OpenMM 或其他工具的集成
- 虚拟筛选工作流
- 集成对接流程

### 资产（`assets/`）

**`batch_template.csv`**：批量处理模板
- 预先格式化好的、含必需列的 CSV
- 展示不同输入类型的示例条目
- 可直接用实际数据定制

**`custom_inference_config.yaml`**：配置模板
- 带全部参数注释的 YAML
- 针对常见使用场景的四种预设配置
- 解释每个参数的详细注释
- 可直接定制和使用

## 最佳实践

1. **务必先验证环境**：在启动大型任务前使用 `setup_check.py`
2. **验证批量 CSV**：使用 `prepare_batch_csv.py` 及早发现错误
3. **从默认参数开始**，再根据系统的具体需求进行调优
4. **生成多个样本**（10-40 个）以获得稳健的预测结果
5. **目视检查**排名靠前的姿态后再进行下游分析
6. **结合打分函数**评估亲和力
7. **使用置信度分数**进行初步排序，而非作为最终决策依据
8. **预先计算嵌入**以用于虚拟筛选活动
9. **记录所用参数**以保证可复现性
10. 尽可能**通过实验验证**结果

## 引用

使用 DiffDock 时，请引用相应的论文：

**DiffDock-L（当前默认模型）**：
```
Corso et al. (2024) "Deep Confident Steps to New Pockets: Strategies for Docking Generalization"
ICLR 2024, arXiv:2402.18396
```

**原始 DiffDock**：
```
Corso et al. (2023) "DiffDock: Diffusion Steps, Twists, and Turns for Molecular Docking"
ICLR 2023, arXiv:2210.01776
```

## 附加资源

- **GitHub 仓库**：https://github.com/gcorso/DiffDock
- **在线演示**：https://huggingface.co/spaces/reginabarzilaygroup/DiffDock-Web
- **DiffDock-L 论文**：https://arxiv.org/abs/2402.18396
- **原始论文**：https://arxiv.org/abs/2210.01776
