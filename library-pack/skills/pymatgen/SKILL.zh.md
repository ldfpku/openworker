# pymatgen

使用 pymatgen 对成分（composition）、分子（molecule）、周期性结构（periodic structure）、计算条目（computed entry）、对称性、相图，以及电子结构和电子结构计算软件文件进行显式的、保留来源信息（provenance-preserving）的工作。将每一次解析、转换、对称性判定、变换，以及数据库查询结果都视为依赖于所用方法与参数的。

frontmatter 中的 MIT 许可证覆盖本技能本身。`pymatgen` 和
`pymatgen-core` 采用 MIT 许可证；`mp-api` 声明为 BSD-3-Clause-LBNL。Materials Project
的数据通常采用 CC BY 4.0 许可，而由用户贡献的数据其所有权仍归贡献者本人所有。在再分发之前请核实具体产物和数据的许可条款。

## 已验证的版本快照（2026-07-23）

- `pymatgen==2026.5.4` 是最新的稳定包装层（wrapper）版本（发布于 2026-05-04）。
  该软件包元数据要求 Python 3.11+，并直接依赖
  `pymatgen-core>=2026.4.16`。
- `pymatgen-core==2026.7.16` 是最新的稳定核心（core）版本（发布于 2026-07-16）。
  它现在包含核心对象、对称性/晶格操作，以及 I/O 层，
  全部位于既有的 `pymatgen.*` 命名空间下。
- `mp-api==0.46.4` 是最新的稳定 Materials Project 客户端
  （发布于 2026-06-15），要求 Python 3.11+，并依赖于
  `pymatgen>2024.2.20`。
- 当前的 API 文档站点是基于 2026.7.16 版本的核心文档构建的。将两个发行包都固定版本，
  可以避免 `pymatgen==2026.5.4` 悄悄解析到未来某个不同的核心版本。
- Pymatgen 使用基于日期的版本号。PyPI 用点号来渲染日期；不要从这些数字中
  推断语义化版本（semantic-version）意义上的兼容性。

创建一个项目锁文件以保证可复现性：

```bash
uv init --python 3.11
uv add "pymatgen==2026.5.4" "pymatgen-core==2026.7.16" "mp-api==0.46.4"
uv lock
uv sync --frozen
```

若需要一个用后即弃、经过审查的环境：

```bash
uv venv --python 3.11 .venv-pymatgen
uv pip install --python .venv-pymatgen/bin/python \
  "pymatgen==2026.5.4" "pymatgen-core==2026.7.16" "mp-api==0.46.4"
```

直接固定版本号并不能冻结所有传递依赖（transitive）的 wheel 包。请保留
`uv.lock`、平台信息、Python 版本、软件包版本，以及产物哈希值。

## 必须遵循的工作流程

1. 说明该对象是非周期性的 `Molecule` 还是周期性的
   `Structure`；记录晶格（lattice）和周期性边界条件。
2. 说明单位。Pymatgen 通常使用 Å、度、eV、eV/atom、amu 和
   g/cm³，但以每个 API 文档中记载的约定为准。
3. 说明坐标模式。`Structure` 的坐标除非设置了
   `coords_are_cartesian=True`，否则为分数坐标（fractional）；`Molecule` 的坐标为笛卡尔坐标（Cartesian）。
4. 检查每一条解析器警告。对于 CIF，要保留占据率（occupancy）、位点合并（site-merging）、
   化学计量比（stoichiometry）和校正相关的警告；不要悄悄接受这些修正。
5. 报告无序性/部分占据情况以及氧化态标注。切勿
   隐式地猜测氧化态。
6. 在进行对称性、近邻、变换、转换或热力学分析之前先运行验证。
7. 对对称性容差（tolerance）进行扫描，并在每次判定时报告以 Å 为单位的
   `symprec` 和以度为单位的 `angle_tolerance`。
8. 将变换视为新的产物（artifact）。保留输入、参数、
   软件版本、警告，以及父/子校验和（checksum）。
9. 在转换之前先识别表示信息（representation）会有哪些损失。只写入新路径，
   并对科学上相关的属性进行往返校验（round-trip check）。
10. 只使用彼此兼容的总能量和校正方案来构建相图。计算出的凸包（hull）
    结果是以所提供的条目集合为条件的。
11. 默认关闭所有数据库访问。在执行显式的执行步骤之前，先说明
    端点、过滤条件、字段、结果数量上限、缓存行为、输出、许可证，以及引用方式。
12. 保留一份产物清单（artifact manifest）。切勿使用 pickle,也不要加载不可信的
    通用对象图；应使用经过 schema 校验的 JSON 和显式的构造函数。

## 核心对象

使用公开的便捷导入方式：

```python
from pymatgen.core import Composition, Element, Lattice, Molecule, Structure

composition = Composition("LiFePO4", strict=True)
iron = Element("Fe")

lattice = Lattice.cubic(5.64)  # Å
structure = Structure(
    lattice,
    ["Na", "Cl"],
    [[0, 0, 0], [0.5, 0.5, 0.5]],
    coords_are_cartesian=False,
    validate_proximity=True,
)

molecule = Molecule(
    ["O", "H", "H"],
    [[0.0, 0.0, 0.0], [0.758, 0.0, 0.504], [-0.758, 0.0, 0.504]],
    charge=0,
    spin_multiplicity=1,
)
```

`Structure` 和 `Molecule` 是可变（mutable）的；当可变性会损害来源信息（provenance）时，
应使用 `IStructure`/`IMolecule` 或显式地做一份拷贝。参见
[核心类（core classes）](references/core_classes.md)。

## 安全的本地结构导入

优先使用附带的验证器，它会捕获 CIF 与 Python 的警告，
并报告单位、占据率、无序性、氧化态、周期性、坐标模式，以及最小原子间距：

```bash
python scripts/composition_structure_validator.py composition "Fe2O3"
python scripts/composition_structure_validator.py structure structure.cif
python scripts/structure_analyzer.py structure.cif --symmetry
```

如需直接处理 CIF，请使用当前的解析器方法，并检查两个警告通道：

```python
import warnings
from pymatgen.io.cif import CifParser

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    parser = CifParser("input.cif", check_cif=True)
    structures = parser.parse_structures(
        primitive=False,
        check_occu=True,
        on_error="raise",
    )

parser_messages = list(parser.warnings)
python_messages = [str(item.message) for item in caught]
```

不要在特权进程中解析不可信的文件。一个严重的、可通过恶意 CIF 文件触发代码执行的漏洞
影响了 2024.2.8 及之前的版本，已在 2024.2.20 中修复；本技能固定使用的版本更新，
但解析器仍然会处理攻击者可控的输入。请使用隔离环境，以及 CPU/内存/磁盘/时间上的限制。

## 对称性

空间群（space group）的判定结果依赖于容差（tolerance）和结构质量：

```python
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

analyzer = SpacegroupAnalyzer(
    structure,
    symprec=0.01,          # Å
    angle_tolerance=5.0,   # degrees
)
symbol = analyzer.get_space_group_symbol()
number = analyzer.get_space_group_number()
```

Materials Project 的处理流程通常使用 `symprec=0.1 Å`，而 pymatgen 文档记载的
默认值是 `0.01 Å`；这两者可能得出不同的判定结果。
应生成一份敏感性报告，而不是不断改动容差直到出现你偏好的答案：

```bash
python scripts/symmetry_sensitivity_report.py structure.cif \
  --symprec 0.001,0.01,0.1 --angle-tolerance 1,5
```

参见[分析模块（analysis modules）](references/analysis_modules.md)。

## 转换与解析器/写入器 I/O

先做计划；规划器本身不会打开文件，也不会导入 pymatgen：

```bash
python scripts/io_conversion_plan.py \
  --input input.cif --input-format cif \
  --output POSCAR.new --output-format poscar \
  --periodic --coordinate-mode direct
```

然后转换到一个新路径，并显式确认信息损失：

```bash
python scripts/structure_converter.py input.cif POSCAR.new \
  --output-format poscar --coordinate-mode direct --allow-lossy \
  --acknowledge-parser-warnings
```

CIF、POSCAR、XYZ 和 JSON 并不保留相同的语义。在每次转换之后都要检查晶格、
周期性、坐标模式、物种（species）排序顺序、选择性动力学（selective dynamics）、位点属性、
氧化态、标签，以及无序性。参见 [I/O 格式（I/O formats）](references/io_formats.md)。

## 变换与来源信息追踪（provenance）

对一份拷贝进行变换，并保留历史记录：

```python
from pymatgen.alchemy.materials import TransformedStructure
from pymatgen.transformations.standard_transformations import (
    SubstitutionTransformation,
    SupercellTransformation,
)

tracked = TransformedStructure(structure.copy(), [])
tracked.append_transformation(SupercellTransformation([2, 2, 2]))
tracked.append_transformation(SubstitutionTransformation({"Na": "K"}))
derived = tracked.final_structure
history = tracked.history
```

"一对多"排序、掺杂（doping）、切片（slab）和磁性变换可能会以组合方式急剧膨胀，
或调用可选的外部可执行程序。请对候选数量、位点数、超胞（supercell）大小、运行时长,
以及输出数量设置上限。参见
[变换与工作流程（transformations and workflows）](references/transformations_workflows.md)。

## 本地相图

附带的生成器是离线运行的，只接受一种严格的 JSON schema，其中
每个条目需给出以 eV 为单位的总能量以及来源信息：

```json
{
  "schema_version": "1.0",
  "energy_unit": "eV",
  "energy_basis": "total_per_entry",
  "provenance": {
    "source": "reviewed local calculations",
    "method": "one compatible energy/correction scheme"
  },
  "entries": [
    {
      "entry_id": "local-Li",
      "composition": "Li",
      "energy_eV": -1.0,
      "provenance": {"source": "calculation manifest sha256:..."}
    }
  ]
}
```

```bash
python scripts/phase_diagram_generator.py entries.json --analyze Li2O
```

必须提供单质端点（elemental endpoints）和所有竞争相（competing phase）。不要混用
来自不同泛函（functional）、赝势（pseudopotential）、磁性状态或校正惯例的原始能量。
计算得到的"位于凸包上（on-hull）"状态并不等同于实验上的稳定性。

## 能带结构、态密度、VASP 与 Q-Chem

只解析所需的数据：

```python
from pymatgen.io.vasp import Vasprun

run = Vasprun(
    "vasprun.xml",
    parse_dos=True,
    parse_eigen=True,
    parse_projected_eigen=False,
    parse_potcar_file=False,
)
band_structure = run.get_band_structure(line_mode=True)
band_gap = band_structure.get_band_gap()
complete_dos = run.complete_dos
```

投影本征值（projected eigenvalue）可能会消耗极大的内存。在解读带隙或态密度之前，
请核实收敛性、k 点路径（k-path）、自旋/自旋轨道耦合（SOC）设置、费米能级（Fermi-level）
约定、展宽（smearing）,以及投影基组。解析成功并不代表计算已经收敛。

当前的 Q-Chem 接口是 `pymatgen.io.qchem.inputs.QCInput` 和
`pymatgen.io.qchem.outputs.QCOutput`：

```python
from pymatgen.io.qchem.inputs import QCInput

job = QCInput(
    molecule,
    rem={"job_type": "sp", "method": "wb97x-v", "basis": "def2-svpd"},
)
text = str(job)
```

Pymatgen 负责写入输入文件和解析输出，但并不授予 VASP 或 Q-Chem 的
使用许可，也不建立方法本身的有效性。POTCAR 文件受 VASP 许可证约束，
pymatgen 并不分发这些文件。切勿再分发这些文件，也不要在无关目录中扫描寻找它们。
诸如 enumlib、Bader、packmol、ffmpeg 和 Zeo++ 等可选工具是原生/外部可执行程序：
在单独进行显式调用之前，请审查其来源、许可证、argv（命令行参数）、工作目录，以及资源限制。

## Materials Project：先规划，再联网

只使用：

```python
from mp_api.client import MPRester
```

该客户端在构造时会读取 `MP_API_KEY`。只应通过用户的 shell 或
密钥管理器提供这一个命名的环境变量。不要将密钥作为 CLI 参数接受、
不要遍历 `.env` 文件、不要转储环境变量，也不要在未做脱敏处理的情况下打印异常数据。

默认采用"演练式"（dry-run）规划：

```bash
python scripts/mp_query.py \
  --chemsys Li-Fe-O \
  --energy-above-hull 0 0.05 \
  --fields formula_pretty,energy_above_hull,band_gap,origins \
  --limit 25
```

只有 `--execute` 才允许执行一次有边界限制的摘要查询，且要求指定一个新的输出：

```bash
python scripts/mp_query.py \
  --material-id mp-149 \
  --fields formula_pretty,structure,origins,last_updated \
  --limit 1 --output mp-149.json --execute
```

该 CLI 设置了 `num_chunks=1`，要求显式指定字段和过滤条件，对结果数量设有上限，
不实现隐式的结果缓存，也绝不会覆盖已有的输出文件。
`MPRester` 初始化时还会执行兼容性/心跳元数据请求；该计划会披露这些请求，
禁用平台细节用户代理（user agent）和本地数据库版本通知日志，
并记录返回的数据库版本。摘要查询工作流不会请求整份数据集的缓存下载。
`mp-api` 0.46.4 会按照其自身配置的策略重试 HTTP 429/502/504，
并遵循 `Retry-After` 头；不要臆造一个数值型的服务配额，也不要添加
无上限的重试循环。

Materials Project 的核心数值是计算得出的、依赖于所用方法的数据——而非
实验事实。PBE 泛函通常会高估晶格参数，并系统性地低估带隙；
汇总数值可能随数据库版本更新而变化。请保留检索时间、查询条件、字段、
material/task 的来源（origins）、（如可获取的）数据库发布版本、客户端版本、
CC BY 署名要求，以及规范引用和特定属性的引用信息。参见
[Materials Project API](references/materials_project_api.md)。

## 附带的命令行工具（CLI）

所有 CLI 都提供不依赖外部库的 `--help`、惰性的科学计算库导入、
有边界限制的 JSON 输出，且不会隐式联网：

- `scripts/composition_structure_validator.py` — 严格的成分/结构
  检查；可选的氧化态猜测功能是显式触发且有边界限制的。
- `scripts/structure_analyzer.py` — 有边界限制的晶格、位点、对称性、距离，
  以及可选的 CrystalNN 报告。
- `scripts/symmetry_sensitivity_report.py` — 容差网格下的空间群判定。
- `scripts/io_conversion_plan.py` — 不依赖外部库的表示信息损失规划工具。
- `scripts/structure_converter.py` — 单文件转换到新路径。
- `scripts/phase_diagram_generator.py` — 严格的本地计算条目凸包计算。
- `scripts/mp_query.py` — 演练式 MP 查询计划，以及可选启用的有边界限制客户端。
- `scripts/artifact_manifest.py` — 校验和、版本、来源，以及来源信息记录。

用法：

```bash
python scripts/artifact_manifest.py \
  --artifact input.cif --artifact analysis.json \
  --workflow "local symmetry sensitivity" --output manifest.json
```

## 参考文档

- [核心类（Core classes）](references/core_classes.md)
- [I/O 格式、VASP 与 Q-Chem](references/io_formats.md)
- [分析、对称性、相图、能带与态密度](references/analysis_modules.md)
- [变换与工作流程](references/transformations_workflows.md)
- [Materials Project API、来源信息、许可证与限制](references/materials_project_api.md)

## 来源（截至 2026-07-23 验证）

- [pymatgen 2026.5.4 on PyPI](https://pypi.org/project/pymatgen/)
- [pymatgen-core 2026.7.16 on PyPI](https://pypi.org/project/pymatgen-core/)
- [pymatgen API documentation](https://pymatgen.org/)
- [pymatgen changelog](https://pymatgen.org/CHANGES.html)
- [mp-api 0.46.4 on PyPI](https://pypi.org/project/mp-api/)
- [Materials Project API getting started](https://docs.materialsproject.org/downloading-data/using-the-api/getting-started)
- [Materials Project query guide](https://docs.materialsproject.org/downloading-data/using-the-api/querying-data)
- [Materials Project FAQ and computed-data caveats](https://docs.materialsproject.org/frequently-asked-questions)
- [Materials Project citation page](https://materialsproject.org/about/cite)
- [Official tutorial series endorsed by pymatgen](https://github.com/computron/pymatgen_tutorials)
