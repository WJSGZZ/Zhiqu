#!/usr/bin/env python3
"""知衢 · 回溯样板的多档位次复算：只用目标年以前的数据出志愿表，再用目标年真实投档线判定。

读取案例目录里的 retro_config.json（事前登记的人物、位次档、筛选条件、打分量表、模型参数），
对每一档位次依次：pool.py 生成候选 → 剔除校区所在地误配 → rank.py 预测 → 按量表打分 →
preferences.py 计分 → optimize.py 选表 → retro_judge.py 判定。中间文件写到 <案例>/retro_ranks/<位次>/，
汇总写 <案例>/retro_ranks.csv。目标年投档表只在判定这一步读取。

用法（技能目录）：
  python3 scripts/retro_run.py examples/2026-GK-R01
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import retro_judge  # noqa: E402

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


def one_rank(case, cfg, R, by_id, school, major):
    out = case / "retro_ranks" / str(R)
    out.mkdir(parents=True, exist_ok=True)
    rel = lambda p: str(Path(p).resolve().relative_to(SKILL))
    lo, hi = cfg.get("band_override", {}).get(str(R)) or [int(R * cfg["band"][0]), int(R * cfg["band"][1])]
    years = [a for y in cfg["data_years"] for a in ("--year", f"{y}=data/{cfg['province']}/general_{y}.csv")]
    run("scripts/pool.py", *years, "--key", cfg["key"], "--public", "--rank-min", str(lo), "--rank-max", str(hi),
        "--match-major", cfg["match_major"], "--exclude-major", cfg["exclude_major"], "--in-provinces", cfg["in_provinces"],
        "--out", rel(out / "pool_raw.csv"))
    raw = read(out / "pool_raw.csv")
    keep = [r for r in raw if not re.search("校区括号.*不符", r["note"])]
    write(out / "pool_manual.csv", keep)
    p = cfg["predict"]
    run("scripts/rank.py", "predict", rel(out / "pool_manual.csv"), "--rank", str(R), "--drift", str(p["drift"]),
        "--target-year", str(cfg["target_year"]), "--sigma-scale", str(p["sigma_scale"]), "--min-p", str(p["min_p"]),
        "--out", rel(out / "pool.csv"))
    pool = read(out / "pool.csv")
    attrs, missing = [], []
    for r in pool:
        a = score_row(r, cfg, by_id, school, major)
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
    run("scripts/optimize.py", rel(out / "reviewed.csv"), "--rank", str(R), "--slots", str(o["slots"]), "--drift", str(p["drift"]),
        "--target-year", str(cfg["target_year"]), "--sigma-scale", str(p["sigma_scale"]), "--decision-mode", "simulation",
        "--u-fall", str(o["u_fall"]), "--max-fall", str(o["max_fall"]), "--json", rel(out / "result.json"))
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    target = SKILL / f"data/{cfg['province']}/general_{cfg['target_year']}.csv"
    judged = retro_judge.judge(result, retro_judge.target_index(target, cfg["key"]), R, cfg["key"])
    (out / "hindsight.json").write_text(json.dumps(judged, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(rank=R, pool=len(pool), slots=judged["n_slots"], status=judged["status"], landing_order=judged["landing_order"] or "",
                landing=judged["landing"] or "", landing_utility=round(judged["landing_utility"], 2) if judged["landing_utility"] else "",
                expected_utility=round(result["expected_utility"], 2), blocker_order=judged["blocker_order"] or "",
                observed=judged["n_observed"], brier=round(judged["brier"], 4))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case")
    a = ap.parse_args()
    case = (SKILL / a.case).resolve() if not Path(a.case).is_absolute() else Path(a.case)
    cfg = json.loads((case / "retro_config.json").read_text(encoding="utf-8"))
    persona = read(SKILL / cfg["persona_attributes"])
    by_id = {r["id"]: r for r in persona}
    school, major = persona_tables(persona)
    rows = [one_rank(case, cfg, R, by_id, school, major) for R in cfg["ranks"]]
    write(case / "retro_ranks.csv", rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
