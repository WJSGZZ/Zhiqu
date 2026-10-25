import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'skills/zhiqu/scripts'))
from rank import Table, MissingDataError
spec=importlib.util.spec_from_file_location('gap_query_db',ROOT/'skills/zhiqu-shared/scripts/zhiqu_db.py')
db=importlib.util.module_from_spec(spec);spec.loader.exec_module(db)

class RankGapGuard(unittest.TestCase):
 def table(self,count=None):
  return Table.from_rows([dict(score=600,cum=100),dict(score=598,cum=130,count=count),dict(score=597,cum=140)])
 def test_missing_score_not_replaced_by_next_band(self):
  with self.assertRaisesRegex(MissingDataError,'599分行'):self.table().rank_of(599)
 def test_missing_rank_not_assigned_to_lower_band(self):
  with self.assertRaisesRegex(MissingDataError,'该段缺数据'):self.table().score_of(120)
 def test_no_invented_best_rank_after_gap(self):
  with self.assertRaises(MissingDataError):self.table().rank_of(598)
 def test_known_neighbor_interval_still_works(self):
  self.assertEqual(self.table().rank_of(597),(131,140));self.assertEqual(self.table().score_of(135),597)
 def test_explicit_count_only_allows_its_own_interval(self):
  t=self.table(5);self.assertEqual(t.rank_of(598),(126,130));self.assertEqual(t.score_of(128),598)
  with self.assertRaises(MissingDataError):t.score_of(120)
 def test_outside_range_not_clamped(self):
  for fn,v in [(self.table().rank_of,601),(self.table().rank_of,596),(self.table().score_of,141)]:
   with self.subTest(v=v),self.assertRaises(MissingDataError):fn(v)
 def test_count_only_does_not_sum_across_missing_score(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'t.csv';p.write_text('score,count\n600,10\n598,20\n')
   with self.assertRaisesRegex(MissingDataError,'599分行'):Table(p)
 def test_missing_head_does_not_invent_best_rank_or_top_score(self):
  t=Table.from_rows([dict(score=600,cum=100),dict(score=599,cum=110)],head_unknown=True)
  with self.assertRaises(MissingDataError):t.rank_of(600)
  with self.assertRaises(MissingDataError):t.score_of(50)
  self.assertEqual(t.score_of(105),599)
 def test_merged_top_count_only_proves_its_actual_tied_interval(self):
  t=Table.from_rows([dict(score=600,cum=100,count=5),dict(score=599,cum=110,count=10)])
  self.assertEqual(t.score_of(97),600)
  with self.assertRaises(MissingDataError):t.score_of(90)
 def test_absent_fractional_score_not_rounded_to_next_row(self):
  with self.assertRaises(MissingDataError):self.table().rank_of(597.5)
 def test_explicit_aggregate_band_never_becomes_an_exact_score(self):
  t=Table.from_rows([dict(score=683,cum=126,count=126,score_operator='>='),dict(score=682,cum=144,count=18)])
  with self.assertRaisesRegex(MissingDataError,'合并分数档'):t.rank_of(683)
  with self.assertRaisesRegex(MissingDataError,'合并分数档'):t.score_of(100)
  self.assertEqual(t.rank_of(682),(127,144));self.assertEqual(t.score_of(130),682)
 def test_csv_aggregate_operator_has_the_same_guard(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'t.csv';p.write_text('score,count,cum,score_operator\n658,109,109,>=\n657,16,125,=\n')
   with self.assertRaisesRegex(MissingDataError,'合并分数档'):Table(p).score_of(50)
   with self.assertRaisesRegex(MissingDataError,'合并分数档'):Table(p).rank_of(658)
   self.assertEqual(Table(p).rank_of(657),(110,125))
 def test_fractional_scale_not_guessed_from_two_observations(self):
  t=Table.from_rows([dict(score=100,cum=10),dict(score=99.5,cum=20)])
  with self.assertRaises(MissingDataError):t.score_of(15)
  with self.assertRaises(MissingDataError):t.rank_of(99.5)
  known=Table.from_rows([dict(score=100,cum=10),dict(score=99.5,cum=20,count=10)])
  self.assertEqual(known.score_of(15),99.5)
 def test_precomputed_interpolated_rows_are_not_official_points(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d)/'t.csv';p.write_text('score,cum,source\n600,100,官方\n599,110,插值\n598,120,官方\n')
   t=Table(p)
   with self.assertRaises(MissingDataError):t.rank_of(599)
   with self.assertRaises(MissingDataError):t.score_of(105)

class DatabaseGapGuard(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.p=Path(self.temp.name)/'test.sqlite'
  with sqlite3.connect(self.p)as c:
   c.executescript('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT);CREATE TABLE gk_official_yfyd(province TEXT,year INTEGER,subject TEXT,score INTEGER,cum INTEGER,source_id TEXT);')
   c.execute("INSERT INTO source VALUES('s','官方','考试院','原分段表','https://a.gov.cn/a','')")
   c.executemany('INSERT INTO gk_official_yfyd VALUES(?,?,?,?,?,?)',[('甲省',2025,'物理',s,n,'s')for s,n in [(600,100),(598,130),(597,140)]])
   self.coverage=dict(source_id='s',table_name='gk_official_yfyd',status='partial',original_rows=4,accepted_rows=3,missing_rows=[dict(page=1,table=1,row=3,reason='原图水印，两读未一致')],missing_scope='其他页未核')
   c.execute('INSERT INTO meta VALUES(?,?)',('gk_source_coverage:s:gk_official_yfyd:one',json.dumps(self.coverage)))
 def tearDown(self):self.temp.cleanup()
 def test_database_score_gap_returns_reason_and_real_missing_row(self):
  r=db.query_yfyd('甲省',2025,'物理',score=599,db=self.p);self.assertEqual(r['status'],'missing_data');self.assertEqual(r['gap']['missing_scores'],[599]);self.assertEqual(r['completeness'][0]['missing_rows'][0]['row'],3);self.assertIn('原表不完整',db.render_text(r));self.assertIn('页1/表1/行3',db.render_text(r));self.assertNotIn('rank',r)
 def test_database_rank_gap_does_not_invent_score(self):
  r=db.query_yfyd('甲省',2025,'物理',rank=120,db=self.p);self.assertEqual(r['status'],'missing_data');self.assertNotIn('score',r)
 def context_count(self,count,kind,status):
  with sqlite3.connect(self.p)as c:
   c.execute('CREATE TABLE IF NOT EXISTS gk_yfyd_context(province TEXT,year INTEGER,subject TEXT,score INTEGER,segment_n INTEGER,count_kind TEXT,value_status TEXT,source_id TEXT)')
   c.execute('DELETE FROM gk_yfyd_context')
   c.execute('INSERT INTO gk_yfyd_context VALUES(?,?,?,?,?,?,?,?)',('甲省',2025,'物理',598,count,kind,json.dumps({'segment_n':{'status':status}}),'s'))
 def test_cumulative_context_count_does_not_close_gap(self):
  self.context_count(130,'累计人数（原表明示）','官方原值')
  r=db.query_yfyd('甲省',2025,'物理',rank=120,db=self.p);self.assertEqual(r['status'],'missing_data');self.assertNotIn('score',r)
 def test_database_aggregate_context_is_not_a_single_score(self):
  self.context_count(100,'本分数人数','官方原值')
  with sqlite3.connect(self.p)as c:
   c.execute('ALTER TABLE gk_yfyd_context ADD COLUMN score_operator TEXT')
   c.execute("UPDATE gk_yfyd_context SET score=600,score_operator='>='")
  for kwargs in [dict(rank=50),dict(score=600)]:
   r=db.query_yfyd('甲省',2025,'物理',db=self.p,**kwargs);self.assertEqual(r['status'],'missing_data');self.assertIn('合并分数档',r['message'])
 def test_unspecified_or_derived_context_count_does_not_close_gap(self):
  for kind,status in [('原表人数','官方原值'),('分段表累计人数','官方原值'),('本分数人数','推算')]:
   with self.subTest(kind=kind,status=status):
    self.context_count(40,kind,status)
    r=db.query_yfyd('甲省',2025,'物理',rank=120,db=self.p);self.assertEqual(r['status'],'missing_data');self.assertNotIn('score',r)
 def test_explicit_original_segment_count_proves_its_own_interval(self):
  self.context_count(30,'本分数人数','官方原值')
  r=db.query_yfyd('甲省',2025,'物理',rank=120,db=self.p);self.assertEqual(r['status'],'ok');self.assertEqual(r['score'],598)
 def test_latest_coverage_declaration_supersedes_older_one(self):
  with sqlite3.connect(self.p)as c:
   c.execute("INSERT INTO gk_official_yfyd VALUES('甲省',2025,'物理',599,115,'s')")
   new=dict(self.coverage,status='obtained',accepted_rows=4,missing_rows=[])
   c.execute('INSERT INTO meta VALUES(?,?)',('gk_source_coverage:s:gk_official_yfyd:two',json.dumps(new)))
  r=db.query_yfyd('甲省',2025,'物理',score=599,db=self.p);self.assertEqual(r['status'],'ok');self.assertEqual(r['rank'],115);self.assertEqual(r['completeness'][0]['missing_rows'],[])
 def test_cutoff_completeness_text_gives_positions_and_reasons(self):
  text=db._completeness_text(dict(self.coverage,table_name='gk_official_cutoff'),True);self.assertIn('页1/表1/行3',text);self.assertIn('两读未一致',text)

if __name__=='__main__':unittest.main()
