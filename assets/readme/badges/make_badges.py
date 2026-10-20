#!/usr/bin/env python3
"""生成 README 顶部的标签（SVG）。改颜色、文字或新增标签都在这里改，再运行一次。

样式与问卷、报告同一套品牌色：扁平、无渐变阴影；“填问卷”是唯一的动作，用黛绿实底，
其余是纸色底、细边框的信息标签。GitHub 用 <img> 显示 SVG，不能加载网页字体，
所以字体只写系统字体，宽度按字符估算并留足余量。
"""
from pathlib import Path
from xml.sax.saxutils import escape

INK, MUTED, GREEN, PAPER, RULE = '#222A26', '#6E776E', '#21473E', '#F4EFE2', '#CFC7B2'
FONT = "-apple-system, 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', 'Segoe UI', sans-serif"
H, SIZE, PAD, GAP = 30, 13, 12, 9


def width(text, size=SIZE):
    return sum(size if ord(c) > 0x2E80 else size * 0.56 for c in text)


def chip(label, value):
    """信息标签：小号灰字标签 + 细竖线 + 墨色值。"""
    lw, vw = width(label, SIZE - 1), width(value)
    total = PAD + lw + GAP + 1 + GAP + vw + PAD
    x_rule = PAD + lw + GAP
    return total, (
        f'<rect x=".5" y=".5" width="{total - 1:.1f}" height="{H - 1}" rx="{H / 2 - .5}" fill="{PAPER}" stroke="{RULE}"/>'
        f'<text x="{PAD}" y="{H / 2 + 4.6}" fill="{MUTED}" font-size="{SIZE - 1}">{escape(label)}</text>'
        f'<rect x="{x_rule:.1f}" y="9" width="1" height="{H - 18}" fill="{RULE}"/>'
        f'<text x="{x_rule + 1 + GAP:.1f}" y="{H / 2 + 4.6}" fill="{INK}" font-size="{SIZE}" font-weight="600">{escape(value)}</text>')


def button(text):
    """动作按钮：黛绿实底，浅色字，右侧细箭头。"""
    tw = width(text)
    total = PAD + 4 + tw + 8 + 7 + PAD + 2
    ax = PAD + 4 + tw + 8
    return total, (
        f'<rect width="{total:.1f}" height="{H}" rx="{H / 2}" fill="{GREEN}"/>'
        f'<text x="{PAD + 4}" y="{H / 2 + 4.6}" fill="#F4EFE2" font-size="{SIZE}" font-weight="600">{escape(text)}</text>'
        f'<path d="M{ax:.1f} 10.5 L{ax + 4.5:.1f} 15 L{ax:.1f} 19.5" fill="none" stroke="#F4EFE2" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>')


BADGES = {
    'questionnaire': ('在线填问卷', button('在线填问卷')),
    'python': ('Python 3.10+', chip('Python', '3.10+')),
    'agents': ('支持 Claude Code · Codex', chip('支持', 'Claude Code · Codex')),
    'license': ('MIT 许可', chip('许可', 'MIT')),
}

out = Path(__file__).resolve().parent
for name, (title, (w, body)) in BADGES.items():
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{H}" viewBox="0 0 {w:.1f} {H}" role="img" aria-label="{escape(title)}">'
           f'<title>{escape(title)}</title><g font-family="{FONT}">{body}</g></svg>\n')
    (out / f'{name}.svg').write_text(svg, encoding='utf-8')
    print(name, round(w))
