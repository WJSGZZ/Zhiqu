#!/usr/bin/env python3
"""问卷版面自检：在真实浏览器里打开三份问卷，展开全部条件题与追问，
检查同一题内相邻控件是否贴在一起或重叠、选项是否挤出卡片、页面是否横向溢出。

用法：python3 skills/zhiqu/scripts/check_questionnaire.py [问卷.html ...]
需要 Python 包 playwright 和本机 Chrome（或 playwright 自带的 Chromium）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGES = ('gaokao.html', 'grad.html', 'career.html')
WIDTHS = (375, 780)
MIN_GAP = 8  # 同一题内上下相邻的两个控件至少留这么多像素

PROBE = r"""
(minGap) => {
  document.querySelectorAll('[hidden]').forEach(e => { if (e.closest('.q,[data-show-when],[data-hide-when],.section,.followup')) e.hidden = false; });
  document.querySelectorAll('.followup').forEach(e => e.classList.add('show'));
  const vis = e => { const s = getComputedStyle(e); const r = e.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.height > 0; };
  const name = e => (e.closest('[data-profile-id]')?.getAttribute('data-profile-id')) || (e.closest('.q')?.querySelector('.q-label')?.textContent.trim().slice(0, 24)) || e.tagName;
  const out = [];
  const docW = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > docW + 1) out.push('页面横向溢出 ' + (document.documentElement.scrollWidth - docW) + 'px');
  document.querySelectorAll('.q').forEach(q => {
    const kids = [...q.children].filter(vis);
    for (let i = 1; i < kids.length; i++) {
      const a = kids[i - 1].getBoundingClientRect(), b = kids[i].getBoundingClientRect();
      const sideBySide = b.top < a.bottom - 2 && (b.left >= a.right - 1 || a.left >= b.right - 1);
      if (sideBySide) continue;
      const gap = Math.round(b.top - a.bottom);
      const isLabel = kids[i - 1].matches('.minilabel,label[for],.q-label');
      if (gap < (isLabel ? 4 : minGap)) out.push(name(q) + '：' + kids[i - 1].className + kids[i - 1].tagName.toLowerCase() + ' 与下一项间距 ' + gap + 'px');
    }
    const card = q.closest('.card');
    if (card) {
      const c = card.getBoundingClientRect();
      q.querySelectorAll('.opt .box, input, textarea, select').forEach(el => {
        if (!vis(el)) return;
        const r = el.getBoundingClientRect();
        if (r.right > c.right + 1) out.push(name(q) + '：控件超出卡片 ' + Math.round(r.right - c.right) + 'px');
      });
    }
  });
  return [...new Set(out)];
}
"""


def check(paths):
    from playwright.sync_api import sync_playwright
    problems = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='chrome')
        except Exception:
            browser = p.chromium.launch()
        for path in paths:
            for width in WIDTHS:
                page = browser.new_page(viewport={'width': width, 'height': 900})
                page.goto(Path(path).resolve().as_uri())
                for msg in page.evaluate(PROBE, MIN_GAP):
                    problems.append(f'{Path(path).name} @{width}px  {msg}')
                page.close()
        browser.close()
    return problems


def main():
    paths = sys.argv[1:] or [str(ROOT / f) for f in PAGES]
    problems = check(paths)
    for line in problems:
        print(line)
    print(f'合计：{len(problems)} 处版面问题' if problems else '问卷版面检查通过')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
