import importlib.util
import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts/zhiqu_db.py'
spec = importlib.util.spec_from_file_location('zhiqu_db_full_ingest', SCRIPT)
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)


class FullIngestReadQueries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.edu = Path(self.tmp.name) / 'education.sqlite'
        self.emp = Path(self.tmp.name) / 'employment.sqlite'
        c = sqlite3.connect(self.edu)
        c.executescript('''
            create table institution(institution_id text,name text,moe_code text,province text,status text,established text,closed text,successor_id text);
            create table source(source_id text,grade text,publisher text,title text,landing_url text,file_url text,archive_sha256 text,archive_path text,archive_status text,retrieved text);
            create table institution_profile(institution_id text,year integer,recommend_rate text,n_master text,n_phd text,source_id text,value_status text);
            create table gk_v_usable(record_id text,institution_id text,year integer,min_score real,min_rank integer,source_id text,value_status text);
            insert into institution values('i1','甲大学','10001','江苏','在办',null,null,null);
            insert into source values('vendor','第三方整理','汇编','旧表','','','','','已存原件','2026-01-01');
            insert into source values('official','官方','甲大学招生办','更正公告','','','','','已存原件','2026-01-01');
            insert into gk_v_usable values('old','i1',2025,600,1000,'vendor','{"min_score":{"status":"第三方整理未核"}}');
        ''')
        c.commit(); c.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_optional_views_preserve_old_school_behavior(self):
        result = db.query_school('甲大学', db=self.edu)
        self.assertEqual([s['table'] for s in result['sections']], ['gk_v_usable'])
        self.assertNotIn('gk_v_purchased', {s['table'] for s in result['sections']})

    def test_purchased_view_field_correction_and_compressed_original(self):
        c = sqlite3.connect(self.edu)
        c.executescript('''
            create table purchased_row(row_id text primary key,source_id text,src_sheet text,src_row integer,src_page integer,src_table text,raw_json text not null,raw_zlib blob,raw_codec text,raw_chunk_id integer,raw_offset integer);
            create table purchased_raw_chunk(chunk_id integer primary key,raw_zlib blob,row_count integer);
            create table correction(correction_id text,table_name text,row_key text,field text,before_value text,after_value text,source_id text,date text);
        ''')
        raw = '{"A1":"省内就业","B1":"江苏","B2":612}'
        packed = zlib.compress(json.dumps([raw],ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        c.execute('insert into purchased_raw_chunk values(?,?,?)',(7,packed,1))
        c.execute('insert into purchased_row values(?,?,?,?,?,?,?,?,?,?,?)',('raw1','vendor','Sheet1',12,3,'表1','',None,'zlib-json-list-v1',7,0))
        c.execute("insert into correction values('fix','gk_purchased_record','p1','min_score','600','612','official','2026-01-01')")
        c.execute('''create view gk_v_purchased as
            select 'p1' record_id,'i1' institution_id,2025 year,'江苏' province,'计算机学院' college,'0854' program_code,
                   8 plan_n,612.0 min_score,1000 min_rank,'vendor' source_id,
                   '招生计划' dataset_type,'plan_entry' record_type,'甲大学' school_raw,'组A' group_name,
                   '物化' subject_requirements,printf('%.*c',250,'范围') scope_raw,
                   '{"plan_n":{"status":"第三方整理未核"},"min_score":{"status":"第三方整理未核"}}' value_status,
                   'raw1' raw_row_id,'{"min_score":"official"}' field_source_ids''')
        c.commit(); c.close()
        result = db.query_school('甲大学', db=self.edu)
        sec = next(s for s in result['sections'] if s['table']=='gk_v_purchased')
        row = sec['rows'][0]
        score = row['values']['min_score']
        self.assertEqual(score['value'], 612.0)
        self.assertEqual(score['source_id'], 'official')
        self.assertEqual(score['value_status']['status'], '人工更正')
        self.assertEqual(score['original_source_id'], 'vendor')
        self.assertEqual(row['field_source_ids']['min_score'], 'official')
        self.assertEqual(row['excerpt'], {'A1':'省内就业','B1':'江苏','B2':612})
        self.assertEqual(row['original_locator'], {'src_sheet':'Sheet1','src_page':3,'src_table':'表1','src_row':12})
        self.assertEqual(row['values']['plan_n']['unit'], '人')
        self.assertEqual(row['values']['plan_n']['value'], 8)
        self.assertEqual(db.CONTEXT_LABELS['province'], '省份')
        self.assertEqual(db.CONTEXT_LABELS['college'], '学院')
        self.assertEqual(db.CONTEXT_LABELS['program_code'], '研究生专业码')
        text = db.render_text(result)
        self.assertIn('省份：江苏', text)
        self.assertIn('学院：计算机学院', text)
        self.assertIn('研究生专业码：0854', text)
        self.assertIn('全文见--json', text)
        c = sqlite3.connect(self.edu)
        c.execute('update purchased_row set raw_offset=1 where row_id=\'raw1\'')
        c.commit(); c.close()
        corrupt = db.query_school('甲大学', db=self.edu)
        corrupt_row = next(s for s in corrupt['sections'] if s['table']=='gk_v_purchased')['rows'][0]
        self.assertIsNone(corrupt_row['excerpt'])
        self.assertIsNone(corrupt_row['original_locator'])

    def test_graduate_destination_counts_percent_and_cohort_not_query_year(self):
        c = sqlite3.connect(self.emp)
        c.executescript('''
            create table source(source_id text,grade text,publisher text,title text);
            create table graduate_destination(record_id text,source_id text,institution_name_raw text,province_raw text,city_raw text,
              graduate_cohort text,graduate_cohort_raw text,cohort_status text,category text,item text,item_raw text,
              headcount integer,percentage real,rank integer,value_status text,src_sheet text,src_row integer);
            insert into source values('e1','第三方整理','就业流向汇编','院校就业流向');
            insert into graduate_destination values('d1','e1','甲大学','江苏','南京','未注明','', '未注明','地区','江苏','江苏120人',120,0.35,1,
              '{"headcount":{"status":"第三方整理未核"},"percentage":{"status":"第三方整理未核"}}','就业表',9);
        ''')
        c.execute("insert into graduate_destination values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ('d2','e1','甲大学','江苏','南京','2019','2019届','原表明确','地区','江苏','江苏80人',80,0.2,2,'{}','就业表',10))
        c.commit(); c.close()
        result = db.query_jobs(region='江苏', year=2025, db=self.emp)
        sec = next(s for s in result['sections'] if s['table']=='graduate_destination')
        self.assertEqual(sec['total'], 1)
        row = sec['rows'][0]
        self.assertEqual(row['context']['graduate_cohort'], '未注明')
        self.assertNotIn('year', row['context'])
        self.assertEqual(row['values']['headcount']['unit'], '签约人数')
        self.assertEqual(row['values']['percentage']['unit'], '百分比（原值）')
        rendered = db.render_text(result)
        self.assertEqual([r['record_id'] for r in sec['rows']], ['d1'])
        self.assertIn('签约人数：120 签约人数', rendered)
        self.assertIn('百分比：0.35 百分比（原值）', rendered)
        self.assertIn('名次：1', rendered)
        self.assertTrue(any('未知届别不代表查询年份' in w for w in result['warnings']))
        elsewhere = db.query_jobs(region='南京', db=self.emp)
        self.assertFalse(any(s['table']=='graduate_destination' for s in elsewhere['sections']))
        major_filtered = db.query_jobs(major='江苏', db=self.emp)
        self.assertFalse(any(s['table']=='graduate_destination' for s in major_filtered['sections']))
        self.assertTrue(any('没有按专业统计' in w for w in major_filtered['warnings']))
        cohort_result = db.query_jobs(region='江苏', year=2019, db=self.emp)
        cohort_sec = next(s for s in cohort_result['sections'] if s['table']=='graduate_destination')
        self.assertEqual({r['record_id'] for r in cohort_sec['rows']}, {'d1','d2'})


class CorrectedValueOfficialLocations(unittest.TestCase):
    """All new correction/locator cases use attached in-memory SQLite only."""
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute("attach database ':memory:' as data")
        self.c.executescript('''
            create table data.source(source_id text,grade text,publisher text,title text);
            insert into data.source values('vendor','第三方整理','汇编','购买表');
            insert into data.source values('official-score','官方','省考试院','投档原表');
            insert into data.source values('official-rank','官方','省考试院','位次原表');
            create table data.purchased_check(record_id text,field text,official_source_id text,official_locator text,verdict text);
            create table data.purchased_row(row_id text,raw_json text,src_sheet text,src_row integer,src_page integer,src_table text);
            insert into data.purchased_row values('raw1','{"G":600,"M":1000}','购买工作表',1035,2,'购买表1');
        ''')
        self.addCleanup(self.c.close)
        self.row = {'record_id':'p1','source_id':'vendor','raw_row_id':'raw1',
                    'year':2025,'min_score':612.0,'min_rank':900,'plan_n':8,
                    'src_row':1035,'src_sheet':'购买工作表',
                    'value_status':'{}',
                    'field_source_ids':'{"min_score":"official-score","min_rank":"official-rank"}'}

    def check(self,record='p1',field='min_score',source='official-score',locator='官方PDF物理页7；表2；行5',verdict='不一致'):
        self.c.execute('insert into data.purchased_check values(?,?,?,?,?)',
                       (record,field,source,locator,verdict))

    def record(self):
        return db._record(self.c,'gk_v_purchased',dict(self.row))

    def text(self,record):
        return db.render_text({'sections':[{'table':'gk_v_purchased','title':'逐值来源测试',
            'total':1,'offset':0,'returned':1,'truncated':0,'rows':[record]}]},full=True)

    def test_corrected_fields_use_exact_record_field_and_official_source(self):
        self.check()
        self.check(field='min_rank',source='official-rank',locator='官方位次表；物理页8；行20')
        self.check(record='another-record',locator='不相关记录位置')
        self.check(field='plan_n',locator='不相关字段位置')
        self.check(source='official-rank',locator='不相关来源位置')
        result = self.record()
        self.assertEqual(result['values']['min_score']['official_locator'],'官方PDF物理页7；表2；行5')
        self.assertEqual(result['values']['min_rank']['official_locator'],'官方位次表；物理页8；行20')
        self.assertEqual(result['values']['min_score']['original_source_id'],'vendor')
        self.assertEqual(result['original_locator'],{'src_sheet':'购买工作表','src_page':2,'src_table':'购买表1','src_row':1035})
        self.assertNotIn('official_locator',result['values']['plan_n'])
        rendered = self.text(result)
        self.assertIn('612.0 分〔官方｜省考试院｜official-score；人工更正〕；官方位置：官方PDF物理页7；表2；行5',rendered)
        self.assertIn('900 位〔官方｜省考试院｜official-rank；人工更正〕；官方位置：官方位次表；物理页8；行20',rendered)
        self.assertIn('原始单元格定位：',rendered)
        values_text = rendered.split(' | ')[-1]
        self.assertNotIn('1035',values_text)
        self.assertNotIn('不相关',values_text)

    def test_duplicate_same_position_is_one_official_location(self):
        self.check(); self.check(verdict='一致')
        score = self.record()['values']['min_score']
        self.assertEqual(score['official_locator'],'官方PDF物理页7；表2；行5')
        self.assertNotIn('official_locator_candidates',score)

    def test_conflicting_positions_are_candidates_not_arbitrary_one(self):
        self.check();self.check(locator='官方PDF物理页9；表3；行10')
        result = self.record(); score = result['values']['min_score']
        self.assertIsNone(score['official_locator'])
        self.assertEqual(len(score['official_locator_candidates']),2)
        self.assertIn('未确定唯一',score['official_locator_status'])
        rendered = self.text(result)
        self.assertIn('官方位置待核（多个匹配位置）',rendered)
        self.assertIn('官方PDF物理页7',rendered)
        self.assertIn('官方PDF物理页9',rendered)

    def test_missing_or_blank_official_position_never_uses_purchase_row(self):
        self.check(locator='');self.check(locator=None)
        result = self.record(); score = result['values']['min_score']
        self.assertIsNone(score['official_locator'])
        self.assertEqual(score['official_locator_status'],'未取到逐值官方定位')
        self.assertEqual(result['original_locator']['src_row'],1035)
        rendered = self.text(result)
        self.assertIn('官方位置：未取到',rendered)
        self.assertNotIn('1035',rendered.split(' | ')[-1])

    def test_legacy_missing_check_table_remains_readable_with_explicit_gap(self):
        self.c.execute('drop table data.purchased_check')
        score = self.record()['values']['min_score']
        self.assertIsNone(score['official_locator'])
        self.assertEqual(score['source_id'],'official-score')
        self.assertEqual(score['value_status']['status'],'人工更正')

    def test_incomplete_check_schema_does_not_invent_official_position(self):
        self.c.execute('drop table data.purchased_check')
        self.c.execute('create table data.purchased_check(record_id text,field text)')
        self.assertIsNone(self.record()['values']['min_score']['official_locator'])


class EmploymentIndustryQueries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'employment.sqlite'
        c=sqlite3.connect(self.path)
        c.executescript("""CREATE TABLE source(source_id TEXT,grade TEXT,publisher TEXT,title TEXT);
        INSERT INTO source VALUES('industry-source','第三方整理','购买汇编','专业就业行业分布分析');
        CREATE TABLE employment_major_industry(source_id TEXT,src_sheet TEXT,src_row INTEGER,major_code TEXT,major_name TEXT,industry TEXT,value_number REAL,percentage REAL,unit_raw TEXT,cohort TEXT,value_status TEXT,raw_cells TEXT);
        """)
        statuses=json.dumps({'value_number':{'status':'第三方整理未核'},'percentage':{'status':'来源未提供','reason':'原表未注明百分号单位'}})
        c.execute('INSERT INTO employment_major_industry VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('industry-source','就业行业分布分析',2,'010101','哲学','教育/培训/院校',28,None,'占比（未注明单位）',None,statuses,json.dumps({'A':'010101','D':'28'})))
        c.commit();c.close()

    def tearDown(self):self.tmp.cleanup()

    def test_raw_ratio_is_never_invented_as_percent_and_keeps_original_locator(self):
        result=db.query_jobs(db=self.path,major='010101',year=2026)
        sec=next(s for s in result['sections'] if s['table']=='employment_major_industry');row=sec['rows'][0]
        self.assertEqual(row['values']['value_number']['value'],28)
        self.assertEqual(row['values']['value_number']['unit'],'占比（未注明单位）')
        self.assertEqual(row['values']['value_number']['source_id'],'industry-source')
        self.assertIsNone(row['values']['percentage']['value'])
        self.assertEqual(row['values']['percentage']['value_status']['status'],'来源未提供')
        self.assertEqual(row['context']['graduate_cohort'],'未注明')
        self.assertEqual(row['locator'],{'src_sheet':'就业行业分布分析','src_row':2})
        self.assertEqual(row['excerpt']['D'],'28')
        self.assertTrue(any('不能视为查询年份' in w for w in result['warnings']))

    def test_industry_is_not_a_regional_destination(self):
        result=db.query_jobs(db=self.path,region='江苏')
        self.assertNotIn('employment_major_industry',{s['table'] for s in result['sections']})

    def test_identical_imported_fragments_display_once_and_keep_source_members(self):
        c=sqlite3.connect(self.path)
        c.executescript("""INSERT INTO source VALUES('other-source','第三方整理','另一汇编','相同片段');
        INSERT INTO employment_major_industry SELECT 'other-source',src_sheet,src_row,major_code,major_name,industry,value_number,percentage,unit_raw,cohort,value_status,raw_cells FROM employment_major_industry;
        CREATE TABLE employment_industry_version(source_id TEXT,preferred_source_id TEXT,scope_note TEXT);
        INSERT INTO employment_industry_version VALUES('industry-source','industry-source','仅已入库匿名片段相同');
        INSERT INTO employment_industry_version VALUES('other-source','industry-source','仅已入库匿名片段相同');
        CREATE VIEW v_employment_major_industry AS SELECT * FROM employment_major_industry WHERE source_id='industry-source';""")
        c.commit();c.close()
        result=db.query_jobs(db=self.path,major='010101')
        sec=next(s for s in result['sections'] if s['table']=='employment_major_industry')
        self.assertEqual(sec['total'],1)
        self.assertEqual({x['source_id'] for x in sec['rows'][0]['equivalent_sources']},{'industry-source','other-source'})
        self.assertTrue(any('只显示一份' in w and '未据此' in w for w in result['warnings']))

class LeanCandidateReadQueries(unittest.TestCase):
    """New lean cases use only an attached in-memory fixture, never real files."""
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.execute("attach database ':memory:' as data")
        self.c.executescript('''
        CREATE TABLE data.source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT);
        INSERT INTO data.source VALUES('primary','第三方整理','甲汇编','主来源');
        INSERT INTO data.source VALUES('extra','第三方整理','乙汇编','附来源');
        CREATE TABLE data.purchased_source_key(source_key INTEGER PRIMARY KEY,source_id TEXT);
        INSERT INTO data.purchased_source_key VALUES(1,'primary'),(2,'extra');
        CREATE TABLE data.purchased_locator_run(raw_start INTEGER PRIMARY KEY,raw_end INTEGER,source_key INTEGER,src_sheet TEXT,src_row_start INTEGER,src_row_step INTEGER,src_page INTEGER,src_table TEXT);
        INSERT INTO data.purchased_locator_run VALUES(10,12,1,'主表',100,2,NULL,NULL),(20,21,2,'附表',9,0,3,'表二'),(30,31,2,NULL,NULL,0,4,'PDF表');
        CREATE TABLE data.purchased_observation(record_key INTEGER PRIMARY KEY,source_key INTEGER,raw_id INTEGER);
        INSERT INTO data.purchased_observation VALUES(7,1,11);
        CREATE TABLE data.purchased_observation_source(record_key INTEGER,raw_id INTEGER,PRIMARY KEY(record_key,raw_id));
        INSERT INTO data.purchased_observation_source VALUES(7,20),(7,30);
        CREATE TABLE data.purchased_audit_sample(source_id TEXT,sample_index INTEGER,raw_id INTEGER,src_sheet TEXT,src_row INTEGER,src_page INTEGER,src_table TEXT,row_sha256 TEXT,cells_json TEXT,note TEXT);
        CREATE VIEW data.gk_v_purchased AS SELECT 'p7' record_id,7 record_key,'primary' source_id,'t19-locator-11' raw_row_id,2025 year,'甲大学' school_raw,'招生计划' dataset_type,'plan_entry' record_type,0 plan_n,600.0 min_score,'{}' value_status,'{}' field_source_ids,'[["专项","原招生范围"]]' scope_raw,'[["学校城市","南京"],["双一流","原表标签"]]' annotation_json;
        ''')
        self.addCleanup(self.c.close)

    def row(self):return dict(self.c.execute('select * from data.gk_v_purchased').fetchone())
    def record(self,row=None):return db._record(self.c,'gk_v_purchased',self.row() if row is None else row)
    def render(self,r,full=False):return db.render_text({'sections':[{'table':'gk_v_purchased','title':'lean测试','total':1,'offset':0,'returned':1,'truncated':0,'rows':[r]}]},full=full)
    def sample(self,source='primary',raw_id=11,row=102,cells=None):
        import hashlib
        cells={'A':'甲大学','D':0} if cells is None else cells;raw=json.dumps(cells,ensure_ascii=False)
        self.c.execute('insert into data.purchased_audit_sample values(?,?,?,?,?,?,?,?,?,?)',(source,1,raw_id,'主表',row,None,None,hashlib.sha256(raw.encode()).hexdigest(),raw,'少量匿名抽样'))

    def test_run_predecessor_and_step_restore_locator_without_full_raw(self):
        r=self.record();self.assertEqual(r['original_locator'],{'src_sheet':'主表','src_row':102});self.assertEqual(r['locator'],r['original_locator']);self.assertIsNone(r['excerpt'])
        self.assertIn('仅保留定位与抽样，此行未留全文',r['excerpt_kind']);self.assertIn('此行未留全文',self.render(r));self.assertEqual(r['values']['plan_n']['value'],0)
        self.assertNotIn('purchased_row',db._tables(self.c));self.assertNotIn('purchased_raw_chunk',db._tables(self.c))

    def test_run_boundary_gap_never_borrows_previous_source_position(self):
        for raw_id in (9,13,19,22,32):
            with self.subTest(raw_id=raw_id):self.assertIsNone(db._lean_locator(self.c,raw_id))
        r=self.row();r['raw_row_id']='t19-locator-13';bad=self.record(r);self.assertIsNone(bad['original_locator']);self.assertIn('未取到',bad['locator']['locator_status'])

    def test_zero_step_and_pdf_missing_row_are_preserved(self):
        self.assertEqual(db._lean_locator(self.c,21)['locator'],{'src_sheet':'附表','src_page':3,'src_table':'表二','src_row':9})
        pdf=db._lean_locator(self.c,31);self.assertEqual(pdf['source_id'],'extra');self.assertEqual(pdf['locator'],{'src_page':4,'src_table':'PDF表'})

    def test_exact_sample_is_quoted_with_sample_label_and_not_whole_source_claim(self):
        self.sample();r=self.record();self.assertEqual(r['excerpt'],{'A':'甲大学','D':0});self.assertIn('匿名抽样',r['excerpt_kind']);self.assertIn('非官方逐字原文',r['excerpt_kind'])
        self.assertNotIn('purchased_row原始单元格',r['excerpt_kind'])

    def test_wrong_source_or_locator_sample_is_not_used(self):
        self.sample(source='extra');self.assertIsNone(self.record()['excerpt']);self.c.execute('delete from data.purchased_audit_sample');self.sample(row=999)
        r=self.record();self.assertIsNone(r['excerpt']);self.assertIn('定位不一致',r['excerpt_status']);self.assertEqual(r['original_locator']['src_row'],102)

    def test_sample_hash_change_is_not_presented_as_quote(self):
        self.sample();self.c.execute("update data.purchased_audit_sample set cells_json='{}'");r=self.record();self.assertIsNone(r['excerpt']);self.assertIn('指纹不符',r['excerpt_status'])

    def test_additional_source_links_include_own_id_and_row_location(self):
        r=self.record();self.assertEqual([x['source_id'] for x in r['additional_sources']],['extra','extra']);self.assertEqual(r['additional_sources'][0]['locator']['src_row'],9);self.assertEqual(r['additional_sources'][1]['locator']['src_page'],4)
        self.assertNotIn('src_row',r['additional_sources'][1]['locator']);text=self.render(r,full=True);self.assertIn('额外来源：extra',text);self.assertIn('附表',text)
        self.c.execute('insert into data.purchased_observation_source values(7,11)');self.assertEqual(len(self.record()['additional_sources']),2)

    def test_extra_gap_retains_explicit_unknown_instead_of_primary_position(self):
        self.c.execute('insert into data.purchased_observation_source values(7,99)');extra=self.record()['additional_sources'][-1];self.assertIsNone(extra['source_id']);self.assertIn('未借用主来源',extra['locator']['locator_status'])

    def test_annotation_output_is_separate_from_admission_scope(self):
        r=self.record();self.assertEqual(r['annotation_json'],[['学校城市','南京'],['双一流','原表标签']]);self.assertEqual(r['context']['scope_raw'],'[["专项","原招生范围"]]');self.assertNotIn('annotation_json',r['context'])
        self.assertEqual(r['annotation_status']['status'],'第三方整理未核');self.assertNotIn('南京',self.render(r));text=self.render(r,full=True);self.assertIn('原表背景旁注（第三方整理未核，不作招生范围）',text);self.assertIn('南京',text)

    def test_primary_observation_source_binding_cannot_be_changed_by_view(self):
        r=self.row();r['source_id']='extra';bad=self.record(r);self.assertIsNone(bad['original_locator']);self.assertIsNone(bad['excerpt'])
        r=self.row();r.pop('raw_row_id');good=self.record(r);self.assertEqual(good['original_locator']['src_row'],102)

    def test_malformed_raw_id_does_not_fall_back_to_a_different_identity(self):
        for raw in ('t19-locator-not-an-integer','t19-locator-999999999999999999999999999'):
            row=self.row();row['raw_row_id']=raw
            with self.subTest(raw=raw):self.assertIsNone(self.record(row)['original_locator'])

    def test_incomplete_optional_locator_schema_shows_a_gap(self):
        self.c.execute('drop table data.purchased_source_key');r=self.record();self.assertIsNone(r['original_locator']);self.assertIsNone(r['excerpt']);self.assertIn('未取到',r['locator']['locator_status'])

    def test_lean_industry_uses_saved_business_original_not_removed_raw_cells(self):
        row={'source_id':'primary','major_code':'010101','industry':'教育','value_raw':'28','value_number':28,'percentage':None,'unit_raw':'占比（未注明单位）','cohort':None,'value_status':'{}','src_sheet':'行业','src_row':2}
        r=db._record(self.c,'employment_major_industry',row);self.assertEqual(r['excerpt'],{'占比原格':'28'});self.assertIn('未保留全行',r['excerpt_kind']);self.assertEqual(r['values']['value_number']['value'],28);self.assertIsNone(r['values']['percentage']['value']);self.assertEqual(r['locator'],{'src_sheet':'行业','src_row':2})

    def test_lean_graduate_compatibility_view_keeps_counts_and_positions(self):
        self.c.executescript('''CREATE TABLE data.destination_fact(record_id TEXT,source_id TEXT,cell_key TEXT,headcount INTEGER,percentage REAL,src_sheet TEXT,src_row INTEGER,src_col TEXT);CREATE TABLE data.cell_dictionary(cell_key TEXT,source_cell_raw TEXT);INSERT INTO data.cell_dictionary VALUES('c','原就业单元格');INSERT INTO data.destination_fact VALUES('d','primary','c',0,12.5,'Flow',2,'D');CREATE VIEW data.graduate_destination AS SELECT f.*,c.source_cell_raw FROM data.destination_fact f JOIN data.cell_dictionary c USING(cell_key);''')
        row=dict(self.c.execute('select * from data.graduate_destination').fetchone());r=db._record(self.c,'graduate_destination',row);self.assertEqual(r['values']['headcount']['value'],0);self.assertEqual(r['values']['percentage']['value'],12.5);self.assertEqual(r['locator'],{'src_sheet':'Flow','src_row':2,'src_col':'D'})

    def test_section_reads_lean_view_record_key_and_annotations(self):
        section=db._section(self.c,'gk_v_purchased','1',[],10,0);self.assertEqual(section['total'],1);self.assertEqual(section['rows'][0]['original_locator']['src_row'],102);self.assertEqual(len(section['rows'][0]['additional_sources']),2);self.assertTrue(section['rows'][0]['annotation_json'])


class NumericConflictReadQueries(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.execute("attach database ':memory:' as data")
        self.c.executescript("""CREATE TABLE data.source(source_id TEXT,grade TEXT,publisher TEXT,title TEXT);
        INSERT INTO data.source VALUES('vendor','第三方整理','购买汇编','购买表'),('official','官方','省考试院','官方更正');
        CREATE TABLE data.purchased_check(record_id TEXT,field TEXT,official_source_id TEXT,official_locator TEXT);
        INSERT INTO data.purchased_check VALUES('p1','min_score','official','官方PDF第7页第3行');
        CREATE TABLE data.gk_purchased_record(record_id TEXT,min_score REAL);
        INSERT INTO data.gk_purchased_record VALUES('p1',600);
        """)
        self.addCleanup(self.c.close)
        self.base={'record_id':'p1','source_id':'vendor','min_score':0,'min_rank':None,'plan_n':5,'value_status':json.dumps({'min_score':{'status':'第三方整理未核'},'min_rank':{'status':'来源未提供'},'plan_n':{'status':'第三方整理未核'}})}
    def record(self,marker=None,**overrides):
        row=dict(self.base);row.update(overrides)
        if marker is not None:row['numeric_conflict_fields']=marker
        return db._record(self.c,'gk_v_purchased',row)
    def render(self,r):return db.render_text({'sections':[{'table':'gk_v_purchased','title':'冲突测试','total':1,'offset':0,'returned':1,'truncated':0,'rows':[r]}]})
    def test_only_hit_field_zero_gets_conflict_note(self):
        r=self.record('["min_score"]');score=r['values']['min_score'];self.assertEqual(score['value'],0);self.assertEqual(score['grade'],'第三方整理');self.assertEqual(score['value_status']['status'],'第三方整理未核');self.assertEqual(score['numeric_conflict']['reason'],db.NUMERIC_CONFLICT_NOTE)
        self.assertNotIn('numeric_conflict',r['values']['plan_n']);self.assertNotIn('numeric_conflict',r['values']['min_rank']);self.assertEqual(r['numeric_conflict_fields'],['min_score'])
        self.assertIn(db.NUMERIC_CONFLICT_NOTE,db._value_text(score));self.assertNotIn(db.NUMERIC_CONFLICT_NOTE,db._value_text(r['values']['plan_n']));self.assertIn('第三方版本冲突字段：最低分',self.render(r))
    def test_null_hit_keeps_null_and_existing_missing_state(self):
        r=self.record('["min_rank"]');rank=r['values']['min_rank'];self.assertIsNone(rank['value']);self.assertEqual(rank['value_status']['status'],'来源未提供');self.assertIn(db.NUMERIC_CONFLICT_NOTE,db._value_text(rank));self.assertNotIn('numeric_conflict',r['values']['min_score'])
    def test_official_effective_correction_source_and_locator_survive_conflict(self):
        r=self.record('["min_score"]',min_score=612,field_source_ids='{"min_score":"official"}');score=r['values']['min_score'];self.assertEqual(score['value'],612);self.assertEqual(score['source_id'],'official');self.assertEqual(score['grade'],'官方');self.assertEqual(score['original_source_id'],'vendor');self.assertEqual(score['value_status']['status'],'人工更正');self.assertEqual(score['official_locator'],'官方PDF第7页第3行')
        text=db._value_text(score);self.assertIn('612 分〔官方',text);self.assertIn('官方位置：官方PDF第7页第3行',text);self.assertIn(db.NUMERIC_CONFLICT_NOTE,text);self.assertEqual(self.c.execute('select min_score from data.gk_purchased_record').fetchone()[0],600)
    def test_nullable_bad_json_and_non_list_markers_never_flag_other_fields_or_raise(self):
        for marker in ('', 'null','{bad','{}','[1]','["min_score",null]'):
            with self.subTest(marker=marker):
                r=self.record(marker);self.assertEqual(r['numeric_conflict_fields'],[]);self.assertFalse(any('numeric_conflict' in v for v in r['values'].values()))
        row=dict(self.base,numeric_conflict_fields=None);r=db._record(self.c,'gk_v_purchased',row);self.assertEqual(r['numeric_conflict_fields'],[])
        bad=self.record('{bad');self.assertIn('未能解析',bad['numeric_conflict_fields_status']);self.assertIn('未推断具体冲突字段',self.render(bad))
    def test_legacy_without_column_has_no_new_conflict_state(self):
        r=self.record();self.assertNotIn('numeric_conflict_fields',r);self.assertFalse(any('numeric_conflict' in v for v in r['values'].values()));self.assertNotIn(db.NUMERIC_CONFLICT_NOTE,self.render(r))
    def test_valid_list_is_preserved_without_unknown_field_polluting_known_values(self):
        marker=['min_score','unknown_field','min_score'];r=self.record(marker);self.assertEqual(r['numeric_conflict_fields'],marker);self.assertEqual(r['values']['min_score']['value'],0);self.assertNotIn('numeric_conflict',r['values']['plan_n']);self.assertEqual(self.base['min_score'],0)


if __name__ == '__main__':
    unittest.main()
