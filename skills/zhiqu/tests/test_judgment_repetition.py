"""Literal whole-reasoning copies, not automated semantic comparison."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import profile_store as ps
from planning_workflow import PlanningCase

class JudgmentRepetitionTests(unittest.TestCase):
 def make(self,kind='grad',sealed=True):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
  data={'zhiqu':kind,'schema':1,'问卷':ps.HEADERS[kind],'form':'synthetic','filled_at':'2026-10-31T18:00:00+08:00','sections':[{'title':'模拟','items':[{'id':'more','q':'补充','a':'虚构最小原答','status':'已答'}]}],'rank':[],'derived':{},'未填的必答题':[]}
  if sealed:data.update(collapsed=[],counts={'visible':1,'answered':1});data['checksum']=ps.checksum(data)
  else:data['sections'][0]['items'][0].pop('status')
  cid=ps.new_id(root,kind,2028,'simulation');ps.ingest(root,cid,json.dumps(data,ensure_ascii=False));p=root/cid;ps.prepare(p)
  reason={'supports':['愿调查'],'counters':['资格待核'],'costs':'资金待核','fallback':'其他路径','switch_conditions':['新证据后重排']}
  judgments=[dict(id='J'+str(i),candidate_id='P'+str(i),checkpoint='2026-11-21',**copy.deepcopy(reason))for i in [1,2]]
  (p/'judgment.json').write_text(json.dumps({'schema_version':1,'matrix':{'options':['P1','P2']},'candidates':judgments,'recommendation':{'primary':['P1'],'backup':['P2']}}))
  (p/'candidates.json').write_text(json.dumps({'paths':[{'id':x}for x in ['P1','P2','excluded']]}))
  return PlanningCase(p)
 def test_sealed_paths_reject_whole_five_part_reasoning_copy(self):
  for kind in ['grad','career']:
   c=self.make(kind);self.assertTrue(c.judgment_repetition_errors());c.stage7();self.assertTrue(any('五项判断完全相同'in e for e in c.errors))
 def test_common_constraint_does_not_require_five_distinct_fields(self):
  c=self.make();c.data['judgment.json']['candidates'][1]['costs']='求职空窗与搬迁支出未核'
  self.assertEqual(c.judgment_repetition_errors(),[])
 def test_whitespace_does_not_disguise_a_copied_argument(self):
  c=self.make();c.data['judgment.json']['candidates'][1]['costs']=' 资金\n待核 '
  self.assertTrue(c.judgment_repetition_errors())
 def test_unsealed_migration_retains_frozen_legacy_analysis(self):
  self.assertEqual(self.make(sealed=False).judgment_repetition_errors(),[])
 def test_inactive_audit_reason_is_not_an_active_comparison_copy(self):
  c=self.make();c.data['judgment.json']['candidates'][1]['costs']='另一路求职开支待核'
  inactive=copy.deepcopy(c.data['judgment.json']['candidates'][0]);inactive['candidate_id']='excluded'
  c.data['judgment.json']['candidates'].append(inactive)
  self.assertEqual(c.judgment_repetition_errors(),[])
 def test_text_container_and_chinese_punctuation_whitespace_do_not_hide_copy(self):
  c=self.make();a,b=c.data['judgment.json']['candidates'];a['costs']='资金，待核';b['costs']='资金，\n待核';b['supports']='愿调查'
  self.assertTrue(any('五项判断完全相同'in e for e in c.judgment_repetition_errors()))
 def test_bad_reason_shapes_are_clear_errors_and_english_words_remain_distinct(self):
  for bad in [{},[1],None]:
   c=self.make();c.data['judgment.json']['candidates'][1]['costs']=bad
   self.assertTrue(any('须为非空文字'in e for e in c.judgment_repetition_errors()))
  c=self.make();c.data['judgment.json']['candidates'][0]['costs']='not able';c.data['judgment.json']['candidates'][1]['costs']='notable'
  self.assertEqual(c.judgment_repetition_errors(),[])
 def test_duplicate_id_cannot_hide_a_missing_active_judgment(self):
  c=self.make();c.data['judgment.json']['candidates'][1]['candidate_id']='P1'
  errors=c.judgment_repetition_errors();self.assertTrue(any('P1'in e and '恰有一条'in e for e in errors));self.assertTrue(any('P2'in e and '恰有一条'in e for e in errors))
 def test_unknown_judgment_id_is_not_an_audit_escape(self):
  c=self.make();c.data['judgment.json']['candidates'][1]['costs']='另一路开支'
  unknown=copy.deepcopy(c.data['judgment.json']['candidates'][0]);unknown['candidate_id']='not-registered'
  c.data['judgment.json']['candidates'].append(unknown)
  self.assertTrue(any('未登记候选'in e for e in c.judgment_repetition_errors()))
