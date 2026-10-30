import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

SCRIPT=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts/zhiqu_db.py'
spec=importlib.util.spec_from_file_location('zhiqu_db',SCRIPT);db=importlib.util.module_from_spec(spec);spec.loader.exec_module(db)

class UnifiedQueries(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'fixture.sqlite';c=sqlite3.connect(self.path)
  c.executescript('''
CREATE TABLE institution(institution_id TEXT,name TEXT,moe_code TEXT,province TEXT,status TEXT,established TEXT,closed TEXT,successor_id TEXT);
CREATE TABLE institution_alias(institution_id TEXT,alias TEXT,province TEXT,year INTEGER,year_from INTEGER,year_to INTEGER);
CREATE TABLE institution_event(institution_id TEXT,name_before TEXT,name_after TEXT,effective TEXT,status TEXT,successor_id TEXT,source_id TEXT);
CREATE TABLE source(source_id TEXT,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT,archive_sha256 TEXT,archive_path TEXT,archive_status TEXT,retrieved TEXT);
CREATE TABLE ky_retest_line(record_id TEXT,institution_id TEXT,year INTEGER,college TEXT,program_code TEXT,program_name TEXT,total REAL,english REAL,politics REAL,direction TEXT,joint_program TEXT,special_plan TEXT,admission_route TEXT,study_mode TEXT,source_id TEXT,value_status TEXT,quarantine_reason TEXT,note TEXT,verification_status TEXT,src_locator TEXT,excerpt_locator_json TEXT);
CREATE VIEW ky_v_retest_line AS SELECT * FROM ky_retest_line WHERE quarantine_reason IS NULL;
CREATE TABLE gk_official_cutoff(institution_id TEXT,province TEXT,year INTEGER,major_code TEXT,plan_type TEXT,score REAL,source_id TEXT,value_status TEXT);
CREATE TABLE institution_profile(institution_id TEXT,year INTEGER,recommend_rate TEXT,n_master TEXT,n_phd TEXT,source_id TEXT,value_status TEXT,year_status TEXT);
CREATE TABLE comparability(scope TEXT,effective_year INTEGER,change TEXT,impact TEXT,source_id TEXT);
CREATE TABLE job_summary(position_id TEXT,region TEXT,year INTEGER,major_clause TEXT,headcount INTEGER,paid_applicants INTEGER,paid_per_seat REAL,source_id TEXT,application_source_id TEXT,value_status TEXT,excerpt TEXT,excerpt_kind TEXT);
CREATE TABLE wage_stat(region TEXT,year INTEGER,"group" TEXT,p50 REAL,unit TEXT,source_id TEXT,value_status TEXT,excerpt TEXT,excerpt_kind TEXT);
CREATE TABLE competition_stat(province TEXT,year INTEGER,"group" TEXT,n_jobs INTEGER,share_below_10 REAL,unit TEXT,source_id TEXT,value_status TEXT);
CREATE TABLE civil_major_summary(region TEXT,year INTEGER,major_name TEXT,share TEXT,source_major_code TEXT,source_id TEXT,value_status TEXT);
''')
  c.executemany('INSERT INTO institution VALUES (?,?,?,?,?,?,?,?)',[('1','甲大学','10001','江苏','在办',None,None,None),('2','旧学院','10002','江苏','转设','1999','2025','3'),('3','新大学','10003','江苏','在办','2026',None,None),('4','同名学校','10004','北京','在办',None,None,None),('5','同名学校','10005','上海','在办',None,None,None)])
  c.executemany('INSERT INTO institution_alias VALUES (?,?,?,?,?,?)',[('1','甲大','',None,None,None),('1','10001','',None,None,None),('1','旧甲大','',None,None,2025),('2','旧学院','',None,None,2025),('3','新大学','',None,2026,None),('4','同名','',None,None,None),('5','同名','',None,None,None)])
  c.execute("INSERT INTO institution_event VALUES ('2','旧学院','新大学','2025-07','转设','3','s')")
  c.executemany('INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?)',[('s','官方','甲大学研究生院','复试线','https://a.edu.cn/notice','https://a.edu.cn/a.pdf','abc','original.pdf','已存原件','2026-01-02'),('v','第三方整理','购买汇编','学校概况','','','','','未取到','2026-01-02')])
  for i,(year,code,total,direction,special,quarantine) in enumerate([(2025,'085404',310,'01','普通',None),(2026,'085404',320,'02','联培',None),(2026,'085410',330,'03','退役',None),(2026,'085404',999,'04','普通','隔离错误')]):
   c.execute('INSERT INTO ky_retest_line VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(i),'1',year,'计算机学院',code,'具体专业',total,None,None,direction,'联合单位' if special=='联培' else '无',special,'一志愿','全日制','s',json.dumps({'total':{'status':'官方原值'},'english':{'status':'原件缺失','reason':'未取得单科原文'}}),quarantine,'第1门政治/管理综合，未强配','未逐行核准','PDF第2页表1第3行','{}'))
  c.executemany('INSERT INTO gk_official_cutoff VALUES (?,?,?,?,?,?,?,?)',[('1','山东',2026,'0854','普通',600,'s','{}'),('1','山东',2026,'0854','中外合作',550,'s','{}')])
  c.execute("INSERT INTO institution_profile VALUES ('1',NULL,'0.586','10','2','v','{}','年份未记录')")
  c.execute("INSERT INTO comparability VALUES ('甲大学',2026,'考试科目改革','跨年分数不可直接比较','s')")
  c.execute('INSERT INTO job_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('j','浙江',2026,'计算机科学与技术',2,20,10,'s','v','{}','原表匿名岗位单元格','原表单元格摘录'))
  c.execute('INSERT INTO wage_stat VALUES (?,?,?,?,?,?,?,?,?)',('浙江·杭州',2022,'计算机专业人员',95000,'元/年','s','{"p50":"官方原值"}','{"原整理列":"95000"}','既有整理CSV逐字记录，非官网原文摘录'))
  c.execute('INSERT INTO competition_stat VALUES (?,?,?,?,?,?,?,?)',('浙江',2026,'计算机',100,.16,'缴费人数/招录人数','s','{"share_below_10":"推算"}'))
  c.execute('INSERT INTO civil_major_summary VALUES (?,?,?,?,?,?,?)',('广东',2026,'计算机科学与技术','30.7%','B080901','s','{"share":"推算"}'))
  c.commit();c.close()
 def tearDown(self):self.temp.cleanup()
 def school(self,*args,**kw):return db.query_school(*args,db=self.path,**kw)
 def program(self,*args,**kw):return db.query_program(*args,db=self.path,**kw)
 def test_alias_and_admission_code(self):
  self.assertEqual(self.school('甲大')['identity']['institution_id'],'1');self.assertEqual(self.school('10001')['identity']['institution_id'],'1')
 def test_research_primary_id_keeps_history_but_dated_alias_stays_dated(self):
  with sqlite3.connect(self.path) as c:
   c.execute("INSERT INTO institution VALUES ('82817','甲研究院',NULL,'北京',NULL,NULL,NULL,NULL)")
   c.executemany('INSERT INTO institution_alias VALUES (?,?,?,?,?,?)',[('82817','82817',None,2026,2026,2026),('82817','99999',None,2026,2026,2026)])
   c.row_factory=sqlite3.Row
   for original in c.execute("SELECT * FROM ky_retest_line WHERE record_id IN ('0','1')").fetchall():
    row=dict(original);row['record_id']='research-'+row['record_id'];row['institution_id']='82817'
    c.execute('INSERT INTO ky_retest_line('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',list(row.values()))
  years=lambda r:{x['context']['year'] for s in r['sections'] for x in s['rows'] if s['table'].startswith('ky_')}
  self.assertEqual(years(self.school('82817')),{2025,2026})
  self.assertEqual(years(self.school('82817',year=2025)),{2025})
  self.assertEqual(years(self.school('99999')),{2026})
  with self.assertRaises(db.QueryError):self.school('99999',year=2025)
 def test_ambiguous_never_picks_one(self):
  with self.assertRaises(db.QueryError):self.school('同名')
  self.assertEqual(self.school('同名',province='北京')['identity']['institution_id'],'4')
 def test_transfer_wrong_year_not_current_dictionary_bypass(self):
  with self.assertRaises(db.QueryError):self.school('旧学院',year=2026)
  with self.assertRaises(db.QueryError):self.school('新大学',year=2025)
  self.assertIn('旧学院',db.render_text(self.school('旧学院',year=2025)))
 def test_direct_id_terminal_year_guard(self):
  with self.assertRaises(db.QueryError):self.school('2',year=2026)
 def test_old_alias_no_year_filters_actual_business_year(self):
  r=self.program('旧甲大','0854');years={x['context']['year'] for s in r['sections'] for x in s['rows']};self.assertEqual(years,{2025})
 def test_program_prefix_preserves_scopes_and_excludes_quarantine(self):
  r=self.program('甲大','0854');rows=[x for s in r['sections'] for x in s['rows']];self.assertEqual(len(rows),3);self.assertEqual({x['context']['program_code'] for x in rows},{'085404','085410'});self.assertEqual({x['context']['direction'] for x in rows},{'01','02','03'});self.assertNotIn(999,{x['values']['total']['value'] for x in rows})
 def test_undergraduate_code_not_joined_to_postgraduate_code(self):
  r=self.program('甲大','0854');self.assertTrue(all(s['table'].startswith('ky_') for s in r['sections']))
 def test_plan_types_and_candidate_province_preserved(self):
  r=self.school('甲大',province='山东');s=next(x for x in r['sections'] if x['table']=='gk_official_cutoff');self.assertEqual(s['total'],2);self.assertEqual({x['context']['plan_type'] for x in s['rows']},{'普通','中外合作'})
 def test_partial_cutoff_exposes_original_missing_rows_in_default_query(self):
  with sqlite3.connect(self.path)as c:
   c.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
   value=dict(source_id='s',table_name='gk_official_cutoff',status='partial',original_rows=3,accepted_rows=2,missing_rows=[dict(page=2,table=1,row=9,reason='原图两读未一致')],missing_scope='续页未核')
   c.execute('INSERT INTO meta VALUES(?,?)',('gk_source_coverage:s:gk_official_cutoff:one',json.dumps(value)))
  result=self.school('甲大',province='山东');section=next(x for x in result['sections']if x['table']=='gk_official_cutoff')
  self.assertTrue(all(x['completeness']['missing_rows'][0]['row']==9 for x in section['rows']));text=db.render_text(result);self.assertIn('原表不完整',text);self.assertIn('页2/表1/行9',text)
 def test_every_value_has_grade_origin_id_status(self):
  r=self.program('甲大','0854');v=r['sections'][0]['rows'][0]['values']['total'];self.assertEqual((v['grade'],v['publisher'],v['source_id']),('官方','甲大学研究生院','s'));self.assertEqual(v['value_status']['status'],'官方原值')
 def test_null_missing_original_not_unpublished(self):
  text=db.render_text(self.program('甲大','0854'));self.assertIn('原件缺失〔官方',text);self.assertNotIn('：未公布',text)
 def test_pagination_explicit_and_exact_total(self):
  r=self.program('甲大','0854',limit=1,offset=1);s=r['sections'][0];self.assertEqual((s['total'],s['returned'],s['truncated'],s['offset']),(3,1,1,1));self.assertIn('后续1行未显示',db.render_text(r))
 def test_comparability_warning(self):self.assertTrue(any('跨年口径' in x for x in self.program('甲大','0854')['warnings']))
 def test_third_party_ratio_not_auto_integer_or_probability(self):
  r=self.school('甲大');s=next(x for x in r['sections'] if x['table']=='institution_profile');v=s['rows'][0]['values']['recommend_rate'];self.assertEqual(v['value'],'0.586');self.assertEqual(v['grade'],'第三方整理');self.assertIn('0.586',db.render_text(r))
 def test_source_detail_and_excerpt_kind(self):
  r=db.query_source('s',db=self.path);text=db.render_text(r);self.assertIn('https://a.edu.cn/a.pdf',text);self.assertIn('abc',text);self.assertIn('2026-01-02',text);self.assertIn('PDF第2页',text)
 def test_jobs_regions_units_and_not_person_probability(self):
  r=db.query_jobs(region='浙江',major='计算机',db=self.path);text=db.render_text(r);self.assertIn('元/年',text);self.assertIn('非个人',text);self.assertIn('在岗',text);self.assertNotIn('录用概率为',text)
 def add_notice(self,region='郑州市'):
  with sqlite3.connect(self.path)as c:
   c.execute('CREATE TABLE recruitment_notice(record_id TEXT,region TEXT,year INTEGER,title TEXT,source_id TEXT,note TEXT,value_status TEXT)')
   c.execute('INSERT INTO recruitment_notice VALUES(?,?,?,?,?,?,?)',('notice',region,2027,'财务助理','s','月薪范围4K-6K','{}'))
 def test_notice_only_does_not_claim_survey_or_competition(self):
  self.add_notice();r=db.query_jobs(region='郑州市',major='财务',year=2027,db=self.path)
  self.assertEqual([s['table']for s in r['sections']],['recruitment_notice'])
  warnings=' '.join(r['warnings']);self.assertIn('不是在岗群体工资调查',warnings);self.assertIn('不代表当前仍在招聘、本人资格或个人offer',warnings)
  self.assertNotIn('原调查在岗群体分位值',warnings);self.assertNotIn('报名人数/名额',warnings);self.assertIn('不构成报考资格认定',warnings)
 def test_mixed_notice_and_wage_have_separate_scope_warnings(self):
  self.add_notice(region='浙江·杭州');r=db.query_jobs(region='杭州',db=self.path)
  self.assertEqual({s['table']for s in r['sections']},{'wage_stat','recruitment_notice'})
  self.assertTrue(any('工资调查块是原调查在岗群体分位值'in x for x in r['warnings']))
  self.assertTrue(any('招聘公告块保留岗位原文报价'in x for x in r['warnings']))
  self.assertFalse(any('报名人数/名额'in x for x in r['warnings']))
 def test_no_results_do_not_assert_data_types_present(self):
  r=db.query_jobs(region='无匹配地区',major='财务',db=self.path);self.assertEqual(r['sections'],[])
  self.assertFalse(any('分位值'in x or '报名人数/名额'in x or '招聘公告块'in x for x in r['warnings']))
  self.assertTrue(any('未命中不代表当地没有岗位'in x for x in r['warnings']))
 def test_type_caveats_follow_matching_block_even_after_last_page(self):
  self.add_notice();r=db.query_jobs(region='郑州市',year=2027,db=self.path,offset=1)
  self.assertEqual((r['sections'][0]['total'],r['sections'][0]['returned']),(1,0))
  self.assertTrue(any('招聘公告块'in x for x in r['warnings']));self.assertFalse(any('分位值'in x for x in r['warnings']))
 def test_percent_string_preserved(self):
  r=db.query_jobs(region='广东',major='计算机',db=self.path);v=r['sections'][0]['rows'][0]['values']['share'];self.assertEqual(v['value'],'30.7%')
 def test_readonly_bytes_unchanged_and_query_only(self):
  before=hashlib.sha256(self.path.read_bytes()).digest();self.school('甲大');db.query_jobs(db=self.path)
  with db._open('education',self.path) as (c,p):
   with self.assertRaises(sqlite3.OperationalError):c.execute('DELETE FROM data.source')
  self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).digest())
 def test_cli_default_table_and_explicit_json(self):
  out=io.StringIO()
  with contextlib.redirect_stdout(out):db.main(['program','甲大','0854','--db',str(self.path),'--limit','1'])
  self.assertIn('适用范围 | 数值',out.getvalue());self.assertFalse(out.getvalue().startswith('{'))
  out=io.StringIO()
  with contextlib.redirect_stdout(out):db.main(['program','甲大','0854','--db',str(self.path),'--json'])
  self.assertEqual(json.loads(out.getvalue())['query'],'program')
 def test_unclosed_location_excluded_and_counted(self):
  c=sqlite3.connect(self.path);c.execute("UPDATE ky_retest_line SET verification_status='原文定位未闭合' WHERE record_id='2'");c.commit();c.close()
  r=self.program('甲大','0854');self.assertEqual(r['sections'][0]['total'],2);self.assertTrue(any('未闭合 1 行' in x for x in r['warnings']))
 def test_ordinary_rename_same_id_shows_chain(self):
  c=sqlite3.connect(self.path);c.execute("INSERT INTO institution_event VALUES ('1','旧甲大','甲大学','2026-01','更名','1','s')");c.commit();c.close()
  r=self.school('旧甲大',year=2026);self.assertEqual(r['identity']['institution_id'],'1');self.assertTrue(any('历史名称' in x for x in r['warnings']))
 def test_source_compiled_excerpt_marked_not_original(self):
  text=db.render_text(db.query_source('s',db=self.path,domain='employment',limit=10));self.assertIn('非官网原文摘录',text)
 def test_paid_ratio_names_both_input_sources(self):
  r=db.query_jobs(region='浙江',major='计算机',db=self.path);v=r['sections'][0]['rows'][0]['values']['paid_per_seat'];self.assertEqual(v['source_id'],'s + v');self.assertEqual(v['grade'],'第三方整理')
 def test_legacy_generic_subjects_not_called_politics_or_math(self):
  c=sqlite3.connect(self.path);c.execute("UPDATE ky_retest_line SET note='原表单科=100/单科>100，不区分政治英语',politics=35,english=35 WHERE record_id='1'");c.commit();c.close()
  r=self.program('甲大','0854',year=2026);v=next(x for x in r['sections'][0]['rows'] if x['record_id']=='1')['values'];self.assertEqual(v['politics']['value'],35);self.assertIn('历史槽位',v['politics']['display_label']);text=db.render_text(r);self.assertNotIn('原列政治/首科（须核口径）：35',text)
 def test_postgraduate_warning_does_not_use_gaokao_reform(self):
  c=sqlite3.connect(self.path);c.execute('ALTER TABLE comparability ADD COLUMN domain TEXT');c.execute("UPDATE comparability SET domain='高考'");c.commit();c.close()
  self.assertFalse(any('跨年口径' in x for x in self.program('甲大','0854')['warnings']))
 def test_admission_province_not_school_location_disambiguation(self):
  c=sqlite3.connect(self.path);c.execute('ALTER TABLE institution_alias ADD COLUMN kind TEXT');c.executemany('INSERT INTO institution_alias VALUES (?,?,?,?,?,?,?)',[('1','8888','江苏',2025,None,None,'省招生代码'),('4','8888','江苏',2026,None,None,'省招生代码')]);c.commit();c.close()
  with self.assertRaises(db.QueryError):self.school('8888',province='江苏')
  self.assertEqual(self.school('8888',province='江苏',year=2026)['identity']['institution_id'],'4')
 def test_continuation_actual_quote_and_hash_binding(self):
  root=Path(self.temp.name);folder=root/'shared/data';folder.mkdir(parents=True)
  evidence={'canonical_row_sha256':'bound','continuation_actual_evidence':{'field_excerpt':{'header':['学院','专业','总分'],'raw_row':['甲学院','085404','320']}}}
  path=folder/'line_evidence.jsonl';path.write_text(json.dumps(evidence,ensure_ascii=False)+'\n')
  loc={'path':'shared/data/line_evidence.jsonl','jsonl_line':1,'sha256':'bound'}
  with mock.patch.object(db,'ROOT',root),mock.patch.object(db,'SHARED',root/'shared'):
   self.assertEqual(db._original_excerpt(loc)['continuation_actual_evidence'],evidence['continuation_actual_evidence'])
   self.assertIn('指纹不符',db._original_excerpt(dict(loc,sha256='wrong'))['摘录状态'])
 def test_default_text_displays_verified_image_locator(self):
  refs={'root_verified_image_references':[{'method':'读图','locator':'第2页表1','sha256':'image-real-sha','source_id':'image-source'}]}
  c=sqlite3.connect(self.path);c.execute('UPDATE ky_retest_line SET excerpt_locator_json=? WHERE record_id=?',(json.dumps(refs,ensure_ascii=False),'1'));c.commit();c.close()
  text=db.render_text(self.program('甲大','0854',year=2026),full=True);self.assertIn('读图定位',text);self.assertIn('image-real-sha',text);self.assertIn('第2页表1',text)
 def test_tuition_raw_is_not_unit_or_currency_inference(self):
  self.assertNotIn('5460',db._unit('gk_plan_entry','tuition',{'tuition_raw':'5460'}))
  self.assertIn('币种与计费周期未标明',db._unit('gk_plan_entry','tuition',{'tuition_raw':'5460'}))
 def test_unknown_null_not_mislabeled_source_omission(self):
  v={'value':None,'value_status':{'status':'未标记（待核）'},'grade':'官方','publisher':'甲大','source_id':'s'}
  self.assertNotIn('来源未提供',db._value_text(v))
 def test_invalid_pagination_and_code_rejected(self):
  with self.assertRaises(db.QueryError):self.school('甲大',limit=0)
  with self.assertRaises(db.QueryError):self.program('甲大',"0854';DELETE")

 def test_retest_scope_and_generic_components_are_explicit(self):
  with sqlite3.connect(self.path) as c:
   c.execute('CREATE TABLE ky_line_scope_context(record_id TEXT PRIMARY KEY,direction TEXT,joint_program TEXT,admission_route TEXT,scope_raw TEXT,source_id TEXT)')
   c.execute('CREATE TABLE ky_line_component(record_id TEXT,component TEXT,value REAL,source_id TEXT,src_locator TEXT,value_status TEXT)')
   c.execute("INSERT INTO ky_line_scope_context VALUES ('1','02软件方向','某校联培基地','一志愿','原表02方向','s')")
   c.execute('INSERT INTO ky_line_component VALUES (?,?,?,?,?,?)',('1','single_100',40,'s',json.dumps({'page':2,'table':1,'row':3}),json.dumps({'status':'官方原值'})))
   c.execute('INSERT INTO ky_line_component VALUES (?,?,?,?,?,?)',('1','exam_1',80,'s','{}',json.dumps({'status':'官方原值'})))
   proof={'src_page':2,'src_table':'原表1','src_row':3,'excerpt':{'总分原格':'320'},'locator':{'sha256':'a'*64,'pdf_page':2,'pdf_row':3}}
   c.execute('UPDATE ky_retest_line SET excerpt_locator_json=? WHERE record_id=?',(json.dumps(proof),'1'))
  result=self.program('甲大','085404',year=2026)
  row=next(r for sec in result['sections'] for r in sec['rows'] if r['record_id']=='1')
  self.assertEqual(row['context']['direction'],'02软件方向')
  self.assertEqual(row['context']['joint_program'],'某校联培基地')
  self.assertEqual(row['values']['single_100']['value'],40)
  self.assertEqual(row['values']['exam_1']['display_label'],'原表科目槽1')
  self.assertIsNone(row['values']['politics']['value'])
  self.assertEqual(row['excerpt'],{'总分原格':'320'})
  self.assertEqual(row['locator']['src_page'],2)
  self.assertEqual(row['values']['single_100']['source_id'],'s')
  self.assertIn('原表科目槽1',db.render_text(result))

 def test_official_manifest_scope_without_public_csv_keeps_batch_and_audit_binding(self):
  with sqlite3.connect(self.path) as c:
   c.execute('ALTER TABLE gk_official_cutoff ADD COLUMN src TEXT')
   c.execute("UPDATE gk_official_cutoff SET src='manifest-row-'||rowid")
   c.execute('CREATE TABLE official_cutoff_scope(source_id TEXT,public_record TEXT,scope_json TEXT,locator_json TEXT)')
   c.execute('CREATE TABLE gk_official_original_evidence(record_id TEXT,table_name TEXT,source_id TEXT,excerpt_locator_json TEXT)')
   for i in (1,2):
    src='manifest-row-'+str(i);rid='audit-'+str(i)
    c.execute('INSERT INTO official_cutoff_scope VALUES (?,?,?,?)',('s',src,json.dumps({'source_batch_raw':'本科普通批','source_group_code':'0'+str(i),'source_subject_requirements':'物理'}),json.dumps({'record_id':rid,'audit_table':'gk_official_original_evidence'})))
    c.execute('INSERT INTO gk_official_original_evidence VALUES (?,?,?,?)',(rid,'gk_official_cutoff','s',json.dumps({'business_key':{'source_id':'s','src':src},'excerpt':['原表总分'],'locator':{'sha256':'a'*64,'row':i}})))
  section=next(s for s in self.school('甲大')['sections'] if s['table']=='gk_official_cutoff')
  self.assertEqual({r['context']['source_group_code'] for r in section['rows']},{'01','02'})
  self.assertTrue(all(r['context']['source_batch_raw']=='本科普通批' for r in section['rows']))
  self.assertEqual(section['rows'][0]['excerpt'],['原表总分'])
  with sqlite3.connect(self.path) as c:c.execute("UPDATE gk_official_original_evidence SET source_id='v' WHERE record_id='audit-1'")
  with self.assertRaisesRegex(db.QueryError,'审计记录不匹配'):self.school('甲大')

 def test_new_official_plan_is_queryable_with_original_scope_and_quality(self):
  with sqlite3.connect(self.path) as c:
   c.execute('CREATE TABLE gk_official_plan(record_id TEXT,institution_id TEXT,province TEXT,year INTEGER,subject TEXT,batch TEXT,group_code TEXT,major_code TEXT,major_name TEXT,gender TEXT,subject_requirements TEXT,scope_raw TEXT,plan_n INTEGER,source_id TEXT,value_status TEXT)')
   c.execute('CREATE TABLE gk_official_original_evidence(record_id TEXT,table_name TEXT,source_id TEXT,excerpt_locator_json TEXT)')
   c.execute('INSERT INTO gk_official_plan VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('p','1','内蒙古',2026,'历史类','本科提前批B段','001','23','原招生专业','男','思想政治','仅提前批意向类别初始计划',2,'s',json.dumps({'plan_n':{'status':'官方原值','reason':'原格'}})))
   proof={'business_key':{'record_id':'p'},'scope':{'intention_category_raw':'公安'},'excerpt':['原计划2人'],'locator':{'sha256':'b'*64,'html_row':2}}
   c.execute('INSERT INTO gk_official_original_evidence VALUES (?,?,?,?)',('p','gk_official_plan','s',json.dumps(proof)))
  section=next(s for s in self.school('甲大')['sections'] if s['table']=='gk_official_plan')
  row=section['rows'][0]
  self.assertEqual(row['values']['plan_n']['value'],2)
  self.assertEqual(row['values']['plan_n']['grade'],'官方')
  self.assertEqual(row['context']['gender'],'男')
  self.assertIn('公安',row['context']['scope_raw'])
  self.assertEqual(row['excerpt'],['原计划2人'])
  with sqlite3.connect(self.path) as c:c.execute("DELETE FROM gk_official_original_evidence WHERE record_id='p'")
  with self.assertRaisesRegex(db.QueryError,'原文审计记录不匹配'):self.school('甲大')

if __name__=='__main__':unittest.main()
