import copy, importlib.util, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
P = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts/ingest_kaoyan_national.py'
sys.path.insert(0, str(P.parent))
spec = importlib.util.spec_from_file_location('ingest_kaoyan_national', P)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IngestKaoyanNationalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.path = d / 'education.stage.sqlite'
        self.audit = d / 'audit-test-generation.sqlite'
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE source(' + ','.join(k + ' TEXT' + (' PRIMARY KEY' if k == 'source_id' else '') for k in mod.SOURCE) + ')')
            c.execute('CREATE TABLE ky_national_line(record_id TEXT PRIMARY KEY,year INTEGER,category TEXT,program_name TEXT,degree_type TEXT,region TEXT,scope TEXT,scope_raw TEXT,source_id TEXT,src_page INTEGER,src_table TEXT,src_row TEXT,locator_method TEXT,locator_status TEXT,line_total REAL,single_100 REAL,single_over_100 REAL,value_status TEXT NOT NULL DEFAULT \'{}\',extra_json TEXT,school TEXT)')
            c.execute('CREATE TABLE old_table(x)')
            c.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            c.executemany('INSERT INTO storage_manifest VALUES(?,?)', [('generation', 'g1'), ('audit_file', self.audit.name)])
        with sqlite3.connect(self.audit) as a:
            a.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            a.execute("INSERT INTO storage_manifest VALUES('generation','g1')")
            a.execute('CREATE TABLE check_sample_misc(' + ','.join(k + ' TEXT' + (' PRIMARY KEY' if k == 'sample_id' else '') for k in mod.SAMPLE) + ')')
        src = {k: '' for k in mod.SOURCE}
        src.update(source_id='s1', grade='官方', publisher='教育部', title='2023国家线', file_url='http://www.moe.gov.cn/a.pdf', archive_sha256='a' * 64, archive_status='已核后删除（有指纹）')
        ok = {'status': '官方原值'}
        row = dict(record_id='0' * 24, year=2023, category='哲学', program_name='哲学', degree_type='学术', region='A', source_id='s1', src_page=1, src_table='表1', src_row='3',
                   line_total=323, single_100=45, single_over_100=68, value_status=json.dumps({'line_total': ok, 'single_100': ok, 'single_over_100': ok}))
        sample = dict(sample_id='x1', domain='考研', table_name='ky_national_line', row_key='0' * 24, field='总分/单科', db_value='[323,45,68]', official_value='[323,45,68]',
                      official_source_id='s1', verdict='一致', checked_on='2026-10-22', reason='双路重读', excerpt='哲学 323 45 68', locator='第1页表1第3行', reviewer='t')
        self.m = {'sources': [src], 'rows': [row], 'samples': [sample]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_insert_idempotent(self):
        r = mod.ingest(self.path, self.m)
        self.assertEqual((r['rows_inserted'], r['samples_inserted'], r['sources_inserted']), (1, 1, 1))
        r = mod.ingest(self.path, self.m)
        self.assertEqual((r['rows_inserted'], r['rows_existing'], r['samples_inserted']), (0, 1, 0))

    def test_conflicting_value_refused(self):
        mod.ingest(self.path, self.m)
        m = copy.deepcopy(self.m)
        m['rows'][0]['line_total'] = 324
        with self.assertRaisesRegex(ValueError, '冲突'):
            mod.ingest(self.path, m)

    def test_null_requires_reason(self):
        m = copy.deepcopy(self.m)
        m['rows'][0]['single_100'] = None
        with self.assertRaisesRegex(ValueError, '空值'):
            mod.ingest(self.path, m)
        st = json.loads(m['rows'][0]['value_status'])
        st['single_100'] = {'status': '来源未提供', 'reason': '原文仅给总分'}
        m['rows'][0]['value_status'] = json.dumps(st)
        self.assertEqual(mod.ingest(self.path, m)['rows_inserted'], 1)

    def test_sample_must_match_row_and_source(self):
        m = copy.deepcopy(self.m)
        m['samples'][0]['official_source_id'] = 'other'
        with self.assertRaisesRegex(ValueError, '抽核'):
            mod.ingest(self.path, m)
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ky_national_line').fetchone()[0], 0)

    def test_only_candidate_and_generation(self):
        with self.assertRaises(ValueError):
            mod.ingest(self.path.with_name('education.sqlite'), self.m)
        with sqlite3.connect(self.audit) as a:
            a.execute("UPDATE storage_manifest SET value='g2'")
        with self.assertRaisesRegex(ValueError, '代号'):
            mod.ingest(self.path, self.m)

    def test_unknown_region_refused(self):
        m = copy.deepcopy(self.m)
        m['rows'][0]['region'] = 'C'
        with self.assertRaisesRegex(ValueError, '分区'):
            mod.ingest(self.path, m)


if __name__ == '__main__':
    unittest.main()
