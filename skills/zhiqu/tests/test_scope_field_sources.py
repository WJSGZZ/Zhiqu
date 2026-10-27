"""选科原标签单独引用学校原文，不借源给分数、不跨年或路线。"""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'))
import gaokao_export as ex
import zhiqu_db as db


class ScopeSourceTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.addCleanup(self.c.close)
        self.c.executescript("""ATTACH DATABASE ':memory:' AS data;
        CREATE TABLE data.source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,archive_sha256 TEXT);
        INSERT INTO data.source VALUES('cut','官方','省考试院','2025投档表','https://example.gov.cn/cut','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
        INSERT INTO data.source VALUES('req','官方','甲大学','2025河北专业原标签','https://example.edu.cn/requirements','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb');
        CREATE TABLE data.gk_official_original_evidence(record_id TEXT PRIMARY KEY,table_name TEXT,source_id TEXT,excerpt_locator_json TEXT);
        CREATE TABLE data.official_cutoff_scope(source_id TEXT,public_record TEXT,scope_json TEXT,locator_json TEXT);
        CREATE TABLE data.gk_official_cutoff(province TEXT,year INT,subject TEXT,code TEXT,name TEXT,major TEXT,major_code TEXT,institution_id TEXT,score INT,rank INT,source_id TEXT,src TEXT,value_status TEXT);
        INSERT INTO data.gk_official_cutoff VALUES('河北',2025,'物理','0001','甲大学','计算机','11','1234567890',600,1000,'cut','public.csv:2','{"score":{"status":"官方原值"},"rank":{"status":"官方原值"}}');
        """)
        self.raw=dict(self.c.execute('SELECT * FROM data.gk_official_cutoff').fetchone())
        self.scope={'batch':'本科批','subject_requirements':'物理+化学'}
        self.proof={'record_id':'scope-proof-1','source_id':'req','value':'物理+化学','excerpt':'计算机--物理+化学',
            'business_key':{k:self.raw[k]for k in ('source_id','src','institution_id','year','province','subject','major')},
            'locator':{'url':'https://example.edu.cn/requirements','sha256':'b'*64,'table':1,'row':3,'column':1},
            'review':{'status':'approved','approved_by':'root','dual_read_equal':True,
                      'manifest_sha256':'c'*64,'sample_proof_sha256':'d'*64,'independent_review_sha256':'e'*64}}
        self.loc={'sha256':'a'*64,'row':9,'scope_field_sources':{'subject_requirements':self.proof}}
        self.save()

    def save(self):
        self.c.execute('INSERT OR REPLACE INTO data.gk_official_original_evidence VALUES(?,?,?,?)',('scope-proof-1','official_cutoff_scope','req',json.dumps(self.proof)))
        self.c.execute('DELETE FROM data.official_cutoff_scope')
        self.c.execute('INSERT INTO data.official_cutoff_scope VALUES(?,?,?,?)',('cut','public.csv:2',json.dumps(self.scope),json.dumps(self.loc)))

    def resolve(self):return ex.scope_field_sources(self.c,db._tables(self.c),self.raw,self.scope,self.loc)

    def test_verified_label_has_own_source_without_reassigning_scores(self):
        resolved,errors=self.resolve();self.assertFalse(errors)
        self.assertEqual(resolved['subject_requirements']['source']['source_id'],'req')
        row=ex.collect(self.c,db._tables(self.c),'河北','物理',[2025])[0]
        self.assertEqual(row['requirement'],'物理+化学')
        self.assertEqual(row['provenance']['score']['source_id'],'cut')
        self.assertEqual(row['provenance']['score']['value'],600)
        self.assertEqual(row['provenance']['score']['scope_sources']['subject_requirements']['source']['source_id'],'req')
        record=db._record(self.c,'gk_official_cutoff',self.raw)
        self.assertEqual(record['values']['score']['source_id'],'cut')
        self.assertEqual(record['sources'][0]['source']['source_id'],'req')

    def test_wrong_year_program_target_or_json_type_not_approved(self):
        for field,value in [('year',2026),('year',2025.0),('province','江苏'),('subject','历史'),
                            ('major','软件工程'),('src','other:2'),('source_id','other'),('institution_id','0000000000')]:
            with self.subTest(field=field,value=value):
                original=copy.deepcopy(self.proof['business_key']);self.proof['business_key'][field]=value
                self.assertTrue(self.resolve()[1]);self.proof['business_key']=original

    def test_missing_source_bad_grade_fingerprint_review_or_value_rejected(self):
        for field,value in [('source_id','absent'),('value','不限'),('excerpt','')]:
            old=self.proof[field];self.proof[field]=value;self.assertTrue(self.resolve()[1]);self.proof[field]=old
        for field,value in [('status','pending'),('dual_read_equal',1),('sample_proof_sha256',''),('independent_review_sha256','')]:
            old=self.proof['review'][field];self.proof['review'][field]=value;self.assertTrue(self.resolve()[1]);self.proof['review'][field]=old
        self.c.execute("UPDATE data.source SET grade='第三方整理' WHERE source_id='req'");self.assertTrue(self.resolve()[1])
        self.c.execute("UPDATE data.source SET grade='官方',archive_sha256=? WHERE source_id='req'",('f'*64,));self.assertTrue(self.resolve()[1])

    def test_invalid_supplement_retains_numeric_query_but_not_candidate_scope(self):
        self.proof['value']='不限';self.save()
        record=db._record(self.c,'gk_official_cutoff',self.raw)
        self.assertEqual(record['values']['score']['value'],600)
        self.assertNotIn('subject_requirements',record['context'])
        self.assertIn('待核',record['context']['subject_requirements_status'])
        row=ex.collect(self.c,db._tables(self.c),'河北','物理',[2025])[0]
        self.assertFalse(row['scope_conflicts']);self.assertTrue(row['scope_source_errors'])
        self.assertEqual(row['requirement'],'')
        with tempfile.TemporaryDirectory()as out:
            result=ex.export_records([row],'河北','物理',[2025],out=out,key='major')
        self.assertEqual(result['exported_rows']['2025'],1)

    def test_missing_or_different_audit_proof_cannot_approve_reference(self):
        for field,value in [('record_id','other-proof'),('excerpt','随便的标签')]:
            original=self.proof[field];self.proof[field]=value
            self.assertTrue(self.resolve()[1]);self.proof[field]=original
        original=self.proof['review']['manifest_sha256'];self.proof['review']['manifest_sha256']='f'*64
        self.assertTrue(self.resolve()[1]);self.proof['review']['manifest_sha256']=original
        self.c.execute('DELETE FROM data.gk_official_original_evidence');self.assertTrue(self.resolve()[1])

    def test_registered_audit_still_requires_real_coordinate_and_source_url(self):
        original=copy.deepcopy(self.proof['locator'])
        for field,value in [('row',None),('row',True),('row',0),('table',-1),('column','1'),('column',0),('url','https://other.edu.cn/a')]:
            with self.subTest(field=field,value=value):
                self.proof['locator']=dict(original);self.proof['locator'][field]=value;self.save()
                self.assertTrue(self.resolve()[1])
        self.proof['locator']=original;self.save();self.assertFalse(self.resolve()[1])

    def test_bad_supplement_does_not_erase_independent_native_requirement(self):
        self.c.execute('ALTER TABLE data.gk_official_cutoff ADD COLUMN subject_requirements TEXT')
        self.c.execute('UPDATE data.gk_official_cutoff SET subject_requirements=?',('物理+生物',))
        self.proof['value']='不限';self.save()
        row=ex.collect(self.c,db._tables(self.c),'河北','物理',[2025])[0]
        self.assertEqual(row['requirement'],'物理+生物')
        self.assertFalse(row['scope_conflicts']);self.assertTrue(row['scope_source_errors'])
        self.assertEqual(row['provenance']['score']['value'],600)
        raw=dict(self.c.execute('SELECT * FROM data.gk_official_cutoff').fetchone())
        for native_key in ('subject_requirements','subject_req_raw'):
            record=db._record(self.c,'gk_official_cutoff',{**self.raw,native_key:raw['subject_requirements']})
            self.assertEqual(record['context']['subject_requirements'],'物理+生物')
            self.assertEqual(record['values']['score']['value'],600)
            self.assertNotIn('scope_sources',record)

    def test_wrong_json_types_return_pending_instead_of_crashing(self):
        for value in [[],{},None,True,1,'']:
            original=self.proof['source_id'];self.proof['source_id']=value
            self.assertTrue(self.resolve()[1]);self.proof['source_id']=original
        for value in [[],{},None,True,1]:
            original=self.proof['locator']['url'];self.proof['locator']['url']=value;self.save()
            self.assertTrue(self.resolve()[1]);self.proof['locator']['url']=original;self.save()

    def test_malformed_reference_is_not_silently_native(self):
        self.loc['scope_field_sources']=[]
        self.assertTrue(self.resolve()[1])
