#!/usr/bin/env python3
"""Preserve anonymous hand-off statistics in a candidate, quarantined until audited.

No individual scores, names or identifiers are accepted. A source fingerprint is
required, and a hand-off CSV position is never substituted for an original page.
"""
import argparse, json, sqlite3
from pathlib import Path
from ingest_kaoyan_lines import candidate_path, privacy, insert_exact, validate_source, SOURCE, dump, number
FIELDS={'record_id','institution_id','school','college','program_code','program_name','year','list_type','admission_route','special_plan','direction','joint_program','n','min','median','max','source_id','handoff_file','handoff_row','note'}
def ingest(database,manifest):
 p=candidate_path(database);privacy(manifest)
 if set(manifest)!={'sources','rows'}:raise ValueError('仅接受sources/rows匿名摘要')
 c=sqlite3.connect(p);c.execute('PRAGMA foreign_keys=ON');out={'inserted':0,'existing':0,'sources_inserted':0,'quarantined':0}
 try:
  c.execute('BEGIN IMMEDIATE')
  def guard(action,a,b,db,trigger):
   if action in (sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):return sqlite3.SQLITE_DENY
   if action==sqlite3.SQLITE_INSERT and a not in {'source','ky_score_dist'}:return sqlite3.SQLITE_DENY
   return sqlite3.SQLITE_OK
  c.set_authorizer(guard)
  for s in manifest['sources']:
   if set(s)!=set(SOURCE) or s.get('grade')!='官方':raise ValueError('必须为完整官方来源')
   validate_source(s)
   if not s.get('archive_sha256'):raise ValueError('必须有名单原件指纹，公告指纹不能代替')
   out['sources_inserted']+=insert_exact(c,'source',{k:s[k] for k in SOURCE},['source_id'])
  for r in manifest['rows']:
   if set(r)!=FIELDS:raise ValueError('摘要字段白名单不符')
   match=c.execute('SELECT name FROM institution WHERE institution_id=?',(r['institution_id'],)).fetchone()
   if not match or match[0]!=r['school']:raise ValueError('学校身份未精确匹配')
   if r['list_type'] not in ('复试','拟录取'):raise ValueError('名单类型未明确')
   values={k:number(r[k],k) for k in ('year','n','min','median','max')}
   if values['year'] is None or values['n'] is None or values['n']<1 or not values['n'].is_integer():raise ValueError('年份或n非法')
   if any(values[k] is None for k in ('min','median','max')) or not values['min']<=values['median']<=values['max']:raise ValueError('摘要次序非法')
   if not c.execute("SELECT 1 FROM source WHERE source_id=? AND grade='官方' AND length(archive_sha256)=64",(r['source_id'],)).fetchone():raise ValueError('缺名单原件来源')
   data={k:r[k] for k in ('record_id','institution_id','school','college','program_code','program_name','list_type','admission_route','special_plan','direction','joint_program','source_id')};data.update(values);data['n']=int(values['n'])
   data.update(scope='前序匿名汇总，原件已删除，本轮未重算',scope_raw=r['note'],scope_parse_status='待原件复核',src_row=None,src_page=None,src_table=None,input_file=r['handoff_file'],input_row=str(r['handoff_row']),quarantine_reason='匿名交接摘要缺原名单页表行及本轮重算证明；不进入可用视图',statistics_complete='仅n/min/median/max；q1/q3/mean未计算',scope_mismatch='待核',scope_mismatch_note='不得与资格线自动合并；复试与拟录取分开',locator_method='前序匿名摘要+原件收据SHA256；不是原件行定位',locator_status='原件定位未闭合',extra_json=dump({'handoff_note':r['note'],'independent_recalculation':False}))
   data['value_status']=dump({k:{'status':'官方原值' if k=='year' else '推算' if k in values else '原件缺失','reason':'原文年份的前序记录' if k=='year' else '前序匿名摘要聚合，未在本轮重算；核准前隔离' if k in values else '摘要未保留，原名单已删，本轮未计算'} for k in ('year','n','min','q1','median','q3','max','mean','excluded_count')})
   added=insert_exact(c,'ky_score_dist',data,['record_id']);out['inserted' if added else 'existing']+=1;out['quarantined']+=1
  if c.execute('PRAGMA foreign_key_check("ky_score_dist")').fetchone():raise ValueError('外键不通过')
  c.commit();return out
 except Exception:c.rollback();raise
 finally:c.close()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',required=True);p.add_argument('--manifest',required=True);p.add_argument('--receipt',required=True);a=p.parse_args();result=ingest(a.database,json.loads(Path(a.manifest).read_text()));Path(a.receipt).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(dump(result))
if __name__=='__main__':main()
