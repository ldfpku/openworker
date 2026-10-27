#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SMJ AI 培训 · 每日出题脚本（cron 纯脚本模式调用，不经模型）

设计要点：
  - 出题必须可复现：同一个日期重跑结果相同（已登记的日期直接回放）。
  - 题量固定 5 题：当周模块 2 单选 + 1 判断 + 1 简答，再加 1 道上一周回顾题。
  - 同一题库内优先取没用过的题；用尽后允许复用（报告里标注）。
  - 学员版正文不含答案；答案与讲评另发讲师（--key），次日随题附上（--review）。
  - 每封邮件附 1 条「今日 Tip」：按当周模块从 tips/tips.json 轮换，每 3 个出题日插一条
    「防错与安全」或「排障」横切类；选取只依赖日期，所以同一天重跑是同一条。

用法：
  python assemble_quiz.py --date 2026-11-02 --roster roster.example.csv
  python assemble_quiz.py --date 2026-11-02 --tip-only            # 只看今天的 Tip
  python assemble_quiz.py --tips-md                              # 重新生成《每日Tip清单》讲义
  python assemble_quiz.py --date 2026-11-02 --key --review            # 讲师版（含昨日讲评）
  python assemble_quiz.py --date 2026-11-02 --commit                  # 登记本题已用
"""
from __future__ import annotations
import argparse, csv, datetime, json, random, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BANK_PATH = HERE / "questions.json"
USED_PATH = HERE / "used.json"
TIP_PATH = HERE.parent / "tips" / "tips.json"
TIPS_MD_PATH = HERE.parent / "12-每日Tip清单.md"
CROSS_CATS = ("C", "F")      # 每 3 个出题日插一条横切类：防错与安全 / 排障

# 8 周课程表：周序号 → 考试模块（模块0 扫盲也考，自学后当周小测）
WEEK_MODULES = ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7"]
START = datetime.date(2026, 11, 2)          # 第一周周一，可按开班日改
PLAN = {"single": 2, "judge": 1, "short": 1}  # 当周模块构成；第 5 题是回顾题


def load_bank() -> tuple[dict, list]:
    data = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    return data["meta"], data["questions"]


def load_used() -> dict:
    if USED_PATH.exists():
        return json.loads(USED_PATH.read_text(encoding="utf-8"))
    return {}


def week_index(day: datetime.date) -> int:
    return max(0, (day - START).days // 7)


def school_day_index(day: datetime.date) -> int:
    """从开班日起数到该日是第几个出题日（0 基）；Tip 轮换靠它，保证只依赖日期。"""
    n, d = 0, START
    while d < day:
        if d.weekday() < 5:
            n += 1
        d += datetime.timedelta(days=1)
    return n


def load_tips() -> tuple[dict, list]:
    if not TIP_PATH.exists():
        return {}, []
    data = json.loads(TIP_PATH.read_text(encoding="utf-8"))
    return data.get("meta", {}), data.get("tips", [])


def tip_for(day: datetime.date, tips: list[dict]) -> dict | None:
    """确定性选 Tip：当周模块的池子按出题日推进；每 3 个出题日插一条横切类（防错/排障）。"""
    if not tips:
        return None
    i, wi = school_day_index(day), week_index(day)
    cur = WEEK_MODULES[min(wi, len(WEEK_MODULES) - 1)]
    if i % 3 == 0:                       # 横切类：防错与安全 / 排障 轮流插
        cat = CROSS_CATS[(i // 3) % len(CROSS_CATS)]
        pool = [t for t in tips if t["cat"] == cat]
        k = (i // 3) // len(CROSS_CATS)
    else:
        pool = [t for t in tips if t.get("week") == cur] or tips
        k = i
    if not pool:
        return None
    return sorted(pool, key=lambda t: t["id"])[k % len(pool)]


def render_tip(tip: dict | None, meta: dict, day: datetime.date) -> str:
    if not tip:
        return ""
    cats = meta.get("cats", {})
    apps = meta.get("apps", {})
    head = (f"今日 Tip｜{tip['id']}｜{cats.get(tip['cat'], tip['cat'])}"
            f"｜{apps.get(tip.get('app'), tip.get('app'))}｜第 {school_day_index(day) + 1} 个出题日")
    lines = [head, f"  在哪：{tip['where']}", f"  怎么做：{tip['do']}",
             f"  为什么：{tip['why']}", f"  怎么算做对了：{tip['verify']}"]
    if tip.get("pit"):
        lines.append(f"  常见误设：{tip['pit']}")
    if tip.get("exam"):
        lines.append(f"  这条会考（{tip['exam']}）")
    return "\n".join(lines)


def tips_markdown(meta: dict, tips: list[dict]) -> str:
    """由 tips.json 生成讲义（别手改生成的 md；改 tips.json 后重跑 --tips-md）。"""
    cats, apps = meta.get("cats", {}), meta.get("apps", {})
    by_week: dict[str, list] = {}
    for t in tips:
        by_week.setdefault(t.get("week", "-"), []).append(t)
    blurb = {"A": "同样的活少花钱", "B": "一次做对、少返工", "C": "不出事、不泄密",
             "D": "让它按时自己跑，还送到位", "E": "手熟：界面与输入的效率",
             "F": "卡住了怎么办", "G": "Hermes 专属操作"}
    out = ["# SMJ AI 培训 · 每日 Tip 清单（自动生成）",
           "",
           f"> 共 {len(tips)} 条。生成方式：`python 题库/assemble_quiz.py --tips-md`（数据源 `tips/tips.json`）。",
           "> 用法：每封邮件附 1 条（按日期轮换，同一天重跑是同一条）；课上要求学员当场做到「怎么算做对了」那一行。",
           "> 讲师配图要求：凡考进题库的 Tip，必须配一张带红框的界面截图（截图先脱敏）。",
           "",
           "## 七类 Tip 各解决什么",
           "",
           "| 类别 | 条数 | 解决什么 |",
           "| --- | --- | --- |"]
    for c in "ABCDEFG":
        out.append(f"| {c}｜{cats.get(c, c)} | {sum(1 for t in tips if t['cat'] == c)} | {blurb.get(c, '')} |")
    out += ["", "## 按周轮换的池子", "", "| 周 | 条数 | Tip 编号 |", "| --- | --- | --- |"]
    for w in sorted(by_week):
        ids = ", ".join(t["id"] for t in sorted(by_week[w], key=lambda t: t["id"]))
        out.append(f"| {w} | {len(by_week[w])} | {ids} |")
    for c in "ABCDEFG":
        pool = [t for t in tips if t["cat"] == c]
        if not pool:
            continue
        out += ["", f"## {c}｜{cats.get(c, c)}（{len(pool)} 条）", "",
                "| 编号 | 在哪 | 怎么做 | 为什么 | 怎么算做对了 | 常见误设 | 会考 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for t in sorted(pool, key=lambda t: t["id"]):
            cells = [t["id"], t["where"], t["do"], t["why"], t["verify"], t.get("pit", "—"), t.get("exam") or "—"]
            out.append("| " + " | ".join(x.replace("|", "／") for x in cells) + " |")
    return "\n".join(out) + "\n"


def check_tips(tips: list[dict]) -> int:
    """体检：条数够不够、每周池子够不够、必填字段全不全。"""
    print(f"Tip 共 {len(tips)} 条（培训要求 ≥30）")
    bad = [f"{t.get('id', '?')} 缺 {k}" for t in tips
           for k in ("id", "cat", "app", "week", "where", "do", "why", "verify") if not t.get(k)]
    for w in WEEK_MODULES:
        n = sum(1 for t in tips if t.get("week") == w)
        print(f"  {w}: 当周池 {n:>2} 条 ‖ {'够用' if n >= 4 else '偏少（补到 4 条以上，否则一周内重样）'}")
    for c in CROSS_CATS:
        print(f"  横切类 {c}: {sum(1 for t in tips if t['cat'] == c)} 条（每 3 个出题日轮到一次）")
    if bad:
        print("字段问题：\n  " + "\n  ".join(bad))
    return 0 if not bad else 1


def pick(module: str, questions: list[dict], used: dict, rng: random.Random,
         want: dict[str, int] | None = None, exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    pool = [q for q in questions if q["module"] == module and q["id"] not in exclude]
    if not pool:
        return []
    fresh = [q for q in pool if q["id"] not in used.get("used", {})]
    chosen = []
    if want:
        for t, n in want.items():
            c = [q for q in fresh if q["type"] == t]
            if len(c) < n:                      # 用尽后允许复用（当周已选过的不再出第二次）
                c = [q for q in pool if q["type"] == t]
            chosen += rng.sample(c, min(n, len(c)))
    else:
        c = fresh or pool
        chosen = [rng.choice(c)]
    # 去重（不同题型可能撞同一题）
    seen, out = set(), []
    for q in chosen:
        if q["id"] not in seen:
            seen.add(q["id"])
            out.append(q)
    return out


def assemble(day: datetime.date, bank_meta: dict, questions: list[dict], used: dict) -> list[dict]:
    rec = used.get("plan", {}).get(day.isoformat())
    if rec:                                     # 同日期重跑 = 回放，保证可复现
        by_id = {q["id"]: q for q in questions}
        return [by_id[i] for i in rec if i in by_id]
    rng = random.Random(day.isoformat())
    wi = week_index(day)
    cur = WEEK_MODULES[min(wi, len(WEEK_MODULES) - 1)]
    sel = pick(cur, questions, used, rng, PLAN)
    prev = WEEK_MODULES[wi - 1] if wi >= 1 else None
    if prev:
        sel += pick(prev, questions, used, rng, exclude={q["id"] for q in sel})
    if len(sel) < 5:
        # 上一周没有可回顾的题（第 1 周）：当周补一道，仍不与当天已选重复
        sel += pick(cur, questions, used, rng, exclude={q["id"] for q in sel})
    return sel[:5]


def render_question(i: int, q: dict, with_answer: bool) -> str:
    lines = [f"{i}. 【{q['id']}｜{q['type']}】{q['q']}"]
    if q.get("options"):
        for n, opt in enumerate(q["options"]):
            mark = "  ← 答案" if (with_answer and q.get("answer") == n) else ""
            lines.append(f"   {chr(65 + n)}. {opt}{mark}")
    lines.append("   （简答按要点给分）" if q["type"] == "short" else "")
    if with_answer:
        a = q.get("answer")
        if isinstance(a, int) and q.get("options"):
            lines.append(f"   参考答案：{chr(65 + a)}")
        if q.get("key_points"):
            lines.append("   要点：" + "；".join(q["key_points"]))
        if q.get("explain"):
            lines.append("   讲评：" + q["explain"])
    return "\n".join([l for l in lines if l])


def check_bank(meta: dict, questions: list) -> int:
    """体检：按「一周 5 个工作日 × 当周模块 4 题」算各模块的池子够不够、复用多密。"""
    need = {t: n * 5 for t, n in PLAN.items()}          # 当周模块一周要出多少道该模块的题
    total_week = sum(need.values())
    print(f"当周模块一周需出 {total_week} 题（{need['single']} 单选 / {need['judge']} 判断 / {need['short']} 简答）")
    print("模块  单选 判断 简答 合计 ‖ 池内每题一周平均出现 ‖ 结论")
    worst = 0.0
    for m, name in meta["modules"].items():
        pool = [q for q in questions if q["module"] == m]
        c = {t: sum(1 for q in pool if q["type"] == t) for t in PLAN}
        ratio = max((need[t] / c[t]) if c[t] else 99 for t in PLAN)
        worst = max(worst, min(ratio, 9))
        ok = all(c[t] >= PLAN[t] for t in PLAN)
        print(f"{m}  {c['single']:>4} {c['judge']:>4} {c['short']:>4} {len(pool):>5} ‖ "
              f"{ratio:>22.1f}× ‖ {'够用' if ok else '缺题：先补足'}"
              f"{'（间隔重复，可接受）' if ratio <= 2.5 else '（偏密，建议补到 12 题以上）'}")
    print(f"\n判据：每题一周内出现 ≤2.5 次算健康（同一周里隔 1–2 天再练一次是有效的间隔重复）；"
          f"当前最差 {worst:.1f}×。整学期（40 个出题日 / 200 槽位）复用率见 --simulate。")
    return 0


def simulate(start: datetime.date, days: int, meta: dict, questions: list) -> int:
    """不落盘地模拟 days 个出题日，报告单日重复与整期复用率（体检用）。"""
    from collections import Counter
    used, ids, dup = {}, [], 0
    day, n = start, 0
    while n < days:
        if day.weekday() < 5:
            sel = assemble(day, meta, questions, used)
            got = [q["id"] for q in sel]
            if len(set(got)) != len(sel):
                dup += 1
            ids += got
            used.setdefault("plan", {})[day.isoformat()] = got
            used.setdefault("used", {}).update({i: day.isoformat() for i in got})
            n += 1
        day += datetime.timedelta(days=1)
    c = Counter(ids)
    print(f"模拟 {days} 个出题日（{start} 起）：槽位 {len(ids)}，用到 {len(c)} 道题，"
          f"整期复用 {1 - len(c) / len(ids):.0%}，单日出现重复的天数 {dup}，"
          f"最常被出的题 {c.most_common(5)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--roster", default=str(HERE / "roster.example.csv"))
    ap.add_argument("--key", action="store_true", help="讲师版：含答案与要点")
    ap.add_argument("--review", action="store_true", help="附昨日答案与讲评")
    ap.add_argument("--commit", action="store_true", help="把本题登记为已用")
    ap.add_argument("--check", action="store_true", help="体检题库：各模块题量与复用倍数")
    ap.add_argument("--check-tips", action="store_true", help="体检 Tip 库：条数与每周池子")
    ap.add_argument("--tips-md", nargs="?", const=str(TIPS_MD_PATH), metavar="输出md",
                    help="由 tips/tips.json 生成《每日Tip清单》讲义（默认写到 12-每日Tip清单.md）")
    ap.add_argument("--tip-only", action="store_true", help="只输出当天的 Tip")
    ap.add_argument("--no-tip", action="store_true", help="邮件里不附 Tip")
    ap.add_argument("--simulate", type=int, metavar="出题日数", help="模拟若干出题日，查重复与复用率")
    ap.add_argument("--sender", default="ai-peixun@smjtools.com")
    args = ap.parse_args()

    day = datetime.date.fromisoformat(args.date)
    meta, questions = load_bank()
    tmeta, tips = load_tips()
    if args.tips_md:
        Path(args.tips_md).write_text(tips_markdown(tmeta, tips), encoding="utf-8")
        print(f"[已生成] {args.tips_md}（{len(tips)} 条）")
        return 0
    if args.check_tips:
        return check_tips(tips)
    if args.check:
        return check_bank(meta, questions)
    if args.simulate:
        return simulate(day, args.simulate, meta, questions)
    if day.weekday() >= 5:
        print(f"[跳过] {day} 是周末，不发题。", file=sys.stderr)
        return 0
    tip = None if args.no_tip else tip_for(day, tips)
    if args.tip_only:
        print(render_tip(tip, tmeta, day) or "（Tip 库为空）")
        return 0
    used = load_used()
    sel = assemble(day, meta, questions, used)
    if not sel:
        print("[错误] 题库为空或该模块没有题。", file=sys.stderr)
        return 1

    wi = week_index(day) + 1
    mod = WEEK_MODULES[min(wi - 1, len(WEEK_MODULES) - 1)]
    names = {"single": "单选", "judge": "判断", "short": "简答"}
    roster = []
    p = Path(args.roster)
    if p.exists():
        with p.open(encoding="utf-8") as f:
            roster = [r for r in csv.DictReader(f) if r.get("email")]

    head = [
        f"主题：SMJ AI 培训·每日 5 题｜第 {wi} 周（{meta['modules'][mod]}）｜{day}",
        f"收件人：{len(roster)} 人（{', '.join(r['email'] for r in roster) if roster else '未配名单'}）",
        f"发件：{args.sender}",
        "",
        "各位同事，早。今天 5 道题，17:00 前回信。格式：题号 答案 一句理由。",
        "满分 100（每题 20 分），简答按要点给分。回信只写自己的，别互相抄。",
        "",
    ]
    if tip:
        head += ["今天先做这一件事（5 分钟，做完再答题；做不到就在回信里写「卡在第几步」）：",
                 render_tip(tip, tmeta, day), ""]
    elif args.no_tip:
        head += [""]
    body = [render_question(i, q, args.key) for i, q in enumerate(sel, 1)]

    tail = ["", "—— 讲评与判分在 17:30 跑，明早随题附上；周五 16:00 有周小结。"]
    if args.review:
        y = day - datetime.timedelta(days=1)
        yrec = used.get("plan", {}).get(y.isoformat())
        if yrec:
            by_id = {q["id"]: q for q in questions}
            ysel = [by_id[i] for i in yrec if i in by_id]
            tail.insert(0, "昨日答案与讲评：\n" + "\n".join(render_question(i, q, True) for i, q in enumerate(ysel, 1)))

    print("\n".join(head + body + tail))

    if args.commit:
        used.setdefault("plan", {})[day.isoformat()] = [q["id"] for q in sel]
        used.setdefault("used", {}).update({q["id"]: day.isoformat() for q in sel})
        USED_PATH.write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[已登记] {day} → {', '.join(q['id'] for q in sel)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
