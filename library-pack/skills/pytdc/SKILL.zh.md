# PyTDC（Therapeutics Data Commons）

通过官方发行版 `PyTDC`（`import tdc`）来发现治疗学相关的机器学习任务、加载已获批准的数据集、应用与任务相匹配的数据划分方式、评估预测结果，并使用经过整理的基准测试组（benchmark group）。应优先使用包内元数据，而不是复制出来的数据集列表，并在构造任何加载器之前先规划好网络/存储方面的影响。

## 已验证的版本快照

- 调研日期:**2026-07-23**
- PyPI 稳定版本:**PyTDC 1.1.15**,发布于 2025-03-31
- 软件包/源码仓库:`mims-harvard/TDC`
- 代码许可证:MIT
- PyPI 上只提供源码分发包，且未声明 `Requires-Python`
- 依赖关系图决定了 **CPython 3.11** 是本文所验证的可复现目标版本:
  `cellxgene-census==1.15.0` 排除了 Python 3.12,而 PyTDC 所限定的
  RDKit 发行版没有 CPython 3.13 的 wheel 包
- PyTDC 在运行时会导入已被弃用的 `pkg_resources` 模块。setuptools 82 移除了该模块;
  请固定使用经验证兼容的版本 **setuptools 80.9.0**。
- `tdc.readthedocs.io` 上标注的仍是 TDC 0.4.1;应将其作为 API 的交叉参考，而不是作为发行版本的依据
- 上游没有发布 GitHub tags/releases,也没有维护变更日志。对未有文档记录的迁移说法应视为不确定信息，需对照已安装的
  1.1.15 版本源码/元数据进行核实。

关于带有日期标注的证据和已知的文档冲突，见 [references/sources.md](references/sources.md)。

## 安装

使用一个隔离的 CPython 3.11 环境，并固定使用经过审查的快照版本:

```bash
uv venv --python 3.11 .venv-pytdc
uv pip install --dry-run --python .venv-pytdc/bin/python \
  "setuptools==80.9.0" "PyTDC==1.1.15"
uv pip install --python .venv-pytdc/bin/python \
  "setuptools==80.9.0" "PyTDC==1.1.15"
```

经过测试的 macOS ARM64 依赖解析结果安装了 123 个包，其中包括大型的科学计算/机器学习依赖项，因此在下载任何数据集之前，环境本身的体积传输和占用就可能达到数百兆字节。请先审阅 dry run 的结果以及可用磁盘空间。直接的版本锁定标识出了本文所审查的 API 快照；当每一个传递依赖的版本也都必须冻结时，请在用户的项目中生成一份针对具体平台的
`uv.lock`。

对于一次性命令:

```bash
uv run --python 3.11 \
  --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/discover_metadata.py --kind tasks
```

要检查是否有更新的发行版本，请查阅 PyPI 的发行历史 <https://pypi.org/project/pytdc/>。在更改版本锁定之前，请先比较其源码分发包、依赖项、官方仓库、任务注册表和冒烟测试；不要在未加说明的情况下把它替换为另一个独立的
`pytdc-nextml` 包。

## 不可协商的数据与网络策略

1. **先发现（Discover first）**。 读取 `tdc.metadata` 或使用
   `scripts/discover_metadata.py` 都不会实例化加载器或下载数据。
2. **再规划（Plan second）**。 记录下确切的任务/数据集、官方任务页面、许可证、
   预期大小、缓存目录、数据划分方式、评估指标以及可复现性所用的随机种子。
3. **下载前先征得用户同意**。 加载器的构造函数会获取缺失的数据。
   有些数据集和基准测试组的归档文件体积很大；基于模型的 oracle 可能会获取模型检查点(checkpoint);远程/对接（docking）类 oracle 可能会传输分子结构数据。
4. **只有获得批准后才执行**。 在内置的 CLI 中,`--execute` 表示确认执行，而对于 MolGen 语料库或受支持的 oracle 检查点，还需要额外加上
   `--download`。
5. **让输出保持有界**。 输出计数、结构模式和小型预览，而不是完整的数据集、序列、预测数组或分子语料库。

### 缓存与开销行为

- 普通加载器默认使用 `path="./data"`,并把文件保存在该路径之下。
  内置脚本则默认使用明确的 `.pytdc-*` 目录。
- 当本地文件名缺失时，核心下载使用 Harvard Dataverse 的文件端点。较新的资源类可能使用其他上游服务。
- `admet_group(path=...)` 及其他基准测试组构造函数，会在
  `<path>/<group>` 不存在时下载并解压该组的归档文件。
- 依赖下载的 `Oracle(...)` 构造在内部使用 `./oracle`。内置的 oracle CLI 会在获得批准的调用之前，先切换到一个安全的运行时目录。
- PyTDC 1.1.15 没有提供统一的缓存配额、淘汰策略，或者针对整个数据集的校验和清单。请使用
  `scripts/cache_audit.py`,并显式地管理磁盘留存。
- 网络传输、本地存储、解压缩、解析、特征生成、分子对接以及外部服务调用，都可能产生时间或金钱上的开销。

PyTDC 的**代码**采用 MIT 许可证。数据集/任务的许可证则各不相同:官方任务页面上，各数据集的条款从知识共享许可证到非商业性限制，乃至"未指明"都有。在下载、再分发、发表或商业使用之前，请核实具体数据集的页面和原始来源的条款。同时引用 TDC 和原始数据集。

## 先从纯元数据发现开始

在本技能所在目录下:

```bash
uv run --python 3.11 --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/discover_metadata.py --kind datasets --task ADME --limit 50

uv run --python 3.11 --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/discover_metadata.py --kind benchmarks --limit 50

uv run --python 3.11 --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/discover_metadata.py --kind evaluators --limit 100
```

包本身的 API 也支持纯元数据查询:

```python
from tdc.utils import retrieve_dataset_names, retrieve_benchmark_names

adme_names = retrieve_dataset_names("ADME")
admet_benchmarks = retrieve_benchmark_names("admet_group")
```

请使用返回的精确名称。PyTDC 在内部执行模糊匹配，但显式匹配可以避免在不知不觉中选中错误的数据集/oracle。

## 数据集工作流

在不下载数据的情况下规划一次数据划分:

```bash
uv run --python 3.11 --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/load_and_split_data.py \
  --task ADME --dataset Caco2_Wang --method scaffold \
  --seed 42 --data-dir .pytdc-data
```

在用户批准了数据集、许可证、数据传输和存储之后:

```bash
uv run --python 3.11 --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/load_and_split_data.py \
  --task ADME --dataset Caco2_Wang --method scaffold \
  --seed 42 --data-dir .pytdc-data --execute
```

已验证的公开导入方式包括:

```python
from tdc.single_pred import ADME, Tox
from tdc.multi_pred import DDI, DTI
from tdc.generation import MolGen, Reaction, RetroSyn
```

构造函数会执行数据访问操作，因此在获得批准之前不要运行它们:

```python
data = ADME(name="Caco2_Wang", path=".pytdc-data")
frame = data.get_data(format="df")
split = data.get_split(
    method="scaffold",
    seed=42,
    frac=[0.7, 0.1, 0.2],
)
# split keys are: train, valid, test
```

在选择任务或数据集之前，请先阅读
[references/datasets.md](references/datasets.md)。

## 选择数据划分方式，同时不要高估其对数据泄漏的控制能力

- `random`:加载器的默认方式；默认种子为 42,划分比例为 0.7/0.1/0.2。
- `scaffold`:官方文档记录的通用支持方式，适用于基于分子的 ADME、Tox 和 HTS 任务。
  PyTDC 会按 RDKit 的 Bemis–Murcko 骨架字符串分组(禁用手性),但这**并不能**证明不存在类似物、重复项、标签、时间或来源方面的数据泄漏。
- `cold_split`:多实例 API。需传入准确的数据框列名，例如
  `method="cold_split", column_name=["Drug", "Target"]`。多列划分可能会丢弃跨分区的行，也不一定能保持所要求的行占比。
- `combination`:内置的 DrugSyn 组合划分方式。
- `time`:配对加载器(pair-loader)API,需要 `time_column` 参数；已验证的内置示例是
  带有 `Year` 列的 `BindingDB_Patent`。API 中的拼写是 `time`,而不是
  `temporal`。

不要使用文档中未记录的 `cold_drug_target`、`temporal` 或 `stratified=True`
示例。对于每一种数据划分方式，都应记录 PyTDC 版本、参数、行数，以及确切的实体重叠审计结果。PyTDC 1.1.15 的随机划分器在测试集抽样时使用传入的种子，但在验证集抽样时使用固定的
`random_state=1`;不要把所有分区都描述成会随种子独立变化。

详细的语义和注意事项见
[references/utilities.md](references/utilities.md)。

## 评估器（Evaluators）

请使用已安装的评估器注册表中的确切名称:

```python
from tdc import Evaluator

mae = Evaluator(name="MAE")(y_true, y_pred)
auroc = Evaluator(name="ROC-AUC")(y_true_binary, predicted_scores)
pcc = Evaluator(name="PCC")(y_true, y_pred)
```

`PCC` 是注册表中皮尔逊相关系数(Pearson correlation)对应的名称;`Pearson` 不是。多分类的注册名称是
`micro-f1`、`macro-f1` 和 `kappa`。带阈值的二分类指标默认阈值为 0.5。指标的方向和输入形状是各指标特有的；应使用官方任务/基准测试所规定的指标，而不是仅凭任务类型来自行选择。

## 基准测试组（Benchmark Groups）

请使用专用的类。顶层的 `from tdc import BenchmarkGroup` 在 1.1.15 中仅作为已弃用的兼容性路径保留。

```python
from tdc.benchmark_group import admet_group

# Run only after approval: construction may download the group archive.
group = admet_group(path=".pytdc-benchmarks")
benchmark = group.get("Caco2_Wang")
train_val = benchmark["train_val"]
test = benchmark["test"]
train, valid = group.get_train_valid_split(
    seed=1,
    benchmark=benchmark["name"],
    split_type="default",
)
```

对于单次运行,`group.evaluate({name: test_predictions})` 返回评估指标结果。
对于排行榜(leaderboard)聚合，应向 `group.evaluate_many(...)` 传入一个**至少包含五个预测字典的列表**。不要按种子对
`group.get(...)` 进行索引，也不要从测试标签中派生出虚拟预测结果。

在下载任何基准测试组之前，使用 `scripts/benchmark_evaluation.py` 来验证一份有界的 JSON 预测计划。关于确切的 JSON 结构和 API 行为，见
[references/utilities.md](references/utilities.md)。

## 分子生成与 Oracle

PyTDC 提供分子语料库、评估器和 oracle;它本身并不在核心工作流中训练或提供通用的分子生成器。发现当前可用的名称:

```bash
uv run --python 3.11 --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/discover_metadata.py --kind oracles --limit 100
```

规划一次有界的本地 QED 打分:

```bash
uv run --python 3.11 --with "setuptools==80.9.0" --with "PyTDC==1.1.15" \
  python scripts/molecular_generation.py score --oracle QED --smiles CCO
```

只有在审查之后才加上 `--execute`。在 1.1.15 中,LogP 和 SA 会调用可下载的
`fpscores` 制品(artifact);它们以及 DRD2/GSK3B/JNK3/CYP3A4_Veith 也都需要
`--download`。该辅助工具刻意拒绝远程服务、分子对接、分发以及复合型 oracle。它会保持输入顺序，且从不对评分方向做任何假设。

在调用任何 oracle 之前，请先阅读
[references/oracles.md](references/oracles.md)。

## 内置资源

### 脚本

- `scripts/discover_metadata.py` —— 无需下载的包注册表发现工具
- `scripts/load_and_split_data.py` —— 与任务相匹配的数据划分方案规划/显式执行
- `scripts/benchmark_evaluation.py` —— 预测结果验证与显式评估
- `scripts/molecular_generation.py` —— 有界的本地/检查点打分，以及 MolGen 规划
- `scripts/cache_audit.py` —— 只读的、有界的缓存清单

每个 CLI 都采用惰性的可选导入、安全的相对输出/缓存路径、JSON 摘要、有界输出，并且不会隐式下载数据集/模型。

### 参考文档

- [references/datasets.md](references/datasets.md) —— 任务发现、数据访问、
  缓存行为以及许可事宜
- [references/utilities.md](references/utilities.md) —— 数据划分、评估器以及
  基准测试组的 API
- [references/oracles.md](references/oracles.md) —— oracle 的类别、副作用
  以及安全执行方式
- [references/sources.md](references/sources.md) —— 带有日期标注的权威来源，以及
  尚未解决的上游文档空白
