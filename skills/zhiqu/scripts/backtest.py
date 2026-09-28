#!/usr/bin/env python3
"""知衢 · 投档数据逐年回测（仅用 Python 标准库，3.8+）。

用前一年的最低录取位次"预测"后一年，量化三件事：
1. 整体漂移：全省录取位次普遍收紧还是放松（共同冲击，对应 optimize.py 的 rho）
2. 结构突变：位次变化超过约 40% 的组有多少、是哪些（逐个查原因，记入变化记录）
3. 招生计划弹性：计划数变化能解释多少位次变化

输入：每年一份投档 CSV，列 code, name, group, plan, admit, score, rank（院校代码、名称、专业组代码、
计划数、投档人数、最低分、最低排位），可由官方投档表整理得到。

用法：
  python3 backtest.py --year 2022=gd_2022.csv --year 2023=gd_2023.csv [--cohort 2022=N --cohort 2023=N]
                      [--top 20] [--out residuals.csv]

注意：按"院校代码 + 组号"匹配。组号相同不代表组内专业相同，匹配错误会表现为"突变"；
因此突变清单是待查线索，不是结论。
"""
import argparse
import csv
import math
import statistics as st

JUMP = math.log(1.4)


def load(path):
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                plan, admit, rank = int(r["plan"]), int(r["admit"] or 0), int(r["rank"])
            except (KeyError, ValueError):
                continue
            out[(r["code"].strip(), r["group"].strip())] = {
                "name": r.get("name", "").strip(), "plan": plan, "admit": admit, "rank": rank,
                "full": admit >= plan > 0,
            }
    return out


def ols(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    res = [y - my - b * (x - mx) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(e * e for e in res) / (len(xs) - 2) / sxx)
    syy = sum((y - my) ** 2 for y in ys)
    return b, se, (1 - sum(e * e for e in res) / syy) if syy else 0.0


def main():
    ap = argparse.ArgumentParser(description="知衢 · 投档数据逐年回测")
    ap.add_argument("--year", action="append", required=True, help="年份=投档CSV，至少两年")
    ap.add_argument("--cohort", action="append", default=[], help="年份=同科类考生总数，用于按百分位折算")
    ap.add_argument("--min-rank", type=int, default=500, help="忽略位次过靠前的组（样本极小、波动失真）")
    ap.add_argument("--top", type=int, default=20, help="列出变化最大的组数")
    ap.add_argument("--out", help="把每个组的残差写成 CSV")
    a = ap.parse_args()

    years = sorted((int(k), v) for k, v in (x.split("=", 1) for x in a.year))
    cohort = {int(k): float(v) for k, v in (x.split("=", 1) for x in a.cohort)}
    if len(years) < 2:
        raise SystemExit("至少需要两年数据")
    data = {y: load(p) for y, p in years}
    rows_out = []

    print("# 知衢 · 投档回测\n")
    for (y0, _), (y1, _) in zip(years, years[1:]):
        d0, d1 = data[y0], data[y1]
        scale = cohort[y1] / cohort[y0] if y0 in cohort and y1 in cohort else 1.0
        pairs = []
        for k in d0.keys() & d1.keys():
            a0, a1 = d0[k], d1[k]
            if not (a0["full"] and a1["full"]) or a0["rank"] < a.min_rank:
                continue
            err = math.log(a1["rank"] / (a0["rank"] * scale))
            pairs.append((k, a0, a1, err, math.log(a1["plan"] / a0["plan"])))
        if not pairs:
            print(f"## {y0} → {y1}：无可匹配的组\n")
            continue
        errs = [p[3] for p in pairs]
        stable = [p for p in pairs if abs(p[3]) <= JUMP]
        print(f"## {y0} → {y1}\n")
        print(f"- 两年都存在且满额的组：{len(pairs)}（{y0} 共 {len(d0)}，{y1} 共 {len(d1)}）"
              + (f"；已按考生总数折算 ×{scale:.3f}" if scale != 1.0 else ""))
        print(f"- 整体漂移（对数误差中位数）：{st.median(errs):+.3f}，即录取位次普遍{'放松' if st.median(errs) > 0 else '收紧'}约 {abs(math.expm1(st.median(errs))):.0%}")
        print(f"- 误差标准差：全部 {st.pstdev(errs):.3f}；去掉突变后 {st.pstdev([p[3] for p in stable]):.3f}（可对照 optimize.py 的 sigma 默认值）")
        print(f"- 结构突变（变化 > 40%）：{len(pairs) - len(stable)} 个，占 {(len(pairs) - len(stable)) / len(pairs):.1%}")
        fit = ols([p[4] for p in stable], [p[3] for p in stable])
        if fit:
            b, se, r2 = fit
            print(f"- 招生计划弹性（去掉突变）：{b:+.3f} ± {se:.3f}，解释力 R² = {r2:.3f}"
                  f"（计划翻倍 → 位次约变化 {math.expm1(b * math.log(2)):+.1%}）")
        print(f"\n变化最大的 {a.top} 个组（待查原因：组内专业、选科要求、定向条件、组号含义）：\n")
        print(f"| 院校 | 组 | {y0} 位次 | {y1} 位次 | 变化 | 计划 {y0}→{y1} |")
        print("|---|---|---|---|---|---|")
        for k, a0, a1, e, _ in sorted(pairs, key=lambda p: -abs(p[3]))[: a.top]:
            print(f"| {a1['name']} | {k[1]} | {a0['rank']} | {a1['rank']} | {math.expm1(e):+.0%} | {a0['plan']}→{a1['plan']} |")
        print()
        for k, a0, a1, e, pc in pairs:
            rows_out.append({"from": y0, "to": y1, "code": k[0], "group": k[1], "name": a1["name"],
                             "rank_from": a0["rank"], "rank_to": a1["rank"], "log_err": round(e, 4),
                             "plan_from": a0["plan"], "plan_to": a1["plan"], "jump": int(abs(e) > JUMP)})

    print("> 突变清单是线索，不是结论：同一组号在两年里可能对应不同专业。只有填报前就能知道的原因，才值得记入变化记录并用于预测。")
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
            w.writeheader()
            w.writerows(rows_out)


if __name__ == "__main__":
    main()
