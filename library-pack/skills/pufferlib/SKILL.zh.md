# PufferLib

使用 PufferLib 时，请明确指定版本档位（version profile）。上游目前存在两个互不兼容的接口面：

| 档位（Profile） | 截至 2026-07-23 的状态 | 主要用途 |
|---|---|---|
| `pufferlib==3.0.0` | PyPI 上最新的稳定发布版，发布于 2025-06-23 | Python/Gymnasium/PettingZoo 模拟层、`pufferlib.vector`、基于 Torch 的 PuffeRL |
| 源码 `4.0` | 上游默认分支；并非最新的稳定 PyPI 制品 | 原生 C 编写的 Ocean 环境、原生 CUDA 训练器、可选的 Torch 回退方案 |

不要将 3.0 的 import 语句与 4.0 的配置/CLI 示例混用。4.0 重新设计移除了当前代码树中原有的 3.0 版 `emulation`、`vector` 和 `pytorch` 模块。

## 安全默认设置

1. 从内置的合成数据、纯 CPU、无网络的工具开始。
2. 不要通过任意的点号路径（dotted path）导入某个环境。内置工具只接受白名单中的内置环境及 slug 标识符。
3. 不要安装或执行未经审查的环境包、原生扩展、ROM、地图（map）、检查点（checkpoint）或 pickle 文件。
4. 核实官方来源、不可变的版本号（revision）、许可证、校验和或证明（attestation），以及构建钩子（build hooks）。将原生构建及首次执行放在沙箱中进行。
5. 对步数、环境数、智能体数、工作进程（worker）数、线程数、缓冲区、内存、磁盘、渲染尺寸及墙钟时间（wall time）设定上限。
6. 使训练环境/随机种子与评估环境/随机种子相互隔离。
7. 日志记录默认设为本地或关闭。使用外部日志记录需要明确的选择加入（opt-in）、披露确认，以及单独的产物上传批准。
8. 绝不通过 CLI、INI、JSON、标签（tag）、运行名称或日志记录器配置传递 W&B 或 Neptune 的凭证。也绝不打印这些凭证。
9. 绝不导出全部环境变量，也绝不递归搜索 `.env` 文件。
10. 在受信任的沙箱加载之前，先对检查点字节内容进行哈希核验；元数据检查并不能证明其安全性。

## 首批本地检查

所有内置的 CLI 都是无依赖的，并输出严格的 JSON：

```bash
python3 scripts/env_template.py --help
python3 scripts/env_contract_validator.py
python3 scripts/benchmark_vectorization.py --backend serial
python3 scripts/train_template.py
python3 scripts/validate_plan.py
python3 scripts/repro_plan.py
```

默认设置为：合成数据、确定性、有边界限制、本地、仅 CPU、无网络，并且在原本会触发训练的地方改为空跑（dry-run）。

## 安装与来源溯源

### 已发布的 3.0.0

PyPI 上只提供 `pufferlib-3.0.0.tar.gz`：

```text
sha256: 7df3a3e3f5f894d78d2a1f5374097890aec01473183e748abefe4f3faa10eaa9
Requires-Python: >=3.9
```

在完成源码/构建审查之后，创建一个版本固定的 uv 项目：

```bash
uv venv --python 3.11
uv add --exact --no-sync "pufferlib==3.0.0"
uv lock
uv sync --frozen
```

提交 `pyproject.toml` 与 `uv.lock`；核实归档文件的摘要值以及每一个已解析的依赖项。源码构建过程可能会编译原生代码并拉取构建所需资源，因此应在没有凭证、没有敏感挂载点的沙箱中进行依赖解析/构建。上传的元数据并未固定 Torch 或 CUDA 版本；不要声称支持某个 PyPI 未曾声明的 CUDA 版本矩阵。

### 当前的 4.0 源码

截至 2026-07-23，经过审查的分支头部提交为：

```text
25647630e1b15330bb3153a5a0d3ff8d234c3acf
```

请固定到这个具体的提交（commit），而不是 `4.0` 分支：

```bash
uv add --no-sync \
  "pufferlib @ git+https://github.com/PufferAI/PufferLib.git@25647630e1b15330bb3153a5a0d3ff8d234c3acf"
uv lock
```

当前的软件包声明要求 Python `>=3.10` 以及 Torch `>=2.9`。上游的 PufferTank 目前使用 Ubuntu 24.04、Python 3.12，以及配合 `cu130` Torch 索引的 NVIDIA CUDA 13.0.2/cuDNN 开发镜像，但并未固定具体的 Torch wheel 版本或全部系统软件包。请将其视为一份参考资料，而非完整的锁定清单。绝不要直接通过管道（pipe）执行一个远程安装脚本。

在进行任何安装或构建之前，先阅读 `references/training.md`。

## 环境工作流

### 1. 校验契约（contract）

Gymnasium 的 reset 返回 `(observation, info)`。step 返回：

```python
(observation, reward, terminated, truncated, info)
```

校验空间（space）、形状（shape）、数据类型（dtype）、有限的奖励值、布尔值、"先 reset 再 step"、"结束后再 reset"、随机种子设置，以及清理逻辑。`terminated` 表示 MDP（马尔可夫决策过程）意义上的终止；`truncated` 表示一种外部截断，例如时间限制。为了正确进行自举（bootstrapping）计算及指标统计，应保留这两者之间的区别。

```bash
python3 scripts/env_contract_validator.py \
  --steps 64 --episodes 8 --seed 42
```

### 2. 只有在审查之后才进行适配

已发布的 3.0 版本使用显式的包装器（wrapper）：

```python
import pufferlib.emulation

wrapped = pufferlib.emulation.GymnasiumPufferEnv(reviewed_gymnasium_instance)
```

对于一个经过审查的 PettingZoo Parallel 环境：

```python
wrapped = pufferlib.emulation.PettingZooPufferEnv(reviewed_parallel_instance)
```

3.0 版本中不存在与旧版技能对应的、受支持的 `pufferlib.emulate(...)` 快捷方式。请阅读 `references/environments.md` 与 `references/integration.md`。

### 3. 原生环境

已发布的 3.0 版 `PufferEnv` 要求在调用 `super().__init__(buf)` 之前先设置好 `single_observation_space`、`single_action_space` 及 `num_agents`。它使用原地（in-place）向量缓冲区，并返回各自独立的终止（terminal）/截断（truncation）数组，以及一份信息字典（info dictionaries）列表。

当前的 4.0 版本使用 C 语言绑定。请从上游的 `ocean/squared`（单智能体）或 `ocean/target`（多智能体）入手，先在本地/经过消毒处理的模式下构建一个环境，并在进行任何优化之前，核实每一个缓冲区的大小/类型/索引是否正确。

## 向量化工作流

已发布的 3.0：

```python
import pufferlib.vector

vecenv = pufferlib.vector.make(
    reviewed_creator,
    backend=pufferlib.vector.Serial,
    num_envs=4,
    seed=42,
)
```

只有在串行（serial）方式下的运行结果通过验证之后，才切换到 `Multiprocessing`。记录 `num_envs`、`num_workers`、`batch_size`、零拷贝（zero-copy）模式、启动方式（start method）、智能体数量、掩码（mask），以及实际返回的各个形状。对于多智能体环境，批次长度（batch length）取决于智能体槽位数量，而不一定等于 `num_envs`。

当前的 4.0 版本改用如下配置方式：

```ini
[vec]
total_agents = 4096
num_buffers = 2
num_threads = 16
```

请阅读 `references/vectorization.md`。对固定的工作负载进行基准测试时，要先预热（warmup），并至少重复三次；分别报告仿真本身的 SPS（每秒步数）与端到端训练的 SPS。内置的基准测试工具只测量其自带的合成测试套件。

## 策略（Policy）工作流

已发布的 3.0 版策略是根据 `single_observation_space`/`single_action_space` 确定尺寸的 Torch 模块。稳定的循环网络组合方式使用 `encode_observations` 与 `decode_actions`；结构化模拟层则使用 `pufferlib.pytorch.nativize_dtype` 与 `nativize_tensor`。

当前 4.0 版本的 Torch 回退方案采用如下组合方式：

```python
pufferlib.models.Policy(encoder=encoder, decoder=decoder, network=network)
```

它提供 MLP、MinGRU、LSTM 及 GRU 这几种网络选择；`--slowly` 用于选择这套回退方案，而非原生后端。请检查输出/状态的形状、掩码、数值是否有限、梯度情况，以及即时执行（eager）与编译（compiled）模式下行为的差异。参见 `references/policies.md`。

## 训练与评估

已发布的 3.0 版训练器的导入方式：

```python
from pufferlib import pufferl

trainer = pufferl.PuffeRL(train_config, vecenv, policy)
```

当前的 4.0 版 CLI：

```bash
puffer train ENV_NAME
puffer eval ENV_NAME --load-model-path EXACT_TRUSTED_PATH
puffer sweep ENV_NAME
```

默认应生成一份计划（plan），而不是直接启动运行：

```bash
python3 scripts/train_template.py \
  --profile pypi-3.0.0 \
  --environment synthetic \
  --device cpu \
  --total-timesteps 10000
```

校验一份自定义的严格 JSON 计划：

```bash
python3 scripts/validate_plan.py --root . --config plan.json
```

该 schema 会拒绝包含密钥的键、无边界限制的资源设置、点号形式的环境路径、无效的向量可整除性设置、混用不同版本的选项，以及训练/评估共用同一随机种子的情况。参见 `references/training.md`。

## 日志记录

PufferLib 3.0 提供 W&B 与 Neptune 支持；当前的 4.0 版 CLI 提供 W&B 支持。二者都是可选的外部服务。它们可能会传输配置信息、指标、源码元数据、硬件遥测数据、输出结果以及经批准的产物，这会带来隐私、数据留存、访问控制及成本方面的影响。

- W&B 凭证：具名的环境变量 `WANDB_API_KEY`。
- Neptune 凭证：具名的环境变量 `NEPTUNE_API_TOKEN`。
- 绝不要把这些值放进参数/配置/日志中。
- 在记录日志之前先对配置键进行脱敏处理。
- 除非明确获得批准，否则不要开启源码/模型上传功能。

规划器（planner）要求同时提供以下两项：

```bash
python3 scripts/train_template.py \
  --logger wandb \
  --enable-external-logging \
  --acknowledge-external-disclosure
```

它只会报告所需的变量名称，绝不会读取该变量的值。

## 检查点（Checkpoint）工作流

PufferLib 3.0 以及 4.0 的 Torch 回退方案使用 Torch 的序列化机制；当前原生的 4.0 版本写出的是不透明的 `.bin` 权重文件。PyTorch 官方警告称，不受信任的模型本质上是程序，且 `torch.load` 使用了反序列化（unpickling）机制。

```bash
python3 scripts/inspect_checkpoint.py checkpoint.pt \
  --root . \
  --expected-sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

该检查工具只进行哈希计算与分类，不会调用 `torch.load`，不会导入 pickle/Torch 模块，也不会检查归档条目或解压文件。在进行任何沙箱加载之前，请核实来源、许可证、架构、环境版本、附属元数据以及校验和。在可复现的评估中，绝不要使用 `latest` 这样的版本标识。

## 内置文件

### 脚本（Scripts）

- `scripts/env_template.py` —— 确定性的合成 Gymnasium 风格模板。
- `scripts/env_contract_validator.py` —— 有边界限制的契约与随机种子检查。
- `scripts/benchmark_vectorization.py` —— 设有上限的串行/spawn 合成基准测试。
- `scripts/train_template.py` —— 不执行实际训练的 3.0/4.0 训练计划生成器。
- `scripts/validate_plan.py` —— 严格的配置/资源/安全性校验器。
- `scripts/inspect_checkpoint.py` —— 不进行反序列化的元数据/哈希检查工具。
- `scripts/repro_plan.py` —— 训练/评估随机种子分离的评估及基准测试计划。

### 参考资料（References）

- `references/environments.md` —— Gymnasium、稳定版 PufferEnv、模拟层、原生 C 实现。
- `references/vectorization.md` —— 后端、形状、启动方式、基准测试。
- `references/policies.md` —— 稳定版/当前版策略契约以及状态安全性。
- `references/training.md` —— 安装、配置、CLI、PuffeRL、评估、日志、检查点。
- `references/integration.md` —— 迁移对照表、第三方及凭证安全性。

## 带日期的上游来源

- [PyPI pufferlib 3.0.0](https://pypi.org/project/pufferlib/3.0.0/) —— 发布于 2025-06-23；核查于 2026-07-23。
- [PyPI 3.0.0 metadata](https://pypi.org/pypi/pufferlib/3.0.0/json) —— 摘要值/依赖项；核查于 2026-07-23。
- [PufferLib official docs](https://puffer.ai/docs.html) —— 当前 4.0 版官方文档；核查于 2026-07-23。
- [PufferLib source](https://github.com/PufferAI/PufferLib) —— 默认分支及实现代码；核查于 2026-07-23。
- [PufferTank 4.0 Dockerfile](https://github.com/PufferAI/PufferTank/blob/4.0/puffertank.dockerfile) —— CUDA/Python 参考配置；核查于 2026-07-23。
- [PufferLib 2.0 paper](https://openreview.net/forum?id=qRyteMTgn0) —— Reinforcement Learning Journal，2025 年；仅用于其所述的相关基准测试结果。
- [PufferLib compatibility paper](https://arxiv.org/abs/2406.12905) —— 提交于 2024-06-18；描述的是更早期的 API/性能档位。
