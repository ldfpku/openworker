# Stable Baselines3

## 概述

Stable Baselines3(SB3)是一个基于 PyTorch 的库，提供强化学习算法的可靠实现。本技能为训练强化学习智能体(agent)、创建自定义环境、实现回调(callback)以及使用 SB3 统一 API 优化训练工作流，提供了全面的指导。

**当前上游版本**： SB3 **2.8.0**(2026 年 4 月)。文档:[stable-baselines3.readthedocs.io](https://stable-baselines3.readthedocs.io/en/master/)。

## 安装

已针对 **stable-baselines3 2.8.0** 测试。要求 **Python 3.10+**(3.9 支持已在 2.8.0 中移除)和 **PyTorch >= 2.3**。

```bash
# 基础安装
uv pip install "stable-baselines3>=2.8"

# 附带额外依赖(TensorBoard、用于 Atari 的 ale-py 等)
uv pip install "stable-baselines3[extra]>=2.8"
```

在 zsh 中，方括号需要加引号:`uv pip install 'stable-baselines3[extra]>=2.8'`。

对于 MuJoCo 连续控制基准测试：

```bash
uv pip install "gymnasium[mujoco]"
```

检查你的版本：

```python
import stable_baselines3
print(stable_baselines3.__version__)
```

## 相关项目

- **[SB3-Contrib](https://github.com/Stable-Baselines-Team/stable-baselines3-contrib)**:实验性算法(MaskablePPO、CrossQ、QR-DQN、RecurrentPPO)——独立的 `sb3-contrib` 包
- **[RL Baselines3 Zoo](https://github.com/DLR-RM/rl-baselines3-zoo)**:预训练智能体、超参数、训练脚本
- **[SBX](https://github.com/araffin/sbx)**:面向偏好 JAX 而非 PyTorch 用户的 SB3 + JAX 实现

## 核心能力

### 1. 训练强化学习智能体

**基本训练模式**：

```python
import gymnasium as gym
from stable_baselines3 import PPO

# 创建环境
env = gym.make("CartPole-v1")

# 初始化智能体(对小型环境的 MlpPolicy 而言,device="cpu" 通常更快)
model = PPO("MlpPolicy", env, verbose=1)

# 训练智能体
model.learn(total_timesteps=10000)

# 保存模型
model.save("ppo_cartpole")

# 加载模型(无需事先实例化)
model = PPO.load("ppo_cartpole", env=env)
```

**重要说明**：
- `total_timesteps` 是一个下限；由于批量采集(batch collection)的存在，实际训练步数可能超过该值
- 应把 `model.load()` 当作静态方法使用，而不是在已有实例上调用
- 为节省空间，经验回放缓冲区(replay buffer)不会随模型一起保存

**算法选择**：
关于详细的算法特性和选型指导，参见 `references/algorithms.md`。快速参考：
- **PPO/A2C**:通用型，支持所有动作空间类型，适合多进程
- **SAC/TD3**:连续控制，离策略(off-policy),样本效率高
- **DQN**:离散动作，离策略
- **HER**:目标条件化任务

关于包含最佳实践的完整训练模板，参见 `scripts/train_rl_agent.py`。

### 2. 自定义环境

**要求**：
自定义环境必须继承自 `gymnasium.Env`,并实现：
- `__init__()`:定义 action_space 和 observation_space
- `reset(seed, options)`:返回初始观测值和 info 字典
- `step(action)`:返回观测值、奖励、terminated、truncated、info
- `render()`:可视化(可选)
- `close()`:清理资源

**关键约束**：
- 图像观测值必须是范围在 [0, 255] 内的 `np.uint8` 类型
- 尽可能使用通道优先(channel-first)格式(channels, height, width)
- SB3 会通过除以 255 自动对图像进行归一化
- 若数据已预先归一化，应在 policy_kwargs 中设置 `normalize_images=False`
- SB3 **不**支持 `start!=0` 的 `Discrete` 或 `MultiDiscrete` 空间

**验证**：
```python
from stable_baselines3.common.env_checker import check_env

check_env(env, warn=True)
```

关于完整的自定义环境模板，参见 `scripts/custom_env_template.py`;关于全面的指导，参见 `references/custom_environments.md`。

### 3. 向量化环境

**目的**：
向量化环境并行运行多个环境实例，从而加速训练，并支持某些封装器(帧堆叠、归一化等)。

**类型**：
- **DummyVecEnv**:在当前进程上顺序执行(适合轻量级环境)
- **SubprocVecEnv**:跨进程并行执行(适合计算密集型环境)

**快速设置**：
```python
from stable_baselines3.common.env_util import make_vec_env

# 创建 4 个并行环境
env = make_vec_env("CartPole-v1", n_envs=4, vec_env_cls=SubprocVecEnv)

model = PPO("MlpPolicy", env, verbose=1)
model.learn(total_timesteps=25000)
```

**离策略优化**：
当离策略算法(SAC、TD3、DQN)配合多个环境使用时，应设置 `gradient_steps=-1`,使每一步环境步进对应一次梯度更新，以平衡实际耗时与样本效率。

**API 差异**：
- `reset()` 只返回观测值(info 可通过 `vec_env.reset_infos` 获取)
- `step()` 返回一个 4 元组:`(obs, rewards, dones, infos)`,而不是 5 元组
- 环境会在每个 episode 结束后自动重置
- 终止时的观测值可通过 `infos[env_idx]["terminal_observation"]` 获取

关于封装器和进阶用法的详细信息，参见 `references/vectorized_envs.md`。

### 4. 用于监控与控制的回调（Callback）

**目的**：
回调可以在不修改核心算法的情况下，实现指标监控、检查点保存、提前停止以及自定义训练逻辑。

**常用回调**：
- **EvalCallback**:定期评估并保存最佳模型
- **CheckpointCallback**:按间隔保存模型检查点
- **StopTrainingOnRewardThreshold**:达到目标奖励时停止
- **ProgressBarCallback**:显示带计时信息的训练进度

**自定义回调结构**：
```python
from stable_baselines3.common.callbacks import BaseCallback

class CustomCallback(BaseCallback):
    def _on_training_start(self):
        # 在第一次 rollout 之前调用
        pass

    def _on_step(self):
        # 每次环境步进之后调用
        # 返回 False 以停止训练
        return True

    def _on_rollout_end(self):
        # 在 rollout 结束时调用
        pass
```

**可用属性**：
- `self.model`:该强化学习算法的实例
- `self.num_timesteps`:环境总步数
- `self.training_env`:训练环境

**串联多个回调**：
```python
from stable_baselines3.common.callbacks import CallbackList

callback = CallbackList([eval_callback, checkpoint_callback, custom_callback])
model.learn(total_timesteps=10000, callback=callback)
```

关于全面的回调文档，参见 `references/callbacks.md`。

### 5. 模型的持久化与检查

**保存与加载**：
```python
# 保存模型
model.save("model_name")

# 保存归一化统计量(若使用 VecNormalize)
vec_env.save("vec_normalize.pkl")

# 加载模型
model = PPO.load("model_name", env=env)

# 加载归一化统计量
vec_env = VecNormalize.load("vec_normalize.pkl", vec_env)
```

**参数访问**：
```python
# 获取参数
params = model.get_parameters()

# 设置参数
model.set_parameters(params)

# 访问 PyTorch 状态字典
state_dict = model.policy.state_dict()
```

### 6. 评估与录制

**评估**：
```python
from stable_baselines3.common.evaluation import evaluate_policy

mean_reward, std_reward = evaluate_policy(
    model,
    env,
    n_eval_episodes=10,
    deterministic=True
)
```

**视频录制**：
```python
from stable_baselines3.common.vec_env import VecVideoRecorder

# 用视频录制器封装环境
env = VecVideoRecorder(
    env,
    "videos/",
    record_video_trigger=lambda x: x % 2000 == 0,
    video_length=200
)
```

关于完整的评估与录制模板，参见 `scripts/evaluate_agent.py`。

### 7. 进阶功能

**学习率调度**：
```python
def linear_schedule(initial_value):
    def func(progress_remaining):
        # progress_remaining 从 1 递减到 0
        return progress_remaining * initial_value
    return func

model = PPO("MlpPolicy", env, learning_rate=linear_schedule(0.001))
```

**多输入策略(字典观测值)**：
```python
model = PPO("MultiInputPolicy", env, verbose=1)
```
当观测值是字典结构时使用(例如将图像与传感器数据组合在一起)。

**后见之明经验回放（Hindsight Experience Replay）**：
```python
from stable_baselines3 import SAC, HerReplayBuffer

model = SAC(
    "MultiInputPolicy",
    env,
    replay_buffer_class=HerReplayBuffer,
    replay_buffer_kwargs=dict(
        n_sampled_goal=4,
        goal_selection_strategy="future",
    ),
)
```

**TensorBoard 集成**：
```python
model = PPO("MlpPolicy", env, tensorboard_log="./tensorboard/")
model.learn(total_timesteps=10000)
```

## 工作流程指导

**启动一个新的强化学习项目**：

1. **定义问题**:确定观测空间、动作空间和奖励结构
2. **选择算法**:参见 `references/algorithms.md` 获取选型指导
3. **创建/适配环境**:如有需要，使用 `scripts/custom_env_template.py`
4. **验证环境**:训练前始终运行 `check_env()`
5. **搭建训练流程**:以 `scripts/train_rl_agent.py` 作为起始模板
6. **加入监控**:为评估和检查点保存实现回调
7. **优化性能**:考虑使用向量化环境以提升速度
8. **评估与迭代**:使用 `scripts/evaluate_agent.py` 进行评估

**常见问题**：

- **内存错误**:对离策略算法减小 `buffer_size`,或减少并行环境数量
- **训练速度慢**:考虑对并行环境使用 SubprocVecEnv
- **训练不稳定**:尝试不同算法、调整超参数，或检查奖励的缩放
- **导入错误**:确认已安装 `stable_baselines3`:`uv pip install 'stable-baselines3[extra]>=2.8'`

## 资源

### scripts/
- `train_rl_agent.py`:包含最佳实践的完整训练脚本模板
- `evaluate_agent.py`:智能体评估与视频录制模板
- `custom_env_template.py`:自定义 Gym 环境模板

### references/
- `algorithms.md`:详细的算法对比与选型指南
- `custom_environments.md`:全面的自定义环境创建指南
- `callbacks.md`:完整的回调系统参考
- `vectorized_envs.md`:向量化环境的用法与封装器
