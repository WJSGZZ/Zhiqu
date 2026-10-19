#!/usr/bin/env python3
"""检查生成的 PDF 报告版面：表格某一栏被挤成一字一行、数字被拆成两行。

用法：python3 check_layout.py 报告.pdf [更多.pdf ...]
发现问题时逐条列出页码和原因，退出码 1；没有问题退出码 0。
需要 PyMuPDF（pip install pymupdf）；report.py、render_report.py 生成 PDF 后会自动调用。
"""
import re
import sys
from collections import defaultdict

COMPLETE_NUMBER = re.compile(r"(?:约|不到|超过|<|>|≤|≥)?\s*\d+(?:[,.]\d+)*\s*%?")
CJK_OR_DIGIT = re.compile(r"^[一-鿿0-9%（）()·\-–—.,，。、：:；;/]+$")


def _lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            text = "".join(s["text"] for s in l["spans"]).strip()
            if not text:
                continue
            size = max(s["size"] for s in l["spans"])
            x0, y0, x1, y1 = l["bbox"]
            out.append({"x": x0, "y": y0, "w": x1 - x0, "t": text, "size": size})
    return out


def _chains(lines, keep):
    """把同一列（左边对齐）、上下紧挨着的行串起来，返回每条连续行链。"""
    cols = defaultdict(list)
    for ln in lines:
        if keep(ln):
            cols[round(ln["x"] / 3)].append(ln)
    chains = []
    for col in cols.values():
        col.sort(key=lambda d: d["y"])
        run = [col[0]]
        for prev, cur in zip(col, col[1:]):
            if cur["y"] - prev["y"] < 2.0 * max(prev["size"], cur["size"]):
                run.append(cur)
            else:
                chains.append(run)
                run = [cur]
        chains.append(run)
    return chains


def check_page(page):
    issues = []
    lines = _lines(page)
    # 一栏被挤成一两个字一行（中文或数字），连续 3 行以上
    for run in _chains(lines, lambda d: len(d["t"]) <= 2 and CJK_OR_DIGIT.match(d["t"]) and not re.fullmatch(r"\d{1,2}%", d["t"])):
        if len(run) >= 3:
            issues.append(f"有一栏被挤成一字一行（{''.join(d['t'] for d in run)[:12]}…）")
    # 数字被拆成两行：上下相邻的两个单独数字
    for run in _chains(lines, lambda d: re.fullmatch(r"\d", d["t"])):
        if len(run) >= 2:
            issues.append(f"数字被拆成两行（{''.join(d['t'] for d in run)}）")
    # 窄栏：连续 6 行以上、每行很短很窄，正文被挤成细条
    for run in _chains(lines, lambda d: d["w"] < 80 and len(d["t"]) <= 10 and not COMPLETE_NUMBER.fullmatch(d["t"])):
        if len(run) >= 8:
            issues.append(f"有一栏过窄，文字被挤成细条（{''.join(d['t'] for d in run)[:12]}…）")
    # 中文正文被挤进很窄的一栏：同一格里连续 15 行以上、每行不到约 12 个字宽（网址换行不算）
    def cjk_ratio(s):
        return sum("\u4e00" <= ch <= "\u9fff" for ch in s) / max(len(s), 1)
    for run in _chains(lines, lambda d: d["w"] < 120):
        if len(run) >= 15 and cjk_ratio("".join(d["t"] for d in run)) >= 0.5:
            issues.append(f"有一栏中文被挤得很窄，一格拉得很长（{run[0]['t'][:10]}…）")
    return issues


def check_pdf(path):
    import pymupdf
    doc = pymupdf.open(path)
    found = []
    for i, page in enumerate(doc):
        for msg in dict.fromkeys(check_page(page)):
            found.append(f"第 {i + 1} 页：{msg}")
    return found


def main(argv=None):
    paths = (argv if argv is not None else sys.argv[1:])
    if not paths:
        print(__doc__)
        return 2
    bad = 0
    for p in paths:
        issues = check_pdf(p)
        if issues:
            bad += 1
            print(f"✗ {p}")
            for msg in issues:
                print(f"    {msg}")
        else:
            print(f"✓ {p}：版面检查通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
