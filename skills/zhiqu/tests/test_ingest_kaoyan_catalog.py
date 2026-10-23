import copy, importlib.util, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
P = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts/ingest_kaoyan_catalog.py'
sys.path.insert(0, str(P.parent))
spec = importlib.util.spec_from_file_location('ingest_kaoyan_catalog', P)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IngestKaoyanCatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.path = d / 'education.stage.sqlite'
        self.audit = d / 'audit-g1.sqlite'
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE institution(institution_id TEXT PRIMARY KEY,name TEXT)')
            c.execute("INSERT INTO institution VALUES('4135010384','厦门大学')")
            c.execute('CREATE TABLE source(' + ','.join(k + ' TEXT' + (' PRIMARY KEY' if k == 'source_id' else '') for k in mod.SOURCE) + ')')
            c.execute('CREATE TABLE ky_program_year(' + ','.join(k + (' INTEGER' if k in ('year', 'planned', 'src_page') else ' TEXT') + (' PRIMARY KEY' if k == 'record_id' else '') for k in mod.COLS) + ',tuimian INTEGER)')
            c.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            c.executemany('INSERT INTO storage_manifest VALUES(?,?)', [('generation', 'g1'), ('audit_file', self.audit.name)])
        with sqlite3.connect(self.audit) as a:
            a.execute('CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            a.execute("INSERT INTO storage_manifest VALUES('generation','g1')")
            a.execute('CREATE TABLE check_sample_misc(' + ','.join(k + ' TEXT' + (' PRIMARY KEY' if k == 'sample_id' else '') for k in mod.SAMPLE) + ')')
        src = {k: '' for k in mod.SOURCE}
        src.update(source_id='s1', grade='官方', publisher='厦门大学', title='目录', file_url='https://zs.xmu.edu.cn/a.xls', archive_sha256='a' * 64, archive_status='已核后删除（有指纹）')
        row = dict(record_id='p4cat-' + '0' * 32, institution_id='4135010384', school='厦门大学', college='011中国语言文学系', program_code='050101', program_name='文艺学', year=2026,
                   direction='01西方美学与文艺理论', subjects='①101思想政治理论', source_id='s1', src_table='Sheet1', src_row='2', planned=None,
                   value_status=json.dumps({'planned': {'status': '来源未提供', 'reason': '目录未列人数'}}))
        smp = {k: '' for k in mod.SAMPLE}
        smp.update(sample_id='x1', table_name='ky_program_year', row_key=row['record_id'], official_source_id='s1', verdict='一致')
        self.m = {'sources': [src], 'rows': [row], 'samples': [smp]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_insert_idempotent(self):
        r = mod.ingest(self.path, self.m)
        self.assertEqual((r['rows_inserted'], r['samples_inserted']), (1, 1))
        self.assertEqual(mod.ingest(self.path, self.m)['rows_existing'], 1)

    def test_identity_must_match(self):
        m = copy.deepcopy(self.m)
        m['rows'][0]['school'] = '厦门大学嘉庚学院'
        with self.assertRaisesRegex(ValueError, '身份'):
            mod.ingest(self.path, m)

    def test_planned_status_consistent(self):
        m = copy.deepcopy(self.m)
        m['rows'][0]['planned'] = 6
        with self.assertRaisesRegex(ValueError, 'planned'):
            mod.ingest(self.path, m)
        m['rows'][0]['value_status'] = json.dumps({'planned': {'status': '官方原值'}})
        self.assertEqual(mod.ingest(self.path, m)['rows_inserted'], 1)

    def test_bad_code_refused(self):
        m = copy.deepcopy(self.m)
        m['rows'][0]['program_code'] = '0501'
        with self.assertRaisesRegex(ValueError, '代码'):
            mod.ingest(self.path, m)

    def test_official_prefixed_code_preserved(self):
        m = copy.deepcopy(self.m)
        m['rows'][0]['program_code'] = 'S145300'
        self.assertEqual(mod.ingest(self.path, m)['rows_inserted'], 1)
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute('SELECT program_code FROM ky_program_year').fetchone()[0], 'S145300')

    def test_unknown_prefix_not_normalized(self):
        for code in ('X145300', 'S14530', 'S1453000'):
            m = copy.deepcopy(self.m)
            m['rows'][0]['program_code'] = code
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, '代码'):
                mod.ingest(self.path, m)

    def test_only_candidate(self):
        with self.assertRaises(ValueError):
            mod.ingest(self.path.with_name('education.sqlite'), self.m)


if __name__ == '__main__':
    unittest.main()
