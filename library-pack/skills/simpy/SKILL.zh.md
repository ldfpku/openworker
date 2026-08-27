# SimPy

## 适用范围

将本技能用于基于过程（process-based）的离散事件模型，其中活跃的实体产出
事件并争用资源：队列、生产系统、物流、网络、服务运营、库存，以及其他
事件驱动的系统。

SimPy 提供了一个事件调度器和建模原语。它**不会**为你选择一个在科学上
有效的概念模型、输入分布、预热期（warm-up）、运行时长、重复次数
（replication count）、估计目标（estimand）,或因果解释。应把这些视为
仿真研究方法论，而不是 SimPy 的 API 行为。

## 当前发行版与安装

于 **2026-07-23** 核实：

- 最新稳定版：**SimPy 4.1.2**，于 2026-05-24 发布到 PyPI；源代码标签
  `4.1.2` 指向提交 `f4381649`。
- 包元数据要求 Python **>=3.8**，并将 CPython 3.8-3.14 以及 PyPy 列为
  受支持分类。SimPy 没有运行时依赖。
- 4.1.2 增加了对 Python 3.13/3.14 的支持，以及针对现代解释器的测试修复。
- 上游项目与本技能均采用 MIT 许可证。

创建一个可复现的环境：

```bash
uv venv --python 3.13
source .venv/bin/activate
uv pip install "simpy==4.1.2"
python -c "import importlib.metadata; print(importlib.metadata.version('simpy'))"
```

不要悄悄地用 `latest`（最新）文档构建版本来替代：它可能描述的是一个
尚未发布的开发版本。请使用 `references/sources.md` 中带版本号的
4.1.2 链接。

## 建模工作流

1. **定义目的和估计目标（estimand）**。 陈述所要回答的决策/问题、系统
   边界、实体、资源、状态、输出、时间单位，以及终止事件或稳态目标。
2. **先写出概念模型**。 记录假设、分布、路由（routing）、优先级、初始
   条件，以及被省略的机制。
3. **实现生成器（generator）**。 一个 SimPy 进程（process）就是一个产出
   事件的 Python 生成器。用 `env.process(...)` 注册该生成器对象。
4. **限定执行范围**。 为每一次生产运行都设定明确的时间、实体数、事件数,
   以及重复次数上限。绝不要在包含永不停止的进程的模型上调用
   `env.run()`。
5. **分离随机流**。 对逻辑上不同的随机源使用各自独立的 RNG 实例；保留
   一份随机种子清单。
6. **有意识地布置监测点**。 在感兴趣的状态转换发生之后进行观测，在
   分析时间范围（horizon）处闭合按时间加权的区间，并测试监测本身没有
   改变事件顺序。
7. **验证与确认**。 测试确定性的边界情形、守恒恒等式（conservation
   identity）、轨迹、排队规则，以及解析基准；针对陈述的目的，与系统
   证据或专家证据做对比。
8. **运行独立的重复实验**。 基于重复实验层面的估计值来构造区间估计,
   而不是基于同一次运行内相关的实体。
9. **报告局限性**。 包括初始化、未完成的实体、运行时长、随机种子/
   随机流、精度、敏感性，以及验证证据。绝不要把仿真中的关联关系
   转化为因果性结论。

在做出推断性结论之前，请阅读 `references/simulation-methodology.md`。

## 最简的有边界模型

```python
import random
import simpy

HORIZON = 480.0
arrival_rng = random.Random(101)
service_rng = random.Random(202)
env = simpy.Environment()
server = simpy.Resource(env, capacity=2)
completed = []

def customer(arrival):
    with server.request() as request:
        yield request
        wait = env.now - arrival
        yield env.timeout(service_rng.expovariate(1 / 6.0))
    completed.append((env.now, wait))

def arrivals():
    for _ in range(10_000):  # Entity cap.
        delay = arrival_rng.expovariate(1 / 4.0)
        if env.now + delay >= HORIZON:
            return
        yield env.timeout(delay)
        env.process(customer(env.now))

env.process(arrivals())
env.run(until=HORIZON)
```

这个数值型的时间范围（horizon）是半开区间：恰好被安排在 `480.0` 时刻
的普通事件不会被处理。应报告未完成的实体，而不是悄悄地把它们当作已
完成的观测值处理。

## 核心语义

### Environment 与确定性排序

`Environment` 是单线程的。队列按仿真时间、事件优先级，然后是严格递增
的事件 ID 排序。因此，同一时间、同一优先级的事件会按照被调度的先后
顺序以 FIFO 方式处理。模型中的进程可以表示并发性，但回调函数是按顺序
且确定性地执行的。

- `env.now`：无单位的仿真时钟；需自行选定并记录一个单位。
- `env.peek()`：下一个事件的发生时间，或无穷大。
- `env.step()`：处理一个事件；队列为空时抛出 `EmptySchedule`。
- `env.active_process`：当前正在执行的进程，否则为 `None`。
- `env.run()`：清空队列；用在包含周期性或永不停止的进程的模型上是
  不安全的。

`env.run(until=number)` 与 `env.run(until=event)` 在边界处理上并不
可以互换：

- 传入一个数值会安排一个紧急停止事件，并排除恰好发生在该时刻的普通
  事件。
- 传入一个 Event 判据（criterion）时，会在其停止回调触发时返回该事件的
  值。同一时刻的其他事件的顺序取决于优先级和调度顺序。
- 在 4.1.2 中，`Environment.step()` 会通过重新调度目标事件来保留
  `StopSimulation` 之后仍剩余的回调。因此，在 `env.run(until=target)`
  之后，即便 `target` 的值已经被返回,`target.processed` 仍可能保持
  `False`，直到再多调用一次 `step()`/`run()`。不要把 `processed` 当作
  判断运行是否结束的唯一测试标准。

参见 `references/events.md` 与 `references/monitoring.md`。

### Event、Timeout、Process 与 Condition

- 一个 `Event` 只会依次经历「未触发（not-triggered）→ 已触发/已调度
  （triggered/scheduled）→ 已处理（processed）」这几个状态。
  `succeed(value)` 或 `fail(exception)` 只会触发它一次。
- 一个 `Timeout` 在被创建时就触发，被安排在 `now + delay` 处发生，且
  不能再次被手动触发成功。
- `env.process(generator)` 创建一个 `Process`；该生成器会以被 yield 的
  事件的值恢复执行。从生成器中返回，会用该返回值使这个 Process 成功
  完成。未被捕获的异常会使它失败。
- `AnyOf` / `a | b` 和 `AllOf` / `a & b` 会 yield 出一个
  `ConditionValue`：一个有序的、类似字典的映射，从**事件对象**映射到
  它们各自的值。要用原始的事件对象来测试成员关系；不要假定结果是一个
  标量。
- `AnyOf` 不会取消落败的那些事件。当放弃一个仍处于挂起状态的资源请求
  时，应显式地取消它；普通的超时（timeout）事件仍会保持已调度状态。

### 中断（Interrupt）

`process.interrupt(cause)` 会安排一个紧急中断，把 `simpy.Interrupt`
抛入目标生成器中。要在可能被中断的那段被 yield 的工作外围捕获它，检查
`interrupt.cause`，更新剩余的工作量，然后选择恢复执行、重新 yield
原始事件，或终止。

中断一个进程，会把它当前恢复回调从其当前所等待的目标事件上移除；这
并不会取消那个目标事件本身。一个进程不能中断它自己，也不能中断一个
已经终止的进程。参见 `references/process-interaction.md`。

## 共享资源

| 类型 | 语义 |
|---|---|
| `Resource` | 类似 FIFO 信号量的使用槽位 |
| `PriorityResource` | 排队请求按较小的数值优先级优先排序 |
| `PreemptiveResource` | 优先级队列，外加对当前使用者的可选抢占 |
| `Container` | 同质数值型液位/存量；`put`/`get` 会等待容量/物料 |
| `Store` | FIFO 的 Python 对象 |
| `FilterStore` | 满足请求所给谓词的第一个可用条目 |
| `PriorityStore` | 按优先级顺序返回的可比较条目 |

使用一个请求的上下文管理器：

```python
def job(env, resource):
    with resource.request() as request:
        yield request
        yield env.timeout(3)
```

退出时，它会释放一个已获取的请求，或取消一个仍处于挂起状态的请求，
异常展开（exception unwinding）过程中也是如此。对于手动持有、仍处于
挂起状态的 `put`/`get`/请求，如果某次中断或超时使得进程放弃了它，
应调用 `cancel()`。

`PreemptiveResource.request(priority=..., preempt=True)` 使用较小的
数字表示较高的优先级。被抢占的进程会收到一个 `Interrupt`，其 cause 是
一个 `Preempted` 对象：`cause.by` 是实施抢占的那个 Process,
`cause.usage_since` 是使用开始的时间，`cause.resource` 是该资源本身。
排队优先级优先于 `preempt` 标志；混用抢占式和非抢占式请求需要有明确
的测试。

阻塞操作、排队规则和示例参见 `references/resources.md`。

## 监测与单步执行

优先在状态转换发生时进行显式的、面向领域的观测。对于通用的资源监测，
包装器（wrapper）或子类可以检查 `count`、`queue`、`level`、`items`、
`put_queue` 和 `get_queue`。对于事件追踪，`schedule()` 和 `step()` 是
核心钩子（hook）。

排队相关的度量对时机很敏感：

- 一个请求方法调用之前的状态、调用之后的状态、授权（grant）回调，以及
  释放（release）回调，都可能在同一个仿真时间戳上各不相同。
- 样本均值是按事件观测次数加权的，而不是按时间加权的。要计算左连续
  状态路径下方的面积，再除以经过的时间。
- 添加初始样本和最终样本；在分析的时间范围（horizon）处闭合最后一个
  区间。
- `env._queue`、资源的 `_env`,以及猴子补丁（monkey-patching）都属于
  实现细节。请固定 SimPy 版本、把插桩（instrumentation）代码隔离开来，
  并在升级后做回归测试。
- 追踪每一个事件都会改变运行时间和内存占用；要对追踪记录设置上限。

请使用 `scripts/resource_monitor.py` 以及 `references/monitoring.md`。

## 实时执行

`simpy.rt.RealtimeEnvironment(initial_time=0, factor=1.0, strict=True)`
把一个仿真时间单位映射到 `factor` 个挂钟秒（wall-clock second）。在
严格模式下，当计算落后于实时进度时，`step()`/`run()` 会抛出
`RuntimeError`。`strict=False` 会容忍这种延迟；但它并不能恢复计时的
准确性。先用 `Environment` 开发逻辑，再另外运行带有充裕的、感知平台
差异的容差的独立计时测试。参见 `references/real-time.md`。

## 内置的安全 CLI 工具

所有 CLI 工具要么使用一个固定的内置队列模型，要么对本地产物做汇总。
它们会拒绝未知的 JSON 键、URL、符号链接、非有限数值、超大输入，以及
不设边界的时间/事件/实体/重复次数。它们绝不会对配置文本求值、执行
用户提供的 Python 代码、导入插件，或调用任何网络服务。

```bash
# 查看所有选项。
python skills/simpy/scripts/bounded_queue_scenario.py --help
python skills/simpy/scripts/replication_runner.py --help
python skills/simpy/scripts/event_trace_summary.py --help
python skills/simpy/scripts/validate_simulation_config.py --help

# 确定性的内置场景。
python skills/simpy/scripts/bounded_queue_scenario.py

# 带重复实验层面 Student-t 区间估计的独立重复实验。
python skills/simpy/scripts/replication_runner.py

# 仅做校验；不运行任何仿真。
python skills/simpy/scripts/validate_simulation_config.py config.json
```

重复实验运行器会拒绝对只有一次重复的结果构造区间估计。它给出的区间
是在所配置的模型之下量化蒙特卡洛不确定性的，既不能验证该模型，也不能
用于识别因果效应。参见 `references/cli-guide.md`。

## 测试

对排序、边界时刻、条件、中断、所有资源规则（discipline）、守恒性、
事件/实体上限、随机种子可复现性，以及监测器不产生干扰这些方面，使用
确定性的单元测试。只把随机性测试用作带有固定随机种子的、宽泛的分布
性检查；避免使用脆弱的精确样本估计值。

在精确锁定的环境中运行本技能的测试套件，且不生成字节码产物：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --isolated --no-project \
  --python 3.13 --with "simpy==4.1.2" \
  python -m unittest discover -s tests/simpy -v
```

## 参考资料

- `references/events.md` —— 调度器、生命周期、运行边界、条件
- `references/process-interaction.md` —— 生成器、共享事件、中断
- `references/resources.md` —— 所有 Resource、Container 和 Store 变体
- `references/monitoring.md` —— 按时间加权、排队计时、追踪、单步执行
- `references/real-time.md` —— factor（比例因子）、严格模式、漂移、计时测试
- `references/simulation-methodology.md` —— 重复实验、预热期、验证、置信区间
- `references/cli-guide.md` —— 模式（schema）、边界、输出，以及安全 CLI 示例
- `references/sources.md` —— 带日期的官方与主要方法学资料来源
