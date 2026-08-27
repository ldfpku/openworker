# GeoMaster

覆盖 GIS、遥感、空间分析以及面向地球观测的机器学习的综合性地理空间科学技能，涵盖 70 多个主题，提供 8 种编程语言的 500 多个代码示例。

## 安装

```bash
# Core Python stack (conda recommended)
conda install -c conda-forge gdal rasterio fiona shapely pyproj geopandas

# Remote sensing & ML
uv pip install rsgislib torchgeo earthengine-api
uv pip install scikit-learn xgboost torch-geometric

# Network & visualization
uv pip install osmnx networkx folium keplergl
uv pip install cartopy contextily mapclassify

# Big data & cloud
uv pip install xarray rioxarray dask-geopandas
uv pip install pystac-client planetary-computer

# Point clouds
uv pip install laspy pylas open3d pdal

# Databases
conda install -c conda-forge postgis spatialite
```

## 快速上手

### 由 Sentinel-2 计算 NDVI

```python
import rasterio
import numpy as np

with rasterio.open('sentinel2.tif') as src:
    red = src.read(4).astype(float)   # B04
    nir = src.read(8).astype(float)   # B08
    ndvi = (nir - red) / (nir + red + 1e-8)
    ndvi = np.nan_to_num(ndvi, nan=0)

    profile = src.profile
    profile.update(count=1, dtype=rasterio.float32)

    with rasterio.open('ndvi.tif', 'w', **profile) as dst:
        dst.write(ndvi.astype(rasterio.float32), 1)
```

### 使用 GeoPandas 进行空间分析

```python
import geopandas as gpd

# Load and ensure same CRS
zones = gpd.read_file('zones.geojson')
points = gpd.read_file('points.geojson')

if zones.crs != points.crs:
    points = points.to_crs(zones.crs)

# Spatial join and statistics
joined = gpd.sjoin(points, zones, how='inner', predicate='within')
stats = joined.groupby('zone_id').agg({
    'value': ['count', 'mean', 'std', 'min', 'max']
}).round(2)
```

### Google Earth Engine 时间序列

```python
import ee
import pandas as pd

ee.Initialize(project='your-project')
roi = ee.Geometry.Point([-122.4, 37.7]).buffer(10000)

s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
      .filterBounds(roi)
      .filterDate('2020-01-01', '2023-12-31')
      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)))

def add_ndvi(img):
    return img.addBands(img.normalizedDifference(['B8', 'B4']).rename('NDVI'))

s2_ndvi = s2.map(add_ndvi)

def extract_series(image):
    stats = image.reduceRegion(ee.Reducer.mean(), roi.centroid(), scale=10, maxPixels=1e9)
    return ee.Feature(None, {'date': image.date().format('YYYY-MM-dd'), 'ndvi': stats.get('NDVI')})

series = s2_ndvi.map(extract_series).getInfo()
df = pd.DataFrame([f['properties'] for f in series['features']])
df['date'] = pd.to_datetime(df['date'])
```

## 核心概念

### 数据类型

| 类型 | 示例 | 库 |
|------|----------|-----------|
| 矢量 | Shapefile、GeoJSON、GeoPackage | GeoPandas、Fiona、GDAL |
| 栅格 | GeoTIFF、NetCDF、COG | Rasterio、Xarray、GDAL |
| 点云 | LAS、LAZ | Laspy、PDAL、Open3D |

### 坐标系统

- **EPSG:4326**（WGS 84）- 地理坐标系，经纬度，用于数据存储
- **EPSG:3857**（Web 墨卡托）- 仅用于网络地图（切勿用于面积/距离计算！）
- **EPSG:326xx/327xx**（UTM）- 用于公制计算，每个分区的畸变率 <1%
- 使用 `gdf.estimate_utm_crs()` 自动检测对应的 UTM 坐标系

```python
# Always check CRS before operations
assert gdf1.crs == gdf2.crs, "CRS mismatch!"

# For area/distance calculations, use projected CRS
gdf_metric = gdf.to_crs(gdf.estimate_utm_crs())
area_sqm = gdf_metric.geometry.area
```

### OGC 标准

- **WMS**：网络地图服务（Web Map Service）——栅格地图
- **WFS**：网络要素服务（Web Feature Service）——矢量数据
- **WCS**：网络覆盖服务（Web Coverage Service）——栅格覆盖数据
- **STAC**：时空资产目录（Spatiotemporal Asset Catalog）——现代元数据标准

## 常见操作

### 光谱指数

```python
def calculate_indices(image_path):
    """NDVI, EVI, SAVI, NDWI from Sentinel-2."""
    with rasterio.open(image_path) as src:
        B02, B03, B04, B08, B11 = [src.read(i).astype(float) for i in [1,2,3,4,5]]

    ndvi = (B08 - B04) / (B08 + B04 + 1e-8)
    evi = 2.5 * (B08 - B04) / (B08 + 6*B04 - 7.5*B02 + 1)
    savi = ((B08 - B04) / (B08 + B04 + 0.5)) * 1.5
    ndwi = (B03 - B08) / (B03 + B08 + 1e-8)

    return {'NDVI': ndvi, 'EVI': evi, 'SAVI': savi, 'NDWI': ndwi}
```

### 矢量操作

```python
# Buffer (use projected CRS!)
gdf_proj = gdf.to_crs(gdf.estimate_utm_crs())
gdf['buffer_1km'] = gdf_proj.geometry.buffer(1000)

# Spatial relationships
intersects = gdf[gdf.geometry.intersects(other_geometry)]
contains = gdf[gdf.geometry.contains(point_geometry)]

# Geometric operations
gdf['centroid'] = gdf.geometry.centroid
gdf['simplified'] = gdf.geometry.simplify(tolerance=0.001)

# Overlay operations
intersection = gpd.overlay(gdf1, gdf2, how='intersection')
union = gpd.overlay(gdf1, gdf2, how='union')
```

### 地形分析

```python
def terrain_metrics(dem_path):
    """Calculate slope, aspect, hillshade from DEM."""
    with rasterio.open(dem_path) as src:
        dem = src.read(1)

    dy, dx = np.gradient(dem)
    slope = np.arctan(np.sqrt(dx**2 + dy**2)) * 180 / np.pi
    aspect = (90 - np.arctan2(-dy, dx) * 180 / np.pi) % 360

    # Hillshade
    az_rad, alt_rad = np.radians(315), np.radians(45)
    hillshade = (np.sin(alt_rad) * np.sin(np.radians(slope)) +
                 np.cos(alt_rad) * np.cos(np.radians(slope)) *
                 np.cos(np.radians(aspect) - az_rad))

    return slope, aspect, hillshade
```

### 网络分析

```python
import osmnx as ox
import networkx as nx

# Download and analyze street network
G = ox.graph_from_place('San Francisco, CA', network_type='drive')
G = ox.add_edge_speeds(G).add_edge_travel_times(G)

# Shortest path
orig = ox.distance.nearest_nodes(G, -122.4, 37.7)
dest = ox.distance.nearest_nodes(G, -122.3, 37.8)
route = nx.shortest_path(G, orig, dest, weight='travel_time')
```

## 影像分类

```python
from sklearn.ensemble import RandomForestClassifier
import rasterio
from rasterio.features import rasterize

def classify_imagery(raster_path, training_gdf, output_path):
    """Train RF and classify imagery."""
    with rasterio.open(raster_path) as src:
        image = src.read()
        profile = src.profile
        transform = src.transform

    # Extract training data
    X_train, y_train = [], []
    for _, row in training_gdf.iterrows():
        mask = rasterize([(row.geometry, 1)],
                        out_shape=(profile['height'], profile['width']),
                        transform=transform, fill=0, dtype=np.uint8)
        pixels = image[:, mask > 0].T
        X_train.extend(pixels)
        y_train.extend([row['class_id']] * len(pixels))

    # Train and predict
    rf = RandomForestClassifier(n_estimators=100, max_depth=20, n_jobs=-1)
    rf.fit(X_train, y_train)

    prediction = rf.predict(image.reshape(image.shape[0], -1).T)
    prediction = prediction.reshape(profile['height'], profile['width'])

    profile.update(dtype=rasterio.uint8, count=1)
    with rasterio.open(output_path, 'w', **profile) as dst:
        dst.write(prediction.astype(rasterio.uint8), 1)

    return rf
```

## 现代云原生工作流

### STAC + Planetary Computer

```python
import pystac_client
import planetary_computer
import odc.stac

# Search Sentinel-2 via STAC
catalog = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace,
)

search = catalog.search(
    collections=["sentinel-2-l2a"],
    bbox=[-122.5, 37.7, -122.3, 37.9],
    datetime="2023-01-01/2023-12-31",
    query={"eo:cloud_cover": {"lt": 20}},
)

# Load as xarray (cloud-native!)
data = odc.stac.load(
    list(search.get_items())[:5],
    bands=["B02", "B03", "B04", "B08"],
    crs="EPSG:32610",
    resolution=10,
)

# Calculate NDVI on xarray
ndvi = (data.B08 - data.B04) / (data.B08 + data.B04)
```

### 云优化 GeoTIFF（COG）

```python
import rasterio
from rasterio.session import AWSSession

# Read COG directly from cloud (partial reads)
session = AWSSession(aws_access_key_id=..., aws_secret_access_key=...)
with rasterio.open('s3://bucket/path.tif', session=session) as src:
    # Read only window of interest
    window = ((1000, 2000), (1000, 2000))
    subset = src.read(1, window=window)

# Write COG
with rasterio.open('output.tif', 'w', **profile,
                   tiled=True, blockxsize=256, blockysize=256,
                   compress='DEFLATE', predictor=2) as dst:
    dst.write(data)

# Validate COG
from rio_cogeo.cogeo import cog_validate
cog_validate('output.tif')
```

## 性能建议

```python
# 1. Spatial indexing (10-100x faster queries)
gdf.sindex  # Auto-created by GeoPandas

# 2. Chunk large rasters
with rasterio.open('large.tif') as src:
    for i, window in src.block_windows(1):
        block = src.read(1, window=window)

# 3. Dask for big data
import dask.array as da
dask_array = da.from_rasterio('large.tif', chunks=(1, 1024, 1024))

# 4. Use Arrow for I/O
gdf.to_file('output.gpkg', use_arrow=True)

# 5. GDAL caching
from osgeo import gdal
gdal.SetCacheMax(2**30)  # 1GB cache

# 6. Parallel processing
rf = RandomForestClassifier(n_jobs=-1)  # All cores
```

## 最佳实践

1. **在进行空间操作前，务必先检查 CRS**
2. **面积/距离计算须使用投影坐标系**
3. **验证几何图形有效性**：`gdf = gdf[gdf.is_valid]`
4. **处理缺失数据**：`gdf['geometry'] = gdf['geometry'].fillna(None)`
5. **使用高效的数据格式**：GeoPackage 优于 Shapefile，大数据量场景使用 Parquet
6. **对光学影像应用云掩膜（cloud masking）**
7. **保留数据处理脉络（lineage）**，以支持可复现的研究
8. **根据分析尺度选择合适的分辨率**

## 详细文档

- **[坐标系统](references/coordinate-systems.md)** - CRS 基础知识、UTM、坐标变换
- **[核心库](references/core-libraries.md)** - GDAL、Rasterio、GeoPandas、Shapely
- **[遥感](references/remote-sensing.md)** - 卫星任务、光谱指数、SAR
- **[机器学习](references/machine-learning.md)** - 面向遥感的深度学习、CNN、GNN
- **[GIS 软件](references/gis-software.md)** - QGIS、ArcGIS、GRASS 集成
- **[科学领域](references/scientific-domains.md)** - 海洋、水文、农业、林业
- **[高级 GIS](references/advanced-gis.md)** - 三维 GIS、时空分析、拓扑关系
- **[大数据](references/big-data.md)** - 分布式处理、GPU 加速
- **[行业应用](references/industry-applications.md)** - 城市规划、灾害管理
- **[编程语言](references/programming-languages.md)** - Python、R、Julia、JS、C++、Java、Go、Rust
- **[数据源](references/data-sources.md)** - 卫星数据目录、API
- **[故障排查](references/troubleshooting.md)** - 常见问题、调试、错误参考
- **[代码示例](references/code-examples.md)** - 500 多个示例

---

**GeoMaster 涵盖从基础 GIS 操作到高级遥感与机器学习的方方面面**。
