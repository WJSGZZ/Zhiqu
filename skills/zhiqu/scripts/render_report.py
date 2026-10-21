#!/usr/bin/env python3
"""知衢 · 通用 Markdown 报告渲染器（仅用 Python 标准库；PDF 由本机 Chrome/Edge 无头模式打印）。

给读研版（zhiqu-grad）和求职版（zhiqu-career）用：这两个技能把报告写成固定
12 节结构的 Markdown（见 skills/zhiqu-grad/references/report-guide.md 和
skills/zhiqu-career/references/report-guide.md），本脚本把它渲染成与高考版
report.py 相同视觉风格的 HTML/PDF。

用法：
  python3 scripts/render_report.py report.md --out 2027-YJ-0001-report.pdf --profile-version profile.txt  # PDF 名须为 <报告号>-report.pdf
  python3 scripts/render_report.py report.md --out report.html   # 只要 HTML

Markdown 格式：
  可选的 YAML 风格前言（两行 `---` 之间），支持字段：
    title      报告标题
    subtitle   副标题
    person     对象，如"小林（模拟）"
    date       报告日期
    edition    版本，如"读研版"/"求职版"
    id         报告编号（不可省略于正式交付）
    stage      版本/当前阶段，限32字以内
    region     地区或学校，限32字以内
    data_asof  数据截至日期
    conclusion 一句话结论；旧note仅兼容，正式交付用conclusion

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

  新组件（均调用report.py，无另一套CSS）：
    ::: bars 图题 / ::: interval 图题 / ::: timeline 图题 / ::: matrix 图题
    元信息行：caption: 读图说明；source: 1,2（对应sources登记顺序）
    bars可加unit: 元、max: 数字；数据行 - 标签 | 数值 | 冲/稳/保/主 | 显示值（后两项可省）
    interval数据行 - 标签 | 区间下界 | 上界 | 对照点；缺值留空或写未取到，不画假零值。
    timeline数据行 - 月份 | 任务 | 截止日 | 检查点（普通点末列留空），横轴每行最多4节点。
    matrix另写columns: 维度A | 维度B；数据行 - 选项 | ✓短语 | △短语（或✗）。
    ::: flow 图题：每行 - 节点ID | 步骤/判断/结果/备选 | 文字 | 标签>目标ID | …（决策流程图，自上而下）
    ::: stack 图题：每行 - 标签 | 分项 数值 | 分项 数值 | …；可加 unit:、percent: 是（构成条，合计写在右侧）
    ::: facts 图题：每行 - 项目 | 内容 | 已知/待确认/未知（现状一览，未知画虚线框写“未填”）
    ::: cost 图题：每行 - 项目 | 数值或未取到 | 币种 | 显示值（同币种共轴，不同币种分开画、不折算）
    ::: route 路线名：恰好四行 - 门槛 | ... / - 时间窗口 | ... / - 投入 | ... / - 切换条件 | ...
    ::: evidence：每行 - 官方/多人一致/第三方整理/单人说法/推测 | 说明。
    ::: questions / ::: scenarios：columns: 列名 | 列名 | …，每行 - 各列内容；画成追问卡、风险触发卡。
    ::: sources：放第12节，每行 - 来源标题 | 完整URL（个人/计算来源可空） | 发布/核实日期。
    所有块都以单独一行:::结束。bars/interval/timeline/matrix必须有图题、caption和source；
    网址只在sources中显示；正文链接和裸网址统一转为尾注。缺图题/来源的SVG拒绝生成。

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


_report = _load_report_module()
CSS = _report.CSS
find_browser = _report.find_browser
outcome_strip = _report.outcome_strip
STRIP_CAP = _report.STRIP_CAP


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
_FENCE_RE = re.compile(r"^:::\s*(kpi|strip|bars|interval|timeline|matrix|flow|stack|facts|cost|route|evidence|sources|questions|scenarios)\s*(.*)$")
_CALLOUT_RE = re.compile(r"^\[!(key|warn|note)\]\s*(.*)$")
_TAGS = ("冲", "稳", "保")


def _fence_items(lines):
    """`- a | b | c` 形式的行 → [[a, b, c], ...]。"""
    return [_split_table_row(re.sub(r"^\s*[-*+]\s+", "", ln)) for ln in lines if ln.strip()]


def _pct(text):
    m = re.search(r"([\d.]+)\s*%", text)
    return float(m.group(1)) / 100 if m else 0.0


def render_fence(kind, title, lines, notes=None):
    """只解析Markdown参数；组件函数与CSS全部调用report.py。"""
    opts, data = {}, []
    for line in lines:
        if not line.strip(): continue
        if re.match(r'^\s*[-*+]\s+',line): data.append(line)
        elif ':' in line:
            key, _, value = line.partition(':'); opts[key.strip()] = value.strip()
        else: raise ValueError(f'组件{kind}行格式错误：{line}')
    items = _fence_items(data)
    if kind == 'sources': return '__SOURCE_NOTES__'
    if kind == 'kpi': return _report.kpi_cards(items, render_inline)
    if kind == 'evidence':
        return ''.join('<p>'+_report.evidence_badge(r[0])+' '+render_inline(r[1] if len(r)>1 else '')+'</p>' for r in items)
    if kind in ('questions','scenarios'):
        columns = [v.strip() for v in opts.get('columns','').split('|')]
        if any(len(r)!=len(columns) for r in items): raise ValueError(kind+'列数与columns不一致')
        if kind == 'questions': return _report.question_cards(items, columns[1:], render_inline)
        return _report.scenario_cards(columns, items, render_inline)
    if kind == 'route':
        mapping = {r[0]:r[1] for r in items if len(r)>1}
        return _report.route_card(title,[mapping.get(k,'待核') for k in ('门槛','时间窗口','投入','切换条件')])
    source = opts.get('source','')
    caption = opts.get('caption','')
    if kind == 'strip':
        pairs = [(r[0],_pct(r[1])) for r in items]
        pfall = sum(v for n,v in pairs if n=='滑档')
        content = _report.outcome_strip([(n,v) for n,v in pairs if n!='滑档'],pfall)
        caption = caption or STRIP_CAP+'浅色是最终录取概率不到5%的志愿'+('；红色是滑档' if pfall else '')+'。'
        title = title or '你最终会被哪里录取'
    elif kind == 'bars':
        content = _report.bar_chart([[r[0],float(r[1].replace(',','')),*(r[2:])] for r in items],opts.get('unit',''),float(opts['max']) if 'max' in opts else None)
    elif kind == 'interval':
        number = lambda s: float(s.replace(',','')) if s and s.strip() and s!='未取到' else None
        content = _report.interval_chart([[r[0],*[number(x) for x in (r[1:]+['']*7)[:7]]] for r in items],opts.get('unit','分'))
    elif kind == 'timeline': content = _report.timeline(items)
    elif kind == 'flow': content = _report.flow(items)
    elif kind == 'stack':
        def seg(text):
            m = re.match(r'^(.*?)\s*([\d,]+(?:\.\d+)?)\s*$', text)
            if not m: raise ValueError('stack分项须写成“名称 数值”：'+text)
            return (m[1].strip(), float(m[2].replace(',','')))
        content = _report.stack([[r[0],[seg(x) for x in r[1:] if x.strip()]] for r in items],opts.get('unit',''),opts.get('percent','') in ('是','true','1'))
    elif kind == 'facts': content = _report.facts(items, render_inline)
    elif kind == 'cost':
        number = lambda s: float(s.replace(',','')) if s and s.strip() and s.strip()!='未取到' else None
        content = _report.cost_chart([[r[0],number(r[1] if len(r)>1 else ''),*(r[2:])] for r in items])
    elif kind == 'matrix':
        if 'columns' not in opts: raise ValueError('matrix须有columns，按|分隔维度')
        columns = [v.strip() for v in opts['columns'].split('|')]
        if any(len(r)!=len(columns)+1 for r in items): raise ValueError('matrix列数与columns不一致')
        content = _report.comparison_matrix(columns,items,render_inline)
    else: raise ValueError('未知报告组件：'+kind)
    return _report.figure(title,content,caption,source)


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


def markdown_to_html(body, notes=None):
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
                out.append(f'<section data-section="{E(num or '')}" data-kind="plan"><h2>{f"<span class=\'no\'>{E(num)}</span>" if num else ""}{render_inline(disp_title)}</h2>')
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
            out.append(render_fence(fm.group(1), fm.group(2).strip(), buf, notes))
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
                inner, _ = markdown_to_html("\n".join(buf[1:]), notes)
                cls = "" if cm.group(1) == "note" else " " + cm.group(1)
                if cm.group(1) == 'key' and cm.group(2).strip() == '核心结论':
                    # The callout body is a flat bullet list; the common component owns its style.
                    items = re.findall(r'<li>(.*?)</li>', inner, re.S)
                    out.append(_report.core_conclusions(items, rendered=True) if items else
                               _report.core_conclusions([inner], rendered=True))
                else:
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

def build_html(meta, body_html, sections, notes=None):
    notes = notes or _report.SourceNotes()
    title = meta.get('title','决策报告')
    person = meta.get('person','本人')
    edition = meta.get('edition','决策').removesuffix('版')
    report_id = meta.get('id','待编号')
    simulated = meta.get('mode','simulation')!='formal'
    cover = _report.cover_html(title,meta.get('subtitle',''),person,
                              meta.get('stage',edition+'版'),meta.get('region','待核'),report_id,
                              meta.get('date','待核'),meta.get('data_asof','待核'),
                              meta.get('conclusion',meta.get('note','')),[(num,t) for num,t,_ in sections if num],simulated=simulated)
    parts = []
    for idx,(num,t,sec_html) in enumerate(sections):
        if idx==0 or num=='12': sec_html = sec_html.replace('<section ', '<section class="newpage" ',1)
        if num != '12': sec_html = notes.compact(_report.section_lead(sec_html))
        else: sec_html = _report.section_lead(sec_html)
        parts.append(sec_html+'</section>')
    body = ''.join(parts)
    if '__SOURCE_NOTES__' in body: body = body.replace('__SOURCE_NOTES__',notes.render())
    elif notes.entries:
        end = body.rfind('</section>'); body=body[:end]+notes.render()+body[end:]
    doc = _report.document_html(title,cover,body,person,edition,report_id,simulated=simulated)
    _report.publication_gate(doc)
    return doc


def render(markdown_text):
    """返回 (html_document, sections)。sections 供测试和调用方检查用。"""
    meta, body = split_front_matter(markdown_text)
    body = re.sub(r"[ \t]*<!--.*?-->", "", body, flags=re.S)  # 核实/复核期限等注释只给维护者看，不进报告
    notes = _report.SourceNotes()
    for match in re.finditer(r'^::: sources[^\n]*\n(.*?)^:::\s*$',body,re.M|re.S):
        for row in _fence_items(match[1].splitlines()):
            label, url, when = (row+['','',''])[:3]
            notes.add(label,url,when)
    body_html, sections = markdown_to_html(body, notes)
    validate_sections(sections)
    doc = build_html(meta, body_html, sections, notes)
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
    layout_gate(out)



def layout_gate(pdf):
    return _report.layout_gate(pdf)


def main():
    ap = argparse.ArgumentParser(description="知衢 · 把固定 12 节结构的 Markdown 报告渲染成 PDF/HTML")
    ap.add_argument("report", help="报告正文 Markdown（前言字段见脚本顶部说明）")
    ap.add_argument("--out", required=True, help="输出文件，.pdf 或 .html")
    ap.add_argument("--profile-version", help="明确指定案例内画像版本；输出PDF必填")
    a = ap.parse_args()
    with open(a.report, encoding="utf-8") as f:
        text = f.read()
    doc, _ = render(text)
    if a.out.lower().endswith(".html"):
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(doc)
        print(f"已生成 {a.out}")
        return
    if not a.profile_version:ap.error('交付PDF必须明确指定 --profile-version')
    from planning_report import generate
    from pathlib import Path
    root=Path(a.report).resolve().parent
    if not (root/'case.json').exists():ap.error('交付PDF必须由已登记的阶段文件生成；请先完成案例工作流')
    from verify_report import report_pdf_name
    import json
    expected=root/report_pdf_name(json.loads((root/'case.json').read_text())['case_id'])
    if Path(a.out).resolve()!=expected:ap.error(f'交付 PDF 一律以报告号命名，生成在案例目录：--out 须为 {expected}')
    generate(root,profile_version=a.profile_version)


if __name__ == "__main__":
    main()
