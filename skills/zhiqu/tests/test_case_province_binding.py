"""换省报告不能只因规则文件存在而沿用另一省的规则。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from case_check import Gate, province_name, PROFILE_FIELDS, PROFILE_HEAD


class ProvinceBindingTests(unittest.TestCase):
    def run_case(self, province='贵州', rules='{"province":"河北"}'):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / '2027-GK-0001'
            folder.mkdir()
            source = Path(temp) / 'rules.json'
            source.write_text(rules)
            case = {'case_id': folder.name, 'province': province, 'year': 2027,
                    'category': '物理', 'mode': 'simulation', 'prepared_on': '2026-10-28',
                    'data_commit': '552951b', 'province_rules': str(source),
                    'rank': 65000, 'slots': 96}
            (folder / 'case.json').write_text(json.dumps(case))
            gate = Gate(folder)
            gate.stage0()
            return gate.errors

    def test_cross_province_simulation_is_rejected(self):
        self.assertTrue(any('不能跨省借用' in e for e in self.run_case()))

    def test_same_province_full_name_and_whitespace_are_allowed(self):
        self.assertEqual(self.run_case(' 贵州省 ', '{"province":"贵州"}'), [])
        self.assertEqual(self.run_case('贵州', '{"province":"贵州省"}'), [])

    def test_municipal_and_autonomous_names_are_exact_aliases(self):
        for full, short in [('北京市', '北京'), ('广西壮族自治区', '广西'),
                            ('新疆维吾尔自治区', '新疆'), ('内蒙古自治区', '内蒙古')]:
            with self.subTest(full=full):
                self.assertEqual(self.run_case(full, json.dumps({'province': short})), [])
        self.assertNotEqual(province_name('吉林市'), province_name('吉林'))
        for invented in ('北京省', '广西省', '贵州自治区'):
            with self.subTest(invented=invented):
                self.assertNotEqual(province_name(invented), province_name(invented[:2]))

    def test_missing_or_invalid_declared_province_is_rejected(self):
        for value in ({}, {'province': ''}, {'province': []}, {'province': True}, [], None):
            with self.subTest(value=value):
                self.assertTrue(any('有效province' in e for e in self.run_case(rules=json.dumps(value))))

    def test_broken_json_reports_an_error_instead_of_crashing(self):
        self.assertTrue(any('有效JSON' in e for e in self.run_case(rules='{bad')))

    def test_known_profile_province_cannot_be_replaced_by_registration(self):
        for value, status, expected in [('浙江', 'given', True), (' 浙江省 ', 'given', True),
                                         ('贵州省', 'given', False), ('浙江', 'inferred', True),
                                         (None, 'unknown', False)]:
            with self.subTest(value=value, status=status), tempfile.TemporaryDirectory() as temp:
                parse = {'fields': [{'field': name, 'status': 'given', 'value': '已提供'}
                                    for name in PROFILE_FIELDS], 'missing': []}
                for field in parse['fields']:
                    if field['field'] == '位次':
                        field['value'] = 65000
                    if field['field'] == '省份':
                        field.update(value=value, status=status, confirmed=True)
                if status == 'unknown':
                    parse['missing'].append('省份')
                (Path(temp) / 'profile_parse.json').write_text(json.dumps(parse))
                gate = Gate(temp)
                gate.case = {'province': '贵州', 'rank': 65000}
                with patch('profile_store.active_profile', return_value=PROFILE_HEAD):
                    gate.stage1()
                self.assertEqual(any('画像生源省' in e for e in gate.errors), expected)
                if not expected:
                    self.assertEqual(gate.errors, [])

    def test_real_wrong_province_file_is_rejected_by_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / '2027-GK-0001'
            folder.mkdir()
            (folder / 'case.json').write_text(json.dumps({
                'case_id': folder.name, 'province': '贵州', 'year': 2027,
                'category': '物理', 'mode': 'simulation', 'prepared_on': '2026-10-28',
                'data_commit': '552951b', 'province_rules': 'data/hebei/rules.json',
                'rank': 65000, 'slots': 96}))
            p = subprocess.run([sys.executable, str(SCRIPTS / 'case_check.py'),
                                str(folder), '--stage', '0'], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('不能跨省借用', p.stdout + p.stderr)
