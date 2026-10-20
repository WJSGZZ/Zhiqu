"""公开层来源登记：sources.csv 格式与逐行 source_id（data-model.md）。"""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_data

DATA = ROOT / "data"


class TestSourcesCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.source = dict(source_id="demo-2025-physics-cutoff", grade="官方", publisher="某省教育考试院", title="投档情况",
                           file_url="https://example.gov.cn/a.pdf", landing_url="", published="", retrieved="2026-10-20",
                           archive_sha256="", archive_path="", archive_status="未取到", wayback_url="",
                           method="PDF 表格抽取", note="")

    def write(self, sources, rows):
        with open(self.dir / "sources.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=validate_data.SOURCE_FIELDS)
            w.writeheader()
            w.writerows(sources)
        (self.dir / "physics_2025.csv").write_text("code,name,score,rank,source_id\n" + "".join(rows), encoding="utf-8")
        return validate_data.check_sources(str(self.dir), ["physics_2025.csv"])[0]

    def test_registered_rows_pass(self):
        self.assertEqual(self.write([self.source], ["10001,北京大学,690,100,demo-2025-physics-cutoff\n"]), [])

    def test_unregistered_or_blank_source_fails(self):
        issues = self.write([self.source], ["10001,北京大学,690,100,demo-2025-physics-cutof\n", "10002,人民大学,680,200,\n"])
        self.assertTrue(any("2 行 source_id" in i for i in issues), issues)

    def test_bad_grade_date_and_duplicate_id_fail(self):
        bad = dict(self.source, grade="外购", retrieved="2026/10/20")
        issues = self.write([bad, self.source], ["10001,北京大学,690,100,demo-2025-physics-cutoff\n"])
        self.assertTrue(any("grade" in i for i in issues))
        self.assertTrue(any("retrieved" in i for i in issues))
        self.assertTrue(any("重复" in i for i in issues))

    def test_repository_layer_fully_sourced(self):
        provinces = [d for d in sorted(os.listdir(DATA)) if (DATA / d).is_dir() and d not in validate_data.SKIP_DIRS]
        for d in provinces:
            files = sorted(f for f in os.listdir(DATA / d) if f.endswith(".csv") and f != "sources.csv")
            with self.subTest(province=d):
                self.assertEqual(validate_data.check_sources(str(DATA / d), files)[0], [])
        self.assertEqual(validate_data.check_sources(str(DATA), list(validate_data.ROOT_SOURCED))[0], [])


if __name__ == "__main__":
    unittest.main()
