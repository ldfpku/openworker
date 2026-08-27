# NetworkX

## 概述

NetworkX 是一个用于创建、操作和分析复杂网络与图的 Python 包。当处理网络或图数据结构时使用此技能，包括社交网络、生物网络、交通系统、引文网络、知识图谱，或任何涉及实体间关系的系统。

本技能针对 NetworkX 3.x(当前稳定版为 3.6,要求 Python >= 3.11)。若干 3.0 版之前的 API(`nx.info`、`nx.write_gpickle`、`nx.read_shp`)以及 3.4 版本时代的 `nx.random_tree` 已不复存在——本技能全文使用的都是当前的替代方案。

## 何时使用此技能

在任务涉及以下内容时调用此技能：

- **创建图**：从数据构建网络结构，添加带属性的节点和边
- **图分析**：计算中心性度量、查找最短路径、检测社区、测量聚类系数
- **图算法**：运行标准算法，如 Dijkstra 算法、PageRank、最小生成树、最大流
- **网络生成**：为测试或仿真创建合成网络(随机网络、无标度网络、小世界网络模型)
- **图的 I/O**：在各种格式之间读写(边列表、GraphML、JSON、CSV、邻接矩阵)
- **可视化**：使用 matplotlib 或交互式库绘制并自定义网络可视化效果
- **网络比较**：检查同构性、计算图度量、分析结构属性

## 核心能力

### 1. 图的创建与操作

NetworkX 支持四种主要的图类型：
- **Graph**：无向图，单条边
- **DiGraph**：有向图，单向连接
- **MultiGraph**：无向图，允许节点间存在多条边
- **MultiDiGraph**：有向图，允许多条边

创建图的方式：
```python
import networkx as nx

# 创建空图
G = nx.Graph()

# 添加节点(可以是任何可哈希类型)
G.add_node(1)
G.add_nodes_from([2, 3, 4])
G.add_node("protein_A", type='enzyme', weight=1.5)

# 添加边
G.add_edge(1, 2)
G.add_edges_from([(1, 3), (2, 4)])
G.add_edge(1, 4, weight=0.8, relation='interacts')
```

**参考文档**：关于创建、修改、检查和管理图结构(包括处理属性和子图)的完整指导，见 `references/graph-basics.md`。

### 2. 图算法

NetworkX 为网络分析提供了大量算法：

**最短路径**：
```python
# 查找最短路径
path = nx.shortest_path(G, source=1, target=5)
length = nx.shortest_path_length(G, source=1, target=5, weight='weight')
```

**中心性度量**：
```python
# 度中心性
degree_cent = nx.degree_centrality(G)

# 介数中心性
betweenness = nx.betweenness_centrality(G)

# PageRank
pagerank = nx.pagerank(G)
```

**社区检测**：
```python
from networkx.algorithms import community

# 检测社区
communities = community.greedy_modularity_communities(G)
```

**连通性**：
```python
# 检查连通性
is_connected = nx.is_connected(G)

# 查找连通分量
components = list(nx.connected_components(G))
```

**参考文档**：关于全部可用算法的详细说明，包括最短路径、中心性度量、聚类、社区检测、流、匹配、树算法与图遍历，见 `references/algorithms.md`。

### 3. 图生成器

为测试、仿真或建模创建合成网络：

**经典图**：
```python
# 完全图
G = nx.complete_graph(n=10)

# 环图
G = nx.cycle_graph(n=20)

# 已知图
G = nx.karate_club_graph()
G = nx.petersen_graph()
```

**随机网络**：
```python
# Erdős-Rényi 随机图
G = nx.erdos_renyi_graph(n=100, p=0.1, seed=42)

# Barabási-Albert 无标度网络
G = nx.barabasi_albert_graph(n=100, m=3, seed=42)

# Watts-Strogatz 小世界网络
G = nx.watts_strogatz_graph(n=100, k=6, p=0.1, seed=42)
```

**结构化网络**：
```python
# 网格图
G = nx.grid_2d_graph(m=5, n=7)

# 随机树(random_tree 在 NetworkX 3.4 中已被移除)
G = nx.random_labeled_tree(100, seed=42)
```

**参考文档**：关于全部图生成器的详尽说明，包括经典图、随机模型(Erdős-Rényi、Barabási-Albert、Watts-Strogatz)、格点图、二部图以及专用网络模型，附带详细参数和使用场景，见 `references/generators.md`。

### 4. 图的读写

NetworkX 支持众多文件格式和数据源：

**文件格式**：
```python
# 边列表
G = nx.read_edgelist('graph.edgelist')
nx.write_edgelist(G, 'graph.edgelist')

# GraphML(保留属性)
G = nx.read_graphml('graph.graphml')
nx.write_graphml(G, 'graph.graphml')

# GML
G = nx.read_gml('graph.gml')
nx.write_gml(G, 'graph.gml')

# JSON(node-link 格式;自 NetworkX 3.6 起,边列表存储在
# "edges" 键下——旧文件可能使用 "links",详见 references/io.md)
data = nx.node_link_data(G)
G = nx.node_link_graph(data)
```

**与 Pandas 集成**：
```python
import pandas as pd

# 从 DataFrame 创建
df = pd.DataFrame({'source': [1, 2, 3], 'target': [2, 3, 4], 'weight': [0.5, 1.0, 0.75]})
G = nx.from_pandas_edgelist(df, 'source', 'target', edge_attr='weight')

# 导出为 DataFrame
df = nx.to_pandas_edgelist(G)
```

**矩阵格式**：
```python
import numpy as np

# 邻接矩阵
A = nx.to_numpy_array(G)
G = nx.from_numpy_array(A)

# 稀疏矩阵
A = nx.to_scipy_sparse_array(G)
G = nx.from_scipy_sparse_array(A)
```

**参考文档**：关于全部 I/O 格式的完整文档，包括 CSV、SQL 数据库、Cytoscape、DOT,以及针对不同使用场景的格式选型建议，见 `references/io.md`。

### 5. 可视化

创建清晰、信息丰富的网络可视化效果：

**基础可视化**：
```python
import matplotlib.pyplot as plt

# 简单绘制
nx.draw(G, with_labels=True)
plt.show()

# 带布局
pos = nx.spring_layout(G, seed=42)
nx.draw(G, pos=pos, with_labels=True, node_color='lightblue', node_size=500)
plt.show()
```

**自定义**：
```python
# 按度数着色
node_colors = [G.degree(n) for n in G.nodes()]
nx.draw(G, node_color=node_colors, cmap=plt.cm.viridis)

# 按中心性调整大小
centrality = nx.betweenness_centrality(G)
node_sizes = [3000 * centrality[n] for n in G.nodes()]
nx.draw(G, node_size=node_sizes)

# 边的权重
edge_widths = [3 * G[u][v].get('weight', 1) for u, v in G.edges()]
nx.draw(G, width=edge_widths)
```

**布局算法**：
```python
# 弹簧布局(力导向)
pos = nx.spring_layout(G, seed=42)

# 环形布局
pos = nx.circular_layout(G)

# Kamada-Kawai 布局
pos = nx.kamada_kawai_layout(G)

# 谱布局
pos = nx.spectral_layout(G)
```

**出版级质量**：
```python
plt.figure(figsize=(12, 8))
pos = nx.spring_layout(G, seed=42)
nx.draw(G, pos=pos, node_color='lightblue', node_size=500,
        edge_color='gray', with_labels=True, font_size=10)
plt.title('Network Visualization', fontsize=16)
plt.axis('off')
plt.tight_layout()
plt.savefig('network.png', dpi=300, bbox_inches='tight')
plt.savefig('network.pdf', bbox_inches='tight')  # 矢量格式
```

**参考文档**：关于可视化技术的详尽文档，包括布局算法、自定义选项、使用 Plotly 和 PyVis 的交互式可视化、三维网络，以及出版级质量图形的制作，见 `references/visualization.md`。

## 使用 NetworkX

### 安装

确认 NetworkX 已安装：
```python
# 检查是否已安装
import networkx as nx
print(nx.__version__)

# 如需安装(通过 bash)
# uv pip install networkx
# uv pip install networkx[default]  # 附带可选依赖
```

### 常见工作流程模式

大多数 NetworkX 任务都遵循以下模式：

1. **创建或加载图**：
   ```python
   # 从零创建
   G = nx.Graph()
   G.add_edges_from([(1, 2), (2, 3), (3, 4)])

   # 或从文件/数据加载
   G = nx.read_edgelist('data.txt')
   ```

2. **检查结构**：
   ```python
   print(f"Nodes: {G.number_of_nodes()}")
   print(f"Edges: {G.number_of_edges()}")
   print(f"Density: {nx.density(G)}")
   print(f"Connected: {nx.is_connected(G)}")
   ```

3. **分析**：
   ```python
   # 计算度量
   degree_cent = nx.degree_centrality(G)
   avg_clustering = nx.average_clustering(G)

   # 查找路径
   path = nx.shortest_path(G, source=1, target=4)

   # 检测社区
   communities = community.greedy_modularity_communities(G)
   ```

4. **可视化**：
   ```python
   pos = nx.spring_layout(G, seed=42)
   nx.draw(G, pos=pos, with_labels=True)
   plt.show()
   ```

5. **导出结果**：
   ```python
   # 保存图
   nx.write_graphml(G, 'analyzed_network.graphml')

   # 保存度量结果
   df = pd.DataFrame({
       'node': list(degree_cent.keys()),
       'centrality': list(degree_cent.values())
   })
   df.to_csv('centrality_results.csv', index=False)
   ```

### 重要注意事项

**浮点精度**：当图中包含浮点数时，由于精度限制，所有结果本质上都是近似值。这可能影响算法的结果，尤其是在最小值/最大值计算中。

**内存与性能**：每次脚本运行时，图数据都必须被载入内存。对于大型网络：
- 使用合适的数据结构(对大型稀疏图使用稀疏矩阵)
- 考虑只加载必要的子图
- 使用高效的文件格式(Python 对象用 pickle,或使用压缩格式)
- 对超大型网络利用近似算法(例如中心性计算中的 `k` 参数)
- 对于繁重的工作负载,NetworkX 3.x 通过 `backend=` 关键字参数或 `nx.config.backend_priority` 支持即插即用的加速后端——例如 `nx-cugraph`(GPU)、`nx-parallel`(多核)、`graphblas-algorithms`(稀疏线性代数)。安装相应的后端包，并向受支持的函数传入 `backend="cugraph"`(或类似值)即可；无需改动算法代码。

**节点与边的类型**：
- 节点可以是任何可哈希的 Python 对象(数字、字符串、元组、自定义对象)
- 为清晰起见，使用有意义的标识符
- 删除节点时，与之相连的所有边都会被自动删除

**随机种子**：在随机图生成和力导向布局中，始终设置随机种子以保证可复现性：
```python
G = nx.erdos_renyi_graph(n=100, p=0.1, seed=42)
pos = nx.spring_layout(G, seed=42)
```

## 快速参考

### 基本操作
```python
# 创建
G = nx.Graph()
G.add_edge(1, 2)

# 查询
G.number_of_nodes()
G.number_of_edges()
G.degree(1)
list(G.neighbors(1))

# 检查
G.has_node(1)
G.has_edge(1, 2)
nx.is_connected(G)

# 修改
G.remove_node(1)
G.remove_edge(1, 2)
G.clear()
```

### 常用算法
```python
# 路径
nx.shortest_path(G, source, target)
nx.all_pairs_shortest_path(G)

# 中心性
nx.degree_centrality(G)
nx.betweenness_centrality(G)
nx.closeness_centrality(G)
nx.pagerank(G)

# 聚类
nx.clustering(G)
nx.average_clustering(G)

# 连通分量
nx.connected_components(G)
nx.strongly_connected_components(G)  # 有向图

# 社区
community.greedy_modularity_communities(G)
```

### 文件 I/O 快速参考
```python
# 读取
nx.read_edgelist('file.txt')
nx.read_graphml('file.graphml')
nx.read_gml('file.gml')

# 写入
nx.write_edgelist(G, 'file.txt')
nx.write_graphml(G, 'file.graphml')
nx.write_gml(G, 'file.gml')

# Pandas
nx.from_pandas_edgelist(df, 'source', 'target')
nx.to_pandas_edgelist(G)
```

## 资源

此技能包含详尽的参考文档：

### references/graph-basics.md
关于图类型、创建与修改图、添加节点和边、管理属性、检查结构以及处理子图的详细指南。

### references/algorithms.md
关于 NetworkX 算法的完整说明，涵盖最短路径、中心性度量、连通性、聚类、社区检测、流算法、树算法、匹配、着色、同构判定与图遍历。

### references/generators.md
关于图生成器的详尽文档，包括经典图、随机模型(Erdős-Rényi、Barabási-Albert、Watts-Strogatz)、格点图、树、社交网络模型以及专用生成器。

### references/io.md
关于以各种格式读写图的完整指南:边列表、邻接列表、GraphML、GML、JSON、CSV、Pandas DataFrame、NumPy 数组、SciPy 稀疏矩阵、数据库集成，以及格式选型指南。

### references/visualization.md
关于可视化技术的详尽文档，包括布局算法、自定义节点和边的外观、标签、使用 Plotly 和 PyVis 的交互式可视化、三维网络、二部图布局，以及出版级质量图形的制作。

## 其他资源

- **官方文档**：https://networkx.org/documentation/latest/
- **教程**：https://networkx.org/documentation/latest/tutorial.html
- **示例库**：https://networkx.org/documentation/latest/auto_examples/index.html
- **GitHub**：https://github.com/networkx/networkx
