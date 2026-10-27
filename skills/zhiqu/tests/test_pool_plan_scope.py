"""计划条件进入筛选、跨年对应和报告限制；旧 CSV 不增加字段。"""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import check_report
import pool
import report


class PoolPlanScopeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.serial = 0

    def write(self, name, rows):
        path = self.root / name
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        return path

    def row(self, *, rank=20000, plan_type=None, admission=None, **extra):
        value = dict(code='10285', name='苏州大学', major='计算机', rank=str(rank), plan='10')
        scope = {}
        original = {}
        if plan_type is not None:
            value['plan_type'] = scope['plan_type'] = plan_type
        if admission is not None:
            original['source_admission_type_raw'] = admission
        fact = {'value': rank, 'grade': '官方', 'source_id': 'offline-test', 'scope': scope,
                'original_scope': {'source_scope_original': original}}
        value['data_provenance'] = json.dumps({'rank': fact}, ensure_ascii=False)
        value['source_grade'] = '官方'
        value.update(extra)
        return value

    def run_pool(self, years, *, extra=(), fail=False):
        self.serial += 1
        output = self.root / f'pool-{self.serial}.csv'
        log = self.root / f'log-{self.serial}.json'
        args = [sys.executable, str(SCRIPTS / 'pool.py'), '--key', 'major', '--out', str(output), '--screening-log', str(log)]
        for year, rows in years:
            path = self.write(f'input-{self.serial}-{year}.csv', rows)
            args += ['--year', f'{year}={path}']
        result = subprocess.run(args + list(extra), capture_output=True, text=True)
        if fail:
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        with output.open() as f:
            rows = list(csv.DictReader(f))
        return output, rows, json.loads(log.read_text())

    def test_same_plan_joins_and_keeps_per_value_provenance(self):
        old = self.row(plan_type='普通', admission='一般统考生')
        new = self.row(rank=19000, plan_type='普通', admission='一般统考生')
        _, rows, _ = self.run_pool([(2024,[old]),(2025,[new])])
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['rank_2024'],rows[0]['rank_2025']),('20000','19000'))
        self.assertEqual(rows[0]['plan_type'],'普通')
        self.assertEqual(rows[0]['source_admission_type_raw'],'一般统考生')
        self.assertEqual(rows[0]['limits'],'')
        self.assertEqual(json.loads(rows[0]['data_provenance']),{
            '2024':json.loads(old['data_provenance']),'2025':json.loads(new['data_provenance'])})

    def test_changed_plan_does_not_borrow_old_year(self):
        _, rows, log = self.run_pool([(2024,[self.row(plan_type='国家专项计划')]),
                                     (2025,[self.row(rank=19000,plan_type='普通')])])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['rank_2024'],'')
        self.assertNotIn('2024',json.loads(rows[0]['data_provenance']))
        self.assertIn('未采用以下年份：2024',rows[0]['note'])
        self.assertEqual(log['plan_scope_history_gaps'][0]['years'],[2024])

    def test_unknown_and_absent_plan_are_not_proof_of_same_scope(self):
        legacy = dict(code='10285',name='苏州大学',major='计算机',rank='20000',plan='10')
        for old in (legacy,self.row(plan_type='未标')):
            _, rows, _ = self.run_pool([(2024,[old]),(2025,[self.row(rank=19000,plan_type='普通')])])
            self.assertEqual(rows[0]['rank_2024'],'')
        _, rows, _ = self.run_pool([(2025,[self.row(plan_type='未标')])])
        self.assertEqual(rows[0]['plan_type'],'未标')
        self.assertEqual(rows[0]['limits'],'')  # 未标不能冒称已核普通，也不凭空断言它是专项。
        _, rows, _ = self.run_pool([(2024,[self.row(plan_type='未标')]),(2025,[self.row(rank=19000,plan_type='未标')])])
        self.assertEqual(rows[0]['rank_2024'],'')  # 两个“未标”也不是同口径证据。

    def test_hidden_original_type_is_excluded_without_changing_names(self):
        for kind in ('国家专项计划','民族班','中外合作办学','预科'):
            _, rows, log = self.run_pool([(2025,[self.row(admission=kind)])])
            self.assertEqual(rows,[],kind)
            self.assertEqual(log['dropped']['排除词（需单独资格、异地培养或学费不同）'],1)

    def test_bare_identity_and_region_labels_follow_existing_default_exclusions(self):
        for kind in ('少数民族','面向厦门'):
            for field in ('plan_type','admission'):
                for flags in ((),('--plan-brackets','legacy')):
                    value=self.row(**{field:kind})
                    _, rows, _ = self.run_pool([(2025,[value])],extra=flags)
                    self.assertEqual(rows,[],(kind,field,flags))
                    _, rows, _ = self.run_pool([(2025,[value])],extra=flags+('--exclude',''))
                    self.assertEqual(len(rows),1)
                    self.assertTrue(check_report.pending(rows[0]))

    def test_override_and_legacy_bracket_flag_do_not_erase_pending_qualification(self):
        for extra in (('--exclude',''),('--exclude','','--plan-brackets','legacy')):
            _, rows, log = self.run_pool([(2025,[self.row(plan_type='国家专项计划',admission='国家专项计划')])],extra=extra)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['name'],'苏州大学·计算机')
            self.assertIn('资格待核：国家专项计划',rows[0]['limits'])
            self.assertTrue(check_report.pending(rows[0]))
            self.assertIn('需核对报名资格',report.pending_note(rows[0]))
            self.assertEqual(log['eligibility_pending'],['苏州大学·计算机'])

    def test_unrecognized_nonordinary_label_is_retained_but_pending(self):
        _, rows, _ = self.run_pool([(2025,[self.row(plan_type='联培项目')])])
        self.assertEqual(len(rows),1)
        self.assertIn('资格待核：联培项目',rows[0]['limits'])

    def test_same_year_different_scopes_cannot_duplicate_an_optimizer_id(self):
        values=[self.row(plan_type='普通'),self.row(rank=18000,plan_type='国家专项计划')]
        _, ordinary, _ = self.run_pool([(2025,values)])
        self.assertEqual(len(ordinary),1)
        self.assertEqual(ordinary[0]['plan_type'],'普通')
        _, rows, log = self.run_pool([(2025,values)],extra=('--exclude',''))
        self.assertEqual(rows,[])
        self.assertEqual(log['plan_scope_ambiguous_ids'],['10285-计算机'])
        self.assertEqual(log['eligibility_pending'],[])
        self.assertEqual(log['dropped']['同一志愿有多个计划口径，须先按计划类型筛选来源'],2)

    def test_plan_claims_must_agree_and_invalid_objects_are_rejected(self):
        value=self.row(plan_type='普通')
        value['plan_type']='国家专项计划'
        self.assertIn('计划条件 plan_type 不一致',self.run_pool([(2025,[value])],fail=True))
        for original in ('bad',{'source_scope_original':['bad']}):
            value=self.row(plan_type='普通');facts=json.loads(value['data_provenance'])
            facts['rank']['original_scope']=original;value['data_provenance']=json.dumps(facts)
            self.assertIn('必须为对象',self.run_pool([(2025,[value])],fail=True))
        value=self.row(plan_type='普通',score='600');facts=json.loads(value['data_provenance'])
        facts['score']={'value':600,'scope':{'plan_type':'国家专项计划'}};value['data_provenance']=json.dumps(facts)
        self.assertIn('计划条件 plan_type 不一致',self.run_pool([(2025,[value])],fail=True))

    def test_null_optional_fact_does_not_supply_plan_scope(self):
        value=self.row(plan_type='普通');value['plan']='';facts=json.loads(value['data_provenance'])
        facts['plan']={'value':None,'scope':{'plan_type':'国家专项计划'}};value['data_provenance']=json.dumps(facts)
        _, rows, _ = self.run_pool([(2025,[value])])
        self.assertEqual(rows[0]['plan_type'],'普通')
        self.assertEqual(rows[0]['limits'],'')

    def test_verified_group_mapping_does_not_override_plan_conditions(self):
        mapping=self.write('map.csv',[{'year':2024,'code':'10285','group':'A','history_key':'same','source':'离线核对夹具'},
                                      {'year':2025,'code':'10285','group':'B','history_key':'same','source':'离线核对夹具'}])
        _, rows, _ = self.run_pool([(2024,[self.row(group='A',plan_type='国家专项计划')]),
                                  (2025,[self.row(group='B',plan_type='普通')])],extra=('--key','group','--group-map',str(mapping)))
        self.assertEqual(rows[0]['rank_2024'],'')
        self.assertEqual(rows[0]['history_status'],'latest_only')

    def test_plan_fields_survive_optimization_with_reader_warning(self):
        _, rows, _ = self.run_pool([(2025,[self.row(plan_type='联培项目',admission='合作培养')])],extra=('--exclude',''))
        data=self.write('utility.csv',[dict(rows[0],utility='80')]);output=self.root/'optimized.json'
        result=subprocess.run([sys.executable,str(SCRIPTS/'optimize.py'),str(data),'--rank','10000','--u-fall','-60',
                               '--slots','1','--sims','100','--seed','7','--json',str(output)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        item=json.loads(output.read_text())['list'][0]
        self.assertEqual(item['plan_type'],'联培项目')
        self.assertEqual(item['source_admission_type_raw'],'合作培养')
        self.assertTrue(check_report.pending(item))
        self.assertIn('合作培养',report.pending_note(item))
        self.assertEqual(item['data_provenance']['2025']['rank']['value'],20000)

    def test_declared_empty_plan_fields_survive_optimization(self):
        _, rows, _ = self.run_pool([(2025,[self.row(plan_type='')])])
        data=self.write('unknown-utility.csv',[dict(rows[0],utility='80')]);output=self.root/'unknown-optimized.json'
        result=subprocess.run([sys.executable,str(SCRIPTS/'optimize.py'),str(data),'--rank','10000','--u-fall','-60',
                               '--slots','1','--sims','100','--seed','7','--json',str(output)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        item=json.loads(output.read_text())['list'][0]
        self.assertIn('plan_type',item)
        self.assertIn('source_admission_type_raw',item)
        self.assertEqual(item['plan_type'],'')
        self.assertEqual(item['source_admission_type_raw'],'')

    def test_input_without_plan_fields_does_not_acquire_structured_columns(self):
        _, rows, _ = self.run_pool([(2024,[self.row()]),(2025,[self.row(rank=19000)])])
        self.assertEqual(rows[0]['rank_2024'],'20000')
        self.assertNotIn('plan_type',rows[0])
        self.assertNotIn('source_admission_type_raw',rows[0])


if __name__ == '__main__':
    unittest.main()
