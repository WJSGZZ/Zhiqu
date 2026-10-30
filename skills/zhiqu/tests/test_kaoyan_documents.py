"""Offline document fixtures. OCR fakes read the fixture model, not parser values."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'))
import kaoyan_documents as d
from kaoyan_adapters import NeedsReview

try:
    import pymupdf
    import pdfplumber
except ImportError:
    pymupdf=None

IDENTITY={'name':'合成大学','institution_id':'4100000001'}
URL='https://fixture.edu.cn/2026/catalog.pdf'


def document(layer='catalog', n=4, title=None, private=False, merged=False, code="085404"):
    kind={'catalog':'招生专业目录','lines':'复试分数线','stats':'拟录取名单'}[layer]
    title=title or '合成大学2026年硕士研究生'+kind
    heads=['专业代码','专业名称','招生人数'if layer=='catalog'else'初试总分'if layer=='stats'else'总分']
    if private:heads+=['姓名','考生编号']
    widths=[110,160,90]+([100,160]if private else[])
    xs=[40]
    for w in widths:xs.append(xs[-1]+w)
    top=100;step=30;doc=pymupdf.open();p=doc.new_page(width=max(700,xs[-1]+40),height=350)
    p.insert_text((40,60),title,fontname='china-s',fontsize=12)
    rows=[heads]+[[code,'计算机技术',str(10+i if layer=='catalog'else 300+i)]+(['合成隐私哨兵','123456789012345']if private else[])for i in range(n)]
    model=[]
    for ri,row in enumerate(rows):
        for ci,text in enumerate(row):
            if merged and ci==0 and ri>1:continue
            box=(xs[ci],top+step*ri,xs[ci+1],top+step*(n+1)if merged and ci==0 and ri==1 else top+step*(ri+1))
            p.draw_rect(box,color=(0,0,0),width=.5)
            p.insert_text((box[0]+4,box[1]+18),text,fontname='china-s',fontsize=10)
            model.append((box,text,ci))
    blob=doc.tobytes();doc.close()
    def ocr(_image,regions,**kwargs):
        answer=[]
        for r in regions:
            x=(r[0]+r[2])/6;y=(r[1]+r[3])/6
            matches=[(text,ci)for b,text,ci in model if b[0]<=x<b[2]and b[1]<=y<b[3]]
            if len(matches)!=1:raise AssertionError('fixture crop outside original physical cells')
            text,ci=matches[0]
            if private and ci>=3:raise AssertionError('private column reached third-read OCR')
            answer.append({'text':text})
        return answer
    return blob,ocr


@unittest.skipUnless(pymupdf,'local PDF readers unavailable')
class DocumentTests(unittest.TestCase):
    def parse(self,blob,ocr,layer='catalog',**kwargs):
        return d.parse_official_pdf(blob,URL,IDENTITY,2026,layer,['0854'],ocr_regions=ocr,**kwargs)

    def test_pdf_catalogue_full_two_read_and_third_sample(self):
        blob,ocr=document();r=self.parse(blob,ocr)
        self.assertEqual(r['rows'],4)
        self.assertEqual([x['planned']for x in r['manifest']['rows']],[10,11,12,13])
        self.assertEqual(r['proofs'][-1]['sample_count'],3)
        self.assertEqual(r['proofs'][-1]['original_rows'],4)
        self.assertTrue(r['proofs'][-1]['sample_passed'])
        self.assertEqual(r['manifest']['sources'][0]['file_url'],URL)

    def test_four_digit_lines_do_not_invent_six_digit_programmes(self):
        blob,ocr=document(layer='lines',code='0854')
        r=self.parse(blob,ocr,'lines')
        self.assertEqual({x['row']['program_code']for x in r['manifest']['rows']},{'0854'})
        r=d.parse_official_pdf(blob,URL,IDENTITY,2026,'lines',['085404'],ocr_regions=ocr)
        self.assertEqual(r['rows'],0)

    def test_circled_subject_markers_do_not_fuse_into_exam_codes(self):
        self.assertEqual(d.norm('① 101 思想政治理论'),'①101思想政治理论')

    def test_pdf_merged_code_uses_one_visible_anchor_for_all_rows(self):
        blob,ocr=document(layer='lines',merged=True);r=self.parse(blob,ocr,'lines')
        self.assertEqual(r['rows'],4)
        self.assertTrue(all(x['row']['program_code']=='085404'for x in r['manifest']['rows']))

    def test_third_reader_any_mismatch_rejects_entire_file(self):
        blob,_=document()
        with self.assertRaisesRegex(NeedsReview,'第三读'):
            self.parse(blob,lambda *a,**k:[{'text':'wrong'}for _ in a[1]])

    def test_title_school_year_category_and_masters_required(self):
        for title in ['别校2026年硕士招生专业目录','合成大学2025年硕士招生专业目录',
                      '合成大学2026年硕士考试大纲','合成大学2026年博士招生专业目录']:
            with self.subTest(title=title):
                blob,ocr=document(title=title)
                with self.assertRaisesRegex(NeedsReview,'标题|页眉'):self.parse(blob,ocr)

    def test_negative_admission_titles_are_not_admitted_statistics(self):
        for word in ['不予拟录取','取消拟录取','未拟录取','未录取']:
            blob,ocr=document(layer='stats',title='合成大学2026年硕士'+word+'名单')
            with self.subTest(word=word),self.assertRaises(NeedsReview):self.parse(blob,ocr,'stats')

    def test_document_dispatch_routes_pdf_image_and_rejects_unknown(self):
        with patch.object(d,'parse_official_pdf',return_value={'kind':'pdf'})as pdf:
            self.assertEqual(d.parse_official_document(b'%PDF',URL,IDENTITY,2026,'catalog',['0854']),{'kind':'pdf'})
            self.assertEqual(pdf.call_count,1)
        with patch.object(d,'parse_official_image',return_value={'kind':'image'})as image:
            self.assertEqual(d.parse_official_document(b'\x89PNG',URL,IDENTITY,2026,'catalog',['0854']),{'kind':'image'})
            self.assertEqual(image.call_count,1)
        with self.assertRaises(NeedsReview):d.parse_official_document(b'PK\x03\x04',URL,IDENTITY,2026,'catalog',['0854'])

    def test_independent_grid_text_difference_rejected_before_ocr(self):
        blob,ocr=document();original=d._grid
        def changed(*a,**k):
            g=original(*a,**k)
            if a[3]=='mupdf':g['rows'][1][0]='085411'
            return g
        with patch.object(d,'_grid',side_effect=changed),self.assertRaisesRegex(NeedsReview,'两种独立'):
            self.parse(blob,ocr)

    def test_unowned_visible_programme_cannot_disappear(self):
        blob,ocr=document();doc=pymupdf.open(stream=blob,filetype='pdf')
        doc[0].insert_text((450,280),'085411',fontname='china-s',fontsize=10)
        blob=doc.tobytes();doc.close()
        with self.assertRaisesRegex(NeedsReview,'页面存在'):self.parse(blob,ocr)

    def test_repeated_requested_code_outside_table_is_not_hidden_by_membership(self):
        blob,ocr=document();doc=pymupdf.open(stream=blob,filetype='pdf')
        doc[0].insert_text((450,280),'085404',fontname='china-s',fontsize=10)
        blob=doc.tobytes();doc.close()
        with self.assertRaisesRegex(NeedsReview,'页面存在'):self.parse(blob,ocr)

    def test_unmapped_later_page_scope_is_not_ignored_by_program_filter(self):
        # A matching ordinary table cannot certify a different section/page.
        blob,ocr=document(layer='lines')
        doc=pymupdf.open(stream=blob,filetype='pdf');page=doc.new_page(width=700,height=350)
        page.insert_text((40,60),'二、硕士研究生专项计划进入复试成绩基本要求',fontname='china-s',fontsize=12)
        page.insert_text((40,100),'其他专业另行规定，调剂复试由各学院安排。',fontname='china-s',fontsize=10)
        mixed=doc.tobytes();doc.close()
        third=unittest.mock.Mock(side_effect=ocr)
        with self.assertRaisesRegex(NeedsReview,'PDF第2页表格外'):
            self.parse(mixed,third,'lines')
        third.assert_not_called()

    def test_all_unmapped_pages_reported_without_raw_text(self):
        blob,ocr=document(layer='lines')
        doc=pymupdf.open(stream=blob,filetype='pdf')
        for label in ('合成隐私哨兵，仅限专项','合成另一哨兵，调剂条件另行规定'):
            page=doc.new_page(width=700,height=350)
            page.insert_text((40,60),label,fontname='china-s',fontsize=12)
        mixed=doc.tobytes();doc.close()
        third=unittest.mock.Mock(side_effect=ocr)
        with self.assertRaises(NeedsReview) as caught:self.parse(mixed,third,'lines')
        self.assertIn('PDF第2、3页表格外',str(caught.exception))
        self.assertNotIn('哨兵',str(caught.exception));third.assert_not_called()

    def test_plain_later_page_number_does_not_create_a_scope_exception(self):
        blob,ocr=document(layer='lines')
        doc=pymupdf.open(stream=blob,filetype='pdf');page=doc.new_page(width=700,height=350)
        page.insert_text((40,60),'2',fontsize=12)
        plain=doc.tobytes();doc.close()
        result=self.parse(plain,ocr,'lines')
        self.assertEqual(result['rows'],4)
        self.assertTrue(result['proofs'][-1]['sample_passed'])

    def test_outside_grid_special_scope_cannot_be_silently_dropped(self):
        blob,ocr=document();doc=pymupdf.open(stream=blob,filetype='pdf')
        doc[0].insert_text((40,300),'仅限退役大学生士兵专项计划',fontname='china-s',fontsize=10)
        blob=doc.tobytes();doc.close()
        with self.assertRaisesRegex(NeedsReview,'表格外'):self.parse(blob,ocr)

    def test_statistics_only_anonymous_n_at_least_three(self):
        for n in [1,2,3,4]:
            with self.subTest(n=n):
                blob,ocr=document(layer='stats',n=n,private=True,merged=True)
                capture=io.StringIO()
                with contextlib.redirect_stdout(capture),contextlib.redirect_stderr(capture):r=self.parse(blob,ocr,'stats')
                data=json.dumps(r,ensure_ascii=False)
                self.assertNotIn('合成隐私哨兵',data+capture.getvalue())
                self.assertNotIn('123456789012345',data+capture.getvalue())
                self.assertEqual(r['rows'],int(n>=3))
                if n>=3:self.assertEqual(r['manifest']['rows'][0]['n'],n)

    def test_deadline_is_not_swallowed(self):
        blob,ocr=document()
        def expired():raise TimeoutError('deadline')
        with self.assertRaises(TimeoutError):self.parse(blob,ocr,deadline=expired)

    def test_numeric_coordinate_tails_not_persisted_as_long_numbers(self):
        blob,ocr=document();r=self.parse(blob,ocr)
        for proof in r['proofs']:
            for loc in proof['sample_locators']:
                for cell in loc.get('cells',[]):
                    for value in cell['bbox']:self.assertEqual(value,round(value,3))


class OwnershipAndContinuation(unittest.TestCase):
    def table(self,page,blank=False,opened=False):
        rows=[['专业代码','总分'],[''if blank else'085404','300']]
        return {'table':page,'page':page,'rows':rows,'anchors':[[[1,1],[1,2]],[[2,1],[2,2]]],
                'boxes':[[{'page':page,'bbox':[0,0,10,10]}for _ in range(2)]for _ in range(2)],
                'literal_cells':{(1,1):'专业代码',(1,2):'总分',(2,1):rows[1][0],(2,2):'300'},
                'open_bottom':{(1,1):False,(1,2):False,(2,1):opened,(2,2):False},
                'xs':[0,10,20],'ys':[0,10,20],'bbox':[0,0,20,20],
                'locations':{0:{'page':page,'table':page,'row':1},1:{'page':page,'table':page,'row':2}}}

    def test_cross_page_only_open_previous_and_empty_first_can_carry(self):
        a,b=self.table(1,opened=True),self.table(2,blank=True)
        d._continue_tables([a,b]);self.assertEqual(b['rows'][1][0],'085404')
        self.assertEqual(b['anchors'][1][0],[1,1,2,1])
        merged=d._join_continuations([a,b]);self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['locations'][2]['page'],2)

    def test_closed_previous_code_does_not_forward_fill(self):
        a,b=self.table(1),self.table(2,blank=True)
        d._continue_tables([a,b]);self.assertEqual(b['rows'][1][0],'')
        self.assertNotIn('continues_table',b)

    def test_new_visible_code_not_overwritten_by_old_scope(self):
        a,b=self.table(1,opened=True),self.table(2)
        b['rows'][1][0]='085411';d._continue_tables([a,b])
        self.assertEqual(b['rows'][1][0],'085411');self.assertNotIn('continues_table',b)

    def test_wrong_header_or_geometry_blocks_carry(self):
        for k in ['header','geometry']:
            a,b=self.table(1,opened=True),self.table(2,blank=True)
            if k=='header':b['rows'][0][1]='初试总分'
            else:b['xs']=[0,12,24]
            d._continue_tables([a,b]);self.assertEqual(b['rows'][1][0],'')

    def test_image_outside_scope_cannot_be_dropped(self):
        read={'tables':[{'bbox':[0,20,100,100]}],'header_box':[0,0,100,20],
              'whole_tokens':[{'text':'退役大学生士兵计划','bbox':[0,110,100,120]}]}
        with self.assertRaisesRegex(NeedsReview,'范围文字'):d._image_outside_scope(read)

    def test_page_number_outside_image_table_is_allowed(self):
        d._image_outside_scope({'tables':[{'bbox':[0,20,100,100]}],'header_box':[0,0,100,20],
                               'whole_tokens':[{'text':'第2页','bbox':[40,110,60,120]}]})


if __name__=='__main__':unittest.main()
