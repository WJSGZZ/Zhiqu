"""render_report.py 的自动测试（只用标准库）。

运行：在 skills/zhiqu 目录下执行
  python3 -m unittest discover -s tests -v
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import render_report as rr  # noqa: E402


SAMPLE_MD = """---
title: 虚构示例报告
subtitle: 读研方向决策
person: 虚构示例 · 小周
date: 2026-09-30
edition: 读研版
note: 这是测试用的虚构样例
---

## 01 摘要

这是**加粗**、*斜体*、`代码` 和链接 [知衢](https://example.com/zhiqu) 的段落。

> 这是一段引用，提醒读者核对官方信息。

- 第一条
- 第二条
  - 嵌套 A
  - 嵌套 B
- 第三条

1. 步骤一
2. 步骤二

| 方面 | 情况 |
|---|---|
| 学历 | 本科 |
| 目标 | 读研 |

---

### 小标题

一段包含 <script>alert(1)</script> 的文本，用来测试转义。

## 02 你的画像

内容占位。

## 03 你看重什么、卡在哪

内容占位。

## 04 候选方向

内容占位。

## 05 方向比较

内容占位。

## 06 目标岗位清单

内容占位。

## 07 时间窗口与检查点

内容占位。

## 08 行动路线

内容占位。

## 09 offer 比较

内容占位。

## 10 风险与权益

内容占位。

## 11 追问清单

内容占位。

## 12 方法、数据来源与声明

内容占位。
"""


class TestMarkdownToHtml(unittest.TestCase):
    def setUp(self):
        self.meta, self.body = rr.split_front_matter(SAMPLE_MD)
        self.html, self.sections = rr.markdown_to_html(self.body)

    def test_front_matter_parsed(self):
        self.assertEqual(self.meta["title"], "虚构示例报告")
        self.assertEqual(self.meta["person"], "虚构示例 · 小周")
        self.assertEqual(self.meta["edition"], "读研版")
        self.assertEqual(self.meta["note"], "这是测试用的虚构样例")

    def test_headings_and_sections(self):
        nums = [n for n, _, _ in self.sections]
        self.assertEqual(nums, [f"{i:02d}" for i in range(1, 13)])
        self.assertIn('<span class=\'no\'>01</span>', self.html)
        self.assertIn("摘要", self.html)

    def test_inline_formatting(self):
        self.assertIn("<strong>加粗</strong>", self.html)
        self.assertIn("<em>斜体</em>", self.html)
        self.assertIn("<code>代码</code>", self.html)
        self.assertIn('<a href="https://example.com/zhiqu">知衢</a>', self.html)

    def test_blockquote(self):
        self.assertIn("<blockquote><p>这是一段引用", self.html)

    def test_lists_with_one_level_nesting(self):
        self.assertIn("<li>第一条</li>", self.html.replace("\n", ""))
        self.assertIn("嵌套 A", self.html)
        self.assertIn("<ol>", self.html)  # 步骤一/二 有序列表
        # 嵌套子列表应出现在"第二条"这一 <li> 内部
        idx_second = self.html.find("第二条")
        idx_nested = self.html.find("嵌套 A")
        idx_third = self.html.find("第三条")
        self.assertTrue(idx_second < idx_nested < idx_third)

    def test_table(self):
        self.assertIn("<table>", self.html)
        self.assertIn("<th>方面</th>", self.html)
        self.assertIn("<td>本科</td>", self.html)

    def test_horizontal_rule(self):
        self.assertIn("<hr>", self.html)

    def test_subheading(self):
        self.assertIn("<h3>小标题</h3>", self.html)

    def test_html_is_escaped_not_passed_through(self):
        self.assertNotIn("<script>", self.html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", self.html)


class TestReportElements(unittest.TestCase):
    """与 report.py 同款的版面元素：提示框、数字卡、落点条、冲稳保标签。"""

    MD = "\n".join([
        "::: kpi",
        "- 志愿数 | 21 | 可填 80 个",
        "- 最可能的去向 | 浙江外国语学院·汉语言文学（师范） | 约 73%",
        ":::",
        "",
        "::: strip",
        "source: 1",
        "- 甲校 | 20%",
        "- 乙校 | 79.5%",
        "- 滑档 | 0.5%",
        ":::",
        "",
        "> [!key] 核心结论",
        "> 1. 第一条",
        "> 2. 第二条",
        "",
        "> [!warn] 下一个检查点",
        "> 出分后重算。",
        "",
        "| 序 | 标签 |",
        "|---|---|",
        "| 1 | 冲 |",
    ])

    def setUp(self):
        self.html, _ = rr.markdown_to_html(self.MD)

    def test_kpi_cards(self):
        self.assertIn('<div class="kpis" style="grid-template-columns:repeat(2,1fr)">', self.html)
        self.assertIn('<span class="num">21</span>', self.html)
        self.assertIn('<span style="font-size:11pt">浙江外国语学院', self.html)  # 汉字多的值用小一号

    def test_outcome_strip(self):
        self.assertIn('<svg class="chart"', self.html)
        self.assertIn("你最终会被哪里录取", self.html)
        self.assertIn("红色是滑档", self.html)

    def test_callout_boxes(self):
        self.assertIn('<div class="box key core-conclusions"><h4>核心结论</h4><ul class="tight"><li><strong>判断：</strong>第一条</li>', self.html)
        self.assertIn('<div class="box warn"><h4>下一个检查点</h4><p>出分后重算。</p></div>', self.html)
        self.assertNotIn("[!key]", self.html)

    def test_tag_cells(self):
        self.assertIn("<span class='tag 冲'>冲</span>", self.html)


class TestNeutralColorNames(unittest.TestCase):
    """读研、求职图表的色名不借用高考冲/稳/保：色名会留在 report.md 和 PDF 附件数据里。"""

    def bars(self, tag):
        return "\n".join(["::: bars 情景", "caption: 说明", "source: 1", f"- 原估计 | 2 | 主 | 2.0 个月", f"- 情景 | 1 | {tag} | 1.0 个月", ":::"])

    def test_neutral_names_render_with_the_same_colors(self):
        import report
        for neutral, legacy in (("留意", "稳"), ("不利", "冲")):
            html_, _ = rr.markdown_to_html(self.bars(neutral))
            self.assertIn(report.PALETTE[legacy], html_)
        html_, _ = rr.markdown_to_html(self.bars("次"))
        self.assertIn(report.PALETTE["保"], html_)

    def test_gaokao_tiers_are_refused_as_chart_colors(self):
        for tag in ("冲", "稳", "保"):
            with self.assertRaisesRegex(ValueError, "高考档位"):
                rr.markdown_to_html(self.bars(tag))

    def test_examples_do_not_carry_gaokao_tier_color_names(self):
        import glob
        import json
        import re
        skills = os.path.dirname(ROOT)
        roots = sorted(glob.glob(os.path.join(skills, "zhiqu-grad/examples/*")) + glob.glob(os.path.join(skills, "zhiqu-career/examples/*")))
        self.assertTrue(roots)
        found = []

        def walk(obj, where):
            if isinstance(obj, dict):
                if obj.get("type") in ("bars",) and isinstance(obj.get("content"), dict):
                    for row in obj["content"].get("rows", []):
                        if len(row) > 2 and row[2] in ("冲", "稳", "保"):
                            found.append((where, row[0], row[2]))
                for value in obj.values():
                    walk(value, where)
            elif isinstance(obj, list):
                for value in obj:
                    walk(value, where)

        for root in roots:
            for path in glob.glob(os.path.join(root, "*.json")):
                walk(json.load(open(path, encoding="utf-8")), path)
            md = os.path.join(root, "report.md")
            if os.path.exists(md):
                for block in re.findall(r"^::: bars[^\n]*\n(.*?)^:::", open(md, encoding="utf-8").read(), re.M | re.S):
                    for line in block.splitlines():
                        cells = [c.strip() for c in re.sub(r"^\s*-\s+", "", line).split("|")] if line.lstrip().startswith("- ") else []
                        if len(cells) > 2 and cells[2] in ("冲", "稳", "保"):
                            found.append((md, cells[0], cells[2]))
        self.assertEqual(found, [])


class TestValidation(unittest.TestCase):
    def test_well_ordered_sections_no_warning(self):
        _, sections = rr.markdown_to_html(rr.split_front_matter(SAMPLE_MD)[1])
        buf = io.StringIO()
        with redirect_stderr(buf):
            rr.validate_sections(sections)
        self.assertEqual(buf.getvalue(), "")

    def test_out_of_order_sections_warn(self):
        bad_md = "## 01 摘要\n\n占位\n\n## 03 顺序错了\n\n占位\n"
        _, sections = rr.markdown_to_html(bad_md)
        buf = io.StringIO()
        with redirect_stderr(buf):
            rr.validate_sections(sections)
        self.assertIn("提醒", buf.getvalue())
        self.assertIn("01..12", buf.getvalue())

    def test_missing_numbers_warn(self):
        bad_md = "## 摘要（没写编号）\n\n占位\n"
        _, sections = rr.markdown_to_html(bad_md)
        buf = io.StringIO()
        with redirect_stderr(buf):
            rr.validate_sections(sections)
        self.assertIn("提醒", buf.getvalue())


class TestFullRender(unittest.TestCase):
    def test_render_includes_cover_toc_and_css(self):
        doc, sections = rr.render(SAMPLE_MD)
        self.assertIn("知其所往，方行其衢。", doc)
        self.assertIn("虚构示例报告", doc)
        self.assertIn("小周（模拟）", doc)
        self.assertIn('class="toc"', doc)
        self.assertIn("<style>", doc)
        # CSS 应来自 report.py（颜色、封面等复用）
        self.assertIn("--accent2:#34685D", doc)
        self.assertEqual(len(sections), 12)

    def test_maintainer_comments_are_not_rendered(self):
        doc, _ = rr.render(SAMPLE_MD.replace("内容占位。", "学费 8000 元 <!-- 核实：2026-10-17；复核期限：2027-07-01 -->", 1))
        self.assertIn("学费 8,000 元", rr.re.sub(r"<[^>]+>", "", doc))
        self.assertNotIn("复核期限", doc)

    def test_render_html_via_cli(self):
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "r.md")
            with open(src, "w", encoding="utf-8") as f:
                f.write(SAMPLE_MD)
            out = os.path.join(d, "r.html")
            p = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "render_report.py"), src, "--out", out],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(out, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("虚构示例报告", html)
            self.assertIn("知其所往，方行其衢。", html)


if __name__ == "__main__":
    unittest.main()
