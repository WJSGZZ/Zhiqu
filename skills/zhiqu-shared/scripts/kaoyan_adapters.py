"""Conservative, RAM-only official HTML adapters; unknown scopes stay pending.

Geometry is independently read twice by kaoyan_tables. Only literal, labelled
columns are mapped. No private roster row is returned or persisted.
"""
import datetime as dt
import hashlib
import json
import math
import random
import re
import statistics
from lxml import html
from kaoyan_tables import html_tables, _decode, _lxml_text, ARTICLE_IMAGE_XPATH
from ingest_kaoyan_lines import RAW, dump, privacy

class NeedsReview(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def samples(n, image=False):
    need = min(n, max(5 if image else 3, math.ceil(n * (.10 if image else .03))))
    return sorted(random.Random(20261020).sample(range(n), need))


def state(value, reason='原文明确列值'):
    return {'status': '来源未提供' if value is None else '官方原值',
            'reason': '原表未提供或未给明确数值，不推算' if value is None else reason}


def number(value):
    s = re.sub(r'\s+', '', value)
    if not re.fullmatch(r'\d{1,3}(?:\.\d+)?', s):
        raise NeedsReview('数值列含范围、符号或不明确文字，需人工核对整表')
    return float(s) if '.' in s else int(s)


BUSINESS_TITLE = {'lines':'复试|分数线','catalog':'目录|(?:招生|专业).*计划|计划.*分配','stats':'拟录取'}


def _names_school(text, school):
    before, found, after = text.partition(school)
    if not found or not re.fullmatch(r'(?:关于|公布|发布|印发|转发|20\d{2}年|[\s\W])*', before):
        return False
    # A university-name prefix is not an identity: a suffixed institution or
    # an unregistered college needs explicit review, not parent-school carry.
    after = after.lstrip(' \t\r\n（）()【】《》:：—-')
    if after.startswith('研究生院'):
        after = after[len('研究生院'):].lstrip(' \t\r\n（）()【】《》:：—-')
    if re.search(r'大学(?!生)|学院|研究所|研究院|党校|学校', after):
        return False
    return not after or bool(re.match(r'20\d{2}|硕士|研究生|招生|复试|初试|统考|全日制|非全日制', after))


def source_record(body, url, school, year, layer):
    root = html.fromstring(_decode(body))
    # Inline spans belong to one heading; distinct headings must not fuse.
    titles = [_lxml_text(node) for node in root.xpath('//h1 | //h2 | //title')]
    business_titles = [re.sub(r'\s+', ' ', x).strip() for x in titles
                       if str(year) in x and re.search(BUSINESS_TITLE[layer], x)]
    # Every heading claiming the requested year's business scope must be
    # attributable. A site masthead or a competing heading cannot lend its
    # school to another table; ambiguous/generic headings need manual review.
    if not business_titles or not all(_names_school(x, school) and set(re.findall(r'20\d{2}', x)) == {str(year)} for x in business_titles):
        raise NeedsReview('原页标题未能同时确认学校、年份和业务类型')
    title = business_titles[0]
    if any('博士'in x or '硕士'not in x for x in business_titles):raise NeedsReview('原页未单独明确硕士层次；不把博士/混合招生表当硕士入库')
    if layer == 'lines' and (not re.search('复试|分数线', title) or re.search('名单|成绩公示|成绩查询',title)):
        raise NeedsReview('原页并非明确复试线')
    if layer == 'catalog' and not re.search('目录|(?:招生|专业).*计划|计划.*分配', title):
        raise NeedsReview('原页并非招生目录或明确专业计划')
    if layer == 'stats' and (not re.search('拟录取', title) or re.search('不予拟录取|取消拟录取|未拟录取|未录取',title)):
        raise NeedsReview('原页不是明确拟录取名单，不据复试名单推录取')
    original_title_sha=hashlib.sha256(title.encode()).hexdigest()
    if layer=='stats':title=f'{school}{year}年拟录取名单初试总分匿名统计（原题指纹留存）'
    digest = hashlib.sha256(body).hexdigest()
    today = dt.date.today().isoformat()
    # Dates are accepted only from actual time/meta/date-labelled fields.
    dates = root.xpath('//time/@datetime | //meta[@name="PubDate"]/@content | //meta[@name="publishdate"]/@content')
    published = next((m.group(0) for x in dates for m in [re.search(r'20\d\d-\d\d-\d\d', x)] if m), '')
    return dict(source_id='src-ondemand-' + digest[:24], grade='官方', publisher=school,
                title=title, landing_url=url, file_url='', published=published, retrieved=today,
                method='两独立HTML解析器逐格和合并锚点核对；固定种子文本3%至少3行抽核',
                archive_sha256=digest, archive_path='', archive_status='已核后删除（有指纹）',
                wayback_url='', note='按需取数，仅原表明示范围；原件仅在内存中处理。原题SHA256='+original_title_sha,
                citation=f'{school}，{title}，{year}，{url}，取得日期{today}', license='未注明', producer_revision='')


HEAD = {
    '专业代码': 'code', '招生专业代码': 'code', '专业名称': 'name', '招生专业名称': 'name',
    '学院': 'college', '学院名称': 'college', '院系名称': 'college',
    '复试线': 'total', '复试分数线': 'total', '总分': 'total', '初试总分': 'initial', '初试成绩': 'initial',
    '政治':'politics','思想政治理论':'politics','英语':'english','数学':'math',
    '业务课一':'major1','业务课二':'major2',
    '单科(满分=100分)':'component_single_100',
    '单科(满分100分)':'component_single_100',
    '单科(满分>100分)':'component_single_gt100',
    '单科(满分大于100分)':'component_single_gt100',
    '政治、外国语':'component_politics_foreign_language_shared',
    '计划分配': 'planned', '招生人数': 'planned', '拟招生人数': 'planned',
    '招生人数(含推免)': 'planned', '拟招生人数(含推免)': 'planned',
    '推免人数':'tuimian', '拟接收推免人数':'tuimian', '初试科目':'subjects',
    '培养形式': 'mode', '学习方式': 'mode', '学科类型': 'degree', '学位类型': 'degree',
    '方向': 'direction', '研究方向': 'direction', '专项计划': 'special',
    '计划类别': 'special', '一志愿/调剂': 'route', '志愿类型': 'route',
    '联培单位': 'joint', '联合培养单位': 'joint', '考试科目': 'subjects',
    '专业代码、名称及研究方向': 'combined',
    '专业领域': 'combined', '招生专业': 'parent_program', '拟招生计划': 'planned',
    '学位类型及学制': 'degree_duration',
    '专业代码及名称': 'combined', '学习形式': 'mode',
    '学院(科研机构)代码及名称': 'college',
    '学院代码及名称': 'college', '专业名称及研究方向': 'combined',
    '招生专业代码、名称': 'combined', '类别代码、名称':'parent_program',
    '专业拟招生人数':'planned', '学习校区':'campus', '学制':'duration',
}
PRIVATE = {'姓名', '考生姓名', '考生编号', '考生号', '准考证号', '身份证号'}


def _heading(root, table_index):
    tables = root.xpath('//table[not(ancestor::table)]')
    if table_index > len(tables):
        raise NeedsReview('独立DOM表定位不一致')
    # Only the nearest preceding paragraph or heading. No previous-school carry.
    nodes = tables[table_index-1].xpath('preceding::*[self::p or self::h2 or self::h3]')
    raw = re.sub(r'\s+', '', _lxml_text(nodes[-1])) if nodes else ''
    if len(raw) > 200 or re.search(r'\d{12,18}|姓名|考生号|联系人|电话|邮箱', raw):
        return ''
    return raw


def _html_table_identity(dom_table, table, school, year, layer, programs):
    """Check local original scope, without searching arbitrary page prose.

    Nearest complete business scope plus intervening headings/paragraphs and
    the table's own caption form its context. Neutral/bare-school subheadings
    cannot reset inherited years or degrees.
    Other tables' cells never supply its institution.
    Unknown labels/long context fail closed; nothing from it is logged.
    """
    grid = table['rows']
    header = next((i for i, row in enumerate(grid[:5]) if any(HEAD.get(re.sub(r'\s+', '', x)) in {'code','combined'} for x in row)), None)
    if header is None:
        return  # The existing unmapped-programme guard owns this case.
    columns = [i for i,x in enumerate(grid[header]) if HEAD.get(re.sub(r'\s+','',x)) in {'code','combined'}]
    selected = [row for row in grid[header+1:] if any(
        (m := re.match(r'^\s*(S\d{6}|\d{4}[0-9A-Z]{2}|\d{4})(?=\D|$)', row[i])) and
        any(m[1].startswith(p) for p in programs) for i in columns)]
    if not selected:
        return
    preceding = dom_table.xpath('preceding::*[not(ancestor::table) and (self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6 or self::p)]')
    context = [_lxml_text(x) for x in dom_table.xpath('./caption | ancestor::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6 or self::p]')]
    for node in reversed(preceding):
        context.append(_lxml_text(node))
        text = _lxml_text(node)
        # A bare school label cannot reset an inherited year or degree. Only
        # a complete, self-contained scope starts a new table section.
        if (_names_school(re.sub(r'\s+', ' ', text).strip(), school)
                and set(re.findall(r'20\d{2}', text)) == {str(year)}
                and '硕士' in text and '博士' not in text
                and re.search(BUSINESS_TITLE[layer], text)):
            break
        if len(context) > 12:
            raise NeedsReview('原表局部标题/段落范围过长，学校归属需人工核对')
    for text in context:
        text = re.sub(r'\s+', ' ', text).strip()
        if _department_scope(text):
            continue  # Explicit department role, not a separate institution.
        business = bool(re.search(BUSINESS_TITLE[layer], text))
        explicit_school = bool(re.search(r'大学(?!生)|学院|研究所|研究院|党校|学校', text))
        labelled = re.match(r'^(?:学校|院校|招生单位)(?:名称)?[：:]\s*(.*)$', text)
        years = set(re.findall(r'20\d{2}', text))
        if not (business or explicit_school or labelled or years or '博士' in text):
            continue
        if len(text) > 300:
            raise NeedsReview('原表局部学校范围说明过长，需人工核对')
        name_text = labelled[1] if labelled else text
        if ((business or explicit_school or labelled) and not _names_school(name_text, school)) or (years and years != {str(year)}) or '博士' in text:
            raise NeedsReview('原表局部学校、年份或层次与请求不一致或未明确；不借网页总标题归属')
    labels = [re.sub(r'\s+','',x) for x in grid[header]]
    school_columns = [i for i,x in enumerate(labels) if re.fullmatch(r'(?:招生)?(?:学校|院校|高校|单位)(?:名称|名)?',x)]
    if any(re.search(r'学校|院校|高校|招生单位',x) and i not in school_columns
           and not re.search(r'毕业|本科|来源',x) for i,x in enumerate(labels)):
        raise NeedsReview('原表学校身份列尚未明确映射，需人工核对')
    year_columns = [i for i,x in enumerate(labels) if x in {'年份','年度','招生年份','招生年度','招生年','学年'}]
    level_columns = [i for i,x in enumerate(labels) if x in {'层次','招生层次','学历层次','培养层次'}]
    for row in selected:
        if any(row[i].strip() != school for i in school_columns):
            raise NeedsReview('原表显式学校列未唯一对应所问学校，需人工核对')
        if any(not re.fullmatch(str(year)+r'(?:年|年度|级)?',row[i].strip()) for i in year_columns):
            raise NeedsReview('原表显式年份列与请求不一致或未明确，需人工核对')
        if any(not re.fullmatch(r'(?:学术(?:学位)?|专业(?:学位)?)?硕士(?:研究生)?(?:[（(](?:全日制|非全日制|专业学位|学术学位)[）)])?',row[i].strip()) for i in level_columns):
            raise NeedsReview('原表显式招生层次不是明确硕士，需人工核对')


def _department_scope(text):
    department = re.fullmatch(r'(?:学院|院系|培养学院)[：:]\s*(.{1,60}(?:学院|系))', text.strip())
    return bool(department) and not re.search(r'大学|研究所|研究院|学校|党校|20\d{2}|博士|硕士|研究生', department[1])


def parse_official_html(body, url, identity, year, layer, programs):
    school, iid = identity['name'], identity['institution_id']
    source = source_record(body, url, school, year, layer)
    sid, digest = source['source_id'], source['archive_sha256']
    tables = html_tables(body)  # No output or persistence of raw grids.
    root = html.fromstring(_decode(body))
    if not tables and root.xpath(ARTICLE_IMAGE_XPATH):
        raise NeedsReview('原业务表为图片；需两种独立读图和10%至少5行抽核，尚未完成不入库')
    for table in tables:
        table['scope'] = _heading(root, table['table'])
        dom_table = root.xpath('//table[not(ancestor::table)]')[table['table']-1]
        trs = [tr for tr in dom_table.xpath('.//tr') if tr.xpath('ancestor::table[1]')[0] is dom_table]
        table['literal_cells'] = {(ri, ci): _lxml_text(cell) for ri, tr in enumerate(trs, 1)
                                  for ci, cell in enumerate(tr.xpath('./td|./th'), 1)}
        _html_table_identity(dom_table, table, school, year, layer, programs)
    return parse_verified_tables(tables, source, identity, year, layer, programs)


def parse_verified_tables(tables, source, identity, year, layer, programs):
    """Map already-agreed original cells; readers own geometry and third-read proof.

    HTML and PDF/image readers share semantic/privacy rules, not extraction.
    Nothing in this function persists or logs private source cells.
    """
    school, iid = identity['name'], identity['institution_id']
    sid, digest = source['source_id'], source['archive_sha256']
    url = source.get('file_url') or source['landing_url']
    output, proofs, pending, stat_scores = [], [], [], []
    stats_other_locs=[];score_labels=[];sampled_record_ids=set()
    for table in tables:
        grid, anchors = table['rows'], table['anchors']
        header = next((i for i, row in enumerate(grid[:5]) if
                       any(HEAD.get(re.sub(r'\s+', '', x)) in {'code', 'combined'} for x in row)), None)
        if header is None:
            # A second table may contain the requested programme with a new
            # header format. It cannot silently disappear from an obtained claim.
            for ri,row in enumerate(grid):
                codes=[re.match(r'^\s*(S\d{6}|\d{4}[0-9A-Z]{2}|\d{4})(?=\s|[（(\u4e00-\u9fff]|$)',cell) for cell in row]
                if any(m and any(m[1].startswith(p)or p.startswith(m[1])for p in programs)for m in codes):
                    pending.append({'table':table['table'],'row':ri+1,'reason':'另表含所问专业或上级代码，但表头未明确映射，范围尚待核对'})
            continue
        labels = [re.sub(r'\s+', '', x) for x in grid[header]]
        roles = {HEAD[x]: i for i, x in enumerate(labels) if x in HEAD}
        if len([HEAD[x] for x in labels if x in HEAD]) != len(roles):
            raise NeedsReview('重复业务表头，需原表人工定位')
        if not {'code', 'combined'} & roles.keys():
            continue
        if layer=='lines' and '类别'in labels:
            if labels.count('类别')!=1:raise NeedsReview('类别列不唯一，需原表核对')
            roles['category']=labels.index('类别')
        # A header rowspan may occupy a second physical tr. It is still a
        # header, not a data row or a valid random data sample.
        header_continuations={ri for ri in range(header+1,len(grid))
                              if grid[ri]==grid[header] and anchors[ri]==anchors[header]}
        if header_continuations and 'sample_row_indices'in table:
            raise NeedsReview('跨行表头的原页抽核须先按实际数据行重新核对')
        scope = table.get('scope', '')
        selected = []
        for row_index in range(header+1, len(grid)):
            if row_index in header_continuations:continue
            row = grid[row_index]
            raw_code = row[roles.get('code', roles.get('combined'))]
            if len(re.findall(r'(?<!\d)(?:\d{4}[0-9A-Z]{2}|S\d{6})(?!\d)',raw_code))>1:
                raise NeedsReview('一个原格包含多个专业代码，科目及计划分配未独立证明，不取第一个代码冒充整格')
            code_pattern=r'(?:\d{4}[0-9A-Z]{2}|S\d{6}|\d{4})' if layer=='lines' else r'(?:\d{4}[0-9A-Z]{2}|S\d{6})'
            match = re.match(r'^\s*('+code_pattern+r')(?=\D|$)', raw_code)
            if not match:
                # Directions may continue only under a real rowspan programme cell.
                if any(re.search(r'\d', x) for x in row):
                    raise NeedsReview('数据行专业代码不明确，不猜父行')
                continue
            code = match[1]
            if layer!='stats' and not any(code.startswith(p) for p in programs):
                continue
            selected.append((row_index, row, code, raw_code))
        if not selected:
            continue
        required = 'total' if layer == 'lines' else 'initial' if layer == 'stats' else 'planned'
        if required not in roles and layer!='catalog':
            pending.append({'table': table['table'], 'reason': '原表没有可直接映射的'+required+'列；需专项/方向人工核对'})
            continue
        if layer != 'stats' and PRIVATE.intersection(labels):
            raise NeedsReview('名单不是分数线/目录，禁止将个人行当业务事实')
        # A nonempty notes column can alter plan scope; never silently drop it.
        for label in ['备注', '说明']:
            if label in labels and any(row[labels.index(label)].strip() for _, row, _, _ in selected):
                raise NeedsReview('非空备注可能改变范围，需人工范围映射')
        physical = [ri for ri in range(header+1,len(grid))if ri not in header_continuations]
        sampled = table.get('sample_row_indices', [physical[i] for i in samples(len(physical))])
        def row_locator(ri):
            return dict({'page': 1, 'table': table['table'], 'row': ri+1},
                        **table.get('locations', {}).get(ri, {}))
        sample_locs = [row_locator(ri) for ri in sampled]
        proof = dict(table=table['table'], original_rows=len(physical), extracted_rows=len(physical),
                     dual_read_equal=True, sample_passed=True, sample_locators=sample_locs,
                     sample_count=len(sample_locs), sha256=digest, method=table.get('read_method', 'lxml及html.parser独立原格与跨度；原行锚点固定随机复读'),
                     selected_rows=len(selected))
        if header_continuations:proof['header_continuation_rows']=[row_locator(ri)for ri in sorted(header_continuations)]
        if table.get('cross_page_proofs'):proof['cross_page_proofs']=table['cross_page_proofs']
        proofs.append(proof)
        seen_origins = set()
        for ri, row, code, raw_code in selected:
            get = lambda key: row[roles[key]].strip() if key in roles else ''
            def literal(key):
                if key not in roles:return ''
                origin=anchors[ri][roles[key]]
                return table.get('literal_cells', {}).get(tuple(origin), row[roles[key]]) if origin!=[0,0] else ''
            loc = dict(sha256=digest, **row_locator(ri))
            mode = get('mode')
            if mode and mode not in {'全日制', '非全日制', '全日制、非全日制'}:
                raise NeedsReview('学习方式原列无法明确解释')
            degree=get('degree')
            row_scope=scope
            if 'category'in roles:
                category=re.sub(r'\s+','',get('category'))
                match=re.fullmatch(r'(学术硕士|专业硕士)\((全日制|非全日制)\)',category)
                if not match:raise NeedsReview('类别列的学位/学习方式或计划口径尚未明确映射')
                category_degree={'学术硕士':'学术学位','专业硕士':'专业学位'}[match[1]]
                if (mode and mode!=match[2])or(degree and degree!=category_degree):raise NeedsReview('类别与独立学位/学习方式列冲突，整份未入')
                degree,mode=category_degree,match[2]
                row_scope='；'.join(x for x in [scope,'原表类别：'+literal('category')]if x)
            special = get('special')
            if not special:
                special = next((x for x in ['少数民族高层次骨干人才计划', '退役大学生士兵计划'] if x in scope), '')
                if '普通考生' in scope:
                    special = '普通考生'
            name = get('name') or raw_code[len(code):].split('（')[0].split('(')[0].strip()
            parent = re.match(r'^(\d{4})(?=\D|$)',get('parent_program'))
            if get('parent_program') and (not parent or not code.startswith(parent[1])):
                raise NeedsReview('原表专业领域与上级专业代码不一致')
            if layer == 'stats':
                if any(row[i] for i, label in enumerate(labels) if label in {'备注', '说明'}):
                    raise NeedsReview('名单备注未完成范围拆分')
                # Initial total only. No personal field is retained in this tuple.
                value = number(get('initial'))
                if value > 500:
                    raise NeedsReview('初试总分范围不合理')
                score_labels.append(labels[roles['initial']])
                if not any(code.startswith(p)for p in programs):
                    stats_other_locs.append({k:loc[k]for k in ('page','table','row')});continue
                key = (code, get('college'), get('direction'), mode, special,
                       get('route') or '原表未注明', get('joint'))
                stat_scores.append((key, value, {k: loc[k] for k in ('page', 'table', 'row')}))
                continue
            origin = tuple(anchors[ri][roles.get('code', roles.get('combined'))])
            plan_origin_key=tuple(anchors[ri][roles['planned']])if 'planned'in roles else ()
            direction_scoped = 'direction' in roles and not re.fullmatch(r'\d+',literal('planned').strip())
            catalogue_key=(origin,plan_origin_key,mode,get('direction') if direction_scoped else '')
            if layer == 'catalog' and catalogue_key in seen_origins:
                continue
            seen_origins.add(catalogue_key)
            rid = fingerprint([sid, layer, loc, code])[:32]
            if ri in sampled:sampled_record_ids.add(rid)
            if layer == 'lines':
                unknown=[label for label in labels if re.search('单科|政治|外语|英语|数学|业务课',label) and label not in HEAD]
                if unknown:raise NeedsReview('单科表头尚未明确映射，需原表槽位核对；不把未映射说成来源未提供')
                raw = {k: None for k in RAW}
                raw.update(year=year, school=school, institution_id=iid, college=get('college') or None,
                           program_code=code, program_name=name, degree_type=degree or None,study_mode=mode or None,
                           total=number(get('total')), special_plan=special or None,
                           line_scope=row_scope or '原表未单列范围', note='只取原总分列；单科未提供',
                           read_method=table.get('read_method','文字双DOM'), source_url=url, src_locator=dump(loc))
                for field in ['politics','english','math','major1','major2']:
                    if field in roles:raw[field]=number(get(field))
                components={role[len('component_'):]:number(get(role)) for role in roles if role.startswith('component_')}
                mapped=[field for field in ['politics','english','math','major1','major2']if field in roles]
                if mapped or components:raw['note']='原总分及明示单科按原表槽位保留；未标科目不强行映射'
                output.append(dict(record_id=rid, institution_id=iid, source_id=sid, row=raw,
                                   src_page=loc['page'], src_table=str(loc['table']), src_row=str(loc['row']),
                                   locator=loc, excerpt=dump(dict({'专业代码': literal('code'), '总分': literal('total')},**({'类别':literal('category')}if 'category'in roles else{}),**{label:literal(HEAD[label])for label in labels if HEAD.get(label)in mapped or HEAD.get(label,'').startswith('component_')})),components=components,
                                   review=dict(status='approved', method=proof['method'], file_proof=proof),
                                   scope_context=dict(direction=get('direction'), joint_program=get('joint'),
                                                      admission_route=get('route'), scope_raw=row_scope),
                                   field_status={k: state(raw.get(k)) for k in ['year','total','politics','english','math','major1','major2']}))
            else:
                plan_raw = literal('planned').strip()
                tui_raw=literal('tuimian').strip()
                tui=int(tui_raw)if re.fullmatch(r'\d+',tui_raw)else None
                planned = int(plan_raw) if re.fullmatch(r'\d+', plan_raw) else None
                plan_origin=tuple(anchors[ri][roles['planned']])if 'planned'in roles else origin
                shared_codes={re.match(r'^\s*(\d{4}[0-9A-Z]{2}|S\d{6})',grid[j][roles.get('code',roles.get('combined'))])[1] for j in range(header+1,len(grid)) if ('planned'not in roles or tuple(anchors[j][roles['planned']])==plan_origin) and re.match(r'^\s*(\d{4}[0-9A-Z]{2}|S\d{6})',grid[j][roles.get('code',roles.get('combined'))])}
                if 'planned'not in roles:shared_codes={code}
                if len(shared_codes)>1:planned=None
                if 'tuimian'in roles:
                    tui_origin=tuple(anchors[ri][roles['tuimian']])
                    tui_codes={grid[j][roles.get('code',roles.get('combined'))]for j in range(header+1,len(grid))if tuple(anchors[j][roles['tuimian']])==tui_origin}
                    if len(tui_codes)>1:tui=None
                related = [j for j in range(header+1, len(grid)) if tuple(anchors[j][roles.get('code', roles.get('combined'))]) == origin and ('planned'not in roles or tuple(anchors[j][roles['planned']])==plan_origin) and ('mode'not in roles or grid[j][roles['mode']].strip()==mode)]
                if direction_scoped:related=[j for j in related if grid[j][roles['direction']].strip()==get('direction')]
                if 'direction'in roles and len({grid[j][roles['direction']]for j in related})>1:raise NeedsReview('原合并计划跨多个方向，需父子范围核对，不复制人数')
                subjects = list(dict.fromkeys(grid[j][roles['subjects']] for j in related)) if 'subjects' in roles else []
                if 'combined' in roles and not mode:
                    mode_match = re.search(r'全日制(?:、非全日制)?|非全日制', raw_code)
                    mode = mode_match[0] if mode_match else ''
                output.append(dict(record_id=rid, institution_id=iid, school=school, college=get('college') or None,
                                   program_code=code, program_name=name, degree_type=get('degree') or
                                   next((x for x in ['学术学位','专业学位']if x in (get('degree_duration')+raw_code)),None),
                                   year=year, study_mode=mode or None, direction=get('direction') or None,
                                   direction_raw=get('direction'), special_plan=special or None,
                                   scope='原表专业拟招计划或目录', scope_raw=scope or source['title'], source_id=sid,
                                   src_page=loc['page'], src_table=str(loc['table']), src_row=str(loc['row']),
                                   locator_method=table.get('read_method','文字双DOM原合并锚点'), locator_status='原页表行与指纹已留',
                                   planned=planned, planned_raw=plan_raw, planned_scope='原人数格跨多个专业，未分配' if len(shared_codes)>1 else (scope or '原表未声明推免/专项是否包含'),
                                   subjects='；'.join(subjects) or None, tuimian=tui,
                                   extra_json=dump({'raw_program_cell': literal('code') or literal('combined'), 'parent_program_raw':get('parent_program'), 'campus_raw':get('campus'), 'degree_duration_raw':get('degree_duration'), 'duration_raw':get('duration'), 'shared_plan_origin':list(plan_origin), 'shared_plan_codes':sorted(shared_codes), 'joint_program_raw':get('joint'), 'admission_route_raw':get('route'), 'tuimian_raw':tui_raw, 'original_plan_header':labels[roles['planned']]if 'planned'in roles else None, 'locator': loc,
                                                    'continuation_rows': [j+1 for j in related], 'file_proof': proof}),
                                   value_status=dump({'planned': state(planned), 'tuimian': state(tui)})))
    if layer == 'stats':
        groups = {}
        for key, score, loc in stat_scores:
            groups.setdefault(key, []).append((score, loc))
        excluded = len(stats_other_locs)
        small_excluded=0
        for key, vals in groups.items():
            if len(vals) < 3:
                excluded += len(vals);small_excluded+=len(vals)
                continue
            code, college, direction, mode, special, route, joint = key
            scores = [v[0] for v in vals]
            output.append(dict(record_id=fingerprint([sid, key])[:32], institution_id=iid, school=school,
                               college=college or None, program_code=code, program_name=None, degree_type=None,
                               year=year, study_mode=mode or None, list_type='拟录取', admission_route=route,
                               special_plan=special or None, direction=direction or None, joint_program=joint or None,
                               n=len(scores), min=min(scores), median=statistics.median(scores), max=max(scores),
                               source_id=sid, src_page=vals[0][1]['page'] if len({v[1]['page'] for v in vals})==1 else None,
                               src_table='匿名分组', src_row=dump([v[1] for v in vals]),
                               scope_raw='原名单逐专业/学院/方向/学习方式/专项/志愿分开，未注明保持未知'))
        # File statistics only; no scores or private rows leave RAM.
        locs = [v[2] for v in stat_scores]+stats_other_locs
        indices = samples(len(locs))
        manifest = dict(sources=[source], rows=output, files=[dict(source_id=sid,
            original_rows=len(locs), included_rows=sum(r['n'] for r in output), excluded_rows=excluded,
            exclusions={'n小于3':small_excluded,'非所问专业':len(stats_other_locs)}, sample_count=len(indices), sample_locators=[locs[i] for i in indices],
            sample_passed=True, dual_read_equal=True, score_column=score_labels[0]if score_labels else '初试总分', method='双DOM内存聚合', review_status='approved')])
    else:
        manifest = {'sources': [source], 'rows': output}
        if layer == 'catalog':
            manifest['samples'] = []
            for row in output:
                if row['record_id'] not in sampled_record_ids:
                    continue
                manifest['samples'].append(dict(sample_id=fingerprint(['sample', row['record_id']])[:32], domain='考研',
                    table_name='ky_program_year', row_key=row['record_id'], field='planned', db_value=str(row['planned']),
                    official_value=str(row['planned']), official_source_id=sid, verdict='一致', checked_on=source['retrieved'],
                    reason='两独立读法原格相同，固定样本通过', excerpt=row['planned_raw'],
                    locator=dump({'page':row['src_page'],'table':row['src_table'],'row':row['src_row'],'sha256':digest}), reviewer='双读程序'))
    privacy(manifest)
    return {'manifest': manifest, 'proofs': proofs, 'pending': pending, 'rows': len(output),
            'suppressed_groups':sum(len(v)<3 for v in groups.values())if layer=='stats'else 0}
