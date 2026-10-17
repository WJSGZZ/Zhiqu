#!/usr/bin/env python3
"""知衢 · 回溯案例的敏感性：同一候选池与打分，换参数重排志愿表，看结论稳不稳。

读取 <案例>/retro_ranks/<位次>/ 的 reviewed.csv、attributes.csv、preferences_config.json 与 result.json，
按基准参数分别改动：共同波动相关 rho、滑档代价 u_fall、全省整体变难或变好考（drift ±0.06），
以及“前景悲观”（最可能落点所在方向的前景分各减 2 分后重新计分）。结果写到 sensitivity/，汇总写 sensitivity.csv。
只用排表时可得的数据，不读目标年投档表。

用法（技能目录）：
  python3 scripts/retro_sensitivity.py examples/2026-GK-R12
"""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent


def run(*cmd):
    p = subprocess.run([sys.executable, *cmd], cwd=SKILL, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(p.stderr or p.stdout)


def read(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case")
    a = ap.parse_args()
    case = (SKILL / a.case).resolve()
    run_dir = next((case / "retro_ranks").iterdir())
    rel = lambda p: str(Path(p).resolve().relative_to(SKILL))
    base = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    pr = base["params"]
    out = run_dir / "sensitivity"
    out.mkdir(exist_ok=True)

    def optimize(csv_path, name, **over):
        args = dict(rank=pr["rank"], slots=pr["slots"], drift=pr["drift"], target_year=pr["target_year"],
                    sigma_scale=pr["sigma_scale"], u_fall=pr["u_fall"], max_fall=pr["max_fall"], rho=pr["rho"])
        args.update(over)
        cmd = ["scripts/optimize.py", rel(csv_path), "--decision-mode", "simulation", "--json", rel(out / f"{name}.json")]
        for k, v in args.items():
            cmd += [f"--{k.replace('_', '-')}", str(v)]
        run(*cmd)
        return json.loads((out / f"{name}.json").read_text(encoding="utf-8"))

    reviewed = run_dir / "reviewed.csv"
    rows = []
    variants = [
        ("rho_0.1", "各校线一起涨跌的程度变弱（共同波动相关 0.3 → 0.1）", dict(rho=0.1)),
        ("rho_0.5", "各校线一起涨跌的程度变强（共同波动相关 0.3 → 0.5）", dict(rho=0.5)),
        ("ufall_-30", "更不怕滑档（滑档代价 −30，滑档上限 3%）", dict(u_fall=-30, max_fall=0.03)),
        ("ufall_-100", "更怕滑档（滑档代价 −100，滑档上限 0.5%）", dict(u_fall=-100, max_fall=0.005)),
        ("drift_harder", "全省整体比往年再难考约 6%", dict(drift=round(pr["drift"] - 0.06, 4))),
        ("drift_easier", "全省整体比往年再好考约 6%", dict(drift=round(pr["drift"] + 0.06, 4))),
    ]
    for name, label, over in variants:
        rows.append((name, label, optimize(reviewed, name, **over)))

    # 前景悲观：最可能落点所在方向的前景分各减 2 分，重新计分后重排
    attrs = read(run_dir / "attributes.csv")
    top = max(base["list"], key=lambda x: x["p_land"])
    direction = next(r["direction"] for r in attrs if r["id"] == top["id"])
    for r in attrs:
        if r["direction"] == direction:
            r["outlook_score"] = f"{max(0.0, float(r['outlook_score']) - 2):g}"
    write(out / "attributes_outlook_pessimistic.csv", attrs)
    run("scripts/preferences.py", rel(out / "attributes_outlook_pessimistic.csv"), "--config", rel(run_dir / "preferences_config.json"),
        "--scenario", "student", "--out", rel(out / "utilities_outlook_pessimistic.csv"),
        "--review", rel(out / "preferences_review_outlook_pessimistic.json"))
    util = {u["id"]: u for u in read(out / "utilities_outlook_pessimistic.csv")}
    pes = []
    for r in read(reviewed):
        r = dict(r)
        for k in ("outlook_score", "utility", "utility_scenario"):
            r[k] = util[r["id"]].get(k, "")
        pes.append(r)
    write(out / "reviewed_outlook_pessimistic.csv", pes)
    rows.append(("outlook_pessimistic", f"前景悲观：最可能去向所在方向的前景分各减 2 分", optimize(out / "reviewed_outlook_pessimistic.csv", "outlook_pessimistic")))

    def summary(res):
        t = max(res["list"], key=lambda x: x["p_land"])
        return t["name"], t["p_land"]

    bname, bp = summary(base)
    border = [x["name"] for x in base["list"]]
    table = [dict(id="base", scenario="基准", expected_utility=f"{base['expected_utility']:.1f}", p_fall=f"{base['p_fall']:.4f}",
                  top=bname, top_p=f"{bp:.3f}", same_top5="是", slots=len(base["list"]))]
    for name, label, res in rows:
        t, p = summary(res)
        table.append(dict(id=name, scenario=label, expected_utility=f"{res['expected_utility']:.1f}", p_fall=f"{res['p_fall']:.4f}",
                          top=t, top_p=f"{p:.3f}", same_top5="是" if [x["name"] for x in res["list"]][:5] == border[:5] else "否",
                          slots=len(res["list"])))
    write(run_dir / "sensitivity.csv", table)
    for r in table:
        print(r)


if __name__ == "__main__":
    main()
