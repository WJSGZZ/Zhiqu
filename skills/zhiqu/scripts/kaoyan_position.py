#!/usr/bin/env python3
"""考研择校：把本人同科目完整模考放进各候选的往年复试线与拟录取初试分布里，给出分数位置和建议档。

用法：python3 kaoyan_position.py 输入.json [--json]
输入：{"mock": {"subjects": ["政治","英语一","数学一","408"], "total": 372,
                 "singles": {"政治": 68, "英语一": 64, "数学一": 112, "408": 128}, "complete": true},
       "programs": [{"id": "P1", "name": "南航 0854", "subjects": [...同上...],
                     "years": {"2026": {"retest": {"total": 330, "singles": {"政治": 50, ...}},
                                        "admitted": {"n": 86, "min": 341, "q1": 360, "median": 371, "q3": 385, "max": 421}}}}]}

方法依据见 skills/zhiqu-grad/references/kaoyan.md「择校」：
- 资格与可比性先行：科目不同、模考不完整时不定档，只写原因；
- 单科低于最近一年复试单科线 → 冒险（单科风险），不看总分；
- 参考年份（最近两年有分布的年份）里任一年拟录取人数 n<5 → 不定档（样本太少）；
- 最近两年都 ≥ 录取者中位数 → 相对稳妥（按分数位置）；≥ 最近一年下四分位 → 够一够；否则冒险；
- 参考年份里有 5≤n<10 → 最高只到“够一够”，并注明“样本小，只作定性”。
不定档时 untiered_reason 取枚举值：科目不同、分布缺失、样本太少（“口径不一致”由调用方按方向/专项判断后填写）。
这里给的是“按分数位置的建议档”，不是个人上岸概率；最终档还要看名额口径、复试准备和年度变化，在 judgment.json 里定。
"""
import argparse
import json
import math
import sys


def distribution_issues(admitted):
    """缺失和无效摘要都不补值，也不把已知不完整年份当作没有该年。"""
    if not isinstance(admitted, dict):
        return ['分布不是统计表']
    labels = {'n': '人数', 'min': '最低分', 'q1': '下四分位',
              'median': '中位数', 'q3': '上四分位', 'max': '最高分'}
    issues = []
    for key, label in labels.items():
        v = admitted.get(key)
        try:
            valid = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
        except OverflowError:
            valid = False
        if key == 'n':
            valid = valid and v >= 1 and int(v) == v
        if not valid:
            issues.append(label + '缺失或无效')
    if not issues:
        values = [admitted[k] for k in ('min', 'q1', 'median', 'q3', 'max')]
        if values != sorted(values):
            issues.append('分位数顺序无效')
    return issues


def position(total, admitted):
    """分数在录取者分布里的位置，用大白话描述。"""
    if total < admitted['min']:
        return f"低于录取最低分 {admitted['min']:g}"
    if total < admitted['q1']:
        return f"在最低分与下四分位 {admitted['q1']:g} 之间"
    if total < admitted['median']:
        return f"在下四分位与中位数 {admitted['median']:g} 之间"
    if total < admitted['q3']:
        return f"在中位数与上四分位 {admitted['q3']:g} 之间"
    return f"高于上四分位 {admitted['q3']:g}"


def place(mock, program):
    years = sorted(program.get('years', {}), reverse=True)
    out = {'id': program['id'], 'name': program['name'], 'tier': None, 'untiered_reason': None, 'reasons': [], 'positions': {}, 'gaps': {}}
    if not mock.get('complete'):
        out['reasons'].append('没有完整模考，不定档；只列院校之间的官方资料差异')
        return out
    if not program.get('subjects'):
        has_dist = any((program.get('years', {})[y] or {}).get('admitted') for y in years)
        out['untiered_reason'] = '科目不同' if has_dist else '分布缺失'
        out['reasons'].append('当届初试科目未取到' + ('，不能确认和模考同卷' if has_dist else '，也没有录取者分布，只有复试线') + '，不定档')
        return out
    if list(program.get('subjects', [])) != list(mock.get('subjects', [])):
        out['untiered_reason'] = '科目不同'
        out['reasons'].append('初试科目和模考不同（' + ('、'.join(program.get('subjects', [])) or '科目未取到') + '），分数不能直接对照，不定档')
        return out
    if not years:
        out['untiered_reason'] = '分布缺失'
        out['reasons'].append('没有取到往年复试线或拟录取分布，不定档')
        return out
    latest = program['years'][years[0]]
    retest = latest.get('retest') or {}
    weak = [f"{s} {mock['singles'][s]:g}（{years[0]} 年单科线 {line:g}）"
            for s, line in (retest.get('singles') or {}).items() if s in mock.get('singles', {}) and mock['singles'][s] < line]
    adm_years = []
    issues = {}
    for y in years[:2]:
        adm = program['years'][y].get('admitted')
        if adm is not None:
            adm_years.append(y)
            missing = distribution_issues(adm)
            if missing:
                issues[y] = missing
            else:
                out['positions'][y] = position(mock['total'], adm)
                out['gaps'][y] = {k: round(mock['total'] - adm[k], 1) for k in ('min', 'q1', 'median', 'q3')}
        line = (program['years'][y].get('retest') or {}).get('total')
        if line is not None:
            out['gaps'].setdefault(y, {})['retest_total'] = round(mock['total'] - line, 1)
    if weak:
        out['tier'] = '冒险'
        out['reasons'].append('单科低于复试单科线：' + '；'.join(weak))
        return out
    if not adm_years:
        out['untiered_reason'] = '分布缺失'
        line = retest.get('total')
        out['reasons'].append('只有复试线、没有拟录取分布：' + (f'总分比 {years[0]} 年复试线高 {mock["total"] - line:g} 分' if line is not None else '复试线也未取到') + '；只作参照，不定档')
        return out
    if issues:
        out['untiered_reason'] = '分布缺失'
        out['reasons'].extend(f'{y} 年拟录取分布：' + '、'.join(gaps) + '；不填补统计值，不定档'
                              for y, gaps in issues.items())
        return out
    sizes = {y: program['years'][y]['admitted'].get('n') for y in adm_years}
    tiny = [y for y, n in sizes.items() if n is not None and n < 5]
    if tiny:
        out['untiered_reason'] = '样本太少'
        out['reasons'].append('、'.join(f'{y} 年只录取 {sizes[y]:g} 人' for y in tiny) + '，样本太少，不定档')
        return out
    small = [y for y, n in sizes.items() if n is not None and n < 10]
    latest_adm = program['years'][adm_years[0]]['admitted']
    if all(mock['total'] >= program['years'][y]['admitted']['median'] for y in adm_years) and len(adm_years) == 2:
        out['tier'] = '相对稳妥'
        out['reasons'].append('最近两年都不低于录取者中位数')
    elif mock['total'] >= latest_adm['q1']:
        out['tier'] = '够一够'
        out['reasons'].append(f'不低于 {adm_years[0]} 年录取者下四分位' + ('' if len(adm_years) == 2 else '（只有一年分布，不给“相对稳妥”）'))
    else:
        out['tier'] = '冒险'
        out['reasons'].append(f'低于 {adm_years[0]} 年录取者下四分位')
    if small:
        if out['tier'] == '相对稳妥':
            out['tier'] = '够一够'
            out['reasons'].append('按位置可到“相对稳妥”，但样本小，最高只给“够一够”')
        out['reasons'].append('、'.join(f'{y} 年只录取 {sizes[y]:g} 人' for y in small) + '，样本小，只作定性')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    data = json.load(open(a.input, encoding='utf-8'))
    rows = [place(data['mock'], p) for p in data['programs']]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    for r in rows:
        print(f"{r['name']}：{r['tier'] or '不定档'}；" + '；'.join(r['reasons'] + [f'{y} 年{v}' for y, v in r['positions'].items()]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
