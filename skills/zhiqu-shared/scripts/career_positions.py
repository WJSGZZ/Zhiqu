"""Narrow, anonymous readers for observed public position bodies.

Original bytes stay in RAM. Dates describe historical announcements unless an
explicit recruitment year is given; addresses and copyright years are not scope.
"""
import datetime as dt
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit


def norm(value):
    return re.sub(r'\s+', ' ', value).strip()


class BodyReader(HTMLParser):
    """Independent streaming paragraph reader, with exact raw element offsets."""
    def __init__(self, text, target_class="wp_articlecontent"):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.target_class = target_class
        self.group_count = 0
        self.groups = []
        self.lines = [0]
        self.lines.extend(m.end() for m in re.finditer('\n', text))
        self.stack = []
        self.paragraphs = []
        self.active = None
        self.heading_active = None
        self.headings = {}

    def absolute_position(self):
        line, col = self.getpos()
        return self.lines[line-1]+col

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.target_class in attrs.get('class','').split():
            self.group_count += 1
            attrs['_position_group'] = self.group_count
        self.stack.append((tag, attrs)) if tag not in {'br','img','hr','meta','link','input','wbr','source'} else None
        if tag == 'p' and any(self.target_class in a.get('class','').split() for _,a in self.stack):
            if self.active is not None:
                raise ValueError('nested paragraph')
            self.active = [self.absolute_position()+len(self.get_starttag_text()), []]
            self.groups.append(next(a['_position_group'] for _,a in reversed(self.stack) if '_position_group'in a))
        if tag == 'h1' and any(self.target_class in a.get('class','').split()for _,a in self.stack):
            group=next(a['_position_group']for _,a in reversed(self.stack)if '_position_group'in a)
            self.heading_active=(group,[])
        if tag == 'br' and self.active is not None:
            self.active[1].append(' ')

    def handle_data(self, value):
        if self.heading_active is not None:
            self.heading_active[1].append(value)
        if self.active is not None:
            self.active[1].append(value)

    def handle_endtag(self, tag):
        if tag == 'h1'and self.heading_active is not None:
            group,parts=self.heading_active
            self.headings.setdefault(group,[]).append(norm(''.join(parts)))
            self.heading_active=None
        if tag == 'p' and self.active is not None:
            start, parts = self.active
            self.paragraphs.append((norm(''.join(parts)), self.text[start:self.absolute_position()]))
            self.active = None
        for n in range(len(self.stack)-1,-1,-1):
            if self.stack[n][0] == tag:
                del self.stack[n:]
                break


def strict_city(raw, requested):
    """Only explicit short city names and their exact 市 form; no address inference."""
    aliases = {'宁波':'宁波市','杭州':'杭州市','上海':'上海市','北京':'北京市'}
    pieces = [norm(x) for x in re.split(r'[/、,，]', raw)]
    return requested in [aliases.get(x,x) for x in pieces]


def parse_position(body, entry, request):
    from lxml import html
    from career_on_demand import Gap, public_text
    try:
        text = body.decode('utf-8-sig')
        root = html.fromstring(text)
    except Exception:
        raise Gap('具体岗位不是可核对的UTF-8文字HTML') from None
    host = urlsplit(entry['url']).hostname or ''
    if host=='zhjyb.zua.edu.cn':return parse_campus_position(text,root,entry,request)
    if host in {'www.tngdigital.com.cn','tngdigital.com.cn'}:
        return parse_tngd(text,root,entry,request)
    if host in {'www.bodenai.com','bodenai.com'}:
        cards = root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," career-card-container ")]')
        if cards:
            raise Gap('已取得具体岗位正文，但未提供招聘年度或发布时间；不从版权年或取得日猜年度')
        raise Gap('未取得已适配的具体岗位正文，栏目首页不算岗位')
    if host not in {'www.eitech.edu.cn','eitech.edu.cn'}:
        raise Gap('该站具体岗位正文尚无专门读法')
    containers = root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," wp_articlecontent ")]')
    if len(containers) != 1:
        raise Gap('具体岗位正文容器不唯一或缺失')
    container = containers[0]
    if any('hidden' in n.attrib or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',n.get('style',''),re.I) for n in [container]+list(container.iterancestors())+list(container.iterdescendants())):
        raise Gap('具体岗位正文有显式隐藏内容，需人工核对')
    if container.xpath('.//script|.//style|.//table|.//form'):
        raise Gap('具体岗位正文结构超出已适配范围')
    paragraphs = container.xpath('.//p')
    grid = [norm(''.join(p.itertext())) for p in paragraphs]
    second = BodyReader(text)
    try:
        second.feed(text);second.close()
    except Exception:
        raise Gap('具体岗位流式读取失败') from None
    if grid != [p[0] for p in second.paragraphs]:
        raise Gap('具体岗位两种读法逐段不一致')
    # Raw-tag extraction independently checks EVERY retained paragraph.
    raw = [norm(unescape(re.sub('<[^>]+>','',re.sub(r'<br\s*/?>',' ',p[1],flags=re.I)))) for p in second.paragraphs]
    if raw != grid:
        raise Gap('具体岗位原始标签逐段全核不一致')
    titles = root.xpath('//title/text()')
    if len(titles) != 1:
        raise Gap('具体岗位标题不唯一')
    # Named research groups are not necessary for a public job evidence record.
    position = re.split(r'[（(]',norm(titles[0]),maxsplit=1)[0].strip()
    public_text(position)
    if '实习生' not in position or request['stage'] != 'internship' or request['direction'] not in position:
        raise Gap('具体岗位名称或实习阶段不匹配')
    dates = re.findall(r'发布时间\s*[：:]\s*(\d{4}-\d{2}-\d{2})',norm(' '.join(root.itertext())))
    if len(set(dates)) != 1:
        raise Gap('岗位公告发布时间不唯一或未提供；不猜招聘年度')
    published = dates[0]
    year = int(published[:4])
    if year not in request['years']:
        raise Gap('具体岗位公告发布年度不在本次历史查询范围')
    if entry['publisher'] not in norm(' '.join(root.itertext())):
        raise Gap('具体岗位原页未找到登记发布单位')
    starts = {}
    for n,p in enumerate(grid):
        hit = re.match(r'^([一二三四五六七])\s*、',p)
        if hit:
            if hit[1] in starts:
                raise Gap('具体岗位章节重复，需人工核对')
            starts[hit[1]] = n
    if list(starts) != list('一二三四五六七'):
        raise Gap('具体岗位章节结构变化，需重新适配')
    def section(a,b):
        indices = list(range(starts[a]+1, starts[b]))
        return norm(' '.join(grid[n] for n in indices)), indices
    duties,di = section('二','三')
    requirements,ri = section('四','五')
    pay,pi = section('六','七')
    target,si = section('三','四')
    location = next(('能够到宁波东方理工大学校内参与实习。' for n in ri if '能够到宁波东方理工大学校内参与实习。' in grid[n]),None)
    if location is None or request['region'] != '宁波市':
        raise Gap('岗位正文没有匹配的明确到岗城市；不使用单位页脚地址')
    values = {'duties':duties or None,'requirements':requirements or None,'pay':pay or None,
              'schedule': next((grid[n] for n in si if '具体实习周期' in grid[n] and '面议' in grid[n]),None)}
    fields = {k:values[k] for k in request['layers']}
    for value in list(fields.values())+[location]:
        if value:public_text(value)
    retained = sorted(set(di+ri+pi+si))
    locator = 'div.wp_articlecontent[1]'
    row = dict(region=request['region'],region_raw=location,region_basis='explicit_attendance_requirement',year=year,
               year_basis='publication_date',published=published,recruitment_year=None,
               year_scope='历史公告发布年度；未提供招聘届别，不认定当年应届资格',position=position,
               stage='internship',stage_raw=position,fields=fields,src_table=1,src_row=1,
               position_locator=locator,field_locators={k:[f'{locator}/p[{n+1}]' for n in {'duties':di,'requirements':ri,'pay':pi,'schedule':si}[k]] for k in fields})
    proof = dict(kind='position-body-v1',src_table=1,original_rows=len(grid),dual_read_equal=True,
                 methods=['lxml-dom-paragraphs','stdlib-htmlparser-paragraphs'],sample_method='raw-html-tag-paragraphs-all-retained',
                 sample_rows=[n+1 for n in retained],sample_passed=True,loaded_rows=1,
                 position_locator=locator,field_locators=row['field_locators'],retained_paragraphs=len(retained))
    return dict(title=position,rows=[row],proofs=[proof],published=published)


def validate_position_proof(row, proof):
    from career_on_demand import Gap, public_text
    if (row.get('year_basis') != 'publication_date' or row.get('recruitment_year') is not None or
        row.get('published','')[:4] != str(row['year']) or
        row.get('region_basis') not in {'explicit_attendance_requirement','explicit_position_location'} or
        not row.get('year_scope') or not row.get('region_raw') or
        row.get('position_locator') != proof.get('position_locator') or
        row.get('field_locators') != proof.get('field_locators') or
        proof.get('sample_method') != 'raw-html-tag-paragraphs-all-retained' or
        proof.get('methods') != ['lxml-dom-paragraphs','stdlib-htmlparser-paragraphs']):
        raise Gap('具体岗位年度、城市或定位证明缺失')
    try:
        dt.date.fromisoformat(row['published'])
    except (ValueError,TypeError):
        raise Gap('具体岗位发布日期无效') from None
    if row['region_basis']=='explicit_attendance_requirement':
        if row['region']!='宁波市' or row['region_raw']!='能够到宁波东方理工大学校内参与实习。':
            raise Gap('具体岗位到岗城市与原文不一致')
    else:
        city=re.fullmatch(r'中国·([^|]+)\s*\|\s*',row['region_raw'])
        if not city or not strict_city(city[1].strip(),row['region']):
            raise Gap('具体岗位工作城市与原文不一致')
    n=proof.get('original_rows');sample=proof.get('sample_rows')
    if (type(n)is not int or n<1 or not isinstance(sample,list)or not sample or
        len(set(sample)) != len(sample) or len(sample)!=proof.get('retained_paragraphs')or
        any(type(x)is not int or not 1<=x<=n for x in sample)):
        raise Gap('具体岗位全核段落定位无效')
    if set(row['field_locators'])!=set(row['fields']):
        raise Gap('具体岗位字段定位缺失')
    for field, locators in row['field_locators'].items():
        if field not in row['fields'] or not isinstance(locators,list) or (row['fields'][field] and not locators):
            raise Gap('具体岗位字段定位无效')
        for locator in locators:
            hit=re.fullmatch(re.escape(row['position_locator'])+r'/p\[(\d+)\]',locator)
            if not hit or int(hit[1])not in sample:
                raise Gap('具体岗位字段未逐段全核')
    for value in [row['position'],row['region_raw']]+list(row['fields'].values()):
        if value:public_text(value)


def parse_tngd(text,root,entry,request):
    from career_on_demand import Gap, public_text
    if entry['publisher'] not in norm(' '.join(root.itertext())):
        raise Gap('具体岗位原页未找到登记发布单位')
    containers=root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," fl-button-lightbox-content ")]')
    second=BodyReader(text,'fl-button-lightbox-content')
    try:second.feed(text);second.close()
    except Exception:raise Gap('具体岗位流式读取失败')from None
    rows=[];proofs=[]
    for index,c in enumerate(containers,1):
        titles=c.xpath('./h1')
        if len(titles)!=1:raise Gap('具体岗位标题不唯一')
        position=norm(''.join(titles[0].itertext()))
        if request['direction']not in position or '实习生'not in position or request['stage']!='internship':continue
        public_text(position)
        if second.headings.get(index)!=[position]:raise Gap('具体岗位标题两读不一致')
        if any('hidden'in n.attrib or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',n.get('style',''),re.I)for n in [c]+list(c.iterdescendants())):
            raise Gap('具体岗位存在未适配的隐藏内容')
        if c.xpath('.//script|.//style|.//table|.//form'):raise Gap('具体岗位正文结构超出已适配范围')
        grid=[norm(''.join(p.itertext()))for p in c.xpath('.//p')]
        streamed=[p for p,g in zip(second.paragraphs,second.groups)if g==index]
        if grid != [p[0]for p in streamed]:raise Gap('具体岗位两种读法逐段不一致')
        raw=[norm(unescape(re.sub('<[^>]+>','',re.sub(r'<br\s*/?>',' ',p[1],flags=re.I))))for p in streamed]
        if raw!=grid:raise Gap('具体岗位原始标签逐段全核不一致')
        if len(grid)<3:raise Gap('具体岗位正文缺少年度或城市')
        date=re.fullmatch(r'(\d{4}) 年 (\d{1,2}) 月 (\d{1,2}) 日',grid[0])
        city=re.fullmatch(r'中国·([^|]+)\s*\|\s*',grid[1])
        if not date or not city:raise Gap('具体岗位日期或工作地格式变化')
        if int(date[1])not in request['years']or not strict_city(city[1].strip(),request['region']):continue
        # Observed backend internship paragraphs; no cross-position field borrowing.
        if not grid[4].startswith('你将参与的工作')or not grid[6].startswith('任职要求'):
            raise Gap('具体岗位业务段结构变化，需重新适配')
        published=f'{int(date[1]):04}-{int(date[2]):02}-{int(date[3]):02}'
        requirements=[n for n in range(6,len(grid))if grid[n]]
        values={'duties':grid[4],'requirements':norm(' '.join(grid[n]for n in requirements)),
                'pay':None,'schedule':grid[6]}
        fields={k:values[k]for k in request['layers']}
        for v in fields.values():
            if v:public_text(v)
        locator=f'div.fl-button-lightbox-content[{index}]'
        mapping={'duties':[4],'requirements':requirements,'pay':[],'schedule':[6]}
        field_locators={k:[f'{locator}/p[{n+1}]'for n in mapping[k]]for k in fields}
        retained=sorted({0,1,4,*requirements})
        row=dict(region=request['region'],region_raw=grid[1],region_basis='explicit_position_location',year=int(date[1]),
                 year_basis='publication_date',published=published,recruitment_year=None,
                 year_scope='历史公告发布年度；资格届别仅按任职要求原文，不由日期推断',position=position,
                 stage='internship',stage_raw=position,fields=fields,src_table=index,src_row=1,
                 position_locator=locator,field_locators=field_locators,visibility_basis='inline_lightbox_static_html')
        proof=dict(kind='position-body-v1',src_table=index,original_rows=len(grid),dual_read_equal=True,
                   methods=['lxml-dom-paragraphs','stdlib-htmlparser-paragraphs'],sample_method='raw-html-tag-paragraphs-all-retained',
                   sample_rows=[n+1 for n in retained],sample_passed=True,loaded_rows=1,
                   position_locator=locator,field_locators=field_locators,retained_paragraphs=len(retained),
                   visibility_basis='inline_lightbox_static_html')
        rows.append(row);proofs.append(proof)
    if not rows:raise Gap('具体岗位正文没有匹配的城市、发布年度、岗位和实习阶段')
    return dict(title='TNGD Career｜'+ '、'.join(r['position']for r in rows),rows=rows,proofs=proofs,
                published=rows[0]['published'])


class CampusBlocks(HTMLParser):
    """Stream observed university-platform blocks; never serialize other content."""
    classes = ('job-information', 'describe-details', 'job-time')
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.text=text;self.stack=[];self.blocks={};self.offsets=[0]
        self.offsets.extend(m.end()for m in re.finditer('\n',text))
    def pos(self):
        line,col=self.getpos();return self.offsets[line-1]+col
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);hits=set(attrs.get('class','').split())&set(self.classes)
        if len(hits)>1:raise ValueError('ambiguous block')
        target=next(iter(hits),None)
        if target:
            if target in self.blocks:raise ValueError('duplicate block')
            self.blocks[target]={'tokens':[],'start':self.pos()+len(self.get_starttag_text())}
        if tag not in {'br','img','hr','meta','link','input','wbr','source'}:self.stack.append((tag,target))
    def handle_data(self,data):
        if not norm(data):return
        for _,target in self.stack:
            if target:self.blocks[target]['tokens'].append(norm(data))
    def handle_endtag(self,tag):
        for n in range(len(self.stack)-1,-1,-1):
            if self.stack[n][0]==tag:
                for _,target in self.stack[n:]:
                    if target:self.blocks[target]['raw']=self.text[self.blocks[target]['start']:self.pos()]
                del self.stack[n:];break


CAMPUS_SCOPE='高校就业平台职位原页，非雇主自有官网；招聘单位仅为页面登记，未独立认证用人主体、合同甲方或授权；不代表当前在招、本人资格或录用报价。'
CAMPUS_KEYS=('职位名称','职位类别','工作性质','月薪范围','学历要求','工作城市','招聘人数','招聘单位')


def parse_campus_position(text,root,entry,request):
    from career_on_demand import Gap,public_text
    if entry['publisher']!='郑州航空工业管理学院':raise Gap('高校就业平台发布者不匹配')
    if not re.fullmatch(r'/module/position_details/id-\d+/nid-\d+',urlsplit(entry['url']).path):raise Gap('不是已适配的高校具体职位原页')
    titles=root.xpath('//title/text()')
    if len(titles)!=1 or entry['publisher']not in titles[0]or '就业信息网'not in titles[0]:raise Gap('高校就业平台原页身份未对应')
    second=CampusBlocks(text)
    try:second.feed(text);second.close()
    except Exception:raise Gap('高校职位流式读取边界不一致')from None
    proof_blocks={};tokens={}
    for cls in CampusBlocks.classes:
        nodes=root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," '+cls+' ")]')
        if len(nodes)!=1 or cls not in second.blocks:raise Gap('高校职位业务块缺失或不唯一')
        node=nodes[0]
        if any('hidden'in n.attrib or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',n.get('style',''),re.I)for n in [node]+list(node.iterancestors())+list(node.iterdescendants())):raise Gap('高校职位业务块有显式隐藏内容')
        if node.xpath('.//script|.//style|.//form|.//table'):raise Gap('高校职位业务块结构未适配')
        first=[norm(x)for x in node.xpath('.//text()')if norm(x)]
        if first!=second.blocks[cls]['tokens']:raise Gap('高校职位两读逐格不一致')
        raw=norm(unescape(re.sub('<[^>]+>',' ',second.blocks[cls].get('raw',''))))
        if raw!=norm(' '.join(first)):raise Gap('高校职位原始标签全核不一致')
        selected=[(n+1,x)for n,x in enumerate(first)if (any(x.startswith(k+'：')for k in CAMPUS_KEYS)if cls=='job-information'else bool(re.fullmatch(r'\d{4}/\d{2}/\d{2}',x))if cls=='job-time'else True)]
        for _,x in selected:public_text(x)
        tokens[cls]=selected;proof_blocks[cls]={'original_tokens':len(first),'retained': [{'token':n,'text':x}for n,x in selected]}
    data={}
    for n,x in tokens['job-information']:
        key,value=x.split('：',1)
        if key in data:raise Gap('高校职位同字段多值')
        data[key]=(value,n)
    if set(data)!=set(CAMPUS_KEYS):raise Gap('高校职位关键原格缺失')
    if data['工作性质'][0]!='校招'or request['stage']!='graduate':raise Gap('高校职位没有明确匹配的校招阶段')
    if data['工作城市'][0]not in {'郑州','郑州市'}or request['region']!='郑州市':raise Gap('高校职位工作城市不匹配，不借单位所在地')
    position=data['职位名称'][0]
    if request['direction']not in position:raise Gap('高校职位名称不匹配')
    req=[x for _,x in tokens['describe-details']]
    if not req or req[0]!='任职要求'or len(req)<2:raise Gap('高校职位任职段结构变化')
    cohorts=re.findall(r'(?<!\d)(20\d{2})届(?:全日制)?应届毕业生',' '.join(req))
    if len(set(cohorts))!=1:raise Gap('高校职位招聘届别不唯一或未明确')
    year=int(cohorts[0])
    if year not in request['years']:raise Gap('高校职位届别不在查询范围，不借发布日期')
    dates=tokens['job-time']
    if len(dates)!=1:raise Gap('高校职位发布日期未明确或不唯一')
    published=dates[0][1].replace('/','-')
    try:dt.date.fromisoformat(published)
    except ValueError:raise Gap('高校职位日期无效')from None
    values={'duties':None,'requirements':' '.join(req),'pay':'月薪范围：'+data['月薪范围'][0],'schedule':None}
    fields={k:values[k]for k in request['layers']}
    locator='html-class:job-information';locs={k:([f'html-class:describe-details/nonempty-descendant-text:{n}'for n,_ in tokens['describe-details']]if k=='requirements'else[f'{locator}/nonempty-descendant-text:{data["月薪范围"][1]}']if k=='pay'else[])for k in fields}
    row=dict(region=request['region'],region_raw='工作城市：'+data['工作城市'][0],region_basis='explicit_campus_position_city',year=year,year_basis='explicit_recruitment_cohort',recruitment_year=year,published=published,year_scope='任职要求明确招聘届别；不由公告发布年推定',position=position,stage='graduate',stage_raw='校招',fields=fields,src_table=1,src_row=1,position_locator=locator,field_locators=locs,visibility_basis='public_static_html_blocks',source_scope=CAMPUS_SCOPE,employer_raw=data['招聘单位'][0],education_summary_raw='学历要求：'+data['学历要求'][0])
    proof=dict(kind='university-position-v1',src_table=1,original_rows=1,loaded_rows=1,dual_read_equal=True,sample_passed=True,methods=['lxml-dom-text-nodes','stdlib-htmlparser-class-blocks'],sample_method='raw-html-blocks-all-retained',locator_basis='class_block_normalized_nonempty_descendant_text_tokens',blocks=proof_blocks,position_locator=locator,field_locators=locs)
    validate_campus_proof(row,proof)
    return dict(title=norm(titles[0]),rows=[row],proofs=[proof],published=published)


def validate_campus_proof(row,proof):
    from career_on_demand import Gap,public_text
    if (proof.get('locator_basis')!='class_block_normalized_nonempty_descendant_text_tokens'or proof.get('kind')!='university-position-v1'or proof.get('methods')!=['lxml-dom-text-nodes','stdlib-htmlparser-class-blocks']or proof.get('sample_method')!='raw-html-blocks-all-retained'or proof.get('dual_read_equal')is not True or proof.get('sample_passed')is not True):raise Gap('高校职位双读全核证明缺失')
    if any(type(v)is not int or v!=1 for v in (row.get('src_table'),row.get('src_row'),proof.get('src_table'),proof.get('original_rows'),proof.get('loaded_rows'))):raise Gap('高校单职位原表行数或定位声明无效')
    if row.get('year_scope')!='任职要求明确招聘届别；不由公告发布年推定'or row.get('visibility_basis')!='public_static_html_blocks':raise Gap('高校职位口径说明或读取方式不一致')
    blocks=proof.get('blocks',{});texts={};locators={}
    for cls in CampusBlocks.classes:
        b=blocks.get(cls,{})
        if type(b.get('original_tokens'))is not int or b['original_tokens']<1 or not isinstance(b.get('retained'),list)or not b['retained']:raise Gap('高校职位抽核位置缺失')
        seen=set();texts[cls]=[]
        for cell in b['retained']:
            n=cell.get('token');v=cell.get('text')
            if type(n)is not int or n in seen or not 1<=n<=b['original_tokens']or not isinstance(v,str):raise Gap('高校职位抽核位置无效')
            seen.add(n);public_text(v);texts[cls].append(v);locators[f'html-class:{cls}/nonempty-descendant-text:{n}']=v
    vals={}
    for x in texts['job-information']:
        if '：'not in x:raise Gap('高校职位原格字段无效')
        key,value=x.split('：',1)
        if key not in CAMPUS_KEYS or key in vals:raise Gap('高校职位原格重复或包含非业务字段')
        vals[key]=value
    dates=texts['job-time'];req=texts['describe-details'];cohorts=re.findall(r'(?<!\d)(20\d{2})届(?:全日制)?应届毕业生',' '.join(req))
    if set(vals)!=set(CAMPUS_KEYS)or vals['工作性质']!='校招'or vals['工作城市']not in {'郑州','郑州市'}or len(dates)!=1 or not re.fullmatch(r'\d{4}/\d{2}/\d{2}',dates[0])or not req or req[0]!='任职要求'or len(set(cohorts))!=1:raise Gap('高校职位口径原格不能核对')
    if (row.get('region')!='郑州市'or row.get('region_raw')!='工作城市：'+vals['工作城市']or row.get('region_basis')!='explicit_campus_position_city'or row.get('year_basis')!='explicit_recruitment_cohort'or row.get('year')!=int(cohorts[0])or row.get('recruitment_year')!=int(cohorts[0])or row.get('published')!=dates[0].replace('/','-')or row.get('position')!=vals['职位名称']or row.get('stage')!='graduate'or row.get('stage_raw')!='校招'or row.get('source_scope')!=CAMPUS_SCOPE or row.get('employer_raw')!=vals['招聘单位']or row.get('education_summary_raw')!='学历要求：'+vals['学历要求']):raise Gap('高校职位结构值与原格不同')
    try:dt.date.fromisoformat(row['published'])
    except (ValueError,TypeError):raise Gap('高校职位日期无效')from None
    expected={'duties':None,'requirements':' '.join(req),'pay':'月薪范围：'+vals['月薪范围'],'schedule':None}
    if row.get('position_locator')!='html-class:job-information'or proof.get('position_locator')!=row['position_locator']or row.get('field_locators')!=proof.get('field_locators')or set(row.get('field_locators',{}))!=set(row.get('fields',{})):raise Gap('高校职位行级或字段定位缺失')
    for k,v in row['fields'].items():
        if k not in expected or v!=expected[k]:raise Gap('高校职位业务值与原段不同')
        ls=row['field_locators'][k]
        if not isinstance(ls,list)or len(set(ls))!=len(ls)or any(x not in locators for x in ls):raise Gap('高校职位字段没有原格支持')
        reconstructed=' '.join(locators[x]for x in ls)if ls else None
        if reconstructed!=v:raise Gap('高校职位字段与定位原文不同')
