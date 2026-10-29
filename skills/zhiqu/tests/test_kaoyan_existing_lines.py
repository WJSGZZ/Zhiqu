"""Source-id reuse certifies a scoped old line, never overwrites its history."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'))
import kaoyan_existing_lines as v
from ingest_kaoyan_lines import SOURCE,RAW
from kaoyan_adapters import parse_official_html

class ExistingLineChecks(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.db=self.root/'education.stage.sqlite';self.audit=self.root/'audit-test.sqlite'
  self.identity={'name':'合成大学','institution_id':'4100000001'}
  body=('<html><meta charset="utf-8"><title>合成大学2026年硕士复试分数线</title><table><tr><th>类别</th><th>专业代码</th><th>专业名称</th><th>学院</th><th>复试分数线</th></tr>'+''.join('<tr><td>专业硕士(全日制)</td><td>'+code+'</td><td>会计</td><td>会计学院</td><td>220</td></tr>'for code in ['125300','125400','125500'])+'</table></html>').encode()
  self.body=body
  self.manifest=parse_official_html(body,'https://fixture.edu.cn/2026/line.html',self.identity,2026,'lines',['125300'])['manifest']
  source=copy.deepcopy(self.manifest['sources'][0]);source.update(source_id='old-source',retrieved='2026-10-20')
  self.oldrow=dict(self.manifest['rows'][0]['row'],record_id='old-row',source_id='old-source',line_scope='专业线',degree_type='专业',verification_status='未逐行核准',quarantine_reason=None)
  with sqlite3.connect(self.db)as c:
   c.execute('create table storage_manifest(key text,value text)');c.executemany('insert into storage_manifest values(?,?)',[('generation','test'),('audit_file',self.audit.name)])
   c.execute('create table source('+','.join(k+' TEXT'for k in SOURCE)+')');c.execute('insert into source values('+','.join('?'for _ in SOURCE)+')',[source[k]for k in SOURCE])
   columns=list(self.oldrow);c.execute('create table ky_retest_line('+','.join(k+(' REAL'if k in v.NUMBERS else ' INTEGER'if k=='year'else ' TEXT')for k in columns)+')');c.execute('insert into ky_retest_line values('+','.join('?'for _ in columns)+')',list(self.oldrow.values()))
  with sqlite3.connect(self.audit)as c:
   c.execute('create table storage_manifest(key text,value text)');c.execute('insert into storage_manifest values(?,?)',('generation','test'))
   c.execute('create table ky_check_sample(check_id integer primary key,table_name text,row_key text,field text,library_value text,official_value text,official_source_id text,status text,checked_date text,note text)')
 def prepare(self,m=None):
  with sqlite3.connect(self.db)as c:return v.prepare(c,m or self.manifest)
 def test_reuses_source_and_appends_idempotent_event_without_changing_old_values(self):
  m=self.prepare();self.assertEqual(m['sources'][0]['source_id'],'old-source');self.assertEqual(m['rows'][0]['record_id'],'old-row')
  with sqlite3.connect(self.db)as c:before=c.execute('select * from ky_retest_line').fetchall();sources=c.execute('select * from source').fetchall()
  self.assertEqual(v.ingest(self.db,m)['verification_events_inserted'],1);self.assertEqual(v.ingest(self.db,m)['verification_events_inserted'],0)
  with sqlite3.connect(self.db)as c:
   c.row_factory=sqlite3.Row;c.execute('attach database ? as audit',(str(self.audit),));self.assertEqual(v.verify(c,m),1);self.assertEqual([tuple(x)for x in c.execute('select * from ky_retest_line')],before);self.assertEqual([tuple(x)for x in c.execute('select * from source')],sources)
 def test_different_mode_program_year_college_or_score_is_not_same_fact(self):
  for field,value in [('study_mode','非全日制'),('program_code','125100'),('year',2025),('college','管理学院'),('total',219),('special_plan','士兵'),('degree_type','学术学位')]:
   m=copy.deepcopy(self.manifest);m['rows'][0]['row'][field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):self.prepare(m)
 def test_unknown_mode_extra_scope_and_components_fail_closed(self):
  for mutate in [lambda x:x['row'].update(study_mode=''),lambda x:x['scope_context'].update(direction='审计方向'),lambda x:x.update(components={'single_100':60})]:
   m=copy.deepcopy(self.manifest);mutate(m['rows'][0])
   with self.assertRaises(ValueError):self.prepare(m)
 def test_source_grade_or_duplicate_sha_never_certifies(self):
  with sqlite3.connect(self.db)as c:c.execute("update source set grade='第三方整理'")
  with self.assertRaises(ValueError):self.prepare()
  with sqlite3.connect(self.db)as c:c.execute("update source set grade='官方'");c.execute('insert into source select * from source')
  with self.assertRaises(ValueError):self.prepare()
 def test_bad_proof_sampling_or_original_fingerprint_is_rejected(self):
  for mutate in [lambda x:x['review']['file_proof'].update(sample_passed=False),lambda x:x['review']['file_proof'].update(sample_locators=[]),lambda x:x['locator'].update(sha256='0'*64)]:
   m=copy.deepcopy(self.manifest);mutate(m['rows'][0])
   with self.assertRaises(ValueError):self.prepare(m)
 def test_tampered_event_is_not_written(self):
  m=self.prepare();m['rows'][0]['projection']['total']='999'
  with self.assertRaises(ValueError):v.ingest(self.db,m)
  with sqlite3.connect(self.audit)as c:self.assertEqual(c.execute('select count(*)from ky_check_sample').fetchone()[0],0)
 def test_raw_scope_and_sample_objects_are_validated(self):
  for mutate in [lambda x:x['scope_context'].update(scope_raw='仅限研究方向01，联合培养'),lambda x:x['review']['file_proof'].update(sample_locators=['a','b','c']),lambda x:x.update(src_row=999)]:
   m=copy.deepcopy(self.manifest);mutate(m['rows'][0])
   with self.assertRaises(ValueError):self.prepare(m)
 def test_rehashed_candidate_cannot_disagree_with_projection(self):
  import hashlib
  m=self.prepare();v.ingest(self.db,m)
  with sqlite3.connect(self.audit)as c:
   e=json.loads(c.execute('select note from ky_check_sample').fetchone()[0]);e['candidate']['row']['total']=999;e.pop('event_sha256');e['event_sha256']=hashlib.sha256(v.dump(e).encode()).hexdigest();c.execute('update ky_check_sample set note=?',(v.dump(e),))
  with sqlite3.connect(':memory:')as c:
   c.execute('attach database ? as data',(str(self.db),));c.execute('attach database ? as audit',(str(self.audit),));self.assertIsNone(v.verified_record(c,'old-row'))
 def test_current_scope_change_invalidates_old_certificate(self):
  m=self.prepare();v.ingest(self.db,m)
  with sqlite3.connect(self.db)as c:
   c.execute('create table ky_line_scope_context(record_id text,direction text,joint_program text,admission_route text,scope_raw text)');c.execute('insert into ky_line_scope_context values(?,?,?,?,?)',('old-row','方向01','联培','调剂','限定'))
  with sqlite3.connect(':memory:')as c:
   c.execute('attach database ? as data',(str(self.db),));c.execute('attach database ? as audit',(str(self.audit),));self.assertIsNone(v.verified_record(c,'old-row'))
 def test_no_source_level_coverage_certificate_for_one_existing_row(self):
  import csv,kaoyan_on_demand as tool
  path=self.root/'coverage.csv';path.write_text('school,year,scope_level,status,formal_official_rows,reason\n合成大学,2026,学院专业资格线,partial,3,旧范围\n')
  tool.update_coverage(path,'合成大学',[dict(year=2026,layer='lines',program='125300',reason='已核存量',status='obtained',source_ids=['old-source'],verification_only=True,published_in_library=True,published_rows=0)])
  with path.open()as f:row=next(csv.DictReader(f))
  self.assertEqual(row['on_demand_obtained'],'');self.assertEqual(row['formal_official_rows'],'3');self.assertEqual(row['status'],'partial')
 def test_lookup_ignores_unverified_neighbours_and_invalid_source_level_cache(self):
  import contextlib
  from unittest.mock import patch
  import kaoyan_on_demand as tool
  m=self.prepare();v.ingest(self.db,m)
  with sqlite3.connect(self.db)as c:
   c.execute("insert into ky_retest_line select "+','.join("'neighbour'"if k=='record_id'else "'另一个学院'"if k=='college'else k for k in self.oldrow)+" from ky_retest_line limit 1")
  @contextlib.contextmanager
  def opened(*args):
   c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('attach database ? as data',(str(self.db),));c.execute('attach database ? as audit',(str(self.audit),))
   try:yield c,None
   finally:c.close()
  coverage=[dict(school='合成大学',year='2026',scope_level='学院专业资格线',status='partial',on_demand_obtained='{"125300":["old-source"]}')]
  with patch.object(tool.zhiqu_db,'_open',side_effect=opened),patch.object(tool.zhiqu_db,'_tables',return_value={'ky_retest_line','ky_check_sample'}):
   hit=tool.lookup(self.db,self.identity,['125300'],[2026],['lines'],coverage)[0]
   self.assertTrue(hit['obtained']);self.assertEqual([r['record_id']for r in hit['records']],['old-row']);self.assertEqual(hit['records'][0]['study_mode'],'全日制')
   with sqlite3.connect(self.audit)as c:c.execute('delete from ky_check_sample')
   self.assertFalse(tool.lookup(self.db,self.identity,['125300'],[2026],['lines'],coverage)[0]['obtained'])
 def test_orchestrator_publishes_only_a_verification_manifest(self):
  from unittest.mock import Mock,patch
  import kaoyan_on_demand as tool
  url='https://fixture.edu.cn/2026/line.html'
  request=dict(database=str(self.db),school='合成大学',programs=['125300'],years=[2026],layers=['lines'],seconds=600,output=str(self.root/'out'),coverage=str(self.root/'absent-coverage.csv'),entries=[url])
  def publish(db,manifests,out,deadline):
   self.assertEqual([layer for layer,_ in manifests],['line_verification']);receipt=v.ingest(db,manifests[0][1]);return {'ingest':[receipt],'published':True}
  with patch.object(tool,'resolve_school',return_value=(self.identity,{'known_official_document_entry_url':url},[])):
   result=tool.run_request(request,registry=[],lookup_fn=Mock(return_value=[dict(year=2026,layer='lines',program='125300',obtained=False,source_ids=['old-source'],records=[],existing_rows=1)]),fetch=Mock(return_value=({'body':self.body},{'url':url,'http_status':200})),publisher=publish)
  self.assertTrue(result['published']);r=result['outcomes'][0];self.assertTrue(r['verification_only']);self.assertEqual(r['published_rows'],0);self.assertEqual(r['status'],'obtained');self.assertEqual(r['source_ids'],['old-source'])
  with sqlite3.connect(self.db)as c:self.assertEqual(c.execute('select count(*)from source').fetchone()[0],1);self.assertEqual(c.execute('select count(*)from ky_retest_line').fetchone()[0],1)
 def test_header_rows_cannot_count_as_samples(self):
  for continuation in (False,True):
   m=copy.deepcopy(self.manifest);proof=m['rows'][0]['review']['file_proof'];proof['sample_locators'][0]['row']=1
   if continuation:
    proof['header_continuation_rows']=[dict(page=1,table=1,row=2)];proof['sample_locators'][0]['row']=2
   with self.assertRaises(ValueError):self.prepare(m)
 def test_hidden_note_scope_is_not_dropped(self):
  m=copy.deepcopy(self.manifest);m['rows'][0]['row']['note']='仅限研究方向01联合培养调剂'
  with self.assertRaises(ValueError):self.prepare(m)
 def test_malformed_locator_is_an_invalid_certificate_not_a_query_crash(self):
  import hashlib
  m=self.prepare();v.ingest(self.db,m)
  with sqlite3.connect(self.audit)as c:
   e=json.loads(c.execute('select note from ky_check_sample').fetchone()[0]);e['candidate']['locator']=[];e.pop('event_sha256');e['event_sha256']=hashlib.sha256(v.dump(e).encode()).hexdigest();c.execute('update ky_check_sample set note=?',(v.dump(e),))
  with sqlite3.connect(':memory:')as c:
   c.execute('attach database ? as data',(str(self.db),));c.execute('attach database ? as audit',(str(self.audit),));self.assertIsNone(v.verified_record(c,'old-row'))
 def test_identical_but_unexplained_scope_is_not_certified_as_ordinary(self):
  m=copy.deepcopy(self.manifest);m['rows'][0]['row']['note']='仅限01方向'
  with sqlite3.connect(self.db)as c:c.execute("update ky_retest_line set note='仅限01方向'")
  with self.assertRaises(ValueError):self.prepare(m)
 def test_single_subject_rule_is_preserved_but_not_certified_by_total_check(self):
  with sqlite3.connect(self.db)as c:c.execute("update ky_retest_line set note='总分线；单科线执行国家A类基本要求；首次；原表类别：专业硕士（全日制）'")
  m=self.prepare();self.assertEqual(m['rows'][0]['verified_fields'],['year','total']);self.assertIn('国家A类',m['rows'][0]['existing_scope_snapshot']['note'])
 def test_query_certificate_binds_current_source_and_projection(self):
  m=self.prepare();v.ingest(self.db,m)
  with sqlite3.connect(':memory:')as c:
   c.execute('attach database ? as data',(str(self.db),));c.execute('attach database ? as audit',(str(self.audit),));self.assertEqual(v.verified_record(c,'old-row')['projection']['study_mode'],'全日制')
   c.execute("update data.ky_retest_line set total=219");self.assertIsNone(v.verified_record(c,'old-row'))

if __name__=='__main__':unittest.main()
