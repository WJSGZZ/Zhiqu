import copy, importlib.util, json, math, sqlite3, sys, tempfile, unittest
from pathlib import Path

P=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts/ingest_gaokao_official.py'
sys.path.insert(0,str(P.parent))
try:
 spec=importlib.util.spec_from_file_location('ingest_gaokao_official_test',P);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
finally:sys.path.pop(0)

class IngestGaokaoOfficialTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'education.stage.sqlite';self.audit=self.path.parent/'audit-test-generation.sqlite'
  with sqlite3.connect(self.path) as c:
   c.execute('CREATE TABLE institution(institution_id TEXT PRIMARY KEY,name TEXT)');c.execute("INSERT INTO institution VALUES('1000000001','甲大学')")
   c.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
   c.execute('CREATE TABLE source('+','.join(k+' TEXT'+(' PRIMARY KEY' if k=='source_id' else '') for k in mod.SOURCE)+')')
   c.execute('CREATE TABLE gk_official_yfyd('+','.join(k+(' INTEGER' if k in ['year','score','cum','src_page'] else ' TEXT') for k in mod.YFYD)+',PRIMARY KEY(province,year,subject,score))')
   c.execute('CREATE TABLE gk_official_cutoff('+','.join(k+(' INTEGER' if k in ['year','plan','admit','score','rank','src_page'] else ' TEXT') for k in mod.CUTOFF)+')')
   c.execute('CREATE TABLE official_cutoff_scope(source_id TEXT REFERENCES source(source_id),public_record TEXT,scope_json TEXT,locator_json TEXT,PRIMARY KEY(source_id,public_record))')
   c.execute('CREATE TABLE source_format_reference(source_id TEXT PRIMARY KEY REFERENCES source(source_id),provided_fields TEXT,scope_fields TEXT,excerpt TEXT,locator TEXT,scope_values TEXT)')
   c.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT)');c.executemany('INSERT INTO storage_manifest VALUES(?,?)',[('generation','test-generation'),('audit_file',self.audit.name)])
   c.execute('CREATE TABLE storage_object(name TEXT PRIMARY KEY,kind TEXT,definition TEXT)');c.execute('CREATE TABLE storage_moved(name TEXT PRIMARY KEY)')
   c.execute('CREATE TABLE storage_external_fk(owner TEXT,table_name TEXT,from_columns TEXT,parent_owner TEXT,parent_table TEXT,to_columns TEXT,id INTEGER,on_update TEXT,on_delete TEXT,match TEXT,PRIMARY KEY(owner,table_name,id))')
   c.execute("INSERT INTO gk_official_yfyd(province,year,subject,score,cum,value_status) VALUES('旧省',2024,'旧科',600,100,'{}')")
  with sqlite3.connect(self.audit) as c:
   c.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT)');c.execute("INSERT INTO storage_manifest VALUES('generation','test-generation')")
  self.source={k:'' for k in mod.SOURCE};self.source.update(source_id='s1',grade='官方',publisher='考试院',title='2026分数表',landing_url='https://example.gov.cn/table',retrieved='2026-10-22',archive_sha256='a'*64)
  self.m={'sources':[self.source],'datasets':[self.dataset('gk_official_yfyd')]}
 def tearDown(self):self.temp.cleanup()
 def dataset(self,table,n=3,prefix='r',sid='s1',digest='a'*64):
  rows=[]
  for i in range(n):
   rid=f'{prefix}{i}';data={k:None for k in mod.FIELDS[table]};data.update(province='甲省',year=2026,subject='物理-普通',source_id=sid,src_row=str(i+2),src_page=1,src_table='表1',locator_method='原表文本')
   data['value_status']={k:{'status':'官方原值' if k in {'score','cum','total','plan_n'} else '来源未提供','reason':'原格已主审或原表未提供'} for k in mod.VALUE_FIELDS[table]}
   if table=='gk_official_yfyd':data.update(score=600-i,cum=100+i,src=f'table:{rid}',locator_status='原格已核')
   elif table=='gk_official_cutoff':data.update(code=str(100+i),name='甲大学',institution_id='1000000001',score=600.25,src=f'table:{rid}',locator_status='原格已核')
   elif table=='gk_yfyd_bucket':data.update(record_id=rid,score_label='101分以下及缺考',score_boundary=101,boundary_operator='以下及缺考；端点未明确',cum=200+i,segment_n=None,scope_raw='普通历史、艺术历史、体育历史；原尾桶包含缺考，端点未明确')
   elif table=='gk_batch_line':data.update(record_id=rid,total=500,education_level='本科',line_scope='普通本科',requirements_json={})
   else:data.update(record_id=rid,plan_n=10,school_raw='甲大学',institution_id='1000000001',school_code='001',group_code='003',major_code='080901',major_name='计算机科学与技术',gender='不限',plan_type='普通',batch='本科批')
   loc={'sha256':digest,'page':1,'table':1,'row':i+2}
   rows.append({'record_id':rid,'data':data,'scope':{'batch':'本科批','student_category':'普通','subject_raw':'物理'},'locator':loc,'excerpt':{'score_cell':str(data.get('score',data.get('total',data.get('plan_n'))))}})
  return {'source_id':sid,'table':table,'rows':rows,'review':{'status':'approved','read_method':'text','original_data_rows':n,'extracted_rows':n,'samples':[{'record_id':r['record_id'],'status':'approved','locator':r['locator']} for r in rows[:min(n,3)]]}}
 def ingest(self,m=None):return mod.ingest(self.path,self.m if m is None else m)
 def snapshot(self):
  with sqlite3.connect(self.path) as c:return c.execute('SELECT * FROM gk_official_yfyd WHERE province=\'旧省\'').fetchall(),c.execute('SELECT * FROM institution').fetchall()
 def test_original_decimal_score_preserves_integer_keys_and_traceable_context(self):
  before=self.snapshot()
  for i,r in enumerate(self.m['datasets'][0]['rows']):
   r['data']['score']=99.75-i/4
   r['yfyd_context']={'segment_n':None,'score_operator':'原表排序成绩（体育统考成绩）','score_upper':None,'scope_raw':'原表体育统考成绩；文化与专业均上线考生','count_raw':r['data']['cum'],'count_kind':'累计人数'}
   r['excerpt']={'score_cell':str(r['data']['score'])}
  self.assertEqual(self.ingest()['inserted'],3)
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute("SELECT score,typeof(score) FROM gk_official_yfyd WHERE province='甲省' ORDER BY score DESC").fetchall(),[(99.75,'real'),(99.5,'real'),(99.25,'real')])
   self.assertEqual(c.execute("SELECT typeof(score) FROM gk_official_yfyd WHERE province='旧省'").fetchone()[0],'integer')
   self.assertEqual(c.execute('SELECT count(*) FROM gk_yfyd_context').fetchone()[0],3)
   self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
  self.assertEqual(self.snapshot(),before)
  self.assertEqual(self.ingest()['existing'],3)
 def coverage(self,**changes):
  page=dict(page=1,a_observed=9,b_observed=9,a_assigned=9,b_assigned=9,a_unassigned=0,b_unassigned=0,a_multiset_equal=True,b_multiset_equal=True)
  page.update(changes);return [page]
 def test_shared_grid_omission_rejected_even_when_both_readers_agree(self):
  # Both grid readers lose the first data row below an external header.
  self.m['datasets'][0]['review']['numeric_coverage']=self.coverage(a_observed=12,b_observed=12,a_unassigned=3,b_unassigned=3,a_multiset_equal=False,b_multiset_equal=False)
  with self.assertRaisesRegex(ValueError,'未全部归属'):self.ingest()
  with sqlite3.connect(self.path)as c:self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0)
 def test_complete_numeric_coverage_keeps_only_proof_digest_per_fact(self):
  cov=self.coverage();self.m['datasets'][0]['review']['numeric_coverage']=cov
  self.assertEqual(self.ingest()['inserted'],3)
  with sqlite3.connect(self.audit)as c:
   review=json.loads(c.execute('SELECT excerpt_locator_json FROM gk_official_original_evidence LIMIT 1').fetchone()[0])['review']
  self.assertNotIn('numeric_coverage',review);self.assertEqual(len(review['numeric_coverage_sha256']),64)
 def test_numeric_coverage_rejects_forged_counts_and_inconsistent_readers(self):
  for cov in [[],self.coverage(a_assigned=True),self.coverage(b_observed=10),self.coverage(a_multiset_equal=False),self.coverage()+self.coverage()]:
   with self.subTest(cov=cov),self.assertRaisesRegex(ValueError,'数字归属|未全部归属'):
    mod.validate_numeric_coverage(dict(numeric_coverage=cov))
 def test_decimal_score_without_original_scope_is_rejected(self):
  self.m['datasets'][0]['rows'][0]['data']['score']=99.75
  with self.assertRaisesRegex(ValueError,'小数分'):self.ingest()
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0)
 def test_decimal_counts_remain_rejected(self):
  self.m['datasets'][0]['rows'][0]['data']['cum']=3.5
  with self.assertRaisesRegex(ValueError,'整数'):self.ingest()
 def test_original_decimal_bucket_boundary_retains_label_and_integer_storage(self):
  before=self.snapshot();d=self.dataset('gk_yfyd_bucket',n=1,prefix='decimal-tail')
  d['rows'][0]['data'].update(score_boundary=287.8,score_label='287.8分以上（含287.8分）',boundary_operator='以上（含）')
  self.m['datasets']=[d];self.assertEqual(self.ingest()['inserted'],1)
  with sqlite3.connect(self.path)as c:
   self.assertEqual(c.execute('SELECT score_boundary,typeof(score_boundary),score_label FROM gk_yfyd_bucket').fetchone(),(287.8,'real','287.8分以上（含287.8分）'))
  self.assertEqual(self.snapshot(),before)
 def test_decimal_bucket_boundary_cannot_disagree_with_original_label(self):
  for value,label in [(287.8,'287.9分以上（含287.9分）'),(.8,'287分以上（按0.8分段）')]:
   d=self.dataset('gk_yfyd_bucket',n=1);d['rows'][0]['data'].update(score_boundary=value,score_label=label);self.m['datasets']=[d]
   with self.assertRaisesRegex(ValueError,'原分数标签'):self.ingest()
 def test_all_business_tables_idempotent_old_unchanged_and_link_receipt(self):
  before=self.snapshot();self.m['datasets']=[self.dataset(t,prefix=str(i)+'-') for i,t in enumerate(mod.FIELDS)]
  a=self.ingest();b=self.ingest();self.assertEqual(a['inserted'],15);self.assertEqual(b['existing'],15);self.assertEqual(b['inserted'],0);self.assertEqual(self.snapshot(),before)
  self.assertEqual(a['tables']['gk_official_cutoff'],{'inserted':3,'existing':0});self.assertEqual(a['validated_business_link_count'],15);self.assertTrue(all(x['matches']==1 for x in a['validated_business_links']))
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT count(*) FROM storage_object').fetchone()[0],5);self.assertEqual(c.execute('SELECT count(*) FROM storage_external_fk').fetchone()[0],1);self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
   self.assertEqual(c.execute('SELECT score FROM gk_official_cutoff LIMIT 1').fetchone()[0],600.25)
  with sqlite3.connect(self.audit) as c:self.assertEqual(c.execute('SELECT count(*) FROM gk_official_original_evidence').fetchone()[0],15)
 def test_same_key_conflict_rolls_back_new_rows_and_source(self):
  self.ingest();m=copy.deepcopy(self.m);m['datasets'][0]['rows'][1]['data']['cum']=999
  extra=self.dataset('gk_batch_line',prefix='extra');m['datasets'].insert(0,extra)
  with self.assertRaisesRegex(ValueError,'冲突'):self.ingest(m)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM gk_batch_line').fetchone()[0],0);self.assertEqual(c.execute("SELECT cum FROM gk_official_yfyd WHERE province='甲省' AND score=599").fetchone()[0],101)
 def test_source_and_evidence_conflicts_are_immutable(self):
  self.ingest()
  for field in ['source','evidence']:
   m=copy.deepcopy(self.m)
   if field=='source':m['sources'][0]['title']='不同标题'
   else:m['datasets'][0]['rows'][0]['excerpt']={'score_cell':'另一摘录'}
   with self.subTest(field=field),self.assertRaisesRegex(ValueError,'冲突'):self.ingest(m)
 def test_wrong_table_source_identity_and_unknown_field(self):
  for mode in ['table','source','data_source','identity','field']:
   m={'sources':[copy.deepcopy(self.source)],'datasets':[self.dataset('gk_official_plan')]};d=m['datasets'][0]
   if mode=='table':d['table']='institution'
   if mode=='source':d['source_id']='absent'
   if mode=='data_source':d['rows'][0]['data']['source_id']='absent'
   if mode=='identity':d['rows'][0]['data']['institution_id']='9999999999'
   if mode=='field':d['rows'][0]['data']['unexpected']='x'
   with self.subTest(mode=mode),self.assertRaises(ValueError):self.ingest(m)
  m={'sources':[copy.deepcopy(self.source)],'datasets':[self.dataset('gk_official_plan')]};m['datasets'][0]['rows'][0]['data']['institution_id']=None
  self.assertEqual(self.ingest(m)['inserted'],3)
 def test_review_counts_and_approval_required(self):
  for field,value in [('status','draft'),('read_method','unknown'),('original_data_rows',2),('extracted_rows',4),('original_data_rows',True)]:
   m=copy.deepcopy(self.m);m['datasets'][0]['review'][field]=value
   with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.ingest(m)
 def test_text_samples_three_percent_at_least_three(self):
  self.m['datasets'][0]['review']['samples'].pop()
  with self.assertRaisesRegex(ValueError,'文本.*抽样不足'):self.ingest()
  self.m['datasets']=[self.dataset('gk_official_yfyd',n=101)]
  with self.assertRaisesRegex(ValueError,'文本.*抽样不足'):self.ingest()
  d=self.m['datasets'][0];r=d['rows'][3];d['review']['samples'].append({'record_id':r['record_id'],'status':'approved','locator':r['locator']});self.assertEqual(self.ingest()['inserted'],101)
 def test_image_samples_ten_percent_at_least_five(self):
  d=self.dataset('gk_official_yfyd',n=60);d['review']['read_method']='image';self.m['datasets']=[d]
  d['review']['samples']=[{'record_id':r['record_id'],'status':'approved','locator':r['locator']} for r in d['rows'][:5]]
  with self.assertRaisesRegex(ValueError,'图片.*抽样不足'):self.ingest()
  r=d['rows'][5];d['review']['samples'].append({'record_id':r['record_id'],'status':'approved','locator':r['locator']});self.assertEqual(self.ingest()['inserted'],60)
 def test_sha_group_prevents_splitting_sample_threshold(self):
  s=copy.deepcopy(self.source);s['source_id']='s2';self.m['sources'].append(s)
  self.m['datasets']=[self.dataset('gk_official_yfyd',n=50),self.dataset('gk_official_plan',n=51,prefix='p',sid='s2')]
  # Repeated approved sample IDs count once even when repeated across datasets.
  self.m['datasets'][1]['review']['samples']=copy.deepcopy(self.m['datasets'][0]['review']['samples'])
  with self.assertRaisesRegex(ValueError,'同SHA合并抽样不足'):self.ingest()
 def test_sample_binding_sha_and_approved_status(self):
  for mode in ['id','locator','sha','status']:
   m=copy.deepcopy(self.m);s=m['datasets'][0]['review']['samples'][0]
   if mode=='id':s['record_id']='unknown'
   if mode=='locator':s['locator']={'page':999}
   if mode=='sha':s['sha256']='b'*64
   if mode=='status':s['status']='draft'
   with self.subTest(mode=mode),self.assertRaises(ValueError):self.ingest(m)
 def test_global_record_id_duplicate_rejected(self):
  self.m['datasets'].append(self.dataset('gk_batch_line'))
  with self.assertRaisesRegex(ValueError,'全局唯一'):self.ingest()
 def test_numeric_invalid_and_integer_counts(self):
  for field,value in [('score',-1),('cum',float('nan')),('cum',float('inf')),('cum',1.2),('year',True)]:
   m=copy.deepcopy(self.m);m['datasets'][0]['rows'][0]['data'][field]=value
   with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.ingest(m)
  for table,field in [('gk_batch_line','total'),('gk_official_plan','plan_n'),('gk_official_cutoff','score')]:
   m={'sources':[copy.deepcopy(self.source)],'datasets':[self.dataset(table)]};m['datasets'][0]['rows'][0]['data'][field]=float('nan')
   with self.subTest(table=table),self.assertRaises(ValueError):self.ingest(m)
 def test_explicit_null_status_not_invented(self):
  d=self.m['datasets'][0];r=d['rows'][0];r['data']['cum']=None;r['data']['value_status']['cum']={'status':'来源未提供','reason':'原表未标累计口径'}
  r['yfyd_context']={'segment_n':None,'score_operator':'=','score_upper':None,'scope_raw':'普通类','count_raw':100,'count_kind':'原表未标明人数口径'}
  self.ingest()
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute("SELECT cum FROM gk_official_yfyd WHERE province='甲省' AND score=600").fetchone()[0],None)
   self.assertEqual(c.execute('SELECT count_raw,count_kind FROM gk_yfyd_context').fetchone(),(100,'原表未标明人数口径'))
   self.assertEqual(json.loads(c.execute("SELECT value_status FROM gk_official_yfyd WHERE province='甲省' AND score=600").fetchone()[0])['cum']['status'],'来源未提供')
 def test_yfyd_context_wrong_table_negative_or_ambiguous_count(self):
  for mode in ['negative','unknown_count','nonempty_cum','wrongtable']:
   m=copy.deepcopy(self.m);r=m['datasets'][0]['rows'][0];r['yfyd_context']={'segment_n':None,'score_operator':'=','score_upper':None,'scope_raw':'普通','count_raw':100,'count_kind':'原表未标明人数口径'};r['data']['cum']=None;r['data']['value_status']['cum']={'status':'来源未提供','reason':'未标人数口径'}
   if mode=='negative':r['yfyd_context']['count_raw']=-1
   if mode=='unknown_count':r['yfyd_context']['count_kind']=''
   if mode=='nonempty_cum':r['data']['cum']=100
   if mode=='wrongtable':m['datasets']=[self.dataset('gk_official_plan')];m['datasets'][0]['rows'][0]['yfyd_context']=r['yfyd_context']
   with self.subTest(mode=mode),self.assertRaises(ValueError):self.ingest(m)
 def test_value_status_required_for_all_numeric_facts(self):
  for v in [None,{}, {'cum':{'status':'官方原值','reason':'已核'}}]:
   m=copy.deepcopy(self.m);m['datasets'][0]['rows'][0]['data']['value_status']=v
   with self.subTest(value=v),self.assertRaises(ValueError):self.ingest(m)
 def test_cutoff_scope_format_and_compact_business_evidence(self):
  d=self.dataset('gk_official_cutoff');d['format']={'provided_fields':['score'],'scope_fields':{'grp':'source_group_code'},'excerpt':'院校｜专业组｜最低分','locator':'PDF第1页表头','scope_values':{'source_batch_raw':'本科批'}};self.m['datasets']=[d];self.ingest()
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT count(*) FROM official_cutoff_scope').fetchone()[0],3);self.assertEqual(c.execute('SELECT provided_fields FROM source_format_reference').fetchone()[0],'["score"]');loc=json.loads(c.execute('SELECT locator_json FROM official_cutoff_scope LIMIT 1').fetchone()[0]);self.assertEqual(loc['audit_table'],'gk_official_original_evidence')
  with sqlite3.connect(self.audit) as c:
   e=json.loads(c.execute('SELECT excerpt_locator_json FROM gk_official_original_evidence LIMIT 1').fetchone()[0]);self.assertIn('locator',e);self.assertNotIn('samples',e['review'])
 def test_no_pair_wrong_generation_and_formal_path(self):
  with sqlite3.connect(self.audit) as c:c.execute("UPDATE storage_manifest SET value='wrong'")
  with self.assertRaisesRegex(ValueError,'代号'):self.ingest()
  self.audit.unlink()
  with self.assertRaisesRegex(ValueError,'配对'):self.ingest()
  formal=self.path.parent/'education.sqlite';formal.touch()
  with self.assertRaisesRegex(ValueError,'候选'):mod.ingest(formal,self.m)
 def test_privacy_keys_and_identifier_rejected(self):
  for value in [{'candidate_id':'x'},{'姓名':'某某'},{'phone':'1'},{'note':'110101200001010011'}]:
   m=copy.deepcopy(self.m);m['datasets'][0]['rows'][0]['excerpt']=value
   with self.subTest(value=value),self.assertRaisesRegex(ValueError,'个人|身份'):self.ingest(m)
 def test_authorizer_blocks_old_update_and_transaction_rolls_back_ddl(self):
  before=self.snapshot()
  with sqlite3.connect(self.path) as c:c.execute("CREATE TRIGGER hostile AFTER INSERT ON source BEGIN UPDATE institution SET name='误写'; END")
  with self.assertRaises(sqlite3.DatabaseError):self.ingest()
  self.assertEqual(self.snapshot(),before)
  with sqlite3.connect(self.path) as c:
   self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0);self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='gk_batch_line'").fetchall())
 def test_nested_requirements_nan_and_raw_count_null_status(self):
  m={'sources':[copy.deepcopy(self.source)],'datasets':[self.dataset('gk_batch_line')]};m['datasets'][0]['rows'][0]['data']['requirements_json']={'minimum':float('nan')}
  with self.assertRaises(ValueError):self.ingest(m)
  m=copy.deepcopy(self.m);r=m['datasets'][0]['rows'][0];r['data']['cum']=None;r['yfyd_context']={'segment_n':None,'score_operator':'=','score_upper':None,'scope_raw':'普通','count_raw':100,'count_kind':'原表未标明人数口径'}
  with self.assertRaisesRegex(ValueError,'来源未提供'):self.ingest(m)
 def test_new_scope_does_not_merge_old_same_score_subject(self):
  d=self.dataset('gk_official_yfyd',prefix='special');
  for r in d['rows']:r['data']['subject']='物理-专项'
  self.m['datasets'].append(d);self.assertEqual(self.ingest()['inserted'],6)

 def bucket_pair(self):
  point=self.dataset('gk_official_yfyd',n=1,prefix='point');point['rows'][0]['data'].update(score=101,cum=123)
  bucket=self.dataset('gk_yfyd_bucket',n=1,prefix='bucket');bucket['rows'][0]['data'].update(cum=156,segment_n=33)
  for d,label in [(point,'明确分数点'),(bucket,'以下及缺考尾桶')]:d['review'].update(original_source_rows=2,partition=label)
  return {'sources':[copy.deepcopy(self.source)],'datasets':[point,bucket]}
 def test_real_101_point_and_unknown_endpoint_bucket_coexist(self):
  m=self.bucket_pair();before=self.snapshot();a=self.ingest(m);b=self.ingest(m)
  self.assertEqual((a['inserted'],b['existing']),(2,2));self.assertEqual(self.snapshot(),before)
  with sqlite3.connect(self.path)as c:
   self.assertEqual(c.execute("SELECT score,cum FROM gk_official_yfyd WHERE province='甲省'").fetchall(),[(101,123)])
   self.assertEqual(c.execute('SELECT score_boundary,score_label,boundary_operator,cum,segment_n FROM gk_yfyd_bucket').fetchone(),(101,'101分以下及缺考','以下及缺考；端点未明确',156,33))
   self.assertTrue(c.execute("SELECT definition FROM storage_object WHERE name='gk_yfyd_bucket'").fetchone())
   self.assertFalse(c.execute('PRAGMA foreign_key_check(gk_yfyd_bucket)').fetchall())
  with sqlite3.connect(self.audit)as c:
   e=json.loads(c.execute("SELECT excerpt_locator_json FROM gk_official_original_evidence WHERE table_name='gk_yfyd_bucket'").fetchone()[0]);self.assertEqual(e['business_key'],{'record_id':'bucket0'})
 def test_bucket_conflict_does_not_overwrite_point_or_bucket(self):
  m=self.bucket_pair();self.ingest(m);changed=copy.deepcopy(m);changed['datasets'][1]['rows'][0]['data']['cum']=999
  with self.assertRaisesRegex(ValueError,'冲突'):self.ingest(changed)
  with sqlite3.connect(self.path)as c:
   self.assertEqual(c.execute("SELECT cum FROM gk_official_yfyd WHERE province='甲省' AND score=101").fetchone()[0],123);self.assertEqual(c.execute('SELECT cum FROM gk_yfyd_bucket').fetchone()[0],156)
 def test_bucket_all_three_value_statuses_required_and_null_preserved(self):
  for field in ['score_boundary','cum','segment_n']:
   m=self.bucket_pair();del m['datasets'][1]['rows'][0]['data']['value_status'][field]
   with self.subTest(field=field),self.assertRaisesRegex(ValueError,'value_status'):self.ingest(m)
  m=self.bucket_pair();row=m['datasets'][1]['rows'][0];row['data']['segment_n']=None;row['data']['value_status']['segment_n']={'status':'来源未提供','reason':'原格未给，不能补0'};self.ingest(m)
  with sqlite3.connect(self.path)as c:self.assertIsNone(c.execute('SELECT segment_n FROM gk_yfyd_bucket').fetchone()[0])
 def test_bucket_requires_literal_label_operator_and_scope(self):
  for field in ['score_label','boundary_operator','scope_raw']:
   m=self.bucket_pair();m['datasets'][1]['rows'][0]['data'][field]=''
   with self.subTest(field=field),self.assertRaisesRegex(ValueError,'尾桶'):self.ingest(m)
 def test_bucket_counts_are_nonnegative_integer_and_boundary_required(self):
  for field,value in [('score_boundary',None),('score_boundary',-1),('score_boundary',101.5),('cum',-1),('cum',1.5),('segment_n',-1),('segment_n',True)]:
   m=self.bucket_pair();m['datasets'][1]['rows'][0]['data'][field]=value
   with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.ingest(m)
 def test_source_partition_count_and_names_must_close(self):
  for mode in ['wrongtotal','missingtotal','conflictingtotal','booltotal','missingpartition','duplicatepartition']:
   m=self.bucket_pair();a,b=m['datasets']
   if mode=='wrongtotal':
    for d in m['datasets']:d['review']['original_source_rows']=3
   if mode=='missingtotal':del b['review']['original_source_rows']
   if mode=='conflictingtotal':b['review']['original_source_rows']=3
   if mode=='booltotal':
    for d in m['datasets']:d['review']['original_source_rows']=True
   if mode=='missingpartition':del b['review']['partition']
   if mode=='duplicatepartition':b['review']['partition']=a['review']['partition']
   with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'同SHA'):self.ingest(m)
   with sqlite3.connect(self.path)as c:
    self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0);self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='gk_yfyd_bucket'").fetchone())
 def test_partition_samples_remain_source_three_percent_combined(self):
  points=self.dataset('gk_official_yfyd',n=100,prefix='p');bucket=self.dataset('gk_yfyd_bucket',n=1,prefix='b');bucket['review']['samples']=[]
  for d,label in [(points,'points'),(bucket,'bucket')]:d['review'].update(original_source_rows=101,partition=label)
  m={'sources':[copy.deepcopy(self.source)],'datasets':[points,bucket]}
  with self.assertRaisesRegex(ValueError,'同SHA合并抽样不足'):self.ingest(m)
  r=bucket['rows'][0];bucket['review']['samples']=[{'record_id':r['record_id'],'status':'approved','locator':r['locator']}];self.assertEqual(self.ingest(m)['inserted'],101)
 def test_late_bad_bucket_rolls_back_point_source_ddl_and_audit(self):
  m=self.bucket_pair();m['datasets'][1]['rows'][0]['data']['segment_n']=-1;before=self.snapshot()
  with self.assertRaises(ValueError):self.ingest(m)
  self.assertEqual(self.snapshot(),before)
  with sqlite3.connect(self.path)as c:
   self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0);self.assertEqual(c.execute('SELECT count(*) FROM storage_object').fetchone()[0],0);self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='gk_yfyd_bucket'").fetchone())
  with sqlite3.connect(self.audit)as c:self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='gk_official_original_evidence'").fetchone())

 def partial_image(self):
  m=copy.deepcopy(self.m);d=m['datasets'][0];removed=d['rows'].pop()
  d['review'].update(read_method='image',dual_read_equal=True,original_data_rows=3,extracted_rows=2,original_source_rows=3,partition='原图1明确两读一致的行',excluded_rows=[{'locator':removed['locator'],'reason':'两读仍不一致，原行不入库'}])
  d['review']['samples']=[s for s in d['review']['samples'] if s['record_id']!=removed['record_id']]
  return m
 def test_partial_image_keeps_exclusion_proof_and_accepted_values_only(self):
  m=self.partial_image();before=self.snapshot();self.assertEqual(self.ingest(m)['inserted'],2);self.assertEqual(self.snapshot(),before)
  with sqlite3.connect(self.path)as c:
   coverage=json.loads(c.execute("SELECT value FROM meta WHERE key LIKE 'gk_source_coverage:%'").fetchone()[0]);self.assertEqual(coverage['status'],'partial');self.assertEqual(coverage['missing_rows'][0]['row'],4);self.assertEqual(coverage['accepted_rows'],2)
  with sqlite3.connect(self.audit)as c:
   for (payload,)in c.execute('SELECT excerpt_locator_json FROM gk_official_original_evidence'):
    review=json.loads(payload)['review'];self.assertEqual(review['original_source_rows'],3);self.assertEqual(review['excluded_row_count'],1);self.assertEqual(len(review['excluded_rows_sha256']),64);self.assertNotIn('excluded_rows',review)
 def test_partial_image_rejects_missing_reason_duplicate_or_accepted_row(self):
  for change in ('no_reason','duplicate','accepted','wrong_sha','missing_total','wrong_total','bad_locator','text','not_equal'):
   with self.subTest(change=change):
    m=self.partial_image();d=m['datasets'][0];r=d['review'];e=r['excluded_rows'][0]
    if change=='no_reason':e['reason']=''
    elif change=='duplicate':r['excluded_rows'].append(copy.deepcopy(e));r['original_data_rows']=4;r['original_source_rows']=4
    elif change=='accepted':e['locator']=copy.deepcopy(d['rows'][0]['locator'])
    elif change=='wrong_sha':e['locator']['sha256']='b'*64
    elif change=='missing_total':r.pop('original_source_rows')
    elif change=='wrong_total':r['original_source_rows']=4
    elif change=='bad_locator':e['locator']['row']=True
    elif change=='text':r['read_method']='text'
    else:r['dual_read_equal']=False
    with self.assertRaises(ValueError):self.ingest(m)
 def test_partial_image_rejects_excluded_row_in_other_partition(self):
  m=self.partial_image();d=copy.deepcopy(m['datasets'][0]);d['review']['partition']='另一个原范围';d['rows'][0]['record_id']='other0';d['rows'][1]['record_id']='other1';d['review']['samples']=[{'record_id':r['record_id'],'status':'approved','locator':r['locator']}for r in d['rows']];m['datasets'].append(d)
  for ds in m['datasets']:ds['review']['original_source_rows']=6
  with self.assertRaisesRegex(ValueError,'排除行重复'):self.ingest(m)

 def test_filling_gap_preserves_old_business_and_audit_rows(self):
  self.ingest(self.partial_image())
  with sqlite3.connect(self.audit)as c:old=c.execute('SELECT * FROM gk_official_original_evidence ORDER BY record_id').fetchall()
  full=copy.deepcopy(self.m);full['datasets'][0]['review'].update(read_method='image',dual_read_equal=True)
  result=self.ingest(full);self.assertEqual(result['inserted'],1);self.assertEqual(result['existing'],2)
  with sqlite3.connect(self.audit)as c:self.assertEqual(c.execute('SELECT * FROM gk_official_original_evidence ORDER BY record_id LIMIT 2').fetchall(),old)
  with sqlite3.connect(self.path)as c:
   latest=json.loads(c.execute("SELECT value FROM meta WHERE key LIKE 'gk_source_coverage:%' ORDER BY rowid DESC LIMIT 1").fetchone()[0]);self.assertEqual(latest['accepted_rows'],3);self.assertEqual(latest['missing_rows'],[])

if __name__=='__main__':unittest.main()
