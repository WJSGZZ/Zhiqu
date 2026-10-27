"""导出缺口提示原科类，绝不据此换标签、借年份或拼竞争序列。"""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'))
import gaokao_export as ex
import zhiqu_db as db


class SubjectOptionsTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute("ATTACH DATABASE ':memory:' AS data")
        self.c.executescript('''
CREATE TABLE data.gk_official_cutoff(province TEXT,year INT,subject TEXT);
CREATE TABLE data.gk_official_yfyd(province TEXT,year INT,subject TEXT);
CREATE TABLE data.gk_v_purchased(province TEXT,year INT,subject TEXT,dataset_type TEXT);
CREATE TABLE data.gk_v_usable(province TEXT,year INT,subject_type TEXT);
CREATE TABLE data.gk_official_plan(province TEXT,year INT,subject TEXT);
CREATE TABLE data.gk_batch_line(province TEXT,year INT,subject TEXT);
INSERT INTO data.gk_official_cutoff VALUES('贵州',2025,'首选科目物理'),('贵州',2025,'首选科目物理'),('贵州',2024,'旧理科'),('湖南',2025,'外省标签');
INSERT INTO data.gk_official_yfyd VALUES('贵州',2025,'首选科目物理'),('贵州',2025,'物理'),('贵州',2025,NULL),('贵州',2025,' ');
INSERT INTO data.gk_v_purchased VALUES('贵州',2025,'历史组合','投档线'),('贵州',2025,'不得提示的非录取数据','招生计划');
INSERT INTO data.gk_v_usable VALUES('贵州',2025,'物理、化学');
INSERT INTO data.gk_official_plan VALUES('贵州',2025,'首选科目历史');
INSERT INTO data.gk_batch_line VALUES('贵州',2025,'综合');
''')
        self.tables = {r[0] for r in self.c.execute("SELECT name FROM data.sqlite_master WHERE type='table'")}

    def test_exact_raw_labels_and_layers_survive_without_alias_join(self):
        result = ex.subject_options(self.c,self.tables,'贵州',[2025],requested='物理')
        labels = {r['subject']: r['layers'] for r in result}
        self.assertEqual(labels['首选科目物理'], ['一分一段原表','投档线原表'])
        self.assertIn('物理、化学', labels)
        self.assertNotIn('物理', labels)
        self.assertEqual(labels['历史组合'], ['外购投档/专业录取分'])
        self.assertNotIn('不得提示的非录取数据', labels)
        self.assertEqual(labels['综合'], ['控制线原表'])
        self.assertEqual(labels['首选科目历史'], ['招生计划原表'])
        self.assertEqual({r['subject'] for r in result[:2]}, {'物理、化学','首选科目物理'})

    def test_province_year_boundaries_and_empty_inputs(self):
        result = ex.subject_options(self.c,self.tables,'贵州',[2025,2025],requested='物理')
        self.assertTrue(all(r['year']==2025 for r in result))
        self.assertNotIn('旧理科', str(result))
        self.assertNotIn('外省标签', str(result))
        self.assertEqual(ex.subject_options(self.c,self.tables,'贵州',[],requested='物理'), [])
        self.assertEqual(ex.subject_options(self.c,set(),'贵州',[2025],requested='物理'), [])
        self.assertEqual(ex.subject_options(self.c,self.tables,'不存在的省份',[2025],requested='物理'), [])

    def test_raw_label_spaces_are_preserved_not_silently_normalized(self):
        self.c.execute("INSERT INTO data.gk_official_yfyd VALUES('贵州',2025,' 物理 ')")
        result = ex.subject_options(self.c,self.tables,'贵州',[2025],requested='物理')
        self.assertIn(' 物理 ', [r['subject'] for r in result])

    def test_cli_missing_label_lists_choices_without_using_their_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=root/'db.sqlite'
            with sqlite3.connect(fixture) as c:
                c.executescript('''
CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT);
CREATE TABLE gk_official_yfyd(province TEXT,year INT,subject TEXT,score INT,cum INT,src TEXT,source_id TEXT,src_row TEXT,value_status TEXT);
INSERT INTO source VALUES('o','官方','考试院','原表','https://example.gov.cn','');
INSERT INTO gk_official_yfyd VALUES('贵州',2025,'首选科目物理',600,10000,'sheet:4','o','4','{}');
''')
            before=fixture.read_bytes();stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status=db.main(['export-gaokao','贵州','物理','--years','2025','--out',str(root/'out'),'--db',str(fixture)])
            self.assertEqual(status,2)
            self.assertIn('首选科目物理',stdout.getvalue())
            self.assertIn('未自动换科类',stdout.getvalue())
            result=json.loads((root/'out/export-metadata.json').read_text())
            self.assertEqual(result['subject_options'],[{'year':2025,'subject':'首选科目物理','layers':['一分一段原表']}])
            self.assertEqual(result['exported_rows'],{'2025':0})
            self.assertEqual(result['yfyd_exported_rows'],{'2025':0})
            self.assertEqual(fixture.read_bytes(),before)

    def test_multiple_years_only_gap_year_has_options_and_terminal_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=root/'db.sqlite'
            with sqlite3.connect(fixture) as c:
                c.executescript('''
CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT);
CREATE TABLE gk_official_yfyd(province TEXT,year INT,subject TEXT,score INT,cum INT,src TEXT,source_id TEXT,src_row TEXT,value_status TEXT);
CREATE TABLE gk_official_cutoff(province TEXT,year INT,subject TEXT,code TEXT,name TEXT,grp TEXT,major_code TEXT,major TEXT,plan INT,score INT,rank INT,source_id TEXT,institution_id TEXT,plan_type TEXT,src TEXT,src_row TEXT,value_status TEXT);
CREATE TABLE official_cutoff_scope(source_id TEXT,public_record TEXT,scope_json TEXT);
INSERT INTO source VALUES('o','官方','考试院','原表','https://example.gov.cn','');
INSERT INTO gk_official_yfyd VALUES('贵州',2024,'物理',600,10000,'sheet:4','o','4','{}');
INSERT INTO gk_official_yfyd VALUES('贵州',2024,'不应提示的已齐年份标签',600,10000,'sheet:5','o','5','{}');
INSERT INTO gk_official_cutoff VALUES('贵州',2024,'物理','1001','甲大学','','080901','计算机科学与技术',10,600,10000,'o','1000000001','普通','original:4','4','{}');
INSERT INTO official_cutoff_scope VALUES('o','original:4','{"batch":"本科批"}');
''')
                for n in range(10):
                    c.execute('INSERT INTO gk_official_yfyd VALUES(?,?,?,?,?,?,?,?,?)',('贵州',2025,f'原标签{n}',600,10000,'sheet:4','o','4','{}'))
            before=fixture.read_bytes();stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status=db.main(['export-gaokao','贵州','物理','--years','2024','2025','--key','major','--out',str(root/'out'),'--db',str(fixture)])
            self.assertEqual(status,0)  # 2024已导出，2025缺口仍保留为partial。
            result=json.loads((root/'out/export-metadata.json').read_text())
            self.assertEqual(result['status'],'partial')
            self.assertEqual(result['exported_rows'],{'2024':1,'2025':0})
            self.assertEqual(result['yfyd_exported_rows'],{'2024':1,'2025':0})
            self.assertEqual(len(result['subject_options']),10)
            self.assertTrue(all(r['year']==2025 for r in result['subject_options']))
            self.assertIn('原标签5',stdout.getvalue())
            self.assertNotIn('原标签6',stdout.getvalue())
            self.assertIn('其余标签见导出说明',stdout.getvalue())
            self.assertNotIn('不应提示的已齐年份标签',stdout.getvalue())
            self.assertEqual(fixture.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
