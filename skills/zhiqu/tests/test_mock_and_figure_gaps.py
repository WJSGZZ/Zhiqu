"""Comparable mocks govern personal tiers; missing figure data stays a short gap."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from planning_workflow import PlanningCase, SKILLS, read, dump
from planning_report import node_markdown

class MockAndGapTests(unittest.TestCase):
    def case(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)/'2028-YJ-S02';shutil.copytree(SKILLS/'zhiqu-grad/examples/2028-YJ-S02',root)
        return PlanningCase(root)

    def mock(self,c):
        c.evidence['MOCK']={'id':'MOCK','value':360,'status':'verified','claim':'本人完整模考总分','unit':'分'}
        return {'complete':True,'same_subjects':True,'subjects':['政治','英语','数学','专业课'],
                'exam_date':'2026-10-18','evidence_refs':['MOCK'],'score_ref':'{{e:MOCK#/value}}'}

    def test_no_mock_passes_without_tiers_with_clear_checkpoint(self):
        c=self.case();c.stage4();self.assertEqual(c.errors,[])
        self.assertFalse(c.has_complete_mock())

    def test_no_mock_rejects_personal_tier_and_missing_checkpoint(self):
        c=self.case();c.data['candidates.json']['school_programs'][0]['tier']='相对稳妥';c.stage4()
        self.assertTrue(any('不得标个人难度档' in e for e in c.errors))
        c=self.case();c.data['candidates.json']['personal_difficulty'].pop('checkpoint');c.stage4()
        self.assertTrue(any('定档检查点' in e for e in c.errors))

    def test_complete_comparable_mock_requires_personal_tiers(self):
        c=self.case();c.data['candidates.json']['personal_difficulty']['mock_exam']=self.mock(c)
        self.assertTrue(c.has_complete_mock());c.stage4()
        self.assertTrue(any('须分个人条件档' in e for e in c.errors))
        c.errors=[]
        for row,tier in zip(c.data['candidates.json']['school_programs'],['相对稳妥','够一够','冒险']):row['tier']=tier
        c.stage4();self.assertEqual(c.errors,[])

    def test_incomplete_different_subject_or_unbacked_mock_rejected(self):
        for changes in ({'complete':False},{'same_subjects':False},{'evidence_refs':[]},{'score_ref':'{{e:missing#/value}}'},{'exam_date':'2028-01-01'}):
            c=self.case();mock=self.mock(c);mock.update(changes)
            c.data['candidates.json']['personal_difficulty']['mock_exam']=mock;c.stage4()
            self.assertTrue(any('模考记录不完整' in e for e in c.errors))

    def test_a_fee_cannot_be_used_as_mock_score(self):
        c=self.case();mock=self.mock(c);c.evidence['MOCK'].update(claim='学费标准',unit='元')
        c.data['candidates.json']['personal_difficulty']['mock_exam']=mock
        self.assertFalse(c.has_complete_mock())

    def plot(self,c):
        entry=next(x for x in c.nodes()['06'] if x['slot']=='score_ranges')
        return c.get_node(entry['ref'])

    def test_complete_gap_passes_and_renders_one_paragraph_without_svg(self):
        c=self.case();n=self.plot(c);self.assertEqual(n['type'],'data_gap')
        self.assertEqual(c.contract_errors(),[])
        text=node_markdown(n,c.expand,{e:1 for e in c.evidence})
        self.assertIn('缺口：',text);self.assertIn('去哪里取：',text);self.assertIn('2027-03-15',text)
        self.assertNotIn(':::',text);self.assertNotIn('<svg',text)

    def test_empty_plot_rejected_and_real_zero_is_data(self):
        c=self.case();n=self.plot(c)
        n.update(type='interval',content={'title':'分数','caption':'学校分布，不是个人把握','rows':[['调查校','未取到','未取到','']]})
        self.assertTrue(any('没有可画数据' in e for e in c.contract_errors()))
        self.assertTrue(c.figure_has_data('interval',{'rows':[['对象','0','10','']]}))
        self.assertFalse(c.figure_has_data('bars',{'rows':[['对象','NaN']]}))

    def test_gap_cannot_replace_missing_source_or_date(self):
        for field in ('missing','source','expected_by'):
            c=self.case();self.plot(c)['content'].pop(field)
            self.assertTrue(any('图表缺口须写' in e for e in c.contract_errors()))
        c=self.case();self.plot(c)['content']['expected_by']='以后'
        self.assertTrue(any('预计补齐日期无效' in e for e in c.contract_errors()))

if __name__=='__main__':unittest.main()
