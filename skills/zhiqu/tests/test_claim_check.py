"""Independent mechanical tests for sentence manifest integrity (no semantic oracle)."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import claim_check as cc

class FixtureCase:
 def __init__(self,root):
  self.root=Path(root);self.case=json.loads((self.root/'case.json').read_text());self.evidence={'E1':{'excerpt':'学校要求初试总分达到300分。','grade':'官方','status':'retrieved','source':{'organization':'学校'}}};self.data={};self.contract={'sections':[{'id':'01','slots':[{'key':'body','condition':'always'}]}]}
 def nodes(self):return {'01':[{'slot':'body','ref':'narrative.json#/node'}]}
 def get_node(self,ref):return json.loads((self.root/'narrative.json').read_text())['node']
 def active(self,slot):return True
 def resolve(self,kind,path):
  if kind=='e' and path=='E1#/value':return 300
  if kind=='p':return '本人登记'
  raise KeyError(path)
 def expand(self,sentence,where):return sentence.replace('{{e:E1#/value}}','300')

class ClaimCheckTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.put('case.json',{'case_id':'T1','authoring':{'model':'writer-model','session_id':'writer-session'},'report_meta':{}})
  self.node('学校要求初试总分达到{{e:E1#/value}}分。')
  self.put('report_trace.json',{'artifacts':{}})
  p=patch('planning_workflow.PlanningCase',FixtureCase);p.start();self.addCleanup(p.stop)
  p=patch('claim_check.content_snapshot',lambda c:{n:cc.file_sha(c.root/n) for n in ('case.json','narrative.json')});p.start();self.addCleanup(p.stop)
  p=patch('planning_report.offer_gap_notice',lambda *a:'');p.start();self.addCleanup(p.stop)
 def put(self,name,obj):cc.write(self.root/name,obj)
 def node(self,text,refs=('E1',),**content):self.put('narrative.json',{'node':{'type':'analysis','evidence_refs':list(refs),'content':{'text':text,**content}}})
 def manifest(self):return cc.build(self.root,bind=True)
 def review(self,decision='支持',kind='事实',reason='学校原句明确要求初试总分达到300分。'):
  data=self.manifest();data['reviewer']={'independent':True,'session_id':'review-session','model':'reviewer-model'};data['reviewed_manifest_sha256']=data['manifest_sha256']
  for x in data['items']:x['review']={'decision':decision,'kind':kind,'reason':reason}
  self.put('claim_check.json',data);return data
 def errors(self,**kwargs):return cc.errors(self.root,**kwargs)
 def test_valid_independent_complete_manifest(self):
  self.review();self.assertEqual(self.errors(),[])
 def test_missing_manifest_is_error(self):self.assertTrue(any('缺逐句' in x for x in self.errors()))
 def test_direct_and_component_reference_inherit_excerpts(self):
  items=cc.extract(FixtureCase(self.root));self.assertEqual(items[0]['evidence_refs'],['E1']);self.assertEqual(items[0]['evidence'][0]['excerpt'],'学校要求初试总分达到300分。');self.assertEqual(items[0]['expanded_text'],'学校要求初试总分达到300分。')
  self.node('学校有相关要求。');self.assertEqual(cc.extract(FixtureCase(self.root))[0]['evidence_refs'],['E1'])
 def test_short_unreferenced_mandatory_and_numeric_sentences_extracted(self):
  self.node('必须。300分。',refs=());items=cc.extract(FixtureCase(self.root));self.assertEqual([x['text'] for x in items],['必须。','300分。'])
 def test_deleted_item_rejected_even_if_manifest_digest_updated(self):
  data=self.review();data['items']=[];data['manifest_sha256']=cc.digest([]);data['reviewed_manifest_sha256']=data['manifest_sha256'];self.put('claim_check.json',data);self.assertTrue(any('不完整' in x for x in self.errors()))
 def test_tampered_quote_or_new_sentence_invalidates_manifest(self):
  data=self.review();data['items'][0]['evidence'][0]['excerpt']='伪造摘录';self.put('claim_check.json',data);self.assertTrue(any('不完整' in x for x in self.errors()))
  self.review();self.node('学校要求初试总分达到300分。学校要求参加面试。');self.assertTrue(any('不完整' in x for x in self.errors()))
 def test_input_snapshot_detects_nonclaim_metadata_change(self):
  self.review();obj=cc.read(self.root/'case.json');obj['target_year']=2028;self.put('case.json',obj);self.assertTrue(any('输入快照' in x for x in self.errors()))
 def test_report_trace_and_actual_report_artifact_are_bound(self):
  (self.root/'report.md').write_text('报告正文');self.put('report_trace.json',{'artifacts':{'report.md':cc.file_sha(self.root/'report.md')}});self.review();self.assertEqual(self.errors(),[])
  (self.root/'report.md').write_text('改过的正文');self.assertTrue(any('报告已变更' in x for x in self.errors()))
  self.put('report_trace.json',{'artifacts':{}});self.assertTrue(any('未绑定当前报告' in x for x in self.errors()))
 def test_reviewer_must_be_independent_and_identified(self):
  for key,value in [('independent',False),('session_id',''),('model','')]:
   with self.subTest(key=key):
    d=self.review();d['reviewer'][key]=value;self.put('claim_check.json',d);self.assertTrue(any('独立会话' in x for x in self.errors()))
 def test_review_must_cover_current_manifest_and_have_reason(self):
  d=self.review();d['reviewed_manifest_sha256']='old';d['items'][0]['review']['reason']=' ';self.put('claim_check.json',d);issues=self.errors();self.assertTrue(any('未覆盖' in x for x in issues));self.assertTrue(any('具体理由' in x for x in issues))
 def test_unsupported_visible_fact_is_blocked(self):
  self.review(decision='不支持');self.assertTrue(any('不支持的句子须删除' in x for x in self.errors()))
 def test_unsupported_may_only_remain_as_explicit_inference(self):
  self.node('推测学校下一年仍采用相同要求。',refs=());self.review(decision='不支持',kind='推测',reason='以前年度要求仅能作为推测前提，当前要求待核。');self.assertEqual(self.errors(),[])
  self.node('学校下一年仍采用相同要求。',refs=());self.review(decision='不支持',kind='推测');self.assertTrue(any('须删除' in x for x in self.errors()))
 def test_partial_support_requires_rewrite_and_old_decision_is_retired(self):
  d=self.review(decision='部分支持');oldid=d['items'][0]['claim_id'];self.assertTrue(any('须改写' in x for x in self.errors()))
  self.node('学校要求达到300分。');new=self.manifest();self.assertIsNone(new['items'][0]['review']);self.assertIn(oldid,[x['claim_id'] for x in new['retired']])
 def test_unreferenced_fact_and_unbound_personal_fact_are_blocked(self):
  self.node('学校必须参加面试。',refs=());self.review();self.assertTrue(any('事实句没有证据' in x for x in self.errors()))
  self.review(kind='个人登记');self.assertTrue(any('本人事实没有登记' in x for x in self.errors()))
 def test_non_authored_source_endnotes_are_excluded(self):
  obj=cc.read(self.root/'narrative.json');obj['node']['type']='source_endnotes';self.put('narrative.json',obj);self.assertEqual(cc.extract(FixtureCase(self.root)),[])

 def test_section_title_and_factual_column_header_are_extracted(self):
  c=FixtureCase(self.root);c.data={'narrative.json':{'sections':{'01':{'title':'2027年报名必须符合要求'}}}}
  self.node('表格正文。',columns=['2027年必须面试'])
  rows=cc.extract(c);self.assertTrue(any(x['text']=='2027年报名必须符合要求' for x in rows));self.assertTrue(any(x['text']=='2027年必须面试' for x in rows))
 def test_same_known_author_and_reviewer_session_is_rejected(self):
  d=self.review();d['reviewer']['session_id']='writer-session';self.put('claim_check.json',d);self.assertTrue(any('写作会话相同' in x for x in self.errors()))
 def test_numeric_leaf_extracted_but_boolean_not_a_number(self):
  self.node('正文',number=300,enabled=True);rows=cc.extract(FixtureCase(self.root));self.assertTrue(any(x['text']=='300' for x in rows));self.assertFalse(any(x['text']=='True' for x in rows))
 def test_nonrendered_analysis_comment_is_excluded(self):
  self.node('学校必须采用999分。',kind='comment');self.assertEqual(cc.extract(FixtureCase(self.root)),[])

if __name__=='__main__':unittest.main()
