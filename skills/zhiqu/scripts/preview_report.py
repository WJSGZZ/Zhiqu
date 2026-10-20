#!/usr/bin/env python3
"""把报告每一页缩成缩略图拼成速览图，改完报告后看一眼版面。

用法：python3 preview_report.py [报告.pdf ...] [--out 目录]
不给 PDF 时，取工作区里相对 main 有改动的 report.pdf。
每张速览图 8 页（4×2），存到 .cache/preview/（不进仓库），打印路径。
自动检查只能抓到已知的几类错（check_layout.py、check_report_styles.py）；
数字被套错样式、图表配色不一、整页只剩一行这类问题要靠眼睛看，这张图就是给眼睛看的。
需要 PyMuPDF（pip install pymupdf）。
"""
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def changed_reports():
    out = subprocess.run(['git', 'diff', '--name-only', 'main', '--', '*report.pdf'],
                         cwd=ROOT, capture_output=True, text=True).stdout.split()
    out += subprocess.run(['git', 'ls-files', '--others', '--exclude-standard', '--', '*report.pdf'],
                          cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [ROOT / p for p in dict.fromkeys(out)]


def preview(pdf, out_dir, per=8, cols=4, dpi=48):
    import pymupdf
    doc = pymupdf.open(pdf)
    w, h = doc[0].rect.width, doc[0].rect.height
    name = Path(pdf).resolve().parent.name
    paths = []
    for start in range(0, len(doc), per):
        pages = range(start, min(start + per, len(doc)))
        rows = (len(pages) + cols - 1) // cols
        sheet = pymupdf.open()
        page = sheet.new_page(width=w * cols, height=h * rows)
        for k, i in enumerate(pages):
            x, y = (k % cols) * w, (k // cols) * h
            page.show_pdf_page(pymupdf.Rect(x, y, x + w, y + h), doc, i)
            page.draw_rect(pymupdf.Rect(x, y, x + w, y + h), color=(.75, .73, .66), width=1)
        path = out_dir / f'{name}_{start // per + 1}.png'
        page.get_pixmap(dpi=dpi).save(path)
        paths.append(path)
    return len(doc), paths


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('pdfs', nargs='*', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT / '.cache' / 'preview')
    args = parser.parse_args()
    pdfs = args.pdfs or changed_reports()
    if not pdfs:
        print('没有改动过的报告；可以直接给出 PDF 路径。')
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for pdf in pdfs:
        n, paths = preview(pdf, args.out)
        print(f'{pdf}（{n} 页）')
        for p in paths:
            print('  ', p)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
