"""填报单位不匹配要说清，不能把专业录取分冒充专业组线。"""
import contextlib
import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'))
import gaokao_export as ex
import zhiqu_db as db
from test_gaokao_db_export import record


class GrainDiagnosticsTests(unittest.TestCase):
    def export(self, records, **kwargs):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        return ex.export_records(records,'河南','物理',[2025],out=tmp.name,**kwargs)

    def test_group_code_on_major_does_not_make_group_cutoff(self):
        r=record(group='105')
        result=self.export([r],key='group')
        self.assertEqual(result['exported_rows'],{'2025':0})
        self.assertEqual(result['grain_mismatches'],[{'year':2025,'requested':'group','actual':'major','rows':1}])
        self.assertEqual(result['rejected'][0]['grain_mismatch'],{'requested':'group','actual':'major'})
        with open(result['files']['2025']) as f:self.assertEqual(list(csv.DictReader(f)),[])

    def test_scope_filters_and_prior_rejections_not_counted_as_grain(self):
        wrong_year=record();wrong_year['year']=2024
        wrong_subject=record();wrong_subject['subject']='历史'
        wrong_batch=record(batch='专科批')
        wrong_school=record();wrong_school['name']='乙大学';wrong_school['code']='2002';wrong_school['institution_id']='1000000002'
        conflict=record();conflict['scope_conflicts']=[{'field':'batch'}]
        result=self.export([record(),wrong_year,wrong_subject,wrong_batch,wrong_school,conflict],key='group',batch='本科批',schools={'甲大学'})
        self.assertEqual(result['grain_mismatches'][0]['rows'],1)
        self.assertEqual(len(result['grain_mismatches']),1)

    def test_compatible_grain_and_reverse_direction(self):
        self.assertEqual(self.export([record()],key='major')['grain_mismatches'],[])
        r=record(group='105',major='');r['grain']='group';r['major_code']=''
        self.assertEqual(self.export([r],key='major')['grain_mismatches'][0]['actual'],'group')

    def test_counts_are_records_not_distinct_schools_and_unknown_is_explicit(self):
        r=record();unknown=record();unknown.pop('grain')
        counts=self.export([r,r,unknown],key='group')['grain_mismatches']
        self.assertEqual({x['actual']:x['rows'] for x in counts},{'major':2,'unknown':1})

    def test_legacy_major_column_requires_explicit_semantics(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;self.addCleanup(c.close)
        c.executescript("""
ATTACH DATABASE ':memory:' AS data;
CREATE TABLE data.source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT);
INSERT INTO data.source VALUES('o','官方','考试院','原表','https://example.gov.cn');
CREATE TABLE data.gk_official_cutoff(province TEXT,year INT,subject TEXT,code TEXT,name TEXT,grp TEXT,major_code TEXT,major TEXT,score INT,rank INT,source_id TEXT,src TEXT,value_status TEXT);
INSERT INTO data.gk_official_cutoff VALUES('河南',2025,'物理','1001','甲大学','105','','计算机科学与技术',600,10000,'o','row:4','{}');
CREATE TABLE data.official_cutoff_scope(source_id TEXT,public_record TEXT,scope_json TEXT);
INSERT INTO data.official_cutoff_scope VALUES('o','row:4','{"batch":"本科批"}');
""")
        tables={'source','gk_official_cutoff','official_cutoff_scope'}
        def collect():return ex.collect(c,tables,'河南','物理',[2025])[0]
        row=collect();self.assertEqual(row['grain'],'unknown')
        self.assertEqual(row['major'],'计算机科学与技术');self.assertEqual(row['requirement'],'')
        for key in ('group','major'):
            self.assertEqual(self.export([row],key=key)['exported_rows'],{'2025':0})
        # 化学既是专业名也是科目，不能仅凭字面决定粒度。
        c.execute("UPDATE data.gk_official_cutoff SET major='化学'")
        self.assertEqual(collect()['grain'],'unknown')
        c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'batch':'本科批','major_name':'化学','requirement':'化学'}),))
        self.assertEqual(collect()['grain'],'major')
        # 原列已明确为选科说明时，保留合法旧格式兼容，不猜新字段。
        c.execute('UPDATE data.official_cutoff_scope SET scope_json=?',(json.dumps({'batch':'本科批','requirement':'化学'}),))
        row=collect();self.assertEqual(row['grain'],'group')
        self.assertEqual(row['major'],'');self.assertEqual(row['requirement'],'化学')
        self.assertEqual(self.export([row],key='group')['exported_rows'],{'2025':1})
        # 同一化学专业有明确专业码时，选科相同也不能降为组线。
        c.execute("UPDATE data.gk_official_cutoff SET major_code='070301'")
        self.assertEqual(collect()['grain'],'major')

    def test_cli_keeps_yfyd_separate_and_reports_real_grain_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=root/'db.sqlite'
            with sqlite3.connect(fixture) as c:
                c.executescript('''
CREATE TABLE source(source_id TEXT PRIMARY KEY,grade TEXT,publisher TEXT,title TEXT,landing_url TEXT,file_url TEXT);
CREATE TABLE gk_official_yfyd(province TEXT,year INT,subject TEXT,score INT,cum INT,src TEXT,source_id TEXT,src_row TEXT,value_status TEXT);
CREATE TABLE gk_official_cutoff(province TEXT,year INT,subject TEXT,code TEXT,name TEXT,grp TEXT,major_code TEXT,major TEXT,plan INT,score INT,rank INT,source_id TEXT,institution_id TEXT,plan_type TEXT,src TEXT,src_row TEXT,value_status TEXT);
CREATE TABLE official_cutoff_scope(source_id TEXT,public_record TEXT,scope_json TEXT);
INSERT INTO source VALUES('o','官方','考试院','原表','https://example.gov.cn','');
INSERT INTO gk_official_yfyd VALUES('河南',2025,'物理',600,10000,'sheet:4','o','4','{}');
INSERT INTO gk_official_cutoff VALUES('河南',2025,'物理','1001','甲大学','105','080901','计算机科学与技术',10,600,10000,'o','1000000001','普通','original:4','4','{}');
INSERT INTO official_cutoff_scope VALUES('o','original:4','{"batch":"本科批"}');
''')
            before=fixture.read_bytes();out=io.StringIO()
            with contextlib.redirect_stdout(out):
                status=db.main(['export-gaokao','河南','物理','--years','2025','--key','group','--batch','本科批','--out',str(root/'out'),'--db',str(fixture)])
            result=json.loads((root/'out/export-metadata.json').read_text())
            self.assertEqual(status,0)  # 分段表可用，候选状态独立报缺。
            self.assertEqual(result['candidate_status'],'missing_data')
            self.assertEqual(result['yfyd_exported_rows'],{'2025':1})
            self.assertIn('院校专业组输入不接收专业记录1条',out.getvalue())
            self.assertIn('不要为凑候选更换填报单位',out.getvalue())
            self.assertEqual(fixture.read_bytes(),before)

if __name__=='__main__':unittest.main()
