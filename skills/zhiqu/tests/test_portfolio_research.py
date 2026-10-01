"""Research must preserve the temporal boundary and unknown observations."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import evaluate_portfolios as research


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


if __name__ == '__main__':
    unittest.main()
