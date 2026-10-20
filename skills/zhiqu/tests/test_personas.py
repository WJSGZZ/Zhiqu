"""Reusable profile regression and checklist-only provenance refresh."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from check_personas import CASES,LIBRARY,profiles,check,profile_errors,questionnaire_questions
from planning_workflow import PlanningCase,SKILLS,read,dump,sha
from operator_check import readable_locator,report_locations,sync_checklist_tool_snapshot,generate,checklist_groups

class PersonaTests(unittest.TestCase):
    def test_library_and_declared_stage_regression(self):
        self.assertEqual(check(),[])

    def test_persona_source_links_are_unique_and_duplicates_are_rejected(self):
        text=LIBRARY.read_text();items=profiles(text)
        self.assertEqual(len(items),len(CASES))
        first=text[text.index('## 2028-YJ-S02 · '):].split('\n## 2027-YJ-S03',1)[0]
        with self.assertRaisesRegex(ValueError,'重复'):profiles(text+'\n'+first)

    def test_json_profiles_use_real_question_ids_and_preserve_oral_context(self):
        for kind,cid,_ in CASES:
            root=SKILLS/f'zhiqu-{kind}/examples'/cid
            data=read(root/'profile.json')
            questions=questionnaire_questions(SKILLS.parent/(kind+'.html'))
            self.assertEqual(profile_errors(data,questions,kind),[])
            self.assertIn('模拟',json.dumps(data,ensure_ascii=False))
            supplement=(root/'profile-supplement.txt').read_text()
            self.assertTrue(supplement.startswith('问卷之外的补充（模拟）\n'))
            self.assertIn('【读研 · 自我盘点】' if kind=='grad' else '【求职 · 自我盘点】',supplement)
            self.assertFalse((root/'profile.txt').exists())
            self.assertTrue(data['未填的必答题'])

    def test_unknown_question_changed_wording_and_empty_answers_are_rejected(self):
        root=SKILLS/'zhiqu-grad/examples/2028-YJ-S02'
        questions=questionnaire_questions(SKILLS.parent/'grad.html')
        original=read(root/'profile.json')
        self.assertTrue(profile_errors([],questions,'grad'))
        for change in ({'id':'made_up_question'},{'q':'改写过的问题'},{'a':None},{'followup_of':'missing_parent'}):
            data=copy.deepcopy(original);data['sections'][0]['items'][0].update(change)
            self.assertTrue(profile_errors(data,questions,'grad'))

    def test_library_rejects_missing_sources_and_duplicated_answer_prose(self):
        text=LIBRARY.read_text()
        with self.assertRaisesRegex(ValueError,'缺'):
            profiles(text.replace('profile.json)','missing.json)',1))
        with self.assertRaisesRegex(ValueError,'重复维护'):
            profiles(text.replace('### 阶段产物','### 问卷回答\n\n### 阶段产物',1))

    def test_unknown_qualification_stays_pending(self):
        for kind,cid,_ in CASES:
            c=PlanningCase(SKILLS/f'zhiqu-{kind}/examples'/cid)
            for key in ('paths','school_programs','job_types','jobs'):
                for candidate in c.data['candidates.json'].get(key,[]):
                    statuses={hc['status'] for hc in candidate['hard_conditions']}
                    if 'unknown' in statuses and 'failed' not in statuses:self.assertEqual(candidate['status'],'pending')

    def test_known_work_experience_failure_is_limited_to_named_program(self):
        for cid in ('2027-YJ-S03','2027-YJ-S04'):
            c=PlanningCase(SKILLS/'zhiqu-grad/examples'/cid)
            self.assertEqual(c.data['candidates.json']['paths'][0]['status'],'ineligible')
            self.assertTrue(all(x['status']=='pending' for x in c.data['candidates.json']['school_programs']))

    def test_official_qualifications_and_new_calculations_are_not_personal_input(self):
        for kind,cid,stage in CASES:
            if stage!=10:continue
            c=PlanningCase(SKILLS/f'zhiqu-{kind}/examples'/cid)
            self.assertEqual(c.personal_inputs(),[])
            self.assertEqual(c.evidence_integrity_errors(),[])
            delivery_errors=c.check(10,delivery=True)
            approved=json.loads((c.root/'review.json').read_text()).get('status')=='approved'
            if not approved:self.assertTrue(any('尚未独立批准交付' in e for e in delivery_errors))
            else:self.assertFalse(any('尚未独立批准交付' in e for e in delivery_errors))
            self.assertTrue(any('尚未完成' in e for e in delivery_errors))

    def test_condition_tiers_are_not_presented_as_school_difficulty(self):
        c=PlanningCase(SKILLS/'zhiqu-grad/examples/2028-YJ-S02')
        self.assertTrue(all('tier' not in x for x in c.data['candidates.json']['school_programs']))
        self.assertIsNone(c.data['candidates.json']['personal_difficulty']['mock_exam'])
        md=(c.root/'report.md').read_text()
        self.assertIn('当前不对学校分难度',md)
        self.assertNotIn('个人上岸率',md)

class ChecklistWordingTests(unittest.TestCase):
    def test_internal_keys_are_replaced_by_factual_labels(self):
        for key in ('prestart','masters-2027-http','report.json#/sources/1'):
            e={'source':{'locator':key},'claim':'教育部报名开始日','value':'2026-10-15'}
            self.assertEqual(readable_locator(e),'教育部报名开始日')
        self.assertEqual(readable_locator({'original_locator':'收费附件第八行'}),'收费附件第八行')

    def test_report_positions_use_subheadings_or_paragraph_opening(self):
        for kind in ('grad','career'):
            c=PlanningCase(SKILLS/f'zhiqu-{kind}/examples/demo_2027')
            positions='\n'.join(x for values in report_locations(c).values() for x in values)
            self.assertNotIn('正文第',positions)
            self.assertTrue('段落“' in positions or '第 9 节' in positions)
            _,_,_=checklist_groups(c.root)

    def copy_demo(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)/'demo_2027';shutil.copytree(SKILLS/'zhiqu-grad/examples/demo_2027',root)
        return root

    def test_legacy_position_migrates_without_losing_human_confirmation(self):
        root=self.copy_demo();generate(root)
        path=root/'operator_check.md';text=path.read_text()
        import re
        text=re.sub(r'  定位：[^\n]+','  定位：masters-2027-http / prestart。',text,count=1)
        confirmation='  核完填：核查人：操控者；核查日期：2026-10-19；结果（确认/不符/仍未知）：确认；原文依据与范围：已核；对建议的处理：保留。'
        text=re.sub(r'  核完填：[^\n]+',confirmation,text,count=1)
        text=text.replace('- [ ]','- [x]',1);path.write_text(text)
        generate(root);updated=path.read_text()
        self.assertNotIn('定位：masters-2027-http / prestart',updated)
        self.assertIn(confirmation,updated)
        self.assertIn('- [x]',updated)

    def test_only_checklist_tool_hash_can_refresh_without_rendering(self):
        root=self.copy_demo();trace=read(root/'report_trace.json');trace['tool_sha256']['operator_check.py']='old-checklist-tool';dump(root/'report_trace.json',trace)
        before={f:sha(root/f) for f in ('calculations.json','report.md','report.html','report.pdf')}
        self.assertTrue(sync_checklist_tool_snapshot(root))
        self.assertEqual(before,{f:sha(root/f) for f in before})
        self.assertEqual(PlanningCase(root).trace_errors(),[])

    def test_changed_source_report_or_other_tool_cannot_refresh(self):
        for field,key in [('source_sha256','case.json'),('artifacts','report.pdf'),('tool_sha256','planning_workflow.py')]:
            root=self.copy_demo();trace=read(root/'report_trace.json');trace['tool_sha256']['operator_check.py']='old-checklist-tool';trace[field][key]='changed';dump(root/'report_trace.json',trace)
            self.assertFalse(sync_checklist_tool_snapshot(root))
            self.assertEqual(read(root/'report_trace.json')['tool_sha256']['operator_check.py'],'old-checklist-tool')
            self.assertTrue(PlanningCase(root).trace_errors())

if __name__=='__main__':unittest.main()
