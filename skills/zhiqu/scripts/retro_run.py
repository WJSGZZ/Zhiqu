#!/usr/bin/env python3
"""知衢 · 回溯样板的多档位次复算：只用目标年以前的数据出志愿表，再用目标年真实投档线判定。

读取案例目录里的 retro_config.json（事前登记的人物、位次档、筛选条件、打分量表、模型参数），
对每一档位次依次：pool.py 生成候选 → 剔除校区所在地误配 → rank.py 预测 → 按量表打分 →
preferences.py 计分 → optimize.py 选表 → retro_judge.py 判定。中间文件写到 <案例>/retro_ranks/<位次>/，
汇总写 <案例>/retro_ranks.csv。目标年投档表只在判定这一步读取。

两种打分：沿用已打分的人物表（persona_attributes，R01），或按事前登记的打分规则（scales）：
学校分由本省最近一年各校录取位次中位数换算（社会认可度），专业、城市、前景按规则表，
都写进 basis。位次可直接登记（ranks），也可登记分数（score），用目标年官方一分一段表换算。

用法（技能目录）：
  python3 scripts/retro_run.py examples/2026-GK-R01
"""
import argparse
import csv
import json
import math
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import retro_judge  # noqa: E402
from rank import Table  # noqa: E402

FIELDS = ["id", "name", "school_score", "major_score", "city_score", "outlook_score", "direction", "basis"]


def run(*cmd):
    p = subprocess.run([sys.executable, *cmd], cwd=SKILL, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(p.stderr or p.stdout)
    return p.stdout


def read(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path, rows, fields=None):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def base(major):
    return re.sub(r"[（(].*$", "", major).strip()


def series_path(cfg, y):
    return f"data/{cfg['province']}/{cfg.get('series', 'general')}_{y}.csv"


def first(rules, text):
    for rule in rules:
        if re.search(rule[0], text):
            return rule
    return None


def school_prestige(cfg):
    """学校分：本省最近一年该校各条目录取位次的中位数（社会认可度）。按位次的对数线性换到量表区间，
    两端取全部学校的 2% 与 98% 分位，超出的记端点；用对数是为了让头部名校之间仍拉得开。"""
    lo, hi = cfg["scales"]["school"].get("range", [3, 10])
    by = {}
    for r in read(SKILL / series_path(cfg, cfg["data_years"][-1])):
        if (r.get("rank") or "").strip():
            by.setdefault(r["name"].strip() if cfg.get("school_key") == "name" else r["code"].strip(), []).append(float(r["rank"]))
    med = {k: sorted(v)[len(v) // 2] for k, v in by.items()}
    logs = sorted(math.log(v) for v in med.values())
    top, bottom = logs[int(len(logs) * .02)], logs[int(len(logs) * .98)]
    score = lambda v: hi - (hi - lo) * min(1, max(0, (math.log(v) - top) / (bottom - top)))
    return {k: (round(score(v) * 2) / 2, v) for k, v in med.items()}


def scale_row(row, cfg, prestige):
    """按事前登记的规则打分；规则没有覆盖的返回 None（应在事前补进规则，不临时打分）。"""
    sc = cfg["scales"]
    s, m = row["name"].split("·", 1)
    key = s if cfg.get("school_key") == "name" else row["code"]
    if key not in prestige:
        return None
    ss, med = prestige[key]
    why = f"本省 {cfg['data_years'][-1]} 年该校录取位次中位数约 {med:,.0f}"
    adj = first(sc["school"].get("adjust", []), s)
    if adj:
        ss, why = min(10, max(0, ss + adj[1])), why + f"，{adj[2]}（{adj[1]:+g}）"
    target = m if cfg["key"] == "major" else (row.get("requirement") or "")
    rule = first(sc["major"], target)
    if not rule:
        return None
    ms, d, mb = rule[1], rule[2], rule[3]
    city = sc["city"].get(row["city"])
    if city is None:
        city = sc["city"].get("_本省" if row["province"] == sc.get("home") else "_外省")
    if city is None:
        return None
    fmt = lambda x: f"{float(x):g}"
    return dict(id=row["id"], name=row["name"], school_score=fmt(ss), major_score=fmt(ms), city_score=fmt(city),
                outlook_score=f"{cfg['outlook_default'][d]:.1f}", direction=d,
                basis=f"学校：{why}；专业：{mb}；前景：方向级默认（{cfg['direction_names'][d]}）；城市：{row['city']}")


def auto_drift(cfg):
    """只用登记的往年数据：相邻两年同一条目位次对数比的中位数，取最近至多三步的平均；只有一年为 0。"""
    data = {}
    for y in cfg["data_years"]:
        d = {}
        for r in read(SKILL / series_path(cfg, y)):
            if (r.get("rank") or "").strip():
                d.setdefault(((r["name"] if cfg.get("school_key") == "name" else r["code"]).strip(),
                              (r.get("major") if cfg["key"] == "major" else r.get("group") or "").strip()), []).append(float(r["rank"]))
        data[y] = {k: v[0] for k, v in d.items() if len(v) == 1}
    steps = []
    years = cfg["data_years"]
    for a, b in zip(years, years[1:]):
        ds = sorted(math.log(data[b][k] / data[a][k]) / (b - a) for k in data[a].keys() & data[b].keys())
        if ds:
            steps.append(ds[len(ds) // 2])
    return round(sum(steps[-3:]) / len(steps[-3:]), 4) if steps else 0.0


def resolve_ranks(cfg):
    if "score" in cfg:
        t = Table(str(SKILL / cfg["yfyd"]))
        return [t.rank_of(cfg["score"])[1]]
    return cfg["ranks"]


def persona_tables(attrs):
    school, major = {}, {}
    for r in attrs:
        s, m = r["name"].split("·", 1)
        school.setdefault(s, (r["school_score"], r["city_score"], r["basis"].split("；专业：")[0], r["basis"].split("城市：")[-1]))
        major.setdefault(base(m), (r["major_score"], r["direction"], r["basis"].split("专业：")[1].split("；")[0]))
    return school, major


def score_row(row, cfg, by_id, school, major):
    """返回打分行；量表里没有的返回 None（应在事前补进量表，不临时打分）。"""
    if row["id"] in by_id:
        a = dict(by_id[row["id"]])
        a["basis"] += "（沿用 S01 原分）"
        return a
    s, m = row["name"].split("·", 1)
    if s in school:
        ss, cs, sb, cb = school[s]
        src_s = "沿用 S01 同校"
    elif s in cfg["school"] and row["city"] in cfg["city"]:
        ss, why = cfg["school"][s]
        cs, sb, cb, src_s = cfg["city"][row["city"]], f"学校：公办；{why}", row["city"], "回溯新增，按 S01 量表人工"
    else:
        return None
    b = base(m)
    if b in major:
        ms, d, mb = major[b]
        src_m = "沿用 S01 同专业名"
    elif b in cfg["major"]:
        ms, d = cfg["major"][b]
        mb, src_m = f"{cfg['direction_names'][d]}（{b}）", "回溯新增，按 S01 量表人工"
    else:
        return None
    fmt = lambda x: f"{float(x):g}"
    return dict(id=row["id"], name=row["name"], school_score=fmt(ss), major_score=fmt(ms), city_score=fmt(cs),
                outlook_score=f"{cfg['outlook_default'][d]:.1f}", direction=d,
                basis=f"{sb}；专业：{mb}；前景：方向级默认（回溯未调研该校）；城市：{cb}（学校与城市：{src_s}；专业：{src_m}）")


def one_rank(case, cfg, R, by_id, school, major, prestige=None, judge=True):
    out = case / "retro_ranks" / str(R)
    out.mkdir(parents=True, exist_ok=True)
    rel = lambda p: str(Path(p).resolve().relative_to(SKILL))
    lo, hi = cfg.get("band_override", {}).get(str(R)) or [int(R * cfg["band"][0]), int(R * cfg["band"][1])]
    years = [a for y in cfg["data_years"] for a in ("--year", f"{y}={series_path(cfg, y)}")]
    opts = ["--school", cfg.get("school_key", "code")]
    if cfg.get("public", True):
        opts.append("--public")
    for k in ("match_major", "exclude_major", "match", "exclude", "in_provinces", "in_province"):
        if k in cfg:
            opts += [f"--{k.replace('_', '-')}", cfg[k]]
    run("scripts/pool.py", *years, "--key", cfg["key"], *opts, "--rank-min", str(lo), "--rank-max", str(hi),
        "--out", rel(out / "pool_raw.csv"))
    raw = read(out / "pool_raw.csv")
    # 校区与名单所在地不符的剔除；不按公办筛选时，教育部名单匹配不到的院校（所在地、办学性质不明）也剔除
    keep = [r for r in raw if not re.search("校区括号.*不符", r["note"]) and r.get("province") != "未知"]
    write(out / "pool_manual.csv", keep)
    p = cfg["predict"]
    drift = auto_drift(cfg) if p["drift"] == "auto" else p["drift"]
    run("scripts/rank.py", "predict", rel(out / "pool_manual.csv"), "--rank", str(R), "--drift", str(drift),
        "--target-year", str(cfg["target_year"]), "--sigma-scale", str(p["sigma_scale"]), "--min-p", str(p["min_p"]),
        "--out", rel(out / "pool.csv"))
    if "subjects" in cfg:
        run("scripts/subject_check.py", rel(out / "pool.csv"), "--subjects", cfg["subjects"]["taken"],
            "--province", cfg["subjects"]["province"], "--out", rel(out / "pool.csv"))
        checked = read(out / "pool.csv")
        write(out / "excluded_subject.csv", [r for r in checked if r["subject_check"].startswith("failed")] or [{"id": "", "subject_check": ""}])
        write(out / "pool.csv", [r for r in checked if not r["subject_check"].startswith("failed")])
    pool = read(out / "pool.csv")
    attrs, missing = [], []
    for r in pool:
        a = scale_row(r, cfg, prestige) if prestige is not None else score_row(r, cfg, by_id, school, major)
        (attrs.append(a) if a else missing.append(r["name"]))
    if missing:
        raise SystemExit(f"位次 {R}：{len(missing)} 个候选不在事前量表里，须先补量表：{missing[:5]}")
    write(out / "attributes.csv", attrs, FIELDS)
    pc = json.loads((SKILL / cfg["persona_config"]).read_text(encoding="utf-8"))
    ids = {r["id"] for r in pool}
    sc = pc["scenarios"][cfg["scenario"]]
    sc["checks"] = [c for c in sc.get("checks", []) if c["a"] in ids and c["b"] in ids]
    (out / "preferences_config.json").write_text(json.dumps(pc, ensure_ascii=False, indent=1), encoding="utf-8")
    run("scripts/preferences.py", rel(out / "attributes.csv"), "--config", rel(out / "preferences_config.json"),
        "--scenario", cfg["scenario"], "--out", rel(out / "utilities.csv"), "--review", rel(out / "preferences_review.json"))
    util = {u["id"]: u for u in read(out / "utilities.csv")}
    reviewed = []
    for r in pool:
        r = dict(r)
        for k in ("school_score", "major_score", "city_score", "outlook_score", "utility", "utility_scenario"):
            r[k] = util[r["id"]].get(k, "")
        reviewed.append(r)
    write(out / "reviewed.csv", reviewed)
    o = cfg["optimize"]
    run("scripts/optimize.py", rel(out / "reviewed.csv"), "--rank", str(R), "--slots", str(o["slots"]), "--drift", str(drift),
        "--target-year", str(cfg["target_year"]), "--sigma-scale", str(p["sigma_scale"]), "--decision-mode", "simulation",
        "--u-fall", str(o["u_fall"]), "--max-fall", str(o["max_fall"]), "--json", rel(out / "result.json"))
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    if not judge:
        return dict(rank=R, pool=len(pool), slots=len(result["list"]), expected_utility=round(result["expected_utility"], 2),
                    p_fall=result.get("p_fall"), drift=drift)
    target = SKILL / series_path(cfg, cfg["target_year"])
    req = {r["id"]: r.get("requirement", "") for r in pool} if cfg["key"] == "group" else None
    judged = retro_judge.judge(result, retro_judge.target_index(target, cfg["key"], cfg.get("school_key", "code")), R, cfg["key"],
                               cfg.get("school_key", "code"), req)
    (out / "hindsight.json").write_text(json.dumps(judged, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(rank=R, pool=len(pool), slots=judged["n_slots"], status=judged["status"], landing_order=judged["landing_order"] or "",
                landing=judged["landing"] or "", landing_utility=round(judged["landing_utility"], 2) if judged["landing_utility"] else "",
                expected_utility=round(result["expected_utility"], 2), blocker_order=judged["blocker_order"] or "",
                observed=judged["n_observed"], brier=round(judged["brier"], 4) if judged["brier"] is not None else "",
                **({"drift": drift} if p["drift"] == "auto" else {}))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case")
    ap.add_argument("--no-judge", action="store_true", help="只出志愿表，不读目标年投档表（登记前调试量表用）")
    a = ap.parse_args()
    case = (SKILL / a.case).resolve() if not Path(a.case).is_absolute() else Path(a.case)
    cfg = json.loads((case / "retro_config.json").read_text(encoding="utf-8"))
    if "scales" in cfg:
        by_id, school, major, prestige = {}, {}, {}, school_prestige(cfg)
    else:
        persona = read(SKILL / cfg["persona_attributes"])
        by_id, prestige = {r["id"]: r for r in persona}, None
        school, major = persona_tables(persona)
    rows = [one_rank(case, cfg, R, by_id, school, major, prestige, not a.no_judge) for R in resolve_ranks(cfg)]
    if a.no_judge:
        for r in rows:
            print(r)
        return
    write(case / "retro_ranks.csv", rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
