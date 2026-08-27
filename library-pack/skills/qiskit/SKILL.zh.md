# Qiskit

使用当前的 Qiskit 2.x API 来构建电路、准备与硬件兼容的指令集架构
（instruction set architecture，ISA）电路，并通过 V2 原语
（primitive）来执行它们。

本技能于 **2026-07-23** 针对 PyPI 发行版 `qiskit==2.5.0`、
`qiskit-ibm-runtime==0.48.0` 和 `qiskit-aer==0.17.2` 做过验证。
在改动版本锁定或记录新发布的行为之前，请查阅
[references/sources.md](references/sources.md)。

## 选择合适的路径

| 目标 | 推荐接口 |
|---|---|
| 精确的本地采样 | `qiskit.primitives.StatevectorSampler` |
| 精确的本地期望值 | `qiskit.primitives.StatevectorEstimator` |
| 高性能或带噪声的仿真 | Qiskit Aer |
| IBM 量子处理器（QPU）采样 | `qiskit_ibm_runtime.SamplerV2` |
| IBM QPU 期望值与误差缓解 | `qiskit_ibm_runtime.EstimatorV2` |
| 不带原生原语的后端 | `BackendSamplerV2` 或 `BackendEstimatorV2` |
| 开放系统或主方程（master-equation）动力学 | 优先使用 QuTiP |
| 可微分量子机器学习 | 除非需要与 Qiskit 集成，否则优先使用 PennyLane |

## 安装

创建一个隔离环境，只安装所需的组件：

```bash
uv venv --python 3.13
source .venv/bin/activate

# 核心 SDK 加上绘图支持
uv pip install "qiskit[visualization]==2.5.0"

# 仅在需要时添加
uv pip install "qiskit-ibm-runtime==0.48.0"
uv pip install "qiskit-aer==0.17.2"
```

不要安装 `qiskit-terra`；它已被 `qiskit` 这个发行包取代。Qiskit
Runtime、Aer、Nature、Machine Learning、Optimization 和 Algorithms
都是独立的发行包。

关于 IBM 账户设置、对 CI 友好的凭据处理、可选包，以及环境修复，
请阅读 [references/setup.md](references/setup.md)。

## 核心工作流

对每一个面向硬件的工作负载，都遵循这样的顺序：

1. **映射（Map）**——把问题映射为一个电路，若使用 Estimator，还需要
   映射为一个或多个可观测量（observable）。
2. **优化（Optimize）**——针对所选后端，对带参数的电路只做一次优化。
3. **应用布局（Apply the layout）**——把该布局应用到每一个可观测量上。
4. **执行（Execute）**——通过 V2 原语，用「原语统一块」（Primitive
   Unified Blocs，PUB）来执行 ISA 电路。
5. **分析（Analyze）**——分析带寄存器信息的结果、元数据、不确定度,
   以及资源使用情况。

不要在每一次优化器迭代内部都对一个带参数的电路做绑定和重新转译
（transpile）。应该只对带参数的电路转译一次，然后在 PUB 中传入参数
数组。

## 快速本地采样

```python
from qiskit import QuantumCircuit
from qiskit.primitives import StatevectorSampler

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()  # creates the classical register named "meas"

sampler = StatevectorSampler(seed=7)
pub_result = sampler.run([circuit], shots=1024).result()[0]
counts = pub_result.data.meas.get_counts()
print(counts)
```

Sampler V2 会保留 shots（发射次数）以及经典寄存器结构。要通过寄存器
的实际名称来访问它；`measure_all()` 使用的名称是 `meas`。

## 快速本地估计

```python
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.primitives import StatevectorEstimator
from qiskit.quantum_info import SparsePauliOp

theta = Parameter("theta")
circuit = QuantumCircuit(2)
circuit.ry(theta, 0)
circuit.cx(0, 1)

observable = SparsePauliOp.from_list([("ZZ", 1.0), ("XX", 0.5)])
parameter_values = [[0.0], [np.pi / 4], [np.pi / 2]]

estimator = StatevectorEstimator(seed=7)
pub = (circuit, observable, parameter_values)
pub_result = estimator.run([pub]).result()[0]
print(pub_result.data.evs)
```

Estimator 使用的电路不应包含末端测量（final measurement）。PUB 数组
会做广播（broadcast）；在构造大规模参数扫描之前，要先核实电路参数的
顺序。

## IBM QPU 采样

本示例假定凭据已按 [references/setup.md](references/setup.md)
中所述的方式安全保存。它绝不会嵌入或打印 API 密钥。

```python
from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler

service = QiskitRuntimeService()
backend = service.least_busy(
    operational=True,
    simulator=False,
    min_num_qubits=2,
)

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()

pass_manager = generate_preset_pass_manager(
    backend=backend,
    optimization_level=1,
    seed_transpiler=7,
)
isa_circuit = pass_manager.run(circuit)

sampler = Sampler(mode=backend)
job = sampler.run([isa_circuit], shots=1024)
print("job_id:", job.job_id())
counts = job.result()[0].data.meas.get_counts()
```

在等待结果之前先保存作业 ID（job ID），这样之后就可以取回该作业。

## IBM QPU 估计

Runtime 版本的 Estimator 既需要一个 ISA 电路，也需要通过转译器布局
（transpiler layout）映射过的可观测量：

```python
from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import EstimatorV2 as Estimator

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
observable = SparsePauliOp.from_list([("ZZ", 1.0)])

pass_manager = generate_preset_pass_manager(
    backend=backend,
    optimization_level=1,
    seed_transpiler=7,
)
isa_circuit = pass_manager.run(circuit)
isa_observable = observable.apply_layout(isa_circuit.layout)

estimator = Estimator(
    mode=backend,
    options={"resilience_level": 1},
)
pub_result = estimator.run(
    [(isa_circuit, isa_observable)],
    precision=0.02,
).result()[0]
print(pub_result.data.evs, pub_result.data.stds)
```

误差缓解（error mitigation）并不保证能改善每一个工作负载的结果，
而且会增加成本。要记录完整的选项和结果元数据。

## Qiskit 2.x 不可协商的规则

- 使用 V2 原语接口和 PUB 输入。不要再编写新的 V1 版 `Sampler`、
  `Estimator`,或 `QuantumInstance` 代码。
- Runtime 原语接受的是 ISA 电路；它们不会替你完成布局、路由和基集
  （basis）转换。
- 用 `observable.apply_layout(isa_circuit.layout)` 把转译器布局
  应用到 Estimator 的可观测量上。
- 对于 Runtime 原语，使用 `mode=backend`、`mode=session`,或
  `mode=batch`。
- 要获得韧性级别（resilience level）和期望值缓解，使用
  `EstimatorV2`。Sampler 有不同的噪声管理选项，并没有类似 Estimator
  那样的韧性级别。
- 把 `BackendV2.target`、`backend.operation_names`、
  `backend.coupling_map`,以及后端的直接属性，当作硬件约束的信息
  来源。不要使用 `backend.configuration()` 或 `BackendProperties`。
- 按经典寄存器名称来读取 Sampler 的输出。比特串的显示方式是最高
  有效位（most-significant bit）在前；而按照惯例，Qiskit 的 qubit 0
  是最低有效位。
- 在比较不同的编译设置时，使用一个固定的 `seed_transpiler`。
  仿真器的随机种子并不能使 QPU 的结果具有确定性。
- `qiskit.pulse` 在 Qiskit 2.0 中已被移除。对于 IBM 硬件，使用受支持
  的分数门（fractional gate）；对于脉冲模型研究，使用 Qiskit
  Dynamics。
- QPY 是 Qiskit 原生的电路序列化格式。对于不受信任的电路产物，不要
  使用 Python 的 pickle。

关于从旧版 API 到当前 API 的详细映射，参见
[references/migration.md](references/migration.md)。

## 执行模式

根据工作负载的形态和账户套餐来选择：

- **Job 模式**：一次性的工作；用 `mode=backend` 实例化一个原语。
- **Batch 模式**：一起提交的若干独立作业；在 Open Plan（开放套餐）
  上可用。
- **Session 模式**：能从有优先权的后续执行中受益的迭代式作业；在
  Open Plan 上不可用。

```python
from qiskit_ibm_runtime import Batch, SamplerV2 as Sampler

with Batch(backend=backend, max_time="10m") as batch:
    sampler = Sampler(mode=batch)
    jobs = [sampler.run([circuit], shots=1024) for circuit in isa_circuits]

results = [job.result() for job in jobs]
```

提交之后要关闭 session 和 batch。退出它们的上下文（context）会阻止
新的提交，但已被接受的作业仍可以完成，具体受服务限制约束。

## 参考资料索引

只阅读当前任务所需要的那些文件：

| 主题 | 参考文档 |
|---|---|
| 版本、安装、认证、CI | [references/setup.md](references/setup.md) |
| 电路、参数、控制流、QPY | [references/circuits.md](references/circuits.md) |
| V2 版 PUB、广播、本地与 Runtime 结果 | [references/primitives.md](references/primitives.md) |
| Target、ISA 电路、布局、pass manager | [references/transpilation.md](references/transpilation.md) |
| IBM 后端、模式、作业、Aer、误差缓解 | [references/backends.md](references/backends.md) |
| 端到端的映射/优化/执行/分析模式 | [references/patterns.md](references/patterns.md) |
| 算法、附加组件、Nature、ML、Optimization | [references/algorithms.md](references/algorithms.md) |
| 电路、结果、态，以及后端相关的绘图 | [references/visualization.md](references/visualization.md) |
| Qiskit 0.x/1.x 与 Runtime 的迁移 | [references/migration.md](references/migration.md) |
| 测试、可复现性，以及故障排查 | [references/testing.md](references/testing.md) |
| 上游文档、发行说明，以及版本基线 | [references/sources.md](references/sources.md) |

## 内置脚本

从技能目录中运行：

```bash
# 已安装包与旧版环境检查；不联网,不读取凭据
python scripts/check_environment.py

# 可直接运行的 V2 本地 Sampler 与 Estimator 示例
python scripts/run_local_primitives.py --shots 1024 --seed 7

# 只读的 IBM 后端能力检查；使用已保存的凭据
python scripts/inspect_runtime.py --min-qubits 5
```

这个 Runtime 检查脚本会选择或检查一个后端，但绝不会提交任何量子
作业。

## 最终检查清单

在交付 Qiskit 代码之前：

1. 确认包版本以及 Python 兼容性。
2. 用态矢量（statevector）原语或 Aer 在本地运行一遍。
3. 核实参数顺序、可观测量所涉及的比特数，以及经典寄存器名称。
4. 针对确切的 `BackendV2` target 做转译，并检查电路深度和双比特门
   操作。
5. 把最终布局应用到每一个可观测量上。
6. 估算 QPU 的成本，并选择 job、batch,或 session 模式。
7. 保存作业 ID、包版本、随机种子、后端名称、原语选项，以及结果
   元数据。
8. 绝不在源代码、日志、笔记本，或版本控制中暴露 API 密钥。
