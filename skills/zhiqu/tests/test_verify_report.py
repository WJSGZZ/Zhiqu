"""Verify one self-contained PDF, using only fictional inputs and local fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_report as verify
try:
    import pymupdf
except ImportError:
    pymupdf = None


def profile(stamp='2026-10-19T12:00:00+08:00'):
    return {'zhiqu':'grad','schema':1,'问卷':'知衢 · 读研 · 模拟问卷','form':'fixture-form','filled_at':stamp,
            'sections':[{'title':'模拟登记','items':[{'id':'budget','q':'预算（模拟）','a':'120'}]}],
            'rank':[],'derived':{},'未填的必答题':[]}


@unittest.skipIf(pymupdf is None, 'PDF tests require the PDF renderer dependency PyMuPDF')
class VerifyDeliveredPDF(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.pdf = self.root/'report.pdf'
        self.profile = verify.json_bytes(profile())
        self.binding = {'file':'profile.json','sha256':verify.digest(self.profile),
                        'filled_at':profile()['filled_at'],'form':'fixture-form'}
        self.case = {'case_id':'2027-YJ-S01','kind':'grad','report_profile':self.binding,
                     'context':{'budget':120},'calculation_plan':{'engine':'registered_operations','operations':[
                         {'output':'remaining','algorithm':'difference','inputs':['{{k:/context/budget}}','{{e:E0001}}']}]}}
        self.evidence = {'items':[{'id':'E0001','claim':'模拟项目费用','value':80,'excerpt':'模拟项目费用为 80 元。',
                                  'source':{'organization':'模拟学校','url':'https://example.edu.cn/fictional'}}]}
        self.materials = {'case_info':[],'personal_inputs':[],'numbers':[
            {'label':'模拟费用','value':80,'sections':'01','evidence_id':'E0001','raw_value':80,
             'excerpt':'模拟项目费用为 80 元。','institution':'模拟学校','url':'https://example.edu.cn/fictional'},
            {'label':'模拟结余','value':40,'sections':'01','inputs':[120,80],'formula':'120 − 80','result':40}],
                         'limitations':[],'gaps':[]}
        self.files = {'case.json':verify.json_bytes(self.case),'profile.json':self.profile,
                      'profile_parse.json':verify.json_bytes({'fields':[]}),
                      'evidence.json':verify.json_bytes(self.evidence),
                      'calculations.json':verify.json_bytes({'remaining':40}),
                      'report_trace.json':verify.json_bytes({'artifacts':{'report.pdf':'old-pdf-hash'}})}
        self.create()

    def create(self, files=None, binding=None, materials=None):
        doc = pymupdf.open();page = doc.new_page()
        page.insert_text((50,50),'01 摘要',fontname='china-s',fontsize=12)
        page.insert_text((50,70),'费用 80 元；结余 40 元。',fontname='china-s',fontsize=12)
        page.insert_text((50,140),'附录：核对材料',fontname='china-s',fontsize=12)
        page.insert_text((50,170),'费用 80 元；结余 40 元；公式 120 - 80 = 40。',fontname='china-s',fontsize=12)
        doc.save(self.pdf);doc.close()
        verify.attach_pdf(self.pdf, files or self.files, materials or self.materials,
                          self.case,binding or self.binding,
                          '<section data-section="01"><h2>01 摘要</h2><p>费用 80 元；结余 40 元。</p></section>')

    def rewrite_attachments(self, mutate):
        # Copy pages, then rebuild the name tree. This avoids embfile_upd API
        # differences between supported PyMuPDF releases and preserves body text.
        with pymupdf.open(self.pdf) as source:
            attachments = {name:source.embfile_get(name) for name in source.embfile_names()}
            mutate(attachments)
            doc = pymupdf.open();doc.insert_pdf(source);doc.set_metadata(source.metadata)
            for name, raw in attachments.items():doc.embfile_add(name,raw)
            target = self.root/'changed.pdf';doc.save(target);doc.close()
        target.replace(self.pdf)

    def mutate_attachment(self, name, content, renew_hash=False):
        def change(attachments):
            attachments[name] = content
            if renew_hash:
                manifest = json.loads(attachments['verification.json'])
                manifest['files'][name] = verify.digest(content)
                attachments['verification.json'] = verify.json_bytes(manifest)
        self.rewrite_attachments(change)

    def test_normal_pdf_recomputes_extracts_and_lists_online_sources(self):
        target = self.root/'extracted'
        result = verify.verify(self.pdf, target)
        self.assertTrue(result['ok'], result['errors'])
        self.assertIn('全部登记计算逐值复算',result['checks'])
        self.assertEqual((target/'profile.json').read_bytes(),self.profile)
        self.assertTrue(any(r['url']=='https://example.edu.cn/fictional' for r in result['online_sources']))
        self.assertTrue(any('不能证明作者' in s for s in result['limitations']))
        trace = json.loads((target/'report_trace.json').read_text())
        self.assertNotIn('report.pdf',trace['artifacts'])

    def test_svg_paint_order_does_not_change_section_number_reading(self):
        # SVGs can be painted after the next section's heading in the PDF stream.
        # Reading positions, rather than drawing order, determine section ownership.
        doc=pymupdf.open();page=doc.new_page()
        page.insert_text((50,40),'01 摘要',fontname='china-s',fontsize=12)
        page.insert_text((50,300),'02 画像',fontname='china-s',fontsize=12)
        page.insert_text((50,100),'费用 80 元；结余 40 元。',fontname='china-s',fontsize=12)
        page.insert_text((50,400),'附录：核对材料',fontname='china-s',fontsize=12)
        page.insert_text((50,430),'费用 80 元；结余 40 元；公式 120 - 80 = 40。',fontname='china-s',fontsize=12)
        doc.save(self.pdf);doc.close()
        html='<section data-section="01"><h2>01 摘要</h2><p>费用 80 元；结余 40 元。</p></section><section data-section="02"><h2>02 画像</h2></section>'
        verify.attach_pdf(self.pdf,self.files,self.materials,self.case,self.binding,html)
        result=verify.verify(self.pdf)
        self.assertTrue(result['ok'],result['errors'])

    def test_changed_visible_number_is_rejected_with_attachments_preserved(self):
        with pymupdf.open(self.pdf) as doc:
            page = doc[0];rect = page.search_for('80')[0]
            page.add_redact_annot(rect,fill=(1,1,1));page.apply_redactions()
            page.insert_text((rect.x0,rect.y1-1),'90',fontsize=12)
            target = self.root/'changed.pdf';doc.save(target)
        target.replace(self.pdf)
        result = verify.verify(self.pdf)
        self.assertFalse(result['ok'])
        self.assertTrue(any('逐页文字' in e for e in result['errors']))
        with pymupdf.open(self.pdf) as doc:self.assertIn('case.json',doc.embfile_names())

    def test_missing_attachment_is_rejected(self):
        self.rewrite_attachments(lambda attachments:attachments.pop('evidence.json'))
        result = verify.verify(self.pdf)
        self.assertFalse(result['ok']);self.assertTrue(any('evidence.json' in e for e in result['errors']),result['errors'])

    def test_changed_attachment_and_forged_calculation_hash_are_rejected(self):
        changed = verify.json_bytes({'remaining':41})
        self.mutate_attachment('calculations.json',changed)
        result = verify.verify(self.pdf)
        self.assertFalse(result['ok']);self.assertTrue(any('附件摘要' in e for e in result['errors']))
        # Updating an attachment's checksum does not replace arithmetic verification.
        self.mutate_attachment('calculations.json',changed,renew_hash=True)
        result = verify.verify(self.pdf)
        self.assertFalse(result['ok']);self.assertTrue(any('计算' in e for e in result['errors']))

    def test_wrong_profile_sha_is_rejected(self):
        files = dict(self.files);case = copy.deepcopy(self.case);case['report_profile']['sha256'] = '0'*64
        files['case.json'] = verify.json_bytes(case);self.create(files=files)
        result = verify.verify(self.pdf)
        self.assertFalse(result['ok']);self.assertTrue(any('画像指纹' in e for e in result['errors']))

    def test_evidence_value_cannot_diverge_from_appendix_even_with_updated_hash(self):
        evidence = copy.deepcopy(self.evidence);evidence['items'][0]['value'] = 81
        self.mutate_attachment('evidence.json',verify.json_bytes(evidence),renew_hash=True)
        result = verify.verify(self.pdf)
        self.assertFalse(result['ok']);self.assertTrue(any('原值/摘录' in e for e in result['errors']))

    def test_unsafe_embedded_path_cannot_be_extracted(self):
        with pymupdf.open(self.pdf) as doc:
            doc.embfile_add('../escape.json',b'{}');target = self.root/'changed.pdf';doc.save(target)
        target.replace(self.pdf)
        with self.assertRaisesRegex(ValueError,'不安全'):verify.verify(self.pdf,self.root/'out')
        self.assertFalse((self.root/'escape.json').exists())

    def test_extract_never_overwrites_existing_file(self):
        target = self.root/'extracted';target.mkdir()
        sentinel = target/'case.json';sentinel.write_text('keep existing contents')
        with self.assertRaisesRegex(ValueError,'不覆盖'):verify.verify(self.pdf,target)
        self.assertEqual(sentinel.read_text(),'keep existing contents')

    def test_windows_backslash_attachment_path_is_rejected(self):
        self.rewrite_attachments(lambda attachments:attachments.update({r'..\escape.json':b'{}'}))
        with self.assertRaisesRegex(ValueError,'不安全'):verify.verify(self.pdf,self.root/'out')

    def test_attach_refuses_unsafe_names_before_writing_pdf(self):
        before = self.pdf.read_bytes()
        with self.assertRaisesRegex(ValueError,'不安全'):
            verify.attach_pdf(self.pdf,{'../escape.json':b'{}'},self.materials,self.case,self.binding,'')
        self.assertEqual(before,self.pdf.read_bytes())


class ExplicitProfileSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);(self.root/'profiles').mkdir()
        self.old = self.root/'profiles/2026-10-19T12-00-00+0800.json'
        self.new = self.root/'profiles/2026-10-20T12-00-00+0800.json'
        self.old.write_bytes(verify.json_bytes(profile()))
        self.new.write_bytes(verify.json_bytes(profile('2026-10-20T12:00:00+08:00')))

    def test_explicit_old_version_is_bound_and_warned_without_replacing_it(self):
        binding, data, warning = verify.select_profile(self.root,str(self.old.relative_to(self.root)))
        self.assertEqual(warning,'报告基于旧画像')
        self.assertEqual(binding['sha256'],hashlib.sha256(self.old.read_bytes()).hexdigest())
        self.assertEqual(data['filled_at'],profile()['filled_at'])
        self.assertIsNone(verify.select_profile(self.root,str(self.new.relative_to(self.root)))[2])

    def test_bind_updates_report_selection_without_changing_working_profile(self):
        working = {'file':'profiles/'+self.new.name,'filled_at':'2026-10-20T12:00:00+08:00'}
        case = {'case_id':'2027-YJ-S01','profile':working,'data_commit':'fixture-data-snapshot'}
        path = self.root/'case.json';path.write_bytes(verify.json_bytes(case))
        binding, data, warning = verify.bind_profile(self.root,str(self.old.relative_to(self.root)))
        saved = json.loads(path.read_text())
        self.assertEqual(saved['report_profile'],binding)
        self.assertEqual(saved['profile'],working)
        self.assertEqual(saved['data_commit'],'fixture-data-snapshot')
        self.assertEqual(warning,'报告基于旧画像')

    def test_analysis_binding_accepts_matching_source_and_rejects_relabel(self):
        case={'case_id':'2027-YJ-S01','data_commit':'fixture-snapshot'}
        (self.root/'case.json').write_bytes(verify.json_bytes(case))
        parsed={'source':{'raw_sha256':verify.digest(self.old.read_bytes())}}
        (self.root/'profile_parse.json').write_bytes(verify.json_bytes(parsed))
        before=(self.root/'case.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'来源指纹不一致'):
            verify.bind_profile(self.root,str(self.new.relative_to(self.root)),require_analysis=True)
        self.assertEqual((self.root/'case.json').read_bytes(),before)
        binding,data,warning=verify.bind_profile(self.root,str(self.old.relative_to(self.root)),require_analysis=True)
        self.assertEqual(binding['sha256'],parsed['source']['raw_sha256'])
        self.assertEqual(warning,'报告基于旧画像')

    def test_selection_cannot_escape_or_silently_choose_nonexistent_version(self):
        outside = self.root.parent/(self.root.name+'-outside.json')
        outside.write_bytes(verify.json_bytes(profile()));self.addCleanup(outside.unlink)
        with self.assertRaisesRegex(ValueError,'案例目录内'):verify.select_profile(self.root,outside)
        with self.assertRaisesRegex(ValueError,'案例目录内'):verify.select_profile(self.root,'absent.json')

    def test_legacy_wrapper_preserves_unknown_fill_time(self):
        (self.root/'old.txt').write_text('模拟旧画像，无填写日期')
        binding, data, warning = verify.select_profile(self.root,'old.txt')
        self.assertIsNone(binding['filled_at']);self.assertIsNone(data['form'])
        self.assertEqual(warning,'报告基于旧画像')
        self.assertEqual(data['text'],'模拟旧画像，无填写日期')


if __name__=='__main__':unittest.main()
