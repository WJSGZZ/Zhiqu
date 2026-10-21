#!/usr/bin/env python3
"""Read-only, provenance-preserving queries for Zhiqu's two local databases.

Public API: query_school, query_program, query_jobs, query_source. Results are
plain dictionaries; render_text renders the same result without hiding limits.
No SQL string supplied by a caller is executed. All database files are attached
with mode=ro to an in-memory connection.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
import zlib

SHARED = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = {k: SHARED / 'data' / k / (k + '.sqlite') for k in ('education', 'employment')}

class QueryError(ValueError):
    pass


def _path(domain, db=None):
    return Path(db or os.environ.get('ZHIQU_' + domain.upper() + '_DB') or DEFAULTS[domain]).expanduser().resolve()


@contextlib.contextmanager
def _open(domain, db=None, education_db=None):
    p = _path(domain, db)
    if not p.is_file():
        raise QueryError('本机数据库未找到：' + str(p))
    c = sqlite3.connect(':memory:', uri=True)
    c.row_factory = sqlite3.Row
    try:
        c.execute('ATTACH DATABASE ? AS data', (p.as_uri() + '?mode=ro',))
        if education_db:
            ep = _path('education', education_db)
            if not ep.is_file():
                raise QueryError('学校专业字典库未找到：' + str(ep))
            c.execute('ATTACH DATABASE ? AS education', (ep.as_uri() + '?mode=ro',))
        c.execute('PRAGMA query_only=ON')
        yield c, p
    finally:
        c.close()


def _ident(s):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', s):
        raise QueryError('无效表名')
    return '"' + s + '"'


def _tables(c):
    return {x[0] for x in c.execute("SELECT name FROM data.sqlite_master WHERE type IN ('table','view')")}


def _cols(c, table):
    return {x[1] for x in c.execute('PRAGMA data.table_info(' + _ident(table) + ')')}


def _json(s, default=None):
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s) if s else ({} if default is None else default)
    except (ValueError, TypeError):
        return {} if default is None else default


def _norm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))


def _identity(c, name, year=None, province=None):
    tables = _tables(c)
    if 'institution' not in tables:
        raise QueryError('数据库缺少学校身份表')
    institutions = [dict(x) for x in c.execute('SELECT * FROM data.institution')]
    by_id = {str(x['institution_id']): x for x in institutions}
    target = _norm(name)
    matches = set()
    warnings = []
    aliases = [dict(x) for x in c.execute('SELECT * FROM data.institution_alias')] if 'institution_alias' in tables else []
    known_names = {_norm(x.get('alias', '')) for x in aliases}
    for row in institutions:
        if target in {_norm(row.get('institution_id', '')), _norm(row.get('moe_code', ''))}:
            matches.add(str(row['institution_id']))
        elif target == _norm(row.get('name', '')) and target not in known_names:
            matches.add(str(row['institution_id']))
    needs_year = False
    admission_code_match = False
    for a in aliases:
        if _norm(a.get('alias', '')) != target:
            continue
        if province and a.get('province') and _norm(province).rstrip('省市') != _norm(a['province']).rstrip('省市'):
            continue
        if a.get('kind')=='省招生代码' and not province:
            continue
        lo, hi, exact = a.get('year_from'), a.get('year_to'), a.get('year')
        if year is not None:
            if exact is not None and int(exact) != int(year):
                continue
            if lo is not None and int(year) < int(lo):
                continue
            if hi is not None and int(year) > int(hi):
                continue
        elif lo is not None or hi is not None or exact is not None:
            needs_year = True
        if a.get('kind')=='省招生代码':
            admission_code_match = True
        matches.add(str(a['institution_id']))
    if province and len(matches) > 1 and not admission_code_match:
        matches = {i for i in matches if i in by_id and (not by_id[i].get('province') or _norm(province).rstrip('省市') == _norm(by_id[i]['province']).rstrip('省市'))}
    if not matches and 'institution_event' in tables:
        for event in c.execute('SELECT * FROM data.institution_event'):
            e=dict(event)
            if _norm(e.get('name_before',''))==target and e.get('status')=='更名' and e.get('successor_id')==e.get('institution_id'):
                matches.add(str(e['institution_id']));warnings.append('按已登记的同标识码更名事件识别历史名称；依据见事件出处')
    if len(matches) != 1:
        names = ['%s（%s）' % (by_id[i].get('name', ''), i) for i in sorted(matches) if i in by_id]
        raise QueryError(('校名存在多个身份，请补年份/省份：' + '、'.join(names)) if matches else '该写法在指定年份/省份未能唯一对齐；不猜学校身份：' + str(name))
    identity = dict(by_id[next(iter(matches))])
    if needs_year:
        warnings.append('未指定年份：别名含适用年限，以下为身份检索；跨年数据按各记录年份校验，不自动重挂继任学校。')
    events = []
    if 'institution_event' in tables:
        cols = _cols(c, 'institution_event')
        tests = ['institution_id=?']; args = [identity['institution_id']]
        if 'successor_id' in cols:
            tests.append('successor_id=?'); args.append(identity['institution_id'])
        events = [dict(x) for x in c.execute('SELECT * FROM data.institution_event WHERE ' + ' OR '.join(tests) + ' ORDER BY effective', args)]
        if year and any(str(x.get('effective', '')).startswith(str(year)) for x in events):
            warnings.append('查询年份发生存续事件；仅给年份不能判定年内事件前后身份，请核生效日期。')
    if year is not None:
        terminal = identity.get('status') in ('转设','合并入他校','撤销')
        closed = re.match(r'^(\d{4})', str(identity.get('closed') or ''))
        if terminal and closed and int(year) > int(closed[1]):
            raise QueryError('该校历史身份已于'+str(identity['closed'])+'结束；不把旧校数据自动挂到继任学校，请核对学校身份与年份。')
        born = re.match(r'^(\d{4})', str(identity.get('established') or ''))
        if born and int(year) < int(born[1]):
            raise QueryError('查询年份早于该身份设立年份；不倒挂新校身份。')
        for e in events:
            effective = re.match(r'^(\d{4})', str(e.get('effective') or ''))
            if e.get('institution_id') == identity['institution_id'] and e.get('status') in ('转设','合并入他校','撤销') and effective and int(year) > int(effective[1]):
                raise QueryError('指定年份已越过该历史身份的'+str(e.get('status'))+'事件；请核对前后身份，不自动转挂。')
    identity['events'] = events
    identity['query_name'] = name
    identity['query_year'] = year
    return identity, warnings


NUMERIC = {
    'institution_profile': ['recommend_rate', 'n_master', 'n_phd', 'school_rank'],
    'gk_plan_entry': ['plan_n', 'group_plan_n', 'years', 'tuition'],
    'gk_official_cutoff': ['plan', 'admit', 'score', 'rank'],
    'gk_v_usable': ['min_score', 'min_rank'],
    'gk_v_purchased': ['plan_n','admitted_n','min_score','mean_score','max_score','min_rank','max_rank','mean_rank','score','segment_n','cumulative_n','tuition','group_plan_n','plan_n_result','count_unspecified','rank_unspecified','score_unspecified'],
    'ky_program_year': ['line_total', 'politics', 'english', 'math', 'major', 'planned', 'tuimian'],
    'ky_v_usable': ['line_total', 'n', 'min', 'q1', 'median', 'q3', 'max', 'mean', 'excluded_count', 'single_100', 'single_over_100', 'planned', 'tuimian'],
    'ky_v_retest_line': ['total', 'politics', 'english', 'math', 'major1', 'major2'],
    'ky_retest_line': ['total', 'politics', 'english', 'math', 'major1', 'major2'],
    'job_summary': ['headcount', 'paid_applicants', 'paid_per_seat'],
    'job_position': ['headcount'],
    'wage_stat': ['p10', 'p25', 'p50', 'p75', 'p90'],
    'competition_stat': ['n_jobs', 'p10', 'p25', 'p50', 'p75', 'p90', 'share_below_10', 'share_100_plus'],
    'civil_major_summary': ['headcount', 'n_jobs', 'share'],
    'industry_stat': ['value'],
    'graduate_destination': ['headcount', 'percentage', 'rank'],
    'employment_major_industry': ['value_number','percentage'],
}
NUMERIC['ky_v_usable_line']=['line_total','politics','english','math','major','single_100','single_over_100']
NUMERIC['ky_v_usable_program']=['planned','tuimian']
NUMERIC['ky_v_usable']=['n','min','q1','median','q3','max','mean','excluded_count']
LABELS = {'total':'总分','line_total':'复试总分','politics':'原列政治/首科（须核口径）','english':'外语','math':'数学','major':'业务课','major1':'业务课一','major2':'业务课二','single_100':'单科满分100门槛','single_over_100':'单科满分超过100门槛','planned':'招生人数','tuimian':'推免人数','n':'样本人数','min':'最低','q1':'下四分位','median':'中位数','q3':'上四分位','max':'最高','mean':'平均','excluded_count':'排除数','recommend_rate':'保研比例','n_master':'硕士点','n_phd':'博士点','school_rank':'原表排名','plan_n':'计划人数','admitted_n':'录取人数','group_plan_n':'专业组人数','plan_n_result':'计划人数结果（原字段）','segment_n':'同分人数','cumulative_n':'累计人数','count_unspecified':'人数（含义未明确）','score_unspecified':'分数（含义未明确）','rank_unspecified':'位次（含义未明确）','years':'学制','tuition':'学费','plan':'计划人数','admit':'录取人数','score':'最低分','rank':'最低位次','min_score':'最低分','mean_score':'平均分','max_score':'最高分','min_rank':'最低位次','mean_rank':'平均位次','max_rank':'最高位次','headcount':'招录人数','percentage':'百分比','paid_applicants':'缴费人数','paid_per_seat':'缴费人数/名额','p10':'10%分位','p25':'25%分位','p50':'中位数','p75':'75%分位','p90':'90%分位','n_jobs':'职位数','share':'原表比例','share_below_10':'低于10人/名额的职位比例','share_100_plus':'100人/名额以上职位比例'}
TITLES = {'institution_profile':'学校概况（第三方，年份未明单列）','gk_plan_entry':'高考招生计划','gk_official_cutoff':'高考官方投档线','gk_v_usable':'高考整理录取记录','gk_v_purchased':'高考购买数据（保留核验状态）','ky_program_year':'考研目录与往年线','ky_v_usable':'考研分布与可用历史记录','ky_v_retest_line':'学校官网复试线（保留核验状态）','ky_retest_line':'学校官网复试线（保留核验状态）','job_summary':'岗位与匿名报名人数','job_position':'岗位','wage_stat':'在岗工资调查（不代表应届起薪）','competition_stat':'匿名群体竞争统计（非个人概率）','civil_major_summary':'本科专业可报岗位汇总','selected_university':'选调高校范围','recruitment_notice':'招聘公告可用性','industry_stat':'行业统计','graduate_destination':'院校就业去向（届别按原表）'}
CONTEXT = ['year','plan_year','province','region','college','program_code','program_name','major_code','major_name','degree_type','study_mode','direction','joint_program','special_plan','admission_route','line_scope','list_type','scope','scope_mismatch','scope_mismatch_note','plan_type','subject','subject_type','batch','group_code','grp','position_id','unit','position','education','degree','major_clause','group_type','group','category','school','school_name','verification_status','note','notes','school_tags','degree_level','master_list','phd_list','year_status']


TITLES['employment_major_industry']='专业就业行业分布（届别、单位按原表）'
LABELS['value_number']='原表占比数值'
CONTEXT += ['industry','unit_raw','value_raw','cohort']
CONTEXT.append('subjects')
CONTEXT += ['graduate_cohort','graduate_cohort_raw','cohort_status','province_raw','city_raw','institution_name_raw','item','item_raw','record_type','dataset_type','school_raw','group_name','subject_requirements','scope_raw']

def _source(c, sid):
    if sid and 'source' in _tables(c):
        row = c.execute('SELECT * FROM data.source WHERE source_id=?', (sid,)).fetchone()
        if row:
            return dict(row)
    return {'source_id': sid or '未登记', 'grade': '未注明', 'publisher': '未注明', 'archive_status':'未取到'}


def _status(row, field):
    s = _json(row.get('value_status')).get(field)
    if isinstance(s, str):
        return {'status': s}
    return dict(s) if isinstance(s, dict) else {'status': '未标记（待核）'}


def _unit(table, field, row):
    if table == 'gk_v_purchased':
        if field in ('count_unspecified',): return '数量（招生/录取含义未判）'
        if field == 'score_unspecified': return '分（语义未判）'
        if field == 'rank_unspecified': return '位（语义未判）'
        if field == 'tuition': return '金额（币种、周期见原表）'
        if field in ('plan_n','admitted_n','group_plan_n','plan_n_result','segment_n','cumulative_n'): return '人'
        if field in ('min_score','mean_score','max_score','score','mean_score'): return '分'
        if field in ('min_rank','max_rank','mean_rank'): return '位'
    if table == 'employment_major_industry':
        return '百分比（原值）' if field=='percentage' else row.get('unit_raw') or '单位未注明'
    if table == 'graduate_destination':
        if field == 'headcount': return '签约人数'
        if field == 'percentage': return '百分比（原值）'
    if field == 'recommend_rate': return '比例（原值，未自动换算百分数）'
    if field in ('share_below_10','share_100_plus'): return '比例（0—1）'
    if field == 'share': return '原表比例'
    if table == 'wage_stat': return row.get('unit') or '单位未提供'
    if table == 'competition_stat': return '职位' if field == 'n_jobs' else row.get('unit') or '单位未提供'
    if field == 'paid_per_seat': return '缴费人数/名额（群体比例）'
    if field == 'tuition':
        raw=str(row.get('tuition_raw') or '')
        # 原始单元格是金额及附注，不是单位；不重复打印金额或推定币种。
        if re.search(r'美元|港币|港元|澳门元|澳元|人民币|元',raw):return '（单位与计费周期见原学费记载）'
        return '（币种与计费周期未标明）'
    if field in ('n','headcount','paid_applicants','plan_n','group_plan_n','planned','tuimian','excluded_count','plan','admit'): return '人'
    if field == 'years': return '年'
    return ''


def _original_excerpt(locator):
    if not isinstance(locator,dict) or not locator.get('path') or not locator.get('jsonl_line'):return None
    path=(ROOT/str(locator['path'])).resolve()
    allowed=(SHARED/'data').resolve()
    if not path.is_relative_to(allowed) or not path.is_file():return None
    try:
        number=int(locator['jsonl_line'])
        if not 1<=number<=200000 or path.stat().st_size>100_000_000:return None
        with path.open(encoding='utf-8') as f:
            for i,line in enumerate(f,1):
                if i!=number:continue
                item=json.loads(line)
                if locator.get('sha256') and item.get('canonical_row_sha256')!=locator['sha256']:return {'摘录状态':'定位指纹不符，未引用'}
                text={k:item[k] for k in ['raw_row_candidates','recovered_safe_quotes','continuation_actual_evidence','root_reviewed_image_locations','unclosed_reasons','review_conclusion'] if item.get(k)}
                return text or None
    except (ValueError,OSError,TypeError):return None
    return None


def _official_value_locator(c, row, field, official_source_id):
    """Match a corrected field's official position; never reuse purchase coordinates."""
    result = {'official_locator': None, 'official_locator_status': '未取到逐值官方定位'}
    if 'purchased_check' not in _tables(c):
        return result
    required = {'record_id','field','official_source_id','official_locator'}
    if not required <= _cols(c, 'purchased_check'):
        return result
    checks = c.execute(
        'SELECT DISTINCT official_locator FROM data.purchased_check '
        'WHERE record_id=? AND field=? AND official_source_id=?',
        (row.get('record_id'), field, official_source_id)).fetchall()
    locations = sorted({x[0] for x in checks if isinstance(x[0], str) and x[0].strip()})
    if len(locations) == 1:
        result.update(official_locator=locations[0], official_locator_status='逐字段核对定位')
    elif len(locations) > 1:
        result.update(official_locator_status='多个匹配位置，未确定唯一官方位置',
                      official_locator_candidates=locations)
    return result



def _lean_raw_id(row):
    match=re.fullmatch(r't19-locator-(\d+)',str(row.get('raw_row_id') or ''))
    raw_id=int(match[1]) if match else row.get('raw_id')
    return raw_id if type(raw_id) is int and 0<=raw_id<=2**63-1 else None



def _lean_primary_raw_id(c, row):
    raw_id=_lean_raw_id(row);tables=_tables(c)
    if row.get('raw_row_id') and raw_id is None:return None,False
    if row.get('record_key') is None or 'purchased_observation' not in tables:return raw_id,True
    if 'purchased_source_key' not in tables or not {'record_key','source_key','raw_id'}<=_cols(c,'purchased_observation'):return raw_id,False
    primary=c.execute('SELECT o.raw_id,s.source_id FROM data.purchased_observation o LEFT JOIN data.purchased_source_key s USING(source_key) WHERE o.record_key=?',(row['record_key'],)).fetchall()
    if len(primary)!=1:return None,False
    observed,sid=primary[0]
    if type(observed) is not int or (raw_id is not None and raw_id!=observed) or (row.get('source_id') and sid!=row['source_id']):return None,False
    return observed,True

def _lean_locator(c, raw_id, expected_source_id=None):
    tables=_tables(c)
    if type(raw_id) is not int or not {'purchased_locator_run','purchased_source_key'}<=tables:return None
    required={'raw_start','raw_end','source_key','src_sheet','src_row_start','src_row_step','src_page','src_table'}
    if not required<=_cols(c,'purchased_locator_run'):return None
    item=c.execute('SELECT r.*,s.source_id FROM data.purchased_locator_run r LEFT JOIN data.purchased_source_key s USING(source_key) WHERE r.raw_start<=? ORDER BY r.raw_start DESC LIMIT 1',(raw_id,)).fetchone()
    if not item:return None
    r=dict(item)
    if type(r.get('raw_end')) is not int or raw_id>r['raw_end'] or not r.get('source_id'):return None
    if expected_source_id and r['source_id']!=expected_source_id:return None
    row_start,step=r.get('src_row_start'),r.get('src_row_step')
    if row_start is not None and (type(row_start) is not int or type(step) is not int):return None
    loc={k:r[k] for k in ('src_sheet','src_page','src_table') if r.get(k) is not None}
    if row_start is not None:loc['src_row']=row_start+(raw_id-r['raw_start'])*step
    return {'source_id':r['source_id'],'raw_id':raw_id,'locator':loc}


def _lean_purchased_evidence(c, row):
    if 'purchased_locator_run' not in _tables(c):return None
    raw_id,primary_valid=_lean_primary_raw_id(c,row)
    located=_lean_locator(c,raw_id,row.get('source_id')) if primary_valid else None
    result={'excerpt':None,'locator':located['locator'] if located else None,
            'excerpt_kind':'仅保留定位与抽样，此行未留全文',
            'excerpt_status':'此行未保留匿名单元格全文；不冒充已取得全原文'}
    if not located:
        result['excerpt_status']='原件定位未能核实；仅保留定位与抽样，此行未留全文'
        return result
    if 'purchased_audit_sample' not in _tables(c):return result
    required={'source_id','raw_id','cells_json'}
    if not required<=_cols(c,'purchased_audit_sample'):return result
    matches=c.execute('SELECT * FROM data.purchased_audit_sample WHERE source_id=? AND raw_id=?',(located['source_id'],raw_id)).fetchall()
    if len(matches)!=1:return result
    sample=dict(matches[0])
    if any(sample.get(k) is not None and sample[k]!=located['locator'].get(k) for k in ('src_sheet','src_row','src_page','src_table')):
        result['excerpt_status']='抽样与定位不一致，未引用；此行未留全文'
        return result
    if sample.get('row_sha256') and hashlib.sha256(str(sample.get('cells_json') or '').encode()).hexdigest()!=sample['row_sha256']:
        result['excerpt_status']='抽样指纹不符，未引用；此行未留全文'
        return result
    try:cells=json.loads(sample['cells_json'])
    except (ValueError,TypeError):return result
    if not isinstance(cells,(dict,list)):return result
    result.update(excerpt=cells,excerpt_kind='原表匿名抽样单元格（此行为保留样本；非官方逐字原文）',excerpt_status='只引用精确匹配此来源、raw_id与逐行定位的保留样本')
    return result


def _purchased_additional_sources(c, row):
    tables=_tables(c);key=row.get('record_key')
    if key is None or 'purchased_observation_source' not in tables:return []
    if not {'record_key','raw_id'}<=_cols(c,'purchased_observation_source'):return []
    primary,_=_lean_primary_raw_id(c,row);result=[];seen=set()
    for (raw_id,) in c.execute('SELECT raw_id FROM data.purchased_observation_source WHERE record_key=? ORDER BY raw_id',(key,)):
        if raw_id==primary or raw_id in seen:continue
        seen.add(raw_id);found=_lean_locator(c,raw_id)
        if found:result.append({**found,'source':_source(c,found['source_id'])})
        else:result.append({'source_id':None,'raw_id':raw_id,'locator':{'locator_status':'额外来源逐行定位未取到，未借用主来源位置'}})
    return result


NUMERIC_CONFLICT_NOTE='同口径第三方版本值不一致，待核'

def _numeric_conflicts(row):
    raw=row.get('numeric_conflict_fields')
    if raw is None or raw=='':return [],None
    try:value=raw if isinstance(raw,list) else json.loads(raw)
    except (ValueError,TypeError):return [],'冲突字段标记格式未能解析，待核；未推断具体冲突字段'
    if value is None:return [],None
    if not isinstance(value,list) or any(not isinstance(field,str) for field in value):
        return [],'冲突字段标记格式未能解析，待核；未推断具体冲突字段'
    return value,None

def _record(c, table, row):
    conflict_fields,conflict_parse_status=_numeric_conflicts(row) if table=='gk_v_purchased' else ([],None)
    sid = row.get('source_id')
    if not sid and row.get('src_file') is not None:
        sid = 'vendor-file-' + str(row['src_file'])
    s = _source(c, sid)
    if table == 'employment_major_industry':
        row=dict(row);row['graduate_cohort']=row.get('cohort') or '未注明'
        if row.get('raw_cells'):
            row['excerpt']=_json(row['raw_cells']);row['excerpt_kind']='原表匿名单元格'
        elif row.get('value_raw') not in (None,''):
            row['excerpt']={'占比原格':row['value_raw']};row['excerpt_kind']='已保留的原表业务字段；未保留全行单元格副本'
        else:
            row['excerpt_kind']='原业务字段留存；此行未保留全行单元格副本'
    values = {}
    wording=' '.join(str(row.get(k) or '') for k in ['scope','scope_raw','note','extra_json'])
    generic_subjects=bool(re.search(r'不区分政治[、/和]?英语|单科\s*[=>]|单科.{0,20}满分|满分.{0,8}100.{0,20}(超过|>|大于)|第[一1]门|第1/2/3/4门',wording))
    if table == 'gk_v_usable' and row.get('entry_id') is not None and 'gk_plan_entry' in _tables(c):
        plan = c.execute('SELECT * FROM data.gk_plan_entry WHERE entry_id=?',(row['entry_id'],)).fetchone()
        if plan:
            plan=dict(plan);sid='vendor-file-'+str(plan.get('src_file'));s=_source(c,sid)
            for key in ['src_file','src_row','src_page','src_table']:row.setdefault(key,plan.get(key))
    for field in NUMERIC.get(table, []):
        if field not in row:
            continue
        vs = _status(row, field)
        field_sources = _json(row.get('field_source_ids'))
        correction_sid = field_sources.get(field) if isinstance(field_sources, dict) else None
        value_sid = correction_sid or (row.get('application_source_id') if field == 'paid_applicants' else sid)
        src = _source(c, value_sid) if value_sid != sid else s
        if correction_sid:
            vs = {'status':'人工更正','original_value_status':vs,'reason':'有字段级官方更正来源；原始状态保留在 original_value_status'}
        if table == 'gk_v_usable' and 'gk_check_sample' in _tables(c):
            chk=c.execute("SELECT official_source_id FROM data.gk_check_sample WHERE entry_id=? AND year=? AND field=? AND table_name='result' AND verdict='不一致'",(row.get('entry_id'),row.get('year'),field)).fetchall()
            ids={x[0] for x in chk if x[0]}
            if len(ids)==1:value_sid=next(iter(ids));src=_source(c,value_sid)
            elif len(ids)>1:vs={'status':'待核','reason':'对应多条官方纠错来源，不选一条冒充唯一出处'}
        if field=='paid_applicants' and 'job_application' in _tables(c) and row.get('position_id'):
            app=c.execute('SELECT value_status FROM data.job_application WHERE position_id=? AND source_id=?',(row['position_id'],value_sid)).fetchall()
            if len(app)==1:vs=_status({'value_status':app[0][0]},'paid_applicants')
        values[field] = {'value': row[field], 'unit': _unit(table, field, row), 'grade': src.get('grade') or row.get('source_grade') or '未注明', 'publisher': src.get('publisher') or '未注明', 'source_id': value_sid or '未登记', 'value_status': vs}
        if correction_sid:
            values[field]['original_source_id'] = sid or '未登记'
            if table == 'gk_v_purchased':
                values[field].update(_official_value_locator(c, row, field, correction_sid))
        if table.startswith('ky_') and generic_subjects and field in ['politics','english','math','major','major1','major2']:
            values[field]['display_label']='历史槽位（原表按满分档或科目编号列示，见范围）'
            values[field]['subject_mapping_status']='不从旧槽位反推政治/英语/数学或两档值；原值保留'
        if field == 'paid_per_seat':
            inputs=[_source(c,x) for x in [sid,row.get('application_source_id')] if x]
            values[field]['source_id']=' + '.join(x['source_id'] for x in inputs)
            values[field]['publisher']='、'.join(dict.fromkeys(x.get('publisher','未注明') for x in inputs))
            values[field]['grade']='官方' if inputs and all(x.get('grade')=='官方' for x in inputs) else '第三方整理' if any(x.get('grade')=='第三方整理' for x in inputs) else '未注明'
            values[field]['value_status'] = {'status':'推算','method':'缴费人数÷招录名额；群体人数/名额，非个人概率','inputs_source_ids':[sid,row.get('application_source_id')]}
        if field in conflict_fields:
            values[field]['numeric_conflict']={'status':'第三方版本冲突','reason':NUMERIC_CONFLICT_NOTE}
    major_links=[];institution_links=[]
    link_id=row.get('record_id',row.get('position_id'))
    if link_id is not None:
        original_table='job_position' if table=='job_summary' else table
        if 'major_link' in _tables(c):major_links=[dict(x) for x in c.execute('SELECT * FROM data.major_link WHERE table_name=? AND record_id=?',(original_table,str(link_id)))]
        if 'institution_link' in _tables(c):institution_links=[dict(x) for x in c.execute('SELECT * FROM data.institution_link WHERE table_name=? AND record_id=?',(original_table,str(link_id)))]
    original = _purchased_original(c, row) if table == 'gk_v_purchased' else None
    lean_evidence=_lean_purchased_evidence(c,row) if table=='gk_v_purchased' and not original else None
    additional_sources=_purchased_additional_sources(c,row) if table=='gk_v_purchased' else []
    annotation=_json(row.get('annotation_json'),[]) if table=='gk_v_purchased' else []
    if not isinstance(annotation,list) or any(not isinstance(pair,list) or len(pair)!=2 for pair in annotation):annotation=[]
    equivalent_sources=[]
    if table == 'employment_major_industry' and 'employment_industry_version' in _tables(c):
        equivalent_sources=[dict(x) for x in c.execute('SELECT * FROM data.employment_industry_version WHERE preferred_source_id=? ORDER BY source_id',(sid,))]
    result = {'table':table,'major_links':major_links,'institution_links':institution_links,'record_id':row.get('record_id',row.get('entry_id',row.get('position_id'))),'field_source_ids':_json(row.get('field_source_ids')) if table == 'gk_v_purchased' else {},'context':{k:row[k] for k in CONTEXT if k in row and row[k] not in (None,'')},'values':values,'source':s,'locator':{k:row[k] for k in ['src_page','src_table','src_sheet','src_row','src_col','src_cell','src_locator','locator','source_locator','locator_method','locator_status'] if k in row},'excerpt':row.get('excerpt') or row.get('field_excerpt') or (original[0] if original else None) or _original_excerpt(_json(row.get('excerpt_locator_json'))),'excerpt_kind':('purchased_row原始单元格' if original else row.get('excerpt_kind') or ('原表摘录或读图定位记录（核验状态另列）' if row.get('excerpt_locator_json') else '原表单元格摘录' if table in ['job_summary','job_position'] else '未取到逐字原文摘录')),'excerpt_locator':_json(row.get('excerpt_locator_json')),'original_locator':original[1] if original else None,'equivalent_sources':equivalent_sources}
    if table=='gk_v_purchased':
        result.update(additional_sources=additional_sources,annotation_json=annotation,
                      annotation_status={'status':'第三方整理未核','note':'原表背景旁注，不是招生适用范围，不参与数字事实身份'})
    if table=='gk_v_purchased' and 'numeric_conflict_fields' in row:
        result['numeric_conflict_fields']=conflict_fields
        if conflict_parse_status:result['numeric_conflict_fields_status']=conflict_parse_status
    if lean_evidence:
        result.update(excerpt=lean_evidence['excerpt'],excerpt_kind=lean_evidence['excerpt_kind'],excerpt_status=lean_evidence['excerpt_status'],original_locator=lean_evidence['locator'])
        if lean_evidence['locator'] is not None:result['locator']=dict(lean_evidence['locator'])
        else:result['locator']={'locator_status':'原件逐行定位未取到，未借用前驱范围外位置'}
    return result


def _purchased_original(c, row):
    rid = row.get('raw_row_id')
    if not rid or 'purchased_row' not in _tables(c): return None
    cols = _cols(c, 'purchased_row')
    wanted = [x for x in ['raw_json','raw_zlib','raw_codec','raw_chunk_id','raw_offset','src_sheet','src_page','src_table','src_row'] if x in cols]
    if 'raw_json' not in wanted: return None
    item = c.execute('SELECT '+','.join(_ident(x) for x in wanted)+' FROM data.purchased_row WHERE row_id=?',(rid,)).fetchone()
    if not item: return None
    d = dict(item); raw = d.get('raw_json')
    try:
        if raw:
            cells=json.loads(raw)
        elif d.get('raw_codec') == 'zlib-utf8-v1' and d.get('raw_zlib'):
            cells=json.loads(zlib.decompress(d['raw_zlib']).decode('utf-8'))
        elif d.get('raw_codec') == 'zlib-json-list-v1' and d.get('raw_chunk_id') is not None and d.get('raw_offset') is not None:
            if 'purchased_raw_chunk' not in _tables(c): return None
            chunk=c.execute('SELECT raw_zlib,row_count FROM data.purchased_raw_chunk WHERE chunk_id=?',(d['raw_chunk_id'],)).fetchone()
            if not chunk or not isinstance(chunk['row_count'],int) or not 1<=chunk['row_count']<=1000: return None
            offset=d['raw_offset']
            if not isinstance(offset,int) or not 0<=offset<chunk['row_count']: return None
            packed_rows=json.loads(zlib.decompress(chunk['raw_zlib']).decode('utf-8'))
            if not isinstance(packed_rows,list) or len(packed_rows)!=chunk['row_count'] or any(not isinstance(x,str) for x in packed_rows): return None
            raw_item=packed_rows[offset]
            cells=json.loads(raw_item)
        else: return None
    except (ValueError,TypeError,OSError,zlib.error,KeyError): return None
    locator={k:d[k] for k in ['src_sheet','src_page','src_table','src_row'] if d.get(k) is not None}
    return cells,locator


def _section(c, table, where, args, limit, offset):
    storage = 'v_employment_major_industry' if table == 'employment_major_industry' and 'v_employment_major_industry' in _tables(c) else table
    cols = _cols(c, storage)
    yf='year' if 'year' in cols else 'plan_year' if 'plan_year' in cols else None
    aggregate='count(*)'+(',min(CAST(t.'+yf+' AS INTEGER)),max(CAST(t.'+yf+' AS INTEGER))' if yf else '')
    totals=c.execute('SELECT '+aggregate+' FROM data.'+_ident(storage)+' t WHERE '+where,args).fetchone()
    total=totals[0];year_range=list(totals[1:]) if yf and totals[1] is not None else []
    order = 'CAST(t.year AS INTEGER) DESC' if 'year' in cols else 't.plan_year DESC' if 'plan_year' in cols else '1'
    rows = c.execute('SELECT t.* FROM data.' + _ident(storage) + ' t WHERE ' + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
    return {'table':table,'title':TITLES.get(table,table),'year_range':year_range,'total':total,'offset':offset,'returned':len(rows),'truncated':max(total-offset-len(rows),0),'rows':[_record(c,table,dict(r)) for r in rows]}


def _bounds(limit, offset):
    if not 1 <= int(limit) <= 200 or int(offset) < 0:
        raise QueryError('limit须为1—200，offset须为非负整数')
    return int(limit), int(offset)


def _warnings(c, identity, sections, year):
    warnings = []
    if 'comparability' in _tables(c):
        years=[int(y) for section in sections for y in section.get('year_range',[]) if y is not None]
        scopes={identity.get('name',''),identity.get('institution_id',''),(identity.get('province') or '').rstrip('省市')}
        scopes|={str(row['context'].get('province','')).rstrip('省市') for section in sections for row in section['rows']}
        scopes.discard('')
        for row in c.execute('SELECT * FROM data.comparability'):
            d = dict(row);scope = str(d.get('scope',''));effective = d.get('effective_year')
            domains={('考研' if x['table'].startswith('ky_') else '高考') for x in sections if x['table'].startswith(('ky_','gk_'))}
            if d.get('domain') and domains and d['domain'] not in domains:continue
            if effective and any(x in scope for x in scopes) and (not years or min(years) <= int(effective) <= max(years)):
                warnings.append('跨年口径：%s %s；影响：%s；出处：%s' % (effective,d.get('change',''),d.get('impact',''),d.get('source_id','未登记')))
    return warnings


def _query_education(name, program=None, year=None, province=None, db=None, limit=10, offset=0, major=None, subject=None, plan_type=None):
    limit, offset = _bounds(limit, offset)
    if program is not None and not re.fullmatch(r'[0-9A-Za-z]{2,12}', str(program)):
        raise QueryError('专业代码只能含字母和数字')
    with _open('education', db) as (c,p):
        ident,warnings = _identity(c,name,year,province);tables=_tables(c);sections=[]
        ky_tables=['ky_v_usable_program' if 'ky_v_usable_program' in tables else 'ky_program_year']+(['ky_v_usable_line'] if 'ky_v_usable_line' in tables else [])+['ky_v_usable']
        candidates = ['institution_profile','gk_plan_entry','gk_official_cutoff','gk_v_usable','gk_v_purchased']+ky_tables if program is None else ['gk_v_purchased']+ky_tables
        candidates.append('ky_v_retest_line' if 'ky_v_retest_line' in tables else 'ky_retest_line')
        entry_ids=None
        if program is None and 'gk_plan_entry' in tables and 'gk_school_code_map' in tables:
            mappings=[dict(x) for x in c.execute('SELECT school_code,province,ingest_id FROM data.gk_school_code_map WHERE institution_id=?',(ident['institution_id'],))]
            conditions=[];mapping_args=[]
            for m in mappings:
                condition='(school_code=? AND province=?';mapping_args.extend([m['school_code'],m['province']])
                if 'ingest_id' in _cols(c,'gk_plan_entry'):condition+=' AND ingest_id=?';mapping_args.append(m['ingest_id'])
                conditions.append(condition+')')
            entry_ids=[x[0] for x in c.execute('SELECT entry_id FROM data.gk_plan_entry WHERE '+' OR '.join(conditions),mapping_args)] if conditions else []
        for table in candidates:
            if table not in tables:continue
            if (major or subject or plan_type) and not table.startswith('gk_'):continue
            cols=_cols(c,table);args=[]
            if 'institution_id' in cols:where='t.institution_id=?';args.append(ident['institution_id'])
            elif 'entry_id' in cols and entry_ids is not None:
                if not entry_ids:continue
                where='t.entry_id IN ('+','.join('?' for _ in entry_ids)+')';args.extend(entry_ids)
            elif 'school_code' in cols and 'gk_school_code_map' in tables:
                where='EXISTS (SELECT 1 FROM data.gk_school_code_map m WHERE m.institution_id=? AND m.school_code=t.school_code AND m.province=t.province'+(' AND m.ingest_id=t.ingest_id' if 'ingest_id' in cols else '')+')';args.append(ident['institution_id'])
            else:continue
            yf='year' if 'year' in cols else 'plan_year' if 'plan_year' in cols else None
            if table=='ky_v_usable_program':where+=' AND (t.planned IS NOT NULL OR t.tuimian IS NOT NULL OR t.subjects IS NOT NULL)'
            if year is not None and yf and table!='institution_profile':where+=' AND CAST(t.'+yf+' AS INTEGER)=?';args.append(int(year))
            if province and 'province' in cols and table.startswith('gk_'):where+=' AND t.province=?';args.append(province)
            if year is None and yf and 'institution_alias' in tables:
                aliases=[dict(x) for x in c.execute('SELECT * FROM data.institution_alias WHERE institution_id=?',(ident['institution_id'],)) if _norm(x['alias'])==_norm(name)]
                if aliases and all(x.get('year') is not None or x.get('year_from') is not None or x.get('year_to') is not None for x in aliases):
                    ranges=[]
                    for a in aliases:
                        lo=a.get('year') if a.get('year') is not None else a.get('year_from');hi=a.get('year') if a.get('year') is not None else a.get('year_to');part=[]
                        if lo is not None:part.append('CAST(t.'+yf+' AS INTEGER)>=?');args.append(lo)
                        if hi is not None:part.append('CAST(t.'+yf+' AS INTEGER)<=?');args.append(hi)
                        ranges.append('('+' AND '.join(part)+')')
                    where+=' AND ('+' OR '.join(ranges)+')'
            if major:
                mf=next((x for x in ['major_name','major'] if x in cols),None)
                if not mf:continue
                where+=' AND t.'+mf+' LIKE ?';args.append('%'+major+'%')
            if subject:
                sf=next((x for x in ['subject','subject_type'] if x in cols),None)
                if not sf:continue
                where+=' AND t.'+sf+' IN (?,?)';args.extend([subject.removesuffix('类'),subject.removesuffix('类')+'类'])
            if plan_type:
                if 'plan_type' not in cols:continue
                where+=' AND t.plan_type=?';args.append(plan_type)
            if program is not None:
                if 'program_code' not in cols:continue
                where+=' AND CAST(t.program_code AS TEXT) LIKE ?';args.append(str(program)+'%')
            if table in ['ky_retest_line','ky_v_retest_line']:
                rawtable='ky_retest_line' if 'ky_retest_line' in tables else table
                if 'verification_status' in _cols(c,rawtable):
                    unclosed=c.execute('SELECT count(*) FROM data.'+_ident(rawtable)+' t WHERE '+where+" AND t.verification_status='原文定位未闭合'",args).fetchone()[0]
                    if unclosed:warnings.append('学校复试线排除原文定位未闭合 '+str(unclosed)+' 行；原表保留，未列为可用。')
                    where+=" AND coalesce(t.verification_status,'')<>'原文定位未闭合'"
                if 'quarantine_reason' in _cols(c,rawtable):
                    isolated=c.execute('SELECT count(*) FROM data.'+_ident(rawtable)+' t WHERE '+where+" AND coalesce(t.quarantine_reason,'')<>''",args).fetchone()[0]
                    if isolated:warnings.append('学校复试线另排除隔离记录 '+str(isolated)+' 行。')
            if 'quarantine_reason' in cols:where+=" AND coalesce(t.quarantine_reason,'')=''"
            sec=_section(c,table,where,args,limit,offset)
            if sec['total']:sections.append(sec)
        warnings += _warnings(c,ident,sections,year)
        if program:warnings.append('仅对研究生专业码作前缀检索；逐行保留具体代码，不与本科专业码直接相等连接。')
        warnings.append('各行学院、方向、学习方式、专项、联培、志愿及计划类型独立呈现，未合并；未见口径变更记录不代表口径稳定。')
        return {'query':'program' if program else 'school','database':str(p),'identity':ident,'sections':sections,'warnings':warnings}


def query_school(name, *, year=None, province=None, db=None, limit=10, offset=0, major=None, subject=None, plan_type=None):
    return _query_education(name,year=year,province=province,db=db,limit=limit,offset=offset,major=major,subject=subject,plan_type=plan_type)


def query_program(name, program, *, year=None, province=None, db=None, limit=10, offset=0):
    return _query_education(name,program=program,year=year,province=province,db=db,limit=limit,offset=offset)


def query_jobs(*, region=None, major=None, year=None, db=None, education_db=None, limit=10, offset=0):
    limit,offset=_bounds(limit,offset)
    with _open('employment',db,education_db) as (c,p):
        tables=_tables(c);sections=[];unknown_cohort_included=False
        for table in ['job_summary' if 'job_summary' in tables else 'job_position','wage_stat','competition_stat','civil_major_summary','selected_university','recruitment_notice','industry_stat','graduate_destination','employment_major_industry']:
            if table not in tables:continue
            cols=_cols(c,table);where='1=1';args=[]
            if table=='graduate_destination' and major:continue # source has no graduate-major dimension
            if region and table=='graduate_destination':
                if not {'category','item'}<=cols:continue
                where+=" AND t.category='地区' AND t.item LIKE ?";args.append('%'+region+'%')
            elif region:
                loc=[x for x in ['region','province','scope','province_raw','city_raw'] if x in cols]
                if not loc:continue
                where+=' AND ('+' OR '.join('t.'+_ident(x)+' LIKE ?' for x in loc)+')';args += ['%'+region+'%']*len(loc)
            if major:
                names=[x for x in ['major_code','major_name','major_clause','major_restriction','group','position','title','note','notes','category','item','item_raw'] if x in cols]
                if not names:continue
                where+=' AND ('+' OR '.join('t.'+_ident(x)+' LIKE ?' for x in names)+')';args+=['%'+major+'%']*len(names)
            if table=='graduate_destination' and year is not None and 'graduate_cohort' in cols:
                cohort_expr="CAST(substr(trim(t.graduate_cohort),1,4) AS INTEGER)"
                unknown_expr="(t.graduate_cohort IS NULL OR trim(t.graduate_cohort)='' OR " + cohort_expr + " NOT BETWEEN 1900 AND 2100)"
                unknown_n=c.execute('SELECT count(*) FROM data.'+_ident(table)+' t WHERE '+where+' AND '+unknown_expr,args).fetchone()[0]
                if unknown_n:unknown_cohort_included=True
                where+=' AND ('+unknown_expr+' OR '+cohort_expr+'=?)';args.append(int(year))
            if year is not None and 'year' in cols:where+=' AND t.year=?';args.append(int(year))
            sec=_section(c,table,where,args,limit,offset)
            if sec['total']:sections.append(sec)
        warnings=['工资是原调查在岗群体分位值，单位逐项列明，不等于应届起薪。','报名人数/名额是群体竞争口径，不是个人录用概率；专业关键词仅筛选原条款，不构成报考资格认定。','本科专业只按major_link的专业层级与全名精确关系解释，不将地方专业代码或研究生代码盲目等同。']
        if major and 'graduate_destination' in tables:warnings.append('院校就业去向原表没有按专业统计，专业筛选时不列入；学校所在地或单位名称不等同于某专业的就业去向。')
        if any(sec['table']=='employment_major_industry' for sec in sections):
            warnings.append('专业就业行业分布为第三方历史参考；届别未注明，不能视为查询年份或单独支撑报告结论；未写百分号的占比数值不自动换算为百分比。')
            if 'employment_industry_version' in tables:
                warnings.append('行业表的已入库匿名片段逐格相同者只显示一份；各原件来源与片段指纹保留在 employment_industry_version，未据此认定原文件字节相同或官方已核。')
        if unknown_cohort_included:warnings.append('院校就业去向中仍列出届别未注明或无法解析的记录；未知届别不代表查询年份，只有明确届别与查询年份相符的记录才按该年份筛选。')
        return {'query':'jobs','database':str(p),'sections':sections,'warnings':warnings}


def query_source(source_id, *, db=None, domain='education', limit=10, offset=0):
    limit,offset=_bounds(limit,offset)
    with _open(domain,db) as (c,p):
        s=_source(c,source_id)
        if s['source_id']=='未登记' or s.get('grade')=='未注明':raise QueryError('未找到来源编号：'+source_id)
        locations=[];counts={}
        for table in sorted(_tables(c)):
            if table not in set(NUMERIC)|{'institution_event','comparability','selected_university','recruitment_notice'}:continue
            cols=_cols(c,table)
            if 'source_id' not in cols:continue
            count=c.execute('SELECT count(*) FROM data.'+_ident(table)+' WHERE source_id=?',(source_id,)).fetchone()[0]
            if not count:continue
            counts[table]=count
            rows=c.execute('SELECT * FROM data.'+_ident(table)+' WHERE source_id=? LIMIT ? OFFSET ?',(source_id,limit,offset))
            for row in rows:
                r=dict(row)
                if table=='gk_v_purchased':
                    detailed=_record(c,table,r)
                    locations.append({k:detailed[k] for k in ('table','locator','excerpt','excerpt_kind','excerpt_locator','original_locator','additional_sources','annotation_json','annotation_status','numeric_conflict_fields','numeric_conflict_fields_status') if k in detailed})
                    continue
                locations.append({'table':table,'locator':{k:r[k] for k in ['record_id','src_page','src_table','src_sheet','src_row','src_col','src_cell','src_locator','locator'] if k in r},'excerpt':r.get('excerpt') or r.get('field_excerpt') or _original_excerpt(_json(r.get('excerpt_locator_json'))),'excerpt_kind':r.get('excerpt_kind') or ('原表摘录或读图定位记录（核验状态另列）' if r.get('excerpt_locator_json') else '未取到逐字原文摘录'),'excerpt_locator':_json(r.get('excerpt_locator_json'))})
        return {'query':'source','database':str(p),'source':s,'locations':locations,'matching_rows_by_table':counts,'limit_per_table':limit,'offset':offset,'warnings':['未留存逐字摘录时明确显示未取到；结构化整理记录不冒充官网逐字原文。']}


def _value_text(v):
    status=v['value_status'].get('status','未标记（待核）')
    raw=v['value']
    if raw is None or raw=='':
        text='未公布' if status=='未公布' else '人数太少未公布' if status=='人数太少未公布' else '原件缺失' if status=='原件缺失' else '来源未提供' if status=='来源未提供' else status
    else:text=str(raw)+((' '+v['unit']) if v.get('unit') else '')
    rendered = '%s〔%s｜%s｜%s；%s〕' % (text,v['grade'],v['publisher'],v['source_id'],status)
    if 'official_locator' in v:
        if v['official_locator']:
            rendered += '；官方位置：' + _plain(v['official_locator'])
        elif v.get('official_locator_candidates'):
            rendered += '；官方位置待核（多个匹配位置）：' + _plain(v['official_locator_candidates'])
        else:
            rendered += '；官方位置：未取到'
    if v.get('numeric_conflict'):rendered+='；'+v['numeric_conflict']['reason']
    return rendered


CONTEXT_LABELS = dict(zip(CONTEXT, ['年份','计划年份','省份','地区','学院','研究生专业码','研究生专业','本科原专业码','本科专业','学位','学习方式','方向','联培','专项','志愿类型','线的范围','名单类型','统计范围','口径是否一致','口径差异','计划类型','科类','科类','批次','专业组','专业组','岗位编号','单位','岗位','学历条件','学位条件','专业条款','分组口径','分组','类别','学校','原校名','核验状态','原备注','原备注','院校标签','办学层次','硕士点原名单','博士点原名单','年份状态']))

CONTEXT_LABELS.update({'industry':'原列就业行业','unit_raw':'原列单位','value_raw':'原格占比','cohort':'原列毕业届别'})
CONTEXT_LABELS['subjects']='考试科目'
CONTEXT_LABELS.update({'graduate_cohort':'毕业届别（原表）','graduate_cohort_raw':'届别原文','cohort_status':'届别状态','province_raw':'学校所在省（原表）','city_raw':'学校所在市（原表）','institution_name_raw':'院校名称（原表）','item':'就业项目','item_raw':'项目原文','record_type':'记录类型','dataset_type':'数据类型','school_raw':'院校原名','group_name':'专业组名称','subject_requirements':'选科要求','scope_raw':'原表范围说明'})

def _plain(obj):
    if isinstance(obj,dict):return '；'.join(str(k)+'：'+_plain(v) for k,v in obj.items())
    if isinstance(obj,list):return ' / '.join(_plain(v) for v in obj)
    return str(obj) if obj is not None else '未提供'

def render_text(result):
    lines=[]
    identity=result.get('identity')
    if identity:
        lines.append('学校身份：%s｜%s｜%s｜%s' % (identity.get('name',''),identity['institution_id'],identity.get('province',''),identity.get('status') or '存续状态未提供'))
        lines.append('存续：设立='+str(identity.get('established') or '未取到')+'；结束='+str(identity.get('closed') or '未取到')+'；继任标识码='+str(identity.get('successor_id') or '未提供')+'；母校/上级关系='+str(identity.get('parent_id') or '未提供')+'；状态出处='+str(identity.get('status_source_id') or '未登记'))
        for e in identity.get('events',[]):lines.append('沿革：%s → %s｜%s｜%s｜出处 %s' % (e.get('name_before',''),e.get('name_after',''),e.get('effective',''),e.get('status',''),e.get('source_id','未登记')))
    if result.get('query')=='source':
        s=result['source'];lines.append('来源明细（逐项一行）')
        for label,key in [('出处编号','source_id'),('等级','grade'),('发布单位','publisher'),('标题','title'),('公告原网址','landing_url'),('附件直链','file_url'),('原件字节存档状态','archive_status'),('原件路径','archive_path'),('指纹SHA256','archive_sha256'),('发布日期','published'),('取文日期','retrieved'),('引用','citation'),('说明','note')]:lines.append(label+'：'+str(s.get(key) or '未取到/未提供'))
        for x in result['locations']:
            lines.append('定位：'+x['table']+'｜'+_plain(x['locator']))
            lines.append('摘录口径：'+x['excerpt_kind']);lines.append('摘录：'+(_plain(_json(x['excerpt'], x['excerpt'])) if x.get('excerpt') else '未取到逐字摘录'))
            if x['excerpt_locator']:lines.append('原文摘录定位：'+_plain(x['excerpt_locator']))
            if x.get('annotation_json'):lines.append('原表背景旁注（第三方整理未核，不作招生范围）：'+_plain(x['annotation_json']))
            if x.get('numeric_conflict_fields'):lines.append('第三方版本冲突字段：'+'、'.join(LABELS.get(field,field) for field in dict.fromkeys(x['numeric_conflict_fields']))+'；'+NUMERIC_CONFLICT_NOTE)
            if x.get('numeric_conflict_fields_status'):lines.append(x['numeric_conflict_fields_status'])
            if x.get('additional_sources'):lines.append('额外来源：'+' / '.join(str(item.get('source_id') or '来源未取到')+'；'+_plain(item['locator']) for item in x['additional_sources']))
        for table,total in result['matching_rows_by_table'].items():
            shown=sum(x['table']==table for x in result['locations']);lines.append('%s：共%s行，offset=%s，本页%s行，后续%s行未显示' % (table,total,result['offset'],shown,max(0,total-result['offset']-shown)))
    for sec in result.get('sections',[]):
        lines.extend(['',sec['title']+'：共%d行，偏移%d，本页%d行，后续%d行未显示' % (sec['total'],sec['offset'],sec['returned'],sec['truncated']),'适用范围 | 数值（等级｜发布单位｜出处编号；质量状态）','--- | ---'])
        for r in sec['rows']:
            def shown_context(k,v):
                text=str(v)
                cap=200 if k=='scope_raw' else 180
                if len(text)>cap:return text[:cap]+'…（本格文字共'+str(len(text))+'字，全文见--json）'
                return text
            context_labels=CONTEXT_LABELS if sec['table']!='employment_major_industry' else {**CONTEXT_LABELS,'major_code':'原专业码','major_name':'专业名称'}
            context='；'.join('%s：%s' % (context_labels.get(k,k), shown_context(k,v)) for k,v in r['context'].items()) or '原件未给适用范围'
            if r.get('original_locator'):context+='；原始单元格定位：'+_plain(r['original_locator'])
            if r.get('excerpt_kind') and (r.get('excerpt') or r.get('excerpt_status')):context+='；摘录口径：'+r['excerpt_kind']
            if r.get('annotation_json'):context+='；原表背景旁注（第三方整理未核，不作招生范围）：'+shown_context('annotation_json',_plain(r['annotation_json']))
            if r.get('numeric_conflict_fields'):context+='；第三方版本冲突字段：'+'、'.join(LABELS.get(field,field) for field in dict.fromkeys(r['numeric_conflict_fields']))+'；'+NUMERIC_CONFLICT_NOTE
            if r.get('numeric_conflict_fields_status'):context+='；'+r['numeric_conflict_fields_status']
            if r.get('additional_sources'):context+='；额外来源：'+' / '.join(str(x.get('source_id') or '来源未取到')+'；'+_plain(x['locator']) for x in r['additional_sources'])
            image_refs=(r.get('excerpt_locator') or {}).get('root_verified_image_references',[])
            if image_refs:context+='；读图定位：'+' / '.join('读图；'+str(x.get('locator') or '位置未提供')+'；SHA256='+str(x.get('sha256') or '未提供')+'；出处='+str(x.get('source_id') or '未提供') for x in image_refs)
            if r.get('major_links'):context+='；本科专业字典：'+' / '.join(str(x.get('major_name',''))+'（'+str(x.get('discipline_level',''))+' '+str(x.get('discipline_code',''))+'；原地方代码 '+str(x.get('source_major_code') or '未标')+'）' for x in r['major_links'])+'；仅条款列出，不等于其他条件合格'
            if r.get('institution_links'):context+='；学校身份关联：'+' / '.join(str(x.get('institution_id',''))+'（'+str(x.get('match_method',''))+'）' for x in r['institution_links'])
            vals='；'.join(v.get('display_label',('签约人数' if sec['table']=='graduate_destination' and k=='headcount' else '名次' if sec['table']=='graduate_destination' and k=='rank' else LABELS.get(k,k)))+'：'+_value_text(v) for k,v in r['values'].items()) or '本条为文字范围/公告状态，未给数值'
            lines.append(context.replace('\n',' ')+' | '+vals.replace('\n',' '))
    for w in result.get('warnings',[]):lines.append('提示：'+w)
    if not result.get('sections') and result.get('query')!='source':lines.append('未取到匹配业务记录；不代表学校或专业未招生。')
    return '\n'.join(lines)+'\n'


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv[:2]==['detail','source']:argv=argv[1:]
    ap=argparse.ArgumentParser(description='知衢本机统一只读查询；来源链与适用范围不合并')
    sub=ap.add_subparsers(dest='command',required=True)
    for cmd in ['school','program','jobs','source']:
        p=sub.add_parser(cmd);p.add_argument('--db');p.add_argument('--json',action='store_true');p.add_argument('--limit',type=int,default=10);p.add_argument('--offset',type=int,default=0)
        if cmd in ['school','program']:p.add_argument('school');p.add_argument('--year',type=int);p.add_argument('--province')
        if cmd=='school':p.add_argument('--major');p.add_argument('--subject');p.add_argument('--plan-type')
        if cmd=='program':p.add_argument('program')
        if cmd=='jobs':p.add_argument('--region');p.add_argument('--major');p.add_argument('--year',type=int);p.add_argument('--education-db')
        if cmd=='source':p.add_argument('source_id');p.add_argument('--domain',choices=['education','employment'],default='education')
    ns=vars(ap.parse_args(argv));command=ns.pop('command');as_json=ns.pop('json')
    try:
        if command=='school':res=query_school(ns.pop('school'),**ns)
        elif command=='program':res=query_program(ns.pop('school'),ns.pop('program'),**ns)
        elif command=='jobs':res=query_jobs(**ns)
        else:res=query_source(ns.pop('source_id'),**ns)
        print(json.dumps(res,ensure_ascii=False,indent=2) if as_json else render_text(res),end='\n' if as_json else '')
    except (QueryError,sqlite3.Error) as e:ap.exit(2,'查询未完成：'+str(e)+'\n')
    return 0

if __name__=='__main__':main()
