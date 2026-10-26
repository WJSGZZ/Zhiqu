"""Official generic field proof/export: isolated SQLite fixtures, no local DB."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
if str(SCRIPTS)not in sys.path:sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('official_core_query_under_test',SCRIPTS/'zhiqu_db.py')
Z=importlib.util.module_from_spec(spec);spec.loader.exec_module(Z)


class OfficialCoreExportTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.execute("ATTACH DATABASE ':memory:' AS data")
        self.c.execute('CREATE TABLE data.source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT,archive_sha256 TEXT)')
        for sid,grade in [('official','官方'),('thirdparty','第三方整理')]:
            self.c.execute('INSERT INTO data.source VALUES(?,?,?,?,?,?,?)',(sid,grade,'示例大学','原专业投档成绩','https://example.edu.cn/original','','a'*64))
        self.c.execute('CREATE TABLE data.core_delta_source(source_id TEXT PRIMARY KEY,unfilled_reason TEXT)')
        self.c.executemany('INSERT INTO data.core_delta_source VALUES(?,?)',[('official',''),('thirdparty',''),('unregistered','')])
        numeric={'year','src_row'}
        self.c.execute('CREATE TABLE data.v_core_delta_number('+','.join('"'+k+'" '+('INTEGER'if k in numeric else'NUMERIC'if k in ('value','raw_value')else'TEXT')for k in Z.CORE_DELTA_COLUMNS)+')')
        self.c.execute('CREATE TABLE data.gk_official_original_evidence(record_id TEXT PRIMARY KEY,table_name TEXT,source_id TEXT,excerpt_locator_json TEXT)')
        self.tables=Z._tables(self.c);self.tmp=tempfile.TemporaryDirectory()

    def tearDown(self):self.c.close();self.tmp.cleanup()

    def add(self,rid='core-number-1',field='min_score',value=0,source='official',school='示例大学',batch='',plan_type='中外合作',proof=True):
        row={k:None for k in Z.CORE_DELTA_COLUMNS}
        row.update(record_id=rid,source_id=source,vendor_source_id=source,institution_id='1234567890',year=2026,province='示例省',subject='历史',batch=batch,school_raw=school,school_code='0010',group_code='',major_code='',major_name='示例专业',plan_type=plan_type,scope_raw='原批次与专业代号未给；专业投档成绩；非省全表',field_name=field,field_label={'min_score':'最低分','mean_score':'平均分','max_score':'最高分'}.get(field,field),value=value,raw_value=value,unit='分',value_status='第三方整理未核',src_sheet='HTML table[4]',src_row=4,src_col={'min_score':'td[4]','max_score':'td[5]','mean_score':'td[6]'}.get(field,'td[4]'),record_type='program_result',dataset_type='专业录取分')
        self.c.execute('INSERT INTO data.v_core_delta_number('+','.join(Z.CORE_DELTA_COLUMNS)+')VALUES('+','.join('?'for _ in Z.CORE_DELTA_COLUMNS)+')',[row[k]for k in Z.CORE_DELTA_COLUMNS])
        row=dict(self.c.execute('SELECT * FROM data.v_core_delta_number WHERE record_id=?',(rid,)).fetchone())
        p={'business_key':{'record_id':rid,'field_name':field,'scope':{k:row.get(k)for k in Z.OFFICIAL_CORE_SCOPE}},'review':{'status':'approved','approved_by':'root','semantic_approved':True,'dual_read_equal':True},'locator':{'sha256':'a'*64,'source_position':{k:row.get(k)for k in ('src_sheet','src_row','src_col')},'table':4,'row':4,'column':{'min_score':4,'max_score':5,'mean_score':6}.get(field,4)},'excerpt':{'value':row['value'],'raw':str(value),'header':row['field_label'],'score_basis':'专业投档成绩'}}
        if proof:self.c.execute('INSERT INTO data.gk_official_original_evidence VALUES(?,?,?,?)',(rid,'core_delta_number',source,json.dumps(p,ensure_ascii=False)))
        return row,p

    def save(self,row,proof,table='core_delta_number',source=None):
        self.c.execute('INSERT OR REPLACE INTO data.gk_official_original_evidence VALUES(?,?,?,?)',(row['record_id'],table,source or row['source_id'],json.dumps(proof,ensure_ascii=False)))

    def check(self,row):return Z._official_core_proof(self.c,row,Z._source(self.c,row['source_id']))

    def export(self,**kw):
        out=Path(self.tmp.name)/('run'+str(len(list(Path(self.tmp.name).iterdir()))));out.mkdir()
        return Z._export_official_core(self.c,self.tables,'示例省','历史',[2026],out,kw.get('schools',set()),kw.get('batch'),kw.get('plan_type'))

    def test_valid_zero_typed_original_cell_and_scope(self):
        row,p=self.add();self.assertEqual(type(row['value']),int);self.assertIsNotNone(self.check(row))
        r=Z._core_delta_record(self.c,'v_core_delta_number',row);v=r['values']['min_score']
        self.assertEqual(v['value'],0);self.assertEqual(v['grade'],'官方');self.assertEqual(v['value_status']['status'],'官方原值')
        self.assertEqual(r['excerpt'],p['excerpt']);self.assertEqual(r['locator'],p['locator'])
        self.assertIn('专业投档成绩',v['display_label']);self.assertNotIn('major_code',r['context']);self.assertNotIn('batch',r['context'])

    def test_missing_proof_is_pending_and_not_exported(self):
        row,_=self.add(proof=False);self.assertIsNone(self.check(row));record=Z._core_delta_record(self.c,'v_core_delta_number',row)
        self.assertEqual(record['quality_gate'],'未通过');self.assertEqual(record['values']['min_score']['value_status']['status'],'待核')
        out=self.export();self.assertEqual(out['official_field_exported_rows'],{'2026':0});self.assertEqual(len(out['official_field_rejected']),1)

    def test_wrong_value_and_numeric_type_rejected(self):
        row,p=self.add(value=12)
        for stated in [13,12.0,True,None,'12']:
            with self.subTest(stated=repr(stated)):
                bad=copy.deepcopy(p);bad['excerpt']['value']=stated;self.save(row,bad);self.assertIsNone(self.check(row))

    def test_bool_nan_infinite_negative_actual_values_rejected(self):
        row,p=self.add()
        for actual in [True,False,float('nan'),float('inf'),-1]:
            with self.subTest(actual=repr(actual)):
                changed=dict(row,value=actual);bad=copy.deepcopy(p);bad['excerpt']['value']=actual;self.save(changed,bad);self.assertIsNone(self.check(changed))

    def test_wrong_fingerprint_source_table_and_record_key_rejected(self):
        row,p=self.add()
        for kind in ['sha','source','table','record']:
            with self.subTest(kind=kind):
                bad=copy.deepcopy(p)
                if kind=='sha':bad['locator']['sha256']='b'*64
                if kind=='record':bad['business_key']['record_id']='other-record'
                self.save(row,bad,source='thirdparty'if kind=='source'else None,table='gk_official_cutoff'if kind=='table'else'core_delta_number')
                self.assertIsNone(self.check(row))
        source=Z._source(self.c,'official');source['archive_sha256']='not-a-fingerprint';self.save(row,p)
        self.assertIsNone(Z._official_core_proof(self.c,row,source))

    def test_every_scope_dimension_must_match_no_inferred_batch(self):
        row,p=self.add()
        for field in Z.OFFICIAL_CORE_SCOPE:
            with self.subTest(field=field):
                bad=copy.deepcopy(p);bad['business_key']['scope'][field]='本科'if field=='batch'else'wrong';self.save(row,bad);self.assertIsNone(self.check(row))
        self.save(row,p);self.assertIsNotNone(self.check(row))
        out=self.export(batch='本科');self.assertEqual(out['official_field_exported_rows']['2026'],0)

    def test_wrong_field_and_every_locator_component_rejected(self):
        row,p=self.add()
        alterations=[('field',None),('source_position','src_sheet'),('source_position','src_row'),('source_position','src_col'),('locator','table'),('locator','row'),('locator','column')]
        for kind,field in alterations:
            with self.subTest(kind=kind,field=field):
                bad=copy.deepcopy(p)
                if kind=='field':bad['business_key']['field_name']='max_score'
                elif kind=='source_position':bad['locator']['source_position'][field]='wrong'
                else:bad['locator'][field]=0
                self.save(row,bad);self.assertIsNone(self.check(row))
        bad=copy.deepcopy(p);bad['locator']['column']=True;self.save(row,bad);self.assertIsNone(self.check(row))

    def test_review_and_required_excerpt_flags_are_strict(self):
        row,p=self.add()
        for field,value in [('status','draft'),('approved_by','another'),('semantic_approved',False),('semantic_approved',1),('dual_read_equal',False),('dual_read_equal',1)]:
            with self.subTest(field=field,value=value):
                bad=copy.deepcopy(p);bad['review'][field]=value;self.save(row,bad);self.assertIsNone(self.check(row))
        for field in ['raw','header','score_basis']:
            bad=copy.deepcopy(p);bad['excerpt'][field]='';self.save(row,bad);self.assertIsNone(self.check(row))

    def test_bad_json_or_shapes_fail_closed(self):
        row,p=self.add()
        for raw in ['{bad','[]','null','42',json.dumps(dict(p,review=[])),json.dumps(dict(p,locator='bad'))]:
            with self.subTest(raw=raw):
                self.c.execute('UPDATE data.gk_official_original_evidence SET excerpt_locator_json=?',(raw,));self.assertIsNone(self.check(row))

    def test_thirdparty_never_upgraded_and_unregistered_not_exported(self):
        row,_=self.add(source='thirdparty');self.assertIsNone(self.check(row));record=Z._core_delta_record(self.c,'v_core_delta_number',row)
        self.assertEqual(record['values']['min_score']['grade'],'第三方整理');self.assertEqual(record['values']['min_score']['value_status']['status'],'第三方整理未核');self.assertIsNone(record['excerpt'])
        self.add(rid='missing-source',source='unregistered');out=self.export();self.assertEqual(out['official_field_exported_rows']['2026'],0)

    def test_three_fields_roundtrip_sources_scope_and_filters_no_mutation(self):
        for rid,field,value in [('core-number-1','min_score',0),('core-number-2','max_score',520),('core-number-3','mean_score',509.5)]:self.add(rid,field,value)
        before=self.c.total_changes;out=self.export(schools={'示例大学'},plan_type='中外合作')
        self.assertEqual(self.c.total_changes,before);self.assertEqual(out['official_field_exported_rows'],{'2026':3});self.assertEqual(out['official_field_rejected'],[])
        with Path(out['official_field_files']['2026']).open()as f:rows=list(csv.DictReader(f))
        self.assertEqual({r['field']for r in rows},{'min_score','max_score','mean_score'});self.assertEqual({r['source_id']for r in rows},{'official'});self.assertEqual({r['source_grade']for r in rows},{'官方'});self.assertEqual({r['batch']for r in rows},{''})
        self.assertEqual({r['scope_raw']for r in rows},{'原批次与专业代号未给；专业投档成绩；非省全表'})
        for row in rows:
            self.assertEqual(json.loads(row['value_status'])['status'],'官方原值');self.assertEqual(json.loads(row['locator'])['source_position']['src_row'],4);self.assertEqual(json.loads(row['excerpt'])['score_basis'],'专业投档成绩');self.assertEqual(row['landing_url'],'https://example.edu.cn/original')
        self.assertEqual(next(r['value']for r in rows if r['field']=='min_score'),'0')
        self.assertEqual(self.export(schools={'别校'})['official_field_exported_rows']['2026'],0)
        self.assertEqual(self.export(schools={'0010'})['official_field_exported_rows']['2026'],3)
        self.assertEqual(self.export(plan_type='普通')['official_field_exported_rows']['2026'],0)

    def test_export_missing_chain_rejects_only_that_field(self):
        self.add('min','min_score',10);self.add('max','max_score',20,proof=False);self.add('avg','mean_score',15)
        out=self.export();self.assertEqual(out['official_field_exported_rows']['2026'],2);self.assertEqual(out['official_field_rejected'],[{'record_id':'max','reason':'官方字段原格核验链未闭合'}])

    def test_main_preflight_refuses_existing_official_csv_before_db_open(self):
        path=Path(self.tmp.name)/'示例省-历史-2026-official-fields.csv';path.write_text('original')
        with mock.patch.object(Z,'_open',side_effect=AssertionError('must not open database')):
            with self.assertRaises(Z.QueryError):Z.export_gaokao('示例省','历史',[2026],out=Path(self.tmp.name))
        self.assertEqual(path.read_text(),'original')


if __name__=='__main__':unittest.main()
