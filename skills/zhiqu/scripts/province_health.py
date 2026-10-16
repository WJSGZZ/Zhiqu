#!/usr/bin/env python3
"""知衢 · 十省可信度体检：逐省、逐科类、逐年的样本外检验与评级（研究输出，不改生产参数）。

方法与评级标准在运行前登记（本地 ROADMAP 第十二节“十省可信度体检”），这里照登记实现：
- 对每个目标年，只用此前年份估计漂移（最近三次相邻变化中位数的平均）和波动倍数
  （在 0.7—2.0 中选此前误差 NLL 最小者，无此前误差用 1.0），用生产同一套 v2 参数函数预测；
- 指标：80% 区间覆盖率、比 5% 分位还热的比例（“说 95% 稳的实际失败率”）、中位偏差、匹配率、突变比例；
- 方向共振（只在有专业名的省份算）：各方向相对全省的位次变化中位数，与模型共同因子标准差对比；
- 评级 A/B/C/D 按登记的阈值机械给出。

用法（技能目录）：
  python3 scripts/province_health.py --out data/calibration/province_health.csv
"""
import argparse
import csv
import math
import os
import re
import statistics as st

import backtest as bt
from evaluate_models import SCALES, score
from optimize import model_parameters

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# (省, 科类文件前缀, 匹配方式（第一个为主）, 院校匹配)
SERIES = [
    ("zhejiang", "general", ["major"], "code"),
    ("shandong", "general", ["major"], "code"),
    ("hebei", "physics", ["major"], "name"),
    ("hebei", "history", ["major"], "name"),
    ("jiangsu", "physics", ["major", "group"], "code"),
    ("jiangsu", "history", ["major", "group"], "code"),
    ("hubei", "physics", ["major", "group"], "code"),
    ("hubei", "history", ["major", "group"], "code"),
    ("fujian", "physics", ["major", "group"], "name"),   # 福建院校代码每年重编，按校名匹配
    ("fujian", "history", ["major", "group"], "name"),
    ("hunan", "physics", ["group"], "code"),   # 湖南表的 major 列是组名（如“第104组”），不是选科要求，只能按组号
    ("hunan", "history", ["group"], "code"),
    ("guangdong", "physics", ["group"], "code"),
    ("guangdong", "history", ["group"], "code"),
    ("shanxi", "physics", ["group"], "name"),    # 山西院校代码每年重编；表中无选科要求，只能按组号
    ("shanxi", "history", ["group"], "name"),
]
NO_TABLE = [("henan", "physics", "无官方投档表"), ("henan", "history", "无官方投档表")]
MAJOR_NAME_PROVINCES = {"zhejiang", "shandong", "hebei"}  # major 列是专业名；其他省的 major 列是选科要求
KEY_LABEL = {"major": "院校+专业名", "group": "院校+组号", "req": "院校+选科要求"}
DIRECTIONS = {
    "电气": "电气|电力|智能电网|能源互联网", "自动化": "自动化|测控|机器人|智能制造",
    "电子信息": "电子信息|通信|微电子|集成电路|电子科学|光电", "计算机": "计算机|软件|人工智能|数据科学|网络空间|信息安全|物联网",
    "机械": "机械|车辆|材料成型", "土木建筑": "土木|建筑|城乡规划|工程管理|给排水",
    "医学": "临床|口腔|医学|护理|药学|中医", "师范教育": "师范|教育", "经管": "经济|金融|会计|财务|管理|贸易|营销",
    "外语": "英语|日语|翻译|外语|商务英语", "法学": "法学|知识产权",
}
JUMP = math.log(1.4)
RHO = 0.3


INTERNAL = os.path.join(DATA, "purchased", "internal_cutoffs")  # 本地内部库（外购，不提交）；只在 --internal 时读


def load(province, stem, key, school_by, internal=False):
    bt.SCHOOL_BY, bt.METRIC = school_by, "rank"
    folder = os.path.join(DATA, province)
    paths = {int(m.group(1)): os.path.join(folder, n) for n in os.listdir(folder)
             if (m := re.fullmatch(stem + r"_(\d{4})\.csv", n))}
    extra = os.path.join(INTERNAL, province)
    if internal and key == "group" and os.path.isdir(extra):  # 外购的选科要求写法与官方不同，只能按组号补
        for n in os.listdir(extra):
            m = re.fullmatch(stem + r"_(\d{4})\.csv", n)
            if m and int(m.group(1)) not in paths:
                paths[int(m.group(1))] = os.path.join(extra, n)
    data, labels = {}, {}
    for year in sorted(paths):
        rows = bt.load(paths[year], key)
        if key == "major" and province not in MAJOR_NAME_PROVINCES:
            rows = {k: v for k, v in rows.items() if k[1]}  # 选科要求为空的条目无法按选科匹配
        usable = {k: v for k, v in rows.items() if v["full"] and v["rank"] and v["rank"] >= 500}
        if usable:
            data[year] = usable
            labels[year] = {k: v["label"] for k, v in usable.items()}
    return data, labels


def yearly(data):
    """每个目标年：只用此前年份的漂移，返回 (drift, [(残差, sigma, 上年位次或 None, 本年位次)])。"""
    years = sorted(data)
    steps = {}
    for a, b in zip(years, years[1:]):
        ds = [math.log(data[b][k]["rank"] / data[a][k]["rank"]) / (b - a) for k in data[a].keys() & data[b].keys()]
        if ds:
            steps[b] = st.median(ds)
    out = {}
    for target in years[1:]:
        prev = [y for y in years if y < target]
        known = [steps[y] for y in prev if y in steps][-3:]
        drift = st.mean(known) if known else 0.0
        errs = []
        for k, v in data[target].items():
            hist = [data[y][k]["rank"] * math.exp(drift * (target - y)) if k in data[y] else None for y in prev[::-1]]
            if not any(hist):
                continue
            mu, sigma, _ = model_parameters(hist)
            last = data[prev[-1]][k]["rank"] if k in data[prev[-1]] else None
            errs.append((math.log(v["rank"]) - mu, sigma, last, v["rank"]))
        out[target] = (drift, errs)
    return out


def next_params(province, stem, key, school_by):
    """下一年（最新年 + 1）的生产参数，按同一规则：漂移取最近三次相邻变化中位数的平均，倍数在 SCALES 中按全部检验误差的 NLL 选。"""
    data, _ = load(province, stem, key, school_by)
    years = sorted(data)
    if len(years) < 2:
        return None
    steps = [st.median(math.log(data[b][k]["rank"] / data[a][k]["rank"]) / (b - a) for k in data[a].keys() & data[b].keys())
             for a, b in zip(years, years[1:]) if data[a].keys() & data[b].keys()]
    errs = [(r, s) for _, (_, es) in yearly(data).items() for r, s, _, _ in es]
    scale = min(SCALES, key=lambda x: score(errs, x, "normal")["nll"]) if errs else 1.0
    return dict(target=years[-1] + 1, drift=round(st.mean(steps[-3:]), 4), sigma_scale=scale, n_errors=len(errs))


def pits(errs, scale):
    from evaluate_models import phi
    return [phi(r / (s * scale)) for r, s, _, _ in errs]


def direction_shift(data, labels, a, b):
    common = data[a].keys() & data[b].keys()
    ch = {k: math.log(data[b][k]["rank"] / data[a][k]["rank"]) for k in common}
    if len(ch) < 50:
        return None
    overall = st.median(ch.values())
    best = None
    for name, pat in DIRECTIONS.items():
        xs = [v - overall for k, v in ch.items() if re.search(pat, labels[b].get(k, ""))]
        if len(xs) >= 20:
            m = st.median(xs)
            if best is None or abs(m) > abs(best[1]):
                best = (name, m, len(xs))
    return best


def grade(summary, key, n_years, n_scaled):
    if n_years == 0:
        return "D"
    cov, fail, worst, match = summary["coverage_80"], summary["fail_95"], summary["worst_fail_95"], summary["match_rate"]
    if (key == "major" and n_years >= 3 and n_scaled >= 2 and 0.72 <= cov <= 0.90 and fail <= 0.07
            and worst <= 0.15 and match >= 0.5):
        return "A"
    if n_years >= 2 and 0.60 <= cov <= 0.95 and fail <= 0.12:
        return "B"
    return "C"


def review(province, stem, key, school_by, internal=False):
    data, labels = load(province, stem, key, school_by, internal)
    rows, pooled, worst = [], [], 0.0
    yr = yearly(data)
    n_scaled = 0
    sigmas_all = []
    for target, (drift, errs) in sorted(yr.items()):
        if not errs:
            continue
        prior = [(r, s) for y, (_, es) in yr.items() if y < target for r, s, _, _ in es]
        if prior:
            scale = min(SCALES, key=lambda x: score(prior, x, "normal")["nll"])
            n_scaled += 1
        else:
            scale = 1.0
        sc = score([(r, s) for r, s, _, _ in errs], scale, "normal")
        ps = pits(errs, scale)
        pooled += ps
        fail = sum(u < 0.05 for u in ps) / len(ps)
        worst = max(worst, fail)
        jumps = [abs(math.log(now / last)) > JUMP for _, _, last, now in errs if last]
        sig = st.median(s * scale for _, s, _, _ in errs)
        sigmas_all.append(sig)
        prev_year = max(y for y in data if y < target)
        d = direction_shift(data, labels, prev_year, target) if province in MAJOR_NAME_PROVINCES else None
        rows.append(dict(record="year", target_year=target, n=len(errs), match_rate=round(len(errs) / len(data[target]), 3),
                         drift=round(drift, 4), sigma_scale=scale, scale_out_of_sample=int(bool(prior)),
                         coverage_80=round(sc["coverage_80"], 3), fail_95=round(fail, 3),
                         median_bias=round(st.median(r for r, _, _, _ in errs), 3), mutation=round(sum(jumps) / len(jumps), 3) if jumps else "",
                         common_sd=round(math.sqrt(RHO) * sig, 3),
                         max_direction=f"{d[0]}（{d[2]} 条）" if d else "", max_direction_shift=round(d[1], 3) if d else ""))
    n_years = len(rows)
    if pooled:
        summ = dict(coverage_80=sum(0.1 <= u <= 0.9 for u in pooled) / len(pooled), fail_95=sum(u < 0.05 for u in pooled) / len(pooled),
                    worst_fail_95=worst, match_rate=st.mean(r["match_rate"] for r in rows))
        g = grade(summ, key, n_years, n_scaled)
        if key == "group" and g == "A":
            g = "B"
        rows.append(dict(record="pooled", target_year="+".join(str(r["target_year"]) for r in rows if r["record"] == "year"),
                         n=len(pooled), match_rate=round(summ["match_rate"], 3), coverage_80=round(summ["coverage_80"], 3),
                         fail_95=round(summ["fail_95"], 3), worst_fail_95=round(worst, 3), years_tested=n_years,
                         years_scaled_out_of_sample=n_scaled, grade=g))
    else:
        rows.append(dict(record="pooled", n=0, years_tested=0, years_scaled_out_of_sample=0, grade="D"))
    for r in rows:
        label = KEY_LABEL["req" if key == "major" and province not in MAJOR_NAME_PROVINCES else key]
        r.update(province=province, category=stem, key=label, years_available="+".join(map(str, sorted(data))))
    return rows


FIELDS = ["province", "category", "key", "years_available", "record", "target_year", "n", "match_rate", "drift", "sigma_scale",
          "scale_out_of_sample", "coverage_80", "fail_95", "worst_fail_95", "median_bias", "mutation", "common_sd",
          "max_direction", "max_direction_shift", "years_tested", "years_scaled_out_of_sample", "grade"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--internal", action="store_true",
                    help="官方缺的年份用本地内部库（外购，内部未核）补，只按组号；结果须标明，不替换正式评级")
    a = ap.parse_args()
    rows = []
    for province, stem, keys, school_by in SERIES:
        for key in keys:
            rows += review(province, stem, key, school_by, a.internal)
    for province, stem, why in NO_TABLE:
        rows.append(dict(province=province, category=stem, key="", record="pooled", n=0, years_tested=0, grade="D",
                         years_available=why))
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("| 省 | 科类 | 匹配 | 年份 | 检验年 | 合并覆盖80% | 说95%稳的失败率 | 最差一年 | 匹配率 | 评级 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["record"] == "pooled":
            pct = lambda x: f"{100*x:.1f}%" if isinstance(x, float) else ""
            print(f"| {r['province']} | {r['category']} | {r.get('key','')} | {r.get('years_available','')} | {r.get('years_tested','')} | "
                  f"{pct(r.get('coverage_80'))} | {pct(r.get('fail_95'))} | {pct(r.get('worst_fail_95'))} | {pct(r.get('match_rate'))} | {r['grade']} |")


if __name__ == "__main__":
    main()
