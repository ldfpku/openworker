#!/usr/bin/env python3
"""备件安全库存与再订货点计算（仅标准库）。

用法：
    python reorder_point.py 出入库.csv --lead-time 10 --safety-days 5
    python reorder_point.py 出入库.csv --lead-time 10 --service-z 1.64
    python reorder_point.py 出入库.csv --lead-time 10 --safety-days 5 --service-z 1.64 --today 2026-06-26 --threshold 2 --holidays 2026-06-19
    python reorder_point.py 出入库.csv --lead-time 10 --safety-days 5 --json

输入 CSV（UTF-8 或带 BOM 的 UTF-8，表头必须有下面五列，顺序不限）：
    日期, 备件编码, 备件名称, 方向, 数量
    - 日期：YYYY-MM-DD 或 YYYY/MM/DD
    - 方向：只认「出库」「入库」（也接受「出」「入」）；其它写法的行会跳过并计数
    - 数量：数字；非数字的行会跳过并计数
    列名的几种常见写法也认：日期 / 出入库日期；备件编码 / 编码 / 物料编码；
    备件名称 / 名称 / 物料名称；方向 / 类型 / 出入库类型；数量 / 数量(件)

参数：
    --lead-time N     采购提前期，按工作日计（必填）。供应商按日历天报的，按贵司作息折算后再填。
    --safety-days N   方法 A：安全库存 = 日均消耗 × 安全天数
    --service-z Z     方法 B：安全库存 = Z × 日消耗标准差 × sqrt(提前期)
                      （服务水平 90% 取 1.28，95% 取 1.64，99% 取 2.33）
                      两个方法至少给一个；都给则两种各出一列
    --today DATE      统计截止日；缺省取 CSV 里最晚的日期
    --recent N        最近期间长度（工作日），缺省 10
    --baseline N      此前期间长度（工作日），缺省 30
    --threshold X     消耗倍数阈值，缺省 2.0；倍数达到阈值的在备注里标「消耗异常」
    --holidays LIST   逗号分隔的节假日（YYYY-MM-DD），从工作日里剔除
    --json            输出 JSON 而不是 Markdown

算法：
    工作日 = 周一到周五，剔除 --holidays；
    最近期间 = 从截止日往前数 N 个工作日（含截止日；截止日不是工作日就从它之前最近的工作日起）；
    此前期间 = 紧接着再往前数 M 个工作日；
    日均消耗 = 两段期间内出库合计 ÷ 两段期间内有流水覆盖的工作日数（出库为 0 的日子也算）；
    倍数 = 最近期间出库 ÷ (此前期间出库 ÷ (此前覆盖工作日数 ÷ N))；此前出库为 0 时不算倍数；
    再订货点 = 日均消耗 × 提前期 + 安全库存；安全库存和再订货点向上取整。
    流水覆盖不足 N + M 个工作日时，按实际覆盖的工作日算，并在输出顶部提示。
    期间之外的行（早于此前期间开始、晚于截止日）不参与计算，只计数。

输出：Markdown 表格，每种备件一行：日均消耗、此前期间出库、最近期间出库、倍数、
      建议安全库存、再订货点、备注；表格上方列出期间、覆盖天数、读入与跳过的行数。
不访问网络，不依赖第三方库。
"""

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import datetime, timedelta

COLUMN_ALIASES = {
    "date": ("日期", "出入库日期", "发生日期"),
    "code": ("备件编码", "编码", "物料编码", "备件代码"),
    "name": ("备件名称", "名称", "物料名称"),
    "direction": ("方向", "类型", "出入库类型", "出入库"),
    "qty": ("数量", "数量(件)", "数量（件）"),
}
OUT_WORDS = ("出库", "出", "领用", "OUT", "out")
IN_WORDS = ("入库", "入", "IN", "in")


def parse_date(text):
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def map_columns(header):
    cleaned = [h.strip().lstrip("﻿") for h in header]
    mapping = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in cleaned:
                mapping[key] = cleaned.index(alias)
                break
        if key not in mapping:
            raise SystemExit(
                "找不到列「%s」（可接受的写法：%s）；实际表头：%s"
                % (aliases[0], " / ".join(aliases), "、".join(cleaned))
            )
    return mapping


def read_rows(path):
    rows = []
    skipped = {"方向不识别": 0, "日期不识别": 0, "数量不识别": 0, "编码为空": 0}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise SystemExit("CSV 是空的")
        col = map_columns(header)
        for raw in reader:
            if not raw or all(not c.strip() for c in raw):
                continue
            d = parse_date(raw[col["date"]]) if len(raw) > col["date"] else None
            if d is None:
                skipped["日期不识别"] += 1
                continue
            code = raw[col["code"]].strip() if len(raw) > col["code"] else ""
            if not code:
                skipped["编码为空"] += 1
                continue
            direction = raw[col["direction"]].strip() if len(raw) > col["direction"] else ""
            if direction in OUT_WORDS:
                sign = "out"
            elif direction in IN_WORDS:
                sign = "in"
            else:
                skipped["方向不识别"] += 1
                continue
            try:
                qty = float(raw[col["qty"]].strip().replace(",", ""))
            except (ValueError, IndexError):
                skipped["数量不识别"] += 1
                continue
            name = raw[col["name"]].strip() if len(raw) > col["name"] else ""
            rows.append({"date": d, "code": code, "name": name, "dir": sign, "qty": qty})
    return rows, skipped


def workdays_back(end, count, holidays):
    """从 end 往前（含 end）取 count 个工作日，返回按日期升序的列表。"""
    days, cur = [], end
    while len(days) < count:
        if cur.weekday() < 5 and cur not in holidays:
            days.append(cur)
        cur -= timedelta(days=1)
    days.reverse()
    return days


def ceil_int(x):
    return int(math.ceil(x - 1e-9)) if x > 0 else 0


def fmt(x, nd=2):
    return ("%." + str(nd) + "f") % x


def main(argv=None):
    ap = argparse.ArgumentParser(description="备件安全库存与再订货点计算")
    ap.add_argument("csv_path", help="出入库流水 CSV")
    ap.add_argument("--lead-time", type=float, required=True, help="采购提前期（工作日）")
    ap.add_argument("--safety-days", type=float, help="方法 A：安全天数")
    ap.add_argument("--service-z", type=float, help="方法 B：服务水平系数 Z")
    ap.add_argument("--today", help="统计截止日 YYYY-MM-DD，缺省取流水里最晚的日期")
    ap.add_argument("--recent", type=int, default=10, help="最近期间工作日数，缺省 10")
    ap.add_argument("--baseline", type=int, default=30, help="此前期间工作日数，缺省 30")
    ap.add_argument("--threshold", type=float, default=2.0, help="消耗倍数阈值，缺省 2.0")
    ap.add_argument("--holidays", default="", help="逗号分隔的节假日 YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    if args.safety_days is None and args.service_z is None:
        ap.error("--safety-days 和 --service-z 至少给一个")
    if args.lead_time <= 0 or args.recent <= 0 or args.baseline <= 0:
        ap.error("--lead-time / --recent / --baseline 都必须大于 0")

    holidays = set()
    for h in (s.strip() for s in args.holidays.split(",")):
        if not h:
            continue
        d = parse_date(h)
        if d is None:
            ap.error("节假日格式不对：%s" % h)
        holidays.add(d)

    rows, skipped = read_rows(args.csv_path)
    if not rows:
        raise SystemExit("没有可用的流水行（跳过情况：%s）" % skipped)

    today = parse_date(args.today) if args.today else max(r["date"] for r in rows)
    if today is None:
        ap.error("--today 格式不对")

    recent_days = workdays_back(today, args.recent, holidays)
    baseline_days = workdays_back(recent_days[0] - timedelta(days=1), args.baseline, holidays)
    all_days = baseline_days + recent_days
    earliest = min(r["date"] for r in rows)
    covered_days = [d for d in all_days if d >= earliest]
    covered_baseline = [d for d in baseline_days if d >= earliest]
    recent_set, baseline_set = set(recent_days), set(baseline_days)

    parts = {}
    outside = 0
    for r in rows:
        d = r["date"]
        if d > today or d < all_days[0]:
            outside += 1
            continue
        p = parts.setdefault(r["code"], {"name": "", "daily": {}, "in_recent": 0.0, "in_total": 0.0})
        if r["name"] and not p["name"]:
            p["name"] = r["name"]
        if r["dir"] == "out":
            p["daily"][d] = p["daily"].get(d, 0.0) + r["qty"]
        else:
            p["in_total"] += r["qty"]
            if d in recent_set:
                p["in_recent"] += r["qty"]

    n_cov = len(covered_days)
    results = []
    for code, p in parts.items():
        recent_out = float(sum(q for d, q in p["daily"].items() if d in recent_set))
        base_out = float(sum(q for d, q in p["daily"].items() if d in baseline_set))
        total_out = recent_out + base_out
        avg = total_out / n_cov if n_cov else 0.0
        series = [p["daily"].get(d, 0.0) for d in covered_days]
        sd = statistics.pstdev(series) if len(series) > 1 else 0.0
        nonzero_days = sum(1 for v in series if v > 0)
        if base_out > 0 and covered_baseline:
            base_per_recent = base_out / (len(covered_baseline) / args.recent)
            ratio = recent_out / base_per_recent
        else:
            ratio = None

        notes = []
        if ratio is not None and ratio >= args.threshold:
            notes.append("消耗异常（达到 %s 倍阈值）" % fmt(args.threshold, 1))
            if p["in_recent"] == 0:
                notes.append("最近期间无入库")
        if base_out == 0 and recent_out > 0:
            notes.append("此前无消耗，最近新增")
        if recent_out == 0 and base_out > 0:
            notes.append("最近期间无出库")
        if total_out == 0:
            notes.append("统计期内无出库")
        if args.service_z is not None and nonzero_days < 5:
            notes.append("出库天数少于 5 天，方法 B 不可靠")

        row = {
            "备件编码": code,
            "备件名称": p["name"],
            "日均消耗": round(avg, 3),
            "此前期间出库": base_out,
            "最近期间出库": recent_out,
            "倍数": None if ratio is None else round(ratio, 2),
            "出库天数": nonzero_days,
        }
        if args.safety_days is not None:
            ss_a = avg * args.safety_days
            row["安全库存A"] = ceil_int(ss_a)
            row["再订货点A"] = ceil_int(avg * args.lead_time + ss_a)
        if args.service_z is not None:
            ss_b = args.service_z * sd * math.sqrt(args.lead_time)
            row["安全库存B"] = ceil_int(ss_b)
            row["再订货点B"] = ceil_int(avg * args.lead_time + ss_b)
        row["备注"] = "；".join(notes)
        results.append(row)

    results.sort(key=lambda r: (-(r["倍数"] if r["倍数"] is not None else -1), r["备件编码"]))

    meta = {
        "截止日": today.isoformat(),
        "最近期间": "%s 至 %s（%d 个工作日）" % (recent_days[0], recent_days[-1], len(recent_days)),
        "此前期间": "%s 至 %s（%d 个工作日）" % (baseline_days[0], baseline_days[-1], len(baseline_days)),
        "流水覆盖工作日": n_cov,
        "读入行数": len(rows),
        "期间外行数": outside,
        "跳过行数": skipped,
        "提前期(工作日)": args.lead_time,
        "安全天数": args.safety_days,
        "服务水平系数Z": args.service_z,
        "倍数阈值": args.threshold,
    }
    if n_cov < len(all_days):
        meta["提示"] = "流水只覆盖 %d 个工作日（要求 %d 个），日均消耗和倍数按实际覆盖天数算" % (n_cov, len(all_days))

    if args.json:
        print(json.dumps({"meta": meta, "rows": results}, ensure_ascii=False, indent=2))
        return 0

    print("# 备件安全库存与再订货点建议")
    print()
    for k, v in meta.items():
        if isinstance(v, dict):
            v = "、".join("%s %d" % kv for kv in v.items())
        elif v is None:
            v = "未用"
        print("- %s：%s" % (k, v))
    print()
    cols = ["备件编码", "备件名称", "日均消耗", "此前期间出库", "最近期间出库", "倍数", "出库天数"]
    if args.safety_days is not None:
        cols += ["安全库存A", "再订货点A"]
    if args.service_z is not None:
        cols += ["安全库存B", "再订货点B"]
    cols.append("备注")
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join(" --- " for _ in cols) + "|")
    for r in results:
        cells = []
        for c in cols:
            v = r.get(c)
            if v is None:
                cells.append("—")
            elif isinstance(v, float) and c in ("此前期间出库", "最近期间出库"):
                cells.append(str(int(v)) if v == int(v) else fmt(v, 2))
            elif isinstance(v, float):
                cells.append(fmt(v, 2))
            else:
                cells.append(str(v))
        print("| " + " | ".join(cells) + " |")
    print()
    print("说明：日均消耗按两段期间内有流水覆盖的工作日平均（含出库为 0 的日子）；"
          "倍数 = 最近期间出库 ÷ 此前期间折算到同样天数的出库；"
          "再订货点 = 日均消耗 × 提前期 + 安全库存，向上取整。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
