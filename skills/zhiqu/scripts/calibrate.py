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
import csv
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as bt  # noqa: E402
from optimize import RECENCY_WEIGHTS, JUMP_WARN, model_parameters  # noqa: E402


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def predict(hist, drift, target, sigma_floor, sigma_single, shrink=None, gamma=0.0, ref=30000, jump_c=1.0):
    """hist: [(year, rank)]，近的在前。与 optimize.load_candidates 相同的规则。
    可选修正（用于检验，默认关闭）：shrink=(先验波动, 等效年数) 把少量年份估出的波动向先验收缩；
    gamma>0 时位次越靠前波动越大（乘以 (ref/位次)^gamma）；jump_c<1 时缩小跳变放大的幅度。"""
    if shrink or gamma or jump_c != 1.0:
        return predict_v2(hist, drift, target, sigma_floor, sigma_single, shrink, gamma, ref, jump_c)
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


def predict_v2(hist, drift, target, sigma_floor, sigma_single, shrink, gamma, ref, jump_c):
    pts = [(k, math.log(r) + drift * (target - y)) for k, (y, r) in enumerate(hist)]
    ws = [RECENCY_WEIGHTS[min(k, len(RECENCY_WEIGHTS) - 1)] for k, _ in pts]
    logs = [l for _, l in pts]
    mu = sum(w * l for w, l in zip(ws, logs)) / sum(ws)
    if len(logs) >= 2:
        var = st.variance(logs)
        if shrink:
            prior, k0 = shrink
            n1 = len(logs) - 1
            var = (n1 * var + k0 * prior ** 2) / (n1 + k0)
        sigma = max(math.sqrt(var), sigma_floor)
        jumps = [abs(logs[k] - logs[k + 1]) for k in range(len(logs) - 1)]
        if max(jumps) > JUMP_WARN:
            sigma = max(sigma, jump_c * max(jumps))
    else:
        sigma = sigma_single
    if gamma:
        sigma *= (ref / hist[0][1]) ** gamma
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
    ap.add_argument("--by", choices=["none", "level", "plan", "hist", "jump"], default="none",
                    help="分档校准：level=位次段三等分，plan=计划人数，hist=历史年数，jump=历史上是否有过大跳变")
    ap.add_argument("--sigma-rule", choices=["v2", "legacy"], default="v2", help="与正式预测一致，默认 v2；旧结果重现用 legacy")
    ap.add_argument("--out", help="逐年校准结果 CSV（包含口径和漂移，无自动调参）")
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
        d = [math.log(data[y1][k]["rank"] / data[y0][k]["rank"]) / (y1-y0) for k in data[y0] if k in data[y1]]
        step[y1] = st.median(d) if d else 0.0
    pits, by_year, bins = [], {}, {}
    for t in years[2:] if len(years) > 2 else years[1:]:
        prev = [y for y in years if y < t]
        if a.drift == "auto":
            past = [step[y] for y in prev if y in step][-3:]
            drift = sum(past) / len(past) if past else 0.0
        else:
            drift = float(a.drift)
        u_t = []
        cuts = sorted(math.log(v["rank"]) for y in prev[-1:] for v in data[y].values())
        if not cuts:
            continue
        t1, t2 = cuts[len(cuts) // 3], cuts[2 * len(cuts) // 3]
        for k, v in data[t].items():
            hist = [(y, data[y][k]["rank"]) for y in sorted(prev, reverse=True) if k in data[y]]
            if not hist:
                continue
            slots = [data[y][k]["rank"] * math.exp(drift * (t - y)) if k in data[y] else None
                     for y in sorted(prev, reverse=True)]
            mu, sigma, _ = model_parameters(slots, a.sigma_floor, a.sigma_single, a.sigma_mult, a.sigma_rule)
            u = phi((math.log(v["rank"]) - mu) / sigma)
            u_t.append(u)
            if a.by != "none":
                if a.by == "level":
                    lr = math.log(hist[0][1])
                    b = "位次靠前 1/3" if lr < t1 else ("位次中间 1/3" if lr < t2 else "位次靠后 1/3")
                elif a.by == "plan":
                    pl = data[hist[0][0]][k].get("plan")  # 目标年的投档表计划可能含追加，不能用作事前分档
                    b = "计划未知" if not pl else ("计划 ≤5" if pl <= 5 else ("计划 6–20" if pl <= 20 else "计划 >20"))
                elif a.by == "hist":
                    b = f"历史 {min(len(hist), 3)}{'+' if len(hist) >= 3 else ''} 年"
                else:
                    ls = [math.log(r) for _, r in hist]
                    b = "有过 >40% 跳变" if len(ls) > 1 and max(abs(x - y) for x, y in zip(ls, ls[1:])) > JUMP_WARN else "历史平稳"
                bins.setdefault(b, []).append(u)
        by_year[t] = (drift, u_t)
        pits += u_t
    n = len(pits)
    if not n:
        sys.exit("没有可检验的条目")
    cover = lambda lo, hi: sum(lo <= u <= hi for u in pits) / n
    print(f"## {a.province} 校准检验（{a.key}，{a.sigma_rule}，sigma×{a.sigma_mult:g}）  样本 {n}")
    if a.key == "group":
        print("⚠ 按组号对应的检验仅供探索；未核实跨年组组成，不能据此宣称正式录取概率已校准")
    print(f"平均 PIT {st.mean(pits):.3f}（0.5 为无偏；> 0.5 表示真实位次比预测更靠后 = 实际更容易，模型偏保守）")
    print(f"50% 区间覆盖 {cover(.25, .75):.1%} | 80% 区间覆盖 {cover(.10, .90):.1%} | 90% 区间覆盖 {cover(.05, .95):.1%}")
    print(f"尾部：真实比 5% 分位还热 {sum(u < .05 for u in pits) / n:.1%}（应为 5%）；比 95% 分位还冷 {sum(u > .95 for u in pits) / n:.1%}（应为 5%）")
    print("\n可靠性（模型说的过线概率 → 实际过线比例）")
    print("| 模型过线概率 | 实际过线比例 |\n|---|---|")
    for p in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        # 考生位次取在预测分布的 (1-p) 分位：过线 ⇔ 真实录取线位次 ≥ 考生位次 ⇔ PIT ≥ 1-p
        obs = sum(u >= 1 - p for u in pits) / n
        print(f"| {p:.0%} | {obs:.1%} |")
    if bins:
        print(f"\n分档（{a.by}）")
        print("| 档 | 样本 | 平均 PIT | 80% 覆盖 | 比 5% 分位还热 | 比 95% 分位还冷 |\n|---|---|---|---|---|---|")
        for b, us in sorted(bins.items()):
            m = len(us)
            print(f"| {b} | {m} | {st.mean(us):.3f} | {sum(.1 <= x <= .9 for x in us) / m:.1%} | {sum(x < .05 for x in us) / m:.1%} | {sum(x > .95 for x in us) / m:.1%} |")
    print("\n逐年（漂移为当年使用的估计值）")
    for t, (d, u) in by_year.items():
        if u:
            print(f"- {t}：漂移 {d:+.3f}，样本 {len(u)}，平均 PIT {st.mean(u):.3f}，80% 覆盖 {sum(.1 <= x <= .9 for x in u) / len(u):.1%}")

    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            fields = ["province", "target_year", "key", "school", "sigma_rule", "sigma_mult", "drift", "n", "mean_pit", "coverage_80", "tail_hot_05", "matching_status"]
            w = csv.DictWriter(f, fieldnames=fields,lineterminator="\n")
            w.writeheader()
            for t, (d, us) in by_year.items():
                if us:
                    w.writerow(dict(province=a.province, target_year=t, key=a.key, school=a.school,
                                    sigma_rule=a.sigma_rule, sigma_mult=a.sigma_mult, drift=d, n=len(us),
                                    mean_pit=st.mean(us), coverage_80=sum(.1 <= x <= .9 for x in us) / len(us),
                                    tail_hot_05=sum(x < .05 for x in us) / len(us),
                                    matching_status="group_number_exploratory" if a.key == "group" else "major_name"))


if __name__ == "__main__":
    main()
