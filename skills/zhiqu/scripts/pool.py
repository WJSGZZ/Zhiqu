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
from decimal import Decimal, InvalidOperation
import json
import os
import re
from data_provenance import cutoff_rank_gate

HERE = os.path.dirname(os.path.abspath(__file__))
# 需要单独资格、异地培养或学费明显不同的条目，默认不进候选池
EXCLUDE = "中外合作|国际|民办|独立学院|专项|联合培养|预科|民族班|面向.{1,8}[县市区州]|定向|分校招生|高本贯通|走读"
# 校名括号里的招生计划类别（不是校区）：八协计划、协作计划、各类专项、预科、民族班、少数民族、定向、面向某地。
# 以各省数据实际出现的写法为准（2026-10-22 统计：河北“八协计划”“地方专项计划”“少数民族预科班”，福建“面向厦门”“少数民族”等）。
# 卓越优才计划、中高计划、京津冀职教改革项目等含义未核实，不在此列，仍按校区括号处理。
PLAN_BRACKET = re.compile(r"八协计划|协作计划|专项|预科|民族班|^少数民族$|^面向|定向")
# 新规则的默认排除词：旧排除词再加两类只限特定身份、却因写法漏网的括号——“（少数民族）”和不带市县字样的“（面向厦门）”。
# 其余计划类（如八协计划）保留并标“资格待核”。考生符合资格时仍用 --exclude 放开。
EXCLUDE_TAGGED = EXCLUDE + r"|[（(](少数民族|面向[^（）()]*)[）)]"
PENDING = "资格待核"
UNKNOWN_PLAN = {"", "未标", "未注明", "未知", "来源未提供", "原件缺失"}
ORDINARY_PLAN = {"普通", "普通类", "一般统考生"}


def weakest_grade(grades):
    """行概览取最弱来源；逐值的真实等级仍保留在 data_provenance 中。"""
    order = {"官方": 0, "官方一致": 1, "第三方整理": 2, "第三方整理·内部未核": 2}
    values = [str(g).strip() for g in grades if str(g or "").strip()]
    return max(values, key=lambda g: order.get(g, 3)) if values else ""


def input_provenance(row, year):
    raw = (row.get("data_provenance") or "").strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict) or any(not isinstance(v, dict) for v in value.values()):
        raise ValueError("data_provenance 必须为按 rank/score/plan 记录的对象")
    if any(key not in {"rank", "score", "plan"} for key in value):
        raise ValueError("data_provenance 只接受 rank/score/plan 字段")
    if not value.get("rank"):
        raise ValueError("data_provenance 缺少实际参与计算的 rank 来历")
    for field, metadata in value.items():
        if field == "rank" and cutoff_rank_gate(metadata):
            raise ValueError("data_provenance.rank 是待核推算参照，不能作为实际投档位次进入候选模型")
        if "value" not in metadata:
            raise ValueError(f"data_provenance.{field} 缺 value")
        actual = str(row.get(field) or "").strip()
        expected = metadata["value"]
        if expected is None:
            if actual or field == "rank":
                raise ValueError(f"data_provenance.{field}.value 与 CSV 数字不一致")
        else:
            if isinstance(expected, bool) or not isinstance(expected, (int, float)):
                raise ValueError(f"data_provenance.{field}.value 必须为数值，不能是布尔或文本")
            try:
                a, b = Decimal(actual), Decimal(str(expected))
            except InvalidOperation:
                raise ValueError(f"CSV {field} 必须为与来历一致的数值") from None
            if not a.is_finite() or not b.is_finite() or a != b:
                raise ValueError(f"data_provenance.{field}.value 与 CSV 数字不一致")
            if field in ("rank", "plan") and a != a.to_integral_value():
                raise ValueError(f"CSV {field} 必须为整数")
        scope = metadata.get("scope", {})
        if not isinstance(scope, dict):
            raise ValueError(f"data_provenance.{field}.scope 必须为对象")
        if "year" in scope and (isinstance(scope["year"], bool) or str(scope["year"]) != str(year)):
            raise ValueError(f"data_provenance.{field}.scope.year 与输入年份不一致")
    return value


def input_plan_scope(row, provenance):
    """只传递具名结构化条件，不从校名、标题或分数反推计划身份。"""
    claims = {"plan_type": [], "source_admission_type_raw": []}
    seen = False

    def take(source, key):
        nonlocal seen
        if key not in source:
            return
        seen = True
        value = source[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"计划条件 {key} 必须为文本")
        if value and value.strip():
            claims[key].append(value.strip())

    for key in claims:
        take(row, key)
    for meta in provenance.values():
        if meta.get("value") is None:
            continue
        scope = meta.get("scope") or {}
        for key in claims:
            take(scope, key)
        original = meta.get("original_scope") or {}
        if not isinstance(original, dict):
            raise ValueError("原计划条件 original_scope 必须为对象")
        original_row = original.get("source_scope_original") or {}
        if not isinstance(original_row, dict):
            raise ValueError("原计划条件 source_scope_original 必须为对象")
        take(original_row, "source_admission_type_raw")
    if not seen:
        return None
    result = {}
    for key, values in claims.items():
        if len(set(values)) > 1:
            raise ValueError(f"CSV 与逐值来历的计划条件 {key} 不一致")
        result[key] = values[0] if values else ""
    return result


def pending_scope_plans(scope):
    if scope is None:
        return []
    return list(dict.fromkeys(value for value in scope.values() if value not in ORDINARY_PLAN | UNKNOWN_PLAN))


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


def plan_split(name):
    """把校名末尾的招生计划类括号与校名分开：返回 (去掉计划括号后的校名, [计划名])。
    内蒙古大学(八协计划)[公办] → 内蒙古大学、[八协计划]；校区、分校、独立学院等其他括号原样保留，
    仍走名单匹配与校区核对，不会因此并到别的学校。括号内用逗号并列多项时，任一项是计划类就整个括号算计划。"""
    n = re.sub(r"[\[【].*?[\]】]", "", name).replace("(", "（").replace(")", "）").strip()
    tail = []
    while True:
        m = re.search(r"（([^（）]*)）\s*$", n)
        if not m:
            break
        tail.insert(0, m.group(1).strip())
        n = n[:m.start()].strip()
    plans = [b for b in tail if any(PLAN_BRACKET.search(x.strip()) for x in re.split("[，,]", b))]
    rest = "".join(f"（{b}）" for b in tail if b not in plans)
    return n + rest, plans


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


def campus_warning(name, info):
    """校名带校区括号（如“华北电力大学(保定)”）而教育部名单只有主校区时，名单里的所在地可能不是该校区所在地。
    括号内容不在名单所在省市里就提醒，不改写所在地，须人工核对。"""
    variants = name_variants(name)
    if not info or len(variants) < 2:
        return ""
    for n in variants[1:]:
        if n == info.get("name"):
            suffix = re.sub(r"[\[【].*?[\]】]", "", name).replace("(", "（").replace(")", "）").strip()[len(n):].strip("（）")
            place = info.get("province", "") + info.get("city", "")
            if suffix and not any(w and w in place for w in (suffix, suffix.replace("校区", ""))):
                return f"校区括号“{suffix}”与名单所在地“{info.get('province', '')}{info.get('city', '')}”不符，所在地须人工核对"
            return ""
    return ""


def join_key(text, legacy=False):
    """跨年对应用：全角括号、逗号换半角，其余照旧。浙江同一专业不同年份全角、半角混用
    （如东南大学“临床医学（5+3一体化）”2024 年用全角），不统一会让旧年位次静默丢失；
    只换写法宽度，不去空格、标签或括号内容，免得把真正不同的条目并成一条。
    legacy=True 只去首尾空白（2026-10-17 以前的做法），仅供复现已登记的回溯案例。"""
    text = (text or "").strip()
    return text if legacy else text.replace("（", "(").replace("）", ")").replace("，", ",")


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
    ap.add_argument("--exclude", default=None, help="名称/专业中含这些词的条目排除（正则，空串表示不排除）；专项、预科、民族班、少数民族、面向某地的定向、联合培养等需要单独资格或异地培养，默认排除")
    ap.add_argument("--match", help="只保留名称或专业匹配该正则的条目")
    ap.add_argument("--match-major", help="只保留专业名（key=major 时的专业名，不含校名）匹配该正则的条目；--match 会连校名一起匹配，如“信息工程”会命中南京信息工程大学的所有专业")
    ap.add_argument("--exclude-major", help="排除专业名匹配该正则的条目（只看专业名，不含校名）")
    ap.add_argument("--in-provinces", help="只保留位于这些省市的院校，逗号分隔，如 浙江省,上海市,江苏省；与 --in-province 不同时使用")
    ap.add_argument("--rank-min", type=int, help="最近一年位次下限")
    ap.add_argument("--rank-max", type=int, help="最近一年位次上限")
    ap.add_argument("--legacy-join", action="store_true",
                    help="跨年对应不统一全角、半角括号与逗号（2026-10-17 以前的做法）；只用于复现已登记的回溯案例，新任务不要用")
    ap.add_argument("--plan-brackets", choices=["tag", "legacy"], default="tag",
                    help="校名带招生计划类括号（八协计划等）时：tag（默认）按括号外校名对名单、保留并在 limits 列标“资格待核：计划名”；"
                         "legacy 为 2026-10-22 以前的做法（括号当校区，与所在地不符即提醒，回溯流程据此剔除），只用于复现已登记的回溯案例")
    ap.add_argument("--screening-log", help="把本步各原因剔除的条数、对不上名单的条目和标“资格待核”的条目写成 JSON，供 screening.json 记账")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tagged = a.plan_brackets == "tag"
    default_exclude = a.exclude is None
    if default_exclude:
        a.exclude = EXCLUDE_TAGGED if tagged else EXCLUDE
    by_code, by_name = schools()
    years = sorted((int(y), p) for y, p in (s.split("=", 1) for s in a.year))
    if len({y for y, _ in years}) != len(years):
        ap.error("--year 不可重复指定同一年")
    if a.in_province and a.in_provinces:
        ap.error("--in-province 与 --in-provinces 不能同时使用")
    if a.group_map and a.key != "group":
        ap.error("--group-map 仅用于 --key group")
    try:
        group_map = load_group_map(a.group_map, a.school)
    except ValueError as exc:
        ap.error(str(exc))
    last = years[-1][0]
    table = {}
    base_scopes = {}
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
                    k = (join_key(school_key, a.legacy_join), join_key(sub, a.legacy_join))
                try:
                    provenance = input_provenance(r, y)
                    plan_scope = input_plan_scope(r, provenance)
                except (ValueError, TypeError) as exc:
                    ap.error(f"{y} 年 {school}·{sub} 来源信息无效：{exc}")
                base_key = k
                signature = None if plan_scope is None else tuple(plan_scope.items())
                if plan_scope is not None and all(value in UNKNOWN_PLAN for value in plan_scope.values()):
                    signature = ("unknown_year", y, signature)
                if signature is not None:
                    k = (k, signature)
                base_scopes.setdefault(base_key, {}).setdefault(y, set()).add(signature)
                e = table.setdefault(k, {"code": code, "school": school, "sub": sub.strip(),
                                         "req": "", "ranks": {}, "plan": "", "sources": [], "ambiguous": set(), "major_code": "", "provenance": {}, "grades": {},
                                         "plan_scope": plan_scope, "base_key": base_key, "signature": signature})
                if y in e["ambiguous"]:
                    continue
                if y in e["ranks"]:
                    if a.key == "group":
                        ap.error(f"{y} 年 {school}·{sub} 出现重复键，不能静默覆盖；先核对校区、招生条件和专业代码")
                    e["ambiguous"].add(y)
                    del e["ranks"][y]
                    e["provenance"].pop(y, None)
                    e["grades"].pop(y, None)
                    # 同校同名专业的不同校区/类型，整年剔除，不能任选一条
                    continue
                if provenance:
                    e["provenance"][y] = provenance
                grade = (r.get("source_grade") or "").strip()
                if grade:
                    e["grades"][y] = grade
                e["ranks"][y] = int(rk)
                e["code"] = code  # 保留最近一年的院校代码，填报单用
                e["school"], e["sub"] = school, sub.strip()
                e["plan"] = r.get("plan") or ""  # 最新年份未知时，不冒用旧计划
                e["major_code"] = (r.get("major_code") or "").strip()  # 填报单用；专业+院校省份的专业代号，随最近一年
                if mapped:
                    e["sources"].append(f"{y}: {mapped[1]}")
                if a.key == "group":
                    e["req"] = (r.get("major") or "").strip()  # 专业组省份的 major 列存的是选科要求
    rows, unmatched = [], 0
    log = {"plan_brackets": a.plan_brackets, "dropped": {}, "unmatched": [], "eligibility_pending": []}
    drop = lambda why: log["dropped"].__setitem__(why, log["dropped"].get(why, 0) + 1)
    for e in table.values():
        sub = e["sub"]
        code = e["code"]
        if last not in e["ranks"]:
            continue
        school, plans = plan_split(e["school"]) if tagged else (e["school"], [])
        info = lookup(code, school, by_code, by_name)
        text = e["school"] + " " + e["sub"] + " " + e["req"]  # 专业组省份的专项、预科、中外合作标记常写在选科要求一栏
        eligibility_text = text
        structured_text = ""
        if e["plan_scope"] is not None:
            structured_text = " ".join("（" + value + "）" for value in e["plan_scope"].values() if value)
            eligibility_text += " " + structured_text
        if (a.exclude and re.search(a.exclude, eligibility_text + " " + info.get("note", ""))
                or default_exclude and structured_text and re.search(EXCLUDE_TAGGED, structured_text)):
            drop("排除词（需单独资格、异地培养或学费不同）")
            continue
        if not info:
            unmatched += 1
            log["unmatched"].append(e["school"] + "·" + sub)
        if a.public and (not info or info.get("note")):
            drop("院校未匹配教育部名单（办学性质不明）" if not info else "民办或中外合作（教育部名单备注）")
            continue
        if a.in_province and (not info or (info.get("province") == a.in_province) == a.out_province):
            drop("所在省不符或未知")
            continue
        if a.match and not re.search(a.match, text):
            continue
        if a.match_major and not re.search(a.match_major, sub):
            continue
        if a.exclude_major and re.search(a.exclude_major, sub):
            continue
        if a.in_provinces and (not info or info.get("province") not in a.in_provinces.split(",")):
            drop("所在省不符或未知")
            continue
        rl = e["ranks"][last]
        if (a.rank_min and rl < a.rank_min) or (a.rank_max and rl > a.rank_max):
            continue
        name = f"{e['school']}·{sub}组" if a.key == "group" else f"{e['school']}·{sub}"
        row = {"id": f"{code}-{sub}", "name": name, "code": code, "group": sub if a.key == "group" else "",
               "major_code": e["major_code"] if a.key == "major" else "", "requirement": e["req"], "province": info.get("province", "未知"), "city": info.get("city", ""),
               "plan": e["plan"]}
        row["history_status"] = ("verified" if len(e["ranks"]) > 1 else "latest_only") if a.key == "group" else "by_major"
        row["note"] = "；".join(e["sources"]) if e["sources"] else ("专业组跨年组成未核实，只用最近一年" if a.key == "group" else "")
        if e["ambiguous"]:
            row["note"] += "；重复专业键已剔除年份：" + ",".join(map(str, sorted(e["ambiguous"])))
        scope_gaps = [y for y, signatures in base_scopes[e["base_key"]].items()
                      if y < last and y not in e["ranks"] and any(s != e["signature"] for s in signatures)]
        if scope_gaps:
            row["note"] += "；计划条件不同或未明，未采用以下年份：" + ",".join(map(str, sorted(scope_gaps)))
            log.setdefault("plan_scope_history_gaps", []).append({"id": row["id"], "name": name, "years": sorted(scope_gaps)})
        warn = campus_warning(school, info)
        if warn:
            row["note"] = (row["note"] + "；" if row["note"] else "") + warn
        if tagged or e["plan_scope"] is not None:
            pending = list(dict.fromkeys((plans if tagged and info else []) + pending_scope_plans(e["plan_scope"])))
            row["limits"] = f"{PENDING}：{'、'.join(pending)}" if pending else ""
            if row["limits"]:
                log["eligibility_pending"].append(name)
        if e["plan_scope"] is not None:
            row.update(e["plan_scope"])
        for y, _ in reversed(years):
            row[f"rank_{y}"] = e["ranks"].get(y, "")
        if e["provenance"] or e["grades"]:
            if e["provenance"]:
                row["data_provenance"] = json.dumps(e["provenance"], ensure_ascii=False, sort_keys=True)
            # 不以逐值抽核结果覆盖原始 grade，也不把另一字段的官方来源借给位次。
            row["source_grade"] = weakest_grade(list(e["grades"].values()) + [
                v.get("display_grade") or v.get("grade", "")
                for fields in e["provenance"].values() for v in fields.values()
                if v.get("value") is not None])
        rows.append(row)
    id_counts = {}
    for row in rows:
        id_counts[row["id"]] = id_counts.get(row["id"], 0) + 1
    structured_ids = {row["id"] for row in rows if "plan_type" in row}
    ambiguous_ids = {identity for identity, count in id_counts.items() if count > 1 and identity in structured_ids}
    if ambiguous_ids:
        rows = [row for row in rows if row["id"] not in ambiguous_ids]
        log["plan_scope_ambiguous_ids"] = sorted(ambiguous_ids)
        log["dropped"]["同一志愿有多个计划口径，须先按计划类型筛选来源"] = sum(id_counts[identity] for identity in ambiguous_ids)
        kept_ids = {row["id"] for row in rows}
        if "plan_scope_history_gaps" in log:
            log["plan_scope_history_gaps"] = [item for item in log["plan_scope_history_gaps"] if item["id"] in kept_ids]
    log["eligibility_pending"] = [row["name"] for row in rows if PENDING in row.get("limits", "")]
    rows.sort(key=lambda r: r[f"rank_{last}"])
    unknown = sum(r["province"] == "未知" for r in rows)
    cols = ["id", "name", "code", "group", "major_code", "requirement", "province", "city", "plan", "history_status", "note"] + (["limits"] if tagged or any("limits" in row for row in rows) else []) + [f"rank_{y}" for y, _ in reversed(years)]
    cols += [key for key in ("plan_type", "source_admission_type_raw") if any(key in row for row in rows)]
    cols += [key for key in ("source_grade", "data_provenance") if any(key in row for row in rows)]
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
    if log["eligibility_pending"]:
        print(f"⚠ {len(log['eligibility_pending'])} 个条目含招生计划条件，已标“{PENDING}”：填报前须按当年招生章程核对报名资格")
    if ambiguous_ids:
        print(f"⚠ {len(ambiguous_ids)} 个志愿因计划口径不唯一未写出；先在来源导出时明确计划类型")
    if a.screening_log:
        with open(a.screening_log, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
