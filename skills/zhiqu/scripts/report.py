#!/usr/bin/env python3
"""知衢 · 志愿填报决策报告生成器（仅用 Python 标准库；PDF 由本机 Chrome/Edge 无头模式打印）。

用法：
  python3 report.py report.json --opt result.json --out 报告.pdf
  python3 report.py report.json --opt result.json --out 报告.html   # 只要 HTML

report.json 的字段见 references/report-guide.md；result.json 是 optimize.py --json 的输出。
找不到浏览器时会只输出 HTML，并提示用浏览器"打印 → 存储为 PDF"。
"""
import argparse
from check_report import check_report, publication_gate
import html
import json
import os
import re
import shutil
import math
import subprocess
import sys
import tempfile
import time

E = html.escape
NUM_CELL = re.compile(r"[\d,.\s%~～+\-–—<>≥≤/]+|(?:不到|超过|约)\s?[\d,.]+%?")


def td(c):
    """表格单元格：纯数字（位次、分数、百分比、序号）不换行，避免被拆成两行。"""
    s = str(c)
    cls = " class='num'" if NUM_CELL.fullmatch(s.strip()) else ""
    return f"<td{cls}>{E(s)}</td>"

CSS = r"""
@page { size: A4; margin: 20mm 18mm 20mm 18mm; background: #EEE9DC;
  @top-left { content: "__TOPLEFT__"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #6E776E; }
  @top-right { content: "__RUNHEAD__"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #6E776E; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #6E776E; }
  @bottom-left { content: "仅供参考 · 以当年官方文件为准"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #9CA197; }
}
@page cover { margin: 0; @top-left { content: none; } @top-right { content: none; } @bottom-right { content: none; } @bottom-left { content: none; } }
:root { --sans: "PingFang SC","Source Han Sans SC","Noto Sans SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; --ink:#222A26; --soft:#454E48; --muted:#6E776E; --rule:#D3CCB8; --rule2:#B5AD98;
  --accent:#21473E; --accent2:#34685D; --pale:#E3DDCB; --amber:#A8772B; --red:#9B3B2E; --green:#34685D; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
html, body { background: #EEE9DC; }
body { margin: 0; color: var(--ink); font: 10pt/1.75 "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; font-feature-settings: "lnum"; }
h1,h2,h3 { font-family: "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; font-weight: 700; color: var(--ink); }
h2 { font-size: 18pt; letter-spacing: .5pt; margin: 0 0 4.5mm; padding-bottom: 2.5mm; border-bottom: 1.2pt solid var(--accent); break-after: avoid; }
h2 .no { color: var(--accent); margin-right: 3.5mm; font: 600 12pt var(--sans); letter-spacing: 1pt; vertical-align: 2pt; }
h3 { font-size: 12pt; margin: 6mm 0 2mm; break-after: avoid; }
p { margin: 0 0 2.6mm; }
section { margin-top: 12mm; }
section.newpage { break-before: page; margin-top: 0; }
p, li, dd { orphans: 3; widows: 3; }
h4, dt { break-after: avoid; }
svg.chart { width: 100%; height: auto; display: block; }
.lead { font-size: 11pt; color: var(--soft); break-after: avoid; }
.small { font-size: 8.5pt; color: var(--muted); }
.num { font-variant-numeric: tabular-nums; }
.url { display: block; font: 7pt/1.35 var(--sans); color: var(--muted); word-break: break-all; margin-top: .6mm; }

/* cover */
.cover { page: cover; width: 210mm; height: 296mm; overflow: hidden; padding: 0; position: relative; background: #EEE9DC; break-after: page; }
.cover .band { background: var(--accent); color: #F2EFE6; padding: 20mm 22mm 10mm; }
.cover .kicker { font-size: 9pt; letter-spacing: 3pt; opacity: .85; }
.cover h1 { color: #EEE9DC; font-size: 30pt; margin: 6mm 0 3mm; letter-spacing: 1pt; }
.cover .sub { font-size: 11pt; opacity: .9; }
.cover .motto { margin-top: 6mm; font-size: 10.5pt; letter-spacing: 4pt; opacity: .78; display: flex; align-items: center; gap: 4mm; }
.cover .motto::before { content: ""; width: 8mm; height: .6pt; background: #F2EFE6; opacity: .7; }
.cover .meta { padding: 8mm 22mm 0; display: grid; grid-template-columns: repeat(3,1fr); gap: 4mm 8mm; }
.cover .meta div { border-top: .8pt solid var(--rule2); padding-top: 2mm; }
.cover .meta b { display:block; font-size: 8pt; color: var(--muted); font-weight: 500; letter-spacing: 1pt; }
.cover .meta span { font-size: 12pt; }
.cover .verdict { margin: 9mm 22mm 0; padding: 6mm 8mm; background: #FAF7EE; border-left: 3pt solid var(--accent); }
.cover .verdict b { display:block; font-size: 8pt; color: var(--accent); letter-spacing: 2pt; margin-bottom: 2mm; }
.cover .verdict p { font-size: 14pt; line-height: 1.6; margin: 0; }
.cover .verdict.long p { font-size: 11pt; line-height: 1.55; }
.cover .verdict.long { margin-top: 6mm; padding: 4mm 8mm; }
.cover.dense .meta { gap: 2.5mm 8mm; } .cover.dense .meta span { font-size: 11pt; }
.cover.dense .verdict { margin-top: 5mm; padding: 4mm 8mm; } .cover.dense .verdict p { font-size: 11pt; line-height: 1.55; }
.cover .foot { position: absolute; left: 22mm; right: 22mm; bottom: 16mm; font-size: 8pt; color: var(--muted); border-top: .6pt solid var(--rule); padding-top: 3mm; }

/* kpis */
.kpis { display: grid; grid-template-columns: repeat(4,1fr); gap: 0; border-top: 1pt solid var(--ink); border-bottom: .6pt solid var(--rule2); margin: 4mm 0 6mm; }
.kpis div { padding: 3mm 3mm 3mm 0; }
.kpis div + div { padding-left: 4mm; border-left: .6pt solid var(--rule); }
.kpis b { display:block; font: 500 7.8pt var(--sans); color: var(--muted); letter-spacing: .5pt; }
.kpis span { font: 700 19pt/1.25 "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; font-variant-numeric: tabular-nums; }
.kpis em { display:block; font: normal 7.8pt/1.5 var(--sans); color: var(--soft); margin-top: .5mm; }

/* boxes */
.box { background: #FAF7EE; border: .6pt solid var(--rule); padding: 4mm 5mm; margin: 3mm 0 4mm; }
.box.key { border-left: 2.5pt solid var(--accent); }
.box.warn { border-left: 2.5pt solid var(--amber); }
.box h4 { margin: 0 0 1.5mm; font: 600 8.5pt var(--sans); letter-spacing: 1pt; color: var(--accent); }
.box.warn h4 { color: var(--amber); }
ol.tight, ul.tight, .box > ol, .box > ul { margin: 0; padding-left: 5mm; }
ol.tight li, ul.tight li, .box > ol li, .box > ul li { margin: .6mm 0; }
.box > p { margin: 0 0 1.5mm; } .box > p:last-child { margin-bottom: 0; }

/* tables */
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 8.8pt; font-variant-numeric: tabular-nums; }
thead th { white-space: nowrap; text-align: left; font: 600 7.8pt var(--sans); color: var(--soft); letter-spacing: .3pt; border-top: 1pt solid var(--ink); border-bottom: .6pt solid var(--ink); padding: 1.6mm 2mm; }
table.vt { table-layout: fixed; }
table.rt { table-layout: fixed; }
td.num { white-space: nowrap; font-variant-numeric: tabular-nums; }
td { overflow-wrap: anywhere; }
table.vt thead th { white-space: normal; }
table.vt td:nth-child(2) { font-weight: 600; }
table.vt td .small { font-weight: 400; }
table.vt td.note { font-size: 8pt; line-height: 1.6; }
table.vt td.c, table.vt th.c { white-space: nowrap; }
tbody td { border-bottom: .4pt solid var(--rule); padding: 1.5mm 2mm; vertical-align: top; }
tbody tr { break-inside: avoid; }
td.r, th.r { text-align: right; font-variant-numeric: tabular-nums; }
td.c, th.c { text-align: center; }
tr.hl td { background: #E7EDE8; }
.tag { display: inline-block; min-width: 7mm; text-align: center; font: 600 7.5pt/1.5 var(--sans); padding: .2mm 1.5mm; border-radius: .8mm; color: #fff; }
.tag.冲 { background: var(--red); } .tag.稳 { background: var(--amber); } .tag.保 { background: var(--green); }

/* two columns / cards */
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; }
.grid2.wide { grid-template-columns: 1fr; }
.card table { font-size: 8.3pt; margin: 2.5mm 0 0; }
.card table thead th { border-top: .6pt solid var(--rule2); }
.card { background: #FAF7EE; border-top: 1.6pt solid var(--accent2); padding: 4mm 5mm 3mm; }
.card h3 { margin: 0 0 1mm; }
.card .fit { font: 600 7.8pt var(--sans); color: var(--accent); letter-spacing: 1pt; }
.card dl { margin: 2mm 0 0; }
.card dt { font: 600 7.8pt var(--sans); color: var(--muted); margin-top: 1.8mm; }
.card dd { margin: 0; }
.fig { margin: 2mm 0 5mm; break-inside: avoid; }
.fig .cap { font: 7.8pt/1.55 var(--sans); color: var(--muted); margin-top: 1.5mm; }
.fig .ttl { font: 600 8.8pt var(--sans); margin-bottom: 1.5mm; color: var(--soft); }
.glossary dt { font-weight: 600; margin-top: 1.5mm; } .glossary dd { margin: 0 0 1mm; color: var(--soft); }
ul.asklist { list-style: none; padding: 0; margin: 0 0 3mm; }
ul.asklist li { padding: 2mm 0 2mm 4mm; border-left: 2pt solid var(--rule2); margin: 0 0 2mm; background: #FAF7EE; break-inside: avoid; }
ul.asklist li b { font-weight: 600; } ul.asklist li span { display: block; font-size: 8.5pt; color: var(--muted); margin-top: .5mm; }
.toc { margin-top: 2mm; columns: 2; column-gap: 10mm; } .toc div { display: flex; border-bottom: .4pt dotted var(--rule2); padding: .8mm 0; break-inside: avoid; }
.toc div span:first-child { width: 10mm; color: var(--accent); font-weight: 600; }

a { color:inherit; text-decoration:none; }
/* Professional system: shared by all three report types. */
.cover .meta { gap: 3.5mm 7mm; }
.cover .meta span { display:block; font-size:11pt; line-height:1.5; min-height:12mm; }
.cover .sub { white-space:nowrap; font-size:10pt; }
.cover-toc { margin:6mm 22mm 0; padding:3mm 0 0; border-top:.6pt solid var(--rule2); }
.cover-toc > b { font:600 8pt var(--sans); color:var(--accent); }
.cover .verdict.long { margin-top:6mm; }
.toc { font-size:9pt; line-height:1.5; }
.toc div { padding:1mm 0; }
section > p:first-of-type strong { color:var(--accent); }
figure { margin-left:0; margin-right:0; }
.fig, .route-card, .timeline-row, .kpis { break-inside:avoid; }
.matrix { table-layout:fixed; font-size:8.3pt; }
.matrix th { white-space:normal; }
.matrix th:first-child { width:17%; }
.matrix td.yes { color:var(--accent); }
.matrix td.no { color:var(--red); }
.matrix td.pending { color:var(--soft); }
.timeline { margin:4mm 0; }
.timeline-row { display:flex; gap:3mm; margin:0 0 4mm; border-top:1.2pt solid var(--rule2); }
.milestone { flex:1; padding:3mm 2mm 0; position:relative; font-size:8pt; }
.milestone::before { content:'●'; color:var(--accent2); position:absolute; top:-3.5mm; }
.milestone.checkpoint::before { content:'◆'; color:var(--amber); }
.milestone b, .milestone strong, .milestone span { display:block; }
.milestone b { color:var(--accent); margin-bottom:1mm; }
.milestone span { color:var(--muted); margin-top:1mm; }
.route-card { border: .6pt solid var(--rule); border-left:2.5pt solid var(--accent); padding:4mm; margin:3mm 0 5mm; background:#FAF7EE; }
.route-card h3 { margin:0 0 2mm; }
.route-card dl { display:grid; grid-template-columns:repeat(4,1fr); margin:0; gap:4mm; font-size:8.8pt; }
.route-card dt { color:var(--accent); font:600 8pt var(--sans); margin-bottom:1mm; }
.route-card dd { margin:0; }
.evidence { display:inline-block; padding:.3mm 1.5mm; font:7.8pt var(--sans); border: .5pt solid var(--rule2); }
.evidence.official { background:var(--accent);color:#fff; }
.evidence.corroborated { background:var(--accent2);color:#fff; }
.evidence.single { background:var(--pale);color:var(--ink); }
.evidence.inference { background:transparent;color:var(--muted); }
.source-ref { color:var(--accent);font-size:7.5pt; }
.source-notes { list-style:none; padding:0; font-size:7.8pt; line-height:1.35; }
.source-notes li { margin:0 0 .6mm; break-inside:avoid; }
section[data-section="12"] { margin-top:6mm; }
.source-notes .url { display:inline; margin-left:1.5mm; line-height:1.35; }
table.vt th { white-space:normal; }
table.vt td .row-note { display:block;white-space:nowrap;font-size:7.8pt;font-weight:400;color:var(--muted); }
"""


# 三版打印规范：A4/既有字体与色板；正文10pt/1.75，节标题18pt，
# 小标题12pt；图内文字10.5 SVG单位（640宽映射174mm，实际约8pt），最低7pt。
# 千分位数字、中文量词前空格、区间用“—”；概率精度仍由prob_formatter控制。
PALETTE = {'冲': '#9B3B2E', '稳': '#A8772B', '保': '#34685D', '主': '#21473E'}
URL_RE = re.compile(r'https?://[^\s<>"\'，；。）、（【】]+')


def display_text(value):
    """只规范显示，不回写数据；编号/日期/专业代码不转换。"""
    text = str(value)
    text = re.sub(r'(?<![A-Za-z0-9_,.])(\d{4,})(?=\s*(?:元|名|人|位|小时))', lambda m: f'{int(m[1]):,}', text)
    return re.sub(r'(\d)(?=(?:万|亿)?(?:元|分(?!位)|名|人|小时))', r'\1 ', text)


def public_text(text):
    """发布层仅清理开发措辞；输入JSON与结论、数值保持原样。"""
    text = text.replace('模拟用户','本人').replace('模拟考生','本案考生').replace('虚构考生','本案考生')
    for old,new in [('模拟','试算'),('示例','本案'),('演示','对照'),('复现','复核'),('脚本','计算方法'),('虚构','本案')]:
        text = text.replace(old,new)
    text = re.sub(r'python3\s+scripts/[^；。]+','按本节记录的方法重新核算',text)
    text = re.sub(r'(?:skills/zhiqu/)?(?:scripts/|data/calibration/)?[A-Za-z_]+\.py','本省检验方法',text)
    for old,new in [('retro_ranks/<位次>/','各位次的独立结果'),('retro_ranks.csv','多档位次汇总'),('retro_config.json','事前登记'),('hindsight.json','事后对照记录'),('preferences_review.json','偏好核对记录'),('data/schools.csv','教育部高校名录'),('model_review_2026.csv','年度检验记录'),('README.md','来源说明')]:
        text = text.replace(old,new)
    for old,new in [('预测过线','单独过线'),('过线概率','单独过线'),('落点概率','最终录取'),('最终录取概率','最终录取'),('预测线','预测位次')]:
        text = text.replace(old,new)
    return display_text(text.replace('–','—'))


def simulated_name(name):
    name = re.sub(r'^(?:虚构示例|模拟用户|示例)\s*[·：]?\s*', '', str(name)).replace('（虚构）','')
    return name if '（模拟）' in name else name + '（模拟）'


def cover_html(title, subtitle, person, stage, region, report_id, generated, data_asof, conclusion, sections):
    """三版唯一封面：固定六格；长说明移到摘要，调用方负责保留。"""
    rows = [('对象', simulated_name(person)), ('版本或阶段', stage), ('地区或学校', region),
            ('报告编号', report_id), ('生成日期', generated), ('数据截至', data_asof)]
    for key, value in rows:
        if _text_width(str(value),11)>280 or len(str(value))>32 or '\n' in str(value):
            raise ValueError(f'封面{key}过长，请把说明移到摘要页')
    toc = ''.join(f'<div><span>{int(i):02d}</span><span>{E(t)}</span></div>' for i, t in sections)
    return ('<div class="cover"><div class="band"><div class="kicker">知衢 · 决策报告</div>'
            f'<h1>{E(title)}</h1><div class="sub">{E(subtitle)}</div>'
            '<div class="motto">知其所往，方行其衢。</div></div><div class="meta">'
            + ''.join(f'<div><b>{a}</b><span>{E(str(b))}</span></div>' for a, b in rows)
            + '</div>' + (f'<div class="verdict long"><b>一句话结论</b><p>{E(public_text(conclusion))}</p></div>' if conclusion else '')
            + f'<div class="cover-toc"><b>目录</b><div class="toc">{toc}</div></div>'
            '<div class="foot">仅供本人决策参考；依据、假设与局限见正文及第 12 节。</div></div>')


def document_html(title, cover, body, person, edition, report_id):
    runhead = f'{simulated_name(person)} · {edition} · {report_id}'
    safe = lambda s: str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
    css = CSS.replace('__RUNHEAD__', safe(runhead)).replace('__TOPLEFT__', safe('知衢 · ' + edition + '决策报告'))
    return f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>{E(title)}</title><style>{css}</style></head><body>{cover}{body}</body></html>'


def readable_url(url):
    """只解码非ASCII的UTF-8百分号字节，保留%2F/%3F等有语义的ASCII转义。"""
    from urllib.parse import unquote
    def decode(m):
        text = unquote(m[0],errors='replace')
        return m[0] if '\ufffd' in text else text
    return re.sub(r'(?:%[89a-fA-F][0-9a-fA-F])+',decode,url)


class SourceNotes:
    """编号按首次登记顺序稳定，完整URL只在第12节输出，正文只留[n]。"""
    def __init__(self):
        self.entries = []

    def add(self, label, url='', date=''):
        for i, entry in enumerate(self.entries, 1):
            if (url and entry[1] == url) or (not url and entry == (label, url, date)):
                return i
        self.entries.append((label, url, date))
        return len(self.entries)

    def compact(self, fragment):
        from html.parser import HTMLParser
        owner = self
        class Compact(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.out = []
                self.link_ref = None
            def handle_starttag(self, tag, attrs):
                if tag == 'a' and dict(attrs).get('href','').startswith(('http://','https://')):
                    self.link_ref = owner.add('引用原页；证据强弱见正文',dict(attrs)['href'])
                    return
                if self.link_ref is not None: return
                self.out.append('<' + tag + ''.join(f' {k}="{E(v or "", quote=True)}"' for k, v in attrs) + '>')
            def handle_endtag(self, tag):
                if tag == 'a' and self.link_ref is not None:
                    self.out.append(f'<sup class="source-ref">[{self.link_ref}]</sup>'); self.link_ref = None
                    return
                if self.link_ref is not None: return
                self.out.append(f'</{tag}>')
            def handle_data(self, text):
                if self.link_ref is not None: return
                pos = 0
                for m in URL_RE.finditer(text):
                    url = m[0].rstrip('.,;)')
                    self.out.append(E(public_text(text[pos:m.start()])))
                    self.out.append(f'<sup class="source-ref">[{owner.add("引用原页；证据强弱见正文", url)}]</sup>')
                    pos = m.start() + len(url)
                self.out.append(E(public_text(text[pos:])))
        parser = Compact(); parser.feed(fragment)
        return ''.join(parser.out)

    def render(self):
        return '<ol class="source-notes">' + ''.join(
            f'<li id="source-{i}"><b>[{i}] {E(public_text(label))}</b>'
            + (f' · {E(date)}' if date else '')
            + (f'<span class="url"><a href="{E(url)}">{E(readable_url(url))}</a></span>' if url else '') + '</li>'
            for i, (label, url, date) in enumerate(self.entries, 1)) + '</ol>'


def figure(title, content, caption, sources):
    """唯一图框，SVG内标题/来源与可见图题/图注同时生成。"""
    if not title or not caption or not re.search(r'\d', str(sources)):
        raise ValueError('每张图必须有标题、读图说明和数据来源编号')
    refs = str(sources)
    content = re.sub(r'(<svg\b[^>]*)(>)', lambda m: m[1] + f' role="img" data-source-refs="{E(refs)}"' + m[2] + f'<title>{E(title)}</title>', content)
    return (f'<figure class="fig"><div class="ttl">{E(title)}</div>{content}'
            f'<figcaption class="cap">{E(caption)} 数据来源：' +
            '、'.join(f'[{n}]' for n in re.findall(r'\d+', refs)) + '</figcaption></figure>')


def bar_chart(rows, unit='', maximum=None):
    """rows=[label,value,tag?,display?]，不改数值；负值/缺失不伪装成0。"""
    rows = [list(r) for r in rows]
    vals = [float(r[1]) for r in rows if r[1] is not None]
    vmax = float(maximum or max(vals, default=1) or 1)
    if any(v < 0 or not math.isfinite(v) for v in vals):
        raise ValueError('条形图只接受有限非负数；负结余应在情景表中明确披露')
    width, label_w, plot_w, row_h = 640, 215, 330, 18
    out = [f'<svg class="chart" viewBox="0 0 {width} {len(rows)*row_h+8}" xmlns="http://www.w3.org/2000/svg" font-size="10.5" font-family="PingFang SC, Noto Sans SC, sans-serif">']
    for i, row in enumerate(rows):
        label, value = row[:2]; tag = row[2] if len(row) > 2 else '主'; y = i*row_h+3
        out.append(f'<text x="0" y="{y+15}" fill="#454E48">{E(label)}</text>')
        out.append(f'<rect x="{label_w}" y="{y+2}" width="{plot_w}" height="13" fill="#E3DDCB"/>')
        if value is None:
            display = '未取到'
        else:
            if float(value) > vmax: raise ValueError('条形图数值超出上界')
            bw = plot_w*float(value)/vmax
            out.append(f'<rect x="{label_w}" y="{y+2}" width="{bw:.2f}" height="13" fill="{PALETTE.get(tag, PALETTE["主"])}"/>')
            display = row[3] if len(row) > 3 and row[3] else f'{float(value):,.1f}'.removesuffix('.0') + (' '+unit if unit else '')
        out.append(f'<text x="635" y="{y+15}" text-anchor="end" fill="#222A26">{E(str(display))}</text>')
    out.append('</svg>'); return ''.join(out)


def interval_chart(rows, unit='分'):
    """rows=[label,lo,hi,point]；缺资料明确显示；每行保持原统计口径。"""
    vals = [float(v) for r in rows for v in r[1:4] if v is not None]
    low, high = (min(vals)-10, max(vals)+10) if vals else (0, 100)
    scale = lambda v: 225 + (float(v)-low)/max(high-low,1)*320
    out = [f'<svg class="chart" viewBox="0 0 640 {len(rows)*37+28}" xmlns="http://www.w3.org/2000/svg" font-size="10.5" font-family="PingFang SC, Noto Sans SC, sans-serif">']
    for i, (label, lo, hi, point) in enumerate(rows):
        y = 17+i*37
        out.append(f'<text x="0" y="{y+4}" fill="#454E48">{E(label)}</text>')
        if lo is not None and hi is not None:
            if lo > hi: raise ValueError('区间下界不可大于上界')
            out.append(f'<line x1="{scale(lo):.1f}" x2="{scale(hi):.1f}" y1="{y}" y2="{y}" stroke="#34685D" stroke-width="6"/>')
            out.append(f'<text x="225" y="{y+18}" fill="#6E776E">{lo:g}—{hi:g} {E(unit)}</text>')
        else:
            out.append(f'<text x="225" y="{y+4}" fill="#6E776E">区间未取到</text>')
        if point is not None:
            out.append(f'<circle cx="{scale(point):.1f}" cy="{y}" r="4" fill="#A8772B"/><text x="630" y="{y+4}" text-anchor="end" fill="#222A26">对照 {point:g}</text>')
    out.append('</svg>'); return ''.join(out)


def timeline(rows):
    """横向月份轴，每段最多4节点，超出续行；rows=[月,任务,截止日,检查点?]。"""
    out = ['<div class="timeline">']
    for start in range(0, len(rows), 4):
        chunk = rows[start:start+4]
        out.append('<div class="timeline-row">')
        for row in chunk:
            month, task, deadline, *rest = row
            cls = ' checkpoint' if rest and rest[0] not in ('', '普通', False) else ''
            out.append(f'<div class="milestone{cls}"><b>{E(month)}</b><strong>{E(task)}</strong><span>截止：{E(deadline)}</span></div>')
        out.append('</div>')
    return ''.join(out)+'</div>'


def comparison_matrix(columns, rows):
    out = ['<table class="matrix"><thead><tr><th>选项</th>' + ''.join(f'<th>{E(c)}</th>' for c in columns) + '</tr></thead><tbody>']
    for row in rows:
        out.append('<tr><td>'+E(str(row[0]))+'</td>')
        for value in row[1:]:
            val = str(value); state = 'yes' if val.startswith('✓') else ('no' if val.startswith('✗') else 'pending')
            out.append(f'<td class="{state}">{E(val)}</td>')
        out.append('</tr>')
    return ''.join(out)+'</tbody></table>'


def route_card(title, rows):
    keys = ['门槛', '时间窗口', '投入', '切换条件']
    if len(rows) != 4: raise ValueError('路线卡须恰好四栏')
    return f'<div class="route-card"><h3>{E(title)}</h3><dl>' + ''.join(f'<div><dt>{key}</dt><dd>{E(str(value))}</dd></div>' for key, value in zip(keys, rows))+'</dl></div>'


def kpi_cards(items, inline=E):
    cards = []
    for row in items[:4]:
        label, value, note = (list(row)+['','',''])[:3]
        cjk = sum(ord(c)>0x2E80 for c in value)
        big = ' class="num"' if cjk<=4 and len(value)<=12 else ' style="font-size:11pt"'
        cards.append(f'<div><b>{inline(label)}</b><span{big}>{inline(value)}</span>'+(f'<em>{inline(note)}</em>' if note else '')+'</div>')
    return f'<div class="kpis" style="grid-template-columns:repeat({max(len(cards),1)},1fr)">'+''.join(cards)+'</div>'


def evidence_badge(level):
    names = {'官方': 'official', '多人一致': 'corroborated', '单人说法': 'single', '推测': 'inference'}
    if level not in names: raise ValueError('未知证据等级')
    return f'<span class="evidence {names[level]}">{level}</span>'


def section_lead(body):
    """把节内第一段的首句显著标出；文本不改，已加粗的不重复。"""
    def replace(m):
        opening, inside = m.groups()
        if inside.startswith(('<strong>', '<b>')): return m[0]
        sentence = re.match(r'(.+?[。！？]|.+$)', inside, re.S)[1]
        return opening + '<strong>' + sentence + '</strong>' + inside[len(sentence):] + '</p>'
    return re.sub(r'(<p(?: class="lead")?>)(.*?)</p>', replace, body, count=1, flags=re.S)


def pct(x, d=0):
    if x is None:
        return "–"
    if d == 0 and 0 < x < 0.01:
        d = 1  # 小于 1% 时保留一位小数，避免把 0.5% 显示成 0%
    return f"{x * 100:.{d}f}%"


GRADE_MEANING = {
    "A": "本省历年回测显示概率基本可信，报告写百分比（仍是按历年波动推算，不是录取率）。",
    "B": "本省概率大体可用但不够精确，百分比取整到 5%，并给出 80% 区间；保底要求留足余量。",
    "C": "概率不够可信（本省检验年份太少、区间失准，或今年是改版年）：报告不写百分比，只写冲、稳、保三档和预测区间。",
    "D": "本省无法检验概率，报告不出过线概率，只做定性分析。",
}


def prob_formatter(grade):
    """按本省可信度评级显示概率：A 原样；B 取整到 5%；C、D 不显示数值（返回 None 由调用处改写）。"""
    def f(x, d=0):
        if x is None:
            return "–"
        if grade == "A":
            return pct(x, d)
        if grade == "B":
            if x <= 0:
                return "0%"
            if x >= 1:
                return "100%"
            if x < 0.05:  # 取整到 5% 后两端会写成“约 0%”“约 100%”，与“有可能但很小”的含义不符
                return "&lt; 5%"
            if x > 0.95:
                return "&gt; 95%"
            return f"约 {round(x * 20) * 5:.0f}%"
        return None
    return f


STRIP_CAP = '从左到右按志愿顺序排列，色块越宽，最终被该志愿录取的可能越大；数字是志愿序号，对应“志愿表”一节。'
UTILITY_SCALE = "100 分 = 候选中你最想去的"


def strategy_caption(eu, pfall, top, safe):
    """按实际数字写策略图的图注，不预设“只挑最想去的一定滑档”。"""
    parts = ["条越长越好；滑档概率越低越好。"]
    if top:
        if abs(top[0] - (eu or 0)) < 0.05 and abs(top[1] - (pfall or 0)) < 1e-9:
            parts.append("只挑最想去的，在本案和本报告的方案结果相同：你最想去的几个里已经有够稳的保底。")
        elif top[1] > (pfall or 0):
            parts.append("只挑最想去的，滑档风险更高。")
        elif top[0] < (eu or 0):
            parts.append("只挑最想去的，滑档风险没有更高，但期望效用更低：前段太集中，落空后没有中间档接住。")
    if safe and safe[0] < (eu or 0):
        parts.append("只挑最稳的，几乎不会滑档，但浪费了分数。")
    return "".join(parts)


def interval80(x):
    """80% 预测区间（位次），与优化器使用的 σ 一致。"""
    lo = x["expected_cut_rank"] * math.exp(-1.2816 * x["sigma"])
    hi = x["expected_cut_rank"] * math.exp(1.2816 * x["sigma"])
    return f"{round(lo):,}–{round(hi):,}"


def bars_h(items, width=640, bar_h=13, gap=6, label_w=170, color="#34685D", fmt=lambda v: f"{v:.0%}", vmax=None):
    """水平条形图：items = [(label, value)]"""
    vmax = vmax or max((v for _, v in items), default=1) or 1
    h = len(items) * (bar_h + gap) + 4
    w_plot = width - label_w - 44
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" font-family="PT Serif, Songti SC, Noto Serif SC, serif" font-size="10.5">']
    for i, (lab, v) in enumerate(items):
        y = i * (bar_h + gap) + 2
        bw = max(0.5, w_plot * v / vmax)
        lab = lab if len(lab) <= 16 else lab[:15] + "…"
        out.append(f'<text x="{label_w - 6}" y="{y + bar_h - 3}" text-anchor="end" fill="#454E48">{E(lab)}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{w_plot}" height="{bar_h}" fill="#E3DDCB"/>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" fill="{color}"/>')
        out.append(f'<text x="{label_w + bw + 4:.1f}" y="{y + bar_h - 3}" fill="#222A26">{E(fmt(v))}</text>')
    out.append("</svg>")
    return "".join(out)


def strategy_chart(rows, width=640, fmt=None):
    """策略对比：期望效用条 + 右侧固定栏写滑档概率。rows = [(name, eu, pfall, highlight)]
    右侧留出固定宽度，期望值写在条内末端，长短都不会与滑档文字重叠。"""
    vmax = max(r[1] for r in rows) or 1
    label_w, bar_h, gap, right_w = 120, 20, 9, 150
    h = len(rows) * (bar_h + gap) + 6
    w_plot = width - label_w - right_w - 12
    sans = "PingFang SC, Source Han Sans SC, Noto Sans SC, sans-serif"
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" font-family="{sans}" font-size="10.5">']
    for i, (n, eu, pf, hl) in enumerate(rows):
        y = i * (bar_h + gap) + 3
        bw = max(28, w_plot * max(eu, 0) / vmax)
        col = "#21473E" if hl else "#CEC6B1"
        txt = "#EEE9DC" if hl else "#454E48"
        out.append(f'<text x="{label_w - 8}" y="{y + bar_h - 6}" text-anchor="end" fill="#222A26" font-weight="{600 if hl else 400}">{E(n)}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{w_plot}" height="{bar_h}" fill="#E3DDCB"/>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" fill="{col}"/>')
        out.append(f'<text x="{label_w + bw - 6:.1f}" y="{y + bar_h - 6}" text-anchor="end" fill="{txt}" font-weight="600">{eu:.1f}</text>')
        fall = fmt(pf) if fmt else f"{pf:.1%}"
        out.append(f'<text x="{width - 4}" y="{y + bar_h - 6}" text-anchor="end" fill="{"#9B3B2E" if pf > 0.01 else "#6E776E"}">滑档 {E(fall)}</text>')
    out.append("</svg>")
    return "".join(out)


def _text_width(text, size=9):
    """估算 SVG 文字宽度：汉字按一个字号宽，其他字符按约 0.62 个字号。"""
    return sum(size if ord(c) > 0x2E80 else size * 0.62 for c in text)


def outcome_strip(items, pfall, width=640, fmt=None):
    """结局分布：一条 100% 堆积条，按志愿顺序着色，展示“最可能落在哪里”。图注由调用处写在条下。"""
    h = 26
    sans = "PingFang SC, Source Han Sans SC, Noto Sans SC, sans-serif"
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" font-family="{sans}" font-size="10.5">']
    x = 0.0
    strong = ["#21473E", "#5E8C7F", "#34685D", "#7FA597"]  # 主要去向（≥5%）按出现顺序交替深浅
    k = 0
    for i, (lab, p) in enumerate(items):
        w = width * p
        if w <= 0:
            continue
        if p >= 0.05:
            col = strong[k % len(strong)]
            k += 1
        else:
            col = "#CEC6B1"
        out.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{h}" fill="{col}" stroke="#EEE9DC" stroke-width="1"/>')
        pl = f"{p:.0%}" if fmt is None else fmt(p)
        tail = f" · {pl}" if pl else ""
        # 从长到短取第一个放得下的标签，窄段不把字截断
        fits = [t for t in (f"第 {i + 1} 志愿{tail}", f"{i + 1}{tail}") if _text_width(t) + 12 <= w]
        if fits:
            out.append(f'<text x="{x + 6:.1f}" y="{h / 2 + 3.5:.1f}" fill="#fff" font-weight="600">{fits[0]}</text>')
        elif w > 14:
            ink = "#fff" if p >= 0.05 else "#454E48"
            out.append(f'<text x="{x + w / 2:.1f}" y="{h / 2 + 3.5:.1f}" fill="{ink}" text-anchor="middle">{i + 1}</text>')
        x += w
    if pfall > 0:
        w = max(1.5, width * pfall)
        out.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{h}" fill="#9B3B2E"/>')
    out.append("</svg>")
    return "".join(out)


def source_cell(text):
    """来源格：机构名正常排，网址缩成一行小字，避免在窄栏里从中间断开。"""
    import re as _re
    urls = _re.findall(r"https?://\S+", text or "")
    name = _re.sub(r"https?://\S+", "", text or "").strip(" ；;，,")
    short = [_re.sub(r"^https?://(www\.)?", "", u) for u in urls]
    return E(name or "—") + "".join(f"<span class='url'>{E(u)}</span>" for u in short)


def unprefix(text, label):
    """表头已写“门槛”“代价”“依据”时，去掉格内重复的“门槛：”前缀。"""
    t = (text or "").strip()
    return t[len(label) + 1:].lstrip() if t.startswith(label + "：") else t


def limit_line(x):
    """招生章程里的硬性限制（体检、单科、语种、性别等），提醒考生录入前再核对一次。"""
    return f"<div class='small' style='color:#9B3B2E'>限制：{E(x['limits'])}</div>" if x.get("limits") else ""


def group_line(x, fmt=None):
    """专业组志愿：列出落到组内各专业和被调剂的概率。"""
    ms = x.get("majors")
    if not ms or x.get("p_land", 0) <= 0:
        return ""
    fmt = fmt or pct
    if fmt(0.5) is None:
        return "<div class='small'>组内：" + "、".join(E(m["name"]) for m in ms) + "（本省评级不给分专业概率）</div>"
    parts = [f"{E(m['name'])} {fmt(m['p'], 1)}" for m in ms] + [f"调剂 {fmt(x.get('p_adjusted', 0), 1)}"]
    return "<div class='small'>组内：" + "｜".join(parts) + "</div>"


def build(rep, opt):
    m = rep.get("meta", {})
    refs = SourceNotes()
    for label, source, date in rep.get('sources', []):
        urls = URL_RE.findall(source)
        for url in urls or ['']:
            refs.add(label + ('；' + URL_RE.sub('', source) if not urls else ''), url.rstrip('.,;)'), date)
    model_ref = refs.add('本报告志愿组合计算；与本次志愿表相同的位次、概率及顺序')
    profile_ref = refs.add('本人画像、优先级与家庭约束；个人陈述及本报告的条件判断')
    lst = (opt or {}).get("list", [])
    eu = (opt or {}).get("expected_utility")
    pfall = (opt or {}).get("p_fall")
    stress = (opt or {}).get("stress", {})
    top = [x for x in lst if x["p_land"] >= 0.005]
    # 以原专业录取、且偏好分 ≥ 70 的概率（被调剂的部分不计入）
    def good(x):
        if x.get("majors"):  # 专业组：按组内实际落到的专业计
            return sum(m["p"] for m in x["majors"] if m["utility"] >= 70)
        return x["p_land"] - x.get("p_adjusted", 0) if x["utility"] >= 70 else 0.0
    p_good = sum(good(x) for x in lst) if lst else None
    likely = max(lst, key=lambda x: x["p_land"]) if lst else None
    sims = ((opt or {}).get("params") or {}).get("sims") or 4000
    grade = m.get("prob_grade", "A")
    fmt = prob_formatter(grade)
    numeric = grade in ("A", "B")

    def fall_txt(p):
        if p == 0:  # 模拟中一次都没出现，只能说低于 1/模拟次数
            return f"&lt; {100 / sims:.2g}%" if grade == "A" else "模拟中未出现"
        return fmt(p, 1) if numeric else "有风险，见第 05 节"
    likely_name = likely["name"] if likely else "–"
    likely_p = likely["p_land"] if likely else None
    if likely and likely.get("majors"):  # 专业组：显示"学校·最可能的专业"
        top = max(likely["majors"], key=lambda m: m["p"])
        likely_name = likely["name"].split("·")[0] + "·" + top["name"]
        likely_p = top["p"]
    strip_fmt = (lambda p: f"{p:.0%}") if grade == "A" else ((lambda p: fmt(p).replace("约 ", "≈").replace("&lt; ", "<").replace("&gt; ", ">")) if numeric else (lambda p: ""))
    secs = []
    missing = []
    n = 0

    # 只在封面之后另起一页，其余各节接着排：文中任何强制分页都可能让上一节剩下一两行独占一页、
    # 留下大片空白（2026-10 的样板实测如此）。表格行不拆、表头每页重复，小标题跟着下文走。
    NEW_PAGE = {"摘要"}

    def sec(title, body):
        nonlocal n
        n += 1
        cls = ' class="newpage"' if title in NEW_PAGE else ""
        secs.append((n, title, f'<section{cls} data-section="{n:02d}"><h2><span class="no">{n:02d}</span>{E(title)}</h2>{refs.compact(section_lead(body)) if n != 12 else section_lead(body)}</section>'))

    # 目录固定：每一节都出现。没有内容的节写明原因（report.json 的 omitted.<键>），并在终端提醒。
    omitted = rep.get("omitted", {})

    def blank(key, title, default):
        why = omitted.get(key)
        if not why:
            missing.append(title)
        sec(title, f'<div class="box"><h4>本节说明</h4><p>{E(why or default)}</p></div>')

    # 01 摘要
    s = rep.get("summary", {})
    body = f'<p class="lead">{E(s.get("headline", ""))}</p>'
    if lst:
        body += ('<div class="kpis">'
                 f'<div><b>推荐志愿数</b><span class="num">{len(lst)}</span><em>本批次可填 {E(str(m.get("slots", "–")))} 个</em></div>'
                 f'<div><b>最可能的去向</b><span style="font-size:11pt">{E(likely_name)}</span><em>{"概率" + ("" if grade == "B" else "约 ") + fmt(likely_p) if numeric else "落点最集中的志愿（本省评级不给精确概率）"}</em></div>'
                 + (f'<div><b>满意度 70 分以上的概率</b><span class="num">{fmt(p_good)}</span><em>{E(m.get("utility_scale", UTILITY_SCALE))}</em></div>' if numeric else
                    f'<div><b>冲 / 稳 / 保</b><span class="num">{" / ".join(str(sum(x["tag"] == t for x in lst)) for t in ("冲", "稳", "保"))}</span><em>按模型过线可能性分档，不给百分比</em></div>')
                 + (f'<div><b>滑档风险</b><span class="num">{fall_txt(pfall)}</span><em>录取线整体大波动时 {fall_txt(stress.get("p_fall"))}</em></div>' if grade == "A" or pfall else
                    f'<div><b>滑档风险</b><span class="num">未出现</span><em>{sims:,} 次模拟中没有出现滑档；录取线整体大波动时{"也没有" if not stress.get("p_fall") else "：" + fall_txt(stress.get("p_fall"))}</em></div>')
                 + '</div>')
    if m.get('date') and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(m['date'])):
        body += f'<div class="box"><h4>报告口径</h4><p>{E(m["date"])}</p></div>'
    if lst:
        body += figure('你最终会被哪里录取', outcome_strip([(x['name'], x['p_land']) for x in lst], pfall or 0, fmt=strip_fmt),
                       STRIP_CAP + ('浅色为最终录取不到5%的志愿；红色为滑档。' if numeric else '仅作定性示意，本省评级不显示百分比。'), model_ref)
    if s.get("points"):
        body += '<div class="box key"><h4>核心结论</h4><ol class="tight">' + "".join(f"<li>{E(x)}</li>" for x in s["points"]) + "</ol></div>"
    if s.get("after_the_fact"):  # 回溯样板：目标年真实结果，只有事后才知道，不能混进事前结论
        body += ('<div class="box"><h4>事后才知道的结果（填报时不可能知道，不参与上面的结论）</h4><ul class="tight">'
                 + "".join(f"<li>{E(x)}</li>" for x in s["after_the_fact"]) + "</ul></div>")
    if s.get("actions"):
        body += '<div class="box warn"><h4>接下来你要做的事</h4><ol class="tight">' + "".join(f"<li>{E(x)}</li>" for x in s["actions"]) + "</ol></div>"
    if s.get("plain"):
        body += "".join(f"<p>{E(x)}</p>" for x in s["plain"])
    sec("摘要", body)

    # 02 画像
    pr = rep.get("profile", {})
    body = ""
    if pr.get("intro"):
        body += f'<p class="lead">{E(pr["intro"])}</p>'
    if pr.get("facts"):
        body += "<table><thead><tr><th style='width:28%'>项目</th><th>情况</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{E(a)}</td><td>{E(b)}</td></tr>" for a, b in pr["facts"]) + "</tbody></table>"
    if pr.get("priorities"):
        body += figure('你最在乎什么', bars_h([(a, float(b)) for a, b in pr['priorities']], fmt=lambda v: f'{v:.0%}', vmax=1),
                       '权重越大，对偏好评分影响越大；石绿表示权重，稳妥程度另按滑档约束。', profile_ref)
    if pr.get("constraints"):
        body += '<div class="box"><h4>硬约束（不满足的学校和专业已经排除）</h4><ul class="tight">' + "".join(f"<li>{E(x)}</li>" for x in pr["constraints"]) + "</ul></div>"
    if pr.get("tensions"):
        body += '<div class="box warn"><h4>需要你想清楚的矛盾</h4><ul class="tight">' + "".join(f"<li>{E(x)}</li>" for x in pr["tensions"]) + "</ul></div>"
    sec("你的画像", body)

    # 03 方向
    ds = rep.get("directions", [])
    if ds:
        body = '<p class="lead">' + E(rep.get("directions_intro", "以下方向由兴趣、能力、目标和约束交叉得出。每个方向都列出支持证据、反面证据、有条件的就业前景和验证办法。")) + "</p><div class='grid2" + (" wide" if any(d.get("paths") for d in ds) else "") + "'>"
        for d in ds:
            body += (f'<div class="card"><div class="fit">{E(d.get("fit", ""))}</div><h3>{E(d["name"])}</h3>'
                     f'<div class="small">{E(d.get("majors", ""))}</div><dl>'
                     + (f"<dt>支持</dt><dd>{'；'.join(E(x) for x in d.get('evidence', []))}</dd>" if d.get("evidence") else "")
                     + (f"<dt>反面</dt><dd>{'；'.join(E(x) for x in d.get('counter', []))}</dd>" if d.get("counter") else "")
                     + (f"<dt>前景（有条件）</dt><dd>{'<br>'.join(E(x) for x in d.get('outlook', []))}</dd>" if d.get("outlook") else "")
                     + (f"<dt>怎么验证</dt><dd>{E(d['verify'])}</dd>" if d.get("verify") else "")
                     + "</dl>"
                     + ("<table><thead><tr><th style='width:14%'>去向</th><th>门槛</th><th>代价</th><th style='width:24%'>依据</th></tr></thead><tbody>"
                        + "".join(f"<tr><td>{E(a)}</td><td>{E(unprefix(b, '门槛'))}</td><td>{E(unprefix(c, '代价'))}</td><td class='small'>{E(unprefix(e, '依据'))}</td></tr>" for a, b, c, e in d["paths"])
                        + "</tbody></table>" if d.get("paths") else "")
                     + "</div>")
        body += "</div>"
        matrix_rows = [[d['name'], '△ '+d.get('fit','见方向分析'), '△ 见去向门槛', '△ 见条件前景',
                        '△ 按学校核对', '△ 见家庭约束'] for d in ds]
        body += figure('方向比较：先看证据，再核具体学校', comparison_matrix(['兴趣匹配', '门槛', '就业', '城市', '家庭接受度'], matrix_rows),
                       '△表示须结合下文证据或具体院校继续核实，不表示不匹配；本表不新增评分或改变方向结论。', profile_ref)
        if rep.get("roadmap"):
            body += ("<h3>路线图：门槛、顺序、里程碑与切换条件</h3><table><thead><tr><th style='width:20%'>核对项</th><th>安排</th></tr></thead><tbody>"
                     + "".join(f"<tr><td>{E(a)}</td><td>{E(b)}</td></tr>" for a, b in rep["roadmap"]) + "</tbody></table>")
        if rep.get("news"):
            body += ("<h3>近期报道与政策</h3><p class='small'>前景和录取线都会受社会情况影响。下表是填报前查到的相关报道，影响一栏是本报告的判断。</p>"
                     "<table><thead><tr><th>事件</th><th style='width:12%'>日期</th><th style='width:22%'>来源</th><th style='width:30%'>对本报告的影响</th></tr></thead><tbody>"
                     + "".join(f"<tr><td>{E(a)}</td><td class='small'>{E(b)}</td><td class='small'>{source_cell(c)}</td><td>{E(d)}</td></tr>" for a, b, c, d in rep["news"])
                     + "</tbody></table>")
        sec("专业方向", body)
    else:
        blank("directions", "专业方向", "本次没有做专业方向分析。")

    # 04 志愿表
    if lst:
        notes = rep.get("list_notes", {})
        body = '<p class="lead">下表就是建议的填报顺序。顺序按本人偏好排列，单独过线与最终录取是两个不同的量。</p>'
        if numeric:
            # Ten rows per chart keeps labels readable and the figure on one printed page.
            for start in range(0, len(lst), 10):
                part = lst[start:start+10]
                body += figure('各志愿的单独过线' + (f'（{start+1}—{start+len(part)}）' if len(lst)>10 else ''),
                               bar_chart([[f"{x['order']:02d} {x['name'][:17]}", x['p_clear'], x['tag'], html.unescape(fmt(x['p_clear']))] for x in part], maximum=1),
                               '红为冲、琥珀为稳、石绿为保；条长为单独过线，精度同主表。', model_ref)
        body += figure('你最终会被哪里录取', outcome_strip([(x['name'], x['p_land']) for x in lst], pfall or 0, fmt=strip_fmt), STRIP_CAP, model_ref)
        cols = "<colgroup><col style='width:5%'><col style='width:35%'><col style='width:7%'><col style='width:8%'><col style='width:12%'><col style='width:12%'><col style='width:21%'></colgroup>"
        body += "<table class='vt'>"+cols+"<thead><tr><th>序</th><th>志愿</th><th>类型</th><th>偏好</th><th>单独过线</th><th>最终录取</th><th>预测位次</th></tr></thead><tbody>"
        for x in lst:
            hl = " class='hl'" if likely and x is likely else ''
            probs = f"<td class='r'>{fmt(x['p_clear'])}</td><td class='r'>{fmt(x['p_land'],1)}</td>" if numeric else "<td>按分档</td><td>不显示百分比</td>"
            rank_cell = f"{x['expected_cut_rank']:,}" + (f"<div class='small'>{interval80(x)}</div>" if grade!='A' else '')
            snippets = [v.strip() for v in re.split(r'[。；]', notes.get(x['name'],'')) if v.strip() and not re.search(r'\d',v)]
            note = snippets[0] if snippets else ('请核章程限制' if x.get('limits') else '历年位次与计划见方法附表')
            note = note if len(note)<=18 else note[:17]+'…'
            body += (f"<tr{hl}><td class='num'>{x['order']}</td><td>{E(x['name'])}<span class='row-note'>{E(note)}</span></td>"
                     f"<td><span class='tag {E(x['tag'])}'>{E(x['tag'])}</span></td><td class='r'>{x['utility']:.1f}</td>{probs}<td class='r'>{rank_cell}</td></tr>")
        body += '</tbody></table>'
        body += ('<p class="small">"偏好"是 0–100 的分数，由"你的画像"一节的权重和各项打分算出。"单独过线"只看这一个志愿；"最终录取"考虑了前面志愿可能已经录取你；"预测位次"是今年最低录取位次的中位预测。'
                 '冲：单独过线 &lt; 40%；稳：40%–85%；保：≥ 85%。高亮行是最可能的去向。'
                 + ('' if grade == "A" else '本省概率评级为 ' + grade + '：' + GRADE_MEANING[grade] + '“80% 区间”指今年最低录取位次大约有八成可能落在这个范围内。')
                 + '</p>')
        sec("志愿表", body)

        # 05 为什么这样排
        rows = [("本报告的方案", eu, pfall, True)]
        bu, bs = opt.get("baseline_top_utility"), opt.get("baseline_safest")
        if bu:
            rows.append(("只挑最想去的", bu[0], bu[1], False))
        if bs:
            rows.append(("只挑最稳的", bs[0], bs[1], False))
        body = '<p class="lead">本方案兼顾偏好与落空代价；下图与其他两种填法使用同一组数据和假设。</p>'
        body += figure('三种填法的对比', strategy_chart(rows, fmt=(None if grade=='A' else (lambda p: fall_txt(p) if p==0 or numeric else '有'))),
                       strategy_caption(eu, pfall, bu, bs) + '深绿为本报告方案，浅色为对照填法。', model_ref)
        if rep.get("why"):
            body += "".join(f"<p>{E(x)}</p>" for x in rep["why"])
        if stress:
            body += (f'<div class="box"><h4>压力测试</h4><p>如果今年各校录取线的波动是往年的 {E(str(rep.get("stress_mult", 2)))} 倍，'
                     f'这张志愿表的期望效用为 {stress.get("expected_utility", 0):.1f}，滑档{("概率为 " + fall_txt(stress.get("p_fall"))) if grade == "A" else ("：" + fall_txt(stress.get("p_fall")))}。'
                     + ('波动放大后期望效用反而略高，是因为波动是双向放大的：排在前面的冲刺志愿意外过线的机会也变大，而后面的保底仍然够稳。这说明这张表在大波动下没有变差，不说明大波动对你有利。'
                        if stress.get("expected_utility", 0) > (eu or 0) and not stress.get("p_fall") else '') + '</p></div>')
        if rep.get("sensitivity"):
            body += "<h3>换一种假设，结论会变吗</h3><table><thead><tr><th>假设</th><th class='r'>期望效用</th><th class='r'>滑档概率</th><th>前段是否变化</th></tr></thead><tbody>" + "".join(
                f"<tr><td>{E(a)}</td><td class='r'>{E(str(b))}</td><td class='r'>{E(str(c))}</td><td>{E(d)}</td></tr>" for a, b, c, d in rep["sensitivity"]) + "</tbody></table>"
        sec("为什么这样排", body)
    else:
        blank("list", "志愿表", "本次没有运行志愿组合优化，因此没有志愿表。")
        blank("list", "为什么这样排", "本次没有运行志愿组合优化，因此没有排序依据与方案对比。")

    # 06 院校调研
    rs = rep.get("research", [])
    qs = rep.get("questions", [])
    if rs or qs:
        body = '<p class="lead">以下是对排名靠前学校的升学和就业调研。每条信息都注明了证据等级：官方文件 &gt; 多人一致 &gt; 单人说法 &gt; 推测。</p>'
        for r in rs:
            body += f"<h3>{E(r['school'])}</h3><table class='rt'><colgroup><col style='width:14%'><col><col style='width:24%'></colgroup><thead><tr><th>方面</th><th>发现</th><th>证据等级</th></tr></thead><tbody>" + "".join(
                f"<tr><td>{E(a)}</td><td>{E(b)}</td><td class='small' style='word-break:break-all'>{evidence_badge(next((g for g in ('官方','多人一致','单人说法','推测') if g in c), '推测'))} {E(c)}</td></tr>" for a, b, c in r.get("items", [])) + "</tbody></table>" + (
                "<p class='small' style='word-break:break-all'>来源：" + "；".join(E(u) for u in r["sources"]) + "</p>" if r.get("sources") else "")
        if qs:
            body += ('<div class="box key"><h4>请你亲自去问学长学姐的问题</h4><p class="small">开头先说明：每条回答请标"确认 / 听说 / 不知道"，不确定就说不知道。最好问两个以上、不同年级的人。</p><ol class="tight">'
                     + "".join(f"<li>{E(x)}</li>" for x in qs) + "</ol></div>")
        sec("院校调研", body)
    else:
        blank("research", "院校调研", "本次没有做院校调研。")

    # 07 待核实
    if rep.get("todo"):
        body = ('<p class="lead">以下事项会直接影响能不能报、报了能不能录，请在正式填报前逐一核对。</p><table><thead><tr><th class="c" style="width:8%">✓</th><th>事项</th><th style="width:30%">去哪里查</th></tr></thead><tbody>'
                + "".join(f"<tr><td class='c'>□</td><td>{E(a)}</td><td class='small'>{E(b)}</td></tr>" for a, b in rep["todo"]) + "</tbody></table>")
        sec("填报前核对清单", body)
    else:
        blank("todo", "填报前核对清单", "本次没有列出待核对事项。")

    # 填报单：照着录入官方系统
    if lst:
        rows_html = ""
        for x in lst:
            code = x.get("code") or ""
            sub = x.get("group") or x.get("major_code") or ""
            ms = "、".join(f"{i}. {m['name']}" for i, m in enumerate(x.get("majors") or [], 1))
            rows_html += (f"<tr><td class='c num'>{x['order']}</td><td class='num'>{E(code) or '＿＿＿'}</td><td>{E(x['name'].split('（')[0].split('·')[0] if x.get('group') else x['name'].split('（')[0])}</td>"
                          f"<td class='num'>{E(sub) or '＿＿'}</td><td class='small'>{E(ms) or '—'}{limit_line(x)}</td>"
                          f"<td class='c'>{('是' if x.get('obey', True) else '<b>否</b>') if x.get('group') else '—'}</td><td class='c'>□</td></tr>")
        body = ('<p class="lead">这一页用来照着录入志愿填报系统。录错一个代码，前面算得再准也没用，所以请逐格核对。</p>'
                '<div class="box warn"><h4>录入前必读</h4><ol class="tight">'
                '<li>院校代码、专业组或专业代码<b>每年可能变</b>：表中代码来自往年数据，必须按今年的招生计划或专业目录逐个核对、改正。</li>'
                '<li>专业组志愿：组内专业按下表顺序填；"服从调剂"一栏与本报告的计算一致，改动前先回来重算。</li>'
                '<li>录入后，把系统里的志愿表截图或打印，逐行对照本页勾选；提交前确认截止时间。</li></ol></div>'
                "<table><thead><tr><th class='c'>序</th><th>院校代码</th><th>院校</th><th>专业组 / 专业代码</th><th>组内专业志愿顺序</th><th class='c'>服从调剂</th><th class='c'>已核对</th></tr></thead><tbody>"
                + rows_html + "</tbody></table>")
        sec("填报单", body)
    else:
        blank("list", "填报单", "本次没有运行志愿组合优化，因此没有填报单。")

    # 可以直接问我（个性化的追问清单）
    if rep.get("ask_me"):
        body = ('<p class="lead">' + E(rep.get("ask_me_intro", "这份报告是和 AI 一起做出来的。看不懂的地方、想换个假设算一算，都可以直接回去问它。下面是根据你的情况预备的问题，挑感兴趣的问就行。")) + "</p>")
        for grp in rep["ask_me"]:
            body += f'<h3>{E(grp["topic"])}</h3><ul class="asklist">' + "".join(
                f'<li><b>“{E(q["q"])}”</b>' + (f'<span>{E(q["why"])}</span>' if q.get("why") else "") + "</li>" for q in grp["items"]) + "</ul>"
        body += '<p class="small">提问时可以直接说"按报告志愿表的第 3 个志愿……"，AI 会接着这份报告的数据回答；它不知道的会说不知道。</p>'
        sec("追问清单", body)
    else:
        blank("ask_me", "追问清单", "本次没有预备追问清单。")

    def block(b):
        """方法与事后回看的小节：标题、段落、可选表格。"""
        html = f"<h3>{E(b['title'])}</h3>" + "".join(f"<p>{E(x)}</p>" for x in b.get("paras", []))
        if b.get("rows"):
            html += ("<table><thead><tr>" + "".join(f"<th>{E(c)}</th>" for c in b.get("columns", [])) + "</tr></thead><tbody>"
                     + "".join("<tr>" + "".join(td(c) for c in row) + "</tr>" for row in b["rows"]) + "</tbody></table>")
        return html + "".join(f'<p class="small">{E(x)}</p>' for x in b.get("notes", []))

    # 08 方法与假设（可用术语）
    body = '<p class="lead">这一节写给想了解细节的读者，会用到一些专业术语，术语解释在本节末尾。</p>'
    if rep.get("assumptions"):
        body += "<h3>关键假设</h3><table><thead><tr><th style='width:24%'>参数</th><th style='width:14%'>取值</th><th>依据</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{E(a)}</td><td class='num'>{E(str(b))}</td><td>{E(c)}</td></tr>" for a, b, c in rep["assumptions"]) + "</tbody></table>"
    body += ("<h3>模型</h3><p>平行志愿按\"分数优先、遵循志愿、一次投档\"投档，考生落到表中第一个\"位次过线\"的志愿，因此表内按效用降序排列是最优的，需要优化的是入选集合。"
             "各志愿今年的最低录取位次按对数正态分布建模：均值为历年位次对数的近期加权平均（以去年为主）并修正全省漂移，波动取历年离散度与下限的较大者；各志愿通过共同因子相关。"
             "用蒙特卡洛模拟得到每种志愿组合的期望效用，再用边际改进贪心算法选择组合；基准下已无增益时，在压力情景（波动放大）下继续补位，只接受不降低基准期望的补位。</p>")
    if rep.get("backtest"):
        body += f"<h3>本省回测</h3><p>{E(rep['backtest'])}</p>"
    if m.get("prob_grade"):
        body += ("<h3>本报告的概率评级</h3><p><b>" + E(m["prob_grade"]) + " 级。</b>" + E(GRADE_MEANING.get(m["prob_grade"], "")) + "</p>"
                 + (f"<p>{E(m['grade_note'])}</p>" if m.get("grade_note") else ""))
    body += "".join(block(b) for b in rep.get("methods", []))
    body += ('<div class="box glossary"><h4>术语解释</h4><dl>'
             "<dt>位次</dt><dd>全省同科类考生中的排名，比分数更能跨年比较。</dd>"
             "<dt>期望效用</dt><dd>各种可能结局的满意度，按发生概率加权后的平均值。</dd>"
             "<dt>蒙特卡洛模拟</dt><dd>按历史波动随机生成几千种\"今年可能的录取线\"，统计各种结局出现的频率。</dd>"
             "<dt>漂移</dt><dd>全省录取位次整体逐年变宽或变紧的趋势。</dd>"
             "<dt>回测</dt><dd>用过去的数据去\"预测\"已经发生的年份，检验方法准不准。</dd></dl></div>")
    if lst:
        body += '<h3>各志愿历年位次与计划</h3><p class="small">原主表的历年位次、计划与组内说明集中在此；未公布或未核实的项目不补造数字。</p><table><thead><tr><th style="width:6%">序</th><th style="width:30%">志愿</th><th>历年位次、计划及补充说明</th></tr></thead><tbody>'
        body += ''.join(f"<tr><td>{x['order']}</td><td>{E(x['name'])}</td><td>{E(rep.get('list_notes',{}).get(x['name'],'未提供历年明细'))}{group_line(x,fmt)}{limit_line(x)}</td></tr>" for x in lst)
        body += '</tbody></table>'
    sec("方法与假设", body)

    # 事后回看（仅用于回测案例）
    if rep.get("hindsight"):
        h = rep["hindsight"]
        body = '<p class="lead">' + E(h.get("intro", "")) + "</p>"
        if h.get("table"):
            body += "<table><thead><tr>" + "".join(f"<th>{E(c)}</th>" for c in h["columns"]) + "</tr></thead><tbody>" + "".join(
                "<tr>" + "".join(td(c) for c in row) + "</tr>" for row in h["table"]) + "</tbody></table>"
        body += "".join(f"<p>{E(x)}</p>" for x in h.get("notes", []))
        body += "".join(block(b) for b in h.get("extra", []))
        sec("事后回看", body)
    else:
        sec("事后回看", '<p class="lead">' + E(omitted.get("hindsight", "录取结果公布后，把真实的投档线和最终去向填进这一节，与本报告的预测逐条对照：哪些判断准、哪些偏了、偏在哪里。这样下一次的判断才会更准。")) + "</p>")

    # 12 来源与声明：完整网址只在此列出。
    body = '<p><strong>以下来源对应正文编号；个人陈述、模型结果与官方资料分开列明。</strong></p>'
    body += ('<div class="box warn"><h4>声明</h4><ol class="tight">'
             "<li>本报告不是官方建议。一切以本省教育考试院当年的填报规则、招生计划和各校当年招生章程为准。</li>"
             "<li>概率来自历年数据的统计推算，不是录取承诺；AI 与模型都可能出错，请交叉核实。</li>"
             "<li>最终的决策权和后果，属于考生和家庭。</li></ol></div>")
    body += refs.render()
    sec("数据来源与声明", body)

    from datetime import date
    generated = date.today().isoformat()
    dates = [str(r[2])[:10] for r in rep.get('sources',[]) if re.match(r'\d{4}-\d{2}-\d{2}',str(r[2]))]
    asof = m.get('data_asof') or (max(dates) if dates else m.get('date','待核'))
    if len(str(asof))>32: asof = '见摘要报告口径'
    report_id = m.get('case_id') or m.get('id') or '待编号'
    subtitle = ' · '.join(part.strip() for part in m.get('subtitle','').split('·') if not re.search(r'样板|模拟|虚构|实际生成|回溯版|案例',part))
    cover = cover_html(m.get('title','高考志愿填报决策报告'), subtitle, m.get('candidate','本人'),
                       m.get('stage','高考版 · 填报决策'), m.get('province','待核'), report_id, generated, asof,
                       s.get('headline',''), [(i,t) for i,t,_ in secs])
    if missing:
        print('提醒：以下各节没有内容：'+'、'.join(dict.fromkeys(missing)),file=sys.stderr)
    return document_html(m.get('title','高考志愿填报决策报告'),cover,''.join(b for _,_,b in secs),m.get('candidate','本人'),'高考',report_id)


def write_sheet(opt, path):
    """填报单 CSV：列与报告“填报单”一节一致，代码缺失的留空，由 case_check 拒绝。"""
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["序", "院校代码", "院校", "专业组", "专业代码", "组内专业顺序", "服从调剂"])
        for x in (opt or {}).get("list", []):
            ms = "、".join(f"{i}. {mj['name']}" for i, mj in enumerate(x.get("majors") or [], 1))
            w.writerow([x["order"], x.get("code") or "", x["name"].split("（")[0].split("·")[0] if x.get("group") else x["name"].split("（")[0],
                        x.get("group") or "", x.get("major_code") or "", ms, ("是" if x.get("obey", True) else "否") if x.get("group") else "—"])


def find_browser():
    cands = [os.environ.get("CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "/Applications/Chromium.app/Contents/MacOS/Chromium",
             shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("msedge"),
             r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    return next((c for c in cands if c and os.path.exists(c)), None)



def layout_gate(pdf):
    """生成 PDF 后必做的版面自检；表格挤成一字一行、数字拆行等问题直接报错。"""
    try:
        from check_layout import check_pdf
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from check_layout import check_pdf
    try:
        issues = check_pdf(pdf)
    except ImportError:
        sys.exit("未安装 PyMuPDF，无法执行强制版面自检；请安装后重新生成，不能交付未检查的PDF。")
    if issues:
        print("✗ 版面自检没通过：", file=sys.stderr)
        for msg in issues:
            print("    " + msg, file=sys.stderr)
        sys.exit("请修好版式后重新生成；不要交付这份 PDF。")
    print("版面自检通过")

def main():
    ap = argparse.ArgumentParser(description="知衢 · 生成志愿填报决策报告（PDF/HTML）")
    ap.add_argument("report", help="报告内容 JSON（字段见 references/report-guide.md）")
    ap.add_argument("--opt", help="optimize.py --json 的输出")
    ap.add_argument("--out", required=True, help="输出文件，.pdf 或 .html")
    ap.add_argument("--sheet", help="另存填报单 CSV（序、院校代码、院校、专业组、专业代码、组内专业顺序、服从调剂），与报告里的填报单一致")
    a = ap.parse_args()
    rep = json.load(open(a.report, encoding="utf-8"))
    opt = json.load(open(a.opt, encoding="utf-8")) if a.opt else None
    if opt:
        errors = check_report(rep, opt)
        if errors:
            ap.error("报告数字核验失败：" + "；".join(errors))
    if a.sheet:
        write_sheet(opt, a.sheet)
    doc = build(rep, opt)
    publication_gate(doc)
    if a.out.lower().endswith(".html"):
        open(a.out, "w", encoding="utf-8").write(doc)
        print(f"已生成 {a.out}")
        return
    br = find_browser()
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    tmp.write(doc)
    tmp.close()
    if not br:
        html_out = os.path.splitext(a.out)[0] + ".html"
        shutil.copy(tmp.name, html_out)
        sys.exit(f"没有找到 Chrome/Edge，已输出 {html_out}；请用浏览器打开后\"打印 → 存储为 PDF\"（勾选\"背景图形\"）。")
    out = os.path.abspath(a.out)
    if os.path.exists(out):
        os.unlink(out)
    with tempfile.TemporaryDirectory() as prof:
        # 部分环境下 Chrome 打印完不会自行退出：等 PDF 写完且大小稳定后结束进程
        proc = subprocess.Popen([br, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={prof}",
                                 f"--print-to-pdf={out}", "file://" + tmp.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


if __name__ == "__main__":
    main()
