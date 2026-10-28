"""只读生成分领域质量摘要；不把已入库样本当作全部取数尝试。"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import zhiqu_db as db

LAYERS = {
    '高考': [('批次线', 'gk_batch_line'), ('官方投档线', 'gk_official_cutoff'),
           ('官方一分一段', 'gk_official_yfyd'), ('官方计划', 'gk_official_plan'),
           ('外购计划', 'gk_plan_entry'), ('外购录取结果', 'gk_result'),
           ('外购其他事实', 'gk_purchased_fact'), ('外购一分一段（派生查询视图）', 'gk_vendor_yfyd')],
    '考研': [('国家线', 'ky_national_line'), ('既有院线', 'ky_official_line'),
           ('新增学校及院系复试线', 'ky_retest_line'), ('招生及目录（兼含历史第三方院线）', 'ky_program_year'),
           ('复试及拟录取统计', 'ky_score_dist')],
}
LIMITS = [
    '各层是存储行数，不同表可能描述同一事实，不能相加为去重事实总数。',
    '覆盖obtained只指已登记来源范围；verified_complete单列，不代表全省或全校全部范围齐全。',
    '来源等级按本层引用的不同source_id计，不按数值计；没有source_id的表仅显示行级来源等级。',
    '待核仅为已登记问题条数，含历史未核销问题，不代表当前仍错误的业务行数。',
    '没有完整的拒收/失败文件分母，整体两读一致率不可计算；不以入库成功样本声称100%。',
    '核对表按各自逻辑表分别列示，兼容视图可能含映射历史样本，不能跨表相加。',
    '自划线未有独立可靠类型列，既有院线与新增复试线分别列示，不从校名或标题推断自划线总数。',
]


def group(c, table, column, where='', params=()):
    """只聚合注册的列名；空白与NULL保留在同一未标项。"""
    if column not in db._cols(c, table):
        return None
    sql = ('SELECT COALESCE(NULLIF(TRIM(CAST(' + db._ident(column) +
           " AS TEXT)),''),'未标'),COUNT(*) FROM data." + db._ident(table) +
           (' WHERE ' + where if where else '') + ' GROUP BY 1 ORDER BY 1')
    return dict(c.execute(sql, params))


def value_status(c, table):
    """压缩为字段×状态计数，不输出reason、method或整段原行JSON。"""
    grouped = group(c, table, 'value_status')
    if grouped is None:
        return None
    fields = {}
    invalid = 0
    legacy = Counter()
    for raw, count in grouped.items():
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            value = None
        if isinstance(value, dict):
            for field, detail in value.items():
                status = detail.get('status') if isinstance(detail, dict) else None
                key = status if isinstance(status, str) and status else '未标或结构异常'
                fields.setdefault(field, Counter())[key] += count
        else:
            invalid += count
            # 只保留已知枚举，任意残文不写入产物。
            known = {'官方原值','人工更正','推算','第三方整理未核','第三方已核一致',
                     '未公布','人数太少未公布','来源未提供','原件缺失'}
            legacy[raw if raw in known else '未标或结构异常'] += count
    return {'field_status_counts': {k: dict(sorted(v.items())) for k, v in sorted(fields.items())},
            'non_mapping_rows': invalid, 'legacy_row_status_counts': dict(sorted(legacy.items()))}


def layer(c, label, table, names):
    if table not in names:
        return {'label': label, 'table': table, 'available': False, 'rows': None}
    cols = db._cols(c, table)
    result = {'label': label, 'table': table, 'available': True,
              'rows': c.execute('SELECT COUNT(*) FROM data.' + db._ident(table)).fetchone()[0],
              'value_status': value_status(c, table),
              'quarantine_rows': None, 'source_grades': None}
    if 'quarantine_reason' in cols:
        result['quarantine_rows'] = c.execute('SELECT COUNT(*) FROM data.' + db._ident(table) +
            " WHERE TRIM(COALESCE(quarantine_reason,''))<>''").fetchone()[0]
    if 'source_id' in cols and 'source' in names:
        result['source_grades'] = dict(c.execute(
            "SELECT COALESCE(s.grade,'来源未登记'),COUNT(*) FROM (SELECT DISTINCT source_id FROM data." +
            db._ident(table) + " WHERE source_id IS NOT NULL AND TRIM(source_id)<>'') r "
            'LEFT JOIN data.source s USING(source_id) GROUP BY 1 ORDER BY 1'))
        result['rows_without_source_id'] = c.execute('SELECT COUNT(*) FROM data.' + db._ident(table) +
            " WHERE source_id IS NULL OR TRIM(source_id)=''").fetchone()[0]
    elif 'source_grade' in cols:
        result['source_grade_rows'] = group(c, table, 'source_grade')
    if table == 'ky_score_dist':
        result['list_type_rows'] = group(c, table, 'list_type')
        result['small_group_rows'] = c.execute('SELECT COUNT(*) FROM data.ky_score_dist WHERE n<3').fetchone()[0]
        result['scope_mismatch_rows'] = group(c, table, 'scope_mismatch')
    return result


def coverage(path, domain):
    path = Path(path)
    if not path.is_file():
        return {'available': False, 'cells': None, 'reason': '覆盖表未找到'}
    raw = path.read_bytes()
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        required = {'status', 'year', 'province', 'category'} if domain == '高考' else {'status', 'year', 'school', 'scope_level'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('覆盖表缺少必需列：' + ','.join(sorted(required - set(reader.fieldnames or []))))
        rows = list(reader)
    key_fields = ['province', 'year', 'category'] if domain == '高考' else ['school', 'year', 'scope_level']
    keys = [tuple(r[k] for k in key_fields) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('覆盖表存在重复格，不能重复计数')
    statuses = Counter(r['status'].strip() or '未标' for r in rows)
    reasons = Counter()
    not_obtained = [r for r in rows if r['status'].strip() != 'obtained']
    for r in not_obtained:
        # 按需政策与获取失败分开，不把缺理由视作无失败。
        reason = r.get('deferred_reason', '').strip() or r.get('reason', '').strip() or '未记录原因'
        reasons[reason] += 1
    return {'available': True, 'sha256': hashlib.sha256(raw).hexdigest(), 'cells': len(rows),
            'status_cells': dict(sorted(statuses.items())),
            'strict_flag_without_obtained_cells': sum(r.get('verified_complete', '').strip().lower() in ('true','1','yes') and r['status'].strip() != 'obtained' for r in rows),
            'verified_complete_cells': sum(r.get('verified_complete', '').strip().lower() in ('true', '1', 'yes') for r in rows),
            'not_obtained_reason_cells': dict(sorted(reasons.items()))}


def audit(c, names, domain):
    prefix = 'gk' if domain == '高考' else 'ky'
    result = {}
    # 不累计兼容视图与其底表。每个渠道独立报告，保留分母口径。
    for table, field in [(prefix+'_ingest_issue', 'kind'), (prefix+'_check_sample', 'status'),
                         (prefix+'_correction', 'reason')]:
        if table not in names:
            result[table] = {'available': False, 'rows': None}
            continue
        cols = db._cols(c, table)
        if field not in cols and field == 'status':
            field = 'verdict'
        result[table] = {'available': True,
                        'rows': c.execute('SELECT COUNT(*) FROM data.'+db._ident(table)).fetchone()[0],
                        'by_'+field: group(c, table, field)}
    for table in ['check_sample', 'correction']:
        if table not in names:
            result[table] = {'available': False, 'rows': None}
            continue
        cols = db._cols(c, table)
        if 'domain' in cols:
            where, params = 'domain=?', (domain,)
        elif 'table_name' in cols:
            where, params = 'table_name GLOB ?', (prefix+'_*',)
        else:
            result[table] = {'available': False, 'rows': None, 'reason': '无法可靠区分领域'}
            continue
        result[table] = {'available': True, 'rows': c.execute('SELECT COUNT(*) FROM data.'+
            db._ident(table)+' WHERE '+where, params).fetchone()[0],
            'outcomes': group(c, table, 'verdict' if table == 'check_sample' else 'reason', where, params)}
    return result


def extra_audit(c, names, domain):
    """补充新存储渠道；保留各渠道计数，绝不和旧问题表相加。"""
    specs = [('core_delta_check', 'verdict', None),
             ('v_core_delta_ingest_issue', None, 'occurrence_count'),
             ('core_delta_scope_issue', None, None),
             ('purchased_issue_summary', 'kind', 'occurrences'),
             ('purchased_conflicted_value', None, None)] if domain == '高考' else [('ky_retest_line_issue', 'kind', None)]
    out = {}
    for table, field, occurrences in specs:
        if table not in names:
            out[table] = {'available': False, 'rows': None}
            continue
        out[table] = {'available': True, 'rows': c.execute('SELECT COUNT(*) FROM data.'+db._ident(table)).fetchone()[0]}
        if field:
            out[table]['outcomes'] = group(c, table, field)
        if occurrences and occurrences in db._cols(c, table):
            out[table]['occurrences'] = c.execute('SELECT COALESCE(SUM('+db._ident(occurrences)+'),0) FROM data.'+db._ident(table)).fetchone()[0]
            out[table]['note'] = 'rows为问题组，occurrences为登记出现次数，不是去重业务行数'
    if domain == '高考':
        table = 'purchased_check'
        if table in names and 'sample_mirrored' in db._cols(c, table):
            where = 'COALESCE(sample_mirrored,0)<>1'
            out['purchased_check_unmirrored'] = {'available': True,
                'rows': c.execute('SELECT COUNT(*) FROM data.purchased_check WHERE '+where).fetchone()[0],
                'outcomes': group(c, table, 'verdict', where),
                'note': '仅未镜像到check_sample的检查；不重复列sample_mirrored=1'}
        else:
            out['purchased_check_unmirrored'] = {'available': False, 'rows': None}
    return out


def shared_audit(c, names):
    out = {}
    if 'correction' in names:
        where = "COALESCE(table_name,'') NOT GLOB 'gk_*' AND COALESCE(table_name,'') NOT GLOB 'ky_*'"
        out['correction_without_domain_prefix'] = {
            'rows': c.execute('SELECT COUNT(*) FROM data.correction WHERE '+where).fetchone()[0],
            'by_table': group(c, 'correction', 'table_name', where),
            'note': '共用或旧表名渠道；未纳入两领域前缀统计，不猜领域，需逐类映射'}
    if 'check_sample' in names:
        where = "COALESCE(domain,'') NOT IN ('高考','考研')"
        out['check_sample_other_domains'] = {
            'rows': c.execute('SELECT COUNT(*) FROM data.check_sample WHERE '+where).fetchone()[0],
            'by_domain': group(c, 'check_sample', 'domain', where)}
    return out


def build(c, coverage_root):
    names = db._tables(c)
    manifest = dict(c.execute('SELECT key,value FROM data.storage_manifest')) if 'storage_manifest' in names else {}
    version = None
    if 'dataset_version' in names:
        # 发布顺序不等于字符串版本号排序。
        versions = [str(r[0]) for r in c.execute('SELECT version FROM data.dataset_version')]
        if versions:
            version = max(versions, key=lambda v: tuple(int(x) for x in v.split('.')))
    out = {'schema_version': 1, 'database_version': version, 'generation': manifest.get('generation'),
           'shared_audit_channels': shared_audit(c, names),
           'generated_at': datetime.now(timezone.utc).isoformat(),
           'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'limitations': LIMITS, 'domains': {}}
    for domain, specs in LAYERS.items():
        out['domains'][domain] = {
            'layers': [layer(c, label, table, names) for label, table in specs],
            'coverage': coverage(Path(coverage_root)/('gaokao.csv' if domain == '高考' else 'kaoyan.csv'), domain),
            'audit_channels': {**audit(c, names, domain), **extra_audit(c, names, domain)},
            'dual_read_rate': {'value': None, 'reason': LIMITS[4]},
        }
    out['domains']['考研']['self_lines'] = {'rows': None, 'reason': LIMITS[6]}
    return out


def markdown(report, domain):
    r = report['domains'][domain]
    c = r['coverage']
    lines = [f'# {domain}数据质量摘要', '',
             f"库版本：{report['database_version'] or '未记录'}；生成：{report['generated_at']}。",
             f"配对代次：{report['generation'] or '未记录'}。", '',
             '覆盖格：'+ (str(c['cells'])+'；状态 '+json.dumps(c['status_cells'], ensure_ascii=False)+
              f"；严格完整 {c['verified_complete_cells']}。" if c['available'] else '不可计算（覆盖表缺失）。'),
             '两读整体一致率：不可计算（没有含拒收文件的完整尝试分母）。', '',
             '| 数据层 | 存储行数 | 来源等级（不同出处数） |', '|---|---:|---|']
    for row in r['layers']:
        grades = row.get('source_grades')
        text = json.dumps(grades, ensure_ascii=False) if grades is not None else '未能按出处统计'
        if row.get('source_grade_rows') is not None:
            text += '；行级等级 '+json.dumps(row['source_grade_rows'], ensure_ascii=False)
        lines.append(f"| {row['label']} | {row['rows'] if row['available'] else '未知（表缺失）'} | {text} |")
    lines += ['', '核对、修正与待核（各渠道不可相加）：']
    for table, data in r['audit_channels'].items():
        outcomes = data.get('outcomes') or data.get('by_status') or data.get('by_verdict')
        suffix = '；结果 '+json.dumps(outcomes, ensure_ascii=False) if outcomes and len(outcomes) <= 12 else ''
        lines.append(f"- {table}：{data['rows'] if data['available'] else '未知'} 条{suffix}。")
    lines += ['', '共用/旧名渠道（未纳入以上领域计数）：']
    for name, data in report['shared_audit_channels'].items():
        lines.append('- '+name+'：'+str(data['rows'])+' 条；'+json.dumps(data.get('by_table') or data.get('by_domain'), ensure_ascii=False))
    lines += ['', '未取得原因逐项分布、值状态、隔离/小样本和核对结果分布见同名JSON；不输出个人行或原始名单。', '', '口径与限制：']
    lines += ['- '+item for item in report['limitations']]
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', help='院校查询库，只读并自动连接配对审计库')
    parser.add_argument('--coverage-root', type=Path, default=Path(__file__).resolve().parents[1]/'data/coverage')
    parser.add_argument('--out', type=Path, required=True, help='新的本机输出目录（拒绝覆盖历史报告）')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('输出目录已存在，请按版本/日期选择新目录')
    with db._open('education', args.db) as (c, _):
        c.execute('BEGIN')
        report = build(c, args.coverage_root)
    args.out.mkdir(parents=True)
    for domain, name in [('高考', 'gaokao'), ('考研', 'kaoyan')]:
        payload = {k: v for k, v in report.items() if k != 'domains'}
        payload['domain'] = domain
        payload['metrics'] = report['domains'][domain]
        (args.out/(name+'.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
        (args.out/(name+'.md')).write_text(markdown(report, domain))
    print('高考、考研质量摘要已生成；缺失凭据明确标为不可计算。')


if __name__ == '__main__':
    main()
