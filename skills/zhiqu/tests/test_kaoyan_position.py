import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from kaoyan_position import place

SUBJECTS = ['政治', '英语一', '数学一', '408']
MOCK = {'subjects': SUBJECTS, 'total': 372, 'complete': True,
        'singles': {'政治': 68, '英语一': 64, '数学一': 112, '408': 128}}


def program(admitted_2026, admitted_2025=None, singles=None, subjects=SUBJECTS):
    years = {'2026': {'retest': {'total': 330, 'singles': singles or {'政治': 50, '英语一': 50, '数学一': 75, '408': 75}},
                      'admitted': admitted_2026}}
    if admitted_2025:
        years['2025'] = {'retest': {'total': 325}, 'admitted': admitted_2025}
    return {'id': 'P', 'name': '测试', 'subjects': subjects, 'years': years}


def dist(q1, median, n=80):
    return {'n': n, 'min': q1 - 15, 'q1': q1, 'median': median, 'q3': median + 12, 'max': median + 40}


class KaoyanPositionTests(unittest.TestCase):
    def test_two_years_above_median_is_relatively_safe(self):
        self.assertEqual(place(MOCK, program(dist(355, 365), dist(352, 360)))['tier'], '相对稳妥')

    def test_one_year_only_never_relatively_safe(self):
        self.assertEqual(place(MOCK, program(dist(355, 365)))['tier'], '够一够')

    def test_between_q1_and_median_is_reach(self):
        self.assertEqual(place(MOCK, program(dist(360, 380), dist(358, 378)))['tier'], '够一够')

    def test_below_q1_is_risky(self):
        self.assertEqual(place(MOCK, program(dist(380, 392), dist(378, 390)))['tier'], '冒险')

    def test_single_subject_below_line_overrides_total(self):
        r = place(MOCK, program(dist(340, 350), dist(340, 350), singles={'政治': 50, '英语一': 70, '数学一': 75, '408': 75}))
        self.assertEqual(r['tier'], '冒险')
        self.assertIn('英语一', r['reasons'][0])

    def test_different_subjects_or_incomplete_mock_gives_no_tier(self):
        self.assertIsNone(place(MOCK, program(dist(340, 350), subjects=['政治', '英语二', '数学二', '自命题']))['tier'])
        self.assertIsNone(place(dict(MOCK, complete=False), program(dist(340, 350)))['tier'])

    def test_small_cohort_is_flagged(self):
        r = place(MOCK, program(dist(355, 365, n=6), dist(352, 360, n=5)))
        self.assertTrue(any('分布不稳' in x for x in r['reasons']))


if __name__ == '__main__':
    unittest.main()
