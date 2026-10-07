#!/usr/bin/env python3
"""按专业类别看相邻两年的整体位次变化（专业+院校省份，按“校名+专业名”对应）。

用途：全省漂移之外，某一类专业可能整体变热或变冷（共同偏差）。本脚本只描述，不改预测：
中位数 < 0 表示位次数字变小，即录取更难；“变难占比”是该类里变难的条目比例。
usage: python3 scripts/category_shift.py data/zhejiang/general_2025.csv data/zhejiang/general_2026.csv --class 电气:电气 --class 自动化:自动化
"""
import argparse
import csv
import math
import re
import statistics


def load(path):
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("rank") or "").strip().isdigit():
                out[(r["name"], r["major"])] = int(r["rank"])
    return out


def shifts(old, new):
    return {k: math.log(new[k] / old[k]) for k in new if k in old}


def summarize(changes, pattern):
    """专业名（括号前）以 pattern 开头的条目：(条目数, 位次对数变化中位数, 变难占比)。"""
    xs = [c for (_, major), c in changes.items() if re.match(pattern, re.split(r"[（(]", major)[0])]
    if not xs:
        return 0, None, None
    return len(xs), statistics.median(xs), sum(x < 0 for x in xs) / len(xs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--class", dest="classes", action="append", default=[], help="名称:正则（匹配括号前的专业名开头），可重复")
    a = ap.parse_args()
    ch = shifts(load(a.old), load(a.new))
    if not ch:
        ap.error("两年没有可对应的条目")
    print(f"可对应条目 {len(ch)}；全部专业位次对数变化中位数 {statistics.median(ch.values()):+.3f}")
    for spec in a.classes:
        name, _, pat = spec.partition(":")
        n, med, harder = summarize(ch, pat or name)
        print(f"{name}：{n} 条，中位数 {med:+.3f}，变难占比 {harder:.0%}" if n else f"{name}：没有匹配条目")


if __name__ == "__main__":
    main()
