"""Official membership precedes third-party labels; precision is not conflict."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts/zhiqu_db.py'
spec = importlib.util.spec_from_file_location('official_reference_query', SCRIPT)
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)


class OfficialReference(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'school.sqlite'
        c = sqlite3.connect(self.path)
        c.executescript('''
          CREATE TABLE institution(institution_id TEXT PRIMARY KEY,name TEXT,province TEXT,city TEXT);
          INSERT INTO institution VALUES('4132010285','苏州大学','江苏省','苏州市');
          CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT);
          INSERT INTO source VALUES('moe','官方','教育部','完整名单','https://www.moe.gov.cn/list');
          INSERT INTO source VALUES('vendor-file-1','第三方整理','购买汇编','地区文件','');
          CREATE TABLE v_institution_official_reference(institution_id TEXT,programme TEXT,value TEXT,is_member INTEGER,list_id TEXT,list_year INTEGER,source_id TEXT,source_url TEXT,scope_note TEXT,excerpt TEXT,src_locator TEXT,comparison_basis TEXT);
          INSERT INTO v_institution_official_reference VALUES('4132010285','985工程','未列入该版名单',0,'985',NULL,'moe','https://www.moe.gov.cn/list','名单截至年未标','“985工程”学校名单','{}','完整名单集合比对');
          INSERT INTO v_institution_official_reference VALUES('4132010285','211工程','是',1,'211',NULL,'moe','https://www.moe.gov.cn/list','名单截至年未标','苏州大学','{}','名单原项');
          INSERT INTO v_institution_official_reference VALUES('4132010285','办学所在地','苏州市',NULL,'schools',2025,'moe','https://www.moe.gov.cn/list','截至2025','苏州大学｜苏州市','{}','原表字段');
          CREATE TABLE core_delta_text(text_id INTEGER PRIMARY KEY,value TEXT);
          INSERT INTO core_delta_text VALUES(1,'1'),(2,'0'),(3,'江苏'),(4,'江苏苏州'),(5,'0.128');
          CREATE TABLE school_attribute_fact(attribute_id INTEGER PRIMARY KEY,institution_id TEXT,field_name TEXT,value_text_id INTEGER);
          INSERT INTO school_attribute_fact VALUES(1,'4132010285','is_985',1),(2,'4132010285','is_985',2),(3,'4132010285','school_location',3),(4,'4132010285','school_location',4),(5,'4132010285','recommend_rate',5);
          CREATE TABLE school_profile_source(ingest_id INTEGER,province TEXT,school_code TEXT,src_file INTEGER,src_row INTEGER,is_985 INTEGER,school_location INTEGER,recommend_rate INTEGER);
          INSERT INTO school_profile_source VALUES(1,'省份甲','01',1,10,1,3,5),(2,'省份乙','01',1,20,2,4,5);
        ''')
        c.commit()
        c.close()

    def tearDown(self):
        self.tmp.cleanup()

    def result(self):
        return db.query_school('苏州大学', db=self.path)

    def test_default_official_only_for_membership_full_keeps_conflicts(self):
        result = self.result()
        text = db.render_text(result)
        self.assertIn('985工程：未列入该版名单', text)
        self.assertIn('211工程：是', text)
        self.assertNotIn('985院校：', text)
        self.assertIn('保研比例：0.128', text)
        full = db.render_text(result, full=True)
        self.assertIn('985院校：', full)
        self.assertIn('与官方名单冲突', full)
        self.assertEqual(result['sections'][0]['table'], 'institution_official_reference')

    def test_location_precision_has_no_disagreement_flag(self):
        result = self.result()
        self.assertIn('办学所在地：苏州市', db.render_text(result))
        rows = [r for s in result['sections'] for r in s['rows'] if 'school_location' in r['values']]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row['default_hidden'])
            self.assertIsNone(row['source_conflict'])
            self.assertIn('精度不同', row['context']['official_comparison'])

    def test_list_publication_year_not_fabricated_into_effective_year(self):
        result = self.result()
        row = next(r for r in result['sections'][0]['rows'] if '985工程' in r['values'])
        self.assertIsNone(row['reference']['list_year'])
        self.assertEqual(row['values']['985工程']['value_status']['status'], '推算')
        self.assertIn('不代替名单年份', row['context']['reference_scope'])

    def test_unmatched_official_identity_does_not_restore_thirdparty_membership(self):
        with sqlite3.connect(self.path) as c:
            c.execute('DELETE FROM v_institution_official_reference')
        result = self.result()
        text = db.render_text(result)
        self.assertNotIn('985院校：', text)
        self.assertIn('985院校：', db.render_text(result, full=True))

    def test_official_reference_source_returns_original_excerpt_and_coordinate(self):
        result = db.query_source('moe', db=self.path)
        self.assertEqual(result['matching_rows_by_table']['v_institution_official_reference'], 3)
        self.assertTrue(all('src_locator' in item['locator'] for item in result['locations']))
        self.assertIn('苏州大学', [item['excerpt'] for item in result['locations']])

    def test_unresolved_identity_is_never_false_membership(self):
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE v_institution_official_reference SET is_member=NULL,value='身份口径未能唯一判断' WHERE programme='211工程'")
        text = db.render_text(self.result())
        self.assertIn('211工程：身份口径未能唯一判断', text)
        self.assertNotIn('211工程：未列入', text)


if __name__ == '__main__':
    unittest.main()
