# FlowIO

## 用途

将 FlowIO 用作一个轻量级、底层的流式细胞术标准（Flow Cytometry
Standard，FCS）文件读写器。本技能中的示例针对的是 **FlowIO 1.4.0**，
即于 2026-07-23 核实过的当前稳定发行版。

FlowIO 适用于以下场景：

- 读取 FCS 2.0、3.0 和 3.1 文件
- 检查 HEADER、TEXT、ANALYSIS 以及通道元数据
- 以二维 NumPy 数组的形式获取事件数据
- 读取包含多个数据集的旧版文件
- 写出 list-mode、单精度的 FCS 3.1 文件
- 为 pandas、机器学习，或下游细胞术工具准备数据

FlowIO **不会**执行补偿（compensation）、logicle/双指数（biexponential）
变换、门控（gating）、聚类，或 FlowJo 工作区处理。这些任务应使用
FlowKit 或其他分析包来完成。

## 安装

创建或激活一个 Python 环境，然后安装经过验证的发行版：

```bash
uv pip install "flowio==1.4.0"
```

确认运行时版本：

```bash
uv run python -c "import flowio; print(flowio.__version__)"
```

FlowIO 1.4.0 支持 Python 3.9 到 3.13,并依赖 NumPy。

## 操作工作流

1. **明确操作类型**。 区分元数据清点、事件提取、文件修复、转换，以及
   下游的生物学分析。
2. **在加载事件之前先做检查**。 对于仅涉及元数据的工作，尤其是面对
   大型或不熟悉的文件时，使用 `only_text=True`。
3. **明确选择事件的语义**。 若要从 FCS 元数据得到增益/对数/时间
   缩放，使用 `as_array(preprocess=True)`；若要得到 DATA 段中编码的
   原始数值，使用 `preprocess=False`。要记录下所做的选择。
4. **默认保持严格解析**。 不要自动抑制偏移量（offset）错误。只有在
   面对已知的厂商格式缺陷时才放宽检查，并审查由此产生的事件数据。
5. **把元数据当作可能敏感的信息来对待**。 FCS 的 TEXT 值可能包含样本、
   受试者、操作员和仪器标识符。只导出任务所需的字段。
6. **通过重新打开来验证写入结果**。 在任何 FCS 导出操作之后，检查
   事件数/通道数、标签、元数据以及有代表性的数值。

## 关键语义

### TEXT 键会被规范化

`FlowData.text` 以小写形式存储各个键，并去掉标准 FCS 关键字前面的
`$` 符号：

```python
from flowio import FlowData

flow = FlowData("sample.fcs", only_text=True)
acquisition_date = flow.text.get("date")
instrument = flow.text.get("cyt")
next_dataset = int(flow.text.get("nextdata", "0"))
```

不要查找 `"$DATE"`、`"$CYT"`,或其他以美元符号开头的大写键。TEXT 的值
仍然是字符串。FlowIO 1.4.0 还会从解码后的 TEXT 段中移除每一个 `$`
字符，包括出现在值内部的 `$` 字符；当需要元数据的精确保真度时，要
保留原始文件。

### 事件数据有两种表示形式

- `flow.events` 是未经处理的、被展平成一维的事件数组。
- `flow.as_array()` 以 NumPy `float64` 数组的形式返回形状为
  `(event_count, channel_count)` 的结果。
- `flow.as_array(preprocess=True)` 会应用 FCS 的增益、对数，以及时间
  缩放。它不会应用补偿或 logicle/双指数显示变换。
- `flow.as_array(preprocess=False)` 只对已编码的事件值重塑形状，不做
  那些缩放步骤。

`as_array()` 每次都会创建另一个位于内存中的数组。FlowIO 不提供分块
或内存映射方式的事件访问。

### 通道编号使用两种约定

- NumPy 的列，以及 `fluoro_indices`、`scatter_indices` 和
  `time_index`，使用从零开始的索引。
- `flow.channels` 使用从 1 开始的 FCS 参数编号。
- `null_channels` 包含通过 `null_channel_list` 提供的 PnN 标签
  字符串，包括那些被提供但未找到的标签。
- `pns_labels` 的长度始终与 `pnn_labels` 相同；缺失的可选 PnS 标签
  会显示为空字符串。

### 写入功能是有意受限的

`create_fcs()` 需要：

- 一个已经打开的二进制文件句柄
- 按事件/通道行主序（row-major）展平成一维的事件数据
- 每个通道一个 PnN 名称
- 可选的 PnS 名称，以及通过 `metadata_dict` 提供的字符串值元数据

它写出的是 FCS 3.1 list-mode（`$MODE=L`）单精度浮点
（`$DATATYPE=F`）数据。必需的解释性关键字由 FlowIO 生成，无法通过
元数据来覆盖。

## 快速上手：读取 FCS 文件

```python
from pathlib import Path

from flowio import FlowData

flow = FlowData(Path("sample.fcs"))
events = flow.as_array(preprocess=True)

print(
    {
        "version": flow.version,
        "events": flow.event_count,
        "channels": flow.channel_count,
        "shape": events.shape,
        "pnn": flow.pnn_labels,
        "pns": flow.pns_labels,
        "date": flow.text.get("date"),
        "instrument": flow.text.get("cyt"),
    }
)
```

只需要元数据时：

```python
from flowio import FlowData

flow = FlowData("sample.fcs", only_text=True)
print(flow.version, flow.event_count, flow.pnn_labels)
```

不要在一个仅有元数据的实例上调用 `as_array()`，因为它的事件数据并
没有被加载。

优先传入一个路径或 `Path`，而不是调用方自己持有的文件句柄。
`FlowData` 在解析完成后会关闭传入的句柄。在 FlowIO 1.4.0 中，
`read_multiple_data_sets(handle)` 在读完第一个数据集之后可能失败，
因为该句柄已被关闭；对于多数据集文件，请传入一个文件系统路径。

## 快速上手：读取多个数据集

使用这个独立的辅助函数，而不是手动解析 `$NEXTDATA` 偏移量：

```python
from flowio import read_multiple_data_sets

datasets = read_multiple_data_sets("legacy-multi-dataset.fcs")
for index, dataset in enumerate(datasets):
    values = dataset.as_array(preprocess=True)
    print(index, dataset.event_count, dataset.pnn_labels, values.shape)
```

FCS 3.1 规范已废弃在一个文件中存放多个数据集的做法，但 FlowIO 仍可以
读取使用这种方式的旧版文件。

## 快速上手：创建一个 FCS 3.1 文件

```python
from pathlib import Path

import numpy as np
from flowio import FlowData, create_fcs

values = np.asarray(
    [[100.0, 200.0, 50.0], [150.0, 180.0, 60.0]],
    dtype=np.float32,
)
pnn_labels = ["FSC-A", "SSC-A", "FITC-A"]
pns_labels = ["Forward scatter", "Side scatter", "CD3"]

output = Path("output.fcs")
with output.open("xb") as handle:
    create_fcs(
        handle,
        values.ravel(order="C"),
        pnn_labels,
        opt_channel_names=pns_labels,
        metadata_dict={
            "date": "23-JUL-2026",
            "cyt": "Example instrument",
            "src": "Validated NumPy array",
        },
    )

roundtrip = FlowData(output)
assert roundtrip.event_count == values.shape[0]
assert roundtrip.pnn_labels == pnn_labels
np.testing.assert_allclose(
    roundtrip.as_array(preprocess=False),
    values,
    rtol=1e-6,
    atol=1e-6,
)
```

元数据键可以用大小写混合的形式提供，也可以带 `$`，但不带 `$` 的小写
键与 FlowIO 规范化后的表示形式相匹配，出错的可能性更小。元数据的值
必须是字符串。

## 复制或重写一个已有文件

当事件数据不需要改变时，使用 `write_fcs()`：

```python
from flowio import FlowData

flow = FlowData("source.fcs")

# 保留部分源文件元数据（cyt、date，以及存在时的 spill/spillover）。
flow.write_fcs("copy.fcs")

# 只写出必需的元数据，加上这里提供的自定义字段。
flow.write_fcs("deidentified.fcs", metadata={"src": "Deidentified export"})
```

传入 `metadata=None` 会保留 FlowIO 选定的默认值。传入任何字典
（包括 `{}`）都会替换这些默认值，而不是与之合并。`write_fcs()`
始终产生 FCS 3.1 浮点输出；非浮点类型的源事件数据在写出之前会先经过
预处理。它会以覆盖方式打开目标文件，因此除非确实想要替换，否则在
调用它之前应先拒绝一个已存在的输出路径。对于浮点类型的源数据，
它可以保留已编码的事件数据，同时丢弃 PnG 或 `timestep`，这会改变
之后 `as_array(preprocess=True)` 的结果。要同时验证原始值和经预处理
值的往返一致性。

当事件值、事件数，或通道布局发生变化时，应改用 `create_fcs()`。

## 内置检查工具

`scripts/inspect_fcs.py` 会在不联网的情况下清点一个或多个数据集。
默认情况下它只读取元数据，输出结构性字段和通道标签，而不输出完整的
TEXT/ANALYSIS 数值，并且会拒绝处理超过可配置大小上限的文件。

将 `FLOWIO_SKILL_DIR` 设置为已安装的技能目录。从本仓库的根目录出发，
使用 `skills/flowio`：

```bash
FLOWIO_SKILL_DIR="skills/flowio"

# 元数据与通道清点
uv run --no-project --with "flowio==1.4.0" \
  python "$FLOWIO_SKILL_DIR/scripts/inspect_fcs.py" sample.fcs

# 包含所有规范化后的 TEXT 元数据；请检查输出中是否有标识符
uv run --no-project --with "flowio==1.4.0" \
  python "$FLOWIO_SKILL_DIR/scripts/inspect_fcs.py" sample.fcs --include-text

# 加载事件数据，并使用 FlowIO 的预处理来计算有限值的统计量
uv run --no-project --with "flowio==1.4.0" \
  python "$FLOWIO_SKILL_DIR/scripts/inspect_fcs.py" sample.fcs --stats

# 改为基于编码值计算统计量
uv run --no-project --with "flowio==1.4.0" \
  python "$FLOWIO_SKILL_DIR/scripts/inspect_fcs.py" sample.fcs --stats --raw
```

关于输出文件、输入/数组的内存限制、空通道标签，以及受控的偏移量
恢复选项，请使用 `--help`。

## 参考资料

只阅读当前任务所需要的那份参考文档：

- `references/api_reference.md` —— FlowIO 1.4.0 精确的公共 API 与函数签名
- `references/workflows.md` —— 清点、DataFrame/CSV、批处理、写入以及
  往返模式
- `references/fcs_semantics.md` —— FCS 结构、元数据规范化、预处理方程、
  索引方式，以及写入器行为
- `references/troubleshooting.md` —— 偏移量失败、多数据集文件、内存
  限制、验证、安全性，以及隐私
- `references/sources.md` —— 本次更新所依据的权威上游文档、发行说明、
  源代码，以及 FCS 3.1 出版物

## 不可协商的检查事项

- 绝不声称 FlowIO 会执行补偿或门控。
- 绝不把 `as_array(preprocess=True)` 的结果当作原始采集数值。
- 绝不把一个二维数组或一个路径直接传给 `create_fcs()`。
- 绝不假定 TEXT 键会保留 `$` 或大写拼写形式。
- 绝不在不记录原因、不验证数据的情况下静默偏移量错误。
- 绝不把 FlowIO 的事件加载描述为流式或分块的。
