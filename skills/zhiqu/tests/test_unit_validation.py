import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from unit_validation import errors,reference_unit,normalize_unit

class UnitValidationTests(unittest.TestCase):
    def case(self,unit='元/年',value=100):
        return {'case.json':{'reference_units':{'k:/budget/annual_limit':unit}},
                'calculations.json':{},'evidence.json':{'items':[{'id':'E1','value':value,'unit':unit}]}}
    def check(self,unit,text,expected=True,value=100):
        result=errors(self.case(unit,value),text,'narrative')
        self.assertEqual(bool(result),not expected,result)
    def test_equivalent_money_aliases(self):
        for display in ('元/年','人民币元/学年','CNY/年','¥'):
            text='预算{{e:E1#/value}}'+display if display!='¥' else '¥{{e:E1#/value}}'
            self.check('元/生·学年',text)
    def test_bare_yuan_can_omit_period(self):
        self.check('元/年','年度成本{{e:E1#/value}}元')
        self.check('元/月','成本{{e:E1#/value}}元')
    def test_wrong_period(self):
        self.check('元/年','{{e:E1#/value}}元/月',False)
        self.check('元/月','{{e:E1#/value}}元/年',False)
        self.check('元/年','每月成本{{e:E1#/value}}元',False)
    def test_wrong_scale(self):
        self.check('元','{{e:E1#/value}}万元',False)
        self.check('元','{{e:E1#/value}}（万美元）',False)
        self.check('万元','{{e:E1#/value}}元',False)
        self.check('万元','{{e:E1#/value}}人民币万元')
    def test_wrong_currency_prefix_and_suffix(self):
        for symbol in ('HK$','MOP$','US$','USD'):
            self.check('元',symbol+'{{e:E1#/value}}',False)
        self.check('港元','HK${{e:E1#/value}}港币')
        self.check('港元','HK${{e:E1#/value}}美元',False)
        self.check('港元','¥{{e:E1#/value}}港元',False)
        self.check('澳门元','MOP${{e:E1#/value}}澳门币')
        self.check('美元','US${{e:E1#/value}}美元')
    def test_percentage_requires_registered_format(self):
        self.check('比率','{{e:E1#/value|percent1}}%',True,.2)
        self.check('比率','{{e:E1#/value}}%',False,.2)
        self.check('%','{{e:E1#/value}}%',True,20)
        self.check('%','{{e:E1#/value|percent0}}%',False,20)
    def test_score_people_and_duration(self):
        self.check('分','{{e:E1#/value}}名',False)
        self.check('人','{{e:E1#/value}}名')
        self.check('月','{{e:E1#/value}}年',False)
        self.check('分','{{e:E1#/value}}分')
    def test_metadata_cannot_come_from_prose(self):
        case=self.case();case['evidence.json']['items'][0]['unit']=''
        problems=errors(case,'{{e:E1#/value}}元/年')
        self.assertEqual(len(problems),1)
        self.assertIn('missing-unit',problems[0])
        self.assertIsNone(reference_unit(case,'e','E1#/value'))
    def test_explicit_registration_and_calculation_metadata(self):
        case=self.case();case['case.json']['reference_units']['c:/result']='分'
        case['calculations.json']['result']=100
        self.assertEqual(reference_unit(case,'k','/budget/annual_limit'),'元/年')
        self.assertEqual(reference_unit(case,'c','/result'),'分')
        self.assertFalse(errors(case,'{{k:/budget/annual_limit}}元/年'))
        self.assertTrue(errors(case,'{{c:/result}}元'))
    def test_year_and_percentage_point_are_distinct(self):
        self.check('年份','{{e:E1#/value}}年')
        self.check('年份','{{e:E1#/value}}月',False)
        self.check('%','{{e:E1#/value}}个百分点',False)
        self.check('比率','{{e:E1#/value}}倍')
    def test_registered_scenario_inherits_explicit_operation_unit(self):
        c={'calculation_plan':{'engine':'registered_operations',
           'operations':[{'output':'n','unit':'人'}],
           'scenarios':[{'baseline_output':'n','output_ref':'{{c:/alternate|comma}}'}]}}
        self.assertEqual(reference_unit(c,'c','/alternate'),'人')
    def test_percentile_label_is_not_score_suffix(self):
        self.check('%','{{e:E1#/value}}分位')
    def test_identifier_and_prose_fragments_are_not_quantities(self):
        self.check('代码','{{e:E1#/value}} 分数平移')
        self.check('年份','{{e:E1#/value}}岗位')
        self.check('比率','{{e:E1#/value|percent1}}个人社保',True,.104)
        self.check('代码','{{e:E1#/value}} 分',False)
        self.check('元','{{e:E1#/value}}分数学成绩',False)
        self.check('元','{{e:E1#/value}}个人',False)
        self.check('人','{{e:E1#/value}}个人')
    def test_evidence_unit_only_applies_to_value(self):
        self.assertIsNone(reference_unit(self.case(),'e','E1#/source/id'))
    def test_registered_operation_unit(self):
        c={'calculation_plan':{'engine':'registered_operations','operations':[{'output':'n','unit':'人'}]}}
        self.assertEqual(reference_unit(c,'c','/n'),'人')
        self.assertIsNone(reference_unit(c,'c','/annual_cost'))
    def test_legacy_schema_is_explicit_and_engine_bounded(self):
        c={'calculation_plan':{'engine':'legacy_demo'}}
        self.assertEqual(reference_unit(c,'c','/hypothetical_offers/0/monthly_take_home_cash'),'元/月')
        self.assertEqual(reference_unit(c,'c','/annual_cost'),'元/年')
        for path in ('/other/annual_cost','/annual_cost_extra','/report_parameters/arbitrary_money'):
            self.assertIsNone(reference_unit(c,'c',path))
        self.assertIsNone(reference_unit({},'c','/annual_cost'))
    def test_equivalent_unit_dimensions(self):
        self.assertEqual(normalize_unit('元/生·学年'),normalize_unit('人民币元/年'))
        self.assertNotEqual(normalize_unit('万元/年'),normalize_unit('元/年'))
        self.assertNotEqual(normalize_unit('美元'),normalize_unit('港元'))
    def test_no_unit_mismatch_for_prose_after_reference(self):
        self.check('人','{{e:E1#/value}}，分别开展复核')

if __name__=='__main__':unittest.main()


class CompoundUnits(unittest.TestCase):
    def test_longest_ratio_suffix_and_spacing(self):
        fixture={'evidence.json':{'items':[{'id':'E1','value':40,'unit':'缴费人数÷招录人数'}]}}
        for suffix in ('人/岗','人 / 岗','人/职位','人/名额','人 ／ 名额','缴费人数/招录人数'):
            self.assertEqual(errors(fixture,'约{{e:E1#/value}}'+suffix),[],suffix)
        self.assertTrue(errors(fixture,'约{{e:E1#/value}}人'))
    def test_compound_ratio_does_not_accept_people_or_money_source(self):
        for unit in ('人','元'):
            fixture={'evidence.json':{'items':[{'id':'E1','value':40,'unit':unit}]}}
            self.assertTrue(errors(fixture,'{{e:E1#/value}}人/名额'))


class ExplicitQuotaContext(unittest.TestCase):
    def fixture(self):
        return {'evidence.json':{'items':[{'id':'E1','value':40,'unit':'缴费人数÷招录人数'},{'id':'E2','value':50,'unit':'缴费人数÷招录人数'}]}}
    def test_per_quota_definition_applies_to_same_paragraph_comparison(self):
        for text in ('每个名额约{{e:E1#/value}}人。', '每名额约{{e:E1#/value}}人。',
                     '每个名额缴费人数的中位数约{{e:E1#/value}}人；全省中位数{{e:E2#/value}}人。',
                     '每个名额报名人数的中位数{{e:E1#/value}}人，中间区间上界{{e:E2#/value}}人。'):
            self.assertEqual(errors(self.fixture(),text),[],text)
    def test_missing_denominator_or_different_paragraph_still_fails(self):
        for text in ('中位数约{{e:E1#/value}}人。','每个职位招录{{e:E1#/value}}人。',
                     '每个名额缴费人数为若干。\n\n另一组{{e:E1#/value}}人。'):
            self.assertTrue(errors(self.fixture(),text),text)
    def test_plain_people_source_not_promoted_to_ratio_by_metadata(self):
        c={'evidence.json':{'items':[{'id':'E1','value':40,'unit':'人'}]}}
        self.assertTrue(errors(c,'每个名额约{{e:E1#/value}}人。'))
