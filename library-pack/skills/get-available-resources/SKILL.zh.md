# Get Available Resources(获取可用资源)

为**当前进程**建立一幅保守的可用资源图景。
把主机库存(host inventory)、进程亲和性(process affinity)、cgroup/容器限制、
调度器分配以及加速器运行时可用性分开对待。

## 安全约定

遵循以下规则:

- 只在用户提出请求，或某个特定工作负载确实需要资源规划时运行检测。
  不要为每一个科学计算任务都持久化一份指纹信息。
- 默认使用 stdout。只有当用户选择了一个明确的通用本地文件名时，才持久化保存。
- 不要运行压力测试、基准测试、大规模内存分配、写入探测、设备重置、
  驱动安装，或时钟/功耗方面的更改。
- 不要转储整个环境变量。只读取检测器所实现的、指定名称的 Slurm 和加速器
  相关变量。
- 不要报告主机名、绝对路径、cgroup 路径、作业 ID、设备 UUID、
  PCI 地址，或原始的可见性变量取值。
- 把缺失的观测值当作「未知」处理。绝不要把「未知」转换为「无限制」。
- 绝不要推断出:在某个调度器分配或容器内部，一个可见的主机 CPU、
  内存池或 GPU 就是可用的。

打包的检测器只使用固定的可执行文件/参数元组，不使用 shell,
使用较短的超时时间，对 stdout/stderr 做有边界的截断，并对部分失败发出警告。

## 快速开始

从本技能所在目录运行。

### 一次性的 stdout 快照

```bash
python scripts/detect_resources.py
```

该命令只向 stdout 输出 JSON。只有在普通 shell 权限可接受的情况下,
才对其进行重定向。

### 显式的私有文件

```bash
python scripts/detect_resources.py --output resource-snapshot.json
```

显式输出被限制为当前目录下一个 `.json` 文件名，使用私有权限,
拒绝符号链接和路径穿越，并且除非提供了 `--force`,否则拒绝覆盖已有文件。

### 可选的 psutil 增强

标准库检测器无需安装任何依赖即可工作。若需要更广泛的跨平台
物理核心数、亲和性、可用内存、交换分区和磁盘覆盖信息:

```bash
uv pip install "psutil==7.2.2"
```

该导入是惰性的。psutil 导入失败只会产生一条警告，而不是致命错误。

### 跳过管理工具探测

```bash
python scripts/detect_resources.py --skip-accelerators
```

当加速器发现过程的延迟不可取时，使用此选项。检测器仍会汇总
白名单可见性变量的存在情况与状态，但不返回它们的取值。

## 必要的解读方式

### CPU

把以下几项当作不同的事实来看待:

- `cpu.host.logical`:系统可见的调度单元数。
- `cpu.host.physical`:物理拓扑结构，或为 null;绝不从逻辑核心数推断而来。
- `cpu.process.affinity_logical`:在受支持的情况下，当前的亲和性集合大小。
- `cpu.cgroup_v2.cpuset_logical`:有效的 cgroup cpuset 大小。
- `cpu.cgroup_v2.quota_cores`:有限的 `cpu.max` 容量，可能是小数。
- `scheduler.allocation.cpu_per_process`:在范围明确时，对 Slurm
  每任务分配的有边界解读。
- `cpu.effective.capacity_cores`:观测到的最小正约束值。
- `cpu.effective.worker_ceiling`:CPU 进程工作者数量的保守下限。

配额(quota)为 1.5 指的是 CPU 时间容量，而不是 1.5 个物理核心。
亲和性和 cpuset 约束的是放置位置；配额约束的是带宽。

### 内存

把以下几项分开对待:

- 主机总内存/可用内存;
- 当前 cgroup 用量、硬性的 `memory.max`,以及剩余的层级容量;
- `memory.high`,这是一个压力/节流边界，而非硬性上限;
- 调度器的内存分配及其作用范围；以及
- 保守的有效硬性限制和可用内存估计值。

在 Apple 芯片上,`memory.model` 为 `unified_cpu_gpu`。不要把集成 GPU 的
内存加到 RAM 中，也不要把它描述为独立的显存(VRAM)。

### 加速器

每个设备都是一个后端**候选项(candidate)**:

- NVIDIA GPU → CUDA 候选项;
- AMD GPU → ROCm 候选项;
- Apple 集成 GPU → Metal 候选项。

管理查询层面的可见性并不能确立以下任何一项:

1. 调度器/容器权限;
2. 设备节点访问权限;
3. 驱动/运行时兼容性;
4. 框架软件包兼容性；或
5. 算子/数据类型支持情况。

因此 `runtime_usable_devices` 始终保持为 null,每个设备的
`runtime_compatibility` 字段都标注为 `not_tested`。可见性/分配计数
只是上限，而非保证。

### 磁盘

`capacity_bytes`(容量)、文件系统的 `free_bytes`(空闲空间)、
用户可用的块数，以及一次非写入式的权限检查，这些都是彼此独立的概念。
文件系统或项目配额仍可能比它们更严格。绝对工作路径始终会被脱敏处理。

### 调度器与容器

Slurm 变量描述的是分配范围，但实际的强制执行取决于站点配置,
例如任务亲和性或 cgroup。优先把亲和性和 cgroup 观测结果作为
强制执行的证据。

容器标记用于识别上下文;cgroup 控制用于识别限制。一个没有有限
cgroup 取值的容器，仍然可能看到主机层面的库存；而一个非 root 的
cgroup 也不会被自动标记为容器。

详细的平台规则见
[`references/resource_semantics.md`](references/resource_semantics.md)。

## 规划一个工作负载

规划器接收一份经过校验的快照，自身不执行任何实际工作:

```bash
python scripts/plan_workload.py resource-snapshot.json \
  --workload cpu \
  --tasks 100 \
  --memory-per-worker-mib 2048
```

可选控制项:

- `--workers N`:显式的上限值。
- `--reserve-memory-mib N`:保留在工作者预算之外的内存。
- `--workload cpu|mixed|io`:选择一种有边界的工作者启发式策略。
- `--accelerator none|any|cuda|rocm|metal`:请求给出候选后端的判断,
  但不声称其实际可用。
- `--output plan.json`:显式的私有本地输出；默认是 stdout。

对于 CPU 或混合型工作负载，请把 `suggested_workers` 和
`threads_per_worker` 结合起来使用。进程工作者数量乘以 BLAS/OpenMP
原生线程数，可能导致分配超额(oversubscribe)。

I/O 规划允许有边界的超额分配(最多 32),但会将其标注为一种启发式
估计。只对真实的代表性工作负载做基准测试，并保持在调度器/容器
限制之内。

## 校验或对比快照

校验:

```bash
python scripts/snapshot_tools.py validate resource-snapshot.json
```

在忽略 `observed_at` 的情况下对比资源状态:

```bash
python scripts/snapshot_tools.py diff before.json after.json
```

使用 `--include-volatile` 以包含时间戳。输入必须是常规的、非符号链接的
JSON 文件，大小不超过 1 MiB。对比结果是有边界的。

schema 结构以及 null/零值的含义记录在
[`references/snapshot_schema.md`](references/snapshot_schema.md) 中。

## 可选的加速器诊断计划

生成一份计划，但不执行任何诊断操作:

```bash
python scripts/accelerator_diagnostics.py resource-snapshot.json \
  --backend auto
```

结果中包含固定的、只读的管理查询参数列表，以及针对可见性、权限
和运行时兼容性分别设置的判定关口(gate)。只在将要真正执行该工作负载
的确切环境中，运行框架官方的可用性检查。不要自动安装或改动驱动程序。

## 部分失败与溯源信息

一次探测失败不应抹去已成功获取的观测结果。检查:

- `completeness`(完整性);
- 带有稳定代码、经过排序的 `warnings`(警告);
- 带有来源/状态记录、经过排序的 `provenance`(溯源信息);以及
- 为 null 的字段。

子进程的 stderr 和原始异常文本不会被复制进快照中，因为它们
可能包含标识符或路径信息。

## 各平台说明

- **Linux**: 只读取有边界的 `/proc` 文件和 cgroup v2 文件。
  会考虑祖先层级(ancestor)的 CPU 和内存限制。
- **macOS**: 使用固定的 `sysctl` 键，以及一次有边界的
  `system_profiler SPDisplaysDataType -json` 查询。Apple 芯片的内存是统一的。
- **Windows**: 可选的 psutil 能改善物理核心数、亲和性、可用内存
  和交换分区方面的观测结果。处理器组(processor-group)的作用范围
  可能导致主机计数与进程计数不一致。
- **Slurm**: 只读取一份白名单中的分配变量。绝不会输出作业、
  节点、提交主机、GPU ID 或路径相关的值。
- **NVIDIA/AMD**: 管理类 CLI 是可选的。它们缺失属于正常情况;
  超时、截断、解析失败以及运行时不确定性都会被明确标注出来。

## 打包的文件

- `scripts/detect_resources.py` —— 经过脱敏处理的快照采集器。
- `scripts/plan_workload.py` —— 确定性的工作者/内存规划器。
- `scripts/snapshot_tools.py` —— schema 校验器与有边界的结构化对比工具。
- `scripts/accelerator_diagnostics.py` —— 不执行任何操作的只读诊断计划生成器。
- 仓库根目录下的 `tests/get-available-resources/` —— 不依赖网络的
  Linux、macOS、Windows、cgroup、Slurm 及加速器测试用例。
- `references/resource_semantics.md` —— 解读方式与各平台细节。
- `references/snapshot_schema.md` —— schema 1.1 契约。
- `references/sources.md` —— 带日期标注的官方来源台账。

官方文档最近一次更新于 **2026-07-23**;在更改语义或依赖版本锁定之前,
请查阅
[`references/sources.md`](references/sources.md)。
