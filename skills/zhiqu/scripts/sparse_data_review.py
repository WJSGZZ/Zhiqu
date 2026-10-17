#!/usr/bin/env python3
"""知衢 · 缺数据模式检验（回溯研究，不改生产参数）。

方法与判定标准在运行前登记（本地 ROADMAP 第十二节“缺数据模式”），这里照登记实现：
A. 山西：旧高考（文理分科）2022—2024 院校线能否帮助预测 2026 新高考专业组线。
   旧线来自外购内部库，只在 --internal 时读；输出只有汇总指标，不写逐校明细。
B. 数据好的省（山东、河北物理）模拟只剩 1—2 年数据，比较波动倍数用默认 1.0
   和借他省新高考头几年的倍数，对 2026 真实投档线检验单条预测与整张志愿表。

用法（技能目录）：
  python3 scripts/sparse_data_review.py --part B --out-dir data/calibration
  python3 scripts/sparse_data_review.py --part A --internal --out-dir <本地目录>
"""
import argparse
import csv
import math
import os
import random
import re
import sqlite3
import statistics as st

import province_health as ph
import optimize as opt
from evaluate_models import SCALES, score, phi
from evaluate_portfolios import landing

DATA = ph.DATA
INTERNAL = ph.INTERNAL
SEED = 20261017
MULTS = (0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)   # Brier 的虚拟考生位置 = 上一年位次 × 这些倍数
SPECIAL = re.compile("专项|定向|预科")
PRIMARY = {(p, s): (keys[0], sb) for p, s, keys, sb in ph.SERIES}


# ---------- 共用 ----------

def metrics(items):
    """items: [(mu, sigma, actual, base)]，sigma 已乘倍数；base 是 Brier 虚拟位置的基准位次。"""
    if not items:
        return {}
    errs = [(math.log(a) - mu, s) for mu, s, a, _ in items]
    sc = score(errs, 1.0, "normal")
    brier = []
    for mu, s, a, base in items:
        for m in MULTS:
            c = base * m
            brier.append((phi((mu - math.log(c)) / s) - (a >= c)) ** 2)
    return dict(n=len(items), coverage_80=round(sc["coverage_80"], 3), fail_95=round(sc["hot_tail_05"], 3),
                median_abs_err=round(st.median(abs(r) for r, _ in errs), 3), median_bias=round(st.median(r for r, _ in errs), 3),
                nll=round(sc["nll"], 4), brier=round(st.mean(brier), 4))


def item_brier(mu, s, a, base):
    return sum((phi((mu - math.log(base * m)) / s) - (a >= base * m)) ** 2 for m in MULTS) / len(MULTS)


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def boot_ci(stat, units, reps=2000, level=0.975, seed=SEED):
    rng = random.Random(seed)
    vals = sorted(stat([units[rng.randrange(len(units))] for _ in units]) for _ in range(reps))
    lo = vals[int((1 - level) / 2 * reps)]
    hi = vals[min(reps - 1, int((1 + level) / 2 * reps))]
    return round(lo, 4), round(hi, 4)


def steps(data, years):
    out = {}
    for a, b in zip(years, years[1:]):
        common = data[a].keys() & data[b].keys()
        if common:
            out[b] = st.median(math.log(data[b][k]["rank"] / data[a][k]["rank"]) / (b - a) for k in common)
    return out


def predict(data, years, target, key, drift):
    """按生产规则：最近年份在前，缺年留 None，按漂移补到目标年；返回未乘倍数的 (mu, sigma)。"""
    hist = [data[y][key]["rank"] * math.exp(drift * (target - y)) if key in data[y] else None for y in sorted(years, reverse=True)]
    if not any(hist):
        return None
    mu, sigma, _ = opt.model_parameters(hist)
    return mu, sigma


# ---------- A：山西旧高考 ----------

def norm(name):
    return re.sub(r"\s+", "", name or "").replace("（", "(").replace("）", ")")


def last_cum(path):
    with open(path, encoding="utf-8") as f:
        return int(list(csv.DictReader(f))[-1]["cum"])


def old_lines(stem):
    kind = {"physics": "理科", "history": "文科"}[stem]
    out = {}
    for y in (2022, 2023, 2024):
        best = {}
        with open(os.path.join(INTERNAL, "shanxi", f"other_{y}_other.csv"), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["kind"] != kind or not r["batch"].startswith(("本科一批", "本科二批")) or not r["rank"].strip().isdigit():
                    continue
                s = norm(r["name"])
                best[s] = max(best.get(s, 0), int(r["rank"]))
        out[y] = best
    return out


def old_counts(stem):
    """旧体系本科二批（A/B 段）线上累计人数：外购一分一段（内部未核）。"""
    subj = {"physics": "理科", "history": "文科"}[stem]
    db = sqlite3.connect(os.path.join(DATA, "purchased", "purchased.sqlite"))
    rows = db.execute("select year, max(cum) from vendor_yfyd where province='山西' and subject=? and batch='本科二批' group by year",
                      (subj,)).fetchall()
    return dict(rows)


def ols2(rows):
    """y = a + b·x1 + c·x2 的最小二乘，返回 (b, c)。"""
    my, m1, m2 = (st.mean(r[i] for r in rows) for i in range(3))
    s11 = sum((r[1] - m1) ** 2 for r in rows)
    s22 = sum((r[2] - m2) ** 2 for r in rows)
    s12 = sum((r[1] - m1) * (r[2] - m2) for r in rows)
    s1y = sum((r[1] - m1) * (r[0] - my) for r in rows)
    s2y = sum((r[2] - m2) * (r[0] - my) for r in rows)
    d = s11 * s22 - s12 * s12
    return (s22 * s1y - s12 * s2y) / d, (s11 * s2y - s12 * s1y) / d


def school_min(year_data):
    out = {}
    for (school, _), v in year_data.items():
        if SPECIAL.search(v["label"]):
            continue
        s = norm(school)
        out[s] = max(out.get(s, 0), v["rank"])
    return out


def part_a(stem):
    data, _ = ph.load("shanxi", stem, "group", "name")
    d25, d26 = data[2025], data[2026]
    n_new = {y: last_cum(os.path.join(DATA, "shanxi", f"yfyd_{stem}_{y}.csv")) for y in (2025, 2026)}
    n_old = old_counts(stem)
    old = old_lines(stem)
    m25, m26 = school_min(d25), school_min(d26)
    p_old = {y: {s: r / n_old[y] for s, r in old[y].items()} for y in old}
    p25 = {s: r / n_new[2025] for s, r in m25.items()}
    p26 = {s: r / n_new[2026] for s, r in m26.items()}
    shift = {}
    for y in old:   # A1′：去掉新旧体系之间的整体平移
        common = [s for s in p_old[y] if s in p25]
        shift[y] = st.median(p_old[y][s] / p25[s] for s in common) if common else 1.0
    matched = [k for k in d26 if k in d25]
    rows, units = [], {}
    for k in matched:
        s = norm(k[0])
        r25, actual = d25[k]["rank"], d26[k]["rank"]
        has_old = s in p25 and any(s in p_old[y] for y in old)
        hists = {"A0": [r25]}
        if has_old:
            for name, adj in (("A1", {y: 1.0 for y in old}), ("A1p", shift)):
                hists[name] = [r25] + [r25 * p_old[y][s] / p25[s] / adj[y] if s in p_old[y] else None for y in (2024, 2023, 2022)]
        else:
            hists["A1"] = hists["A1p"] = [r25]
        preds = {}
        for name, h in hists.items():
            mu, sigma, _ = opt.model_parameters(h)
            preds[name] = (mu, sigma, actual, r25)
        rows.append((s, has_old, preds))
    out = []
    evalset = [r for r in rows if r[1]]
    for scope, rs in (("有旧数据的组", evalset), ("全部可匹配组", rows)):
        for name in ("A0", "A1", "A1p"):
            m = metrics([p[name] for _, _, p in rs])
            out.append(dict(part="A", series=f"shanxi-{stem}", scope=scope, method=name, **m))
    # 整群自助：Brier 差（变体 − A0），按学校
    by_school = {}
    for s, _, p in evalset:
        by_school.setdefault(s, []).append(p)
    units = list(by_school.values())
    for name in ("A1", "A1p"):
        def diff(sample, name=name):
            tot = n = 0
            for group in sample:
                for p in group:
                    tot += item_brier(*p[name]) - item_brier(*p["A0"])
                    n += 1
            return tot / n
        point = diff(units)
        lo, hi = boot_ci(diff, units)
        out.append(dict(part="A", series=f"shanxi-{stem}", scope="有旧数据的组", method=f"{name}−A0 Brier 差",
                        n=len(evalset), brier=round(point, 5), ci_975=f"[{lo}, {hi}]", n_schools=len(units)))
    # 顺序稳定性（学校级）
    def geo(s):
        xs = [p_old[y][s] for y in old if s in p_old[y]]
        return math.exp(st.mean(math.log(x) for x in xs)) if xs else None
    common = [s for s in p26 if s in p25 and geo(s)]
    pairs = {
        "旧2024 vs 2026": [(p_old[2024][s], p26[s]) for s in p26 if s in p_old[2024]],
        "2025 vs 2026": [(p25[s], p26[s]) for s in p26 if s in p25],
        "旧三年平均 vs 2026": [(geo(s), p26[s]) for s in p26 if geo(s)],
        "旧2024 vs 2025": [(p_old[2024][s], p25[s]) for s in p25 if s in p_old[2024]],
        "旧2023 vs 旧2024": [(p_old[2023][s], p_old[2024][s]) for s in p_old[2024] if s in p_old[2023]],
    }
    for label, ps in pairs.items():
        out.append(dict(part="A", series=f"shanxi-{stem}", scope="学校级", method=f"Spearman {label}", n=len(ps),
                        spearman=round(spearman([a for a, _ in ps], [b for _, b in ps]), 4)))
    inc = [(math.log(geo(s) / p25[s]), math.log(p26[s] / p25[s])) for s in common]
    stat = lambda sample: spearman([a for a, _ in sample], [b for _, b in sample])
    lo, hi = boot_ci(stat, inc)
    out.append(dict(part="A", series=f"shanxi-{stem}", scope="学校级", method="增量 Spearman ln(p旧/p2025) vs ln(p2026/p2025)",
                    n=len(inc), spearman=round(stat(inc), 4), ci_975=f"[{lo}, {hi}]"))
    # 补充（未登记）：登记的增量 Spearman 两边共用 −ln p2025，2025 年的偶然偏差本身就会让它为正；
    # 改用学校级回归 ln p2026 = a + b·ln p2025 + c·ln p旧，c 才是旧数据的增量，另做一次打乱旧数据的对照。
    reg = [(math.log(p26[s]), math.log(p25[s]), math.log(geo(s))) for s in common]
    b, c = ols2(reg)
    lo, hi = boot_ci(lambda smp: ols2(smp)[1], reg)
    rng = random.Random(SEED)
    shuffled = [x for _, _, x in reg]
    rng.shuffle(shuffled)
    out.append(dict(part="A补充", series=f"shanxi-{stem}", scope="学校级", method="回归 ln p2026 ~ ln p2025 + ln p旧：旧的系数 c",
                    n=len(reg), spearman=round(c, 4), ci_975=f"[{lo}, {hi}]",
                    note=f"2025 的系数 b={b:.3f}；旧数据打乱后 c={ols2([(y, x1, x2) for (y, x1, _), x2 in zip(reg, shuffled)])[1]:.3f}"))
    # 补充（未登记，探索）：把这一回归信号当先验——权重 w 只用旧体系内部估（2022、2023 → 2024），波动沿用 A0
    trio = [(math.log(p_old[2024][s]), math.log(p_old[2023][s]), math.log(p_old[2022][s]))
            for s in p_old[2024] if s in p_old[2023] and s in p_old[2022]]
    bo, co = ols2(trio)
    w = co / (bo + co)
    prior = []
    for s, has_old, p in evalset:
        mu0, sg, a_, r25 = p["A0"]
        ps = [math.log(r25 * p_old[y][s] / p25[s] / shift[y]) for y in old if s in p_old[y]]
        prior.append(((1 - w) * mu0 + w * st.mean(ps), sg, a_, r25))
    out.append(dict(part="A补充", series=f"shanxi-{stem}", scope="有旧数据的组", method=f"先验（w={w:.2f}，探索）",
                    **metrics(prior)))
    # 补充（未登记，诊断）：旧线是“学校最低线”，分开看本校最低普通组与其他组；w 固定 0.25（≈ 上面回归的 c），在 2026 上看，不能当留出证据
    for scope, want in (("本校最低普通组", True), ("本校其他普通组", False)):
        base, moved = [], []
        for s, has_old, p in evalset:
            mu0, sg, a_, r25 = p["A0"]
            if s not in m25 or (r25 == m25[s]) != want:
                continue
            ps = st.mean(math.log(p_old[y][s] / p25[s] / shift[y]) for y in old if s in p_old[y])
            base.append(p["A0"])
            moved.append((mu0 + 0.25 * ps, sg, a_, r25))
        for name, items in (("A0", base), ("A0 + 0.25×旧相对位置（诊断）", moved)):
            out.append(dict(part="A补充", series=f"shanxi-{stem}", scope=scope, method=name, **metrics(items)))
    out.append(dict(part="A", series=f"shanxi-{stem}", scope="口径", method="人数与对应率",
                    note=f"新 本科线累计 2025={n_new[2025]} 2026={n_new[2026]}；旧 二批线累计 {dict(sorted(n_old.items()))}；"
                         f"A1′ 整体平移（旧百分位÷2025 百分位中位数）{ {y: round(v, 3) for y, v in sorted(shift.items())} }；"
                         f"2026 可匹配组 {len(rows)}，其中学校有旧线 {len(evalset)}（{len(evalset)/len(rows):.1%}）；"
                         f"2025 学校 {len(m25)}，对上旧 2024 {sum(s in p_old[2024] for s in m25)}"))
    return out


# ---------- B：数据少时怎么定参数 ----------

REFORM = {("zhejiang", "general"): 2017, ("shandong", "general"): 2020, ("shanxi", "physics"): 2025, ("shanxi", "history"): 2025}
for _p in ("hebei", "jiangsu", "hubei", "fujian", "hunan"):
    for _s in ("physics", "history"):
        REFORM[(_p, _s)] = 2021
TARGETS = [("shandong", "general"), ("hebei", "physics")]
_cache = {}


def series(p, s):
    if (p, s) not in _cache:
        key, sb = PRIMARY[(p, s)]
        _cache[(p, s)] = ph.load(p, s, key, sb)[0]
    return _cache[(p, s)]


def early_errors(p, s, n_years):
    """改革头 n_years 年预测下一年的误差 [(残差, 未乘倍数的 sigma)]。"""
    data = series(p, s)
    y1 = REFORM[(p, s)]
    yrs = [y for y in range(y1, y1 + n_years) if y in data]
    target = y1 + n_years
    if len(yrs) < n_years or target not in data:
        return []
    stp = steps(data, yrs)
    if n_years > 1 and not stp:   # 头几年之间对不上（如湖南 2021→2022 组号整体改编），该系列不进参照库
        return []
    drift = st.mean(stp.values()) if n_years > 1 else 0.0
    out = []
    for k, v in data[target].items():
        pr = predict(data, yrs, target, k, drift)
        if pr:
            out.append((math.log(v["rank"]) - pr[0], pr[1]))
    return out


def borrowed_scale(n_years, exclude):
    pools = {ps: early_errors(*ps, n_years) for ps in REFORM if ps[0] != exclude}
    pools = {ps: e for ps, e in pools.items() if e}
    best = min(SCALES, key=lambda x: st.mean(score(e, x, "normal")["nll"] for e in pools.values()))
    return best, pools


def full_scale(data, target):
    years = sorted(y for y in data if y < target)
    stp = steps(data, years)
    errs = []
    for t in years[1:]:
        prev = [y for y in years if y < t]
        known = [stp[y] for y in prev if y in stp][-3:]
        drift = st.mean(known) if known else 0.0
        for k, v in data[t].items():
            pr = predict(data, prev, t, k, drift)
            if pr:
                errs.append((math.log(v["rank"]) - pr[0], pr[1]))
    return min(SCALES, key=lambda x: score(errs, x, "normal")["nll"])


def scenarios(p, s, target=2026):
    data = series(p, s)
    years = sorted(y for y in data if y < target)
    stp = steps(data, years)
    full_drift = st.mean([stp[y] for y in years if y in stp][-3:])
    b1, _ = borrowed_scale(1, p)
    b2, _ = borrowed_scale(2, p)
    d2 = steps(data, [target - 2, target - 1])[target - 1]
    return {
        "全量": (years, full_drift, full_scale(data, target)),
        "S1-默认": ([target - 1], 0.0, 1.0),
        "S1-借用": ([target - 1], 0.0, b1),
        "S2-默认": ([target - 2, target - 1], d2, 1.0),
        "S2-借用": ([target - 2, target - 1], d2, b2),
    }


def item_rows(data, sc, keys, target):
    years, drift, scale = sc
    rows = {}
    for k in keys:
        pr = predict(data, years, target, k, drift)
        if pr:
            rows[k] = (pr[0], pr[1] * scale)
    return rows


def portfolio(p, s, scs, keys, target=2026, rho=0.3, sims=3000):
    data = series(p, s)
    obs = data[target]
    latest = {k: data[target - 1][k]["rank"] for k in keys}
    ranks = sorted(latest.values())
    preds = {name: item_rows(data, sc, keys, target) for name, sc in scs.items()}
    out = []
    for q in (.1, .2, .3, .4, .5, .6, .7, .8, .9):
        rank = ranks[int((len(ranks) - 1) * q)]
        eligible = sorted((k for k in keys if .5 <= latest[k] / rank <= 3), key=lambda k: (latest[k], k))
        size = min(40, len(eligible))
        pool_keys = [eligible[round(i * (len(eligible) - 1) / (size - 1))] for i in range(size)]
        for name, pr in preds.items():
            pool = [dict(key=k, name=data[target - 1][k]["name"], latest=latest[k], mu=pr[k][0], sigma=pr[k][1],
                         u=100 * max(0, min(1, math.log(300000 / latest[k]) / math.log(300000 / 500))),
                         ua=0, majors=[], p_adj=0) for k in pool_keys]
            admit, adjust, masks = opt.simulate(pool, rank, 0, rho, sims, SEED)
            ev = opt.Evaluator(pool, admit, adjust, masks, sims, 0, .05, 4000)
            sa, sd, sm = opt.simulate(pool, rank, 0, rho, sims, SEED, 2.0)
            stress = opt.Evaluator(pool, sa, sd, sm, sims, 0, .05, 4000)
            sel = opt.greedy(ev, len(pool), 10, 4000)
            sel = ev.order(opt.fill_under_stress(ev, stress, sel, len(pool), 10))
            fall, utility, pos = landing(pool, sel, obs, rank)
            eu, risk, _ = ev.evaluate(sel)
            # 落点比 2025 线“最合适”的那格低多少：实际可投进的志愿里效用最高者 − 实得效用
            reachable = [r["u"] for r in pool if rank <= obs[r["key"]]["rank"]]
            out.append(dict(part="B-表", series=f"{p}-{s}", quantile=q, virtual_rank=rank, method=name,
                            actual_fall=fall, landing_position=pos, realized_utility=round(utility, 2) if utility is not None else "",
                            best_reachable_in_pool=round(max(reachable), 2) if reachable else "", predicted_fall=round(risk, 4),
                            predicted_utility=round(eu, 2), safest_p=round(max(phi((r["mu"] - math.log(rank)) / r["sigma"]) for r in (pool[j] for j in sel)), 4)))
    return out


def part_b():
    out = []
    for p, s in TARGETS:
        data = series(p, s)
        scs = scenarios(p, s)
        common = [k for k in data[2026] if k in data[2025] and k in data[2024]]
        s1_all = [k for k in data[2026] if k in data[2025]]
        for name, sc in scs.items():
            pr = item_rows(data, sc, common, 2026)
            items = [(mu, sg, data[2026][k]["rank"], data[2025][k]["rank"]) for k, (mu, sg) in pr.items()]
            out.append(dict(part="B", series=f"{p}-{s}", scope="2024、2025 都有", method=name, drift=round(sc[1], 4),
                            sigma_scale=sc[2], **metrics(items)))
            if name.startswith("S1") or name == "全量":
                pr = item_rows(data, sc, s1_all, 2026)
                items = [(mu, sg, data[2026][k]["rank"], data[2025][k]["rank"]) for k, (mu, sg) in pr.items()]
                out.append(dict(part="B", series=f"{p}-{s}", scope="2025 有即可", method=name, drift=round(sc[1], 4),
                                sigma_scale=sc[2], **metrics(items)))
        out += portfolio(p, s, scs, common)
    # 补充（未登记，描述性）：真正数据薄的山西，只有 2025 一年时的整张表
    for stem, own in (("physics", 1.3), ("history", 0.9)):
        data = series("shanxi", stem)
        keys = [k for k in data[2026] if k in data[2025]]
        scs = {"S1-默认": ([2025], 0.0, 1.0), "S1-借用": ([2025], 0.0, borrowed_scale(1, "shanxi")[0]),
               "事后本省倍数": ([2025], 0.0, own), "保守 2.0": ([2025], 0.0, 2.0)}
        for r in portfolio("shanxi", stem, scs, keys):
            r["part"] = "B补充-表"
            out.append(r)
    # 参照库与留一省检验（描述性）
    for n_years in (1, 2):
        for ps in REFORM:
            own = early_errors(*ps, n_years)
            if not own:
                continue
            b, _ = borrowed_scale(n_years, ps[0])
            own_best = min(SCALES, key=lambda x: score(own, x, "normal")["nll"])
            out.append(dict(part="B-参照", series=f"{ps[0]}-{ps[1]}", scope=f"改革头 {n_years} 年 → 第 {n_years+1} 年",
                            method="留一省", n=len(own), sigma_scale=b, own_best_scale=own_best,
                            nll=round(score(own, b, "normal")["nll"], 4), nll_default=round(score(own, 1.0, "normal")["nll"], 4),
                            coverage_80=round(score(own, b, "normal")["coverage_80"], 3),
                            coverage_80_default=round(score(own, 1.0, "normal")["coverage_80"], 3),
                            fail_95=round(score(own, b, "normal")["hot_tail_05"], 3),
                            fail_95_default=round(score(own, 1.0, "normal")["hot_tail_05"], 3)))
    # 给山西 2027（已有 2 年、1 个检验年）的借用倍数：参照“改革头 2 年”，排除山西本身
    out.append(dict(part="B-参照", series="shanxi", scope="2027 借用倍数（头 2 年 → 第 3 年，排除山西）", method="借用",
                    sigma_scale=borrowed_scale(2, "shanxi")[0]))
    out.append(dict(part="B-参照", series="henan", scope="借用倍数（头 1 年 → 第 2 年，排除河南）", method="借用",
                    sigma_scale=borrowed_scale(1, "henan")[0]))
    return out


FIELDS = ["part", "series", "scope", "method", "n", "drift", "sigma_scale", "own_best_scale", "coverage_80", "coverage_80_default",
          "fail_95", "fail_95_default", "median_abs_err", "median_bias", "nll", "nll_default", "brier", "ci_975", "n_schools",
          "spearman", "quantile", "virtual_rank", "actual_fall", "landing_position", "realized_utility", "best_reachable_in_pool",
          "predicted_fall", "predicted_utility", "safest_p", "note"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--part", choices=["A", "B"], required=True)
    ap.add_argument("--internal", action="store_true", help="A 部分需要：读本地外购内部库（内部未核，不提交）")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    if a.part == "A":
        if not a.internal:
            ap.error("A 部分要读外购内部库，须加 --internal；结果只放本地")
        rows = part_a("physics") + part_a("history")
        path = os.path.join(a.out_dir, "sparse_review_A_internal.csv")
    else:
        rows = part_b()
        path = os.path.join(a.out_dir, "sparse_review_2026.csv")
    os.makedirs(a.out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        if not r["part"].endswith("表"):
            print({k: v for k, v in r.items() if v not in ("", None)})
    print(path)


if __name__ == "__main__":
    main()
