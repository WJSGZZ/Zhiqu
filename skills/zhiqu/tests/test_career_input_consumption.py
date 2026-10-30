"""Synthetic sealed answers: binding is not semantic or employment validation."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import profile_store as ps
from planning_workflow import PlanningCase

class CareerInputConsumptionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
  self.case,self.path,self.indices=self.make(self.base/'new')
 def make(self,root,*,sealed=True,answers=None):
  values={'salary_known':{'选择':'有大致底线','最低到手月薪':'5200元/月到手为底线'},'income_deadline_status':{'选择':'有明确月份','最晚稳定收入年月':'2027-08'},'current_job':'当前到手5200元/月为自报，无新offer。','leave_reason':'希望少夜班，没有决定辞职。','current_terms':'只说下月再谈，合同尚未核。'}
  if answers is not None:values=answers
  data={'zhiqu':'career','schema':1,'问卷':'【求职 · 自我盘点】','form':'a1','filled_at':'2026-10-30T12:00:00+08:00','sections':[{'title':'模拟原答','items':[{'id':k,'q':k,'a':v,'status':'已答'}for k,v in values.items()]}],'rank':[],'derived':{},'未填的必答题':[]}
  if not sealed:
   for item in data['sections'][0]['items']:item.pop('status')
  if sealed:data.update(collapsed=[],counts={'visible':len(values),'answered':len(values)});data['checksum']=ps.checksum(data)
  ps.new_id(root,'career',2027,'simulation');ps.ingest(root,'2027-QZ-0001',json.dumps(data,ensure_ascii=False));p=root/'2027-QZ-0001';ps.prepare(p)
  f=json.loads((p/'profile_parse.json').read_text());indices={x['field']:i for i,x in enumerate(f['fields'])}
  refs=[]
  for name,suffix in [('收入底线','/最低到手月薪'),('多快需要收入','/最晚稳定收入年月'),('当前工作原答',''),('离开原因原答',''),('在岗与离职约定原答','')]:
   if name in indices and f['fields'][indices[name]]['status']=='given':refs.append('{{p:/fields/'+str(indices[name])+'/value'+suffix+'}}')
  c=json.loads((p/'case.json').read_text());c['report_input_usage']=[{'pointer':f'/fields/{indices[n]}/value','sections':['03','12']}for n in ['收入底线','多快需要收入','当前工作原答','离开原因原答','在岗与离职约定原答']if n in indices and f['fields'][indices[n]]['status']=='given'];ps.dump(p/'case.json',c)
  ps.dump(p/'narrative.json',{'sections':{'03':{'analysis':[{'type':'analysis','content':{'text':'；'.join(refs)},'evidence_refs':[],'calc_refs':[]}]}}});ps.dump(p/'judgment.json',{'presentation':{'03':[{'slot':'analysis','ref':'narrative.json#/sections/03/analysis/0'}]}});ps.dump(p/'evidence.json',{'items':[]})
  return PlanningCase(p),p,indices
 def test_complete_explicit_bindings_pass_and_missing_each_declaration_fails(self):
  self.assertEqual(self.case.career_input_usage_errors(),[])
  for row in self.case.case['report_input_usage']:
   original=self.case.case['report_input_usage'];self.case.case['report_input_usage']=[x for x in original if x is not row]
   self.assertTrue(any('缺正文使用登记'in x for x in self.case.career_input_usage_errors()));self.case.case['report_input_usage']=original
 def test_registration_alone_appendix_only_and_wrong_section_do_not_pass(self):
  self.case.data['narrative.json']['sections']['03']['analysis'][0]['content']['text']='原答已登记，但不引用。'
  self.assertTrue(any('未在激活正文中绑定'in x for x in self.case.career_input_usage_errors()))
  self.case=PlanningCase(self.path)
  for row in self.case.case['report_input_usage']:row['sections']=['12']
  self.assertTrue(any('缺正文使用登记'in x for x in self.case.career_input_usage_errors()))
  for row in self.case.case['report_input_usage']:row['sections']=['02','12']
  self.assertTrue(any('漏登记实际节 03'in x for x in self.case.career_input_usage_errors()))
 def test_comments_unused_content_and_inactive_slots_do_not_count(self):
  node=self.case.data['narrative.json']['sections']['03']['analysis'][0];text=node['content']['text']
  for content in [{'text':'无实际绑定','unused':text},{'text':text,'kind':'comment'},{'text':'<!-- '+text+' -->'}]:
   with self.subTest(content=content):
    node['content']=content;self.assertTrue(any('未在激活正文'in x for x in self.case.career_input_usage_errors()))
  node['content']={'text':text};slot=next(s for sec in self.case.contract['sections']if sec['id']=='03'for s in sec['slots']if s['key']=='analysis');slot['condition']='offer_basis_actual_or_scenario';self.case.case['context']={'offer_basis':'none'}
  self.assertTrue(any('未在激活正文'in x for x in self.case.career_input_usage_errors()))
 def test_same_5200_current_income_cannot_replace_salary_floor(self):
  node=self.case.data['narrative.json']['sections']['03']['analysis'][0]
  node['content']['text']=node['content']['text'].replace('{{p:/fields/'+str(self.indices['收入底线'])+'/value/最低到手月薪}}','{{p:/fields/'+str(self.indices['当前工作原答'])+'/value}}')
  self.assertTrue(any('未在激活正文中绑定：收入底线'in x for x in self.case.career_input_usage_errors()))
 def test_exact_personal_evidence_is_a_binding_but_wrong_excerpt_is_not(self):
  i=self.indices['在岗与离职约定原答'];node=self.case.data['narrative.json']['sections']['03']['analysis'][0];node['content']['text']=node['content']['text'].replace('{{p:/fields/'+str(i)+'/value}}','原答内容待核。');node['evidence_refs']=['E1']
  self.case.evidence={'E1':{'grade':'单人说法','status':'verified','retrieval_method':'provided','source':{'locator':'画像 JSON 题目：current_terms'},'excerpt':'只说下月再谈，合同尚未核。'}}
  self.assertEqual(self.case.career_input_usage_errors(),[])
  for wrong in ['已经答应白班。','未取得','只说下月再谈']:
   self.case.evidence['E1']['excerpt']=wrong;self.assertTrue(any('未在激活正文中绑定：在岗与离职约定原答'in x for x in self.case.career_input_usage_errors()))
 def test_unknown_refusal_and_absent_questions_not_upgraded(self):
  c,_,_=self.make(self.base/'refused',answers={'current_terms':'暂不提供，涉及公司资料','salary_known':{'选择':'不想说'},'income_deadline_status':{'选择':'不确定'}})
  self.assertEqual(c.career_input_usage_errors(),[])
 def test_unsealed_migration_and_grad_keep_existing_policy(self):
  c,_,_=self.make(self.base/'old',sealed=False);c.case['report_input_usage']=[];self.assertEqual(c.career_input_usage_errors(),[])
  self.case.kind='grad';self.assertEqual(self.case.career_input_usage_errors(),[])
 def test_registered_dependency_and_cover_are_real_bindings(self):
  i=self.indices['收入底线'];f=self.case.data['profile_parse.json']['fields'][i];f['value']=5200
  self.case.case['calculation_plan']={'engine':'registered_operations','operations':[{'output':'remaining','inputs':['{{p:/fields/'+str(i)+'/value}}',3000]}]}
  self.case.data['calculations.json']={'remaining':2200}
  node=self.case.data['narrative.json']['sections']['03']['analysis'][0];node['content']['text']=node['content']['text'].replace('{{p:/fields/'+str(i)+'/value/最低到手月薪}}','{{c:/remaining}}');self.assertEqual(self.case.career_input_usage_errors(),[])
  i=self.indices['多快需要收入'];ref='{{p:/fields/'+str(i)+'/value/最晚稳定收入年月}}';node['content']['text']=node['content']['text'].replace(ref,'');self.case.case['report_meta']={'conclusion':ref};next(x for x in self.case.case['report_input_usage']if x['pointer']==f'/fields/{i}/value')['sections']=['01','12'];self.assertEqual(self.case.career_input_usage_errors(),[])
 def test_hidden_link_target_and_title_are_not_visible_bindings(self):
  node=self.case.data['narrative.json']['sections']['03']['analysis'][0];original=node['content']['text'];ref='{{p:/fields/'+str(self.indices['在岗与离职约定原答'])+'/value}}'
  for hidden in ['[查看原答](https://example.invalid/'+ref+')','[查看原答](https://example.invalid/ "'+ref+'")']:
   node['content']['text']=original.replace(ref,hidden);self.assertTrue(any('未在激活正文中绑定：在岗与离职约定原答'in x for x in self.case.career_input_usage_errors()))
  node['content']['text']=original.replace(ref,'['+ref+'](https://example.invalid/)');self.assertEqual(self.case.career_input_usage_errors(),[])
 def test_malformed_containers_and_nonexistent_subpointer_fail_without_crash(self):
  for key in ['report_input_usage','calculation_plan','report_meta']:
   c=copy.deepcopy(self.case.case);self.case.case[key]=None;self.assertTrue(self.case.career_input_usage_errors());self.case.case=c
  node=self.case.data['narrative.json']['sections']['03']['analysis'][0];ref='{{p:/fields/'+str(self.indices['在岗与离职约定原答'])+'/value}}';node['content']['text']=node['content']['text'].replace(ref,ref.replace('/value','/value/nonexistent'))
  self.assertTrue(any('未在激活正文中绑定：在岗与离职约定原答'in x for x in self.case.career_input_usage_errors()))
  node['evidence_refs']=['E1'];self.case.evidence={'E1':{'grade':'单人说法','status':'verified','retrieval_method':'provided','source':None,'excerpt':'只说下月再谈，合同尚未核。'}};self.assertTrue(self.case.career_input_usage_errors())
  self.case.evidence={'E1':None};self.assertTrue(self.case.career_input_usage_errors())
 def test_valid_registered_scenario_numeric_change_and_display_format_pass(self):
  from verification_calculations import _registered
  i=self.indices['收入底线'];self.case.data['profile_parse.json']['fields'][i]['value']=5200;self.case.case['budget']={'monthly_other_expenses_assumption':3000}
  pref='{{p:/fields/'+str(i)+'/value}}';kref='{{k:/budget/monthly_other_expenses_assumption}}'
  self.case.case['calculation_plan']={'engine':'registered_operations','operations':[{'output':'remaining','algorithm':'difference','inputs':[pref,kref]}],'scenarios':[{'baseline_output':'remaining','changed_inputs':{kref:4000},'output_ref':'{{c:/stress}}'}]}
  computed,_=_registered(self.case.case,self.case.data['profile_parse.json'],{'items':[]});self.assertEqual(computed['stress'],1200);self.case.data['calculations.json']=computed
  node=self.case.data['narrative.json']['sections']['03']['analysis'][0];original=node['content']['text'];original_ref='{{p:/fields/'+str(i)+'/value/最低到手月薪}}'
  for shown in ['{{c:/stress}}','{{c:/stress|comma}}']:
   node['content']['text']=original.replace(original_ref,shown);self.assertEqual(self.case.career_input_usage_errors(),[])
 def test_stage8_invokes_gate(self):
  self.case.case['report_input_usage']=[]
  with patch.object(self.case,'contract_errors',return_value=[]),patch('reader_language.check_planning_source',return_value=[]),patch('planning_report.assemble',return_value=('body',[])),patch('render_report.render',return_value=('body',{})),patch('reader_language.check_html',return_value=[]):self.case.stage8()
  self.assertTrue(any('关键原答缺正文使用登记'in x for x in self.case.errors))
