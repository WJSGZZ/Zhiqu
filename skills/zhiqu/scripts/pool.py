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
    by_code, by_name = {r["code"]: r for r in rows}, {r["name"]: r for r in rows}
    aliases = os.path.join(HERE, "..", "data", "school-name-changes.csv")
    if os.path.exists(aliases):
        with open(aliases, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                # 教育部10位标识码的后5位对应本教育部名单 code；不据此改省级招生代号。
                identifier = (r.get("school_code") or "").strip()
                if re.fullmatch(r"\d{10}", identifier) and identifier[-5:] in by_code:
                    info = by_code[identifier[-5:]]
                    for name in (r["former_name"], r["current_name"]):
                        by_name.setdefault(name, info)
    return by_code, by_name


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
    """先按明确校名/官方更名别名确认实体；招生代号不能覆盖不同学校的名称。
    去除末尾校区/路径括号后仍匹配不到时保留未知，不用一般校名前缀猜公办属性。
    北京大学医学部为已有核实的母校归属特例（官方 bjmu.edu.cn）。
    """
    variants = name_variants(name)
    for n in variants:
        if n in by_name:
            return by_name[n]
    if code in by_code and by_code[code]["name"] in variants:
        return by_code[code]
    if variants[-1] == "北京大学医学部":
        return by_name.get("北京大学", {})
    return {}


def load_group_map(path, school_field):
    """人工核实的跨年一对一对应；source 留证据，不由组号推断对应关系。"""
    if not path:
        return {}
    mapping, used = {}, set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"year", school_field, "group", "history_key", "source"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("专业组对应表缺少列：" + ", ".join(sorted(required)))
        for line, r in enumerate(reader, 2):
            values = {k: (r.get(k) or "").strip() for k in required}
            if not all(values.values()):
                raise ValueError(f"专业组对应表第 {line} 行有空字段")
            key = (int(values["year"]), values[school_field], values["group"])
            stable = values["history_key"]
            if key in mapping or (key[0], stable) in used:
                raise ValueError(f"专业组对应表第 {line} 行不是一对一对应；拆组/合组不可直接拼接")
            mapping[key] = (stable, values["source"])
            used.add((key[0], stable))
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", action="append", required=True, help="年份=投档CSV")
    ap.add_argument("--key", choices=["group", "major"], default="group", help="专业组省份用 group，专业+院校省份用 major")
    ap.add_argument("--school", choices=["code", "name"], default="code",
                    help="跨年按院校代码还是院校名称对应；院校代号每年重编的省份（河北）用 name，与 backtest.py 一致")
    ap.add_argument("--group-map", help="已核实组内专业与招生条件的跨年对应 CSV：year,code（或 name）,group,history_key,source；没有对应的组只用最近一年")
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
    if len({y for y, _ in years}) != len(years):
        ap.error("--year 不可重复指定同一年")
    if a.group_map and a.key != "group":
        ap.error("--group-map 仅用于 --key group")
    try:
        group_map = load_group_map(a.group_map, a.school)
    except ValueError as exc:
        ap.error(str(exc))
    last = years[-1][0]
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
                school_key = code if a.school == "code" else school
                mapped = group_map.get((y, school_key, sub.strip())) if a.key == "group" else None
                if a.key == "group":
                    if mapped:
                        k = ("verified", mapped[0])
                    elif y == last:
                        k = ("latest_only", school_key, sub.strip())
                    else:
                        continue  # 同组号不证明同组；未核实的历史不进入预测
                else:
                    k = (school_key, sub.strip())
                e = table.setdefault(k, {"code": code, "school": school, "sub": sub.strip(),
                                         "req": "", "ranks": {}, "plan": "", "sources": [], "ambiguous": set()})
                if y in e["ambiguous"]:
                    continue
                if y in e["ranks"]:
                    if a.key == "group":
                        ap.error(f"{y} 年 {school}·{sub} 出现重复键，不能静默覆盖；先核对校区、招生条件和专业代码")
                    e["ambiguous"].add(y)
                    del e["ranks"][y]  # 同校同名专业的不同校区/类型，整年剔除，不能任选一条
                    continue
                e["ranks"][y] = int(rk)
                e["code"] = code  # 保留最近一年的院校代码，填报单用
                e["school"], e["sub"] = school, sub.strip()
                e["plan"] = r.get("plan") or ""  # 最新年份未知时，不冒用旧计划
                if mapped:
                    e["sources"].append(f"{y}: {mapped[1]}")
                if a.key == "group":
                    e["req"] = (r.get("major") or "").strip()  # 专业组省份的 major 列存的是选科要求
    rows, unmatched = [], 0
    for e in table.values():
        sub = e["sub"]
        code = e["code"]
        if last not in e["ranks"]:
            continue
        info = lookup(code, e["school"], by_code, by_name)
        text = e["school"] + " " + e["sub"]
        if a.exclude and re.search(a.exclude, text + " " + info.get("note", "")):
            continue
        if not info:
            unmatched += 1
        if a.public and (not info or info.get("note")):
            continue
        if a.in_province and (not info or (info.get("province") == a.in_province) == a.out_province):
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
        row["history_status"] = ("verified" if len(e["ranks"]) > 1 else "latest_only") if a.key == "group" else "by_major"
        row["note"] = "；".join(e["sources"]) if e["sources"] else ("专业组跨年组成未核实，只用最近一年" if a.key == "group" else "")
        if e["ambiguous"]:
            row["note"] += "；重复专业键已剔除年份：" + ",".join(map(str, sorted(e["ambiguous"])))
        for y, _ in reversed(years):
            row[f"rank_{y}"] = e["ranks"].get(y, "")
        rows.append(row)
    rows.sort(key=lambda r: r[f"rank_{last}"])
    unknown = sum(r["province"] == "未知" for r in rows)
    cols = ["id", "name", "code", "group", "requirement", "province", "city", "plan", "history_status", "note"] + [f"rank_{y}" for y, _ in reversed(years)]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"写出 {len(rows)} 个候选到 {a.out}；{unknown} 个未在教育部名单中匹配到院校，所在省记为'未知'")
    ambiguous = sum(len(e["ambiguous"]) for e in table.values())
    if ambiguous:
        print(f"⚠ {ambiguous} 个同校同名专业的年度重复键已剔除；最新年份重复的条目未进入候选池，请核对专业代码/校区")
    if a.key == "group":
        print(f"专业组跨年核实：{sum(r['history_status'] == 'verified' for r in rows)} 个；其余只用最近一年位次")
    if (a.in_province or a.public) and unmatched:
        print(f"⚠ {unmatched} 个条目因院校未匹配而无法按所在省或公办民办筛选：已排除，请人工核对")


if __name__ == "__main__":
    main()
