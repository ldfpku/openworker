# Pymoo - Python 中的多目标优化

## 概述

Pymoo 是一个全面的 Python 优化框架，重点面向多目标问题。它可以使用最先进的算法
（NSGA-II/III、MOEA/D、SPEA2）、基准测试问题（ZDT、DTLZ）、可自定义的遗传算子，
以及多准则决策方法来求解单目标和多目标优化问题。它擅长为具有相互冲突目标的问题
找出权衡解（帕累托前沿，Pareto front）。当前稳定发布版本：**pymoo 0.6.1.6**
（2025 年 11 月）。

## 安装

```bash
uv pip install pymoo
```

如需可复现的环境，请锁定版本号：`uv pip install "pymoo==0.6.1.6"`。

**依赖项**： NumPy（自 0.6.1.3 起兼容 2.x）、SciPy、matplotlib（用于可视化）。
Autograd 是用于基于梯度的功能的可选依赖（自 0.6.1.3 起）。

**文档**： https://pymoo.org/ —— 对 LLM 友好的索引：https://pymoo.org/llms.txt

## 何时使用本技能

在以下情况下应使用本技能：
- 求解具有一个或多个目标的优化问题
- 寻找帕累托最优解并分析权衡取舍
- 实现进化算法（GA、DE、PSO、NSGA-II/III）
- 处理带约束的优化问题
- 在标准测试问题（ZDT、DTLZ、WFG）上对算法进行基准测试
- 自定义遗传算子（交叉、变异、选择）
- 对高维优化结果进行可视化
- 从多个相互竞争的解中做出决策
- 处理二元、离散、连续或混合变量问题

## 核心概念

### 统一接口

Pymoo 对所有优化任务都使用一致的 `minimize()` 函数：

```python
from pymoo.optimize import minimize

result = minimize(
    problem,        # What to optimize
    algorithm,      # How to optimize
    termination,    # When to stop
    seed=1,
    verbose=True
)
```

**结果对象包含**：
- `result.X`：最优解的决策变量
- `result.F`：最优解的目标函数值
- `result.G`：约束违反情况（如果有约束）
- `result.algorithm`：包含历史记录的算法对象

### 问题定义风格

Pymoo 支持三种问题定义风格：

- **`Problem`**：向量化——`_evaluate` 接收一批解（矩阵）
- **`ElementwiseProblem`**：每次调用一个解——推荐用于自定义问题和并行评估
- **`FunctionalProblem`**：将目标和约束定义为独立函数，而无需继承子类

### 问题类型

**单目标**： 一个需要最小化/最大化的目标
**多目标**： 2-3 个相互冲突的目标 → 帕累托前沿
**多多目标（Many-objective）**： 4 个及以上的目标 → 高维帕累托前沿
**带约束**： 目标 + 不等式/等式约束
**混合变量**： 在同一个问题中同时包含连续、整数、二元和分类变量
**动态**： 随时间变化的目标或约束

## 快速上手工作流

在
[references/quick_start_workflows.md](references/quick_start_workflows.md)
中提供了九个可运行的工作流：

| # | 工作流 | 适用场景 |
| --- | --- | --- |
| 1 | 单目标优化 | 一个目标，GA 或 DE |
| 2 | 多目标（2-3 个目标） | NSGA-II 与帕累托前沿 |
| 3 | 多多目标（4 个及以上目标） | NSGA-III 或基于参考方向的方法 |
| 4 | 自定义问题定义 | 继承 `Problem` / `ElementwiseProblem` |
| 5 | 约束处理 | 不等式与等式约束 |
| 6 | 从帕累托前沿中做决策 | 标量化与多准则决策方法（MCDM）选择 |
| 7 | 可视化 | 散点图、平行坐标图（PCP）、雷达图（radviz）以及热力图视图 |
| 8 | 并行评估 | 针对开销较大目标的线程、进程或 Dask |
| 9 | 混合变量优化 | 整数、二元和分类变量 |

## 算法选择指南

### 单目标问题

| 算法 | 最适用于 | 关键特性 |
|-----------|----------|--------------|
| **GA** | 通用场景 | 灵活，可定制算子 |
| **DE** | 连续优化 | 良好的全局搜索能力 |
| **PSO** | 平滑的问题空间 | 收敛速度快 |
| **CMA-ES** | 困难/含噪声的问题 | 自适应 |

### 多目标问题（2-3 个目标）

| 算法 | 最适用于 | 关键特性 |
|-----------|----------|--------------|
| **NSGA-II** | 标准基准算法 | 快速、可靠、经过充分验证 |
| **SPEA2** | 基于存档的多目标优化 | 基于强度的适应度、外部存档 |
| **R-NSGA-II** | 偏好区域 | 参考点引导 |
| **MOEA/D** | 可分解的问题 | 标量化方法 |

### 多多目标问题（4 个及以上目标）

| 算法 | 最适用于 | 关键特性 |
|-----------|----------|--------------|
| **NSGA-III** | 4-15 个目标 | 基于参考方向 |
| **RVEA** | 自适应搜索 | 参考向量演化 |
| **AGE-MOEA** | 复杂的问题空间 | 自适应几何结构 |

### 带约束的问题

| 方法 | 算法 | 何时使用 |
|----------|-----------|--------------|
| 可行性优先 | 任意算法 | 可行域较大时 |
| 专用方法 | SRES、ISRES | 约束较为繁重时 |
| 惩罚函数 | GA + 惩罚 | 算法兼容性场景 |

**参见**： `references/algorithms.md` 获取全面的算法参考资料

## 基准测试问题

### 快速获取问题：
```python
from pymoo.problems import get_problem

# Single-objective
problem = get_problem("rastrigin", n_var=10)
problem = get_problem("rosenbrock", n_var=10)

# Multi-objective
problem = get_problem("zdt1")        # Convex front
problem = get_problem("zdt2")        # Non-convex front
problem = get_problem("zdt3")        # Disconnected front

# Many-objective
problem = get_problem("dtlz2", n_obj=5, n_var=12)
problem = get_problem("dtlz7", n_obj=4)
```

**参见**： `references/problems.md` 获取完整的测试问题参考资料

## 遗传算子自定义

### 标准算子配置：
```python
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM

algorithm = GA(
    pop_size=100,
    crossover=SBX(prob=0.9, eta=15),
    mutation=PM(eta=20),
    eliminate_duplicates=True
)
```

### 按变量类型选择算子：

**连续变量**：
- 交叉：SBX（模拟二进制交叉，Simulated Binary Crossover）
- 变异：PM（多项式变异，Polynomial Mutation）

**二元变量**：
- 交叉：TwoPointCrossover、UniformCrossover
- 变异：BitflipMutation

**排列问题（TSP、调度）**：
- 交叉：OrderCrossover（OX）
- 变异：InversionMutation

**参见**： `references/operators.md` 获取全面的算子参考资料

## 性能与故障排查

### 常见问题及解决方法：

**问题：算法不收敛**
- 增大种群规模
- 增加迭代代数
- 检查问题是否为多峰的（尝试不同算法）
- 核实约束条件的表述是否正确

**问题：帕累托前沿分布不佳**
- 对于 NSGA-III：调整参考方向
- 增大种群规模
- 检查重复解的消除机制
- 核实问题的量纲缩放

**问题：可行解太少**
- 使用"约束作为目标"的方法
- 应用修复算子（repair operator）
- 对于受约束的问题尝试 SRES/ISRES
- 检查约束表述方式（应为 g <= 0）

**问题：计算开销过高**
- 减小种群规模
- 减少迭代代数
- 使用更简单的算子
- 通过 `elementwise_runner` 启用并行评估（参见工作流 8）

### 最佳实践：

1. 当量纲差异显著时，对**目标进行归一化**
2. **设置随机种子**以保证可复现性
3. **保存历史记录**以分析收敛情况：`save_history=True`
4. **可视化结果**以理解解的质量
5. 在有真实帕累托前沿可用时，**与之进行比较**
6. **使用合适的终止条件**（代数、评估次数、容差）
7. 针对问题特性**调整算子参数**

## 资源

本技能包含全面的参考文档和可运行的示例：

### references/
供深入理解的详细文档：

- **algorithms.md**：完整的算法参考资料，含参数、用法和选择指南
- **problems.md**：基准测试问题（ZDT、DTLZ、WFG）及其特性
- **operators.md**：遗传算子（采样、选择、交叉、变异）及其配置方式
- **visualization.md**：所有可视化类型，含示例及选择指南
- **constraints_mcdm.md**：约束处理技术及多准则决策方法
- **parallelization.md**：使用 StarmapParallelization 和 JoblibParallelization 进行并行评估

**参考资料的搜索模式**：
- 算法细节：`grep -r "NSGA-II\|NSGA-III\|MOEA/D" references/`
- 约束方法：`grep -r "Feasibility First\|Penalty\|Repair" references/`
- 可视化类型：`grep -r "Scatter\|PCP\|Petal" references/`

### scripts/
展示常见工作流的可运行示例：

- **single_objective_example.py**：使用 GA 的基础单目标优化
- **multi_objective_example.py**：使用 NSGA-II 的多目标优化及可视化
- **many_objective_example.py**：使用 NSGA-III 和参考方向的多多目标优化
- **custom_problem_example.py**：定义自定义问题（含约束与无约束）
- **decision_making_example.py**：在不同偏好下的多准则决策

**运行示例**：
```bash
python3 scripts/single_objective_example.py
python3 scripts/multi_objective_example.py
python3 scripts/many_objective_example.py
python3 scripts/custom_problem_example.py
python3 scripts/decision_making_example.py
```

## 补充说明

**常见模式**：
- 对自定义问题使用 `ElementwiseProblem`（或对基于函数的定义使用 `FunctionalProblem`）
- 对混合变量问题使用带类型化变量的 `vars` 字典
- 约束表述为 `g(x) <= 0` 和 `h(x) = 0`
- NSGA-III 需要参考方向
- 在做多准则决策（MCDM）之前先对目标进行归一化
- 使用合适的终止条件：`('n_gen', N)` 或 `get_termination("f_tol", tol=0.001)`
