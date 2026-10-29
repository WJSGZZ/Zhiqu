"""Append independent checks to existing official lines; never replace old facts.

The existing ky_check_sample audit table is the event log. No new schema or
source is introduced. Ambiguous identity, scope, numbers or originals fail shut.
"""
import copy
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

from ingest_kaoyan_lines import candidate_path, dump, privacy

FIELD='on_demand_line_verification_v1'
IDENTITY=('school','institution_id','year','college','program_code','program_name','degree_type','study_mode','special_plan')
NUMBERS=('total','politics','english','math','major1','major2')
SCOPES=('direction','joint_program','admission_route')

def norm(v):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(v or '')))

def projection(row):
    result={k:norm(row.get(k))for k in IDENTITY}
    result['degree_type']={'专业':'专业学位','专硕':'专业学位','学术':'学术学位','学硕':'学术学位'}.get(result['degree_type'],result['degree_type'])
    if not all(result[k]for k in IDENTITY if k!='special_plan') or result['study_mode']not in ('全日制','非全日制'):
        raise ValueError('存量行身份或学习方式不明确')
    for k in NUMBERS:
        v=row.get(k)
        if v is None or v=='':result[k]=None;continue
        if isinstance(v,bool):raise ValueError('非法存量分值')
        try:
            d=Decimal(str(v))
            if not d.is_finite()or d<0:raise ValueError('非法存量分值')
            result[k]=format(d.normalize(),'f')
        except InvalidOperation:raise ValueError('非法存量分值')from None
    return result

def _proof(item,source):
    if not isinstance(item,dict)or not isinstance(item.get('row'),dict)or not isinstance(item.get('review'),dict)or not isinstance(item.get('locator'),dict):raise ValueError('核验行或定位结构无效')
    review=item['review'];p=review.get('file_proof',{})
    if not isinstance(p,dict):raise ValueError('抽核证明结构无效')
    if review.get('status')!='approved' or p.get('sha256')!=source['archive_sha256']:
        raise ValueError('存量核验缺原件绑定')
    n=p.get('original_rows');locs=p.get('sample_locators',[])
    if not isinstance(locs,list):raise ValueError('抽样清单结构无效')
    if type(n)is not int or n<1 or p.get('extracted_rows')!=n or p.get('dual_read_equal')is not True or p.get('sample_passed')is not True:
        raise ValueError('存量核验缺整表双读证明')
    # First implementation reuses text-table evidence only; image checks remain
    # on the original ingestion path until their complete proof can be reused.
    if re.search('读图|image',str(item['row'].get('read_method','')),re.I):raise ValueError('存量图片核验暂不复用')
    if item['row'].get('read_method')!='文字双DOM':raise ValueError('存量复核当前仅支持已闭合的HTML双DOM表')
    def positive(value):
        if isinstance(value,bool)or not re.fullmatch('[1-9][0-9]*',str(value)):raise ValueError('原件定位必须为正整数')
        return int(value)
    location=item.get('locator',{})
    expected={key:positive(item.get('src_'+key))for key in ('page','table','row')}
    if any(positive(location.get(k))!=value for k,value in expected.items()):raise ValueError('物理行定位不一致')
    if positive(p.get('table'))!=expected['table']:raise ValueError('抽核表号不符')
    headers=p.get('header_continuation_rows',[])
    if not isinstance(headers,list):raise ValueError('续表头结构无效')
    excluded={1}
    for header in headers:
        if not isinstance(header,dict)or any(positive(header.get(k))!=expected[k]for k in ('page','table')):raise ValueError('续表头定位无效')
        excluded.add(positive(header.get('row')))
    bound=n+len(headers)+1
    for sample in locs:
        if not isinstance(sample,dict)or not {'page','table','row'}<=sample.keys():raise ValueError('抽核必须为真实物理格定位')
        point={k:positive(sample[k])for k in ('page','table','row')}
        if point['page']!=expected['page']or point['table']!=expected['table']or point['row']>bound or point['row']in excluded:raise ValueError('抽核定位超出本表范围')
    if expected['row']>bound or expected['row']in excluded or len({dump({k:int(x[k])for k in ('page','table','row')})for x in locs})<max(math.ceil(n*.03),min(3,n)):raise ValueError('存量核验抽核不足')
    if any(type(item.get(k))is bool or item.get(k)in (None,'')for k in ('src_page','src_table','src_row')):
        raise ValueError('存量核验缺原页表行')
    if item.get('locator',{}).get('sha256')!=source['archive_sha256']:raise ValueError('存量行原件指纹不符')
    return p

def prepare(c,manifest,schema="main"):
    """Read-only, all-or-nothing match; return events, not rewritten rows."""
    privacy(manifest);events=[];sources={}
    if schema not in ("main","data"):raise ValueError("核验只读库范围不符")
    c.row_factory=sqlite3.Row
    for source in manifest['sources']:
        if not re.fullmatch('[0-9a-f]{64}',source.get('archive_sha256','')):raise ValueError('原件指纹无效')
        matches=c.execute('select * from '+schema+'.source where archive_sha256=?',(source['archive_sha256'],)).fetchall()
        if len(matches)!=1 or matches[0]['grade']!='官方':raise ValueError('存量原件来源不唯一或非官方')
        old=dict(matches[0]);urls={source.get(k)for k in ('landing_url','file_url')if source.get(k)}
        if not urls.intersection({old.get(k)for k in ('landing_url','file_url')}):raise ValueError('同指纹来源网址无法对应')
        sources[source['source_id']]=(source,old)
    for item in manifest['rows']:
        source,oldsource=sources[item['source_id']];_proof(item,source);new=projection(dict(item['row'],institution_id=item['institution_id']))
        if new['total']is None:raise ValueError('存量复核须有明确总分，文字规则另核')
        scope=item.get('scope_context',{})
        if not isinstance(scope,dict):raise ValueError('范围结构无效')
        if any(norm(scope.get(k))for k in SCOPES)or re.search('专项|调剂|联培|联合培养|研究方向|士兵|少民|骨干',str(scope.get('scope_raw',''))+' '+str(item['row'].get('note',''))+' '+str(item['row'].get('line_scope','')))or new['special_plan']or item.get('components'):
            raise ValueError('存量核验不合并方向、专项或泛化科目槽')
        rows=c.execute('select * from '+schema+'.ky_retest_line where source_id=? and institution_id=? and year=? and program_code=? and college=?',
                       (oldsource['source_id'],item['institution_id'],item['row']['year'],item['row']['program_code'],item['row']['college'])).fetchall()
        if len(rows)!=1:raise ValueError('同源存量业务行不唯一')
        old=dict(rows[0])
        if old.get('quarantine_reason')is not None or old.get('line_scope')not in ('专业线','学院专业资格线')or projection(old)!=new:
            raise ValueError('存量数值或适用范围不一致')
        # Old records with extra scope must not be certified just because the
        # visible school/program/total happened to match.
        if re.search('专项|调剂|联培|联合培养|研究方向|士兵|少民|骨干',old.get('note','')or''):
            raise ValueError('存量原文含额外范围，需另核')
        tables={r[0]for r in c.execute("select name from "+schema+".sqlite_master where type='table'")}
        context=c.execute('select direction,joint_program,admission_route,scope_raw from '+schema+'.ky_line_scope_context where record_id=?',(old['record_id'],)).fetchone()if 'ky_line_scope_context'in tables else None
        if context and (any(norm(v)for v in context[:3])or re.search('专项|调剂|联培|联合培养|研究方向|士兵|少民|骨干',str(context[3]or''))):raise ValueError('存量行另有方向或路线')
        # Do not decide arbitrary raw prose with a blacklist. The only removed
        # scope fragment is the independently read degree/mode category cell.
        try:category=json.loads(item['excerpt']).get('类别')
        except (ValueError,TypeError,AttributeError):raise ValueError('缺独立类别原格')from None
        if not isinstance(category,str)or norm(category)!=('专业硕士'if new['degree_type']=='专业学位'else'学术硕士')+'('+new['study_mode']+')':raise ValueError('类别原格与学位学习方式不符')
        def raw_scope(text):
            parts=re.split('[;；]',norm(text))
            # One observed, literal announcement preface. No wildcard prose:
            # any additional qualification remains and must compare exactly.
            preface=norm(f"根据教育部、江苏省教育考试院相关文件精神，结合我校实际情况，经学校硕士研究生招生工作领导小组研究决定，现将我校{new['year']}年硕士研究生复试分数线公布如下：")
            return ';'.join(part for part in parts if part and part not in ('原表类别:'+norm(category),preface))
        def total_note(text):
            # These describe transcription or single-subject rules, not the
            # total-score population. Keep them verbatim in the event snapshot;
            # the certificate explicitly verifies year/total ONLY.
            metadata={'总分线','首次','只取原总分列','单科未提供','单科线执行国家A类基本要求','单科线执行国家B类基本要求'}
            return ';'.join(part for part in raw_scope(text).split(';')if part and part not in metadata)
        old_raw=context[3]if context else ''
        if any((raw_scope(old_raw),raw_scope(scope.get('scope_raw','')),total_note(old.get('note')),total_note(item['row'].get('note')))):
            raise ValueError('原始范围或备注不等价，不能仅凭分值复用核验')
        if raw_scope(item['row'].get('line_scope',''))!=raw_scope(scope.get('scope_raw','')):raise ValueError('候选原范围文字不一致')
        event={'protocol':FIELD,'record_id':old['record_id'],'source_id':oldsource['source_id'],'archive_sha256':source['archive_sha256'],
               'projection':new,'verified_fields':['year','total'],'scope_context':scope,'existing_scope_snapshot':{'line_scope':old.get('line_scope'),'note':old.get('note'),'context':list(context)if context else None},'checked_date':source['retrieved'],'candidate':copy.deepcopy(item)}
        if dt.date.fromisoformat(event['checked_date'])>dt.date.today():raise ValueError('不能用未来核验日期')
        event['candidate']['source_id']=oldsource['source_id']
        event['event_sha256']=hashlib.sha256(dump(event).encode()).hexdigest();events.append(event)
    if not events:raise ValueError('没有存量核验行')
    return {'sources':[dict(old)for _,old in sources.values()],'rows':events}

def _read_events(c,record_id,source_id):
    rows=c.execute('select library_value,official_value,note,checked_date from audit.ky_check_sample where table_name=? and row_key=? and field=? and official_source_id=? and status=?',
                   ('ky_retest_line',record_id,FIELD,source_id,'一致')).fetchall()
    for library,official,note,checked_date in rows:
        try:
            event=json.loads(note);payload=dict(event);sha=payload.pop('event_sha256')
            if sha!=hashlib.sha256(dump(payload).encode()).hexdigest()or event['protocol']!=FIELD:continue
            if event['record_id']!=record_id or event['source_id']!=source_id or event['checked_date']!=checked_date:continue
            if library!=official or json.loads(library)!=event['projection']:continue
            yield event
        except (ValueError,KeyError,TypeError):continue

def ingest(database,manifest):
    """Candidate only; recheck against that pair before appending each event."""
    path=candidate_path(database);privacy(manifest)
    with sqlite3.connect(path)as c:
        c.row_factory=sqlite3.Row;cfg=dict(c.execute('select key,value from storage_manifest'));audit=path.parent/cfg['audit_file']
        if audit.parent.resolve()!=path.parent or not audit.is_file()or audit.is_symlink()or not re.fullmatch(r'audit-[a-z0-9-]+\.sqlite',audit.name):raise ValueError('审计路径不符')
        c.execute('attach database ? as audit',(str(audit),))
        if dict(c.execute('select key,value from audit.storage_manifest'))['generation']!=cfg['generation']:raise ValueError('审计代号不符')
        count=0
        for event in manifest['rows']:
            source=next(s for s in manifest['sources']if s['source_id']==event['source_id'])
            expected=prepare(c,{'sources':[source],'rows':[event['candidate']]})['rows'][0]
            # The canonical source retains its first-retrieval date; the event
            # separately records this verification date and the re-read proof.
            expected['checked_date']=event['checked_date'];expected.pop('event_sha256');expected['event_sha256']=hashlib.sha256(dump(expected).encode()).hexdigest()
            if expected!=event:raise ValueError('存量核验事件已变化')
            existing=list(_read_events(c,event['record_id'],event['source_id']))
            if any(x['event_sha256']==event['event_sha256']for x in existing):continue
            value=dump(event['projection'])
            c.execute('insert into audit.ky_check_sample(table_name,row_key,field,library_value,official_value,official_source_id,status,checked_date,note)values(?,?,?,?,?,?,?,?,?)',
                      ('ky_retest_line',event['record_id'],FIELD,value,value,event['source_id'],'一致',event['checked_date'],dump(event)));count+=1
    return {'inserted':0,'existing':len(manifest['rows']),'verification_events_inserted':count,'sources_inserted':0}

def verify(c,manifest):
    count=0
    for expected in manifest['rows']:
        matches=[e for e in _read_events(c,expected['record_id'],expected['source_id'])if e==expected]
        if len(matches)!=1:raise ValueError('核验事件实际回读不符')
        row=c.execute('select * from ky_retest_line where record_id=?',(expected['record_id'],)).fetchone()
        if row is None or projection(dict(row))!=expected['projection']:raise ValueError('核验后的旧业务值不符')
        if not _semantic_event(c,expected,'main'):raise ValueError('核验事件候选或当前范围不符')
        count+=1
    return count


def _semantic_event(c,event,schema):
    try:
        source=dict(c.execute('select * from '+schema+'.source where source_id=?',(event['source_id'],)).fetchone())
        expected=prepare(c,{'sources':[source],'rows':[event['candidate']]},schema)['rows'][0]
        if dt.date.fromisoformat(event['checked_date'])>dt.date.today():return False
        expected['checked_date']=event['checked_date'];expected.pop('event_sha256')
        expected['event_sha256']=hashlib.sha256(dump(expected).encode()).hexdigest()
        return expected==event
    except (ValueError,TypeError,KeyError,AttributeError,sqlite3.Error):return False


def verified_record(c,record_id):
    """Recheck the full candidate, source and current scoped row at every hit."""
    c.row_factory=sqlite3.Row
    row=c.execute('select source_id from data.ky_retest_line where record_id=?',(record_id,)).fetchone()
    if not row:return None
    for event in _read_events(c,record_id,row['source_id']):
        if _semantic_event(c,event,'data'):return event
    return None
