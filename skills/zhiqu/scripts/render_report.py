#!/usr/bin/env python3
"""知衢 · 通用 Markdown 报告渲染器（仅用 Python 标准库；PDF 由本机 Chrome/Edge 无头模式打印）。

给读研版（zhiqu-grad）和求职版（zhiqu-career）用：这两个技能把报告写成固定
12 节结构的 Markdown（见 skills/zhiqu-grad/references/report-guide.md 和
skills/zhiqu-career/references/report-guide.md），本脚本把它渲染成与高考版
report.py 相同视觉风格的 HTML/PDF。

用法：
  python3 scripts/render_report.py report.md --out report.pdf
  python3 scripts/render_report.py report.md --out report.html   # 只要 HTML

Markdown 格式：
  可选的 YAML 风格前言（两行 `---` 之间），支持字段：
    title      报告标题
    subtitle   副标题
    person     考生/本人，如"虚构示例 · 小周"
    date       报告日期
    edition    版本，如"读研版"/"求职版"
    note       封面备注

  正文：`## 01 摘要` … `## 12 ...` 为一级小节（对应 report.py 里的
  section），`### ` 为小节内小标题；支持段落、**加粗**、*斜体*、`代码`、
  链接 `[文字](网址)`、无序/有序列表（一层嵌套）、GitHub 风格的 `|` 表格、
  引用块 `> `、分隔线 `---`/`***`。不支持原始 HTML 透传，文本一律转义。

  与高考版 report.py 同款的版面元素（三版报告视觉一致，摘要页尽量都用上）：
    提示框：引用块首行写 `> [!key] 核心结论`（绿边）、`> [!warn] 接下来要做的事`
           （琥珀边）或 `> [!note] 标题`（无色边），其后各行是框内正文，可含列表。
    数字卡：`::: kpi` 与 `:::` 之间每行 `- 标签 | 数值 | 一句说明`，最多 4 张。
    落点条：`::: strip 标题` 与 `:::` 之间每行 `- 志愿名 | 概率`（如 73.3%），
           可加一行 `- 滑档 | 概率`；按志愿顺序画“最终会被哪里录取”的色条。
    表格里内容恰为“冲”“稳”“保”的格子自动画成彩色标签。

找不到浏览器时会只输出 HTML，并提示用浏览器"打印 → 存储为 PDF"（与
report.py 行为一致）。
"""
import argparse
import html
import importlib.util
import os
import re
import sys

E = html.escape

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_report_module():
    """从同目录的 report.py 里取 CSS 和 find_browser，尽量复用而不是复制。"""
    path = os.path.join(_SCRIPTS_DIR, "report.py")
    spec = importlib.util.spec_from_file_location("_zhiqu_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _report = _load_report_module()
    CSS = _report.CSS
    find_browser = _report.find_browser
    outcome_strip = _report.outcome_strip
    STRIP_CAP = _report.STRIP_CAP
except Exception:  # pragma: no cover - 极端情况下 report.py 缺失或加载失败
    CSS = ""
    outcome_strip = None
    STRIP_CAP = ""

    def find_browser():
        return None


EXPECTED_SECTION_NUMBERS = [f"{i:02d}" for i in range(1, 13)]


# ---------------------------------------------------------------------------
# 前言解析
# ---------------------------------------------------------------------------

def split_front_matter(text):
    """返回 (meta_dict, body)。前言必须在文件开头，两行 `---` 之间，
    每行 `key: value`。没有前言时 meta 为空字典。"""
    meta = {}
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            for line in lines[1:end]:
                if not line.strip() or ":" not in line:
                    continue
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip()
            return meta, "\n".join(lines[end + 1:])
    return meta, text


# ---------------------------------------------------------------------------
# 行内格式：转义 + **粗体** *斜体* `代码` [链接](url)
# ---------------------------------------------------------------------------

_INLINE_TOKEN_RE = re.compile(
    r"(?P<code>`([^`]+)`)"
    r"|(?P<link>\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\))"
    r"|(?P<bold>\*\*([^*]+)\*\*)"
    r"|(?P<italic>\*([^*]+)\*)"
)


def render_inline(text):
    """把一行/一段文本里的行内标记转成 HTML；普通文本一律转义，不做 HTML 透传。"""
    out = []
    pos = 0
    for m in _INLINE_TOKEN_RE.finditer(text):
        out.append(E(text[pos:m.start()]))
        if m.group("code"):
            out.append(f"<code>{E(m.group(2))}</code>")
        elif m.group("link"):
            label, url = m.group(4), m.group(5)
            safe_url = E(url)
            out.append(f'<a href="{safe_url}">{render_inline(label)}</a>')
        elif m.group("bold"):
            out.append(f"<strong>{render_inline(m.group(7))}</strong>")
        elif m.group("italic"):
            out.append(f"<em>{render_inline(m.group(9))}</em>")
        pos = m.end()
    out.append(E(text[pos:]))
    return "".join(out)


# ---------------------------------------------------------------------------
# 块级解析
# ---------------------------------------------------------------------------

_ATX_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_HR_RE = re.compile(r"^\s*(---+|\*\*\*+|___+)\s*$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_FENCE_RE = re.compile(r"^:::\s*(kpi|strip)\s*(.*)$")
_CALLOUT_RE = re.compile(r"^\[!(key|warn|note)\]\s*(.*)$")
_TAGS = ("冲", "稳", "保")


def _fence_items(lines):
    """`- a | b | c` 形式的行 → [[a, b, c], ...]。"""
    return [_split_table_row(re.sub(r"^\s*[-*+]\s+", "", ln)) for ln in lines if ln.strip()]


def _pct(text):
    m = re.search(r"([\d.]+)\s*%", text)
    return float(m.group(1)) / 100 if m else 0.0


def render_fence(kind, title, lines):
    """渲染 `::: kpi` 数字卡与 `::: strip` 落点条（与 report.py 摘要页同款）。"""
    items = _fence_items(lines)
    if kind == "kpi":
        cards = []
        for row in items[:4]:
            label, value, note = (row + ["", "", ""])[:3]
            # 数字为主的短值用大字；汉字多的（如去向、方向）用小一号，免得在窄卡里折行
            cjk = sum(ord(c) > 0x2E80 for c in value)
            big = ' class="num"' if cjk <= 4 and len(value) <= 12 else ' style="font-size:11pt"'
            cards.append(f"<div><b>{render_inline(label)}</b><span{big}>{render_inline(value)}</span>"
                         + (f"<em>{render_inline(note)}</em>" if note else "") + "</div>")
        return f'<div class="kpis" style="grid-template-columns:repeat({max(len(cards), 1)},1fr)">' + "".join(cards) + "</div>"
    if outcome_strip is None:
        return ""
    pairs = [(r[0], _pct(r[1] if len(r) > 1 else "")) for r in items]
    pfall = sum(p for name, p in pairs if name == "滑档")
    pairs = [(name, p) for name, p in pairs if name != "滑档"]
    cap = STRIP_CAP + "浅色是最终录取概率不到 5% 的志愿" + ("；红色是滑档" if pfall else "") + "。"
    return (f'<div class="fig"><div class="ttl">{render_inline(title or "你最终会被哪里录取")}</div>'
            + outcome_strip(pairs, pfall) + f'<div class="cap">{E(cap)}</div></div>')


def _cell(text):
    if text in _TAGS:
        return f"<td class='c'><span class='tag {text}'>{text}</span></td>"
    return f"<td>{render_inline(text)}</td>"


def _split_table_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _list_html(items, ordered):
    tag = "ol" if ordered else "ul"
    parts = [f"<{tag}>"]
    for text, sub in items:
        parts.append(f"<li>{render_inline(text)}")
        if sub:
            parts.append(_list_html(sub, sub_ordered(sub)))
        parts.append("</li>")
    parts.append(f"</{tag}>")
    return "".join(parts)


def sub_ordered(items):
    return False  # 子列表统一按无序渲染的开关位；由调用处传入真实类型


def _parse_list(lines, i, base_indent, ordered):
    """解析从 lines[i] 开始、缩进 == base_indent 的同类型列表（含一层嵌套子列表）。
    返回 (items, next_i)，items = [(text, sub_items_or_None)]。"""
    items = []
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            break
        m = (_OL_RE if ordered else _UL_RE).match(line)
        if not m or len(m.group(1)) != base_indent:
            break
        text = m.group(2)
        i += 1
        sub_items = None
        # 紧随其后、缩进更深的列表视为一层嵌套（不再深入嵌套）
        if i < n:
            nm_ul = _UL_RE.match(lines[i])
            nm_ol = _OL_RE.match(lines[i])
            nm = nm_ul or nm_ol
            if nm and len(nm.group(1)) > base_indent:
                sub_ordered_flag = nm_ol is not None
                sub_items, i = _parse_list(lines, i, len(nm.group(1)), sub_ordered_flag)
                sub_items = (sub_items, sub_ordered_flag)
        items.append((text, sub_items))
    return items, i


def _render_list_items(items):
    parts = []
    for text, sub in items:
        parts.append(f"<li>{render_inline(text)}")
        if sub:
            sub_items, sub_ordered_flag = sub
            tag = "ol" if sub_ordered_flag else "ul"
            parts.append(f"<{tag}>" + _render_list_items(sub_items) + f"</{tag}>")
        parts.append("</li>")
    return "".join(parts)


def markdown_to_html(body):
    """把 Markdown 正文转成 HTML 片段，同时返回按 `##` 划分的小节列表
    [(number_or_None, title, html)]，number 取标题里开头的两位数字（若有）。"""
    lines = body.split("\n")
    n = len(lines)
    i = 0
    out = []
    sections = []  # (num, title, start_index_in_out)
    cur_section_out = None

    def flush_section():
        nonlocal cur_section_out
        if cur_section_out is not None:
            num, title, start = cur_section_out
            sections.append((num, title, "".join(out[start:])))

    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        m = _ATX_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 2:
                flush_section()
                num_m = re.match(r"^(\d{2})\s+(.*)$", title)
                num = num_m.group(1) if num_m else None
                disp_title = num_m.group(2) if num_m else title
                out.append(f'<section><h2>{f"<span class=\'no\'>{E(num)}</span>" if num else ""}{render_inline(disp_title)}</h2>')
                cur_section_out = (num, disp_title, len(out) - 1)
            else:
                tag = f"h{min(level, 3) if level != 2 else 3}"
                # ATX level 1/3+ 都渲染为 h3（report.py 风格里只有 h2/h3）
                tag = "h3" if level != 2 else "h2"
                out.append(f"<{tag}>{render_inline(title)}</{tag}>")
            i += 1
            continue

        fm = _FENCE_RE.match(line.strip())
        if fm:
            buf = []
            i += 1
            while i < n and lines[i].strip() != ":::":
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(render_fence(fm.group(1), fm.group(2).strip(), buf))
            continue

        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        qm = _QUOTE_RE.match(line)
        if qm:
            buf = [qm.group(1)]
            i += 1
            while i < n and _QUOTE_RE.match(lines[i]):
                buf.append(_QUOTE_RE.match(lines[i]).group(1))
                i += 1
            cm = _CALLOUT_RE.match(buf[0].strip())
            if cm:
                inner, _ = markdown_to_html("\n".join(buf[1:]))
                cls = "" if cm.group(1) == "note" else " " + cm.group(1)
                out.append(f'<div class="box{cls}"><h4>{render_inline(cm.group(2))}</h4>{inner}</div>')
                continue
            para = " ".join(x for x in buf if x is not None).strip()
            out.append(f"<blockquote><p>{render_inline(para)}</p></blockquote>")
            continue

        # 表格：当前行含 |，下一行是分隔行
        if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_table_row(line)
            i += 2
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i] and not _ATX_RE.match(lines[i]):
                rows.append(_split_table_row(lines[i]))
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{render_inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
            for r in rows:
                cells = r + [""] * (len(header) - len(r))
                out.append("<tr>" + "".join(_cell(c) for c in cells[:len(header)]) + "</tr>")
            out.append("</tbody></table>")
            continue

        ulm = _UL_RE.match(line)
        olm = _OL_RE.match(line)
        if ulm or olm:
            ordered = olm is not None
            indent = len((ulm or olm).group(1))
            items, i = _parse_list(lines, i, indent, ordered)
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + _render_list_items(items) + f"</{tag}>")
            continue

        # 普通段落：连续非空、非特殊行合并为一段
        buf = [line]
        i += 1
        while i < n and lines[i].strip() and not _ATX_RE.match(lines[i]) and not _HR_RE.match(lines[i]) \
                and not _UL_RE.match(lines[i]) and not _OL_RE.match(lines[i]) and not _QUOTE_RE.match(lines[i]) \
                and "|" not in lines[i] and not _FENCE_RE.match(lines[i].strip()):
            buf.append(lines[i])
            i += 1
        out.append(f"<p>{render_inline(' '.join(buf))}</p>")

    flush_section()
    return "".join(out), sections


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def validate_sections(sections):
    """检查 `##` 小节编号是否恰好是 01..12 依次出现；不合规只提醒，不报错。"""
    nums = [num for num, _, _ in sections if num is not None]
    if nums != EXPECTED_SECTION_NUMBERS:
        print(
            "提醒：报告小节编号应为 01..12 依次出现一次，实际为：" + (str(nums) if nums else "（未找到编号小节）"),
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# 整页组装（复用 report.py 的封面/目录风格）
# ---------------------------------------------------------------------------

def build_html(meta, body_html, sections):
    title = meta.get("title", "决策报告")
    subtitle = meta.get("subtitle", "")
    person = meta.get("person", "–")
    date = meta.get("date", "–")
    edition = meta.get("edition", "")
    note = meta.get("note", "")

    toc = "".join(
        f"<div><span>{E(num)}</span><span>{E(t)}</span></div>"
        for num, t, _ in sections if num is not None
    )
    meta_rows = [("本人", person), ("版本", edition or "–"), ("报告日期", date)]
    cover = (
        '<div class="cover"><div class="band">'
        '<div class="kicker">知 衢 · 决 策 报 告</div>'
        f'<h1>{E(title)}</h1><div class="sub">{E(subtitle)}</div>'
        '<div class="motto">知其所往，方行其衢。</div></div>'
        '<div class="meta">'
        + "".join(f"<div><b>{E(a)}</b><span>{E(str(b))}</span></div>" for a, b in meta_rows)
        + "</div>"
        + (f'<div class="verdict"><b>备注</b><p>{E(note)}</p></div>' if note else "")
        + f'<div class="verdict" style="background:transparent;border-left-color:var(--rule2)"><b>目录</b><div class="toc">{toc}</div></div>'
        + '<div class="foot">本报告由「知衢」生成，供本人决策参考；数据来源、假设与局限见"方法与假设"和"数据来源与声明"两节。</div></div>'
    )

    body_parts = []
    for idx, (num, t, sec_html) in enumerate(sections):
        # 有编号的小节沿用 report.py 的 <span class="no">编号</span> 结构（已在渲染时写入）；
        # 每个 `##` 小节各占一个 <section>。只有首节另起一页（封面之后），其余接着排，
        # 小节内允许跨页，避免整节被推到下一页而留下大片空白（CSS 见 report.py）。
        cls = ' class="newpage"' if idx == 0 else ""
        sec_html = sec_html.replace("<section>", f"<section{cls}>", 1) if idx == 0 else sec_html
        body_parts.append(sec_html + "</section>")

    runhead = f"{person} · {edition}".replace('"', "")
    css = CSS.replace("__RUNHEAD__", runhead).replace("__TOPLEFT__", "知衢 · " + (title or "决策报告").replace('"', "")) if CSS else ""
    doc = (
        f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>{E(title)}</title>'
        f'<style>{css}</style></head><body>{cover}{"".join(body_parts)}</body></html>'
    )
    return doc


def render(markdown_text):
    """返回 (html_document, sections)。sections 供测试和调用方检查用。"""
    meta, body = split_front_matter(markdown_text)
    body_html, sections = markdown_to_html(body)
    validate_sections(sections)
    doc = build_html(meta, body_html, sections)
    return doc, sections


# ---------------------------------------------------------------------------
# CLI（PDF 打印逻辑与 report.py 一致）
# ---------------------------------------------------------------------------

def _print_pdf(doc, out_path):
    import shutil
    import subprocess
    import tempfile
    import time

    br = find_browser()
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    tmp.write(doc)
    tmp.close()
    if not br:
        html_out = os.path.splitext(out_path)[0] + ".html"
        shutil.copy(tmp.name, html_out)
        sys.exit(f"没有找到 Chrome/Edge，已输出 {html_out}；请用浏览器打开后\"打印 → 存储为 PDF\"（勾选\"背景图形\"）。")
    out = os.path.abspath(out_path)
    if os.path.exists(out):
        os.unlink(out)
    with tempfile.TemporaryDirectory() as prof:
        proc = subprocess.Popen(
            [br, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={prof}",
             f"--print-to-pdf={out}", "file://" + tmp.name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        last, stable, waited = -1, 0, 0.0
        while waited < 120 and stable < 3:
            time.sleep(0.5)
            waited += 0.5
            if proc.poll() is not None and os.path.exists(out):
                break
            size = os.path.getsize(out) if os.path.exists(out) else -1
            stable = stable + 1 if size > 0 and size == last else 0
            last = size
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        sys.exit("PDF 生成失败：请改用 --out 报告.html，再用浏览器打印为 PDF。")
    os.unlink(tmp.name)
    print(f"已生成 {out}")


def main():
    ap = argparse.ArgumentParser(description="知衢 · 把固定 12 节结构的 Markdown 报告渲染成 PDF/HTML")
    ap.add_argument("report", help="报告正文 Markdown（前言字段见脚本顶部说明）")
    ap.add_argument("--out", required=True, help="输出文件，.pdf 或 .html")
    a = ap.parse_args()
    with open(a.report, encoding="utf-8") as f:
        text = f.read()
    doc, _ = render(text)
    if a.out.lower().endswith(".html"):
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(doc)
        print(f"已生成 {a.out}")
        return
    _print_pdf(doc, a.out)


if __name__ == "__main__":
    main()
