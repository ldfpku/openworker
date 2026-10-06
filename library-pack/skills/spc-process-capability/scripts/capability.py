#!/usr/bin/env python3
"""capability.py —— 过程能力与控制图计算（只用标准库，不访问网络）。

用法
----
    python capability.py 数据.csv --usl 60.02 --lsl 59.98
    python capability.py 数据.csv --usl 60.02 --lsl 59.98 --target 60.00
    python capability.py 数据.csv --usl 60.02 --lsl 59.98 --value-col 测量值 --group-col 批次
    python capability.py 数据.csv --usl 60.02 --lsl 59.98 --subgroup-size 5
    python capability.py 数据.csv --usl 60.02 --json

输入 CSV
--------
- 第一行是表头，UTF-8（带不带 BOM 都行）。
- 一列测量值：用 --value-col 指定列名或列序号（从 0 起）；不指定时自动取第一列
  「所有非空单元格都能转成数字」的列。
- 可选分组列：用 --group-col 指定（如 批次 / 子组 / 日期），相同值的相邻行算一个子组。
  没有分组列时可用 --subgroup-size N 把相邻 N 个值并成一个子组。
  两者都不给，就按单值-移动极差（I-MR）处理。
- 子组大小必须相同且在 2–10 之间；不满足就退回 I-MR 并在结果里提示。
- 测量值为空或不是数字的行会跳过，并报告跳过的行号（行号 = CSV 行号，表头是第 1 行）。

输出
----
Markdown（默认）或 JSON（--json）：
- n、均值、中位数、最小值、最大值
- 总体标准差（样本标准差，分母 n-1）
- 组内标准差：I-MR 用 MR̄ / 1.128；Xbar-R 用 R̄ / d2(n)
- Cp、Cpk（用组内标准差）；Pp、Ppk（用总体标准差）
- 给了 --target 时：均值相对目标的偏移、Cpm
- 超规格点数（高于 USL、低于 LSL）及其行号
- 控制限：I 图 / MR 图，或 Xbar 图 / R 图
- 判异：超控制限、连续 7 点在中心线同一侧、连续 7 点递增或递减

规格限可以只给一边：只有 USL 或只有 LSL 时不算 Cp / Pp，Cpk / Ppk 取单边值。
"""

import argparse
import csv
import json
import math
import statistics
import sys

# 控制图常数（子组大小 n = 2..10）：d2、A2、D3、D4
CONSTANTS = {
    2: (1.128, 1.880, 0.000, 3.267),
    3: (1.693, 1.023, 0.000, 2.574),
    4: (2.059, 0.729, 0.000, 2.282),
    5: (2.326, 0.577, 0.000, 2.114),
    6: (2.534, 0.483, 0.000, 2.004),
    7: (2.704, 0.419, 0.076, 1.924),
    8: (2.847, 0.373, 0.136, 1.864),
    9: (2.970, 0.337, 0.184, 1.816),
    10: (3.078, 0.308, 0.223, 1.777),
}
RUN_LENGTH = 7  # 连续同侧 / 连续趋势 的判异长度


def to_float(text):
    try:
        return float(str(text).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        sys.exit("CSV 至少要有表头和一行数据。")
    header = [h.strip() for h in rows[0]]
    return header, rows[1:]


VALUE_COL_NAMES = ("测量值", "实测值", "实测", "测量", "读数", "数值", "值", "value", "measurement", "measured")
INDEX_COL_NAMES = ("序号", "编号", "行号", "no", "no.", "id", "index")


def resolve_col(header, spec, rows):
    """把列名或列序号解析成列下标。

    spec 为空时自动选测量值列：先按常见列名找；再找「绝大多数非空单元格是数字」的列，
    跳过序号类列（列名像「序号」或内容是 1,2,3… 的连续整数）。
    """
    if spec is not None:
        if spec in header:
            return header.index(spec)
        if spec.isdigit() and int(spec) < len(header):
            return int(spec)
        sys.exit(f"找不到列「{spec}」，表头是：{header}")
    for idx, name in enumerate(header):
        if name.lower() in VALUE_COL_NAMES:
            return idx
    candidates = []
    for idx, name in enumerate(header):
        cells = [r[idx] for r in rows if idx < len(r) and r[idx].strip()]
        nums = [to_float(c) for c in cells]
        good = [v for v in nums if v is not None]
        if not good or len(good) < 0.8 * len(cells):
            continue
        looks_index = name.lower() in INDEX_COL_NAMES or (
            len(good) == len(cells) and all(v == i for i, v in enumerate(good, start=int(good[0])))
            and good[0] in (0.0, 1.0))
        if not looks_index:
            return idx
        candidates.append(idx)
    if candidates:
        return candidates[0]
    sys.exit("没有找到像测量值的列，请用 --value-col 指定测量值列。")


def load_values(header, rows, value_col, group_col):
    values, groups, row_nums, skipped = [], [], [], []
    for i, r in enumerate(rows, start=2):  # 表头是第 1 行
        cell = r[value_col] if value_col < len(r) else ""
        v = to_float(cell)
        if v is None:
            skipped.append(i)
            continue
        values.append(v)
        row_nums.append(i)
        groups.append(r[group_col].strip() if group_col is not None and group_col < len(r) else None)
    return values, groups, row_nums, skipped


def make_subgroups(values, groups, row_nums, group_col, subgroup_size):
    """返回 (子组列表 [(标签, [值], [行号])], 退回 I-MR 的原因或 None)。"""
    if group_col is not None:
        subs, cur_label, cur_vals, cur_rows = [], object(), [], []
        for v, g, rn in zip(values, groups, row_nums):
            if g != cur_label:
                if cur_vals:
                    subs.append((cur_label, cur_vals, cur_rows))
                cur_label, cur_vals, cur_rows = g, [], []
            cur_vals.append(v)
            cur_rows.append(rn)
        if cur_vals:
            subs.append((cur_label, cur_vals, cur_rows))
    elif subgroup_size:
        subs, note = [], None
        for k in range(0, len(values), subgroup_size):
            chunk = values[k:k + subgroup_size]
            if len(chunk) < subgroup_size:
                note = f"末尾 {len(chunk)} 个值不足一个子组（行 {', '.join(map(str, row_nums[k:]))}），控制图未计入；能力指数仍用全部数据"
                break
            subs.append((f"子组{k // subgroup_size + 1}", chunk, row_nums[k:k + subgroup_size]))
        if len(subs) < 2:
            return None, "子组数量不足 2 个，退回按 I-MR 处理"
        if subgroup_size not in CONSTANTS:
            return None, f"子组大小 {subgroup_size} 不在 2–10 范围内，退回按 I-MR 处理"
        return subs, note
    else:
        return None, None
    sizes = {len(s[1]) for s in subs}
    if len(sizes) != 1:
        return None, f"子组大小不一致（{sorted(sizes)}），退回按 I-MR 处理"
    n = sizes.pop()
    if n not in CONSTANTS:
        return None, f"子组大小 {n} 不在 2–10 范围内，退回按 I-MR 处理"
    if len(subs) < 2:
        return None, "子组数量不足 2 个，退回按 I-MR 处理"
    return subs, None


def run_rules(series, cl, ucl, lcl, labels):
    """简版西电规则：超控制限；连续 7 点同侧；连续 7 点递增或递减。返回 [(规则, [标签])]。"""
    hits = []
    beyond = [lab for x, lab in zip(series, labels) if x > ucl or x < lcl]
    if beyond:
        hits.append(("超出控制限", beyond))
    same = []
    run_side, run_labels = None, []
    for x, lab in zip(series, labels):
        side = 1 if x > cl else (-1 if x < cl else 0)
        if side != 0 and side == run_side:
            run_labels.append(lab)
        else:
            run_side, run_labels = side, [lab]
        if side != 0 and len(run_labels) == RUN_LENGTH:
            same.append(run_labels[-1])
    if same:
        hits.append((f"连续 {RUN_LENGTH} 点在中心线同一侧（第 {RUN_LENGTH} 点处）", same))
    trend = []
    direction, run_labels = 0, []
    for k in range(1, len(series)):
        d = 1 if series[k] > series[k - 1] else (-1 if series[k] < series[k - 1] else 0)
        if d != 0 and d == direction:
            run_labels.append(labels[k])
        else:
            direction, run_labels = d, [labels[k - 1], labels[k]] if d != 0 else []
        if d != 0 and len(run_labels) == RUN_LENGTH:
            trend.append(run_labels[-1])
    if trend:
        hits.append((f"连续 {RUN_LENGTH} 点递增或递减（第 {RUN_LENGTH} 点处）", trend))
    return hits


def safe_div(a, b):
    return a / b if b else None


def capability(mean, sigma, usl, lsl):
    cp = safe_div(usl - lsl, 6 * sigma) if usl is not None and lsl is not None else None
    cpu = safe_div(usl - mean, 3 * sigma) if usl is not None else None
    cpl = safe_div(mean - lsl, 3 * sigma) if lsl is not None else None
    sides = [v for v in (cpu, cpl) if v is not None]
    cpk = min(sides) if sides else None
    return cp, cpu, cpl, cpk


def fmt(x, nd=4):
    if x is None:
        return "—"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "—"
    return f"{x:.{nd}f}"


def analyze(args):
    header, rows = read_csv(args.csv)
    value_col = resolve_col(header, args.value_col, rows)
    group_col = resolve_col(header, args.group_col, rows) if args.group_col else None
    values, groups, row_nums, skipped = load_values(header, rows, value_col, group_col)
    if len(values) < 2:
        sys.exit("有效测量值不足 2 个。")
    usl, lsl, target = args.usl, args.lsl, args.target
    if usl is not None and lsl is not None and usl <= lsl:
        sys.exit("USL 必须大于 LSL。")

    n = len(values)
    mean = statistics.fmean(values)
    s_overall = statistics.stdev(values)
    subs, fallback = make_subgroups(values, groups, row_nums, group_col, args.subgroup_size)

    result = {
        "文件": args.csv, "测量值列": header[value_col], "n": n,
        "跳过的行": skipped, "均值": mean, "中位数": statistics.median(values),
        "最小值": min(values), "最大值": max(values), "总体标准差": s_overall,
        "USL": usl, "LSL": lsl, "目标值": target, "提示": [],
    }
    if fallback:
        result["提示"].append(fallback)
    if n < 25:
        result["提示"].append(f"n = {n} 少于 25，能力指数只能作初步参考，建议至少 25–30 个数据（分组时建议 ≥ 20 个子组）")

    if subs:
        k = len(subs[0][1])
        d2, a2, d3, d4 = CONSTANTS[k]
        ranges = [max(s[1]) - min(s[1]) for s in subs]
        means = [statistics.fmean(s[1]) for s in subs]
        rbar = statistics.fmean(ranges)
        s_within = rbar / d2
        labels = [str(s[0]) for s in subs]
        chart = {
            "类型": "Xbar-R", "子组大小": k, "子组数": len(subs),
            "Xbar图": {"CL": mean, "UCL": mean + a2 * rbar, "LCL": mean - a2 * rbar},
            "R图": {"CL": rbar, "UCL": d4 * rbar, "LCL": d3 * rbar},
            "点序列": means, "标签": labels,
        }
        chart["判异"] = run_rules(means, mean, chart["Xbar图"]["UCL"], chart["Xbar图"]["LCL"], labels)
        r_beyond = [lab for r, lab in zip(ranges, labels) if r > chart["R图"]["UCL"] or r < chart["R图"]["LCL"]]
        if r_beyond:
            chart["判异"].append(("R 图超出控制限", r_beyond))
    else:
        mrs = [abs(values[i] - values[i - 1]) for i in range(1, n)]
        mrbar = statistics.fmean(mrs)
        d2 = CONSTANTS[2][0]
        s_within = mrbar / d2
        labels = [f"第{rn}行" for rn in row_nums]
        chart = {
            "类型": "I-MR", "MR均值": mrbar,
            "I图": {"CL": mean, "UCL": mean + 3 * mrbar / d2, "LCL": mean - 3 * mrbar / d2},
            "MR图": {"CL": mrbar, "UCL": CONSTANTS[2][3] * mrbar, "LCL": 0.0},
            "点序列": values, "标签": labels,
        }
        chart["判异"] = run_rules(values, mean, chart["I图"]["UCL"], chart["I图"]["LCL"], labels)
        mr_beyond = [labels[i + 1] for i, mr in enumerate(mrs) if mr > chart["MR图"]["UCL"]]
        if mr_beyond:
            chart["判异"].append(("MR 图超出控制限", mr_beyond))

    result["组内标准差"] = s_within
    cp, cpu, cpl, cpk = capability(mean, s_within, usl, lsl)
    pp, ppu, ppl, ppk = capability(mean, s_overall, usl, lsl)
    result.update({"Cp": cp, "Cpu": cpu, "Cpl": cpl, "Cpk": cpk,
                   "Pp": pp, "Ppu": ppu, "Ppl": ppl, "Ppk": ppk})
    if target is not None:
        result["偏移量"] = mean - target
        if usl is not None and lsl is not None:
            result["Cpm"] = (usl - lsl) / (6 * math.sqrt(s_overall ** 2 + (mean - target) ** 2))
    above = [rn for v, rn in zip(values, row_nums) if usl is not None and v > usl]
    below = [rn for v, rn in zip(values, row_nums) if lsl is not None and v < lsl]
    result["超USL"] = above
    result["低于LSL"] = below
    result["控制图"] = chart
    return result


def render_markdown(r):
    out = []
    out.append(f"# 过程能力分析：{r['文件']}（列「{r['测量值列']}」）")
    out.append("")
    out.append("## 基本统计")
    out.append("| 项目 | 值 |")
    out.append("| --- | --- |")
    out.append(f"| n | {r['n']} |")
    out.append(f"| 均值 | {fmt(r['均值'])} |")
    out.append(f"| 中位数 | {fmt(r['中位数'])} |")
    out.append(f"| 最小值 / 最大值 | {fmt(r['最小值'])} / {fmt(r['最大值'])} |")
    out.append(f"| 总体标准差（n-1） | {fmt(r['总体标准差'], 5)} |")
    out.append(f"| 组内标准差（{r['控制图']['类型']}） | {fmt(r['组内标准差'], 5)} |")
    out.append(f"| USL / LSL / 目标 | {fmt(r['USL'])} / {fmt(r['LSL'])} / {fmt(r['目标值'])} |")
    if "偏移量" in r:
        out.append(f"| 均值 − 目标 | {fmt(r['偏移量'])} |")
    if r["跳过的行"]:
        out.append(f"| 跳过的行（非数字或空） | {', '.join(map(str, r['跳过的行']))} |")
    out.append("")
    out.append("## 能力指数")
    out.append("| 指数 | 值 | 口径 |")
    out.append("| --- | --- | --- |")
    out.append(f"| Cp | {fmt(r['Cp'], 2)} | (USL − LSL) / (6 × 组内标准差) |")
    out.append(f"| Cpk | {fmt(r['Cpk'], 2)} | min(Cpu, Cpl)，Cpu = {fmt(r['Cpu'], 2)}，Cpl = {fmt(r['Cpl'], 2)} |")
    out.append(f"| Pp | {fmt(r['Pp'], 2)} | (USL − LSL) / (6 × 总体标准差) |")
    out.append(f"| Ppk | {fmt(r['Ppk'], 2)} | min(Ppu, Ppl)，Ppu = {fmt(r['Ppu'], 2)}，Ppl = {fmt(r['Ppl'], 2)} |")
    if "Cpm" in r:
        out.append(f"| Cpm | {fmt(r['Cpm'], 2)} | (USL − LSL) / (6 × √(总体方差 + 偏移量²)) |")
    out.append("")
    out.append("## 超规格")
    out.append(f"- 高于 USL：{len(r['超USL'])} 点" + (f"（行 {', '.join(map(str, r['超USL'][:20]))}）" if r["超USL"] else ""))
    out.append(f"- 低于 LSL：{len(r['低于LSL'])} 点" + (f"（行 {', '.join(map(str, r['低于LSL'][:20]))}）" if r["低于LSL"] else ""))
    out.append("")
    c = r["控制图"]
    out.append(f"## 控制图（{c['类型']}）")
    out.append("| 图 | CL | UCL | LCL |")
    out.append("| --- | --- | --- | --- |")
    if c["类型"] == "I-MR":
        out.append(f"| I 图（单值） | {fmt(c['I图']['CL'])} | {fmt(c['I图']['UCL'])} | {fmt(c['I图']['LCL'])} |")
        out.append(f"| MR 图（移动极差） | {fmt(c['MR图']['CL'])} | {fmt(c['MR图']['UCL'])} | {fmt(c['MR图']['LCL'])} |")
    else:
        out.append(f"| Xbar 图（子组大小 {c['子组大小']}，{c['子组数']} 个子组） | {fmt(c['Xbar图']['CL'])} | {fmt(c['Xbar图']['UCL'])} | {fmt(c['Xbar图']['LCL'])} |")
        out.append(f"| R 图 | {fmt(c['R图']['CL'])} | {fmt(c['R图']['UCL'])} | {fmt(c['R图']['LCL'])} |")
    out.append("")
    out.append("## 判异")
    if c["判异"]:
        for rule, labs in c["判异"]:
            out.append(f"- {rule}：{', '.join(labs[:20])}" + ("（仅列前 20 个）" if len(labs) > 20 else ""))
    else:
        out.append("- 未触发（超控制限 / 连续 7 点同侧 / 连续 7 点趋势 均未出现）")
    if r["提示"]:
        out.append("")
        out.append("## 提示")
        for t in r["提示"]:
            out.append(f"- {t}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="过程能力与控制图计算（标准库）")
    ap.add_argument("csv", help="输入 CSV 文件")
    ap.add_argument("--usl", type=float, help="规格上限")
    ap.add_argument("--lsl", type=float, help="规格下限")
    ap.add_argument("--target", type=float, help="目标值（可选）")
    ap.add_argument("--value-col", help="测量值列名或列序号（从 0 起）")
    ap.add_argument("--group-col", help="分组列名或列序号（可选）")
    ap.add_argument("--subgroup-size", type=int, help="没有分组列时，把相邻 N 个值并成一个子组")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是 Markdown")
    args = ap.parse_args()
    if args.usl is None and args.lsl is None:
        sys.exit("至少要给 --usl 或 --lsl 之一。")
    result = analyze(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_markdown(result))


if __name__ == "__main__":
    main()
