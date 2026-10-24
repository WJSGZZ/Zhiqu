"""Offline tests: fake OCR only; no network or real candidate records."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

SHARED = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'
sys.path.insert(0, str(SHARED))
import kaoyan_vision as vision


def image_bytes(width=100, height=100):
    output = io.BytesIO()
    Image.new('RGB', (width, height), 'white').save(output, format='PNG')
    return output.getvalue()


def token(text='3', rect=(.1,.8,.2,.1), confidence=1, chars=None):
    return dict(text=text, rect=list(rect), confidence=confidence,
                chars=chars if chars is not None else [dict(text=c, rect=list(rect)) for c in text])


class VisionTests(unittest.TestCase):
    def test_bottom_left_boxes_map_to_original_crop_pixels(self):
        data = image_bytes(200, 300)
        result = vision.region_text(data, (40,60,140,260), backend=lambda *a,**k:[[token()]])
        self.assertEqual(result['region'], [40,60,140,260])
        box=result['tokens'][0]['bbox']
        for actual, expected in zip(box,[50,80,70,100]):self.assertAlmostEqual(actual,expected)
        self.assertEqual(result['normalized'],'3')

    def test_only_whitespace_normalizes_not_wrong_digit_or_scope(self):
        self.assertEqual(vision.normalized('08 5404\n'), '085404')
        self.assertNotEqual(vision.normalized('O85404'), '085404')
        self.assertNotEqual(vision.normalized('本科'), vision.normalized('本釉'))

    def test_batch_samples_use_one_backend_call_and_pass_setting(self):
        calls=[]
        def backend(data,**kw):
            calls.append(kw)
            return [[token('1')]for _ in kw['regions']]
        result=vision.recognize_regions(image_bytes(),[(0,0,50,50),(50,50,100,100)],mode='fast',correction=True,backend=backend)
        self.assertEqual(len(calls),1);self.assertEqual(len(result),2)
        self.assertEqual(calls[0]['level'],'fast');self.assertTrue(calls[0]['correction'])

    def test_low_confidence_refuses_whole_source(self):
        with self.assertRaises(vision.VisionMismatch):
            vision.region_text(image_bytes(),backend=lambda *a,**k:[[token(confidence=.24)]])

    def test_fixed_cjk_minimum_is_not_a_claim_of_accuracy(self):
        result=vision.region_text(image_bytes(),backend=lambda *a,**k:[[token('科',confidence=.25)]])
        self.assertEqual(result['normalized'],'科')

    def test_character_geometry_must_cover_complete_recognized_text(self):
        t=token('085404',chars=[dict(text='08540',rect=[.1,.8,.2,.1])])
        with self.assertRaises(vision.VisionMismatch):vision.region_text(image_bytes(),backend=lambda *a,**k:[[t]])

    def test_crop_outside_source_is_rejected_before_ocr(self):
        def never(*a,**k):raise AssertionError('backend must not run')
        for box in [(-1,0,1,1),(0,0,101,10),(1,1,1,2),(0,0,float('nan'),2)]:
            with self.subTest(box=box),self.assertRaises(vision.VisionMismatch):vision.region_text(image_bytes(),box,backend=never)

    def two_cells(self):return [dict(cell_id='r1c1',bbox=[0,0,50,100]),dict(cell_id='r1c2',bbox=[50,0,100,100])]

    def test_complete_dual_cells_agree_without_picking_methods(self):
        calls=[]
        def backend(data,**kw):
            calls.append(kw['regions'])
            if len(kw['regions'])==1:return [[token('3',(.1,.8,.1,.1)),token('5',(.6,.8,.1,.1))]]
            return [[token('3')],[token('5')]]
        result=vision.dual_read_cells(image_bytes(),self.two_cells(),backend=backend)
        self.assertTrue(result['ok']);self.assertEqual([c['text']for c in result['cells']],['3','5'])
        self.assertEqual(len(calls),2)

    def test_one_disagreeing_cell_refuses_whole_image(self):
        def backend(data,**kw):
            if len(kw['regions'])==1:return [[token('3',(.1,.8,.1,.1)),token('5',(.6,.8,.1,.1))]]
            return [[token('3')],[token('6')]]
        with self.assertRaises(vision.VisionMismatch):vision.dual_read_cells(image_bytes(),self.two_cells(),backend=backend)

    def test_glyph_ink_tops_cannot_reorder_one_recognized_line(self):
        calls=[]
        def backend(data,**kw):
            calls.append(kw)
            if len(calls)==1:return [[token('代码',(.1,.7,.7,.2),chars=[dict(text='代',rect=[.1,.7,.2,.2]),dict(text='码',rect=[.5,.8,.2,.1])])]]
            return [[token('代码')]]
        result=vision.dual_read_cells(image_bytes(),[dict(cell_id='a',bbox=[0,0,100,100])],backend=backend)
        self.assertEqual(result['cells'][0]['text'],'代码')

    def test_whole_ocr_crossing_column_border_is_rejected(self):
        with self.assertRaises(vision.VisionMismatch):
            vision.dual_read_cells(image_bytes(),self.two_cells(),backend=lambda *a,**k:[[token('3',(.45,.8,.1,.1))]])

    def test_relevant_text_in_uncovered_table_gap_is_rejected(self):
        cells=[dict(cell_id='a',bbox=[0,0,40,100]),dict(cell_id='b',bbox=[60,0,100,100])]
        with self.assertRaises(vision.VisionMismatch):vision.dual_read_cells(image_bytes(),cells,backend=lambda *a,**k:[[token('3',(.45,.8,.1,.1))]])

    def test_character_partly_inside_outer_table_edge_is_not_silently_ignored(self):
        cells=[dict(cell_id='a',bbox=[20,0,100,100])]
        with self.assertRaises(vision.VisionMismatch):
            vision.dual_read_cells(image_bytes(),cells,backend=lambda *a,**k:[[token('3',(.10,.8,.15,.1))]])

    def test_whole_multichar_without_character_boxes_is_not_split_by_guess(self):
        with self.assertRaises(vision.VisionMismatch):
            vision.dual_read_cells(image_bytes(),self.two_cells(),backend=lambda *a,**k:[[token('35',chars=[])]])

    def test_table_title_outside_explicit_grid_not_lost_into_cells(self):
        cells=[dict(cell_id='a',bbox=[0,50,100,100])]
        calls=[]
        def backend(data,**kw):
            calls.append(kw['regions'])
            if kw['regions']==[(0,0,100,100)]:return [[token('题',(.1,.8,.1,.1)),token('3',(.1,.2,.1,.1))]]
            return [[token('3')]]
        result=vision.dual_read_cells(image_bytes(),cells,backend=backend)
        self.assertEqual(result['cells'][0]['text'],'3')
        self.assertEqual(len(result['whole_tokens']),2)

    def test_blank_image_does_not_approve_blank_cells(self):
        with self.assertRaises(vision.VisionMismatch):
            vision.dual_read_cells(image_bytes(),[dict(cell_id='a',bbox=[0,0,100,100])],backend=lambda *a,**k:[[]])

    def test_overlapping_cell_geometry_is_rejected(self):
        with self.assertRaises(vision.VisionMismatch):vision.dual_read_cells(image_bytes(),[dict(cell_id='a',bbox=[0,0,60,100]),dict(cell_id='b',bbox=[50,0,100,100])],backend=lambda *a,**k:[])

    def test_deadline_halts_before_dependency_or_private_ocr(self):
        def expired():raise TimeoutError('合成期限')
        with self.assertRaises(TimeoutError):vision.region_text(image_bytes(),deadline=expired,backend=lambda *a,**k:[])

    def test_missing_local_capability_returns_fixed_error(self):
        with patch.object(vision.platform,'system',return_value='Linux'):
            with self.assertRaises(vision.VisionUnavailable):vision.region_text(image_bytes())

    def test_original_and_ocr_are_not_written_or_logged(self):
        sentinel='合成隐私哨兵';out,err=io.StringIO(),io.StringIO()
        with tempfile.TemporaryDirectory()as tmp,contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            result=vision.region_text(image_bytes(),backend=lambda *a,**k:[[token(sentinel)]],cache_dir=tmp)
            self.assertEqual(result['normalized'],sentinel)
            self.assertEqual(list(Path(tmp).iterdir()),[])
        self.assertEqual(out.getvalue(),'');self.assertEqual(err.getvalue(),'')

    def test_process_error_does_not_echo_stdout_or_stderr(self):
        class Failed:
            returncode=2
            def communicate(self,*a,**k):return b'private synthetic stdout',b'private synthetic stderr'
        with patch.object(vision.subprocess,'Popen',return_value=Failed()):
            with self.assertRaises(vision.VisionUnavailable)as raised:vision._run(['fake'],b'synthetic',None)
        self.assertNotIn('private',str(raised.exception))

    def test_timed_out_child_group_is_killed_and_reaped(self):
        class Timed:
            pid=123
            calls=0
            def communicate(self,*a,**k):
                self.calls+=1
                if self.calls==1:raise subprocess.TimeoutExpired('private synthetic command',.01)
                return b'',b''
        child=Timed()
        with patch.object(vision.subprocess,'Popen',return_value=child),patch.object(vision.os,'killpg')as kill:
            with self.assertRaises(TimeoutError):vision._run(['fake'],b'synthetic',None)
            kill.assert_called_once();self.assertEqual(child.calls,2)

    def test_failed_compile_cleans_temporary_executable(self):
        with tempfile.TemporaryDirectory()as tmp,patch.object(vision.platform,'system',return_value='Darwin'),patch.object(vision.shutil,'which',return_value='/fake/swiftc'),patch.object(vision,'_run',side_effect=vision.VisionUnavailable('本机编译失败')):
            with self.assertRaises(vision.VisionUnavailable):vision._helper_binary(tmp)
            self.assertEqual(list(Path(tmp).glob('vision-build-*')),[])

    def test_cached_binary_fingerprint_is_checked_without_recompilation(self):
        with tempfile.TemporaryDirectory()as tmp,patch.object(vision.platform,'system',return_value='Darwin'),patch.object(vision.shutil,'which',return_value='/fake/swiftc'):
            import hashlib
            h=hashlib.sha256(vision.SWIFT_SOURCE.encode()).hexdigest();base=Path(tmp)/('vision-'+h)
            base.with_suffix('.swift').write_text(vision.SWIFT_SOURCE);base.write_bytes(b'fake-code')
            base.with_suffix('.json').write_text(json.dumps(dict(source_sha256=h,binary_sha256=hashlib.sha256(b'fake-code').hexdigest())))
            with patch.object(vision,'_run')as run:self.assertEqual(vision._helper_binary(tmp),base);run.assert_not_called()
            base.write_bytes(b'tampered-code')
            with self.assertRaises(vision.VisionUnavailable):vision._helper_binary(tmp)


if __name__=='__main__':unittest.main()
