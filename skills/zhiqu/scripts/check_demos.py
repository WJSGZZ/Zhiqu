#!/usr/bin/env python3
"""Validate the three fictional 2027 planning demos and reproduce their budgets.

Run from any directory. --write updates calculations.json from explicit scenario
assumptions; without it saved outputs must match. No admission model is changed.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
DEMO_PATHS = (
    SKILLS / 'zhiqu/examples/demo_2027_gaokao',
    SKILLS / 'zhiqu-grad/examples/demo_2027',
    SKILLS / 'zhiqu-career/examples/demo_2027',
)


def age_on(birthday, when):
    birth = date.fromisoformat(birthday[:10])
    day = date.fromisoformat(when)
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def calculate(case):
    b = case['budget']
    result = {'all_money_values_cny': True, 'scenario_only': True,
              'age_at_decision': age_on(case['birth_datetime'], case['decision_date']),
              'age_at_target': age_on(case['birth_datetime'], case['target_date'])}
    if case['kind'] in ('gaokao', 'grad'):
        annual = b['annual_tuition_assumption'] + b['annual_housing_assumption'] + b['monthly_living_assumption'] * b['living_months']
        result.update(annual_cost=annual, annual_margin=b['annual_limit'] - annual,
                      annual_cost_if_living_plus_200=annual + 200 * b['living_months'],
                      annual_margin_if_living_plus_200=b['annual_limit'] - annual - 200 * b['living_months'])
        if case['kind'] == 'grad':
            result['three_year_cost_assumption'] = annual * 3
    else:
        expenses = b['monthly_housing_assumption'] + b['monthly_other_expenses_assumption']
        result.update(monthly_expenses=expenses,
                      monthly_remaining=b['take_home_assumption'] - expenses,
                      monthly_remaining_if_housing_plus_600=b['take_home_assumption'] - expenses - 600)
    return result


def validate(case, chart, profile, report):
    if case.get('stage') != {'gaokao': 'pre_score', 'grad': 'pre_exam', 'career': 'pre_offer'}.get(case.get('kind')):
        raise ValueError('wrong decision stage for demo kind')
    if case.get('fictional') is not True:
        raise ValueError('demo must be explicitly fictional')
    if not case['education_entry'] < case['decision_date'] < case['graduation_date'] <= case['target_date']:
        raise ValueError('education / decision / graduation / target dates inconsistent')
    if case['target_date'][:4] != '2027':
        raise ValueError('2027 cohort required')
    if any(case.get(key) is not None for key in ('personal_success_probability', 'official_2027_score', 'official_offer')):
        raise ValueError('planning stage cannot assert a future score, personal probability or offer')
    if chart['input']['birth_datetime_local'] != case['birth_datetime']:
        raise ValueError('birth input does not match case')
    if chart['candidate_count'] != 1 or chart['warnings']:
        raise ValueError('these demos require a stable, explicitly calculated chart')
    c = chart['candidates'][0]
    if c['pillars_text'] != case['pillars_text'] or c['luck'][0]['start_datetime_birth_zone'] != case['luck_start']:
        raise ValueError('chart structure or precise luck start mismatch')
    if age_on(case['birth_datetime'], case['education_entry']) < 14:
        raise ValueError('implausible education timeline requires explicit explanation')
    prefixes = {'gaokao': '【高考志愿 · 自我盘点】', 'grad': '【读研 · 自我盘点】', 'career': '【求职 · 自我盘点】'}
    if not profile.startswith(prefixes[case['kind']]) or case['person'] not in profile:
        raise ValueError('wrong profile or skill route')
    numbers = re.findall(r'^## (\d{2}) ', report, flags=re.M)
    if numbers != [f'{i:02d}' for i in range(1, 13)]:
        raise ValueError('report needs exactly the ordered 12 sections')
    for item in case['evidence']:
        if item['status'] != 'pending' or not item['unresolved']:
            raise ValueError('the examples have unresolved annual eligibility; do not silently certify it')
        if not item['source'].startswith('https://') or not item['verified_scope']:
            raise ValueError('official reference and scope required')


def check(path, write=False):
    case = json.loads((path / 'case.json').read_text(encoding='utf-8'))
    chart = json.loads((path / 'birth_chart.json').read_text(encoding='utf-8'))
    fresh = json.loads(subprocess.check_output([
        sys.executable, str(SKILLS / 'bazi/scripts/calculate_bazi.py'), str(path / 'birth_input.json')], text=True))
    # tzdb version labels vary by installation; compare calculations, not runtime labels.
    def without_runtime_labels(value):
        if isinstance(value, dict):
            return {k: without_runtime_labels(v) for k, v in value.items() if k != 'timezone_database'}
        if isinstance(value, list):
            return [without_runtime_labels(v) for v in value]
        return value
    if without_runtime_labels(fresh) != without_runtime_labels(chart):
        raise ValueError(f'{path}: saved chart differs from actual recalculation')
    validate(case, chart, (path / 'profile.txt').read_text(encoding='utf-8'), (path / 'report.md').read_text(encoding='utf-8'))
    result = calculate(case)
    out = path / 'calculations.json'
    if write:
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    elif json.loads(out.read_text(encoding='utf-8')) != result:
        raise ValueError(f'{path}: saved budget differs from scenario inputs')
    return case['person'], result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='regenerate explicit scenario budget outputs')
    args = parser.parse_args()
    for path in DEMO_PATHS:
        name, result = check(path, args.write)
        print(name + ': ' + json.dumps(result, ensure_ascii=False))
    print('3 fictional demos: birth recalculation, timeline, evidence scope and budget outputs passed.')


if __name__ == '__main__':
    main()
