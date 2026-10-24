"""Anonymous synthetic pixel geometry; OCR doubles are injected offline."""
import contextlib
import io
import math
from pathlib import Path
import sys
import unittest

from PIL import Image,ImageDraw

SHARED=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
sys.path.insert(0,str(SHARED))
import kaoyan_image_tables as images
from kaoyan_adapters import NeedsReview
import kaoyan_vision as vision


TITLE='合成大学2026年硕士复试分数线'


def fixture(data_rows=2, merged_code=False, partial_edge=False, missing_outer=False,
            l_shape=False, colspan=False, private_column=False):
    ncols=3 if private_column else 2
    xs=[50+300*i for i in range(ncols+1)]
    ys=[100+60*i for i in range(data_rows+2)]
    im=Image.new('RGB',(xs[-1]+50,ys[-1]+50),'white');d=ImageDraw.Draw(im)
    for y in ys:d.line((xs[0],y,xs[-1],y),fill='black',width=2)
    for x in xs:d.line((x,ys[0],x,ys[-1]),fill='black',width=2)
    if merged_code or l_shape:d.rectangle((xs[0]+3,ys[2]-2,xs[1]-3,ys[2]+3),fill='white')
    if partial_edge:d.rectangle((xs[1]-2,ys[1]+3,xs[1]+3,(ys[1]+ys[2])/2),fill='white')
    if missing_outer:d.rectangle((xs[-1]-2,ys[0],xs[-1]+3,ys[-1]),fill='white')
    if l_shape:d.rectangle((xs[1]-2,ys[1]+3,xs[1]+3,ys[2]-3),fill='white')
    if colspan:d.rectangle((xs[1]-2,ys[0]+3,xs[1]+3,ys[1]-3),fill='white')
    b=io.BytesIO();im.save(b,format='PNG')
    values={(1,ci+1):v for ci,v in enumerate(['专业代码','总分','姓名'][:ncols])}
    for ri in range(data_rows):
        values[(ri+2,1)]='085404'if not merged_code or ri==0 else'085404'
        values[(ri+2,2)]=str(300+ri)
        if private_column:values[(ri+2,3)]='合成隐私哨兵'
    return b.getvalue(),values,xs,ys


def readers(values, *, sample_wrong=False, header_wrong=False, extra_tokens=None,
            fail_dual=False):
    calls=[];cell_boxes={}
    def dual(body,cells,**kwargs):
        calls.append(('dual',kwargs))
        if fail_dual:raise vision.VisionMismatch('合成失败')
        read=[]
        for c in cells:
            value=values[tuple(c['anchor'])];cell_boxes[tuple(c['bbox'])]=value
            read.append(dict(cell_id=c['cell_id'],text=value))
        return dict(ok=True,checked_cells=len(cells),cells=read,
                    whole_tokens=[dict(text=TITLE,bbox=[20,20,600,50],chars=[])]+(extra_tokens or[]))
    def regions(body,regions,**kwargs):
        calls.append(('regions',kwargs,list(regions)))
        if not kwargs['correction']:return [dict(text='错误标题'if header_wrong else TITLE)]
        return [dict(text='999'if sample_wrong else cell_boxes[tuple(box)])for box in regions]
    return dual,regions,calls


class ImageTableTests(unittest.TestCase):
    def test_fixed_pixel_grid_detects_two_columns_and_physical_rows(self):
        body,values,xs,ys=fixture();g=images.find_pixel_grids(body)[0]
        self.assertEqual((g['nr'],g['nc']),(3,2));self.assertEqual(len(g['physical_cells']),6)
        self.assertEqual(g['owner'][(0,0)]['anchor'],[1,1])
        for a,b in zip(g['xs'],xs):self.assertLess(abs(a-b),2)

    def test_shared_pixel_boundaries_do_not_expand_into_overlapping_crops(self):
        body,*_=fixture();g=images.find_pixel_grids(body)[0]
        self.assertTrue(all(isinstance(v,int)for v in g['xs']+g['ys']))
        boxes=[vision._region(c['bbox'],vision._image_info(body))for c in g['physical_cells']]
        for i,a in enumerate(boxes):
            for b in boxes[i+1:]:self.assertFalse(min(a[2],b[2])>max(a[0],b[0])and min(a[3],b[3])>max(a[1],b[1]))

    def test_merged_programme_is_one_real_rectangle_not_text_forward_fill(self):
        body,values,xs,ys=fixture(merged_code=True);g=images.find_pixel_grids(body)[0]
        self.assertEqual(len(g['physical_cells']),5)
        self.assertEqual(g['owner'][(1,0)],g['owner'][(2,0)])
        self.assertEqual(g['owner'][(2,0)]['anchor'],[2,1])

    def test_colspan_geometry_does_not_come_from_ocr_words(self):
        body,values,xs,ys=fixture(colspan=True);g=images.find_pixel_grids(body)[0]
        self.assertEqual(g['owner'][(0,0)],g['owner'][(0,1)])

    def test_two_stacked_tables_sharing_x_positions_are_separate_components(self):
        body,*_=fixture(data_rows=1);piece=Image.open(io.BytesIO(body));im=Image.new('RGB',(piece.width,piece.height*2+60),'white');im.paste(piece,(0,0));im.paste(piece,(0,piece.height+60));b=io.BytesIO();im.save(b,format='PNG')
        grids=images.find_pixel_grids(b.getvalue())
        self.assertEqual(len(grids),2);self.assertEqual([g['table']for g in grids],[1,2])

    def test_two_side_tables_sharing_y_positions_are_separate_components(self):
        body,*_=fixture(data_rows=1);piece=Image.open(io.BytesIO(body));im=Image.new('RGB',(piece.width*2+60,piece.height),'white');im.paste(piece,(0,0));im.paste(piece,(piece.width+60,0));b=io.BytesIO();im.save(b,format='PNG')
        self.assertEqual(len(images.find_pixel_grids(b.getvalue())),2)

    def test_partial_separator_is_rejected_not_guessed_merge(self):
        with self.assertRaises(NeedsReview):images.find_pixel_grids(fixture(partial_edge=True)[0])

    def test_missing_outer_edge_cannot_crop_away_a_column(self):
        with self.assertRaises(NeedsReview):images.find_pixel_grids(fixture(missing_outer=True)[0])

    def test_nonrectangular_merge_is_rejected(self):
        with self.assertRaises(NeedsReview):images.find_pixel_grids(fixture(l_shape=True)[0])

    def test_blank_or_faint_unruled_image_rejected(self):
        for color in ['white',(190,190,190)]:
            im=Image.new('RGB',(700,400),'white');d=ImageDraw.Draw(im);d.rectangle((50,100,650,350),outline=color,width=2);b=io.BytesIO();im.save(b,format='PNG')
            with self.subTest(color=color),self.assertRaises(NeedsReview):images.find_pixel_grids(b.getvalue())

    def test_rotated_grid_is_not_automatically_straightened(self):
        im=Image.open(io.BytesIO(fixture()[0])).rotate(6,fillcolor='white');b=io.BytesIO();im.save(b,format='PNG')
        with self.assertRaises(NeedsReview):images.find_pixel_grids(b.getvalue())

    def test_full_adapter_shape_and_merged_literal_anchor(self):
        body,values,xs,ys=fixture(merged_code=True);dual,regions,calls=readers(values)
        out=images.read_image_tables(body,cell_reader=dual,ocr_regions=regions)
        t=out['tables'][0];self.assertEqual(t['rows'],[['专业代码','总分'],['085404','300'],['085404','301']])
        self.assertEqual(t['anchors'][1][0],t['anchors'][2][0]);self.assertEqual(t['literal_cells'][(2,1)],'085404')
        self.assertEqual(t['locations'][2]['page'],1);self.assertEqual(t['locations'][2]['row'],3)
        self.assertEqual(out['header_read_a'],out['header_read_b']);self.assertTrue(out['sample_proof']['sample_passed'])
        self.assertEqual(out['sample_proof']['sample_count'],2)

    def test_ten_percent_min_five_rows_and_all_business_cells(self):
        body,values,xs,ys=fixture(data_rows=12);dual,regions,calls=readers(values)
        out=images.read_image_tables(body,cell_reader=dual,ocr_regions=regions);t=out['tables'][0]
        self.assertEqual(len(t['sample_row_indices']),5);self.assertEqual(out['sample_proof']['sample_cells'],10)
        self.assertEqual(t['sample_row_indices'],[i+1 for i in images.samples(12,image=True)])
        self.assertTrue(calls[-1][1]['correction']);self.assertEqual(calls[-1][1]['mode'],'accurate')

    def test_third_sample_never_reads_private_name_column(self):
        body,values,xs,ys=fixture(data_rows=6,private_column=True);dual,regions,calls=readers(values)
        out=images.read_image_tables(body,cell_reader=dual,ocr_regions=regions)
        self.assertEqual(out['sample_proof']['sample_cells'],10)
        sample_boxes=calls[-1][2]
        self.assertTrue(all(b[2]<xs[2]+2 for b in sample_boxes))

    def test_sample_failure_rejects_whole_image(self):
        body,values,*_=fixture();dual,regions,calls=readers(values,sample_wrong=True)
        with self.assertRaises(NeedsReview):images.read_image_tables(body,cell_reader=dual,ocr_regions=regions)

    def test_header_crop_disagreement_rejects_source(self):
        body,values,*_=fixture();dual,regions,calls=readers(values,header_wrong=True)
        with self.assertRaises(NeedsReview):images.read_image_tables(body,cell_reader=dual,ocr_regions=regions)

    def test_low_confidence_dual_failure_is_fixed_gap_without_ocr_values(self):
        body,values,*_=fixture();dual,regions,calls=readers(values,fail_dual=True)
        with self.assertRaises(NeedsReview)as e:images.read_image_tables(body,cell_reader=dual,ocr_regions=regions)
        self.assertNotIn('合成隐私哨兵',str(e.exception))

    def test_uncovered_side_text_is_not_silently_discarded(self):
        body,values,*_=fixture();extra=[dict(text='300',bbox=[655,170,690,195],chars=[])]
        dual,regions,calls=readers(values,extra_tokens=extra)
        with self.assertRaises(NeedsReview):images.read_image_tables(body,cell_reader=dual,ocr_regions=regions)

    def test_deadline_interrupts_before_ocr(self):
        def deadline():raise TimeoutError('合成限时')
        with self.assertRaises(TimeoutError):images.read_image_tables(fixture()[0],deadline=deadline)

    def test_private_text_and_original_are_never_logged(self):
        body,values,*_=fixture(private_column=True);dual,regions,calls=readers(values);a,b=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(a),contextlib.redirect_stderr(b):images.read_image_tables(body,cell_reader=dual,ocr_regions=regions)
        self.assertEqual(a.getvalue(),'');self.assertEqual(b.getvalue(),'')


if __name__=='__main__':unittest.main()
