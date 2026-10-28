"""第三方参照按现有D级披露，逐值数字及等级不能在渲染时丢失。"""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import report
from check_report import check_report
from data_provenance import UNVERIFIED, evidence_lines


class ReportProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.rep = json.loads((ROOT / 'examples/2026-GK-R01/report.json').read_text())
        self.result = json.loads((ROOT / 'examples/2026-GK-R01/result.json').read_text())
        self.rep['meta'].update(prob_grade='D', grade_note='本次使用第三方历史数据，只作参照，不给概率')
        self.result['params']['rank'] = 1
        self.rep['meta']['rank'] = 1
        # 旧示例叙述含概率，这里只检查新增流程，不拿事后数据改例。
        for key in ('summary', 'why', 'list_notes', 'roadmap', 'ask_me'):
            self.rep.pop(key, None)
        self.rep['summary'] = {'headline': '本次仅作历史资料参照，实际方案须补核后再定。'}
        self.rep.pop('numeric_claims', None)
        self.rep['third_party_review'] = {}
        for index, item in enumerate(self.result['list']):
            fact = dict(value=20000 + index, grade='第三方整理',
                        display_grade='第三方整理·内部未核', source_id='vendor-test',
                        value_status='第三方整理未核', publisher='购买汇编', title='测试原表',
                        cross_check_summary={'scope': '本值同口径官方投档核对', 'checked': 0, 'inconsistent': 0},
                        completeness={'status': 'partial', 'missing_rows': [5]})
            item['data_provenance'] = {'2025': {'rank': fact}}
            item['source_grade'] = '第三方整理·内部未核'
            self.rep['third_party_review'][item['name']] = dict(
                disclosure=UNVERIFIED + '；仅作历史参照，不单独支撑主结论',
                margin='按原历史线留30%以上位次余量，另核两项可接受的保底')

    def test_d_does_not_draw_probability_weighted_strategy_with_negative_baseline(self):
        from unittest.mock import patch
        self.result['baseline_top_utility'] = [-1.725, .51725]
        self.result['stress']['expected_utility'] = -12.5
        with patch.object(report, 'strategy_chart', side_effect=AssertionError('D级不应绘制概率加权满意度')), patch.object(report,'outcome_strip',side_effect=AssertionError('D级不应靠色条宽度隐含录取概率')):
            rendered = report.build(self.rep, self.result)
        self.assertIn('暂不比较按录取概率加权的满意度', rendered)
        self.assertIn('压力测试的边界', rendered)
        self.assertIn('尚不能判断', rendered)
        self.assertIn('历史参照组数', rendered)
        self.assertNotIn('这张志愿表的期望效用为', rendered)

    def test_d_code_reference_is_not_a_fill_instruction_or_adjustment_consent(self):
        self.result['list'][0].update(group='501',limits='资格待核：选科要求待核',obey=True)
        rendered=report.build(self.rep,self.result)
        self.assertNotIn('这一页用来照着录入志愿填报系统',rendered)
        self.assertNotIn('冲：单独过线 &lt; 40%',rendered)
        self.assertNotIn('等单列的招生计划',rendered)
        self.assertIn('待本人确认',rendered)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sheet.csv';report.write_sheet(self.result,path)
            with path.open(encoding='utf-8-sig')as f:sheet=list(csv.DictReader(f))
            self.assertEqual(sheet[0]['服从调剂'],'待本人确认')
        legacy={'group':'501','obey':False}
        self.assertEqual(report.entry_adjustment(legacy),'否')
        known=dict(legacy,obey=True,data_provenance={'2025':{}},majors=[{'name':'已核专业'}])
        self.assertEqual(report.entry_adjustment(known),'是')

    def test_d_appendix_keeps_model_numbers_in_attachments_not_visible_table(self):
        import verify_report as verify
        from unittest.mock import patch
        before=copy.deepcopy(self.result)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'case.json').write_text(json.dumps({'case_id':'2027-GK-0001','mode':'simulation'}))
            source=ROOT/self.result['params']['csv']
            with patch.object(verify,'candidate_file',return_value=source):
                material=verify.gaokao_materials(root,self.rep,self.result,{'sha256':'fixture','file':'profile.json'})
                self.assertEqual(material['numbers'],[])
                self.assertTrue(any('原始条件模型计算仅留核对附件' in r['reason'] for r in material['limitations']))
                self.rep['meta']['prob_grade']='B'
                numeric=verify.gaokao_materials(root,self.rep,self.result,{'sha256':'fixture','file':'profile.json'})
                self.assertTrue(any(r['label']=='总概率核对'for r in numeric['numbers']))
        self.assertEqual(before,self.result)

    def test_d_qualitative_summary_is_still_checked_against_the_contract(self):
        rendered=report.build(self.rep,self.result)
        self.assertEqual(check_report(self.rep,self.result,rendered),[])
        tampered=rendered.replace('尚不能判断','已经稳录')
        self.assertTrue(any('摘要指标' in e for e in check_report(self.rep,self.result,tampered)))

    def test_pdf_html_sync_binds_exact_printed_document_without_losing_pdf_digest(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original={'artifacts':{'2027-GK-0001-report.pdf':'existing-pdf-sha'},'source_sha256':{'report.json':'unchanged-source'}}
            (root/'report_trace.json').write_text(json.dumps(original));(root/'report.html').write_text('过期旧版')
            document='<html><p>最终打印内容：尚不能判断</p></html>'
            report.sync_rendered_html(root,document)
            self.assertEqual((root/'report.html').read_bytes(),document.encode())
            trace=json.loads((root/'report_trace.json').read_text())
            self.assertEqual(trace['artifacts']['report.html'],hashlib.sha256(document.encode()).hexdigest())
            self.assertEqual(trace['artifacts']['2027-GK-0001-report.pdf'],'existing-pdf-sha')
            self.assertEqual(trace['source_sha256'],original['source_sha256'])

    def test_third_party_d_disclosure_and_margin_pass(self):
        self.assertEqual(check_report(self.rep, self.result), [])

    def test_missing_disclosure_or_margin_rejected(self):
        name = self.result['list'][0]['name']
        for key in ('disclosure', 'margin'):
            rep = copy.deepcopy(self.rep)
            del rep['third_party_review'][name][key]
            self.assertTrue(check_report(rep, self.result))

    def test_third_party_cannot_print_probabilities_as_grade_a(self):
        self.rep['meta']['prob_grade'] = 'A'
        self.assertTrue(any('D 级' in e for e in check_report(self.rep, self.result)))

    def test_direct_renderer_and_checker_keep_each_value_label(self):
        html = report.build(self.rep, self.result)
        self.assertEqual(check_report(self.rep, self.result, html), [])
        self.assertIn(UNVERIFIED, html)
        self.assertIn('本案数据评级', html)
        self.assertNotIn('大约有八成可能', html)
        self.assertIn('缺口', html)
        self.assertIn('不跨缺口换算', html)
        # 改来源等级而不改数字，也必须被HTML逐格核验拦下。
        changed = html.replace(UNVERIFIED, '官方', 1)
        self.assertTrue(check_report(self.rep, self.result, changed))
        lines = evidence_lines(self.result['list'][0])
        changed = html.replace(report.E(lines[0]), '历年明细未提供', 1)
        self.assertTrue(check_report(self.rep, self.result, changed))

    def test_sheet_displays_grade_source_and_original_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sheet.csv'
            report.write_sheet(self.result, path)
            with path.open(encoding='utf-8-sig') as source:
                rows = list(csv.DictReader(source))
            self.assertIn(UNVERIFIED, rows[0]['数据等级'])
            self.assertIn('20,000', rows[0]['历年数字与出处'])
            self.assertIn('vendor-test', rows[0]['历年数字与出处'])

    def test_score_official_does_not_upgrade_third_party_rank(self):
        item = self.result['list'][0]
        item['data_provenance']['2025']['score'] = dict(value=500, grade='官方',
            display_grade='官方', value_status='官方原值', source_id='official-score')
        del self.rep['third_party_review'][item['name']]
        self.assertTrue(check_report(self.rep, self.result))

    def test_missing_rank_provenance_and_fake_official_rejected(self):
        item = self.result['list'][0]
        item['data_provenance'] = {}
        self.assertTrue(check_report(self.rep, self.result))
        item['data_provenance'] = {'2025': {'rank': dict(value=1, grade='第三方整理',
            display_grade='官方', source_id='fake', value_status='第三方整理未核')}}
        self.assertTrue(check_report(self.rep, self.result))

    def test_official_consistency_needs_actual_check(self):
        fact = self.result['list'][0]['data_provenance']['2025']['rank']
        fact['display_grade'] = '官方一致'
        self.assertTrue(check_report(self.rep, self.result))

    def test_official_consistency_accepts_only_bound_same_scope_value(self):
        fact = self.result['list'][0]['data_provenance']['2025']['rank']
        fact['scope'] = {'province': '河南', 'year': 2025, 'subject': '物理', 'major': '测试专业'}
        fact['display_grade'] = '官方一致'
        fact['cross_check'] = dict(verdict='一致', field='rank', scope=fact['scope'],
            thirdparty_scope=fact['scope'], official_value=fact['value'], thirdparty_value=fact['value'],
            official_source={'grade': '官方', 'source_id': 'official-test', 'landing_url': 'https://example.edu.cn'},
            official_value_status={'status': '官方原值'},
            official_locator={'row': 7}, comparison_basis='同事实同口径逐值')
        self.assertEqual(check_report(self.rep, self.result), [])
        fact['cross_check']['official_value'] += 1
        self.assertTrue(check_report(self.rep, self.result))

    def test_official_consistency_cannot_use_derived_or_unknown_official_value(self):
        fact=self.result['list'][0]['data_provenance']['2025']['rank']
        fact['scope']={'province':'河南','year':2025,'subject':'物理','major':'测试专业'}
        fact['display_grade']='官方一致'
        fact['cross_check']=dict(verdict='一致',field='rank',scope=fact['scope'],
            thirdparty_scope=fact['scope'],official_value=fact['value'],thirdparty_value=fact['value'],
            official_source={'grade':'官方','source_id':'official-test','landing_url':'https://example.edu.cn'},
            official_locator={'row':7},comparison_basis='同事实同口径逐值')
        for state in [None,{},'官方原值','{"status":"官方原值"}',[],{'status':'推算'},{'status':'原件缺失'},
                      {'status':'待核'},{'status':'第三方已核一致'}]:
            with self.subTest(state=state):
                fact['cross_check']['official_value_status']=state
                self.assertTrue(any('官方一致缺' in e for e in check_report(self.rep,self.result)))
        for status in ['官方原值','人工更正']:
            fact['cross_check']['official_value_status']={'status':status}
            self.assertEqual(check_report(self.rep,self.result),[])
        del fact['cross_check']['official_value_status']
        self.assertTrue(any('官方一致缺' in e for e in check_report(self.rep,self.result)))

    def test_score_only_original_derived_rank_cannot_enter_new_report(self):
        fact=self.result['list'][0]['data_provenance']['2025']['rank']
        fact.update(grade='官方',display_grade='官方',value_status={'status':'推算','method':'投档分→同年同科一分一段累计'},
            original_scope={'source_format_reference':{'provided_fields':['score']}})
        for state in [{'status':'推算','method':'投档分→同年同科一分一段累计'},'推算']:
            fact['value_status']=state
            errors=check_report(self.rep,self.result)
            self.assertTrue(any('不能作为实际投档位次' in error for error in errors))
        # 仅标D级或另写余量不替代这项输入/口径核查。
        self.rep['meta']['prob_grade']='D'
        self.assertTrue(any('不能作为实际投档位次' in e for e in check_report(self.rep,self.result)))
        fact.pop('original_scope');fact['usage_gate']={'model_usable':False}
        self.assertTrue(any('不能作为实际投档位次' in e for e in check_report(self.rep,self.result)))

    def test_old_export_declared_cumulative_rank_is_rejected_without_format_key(self):
        from test_legacy_derived_rank_gate import legacy_fact
        fact=self.result['list'][0]['data_provenance']['2025']['rank']
        original_value=fact['value'];old=legacy_fact();old['value']=original_value;old['scope']={'year':2025}
        fact.clear();fact.update(old)
        errors=check_report(self.rep,self.result)
        self.assertTrue(any('重新导出' in e for e in errors))
        self.assertFalse(any('原表未公布' in e for e in errors))
        fact['grade']='第三方整理';fact['display_grade']='第三方整理·内部未核'
        self.assertTrue(any('不能作为实际投档位次' in e for e in check_report(self.rep,self.result)))

    def test_selection_gap_must_appear_in_report_and_not_count_as_confirmed(self):
        item=self.result['list'][0]
        item['data_provenance']['2025']['rank']['selection_review']={'status':'选科要求待核'}
        self.assertTrue(any('选科要求待核须进入资格限制' in e for e in check_report(self.rep,self.result)))
        item['limits']='资格待核：选科要求待核'
        html=report.build(self.rep,self.result)
        self.assertIn('需核对报名资格（选科要求待核）',html)
        self.assertEqual(check_report(self.rep,self.result,html),[])

    def test_third_party_without_check_scope_is_rejected(self):
        fact = self.result['list'][0]['data_provenance']['2025']['rank']
        del fact['cross_check_summary']
        self.assertTrue(check_report(self.rep, self.result))


if __name__ == '__main__':
    unittest.main()
