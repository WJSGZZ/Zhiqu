"""Read-only gaokao exports; scope and field-level provenance survive CSV."""
import collections
import csv
import json
import math
import re
from pathlib import Path
import unicodedata

FIELDS = ('rank', 'score', 'plan')
CSV_FIELDS = ['code','name','group','major','major_code','rank','plan','score','year','batch','plan_type','requirement','source_grade','source_id','value_status','data_provenance']
CONFLICT_FIELDS = ['year','school','group','major','batch','plan_type','field','values','source_ids','reason','resolution','scope']

def text(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()

def obj(value):
    if isinstance(value, dict): return value
    try:
        parsed = json.loads(value or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError): return {}

def number(value):
    if value is None or value == '' or isinstance(value, bool): return None
    try: value = float(value)
    except (ValueError, TypeError): return None
    if not math.isfinite(value) or value < 0: return None
    return int(value) if value.is_integer() else value

def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def group_code(value):
    value=text(value)
    match=re.fullmatch(r'\(([0-9A-Za-z]+)\)',value)
    return match.group(1) if match else value

def requirement(value, subject):
    value=text(value)
    match=re.fullmatch(r'首选(物理|历史)[,、; ]*再选(.+)',value)
    if match and match.group(1)==subject:value=match.group(2).strip()
    item=r'(思想政治|物理|历史|化学|生物|地理)'
    both=re.fullmatch(item+r'(?:和|与)'+item,value) or re.fullmatch(item+r'[,、]'+item+r'\(2科必选\)',value)
    return '、'.join(sorted(both.groups()))+'(2科必选)' if both else value

def scope_text(value):
    value=text(value)
    try: parsed=json.loads(value)
    except (ValueError,TypeError): return value
    if parsed in ([],{},None): return ''
    if isinstance(parsed,list) and all(isinstance(x,list)and len(x)==2 for x in parsed):
        return dump(sorted([[text(k),text(v)]for k,v in parsed if text(v)]))
    return dump(parsed)

def _source(c, source_id, cache):
    if source_id not in cache:
        found = c.execute('SELECT * FROM data.source WHERE source_id=?', (source_id,)).fetchone() if source_id else None
        cache[source_id] = dict(found, _registered=True) if found else {'source_id':source_id, 'grade':'未登记', '_registered':False}
    return cache[source_id]

def _scope(row):
    return {k: row.get(k, '') for k in ('province','year','subject','institution_id','code','batch','group','major_code','major','plan_type','requirement','scope_raw','name')}

def valid_cross_check(check, row, field, value):
    """Only an explicit per-value, full-scope official comparison may upgrade a label."""
    if not isinstance(check,dict): return False
    official=check.get('official_source')
    return (check.get('verdict')=='一致' and check.get('field')==field
            and check.get('scope')==_scope(row) and check.get('thirdparty_scope')==_scope(row)
            and check.get('official_value')==value and check.get('thirdparty_value')==value
            and isinstance(official,dict) and official.get('grade')=='官方'
            and official.get('source_id') and (official.get('landing_url') or official.get('file_url'))
            and check.get('official_locator') and check.get('comparison_basis')=='同事实同口径逐值')

def _meta(row, field, value, source, state, locator, checks=None, cross_check=None):
    checks = checks or []
    grade = source.get('grade') or '未登记'
    registered = source.get('_registered',bool(source.get('source_id'))) and grade in ('官方','第三方整理')
    confirmed = grade=='第三方整理' and value is not None and valid_cross_check(cross_check,row,field,value)
    display = '官方' if grade=='官方' else '官方一致' if confirmed else '第三方整理·内部未核'
    state = dict(state) if isinstance(state,dict) else {}
    if not state.get('status') or state.get('status') in ('未注明','未知'):
        state = {'status':'来源未提供' if value is None else '官方原值' if grade=='官方' else '第三方整理未核',
                 'reason':'原来源未提供此值，不补数' if value is None else '来源表登记等级为官方，保留原值' if grade=='官方' else '整理来源，尚无同事实同口径逐值官方核对凭据'}
    result = {'value':value, 'source_registered':bool(registered), 'grade':grade, 'display_grade':display, 'source_id':source.get('source_id') or row.get('source_id',''), 'publisher':source.get('publisher',''), 'title':source.get('title',''), 'url':source.get('landing_url') or source.get('file_url',''), 'landing_url':source.get('landing_url',''), 'file_url':source.get('file_url',''), 'value_status':state, 'locator':locator, 'scope':_scope(row), 'completeness':row.get('completeness'), 'checks':checks, 'original_scope':row.get('original_scope',_scope(row))}
    if grade=='第三方整理':
        historical=[c for c in checks if str(c.get('kind','')).startswith('rank_vs_yfyd')]
        result['cross_check_summary']={'scope':'本值同口径官方投档逐值核对','checked':1 if confirmed else 0,'inconsistent':0,'note':'有完整同事实同口径逐值官方凭据' if confirmed else '本值同口径官方投档未核；未将其他范围或全来源历史抽样算成本值已核','other_checks':checks}
        if historical: result['cross_check_summary']['note']+='；已有位次与官方一分一段吻合检查，属于位次口径检查，不是官方投档逐值核对'
    if confirmed: result['cross_check']=cross_check
    return result


def collect(c, tables, province, subject, years):
    """Read existing logical tables. No fallback rank conversion or guessed scope."""
    source_cache = {}; completeness_cache = {}; school_ids = {}; result = []
    def source(sid): return _source(c, sid, source_cache)
    def normalize(raw, table):
        scope = obj(raw.get('_scope_json'))
        extra_scope = {k:v for k,v in scope.items() if k not in {'batch','批次','group','grp','major','major_code','plan_type','subject','province','year','name','code','institution_id','requirement','subject_requirements','group_code','school_code','school_name','school_raw','major_name'}}
        scope_conflicts=[]
        def pick(field, raw_keys, scope_keys):
            candidates=[text(raw[k])for k in raw_keys if raw.get(k)not in(None,'')]+[text(scope[k])for k in scope_keys if scope.get(k)not in(None,'')]
            normalize_value=group_code if field=='group' else (lambda v:requirement(v,subject)) if field=='requirement' else text
            if len({normalize_value(v)for v in candidates})>1:scope_conflicts.append({'field':field,'original_values':candidates})
            return candidates[0] if candidates else ''
        row = {'province':province, 'year':int(raw['year']), 'subject':subject,
               'code':pick('code',('code','school_code'),('code','school_code')), 'name':pick('name',('name','school_name','school_raw'),('name','school_name','school_raw')),
               'group':pick('group',('grp','group_code'),('group','grp','group_code')), 'major_code':pick('major_code',('major_code',),('major_code',)),
               'major':pick('major',('major','major_name'),('major','major_name')), 'institution_id':pick('institution_id',('institution_id',),('institution_id',)),
               'batch':pick('batch',('batch',),('batch','批次')),
               'plan_type':pick('plan_type',('plan_type',),('plan_type',)) or '未标', 'requirement':pick('requirement',('subject_requirements','subject_req_raw'),('requirement','subject_requirements')),
               'scope_raw':text(raw.get('scope_raw')) or (dump(extra_scope) if extra_scope else ''), 'record_id':raw.get('record_id',raw.get('entry_id')), 'table':table,
               'source_id':raw.get('source_id') or ('vendor-file-'+str(raw.get('src_file')) if raw.get('src_file') is not None else ''),
               'completeness':None,'scope_conflicts':scope_conflicts}
        row['original_scope']=dict(_scope(row),source_scope_original=scope)
        row['group']=group_code(row['group'])
        row['requirement']=requirement(row['requirement'],subject)
        row['scope_raw']=scope_text(row['scope_raw'])
        if not row['institution_id'] and table=='gk_v_usable' and 'gk_school_code_map' in tables:
            mk=(province,row['code'],raw.get('ingest_id'))
            if mk not in school_ids:
                found=c.execute('SELECT DISTINCT institution_id FROM data.gk_school_code_map WHERE province=? AND school_code=? AND ingest_id=?',mk).fetchall()
                school_ids[mk]=found[0][0] if len(found)==1 else ''
            row['institution_id']=school_ids[mk]
        if table == 'gk_official_cutoff':
            row['grain'] = 'major' if row['major_code'] or row['major'] and not row['group'] else 'group' if row['group'] else 'school'
            if row['grain'] == 'group':
                row['requirement'] = row['requirement'] or row['major']; row['major'] = ''
        else:
            row['grain'] = 'major' if row['major_code'] or row['major'] else 'group' if row['group'] else 'school'
        if table == 'gk_v_purchased' and raw.get('dataset_type') not in ('投档线','专业录取分'):
            return None
        statuses = obj(raw.get('value_status')); overrides = obj(raw.get('field_source_ids'))
        field_map = {'rank':'rank' if table == 'gk_official_cutoff' else 'min_rank', 'score':'score' if table == 'gk_official_cutoff' else 'min_score', 'plan':'plan' if table == 'gk_official_cutoff' else 'plan_n'}
        row['values'] = {}; row['provenance'] = {}
        for field, original in field_map.items():
            value = number(raw.get(original)); row['values'][field] = value
            sid = overrides.get(original) or row['source_id']; src = source(sid)
            locator = {k:raw.get(k) for k in ('src','src_row','src_page','src_table','src_sheet') if raw.get(k) not in (None,'')}
            checks = []
            # An yfyd consistency check is not a same-scope official cutoff check.
            if table == 'gk_v_usable' and 'gk_check_sample' in tables:
                for check in c.execute("SELECT * FROM data.gk_check_sample WHERE entry_id=? AND year=? AND (field=? OR (?='rank' AND field IN('rank_vs_yfyd_m','rank_vs_yfyd_g'))) AND (table_name='result' OR field LIKE 'rank_vs_yfyd_%')", (raw.get('entry_id'),raw['year'],original,field)):
                    d = dict(check); official = source(d.get('official_source_id'))
                    checks.append({'kind':d['field'] if d['field'].startswith('rank_vs_yfyd') else 'unconfirmed_scope_check','same_scope':False,'same_value':d.get('verdict')=='一致','verdict':d.get('verdict'),'official_source_id':official.get('source_id'),'field':d['field']})
                    # A historical correction/check with unconfirmed scope is
                    # retained as an audit lead, not borrowed as official origin.
            if table == 'gk_v_purchased' and 'purchased_check' in tables:
                for check in c.execute('SELECT * FROM data.purchased_check WHERE record_id=? AND field=?', (raw.get('record_id'),original)):
                    d = dict(check)
                    checks.append({'kind':'unconfirmed_scope_check','same_scope':False,'same_value':d.get('verdict')=='一致','verdict':d.get('verdict'),'official_source_id':d.get('official_source_id'),'official_locator':d.get('official_locator')})
            row['provenance'][field] = _meta(row, field, value, src, statuses.get(original), locator, checks)
        if 'meta' in tables and row['source_id']:
            prefix = 'gk_source_coverage:'+row['source_id']+':'+table+':'
            if prefix not in completeness_cache:
                found = c.execute('SELECT value FROM data.meta WHERE key>=? AND key<? ORDER BY rowid DESC LIMIT 1',(prefix,prefix+'\uffff')).fetchone()
                completeness_cache[prefix] = obj(found[0]) if found else None
            row['completeness'] = completeness_cache[prefix]
            for meta in row['provenance'].values(): meta['completeness'] = row['completeness']
        return row
    for year in years:
        if 'gk_official_cutoff' in tables:
            join = ' LEFT JOIN data.official_cutoff_scope k ON k.source_id=t.source_id AND k.public_record=t.src' if 'official_cutoff_scope' in tables else ''
            scope_select = ',k.scope_json AS _scope_json' if join else ''
            for item in c.execute('SELECT t.*'+scope_select+' FROM data.gk_official_cutoff t'+join+' WHERE t.province=? AND t.year=? AND t.subject=?',(province,year,subject)):
                result.append(normalize(dict(item),'gk_official_cutoff'))
        if {'gk_v_usable','gk_v_plan'} <= tables:
            sql = 'SELECT v.*,p.plan_n,p.plan_year,p.ingest_id,p.subject_req_raw,p.major_note,p.other_req,p.foreign_lang_req,p.src_file,p.src_row FROM data.gk_v_usable v JOIN data.gk_v_plan p USING(entry_id) WHERE v.province=? AND v.year=? AND v.subject_type=?'
            for item in c.execute(sql,(province,year,subject)):
                raw = dict(item)
                if raw.get('plan_year') != raw['year']: raw['plan_n'] = None
                raw['scope_raw']=dump([[label,raw[field]]for label,field in [('专业备注','major_note'),('其他要求','other_req'),('外语要求','foreign_lang_req')]if raw.get(field)])
                result.append(normalize(raw,'gk_v_usable'))
        if 'gk_v_purchased' in tables:
            # Filtering by dataset before requesting numeric columns avoids exporting plans or purchased yfyd as cutoffs.
            sql = "SELECT * FROM data.gk_v_purchased WHERE province=? AND year=? AND subject=? AND dataset_type IN('投档线','专业录取分')"
            for item in c.execute(sql,(province,year,subject)):
                result.append(normalize(dict(item),'gk_v_purchased'))
    return [r for r in result if r is not None]

def export_records(records, province, subject, years, *, out, key='group', schools=None, batch=None, plan_type=None, yfyd_metadata=None):
    """Pure merge/export path, also exercised by offline fixtures."""
    if key not in ('group','major'): raise ValueError('key须为group或major')
    years = sorted(set(int(y) for y in years)); out = Path(out)
    if not years: raise ValueError('至少指定一年')
    out.mkdir(parents=True,exist_ok=True)
    targets = [out/f'{province}-{subject}-{y}.csv' for y in years]+[out/'conflicts.csv',out/'export-metadata.json']
    if any(p.exists() for p in targets): raise ValueError('导出目标已存在；请使用新目录，避免覆盖旧案例')
    selected=[]; rejected=[]; conflicts=[]
    school_set=set(schools or [])
    for row in records:
        if row['year'] not in years: continue
        if school_set and not {row.get('institution_id'),row.get('name'),row.get('code')} & school_set: continue
        if batch is not None and row.get('batch') != batch: continue
        if plan_type is not None and row.get('plan_type') != plan_type: continue
        if row.get('scope_conflicts'):
            rejected.append({'year':row['year'],'school':row.get('name'),'record_id':row.get('record_id'),'table':row.get('table'),'reason':'业务列与明确scope字段冲突，不猜范围','scope_conflicts':row['scope_conflicts']})
            continue
        unregistered=[field for field in FIELDS if row['values'].get(field) is not None and (not row['provenance'][field].get('source_registered') or row['provenance'][field].get('grade')not in ('官方','第三方整理'))]
        if unregistered:
            rejected.append({'year':row['year'],'school':row.get('name'),'record_id':row.get('record_id'),'table':row.get('table'),'reason':'缺真实来源登记或有效等级：'+','.join(unregistered)})
            continue
        missing=[k for k in ('code','name','batch') if not row.get(k)]
        if row.get('grain') != key: missing.append('requested_'+key+'_grain')
        if key=='group' and not row.get('group'): missing.append('group')
        if key=='major' and not row.get('major'): missing.append('major')
        if missing:
            rejected.append({'year':row['year'],'school':row.get('name'),'record_id':row.get('record_id'),'table':row.get('table'),'reason':'缺少或不符合关键范围：'+','.join(missing)})
        else: selected.append(row)
    def identity(r):
        school = ('id',r['institution_id']) if r.get('institution_id') else ('name',r['name'])
        campus_scope = r['name'] if re.search(r'校区|分校|校本部|办学点|教学点',r['name']) else ''
        return (r['year'],school,r['code'],campus_scope,r['batch'],r.get('group',''),r.get('major_code',''),r.get('major',''),r.get('plan_type','未标'),r.get('requirement',''),r.get('scope_raw',''))
    groups=collections.defaultdict(list)
    for r in selected: groups[identity(r)].append(r)
    merged=[]
    def conflict(row,field,candidates,reason,resolution):
        conflicts.append({'year':row['year'],'school':row['name'],'group':row.get('group',''),'major':row.get('major',''),'batch':row['batch'],'plan_type':row.get('plan_type','未标'),'field':field,'values':dump([v for v,m in candidates]),'source_ids':dump([m.get('source_id') for v,m in candidates]),'reason':reason,'resolution':resolution,'scope':dump(_scope(row))})
    for facts in groups.values():
        representative=sorted(facts,key=lambda r:(r.get('table',''),str(r.get('record_id',''))))[0]; values={};provenance={}
        for field in FIELDS:
            candidates=[(r['values'].get(field),r['provenance'][field]) for r in facts if r['values'].get(field) is not None]
            official=[x for x in candidates if x[1].get('grade')=='官方'];chosen=official or candidates
            distinct={v for v,m in chosen}
            if len(distinct)>1:
                conflict(representative,field,chosen,'同口径官方值冲突' if official else '第三方来源之间不一致','该值不导出')
                values[field]=None;provenance[field]={'value':None,'grade':'未取得','display_grade':'来源冲突未取值','value_status':{'status':'待核'},'scope':_scope(representative),'conflict':True};continue
            if chosen:
                value,meta=sorted(chosen,key=lambda x:x[1].get('source_id',''))[0];meta=dict(meta)
                meta['additional_source_ids']=sorted({m.get('source_id','')for v,m in candidates if v==value})
                meta['additional_sources']=[dict(m)for v,m in candidates if v==value]
                if meta.get('grade')=='第三方整理':
                    historical=[]
                    for same_value,same_meta in candidates:
                        if same_value==value:
                            historical.extend([dict(check,checked_source_id=same_meta.get('source_id'))for check in same_meta.get('checks',[])])
                    meta['checks']=historical
                    summary=dict(meta['cross_check_summary']);summary['other_checks']=historical
                    if any(str(check.get('kind','')).startswith('rank_vs_yfyd')for check in historical):
                        summary['note']='本值同口径官方投档未核；同事实同值来源已有位次与官方一分一段检查，这不是官方投档逐值核对；该历史检查未计为本值官方投档已核'
                    meta['cross_check_summary']=summary
                if official:
                    meta['cross_checks']=[{'verdict':'一致','field':field,'scope':meta.get('scope'),'thirdparty_scope':other_meta.get('scope'),'scope_identity':identity(representative),'official_value':value,'thirdparty_value':other_value,'official_source':{k:meta.get(k)for k in ('source_id','grade','publisher','title','landing_url','file_url')},'official_locator':meta.get('locator'),'thirdparty_source_id':other_meta.get('source_id'),'comparison_basis':'同事实同口径逐值'}for other_value,other_meta in candidates if other_meta.get('grade')=='第三方整理' and other_value==value]
                    contrary=[x for x in candidates if x[1].get('grade')!='官方' and x[0]!=value]
                    if contrary: conflict(representative,field,official+contrary,'第三方与同口径官方冲突','采用官方值')
                values[field]=value;provenance[field]=meta
            else:
                values[field]=None;provenance[field]={'value':None,'grade':'未取得','display_grade':'来源未提供','source_id':'','value_status':{'status':'来源未提供'},'scope':_scope(representative),'completeness':representative.get('completeness')}
        row=dict(representative,values=values,provenance=provenance)
        if values['rank'] is None or not isinstance(values['rank'],int) or values['rank']<1:
            rejected.append({'year':row['year'],'school':row['name'],'record_id':row.get('record_id'),'reason':'缺可用整数位次；不从分数换算，不跨缺口插值'});continue
        merged.append(row)
    # pool's join key omits batch/scope/plan_type. Never let it silently collapse
    # these facts; callers must select an unambiguous scope first.
    poolkeys=collections.defaultdict(list)
    for r in merged: poolkeys[(r['year'],r['code'],r['group'] if key=='group' else r['major'])].append(r)
    accepted=[]
    for rows in poolkeys.values():
        if len(rows)>1:
            for row in rows:
                conflict(row,'scope',[(row['values']['rank'],row['provenance']['rank'])],'同一pool键存在不同批次/组/专业/计划/范围','全部排除；须明确范围后重导')
                rejected.append({'year':row['year'],'school':row['name'],'record_id':row.get('record_id'),'reason':'pool键范围不唯一'})
        else: accepted+=rows
    counts={};paths={}
    for year in years:
        path=out/f'{province}-{subject}-{year}.csv';ys=sorted((r for r in accepted if r['year']==year),key=lambda r:(r['code'],r.get('group',''),r.get('major','')))
        with path.open('w',newline='',encoding='utf-8')as f:
            writer=csv.DictWriter(f,fieldnames=CSV_FIELDS);writer.writeheader()
            for r in ys:
                v,p=r['values'],r['provenance'];sources=sorted({m.get('source_id','')for m in p.values()if m.get('source_id')});grades=[m['display_grade']for m in p.values()if m.get('value')is not None]
                weakest=max(grades,key={'官方':0,'官方一致':1,'第三方整理·内部未核':2}.__getitem__)
                writer.writerow({'code':r['code'],'name':r['name'],'group':r.get('group',''),'major':r.get('requirement','')if key=='group'else r.get('major',''),'major_code':r.get('major_code',''),'rank':v['rank'],'plan':v['plan'] if v['plan']is not None else'','score':v['score'] if v['score']is not None else'','year':year,'batch':r['batch'],'plan_type':r.get('plan_type','未标'),'requirement':r.get('requirement',''),'source_grade':weakest,'source_id':'｜'.join(sources),'value_status':dump({field:p[field].get('value_status')for field in FIELDS}),'data_provenance':dump(p)})
        counts[str(year)]=len(ys);paths[str(year)]=str(path.resolve())
    with (out/'conflicts.csv').open('w',newline='',encoding='utf-8')as f:
        writer=csv.DictWriter(f,fieldnames=CONFLICT_FIELDS);writer.writeheader();writer.writerows(conflicts)
    metadata={'status':'ok' if all(counts.values()) else 'partial' if any(counts.values()) else 'missing_data','province':province,'subject':subject,'years':years,'key':key,'batch_filter':batch,'plan_type_filter':plan_type,'input_records':len(records),'exported_rows':counts,'files':paths,'conflict_count':len(conflicts),'conflicts_file':str((out/'conflicts.csv').resolve()),'rejected':rejected,'yfyd':yfyd_metadata or [],'rank_conversion_performed':False,'rules':['官方同事实同口径逐值优先，第三方补缺','rank_vs_yfyd不等同官方投档核对','缺位次不从分数推造','专业组跨年仍须pool --group-map核实'],'database_written':False}
    (out/'export-metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    return metadata


def export_yfyd(rows_by_year, province, subject, years, *, out, sources, coverage, metadata):
    """Keep every original CDF row, plus a cumulative-only rank.Table input."""
    columns=['province','year','subject','score','count','cum','score_operator','source_operator','source_head_unknown','score_label','count_raw','count_kind','grade','source_grade','display_grade','source_id','value_status','src_row','src_page','src_table','locator_method','locator_status','locator','completeness','data_provenance','source']
    files={};usable_files={};counts={};usable_counts={};omitted={};out=Path(out)
    targets=[out/f'{province}-{subject}-{year}-yfyd-{kind}.csv'for year in years for kind in ('all','usable')]
    if any(p.exists()for p in targets):raise ValueError('一分一段目标已存在，不能覆盖')
    labels=collections.defaultdict(list)
    for item in metadata:
        bucket=item.get('aggregate_bucket')
        if bucket:labels[(item['year'],bucket['source_id'],bucket['score_boundary'])].append(bucket['score_label'])
    for year in years:
        raw=rows_by_year.get(year,[]);heads={};prepared=[]
        usable=[r for r in raw if r.get('cum') is not None and r.get('score') is not None]
        for row in usable:
            sid=row['source_id']
            if sid not in heads:
                ordinary=str(row.get('score_operator')or'=').strip()in('','=', '＝')
                heads[sid]=not ordinary or row.get('count')is None
        for row in raw:
            sid=row['source_id'];source=sources.get(sid,{})
            if source.get('source_id')!=sid or source.get('grade')!='官方':raise ValueError('一分一段缺真实官方来源登记：'+str(sid))
            scope={'province':province,'year':year,'subject':subject,'scope_raw':row.get('_scope_raw')or''}
            locator={k:row.get(k)for k in ('src','src_row','src_page','src_table','locator_method','locator_status')if row.get(k)not in(None,'')}
            complete=coverage.get(sid);scope['completeness']=complete
            operator=row.get('score_operator')or'='
            count=row.get('count')if str(operator).strip()in('','=', '＝')else None
            states=obj(row.get('value_status'));context_states=obj(row.get('_count_status'));current=row.get('_current_states',{});evidence=row.get('_field_evidence',{})
            raw_count=row.get('_count_raw');kind=row.get('_count_kind')or''
            values={'score':row.get('score'),'cum':row.get('cum'),'count':count,'count_raw':raw_count};provenance={}
            for field,value in values.items():
                original_field='segment_n'if field=='count'else field
                original=context_states.get(original_field)if field in('count','count_raw')else states.get(field)
                state=current.get(original_field)or original
                proof=evidence.get(original_field)if value is not None else None
                active_locator=proof['locator']if proof else locator
                if field=='count'and value is None:state=original if isinstance(original,dict)and original.get('status')=='原件缺失'else {'status':'来源未提供','reason':'没有可导出的可信原单分人数；原口径/原状态另保留，不填推算或合并档人数'}
                provenance[field]=_meta(scope,field,value,source,state,active_locator)
                provenance[field].update(original_value_status=original,original_locator=locator,original_source_metadata={k:source.get(k)for k in('source_id','grade','publisher','title','landing_url','file_url','archive_sha256','archive_status','published','retrieved')},source_assets=row.get('_source_assets',[]),evidence_refs=row.get('_evidence_refs',[]))
                if proof:
                    provenance[field].update(current_evidence=proof,archive_sha256=proof['locator']['sha256'],url=proof['source_asset'].get('url')or provenance[field]['url'])
                else:provenance[field]['archive_sha256']=source.get('archive_sha256','')
            provenance['count']['count_gate']='仅保留可信原单分人数；合并档、累计人数、推算值不填count'
            provenance['count']['original_context_value_status']=context_states.get('segment_n')
            bucket_labels=labels.get((year,sid,row.get('score')),[])
            score_label=bucket_labels[0]if len(bucket_labels)==1 else ''
            predicted=any(isinstance(v,dict)and v.get('status')=='推算'for v in states.values())
            data={'province':province,'year':year,'subject':subject,'score':row.get('score'),'count':count,'cum':row.get('cum'),'score_operator':operator,'source_operator':row.get('score_operator')or'=', 'source_head_unknown':int(heads.get(sid,True)), 'score_label':score_label,'count_raw':raw_count,'count_kind':kind,'grade':'官方','source_grade':'官方','display_grade':'官方','source_id':sid,'value_status':dump({field:p['value_status']for field,p in provenance.items()}),'src_row':row.get('src_row'),'src_page':row.get('src_page'),'src_table':row.get('src_table'),'locator_method':row.get('locator_method'),'locator_status':row.get('locator_status'),'locator':dump(locator),'completeness':dump(complete),'data_provenance':dump(provenance),'source':'插值/推算，非原表行'if predicted else sid}
            active=provenance['cum'].get('current_evidence')
            if active:
                loc=active['locator'];data.update(locator=dump(loc),src_row=loc.get('row',row.get('src_row')),src_page=loc.get('page',row.get('src_page')),src_table=loc.get('table',loc.get('sheet',row.get('src_table'))),locator_method='新增root逐值原件审计',locator_status='原登记另见各值original_locator/source_metadata')
            prepared.append(data)
        all_path=out/f'{province}-{subject}-{year}-yfyd-all.csv';usable_path=out/f'{province}-{subject}-{year}-yfyd-usable.csv'
        valid=[row for row in prepared if row['cum']is not None and row['score']is not None]
        for path,subset in ((all_path,prepared),(usable_path,valid)):
            with path.open('w',newline='',encoding='utf-8')as f:
                writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows({k:''if r.get(k)is None else r.get(k,'')for k in columns}for r in subset)
        files[str(year)]=str(all_path.resolve());usable_files[str(year)]=str(usable_path.resolve());counts[str(year)]=len(prepared);usable_counts[str(year)]=len(valid)
        omitted[str(year)]=[{'source_id':r['source_id'],'score':r.get('score'),'src_row':r.get('src_row'),'reason':'原累计或分数为空，仅保留all，不由本段人数补累计'}for r in prepared if r['cum']is None or r['score']is None]
    return {'yfyd_files':files,'yfyd_usable_files':usable_files,'yfyd_exported_rows':counts,'yfyd_usable_rows':usable_counts,'yfyd_omitted_from_usable':omitted,'yfyd_rank_conversion_performed':False,'yfyd_subject_exact':subject,'yfyd_school_filter_applied':False}


# Independent reference exports: never volunteer candidates and never rank inputs.
_AUX_PLAN_FIELDS = ['record_id','province','year','subject','institution_id','school_raw','school_code','group_code','major_code','major_name','batch','plan_type','plan_n','gender','subject_requirements','scope_raw','src_row','src_page','src_table','locator_method']
_AUX_BATCH_FIELDS = ['record_id','province','year','subject','education_level','line_scope','total','requirements_json','src_row','src_page','src_table','locator_method']
_AUX_METADATA_FIELDS = ['source_grade','source_id','value_status','data_provenance','completeness']


def _aux_rows(c, sql, params=()):
    cursor = c.execute(sql, params)
    names = [x[0] for x in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _aux_table(c, name, schemas=('data','main')):
    available = {r[1] for r in c.execute('PRAGMA database_list')}
    for schema in schemas:
        if schema in available and c.execute('SELECT 1 FROM '+schema+'.sqlite_master WHERE name=? AND type IN (\'table\',\'view\')', (name,)).fetchone():
            return schema+'.'+name
    return None


def _aux_list(value):
    if isinstance(value, dict): return [value]
    if isinstance(value, list) and all(isinstance(x, dict) for x in value): return value
    return []


def _aux_same_value(after, value):
    if isinstance(value, bool) or isinstance(after, bool): return False
    if isinstance(value, (int,float)) and isinstance(after, (int,float)):
        return math.isfinite(value) and math.isfinite(after) and value == after
    return type(value) is type(after) and value == after


def collect_auxiliary(c, tables, province, subject, years, schools=None, batch=None,
                      plan_type=None, completeness=None):
    """Read exact-scope official-plan/control reference rows, without changing the DB.

    `completeness` may be a mapping keyed by (source_id, table) / source_id, or
    a callback receiving the unmodified row plus `_table`. Correction evidence
    is consulted only for rows declaring a correction or an artificial change.
    """
    result = {'plans':[], 'batch_lines':[], 'rejected':[], 'sources':{}}
    source_table = _aux_table(c, 'source')
    audit_table = _aux_table(c, 'gk_official_original_evidence', ('audit','main','data'))
    source_cache = result['sources']
    years = sorted(set(map(int, years)))
    if not years: return result
    def source(sid):
        if sid not in source_cache:
            found = _aux_rows(c, 'SELECT * FROM '+source_table+' WHERE source_id=?', (sid,)) if source_table and sid else []
            source_cache[sid] = dict(found[0], _registered=True) if len(found)==1 else {'source_id':sid,'grade':'未登记','_registered':False}
        return source_cache[sid]
    def reject(row, table, reason):
        result['rejected'].append({'record_id':row.get('record_id'), 'table':table, 'source_id':row.get('source_id'), 'reason':reason})
    def field_value(row, scope, field):
        if field.startswith('scope_raw.'):
            return scope.get(field.split('.',1)[1])
        return row.get(field)
    def corrected(row, scope, metas, original_source, original_locator):
        declared = _aux_list(scope.get('更正依据'))
        changed = obj(row.get('value_status')).get('plan_n',{}).get('status')=='人工更正'
        if not declared and not changed: return None
        if not audit_table: return '更正链缺少原格审计表'
        evidence = _aux_rows(c, 'SELECT * FROM '+audit_table+' WHERE record_id=? AND table_name=? AND source_id=?', (row['record_id'],'gk_official_plan',row['source_id']))
        if len(evidence)!=1: return '更正链原业务记录/本源审计不唯一或缺失'
        evidence = obj(evidence[0].get('excerpt_locator_json'))
        review = evidence.get('review',{})
        if (evidence.get('business_key')!={'record_id':row['record_id']}
                or review.get('status')!='approved' or review.get('approved_by')!='root'
                or not original_source.get('archive_sha256')
                or evidence.get('locator',{}).get('sha256')!=original_source['archive_sha256']):
            return '更正链原业务键/root复核/原书指纹未闭合'
        cells = _aux_list(evidence.get('excerpt',{}).get('更正原格'))
        grouped = collections.defaultdict(list)
        for cell in cells:
            if not isinstance(cell.get('field'),str): return '更正原格字段类型无效'
            grouped[cell['field']].append(cell)
        if any(not isinstance(x.get('field'),str) for x in declared): return '更正范围字段类型无效'
        expected = {x['field'] for x in declared}
        if changed: expected.add('plan_n')
        if None in expected or not expected: return '更正字段声明缺失'
        # Extra evidence is not silently applied to another field or another number.
        if set(grouped)!=expected: return '更正字段声明与原格证据集合不一致'
        for field in sorted(expected):
            if field not in row and not (field.startswith('scope_raw.') and field.split('.',1)[1] in scope): return '更正指向未登记字段：'+field
            if len(grouped[field])!=1: return '更正字段不唯一：'+str(field)
            cell = grouped[field][0]; value = field_value(row,scope,field)
            # Some source annotations explicitly retain both changed phrase and full
            # before/after cells. Use that full cell only for an exact scope text field;
            # never reconstruct text or use it to coerce a numeric/code correction.
            after = cell.get('after_full_raw') if field.startswith('scope_raw.') and 'after_full_raw' in cell else cell.get('after')
            if 'after' not in cell or not _aux_same_value(after,value): return '更正后值与当前字段不同：'+str(field)
            declarations = [x for x in declared if x.get('field')==field]
            if len(declarations)>1: return '更正范围字段重复：'+str(field)
            if declarations:
                declaration = declarations[0]
                declared_after = declaration.get('更正后',declaration.get('现行值',declaration.get('after')))
                if declaration.get('source_id')!=cell.get('source_id') or not _aux_same_value(declared_after,value):
                    return 'scope更正来源/现行值与审计不一致：'+str(field)
            actual = source(cell.get('source_id'))
            loc = cell.get('locator')
            if (not actual.get('_registered') or actual.get('grade') not in ('官方','第三方整理')
                    or not cell.get('sha256') or actual.get('archive_sha256')!=cell['sha256']
                    or not isinstance(loc,dict) or loc.get('table') is None or loc.get('row') is None):
                return '更正来源登记/指纹/原页表行缺失：'+str(field)
            before = cell.get('before_full_raw') if field.startswith('scope_raw.') and 'before_full_raw' in cell else cell.get('before')
            original = _meta(row,field,before,original_source,{'status':'官方原值' if original_source['grade']=='官方' else '第三方整理未核','reason':'更正前原书原值；不冒充现行值'},original_locator)
            locator = dict(loc,sha256=cell['sha256'])
            meta = _meta(row,field,value,actual,{'status':'人工更正','reason':'来源方更正原格与当前字段逐值一致'},locator)
            meta['original_provenance'] = original
            meta['correction_evidence'] = {'record_id':row['record_id'],'field':field,'before':before,'after':value,'source_id':actual['source_id'],'sha256':cell['sha256'],'locator':locator,'review':review}
            metas[field] = meta
        return None
    wanted = set(schools or []) if not isinstance(schools,str) else {schools}
    for table, bucket in [('gk_official_plan','plans'),('gk_batch_line','batch_lines')]:
        if table not in tables and not any(str(x).endswith('.'+table) for x in tables): continue
        qualified = _aux_table(c, table)
        if not qualified: continue
        sql = 'SELECT * FROM '+qualified+' WHERE province=? AND subject=? AND year IN ('+','.join('?' for _ in years)+')'
        for raw in _aux_rows(c,sql,[province,subject,*years]):
            if table=='gk_official_plan':
                if wanted and not wanted.intersection({raw.get('institution_id'),raw.get('school_raw'),raw.get('school_code')}): continue
                if batch is not None and raw.get('batch')!=batch: continue
                if plan_type is not None and raw.get('plan_type')!=plan_type: continue
            src = source(raw.get('source_id'))
            if not src.get('_registered') or src.get('grade') not in ('官方','第三方整理'):
                reject(raw,table,'缺少真实来源登记或不支持来源等级'); continue
            row = dict(raw)
            # Preserve raw local codes, NULL and literal withdrawal zero without conversion.
            row.update(code=raw.get('school_code'),name=raw.get('school_raw'),group=raw.get('group_code'),major=raw.get('major_name'),requirement=raw.get('subject_requirements'))
            row['_table'] = table
            row['completeness'] = completeness(row) if callable(completeness) else (completeness or {}).get((raw['source_id'],table),(completeness or {}).get(raw['source_id']))
            scope = obj(raw.get('scope_raw'))
            original_scope = dict(raw)
            row['original_scope'] = original_scope
            loc = {k:raw.get(k) for k in ('src_row','src_page','src_table','locator_method')}
            loc['sha256'] = src.get('archive_sha256','')
            state = obj(raw.get('value_status'))
            field = 'plan_n' if table=='gk_official_plan' else 'total'
            fields = [field]+(['school_code','group_code','major_code','major_name','subject_requirements'] if table=='gk_official_plan' else [])
            metas = {f:_meta(row,f,raw.get(f),src,state.get(f),loc) for f in fields}
            if table=='gk_official_plan':
                error = corrected(row,scope,metas,src,loc)
                if error: reject(raw,table,error); continue
            for m in metas.values():
                if m['grade']=='第三方整理':
                    m['cross_check_summary']={'scope':'本辅助数据逐值同口径核对','checked':0,'inconsistent':0,'note':'第三方整理·内部未核；不借其他范围检查提升等级'}
            primary = metas[field]
            output = {k:raw.get(k) for k in (_AUX_PLAN_FIELDS if table=='gk_official_plan' else _AUX_BATCH_FIELDS)}
            if primary.get('correction_evidence'):
                actual_loc = primary['locator']
                output.update(src_row=str(actual_loc['row']), src_page=actual_loc.get('page'),
                              src_table=str(actual_loc['table']), locator_method='来源方更正原格；原书定位见original_provenance')
            output.update(source_id=primary['source_id'], source_grade=('第三方整理·内部未核' if any(m['grade']=='第三方整理' for m in metas.values()) else '官方'), value_status={f:m['value_status'] for f,m in metas.items()}, data_provenance=metas, completeness=row['completeness'])
            result[bucket].append(output)
    return result


def export_auxiliary(collected, province, subject, years, *, out):
    """Write separate references, checking every destination before any write."""
    out = Path(out)
    years = sorted(set(map(int,years)))
    targets = {(kind,year):out/(f'{province}-{subject}-{year}-'+suffix+'.csv')
               for kind,suffix in [('plans','plans'),('batch_lines','batch-lines')] for year in years}
    for path in targets.values():
        if path.exists(): raise FileExistsError('辅助导出目标已存在：'+str(path))
    out.mkdir(parents=True,exist_ok=True)
    result = {'plan_files':{},'batch_line_files':{},'plan_exported_rows':{},'batch_line_exported_rows':{},'rejected':collected.get('rejected',[]),'sources':collected.get('sources',{}),'volunteer_candidates_added':0,'rank_conversion_performed':False}
    for (kind,year),path in targets.items():
        fields = (_AUX_PLAN_FIELDS if kind=='plans' else _AUX_BATCH_FIELDS)+_AUX_METADATA_FIELDS
        rows = [r for r in collected.get(kind,[]) if int(r['year'])==year]
        with path.open('x',newline='',encoding='utf-8') as f:
            writer = csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            for row in rows:
                writer.writerow({k:dump(row.get(k)) if isinstance(row.get(k),(dict,list)) else row.get(k) for k in fields})
        prefix = 'plan' if kind=='plans' else 'batch_line'
        result[prefix+'_files'][year] = str(path)
        result[prefix+'_exported_rows'][year] = len(rows)
    return result
