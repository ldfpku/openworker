# Opentrons 集成

## 概述

为 Opentrons Flex 和 OT-2 编写具备生产级思维的 Python Protocol API v2 协议。本技能涵盖协议结构、硬件与甲板（deck）配置、液体处理、运行时自定义、模块控制、仿真以及安全部署。

截至 **2026-07-23** 已验证的基线版本为：

- `opentrons==9.1.1` 用于可复现的 Flex 仿真。
- `opentrons==9.0.0` 用于本地 OT-2 API 2.28 兼容性仿真。
- 在当前软件下,Flex 支持 API 级别 2.15 至 2.29。
- 在当前软件下,OT-2 支持 API 级别 2.0 至 2.28。
- 在此验证基线下,API 2.29 仅限 Flex 使用。不要在 OT-2 协议中使用 `2.29`。

阅读 `references/sources.md` 以获取本快照所使用的上游文档。在针对更新的机器人软件版本编写协议之前，请重新查看官方版本说明页面。

## 安全边界

Opentrons 协议控制的是真实的物理设备。切勿把 Python 语法通过或本地仿真成功，当作可以在真实机器人上运行的许可。

在正式执行之前：

1. 使用编写协议时所锁定的同一个 `opentrons` 版本进行本地仿真。
2. 将协议导入正确的 Opentrons App,并要求分析(analysis)成功通过。
3. 核实机器人型号、软件版本、移液器、挂载位置、模块、适配器、耗材(labware)定义、甲板固定装置、吸头数量、源液体积、死体积以及目标容量。
4. 与操作人员一起审查运行预览和甲板地图。
5. 当几何布局、自定义耗材、部分吸头拾取或抓手(gripper)移动是新出现的内容时，应使用无危害液体执行一次缓慢的空跑测试(dry run)。
6. 确保紧急停止按钮随时可及，并遵循现场特定的生物安全、化学安全和污染控制规程。

仿真无法验证物理校准、液体特性、液面(meniscus)行为、耗材制造公差、瓶盖或密封件的去除、管路，以及所有可能发生的碰撞情况。

## 选择正确的接口

对于导入 Opentrons App 并通过 Protocol API 运行的 Python 文件，使用此技能。

- 对于受支持的免代码工作流，使用 **Protocol Designer**。
- 对于需要跨供应商、与硬件无关的工作流，使用 **PyLabRobot**。
- 应把机器人的 HTTP API 视为一个独立的集成接口。若确实需要直接的 HTTP 控制，应使用目标机器人所提供的 OpenAPI 文档，而不要从 Protocol API 的方法去推断接口端点。

## 必需的前期信息收集

在以下事实明确之前，不要编写最终的协议代码：

- 机器人型号：Flex 还是 OT-2,以及已安装的机器人软件版本。
- 移液器型号、量程范围、通道数和挂载位置。
- 模块及其代次；是否配备 Flex Gripper 或 Stacker。
- 确切的耗材 API 加载名称，以及自定义定义文件(如有)。
- 甲板固定装置：Flex 废料桶(trash bin)、废料槽(waste chute)、暂存槽位，或 Stacker。
- 源液体积、目标体积、死体积、混合需求以及液体特性。
- 吸头策略：污染边界、复用策略、滤芯、部分吸头拾取，以及吸头总数。
- 操作人员干预、孵育时长、运行时参数以及输出文件。
- 验收标准:可容忍的体积误差、必需的对照组，以及空跑测试计划。

若任何物理配置尚不确定，应给出一份参数化草案和一份明确的假设清单，而不是靠猜测。

## 安装与仿真

Flex：

```bash
uv run --with "opentrons==9.1.1" opentrons_simulate protocol.py
```

OT-2 API 2.28：

```bash
uv run --with "opentrons==9.0.0" opentrons_simulate protocol.py
```

在 Flex/OT-2 发布线分离之后,9.1.1 版软件包会有意拒绝处理 OT-2 协议。务必始终在当前的 OT-2 App 中完成 OT-2 分析。

若要建立一个专用的 Flex 环境：

```bash
uv venv --python 3.10
uv pip install --python .venv/bin/python -r skills/opentrons-integration/requirements-flex.txt
.venv/bin/opentrons_simulate protocol.py
```

若要建立 OT-2 兼容性环境，改用 `requirements-ot2.txt`。在 Windows 上，应从 `.venv\Scripts\opentrons_simulate.exe` 调用该可执行文件。本地仿真适用于 Python 协议;Protocol Designer 生成的 JSON 文件应改为导入相应的 Opentrons App。

## 协议骨架

### Flex,API 2.29

对于 Flex,`requirements` 是必需的。`apiLevel` 只应放在 `requirements` 中，不要同时出现在 `metadata` 和 `requirements` 里。

```python
from opentrons import protocol_api

metadata = {
    "protocolName": "Flex transfer",
    "author": "Your Name",
    "description": "Transfer buffer into a plate.",
}
requirements = {"robotType": "Flex", "apiLevel": "2.29"}


def run(protocol: protocol_api.ProtocolContext) -> None:
    tips = protocol.load_labware(
        "opentrons_flex_96_tiprack_200ul", "D1"
    )
    reservoir = protocol.load_labware("nest_12_reservoir_15ml", "D2")
    plate = protocol.load_labware("nest_96_wellplate_200ul_flat", "C2")
    protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument(
        "flex_1channel_1000", "left", tip_racks=[tips]
    )

    pipette.transfer(
        100,
        reservoir["A1"],
        plate["A1"],
        new_tip="always",
    )
```

### OT-2,API 2.28

对于 OT-2 API 2.15 及以上版本，建议加上 `requirements` 代码块。OT-2 在 12 号槽位有一个固定废料桶；不要调用 `load_trash_bin()`。

```python
from opentrons import protocol_api

metadata = {
    "protocolName": "OT-2 transfer",
    "author": "Your Name",
}
requirements = {"robotType": "OT-2", "apiLevel": "2.28"}


def run(protocol: protocol_api.ProtocolContext) -> None:
    tips = protocol.load_labware("opentrons_96_tiprack_300ul", "1")
    reservoir = protocol.load_labware("nest_12_reservoir_15ml", "2")
    plate = protocol.load_labware("nest_96_wellplate_200ul_flat", "3")
    pipette = protocol.load_instrument(
        "p300_single_gen2", "left", tip_racks=[tips]
    )
    pipette.transfer(100, reservoir["A1"], plate["A1"])
```

当一份协议必须在软件版本参差不齐的机器人群中运行时，应使用能提供所需全部功能的最低 API 级别。只有当工作流确实需要其行为或能力时，才使用当前的最高级别。

## 编写工作流程

### 1. 选定机器人和 API 级别

在 App 的机器人高级设置中检查支持的最高 API。使用 `references/api_reference.md` 把每一项所需功能对应到它所需的最低 API 级别。

重要的版本节点：

- 2.20：CSV 运行时参数、液体存在检测、扩展的部分喷嘴布局。
- 2.21：吸光度读板仪(Absorbance Plate Reader)。
- 2.22：当前的耗材级液体加载方法。
- 2.23:液面位置(meniscus location)与耗材盖(labware lids)。
- 2.24：液体分类(liquid classes)与液体分类复合命令。
- 2.25：Flex Stacker 与 Flex 96 通道 200 µL 移液器。
- 2.27：动态移液与并发模块操作。
- 2.28：20 µL Flex 吸头、改进的部分吸头归还，以及热循环仪(thermocycler)升降温速率控制。
- 2.29:步骤分组(step grouping);在当前验证基线下仅限 Flex。

### 2. 显式构建甲板

- 使用官方耗材库(Labware Library)中的确切加载名称。
- 显式加载 Flex 废料桶或废料槽。
- 需考虑模块的占地面积、暂存槽位、Stacker 穿梭轨道、抓手运动路径，以及高耗材的相邻关系。
- 按文档记录的顺序，在适配器或模块上下文中加载耗材。
- 切勿用名称相近的耗材定义相互替代；几何形状和偏移量是协议安全模型的一部分。

参见 `references/modules_and_deck.md`。

### 3. 选择移液器和吸头

当前的加载名称为：

- Flex：`flex_1channel_50`、`flex_1channel_1000`、
  `flex_8channel_50`、`flex_8channel_1000`、
  `flex_96channel_200`、`flex_96channel_1000`。
- OT-2 GEN2:`p20_single_gen2`、`p20_multi_gen2`、
  `p300_single_gen2`、`p300_multi_gen2`、`p1000_single_gen2`。

检查所需的每一个体积都在所配置移液器和吸头的量程范围内。100 nL 的操作不属于 Opentrons 移液任务的范畴。

### 4. 选择液体处理层级

- 若需要显式控制，使用 `aspirate()`、`dispense()`、`mix()`、`air_gap()`、`blow_out()` 和 `touch_tip()`。
- 对于标准动作，使用 `transfer()`、`distribute()` 和 `consolidate()`。
- 在 Flex 上，对于经 Opentrons 验证过的水性、挥发性或黏稠液体行为，可考虑使用 `transfer_with_liquid_class()`、`distribute_with_liquid_class()` 或 `consolidate_with_liquid_class()`。
- 只有在 API 2.27+ 且已审查过几何布局的情况下，才使用动态起止位置或 `dynamic_mix()`。

在优化吸头使用之前，先梳理污染边界。切勿仅为了减少耗材消耗，而在不相关的样本之间复用同一吸头。参见 `references/liquid_handling.md`。

### 5. 添加初始设置信息与运行时控制

使用 `define_liquid()` 以及耗材级的 `load_liquid()` 或 `load_liquid_by_well()` 来改善初始设置的可视化效果。在 API 2.22+ 的新协议中，不要使用已废弃的 `Well.load_liquid()`。

在 `add_parameters()` 中定义由操作人员控制的数值，并从 `protocol.params` 中读取它们。要验证取值范围，并使用能产生安全、有意义仿真结果的默认值。CSV 参数没有默认值，且每次运行只能选择一个 CSV 参数。

### 6. 资源预算

在仿真之前，需计算：

- 每一条分支路径下所需的吸头或吸头集合数量。
- 源液体积 = 实际交付体积 + 混合损耗 + 废弃体积 + 死体积 + 一份合理的储备量。
- 每次添加和混合之后的最大目标体积。
- 模块、适配器、废料桶和暂存位所需的数量。
- 孵育和模块的时序安排，包括并发任务。

### 7. 分层验证

1. 编译:`python -m py_compile protocol.py`。
2. 使用锁定的软件包版本进行仿真。
3. 检查运行日志中的命令数量、换吸头次数、暂停，以及意外的位置。
4. 导入相应的 App 并要求分析(analysis)成功通过。
5. 检查协议可视化效果、运行时参数默认值、甲板地图、模块设置以及耗材偏移量。
6. 首次使用前，进行一次由操作人员审核的空跑测试(dry run)。

参见 `references/validation_and_operations.md`。

## 常见失败模式

- 使用旧名称，例如 `p300_single_flex`;应使用当前的 `flex_*` 加载名称。
- 在 `metadata` 和 `requirements` 中同时声明 `apiLevel`。
- 在 OT-2 上使用 API 2.29。
- 忘记加载 Flex 废料桶或废料槽。
- 在 Flex 上加载磁力模块(Magnetic Module);应使用受支持的 Flex 磁力硬件。
- 在读板仪上调用 `read(wavelengths=...)`;应先调用 `initialize()`,再调用 `read()`。
- 使用已废弃的 `Well.load_liquid()`,而不是耗材级方法。
- 误以为仿真能验证校准、液面高度或物理间隙。
- 向部分喷嘴移液器传入不安全的孔位，可能导致吸头落到耗材之外并造成碰撞。
- 在对污染要求互不兼容的样本之间使用 `new_tip="once"`。

## 内置模板

| 文件 | 用途 |
| --- | --- |
| `scripts/basic_protocol_template.py` | 使用当前名称的最简 Flex 2.29 转移协议 |
| `scripts/ot2_basic_protocol_template.py` | 最简 OT-2 2.28 转移协议 |
| `scripts/serial_dilution_template.py` | 使用 8 通道 Flex 移液器进行全板 1:2 稀释 |
| `scripts/pcr_setup_template.py` | Flex PCR 设置与热循环仪循环控制 |
| `scripts/runtime_parameters_template.py` | 安全的数值型与布尔型运行时参数 |
| `scripts/absorbance_reader_template.py` | 正确的 Flex 读板仪初始化与读数工作流 |

这些模板是起点，而不是经过验证的实验方案。只有在核实过硬件兼容性和湿实验方法之后，才能替换体积、耗材、液体、时序和吸头策略。

## 参考指南

| 参考文档 | 用途 |
| --- | --- |
| `references/api_reference.md` | 当前加载名称、版本节点，以及高价值方法 |
| `references/protocol_authoring.md` | 需求声明(requirements)、耗材、运行时参数与设计工作流 |
| `references/liquid_handling.md` | 命令选择、液体分类、传感检测与部分吸头 |
| `references/modules_and_deck.md` | 模块兼容性、甲板固定装置、抓手与 Stacker |
| `references/validation_and_operations.md` | 仿真、App 分析、空跑测试与故障排查 |
| `references/migration-api-2-19-to-2-29.md` | 更新旧协议以及本技能此前使用的模式 |
| `references/sources.md` | 官方文档与发布信息来源 |
