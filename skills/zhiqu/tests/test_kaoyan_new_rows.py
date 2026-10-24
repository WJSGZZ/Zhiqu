"""Offline read-back checks on disposable SQLite files, never real records."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'
sys.path.insert(0, str(SCRIPTS))
from ingest_kaoyan_lines import RAW, SOURCE, DDL, SCOPE_DDL, dump
from kaoyan_new_rows import verify_manifest_rows


def quote(name):
    return '"' + name.replace('"', '""') + '"'


class NewRowsReadback(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'candidate.sqlite'
        self.source = dict.fromkeys(SOURCE, '')
        self.source.update(source_id='synthetic-source', grade='官方', publisher='合成大学研究生院',
                           title='合成大学2026年硕士招生资料',
                           landing_url='https://fixture.edu.cn/2026/notice.html',
                           file_url='https://fixture.edu.cn/2026/table.pdf',
                           published='2025-09-01', retrieved='2026-10-24', method='synthetic-dual',
                           archive_sha256='a' * 64, archive_status='已核后删除（有指纹）',
                           license='未注明')
        with sqlite3.connect(self.database) as c:
            c.execute('CREATE TABLE source(' + ','.join(quote(k) +
                      (' TEXT PRIMARY KEY' if k == 'source_id' else ' TEXT') for k in SOURCE) + ')')
            numeric = {'total', 'politics', 'english', 'math', 'major1', 'major2'}
            columns = [(k, 'INTEGER' if k == 'year' else 'REAL' if k in numeric else 'TEXT') for k in RAW]
            columns += [('record_id', 'TEXT PRIMARY KEY'), ('source_id', 'TEXT')]
            self.create(c, 'ky_retest_line', columns)
            self.create(c, 'ky_retest_line_source', [('record_id', 'TEXT'), ('source_id', 'TEXT'), ('locator_json', 'TEXT')])
            c.execute(SCOPE_DDL)
            c.execute(DDL)
            self.create_catalog(c)
            self.create(c, 'ky_score_dist', [('record_id', 'TEXT PRIMARY KEY'), ('institution_id', 'TEXT'),
                ('source_id', 'TEXT'), ('school', 'TEXT'), ('program_code', 'TEXT'), ('year', 'INTEGER'),
                ('n', 'INTEGER'), ('min', 'REAL'), ('median', 'REAL'), ('max', 'REAL'),
                ('list_type', 'TEXT'), ('src_page', 'INTEGER'), ('src_table', 'TEXT'), ('src_row', 'TEXT')])
            self.insert(c, 'source', self.source)

    @staticmethod
    def create(c, table, columns):
        c.execute('CREATE TABLE ' + quote(table) + '(' + ','.join(quote(k) + ' ' + t for k, t in columns) + ')')

    def create_catalog(self, c, planned_type='INTEGER'):
        self.create(c, 'ky_program_year', [('record_id', 'TEXT PRIMARY KEY'), ('institution_id', 'TEXT'),
            ('source_id', 'TEXT'), ('program_code', 'TEXT'), ('year', 'INTEGER'), ('planned', planned_type),
            ('tuimian', 'INTEGER'), ('src_table', 'TEXT'), ('src_row', 'TEXT')])

    @staticmethod
    def insert(c, table, row):
        c.execute('INSERT INTO ' + quote(table) + '(' + ','.join(quote(k) for k in row) + ') VALUES(' +
                  ','.join('?' for _ in row) + ')', list(row.values()))

    def change(self, sql, values=()):
        with sqlite3.connect(self.database) as c:
            c.execute(sql, values)

    def manifest(self, row):
        return {'sources': [deepcopy(self.source)], 'rows': [row]}

    def catalog(self, planned=41):
        row = dict(record_id='catalog-r1', institution_id='4100000001', source_id=self.source['source_id'],
                   program_code='085404', year=2026, planned=planned, tuimian=None, src_table=1, src_row=7)
        with sqlite3.connect(self.database) as c:
            self.insert(c, 'ky_program_year', row)
        return self.manifest(row)

    def stats(self, n=3):
        low, med, high = (301, 301, 301) if n == 1 else (301, 310, 319) if n == 2 else (301, 317, 335)
        row = dict(record_id='stats-r1', institution_id='4100000001', source_id=self.source['source_id'],
                   school='合成大学', program_code='085404', year=2026, n=n, min=low, median=med, max=high,
                   list_type='拟录取', src_page=2, src_table='匿名分组', src_row='p2:r3-r5')
        with sqlite3.connect(self.database) as c:
            self.insert(c, 'ky_score_dist', row)
        return self.manifest(row)

    def lines(self, partial_context=False, normalized_scope=False):
        raw = dict.fromkeys(RAW)
        raw.update(year=2026, school='合成大学', institution_id='4100000001', college='计算机学院',
                   program_code='085404', program_name='计算机技术', degree_type='专业学位', study_mode='全日制',
                   line_scope='原专业资格要求', total=312, politics=45, english=40,
                   note='原范围说明', read_method='文字双读', source_url=self.source['file_url'],
                   src_locator='pdf:p2:t1:r3')
        context = {'direction': '不分方向'} if partial_context else dict(
            direction='不分方向', joint_program='', admission_route='一志愿', scope_raw='原专业资格要求')
        row = dict(record_id='line-r1', institution_id=raw['institution_id'], source_id=self.source['source_id'],
                   row=raw, src_page=2, src_table='t1', src_row='3', scope_context=context,
                   components={'single_gt100': 60}, review={'method': 'synthetic-dual'})
        business = dict(raw, record_id=row['record_id'], source_id=row['source_id'],
                        published_date=self.source['published'], retrieved_date=self.source['retrieved'])
        if normalized_scope:
            row['scope_kind'] = '学院专业资格线'
            business.update(line_scope=row['scope_kind'], note=raw['note'] + '；原scope=' + raw['line_scope'])
        compact = {k: row[k] for k in ['src_page', 'src_table', 'src_row']}
        compact.update(evidence_record_id=row['record_id'], audit_table='ky_line_original_evidence')
        with sqlite3.connect(self.database) as c:
            self.insert(c, 'ky_retest_line', business)
            self.insert(c, 'ky_retest_line_source', dict(record_id=row['record_id'], source_id=row['source_id'],
                                                       locator_json=dump(compact)))
            self.insert(c, 'ky_line_scope_context', dict(record_id=row['record_id'], source_id=row['source_id'],
                **{k: context.get(k, '') for k in ['direction', 'joint_program', 'admission_route', 'scope_raw']}))
            self.insert(c, 'ky_line_component', dict(record_id=row['record_id'], component='single_gt100', value=60,
                source_id=row['source_id'], src_locator=dump(compact),
                value_status=dump({'value': {'status': '官方原值', 'method': 'synthetic-dual'}})))
        return self.manifest(row)

    def verify(self, layer, manifest, deadline=None):
        return verify_manifest_rows(self.database, [(layer, manifest)], deadline=deadline)

    def test_catalog_real_column_affinities_are_applied_before_exact_comparison(self):
        manifest = self.catalog(planned=41.0)
        self.assertEqual(self.verify('catalog', manifest)['rows'], 1)
        with sqlite3.connect(self.database) as c:
            self.assertEqual(c.execute('SELECT planned,typeof(planned),src_table,typeof(src_table) FROM ky_program_year').fetchone(),
                             (41, 'integer', '1', 'text'))

    def test_number_mismatch_is_rejected(self):
        manifest = self.catalog()
        self.change('UPDATE ky_program_year SET planned=42')
        with self.assertRaises(ValueError): self.verify('catalog', manifest)

    def test_equal_python_numbers_with_different_sqlite_types_are_rejected(self):
        with sqlite3.connect(self.database) as c:
            c.execute('DROP TABLE ky_program_year'); self.create_catalog(c, planned_type='BLOB')
        manifest = self.catalog()
        self.change('UPDATE ky_program_year SET planned=?', (41.0,))
        with self.assertRaises(ValueError): self.verify('catalog', manifest)

    def test_null_is_not_zero(self):
        manifest = self.catalog()
        self.change('UPDATE ky_program_year SET tuimian=0')
        with self.assertRaises(ValueError): self.verify('catalog', manifest)

    def test_program_leading_zero_is_not_discarded(self):
        manifest = self.catalog()
        self.change("UPDATE ky_program_year SET program_code='85404'")
        with self.assertRaises(ValueError): self.verify('catalog', manifest)

    def test_source_fingerprint_and_publisher_are_exact(self):
        manifest = self.catalog()
        for field, value in [('archive_sha256', 'b' * 64), ('publisher', '合成不同发布单位'), ('grade', '第三方整理')]:
            with self.subTest(field=field):
                self.change('UPDATE source SET ' + quote(field) + '=?', (value,))
                with self.assertRaises(ValueError): self.verify('catalog', manifest)
                self.change('UPDATE source SET ' + quote(field) + '=?', (self.source[field],))

    def test_row_source_and_identity_are_exact(self):
        manifest = self.catalog()
        self.change("UPDATE ky_program_year SET source_id='other-source'")
        with self.assertRaises(ValueError): self.verify('catalog', manifest)
        self.change('UPDATE ky_program_year SET source_id=?,record_id=?', (self.source['source_id'], 'other-record'))
        with self.assertRaises(ValueError): self.verify('catalog', manifest)

    def test_line_numbers_dates_context_component_and_locator_pass(self):
        manifest = self.lines(normalized_scope=True)
        result = self.verify('lines', manifest)
        self.assertEqual((result['sources'], result['rows'], result['components']), (1, 1, 1))

    def test_line_date_must_come_from_source(self):
        manifest = self.lines()
        manifest['rows'][0]['row']['published_date'] = '1999-01-01'
        self.assertTrue(self.verify('lines', manifest)['ok'])
        self.change("UPDATE ky_retest_line SET published_date='1999-01-01'")
        with self.assertRaises(ValueError): self.verify('lines', manifest)

    def test_line_parent_locator_page_row_table_are_exact(self):
        manifest = self.lines()
        for key, wrong in [('src_page', 3), ('src_table', 't2'), ('src_row', '4')]:
            with self.subTest(key=key):
                locator = {k: manifest['rows'][0][k] for k in ['src_page', 'src_table', 'src_row']}
                locator[key] = wrong
                self.change('UPDATE ky_retest_line_source SET locator_json=?', (dump(locator),))
                with self.assertRaises(ValueError): self.verify('lines', manifest)

    def test_line_missing_or_wrong_source_association_is_rejected(self):
        manifest = self.lines()
        self.change("UPDATE ky_retest_line_source SET source_id='other-source'")
        with self.assertRaises(ValueError): self.verify('lines', manifest)
        self.change('DELETE FROM ky_retest_line_source')
        with self.assertRaises(ValueError): self.verify('lines', manifest)

    def test_line_component_value_is_exact(self):
        manifest = self.lines()
        self.change('UPDATE ky_line_component SET value=61')
        with self.assertRaises(ValueError): self.verify('lines', manifest)

    def test_line_component_own_locator_cannot_disagree_with_parent(self):
        manifest = self.lines()
        self.change('UPDATE ky_line_component SET src_locator=?', (dump({'src_page': 99, 'src_table': 't9', 'src_row': '99'}),))
        with self.assertRaises(ValueError): self.verify('lines', manifest)

    def test_omitted_context_fields_must_match_explicit_ingester_empty_defaults(self):
        manifest = self.lines(partial_context=True)
        self.assertTrue(self.verify('lines', manifest)['ok'])
        self.change("UPDATE ky_line_scope_context SET joint_program='合成错误联培' ")
        with self.assertRaises(ValueError): self.verify('lines', manifest)

    def test_three_person_statistics_and_real_score_affinity_pass(self):
        self.assertTrue(self.verify('stats', self.stats(3))['ok'])

    def test_one_and_two_person_statistics_are_rejected_even_if_database_matches(self):
        for n in [1, 2]:
            with self.subTest(n=n):
                self.change('DELETE FROM ky_score_dist')
                manifest = self.stats(n)
                with self.assertRaisesRegex(ValueError, '不足三人'): self.verify('stats', manifest)

    def test_statistic_endpoint_mismatch_is_rejected(self):
        manifest = self.stats()
        self.change('UPDATE ky_score_dist SET max=336')
        with self.assertRaises(ValueError): self.verify('stats', manifest)

    def test_deadline_exception_stops_readback(self):
        manifest = self.catalog()
        def expired(): raise TimeoutError('合成期限已到')
        with self.assertRaises(TimeoutError): self.verify('catalog', manifest, deadline=expired)

    def test_private_field_is_rejected_without_echoing_the_value(self):
        manifest = self.stats()
        manifest['rows'][0]['姓名'] = '合成隐私标记'
        with self.assertRaises(ValueError) as caught: self.verify('stats', manifest)
        self.assertNotIn('合成隐私标记', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
