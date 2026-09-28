#!/usr/bin/env python3
"""知衢 · 投档数据逐年回测（仅用 Python 标准库，3.8+）。

用过去的最低录取位次"预测"已经发生的年份，量化：
1. 整体漂移：全省录取位次普遍收紧还是放松（共同冲击，对应 optimize.py 的 rho）
2. 误差大小：去掉突变后的标准差（校准 optimize.py 的 sigma）
3. 结构突变：位次变化超过约 40% 的比例与清单（逐个查原因，记入变化记录）
4. 招生计划弹性：计划数变化能解释多少位次变化
5. 三年及以上时：只看去年 / 近期加权 / 三年平均 / 三年中位数哪个更准，以及位次变化是否均值回归（大小年）

输入：每年一份投档 CSV，UTF-8。必需列 code、plan、rank；另需
  --key group：专业组代码列 group（院校专业组模式，如广东），可选 admit 列判断是否满额
  --key major：专业名称列 major（专业+院校模式，如浙江）；位次为空视为未满额
可选列 name、score。

用法：
  python3 backtest.py --key group --year 2022=gd_2022.csv --year 2023=gd_2023.csv
  python3 backtest.py --key major --year 2022=zj_2022.csv ... --year 2026=zj_2026.csv [--cohort 年份=人数 ...]

注意：跨年匹配依赖代码或专业名称，匹配错误会表现为"突变"；突变清单是待查线索，不是结论。
"""
import argparse
import csv
import math
import re
import statistics as st

JUMP = math.log(1.4)
METRIC = "rank"


def val(v):
    """统一尺度：位次模式取 log(位次)；分数模式取 -分数（数值越大越宽松，与位次同向）。"""
    return math.log(v["rank"]) if METRIC == "rank" else -v["score"]
RECENCY = [1.0, 0.15, 0.05]  # 与 optimize.py 的近期加权一致


def major_key(name):
    """专业名去掉括号内的注释与空白，用于跨年匹配。"""
    s = re.sub(r"[（(][^）)]*[）)]", "", name or "")
    return re.sub(r"\s+", "", s)


def school_key(r):
    """院校名称去掉 [公办] 之类的方括号标注与空白；圆括号里的校区、城市保留。"""
    return re.sub(r"\s+", "", re.sub(r"\[[^\]]*\]", "", r.get("name") or ""))


SCHOOL_BY = "code"


def load(path, key):
    out, dup = {}, set()
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                plan = int(r["plan"]) if (r.get("plan") or "").strip() else None  # 部分省份不公布计划数
            except ValueError:
                plan = None
            rank_s = (r.get("rank") or "").strip()
            admit_s = (r.get("admit") or "").strip()
            if not rank_s.isdigit():
                rank_s = ""
            filled = (plan is None or plan > 0) and (int(admit_s) >= plan if admit_s and plan else True)
            full = bool(rank_s) and filled
            if METRIC == "score":
                full = filled and (r.get("score") or "").strip().replace(".", "", 1).isdigit() and float(r["score"]) > 0  # 0 分表示无人投档
            k2 = major_key(r.get("major")) if key == "major" else (r.get("group") or "").strip()
            k = (r["code"].strip() if SCHOOL_BY == "code" else school_key(r), k2)
            if k in out:
                dup.add(k)
            out[k] = {"name": (r.get("name") or "").strip(),
                      "label": (r.get("major") or r.get("group") or "").strip(),
                      "plan": plan, "rank": int(rank_s) if rank_s else None, "full": full,
                      "score": float(r["score"]) if (r.get("score") or "").strip().replace(".", "", 1).isdigit() and float(r["score"]) > 0 else None}
    for k in dup:  # 同校同名专业（如不同校区）无法唯一匹配，整体剔除
        out.pop(k, None)
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


def summarize(errs):
    stable = [e for e in errs if abs(e) <= JUMP]
    return {"n": len(errs), "bias": st.median(errs), "mae": st.mean(abs(e) for e in errs),
            "sd_stable": st.pstdev(stable) if len(stable) > 1 else float("nan"),
            "mae_stable": st.mean(abs(e) for e in stable) if stable else float("nan"),
            "jump": 1 - len(stable) / len(errs)}


def main():
    ap = argparse.ArgumentParser(description="知衢 · 投档数据逐年回测")
    ap.add_argument("--key", choices=["group", "major"], default="group",
                    help="跨年匹配方式：group=院校+专业组代码；major=院校+专业名称")
    ap.add_argument("--year", action="append", required=True, help="年份=投档CSV，至少两年")
    ap.add_argument("--cohort", action="append", default=[], help="年份=同科类考生总数，用于按百分位折算")
    ap.add_argument("--school", choices=["code", "name"], default="code",
                    help="院校跨年匹配：code=院校代号（默认）；name=院校名称（代号每年重编的省份，如河北）")
    ap.add_argument("--metric", choices=["rank", "score"], default="rank",
                    help="rank=按位次（默认）；score=只有分数、没有一分一段表时按分数，逐年扣除整体漂移")
    ap.add_argument("--jump-points", type=float, default=15, help="分数模式下的突变阈值（分）")
    ap.add_argument("--min-rank", type=int, default=500, help="忽略位次过靠前的组（样本极小、波动失真）")
    ap.add_argument("--top", type=int, default=15, help="列出变化最大的条目数")
    ap.add_argument("--out", help="把相邻年份的逐条残差写成 CSV")
    a = ap.parse_args()

    global METRIC, JUMP, SCHOOL_BY
    METRIC = a.metric
    SCHOOL_BY = a.school
    if METRIC == "score":
        JUMP = a.jump_points
    years = sorted((int(k), v) for k, v in (x.split("=", 1) for x in a.year))
    cohort = {int(k): float(v) for k, v in (x.split("=", 1) for x in a.cohort)}
    if len(years) < 2:
        raise SystemExit("至少需要两年数据")
    ys = [y for y, _ in years]
    data = {y: load(p, a.key) for y, p in years}

    def scaled(y_from, y_to, r):
        if y_from in cohort and y_to in cohort:
            return r * cohort[y_to] / cohort[y_from]
        return r

    def ok(y, k):
        v = data[y].get(k)
        return v is not None and v["full"] and (METRIC == "score" or v["rank"] >= a.min_rank)

    rows_out = []
    print("# 知衢 · 投档回测\n")
    print(f"匹配方式：{'院校 + 专业名称' if a.key == 'major' else '院校 + 专业组代码'}；年份：{', '.join(map(str, ys))}\n")

    # ---- 相邻两年 ----
    for y0, y1 in zip(ys, ys[1:]):
        d0, d1 = data[y0], data[y1]
        pairs = [(k, d0[k], d1[k]) for k in d0.keys() & d1.keys() if ok(y0, k) and ok(y1, k)]
        if not pairs:
            print(f"## {y0} → {y1}：无可匹配条目\n")
            continue
        errs = [val(v1) - val(v0) - (math.log(scaled(y0, y1, 1.0)) if METRIC == "rank" else 0.0) for _, v0, v1 in pairs]
        drift = st.median(errs)
        if METRIC == "score":  # 分数含试卷难度，逐年扣除整体漂移后再比较
            errs = [e - drift for e in errs]
        s = summarize(errs)
        stable = [(k, v0, v1, e) for (k, v0, v1), e in zip(pairs, errs) if abs(e) <= JUMP]
        print(f"## {y0} → {y1}\n")
        print(f"- 两年都存在且满额：{s['n']} 条（{y0} 共 {len(d0)}，{y1} 共 {len(d1)}）")
        if METRIC == "rank":
            print(f"- 整体漂移（对数误差中位数）：{drift:+.3f}，即录取位次普遍{'放松' if drift > 0 else '收紧'}约 {abs(math.expm1(drift)):.1%}")
        else:
            print(f"- 整体漂移：投档分普遍{'下降' if drift > 0 else '上升'} {abs(drift):.1f} 分（含试卷难度变化；以下误差已扣除该漂移）")
        print(f"- 误差：平均绝对误差 {s['mae']:.3f}；去掉突变后标准差 {s['sd_stable']:.3f}")
        print(f"- 结构突变（{'变化 > 40%' if METRIC == 'rank' else f'偏离 > {JUMP:g} 分'}）：{s['jump']:.1%}")
        if s["jump"] > 0.3:
            print("- ⚠ 突变比例异常高，多半是匹配错位：院校代号可能每年重编（试 --school name），或组号含义变了")
        withplan = [p for p in stable if p[1]["plan"] and p[2]["plan"]] if METRIC == "rank" else []
        fit = ols([math.log(v1["plan"] / v0["plan"]) for _, v0, v1, _ in withplan], [e for *_, e in withplan])
        if fit:
            b, se, r2 = fit
            print(f"- 招生计划弹性（去掉突变）：{b:+.3f} ± {se:.3f}，R² = {r2:.3f}（计划翻倍 → 位次约 {math.expm1(b * math.log(2)):+.1%}）")
        if a.top:
            print(f"\n变化最大的 {a.top} 条（待查原因）：\n")
            print(f"| 院校 | 专业/组 | {y0} 位次 | {y1} 位次 | 变化 | 计划 |")
            print("|---|---|---|---|---|---|")
        for (k, v0, v1), e in sorted(zip(pairs, errs), key=lambda p: -abs(p[1]))[: a.top]:
            if METRIC == "rank":
                print(f"| {v1['name']} | {v1['label']} | {v0['rank']} | {v1['rank']} | {math.expm1(e):+.0%} | {v0['plan'] or '-'}→{v1['plan'] or '-'} |")
            else:
                print(f"| {v1['name']} | {v1['label']} | {v0['score']:g} 分 | {v1['score']:g} 分 | {-e:+.0f} 分（已扣漂移） | {v0['plan'] or '-'}→{v1['plan'] or '-'} |")
        print()
        for (k, v0, v1), e in zip(pairs, errs):
            rows_out.append({"from": y0, "to": y1, "code": k[0], "key": k[1], "name": v1["name"],
                             "rank_from": v0["rank"], "rank_to": v1["rank"], "err": round(e, 4),
                             "plan_from": v0["plan"], "plan_to": v1["plan"], "jump": int(abs(e) > JUMP)})

    # ---- 三年及以上：比较预测方法、检验均值回归 ----
    if len(ys) >= 3:
        print("## 预测方法比较（只用目标年之前的数据）\n")
        methods = {"只看去年": [], "去年 + 历史漂移": [], "去年 + 漂移 + 本省自相关修正": [],
                   "近期加权（本工具默认）": [], "近两年平均": [], "近三年平均": [], "近三年中位数": []}
        drifts = {}
        for y0, y1 in zip(ys, ys[1:]):
            e = [val(data[y1][k]) - val(data[y0][k]) for k in data[y1] if ok(y0, k) and ok(y1, k)]
            if e:
                drifts[y1] = st.median(e)
        def cum_drift(y):  # 从首年到 y 年累计的全省漂移
            return sum(drifts.get(z, 0.0) for z in range(ys[0] + 1, y + 1))

        def ar_coef(until):  # 只用 until 年及以前的数据估计"本年变化对上年变化"的系数
            xs_, ys_ = [], []
            for j in range(2, len(ys)):
                b0, b1, b2 = ys[j - 2], ys[j - 1], ys[j]
                if b2 > until:
                    break
                for k in data[b2]:
                    if ok(b0, k) and ok(b1, k) and ok(b2, k):
                        l0, l1, l2 = (val(data[y][k]) - cum_drift(y) for y in (b0, b1, b2))
                        if abs(l1 - l0) <= 2 * JUMP and abs(l2 - l1) <= 2 * JUMP:
                            xs_.append(l1 - l0)
                            ys_.append(l2 - l1)
            f = ols(xs_, ys_)
            return f[0] if f else 0.0

        ar_cache = {}
        for i in range(2, len(ys)):
            t = ys[i]
            hist = ys[max(0, i - 3):i][::-1]  # 最近在前
            for k in data[t]:
                if not ok(t, k) or not all(ok(h, k) for h in hist[:2]):
                    continue
                if METRIC == "rank":
                    logs = [val(data[h][k]) + math.log(scaled(h, t, 1.0)) for h in hist if ok(h, k)]
                else:  # 分数模式：把往年分数按已实现的逐年漂移换算到目标年尺度（试卷难度不可预测，也与位次预测无关）
                    logs = [val(data[h][k]) + sum(drifts.get(y, 0.0) for y in range(h + 1, t + 1)) for h in hist if ok(h, k)]
                actual = val(data[t][k])
                ws = RECENCY[: len(logs)]
                methods["只看去年"].append(actual - logs[0])
                past = [drifts[y] for y in drifts if y < t]  # 只用目标年之前已知的漂移
                if METRIC == "rank":
                    d_hat = st.mean(past) if past else 0.0
                    methods["去年 + 历史漂移"].append(actual - logs[0] - d_hat)
                    if t not in ar_cache:
                        ar_cache[t] = ar_coef(t - 1)
                    last_change = (logs[0] - logs[1]) - drifts.get(hist[0], 0.0)  # 去年相对全省的变化
                    if abs(last_change) > 2 * JUMP:
                        last_change = 0.0
                    methods["去年 + 漂移 + 本省自相关修正"].append(actual - logs[0] - d_hat - ar_cache[t] * last_change)
                methods["近期加权（本工具默认）"].append(actual - sum(w * l for w, l in zip(ws, logs)) / sum(ws))
                methods["近两年平均"].append(actual - st.mean(logs[:2]))
                if len(logs) >= 3:
                    methods["近三年平均"].append(actual - st.mean(logs[:3]))
                    methods["近三年中位数"].append(actual - st.median(logs[:3]))
        print("| 方法 | 样本 | 中位偏差 | 平均绝对误差 | 去掉突变后标准差 | 突变比例 |")
        print("|---|---|---|---|---|---|")
        for m, e in methods.items():
            if e:
                s = summarize(e)
                print(f"| {m} | {s['n']} | {s['bias']:+.3f} | {s['mae']:.3f} | {s['sd_stable']:.3f} | {s['jump']:.1%} |")
        print("\n（前两行和\"近两年平均\"的样本为至少有两年历史的条目；三年方法只含有三年历史的条目，样本更少。）\n")

        print("## 大小年：位次变化是否均值回归\n")
        dx, dy = [], []
        for i in range(2, len(ys)):
            a0, a1, a2 = ys[i - 2], ys[i - 1], ys[i]
            for k in data[a2]:
                if ok(a0, k) and ok(a1, k) and ok(a2, k):
                    # 扣掉逐年的全省整体漂移，只看单个志愿相对全省的变化；否则持续的漂移会伪装成"趋势"
                    l0, l1, l2 = (val(data[y][k]) - sum(drifts.get(z, 0.0) for z in range(ys[0] + 1, y + 1)) for y in (a0, a1, a2))
                    if abs(l1 - l0) <= 2 * JUMP and abs(l2 - l1) <= 2 * JUMP:  # 排除明显的换义
                        dx.append(l1 - l0)
                        dy.append(l2 - l1)
        fit = ols(dx, dy)
        if fit:
            b, se, r2 = fit
            print(f"- 本年变化对上年变化的回归系数：{b:+.3f} ± {se:.3f}（样本 {len(dx)}，R² = {r2:.3f}）")
            if b < -2 * se:
                print(f"- 显著为负：去年位次每偏离 10%，今年平均反向回调约 {abs(b) * 10:.1f}%，存在大小年效应；只看去年会被单年异常带偏。")
            elif b > 2 * se:
                print("- 显著为正：变化有延续性（趋势），近期年份应给更高权重。")
            else:
                print("- 不显著：看不出系统性的大小年或趋势。")
        print()

    print("> 突变清单是线索，不是结论：专业名或组号相同不代表内容相同。只有填报前就能知道的原因，才值得记入变化记录并用于预测。")
    if a.out and rows_out:
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
            w.writeheader()
            w.writerows(rows_out)


if __name__ == "__main__":
    main()
