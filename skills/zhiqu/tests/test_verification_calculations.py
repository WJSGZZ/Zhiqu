"""Verification uses registered source inputs, rejects modified outputs, and emits arithmetic."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verification_calculations import calculation_rows, recompute, walk, numeric, _registered

SKILLS = Path(__file__).resolve().parents[2]


def load_case(path):
    return [json.loads((path / name).read_text()) for name in
            ('case.json', 'profile_parse.json', 'evidence.json', 'calculations.json')]


class VerificationCalculationTests(unittest.TestCase):
    def test_list_statistics_are_named_by_their_data_item_not_scores(self):
        case = {'anonymous_data': {'x': {'values': [3, 9, 1, 5]}}, 'calculation_plan': {'operations': [
            {'output': 'n', 'algorithm': 'count', 'inputs': ['{{k:/anonymous_data/x/values}}'], 'item_name': '职位'},
            {'output': 'mid', 'algorithm': 'median', 'inputs': ['{{k:/anonymous_data/x/values}}'],
             'item_name': '职位的竞争比', 'unit': '缴费人数÷招录人数'},
            {'output': 'top', 'algorithm': 'max', 'inputs': ['{{k:/anonymous_data/x/values}}']}]}}
        computed, rows = _registered(case, {}, {'items': []})
        self.assertEqual(computed, {'n': 4, 'mid': 4.0, 'top': 9})
        formulas = {r['path']: r['formula'] for r in rows}
        self.assertEqual(formulas['/n'], '数出 4 个职位')
        self.assertIn('4 个职位的竞争比（单位：缴费人数÷招录人数）排序后取中位数', formulas['/mid'])
        self.assertEqual(formulas['/top'], '4 个数值排序后取最高')
        self.assertFalse(any('分数' in f for f in formulas.values()))

    def test_flagship_career_example_recomputes(self):
        args = load_case(SKILLS / 'zhiqu-career/examples/2027-QZ-S05')
        self.assertEqual(recompute(*args), args[-1])

    def test_four_complete_examples_recompute_and_describe_every_number(self):
        for name in ('zhiqu-grad/examples/demo_2027', 'zhiqu-career/examples/demo_2027',
                     'zhiqu-grad/examples/2028-YJ-S02', 'zhiqu-career/examples/2027-QZ-S02'):
            with self.subTest(name=name):
                args = load_case(SKILLS / name)
                original = copy.deepcopy(args)
                self.assertEqual(recompute(*args), args[-1])
                rows = calculation_rows(*args)
                self.assertEqual({row['path'] for row in rows},
                                 {path for path, value in walk(args[-1]) if numeric(value)})
                self.assertTrue(all(row['inputs'] and row['formula'] for row in rows))
                self.assertEqual(args, original)
                tampered = copy.deepcopy(args)
                key = next(key for key, value in tampered[-1].items() if numeric(value))
                tampered[-1][key] += 1
                with self.assertRaises(ValueError): recompute(*tampered)

    def test_registered_refs_recompute_before_saved_results(self):
        case = {'kind': 'grad', 'calculation_plan': {'engine': 'registered_operations', 'operations': [
            {'output': 'sum', 'algorithm': 'sum', 'inputs': ['{{k:/budget}}', '{{p:/score}}', '{{e:E1#/value}}']},
            {'output': 'product', 'algorithm': 'product', 'inputs': ['{{c:/sum}}', 2]},
            {'output': 'ratio', 'algorithm': 'ratio', 'inputs': ['{{c:/product}}', 3], 'rounding': 1}],
            'scenarios': [{'baseline_output':'sum', 'changed_inputs':{'{{k:/budget}}': 4},
                           'output_ref':'{{c:/alternative}}'}]}, 'budget': 1}
        profile = {'score': 2}; evidence = {'items':[{'id':'E1', 'value':3}]}
        result = {'sum':6, 'product':12, 'ratio':4.0, 'alternative':9}
        self.assertEqual(recompute(case, profile, evidence, result), result)
        rows = calculation_rows(case, profile, evidence, result)
        self.assertEqual(rows[1]['inputs'], [6, 2])
        bad = dict(result, sum=7, product=14, ratio=4.7)
        with self.assertRaises(ValueError): recompute(case, profile, evidence, bad)

    def test_missing_unknown_or_nonfinite_algorithm_rejected(self):
        for algorithm, values in [('eval', [1]), ('sum', []), ('ratio', [1, 0]), ('sum', [float('inf')])]:
            case = {'calculation_plan': {'engine': 'registered_operations', 'operations': [
                {'output':'x', 'algorithm':algorithm, 'inputs':values}]}}
            with self.subTest(algorithm=algorithm, values=values):
                with self.assertRaises((ValueError, ZeroDivisionError)):
                    recompute(case, {}, {'items':[]}, {'x':0})

    def test_forward_and_circular_result_references_rejected(self):
        case = {'calculation_plan': {'engine':'registered_operations', 'operations':[
            {'output':'x','algorithm':'sum','inputs':['{{c:/x}}',1]}]}}
        with self.assertRaises(KeyError): recompute(case, {}, {'items':[]}, {'x':2})

    def test_offer_formulas_use_unrounded_tax_and_original_inputs(self):
        args = load_case(SKILLS / 'zhiqu-career/examples/demo_2027')
        rows = {row['path']:row for row in calculation_rows(*args)}
        row = rows['/offer_b_ordinary_month/remaining_cash']
        self.assertEqual(row['result'],1967)
        self.assertEqual(row['inputs']['发薪月数'],12)
        self.assertIn('中间值不取整', row['formula'])
        self.assertNotIn('1967', row['formula'])
        row = rows['/hypothetical_offers/1/tax']
        self.assertIn('60000', row['formula'])

    def test_quantile_formula_provides_interpolation_operands(self):
        args = load_case(SKILLS / 'zhiqu-grad/examples/demo_2027')
        rows = {row['path']:row for row in calculation_rows(*args)}
        row = rows['/gdut_2026_first_choice_retest_scores/q1']
        self.assertIn('Type 7',row['formula'])
        self.assertEqual(row['inputs']['样本量'],86)
        self.assertIn('相邻排序值',row['inputs'])
        source_row = rows['/scut_reference_statistics/2026_普通计划/n']
        self.assertIn('未附原始名单', source_row['verification_limit'])

    def test_boolean_result_cannot_replace_number(self):
        case = {'calculation_plan': {'engine':'registered_operations','operations':[
            {'output':'x','algorithm':'sum','inputs':[1]}]}}
        with self.assertRaises(ValueError): recompute(case, {}, {'items':[]}, {'x':True})


class GaokaoVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = SKILLS / 'zhiqu'
        cls.pro = cls.root / 'examples/2026-GK-R01/result.json'
        cls.group = cls.root / 'examples/case_c_guangdong_e2e/result.json'

    def example(self, path):
        result = json.loads(path.read_text())
        return result, (self.root / result['params']['csv']).read_bytes()

    def test_all_saved_gaokao_results_recompute_exactly(self):
        from verification_calculations import recompute_gaokao
        paths = sorted((self.root/'examples').glob('*/**/result.json'))
        self.assertGreaterEqual(len(paths), 18)
        for path in paths:
            with self.subTest(path=str(path)):
                saved, source = self.example(path)
                fresh = recompute_gaokao(saved, source)
                self.assertEqual(fresh['list'], saved['list'])
                self.assertEqual(fresh['stress'], saved['stress'])

    def test_per_row_numbers_cannot_hide_behind_unchanged_totals(self):
        from verification_calculations import recompute_gaokao
        result, source = self.example(self.pro)
        for key in ('p_clear','p_land','p_adjusted','expected_cut_rank','sigma','utility','order'):
            bad = copy.deepcopy(result); bad['list'][0][key] += .01
            with self.subTest(key=key):
                with self.assertRaises(ValueError): recompute_gaokao(bad, source)

    def test_major_probabilities_and_names_rechecked(self):
        from verification_calculations import recompute_gaokao
        result, source = self.example(self.group)
        for key in ('p','utility','name'):
            bad = copy.deepcopy(result)
            major = bad['list'][0]['majors'][0]
            major[key] = major[key] + ('错' if key == 'name' else .001)
            with self.subTest(key=key):
                with self.assertRaises(ValueError): recompute_gaokao(bad, source)

    def test_limits_nonfinite_and_arbitrary_params(self):
        from verification_calculations import recompute_gaokao
        result, source = self.example(self.pro)
        for key,value in [('sims',20001),('slots',101),('rank',float('nan')),('rho',1),('sigma_rule','exec')]:
            bad=copy.deepcopy(result);bad['params'][key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError): recompute_gaokao(bad,source)
        bad=copy.deepcopy(result);bad['params']['csv']='/never/read/from/pdf.csv';bad['params']['json']='/never/write.json'
        self.assertEqual(recompute_gaokao(bad,source)['list'],result['list'])
        many = b'id,name,utility,rank_2025\n' + b'a,a,50,10000\n'*5001
        with self.assertRaises(ValueError): recompute_gaokao(result,many)

    def test_formal_attachment_never_invokes_qualification_source_loader(self):
        from verification_calculations import recompute_gaokao
        from unittest.mock import patch
        import builtins
        import csv
        import io
        result, source = self.example(self.pro)
        result['params']['decision_mode'] = 'formal'
        reader = csv.DictReader(io.StringIO(source.decode('utf-8-sig')))
        rows = list(reader)
        fields = list(reader.fieldnames) + ['qualification_file']
        forbidden_path = '/never/read/client-private-qualification.json'
        for row in rows:
            row['qualification_file'] = forbidden_path
        out = io.StringIO(newline='')
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
        original_open = builtins.open
        def guarded_open(file, *args, **kwargs):
            if str(file) == forbidden_path:
                raise AssertionError('attachment must not trigger external file reads')
            return original_open(file, *args, **kwargs)
        with patch('optimize.require_formal', side_effect=AssertionError('offline replay must not run eligibility loader')) as gate:
            with patch('builtins.open', side_effect=guarded_open):
                fresh = recompute_gaokao(result, out.getvalue().encode())
        gate.assert_not_called()
        self.assertEqual(fresh['list'], result['list'])

    def test_changed_candidate_order_or_source_rejected(self):
        from verification_calculations import recompute_gaokao
        result, source = self.example(self.group)
        lines=source.decode('utf-8-sig').splitlines()
        changed=('\n'.join([lines[0]]+list(reversed(lines[1:])))+'\n').encode()
        with self.assertRaises(ValueError): recompute_gaokao(result,changed)


if __name__ == '__main__':
    unittest.main()
