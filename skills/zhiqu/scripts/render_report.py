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
except Exception:  # pragma: no cover - 极端情况下 report.py 缺失或加载失败
    CSS = ""

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
                out.append("<tr>" + "".join(f"<td>{render_inline(c)}</td>" for c in cells[:len(header)]) + "</tr>")
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
                and "|" not in lines[i]:
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
        # 每个 `##` 小节各占一个 <section>，与 report.py 的分页习惯一致：除首节外都从新的一节开始，
        # 具体是否分页交给浏览器打印时的 CSS（section 默认 break-inside: avoid-page）。
        cls = ' class="major"' if idx == 0 else ""
        sec_html = sec_html.replace("<section>", f"<section{cls}>", 1) if idx == 0 else sec_html
        body_parts.append(sec_html + "</section>")

    runhead = f"{person} · {edition}".replace('"', "")
    css = CSS.replace("__RUNHEAD__", runhead) if CSS else ""
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
