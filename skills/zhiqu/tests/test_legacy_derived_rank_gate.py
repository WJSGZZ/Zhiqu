"""旧导出缺新格式键，不抹掉数值已经声明的累计末端口径。"""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from data_provenance import cutoff_rank_gate, rank_gate_reason
from pool import input_provenance


def legacy_fact():
    return {'value':20000,'grade':'官方','display_grade':'官方','source_id':'original',
            'source_registered':True,'scope':{'year':2026},
            'value_status':{'status':'推算','method':'投档分→同年同科一分一段累计；原附注'},
            'original_scope':{'source_format_reference':{
                'source_id':'original','excerpt':'投档最低分及同分排序项',
                'locator':json.dumps({'columns':{'code':'A','name':'B','major_code':'C','major':'D','score':'E'},'sha256':'a'*64})}}}


class LegacyRankGateTests(unittest.TestCase):
    def test_missing_new_key_does_not_restore_declared_cumulative_rank(self):
        fact=legacy_fact()
        self.assertNotIn('provided_fields',fact['original_scope']['source_format_reference'])
        self.assertFalse(cutoff_rank_gate(fact)['model_usable'])
        self.assertIn('字段清单',cutoff_rank_gate(fact)['reason'])
        self.assertEqual(fact,legacy_fact())

    def test_complete_or_undeclared_formats_keep_the_previous_policy(self):
        fact=legacy_fact()
        self.assertIsNotNone(cutoff_rank_gate(fact,['score']))
        self.assertIsNone(cutoff_rank_gate(fact,['score','rank']))
        fact.pop('original_scope')
        self.assertIsNone(cutoff_rank_gate(fact))
        for fields in (None,[],'unknown'):
            with self.subTest(fields=fields):self.assertIsNone(cutoff_rank_gate(fact,fields))
        fact['original_scope']={'source_format_reference':{}}
        self.assertIsNone(cutoff_rank_gate(fact))

    def test_downgraded_grade_does_not_change_declared_method_meaning(self):
        for grade in ('官方','第三方整理','未注明'):
            fact=legacy_fact();fact.update(grade=grade,display_grade='第三方整理·内部未核')
            self.assertFalse(cutoff_rank_gate(fact)['model_usable'])

    def test_unknown_or_negated_methods_are_not_inferred(self):
        for method in ('','未登记','直接抄录最低位次','不使用投档分→同年同科一分一段累计','曾比较投档分→同年同科一分一段累计',None,[],{}):
            fact=legacy_fact();fact.pop('original_scope');fact['value_status']['method']=method
            self.assertIsNone(cutoff_rank_gate(fact))

    def test_actual_original_values_and_other_unknown_calculations_stay_unchanged(self):
        for status in ('官方原值','人工更正'):
            fact=legacy_fact();fact['value_status']={'status':status}
            self.assertIsNone(cutoff_rank_gate(fact))
        fact=legacy_fact();fact['value_status']='推算'
        self.assertIsNotNone(cutoff_rank_gate(fact))
        self.assertIsNotNone(cutoff_rank_gate(fact,['score']))
        fact['value']=None;self.assertIsNone(cutoff_rank_gate(fact,['score']))

    def test_json_object_status_and_mapping_status_use_the_same_gate(self):
        fact=legacy_fact();expected=cutoff_rank_gate(fact)
        fact['value_status']=json.dumps(fact['value_status'],ensure_ascii=False)
        self.assertEqual(cutoff_rank_gate(fact),expected)
        for state in ('not-json','[]','null','{"status":'):
            fact['value_status']=state
            self.assertIsNotNone(cutoff_rank_gate(fact))

    def test_broken_declared_field_lists_are_missing_not_unknown(self):
        for fields in (None,[],[''],[False],'score',{'score':True}):
            with self.subTest(fields=fields):
                fact=legacy_fact();fact['original_scope']['source_format_reference']['provided_fields']=fields
                self.assertFalse(cutoff_rank_gate(fact)['model_usable'])
        fact=legacy_fact()
        self.assertIsNotNone(cutoff_rank_gate(fact,[]))
        fact['original_scope']['source_format_reference']['provided_fields']=['score','rank']
        self.assertIsNone(cutoff_rank_gate(fact))

    def test_bad_state_types_never_count_as_a_usable_rank(self):
        for state in ({'status':['推算']},{'status':{'status':'推算'}},{'status':True},{'status':None},{},[],True,1,'[]','null','{"status":'):
            with self.subTest(state=state):
                fact=legacy_fact();fact['value_status']=state
                self.assertFalse(cutoff_rank_gate(fact)['model_usable'])
                fact['original_scope']['source_format_reference']['provided_fields']=['score','rank']
                self.assertFalse(cutoff_rank_gate(fact)['model_usable'])
        fact=legacy_fact();fact['original_scope']='not-an-object'
        self.assertIn('original_scope',cutoff_rank_gate(fact)['reason'])

    def test_error_details_never_echo_an_unknown_container(self):
        for reason in (['not-for-output'],{'private':'not-for-output'},None,''):
            fact=legacy_fact();fact['usage_gate']={'model_usable':False,'reason':reason}
            self.assertEqual(rank_gate_reason(cutoff_rank_gate(fact)),'数值来源或适用口径尚未核准')

    def test_pool_rejects_legacy_provenance_before_writing_candidates(self):
        row={'code':'001','name':'甲大学','major':'计算机','rank':'20000','data_provenance':json.dumps({'rank':legacy_fact()})}
        with self.assertRaisesRegex(ValueError,'不能作为实际投档位次'):input_provenance(row,2026)
        with tempfile.TemporaryDirectory()as td:
            source=Path(td)/'input.csv';out=Path(td)/'pool.csv'
            with source.open('w')as f:
                writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
            result=subprocess.run([sys.executable,str(SCRIPTS/'pool.py'),'--key','major','--school','name','--year',f'2026={source}','--out',str(out)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('不能作为实际投档位次',result.stderr);self.assertIn('重新导出',result.stderr);self.assertNotIn('原表未公布',result.stderr);self.assertFalse(out.exists())
