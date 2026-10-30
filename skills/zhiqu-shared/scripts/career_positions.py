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
