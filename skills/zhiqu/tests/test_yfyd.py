"""一分一段表结构及投档最低位次的交叉核验测试。"""
import contextlib
import csv
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import check_yfyd  # noqa: E402


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


class TestCheckYfyd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.yfyd = os.path.join(self.tmp.name, "yfyd.csv")
        self.admissions = os.path.join(self.tmp.name, "admissions.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def test_count_cumulative_recurrence(self):
        write_csv(self.yfyd, ["score", "count", "cum"], [[600, 2, 2], [599, 3, 5]])
        result = check_yfyd.check_yfyd(self.yfyd)
        self.assertEqual(result["issues"], [])

    def test_count_cumulative_misalignment_is_error(self):
        write_csv(self.yfyd, ["score", "count", "cum"], [[600, 2, 2], [599, 3, 6]])
        result = check_yfyd.check_yfyd(self.yfyd)
        self.assertTrue(any("上一行累计" in issue for issue in result["issues"]))

    def test_non_monotonic_cumulative_is_error(self):
        write_csv(self.yfyd, ["score", "count", "cum"], [[600, 2, 5], [599, 3, 4]])
        result = check_yfyd.check_yfyd(self.yfyd)
        self.assertTrue(any("小于上一行" in issue for issue in result["issues"]))

    def test_count_cannot_exceed_cumulative(self):
        write_csv(self.yfyd, ["score", "count", "cum"], [[600, 6, 5]])
        result = check_yfyd.check_yfyd(self.yfyd)
        self.assertTrue(any("大于累计数" in issue for issue in result["issues"]))

    def test_admission_rank_must_be_in_same_score_tie_interval(self):
        write_csv(self.yfyd, ["score", "count", "cum"], [[600, 2, 5], [599, 3, 8]])
        write_csv(self.admissions, ["score", "rank"], [[600, 5], [599, 6]])
        result = check_yfyd.check_yfyd(self.yfyd)
        issues, _ = check_yfyd.check_admissions(self.admissions, result["segments"], result["range"])
        self.assertEqual(issues, [])
        write_csv(self.admissions, ["score", "rank"], [[600, 6]])
        issues, _ = check_yfyd.check_admissions(self.admissions, result["segments"], result["range"])
        self.assertTrue(any("不在同分位次区间" in issue for issue in issues))

    def test_repeated_terminal_score_requires_explicit_summary_declaration(self):
        write_csv(self.yfyd, ["score", "count", "cum", "source"], [
            [600, 2, 2, "原表"], [100, 2, 4, "原表"], [100, 5, 9, "原表"]
        ])
        implicit = check_yfyd.check_yfyd(self.yfyd)
        self.assertTrue(any("分数重复" in issue for issue in implicit["issues"]))
        explicit = check_yfyd.check_yfyd(self.yfyd, trailing_below_score_summary=100)
        self.assertEqual(explicit["issues"], [])
        self.assertEqual(explicit["range"], (100, 600))
        self.assertEqual(explicit["segments"][100], (3, 4))
        write_csv(self.admissions, ["score", "rank"], [[100, 4]])
        issues, _ = check_yfyd.check_admissions(self.admissions, explicit["segments"], explicit["range"])
        self.assertEqual(issues, [])

    def test_missing_score_and_interpolation_do_not_certify_tie_bounds(self):
        write_csv(self.yfyd, ["score", "cum", "source"], [[600, 5, "原表"], [598, 12, "原表"], [597, 15, "插值"]])
        result = check_yfyd.check_yfyd(self.yfyd)
        self.assertIsNone(result["segments"][598][0])
        self.assertNotIn(597, result["segments"])

    def test_incorrect_summary_declaration_is_error(self):
        write_csv(self.yfyd, ["score", "count", "cum"], [[600, 2, 2], [100, 3, 5]])
        result = check_yfyd.check_yfyd(self.yfyd, trailing_below_score_summary=100)
        self.assertTrue(any("声明末尾" in issue for issue in result["issues"]))

    def test_cli_returns_nonzero_for_alignment_error(self):
        write_csv(self.yfyd, ["score", "count", "cum"], [[600, 2, 2], [599, 3, 6]])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = check_yfyd.main([self.yfyd])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
