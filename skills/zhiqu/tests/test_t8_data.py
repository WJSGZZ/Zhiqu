"""T8 选调高校范围表的结构、来源日期和主入口检查。"""
from collections import Counter
from contextlib import redirect_stdout
import csv
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_data


class TestSelectedUniversitiesData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "selected-universities-2027.csv"
        self.row = {
            "province": "江苏省", "year": "2027", "category": "类别Ⅰ",
            "school": "模拟大学", "major_restriction": "", "source_url": "https://example.gov.cn/notice.htm",
            "published_date": "2026-10-01", "retrieved_date": "2026-10-18",
            "review_deadline": "2027-09-30", "source_locator": "附件1第1页第2行", "notes": "",
        }

    def write(self, rows=None, fields=None):
        with self.path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields or validate_data.SELECTED_UNIVERSITIES_FIELDS,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows([self.row] if rows is None else rows)

    def check(self, **updates):
        self.write([dict(self.row, **updates)])
        return validate_data.check_selected_universities_file(self.path)[0]

    def test_valid_and_optional_fields(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(self.check(review_deadline=self.row["retrieved_date"]), [])

    def test_required_values(self):
        required = set(validate_data.SELECTED_UNIVERSITIES_FIELDS) - {"major_restriction", "notes"}
        for field in sorted(required):
            for value in ("", "   "):
                with self.subTest(field=field, value=value):
                    self.assertTrue(any(field in issue for issue in self.check(**{field: value})))

    def test_missing_columns_and_empty_or_missing_file(self):
        self.assertTrue(validate_data.check_selected_universities_file(self.path)[0])
        self.write(rows=[])
        self.assertTrue(validate_data.check_selected_universities_file(self.path)[0])
        for field in validate_data.SELECTED_UNIVERSITIES_FIELDS:
            with self.subTest(field=field):
                self.write(fields=[name for name in validate_data.SELECTED_UNIVERSITIES_FIELDS if name != field])
                issues, _ = validate_data.check_selected_universities_file(self.path)
                self.assertTrue(any("表头" in issue and field in issue for issue in issues))

    def test_year_must_be_integer_2027(self):
        for value in ("2026", "2028", "2027.0", "2.027e3", "NaN", "nan", "inf", "-inf",
                      "Infinity", "infinite", "二〇二七", "2027年", "02027"):
            with self.subTest(value=value):
                self.assertTrue(any("year" in issue for issue in self.check(year=value)))

    def test_web_url(self):
        for value in ("", "example.gov.cn/a", "https:///a", "ftp://example.gov.cn/a", "https://[broken",
                      "https://bad host/a", "https://example.gov.cn:no/a", "https://example.gov.cn:99999/a"):
            with self.subTest(value=value):
                self.assertTrue(any("source_url" in issue for issue in self.check(source_url=value)))
        self.assertEqual(self.check(source_url="http://example.gov.cn/a"), [])

    def test_real_iso_dates(self):
        for field in ("published_date", "retrieved_date", "review_deadline"):
            for value in ("2026/10/18", "2026-1-18", "2026-02-30", "2026-13-01", "0000-10-18", "NaN"):
                with self.subTest(field=field, value=value):
                    self.assertTrue(any(field in issue for issue in self.check(**{field: value})))
        self.assertTrue(any("早于" in issue for issue in self.check(review_deadline="2026-10-17")))

    def test_duplicate_key_and_distinct_restrictions(self):
        self.write([self.row, dict(self.row, notes="第二个来源也不能重复入库")])
        issues, _ = validate_data.check_selected_universities_file(self.path)
        self.assertTrue(any("重复" in issue for issue in issues))
        for field in ("province", "category", "school", "major_restriction"):
            with self.subTest(field=field):
                self.write([self.row, dict(self.row, **{field: "另一范围"})])
                self.assertEqual(validate_data.check_selected_universities_file(self.path)[0], [])

    def test_main_always_checks_career_table_separately(self):
        data = Path(self.tmp.name) / "gaokao"
        data.mkdir()
        (data / "schools.csv").write_text("code,name\n10001,模拟大学\n", encoding="utf-8")
        (data / "jiangsu").mkdir()
        for provinces in ([], ["jiangsu"]):
            for valid in (True, False):
                self.write([dict(self.row, year="2027" if valid else "NaN")])
                with self.subTest(provinces=provinces, valid=valid), \
                        patch.object(validate_data, "DATA", str(data)), \
                        patch.object(validate_data, "CAREER_DATA", self.tmp.name), \
                        patch.object(validate_data, "check_after_entry_file", return_value=([], [])), \
                        patch.object(validate_data, "check_competition_file", return_value=([], [])), \
                        patch.object(validate_data, "check_file") as admission_checker, \
                        patch.object(sys, "argv", ["validate_data.py", *provinces]), \
                        redirect_stdout(io.StringIO()) as output:
                    with self.assertRaises(SystemExit) as result:
                        validate_data.main()
                    self.assertEqual(result.exception.code, 0 if valid else 1)
                    self.assertIn("selected-universities-2027.csv", output.getvalue())
                    if not valid:
                        self.assertIn("year 必须是整数 2027", output.getvalue())
                        self.assertIn("共 1 个需要处理的问题", output.getvalue())
                    admission_checker.assert_not_called()

    def test_repository_table(self):
        path = ROOT.parent / "zhiqu-career" / "data" / "selected-universities-2027.csv"
        issues, _ = validate_data.check_selected_universities_file(path)
        self.assertEqual(issues, [])

    def test_repository_province_category_coverage(self):
        path = ROOT.parent / "zhiqu-career" / "data" / "selected-universities-2027.csv"
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 787)
        self.assertEqual(Counter(row["province"] for row in rows), {"江苏": 223, "浙江": 394, "山东": 170})
        expected = {
            ("江苏", "第一批/名校优生第1组"): 22,
            ("江苏", "第一批/名校优生第2组"): 5,
            ("江苏", "第一批/名校优生第3组"): 9,
            ("江苏", "第一批/名校优生第4组"): 4,
            ("江苏", "第一批/名校优生第5组"): 6,
            ("江苏", "第二批/乡镇类别I"): 144,
            ("江苏", "第二批/乡镇类别II"): 33,
            ("浙江", "常规选调/36所“双一流”高校"): 36,
            ("浙江", "常规选调/3所科研型大学"): 3,
            ("浙江", "常规选调/5所政法大学"): 5,
            ("浙江", "常规选调/15所省重点建设高校"): 15,
            ("浙江", "定向紧缺专业选调"): 335,
            ("山东", "第一批/定向选调"): 21,
            ("山东", "第二批/定向选调/部分高校"): 50,
            ("山东", "第二批/定向选调/部分高校的相关专业"): 99,
        }
        self.assertEqual(Counter((row["province"], row["category"]) for row in rows), expected)
        scarce_majors = [row for row in rows if row["province"] == "浙江" and row["category"] == "定向紧缺专业选调"]
        self.assertEqual(len({row["major_restriction"] for row in scarce_majors}), 39)

    def test_repository_eligibility_boundaries(self):
        path = ROOT.parent / "zhiqu-career" / "data" / "selected-universities-2027.csv"
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        zhongshan = [row for row in rows if row["province"] == "浙江" and row["school"] == "中山大学"
                     and row["major_restriction"].startswith("0307 ")]
        self.assertEqual(len(zhongshan), 1)
        self.assertIn("中共党史、党的建设专业毕业生也可报考", zhongshan[0]["notes"])
        geology = [row for row in rows if row["province"] == "山东" and row["school"] == "中国地质大学（武汉）"]
        self.assertEqual(len(geology), 1)
        self.assertEqual(geology[0]["major_restriction"], "地质学、地质资源与地质工程")
        huaian = [row for row in rows if row["province"] == "江苏" and row["school"] == "淮安大学"]
        self.assertEqual(len(huaian), 1)
        self.assertEqual(huaian[0]["category"], "第二批/乡镇类别II")


if __name__ == "__main__":
    unittest.main()


class TestCivilServiceCompetition(unittest.TestCase):
    path = ROOT.parent / "zhiqu-career" / "data" / "civil-service-competition-2026.csv"

    def test_repository_table(self):
        issues, _ = validate_data.check_competition_file(self.path)
        self.assertEqual(issues, [])

    def test_rejects_non_monotone_quantiles(self):
        with self.path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        rows[0]["p25"] = str(float(rows[0]["p75"]) + 1)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "c.csv"
            with bad.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            issues, _ = validate_data.check_competition_file(bad)
        self.assertTrue(any("分位数没有递增" in x for x in issues))

    def test_no_row_level_job_data(self):
        with self.path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertLess(len(rows), 50)
        self.assertNotIn("job_code", rows[0])
