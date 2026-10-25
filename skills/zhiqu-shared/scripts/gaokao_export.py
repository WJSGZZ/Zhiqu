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
