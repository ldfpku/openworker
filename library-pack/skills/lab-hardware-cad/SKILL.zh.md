# Lab Hardware CAD（实验室硬件 CAD）

将物理研究硬件设计为**参数化 Python 源码**，导出 STEP 作为权威工件（authoritative artifact），并在任何东西被送去加工之前，对结果同时做数值校验和视觉校验。

实验室硬件设计中最难的部分几乎从来都不是几何形状本身。难点在于该零件必须与那些尺寸由已发布标准或供应商图纸固定下来的设备相配合。宽了 0.5 mm 的支架装不进读板机；通道纵横比不对会在键合过程中塌陷；螺栓孔间距是 25.4 mm 而不是 25.0 mm 的安装座够不到光学平台。这个技能的存在，就是为了让这些数字保持正确并被检查过。

## 何时使用

任何要求设计、建模或加工实验室物理零件的请求都应使用本技能:芯片、模具、安装座、适配器、支架、试管架、支架托架、外壳、夹具、治具、动物行为竞技场或迷宫。检查或修改已有的 STEP 文件时也应使用。

**不要**用于有限元分析、计算流体力学、分子结构或科学绘图。那些是不同的技能。

## 环境搭建

```bash
uv venv --python 3.12 .venv-labcad
uv pip install --python .venv-labcad/bin/python "build123d==0.11.1" "matplotlib>=3.8"
```

build123d 0.11.1 需要 Python >=3.10,<3.15,并通过 `cadquery-ocp-novtk` 引入 OpenCascade 内核。该 wheel 包体积较大；每个项目安装一次并复用即可。

所有内置脚本都支持 `--help`。`check.py standards` 无需安装 build123d 即可运行。

**模型文件是被执行的，不是被解析的**。 `gen.py`、`check.py` 和 `snapshot.py` 会导入某个 `*_model.py` 并调用其 `build()`,这会在当前环境中运行任意 Python 代码。这是参数化 CAD 本身固有的特性——源码就是设计本身。只运行在本次会话中编写的、或由用户从可信位置提供的模型文件。如果某个模型来自互联网、共享盘或不受信任的同事，先阅读它再运行，并说明你已经这样做了。

## 必须遵循的工作流程

按顺序执行以下步骤。第 5 步和第 6 步不是可选的，并且第 6 步不会因为第 5 步通过了而被免除。

### 1. 路由到某一设备族

阅读请求，进行分类，并且**只**加载一份设备族参考文档。不要把四份都加载——它们都很长，而且混用不同族之间的约定是常见的出错来源。

| 如果该零件是 | 加载 |
| --- | --- |
| 芯片、模具、通道网络、流通池、垫圈，或任何带流体端口的东西 | `references/microfluidics.md` |
| 安装座、支柱、面包板适配器、笼式系统零件、光路中的滤光片或样品支架 | `references/optomechanics.md` |
| 用于孔板、比色皿、试管、载玻片或培养皿的适配器、内衬、支架或托架 | `references/labware-adapters.md` |
| 动物实验用的竞技场、迷宫、头部固定部件、饮水嘴、系绳，或安装在铝型材上的外壳 | `references/behavior-rigs.md` |

如果该零件确实横跨两个设备族——比如一个要固定到光学平台上的微流控芯片——加载拥有**关键接口**的那一族，然后只读第二份文档中与接口相关的部分。在回复中说明你路由到了哪个设备族。

### 2. 在动手做任何几何建模之前先确定接口尺寸

每个零件至少有一个配合接口。写代码之前，针对每个接口写下:

- 该尺寸的**来源**:一份已发布标准、一份供应商图纸，或一次用户测量;
- **标称值和公差**;
- 你打算采用的**间隙或过盈量**,以及理由。

在 `assets/standards.json` 或设备族参考文档中查这个数字。**永远不要凭记忆写接口尺寸**。 如果这个数字不在标准文件或参考文档中，就向用户索要供应商图纸或实测值，而不要去猜。凭猜测填写接口尺寸，是本技能中代价最高的单一失败模式。

一个必须**容纳**某个标准化组件的特征，应按该组件的**最大实体状态**(maximum material condition,即标称值加上正公差)来定尺寸，然后才在此基础上给出间隙。如果按标称值定尺寸，就只能装下符合公差的那一半较小零件。

```bash
python scripts/check.py standards --list
python scripts/check.py standards --show slas-microplate-footprint
```

内置的标准 ID(精确字符串；不要猜测变体):`slas-microplate-footprint`、`slas-microplate-height`、`slas-microplate-flange`、`slas-well-positions-96`、`slas-well-positions-384`、`slas-well-positions-1536`、`cuvette-standard-10mm`、`optical-breadboard-metric`、`optical-breadboard-imperial`、`cage-system-30mm`、`sm1-lens-tube-thread`。

如果该零件不与列表中的任何东西配合，这很常见也没问题:声明没有接口，并在报告中把每个接口尺寸的来源(用户规格、供应商图纸、实测值)标注为**未经检查**。永远不要为了填补空白而对着一个不相关的标准做声明——一个编造出来的声明比诚实地说"没人检查过这个"更糟糕。

### 3. 先选加工工艺，再选几何形状

阅读 `references/fabrication-limits.md`。加工工艺决定了最小壁厚、最小特征尺寸、可达到的公差，以及零件能否承受高压灭菌或接触你所用的溶剂。FDM 无法保持 ±0.05 mm 的公差;SLA 树脂在未经后固化和测试之前通常不适合接触细胞。把加工工艺和材料记录在模型的文档字符串(docstring)里。

### 4. 编写参数化模型

编写 `<part>_model.py`。源码是权威工件——**永远不要手工编辑导出的 STEP 文件**,也永远不要从网格(mesh)重新生成。

要求:

- 用户可能会更改的每个尺寸都是一个**模块级命名常量**,名字中带单位:`bore_d_mm`、`wall_t_mm`、`post_h_mm`。除了 0、1、2 之外，函数体内不允许出现裸数字。
- 暴露 `build() -> Part`。`gen.py` 会调用它。
- 把参数分组为一个 `INTERFACE` 块(由标准固定的尺寸，并标注标准 ID)和一个 `DESIGN` 块(你可以自由选择的尺寸)。
- **在函数内部推导每一个计算得出的尺寸**,永远不要在模块级别推导，这样 `--param` 的覆盖才能真正生效。
- 声明一个 `interfaces()` 函数，返回该零件必须配合的尺寸，每一项都带有其标准 ID 和意图(intent)。这就是让接口在第 5 步中可被机器检查的关键。当某特征必须**容纳**任何符合规格的零件时(一个凹槽、孔或槽——按最大实体状态加上你的间隙做单边检查),`intent` 为 `"envelope"`;当该零件自身必须符合规格时(对称带),`intent` 为 `"match"`。`clearance` 是以毫米为单位的总间隙，必须是非负数。只声明约束**这个零件本身配合特征**的尺寸——配合设备的某个属性(比如工作台的边缘留白、典型孔板厚度)不是你的接口。如果没有适用的内置标准，返回 `[]`。
- 声明一个 `checks()` 函数，里面是从已构建实体上测得的**通过/不通过量规**:对所有必须能穿过或装入的东西(螺丝杆、光路走廊、处于最大实体状态的配合零件落入其凹槽)用 `clear` 区域，对所有必须保留的材料(凸棱、台阶、螺丝座)用 `material` 区域，以及对用户提出的每一个尺寸限制用 `bbox_*` 边界。把**请求中的每一条几何要求**都映射为一条记录；这些能捕捉到 `is_valid`、包围盒和声明数字都看不出来的错误。`gen.py` 在每次生成时都会运行它们，并在有一项失败时使构建失败。模式(schema)和实例见 `references/build123d-patterns.md`。
- 把加工工艺、材料以及每个接口的来源都写进模块文档字符串。

```python
"""SLAS microplate carrier for a custom stage insert.

Process: FDM, PETG, 0.2 mm layer.  Tolerance budget +/-0.3 mm.
Interfaces:
  - Plate pocket: ANSI/SLAS 1-2004 (R2012) footprint 127.76 x 85.48 mm, +/-0.25.
  - Stage bolts: user-measured, 40.0 mm centres (drawing in docs/stage.pdf).
"""
from build123d import *

# --- INTERFACE (fixed by standard; do not tune) ---
plate_l_mm = 127.76   # ANSI/SLAS 1-2004 nominal
plate_w_mm = 85.48    # ANSI/SLAS 1-2004 nominal
plate_tol_mm = 0.25   # ANSI/SLAS 1-2004; the pocket is sized to nominal + this
# --- DESIGN (free) ---
pocket_clearance_mm = 0.40   # per-side; FDM, see fabrication-limits.md
wall_t_mm = 3.0
floor_t_mm = 2.5
body_h_mm = 12.0


def pocket_mm() -> tuple[float, float]:
    """Pocket at the plate's maximum material condition plus clearance per side.

    A pocket sized from nominal jams on roughly half of conforming plates.
    """
    growth = plate_tol_mm + 2 * pocket_clearance_mm
    return plate_l_mm + growth, plate_w_mm + growth


def interfaces() -> list[dict]:
    """What this part must fit. `check.py interfaces` verifies every entry."""
    pocket_l, pocket_w = pocket_mm()
    return [
        {"feature": "plate pocket length", "standard": "slas-microplate-footprint",
         "dimension": "footprint_length", "value": pocket_l,
         "intent": "envelope", "clearance": 2 * pocket_clearance_mm},
        {"feature": "plate pocket width", "standard": "slas-microplate-footprint",
         "dimension": "footprint_width", "value": pocket_w,
         "intent": "envelope", "clearance": 2 * pocket_clearance_mm},
    ]


def checks() -> list[dict]:
    """Gauges measured from the built solid. Sized from the REQUIREMENT's numbers
    (plate MMC, the user's height limit), not from the pocket parameters, so a
    wrong parameter cannot shrink the gauge to match the wrong geometry."""
    depth = body_h_mm - floor_t_mm
    return [
        {"feature": "plate at MMC drops into the pocket",
         "clear": {"box": (plate_l_mm + plate_tol_mm, plate_w_mm + plate_tol_mm, depth),
                   "at": [(0.0, 0.0, floor_t_mm + depth / 2)]}},
        {"feature": "under 15 mm for the stage", "bbox_z": {"max": 15.0}},
    ]


def build() -> Part:
    pocket_l, pocket_w = pocket_mm()
    with BuildPart() as carrier:
        Box(pocket_l + 2 * wall_t_mm, pocket_w + 2 * wall_t_mm, body_h_mm,
            align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, 0, floor_t_mm)):
            Box(pocket_l, pocket_w, body_h_mm, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
    return carrier.part
```

关于 builder 风格与 algebra 风格的选择、`interfaces()` 的约定、草图绘制、选择器、圆角以及螺纹嵌件孔，参见 `references/build123d-patterns.md`。

### 5. 生成并运行检查

```bash
python scripts/gen.py carrier_model.py --outdir out/
python scripts/check.py facts out/carrier.step
python scripts/check.py interfaces out/carrier.manifest.json
python scripts/check.py geometry out/carrier.step --model carrier_model.py
```

`gen.py` 还会针对它刚构建出的实体评估模型的 `checks()` 量规，打印每一项的 PASS/FAIL,把它们记录进清单(manifest),并在有失败项时以非零状态退出——所以一个违反自身声明几何约束的零件永远不会悄悄地变成一个工件。`check.py geometry` 会针对导出的 STEP(即权威工件)重新运行同一组量规。

`out/` 只是一个临时目录的约定，不是硬性要求。当用户要求把交付物放在特定位置时，就在那里生成(`--outdir .`),或者在结束前把 STEP、清单和 DXF 复制过去——一个只存在于 `out/` 里面的交付物，并不算真正交付。

`gen.py` 会写出 `carrier.step`(权威文件)、`carrier.stl`(网格预览及打印用)和 `carrier.manifest.json`(记录源码哈希、解析后的参数、声明的接口、库版本，以及测得的包围盒、体积和有效性)。这份清单就是溯源记录——要和工件一起保存。

`check.py facts` 报告 `is_valid`、包围盒、体积、表面积、质心和实体数量。一个报告 `is_valid: false` 的零件是有问题的几何体；在继续之前先修复源码。

`check.py interfaces` 会对照标准数据库评估模型声明的每一项，并在失败时以非零状态退出。**要清楚它检查的是什么、不检查的是什么**: 它检查的是*声明出来的数字*——能捕捉到抄错的尺寸、用错的标准、按标称值而非最大实体状态定尺寸这类问题——但它从不测量实际构建出来的几何体，而且一个由同一批常量计算出来、又拿去和这批常量做检查的值，天然就会以零余量通过。不要拿它作为几何形状正确的证据;`facts` 和快照才是几何检查。空的声明列表也会通过检查:一个不与内置数据库中任何东西配合的零件没有什么可声明的，它的接口尺寸应改为在报告中标注为未经检查。

对于内部特征——凹槽、孔或槽——请使用 `interfaces` 而不是 `check.py fit`,因为这些特征不会出现在零件的外部包围盒里，而 `fit` 测量的正是包围盒。只在需要手动检查单个数字时(`--value footprint_length=128.81`)才使用 `fit`,或者是当零件本身的外轮廓就是接口时，比如按孔板底座轮廓切割的垫圈。

对于组件装配，检查零件之间是否互相干涉:

```bash
python scripts/check.py clearance out/carrier.step out/lid.step --min 0.3
```

### 6. 生成快照并亲自查看

```bash
python scripts/snapshot.py out/carrier.step --out out/carrier.png
```

然后**阅读这张 PNG 图片**。每次生成和每次修改之后，这一步都是必须的。确定性检查通过并不是跳过这一步的理由:`is_valid` 和正确的包围盒完全可以与"凹槽切在了错误的面上""凸台放在了本体外面""圆角吃掉了某个特征"这类问题同时成立。这些错误在图片里一目了然，在数字里却毫无踪迹。

同时也要了解渲染图的局限性。一个远小于画面尺寸的特征——40 mm 零件上一道 0.3 mm 的模具凸棱、孔板上的一处沉孔台阶——可能从任何视图都根本判断不出来。不要报告说你看到了图片其实无法分辨的东西；那比压根不看还糟糕。对于这类特征，本技能提供了专用工具:`check.py bores` 会打印每一个圆柱面(直径、轴线、位置、跨度、扫掠角),供你核对实际钻孔与模型意图是否一致;`check.py probe` 能一次性回答"这个区域是空的还是有材料"这类问题，而无需修改模型。引用测得的数字；从图片中只报告图片真正显示出来的内容。

六个视图是真正的正交投影，且轮廓线是模型的真实边线,**未做隐藏线消除**。所以一个"透过"材料可见的圆圈，是远端的一个孔，而不是一扇窗口——这个零件并不是透明的。应按这个方式解读，而不是报告出一个根本不存在的孔。

在回复中说明你在快照中实际看到了什么，而不只是说你生成了一张快照。

### 7. 通过源码修复

如果任何检查失败，修改参数或模型代码，重新运行 `gen.py`,然后**同时**重新执行第 5 步和第 6 步。永远不要直接修补 STEP 文件。

### 8. 加工之前先报告

按照 `references/validation.md` 逐项过一遍，并向用户提供:加工工艺和材料、每一个接口尺寸及其来源和公差、所选用的间隙、快照中看到的内容，以及任何未通过的检查。

明确标出每一个自动检查无法覆盖的接口——一份供应商图纸、一次用户测量，或一个不在内置数据库中的标准。`check.py interfaces` 只报告模型对照已知标准所声明的内容，所以它的沉默不代表已经确认；一个没人能检查的尺寸必须被明确标注出来。

## 单位

build123d 内部是无单位的，而本技能中一切都是**毫米和度**。调用 `export_step` 时使用 `Unit.MM`。光机部件中普遍存在英制硬件(1/4-20 螺钉、1 英寸网格、SM1 螺纹);在定义处用一个命名常量一次性转换为毫米，永远不要在同一个表达式内混用两种单位制。1 英寸精确等于 25.4 mm,而 25 mm 的公制光学网格**不能**与 1 英寸的英制网格互换——这个误差在四个孔之后会累积到 1.6 mm。

## 公差与配合

标称尺寸不等于配合关系。每一个配合尺寸都需要根据 `references/fabrication-limits.md` 中的加工工艺公差，刻意选定一个间隙。常见默认值(单边):

| 配合类型 | FDM | SLA | CNC |
| --- | --- | --- | --- |
| 自由滑动(孔板放入凹槽) | 0.40 mm | 0.20 mm | 0.10 mm |
| 定位但可拆卸 | 0.25 mm | 0.10 mm | 0.05 mm |
| 压装/过盈配合 | -0.05 mm | -0.03 mm | -0.02 mm |

这些是首件试制的起点，不是保证值。在报告这些数字时要说明这一点，并建议在投入整件加工之前，先打印一份关键接口的测试样片。

## 科学注意事项

- **材料兼容性是决定性因素**。 一个几何上完美的零件，如果材料选错了，实际使用中仍会失败:高压灭菌循环会使 PLA 变形，许多溶剂会使亚克力开裂，未固化的 SLA 树脂对细胞有毒性。在为任何接触细胞、组织、溶剂或高温的场景推荐材料之前，先查阅 `references/fabrication-limits.md`。
- **光学部件有非几何性的要求**。 自发荧光、表面粗糙度和杂散光散射不会体现在 STEP 文件里。黑色树脂不会自动等于低散射。
- **供应商耗材各不相同**。 SLAS 标准固定了孔板的底座轮廓，但没有固定孔的几何形状、裙边轮廓或盖子的配合方式，而且不同供应商的耗材试管也各不相同。有标准可依时按标准设计；否则就要求实测。
- **通过包围盒检查不等于零件合格**。 `fit` 只检查交给它的那些尺寸。它看不到缺失的特征，也不能替代快照检查。

## 参考文档

| 文件 | 内容 |
| --- | --- |
| `references/microfluidics.md` | 通道截面与纵横比、模具与芯片的极性关系、按工艺划分的最小特征尺寸、端口与管路接口、键合边缘、死体积 |
| `references/optomechanics.md` | 面包板网格与螺钉间隙、支柱与底座高度、30 mm 笼式系统几何、SM 镜筒螺纹、光束高度 |
| `references/labware-adapters.md` | ANSI/SLAS 1-4 孔板尺寸、比色皿、试管、载玻片、培养皿、机台与工作台约束 |
| `references/behavior-rigs.md` | 竞技场与迷宫几何、头部固定接口、饮水嘴与端口、T 型槽铝型材、清洁与耐用性 |
| `references/fabrication-limits.md` | 加工工艺公差、最小壁厚与最小特征、间隙与螺纹嵌件、材料、高压灭菌与耐溶剂性及生物相容性 |
| `references/validation.md` | 加工前检查清单及每一项能捕捉的失效模式 |
| `references/build123d-patterns.md` | build123d 0.11.1 API 速查手册:builder 风格与 algebra 风格、草图、选择器、连接件、导出 |

## 脚本

| 命令 | 用途 |
| --- | --- |
| `gen.py <model.py> --outdir DIR` | 运行 `build()`,导出 STEP 和 STL,写出溯源清单 |
| `gen.py <model.py> --dxf [--dxf-z MM]` | 同时切出用于激光切割的 2D DXF 剖面(默认平面:中高位置) |
| `check.py facts <step>` | 有效性、包围盒、体积、面积、质心、实体数量 |
| `check.py interfaces <manifest\|model.py>` | 对照标准检查每一个声明的接口数字；失败时非零退出 |
| `check.py geometry <model.py\|step --model M>` | 针对已构建实体评估模型的 `checks()` 量规——是测量结果，而非声明内容 |
| `check.py probe <step> --cyl D\|--box X,Y,Z --at ...` | 单次的临时量规:该区域是无材料的，还是被材料填充的 |
| `check.py bores <step>` | 每一个圆柱面的普查:直径、轴线、位置、跨度、扫掠角 |
| `check.py fit --standard ID --value DIM=MM` | 手动检查单个尺寸，或检查外部轮廓即为接口的零件 |
| `check.py clearance <a> <b> --min MM` | 两个实体之间的最小距离；用于检测干涉 |
| `check.py standards [--list\|--show ID]` | 浏览内置的标准数据(仅需标准库) |
| `snapshot.py <step> --out PNG` | 六视图正交及等轴测渲染，供视觉审查 |

所有命令都接受 `--json` 以输出机器可读结果，并把进度信息写到 stderr。`check.py standards`,以及针对清单文件运行的 `check.py interfaces`,都无需安装 build123d 即可运行。
