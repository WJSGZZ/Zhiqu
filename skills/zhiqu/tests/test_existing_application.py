"""合成原答与截止证据，只验证单校范围门禁，不认证真实报名或官方事实。"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from planning_workflow import PlanningCase,dump

class ExistingApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.text='本人称已报合成大学081200，回执和确认状态未核。'
        self.field={'field':'实际报考原答','value':self.text,'quote':self.text,'answer_refs':['ky_target']}
        self.raw={'sections':[{'items':[{'id':'ky_target','a':self.text}]}]}
        self.case={'kind':'grad','target_year':2027,'context':{'takes_kaoyan':True,'as_of':'2026-10-30'},'profile':{'file':'original.json'}}
        self.deadline={'id':'END','claim':'全国网上报名截止日','grade':'官方','status':'verified','availability':'available','value':'2026-10-24','published_on':'2026-09-23','retrieved_on':'2026-10-20','verified_on':'2026-10-20','review_due':'2026-11-19','scope':'2027年全国统考','excerpt':'全国网上报名时间为2026年10月15日至10月24日。','source':{'url':'https://www.moe.gov.cn/synthetic','sha256':'a'*64}}
        self.candidates={'school_programs':[{'id':'S1','school':'合成大学','program_code':'081200','year':2027,'status':'pending','hard_conditions':[{'id':'registration_status','status':'unknown','evidence_refs':['USER']}]}],'paths':[],'personal_difficulty':{'mock_exam':None,'checkpoint':{'date':'2026-11-12','action':'核完整同科目模考后再定档'}}}
        self.scope={'candidate_id':'S1','status':'reported','statement_ref':'profile_parse.json#/fields/0/value','deadline_evidence_id':'END'}
    def check(self,declared=True):
        c=copy.deepcopy(self.candidates)
        if declared:c['existing_application']=copy.deepcopy(self.scope)
        for name,obj in [('case.json',self.case),('profile_parse.json',{'fields':[self.field]}),('original.json',self.raw),('candidates.json',c),('evidence.json',{'items':[self.deadline,{'id':'USER','grade':'单人说法','status':'verified'}]})]:dump(self.root/name,obj)
        p=PlanningCase(self.root);p.stage4();return p.errors
    def test_reported_target_after_official_window_can_remain_one_school(self):
        self.assertEqual(self.check(),[])
        self.assertEqual(self.candidates['school_programs'][0]['status'],'pending')
        self.assertEqual(self.candidates['school_programs'][0]['hard_conditions'][0]['status'],'unknown')
    def test_ordinary_choice_still_requires_three_schools(self):
        self.assertTrue(any('候选少于' in e for e in self.check(False)))
    def test_boolean_or_success_claim_is_not_an_escape_switch(self):
        for scope in [True,{},dict(self.scope,status='verified'),dict(self.scope,candidate_id='other')]:
            with self.subTest(scope=scope):
                self.scope=scope;self.assertTrue(any('不能缩成单校' in e for e in self.check()))
        self.scope={'candidate_id':'S1','status':'reported','statement_ref':'profile_parse.json#/fields/0/value','deadline_evidence_id':'END'}
        for state in ['verified','ineligible']:
            self.candidates['school_programs'][0]['status']=state;self.assertTrue(self.check())
    def test_deadline_must_be_official_current_and_already_passed(self):
        original=copy.deepcopy(self.deadline)
        for key,value in [('grade','第三方整理'),('status','unretrieved'),('availability','unavailable'),('scope','2026年全国统考'),('value','2026-11-24'),('value','2026-10-30'),('review_due','2026-10-29'),('retrieved_on','2026-11-01'),('claim','全国初试截止日')]:
            with self.subTest(key=key,value=value):
                self.deadline=copy.deepcopy(original);self.deadline[key]=value;self.assertTrue(self.check())
        self.deadline=original
        for source in [{'url':'https://third.example/page','sha256':'a'*64},{'url':'javascript://www.moe.gov.cn/a','sha256':'a'*64},{'url':'https://www.moe.gov.cn/a','sha256':''}]:
            self.deadline['source']=source;self.assertTrue(self.check())
    def test_statement_must_match_original_school_code_and_affirmation(self):
        for text in ['本人未报名合成大学081200。','本人不是已经报名合成大学081200。','本人想报合成大学081200。','本人已报别的大学081200。','本人已报合成大学081201。','本人已报合成大学0812000。','同学已报合成大学081200，我尚在择校。','本人并没有完成报名合成大学081200，系统误显已经报名。','本人已报合成大学081200，随后已撤销报名，目前仍在择校。','本人已报合成大学081200；后来撤回报名。','本人已报名，替同学报合成大学081200。','本人已报合成大学081200调剂。']:
            with self.subTest(text=text):
                self.field.update(value=text,quote=text);self.raw['sections'][0]['items'][0]['a']=text;self.assertTrue(self.check())
    def test_fabricated_parse_and_unbound_original_are_rejected(self):
        self.raw['sections'][0]['items'][0]['a']='本人尚未确定目标。';self.assertTrue(self.check())
        self.raw['sections'][0]['items'][0]['a']=self.text;self.field['quote']='改写后的说法';self.assertTrue(self.check())
        self.field['quote']=self.text;self.scope['statement_ref']='case.json#/context/as_of';self.assertTrue(self.check())
    def test_scope_cannot_change_cohort_or_confirm_registration(self):
        self.candidates['school_programs'][0]['year']=2028;self.assertTrue(self.check());self.candidates['school_programs'][0]['year']=2027
        self.candidates['school_programs'][0]['hard_conditions'][0]['status']='met';self.assertTrue(self.check())
    def test_one_school_does_not_bypass_mock_and_eligibility_checks(self):
        self.candidates['school_programs'][0]['tier']='相对稳妥';self.assertTrue(any('无同科目完整模考' in e for e in self.check()))

    def test_pre_registration_or_confirmation_date_cannot_be_used_as_main_deadline(self):
        self.deadline['excerpt']='全国网上报名时间为2026年10月15日至10月31日。预报名截止日为2026年10月24日。'
        self.assertTrue(self.check())
        self.deadline['excerpt']='网上确认时间为2026年10月15日至10月24日。'
        self.assertTrue(self.check())
        self.deadline['excerpt']='预 报名时间为2026年10月15日至10月24日。'
        self.assertTrue(self.check())
    def test_future_cohort_cannot_relabel_last_years_registration_window(self):
        self.case['target_year']=2028;self.candidates['school_programs'][0]['year']=2028;self.deadline['scope']='2028年全国统考'
        self.assertTrue(self.check())

    def test_existing_application_cannot_turn_off_kaoyan_guards(self):
        self.case['context']['takes_kaoyan']=False
        self.assertTrue(any('不能用false' in e for e in self.check()))

    def test_alternative_school_or_code_cannot_be_spliced_into_registration(self):
        for text in ['本人已报其他大学081201，合成大学081200仅作备选。','本人已报合成大学081201，081200只是往年专业代码。','本人已报合成大学081200；我仍在择校，还未提交报名。','本人已报合成大学081200；其实我没报。']:
            self.field.update(value=text,quote=text);self.raw['sections'][0]['items'][0]['a']=text
            self.assertTrue(self.check())
    def test_registration_interval_must_have_a_valid_ordered_start(self):
        for text in ['全国网上报名时间为2026年11月15日至10月24日。','全国网上报名时间为2026年99月99日至10月24日。']:
            self.deadline['excerpt']=text;self.assertTrue(self.check())

    def test_default_parser_quote_binds_the_same_original_question_only(self):
        self.field['quote']=json.dumps({'ky_target':self.text},ensure_ascii=False)
        self.assertEqual(self.check(),[])
        self.field['quote']=json.dumps({'another_question':self.text},ensure_ascii=False)
        self.assertTrue(self.check())
        self.field['quote']=json.dumps({'ky_target':self.text,'extra':'未提供'},ensure_ascii=False)
        self.assertTrue(self.check())
