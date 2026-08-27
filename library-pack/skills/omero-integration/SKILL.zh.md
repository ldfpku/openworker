# OMERO 集成（OMERO Integration）

使用最新的 OME 文档，并采用最小的、明确指定的数据范围。OMERO 中的
数据可能包含尚未发表的图像、标识符、注释、原始文件，以及派生出的
测量值。

## 已核实的基线版本

本技能于 **2026-07-23** 做了更新：

- **OMERO.server 5.6.18**（2026 年 5 月）是当前文档记载的稳定服务器
  版本。
- OME 使用 **OMERO.py/omero-py 5.22.1** 和 **OMERO.web 5.31.0** 对其
  做过测试。
- `omero-py==5.22.1` 需要 Python 3.10 或更高版本。OMERO 的支持矩阵
  支持 3.10 和 3.11，推荐使用 3.12，而 3.13/3.14 仍被标记为「即将
  支持」。
- OMERO 5.6 使用 **IcePy 3.6**，其中 3.6.5 版本的预构建客户端 wheel
  文件在文档中列出了支持到 Python 3.12 的版本。

上面的版本锁定是一份可复现的技能快照，并不代表每一个 OMERO.server
发行版都能接受该客户端版本。对于其他服务器版本，请查阅其对应的发行
条目，并使用与之经过测试的 OMERO.py 版本。参见
[`references/sources.md`](references/sources.md)。

## 操作契约

1. 先从本地校验或空跑（dry run）开始。在用户选定主机、组
   （group）、对象类型、ID 以及结果数量上限之前，不要建立连接。
2. 只从 frontmatter 中列出的具名 `OMERO_*` 变量读取凭据。绝不搜索
   父目录，也绝不加载 `.env` 文件。
3. 绝不把密码或会话密钥（session key）放进命令参数、源代码、输出的
   JSON、日志、错误追踪（traceback）,或聊天内容中。会话密钥是一种
   持有者凭据（bearer credential）。
4. 默认使用 `secure=True`。OMERO 默认会对登录过程加密，但登录之后的
   数据以及会话 ID，在其他情况下可能以未加密方式传输。`secure=True`
   本身并不能保证证书主机名验证（hostname verification）。
5. 对每一次列表、分页、ROI、形状（shape）、注释、表格行、像素平面,
   以及本地文件扫描，都要设置边界。不要在没有明确批准的情况下，把
   一个针对单个对象的请求变成一次覆盖整个组、乃至跨组的导出。
6. 把所有写操作分别对待：注释/链接创建、渲染默认值保存、图像创建、
   导入、脚本上传、表格写入、所有权或组变更，以及删除操作，都需要
   一个经过审查的、精确的目标对象。
7. 在 `finally` 代码块中或按照文档记载的上下文管理器（context
   manager）模式，关闭 `BlitzGateway`、表格句柄、原始数据存储（raw
   store）、缩略图存储（thumbnail store）、渲染引擎、脚本客户端,
   以及其他有状态的服务。
8. 绝不要仅仅为了「测试」示例代码而连接到一台真实的服务器。

## 选择接口

- **BlitzGateway（`omero-py`）**：主要的 Python 客户端，用于对象遍历、
  像素、注释、ROI、渲染，以及各类服务。
- **OMERO CLI**：会话、导入扫描/导入、OME-TIFF 或 XML 导出、脚本,
  以及管理插件。大多数客户端命令都是远程执行的；导入操作还需要
  通过 `OMERODIR` 使用与之匹配的服务端 Java 库。
- **OMERO.web 的 `api` 和 `webgateway`**：这是官方文档中唯一被称为
  稳定公共 API 的两个 OMERO.web 应用。有文档记载的 JSON API
  支持版本发现（version-discovered），但对象覆盖范围有限；它并不
  能证明每一个 webclient URL 都是一个受支持的 REST 端点。
- **OMERO.server 脚本**：由服务器基础设施执行的、已上传的插件。它们
  与 `scripts/` 目录中内置的本地客户端辅助工具是不同的东西。

## 安装一个可复现的客户端

创建一个 Python 3.12 环境：

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
```

安装与解释器、操作系统、架构以及 wheel 标签相匹配的确切
IcePy 3.6.5 wheel 文件，然后再安装 OMERO.py：

```bash
# 从官方 OMERO 关联的版本矩阵中下载匹配的 3.6.5 wheel 文件。
uv pip install "/absolute/path/to/zeroc_ice-3.6.5-<matching-tags>.whl"
uv pip install "omero-py==5.22.1"
```

不要用 Ice 3.7 来替代：OMERO 5.6 的支持矩阵把 Ice 3.6 标记为推荐
版本，而把 3.7 标记为不受支持。直接安装可能会尝试从源代码编译
IcePy；应优先使用一个经过审查、版本匹配的 wheel 文件。上游的包
采用 GPL-2.0-or-later 许可证；本技能自身的文件采用 MIT 许可证。

只有在使用导入/管理命令时，`OMERODIR` 才必须指向一个已解压、版本
兼容的 OMERO.server 目录。一个普通的远程 BlitzGateway 客户端并不
需要那个服务器目录树。在进行安装或身份验证工作之前，请阅读
[`references/connection.md`](references/connection.md)。

## 凭据与连接

在调用方所在的环境或密钥管理器中设置具名变量。不要把密码放进
`omero` CLI 命令中：

```bash
export OMERO_HOST="omero.example.org"
export OMERO_PORT="4064"
export OMERO_USER="researcher"
export OMERO_SECURE="true"
# 通过环境变量/密钥管理器提供 OMERO_PASSWORD，或改用
# OMERO_SESSION_KEY。不要把这两个值中的任何一个回显出来。
```

一种基于密码认证、且对异常安全的读取模式如下：

```python
import os
from omero.gateway import BlitzGateway

conn = None
try:
    conn = BlitzGateway(
        os.environ["OMERO_USER"],
        os.environ["OMERO_PASSWORD"],
        host=os.environ["OMERO_HOST"],
        port=int(os.environ.get("OMERO_PORT", "4064")),
        secure=True,
    )
    if not conn.connect():
        raise RuntimeError("OMERO connection failed")

    images = conn.getObjects(
        "Image",
        opts={"limit": 25, "offset": 0, "order_by": "obj.id"},
    )
    for image in images:
        print(image.getId())  # Do not print names unless requested.
finally:
    if conn is not None:
        conn.close()
```

关于复用已有会话、CLI 提示模式、证书验证、组上下文，以及清理细节，
请阅读 [`references/connection.md`](references/connection.md)。

## 内置的安全辅助工具

所有辅助工具都使用 `argparse`；即使未安装 OMERO，`--help` 也能
正常工作。远程辅助工具默认是空跑（dry-run）模式，需要 `--execute`
才会真正执行。

```bash
python -B scripts/validate_config.py --help
python -B scripts/inventory.py --help
python -B scripts/export_image_metadata.py --help
python -B scripts/plan_transfer.py --help
```

- `validate_config.py`：只在本地校验具名的端点/认证变量；即使启用
  可选的 DNS 解析，也依然不会联系 OMERO。
- `inventory.py`：有边界的、只读的对象清点，以分页 JSON 形式输出。
- `export_image_metadata.py`：针对明确指定的图像，导出其注释/ROI
  的 JSON,默认会做脱敏处理，并对每个类别设置数量上限；它绝不会
  下载文件字节或像素数据。
- `plan_transfer.py`：仅在本地进行的导入扫描，或按图像逐一生成的
  导出计划；它绝不会调用 OMERO,也绝不会输出任何凭据相关的标志。

在使用它们之前，请阅读
[`references/scripts.md`](references/scripts.md)。

## 能力指南

- 连接、会话、组、TLS：
  [`references/connection.md`](references/connection.md)
- 层级结构、分页、筛查（screening）数据、导入/导出：
  [`references/data_access.md`](references/data_access.md)
- 标签、映射/文件/评论类注释、命名空间：
  [`references/metadata.md`](references/metadata.md)
- 原始平面（raw plane）、图块（tile）、缩略图、渲染：
  [`references/image_processing.md`](references/image_processing.md)
- ROI 模型、形状导出、统计方面的注意事项：
  [`references/rois.md`](references/rois.md)
- 有边界的表格创建、分页、查询、关闭：
  [`references/tables.md`](references/tables.md)
- 本地辅助工具以及 OMERO.server 脚本：
  [`references/scripts.md`](references/scripts.md)
- 权限、文件集（fileset）、网页/公开链接、破坏性操作：
  [`references/advanced.md`](references/advanced.md)

## 开展远程工作之前的最终审查

- 确认服务器版本，以及与之经过测试的 OMERO.py 配对版本。
- 确认目标主机、SSL 路由端口、用户/会话，以及唯一一个组。
- 确认确切的对象 ID/类型，以及硬性数量上限。
- 确认名称、注释值、文件名、ROI 标签、所有者姓名、像素，或原始
  文件是否可以离开服务器。
- 展示拟定的输出路径，除非明确获得允许，否则拒绝覆盖已有文件。
- 对于写操作，要把变更内容和目标 ID,与任何读取计划分开展示。
- 即使在部分失败之后，也要关闭每一个连接/服务。
