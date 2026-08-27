# GeoPandas

对于直接使用 GeoPandas `GeoSeries`、`GeoDataFrame`、空间操作，或矢量数据 I/O 的 Python 工作流，使用本技能获取指导和本地审计工具。本技能针对的是稳定版
**GeoPandas 1.1.4**（发布于 2026-06-26），而不是尚未发布的 1.2 版本文档。

## 可复现的环境

GeoPandas 1.1.4 要求 Python 3.10+；其带标签的源码要求 NumPy >=1.24、
pandas >=2.0、Shapely >=2.0、pyproj >=3.5、pyogrio >=0.7.2 以及 `packaging`。
以下这个确切的 Python 3.12 版本快照已于 2026-07-23 经过冒烟测试：

```bash
uv venv --python 3.12
uv pip install \
  "geopandas==1.1.4" \
  "numpy==2.5.1" \
  "pandas==3.0.5" \
  "shapely==2.1.2" \
  "pyproj==3.7.2" \
  "pyogrio==0.13.0" \
  "pyarrow==25.0.0" \
  "packaging==26.2"
```

也要在项目锁文件中固定可选的绘图和 PostGIS 相关软件包的版本。
不要混用来自不兼容的软件包渠道（channel）的二进制地理空间软件包。

## 安全与隐私约定

- 将精确坐标、地址、地块边界、轨迹，以及小范围空间连接（join）的结果都视为敏感信息。
  报告默认只呈现计数、类别、粗略范围以及经过脱敏处理的标识符。发布前需先做泛化处理。
- 切勿自动加载 URL、云端 URI、GDAL 的 `/vsi*` 路径、压缩包，也不要自动对地址进行地理编码（geocode）。
  应先获得明确批准、核实来源与哈希值，然后将解压后的文件放到一个隔离的工作区中处理。
- GDAL/OGR 驱动、GEOS、PROJ、pyogrio、Shapely、pyproj 及其 wheel 包构成了一个原生代码信任边界。
  优先使用官方 wheel 包/conda-forge，记录所用的原生库版本，限制可用驱动的范围，
  并在沙箱环境中处理不可信数据。
- 不要通过权限宽松的 GDAL 驱动打开启用了宏的 Office 文件或嵌套压缩包。
  附带的 CLI 工具使用扩展名白名单，并拒绝处理压缩包。
- 只读取具名的数据库密钥，例如 `GEOPANDAS_POSTGIS_PASSWORD`；应使用密钥管理器或作用域受限的
  环境变量。切勿将密码嵌入 URL 或源码中，不要打印数据库连接引擎/URL，也不要转储环境变量。
- 每一份派生产物都需要记录源数据的哈希值/版本号、CRS（坐标参考系统）、操作参数、
  谓词（predicate）、连接的基数关系（join cardinality）、精度/修复方式的选择，以及行数核查结果。

## 正确性检查关卡

在信任某个结果之前，需通过以下关卡：

1. **身份与来源信息** —— 明确源图层、稳定的要素键（feature key）、
   重复 ID、行数、几何列、所用的解析器/驱动，以及内容哈希值。
2. **几何状态** —— 分别统计空值（null）、空几何（empty）、无效、混合类型、Z/M 维度，
   以及坍缩（collapsed）的几何数量。`None` 是缺失值；一个空的 Shapely 几何对象则是真实存在的对象。
3. **CRS 语义** —— 要求存在 CRS 元数据。`set_crs()` 是赋值元数据；
   `to_crs()` 才是对坐标进行变换。切勿从坐标数值的范围来猜测 CRS。
4. **单位与操作** —— GeoPandas 处理的是平面几何。地理坐标是角度单位；
   不要直接将其用于缓冲区（buffer）、距离、面积、最近邻连接、精度网格或容差计算。
   应选择一个适合具体用途的局部/等积投影 CRS，或使用测地线（geodesic）方法。
5. **变换质量** —— 检查坐标轴顺序、适用范围（area of use）、基准面变换管线（datum pipeline）、
   预期精度、"大致估算（ballpark）"状态，以及缺失的变换格网（grid）。
   除非用户明确同意获取变换格网，否则应保持 PROJ 网络访问处于禁用状态。
6. **拓扑与精度** —— 在修复/叠加操作前后都要进行有效性校验。
   应根据源数据精度和 CRS 单位来选取精度格网；随意的吸附（snapping）
   可能会导致要素坍缩或产生偏差。
7. **基数关系** —— 在执行 `merge`、`sjoin` 或 `sjoin_nearest` 之前，
   先说明预期是一对一、一对多还是多对多的关系；操作之后要审计未匹配和被重复匹配的行。
8. **输出约定** —— 使用一个新的输出路径、保留稳定的要素 ID、
   记录模式（schema）/CRS/编码方式，重新打开该产物文件并核对行数/类型。

## CRS 与反经线（antimeridian）规则

GeoPandas 将 CRS 存储为 `pyproj.CRS` 对象。坐标数组采用传统 GIS 的
`(x, y)` 顺序，而权威机构定义的坐标系可能会声明纬度优先的坐标轴顺序。
在显式的坐标数组处理流程中应使用 `Transformer(..., always_xy=True)`，
并记录下这一选择。

`to_crs()` 变换的是顶点坐标，并假设每一段线段在源 CRS 下都是直线；
它并不会对测地线弧进行变换。跨越 ±180° 经线或某个投影边界的几何对象
可能会被严重错误地"包裹"。应先检测这类跨越情况，在一个明确记录的地理坐标表示下
拆分/展开并加密（densify）几何，再对各部分分别做变换，最后进行校验。
不要将 Web Mercator 用作通用的测量用 CRS。

```python
crs = gdf.crs  # a pyproj.CRS when present
if crs is None or crs.is_geographic:
    raise ValueError("Choose a justified projected CRS before planar measurement")

unit_names = [axis.unit_name for axis in crs.axis_info]
areas = gdf.geometry.area  # square CRS units, not automatically square metres
```

参见 [CRS 管理](references/crs-management.md)。

## 核心 API 决策

### 数据结构

- 一个 `GeoDataFrame` 可以包含多个几何列，每一列都带有各自的 CRS 元数据，
  但只有 `active_geometry_name` 所指定的那一列会驱动整个数据框层级的空间操作。
- `GeoSeries` 的二元方法是逐行（row-wise）操作的，默认按索引对齐。
  只有当明确打算按位置配对，并且已核实长度和顺序一致时，才使用 `align=False`。
- 重复的列名和重复的要素 ID 会带来歧义；应在做连接和导出之前先拒绝或解决这些重复情况。

参见 [数据结构](references/data-structures.md)。

### 几何有效性、精度与合并（union）

在使用 `make_valid(method="linework"|"structure", keep_collapsed=...)` 之前，
先使用 `is_valid` 和经过脱敏处理的 `is_valid_reason()` 类别信息。修复操作
可能会改变几何类型或维度；应保留原始数据，并比较行数、面积、类型、空几何数量，
以及坍缩部分的数量。

`set_precision(grid_size, mode=...)` 使用的是 **CRS 单位**，可能会移除
重复的顶点或使要素坍缩。`union_all(method="unary", grid_size=...)` 是稳健的默认选择。
只有在 `is_valid_coverage()` 证明不存在重叠且边缘匹配之后，才使用 `coverage` 方法；
在 Shapely >=2.1 环境下，如果其分区（partitioning）假设适用，可使用 `disjoint_subset`。

参见 [几何操作](references/geometric-operations.md)。

### 连接（join）、叠加（overlay）、裁切（clip）与融合（dissolve）

- `sjoin` 的谓词是有方向性的：`left.within(right)` 并不等同于
  `left.contains(right)`。`intersects` 包含边界接触的情况；`contains`
  排除仅在边界上的点，而 `covers` 则包含边界上的点。
- `predicate="dwithin"` 需要提供 `distance` 参数；无论是标量还是逐行指定的距离值，
  单位都是 CRS 单位。`sjoin_nearest` 会返回所有距离相等的最近匹配结果，
  它**不**实现 `k=` 参数。
- `overlay(..., make_valid=True)` 会修复无效的输入，但可能改变几何类型；
  `keep_geom_type=None` 会丢弃其他类型的几何，并给出警告。精度不匹配可能会
  产生细碎的"薄片"（slivers）几何；应对其进行量化，而不是悄悄将其删除。
- `clip` 会对掩膜（mask）进行融合。矩形裁切速度快，但结果可能不够"干净"，
  且可能遗漏坍缩成一个点的线要素；需要对其输出进行校验。
- `dissolve` 结合了 `groupby.agg` 与 `union_all`；应显式选择属性聚合方式，
  并审计空值分组键的情况。

参见 [空间分析](references/spatial-analysis.md)。

### I/O、Arrow 与 PostGIS

GeoPandas 1.x 默认使用 pyogrio。驱动的可用性和语义取决于所安装的 GDAL，
而不仅仅是 GeoPandas 本身。通用数据交换场景优先使用本地 GeoPackage 格式，
列式互操作场景则优先使用 WKB GeoParquet 格式。

GeoParquet 默认使用稳定的 1.0.0 schema。原生的 GeoArrow 编码方式和边界框
覆盖（bbox covering）功能需要 1.1.0 schema，且互操作性仍然较弱。GeoParquet 中缺失
`crs` 键意味着使用 `OGC:CRS84`；而显式设置 `crs: null` 则表示未知——不要将两者混为一谈。
每次导出后都要重新打开文件并进行校验。

对 PostGIS 应使用参数化 SQL 以及 SQLAlchemy 的 `Engine`/`Connection`。
`if_exists="replace"` 具有破坏性；默认应使用 `"fail"`，并在事务中操作。

参见 [数据 I/O](references/data-io.md)。

## 迁移检查清单

对于从 GeoPandas 0.14 或更早版本迁移过来的代码：

- GeoPandas 1.0 只支持 Shapely >=2；PyGEOS、Shapely <2，以及 rtree
  空间索引后端均已被移除。
- pyogrio 已取代 Fiona 成为默认安装/使用的 I/O 引擎。应显式设置 `engine=`，
  并测试 schema、空值、日期时间、编码方式和追加（append）行为。
- 将 `sjoin(op=...)` 替换为 `predicate=`，将 `sindex.query_bulk()` 替换为
  `sindex.query()`，将 `unary_union` 替换为 `union_all()`，
  将 `GeometryArray.data` 替换为 `to_numpy()`/`np.asarray`。
- 将 `read_file(include_fields=...|ignore_fields=...)` 替换为 `columns=`。
  使用 `schema_version=`，而不是已移除的 GeoParquet `version=` 兼容参数。
- 不要使用已移除的 `geopandas.datasets`、内部的 `geopandas.io.*` 入口点、
  绘图相关的 `axes`/`colormap` 参数，或集合运算符（set-operation operators）。
- `explode()` 现在默认 `index_parts=False`；传给 `set_geometry()` 的带名 Series
  会提供新的活动几何列名称；带名的右侧索引可以在 `sjoin` 的输出中替代 `index_right`。
- 不要通过赋值 `.crs` 来覆盖元数据，也不要依赖已弃用的
  `set_geometry(drop=...)`；应使用显式的 `set_crs()` 以及重命名/删除步骤。
- GeoPandas 1.1 要求 Python >=3.10、pandas >=2.0、NumPy >=1.24 和 pyproj
  >=3.5。1.1.2 版本修复了一个通过 PostGIS 几何列名触发的 SQL 注入漏洞；
  本技能固定使用的 1.1.4 版本已包含该修复。

### 绘图与探索

地图是分析性的输出产物：应标注单位、分类方法、缺失数据情况、
归一化的分母，以及日期。`explore()` 可能会在提示框/弹窗中暴露每一个属性字段，
并且会联系瓦片图/CDN 服务器；对于本地草稿，应先做泛化处理，并使用
`tiles=None`、`tooltip=False` 和 `popup=False`。

参见 [可视化](references/visualization.md)。

## 附带的本地命令行工具（CLI）

所有辅助工具都是确定性的、拒绝处理网络/压缩包路径、对输入字节数和要素数量
设有上限、导入采用惰性加载（因此 `--help` 不依赖外部库），
并且输出的 JSON 中不含坐标或记录标识符。

| CLI | 用途 |
|---|---|
| `scripts/vector_inventory.py` | 经过脱敏处理的本地矢量/GeoParquet 技术清单 |
| `scripts/crs_reprojection_plan.py` | CRS 单位、坐标轴、候选变换方案与反经线处理计划 |
| `scripts/geometry_validity_report.py` | 演练式（dry-run）有效性审计；可选修复并输出到新的 GeoPackage |
| `scripts/spatial_join_audit.py` | 谓词语义、重复 ID 与连接基数关系 |
| `scripts/export_plan.py` | 非执行式的矢量/GeoParquet 导出方案 |
| `scripts/sensitive_coordinates_checklist.py` | 隐私/泛化处理的发布关卡检查 |

```bash
python skills/geopandas/scripts/vector_inventory.py --help
python skills/geopandas/scripts/crs_reprojection_plan.py \
  --source-crs EPSG:4326 --target-crs EPSG:32631
python skills/geopandas/scripts/geometry_validity_report.py data.gpkg
python skills/geopandas/scripts/spatial_join_audit.py points.gpkg zones.gpkg \
  --predicate within --left-id point_id --right-id zone_id
python skills/geopandas/scripts/export_plan.py data.gpkg result.parquet \
  --format geoparquet --schema-version 1.0.0 \
  --stable-id-column feature_id --id-unique-verified
python skills/geopandas/scripts/sensitive_coordinates_checklist.py \
  --public-output --precise-points --contains-addresses
```

## 参考文档索引

- [数据结构](references/data-structures.md)
- [CRS 管理](references/crs-management.md)
- [几何操作](references/geometric-operations.md)
- [空间分析](references/spatial-analysis.md)
- [数据 I/O](references/data-io.md)
- [可视化](references/visualization.md)

## 来源（截至 2026-07-23 验证）

- [GeoPandas 1.1.4 on PyPI](https://pypi.org/project/geopandas/1.1.4/) — 发布于 2026-06-26。
- [GeoPandas 1.1.4 release](https://github.com/geopandas/geopandas/releases/tag/v1.1.4) — 缺陷修复版本。
- [GeoPandas 1.1.4 tagged dependencies](https://github.com/geopandas/geopandas/blob/v1.1.4/pyproject.toml)。
- [Stable GeoPandas documentation](https://geopandas.org/en/stable/)。
- [GeoPandas 1.0 migration release](https://github.com/geopandas/geopandas/releases/tag/v1.0.0)。
