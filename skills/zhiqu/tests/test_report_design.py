"""Shared print components and publication gates: reject missing evidence, preserve values."""
import sys
import re
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report
import render_report
from check_report import check_publication_html


class PublicationGateTests(unittest.TestCase):
    def test_long_url_in_body_or_split_across_inline_nodes_is_rejected(self):
        url = 'https://example.edu.cn/' + 'a' * 45
        for content in (url, url[:25]+'<span>'+url[25:]+'</span>'):
            issues = check_publication_html('<section data-section="03"><p>'+content+'</p></section>')
            self.assertTrue(any('40字符' in x for x in issues))
        self.assertEqual(check_publication_html('<section data-section="12"><p>'+url+'</p></section>'), [])

    def test_scheme_less_long_url_after_chinese_is_rejected(self):
        """网址去掉 http 前缀、紧跟在中文机构名后面，也算正文长网址（2026-10-19 新闻表的问题）。"""
        doc = "<section data-section='03'><td>山东省教育招生考试院<span class='url'>sdzk.cn/NewsInfo.aspx?NewsID=7251&amp;BCID=1149&amp;CID=1120</span></td></section>"
        self.assertTrue(any("网址" in e for e in check_publication_html(doc)))

    def test_svg_needs_title_source_and_resolved_footnote(self):
        for svg in ('<svg></svg>', '<svg><title>图题</title></svg>',
                    '<svg data-source-refs="3"><title>图题</title></svg>'):
            self.assertTrue(check_publication_html(svg))
        chart = report.figure('分数参照',report.interval_chart([['普通计划',356,404,380]]),
                              '绿线为四分位区间，点为对照情景；不代表录取概率。','3')
        self.assertEqual(check_publication_html(chart+'<li id="source-3">官方统计</li>'), [])

    def test_missing_quartiles_are_not_drawn_as_zero(self):
        svg = report.interval_chart([['待核候选',None,None,None]])
        self.assertIn('区间未取到',svg)
        self.assertNotIn('<line ',svg)
        self.assertNotIn('<circle ',svg)
        with self.assertRaises(ValueError): report.interval_chart([['倒置',400,350,380]])

    def test_bars_keep_display_precision_and_reject_bad_scale(self):
        svg = report.bar_chart([['B省',.943,'保','约 95%']],maximum=1)
        self.assertIn('约 95%',svg)
        self.assertIn('311.19',svg)  # actual value .943, never rounded before plotting
        with self.assertRaises(ValueError): report.bar_chart([['负数',-2]])
        with self.assertRaises(ValueError): report.bar_chart([['超界',200]],maximum=100)

    def test_notes_deduplicate_and_compact_both_urls_and_links(self):
        notes = report.SourceNotes()
        url='https://school.edu.cn/'+'notice'*12
        n=notes.add('原始公告',url,'2026-10-19')
        fragment=notes.compact(f'<p>{url}；<a href="{url}">完整官网链接</a></p>')
        self.assertEqual(n,1)
        self.assertNotIn(url,fragment)
        self.assertEqual(fragment.count('[1]'),2)
        self.assertEqual(len(notes.entries),1)
        self.assertIn(url,notes.render())

    def test_number_typography_preserves_dates_codes_and_percentiles(self):
        self.assertEqual(report.public_text('预算25200元；530分可比较；120人；085801；2026-10-19；25%分位'),
                         '预算25,200 元；530 分可比较；120 人；085801；2026-10-19；25%分位')

    def test_readable_source_url_keeps_reserved_escapes(self):
        url='https://school.edu.cn/%E5%AD%A6%E8%B4%B9%2F2027.pdf'
        self.assertEqual(report.readable_url(url),'https://school.edu.cn/学费%2F2027.pdf')
        notes=report.SourceNotes();notes.add('收费',url)
        self.assertIn('href="'+url+'"',notes.render())
        self.assertIn('学费%2F2027.pdf',notes.render())

    def test_cover_has_exactly_six_cells_and_one_name_mark(self):
        cover=report.cover_html('读研路径决策报告','广东 · 2027','小林（模拟）','读研版 · 初试前','广东','2027-YJ-S01','2026-10-19','2026-10-19','4,000 次模拟中未出现滑档',[(i,str(i)) for i in range(1,13)])
        self.assertEqual(cover.count('<span>'),30)  # 6 metadata + 24 TOC cells
        self.assertEqual(cover.count('（模拟）'),1)
        self.assertIn('一句话结论',cover)
        self.assertNotIn('次模拟',cover)
        self.assertIn('次试算',cover)
        self.assertNotIn('备注',cover)
        with self.assertRaises(ValueError):
            report.cover_html('报告','','本人','说明'*20,'广东','1','2026-10-19','2026-10-19','结论',[])

    def test_markdown_fences_share_components_and_resolve_sources(self):
        body='''::: bars 年度费用
caption: 石绿为已列明的费用，单位元。
source: 1
unit: 元
- 学费 | 8000 | 主 | 8,000 元
:::
'''
        sections='\n\n'.join(f'## {i:02d} 标题{i}\n\n**本节结论。**\n\n'+(body if i==1 else '')+('::: sources\n- 当年收费标准 | https://school.edu.cn/fee | 2026-10-19\n:::' if i==12 else '') for i in range(1,13))
        html,_=render_report.render('---\nperson: 小林（模拟）\n---\n'+sections)
        self.assertEqual(check_publication_html(html),[])
        self.assertIn('<title>年度费用</title>',html)
        self.assertIn('8,000 元',html)
        with self.assertRaises(ValueError): render_report.render('---\nperson: 小林\n---\n'+sections.replace('source: 1','source: 9'))
        with self.assertRaises(ValueError): render_report.render('---\nperson: 小林\n---\n'+sections.replace('source: 1',''))


class UnifiedReportStyleTests(unittest.TestCase):
    def test_core_conclusions_keep_text_and_unify_bullets(self):
        output = report.core_conclusions(['费用：每年 8,000 元。', '按原口径保留 37% 结论。'])
        self.assertIn('<ul class="tight">', output)
        self.assertNotIn('<ol', output)
        self.assertIn('<strong>费用：</strong>每年 8,000 元。', output)
        self.assertIn('<strong>判断：</strong>按原口径保留 37% 结论。', output)

    def test_markdown_core_conclusions_use_same_component(self):
        output, _ = render_report.markdown_to_html('> [!key] 核心结论\n> - **费用**：8,000 元。\n> - 预算有限。')
        self.assertEqual(output, report.core_conclusions(['<strong>费用</strong>：8,000 元。', '预算有限。'], rendered=True))

    def test_appendix_has_extractable_escaped_evidence(self):
        output = report.verification_appendix_html({
            'case_info': [('案例号', '2027-YJ-S01')],
            'personal_inputs': [{'label': '预算', 'value': 30000, 'sections': '第 1 节'}],
            'numbers': [{'label': '学费', 'value': 8000, 'sections': '第 9 节',
                         'institution': '学校', 'url': 'https://school.edu.cn/fee', 'excerpt': '学费 8000 元/年。'}],
            'limitations': [{'claim': '<待核>', 'reason': '费用可能调整'}],
            'gaps': [{'label': '目录', 'reason': '验证码'}]})
        for text in ('本 PDF 附带数据文件', '学费 8000 元/年。', 'https://school.edu.cn/fee', '验证码', '&lt;待核&gt;'):
            self.assertIn(text, output)
        self.assertIn('data-section="appendix"', output)
        self.assertNotIn('<svg', output)

    def test_style_checker_rejects_drift(self):
        from check_report_styles import normalized_css
        rendered = report.CSS.replace('__TOPLEFT__', '知衢 · 高考决策报告').replace('__RUNHEAD__', '小明 · 2027-GK-S01')
        self.assertEqual(normalized_css(rendered), normalized_css(report.CSS))
        self.assertNotEqual(normalized_css(rendered.replace('font: 10pt/1.75', 'font: 11pt/1.75')), normalized_css(report.CSS))



class NumericRuns(unittest.TestCase):
    def test_numeric_prose_stays_whole_without_changing_text_or_link_targets(self):
        from html import unescape
        source='<section data-section="06"><p>2024—2025 学年，92.32%，447 人。</p><a href="https://example.edu.cn/2025">入口</a></section>'
        result=report.keep_numeric_runs(source)
        self.assertIn('<span class="number-run">2025</span>',result)
        self.assertIn('<span class="number-run">92.32%</span>',result)
        self.assertIn('href="https://example.edu.cn/2025"',result)
        self.assertEqual(re.sub('<[^>]+>','',unescape(source)),re.sub('<[^>]+>','',unescape(result)))

    def test_source_urls_and_svg_keep_their_own_print_rules(self):
        source='<svg><text x="20">2025</text></svg><section data-section="12">https://example.edu.cn/2025</section>'
        self.assertEqual(report.keep_numeric_runs(source),source)

if __name__ == '__main__':
    unittest.main()
