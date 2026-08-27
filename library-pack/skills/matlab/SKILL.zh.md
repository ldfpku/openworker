# MATLAB 与 GNU Octave

使用本技能来设计或审查数值代码、迁移 MATLAB 版本、准备可复现的项目，
以及规划受信任的执行。MATLAB 和 GNU Octave 是不同的产品：两者之间的
兼容性是部分的，既不是许可证保证，也不是行为保证。

## 产品与许可证闸门

- **MATLAB R2026a 是专有软件**。 不要假定用户已经安装、已获许可、或可以
  使用 MATLAB、MATLAB Online、某个具名工具箱、MATLAB Test、MATLAB
  Compiler、MATLAB Coder、Parallel Computing Toolbox 或某个附加组件。
- **MATLAB Runtime 不是 MATLAB**。 它只能运行由 MATLAB Compiler 生成的
  兼容应用程序；它无法运行任意源代码，也无法承载面向 Python 的 MATLAB
  Engine。构建产物需要相应的、已获许可的编译器，以及源代码所使用的
  每一个产品。
- **GNU Octave 11.3.0 是遵循 GPLv3+ 许可的自由软件**。 Octave 的包
  并不是 MATLAB 工具箱。名称相似并不意味着 API、数值行为、图形表现
  或许可方面存在等价性。
- 要询问用户实际拥有的是哪种运行环境、哪个版本、哪个平台、已安装了
  哪些产品，以及许可证情况。在得到确认之前，把可用性视为「未知」。

参见 [Octave 兼容性](references/octave-compatibility.md) 与
[执行/产品边界](references/executing-scripts.md)。

## 不可协商的安全边界

绝不运行不受信任的 `.m`、`.mlx`、MEX 二进制文件、MAT 文件、项目的启动
或关闭动作、包安装程序，或生成的产物。静态审查并不能证明其安全。

请将以下内容视为执行面或代码加载面：

- `eval`、`evalin`、`assignin`、由文本派生的 `feval`、`str2func`、
  回调函数、定时器、应用回调，以及被动态修改过的路径；
- `system`、`unix`、`dos`、shell 转义符 `!`、Java、.NET、Python
  （`py.*`、`pyrun`、`pyrunfile`）、MEX，以及原生库；
- `mex`、`codegen`、MATLAB Compiler、构建任务、包/项目的启动，以及
  生成的代码；
- `load`、对象反序列化（`loadobj`、自定义序列化）、函数句柄、
  Java/System 对象，以及可以从 MAT 文件中触达的类代码。

对于本工具集而言，`.mlx` 是一种不透明的归档格式，而 MEX 则是原生的
可执行代码。不要用 Python 的 pickle 来做数据交换。先做检查，在合适
时做隔离，取得明确批准，然后才调用经用户确认过的可执行程序和许可证。
所附带的脚本都是静态或空跑（dry-run）工具：没有一个会启动 MATLAB、
Octave、Python Engine、编译器或子进程。

## 默认工作流

1. **明确目标**。 记录 MATLAB 版本或 Octave 版本、操作系统/架构、
   基础产品与所需工具箱/包的区别、预期的输入/输出、数值容差，以及
   是否已获得执行授权。
2. **做静态清点**。 在任何运行时加载之前，先扫描 `.m` 文件、不透明的
   产物、项目路径、所需产品，以及 MAT 文件头。
3. **选择代码形式**。 自动化场景优先使用带 `arguments` 代码块的函数。
   脚本仅用于受控的编排，实时脚本（live script）仅用于经过审查的
   交互式叙述。
4. **让语义明确化**。 记录形状（shape）、类别（class）、单位、缺失值
   规则、索引方式、隐式扩展、随机数生成算法/种子、容差，以及输出
   格式。
5. **在没有隐藏状态的情况下测试**。 保持测试夹具（fixture）为合成
   数据、路径限定于项目内部、图形结果具有确定性，并使测试不依赖
   基础工作区中残留的数据。
6. **规划执行**。 生成一份 argv 计划，审查启动/路径方面的影响以及
   许可证情况，只有在这些辅助工具之外获得明确批准后才启动。
7. **记录出处（provenance）**。 对具名的输入/代码计算哈希值，并记录
   版本、所用产品、随机数生成策略、容差，以及命令计划，但不要转储
   整个环境。

## 语言与数据检查清单

### 脚本、函数与实时脚本

- 脚本共享调用者/基础工作区，并会留下变量。函数拥有各自局部的
  工作区，以及明确的输入/输出。
- 实时脚本（`.mlx`）把代码和富文本输出混在一起，但并不是纯文本形式的
  审查产物。要做静态检查时，应将经过审查的代码导出为 `.m`。
- 避免使用 `clear all`、范围过宽的 `addpath(genpath(...))`、对
  `pwd` 的依赖、全局变量，以及静默的名称遮蔽（shadowing）。使用项目
  根目录和 `fullfile`。
- 在 `arguments` 代码块中校验大小、类别和取值。要记住：类型声明可能
  会对输入做转换；而校验器（validator）只检查、不转换。
- 主函数所在的文件名应与主函数名一致。局部函数（local function）仅在
  该文件内私有；自 R2024a 起，只要不在条件语句内部，它们可以出现在
  脚本中的任意位置。

```matlab
function y = scaleSignal(x, options)
arguments
    x (:,1) double {mustBeFinite}
    options.Scale (1,1) double {mustBeFinite, mustBeNonzero} = 1
end
y = x .* options.Scale;
end
```

阅读 [编程](references/programming.md)。

### 数组、索引与数值运算

- MATLAB 使用从 1 开始、按列优先（column-major）的索引方式。
  `A(i,j)`、`A(k)`、`A(:,j)`、`A{...}` 与 `A.(name)` 的语义各不相同。
- `*`、`/`、`\` 和 `^` 是矩阵运算；带点号的形式是逐元素（element-wise）
  运算。应使用 `A\b`，而不是 `inv(A)*b`。
- 自 R2016b 起，维度兼容的数组会隐式扩展。在可能意外形成外积
  （outer）结果的运算之前，先断言预期的形状。
- 当输出大小已知时应预先分配空间，但不要为了向量化而不惜产生巨大的
  临时变量或难以阅读的代码。用 `timeit` 或性能分析器（profiler）
  来测量。
- 比较浮点结果时，应使用领域内选定的绝对与相对容差，而不是笼统地用
  `==`，也不要用 `eps` 的某个「魔法倍数」。
- 把随机算法和种子都固定下来。对独立的并行工作，使用具名的
  `RandStream` 子流（substream）；不要为了可复现性的声明而使用基于
  时间的 `rng("shuffle")`。

阅读 [数组](references/matrices-arrays.md) 与
[数学运算](references/mathematics.md)。

### 表格、时间表与缺失值

- `table` 拥有若干具名、行数相同、但类型可能不同的变量。`T(rows,vars)`
  返回一个表格；`T{rows,vars}` 提取其中的内容；`T.Var` 选取某一个变量。
- `timetable` 在此基础上还带有行时间戳。要先排序、校验时区和唯一性，
  再有意识地使用 `retime`/`synchronize`。
- 缺失值哨兵（sentinel）是与类型相关的：`NaN`、`NaT`、`<missing>`、
  `<undefined>`，以及空字符向量。整数与逻辑数组没有标准的缺失值
  哨兵。
- 对生产数据要明确定义导入选项（import option），而不是依赖自动推断。
  要保留单位、时区、变量名、编码方式，以及缺失值规则。

阅读 [数据导入/导出](references/data-import-export.md)。

## 图形与导出

使用显式的图形句柄（figure handle）和坐标轴句柄（axes handle），配合
`tiledlayout`；标注单位；有意识地设置坐标范围、色阶、字号和色图
（colormap）。对于出版用途的输出，优先使用 `exportgraphics` 而非
`saveas`。在 R2026a 中，它可以导出栅格图、PDF/EPS/EMF、SVG、GIF 以及
交互式 HTML；不同格式的能力有所差异。对于适合的 PDF/SVG 风格输出，
应指定 `ContentType="vector"`；对于栅格输出，应指定 `Resolution`。
要审查可访问性以及嵌入式栅格化的行为。

阅读 [图形与导出](references/graphics-visualization.md)。

## MAT 文件与数据交换

- 版本 7 是 `save` 的常规默认值；`matfile` 默认创建的是版本 7.3。
  版本 4/6/7/7.3 在类型、压缩方式和单变量限制方面各不相同。
- 版本 7.3 基于 HDF5，但并不是一种任意的 HDF5 互操作契约。局部访问
  和分块（chunking）有助于处理大型数组。
- 绝不加载不受信任的 MAT 文件。要先清点文件头/数据集。对象可能触发
  类的反序列化行为；不透明内容、函数内容或原生内容需要升级审查
  流程。
- 对于简单的数据交换，优先使用带有文档化模式（schema）的
  CSV/JSON/Parquet/HDF5。不要把 pickle 数据改名成 MAT 文件，也不要
  反序列化 pickle 数据。

阅读 [数据导入/导出](references/data-import-export.md)。

## 项目、分析与测试

- 使用 MATLAB Projects 来管理受控的路径、启动/关闭任务、依赖关系、
  源代码控制，以及可复现的入口点。在打开不受信任的项目之前，要先
  审查项目动作。
- `matlab.codetools.requiredFilesAndProducts` 和 Dependency Analyzer
  都是静态近似分析；动态派发（dynamic dispatch）可能导致遗漏或误报。
  「所需产品」报告并不能证明某个许可证是可用的。
- 在迁移之前使用 Code Analyzer（`codeIssues`；旧的文本工作流可以用
  `checkcode`）和 `codeCompatibilityReport`。
- 基础版 MATLAB 包含基于脚本、基于函数以及基于类的 `matlab.unittest`
  工作流。并行运行需要 Parallel Computing Toolbox。基于依赖关系的
  测试选择、更丰富的质量仪表盘、生成的测试，以及高级覆盖率/等价性
  功能，可能需要 MATLAB Test 或其他产品。
- 当目标测试所属的项目尚未打开时，R2026a 的 `runtests` 会自动打开
  该项目，并在之后关闭它。在依赖此行为之前，要考虑到启动和关闭
  动作带来的影响。

阅读 [编程](references/programming.md) 与
[执行/测试](references/executing-scripts.md)。

## Python 集成（针对 R2026a 固定版本）

- R2026a 为面向 Python 的 MATLAB 接口、面向 Python 的 MATLAB Engine，
  以及面向 Python 的 MATLAB Compiler SDK 支持 64 位 CPython 3.9-3.13。
- 本文档所审阅的当前 R2026a PyPI 包是
  `matlabengine==26.1.12`（发布于 2026-05-08）。它需要已安装的
  R2026a；仅有 MATLAB Runtime 是不够的。R2026a 还在一个名为
  `matlabroot` 的路径下附带预安装的 Engine 发行版。
- 安装该包并不会授予 MATLAB 或工具箱许可证。要配置一个具名的
  解释器/可执行文件；不要打印完整的环境变量、`PATH`、`PYTHONPATH`
  或凭据。
- `pyenv` 控制从 MATLAB 到 Python 的解释器选择。进程内（in-process）
  Python 通常需要重启 MATLAB 才能切换；进程外（out-of-process）
  Python 则可以被终止并重新配置。
- 启动 Engine 是一个明确的执行动作：`matlab.engine.start_matlab()`
  会启动一个 MATLAB 进程，并可能签出（check out）一份许可证。绝不要
  仅仅为了探测其可用性而调用它。
- 要核实 NumPy 数组、pandas DataFrame、表格/时间表、字符串/缺失值、
  日期时间/时长、字典、形状/顺序，以及不受支持的稀疏/对象/分类
  （categorical）情形的转换语义。

阅读 [Python 集成](references/python-integration.md)。

## 本地辅助 CLI 工具

每个辅助工具都不联网、有边界限制、拒绝符号链接，且不执行代码。请在
本技能所在目录下用 Python 3.11+ 运行。Bash 只被允许用来调用这些
Python CLI 和校验命令；绝不要用它来执行生成出来的 MATLAB/Octave
argv 计划或不受信任的产物。

| 辅助工具 | 用途 |
|---|---|
| `scripts/plan_batch_command.py` | 生成经过审查的 MATLAB/Octave argv；从不执行 |
| `scripts/scan_m_code.py` | 扫描 `.m` 文本，标记不透明的 `.mlx`/MEX 风险 |
| `scripts/validate_project_manifest.py` | 校验路径以及声明的产品/许可证状态 |
| `scripts/inventory_mat_file.py` | 文件头/元数据清点；从不调用 `loadmat` |
| `scripts/plan_python_compatibility.py` | 检查 R2026a 的 CPython/Engine 兼容性 |
| `scripts/reproducibility_report.py` | 对具名的本地产物计算哈希，并生成一份有边界的报告 |
| `scripts/generate_function_scaffold.py` | 以空跑方式或实际创建函数与单元测试脚手架 |

```bash
python scripts/scan_m_code.py path/to/source --root path/to/project
python scripts/plan_batch_command.py matlab script path/to/main.m --root path/to/project
python scripts/validate_project_manifest.py project-manifest.json --root path/to/project
python scripts/inventory_mat_file.py data.mat --root path/to/project
python scripts/plan_python_compatibility.py --python-version 3.13
python scripts/reproducibility_report.py --root path/to/project --file src/analyze.m
python scripts/generate_function_scaffold.py analyzeSignal --root path/to/project
```

脚手架生成器默认以空跑方式运行；实际写入需要 `--write`，并拒绝发生
冲突的写入。SciPy 和 h5py 是可选的清点后端；如获授权，可将其经审查
确认的确切版本加入调用方项目的 lockfile。对于 `--help` 或仅涉及文件头
的清点而言，这两者都不是必需的，本技能本身也不执行任何包安装操作。

## 参考资料

- [编程、工作区、项目、分析、测试](references/programming.md)
- [矩阵、索引、类型、缺失值、性能](references/matrices-arrays.md)
- [数值方法、容差、随机数生成、工具箱边界](references/mathematics.md)
- [图形与 `exportgraphics`](references/graphics-visualization.md)
- [导入/导出、表格/时间表、MAT 语义与安全性](references/data-import-export.md)
- [MATLAB/Octave 命令行执行与迁移](references/executing-scripts.md)
- [MATLAB 与 Python 互操作](references/python-integration.md)
- [GNU Octave 11.3.0 兼容性差异](references/octave-compatibility.md)

所附带的 JSON 资源为
[项目清单（project manifest）](assets/project_manifest_template.json)、
[可复现性清单（reproducibility manifest）](assets/reproducibility_manifest_template.json)，
以及
[R2026a Python 对照表](assets/python_compatibility_r2026a.json)。
不存在 `templates/` 目录，也没有从 `assets/` 加载任何 Markdown
文件；本地链接测试会强制执行这一套包契约。

## 主要资料来源（于 2026-07-23 核实）

- [MATLAB R2026a documentation](https://www.mathworks.com/help/matlab/)
- [MATLAB R2026a release notes](https://www.mathworks.com/help/matlab/release-notes.html)
- [R2026a system requirements](https://www.mathworks.com/support/requirements/matlab-system-requirements.html)
- [Python compatibility by release](https://www.mathworks.com/support/requirements/python-compatibility.html)
- [MATLAB Engine installation](https://www.mathworks.com/help/matlab/matlab_external/install-the-matlab-engine-for-python.html)
- [GNU Octave 11.3.0 release](https://octave.org/)
- [GNU Octave current manual](https://docs.octave.org/latest/)
