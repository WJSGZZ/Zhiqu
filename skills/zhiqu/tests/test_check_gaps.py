"""Regression for expiry, source authentication, reader probability and review status."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from claim_guards import personal_probability_errors
from planning_workflow import PlanningCase,read,review_errors
ROOT=SCRIPTS.parents[2]

class PersonalProbabilityTests(unittest.TestCase):
 def test_affirmative_variants(self):
  for text in ['你有80%的机会。','你的把握是八成。','你考上的可能性是三分之二。','这群人一半录取，因此你也有一半机会。','您的录取概率为80％。','你被录取的可能性就是一半。','你考上的机会超过一半。']:
   with self.subTest(text=text):self.assertTrue(personal_probability_errors(text))
 def test_denials_and_group_statistics(self):
  for text in ['这不是你个人的录取概率。','八成是群体比例，这不是你个人的录取概率。','群体比例为80%，不代表你有80%的机会。','群体录取比例80%，不能据此说你有八成机会。','群体录取比例80%，仍需核实样本。','你需要核对条件，学校有八成学生继续深造。']:
   with self.subTest(text=text):self.assertFalse(personal_probability_errors(text))
 def test_denial_does_not_hide_another_positive_claim(self):
  self.assertTrue(personal_probability_errors('这不是你个人的录取概率，而是你有80%的机会。'))
 def test_reference_is_expanded_before_probability_check(self):
  c=PlanningCase(ROOT/'skills/zhiqu-grad/examples/2027-YJ-S01')
  e=next(e for e in c.evidence.values() if type(e.get('value')) in (int,float))
  self.assertTrue(any('个人概率' in x for x in c.numeric_errors('你的机会是{{e:'+e['id']+'#/value}}%。')))

class EvidenceExpiryTests(unittest.TestCase):
 def case(self):return PlanningCase(ROOT/'skills/zhiqu-grad/examples/2027-YJ-S01')
 def test_expired_before_asof_is_rejected_at_stage5(self):
  c=self.case();e=next(iter(c.evidence.values()));e['retrieved_on']='2026-08-01';e['review_due']='2026-08-02';c.stage5()
  self.assertTrue(any('证据复核期限早于报告as_of' in x for x in c.errors))
 def test_missing_asof_uses_generation_date_at_evidence_gate(self):
  c=self.case();c.case['context'].pop('as_of');e=next(iter(c.evidence.values()));e['retrieved_on']='2000-01-01';e['review_due']='2000-01-02';c.stage5()
  self.assertTrue(any('证据复核期限早于报告as_of' in x for x in c.errors))
 def test_equal_due_is_valid_and_future_due_is_valid(self):
  for due in ['2026-10-19','2027-08-31']:
   c=self.case();c.case['context']['as_of']='2026-10-19';e=next(iter(c.evidence.values()));e['review_due']=due;c.stage5()
   self.assertFalse(any('证据复核期限早于报告as_of' in x for x in c.errors))
 def test_generation_stops_before_renderer_for_expired_evidence(self):
  import planning_report
  import shutil
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'2027-YJ-S01';shutil.copytree(ROOT/'skills/zhiqu-grad/examples/2027-YJ-S01',root)
   obj=read(root/'evidence.json');obj['items'][0].update(retrieved_on='2026-08-01',review_due='2026-08-02');(root/'evidence.json').write_text(json.dumps(obj))
   with patch('render_report._print_pdf',side_effect=AssertionError('renderer must not run')):
    with self.assertRaisesRegex(ValueError,'证据复核期限早于报告as_of'):planning_report.generate(root,profile_version=read(root/'case.json')['report_profile']['file'])

class ReviewStatusTests(unittest.TestCase):
 def errors_for(self,status,include=True):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);obj={'status':status} if include else {}; (root/'review.json').write_text(json.dumps(obj));return review_errors(root)
 def test_unknown_or_nonstring_status_rejected(self):
  for status in ['passed','ready',None,123]:self.assertTrue(any('review.json.status' in x for x in self.errors_for(status)))
 def test_documented_statuses_and_missing_are_not_status_errors(self):
  for status in ['draft','self_assessed','awaiting_independent_review','approved','changes_required']:
   self.assertFalse(any('review.json.status' in x for x in self.errors_for(status)))
  self.assertFalse(any('review.json.status' in x for x in self.errors_for(None,False)))
class OfficialSourceTests(unittest.TestCase):
 def setUp(self):
  self.e={'id':'E1','grade':'官方','status':'verified','source':{
   'organization':'教育部','url':'https://www.moe.gov.cn/official-test.html','sha256':'a'*64}}
 def errors(self):
  from source_authentication import official_source_errors
  with patch('source_authentication.official_domain_for_url',side_effect=lambda u: {'domain':'moe.gov.cn'} if u.startswith('https://www.moe.gov.cn/') else None):
   return official_source_errors(self.e)
 def test_good_declared_fingerprint_without_local_artifacts(self):self.assertEqual(self.errors(),[])
 def test_missing_or_invalid_verified_fingerprint(self):
  self.e['source'].pop('sha256');self.assertTrue(any('须记录原文指纹' in x for x in self.errors()))
  self.e['source']['sha256']='not-a-sha';self.assertTrue(any('64位' in x for x in self.errors()))
 def test_unretrieved_is_allowed_as_a_gap(self):
  self.e.update(status='unretrieved',value=None,gap='未取到当届公告');self.e['source'].pop('sha256');self.assertEqual(self.errors(),[])
 def test_unretrieved_cannot_have_a_positive_factual_value(self):
  self.e.update(status='unretrieved',value=0);self.assertTrue(any('肯定事实' in x for x in self.errors()))
 def test_name_cannot_launder_explicit_third_party_even_on_official_host(self):
  for name in ['第三方汇总','经验帖','某整理平台','考研机构']:
   self.e['source']['organization']=name;self.assertTrue(any('不得标官方' in x for x in self.errors()))
 def test_generic_official_institution_name_is_allowed(self):
  self.e['source']['organization']='国家教育考试机构';self.assertEqual(self.errors(),[])
 def test_missing_identity_is_rejected(self):
  self.e['source'].pop('organization');self.assertTrue(any('发布单位或来源身份' in x for x in self.errors()))
 def test_lookalike_host_is_rejected(self):
  self.e['source']['url']='https://www.moe.gov.cn.attacker.example/a';self.assertTrue(any('域名不在' in x for x in self.errors()))
 def test_nonofficial_source_is_not_relabelled(self):
  self.e['grade']='第三方整理';self.assertEqual(self.errors(),[])
 def test_registry_subdomains_and_host_boundaries(self):
  from official_source_audit import official_domain_for_url
  domains={'moe.gov.cn':{'domain':'moe.gov.cn','organization':'教育部','evidence':'official URL'}}
  self.assertIsNotNone(official_domain_for_url('https://hudong.moe.gov.cn/a',domains))
  self.assertIsNone(official_domain_for_url('https://moe.gov.cn.attacker.example/a',domains))
  self.assertIsNone(official_domain_for_url('https://moe.gov.cn@attacker.example/a',domains))

if __name__=='__main__':unittest.main()
