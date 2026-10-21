"""Canonical school facts: fictional SQLite fixtures, no local production DB reads."""
import importlib.util,sqlite3,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('school_attribute_query_db',Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts/zhiqu_db.py')
db=importlib.util.module_from_spec(spec);spec.loader.exec_module(db)

class SchoolAttributeQuery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'fixture.sqlite'
  self.c=sqlite3.connect(self.path);self.addCleanup(self.c.close)
  self.c.executescript('''
  CREATE TABLE institution(institution_id TEXT,name TEXT,province TEXT);INSERT INTO institution VALUES('i1','甲大学','江苏');
  CREATE TABLE source(source_id TEXT,grade TEXT,publisher TEXT,title TEXT);INSERT INTO source VALUES('vendor-file-1','第三方整理','甲汇编','甲文件'),('vendor-file-2','第三方整理','乙汇编','乙文件'),('core-source','第三方整理','丙汇编','丙文件');
  CREATE TABLE core_delta_text(text_id INTEGER PRIMARY KEY,value TEXT UNIQUE);
  INSERT INTO core_delta_text VALUES(1,'重点'),(2,'0.128'),(3,'0.149'),(4,'88'),(5,'甲学科；乙学科'),(6,'1'),(7,'测试表'),(8,'D'),(9,'物化'),(10,'89');
  CREATE TABLE school_attribute_fact(attribute_id INTEGER PRIMARY KEY,institution_id TEXT,field_name TEXT,value_text_id INTEGER);
  CREATE INDEX school_attribute_institution_field ON school_attribute_fact(institution_id,field_name,value_text_id);
  INSERT INTO school_attribute_fact VALUES(1,'i1','school_level',1),(2,'i1','recommend_rate',2),(3,'i1','recommend_rate',3),(4,'i1','n_master',4),(5,'i1','master_list',5),(6,'i1','is_985',6),(7,'other','school_level',1);
  CREATE TABLE school_profile_source(ingest_id INTEGER,province TEXT,school_code TEXT,school_level INTEGER,recommend_rate INTEGER,n_master INTEGER,master_list INTEGER,src_file INTEGER,src_row INTEGER);
  INSERT INTO school_profile_source VALUES(1,'江苏','001',1,2,4,5,1,12),(1,'浙江','002',1,2,4,5,2,24),(1,'北京','003',NULL,3,NULL,NULL,2,30);
  CREATE TABLE school_core_attribute_map(original_value_id INTEGER PRIMARY KEY,context_id INTEGER,attribute_id INTEGER);
  CREATE INDEX school_core_map_attribute_context ON school_core_attribute_map(attribute_id,context_id);
  INSERT INTO school_core_attribute_map VALUES(11,1,6),(12,2,6);
  CREATE TABLE school_core_attribute_source(original_value_id INTEGER,locator_id INTEGER,col_id INTEGER,PRIMARY KEY(original_value_id,locator_id,col_id)) WITHOUT ROWID;
  INSERT INTO school_core_attribute_source VALUES(11,1,8),(12,2,8);
  CREATE TABLE core_delta_locator(locator_id INTEGER PRIMARY KEY,source_key INTEGER,sheet_id INTEGER,src_row INTEGER);
  INSERT INTO core_delta_locator VALUES(1,1,7,2),(2,1,7,9);
  CREATE TABLE core_delta_source(source_key INTEGER PRIMARY KEY,source_id TEXT);INSERT INTO core_delta_source VALUES(1,'core-source');
  ''');self.c.commit()
 def section(self,**kwargs):return next(x for x in db.query_school('甲大学',db=self.path,**kwargs)['sections'] if x['table']=='school_attribute_fact')
 def test_field_paging_keeps_all_conflicting_values(self):
  sec=self.section(limit=1,offset=1)
  self.assertEqual((sec['total'],sec['fact_count'],sec['returned'],len(sec['rows'])),(5,6,1,2))
  self.assertEqual(['0.128','0.149'],[r['values']['recommend_rate']['value'] for r in sec['rows']])
  self.assertTrue(all(r['source_conflict']=='来源之间不一致' for r in sec['rows']))
 def test_multiple_sources_real_coordinates_without_guessed_sheet(self):
  row=self.section()['rows'][0];self.assertEqual(2,len(row['sources']))
  self.assertEqual({'year_status':'未记录'},row['context'])
  self.assertEqual(['vendor-file-1','vendor-file-2'],[x['source']['source_id'] for x in row['sources']])
  self.assertEqual([12,24],[x['locator']['src_row'] for x in row['sources']]);self.assertTrue(all('src_sheet' not in x['locator'] for x in row['sources']))
  self.assertTrue(all('src_table' not in x['locator'] for x in row['sources']))
  self.assertTrue(all(x['locator']['database_table']=='gk_school_info' for x in row['sources']))
  self.assertIn('统计年份未明',self.section()['title'])
 def test_core_sources_use_true_first_last_not_contiguous_range(self):
  row=next(r for r in self.section()['rows'] if 'is_985' in r['values']);loc=row['sources'][0]['locator']
  self.assertEqual((2,2,9,2),(loc['src_row'],loc['first_row'],loc['last_row'],loc['matched_rows']))
  self.assertEqual(('测试表','D'),(loc['src_sheet'],loc['src_col']));self.assertIn('不表示中间各行',loc['locator_status'])
  plans=' '.join(str(x) for x in self.c.execute('EXPLAIN QUERY PLAN SELECT m.original_value_id FROM school_core_attribute_map m CROSS JOIN school_core_attribute_source s ON s.original_value_id=m.original_value_id WHERE m.attribute_id=6'))
  self.assertIn('school_core_map_attribute_context',plans)
 def test_quarantined_sheet_cannot_reappear_as_a_school_attribute(self):
  self.c.executescript('CREATE TABLE core_delta_scope_issue(source_key INTEGER,sheet_id INTEGER,PRIMARY KEY(source_key,sheet_id)); INSERT INTO core_delta_scope_issue VALUES(1,7);');self.c.commit()
  sec=self.section()
  self.assertEqual(1,sec['excluded_facts'])
  self.assertNotIn('is_985',sec['canonical_fields'])
  self.assertFalse(any('is_985' in r['values'] for r in sec['rows']))
  self.assertIn('沿用原工作表身份隔离',db.render_text(db.query_school('甲大学',db=self.path)))
 def test_valid_source_keeps_fact_but_quarantined_sources_are_excluded(self):
  self.c.executescript('''CREATE TABLE core_delta_scope_issue(source_key INTEGER,sheet_id INTEGER,PRIMARY KEY(source_key,sheet_id));
  INSERT INTO core_delta_scope_issue VALUES(1,7);
  INSERT INTO core_delta_source VALUES(2,'clean');
  INSERT INTO source VALUES('clean','第三方整理','有效汇编','有效文件');
  INSERT INTO core_delta_locator VALUES(3,2,7,15);
  INSERT INTO school_core_attribute_source VALUES(11,3,8);''');self.c.commit()
  row=next(r for r in self.section()['rows'] if 'is_985' in r['values'])
  self.assertEqual(['clean'],[s['source']['source_id'] for s in row['sources']])
  self.assertEqual(15,row['sources'][0]['locator']['src_row'])
  self.assertEqual(1,row['sources'][0]['locator']['matched_rows'])
 def test_declared_count_only_when_unique_nonnegative_integer(self):
  row=next(r for r in self.section()['rows'] if 'master_list' in r['values']);self.assertEqual(88,row['values']['master_list']['declared_count'])
  self.c.execute("INSERT INTO school_attribute_fact VALUES(8,'i1','n_master',10)")
  self.c.execute("INSERT INTO school_profile_source VALUES(1,'山西','004',NULL,NULL,8,NULL,2,41)");self.c.commit()
  row=next(r for r in self.section()['rows'] if 'master_list' in r['values']);self.assertNotIn('declared_count',row['values']['master_list'])
 def test_empty_facts_excluded_source_status_and_render(self):
  self.c.executescript("INSERT INTO core_delta_text VALUES(20,'');INSERT INTO school_attribute_fact VALUES(20,'i1','empty',20);");self.c.commit()
  sec=self.section();self.assertEqual(5,sec['total']);v=sec['rows'][0]['values']['school_level']
  self.assertEqual('第三方整理',v['grade']);self.assertEqual('第三方整理未核',v['value_status']['status'])
  text=db.render_text(db.query_school('甲大学',db=self.path));self.assertIn('来源之间不一致',text);self.assertIn('88 个',text)
 def test_canonical_core_duplicate_filter_preserves_other_fields(self):
  self.c.executescript('''CREATE TABLE core_test(record_id TEXT,institution_id TEXT,field_name TEXT,value TEXT,source_id TEXT);
  INSERT INTO core_test VALUES('a','i1','is_985','1','core-source'),('b','i1','is_211','1','core-source'),('c','i1','subject_requirements','物化','core-source');
  CREATE VIEW v_core_delta_attribute AS SELECT * FROM core_test;''');self.c.commit()
  sections=db.query_school('甲大学',db=self.path,limit=1)['sections'];core=next(s for s in sections if s['table']=='core_delta')
  self.assertEqual(2,core['total']);self.assertNotIn('is_985',core['rows'][0]['values'])
  self.assertEqual('is_211',next(iter(core['rows'][0]['values'])))
 def test_old_layout_unchanged_without_canonical_table(self):
  self.c.executescript('DROP TABLE school_attribute_fact; CREATE TABLE institution_profile(institution_id TEXT,recommend_rate TEXT,source_id TEXT); INSERT INTO institution_profile VALUES(\'i1\',\'0.128\',\'vendor-file-1\');');self.c.commit()
  r=db.query_school('甲大学',db=self.path);self.assertEqual(['institution_profile'],[s['table'] for s in r['sections']]);self.assertEqual('0.128',r['sections'][0]['rows'][0]['values']['recommend_rate']['value'])
if __name__=='__main__':unittest.main()
