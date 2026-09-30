import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_report import check_report
from pipeline import merge_preferences
from audit_skill import local_links
import report


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = json.loads((ROOT / 'examples/case_b_zhejiang_2027/result.json').read_text())
        cls.rep = json.loads((ROOT / 'examples/case_b_zhejiang_2027/report.json').read_text())

    def test_report_detects_metadata_and_claim_drift(self):
        rep = copy.deepcopy(self.rep)
        rep['numeric_claims'] = [{'report_path': 'summary.headline', 'number_index': 0,
                                  'result_path': 'expected_utility', 'tolerance': 0.05}]
        rep['summary']['headline'] = f'平均满意度 {self.result["expected_utility"]:.1f}'
        self.assertEqual(check_report(rep, self.result), [])
        rep['summary']['headline'] = '平均满意度 999'
        rep['meta']['rank'] = 1
        self.assertEqual(len(check_report(rep, self.result)), 2)

    def test_html_table_detects_changed_probability_and_missing_rows(self):
        html = report.build(self.rep, self.result)
        self.assertEqual(check_report(self.rep, self.result, html), [])
        row = self.result['list'][0]
        old = f"<td class='r'>{row['p_clear']:.0%}</td>"
        changed = html.replace(old, "<td class='r'>999%</td>", 1)
        self.assertTrue(check_report(self.rep, self.result, changed))
        self.assertTrue(check_report(self.rep, self.result, '<html></html>'))
        tampered = html.replace('概率约 ', '概率错 ', 1)
        self.assertTrue(check_report(self.rep, self.result, tampered))

    def test_claim_percent_scaling_and_invalid_tolerance(self):
        rep = copy.deepcopy(self.rep)
        rep['summary']['headline'] = f'滑档概率 {100*self.result["p_fall"]:.2f}%'
        rep['numeric_claims'] = [{'report_path':'summary.headline', 'result_path':'p_fall', 'scale':100, 'tolerance':0.005}]
        self.assertEqual(check_report(rep, self.result), [])
        rep['numeric_claims'][0]['tolerance'] = -1
        self.assertTrue(check_report(rep, self.result))

    def test_preferences_cannot_replace_facts_or_use_stale_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pool, prefs, out = [base / x for x in ('pool.csv', 'prefs.csv', 'out.csv')]
            pool.write_text('id,name,rank_2026\nx,示例,20000\ny,其他,30000\n')
            prefs.write_text('id,utility,rank_2026\nx,80,1\n')
            with self.assertRaisesRegex(ValueError, '历史事实'):
                merge_preferences(pool, prefs, out)
            prefs.write_text('id,utility\nz,80\n')
            with self.assertRaisesRegex(ValueError, '旧候选池'):
                merge_preferences(pool, prefs, out)
            prefs.write_text('id,utility\nx,80\n')
            merge_preferences(pool, prefs, out)
            self.assertNotIn('其他', out.read_text())
            self.assertIn('20000', out.read_text())

    def test_pipeline_runs_all_stages_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'output'
            command = [sys.executable, str(ROOT / 'scripts/pipeline.py'), str(ROOT / 'examples/pipeline_demo/config.json'), '--out-dir', str(out)]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            for name in ('pool.csv','reviewed.csv','predicted.csv','result.json','report.html'):
                self.assertTrue((out / name).is_file())
            result = json.loads((out / 'result.json').read_text())
            rep = json.loads((ROOT / 'examples/pipeline_demo/report.json').read_text())
            self.assertEqual(check_report(rep, result, (out / 'report.html').read_text()), [])
            self.assertEqual(len(result['list']), 6)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('已有内容', second.stderr)

    def test_all_local_document_file_links_exist(self):
        errors, _ = local_links()
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
