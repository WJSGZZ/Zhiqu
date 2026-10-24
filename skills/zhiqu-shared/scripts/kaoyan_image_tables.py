"""Pixel-grid image reader; unknown geometry and any failed reading stay gaps.

No OCR word decides a boundary. The constants below are fixed before real-school
trials. Text stays in memory: this module neither logs nor persists images, OCR,
personal columns, or source rows. The caller owns source identity and programme
ownership, and must compare both returned header readings with the target.
"""
import io
import math
import re
import unicodedata

from kaoyan_adapters import HEAD, PRIVATE, NeedsReview, samples
import kaoyan_vision as vision

INK_THRESHOLD = 160
MIN_LINE_PIXELS = 24
MIN_LINE_FRACTION = .025
MAX_PIXEL_GAP = 2
AXIS_TOLERANCE = 3
PRESENT_COVERAGE = .90
ABSENT_COVERAGE = .08
MAX_BASE_CELLS = 20000


def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or ''))


def _tick(deadline):
    if deadline is not None:deadline()


def _merge(intervals):
    out=[]
    for start,end in sorted(intervals):
        if out and start <= out[-1][1]+MAX_PIXEL_GAP:out[-1][1]=max(end,out[-1][1])
        else:out.append([float(start),float(end)])
    return out


def _pixel_lines(mask, orientation, minimum, deadline):
    """Find long nearly-contiguous ink runs, independently of OCR tokens."""
    import numpy as np
    a=mask if orientation=='h'else mask.T
    raw=[]
    for position in np.flatnonzero(a.sum(axis=1)>=minimum):
        _tick(deadline)
        points=np.flatnonzero(a[position])
        if not len(points):continue
        cuts=np.flatnonzero(np.diff(points)>MAX_PIXEL_GAP+1)
        starts=np.r_[0,cuts+1];ends=np.r_[cuts,len(points)-1]
        lengths=points[ends]-points[starts]+1
        counts=ends-starts+1
        for begin,end,length,count in zip(starts,ends,lengths,counts):
            if length>=minimum and count/length>=PRESENT_COVERAGE:
                raw.append((float(position),float(points[begin]),float(points[end]+1)))
    groups=[]
    for position,start,end in raw:
        if not groups or position-groups[-1]['positions'][-1]>AXIS_TOLERANCE:
            groups.append({'positions':[position],'intervals':[(start,end)]})
        else:
            groups[-1]['positions'].append(position);groups[-1]['intervals'].append((start,end))
    # Original pixels are discrete. A shared half-pixel boundary would be
    # floor/ceil-expanded into overlapping crops by the OCR image decoder.
    return [{'axis':orientation,'position':int(round(sum(g['positions'])/len(g['positions']))),
             'intervals':[interval]}for g in groups for interval in _merge(g['intervals'])]


def _at(edge, point):
    return any(start-AXIS_TOLERANCE<=point<=end+AXIS_TOLERANCE for start,end in edge['intervals'])


def _components(horizontal, vertical):
    edges=horizontal+vertical;adj=[set()for _ in edges];n=len(horizontal)
    for hi,h in enumerate(horizontal):
        for vi,v in enumerate(vertical,n):
            if _at(h,v['position'])and _at(v,h['position']):adj[hi].add(vi);adj[vi].add(hi)
    seen=set();out=[]
    for start in range(len(edges)):
        if start in seen or not adj[start]:continue
        todo=[start];group=[]
        while todo:
            k=todo.pop()
            if k in seen:continue
            seen.add(k);group.append(edges[k]);todo.extend(adj[k]-seen)
        if sum(e['axis']=='h'for e in group)>=2 and sum(e['axis']=='v'for e in group)>=2:out.append(group)
    return out


def _edge_state(edges, axis, position, start, end):
    # Exclude tiny intersection stubs from an intentionally absent merge edge.
    start+=AXIS_TOLERANCE;end-=AXIS_TOLERANCE
    if end<=start:raise NeedsReview('图片原格过窄，不能可靠判边界')
    intervals=[]
    for edge in edges:
        if edge['axis']==axis and abs(edge['position']-position)<=AXIS_TOLERANCE:
            intervals.extend((max(start,a),min(end,b))for a,b in edge['intervals']if a<end and b>start)
    coverage=sum(b-a for a,b in _merge(intervals))/(end-start)
    if coverage>=PRESENT_COVERAGE:return 1
    if coverage<=ABSENT_COVERAGE:return 0
    raise NeedsReview('图片格线只有部分可见，不能猜合并边界')


def _geometry(edges, size, table, page):
    xs=sorted({e['position']for e in edges if e['axis']=='v'})
    ys=sorted({e['position']for e in edges if e['axis']=='h'})
    width,height=size
    if xs[-1]-xs[0]<max(120,width*.10)or ys[-1]-ys[0]<max(40,height*.03):return None
    if (len(xs)-1)*(len(ys)-1)>MAX_BASE_CELLS:raise NeedsReview('图片网格超出安全处理范围')
    # A full missing outer rule must not silently crop away a column or row.
    for edge in edges:
        low,high=(xs[0],xs[-1])if edge['axis']=='h'else(ys[0],ys[-1])
        if any(a<low-AXIS_TOLERANCE or b>high+AXIS_TOLERANCE+1 for a,b in edge['intervals']):
            raise NeedsReview('图片边框未闭合，可能漏整行或整列')
    nr,nc=len(ys)-1,len(xs)-1
    for ci in range(nc):
        if not all(_edge_state(edges,'h',y,xs[ci],xs[ci+1])for y in [ys[0],ys[-1]]):raise NeedsReview('图片上下外框未闭合')
    for ri in range(nr):
        if not all(_edge_state(edges,'v',x,ys[ri],ys[ri+1])for x in [xs[0],xs[-1]]):raise NeedsReview('图片左右外框未闭合')
    parent=list(range(nr*nc))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):parent[find(a)]=find(b)
    for ri in range(nr):
        for ci in range(nc):
            if ci+1<nc and not _edge_state(edges,'v',xs[ci+1],ys[ri],ys[ri+1]):union(ri*nc+ci,ri*nc+ci+1)
            if ri+1<nr and not _edge_state(edges,'h',ys[ri+1],xs[ci],xs[ci+1]):union(ri*nc+ci,(ri+1)*nc+ci)
    groups={}
    for ri in range(nr):
        for ci in range(nc):groups.setdefault(find(ri*nc+ci),[]).append((ri,ci))
    cells=[];owner={}
    for positions in groups.values():
        r0=min(x[0]for x in positions);r1=max(x[0]for x in positions);c0=min(x[1]for x in positions);c1=max(x[1]for x in positions)
        if len(positions)!=(r1-r0+1)*(c1-c0+1):raise NeedsReview('图片缺边形成非矩形范围，不能猜合并格')
        cell={'cell_id':f't{table}r{r0+1}c{c0+1}','bbox':[xs[c0],ys[r0],xs[c1+1],ys[r1+1]],'anchor':[r0+1,c0+1]}
        cells.append(cell)
        for pos in positions:owner[pos]=cell
    return {'table':table,'page':page,'xs':xs,'ys':ys,'bbox':[xs[0],ys[0],xs[-1],ys[-1]],
            'physical_cells':sorted(cells,key=lambda c:c['anchor']),'owner':owner,'nr':nr,'nc':nc}


def find_pixel_grids(image_bytes, *, page=1, table_start=1, deadline=None):
    """Return geometry only. Its thresholds never depend on words or school."""
    _tick(deadline)
    try:
        import numpy as np
        from PIL import Image
        width,height=vision._image_info(image_bytes)
        with Image.open(io.BytesIO(image_bytes))as image:mask=np.asarray(image.convert('L'))<=INK_THRESHOLD
    except (ImportError,vision.VisionMismatch):
        raise NeedsReview('图片解码或本机网格依赖不可用')from None
    minimum=max(MIN_LINE_PIXELS,math.ceil(min(width,height)*MIN_LINE_FRACTION))
    horizontal=_pixel_lines(mask,'h',minimum,deadline);vertical=_pixel_lines(mask,'v',minimum,deadline)
    output=[]
    for group in sorted(_components(horizontal,vertical),key=lambda g:(min(e['position']for e in g if e['axis']=='h'),min(e['position']for e in g if e['axis']=='v'))):
        _tick(deadline);grid=_geometry(group,(width,height),table_start+len(output),page)
        if grid is not None:output.append(grid)
    if not output:raise NeedsReview('图片没有可靠闭合物理网格，需人工')
    for i,a in enumerate(output):
        for b in output[i+1:]:
            if min(a['bbox'][2],b['bbox'][2])>max(a['bbox'][0],b['bbox'][0])and min(a['bbox'][3],b['bbox'][3])>max(a['bbox'][1],b['bbox'][1]):raise NeedsReview('图片表格组件重叠，不能自动判范围')
    return output


def _header_index(table):
    return next((ri for ri,row in enumerate(table['rows'][:5])if any(HEAD.get(norm(x))in{'code','combined'}for x in row)),None)


def read_image_tables(image_bytes, *, page=1, table_start=1, deadline=None,
                      ocr_backend=None, cell_reader=None, ocr_regions=None):
    """Read line-ruled images/scanned pages; return verified-table adapter shape.

    The fixed third reading uses accurate Vision with language correction on;
    first/second readings use correction off. It checks 10%, min five (all if
    smaller) physical data rows, only declared business columns and code anchors.
    Header comparison is returned as original readings; caller checks identity.
    Injected readers are for offline tests, never a source-level trust override.
    """
    grids=find_pixel_grids(image_bytes,page=page,table_start=table_start,deadline=deadline)
    cell_reader=cell_reader or vision.dual_read_cells
    region_reader=ocr_regions or vision.recognize_regions
    tables=[];whole_tokens=None
    try:
        for grid in grids:
            _tick(deadline)
            kwargs={'deadline':deadline,'min_confidence':.25,'table_region':grid['bbox']}
            if ocr_backend is not None:kwargs['backend']=ocr_backend
            read=cell_reader(image_bytes,grid['physical_cells'],**kwargs)
            if read.get('ok')is not True or read.get('checked_cells')!=len(grid['physical_cells']):raise NeedsReview('图片完整双读尚未闭合')
            if whole_tokens is None:whole_tokens=read['whole_tokens']
            text={c['cell_id']:c for c in read['cells']}
            if set(text)!={c['cell_id']for c in grid['physical_cells']}:raise NeedsReview('图片OCR格与物理格数量不一致')
            rows=[];anchors=[];boxes=[];literal={}
            for ri in range(grid['nr']):
                row=[];aa=[];bb=[]
                for ci in range(grid['nc']):
                    cell=grid['owner'][(ri,ci)];value=norm(text[cell['cell_id']]['text']);row.append(value);aa.append(cell['anchor']);bb.append({'page':page,'bbox':cell['bbox']});literal[tuple(cell['anchor'])]=value
                rows.append(row);anchors.append(aa);boxes.append(bb)
            table={k:grid[k]for k in['table','page','xs','ys','bbox']}
            table.update(rows=rows,anchors=anchors,boxes=boxes,literal_cells=literal,
                         open_bottom={tuple(c['anchor']):False for c in grid['physical_cells']},
                         locations={ri:{'page':page,'table':grid['table'],'row':ri+1,'cells':boxes[ri]}for ri in range(len(rows))},
                         read_method='macOS Vision原图字符位置与固定像素原格裁剪逐格一致；10%第三配置区域抽核')
            tables.append(table)
        # Text in a table's physical row band but outside every grid could be a
        # column whose outer rule vanished, or an unhandled scope paragraph.
        for token in whole_tokens or []:
            chars=token.get('chars')or[{'text':token['text'],'bbox':token['bbox']}]
            for char in chars:
                if not vision.normalized(char['text']):continue
                b=char['bbox'];cx,cy=(b[0]+b[2])/2,(b[1]+b[3])/2
                if any(t['bbox'][1]<cy<t['bbox'][3]for t in tables)and not any(t['bbox'][0]<=cx<=t['bbox'][2]and t['bbox'][1]<=cy<=t['bbox'][3]for t in tables):raise NeedsReview('图片表格旁有未覆盖文字，不能漏列或猜范围')
        first=tables[0];h=_header_index(first)
        if h is None:raise NeedsReview('图片表头未明确专业代码列')
        width,height=vision._image_info(image_bytes)
        header_box=[0,0,width,first['ys'][h]]
        if header_box[3]<=2:raise NeedsReview('图片没有可独立核对的标题范围')
        def within(token):
            b=token['bbox'];return header_box[0]<=(b[0]+b[2])/2<header_box[2]and header_box[1]<=(b[1]+b[3])/2<header_box[3]
        header_a='\n'.join(t['text']for t in whole_tokens or[]if within(t))
        kw={'deadline':deadline,'min_confidence':.25,'mode':'accurate','correction':False}
        if ocr_backend is not None:kw['backend']=ocr_backend
        header_result=region_reader(image_bytes,[header_box],**kw)
        if len(header_result)!=1 or not header_a.strip()or vision.normalized(header_a)!=vision.normalized(header_result[0]['text']):raise NeedsReview('图片标题两种区域读法不一致，整份未入')
        candidates=[]
        for table in tables:
            h=_header_index(table)
            if h is None:raise NeedsReview('图片含未能明确专业表头的独立表，需人工')
            for ri in range(h+1,len(table['rows'])):candidates.append((table,ri,h))
            table['sample_row_indices']=[]
        if not candidates:raise NeedsReview('图片没有可抽核的专业数据行')
        chosen=samples(len(candidates),image=True);requests={}
        for index in chosen:
            table,ri,h=candidates[index];table['sample_row_indices'].append(ri)
            for ci,value in enumerate(table['rows'][ri]):
                label=norm(table['rows'][h][ci])
                if not value or label in PRIVATE or label not in HEAD:continue
                box=table['boxes'][ri][ci]['bbox'];key=tuple(box)
                requests.setdefault(key,{'expected':value,'page':page,'table':table['table'],'row':ri+1,'column':ci+1,'bbox':box})
        if not requests:raise NeedsReview('图片抽核没有可明确映射的业务字段')
        kw.update(correction=True)
        results=region_reader(image_bytes,list(requests),**kw)
        if len(results)!=len(requests):raise NeedsReview('图片第三读抽核区域数不一致')
        sample_locations=[]
        for request,item in zip(requests.values(),results):
            _tick(deadline)
            if norm(item['text'])!=request['expected']:raise NeedsReview('图片第三读抽核不一致，整份未入')
            sample_locations.append({k:v for k,v in request.items()if k!='expected'})
        return {'tables':tables,'header_read_a':header_a,'header_read_b':header_result[0]['text'],
                'header_box':header_box,'whole_tokens':whole_tokens,
                'sample_proof':{'sample_count':len(chosen),'sample_cells':len(sample_locations),
                                'sample_locators':sample_locations,'sample_passed':True,
                                'original_rows':len(candidates),'third_read':'macOS Vision固定accurate+language correction逐原格抽核'},
                'read_method':'image','geometry_policy':{'ink_threshold':INK_THRESHOLD,'minimum_line_pixels':MIN_LINE_PIXELS,'minimum_line_fraction':MIN_LINE_FRACTION,'maximum_pixel_gap':MAX_PIXEL_GAP,'present_coverage':PRESENT_COVERAGE,'absent_coverage':ABSENT_COVERAGE}}
    except (vision.VisionMismatch,vision.VisionUnavailable):
        raise NeedsReview('图片本机两读或抽核未通过，整份未入')from None
