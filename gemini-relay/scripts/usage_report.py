"""gemini-relay 用量报表 —— 按人（邮箱）汇总 Cloudflare D1 里的 usage 流水表。

背景：gemini-relay v2 的 Worker 每次转发请求都会往 D1 数据库（database_name
gemini_relay_usage，binding USAGE_DB）异步写一条 usage 流水（schema 见
worker/migrations/0001_init.sql）。本脚本通过 Cloudflare 的 D1 HTTP Query API
在本机跑聚合 SQL，不需要登录控制台，也不需要装 wrangler。

依赖：仅 httpx（仓库根目录 .venv 已经装好，见 .venv/pyvenv.cfg）。用仓库自带的
解释器运行：

    C:\\Users\\liude\\github\\openworker\\.venv\\Scripts\\python.exe ^
        gemini-relay\\scripts\\usage_report.py [参数]

环境变量（三个都必须设置，缺一个就会在发起任何网络请求之前报错退出）：

    CF_API_TOKEN        Cloudflare API Token，只需要 Account 级别的 D1:Read 权限。
                         创建步骤：登录 dash.cloudflare.com → 右上角头像 →
                         My Profile → API Tokens → Create Token → 用
                         "Custom token"，Permissions 选 Account / D1 / Read，
                         Account Resources 限定到目标账号即可，不需要 Zone 权限。
    CF_ACCOUNT_ID        Cloudflare 账号 ID（dash 首页右侧栏或任意 zone 概览页
                         右下角能看到，一串 32 位十六进制）。
    CF_D1_DATABASE_ID    目标 D1 数据库的 UUID（`npx wrangler d1 info
                         gemini_relay_usage` 能查到，也能在控制台 Workers &
                         Pages → D1 → gemini_relay_usage 详情页看到）。

命令行参数：

    --days N          统计最近 N 天（默认 30），与 --month 互斥。
    --month YYYY-MM    统计某个自然月（如 2026-08），与 --days 互斥。
    --by-model         额外输出一张「邮箱 x 模型」的分解表。
    --csv PATH         把控制台打印的表格（们）追加写成一份 CSV 文件。

用法示例：

    # 最近 30 天（默认），每人一行
    python usage_report.py

    # 最近 7 天
    python usage_report.py --days 7

    # 2026 年 8 月整月，附带按模型分解
    python usage_report.py --month 2026-08 --by-model

    # 同上，同时导出 CSV
    python usage_report.py --month 2026-08 --by-model --csv usage-2026-08.csv

也可以完全不用这个脚本：去 Cloudflare 控制台 Workers & Pages → D1 →
gemini_relay_usage → Console，直接跑 SQL。下面三条是最常用的现成语句
（口径和本脚本一致，字段名对应 worker/migrations/0001_init.sql 里的 usage 表）：

    -- 1) 本月每人汇总
    SELECT
      email,
      COUNT(*) AS requests,
      SUM(prompt_tokens) AS prompt_tokens,
      SUM(output_tokens) AS output_tokens,
      SUM(total_tokens) AS total_tokens,
      SUM(thoughts_tokens) AS thoughts_tokens,
      SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS failed
    FROM usage
    WHERE substr(ts, 1, 7) = strftime('%Y-%m', 'now')
    GROUP BY email
    ORDER BY total_tokens DESC;

    -- 2) 每日趋势（最近 30 天）
    SELECT
      substr(ts, 1, 10) AS day,
      COUNT(*) AS requests,
      SUM(total_tokens) AS total_tokens
    FROM usage
    WHERE ts >= datetime('now', '-30 days')
    GROUP BY day
    ORDER BY day;

    -- 3) 按模型分解（本月，每人每模型一行）
    SELECT
      email,
      model,
      COUNT(*) AS requests,
      SUM(total_tokens) AS total_tokens
    FROM usage
    WHERE substr(ts, 1, 7) = strftime('%Y-%m', 'now')
    GROUP BY email, model
    ORDER BY email ASC, total_tokens DESC;

口径说明：本报表统计的是「经中转的 token 数」，供团队内部按人归因用；权威计费
口径仍以 Google 侧（AI Studio / Cloud 控制台按项目或按 key 查看）为准，两者不
保证逐位对齐（比如失败请求、部分工具调用场景 Google 侧计费口径可能不同）。

退出码：0 = 成功；1 = 参数错误、环境变量缺失、网络/API 错误等（均打印中文
提示到 stderr，不抛出未处理的 traceback）。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

D1_QUERY_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"

REQUIRED_ENV_VARS = ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_D1_DATABASE_ID")

# 与 worker/migrations/0001_init.sql 的列顺序保持一致，方便对照 schema 核对。
SUMMARY_SQL = """
SELECT
  email,
  COUNT(*) AS requests,
  COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
  COALESCE(SUM(output_tokens), 0) AS output_tokens,
  COALESCE(SUM(total_tokens), 0) AS total_tokens,
  COALESCE(SUM(thoughts_tokens), 0) AS thoughts_tokens,
  SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS failed
FROM usage
WHERE ts >= ? AND ts < ?
GROUP BY email
ORDER BY total_tokens DESC
""".strip()

BY_MODEL_SQL = """
SELECT
  email,
  model,
  COUNT(*) AS requests,
  COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
  COALESCE(SUM(output_tokens), 0) AS output_tokens,
  COALESCE(SUM(total_tokens), 0) AS total_tokens,
  COALESCE(SUM(thoughts_tokens), 0) AS thoughts_tokens,
  SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS failed
FROM usage
WHERE ts >= ? AND ts < ?
GROUP BY email, model
ORDER BY email ASC, total_tokens DESC
""".strip()

SUMMARY_HEADERS = [
    "email",
    "requests",
    "prompt_tokens",
    "output_tokens",
    "total_tokens",
    "thoughts_tokens",
    "failed",
]
BY_MODEL_HEADERS = [
    "email",
    "model",
    "requests",
    "prompt_tokens",
    "output_tokens",
    "total_tokens",
    "thoughts_tokens",
    "failed",
]

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class ReportError(Exception):
    """携带一条给操作员看的中文提示；main() 捕获后打印到 stderr 并返回退出码 1。

    不用于网络/未预期异常——那些由 main() 里更外层的 try/except 统一兜底，
    确保任何情况下都不会把原始 traceback 甩给用户。
    """


def check_env() -> dict[str, str]:
    """校验三个必需环境变量都存在；缺失时列出全部缺失项（不是只报第一个）。"""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise ReportError(
            "缺少环境变量："
            + "、".join(missing)
            + "。三个都要设置：CF_API_TOKEN（Account/D1/Read 权限的 API Token）、"
            "CF_ACCOUNT_ID、CF_D1_DATABASE_ID——获取方式见本文件顶部文档字符串。"
        )
    return {name: os.environ[name] for name in REQUIRED_ENV_VARS}


def resolve_window(days: int | None, month: str | None) -> tuple[str, str, str]:
    """把 --days/--month 转成 [from_iso, to_iso) 半开区间，以及一句人类可读的窗口描述。

    只接受已经过 argparse 校验的整数/字符串，绝不对原始命令行文本做字符串拼接
    进 SQL——时间边界最终以 SQL 参数（? 占位符 + params 数组）的形式传给 D1，
    不会出现在 SQL 文本里。
    """
    if month is not None:
        m = _MONTH_RE.match(month)
        if not m:
            raise ReportError(f"--month 格式不对：{month!r}，需要 YYYY-MM，例如 2026-08。")
        year, mon = int(m.group(1)), int(m.group(2))
        start = datetime(year, mon, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if mon == 12 else datetime(year, mon + 1, 1, tzinfo=timezone.utc)
        label = f"{year:04d}-{mon:02d}"
    else:
        n = days if days is not None else 30
        if n <= 0:
            raise ReportError(f"--days 必须是正整数，收到 {n}。")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=n)
        label = f"最近 {n} 天"

    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    return start.strftime(fmt), end.strftime(fmt), label


def run_query(env: dict[str, str], sql: str, params: list[Any]) -> list[dict[str, Any]]:
    """POST 一条参数化 SQL 给 D1 Query API，返回 results 数组（可能为空列表）。

    所有网络/HTTP/JSON 层面的失败都在这里转成 ReportError（中文提示），交给
    main() 统一捕获打印，绝不让 httpx 的原始异常或 traceback 冒到用户面前。
    """
    import httpx  # 延迟导入：--help 等不碰网络的路径不必强制要求 httpx 已安装。

    url = D1_QUERY_URL.format(account_id=env["CF_ACCOUNT_ID"], database_id=env["CF_D1_DATABASE_ID"])
    headers = {
        "Authorization": f"Bearer {env['CF_API_TOKEN']}",
        "Content-Type": "application/json",
    }
    body = {"sql": sql, "params": params}

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=30.0)
    except httpx.RequestError as exc:
        raise ReportError(
            f"请求 Cloudflare API 失败：{type(exc).__name__}: {exc}\n"
            "请检查：网络是否连通 api.cloudflare.com、CF_ACCOUNT_ID / CF_D1_DATABASE_ID "
            "是否填对、本机是否有失效的代理环境变量（HTTP_PROXY/HTTPS_PROXY/ALL_PROXY）。"
        ) from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise ReportError(
            f"Cloudflare API 返回了无法解析的响应（HTTP {resp.status_code}），"
            "可能是网络中间设备拦截了请求，或者 URL/账号 ID 配置有误。"
        ) from exc

    if not data.get("success"):
        errors = data.get("errors") or []
        if errors:
            detail = "; ".join(f"[{e.get('code', '?')}] {e.get('message', e)}" for e in errors)
        else:
            detail = f"HTTP {resp.status_code}，无详细错误信息"
        raise ReportError(
            f"Cloudflare API 返回失败：{detail}\n"
            "常见原因：CF_API_TOKEN 权限不够（需要 Account/D1/Read）、CF_D1_DATABASE_ID "
            "写错、或者该数据库还没跑过迁移（worker/migrations/0001_init.sql）。"
        )

    result_list = data.get("result") or []
    if not result_list:
        return []
    return result_list[0].get("results") or []


def format_table(headers: list[str], rows: list[list[Any]]) -> str:
    """纯文本对齐表格：第一列左对齐（email/model 这种文本），其余右对齐（数字列）。"""
    str_rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            parts.append(cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i]))
        return "  ".join(parts)

    lines = [fmt_row(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt_row(row) for row in str_rows)
    return "\n".join(lines)


def rows_from_results(results: list[dict[str, Any]], headers: list[str]) -> list[list[Any]]:
    return [[r.get(h, "") for h in headers] for r in results]


def write_csv_sections(path: str, sections: list[tuple[str, list[str], list[list[Any]]]]) -> None:
    """把一个或多个（标题, 表头, 数据行）三元组顺序写进同一个 CSV 文件，段间空一行。"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        for i, (title, headers, rows) in enumerate(sections):
            if i > 0:
                writer.writerow([])
            writer.writerow([title])
            writer.writerow(headers)
            writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="usage_report.py",
        description="按邮箱汇总 gemini-relay 的 D1 用量流水（usage 表）。",
    )
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=None, help="统计最近 N 天（默认 30）")
    window.add_argument("--month", type=str, default=None, metavar="YYYY-MM", help="统计某个自然月，如 2026-08")
    parser.add_argument("--by-model", action="store_true", help="额外输出「邮箱 x 模型」分解表")
    parser.add_argument("--csv", type=str, default=None, metavar="PATH", help="把表格同时写成 CSV 文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        env = check_env()
        from_iso, to_iso, window_label = resolve_window(args.days, args.month)

        print(f"gemini-relay 用量报表 —— 窗口：{window_label}（{from_iso} 至 {to_iso}，UTC，含头不含尾）", flush=True)
        print(flush=True)

        summary_results = run_query(env, SUMMARY_SQL, [from_iso, to_iso])
        summary_rows = rows_from_results(summary_results, SUMMARY_HEADERS)

        print("每人汇总（按 total_tokens 降序）：")
        if summary_rows:
            print(format_table(SUMMARY_HEADERS, summary_rows))
        else:
            print("（这段时间没有任何记录）")
        print()

        csv_sections: list[tuple[str, list[str], list[list[Any]]]] = [
            ("summary", SUMMARY_HEADERS, summary_rows)
        ]

        if args.by_model:
            by_model_results = run_query(env, BY_MODEL_SQL, [from_iso, to_iso])
            by_model_rows = rows_from_results(by_model_results, BY_MODEL_HEADERS)

            print("按模型分解（每人每模型一行，按 total_tokens 降序）：")
            if by_model_rows:
                print(format_table(BY_MODEL_HEADERS, by_model_rows))
            else:
                print("（这段时间没有任何记录）")
            print()

            csv_sections.append(("by_model", BY_MODEL_HEADERS, by_model_rows))

        if args.csv:
            try:
                write_csv_sections(args.csv, csv_sections)
            except OSError as exc:
                raise ReportError(f"写 CSV 文件失败：{args.csv} —— {exc}") from exc
            print(f"已写入 CSV：{args.csv}")

        return 0

    except ReportError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - 最后一道防线：绝不把原始 traceback 甩给用户
        print(f"未预期的错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
