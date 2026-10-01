"""Prevent a future score/offer or a stale chart becoming a planning-demo fact."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_demos


class DemoIntegrity(unittest.TestCase):
    def setUp(self):
        path = check_demos.DEMO_PATHS[1]
        self.case = json.loads((path / 'case.json').read_text(encoding='utf-8'))
        self.chart = json.loads((path / 'birth_chart.json').read_text(encoding='utf-8'))
        self.profile = (path / 'profile.txt').read_text(encoding='utf-8')
        self.report = (path / 'report.md').read_text(encoding='utf-8')

    def test_saved_demos_actually_reproduce(self):
        for path in check_demos.DEMO_PATHS:
            with self.subTest(path=path):
                check_demos.check(path)

    def test_future_result_cannot_become_fact(self):
        for field in ('personal_success_probability', 'official_2027_score', 'official_offer'):
            with self.subTest(field=field):
                changed = dict(self.case, **{field: 0.7})
                with self.assertRaisesRegex(ValueError, 'future score'):
                    check_demos.validate(changed, self.chart, self.profile, self.report)

    def test_stale_start_direction_is_rejected(self):
        changed = copy.deepcopy(self.chart)
        changed['candidates'][0]['luck'][0]['start_datetime_birth_zone'] = '2006-01-01T00:00:00+08:00'
        with self.assertRaisesRegex(ValueError, 'precise luck start'):
            check_demos.validate(self.case, changed, self.profile, self.report)

    def test_examination_and_entry_timeline_cannot_reverse(self):
        changed = dict(self.case, graduation_date='2026-06-30')
        with self.assertRaisesRegex(ValueError, 'dates inconsistent'):
            check_demos.validate(changed, self.chart, self.profile, self.report)

    def test_unknown_annual_eligibility_cannot_be_certified(self):
        changed = copy.deepcopy(self.case)
        changed['evidence'][0]['status'] = 'verified'
        with self.assertRaisesRegex(ValueError, '未决|unresolved annual eligibility'):
            check_demos.validate(changed, self.chart, self.profile, self.report)


if __name__ == '__main__':
    unittest.main()
