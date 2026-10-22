import copy, importlib.util, sqlite3, sys, unittest
from pathlib import Path
import test_ingest_kaoyan_lines as lines_tests
P=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
sys.path.insert(0,str(P))
spec=importlib.util.spec_from_file_location('ingest_kaoyan_stats',P/'ingest_kaoyan_stats.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
sys.path.pop(0)
class AnonymousStatsTest(unittest.TestCase):
 def setUp(self):
  self.base=lines_tests.IngestKaoyanLinesTest();self.base.setUp();self.path=self.base.path
  fields='record_id institution_id school college program_code program_name list_type admission_route special_plan direction joint_program source_id year n min median max scope scope_raw scope_parse_status src_row src_page src_table input_file input_row quarantine_reason statistics_complete scope_mismatch scope_mismatch_note locator_method locator_status extra_json value_status'.split()
  with sqlite3.connect(self.path) as c:c.execute('CREATE TABLE ky_score_dist('+','.join('"'+k+'" '+('REAL' if k in ('year','n','min','median','max') else 'TEXT')+(' PRIMARY KEY' if k=='record_id' else '') for k in fields)+')')
  s=copy.deepcopy(self.base.m['sources'][0]);s.update(archive_sha256='a'*64,archive_status='已删除（有指纹，核对见记录）',archive_path='')
  r={k:'' for k in m.FIELDS};r.update(record_id='a',institution_id='1000000001',school='甲大学',source_id='s1',year=2026,list_type='复试',n=12,min=300,median=320,max=345,handoff_file='anonymous.csv',handoff_row=2)
  self.man={'sources':[s],'rows':[r]}
 def tearDown(self):self.base.tearDown()
 def test_handoff_is_quarantined_and_not_original_locator(self):
  self.assertEqual(m.ingest(self.path,self.man)['quarantined'],1)
  with sqlite3.connect(self.path) as c:
   row=c.execute('SELECT src_row,src_page,quarantine_reason,locator_status FROM ky_score_dist').fetchone()
   self.assertIsNone(row[0]);self.assertIsNone(row[1]);self.assertTrue(row[2]);self.assertEqual(row[3],'原件定位未闭合')
  self.assertEqual(m.ingest(self.path,self.man)['existing'],1)
 def test_missing_original_fingerprint_rejects_and_rolls_back(self):
  self.man['sources'][0]['archive_sha256']=''
  with self.assertRaises(ValueError):m.ingest(self.path,self.man)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM source').fetchone()[0],0)
 def test_invalid_summary_order_or_n_is_rejected(self):
  for fields in ({'min':400},{'n':2.5},{'n':0},{'list_type':'待定'}):
   r=copy.deepcopy(self.man);r['rows'][0].update(fields)
   with self.subTest(fields=fields),self.assertRaises(ValueError):m.ingest(self.path,r)
 def test_individual_data_is_rejected(self):
  self.man['rows'][0]['candidate_id']='not allowed'
  with self.assertRaises(ValueError):m.ingest(self.path,self.man)
 def test_existing_numeric_values_cannot_be_overwritten(self):
  m.ingest(self.path,self.man);self.man['rows'][0]['median']=325
  with self.assertRaisesRegex(ValueError,'冲突'):m.ingest(self.path,self.man)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT median FROM ky_score_dist').fetchone()[0],320)
if __name__=='__main__':unittest.main()
