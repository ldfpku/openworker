# OpenPIV

## 概述

OpenPIV（Open Particle Image Velocimetry）从 PIV 图像对中分析流体流动。它涵盖
预处理、互相关、向量校验、离群值替换、平滑处理以及缩放到物理单位。

以下内容均已针对 **openpiv 0.25.4** 验证过。API 会在不同版本之间发生变化——在把某段代码用于其他版本前，请先用
`inspect.signature()` 核实。

## 何时使用

在处理实验性 PIV 或流动可视化图像对时使用本技能：测量二维速度场、调整询问窗口（interrogation-window）参数、校验向量，或推导涡量、应变率和湍流统计量。若是要*模拟*流动而非*测量*流动，请改用 CFD 技能。

## 快速入门

安装 OpenPIV：

```bash
uv pip install openpiv

# Pin it when the analysis needs to be reproducible -- this is the version every
# snippet below was checked against.
uv pip install "openpiv==0.25.4"
```

对一对图像运行 PIV 分析：

```python
import numpy as np
from openpiv import tools, pyprocess, validation, filters, scaling

frame_a = tools.imread("image_a.bmp")
frame_b = tools.imread("image_b.bmp")

# Cross-correlate. Returns (u, v, s2n) whenever sig2noise_method is not None.
u, v, s2n = pyprocess.extended_search_area_piv(
    frame_a.astype(np.int32),
    frame_b.astype(np.int32),
    window_size=32,
    overlap=12,
    dt=0.02,
    search_area_size=38,
    correlation_method="linear",   # required for search_area_size > window_size
    sig2noise_method="peak2peak",
)

x, y = pyprocess.get_coordinates(
    image_size=frame_a.shape,
    search_area_size=38,
    overlap=12,
)

# flags is a boolean array: True marks a spurious vector.
flags = validation.sig2noise_val(s2n, threshold=1.05)
u, v = filters.replace_outliers(u, v, flags, method="localmean", max_iter=3, kernel_size=2)

# Scale to physical units, then flip to image coordinates for plotting.
x, y, u, v = scaling.uniform(x, y, u, v, scaling_factor=96.52)
x, y, u, v = tools.transform_coordinates(x, y, u, v)

tools.save("vectors.txt", x, y, u, v, flags)
```

或者使用随附的 CLI，它恰好封装了上述流程：

```bash
python skills/openpiv/scripts/runner.py \
    --image frame_a.bmp --image frame_b.bmp --output_dir results --verbose
```

## 核心概念

### PIV 基础

粒子图像测速法（Particle Image Velocimetry）是一种光学测量方法，通过在两张图像之间追踪被照亮的示踪粒子来测量流体速度。

**处理流程**：

1. 采集一对由已知时间间隔 `dt` 分隔的图像（`frame_a`、`frame_b`）。
2. 将图像划分为若干询问窗口（interrogation window）。
3. 对匹配的窗口做互相关，找出位移峰值。
4. 校验向量（信噪比、全局范围、局部中值）。
5. 用插值结果替换离群向量。
6. 将像素位移缩放为物理单位。

### 询问窗口参数

**`window_size`** —— 相关窗口的像素大小（通常为 16–128）。窗口越大，相关性越好，但空间分辨率越粗。

**`overlap`** —— 相邻窗口之间共享的像素数（通常为 `window_size` 的 50–75%）。重叠越大，向量密度和计算开销越高，但相邻向量之间会变得相关，而不再相互独立。

**`search_area_size`** —— 在第二帧中搜索的窗口范围。必须 ≥ `window_size`；比后者大几个像素可以容纳更大的位移。使用扩展搜索区域时应配合
`correlation_method="linear"` ——默认值 `"circular"` 依赖 FFT 的环绕（wrap-around）特性，会把较大的位移混叠成较小的位移。参见 `references/advanced_algorithms.md`。

经验法则：让最大位移保持在 `window_size` 的四分之一以下，并使每个窗口内大约有
5–10 个粒子。

### 信噪比

`s2n` 衡量相关峰值有多明显。`sig2noise_method` 控制其计算方式——
`"peak2mean"`（函数默认值）或 `"peak2peak"`。**两者的量纲不同**，因此针对一种方法调好的阈值对另一种方法毫无意义。典型的 `peak2peak` 阈值为 1.05–1.3。

```python
flags = validation.sig2noise_val(s2n, threshold=1.05)
# flags is bool: True == spurious. `~flags` selects the good vectors.
```

## 常见操作

### 动态掩膜（Dynamic Masking）

掩膜功能位于 `openpiv.preprocess` 中，**而非** `openpiv.masking` 模块。它返回一个
`(image, mask)` 元组，且要求输入为浮点型图像。

```python
from openpiv import preprocess

# method="edges" for dark, sharp-edged objects; "intensity" for high-contrast objects.
frame_a_masked, mask_a = preprocess.dynamic_masking(
    frame_a.astype(np.float64), method="intensity", filter_size=7, threshold=0.005
)
frame_b_masked, mask_b = preprocess.dynamic_masking(
    frame_b.astype(np.float64), method="intensity", filter_size=7, threshold=0.005
)
```

将**返回的图像**送入互相关步骤——它已经把被掩膜的区域置零。不要用原始帧再去乘以 `mask`：掩膜已经生效；而且对于
`method="edges"`，返回的 mask 是 `uint8` 的 0/255 而非布尔值，因此再相乘会把图像按 255 重新缩放。

### 多轮次处理（Multi-Pass Processing）

多轮次处理（窗口变形）位于 `openpiv.windef` 中，由 `PIVSettings` 数据类驱动。
`pyprocess` 没有多轮次处理的入口函数。

```python
import numpy as np
from openpiv import scaling, windef

settings = windef.PIVSettings()
settings.windowsizes = (64, 32, 16)   # one entry per pass, decreasing (this is also the default)
settings.overlap = (32, 16, 8)        # same length as windowsizes
settings.num_iterations = 3           # number of passes to actually run
settings.sig2noise_threshold = 1.05

x, y, u, v, flags = windef.simple_multipass(
    frame_a.astype(np.int32), frame_b.astype(np.int32), settings
)

# Output is in PIXELS PER FRAME -- convert yourself. scaling.uniform only divides
# by scaling_factor, so apply dt separately.
dt = 0.02
x, y, u, v = scaling.uniform(x, y, u, v, scaling_factor=96.52)
u, v = u / dt, v / dt
```

`simple_multipass` 已经完成了校验、离群值替换、把剩余的 NaN 填充为零，并调用了
`transform_coordinates`——不要重复这些步骤。

**单位陷阱**：`PIVSettings` 有 `dt` 和 `scaling_factor` 字段，但 `windef` 从未真正使用它们——
`first_pass` 调用 `extended_search_area_piv` 时并未传入 `dt`，因此整条多轮次处理链都是以“每帧像素数”为单位工作的。设置
`settings.dt = 0.02` 不会改变返回值的任何内容。请按上面的方式事后手动转换。

若需要对各轮次进行更精细的控制，`windef.first_pass` 和 `windef.multipass_img_deform` 是更底层的构建单元。

## 校验与后处理

### 校验方法

每个校验器都返回一个布尔数组，**True 表示该向量是离群/虚假向量**。

```python
# Signal-to-noise
flags = validation.sig2noise_val(s2n, threshold=1.05)

# Global range -- takes (min, max) TUPLES, positionally or as u_thresholds/v_thresholds.
flags = validation.global_val(u, v, (-300, 300), (-300, 300))

# Local median -- u_threshold and v_threshold are REQUIRED; size is the neighbourhood half-width.
flags = validation.local_median_val(u, v, u_threshold=30.0, v_threshold=30.0, size=1)

# Combine with boolean OR (not np.maximum -- these are bool arrays).
flags = (
    validation.sig2noise_val(s2n, threshold=1.05)
    | validation.global_val(u, v, (-300, 300), (-300, 300))
    | validation.local_median_val(u, v, u_threshold=30.0, v_threshold=30.0)
)
```

**这些阈值应以 `u` 和 `v` 的单位来设置，而不是以“每帧像素数”为单位。**
`extended_search_area_piv` 会除以 `dt`，因此当 `dt=0.02` 时，3 像素/帧的位移会变成
150 像素/秒。上面给出的阈值适用于这种情况；PIV 文献以及
`PIVSettings.min_max_u_disp` 中使用的 `(-30, 30)` 这个数值，是以“像素/帧”为单位的限值，若把它用于“像素/秒”的输出，会把整个流场都判为无效。请要么在缩放之前进行校验，要么把阈值也按 `1/dt` 缩放。

### 离群值替换

```python
u, v = filters.replace_outliers(
    u, v, flags, method="localmean", max_iter=3, tol=1e-3, kernel_size=2
)
```

`method` 只接受 `"localmean"`、`"disk"` 或 `"distance"`——仅限这三种。传入无法识别的名称并不会报错；它会退化为一个全零核，并悄无声息地返回一个没有意义的流场。注意，替换操作会*填充*被标记的位置为插值结果——如果随后再把它们覆盖为 NaN，那么这次替换就白做了。请二选一：

```python
# Keep flagged vectors out of the analysis entirely, instead of interpolating them.
u = np.where(flags, np.nan, u)
v = np.where(flags, np.nan, v)
```

### 平滑处理

平滑功能是 `openpiv.smoothn.smoothn`；不存在 `openpiv.smooth` 模块。它返回一个元组，其第一个元素是平滑后的流场，且不接受 NaN 输入。

```python
from openpiv.smoothn import smoothn

u_smooth, *_ = smoothn(np.nan_to_num(u), s=0.5)  # s: larger == smoother
v_smooth, *_ = smoothn(np.nan_to_num(v), s=0.5)
u_smooth = np.asarray(u_smooth)
```

## 可视化

### 向量场绘图

`display_vector_field` 读取一个已保存的向量文件，并在内部调用 `plt.show()`，因此在批处理运行时应选用非交互式后端。

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpiv import tools

fig, ax = plt.subplots(figsize=(8, 8))
tools.display_vector_field(
    "vectors.txt",
    ax=ax,
    scaling_factor=96.52,   # same factor used in scaling.uniform, to map back onto the image
    scale=50,
    width=0.0035,
    on_img=True,
    image_name="frame_a.bmp",
)
fig.savefig("vector_field.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

### 自定义可视化

```python
import numpy as np
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 3, figsize=(15, 5))

mag = np.sqrt(u**2 + v**2)
for ax, field, title, cmap in [
    (axes[0], mag, "Velocity Magnitude", "viridis"),
    (axes[1], u, "U Velocity", "RdBu_r"),
    (axes[2], v, "V Velocity", "RdBu_r"),
]:
    im = ax.imshow(field, cmap=cmap)
    ax.set_title(title)
    plt.colorbar(im, ax=ax)

fig.tight_layout()
fig.savefig("velocity_components.png")
plt.close(fig)
```

## 分析函数

`scripts/analyze.py` 把这些功能打包在一起，作用于由 `runner.py` 写出的
`params.npz` 文件。它会从已保存的坐标中推断出物理网格间距，因此得到的导数是按“每单位长度”计算的：

```python
import sys
sys.path.insert(0, "skills/openpiv/scripts")
from analyze import PIVAnalyzer

piv = PIVAnalyzer("results/params.npz")
vorticity = piv.compute_vorticity()          # dv/dx - du/dy
exx, eyy, exy = piv.compute_strain()
stats = piv.compute_statistics()             # u_mean, v_mean, rms_u, rms_v, tke
piv.plot_vector_field(save_path="quiver.png")
```

如果你更想内联计算，以下是独立形式：

### 涡量（Vorticity）

```python
def compute_vorticity(u, v, dx=1.0, dy=None):
    """Out-of-plane vorticity dv/dx - du/dy. Pass the physical grid spacing, not 1.0."""
    dy = dx if dy is None else dy
    return np.gradient(v, dx, axis=1) - np.gradient(u, dy, axis=0)
```

网格间距以物理单位表示为 `(window_size - overlap) / scaling_factor`，因此若把 `dx` 留为 `1.0`，得到的将是“每个网格单元”的涡量，而不是“每单位长度”的涡量。

**符号约定**：`runner.py` 最后会调用 `transform_coordinates`，它会把网格重新标记为右手系、y 轴向上的坐标系，但各行仍保持图像顺序，因此保存下来的 `y` 会随行索引增大而*减小*。上面给出的独立函数默认相反的约定，因此作用于 `params.npz` 中的流场时，它们实际计算出的是
`-du/dy`，并会使涡量和剪切应变的符号翻转——请对 `axis=0` 方向的导数取负号，或者改用
`PIVAnalyzer`，它会从已保存的坐标中读取方向信息。

### 应变率（Strain Rate）

```python
def compute_strain(u, v, dx=1.0, dy=None):
    """Return (exx, eyy, exy) of the 2D strain-rate tensor."""
    dy = dx if dy is None else dy
    du_dx = np.gradient(u, dx, axis=1)
    du_dy = np.gradient(u, dy, axis=0)
    dv_dx = np.gradient(v, dx, axis=1)
    dv_dy = np.gradient(v, dy, axis=0)
    return du_dx, dv_dy, 0.5 * (du_dy + dv_dx)
```

### 湍流统计量

```python
def compute_statistics(u, v):
    """Single-frame spatial statistics. NOT Reynolds decomposition."""
    u_prime = u - np.nanmean(u)
    v_prime = v - np.nanmean(v)
    rms_u, rms_v = np.nanstd(u_prime), np.nanstd(v_prime)
    return {
        "u_mean": np.nanmean(u),
        "v_mean": np.nanmean(v),
        "rms_u": rms_u,
        "rms_v": rms_v,
        "tke": 0.5 * (rms_u**2 + rms_v**2),
    }
```

**注意事项**：减去单帧的*空间*平均值所测得的是空间方差，只有在流场是均匀场的情况下，它才等于湍流强度。真正的雷诺分解（Reynolds decomposition）需要一组图像对（ensemble）：先沿时间轴求平均，再从每一次实现（realization）中减去该平均场。

## CLI 用法

```bash
# Basic run
python skills/openpiv/scripts/runner.py \
    --image img1.bmp --image img2.bmp --output_dir results --verbose

# Tuned parameters with dynamic masking
python skills/openpiv/scripts/runner.py \
    --image frame_a.bmp \
    --image frame_b.bmp \
    --output_dir results \
    --window_size 32 \
    --overlap 12 \
    --search_area 38 \
    --dt 0.02 \
    --scaling 96.52 \
    --threshold 1.05 \
    --mask dynamic \
    --mask_method intensity \
    --verbose
```

### CLI 选项

| 选项 | 默认值 | 说明 |
|--------|---------|-------------|
| `--image` | 必填 | 图像文件；需要恰好指定两次以组成一对 |
| `--output_dir` | `results` | 输出目录（若不存在则创建） |
| `--window_size` | 32 | 询问窗口大小（像素） |
| `--overlap` | 12 | 窗口重叠（像素） |
| `--search_area` | 38 | 搜索区域大小（像素），必须 ≥ `--window_size` |
| `--dt` | 0.02 | 帧间时间间隔（秒） |
| `--scaling` | 96.52 | 缩放因子，每物理单位对应的像素数（例如 px/mm） |
| `--threshold` | 1.05 | `peak2peak` 信噪比阈值 |
| `--mask` | `none` | `none` 或 `dynamic`（`openpiv.preprocess.dynamic_masking`） |
| `--mask_method` | `intensity` | `edges` 或 `intensity`，仅在 `--mask dynamic` 时使用 |
| `--drop_invalid` | 关闭 | 将被标记的向量置为 NaN，而不是保留插值结果 |
| `--verbose` | 关闭 | 打印进度信息 |

针对 OpenPIV 自带的示例图像对，端到端验证一次安装是否正常：

```bash
python skills/openpiv/scripts/run_example.py --output_dir /tmp/openpiv-demo
```

## 输出文件

- **vectors.txt** —— 制表符分隔，`%.4e` 格式，带有 `# x y u v flags mask` 注释表头
- **params.npz** —— 包含 `x`、`y`、`u`、`v`、`flags` 数组的 NumPy 归档文件
- **vector_field.png** —— 绘制在第一帧图像上的向量场

```text
# x	y	u	v	flags	mask
2.1757e-01	3.5226e+00	-6.2220e-02	-2.7081e+00	0.0000e+00	0.0000e+00
4.8695e-01	3.5226e+00	-3.1587e-01	-2.9800e+00	0.0000e+00	0.0000e+00
```

`flags` 以浮点数形式写出，`0` 表示有效向量，`1` 表示被标记的向量。

## 最佳实践

### 参数选择

1. **窗口大小** —— 32×32 适合大多数情况。64/128 用于在更粗分辨率下获得更好的相关性；
   16/24 用于更精细的分辨率，但代价是噪声更大。
2. **重叠** —— 窗口大小的 50–75%。
3. **阈值** —— 调高阈值以剔除更多向量；每次切换
   `sig2noise_method` 之后都要重新调优。
4. **缩放因子** —— 针对已知的参照物（例如标定网格）进行标定，并保持单位一致
   （OpenPIV 的 `test1` 教程数据中的 `96.52` 是 px/mm）。

### 图像质量

- 粒子清晰可见且分布均匀，每个询问窗口内 5–10 个
- 无饱和或过曝区域
- 背景噪声最小；可考虑在整个运行过程中做背景消减

### 处理技巧

1. 先从默认参数开始，再根据得到的向量场进行调优。
2. 检查 `s2n` 的分布——中位数偏低说明相关性差，而不是阈值不对。
3. 尽早可视化；明显的问题（向量场均一、边缘伪影）会立刻显现出来。
4. 对具有较大速度梯度或位移的流动，使用多轮次处理（`windef`）。
5. 对反光和固体边界进行掩膜处理，而不是任由它们生成向量。

## 资源

### references/

- `advanced_algorithms.md` —— 相关与亚像素方法、多轮次窗口变形、
  `PIVSettings` 字段、三维及相分离（phase-separation）模块

在需要详细的算法或设置信息时加载该参考文档。
