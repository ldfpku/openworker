# PyLabRobot

使用 PyLabRobot 与硬件无关的前端、资源树（resource tree）、跟踪器（tracker）以及
设备专用后端来开发实验室自动化流程。默认应使用本地清单验证、记账（bookkeeping）
以及纯软件的 chatterbox 后端。

## 已核实的版本快照

- PyPI 稳定版：**`PyLabRobot==0.2.1`**，发布于 **2026-03-23**。
- 上游要求：**Python >=3.9**。此技能为可复现的冒烟测试使用 Python 3.11。
- `/stable/` 文档自我标注为 0.2.1 版本。`/dev/` 及代码仓库
  `main` 分支描述的是尚未发布的开发内容，不得假定其在 0.2.1 中可用。
- 稳定版的液体处理（liquid-handler）后端包括 `STARBackend`、`VantageBackend`、
  `EVOBackend`、`OpentronsOT2Backend`，以及离线的
  `LiquidHandlerChatterboxBackend`。
- PyLabRobot 的 GitHub Releases 页面没有 0.2.x 软件发行条目；应以
  PyPI 历史记录、`v0.2.1` 标签及更新日志作为发布证据。

## 不可协商的硬件边界

绝不可自动连接、初始化、归位（home）、移动、加热、振荡、旋转、泵送、开/关，
或以其他方式控制物理设备。不得仅通过更改环境变量、配置值或导入语句，
就把模拟计划变成实时后端。

在任何单独获得授权的实时运行之前，须要求受过训练的操作人员：

1. 明确确认具体的后端、设备身份、固件、传输方式、
   甲板（deck）及方案（protocol）版本。
2. 将物理甲板与资源树进行核对，包括载具（carrier）、
   适配器、盖子、板、吸头架（tip rack）、废液区、耗材摆放方向、条码，
   以及每一个已占用的坐标位置。
3. 验证标定、示教、运动包络（motion envelope）、碰撞风险、
   夹爪或通道间隙，以及所有吸液/分液坐标。
4. 核查液源身份及实际装液量、死体积（dead volume）、目标容量、
   吸头类型/容量/滤芯兼容性、通道映射、单位、
   高度、速率、液体类别、吹扫/混匀，以及污染防控边界。
5. 确认防护装置、门、废液容量、密闭性、急停就绪状态、
   个人防护装备（PPE）、生物安全/化学品管控，以及安全的中止/恢复流程。
6. 在任何新增或变更的情况下，批准一次缓慢的空跑（dry run）或
   无危害的调试运行。

跟踪器（tracker）状态是**记账**，不是感知。它无法证明液体或吸头
是否物理存在。可视化工具（Visualizer）渲染的是资源/跟踪器事件；它
不模拟物理过程。Chatterbox 打印的是计划中的操作；它不能证明
标定、可达性、无碰撞、液体行为或设备状态。

## 必需的前期信息

不得对以下任何一项进行猜测：

- 确切的设备型号、已安装的选装件、固件、计算机/操作系统及传输方式。
- 稳定的 PyLabRobot 版本及所需的额外扩展包（extras）。
- 甲板/甲板原点、载具、适配器、资源定义、尺寸、
  坐标、朝向及运动间隙。
- 板/管/储液槽容量及死体积；初始物理装液量。
- 吸头型号、滤芯、配合方式、容量、吸头架状态、通道数及通道
  映射关系。
- 转移单位（`uL`、`mm`、`uL/s`、`s`）、高度、速率、混匀、气隙、
  吹扫、液体特性，以及经验证的厂商液体类别。
- 污染防控政策、管控措施、废液处理、操作人员干预方式、
  验收标准及恢复流程。

如果信息缺失，只应生成一份假设/阻塞项清单以及一份离线草稿。

## 可复现的安装方式

用于离线 API 检查和 chatterbox 模拟：

```bash
uv venv --python 3.11 .venv-pylabrobot
uv pip install --python .venv-pylabrobot/bin/python "PyLabRobot==0.2.1"
```

在 Windows 上，请使用 `.venv-pylabrobot\Scripts\python.exe`。在用户
指明设备并明确批准其传输依赖之前，不得安装硬件扩展包。之后，
在考虑固定诸如 `"PyLabRobot[serial]==0.2.1"` 或 `"PyLabRobot[usb]==0.2.1"`
这样的版本之前，应先查阅对应的稳定版设备文档页面。

## 以离线为先的工作流

从代码仓库根目录运行。每个随附的 CLI 都使用严格且有边界限制的 UTF-8
JSON/CSV、本地非符号链接路径、固定的允许列表（allowlist）以及 JSON 输出。
它们都不能选择实时后端。

```bash
python3 skills/pylabrobot/scripts/validate_manifest.py \
  --input tests/pylabrobot/fixtures/protocol_manifest.json

python3 skills/pylabrobot/scripts/check_deck_geometry.py \
  --input tests/pylabrobot/fixtures/protocol_manifest.json

python3 skills/pylabrobot/scripts/plan_transfers.py \
  --manifest tests/pylabrobot/fixtures/protocol_manifest.json \
  --transfers tests/pylabrobot/fixtures/transfers.csv

python3 skills/pylabrobot/scripts/generate_simulation_plan.py \
  --manifest tests/pylabrobot/fixtures/protocol_manifest.json \
  --transfers tests/pylabrobot/fixtures/transfers.csv

python3 skills/pylabrobot/scripts/inspect_backends.py \
  --expected-version 0.2.1 --strict
```

几何检查工具使用的是保守的、坐标轴对齐的静态包围盒；它不是一个
运动规划器。转移规划工具要求每一行使用一个新吸头，并检查
源体积/死体积/目标体积、吸头容量、孔位、通道、高度、速率、
单位及允许列表。在制作项目专用清单之前，请先查阅
`assets/protocol-manifest.schema.json` 以及合成测试数据（fixture）。

## 已验证的纯软件示例

下面这个确切的后端是纯软件实现的。不得替换为硬件后端。

```python
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
from pylabrobot.resources import (
    Cor_96_wellplate_360ul_Fb,
    PLT_CAR_L5AC_A00,
    TIP_CAR_480_A00,
    hamilton_96_tiprack_1000uL_filter,
    set_tip_tracking,
    set_volume_tracking,
)
from pylabrobot.resources.hamilton import STARLetDeck

set_tip_tracking(True)
set_volume_tracking(True)

deck = STARLetDeck()
tip_carrier = TIP_CAR_480_A00(name="tip_carrier")
tips = hamilton_96_tiprack_1000uL_filter(name="tips")
tip_carrier[0] = tips
plate_carrier = PLT_CAR_L5AC_A00(name="plate_carrier")
source = Cor_96_wellplate_360ul_Fb(name="source")
destination = Cor_96_wellplate_360ul_Fb(name="destination")
plate_carrier[0] = source
plate_carrier[1] = destination
deck.assign_child_resource(tip_carrier, rails=3)
deck.assign_child_resource(plate_carrier, rails=15)
source.get_well("A1").tracker.set_volume(100.0)  # planned state, not sensing

lh = LiquidHandler(backend=LiquidHandlerChatterboxBackend(), deck=deck)
await lh.setup()  # safe here only because the backend above is software-only
try:
    await lh.pick_up_tips(tips["A1"])
    await lh.aspirate(source["A1"], vols=[10.0])
    await lh.dispense(destination["A1"], vols=[10.0])
    await lh.return_tips()
finally:
    await lh.stop()
```

## 可避免过时代码的 API 规则

- 当前名称为 `STARBackend`、`VantageBackend`、`EVOBackend` 和
  `OpentronsOT2Backend`；不要使用过时的 `STAR`、`TecanBackend`、
  `OpentronsBackend` 或 `ChatterboxBackend` 导入方式。
- 通用的离线液体处理测试应使用 `LiquidHandlerChatterboxBackend`。
  `ChatterBoxBackend` 是另一个使用旧命名的独立导出项；不要将两者混淆。
- `Visualizer(resource=...)` 是有效的用法，随后应调用 `await vis.setup()` 和
  `await vis.stop()`；它会启动 localhost 上的 HTTP/WebSocket 服务器，并可能
  打开浏览器。
- 0.2.1 中不存在通用的 `from pylabrobot.liquid_handling import LiquidClass`。
  稳定版中的液体类别是厂商专属的，例如
  `pylabrobot.liquid_handling.liquid_classes.hamilton.HamiltonLiquidClass`。
- 大多数前端方法都是异步的。后端的关键字参数和能力是
  厂商/型号专属的；共享的前端并不意味着行为完全一致。

## 参考资料

- [液体处理（Liquid handling）](references/liquid-handling.md) —— 操作、吸头、跟踪、
  液体类别、单位及验证。
- [资源（Resources）](references/resources.md) —— 甲板、坐标、板、吸头架、
  碰撞、状态及序列化。
- [硬件后端（Hardware backends）](references/hardware-backends.md) —— 已验证的名称、
  支持级别、能力及实时运行关口。
- [分析设备（Analytical equipment）](references/analytical-equipment.md) —— 读板机
  及天平。
- [物料处理（Material handling）](references/material-handling.md) —— 泵、加热器、
  振荡器、温度控制、存储及离心机。
- [可视化（Visualization）](references/visualization.md) —— chatterbox、Visualizer、
  localhost 服务及模拟限制。

## 带日期的上游来源

于 **2026-07-23** 核实：

- [PyPI 0.2.1](https://pypi.org/project/PyLabRobot/) —— 发布于 2026-03-23；
  Python >=3.9；扩展包及构件。
- [稳定版安装指南](https://docs.pylabrobot.org/stable/user_guide/_getting-started/installation.html)
  —— 稳定版与源码/开发版安装方式的区别，以及可选的传输方式扩展组。
- [稳定版 API](https://docs.pylabrobot.org/stable/api/pylabrobot.html) 及
  [支持的设备](https://docs.pylabrobot.org/stable/user_guide/machines.html)
  —— 0.2.1 版 API 及各型号专属的支持标签。
- [`v0.2.1` 源码标签](https://github.com/PyLabRobot/pylabrobot/tree/v0.2.1)
  及[更新日志](https://github.com/PyLabRobot/pylabrobot/blob/main/CHANGELOG.md)
  —— 标签日期为 2026-03-23；`Unreleased`（未发布）部分仅为开发中内容。
