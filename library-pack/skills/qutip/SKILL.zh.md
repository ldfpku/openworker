# QuTiP 5

## 适用范围

将 QuTiP 用于有限维量子力学、量子光学、Lindblad 动力学、量子轨迹
(trajectories)、弱耦合 Bloch-Redfield 模型，以及专门的 Floquet、HEOM 和
置换不变性(permutational-invariance)方法。它不是一个硬件执行 SDK。电路和
控制相关功能已迁移到独立的 QuTiP 系列软件包中。

本技能针对的是 **QuTiP 5.3.0**,发布于 2026-05-22。QuTiP 5.3 要求
Python 3.11 或更高版本。其必需的依赖库是 NumPy(`>=1.23.2`)、SciPy
(`>=1.9.2`,不包括 `1.16.0` 和 `1.17.0`),以及 `packaging`。

## 可复现的 uv 环境快照

创建一个专用环境，并锁定每一个直接依赖的版本:

```bash
uv venv --python 3.11
uv pip install "qutip==5.3.0"
```

用于绘图:

```bash
uv pip install "qutip[graphics]==5.3.0"
```

可选的 QuTiP 系列软件包各自独立维护版本号:

```bash
uv pip install "qutip-qip==0.4.2"
uv pip install "qutip-qtrl==0.2.0"
uv pip install "qutip-jax==0.1.1"
```

- `qutip-qip` 0.4.2(2026-06-23)是生产/稳定级的电路、门操作，以及带噪声
  器件仿真软件包。应从 `qutip_qip` 导入，而不是 `qutip.qip`。
- `qutip-qtrl` 0.2.0(2026-06-23)提供 GRAPE 和 CRAB **量子最优控制**功能。
  它不是一个轨迹查看器。应从 `qutip_qtrl` 导入，而不是 `qutip.control`;
  PyPI 目前仍将其归类为 pre-alpha 阶段。
- `qutip-jax` 0.1.1(2025-05-29)是用于 GPU 和自动微分实验的官方 JAX 数据
  后端。它被明确标注为 pre-alpha 阶段。
- `qutip-cupy` 是一个官方 QuTiP 组织下的仓库，但它没有 PyPI 发布版本，而且
  其自身的 README 也说明尚未正式发布。不要把一个未发布的 Git 安装源放进
  可复现的工作流程中。

当需要连传递依赖(transitive dependency)的身份也一并锁定时，应使用项目
锁定文件或带哈希生成能力的 `uv pip compile` 工作流程。

## 不可协商的模型契约

在求解之前，要先记录:

1. **单位与约定**。 QuTiP 的方程通常设定 \(\hbar=1\)。哈密顿量的各项是角
   频率，速率具有时间倒数的单位。转换周期频率时用 \(2\pi f\);绝不要混用
   Hz 和 rad/s。
2. **子系统顺序**。 `tensor(A, B, C)` 固定了子系统索引 `0, 1, 2`。要在每一
   个态、算符、坍缩通道(collapse channel)和部分求迹(partial trace)中都
   保持这个顺序。`obj.ptrace([0, 2])` 保留的是这些子系统，而不是把它们
   求迹掉。
3. **态的有效性**。 检查态矢量的模、密度矩阵的厄米性(Hermiticity)、迹为
   1,以及本征值是否高于一个明确规定的负值容差。极小的负值可能只是数值
   误差；而实质性的负值意味着所声称的态不成立。
4. **生成元的含义**。 速率为 `gamma` 的 Lindblad 通道，用 `sqrt(gamma) * A`
   表示，而不是 `gamma * A`。要明确定义每个速率所度量的是什么。例如,
   `sqrt(gamma_phi / 2) * sigmaz()` 给出的相干性衰减是 `exp(-gamma_phi * t)`。
5. **近似假设**。 无论在何处使用，都要说明所采用的旋转波近似(rotating-wave)、
   玻恩-马尔可夫近似(Born-Markov)、久期近似(secular)、弱耦合、浴平衡
   (bath-equilibrium)、截断、对称性，以及初始因子化假设。
6. **数值方法**。 要为希尔伯特空间截断、输出网格、积分方法、容差、轨迹数量
   和随机种子提供依据。要报告 `result.stats`。
7. **收敛性**。 要对每一个人为设定的截断值做扫描:Fock 空间维数、时间/频率
   窗口及间距、ODE 容差、轨迹数量、Floquet 谐波、HEOM 深度和浴指数，或视
   情况而定的 PIQS 表示方式。

## Qobj、维度与张量顺序

优先使用显式导入，并同时检查形状(shape)和结构化维度(dims):

```python
from qutip import basis, qeye, sigmaz, tensor

psi = tensor(basis(2, 0), basis(3, 1))
z_on_first = tensor(sigmaz(), qeye(3))

assert psi.shape == (6, 1)
assert psi.dims == [[2, 3], [1]]
assert z_on_first.dims == [[2, 3], [2, 3]]
rho_first = psi.proj().ptrace(0)  # keep subsystem 0
```

单看矩阵形状是不够的:两个对象都可以是 6 行 6 列，却编码着不同的张量分解
方式。在构建复合系统、超算符(superoperator)或信道模型之前，先阅读
`references/core_concepts.md`。

## 依据物理机制选择求解器

| 模型 | 当前 API | 需要说明的依据 |
|---|---|---|
| 封闭、纯态、幺正演化 | `sesolve` | 厄米哈密顿量；无耗散 |
| Lindblad/开放系统或混合态 | `mesolve` | 马尔可夫完全正定模型及信道速率 |
| 量子跳变(Quantum jumps) | `mcsolve` | 展开方式(unravelling)、轨迹收敛性、随机种子 |
| 微观弱耦合浴 | `brmesolve` | 玻恩-马尔可夫/弱耦合近似、谱、是否采用久期近似 |
| 扩散型测量 | `ssesolve`、`smesolve` | 受监测与未受监测信道的区分 |
| 周期性驱动 | `FloquetBasis`、`fsesolve`、`fmmesolve` | 已核实的周期与 Floquet 收敛性 |
| 结构化非马尔可夫浴 | `qutip.solver.heom` | 浴的展开与层级(hierarchy)收敛性 |
| 对称自旋系综 | `qutip.piqs` | 置换对称性与基组选择 |

不要仅仅因为某个更专门的求解器存在，就选用它。

## 确定性开放系统示例

QuTiP 5.3 使用普通的选项字典。求解器控制项、`e_ops` 和 `args` 都是纯关键字
参数；旧版可变的选项对象已被移除。

```python
import numpy as np
from qutip import basis, mesolve, sigmam, sigmaz

omega = 2.0
gamma = 0.15
tlist = np.linspace(0.0, 20.0, 401)
excited = basis(2, 0)

result = mesolve(
    0.5 * omega * sigmaz(),
    excited,
    tlist,
    c_ops=[np.sqrt(gamma) * sigmam()],
    e_ops={"sigma_z": sigmaz(), "excited": excited.proj()},
    options={
        "method": "adams",
        "atol": 1e-10,
        "rtol": 1e-8,
        "store_final_state": True,
        "progress_bar": "",
    },
)

population = np.asarray(result.e_data["excited"])
assert np.max(np.abs(population - np.exp(-gamma * tlist))) < 2e-6
assert isinstance(result.stats, dict)
```

如果问题是刚性(stiff)的，可以比较 `bdf` 或 `lsoda`;不要在没有重新运行
容差和不变量检查的情况下更换积分器。QuTiP 5.3 在 `mesolve` 中还支持
`options={"matrix_form": True}`;在把它当作默认选项使用之前，应先做基准
测试和验证。

## 含时系统

优先使用可信的 Python 可调用对象(callable)或数值系数数组。不要从用户输入
中构造系数的源代码字符串。

```python
import numpy as np
from qutip import QobjEvo, sigmax, sigmaz

def envelope(t, amplitude, center, width):
    return amplitude * np.exp(-0.5 * ((t - center) / width) ** 2)

H = QobjEvo(
    [0.5 * sigmaz(), [sigmax(), envelope]],
    args={"amplitude": 0.2, "center": 5.0, "width": 1.0},
)
instantaneous_H = H(5.0)
H.arguments(amplitude=0.1)
```

较旧的 `f(t, args)` 系数签名在 5.3 中已被弃用，并计划在 5.5 中移除。参见
`references/time_evolution.md`。

## 轨迹与随机求解器

```python
import numpy as np
from qutip import basis, mcsolve, sigmam, sigmaz

tlist = np.linspace(0.0, 10.0, 201)
result = mcsolve(
    0.5 * sigmaz(),
    basis(2, 0),
    tlist,
    [np.sqrt(0.2) * sigmam()],
    e_ops=[basis(2, 0).proj()],
    ntraj=400,
    seeds=20260723,
    options={"keep_runs_results": False, "progress_bar": ""},
)
```

要报告 `ntraj`、`result.seeds`、不确定度或相同种子重复运行的敏感度，以及是
否保留了各次独立运行的结果。只有在成对轨迹(paired trajectories)是有意为
之的情况下，才复用 `seeds=previous_result.seeds`。`ssesolve` 和
`smesolve` 使用的是布尔类型的 `heterodyne` 参数，而不是旧版的整数噪声代码。

## 稳态、谱与相空间

```python
import numpy as np
from qutip import QFunc, liouvillian, operator_to_vector, qfunc, steadystate

rho_ss = steadystate(H, c_ops, method="direct")
residual = (liouvillian(H, c_ops) * operator_to_vector(rho_ss)).norm()
assert residual < 1e-9

xvec = np.linspace(-5.0, 5.0, 151)
Q_once = qfunc(rho_ss, xvec, xvec)
q_many = QFunc(xvec, xvec)
Q_again = q_many(rho_ss)
assert Q_once.shape == (len(xvec), len(xvec))
```

对于 `wigner`、`qfunc` 和 `QFunc`,数组元素 `[j, k]` 对应的是
`yvec[j]`、`xvec[k]`。在 QuTiP 5.3 中,`QFunc` 是用固定坐标初始化、再用
一个态去调用的；它没有 `.eval` 方法。本技能绝不使用 Python 动态代码执行。
优先使用 `plot_wigner`、`Result.plot_expect`,或
`references/visualization.md` 中记录的显式 Matplotlib 坐标轴方式。

直接调用的 `spectrum` 给出的是一个静态的稳态谱。对有限相关函数做 FFT,需要
显式检查尾部衰减、时间步长带来的混叠(aliasing)、频率分辨率、窗函数的
敏感性，以及变换约定。参见 `references/analysis.md`。

## 进阶方法的边界

- 从 `qutip.solver.heom` 导入 HEOM;旧版 QuTiP 4 的 nonmarkov HEOM 命名
  空间已经过时。
- 使用 `FloquetBasis` 获取模式和准能量(quasi-energies)。要通过数值方式
  核实 `H(t + T) == H(t)`,并对基组/截断的选择做扫描。
- 通过 `from qutip import piqs` 访问 PIQS。`Dicke.pisolve` 只是针对
  对角态/对角哈密顿量情形的优化路径；一般的 Dicke 基动力学要使用刘维尔量
  (Liouvillian)配合 `mesolve`。
- `brmesolve` 可能违反正定性，尤其是在未做久期近似(secularization)的
  情况下。应随时间检查密度矩阵的本征值。
- QIP 和最优控制属于扩展软件包的范畴。绝不要把本地仿真结果说成是量子硬件
  的执行结果。

关于 HEOM、Floquet、PIQS、随机方法及扩展软件包的边界，参见
`references/advanced.md`。

## 安全的本地命令行工具

所有打包的工具都仅在本地运行，输出严格的 JSON,拒绝非有限数值的 JSON 和
未知键，且绝不加载 pickle 文件或可执行的模型代码。仿真相关的导入是延迟
(lazy)加载的，因此即使未安装 QuTiP,每个工具的 `--help` 也都能正常运行。

| 脚本 | 用途 |
|---|---|
| `scripts/qobj_model_validator.py` | 校验有边界的 Qobj 模型 JSON、维度、态、速率，以及角色兼容性 |
| `scripts/two_level_simulation.py` | 运行一个有边界的二能级 Lindblad 或量子跳变仿真 |
| `scripts/solver_config_planner.py` | 选择当前求解器，并给出选项/检查清单方案 |
| `scripts/convergence_sweep.py` | 在一个合成模型上扫描容差/网格大小或轨迹数量 |
| `scripts/result_audit.py` | 审计 JSON 输出，而不反序列化 Python 对象 |
| `scripts/steady_state_spectrum_planner.py` | 规划有边界的稳态检查以及直接谱/FFT 谱检查 |

示例:

```bash
python skills/qutip/scripts/two_level_simulation.py --help
python skills/qutip/scripts/two_level_simulation.py \
  --decay-rate 0.2 --t-final 10 --time-points 201 \
  --output two-level.json
python skills/qutip/scripts/result_audit.py two-level.json
```

## 完成检查清单

- 记录单位、\(\hbar\)、张量顺序、初始态、信道，以及模型假设。
- 校验厄米性、模/迹、正定性、维度，以及生成元的单位。
- 锁定 QuTiP 及各直接扩展的版本；记录平台、Python、NumPy 和 SciPy 版本。
- 检查结果的选项和统计信息；不要假定状态已经被存储。
- 对截断值、网格、容差/积分器，以及随机方法做收敛性扫描。
- 把可移植的数值/配置摘要保存为 JSON 或文本格式。不要加载不可信的
  QuTiP 对象/结果文件，因为对象序列化可能执行代码。

## 参考文件

- `references/core_concepts.md` —— Qobj、维度、张量积、态、信道，以及
  单位约定
- `references/time_evolution.md` —— 当前求解器的函数签名、选项、结果、
  QobjEvo、轨迹，以及数值控制
- `references/analysis.md` —— 物理态审计、稳态、关联函数、谱，以及收敛性
- `references/visualization.md` —— Wigner 函数、Q 函数、`QFunc`、Bloch
  球、结果图与矩阵图
- `references/advanced.md` —— Bloch-Redfield、随机方法、Floquet、HEOM、
  PIQS,以及 QuTiP 系列软件包的边界

## 带日期的官方来源

核实于 **2026-07-23**:

- [QuTiP 5.3.0 PyPI metadata](https://pypi.org/project/qutip/)
- [QuTiP 5.3.0 release](https://github.com/qutip/qutip/releases/tag/v5.3.0)
- [QuTiP 5.3 changelog](https://qutip.readthedocs.io/en/stable/changelog.html)
- [QuTiP 5.3 API](https://qutip.readthedocs.io/en/stable/apidoc/apidoc.html)
- [QuTiP version-5 tutorials](https://github.com/qutip/qutip-tutorials/tree/main/tutorials-v5)
- [qutip-qip PyPI](https://pypi.org/project/qutip-qip/)
- [qutip-qtrl PyPI](https://pypi.org/project/qutip-qtrl/)
- [qutip-jax PyPI](https://pypi.org/project/qutip-jax/)
- [official unreleased qutip-cupy repository](https://github.com/qutip/qutip-cupy)
