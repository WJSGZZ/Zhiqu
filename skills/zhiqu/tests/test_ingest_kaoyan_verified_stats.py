import copy, importlib.util, json, sqlite3, sys, unittest
from pathlib import Path
import test_ingest_kaoyan_catalog as catalog_tests
P=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
sys.path.insert(0,str(P))
spec=importlib.util.spec_from_file_location('verified_stats',P/'ingest_kaoyan_verified_stats.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class VerifiedAnonymousStatsTest(unittest.TestCase):
    def setUp(self):
        self.base=catalog_tests.IngestKaoyanCatalogTest();self.base.setUp();self.path=self.base.path
        extra='scope scope_parse_status quarantine_reason statistics_complete scope_mismatch scope_mismatch_note locator_method locator_status extra_json value_status'.split()
        cols=sorted(m.FIELDS | set(extra))
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE ky_score_dist('+','.join('"'+k+'" '+('REAL' if k in ('min','median','max') else 'INTEGER' if k in ('n','year','src_page') else 'TEXT')+(' PRIMARY KEY' if k=='record_id' else '') for k in cols)+')')
        src=copy.deepcopy(self.base.m['sources'][0]);src['retrieved']='2026-10-23'
        row={k:None for k in m.FIELDS};row.update(record_id='stats-example',institution_id='4135010384',school='厦门大学',college='某学院',program_code='081200',program_name='计算机科学与技术',year=2026,list_type='拟录取',admission_route='未注明',n=3,min=300,median=320,max=340,source_id='s1',src_page=1,src_table='表1',src_row='原数据行1—4',scope_raw='按原学院/专业/专项/学习方式分组；不推断一志愿或调剂')
        proof=dict(source_id='s1',original_rows=4,included_rows=3,excluded_rows=1,exclusions={'原件未给初试成绩':1},sample_count=3,sample_locators=[{'page':1,'table':1,'row':i} for i in (1,2,3)],sample_passed=True,dual_read_equal=True,score_column='初试成绩',method='两独立解析内存逐格比较',review_status='approved')
        self.man={'sources':[src],'rows':[row],'files':[proof]}
    def tearDown(self):self.base.tearDown()
    def test_available_aggregate_and_idempotence(self):
        self.assertEqual(m.ingest(self.path,self.man)['rows_inserted'],1)
        self.assertEqual(m.ingest(self.path,self.man)['rows_existing'],1)
        with sqlite3.connect(self.path) as c:
            row=c.execute('SELECT n,median,quarantine_reason,extra_json FROM ky_score_dist').fetchone()
            self.assertEqual(row[:3],(3,320,None));self.assertIn('file_proof_sha256',json.loads(row[3]))
    def test_incomplete_or_failed_file_is_rejected(self):
        for change in ({'original_rows':5},{'sample_count':2,'sample_locators':[{'page':1,'table':1,'row':i} for i in (1,2)]},{'sample_passed':False},{'dual_read_equal':False},{'review_status':'pending'},{'score_column':'总成绩'}):
            data=copy.deepcopy(self.man);data['files'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):m.ingest(self.path,data)
        with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0)
    def test_group_totals_must_match_original(self):
        data=copy.deepcopy(self.man);data['rows'][0]['n']=4
        with self.assertRaisesRegex(ValueError,'人数'):m.ingest(self.path,data)
    def test_single_person_group_rejected(self):
        data=copy.deepcopy(self.man);data['rows'][0]['n']=1
        with self.assertRaisesRegex(ValueError,'n>=3'):m.ingest(self.path,data)
        with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM ky_score_dist').fetchone()[0],0)
    def test_two_person_group_rejected(self):
        data=copy.deepcopy(self.man);data['rows'][0]['n']=2
        with self.assertRaisesRegex(ValueError,'n>=3'):m.ingest(self.path,data)
        with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM ky_score_dist').fetchone()[0],0)
    def test_individual_values_not_an_input_format(self):
        for key,value in [('candidate_name','forbidden'),('scores',[300,340])]:
            data=copy.deepcopy(self.man);data['rows'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):m.ingest(self.path,data)
    def test_existing_numbers_unchanged_on_conflict(self):
        m.ingest(self.path,self.man);self.man['rows'][0]['median']=321
        with self.assertRaisesRegex(ValueError,'冲突'):m.ingest(self.path,self.man)
        with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT median FROM ky_score_dist').fetchone()[0],320)
    def test_only_candidate(self):
        with self.assertRaises(ValueError):m.ingest(self.path.with_name('education.sqlite'),self.man)

if __name__=='__main__':unittest.main()
