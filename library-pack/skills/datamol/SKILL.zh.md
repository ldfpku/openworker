# Datamol 化学信息学技能

## 概述

Datamol 是一个 Python 库，为分子化学信息学提供了轻量级、Pythonic 的 RDKit 抽象层。它通过合理的默认值、高效的并行化，以及现代化的 I/O 能力，简化了复杂的分子操作。所有分子对象都是原生的 `rdkit.Chem.Mol` 实例，确保与 RDKit 生态系统完全兼容。

**版本说明**：示例针对 **datamol 0.12.x**（PyPI 稳定版：**0.12.5**，2024 年 6 月）。自 0.10.0 起，模块默认采用懒加载（设置 `DATAMOL_DISABLE_LAZY_LOADING=1` 可禁用）。自 0.12.2 起，RDKit 成为 datamol 的直接 PyPI 依赖。指纹计算使用 RDKit 的 `rdFingerprintGenerator` API（0.12.5+）。

**主要能力**：
- 分子格式转换（SMILES、SELFIES、InChI）
- 结构标准化与净化
- 分子描述符与指纹
- 三维构象生成与分析
- 聚类与多样性选择
- 骨架与片段分析
- 化学反应应用
- 可视化与对齐
- 带并行化的批处理
- 通过 fsspec 实现的云存储支持

## 安装与设置

指导用户安装 datamol：

```bash
uv pip install datamol
```

RDKit 会随 datamol 一起自动安装。对于远程文件路径（S3、GCS、HTTP），请安装对应的 fsspec 后端：

```bash
uv pip install s3fs   # AWS S3
uv pip install gcsfs  # Google Cloud Storage
```

**导入约定**：
```python
import datamol as dm
```

## 核心工作流

十个工作流领域，各自附带示例代码，记录在
[references/core_workflows.md](references/core_workflows.md) 中：

| # | 领域 | 涵盖内容 |
| --- | --- | --- |
| 1 | 基础分子处理 | `to_mol`、批量转换、错误处理、规范与同分异构 SMILES、净化与完整标准化 |
| 2 | 文件读写 | SDF、SMILES、CSV、带渲染结构的 Excel、通用读写器，以及云端或 HTTPS 路径 |
| 3 | 描述符与属性 | 标准描述符集合、并行计算、芳香性、立体化学、柔性以及过滤 |
| 4 | 指纹与相似度 | ECFP4 及其他类型、成对与跨集合距离、最近邻查找（Tanimoto 距离 = 1 − 相似度） |
| 5 | 聚类与多样性 | 相似度聚类、多样化子集挑选，以及聚类中心 |
| 6 | 骨架分析 | Bemis-Murcko 骨架、分组与计数，以及按骨架不重叠的训练/测试划分 |
| 7 | 片段化 | 分子片段化、在库中查找共有片段，以及基于片段的评分 |
| 8 | 三维构象 | 生成、访问、RMSD 聚类、代表性选择，以及 SASA |
| 9 | 可视化 | 网格、文件、出版级 SVG、子结构对齐、原子与键高亮、构象展示 |
| 10 | 化学反应 | 反应 SMARTS，应用于单个分子或整个库 |

三条端到端流水线——加载/过滤/分析、按骨架系列的 SAR、以及虚拟
筛选——记录在 [references/workflow_patterns.md](references/workflow_patterns.md) 中。

## 并行化

Datamol 为许多操作内置了并行化。使用 `n_jobs` 参数：
- `n_jobs=1`：顺序执行（不并行）
- `n_jobs=-1`：使用所有可用的 CPU 核心
- `n_jobs=4`：使用 4 个核心

**支持并行化的函数**：
- `dm.read_sdf(..., n_jobs=-1)`
- `dm.descriptors.batch_compute_many_descriptors(..., n_jobs=-1)`
- `dm.cluster_mols(..., n_jobs=-1)`
- `dm.pdist(..., n_jobs=-1)`
- `dm.conformers.sasa(..., n_jobs=-1)`

**进度条**：许多批处理操作支持 `progress=True` 参数。

## 参考文档

如需详细的 API 文档，请查阅以下参考文件：

- **`references/core_api.md`**：核心命名空间函数（转换、标准化、指纹、聚类）
- **`references/io_module.md`**：文件 I/O 操作（读写 SDF、CSV、Excel、远程文件）
- **`references/conformers_module.md`**：三维构象生成、聚类、SASA 计算
- **`references/descriptors_viz.md`**：分子描述符与可视化函数
- **`references/fragments_scaffolds.md`**：骨架提取、BRICS/RECAP 片段化
- **`references/reactions_data.md`**：化学反应与示例数据集

## 最佳实践

1. **始终标准化来自外部来源的分子**：
   ```python
   mol = dm.standardize_mol(mol, disconnect_metals=True, normalize=True, reionize=True)
   ```

2. **在分子解析后检查 None 值**：
   ```python
   mol = dm.to_mol(smiles)
   if mol is None:
       # Handle invalid SMILES
   ```

3. **对大型数据集使用并行处理**：
   ```python
   result = dm.operation(..., n_jobs=-1, progress=True)
   ```

4. **仅在需要时使用云端 I/O**——确认远程写入路径；按需安装 `s3fs`/`gcsfs`：
   ```python
   df = dm.read_sdf("s3://bucket/compounds.sdf")
   ```

5. **为相似度计算选用合适的指纹**：
   - ECFP（Morgan）：通用型，结构相似度
   - MACCS：速度快，特征空间更小
   - 原子对：考虑原子对及其距离

6. **考虑规模限制**：
   - Butina 聚类：约 1,000 个分子（完整距离矩阵）
   - 对于更大的数据集：使用多样性选择或层次化方法

7. **面向机器学习的骨架划分**：确保按骨架正确划分训练集与测试集

8. **对齐分子**：在展示 SAR 系列时进行对齐

## 错误处理

```python
# Safe molecule creation
def safe_to_mol(smiles):
    try:
        mol = dm.to_mol(smiles)
        if mol is not None:
            mol = dm.standardize_mol(mol)
        return mol
    except Exception as e:
        print(f"Failed to process {smiles}: {e}")
        return None

# Safe batch processing
valid_mols = []
for smiles in smiles_list:
    mol = safe_to_mol(smiles)
    if mol is not None:
        valid_mols.append(mol)
```

## 与机器学习集成

Datamol 自带 `scipy` 与 `scikit-learn` 作为依赖。将它们作为普通的 PyPI 包导入即可——它们并非本技能自带的脚本。

```python
import numpy as np

# Feature generation
X = np.array([dm.to_fp(mol) for mol in mols])

# Or descriptors
desc_df = dm.descriptors.batch_compute_many_descriptors(mols, n_jobs=-1)
X = desc_df.values

# Train model (scikit-learn PyPI package)
from sklearn.ensemble import RandomForestRegressor  # third-party library
model = RandomForestRegressor()
model.fit(X, y_target)

# Predict
predictions = model.predict(X_test)
```

## 故障排查

**问题**：分子解析失败
- **解决方法**：先使用 `dm.standardize_smiles()`，或尝试 `dm.fix_mol()`

**问题**：聚类时出现内存错误
- **解决方法**：对大规模集合使用 `dm.pick_diverse()` 代替完整聚类

**问题**：构象生成缓慢
- **解决方法**：减少 `n_confs`，或增大 `rms_cutoff` 以生成更少的构象

**问题**：远程文件访问失败
- **解决方法**：安装匹配的 fsspec 后端（`uv pip install s3fs` 或 `gcsfs`），并确认只设置了该后端所需的提供方凭据（参见上文的远程文件支持）

## 更多资源

- **Datamol 文档**：https://docs.datamol.io/
- **RDKit 文档**：https://www.rdkit.org/docs/
- **GitHub 仓库**：https://github.com/datamol-io/datamol
