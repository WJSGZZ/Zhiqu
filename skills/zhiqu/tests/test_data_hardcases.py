"""数据难例索引：复用既有合成fixture和断言，不访问正式库或原件。

单独跑：python3 -m unittest discover -s skills/zhiqu/tests -p test_data_hardcases.py -v
full discover也会复用这些方法；计数包含复用，不代表增加同样数量的新断言。
"""
import ast
import copy
import json
from pathlib import Path
import re
import unittest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[2]
CATALOG = TESTS / 'fixtures/data-hardcases.json'
SELECTOR = re.compile(r'(test_[a-z0-9_]+)\.([A-Za-z][A-Za-z0-9_]*)\.(test_[a-zA-Z0-9_]+)')


def validate_catalog(data):
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('难例索引须为schema_version=1的对象')
    cases = data.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('难例cases须为非空列表')
    ids, selectors = set(), set()
    for case in cases:
        if not isinstance(case, dict):raise ValueError('难例须为对象')
        ident, selector = case.get('id'), case.get('test')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9-]+', ident) or ident in ids:
            raise ValueError('难例id须唯一且为小写英文/数字/短横线')
        match = SELECTOR.fullmatch(selector) if isinstance(selector, str) else None
        if not match or selector in selectors or match[1] == Path(__file__).stem:
            raise ValueError('难例须唯一指向本地具体测试方法，不能递归加载本索引')
        module, cls, method = match.groups()
        path = TESTS / (module + '.py')
        if not path.is_file() or path.resolve().parent != TESTS:
            raise ValueError('难例测试文件须在本项目tests内')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        symbols = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        symbols.update(n.name+'.'+f.name for n in tree.body if isinstance(n, ast.ClassDef)
                       for f in n.body if isinstance(f, ast.FunctionDef))
        if cls+'.'+method not in symbols:raise ValueError('难例测试方法不存在')
        fixture = case.get('input_fixture')
        if (not isinstance(fixture, dict) or fixture.get('file') != path.name
                or not isinstance(fixture.get('symbols'), list) or cls+'.'+method not in fixture['symbols']
                or any(not isinstance(s, str) or s not in symbols for s in fixture['symbols'])):
            raise ValueError('最小输入须指向实际存在的fixture函数或方法，不另抄一份数据')
        if case.get('domain') not in ('高考', '考研', '就业', '报告') or not isinstance(case.get('expected'), str) or not case['expected'].strip():
            raise ValueError('难例须有领域及明确期望结果')
        origin = case.get('provenance')
        if (not isinstance(origin, dict) or not isinstance(origin.get('commit'), str)
                or not re.fullmatch(r'[0-9a-f]{7,40}', origin['commit'])
                or origin.get('file') != path.relative_to(ROOT).as_posix()
                or not isinstance(origin.get('basis'), str) or not origin['basis'].strip()):
            raise ValueError('难例须记录修补提交及实际输入所在文件，不能冒充原件核验')
        ids.add(ident); selectors.add(selector)
    pending = data.get('not_in_this_suite')
    if not isinstance(pending, list):raise ValueError('未覆盖项须单列原因，不能混进通过数')
    for item in pending:
        ident = item.get('id') if isinstance(item, dict) else None
        if (not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9-]+', ident) or ident in ids
                or not isinstance(item.get('reason'), str) or not item['reason'].strip()):
            raise ValueError('未覆盖项须有唯一id及原因，不能混进通过数')
        ids.add(ident)
    return cases


class HardcaseIndexTests(unittest.TestCase):
    def test_index_and_input_locations_are_valid(self):
        cases = validate_catalog(json.loads(CATALOG.read_text()))
        self.assertEqual(len({x['test'] for x in cases}), len(cases))
        self.assertTrue({'高考', '考研', '报告'} <= {x['domain'] for x in cases})

    def test_bad_or_stale_index_fails_instead_of_silently_running_nothing(self):
        original = json.loads(CATALOG.read_text())
        changes = [lambda d: d.update(schema_version=True), lambda d: d.update(cases=[]),
                   lambda d: d['cases'].append(copy.deepcopy(d['cases'][0])),
                   lambda d: d['cases'][0].update(test='os.system'),
                   lambda d: d['cases'][0].update(test='test_data_hardcases.HardcaseIndexTests.test_index_and_input_locations_are_valid'),
                   lambda d: d['cases'][0].update(test='test_no_such_module.NoClass.test_absent'),
                   lambda d: d['cases'][0]['input_fixture'].update(file='/private/input.py'),
                   lambda d: d['cases'][0]['input_fixture'].update(symbols=['missing_fixture']),
                   lambda d: d['cases'][0]['input_fixture'].update(symbols=['legacy_fact']),
                   lambda d: d['cases'][0]['provenance'].update(commit='unknown'),
                   lambda d: d['cases'][0].update(expected=''),
                   lambda d: d.update(not_in_this_suite=[{'id':'image','reason':''}])]
        for change in changes:
            data = copy.deepcopy(original);change(data)
            with self.subTest(change=changes.index(change)), self.assertRaises(ValueError):validate_catalog(data)


def load_tests(loader, standard_tests, pattern):
    """只组合unittest已有TestCase；fixture及断言仍由原方法执行。"""
    cases = validate_catalog(json.loads(CATALOG.read_text(encoding='utf-8')))
    suite = unittest.TestSuite([standard_tests])
    for case in cases:
        selected = loader.loadTestsFromName(case['test'])
        if selected.countTestCases() != 1 or loader.errors:
            raise ValueError('难例不能精确加载一个既有测试：'+case['id'])
        suite.addTests(selected)
    return suite
