# Cirq - 用 Python 进行量子计算

Cirq 是 Google Quantum AI 推出的开源框架，用于在量子计算机和模拟器上设计、
模拟和运行量子电路。

## 何时使用本技能

在以下情况下使用本技能:
- 用 Python 构建、模拟或优化 NISQ(含噪声中等规模量子)电路
- 在 Google Quantum AI 处理器上(通过 `cirq-google`)或合作伙伴后端
  (IonQ、Azure Quantum、AQT、Pasqal)上运行任务
- 建模噪声、编译到硬件门集(gateset),或设计表征(characterization)实验
- 使用参数扫描(parameter sweeps)、变换器(transformers),或 ReCirq
  实验模式

面向 IBM 硬件请使用 **qiskit**;涉及自动微分的量子机器学习请使用
**pennylane**;物理仿真请使用 **qutip**。

## 安装

需要 Python 3.11+。当前稳定版本:**1.6.1**(2025 年 8 月)。各厂商相关的
软件包共享同一个版本号。

```bash
uv pip install "cirq==1.6.1"
```

用于硬件集成(为保证可复现性，应锁定匹配的版本):
```bash
# Google Quantum Engine (requires approved GCP project access)
uv pip install "cirq-google==1.6.1"

# IonQ
uv pip install "cirq-ionq==1.6.1"

# AQT (Alpine Quantum Technologies)
uv pip install "cirq-aqt==1.6.1"

# Pasqal
uv pip install "cirq-pasqal==1.6.1"

# Azure Quantum (IonQ, Honeywell/Quantinuum backends)
uv pip install "azure-quantum[cirq]"
```

在开发阶段想要用到最新特性时，可以不锁定版本；而在生产环境或硬件运行时,
应将所有相关软件包都锁定到同一个 Cirq 发布版本。

## 快速开始

### 基础电路

```python
import cirq
import numpy as np

# Create qubits
q0, q1 = cirq.LineQubit.range(2)

# Build circuit
circuit = cirq.Circuit(
    cirq.H(q0),              # Hadamard on q0
    cirq.CNOT(q0, q1),       # CNOT with q0 control, q1 target
    cirq.measure(q0, q1, key='result')
)

print(circuit)

# Simulate
simulator = cirq.Simulator()
result = simulator.run(circuit, repetitions=1000)

# Display results
print(result.histogram(key='result'))
```

### 参数化电路

```python
import sympy

# Define symbolic parameter
theta = sympy.Symbol('theta')

# Create parameterized circuit
circuit = cirq.Circuit(
    cirq.ry(theta)(q0),
    cirq.measure(q0, key='m')
)

# Sweep over parameter values
sweep = cirq.Linspace('theta', start=0, stop=2*np.pi, length=20)
results = simulator.run_sweep(circuit, params=sweep, repetitions=1000)

# Process results
for params, result in zip(sweep, results):
    theta_val = params['theta']
    counts = result.histogram(key='m')
    print(f"θ={theta_val:.2f}: {counts}")
```

## 核心能力

### 电路构建
关于构建量子电路的全面信息，包括量子比特(qubit)、门操作、算符、自定义
门，以及电路模式，请参阅:
- **[references/building.md](references/building.md)** —— 电路构建完整指南

常见主题:
- 量子比特类型(GridQubit、LineQubit、NamedQubit)
- 单比特和双比特门
- 参数化的门与算符
- 自定义门的分解
- 用 moment 组织电路
- 标准电路模式(Bell 态、GHZ 态、QFT)
- 导入/导出(OpenQASM、JSON)
- 处理量子多值系统(qudit)与可观测量

### 模拟
关于量子电路模拟的详细信息，包括精确模拟、含噪声模拟、参数扫描，以及量子
虚拟机，请参阅:
- **[references/simulation.md](references/simulation.md)** —— 量子模拟完整指南

常见主题:
- 精确模拟(态矢量、密度矩阵)
- 采样与测量
- 参数扫描(单参数与多参数)
- 含噪声模拟
- 状态直方图与可视化
- 量子虚拟机(QVM)
- 期望值与可观测量
- 性能优化

### 电路变换
关于优化、编译和操作量子电路的信息，请参阅:
- **[references/transformation.md](references/transformation.md)** —— 电路变换完整指南

常见主题:
- 变换器(Transformer)框架
- 门分解
- 电路优化(合并门、消去 Z 门、丢弃可忽略的操作)
- 面向硬件的电路编译
- 量子比特路由与 SWAP 插入
- 自定义变换器
- 变换流水线

### 硬件集成
关于在各家提供商的真实量子硬件上运行电路的信息，请参阅:
- **[references/hardware.md](references/hardware.md)** —— 硬件集成完整指南

支持的提供商:
- **Google Quantum AI**(`cirq-google`)—— 通过 Quantum Engine 使用
  Sycamore、Weber、Willow 处理器(访问受限；需要经批准的 GCP 项目)
- **IonQ**(`cirq-ionq`)—— 离子阱 QPU 与模拟器
- **Azure Quantum**(`azure-quantum[cirq]`)—— IonQ 和
  Honeywell/Quantinuum 后端
- **AQT**(`cirq-aqt`)—— Alpine Quantum Technologies
- **Pasqal**(`cirq-pasqal`)—— 中性原子器件

涉及的主题包括设备表示、量子比特选择、身份验证、任务管理，以及针对硬件的
电路优化。Google Cloud 相关配置见
[Access and authentication](https://quantumai.google/cirq/google/access)。

### 噪声建模
关于噪声建模、含噪声模拟、表征，以及误差缓解的信息，请参阅:
- **[references/noise.md](references/noise.md)** —— 噪声建模完整指南

常见主题:
- 噪声信道(去极化、振幅阻尼、相位阻尼)
- 噪声模型(常量噪声、按门类型区分、按量子比特区分、热噪声)
- 为电路添加噪声
- 读出噪声(Readout noise)
- 噪声表征(随机基准测试、XEB)
- 噪声可视化(热力图)
- 误差缓解技术

### 量子实验
关于设计实验、参数扫描、数据采集，以及使用 ReCirq 框架的信息，请参阅:
- **[references/experiments.md](references/experiments.md)** —— 量子实验完整指南

常见主题:
- 实验设计模式
- 参数扫描与数据采集
- ReCirq 框架结构
- 常见算法(VQE、QAOA、QPE)
- 数据分析与可视化
- 统计分析与保真度估计
- 并行数据采集

## 常见模式

### 变分算法模板

```python
import scipy.optimize

def variational_algorithm(ansatz, cost_function, initial_params):
    """Template for variational quantum algorithms."""

    def objective(params):
        circuit = ansatz(params)
        simulator = cirq.Simulator()
        result = simulator.simulate(circuit)
        return cost_function(result)

    # Optimize
    result = scipy.optimize.minimize(
        objective,
        initial_params,
        method='COBYLA'
    )

    return result

# Define ansatz
def my_ansatz(params):
    q = cirq.LineQubit(0)
    return cirq.Circuit(
        cirq.ry(params[0])(q),
        cirq.rz(params[1])(q)
    )

# Define cost function
def my_cost(result):
    state = result.final_state_vector
    # Calculate cost based on state
    return np.real(state[0])

# Run optimization
result = variational_algorithm(my_ansatz, my_cost, [0.0, 0.0])
```

### 硬件执行模板

```python
import os

def run_on_hardware(circuit, provider='google', processor_id=None, repetitions=1000):
    """Template for running on quantum hardware."""

    if provider == 'google':
        import cirq_google as cg

        project_id = os.environ['GOOGLE_CLOUD_PROJECT']
        engine = cg.Engine(project_id=project_id)

        # List available processors: engine.list_processors()
        processor_id = processor_id or 'weber'  # use your assigned processor_id
        sampler = engine.get_sampler(processor_id=processor_id)
        return sampler.run(circuit, repetitions=repetitions)

    elif provider == 'ionq':
        import cirq_ionq as ionq

        # Requires IONQ_API_KEY in environment
        service = ionq.Service()
        return service.run(circuit, repetitions=repetitions, target='qpu')

    elif provider == 'azure':
        from azure.quantum.cirq import AzureQuantumService

        service = AzureQuantumService(
            resource_id=os.environ['AZURE_QUANTUM_RESOURCE_ID'],
            location=os.environ['AZURE_QUANTUM_LOCATION'],
        )
        return service.run(circuit, repetitions=repetitions, target='ionq.qpu')

    else:
        raise ValueError(f"Unknown provider: {provider}")
```

### 噪声研究模板

```python
def noise_comparison_study(circuit, noise_levels):
    """Compare circuit performance at different noise levels."""

    results = {}

    for noise_level in noise_levels:
        # Create noisy circuit
        noisy_circuit = circuit.with_noise(cirq.depolarize(p=noise_level))

        # Simulate
        simulator = cirq.DensityMatrixSimulator()
        result = simulator.run(noisy_circuit, repetitions=1000)

        # Analyze
        results[noise_level] = {
            'histogram': result.histogram(key='result'),
            'dominant_state': max(
                result.histogram(key='result').items(),
                key=lambda x: x[1]
            )
        }

    return results

# Run study
noise_levels = [0.0, 0.001, 0.01, 0.05, 0.1]
results = noise_comparison_study(circuit, noise_levels)
```

## 最佳实践

1. **电路设计**
   - 针对目标拓扑结构使用合适的量子比特类型
   - 保持电路模块化、可复用
   - 用有描述性的键(key)标注测量结果
   - 在执行前对照设备约束条件校验电路

2. **模拟**
   - 对纯态使用态矢量模拟(效率更高)
   - 只在需要时(混合态、噪声)才使用密度矩阵模拟
   - 善用参数扫描，而不是逐次单独运行
   - 对于大系统要留意内存占用(2^n 增长很快)

3. **硬件执行**
   - 始终先在模拟器上测试
   - 根据校准数据挑选最合适的量子比特
   - 针对目标硬件门集优化电路
   - 在生产环境运行中实施误差缓解
   - 立即保存来之不易的硬件运行结果

4. **电路优化**
   - 从高层内置的变换器(transformer)开始
   - 依序串联多个优化步骤
   - 追踪电路深度和门数量的削减情况
   - 变换后要校验正确性

5. **噪声建模**
   - 使用基于校准数据的真实噪声模型
   - 涵盖所有误差来源(门操作、退相干、读出)
   - 先表征，再缓解
   - 保持电路较浅，以减少噪声累积

6. **实验**
   - 用清晰的阶段划分来组织实验(数据生成、采集、分析)
   - 使用 ReCirq 模式以保证可复现性
   - 频繁保存中间结果
   - 并行处理相互独立的任务
   - 用元数据做详尽的文档记录

## 其他资源

- **官方文档**: https://quantumai.google/cirq
- **API 参考**: https://quantumai.google/reference/python/cirq
- **教程**: https://quantumai.google/cirq/tutorials
- **示例**: https://github.com/quantumlib/Cirq/tree/main/examples
- **版本策略**: https://quantumai.google/cirq/dev/versions
- **ReCirq**: https://github.com/quantumlib/ReCirq

## 常见问题

**电路对硬件来说太深**:
- 使用电路优化变换器来降低深度
- 优化技巧参见 `transformation.md`

**模拟出现内存问题**:
- 从密度矩阵模拟器切换为态矢量模拟器
- 减少量子比特数量，或对 Clifford 电路使用稳定子(stabilizer)模拟器

**设备校验错误**:
- 用 device.metadata.nx_graph 检查量子比特连通性
- 把门分解为设备原生的门集
- 特定设备的编译方式参见 `hardware.md`

**含噪声模拟太慢**:
- 密度矩阵模拟的复杂度是 O(2^2n)——考虑减少量子比特数量
- 只在关键操作上有选择地使用噪声模型
- 性能优化参见 `simulation.md`
