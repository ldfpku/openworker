# PyHealth

PyHealth（<https://pyhealth.dev/>）是一个用于临床深度学习的 Python 工具包。它在电子病历（EHR）、
生理信号和医学影像之间提供了统一的、模块化的流水线。

该库围绕**五阶段流水线**（`Dataset → Task → Model → Trainer → Metrics`，数据集 → 任务 → 模型 → 训练器 → 指标）
构建，每个阶段都可替换，且各阶段之间的接口保持稳定。遵循这一流水线结构的代码组合性良好；
绕开它的代码通常会与该库产生冲突。

## 何时使用此技能

只要用户在进行临床/医疗健康机器学习工作，且以下任一情况成立，就应使用此技能：

- 用户提到 PyHealth、MIMIC-III/IV、eICU、OMOP-CDM、EHRShot、SleepEDF、SHHS、ISRUC、COVID19-CXR、ChestX-ray14、TUEV/TUAB。
- 用户想要预测死亡率、再入院率、住院时长、药物推荐、睡眠分期、ICD 编码或去标识化处理。
- 用户需要查找或交叉映射医疗编码（ICD-9-CM、ICD-10-CM、ATC、NDC、RxNorm、CCS）。
- 用户拥有 EHR 形状的数据，并希望在不自行编写底层管道代码的情况下训练一个临床模型。

当工作流恰好符合其五个阶段时，PyHealth 就是正确的工具。如果用户只是想在表格数据上使用通用的
PyTorch，则不需要此技能。

## 安装（使用 uv）

PyHealth 2.0 需要 Python ≥ 3.12, < 3.14。请使用 `uv` 进行环境管理——它更快且可复现。

```bash
# Create a project with the right Python
uv init my-pyhealth-project
cd my-pyhealth-project
uv python pin 3.12

# Add PyHealth (this also pulls in PyTorch and friends)
uv add pyhealth

# Run scripts inside the env
uv run python train.py
```

对于不需要建立项目的一次性脚本，可使用 `uv run --with pyhealth python script.py`。对于旧版的 1.x
系列（需要 Python 3.9+），使用 `uv add pyhealth==1.16`。详细的安装说明、MIMIC 访问权限，以及
GPU/CPU 设备方面的提示都在 `references/installation.md` 中。

## 五阶段流水线

一条完整的流水线通常不到 20 行代码。以下是标准形态——从这里开始并按需修改各部分：

```python
from pyhealth.datasets import MIMIC3Dataset, split_by_patient, get_dataloader
from pyhealth.tasks import MortalityPredictionMIMIC3
from pyhealth.models import Transformer
from pyhealth.trainer import Trainer
from pyhealth.metrics.binary import binary_metrics_fn

# 1. Dataset — raw patient registry
base = MIMIC3Dataset(
    root="https://storage.googleapis.com/pyhealth/Synthetic_MIMIC-III/",
    tables=["DIAGNOSES_ICD", "PROCEDURES_ICD", "PRESCRIPTIONS"],
)

# 2. Task — converts patients into supervised samples
samples = base.set_task(MortalityPredictionMIMIC3())

# 3. Split + DataLoaders (split by patient to avoid leakage)
train_ds, val_ds, test_ds = split_by_patient(samples, [0.8, 0.1, 0.1])
train_loader = get_dataloader(train_ds, batch_size=32, shuffle=True)
val_loader   = get_dataloader(val_ds,   batch_size=32, shuffle=False)
test_loader  = get_dataloader(test_ds,  batch_size=32, shuffle=False)

# 4. Model — must be passed the SampleDataset, not the BaseDataset
model = Transformer(dataset=samples)

# 5. Train + evaluate
trainer = Trainer(model=model)
trainer.train(
    train_dataloader=train_loader,
    val_dataloader=val_loader,
    epochs=50,
    monitor="pr_auc",
)

y_true, y_prob, _ = trainer.inference(test_loader)
print(binary_metrics_fn(y_true, y_prob, metrics=["pr_auc", "roc_auc"]))
```

一份可直接复制粘贴使用的起始代码在 `assets/starter_pipeline.py` 中。

## 必须弄对的关键事项

以下是 PyHealth 代码最常绊倒的错误之处。在编写流水线之前，请务必牢记这些要点：

1. **模型接受的是 `SampleDataset`，而不是 `BaseDataset`。** `MIMIC3Dataset(...)` 返回的是一个
   `BaseDataset`（一个可查询的患者注册表）。只有在调用 `.set_task(task)` 之后，才会得到
   `SampleDataset`，这才是模型、切分器（splitter）和 DataLoader 所期望接收的对象。如果将 `base`
   传给模型，会导致失败或行为异常。

2. **务必按患者（或按就诊次数）切分，而不是按样本切分**。 随机的样本级切分会导致训练集/测试集
   之间的信息泄漏，因为同一名患者可能同时出现在两者中。对于患者级预测使用 `split_by_patient`，
   仅当各次就诊相互独立时才使用 `split_by_visit`。

3. **确保任务与数据集匹配**。 任务是与特定数据集绑定的：`MortalityPredictionMIMIC3` 不能用于
   MIMIC-IV——应使用 `MortalityPredictionMIMIC4` 或 `InHospitalMortalityMIMIC4`。完整的映射关系
   见 `references/tasks.md`。

4. **选择与任务类型匹配的 `monitor`。** 对于二分类任务，使用 `"pr_auc"` 或 `"roc_auc"`。对于
   多标签任务（如药物推荐），使用 `"pr_auc_samples"` 或 `"jaccard_samples"`。对于多分类任务，
   使用 `"accuracy"` 或 `"f1_macro"`。若 monitor 选错，检查点（checkpoint）选择就会保存错误的
   训练轮次。

5. **MIMIC-IV 使用的是 `ehr_root=`，而不是 `root=`。** 这是数据集构造函数中唯一一处不一致的地方。

6. **为保证工作可复现，应将 `cache_dir=` 指向某个持久化位置。** PyHealth 会缓存已解析的数据集；
   若不设置 `cache_dir`，每次运行都会重新解析。

## 如何使用此技能

PyHealth 的 API 面很大——没有必要一次性全部加载。应根据用户任务阅读相应的参考文件：

| 若用户询问… | 阅读 |
|---|---|
| 安装、环境搭建、MIMIC 访问权限、GPU | `references/installation.md` |
| 应使用哪个数据集类、加载模式、数据切分 | `references/datasets.md` |
| 应选择哪种预测任务（死亡率、再入院、药物推荐、睡眠分期……） | `references/tasks.md` |
| 选择模型架构、模型专属参数 | `references/models.md` |
| 查找或交叉映射 ICD/ATC/NDC/RxNorm/CCS 编码、分词器（tokenizer） | `references/medcode.md` |
| 常见场景的端到端方案 | `references/examples.md` |

对于多步骤任务（例如"在 MIMIC-IV 上构建一个药物推荐流水线"），应将 `tasks.md` + `models.md` +
`examples.md` 一并阅读——它们之间存在交叉引用。

## 关于代码风格的说明

应编写精简、地道的 PyHealth 代码。该库有明确的设计主张；应顺应其抽象设计，而不是用原始 PyTorch
重新实现它们。如果发现自己在编写自定义的训练循环，应先问一下 `Trainer` 是否能胜任这项工作——
几乎总是可以的，而且它免费提供了检查点保存、日志记录和最佳模型选择功能。

当用户拥有私有的 MIMIC 访问权限时，应引导其指向本地 CSV 根目录；对于演示和学习用途，
合成的 MIMIC-III 数据桶（`https://storage.googleapis.com/pyhealth/Synthetic_MIMIC-III/`）即可满足需求，
且无需任何凭证即可使用。
