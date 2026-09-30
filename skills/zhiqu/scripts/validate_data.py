#!/usr/bin/env python3
"""校验 data/ 下各省投档 CSV：每年 7 月加入新数据后先跑一遍。

检查：
1. 表头是否包含 code, name 和 score / rank 之一；
2. 位次与分数是否一致：同一文件里分数更高的条目，位次应更靠前（数字更小）。
   随机抽取成对比较，违反比例超过阈值（默认 2%）报警——多半是列错位、OCR 错读或位次推算有误；
3. 重复键（同一院校代码 + 专业组 / 专业出现多次）；
4. 年份覆盖（中间缺年）；
5. 院校代码与教育部高校名单（data/schools.csv）的匹配率，只对使用全国统一 5 位代码的省份有意义；
6. 同一院校代码在同一文件里出现多个校名（括号注释除外）——多半是 PDF 水印字或识别噪声混进了校名
   （如江苏的"育南京大学"、上海的"市华东师大"、湖北的"北京化 工大学信"）。

usage: python3 scripts/validate_data.py [省份目录名 ...]   # 不给则检查全部
"""
import csv
import os
import random
import re
import sys

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
SKIP_DIRS = {"civil_service"}
VIOLATION_WARN = 0.02


def num(v):
    v = (v or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def check_file(path, codes):
    issues, notes = [], []
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        header = rows[0].keys() if rows else []
    if not rows:
        return ["空文件"], notes
    if "code" not in header or "name" not in header or not ({"score", "rank"} & set(header)):
        issues.append(f"表头缺少必要列：{', '.join(header)}")
        return issues, notes
    # 位次与分数一致性
    pairs = [(num(r.get("score")), num(r.get("rank"))) for r in rows]
    pairs = [(s, k) for s, k in pairs if s and k]
    if len(pairs) > 50:
        rng = random.Random(0)
        bad = tot = 0
        for _ in range(4000):
            (s1, k1), (s2, k2) = rng.sample(pairs, 2)
            if s1 == s2:
                continue
            tot += 1
            if (s1 > s2) != (k1 < k2):
                bad += 1
        rate = bad / tot if tot else 0
        notes.append(f"分数-位次不一致 {rate:.2%}")
        if rate > VIOLATION_WARN:
            issues.append(f"分数与位次不一致的比例 {rate:.1%}（阈值 {VIOLATION_WARN:.0%}）：检查列是否错位、识别是否出错")
    # 重复键
    sub = "group" if any((r.get("group") or "").strip() for r in rows) else ("major" if "major" in header else None)
    keys = [((r.get("code") or "").strip(), (r.get(sub) or "").strip() if sub else "") for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        notes.append(f"重复键 {dup} 条（按 code + {sub or '无'}）")
        if dup / len(keys) > 0.05:
            issues.append(f"重复键占 {dup / len(keys):.1%}：同校同名专业（如不同校区）会在回测中被剔除，比例过高需检查")
    # 同一代码多个校名（去掉括号里的校区、办学类型等注释后比较）
    names = {}
    for r in rows:
        base = re.sub(r"[（(\[].*$", "", (r.get("name") or "").strip()).strip()
        names.setdefault((r.get("code") or "").strip(), set()).add(base)
    multi = {c: n for c, n in names.items() if c and len(n) > 1}
    if multi:
        eg = "；".join(f"{c}: {'/'.join(sorted(n))}" for c, n in list(multi.items())[:3])
        notes.append(f"同代码多校名 {len(multi)} 个")
        if multi:
            issues.append(f"{len(multi)} 个院校代码对应多个校名（如 {eg}）：检查水印字或识别错误")
    # 院校代码匹配
    c5 = [k[0] for k in keys if re.fullmatch(r"\d{5}", k[0])]
    if len(c5) > 0.8 * len(keys):
        rate = sum(c in codes for c in c5) / len(c5)
        notes.append(f"代码匹配教育部名单 {rate:.1%}")
        if rate < 0.9:
            issues.append(f"院校代码与教育部名单匹配率只有 {rate:.1%}")
    return issues, notes


def main():
    with open(os.path.join(DATA, "schools.csv"), encoding="utf-8") as f:
        codes = {r["code"] for r in csv.DictReader(f)}
    provs = sys.argv[1:] or sorted(d for d in os.listdir(DATA) if os.path.isdir(os.path.join(DATA, d)) and d not in SKIP_DIRS)
    n_issue = 0
    for p in provs:
        files = sorted(fn for fn in os.listdir(os.path.join(DATA, p)) if fn.endswith(".csv") and not fn.startswith(("yfyd", "early")))
        series = {}
        for fn in files:
            m = re.match(r"(.+)_(\d{4})\.csv$", fn)
            if m:
                series.setdefault(m.group(1), []).append(int(m.group(2)))
        print(f"## {p}")
        for name, ys in series.items():
            gaps = [y for y in range(min(ys), max(ys) + 1) if y not in ys]
            print(f"- {name}：{min(ys)}–{max(ys)}" + (f"，缺 {gaps}" if gaps else ""))
        for fn in files:
            issues, notes = check_file(os.path.join(DATA, p, fn), codes)
            print(f"  {fn}：{'；'.join(notes) or '—'}")
            for i in issues:
                print(f"    ⚠ {i}")
                n_issue += 1
    print(f"\n共 {n_issue} 个需要处理的问题")
    sys.exit(1 if n_issue else 0)


if __name__ == "__main__":
    main()
