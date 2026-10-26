import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts/gaokao_export.py'
spec = importlib.util.spec_from_file_location('auxiliary_export_under_test', SCRIPT)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)


class AuxiliaryExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'fixture.sqlite'
        self.c = sqlite3.connect(self.path)
        self.c.execute('CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT,archive_sha256 TEXT)')
        for sid,grade,digest in [('book','官方','a'*64),('fix','官方','b'*64),('vendor','第三方整理','c'*64)]:
            self.c.execute('INSERT INTO source VALUES(?,?,?,?,?,?,?)',(sid,grade,'发布者',sid,'https://example.edu.cn/'+sid,'',digest))
        self.c.execute('CREATE TABLE gk_official_plan(record_id TEXT PRIMARY KEY,province TEXT,year INT,subject TEXT,institution_id TEXT,school_raw TEXT,school_code TEXT,group_code TEXT,major_code TEXT,major_name TEXT,batch TEXT,plan_type TEXT,plan_n INT,gender TEXT,subject_requirements TEXT,scope_raw TEXT,source_id TEXT,src_row TEXT,src_page INT,src_table TEXT,locator_method TEXT,value_status TEXT)')
        self.c.execute('CREATE TABLE gk_batch_line(record_id TEXT PRIMARY KEY,province TEXT,year INT,subject TEXT,education_level TEXT,line_scope TEXT,total REAL,requirements_json TEXT,source_id TEXT,src_row TEXT,src_page INT,src_table TEXT,locator_method TEXT,value_status TEXT)')
        self.c.execute('CREATE TABLE gk_official_original_evidence(record_id TEXT,table_name TEXT,source_id TEXT,excerpt_locator_json TEXT)')
        self.tables={'gk_official_plan','gk_batch_line'}

    def tearDown(self):
        self.c.close();self.tmp.cleanup()

    def plan(self,rid='p',value=3,source='book',scope=None,plan_type='普通',school='学校甲',state='官方原值',major='01',group='001'):
        values=[rid,'省甲',2025,'历史','1234567890',school,'0010',group,major,'原专业','本科',plan_type,value,None,'不限',json.dumps(scope or {},ensure_ascii=False),source,'7',5,'2','原格',json.dumps({'plan_n':{'status':state,'reason':'实际状态'}})]
        self.c.execute('INSERT INTO gk_official_plan VALUES('+','.join('?'for _ in values)+')',values)

    def line(self):
        self.c.execute('INSERT INTO gk_batch_line VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('b','省甲',2025,'历史','本科','普通本科',400,'{}','book','1',1,'1','原格','{}'))

    def read(self,**kw):
        self.c.commit()
        return E.collect_auxiliary(self.c,self.tables,'省甲','历史',[2025],**kw)

    def correction(self,rid='p',field='plan_n',before=606,after=656,scope_after=None,broken=False):
        after = after if scope_after is None else scope_after
        cell={'field':field,'before':before,'after':after,'source_id':'fix','sha256':'z'*64 if broken else'b'*64,'locator':{'page':2,'table':3,'row':4,'columns':['原','更正']}}
        payload={'business_key':{'record_id':rid},'locator':{'sha256':'a'*64,'page':5,'table':2,'row':7},'review':{'status':'approved','approved_by':'root','semantic_approved':True},'excerpt':{'更正原格':cell}}
        self.c.execute('INSERT INTO gk_official_original_evidence VALUES(?,?,?,?)',(rid,'gk_official_plan','book',json.dumps(payload)))

    def test_exact_scope_plan_types_and_school_filter_leave_province_line(self):
        self.plan('p1',plan_type='普通');self.plan('p2',plan_type='中外合作');self.plan('p3',school='学校乙');self.line()
        got=self.read(schools=['学校甲'],batch='本科',plan_type='普通')
        self.assertEqual([x['record_id']for x in got['plans']],['p1'])
        self.assertEqual(len(got['batch_lines']),1)
        self.assertEqual(self.read(schools=['0010'])['plans'][0]['major_code'],'01')
        self.assertEqual(len(E.collect_auxiliary(self.c,self.tables,'省甲','物理',[2025])['plans']),0)
        self.assertEqual(len(E.collect_auxiliary(self.c,self.tables,'省甲','历史',[2026])['plans']),0)

    def test_null_zero_grade_and_missing_source(self):
        self.plan('null',None);self.plan('zero',0);self.plan('vendor',4,'vendor');self.plan('missing',2,'absent')
        got=self.read();by={x['record_id']:x for x in got['plans']}
        self.assertIsNone(by['null']['plan_n']);self.assertEqual(by['zero']['plan_n'],0)
        self.assertEqual(by['vendor']['source_grade'],'第三方整理·内部未核')
        self.assertEqual(by['vendor']['data_provenance']['plan_n']['grade'],'第三方整理')
        self.assertEqual(by['zero']['source_grade'],'官方')
        self.assertEqual(got['rejected'][0]['record_id'],'missing')

    def test_numeric_correction_uses_real_source_locator_and_original(self):
        scope={'更正依据':{'field':'plan_n','source_id':'fix','原值':606,'更正后':656}}
        self.plan(value=656,scope=scope,state='人工更正');self.correction()
        got=self.read()['plans'][0];meta=got['data_provenance']['plan_n']
        self.assertEqual((got['source_id'],got['src_page'],got['src_table'],got['src_row']),('fix',2,'3','4'))
        self.assertEqual(meta['value'],656);self.assertEqual(meta['source_id'],'fix')
        self.assertEqual(meta['original_provenance']['value'],606)
        self.assertEqual(meta['original_provenance']['source_id'],'book')

    def test_code_only_correction_does_not_steal_plan_source(self):
        scope={'更正依据':[{'field':'major_code','source_id':'fix','原值':'02','现行值':'01'}]}
        self.plan(value=7,scope=scope);self.correction(field='major_code',before='02',after='01')
        row=self.read()['plans'][0]
        self.assertEqual(row['source_id'],'book');self.assertEqual(row['data_provenance']['plan_n']['source_id'],'book')
        self.assertEqual(row['data_provenance']['major_code']['source_id'],'fix')
        self.assertEqual(row['data_provenance']['major_code']['value'],'01')

    def test_missing_invalid_and_duplicate_correction_chains_reject(self):
        scope={'更正依据':{'field':'plan_n','source_id':'fix','更正后':656}}
        self.plan(value=656,scope=scope,state='人工更正')
        self.assertEqual(len(self.read()['rejected']),1)
        self.correction(broken=True)
        self.assertEqual(len(self.read()['rejected']),1)
        self.c.execute('DELETE FROM gk_official_original_evidence');self.correction();self.correction()
        self.assertEqual(len(self.read()['rejected']),1)

    def test_code_after_is_string_not_lossy_numeric(self):
        scope={'更正依据':{'field':'major_code','source_id':'fix','更正后':'01'}}
        self.plan(scope=scope);self.correction(field='major_code',before='02',after=1)
        self.assertEqual(len(self.read()['rejected']),1)

    def test_explicit_full_scope_text_is_used_without_reconstruction(self):
        field='scope_raw.专业备注现行';after='固边计划，定向到地区甲就业';before='固边计划，定向到地区乙就业'
        self.plan(scope={'专业备注现行':after,'更正依据':[{'field':field,'source_id':'fix','现行值':after}]})
        self.correction(field=field,before='地区乙',after='地区甲')
        row=self.c.execute('SELECT excerpt_locator_json FROM gk_official_original_evidence').fetchone()
        payload=json.loads(row[0]);payload['excerpt']['更正原格'].update(after_full_raw=after,before_full_raw=before)
        self.c.execute('UPDATE gk_official_original_evidence SET excerpt_locator_json=?',(json.dumps(payload),))
        got=self.read()['plans'][0]
        self.assertEqual(got['data_provenance'][field]['value'],after)
        self.assertEqual(got['data_provenance'][field]['original_provenance']['value'],before)
        self.assertEqual(got['data_provenance']['plan_n']['source_id'],'book')

    def test_export_is_readonly_and_refuses_all_existing_destinations(self):
        self.plan(value=0);self.line();self.c.commit();before=self.path.read_bytes()
        got=self.read();out=Path(self.tmp.name)/'export'
        exported=E.export_auxiliary(got,'省甲','历史',[2025],out=out)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(exported['plan_exported_rows'][2025],1)
        self.assertEqual(exported['volunteer_candidates_added'],0)
        with Path(exported['plan_files'][2025]).open()as f:row=next(csv.DictReader(f))
        self.assertEqual(row['major_code'],'01');self.assertEqual(row['plan_n'],'0')
        self.assertEqual(json.loads(row['data_provenance'])['plan_n']['value'],0)
        second=Path(self.tmp.name)/'collision';second.mkdir();block=second/'省甲-历史-2025-batch-lines.csv';block.write_text('keep')
        with self.assertRaises(FileExistsError):E.export_auxiliary(got,'省甲','历史',[2025],out=second)
        self.assertEqual([x.name for x in second.iterdir()],[block.name])
        self.assertEqual(block.read_text(),'keep')

    def test_legacy_fixture_without_tables_is_empty(self):
        self.assertEqual(E.collect_auxiliary(self.c,set(),'省甲','历史',[2025])['plans'],[])

    def test_normal_rows_do_not_query_audit(self):
        self.plan();queries=[];self.c.set_trace_callback(queries.append);self.read();self.c.set_trace_callback(None)
        self.assertFalse(any('SELECT * FROM main.gk_official_original_evidence'in x for x in queries))


    def test_entrypoint_exports_auxiliary_without_fabricating_pool_candidates(self):
        import contextlib
        import sys
        from unittest.mock import patch
        sys.path.insert(0,str(SCRIPT.parent))
        import zhiqu_db as db
        self.plan(value=0);self.line();self.c.commit()
        @contextlib.contextmanager
        def connection(*args,**kwargs):
            c=sqlite3.connect(':memory:',uri=True);c.row_factory=sqlite3.Row
            c.execute('ATTACH DATABASE ? AS data',(self.path.as_uri()+'?mode=ro',))
            try:yield c,self.path
            finally:c.close()
        before=self.path.read_bytes();out=Path(self.tmp.name)/'entrypoint'
        with patch.object(db,'_open',connection),patch.object(db,'_tables',return_value=self.tables):
            result=db.export_gaokao('省甲','历史',[2025],out=out)
            self.assertEqual(result['status'],'partial')
            self.assertEqual(result['candidate_status'],'missing_data')
            self.assertEqual(result['exported_rows'],{'2025':0})
            self.assertEqual(result['plan_exported_rows'],{'2025':1})
            self.assertEqual(result['batch_line_exported_rows'],{'2025':1})
            self.assertIn('志愿候选和一分一段仍缺',result['message'])
            blocked=Path(self.tmp.name)/'blocked';blocked.mkdir()
            target=blocked/'省甲-历史-2025-batch-lines.csv';target.write_text('do not overwrite')
            with self.assertRaises(db.QueryError):db.export_gaokao('省甲','历史',[2025],out=blocked)
            self.assertEqual(list(blocked.iterdir()),[target])
        self.assertEqual(self.path.read_bytes(),before)

    def test_entrypoint_batch_lines_only_remain_visible(self):
        import contextlib
        import sys
        from unittest.mock import patch
        sys.path.insert(0,str(SCRIPT.parent))
        import zhiqu_db as db
        self.line();self.c.commit()
        @contextlib.contextmanager
        def connection(*args,**kwargs):
            c=sqlite3.connect(':memory:',uri=True);c.row_factory=sqlite3.Row
            c.execute('ATTACH DATABASE ? AS data',(self.path.as_uri()+'?mode=ro',))
            try:yield c,self.path
            finally:c.close()
        with patch.object(db,'_open',connection),patch.object(db,'_tables',return_value=self.tables):
            result=db.export_gaokao('省甲','历史',[2025],out=Path(self.tmp.name)/'only-lines')
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['plan_exported_rows'],{'2025':0})
        self.assertEqual(result['batch_line_exported_rows'],{'2025':1})


if __name__=='__main__':unittest.main()
