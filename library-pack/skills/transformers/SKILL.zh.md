# Transformers

## 概述

Hugging Face Transformers 库提供了对数千个跨自然语言处理(NLP)、计算机视觉、音频以及多模态领域的预训练模型的访问能力。使用此技能来加载模型、执行推理，并在自定义数据上进行微调。

## 安装

针对 **transformers 5.12.0**(当前 PyPI 版本;2026 年 6 月)进行了测试。需要 **Python 3.10+**;`torch` 附加组件目前要求 **PyTorch 2.4+**。

```bash
uv pip install "transformers[torch]==5.12.0" huggingface_hub==1.19.0 datasets==5.0.0 evaluate==0.4.6 accelerate==1.14.0
```

对于视觉任务，额外安装:

```bash
uv pip install timm==1.0.27 pillow==12.2.0
```

对于音频任务，额外安装:

```bash
uv pip install librosa==0.11.0 soundfile==0.14.0
```

这些版本锁定是为了让本技能中的示例可复现。对于探索性工作，仅在核对过 Transformers 和 Hub 的发布说明、确认没有 API 变更之后，才放宽这些版本限制。

检查你的版本:

```python
import transformers
print(transformers.__version__)
```

## 鉴权

Hugging Face Hub 上的许多模型是受限(gated)或私有的。在加载它们之前需要先鉴权。

**推荐做法**: CLI 登录(将 token 存放在 `~/.cache/huggingface/token` 中):

```bash
hf auth login
```

**Python 方式**:

```python
from huggingface_hub import login
login()  # Interactive prompt; do not hardcode tokens in scripts
```

**服务器 / CI 环境**: 在环境变量中设置 `HF_TOKEN`(绝不要把 token 提交到 git 或写进 shell 配置文件中):

```bash
export HF_TOKEN="..."  # Read token from a secret manager, not source code
```

在此处获取 token: https://huggingface.co/settings/tokens

**安全性**: 绝不要把 token 粘贴到 notebook、代码仓库或共享的配置文件中。相比在 `.bashrc` 或 `.zshrc` 中导出 token,优先使用 `hf auth login`。

使用能满足需求的最窄 token 权限范围:下载私有或受限模型用 `read`,只有需要上传时才用 `write`。如果一个长期运行的环境不应该在每次 Hub 请求中都发送已存储的 token,请设置 `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`,并仅在需要鉴权的地方传入 token。

## Transformers v5

Transformers v5 是**仅支持 PyTorch** 的(TensorFlow 和 JAX 后端已被移除)。从 v4 升级请参见 [v5 迁移指南](https://github.com/huggingface/transformers/blob/main/MIGRATION_GUIDE_V5.md)。新项目应将 **transformers 5.x** 与 **huggingface_hub 1.x** 搭配使用。

**受限或自定义架构**: 先在 Hub 上接受模型许可协议，然后仅在你已审阅过模型卡(model card)所要求的自定义代码时，才用 `trust_remote_code=True` 加载。

**缓存位置**: 设置 `HF_HOME` 用于所有 Hugging Face 缓存，或仅为 Hub 文件设置 `HF_HUB_CACHE`。只有在所需的模型快照已经被缓存之后，才使用 `HF_HUB_OFFLINE=1`。

## 快速开始

使用 Pipeline API 可以无需手动配置即可快速推理:

```python
from transformers import pipeline

# Text generation (prefer max_new_tokens for causal LMs)
generator = pipeline("text-generation", model="Qwen/Qwen2.5-1.5B")
result = generator("The future of AI is", max_new_tokens=50)

# Text classification
classifier = pipeline("text-classification")
result = classifier("This movie was excellent!")

# Question answering
qa = pipeline("question-answering")
result = qa(question="What is AI?", context="AI is artificial intelligence...")
```

## 核心能力

### 1. 用于快速推理的 Pipeline

用于跨多种任务的简单、优化过的推理。支持文本生成、分类、命名实体识别(NER)、问答、摘要、翻译、图像分类、目标检测、音频分类等等。

**何时使用**:快速原型验证、简单的推理任务、不需要自定义预处理时。

全面的任务覆盖和优化说明见 `references/pipelines.md`。

### 2. 模型加载与管理

加载预训练模型，并对配置、设备放置和精度进行细粒度控制。

**何时使用**:自定义模型初始化、高级设备管理、模型检查。

加载模式和最佳实践见 `references/models.md`。

### 3. 文本生成

使用各种解码策略(贪心搜索、束搜索 beam search、采样)和控制参数(温度、top-k、top-p)用大语言模型生成文本。

**何时使用**:创意文本生成、代码生成、对话式 AI、文本补全。

生成策略和参数见 `references/generation.md`。

### 4. 训练与微调

使用 Trainer API 在自定义数据集上微调预训练模型，支持自动混合精度、分布式训练和日志记录。

**何时使用**:面向特定任务的模型适配、领域适配、提升模型性能。

训练工作流和最佳实践见 `references/training.md`。

### 5. 分词(Tokenization)

将文本转换为用于模型输入的 token 和 token ID,支持填充(padding)、截断(truncation)和特殊 token 处理。

**何时使用**:自定义预处理流水线、理解模型输入、批处理。

分词的详细内容见 `references/tokenizers.md`。

## 常见模式

### 模式 1:简单推理
对于直接了当的任务，使用 pipeline:
```python
pipe = pipeline("task-name", model="model-id")
output = pipe(input_data)
```

### 模式 2:自定义模型用法
对于高级控制，分别加载模型和分词器:
```python
from transformers import AutoModelForCausalLM, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("model-id")
model = AutoModelForCausalLM.from_pretrained("model-id", device_map="auto")

inputs = tokenizer("text", return_tensors="pt")
outputs = model.generate(**inputs, max_new_tokens=100)
result = tokenizer.decode(outputs[0])
```

### 模式 3:微调
对于任务适配，使用 Trainer:
```python
from transformers import Trainer, TrainingArguments

training_args = TrainingArguments(
    output_dir="./results",
    num_train_epochs=3,
    per_device_train_batch_size=8,
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
)

trainer.train()
```

## 参考文档

关于具体组件的详细信息:
- **Pipelines**:`references/pipelines.md` - 所有支持的任务及优化说明
- **Models**:`references/models.md` - 加载、保存和配置
- **Generation**:`references/generation.md` - 文本生成策略和参数
- **Training**:`references/training.md` - 使用 Trainer API 微调
- **Tokenizers**:`references/tokenizers.md` - 分词与预处理
