import copy,importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts/ingest_kaoyan_lines.py'
spec=importlib.util.spec_from_file_location('ingest_kaoyan_lines',P);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class IngestKaoyanLinesTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'education.stage.sqlite'
  c=sqlite3.connect(self.path);c.execute('CREATE TABLE institution(institution_id TEXT PRIMARY KEY,name TEXT)');c.execute("INSERT INTO institution VALUES('1000000001','甲大学')")
  c.execute('CREATE TABLE source('+','.join(k+' TEXT'+(' PRIMARY KEY' if k=='source_id' else '') for k in mod.SOURCE)+')')
  raw=','.join('"'+k+'" '+('REAL' if k in mod.NUM else 'TEXT') for k in mod.RAW)
  c.execute('CREATE TABLE ky_retest_line('+raw+',record_id TEXT PRIMARY KEY,source_id TEXT REFERENCES source(source_id),value_status TEXT NOT NULL,quarantine_reason TEXT,verification_status TEXT NOT NULL,excerpt_locator_json TEXT NOT NULL,original_row_json TEXT NOT NULL)')
  c.execute('CREATE TABLE ky_retest_line_source(record_id TEXT REFERENCES ky_retest_line(record_id),source_id TEXT REFERENCES source(source_id),role TEXT,locator_json TEXT,PRIMARY KEY(record_id,source_id))')
  c.execute('CREATE TABLE storage_object(name TEXT PRIMARY KEY,kind TEXT,definition TEXT)')
  c.execute('CREATE TABLE storage_moved(name TEXT PRIMARY KEY)')
  c.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
  c.executemany('INSERT INTO storage_manifest VALUES(?,?)',[('generation','test-generation'),('audit_file','audit-test-generation.sqlite')])
  c.execute('CREATE TABLE storage_external_fk(owner TEXT,table_name TEXT,from_columns TEXT,parent_owner TEXT,parent_table TEXT,to_columns TEXT,id INTEGER,on_update TEXT,on_delete TEXT,match TEXT,PRIMARY KEY(owner,table_name,id))');c.commit();c.close()
  self.audit=Path(self.tmp.name)/'audit-test-generation.sqlite'
  with sqlite3.connect(self.audit) as a:
   a.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)');a.execute("INSERT INTO storage_manifest VALUES('generation','test-generation')")
  source={k:'' for k in mod.SOURCE};source.update(source_id='s1',grade='官方',publisher='甲大学',title='2026复试线',landing_url='https://example.edu.cn/lines',retrieved='2026-01-01')
  row={k:None for k in mod.RAW};row.update(year=2026,school='甲大学',institution_id='1000000001',program_code='085400',total=300,read_method='文本',line_scope='原口径')
  self.m={'sources':[source],'rows':[{'row':row,'record_id':'r1','source_id':'s1','institution_id':'1000000001','scope_kind':'专业线','src_page':1,'src_table':'表1','src_row':3,'excerpt':'总分300','locator':'第1页表1第3行','components':{'single_100':40,'exam_1':40},'review':{'status':'approved','method':'逐格核对'}}]}
 def tearDown(self):self.tmp.cleanup()
 def run_ingest(self,m=None):return mod.ingest(self.path,m or self.m)
 def test_insert_idempotence_registry_and_locator(self):
  self.assertEqual(self.run_ingest()['inserted'],1);self.assertEqual(self.run_ingest()['existing'],1)
  with sqlite3.connect(self.path) as c:
   c.row_factory=sqlite3.Row;r=dict(c.execute('SELECT * FROM ky_retest_line').fetchone())
   self.assertEqual(len(r),29);self.assertEqual(r['original_row_json'],'{}');self.assertEqual(json.loads(r['excerpt_locator_json'])['src_row'],3)
   self.assertIsNone(r['politics']);self.assertEqual(c.execute('SELECT count(*) FROM ky_line_component').fetchone()[0],2)
   self.assertEqual(c.execute("SELECT kind FROM storage_object WHERE name='ky_line_component'").fetchone()[0],'table')
   self.assertEqual(set(json.loads(r['value_status'])),set(mod.NUM));self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
 def test_full_evidence_only_in_paired_audit(self):
  self.m['rows'][0]['locator']={'sha256':'a'*64,'large_header_proof':['原表头']*500}
  self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='ky_line_original_evidence'").fetchone())
   self.assertNotIn('large_header_proof',c.execute('SELECT excerpt_locator_json FROM ky_retest_line').fetchone()[0])
   self.assertTrue(all('large_header_proof' not in x[0] for x in c.execute('SELECT src_locator FROM ky_line_component')))
   self.assertEqual(c.execute("SELECT count(*) FROM storage_external_fk WHERE table_name='ky_line_original_evidence'").fetchone()[0],2)
  with sqlite3.connect(self.audit) as c:
   evidence=json.loads(c.execute('SELECT excerpt_locator_json FROM ky_line_original_evidence').fetchone()[0])
   self.assertEqual(evidence['locator']['large_header_proof'],['原表头']*500)
 def test_query_reassembles_and_binds_audit_evidence(self):
  self.run_ingest()
  query_path=P.with_name('zhiqu_db.py')
  spec=importlib.util.spec_from_file_location('line_query_test',query_path);query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)
  with query._open('education',self.path) as (c,_):
   raw=dict(c.execute('SELECT * FROM data.ky_retest_line').fetchone())
   result=query._record(c,'ky_retest_line',raw)
   self.assertEqual(result['excerpt'],'总分300')
   self.assertEqual(result['values']['single_100']['original_locator']['review']['status'],'approved')
  with sqlite3.connect(self.audit) as c:c.execute("UPDATE ky_line_original_evidence SET source_id='wrong-source'")
  with query._open('education',self.path) as (c,_):
   raw=dict(c.execute('SELECT * FROM data.ky_retest_line').fetchone())
   with self.assertRaises(query.QueryError):query._record(c,'ky_retest_line',raw)
 def test_wrong_audit_generation_is_refused(self):
  with sqlite3.connect(self.audit) as c:c.execute("UPDATE storage_manifest SET value='another' WHERE key='generation'")
  with self.assertRaisesRegex(ValueError,'代号'):self.run_ingest()
 def test_exact_150_component_preserves_denominator(self):
  self.m['rows'][0]['components']={'single_150':68}
  self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute("SELECT component,value FROM ky_line_component").fetchall(),[('single_150',68.0)])
 def test_standard_score_is_not_initial_total(self):
  self.m['rows'][0]['row']['total']=None
  self.m['rows'][0]['scope_kind']='专项资格规则'
  self.m['rows'][0]['components']={'standard_score':126}
  self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertIsNone(c.execute('SELECT total FROM ky_retest_line').fetchone()[0])
   self.assertEqual(c.execute('SELECT component,value FROM ky_line_component').fetchall(),[('standard_score',126.0)])
 def test_combined_exam_condition_is_not_single_subject(self):
  self.m['rows'][0]['components']={'exam_1_2_3_sum':178}
  self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertIsNone(c.execute('SELECT politics FROM ky_retest_line').fetchone()[0])
   self.assertEqual(c.execute('SELECT component,value FROM ky_line_component').fetchall(),[('exam_1_2_3_sum',178.0)])
 def test_original_comprehensive_does_not_guess_exam_slot_or_maximum(self):
  self.m['rows'][0]['components']={'comprehensive_unspecified':108,'english_or_politics':36}
  self.m['rows'][0]['excerpt']='原表：总分294，英语/政治36，综合108；未注明综合科目序及满分'
  self.run_ingest()
  query_path=P.with_name('zhiqu_db.py')
  spec=importlib.util.spec_from_file_location('comprehensive_query_test',query_path);query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)
  with query._open('education',self.path) as (c,_):
   raw=dict(c.execute('SELECT * FROM data.ky_retest_line').fetchone())
   result=query._record(c,'ky_retest_line',raw)
   self.assertEqual(result['values']['comprehensive_unspecified']['value'],108)
   self.assertEqual(result['values']['english_or_politics']['value'],36)
   self.assertIsNone(raw['politics']);self.assertIsNone(raw['english'])
   self.assertIn('原表合列',query.LABELS['english_or_politics'])
   self.assertIn('原表未注明科目序及满分',query.LABELS['comprehensive_unspecified'])
   self.assertIsNone(raw['math']);self.assertIsNone(raw['major1']);self.assertIsNone(raw['major2'])
   self.assertFalse(c.execute("SELECT 1 FROM data.ky_line_component WHERE component IN ('exam_3','single_over_100','single_150')").fetchone())
 def _assert_literal_foreign_language_component(self,component,label):
  self.m['rows'][0]['components']={component:60}
  self.run_ingest()
  spec=importlib.util.spec_from_file_location('literal_foreign_query_test',P.with_name('zhiqu_db.py'));query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)
  with query._open('education',self.path) as (c,_):
   raw=dict(c.execute('SELECT * FROM data.ky_retest_line').fetchone())
   result=query._record(c,'ky_retest_line',raw)
   self.assertEqual(result['values'][component]['value'],60)
   self.assertEqual(query.LABELS[component],label)
   self.assertIsNone(raw['politics']);self.assertIsNone(raw['english'])
   self.assertEqual(c.execute('SELECT component FROM data.ky_line_component').fetchall()[0][0],component)
   self.assertFalse(c.execute("SELECT 1 FROM data.ky_line_component WHERE component IN ('exam_1','exam_2','single_100','single_150','english_or_politics')").fetchone())
 def test_shared_politics_foreign_language_does_not_mean_boolean_or(self):
  self._assert_literal_foreign_language_component('politics_foreign_language_shared','政治／外语门槛（原表合列，未限定语种）')
 def test_unspecified_foreign_language_is_not_assumed_english(self):
  self._assert_literal_foreign_language_component('foreign_language_unspecified','外语门槛（原表未限定语种）')
 def test_conflicting_record_rejected_and_rollback(self):
  self.run_ingest();m=copy.deepcopy(self.m);m['rows'][0]['row']['total']=301
  with self.assertRaisesRegex(ValueError,'冲突'):self.run_ingest(m)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT total FROM ky_retest_line').fetchone()[0],300)
 def test_source_conflict_rejected(self):
  self.run_ingest();m=copy.deepcopy(self.m);m['sources'][0]['title']='另标题'
  with self.assertRaisesRegex(ValueError,'冲突'):self.run_ingest(m)
 def test_school_exact_identity(self):
  self.m['rows'][0]['row']['school']='甲大'
  with self.assertRaisesRegex(ValueError,'精确匹配'):self.run_ingest()
 def test_unverified_staging_dates_never_become_source_dates(self):
  self.m['sources'][0]['published']=''
  self.m['sources'][0]['retrieved']='2026-10-21'
  self.m['rows'][0]['row'].update(published_date='2026-03-01',retrieved_date='2026-10-22')
  self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT published_date,retrieved_date FROM ky_retest_line').fetchone(),(None,'2026-10-21'))
 def test_verified_publication_is_separate_from_retrieval(self):
  self.m['sources'][0]['published']='2026-03-19'
  self.m['sources'][0]['retrieved']='2026-10-21'
  self.m['rows'][0]['row'].update(published_date='',retrieved_date='2026-10-22')
  self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT published_date,retrieved_date FROM ky_retest_line').fetchone(),('2026-03-19','2026-10-21'))
 def test_total_rule_stays_null_and_components_not_politics(self):
  self.m['rows'][0]['row']['total']='执行国家线';self.m['rows'][0]['scope_kind']='国家线适用规则';self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT total,politics FROM ky_retest_line').fetchone(),(None,None))
   self.assertEqual(c.execute("SELECT value FROM ky_line_component WHERE component='single_100'").fetchone()[0],40)
 def test_strict_numbers_and_unknown_component(self):
  for value in [-1,float('nan'),'40分',True]:
   with self.subTest(value=value):
    m=copy.deepcopy(self.m);m['rows'][0]['row']['english']=value
    with self.assertRaises(ValueError):self.run_ingest(m)
  m=copy.deepcopy(self.m);m['rows'][0]['components']={'politics':40}
  with self.assertRaisesRegex(ValueError,'科目槽'):self.run_ingest(m)
 def test_privacy_key_and_number_rejected(self):
  for value in [{'candidate_id':'x'}, {'姓名':'张某'}, {'excerpt':'110101200001010011'}]:
   m=copy.deepcopy(self.m);m['rows'][0].update(value)
   with self.assertRaisesRegex(ValueError,'身份'):self.run_ingest(m)
 def test_unapproved_rejected(self):
  self.m['rows'][0]['review']['status']='candidate'
  with self.assertRaisesRegex(ValueError,'批准'):self.run_ingest()
 def test_image_review_threshold_and_hash(self):
  r=self.m['rows'][0];r['row']['read_method']='读图';r['review'].update(candidate_count=60,image_sha256='a'*64,samples=[{'status':'approved','sample_id':str(i)} for i in range(5)])
  with self.assertRaisesRegex(ValueError,'抽样不足'):self.run_ingest()
  r['review']['samples'].append({'status':'approved','sample_id':'5'});self.assertEqual(self.run_ingest()['inserted'],1)
 def test_image_needs_original_hash_and_approved_samples(self):
  r=self.m['rows'][0];r['row']['read_method']='读图';r['review'].update(samples=[{'status':'approved'}])
  with self.assertRaisesRegex(ValueError,'指纹'):self.run_ingest()
  r['review'].update(image_sha256='b'*64,samples=[{'status':'candidate'}])
  with self.assertRaisesRegex(ValueError,'抽样'):self.run_ingest()
 def test_official_database_path_refused(self):
  p=Path(self.tmp.name)/'education.sqlite';p.touch()
  with self.assertRaisesRegex(ValueError,'候选'):mod.ingest(p,self.m)
 def test_authorizer_blocks_old_business_update(self):
  with sqlite3.connect(self.path) as c:c.execute("CREATE TRIGGER unwanted AFTER INSERT ON source BEGIN UPDATE institution SET name='误写'; END")
  with self.assertRaises(sqlite3.DatabaseError):self.run_ingest()
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT name FROM institution').fetchone()[0],'甲大学')
 def test_url_timestamp_and_fingerprint_are_not_identity_numbers(self):
  self.m['sources'][0]['file_url']='https://example.edu.cn/20261020143059.pdf'
  self.m['sources'][0]['archive_sha256']='1'*64
  self.m['rows'][0]['row']['source_url']='https://example.edu.cn/20261020143059'
  self.assertEqual(self.run_ingest()['inserted'],1)
  m=copy.deepcopy(self.m);m['sources'][0]['candidate_id']='20261020143059'
  with self.assertRaisesRegex(ValueError,'身份字段'):self.run_ingest(m)
 def test_rule_total_original_words_preserved(self):
  self.m['rows'][0]['row']['total']='按A区国家线';self.run_ingest()
  with sqlite3.connect(self.path) as c:
   total,note=c.execute('SELECT total,note FROM ky_retest_line').fetchone();self.assertIsNone(total);self.assertIn('原total=按A区国家线',note)
 def test_national_rule_numeric_total_refused(self):
  self.m['rows'][0]['scope_kind']='国家线适用规则'
  with self.assertRaisesRegex(ValueError,'禁止填数值total'):self.run_ingest()
 def test_null_status_default_and_explicit_review(self):
  self.m['rows'][0]['field_status']={'english':{'status':'来源未提供','reason':'原表没有英语列'}};self.run_ingest()
  with sqlite3.connect(self.path) as c:
   v=json.loads(c.execute('SELECT value_status FROM ky_retest_line').fetchone()[0]);self.assertEqual(v['english']['status'],'来源未提供');self.assertEqual(v['math'],{'status':'原件缺失','reason':'空值原文口径待核'})
 def test_empty_status_reason_refused(self):
  self.m['rows'][0]['field_status']={'english':{'status':'来源未提供'}}
  with self.assertRaisesRegex(ValueError,'status与reason'):self.run_ingest()
 def test_image_sample_source_binding_and_positive_count(self):
  r=self.m['rows'][0];r['row']['read_method']='读图';r['review'].update(candidate_count=0,image_sha256='a'*64,samples=[{'status':'approved','sample_id':'one'}])
  with self.assertRaisesRegex(ValueError,'抽样不足'):self.run_ingest()
  r['review']['candidate_count']=1;self.run_ingest()
  with sqlite3.connect(self.audit) as c:
   v=json.loads(c.execute('SELECT excerpt_locator_json FROM ky_line_original_evidence').fetchone()[0])['review']['samples'][0];self.assertEqual(v['source_id'],'s1');self.assertEqual(v['image_sha256'],'a'*64)
  r['review']['samples'][0]['source_id']='wrong'
  with self.assertRaisesRegex(ValueError,'不匹配'):self.run_ingest()
 def test_new_source_requires_url_and_valid_deleted_fingerprint(self):
  self.m['sources'][0]['landing_url']=''
  with self.assertRaisesRegex(ValueError,'URL'):self.run_ingest()
  s=self.m['sources'][0];s['landing_url']='https://example.edu.cn/line';s['archive_status']='已删除（有指纹，核对见记录）'
  with self.assertRaisesRegex(ValueError,'SHA256'):self.run_ingest()
  s['archive_sha256']='b'*64;s['archive_path']='old.pdf'
  with self.assertRaisesRegex(ValueError,'路径为空'):self.run_ingest()
  s['archive_path']='';self.assertEqual(self.run_ingest()['inserted'],1)
 def test_unchanged_existing_source_can_be_reused_without_update(self):
  self.run_ingest();self.m['sources']=[];self.assertEqual(self.run_ingest()['existing'],1)
 def test_same_program_different_directions_remain_separate(self):
  first=self.m['rows'][0];first['scope_context']={'direction':'人工智能','joint_program':'','admission_route':'一志愿','scope_raw':'01方向'}
  second=copy.deepcopy(first);second['record_id']='r2';second['scope_context']['direction']='软件工程';second['scope_context']['scope_raw']='02方向';self.m['rows'].append(second)
  self.assertEqual(self.run_ingest()['inserted'],2);self.assertEqual(self.run_ingest()['existing'],2)
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT direction FROM ky_line_scope_context ORDER BY record_id').fetchall(),[('人工智能',),('软件工程',)])
   self.assertEqual(c.execute("SELECT count(*) FROM ky_retest_line WHERE program_code='085400'").fetchone()[0],2)
   self.assertEqual(c.execute("SELECT kind FROM storage_object WHERE name='ky_line_scope_context'").fetchone()[0],'table')
 def test_scope_missing_not_inferred_from_note(self):
  self.m['rows'][0]['row']['note']='联合培养、一志愿';self.m['rows'][0]['scope_context']={'direction':'方向甲'};self.run_ingest()
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT direction,joint_program,admission_route,scope_raw FROM ky_line_scope_context').fetchone(),('方向甲','','',''))
 def test_scope_optional_and_conflict_rejected(self):
  self.run_ingest()
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM ky_line_scope_context').fetchone()[0],0)
  self.m['rows'][0]['scope_context']={'direction':'甲'};self.run_ingest();self.m['rows'][0]['scope_context']={'direction':'乙'}
  with self.assertRaisesRegex(ValueError,'冲突'):self.run_ingest()
 def test_scope_unknown_or_nontext_rejected(self):
  for context in [{'candidate_name':'x'},{'other':'x'},{'direction':None}]:
   self.m['rows'][0]['scope_context']=context
   with self.assertRaises(ValueError):self.run_ingest()
 def test_atomic_failure_does_not_add_source_or_fact(self):
  self.m['rows'][0]['components']={'bad':10}
  with self.assertRaises(ValueError):self.run_ingest()
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0);self.assertEqual(c.execute('SELECT count(*) FROM ky_retest_line').fetchone()[0],0)
 def test_citation_url_timestamp_is_not_personal_id(self):
  self.m['sources'][0]['citation']='甲校，公告，https://a.edu.cn/files/1773998031161818.pdf，2026-10-22'
  self.assertEqual(self.run_ingest()['inserted'],1)

if __name__=='__main__':unittest.main()
