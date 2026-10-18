"""入学后机会表的来源与复核日期校验。"""
import csv
from collections import defaultdict
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_data

COMPLETED_PROVINCES = ("江苏省",)


def source_omission_conflicts(rows):
    """提示同一原文被拆行后的信息遗漏，不判断不同项目的政策范围。"""
    by_source = defaultdict(list)
    for line, row in enumerate(rows, 2):
        if row["status"] == "verified":
            by_source[row["source_url"]].append((line, row))
    conflicts = []
    for source, group in by_source.items():
        for field in ("seats", "selection_time", "eligibility"):
            unknown = [(line, row) for line, row in group
                       if row[field].strip() in {"原文未说明", "未取到"}]
            specific = [(line, row) for line, row in group
                        if row[field].strip() not in {"原文未说明", "未取到", "未查到", ""}
                        and not ("未取" in row[field] or "见附件" in row[field])]
            if unknown and specific:
                conflicts.append({
                    "source_url": source, "field": field,
                    "generic_unknown": [{"line": line, "school": row["school"],
                                         "type": row["opportunity_type"],
                                         "project": row["project_name"], "value": row[field]}
                                        for line, row in unknown],
                    "specific": [{"line": line, "school": row["school"],
                                  "type": row["opportunity_type"],
                                  "project": row["project_name"], "value": row[field]}
                                 for line, row in specific],
                })
    return conflicts


class TestAfterEntryData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "after-entry-opportunities.csv"
        self.row = dict.fromkeys(validate_data.AFTER_ENTRY_FIELDS, "待查")
        self.row.update(school="模拟大学", province="江苏", opportunity_type="转专业",
                        source_url="https://jwc.example.edu.cn/policy/1.html",
                        verified_date="2026-10-18", review_deadline="2027-09-30",
                        status="verified")

    def write(self, row=None, fields=None):
        with self.path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields or validate_data.AFTER_ENTRY_FIELDS,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerow(self.row if row is None else row)

    def check(self, **updates):
        self.write(dict(self.row, **updates))
        return validate_data.check_after_entry_file(self.path)[0]

    def test_valid_rows_and_all_evidence_statuses(self):
        for status in sorted(validate_data.AFTER_ENTRY_STATUSES):
            with self.subTest(status=status):
                self.assertEqual(self.check(status=status), [])
        self.assertEqual(self.check(review_deadline="2026-10-18"), [])

    def test_url_is_required_and_must_have_web_scheme_and_hostname(self):
        for source in ("", "   ", "jwc.example.edu.cn/policy", "https:///policy",
                       "ftp://jwc.example.edu.cn/policy", "https://[broken"):
            with self.subTest(source=source):
                self.assertTrue(any("source_url" in issue for issue in self.check(source_url=source)))

    def test_dates_require_iso_format_and_real_calendar_date(self):
        for field in ("verified_date", "review_deadline"):
            for value in ("", "2026/10/18", "2026-1-18", "2026-02-30", "0000-10-18"):
                with self.subTest(field=field, value=value):
                    issues = self.check(**{field: value})
                    self.assertTrue(any(field in issue for issue in issues), issues)

    def test_review_cannot_precede_verification(self):
        self.assertTrue(any("早于" in issue for issue in self.check(review_deadline="2026-10-17")))

    def test_missing_columns(self):
        fields = [field for field in validate_data.AFTER_ENTRY_FIELDS if field != "source_url"]
        self.write(fields=fields)
        issues, _ = validate_data.check_after_entry_file(self.path)
        self.assertTrue(any("表头" in issue and "source_url" in issue for issue in issues))

    def test_unknown_status_and_required_labels(self):
        self.assertTrue(any("status 未知" in issue for issue in self.check(status="pending")))
        for field in ("school", "province", "opportunity_type", "status"):
            with self.subTest(field=field):
                self.assertTrue(any(field in issue for issue in self.check(**{field: ""})))

    def test_missing_or_empty_file(self):
        self.assertTrue(validate_data.check_after_entry_file(self.path)[0])
        self.path.write_text(",".join(validate_data.AFTER_ENTRY_FIELDS) + "\n", encoding="utf-8")
        self.assertTrue(validate_data.check_after_entry_file(self.path)[0])

    def test_cli_includes_table_even_with_explicit_province(self):
        data = Path(self.tmp.name)
        (data / "schools.csv").write_text("code,name\n10001,模拟大学\n", encoding="utf-8")
        (data / "jiangsu").mkdir()
        self.write(dict(self.row, source_url=""))
        for provinces in ([], ["jiangsu"]):
            with self.subTest(provinces=provinces), patch.object(validate_data, "DATA", str(data)), \
                    patch.object(sys, "argv", ["validate_data.py", *provinces]), \
                    redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as result:
                    validate_data.main()
                self.assertEqual(result.exception.code, 1)
                self.assertIn("source_url", output.getvalue())
                self.assertIn("共 1 个需要处理的问题", output.getvalue())

    def test_repository_table(self):
        issues, _ = validate_data.check_after_entry_file(ROOT / "data" / "after-entry-opportunities.csv")
        self.assertEqual(issues, [])

    def test_repository_has_no_research_placeholders_or_local_paths(self):
        text = (ROOT / "data" / "after-entry-opportunities.csv").read_text(encoding="utf-8")
        for placeholder in ("text_path", "raw_path", "/tmp/", "/Users/", "以text_path前40行为准"):
            with self.subTest(placeholder=placeholder):
                self.assertFalse(placeholder in text, f"机会表仍含调研占位内容：{placeholder}")

    def test_completed_provinces_public_undergraduate_coverage_and_four_categories(self):
        with (ROOT / "data" / "schools.csv").open(encoding="utf-8-sig", newline="") as f:
            schools = list(csv.DictReader(f))
        with (ROOT / "data" / "after-entry-opportunities.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        categories = {"二次选拔", "大类分流", "转专业", "贯通与双学位"}
        for province in COMPLETED_PROVINCES:
            expected = {
                row["name"] for row in schools
                if row["province"] == province and row["level"] == "本科"
                and not any(label in (row.get("note") or "")
                            for label in ("民办", "独立学院", "合作办学"))
            }
            province_rows = [row for row in rows if row["province"] == province]
            with self.subTest(province=province):
                self.assertTrue(expected, "已完成省份须能从学校基表筛出公办本科")
                self.assertEqual({row["school"] for row in province_rows}, expected)
            for school in sorted(expected):
                with self.subTest(province=province, school=school):
                    self.assertEqual({row["opportunity_type"] for row in province_rows
                                      if row["school"] == school}, categories)

    def test_same_source_does_not_mix_specific_rules_with_generic_unknowns(self):
        with (ROOT / "data" / "after-entry-opportunities.csv").open(encoding="utf-8-sig", newline="") as f:
            conflicts = source_omission_conflicts(list(csv.DictReader(f)))
        self.assertEqual(conflicts, [],
                         "同一来源已有具体值时须复核精确的‘原文未说明/未取到’；"
                         "若属不同项目，请在字段里写清所指项目与未说明范围")

    def test_unknown_evidence_has_search_scope_or_retrieval_reason(self):
        with (ROOT / "data" / "after-entry-opportunities.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            if row["status"] not in {"not_found", "unretrieved"}:
                continue
            with self.subTest(school=row["school"], category=row["opportunity_type"], project=row["project_name"]):
                notes = row["notes"].strip()
                if row["status"] == "not_found":
                    self.assertIn("未查到", notes)
                    self.assertRegex(notes, r"已查[：:]\s*[^；）]{3,}",
                                     "未查到必须说明实际查过的页面或栏目")
                else:
                    self.assertRegex(notes, r"未取到|等待手动取文")
                    self.assertRegex(notes, r"超时|验证码|HTTP|HTTPS|SSL|TLS|连接|拒绝|拦截|正文[（(]\d{3}[）)]|无法解析|需登录|空壳|下载失败|打不开|空白页|空响应|HTML",
                                     "未取到必须说明正文未能取得的具体原因")
                self.assertNotRegex(notes, r"(?:^|[；。])(?:该校|学校)?(?:没有|不存在|不提供)",
                                    "未查到或未取到不能直接写成学校没有该机会")


if __name__ == "__main__":
    unittest.main()
