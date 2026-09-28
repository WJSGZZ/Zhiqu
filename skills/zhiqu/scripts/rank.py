#!/usr/bin/env python3
"""知衢 · 分数、位次与录取线预测工具（仅用 Python 标准库，3.8+）。

一分一段表 CSV：列 score + count（该分人数）或 score + cumulative（累计人数），UTF-8。
本工具的"位次"取该分数的累计人数（即同分考生中的最后一名），与多数省份公布口径一致；
同分段的最好位次也一并给出。

子命令：
  score   分数 → 位次                rank.py score  --table 2026.csv 596
  rank    位次 → 分数                rank.py rank   --table 2026.csv 23500
  equiv   等位分：今年分数在往年相当于多少分
                                     rank.py equiv  --table 2026.csv --past 2025.csv --past 2024.csv 596
  estimate 估分（出分前）→ 位次区间，并给出 optimize.py 的 --rank-sd
                                     rank.py estimate --table 2025.csv 596 --err 8
  predict 逐个志愿预测今年最低录取位次（中位与 80% 区间）、换算分数线、单独过线概率；
          可按过线概率筛出候选池
                                     rank.py predict pool.csv --rank 23500 [--table 2026.csv]
                                             [--min-p 0.02 --max-p 0.995 --out candidates.csv]
"""
import argparse
import bisect
import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optimize import load_candidates, parse_cohort  # noqa: E402  同一套位次模型，避免两处实现不一致

Z80 = 1.2816  # 标准正态 90% 分位，用于 80% 区间
Z90 = 1.6449  # 95% 分位，用于 90% 区间


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


class Table:
    """一分一段表。scores 从高到低，cum[i] 为分数 >= scores[i] 的人数。"""

    def __init__(self, path):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            cols = {c.strip().lower(): c for c in reader.fieldnames or []}
            if "score" not in cols or not ({"count", "cumulative"} & cols.keys()):
                sys.exit(f"{path}：需要 score 列，以及 count 或 cumulative 列")
            rows = []
            for r in reader:
                s = r[cols["score"]].strip()
                if not s:
                    continue
                if "cumulative" in cols and r[cols["cumulative"]].strip():
                    rows.append((float(s), None, int(float(r[cols["cumulative"]]))))
                else:
                    rows.append((float(s), int(float(r[cols["count"]])), None))
        rows.sort(key=lambda x: -x[0])
        self.scores, self.cum, total = [], [], 0
        for s, cnt, cu in rows:
            total = cu if cu is not None else total + cnt
            self.scores.append(s)
            self.cum.append(total)
        if any(b < a for a, b in zip(self.cum, self.cum[1:])):
            sys.exit(f"{path}：累计人数不是单调递增，请检查表格")
        self.path, self.total = path, self.cum[-1]

    def rank_of(self, score):
        """返回 (最好位次, 位次)。分数不在表中时取表中不高于它的最近一档。"""
        neg = [-x for x in self.scores]
        i = bisect.bisect_left(neg, -score)
        if i >= len(self.scores):
            return self.cum[-1], self.cum[-1]
        prev = self.cum[i - 1] if i > 0 else 0
        return prev + 1, self.cum[i]

    def score_of(self, rank):
        """位次 rank 的考生所在分数。"""
        i = bisect.bisect_left(self.cum, rank)
        return self.scores[min(i, len(self.scores) - 1)]


def cmd_score(a):
    t = Table(a.table)
    best, r = t.rank_of(a.score)
    print(f"{a.score:g} 分 → 位次 {r}（同分最好 {best}），全表 {t.total} 人，前 {r / t.total:.2%}")


def cmd_rank(a):
    t = Table(a.table)
    s = t.score_of(a.rank)
    print(f"位次 {a.rank:.0f} → {s:g} 分（全表 {t.total} 人，前 {a.rank / t.total:.2%}）")


def cmd_equiv(a):
    t = Table(a.table)
    _, r = t.rank_of(a.score)
    print(f"今年 {a.score:g} 分，位次 {r}（前 {r / t.total:.2%}）")
    for p in a.past:
        pt = Table(p)
        rr = r if a.by == "rank" else max(1, round(r / t.total * pt.total))
        print(f"- {os.path.basename(p)}：等位分 {pt.score_of(rr):g}（按{'位次' if a.by == 'rank' else '百分位'}，对应位次 {rr}）")
    if a.by == "rank":
        print("  若两年同科类考生总数差别明显，改用 --by percentile 再看一次。")


def cmd_estimate(a):
    t = Table(a.table)
    hi = t.rank_of(a.score + a.err)[1]
    mid = t.rank_of(a.score)[1]
    lo = t.rank_of(a.score - a.err)[1]
    sd = (math.log(lo) - math.log(max(hi, 1))) / (2 * Z90) if lo > hi else 0.0
    print(f"估分 {a.score:g} ± {a.err:g}（按约 90% 把握理解），参照 {os.path.basename(a.table)}：")
    print(f"- 位次中位约 {mid}，区间 {hi} – {lo}")
    print(f"- optimize.py 可用：--rank {mid} --rank-sd {sd:.3f}")
    print("  注意：用的是往年一分一段表，只能近似；出分后请换成今年的表和真实位次。")


def cmd_predict(a):
    rows, skipped = load_candidates(a.csv, True, a.sigma_floor, a.sigma_single, 0.0, require_utility=False,
                                    cohort=parse_cohort(a.cohort), cohort_now=a.cohort_now,
                                    drift=a.drift, target_year=a.target_year)
    table = Table(a.table) if a.table else None
    log_r = math.log(a.rank) if a.rank else None
    out = []
    for r in rows:
        mid = math.exp(r["mu"])
        lo, hi = math.exp(r["mu"] - Z80 * r["sigma"]), math.exp(r["mu"] + Z80 * r["sigma"])
        s = math.sqrt(r["sigma"] ** 2 + a.rank_sd ** 2)
        p = phi((r["mu"] - log_r) / s) if log_r is not None else None
        out.append((r, mid, lo, hi, p))
    if log_r is not None:
        out.sort(key=lambda x: -x[4])
    kept = [x for x in out if x[4] is None or a.min_p <= x[4] <= a.max_p]

    print("| 志愿 | 预测最低位次 | 80% 区间 | " + ("预测分数线 | " if table else "") + ("单独过线概率 | " if log_r else "") + "数据年数 |")
    print("|---|---|---|" + ("---|" if table else "") + ("---|" if log_r else "") + "---|")
    for r, mid, lo, hi, p in kept:
        cells = [r["name"], f"{mid:.0f}", f"{lo:.0f} – {hi:.0f}"]
        if table:
            cells.append(f"{table.score_of(round(mid)):g}（{table.score_of(round(hi)):g} – {table.score_of(round(lo)):g}）")
        if log_r:
            cells.append(f"{p:.0%}")
        cells.append(str(r["n_years"]))
        print("| " + " | ".join(cells) + " |")
    print(f"\n共 {len(rows)} 个，保留 {len(kept)} 个" + (f"（过线概率 {a.min_p:.0%} – {a.max_p:.1%}）" if log_r else ""))
    if skipped:
        print("跳过（缺位次）：" + "、".join(skipped))
    shaky = [x[0]["name"] for x in kept if x[0]["unstable"]]
    if shaky:
        print("⚠ 历年位次跳变超过约 40%（已自动放大波动）：" + "、".join(shaky))
        print("  多半是组内专业、招生条件或组号含义变了；先查招生章程和当年专业组组成，再决定是否保留。")
    print("区间只反映历年波动，不含招生计划、选科要求等今年的新变化；这些需要人工判断后写进 adj。")

    if a.out:
        fields = list(kept[0][0]["raw"].keys()) if kept else []
        extra = ["pred_rank", "pred_low", "pred_high", "p_clear", "unstable"]
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields + [c for c in extra if c not in fields])
            w.writeheader()
            for r, mid, lo, hi, p in kept:
                row = dict(r["raw"])
                row.update(pred_rank=round(mid), pred_low=round(lo), pred_high=round(hi),
                           p_clear="" if p is None else round(p, 4), unstable=int(r["unstable"]))
                w.writerow(row)
        print(f"已写出候选池：{a.out}（utility 列留给效用打分）")


def main():
    ap = argparse.ArgumentParser(description="知衢 · 分数、位次与录取线预测")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="分数 → 位次")
    s.add_argument("score", type=float)
    s.add_argument("--table", required=True, help="一分一段表 CSV")
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("rank", help="位次 → 分数")
    s.add_argument("rank", type=float)
    s.add_argument("--table", required=True)
    s.set_defaults(fn=cmd_rank)

    s = sub.add_parser("equiv", help="等位分")
    s.add_argument("score", type=float)
    s.add_argument("--table", required=True, help="今年一分一段表")
    s.add_argument("--past", action="append", required=True, help="往年一分一段表，可重复")
    s.add_argument("--by", choices=["rank", "percentile"], default="rank")
    s.set_defaults(fn=cmd_equiv)

    s = sub.add_parser("estimate", help="估分 → 位次区间")
    s.add_argument("score", type=float)
    s.add_argument("--table", required=True, help="最近一年的一分一段表")
    s.add_argument("--err", type=float, required=True, help="估分误差（分），按约 90%% 把握理解")
    s.set_defaults(fn=cmd_estimate)

    s = sub.add_parser("predict", help="预测各志愿录取线并筛选候选池")
    s.add_argument("csv", help="志愿 CSV，至少含 name 与 rank_年份 列（格式同 optimize.py）")
    s.add_argument("--rank", type=float, help="考生位次；给出则计算过线概率并可筛选")
    s.add_argument("--rank-sd", type=float, default=0.0, help="出分前的位次不确定性，见 estimate")
    s.add_argument("--table", help="今年一分一段表；给出则把预测位次换算成分数线")
    s.add_argument("--min-p", type=float, default=0.0, help="筛选：过线概率下限")
    s.add_argument("--max-p", type=float, default=1.0, help="筛选：过线概率上限")
    s.add_argument("--sigma-floor", type=float, default=0.10)
    s.add_argument("--sigma-single", type=float, default=0.25)
    s.add_argument("--drift", type=float, default=0.0, help="全省录取位次每年的对数漂移（backtest.py 估计）")
    s.add_argument("--target-year", type=int, help="预测的年份，默认为数据最近一年 +1")
    s.add_argument("--cohort", action="append", default=[], help="年份=该年同科类考生总数，可重复")
    s.add_argument("--cohort-now", type=float, help="今年同科类考生总数；与 --cohort 一起按百分位折算历年位次")
    s.add_argument("--out", help="把保留的志愿写成候选池 CSV")
    s.set_defaults(fn=cmd_predict)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
