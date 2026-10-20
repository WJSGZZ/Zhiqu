"""读者用语检查只覆盖明确规则，不能冒充通用语义检查。"""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import reader_language as language

class ReaderLanguage(unittest.TestCase):
    def check(self,text,**kw):return language.check_fragments([language.Fragment(text,'03','sections.03.content')],**kw)
    def test_section_twelve_exempt_but_eleven_checked(self):
        issues=language.check_html('<section data-section="11"><p>用脚本复现。</p></section><section data-section="12"><p>附件 calculations.json 快照。</p></section>')
        self.assertEqual({i['term'] for i in issues},{'脚本','复现'})
        self.assertEqual({i['section'] for i in issues},{'11'})
    def test_developer_terms_each_injected(self):
        for term in ('返工','复现','演示','脚本','快照','calculations.json','compute.py','字段路径','/budget/annual'):
            self.assertTrue(self.check('本报告的'+term+'在这里。'),term)
    def test_career_context_requires_review_not_blanket_pass(self):
        issues=self.check('你在软件开发岗位需要写脚本处理数据。')
        self.assertEqual(issues[0]['severity'],'needs_review')
        self.assertEqual(self.check('脚本显示录取范围。')[0]['severity'],'error')
    def test_reference_placeholders_are_not_visible_internal_ids(self):
        data={'sections':{'03':{'node':{'type':'paragraph','content':{'text':'费用 {{e:E035#/value}} 元。'},'evidence_refs':['E035']}}}}
        self.assertEqual(language.check_fragments(language.json_fragments(data)),[])
        self.assertTrue(self.check('具体见E035。'))
    def test_terminology_different_real_concepts_unchanged(self):
        self.assertEqual(self.check('税前年薪20万元，扣税前收入有波动。'),[])
        self.assertEqual(self.check('官方原文公布的群体统计录取率为20%。'),[])
        self.assertEqual(self.check('住房是每月主要支出，收入另作核算。'),[])
        self.assertTrue(any(i['code']=='inconsistent_term' for i in self.check('本志愿模型的过线概率为20%。')))
    def test_first_occurrence_explained_or_glossary_defined(self):
        self.assertEqual(self.check('ROI（投入产出比）只作辅助。'),[])
        self.assertEqual(self.check('蒙特卡洛，即随机试算很多种可能结果。'),[])
        self.assertTrue(any(i['code']=='unexplained_term' for i in self.check('本例用蒙特卡洛。')))
        self.assertEqual(self.check('本例用蒙特卡洛。',glossary={'蒙特卡洛试算':'随机试算结果。'}),[])
        self.assertEqual(self.check('今天先比较学校与专业。'),[])
    def test_glossary_html_definition_is_used(self):
        html='<section data-section="03"><p>比较期望效用。</p></section><section data-section="10"><div class="box glossary"><dl><dt>期望效用</dt><dd>各结果加权后的平均满意度。</dd></dl></div></section>'
        self.assertEqual(language.check_html(html),[])
    def test_json_content_location_and_section(self):
        issues=language.check_fragments(language.json_fragments({'sections':{'11':{'lead':{'type':'paragraph','content':{'text':'脚本结果。'}}},'12':{'text':'脚本'}}}))
        self.assertEqual(len(issues),1);self.assertEqual(issues[0]['location'],'sections.11.lead.content.text')
    def test_html_split_spans_keep_words_and_table_codes_reviewable(self):
        issues=language.check_html('<section data-section="03"><p>快<span>照</span></p><table><tr><th>序</th><th>院校代码</th><th>院校</th></tr><tr><td>1</td><td>E100</td><td>某某大学</td></tr></table></section>')
        self.assertEqual(issues[0]['term'],'快照');self.assertEqual(len(issues),1)
        self.assertTrue(language.check_html('<section data-section="03"><p>见E100。</p></section>'))
    def test_pdf_location_survives(self):
        issue=language.check_fragments([language.Fragment('演示结果。','04','PDF',page=5)])[0]
        self.assertEqual(issue['page'],5)

if __name__=='__main__':unittest.main()
