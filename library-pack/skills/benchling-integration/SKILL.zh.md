# Benchling 集成

## 概述

Benchling 是一个面向生命科学研发的云平台。可以通过 Python SDK 和 REST API，
以编程方式访问注册实体（DNA、RNA、蛋白质）、库存、电子实验记录本，以及工作流。

**版本说明**： 示例针对的是 **benchling-sdk 1.25.0**（PyPI 上最新的稳定版本）。
文档：[benchling.com/sdk-docs](https://benchling.com/sdk-docs/)。
平台指南：[docs.benchling.com](https://docs.benchling.com/)。

## 何时使用本技能

在以下情况下应使用本技能：
- 使用 Benchling 的 Python SDK 或 REST API
- 管理生物序列（DNA、RNA、蛋白质）及注册实体
- 自动化库存操作（样本、容器、存放位置、转移）
- 创建或查询电子实验记录本条目
- 构建工作流自动化或 Benchling Apps
- 在 Benchling 与外部系统之间同步数据
- 查询 Benchling 数据仓库以进行分析
- 使用 AWS EventBridge 搭建事件驱动的集成

## 核心能力

七大能力领域，每个都附有代码示例，位于
[references/core_capabilities.md](references/core_capabilities.md)：

1. **身份验证与初始设置**——API 密钥和 OAuth app 身份验证；参见
   [references/authentication.md](references/authentication.md)。
2. **注册表与实体管理**——DNA 和氨基酸序列、自定义实体、模式（schema），
   以及注册流程。
3. **库存管理**——容器、盒子、板、存放位置，以及转移操作。
4. **实验记录本与文档**——条目、日常记录，以及结构化表格。
5. **工作流与自动化**——任务、流程图，以及检测运行（assay run）。
6. **事件与集成**——EventBridge 订阅；参见
   [references/eventbridge.md](references/eventbridge.md)。
7. **数据仓库与分析**——对数据仓库的 SQL 访问。

端点及 SDK 的详细信息位于
[references/api_endpoints.md](references/api_endpoints.md) 和
[references/sdk_reference.md](references/sdk_reference.md)。

## 最佳实践

### 错误处理

SDK 会自动重试失败的请求：
```python
# Automatic retry for 429, 502, 503, 504 status codes
# Up to 5 retries with exponential backoff
# Customize retry behavior if needed
from benchling_sdk.retry import RetryStrategy

benchling = Benchling(
    url=tenant_url,
    auth_method=ApiKeyAuth(api_key),
    retry_strategy=RetryStrategy(max_retries=3),
)
```

### 分页效率

使用生成器（generator）以实现内存高效的分页：
```python
# Generator-based iteration
for page in benchling.dna_sequences.list():
    for sequence in page:
        process(sequence)

# Check estimated count without loading all pages
total = benchling.dna_sequences.list().estimated_count()
```

### 模式字段辅助工具

对自定义模式字段使用 `fields()` 辅助函数：
```python
# Convert dict to Fields object
custom_fields = benchling.models.fields({
    "concentration": "100 ng/μL",
    "date_prepared": "2025-10-20",
    "notes": "High quality prep"
})
```

### 向前兼容性

SDK 能够优雅地处理未知的枚举值和类型：
- 未知的枚举值会被保留
- 无法识别的多态类型会返回 `UnknownType`
- 使得代码能够兼容更新的 API 版本

### 安全注意事项

- 绝不将 API 密钥或 OAuth 密钥提交到版本控制中
- 只读取指定的环境变量（`BENCHLING_TENANT_URL`、`BENCHLING_API_KEY` 等）
- 网络调用只应发往你的租户（tenant）URL
- 若密钥泄露则应轮换；在多用户的生产环境应用中使用 OAuth
- 在开发者控制台中为应用授予所需的最小权限

## 资源

### references/

供深入了解的详细参考文档：

- **authentication.md** —— 全面的身份验证指南，包括 OIDC、安全最佳实践，
  以及凭证管理
- **sdk_reference.md** —— 详细的 Python SDK 参考文档，含高级模式、
  示例，以及所有实体类型
- **api_endpoints.md** —— 用于不依赖 SDK 直接发起 HTTP 调用的
  REST API 端点参考
- **eventbridge.md** —— EventBridge 设置、事件负载模式（schema）、
  规则示例、Lambda 处理函数、校验，以及恢复机制

根据具体的集成需求按需加载这些参考资料。

## 常见用例

**1. 批量导入实体**：
```python
# Import multiple sequences from FASTA file
from Bio import SeqIO

for record in SeqIO.parse("sequences.fasta", "fasta"):
    benchling.dna_sequences.create(
        DnaSequenceCreate(
            name=record.id,
            bases=str(record.seq),
            is_circular=False,
            folder_id="fld_abc123"
        )
    )
```

**2. 库存审计**：
```python
# List all containers in a specific location
containers = benchling.containers.list(
    parent_storage_id="box_abc123"
)

for page in containers:
    for container in page:
        print(f"{container.name}: {container.barcode}")
```

**3. 工作流自动化**：
```python
# Update all pending tasks for a workflow
tasks = benchling.workflow_tasks.list(
    workflow_id="wf_abc123",
    status="pending"
)

for page in tasks:
    for task in page:
        # Perform automated checks
        if auto_validate(task):
            benchling.workflow_tasks.update(
                task_id=task.id,
                workflow_task=WorkflowTaskUpdate(
                    status_id="status_complete"
                )
            )
```

**4. 数据导出**：
```python
# Export all sequences with specific properties
sequences = benchling.dna_sequences.list()
export_data = []

for page in sequences:
    for seq in page:
        if seq.schema_id == "target_schema_id":
            export_data.append({
                "id": seq.id,
                "name": seq.name,
                "bases": seq.bases,
                "length": len(seq.bases)
            })

# Save to CSV or database
import csv
with open("sequences.csv", "w") as f:
    writer = csv.DictWriter(f, fieldnames=export_data[0].keys())
    writer.writeheader()
    writer.writerows(export_data)
```

## 补充资源

- **官方文档**： https://docs.benchling.com
- **Python SDK 参考**： https://benchling.com/sdk-docs/
- **API 参考**： https://benchling.com/api/reference
- **技术支持**： [email protected]
