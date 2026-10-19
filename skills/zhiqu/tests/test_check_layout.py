"""check_layout.py：用人工排好的 PDF 检验版面自检能拦下坏版式、放过正常表格。"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

try:
    import pymupdf
except ImportError:  # 没装 PyMuPDF 的环境跳过
    pymupdf = None

import check_layout  # noqa: E402
import report  # noqa: E402

FONT = "china-s"


def make_pdf(path, rows):
    """rows: [(x, y, text)]，字号 8.8，模拟报告里的表格文字。"""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for x, y, text in rows:
        page.insert_text((x, y), text, fontsize=8.8, fontname=FONT)
    doc.save(path)


@unittest.skipIf(pymupdf is None, "需要 PyMuPDF")
class TestCheckLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "t.pdf")

    def tearDown(self):
        self.tmp.cleanup()

    def issues(self, rows):
        make_pdf(self.path, rows)
        return check_layout.check_pdf(self.path)

    def test_normal_table_passes(self):
        rows = []
        for i in range(12):  # 每行一条记录，行距 22pt：序号、志愿、冲稳保、位次
            y = 120 + 22 * i
            rows += [(56, y, str(i + 1)), (80, y, f"示例大学{i}组·计算机类"), (300, y, "冲稳保"[i % 3]), (360, y, "23,456")]
        rows += [(80, 420 + 15 * k, "这是一段正常宽度的说明文字，每行二十多个字，连续写好几行也没有问题。") for k in range(20)]
        self.assertEqual(self.issues(rows), [])

    def test_one_char_per_line_column_fails(self):
        rows = [(56, 130 + 15 * k, ch) for k, ch in enumerate("培养方案")]
        self.assertTrue(any("一字一行" in x for x in self.issues(rows)))

    def test_complete_percent_labels_in_compact_chart_are_not_split_digits(self):
        rows = [(460,130+14*k,t) for k,t in enumerate(['2%','3%','9%','2%'])]
        self.assertEqual(self.issues(rows), [])

    def test_approx_percent_column_is_not_squeezed_prose(self):
        rows = [(460,130+14*k,'约 20%') for k in range(10)]
        self.assertEqual(self.issues(rows), [])

    def test_split_number_fails(self):
        rows = [(56, 130, "1"), (56, 145, "6"), (80, 130, "华中农业大学-05组")]
        self.assertTrue(any("数字被拆成两行" in x for x in self.issues(rows)))

    def test_squeezed_chinese_column_fails(self):
        text = "现行为普通全日制本科生转专业管理办法全校性转专业只面向一年级绩点排名前百分之十可免笔试接收计划原则上不超过该专业一年级人数的百分之十须在四月底前完成" * 3
        rows = [(185, 130 + 15 * k, text[k * 10:(k + 1) * 10]) for k in range(len(text) // 10)]
        self.assertGreaterEqual(len(rows), 15)
        self.assertTrue(any("挤得很窄" in x for x in self.issues(rows)))

    def test_long_url_wrapping_is_allowed(self):
        url = "https://www.example.edu.cn/__local/D/67/01/C9A0C6E710BC41620E53F38F7CD_78101079_19346A.pdf" * 3
        rows = [(461, 130 + 15 * k, url[k * 16:(k + 1) * 16]) for k in range(16)]
        self.assertEqual(self.issues(rows), [])


class TestLayoutGate(unittest.TestCase):
    def test_gate_stops_on_issues(self):
        with patch("check_layout.check_pdf", return_value=["第 3 页：数字被拆成两行（16）"]), \
                patch("sys.stderr"), self.assertRaises(SystemExit):
            report.layout_gate("x.pdf")

    def test_gate_passes_clean_pdf(self):
        with patch("check_layout.check_pdf", return_value=[]), patch("builtins.print"):
            report.layout_gate("x.pdf")


if __name__ == "__main__":
    unittest.main()
