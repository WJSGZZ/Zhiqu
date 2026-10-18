#!/usr/bin/env python3
"""校验各省投档 CSV、入学后的机会表和求职版选调高校范围表。

检查：
1. 表头是否包含 code, name 和 score / rank 之一；
2. 位次与分数是否一致：同一文件里分数更高的条目，位次应更靠前（数字更小）。
   随机抽取成对比较，违反比例超过阈值（默认 2%）报警——多半是列错位、OCR 错读或位次推算有误；
3. 重复键（同一院校代码 + 专业组 / 专业出现多次）；
4. 年份覆盖（中间缺年）；
5. 代码数值在教育部高校名单（data/schools.csv）的出现率，不证明同一学校，须核对校名；
6. 同一院校代码在同一文件里出现多个校名（括号注释除外）——多半是 PDF 水印字或识别噪声混进了校名
   （如江苏的"育南京大学"、上海的"市华东师大"、湖北的"北京化 工大学信"）；
7. 入学后的机会表：必要列、证据状态、来源网址、真实日期与复核先后顺序；
8. 选调高校范围表：必要列、2027 年份、来源定位、日期与复核先后顺序、重复条目。

usage: python3 scripts/validate_data.py [省份目录名 ...]   # 不给则检查全部
"""
import argparse
import csv
import datetime
from datetime import date
import os
import random
import re
import sys
from urllib.parse import urlsplit

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CAREER_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "zhiqu-career", "data")
SKIP_DIRS = {"civil_service", "calibration", "purchased"}  # purchased 是本地内部库，不提交
MAX_SCORE = 750
VIOLATION_WARN = 0.02
AFTER_ENTRY_FIELDS = (
    "school", "province", "opportunity_type", "project_name", "eligibility",
    "selection_time", "selection_method", "seats", "available_majors",
    "extra_fees", "applicable_year", "source_url", "verified_date",
    "review_deadline", "status", "notes",
)
AFTER_ENTRY_STATUSES = {"verified", "not_found", "unretrieved"}
SELECTED_UNIVERSITIES_FIELDS = (
    "province", "year", "category", "school", "major_restriction", "source_url",
    "published_date", "retrieved_date", "review_deadline", "source_locator", "notes",
)


def num(v):
    v = (v or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def check_after_entry_file(path):
    """校验机会表的来源地址与复核时间；不把格式合格当作内容已核实。"""
    issues, notes = [], []
    if not os.path.isfile(path):
        return ["入学后的机会表不存在"], notes
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing = [field for field in AFTER_ENTRY_FIELDS if field not in header]
        if missing:
            return [f"表头缺少必要列：{', '.join(missing)}"], notes
        rows = list(reader)
    if not rows:
        return ["空文件"], notes
    for line, row in enumerate(rows, start=2):
        for field in ("school", "province", "opportunity_type", "status"):
            if not (row.get(field) or "").strip():
                issues.append(f"第 {line} 行 {field} 不能为空")
        status = (row.get("status") or "").strip()
        if status and status not in AFTER_ENTRY_STATUSES:
            issues.append(f"第 {line} 行 status 未知：{status}")
        source = (row.get("source_url") or "").strip()
        try:
            parsed = urlsplit(source)
            valid_source = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            valid_source = False
        if not valid_source:
            issues.append(f"第 {line} 行 source_url 必须是非空的 http/https 网址")
        dates = {}
        for field in ("verified_date", "review_deadline"):
            value = (row.get(field) or "").strip()
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError
                dates[field] = date.fromisoformat(value)
            except ValueError:
                issues.append(f"第 {line} 行 {field} 必须是真实的 YYYY-MM-DD 日期：{value}")
        if len(dates) == 2 and dates["review_deadline"] < dates["verified_date"]:
            issues.append(f"第 {line} 行复核期限早于核实日期")
    notes.append(f"{len(rows)} 行，{len({(row.get('school') or '').strip() for row in rows})} 所学校")
    return issues, notes


COMPETITION_FIELDS = (
    "province", "year", "measure", "unit", "group_type", "group", "n_jobs",
    "p10", "p25", "p50", "p75", "p90", "share_below_10", "share_100_plus",
    "scope", "source_url", "published_date", "retrieved_date", "review_deadline",
)


def check_competition_file(path):
    """校验公务员竞争汇总表：分位数要递增，比例在 0—1，日期为真实日期。"""
    issues, notes = [], []
    if not os.path.isfile(path):
        return ["竞争汇总表不存在"], notes
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [x for x in COMPETITION_FIELDS if x not in (reader.fieldnames or [])]
        if missing:
            return [f"表头缺少必要列：{', '.join(missing)}"], notes
        rows = list(reader)
    if not rows:
        return ["空文件"], notes
    for i, r in enumerate(rows, start=2):
        where = f"第 {i} 行"
        if not re.match(r"^https?://", r["source_url"].strip()):
            issues.append(f"{where}：source_url 不是网址")
        for k in ("retrieved_date", "review_deadline") + (("published_date",) if r["published_date"].strip() else ()):
            try:
                datetime.date.fromisoformat(r[k].strip())
            except ValueError:
                issues.append(f"{where}：{k} 不是真实日期")
        try:
            n = int(r["n_jobs"])
            qs = [float(r[k]) for k in ("p10", "p25", "p50", "p75", "p90")]
        except ValueError:
            issues.append(f"{where}：n_jobs 或分位数不是数字")
            continue
        if n <= 0:
            issues.append(f"{where}：n_jobs 必须为正")
        if qs != sorted(qs):
            issues.append(f"{where}：分位数没有递增")
        for k in ("share_below_10", "share_100_plus"):
            v = r[k].strip()
            if v and not 0 <= float(v) <= 1:
                issues.append(f"{where}：{k} 不在 0—1")
    notes.append(f"{len(rows)} 行")
    return issues, notes


def check_selected_universities_file(path):
    """校验选调高校范围表；来源定位供人工回到官方附件复核。"""
    issues, notes = [], []
    if not os.path.isfile(path):
        return ["选调高校范围表不存在"], notes
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [field for field in SELECTED_UNIVERSITIES_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            return [f"表头缺少必要列：{', '.join(missing)}"], notes
        rows = list(reader)
    if not rows:
        return ["空文件"], notes
    seen = {}
    required = set(SELECTED_UNIVERSITIES_FIELDS) - {"major_restriction", "notes"}
    for line, row in enumerate(rows, start=2):
        values = {field: (row.get(field) or "").strip() for field in SELECTED_UNIVERSITIES_FIELDS}
        for field in SELECTED_UNIVERSITIES_FIELDS:
            if field in required and not values[field]:
                issues.append(f"第 {line} 行 {field} 不能为空")
        if values["year"] != "2027":
            issues.append(f"第 {line} 行 year 必须是整数 2027：{values['year']}")
        source = values["source_url"]
        try:
            parsed = urlsplit(source)
            valid_source = (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                            and not re.search(r"\s", source))
            parsed.port  # 非数字或超范围端口也不是合法网址
        except ValueError:
            valid_source = False
        if not valid_source:
            issues.append(f"第 {line} 行 source_url 必须是非空的 http/https 网址")
        dates = {}
        for field in ("published_date", "retrieved_date", "review_deadline"):
            value = values[field]
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    raise ValueError
                dates[field] = date.fromisoformat(value)
            except ValueError:
                issues.append(f"第 {line} 行 {field} 必须是真实的 YYYY-MM-DD 日期：{value}")
        if ("review_deadline" in dates and "retrieved_date" in dates
                and dates["review_deadline"] < dates["retrieved_date"]):
            issues.append(f"第 {line} 行复核期限早于取得日期")
        key = tuple(values[field] for field in ("province", "year", "category", "school", "major_restriction"))
        if key in seen:
            issues.append(f"第 {line} 行与第 {seen[key]} 行重复：province/year/category/school/major_restriction")
        else:
            seen[key] = line
    notes.append(f"{len(rows)} 行，{len({row.get('school') for row in rows})} 个原文校名")
    return issues, notes


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
    # 分数超出满分：十省高考总分均为 750；2026-10 发现江苏 xls 数值格转换时丢了小数点（688.0 → 6880）
    over = [(r.get("name"), r.get("score")) for r in rows if (num(r.get("score")) or 0) > MAX_SCORE]
    if over:
        issues.append(f"{len(over)} 行分数超过满分 {MAX_SCORE}，疑似转换时丢了小数点：{over[:3]}")
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
        notes.append(f"代码值在教育部名单出现 {rate:.1%}（数值重合不证明学校身份）")
        if rate < 0.9:
            issues.append(f"院校代码与教育部名单匹配率只有 {rate:.1%}")
    return issues, notes


def main():
    parser = argparse.ArgumentParser(description="校验投档 CSV、入学后的机会表和选调高校范围表")
    parser.add_argument("provinces", nargs="*", help="data 下的省份目录；默认全部省份")
    args = parser.parse_args()
    with open(os.path.join(DATA, "schools.csv"), encoding="utf-8") as f:
        codes = {r["code"] for r in csv.DictReader(f)}
    provs = args.provinces or sorted(d for d in os.listdir(DATA) if os.path.isdir(os.path.join(DATA, d)) and d not in SKIP_DIRS)
    for province in provs:
        if province not in os.listdir(DATA) or not os.path.isdir(os.path.join(DATA, province)):
            parser.error(f"未知省份目录：{province}")
    n_issue = 0
    issues, notes = check_after_entry_file(os.path.join(DATA, "after-entry-opportunities.csv"))
    print(f"## after-entry-opportunities.csv：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    issues, notes = check_selected_universities_file(os.path.join(CAREER_DATA, "selected-universities-2027.csv"))
    print(f"## selected-universities-2027.csv：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    issues, notes = check_competition_file(os.path.join(CAREER_DATA, "civil-service-competition-2026.csv"))
    print(f"## civil-service-competition-2026.csv：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
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
