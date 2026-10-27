#!/usr/bin/env python3
"""Read-only, provenance-preserving queries for Zhiqu's two local databases.

Public API: query_school, query_program, query_jobs, query_source. Results are
plain dictionaries; render_text renders the same result without hiding limits.
No SQL string supplied by a caller is executed. All database files are attached
with mode=ro to an in-memory connection.
"""
import argparse
import contextlib
import csv
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
import zlib
import importlib.util

_storage_spec = importlib.util.spec_from_file_location('zhiqu_db_storage', Path(__file__).with_name('db_storage.py'))
_storage = importlib.util.module_from_spec(_storage_spec)
_storage_spec.loader.exec_module(_storage)

_export_rules_spec = importlib.util.spec_from_file_location('zhiqu_query_export_rules', Path(__file__).with_name('gaokao_export.py'))
_export_rules = importlib.util.module_from_spec(_export_rules_spec)
_export_rules_spec.loader.exec_module(_export_rules)

SHARED = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = {k: SHARED / 'data' / k / (k + '.sqlite') for k in ('education', 'employment')}
# Only these recorded source meanings explicitly identify a per-score count.
# Unspecified “人数”, cumulative counts and derived counts cannot close a gap.
SEGMENT_COUNT_KINDS = frozenset({
    '分段人数（原列）', '原分段人数', '原表分别明示人数与累计人数',
    '原表分别明示人数小计与人数累计', '原表本分人数',
    '原表本段与累计人数分列', '原表本段人数/累计人数；空人数不推算',
    '本分数人数', '本段人数/累计人数/累计比例%原表分列',
})

class QueryError(ValueError):
    pass


def _source_completeness(c, table, source_id):
    if 'meta' not in _tables(c):return None
    prefix='gk_source_coverage:'+str(source_id)+':'+table+':'
    row=c.execute('SELECT value FROM data.meta WHERE key>=? AND key<? ORDER BY rowid DESC LIMIT 1',(prefix,prefix+'\uffff')).fetchone()
    if not row:return None
    value=_json(row[0],{})
    if value.get('source_id')!=source_id or value.get('table_name')!=table or not isinstance(value.get('missing_rows'),list):raise QueryError('原表完整性记录损坏：'+str(source_id))
    return value


def _completeness_text(value, full=False):
    if not value or value.get('status')!='partial':return ''
    missing=value['missing_rows'];shown=missing if full else missing[:12]
    positions='、'.join(f"页{x['page']}/表{x['table']}/行{x['row']}" for x in shown)
    text=f"原表不完整：原件{value['original_rows']}行，已核入{value['accepted_rows']}行；缺{len(missing)}行"
    if positions:text+='（'+positions+'）'
    if len(missing)>len(shown):text+='；--full查看全部缺行及原因'
    if full and missing:text+='；排除原因：'+'；'.join(dict.fromkeys(x['reason'] for x in missing))
    if value.get('missing_scope'):text+='；'+value['missing_scope']
    return text


def _yfyd_current_evidence(c, rows):
    """Resolve explicit root-approved typed field proofs; never rewrite stored states."""
    if not rows:return
    tables=_tables(c);sources={};assets={};bykey={}
    for row in rows:
        sid=row['source_id']
        if sid not in sources:
            sources[sid]=_source(c,sid)
            assets[sid]=[dict(r)for r in c.execute('SELECT source_id,sha256,url,role,retrieved FROM data.source_asset WHERE source_id=?',(sid,))] if 'source_asset'in tables else []
        row['_source_assets']=assets[sid];row['_evidence_refs']=[];row['_field_evidence']={};row['_current_states']={}
        bykey[(sid,row['province'],row['year'],row['subject'],row['score'])]=row
    if 'gk_official_original_evidence'not in tables:return
    digest=lambda value:isinstance(value,str)and re.fullmatch(r'[0-9a-f]{64}',value)is not None
    def json_sql_type(value):
        if value is None:return 'null'
        if type(value)is int:return 'integer'
        if type(value)is float:return 'real'
        if type(value)is str:return 'text'
        return 'invalid'
    for sid in sources:
        for evidence in c.execute("SELECT record_id,source_id,excerpt_locator_json FROM data.gk_official_original_evidence WHERE source_id=? AND table_name='gk_official_yfyd' ORDER BY rowid DESC",(sid,)):
            payload=_json(evidence['excerpt_locator_json'])
            if not isinstance(payload,dict):continue
            key=payload.get('business_key',{})
            if not isinstance(key,dict)or set(key)!={'province','year','subject','score'}:continue
            lookup=(sid,key['province'],key['year'],key['subject'],key['score']);row=bykey.get(lookup)
            if row is None or any(type(key[k])is not type(row[k])for k in key):continue
            review=payload.get('review',{});locator=payload.get('locator',{})
            if not isinstance(review,dict)or not isinstance(locator,dict):continue
            fingerprint=locator.get('sha256')
            linked=next((a for a in assets[sid]if a.get('sha256')==fingerprint),None)
            if linked is None and digest(fingerprint)and sources[sid].get('archive_sha256')==fingerprint:
                linked={'source_id':sid,'sha256':fingerprint,'url':sources[sid].get('file_url')or sources[sid].get('landing_url'),'role':'source_original'}
            contract=(review.get('status')=='approved'and review.get('approved_by')=='root'and review.get('scope_verified')is True and isinstance(payload.get('scope'),dict)and bool(payload['scope'])and digest(review.get('manifest_sha256'))and digest(review.get('sample_proof_sha256'))and digest(fingerprint)and linked is not None and sources[sid].get('grade')=='官方')
            reference={'record_id':evidence['record_id'],'source_id':sid,'locator':locator,'source_asset':linked,'review_status':review.get('status'),'approved_by':review.get('approved_by'),'scope_verified':review.get('scope_verified')is True,'manifest_sha256':review.get('manifest_sha256'),'sample_proof_sha256':review.get('sample_proof_sha256'),'root_asset_scope_contract_passed':bool(contract),'scope':payload.get('scope')}
            row['_evidence_refs'].append(reference)
            if not contract:continue
            verified=payload.get('verified_fields',review.get('verified_fields',{}))
            if not isinstance(verified,dict):continue
            for field,value_key,type_key in [('score','score','_score_type'),('cum','cum','_cum_type'),('segment_n','_segment_n','_segment_type'),('count_raw','_count_raw','_count_raw_type')]:
                value=row.get(value_key);proof=verified.get(field)
                if value is None or field not in verified:continue
                stated=proof.get('value')if isinstance(proof,dict)else proof
                declared=proof.get('sqlite_type')if isinstance(proof,dict)else json_sql_type(stated)
                if stated!=value or type(stated)is not type(value)or declared!=row.get(type_key)or json_sql_type(stated)!=row.get(type_key):continue
                if field in row['_field_evidence']:continue
                row['_field_evidence'][field]=dict(reference,field=field,verified_value=stated,sqlite_type=declared)
                row['_current_states'][field]={'status':'官方原值','reason':'追加原件审计由root批准；同业务键/范围/来源成员及本字段原值、SQLite类型核对一致','evidence_record_id':evidence['record_id']}


def _yfyd_rows(c, province, year, subject):
    """One original-count gate shared by SQLite lookup and annual CSV export."""
    context_columns={r[1] for r in c.execute('PRAGMA data.table_info(gk_yfyd_context)')}
    if {'segment_n','count_kind','value_status'} <= context_columns:
        operator='k.score_operator' if 'score_operator' in context_columns else "'='"
        extras=','.join(('k.'+field if field in context_columns else 'NULL')+' AS _'+field for field in ('count_raw','scope_raw'))+",k.segment_n AS _segment_n,typeof(k.segment_n) AS _segment_type,"+("typeof(k.count_raw)"if 'count_raw'in context_columns else"'null'")+" AS _count_raw_type"
        sql='SELECT y.*,typeof(y.score) AS _score_type,typeof(y.cum) AS _cum_type,k.segment_n AS count,k.count_kind AS _count_kind,k.value_status AS _count_status,'+operator+' AS score_operator,'+extras+' FROM data.gk_official_yfyd y LEFT JOIN data.gk_yfyd_context k ON y.province=k.province AND y.year=k.year AND y.subject=k.subject AND y.score=k.score AND y.source_id=k.source_id WHERE y.province=? AND y.year=? AND y.subject=? ORDER BY y.score DESC'
    else:sql='SELECT *,typeof(score) AS _score_type,typeof(cum) AS _cum_type FROM data.gk_official_yfyd WHERE province=? AND year=? AND subject=? ORDER BY score DESC'
    rows=[dict(r) for r in c.execute(sql,(province,year,subject))]
    _yfyd_current_evidence(c,rows)
    for row in rows:
        kind=row.get('_count_kind') or ''
        states=_json(row.get('_count_status'),{})
        state=row.get('_current_states',{}).get('segment_n')or(states.get('segment_n',{}) if isinstance(states,dict) else {})
        original=isinstance(state,dict) and state.get('status') in {'官方原值','人工更正'}
        if not (original and kind in SEGMENT_COUNT_KINDS):row['count']=None
    return rows


def query_yfyd(province, year, subject, *, score=None, rank=None, db=None):
    """SQLite与报告CSV共用rank.Table；缺行不能通过另一查询路径补算。"""
    if (score is None)==(rank is None):raise QueryError('分数、位次必须且只能提供一项')
    scripts=ROOT/'skills/zhiqu/scripts'
    if str(scripts) not in sys.path:sys.path.insert(0,str(scripts))
    from rank import Table, MissingDataError
    with _open('education',db)as(c,_):
        rows=_yfyd_rows(c,province,year,subject)
        if not rows:raise QueryError('未取到该省年科类的一分一段表')
        ids=list(dict.fromkeys(r['source_id'] for r in rows));coverage=[_source_completeness(c,'gk_official_yfyd',sid)for sid in ids]
        result={'kind':'yfyd','province':province,'year':year,'subject':subject,'completeness':[v for v in coverage if v],'sources':[_source(c,sid)for sid in ids]}
        usable=[r for r in rows if r.get('cum') is not None]
        if not usable:
            result.update(status='missing_data',message='该段缺数据：原表没有可用累计人数，不能换算')
            return result
        head=usable[0];head_unknown=False
        for entry in result['completeness']:
            if entry['source_id']!=head['source_id']:continue
            for missing in entry['missing_rows']:
                try:
                    if missing['page']==head.get('src_page') and str(missing['table'])==str(head.get('src_table')) and missing['row']<int(head['src_row']):head_unknown=True
                except (KeyError,TypeError,ValueError):head_unknown=True
        table=Table.from_rows(usable,province+str(year)+subject,head_unknown=head_unknown)
        try:
            if score is not None:
                best,last=table.rank_of(score);result.update(score=score,best_rank=best,rank=last)
            else:result.update(rank=rank,score=table.score_of(rank))
            result['status']='ok'
        except MissingDataError as exc:result.update(status='missing_data',message=str(exc),gap=exc.details)
        return result


def _path(domain, db=None):
    return Path(db or os.environ.get('ZHIQU_' + domain.upper() + '_DB') or DEFAULTS[domain]).expanduser().resolve()


@contextlib.contextmanager
def _open(domain, db=None, education_db=None):
    p = _path(domain, db)
    if not p.is_file():
        raise QueryError('本机数据库未找到：' + str(p))
    c = sqlite3.connect(':memory:', uri=True, factory=_storage.StorageConnection)
    c.row_factory = sqlite3.Row
    try:
        c.execute('ATTACH DATABASE ? AS data', (p.as_uri() + '?mode=ro',))
        _storage.install_audit(c, p)
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
    return {x[0] for x in c.execute("SELECT name FROM data.sqlite_master WHERE type IN ('table','view')")} | _storage.logical_names(c)


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
        # A primary identity is not a dated spelling of that identity.
        if target == _norm(a.get('institution_id', '')):
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
    'gk_official_plan': ['plan_n'],
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
LABELS = {'business_subject_unspecified':'业务课门槛（原表未注明科目序及满分）','single_ge150':'单科满分至少150门槛','politics_foreign_language_shared':'政治／外语门槛（原表合列，未限定语种）','foreign_language_unspecified':'外语门槛（原表未限定语种）','english_or_politics':'英语／政治门槛（原表合列）','comprehensive_unspecified':'综合门槛（原表未注明科目序及满分）','standard_score':'标准分门槛（非初试原始总分）','exam_1_2_3_sum':'第一至第三科成绩之和门槛','single_150':'单科满分150门槛','total':'总分','line_total':'复试总分','politics':'原列政治/首科（须核口径）','english':'外语','math':'数学','major':'业务课','major1':'业务课一','major2':'业务课二','single_100':'单科满分100门槛','single_over_100':'单科满分超过100门槛','planned':'招生人数','tuimian':'推免人数','n':'样本人数','min':'最低','q1':'下四分位','median':'中位数','q3':'上四分位','max':'最高','mean':'平均','excluded_count':'排除数','recommend_rate':'保研比例','n_master':'硕士点','n_phd':'博士点','school_rank':'原表排名','plan_n':'计划人数','admitted_n':'录取人数','group_plan_n':'专业组人数','plan_n_result':'计划人数结果（原字段）','segment_n':'同分人数','cumulative_n':'累计人数','count_unspecified':'人数（含义未明确）','score_unspecified':'分数（含义未明确）','rank_unspecified':'位次（含义未明确）','years':'学制','tuition':'学费','plan':'计划人数','admit':'录取人数','score':'最低分','rank':'最低位次','min_score':'最低分','mean_score':'平均分','max_score':'最高分','min_rank':'最低位次','mean_rank':'平均位次','max_rank':'最高位次','headcount':'招录人数','percentage':'百分比','paid_applicants':'缴费人数','paid_per_seat':'缴费人数/名额','p10':'10%分位','p25':'25%分位','p50':'中位数','p75':'75%分位','p90':'90%分位','n_jobs':'职位数','share':'原表比例','share_below_10':'低于10人/名额的职位比例','share_100_plus':'100人/名额以上职位比例'}
TITLES = {'gk_official_plan':'高考官方初始计划（按原表范围）','institution_profile':'学校概况（第三方，年份未明单列）','gk_plan_entry':'高考招生计划','gk_official_cutoff':'高考官方投档线','gk_v_usable':'高考整理录取记录','gk_v_purchased':'高考购买数据（保留核验状态）','ky_program_year':'考研目录与往年线','ky_v_usable':'考研分布与可用历史记录','ky_v_retest_line':'学校官网复试线（保留核验状态）','ky_retest_line':'学校官网复试线（保留核验状态）','job_summary':'岗位与匿名报名人数','job_position':'岗位','wage_stat':'在岗工资调查（不代表应届起薪）','competition_stat':'匿名群体竞争统计（非个人概率）','civil_major_summary':'本科专业可报岗位汇总','selected_university':'选调高校范围','recruitment_notice':'招聘公告可用性','industry_stat':'行业统计','graduate_destination':'院校就业去向（届别按原表）'}
CONTEXT = ['year','plan_year','province','region','college','program_code','program_name','major_code','major_name','degree_type','study_mode','direction','joint_program','special_plan','admission_route','line_scope','list_type','scope','scope_mismatch','scope_mismatch_note','plan_type','subject','subject_type','batch','group_code','grp','position_id','unit','position','education','degree','major_clause','group_type','group','category','school','school_name','verification_status','note','notes','school_tags','degree_level','master_list','phd_list','year_status']


TITLES['employment_major_industry']='专业就业行业分布（届别、单位按原表）'
TITLES.update({'ky_v_usable_program':'考研招生目录','ky_v_usable_line':'考研历史复试线'})
LABELS['value_number']='原表占比数值'
CONTEXT += ['industry','unit_raw','value_raw','cohort']
CONTEXT += ['subjects','gender']
CONTEXT += ['major_full','school_group_code','old_batch','duration','comparison_status','other_province_raw','province_status']
CONTEXT += ['graduate_cohort','graduate_cohort_raw','cohort_status','province_raw','city_raw','institution_name_raw','item','item_raw','record_type','dataset_type','school_raw','group_name','subject_requirements','scope_raw']

def _source(c, sid):
    if sid and 'source' in _tables(c):
        row = c.execute('SELECT * FROM data.source WHERE source_id=?', (sid,)).fetchone()
        if row:
            return dict(row)
    if sid and 'core_delta_source' in _tables(c):
        row=c.execute('SELECT * FROM data.core_delta_source WHERE source_id=?',(sid,)).fetchone()
        if row:
            item=dict(row)
            deleted=any(marker in str(item.get('status') or '') for marker in ('originals_deleted','已删除'))
            return {'source_id':sid,'grade':'第三方整理','publisher':'购买汇编',
                    'title':item.get('relative_path'),'archive_path':None if deleted else item.get('relative_path'),
                    'original_relative_path':item.get('relative_path'),'archive_sha256':item.get('sha256'),
                    'archive_status':'已按用户授权删除' if deleted else '临时原件待清理（有指纹）',
                    'source_record_status':item.get('status'),'category':item.get('category'),
                    'note':'购买汇编补录来源；未登记官方网址或逐字摘录'}
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
    if not isinstance(locator,dict):return None
    if isinstance(locator.get('excerpt'), (str, dict, list)) and locator.get('locator'):
        return locator['excerpt']
    if not locator.get('path') or not locator.get('jsonl_line'):return None
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

@lru_cache(maxsize=256)
def _public_format_record(root, locator):
    """Read only one publicly versioned CSV record; never an original attachment."""
    match=re.fullmatch(r'(.+\.csv):(\d+)',str(locator or ''))
    if not match:return None
    base=(Path(root)/'skills/zhiqu/data').resolve();path=(base/match[1]).resolve()
    if not path.is_relative_to(base) or 'purchased' in path.relative_to(base).parts or not path.is_file():return None
    number=int(match[2])
    if number<2:return None
    try:
        with path.open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f);columns=reader.fieldnames or []
            for line,item in enumerate(reader,2):
                if line==number:
                    # Only scope metadata and format columns are returned, no row copy.
                    keep=('source_id','code','name','group','major_code','major','batch','type','subjects','subject','region')
                    return {'columns':columns,'scope':{k:item[k] for k in keep if item.get(k) not in (None,'')},'public_record':match[1]+':'+str(number)}
    except (OSError,csv.Error,UnicodeError):return None
    return None


def _official_context(c, row, *, ignore_scope_fields=()):
    """Only verified original-header evidence establishes field applicability."""
    context={}
    if row.get('code') not in (None,''):context['source_school_code']=row['code']
    if row.get('name') not in (None,''):context['source_school_name']=row['name']
    if row.get('major_code') not in (None,''):context['source_major_code']=row['major_code']
    fmt=_public_format_record(str(ROOT),str(row.get('src') or row.get('src_row') or ''))
    if fmt:
        raw=fmt['scope']
        if any(row.get(a) not in (None,'') and raw.get(b) not in (None,'') and str(row[a])!=str(raw[b]) for a,b in [('code','code'),('source_id','source_id')]):fmt=None
    raw=dict(row)
    if fmt:
        raw.update(fmt['scope']);context['source_public_row']=fmt['public_record']
        context['public_csv_columns']=list(fmt['columns'])
        for col,key in [('batch','source_batch_raw'),('type','source_type_raw'),('region','source_region_raw')]:
            if raw.get(col):context[key]=raw[col]
    reference=None
    if 'source_format_reference' in _tables(c):
        found=c.execute('SELECT * FROM data.source_format_reference WHERE source_id=?',(row.get('source_id'),)).fetchone()
        if found:
            item=dict(found);fields=_json(item.get('provided_fields'),None);scope=_json(item.get('scope_fields'),None)
            if isinstance(fields,list) and isinstance(scope,dict) and item.get('excerpt') and item.get('locator'):
                reference=item;context['source_format_columns']=fields
                context['source_format_reference']={k:item[k] for k in ('source_id','excerpt','locator')}
                context['source_format_status']='原格式已核；只将原表应有字段的空值显示为表中空白'
                for original,key in scope.items():
                    if isinstance(key,str) and raw.get(original) not in (None,''):context[key]=raw[original]
                fixed=_json(item.get('scope_values'),{})
                if isinstance(fixed,dict):context.update({k:v for k,v in fixed.items() if v not in (None,'') and k!='required_scope_fields'})
    if not reference:context['source_format_status']='原格式未核，空值状态见--full'
    public_record = context.get('source_public_row') or row.get('src')
    if public_record and 'official_cutoff_scope' in _tables(c):
        found=c.execute('SELECT scope_json,locator_json FROM data.official_cutoff_scope WHERE source_id=? AND public_record=?',(row.get('source_id'),public_record)).fetchone()
        if found:
            context['source_public_row'] = public_record
            scope=_json(found[0],{});locator=_json(found[1],{})
            if isinstance(scope,dict):context.update({k:v for k,v in scope.items() if k not in ignore_scope_fields})
            context['source_scope_locator']=locator
    grp=context.get('source_group_code') or row.get('grp') or row.get('group')
    if grp not in (None,'','-','—','--'):
        context['source_granularity']='院校专业组';context['source_group_code']=grp
        if row.get('major') not in (None,'') and not context.get('major_name'):context.setdefault('group_scope_raw',row['major'])
    elif context.get('major_name'):context['source_granularity']='专业'
    elif row.get('major') not in (None,''):
        context['source_granularity']='原表项目（含义待核）';context['original_major_raw']=row['major']
    else:context['source_granularity']='院校/原表记录；未给专业或专业组'
    if not any(row.get(k) or context.get(k) for k in ('batch','source_batch_raw','source_type_raw')):context['source_batch_status']='当前记录未留批次字段；不能据此认定不同记录属于同一批次'
    if row.get('_query_record_rowid') is not None:context['source_record_key']='gk_official_cutoff:'+str(row['_query_record_rowid'])
    return context


def _record(c, table, row):
    components = {}
    full_line_proof = None
    if table in ('ky_retest_line', 'ky_v_retest_line') and row.get('record_id') is not None:
        row = dict(row)
        stored_proof = _json(row.get('excerpt_locator_json'))
        audit_pointer = isinstance(stored_proof, dict) and stored_proof.get('audit_table') == 'ky_line_original_evidence'
        evidence = None
        if 'ky_line_original_evidence' in _tables(c):
            evidence = c.execute('SELECT source_id,excerpt_locator_json FROM data.ky_line_original_evidence WHERE record_id=?', (row['record_id'],)).fetchone()
        if audit_pointer and (not evidence or evidence['source_id'] != row.get('source_id')):
            raise QueryError('复试线与原文审计记录不匹配：' + str(row['record_id']))
        if evidence and evidence['source_id'] == row.get('source_id'):
            # The compact query row points to the same generation's full audit proof.
            full_line_proof = evidence['excerpt_locator_json']
            row['excerpt_locator_json'] = full_line_proof
        if 'ky_line_scope_context' in _tables(c):
            context = c.execute('SELECT direction,joint_program,admission_route,scope_raw FROM data.ky_line_scope_context WHERE record_id=?', (row['record_id'],)).fetchone()
            if context:
                # Only explicitly retained original scope; never infer a direction from its score.
                row.update({key: value for key, value in dict(context).items() if value not in (None, '')})
        if 'ky_line_component' in _tables(c):
            components = {item['component']: dict(item) for item in c.execute('SELECT * FROM data.ky_line_component WHERE record_id=?', (row['record_id'],))}
    if table == 'gk_official_plan':
        row = dict(row)
        proof = None
        if 'gk_official_original_evidence' in _tables(c):
            proof = c.execute('SELECT table_name,source_id,excerpt_locator_json FROM data.gk_official_original_evidence WHERE record_id=?',(row.get('record_id'),)).fetchone()
        if not proof or proof['table_name'] != table or proof['source_id'] != row.get('source_id'):
            raise QueryError('招生计划与原文审计记录不匹配：'+str(row.get('record_id')))
        original_proof = _json(proof['excerpt_locator_json'],{})
        if original_proof.get('business_key') != {'record_id':row.get('record_id')}:
            raise QueryError('招生计划与原文审计位置不匹配')
        row['excerpt_locator_json'] = json.dumps({'excerpt':original_proof.get('excerpt'),'locator':original_proof.get('locator')},ensure_ascii=False)
        intention = original_proof.get('scope',{}).get('intention_category_raw')
        if intention:row['scope_raw'] = str(row.get('scope_raw') or '')+'；意向类别：'+str(intention)
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
    for component, item in components.items():
        component_source = _source(c, item['source_id'])
        values[component] = {
            'value': item['value'], 'unit': '分',
            'grade': component_source.get('grade') or '未注明',
            'publisher': component_source.get('publisher') or '未注明',
            'source_id': item['source_id'], 'value_status': _status({'value_status': item['value_status']}, 'value') if 'value' in _json(item['value_status']) else _json(item['value_status']),
            'display_label': LABELS.get(component, '原表科目槽' + component.removeprefix('exam_')),
            'original_locator': _json(full_line_proof or item['src_locator']),
        }
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
    if table in ('ky_retest_line', 'ky_v_retest_line'):
        proof = _json(row.get('excerpt_locator_json'))
        if isinstance(proof, dict) and proof.get('locator'):
            result['locator']['original'] = proof['locator']
            result['locator'].update({key: proof[key] for key in ('src_page','src_table','src_row') if proof.get(key) not in (None, '')})
    if table=='gk_official_cutoff':
        result['completeness']=_source_completeness(c,table,row.get('source_id'))
        result['context'].update(_official_context(c, row))
        pointer=result['context'].get('source_scope_locator')
        supplements,scope_errors=_export_rules.scope_field_sources(c,_tables(c),row,result['context'],pointer)
        if supplements:
            result['scope_sources']=supplements
            result['sources']=[dict(proof,role='选科原标签') for proof in supplements.values()]
            result['context']['subject_requirements_status']='官网当年该省专业原标签；不扩至其他年份或专项'
        if scope_errors:
            native_context=_official_context(c,row,ignore_scope_fields={'subject_requirements'})
            native=next((row[k] for k in ('subject_requirements','subject_req_raw') if row.get(k) not in (None,'')),native_context.get('subject_requirements'))
            if native not in (None,''):
                result['context']['subject_requirements']=native
                result['context']['subject_requirements_status']='原业务字段；另取的选科补充来源链不匹配，未采用补充'
            else:
                result['context'].pop('subject_requirements',None)
                result['context']['subject_requirements_status']='待核：选科补充原文的来源链不匹配'
            result['scope_source_errors']=scope_errors
        provided=result['context'].get('source_format_columns')
        if 'rank' in values:
            _,reference=_export_rules._format_scope(c,_tables(c),row.get('source_id'),{})
            gate=_export_rules.cutoff_rank_gate(values['rank'],reference.get('provided_fields') if reference else None)
            if gate:
                values['rank'].update(usage_gate=gate,display_label=gate['meaning'],supplement_warning=gate['reason'])
        if isinstance(provided,list):
            for field,value in values.items():
                if value['value'] in (None,'') and field not in provided:
                    value['value_status']={'status':'来源未提供','reason':'已核原件格式不设此列；兼容占位，不是原件遗失',
                                           'applicable_by_format':False,'original_status':value['value_status']}
        if row.get('src'):result['locator']['public_record']=row['src']
        if result['context'].get('source_scope_locator'):
            result['locator']['original_scope']=result['context']['source_scope_locator']
            pointer=result['context']['source_scope_locator']
            if isinstance(pointer,dict) and pointer.get('audit_table')=='gk_official_original_evidence':
                proof=None
                if 'gk_official_original_evidence' in _tables(c):
                    proof=c.execute('SELECT table_name,source_id,excerpt_locator_json FROM data.gk_official_original_evidence WHERE record_id=?',(pointer.get('record_id'),)).fetchone()
                expected={'source_id':row.get('source_id'),'src':row.get('src')}
                if not proof or proof['table_name']!='gk_official_cutoff' or proof['source_id']!=row.get('source_id') or _json(proof['excerpt_locator_json'],{}).get('business_key')!=expected:
                    raise QueryError('投档线与原文审计记录不匹配：'+str(pointer.get('record_id')))
                original_proof=_json(proof['excerpt_locator_json'],{})
                result['excerpt']=original_proof.get('excerpt')
                result['excerpt_kind']='官方原表匿名单元格摘录（逐文件抽核）'
                result['original_locator']=original_proof.get('locator')
        if result['context'].get('source_format_reference'):
            result['locator']['original_format']=result['context']['source_format_reference']
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
    projection='t.*'
    if table=='gk_official_cutoff' and c.execute("SELECT type FROM data.sqlite_master WHERE name=?",(storage,)).fetchone()[0]=='table':projection='t.rowid AS _query_record_rowid,t.*'
    rows = c.execute('SELECT '+projection+' FROM data.' + _ident(storage) + ' t WHERE ' + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
    records=[_record(c,table,dict(r)) for r in rows]
    if table=='gk_official_cutoff':
        groups={}
        for record in records:
            scope={k:v for k,v in record['context'].items() if k not in ('source_record_key','source_public_row','source_format_columns','source_format_status','source_format_reference','public_csv_columns','source_scope_locator')}
            groups.setdefault(json.dumps(scope,ensure_ascii=False,sort_keys=True),[]).append(record)
        for duplicates in groups.values():
            if len(duplicates)>1:
                for record in duplicates:
                    ctx=record['context'];ctx['scope_row_disambiguator']=ctx.get('source_public_row') or ctx.get('source_record_key') or _plain(record.get('locator'))
                    # Identical CSV source rows can still be separate real DB rows.
                    if sum(r['context'].get('source_public_row')==ctx.get('source_public_row') for r in duplicates)>1 and ctx.get('source_record_key'):ctx['scope_row_disambiguator']+='；'+ctx['source_record_key']
    return {'table':table,'title':TITLES.get(table,table),'year_range':year_range,'total':total,'offset':offset,'returned':len(rows),'truncated':max(total-offset-len(rows),0),'rows':records}


CORE_DELTA_VIEWS=('v_core_delta_number','v_core_delta_attribute')
CORE_DELTA_COLUMNS=('record_id','source_id','vendor_source_id','institution_id','year','province','subject','batch','school_raw','school_code','group_code','major_code','major_name','plan_type','scope_raw','field_name','field_label','value','raw_value','unit','value_status','src_sheet','src_row','src_col','official_locator','major_full','school_group_code','group_name','subject_requirements','old_batch','duration','comparison_status','record_type','dataset_type','other_province_raw','year_status','province_status')


OFFICIAL_CORE_SCOPE=('province','year','subject','institution_id','school_raw','major_name','batch','plan_type','scope_raw')


def _official_core_proof(c, row, source):
    """Recognize a reviewed original cell, never infer quality from its publisher."""
    if source.get('grade')!='官方' or 'gk_official_original_evidence' not in _tables(c):return None
    evidence=c.execute('SELECT table_name,source_id,excerpt_locator_json FROM data.gk_official_original_evidence WHERE record_id=?',(row.get('record_id'),)).fetchone()
    if not evidence or evidence[0]!='core_delta_number' or evidence[1]!=row.get('source_id'):return None
    proof=_json(evidence[2],{})
    if not isinstance(proof,dict):return None
    review=proof.get('review',{});key=proof.get('business_key',{});loc=proof.get('locator',{});cell=proof.get('excerpt',{})
    if not all(isinstance(x,dict) for x in (review,key,loc,cell)):return None
    expected={'record_id':row.get('record_id'),'field_name':row.get('field_name'),'scope':{k:row.get(k) for k in OFFICIAL_CORE_SCOPE}}
    position={k:row.get(k) for k in ('src_sheet','src_row','src_col')}
    actual=row.get('value');stated=cell.get('value')
    if (review.get('status')!='approved' or review.get('approved_by')!='root' or review.get('semantic_approved') is not True
            or review.get('dual_read_equal') is not True or key!=expected
            or not re.fullmatch('[0-9a-f]{64}',str(source.get('archive_sha256') or ''))
            or loc.get('sha256')!=source['archive_sha256'] or loc.get('source_position')!=position
            or type(actual) is not type(stated) or actual!=stated or isinstance(actual,bool)
            or not isinstance(actual,(int,float)) or not math.isfinite(actual) or actual<0
            or not cell.get('raw') or not cell.get('header') or not cell.get('score_basis')
            or not all(isinstance(loc.get(k),int) and not isinstance(loc[k],bool) and loc[k]>0 for k in ('table','row','column'))):return None
    return proof


def _core_delta_record(c, table, row):
    """One field per record. Purchase coordinates never become official coordinates."""
    sid=row.get('source_id');vendor=row.get('vendor_source_id');source=_source(c,sid)
    locator={k:row[k] for k in ('src_sheet','src_row','src_col') if row.get(k) not in (None,'')}
    if not locator.get('src_col'):locator['locator_status']='字段列位置未唯一确定，不能视为逐值列定位完整'
    corrected=bool(vendor and sid!=vendor)
    field=row.get('field_name') or 'value'
    value={'value':row.get('value'),'raw_value':row.get('raw_value'),
           'display_label':row.get('field_label') or field,'unit':row.get('unit') or '',
           'grade':source.get('grade') or '未注明','publisher':source.get('publisher') or '未注明',
           'source_id':sid or '未登记','value_status':{'status':row.get('value_status') or '未标记（待核）'}}
    if vendor and 'unfilled_reason' in _cols(c,'core_delta_source'):
        problem=c.execute('SELECT unfilled_reason FROM data.core_delta_source WHERE source_id=?',(vendor,)).fetchone()
        if problem and problem[0]:
            note=str(problem[0]).replace('year_unconfirmed:original_year_not_verified','年份缺少原表依据').replace('province_unconfirmed','省份缺少原行依据')
            value['supplement_warning']='来源仍有未补或未解释内容：'+note
    if corrected or row.get('official_locator'):
        value.update(official_locator=row.get('official_locator'),original_source_id=vendor,
                     vendor_locator=locator)
    else:value['locator']=locator
    result = {'table':table,'record_id':row.get('record_id'),
            'context':{k:row[k] for k in CONTEXT+['school_code'] if row.get(k) not in (None,'')},
            'values':{field:value},'source':source,
            'vendor_source_id':vendor,'vendor_source':_source(c,vendor) if vendor else None,
            'locator':{'official_locator':row.get('official_locator')} if corrected else locator,
            'original_locator':locator if corrected else None,
            'excerpt':None,'excerpt_kind':'补录结构化字段及原格值；不冒充官方逐字摘录',
            'excerpt_locator':{}}
    if table=='v_core_delta_number' and source.get('grade')=='官方':
        proof=_official_core_proof(c,row,source)
        if proof:
            value['value_status']={'status':'官方原值','reason':'本值原格、完整范围、来源指纹及主审两读核验链一致'}
            value['raw_value']=proof['excerpt']['raw']
            value['locator']=proof['locator'];value['display_label']=proof['excerpt']['score_basis']+'·'+proof['excerpt']['header']
            result.update(locator=proof['locator'],excerpt=proof['excerpt'],excerpt_kind='主审核过的官方原格摘录',excerpt_locator=proof)
        else:
            value['value_status']={'status':'待核','reason':'官方发布身份不替代本值原格审核；审核链缺失或不匹配'}
            result['quality_gate']='未通过'
    return result


def _core_delta_section(c, identity, name, program, year, province, major, subject, plan_type, limit, offset, exclude_school_fields=()):
    tables=_tables(c);parts=[];args=[]
    for table in CORE_DELTA_VIEWS:
        if table not in tables:continue
        where=['t.institution_id=?'];bound=[identity['institution_id']]
        if table=='v_core_delta_attribute' and exclude_school_fields:
            where.append('t.field_name NOT IN ('+','.join('?' for _ in exclude_school_fields)+')');bound.extend(exclude_school_fields)
        if year is not None:where.append('CAST(t.year AS INTEGER)=?');bound.append(int(year))
        if province:where.append('t.province=?');bound.append(province)
        if major:where.append('t.major_name LIKE ?');bound.append('%'+major+'%')
        if subject:
            where.append('t.subject IN (?,?)');bound.extend([subject.removesuffix('类'),subject.removesuffix('类')+'类'])
        if plan_type:where.append('t.plan_type=?');bound.append(plan_type)
        if program is not None:where.append('CAST(t.major_code AS TEXT) LIKE ?');bound.append(str(program)+'%')
        if year is None and 'institution_alias' in tables and _norm(name) != _norm(identity['institution_id']):
            aliases=[dict(x) for x in c.execute('SELECT * FROM data.institution_alias WHERE institution_id=?',(identity['institution_id'],)) if _norm(x['alias'])==_norm(name)]
            if aliases and all(x.get('year') is not None or x.get('year_from') is not None or x.get('year_to') is not None for x in aliases):
                ranges=[]
                for a in aliases:
                    lo=a.get('year') if a.get('year') is not None else a.get('year_from');hi=a.get('year') if a.get('year') is not None else a.get('year_to');clause=[]
                    if lo is not None:clause.append('CAST(t.year AS INTEGER)>=?');bound.append(lo)
                    if hi is not None:clause.append('CAST(t.year AS INTEGER)<=?');bound.append(hi)
                    ranges.append('('+' AND '.join(clause)+')')
                where.append('('+' OR '.join(ranges)+')')
        available=_cols(c,table)
        fields=','.join(('t.'+_ident(column) if column in available else 'NULL AS '+_ident(column)) for column in CORE_DELTA_COLUMNS)
        parts.append("SELECT '"+table+"' AS core_view,"+fields+" FROM data."+_ident(table)+' t WHERE '+' AND '.join(where));args.extend(bound)
    if not parts:return None
    union=' UNION ALL '.join(parts)
    totals=c.execute('SELECT count(*),min(CAST(year AS INTEGER)),max(CAST(year AS INTEGER)) FROM ('+union+')',args).fetchone()
    if not totals[0]:return None
    rows=c.execute('SELECT * FROM ('+union+') ORDER BY CAST(year AS INTEGER) DESC,record_id,core_view,field_name,source_id LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
    return {'table':'core_delta','title':'本轮补录字段','year_range':list(totals[1:]) if totals[1] is not None else [],
            'total':totals[0],'offset':offset,'returned':len(rows),'truncated':max(totals[0]-offset-len(rows),0),
            'rows':[_core_delta_record(c,row['core_view'],dict(row)) for row in rows]}


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
            domains={('考研' if x['table'].startswith('ky_') else '高考') for x in sections if x['table'].startswith(('ky_','gk_')) or x['table']=='core_delta'}
            if d.get('domain') and domains and d['domain'] not in domains:continue
            if effective and any(x in scope for x in scopes) and (not years or min(years) <= int(effective) <= max(years)):
                warnings.append('跨年口径：%s %s；影响：%s；出处：%s' % (effective,d.get('change',''),d.get('impact',''),d.get('source_id','未登记')))
    return warnings


def _official_reference_section(c, identity):
    if 'v_institution_official_reference' not in _tables(c):
        return None
    rows=[]
    order={'办学所在地':0,'主管部门':1,'办学层次':2,'985工程':3,'211工程':4,'第二轮双一流':5}
    items=[dict(r) for r in c.execute('SELECT * FROM data.v_institution_official_reference WHERE institution_id=?',(identity['institution_id'],))]
    for item in sorted(items,key=lambda x:(order.get(x['programme'],99),x['list_id'])):
        source=_source(c,item['source_id']);programme=item['programme'];state=item['is_member']
        membership=programme in {'985工程','211工程','第二轮双一流'}
        status='推算' if membership and state==0 else '来源未提供' if membership and state is None else '官方原值'
        scope='名单年份：'+str(item['list_year']) if item['list_year'] is not None else '名单截至年未标（页面发布日期不代替名单年份）'
        value={'value':item['value'],'unit':'','display_label':programme,
               'grade':'官方','publisher':source.get('publisher','教育部'),'source_id':item['source_id'],
               'value_status':{'status':status,'method':item['comparison_basis']}}
        rows.append({'table':'institution_official_reference','record_id':identity['institution_id']+':'+item['programme'],
                     'context':{'reference_scope':scope},'values':{programme:value},'source':source,
                     'locator':_json(item['src_locator']),'excerpt':item['excerpt'],
                     'excerpt_kind':'官方原表；未列入结论由完整名单集合比较得出，不冒充逐校否定原句',
                     'reference':item})
    if not rows:return None
    return {'table':'institution_official_reference','title':'学校官方信息（教育部名单）','year_range':[],
            'total':len(rows),'offset':0,'returned':len(rows),'truncated':0,'rows':rows}


def _school_attribute_section(c, ident, limit, offset):
    """Canonical school facts; paginate fields, keeping every conflicting value together."""
    tables=_tables(c)
    if 'school_attribute_fact' not in tables:return None
    labels={'school_level':'学校层次','school_tags':'学校标签','recommend_rate':'保研比例','n_master':'硕士点','n_phd':'博士点','master_list':'硕士点名单','phd_list':'博士点名单','is_985':'985院校','is_211':'211院校','school_location':'学校所在地','province_of_school':'学校所在省份','city':'城市','city_tier':'城市类别','rename_note':'更名说明','affiliation':'隶属','school_type':'学校类型','ownership':'办学性质','degree_level':'学位层次','school_rank':'原表排名','transfer_policy':'转专业说明','charter_url':'招生章程网址'}
    priority=['school_level','school_tags','recommend_rate','n_master','n_phd','master_list','phd_list','is_985','is_211','school_location']
    facts=[dict(r) for r in c.execute('SELECT f.attribute_id,f.field_name,t.value FROM data.school_attribute_fact f JOIN data.core_delta_text t ON t.text_id=f.value_text_id WHERE f.institution_id=? AND t.value<>\'\' ORDER BY f.field_name,t.value,f.attribute_id',(ident['institution_id'],))]
    original_fact_count=len(facts)
    profile_cols=_cols(c,'school_profile_source') if 'school_profile_source' in tables else set()
    core_sources={'school_core_attribute_map','school_core_attribute_source','core_delta_locator','core_delta_source'}<=tables
    scope_guard=('NOT EXISTS(SELECT 1 FROM data.core_delta_scope_issue qi WHERE qi.source_key=l.source_key AND qi.sheet_id=l.sheet_id)'
                 if 'core_delta_scope_issue' in tables else '1=1')
    eligible=[]
    for fact in facts:
        aid=fact['attribute_id'];field=fact['field_name']
        supported=field in profile_cols and c.execute('SELECT 1 FROM data.school_profile_source WHERE '+_ident(field)+'=? LIMIT 1',(aid,)).fetchone() is not None
        if not supported and core_sources:
            supported=c.execute('''SELECT 1 FROM data.school_core_attribute_map m
                CROSS JOIN data.school_core_attribute_source s ON s.original_value_id=m.original_value_id
                CROSS JOIN data.core_delta_locator l ON l.locator_id=s.locator_id
                WHERE m.attribute_id=? AND '''+scope_guard+' LIMIT 1',(aid,)).fetchone() is not None
        if supported:eligible.append(fact)
    facts=eligible
    if not facts:return None
    grouped={}
    for fact in facts:grouped.setdefault(fact['field_name'],[]).append(fact)
    fields=sorted(grouped,key=lambda f:(priority.index(f) if f in priority else len(priority),f))
    official={r['programme']:dict(r) for r in c.execute('SELECT * FROM data.v_institution_official_reference WHERE institution_id=?',(ident['institution_id'],))} if 'v_institution_official_reference' in tables else {}
    controlled={'is_985','is_211','school_tags','school_level','school_location','province_of_school','city','affiliation'} if 'v_institution_official_reference' in tables else set()
    public_fields=[f for f in fields if f not in controlled]
    selected=public_fields[offset:offset+limit]+[f for f in fields if f in controlled];rows=[]
    for field in selected:
        for fact in grouped[field]:
            aid=fact['attribute_id'];sources=[]
            if field in profile_cols:
                for loc in c.execute('SELECT ingest_id,province,school_code,src_file,src_row FROM data.school_profile_source WHERE '+_ident(field)+'=? ORDER BY src_file,src_row,ingest_id,province,school_code',(aid,)):
                    locator={k:loc[k] for k in ('ingest_id','province','school_code','src_file','src_row') if loc[k] is not None}
                    locator.update(database_table='gk_school_info',locator_status='原文件行号；工作表未登记，不推定')
                    sources.append({'source':_source(c,'vendor-file-'+str(loc['src_file']) if loc['src_file'] is not None else None),'locator':locator})
            if core_sources:
                # Map(attribute_id,context_id) narrows first; source PK begins with original_value_id.
                sql='''SELECT ds.source_id,sheet.value AS src_sheet,col.value AS src_col,
                    min(l.src_row) AS first_row,max(l.src_row) AS last_row,
                    count(DISTINCT l.src_row) AS matched_rows,count(*) AS matched_cells
                    FROM data.school_core_attribute_map m
                    CROSS JOIN data.school_core_attribute_source s ON s.original_value_id=m.original_value_id
                    CROSS JOIN data.core_delta_locator l ON l.locator_id=s.locator_id
                    CROSS JOIN data.core_delta_source ds ON ds.source_key=l.source_key
                    CROSS JOIN data.core_delta_text sheet ON sheet.text_id=l.sheet_id
                    CROSS JOIN data.core_delta_text col ON col.text_id=s.col_id
                    WHERE m.attribute_id=? AND '''+scope_guard+'''
                    GROUP BY ds.source_id,sheet.value,col.value
                    ORDER BY ds.source_id,sheet.value,col.value'''
                for loc in c.execute(sql,(aid,)):
                    locator={k:loc[k] for k in ('src_sheet','src_col','first_row','last_row','matched_rows','matched_cells')}
                    locator.update(src_row=loc['first_row'],locator_status='首个真实匹配行；首末行仅为边界，不表示中间各行均匹配；完整逐行位置保留在库中')
                    sources.append({'source':_source(c,loc['source_id']),'locator':locator})
            source=sources[0]['source'] if sources else {'source_id':'未登记','grade':'第三方整理','publisher':'未注明'}
            value={'value':fact['value'],'display_label':labels.get(field,field),'unit':'个' if field in ('n_master','n_phd') else '比例（原值，未自动换算百分数）' if field=='recommend_rate' else '',
                   'grade':'第三方整理','publisher':source.get('publisher') or '未注明','source_id':source.get('source_id') or '未登记','value_status':{'status':'第三方整理未核'}}
            count_field={'master_list':'n_master','phd_list':'n_phd'}.get(field)
            if count_field and len(grouped.get(count_field,[]))==1:
                raw=grouped[count_field][0]['value']
                if re.fullmatch(r'[0-9]+',raw.strip()):value['declared_count']=int(raw.strip())
            row={'table':'school_attribute_fact','record_id':'school-attribute-'+str(aid),'context':{'year_status':'未记录'},'values':{field:value},'sources':sources,
                 'source_conflict':'来源之间不一致' if len(grouped[field])>1 else None}
            if field in controlled:
                row['default_hidden']=True
                programme={'is_985':'985工程','is_211':'211工程'}.get(field)
                ref=official.get(programme)
                if ref and ref['is_member'] is not None:
                    raw=str(fact['value']).strip().lower()
                    parsed=1 if raw in {'是','有','1','1.0','true','yes','√'} else 0 if raw in {'否','无','0','0.0','false','no','×'} else None
                    row['context']['official_comparison']='与官方名单冲突' if parsed is not None and parsed!=ref['is_member'] else '官方身份以教育部名单为准；此处保留第三方原值'
                    if parsed is not None and parsed!=ref['is_member']:
                        value['value_status']['reason']='与官方名单冲突；'+ref['scope_note']
                elif field in {'school_location','province_of_school','city'} and '办学所在地' in official:
                    raw=re.sub('[省市\\s]','',str(fact['value']))
                    prov=re.sub('[省市\\s]','',str(ident.get('province') or ''))
                    city=re.sub('[省市\\s]','',official['办学所在地']['value'])
                    compatible=raw in {prov,city,prov+city} or (prov and city and raw==prov+city)
                    row['source_conflict']=None if compatible else row['source_conflict']
                    row['context']['official_comparison']='所在地精度不同，采用教育部城市字段' if compatible else '与本版教育部所在地不同；第三方统计时点未标'
                else:row['context']['official_comparison']='项目标签、主管部门和所在地默认采用官方参考；第三方历史标签保留待核'
            rows.append(row)
    return {'table':'school_attribute_fact','title':'学校概况（第三方，统计年份未明）','year_range':[],'total':len(public_fields),'fact_count':len(facts),'excluded_facts':original_fact_count-len(facts),'offset':offset,'returned':len(selected),'truncated':max(len(public_fields)-offset-limit,0),'canonical_fields':fields,'rows':rows}


def _query_education(name, program=None, year=None, province=None, db=None, limit=10, offset=0, major=None, subject=None, plan_type=None):
    limit, offset = _bounds(limit, offset)
    if program is not None and not re.fullmatch(r'[0-9A-Za-z]{2,12}', str(program)):
        raise QueryError('专业代码只能含字母和数字')
    with _open('education', db) as (c,p):
        ident,warnings = _identity(c,name,year,province);tables=_tables(c);sections=[]
        official=_official_reference_section(c,ident) if program is None else None
        if official:sections.append(official)
        ky_tables=['ky_v_usable_program' if 'ky_v_usable_program' in tables else 'ky_program_year']+(['ky_v_usable_line'] if 'ky_v_usable_line' in tables else [])+['ky_v_usable']
        candidates = ['institution_profile','gk_official_plan','gk_plan_entry','gk_official_cutoff','gk_v_usable','gk_v_purchased']+ky_tables if program is None else ['gk_v_purchased']+ky_tables
        canonical=_school_attribute_section(c,ident,limit,offset) if program is None and 'school_attribute_fact' in tables else None
        if program is None and 'school_attribute_fact' in tables:
            candidates.remove('institution_profile')
            if canonical:sections.append(canonical)
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
            if year is None and yf and 'institution_alias' in tables and _norm(name) != _norm(ident['institution_id']):
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
        exclude_school_fields=tuple(f for f in ('is_985','is_211','school_location') if canonical and f in canonical['canonical_fields'])
        core=_core_delta_section(c,ident,name,program,year,province,major,subject,plan_type,limit,offset,exclude_school_fields=exclude_school_fields)
        if core:sections.append(core)
        def section_priority(section):
            if section['table']=='institution_official_reference':return 0
            if section['table'] in {'gk_official_plan','gk_official_cutoff','ky_v_usable_line','ky_v_retest_line','ky_retest_line'}:return 1
            grades=[v.get('grade') for r in section['rows'] for v in r.get('values',{}).values()]
            return 1 if grades and all(g=='官方' for g in grades) else 2
        sections.sort(key=section_priority)
        warnings += _warnings(c,ident,sections,year)
        if program:
            warnings.append('旧研究生记录按研究生专业码前缀检索；本轮补录字段按其原专业码前缀检索，二者不作等价连接。' if core else '仅对研究生专业码作前缀检索；逐行保留具体代码，不与本科专业码直接相等连接。')
        warnings.append('各行学院、方向、学习方式、专项、联培、志愿及计划类型独立呈现，未合并；未见口径变更记录不代表口径稳定。')
        return {'query':'program' if program else 'school','database':str(p),'identity':ident,'sections':sections,'warnings':warnings}


def query_school(name, *, year=None, province=None, db=None, limit=10, offset=0, major=None, subject=None, plan_type=None):
    return _query_education(name,year=year,province=province,db=db,limit=limit,offset=offset,major=major,subject=subject,plan_type=plan_type)


def query_program(name, program, *, year=None, province=None, db=None, limit=10, offset=0, major=None, subject=None, plan_type=None):
    return _query_education(name,program=program,year=year,province=province,db=db,limit=limit,offset=offset,major=major,subject=subject,plan_type=plan_type)


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
            if table not in set(NUMERIC)|{'institution_event','comparability','selected_university','recruitment_notice','v_institution_official_reference'}:continue
            cols=_cols(c,table)
            if 'source_id' not in cols:continue
            count=c.execute('SELECT count(*) FROM data.'+_ident(table)+' WHERE source_id=?',(source_id,)).fetchone()[0]
            if not count:continue
            counts[table]=count
            rows=c.execute('SELECT * FROM data.'+_ident(table)+' WHERE source_id=? LIMIT ? OFFSET ?',(source_id,limit,offset))
            for row in rows:
                r=dict(row)
                if table in {'gk_v_purchased','gk_official_cutoff'}:
                    detailed=_record(c,table,r)
                    locations.append({k:detailed[k] for k in ('table','locator','context','excerpt','excerpt_kind','excerpt_locator','original_locator','additional_sources','annotation_json','annotation_status','numeric_conflict_fields','numeric_conflict_fields_status') if k in detailed})
                    continue
                locations.append({'table':table,'locator':{k:r[k] for k in ['record_id','src_page','src_table','src_sheet','src_row','src_col','src_cell','src_locator','locator'] if k in r},'excerpt':r.get('excerpt') or r.get('field_excerpt') or _original_excerpt(_json(r.get('excerpt_locator_json'))),'excerpt_kind':r.get('excerpt_kind') or ('原表摘录或读图定位记录（核验状态另列）' if r.get('excerpt_locator_json') else '未取到逐字原文摘录'),'excerpt_locator':_json(r.get('excerpt_locator_json'))})
        return {'query':'source','database':str(p),'source':s,'locations':locations,'matching_rows_by_table':counts,'limit_per_table':limit,'offset':offset,'warnings':['未留存逐字摘录时明确显示未取到；结构化整理记录不冒充官网逐字原文。']}


def _value_text(v, *, hide_status=False):
    status=v['value_status'].get('status','未标记（待核）')
    raw=v['value']
    if raw is None or raw=='':
        text='未公布' if status=='未公布' else '人数太少未公布' if status=='人数太少未公布' else '原件缺失' if status=='原件缺失' else '来源未提供' if status=='来源未提供' else status
    else:text=str(raw)+((' '+v['unit']) if v.get('unit') else '')
    rendered = ('%s〔%s｜%s｜%s〕' % (text,v['grade'],v['publisher'],v['source_id'])) if hide_status else ('%s〔%s｜%s｜%s；%s〕' % (text,v['grade'],v['publisher'],v['source_id'],status))
    if v.get('supplement_warning'):rendered+='；'+v['supplement_warning']
    if 'official_locator' in v:
        if v['official_locator']:
            rendered += '；官方位置：' + _plain(v['official_locator'])
        elif v.get('official_locator_candidates'):
            rendered += '；官方位置待核（多个匹配位置）：' + _plain(v['official_locator_candidates'])
        else:
            rendered += '；官方位置：未取到'
    if v.get('locator'):rendered+='；位置：'+_plain(v['locator'])
    if v.get('numeric_conflict'):rendered+='；'+v['numeric_conflict']['reason']
    return rendered


CONTEXT_LABELS = dict(zip(CONTEXT, ['年份','计划年份','省份','地区','学院','研究生专业码','研究生专业','本科原专业码','本科专业','学位','学习方式','方向','联培','专项','志愿类型','线的范围','名单类型','统计范围','口径是否一致','口径差异','计划类型','科类','科类','批次','专业组','专业组','岗位编号','单位','岗位','学历条件','学位条件','专业条款','分组口径','分组','类别','学校','原校名','核验状态','原备注','原备注','院校标签','办学层次','硕士点原名单','博士点原名单','年份状态']))
CONTEXT_LABELS['subject_requirements_status']='选科状态'

CONTEXT_LABELS.update({'industry':'原列就业行业','unit_raw':'原列单位','value_raw':'原格占比','cohort':'原列毕业届别'})
CONTEXT_LABELS['subjects']='考试科目'
CONTEXT_LABELS['gender']='性别限制'
CONTEXT_LABELS.update({'reference_scope':'官方名单口径','official_comparison':'与官方参考比较'})
CONTEXT_LABELS.update({'major_full':'专业完整原名','school_group_code':'院校专业组组合代码','old_batch':'原旧批次','duration':'学制原文','comparison_status':'比较口径状态','other_province_raw':'另省份列（原口径未注明）','province_status':'省份依据状态'})
CONTEXT_LABELS.update({'graduate_cohort':'毕业届别（原表）','graduate_cohort_raw':'届别原文','cohort_status':'届别状态','province_raw':'学校所在省（原表）','city_raw':'学校所在市（原表）','institution_name_raw':'院校名称（原表）','item':'就业项目','item_raw':'项目原文','record_type':'记录类型','dataset_type':'数据类型','school_raw':'院校原名','group_name':'专业组名称','subject_requirements':'选科要求','scope_raw':'原表范围说明'})

CONTEXT_LABELS.update({'source_school_code':'原院校代码','source_school_name':'原院校名','source_region_raw':'原地区','source_batch_status':'批次说明','source_major_code':'原专业代码','source_group_code':'原专业组码','source_granularity':'口径','group_scope_raw':'原组说明','subject_requirements':'选科要求','original_major_raw':'原项目（含义待核）','source_batch_raw':'原批次','source_type_raw':'原类别/批次','scope_row_disambiguator':'记录位置'})

def _plain(obj):
    if isinstance(obj,dict):return '；'.join(globals().get('_SOURCE_LABELS',{}).get(k,globals().get('CONTEXT_LABELS',{}).get(k,str(k)))+'：'+_plain(v) for k,v in obj.items())
    if isinstance(obj,list):return ' / '.join(_plain(v) for v in obj)
    return str(obj) if obj is not None else '未提供'

def _render_full_text(result):
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
                cap=10**12
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


# Text presentation is separate from the read-only result objects: no field or
# provenance entry is removed from --json, and --full expands the current page.
_PROFILE_TABLES = {'institution_profile', 'school_attribute_fact'}
_LIST_FIELDS = {'master_list_raw', 'phd_list_raw', 'master_list', 'phd_list',
                'masters_raw', 'phds_raw'}
_SOURCE_LABELS = {'source_id':'出处', 'grade':'等级', 'publisher':'发布单位',
    'title':'标题', 'landing_url':'网页', 'file_url':'附件', 'published':'发布',
    'retrieved':'取文', 'archive_sha256':'指纹', 'archive_status':'原件状态',
    'src_page':'页', 'src_table':'表', 'src_sheet':'工作表', 'src_row':'行',
    'src_col':'列', 'locator':'定位', 'source_locator':'定位', 'src_locator':'定位',
    'locator_status':'定位说明', 'database_table':'库内表',
    'first_row':'首行', 'last_row':'末行', 'matched_rows':'匹配行数', 'matched_cells':'匹配格数'}


def _short_text(value, full=False, cap=180):
    text=_plain(value).replace('\n',' ')
    return text if full or len(text)<=cap else text[:cap]+'…（全文见--json或--full）'


def _list_text(field, value, full=False, declared_count=None):
    if full or field not in _LIST_FIELDS:
        return _short_text(value,full)
    if type(declared_count) is int and declared_count>=0:
        return str(declared_count)+' 个（原表数量；--full 查看名单）'
    # Only actual sequences, JSON arrays, or unambiguous line/semicolon lists
    # provide defensible counts. Chinese commas can occur inside discipline names.
    items=None
    if isinstance(value,(list,tuple)):items=list(value)
    elif isinstance(value,str):
        parsed=_json(value, None)
        if isinstance(parsed,list):items=parsed
        elif re.search(r'[;；\n]',value):items=[x.strip() for x in re.split(r'[;；\n]+',value) if x.strip()]
    if items is not None and all(isinstance(x,str) and x.strip() for x in items):
        return str(len(items))+' 个（--full 查看名单）'
    if value in (None,'',[]):return '来源未提供'
    return '原名单待核（无法可靠计数；--full 查看原文）'


def _profile_rows(rows):
    """Collapse only school attributes, never score/plan context dimensions."""
    grouped={}
    for row in rows:
        context=row.get('context',{})
        for key,value in row.get('values',{}).items():
            token=(key,json.dumps(value.get('value'),ensure_ascii=False,sort_keys=True),value.get('unit',''))
            item=grouped.setdefault(token,{'context':{},'values':{key:value},'_origin_rows':[]})
            item['_origin_rows'].append(row)
        for key,value in context.items():
            if key not in {'tags','level','school_tags','degree_level','master_list','phd_list','master_list_raw','phd_list_raw'}:continue
            token=(key,json.dumps(value,ensure_ascii=False,sort_keys=True),'context')
            item=grouped.setdefault(token,{'context':{key:value},'values':{},'_origin_rows':[]})
            item['_origin_rows'].append(row)
    fields={}
    for token in grouped:fields.setdefault(token[0],set()).add(token[1])
    by_field={}
    for token,item in grouped.items():
        group=by_field.setdefault(token[0],{'context':{},'values':{},'_variants':[],'_origin_rows':[]})
        group['_variants'].append(item)
        group['_origin_rows'].extend(item['_origin_rows'])
        group['_conflict']=len(fields[token[0]])>1 or any(r.get('source_conflict') for r in group['_origin_rows'])
    return list(by_field.values()) or rows


def _locator_text(locator):
    text=_plain(locator)
    if isinstance(locator,dict) and locator.get('first_row') is not None:
        text+='；行边界：'+str(locator['first_row'])+'—'+str(locator.get('last_row',locator['first_row']))+'（可能不连续；匹配'+str(locator.get('matched_rows','未注明'))+'行；完整逐行关联保留在库中，此处未逐行展开）'
    return text


def _source_lines(row, full=False, refs=None):
    lines=[]
    source=row.get('source') or {}
    refs=refs or {}
    def prefix(src):return ('['+refs[str(src.get('source_id'))]+'] ') if str(src.get('source_id')) in refs else ''
    # Explicit labels, one source per line; never dump the source dictionary.
    if source:
        keys=['source_id','grade','publisher','title','landing_url','file_url','published','retrieved','archive_sha256','archive_status']
        lines.append(prefix(source)+'来源：'+'；'.join(_SOURCE_LABELS[k]+'：'+_short_text(source[k],full) for k in keys if source.get(k) not in (None,'')))
    original=row.get('original_locator')
    if original:lines.append(prefix(source)+'原始单元格定位：'+_locator_text(original))
    elif row.get('locator'):lines.append(prefix(source)+'定位：'+_locator_text(row['locator']))
    for value in row.get('values',{}).values():
        if 'official_locator' in value or value.get('locator'):
            lines.append('逐值出处：'+_value_text(value))
    if row.get('excerpt_kind') and (row.get('excerpt') or row.get('excerpt_status')):
        lines.append('摘录口径：'+row['excerpt_kind'])
    if full and row.get('excerpt'):lines.append('摘录：'+_plain(row['excerpt']))
    if full:
        if row.get('context'):lines.append('原表范围：'+_plain(row['context']))
        for key,label in [('major_links','本科专业字典'),('institution_links','学校身份关联'),('equivalent_sources','等价片段来源'),('excerpt_locator','摘录定位')]:
            if row.get(key):lines.append(label+'：'+_plain(row[key]))
        extra={k:v for k,v in source.items() if k not in _SOURCE_LABELS and v not in (None,'')}
        if extra:lines.append('来源补充：'+_plain(extra))
    if row.get('excerpt_status'):lines.append('摘录状态：'+_short_text(row['excerpt_status'],full))
    for item in row.get('additional_sources',[]):
        lines.append('额外来源：'+str(item.get('source_id') or '未登记')+'；'+_locator_text(item.get('locator',{})))
    for item in row.get('sources',[]):
        if isinstance(item,dict):
            src=item.get('source',item)
            lines.append(prefix(src)+'来源：'+'；'.join(_SOURCE_LABELS.get(k,k)+'：'+_short_text(src[k],full) for k in _SOURCE_LABELS if src.get(k) not in (None,'')))
            if item.get('locator'):lines.append(prefix(src)+'定位：'+_locator_text(item['locator']))
            if full:
                extra={k:v for k,v in src.items() if k not in _SOURCE_LABELS and v not in (None,'')}
                if extra:lines.append(prefix(src)+'来源补充：'+_plain(extra))
    for item in (row.get('excerpt_locator') or {}).get('root_verified_image_references',[]):
        lines.append('读图定位：'+str(item.get('locator') or '未提供')+'；SHA256='+str(item.get('sha256') or '未提供')+'；出处='+str(item.get('source_id') or '未提供'))
    return lines


def _compact_source_lines(rows, refs):
    """One bounded, human-readable line per source; keep full objects untouched."""
    entries={}
    def add(sid,source=None,locator=None,detail=None):
        sid=str(sid or '未登记')
        entry=entries.setdefault(sid,{'source':{},'locations':[],'details':[]})
        if source:entry['source'].update({k:v for k,v in source.items() if v not in (None,'')})
        if locator and locator not in entry['locations']:entry['locations'].append(locator)
        if detail and detail not in entry['details']:entry['details'].append(detail)
    priority=[]
    for row in rows:
        source=row.get('source') or {};sid=source.get('source_id')
        for value in row.get('values',{}).values():
            vid=str(value.get('source_id') or '未登记')
            if vid not in priority:priority.append(vid)
            add(vid,{'source_id':vid,'publisher':value.get('publisher')},locator=value.get('locator'))
            if 'official_locator' in value:
                add(vid,detail='逐值出处：'+_value_text(value))
        if source:add(sid,source,row.get('original_locator') or row.get('locator'))
        if row.get('original_locator'):add(sid,detail='原始单元格定位：'+_plain(row['original_locator']))
        if row.get('excerpt_kind') and (row.get('excerpt') or row.get('excerpt_status')):add(sid,detail='摘录口径：'+_short_text(row['excerpt_kind'],cap=120))
        if row.get('excerpt_status'):add(sid,detail='摘录状态：'+_short_text(row['excerpt_status'],cap=120))
        for item in row.get('sources',[]):
            if isinstance(item,dict):
                src=item.get('source',item)
                add(src.get('source_id'),src,item.get('locator'))
        for item in row.get('additional_sources',[]):
            add(item.get('source_id'),locator=item.get('locator'),detail='额外来源：'+str(item.get('source_id') or '未登记'))
        for item in (row.get('excerpt_locator') or {}).get('root_verified_image_references',[]):
            add(item.get('source_id'),detail='读图定位：'+str(item.get('locator') or '未提供')+'；SHA256='+str(item.get('sha256') or '未提供'))
    for sid in refs:add(sid)
    order=[sid for sid in priority if sid in entries]+[sid for sid in entries if sid not in priority]
    def title_text(value):
        value=str(value or '').replace('\n',' ')
        if value.lstrip().startswith(('{','[')) or re.search(r'"(?:members|note|citation)"\s*:',value):return '结构化来源标题（--full查看）'
        return value if len(value)<=60 else value[:59]+'…'
    lines=[]
    for sid in order[:10]:
        entry=entries[sid];src=entry['source'];ref=refs.get(sid,sid)
        published=re.search(r'(?:19|20)\d{2}',str(src.get('published') or ''))
        year=published.group(0) if published else next(iter(re.findall(r'(?:19|20)\d{2}',str(src.get('title') or ''))),'未注明')
        link=src.get('landing_url') or src.get('file_url') or '链接未登记'
        parts=['['+ref+']',title_text(src.get('publisher') or '发布单位未注明'),title_text(src.get('title') or '标题未注明'),year,_short_text(link,cap=240)]
        lines.append('｜'.join(parts).replace('\n',' '))
    if len(order)>10:lines.append('另'+str(len(order)-10)+'条来源未展开（含其他值的出处时仍以上方S编号区分；--full或--json查看完整来源和定位）')
    return lines


def render_text(result, *, full=False):
    if result.get('kind')=='yfyd':
        lines=[result['province']+' '+str(result['year'])+' '+result['subject']]
        lines.extend(_completeness_text(v,full)for v in result['completeness']if v.get('status')=='partial')
        if result['status']=='missing_data':lines.append(result['message'])
        else:lines.append(str(result['score'])+'分 → 位次'+str(result['rank']))
        lines.extend('来源：'+str(s.get('grade')or'未注明')+'｜'+str(s.get('publisher')or'未注明')+'｜'+str(s.get('title')or'')+'｜'+str(s.get('landing_url')or s.get('file_url')or'') for s in result['sources'])
        return '\n'.join(lines)+'\n'
    if result.get('query')=='source':
        if full:return _render_full_text(result)
        return _render_full_text(dict(result,locations=[{k:v for k,v in row.items() if k!='annotation_json'} for row in result.get('locations',[])]))
    # Preserve identity/event wording and warnings, with no business rows duplicated.
    header=dict(result,sections=[],warnings=[])
    lines=_render_full_text(header).splitlines()
    if lines and lines[-1].startswith('未取到匹配业务记录'):lines.pop()
    for sec in result.get('sections',[]):
        original=sec.get('rows',[])
        profile=sec.get('table') in _PROFILE_TABLES
        default_rows=original if full else [r for r in original if not r.get('default_hidden') and not r.get('full_only') and not (profile and r.get('values') and all(k in {'school_location','province_of_school','city','city_tier','school_address'} and v.get('grade')=='第三方整理' for k,v in r['values'].items()))]
        hidden_on_page=len(original)-len(default_rows)
        rows=_profile_rows(default_rows) if profile else default_rows
        if profile and not full:
            background={'school_tags','school_tag','school_levels','school_level','degree_level','tags','levels','is_985','is_211','affiliation','ownership','school_type','school_rank','school_location','province_of_school','school_city','city_tier'}
            filtered=[r for r in rows if not all(not v.get('values') and set(v.get('context',{})) and set(v.get('context',{}))<=background for v in r.get('_variants',[r]))]
            hidden_on_page+=len(rows)-len(filtered);rows=filtered
        visible=rows if full else rows[:10]
        more=max(0,len(rows)-len(visible))+sec.get('truncated',0)
        noun='字段' if profile else '行'
        total_label=str(sec.get('total',len(original)))+noun
        if profile and sec.get('fact_count') is not None:total_label+='（'+str(sec['fact_count'])+'个不同值）'
        lines.extend(['',sec['title']+'：共'+total_label+'；本页'+str(len(visible))+noun+'；后续'+str(more)+'行未显示','适用范围 | 数值与出处','--- | ---'])
        completeness={}
        for item in original:
            for origin in item.get('_origin_rows',[item]):
                value=origin.get('completeness')
                if value:completeness[value['source_id']]=value
        for value in completeness.values():
            message=_completeness_text(value,full)
            if message:lines.append('原表说明〔'+value['source_id']+'〕：'+message)
        if hidden_on_page:lines.append('显示说明：本页另有'+str(hidden_on_page)+'条保留记录默认不展开；--full或--json查看。')
        if sec.get('excluded_facts'):
            lines.append('说明：'+str(sec['excluded_facts'])+'个属性无可用来源；已沿用原工作表身份隔离，不纳入概况或冲突判定。')
        populated=[v for item in visible for variant in item.get('_variants',[item]) for v in variant.get('values',{}).values() if v.get('value') not in (None,'')]
        collapse_unverified=not full and bool(populated) and all((v.get('value_status',{}).get('status') if isinstance(v.get('value_status'),dict) else v.get('value_status'))=='第三方整理未核' for v in populated)
        repeated=[]
        for item in visible:
            for origin in item.get('_origin_rows',[item]):
                for key in ('source_format_status','source_batch_status','year_status','province_status'):
                    value=origin.get('context',{}).get(key)
                    if value:repeated.append((key,str(value)))
                for v in origin.get('values',{}).values():
                    if v.get('supplement_warning'):repeated.append(('supplement_warning',v['supplement_warning']))
        common={pair for pair in repeated if repeated.count(pair)>1}
        caveats=[]
        if not full:
            if collapse_unverified:caveats.append('本块有值记录均为第三方整理未核；完整逐值状态见--full或--json。')
            for _,message in dict.fromkeys(pair for pair in repeated if pair in common or pair[0]=='source_format_status'):
                if message not in caveats:caveats.append(message)
            if any(isinstance(r.get('context',{}).get('source_format_columns'),list) for r in original):caveats.append('已核原格式未列的空占位仅在--full显示；原表应有字段的空白仍列出。')
            if any(r.get('excerpt_kind') and '此行未留全文' in r['excerpt_kind'] for r in original):caveats.append('部分记录仅保留定位与抽样，此行未留全文；--full查看逐项核对信息。')
            values=[v for r in original for v in r.get('values',{}).values()]
            if any('official_locator' in v and not v.get('official_locator') for v in values):caveats.append('部分字段的官方原文定位未取到或尚未唯一确认；--full查看候选，未借用购买表位置。')
            if caveats:lines.append('本块说明：'+'；'.join(caveats))
        origins=[]
        refs={}
        for item in visible:
            for origin in item.get('_origin_rows',[item]):
                ids=[v.get('source_id') for v in origin.get('values',{}).values()]
                ids.append((origin.get('source') or {}).get('source_id'))
                ids.extend((x.get('source',x) or {}).get('source_id') for x in origin.get('sources',[]) if isinstance(x,dict))
                for sid in ids:
                    if sid is not None and str(sid) not in refs:refs[str(sid)]='S'+str(len(refs)+1)
        rendered_scopes={}
        for row in visible:
            variants=row.get('_variants',[row])
            context_parts=[]
            for variant in variants:
                for k,v in variant.get('context',{}).items():
                    if not full and k in {'school_tags','school_tag','school_levels','school_level','degree_level','tags','levels','is_985','is_211','affiliation','ownership','school_type','school_rank','school_location','province_of_school','school_city','city_tier'}:continue
                    if not full and k in {'source_format_columns','source_public_row','source_record_key','public_csv_columns','source_format_reference','source_format_status','source_scope_locator'}:continue
                    if not full and (k,str(v)) in common:continue
                    if not full and k=='source_school_name' and str(v)==str((result.get('identity') or {}).get('name')):continue
                    if not full and k=='grp' and variant.get('context',{}).get('source_group_code'):continue
                    if not full and k=='group_scope_raw' and v==variant.get('context',{}).get('subject_requirements'):continue
                    if not full and k in {'record_type','dataset_type','school_raw','school','school_name','comparison_status'}:
                        continue
                    if not full and k=='scope_raw':v=_json(v,v)
                    text=_list_text(k,v,full)
                    if not full:text=_short_text(text,cap=100)
                    context_parts.append(({'master_list':'硕士点','phd_list':'博士点'}.get(k,CONTEXT_LABELS.get(k,k)))+'：'+text)
            context='；'.join(dict.fromkeys(context_parts)) or ('学校概况' if profile else '原件未给适用范围')
            vals=[]
            missing=[]
            for key,value in [(k,v) for variant in variants for k,v in variant.get('values',{}).items()]:
                if not full and profile and key in {'school_location','province_of_school','city','city_tier','school_address'} and value.get('grade')=='第三方整理':continue
                status=value.get('value_status')
                status=status.get('status') if isinstance(status,dict) else status
                if not full and value.get('value') in (None,'') and 'source_format_status' in row.get('context',{}) and (not isinstance(row['context'].get('source_format_columns'),list) or key not in row['context']['source_format_columns']):
                    continue
                label=value.get('display_label',('签约人数' if sec['table']=='graduate_destination' and key=='headcount' else '名次' if sec['table']=='graduate_destination' and key=='rank' else LABELS.get(key,key)))
                if not full and value.get('value') is None and status=='来源未提供' and 'source_format_status' not in row.get('context',{}):
                    missing.append((label,value))
                    continue
                copy=dict(value)
                if not full:
                    copy={k:v for k,v in copy.items() if k not in ('locator','official_locator','official_locator_candidates')}
                    if ('supplement_warning',str(copy.get('supplement_warning'))) in common:copy.pop('supplement_warning',None)
                    if copy.get('value') in (None,'') and isinstance(row.get('context',{}).get('source_format_columns'),list) and key in row['context']['source_format_columns']:
                        copy['value_status']={'status':'表中空白（原因未核）','original_status':value.get('value_status')}
                    if copy.get('value') in (None,'') and row.get('context',{}).get('source_format_status','').startswith('未核定'):
                        copy['value_status']={'status':'空值待核（格式未知）','original_status':value.get('value_status')}
                    if isinstance(copy.get('value'),(str,list,dict)):copy['value']=_list_text(key,copy['value'],full,copy.get('declared_count'))
                    copy['publisher']=_short_text(copy.get('publisher','未注明'),cap=60)
                    copy['source_id']=refs.get(str(copy.get('source_id')),str(copy.get('source_id') or '未登记'))
                vals.append(label+'：'+_value_text(copy,hide_status=collapse_unverified and value.get('value') not in (None,'')))
            if missing:
                label='、'.join(x[0] for x in missing[:3])
                if len(missing)>3:label+='等'+str(len(missing))+'项'
                copy=dict(missing[0][1]);copy['source_id']=refs.get(str(copy.get('source_id')),str(copy.get('source_id') or '未登记'))
                vals.append(label+'：'+_value_text(copy))
            if row.get('_conflict') or row.get('source_conflict'):context+='；来源之间不一致'
            if full and row.get('annotation_json'):context+='；原表背景旁注（第三方整理未核，不作招生范围）：'+_short_text(row['annotation_json'],full)
            if row.get('numeric_conflict_fields'):context+='；第三方版本冲突字段：'+'、'.join(LABELS.get(k,k) for k in dict.fromkeys(row['numeric_conflict_fields']))+'；'+NUMERIC_CONFLICT_NOTE
            if row.get('numeric_conflict_fields_status'):context+='；'+row['numeric_conflict_fields_status']
            if sec.get('table')=='gk_official_cutoff':
                def actual_key(item):
                    ctx=item.get('context',{})
                    if ctx.get('scope_row_disambiguator'):return ctx['scope_row_disambiguator']
                    keys=[ctx[k] for k in ('source_public_row','source_record_key') if ctx.get(k)]
                    return '；'.join(map(str,keys)) or item.get('record_id') or _plain(item.get('locator') or {})
                if context in rendered_scopes:
                    old_index,old_row=rendered_scopes[context]
                    previous=actual_key(old_row);current=actual_key(row)
                    if previous and ('；记录位置：'+str(previous)) not in lines[old_index]:lines[old_index]=lines[old_index].replace(' | ','；记录位置：'+str(previous)+' | ',1)
                    if current:context+='；记录位置：'+str(current)
                else:rendered_scopes[context]=(len(lines),row)
            lines.append(context+' | '+('；'.join(vals) or '原表文字信息'))
            origins.extend(row.get('_origin_rows',[row]))
        if full:
            sources=[]
            for row in origins:sources.extend(_source_lines(row,True,refs))
            for sid,ref in refs.items():
                if not any(('出处：'+sid) in line for line in sources):sources.append('['+ref+'] 出处：'+sid)
            sources=list(dict.fromkeys(sources))
        else:sources=_compact_source_lines(origins,refs)
        if sources:lines.extend(['来源详情：']+sources)
        # Explicit paging also keeps source-coordinate text outside the value cell.
        lines.append('分页 | offset='+str(sec.get('offset',0))+'；后续'+str(more)+'行未显示；--full展开本页，后续页用--offset')
    for warning in result.get('warnings',[]):lines.append('提示：'+warning)
    if not result.get('sections'):lines.append('未取到匹配业务记录；不代表学校或专业未招生。')
    return '\n'.join(lines)+'\n'


def _export_official_core(c, tables, province, subject, years, out, schools, batch, plan_type):
    """Export reviewed official facts separately; incomplete scopes are not pool rows."""
    rows=[];rejected=[];sources={}
    if {'v_core_delta_number','core_delta_source','source'}<=tables:
        ids=[r[0] for r in c.execute('SELECT cs.source_id FROM data.core_delta_source cs JOIN data.source s ON s.source_id=cs.source_id WHERE s.grade=?',('官方',))]
        for sid in ids:
            sql='SELECT '+','.join(CORE_DELTA_COLUMNS)+' FROM data.v_core_delta_number WHERE vendor_source_id=? AND province=? AND subject=? AND year IN ('+','.join('?'for _ in years)+')'
            for item in c.execute(sql,(sid,province,subject,*years)):
                raw=dict(item)
                if schools and not schools.intersection({raw.get('institution_id'),raw.get('school_raw'),raw.get('school_code')}):continue
                if batch is not None and raw.get('batch')!=batch:continue
                if plan_type is not None and raw.get('plan_type')!=plan_type:continue
                record=_core_delta_record(c,'v_core_delta_number',raw)
                if record.get('quality_gate')=='未通过':
                    rejected.append({'record_id':raw['record_id'],'reason':'官方字段原格核验链未闭合'});continue
                field=raw['field_name'];value=record['values'][field];source=record['source'];sources[sid]=source
                rows.append(dict(record_id=raw['record_id'],province=province,year=raw['year'],subject=subject,school=raw['school_raw'],program=raw['major_name'],batch=raw.get('batch'),plan_type=raw.get('plan_type'),scope_raw=raw.get('scope_raw'),field=field,value=value['value'],unit=value['unit'],source_grade=value['grade'],source_id=sid,publisher=source.get('publisher'),landing_url=source.get('landing_url'),file_url=source.get('file_url'),archive_sha256=source.get('archive_sha256'),value_status=value['value_status'],locator=record['locator'],excerpt=record['excerpt']))
    fields='record_id province year subject school program batch plan_type scope_raw field value unit source_grade source_id publisher landing_url file_url archive_sha256 value_status locator excerpt'.split()
    result={'official_field_files':{},'official_field_exported_rows':{},'official_field_rejected':rejected,'official_field_sources':sources}
    for year in years:
        path=Path(out)/f'{province}-{subject}-{year}-official-fields.csv'
        with path.open('x',newline='',encoding='utf-8')as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            items=sorted((r for r in rows if r['year']==year),key=lambda r:r['record_id'])
            for row in items:writer.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True)if isinstance(v,(dict,list))else v for k,v in row.items()})
        result['official_field_files'][str(year)]=str(path);result['official_field_exported_rows'][str(year)]=len(items)
    return result


def export_gaokao(province, subject, years, *, out, schools=None, batch=None, plan_type=None, key='group', db=None):
    """Export pool inputs and separate reference CSVs, with scope and value sources."""
    from gaokao_export import collect, export_records, export_yfyd, collect_auxiliary, export_auxiliary, subject_options
    years = sorted(set(int(y) for y in years))
    if not years or any(y < 1900 or y > 2100 for y in years):
        raise QueryError('年份须为1900—2100的非空列表')
    cdf_targets=[Path(out)/f'{province}-{subject}-{year}-yfyd-{kind}.csv'for year in years for kind in ('all','usable')]
    if any(target.exists()for target in cdf_targets):raise QueryError('一分一段导出目标已存在，请使用新目录')
    auxiliary_targets=[Path(out)/f'{province}-{subject}-{year}-{kind}.csv'for year in years for kind in ('plans','batch-lines')]
    auxiliary_targets += [Path(out)/f'{province}-{subject}-{year}-official-fields.csv'for year in years]
    if any(target.exists()for target in auxiliary_targets):raise QueryError('计划或控制线导出目标已存在，请使用新目录')
    with _open('education', db) as (c, path):
        tables = _tables(c)
        selected = set(schools or [])
        if selected and 'institution' in tables:
            for school in schools:
                try: selected.add(_identity(c, school)[0]['institution_id'])
                except QueryError: pass
        records = collect(c, tables, province, subject, years)
        auxiliary=collect_auxiliary(c,tables,province,subject,years,schools=selected,batch=batch,plan_type=plan_type,completeness=lambda row:_source_completeness(c,row['_table'],row['source_id']))
        yfyd = []; cdf_rows={}; cdf_sources={}; cdf_coverage={}
        for year in years:
            if 'gk_official_yfyd' in tables:
                cdf_rows[year]=_yfyd_rows(c,province,year,subject)
                for item in cdf_rows[year]:
                    sid=item['source_id']
                    if sid not in cdf_sources:
                        cdf_sources[sid]=_source(c,sid)
                        cdf_coverage[sid]=_source_completeness(c,'gk_official_yfyd',sid)
                for row in c.execute('SELECT source_id,count(*) AS rows FROM data.gk_official_yfyd WHERE province=? AND year=? AND subject=? GROUP BY source_id',(province,year,subject)):
                    yfyd.append({'year':year,'source_id':row['source_id'],'rows':row['rows'],'completeness':_source_completeness(c,'gk_official_yfyd',row['source_id'])})
            if 'gk_yfyd_context' in tables:
                for row in c.execute("SELECT score,score_operator,scope_raw,source_id FROM data.gk_yfyd_context WHERE province=? AND year=? AND subject=? AND coalesce(score_operator,'=') NOT IN('','=', '＝')",(province,year,subject)):
                    yfyd.append({'year':year,'aggregate_context':dict(row)})
            if 'gk_yfyd_bucket' in tables:
                for row in c.execute('SELECT score_label,score_boundary,boundary_operator,source_id FROM data.gk_yfyd_bucket WHERE province=? AND year=? AND subject=?',(province,year,subject)):
                    yfyd.append({'year':year,'aggregate_bucket':dict(row)})
        try:
            result = export_records(records,province,subject,years,out=out,key=key,schools=selected,batch=batch,plan_type=plan_type,yfyd_metadata=yfyd)
            result['candidate_status']=result['status']
            result.update(export_yfyd(cdf_rows,province,subject,years,out=out,sources=cdf_sources,coverage=cdf_coverage,metadata=yfyd))
            aux=export_auxiliary(auxiliary,province,subject,years,out=out)
            for name in ('plan_files','batch_line_files','plan_exported_rows','batch_line_exported_rows'):
                aux[name]={str(k):v for k,v in aux[name].items()}
            result['auxiliary']=aux
            result['plan_exported_rows']=aux['plan_exported_rows']
            result['batch_line_exported_rows']=aux['batch_line_exported_rows']
            result.update(_export_official_core(c,tables,province,subject,years,out,selected,batch,plan_type))
            available={str(year):bool(result['exported_rows'][str(year)]or result['yfyd_exported_rows'][str(year)])for year in years}
            result['status']='ok' if all(available.values()) else 'partial' if any(available.values()) else 'missing_data'
            result['message']='未导出志愿候选；仅有一分一段原表' if not any(result['exported_rows'].values()) and any(result['yfyd_exported_rows'].values()) else '已分别列出候选、分段表及辅助原表行数'
            if not any(available.values()) and (any(aux['plan_exported_rows'].values()) or any(aux['batch_line_exported_rows'].values()) or any(result['official_field_exported_rows'].values())):
                result['status']='partial'
                result['message']='仅导出计划、控制线或已核官方字段辅助原表；志愿候选和一分一段仍缺，不可据此推算录取位次'
            if result.get('scope_audit_count'):
                result['message']+='；'+str(result['scope_audit_count'])+'条第三方范围记录单列审计，未阻断唯一官方原行；选科缺口未用第三方填充'
            if result.get('withheld_values'):
                result['message']+='；'+str(len(result['withheld_values']))+'条推算位次只留待核参照，未作实际投档位次进入模型；原分数及逐行定位仍可查询，详情见导出说明'
            missing_years=[year for year in years if not result['exported_rows'][str(year)] or not result['yfyd_exported_rows'][str(year)]]
            result['subject_options']=subject_options(c,tables,province,missing_years,requested=subject)
            if result['subject_options']:
                shown='；'.join(str(item['year'])+'年「'+item['subject']+'」（'+'、'.join(item['layers'])+'）'for item in result['subject_options'][:6])
                more='；其余标签见导出说明' if len(result['subject_options'])>6 else ''
                result['message']+='；本省相应年份另有原始科类标签：'+shown+more+'。请核对适用口径后重新指定；未自动换科类，标签存在不代表适用本考生或可导出，未按候选学校筛选'
        except ValueError as exc:
            raise QueryError(str(exc)) from exc
        result['database'] = str(path)
        if 'dataset_version' in tables:
            version=c.execute('SELECT version FROM data.dataset_version ORDER BY rowid DESC LIMIT 1').fetchone()
            result['database_version']=version[0] if version else None
        if 'storage_manifest' in tables:
            result['generation']=dict(c.execute('SELECT key,value FROM data.storage_manifest')).get('generation')
        (Path(out)/'export-metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return result


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv[:2]==['detail','source']:argv=argv[1:]
    ap=argparse.ArgumentParser(description='知衢本机统一只读查询；来源链与适用范围不合并')
    sub=ap.add_subparsers(dest='command',required=True)
    ex=sub.add_parser('export-gaokao');ex.add_argument('province');ex.add_argument('subject');ex.add_argument('--years',nargs='+',type=int,required=True);ex.add_argument('--out',required=True);ex.add_argument('--schools',nargs='+');ex.add_argument('--key',choices=['group','major'],default='group');ex.add_argument('--batch');ex.add_argument('--plan-type');ex.add_argument('--db');ex.add_argument('--json',action='store_true')
    yf=sub.add_parser('yfyd');yf.add_argument('province');yf.add_argument('year',type=int);yf.add_argument('subject');yf.add_argument('--db');yf.add_argument('--json',action='store_true');yf.add_argument('--full',action='store_true')
    choice=yf.add_mutually_exclusive_group(required=True);choice.add_argument('--score',type=float);choice.add_argument('--rank',type=float)
    for cmd in ['school','program','jobs','source']:
        p=sub.add_parser(cmd);p.add_argument('--db');p.add_argument('--json',action='store_true');p.add_argument('--full',action='store_true',help='展开当前页的完整文字与来源；分页仍用--limit/--offset');p.add_argument('--limit',type=int,default=10);p.add_argument('--offset',type=int,default=0)
        if cmd in ['school','program']:p.add_argument('school');p.add_argument('--year',type=int);p.add_argument('--province')
        if cmd in ['school','program']:p.add_argument('--major');p.add_argument('--subject');p.add_argument('--plan-type')
        if cmd=='program':p.add_argument('program')
        if cmd=='jobs':p.add_argument('--region');p.add_argument('--major');p.add_argument('--year',type=int);p.add_argument('--education-db')
        if cmd=='source':p.add_argument('source_id');p.add_argument('--domain',choices=['education','employment'],default='education')
    ns=vars(ap.parse_args(argv));command=ns.pop('command');as_json=ns.pop('json');full=ns.pop('full',False)
    try:
        if command=='export-gaokao':
            res=export_gaokao(**ns)
            if as_json:print(json.dumps(res,ensure_ascii=False,indent=2))
            else:print('逐年导出：'+'；'.join(year+'年 志愿候选'+str(n)+'行，一分一段'+str(res['yfyd_exported_rows'].get(year,0))+'行（可读累计'+str(res['yfyd_usable_rows'].get(year,0))+'行），计划'+str(res['plan_exported_rows'].get(year,0))+'行，控制线'+str(res['batch_line_exported_rows'].get(year,0))+'行，已核官方字段'+str(res['official_field_exported_rows'].get(year,0))+'项'for year,n in res['exported_rows'].items())+'；冲突'+str(res['conflict_count'])+'条；'+res['message']+'；见'+str(Path(ns['out'])/'export-metadata.json'))
            return 2 if res.get('status')=='missing_data' else 0
        elif command=='yfyd':res=query_yfyd(**ns)
        elif command=='school':res=query_school(ns.pop('school'),**ns)
        elif command=='program':res=query_program(ns.pop('school'),ns.pop('program'),**ns)
        elif command=='jobs':res=query_jobs(**ns)
        else:res=query_source(ns.pop('source_id'),**ns)
        print(json.dumps(res,ensure_ascii=False,indent=2) if as_json else render_text(res,full=full),end='\n' if as_json else '')
    except (QueryError,sqlite3.Error) as e:ap.exit(2,'查询未完成：'+str(e)+'\n')
    return 2 if res.get('status')=='missing_data' else 0

if __name__=='__main__':sys.exit(main())
