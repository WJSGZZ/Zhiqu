#!/usr/bin/env python3
"""知衢 · 选考科目核对：用官方选考要求表（data/subject_req_2027.csv）逐个核对候选池。

按"校名 + 专业名"在本省官方表中查找（浙江官方表没有院校代码）；专业名带括号的
（如"电气工程及其自动化(卓越工程师班)"）找不到时退回基础专业名，并在说明里写明。
要求表里列出的科目必须全部选考（"1 门/2 门/3 门科目考生均须/必须选考"），"不提科目要求"即满足。
结果写进 eligibility_evidence 中名称含"选考"的硬条件：met / failed；查不到的保持 unknown。
只核选考科目，不核章程、体检、计划，因此不会把整条证据改成 verified。

用法：
  python3 scripts/subject_check.py pool.csv --subjects 物理,化学,技术 --province 浙 --out pool.csv
"""
import argparse
import csv
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
TABLE = DATA / "subject_req_2027.csv"
CHAR = {"河北": "冀", "河南": "豫", "山东": "鲁", "江苏": "苏", "浙江": "浙", "福建": "闽", "湖北": "鄂", "湖南": "湘", "广东": "粤"}


def official_source(province):
    """本省官方表的来源网址，唯一记录在 data/README.md 的“2027 届选考科目要求”表里。"""
    part = (DATA / "README.md").read_text(encoding="utf-8").split("2027 届选考科目要求", 1)[-1]
    for line in part.splitlines():
        m = re.match(r"\|\s*(\S+?)\s*\|.*?<(https?://[^>]+)>", line)
        if m and CHAR.get(m.group(1)) == province:
            return m.group(2)
    return None


def base(name):
    return re.sub(r"[（(].*$", "", name).strip()


def required(req):
    if not req or "不提" in req:
        return []
    return [s.strip() for s in re.sub(r"[（(].*$", "", req).split(",") if s.strip()]


def load(province):
    idx = {}
    with open(TABLE, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if province in r["provinces"]:
                idx.setdefault((r["school_name"].strip(), r["major_name"].strip()), []).append(r["req"])
    return idx


def check(name, idx, subjects):
    school, major = name.split("·", 1)
    for key, how in (((school, major), ""), ((school, base(major)), "按基础专业名“%s”匹配；" % base(major))):
        reqs = set(idx.get(key, []))
        if len(reqs) == 1:
            req = reqs.pop()
            need = required(req)
            ok = all(s in subjects for s in need)
            return ("met" if ok else "failed"), f"{how}要求“{req}”"
        if len(reqs) > 1:
            return "unknown", f"{how}同校同名专业有 {len(reqs)} 种要求，须人工核对"
    return "unknown", "官方表中未找到该校该专业"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv")
    ap.add_argument("--subjects", required=True, help="本人选考科目，逗号分隔")
    ap.add_argument("--province", required=True, help="官方表 provinces 列里代表本省的单字，如 浙")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    subjects = {s.strip() for s in a.subjects.replace("，", ",").split(",") if s.strip()}
    idx = load(a.province)
    src = official_source(a.province)
    with open(a.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    counts = {"met": 0, "failed": 0, "unknown": 0}
    for r in rows:
        status, note = check(r["name"], idx, subjects)
        counts[status] += 1
        r["subject_check"] = f"{status}：{note}"
        if r.get("eligibility_evidence"):
            ev = json.loads(r["eligibility_evidence"])
            for c in ev.get("hard_conditions", []):
                if "选考" in c.get("name", ""):
                    c["status"] = status
                    if status != "unknown" and src and src.startswith("https://"):
                        c["source"] = src
                    c["note"] = note + "（data/subject_req_2027.csv）"
            if status == "met":
                ev["unresolved"] = [u for u in ev.get("unresolved", []) if "选考" not in u] or ev.get("unresolved", [])
            if status == "failed":
                ev["status"] = "ineligible"
            r["eligibility_evidence"] = json.dumps(ev, ensure_ascii=False)
    fields = list(rows[0]) if rows else []
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"核对 {len(rows)} 个候选：满足 {counts['met']}，不满足 {counts['failed']}，查不到 {counts['unknown']}")
    for r in rows:
        if not r["subject_check"].startswith("met"):
            print(f"  {r['name']}：{r['subject_check']}")


if __name__ == "__main__":
    main()
