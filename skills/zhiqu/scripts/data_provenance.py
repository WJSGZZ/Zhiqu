"""数据库导出到志愿表的逐值来历；不参与位次、预测或志愿排序计算。"""
import json


UNVERIFIED = '第三方整理，未经官方核对'
DISPLAY_GRADES = {'官方', '官方一致', '第三方整理·内部未核'}
FIELDS = {'rank': '位次', 'score': '分数', 'plan': '计划人数'}


def cutoff_rank_gate(fact, provided_fields=None):
    """已核仅分数原表中的推算位次不能冒充实际投档位次；未知格式不猜。"""
    declared_gate = fact.get('usage_gate')
    if isinstance(declared_gate, dict) and declared_gate.get('model_usable') is False:
        return declared_gate
    if provided_fields is None:
        original = fact.get('original_scope')
        reference = original.get('source_format_reference') if isinstance(original, dict) else None
        provided_fields = reference.get('provided_fields') if isinstance(reference, dict) else None
    state = fact.get('value_status')
    status = state.get('status') if isinstance(state, dict) else state
    if not (fact.get('value') not in (None, '') and fact.get('grade') == '官方'
            and status == '推算'
            and isinstance(provided_fields, list) and provided_fields
            and all(isinstance(field, str) for field in provided_fields)
            and 'score' in provided_fields and 'rank' not in provided_fields):
        return None
    method = (state.get('method') if isinstance(state, dict) else None) or '未登记'
    cumulative = isinstance(method, str) and '一分一段累计' in method
    return {'model_usable': False, 'status': '推算参照，待核',
            'meaning': '最低分对应累计末位，非实际最低投档位次' if cumulative else '推算位次，原表未公布实际最低投档位次',
            'method': method,
            'reason': '原表未设位次列；推算输入及适用口径须另核，不作为实际投档位次进入志愿模型'}


def provenance(item):
    value = item.get('data_provenance') or {}
    return json.loads(value) if isinstance(value, str) else value


def entries(item):
    value = provenance(item)
    if not isinstance(value, dict):
        raise ValueError('data_provenance 须为按年份登记的对象')
    for year, fields in sorted(value.items()):
        if not isinstance(fields, dict):
            raise ValueError('逐年来源须为对象')
        for field, fact in fields.items():
            if field not in FIELDS or not isinstance(fact, dict):
                raise ValueError('逐值来源只接受 rank/score/plan 对象')
            yield str(year), field, fact


def display_grade(fact):
    grade = fact.get('display_grade')
    if grade:
        return grade
    return '官方' if fact.get('grade') == '官方' else '第三方整理·内部未核'


def status_text(fact):
    status = fact.get('value_status', '')
    return str(status.get('status', '')) if isinstance(status, dict) else str(status)


def fact_label(fact):
    grade = display_grade(fact)
    label = UNVERIFIED if grade == '第三方整理·内部未核' else grade
    return f'{label}｜来源 {fact.get("source_id", "未登记")}｜{status_text(fact)}'


def prediction_label(item):
    if not item.get('data_provenance') and not item.get('source_grade'):
        return ''
    ranks = [fact for _, field, fact in entries(item) if field == 'rank']
    labels = list(dict.fromkeys(fact_label(fact) for fact in ranks))
    return '模型推算；位次依据：' + '；'.join(labels or [UNVERIFIED])


def only_third_party(item):
    ranks = [fact for _, field, fact in entries(item) if field == 'rank']
    return bool(ranks) and all(display_grade(fact) not in ('官方', '官方一致') for fact in ranks)


def evidence_lines(item):
    """每个原始数字各带来历，不用分数的核对标签替位次升级。"""
    result = []
    for year, field, fact in entries(item):
        value = fact.get('value')
        if value is None:
            continue
        shown = f'{value:,}' if isinstance(value, (int, float)) else str(value)
        line = f'{year}年{FIELDS[field]} {shown}【{fact_label(fact)}】'
        summary = fact.get('cross_check_summary')
        if fact.get('grade') == '第三方整理' and isinstance(summary, dict):
            line += (f'；官方核对：{summary.get("scope", "未注明范围")}，'
                     f'{summary.get("checked", 0)}项、不一致{summary.get("inconsistent", 0)}项')
        completeness = fact.get('completeness') or {}
        if completeness.get('status') == 'partial':
            line += '；原表不完整，不跨缺口换算'
            missing = completeness.get('missing_rows') or completeness.get('missing_scope')
            if missing:
                line += '；缺口：' + json.dumps(missing, ensure_ascii=False)
        result.append(line)
    return result


def provenance_errors(item):
    if not item.get('data_provenance') and not item.get('source_grade'):
        return []  # 旧公开 CSV 流程不补猜等级，也不改变历史案例。
    errors = []
    try:
        facts = list(entries(item))
    except (ValueError, TypeError, AttributeError) as exc:
        return [f'逐值来源无效：{exc}']
    if not any(field == 'rank' for _, field, _ in facts):
        errors.append('数据库候选缺少用于判断的位次来源')
    for year, field, fact in facts:
        if fact.get('value') is None:
            if field == 'rank':
                errors.append(f'{year}.{field} 缺原始值')
            continue  # 计划/分数可未提供，不借空占位给已有位次升级。
        if not fact.get('source_id') or not status_text(fact):
            errors.append(f'{year}.{field} 缺来源编号或值状态')
        if field == 'rank' and cutoff_rank_gate(fact):
            errors.append(f'{year}.{field} 是原表未公布的推算参照，不能作为实际投档位次参与志愿判断；须另核输入和口径')
        if fact.get('grade') not in ('官方', '第三方整理') or display_grade(fact) not in DISPLAY_GRADES:
            errors.append(f'{year}.{field} 来源等级无效')
        if display_grade(fact) == '官方' and fact.get('grade') != '官方':
            errors.append(f'{year}.{field} 第三方不能冒充官方')
        if fact.get('grade') == '第三方整理':
            summary = fact.get('cross_check_summary') or {}
            if not (isinstance(summary, dict) and summary.get('scope')
                    and type(summary.get('checked')) is int and type(summary.get('inconsistent')) is int
                    and 0 <= summary['inconsistent'] <= summary['checked']):
                errors.append(f'{year}.{field} 第三方须登记官方核对范围、项数与不一致数（未核填0）')
        if display_grade(fact) == '官方一致':
            check = fact.get('cross_check') or {}
            source = check.get('official_source') or {} if isinstance(check, dict) else {}
            if not (isinstance(check, dict) and source.get('source_id') and source.get('grade') == '官方'
                    and (source.get('landing_url') or source.get('file_url'))
                    and check.get('verdict') == '一致' and check.get('field') == field
                    and check.get('scope') == fact.get('scope') == check.get('thirdparty_scope')
                    and check.get('official_value') == fact.get('value') == check.get('thirdparty_value')
                    and isinstance(check.get('official_value_status'), dict)
                    and check['official_value_status'].get('status') in ('官方原值', '人工更正')
                    and check.get('official_locator') and check.get('comparison_basis') == '同事实同口径逐值'):
                errors.append(f'{year}.{field} 官方一致缺逐值同口径官方核对凭据')
    return errors
