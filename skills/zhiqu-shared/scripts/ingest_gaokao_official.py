#!/usr/bin/env python3
"""Insert reviewed anonymous gaokao tables into a paired candidate only."""
import argparse, collections, copy, hashlib, json, math, re, sqlite3
from pathlib import Path
from ingest_kaoyan_lines import SOURCE, candidate_path, dump, number, privacy as base_privacy, validate_source

YFYD='province year subject score cum src source_id src_row src_page src_table locator_method locator_status value_status'.split()
CUTOFF='province year subject code name grp major_code major plan admit score rank src source_id institution_id plan_type src_row src_page src_table locator_method locator_status value_status'.split()
BATCH='record_id province year subject education_level line_scope total requirements_json source_id src_row src_page src_table locator_method value_status'.split()
PLAN='record_id province year subject batch school_raw institution_id school_code group_code major_code major_name plan_n gender subject_requirements plan_type scope_raw source_id src_row src_page src_table locator_method value_status'.split()
BUCKET='record_id province year subject score_label score_boundary boundary_operator cum segment_n scope_raw source_id src_row src_page src_table locator_method value_status'.split()
FIELDS={'gk_yfyd_bucket':BUCKET,'gk_official_yfyd':YFYD,'gk_official_cutoff':CUTOFF,'gk_batch_line':BATCH,'gk_official_plan':PLAN}
NUMERIC={'gk_yfyd_bucket':('year','score_boundary','cum','segment_n','src_page'),'gk_official_yfyd':('year','score','cum','src_page'),'gk_official_cutoff':('year','plan','admit','score','rank','src_page'),'gk_batch_line':('year','total','src_page'),'gk_official_plan':('year','plan_n','src_page')}
VALUE_FIELDS={'gk_yfyd_bucket':('score_boundary','cum','segment_n'),'gk_official_yfyd':('score','cum'),'gk_official_cutoff':('plan','admit','score','rank'),'gk_batch_line':('total',),'gk_official_plan':('plan_n',)}
STATUSES={'官方原值','人工更正','推算','第三方整理未核','第三方已核一致','未公布','人数太少未公布','来源未提供','原件缺失'}
DDL={
 'gk_yfyd_bucket':'CREATE TABLE gk_yfyd_bucket(record_id TEXT PRIMARY KEY,province TEXT NOT NULL,year INTEGER NOT NULL,subject TEXT NOT NULL,score_label TEXT NOT NULL,score_boundary INTEGER NOT NULL CHECK(score_boundary>=0),boundary_operator TEXT NOT NULL,cum INTEGER CHECK(cum>=0),segment_n INTEGER CHECK(segment_n>=0),scope_raw TEXT NOT NULL,source_id TEXT NOT NULL REFERENCES source(source_id),src_row TEXT,src_page INTEGER,src_table TEXT,locator_method TEXT,value_status TEXT NOT NULL)',
 'gk_yfyd_context':'CREATE TABLE gk_yfyd_context(province TEXT NOT NULL,year INTEGER NOT NULL,subject TEXT NOT NULL,score INTEGER NOT NULL,segment_n INTEGER,score_operator TEXT,score_upper INTEGER,scope_raw TEXT,count_raw INTEGER,count_kind TEXT,cumulative_pct REAL,value_status TEXT NOT NULL,source_id TEXT NOT NULL REFERENCES source(source_id),PRIMARY KEY(province,year,subject,score),FOREIGN KEY(province,year,subject,score) REFERENCES gk_official_yfyd(province,year,subject,score))',
 'gk_batch_line':'CREATE TABLE gk_batch_line(record_id TEXT PRIMARY KEY,province TEXT NOT NULL,year INTEGER NOT NULL,subject TEXT NOT NULL,education_level TEXT,line_scope TEXT,total REAL,requirements_json TEXT,source_id TEXT NOT NULL REFERENCES source(source_id),src_row TEXT,src_page INTEGER,src_table TEXT,locator_method TEXT,value_status TEXT NOT NULL)',
 'gk_official_plan':'CREATE TABLE gk_official_plan(record_id TEXT PRIMARY KEY,province TEXT NOT NULL,year INTEGER NOT NULL,subject TEXT NOT NULL,batch TEXT,school_raw TEXT,institution_id TEXT REFERENCES institution(institution_id),school_code TEXT,group_code TEXT,major_code TEXT,major_name TEXT,plan_n INTEGER,gender TEXT,subject_requirements TEXT,plan_type TEXT,scope_raw TEXT,source_id TEXT NOT NULL REFERENCES source(source_id),src_row TEXT,src_page INTEGER,src_table TEXT,locator_method TEXT,value_status TEXT NOT NULL)',
 'gk_official_original_evidence':'CREATE TABLE audit.gk_official_original_evidence(record_id TEXT PRIMARY KEY,table_name TEXT NOT NULL,source_id TEXT NOT NULL,excerpt_locator_json TEXT NOT NULL)',
}

def privacy(value):
 base_privacy(value)
 def check(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if re.search(r'(^|_)(contact|contact_name|phone|telephone|email)($|_)|联系人|联系方式|联系电话|邮箱|手机号',str(k),re.I):raise ValueError('禁止个人联系字段')
    check(x)
  elif isinstance(v,list):
   for x in v:check(x)
 check(value)

def exact(c,table,data,key,schema='main'):
 name='"'+schema+'"."'+table+'"'
 old=c.execute('SELECT '+','.join('"'+k+'"' for k in data)+' FROM '+name+' WHERE '+' AND '.join('"'+k+'" IS ?' for k in key),[data[k] for k in key]).fetchall()
 if old:
  if any(tuple(r)!=tuple(data.values()) for r in old):raise ValueError('已有记录冲突:'+table)
  return False
 c.execute('INSERT INTO '+name+' ('+','.join('"'+k+'"' for k in data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values()));return True

def integer(value,field,required=False):
 n=number(value,field)
 if n is None:
  if required:raise ValueError('缺少数字:'+field)
  return None
 if not float(n).is_integer():raise ValueError('必须为非负整数:'+field)
 return int(n)

def object_json(v,label):
 if isinstance(v,str):
  try:v=json.loads(v)
  except (ValueError,TypeError):raise ValueError(label+'不是JSON对象')
 if not isinstance(v,dict):raise ValueError(label+'必须为对象')
 def finite_numbers(x):
  if isinstance(x,dict):
   for z in x.values():finite_numbers(z)
  elif isinstance(x,list):
   for z in x:finite_numbers(z)
  elif isinstance(x,(int,float)) and not isinstance(x,bool) and (not math.isfinite(x) or x<0):raise ValueError(label+'含非法数字')
 finite_numbers(v)
 return v

def state_json(v,fields):
 statuses=object_json(v,'value_status')
 if not set(fields)<=set(statuses):raise ValueError('value_status缺少数值字段明确状态')
 if set(statuses)-set(fields)-{'year','src_page','segment_n','score_upper','count_raw','cumulative_pct'}:raise ValueError('value_status未知数值字段')
 for k,s in statuses.items():
  if not isinstance(s,dict) or s.get('status') not in STATUSES or not str(s.get('reason') or '').strip():raise ValueError('value_status须有明确status与reason')
 return dump(statuses)

def validate_numeric_coverage(review):
 """Check declared original-region coverage; equality of extracted grids alone is insufficient."""
 pages=review.get('numeric_coverage')
 if pages is None:return
 if not isinstance(pages,list) or not pages:raise ValueError('原页数字归属证明不能为空')
 fields={'page','a_observed','b_observed','a_assigned','b_assigned','a_unassigned','b_unassigned','a_multiset_equal','b_multiset_equal'}
 seen=set();total=0
 for page in pages:
  if not isinstance(page,dict) or set(page)!=fields:raise ValueError('原页数字归属字段不完整')
  numbers=fields-{'a_multiset_equal','b_multiset_equal'}
  if any(type(page[k]) is not int or page[k]<0 for k in numbers):raise ValueError('原页数字归属计数须为非负整数')
  if page['page']<1 or page['page'] in seen:raise ValueError('原页数字归属页码重复或无效')
  seen.add(page['page']);total+=page['a_observed']
  if page['a_multiset_equal'] is not True or page['b_multiset_equal'] is not True or page['a_unassigned'] or page['b_unassigned'] or len({page[k] for k in ('a_observed','b_observed','a_assigned','b_assigned')})!=1:
   raise ValueError('原页数字未全部归属；两读相同也不能放行漏行')
 if not total:raise ValueError('原页数字归属证明没有数值，不能证明数值表完整')


def image_row_key(locator,digest):
 if not isinstance(locator,dict) or locator.get('sha256')!=digest:raise ValueError('图片排除行原件指纹不符')
 if any(type(locator.get(k)) is not int or locator[k]<1 for k in ('page','table','row')):raise ValueError('图片排除行须有真实正整数页表行')
 return tuple(locator[k] for k in ('page','table','row'))

def excluded_image_rows(review,digest):
 excluded=review.get('excluded_rows',[])
 if not isinstance(excluded,list):raise ValueError('图片排除行须为清单')
 if excluded and (review.get('read_method')!='image' or review.get('dual_read_equal') is not True):raise ValueError('排除行仅用于其余图片行两读一致的明确子集')
 keys=set()
 for row in excluded:
  if not isinstance(row,dict) or set(row)!={'locator','reason'} or not isinstance(row['reason'],str) or not row['reason'].strip():raise ValueError('图片排除行须有定位和明确原因')
  key=image_row_key(row['locator'],digest)
  if key in keys:raise ValueError('图片排除行重复')
  keys.add(key)
 return keys

def validate_reviews(manifest,sources):
 groups=collections.defaultdict(list);allids=set();datasets=manifest['datasets']
 for dataset in datasets:
  if not isinstance(dataset,dict) or set(dataset)-{'source_id','table','rows','review','format'}:raise ValueError('dataset字段白名单不符')
  sid=dataset.get('source_id');table=dataset.get('table');review=dataset.get('review',{});rows=dataset.get('rows')
  if table not in FIELDS:raise ValueError('不允许的业务表')
  if sid not in sources:raise ValueError('dataset缺少完整官方来源')
  if not isinstance(rows,list) or not rows:raise ValueError('dataset须有数据行')
  if not isinstance(review,dict) or review.get('status')!='approved':raise ValueError('dataset必须经主审批准')
  if review.get('read_method') not in {'text','image'}:raise ValueError('read_method须明确text/image')
  validate_numeric_coverage(review)
  excluded=excluded_image_rows(review,sources[sid]['archive_sha256'])
  expected={'original_data_rows':len(rows)+len(excluded),'extracted_rows':len(rows)}
  for k,n in expected.items():
   if type(review.get(k)) is not int or review[k]!=n:raise ValueError('原表数据行数/提取行数/清单行数不相符')
  if not isinstance(review.get('samples'),list):raise ValueError('须提供已批准抽样')
  for item in rows:
   if not isinstance(item,dict) or set(item)-{'record_id','data','scope','locator','excerpt','yfyd_context'}:raise ValueError('item字段白名单不符')
   rid=item.get('record_id')
   if not isinstance(rid,str) or not rid or rid in allids:raise ValueError('record_id须全局唯一')
   allids.add(rid)
   if not isinstance(item.get('scope'),dict) or not item.get('locator') or not isinstance(item.get('locator'),dict) or item.get('excerpt') in (None,'',{},[]):raise ValueError('每行须提供scope、真实locator及最小原格摘录')
   if item.get('locator',{}).get('sha256')!=sources[sid]['archive_sha256']:raise ValueError('行定位指纹与原件来源不符')
   if not isinstance(item.get('data'),dict):raise ValueError('data必须为对象')
  groups[sources[sid]['archive_sha256']].append(dataset)
 for digest,group in groups.items():
  excluded=set();accepted=set();partial=any(d['review'].get('excluded_rows') for d in group)
  if partial:
   for d in group:
    keys=excluded_image_rows(d['review'],digest)
    if excluded & keys:raise ValueError('同源分区排除行重复')
    excluded.update(keys)
    for row in d['rows']:
     key=image_row_key(row['locator'],digest)
     if key in accepted:raise ValueError('同源图片分区数据行重复')
     accepted.add(key)
   if excluded & accepted:raise ValueError('排除行同时出现在已批准数据中')
  declarations=[d['review'].get('original_source_rows') for d in group]
  if partial and any(v is None for v in declarations):raise ValueError('图片部分入库须声明原源总行数及分区')
  if any(v is not None for v in declarations):
   if any(not isinstance(v,int) or isinstance(v,bool) or v<=0 for v in declarations) or len(set(declarations))!=1:raise ValueError('同SHA原源总行数声明不一致')
   partitions=[d['review'].get('partition') for d in group]
   if any(not isinstance(p,str) or not p.strip() for p in partitions) or len(set(partitions))!=len(partitions):raise ValueError('同SHA须明确唯一partition')
   if sum(d['review']['original_data_rows'] for d in group)!=declarations[0]:raise ValueError('同SHA各partition合计与原源总行数不符')
  candidates={r['record_id']:r for d in group for r in d['rows']};n=len(candidates);sampleids=set();image=any(d['review']['read_method']=='image' for d in group)
  for d in group:
   for sample in d['review']['samples']:
    if not isinstance(sample,dict) or sample.get('status')!='approved':raise ValueError('抽样必须经批准')
    rid=sample.get('record_id')
    if rid not in candidates or not sample.get('locator') or dump(sample['locator'])!=dump(candidates[rid]['locator']):raise ValueError('抽样记录/原格定位未绑定候选')
    if sample.get('source_id',d['source_id']) not in {x['source_id'] for x in group}:raise ValueError('抽样来源不匹配')
    if sample.get('sha256',digest)!=digest:raise ValueError('抽样原件指纹不匹配')
    sampleids.add(rid)
  need=max(math.ceil(n*(.1 if image else .03)),min(5 if image else 3,n))
  if len(sampleids)<need:raise ValueError(('图片' if image else '文本')+'同SHA合并抽样不足')

def prepare_data(c,dataset,item):
 table=dataset['table'];fields=FIELDS[table];raw=item['data'];sid=dataset['source_id'];rid=item['record_id']
 if set(raw)-set(fields):raise ValueError('data字段白名单不符')
 if raw.get('source_id')!=sid:raise ValueError('data来源与dataset不符')
 if table in {'gk_batch_line','gk_official_plan','gk_yfyd_bucket'} and raw.get('record_id',rid)!=rid:raise ValueError('data与item记录ID不符')
 data={k:raw.get(k) for k in fields}
 if table in {'gk_batch_line','gk_official_plan','gk_yfyd_bucket'}:data['record_id']=rid
 for key in ('province','subject'):
  if not isinstance(data[key],str) or not data[key].strip():raise ValueError('缺少明确省份/科类')
 for key in NUMERIC[table]:
  if table=='gk_yfyd_bucket' and key=='score_boundary':
   value=number(data[key],key)
   if value is None:raise ValueError('缺少数字:score_boundary')
   if float(value).is_integer():data[key]=int(value)
   else:
    from decimal import Decimal
    literal=re.findall(r'(?<![\d.])\d+(?:\.\d+)?(?![\d.])',str(data.get('score_label') or ''))
    if not literal or Decimal(literal[0])!=Decimal(str(value)):raise ValueError('小数边界须与原分数标签逐值相同')
    data[key]=value
  elif table=='gk_official_yfyd' and key=='score':
   value=number(data[key],key)
   if value is None:raise ValueError('缺少数字:score')
   if float(value).is_integer():data[key]=int(value)
   else:
    context=item.get('yfyd_context')
    if not isinstance(context,dict) or not str(context.get('score_operator') or '').strip() or not str(context.get('scope_raw') or '').strip():raise ValueError('原表小数分必须保留分数口径与适用范围')
    # SQLite INTEGER affinity preserves a non-integral REAL without rounding;
    # keep existing integer keys and their storage types unchanged.
    data[key]=value
  else:
   data[key]=number(data[key],key) if key=='total' or table=='gk_official_cutoff' and key=='score' else integer(data[key],key,required=key=='year' or table=='gk_yfyd_bucket' and key=='score_boundary')
 if table=='gk_yfyd_bucket':
  for field in ('score_label','boundary_operator','scope_raw'):
   if not isinstance(data.get(field),str) or not data[field].strip():raise ValueError('尾桶须保留原词/范围:'+field)
 if data.get('src_page')==0:raise ValueError('物理页码须从1起')
 data['value_status']=state_json(raw.get('value_status'),VALUE_FIELDS[table])
 if 'requirements_json' in data:data['requirements_json']=dump(object_json(raw.get('requirements_json'),'requirements_json'))
 iid=data.get('institution_id')
 if iid not in ('',None) and not c.execute('SELECT 1 FROM institution WHERE institution_id=?',(iid,)).fetchone():raise ValueError('学校身份不存在，不猜挂接')
 # Preserve a short original position, not a whole source-row clone.
 if data.get('src_row') in ('',None) or not isinstance(data.get('src_row'),(str,int)) or isinstance(data.get('src_row'),bool) or len(str(data['src_row']))>512:raise ValueError('src_row必须为紧凑原表位置')
 data['src_row']=str(data['src_row'])
 if not isinstance(data.get('locator_method'),str) or not data['locator_method'].strip():raise ValueError('缺locator_method')
 if table in {'gk_official_yfyd','gk_official_cutoff'}:
  if not isinstance(data.get('src'),str) or not data['src'].strip():raise ValueError('src须为稳定来源位置键')
 if table=='gk_official_yfyd':key={k:data[k] for k in ('province','year','subject','score')}
 elif table=='gk_official_cutoff':key={'source_id':sid,'src':data['src']}
 else:key={'record_id':rid}
 return data,key

def ingest(database,manifest):
 path=candidate_path(database);privacy(manifest)
 if not isinstance(manifest,dict) or set(manifest)!={'sources','datasets'} or not isinstance(manifest['sources'],list) or not isinstance(manifest['datasets'],list):raise ValueError('manifest仅接受sources/datasets')
 sources={}
 for source in manifest['sources']:
  if not isinstance(source,dict) or set(source)!=set(SOURCE) or source.get('grade')!='官方':raise ValueError('必须提供官方来源原17列')
  if source['source_id'] in sources:raise ValueError('重复source_id')
  validate_source(source)
  if not re.fullmatch('[0-9a-f]{64}',source.get('archive_sha256') or ''):raise ValueError('须有原件SHA256')
  sources[source['source_id']]=source
 validate_reviews(manifest,sources)
 result={'tables':{},'inserted':0,'existing':0,'sources_inserted':0,'evidence_inserted':0,'context_inserted':0,'scope_inserted':0,'validated_business_links':[]}
 c=sqlite3.connect(path);c.execute('PRAGMA foreign_keys=ON')
 try:
  config=dict(c.execute('SELECT key,value FROM storage_manifest'));name=config.get('audit_file','')
  if not re.fullmatch(r'audit-[a-z0-9-]+\.sqlite',name):raise ValueError('缺少配对审计库')
  audit=path.parent/name
  if not audit.is_file() or audit.resolve().parent!=path.parent:raise ValueError('配对审计库路径无效')
  c.execute('ATTACH DATABASE ? AS audit',(str(audit),));generation=c.execute("SELECT value FROM audit.storage_manifest WHERE key='generation'").fetchone()
  if not generation or generation[0]!=config.get('generation'):raise ValueError('查询与审计库代号不一致')
  c.execute('BEGIN IMMEDIATE');creating={'active':True}
  allowed_main={'gk_yfyd_bucket','source','gk_official_yfyd','gk_official_cutoff','gk_yfyd_context','gk_batch_line','gk_official_plan','official_cutoff_scope','source_format_reference','storage_object','storage_moved','storage_external_fk'}
  def guard(action,a,b,db,trigger):
   if action in (sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):return sqlite3.SQLITE_OK if creating['active'] and a=='sqlite_master' and trigger is None else sqlite3.SQLITE_DENY
   if action==sqlite3.SQLITE_INSERT:
    if trigger is not None:return sqlite3.SQLITE_DENY
    if creating['active'] and a=='sqlite_master':return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_OK if (db=='main' and a in allowed_main) or (db=='audit' and a=='gk_official_original_evidence') else sqlite3.SQLITE_DENY
   if action==sqlite3.SQLITE_CREATE_TABLE:return sqlite3.SQLITE_OK if creating['active'] and a in DDL and db==('audit' if a=='gk_official_original_evidence' else 'main') else sqlite3.SQLITE_DENY
   if action in (sqlite3.SQLITE_CREATE_INDEX,):return sqlite3.SQLITE_OK if creating['active'] and b in DDL else sqlite3.SQLITE_DENY
   if action in (sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_DROP_INDEX,sqlite3.SQLITE_CREATE_TRIGGER,sqlite3.SQLITE_CREATE_VIEW,sqlite3.SQLITE_DROP_VIEW,sqlite3.SQLITE_DROP_TRIGGER,sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH):return sqlite3.SQLITE_DENY
   return sqlite3.SQLITE_OK
  c.set_authorizer(guard)
  for table,ddl in DDL.items():
   schema='audit' if table=='gk_official_original_evidence' else 'main'
   if not c.execute('SELECT 1 FROM '+schema+'.sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone():c.execute(ddl)
  creating['active']=False
  for table in DDL:
   schema='audit' if table=='gk_official_original_evidence' else 'main';definition=c.execute('SELECT sql FROM '+schema+'.sqlite_master WHERE name=?',(table,)).fetchone()[0]
   exact(c,'storage_object',{'name':table,'kind':'table','definition':definition},['name'])
  exact(c,'storage_moved',{'name':'gk_official_original_evidence'},['name'])
  exact(c,'storage_external_fk',{'owner':'audit','table_name':'gk_official_original_evidence','from_columns':dump(['source_id']),'parent_owner':'data','parent_table':'source','to_columns':dump(['source_id']),'id':0,'on_update':'NO ACTION','on_delete':'NO ACTION','match':'NONE'},['owner','table_name','id'])
  for source in sources.values():result['sources_inserted']+=exact(c,'source',{k:source[k] for k in SOURCE},['source_id'])
  cutoff_positions={}
  for dataset in manifest['datasets']:
   table=dataset['table'];sid=dataset['source_id'];fmt=dataset.get('format')
   if table=='gk_official_cutoff' and sid not in cutoff_positions:
    # One source scan per file; do not leave an ingestion-only index in the query store.
    fields=FIELDS[table];positions={}
    for prior in c.execute('SELECT rowid,'+','.join(fields)+' FROM gk_official_cutoff WHERE source_id=?',(sid,)):
     pos=prior[fields.index('src')+1]
     if pos in positions:raise ValueError('已有投档位置不唯一')
     positions[pos]=(prior[0],tuple(prior[1:]))
    cutoff_positions[sid]=positions
   if fmt is not None:
    if table!='gk_official_cutoff' or not isinstance(fmt,dict) or set(fmt)!={'provided_fields','scope_fields','excerpt','locator','scope_values'}:raise ValueError('仅cutoff允许完整原表format')
    if not isinstance(fmt['provided_fields'],list) or not all(isinstance(x,str) for x in fmt['provided_fields']) or not isinstance(fmt['scope_fields'],dict) or not isinstance(fmt['scope_values'],dict) or not isinstance(fmt['excerpt'],str) or not fmt['excerpt'].strip() or not isinstance(fmt['locator'],str) or not fmt['locator'].strip():raise ValueError('format字段类型或表头证据不完整')
    exact(c,'source_format_reference',{'source_id':sid,**{k:dump(fmt[k]) if k in {'provided_fields','scope_fields','scope_values'} else fmt[k] for k in ('provided_fields','scope_fields','excerpt','locator','scope_values')}},['source_id'])
   review_samples_sha256=hashlib.sha256(dump(dataset['review']['samples']).encode()).hexdigest()
   for item in dataset['rows']:
    data,key=prepare_data(c,dataset,item);rid=item['record_id'];cutoff_rowid=None
    if table=='gk_official_cutoff':
     prior=cutoff_positions[sid].get(data['src'])
     if prior:
      if prior[1]!=tuple(data.values()):raise ValueError('已有记录冲突:'+table)
      cutoff_rowid=prior[0];added=False
     else:
      cur=c.execute('INSERT INTO gk_official_cutoff ('+','.join(data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values()))
      cutoff_rowid=cur.lastrowid;cutoff_positions[sid][data['src']]=(cutoff_rowid,tuple(data.values()));added=True
    else:added=exact(c,table,data,list(key))
    result['inserted' if added else 'existing']+=1;result['tables'].setdefault(table,{'inserted':0,'existing':0})['inserted' if added else 'existing']+=1
    if table=='gk_official_cutoff':result['scope_inserted']+=exact(c,'official_cutoff_scope',{'source_id':sid,'public_record':data['src'],'scope_json':dump(item['scope']),'locator_json':dump({'record_id':rid,'audit_table':'gk_official_original_evidence'})},['source_id','public_record'])
    context=item.get('yfyd_context')
    if context is not None:
     if table!='gk_official_yfyd' or not isinstance(context,dict) or not {'segment_n','score_operator','score_upper','scope_raw'}<=set(context) or set(context)-{'segment_n','score_operator','score_upper','scope_raw','count_raw','count_kind','cumulative_pct','value_status'}:raise ValueError('yfyd_context字段白名单不符')
     if not isinstance(context['score_operator'],str) or not isinstance(context['scope_raw'],str):raise ValueError('yfyd_context口径须明确文本')
     if context.get('count_kind') is not None and not isinstance(context['count_kind'],str):raise ValueError('count_kind须明确文本')
     if context.get('count_raw') is not None and not str(context.get('count_kind') or '').strip():raise ValueError('原格人数须明确count_kind，未标口径不得猜累计')
     if context.get('count_kind')=='原表未标明人数口径':
      if data['cum'] is not None:raise ValueError('未标人数口径时cum须为空')
      if json.loads(data['value_status'])['cum']['status']!='来源未提供':raise ValueError('未标人数口径时cum状态须为来源未提供')
     ctx={**key,'count_raw':integer(context.get('count_raw'),'count_raw'),'count_kind':context.get('count_kind'),'segment_n':integer(context['segment_n'],'segment_n'),'score_operator':context['score_operator'],'score_upper':integer(context['score_upper'],'score_upper'),'scope_raw':context['scope_raw'],'source_id':sid}
     ctx['cumulative_pct']=number(context.get('cumulative_pct'),'cumulative_pct')
     explicit=context.get('value_status')
     context_status={f:{'status':'官方原值' if ctx[f] is not None else '来源未提供','reason':'审核清单中的原表实际数值' if ctx[f] is not None else '本原表未提供此项，不外推'} for f in ('segment_n','score_upper','count_raw','cumulative_pct')}
     if explicit is not None:
      supplied=object_json(explicit,'yfyd_context.value_status')
      if set(supplied)-set(context_status):raise ValueError('yfyd_context状态字段未知')
      context_status.update(supplied)
     ctx['value_status']=state_json(context_status,tuple(context_status))
     result['context_inserted']+=exact(c,'gk_yfyd_context',ctx,list(key))
    review_meta={k:v for k,v in dataset['review'].items() if k not in {'samples','numeric_coverage','excluded_rows'}}
    if dataset['review'].get('excluded_rows'):
     review_meta['excluded_row_count']=len(dataset['review']['excluded_rows'])
     review_meta['excluded_rows_sha256']=hashlib.sha256(dump(dataset['review']['excluded_rows']).encode()).hexdigest()
    if dataset['review'].get('numeric_coverage') is not None:
     # Keep the source-level proof once in the approved batch; bind each row by digest.
     review_meta['numeric_coverage_sha256']=hashlib.sha256(dump(dataset['review']['numeric_coverage']).encode()).hexdigest()
    evidence={'record_id':rid,'table_name':table,'source_id':sid,'excerpt_locator_json':dump({'business_key':key,'scope':item['scope'],'locator':item['locator'],'excerpt':item['excerpt'],'review':review_meta,'review_samples_sha256':review_samples_sha256})}
    result['evidence_inserted']+=exact(c,'gk_official_original_evidence',evidence,['record_id'],schema='audit')
    # Actually resolve each audit record to its exact business key before commit.
    e=c.execute('SELECT table_name,source_id,excerpt_locator_json FROM audit.gk_official_original_evidence WHERE record_id=?',(rid,)).fetchone()
    if not e or e[0]!=table or e[1]!=sid or json.loads(e[2])['business_key']!=key:raise ValueError('逐行审计绑定不一致')
    where=' AND '.join('"'+k+'" IS ?' for k in key);args=list(key.values())
    if cutoff_rowid is not None:where+=' AND rowid=?';args.append(cutoff_rowid)
    count=c.execute('SELECT count(*) FROM "'+table+'" WHERE '+where,args).fetchone()[0]
    if count!=1:raise ValueError('逐行业务联接悬空或不唯一')
    result['validated_business_links'].append({'record_id':rid,'table':table,'source_id':sid,'key':key,'matches':count})
  for table in ('gk_yfyd_bucket','gk_official_yfyd','gk_official_cutoff','gk_yfyd_context','gk_batch_line','gk_official_plan','official_cutoff_scope','source_format_reference'):
   if c.execute('PRAGMA foreign_key_check("'+table+'")').fetchone():raise ValueError('外键检查失败:'+table)
  c.commit();result.update(generation=config['generation'],audit_file=name,validated_business_link_count=len(result['validated_business_links']),manifest_content_sha256=hashlib.sha256(dump(manifest).encode()).hexdigest());return result
 except Exception:c.rollback();raise
 finally:c.close()

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--database',required=True);ap.add_argument('--manifest',required=True);ap.add_argument('--receipt',required=True);args=ap.parse_args();p=Path(args.manifest);result=ingest(args.database,json.loads(p.read_text()));result.update(database=str(Path(args.database).resolve()),manifest_sha256=hashlib.sha256(p.read_bytes()).hexdigest());Path(args.receipt).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(dump(result))
if __name__=='__main__':main()
