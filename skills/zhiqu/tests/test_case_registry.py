"""Closed public example registration and profile binding; no private-directory scan."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'))
from family_check import check_case_registry


class PublicRegistry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'skills/zhiqu-grad/examples/demo'
        self.folder.mkdir(parents=True)
        self.case = {'case_id':'2027-YJ-S01'}
        self.record = {'case_id':'2027-YJ-S01','directory':str(self.folder.relative_to(self.root)), 'reports':[]}
        self.registry = self.root / 'skills/zhiqu-shared/references/cases.json'
        self.registry.parent.mkdir(parents=True)
        self.write()

    def write(self, records=None):
        (self.folder / 'case.json').write_text(json.dumps(self.case))
        self.registry.write_text(json.dumps({'schema':1,'cases':records if records is not None else [self.record]}))

    def test_valid_registry_and_binding_pass(self):
        raw = '{"fictional":true}\n';(self.folder / 'profile_snapshot.json').write_text(raw)
        binding = {'file':'profile_snapshot.json','sha256':hashlib.sha256(raw.encode()).hexdigest(),'filled_at':None}
        self.case['report_profile'] = binding;self.record['profile'] = dict(binding);self.write()
        self.assertEqual(check_case_registry(self.root), [])
        # An unregistered private tree is deliberately outside the scan.
        private = self.root / 'cases/2027-YJ-0001';private.mkdir(parents=True)
        (private / 'case.json').write_text('{}')
        self.assertEqual(check_case_registry(self.root), [])

    def deliverable(self):
        raw=b'{"fictional":true}';(self.folder/'profile.json').write_bytes(raw)
        binding={'file':'profile.json','sha256':hashlib.sha256(raw).hexdigest(),'filled_at':None}
        self.case['report_profile']=binding;self.record['profile']=dict(binding)
        pdf=self.folder/'report.pdf';pdf.write_bytes(b'fictional-pdf-bytes-for-hash-check-only')
        name=str(pdf.relative_to(self.root));self.record['reports']=[name]
        self.record['report_versions']=[{'file':name,'generated_at':'2026-10-19T12:00:00+08:00','version':'1',
            'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'profile_sha256':binding['sha256']}]
        self.write();return pdf

    def test_deliverable_version_fingerprints_pass_and_half_case_needs_no_version(self):
        self.assertEqual(check_case_registry(self.root), [])
        self.deliverable()
        self.assertEqual(check_case_registry(self.root), [])

    def test_deliverable_requires_explicit_report_binding(self):
        self.deliverable();self.case['profile']=self.case.pop('report_profile');self.write()
        self.assertTrue(any('必须绑定 case.report_profile' in x[3] for x in check_case_registry(self.root)))

    def test_each_deliverable_requires_one_complete_version_entry(self):
        self.deliverable()
        for field in ('file','generated_at','version','sha256','profile_sha256'):
            with self.subTest(field=field):
                saved=self.record['report_versions'][0].pop(field);self.write()
                self.assertTrue(check_case_registry(self.root))
                self.record['report_versions'][0][field]=saved
        self.record['report_versions']=[];self.write()
        self.assertTrue(any('缺版本登记' in x[3] for x in check_case_registry(self.root)))
        self.record.pop('report_versions');self.write()
        self.assertTrue(any('缺 report_versions' in x[3] for x in check_case_registry(self.root)))

    def test_changed_pdf_and_wrong_profile_version_are_rejected(self):
        pdf=self.deliverable();pdf.write_bytes(b'changed-pdf')
        self.assertTrue(any('报告文件指纹' in x[3] for x in check_case_registry(self.root)))
        self.record['report_versions'][0]['sha256']=hashlib.sha256(pdf.read_bytes()).hexdigest()
        self.record['report_versions'][0]['profile_sha256']='0'*64;self.write()
        self.assertTrue(any('报告版本画像指纹' in x[3] for x in check_case_registry(self.root)))

    def test_duplicate_version_and_timezone_free_generation_are_rejected(self):
        self.deliverable();self.record['report_versions'].append(dict(self.record['report_versions'][0]));self.write()
        self.assertTrue(any('重复登记版本' in x[3] for x in check_case_registry(self.root)))
        self.record['report_versions']=self.record['report_versions'][:1]
        self.record['report_versions'][0]['generated_at']='2026-10-19T12:00:00';self.write()
        self.assertTrue(any('时间须含时区' in x[3] for x in check_case_registry(self.root)))

    def test_duplicate_and_missing_registration_fail(self):
        self.write([self.record,self.record])
        self.assertTrue(any('重号' in x[3] for x in check_case_registry(self.root)))
        self.write([])
        self.assertTrue(any('未登记' in x[3] for x in check_case_registry(self.root)))

    def test_missing_case_id_and_dead_registration_fail(self):
        self.case.pop('case_id');self.write()
        self.assertTrue(any('缺少 case_id' in x[3] for x in check_case_registry(self.root)))
        self.record['directory'] = 'skills/zhiqu-grad/examples/absent';self.write()
        self.assertTrue(any('不存在' in x[3] for x in check_case_registry(self.root)))

    def test_different_directories_cannot_reuse_id(self):
        other = self.folder.parent / 'other';other.mkdir();(other/'case.json').write_text(json.dumps(self.case))
        self.write([self.record,{**self.record,'directory':str(other.relative_to(self.root))}])
        self.assertTrue(any('同一案例号' in x[3] for x in check_case_registry(self.root)))

    def test_mismatched_binding_and_changed_profile_fail(self):
        (self.folder/'profile.json').write_text('{}')
        self.case['report_profile'] = {'file':'profile.json','sha256':'0'*64,'filled_at':None}
        self.record['profile'] = {**self.case['report_profile'],'sha256':'1'*64};self.write()
        messages = [x[3] for x in check_case_registry(self.root)]
        self.assertTrue(any('绑定不一致' in x for x in messages))
        self.assertTrue(any('指纹' in x for x in messages))

    def test_path_escape_and_missing_report_fail(self):
        self.record['reports'] = ['../private.pdf'];self.write()
        self.assertTrue(any('越出' in x[3] for x in check_case_registry(self.root)))
        self.record['directory'] = '../private';self.write()
        self.assertTrue(any('examples' in x[3] for x in check_case_registry(self.root)))

    def test_pipeline_without_deliverable_is_not_a_registered_case(self):
        pipeline = self.folder.parent / 'pipeline';pipeline.mkdir()
        (pipeline/'report.json').write_text('{"meta":{}}')
        self.assertEqual(check_case_registry(self.root), [])


if __name__ == '__main__':unittest.main()
