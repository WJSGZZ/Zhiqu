#!/usr/bin/env python3
"""交叉核对由官方一分一段表整理的 CSV 与可选投档表。

一分一段 CSV 必须含 score 与 cumulative / cum；count 可选。
末尾若有同分重复且代表“该分以下”汇总，必须显式传 --trailing-below-score-summary 分数。
投档表如传入 --admissions，需有 score 与 rank 列；检查最低分、最低位次是否落在该分累计表给出的并列区间。

示例：
  python3 scripts/check_yfyd.py data/hebei/yfyd_physics_2021.csv \
      --admissions data/hebei/physics_2021.csv
  python3 scripts/check_yfyd.py data/hunan/yfyd_physics_2023.csv \
      --trailing-below-score-summary 100
"""
import argparse
import csv
import sys


def integer(value, label, line, issues, *, optional=False):
    value = (value or "").strip()
    if not value and optional:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        issues.append(f"第 {line} 行 {label} 不是整数：{value!r}")
        return None
    return number


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = set(reader.fieldnames or [])
    return rows, headers


def check_yfyd(path, trailing_below_score_summary=None):
    issues, warnings = [], []
    try:
        rows, headers = read_csv(path)
    except (OSError, csv.Error) as exc:
        return {"issues": [f"无法读取 {path}: {exc}"], "warnings": [], "segments": {}, "range": None}
    score_col = "score"
    cum_col = "cumulative" if "cumulative" in headers else "cum" if "cum" in headers else None
    if not rows:
        return {"issues": ["空文件"], "warnings": [], "segments": {}, "range": None}
    missing = {score_col} - headers
    if not cum_col:
        missing.add("cumulative 或 cum")
    if missing:
        return {"issues": ["缺少必要列：" + ", ".join(sorted(missing))], "warnings": [], "segments": {}, "range": None}

    parsed = []
    for i, row in enumerate(rows, start=2):
        score = integer(row.get(score_col), score_col, i, issues)
        cum = integer(row.get(cum_col), cum_col, i, issues)
        count = integer(row.get("count"), "count", i, issues, optional=True) if "count" in headers else None
        source = (row.get("source") or "").strip()
        if score is None or cum is None:
            continue
        if score < 0 or cum < 0 or (count is not None and count < 0):
            issues.append(f"第 {i} 行 score/count/cumulative 不得为负数")
        if count is not None and count > cum:
            issues.append(f"第 {i} 行本段人数 {count} 大于累计数 {cum}")
        parsed.append({"score": score, "cum": cum, "count": count, "source": source, "line": i})

    if not parsed:
        return {"issues": issues or ["没有有效数据行"], "warnings": warnings, "segments": {}, "range": None}

    summary_index = None
    if trailing_below_score_summary is not None:
        matching = [i for i, row in enumerate(parsed) if row["score"] == trailing_below_score_summary]
        if len(parsed) < 2 or len(matching) != 2 or matching != [len(parsed) - 2, len(parsed) - 1]:
            issues.append(
                f"声明末尾 {trailing_below_score_summary} 分以下汇总失败：要求文件最后两行恰为该分数，且该分数仅出现两次"
            )
        else:
            summary_index = len(parsed) - 1

    for i in range(1, len(parsed)):
        prev, cur = parsed[i - 1], parsed[i]
        if cur["score"] > prev["score"]:
            issues.append(f"第 {cur['line']} 行分数 {cur['score']} 高于上一行 {prev['score']}，顺序应为降序")
        if cur["score"] == prev["score"] and not (summary_index == i and summary_index == len(parsed) - 1):
            issues.append(f"第 {cur['line']} 行与上一行分数重复 {cur['score']}；若末档是低于该分的汇总行，请显式声明")
        if cur["cum"] < prev["cum"]:
            issues.append(f"第 {cur['line']} 行累计数 {cur['cum']} 小于上一行 {prev['cum']}")

    missing_counts = sum(r["count"] is None for r in parsed)
    if "count" not in headers:
        warnings.append("无 count 列，无法核验 count 与累计数递推")
    elif missing_counts:
        warnings.append(f"{missing_counts} 行 count 为空，相关递推无法核验")

    for i, cur in enumerate(parsed):
        if cur["count"] is None:
            continue
        if i == 0:
            if cur["cum"] < cur["count"]:
                issues.append(f"第 {cur['line']} 行累计数小于本行人数")
            continue
        prev = parsed[i - 1]
        # 前行累计若为插值，递推无独立基准；提示而不拿估值判错。
        if prev["source"] == "插值":
            warnings.append(f"第 {cur['line']} 行 count 可见，但上一行累计标记为插值，跳过递推认证")
            continue
        expected = prev["cum"] + cur["count"]
        if cur["cum"] != expected:
            issues.append(f"第 {cur['line']} 行累计 {cur['cum']} != 上一行累计 {prev['cum']} + 本行人数 {cur['count']} (= {expected})")

    # 仅用于投档表核对的精确分数段映射；明确声明的末尾汇总行不代表精确同分段。
    segments = {}
    for i, row in enumerate(parsed):
        if i == summary_index:
            continue
        if row["score"] in segments:
            continue
        low = None
        if row["source"] == "插值":
            continue  # 插值分段不认证真实同分区间
        if row["count"] is not None:
            low = row["cum"] - row["count"] + 1
        elif i > 0 and parsed[i - 1]["score"] == row["score"] + 1 and parsed[i - 1]["source"] != "插值":
            low = parsed[i - 1]["cum"] + 1
        if low is not None and low < 1:
            issues.append(f"第 {row['line']} 行按累计-人数计算的并列位次下界无效：{low}")
        segments[row["score"]] = (low, row["cum"])

    values = [r["score"] for i, r in enumerate(parsed) if i != summary_index]
    score_range = (min(values), max(values)) if values else None
    warnings.append("仅认证表内公布分数范围；高于最高分或低于最低分的分数不在本表核验范围，未据此认证最高档覆盖完整")
    return {"issues": issues, "warnings": warnings, "segments": segments, "range": score_range}


def check_admissions(path, segments, score_range):
    issues, warnings = [], []
    try:
        rows, headers = read_csv(path)
    except (OSError, csv.Error) as exc:
        return [f"无法读取投档表 {path}: {exc}"], warnings
    if not {"score", "rank"} <= headers:
        return ["投档表缺少 score 或 rank 列"], warnings
    checked = 0
    for line, row in enumerate(rows, start=2):
        score = integer(row.get("score"), "投档 score", line, issues, optional=True)
        rank = integer(row.get("rank"), "投档 rank", line, issues, optional=True)
        if score is None or rank is None:
            continue
        if score_range is None or score < score_range[0] or score > score_range[1]:
            warnings.append(f"投档表第 {line} 行最低分 {score} 超出统计表公布范围，跳过")
            continue
        if score not in segments:
            warnings.append(f"投档表第 {line} 行最低分 {score} 无对应分数段，跳过")
            continue
        low, high = segments[score]
        if low is None:
            warnings.append(f"投档表第 {line} 行最低分 {score} 的同分段下界无法确定，跳过位次认证")
            continue
        checked += 1
        if not low <= rank <= high:
            issues.append(f"投档表第 {line} 行最低分/位次 {score}/{rank} 不在同分位次区间 {low}–{high}")
    warnings.append(f"投档表匹配 {checked} 行最低分/最低位次")
    return issues, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验官方一分一段表整理数据及可选投档表最低位次")
    parser.add_argument("yfyd_csv", help="一分一段 CSV，含 score,cumulative 或 score,cum")
    parser.add_argument("--admissions", help="可选投档表 CSV，需含 score,rank")
    parser.add_argument(
        "--trailing-below-score-summary", type=int, metavar="分数",
        help="显式声明最后一行是低于该分的汇总行，且其 score 重复阈值分数；该行不作为精确同分段"
    )
    args = parser.parse_args(argv)

    result = check_yfyd(args.yfyd_csv, args.trailing_below_score_summary)
    if result["range"]:
        low, high = result["range"]
        print(f"公布分数范围：{low}–{high}")
    for warning in result["warnings"]:
        print(f"⚠ {warning}")
    issues = list(result["issues"])
    if args.admissions and not issues:
        more, warnings = check_admissions(args.admissions, result["segments"], result["range"])
        issues.extend(more)
        for warning in warnings:
            print(f"⚠ {warning}")
    for issue in issues:
        print(f"错误：{issue}", file=sys.stderr)
    if issues:
        return 1
    print("已参与的检查未发现错误；告警及未参与部分仍待核实")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
