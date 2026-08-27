# PennyLane

## 概览

PennyLane 是一个量子计算库，能够像训练神经网络一样训练量子计算机。它提供对量子电路的自动微分、与设备无关的编程方式，以及与经典机器学习框架的无缝集成。

## 安装

PennyLane 0.45.0 需要 Python 3.11 或更高版本。使用 uv 并锁定版本以获得可复现的环境:

```bash
uv pip install "pennylane==0.45.0"
```

要访问量子硬件，请安装与目标提供商匹配的插件。在添加或升级 Qiskit 时，建议从一个干净的环境开始，因为它的依赖关系图较为严格。

```bash
# IBM Quantum
uv pip install "pennylane-qiskit==0.45.0"

# Amazon Braket
uv pip install "amazon-braket-pennylane-plugin==1.34.1"

# Google Cirq
uv pip install "pennylane-cirq==0.44.0"

# Rigetti Forest
uv pip install "pennylane-rigetti==0.40.0"

# IonQ
uv pip install "pennylane-ionq==0.45.0"

# High-performance local simulators
uv pip install "pennylane-lightning==0.45.0"

# Catalyst JIT compilation
uv pip install "pennylane-catalyst==0.15.0"
```

## 快速开始

构建一个量子电路并优化其参数:

```python
import pennylane as qml
from pennylane import numpy as np

# Create device
dev = qml.device('default.qubit', wires=2)

# Define quantum circuit
@qml.qnode(dev)
def circuit(params):
    qml.RX(params[0], wires=0)
    qml.RY(params[1], wires=1)
    qml.CNOT(wires=[0, 1])
    return qml.expval(qml.PauliZ(0))

# Optimize parameters
opt = qml.GradientDescentOptimizer(stepsize=0.1)
params = np.array([0.1, 0.2], requires_grad=True)

for i in range(100):
    params = opt.step(circuit, params)
```

## 核心能力

### 1. 量子电路构建

使用门(gate)、测量和态制备来构建电路。详见 `references/quantum_circuits.md`,涵盖:
- 单量子比特与多量子比特门
- 受控操作与条件逻辑
- 电路中途测量(mid-circuit measurement)与自适应电路
- 各种测量类型(期望值、概率、采样)
- 电路检查与调试

### 2. 量子机器学习

创建混合量子-经典模型。详见 `references/quantum_ml.md`,涵盖:
- 与 PyTorch 和 JAX 的集成
- 量子神经网络与变分分类器
- 数据编码策略(角度编码、振幅编码、基态编码、IQP 编码)
- 通过反向传播训练混合模型
- 使用量子电路进行迁移学习

### 3. 量子化学

模拟分子并计算基态能量。详见 `references/quantum_chemistry.md`,涵盖:
- 分子哈密顿量生成
- 变分量子本征求解器(Variational Quantum Eigensolver, VQE)
- 用于化学计算的 UCCSD ansatz
- 几何结构优化与解离曲线
- 分子性质计算

### 4. 设备管理

在模拟器或量子硬件上执行电路。详见 `references/devices_backends.md`,涵盖:
- 内置模拟器(default.qubit、lightning.qubit、default.mixed)
- 硬件插件(IBM、Amazon Braket、Google、Rigetti、IonQ)
- 设备选择与配置
- 性能优化与缓存
- GPU 加速与 JIT 编译

### 5. 优化

使用各种优化器训练量子电路。详见 `references/optimization.md`,涵盖:
- 内置优化器(Adam、梯度下降、动量法、RMSProp)
- 梯度计算方法(反向传播、参数移位法(parameter-shift)、伴随法(adjoint))
- 变分算法(VQE、QAOA)
- 训练策略(学习率调度、小批量训练)
- 处理贫瘠高原(barren plateaus)和局部极小值问题

### 6. 高级特性

利用模板、变换和编译功能。详见 `references/advanced_features.md`,涵盖:
- 电路模板与层
- 变换与电路优化
- 脉冲级编程
- Catalyst JIT 编译
- 噪声模型与误差缓解
- 资源估计

## 常见工作流程

### 训练一个变分分类器

```python
# 1. Define ansatz
@qml.qnode(dev)
def classifier(x, weights):
    # Encode data
    qml.AngleEmbedding(x, wires=range(4))

    # Variational layers
    qml.StronglyEntanglingLayers(weights, wires=range(4))

    return qml.expval(qml.PauliZ(0))

# 2. Train
opt = qml.AdamOptimizer(stepsize=0.01)
weights = np.random.random((3, 4, 3))  # 3 layers, 4 wires

for epoch in range(100):
    for x, y in zip(X_train, y_train):
        weights = opt.step(lambda w: (classifier(x, w) - y)**2, weights)
```

### 运行 VQE 求解分子基态

```python
from pennylane import qchem

# 1. Build Hamiltonian
symbols = ['H', 'H']
geometry = np.array([[0.0, 0.0, -0.66140414], [0.0, 0.0, 0.66140414]])
molecule = qchem.Molecule(symbols, geometry)
H, n_qubits = qchem.molecular_hamiltonian(molecule)
hf_state = qchem.hf_state(electrons=2, orbitals=n_qubits)
singles, doubles = qchem.excitations(electrons=2, orbitals=n_qubits)
s_wires, d_wires = qchem.excitations_to_wires(singles, doubles)

# 2. Define ansatz
@qml.qnode(dev)
def vqe_circuit(params):
    qml.BasisState(hf_state, wires=range(n_qubits))
    qml.UCCSD(params, wires=range(n_qubits), s_wires=s_wires, d_wires=d_wires)
    return qml.expval(H)

# 3. Optimize
opt = qml.AdamOptimizer(stepsize=0.1)
params = np.zeros(len(singles) + len(doubles), requires_grad=True)

for i in range(100):
    params, energy = opt.step_and_cost(vqe_circuit, params)
    print(f"Step {i}: Energy = {energy:.6f} Ha")
```

### 在不同设备之间切换

```python
# Same circuit, different backends
circuit_def = lambda dev: qml.qnode(dev)(circuit_function)

# Test on simulator
dev_sim = qml.device('default.qubit', wires=4)
result_sim = circuit_def(dev_sim)(params)

# Run on quantum hardware
from qiskit_ibm_runtime import QiskitRuntimeService

service = QiskitRuntimeService()
backend = service.least_busy(operational=True, simulator=False, min_num_qubits=4)
dev_hw = qml.device('qiskit.remote', wires=backend.num_qubits, backend=backend)
result_hw = circuit_def(dev_hw)(params)
```

## 详细文档

关于特定主题的全面覆盖内容，请查阅以下参考文件:

- **入门指南**:`references/getting_started.md` —— 安装、基本概念、第一步操作
- **量子电路**:`references/quantum_circuits.md` —— 门、测量、电路模式
- **量子机器学习**:`references/quantum_ml.md` —— 混合模型、框架集成、量子神经网络(QNN)
- **量子化学**:`references/quantum_chemistry.md` —— VQE、分子哈密顿量、化学工作流程
- **设备**:`references/devices_backends.md` —— 模拟器、硬件插件、设备配置
- **优化**:`references/optimization.md` —— 优化器、梯度、变分算法
- **高级内容**:`references/advanced_features.md` —— 模板、变换、JIT 编译、噪声

## 最佳实践

1. **先从模拟器开始** —— 在部署到硬件之前，先在 `default.qubit` 上测试
2. **面向硬件时使用参数移位法(parameter-shift)** —— 反向传播只能在模拟器上使用
3. **选择合适的编码方式** —— 让数据编码方式与问题结构相匹配
4. **谨慎初始化** —— 使用较小的随机值以避免贫瘠高原(barren plateaus)问题
5. **监控梯度** —— 检查深层电路中是否存在梯度消失
6. **缓存设备对象** —— 复用设备对象以减少初始化开销
7. **分析电路** —— 使用 `qml.specs()` 分析电路复杂度
8. **本地测试** —— 在提交到硬件之前，先在模拟器上验证
9. **使用模板** —— 对常见电路模式利用内置模板
10. **尽可能进行编译** —— 对性能关键代码使用 Catalyst JIT

## 资源

- 官方文档:https://docs.pennylane.ai
- Codebook(教程):https://pennylane.ai/codebook
- QML 演示:https://pennylane.ai/qml/demonstrations
- 社区论坛:https://discuss.pennylane.ai
- GitHub:https://github.com/PennyLaneAI/pennylane
