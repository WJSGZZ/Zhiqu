"""数据库导出元数据可选传递，不改变旧 CSV 的计算输入。"""
import csv
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pool import input_provenance
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'


class PoolProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, rows):
        path = self.base / name
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def row(self, rank='20000', **extra):
        return dict(code='10285', name='苏州大学', major='计算机', rank=rank, plan='10', **extra)

    def pool(self, *years, extra=()):
        out = self.base / 'pool.csv'
        args = [sys.executable, str(SCRIPTS / 'pool.py'), '--key', 'major', '--out', str(out)]
        for year, path in years:
            args += ['--year', f'{year}={path}']
        result = subprocess.run(args + list(extra), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with out.open(encoding='utf-8') as f:
            return out, list(csv.DictReader(f))

    def test_optional_fields_absent_for_legacy_csv(self):
        path = self.write('old.csv', [self.row()])
        out, rows = self.pool((2025, path))
        self.assertNotIn('data_provenance', rows[0])
        self.assertNotIn('source_grade', rows[0])
        self.assertEqual(rows[0]['rank_2025'], '20000')

    def test_year_and_field_provenance_kept_without_upgrading(self):
        rank = dict(grade='第三方整理', display_grade='第三方整理·内部未核', source_id='vendor',
                    value_status='第三方整理未核', value=20000,
                    completeness={'status': 'partial', 'missing_rows': [5]}, scope={'major': '计算机'})
        score = dict(grade='官方', display_grade='官方', source_id='official', value_status='官方原值', value=640)
        old = self.write('old.csv', [self.row(data_provenance=json.dumps({'rank': rank}), source_grade='第三方整理·内部未核')])
        official_rank = dict(grade='官方', display_grade='官方', source_id='official-rank', value_status='官方原值', value=19000)
        new = self.write('new.csv', [self.row('19000', score='640', data_provenance=json.dumps({'rank': official_rank, 'score': score}), source_grade='官方')])
        _, rows = self.pool((2024, old), (2025, new))
        value = json.loads(rows[0]['data_provenance'])
        self.assertEqual(value, {'2024': {'rank': rank}, '2025': {'rank': official_rank, 'score': score}})
        self.assertIn(rows[0]['source_grade'], ['第三方整理', '第三方整理·内部未核'])
        self.assertEqual(value['2024']['rank']['display_grade'], '第三方整理·内部未核')

    def test_excluded_duplicate_year_loses_its_provenance(self):
        provenance = json.dumps({'rank': {'grade': '第三方整理', 'source_id': 'ambiguous', 'value': 20000}})
        old = self.write('old.csv', [self.row(data_provenance=provenance)] * 2)
        new = self.write('new.csv', [self.row('19000', source_grade='官方')])
        _, rows = self.pool((2024, old), (2025, new))
        self.assertEqual(rows[0]['rank_2024'], '')
        self.assertNotIn('data_provenance', rows[0])
        self.assertEqual(rows[0]['source_grade'], '官方')

    def test_missing_optional_plan_does_not_replace_real_source_grade(self):
        raw = self.row()
        raw['plan'] = ''
        raw['source_grade'] = '第三方整理·内部未核'
        raw['data_provenance'] = json.dumps({'rank': {'value': 20000, 'grade': '第三方整理',
            'display_grade': '第三方整理·内部未核', 'source_id': 'vendor'},
            'plan': {'value': None, 'grade': '未取得', 'value_status': {'status': '来源未提供'}}})
        _, rows = self.pool((2025, self.write('null-plan.csv', [raw])))
        self.assertEqual(rows[0]['source_grade'], '第三方整理·内部未核')

    def test_empty_rank_and_unknown_public_school_are_not_invented(self):
        path = self.write('empty.csv', [self.row('', data_provenance='{}'),
            dict(code='99999', name='未匹配测试学校', major='计算机', rank='1', plan='2', source_grade='官方')])
        _, rows = self.pool((2025, path), extra=('--public',))
        self.assertEqual(rows, [])

    def test_provenance_rejects_tampered_values_and_scope(self):
        def validate(fields, **extra):
            return input_provenance(self.row(data_provenance=json.dumps(fields), **extra), 2025)
        invalid = [
            {'score': {'value': 640}},
            {'rank': {'value': 19000}},
            {'rank': {'value': True}},
            {'rank': {'value': '20000'}},
            {'rank': {'value': None}},
            {'rank': {'value': 20000, 'scope': {'year': 2024}}},
            {'rank': {'value': 20000}, 'plan': {'value': 11}},
            {'rank': {'value': 20000}, 'score': {'value': 640}},
            {'rank': {'value': 20000}, 'score': {'value': float('nan')}},
        ]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate(fields)
        valid = {'rank': {'value': 20000, 'scope': {'year': 2025}}, 'plan': {'value': 10}, 'score': {'value': None}}
        self.assertEqual(validate(valid), valid)
        valid['score']['value'] = 640.5
        self.assertEqual(validate(valid, score='640.50'), valid)

    def test_pool_rejects_tampered_rank_before_writing_output(self):
        source = self.write('tampered.csv', [self.row(data_provenance=json.dumps({'rank': {'value': 19000}}))])
        output = self.base / 'rejected.csv'
        result = subprocess.run([sys.executable, str(SCRIPTS / 'pool.py'), '--year', f'2025={source}',
            '--key', 'major', '--out', str(output)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('与 CSV 数字不一致', result.stderr)
        self.assertFalse(output.exists())

    def test_optimize_list_preserves_provenance_and_legacy_keys(self):
        provenance = {'2025': {'rank': {'grade': '第三方整理', 'source_id': 'vendor', 'value': 20000}}}
        baseline = dict(id='x', name='苏州大学·计算机', rank_2025='20000', utility='80')
        def optimize(row, filename):
            path = self.write(filename + '.csv', [row])
            output = self.base / (filename + '.json')
            result = subprocess.run([sys.executable, str(SCRIPTS / 'optimize.py'), str(path),
                '--rank', '10000', '--u-fall', '-60', '--slots', '1', '--sims', '100', '--seed', '7', '--json', str(output)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(output.read_text())
        old = optimize(baseline, 'legacy')
        new = optimize(dict(baseline, data_provenance=json.dumps(provenance), source_grade='第三方整理'), 'metadata')
        self.assertEqual(new['list'][0]['data_provenance'], provenance)
        self.assertEqual(new['list'][0]['source_grade'], '第三方整理')
        del new['list'][0]['data_provenance']
        del new['list'][0]['source_grade']
        for key in ('csv', 'json'):
            new['params'][key] = old['params'][key]
        self.assertEqual(new, old)


if __name__ == '__main__':
    unittest.main()
