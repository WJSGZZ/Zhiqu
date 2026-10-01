"""Structured eligibility gate. Source URLs are provenance, not proof of truth."""
import json

STATUSES = {'verified', 'pending', 'ineligible'}


def validate_evidence(item, year=None):
    if not isinstance(item, dict):
        raise ValueError('证据须为对象')
    if item.get('status') not in STATUSES:
        raise ValueError('证据状态须为 verified / pending / ineligible')
    if not isinstance(item.get('year'), int) or not item.get('source', '').startswith('https://'):
        raise ValueError('证据须有适用年份和官方来源')
    if year is not None and item['year'] != year:
        raise ValueError('证据年份与决策年份不一致')
    conditions = item.get('hard_conditions', [])
    if not isinstance(conditions, list) or not conditions or any(not isinstance(c, dict) or c.get('status') not in {'met', 'unknown', 'failed'} or
                             not c.get('name') or not c.get('source', '').startswith('https://') for c in conditions):
        raise ValueError('逐项列出硬条件、met / unknown / failed 状态和来源')
    if item['status'] == 'verified' and (item.get('unresolved') or any(c['status'] != 'met' for c in conditions)):
        raise ValueError('未决或不满足的硬条件不能标已核实可行')
    if item['status'] == 'pending' and not item.get('unresolved'):
        raise ValueError('待核实须列明未决事项')
    if item['status'] == 'ineligible' and not any(c['status'] == 'failed' for c in conditions):
        raise ValueError('不可行须有已失败的硬条件')


def require_formal(row, year):
    try:
        item = json.loads(row.get('eligibility_evidence') or '{}')
        validate_evidence(item, year)
        if item['status'] != 'verified':
            raise ValueError('待核实或不可行候选不能进入正式推荐')
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f'{row.get("name", row.get("id", "候选"))}: {exc}') from exc
