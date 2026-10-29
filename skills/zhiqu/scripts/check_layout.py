#!/usr/bin/env python3
"""检查生成的 PDF 报告版面：表格某一栏被挤成一字一行、数字被拆成两行、正文页中间留下大片空白、
节末或全文最后一页只剩一两行收尾内容（孤页）。

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
BLANK_RATIO = 0.30      # 连续空白超过版心高度的这个比例就报错（2026-10-20：33% 的空白肉眼已明显，从 0.35 收紧）


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


TAIL_LINES = 3        # 节末或全文最后一页只剩这么几行正文就算孤页
TAIL_OCCUPIED = 0.15  # 且这一页内容占版心不到这个比例（整页图表、表格不算孤页）
SECTION_HEAD = re.compile(r"^(\d{2})\s*\S")


def _section_heads(page):
    """本页出现的一级小节标题编号（标题字号约 18；正文里的“12 个”字号小，不会误认）。"""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            text = "".join(s["text"] for s in l["spans"]).strip()
            if text and max(s["size"] for s in l["spans"]) >= 16 and SECTION_HEAD.match(text):
                out.append(SECTION_HEAD.match(text)[1])
    return out


def _short_table_rows(lines, page=None):
    """只识别同一基线的多栏短尾；避免把普通四五行段落也当三行孤尾。"""
    bands=[]
    for line in sorted(lines,key=lambda item:item['y']):
        if not bands or abs(line['y']-bands[-1][0]['y'])>2:
            bands.append([line])
        else:
            bands[-1].append(line)
    if not 2<=len(bands)<=5:
        return None
    if not all(len(band)>=2 and max(x['x'] for x in band)-min(x['x'] for x in band)>40
               for band in bands) or page is None:
        return None
    # 双栏段落也会共享基线；必须有跨过所有单元格的表格横线，一带一格。
    left=min(line['x'] for line in lines)
    right=max(line['x']+line.get('w',0) for line in lines)
    segments=defaultdict(list)
    for drawing in page.get_drawings():
        rect=drawing['rect']
        if rect.height<=1.5 and rect.width>0:
            segments[round(rect.y0,1)].append((rect.x0,rect.x1))
    rules=[]
    for y,parts in segments.items():
        merged=[]
        for start,end in sorted(parts):
            if merged and start<=merged[-1][1]+1:
                merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else:merged.append((start,end))
        if any(a<=left and b>=right for a,b in merged):rules.append(y)
    rules.sort()
    intervals=[]
    for band in bands:
        y=band[0]['y']
        interval=next((i for i,(a,b) in enumerate(zip(rules,rules[1:])) if a<y<b),None)
        if interval is None:return None
        intervals.append(interval)
    if len(set(intervals))==len(bands):
        return len(bands)
    return None


def tail_orphans(doc):
    """节末或全文最后一页只剩一两行收尾文字的页：[(页码, 所在小节编号, 行数)]。

    只查有页眉的正文页，且下一页开新节或已是全文最后一页。
    若稀疏尾页先续上一节几行、再开新节，仍归前一节收紧，不让新标题掩盖孤尾。
    小节编号取这一页之前最近的一级标题，供生成器收紧那一节的行距后重排。
    """
    infos = [_blank_info(p) for p in doc]
    heads = [_section_heads(p) for p in doc]
    current, owner = None, []
    for h in heads:
        owner.append(current if not h else h[0])
        current = h[-1] if h else current
    out = []
    for i, info in enumerate(infos):
        if i == 0 or not info["header"]:
            continue
        if i < len(infos) - 1 and not _starts_section(infos[i + 1]):
            continue
        top, bot = PAGE_MARGIN, doc[i].rect.height - PAGE_MARGIN
        lines = [ln for ln in _lines(doc[i]) if top <= ln["y"] <= bot]
        used = 1 - sum(b - a for a, b in info["gaps"]) / info["height"]
        sid = owner[i]
        if heads[i]:
            # 只查新节标题前的续行；整页仍须稀疏。正常的新节首页不受影响。
            visible_heads = [ln["y"] for ln in lines
                             if ln["size"] >= 16 and SECTION_HEAD.match(ln["t"])]
            if not visible_heads:  # 整页扫描可能只在页眉/页边界找到大字号编号。
                continue
            first_head = min(visible_heads)
            lines = [ln for ln in lines if ln["y"] < first_head]
            sid = heads[i - 1][-1] if heads[i - 1] else owner[i - 1]
        count=len(lines)
        if (not heads[i] and sid in {f'{n:02}' for n in range(1,12)}
                and not any(ln['t']=='目录' for ln in lines)):
            # 五行双栏短表会成为十条PDF文本行；按视觉行检查，不让新节豁免遮住整块孤表。
            count=_short_table_rows(lines,doc[i]) or count
        limit=5 if count!=len(lines) else TAIL_LINES
        if 0 < count <= limit and used < TAIL_OCCUPIED:
            out.append((i + 1, sid, count))
    return out


def check_pdf(path):
    import pymupdf
    doc = pymupdf.open(path)
    found = []
    for i, page in enumerate(doc):
        for msg in dict.fromkeys(check_page(page)):
            found.append(f"第 {i + 1} 页：{msg}")
    for page_no, msg in blank_issues(doc):
        found.append(f"第 {page_no} 页：{msg}")
    for page_no, sid, n in tail_orphans(doc):
        found.append(f"第 {page_no} 页：节末孤页，只剩 {n} 行收尾内容（{sid or '?'} 节）；"
                     "生成器已试过收紧该节行距仍放不回上一页，先删短或调整这一节的内容")
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
