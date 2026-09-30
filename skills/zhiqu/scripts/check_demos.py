#!/usr/bin/env python3
"""Validate the three fictional 2027 planning demos and reproduce their numbers.

Run from any directory. --write updates calculations.json from explicit scenario
assumptions; without it saved outputs must match. Each demo also has a clearly
labelled hypothetical follow-up stage (假想出分后 / 假想初试成绩 / 假想offer):
the gaokao optimizer runs are re-executed and must reproduce the saved results,
offer take-home pay is recomputed from explicit tax and contribution rules, and
the grad score reference must carry official statistics. No model is changed.
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


# 居民个人综合所得年度税率表（应纳税所得额上限, 税率, 速算扣除数）
TAX_BRACKETS = ((36000, 0.03, 0), (144000, 0.10, 2520), (300000, 0.20, 16920),
                (420000, 0.25, 31920), (660000, 0.30, 52920), (960000, 0.35, 85920),
                (float('inf'), 0.45, 181920))


def annual_tax(taxable):
    if taxable <= 0:
        return 0.0
    for cap, rate, quick in TAX_BRACKETS:
        if taxable <= cap:
            return taxable * rate - quick


def offer_numbers(offer, f):
    """一个假想 offer 的到手收入、时薪与月结余；公积金只按缴存额单列，是否计为收入由本人确认。"""
    gross = offer['monthly_gross'] * offer['months']
    ss = offer['ss_base'] * f['ss_personal_rate_assumption'] * 12
    hf = offer['ss_base'] * offer['hf_rate'] * 12
    tax = annual_tax(gross - 60000 - ss - hf)
    take_home = gross - ss - hf - tax
    hours = f['standard_hours_per_year'] + offer['extra_hours_per_month'] * 12
    monthly = take_home / 12
    return {'name': offer['name'], 'annual_gross': round(gross), 'personal_social_insurance': round(ss),
            'personal_housing_fund': round(hf), 'housing_fund_account_total': round(hf * 2), 'tax': round(tax),
            'annual_take_home_cash': round(take_home), 'monthly_take_home_cash': round(monthly),
            'hours_per_year': hours, 'hourly_cash': round(take_home / hours, 1),
            'hourly_if_housing_fund_counted': round((take_home + hf * 2) / hours, 1),
            'monthly_remaining_cash': round(monthly - offer['monthly_rent'] - offer['monthly_other']),
            'above_local_minimum_wage': offer['monthly_gross'] >= offer['minimum_wage_tier']}


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
        f = case.get('hypothetical_followup')
        if f:
            result['hypothetical_offers'] = [offer_numbers(o, f) for o in f['offers']]
    return result


def check_followup(path, case):
    """复现假想后续阶段：高考重跑优化器，读研核对官方统计齐全。"""
    f = case.get('hypothetical_followup')
    if not f or '假想' not in f.get('label', ''):
        raise ValueError(f'{path}: every demo needs a clearly labelled hypothetical follow-up stage')
    if case['kind'] == 'gaokao':
        for cand, saved in ((f['candidates'], f['result']),
                            (f['parent_weights_candidates'], f['parent_weights_result'])):
            tmp = path / '.check_tmp.json'
            subprocess.run([sys.executable, str(SKILLS / 'zhiqu/scripts/optimize.py'), str(path / cand),
                            *f['optimize_args'], '--json', str(tmp)], capture_output=True, text=True, check=True)
            fresh = json.loads(tmp.read_text(encoding='utf-8'))
            tmp.unlink()
            old = json.loads((path / saved).read_text(encoding='utf-8'))
            if [x['name'] for x in fresh['list']] != [x['name'] for x in old['list']] or \
                    abs(fresh['expected_utility'] - old['expected_utility']) > 0.05:
                raise ValueError(f'{path}: {saved} is not reproduced by optimize.py with the recorded arguments')
    elif case['kind'] == 'grad':
        stats = f['official_stats']
        if not stats or not all({'n', 'min', 'median', 'max'} <= set(v) for v in stats.values()):
            raise ValueError(f'{path}: grad follow-up needs official distribution statistics')
        if not all(src.startswith('https://') for src in f['sources']):
            raise ValueError(f'{path}: official sources required')


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
    check_followup(path, case)
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
    print('3 fictional demos: birth recalculation, timeline, evidence scope, budgets and hypothetical follow-ups passed.')


if __name__ == '__main__':
    main()
