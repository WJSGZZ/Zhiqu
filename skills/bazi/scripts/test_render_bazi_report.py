#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("render_bazi_report.py")
SPEC = importlib.util.spec_from_file_location("render_bazi_report", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RenderReportTests(unittest.TestCase):
    def fixture(self):
        return {
            "meta": {
                "title": "甲子 · 乙丑 · 丙寅 · 丁卯",
                "analysis_date": "2026-08-05",
                "chart_label": "甲子 · 乙丑 · 丙寅 · 丁卯",
                "calendar_note": "测试口径",
                "model_version": "test@1",
                "status_tags": ["3/4柱已知", "时柱待补"],
            },
            "summary": {
                "verdict": "这是测试结论。",
                "confidence": "中",
                "key_mechanism": "测试机制。",
                "strongest_objection": "测试异议。",
            },
            "chart": {"columns": ["年", "月"], "rows": [{"label": "天干", "values": ["甲", "乙"]}]},
            "domains": [{"name": "研究", "fit": 78, "mechanism": "机制", "suitable_roles": ["分析"]}],
            "luck_cycles": [{"name": "第一运", "ganzhi": "戊辰", "years": "2030-2039", "summary": "运势摘要", "years_detail": [{"year": 2030, "ganzhi": "庚戌", "summary": "年份摘要"}]}],
        }

    def test_render_is_portable_and_escaped(self):
        data = self.fixture()
        data["summary"]["verdict"] = "<script>alert(1)</script>"
        rendered = MODULE.render(data)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("data-action=\"print\"", rendered)
        self.assertIn("data-search", rendered)
        self.assertIn("data-action=\"menu\"", rendered)
        self.assertIn("3/4柱已知", rendered)
        self.assertIn('<span class="pillar">甲子</span><span class="pillar">乙丑</span>', rendered)
        self.assertIn("第一运", rendered)
        self.assertIn("@media print", rendered)
        self.assertNotIn("https://", rendered)

    def test_required_fields(self):
        with self.assertRaisesRegex(ValueError, "meta.title"):
            MODULE.render({"meta": {"analysis_date": "x", "chart_label": "x"}, "summary": {"verdict": "x", "confidence": "中"}})

    def test_writes_utf8_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            output.write_text(MODULE.render(self.fixture()), encoding="utf-8")
            text = output.read_text(encoding="utf-8")
            self.assertIn("甲子", text)
            self.assertIn("甲子", text)


if __name__ == "__main__":
    unittest.main()
