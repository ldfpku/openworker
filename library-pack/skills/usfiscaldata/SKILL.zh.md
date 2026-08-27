# 美国财政部 Fiscal Data API

由美国财政部提供的免费开放 REST API，用于获取联邦财政数据。无需 API 密钥或注册即可使用。

**基础 URL**： `https://api.fiscaldata.treasury.gov/services/api/fiscal_service`

可通过数据集搜索浏览[54 个数据集、179 张数据表](https://fiscaldata.treasury.gov/datasets/)。请以各数据集的 API Quick Guide 为准核实端点路径——路径会随时间变化。

## 安装

```bash
uv pip install requests pandas
```

## 快速开始

```python
import requests
import pandas as pd

BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

# Get the current national debt (Debt to the Penny)
resp = requests.get(f"{BASE_URL}/v2/accounting/od/debt_to_penny", params={
    "sort": "-record_date",
    "page[size]": 1
})
data = resp.json()["data"][0]
print(f"Total public debt as of {data['record_date']}: ${float(data['tot_pub_debt_out_amt']):,.0f}")
```

```python
# Get Treasury exchange rates for recent quarters
resp = requests.get(f"{BASE_URL}/v1/accounting/od/rates_of_exchange", params={
    "fields": "country_currency_desc,exchange_rate,record_date",
    "filter": "record_date:gte:2024-01-01",
    "sort": "-record_date",
    "page[size]": 100
})
df = pd.DataFrame(resp.json()["data"])
```

## 身份验证

无需身份验证。该 API 完全开放且免费。

## 核心参数

| 参数 | 示例 | 说明 |
|-----------|---------|-------------|
| `fields=` | `fields=record_date,tot_pub_debt_out_amt` | 选择指定的列 |
| `filter=` | `filter=record_date:gte:2024-01-01` | 过滤记录 |
| `sort=` | `sort=-record_date` | 排序（前缀 `-` 表示降序） |
| `format=` | `format=json` | 输出格式：`json`、`csv`、`xml` |
| `page[size]=` | `page[size]=100` | 每页记录数（默认 100） |
| `page[number]=` | `page[number]=2` | 页码（从 1 开始） |

**过滤运算符**： `lt`、`lte`、`gt`、`gte`、`eq`、`in`

```python
# Multiple filters separated by comma
"filter=country_currency_desc:in:(Canada-Dollar,Mexico-Peso),record_date:gte:2024-01-01"
```

## 主要数据集与端点

### 债务

| 数据集 | 端点 | 更新频率 |
|---------|----------|-----------|
| Debt to the Penny（精确到分的国债余额） | `/v2/accounting/od/debt_to_penny` | 每日 |
| Historical Debt Outstanding（历史未偿债务） | `/v2/accounting/od/debt_outstanding` | 每年 |
| Schedules of Federal Debt（联邦债务明细表） | `/v1/accounting/od/schedules_fed_debt` | 每月 |

### 每日与每月报表

| 数据集 | 端点 | 更新频率 |
|---------|----------|-----------|
| DTS Operating Cash Balance（每日财政报表——运营现金余额） | `/v1/accounting/dts/operating_cash_balance` | 每日 |
| DTS Deposits & Withdrawals（每日财政报表——存取款） | `/v1/accounting/dts/deposits_withdrawals_operating_cash` | 每日 |
| Monthly Treasury Statement, MTS（月度财政部报表） | `/v1/accounting/mts/mts_table_1`（共 18 张表——见 [datasets-fiscal.md](references/datasets-fiscal.md)） | 每月 |

### 利率与汇率

| 数据集 | 端点 | 更新频率 |
|---------|----------|-----------|
| Average Interest Rates on Treasury Securities（国债平均利率） | `/v2/accounting/od/avg_interest_rates` | 每月 |
| Treasury Reporting Rates of Exchange（财政部申报汇率） | `/v1/accounting/od/rates_of_exchange` | 每季度 |
| Interest Expense on Public Debt（公共债务利息支出） | `/v2/accounting/od/interest_expense` | 每月 |

### 证券与拍卖

| 数据集 | 端点 | 更新频率 |
|---------|----------|-----------|
| Treasury Securities Auctions Data（国债拍卖数据） | `/v1/accounting/od/auctions_query` | 按需更新 |
| Treasury Securities Upcoming Auctions（即将进行的国债拍卖） | `/v1/accounting/od/upcoming_auctions` | 按需更新 |
| Treasury Securities Buybacks（国债回购） | `/v1/accounting/od/buybacks_operations` | 按需更新 |

### 储蓄债券

| 数据集 | 端点 | 更新频率 |
|---------|----------|-----------|
| I Bonds Interest Rates（I 系列储蓄债券利率） | `/v1/accounting/od/i_bonds_interest_rates` | 每半年 |
| Savings Bonds Issues, Redemptions & Maturities（储蓄债券发行、赎回与到期情况） | `/v1/accounting/od/savings_bonds_report` | 每月 |

## 响应结构

```json
{
  "data": [...],
  "meta": {
    "count": 100,
    "total-count": 3790,
    "total-pages": 38,
    "labels": {"field_name": "Human Readable Label"},
    "dataTypes": {"field_name": "STRING|NUMBER|DATE|CURRENCY"},
    "dataFormats": {"field_name": "String|10.2|YYYY-MM-DD"}
  },
  "links": {"self": "...", "first": "...", "prev": null, "next": "...", "last": "..."}
}
```

**注意**： 所有返回值均为字符串类型。请按需自行转换（例如 `float()`、`pd.to_datetime()`）。空值会以字符串 `"null"` 的形式出现。

## 常见模式

### 将所有分页数据加载到一个 DataFrame 中

使用 [parameters.md](references/parameters.md) 中提供的、有边界限制的 `fetch_all()` 辅助函数。对于较小的结果集，当 `meta.total-pages` 为 1 时，一次带 `page[size]=10000` 的请求即可满足需求。

```python
# Single-page fetch when total-pages == 1
params = {"sort": "-record_date", "page[size]": 10000}
resp = requests.get(f"{BASE_URL}/v2/accounting/od/debt_outstanding", params=params)
result = resp.json()
if result["meta"]["total-pages"] > 1:
    raise ValueError("Use fetch_all() from parameters.md for multi-page results")
df = pd.DataFrame(result["data"])
```

### 聚合（自动求和）

省略分组字段会触发自动聚合：

```python
# Sum all deposits/withdrawals by record_date and transaction type
resp = requests.get(f"{BASE_URL}/v1/accounting/dts/deposits_withdrawals_operating_cash", params={
    "fields": "record_date,transaction_type,transaction_today_amt"
})
```

## 参考文件

- **[api-basics.md](references/api-basics.md)** —— URL 结构、HTTP 方法、版本管理、数据类型
- **[parameters.md](references/parameters.md)** —— 全部参数及详细示例与边界情况
- **[datasets-debt.md](references/datasets-debt.md)** —— 债务相关数据集：Debt to the Penny、历史债务、联邦债务明细表、TROR
- **[datasets-fiscal.md](references/datasets-fiscal.md)** —— 每日财政报表、月度财政部报表、收入、支出
- **[datasets-interest-rates.md](references/datasets-interest-rates.md)** —— 平均利率、汇率、TIPS/CPI、认定利率
- **[datasets-securities.md](references/datasets-securities.md)** —— 国债拍卖、储蓄债券、SLGS、回购
- **[response-format.md](references/response-format.md)** —— 响应对象、错误处理、分页、响应状态码
- **[examples.md](references/examples.md)** —— 针对常见用例的 Python、R 及 pandas 代码示例
