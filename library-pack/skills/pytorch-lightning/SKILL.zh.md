# PyTorch Lightning

## 概述

PyTorch Lightning 是一个深度学习框架，它对 PyTorch 代码进行组织，消除样板代码(boilerplate),同时保留完全的灵活性。可用它自动化训练工作流、多设备编排，并为在多个 GPU/TPU 上进行神经网络训练与扩展实现最佳实践。

**当前上游版本**: lightning 2.6.4(PyPI,2026 年 5 月)。文档:[lightning.ai/docs/pytorch/stable](https://lightning.ai/docs/pytorch/stable/)。使用 `import lightning as L`(`pytorch-lightning` 这个包名安装的仍然是同一个库)。

## 安装

```bash
uv pip install lightning
```

可选的附加组件:

```bash
uv pip install lightning[extra]    # 日志记录器、训练策略等
uv pip install wandb mlflow        # 按需安装特定的日志记录器
```

## 何时使用本技能

以下情况应使用本技能:
- 使用 PyTorch Lightning 构建、训练或部署神经网络
- 将 PyTorch 代码组织为 LightningModule
- 为多 GPU/TPU 训练配置 Trainer
- 使用 LightningDataModule 实现数据管道
- 处理回调(callback)、日志记录，以及分布式训练策略(DDP、FSDP、DeepSpeed)
- 以专业方式组织深度学习项目结构

## 核心能力

### 1. LightningModule —— 模型定义

将 PyTorch 模型组织为六个逻辑部分:

1. **初始化** —— `__init__()` 和 `setup()`
2. **训练循环** —— `training_step(batch, batch_idx)`
3. **验证循环** —— `validation_step(batch, batch_idx)`
4. **测试循环** —— `test_step(batch, batch_idx)`
5. **预测** —— `predict_step(batch, batch_idx)`
6. **优化器配置** —— `configure_optimizers()`

**快速模板参考**: 完整的样板代码见 `scripts/template_lightning_module.py`。

**详细文档**: 关于方法、钩子(hook)、属性和最佳实践的全面说明，阅读 `references/lightning_module.md`。

### 2. Trainer —— 训练自动化

Trainer 自动化训练循环、设备管理、梯度操作和回调。主要特性:

- 通过策略选择(DDP、FSDP、DeepSpeed)支持多 GPU/TPU
- 自动混合精度训练
- 梯度累积与梯度裁剪
- 检查点保存与提前停止(early stopping)
- 进度条与日志记录

**快速配置参考**: 常见的 Trainer 配置示例见 `scripts/quick_trainer_setup.py`。

**详细文档**: 所有参数、方法和配置选项，阅读 `references/trainer.md`。

### 3. LightningDataModule —— 数据管道组织

将所有数据处理步骤封装到一个可复用的类中:

1. `prepare_data()` —— 下载和处理数据(单进程)
2. `setup()` —— 创建数据集并应用变换(每个 GPU 各自执行)
3. `train_dataloader()` —— 返回训练用 DataLoader
4. `val_dataloader()` —— 返回验证用 DataLoader
5. `test_dataloader()` —— 返回测试用 DataLoader

**快速模板参考**: 完整的样板代码见 `scripts/template_datamodule.py`。

**详细文档**: 方法细节与使用模式，阅读 `references/data_module.md`。

### 4. Callbacks(回调)—— 可扩展的训练逻辑

在特定的训练钩子处添加自定义功能，而无需修改你的 LightningModule。内置回调包括:

- **ModelCheckpoint** —— 保存最优/最新的模型
- **EarlyStopping** —— 当指标停滞不前时停止训练
- **LearningRateMonitor** —— 跟踪学习率调度器的变化
- **BatchSizeFinder** —— 自动确定最优批大小(batch size)

**详细文档**: 内置回调与自定义回调的创建方法，阅读 `references/callbacks.md`。

### 5. 日志记录 —— 实验跟踪

可与多个日志记录平台集成:

- TensorBoard(默认)
- Weights & Biases(WandbLogger)
- MLflow(MLFlowLogger)
- Comet(CometLogger)
- CSV(CSVLogger)

注意:`NeptuneLogger` 已在 lightning 2.6.4 中移除。请改用 W&B、MLflow 或 TensorBoard。

在任何 LightningModule 方法中使用 `self.log("metric_name", value)` 来记录指标。

**详细文档**: 日志记录器的设置与配置，阅读 `references/logging.md`。

### 6. 分布式训练 —— 扩展到多个设备

根据模型规模选择合适的训练策略:

- **DDP** —— 适用于参数量小于 5 亿(500M)的模型(ResNet、较小的 transformer)
- **FSDP** —— 适用于参数量在 5 亿以上的模型(大型 transformer,推荐 Lightning 用户使用)
- **DeepSpeed** —— 适用于需要前沿特性和精细控制的场景

配置方式:`Trainer(strategy="ddp", accelerator="gpu", devices=4)`

**详细文档**: 各策略的比较与配置，阅读 `references/distributed_training.md`。

### 7. 最佳实践

- 设备无关的代码 —— 使用 `self.device`,而不是 `.cuda()`
- 超参数保存 —— 在 `__init__()` 中使用 `self.save_hyperparameters()`
- 指标记录 —— 使用 `self.log()` 以实现跨设备的自动聚合
- 可复现性 —— 使用 `seed_everything()` 和 `Trainer(deterministic=True)`
- 调试 —— 使用 `Trainer(fast_dev_run=True)` 以单个批次进行测试

**详细文档**: 常见模式与陷阱，阅读 `references/best_practices.md`。

## 快速工作流程

1. **定义模型**:
   ```python
   class MyModel(L.LightningModule):
       def __init__(self):
           super().__init__()
           self.save_hyperparameters()
           self.model = YourNetwork()

       def training_step(self, batch, batch_idx):
           x, y = batch
           loss = F.cross_entropy(self.model(x), y)
           self.log("train_loss", loss)
           return loss

       def configure_optimizers(self):
           return torch.optim.Adam(self.parameters())
   ```

2. **准备数据**:
   ```python
   # 方式一: 直接使用 DataLoader
   train_loader = DataLoader(train_dataset, batch_size=32)

   # 方式二: LightningDataModule(推荐,便于复用)
   dm = MyDataModule(batch_size=32)
   ```

3. **训练**:
   ```python
   trainer = L.Trainer(max_epochs=10, accelerator="gpu", devices=2)
   trainer.fit(model, train_loader)  # 或者 trainer.fit(model, datamodule=dm)
   ```

## 资源

### scripts/
用于常见 PyTorch Lightning 模式的可执行 Python 模板:

- `template_lightning_module.py` —— 完整的 LightningModule 样板代码
- `template_datamodule.py` —— 完整的 LightningDataModule 样板代码
- `quick_trainer_setup.py` —— 常见 Trainer 配置示例

### references/
针对每个 PyTorch Lightning 组件的详细文档:

- `lightning_module.md` —— LightningModule 全面指南(方法、钩子、属性)
- `trainer.md` —— Trainer 配置与参数
- `data_module.md` —— LightningDataModule 模式与方法
- `callbacks.md` —— 内置与自定义回调
- `logging.md` —— 日志记录器集成与使用方法
- `distributed_training.md` —— DDP、FSDP、DeepSpeed 的比较与配置
- `best_practices.md` —— 常见模式、技巧与陷阱
