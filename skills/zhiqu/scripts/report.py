#!/usr/bin/env python3
"""知衢 · 志愿填报决策报告生成器（仅用 Python 标准库；PDF 由本机 Chrome/Edge 无头模式打印）。

用法：
  python3 report.py report.json --opt result.json --out 报告.pdf
  python3 report.py report.json --opt result.json --out 报告.html   # 只要 HTML

report.json 的字段见 references/report-guide.md；result.json 是 optimize.py --json 的输出。
找不到浏览器时会只输出 HTML，并提示用浏览器"打印 → 存储为 PDF"。
"""
import argparse
from check_report import check_report
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

E = html.escape

CSS = r"""
@page { size: A4; margin: 20mm 18mm 20mm 18mm; background: #FBF6E6;
  @top-left { content: "知衢 · 志愿填报决策报告"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #8C8472; }
  @top-right { content: "__RUNHEAD__"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #8C8472; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #8C8472; }
  @bottom-left { content: "仅供参考 · 以当年官方招生信息为准"; font: 8pt "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; color: #A39B87; }
}
@page cover { margin: 0; @top-left { content: none; } @top-right { content: none; } @bottom-right { content: none; } @bottom-left { content: none; } }
:root { --ink:#161616; --soft:#3B3832; --muted:#66604F; --rule:#D9CFB4; --rule2:#BFB294;
  --accent:#21473E; --accent2:#34685D; --pale:#EFE7D0; --amber:#9A6B1F; --red:#9B3B2E; --green:#2F6B4F; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
html, body { background: #FBF6E6; }
body { margin: 0; color: var(--ink); font: 10pt/1.75 "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; font-feature-settings: "lnum"; }
h1,h2,h3 { font-family: "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; font-weight: 700; color: var(--ink); }
h2 { font-size: 17pt; margin: 0 0 4mm; padding-bottom: 2.5mm; border-bottom: 1.2pt solid var(--accent); break-after: avoid; }
h2 .no { color: var(--accent); margin-right: 3mm; font-weight: 400; font-size: 13pt; vertical-align: 1pt; }
h3 { font-size: 12pt; margin: 6mm 0 2mm; break-after: avoid; }
p { margin: 0 0 2.6mm; }
section { margin-top: 12mm; }
section:not(.major) { break-inside: avoid-page; }
section.major { break-before: page; margin-top: 0; }
svg.chart { width: 100%; height: auto; display: block; }
.lead { font-size: 11pt; color: var(--soft); }
.small { font-size: 8.5pt; color: var(--muted); }
.num { font-variant-numeric: tabular-nums; }

/* cover */
.cover { page: cover; width: 210mm; height: 296mm; overflow: hidden; padding: 0; position: relative; background: #FBF6E6; break-after: page; }
.cover .band { background: var(--accent); color: #F5EFDD; padding: 26mm 22mm 13mm; }
.cover .kicker { font-size: 9pt; letter-spacing: 3pt; opacity: .85; }
.cover h1 { color: #FBF6E6; font-size: 30pt; margin: 6mm 0 3mm; letter-spacing: 1pt; }
.cover .sub { font-size: 11pt; opacity: .9; }
.cover .motto { margin-top: 9mm; font-size: 10.5pt; letter-spacing: 4pt; opacity: .78; display: flex; align-items: center; gap: 4mm; }
.cover .motto::before { content: ""; width: 8mm; height: .6pt; background: #F5EFDD; opacity: .7; }
.cover .meta { padding: 10mm 22mm 0; display: grid; grid-template-columns: repeat(3,1fr); gap: 6mm 8mm; }
.cover .meta div { border-top: .8pt solid var(--rule2); padding-top: 2mm; }
.cover .meta b { display:block; font-size: 8pt; color: var(--muted); font-weight: 500; letter-spacing: 1pt; }
.cover .meta span { font-size: 12pt; }
.cover .verdict { margin: 9mm 22mm 0; padding: 6mm 8mm; background: #FFFDF6; border-left: 3pt solid var(--accent); }
.cover .verdict b { display:block; font-size: 8pt; color: var(--accent); letter-spacing: 2pt; margin-bottom: 2mm; }
.cover .verdict p { font-size: 14pt; line-height: 1.6; margin: 0; }
.cover .foot { position: absolute; left: 22mm; right: 22mm; bottom: 16mm; font-size: 8pt; color: var(--muted); border-top: .6pt solid var(--rule); padding-top: 3mm; }

/* kpis */
.kpis { display: grid; grid-template-columns: repeat(4,1fr); gap: 0; border-top: 1pt solid var(--ink); border-bottom: .6pt solid var(--rule2); margin: 4mm 0 6mm; }
.kpis div { padding: 3mm 3mm 3mm 0; }
.kpis div + div { padding-left: 4mm; border-left: .6pt solid var(--rule); }
.kpis b { display:block; font-size: 8pt; color: var(--muted); font-weight: 500; }
.kpis span { font: 700 19pt/1.25 "PT Serif","Songti SC","Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif; }
.kpis em { display:block; font-style: normal; font-size: 8pt; color: var(--soft); }

/* boxes */
.box { background: #FFFDF6; border: .6pt solid var(--rule); padding: 4mm 5mm; margin: 3mm 0 4mm; break-inside: avoid; }
.box.key { border-left: 2.5pt solid var(--accent); }
.box.warn { border-left: 2.5pt solid var(--amber); }
.box h4 { margin: 0 0 1.5mm; font-size: 9pt; letter-spacing: 1pt; color: var(--accent); }
.box.warn h4 { color: var(--amber); }
ol.tight, ul.tight { margin: 0; padding-left: 5mm; }
ol.tight li, ul.tight li { margin: .6mm 0; }

/* tables */
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 8.8pt; }
thead th { white-space: nowrap; text-align: left; font-weight: 600; color: var(--soft); border-top: 1pt solid var(--ink); border-bottom: .6pt solid var(--ink); padding: 1.6mm 2mm; font-size: 8pt; }
tbody td { border-bottom: .4pt solid var(--rule); padding: 1.5mm 2mm; vertical-align: top; }
tbody tr { break-inside: avoid; }
td.r, th.r { text-align: right; font-variant-numeric: tabular-nums; }
td.c, th.c { text-align: center; }
tr.hl td { background: #F3EBD2; }
.tag { display: inline-block; min-width: 7mm; text-align: center; font-size: 7.5pt; padding: .2mm 1.5mm; border-radius: 1mm; color: #fff; }
.tag.冲 { background: var(--red); } .tag.稳 { background: var(--amber); } .tag.保 { background: var(--green); }

/* two columns / cards */
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; }
.card { background: #FFFDF6; border: .6pt solid var(--rule); padding: 4mm 5mm; break-inside: avoid; }
.card h3 { margin: 0 0 1mm; }
.card .fit { font-size: 8pt; color: var(--accent); letter-spacing: 1pt; }
.card dl { margin: 2mm 0 0; }
.card dt { font-size: 8pt; color: var(--muted); margin-top: 1.6mm; }
.card dd { margin: 0; }
.fig { margin: 2mm 0 5mm; break-inside: avoid; }
.fig .cap { font-size: 8pt; color: var(--muted); margin-top: 1mm; }
.fig .ttl { font-size: 9pt; font-weight: 600; margin-bottom: 1mm; }
.glossary dt { font-weight: 600; margin-top: 1.5mm; } .glossary dd { margin: 0 0 1mm; color: var(--soft); }
ul.asklist { list-style: none; padding: 0; margin: 0 0 3mm; }
ul.asklist li { padding: 2mm 0 2mm 4mm; border-left: 2pt solid var(--rule2); margin: 0 0 2mm; background: #FFFDF6; break-inside: avoid; }
ul.asklist li b { font-weight: 600; } ul.asklist li span { display: block; font-size: 8.5pt; color: var(--muted); margin-top: .5mm; }
.toc { margin-top: 2mm; columns: 2; column-gap: 10mm; } .toc div { display: flex; border-bottom: .4pt dotted var(--rule2); padding: 1.1mm 0; break-inside: avoid; }
.toc div span:first-child { width: 10mm; color: var(--accent); font-weight: 600; }
"""


def pct(x, d=0):
    if x is None:
        return "–"
    if d == 0 and 0 < x < 0.01:
        d = 1  # 小于 1% 时保留一位小数，避免把 0.5% 显示成 0%
    return f"{x * 100:.{d}f}%"


def bars_h(items, width=640, bar_h=13, gap=6, label_w=170, color="#34685D", fmt=lambda v: f"{v:.0%}", vmax=None):
    """水平条形图：items = [(label, value)]"""
    vmax = vmax or max((v for _, v in items), default=1) or 1
    h = len(items) * (bar_h + gap) + 4
    w_plot = width - label_w - 44
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" font-family="PT Serif, Songti SC, Noto Serif SC, serif" font-size="9">']
    for i, (lab, v) in enumerate(items):
        y = i * (bar_h + gap) + 2
        bw = max(0.5, w_plot * v / vmax)
        lab = lab if len(lab) <= 16 else lab[:15] + "…"
        out.append(f'<text x="{label_w - 6}" y="{y + bar_h - 3}" text-anchor="end" fill="#4A4740">{E(lab)}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{w_plot}" height="{bar_h}" fill="#EFE7D0"/>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" fill="{color}"/>')
        out.append(f'<text x="{label_w + bw + 4:.1f}" y="{y + bar_h - 3}" fill="#1B1B1B">{E(fmt(v))}</text>')
    out.append("</svg>")
    return "".join(out)


def strategy_chart(rows, width=640):
    """策略对比：期望效用条 + 滑档概率标注。rows = [(name, eu, pfall, highlight)]"""
    vmax = max(r[1] for r in rows) or 1
    label_w, bar_h, gap = 150, 18, 10
    h = len(rows) * (bar_h + gap) + 8
    w_plot = width - label_w - 110
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" font-family="PT Serif, Songti SC, Noto Serif SC, serif" font-size="9">']
    for i, (n, eu, pf, hl) in enumerate(rows):
        y = i * (bar_h + gap) + 4
        bw = max(1, w_plot * max(eu, 0) / vmax)
        col = "#21473E" if hl else "#BFB294"
        out.append(f'<text x="{label_w - 6}" y="{y + bar_h - 5}" text-anchor="end" fill="#1B1B1B" font-weight="{600 if hl else 400}">{E(n)}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" fill="{col}"/>')
        out.append(f'<text x="{label_w + bw + 5:.1f}" y="{y + bar_h - 5}" fill="#1B1B1B">期望 {eu:.1f}</text>')
        out.append(f'<text x="{width - 4}" y="{y + bar_h - 5}" text-anchor="end" fill="{"#9B3B2E" if pf > 0.01 else "#4A4740"}">滑档 {pf:.1%}</text>')
    out.append("</svg>")
    return "".join(out)


def outcome_strip(items, pfall, width=640):
    """结局分布：一条 100% 堆积条，按志愿顺序着色，展示"最可能落在哪里"。"""
    h = 34
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" xmlns="http://www.w3.org/2000/svg" font-family="PT Serif, Songti SC, Noto Serif SC, serif" font-size="8">']
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
            col = "#CFC6AE"
        out.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="18" fill="{col}" stroke="#FBF6E6" stroke-width="0.6"/>')
        if w > 34:
            out.append(f'<text x="{x + 3:.1f}" y="12" fill="#fff">{E(str(i + 1))} · {p:.0%}</text>')
        x += w
    if pfall > 0:
        w = max(1.5, width * pfall)
        out.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="18" fill="#9B3B2E"/>')
    out.append(f'<text x="0" y="30" fill="#7D7665">左起为第 1 志愿；色块宽度 = 最终被该志愿录取的概率{"；红色 = 滑档" if pfall > 0 else ""}</text>')
    out.append("</svg>")
    return "".join(out)


def limit_line(x):
    """招生章程里的硬性限制（体检、单科、语种、性别等），提醒考生录入前再核对一次。"""
    return f"<div class='small' style='color:#9B3B2E'>限制：{E(x['limits'])}</div>" if x.get("limits") else ""


def group_line(x):
    """专业组志愿：列出落到组内各专业和被调剂的概率。"""
    ms = x.get("majors")
    if not ms or x.get("p_land", 0) <= 0:
        return ""
    parts = [f"{E(m['name'])} {pct(m['p'], 1)}" for m in ms] + [f"调剂 {pct(x.get('p_adjusted', 0), 1)}"]
    return "<div class='small'>组内：" + "｜".join(parts) + "</div>"


def build(rep, opt):
    m = rep.get("meta", {})
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
    fall_txt = lambda p: (f"&lt; {100 / sims:.2g}%" if p == 0 else pct(p, 1))  # 模拟中一次都没出现，只能说低于 1/模拟次数
    likely_name = likely["name"] if likely else "–"
    likely_p = likely["p_land"] if likely else None
    if likely and likely.get("majors"):  # 专业组：显示"学校·最可能的专业"
        top = max(likely["majors"], key=lambda m: m["p"])
        likely_name = likely["name"].split("·")[0] + "·" + top["name"]
        likely_p = top["p"]
    secs = []
    missing = []
    n = 0

    def sec(title, body, major=False):
        nonlocal n
        n += 1
        cls = ' class="major"' if major else ""
        secs.append((n, title, f'<section{cls}><h2><span class="no">{n:02d}</span>{E(title)}</h2>{body}</section>'))

    # 目录固定：每一节都出现。没有内容的节写明原因（report.json 的 omitted.<键>），并在终端提醒。
    omitted = rep.get("omitted", {})

    def blank(key, title, default, major=False):
        why = omitted.get(key)
        if not why:
            missing.append(title)
        sec(title, f'<div class="box"><h4>本节说明</h4><p>{E(why or default)}</p></div>', major)

    # 01 摘要
    s = rep.get("summary", {})
    body = f'<p class="lead">{E(s.get("headline", ""))}</p>'
    if lst:
        body += ('<div class="kpis">'
                 f'<div><b>推荐志愿数</b><span class="num">{len(lst)}</span><em>本批次可填 {E(str(m.get("slots", "–")))} 个</em></div>'
                 f'<div><b>最可能的去向</b><span style="font-size:11pt">{E(likely_name)}</span><em>概率约 {pct(likely_p)}</em></div>'
                 f'<div><b>满意度 70 分以上的概率</b><span class="num">{pct(p_good)}</span><em>100 分 = 候选中你最想去的</em></div>'
                 f'<div><b>滑档风险</b><span class="num">{fall_txt(pfall)}</span><em>录取线整体大波动时 {fall_txt(stress.get("p_fall"))}</em></div>'
                 '</div>')
    if lst:
        body += ('<div class="fig"><div class="ttl">你最终会被哪里录取</div>' + outcome_strip([(x["name"], x["p_land"]) for x in lst], pfall or 0)
                 + '<div class="cap">数字是志愿序号，对应"志愿表"一节；浅色是录取概率不到 5% 的志愿。</div></div>')
    if s.get("points"):
        body += '<div class="box key"><h4>核心结论</h4><ol class="tight">' + "".join(f"<li>{E(x)}</li>" for x in s["points"]) + "</ol></div>"
    if s.get("actions"):
        body += '<div class="box warn"><h4>接下来你要做的事</h4><ol class="tight">' + "".join(f"<li>{E(x)}</li>" for x in s["actions"]) + "</ol></div>"
    if s.get("plain"):
        body += "".join(f"<p>{E(x)}</p>" for x in s["plain"])
    sec("摘要", body, major=True)

    # 02 画像
    pr = rep.get("profile", {})
    body = ""
    if pr.get("intro"):
        body += f'<p class="lead">{E(pr["intro"])}</p>'
    if pr.get("facts"):
        body += "<table><thead><tr><th style='width:28%'>项目</th><th>情况</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{E(a)}</td><td>{E(b)}</td></tr>" for a, b in pr["facts"]) + "</tbody></table>"
    if pr.get("priorities"):
        body += ('<div class="fig"><div class="ttl">你最在乎什么（由问卷第九节的排序换算的权重）</div>'
                 + bars_h([(a, float(b)) for a, b in pr["priorities"]], fmt=lambda v: f"{v:.0%}", vmax=1)
                 + '<div class="cap">权重越大，这一项对"这个志愿好不好"的影响越大。"录取稳妥"不计入权重，而是决定你能承受多大的滑档风险。</div></div>')
    if pr.get("constraints"):
        body += '<div class="box"><h4>硬约束（不满足的学校和专业已经排除）</h4><ul class="tight">' + "".join(f"<li>{E(x)}</li>" for x in pr["constraints"]) + "</ul></div>"
    if pr.get("tensions"):
        body += '<div class="box warn"><h4>需要你想清楚的矛盾</h4><ul class="tight">' + "".join(f"<li>{E(x)}</li>" for x in pr["tensions"]) + "</ul></div>"
    sec("你的画像", body, major=True)

    # 03 方向
    ds = rep.get("directions", [])
    if ds:
        body = '<p class="lead">' + E(rep.get("directions_intro", "以下方向由兴趣、能力、目标和约束交叉得出。每个方向都列出支持证据、反面证据、有条件的就业前景和验证办法。")) + "</p><div class='grid2'>"
        for d in ds:
            body += (f'<div class="card"><div class="fit">{E(d.get("fit", ""))}</div><h3>{E(d["name"])}</h3>'
                     f'<div class="small">{E(d.get("majors", ""))}</div><dl>'
                     + (f"<dt>支持</dt><dd>{'；'.join(E(x) for x in d.get('evidence', []))}</dd>" if d.get("evidence") else "")
                     + (f"<dt>反面</dt><dd>{'；'.join(E(x) for x in d.get('counter', []))}</dd>" if d.get("counter") else "")
                     + (f"<dt>前景（有条件）</dt><dd>{'<br>'.join(E(x) for x in d.get('outlook', []))}</dd>" if d.get("outlook") else "")
                     + (f"<dt>怎么验证</dt><dd>{E(d['verify'])}</dd>" if d.get("verify") else "")
                     + "</dl></div>")
        body += "</div>"
        if rep.get("news"):
            body += ("<h3>近期报道与政策</h3><p class='small'>前景和录取线都会受社会情况影响。下表是填报前查到的相关报道，影响一栏是本报告的判断。</p>"
                     "<table><thead><tr><th>事件</th><th style='width:12%'>日期</th><th style='width:22%'>来源</th><th style='width:30%'>对本报告的影响</th></tr></thead><tbody>"
                     + "".join(f"<tr><td>{E(a)}</td><td class='small'>{E(b)}</td><td class='small' style='word-break:break-all'>{E(c)}</td><td>{E(d)}</td></tr>" for a, b, c, d in rep["news"])
                     + "</tbody></table>")
        sec("专业方向", body, major=True)
    else:
        blank("directions", "专业方向", "本次没有做专业方向分析。", major=True)

    # 04 志愿表
    if lst:
        notes = rep.get("list_notes", {})
        body = ('<p class="lead">下表就是建议的填报顺序。顺序按"你有多想去"排，而不是按"把握有多大"排：平行志愿会从第一个开始逐个检查，排在前面的冲刺志愿不会影响后面志愿的录取机会。</p>'
                '<div class="fig"><div class="ttl">你最终会被哪里录取</div>' + outcome_strip([(x["name"], x["p_land"]) for x in lst], pfall or 0) + "</div>")
        body += ("<table><thead><tr><th class='c'>序</th><th>志愿</th><th class='c'>类型</th><th class='r'>偏好</th>"
                 "<th class='r'>单独过线</th><th class='r'>最终录取</th><th class='r'>预测位次</th><th>说明</th></tr></thead><tbody>")
        for x in lst:
            hl = " class='hl'" if likely and x is likely else ""
            body += (f"<tr{hl}><td class='c num'>{x['order']}</td><td>{E(x['name'])}{group_line(x)}</td><td class='c'><span class='tag {E(x['tag'])}'>{E(x['tag'])}</span></td>"
                     f"<td class='r'>{x['utility']:g}</td><td class='r'>{pct(x['p_clear'])}</td><td class='r'>{pct(x['p_land'], 1)}</td>"
                     f"<td class='r'>{x['expected_cut_rank']:,}</td><td class='small'>{E(notes.get(x['name'], ''))}{limit_line(x)}</td></tr>")
        body += "</tbody></table>"
        body += ('<p class="small">"偏好"是 0–100 的分数，由"你的画像"一节的权重和各项打分算出。"单独过线"只看这一个志愿；"最终录取"考虑了前面志愿可能已经录取你；"预测位次"是今年最低录取位次的中位预测。'
                 '冲：单独过线 &lt; 40%；稳：40%–85%；保：≥ 85%。高亮行是最可能的去向。</p>')
        sec("志愿表", body, major=True)

        # 05 为什么这样排
        rows = [("本报告的方案", eu, pfall, True)]
        bu, bs = opt.get("baseline_top_utility"), opt.get("baseline_safest")
        if bu:
            rows.append(("只挑最想去的", bu[0], bu[1], False))
        if bs:
            rows.append(("只挑最稳的", bs[0], bs[1], False))
        body = ('<p class="lead">"期望效用"可以理解为：把所有可能的结局按发生的概率加权平均后，你平均能得到多满意的结果。它同时考虑了"想不想去"和"能不能上"。</p>'
                '<div class="fig"><div class="ttl">三种填法的对比</div>' + strategy_chart(rows)
                + '<div class="cap">条越长越好；滑档概率越低越好。只挑最想去的，容易滑档；只挑最稳的，又浪费了分数。</div></div>')
        if rep.get("why"):
            body += "".join(f"<p>{E(x)}</p>" for x in rep["why"])
        if stress:
            body += (f'<div class="box"><h4>压力测试</h4><p>如果今年各校录取线的波动是往年的 {E(str(rep.get("stress_mult", 2)))} 倍，'
                     f'这张志愿表的期望效用为 {stress.get("expected_utility", 0):.1f}，滑档概率为 {pct(stress.get("p_fall"), 1)}。</p></div>')
        if rep.get("sensitivity"):
            body += "<h3>换一种假设，结论会变吗</h3><table><thead><tr><th>假设</th><th class='r'>期望效用</th><th class='r'>滑档概率</th><th>前段是否变化</th></tr></thead><tbody>" + "".join(
                f"<tr><td>{E(a)}</td><td class='r'>{E(str(b))}</td><td class='r'>{E(str(c))}</td><td>{E(d)}</td></tr>" for a, b, c, d in rep["sensitivity"]) + "</tbody></table>"
        sec("为什么这样排", body)
    else:
        blank("list", "志愿表", "本次没有运行志愿组合优化，因此没有志愿表。", major=True)
        blank("list", "为什么这样排", "本次没有运行志愿组合优化，因此没有排序依据与方案对比。")

    # 06 院校调研
    rs = rep.get("research", [])
    qs = rep.get("questions", [])
    if rs or qs:
        body = '<p class="lead">以下是对排名靠前学校的升学和就业调研。每条信息都注明了证据等级：官方文件 &gt; 多人一致 &gt; 单人说法 &gt; 推测。</p>'
        for r in rs:
            body += f"<h3>{E(r['school'])}</h3><table><thead><tr><th style='width:26%'>方面</th><th>发现</th><th style='width:18%'>证据等级</th></tr></thead><tbody>" + "".join(
                f"<tr><td>{E(a)}</td><td>{E(b)}</td><td class='small'>{E(c)}</td></tr>" for a, b, c in r.get("items", [])) + "</tbody></table>"
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
                          f"<td class='c'>{'是' if x.get('obey', True) else '<b>否</b>'}</td><td class='c'>□</td></tr>")
        body = ('<p class="lead">这一页用来照着录入志愿填报系统。录错一个代码，前面算得再准也没用，所以请逐格核对。</p>'
                '<div class="box warn"><h4>录入前必读</h4><ol class="tight">'
                '<li>院校代码、专业组或专业代码<b>每年可能变</b>：表中代码来自往年数据，必须按今年的招生计划或专业目录逐个核对、改正。</li>'
                '<li>专业组志愿：组内专业按下表顺序填；"服从调剂"一栏与本报告的计算一致，改动前先回来重算。</li>'
                '<li>录入后，把系统里的志愿表截图或打印，逐行对照本页勾选；提交前确认截止时间。</li></ol></div>'
                "<table><thead><tr><th class='c'>序</th><th>院校代码</th><th>院校</th><th>专业组 / 专业代码</th><th>组内专业志愿顺序</th><th class='c'>服从调剂</th><th class='c'>已核对</th></tr></thead><tbody>"
                + rows_html + "</tbody></table>")
        sec("填报单", body, major=True)
    else:
        blank("list", "填报单", "本次没有运行志愿组合优化，因此没有填报单。", major=True)

    # 可以直接问我（个性化的追问清单）
    if rep.get("ask_me"):
        body = ('<p class="lead">' + E(rep.get("ask_me_intro", "这份报告是和 AI 一起做出来的。看不懂的地方、想换个假设算一算，都可以直接回去问它。下面是根据你的情况预备的问题，挑感兴趣的问就行。")) + "</p>")
        for grp in rep["ask_me"]:
            body += f'<h3>{E(grp["topic"])}</h3><ul class="asklist">' + "".join(
                f'<li><b>“{E(q["q"])}”</b>' + (f'<span>{E(q["why"])}</span>' if q.get("why") else "") + "</li>" for q in grp["items"]) + "</ul>"
        body += '<p class="small">提问时可以直接说"按报告志愿表的第 3 个志愿……"，AI 会接着这份报告的数据回答；它不知道的会说不知道。</p>'
        sec("追问清单", body, major=True)
    else:
        blank("ask_me", "追问清单", "本次没有预备追问清单。", major=True)

    # 08 方法与假设（可用术语）
    body = '<p class="lead">这一节写给想了解细节的读者，会用到一些专业术语，术语解释在本节末尾。</p>'
    if rep.get("assumptions"):
        body += "<h3>关键假设</h3><table><thead><tr><th style='width:24%'>参数</th><th style='width:14%'>取值</th><th>依据</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{E(a)}</td><td class='num'>{E(str(b))}</td><td>{E(c)}</td></tr>" for a, b, c in rep["assumptions"]) + "</tbody></table>"
    body += ("<h3>模型</h3><p>平行志愿按\"分数优先、遵循志愿、一次投档\"投档，考生落到表中第一个\"位次过线\"的志愿，因此表内按效用降序排列是最优的，需要优化的是入选集合。"
             "各志愿今年的最低录取位次按对数正态分布建模：均值为历年位次对数的近期加权平均（以去年为主）并修正全省漂移，波动取历年离散度与下限的较大者；各志愿通过共同因子相关。"
             "用蒙特卡洛模拟得到每种志愿组合的期望效用，再用边际改进贪心算法选择组合，并在压力情景下补满剩余志愿位。</p>")
    if rep.get("backtest"):
        body += f"<h3>本省回测</h3><p>{E(rep['backtest'])}</p>"
    body += ('<div class="box glossary"><h4>术语解释</h4><dl>'
             "<dt>位次</dt><dd>全省同科类考生中的排名，比分数更能跨年比较。</dd>"
             "<dt>期望效用</dt><dd>各种可能结局的满意度，按发生概率加权后的平均值。</dd>"
             "<dt>蒙特卡洛模拟</dt><dd>按历史波动随机生成几千种\"今年可能的录取线\"，统计各种结局出现的频率。</dd>"
             "<dt>漂移</dt><dd>全省录取位次整体逐年变宽或变紧的趋势。</dd>"
             "<dt>回测</dt><dd>用过去的数据去\"预测\"已经发生的年份，检验方法准不准。</dd></dl></div>")
    sec("方法与假设", body, major=True)

    # 事后回看（仅用于回测案例）
    if rep.get("hindsight"):
        h = rep["hindsight"]
        body = '<p class="lead">' + E(h.get("intro", "")) + "</p>"
        if h.get("table"):
            body += "<table><thead><tr>" + "".join(f"<th>{E(c)}</th>" for c in h["columns"]) + "</tr></thead><tbody>" + "".join(
                "<tr>" + "".join(f"<td>{E(str(c))}</td>" for c in row) + "</tr>" for row in h["table"]) + "</tbody></table>"
        body += "".join(f"<p>{E(x)}</p>" for x in h.get("notes", []))
        sec("事后回看", body, major=True)
    else:
        sec("事后回看", '<p class="lead">' + E(omitted.get("hindsight", "录取结果公布后，把真实的投档线和最终去向填进这一节，与本报告的预测逐条对照：哪些判断准、哪些偏了、偏在哪里。这样下一次的判断才会更准。")) + "</p>", major=True)

    # 09 来源与声明
    body = ""
    if rep.get("sources"):
        body += "<table><thead><tr><th style='width:30%'>数据</th><th>来源</th><th style='width:16%'>查询日期</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{E(a)}</td><td class='small' style='word-break:break-all'>{E(b)}</td><td class='small'>{E(c)}</td></tr>" for a, b, c in rep["sources"]) + "</tbody></table>"
    body += ('<div class="box warn"><h4>声明</h4><ol class="tight">'
             "<li>本报告不是官方建议。一切以本省教育考试院当年的填报规则、招生计划和各校当年招生章程为准。</li>"
             "<li>概率来自历年数据的统计推算，不是录取承诺；AI 与模型都可能出错，请交叉核实。</li>"
             "<li>最终的决策权和后果，属于考生和家庭。</li></ol></div>")
    sec("数据来源与声明", body)

    toc = "".join(f"<div><span>{i:02d}</span><span>{E(t)}</span></div>" for i, t, _ in secs)
    cover = (f'<div class="cover"><div class="band"><div class="kicker">知 衢 · 志 愿 填 报 决 策 报 告</div>'
             f'<h1>{E(m.get("title", "志愿填报决策报告"))}</h1><div class="sub">{E(m.get("subtitle", ""))}</div>'
             '<div class="motto">知其所往，方行其衢。</div></div>'
             '<div class="meta">'
             + "".join(f"<div><b>{E(a)}</b><span>{E(str(b))}</span></div>" for a, b in [
                 ("考生", m.get("candidate", "–")), ("省份 · 科类", f'{m.get("province", "–")} · {m.get("category", "–")}'),
                 ("批次", m.get("batch", "–")), ("分数", m.get("score", "–")), ("全省位次", m.get("rank", "–")), ("报告日期", m.get("date", "–"))])
             + "</div>"
             + (f'<div class="verdict"><b>一句话结论</b><p>{E(s.get("headline", ""))}</p></div>' if s.get("headline") else "")
             + f'<div class="verdict" style="background:transparent;border-left-color:var(--rule2)"><b>目录</b><div class="toc">{toc}</div></div>'
             + '<div class="foot">本报告由「知衢」生成，供考生与家庭决策参考。数据来源、假设与局限见"方法与假设"和"数据来源与声明"两节。</div></div>')
    runhead = f'{m.get("candidate", "")} · {m.get("province", "")} {m.get("category", "")}'.replace('"', "")
    css = CSS.replace("__RUNHEAD__", runhead)
    if missing:
        print("提醒：以下各节没有内容，也没有在 omitted 中写明原因：" + "、".join(dict.fromkeys(missing)), file=sys.stderr)
    return f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>{E(m.get("title", "志愿填报决策报告"))}</title><style>{css}</style></head><body>{cover}{"".join(b for _, _, b in secs)}</body></html>'


def find_browser():
    cands = [os.environ.get("CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "/Applications/Chromium.app/Contents/MacOS/Chromium",
             shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("msedge"),
             r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    return next((c for c in cands if c and os.path.exists(c)), None)


def main():
    ap = argparse.ArgumentParser(description="知衢 · 生成志愿填报决策报告（PDF/HTML）")
    ap.add_argument("report", help="报告内容 JSON（字段见 references/report-guide.md）")
    ap.add_argument("--opt", help="optimize.py --json 的输出")
    ap.add_argument("--out", required=True, help="输出文件，.pdf 或 .html")
    a = ap.parse_args()
    rep = json.load(open(a.report, encoding="utf-8"))
    opt = json.load(open(a.opt, encoding="utf-8")) if a.opt else None
    if opt:
        errors = check_report(rep, opt)
        if errors:
            ap.error("报告数字核验失败：" + "；".join(errors))
    doc = build(rep, opt)
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


if __name__ == "__main__":
    main()
