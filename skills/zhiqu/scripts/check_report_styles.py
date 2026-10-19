#!/usr/bin/env python3
"""Compare generated reports against the unique shared print design; no PDF generation."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import report


def normalized_css(css):
    """Running names and report types vary; all other CSS must be identical."""
    css = re.sub(r'(@top-(?:left|right)\s*\{\s*content:\s*)"(?:\\.|[^"\\])*"', r'\1"__HEADER__"', css)
    return re.sub(r'\s+', ' ', css).strip()


class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.classes = set()
        self.sections = []
        self.svg_count = 0
        self.core_lists = []
        self.in_core = False
        self.core_depth = 0
        self.core_bullets = 0
        self.core_heading = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        self.classes.update(classes)
        if tag == 'section' and attrs.get('data-section', '').isdigit():
            self.sections.append(int(attrs['data-section']))
        if tag == 'svg':
            self.svg_count += 1
        if 'core-conclusions' in classes:
            self.in_core = True
            self.core_depth = 1
        elif self.in_core:
            if tag == 'div': self.core_depth += 1
            if tag in ('ol', 'ul'): self.core_lists.append(tag)
            if tag == 'li': self.core_bullets += 1
            if tag in ('strong', 'b'): self.core_heading += 1

    def handle_endtag(self, tag):
        if self.in_core and tag == 'div':
            self.core_depth -= 1
            if not self.core_depth: self.in_core = False


def inspect_html(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    errors = []
    css_parts = re.findall(r'<style[^>]*>(.*?)</style>', text, re.S)
    css = '\n'.join(css_parts)
    shared = normalized_css(report.CSS)
    if normalized_css(css) != shared:
        errors.append('样式不是当前 report.py 的唯一共用样式')
    structure = Structure(); structure.feed(text)
    for cls, label in [('cover','封面'), ('meta','六格元数据'), ('cover-toc','封面目录'),
                       ('core-conclusions','核心结论'), ('kpis','摘要数字卡')]:
        if cls not in structure.classes: errors.append('缺少' + label)
    if structure.sections != list(range(1, 13)):
        errors.append('正文目录不是完整的 01—12 节')
    if structure.core_lists != ['ul'] or structure.core_bullets != structure.core_heading:
        errors.append('核心结论须为唯一圆点列表，每项有粗体短标题')
    for token, label in [('__TOPLEFT__','页眉左'), ('__RUNHEAD__','页眉右')]:
        if token in css: errors.append(label+'仍有未替换占位')
    for token, label in [('counter(pages)','页码总数'), ('仅供参考 · 以当年官方文件为准','页脚声明'),
                         ('tbody td','表格'), ('.box.key','提示框'), ('svg.chart','图表')]:
        if token not in css: errors.append('缺少'+label+'共用样式')
    return {'path': str(path), 'passed': not errors, 'errors': errors,
            'style_sha256': hashlib.sha256(normalized_css(css).encode()).hexdigest(),
            'checks': ['封面', '目录', '摘要核心结论', '页眉页脚', '表格', '提示框', '图表样式'],
            'charts': structure.svg_count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    paths = args.paths or sorted(root.glob('skills/zhiqu*/examples/**/report.html'))
    result = {'reports': [inspect_html(path) for path in paths]}
    result['passed'] = bool(paths) and all(row['passed'] for row in result['reports'])
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out: args.out.write_text(encoded + '\n', encoding='utf-8')
    print(encoded)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
