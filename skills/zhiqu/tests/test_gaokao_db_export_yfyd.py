"""Offline original-CDF exports share the lookup count gate and gap checks."""
import contextlib
import csv
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'skills/zhiqu-shared/scripts'))
sys.path.insert(0,str(ROOT/'skills/zhiqu/scripts'))
import zhiqu_db
from rank import Table,MissingDataError

class CdfExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.db=self.root/'fixture.sqlite'
        with sqlite3.connect(self.db)as c:
            c.executescript('''CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT,archive_sha256 TEXT,archive_status TEXT);
CREATE TABLE gk_official_yfyd(province TEXT,year INT,subject TEXT,score INT,cum INT,src TEXT,source_id TEXT,src_row TEXT,src_page INT,src_table TEXT,locator_method TEXT,locator_status TEXT,value_status TEXT);
CREATE TABLE gk_yfyd_context(province TEXT,year INT,subject TEXT,score INT,segment_n INT,score_operator TEXT,score_upper INT,scope_raw TEXT,count_raw INT,count_kind TEXT,cumulative_pct REAL,value_status TEXT,source_id TEXT);
CREATE TABLE gk_yfyd_bucket(score_label TEXT,score_boundary INT,boundary_operator TEXT,source_id TEXT,province TEXT,year INT,subject TEXT);
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
INSERT INTO source VALUES('official','官方','测试考试院','2025原一分一段表','https://example.gov.cn/page','https://example.gov.cn/table','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','已删除（有指纹，核对见记录）');''')
    def add(self,score,cum,count=None,*,subject='综合',kind='原表分别明示人数与累计人数',state='官方原值',op='=',row='4'):
        states={k:{'status':'官方原值'if v is not None else'来源未提供','reason':'原格'}for k,v in [('score',score),('cum',cum)]}
        cs={'segment_n':{'status':state if count is not None else'来源未提供','reason':'原人数口径'}}
        with sqlite3.connect(self.db)as c:
            c.execute('INSERT INTO gk_official_yfyd VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',('山东',2025,subject,score,cum,'sheet:'+row,'official',row,None,'原sheet','文字','原格',json.dumps(states)))
            c.execute('INSERT INTO gk_yfyd_context VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',('山东',2025,subject,score,count,op,None,'原表本段与累计人数',count,kind,None,json.dumps(cs),'official'))
    def export(self,subject='综合',name='out'):
        before=self.db.read_bytes();result=zhiqu_db.export_gaokao('山东',subject,[2025],out=self.root/name,key='major',db=self.db);self.assertEqual(before,self.db.read_bytes())
        with open(result['yfyd_files']['2025'])as f:allrows=list(csv.DictReader(f))
        with open(result['yfyd_usable_files']['2025'])as f:usable=list(csv.DictReader(f))
        return result,allrows,usable
    def missing_original_with_evidence(self,*,scope=True,asset=True,fields=True,wrong_type=False,approved=True):
        self.add(692,54,7)
        states={f:{'status':'原件缺失','reason':'原登记没有原件'}for f in ('score','cum')}
        context={f:{'status':'原件缺失','reason':'原登记没有原件'}for f in ('segment_n','count_raw')}
        self.fp='b'*64
        with sqlite3.connect(self.db)as c:
            c.execute("UPDATE source SET archive_sha256='',archive_status='未取到'")
            c.execute('UPDATE gk_official_yfyd SET value_status=?',(json.dumps(states),))
            c.execute('UPDATE gk_yfyd_context SET value_status=?',(json.dumps(context),))
            c.executescript('CREATE TABLE source_asset(source_id TEXT,sha256 TEXT,path TEXT,url TEXT,role TEXT,retrieved TEXT);CREATE TABLE gk_official_original_evidence(record_id TEXT,table_name TEXT,source_id TEXT,excerpt_locator_json TEXT);')
            if asset:c.execute('INSERT INTO source_asset VALUES(?,?,?,?,?,?)',('official',self.fp,'','https://example.gov.cn/new.pdf','attachment','2026-10-26'))
            payload={'business_key':{'province':'山东','year':2025,'subject':'综合','score':692},'scope':{'人群':'原表全体'},'locator':{'sha256':self.fp,'page':1,'table':1,'row':4},'review':{'status':'approved'if approved else'pending','approved_by':'root','scope_verified':scope,'manifest_sha256':'c'*64,'sample_proof_sha256':'d'*64}}
            if fields:payload['verified_fields']={k:{'value':float(v)if wrong_type else v,'sqlite_type':'real'if wrong_type else'integer'}for k,v in [('score',692),('cum',54),('segment_n',7),('count_raw',7)]}
            c.execute('INSERT INTO gk_official_original_evidence VALUES(?,?,?,?)',('new-evidence','gk_official_yfyd','official',json.dumps(payload)))

    def test_empty_cumulative_never_becomes_zero_or_segment_sum(self):
        self.add(692,54,7);self.add(691,60,6,row='5');self.add(690,None,None,row='6')
        result,rows,usable=self.export();self.assertEqual(result['candidate_status'],'missing_data');self.assertEqual(result['status'],'ok')
        self.assertEqual(result['yfyd_exported_rows'],{'2025':3});self.assertEqual(result['yfyd_usable_rows'],{'2025':2})
        self.assertEqual(rows[-1]['cum'],'');self.assertEqual(rows[-1]['count'],'');self.assertEqual(rows[-1]['count_raw'],'')
        self.assertNotIn('690',[r['score']for r in usable]);self.assertEqual(rows[-1]['grade'],'官方')
        p=json.loads(rows[-1]['data_provenance']);self.assertIsNone(p['cum']['value']);self.assertEqual(p['cum']['source_id'],'official');self.assertEqual(p['cum']['value_status']['status'],'来源未提供')
        table=Table(result['yfyd_usable_files']['2025']);self.assertEqual(table.rank_of(692),(48,54))
        with self.assertRaises(MissingDataError):table.score_of(47)
        with self.assertRaises(MissingDataError):table.rank_of(693)
    def test_real_rank_cli_and_row_source(self):
        self.add(692,54,7);self.add(691,60,6,row='5');result,rows,_=self.export()
        run=subprocess.run([sys.executable,str(ROOT/'skills/zhiqu/scripts/rank.py'),'score','692','--table',result['yfyd_usable_files']['2025']],text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertIn('位次 54（同分最好 48）',run.stdout)
        self.assertEqual(json.loads(rows[0]['data_provenance'])['cum']['source_id'],'official');self.assertEqual(rows[0]['src_row'],'4')
    def test_count_gate_and_unknown_head(self):
        self.add(692,54,54,kind='累计人数');self.add(691,60,6,row='5');result,rows,_=self.export()
        self.assertEqual(rows[0]['count'],'');self.assertEqual(rows[0]['count_raw'],'54');self.assertEqual(rows[0]['source_head_unknown'],'1')
        self.assertEqual(json.loads(rows[0]['data_provenance'])['count']['value_status']['status'],'来源未提供')
        table=Table(result['yfyd_usable_files']['2025'])
        with self.assertRaises(MissingDataError):table.rank_of(692)
        with self.assertRaises(MissingDataError):table.score_of(1)
        self.assertEqual(table.rank_of(691),(55,60))
        self.assertEqual(zhiqu_db._yfyd_rows.__name__,'_yfyd_rows')
    def test_derived_segment_is_not_exported_as_original(self):
        self.add(692,54,7,state='推算');result,rows,_=self.export();self.assertEqual(rows[0]['count'],'');self.assertEqual(rows[0]['source_head_unknown'],'1')
        with self.assertRaises(MissingDataError):Table(result['yfyd_usable_files']['2025']).score_of(1)
    def test_aggregate_original_label_and_operator_remain(self):
        self.add(683,126,126,kind='原表合并档人数（非单分）',op='>=');self.add(682,144,18,row='5')
        with sqlite3.connect(self.db)as c:c.execute('INSERT INTO gk_yfyd_bucket VALUES(?,?,?,?,?,?,?)',('683及以上',683,'>=','official','山东',2025,'综合'))
        result,rows,_=self.export();self.assertEqual(rows[0]['score_label'],'683及以上');self.assertEqual(rows[0]['source_operator'],'>=');self.assertEqual(rows[0]['count'],'')
        table=Table(result['yfyd_usable_files']['2025'])
        with self.assertRaises(MissingDataError):table.rank_of(683)
        with self.assertRaises(MissingDataError):table.score_of(126)
        self.assertEqual(table.rank_of(682),(127,144))
    def test_missing_middle_row_is_not_interpolated(self):
        self.add(692,54,7);self.add(690,70,10,row='6')
        coverage={'source_id':'official','table_name':'gk_official_yfyd','status':'partial','missing_rows':[{'page':1,'table':1,'row':5}],'missing_scope':'原行5排除'}
        with sqlite3.connect(self.db)as c:c.execute('INSERT INTO meta VALUES(?,?)',('gk_source_coverage:official:gk_official_yfyd:proof',json.dumps(coverage)))
        result,rows,_=self.export();self.assertEqual(json.loads(rows[0]['completeness'])['status'],'partial')
        table=Table(result['yfyd_usable_files']['2025'])
        with self.assertRaises(MissingDataError):table.rank_of(691)
        with self.assertRaises(MissingDataError):table.score_of(55)
        self.assertEqual(table.rank_of(690),(61,70))
    def test_subject_is_exact_and_no_original_score_is_fabricated(self):
        self.add(692,54,7);self.add(692,52,7,subject='选考物理子集');self.add(None,1,None,subject='选考物理子集',row='7')
        result,rows,usable=self.export('选考物理子集')
        self.assertTrue(all(r['subject']=='选考物理子集'for r in rows));self.assertEqual(result['yfyd_exported_rows']['2025'],2)
        self.assertEqual(len(usable),1);self.assertEqual(rows[-1]['score'],'');self.assertEqual(usable[0]['cum'],'52')
    def test_new_optional_head_flag_does_not_change_old_csv_behavior(self):
        old=self.root/'old.csv';old.write_text('score,cum\n692,54\n691,60\n');self.assertEqual(Table(old).rank_of(692),(1,54))
        new=self.root/'new.csv';new.write_text('score,cum,source_head_unknown\n692,54,1\n691,60,1\n')
        with self.assertRaises(MissingDataError):Table(new).rank_of(692)
        with self.assertRaises(MissingDataError):Table(new).score_of(1)
    def test_cli_says_no_candidates_but_cdf_is_present(self):
        self.add(692,54,7);out=io.StringIO()
        with contextlib.redirect_stdout(out):status=zhiqu_db.main(['export-gaokao','山东','综合','--years','2025','--out',str(self.root/'cli'),'--key','major','--db',str(self.db)])
        self.assertEqual(status,0);self.assertIn('志愿候选0行，一分一段1行',out.getvalue())
    def test_explicit_typed_field_evidence_updates_export_state_only(self):
        self.missing_original_with_evidence();result,rows,_=self.export();p=json.loads(rows[0]['data_provenance'])
        self.assertEqual(rows[0]['count'],'7');self.assertEqual(rows[0]['source_head_unknown'],'0')
        for field in ('score','cum','count','count_raw'):
            self.assertEqual(p[field]['value_status']['status'],'官方原值')
            self.assertEqual(p[field]['original_value_status']['status'],'原件缺失')
            self.assertEqual(p[field]['current_evidence']['record_id'],'new-evidence')
            self.assertEqual(p[field]['original_source_metadata']['archive_status'],'未取到')
            self.assertEqual(p[field]['source_assets'][0]['sha256'],self.fp)
        self.assertEqual(p['cum']['url'],'https://example.gov.cn/new.pdf');self.assertEqual(rows[0]['src_page'],'1')
        with sqlite3.connect(self.db)as c:
            self.assertEqual(c.execute('SELECT archive_status FROM source').fetchone()[0],'未取到')
            self.assertEqual(json.loads(c.execute('SELECT value_status FROM gk_official_yfyd').fetchone()[0])['cum']['status'],'原件缺失')
        self.assertEqual(Table(result['yfyd_usable_files']['2025']).rank_of(692),(48,54))

    def test_untyped_append_evidence_is_only_a_reference(self):
        self.missing_original_with_evidence(fields=False);_,rows,_=self.export();p=json.loads(rows[0]['data_provenance'])
        self.assertEqual(p['cum']['value_status']['status'],'原件缺失');self.assertNotIn('current_evidence',p['cum'])
        self.assertEqual(p['cum']['evidence_refs'][0]['record_id'],'new-evidence');self.assertEqual(rows[0]['count'],'')

    def test_same_numeric_value_with_wrong_type_does_not_upgrade(self):
        self.missing_original_with_evidence(wrong_type=True);_,rows,_=self.export();p=json.loads(rows[0]['data_provenance'])
        self.assertEqual(p['cum']['value_status']['status'],'原件缺失');self.assertNotIn('current_evidence',p['cum'])

    def test_no_verified_scope_or_matching_asset_does_not_upgrade(self):
        for kwargs in ({'scope':False},{'asset':False},{'approved':False}):
            with self.subTest(kwargs=kwargs):
                other=CdfExportTests();other.setUp()
                try:
                    other.missing_original_with_evidence(**kwargs);_,rows,_=other.export();p=json.loads(rows[0]['data_provenance'])
                    self.assertEqual(p['cum']['value_status']['status'],'原件缺失');self.assertNotIn('current_evidence',p['cum'])
                finally:other.doCleanups()

    def test_none_is_not_upgraded_even_if_explicitly_verified(self):
        self.missing_original_with_evidence()
        with sqlite3.connect(self.db)as c:
            c.execute('UPDATE gk_official_yfyd SET cum=NULL')
            payload=json.loads(c.execute('SELECT excerpt_locator_json FROM gk_official_original_evidence').fetchone()[0]);payload['verified_fields']['cum']={'value':None,'sqlite_type':'null'}
            c.execute('UPDATE gk_official_original_evidence SET excerpt_locator_json=?',(json.dumps(payload),))
        result,rows,usable=self.export();p=json.loads(rows[0]['data_provenance'])
        self.assertEqual(p['cum']['value_status']['status'],'原件缺失');self.assertNotIn('current_evidence',p['cum']);self.assertEqual(usable,[])

    def test_published_zero_is_not_an_empty_value(self):
        self.add(692,0,0);_,rows,usable=self.export();self.assertEqual(rows[0]['cum'],'0');self.assertEqual(rows[0]['count'],'0');self.assertEqual(len(usable),1)

if __name__=='__main__':unittest.main()
