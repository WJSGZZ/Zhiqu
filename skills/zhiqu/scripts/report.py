#!/usr/bin/env python3
"""知衢 · 志愿填报决策报告生成器（仅用 Python 标准库；PDF 由本机 Chrome/Edge 无头模式打印）。

用法：
  python3 report.py report.json --opt result.json --out <报告号>-report.pdf --profile-version profile.txt
  python3 report.py report.json --opt result.json --out 报告.html   # 只要 HTML

report.json 的字段见 references/report-guide.md；result.json 是 optimize.py --json 的输出。
找不到浏览器时会只输出 HTML，并提示用浏览器"打印 → 存储为 PDF"。
"""
import argparse
from check_report import check_report, publication_gate
from data_provenance import (entries as provenance_entries, evidence_lines,
                             only_third_party, prediction_label)
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
from pathlib import Path

E = html.escape
NUM_CELL = re.compile(r"[\d,.\s%~～+\-–—<>≥≤/]+|(?:不到|超过|约)\s?[\d,.]+%?")


def td(c):
    """表格单元格：纯数字（位次、分数、百分比、序号）不换行，避免被拆成两行。"""
    s = str(c)
    cls = " class='num'" if NUM_CELL.fullmatch(s.strip()) else ""
    return f"<td{cls}>{E(s)}</td>"

CSS = r"""
@page { size: A4; margin: 20mm 18mm 20mm 18mm; background: #F2EEE3;
  @top-left { content: "__TOPLEFT__"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #6E776E; }
  @top-right { content: "__RUNHEAD__"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #6E776E; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #6E776E; }
  @bottom-left { content: "仅供参考 · 以当年官方文件为准"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #9CA197; }
}
@page cover { margin: 0; @top-left { content: none; } @top-right { content: none; } @bottom-right { content: none; } @bottom-left { content: none; } }
:root { --sans: "PingFang SC","Source Han Sans SC","Noto Sans SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; --ink:#222A26; --soft:#454E48; --muted:#6E776E; --rule:#D3CCB8; --rule2:#B5AD98;
  --accent:#21473E; --accent2:#34685D; --pale:#E3DDCB; --amber:#A8772B; --red:#9B3B2E; --green:#34685D; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
html, body { background: #F2EEE3; }
body { margin: 0; color: var(--ink); font: 10pt/1.75 "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; font-feature-settings: "lnum"; }
h1,h2,h3 { font-family: "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; font-weight: 700; color: var(--ink); }
h2 { font-size: 18pt; letter-spacing: .5pt; margin: 0 0 4.5mm; padding-bottom: 2.5mm; border-bottom: 1.2pt solid var(--accent); break-after: avoid; }
h2 .no { color: var(--accent); margin-right: 3.5mm; font: 600 12pt var(--sans); letter-spacing: 1pt; vertical-align: 2pt; }
h3 { font-size: 12pt; margin: 6mm 0 2mm; break-after: avoid; }
p { margin: 0 0 2.6mm; }
section { margin-top: 12mm; }
section.newpage { break-before: page; margin-top: 0; }
/* 节标题和第一句不单独留在页底：跟着下面的内容走。 */
h2 + p, h2 + .lead { break-after: avoid; }
section[data-kind="plan"]:not([data-section="12"]) > h2 + p:has(> strong:first-child) { break-inside: avoid; }
p, li, dd { orphans: 3; widows: 3; }
/* 节末只剩一两行掉到新页时（check_layout 的孤页检查），生成器给这一节加 fit / fit2 后重排：
   只收行距和段距，字号不变；fit2 再紧一档。 */
section.fit p, section.fit li, section.fit dd { line-height: 1.62; }
section.fit p { margin-bottom: 1.8mm; } section.fit h3 { margin-top: 4.5mm; }
section.fit ul.asklist li { padding: 1.5mm 0 1.5mm 4mm; margin-bottom: 1.4mm; }
section.fit tbody td { padding: 1.2mm 2mm; } section.fit .fig { margin-bottom: 3.5mm; }
section.fit2 p, section.fit2 li, section.fit2 dd { line-height: 1.52; }
section.fit2 p { margin-bottom: 1.2mm; } section.fit2 h3 { margin-top: 3.5mm; }
section.fit2 .box { padding: 3mm 4mm; margin: 2mm 0 3mm; }
h4, dt { break-after: avoid; }
svg.chart { width: 100%; height: auto; display: block; }
.lead { font-size: 11pt; color: var(--soft); break-after: avoid; }
.small { font-size: 8.5pt; color: var(--muted); }
.num { font-variant-numeric: tabular-nums; }
.url { display: block; font: 7pt/1.35 var(--sans); color: var(--muted); word-break: break-all; margin-top: .6mm; }

/* cover */
.cover { page: cover; width: 210mm; height: 296mm; overflow: hidden; padding: 0; position: relative; background: #F2EEE3; break-after: page; }
.cover .band { background: var(--accent); color: #F2EFE6; padding: 20mm 22mm 10mm; }
.cover .kicker { font-size: 9pt; letter-spacing: 3pt; opacity: .85; }
.cover h1 { color: #F2EEE3; font-size: 30pt; margin: 6mm 0 3mm; letter-spacing: 1pt; }
.cover .sub { font-size: 11pt; opacity: .9; }
.cover .motto { margin-top: 6mm; font-size: 10.5pt; letter-spacing: 4pt; opacity: .78; display: flex; align-items: center; gap: 4mm; }
.cover .motto::before { content: ""; width: 8mm; height: .6pt; background: #F2EFE6; opacity: .7; }
.cover .meta { padding: 8mm 22mm 0; display: grid; grid-template-columns: repeat(3,1fr); gap: 4mm 8mm; }
.cover .meta div { border-top: .8pt solid var(--rule2); padding-top: 2mm; }
.cover .meta b { display:block; font-size: 8pt; color: var(--muted); font-weight: 500; letter-spacing: 1pt; }
.cover .meta span { font-size: 12pt; }
.cover .verdict { margin: 9mm 22mm 0; padding: 6mm 8mm; background: #FFFDF8; border-left: 3pt solid var(--accent); }
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
.box { background: #FFFDF8; border: .6pt solid var(--rule); padding: 4mm 5mm; margin: 3mm 0 4mm; }
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
/* 正文里每个数字都套 .number-run 防止拆行。它只负责不拆行，外观一律跟随所在文字；
   其他规则里的 "xx span" 不能改到它（曾把封面编号拆成三行、把问句里的 2.5 变成独立一行）。 */
.number-run { white-space:nowrap !important; display:inline !important; font:inherit !important; color:inherit !important;
  margin:0 !important; padding:0 !important; border:0 !important; background:none !important; min-height:0 !important;
  width:auto !important; letter-spacing:inherit !important; }
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
.tag.冲 { background: var(--amber); } .tag.稳 { background: var(--accent2); } .tag.保 { background: var(--accent); }

/* two columns / cards */
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; }
.grid2.wide { grid-template-columns: 1fr; }
.card table { font-size: 8.3pt; margin: 2.5mm 0 0; }
.card table thead th { border-top: .6pt solid var(--rule2); }
.card { background: #FFFDF8; border-top: 1.6pt solid var(--accent2); padding: 4mm 5mm 3mm; }
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
ul.asklist li { padding: 2mm 0 2mm 4mm; border-left: 2pt solid var(--rule2); margin: 0 0 2mm; background: #FFFDF8; break-inside: avoid; }
ul.asklist li b { font-weight: 600; }
.ask-line { font-size: 8.5pt; line-height: 1.55; color: var(--soft); margin-top: .6mm; }
.ask-line em { font: normal 600 7.6pt var(--sans); color: var(--accent2); margin-right: 2mm; }
.trigger-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; margin: 2mm 0 4mm; }
.trigger { background: #FFFDF8; border-left: 2pt solid var(--amber); padding: 2.5mm 3.5mm; break-inside: avoid; }
.trigger .if { font-weight: 600; font-size: 9.2pt; margin-bottom: .8mm; }
.trigger .if em { font: normal 600 7.6pt var(--sans); color: var(--amber); margin-right: 2mm; }
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
.matrix td { font-size:8pt; line-height:1.45; }
.matrix td.opt { font-weight:600; }
i.dot { display:inline-block; width:3.6mm; height:3.6mm; margin-right:1.4mm; vertical-align:-.7mm; font-style:normal; }
i.dot svg { display:block; width:100%; height:100%; }
i.checkbox { display:inline-block; width:3.2mm; height:3.2mm; border:.8pt solid var(--rule2); border-radius:.6mm; background:#FFFDF8; vertical-align:-.5mm; }
.matrix-key { font:7.6pt var(--sans); color:var(--muted); margin:-2mm 0 3mm; }
.facts { display:grid; grid-template-columns:repeat(3,1fr); gap:2mm; margin:1mm 0 3mm; }
.fact { padding:1.8mm 2.6mm; background:#FFFDF8; border-left:2.2pt solid var(--accent); break-inside:avoid; }
.fact.pending { border-left-color:var(--amber); background:#F5ECD9; }
.fact.unknown { background:transparent; border:.8pt dashed var(--rule2); }
.fact b { display:block; font:600 7.6pt var(--sans); color:var(--muted); letter-spacing:.3pt; }
.fact span { display:block; font-size:9.4pt; line-height:1.45; }
.fact.unknown span { color:var(--muted); }
i.fk { display:inline-block; width:3.4mm; height:2.6mm; margin-right:1.2mm; vertical-align:-.3mm; }
i.fk.known { background:#FFFDF8; border-left:2.2pt solid var(--accent); }
i.fk.pending { background:#F5ECD9; border-left:2.2pt solid var(--amber); }
i.fk.unknown { border:.8pt dashed var(--rule2); }
.fig .matrix-key { margin:1mm 0 0; }
.panel-ttl { font:600 7.8pt var(--sans); color:var(--accent); margin:2mm 0 .5mm; }
.timeline { margin:4mm 0; }
.timeline-row { display:flex; gap:3mm; margin:0 0 4mm; border-top:1.2pt solid var(--rule2); }
.milestone { flex:1; padding:3mm 2mm 0; position:relative; font-size:8pt; }
.milestone::before { content:''; position:absolute; top:-1.55mm; left:2mm; width:2.6mm; height:2.6mm; border-radius:50%;
  background:var(--accent2); }
.milestone.checkpoint::before { border-radius:.3mm; transform:rotate(45deg); background:var(--amber); }
.milestone b, .milestone strong, .milestone span { display:block; }
.milestone b { color:var(--accent); margin-bottom:1mm; }
.milestone span { color:var(--muted); margin-top:1mm; }
.route-card { border: .6pt solid var(--rule); border-left:2.5pt solid var(--accent); padding:4mm; margin:3mm 0 5mm; background:#FFFDF8; }
.route-card h3 { margin:0 0 2mm; }
.route-card dl { display:grid; grid-template-columns:repeat(4,1fr); margin:0; gap:4mm; font-size:8.8pt; }
.route-card dt { color:var(--accent); font:600 8pt var(--sans); margin-bottom:1mm; }
.route-card dd { margin:0; }
.evidence { display:inline-block; padding:.3mm 1.5mm; font:7.8pt var(--sans); border: .5pt solid var(--rule2); }
.evidence.official { background:var(--accent);color:#fff; }
.evidence.corroborated { background:var(--accent2);color:#fff; }
.evidence.single { background:var(--pale);color:var(--ink); }
.evidence.inference { background:transparent;color:var(--muted); }
.evidence.missing { background:transparent;color:var(--muted);border-style:dashed; }
.evidence.compiled { background:transparent;color:var(--amber);border-color:var(--amber); }
/* 院校卡片：一格一个方面、一句结论；完整调研在第 12 节。 */
.school-card { background:#FFFDF8; border-top:1.6pt solid var(--accent2); padding:3.5mm 5mm 1mm; margin:0 0 5mm; break-inside:avoid; }
.school-card h3 { margin:0 0 2.5mm; font-size:11.5pt; }
/* 长信息卡（高考路线图）可在格与格之间换页，格内不拆、标题不落单：整块卡挤到下一页会在节中间留下大半页空白（2026-10-20 版面空白检查）。 */
.school-card.breakable { break-inside:auto; -webkit-box-decoration-break:clone; box-decoration-break:clone; } .school-card.breakable h3 { break-after:avoid; } .school-card.breakable .school-grid > div { break-inside:avoid; }
.school-card h3 small { font:400 8pt var(--sans); color:var(--muted); margin-left:2mm; }
.school-grid { display:grid; grid-template-columns:1fr 1fr; gap:0 7mm; }
.school-grid > div { border-top:.4pt solid var(--rule); padding:1.8mm 0 2.2mm; }
.school-grid .aspect { display:flex; justify-content:space-between; align-items:center; font:600 8.2pt var(--sans); color:var(--accent); margin-bottom:.8mm; }
.school-grid p { margin:0; font-size:9pt; line-height:1.6; }
section[data-section="12"] h3 { font-size:11pt; }
section[data-section="12"] h4 { font:600 9.5pt var(--sans); color:var(--accent); margin:4mm 0 1.5mm; }
.source-ref { color:var(--accent);font-size:7.5pt; }
.source-notes { list-style:none; padding:0; font-size:7.8pt; line-height:1.35; }
.source-notes li { margin:0 0 .6mm; break-inside:avoid; }
section[data-section="12"] { margin-top:6mm; }
.source-notes .url { display:inline; margin-left:1.5mm; line-height:1.35; }
table.vt th { white-space:normal; }
table.vt td .row-note { display:block;white-space:nowrap;font-size:7.8pt;font-weight:400;color:var(--muted); }
/* 核对材料：紧凑排版，同一出处只印一次；长网址可断行。 */
.verification-appendix { font-size:8.6pt; line-height:1.45; }
.verification-appendix h4 { font:600 9.5pt var(--sans); color:var(--accent); margin:5mm 0 2mm; break-after:avoid; }
.verification-appendix .audit-list { margin:.5mm 0 1mm; padding-left:5mm; }
.verification-appendix p { margin:0 0 1mm; }
.verification-appendix table { width:100%; border-collapse:collapse; margin:1mm 0 2mm; font-size:8pt; table-layout:auto; }
.verification-appendix th, .verification-appendix td { padding:2.5pt 4pt; border-bottom:.4pt solid var(--rule); vertical-align:top; text-align:left; line-height:1.35; overflow-wrap:anywhere; }
.verification-appendix thead th { color:var(--muted); font-weight:600; }
.verification-appendix .audit-kv th { width:30%; color:var(--muted); font-weight:400; }
.verification-appendix .audit-sec { white-space:nowrap; color:var(--muted); }
.verification-appendix .audit-source { border-bottom:.4pt solid var(--rule); padding:1.5mm 0 2mm; }
.verification-appendix .audit-ev, .verification-appendix .audit-src-head { break-inside:avoid; }
.verification-appendix .audit-src-head { break-after:avoid; }
.verification-appendix .audit-claim { margin-top:1.2mm; margin-bottom:0; }
.verification-appendix .audit-excerpt { color:var(--soft); }
.verification-appendix .audit-vals { color:var(--accent); }
.verification-appendix .audit-item { border-bottom:.4pt solid var(--rule); padding:1.5mm 0; break-inside:avoid; }
.verification-appendix .audit-url { font-size:7.2pt; color:var(--muted); overflow-wrap:anywhere; word-break:break-all; }
.verification-appendix dt { font-weight:600; color:var(--accent); }
.verification-appendix dd { margin:0 0 2mm; overflow-wrap:anywhere; }
.verification-appendix blockquote { margin:1mm 0 2mm 3mm; color:var(--soft); }

"""


# 三版打印规范：A4/既有字体与色板；正文10pt/1.75，节标题18pt，
# 小标题12pt；图内文字10.5 SVG单位（640宽映射174mm，实际约8pt），最低7pt。
# 千分位数字、中文量词前空格、区间用“—”；概率精度仍由prob_formatter控制。
# 颜色只有一套含义：黛绿 = 主选／本方案，石绿 = 一般数据，琥珀 = 提醒或对照情景，红 = 风险（滑档、超预算）。
PALETTE = {'冲': '#9B3B2E', '稳': '#A8772B', '保': '#34685D', '主': '#21473E', '次': '#34685D', '留意': '#A8772B', '不利': '#9B3B2E'}
# 读研、求职图表只用中性色名（主、次、留意、不利），不借用高考的冲／稳／保：
# 色名会原样留在 report.md 和 PDF 附件数据里，读者会把“冲”读成“可以冲一冲”。
NEUTRAL_TAGS = ('主', '次', '留意', '不利')
GAOKAO_TAGS = ('冲', '稳', '保')
# 高考志愿的冲／稳／保按把握程度由浅到深：冲要留意（琥珀），稳（石绿），保（黛绿）；红色留给滑档。
CERTAINTY = {'冲': '#A8772B', '稳': '#34685D', '保': '#21473E'}
URL_RE = re.compile(r'https?://[^\s<>"\'，；。）、（【】]+')


def display_text(value):
    """只规范显示，不回写数据；编号/日期/专业代码不转换。"""
    text = str(value)
    text = re.sub(r'(?<![A-Za-z0-9_,.])(\d{4,})(?=\s*(?:元|名|人|位|小时))', lambda m: f'{int(m[1]):,}', text)
    return re.sub(r'(\d)(?=(?:万|亿)?(?:元|分(?!位)|名|人|小时))', r'\1 ', text)


# 引号里的是原话或原文，发布层不改字。
QUOTED = re.compile(r'(“[^”]*”|「[^」]*」|『[^』]*』)')
# “模拟”只在指计算（蒙特卡洛模拟、模拟次数）时改称“试算”；考试和练习里的“模拟”（上机模拟、模拟考、
# 模拟面试）是本人或原文的说法，照印。曾把本人原话“没做过完整的上机模拟”印成“上机试算”。
SIMULATION = re.compile(r'(?<!上机)(?<!面试)(?<!笔试)(?<!机考)(?<!全真)(?<!实战)(?<!口语)(?<!考试)模拟(?![考卷题面测训练器联法])')


def public_words(text):
    """发布层的换词（开发措辞→读者用语）；不动引号内的原话。数字格式在 display_text。"""
    def words(part):
        part = part.replace('模拟用户','本人').replace('模拟考生','本案考生').replace('虚构考生','本案考生')
        part = SIMULATION.sub('试算', part)
        # “虚构”只在开发措辞里换（虚构数据、虚构演示）；“不比较虚构年薪”的“虚构”是读者用语，换成“本案”意思就反了。
        part = re.sub(r'虚构(?=考生|示例|演示|数据|案例|人物|用户|样例)', '本案', part)
        for old,new in [('示例','本案'),('演示','对照'),('复现','复核'),('脚本','计算方法')]:
            part = part.replace(old,new)
        part = re.sub(r'python3\s+scripts/[^；。]+','按本节记录的方法重新核算',part)
        part = re.sub(r'(?:skills/zhiqu/)?(?:scripts/|data/calibration/)?[A-Za-z_]+\.py','本省检验方法',part)
        for old,new in [('retro_ranks/<位次>/','各位次的独立结果'),('retro_ranks.csv','多档位次汇总'),('retro_config.json','事前登记'),('hindsight.json','事后对照记录'),('preferences_review.json','偏好核对记录'),('data/schools.csv','教育部高校名录'),('model_review_2026.csv','年度检验记录'),('README.md','来源说明')]:
            part = part.replace(old,new)
        for old,new in [('预测过线','单独过线'),('过线概率','单独过线'),('落点概率','最终录取'),('最终录取概率','最终录取'),('预测线','预测位次')]:
            part = part.replace(old,new)
        return part
    return ''.join(chunk if QUOTED.fullmatch(chunk) else words(chunk) for chunk in QUOTED.split(str(text)))


def public_text(text):
    """发布层仅清理开发措辞；输入JSON与结论、数值保持原样。"""
    return display_text(public_words(text).replace('–','—'))


def simulated_name(name, simulated=True):
    """示例报告在名字后标“（模拟）”；正式案例（真实客户）不标。"""
    name = re.sub(r'^(?:虚构示例|模拟用户|示例)\s*[·：]?\s*', '', str(name)).replace('（虚构）','')
    if not simulated: return name.replace('（模拟）','')
    return name if '（模拟）' in name else name + '（模拟）'


def cover_html(title, subtitle, person, stage, region, report_id, generated, data_asof, conclusion, sections, simulated=True):
    """三版唯一封面：固定六格；长说明移到摘要，调用方负责保留。"""
    rows = [('对象', simulated_name(person, simulated)), ('版本或阶段', stage), ('地区或学校', region),
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


def core_conclusions(items, rendered=False):
    """三版唯一核心结论样式：圆点列表与粗体短标题，保留原句全部信息。"""
    rows = []
    for item in items:
        text = str(item)
        if rendered and re.match(r"^<(?:strong|b)>", text):
            content = text
        elif not rendered and re.match(r"^[^：:。；，]{1,12}[：:]", text):
            heading, detail = re.split(r"[：:]", text, maxsplit=1)
            content = f"<strong>{E(heading)}：</strong>{E(detail)}"
        else:
            content = '<strong>判断：</strong>' + (text if rendered else E(text))
        rows.append('<li>' + content + '</li>')
    return '<div class="box key core-conclusions"><h4>核心结论</h4><ul class="tight">' + ''.join(rows) + '</ul></div>'


VERIFY_MARK = '逐项核对材料'  # verify_report.py 以此分开正文与核对材料；全文只出现一次
VERIFY_SLOT = '<!--ZQ-VERIFY-->'


def verification_appendix_html(materials):
    """核对附录的唯一打印组件。输入为可读字段，不接收未转义HTML。

    同一出处、同一摘录、同一计算项只印一次，下面列出它支撑的全部数字与所在节；
    每个数字的原值都留在可提取的文字里，供 verify_report.py 与其他读者逐项核对。
    """
    def val(value):
        if isinstance(value, dict):  # 不印 JSON：只列取值
            value = '；'.join(str(v) for v in value.values() if v not in (None, ''))
        elif isinstance(value, (list, tuple)):
            value = '；'.join(map(str, value))
        if isinstance(value,float):value=format(value,'.10g')
        return E(str(value if value is not None else '未登记'))
    def secs(text):
        text=str(text or '').strip()
        return E(text) if text else '—'
    numbers=materials.get('numbers', [])
    registered=('本人','本报告设置','报告登记')
    evidence=[r for r in numbers if r.get('evidence_id')]
    registry=[r for r in numbers if not r.get('evidence_id') and str(r.get('institution','')).startswith(registered)]
    model=[r for r in numbers if not r.get('evidence_id') and '：' in str(r.get('label','')) and str(r.get('institution','')).startswith('录取线模型')]
    calc_refs={r['calculation_path']:r for r in numbers if r.get('calculation_path')}
    from verify_report import calculation_display_values
    calc_displays=calculation_display_values(numbers)
    formulas=[r for r in numbers if r.get('path') and r.get('formula') is not None]
    used=set(map(id,evidence+registry+model+formulas))|{id(r) for r in numbers if r.get('calculation_path')}
    rest=[r for r in numbers if id(r) not in used]

    body = (f'<div class="verification-appendix"><h3>{VERIFY_MARK}</h3><p>本 PDF 附带数据文件，可用 PDF 阅读器的附件面板取出。'
            '下面按出处列出报告里的数字：同一出处、同一段原文只印一次，后面跟着它支撑的数字和所在章节。</p>')
    case_info = materials.get('case_info', [])
    if isinstance(case_info, dict):
        case_info = case_info.items()
    body += '<h4>案例信息</h4><table class="audit-kv"><tbody>' + ''.join(f'<tr><th>{val(k)}</th><td>{val(v)}</td></tr>' for k, v in case_info) + '</tbody></table>'

    personal=materials.get('personal_inputs', [])
    if personal:
        body += '<h4>分析用到的本人信息</h4><table class="audit-grid"><thead><tr><th>项目</th><th>本人填写</th><th>用于</th></tr></thead><tbody>'
        body += ''.join(f'<tr><td>{val(r.get("label","本人输入"))}</td><td>{val(r.get("value"))}</td><td class="audit-sec">{secs(r.get("sections"))}</td></tr>' for r in personal)
        body += '</tbody></table>'

    if evidence:
        body += '<h4>官方出处与数字</h4>'
        groups={}
        for r in evidence:
            groups.setdefault((r.get('institution',''),r.get('url','')),{}).setdefault(r['evidence_id'],[]).append(r)
        for (inst,url),items in groups.items():
            body += f'<div class="audit-source"><p class="audit-src-head"><b>{val(inst or "出处")}</b></p>'
            if url:body += f'<p class="audit-url">{val(url)}</p>'
            # 同一出处里摘录相同的几条合在一起：原文只印一次，下面逐条列出核对项和数字。
            by_excerpt={}
            for eid,rows in items.items():by_excerpt.setdefault(str(rows[0].get('excerpt') or ''),[]).append(rows)
            for excerpt,claims in by_excerpt.items():
                body += '<div class="audit-ev">'
                for rows in claims:
                    body += (f'<p class="audit-claim">{val(rows[0].get("label","核对项"))}：<span class="audit-vals">'
                             + '；'.join(f'{val(r.get("value"))}（{secs(r.get("sections"))}）' for r in rows) + '</span></p>')
                if excerpt:body += f'<p class="audit-excerpt">原文：{E(excerpt)}</p>'
                body += '</div>'
            body += '</div>'

    qualitative=materials.get('qualitative', [])
    if qualitative:
        body += '<h4>非数字依据</h4><p>正文判断用到、但不以数字出现的官方原文。每条依次是：说法、原文摘录、出处与链接、所在节。</p>'
        for r in qualitative:
            body += (f'<div class="audit-item"><p><b>{val(r.get("label"))}</b>（{secs(r.get("sections"))}）</p>'
                     f'<p class="audit-excerpt">原文：{E(str(r.get("excerpt","")))}</p>'
                     + (f'<p>适用范围：{val(process_words(r["scope"]))}</p>' if r.get('scope') else '')
                     + f'<p>出处：{val(r.get("institution") or "出处")}</p>'
                     + (f'<p class="audit-url">{val(r["url"])}</p>' if r.get('url') else '') + '</div>')

    if formulas or calc_refs:
        body += '<h4>计算项</h4><p>按登记输入复算；详细依据和原始数值见 PDF 附带的计算明细。</p><table class="audit-grid"><thead><tr><th>项目</th><th>结果</th><th>算法</th><th>所在节</th></tr></thead><tbody>'
        seen=set()
        for r in formulas:
            ref=calc_refs.get(r['path'])
            if ref is not None:seen.add(r['path'])
            nums={k:v for k,v in (r.get('inputs') or {}).items() if isinstance(v,(int,float)) and not isinstance(v,bool)} if isinstance(r.get('inputs'),dict) else {}
            inputs=('；输入 '+'，'.join(f'{E(str(k))}={val(v)}' for k,v in nums.items())) if nums else ''
            result=val(calc_displays[r['path']])
            # 仅印一种已登记显示值（如10.4%），原始0.104仍在计算附件中。
            body += f'<tr><td>{val(r.get("label",r["path"]))}</td><td>{result}</td><td>{val(r.get("formula"))}{inputs}</td><td class="audit-sec">{secs(r.get("sections"))}</td></tr>'
        for path,ref in calc_refs.items():
            if path in seen:continue
            body += f'<tr><td>{val(ref.get("label") or "参数登记项")}</td><td>{val(calc_displays[path])}</td><td>参数登记，见 PDF 附带的计算明细</td><td class="audit-sec">{secs(ref.get("sections"))}</td></tr>'
        body += '</tbody></table>'

    if model:
        body += ('<h4>志愿计算结果</h4><p>概率是 0—1 之间的小数，由录取线模型模拟得出：单独过线 = 该志愿过线的模拟次数 ÷ 总模拟次数；最终录取 = 此前志愿都未录取、本志愿录取的次数 ÷ 总模拟次数。'
                 '预测位次 = 历史位次按登记漂移调整后，近期加权的对数均值。偏好分来自本人排序和登记评分。原序候选表 candidates.csv 和结果 result.json 都在附件里，可逐项复算。</p>')
        cols=['单独过线','最终录取','预测位次','偏好分'];table={}
        for r in model:
            name,_,field=str(r['label']).rpartition('：')
            table.setdefault(name,{})[field]=r
        body += '<table class="audit-grid"><thead><tr><th>志愿</th>' + ''.join(f'<th>{c}</th>' for c in cols) + '</tr></thead><tbody>'
        for name,fields in table.items():
            body += f'<tr><td>{val(name)}</td>' + ''.join(f'<td class="num">{val(fields[c].get("value")) if c in fields else "—"}</td>' for c in cols) + '</tr>'
        body += '</tbody></table>'

    if registry:
        body += '<h4>登记值</h4><p>本人画像、报告设置的个人检查点和费用情景，不是官方数据。</p><table class="audit-grid"><thead><tr><th>值</th><th>登记项</th><th>所在节</th></tr></thead><tbody>'
        body += ''.join(f'<tr><td>{val(r.get("value"))}</td><td>{val(r.get("label"))}</td><td class="audit-sec">{secs(r.get("sections"))}</td></tr>' for r in registry)
        body += '</tbody></table>'

    if rest:
        body += '<h4>其他核对项</h4>'
        for r in rest:
            how='；'.join(str(r.get(k)) for k in ('inputs','formula','verification_limit') if r.get(k) not in (None,'',[],{}))
            body += (f'<div class="audit-item"><p><b>{val(r.get("label","核对项"))}</b>：{val(r.get("value"))}（{secs(r.get("sections"))}）</p>'
                     + (f'<p>出处：{val(r["institution"])}</p>' if r.get('institution') else '')
                     + (f'<p class="audit-excerpt">原文：{val(r["excerpt"])}</p>' if r.get('excerpt') else '')
                     + (f'<p class="audit-excerpt">核对方式：{E(how)}</p>' if how else '')
                     + (f'<p class="audit-url">{val(r["url"])}</p>' if r.get('url') else '') + '</div>')

    limits=[];seen_limits=set()
    for row in materials.get('limitations', []):
        key=(str(row.get('kind')),str(row.get('name')),str(row.get('pairs')),str(row.get('claim')),str(row.get('reason')),str(row.get('change_if')),str(row.get('url')))
        if key in seen_limits:continue
        seen_limits.add(key);limits.append(row)
    def plain(value):
        if isinstance(value,(list,tuple)):return '；'.join(map(str,value))
        text=str(value)
        if text.startswith('[') and text.endswith(']'):
            try:
                items=json.loads(text)
                if isinstance(items,list):return '；'.join(map(str,items))
            except ValueError:pass
        return text
    shared=materials.get('shared_conditions', [])
    typed=[r for r in limits if r.get('kind')]
    limits=[r for r in limits if not r.get('kind')]
    if typed or shared:
        body += '<h4>反证与限制</h4>'
        if shared:
            body += '<div class="audit-item"><p><b>所有候选共同的前提</b>（任何一条不成立，下列判断都要重看）：</p><ul class="audit-list">' + ''.join('<li>' + val(c) + '</li>' for c in shared) + '</ul></div>'
        for r in typed:
            if r['kind'] == 'candidate':
                body += (f'<div class="audit-item"><p><b>{val(r.get("name"))}</b></p>'
                         + (f'<p>不利的一面：{val(r.get("claim"))}</p>' if r.get('claim') else '')
                         + (f'<p>支持的一面：{val(r.get("reason"))}</p>' if r.get('reason') else '')
                         + (f'<p>出现以下情况要改判：{val(r.get("change_if"))}</p>' if r.get('change_if') else ''))
            else:
                pairs=[(k, v) for k, v in r.get('pairs', []) if v]
                head, rest = (pairs[0], pairs[1:]) if pairs else (('', ''), [])
                body += (f'<div class="audit-item"><p><b>第 {secs(r.get("section"))} 节 · {val(head[0]) + "：" if head[0] else ""}{val(head[1])}</b></p>'
                         + ''.join(f'<p>{val(k)}：{val(v)}</p>' for k, v in rest))
            if r.get('url'):
                body += ''.join(f'<p class="audit-url">{val(u)}</p>' for u in str(r['url']).split('；') if u)
            body += '</div>'
    if limits:
        # 适用条件和改判条件相同的限制合成一条：条件只印一次，下面列出各项。
        grouped={}
        for row in limits:
            grouped.setdefault((str(row.get('reason') or ''),plain(row.get('change_if') or '')),[]).append(row)
        if not (typed or shared):body += '<h4>反证与限制</h4>'
        for (reason,change),rows in grouped.items():
            if len(rows)==1:
                body += '<div class="audit-item"><p><b>限制：</b>' + val(rows[0].get('claim')) + '</p>'
            else:
                body += '<div class="audit-item"><p><b>限制（以下 ' + str(len(rows)) + ' 项条件相同）：</b></p><ul class="audit-list">' + ''.join('<li>' + val(r.get('claim')) + '</li>' for r in rows) + '</ul>'
            if reason:body += '<p>适用条件：' + E(reason) + '</p>'
            if change:body += '<p>出现以下情况要改判：' + E(change) + '</p>'
            for url in dict.fromkeys(r.get('url') for r in rows if r.get('url')):body += '<p class="audit-url">' + val(url) + '</p>'
            body += '</div>'
    body += '<h4>未取到的信息和原因</h4>'
    for row in materials.get('gaps', []):
        body += '<div class="audit-item"><p><b>' + val(row.get('label')) + '</b>：' + val(row.get('reason')) + '</p>' + (f'<p class="audit-url">{val(row["url"])}</p>' if row.get('url') else '') + '</div>'
    if not materials.get('gaps'):
        body += '<p>未登记额外取文缺口；已知限制见上节。</p>'
    body += '</div>'
    leaks = appendix_leaks(body)
    if leaks:
        raise ValueError('核对附录出现未翻译的字段名或路径：' + '、'.join(leaks[:5]))
    return body


PROCESS_WORDS = [('HTTP为动态壳，内置浏览器核正文', '网页为动态页面，用浏览器打开核对正文'), ('在内存核原', '核对原'), ('curl', '直接下载')]


def process_words(text):
    """取文工具名等内部过程词换成读者能懂的说法。"""
    text = str(text)
    for a, b in PROCESS_WORDS:
        text = text.replace(a, b)
    return text


def appendix_leaks(fragment):
    """核对附录是给人和 AI 逐条核对的：不许出现 /education/xxx 这类字段路径、meta 或 fail_count 这类英文键名。网址不算。"""
    text = re.sub(r'<[^>]+>', ' ', fragment)
    text = re.sub(r'(?:https?://|www\.)\S+|\b[\w.-]+\.(?:cn|com|hk|mo|org|edu|net|gov)(?:/\S*)?', ' ', html.unescape(text))
    text = re.sub(r'\b[\w-]+\.(?:json|csv|pdf|txt)\b', ' ', text)  # 附件文件名可以出现
    found = re.findall(r'(?<![\w.])/[A-Za-z_][\w]*(?:/[\w~]+)+', text)
    found += re.findall(r'\bmeta\b|\bcurl\b|\b[a-z]+(?:_[a-z0-9]+)+\b|\b[a-z]+(?:-[a-z0-9]+)+\b', text)
    return list(dict.fromkeys(found))


def keep_numeric_runs(fragment):
    """Chinese prose may wrap a year mid-number; preserve each visible run.

    Work on text nodes only. URLs in the source list and SVG markup retain their
    own wrapping/coordinate rules; no attributes or data values are rewritten.
    """
    out=[];svg=0;sources=False
    for chunk in re.split(r'(<[^>]+>)',fragment):
        if chunk.startswith('<'):
            if re.match(r'<svg(?:\s|>)',chunk):svg+=1
            if chunk.startswith('</svg'):svg-=1
            if chunk.startswith('<section') and re.search(r'data-section=["\']12["\']',chunk):sources=True
            if chunk.startswith('</section'):sources=False
            out.append(chunk);continue
        if svg or sources:out.append(chunk);continue
        text=html.unescape(chunk);pos=0
        for match in re.finditer(r'\d[\d,]*(?:\.\d+)?(?:%|％)?',text):
            out.append(E(text[pos:match.start()]))
            out.append('<span class="number-run">'+E(match[0])+'</span>');pos=match.end()
        out.append(E(text[pos:]))
    return ''.join(out)


def document_html(title, cover, body, person, edition, report_id, simulated=True):
    runhead = f'{simulated_name(person, simulated)} · {edition} · {report_id}'
    safe = lambda s: str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
    css = CSS.replace('__RUNHEAD__', safe(runhead)).replace('__TOPLEFT__', safe('知衢 · ' + edition + '决策报告'))
    cover,body=keep_numeric_runs(cover),keep_numeric_runs(body)
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
        date = str(date).replace('方式：curl', '方式：直接下载官网原文')  # 不印工具名
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


# ---- 图表共用几何（科研插图标准）-----------------------------------------------------------
# 所有 SVG 图宽 640 个单位，印到 A4 版心（174mm）时 1 单位约 0.77pt；最小字号 9.5 单位≈7.3pt。
# 同一套左右栏：标签栏 0—206，绘图区 PLOT_L—PLOT_R，数值栏右对齐到 VALUE_R。条形、区间、策略图共用，
# 换图时左边距和数值列对齐。数值轴一律画刻度和单位；条形从 0 起；缺数据写“未取到”、画虚线框，不画成 0。
CHART_W = 640
CHART_SANS = "PingFang SC, Source Han Sans SC, Noto Sans SC, sans-serif"
LABEL_W, PLOT_L, PLOT_R, VALUE_R = 206, 214, 540, 638
FS, FS_SMALL = 10.5, 9.5
# 640 单位铺满 A4 正文 174mm：11.2 单位约 8.63pt，高于正文小号 8.5pt。
DIAGRAM_FONT, DIAGRAM_SMALL = 12, 11.2
INK, SOFT, MUTED, RULE, GRID = '#222A26', '#454E48', '#6E776E', '#B5AD98', '#D3CCB8'


def _svg_open(height, cls='chart'):
    return (f'<svg class="{cls}" viewBox="0 0 {CHART_W} {height:.0f}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="{CHART_SANS}" font-size="{FS}">')


def _fit_text(text, width, size=FS):
    """按估算宽度截断，截断处加省略号；不在半个括号处硬切。"""
    text = str(text)
    if _text_width(text, size) <= width:
        return text
    while text and _text_width(text + '…', size) > width:
        text = text[:-1]
    return text.rstrip('(（[【·- ') + '…'


def _num(v):
    """刻度数字：整数加千分位，小数去掉多余的 0。"""
    v = float(v)
    if abs(v - round(v)) < 1e-9:
        return f'{int(round(v)):,}'
    return f'{v:,.6g}'


def nice_ticks(lo, hi, target=5):
    """覆盖 [lo, hi] 的整齐刻度：步长取 1、2、2.5、5 乘 10 的幂。返回刻度列表（首尾包住数据）。"""
    lo, hi = float(lo), float(hi)
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw - 1e-12)
    first = math.floor(lo / step + 1e-9) * step
    last = math.ceil(hi / step - 1e-9) * step
    n = int(round((last - first) / step))
    return [round(first + i * step, 10) for i in range(n + 1)]


def _x_axis(ticks, scale, y, fmt=_num, unit='', grid_top=None):
    """横向数值轴：轴线、刻度、刻度值；单位写在最后一个刻度值后面。grid_top 给出时画浅色竖向网格。"""
    out = []
    for i, t in enumerate(ticks):
        x = scale(t)
        if grid_top is not None:
            out.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{grid_top:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width=".6"/>')
        out.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{y:.1f}" y2="{y + 3:.1f}" stroke="{MUTED}" stroke-width=".8"/>')
        label = fmt(t) + (' ' + unit if unit and i == len(ticks) - 1 else '')
        anchor = 'start' if i == 0 and x - _text_width(label, FS_SMALL) / 2 < 0 else 'middle'
        out.append(f'<text x="{x:.2f}" y="{y + 13:.1f}" font-size="{FS_SMALL}" fill="{MUTED}" text-anchor="{anchor}">{E(label)}</text>')
    out.insert(0, f'<line x1="{scale(ticks[0]):.2f}" x2="{scale(ticks[-1]):.2f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{MUTED}" stroke-width=".8"/>')
    return ''.join(out)


def _legend(items, y, x=0, font_size=FS_SMALL):
    """图例：[(图形SVG片段生成函数(x, y), 文字)]，从左往右排，返回 (svg, 结束x)。"""
    out = []
    for draw, text in items:
        # 图标中心离起点 8 个单位：最宽的图标（菱形半宽 7、描边 1）也不出 viewBox 左缘（2026-10-20 流程图图例被裁）
        out.append(draw(x + 8, y - 3.5))
        out.append(f'<text x="{x + 17:.1f}" y="{y:.1f}" font-size="{font_size}" fill="{MUTED}">{E(text)}</text>')
        x += 17 + _text_width(text, font_size) + 14
    return ''.join(out), x


def _swatch(color):
    return lambda x, y: f'<rect x="{x - 5:.1f}" y="{y - 4.5:.1f}" width="10" height="9" fill="{color}"/>'


def bar_chart(rows, unit='', maximum=None, palette=None, legend=None, tick_fmt=None):
    """水平条形图。rows=[label,value,tag?,display?]，不改数值；负值不收，缺失写“未取到”不画成 0。

    条从 0 起，长度严格与数值成比例；轴的上界取 maximum（给了时），否则取覆盖最大值的整齐刻度。
    轴下有刻度值，单位写在最后一个刻度后。legend={tag: 说明} 时在图顶画色块图例（多种颜色时应给，或在图注写明）。
    """
    rows = [list(r) for r in rows]
    vals = [float(r[1]) for r in rows if r[1] is not None]
    if any(v < 0 or not math.isfinite(v) for v in vals):
        raise ValueError('条形图只接受有限非负数；负结余应在情景表中明确披露')
    if maximum is not None and any(v > float(maximum) for v in vals):
        raise ValueError('条形图数值超出上界')
    pal = palette or PALETTE
    ticks = nice_ticks(0, float(maximum) if maximum else (max(vals, default=0) or 1))
    if maximum:
        ticks = [t for t in ticks if t <= float(maximum) + 1e-9]
        if abs(ticks[-1] - float(maximum)) > 1e-9:
            ticks.append(float(maximum))
    vmax = ticks[-1]
    scale = lambda v: PLOT_L + (PLOT_R - PLOT_L) * float(v) / vmax
    row_h, bar_h = 18, 12
    top = 18 if legend else 2
    axis_y = top + len(rows) * row_h + 3
    out = [_svg_open(axis_y + (18 if vals else 0))]
    if legend:
        present = {(r[2] if len(r) > 2 and r[2] else '主') for r in rows}
        used = [t for t in legend if t in present]
        out.append(_legend([(_swatch(pal.get(t, PALETTE['主'])), legend[t]) for t in used], 10, PLOT_L)[0])
    if vals:  # 一个数都没取到时不画数轴：没有可比的量，画一条 0—1 的轴只会误导
        out.append(_x_axis(ticks, scale, axis_y, tick_fmt or _num, unit, grid_top=top))
    for i, row in enumerate(rows):
        label, value = row[:2]
        tag = row[2] if len(row) > 2 and row[2] else '主'
        y = top + i * row_h + 3
        out.append(f'<text x="0" y="{y + 10:.1f}" fill="{SOFT}">{E(_fit_text(label, LABEL_W))}</text>')
        if value is None:
            out.append(f'<rect x="{PLOT_L}" y="{y:.1f}" width="{PLOT_R - PLOT_L}" height="{bar_h}" fill="none" stroke="{RULE}" stroke-width=".8" stroke-dasharray="3 2"/>')
            display = '未取到'
        else:
            bw = scale(value) - PLOT_L
            out.append(f'<rect x="{PLOT_L}" y="{y:.1f}" width="{bw:.2f}" height="{bar_h}" fill="{pal.get(tag, PALETTE["主"])}"/>')
            display = row[3] if len(row) > 3 and row[3] else _num(value) + (' ' + unit if unit else '')
        out.append(f'<text x="{VALUE_R}" y="{y + 10:.1f}" text-anchor="end" fill="{INK}">{E(str(display))}</text>')
    if vals:
        out.append(f'<line x1="{PLOT_L}" x2="{PLOT_L}" y1="{top:.1f}" y2="{axis_y:.1f}" stroke="{MUTED}" stroke-width=".8"/>')
    out.append('</svg>')
    return ''.join(out)


def _interval_marks():
    return {
        'iqr': (lambda x, y: f'<line x1="{x - 6:.1f}" x2="{x + 6:.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="#34685D" stroke-width="7"/>', '中间一半（25%—75% 分位）'),
        'range': (lambda x, y: f'<line x1="{x - 6:.1f}" x2="{x + 6:.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="#34685D" stroke-width="1.2"/>', '最低—最高'),
        'median': (lambda x, y: f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y - 6:.1f}" y2="{y + 6:.1f}" stroke="#21473E" stroke-width="2"/>', '中位数'),
        'line': (lambda x, y: f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y - 7:.1f}" y2="{y + 7:.1f}" stroke="{INK}" stroke-width="1" stroke-dasharray="2 1.5"/>', '复试线'),
        'point': (lambda x, y: f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" fill="#A8772B"/>', '对照分'),
    }


def interval_chart(rows, unit='分'):
    """分数分布图。rows=[label, Q1, Q3, 对照点, 最低?, 最高?, 中位数?, 复试线?]；后四项可省，缺资料明确显示。

    粗石绿段＝中间一半（Q1—Q3），细线＝最低到最高，黛绿短竖线＝中位数，虚线短竖线＝复试线，
    琥珀点＝对照分（本人模考或明示的情景分）。每行保持原统计口径，不跨口径合并。
    下方是带刻度的分数轴（不从 0 起：这是位置图，不比长度），图例只列出图里实际出现的标记。
    各行对照分相同时画一条贯穿各行的琥珀虚线并只标一次数值。
    """
    rows = [list(r) + [None] * (8 - len(r)) for r in rows]
    vals = [float(v) for r in rows for v in r[1:8] if v is not None]
    # 同一张图里数字写法一致：千分位，小数位取全图所需的最多位（最多 1 位）
    places = 1 if any(abs(v - round(v)) > 1e-9 for v in vals) else 0
    num = lambda v: f'{float(v):,.{places}f}'
    for label, lo, hi, point, vmin, vmax, med, line in rows:
        if vmin is not None and vmax is not None and vmin > vmax: raise ValueError('最低分不可大于最高分')
        if lo is not None and hi is not None and lo > hi: raise ValueError('区间下界不可大于上界')
    points = {r[3] for r in rows if r[3] is not None}
    common = len(rows) > 1 and len(points) == 1 and all(r[3] is not None for r in rows)
    row_h = 30 if any(r[4] is not None and r[5] is not None for r in rows) or (points and not common) else 24
    top = 16 if common else 4
    axis_y = top + len(rows) * row_h + 2
    if vals:
        ticks = nice_ticks(min(vals) - 1, max(vals) + 1, 6)
        scale = lambda v: PLOT_L + (float(v) - ticks[0]) / (ticks[-1] - ticks[0]) * (PLOT_R - PLOT_L)
    used = []
    body = []
    marks = _interval_marks()
    for i, (label, lo, hi, point, vmin, vmax, med, line) in enumerate(rows):
        y = top + i * row_h + 10
        body.append(f'<text x="0" y="{y + 3.5:.1f}" fill="{SOFT}">{E(_fit_text(label, LABEL_W))}</text>')
        detail = []
        if vmin is not None and vmax is not None:
            body.append(f'<line x1="{scale(vmin):.2f}" x2="{scale(vmax):.2f}" y1="{y}" y2="{y}" stroke="#34685D" stroke-width="1.2"/>')
            used.append('range'); detail.append(f'全距 {num(vmin)}—{num(vmax)}')
        if lo is not None and hi is not None:
            body.append(f'<line x1="{scale(lo):.2f}" x2="{scale(hi):.2f}" y1="{y}" y2="{y}" stroke="#34685D" stroke-width="7"/>')
            used.append('iqr')
            body.append(f'<text x="{VALUE_R}" y="{y + 3.5:.1f}" text-anchor="end" fill="{INK}">{num(lo)}—{num(hi)} {E(unit)}</text>')
        else:
            body.append(f'<rect x="{PLOT_L}" y="{y - 6}" width="{PLOT_R - PLOT_L}" height="12" fill="none" stroke="{RULE}" stroke-width=".8" stroke-dasharray="3 2"/>'
                        f'<text x="{PLOT_L + 6}" y="{y + 3.5:.1f}" font-size="{FS_SMALL}" fill="{MUTED}">区间未取到</text>'
                        f'<text x="{VALUE_R}" y="{y + 3.5:.1f}" text-anchor="end" fill="{MUTED}">未取到</text>')
        if med is not None:
            body.append(marks['median'][0](scale(med), y)); used.append('median')
        if line is not None:
            body.append(marks['line'][0](scale(line), y)); used.append('line'); detail.append(f'复试线 {num(line)}')
        if point is not None:
            body.append(marks['point'][0](scale(point), y)); used.append('point')
            if not common: detail.append(f'对照 {num(point)}')
        if detail:
            body.append(f'<text x="{VALUE_R}" y="{y + 15:.1f}" text-anchor="end" font-size="{FS_SMALL}" fill="{MUTED}">{E("；".join(detail))}</text>')
    out = []
    height = axis_y + (20 if vals else 0)
    used = [k for k in ('iqr', 'range', 'median', 'line', 'point') if k in used]
    if used:
        height += 16
    out.append(_svg_open(height))
    if vals:
        out.append(_x_axis(ticks, scale, axis_y, _num, unit, grid_top=top))
    if common:
        pv = next(iter(points)); xp = scale(pv)
        out.append(f'<line x1="{xp:.2f}" x2="{xp:.2f}" y1="{top - 2}" y2="{axis_y}" stroke="#A8772B" stroke-width=".9" stroke-dasharray="3 2"/>'
                   f'<text x="{xp:.2f}" y="{top - 5}" text-anchor="middle" font-size="{FS_SMALL}" fill="#A8772B">对照 {num(pv)} {E(unit)}</text>')
    out.extend(body)
    if used:
        out.append(_legend([marks[k] for k in used], height - 5, 0)[0])
    out.append('</svg>')
    return ''.join(out)


def _wrap(text, width, size=FS):
    """按估算宽度折行（中文逐字、英文数字整词），各行长度大致相等，不留一两个字的尾行。"""
    total = _text_width(str(text), size)
    if total > width:
        width = min(width, total / math.ceil(total / width) + size)
    lines, cur = [], ''
    for tok in re.findall(r'[A-Za-z0-9.,%/+\-]+|\s+|.', str(text)):
        if cur and _text_width(cur + tok, size) > width and tok not in '，。、；：？！）”’':  # 标点不放行首
            lines.append(cur.rstrip()); cur = tok.lstrip()
        else:
            cur += tok
    if cur.strip():
        lines.append(cur.rstrip())
    # 标点不单独起一行（“？”“。”挂到上一行末尾）
    while len(lines) > 1 and re.fullmatch(r'[，。、；：？！）”’,.;:?!)]+', lines[-1]):
        tail = lines.pop()
        lines[-1] += tail
    return lines or ['']


FLOW_SHAPES = {'步骤': 'step', '判断': 'decision', '结果': 'main', '备选': 'alt'}


def flow(rows):
    """决策流程图。rows=[节点ID, 形状, 文字, 去向...]；形状：步骤（方框）、判断（菱形）、结果（主线去向，深色）、备选（浅色）。
    去向写“标签>目标ID”或“>目标ID”。主线一直向下；判断的第一个去向向下、第二个向右（三个去向时左、下、右）；
    向两侧去、且不再往下走的去向和菱形放在同一高度，用横向箭头连。连线不穿过其他方框，放不下就报错。
    只画流程和条件，不打分；判断条件应能由本人核实。
    """
    nodes, order = {}, []
    for row in rows:
        nid, shape, text, *edges = [str(c).strip() for c in row]
        if shape not in FLOW_SHAPES: raise ValueError('流程图形状只能是：' + '、'.join(FLOW_SHAPES))
        if nid in nodes: raise ValueError('流程图节点重复：' + nid)
        out = []
        for e in edges:
            if not e: continue
            if '>' not in e: raise ValueError('流程图去向写成“标签>目标ID”：' + e)
            label, _, target = e.rpartition('>')
            out.append((label.strip(), target.strip()))
        nodes[nid] = dict(id=nid, kind=FLOW_SHAPES[shape], text=text, edges=out, parents=[])
        order.append(nid)
    for n in nodes.values():
        for _, t in n['edges']:
            if t not in nodes: raise ValueError('流程图去向不存在：' + t)
            nodes[t]['parents'].append(n['id'])
    for n in nodes.values():  # 尺寸：方框文字最宽 160；菱形里文字最宽 120，菱形宽高取文字框的两倍
        if n['kind'] == 'decision':
            n['lines'] = _wrap(n['text'], 120, DIAGRAM_FONT)
            tw = max(_text_width(l, DIAGRAM_FONT) for l in n['lines']); th = 16 * len(n['lines'])
            n['w'], n['h'] = 2 * tw + 16, 2 * th + 10
        else:
            n['lines'] = _wrap(n['text'], 160, DIAGRAM_FONT)
            n['w'] = max(_text_width(l, DIAGRAM_FONT) for l in n['lines']) + 22; n['h'] = 16 * len(n['lines']) + 14
    col, side = {}, set()
    for nid in order:
        n = nodes[nid]; col.setdefault(nid, 0)
        kids = [t for _, t in n['edges']]
        offs = ([-1, 0, 1] if len(kids) == 3 else list(range(len(kids)))) if n['kind'] == 'decision' else list(range(len(kids)))
        for t, o in zip(kids, offs):
            col.setdefault(t, col[nid] + o)
            if n['kind'] == 'decision' and o != 0 and not nodes[t]['edges'] and len(nodes[t]['parents']) == 1:
                side.add(t)  # 侧向的终点：和菱形同一高度
    layer = {}
    def depth(nid, seen=()):
        if nid in seen: raise ValueError('流程图不能有回路')
        if nid not in layer:
            ps = nodes[nid]['parents']
            layer[nid] = depth(ps[0], seen + (nid,)) if nid in side else max([depth(q, seen + (nid,)) + 1 for q in ps] or [0])
        return layer[nid]
    for nid in order: depth(nid)
    cols = sorted(set(col.values()))
    widths = {c: max(n['w'] for n in nodes.values() if col[n['id']] == c) for c in cols}
    total = sum(widths.values()) + 28 * (len(cols) - 1)
    if total > CHART_W:
        # 字号不能为适应分支而缩小；先把完整文字换成较短的行并增加框高。
        for n in nodes.values():
            limit=90 if n['kind']=='decision' else 140
            n['lines']=_wrap(n['text'],limit,DIAGRAM_FONT)
            tw=max(_text_width(line,DIAGRAM_FONT) for line in n['lines'])
            th=16*len(n['lines'])
            n['w'],n['h']=(2*tw+16,2*th+10) if n['kind']=='decision' else (tw+22,th+14)
        widths={c:max(n['w'] for n in nodes.values() if col[n['id']]==c) for c in cols}
        total=sum(widths.values())+28*(len(cols)-1)
    if total > CHART_W:
        raise ValueError('流程图分支太多或文字太长，放不下；请拆图或缩短文字')
    x = (CHART_W - total) / 2; cx = {}
    for c in cols:
        cx[c] = x + widths[c] / 2; x += widths[c] + 28
    layers = {}
    for nid in order:
        nodes[nid]['cx'] = cx[col[nid]]
        layers.setdefault(layer[nid], []).append(nodes[nid])
    gap_y, y = 32, 4
    for k in sorted(layers):
        row = layers[k]
        if len({col[n['id']] for n in row}) < len(row):
            raise ValueError('流程图同一层有两个节点落在同一列；请调整去向顺序')
        hmax = max(n['h'] for n in row)
        for n in row: n['cy'] = y + hmax / 2
        y += hmax + gap_y
    height = y - gap_y + 26
    boxes = [(n['cx'] - n['w'] / 2, n['cy'] - n['h'] / 2, n['cx'] + n['w'] / 2, n['cy'] + n['h'] / 2, n['id']) for n in nodes.values()]
    def clear(x1, y1, x2, y2, skip):
        lo_x, hi_x, lo_y, hi_y = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
        for bx1, by1, bx2, by2, nid in boxes:
            if nid in skip: continue
            if lo_x < bx2 + 2 and hi_x > bx1 - 2 and lo_y < by2 + 2 and hi_y > by1 - 2:
                raise ValueError('流程图连线穿过其他方框；请调整节点顺序或拆图')
    out, labels, used = [], [], set()
    for n in (nodes[i] for i in order):
        exits = set()
        for label, t in n['edges']:
            c = nodes[t]; top = c['cy'] - c['h'] / 2; skip = {n['id'], t}
            dx = c['cx'] - n['cx']
            if n['kind'] == 'decision' and abs(dx) > 1:
                sd = -1 if dx < 0 else 1
                if sd in exits: raise ValueError('判断的同一侧只能引出一条分支')
                exits.add(sd)
                vx = n['cx'] + sd * n['w'] / 2
                side_x = c['cx'] - sd * c['w'] / 2
                top_taken = any(q != n['id'] and abs(nodes[q]['cx'] - c['cx']) <= 1 for q in c['parents'])
                if t in side:
                    pts = [(vx, n['cy']), (side_x, n['cy'])]
                elif top_taken and c['cy'] > n['cy'] + 1 and sd * (side_x - vx) >= 16:
                    # 目标的上方入口已被正上方的父节点占用：从朝向本节点的侧边进入，各自带箭头，不在线段中途汇合。
                    ex = side_x - sd * 10
                    pts = [(vx, n['cy']), (ex, n['cy']), (ex, c['cy']), (side_x, c['cy'])]
                elif sd * (c['cx'] - vx) >= 6:
                    pts = [(vx, n['cy']), (c['cx'], n['cy']), (c['cx'], top)]
                else:
                    ox = vx + sd * 10; mid = n['cy'] + n['h'] / 2 + gap_y / 2
                    pts = [(vx, n['cy']), (ox, n['cy']), (ox, mid), (c['cx'], mid), (c['cx'], top)]
                lab = (vx + sd * 5, n['cy'] - 5, 'end' if sd < 0 else 'start')
            else:
                if n['kind'] == 'decision':
                    if 0 in exits: raise ValueError('判断的下方只能引出一条分支')
                    exits.add(0)
                bottom = n['cy'] + n['h'] / 2
                if abs(dx) <= 1:
                    pts = [(c['cx'], bottom), (c['cx'], top)]
                else:
                    mid = bottom + gap_y / 2
                    pts = [(n['cx'], bottom), (n['cx'], mid), (c['cx'], mid), (c['cx'], top)]
                lab = (pts[0][0] + 5, bottom + 12, 'start')
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]): clear(x1, y1, x2, y2, skip)
            (ax, ay), (bx, by) = pts[-2], pts[-1]
            ux, uy = (bx > ax) - (bx < ax), (by > ay) - (by < ay)   # 最后一段的方向：箭头沿它画
            tip = (bx, by); base = (bx - ux * 6, by - uy * 6)
            d = 'M' + ' L'.join(f'{px:.1f} {py:.1f}' for px, py in pts[:-1]) + f' L{base[0]:.1f} {base[1]:.1f}'
            wing = ((-uy * 3.5, ux * 3.5), (uy * 3.5, -ux * 3.5))
            out.append(f'<path d="{d}" fill="none" stroke="{MUTED}" stroke-width="1"/>'
                       f'<path d="M{base[0] + wing[0][0]:.1f} {base[1] + wing[0][1]:.1f}L{base[0] + wing[1][0]:.1f} {base[1] + wing[1][1]:.1f}L{tip[0]:.1f} {tip[1]:.1f}Z" fill="{MUTED}"/>')
            if label:
                labels.append(f'<text x="{lab[0]:.1f}" y="{lab[1]:.1f}" text-anchor="{lab[2]}" font-size="{DIAGRAM_SMALL}" font-weight="600" fill="{SOFT}">{E(label)}</text>')
    style = {'step': ('#FFFDF8', '#21473E', INK), 'decision': ('#FFFDF8', '#A8772B', INK),
             'main': ('#21473E', '#21473E', '#FFFFFF'), 'alt': ('#E3DDCB', '#B5AD98', INK)}
    for n in (nodes[i] for i in order):
        fill, stroke, ink = style[n['kind']]; used.add(n['kind'])
        x0, y0 = n['cx'] - n['w'] / 2, n['cy'] - n['h'] / 2
        if n['kind'] == 'decision':
            out.append(f'<path d="M{n["cx"]:.1f} {y0:.1f}L{x0 + n["w"]:.1f} {n["cy"]:.1f}L{n["cx"]:.1f} {y0 + n["h"]:.1f}L{x0:.1f} {n["cy"]:.1f}Z" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
        else:
            out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{n["w"]:.1f}" height="{n["h"]:.1f}" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        first = n['cy'] - 16 * (len(n['lines']) - 1) / 2 + 3.6
        for i, line in enumerate(n['lines']):
            out.append(f'<text x="{n["cx"]:.1f}" y="{first + 16 * i:.1f}" text-anchor="middle" font-size="{DIAGRAM_FONT}" fill="{ink}"'
                       + (' font-weight="600"' if n['kind'] in ('main', 'decision') else '') + f'>{E(line)}</text>')
    key = {'step': (lambda x, y: f'<rect x="{x - 6:.1f}" y="{y - 4.5:.1f}" width="12" height="9" rx="1.5" fill="#FFFDF8" stroke="#21473E"/>', '要做的事'),
           'decision': (lambda x, y: f'<path d="M{x:.1f} {y - 5.5:.1f}L{x + 7:.1f} {y:.1f}L{x:.1f} {y + 5.5:.1f}L{x - 7:.1f} {y:.1f}Z" fill="#FFFDF8" stroke="#A8772B"/>', '要核实的判断'),
           'main': (_swatch('#21473E'), '主线去向'), 'alt': (_swatch('#E3DDCB'), '备选去向')}
    legend = _legend([key[k] for k in ('step', 'decision', 'main', 'alt') if k in used], height - 6, 0, DIAGRAM_SMALL)[0]
    return _svg_open(height) + ''.join(out) + ''.join(labels) + legend + '</svg>'


STACK_COLORS = [('#21473E', '#FFFFFF'), ('#34685D', '#FFFFFF'), ('#CEC6B1', INK), ('#E3DDCB', INK)]


def stack(rows, unit='', percent=False):
    """构成条：rows=[标签, [(分项, 数值), ...]]。各行共用一条从 0 起的数轴（percent=True 时各行按 100% 画），
    分段宽度严格按数值；颜色按段的位置深浅交替，只为分开相邻段；段内写“名称 数值”，
    段太窄只写得下数值或都写不下时，在图下按行补全“左起第几段为 名称 数值”，保证每段都能对上分项名；右侧写合计。"""
    for _, segs in rows:
        for name, v in segs:
            if v is None or float(v) < 0: raise ValueError('构成条的分项须为非负数值；缺的分项不画进构成条')
    totals = [sum(float(v) for _, v in segs) for _, segs in rows]
    ticks = [0, .25, .5, .75, 1] if percent else nice_ticks(0, max(totals) or 1)
    scale = lambda v: PLOT_L + (PLOT_R - PLOT_L) * float(v) / ticks[-1]
    row_h, bar_h = 34, 18
    axis_y = len(rows) * row_h + 2
    out = [_x_axis(ticks, scale, axis_y, (lambda v: f'{v:.0%}') if percent else _num, '' if percent else unit, grid_top=0)]
    notes = []
    for i, ((label, segs), total) in enumerate(zip(rows, totals)):
        y = i * row_h + 4; x = 0.0; missing = []
        out.append(f'<text x="0" y="{y + 13:.1f}" fill="{SOFT}">{E(_fit_text(label, LABEL_W))}</text>')
        for j, (name, v) in enumerate(segs):
            share = float(v) / total if percent and total else float(v)
            x0 = scale(x); x1 = scale(x + share); w = x1 - x0
            fill, ink = STACK_COLORS[j % len(STACK_COLORS)]  # 按位置着色只为分开相邻段；分项名写在段内
            out.append(f'<rect x="{x0:.2f}" y="{y}" width="{w:.2f}" height="{bar_h}" fill="{fill}"/>')
            if x > 0: out.append(f'<line x1="{x0:.2f}" x2="{x0:.2f}" y1="{y}" y2="{y + bar_h}" stroke="#F2EEE3" stroke-width="1.2"/>')
            full = f'{name} {_num(v)}'
            text = next((t for t in (full, _num(v)) if _text_width(t, FS_SMALL) + 8 <= w), None)
            if text:
                out.append(f'<text x="{x0 + w / 2:.2f}" y="{y + 12.5:.1f}" text-anchor="middle" font-size="{FS_SMALL}" fill="{ink}">{E(text)}</text>')
            if text != full:  # 段内只写得下分数或什么都写不下：在图下按“行、左起第几段”补全分项名，每段都能对上
                missing.append((j, full))
            x += share
        if missing:
            notes.append(f'{label}：从左到右依次为 ' + '、'.join(t for _, t in missing) if len(missing) == len(segs)
                         else f'{label}：' + '、'.join(f'左起第{j + 1}段为 {t}' for j, t in missing))
        out.append(f'<text x="{VALUE_R}" y="{y + 13:.1f}" text-anchor="end" fill="{INK}">合计 {_num(total)}{(" " + E(unit)) if unit else ""}</text>')
    height = axis_y + 18
    if notes:
        lines, cur = [], '段内未写全的分项：'
        for k, note in enumerate(notes):
            piece = note + ('；' if k < len(notes) - 1 else '')
            if cur and _text_width(cur + piece, FS_SMALL) > VALUE_R:
                lines.append(cur); cur = ''
            cur += piece
        lines.append(cur)
        for line in lines:
            height += 13
            out.append(f'<text x="0" y="{height - 4:.1f}" font-size="{FS_SMALL}" fill="{MUTED}">{E(line)}</text>')
    return _svg_open(height) + ''.join(out) + '</svg>'


EVIDENCE_STYLE = {  # 与证据徽章同色：官方黛绿、多人一致石绿、单人说法浅色、推测空心、第三方整理琥珀框、未取到虚线
    '官方': ('#21473E', 'none', '#FFFFFF', ''), '多人一致': ('#34685D', 'none', '#FFFFFF', ''),
    '单人说法': ('#E3DDCB', 'none', INK, ''), '推测': ('none', '#B5AD98', MUTED, ''), '第三方整理': ('none', '#A8772B', '#A8772B', ''), '未取到': ('none', '#B5AD98', MUTED, '3 2')}


def evidence_grid(rows):
    """调研证据一览：rows=[学校, [(方面, 证据等级), ...]]。每格写证据等级，颜色同证据徽章，没调研的方面留空并写“未查”。
    只表示“这条信息有多可靠”，不是学校好坏的评分。"""
    aspects = list(dict.fromkeys(a for _, cells in rows for a, _ in cells))
    if not aspects: raise ValueError('证据一览没有任何方面')
    for _, cells in rows:
        for _, g in cells:
            if g not in EVIDENCE_STYLE: raise ValueError('未知证据等级：' + str(g))
    cw = (VALUE_R - PLOT_L) / len(aspects); row_h, head = 22, 16
    out = [f'<text x="{PLOT_L + cw * (i + .5):.1f}" y="11" text-anchor="middle" font-size="{FS_SMALL}" fill="{MUTED}">{E(_fit_text(a, cw - 4, FS_SMALL))}</text>' for i, a in enumerate(aspects)]
    for r, (school, cells) in enumerate(rows):
        y = head + r * row_h; got = dict(cells)
        out.append(f'<text x="0" y="{y + 14:.1f}" fill="{SOFT}">{E(_fit_text(school, LABEL_W))}</text>')
        for i, a in enumerate(aspects):
            x = PLOT_L + cw * i + 2; w = cw - 4
            g = got.get(a)
            if g is None:
                out.append(f'<text x="{x + w / 2:.1f}" y="{y + 14:.1f}" text-anchor="middle" font-size="{FS_SMALL}" fill="{MUTED}">未查</text>')
                continue
            fill, stroke, ink, dash = EVIDENCE_STYLE[g]
            out.append(f'<rect x="{x:.1f}" y="{y + 2}" width="{w:.1f}" height="{row_h - 5}" fill="{fill}"'
                       + (f' stroke="{stroke}" stroke-width=".8"' if stroke != 'none' else '') + (f' stroke-dasharray="{dash}"' if dash else '') + '/>'
                       f'<text x="{x + w / 2:.1f}" y="{y + 14:.1f}" text-anchor="middle" font-size="{FS_SMALL}" fill="{ink}">{E(g)}</text>')
    height = head + len(rows) * row_h + 4
    return _svg_open(height) + ''.join(out) + '</svg>'


FACT_STATES = {'已知': 'known', '待确认': 'pending', '未知': 'unknown'}


def facts(rows, inline=E):
    """现状一览：rows=[项目, 内容, 状态]，状态为已知、待确认或未知。已知实心、待确认琥珀边、未知虚线框写“未填”，
    一眼看出还缺什么。只列本人给出或明确缺失的信息，不估值。"""
    cells = []
    for row in rows:
        label, value, state = (list(row) + ['', '', ''])[:3]
        if state not in FACT_STATES: raise ValueError('现状一览的状态只能是：已知、待确认、未知')
        cls = FACT_STATES[state]
        shown = inline(str(value)) if str(value).strip() and cls != 'unknown' else ('未填' if cls == 'unknown' else '待确认')
        if cls == 'unknown' and str(value).strip(): shown = inline(str(value))  # 写了缺什么就直接写，虚线框已表示未知
        cells.append(f'<div class="fact {cls}"><b>{E(str(label))}</b><span>{shown}</span></div>')
    key = '　'.join(f'<i class="fk {k}"></i>{v}' for k, v in (('known', '已知'), ('pending', '待确认'), ('unknown', '未知或未填')))
    return f'<div class="facts">{"".join(cells)}</div><p class="matrix-key">{key}</p>'


def cost_chart(rows):
    """费用对比：rows=[项目, 数值或 None, 币种/单位, 显示?]。同一币种共用一条数轴；不同币种分开画、各自刻度，
    不按汇率折算；没取到的项画虚线空框并写“未取到”，不画成 0。"""
    groups = {}
    for row in rows:
        label, value, cur, *rest = list(row) + [None] * (3 - len(row))
        groups.setdefault(str(cur or '未注明单位'), []).append([label, value, '主', rest[0] if rest and rest[0] else None])
    panels = []
    for cur, items in groups.items():
        panels.append(f'<div class="panel-ttl">{E(cur)}</div>' + bar_chart(items, cur))
    if len(groups) > 1:
        panels.append(f'<p class="matrix-key">不同币种各用自己的刻度，没有按汇率折算；条长只在同一币种内可比。虚线框为未取到。</p>')
    return '<div class="cost">' + ''.join(panels) + '</div>'


TIMELINE_MONTH = re.compile(r'^\s*(\d{4})\s*[.\-/年]\s*(\d{1,2})\s*月?\s*$')


def _timeline_marker(x, y, checkpoint):
    if checkpoint:
        return f'<path d="M{x:.1f} {y-4.6:.1f}L{x+4.6:.1f} {y:.1f}L{x:.1f} {y+4.6:.1f}L{x-4.6:.1f} {y:.1f}Z" fill="#A8772B"/>'
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" fill="#34685D"/>'


def timeline(rows):
    """时间线。rows=[时间, 事项, 说明, 检查点?]。

    时间全是“年.月”时画等比例横轴：每个节点落在它的月份上，轴下是年份刻度和半年短刻度，
    标签在轴上方分层避让、用引线连到节点。只要有一个时间是“2027 春季”“毕业后 3 个月内”这类模糊说法，
    就改画纵向顺序图，并注明间距不代表时长，不把模糊时间画成精确位置。
    """
    sans = "PingFang SC, Source Han Sans SC, Noto Sans SC, sans-serif"
    items = []
    for row in rows:
        when, task, note, *rest = list(row) + [''] * (3 - len(row))
        cp = bool(rest and rest[0] not in ('', '普通', False))
        m = TIMELINE_MONTH.match(str(when))
        items.append(dict(when=str(when).strip(), task=str(task).strip(), note=str(note).strip(), cp=cp,
                          month=(int(m[1]) * 12 + int(m[2]) - 1) if m and 1 <= int(m[2]) <= 12 else None))
    legend_y_pad = 22
    same_month = False
    def legend(y, scaled):
        tail = ('横轴按月份等比例' + ('；同月事项在该月内按先后错开' if same_month else '')) if scaled else '按先后排列，间距不代表时长'
        return (f'{_timeline_marker(6, y-3.5, True)}<text x="16" y="{y}" fill="#6E776E">个人检查点</text>'
                f'{_timeline_marker(86, y-3.5, False)}<text x="96" y="{y}" fill="#6E776E">流程节点</text>'
                f'<text x="640" y="{y}" text-anchor="end" fill="#6E776E">{tail}</text>')
    if items and all(i['month'] is not None for i in items):
        lo = min(i['month'] for i in items) - 1; hi = max(i['month'] for i in items) + 1
        x = lambda m: 20 + (m + .5 - lo) / max(hi - lo + 1, 1) * 600
        # 标签都在轴上方分层，轴下只放年份刻度。用回溯找层数最少的摆法，约束：
        # 同层标签不重叠；较高层节点的引线不穿过较低层的标签。标签可在引线右侧或左侧展开。
        band = 600 / max(hi - lo + 1, 1)
        groups = {}
        for it in items:
            groups.setdefault(it['month'], []).append(it)
        for group in groups.values():
            # 同一个月的几项：都留在这个月的格子里，按输入先后左右错开，标记不互相盖住。
            gap = min(10.0, band * .9 / len(group))
            for j, it in enumerate(group):
                it['cx'] = x(it['month']) + (j - (len(group) - 1) / 2) * gap
            same_month = same_month or len(group) > 1
        for it in items:
            it['w'] = max(_text_width(f"{it['when']}  {it['task']}", DIAGRAM_FONT), _text_width(it['note'], DIAGRAM_SMALL)) + 4
            it['opts'] = sorted({min(max(a, 0), 640 - it['w']) for a in (it['cx'] - 3, it['cx'] + 3 - it['w'])},
                                key=lambda l, c=it['cx']: abs(l - (c - 3)))
        def ok(a, ka, la, b, kb, lb):
            if ka == kb: return la > lb + b['w'] + 10 or la + a['w'] + 10 < lb
            lo_it, lo_l, hi_it = (a, la, b) if ka < kb else (b, lb, a)
            return not (lo_l - 4 <= hi_it['cx'] <= lo_l + lo_it['w'] + 4)
        def solve(top):
            chosen = []
            def dfs(n):
                if n == len(items): return True
                for k in range(1, top + 1):
                    for l in items[n]['opts']:
                        if all(ok(items[n], k, l, items[m], km, lm) for m, (km, lm) in enumerate(chosen)):
                            chosen.append((k, l))
                            if dfs(n + 1): return True
                            chosen.pop()
                return False
            return chosen if dfs(0) else None
        for top in range(1, 7):
            plan = solve(top)
            if plan: break
        else:
            raise ValueError('时间线节点过密，标签放不下；请合并同月事项')
        for it, (k, l) in zip(items, plan): it.update(lv=('up', k), left=l)
        up = max([i['lv'][1] for i in items if i['lv'][0] == 'up'] or [0])
        down = max([i['lv'][1] for i in items if i['lv'][0] == 'down'] or [0])
        step = 40; axis = 8 + up * step + 6
        height = axis + 18 + down * step + legend_y_pad
        out = [f'<svg class="chart timeline-chart" viewBox="0 0 640 {height:.0f}" xmlns="http://www.w3.org/2000/svg" font-family="{sans}" font-size="{DIAGRAM_FONT}">',
               f'<line x1="14" x2="626" y1="{axis}" y2="{axis}" stroke="#B5AD98" stroke-width="1.2"/>']
        for m in range(lo, hi + 1):
            if m % 12 == 0:
                out.append(f'<line x1="{x(m)-.5*600/max(hi-lo+1,1):.1f}" x2="{x(m)-.5*600/max(hi-lo+1,1):.1f}" y1="{axis-5}" y2="{axis+5}" stroke="#6E776E" stroke-width="1"/>'
                           f'<text x="{x(m)-.5*600/max(hi-lo+1,1)+3:.1f}" y="{axis+14}" font-size="{DIAGRAM_SMALL}" fill="#6E776E">{m // 12} 年</text>')
            elif m % 12 != 6 and hi - lo <= 36:  # 月刻度：只是极短的点，帮助数月份
                out.append(f'<line x1="{x(m)-.5*600/max(hi-lo+1,1):.1f}" x2="{x(m)-.5*600/max(hi-lo+1,1):.1f}" y1="{axis}" y2="{axis+3}" stroke="#B5AD98" stroke-width=".7"/>')
            elif m % 12 == 6:
                out.append(f'<line x1="{x(m)-.5*600/max(hi-lo+1,1):.1f}" x2="{x(m)-.5*600/max(hi-lo+1,1):.1f}" y1="{axis-2.5}" y2="{axis+2.5}" stroke="#B5AD98" stroke-width="1"/>')
        for it in items:
            side, k = it['lv']
            ty = axis - 8 - (k - 1) * step - 13 if side == 'up' else axis + 18 + (k - 1) * step + 10
            ly = ty + (16 if it['note'] else 5)  # 引线停在标签下方，不碰文字
            out.append(f'<line x1="{it["cx"]:.1f}" x2="{it["cx"]:.1f}" y1="{axis}" y2="{ly:.1f}" stroke="#B5AD98" stroke-width=".8"/>')
            out.append(f'<text x="{it["left"]:.1f}" y="{ty:.1f}"><tspan font-weight="600" fill="#21473E">{E(it["when"])}</tspan>'
                       f'<tspan dx="5" font-weight="600" fill="#222A26">{E(it["task"])}</tspan></text>')
            if it['note']:
                out.append(f'<text x="{it["left"]:.1f}" y="{ty+15:.1f}" font-size="{DIAGRAM_SMALL}" fill="#6E776E">{E(it["note"])}</text>')
        for it in items:
            out.append(_timeline_marker(it['cx'], axis, it['cp']))
        out.append(legend(height - 6, True))
        return ''.join(out) + '</svg>'
    # 顺序图每项一行：事项和说明写在同一行（说明用小一号灰字），行距固定。
    # 两行写法会让 PDF 里出现一串短行，被版面自检当成“被挤窄的栏”（2026-10-20）。
    row_h = 28; height = 8 + len(items) * row_h + legend_y_pad
    out = [f'<svg class="chart timeline-chart" viewBox="0 0 640 {height}" xmlns="http://www.w3.org/2000/svg" font-family="{sans}" font-size="{DIAGRAM_FONT}">',
           f'<line x1="110" x2="110" y1="{8 + row_h/2}" y2="{8 + (len(items)-.5)*row_h}" stroke="#B5AD98" stroke-width="1.2"/>']
    for n, it in enumerate(items):
        y = 8 + (n + .5) * row_h
        out.append(f'<text x="96" y="{y+3.5:.1f}" text-anchor="end" font-weight="600" fill="#21473E">{E(_fit_text(it["when"], 94, DIAGRAM_FONT))}</text>')
        out.append(_timeline_marker(110, y, it['cp']))
        task = _fit_text(it['task'], 516, DIAGRAM_FONT)
        note = _fit_text(it['note'], 516 - _text_width(task, DIAGRAM_FONT) - 12, DIAGRAM_SMALL) if it['note'] else ''
        out.append(f'<text x="124" y="{y+3.5:.1f}"><tspan font-weight="600" fill="#222A26">{E(task)}</tspan>'
                   + (f'<tspan dx="12" font-size="{DIAGRAM_SMALL}" fill="#6E776E">{E(note)}</tspan>' if note else '') + '</text>')
    out.append(legend(height - 6, False))
    return ''.join(out) + '</svg>'


# 状态图标用 SVG 画，不用字符：字符随字体变形、对不齐（2026-10-20 被指出）。
# 有支持＝黛绿实心圆＋勾；待核＝琥珀圆环、左半填色（“只确认了一半”）；不满足＝红色实心圆＋叉。
SYMBOL = {
    "yes": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7.5" fill="#21473E"/>'
           '<path d="M4.6 8.3 7 10.6 11.6 5.6" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "pending": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.8" fill="#FFFDF8" stroke="#A8772B" stroke-width="1.4"/>'
               '<path d="M8 3.6a4.4 4.4 0 0 0 0 8.8z" fill="#A8772B"/></svg>',
    "no": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7.5" fill="#9B3B2E"/>'
          '<path d="M5.4 5.4 10.6 10.6M10.6 5.4 5.4 10.6" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
}


def comparison_matrix(columns, rows, inline=E):
    """比较矩阵：每格一个状态点加短说明。实心黛绿＝有支持，空心琥珀＝未核实或要补，红＝当前不满足。"""
    out = ['<table class="matrix"><thead><tr><th>选项</th>' + ''.join(f'<th>{E(c)}</th>' for c in columns) + '</tr></thead><tbody>']
    for row in rows:
        out.append('<tr><td class="opt">'+inline(str(row[0]))+'</td>')
        for value in row[1:]:
            val = str(value).strip()
            if val[:1] not in '✓✗△':
                raise ValueError(f'比较矩阵每格须以 ✓、△ 或 ✗ 开头标明状态，不默认当作待核：{val[:12]}')
            state = {'✓': 'yes', '✗': 'no', '△': 'pending'}[val[:1]]
            text = val[1:].strip()
            mark = {'yes': '有支持', 'no': '不满足', 'pending': '待核'}[state]
            out.append(f'<td class="{state}"><i class="dot {state}" title="{mark}">{SYMBOL[state]}</i>{inline(text)}</td>')
        out.append('</tr>')
    out.append('</tbody></table><p class="matrix-key">' + '　'.join(f'<i class="dot {k}">{SYMBOL[k]}</i>{v}' for k, v in (('yes', '有支持'), ('pending', '待核或要补'), ('no', '当前不满足'))) + '</p>')
    return ''.join(out)


def question_cards(rows, labels=None, inline=E):
    """追问卡：问题加引号作标题，其余各列写成带小标签的行；三类报告同一画法。"""
    labels = labels or []
    out = ['<ul class="asklist">']
    for row in rows:
        q, rest = row[0], row[1:]
        out.append(f'<li><b>“{inline(str(q).strip("“”"))}”</b>')
        for i, text in enumerate(rest):
            label = labels[i] if i < len(labels) else ''
            out.append(f'<div class="ask-line">' + (f'<em>{E(label)}</em>' if label else '') + f'{inline(str(text))}</div>')
        out.append('</li>')
    return ''.join(out) + '</ul>'


def scenario_cards(columns, rows, inline=E):
    """风险触发卡：“如果……”作标题，其余各列写成带小标签的行，两张一排。"""
    out = ['<div class="trigger-grid">']
    for row in rows:
        out.append(f'<div class="trigger"><div class="if"><em>如果</em>{inline(str(row[0]))}</div>'
                   + ''.join(f'<div class="ask-line"><em>{E(c)}</em>{inline(str(v))}</div>' for c, v in zip(columns[1:], row[1:]))
                   + '</div>')
    return ''.join(out) + '</div>'


def route_card(title, rows):
    keys = ['门槛', '时间窗口', '投入', '切换条件']
    if len(rows) != 4: raise ValueError('路线卡须恰好四栏')
    return f'<div class="route-card"><h3>{E(title)}</h3><dl>' + ''.join(f'<div><dt>{key}</dt><dd>{E(str(value))}</dd></div>' for key, value in zip(keys, rows))+'</dl></div>'


def kpi_cards(items, inline=E):
    cards = []
    for row in items[:4]:
        label, value, note = (list(row)+['','',''])[:3]
        # 同类同字号：含数字的短值（金额、日期、名次）一律大号数字；纯文字的值（阶段、方向名）一律 11pt。
        cjk = sum(ord(c)>0x2E80 for c in value)
        big = ' class="num"' if re.search(r'\d', value) and cjk <= 4 and len(value) <= 12 else ' style="font-size:11pt"'
        cards.append(f'<div><b>{inline(label)}</b><span{big}>{inline(value)}</span>'+(f'<em>{inline(note)}</em>' if note else '')+'</div>')
    return f'<div class="kpis" style="grid-template-columns:repeat({max(len(cards),1)},1fr)">'+''.join(cards)+'</div>'


def evidence_badge(level):
    names = {'官方': 'official', '多人一致': 'corroborated', '单人说法': 'single', '推测': 'inference', '第三方整理': 'compiled', '未取到': 'missing'}
    if level not in names: raise ValueError('未知证据等级')
    return f'<span class="evidence {names[level]}">{level}</span>'


def grade_of(text):
    """调研证据等级文字 → 徽章等级；以“未取到”开头的不冒充推测。"""
    text = str(text)
    if text.startswith('未取到'): return '未取到'
    return next((g for g in ('官方', '多人一致', '第三方整理', '单人说法', '推测') if g in text), '推测')


def school_card(r):
    """一所学校一张卡：每个方面一句结论（brief）加证据等级；没有 brief 的方面写“见第 12 节”。"""
    name = str(r['school']); note = ''
    m = re.match(r'(.+?)（(.+)）$', name)
    if m: name, note = m.groups()
    return info_card(name, [(a, r["brief"].get(a, "见第 12 节完整调研。"), evidence_badge(grade_of(c))) for a, b, c in r.get('items', [])], note)


def info_card(title, cells, note='', breakable=False):
    """信息卡：标题加两栏小格，每格一个小标签、一段话，可带右上角徽章。院校调研、高考路线图共用。
    breakable=True 时允许在格与格之间换页（格内不拆），用于路线图这类长卡片。"""
    body = ''.join(f'<div><div class="aspect"><span>{E(label)}</span>{badge}</div><p>{E(text)}</p></div>'
                   for label, text, *rest in cells for badge in [rest[0] if rest else ''])
    cls = 'school-card breakable' if breakable else 'school-card'
    return f'<div class="{cls}"><h3>{E(title)}' + (f'<small>{E(note)}</small>' if note else '') + f'</h3><div class="school-grid">{body}</div></div>'


def research_table(r, level='h3'):
    """一所学校的完整调研表（发现原文与证据等级）。"""
    return (f"<{level}>{E(r['school'])}</{level}><table class='rt'><colgroup><col style='width:14%'><col><col style='width:24%'></colgroup><thead><tr><th>方面</th><th>发现</th><th>证据等级</th></tr></thead><tbody>"
            + "".join(f"<tr><td>{E(a)}</td><td>{E(b)}</td><td class='small' style='word-break:break-all'>{evidence_badge(grade_of(c))} {E(c)}</td></tr>" for a, b, c in r.get("items", []))
            + "</tbody></table>"
            + ("<p class='small' style='word-break:break-all'>来源：" + "；".join(E(u) for u in r["sources"]) + "</p>" if r.get("sources") else ""))


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
    if x >= 1 - 0.5 * 10 ** -(d + 2):
        # 模型估计不写成“100%”：四舍五入到 100% 的写成“超过 99%”（一位小数时“超过 99.9%”），与正文一致。
        return "&gt; " + ("99%" if d == 0 else f"{100 - 10 ** -d:.{d}f}%")
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
                return "&gt; 95%"
            if x < 0.05:  # 取整到 5% 后两端会写成“约 0%”“约 100%”，与“有可能但很小”的含义不符
                return "&lt; 5%"
            if x > 0.95:
                return "&gt; 95%"
            return f"约 {round(x * 20) * 5:.0f}%"
        return None
    return f


STRIP_CAP = '从左到右按志愿顺序排列，色块宽度等于最终被该志愿录取的可能；数字是志愿序号，对应“志愿表”一节，深浅交替只为分开相邻两段。'
UTILITY_SCALE = "100 分 = 候选中你最想去的"


def strategy_caption(eu, pfall, top, safe, fall_fmt=None):
    """按实际数字写策略图的图注，不预设“只挑最想去的一定滑档”。

    比较按图上显示的精度做（满意度一位小数、滑档按正文格式）：显示出来一样的，不说谁高谁低。
    """
    fall_fmt = fall_fmt or (lambda p: f"{p:.1%}")
    shown = lambda r: (f"{r[0]:.1f}", fall_fmt(r[1]))
    mine = (eu or 0, pfall or 0)
    parts = ["条越长越好；滑档概率越低越好。"]
    if top:
        if abs(top[0] - mine[0]) < 0.05 and abs(top[1] - mine[1]) < 1e-9:
            parts.append("只挑最想去的，在本案和本报告的方案结果相同：你最想去的几个里已经有够稳的保底。")
        elif shown(top) == shown(mine):
            parts.append("只挑最想去的，与本报告方案在图上显示的精度内相同，差别小到不足以区分。")
        elif fall_fmt(top[1]) != fall_fmt(mine[1]) and top[1] > mine[1]:
            parts.append("只挑最想去的，滑档风险更高。")
        elif f"{top[0]:.1f}" != f"{mine[0]:.1f}" and top[0] < mine[0]:
            parts.append("只挑最想去的，滑档风险没有更高，但期望效用更低：前段太集中，落空后没有中间档接住。")
    if safe:
        if shown(safe) == shown(mine):
            parts.append("只挑最稳的，结果也在显示精度内相同。")
        elif f"{safe[0]:.1f}" != f"{mine[0]:.1f}" and safe[0] < mine[0]:
            parts.append("只挑最稳的，几乎不会滑档，但浪费了分数。")
    return "".join(parts)


def interval80(x):
    """80% 预测区间（位次），与优化器使用的 σ 一致。"""
    lo = x["expected_cut_rank"] * math.exp(-1.2816 * x["sigma"])
    hi = x["expected_cut_rank"] * math.exp(1.2816 * x["sigma"])
    return f"{round(lo):,}–{round(hi):,}"


def bars_h(items, fmt=lambda v: f"{v:.0%}", vmax=None):
    """水平条形图：items = [(label, value)]；与 bar_chart 同一画法（同字体、行高、底条和数值位置）。"""
    return bar_chart([[lab, v, '次', fmt(v)] for lab, v in items], maximum=vmax or max((v for _, v in items), default=1) or 1, tick_fmt=fmt)


def strategy_chart(rows, width=640, fmt=None):
    """策略对比：rows = [(name, eu, pfall, highlight)]。

    满意度轴固定 0—100（与“100 分 = 候选中你最想去的”同一量尺），条从 0 起、长度严格按数值；
    右侧两列分别写满意度和滑档概率，列头说明含义。fmt 把滑档概率写成与正文相同的精度。
    """
    if any(not 0 <= float(r[1]) <= 100 for r in rows):
        raise ValueError('平均满意度须在 0—100 之间')
    eu_r, fall_r, plot_r = 548, VALUE_R, 470
    bar_h, gap, head = 18, 9, 14
    scale = lambda v: PLOT_L + (plot_r - PLOT_L) * float(v) / 100
    axis_y = head + len(rows) * (bar_h + gap) - gap + 4
    out = [_svg_open(axis_y + 18),
           f'<text x="{eu_r}" y="9" text-anchor="end" font-size="{FS_SMALL}" fill="{MUTED}">平均满意度</text>'
           f'<text x="{fall_r}" y="9" text-anchor="end" font-size="{FS_SMALL}" fill="{MUTED}">滑档概率</text>']
    out.append(_x_axis([0, 20, 40, 60, 80, 100], scale, axis_y, _num, '分', grid_top=head))
    for i, (n, eu, pf, hl) in enumerate(rows):
        y = head + i * (bar_h + gap)
        col = "#21473E" if hl else "#CEC6B1"
        out.append(f'<text x="0" y="{y + bar_h - 5}" fill="{INK}" font-weight="{600 if hl else 400}">{E(_fit_text(n, LABEL_W))}</text>')
        out.append(f'<rect x="{PLOT_L}" y="{y}" width="{scale(eu) - PLOT_L:.2f}" height="{bar_h}" fill="{col}"/>')
        out.append(f'<text x="{eu_r}" y="{y + bar_h - 5}" text-anchor="end" fill="{INK}" font-weight="{600 if hl else 400}">{eu:.1f}</text>')
        fall = html.unescape(fmt(pf)) if fmt else f"{pf:.1%}"
        out.append(f'<text x="{fall_r}" y="{y + bar_h - 5}" text-anchor="end" fill="{"#9B3B2E" if pf > 0.01 else MUTED}">{E(fall)}</text>')
    out.append(f'<line x1="{PLOT_L}" x2="{PLOT_L}" y1="{head}" y2="{axis_y}" stroke="{MUTED}" stroke-width=".8"/>')
    out.append("</svg>")
    return "".join(out)


def _text_width(text, size=9):
    """估算 SVG 文字宽度：汉字按一个字号宽，其他字符按约 0.62 个字号。"""
    return sum(size if ord(c) > 0x2E80 else size * 0.62 for c in text)


def _ranges(nums):
    """[5,6,7,9] → '5—7、9'。"""
    out, run = [], []
    for n in nums:
        if run and n == run[-1] + 1:
            run.append(n)
        else:
            if run: out.append(run)
            run = [n]
    if run: out.append(run)
    return '、'.join(f'{r[0]}—{r[-1]}' if len(r) > 2 else '、'.join(map(str, r)) for r in out)


def outcome_strip(items, pfall, width=640, fmt=None, fall_text=None):
    """结局分布：一条 100% 堆积条，按志愿顺序排列，每段宽度严格等于最终录取概率（不设最小宽度）。

    ≥5% 的段黛绿、石绿交替（只为分开相邻两段），<5% 的段浅色，滑档红色。放不下序号的窄段在条下写明是哪几个志愿；
    能显示百分比时条下有 0—100% 刻度。fmt 返回空串表示本省评级不给百分比（只作定性示意，不画刻度）。
    """
    h = 24
    numeric = fmt is None or bool(fmt(0.5))
    fmt = fmt or (lambda p: f"{p:.0%}")
    inner = width - 2  # 左右各留 1 个单位：0% 与 100% 刻度线的描边不出画布
    out = []
    x = 1.0
    strong = ["#21473E", "#34685D"]
    k = 0
    seps, narrow, narrow_p = [], [], 0.0
    for i, (lab, p) in enumerate(items):
        w = inner * p
        if w <= 0:
            continue
        col = strong[k % 2] if p >= 0.05 else "#CEC6B1"
        k += p >= 0.05
        out.append(f'<rect x="{x:.2f}" y="0" width="{w:.2f}" height="{h}" fill="{col}"/>')
        if x > 1 and w >= 1.5:
            seps.append(x)
        pl = fmt(p)
        tail = f" · {pl}" if pl else ""
        fits = [t for t in (f"第 {i + 1} 志愿{tail}", f"{i + 1}{tail}") if _text_width(t, FS) + 12 <= w]
        if fits:
            out.append(f'<text x="{x + 6:.1f}" y="{h / 2 + 3.6:.1f}" fill="#fff" font-weight="600">{fits[0]}</text>')
        elif _text_width(str(i + 1), FS) + 4 <= w:
            ink = "#fff" if p >= 0.05 else SOFT
            out.append(f'<text x="{x + w / 2:.1f}" y="{h / 2 + 3.6:.1f}" fill="{ink}" text-anchor="middle">{i + 1}</text>')
        else:
            narrow.append(i + 1); narrow_p += p
        x += w
    if pfall > 0:
        out.append(f'<rect x="{x:.2f}" y="0" width="{inner * pfall:.2f}" height="{h}" fill="#9B3B2E"/>')
    out.extend(f'<line x1="{sx:.2f}" x2="{sx:.2f}" y1="0" y2="{h}" stroke="#F2EEE3" stroke-width="1"/>' for sx in seps)
    y = h
    if numeric:
        scale = lambda v: 1 + v * inner
        out.append(_x_axis([0, .25, .5, .75, 1], scale, h + 2, lambda v: f"{v:.0%}"))
        out[-1] = out[-1].replace('text-anchor="middle">100%', 'text-anchor="end">100%')
        y = h + 18
    notes = []
    if narrow:
        total = fmt(narrow_p) if numeric else ''
        if numeric and total in ('0%', ''):
            total = '不到 1%'
        notes.append(f'太窄未标号：第 {_ranges(narrow)} 志愿' + (f'，合计 {total}' if total else ''))
    right = ''
    if pfall > 0:
        right = '红色：滑档 ' + (fall_text if fall_text else (f"{pfall:.1%}" if pfall >= .001 else "不到 0.1%"))
        if inner * pfall < 1:
            right += '（宽度不足 1 个单位，按比例几乎看不见）'
    if notes or right:
        y += 13
        if notes:
            out.append(f'<text x="0" y="{y:.1f}" font-size="{FS_SMALL}" fill="{MUTED}">{E(notes[0])}</text>')
        if right:
            if notes and _text_width(notes[0], FS_SMALL) + _text_width(right, FS_SMALL) + 20 > width:
                y += 13  # 两条注记放不下一行时分两行，不叠字
            out.append(f'<text x="{width}" y="{y:.1f}" font-size="{FS_SMALL}" fill="#9B3B2E" text-anchor="end">{E(right)}</text>')
    return _svg_open(y + 4) + "".join(out) + "</svg>"


def source_cell(text, refs=None):
    """来源格：只写机构名和尾注编号 [n]，完整网址统一列在第 12 节。"""
    import re as _re
    urls = _re.findall(r"https?://\S+", text or "")
    name = _re.sub(r"https?://\S+", "", text or "").strip(" ；;，,")
    if refs is None:
        return E(name or "—")
    marks = "".join(f"<sup class=\"source-ref\">[{refs.add(name or '来源', u)}]</sup>" for u in urls)
    return E(name or "—") + marks


def unprefix(text, label):
    """表头已写“门槛”“代价”“依据”时，去掉格内重复的“门槛：”前缀。"""
    t = (text or "").strip()
    return t[len(label) + 1:].lstrip() if t.startswith(label + "：") else t


def pending_plan(x):
    """pool.py 给招生计划类括号（八协计划等）标的“资格待核：计划名”：返回计划名，没有则返回空串。"""
    m = re.search(r"资格待核：([^；;]+)", x.get("limits") or "")
    return m.group(1).strip() if m else ""


def pending_note(x):
    """志愿表行注：资格待核的志愿不当普通志愿，先核报名资格。"""
    plan = pending_plan(x)
    return f"需核对报名资格（{plan}）" if plan else ""


def limit_line(x):
    """招生章程里的硬性限制（体检、单科、语种、性别等），提醒考生录入前再核对一次。"""
    if not x.get("limits"):
        return ""
    text = x["limits"]
    if pending_plan(x):
        text = re.sub(r"资格待核：[^；;]+", pending_note(x) + "：按当年招生章程和本省招生计划确认能报再填，核实前不算保底", text)
    return f"<div class='small' style='color:#9B3B2E'>限制：{E(text)}</div>"


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
    research_ref = refs.add('本报告院校调研记录；各方面的发现、出处与证据等级见第 12 节') if rep.get('research') else None
    profile_ref = refs.add('本人画像、优先级与家庭约束；个人陈述及本报告的条件判断')
    lst = (opt or {}).get("list", [])
    eu = (opt or {}).get("expected_utility")
    pfall = (opt or {}).get("p_fall")
    stress = (opt or {}).get("stress", {})
    top = [x for x in lst if x["p_land"] >= 0.005]
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
    NEW_PAGE = {"摘要", "核对与来源"}

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
        # 摘要四张卡格式固定，三类评级都一样：推荐志愿数（含冲稳保）、最可能的去向、平均满意度、滑档风险。
        # 不用“满意度 70 分以上的概率”这类固定门槛：100 分是理想组合，位次靠后的考生整张表都到不了 70，会显示 0%、读成判决（R07）。
        tiers = " / ".join(f"{t} {sum(x['tag'] == t for x in lst)}" for t in ("冲", "稳", "保"))
        body += ('<div class="kpis">'
                 f'<div><b>推荐志愿数</b><span class="num">{len(lst)}</span><em>本批次可填 {E(str(m.get("slots", "–")))} 个；{tiers}</em></div>'
                 f'<div><b>最可能的去向</b><span style="font-size:11pt">{E(likely_name)}</span><em>{"概率" + ("" if grade == "B" or fmt(likely_p).startswith("&") else "约 ") + fmt(likely_p) if numeric else "落点最集中的志愿（本省评级不给精确概率）"}</em></div>'
                 + (f'<div><b>平均满意度（0—100）</b><span class="num">{eu:.1f} 分</span><em>表里最高的志愿 {max(x["utility"] for x in lst):.0f} 分。{E(m.get("utility_scale", UTILITY_SCALE))}</em></div>' if numeric and eu is not None else
                    f'<div><b>平均满意度（0—100）</b><span class="num">不估算</span><em>本省概率评级 {E(grade)}，概率不可信，按概率加权的满意度也不算；表里最高的志愿 {max(x["utility"] for x in lst):.0f} 分。</em></div>')
                 + (f'<div><b>滑档风险</b><span class="num">{fall_txt(pfall)}</span><em>录取线整体大波动时 {fall_txt(stress.get("p_fall"))}</em></div>' if grade == "A" or pfall else
                    f'<div><b>滑档风险</b><span class="num">未出现</span><em>{sims:,} 次模拟中没有出现滑档；录取线整体大波动时{"也没有" if not stress.get("p_fall") else "：" + fall_txt(stress.get("p_fall"))}</em></div>')
                 + '</div>')
    if lst:
        body += figure('你最终会被哪里录取', outcome_strip([(x['name'], x['p_land']) for x in lst], pfall or 0, fmt=strip_fmt, fall_text=html.unescape(fall_txt(pfall or 0))),
                       STRIP_CAP + ('浅色为最终录取不到5%的志愿；红色为滑档。' if numeric else '仅作定性示意，本省评级不显示百分比。'), model_ref)
    if s.get("points"):
        body += core_conclusions(s["points"] + (["报告口径：" + str(m["date"])] if m.get("date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(m["date"])) else []))
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
        # 不再放全是“△ 见下文”的方向比较表：每格都没有信息，只占版面（2026-10-20）。
        if rep.get("roadmap"):
            body += info_card("路线图：门槛、顺序、里程碑与切换条件", rep["roadmap"], breakable=True)
        if rep.get("news"):
            body += ("<h3>近期报道与政策</h3><p class='small'>前景和录取线都会受社会情况影响。下表是填报前查到的相关报道，影响一栏是本报告的判断。</p>"
                     "<table><thead><tr><th>事件</th><th style='width:12%'>日期</th><th style='width:22%'>来源</th><th style='width:30%'>对本报告的影响</th></tr></thead><tbody>"
                     + "".join(f"<tr><td>{E(a)}</td><td class='small'>{E(b)}</td><td class='small'>{source_cell(c, refs)}</td><td>{E(d)}</td></tr>" for a, b, c, d in rep["news"])
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
                               bar_chart([[f"{x['order']:02d} {x['name']}", x['p_clear'], x['tag'], html.unescape(fmt(x['p_clear']))] for x in part], maximum=1, palette=CERTAINTY,
                                         legend={'冲': '冲', '稳': '稳', '保': '保'}, tick_fmt=lambda v: f'{v:.0%}'),
                               '琥珀为冲、石绿为稳、黛绿为保；条长为单独过线，精度同主表。', model_ref)
        body += figure('你最终会被哪里录取', outcome_strip([(x['name'], x['p_land']) for x in lst], pfall or 0, fmt=strip_fmt, fall_text=html.unescape(fall_txt(pfall or 0))), STRIP_CAP, model_ref)
        cols = "<colgroup><col style='width:5%'><col style='width:35%'><col style='width:7%'><col style='width:8%'><col style='width:12%'><col style='width:12%'><col style='width:21%'></colgroup>"
        body += "<table class='vt'>"+cols+"<thead><tr><th>序</th><th>志愿</th><th>类型</th><th>偏好</th><th>单独过线</th><th>最终录取</th><th>预测位次</th></tr></thead><tbody>"
        for x in lst:
            hl = " class='hl'" if likely and x is likely else ''
            probs = f"<td class='r'>{fmt(x['p_clear'])}</td><td class='r'>{fmt(x['p_land'],1)}</td>" if numeric else "<td>按分档</td><td>不显示百分比</td>"
            rank_cell = f"{x['expected_cut_rank']:,}" + (f"<div class='small'>{interval80(x)}</div>" if grade!='A' else '')
            if prediction_label(x):
                rank_cell += f"<div class='small'>{E(prediction_label(x))}</div>"
            snippets = [v.strip() for v in re.split(r'[。；]', notes.get(x['name'],'')) if v.strip() and not re.search(r'\d',v)]
            note = pending_note(x) or (snippets[0] if snippets else ('请核章程限制' if x.get('limits') else '历年位次与计划见第 12 节'))
            note = note if len(note)<=18 else note[:17]+'…'
            body += (f"<tr{hl}><td class='num'>{x['order']}</td><td>{E(x['name'])}<span class='row-note'>{E(note)}</span></td>"
                     f"<td><span class='tag {E(x['tag'])}'>{E(x['tag'])}</span></td><td class='r'>{x['utility']:.1f}</td>{probs}<td class='r'>{rank_cell}</td></tr>")
        body += '</tbody></table>'
        for x in lst:
            review = rep.get('third_party_review', {}).get(x['name'], {})
            if only_third_party(x):
                body += (f"<p class='small'><strong>{E(x['name'])}</strong>："
                         f"{E(str(review.get('disclosure', '第三方整理，未经官方核对；不单独支撑主结论')))}；"
                         f"{E(str(review.get('margin', '余量建议尚未填写，不能交付')))}</p>")
        body += ('<p class="small">"偏好"是 0–100 的分数，由"你的画像"一节的权重和各项打分算出。"单独过线"只看这一个志愿；"最终录取"考虑了前面志愿可能已经录取你；"预测位次"是今年最低录取位次的中位预测。'
                 '冲：单独过线 &lt; 40%；稳：40%–85%；保：≥ 85%。高亮行是最可能的去向。'
                 + ('标“需核对报名资格”的志愿属于' + E('、'.join(dict.fromkeys(pending_plan(x) for x in lst if pending_plan(x))))
                    + '等单列的招生计划，能不能报要按当年招生章程和本省招生计划核对；核实之前不当作普通志愿，也不要指望它兜底。'
                    if any(pending_plan(x) for x in lst) else '')
                 + ('' if grade == "A" else '本省概率评级为 ' + grade + '：' + GRADE_MEANING[grade] + '“80% 区间”指今年最低录取位次大约有八成可能落在这个范围内。')
                 + '</p>')
        sec("志愿表", body)

        # 05 为什么这样排
        fall_shown = lambda p: html.unescape(fall_txt(p) if p == 0 or numeric else '有')
        rows = [("本报告的方案", eu, pfall, True)]
        bu, bs = opt.get("baseline_top_utility"), opt.get("baseline_safest")
        if bu:
            rows.append(("只挑最想去的", bu[0], bu[1], False))
        if bs:
            rows.append(("只挑最稳的", bs[0], bs[1], False))
        body = '<p class="lead">本方案兼顾偏好与落空代价；下图与其他两种填法使用同一组数据和假设。</p>'
        body += figure('三种填法的对比', strategy_chart(rows, fmt=fall_shown),
                       strategy_caption(eu, pfall, bu, bs, fall_shown) + '深绿为本报告方案，浅色为对照填法。', model_ref)
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
        carded = [r for r in rs if r.get('brief')]
        if carded:
            body = ('<p class="lead">排在前面的几所学校，每个方面只写一句结论，右上角是证据等级：官方 &gt; 多人一致 &gt; 单人说法 &gt; 推测；虚线框表示没取到。'
                    '完整调研原文和出处在第 12 节。</p>')
        else:
            body = '<p class="lead">以下是对排名靠前学校的升学和就业调研。每条信息都注明了证据等级：官方文件 &gt; 多人一致 &gt; 单人说法 &gt; 推测。</p>'
        if any(r.get('items') for r in rs):
            body += figure('排在前面的学校，各方面查到了多少', evidence_grid([(r['school'], [(x[0], grade_of(x[2])) for x in r.get('items', [])]) for r in rs]),
                           '每格是这一方面信息的证据等级，颜色同下方徽章：深色为官方，石绿为多人一致，浅色为单人说法，空心为推测，虚线为没取到。只表示信息有多可靠，不是给学校打分。',
                           research_ref)
        for r in rs:
            body += school_card(r) if r.get('brief') else research_table(r)
        if qs:
            body += ('<div class="box key"><h4>请你亲自去问学长学姐的问题</h4><p class="small">开头先说明：每条回答请标"确认 / 听说 / 不知道"，不确定就说不知道。最好问两个以上、不同年级的人。</p><ol class="tight">'
                     + "".join(f"<li>{E(x)}</li>" for x in qs) + "</ol></div>")
        sec("院校调研", body)
    else:
        blank("research", "院校调研", "本次没有做院校调研。")

    # 07 待核实
    if rep.get("todo"):
        body = ('<p class="lead">以下事项会直接影响能不能报、报了能不能录，请在正式填报前逐一核对。</p><table><thead><tr><th class="c" style="width:8%">核对</th><th>事项</th><th style="width:30%">去哪里查</th></tr></thead><tbody>'
                + "".join(f"<tr><td class='c'><i class='checkbox'></i></td><td>{E(a)}</td><td class='small'>{E(b)}</td></tr>" for a, b in rep["todo"]) + "</tbody></table>")
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
                          f"<td class='c'>{('是' if x.get('obey', True) else '<b>否</b>') if x.get('group') else '—'}</td><td class='c'><i class='checkbox'></i></td></tr>")
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
            body += f'<h3>{E(grp["topic"])}</h3>' + question_cards([[q["q"]] + ([q["why"]] if q.get("why") else []) for q in grp["items"]])
        body += '<p class="small">提问时可以直接说"按报告志愿表的第 3 个志愿……"，AI 会接着这份报告的数据回答；它不知道的会说不知道。</p>'
        sec("追问清单", body)
    else:
        blank("ask_me", "追问清单", "本次没有预备追问清单。")

    def block(b, level='h3'):
        """方法与事后回看的小节：标题、段落、可选表格。"""
        html = f"<{level}>{E(b['title'])}</{level}>" + "".join(f"<p>{E(x)}</p>" for x in b.get("paras", []))
        if b.get("rows"):
            html += ("<table><thead><tr>" + "".join(f"<th>{E(c)}</th>" for c in b.get("columns", [])) + "</tr></thead><tbody>"
                     + "".join("<tr>" + "".join(td(c) for c in row) + "</tr>" for row in b["rows"]) + "</tbody></table>")
        return html + "".join(f'<p class="small">{E(x)}</p>' for x in b.get("notes", []))

    # 10 方法与假设：正文只留读者需要的（概率可信度、回测、术语）；参数、模型和逐志愿历年数据放第 12 节。
    body = '<p class="lead">这一节用大白话说明结论靠什么算出来、在什么情况下会不准。参数取值、模型细节和各志愿的历年位次放在第 12 节。</p>'
    if m.get("prob_grade"):
        body += ("<h3>概率能信到什么程度</h3><p><b>" + E(m["prob_grade"]) + " 级。</b>" + E(GRADE_MEANING.get(m["prob_grade"], "")) + "</p>"
                 + (f"<p>{E(m['grade_note'])}</p>" if m.get("grade_note") else ""))
    if rep.get("backtest"):
        body += f"<h3>用往年检验过吗</h3><p>{E(rep['backtest'])}</p>"
    body += ('<div class="box glossary"><h4>术语解释</h4><dl>'
             "<dt>位次</dt><dd>全省同科类考生中的排名，比分数更能跨年比较。</dd>"
             "<dt>期望效用</dt><dd>各种可能结局的满意度，按发生概率加权后的平均值。</dd>"
             "<dt>蒙特卡洛模拟</dt><dd>按历史波动随机生成几千种\"今年可能的录取线\"，统计各种结局出现的频率。</dd>"
             "<dt>漂移</dt><dd>全省录取位次整体逐年变宽或变紧的趋势。</dd>"
             "<dt>回测</dt><dd>用过去的数据去\"预测\"已经发生的年份，检验方法准不准。</dd></dl></div>")
    details = ""
    if rep.get("assumptions"):
        details += "<h4>关键假设</h4><table><thead><tr><th style='width:24%'>参数</th><th style='width:14%'>取值</th><th>依据</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{E(a)}</td><td class='num'>{E(str(b))}</td><td>{E(c)}</td></tr>" for a, b, c in rep["assumptions"]) + "</tbody></table>"
    details += ("<h4>模型</h4><p>平行志愿按\"分数优先、遵循志愿、一次投档\"投档，考生落到表中第一个\"位次过线\"的志愿，因此表内按效用降序排列是最优的，需要优化的是入选集合。"
                "各志愿今年的最低录取位次按对数正态分布建模：均值为历年位次对数的近期加权平均（以去年为主）并修正全省漂移，波动取历年离散度与下限的较大者；各志愿通过共同因子相关。"
                "用蒙特卡洛模拟得到每种志愿组合的期望效用，再用边际改进贪心算法选择组合；基准下已无增益时，在压力情景（波动放大）下继续补位，只接受不降低基准期望的补位。</p>")
    details += "".join(block(b, 'h4') for b in rep.get("methods", []))
    if lst:
        details += '<h4>各志愿历年位次与计划</h4><p class="small">未公布或未核实的项目不补造数字。</p><table><thead><tr><th style="width:6%">序</th><th style="width:30%">志愿</th><th>历年位次、计划及补充说明</th></tr></thead><tbody>'
        details += ''.join(f"<tr><td>{x['order']}</td><td>{E(x['name'])}</td><td>{E(rep.get('list_notes',{}).get(x['name'],'未提供历年明细'))}{group_line(x,fmt)}{limit_line(x)}</td></tr>" for x in lst)
        details += '</tbody></table>'
        if any(x.get('data_provenance') for x in lst):
            details += '<h4>逐值来历与待核清单</h4>'
            for x in lst:
                lines = evidence_lines(x)
                if not lines:
                    continue
                details += f'<h4>{E(x["name"])}</h4><ul>' + ''.join(f'<li>{E(line)}</li>' for line in lines) + '</ul>'
                seen = set()
                for _, _, fact in provenance_entries(x):
                    sid = fact.get('source_id', '')
                    if sid in seen:
                        continue
                    seen.add(sid)
                    source = fact.get('source') or fact
                    label = '｜'.join(str(source.get(k) or '未注明') for k in ('publisher', 'title'))
                    url = source.get('landing_url') or source.get('file_url') or source.get('url') or ''
                    ref = refs.add(label + '；出处 ' + sid, url, source.get('retrieved', ''))
                    details += f'<p class="small">{E(sid)}：{E(label)}<sup class="source-ref">[{ref}]</sup></p>'
                if only_third_party(x):
                    review = rep.get('third_party_review', {}).get(x['name'], {})
                    details += f'<p>{E(str(review.get("disclosure", "")))}；{E(str(review.get("margin", "")))}</p>'
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

    # 12 核对与来源：写给要核对的人或 AI。正文给人读，核对用的细节都在这一章；完整网址只在此列出。
    body = ('<p><strong>这一章写给想核对这份报告的人或 AI。</strong>正文里的数字、出处和计算都能在这里对上；PDF 还附带原始数据文件，可用阅读器的附件面板取出。</p>'
            '<div class="box warn"><h4>声明</h4><ol class="tight">'
            "<li>本报告不是官方建议。一切以本省教育考试院当年的填报规则、招生计划和各校当年招生章程为准。</li>"
            "<li>概率来自历年数据的统计推算，不是录取承诺；AI 与模型都可能出错，请交叉核实。</li>"
            "<li>最终的决策权和后果，属于考生和家庭。</li></ol></div>")
    body += "<h3>方法细节</h3>" + details
    if any(r.get('brief') for r in rs):
        body += "<h3>院校调研原文</h3>" + "".join(research_table(r, 'h4') for r in rs if r.get('brief'))
    body += VERIFY_SLOT + "<h3>来源列表</h3><p class='small'>正文方括号里的编号对应下表；个人陈述、模型结果与官方资料分开列明。</p>" + refs.render()
    sec("核对与来源", body)

    from datetime import date
    generated = date.today().isoformat()
    dates = [str(r[2])[:10] for r in rep.get('sources',[]) if re.match(r'\d{4}-\d{2}-\d{2}',str(r[2]))]
    asof = m.get('data_asof') or (max(dates) if dates else m.get('date','待核'))
    if len(str(asof))>32: asof = '见摘要报告口径'
    report_id = m.get('case_id') or m.get('id') or '待编号'
    subtitle = ' · '.join(part.strip() for part in m.get('subtitle','').split('·') if not re.search(r'样板|模拟|虚构|实际生成|回溯版|案例',part))
    cover = cover_html(m.get('title','高考志愿填报决策报告'), subtitle, m.get('candidate','本人'),
                       m.get('stage','高考版 · 填报决策'), m.get('province','待核'), report_id, generated, asof,
                       s.get('headline',''), [(i,t) for i,t,_ in secs], simulated=m.get('mode')!='formal')
    if missing:
        print('提醒：以下各节没有内容：'+'、'.join(dict.fromkeys(missing)),file=sys.stderr)
    return document_html(m.get('title','高考志愿填报决策报告'),cover,''.join(b for _,_,b in secs),m.get('candidate','本人'),'高考',report_id,simulated=m.get('mode')!='formal')


def write_sheet(opt, path):
    """填报单 CSV：列与报告“填报单”一节一致，代码缺失的留空，由 case_check 拒绝。"""
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        metadata = any(x.get('data_provenance') or x.get('source_grade') for x in (opt or {}).get('list', []))
        w.writerow(["序", "院校代码", "院校", "专业组", "专业代码", "组内专业顺序", "服从调剂"] + (["数据等级", "历年数字与出处"] if metadata else []))
        for x in (opt or {}).get("list", []):
            ms = "、".join(f"{i}. {mj['name']}" for i, mj in enumerate(x.get("majors") or [], 1))
            w.writerow([x["order"], x.get("code") or "", x["name"].split("（")[0].split("·")[0] if x.get("group") else x["name"].split("（")[0],
                        x.get("group") or "", x.get("major_code") or "", ms, ("是" if x.get("obey", True) else "否") if x.get("group") else "—"]
                       + ([prediction_label(x), '；'.join(evidence_lines(x))] if metadata else []))


def find_browser():
    cands = [os.environ.get("CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "/Applications/Chromium.app/Contents/MacOS/Chromium",
             shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("msedge"),
             r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    return next((c for c in cands if c and os.path.exists(c)), None)



def print_pdf(doc, out_path):
    """用本机 Chrome/Edge 无头模式把 HTML 打印成 PDF；三版共用。找不到浏览器时输出 HTML 并退出。"""
    br = find_browser()
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    tmp.write(doc)
    tmp.close()
    if not br:
        html_out = os.path.splitext(str(out_path))[0] + ".html"
        shutil.copy(tmp.name, html_out)
        sys.exit(f"没有找到 Chrome/Edge，已输出 {html_out}；请用浏览器打开后\"打印 → 存储为 PDF\"（勾选\"背景图形\"）。")
    out = os.path.abspath(out_path)
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
    return out


FIT_LEVELS = ('fit', 'fit2')


def add_section_class(doc, sid, name):
    """给 data-section=sid 的小节加 class（已有 class 时追加，替换更低一档的 fit）。"""
    def repl(m):
        attrs = m[1]
        cls = re.search(r'class="([^"]*)"', attrs)
        if cls:
            kept = [c for c in cls[1].split() if c not in FIT_LEVELS]
            return '<section' + attrs.replace(cls[0], 'class="' + ' '.join(kept + [name]) + '"') + '>'
        return f'<section class="{name}"' + attrs + '>'
    return re.sub(r'<section((?=[^>]*data-section="' + re.escape(sid) + r'")[^>]*)>', repl, doc, count=1)


def print_fitted(doc, out_path, rounds=4):
    """打印 PDF；节末只剩一两行掉到新页时，收紧那一节（再不行连同上一节）的行距重排。

    返回最终打印所用的 HTML（调用方据此保存 report.html、嵌入附件）。孤页仍在时由 check_layout 报错。"""
    try:
        import pymupdf
        from check_layout import tail_orphans
    except ImportError:
        print_pdf(doc, out_path)
        return doc
    levels = {}
    for _ in range(rounds + 1):
        out = print_pdf(doc, out_path)
        with pymupdf.open(out) as pdf:
            orphans = [sid for _, sid, _ in tail_orphans(pdf) if sid]
        if not orphans or _ == rounds:
            return doc
        changed = False
        for sid in orphans:
            level = levels.get(sid, -1)
            target = sid
            if level + 1 >= len(FIT_LEVELS):  # 本节已收到最紧：再收紧上一节
                prev = f'{int(sid) - 1:02d}'
                target, level = prev, levels.get(prev, -1)
                if level + 1 >= len(FIT_LEVELS) or int(sid) <= 1:
                    continue
            levels[target] = level + 1
            doc = add_section_class(doc, target, FIT_LEVELS[level + 1])
            changed = True
        if not changed:
            return doc
    return doc


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
    ap.add_argument("--profile-version", help="明确指定案例内所用画像文件或存档版本；正式输出必填")
    a = ap.parse_args()
    rep = json.load(open(a.report, encoding="utf-8"))
    opt = json.load(open(a.opt, encoding="utf-8")) if a.opt else None
    if opt:
        errors = check_report(rep, opt)
        if errors:
            ap.error("报告数字核验失败：" + "；".join(errors))
    if a.sheet:
        write_sheet(opt, a.sheet)
    if (Path(a.report).resolve().parent/'case.json').exists():
        from datetime import datetime
        rep.setdefault('meta',{})['generated_on']=datetime.now().strftime('%Y-%m-%d')
    doc = build(rep, opt)
    binding = materials = None
    root = Path(a.report).resolve().parent
    if (root/'case.json').exists():
        from authoring_metadata import authoring_errors
        errors=authoring_errors(json.load(open(root/'case.json',encoding='utf-8')))
        if errors:ap.error('；'.join(errors))
        if not a.profile_version:ap.error('生成有案例号的报告必须指定 --profile-version')
        from verify_report import report_pdf_name
        expected = report_pdf_name(json.load(open(root/'case.json', encoding='utf-8'))['case_id'])
        if not a.out.lower().endswith('.html') and Path(a.out).name != expected:
            ap.error(f'交付 PDF 一律以报告号命名：--out 须为 {expected}')
        from verify_report import bind_profile, gaokao_materials, append_html, require_analysis_profile
        binding, profile, warning = bind_profile(root,a.profile_version,require_analysis=True)
        if warning:print(warning,file=sys.stderr)
        materials=gaokao_materials(root,rep,opt,binding,warning)
        doc=append_html(doc,materials)
    elif not a.out.lower().endswith('.html'):
        ap.error('交付PDF须有case.json并明确指定 --profile-version；无登记仅能预览HTML')
    publication_gate(doc)
    if a.out.lower().endswith(".html"):
        open(a.out, "w", encoding="utf-8").write(doc)
        print(f"已生成 {a.out}")
        return
    doc = print_fitted(doc, a.out)
    out = os.path.abspath(a.out)
    print(f"已生成 {out}")
    if binding:
        from verify_report import gaokao_files, attach_pdf, read, json_bytes, digest
        files = gaokao_files(root,rep,opt,binding,a.opt)
        attach_pdf(out,files,materials,read(root/'case.json'),binding,doc)
        trace = json.loads(files['report_trace.json'])
        trace['artifacts']={Path(out).name:digest(Path(out).read_bytes())}
        (root/'report_trace.json').write_bytes(json_bytes(trace))
    layout_gate(out)
    if binding:
        from verify_report import verify
        result=verify(out)
        if not result['ok']:sys.exit('PDF核对失败，不能交付：'+'；'.join(result['errors']))
    if binding:
        from verify_report import record_generation
        record_generation(root,out)


if __name__ == "__main__":
    main()
