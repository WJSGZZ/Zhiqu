"""质量摘要的分母、领域与只读路由边界。"""
import csv
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import data_quality as q
import db_storage


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.c = sqlite3.connect(':memory:', factory=db_storage.StorageConnection)
        self.addCleanup(self.c.close)
        self.c.execute("ATTACH DATABASE ':memory:' AS data")
        self.c.execute("ATTACH DATABASE ':memory:' AS audit")
        self.c.execute('CREATE TABLE data.source(source_id TEXT PRIMARY KEY,grade TEXT)')
        self.c.executemany('INSERT INTO data.source VALUES (?,?)', [('o','官方'), ('t','第三方整理'), ('unused','官方')])
        self.c.execute('CREATE TABLE data.ky_score_dist(source_id TEXT,value_status TEXT,n INT,list_type TEXT,scope_mismatch TEXT,quarantine_reason TEXT)')
        self.c.executemany('INSERT INTO data.ky_score_dist VALUES (?,?,?,?,?,?)', [
            ('o','官方原值',3,'复试','0',''), ('o','官方原值',10,'复试','0',''),
            ('t','第三方整理未核',2,'拟录取','1','待核'), ('unknown',None,5,'拟录取',None,None)])
        self.c.execute('CREATE TABLE audit.ky_ingest_issue(kind TEXT)')
        self.c.execute("INSERT INTO audit.ky_ingest_issue VALUES ('unmatched_school')")
        self.c.routes = {'ky_ingest_issue': 'audit', 'ky_check_sample': 'temp'}
        self.c.storage_logical_names = {'ky_ingest_issue','ky_check_sample'}
        self.c.execute('CREATE TEMP VIEW ky_check_sample AS SELECT 1 AS check_id,\'一致\' AS status')
        self.c.execute('CREATE TABLE data.dataset_version(version TEXT)')
        self.c.executemany('INSERT INTO data.dataset_version VALUES (?)', [('9.0.0',), ('16.9.0',), ('16.10.0',)])
        self.c.execute('CREATE TABLE data.correction(table_name TEXT,reason TEXT)')
        self.c.executemany('INSERT INTO data.correction VALUES (?,?)', [('ky_score_dist','口径'), ('gk_result','录入'), ('kyXelse','不应匹配')])

    def write_coverage(self, domain='高考', rows=None):
        fields = ['province','year','category','status','verified_complete','reason'] if domain == '高考' else ['school','year','scope_level','status','verified_complete','reason','deferred_reason']
        p = self.root/('gaokao.csv' if domain == '高考' else 'kaoyan.csv')
        with p.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows or [])
        return p

    def test_source_denominator_is_referenced_distinct_sources(self):
        r=q.layer(self.c,'统计','ky_score_dist',q.db._tables(self.c))
        self.assertEqual(r['source_grades'],{'官方':1,'第三方整理':1,'来源未登记':1})
        self.assertEqual(r['rows'],4)
        self.assertEqual(r['small_group_rows'],1)
        self.assertEqual(r['quarantine_rows'],1)
        self.assertEqual(r['list_type_rows'],{'复试':2,'拟录取':2})

    def test_audit_and_temp_routes_not_missing_or_doubled(self):
        r=q.audit(self.c,q.db._tables(self.c),'考研')
        self.assertEqual(r['ky_ingest_issue']['rows'],1)
        self.assertEqual(r['ky_check_sample']['rows'],1)
        self.assertEqual(r['correction']['rows'],1)
        self.assertNotIn('total',r)

    def test_missing_tables_and_denominator_are_unknown(self):
        r=q.build(self.c,self.root)
        self.assertIsNone(r['domains']['高考']['coverage']['cells'])
        self.assertIsNone(r['domains']['高考']['layers'][0]['rows'])
        self.assertIsNone(r['domains']['考研']['dual_read_rate']['value'])
        self.assertEqual(r['database_version'],'16.10.0')

    def test_obtained_and_strict_complete_separate(self):
        p=self.write_coverage(rows=[{'province':'河北','year':'2025','category':'投档线','status':'obtained','verified_complete':'false'},
            {'province':'河北','year':'2026','category':'投档线','status':'partial','verified_complete':'true','reason':'仅一批'}])
        before=p.read_bytes();r=q.coverage(p,'高考')
        self.assertEqual(r['status_cells'],{'obtained':1,'partial':1})
        self.assertEqual(r['verified_complete_cells'],1)
        self.assertEqual(r['not_obtained_reason_cells'],{'仅一批':1})
        self.assertEqual(p.read_bytes(),before)

    def test_deferred_not_fetch_failure(self):
        p=self.write_coverage('考研',[{'school':'某校','year':'2026','scope_level':'目录','status':'not fetched','reason':'未查询','deferred_reason':'按需取'}])
        self.assertEqual(q.coverage(p,'考研')['not_obtained_reason_cells'],{'按需取':1})

    def test_duplicate_or_malformed_cells_rejected(self):
        row={'province':'河北','year':'2025','category':'投档线','status':'obtained'}
        p=self.write_coverage(rows=[row,row])
        with self.assertRaisesRegex(ValueError,'重复格'):
            q.coverage(p,'高考')
        p.write_text('status\nobtained\n')
        with self.assertRaisesRegex(ValueError,'必需列'):
            q.coverage(p,'高考')

    def test_value_status_count_is_per_field_and_no_raw_reason(self):
        self.c.execute('UPDATE data.ky_score_dist SET value_status=?',
            (json.dumps({'min': {'status':'官方原值','reason':'不应输出原行'},
                         'max': {'status':'原件缺失'}}),))
        r=q.value_status(self.c,'ky_score_dist')
        self.assertEqual(r['field_status_counts']['min'],{'官方原值':4})
        self.assertEqual(r['field_status_counts']['max'],{'原件缺失':4})
        self.assertNotIn('不应输出',json.dumps(r,ensure_ascii=False))
        self.assertEqual(r['non_mapping_rows'],0)

    def test_new_issue_groups_and_non_mirrored_checks_separate(self):
        self.c.execute('CREATE TABLE data.purchased_check(sample_mirrored INT,verdict TEXT)')
        self.c.executemany('INSERT INTO data.purchased_check VALUES (?,?)',[(1,'一致'),(0,'不一致'),(None,'未取到')])
        self.c.execute('CREATE TEMP VIEW v_core_delta_ingest_issue AS SELECT 42 AS occurrence_count')
        self.c.storage_logical_names.add('v_core_delta_ingest_issue')
        self.c.routes['v_core_delta_ingest_issue']='temp'
        r=q.extra_audit(self.c,q.db._tables(self.c),'高考')
        self.assertEqual(r['purchased_check_unmirrored']['rows'],2)
        self.assertEqual(r['purchased_check_unmirrored']['outcomes'],{'不一致':1,'未取到':1})
        self.assertEqual(r['v_core_delta_ingest_issue']['rows'],1)
        self.assertEqual(r['v_core_delta_ingest_issue']['occurrences'],42)

    def test_non_prefixed_corrections_are_visible_shared(self):
        self.c.execute("INSERT INTO data.correction VALUES ('staging_kaoyan_candidate','历史问题')")
        self.c.execute("INSERT INTO data.correction VALUES (NULL,'无归属')")
        r=q.shared_audit(self.c,q.db._tables(self.c))
        self.assertEqual(r['correction_without_domain_prefix']['rows'],3)
        self.assertEqual(r['correction_without_domain_prefix']['by_table'],{'kyXelse':1,'staging_kaoyan_candidate':1,'未标':1})

    def test_comparable_check_denominator_excludes_scope_missing_and_unknown(self):
        self.c.execute('CREATE TABLE data.samples(verdict TEXT)')
        self.c.executemany('INSERT INTO data.samples VALUES (?)',[(x,) for x in ['一致','一致','不一致','口径不同','未取到','synthetic-private',None]])
        r=q.check_outcomes(self.c,'samples','verdict')
        self.assertEqual(r['recorded_checks'],7);self.assertEqual(r['comparable_checks'],3)
        self.assertEqual(r['agreement_rate'],2/3);self.assertEqual(r['outcome_counts']['其他或未标'],2)
        self.assertIsNone(r['manual_gold_accuracy']);self.assertIsNone(r['population_coverage_rate'])
        self.assertNotIn('synthetic-private',json.dumps(r))

    def test_zero_comparable_denominator_and_absent_field_are_unknown(self):
        self.c.execute('CREATE TABLE data.samples(verdict TEXT)')
        for values in [[],[('未取到',),('口径不同',)]]:
            self.c.execute('DELETE FROM data.samples');self.c.executemany('INSERT INTO data.samples VALUES (?)',values)
            r=q.check_outcomes(self.c,'samples','verdict');self.assertIsNone(r['agreement_rate'])
            self.assertEqual(r['comparable_checks'],0)
        r=q.check_outcomes(self.c,'samples','status');self.assertFalse(r['available']);self.assertIsNone(r['agreement_rate'])

    def test_check_channels_keep_domain_and_mirror_filters_without_pooling(self):
        self.c.execute('CREATE TABLE data.check_sample(domain TEXT,verdict TEXT)')
        self.c.executemany('INSERT INTO data.check_sample VALUES (?,?)',[('高考','不一致'),('考研','一致'),('就业','一致')])
        self.c.execute('CREATE TABLE data.purchased_check(sample_mirrored INT,verdict TEXT)')
        self.c.executemany('INSERT INTO data.purchased_check VALUES (?,?)',[(1,'一致'),(0,'不一致'),(None,'未取到')])
        r=q.audit(self.c,q.db._tables(self.c),'考研')
        self.assertEqual(r['check_sample']['check_outcomes']['recorded_checks'],1)
        self.assertEqual(r['ky_check_sample']['check_outcomes']['recorded_checks'],1)
        self.assertNotIn('total',r)
        r=q.extra_audit(self.c,q.db._tables(self.c),'高考')['purchased_check_unmirrored']['check_outcomes']
        self.assertEqual(r['recorded_checks'],2);self.assertEqual(r['comparable_checks'],1);self.assertEqual(r['agreement_rate'],0)

    def test_markdown_names_recorded_agreement_not_manual_accuracy(self):
        report=q.build(self.c,self.root);text=q.markdown(report,'考研')
        self.assertIn('1/1，100.00%',text);self.assertIn('不是人工真值准确率',text)
        self.assertIn('不合并比例',text)

    def test_build_does_not_write_database(self):
        before=list(self.c.iterdump());q.build(self.c,self.root)
        self.assertEqual(list(self.c.iterdump()),before)

    def test_markdown_does_not_claim_global_pass_or_sum(self):
        r=q.build(self.c,self.root);text=q.markdown(r,'考研')
        self.assertIn('不可计算',text)
        self.assertIn('不能相加',text)
        self.assertIn('来源未登记',text)


if __name__=='__main__':
    unittest.main()
