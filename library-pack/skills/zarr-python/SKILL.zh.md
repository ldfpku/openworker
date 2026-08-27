# Zarr Python

## 概述

Zarr 是一个用于存储带分块(chunking)和压缩功能的大型 N 维数组的 Python 库。将本 skill 用于高效的并行 I/O、云原生工作流，以及与 NumPy、Dask 和 Xarray 的无缝集成。

**当前上游版本**: zarr **3.2.1**(发布于 2026-05-05)。文档地址:[zarr.readthedocs.io](https://zarr.readthedocs.io/en/stable/)。新建数组默认使用 **Zarr format 3**;如需兼容旧版本，设置 `zarr_format=2`。Zarr 3.2 新增了矩形分块(rectilinear chunks),并持续完善 v3 编解码器(codec)流水线。本 skill 是由 K-Dense Inc. 维护的**社区指南**,并非 zarr-developers 官方发布的软件包。

## 快速开始

### 安装

```bash
uv pip install "zarr==3.2.1"
```

当前稳定版 Zarr-Python 要求 **Python 3.12+** 及 NumPy 2.0+。对于远程存储(S3、GCS、HTTP),在项目锁定文件中锁定可选的 extra/后端版本:

```bash
uv pip install "zarr[remote]==3.2.1" "s3fs==2026.4.0" "gcsfs==2026.5.0"
```

只有在你的项目已有一份提交的锁定文件并配有兼容性测试时，才使用类似 `zarr>=3,<4` 这样的版本范围。对于 Zarr-Python 2 / Python 3.10-3.11 的工作流，应从 support-v2 发布说明中选择一个确切的 `zarr==2.x.y` 补丁版本，并提交生成的锁定文件。

### 基础数组创建

```python
import zarr
import numpy as np

# Create a 2D array with chunking and compression
z = zarr.create_array(
    store="data/my_array.zarr",
    shape=(10000, 10000),
    chunks=(1000, 1000),
    dtype="f4"
)

# Write data using NumPy-style indexing
z[:, :] = np.random.random((10000, 10000))

# Read data
data = z[0:100, 0:100]  # Returns NumPy array
```

## 核心操作

### 创建数组

Zarr 提供了多个用于创建数组的便捷函数:

```python
# Create empty array
z = zarr.zeros(shape=(10000, 10000), chunks=(1000, 1000), dtype='f4',
               store='data.zarr')

# Create filled arrays
z = zarr.ones((5000, 5000), chunks=(500, 500))
z = zarr.full((1000, 1000), fill_value=42, chunks=(100, 100))

# Create from existing data
data = np.arange(10000).reshape(100, 100)
z = zarr.array(data, chunks=(10, 10), store='data.zarr')

# Create like another array
z2 = zarr.zeros_like(z)  # Matches shape, chunks, dtype of z
```

### 打开已有数组

```python
# Open array (read/write mode by default)
z = zarr.open_array('data.zarr', mode='r+')

# Read-only mode
z = zarr.open_array('data.zarr', mode='r')

# The open() function auto-detects arrays vs groups
z = zarr.open('data.zarr')  # Returns Array or Group
```

### 读写数据

Zarr 数组支持类似 NumPy 的索引方式:

```python
# Write entire array
z[:] = 42

# Write slices
z[0, :] = np.arange(100)
z[10:20, 50:60] = np.random.random((10, 10))

# Read data (returns NumPy array)
data = z[0:100, 0:100]
row = z[5, :]

# Advanced indexing
z.vindex[[0, 5, 10], [2, 8, 15]]  # Coordinate indexing
z.oindex[0:10, [5, 10, 15]]       # Orthogonal indexing
z.blocks[0, 0]                     # Block/chunk indexing
```

### 调整大小与追加

```python
# Resize array (v3: pass shape as a tuple)
z.resize((15000, 15000))

# Append data along an axis
z.append(np.random.random((1000, 10000)), axis=0)  # Adds rows
```

## 组(Groups)与层级结构

组以层级方式组织多个数组，类似于目录或 HDF5 中的组。

### 创建和使用组

```python
# Create root group
root = zarr.group(store='data/hierarchy.zarr')

# Create sub-groups
temperature = root.create_group('temperature')
precipitation = root.create_group('precipitation')

# Create arrays within groups
temp_array = temperature.create_array(
    name='t2m',
    shape=(365, 720, 1440),
    chunks=(1, 720, 1440),
    dtype='f4'
)

precip_array = precipitation.create_array(
    name='prcp',
    shape=(365, 720, 1440),
    chunks=(1, 720, 1440),
    dtype='f4'
)

# Access using paths
array = root['temperature/t2m']

# Visualize hierarchy
print(root.tree())
# Output:
# /
#  ├── temperature
#  │   └── t2m (365, 720, 1440) f4
#  └── precipitation
#      └── prcp (365, 720, 1440) f4
```

### 组 API(v3)

使用 `create_array` / `require_array`(h5py 风格的 `create_dataset` / `require_dataset` 在 v3 中已被移除):

```python
root = zarr.group('data.zarr')
arr = root.create_array('my_data', shape=(1000, 1000), chunks=(100, 100), dtype='f4')

grp = root.require_group('subgroup')
arr2 = grp.require_array('array', shape=(500, 500), chunks=(50, 50), dtype='i4')
```

## 属性与元数据

使用属性(attributes)为数组和组附加自定义元数据:

```python
# Add attributes to array
z = zarr.zeros((1000, 1000), chunks=(100, 100))
z.attrs['description'] = 'Temperature data in Kelvin'
z.attrs['units'] = 'K'
z.attrs['created'] = '2024-01-15'
z.attrs['processing_version'] = 2.1

# Attributes are stored as JSON
print(z.attrs['units'])  # Output: K

# Add attributes to groups
root = zarr.group('data.zarr')
root.attrs['project'] = 'Climate Analysis'
root.attrs['institution'] = 'Research Institute'

# Attributes persist with the array/group
z2 = zarr.open('data.zarr')
print(z2.attrs['description'])
```

**重要提示**:属性必须是可 JSON 序列化的(字符串、数字、列表、字典、布尔值、null)。

## 分块、压缩、存储与性能

- [references/chunking_and_compression.md](references/chunking_and_compression.md):
  根据访问模式设置分块大小(目标约 1 MB,云端场景 5-100 MB)、分片(sharding),
  以及编解码器的选择。
- [references/storage_backends.md](references/storage_backends.md):本地、内存、ZIP,
  以及基于 fsspec 的远程存储(S3、GCS),含凭证使用指南——优先使用 IAM 角色或
  工作负载身份(workload identity),绝不打印凭证值。
- [references/integration.md](references/integration.md):与 NumPy、Dask 和 Xarray 的
  集成、线程安全性，以及合并元数据(consolidated metadata)。
- [references/performance_and_patterns.md](references/performance_and_patterns.md):
  性能优化、可追加的时间序列与大矩阵模式、格式转换，以及故障排查。
- [references/api_reference.md](references/api_reference.md) 与
  [references/v3_migration.md](references/v3_migration.md):完整 API 以及 v2 到 v3 的
  迁移说明。

## 其他资源

### 随附参考文档

| 文件 | 内容 |
|------|----------|
| `references/api_reference.md` | 函数签名、存储、编解码器、索引 |
| `references/v3_migration.md` | Zarr-Python 2→3 的破坏性变更及在建功能 |

### 官方上游

- **文档**: https://zarr.readthedocs.io/en/stable/
- **3.0 迁移指南**: https://zarr.readthedocs.io/en/stable/user-guide/v3_migration/
- **存储后端**: https://zarr.readthedocs.io/en/stable/user-guide/storage/
- **Zarr 规范**: https://zarr-specs.readthedocs.io/
- **GitHub**: https://github.com/zarr-developers/zarr-python
- **开发者聊天室**: https://ossci.zulipchat.com/#narrow/channel/423692-Zarr-Python

**相关库**: [Xarray](https://docs.xarray.dev/)、[Dask](https://docs.dask.org/)、[NumCodecs](https://numcodecs.readthedocs.io/)
