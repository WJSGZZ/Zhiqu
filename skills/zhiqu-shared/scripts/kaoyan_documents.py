"""RAM-only PDF/image readers. Uncertain geometry, ownership or samples fail closed.

PDF A reads pdfplumber's line cells; PDF B independently detects MuPDF line
cells and assembles original character positions. Neither consumes the other's
text. Vision reads rendered sample regions as a third method. Private columns
never leave these in-memory readers.
"""
import contextlib
import datetime as dt
import hashlib
import io
import math
import re
import unicodedata
import warnings

from kaoyan_adapters import (HEAD, PRIVATE, NeedsReview, parse_verified_tables,
                             samples)


class _ScanOnly(NeedsReview):
    pass


def norm(text):
    # Circled list markers must not fuse into exam codes (①101 != 1101).
    markers={chr(0x2460+i):chr(0xe000+i)for i in range(20)}
    text=(text or '').translate(str.maketrans(markers))
    text=unicodedata.normalize('NFKC',text).translate(str.maketrans({v:k for k,v in markers.items()}))
    return re.sub(r'\s+', '', text)


def tick(deadline):
    if deadline: deadline()


def _lines(chars):
    lines = []
    for c in sorted(chars, key=lambda z: (z[1]+z[3])/2):
        y = (c[1]+c[3])/2
        if not lines or abs(y-lines[-1][0]) > 2.5:
            lines.append([y, [c]])
        else:
            lines[-1][1].append(c)
    return [''.join(c[4] for c in sorted(line, key=lambda z: z[0])) for _, line in lines]


def _inside(chars, box):
    return [c for c in chars if box[0] <= (c[0]+c[2])/2 < box[2]
            and box[1] <= (c[1]+c[3])/2 < box[3]]


def _cluster(values, tolerance=.7):
    out = []
    for x in sorted(values):
        if not out or x-out[-1] > tolerance: out.append(x)
    return out


def _pdf_edges(page):
    edges=[]
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0]=='re':
                r=item[1]
                edges.extend([('h',r.x0,r.x1,r.y0,r.y0),('h',r.x0,r.x1,r.y1,r.y1),
                              ('v',r.x0,r.x0,r.y0,r.y1),('v',r.x1,r.x1,r.y0,r.y1)])
            elif item[0]=='l':
                a,b=item[1:3]
                if abs(a.y-b.y)<.3:edges.append(('h',min(a.x,b.x),max(a.x,b.x),a.y,a.y))
                if abs(a.x-b.x)<.3:edges.append(('v',a.x,a.x,min(a.y,b.y),max(a.y,b.y)))
    return edges


def _closed(edges, box, bottom=True):
    y=box[3] if bottom else box[1]
    intervals=sorted((max(box[0],e[1]),min(box[2],e[2])) for e in edges
                     if e[0]=='h' and abs(e[3]-y)<1 and e[2]>box[0] and e[1]<box[2])
    end=box[0]
    for a,b in intervals:
        if a>end+1:return False
        end=max(end,b)
    return end>=box[2]-1


def _grid(cells, chars, edges, reader, page, table):
    """Expand real merged rectangles; no textual forward fill."""
    cells=[tuple(map(float,c)) for c in cells if c]
    xs=_cluster([v for c in cells for v in (c[0],c[2])])
    ys=_cluster([v for c in cells for v in (c[1],c[3])])
    if len(xs)<2 or len(ys)<2:raise NeedsReview('原表缺少可靠物理网格')
    if (len(xs)-1)*(len(ys)-1)>200000:raise NeedsReview('原表网格超出本次安全处理范围')
    text={}
    for c in cells:
        selected=_inside(chars,c)
        if reader=='plumber':
            from pdfplumber.utils import extract_text
            # The other reader uses its own line grouping, not this utility.
            selected_dict=[{'x0':z[0],'top':z[1],'x1':z[2],'bottom':z[3],
                            'doctop':z[1],'text':z[4],'upright':True,'height':z[3]-z[1],'width':z[2]-z[0]}for z in selected]
            text[c]=norm(extract_text(selected_dict,x_tolerance=2,y_tolerance=2)) if selected else ''
        else:text[c]=norm(''.join(_lines(selected)))
    rows=[];anchors=[];boxes=[];literal={};open_bottom={}
    for ri in range(len(ys)-1):
        row=[];aa=[];bb=[]
        for ci in range(len(xs)-1):
            cx=(xs[ci]+xs[ci+1])/2;cy=(ys[ri]+ys[ri+1])/2
            found=[c for c in cells if c[0]-.1<cx<c[2]+.1 and c[1]-.1<cy<c[3]+.1]
            if not found:
                # An unclosed final column band can be a genuine page break.
                # Require a drawn top and BOTH vertical sides, and no bottom;
                # any later carry additionally requires the next first cell empty.
                top=max((e[3]for e in edges if e[0]=='h'and e[1]<=xs[ci]+1 and e[2]>=xs[ci+1]-1 and e[3]<=cy),default=None)
                c=(xs[ci],top if top is not None else cy,xs[ci+1],ys[-1])
                sides=all(any(e[0]=='v'and abs(e[1]-x)<1 and e[3]<=c[1]+1 and e[4]>=c[3]-1 for e in edges)for x in[c[0],c[2]])
                overlap=any(min(c[2],z[2])-max(c[0],z[0])>.5 and min(c[3],z[3])-max(c[1],z[1])>.5 for z in cells)
                if top is None or not sides or _closed(edges,c)or overlap:raise NeedsReview('原表物理格缺口没有可靠跨页边界')
                cells.append(c)
                selected=_inside(chars,c)
                if reader=='plumber':
                    from pdfplumber.utils import extract_text
                    z=[dict(x0=q[0],top=q[1],x1=q[2],bottom=q[3],doctop=q[1],text=q[4],upright=True,height=q[3]-q[1],width=q[2]-q[0])for q in selected]
                    text[c]=norm(extract_text(z,x_tolerance=2,y_tolerance=2))if z else''
                else:text[c]=norm(''.join(_lines(selected)))
                found=[c]
            if len(found)!=1:raise NeedsReview('原表物理格重叠，不能猜合并范围')
            c=found[0];ar=min(range(len(ys)),key=lambda i:abs(ys[i]-c[1]));ac=min(range(len(xs)),key=lambda i:abs(xs[i]-c[0]))
            # Millipoint locators avoid meaningless binary-float digit tails;
            # original geometry and all business values are compared unrounded.
            ink=_inside(chars,c)
            crop=[max(c[0],min(v[0]for v in ink)-1.5),max(c[1],min(v[1]for v in ink)-1.5),
                  min(c[2],max(v[2]for v in ink)+1.5),min(c[3],max(v[3]for v in ink)+1.5)] if ink else list(c)
            anchor=(ar+1,ac+1);row.append(text[c]);aa.append(list(anchor));bb.append({'page':page,'bbox':[round(v,3)for v in c],
                                                                                   'ink_crop':[round(v,3)for v in crop]})
            literal[anchor]=text[c]
            open_bottom[anchor]=not _closed(edges,c)
        rows.append(row);anchors.append(aa);boxes.append(bb)
    return {'table':table,'page':page,'rows':rows,'anchors':anchors,'boxes':boxes,
            'literal_cells':literal,'open_bottom':open_bottom,'xs':xs,'ys':ys,
            'bbox':[xs[0],ys[0],xs[-1],ys[-1]]}


def _same_grid(a,b):
    if a['rows']!=b['rows'] or a['anchors']!=b['anchors']:
        raise NeedsReview('PDF两种独立读法有格值或合并范围不一致，整份未入')
    if len(a['xs'])!=len(b['xs']) or len(a['ys'])!=len(b['ys']):
        raise NeedsReview('PDF独立格线数量不一致，整份未入')
    if any(abs(x-y)>1 for k in ['xs','ys'] for x,y in zip(a[k],b[k])):
        raise NeedsReview('PDF独立物理边界不一致，整份未入')
    if a['open_bottom']!=b['open_bottom']:
        raise NeedsReview('PDF跨页封口线的独立判断不一致')


def _title(headers_a,headers_b,school,year,layer):
    terms={'lines':r'复试.*(?:分数线|基本要求|成绩要求)|复试线',
           'catalog':r'招生.*(?:专业目录|目录|计划)', 'stats':r'拟录取'}
    for x,y in zip(headers_a,headers_b):
        a,b=norm(x),norm(y)
        ma,mb=re.search(terms[layer],a),re.search(terms[layer],b)
        if layer=='stats' and any(re.search('不予拟录取|取消拟录取|未拟录取|未录取',z)for z in [a,b]):continue
        if all(school in z and str(year)in z and '硕士'in z and '博士'not in z for z in [a,b]) and ma and mb:
            # Only the original header range, never a fabricated document title.
            left=min(a.index(school),a.index(str(year)));right=max(ma.end(),a.index(school)+len(school))
            title=a[left:right]
            if len(title)>250:raise NeedsReview('PDF标题范围过长，未能可靠确定原题')
            return title
    raise NeedsReview('PDF标题或页眉未同时确认学校、年份、硕士层次与数据类别')


def _source(body,url,school,year,layer,title,kind):
    sha=hashlib.sha256(body).hexdigest();today=dt.date.today().isoformat()
    title_sha=hashlib.sha256(title.encode()).hexdigest()
    if layer=='stats':title=f'{school}{year}年拟录取初试总分匿名统计（原题指纹留存）'
    method=('pdfplumber格线原格与PyMuPDF独立格线/字位置逐格核对；macOS Vision原页区域第三读抽核'
            if kind=='text' else 'macOS Vision原图字符位置与逐原格切块独立识别；10%区域抽核')
    return dict(source_id='src-ondemand-'+sha[:24],grade='官方',publisher=school,title=title,
                landing_url='',file_url=url,published='',retrieved=today,method=method,
                archive_sha256=sha,archive_path='',archive_status='已核后删除（有指纹）',
                wayback_url='',note='按需取得原表，仅匿名业务及定位；原题SHA256='+title_sha,
                citation=f'{school}，{title}，{year}，{url}，取得日期{today}',license='未注明',producer_revision='')


def _header_index(table):
    return next((ri for ri,row in enumerate(table['rows'][:5]) if
                 any(HEAD.get(norm(x))in {'code','combined'}for x in row)),None)


def _continue_tables(tables):
    """Only visible-code/open-bottom/empty-next-first-cell chains may carry.

    This is geometry continuity, never a last-seen-programme forward fill.
    Cross-page literals retain their original page/table/row/column identity.
    """
    previous=None
    for table in tables:
        table['literal_cells']={(table['page'],table['table'],*a):v for a,v in table['literal_cells'].items()}
        table['open_bottom']={(table['page'],table['table'],*a):v for a,v in table['open_bottom'].items()}
        table['anchors']=[[[table['page'],table['table'],*a]for a in row]for row in table['anchors']]
        h=_header_index(table)
        if h is None:continue
        codecols=[i for i,x in enumerate(table['rows'][h])if HEAD.get(norm(x))in{'code','combined'}]
        ci=codecols[0]if len(codecols)==1 else None
        if ci is None:continue
        if previous and table['page']==previous['page']+1:
            ph=_header_index(previous)
            same=table['rows'][h]==previous['rows'][ph] and len(table['xs'])==len(previous['xs'])and all(abs(x-y)<1 for x,y in zip(table['xs'],previous['xs']))
            first=h+1
            if same and first<len(table['rows'])and not table['rows'][first][ci]:
                old=tuple(previous['anchors'][-1][ci]);value=previous['rows'][-1][ci]
                if previous['open_bottom'].get(old) and re.match(r'^\*?(?:\d{4}[0-9A-Z]{2}|S\d{6})(?=\D|$)',value):
                    table['continues_table']=previous['table']
                    for col in range(len(table['rows'][h])):
                        pa=tuple(previous['anchors'][-1][col]);ca=table['anchors'][first][col]
                        if previous['open_bottom'].get(pa)and not table['rows'][first][col]:
                            for ri in range(first,len(table['rows'])):
                                if table['anchors'][ri][col]==ca:
                                    table['rows'][ri][col]=previous['rows'][-1][col]
                                    table['anchors'][ri][col]=list(pa)
                                    table['boxes'][ri][col]=previous['boxes'][-1][col]
                            table['literal_cells'][pa]=previous['literal_cells'].get(pa,value)
                    table['cross_page_proof']={'previous_page':previous['page'],'previous_table':previous['table'],
                                               'previous_code_band_open_bottom':True,'next_first_code_band_empty':True,
                                               'original_code_anchor':list(old)}
        previous=table
    return tables


def _join_continuations(tables):
    groups={};out=[]
    for table in tables:
        prior=table.get('continues_table');dest=groups.get(prior)
        if dest is None:
            out.append(table);groups[table['table']]=table;continue
        h=_header_index(table);start=len(dest['rows'])
        for ri in range(h+1,len(table['rows'])):
            dest['rows'].append(table['rows'][ri]);dest['anchors'].append(table['anchors'][ri]);dest['boxes'].append(table['boxes'][ri])
            dest['locations'][len(dest['rows'])-1]=table['locations'][ri]
        dest['literal_cells'].update(table['literal_cells']);dest.setdefault('cross_page_proofs',[]).append(table['cross_page_proof'])
        groups[table['table']]=dest
    return out


def _ownership(tables, page_chars, programs, layer="catalog"):
    """Every visible requested six-digit code must have an actual original cell."""
    code_pattern=r'(?:\d{4}[0-9A-Z]{2}|S\d{6}|\d{4})' if layer=='lines' else r'(?:\d{4}[0-9A-Z]{2}|S\d{6})'
    for table in tables:
        h=_header_index(table)
        if h is None:continue
        labels=table['rows'][h];codecols=[i for i,x in enumerate(labels)if HEAD.get(norm(x))in{'code','combined'}]
        if len(codecols)!=1:raise NeedsReview('专业代码列不唯一，不能自动判归属')
        ci=codecols[0];visible=[];owned=[]
        # Scan the entire visible programme column, not only extracted rows.
        x0,x1=table['xs'][ci:ci+2]
        chars=[c for c in page_chars[table['page']] if x0<=(c[0]+c[2])/2<x1 and
               table['ys'][h+1]<=(c[1]+c[3])/2<table['bbox'][3]]
        for line in _lines(chars):visible.extend(re.findall(r'(?<!\d)'+code_pattern+r'(?!\d)',norm(line)))
        seen=set()
        for ri,row in enumerate(table['rows'][h+1:],h+1):
            anchor=tuple(table['anchors'][ri][ci]);raw=row[ci]
            m=re.match(r'^\*?('+code_pattern+r')(?=\D|$)',raw)
            if m and anchor not in seen:
                if table['boxes'][ri][ci]['page']==table['page']:owned.append(m[1])
                seen.add(anchor)
            elif not m and any(re.search(r'\d',v)for v in row):
                raise NeedsReview('数据行缺少实际专业代码或已证明的合并锚点')
        if sorted(visible)!=sorted(owned):raise NeedsReview('全页可见专业代码锚点与原格归属未闭合')
    # Locate each visible occurrence, not mere membership in table text: a
    # second occurrence of the same code outside the table must not disappear.
    for page,chars in page_chars.items():
        groups=[]
        for c in sorted(chars,key=lambda z:(z[1]+z[3])/2):
            y=(c[1]+c[3])/2
            if not groups or abs(y-groups[-1][0])>2.5:groups.append([y,[c]])
            else:groups[-1][1].append(c)
        cells=[]
        for t in tables:
            h=_header_index(t)
            if t['page']!=page or h is None:continue
            ci=next(i for i,v in enumerate(t['rows'][h])if HEAD.get(norm(v))in {'code','combined'})
            cells.extend(t['boxes'][ri][ci]['bbox']for ri in range(h+1,len(t['rows']))if t['boxes'][ri][ci]['page']==page)
        for _,line in groups:
            text='';owners=[]
            for c in sorted(line,key=lambda z:z[0]):
                part=norm(c[4]);text+=part;owners.extend([c]*len(part))
            for m in re.finditer(r'(?<!\d)('+code_pattern+r')(?!\d)',text):
                if not any(m[1].startswith(p)for p in programs):continue
                ink=owners[m.start():m.end()]
                box=(min(c[0]for c in ink),min(c[1]for c in ink),max(c[2]for c in ink),max(c[3]for c in ink))
                if not any(box[0]>=c[0]-1 and box[1]>=c[1]-1 and box[2]<=c[2]+1 and box[3]<=c[3]+1 for c in cells):
                    raise NeedsReview('页面存在所问专业代码但未被可靠原表覆盖')


def _outside_pdf_scope(tables,page_chars,school):
    # Outside-grid scope is data too. Until it has a declared mapping, do not
    # silently discard an exception/plan footnote just because cells agree.
    unmapped_pages=[]
    for pi,chars in page_chars.items():
        boxes=[t['bbox']for t in tables if t['page']==pi]
        outside=[c for c in chars if not any(b[0]<=(c[0]+c[2])/2<=b[2]and b[1]<=(c[1]+c[3])/2<=b[3]for b in boxes)]
        text=norm(''.join(_lines(outside))).replace(norm(school),'')
        if re.search(r'推免|专项|士兵|骨干|联合培养|联培|一志愿|调剂|非全日制|研究方向|不含|包含|另行|调整|(?:总分|单科|满分|计划数|招生人数).{0,12}\d',text):
            unmapped_pages.append(pi)
    if unmapped_pages:
        # Fixed wording plus actual page numbers only; never echo the raw
        # paragraph, names or IDs. Collect all pages in this pass, not just the
        # first exception, so a human need not re-fetch to discover the next one.
        raise NeedsReview('PDF第'+'、'.join(str(p)for p in sorted(unmapped_pages))+'页表格外含未映射的专项/志愿/方向或人数分数口径，需先核清范围')


def _sample_tables(tables, page_image, deadline, ocr_regions):
    candidates=[]
    for table in tables:
        h=_header_index(table)
        if h is None:continue
        for ri in range(h+1,len(table['rows'])):candidates.append((table,ri))
    if not candidates:raise NeedsReview('PDF没有可明确映射的专业业务表')
    chosen=samples(len(candidates));by_page={};requests=[]
    for i in chosen:
        t,ri=candidates[i];h=_header_index(t);labels=t['rows'][h];t.setdefault('sample_row_indices',[]).append(ri)
        for ci,value in enumerate(t['rows'][ri]):
            if not value or norm(labels[ci])in PRIVATE or norm(labels[ci])not in HEAD:continue
            b=t['boxes'][ri][ci];key=(b['page'],tuple(b.get('ink_crop',b['bbox'])))
            if key not in by_page:
                loc=t['locations'].get(ri,{})
                by_page[key]=(value,{'page':b['page'],'table':loc.get('table',t['table']),'row':loc.get('row',ri+1),'column':ci+1,'bbox':b['bbox']})
    for p in sorted({key[0]for key in by_page}):
        tick(deadline);image,scale=page_image(p)
        keys=[k for k in by_page if k[0]==p]
        regions=[[v*scale for v in key[1]]for key in keys]
        got=ocr_regions(image,regions,deadline=deadline,min_confidence=.25)
        if len(got)!=len(keys):raise NeedsReview('Vision第三读抽核区域数量不一致，整份未入')
        for key,item in zip(keys,got):
            value,loc=by_page[key]
            if norm(item['text'])!=norm(value):raise NeedsReview(f'Vision第三读抽核失败，整份未入（页{p}/行{loc["row"]}/列{loc["column"]}）')
            requests.append(loc)
    for t in tables:t.setdefault('sample_row_indices',[])
    return {'sample_count':len(chosen),'sample_cells':len(requests),'sample_locators':requests,
            'original_rows':len(candidates),'sample_passed':True,'third_read':'macOS Vision rendered original regions'}


def parse_official_pdf(body,url,identity,year,layer,programs,*,deadline=None,ocr_regions=None):
    """Return the same anonymous manifest contract as the HTML adapter."""
    try:
        return _pdf(body,url,identity,year,layer,programs,deadline,ocr_regions)
    except _ScanOnly:
        return _scanned_pdf(body,url,identity,year,layer,programs,deadline)
    except (NeedsReview,TimeoutError):raise
    except Exception:
        raise NeedsReview('PDF解析或独立核对失败；未输出原文异常内容') from None


def _pdf(body,url,identity,year,layer,programs,deadline,ocr_regions):
    import pdfplumber
    import pymupdf
    if not body.startswith(b'%PDF')or len(body)>20*1024*1024:raise NeedsReview('附件并非安全范围内的PDF原件')
    if ocr_regions is None:
        from kaoyan_vision import recognize_regions
        ocr_regions=recognize_regions
    tables=[];headers_a=[];headers_b=[];page_chars={}
    with warnings.catch_warnings(),contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter('ignore')
        with pdfplumber.open(io.BytesIO(body))as pa,pymupdf.open(stream=body,filetype='pdf')as pb:
            if len(pa.pages)!=len(pb)or not 1<=len(pb)<=200:raise NeedsReview('PDF页数不一致或超出单校自动处理范围')
            for pi,(a,b)in enumerate(zip(pa.pages,pb),1):
                tick(deadline)
                if a.rotation or b.rotation:raise NeedsReview('旋转PDF尚未可靠双读，不自动入库')
                ac=[(c['x0'],c['top'],c['x1'],c['bottom'],c['text'])for c in a.chars]
                bc=[(*c['bbox'],c['c'])for block in b.get_text('rawdict')['blocks']if'lines'in block
                    for line in block['lines']for span in line['spans']for c in span['chars']]
                page_chars[pi]=bc
                aa=sorted(a.find_tables(table_settings={'vertical_strategy':'lines','horizontal_strategy':'lines'}),key=lambda t:(t.bbox[1],t.bbox[0]))
                bb=sorted(b.find_tables(vertical_strategy='lines',horizontal_strategy='lines',use_layout=False).tables,key=lambda t:(t.bbox[1],t.bbox[0]))
                top=min([t.bbox[1]for t in aa]+[a.height*.35])
                headers_a.append(''.join(_lines([c for c in ac if c[3]<=top+1])))
                headers_b.append(''.join(_lines([c for c in bc if c[3]<=top+1])))
                if not ac or not bc:raise _ScanOnly('扫描PDF转图片双读')
                if len(aa)!=len(bb):raise NeedsReview('PDF两引擎识别的物理表格数量不一致')
                for ta,tb in zip(aa,bb):
                    ea=[(e['orientation'],e['x0'],e['x1'],e['top'],e['bottom'])for e in a.edges]
                    ga=_grid(ta.cells,ac,ea,'plumber',pi,len(tables)+1)
                    gb=_grid(tb.cells,bc,_pdf_edges(b),'mupdf',pi,len(tables)+1)
                    _same_grid(ga,gb)
                    hi=_header_index(ga)
                    if hi is not None and hi>0:
                        headers_a[-1]+=''.join(v for r in ga['rows'][:hi]for v in r)
                        headers_b[-1]+=''.join(v for r in gb['rows'][:hi]for v in r)
                    ga['locations']={ri:{'page':pi,'table':ga['table'],'row':ri+1,'cells':ga['boxes'][ri]}for ri in range(len(ga['rows']))}
                    ga['read_method']='pdfplumber格线原格 / PyMuPDF独立格线字位置 / Vision第三读抽核'
                    tables.append(ga)
            title=_title(headers_a,headers_b,identity['name'],year,layer)
            _outside_pdf_scope(tables,page_chars,identity['name'])
            _continue_tables(tables)
            _ownership(tables,page_chars,programs,layer)
            tables=_join_continuations(tables)
            def render(page):
                tick(deadline);scale=3
                return pb[page-1].get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png'),scale
            proof=_sample_tables(tables,render,deadline,ocr_regions)
            source=_source(body,url,identity['name'],year,layer,title,'text')
            result=parse_verified_tables(tables,source,identity,year,layer,programs)
            proof.update(sha256=source['archive_sha256'],dual_read_equal=True,methods=['pdfplumber line cells','PyMuPDF independent drawings and character positions','macOS Vision original-region samples'],status='approved',read_method='text',extracted_rows=proof['original_rows'])
            result['proofs'].append(proof)
            if layer=='stats':
                for f in result['manifest'].get('files',[]):f['method']='PDF两独立原格与Vision第三读抽核后内存匿名聚合'
            return result


def parse_official_image(body,url,identity,year,layer,programs,*,deadline=None,reader=None):
    """Lined images only; OCR, geometry, samples and outside scopes all gate entry."""
    if reader is None:
        from kaoyan_image_tables import read_image_tables
        reader=read_image_tables
    try:
        read=reader(body,deadline=deadline)
        title=_title([read['header_read_a']],[read['header_read_b']],identity['name'],year,layer)
        tables=read['tables']
        _image_outside_scope(read)
        source=_source(body,url,identity['name'],year,layer,title,'image')
        result=parse_verified_tables(tables,source,identity,year,layer,programs)
        proof=dict(read['sample_proof'],sha256=source['archive_sha256'],read_method='image',
                   dual_read_equal=True,status='approved',methods=['Vision whole original character geometry','Vision fixed original-cell crops','Vision sampled original crops with fixed second setting'])
        for tableproof in result['proofs']:tableproof['method']=source['method']
        if layer=='lines':
            locs=proof['sample_locators'];n=proof['original_rows']
            for row in result['manifest']['rows']:
                row['row']['read_method']='读图：原图/逐格两读及固定第三配置抽核'
                row['review'].update(image_sha256=source['archive_sha256'],candidate_count=n,
                                     samples=[{'status':'approved','source_id':source['source_id'],
                                               'image_sha256':source['archive_sha256'],'locator':loc}for loc in locs])
        if layer=='stats':
            for f in result['manifest'].get('files',[]):f.update(method='图片整格双读及10%固定第三读后内存匿名聚合',read_method='image')
        result['proofs'].append(proof)
        return result
    except (NeedsReview,TimeoutError):raise
    except Exception:raise NeedsReview('图片网格/OCR独立核对未通过；未输出源文字')from None


def _image_outside_scope(read):
    boxes=[t['bbox']for t in read['tables']];header=read['header_box']
    def inside(b,r):return b[0]>=r[0]-1 and b[1]>=r[1]-1 and b[2]<=r[2]+1 and b[3]<=r[3]+1
    for token in read['whole_tokens']:
        if inside(token['bbox'],header)or any(inside(token['bbox'],b)for b in boxes):continue
        if not re.fullmatch(r'(?:第)?\d{1,3}(?:页)?',norm(token['text'])):
            raise NeedsReview('图片表格外有未映射范围文字，须先核清学院/方向/专项')


def _scanned_pdf(body,url,identity,year,layer,programs,deadline):
    import pymupdf
    from kaoyan_image_tables import read_image_tables
    tables=[];ha=[];hb=[];locs=[];n=0;image_shas=[]
    try:
        with pymupdf.open(stream=body,filetype='pdf')as doc:
            if len(doc)>80:raise NeedsReview('扫描PDF页数超出单校自动识别范围')
            for pi,page in enumerate(doc,1):
                tick(deadline)
                image=page.get_pixmap(matrix=pymupdf.Matrix(3,3),alpha=False).tobytes('png')
                read=read_image_tables(image,page=pi,table_start=len(tables)+1,deadline=deadline)
                _image_outside_scope(read);tables.extend(read['tables']);ha.append(read['header_read_a']);hb.append(read['header_read_b'])
                n+=read['sample_proof']['original_rows'];locs+=read['sample_proof']['sample_locators']
                image_shas.append({'page':pi,'sha256':hashlib.sha256(image).hexdigest()})
        title=_title(ha,hb,identity['name'],year,layer);source=_source(body,url,identity['name'],year,layer,title,'image')
        source['method']='扫描PDF原页固定3倍渲染；'+source['method']
        result=parse_verified_tables(tables,source,identity,year,layer,programs)
        proof=dict(sha256=source['archive_sha256'],read_method='image',status='approved',original_rows=n,extracted_rows=n,
                   dual_read_equal=True,sample_passed=True,sample_locators=locs,image_pages=image_shas,
                   methods=['Vision whole rendered page geometry','Vision fixed cell crops','Vision fixed third-setting samples'])
        if layer=='lines':
            for row in result['manifest']['rows']:
                row['row']['read_method']='读图：扫描PDF原页/逐原格双读及10%第三读'
                row['review'].update(image_sha256=source['archive_sha256'],candidate_count=n,
                                     samples=[{'status':'approved','source_id':source['source_id'],'image_sha256':source['archive_sha256'],'locator':loc}for loc in locs])
        if layer=='stats':
            for f in result['manifest'].get('files',[]):f.update(method='扫描PDF图片双读与10%抽核后匿名聚合',read_method='image')
        result['proofs'].append(proof);return result
    except (NeedsReview,TimeoutError):raise
    except Exception:raise NeedsReview('扫描PDF原图双读或抽核失败，整份未入')from None


def parse_official_document(body,url,identity,year,layer,programs,*,deadline=None):
    if body.startswith(b'%PDF'):return parse_official_pdf(body,url,identity,year,layer,programs,deadline=deadline)
    if body.startswith((b'\x89PNG',b'\xff\xd8',b'GIF87a',b'GIF89a',b'RIFF')):
        return parse_official_image(body,url,identity,year,layer,programs,deadline=deadline)
    raise NeedsReview('附件不是已支持且能独立核验的PDF或图片')
