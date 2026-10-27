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
        proof={'verdict':'一致','field':'rank','scope':ex._scope(r),'thirdparty_scope':ex._scope(r),'official_value':1000,'thirdparty_value':1000,'official_source':{'grade':'官方','source_id':'o','landing_url':'https://example.edu.cn'},'official_locator':{'row':7},'comparison_basis':'同事实同口径逐值'}
        m=ex._meta(r,'rank',1000,{'grade':'第三方整理','source_id':'v'},{},{},cross_check=proof)
        self.assertEqual(m['display_grade'],'官方一致')
        self.assertEqual(m['grade'],'第三方整理');self.assertEqual(m['cross_check'],proof)

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

    def test_missing_header_does_not_guess_from_source_id_or_title(self):
        self.c.execute('DELETE FROM data.source_format_reference');self.assertEqual(self.export()[1],[])

if __name__=='__main__':unittest.main()
