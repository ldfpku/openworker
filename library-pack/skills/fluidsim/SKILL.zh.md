# FluidSim

将 FluidSim 0.9.0 用作以 Python 定义数值求解器的框架，尤其适用于周期性笛卡尔伪谱(pseudospectral)CFD。上游 FluidSim 采用 CeCILL-2.1 许可证;MIT 这一 frontmatter 许可证仅适用于本技能本身。

本技能**不会**把一次运行完成、一个稳定的时间步长、一张平滑的图，或程序的正常退出，当作数值收敛性或物理有效性的证据。

## 必需的工作流程

1. 明确写出方程、单位或无量纲化方式、几何形状、边界、初始条件、强迫项(forcing)、观测量，以及验收标准。
2. 选择一个已验证的求解器，并检查其生成的默认参数。
3. 创建一份严格的 JSON 计划，明确写出 CPU、内存、磁盘、墙钟时间、输出文件、时间步长、CFL、分辨率和去混叠(dealiasing)的边界值。
4. 运行内置的校验器和资源估算器。
5. 生成并审阅一份空运行(dry-run)脚本。除非明确确认配置 ID,否则它不会执行任何操作。
6. 运行一次极小规模的串行试点(pilot)。检查预算、散度/约束条件、谱尾(spectral tails)、CFL/时间步历史，以及输出增长情况。
7. 独立地精细化网格和时间步长。检查守恒量/预算残差以及观测量的敏感性。
8. 只有到这一步，才准备针对特定站点的 MPI 作业。绝不要自动提交或启动 MPI。
9. 保留配置、脚本、`uv.lock`、包/平台/后端版本、日志、输出清单、校验和，以及重启谱系(restart lineage)。

如果物理假设、单位、边界条件、强迫项语义、分辨率判据、资源限制或验收标准有缺失，应当停止。

## 版本与安装

截至 2026-07-23 核实如下:

- 最新稳定 PyPI 版本:`fluidsim==0.9.0`(2025-12-04)。
- 包元数据要求 Python `>=3.11`,并列出支持 Python 3.11-3.14。
- 伪谱参数的创建需要 FluidFFT;冒烟测试中裸 `import fluidsim` 可以成功，但在安装 `fft` extra 之前,`ns2d.create_default_params()` 会失败。
- 此处测试所用的配套版本为:`fluidfft==0.4.5` 和 `pyFFTW==0.15.1`。

优先使用项目锁定文件:

```bash
uv init --python 3.11
uv add "fluidsim[fft]==0.9.0" "fluidfft==0.4.5" "pyFFTW==0.15.1"
uv lock
uv sync --frozen
```

如需一个隔离的一次性环境:

```bash
uv venv --python 3.11
uv pip install "fluidsim[fft]==0.9.0" "fluidfft==0.4.5" "pyFFTW==0.15.1"
```

项目锁定文件是可复现性的记录；仅靠直接固定版本号并不能冻结所有的传递依赖产物(transitive artifacts)。不要跨不兼容的平台或 MPI ABI 复用同一份锁定文件。

MPI 是可选的原生组件:

```bash
uv add "mpi4py==4.1.2" "fluidfft-mpi-with-fftw==0.0.1" "fluidfft-fftwmpi==0.0.1"
uv lock
```

这些包仍然需要一个兼容的 MPI 运行时和 FFTW 开发库。可选的原生插件包括:

- `fluidfft-fftw==0.0.1`:串行的
  `fft2d.with_fftw1d`、`fft2d.with_fftw2d`、`fft3d.with_fftw3d`。
- `fluidfft-mpi-with-fftw==0.0.1`:MPI 版的
  `fft2d.mpi_with_fftw1d`、`fft3d.mpi_with_fftw1d`。
- `fluidfft-fftwmpi==0.0.1`:支持 MPI 的 FFTW
  `fft2d.mpi_with_fftwmpi2d`、`fft3d.mpi_with_fftwmpi3d`。
- `fluidfft-p3dfft==0.0.1`:`fft3d.mpi_with_p3dfft`;需要 P3DFFT。
- FluidFFT 还声明了 PFFT 和 P3DFFT 这两个 extra;需要针对目标集群审查并固定它们各自的原生技术栈版本。

FluidFFT 的文档中历史上提到过 cuFFT,但 FluidFFT 0.4.5 的包元数据中并未声明任何 CUDA extra 或已安装的 GPU 插件，其 CUDA 安装页面也尚未完成。不要声称具备 GPU 加速能力，也不要把一个不相关的 CUDA wheel 当作 FluidSim 后端来安装。请把 GPU 相关工作视为源码层面的实验性集成，需要单独进行验证。

系统依赖、MPI ABI、HDF5-MPI、后端发现与验证，详见 [installation](references/installation.md)。

## API 概览

使用直接的、带版本的导入方式:

```python
from fluidsim.solvers.ns2d.solver import Simul

params = Simul.create_default_params()
params.oper.nx = params.oper.ny = 32
params.oper.Lx = params.oper.Ly = 2 * 3.141592653589793
params.oper.coef_dealiasing = 2 / 3
params.time_stepping.USE_CFL = True
params.time_stepping.cfl_coef = 0.5
params.time_stepping.deltat0 = 0.001
params.time_stepping.deltat_max = 0.01
params.time_stepping.t_end = 0.1
params.time_stepping.max_elapsed = "00:05:00"
params.init_fields.type = "noise"
params.init_fields.noise.velo_max = 0.01
params.output.HAS_TO_SAVE = False
params.output.ONLINE_PLOT_OK = False
```

0.9 版本中的一些重要更正:

- CFL 字段是:`params.time_stepping.cfl_coef`,而不是 `CFL`。
- 时间相关强迫项(time-correlated forcing):
  是 `params.forcing.tcrandom.time_correlation`,而不是扁平的
  `tcrandom_time_correlation`。
- NS2D 的默认初始类型包括 `constant`、`noise`、`jet`、`dipole`、
  `from_file`、`from_simul` 和 `in_script`;不要为每个求解器都臆造一份"通用"列表。
- 输出状态文件默认名为 `state_phys_t*.nc`;谱数据使用
  `spectra1D.h5`/`spectra2D.h5`;标量均值文件因求解器而异，可能是
  `spatial_means.txt` 或 JSON-lines 格式。
- `params.output.sub_directory` 是相对于 `FLUIDSIM_PATH` 的相对路径。

`ParamContainer` 会拒绝未声明的属性。始终先从所选的 `Simul` 类生成默认参数，并在修改数值之前先检查它们。参见 [parameters](references/parameters.md)。

## 求解器

主要的笛卡尔 CFD 键名与导入方式:

```python
from fluidsim.solvers.ns2d.solver import Simul       # ns2d
from fluidsim.solvers.ns2d.bouss.solver import Simul # ns2d.bouss
from fluidsim.solvers.ns2d.strat.solver import Simul # ns2d.strat
from fluidsim.solvers.ns3d.solver import Simul       # ns3d
from fluidsim.solvers.ns3d.bouss.solver import Simul # ns3d.bouss
from fluidsim.solvers.ns3d.strat.solver import Simul # ns3d.strat
```

0.9 版本的求解器注册表中还包括 `plate2d`、多种 `sw1l` 变体、`waves2d`、一维模型、零维模型、球面求解器，以及框架适配器。某个求解器出现在注册表中，并不意味着它适用于某个具体的科学问题。请在求解器源代码中核实方程、变量、几何形状、边界条件和诊断量。参见 [solvers](references/solvers.md)。

## 强迫项与时间推进

强迫项(Forcing)是求解器特定的。当前的一个归一化随机强迫示例如下:

```python
params.forcing.enable = True
params.forcing.type = "tcrandom"
params.forcing.forcing_rate = 1.0
params.forcing.nkmin_forcing = 4
params.forcing.nkmax_forcing = 5
params.forcing.tcrandom.time_correlation = "based_on_forcing_rate"
```

请记录被施加强迫的变量、归一化的定义、波数范围(wave-number band)、随机种子/状态、注入目标，以及实测注入量。FluidSim 0.9 会保存状态参数以供重启使用;0.8.6 修复了时间相关强迫项在重启时的行为问题。

可用的伪谱格式包括 Euler/RK2 相移(phase-shift)变体、`RK2_trapezoid` 和 `RK4`。一个格式的命名并不能确立其精度。请检查 CFL、快波/耗散极限、`deltat_max`,以及时间步的精细化程度。参见 [advanced features](references/advanced_features.md)。

## 输出、加载与重启

用于只读分析:

```python
from fluidsim import load_sim_for_plot

sim = load_sim_for_plot("run-directory", hide_stdout=True)
sim.output.spatial_means.plot()
sim.output.spectra.plot1d()
sim.output.phys_fields.plot(time=1.0)
```

`load_sim_for_plot` 使用一个粗算子(coarse operator),并禁用保存/在线绘图功能。若需要一个携带状态的对象:

```python
from fluidsim import load_state_phys_file

sim = load_state_phys_file("run-directory", t_approx="last")
```

对于受控的重启，优先使用 `load_for_restart`,或者先运行
`fluidsim-restart --only-check`。不要对不可信的文本使用 `--modify-params`:
上游 CLI 会执行传给该选项的 Python 代码。本技能的生成器绝不会生成该选项。请核实求解器、网格/计算域、状态变量、版本号、强迫状态、校验和、目标时间、输出目的地，以及资源边界。分辨率的变更需要走专用的、经过审查的工作流程，而不是悄悄修改网格设置。参见 [simulation workflow](references/simulation_workflow.md) 和
[output analysis](references/output_analysis.md)。

## 科学验收关卡

在解读结果之前，需要具备:

- 明确的量纲单位，或一份完整的无量纲化映射表。
- 正确的方程、周期性几何形状/边界、初始状态、强迫项，以及诊断量的定义。
- 分辨率和去混叠的证据:谱/谱尾、已解析的梯度，以及与求解器相适应的小尺度判据。
- 时间步长的证据:CFL 历史、最快波速和耗散极限，以及更小步长的对比。
- 守恒量与预算检查，包括强迫、耗散、能量传递和残差。
- 针对所报告观测量的网格/时间精细化，附带不确定性或敏感性分析。
- 在适当情况下，与解析解、构造解(manufactured solution)、基准测试，或独立复现的结果进行比较。
- 完整的溯源信息与重启谱系。

绝不能仅凭参数取值或图表，就把一次运行标注为"DNS"、"已收敛"、"已验证"、"稳态"或"物理上正确"。

## 内置的本地工具

所有工具都输出严格的 JSON,拒绝 URL/路径穿越/符号链接，强制执行硬性边界值，不使用网络或子进程，也绝不会启动一次模拟运行:

```bash
python3 scripts/solver_config_validator.py --example
python3 scripts/solver_config_validator.py --config config.json
python3 scripts/grid_resource_estimator.py --config config.json
python3 scripts/simulation_dry_run.py --config config.json --output run.py
python3 scripts/output_inventory.py --path run-directory
python3 scripts/budget_summary.py --path run-directory
python3 scripts/restart_compatibility.py --source state.nc --target-config config.json
```

HDF5 相关工具惰性依赖 `h5py`,检查的是有边界限制的元数据/超片(hyperslabs),绝不会追踪外部链接或加载完整的场数组。

## 参考资料

- [安装与 FFT/MPI 后端](references/installation.md)
- [求解器注册表与选择](references/solvers.md)
- [仿真、试点与重启工作流程](references/simulation_workflow.md)
- [已验证的参数体系](references/parameters.md)
- [输出、绘图与预算分析](references/output_analysis.md)
- [强迫项、算子、MPI 与迁移指南](references/advanced_features.md)

## 有日期标注的上游依据

已于 2026-07-23 对照以下资料核实:
[PyPI 0.9.0](https://pypi.org/project/fluidsim/)、
[FluidSim 0.9 文档](https://fluidsim.readthedocs.io/en/latest/)、
[发行说明](https://fluidsim.readthedocs.io/en/latest/changes.html)、
[官方源码镜像](https://github.com/fluiddyn/fluidsim)、
[FluidFFT 0.4.5 文档](https://fluidfft.readthedocs.io/en/latest/),以及
主要的 FluidSim 论文([DOI 10.5334/jors.239](https://doi.org/10.5334/jors.239))
和 FluidFFT 论文([DOI 10.5334/jors.238](https://doi.org/10.5334/jors.238))。
API 相关论断依据官方文档/源码；参考资料中的方法/性能论断，其适用范围限于所引用的原始论文及其基准测试设置。
