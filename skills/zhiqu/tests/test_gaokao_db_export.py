"""Offline scope/provenance contracts for the DB -> pool export."""
import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'skills/zhiqu-shared/scripts'))
import gaokao_export as ex
import zhiqu_db

def record(*,grade='第三方整理',sid='vendor',rank=1000,score=600,plan=10,batch='本科批',plan_type='普通',major='计算机科学与技术',group='',scope_raw=''):
    r={'province':'河南','year':2025,'subject':'物理','code':'1001','name':'甲大学','institution_id':'1000000001','group':group,'major_code':'080901','major':major,'batch':batch,'plan_type':plan_type,'requirement':'物理+化学','scope_raw':scope_raw,'grain':'major','record_id':sid,'table':'fixture','completeness':{'status':'partial','missing_rows':[{'page':1,'table':1,'row':8}]}}
    r['values']={'rank':rank,'score':score,'plan':plan}
    r['provenance']={f:ex._meta(r,f,v,{'source_id':sid,'grade':grade,'publisher':'测试发布单位','title':'测试原表','landing_url':'https://example.edu.cn/table'}, {'status':'官方原值'if grade=='官方'else'第三方整理未核'}, {'src_row':'9'})for f,v in r['values'].items()}
    return r

class GaokaoDbExportTests(unittest.TestCase):
    def run_export(self,rows,**kw):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        result=ex.export_records(rows,'河南','物理',[2025],out=self.tmp.name,key='major',**kw)
        with open(result['files']['2025'],newline='')as f:csvrows=list(csv.DictReader(f))
        return result,csvrows

    def test_official_value_wins_same_scope_and_conflict_is_recorded(self):
        result,rows=self.run_export([record(),record(grade='官方',sid='official',rank=900)])
        self.assertEqual(rows[0]['rank'],'900')
        self.assertEqual(json.loads(rows[0]['data_provenance'])['rank']['grade'],'官方')
        self.assertGreater(result['conflict_count'],0)
        self.assertFalse(result['rank_conversion_performed'])

    def test_per_value_fallback_does_not_upgrade_third_party_rank(self):
        _,rows=self.run_export([record(),record(grade='官方',sid='official',rank=None,score=601,plan=None)])
        p=json.loads(rows[0]['data_provenance'])
        self.assertEqual(p['score']['grade'],'官方');self.assertEqual(p['rank']['grade'],'第三方整理')
        self.assertEqual(p['rank']['value'],1000)
        self.assertEqual(rows[0]['source_grade'],'第三方整理·内部未核')
        self.assertEqual(p['rank']['completeness']['status'],'partial')

    def test_conflicting_third_party_rank_is_not_picked(self):
        result,rows=self.run_export([record(),record(sid='vendor2',rank=1001)])
        self.assertEqual(rows,[]);self.assertGreater(result['conflict_count'],0)

    def test_batch_or_plan_scope_cannot_collapse_into_one_pool_key(self):
        result,rows=self.run_export([record(),record(sid='other',batch='提前批')])
        self.assertEqual(rows,[])
        with open(result['conflicts_file'])as f:self.assertTrue(any(x['field']=='scope'for x in csv.DictReader(f)))
        _,rows=self.run_export([record(),record(sid='other',batch='提前批')],batch='本科批')
        self.assertEqual(len(rows),1)

    def test_missing_rank_or_batch_is_a_gap_not_a_conversion(self):
        result,rows=self.run_export([record(rank=None),record(sid='other',batch='')])
        self.assertEqual(rows,[]);self.assertEqual(len(result['rejected']),2)

    def test_rank_yfyd_check_does_not_become_official_cutoff_check(self):
        r=record();m=ex._meta(r,'rank',1000,{'grade':'第三方整理','source_id':'v'},{'status':'第三方整理未核'},{},[{'kind':'rank_vs_yfyd_m','same_scope':True,'same_value':True}])
        self.assertEqual(m['display_grade'],'第三方整理·内部未核')
        self.assertEqual(m['cross_check_summary']['checked'],0)
        self.assertIn('不是官方投档',m['cross_check_summary']['note'])
        m=ex._meta(r,'rank',1000,{'grade':'第三方整理','source_id':'v'},{},{},[{'kind':'official_cutoff','same_scope':True,'same_value':True}])
        self.assertEqual(m['display_grade'],'第三方整理·内部未核')
        proof={'verdict':'一致','field':'rank','scope':ex._scope(r),'thirdparty_scope':ex._scope(r),'official_value':1000,'thirdparty_value':1000,'official_source':{'grade':'官方','source_id':'o','landing_url':'https://example.edu.cn'},'official_value_status':{'status':'官方原值'},'official_locator':{'row':7},'comparison_basis':'同事实同口径逐值'}
        m=ex._meta(r,'rank',1000,{'grade':'第三方整理','source_id':'v'},{},{},cross_check=proof)
        self.assertEqual(m['display_grade'],'官方一致')
        self.assertEqual(m['grade'],'第三方整理');self.assertEqual(m['cross_check'],proof)

    def test_derived_official_rank_cannot_certify_matching_vendor(self):
        official=record(grade='官方',sid='official')
        official['provenance']['rank']['value_status']={'status':'推算','method':'投档分对应同年一分一段累计'}
        _,rows=self.run_export([record(),official])
        facts=json.loads(rows[0]['data_provenance'])
        self.assertEqual(rows[0]['rank'],'1000')  # 不借本次凭据修补改变原业务数值。
        self.assertEqual(facts['rank']['value_status']['status'],'推算')
        self.assertEqual(facts['rank']['cross_checks'],[])
        self.assertEqual(facts['score']['cross_checks'][0]['official_value_status'],{'status':'官方原值'})
        self.assertEqual(facts['plan']['cross_checks'][0]['official_value_status'],{'status':'官方原值'})
        proof=facts['score']['cross_checks'][0]
        self.assertTrue(ex.valid_cross_check(proof,official,'score',600))
        self.assertNotIn('cross_check',facts['rank'])

    def test_source_grade_fallback_is_not_explicit_official_value_evidence(self):
        for state in [None,{},'官方原值',{'status':'未知'},{'status':'未注明'}]:
            with self.subTest(state=state):
                official=record(grade='官方',sid='official')
                official['provenance']['rank']=ex._meta(official,'rank',1000,
                    {'grade':'官方','source_id':'official','landing_url':'https://example.edu.cn'},state,{'row':7})
                self.assertEqual(official['provenance']['rank']['value_status']['status'],'官方原值')
                self.assertFalse(official['provenance']['rank']['value_status_explicit'])
                _,rows=self.run_export([record(),official])
                self.assertEqual(json.loads(rows[0]['data_provenance'])['rank']['cross_checks'],[])

    def test_official_consistency_requires_per_value_original_status(self):
        r=record();official=record(grade='官方',sid='official')
        _,rows=self.run_export([r,official])
        proof=json.loads(rows[0]['data_provenance'])['rank']['cross_checks'][0]
        for state in [None,{},'官方原值','{"status":"官方原值"}',[],{'status':'推算'},{'status':'原件缺失'},
                      {'status':'待核'},{'status':'第三方已核一致'}]:
            with self.subTest(state=state):
                changed=dict(proof,official_value_status=state)
                self.assertFalse(ex.valid_cross_check(changed,r,'rank',1000))
                meta=ex._meta(r,'rank',1000,{'grade':'第三方整理','source_id':'vendor'},
                              {'status':'第三方整理未核'},{'row':9},cross_check=changed)
                self.assertEqual(meta['display_grade'],'第三方整理·内部未核')
                self.assertEqual(meta['cross_check_summary']['checked'],0)
        for status in ['官方原值','人工更正']:
            with self.subTest(status=status):
                changed=dict(proof,official_value_status={'status':status})
                self.assertTrue(ex.valid_cross_check(changed,r,'rank',1000))
        missing=dict(proof);missing.pop('official_value_status')
        self.assertFalse(ex.valid_cross_check(missing,r,'rank',1000))

    def test_aggregate_metadata_is_retained_without_conversion(self):
        bucket={'year':2025,'aggregate_bucket':{'score_label':'683及以上','boundary_operator':'>='}}
        result,rows=self.run_export([record()],yfyd_metadata=[bucket])
        self.assertEqual(result['yfyd'],[bucket]);self.assertEqual(rows[0]['rank'],'1000')

    def test_source_status_fallback_and_identical_alias_fact_dedup(self):
        r=record();r2=record(sid='second');r2['name']='甲大'
        for field in ex.FIELDS:
            r2['provenance'][field]['scope']=ex._scope(r2)
        _,rows=self.run_export([r,r2])
        self.assertEqual(len(rows),1)
        self.assertEqual(set(json.loads(rows[0]['data_provenance'])['rank']['additional_source_ids']),{'vendor','second'})
        m=ex._meta(r,'rank',1000,{'grade':'官方'},None,{})
        self.assertEqual(m['display_grade'],'官方');self.assertEqual(m['value_status']['status'],'官方原值')
        m=ex._meta(r,'rank',1000,{'grade':'第三方整理'},None,{})
        self.assertEqual(m['value_status']['status'],'第三方整理未核');self.assertTrue(m['value_status']['reason'])

    def test_presentation_only_scope_normalization_keeps_real_differences(self):
        self.assertEqual(ex.group_code('(101)'),'101')
        self.assertEqual(ex.group_code('（01）'),'01')
        self.assertEqual(ex.requirement('首选物理，再选化学','物理'),'化学')
        self.assertEqual(ex.requirement('首选历史，再选化学','物理'),'首选历史,再选化学')
        self.assertEqual(ex.scope_text('[]'),'')
        self.assertEqual(ex.requirement('化学和生物','物理'),ex.requirement('化学、生物(2科必选)','物理'))
        self.assertNotEqual(ex.requirement('化学或生物','物理'),ex.requirement('化学和生物','物理'))
        self.assertEqual(ex.scope_text('[["专业备注","(色弱不予录取；校区：甲)"]]'),ex.scope_text('[["专业备注","(色弱不予录取;校区:甲)"]]'))
        self.assertNotEqual(ex.scope_text('[["专业备注","(色弱不予录取)"]]'),ex.scope_text('[]'))

    def test_historical_yfyd_check_survives_same_fact_source_dedup(self):
        r=record(sid='a');older=record(sid='z')
        older['provenance']['rank']['checks']=[{'kind':'rank_vs_yfyd_m','verdict':'一致'}]
        _,rows=self.run_export([r,older]);m=json.loads(rows[0]['data_provenance'])['rank']
        self.assertEqual(m['display_grade'],'第三方整理·内部未核')
        self.assertEqual(m['cross_check_summary']['checked'],0)
        self.assertIn('不是官方投档',m['cross_check_summary']['note'])
        self.assertEqual(m['cross_check_summary']['other_checks'][0]['checked_source_id'],'z')

    def test_missing_registered_source_is_rejected_not_guessed(self):
        r=record();r['provenance']['rank']['source_registered']=False;r['provenance']['rank']['grade']='未登记'
        result,rows=self.run_export([r]);self.assertEqual(rows,[])
        self.assertIn('缺真实来源登记',result['rejected'][0]['reason'])

    def test_existing_output_is_not_overwritten(self):
        result,_=self.run_export([record()])
        with self.assertRaises(ValueError):ex.export_records([record()],'河南','物理',[2025],out=self.tmp.name,key='major')

    def test_historical_yfyd_correction_cannot_borrow_official_cutoff_grade(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'legacy.sqlite'
            with sqlite3.connect(db) as c:
                c.executescript('''CREATE TABLE source(source_id TEXT,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT);
                INSERT INTO source VALUES('vendor-file-1','第三方整理','购买汇编','原表','','');
                INSERT INTO source VALUES('o','官方','考试院','一分一段','https://example.gov.cn','');
                CREATE TABLE gk_v_usable(entry_id INT,province TEXT,year INT,subject_type TEXT,school_code TEXT,school_name TEXT,major_name TEXT,major_code TEXT,group_code TEXT,batch TEXT,min_rank INT,min_score INT,institution_id TEXT,value_status TEXT);
                INSERT INTO gk_v_usable VALUES(1,'河南',2025,'物理','1001','甲大学','计算机','080901','','本科批',1000,600,'1000000001','{}');
                CREATE TABLE gk_v_plan(entry_id INT,plan_n INT,plan_year INT,ingest_id INT,subject_req_raw TEXT,major_note TEXT,other_req TEXT,foreign_lang_req TEXT,src_file INT,src_row TEXT);
                INSERT INTO gk_v_plan VALUES(1,10,2025,1,'物理','','','',1,'9');
                CREATE TABLE gk_check_sample(entry_id INT,year INT,field TEXT,table_name TEXT,official_source_id TEXT,official_value TEXT,verdict TEXT);
                INSERT INTO gk_check_sample VALUES(1,2025,'rank_vs_yfyd_m','result','o','1000','不一致');''')
            with zhiqu_db._open('education', db) as (c, _):
                rows=ex.collect(c,zhiqu_db._tables(c),'河南','物理',[2025])
            self.assertEqual(len(rows),1)
            fact=rows[0]['provenance']['rank']
            self.assertEqual(fact['source_id'],'vendor-file-1')
            self.assertEqual(fact['display_grade'],'第三方整理·内部未核')
            self.assertEqual(fact['checks'][0]['kind'],'rank_vs_yfyd_m')

    def test_actual_sqlite_fixture_and_cli_entrypoint_are_read_only(self):
        with tempfile.TemporaryDirectory()as d:
            db=Path(d)/'fixture.sqlite'
            c=sqlite3.connect(db)
            c.executescript("CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT);CREATE TABLE gk_official_cutoff(province TEXT,year INT,subject TEXT,code TEXT,name TEXT,grp TEXT,major_code TEXT,major TEXT,plan INT,score INT,rank INT,source_id TEXT,institution_id TEXT,plan_type TEXT,src TEXT,src_row TEXT,value_status TEXT);CREATE TABLE official_cutoff_scope(source_id TEXT,public_record TEXT,scope_json TEXT);INSERT INTO source VALUES('o','官方','测试学校','原表','https://example.edu.cn','');")
            c.execute("INSERT INTO gk_official_cutoff VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('河南',2025,'物理','1001','甲大学','','080901','计算机科学与技术',10,600,1000,'o','1000000001','普通','original:4','4',json.dumps({'rank':{'status':'官方原值'}})))
            c.execute("INSERT INTO official_cutoff_scope VALUES(?,?,?)",('o','original:4',json.dumps({'batch':'本科批'})))
            c.execute("INSERT INTO gk_official_cutoff VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('河南',2025,'物理','','','','','',10,601,900,'o','1000000002','普通','original:5','5','{}'))
            c.execute("INSERT INTO official_cutoff_scope VALUES(?,?,?)",('o','original:5',json.dumps({'batch':'本科批','code':'1002','name':'乙大学','major_code':'080901','major':'计算机科学与技术','requirement':'化学'})))
            c.execute("INSERT INTO gk_official_cutoff VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('河南',2025,'物理','1003','丙大学','','080901','计算机科学与技术',10,600,1000,'o','1000000003','普通','original:6','6','{}'))
            c.execute("INSERT INTO official_cutoff_scope VALUES(?,?,?)",('o','original:6',json.dumps({'batch':'本科批','code':'9999'})))
            c.commit();c.close();before=db.read_bytes()
            result=zhiqu_db.export_gaokao('河南','物理',[2025],out=Path(d)/'export',key='major',db=db)
            self.assertEqual(result['exported_rows'],{'2025':2});self.assertEqual(db.read_bytes(),before)
            self.assertTrue(any('明确scope' in r['reason']for r in result['rejected']))
            with open(result['files']['2025'])as f:exported=list(csv.DictReader(f))
            filled=next(r for r in exported if r['code']=='1002');self.assertEqual(filled['major_code'],'080901')
            self.assertEqual(json.loads(filled['data_provenance'])['rank']['original_scope']['source_scope_original']['name'],'乙大学')
            import contextlib,io
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                status=zhiqu_db.main(['export-gaokao','河南','物理','--years','2025','--out',str(Path(d)/'cli'),'--key','major','--db',str(db),'--json'])
            self.assertEqual(status,0);self.assertEqual(json.loads(output.getvalue())['exported_rows'],{'2025':2})
            self.assertEqual(db.read_bytes(),before)


class OriginalHeaderScopeTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("ATTACH DATABASE ':memory:' AS data;CREATE TABLE data.source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT);INSERT INTO data.source VALUES('o','官方','考试院','原表','https://example.edu.cn/original');CREATE TABLE data.gk_official_cutoff(province TEXT,year INT,subject TEXT,code TEXT,name TEXT,grp TEXT,major_code TEXT,major TEXT,score INT,rank INT,source_id TEXT,src TEXT,value_status TEXT);INSERT INTO data.gk_official_cutoff VALUES('河北',2025,'物理','001','甲大学','','','计算机科学与技术',600,1000,'o','public.csv:2','{}');CREATE TABLE data.source_format_reference(source_id TEXT PRIMARY KEY,provided_fields TEXT,scope_fields TEXT,excerpt TEXT,locator TEXT,scope_values TEXT);CREATE TABLE data.official_cutoff_scope(source_id TEXT,public_record TEXT,scope_json TEXT,locator_json TEXT);")
        self.c.execute('INSERT INTO data.source_format_reference VALUES(?,?,?,?,?,?)',('o','["score"]','{}','2025年河北省普通高校招生本科批；物理科目组合',json.dumps({'sha256':'a'*64,'sheet':'原表','row':1}),json.dumps({'source_batch_raw':'本科批','year':2025,'subject':'物理'})))
        self.c.execute('INSERT INTO data.official_cutoff_scope VALUES(?,?,?,?)',('o','public.csv:2',json.dumps({'major_code':'16'}),json.dumps({'sha256':'a'*64,'sheet':'原表','row':5,'columns':['A','C','D','E']})))
    def collect(self):return ex.collect(self.c,zhiqu_db._tables(self.c),'河北','物理',[2025])
    def export(self):
        with tempfile.TemporaryDirectory()as d:
            m=ex.export_records(self.collect(),'河北','物理',[2025],out=d,key='major')
            with open(m['files']['2025'])as f:rows=list(csv.DictReader(f))
            return m,rows
    def test_derived_rank_from_score_only_original_is_not_model_input(self):
        state={'score':{'status':'官方原值'},'rank':{'status':'推算','method':'投档分→同年同科一分一段累计'}}
        self.c.execute('UPDATE data.gk_official_cutoff SET value_status=?',(json.dumps(state),))
        before=dict(self.c.execute('SELECT * FROM data.gk_official_cutoff').fetchone())
        normalized=self.collect()[0]
        self.assertEqual(normalized['values'],{'rank':1000,'score':600,'plan':None})
        self.assertFalse(normalized['provenance']['rank']['usage_gate']['model_usable'])
        m,rows=self.export();self.assertEqual(rows,[])
        withheld=m['withheld_values'][0]
        self.assertEqual(withheld['value'],1000)
        retained=withheld['retained_values']['score']
        self.assertEqual(retained['value'],600);self.assertEqual(retained['grade'],'官方')
        self.assertEqual(retained['source_id'],'o');self.assertEqual(retained['locator']['scope_locator']['row'],5)
        self.assertEqual(withheld['locator']['scope_locator']['row'],5)
        self.assertIn('非实际最低投档位次',withheld['usage_gate']['meaning'])
        self.assertEqual(dict(self.c.execute('SELECT * FROM data.gk_official_cutoff').fetchone()),before)

    def test_string_derived_status_is_preserved_and_blocked_like_query(self):
        self.c.execute('UPDATE data.gk_official_cutoff SET value_status=?',
            (json.dumps({'rank':'推算','score':{'status':'官方原值'}}),))
        row=self.collect()[0]
        self.assertEqual(row['provenance']['rank']['value_status']['status'],'推算')
        self.assertFalse(row['provenance']['rank']['value_status_explicit'])
        self.assertFalse(row['provenance']['rank']['usage_gate']['model_usable'])
        m,rows=self.export();self.assertEqual(rows,[]);self.assertEqual(m['withheld_values'][0]['value'],1000)

    def test_unknown_format_or_publisher_rank_not_reclassified(self):
        self.c.execute('UPDATE data.gk_official_cutoff SET value_status=?',
            (json.dumps({'rank':{'status':'推算','method':'待补方法'}}),))
        self.c.execute('UPDATE data.source_format_reference SET provided_fields=?',('["score","rank"]',))
        m,rows=self.export();self.assertEqual(len(rows),1);self.assertEqual(m['withheld_values'],[])
        self.c.execute('DELETE FROM data.source_format_reference')
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'batch':'本科批','major_code':'16'}),))
        m,rows=self.export();self.assertEqual(len(rows),1);self.assertEqual(m['withheld_values'],[])

    def test_same_scope_vendor_rank_fills_gap_without_borrowing_official_grade(self):
        self.c.execute('UPDATE data.gk_official_cutoff SET value_status=?',
            (json.dumps({'rank':{'status':'推算','method':'投档分→同年同科一分一段累计'},'score':{'status':'官方原值'}}),))
        official=self.collect()[0]
        vendor=dict(official,record_id='vendor-test',table='fixture',source_id='vendor')
        vendor['values']=dict(rank=999,score=599,plan=None)
        vendor['provenance']={field:ex._meta(vendor,field,value,
            {'grade':'第三方整理','source_id':'vendor','publisher':'测试整理方'},
            {'status':'第三方整理未核'},{'src_row':'vendor.xlsx:7'})for field,value in vendor['values'].items()}
        with tempfile.TemporaryDirectory()as d:
            result=ex.export_records([official,vendor],'河北','物理',[2025],out=d,key='major')
            with open(result['files']['2025']) as exported:rows=list(csv.DictReader(exported))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['rank'],'999');self.assertEqual(rows[0]['score'],'600')
        self.assertEqual(rows[0]['source_grade'],'第三方整理·内部未核')
        facts=json.loads(rows[0]['data_provenance'])
        self.assertEqual(facts['rank']['source_id'],'vendor');self.assertEqual(facts['score']['source_id'],'o')
        self.assertEqual(facts['rank']['cross_check_summary']['checked'],0)
        self.assertEqual(len(result['withheld_values']),1)

    def test_exact_legacy_header_requires_matching_official_fingerprint(self):
        self.c.execute('ALTER TABLE data.source ADD COLUMN archive_sha256 TEXT')
        self.c.execute('UPDATE data.source SET archive_sha256=?', ('a'*64,))
        for prefix in ('原表表头；指纹=', '原表头；SHA=', '原件真实表头；SHA='):
            self.c.execute('UPDATE data.source_format_reference SET locator=?', (prefix+'a'*64,))
            _, rows = self.export()
            self.assertEqual(len(rows), 1)
            loc = json.loads(json.loads(rows[0]['data_provenance'])['score']['locator']['original_format']['locator'])
            self.assertEqual(loc['sha256'], 'a'*64)
            self.assertEqual(loc['legacy_locator_raw'], prefix+'a'*64)
        self.c.execute('UPDATE data.source SET archive_sha256=?', ('b'*64,))
        self.assertEqual(self.export()[1], [])
        self.c.execute("UPDATE data.source SET archive_sha256=?,grade='第三方整理'", ('a'*64,))
        self.assertEqual(self.export()[1], [])

    def test_analogous_header_and_unbound_legacy_locator_are_not_original_proof(self):
        self.c.execute('ALTER TABLE data.source ADD COLUMN archive_sha256 TEXT')
        self.c.execute('UPDATE data.source SET archive_sha256=?', ('a'*64,))
        for locator in ('原表表头或同站同类表列结构；指纹='+'a'*64,
                        '原表头；SHA='+'a'*64+'extra',
                        '原表头；SHA='+'a'*63,
                        '原表头；SHA='+('A'*64),
                        'original header '+('a'*64)):
            self.c.execute('UPDATE data.source_format_reference SET locator=?', (locator,))
            self.assertEqual(self.export()[1], [], locator)
        self.c.execute('UPDATE data.source SET archive_sha256=NULL')
        self.c.execute('UPDATE data.source_format_reference SET locator=?', ('原表头；SHA='+'a'*64,))
        self.assertEqual(self.export()[1], [])

    def test_source_header_scope_and_real_row_locator_survive_export(self):
        m,rows=self.export();self.assertEqual(m['exported_rows'],{'2025':1});self.assertEqual(rows[0]['batch'],'本科批');self.assertEqual(rows[0]['major_code'],'16')
        fact=json.loads(rows[0]['data_provenance'])['score'];self.assertEqual(fact['value'],600);self.assertEqual(fact['grade'],'官方');self.assertEqual(fact['locator']['scope_locator']['row'],5);self.assertIn('source_format_reference',fact['original_scope'])
    def test_row_scope_cannot_silently_override_source_scope(self):
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'batch':'提前批','major_code':'16'}),));m,rows=self.export();self.assertEqual(rows,[]);self.assertIn('scope',m['rejected'][0]['reason'])
    def test_unproved_or_malformed_header_does_not_fill_batch(self):
        for column,value in [('excerpt',''),('locator',''),('locator','not-json'),('locator','[]'),('scope_fields','[]'),('provided_fields','{}'),('scope_values','not-json')]:
            original=self.c.execute('SELECT '+column+' FROM data.source_format_reference').fetchone()[0]
            self.c.execute('UPDATE data.source_format_reference SET '+column+'=?',(value,));m,rows=self.export();self.assertEqual(rows,[],column);self.c.execute('UPDATE data.source_format_reference SET '+column+'=?',(original,))
    def test_source_wide_year_or_subject_mismatch_is_a_gap(self):
        for field,value in [('year',2024),('subject','历史')]:
            fixed={'source_batch_raw':'本科批','year':2025,'subject':'物理'};fixed[field]=value;self.c.execute('UPDATE data.source_format_reference SET scope_values=?',(json.dumps(fixed),));m,rows=self.export();self.assertEqual(rows,[]);self.assertTrue(m['rejected'])
    def test_two_distinct_batch_labels_are_not_merged(self):
        self.c.execute('UPDATE data.source_format_reference SET scope_values=?',(json.dumps({'batch':'提前批','source_batch_raw':'本科批'}),));self.assertEqual(self.export()[1],[])
    def test_unaligned_original_major_code_cannot_be_merged_as_blank(self):
        self.c.execute('UPDATE data.source_format_reference SET scope_values=?',(json.dumps({'source_batch_raw':'本科批','required_scope_fields':['major_code']}),))
        self.c.execute('DELETE FROM data.official_cutoff_scope');m,rows=self.export();self.assertEqual(rows,[]);self.assertIn('scope',m['rejected'][0]['reason'])

    def test_row_year_subject_and_province_must_match_selected_competition(self):
        for field,value in [('year',2024),('subject','历史'),('province','河南')]:
            scope={'major_code':'16',field:value};self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps(scope),));self.assertEqual(self.export()[1],[],field)

    def test_source_wide_major_code_cannot_replace_row_alignment(self):
        self.c.execute('UPDATE data.source_format_reference SET scope_values=?',(json.dumps({'source_batch_raw':'本科批','major_code':'16','required_scope_fields':['major_code']}),))
        self.c.execute('DELETE FROM data.official_cutoff_scope');self.assertEqual(self.export()[1],[])

    def test_blank_row_major_codes_do_not_satisfy_alignment(self):
        self.c.execute('UPDATE data.source_format_reference SET scope_values=?',(json.dumps({'source_batch_raw':'本科批','required_scope_fields':['major_code']}),))
        for value in ['   ','\u3000']:
            self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'major_code':value}),));self.assertEqual(self.export()[1],[])

    def test_ingest_alignment_contract_is_not_a_reader_scope(self):
        self.c.execute('UPDATE data.source_format_reference SET scope_values=?',(json.dumps({'source_batch_raw':'本科批','required_scope_fields':['major_code']}),))
        row=dict(self.c.execute('SELECT * FROM data.gk_official_cutoff').fetchone());context=zhiqu_db._official_context(self.c,row)
        self.assertEqual(context['source_batch_raw'],'本科批');self.assertNotIn('required_scope_fields',context)

    def test_missing_header_does_not_guess_from_source_id_or_title(self):
        self.c.execute('DELETE FROM data.source_format_reference');self.assertEqual(self.export()[1],[])

    def test_explicit_row_original_batch_is_not_lost_without_source_header(self):
        self.c.execute('DELETE FROM data.source_format_reference')
        scope={'major_code':'16','source_batch_raw':'本科批','source_admission_type_raw':'一般统考生'}
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps(scope),))
        _,rows=self.export();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['batch'],'本科批')
        fact=json.loads(rows[0]['data_provenance'])['score']
        self.assertEqual(fact['value'],600);self.assertEqual(fact['display_grade'],'官方')
        self.assertEqual(fact['original_scope']['source_scope_original'],scope)
        self.assertIn('一般统考生',fact['scope']['scope_raw'])

    def test_original_row_batch_alias_participates_in_all_scope_conflicts(self):
        # 明确批次、中文批次、原批次别名和整表常量均不能相互覆盖。
        for scope in ({'major_code':'16','source_batch_raw':'提前批'},
                      {'major_code':'16','batch':'提前批','source_batch_raw':'本科批'},
                      {'major_code':'16','批次':'提前批','source_batch_raw':'本科批'}):
            self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps(scope),))
            meta,rows=self.export();self.assertEqual(rows,[]);self.assertTrue(meta['rejected'])

    def test_title_or_blank_original_batch_is_not_used_as_row_evidence(self):
        self.c.execute('DELETE FROM data.source_format_reference')
        for batch in ('',' ','\u3000'):
            scope={'major_code':'16','source_batch_raw':batch,'source_title':'2025年普通类本科批投档情况','scope_raw':'本科批'}
            self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps(scope),))
            self.assertEqual(self.export()[1],[])

    def test_original_batch_alias_satisfies_only_its_own_row_alignment(self):
        self.c.execute('UPDATE data.source_format_reference SET scope_values=?',(json.dumps({'source_batch_raw':'本科批','required_scope_fields':['batch']}),))
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'major_code':'16','source_batch_raw':'本科批'}),))
        self.assertEqual(len(self.export()[1]),1)
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'major_code':'16','source_batch_raw':' '}),))
        self.assertEqual(self.export()[1],[])

    def test_different_admission_types_are_not_merged_by_original_batch_alias(self):
        self.c.execute('DELETE FROM data.source_format_reference')
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'major_code':'16','source_batch_raw':'本科批','source_admission_type_raw':'一般统考生'}),))
        self.c.execute("INSERT INTO data.gk_official_cutoff SELECT province,year,subject,code,name,grp,major_code,major,score,rank,source_id,'public.csv:3',value_status FROM data.gk_official_cutoff LIMIT 1")
        self.c.execute('INSERT INTO data.official_cutoff_scope VALUES(?,?,?,?)',('o','public.csv:3',json.dumps({'major_code':'16','source_batch_raw':'本科批','source_admission_type_raw':'民族班'}),'{}'))
        meta,rows=self.export();self.assertEqual(len(rows),1)
        fact=json.loads(rows[0]['data_provenance'])['rank']
        self.assertEqual(fact['original_scope']['source_scope_original']['source_admission_type_raw'],'一般统考生')
        self.assertTrue(any(r.get('source_admission_type_raw')=='民族班'for r in meta['rejected']))

    def test_unaligned_original_admission_type_is_not_an_ordinary_candidate(self):
        self.c.execute('DELETE FROM data.source_format_reference')
        for kind in ('民族班','预科','国家专项计划','地方专项计划','中外合作办学','少数民族彝语类','未知招考类型'):
            self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'major_code':'16','source_batch_raw':'本科批','source_admission_type_raw':kind}),))
            meta,rows=self.export();self.assertEqual(rows,[],kind)
            self.assertEqual(meta['rejected'][0]['source_admission_type_raw'],kind)

    def test_special_candidate_requires_explicit_matching_plan_filter(self):
        self.c.execute('ALTER TABLE data.gk_official_cutoff ADD COLUMN plan_type TEXT')
        self.c.execute("UPDATE data.gk_official_cutoff SET plan_type='国家专项计划'")
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'major_code':'16','source_batch_raw':'本科批','source_admission_type_raw':'国家专项计划'}),))
        self.assertEqual(self.export()[1],[])
        with tempfile.TemporaryDirectory()as d:
            result=ex.export_records(self.collect(),'河北','物理',[2025],out=d,key='major',plan_type='国家专项计划')
            self.assertEqual(result['exported_rows'],{'2025':1})
        self.c.execute("UPDATE data.gk_official_cutoff SET plan_type='中外合作办学'")
        with tempfile.TemporaryDirectory()as d:
            result=ex.export_records(self.collect(),'河北','物理',[2025],out=d,key='major',plan_type='中外合作办学')
            self.assertEqual(result['exported_rows'],{'2025':0})
        # 显式筛“未标”也不能把未对齐的专项当普通候选放行。
        self.c.execute('UPDATE data.gk_official_cutoff SET plan_type=NULL')
        with tempfile.TemporaryDirectory()as d:
            result=ex.export_records(self.collect(),'河北','物理',[2025],out=d,key='major',plan_type='未标')
            self.assertEqual(result['exported_rows'],{'2025':0})
        self.c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'major_code':'16','source_batch_raw':'本科批','source_admission_type_raw':'未标'}),))
        with tempfile.TemporaryDirectory()as d:
            result=ex.export_records(self.collect(),'河北','物理',[2025],out=d,key='major',plan_type='未标')
            self.assertEqual(result['exported_rows'],{'2025':0})

if __name__=='__main__':unittest.main()
