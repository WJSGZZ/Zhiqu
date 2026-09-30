#!/usr/bin/env python3
"""核验报告元数据、显式数字声明及 HTML 志愿表，不猜测自然语言的数字含义。"""
import argparse
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path


def at(obj, path):
    for key in path.split('.'):
        obj = obj[int(key)] if isinstance(obj, list) else obj[key]
    return obj


def check_report(rep, result, html=None):
    errors = []
    params = result['params']
    for key in ('rank', 'slots'):
        value = rep.get('meta', {}).get(key)
        if value is not None:
            number = re.fullmatch(r'\s*(\d+(?:,\d{3})*(?:\.\d+)?)(?:[（(][^）)]*[）)])?\s*', str(value))
            if not number or float(number.group(1).replace(',', '')) != float(params[key]):
                errors.append(f'meta.{key} 与 result.params.{key} 不一致或格式无效')
    try:
        multiplier = float(rep.get('stress_mult', 2))
        if not math.isfinite(multiplier) or multiplier != float(params.get('stress', 2)):
            errors.append('stress_mult 与 result.params.stress 不一致')
    except (TypeError, ValueError):
        errors.append('stress_mult 必须为有效数字')
    for i, claim in enumerate(rep.get('numeric_claims', [])):
        try:
            text = str(at(rep, claim['report_path']))
            numbers = re.findall(r'-?\d+(?:,\d{3})*(?:\.\d+)?', text)
            value = float(numbers[claim.get('number_index', 0)].replace(',', ''))
            expected = float(at(result, claim['result_path'])) * claim.get('scale', 1)
            tolerance = float(claim.get('tolerance', 0.05))
            if tolerance < 0 or not all(math.isfinite(x) for x in (value, expected, tolerance)):
                raise ValueError('数字及容差须为有限值，容差不可为负')
            if abs(value - expected) > tolerance + 1e-10:
                errors.append(f'numeric_claims[{i}] {claim["report_path"]}: {value} ≠ {expected:g}（容差 {tolerance:g}）')
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            errors.append(f'numeric_claims[{i}] 无效: {exc}')
    if html is not None:
        parser = Tables()
        parser.feed(html)
        tables = [t for t in parser.tables if t and t[0] == ['序', '志愿', '类型', '偏好', '单独过线', '最终录取', '预测位次', '说明']]
        if len(tables) != 1:
            errors.append('HTML 须有且仅有一张完整志愿表')
        else:
            rows = tables[0][1:]
            if len(rows) != len(result['list']):
                errors.append('HTML 志愿行数与 result 不一致')
            for i, (cells, item) in enumerate(zip(rows, result['list'])):
                expected = [str(item['order']), item['tag'], f'{item["utility"]:g}',
                            f'{100*item["p_clear"]:.{1 if 0 < item["p_clear"] < 0.01 else 0}f}%', f'{100*item["p_land"]:.1f}%', f'{item["expected_cut_rank"]:,}']
                actual = [cells[j] for j in (0, 2, 3, 4, 5, 6)] if len(cells) == 8 else []
                if actual != expected or not cells[1].startswith(item['name']):
                    errors.append(f'HTML 志愿表第 {i+1} 行与 result 不一致')
        metrics = Metrics()
        metrics.feed(html)
        items = result['list']
        if items:
            likely = max(items, key=lambda item: item['p_land'])
            name, probability = likely['name'], likely['p_land']
            if likely.get('majors'):
                major = max(likely['majors'], key=lambda major: major['p'])
                name, probability = name.split('·')[0] + '·' + major['name'], major['p']
            good = sum(sum(m['p'] for m in x['majors'] if m['utility'] >= 70) if x.get('majors') else (x['p_land'] - x.get('p_adjusted', 0) if x['utility'] >= 70 else 0) for x in items)
            sims = params.get('sims', 4000)
            fall = lambda p: f'< {100/sims:.2g}%' if p == 0 else percentage(p, 1)
            expected = [str(len(items)), f'本批次可填 {rep.get("meta", {}).get("slots", "–")} 个', name, '概率约 ' + percentage(probability), percentage(good), '100 分 = 候选中你最想去的', fall(result['p_fall']), '录取线整体大波动时 ' + fall(result['stress']['p_fall'])]
            if metrics.values != expected:
                errors.append('HTML 摘要指标与 result 不一致')
    return errors


def percentage(value, decimals=0):
    if decimals == 0 and 0 < value < 0.01:
        decimals = 1
    return f'{100*value:.{decimals}f}%'


class Metrics(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth, self.cell, self.values = 0, None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'div' and (self.depth or dict(attrs).get('class') == 'kpis'):
            self.depth += 1
        elif self.depth and tag in ('span', 'em'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.depth and tag in ('span', 'em') and self.cell is not None:
            self.values.append(''.join(self.cell).strip())
            self.cell = None
        elif self.depth and tag == 'div':
            self.depth -= 1


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table = []
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('report')
    ap.add_argument('--opt', required=True)
    ap.add_argument('--html', help='report.py 生成的 HTML，核验其中的志愿表')
    args = ap.parse_args()
    rep = json.loads(Path(args.report).read_text(encoding='utf-8'))
    result = json.loads(Path(args.opt).read_text(encoding='utf-8'))
    html = Path(args.html).read_text(encoding='utf-8') if args.html else None
    errors = check_report(rep, result, html)
    if errors:
        ap.exit(1, '\n'.join(errors) + '\n')
    print(f'核验通过：元数据、{len(rep.get("numeric_claims", []))} 条数字声明' + ('、HTML 摘要与志愿表' if html else ''))
    print('自然语言中未标注的数字及敏感性情景须人工核对；本工具不核验 PDF 排版。')


if __name__ == '__main__':
    main()
