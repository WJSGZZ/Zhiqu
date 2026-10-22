#!/usr/bin/env python3
"""Insert explicitly reviewed official lines into an existing candidate only."""
import argparse, collections, copy, hashlib, json, math, re, sqlite3
from pathlib import Path
SOURCE='source_id grade publisher title landing_url file_url published retrieved method archive_sha256 archive_path archive_status wayback_url note citation license producer_revision'.split()
RAW='year school institution_id college program_code program_name degree_type study_mode line_scope total politics english math major1 major2 special_plan note read_method source_url published_date retrieved_date src_locator'.split()
NUM=['year','total','politics','english','math','major1','major2']
COMP={'single_100','single_150','single_over_100','single_gt100','single_le100','exam_1','exam_2','exam_3','exam_4',}
DDL='CREATE TABLE ky_line_component(record_id TEXT NOT NULL REFERENCES ky_retest_line(record_id),component TEXT NOT NULL,value REAL NOT NULL,source_id TEXT NOT NULL REFERENCES source(source_id),src_locator TEXT NOT NULL,value_status TEXT NOT NULL,PRIMARY KEY(record_id,component))'
SCOPE_DDL='CREATE TABLE ky_line_scope_context(record_id TEXT PRIMARY KEY REFERENCES ky_retest_line(record_id),direction TEXT,joint_program TEXT,admission_route TEXT,scope_raw TEXT,source_id TEXT NOT NULL REFERENCES source(source_id))'
AUDIT_DDL='CREATE TABLE ky_line_original_evidence(record_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,excerpt_locator_json TEXT NOT NULL)'
SCOPES=['direction','joint_program','admission_route','scope_raw']
def dump(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def privacy(v,key=''):
 if re.search(r'(^|_)(candidate_id|candidate_name|candidate_number|candidate_no|student_id|student_name|id_card|identity_number|姓名|考生姓名|考生编号|考生号|准考证号|身份证|身份证号)($|_)',key,re.I):raise ValueError('禁止个人身份字段')
 if isinstance(v,dict):
  for k,x in v.items():privacy(x,str(k))
 elif isinstance(v,list):
  for x in v:privacy(x,key)
 elif isinstance(v,str) and key not in {'landing_url','file_url','source_url','wayback_url','archive_path','archive_sha256','image_sha256','sha256'} and re.search(r'(?<![A-Za-z0-9])[0-9]{12,17}[0-9Xx](?![A-Za-z0-9])',re.sub(r'https?://[^\s，；|<>]+','[URL]',v)):raise ValueError('禁止疑似个人身份号码')
def validate_source(source):
 if not any(isinstance(source.get(k),str) and re.match(r'^https?://[^/\s]+',source[k]) for k in ('landing_url','file_url')):raise ValueError('官方来源至少须有公告页或附件URL')
 if source.get('archive_status') in {'已核后删除（有指纹）','已删除（有指纹，核对见记录）'}:
  if not re.fullmatch('[0-9a-f]{64}',source.get('archive_sha256') or '') or source.get('archive_path') not in ('',None):raise ValueError('删除状态须保留原件SHA256且路径为空')
def number(v,field):
 if v in (None,''):return None
 if isinstance(v,bool):raise ValueError('非法数字:'+field)
 if isinstance(v,str) and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',v):raise ValueError('非法数字:'+field)
 try:n=float(v)
 except (ValueError,TypeError):raise ValueError('非法数字:'+field)
 if not math.isfinite(n) or n<0:raise ValueError('非法数字:'+field)
 if field=='year' and not n.is_integer():raise ValueError('年份必须为整数')
 return int(n) if field=='year' else n
def insert_exact(c,table,data,key):
 old=c.execute('SELECT '+','.join('"'+x+'"' for x in data)+' FROM "'+table+'" WHERE '+ ' AND '.join('"'+k+'" IS ?' for k in key),[data[k] for k in key]).fetchone()
 if old is not None:
  if tuple(old)!=tuple(data.values()):raise ValueError('已有记录冲突:'+table)
  return False
 c.execute('INSERT INTO "'+table+'" ('+','.join('"'+x+'"' for x in data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values()));return True
def candidate_path(path):
 p=Path(path).resolve()
 if not p.is_file() or p.name in {'education.sqlite','employment.sqlite','purchased.sqlite','kaoyan.sqlite'} or 'snapshot' in p.parts or 'rollback' in p.parts:raise ValueError('只能写现有候选数据库')
 if not any(x in p.name.lower() for x in ('candidate','stage','test')):raise ValueError('候选文件名须含 candidate/stage/test')
 return p
def ingest(database,manifest):
 p=candidate_path(database);privacy(manifest)
 if set(manifest)-{'sources','rows'}:raise ValueError('manifest 顶层字段未知')
 rows=manifest.get('rows',[]);counts=collections.Counter((r.get('source_id'),r.get('review',{}).get('image_sha256')) for r in rows)
 c=sqlite3.connect(p);c.execute('PRAGMA foreign_keys=ON');result={'inserted':0,'existing':0,'components_inserted':0,'sources_inserted':0}
 try:
  config=dict(c.execute('SELECT key,value FROM storage_manifest'))
  filename=config.get('audit_file','')
  if not re.fullmatch(r'audit-[a-z0-9-]+\.sqlite',filename):raise ValueError('缺少配对审计库')
  audit=p.parent/filename
  if not audit.is_file() or audit.resolve().parent!=p.parent:raise ValueError('配对审计库路径无效')
  c.execute('ATTACH DATABASE ? AS audit',(str(audit),))
  generation=c.execute("SELECT value FROM audit.storage_manifest WHERE key='generation'").fetchone()
  if not generation or generation[0]!=config.get('generation'):raise ValueError('查询与审计库代号不一致')
  c.execute('BEGIN IMMEDIATE')
  allowed={'source','ky_retest_line','ky_retest_line_source','ky_line_component','ky_line_scope_context','storage_object','storage_external_fk','storage_moved','ky_line_original_evidence'}
  schema_creation={'active':True}
  def guard(action,a,b,db,trigger):
   if action in (sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
    return sqlite3.SQLITE_OK if schema_creation['active'] and a=='sqlite_master' else sqlite3.SQLITE_DENY
   if action==sqlite3.SQLITE_INSERT and (a not in allowed or (db=='audit' and a!='ky_line_original_evidence')):
    return sqlite3.SQLITE_OK if schema_creation['active'] and a=='sqlite_master' else sqlite3.SQLITE_DENY
   if action==sqlite3.SQLITE_CREATE_TABLE and a not in {'ky_line_component','ky_line_scope_context','ky_line_original_evidence'}:return sqlite3.SQLITE_DENY
   return sqlite3.SQLITE_OK
  c.set_authorizer(guard)
  for table,ddl in [('ky_line_component',DDL),('ky_line_scope_context',SCOPE_DDL)]:
   if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():c.execute(ddl)
  if not c.execute("SELECT 1 FROM audit.sqlite_master WHERE name='ky_line_original_evidence'").fetchone():c.execute(AUDIT_DDL.replace('CREATE TABLE ky_','CREATE TABLE audit.ky_',1))
  schema_creation['active']=False
  if c.execute("SELECT 1 FROM sqlite_master WHERE name='storage_object'").fetchone():
   for table in ('ky_line_component','ky_line_scope_context','ky_line_original_evidence'):
    schema='audit' if table=='ky_line_original_evidence' else 'main'
    insert_exact(c,'storage_object',{'name':table,'kind':'table','definition':c.execute('SELECT sql FROM '+schema+'.sqlite_master WHERE name=?',(table,)).fetchone()[0]},['name'])
   insert_exact(c,'storage_moved',{'name':'ky_line_original_evidence'},['name'])
   for idx,column,parent in [(0,'record_id','ky_retest_line'),(1,'source_id','source')]:
    insert_exact(c,'storage_external_fk',{'owner':'audit','table_name':'ky_line_original_evidence','from_columns':dump([column]),'parent_owner':'data','parent_table':parent,'to_columns':dump([column]),'id':idx,'on_update':'NO ACTION','on_delete':'NO ACTION','match':'NONE'},['owner','table_name','id'])
  for source in manifest.get('sources',[]):
   if set(source)!=set(SOURCE):raise ValueError('source 必须提供原17列，不猜日期')
   if source['grade']!='官方':raise ValueError('只接受官方来源')
   validate_source(source)
   result['sources_inserted']+=insert_exact(c,'source',{k:source[k] for k in SOURCE},['source_id'])
  for item in rows:
   raw=item['row'];review=copy.deepcopy(item.get('review',{}));status=review.get('status')
   if set(raw)-set(RAW):raise ValueError('原始行包含未知列')
   if status not in {'approved','已批准','核验通过'}:raise ValueError('行必须经主审批准')
   iid=item['institution_id'];school=raw.get('school');match=c.execute('SELECT name FROM institution WHERE institution_id=?',(iid,)).fetchone()
   if not match or match[0]!=school or raw.get('institution_id') not in (None,'',iid):raise ValueError('官方校名与身份未精确匹配')
   sid=item['source_id'];s=c.execute('SELECT grade,published,retrieved FROM source WHERE source_id=?',(sid,)).fetchone()
   if not s or s[0]!='官方':raise ValueError('缺少官方来源')
   is_image='读图' in str(raw.get('read_method','')) or 'image' in str(raw.get('read_method','')).lower()
   if is_image:
    image=review.get('image_sha256','');n=review.get('candidate_count',counts[(sid,image)]);samples=review.get('samples',[])
    for sample in samples if isinstance(samples,list) else []:
     if not isinstance(sample,dict):raise ValueError('读图样本必须为对象')
     if sample.get('source_id',sid)!=sid or sample.get('image_sha256',image)!=image:raise ValueError('读图样本来源或图指纹不匹配')
     sample.update(source_id=sid,image_sha256=image)
    approved_samples=[x for x in samples if isinstance(x,dict) and x.get('status') in {'approved','已批准','核验通过'}] if isinstance(samples,list) else []
    sample_keys=[dump(x.get('locator') or {k:x[k] for k in ('sample_id','record_id','src_row','src_page','src_table') if k in x}) for x in approved_samples]
    approved=len(set(sample_keys)) if all(k!='{}' for k in sample_keys) else 0
    if not re.fullmatch('[0-9a-f]{64}',image) or not isinstance(n,int) or isinstance(n,bool) or n<1 or n<counts[(sid,image)] or approved<max(math.ceil(n*.1),min(5,n)):raise ValueError('读图原件指纹或已批准抽样不足')
   data={k:raw.get(k) for k in RAW};data['institution_id']=iid
   # Staging dates are hints; only the independently checked source metadata is authoritative.
   data['published_date']=s[1] or None
   data['retrieved_date']=s[2] or None
   scope=item.get('scope_kind');original_scope=data.get('line_scope')
   if scope:data['line_scope']=scope
   if scope and original_scope!=scope:data['note']=(data.get('note') or '')+'；原scope='+str(original_scope or '')
   statuses={};field_status=item.get('field_status',{})
   if set(field_status)-set(NUM):raise ValueError('未知字段空值审核')
   for k in NUM:
    v=data[k]
    if k=='total' and isinstance(v,str) and v!='' and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',v):
     if re.fullmatch(r'[+\-]?[0-9.]+(?:[eE][+\-]?[0-9]+)?',v) or v.lower() in {'nan','inf','infinity'}:raise ValueError('非法数字:total')
     data['note']=(data.get('note') or '')+'；原total='+v;v=None
    data[k]=number(v,k)
    if k=='year' and data[k] is None:raise ValueError('年份缺失')
    if k=='total' and scope=='国家线适用规则' and data[k] is not None:raise ValueError('国家线适用规则禁止填数值total')
    explicit=field_status.get(k)
    if explicit is not None:
     if not isinstance(explicit,dict) or explicit.get('status') not in {'官方原值','人工更正','推算','第三方整理未核','第三方已核一致','未公布','人数太少未公布','来源未提供','原件缺失'} or not str(explicit.get('reason') or '').strip():raise ValueError('字段状态需明确status与reason')
     statuses[k]=explicit
    else:statuses[k]={'status':'官方原值' if data[k] is not None else '原件缺失','reason':'审核清单已批准' if data[k] is not None else '空值原文口径待核'}
   loc={k:item.get(k) for k in ['src_page','src_table','src_row','excerpt','locator']};loc['review']=review
   compact={k:item.get(k) for k in ('src_page','src_table','src_row')}
   compact.update(evidence_record_id=item['record_id'],audit_table='ky_line_original_evidence')
   if isinstance(item.get('locator'),dict):compact['sha256']=item['locator'].get('sha256')
   data.update(record_id=item['record_id'],source_id=sid,value_status=dump(statuses),quarantine_reason=None,verification_status='原文审核通过',excerpt_locator_json=dump(compact),original_row_json='{}')
   added=insert_exact(c,'ky_retest_line',data,['record_id']);result['inserted' if added else 'existing']+=1
   insert_exact(c,'ky_retest_line_source',{'record_id':item['record_id'],'source_id':sid,'role':'官方原文','locator_json':dump(compact)},['record_id','source_id'])
   evidence={'record_id':item['record_id'],'source_id':sid,'excerpt_locator_json':dump(loc)}
   existing=c.execute('SELECT record_id,source_id,excerpt_locator_json FROM audit.ky_line_original_evidence WHERE record_id=?',(item['record_id'],)).fetchone()
   if existing is not None and tuple(existing)!=tuple(evidence.values()):raise ValueError('已有记录冲突:ky_line_original_evidence')
   if existing is None:c.execute('INSERT INTO audit.ky_line_original_evidence VALUES(?,?,?)',tuple(evidence.values()))
   if 'scope_context' in item:
    context=item['scope_context']
    if not isinstance(context,dict) or set(context)-set(SCOPES):raise ValueError('scope_context 只接受四个文本字段')
    if any(not isinstance(v,str) for v in context.values()):raise ValueError('scope_context 必须为文本，未明确用空字符串')
    insert_exact(c,'ky_line_scope_context',{'record_id':item['record_id'],**{k:context.get(k,'') for k in SCOPES},'source_id':sid},['record_id'])
   for component,value in item.get('components',{}).items():
    if component not in COMP:raise ValueError('未知科目槽；不得强映射为政治')
    val=number(value,component)
    if val is None:continue
    result['components_inserted']+=insert_exact(c,'ky_line_component',{'record_id':item['record_id'],'component':component,'value':val,'source_id':sid,'src_locator':dump(compact),'value_status':dump({'value':{'status':'官方原值','method':review.get('method','')}})},['record_id','component'])
  # Old tables are immutable under the authorizer. Check the written tables here;
  # the release step validates both complete stores once.
  for table in ('ky_retest_line','ky_retest_line_source','ky_line_component','ky_line_scope_context'):
   if c.execute('PRAGMA foreign_key_check("'+table+'")').fetchone():raise ValueError('外键检查失败')
  c.commit();return result
 except Exception:c.rollback();raise
 finally:c.close()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--database',required=True);ap.add_argument('--manifest',required=True);ap.add_argument('--receipt',required=True);a=ap.parse_args()
 m=json.loads(Path(a.manifest).read_text());r=ingest(a.database,m);r.update(database=str(Path(a.database).resolve()),manifest_sha256=hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest());Path(a.receipt).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(dump(r))
if __name__=='__main__':main()
