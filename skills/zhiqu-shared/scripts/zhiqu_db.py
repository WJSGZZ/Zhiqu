#!/usr/bin/env python3
"""Read-only, provenance-preserving queries for Zhiqu's two local databases.

Public API: query_school, query_program, query_jobs, query_source. Results are
plain dictionaries; render_text renders the same result without hiding limits.
No SQL string supplied by a caller is executed. All database files are attached
with mode=ro to an in-memory connection.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

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
}
NUMERIC['ky_v_usable_line']=['line_total','politics','english','math','major','single_100','single_over_100']
NUMERIC['ky_v_usable_program']=['planned','tuimian']
NUMERIC['ky_v_usable']=['n','min','q1','median','q3','max','mean','excluded_count']
LABELS = {'total':'总分','line_total':'复试总分','politics':'原列政治/首科（须核口径）','english':'外语','math':'数学','major':'业务课','major1':'业务课一','major2':'业务课二','single_100':'单科满分100门槛','single_over_100':'单科满分超过100门槛','planned':'招生人数','tuimian':'推免人数','n':'样本人数','min':'最低','q1':'下四分位','median':'中位数','q3':'上四分位','max':'最高','mean':'平均','excluded_count':'排除数','recommend_rate':'保研比例','n_master':'硕士点','n_phd':'博士点','school_rank':'原表排名','plan_n':'计划人数','group_plan_n':'专业组人数','years':'学制','tuition':'学费','plan':'计划人数','admit':'录取人数','score':'最低分','rank':'最低位次','min_score':'最低分','min_rank':'最低位次','headcount':'招录人数','paid_applicants':'缴费人数','paid_per_seat':'缴费人数/名额','p10':'10%分位','p25':'25%分位','p50':'中位数','p75':'75%分位','p90':'90%分位','n_jobs':'职位数','share':'原表比例','share_below_10':'低于10人/名额的职位比例','share_100_plus':'100人/名额以上职位比例'}
TITLES = {'institution_profile':'学校概况（第三方，年份未明单列）','gk_plan_entry':'高考招生计划','gk_official_cutoff':'高考官方投档线','gk_v_usable':'高考整理录取记录','ky_program_year':'考研目录与往年线','ky_v_usable':'考研分布与可用历史记录','ky_v_retest_line':'学校官网复试线（保留核验状态）','ky_retest_line':'学校官网复试线（保留核验状态）','job_summary':'岗位与匿名报名人数','job_position':'岗位','wage_stat':'在岗工资调查（不代表应届起薪）','competition_stat':'匿名群体竞争统计（非个人概率）','civil_major_summary':'本科专业可报岗位汇总','selected_university':'选调高校范围','recruitment_notice':'招聘公告可用性','industry_stat':'行业统计'}
CONTEXT = ['year','plan_year','province','region','college','program_code','program_name','major_code','major_name','degree_type','study_mode','direction','joint_program','special_plan','admission_route','line_scope','list_type','scope','scope_mismatch','scope_mismatch_note','plan_type','subject','subject_type','batch','group_code','grp','position_id','unit','position','education','degree','major_clause','group_type','group','category','school','school_name','verification_status','note','notes','school_tags','degree_level','master_list','phd_list','year_status']


CONTEXT.append('subjects')

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


def _record(c, table, row):
    sid = row.get('source_id')
    if not sid and row.get('src_file') is not None:
        sid = 'vendor-file-' + str(row['src_file'])
    s = _source(c, sid)
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
        value_sid = row.get('application_source_id') if field == 'paid_applicants' else sid
        src = _source(c, value_sid) if value_sid != sid else s
        if table == 'gk_v_usable' and 'gk_check_sample' in _tables(c):
            chk=c.execute("SELECT official_source_id FROM data.gk_check_sample WHERE entry_id=? AND year=? AND field=? AND table_name='result' AND verdict='不一致'",(row.get('entry_id'),row.get('year'),field)).fetchall()
            ids={x[0] for x in chk if x[0]}
            if len(ids)==1:value_sid=next(iter(ids));src=_source(c,value_sid)
            elif len(ids)>1:vs={'status':'待核','reason':'对应多条官方纠错来源，不选一条冒充唯一出处'}
        if field=='paid_applicants' and 'job_application' in _tables(c) and row.get('position_id'):
            app=c.execute('SELECT value_status FROM data.job_application WHERE position_id=? AND source_id=?',(row['position_id'],value_sid)).fetchall()
            if len(app)==1:vs=_status({'value_status':app[0][0]},'paid_applicants')
        values[field] = {'value': row[field], 'unit': _unit(table, field, row), 'grade': src.get('grade') or row.get('source_grade') or '未注明', 'publisher': src.get('publisher') or '未注明', 'source_id': value_sid or '未登记', 'value_status': vs}
        if table.startswith('ky_') and generic_subjects and field in ['politics','english','math','major','major1','major2']:
            values[field]['display_label']='历史槽位（原表按满分档或科目编号列示，见范围）'
            values[field]['subject_mapping_status']='不从旧槽位反推政治/英语/数学或两档值；原值保留'
        if field == 'paid_per_seat':
            inputs=[_source(c,x) for x in [sid,row.get('application_source_id')] if x]
            values[field]['source_id']=' + '.join(x['source_id'] for x in inputs)
            values[field]['publisher']='、'.join(dict.fromkeys(x.get('publisher','未注明') for x in inputs))
            values[field]['grade']='官方' if inputs and all(x.get('grade')=='官方' for x in inputs) else '第三方整理' if any(x.get('grade')=='第三方整理' for x in inputs) else '未注明'
            values[field]['value_status'] = {'status':'推算','method':'缴费人数÷招录名额；群体人数/名额，非个人概率','inputs_source_ids':[sid,row.get('application_source_id')]}
    major_links=[];institution_links=[]
    link_id=row.get('record_id',row.get('position_id'))
    if link_id is not None:
        original_table='job_position' if table=='job_summary' else table
        if 'major_link' in _tables(c):major_links=[dict(x) for x in c.execute('SELECT * FROM data.major_link WHERE table_name=? AND record_id=?',(original_table,str(link_id)))]
        if 'institution_link' in _tables(c):institution_links=[dict(x) for x in c.execute('SELECT * FROM data.institution_link WHERE table_name=? AND record_id=?',(original_table,str(link_id)))]
    return {'table':table,'major_links':major_links,'institution_links':institution_links,'record_id':row.get('record_id',row.get('entry_id',row.get('position_id'))),'context':{k:row[k] for k in CONTEXT if k in row and row[k] not in (None,'')},'values':values,'source':s,'locator':{k:row[k] for k in ['src_page','src_table','src_sheet','src_row','src_locator','locator','source_locator','locator_method','locator_status'] if k in row},'excerpt':row.get('excerpt') or row.get('field_excerpt') or _original_excerpt(_json(row.get('excerpt_locator_json'))),'excerpt_kind':row.get('excerpt_kind') or ('原表摘录或读图定位记录（核验状态另列）' if row.get('excerpt_locator_json') else '原表单元格摘录' if table in ['job_summary','job_position'] else '未取到逐字原文摘录'),'excerpt_locator':_json(row.get('excerpt_locator_json'))}


def _section(c, table, where, args, limit, offset):
    cols = _cols(c, table)
    yf='year' if 'year' in cols else 'plan_year' if 'plan_year' in cols else None
    aggregate='count(*)'+(',min(CAST(t.'+yf+' AS INTEGER)),max(CAST(t.'+yf+' AS INTEGER))' if yf else '')
    totals=c.execute('SELECT '+aggregate+' FROM data.'+_ident(table)+' t WHERE '+where,args).fetchone()
    total=totals[0];year_range=list(totals[1:]) if yf and totals[1] is not None else []
    order = 'CAST(t.year AS INTEGER) DESC' if 'year' in cols else 't.plan_year DESC' if 'plan_year' in cols else '1'
    rows = c.execute('SELECT t.* FROM data.' + _ident(table) + ' t WHERE ' + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
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
        candidates = ['institution_profile','gk_plan_entry','gk_official_cutoff','gk_v_usable']+ky_tables if program is None else ky_tables
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
        tables=_tables(c);sections=[]
        for table in ['job_summary' if 'job_summary' in tables else 'job_position','wage_stat','competition_stat','civil_major_summary','selected_university','recruitment_notice','industry_stat']:
            if table not in tables:continue
            cols=_cols(c,table);where='1=1';args=[]
            if region:
                loc=[x for x in ['region','province','scope'] if x in cols]
                if not loc:continue
                where+=' AND ('+' OR '.join('t.'+_ident(x)+' LIKE ?' for x in loc)+')';args += ['%'+region+'%']*len(loc)
            if major:
                names=[x for x in ['major_name','major_clause','major_restriction','group','position','title','note','notes'] if x in cols]
                if not names:continue
                where+=' AND ('+' OR '.join('t.'+_ident(x)+' LIKE ?' for x in names)+')';args+=['%'+major+'%']*len(names)
            if year is not None and 'year' in cols:where+=' AND t.year=?';args.append(int(year))
            sec=_section(c,table,where,args,limit,offset)
            if sec['total']:sections.append(sec)
        return {'query':'jobs','database':str(p),'sections':sections,'warnings':['工资是原调查在岗群体分位值，单位逐项列明，不等于应届起薪。','报名人数/名额是群体竞争口径，不是个人录用概率；专业关键词仅筛选原条款，不构成报考资格认定。','本科专业只按major_link的专业层级与全名精确关系解释，不将地方专业代码或研究生代码盲目等同。']}


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
                r=dict(row);locations.append({'table':table,'locator':{k:r[k] for k in ['record_id','src_page','src_table','src_sheet','src_row','src_locator','locator'] if k in r},'excerpt':r.get('excerpt') or r.get('field_excerpt') or _original_excerpt(_json(r.get('excerpt_locator_json'))),'excerpt_kind':r.get('excerpt_kind') or ('原表摘录或读图定位记录（核验状态另列）' if r.get('excerpt_locator_json') else '未取到逐字原文摘录'),'excerpt_locator':_json(r.get('excerpt_locator_json'))})
        return {'query':'source','database':str(p),'source':s,'locations':locations,'matching_rows_by_table':counts,'limit_per_table':limit,'offset':offset,'warnings':['未留存逐字摘录时明确显示未取到；结构化整理记录不冒充官网逐字原文。']}


def _value_text(v):
    status=v['value_status'].get('status','未标记（待核）')
    raw=v['value']
    if raw is None or raw=='':
        text='未公布' if status=='未公布' else '人数太少未公布' if status=='人数太少未公布' else '原件缺失' if status=='原件缺失' else '来源未提供' if status=='来源未提供' else status
    else:text=str(raw)+((' '+v['unit']) if v.get('unit') else '')
    return '%s〔%s｜%s｜%s；%s〕' % (text,v['grade'],v['publisher'],v['source_id'],status)


CONTEXT_LABELS = dict(zip(CONTEXT, ['年份','计划年份','省份','地区','学院','研究生专业码','研究生专业','本科原专业码','本科专业','学位','学习方式','方向','联培','专项','志愿类型','线的范围','名单类型','统计范围','口径是否一致','口径差异','计划类型','科类','科类','批次','专业组','专业组','岗位编号','单位','岗位','学历条件','学位条件','专业条款','分组口径','分组','类别','学校','原校名','核验状态','原备注','原备注','院校标签','办学层次','硕士点原名单','博士点原名单','年份状态']))

CONTEXT_LABELS['subjects']='考试科目'

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
        for table,total in result['matching_rows_by_table'].items():
            shown=sum(x['table']==table for x in result['locations']);lines.append('%s：共%s行，offset=%s，本页%s行，后续%s行未显示' % (table,total,result['offset'],shown,max(0,total-result['offset']-shown)))
    for sec in result.get('sections',[]):
        lines.extend(['',sec['title']+'：共%d行，偏移%d，本页%d行，后续%d行未显示' % (sec['total'],sec['offset'],sec['returned'],sec['truncated']),'适用范围 | 数值（等级｜发布单位｜出处编号；质量状态）','--- | ---'])
        for r in sec['rows']:
            context='；'.join('%s：%s' % (CONTEXT_LABELS.get(k,k), str(v) if len(str(v))<=180 else str(v)[:180]+'…（本格文字共'+str(len(str(v)))+'字，全文见--json）') for k,v in r['context'].items()) or '原件未给适用范围'
            if r.get('excerpt') and r.get('excerpt_kind'):context+='；摘录口径：'+r['excerpt_kind']
            image_refs=(r.get('excerpt_locator') or {}).get('root_verified_image_references',[])
            if image_refs:context+='；读图定位：'+' / '.join('读图；'+str(x.get('locator') or '位置未提供')+'；SHA256='+str(x.get('sha256') or '未提供')+'；出处='+str(x.get('source_id') or '未提供') for x in image_refs)
            if r.get('major_links'):context+='；本科专业字典：'+' / '.join(str(x.get('major_name',''))+'（'+str(x.get('discipline_level',''))+' '+str(x.get('discipline_code',''))+'；原地方代码 '+str(x.get('source_major_code') or '未标')+'）' for x in r['major_links'])+'；仅条款列出，不等于其他条件合格'
            if r.get('institution_links'):context+='；学校身份关联：'+' / '.join(str(x.get('institution_id',''))+'（'+str(x.get('match_method',''))+'）' for x in r['institution_links'])
            vals='；'.join(v.get('display_label',LABELS.get(k,k))+'：'+_value_text(v) for k,v in r['values'].items()) or '本条为文字范围/公告状态，未给数值'
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
