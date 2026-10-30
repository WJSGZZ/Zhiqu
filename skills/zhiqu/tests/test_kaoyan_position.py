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

    def test_n3_in_any_reference_year_gives_no_tier(self):
        r = place(MOCK, program(dist(330, 340, n=3), dist(330, 340, n=40)))
        self.assertIsNone(r['tier'])
        self.assertEqual(r['untiered_reason'], '样本太少')

    def test_n5_caps_relatively_safe_at_reach(self):
        r = place(MOCK, program(dist(355, 365, n=5), dist(352, 360, n=40)))
        self.assertEqual(r['tier'], '够一够')
        self.assertTrue(any('样本小，只作定性' in x for x in r['reasons']))

    def test_n9_still_capped_and_flagged(self):
        r = place(MOCK, program(dist(355, 365, n=40), dist(352, 360, n=9)))
        self.assertEqual(r['tier'], '够一够')
        self.assertTrue(any('样本小，只作定性' in x for x in r['reasons']))
        r = place(MOCK, program(dist(380, 392, n=9), dist(378, 390, n=9)))
        self.assertEqual(r['tier'], '冒险')
        self.assertTrue(any('样本小，只作定性' in x for x in r['reasons']))

    def test_untiered_reasons_are_enumerated(self):
        self.assertEqual(place(MOCK, program(dist(340, 350), subjects=['政治', '英语二', '数学二', '408']))['untiered_reason'], '科目不同')
        p = program(dist(340, 350)); p['years']['2026'].pop('admitted')
        self.assertEqual(place(MOCK, p)['untiered_reason'], '分布缺失')
        p['subjects'] = []
        self.assertEqual(place(MOCK, p)['untiered_reason'], '分布缺失')

    def test_partial_distribution_is_a_gap_not_a_crash(self):
        for year in ['2026', '2025']:
            for field in ['n', 'min', 'q1', 'median', 'q3', 'max']:
                for missing in ['absent', None]:
                    with self.subTest(year=year, field=field, missing=missing):
                        p = program(dist(355, 365), dist(352, 360))
                        adm = p['years'][year]['admitted']
                        if missing == 'absent':
                            adm.pop(field)
                        else:
                            adm[field] = None
                        r = place(MOCK, p)
                        self.assertIsNone(r['tier'])
                        self.assertEqual(r['untiered_reason'], '分布缺失')
                        self.assertNotIn(year, r['positions'])
                        self.assertEqual(r['gaps'][year], {'retest_total': MOCK['total'] - p['years'][year]['retest']['total']})
                        self.assertTrue(any(year in reason for reason in r['reasons']))

    def test_invalid_statistics_cannot_create_a_tier(self):
        for field, value in [('n', 0), ('n', 2.5), ('n', True), ('n', '80'),
                             ('q1', float('nan')), ('q3', float('inf')),
                             ('median', True), ('min', -1), ('q1', 500), ('max', 300),
                             ('n', 10**400), ('q3', 10**400)]:
            with self.subTest(field=field, value=value):
                a = dist(355, 365); a[field] = value
                r = place(MOCK, program(a, dist(352, 360)))
                self.assertIsNone(r['tier'])
                self.assertEqual(r['untiered_reason'], '分布缺失')

    def test_empty_or_non_mapping_statistics_remain_a_gap(self):
        for a in [{}, [], '未公布', 1]:
            with self.subTest(admitted=a):
                r = place(MOCK, program(a, dist(352, 360)))
                self.assertIsNone(r['tier'])
                self.assertEqual(r['untiered_reason'], '分布缺失')

    def test_single_subject_risk_survives_partial_statistics(self):
        for missing in [None, 10**400]:
            a = dist(355, 365); a['q1'] = missing; a['q3'] = missing
            r = place(MOCK, program(a, singles={'英语一': 70}))
            self.assertEqual(r['tier'], '冒险')
            self.assertTrue(any('单科低于' in reason for reason in r['reasons']))
            self.assertNotIn('2026', r['positions'])
            self.assertEqual(r['gaps']['2026']['retest_total'], 42)

if __name__ == '__main__':
    unittest.main()
