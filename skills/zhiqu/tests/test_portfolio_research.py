"""Research must preserve the temporal boundary and unknown observations."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import evaluate_portfolios as research
import sparse_data_review as sparse


class PortfolioResearch(unittest.TestCase):
    def test_target_observations_cannot_change_prediction_or_utility(self):
        value = lambda rank: dict(rank=rank, name='测试师范大学')
        data = {2024: {('x', 'm'): value(15000)}, 2025: {('x', 'm'): value(16000)}}
        expected = research.historical_rows(data, 2026)
        data[2026] = {('x', 'm'): value(90000), ('future', 'm'): value(5000)}
        self.assertEqual(expected, research.historical_rows(data, 2026))
        result = research.resonance_review('test', data, 2027)
        self.assertEqual('unavailable_target_observations', result['scope'])
        self.assertIsNone(result['permutation_p'])

    def test_missing_earlier_choice_is_not_a_rejection(self):
        rows = [dict(key=('x', 'm'), u=90), dict(key=('y', 'm'), u=50)]
        self.assertEqual((None, None, None), research.landing(rows, [0, 1], {('y', 'm'): dict(rank=20000)}, 10000))
        self.assertEqual((0, 90, 1), research.landing(rows, [0, 1], {('x', 'm'): dict(rank=20000)}, 10000))

    def test_bh_monotonic_adjustment_and_variance(self):
        qs = research.bh([.01, .04, .03])
        for actual, expected in zip(qs, [.03, .04, .04]):
            self.assertAlmostEqual(actual, expected)
        ratio, _ = research.variance_components([0, 0, 10, 10], ['a', 'a', 'b', 'b'])
        self.assertEqual(1, ratio)


class SparseDataResearch(unittest.TestCase):
    def test_prediction_never_reads_the_target_year(self):
        value = lambda rank: dict(rank=rank, name='测试大学', label='')
        data = {2024: {('x', '1'): value(15000)}, 2025: {('x', '1'): value(16000)}}
        expected = sparse.predict(data, [2024, 2025], 2026, ('x', '1'), 0.02)
        data[2026] = {('x', '1'): value(90000)}
        self.assertEqual(expected, sparse.predict(data, [2024, 2025], 2026, ('x', '1'), 0.02))
        self.assertIsNone(sparse.predict(data, [2024, 2025], 2026, ('y', '1'), 0.0))

    def test_rank_correlation_and_two_factor_regression(self):
        self.assertAlmostEqual(1.0, sparse.spearman([1, 2, 3, 4], [10, 20, 30, 40]))
        self.assertAlmostEqual(-1.0, sparse.spearman([1, 2, 3, 4], [4, 3, 2, 1]))
        rows = [(0.7 * a + 0.25 * b + 1, a, b) for a, b in ((1, 2), (2, 1), (3, 5), (4, 3), (5, 8))]
        b, c = sparse.ols2(rows)
        self.assertAlmostEqual(0.7, b)
        self.assertAlmostEqual(0.25, c)

    def test_school_floor_ignores_special_plan_groups(self):
        year = {('甲大学', '1'): dict(rank=20000, label='1'), ('甲大学', '2'): dict(rank=40000, label='国家专项计划组'),
                ('甲大学', '3'): dict(rank=30000, label='合作办学组')}
        self.assertEqual({'甲大学': 30000}, sparse.school_min(year))


if __name__ == '__main__':
    unittest.main()
