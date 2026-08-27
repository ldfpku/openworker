# Astropy

## 概述

Astropy 是天文学领域的核心 Python 包，为天文研究和数据分析提供基础功能。可用 astropy 进行坐标变换、单位与物理量计算、FITS 文件操作、宇宙学计算、精确时间处理、表格数据操作，以及天文图像处理。

## 何时使用本技能

在任务涉及以下内容时使用 astropy：
- 在不同天球坐标系之间转换（ICRS、Galactic、FK5、AltAz 等）
- 处理物理单位与物理量（如 Jy 转 mJy、parsec 转 km 等）
- 读取、写入或操作 FITS 文件（图像或表格）
- 宇宙学计算（光度距离、回溯时间、哈勃参数）
- 使用不同时间尺度（UTC、TAI、TT、TDB）和格式（JD、MJD、ISO）进行精确时间处理
- 表格操作（读取星表、交叉匹配、筛选、连接）
- 在像素坐标与世界坐标之间进行 WCS 变换
- 天文常数与相关计算

## 快速开始

```python
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.io import fits
from astropy.table import Table
from astropy.cosmology import Planck18

# Units and quantities
distance = 100 * u.pc
distance_km = distance.to(u.km)

# Coordinates
coord = SkyCoord(ra=10.5*u.degree, dec=41.2*u.degree, frame='icrs')
coord_galactic = coord.galactic

# Time
t = Time('2023-01-15 12:30:00')
jd = t.jd  # Julian Date

# FITS files
data = fits.getdata('image.fits')
header = fits.getheader('image.fits')

# Tables
table = Table.read('catalog.fits')

# Cosmology
d_L = Planck18.luminosity_distance(z=1.0)
```

## 核心能力

### 1. 单位与物理量（`astropy.units`）

处理带单位的物理量，进行单位换算，并确保计算中的量纲一致性。

**关键操作**：
- 通过将数值与单位相乘来创建物理量
- 使用 `.to()` 方法在不同单位间转换
- 进行带自动单位处理的算术运算
- 使用等价关系（equivalencies）处理特定领域的换算（光谱、多普勒、视差）
- 处理对数单位（星等、分贝）

**详见**： `references/units.md`，其中包含完整文档、单位体系、等价关系、性能优化以及单位算术。

### 2. 坐标系统（`astropy.coordinates`）

表示天体位置，并在不同坐标系之间进行变换。

**关键操作**：
- 使用 `SkyCoord` 在任意坐标系（ICRS、Galactic、FK5、AltAz 等）中创建坐标
- 在不同坐标系之间进行变换
- 计算角距离和位置角
- 将坐标与星表匹配
- 加入距离信息以进行三维坐标运算
- 处理自行（proper motion）和视向速度
- 从在线数据库中查询命名天体

**详见**： `references/coordinates.md`，其中包含详细的坐标系说明、变换方法、与观测者相关的坐标系（AltAz）、星表匹配以及性能建议。

### 3. 宇宙学计算（`astropy.cosmology`）

使用标准宇宙学模型进行宇宙学计算。

**关键操作**：
- 使用内置宇宙学模型（Planck18、WMAP9 等）
- 创建自定义宇宙学模型
- 计算各类距离（光度距离、共动距离、角直径距离）
- 计算年龄与回溯时间
- 确定任意红移处的哈勃参数
- 计算密度参数与体积
- 进行逆向计算（根据给定距离求红移 z）

**详见**： `references/cosmology.md`，其中包含可用模型、距离计算、时间计算、密度参数以及中微子效应。

### 4. FITS 文件处理（`astropy.io.fits`）

读取、写入并操作 FITS（Flexible Image Transport System）文件。

**关键操作**：
- 使用上下文管理器打开 FITS 文件
- 按索引或名称访问 HDU（Header Data Unit，头数据单元）
- 读取并修改头信息（关键字、注释、历史记录）
- 处理图像数据（NumPy 数组）
- 处理表格数据（二进制表和 ASCII 表）
- 创建新的 FITS 文件（单一扩展或多扩展）
- 对大文件使用内存映射
- 访问远程 FITS 文件（S3、HTTP）

**详见**： `references/fits.md`，其中包含完整的文件操作、头信息处理、图像与表格处理、多扩展文件以及性能相关考量。

### 5. 表格操作（`astropy.table`）

处理表格数据，支持单位、元数据以及多种文件格式。

**关键操作**：
- 从数组、列表或字典创建表格
- 以多种格式（FITS、CSV、HDF5、VOTable）读写表格
- 访问并修改列与行
- 对表格进行排序、筛选与索引
- 执行数据库风格的操作（连接、分组、聚合）
- 堆叠与拼接表格
- 处理带单位信息的列（QTable）
- 使用掩码处理缺失数据

**详见**： `references/tables.md`，其中包含表格创建、I/O 操作、数据处理、排序、筛选、连接、分组以及性能建议。

### 6. 时间处理（`astropy.time`）

在不同时间尺度和格式之间进行精确的时间表示与转换。

**关键操作**：
- 以多种格式（ISO、JD、MJD、Unix 等）创建 Time 对象
- 在不同时间尺度（UTC、TAI、TT、TDB 等）之间转换
- 使用 TimeDelta 进行时间算术运算
- 为观测者计算恒星时
- 计算光行时修正（质心、日心）
- 高效处理时间数组
- 处理带掩码（缺失）的时间

**详见**： `references/time.md`，其中包含时间格式、时间尺度、转换方法、算术运算、观测相关功能以及精度处理。

### 7. 世界坐标系统（`astropy.wcs`）

在图像的像素坐标与世界坐标之间进行变换。

**关键操作**：
- 从 FITS 头信息中读取 WCS
- 将像素坐标转换为世界坐标（及其逆过程）
- 计算图像footprint（图像所覆盖的天区范围）
- 访问 WCS 参数（参考像素、投影方式、比例尺）
- 创建自定义 WCS 对象

**详见**： `references/wcs_and_other_modules.md`，其中包含 WCS 相关操作与变换方法。

## 其他能力

`references/wcs_and_other_modules.md` 文件还涵盖以下内容：

### NDData 与 CCDData
用于存放带元数据、不确定度、掩码以及 WCS 信息的 n 维数据集的容器。

### Modeling（建模）
用于对天文数据创建并拟合数学模型的框架。

### Visualization（可视化）
用于以合适的拉伸和缩放方式显示天文图像的工具。

### Constants（常数）
带有正确单位的物理与天文常数（光速、太阳质量、普朗克常数等）。

### Convolution（卷积）
用于平滑和滤波的图像处理卷积核。

### Statistics（统计）
包含 sigma 截断（sigma clipping）与离群值剔除等在内的稳健统计函数。

## 安装

```bash
# Reproducible install against the current stable release
uv pip install "astropy==7.2.0"

# Recommended optional dependencies for plotting and common workflows
uv pip install "astropy[recommended]==7.2.0"

# Full optional dependency set for broad astronomy workflows
uv pip install "astropy[all]==7.2.0"
```

Astropy 7.2.0 需要 Python 3.11 及以上版本，并依赖 NumPy、PyERFA、PyYAML 以及 packaging。请使用隔离的虚拟环境；不要以提升的权限安装 Astropy。

请注意，`[recommended]` 和 `[all]` 附加依赖集会引入未锁定版本的传递依赖（matplotlib、scipy 等）。对于要求可复现的生产环境，应使用锁文件锁定完整的依赖树（在项目中使用 `uv lock`，或对 requirements 文件使用 `uv pip compile`），并在部署前审查已解析出的版本。

## 常见工作流

### 在不同坐标系之间转换坐标

```python
from astropy.coordinates import SkyCoord
import astropy.units as u

# Create coordinate
c = SkyCoord(ra='05h23m34.5s', dec='-69d45m22s', frame='icrs')

# Transform to galactic
c_gal = c.galactic
print(f"l={c_gal.l.deg}, b={c_gal.b.deg}")

# Transform to alt-az (requires time and location)
from astropy.time import Time
from astropy.coordinates import EarthLocation, AltAz

observing_time = Time('2023-06-15 23:00:00')
observing_location = EarthLocation(lat=40*u.deg, lon=-120*u.deg)
aa_frame = AltAz(obstime=observing_time, location=observing_location)
c_altaz = c.transform_to(aa_frame)
print(f"Alt={c_altaz.alt.deg}, Az={c_altaz.az.deg}")
```

### 读取并分析 FITS 文件

```python
from astropy.io import fits
import numpy as np

# Open FITS file
with fits.open('observation.fits') as hdul:
    # Display structure
    hdul.info()

    # Get image data and header
    data = hdul[1].data
    header = hdul[1].header

    # Access header values
    exptime = header['EXPTIME']
    filter_name = header['FILTER']

    # Analyze data
    mean = np.mean(data)
    median = np.median(data)
    print(f"Mean: {mean}, Median: {median}")
```

### 宇宙学距离计算

```python
from astropy.cosmology import Planck18
import astropy.units as u
import numpy as np

# Calculate distances at z=1.5
z = 1.5
d_L = Planck18.luminosity_distance(z)
d_A = Planck18.angular_diameter_distance(z)

print(f"Luminosity distance: {d_L}")
print(f"Angular diameter distance: {d_A}")

# Age of universe at that redshift
age = Planck18.age(z)
print(f"Age at z={z}: {age.to(u.Gyr)}")

# Lookback time
t_lookback = Planck18.lookback_time(z)
print(f"Lookback time: {t_lookback.to(u.Gyr)}")
```

### 星表交叉匹配

```python
from astropy.table import Table
from astropy.coordinates import SkyCoord, match_coordinates_sky
import astropy.units as u

# Read catalogs
cat1 = Table.read('catalog1.fits')
cat2 = Table.read('catalog2.fits')

# Create coordinate objects
coords1 = SkyCoord(ra=cat1['RA']*u.degree, dec=cat1['DEC']*u.degree)
coords2 = SkyCoord(ra=cat2['RA']*u.degree, dec=cat2['DEC']*u.degree)

# Find matches
idx, sep, _ = coords1.match_to_catalog_sky(coords2)

# Filter by separation threshold
max_sep = 1 * u.arcsec
matches = sep < max_sep

# Create matched catalogs
cat1_matched = cat1[matches]
cat2_matched = cat2[idx[matches]]
print(f"Found {len(cat1_matched)} matches")
```

## 最佳实践

1. **始终使用单位**：为物理量附加单位，以避免错误并确保计算中的量纲一致性
2. **对 FITS 文件使用上下文管理器**：确保文件被正确关闭
3. **优先使用数组而非循环**：将多个坐标/时间作为数组处理，以获得更好的性能
4. **检查坐标系**：在进行变换前核实坐标所处的坐标系
5. **使用合适的宇宙学模型**：为你的分析选择正确的宇宙学模型
6. **处理缺失数据**：对含有缺失值的表格使用带掩码的列
7. **明确指定时间尺度**：为了精确计时，应明确说明所用的时间尺度（UTC、TT、TDB）
8. **对带单位的表格使用 QTable**：当表格列带有单位时
9. **检查 WCS 有效性**：在使用变换前核实 WCS 是否有效
10. **缓存常用的计算结果**：开销较大的计算（如宇宙学距离）可以被缓存
11. **明确网络访问情况**：`SkyCoord.from_name()`、`EarthLocation.of_site(refresh_cache=True)`、`EarthLocation.of_address()`、`download_file()`、远程 FITS 读取，以及部分 IERS 时间/坐标变换，可能会联系外部服务或更新本地缓存。避免将敏感的目标名称、地址、URL 或专有文件位置发送给第三方服务。在处理可能敏感的目标或数据位置时，进行这些网络调用前应先与用户确认。
12. **为可复现性锁定版本**：在共享环境中使用如 `astropy==7.2.0` 这样的锁定版本；仅在审阅发行说明之后，有意地更新锁定版本。

## 当前版本说明

- 已核实的当前稳定发行版：Astropy 7.2.0（发布于 2025-11-25；截至 2026-06-10 核实为当前版本）
- Python 版本要求：3.11 及以上
- **Astropy 8.0 目前处于候选发布阶段**（8.0.0rc1，2026-05-26）。需要预先留意的关键变化：
  - 已废弃的 `astropy.cosmology` 子模块垫片（`astropy.cosmology.flrw`、`.core`、`.funcs`、`.connect`、`.parameter`）已被移除——应直接从 `astropy.cosmology` 导入一切所需内容（例如 `from astropy.cosmology import FlatLambdaCDM, z_at_value`）
  - `astropy.constants` 的默认值由 CODATA 2018 变为 CODATA 2022；若可复现性有要求，应通过 `astropyconst` science states 锁定常数版本
  - NumPy 2.0 成为最低支持版本；7.2.x LTS 分支在 8.0 发布后的六个月内仍保留对 NumPy 1.x 的支持
  - 内置的测试运行器（`astropy.test()`、`TestRunner`）已被正式废弃——应直接调用 `pytest`
- 应在新代码中避免使用的近期 7.x 版本废弃用法：将表索引标识符作为 `.loc` 的第一个元素传入（`t.loc["b", 2]`）——应改用 `t.loc.with_index("b")[2]`（计划于 9.0 版本中移除）；`astropy.utils.isiterable()`——应改用 `numpy.iterable()`
- 近期 7.0 版本中已移除的内容：较旧的、已废弃的 FITS API，例如 `(Bin)Table.update`、`_ExtensionHDU`、`_NonstandardExtHDU`，以及 `CompImageHDU` 的 `tile_size` 参数；`CompImageHeader` 已被废弃。在新示例中应避免这些旧有用法。
- 推荐的可选附加依赖集为：`recommended`（用于常见的绘图/科学计算依赖），仅在需要更广泛的可选功能集时才使用 `all`。

## 文档与资源

- Astropy 官方文档：https://docs.astropy.org/en/stable/
- 教程：https://learn.astropy.org/
- GitHub：https://github.com/astropy/astropy

## 参考文件

关于各具体模块的详细信息：
- `references/units.md` - 单位、物理量、换算与等价关系
- `references/coordinates.md` - 坐标系统、变换与星表匹配
- `references/cosmology.md` - 宇宙学模型与计算
- `references/fits.md` - FITS 文件操作与处理
- `references/tables.md` - 表格创建、I/O 与相关操作
- `references/time.md` - 时间格式、时间尺度与计算
- `references/wcs_and_other_modules.md` - WCS、NDData、建模、可视化、常数与实用工具
