"""Recompute trusted registered planning algorithms and describe their arithmetic.

Only bundled algorithms run. JSON attachments never provide executable Python.
The saved result is compared after computing from source inputs, never used as an
input for registered calculations.
"""
import math
import re
from datetime import date

REF = re.compile(r'\{\{([kpec]):([^{}|]+?)(?:\|([^{}]+))?\}\}')


def pointer(obj, path):
    if not path: return obj
    if not path.startswith('/'): raise ValueError('JSON Pointer must start with /')
    for item in path[1:].split('/'):
        key = item.replace('~1', '/').replace('~0', '~')
        obj = obj[int(key)] if isinstance(obj, list) else obj[key]
    return obj


def walk(obj, path=''):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from walk(value, path + '/' + str(key).replace('~', '~0').replace('/', '~1'))
    elif isinstance(obj, (list, tuple)):
        for key, value in enumerate(obj): yield from walk(value, path + '/' + str(key))
    else: yield path, obj


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def _quantile(sorted_values, q):
    """含端点的线性插值（与 numpy 默认 linear 相同）：位置 = (n−1)·q。"""
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos); hi = math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


STATS = {'min': lambda v: v[0], 'max': lambda v: v[-1], 'median': lambda v: _quantile(v, .5),
         'q1': lambda v: _quantile(v, .25), 'q3': lambda v: _quantile(v, .75), 'count': len}
STAT_NAMES = {'min': '最低', 'max': '最高', 'median': '中位数', 'q1': '下四分位', 'q3': '上四分位', 'count': '个数'}


def _registered(case, profile, evidence):
    computed = {}; rows = []
    items = evidence.get('items', []) if isinstance(evidence, dict) and 'items' in evidence else evidence
    entries = {row['id']: row for row in items} if isinstance(items, list) else items

    def resolve(value, allow_list=False):
        if numeric(value): return value
        match = REF.fullmatch(str(value))
        if not match: raise ValueError('计算输入必须为数值或完整登记引用：' + str(value))
        kind, path, fmt = match.groups()
        if kind == 'e':
            eid, sep, subpath = path.partition('#')
            value = pointer(entries[eid], subpath if sep else '/value')
        else:
            value = pointer({'k': case, 'p': profile, 'c': computed}[kind], path)
        if allow_list and isinstance(value, list) and value and all(numeric(v) for v in value): return value
        if not numeric(value): raise ValueError('计算输入不是有限数值：' + str(value))
        return value

    def calculate(op, replacements=None):
        inputs = [(replacements or {}).get(v, v) for v in op['inputs']]
        algorithm = op['algorithm']
        if algorithm in STATS:
            # 匿名分数表（如拟录取初试总分，不含姓名编号）→ 分布统计；输入是一个数值列表或若干数值。
            raw = [resolve(v, allow_list=True) for v in inputs]
            values = [x for v in raw for x in (v if isinstance(v, list) else [v])]
            if not values: raise ValueError('计算输入为空')
            value = STATS[algorithm](sorted(values))
            # 说明按数据项命名（计算项自带 item_name、unit），不写死“分数”：同一算法也用于竞争比、工资等匿名列表。
            item = op.get('item_name') or '数值'; unit = f'（单位：{op["unit"]}）' if op.get('unit') else ''
            if algorithm == 'count': formula = f'数出 {len(values)} 个{item}'
            else:
                formula = f'{len(values)} 个{item}{unit}排序后取{STAT_NAMES[algorithm]}'
                if algorithm in ('q1', 'median', 'q3'): formula += '（四分位按含端点的线性插值）'
            if not numeric(value): raise ValueError('计算结果不是有限数值')
            return value, [len(values)], formula
        values = [resolve(v) for v in inputs]
        if not values: raise ValueError('计算输入为空')
        if algorithm == 'sum': value = sum(values); formula = ' + '.join(map(str, values))
        elif algorithm == 'product': value = math.prod(values); formula = ' × '.join(map(str, values))
        elif algorithm in ('difference', 'ratio'):
            if len(values) != 2: raise ValueError('差值或比值需要两个输入')
            value = values[0] - values[1] if algorithm == 'difference' else values[0] / values[1]
            formula = f'{values[0]} {"−" if algorithm == "difference" else "÷"} {values[1]}'
        else: raise ValueError('未登记的算法：' + str(algorithm))
        if op.get('rounding') is not None:
            if type(op['rounding']) is not int: raise ValueError('rounding须为整数')
            value = round(value, op['rounding']); formula += f'；四舍六入五成双取 {op["rounding"]} 位小数'
        if not numeric(value): raise ValueError('计算结果不是有限数值')
        return value, values, formula

    plan = case['calculation_plan']
    operations = {}
    for op in plan.get('operations', []):
        key = op['output']
        if key in computed or '/' in key: raise ValueError('计算输出重复或不是顶层键')
        value, inputs, formula = calculate(op)
        computed[key] = value; operations[key] = op
        rows.append(_row('/' + key, op.get('label', key), value, inputs, formula))
    if not operations: raise ValueError('缺已登记的计算操作')
    for scenario in plan.get('scenarios', []):
        op = operations[scenario['baseline_output']]
        changes = scenario['changed_inputs']
        if not changes or any(key not in op['inputs'] or resolve(key) == resolve(value) for key, value in changes.items()):
            raise ValueError('情景没有实际改变已登记输入')
        match = REF.fullmatch(scenario['output_ref'])
        if not match or match[1] != 'c' or not re.fullmatch('/[^/]+', match[2]):
            raise ValueError('情景输出须为顶层计算引用')
        key = match[2][1:]
        if key in computed: raise ValueError('情景输出重复')
        value, inputs, formula = calculate(op, changes)
        computed[key] = value
        rows.append(_row('/' + key, scenario.get('label') or scenario.get('why', key), value, inputs, formula))
    return computed, rows


def _row(path, label, value, inputs, formula):
    return {'path': path, 'label': label, 'value': value, 'inputs': inputs,
            'formula': formula, 'result': value, 'sections': ''}


def recompute(case, profile, evidence, calculations):
    """Return recomputed results; reject any missing/changed/extra result keys."""
    engine = case.get('calculation_plan', {}).get('engine')
    if engine == 'legacy_demo':
        from check_demos import calculate
        fresh = calculate(case)
    elif engine == 'registered_operations': fresh, _ = _registered(case, profile, evidence)
    else: raise ValueError('不支持的计算引擎：' + str(engine))
    if fresh != calculations or any(isinstance(pointer(calculations, path), bool) != isinstance(value, bool)
                                     for path, value in walk(fresh)):
        raise ValueError('保存的计算结果与登记输入、算法不一致')
    return fresh


def _budget_description(b, key):
    annual = b['annual_tuition'] + b['annual_housing'] + b['monthly_living_assumption'] * b['living_months']
    base = f'{b["annual_tuition"]} 学费 + {b["annual_housing"]} 住宿 + {b["monthly_living_assumption"]} 月生活费 × {b["living_months"]} 月'
    inputs = dict(b)
    formulas = {'annual_cost': base,
                'annual_margin': f'{b["annual_limit"]} − ({base})',
                'annual_cost_if_living_plus_200': base + f' + 200 × {b["living_months"]}',
                'annual_margin_if_living_plus_200': f'{b["annual_limit"]} − ({base}) − 200 × {b["living_months"]}',
                'total_cost_over_program': f'({base}) × {b.get("years", 1)}',
                'total_cost': f'({base}) × {b.get("years", 1)}'}
    return inputs, formulas[key]


def _offer_description(offer, followup, key):
    from check_demos import TAX_BRACKETS
    f = followup; o = offer
    gross = o['monthly_gross'] * o['months']
    base = min(max(o['monthly_gross'], f['ss_base_limits']['lower']), f['ss_base_limits']['upper'])
    ss = base * f['ss_personal_rate_assumption'] * 12
    hf = o['monthly_gross'] * o['hf_rate'] * 12
    taxable = max(0, gross - 60000 - ss - hf)
    cap, rate, quick = next((cap, rate, quick) for cap, rate, quick in TAX_BRACKETS if taxable <= cap)
    tax = 0 if taxable <= 0 else taxable * rate - quick
    cash = gross - ss - hf - tax
    hours = f['standard_hours_per_year'] + o['extra_hours_per_month'] * 12
    formulas = {
        'annual_gross': f'{o["monthly_gross"]} × {o["months"]}',
        'social_insurance_base': f'月薪 {o["monthly_gross"]}，不低于下限 {f["ss_base_limits"]["lower"]}、不高于上限 {f["ss_base_limits"]["upper"]}',
        'personal_social_insurance': f'{base} × {f["ss_personal_rate_assumption"]} × 12',
        'personal_housing_fund': f'{o["monthly_gross"]} × {o["hf_rate"]} × 12',
        'housing_fund_account_total': f'({o["monthly_gross"]} × {o["hf_rate"]} × 12) × 2（单位与个人等额情景）',
        'tax': f'max(0, {gross} − 60000 − {ss} − {hf}) = {taxable}；该档税额 = {taxable} × {rate} − {quick}' if taxable else f'{gross} − 60000 − {ss} − {hf} ≤ 0，税额为 0',
        'annual_take_home_cash': f'{gross} − {ss} − {hf} − {tax}',
        'monthly_take_home_cash': f'({gross} − {ss} − {hf} − {tax}) ÷ 12',
        'hours_per_year': f'{f["standard_hours_per_year"]} + {o["extra_hours_per_month"]} × 12',
        'hourly_cash': f'({gross} − {ss} − {hf} − {tax}) ÷ {hours}',
        'hourly_if_housing_fund_counted': f'({gross} − {ss} − {hf} − {tax} + {hf} × 2) ÷ {hours}',
        'monthly_remaining_cash': f'({gross} − {ss} − {hf} − {tax}) ÷ 12 − {o["monthly_rent"]} − {o["monthly_other"]}'}
    inputs = {'月薪': o['monthly_gross'], '发薪月数': o['months'], '社保基数上下限': f['ss_base_limits'],
              '个人社保比例': f['ss_personal_rate_assumption'], '个人公积金比例': o['hf_rate'],
              '基础年工时': f['standard_hours_per_year'], '额外月工时': o['extra_hours_per_month'],
              '月租金': o['monthly_rent'], '其他月支出': o['monthly_other']}
    precision = 1 if key in ('hourly_cash', 'hourly_if_housing_fund_counted') else 0
    formula = formulas[key]
    if key not in ('social_insurance_base', 'hours_per_year'):
        formula += f'；中间值不取整，最终四舍六入五成双取 {precision} 位小数'
    return inputs, formula


def _legacy_description(case, path):
    parts = [part.replace('~1', '/').replace('~0', '~') for part in path.lstrip('/').split('/')]; first = parts[0]; key = parts[-1]
    b = case['budget']; plan = case['calculation_plan']
    if first in ('age_at_decision', 'age_at_target'):
        when = case['decision_date' if first == 'age_at_decision' else 'target_date']
        birth = date.fromisoformat(case['birth_datetime'][:10]); target = date.fromisoformat(when)
        return {'出生日期': birth.isoformat(), '参照日期': when}, f'{target.year} − {birth.year} − 当年生日尚未到达时扣 1'
    if first.startswith('annual_') or first == 'total_cost_over_program': return _budget_description(b, first)
    if first in ('monthly_expenses', 'monthly_remaining', 'monthly_remaining_if_housing_plus_600'):
        expenses = f'{b["monthly_housing_assumption"]} + {b["monthly_other_expenses_assumption"]}'
        return dict(b), expenses if first == 'monthly_expenses' else f'{b["take_home_assumption"]} − ({expenses})' + (' − 600' if first.endswith('600') else '')
    if first == 'gdut_fee_reference':
        g = case['additional_scenarios'][first]
        normalized = dict(g, annual_tuition=g['official_tuition'], annual_housing=g['annual_housing_assumption'])
        return _budget_description(normalized, key)
    if first == 'gdut_2026_retest':
        g = case['additional_scenarios'][first]; prefix = 'initial' if key.startswith('initial') else 'retest'
        return {k: g[k] for k in (prefix+'_increment', prefix+'_max', prefix+'_weight')}, f'{g[prefix+"_increment"]} ÷ {g[prefix+"_max"]} × 100 × {g[prefix+"_weight"]}'
    if first == 'gdut_2026_first_choice_retest_scores':
        g = case['additional_scenarios'][first]; scores = sorted(int(score) for score, count in g['score_histogram'].items() for _ in range(count))
        if key == 'n': return {'匿名分数频数': g['score_histogram']}, '各分数频数之和；全日制行数减退役士兵行数'
        if key in ('min', 'max'): return {'匿名分数频数': g['score_histogram']}, ('最小' if key == 'min' else '最大') + '非零频数对应分数'
        p = {'q1': .25, 'median': .5, 'q3': .75}[key]; h = (len(scores)-1)*p; lo = math.floor(h); frac = h-lo
        return {'样本量': len(scores), '分位比例': p, '相邻排序值': [scores[lo], scores[min(lo+1,len(scores)-1)]]}, f'Type 7：h = ({len(scores)} − 1) × {p} = {h}（从 0 编号）；{scores[lo]} + {frac} × ({scores[min(lo+1,len(scores)-1)]} − {scores[lo]})'
    if first == 'hypothetical_offers': return _offer_description(case['hypothetical_followup']['offers'][int(parts[1])], case['hypothetical_followup'], key)
    if first == 'offer_b_ordinary_month':
        offer = dict(case['hypothetical_followup']['offers'][1], months=12)
        return _offer_description(offer, case['hypothetical_followup'], 'monthly_take_home_cash' if key == 'take_home_cash' else 'monthly_remaining_cash')
    if first == 'report_parameters':
        spec = plan['display_inputs'][key]
        if spec.get('algorithm') == 'sum': return spec['source_values'], ' + '.join(map(str, spec['source_values']))
        if spec.get('algorithm') == 'percent_to_ratio': return spec['source_values'], f'{spec["source_values"][0]} ÷ 100（百分数换算）'
        return {spec['case_pointer']: pointer(case, spec['case_pointer'])}, '登记输入原值，不是模型预测'
    if first == 'report_constants':
        value = 12 if key == 'months_per_year' else 200
        return {'定义': '每年月份' if key == 'months_per_year' else '生活费压力情景增量'}, f'登记输入/单位换算：{value}'
    if first == 'luck_start_year': return {'登记起运日期': case['luck_start']}, '取登记日期的年份；不参与录取或求职判断'
    if first == 'illustrative_parameters': return {key: plan['illustrative_parameters'][key]['value']}, '登记输入：说明性参数，不是个人成功概率'
    if first == 'scut_reference_statistics':
        return {'登记匿名官方统计': case['hypothetical_followup']['official_stats'][parts[1]][key]}, '登记的官方样本统计原值；不是本人的录取概率'
    if first == 'sample_reconciliation_2025':
        g = case['source_aggregates']['scut_2025_reconciliation']
        if key == 'ordinary': return dict(g), f'{g["total"]} − {g["minority"]} − {g["soldier"]} − {g["joint"]}'
        return {key: g[key]}, '登记的匿名分类人数原值'
    if first == 'reference_wages_cny':
        value = case['hypothetical_followup']['reference_wages'][parts[1]][key]
        return {'官方工资价位（万元）': value}, f'{value} × 10,000；取整为元（在岗工资，不等于应届起薪）'
    raise ValueError('计算核对说明尚未覆盖：' + path)



# 核对表里的计算项名称：把登记路径翻成中文，读者和其他 AI 不用猜英文字段名。
WORDS = {'additional_scenarios':'补充情景', 'hypothetical_followup':'假设情景', 'gdut_2026_first_choice_retest_scores':'广工 2026 一志愿复试成绩',
         'excluded_soldier_rows':'剔除的退役士兵专项人数', 'full_time_rows':'全日制复试人数', 'score_histogram':'分数频数',
         'gdut_2026_retest':'广工复试换算', 'initial_increment':'初试加分', 'initial_max':'初试满分', 'initial_weight':'初试权重',
         'retest_increment':'复试加分', 'retest_weight':'复试权重', 'gdut_fee_reference':'广工费用参照', 'annual_housing_assumption':'年住宿假设',
         'annual_limit':'年度预算上限', 'living_months':'生活月数', 'monthly_living_assumption':'每月生活费假设', 'target_cohort':'目标年级',
         'annual_cost_if_living_plus_200':'生活费每月多 200 元时的年费用', 'annual_margin_if_living_plus_200':'生活费每月多 200 元时的预算余量',
         'budget':'预算', 'annual_housing':'年住宿', 'daily_hours_ceiling':'每日工时上限', 'hourly_if_housing_fund_counted':'计入公积金的时薪',
         'hours_per_year':'年工时', 'housing_fund_account_total':'公积金账户年合计', 'offers':'offer', 'extra_hours_per_month':'每月加班小时',
         'hf_rate':'公积金比例', 'monthly_gross':'税前月薪', 'monthly_other':'每月其他支出', 'monthly_rent':'每月房租', 'months':'发薪月数',
         'score_scenarios':'分数情景', 'ss_personal_rate_assumption':'个人社保比例假设', 'standard_hours_per_year':'标准年工时',
         'initial_increment_contribution':'初试加分对总成绩的贡献', 'retest_increment_contribution':'复试加分对总成绩的贡献',
         'sample_reconciliation_2025':'2025 名单核对', 'joint':'联合培养人数', 'minority':'少数民族骨干人数', 'ordinary':'普通计划人数',
         'soldier':'退役士兵人数', 'total':'合计', 'living_increment':'生活费增量', 'luck_start_year':'起运年份',
         'monthly_remaining_if_housing_plus_600':'房租多 600 元时每月结余', 'months_per_year':'每年月数', 'reference_wages_cny':'工资价位参考',
         'p10':'第 10 百分位', 'p25':'下四分位', 'p50':'中位数', 'p75':'上四分位', 'p90':'第 90 百分位', 'remaining_cash':'结余',
         'take_home_cash':'到手现金', 'offer_b_ordinary_month':'offer B 普通月', 'social_insurance_base':'社保基数', 'total_cost':'总费用',
         'hypothetical_offers':'假设 offer', 'illustrative_parameters':'示意参数', 'scut_reference_statistics':'华工录取统计',
         'buffer_months':'预留应急后可支撑月数', 'higher_rent_months':'房租提高后可支撑月数', 'all_cash_months':'动用全部现金可支撑月数',
         'spendable':'可动用现金', 'monthly_cost':'每月支出', 'high_monthly_cost':'房租提高后每月支出', 'report_parameters':'', 'report_constants':'',
         'annual_margin':'年度预算余量', 'annual_cost':'年度总费用', 'q1_label':'下四分位的标注', 'q3_label':'上四分位的标注',
         'p10_label':'第 10 百分位的标注', 'p90_label':'第 90 百分位的标注', 'n':'人数', 'min':'最低分', 'q1':'下四分位', 'median':'中位数',
         'q3':'上四分位', 'max':'最高分', 'official_stats':'官方统计', 'official_tuition':'官方学费', 'tuition_reference':'学费参照',
         'annual_tuition':'年学费', 'take_home_assumption':'到手月收入假设', 'monthly_housing_assumption':'每月住房费假设',
         'monthly_other_expenses_assumption':'每月其他支出假设', 'years':'学制年数', 'family_reserve_needed':'家庭需预留金额', 'retest_max':'复试满分', 'applicable_cohort':'适用年级', 'source_group':'来源编号'}


def cn_label(path, fallback):
    """登记路径 → 中文名；有不认识的片段时退回原名，不猜。"""
    parts = []
    for segment in path.strip('/').split('/'):
        pieces = segment.split('__')
        for i, piece in enumerate(pieces):
            prev = pieces[i-1] if i else (parts and None)
            if piece.isdigit():
                n = int(piece)
                if i and pieces[i-1] == 'score_histogram': parts.append(f'{n} 分人数')
                elif i and pieces[i-1] == 'offers' or segment == piece and path.startswith('/hypothetical_offers/'): parts.append('ABCDEFGH'[n] if n < 8 else str(n + 1))
                else: parts.append(f'第 {n + 1} 个')
                continue
            if piece in WORDS:
                if WORDS[piece]: parts.append(WORDS[piece])
            elif any('\u4e00' <= ch <= '\u9fff' for ch in piece): parts.append(piece)
            else: return fallback
    return '·'.join(parts) or fallback


def calculation_rows(case, profile, evidence, calculations):
    """Describe each numeric leaf. Caller maps paths to actual report sections."""
    fresh = recompute(case, profile, evidence, calculations)
    if case['calculation_plan']['engine'] == 'registered_operations':
        return _registered(case, profile, evidence)[1]
    rows = []
    labels = {'annual_cost':'年度总费用', 'annual_margin':'年度预算余量',
              'age_at_decision':'决策时年龄', 'age_at_target':'目标时年龄',
              'monthly_expenses':'每月总支出', 'monthly_remaining':'每月结余',
              'annual_gross':'税前年收入', 'annual_take_home_cash':'到手年收入',
              'monthly_take_home_cash':'到手月收入', 'monthly_remaining_cash':'扣除月支出后结余',
              'hourly_cash':'现金时薪', 'personal_social_insurance':'个人年社保',
              'personal_housing_fund':'个人年公积金', 'tax':'年度个税',
              'total_cost_over_program':'学制总费用', 'n':'人数', 'min':'最低分',
              'q1':'下四分位', 'median':'中位数', 'q3':'上四分位', 'max':'最高分'}
    for path, value in walk(fresh):
        if not numeric(value): continue
        inputs, formula = _legacy_description(case, path)
        key = path.rsplit('/',1)[-1]
        row = _row(path, labels.get(key) or cn_label(path, key), value, inputs, formula)
        if path.startswith('/scut_reference_statistics/') or (path.startswith('/report_parameters/') and
                '/official_stats/' in case['calculation_plan']['display_inputs'][key].get('case_pointer', '')):
            row['verification_limit'] = '未附原始名单，只能复核与登记的官方匿名统计一致，不能从原始名单独立重算分位数或人数。'
        rows.append(row)
    return rows


def recompute_gaokao(result, candidates_csv):
    """Re-evaluate the supplied preference list using bundled optimizer code.

    Candidate order and both random seeds are preserved. This verifies every
    displayed probability and selected major, but deliberately does not rerun
    greedy/swap selection and therefore does not prove global optimality.
    Filesystem paths from result.params are never opened or executed.
    """
    import csv
    import io
    import tempfile
    from pathlib import Path
    import optimize

    if not isinstance(candidates_csv, bytes) or len(candidates_csv) > 20 * 1024 * 1024:
        raise ValueError('候选附件须为不超过 20 MiB 的 CSV 字节')
    raw = result.get('params', {})
    if not isinstance(raw, dict): raise ValueError('缺高考计算参数')
    for path, value in walk(raw):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not numeric(value):
            raise ValueError('高考参数必须为有限数：' + path)
    defaults = {'rank_sd':0.0, 'rho':.3, 'sigma_floor':.1, 'sigma_single':.25,
                'sigma_rule':'v2', 'sigma_scale':1.0, 'no_obey':False, 'stress':2.0,
                'drift':0.0, 'target_year':None, 'cohort':[], 'cohort_now':None,
                'sims':4000, 'seed':42, 'max_fall':None, 'decision_mode':'exploration'}
    allowed = set(defaults) | {'rank', 'slots', 'u_fall'}
    params = {key:raw.get(key, defaults.get(key)) for key in allowed}
    for key in ('rank','slots','u_fall','rank_sd','rho','sigma_floor','sigma_single',
                'sigma_scale','stress','drift','sims','seed'):
        if not numeric(params[key]): raise ValueError('非法高考数值参数：' + key)
    for key in ('sims','slots','seed'):
        if type(params[key]) is not int: raise ValueError(key + '须为整数')
    if not 1 <= params['sims'] <= 20000 or not 1 <= params['slots'] <= 100:
        raise ValueError('复算上限：sims ≤ 20000、slots ≤ 100')
    if not params['rank'] > 0 or not 0 <= params['rho'] < 1 or params['rank_sd'] < 0:
        raise ValueError('位次、相关系数或位次波动范围错误')
    if any(params[key] < 0 for key in ('sigma_floor','sigma_single','sigma_scale','stress')):
        raise ValueError('波动参数不得为负')
    if params['max_fall'] is not None and (not numeric(params['max_fall']) or not 0 <= params['max_fall'] <= 1):
        raise ValueError('滑档上限必须在 0—1 之间')
    if type(params['no_obey']) is not bool: raise ValueError('no_obey须为布尔值')
    if params['sigma_rule'] not in ('v2','legacy') or params['decision_mode'] not in ('formal','simulation','exploration'):
        raise ValueError('未登记的模型规则或决策模式')
    if params['target_year'] is not None and (type(params['target_year']) is not int or not 1900 <= params['target_year'] <= 2200):
        raise ValueError('目标年份错误')
    if not isinstance(params['cohort'],list) or len(params['cohort']) > 100:
        raise ValueError('考生人数参数格式错误')
    try:
        cohort = optimize.parse_cohort(params['cohort'])
        if any(not numeric(value) or value <= 0 for value in cohort.values()):
            raise ValueError('考生人数必须为有限正数')
        if params['cohort_now'] is not None and (not numeric(params['cohort_now']) or params['cohort_now'] <= 0):
            raise ValueError('当年人数必须为有限正数')
        text = candidates_csv.decode('utf-8-sig')
        parsed = list(csv.DictReader(io.StringIO(text, newline='')))
        if not 1 <= len(parsed) <= 5000: raise ValueError('候选数量须在 1—5000 之间')
        # Preserve the original raw row order; selected-only loading changes RNG draws.
        with tempfile.TemporaryDirectory(prefix='zhiqu-verify-') as directory:
            path = Path(directory) / 'candidates.csv'; path.write_bytes(candidates_csv)
            rows, skipped = optimize.load_candidates(path, not params['no_obey'], params['sigma_floor'],
                params['sigma_single'], params['u_fall'], cohort=cohort, cohort_now=params['cohort_now'],
                drift=params['drift'], target_year=params['target_year'], sigma_scale=params['sigma_scale'],
                sigma_rule=params['sigma_rule'], decision_mode='simulation')
            # Offline replay checks mathematics only. Eligibility is a separate
            # source review; never let attached eligibility fields trigger a
            # formal source loader now or in a future optimizer implementation.
    except SystemExit as exc:
        raise ValueError('候选或参数未通过可信计算器校验：' + str(exc)) from exc
    except (UnicodeError, OverflowError, TypeError) as exc:
        raise ValueError('候选附件或参数不合法：' + str(exc)) from exc
    if not rows or len(rows) > 5000: raise ValueError('没有可复算的候选')
    for row in rows:
        for path, value in walk({key:row[key] for key in ('mu','sigma','u','ua','p_adj','expected_cut','majors','gaps')}):
            if isinstance(value,(int,float)) and not isinstance(value,bool) and not numeric(value):
                raise ValueError('候选含非有限数：' + path)
        if len(row['majors']) > 100: raise ValueError('每个专业组最多复算 100 个专业')
    ids = {row['id']:i for i,row in enumerate(rows)}
    if len(ids) != len(rows): raise ValueError('候选 ID 重复')
    saved_list = result.get('list')
    if not isinstance(saved_list,list) or not 1 <= len(saved_list) <= params['slots']:
        raise ValueError('志愿列表为空或超过名额')
    try: selected = [ids[item['id']] for item in saved_list]
    except (KeyError,TypeError) as exc: raise ValueError('志愿引用了不存在的候选') from exc
    if len(selected) != len(set(selected)): raise ValueError('志愿重复')
    n = params['sims']
    admit, adjust, masks = optimize.simulate(rows, params['rank'], params['rank_sd'], params['rho'], n, params['seed'])
    optimize.set_group_utility(rows, admit, adjust, masks)
    ev = optimize.Evaluator(rows, admit, adjust, masks, n, params['u_fall'], params['max_fall'], penalty=1e4)
    if ev.order(selected) != selected: raise ValueError('志愿顺序与登记效用顺序不符')
    eu, fall, _, land = ev.evaluate(selected, detail=True)
    sa, sj, sm = optimize.simulate(rows, params['rank'], params['rank_sd'], params['rho'], n, params['seed']+1, params['stress'])
    sev = optimize.Evaluator(rows, sa, sj, sm, n, params['u_fall'], params['max_fall'], penalty=1e4)
    stress_u, stress_fall, _ = sev.evaluate(selected)
    clear = [optimize.popcount(mask)/n for mask in admit]
    fresh_list = []
    for order,j in enumerate(selected,1):
        row = rows[j]; normal, adjusted, major_counts = land.get(j,(0,0,[]))
        item = {'order':order,'id':row['id'],'name':row['name'],'utility':row['u'],
                'p_clear':clear[j],'p_land':(normal+adjusted)/n,'p_adjusted':adjusted/n,
                'tag':optimize.label(clear[j]),'expected_cut_rank':round(row['expected_cut']),
                'sigma':row['sigma'],'obey':row['obey'],'n_years':row['n_years']}
        for key in ('code','group','major_code','limits'): item[key] = (row['raw'].get(key) or '').strip()
        if row['majors']:
            item['majors'] = [{'name':name,'utility':utility,'p':count/n}
                             for (name,utility,_),count in zip(row['majors'],major_counts or [0]*len(row['majors']))]
        fresh_list.append(item)
    by_u = sorted(range(len(rows)),key=lambda j:-rows[j]['u'])[:params['slots']]
    by_p = sorted(range(len(rows)),key=lambda j:(-clear[j],-rows[j]['u']))[:params['slots']]
    fresh = {'expected_utility':eu,'p_fall':fall,'stress':{'expected_utility':stress_u,'p_fall':stress_fall},
             'list':fresh_list,'baseline_top_utility':list(ev.evaluate(by_u)[:2]),
             'baseline_safest':list(ev.evaluate(by_p)[:2]),'skipped':skipped}
    for key,value in fresh.items():
        if key not in result or result[key] != value:
            raise ValueError('高考复算不一致：' + key)
        for path,leaf in walk(value):
            if isinstance(leaf,bool) != isinstance(pointer(result[key],path),bool):
                raise ValueError('高考结果类型不一致：' + key + path)
    return fresh
