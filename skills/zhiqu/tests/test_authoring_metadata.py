"""写作模型缺失必须显式报错；渲染版本由真实代码字节得出。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from authoring_metadata import authoring_errors,trace_metadata
from planning_workflow import PlanningCase
import verify_report

class AuthoringMetadata(unittest.TestCase):
    def test_missing_invalid_or_blank_model_rejected(self):
        for case in ({},{'authoring':None},{'authoring':{'model':''}},{'authoring':{'model':42}},{'authoring':{'model':'  '}}):
            self.assertTrue(authoring_errors(case))
            with self.assertRaises(ValueError):trace_metadata(case,[])
    def test_historical_unknown_is_explicit_not_guessed(self):
        self.assertEqual(authoring_errors({'authoring':{'model':'未记录'}}),[])
    def test_model_version_and_actual_renderer_change_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'render.py';path.write_text('version one')
            case={'authoring':{'model':'Example Model 2026-10-20'}}
            before=trace_metadata(case,[path]);self.assertEqual(before['authoring'],case['authoring'])
            self.assertTrue(before['renderer']['version'].startswith('sha256:'))
            self.assertEqual(before,trace_metadata(case,[path]))
            path.write_text('version two');self.assertNotEqual(before['renderer']['version'],trace_metadata(case,[path])['renderer']['version'])
    def test_stage_zero_checks_missing_authoring(self):
        root=Path(__file__).resolve().parents[2]/'zhiqu-grad/examples/2027-YJ-S01'
        case=PlanningCase(root);case.case.pop('authoring',None)
        # need() returns the shared parsed case input.
        case.data['case.json']=case.case
        case.stage0();self.assertTrue(any('authoring.model' in error for error in case.errors))
    def test_gaokao_files_include_metadata_and_reject_missing_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);case={'case_id':'2026-GK-R01','authoring':{'model':'未记录'}}
            (root/'case.json').write_text(json.dumps(case));(root/'profile.json').write_text('{}');(root/'candidates.csv').write_text('id\n')
            result={'expected_utility':0,'p_fall':0};binding={'file':'profile.json'}
            with patch.object(verify_report,'candidate_file',return_value=root/'candidates.csv'):
                files=verify_report.gaokao_files(root,{},result,binding,root/'result.json')
                trace=json.loads(files['report_trace.json']);self.assertEqual(trace['authoring'],case['authoring']);self.assertIn('report.py',trace['renderer']['files_sha256'])
                case.pop('authoring');(root/'case.json').write_text(json.dumps(case))
                with self.assertRaisesRegex(ValueError,'authoring.model'):verify_report.gaokao_files(root,{},result,binding,root/'result.json')
