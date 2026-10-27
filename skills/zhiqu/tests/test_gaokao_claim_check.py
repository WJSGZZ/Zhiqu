"""Database-to-report claims stay pending until a separate session reviews them."""
import json,sys,tempfile,unittest,shutil
from pathlib import Path
from unittest.mock import patch
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
import claim_check as cc,case_check
from decision_evidence import validate_evidence

class GaokaoClaimTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'2027-GK-0001';self.root.mkdir();(self.root/'profile.txt').write_text('虚构画像')
  self.put('case.json',{'case_id':self.root.name,'kind':'gaokao','authoring':{'model':'writer','session_id':'author'}})
  self.put('profile_snapshot.json',{'source':'模拟问卷'})
  self.put('report.json',{'meta':{'year':2027,'prob_grade':'D'},'summary':{'headline':'若实际位次约60000，先比较愿意读的专业。'},'directions':[{'name':'计算机','counter':['招生计划未取得，不能认定可报。']}], 'todo':[['预算','每年学费上限6000元，原标准未取得。']], 'sources':[['历史最低位次','http://www.hebeea.edu.cn/c/old.html','2026-10-27']], 'source_details':{'G001':{'excerpt':'原数格60000','grade':'第三方整理','status':'provided','scope':'2024河北物理本科参照'}},'claim_evidence_refs':{'report.json#/summary':['G001'],'result.json#/list':['G001']}})
  self.put('result.json',{'params':{'target_year':2027},'list':[{'order':1,'name':'测试大学·计算机科学与技术','code':'0001','major_code':'01','tag':'稳','expected_cut_rank':80000,'sigma':0.2,'p_clear':.8,'p_land':.7}]})
  self.put('report_trace.json',{'artifacts':{}})
 def put(self,n,d):cc.write(self.root/n,d)
 def manifest(self):return cc.build(self.root,bind=True)
 def test_gaokao_build_bind_needs_no_planning_case_files(self):
  data=self.manifest();self.assertTrue(data['items']);self.assertTrue(all(x['review']is None for x in data['items']));self.assertIsNone(data['reviewer']);self.assertEqual(cc.errors(self.root,require_review=False),[])
 def test_actual_report_components_and_generated_rows_are_extracted(self):
  items=self.manifest()['items'];locations=[x['location']for x in items]
  for prefix in ['report.json#/summary','report.json#/directions','report.json#/todo','result.json#/list','result.json#/entry_sheet']:self.assertTrue(any(x.startswith(prefix)for x in locations),prefix)
  self.assertTrue(any('rendered_interval' in x['location'] for x in items));self.assertTrue(any(x['text']=='80000'for x in items));self.assertFalse(any(x['text']in ['0.8','0.7']for x in items))
 def test_source_excerpts_attached_without_guessing_official_from_url(self):
  items=self.manifest()['items'];x=next(x for x in items if x['location'].startswith('report.json#/summary'));self.assertEqual(x['evidence'][0]['excerpt'],'原数格60000');self.assertEqual(x['evidence'][0]['grade'],'第三方整理')
  r=cc.read(self.root/'report.json');r.pop('source_details');self.put('report.json',r);x=next(x for x in self.manifest()['items']if x['location'].startswith('report.json#/summary'));self.assertIsNone(x['evidence'][0]['grade']);self.assertEqual(x['evidence'][0]['excerpt'],'')
 def test_report_edit_and_pdf_edit_invalidate_manifest(self):
  (self.root/'report.pdf').write_bytes(b'original');self.put('report_trace.json',{'artifacts':{'report.pdf':cc.file_sha(self.root/'report.pdf')}});self.manifest();r=cc.read(self.root/'report.json');r['todo'].append(['新事实','必须达到650分']);self.put('report.json',r);self.assertTrue(any('不完整'in e or'过期'in e for e in cc.errors(self.root,require_review=False)))
  self.manifest();(self.root/'report.pdf').write_bytes(b'changed');self.assertTrue(any('报告已变更'in e for e in cc.errors(self.root,require_review=False)))
 def test_delivery_cannot_silently_use_stage7(self):
  with self.assertRaisesRegex(ValueError,'阶段8'):case_check.run(self.root,7,delivery=True)
 def test_pending_gaokao_claims_are_not_independent_approval(self):
  self.manifest();errors=cc.errors(self.root);self.assertTrue(any('独立会话'in e for e in errors));self.assertTrue(any('未覆盖'in e for e in errors))
 def test_inputs_changed_after_extraction_expire_snapshot(self):
  self.put('rules_check.json',{'year':2026});self.manifest();self.put('rules_check.json',{'year':2027});self.assertTrue(any('输入快照'in e for e in cc.errors(self.root,require_review=False)))

class RecordedHTTPProvenanceTests(unittest.TestCase):
 def item(self,url):return {'status':'pending','year':2027,'source':url,'hard_conditions':[{'name':'2027专业选科','status':'unknown','source':url}],'unresolved':['仅有2026登记，2027原文未取得']}
 def test_recorded_official_http_is_preserved_as_pending(self):validate_evidence(self.item('http://www.hebeea.edu.cn/c/2026-06-17/493051.html'),2027)
 def test_invalid_or_credential_urls_not_accepted(self):
  for url in ['javascript:alert(1)','file:///tmp/evidence','https://','http://name:secret@example.edu.cn/','http://bad host/']:
   with self.subTest(url=url),self.assertRaises(ValueError):validate_evidence(self.item(url),2027)

if __name__=='__main__':unittest.main()

class DatabaseReplayAndShapeTests(unittest.TestCase):
 def sample(self):
  root=SCRIPTS.parent/'examples/2026-GK-R01';r=cc.read(root/'result.json');return r,(SCRIPTS.parent/r['params']['csv']).read_bytes()
 def test_replay_preserves_and_checks_source_fields(self):
  import csv,io,copy
  from verification_calculations import recompute_gaokao
  result,source=self.sample();rows=list(csv.DictReader(io.StringIO(source.decode('utf-8-sig'))));fact={'2025':{'rank':{'value':123,'grade':'第三方整理','source_id':'vendor-test'}}}
  for row in rows:row['source_grade']='第三方整理·内部未核';row['data_provenance']=json.dumps(fact,ensure_ascii=False)
  out=io.StringIO();w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
  for item in result['list']:item['source_grade']='第三方整理·内部未核';item['data_provenance']=copy.deepcopy(fact)
  self.assertEqual(recompute_gaokao(result,out.getvalue().encode())['list'],result['list'])
  result['list'][0]['data_provenance']['2025']['rank']['grade']='官方'
  with self.assertRaisesRegex(ValueError,'list'):recompute_gaokao(result,out.getvalue().encode())
 def test_historical_codes_only_change_database_sheet(self):
  import report,csv,copy
  r,_=self.sample();before=copy.deepcopy(r)
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'sheet.csv';report.write_sheet(r,p);self.assertNotIn('代码适用年份与状态',p.read_text())
   r['list'][0]['data_provenance']={'2025':{'rank':{'value':1,'source_id':'old','grade':'第三方整理'}}};r['params']['target_year']=2027
   report.write_sheet(r,p)
   with p.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
   self.assertIn('2025年历史参照',rows[0]['代码适用年份与状态']);self.assertIn('不能直接填报',rows[0]['代码适用年份与状态'])
 def test_missing_research_only_allowed_as_explicit_pending_simulation(self):
  import copy
  from check_report import check_sections
  root=SCRIPTS.parent/'examples/2027-GK-S01';rep=cc.read(root/'report.json');result=cc.read(root/'result.json');rep['meta']['mode']='simulation';rep['research_status']='pending';rep['research_gap_reason']='不联网；库内未留存原文'
  for x in rep['research']:x['sources']=[];x['items']=[['培养方案','未取到：库内没有原文，不能编造','未取到：待原文']]
  self.assertEqual(check_sections(rep,result),[])
  rep['meta']['mode']='formal';self.assertTrue(any('院校'in e or'调研'in e for e in check_sections(rep,result)))
 def test_renderer_shapes_checked_before_generation(self):
  from check_report import check_sections
  rep=cc.read(SCRIPTS.parent/'examples/2027-GK-S01/report.json')
  for key,value,word in [('news',[['a','b','c']],'news'),('questions',[['a','b']],'questions'),('todo',[['a','b','c']],'todo'),('methods',[{'title':'数据','paragraphs':['not rendered']}],'paras')]:
   changed=dict(rep);changed[key]=value;self.assertTrue(any(word in x for x in check_sections(changed)))
