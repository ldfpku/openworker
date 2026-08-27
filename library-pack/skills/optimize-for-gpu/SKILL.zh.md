# GPU Optimization for Python with NVIDIA（面向 NVIDIA 的 Python GPU 优化）

把 GPU 加速当作一项以证据为驱动的优化，而不是一次自动重写。保持用户原有的数值和算法约定(contract),用有代表性的数据进行测量，并且只有在同步的端到端基准测试显示出有意义的提升时，才保留 GPU 版本。

## 何时适用本技能

- 用户希望加快数值/科学计算类 Python 代码的运行速度
- 用户在处理大型数组、矩阵或数据框(dataframe)
- 用户提到 CUDA、GPU、NVIDIA 或并行计算
- 用户有处理大数据集的 NumPy、pandas、SciPy、scikit-learn、NetworkX 或 scipy.sparse.linalg 代码
- 用户需要底层 GPU 基元(稀疏特征值求解器、设备内存管理、多 GPU 通信)
- 用户在做机器学习(训练、推理、超参数调优、预处理)
- 用户在做图分析(中心性、社区发现、最短路径、PageRank 等)
- 用户在做向量搜索、最近邻搜索、相似性搜索，或构建 RAG 流水线
- 用户有可以做 GPU 加速的 Faiss、Annoy、ScaNN 或 sklearn NearestNeighbors 代码
- 用户希望在大数据集上实现 GPU 加速的交互式仪表盘、交叉筛选或探索性数据分析
- 用户在用 GeoPandas 或 shapely 做地理空间分析(点在多边形内判断、空间连接、轨迹分析、距离计算)
- 用户在用 scikit-image 或 OpenCV 做图像处理、计算机视觉，或医学影像处理(滤波、分割、形态学操作、特征检测)
- 用户在处理全切片图像(WSI)、数字病理学、显微成像或遥感影像
- 用户正在把大型二进制数据文件加载进 GPU 内存(numpy.fromfile → cupy,或 Python open() → GPU 数组)
- 用户需要直接把 S3、HTTP 或 WebHDFS 中的文件读入 GPU 内存
- 用户提到 GPUDirect Storage(GDS),或希望绕过 CPU 内存中转来做文件 IO
- 用户在做物理仿真(粒子、布料、流体、刚体)或可微分仿真
- 用户需要网格操作(光线投射、最近点查询、有符号距离场)或 GPU 上的几何处理
- 用户在做机器人学(运动学、动力学、控制)相关的变换和四元数运算
- 用户有可以被 JIT 编译为 GPU 内核的 Python 仿真循环
- 用户提到 NVIDIA Warp,或希望把可微分 GPU 仿真与 PyTorch/JAX 集成
- 用户在做仿真、信号处理、金融建模、生物信息学、物理学，或任何计算密集型工作
- 用户希望优化现有代码，而 GPU 加速正是恰当的解法

## 选择恰当的最小层级

优先使用维护良好的库实现，而不是自定义内核:

| 现有工作负载 | 首选路径 | 适用场景 |
| --- | --- | --- |
| NumPy / SciPy | **CuPy** | 数组、稀疏矩阵、线性代数、FFT、信号处理 |
| pandas | **cudf.pandas**,其次 **cuDF** | 先用加速器模式；需要更多控制时用原生 API |
| scikit-learn | **cuml.accel**,其次 **cuML** | 先用加速器模式；需要时使用原生估计器 |
| NetworkX | **nx-cugraph**,其次 **cuGraph** | 先用后端分发；大规模场景下使用原生图 API |
| scikit-image | **cuCIM** | GPU 图像处理和全切片成像 |
| Faiss / Annoy / k-NN | **cuVS** | 精确与近似向量搜索 |
| 原始或远程文件 I/O | **KvikIO** | GPU 缓冲区和 GPUDirect Storage |
| 自定义数组内核 | 新工作用 **Numba-CUDA-MLIR**;现有代码用 **Numba-CUDA** | 显式的 SIMT 内核和共享内存 |
| 空间或可微分内核 | **Warp** | 几何、仿真内核、机器人学、自动微分 |
| 高层物理仿真 | **Newton** | 维护中的引擎，是已移除的 `warp.sim` 模块的继任者 |
| 底层 RAPIDS 基元 | **RAFT**(`pylibraft`) | 稀疏特征值求解器、资源管理、多 GPU 构建模块 |

不要仅仅为了使用上述某个库，就把代码从 PyTorch、JAX、TensorFlow 或其他原生支持 GPU 的框架中搬出来。首先应消除 CPU 往返(round trip),并使用该框架自身的编译器、性能分析器、混合精度和批处理机制。

以下项目应视为仅供维护的遗留项目:

| 项目 | 状态 | 建议 |
| --- | --- | --- |
| **cuxfilter** | 最终发布版本为 26.06 | 仅维护现有仪表盘。新工作应把 cuDF 与 HoloViews/hvPlot/Datashader 结合，并用 Panel、Dash、Streamlit 或 Bokeh 提供服务。 |
| **cuSpatial** | 已在 25.04 版本归档 | 仅在隔离的遗留环境中使用。新工作应把几何计算留在 GeoPandas/Shapely 中，并用 cuDF 加速兼容的表格化阶段。 |

关于每个库的完整指导——包括每个库*不该*使用的场景以及如何组合使用它们——参见 [references/decision_framework.md](references/decision_framework.md)。安装命令和 CUDA 版本选择参见 [references/installation.md](references/installation.md)。每个库的前后转换示例参见 [references/code_transformation_patterns.md](references/code_transformation_patterns.md)。

## 优化工作流程

### 1. 明确约定(contract)并建立基线

- 记录一份有代表性的输入、预期输出，以及可接受的数值容差。
- 测量当前的端到端路径，包括输入、传输、计算和输出各环节。
- 在改动代码之前先做性能分析(profile)。对 CPU 代码使用 CPU 性能分析工具，并判断真正的瓶颈是计算、内存带宽、内存分配、传输、同步，还是存储。
- 把硬件、软件包版本、数据类型(dtype)、形状(shape)、批大小和预热(warm-up)策略与结果一并记录下来。

### 2. 移植之前先检查适用性

当热点路径暴露出大量可独立并行的工作、运行频率足以摊薄初始化和传输成本，并且工作集能装入可用的设备内存(且留有临时空间)时,GPU 执行才是有前景的。当工作负载规模较小、大部分是顺序执行、被不受支持的操作主导，或者需要频繁的主机-设备往返时，应保留 CPU 路径。

不要用固定的行数阈值作为判断依据。要针对用户的实际数据形状和硬件做基准测试。对于超出内存容量的数据(out-of-core data),要先估算峰值工作内存，并在分配之前选择分块处理、Dask,或流式设计方案。

### 3. 尝试破坏性最小的实现方式

1. 如果代码已经在使用某个 GPU 原生框架，就在该框架内部做优化。
2. 尝试加速器模式或后端分发模式(`cudf.pandas`、`cuml.accel`、`nx-cugraph`)。
3. 只有在加速器覆盖范围或性能不足时，才转向原生 GPU API。
4. 只有在性能分析显示某个操作没有合适的库实现时，才编写自定义内核。

在编写代码之前先阅读相应的库参考文档；即使名称兼容，默认值、数据类型、输出类型和支持的参数也可能不同。

### 4. 保持连贯的 GPU 数据路径

- 一次性传输输入，让中间结果常驻设备内存。
- 复用内存分配，并在语义允许的情况下优先使用 `out=` 或原地(in-place)形式。
- 批处理小规模操作；在能消除中间数组的情况下融合逐元素运算。
- 只有在性能分析显示传输重叠确实重要时，才使用锁页(pinned)主机内存和非默认流(stream)。
- 只有在约定允许的情况下，才选择 `float32`、混合精度，或降低精度的存储方式。

### 5. 先验证语义，再关注速度

- 在小规模的确定性测试用例和有代表性的数据上，比较 CPU 和 GPU 的输出。
- 对浮点结果使用明确的容差，并测试边界情况、NaN、顺序和数据类型。
- 对于近似最近邻索引，要报告相对于精确搜索的 recall@k;不要把精确的 CPU 算法和近似的 GPU 算法当作等价物来比较。
- 检查加速器发出的警告和日志，留意是否回退到了 CPU。

### 6. 正确地对 GPU 代码做基准测试

GPU 的工作是异步的，所以在一个未同步的调用外面套一个 CPU 计时器，测到的只是入队(enqueue)时间。先预热上下文创建和 JIT 编译，然后使用 CUDA 事件或具备库感知能力的计时器:

```python
from cupyx.profiler import benchmark

print(benchmark(gpu_function, (arg1, arg2), n_warmup=10, n_repeat=100))
```

在 notebook 中使用 `%gpu_timeit`,用 Nsight Systems(`nsys`)查看端到端时间线，用 Nsight Compute(`ncu`)做内核层面的分析。既要报告同步后的内核/区域耗时，也要报告实际的端到端延迟；如果生产环境需要承担传输和转换开销，应把这部分也计入。

### 7. 保留、修改，或放弃这次移植

只有当 GPU 路径通过了正确性检查、并且在有代表性的数据上改善了用户关心的那个指标时，才保留它。如果没有改善，要说明限制因素是问题规模、传输开销、不受支持的回退、内存压力、启动粒度，还是算法本身。

## 重要说明

- 当应用需要可移植性时，提供一个 CPU 回退方案；否则应及早失败，并给出清晰的硬件和依赖错误信息。
- 对照 CPU 结果测试数值正确性(由于运算顺序的不同,GPU 浮点结果可能存在细微差异)。
- GPU 内存是有限的——对于超出 GPU 内存容量的数据集，考虑分块处理，或使用支持多 GPU 的 RAPIDS Dask。
- 对于受支持的零拷贝互操作，优先使用 CUDA Array Interface 或 DLPack,但要核实设备、数据类型、连续性、所有权和流语义，而不要假定每一次转换都是零成本的。

## 参考文件

在编写任何 GPU 优化代码之前，先阅读相应的参考文件:

| 文件 | 何时阅读 |
|------|-------------|
| `references/cupy.md` | 用户有 NumPy/SciPy 代码，或需要在 GPU 上做数组运算 |
| `references/numba.md` | 用户已有 Numba-CUDA 代码，或需要显式的 SIMT 内核；注意向 Numba-CUDA-MLIR 的迁移路径 |
| `references/cudf.md` | 用户有 pandas 代码，或需要在 GPU 上做 dataframe 操作 |
| `references/cuml.md` | 用户有 scikit-learn 代码，或需要在 GPU 上做机器学习训练/推理/预处理 |
| `references/cugraph.md` | 用户有 NetworkX 代码，或需要在 GPU 上做图分析 |
| `references/warp.md` | 用户需要用于仿真、空间计算、网格/体素查询、可微分编程或机器人学的 GPU 内核；高层物理引擎请使用 Newton |
| `references/kvikio.md` | 用户需要面向/来自 GPU 的高性能文件 IO、GPUDirect Storage、把 S3/HTTP 读入 GPU,或在 GPU 上处理 Zarr |
| `references/cuxfilter.md` | 用户在维护或明确要求使用 cuxfilter(已停止更新——26.06 是最终发布版本) |
| `references/cucim.md` | 用户有 scikit-image 代码，或需要图像处理、数字病理学，或在 GPU 上读取 WSI |
| `references/cuvs.md` | 用户需要在 GPU 上做向量搜索、最近邻搜索、相似性搜索，或 RAG 检索 |
| `references/cuspatial.md` | 用户在维护或明确要求使用 cuSpatial(已归档——冻结在 25.04 版本，与当前 RAPIDS 相隔离) |
| `references/raft.md` | 用户需要稀疏特征值求解器、设备内存管理，或多 GPU 基元 |

在编写代码之前先阅读对应的参考文档——它们包含针对每个库的详细 API 模式、优化技巧和常见陷阱。
