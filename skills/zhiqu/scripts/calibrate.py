#!/usr/bin/env python3
"""校准检验：模型说"70% 能过线"的志愿，实际是不是七成过线。

对每个目标年份 T，只用 T 之前的数据，按 optimize.py 的同一套规则
（近期加权均值、全省漂移修正、波动下限、突变放大）给每个专业/专业组算出
今年最低录取位次的对数正态分布 N(mu, sigma)，再看真实位次落在分布的哪个位置：

  PIT = Φ((ln 真实位次 − mu) / sigma)

模型校准良好时，PIT 在 0–1 上均匀分布：
- 50% / 80% / 90% 预测区间的实际覆盖率应接近 50% / 80% / 90%；
- 对任意考生位次 r，模型给出的过线概率 p = P(录取线位次 ≥ r)，实际过线比例也应接近 p（可靠性表）；
- 平均 PIT 偏离 0.5 表示整体偏乐观或偏保守。

漂移只用 T 之前可得的相邻年份变化估计（无前视）。

usage:
  python3 scripts/calibrate.py --province 浙江 --key major --year 2022=data/zhejiang/general_2022.csv ... [--drift auto|0]
"""
import argparse
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as bt  # noqa: E402
from optimize import RECENCY_WEIGHTS, JUMP_WARN  # noqa: E402


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def predict(hist, drift, target, sigma_floor, sigma_single):
    """hist: [(year, rank)]，近的在前。与 optimize.load_candidates 相同的规则。"""
    pts = [(k, math.log(r) + drift * (target - y)) for k, (y, r) in enumerate(hist)]
    ws = [RECENCY_WEIGHTS[min(k, len(RECENCY_WEIGHTS) - 1)] for k, _ in pts]
    logs = [l for _, l in pts]
    mu = sum(w * l for w, l in zip(ws, logs)) / sum(ws)
    if len(logs) >= 2:
        sd = st.stdev(logs)
        sigma = max(sd, sigma_floor)
        jumps = [abs(logs[k] - logs[k + 1]) for k in range(len(logs) - 1)]
        if max(jumps) > JUMP_WARN:
            sigma = max(sigma, max(jumps))
    else:
        sigma = sigma_single
    return mu, sigma


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--province", default="")
    ap.add_argument("--key", choices=["group", "major"], default="group")
    ap.add_argument("--school", choices=["code", "name"], default="code")
    ap.add_argument("--year", action="append", required=True, help="年份=投档CSV")
    ap.add_argument("--drift", default="auto", help="auto = 用目标年之前最近三次相邻变化的中位数平均；或给定数值")
    ap.add_argument("--sigma-floor", type=float, default=0.10)
    ap.add_argument("--sigma-single", type=float, default=0.25)
    ap.add_argument("--min-rank", type=int, default=500)
    ap.add_argument("--sigma-mult", type=float, default=1.0, help="把 sigma 乘以这个倍数再检验（找出校准所需的放大倍数）")
    a = ap.parse_args()
    bt.SCHOOL_BY = a.school
    data = {}
    for s in a.year:
        y, p = s.split("=", 1)
        data[int(y)] = {k: v for k, v in bt.load(p, a.key).items() if v["full"] and v["rank"] and v["rank"] >= a.min_rank}
    years = sorted(data)
    # 相邻年份整体漂移（对数位次变化的中位数）
    step = {}
    for y0, y1 in zip(years, years[1:]):
        d = [math.log(data[y1][k]["rank"] / data[y0][k]["rank"]) for k in data[y0] if k in data[y1]]
        step[y1] = st.median(d) if d else 0.0
    pits, by_year = [], {}
    for t in years[2:] if len(years) > 2 else years[1:]:
        prev = [y for y in years if y < t]
        if a.drift == "auto":
            past = [step[y] for y in prev if y in step][-3:]
            drift = sum(past) / len(past) if past else 0.0
        else:
            drift = float(a.drift)
        u_t = []
        for k, v in data[t].items():
            hist = [(y, data[y][k]["rank"]) for y in sorted(prev, reverse=True) if k in data[y]]
            if not hist:
                continue
            mu, sigma = predict(hist, drift, t, a.sigma_floor, a.sigma_single)
            sigma *= a.sigma_mult
            u_t.append(phi((math.log(v["rank"]) - mu) / sigma))
        by_year[t] = (drift, u_t)
        pits += u_t
    n = len(pits)
    if not n:
        sys.exit("没有可检验的条目")
    cover = lambda lo, hi: sum(lo <= u <= hi for u in pits) / n
    print(f"## {a.province} 校准检验（{a.key}，sigma×{a.sigma_mult:g}）  样本 {n}")
    print(f"平均 PIT {st.mean(pits):.3f}（0.5 为无偏；> 0.5 表示真实位次比预测更靠后 = 实际更容易，模型偏保守）")
    print(f"50% 区间覆盖 {cover(.25, .75):.1%} | 80% 区间覆盖 {cover(.10, .90):.1%} | 90% 区间覆盖 {cover(.05, .95):.1%}")
    print(f"尾部：真实比 5% 分位还热 {sum(u < .05 for u in pits) / n:.1%}（应为 5%）；比 95% 分位还冷 {sum(u > .95 for u in pits) / n:.1%}（应为 5%）")
    print("\n可靠性（模型说的过线概率 → 实际过线比例）")
    print("| 模型过线概率 | 实际过线比例 |\n|---|---|")
    for p in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        # 考生位次取在预测分布的 (1-p) 分位：过线 ⇔ 真实录取线位次 ≥ 考生位次 ⇔ PIT ≥ 1-p
        obs = sum(u >= 1 - p for u in pits) / n
        print(f"| {p:.0%} | {obs:.1%} |")
    print("\n逐年（漂移为当年使用的估计值）")
    for t, (d, u) in by_year.items():
        if u:
            print(f"- {t}：漂移 {d:+.3f}，样本 {len(u)}，平均 PIT {st.mean(u):.3f}，80% 覆盖 {sum(.1 <= x <= .9 for x in u) / len(u):.1%}")


if __name__ == "__main__":
    main()
