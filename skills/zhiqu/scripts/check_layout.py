#!/usr/bin/env python3
"""检查生成的 PDF 报告版面：表格某一栏被挤成一字一行、数字被拆成两行、正文页中间留下大片空白。

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


MM = 72 / 25.4
PAGE_MARGIN = 20 * MM   # 与 report.py 的 @page 上下边距 20mm 一致：版心是去掉页眉页脚边距后的区域
BLANK_RATIO = 0.35      # 连续空白超过版心高度的这个比例就报错


def _blank_info(page):
    """返回本页是否有页眉（封面没有）、版心内各段连续空白 [(起, 止)]、版心第一行（y0, 文字, 最大字号）。"""
    w, h = page.rect.width, page.rect.height
    top, bot = PAGE_MARGIN, h - PAGE_MARGIN
    occupied, lines, header = [], [], False
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            text = "".join(s["text"] for s in l["spans"]).strip()
            if not text:
                continue
            y0, y1 = l["bbox"][1], l["bbox"][3]
            if y1 < top:
                header = True
                continue
            if y0 > bot:
                continue
            occupied.append((y0, y1))
            lines.append((y0, text, max(s["size"] for s in l["spans"])))
    for d in page.get_drawings():  # 图表、卡片底色、分隔线；整页底色不算内容
        r = d["rect"]
        if r.width * r.height < 0.5 * w * h and r.y1 > top and r.y0 < bot:
            occupied.append((max(r.y0, top), min(r.y1, bot)))
    for im in page.get_image_info():
        y0, y1 = im["bbox"][1], im["bbox"][3]
        if y1 > top and y0 < bot:
            occupied.append((max(y0, top), min(y1, bot)))
    gaps, cur = [], top
    for a, b in sorted(occupied):
        if a > cur:
            gaps.append((cur, a))
        cur = max(cur, b)
    if bot > cur:
        gaps.append((cur, bot))
    return {"header": header, "gaps": gaps, "height": bot - top, "first": min(lines) if lines else None}


def _starts_section(info):
    """下一页以一级小节标题（“05 方向比较”，标题字号约 18）开头：本页是节末最后一页。"""
    first = info["first"]
    return bool(first) and first[2] >= 16 and re.match(r"^\d{2}\s*\S", first[1]) is not None


def blank_issues(doc, ratio=BLANK_RATIO):
    """正文页连续空白超过版心高度的 ratio 即报错。

    不查封面（没有页眉）、含“目录”的页、全书最后一页和节末最后一页（下一页以新的一级小节开头），
    那几处留白是正常的分节；节中间因为整块图表或表格换页留下的大片空白要报出来。
    """
    infos = [_blank_info(p) for p in doc]
    issues = []
    for i, info in enumerate(infos):
        if not info["header"] or i == len(infos) - 1 or _starts_section(infos[i + 1]):
            continue
        if "目录" in (ln.strip() for ln in doc[i].get_text().split("\n")):
            continue
        a, b = max(info["gaps"], key=lambda g: g[1] - g[0], default=(0, 0))
        if (b - a) > ratio * info["height"]:
            issues.append((i + 1, f"正文页中间留下大片空白：从距页顶 {a / MM:.0f}mm 到 {b / MM:.0f}mm，"
                                  f"占版心高度 {(b - a) / info['height']:.0%}（上限 {ratio:.0%}）；"
                                  "多半是整块图表或表格挤到下一页，先调内容顺序"))
    return issues


def check_pdf(path):
    import pymupdf
    doc = pymupdf.open(path)
    found = []
    for i, page in enumerate(doc):
        for msg in dict.fromkeys(check_page(page)):
            found.append(f"第 {i + 1} 页：{msg}")
    for page_no, msg in blank_issues(doc):
        found.append(f"第 {page_no} 页：{msg}")
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
