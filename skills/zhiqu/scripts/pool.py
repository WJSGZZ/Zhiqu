#!/usr/bin/env python3
"""从本省历年投档数据生成候选志愿宽表（每行一个志愿，rank_年份 列），供 rank.py predict / optimize.py 使用。

按全国普通高校名单（data/schools.csv，教育部 2025 年版）补上院校所在省市、公办/民办，
可按所在省、公办、位次范围、名称筛选。

usage:
  python3 scripts/pool.py --year 2024=data/guangdong/physics_2024.csv --year 2025=... --year 2026=... \
      --key group --in-province 广东省 --public --rank-min 15000 --rank-max 60000 --out 志愿.csv
"""
import argparse
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
# 需要单独资格、异地培养或学费明显不同的条目，默认不进候选池
EXCLUDE = "中外合作|国际|民办|独立学院|专项|联合培养|预科|民族班|面向.{1,8}[县市区州]|定向|分校招生|高本贯通|走读"


def schools():
    with open(os.path.join(HERE, "..", "data", "schools.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["code"]: r for r in rows}, {r["name"]: r for r in rows}


def name_variants(name):
    """由长到短的候选校名：去掉方括号标签，统一全角括号，再逐个去掉末尾的括号注释。
    中国石油大学(华东)(青岛市)[公办] → 中国石油大学（华东）（青岛市）、中国石油大学（华东）、中国石油大学。"""
    n = re.sub(r"[\[【].*?[\]】]", "", name).replace("(", "（").replace(")", "）").strip()
    out = [n]
    while re.search(r"（[^（）]*）\s*$", n):
        n = re.sub(r"（[^（）]*）\s*$", "", n).strip()
        out.append(n)
    return out


def lookup(code, name, by_code, by_name):
    """先按教育部代码匹配（广东等用国标代码的省份），再按校名匹配（浙江、山东等用本省院校代号的省份）；
    校名不在名单里时取名单中最长的前缀校名（北京大学医学部 → 北京大学）。
    2025 年 6 月以后更名或新设的院校（如湖州师范学院 → 湖州师范大学）匹配不到，记为未知。"""
    if code in by_code:
        return by_code[code]
    variants = name_variants(name)
    for n in variants:
        if n in by_name:
            return by_name[n]
    n = variants[-1]
    for k in range(len(n) - 1, 3, -1):
        if n[:k] in by_name:
            return by_name[n[:k]]
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", action="append", required=True, help="年份=投档CSV")
    ap.add_argument("--key", choices=["group", "major"], default="group", help="专业组省份用 group，专业+院校省份用 major")
    ap.add_argument("--school", choices=["code", "name"], default="code",
                    help="跨年按院校代码还是院校名称对应；院校代号每年重编的省份（河北）用 name，与 backtest.py 一致")
    ap.add_argument("--in-province", help="只保留位于该省的院校，如 广东省")
    ap.add_argument("--out-province", action="store_true", help="与 --in-province 相反：只保留外省院校")
    ap.add_argument("--public", action="store_true", help="排除民办与中外合作办学院校（按教育部名单备注）")
    ap.add_argument("--exclude", default=EXCLUDE, help="名称/专业中含这些词的条目排除（正则，空串表示不排除）；专项、预科、民族班、面向某县的定向、联合培养等需要单独资格或异地培养，默认排除")
    ap.add_argument("--match", help="只保留名称或专业匹配该正则的条目")
    ap.add_argument("--rank-min", type=int, help="最近一年位次下限")
    ap.add_argument("--rank-max", type=int, help="最近一年位次上限")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    by_code, by_name = schools()
    years = sorted((int(y), p) for y, p in (s.split("=", 1) for s in a.year))
    table = {}
    for y, p in years:
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rk = (r.get("rank") or "").strip()
                if not rk.isdigit():
                    continue
                code = (r.get("code") or "").strip()
                sub = (r.get("group") if a.key == "group" else r.get("major")) or ""
                school = (r.get("name") or "").strip()
                k = (code if a.school == "code" else school, sub.strip())
                e = table.setdefault(k, {"code": code, "school": school, "sub": sub.strip(),
                                         "req": (r.get("major") or "").strip() if a.key == "group" else "", "ranks": {}, "plan": ""})
                e["ranks"][y] = int(rk)
                e["code"] = code  # 保留最近一年的院校代码，填报单用
                e["plan"] = r.get("plan") or e["plan"]
                if a.key == "group":
                    e["req"] = (r.get("major") or "").strip()  # 专业组省份的 major 列存的是选科要求
    last = years[-1][0]
    rows, unmatched = [], 0
    for (_, sub), e in table.items():
        code = e["code"]
        if last not in e["ranks"]:
            continue
        info = lookup(code, e["school"], by_code, by_name)
        text = e["school"] + " " + e["sub"]
        if a.exclude and re.search(a.exclude, text + " " + info.get("note", "")):
            continue
        if not info:
            unmatched += 1
        if a.public and info.get("note"):
            continue
        if a.in_province and (info.get("province") == a.in_province) == a.out_province:
            continue
        if a.match and not re.search(a.match, text):
            continue
        rl = e["ranks"][last]
        if (a.rank_min and rl < a.rank_min) or (a.rank_max and rl > a.rank_max):
            continue
        name = f"{e['school']}·{sub}组" if a.key == "group" else f"{e['school']}·{sub}"
        row = {"id": f"{code}-{sub}", "name": name, "code": code, "group": sub if a.key == "group" else "",
               "requirement": e["req"], "province": info.get("province", "未知"), "city": info.get("city", ""),
               "plan": e["plan"]}
        for y, _ in reversed(years):
            row[f"rank_{y}"] = e["ranks"].get(y, "")
        rows.append(row)
    rows.sort(key=lambda r: r[f"rank_{last}"])
    unknown = sum(r["province"] == "未知" for r in rows)
    cols = ["id", "name", "code", "group", "requirement", "province", "city", "plan"] + [f"rank_{y}" for y, _ in reversed(years)]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"写出 {len(rows)} 个候选到 {a.out}；{unknown} 个未在教育部名单中匹配到院校，所在省记为'未知'")
    if (a.in_province or a.public) and unmatched:
        print(f"⚠ {unmatched} 个条目因院校未匹配而无法按所在省或公办民办筛选：--in-province 会排除它们，--public 会保留它们，请人工核对")


if __name__ == "__main__":
    main()
