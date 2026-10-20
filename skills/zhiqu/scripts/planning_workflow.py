"""Shared staged checks and deterministic assembly for graduate/career reports.

Only Python standard library. Business quantities live in report-contract.json.
No network access and no evaluation of expressions supplied in case files.
"""
import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from profile_store import active_profile, parse_profile, source_files, alignment_errors

SKILLS = Path(__file__).resolve().parents[2]
FILES = ('case.json', 'profile_parse.json', 'directions.json', 'rules_check.json',
         'candidates.json', 'evidence.json', 'calculations.json', 'judgment.json', 'narrative.json')
PITFALLS = ('没查到写成不存在', '群体数字当个人概率', '经验帖数字做决定', '按编号引用问卷',
            '同一事实写两处', '会过期的事实', '八字越界', '委派判断类任务', '取页摘要当原文')
RUBRIC = ('clarity', 'traceability', 'reasoning', 'consistency', 'timeliness', 'personalization',
          'actionability', 'boundaries', 'summary_access', 'layout')
PROFILE_FIELDS = {
 'grad': ('年级','专业','院校层次','均分或排名','英语','数学基础','读研动机','目标方向','预算','能否二战','目标地区'),
 'career': ('学历','专业','毕业时间','求职阶段','经历','证书','目标岗位','收入底线','城市','单位类型偏好','户籍','政治面貌','多快需要收入')}
# 报告里画成图的组件：都必须有图题、读图说明和来源；没数据时改成一行缺口说明。
FIGURE_TYPES = ('bars','interval','timeline','comparison_matrix','flow','stack','facts','cost')
REF = re.compile(r'\{\{(e|c|k|p):([^{}|]+?)(?:\|([^{}]+))?\}\}')
NUMBER = re.compile(r'(?<![A-Za-z])\d[\d,]*(?:\.\d+)?(?:%|％)?')
CHINESE_QUANTITY = re.compile(r'[零〇一二两三四五六七八九十百千万]+(?=\s*(?:元|分(?!位|制|比)|人|名|个月|万元|%))')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pointer(obj, path):
    if path == '': return obj
    if not path.startswith('/'): raise ValueError('JSON Pointer must start with /')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def walk(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items(): yield from walk(v, path+'/'+str(k).replace('~','~0').replace('/','~1'))
    elif isinstance(obj, list):
        for i, v in enumerate(obj): yield from walk(v, path+'/'+str(i))
    else: yield path, obj


def day(value):
    if not isinstance(value, str) or not DATE.fullmatch(value): raise ValueError('日期须为YYYY-MM-DD')
    return date.fromisoformat(value)


CN_DIGITS={c:i for i,c in enumerate('零一二三四五六七八九')}|{'〇':0,'两':2,'兩':2}
CN_UNITS={'十':10,'拾':10,'百':100,'佰':100,'千':1000,'仟':1000}


def cn_number(text):
    """“十八萬三千九百六十” -> 183960；官方页面常用中文大写金额。"""
    total=section=digit=0
    for ch in text:
        if ch in CN_DIGITS:digit=CN_DIGITS[ch]
        elif ch in CN_UNITS:section+=(digit or 1)*CN_UNITS[ch];digit=0
        elif ch in '萬万':total+=(section+digit)*10000;section=digit=0
        elif ch in '億亿':total=(total+section+digit)*100000000;section=digit=0
    return total+section+digit


def with_arabic(text):
    """在摘录后附上中文数字的阿拉伯写法，供数值比对；原摘录不改。"""
    runs=re.findall(r'[零〇一二两兩三四五六七八九十拾百佰千仟萬万億亿]{2,}',str(text))
    return str(text)+''.join(' '+str(cn_number(r)) for r in runs)


def excerpt_contains(value, excerpt):
    """Compare exact values allowing typographic commas/spaces, Chinese date notation and Chinese numerals."""
    excerpt=with_arabic(excerpt)
    def clean(text):return re.sub(r'[\s,，]','',str(text))
    needle=clean(value);haystack=clean(excerpt).replace('：',':')
    if not needle:return False
    if re.fullmatch(r'\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d(?::\d\d)?)?',str(value)):
        from datetime import datetime
        d=datetime.fromisoformat(str(value));parts=[str(d.year),f'{d.month}月{d.day}日']
        if 'T' in str(value) or ' ' in str(value):parts.append(d.strftime('%H:%M').lstrip('0'))
        return needle in haystack or all(p in haystack for p in parts) or (str(d.year) in haystack and f'{d.month}月' in haystack and f'{d.day}日' in haystack and (len(parts)<3 or parts[-1] in haystack))
    if isinstance(value,(float,int)) or re.fullmatch(r'\d+(?:\.\d+)?%?',needle):
        return bool(re.search(r'(?<![\d.])'+re.escape(needle)+(r'0*' if '.' in needle else r'(?:\.0+)?')+r'(?![\d.])',str(excerpt).replace(',', '').replace('，', '')))
    return needle in haystack


class PlanningCase:
    def __init__(self, root):
        self.root = Path(root)
        self.data = {f: read(self.root/f) for f in FILES if (self.root/f).is_file()}
        self.case = self.data.get('case.json', {})
        self.kind = self.case.get('kind')
        if self.kind not in PROFILE_FIELDS: raise ValueError('case.json.kind：须为grad/career')
        self.contract = read(SKILLS/f'zhiqu-{self.kind}/references/report-contract.json')
        self.limits = self.contract['workflow_limits']
        self.evidence = {e['id']: e for e in self.data.get('evidence.json', {}).get('items', [])}
        self.errors = []
        self.trace = []

    def contract_path(self):
        return SKILLS/f'zhiqu-{self.kind}/references/report-contract.json'

    def err(self, file, field, message):
        self.errors.append(f'{file}:{field}：{message}')

    def need(self, file):
        if file not in self.data: self.err(file, '', '缺阶段文件'); return {}
        return self.data[file]

    def resolve(self, kind, path):
        if kind == 'e':
            eid, sep, part = path.partition('#')
            if not sep: raise ValueError('证据引用须含#与JSON Pointer')
            if self.evidence[eid].get('status')=='unretrieved' and part.startswith('/value') and self.evidence[eid].get('value') is not None:raise ValueError('未取到原文的数值不能当已核事实展示')
            return pointer(self.evidence[eid], part)
        file = {'c':'calculations.json','k':'case.json','p':'profile_parse.json'}[kind]
        if kind == 'k' and not self.registration_allowed(path): raise ValueError('官方规则不能用登记字段替代证据')
        if kind == 'p':
            if not re.match(r'^/fields/\d+/value(?:/|$)',path): raise ValueError('画像引用只能读取本人value')
            field = pointer(self.data[file], '/'+ '/'.join(path.lstrip('/').split('/')[:2]))
            if field.get('status') != 'given' or field.get('category') not in ('fact','preference','constraint','self_judgment'):
                raise ValueError('画像直接引用须为本人given字段')
        return pointer(self.data[file], path)

    @staticmethod
    def registration_allowed(path):
        return bool(re.match(r'^/(?:target_year|education|graduation_date|education_entry|birth_datetime|decision_date|target_date|context/(?:as_of|personal_dates)|budget/(?:annual_limit|monthly_living_assumption|take_home_assumption|monthly_housing_assumption|monthly_other_expenses_assumption))(?:/|$)', path))

    @staticmethod
    def format(value, fmt=None):
        if value is None: return '未取到'
        if isinstance(value, (dict,list)): raise ValueError('引用必须定位到单个可显示值')
        if not fmt or fmt=='text': return str(int(value)) if isinstance(value,float) and value.is_integer() else str(value)
        if fmt in ('md','md_short','md_hm','ymd_cn','ym','ym_cn','year','month','day','datetime','hm'):
            from datetime import datetime
            parsed=datetime.fromisoformat(str(value))
            return {'md':f'{parsed.month} 月 {parsed.day} 日','md_short':f'{parsed.month:02d}-{parsed.day:02d}','md_hm':f'{parsed.month:02d}-{parsed.day:02d} '+parsed.strftime('%H:%M'),
                    'ymd_cn':f'{parsed.year} 年 {parsed.month} 月 {parsed.day} 日','ym':f'{parsed.year}.{parsed.month:02d}',
                    'ym_cn':f'{parsed.year} 年 {parsed.month} 月','day':str(parsed.day),'month':str(parsed.month),'year':str(parsed.year),'datetime':parsed.strftime('%Y-%m-%d %H:%M'), 'hm':parsed.strftime('%H:%M')}[fmt]
        if fmt in ('yuan','arabic'):
            label=str(value).removesuffix('元')
            digits={ch:i for i,ch in enumerate('零一二三四五六七八九')};digits.update({'〇':0,'两':2})
            total=section=number=0
            for ch in label:
                if ch in digits:number=digits[ch]
                elif ch in '十百千':section+=(number or 1)*{'十':10,'百':100,'千':1000}[ch];number=0
                elif ch in '万亿':total+=(section+number)*{'万':10000,'亿':100000000}[ch];section=number=0
                else:raise ValueError('不支持的中文数值')
            value=total+section+number
            return f'{value:,}' if fmt=='yuan' else str(value)
        if fmt == 'chinese':
            number=int(value)
            if number!=float(value) or not 0<=number<100:raise ValueError('中文计数显示仅支持非负两位整数')
            digits='零一二三四五六七八九'
            if number<10:return digits[number]
            tens,ones=divmod(number,10)
            return (digits[tens] if tens>1 else '')+'十'+(digits[ones] if ones else '')
        if fmt == 'abs_comma': return f'{abs(float(value)):,.0f}'
        if fmt == 'comma': return f'{float(value):,.0f}'
        if fmt == '1f': return f'{float(value):.1f}'
        if fmt == 'percent0': return f'{float(value):.0%}'
        if fmt == 'percent1': return f'{float(value):.1%}'
        raise ValueError('未知显示格式：'+fmt)

    def personal_inputs(self):
        """Return exact registration pointers, never infer provenance from equal numbers."""
        return [{'id':e['id'],'value':e.get('value'),'registration_ref':e.get('registration_ref')}
                for e in self.evidence.values() if e.get('publication_status')=='personal_input']

    def evidence_integrity_errors(self):
        errors=[]
        report=(self.root/'report.md').read_text() if (self.root/'report.md').exists() else ''
        sentences={re.sub(r'[*`\s]','',x).strip('。！？') for x in re.split(r'[。！？\n]',report)}
        cited=set()
        for sid,entries in self.nodes().items():
            for entry in entries:
                for _,value in walk(self.get_node(entry['ref']).get('content',{})):
                    if isinstance(value,str):
                        cited.update(m[2].split('#')[0] for m in REF.finditer(value) if m[1]=='e')
        # Numeric inputs also matter when only their calculated result is displayed.
        for file,obj in self.data.items():
            if file=='evidence.json':obj=obj.get('report_blocks',{})
            for _,value in walk(obj):
                if isinstance(value,str):cited.update(m[2].split('#')[0] for m in REF.finditer(value) if m[1]=='e')
        for e in self.evidence.values():
            where='evidence.json.items.'+e['id'];value=e.get('value');claim=e.get('claim','')
            if isinstance(value,(dict,list)):errors.append(where+'.value：证据只允许单个值，不得用字典或列表')
            normalized=re.sub(r'[*`\s]','',claim).strip('。！？')
            if normalized and (normalized in sentences or re.search(r'\{\{|\*\*|\n|\[\d+\]',claim)):
                errors.append(where+'.claim：须用原子事实标签，不能复制报告原句或模板')
            if e.get('publication_status')=='personal_input':
                source=e.get('source',{})
                if source.get('url') or re.search(r'大学|学院|教育部|政府|人社|招生办|考试院|税务|司法部|公务员局|组织部|财政部|国家电网|南方电网',source.get('organization','')+' '+claim):
                    errors.append(where+'.source：personal_input不得带官方网址或官方机构名')
                try:
                    file,sep,path=e.get('registration_ref','').partition('#')
                    if not sep or file not in ('case.json','profile_parse.json'):raise ValueError('缺登记字段')
                    if file=='case.json' and not self.registration_allowed(path):raise ValueError('不是客户登记字段')
                    if file=='profile_parse.json':
                        self.resolve('p',path)
                    actual=pointer(self.data[file],path)
                    if value is None or isinstance(actual,(dict,list)) or type(actual)!=type(value) or actual!=value:raise ValueError('登记值不一致')
                except (ValueError,KeyError,IndexError,TypeError):errors.append(where+'.registration_ref：personal_input的值必须精确对应登记字段')
            if e.get('grade')=='官方' and e.get('status')=='verified' and e['id'] in cited:
                if value is None or not excerpt_contains(value,e.get('excerpt','')):errors.append(where+'.excerpt：报告引用的官方值未出现在原文摘录中')
                if e.get('excerpt')==claim or len(e.get('excerpt','').splitlines())>2:errors.append(where+'.excerpt：须为不超过两行的原文摘录，不能用claim代替')
        return errors

    def expand(self, text, location=''):
        def sub(m):
            value = self.resolve(m[1],m[2]); out = self.format(value,m[3])
            self.trace.append({'location':location,'ref':m[0],'value':value,'display':out})
            return out
        return REF.sub(sub,str(text))

    def numeric_errors(self, text, location=''):
        errors=[]
        try: self.expand(text,location)
        except (KeyError,IndexError,ValueError,TypeError) as exc: errors.append(f'{location}：引用无法解析：{exc}')
        plain=REF.sub('',str(text))
        plain=re.sub(r'\[\d+(?:,\d+)*\]', '',plain)
        plain=re.sub(r'https?://\S+', '',plain)
        plain=re.sub(r'\d{4}-(?:GK|YJ|QZ)-(?:\d{4}|[SR]\d{2})','',plain)
        # Structural counts and ordinals are not factual policy amounts.
        plain=re.sub(r'(?:第\s*[零一二两三四五六七八九十百\d]+\s*(?:个|条|节|项|章|页|志愿)|[零一二两三四五六七八九十\d]+\s*(?:件事|条路|个方向|条路径|项任务|个候选))','',plain)
        plain=re.sub(r'页码\s*\d+\s*/\s*\d+','',plain)
        plain=re.sub(r'^\s*\d+[.)、]\s*','',plain,flags=re.M)
        year=str(self.case.get('target_year',''))
        if year: plain=re.sub(r'(?<!\d)'+re.escape(year)+r'(?=\s*[年届])','',plain)
        for m in list(NUMBER.finditer(plain))+list(CHINESE_QUANTITY.finditer(plain)):
            errors.append(f'{location}：数字“{m[0]}”无证据/计算/登记引用')
        return errors

    def numeric_tree(self, node, location):
        # Numbers in report rows must also be bound, rather than hidden as JSON numbers.
        errs=[]
        for path,value in walk(node):
            if isinstance(value,str): errs.extend(self.numeric_errors(value,location+path))
            elif isinstance(value,(int,float)) and not isinstance(value,bool): errs.append(location+path+'：数值未绑定引用')
        return errs

    def nodes(self):
        return self.data.get('judgment.json',{}).get('presentation',{})

    def get_node(self, ref):
        file, sep, path=ref.partition('#')
        if not sep or file not in FILES: raise ValueError('非法阶段节点引用：'+ref)
        return pointer(self.data[file],path)

    def active(self, slot):
        cond=slot.get('condition','always')
        if cond=='always': return True
        if cond=='offer_basis_actual_or_scenario': return self.case.get('context',{}).get('offer_basis') in ('actual','scenario')
        if cond=='offer_basis_none': return self.case.get('context',{}).get('offer_basis')=='none'
        if cond=='matrix_unknown_ratio_gt_0_7':
            matrix=self.data.get('judgment.json',{}).get('matrix',{}); cells=matrix.get('cells',[])
            return bool(cells) and sum(x.get('status')=='unknown' for x in cells)/len(cells)>self.contract['matrix_policy']['unknown_ratio_explanation_above']
        raise ValueError('合同条件未实现：'+cond)

    def has_complete_mock(self):
        """The record must identify a complete comparable mock and a real score reference.

        This validates the declared record, not the authenticity of a person's exam.
        The operator still checks the paper, subjects and completion conditions.
        """
        assessment=self.data.get('candidates.json',{}).get('personal_difficulty',{})
        mock=assessment.get('mock_exam')
        if not mock:return False
        try:
            if mock.get('complete') is not True or mock.get('same_subjects') is not True:return False
            if not isinstance(mock.get('subjects'),list) or not mock['subjects'] or any(not isinstance(v,str) or not v.strip() for v in mock['subjects']):return False
            if not mock.get('evidence_refs'):return False
            if any(eid not in self.evidence or self.evidence[eid].get('status')!='verified' for eid in mock['evidence_refs']):return False
            if day(mock['exam_date'])>day(self.case['context']['as_of']):return False
            match=REF.fullmatch(mock['score_ref'])
            if not match or match[1] not in ('p','e'):return False
            if match[1]=='e':
                eid=match[2].split('#')[0]
                if eid not in mock['evidence_refs']:return False
                e=self.evidence[eid]
                if e.get('unit')!='分' or not re.search(r'模考|模拟考试',e.get('claim','')+' '+e.get('scope','')):return False
            else:
                field=pointer(self.data['profile_parse.json'],'/'+ '/'.join(match[2].lstrip('/').split('/')[:2]))
                if not re.search(r'模考|模拟考试',field.get('field','')+' '+field.get('quote','')):return False
            score=self.resolve(match[1],match[2])
            return isinstance(score,(int,float)) and not isinstance(score,bool) and score>=0
        except (KeyError,ValueError,TypeError,IndexError):return False

    def figure_has_data(self, typ, content):
        rows=content.get('rows',[])
        def number(value):
            try:
                import math
                result=float(self.expand(value).replace(',',''))
                return result if math.isfinite(result) else None
            except (TypeError,ValueError,KeyError,IndexError):return None
        if typ=='interval':
            return any(len(row)>=3 and number(row[1]) is not None and number(row[2]) is not None
                       and number(row[1])<=number(row[2]) for row in rows)
        if typ=='bars':return any(len(row)>=2 and number(row[1]) is not None for row in rows)
        if typ=='stack':return any(len(row)>=2 for row in rows)
        if typ=='cost':return any(len(row)>=3 for row in rows)
        return bool(rows)

    def contract_errors(self):
        errs=[]; narrative=self.data.get('narrative.json',{}).get('sections',{})
        if set(narrative)!=set(s['id'] for s in self.contract['sections']): errs.append('narrative.json.sections：须逐节覆盖内容合同')
        for section in self.contract['sections']:
            sid=section['id']; entries=self.nodes().get(sid,[]); slots={s['key']:s for s in section['slots']}; counts={k:0 for k in slots}
            for i,entry in enumerate(entries):
                where=f'judgment.json.presentation.{sid}[{i}]'
                try:
                    key=entry['slot']; cfg=slots[key]; node=self.get_node(entry['ref']); typ=node['type']
                    if typ not in cfg.get('node_types',[cfg['component']]): raise ValueError(f'组件{typ}不属于{key}')
                    file,_,path=entry['ref'].partition('#')
                    if not any(file==x['file'] and (not x['pointer'] or path==x['pointer'] or path.startswith(x['pointer'].rstrip('/')+'/')) for x in cfg['from']):
                        raise ValueError('数据来自未授权阶段文件/位置')
                    content=node.get('content',{}); n=len(content.get('items',content.get('rows',[content]))) if cfg['count_by']=='items' else 1
                    counts[key]+=n
                    if cfg['source_required'] and not node.get('evidence_refs') and not node.get('calc_refs') and not node.get('registration_refs'):
                        errs.append(where+'：缺来源引用')
                    refs=node.get('evidence_refs',[])
                    if any(eid not in self.evidence for eid in refs): errs.append(where+'：来源ID不存在')
                    errs.extend(self.numeric_tree(node.get('content',{}),where+'.content'))
                    if typ=='data_gap':
                        if not all(content.get(k) for k in ('missing','source','expected_by')):errs.append(where+'：图表缺口须写缺什么、去哪取、预计何时补')
                        else:
                            try:day(self.expand(content['expected_by']))
                            except (ValueError,KeyError,TypeError):errs.append(where+'：图表缺口预计补齐日期无效')
                    if typ in FIGURE_TYPES:
                        if not self.figure_has_data(typ,content):errs.append(where+'：没有可画数据，须改为一行缺口说明')
                        if not all(node.get('content',{}).get(k) for k in ('title','caption')): errs.append(where+'：图缺标题或读图说明')
                    if typ=='dated_actions':
                        for action in node.get('content',{}).get('items',[]):
                            try:
                                deadline=self.expand(action['date'],where);day(deadline)
                                if not action.get('text'): raise ValueError('缺行动内容')
                            except (KeyError,ValueError): errs.append(where+'：摘要事项缺有效日期')
                    if file=='narrative.json':
                        if typ not in ('analysis','conclusion_sentence','titled_points','unknown_explanation','disclaimer'):errs.append(where+'：叙述不能携带结构化组件')
                        for _,text in walk(content):
                            if isinstance(text,str) and re.search(r'(?m)^\s*(?:#{1,2}\s|:::|\|)',text): errs.append(where+'：叙述包含整章标题、表格或组件')
                    if typ=='titled_points':
                        if any(not a.get('title') or not a.get('text') for a in node.get('content',{}).get('items',[])): errs.append(where+'：核心结论缺小标题或短句')
                except (KeyError,IndexError,ValueError,TypeError) as exc: errs.append(where+'：'+str(exc))
            for key,cfg in slots.items():
                n=counts[key]
                if not self.active(cfg): continue
                if n<cfg['min'] or (cfg['max'] is not None and n>cfg['max']): errs.append(f'内容合同.{sid}.{key}：现有{n}，要求{cfg["min"]}…{cfg["max"]}')
            allowed={s.get('narrative_key','').split('.',1)[-1] for s in slots.values() if s.get('narrative_key')} | {'title'}
            extra=set(narrative.get(sid,{}))-allowed
            if extra: errs.append(f'narrative.json.sections.{sid}：未登记叙述位置{sorted(extra)}')
        matrix=self.data.get('judgment.json',{}).get('matrix',{}); policy=self.contract['matrix_policy']
        if len(matrix.get('options',[]))<policy['min_options'] or len(matrix.get('dimensions',[]))<policy['min_dimensions']: errs.append('judgment.json.matrix：选项/维度少于合同要求')
        pairs=[(c.get('candidate_id'),c.get('dimension_id')) for c in matrix.get('cells',[])]
        expected={(o,d['id']) for o in matrix.get('options',[]) for d in matrix.get('dimensions',[])}
        if len(set(pairs))!=len(pairs) or set(pairs)!=expected: errs.append('judgment.json.matrix.cells：重复或缺失行列格')
        return errs

    def check(self, stage, delivery=False):
        for n in range(stage+1):
            try: getattr(self,'stage'+str(n))(delivery) if n==10 else getattr(self,'stage'+str(n))()
            except (KeyError,ValueError,TypeError,IndexError,OSError) as exc: self.err('阶段'+str(n),'',str(exc))
        return self.errors

    def stage0(self):
        c=self.need('case.json')
        for key in ('case_id','mode','prepared_on','version','decision_stage','target_year','education','deadlines','data_commit','context','report_meta'):
            if c.get(key) in (None,'',[]): self.err('case.json',key,'缺登记信息')
        code='YJ' if self.kind=='grad' else 'QZ'
        if not re.fullmatch(r'\d{4}-'+code+r'-(?:\d{4}|S\d{2})',c.get('case_id','')): self.err('case.json','case_id','编号格式不符')
        if not c.get('legacy_directory') and self.root.name!=c.get('case_id'): self.err('case.json','case_id','与目录名不一致')
        if c.get('mode') not in ('formal','simulation'): self.err('case.json','mode','非法模式')
        if c.get('mode')=='formal' and '-S' in c.get('case_id',''): self.err('case.json','case_id','正式编号不能用S')
        if day(c['prepared_on'])>day(c['context']['as_of']): self.err('case.json','context.as_of','早于准备日')
        stages={'grad':['还在考虑','备考中','初试已出分','已有录取'],'career':['还没开始','投递中','有 offer 在比较','在职想跳槽']}
        if c.get('decision_stage') not in stages[self.kind]: self.err('case.json','decision_stage','阶段不合法')
        if c['context'].get('offer_basis') not in ('actual','scenario','none'):self.err('case.json','context.offer_basis','须区分实际、条件情景或暂无')
        if self.kind=='career' and c.get('hypothetical_followup',{}).get('offers') and c['context'].get('offer_basis')!='scenario':self.err('case.json','context.offer_basis','已有的条件offer不能冒充实际或改成none跳过收入图')
        for k in ('id','stage','region','date','data_asof','conclusion'):
            if not c.get('report_meta',{}).get(k):self.err('case.json','report_meta.'+k,'缺封面信息')
        for d in c.get('deadlines',[]):
            if d.get('date'):day(d['date'])
            elif not d.get('unknown_reason'):self.err('case.json','deadlines','未知日期须说明')

    def stage1(self):
        header='【读研 · 自我盘点】' if self.kind=='grad' else '【求职 · 自我盘点】'
        raw=active_profile(self.root)
        structured=parse_profile(raw)
        if structured is not None:
            if structured['zhiqu']!=self.kind:self.err('profile.json','','画像类型与登记不一致')
        elif not raw.startswith(header):self.err('profile.txt','','画像开头错误')
        if structured is not None:self.errors.extend(alignment_errors(self.root))
        p=self.need('profile_parse.json');fields={x['field']:x for x in p.get('fields',[])};missing={x['field'] for x in p.get('missing',[])}
        for name in PROFILE_FIELDS[self.kind]:
            f=fields.get(name,{})
            if f.get('status') not in ('given','inferred','unknown'): self.err('profile_parse.json',name,'缺字段状态')
            if f.get('category') not in ('fact','preference','constraint','self_judgment'): self.err('profile_parse.json',name,'缺四类分类')
            if f.get('status')=='unknown' or (f.get('status')=='inferred' and not f.get('confirmed')):
                if name not in missing:self.err('profile_parse.json',name,'须列missing')
            elif f.get('value') is None or not f.get('quote') or not f.get('locator'):self.err('profile_parse.json',name,'缺本人原话或定位')

    def stage2(self):
        d=self.need('directions.json')
        for key in ('questions','directions'):
            if not self.limits[key+'_min']<=len(d.get(key,[]))<=self.limits[key+'_max']:self.err('directions.json',key,'数量不符合合同')
        for x in d.get('directions',[]):
            if not all(x.get(k) for k in ('id','name','support','counter','verify')):self.err('directions.json',x.get('id','?'),'缺支持、反证或验证')

    def stage3(self):
        r=self.need('rules_check.json');now=day(self.case['context']['as_of'])
        if not r.get('items'):self.err('rules_check.json','items','缺用到的规则复核')
        if r.get('as_of')!=now.isoformat():self.err('rules_check.json','as_of','与出稿日不一致')
        for i in r.get('items',[]):
            if i.get('status') not in ('verified','unretrieved'):self.err('rules_check.json',i.get('id','?'),'规则状态错误')
            if not all(e in self.evidence for e in i.get('evidence_refs',[])) or not i.get('evidence_refs'):self.err('rules_check.json',i.get('id','?'),'缺规则来源')
            if i.get('status')=='verified':
                if any(self.evidence[e].get('status')!='verified' or self.evidence[e].get('grade')!='官方' for e in i.get('evidence_refs',[]) if e in self.evidence):self.err('rules_check.json',i['id'],'已核规则必须由已取得的官方原文支持')
                if i.get('volatile') and not 0<=(now-day(i['verified_on'])).days<=self.limits['rule_fresh_days']:self.err('rules_check.json',i['id'],'会变规则未及时复核')
                if day(i['review_due'])<now:self.err('rules_check.json',i['id'],'规则已过期')
            elif not i.get('gap'):self.err('rules_check.json',i.get('id','?'),'未取到须说明影响与下一步')

    def stage4(self):
        c=self.need('candidates.json');pool=c.get('school_programs',[]) if self.kind=='grad' else c.get('job_types',[])
        minimum=self.limits['school_programs_min_if_kaoyan'] if self.kind=='grad' and self.case['context'].get('takes_kaoyan') else self.limits['job_types_min'] if self.kind=='career' else 1
        if len(pool)<minimum:self.err('candidates.json','','候选少于合同要求')
        if self.kind=='grad' and self.case['context'].get('takes_kaoyan'):
            assessment=c.get('personal_difficulty',{});mock=assessment.get('mock_exam')
            if mock and not self.has_complete_mock():self.err('candidates.json','personal_difficulty','模考记录不完整、不同科目或缺有效成绩证据')
            if self.has_complete_mock():
                if {x.get('tier') for x in pool}!={'相对稳妥','够一够','冒险'}:self.err('candidates.json','school_programs','有同科目完整模考证据后须分个人条件档')
            else:
                if any(x.get('tier') for x in pool):self.err('candidates.json','school_programs','无同科目完整模考证据，不得标个人难度档')
                checkpoint=assessment.get('checkpoint',{})
                try:
                    day(self.expand(checkpoint['date']))
                    if not checkpoint.get('action'):raise ValueError('缺取得模考后的定档动作')
                except (KeyError,ValueError,TypeError):self.err('candidates.json','personal_difficulty.checkpoint','无模考时须明确取得同科目完整模考后的定档检查点')
        for candidate in pool+c.get('paths',[])+c.get('jobs',[]):
            if not candidate.get('hard_conditions'):self.err('candidates.json',candidate.get('id','?'),'硬条件为空')
            for hc in candidate.get('hard_conditions',[]):
                if hc.get('status') not in ('met','unknown','failed') or not hc.get('evidence_refs') or any(e not in self.evidence for e in hc.get('evidence_refs',[])):self.err('candidates.json',candidate.get('id','?'),'硬条件状态/证据错误')
                if hc.get('status')=='met':
                    refs=[self.evidence[e] for e in hc.get('evidence_refs',[]) if e in self.evidence]
                    if not any(e.get('grade')=='官方' and e.get('status')=='verified' for e in refs) or any(e.get('status')!='verified' for e in refs):self.err('candidates.json',candidate.get('id','?'),'met缺已核官方适用条件')
            statuses={x.get('status') for x in candidate.get('hard_conditions',[])}
            expected='ineligible' if 'failed' in statuses else 'pending' if 'unknown' in statuses else 'verified'
            if candidate.get('status')!=expected:self.err('candidates.json',candidate.get('id','?'),'不能把未知或不符合当已核实可行')
            if 'failed' in statuses and not candidate.get('excluded_reason'):self.err('candidates.json',candidate.get('id','?'),'剔除缺原因')

    def stage5(self):
        items=self.need('evidence.json').get('items',[])
        self.errors.extend(self.evidence_integrity_errors())
        if len(self.evidence)!=len(items):self.err('evidence.json','items','ID重复')
        now=day(self.case['context']['as_of'])
        required=('id','claim','unit','source','published_on','retrieved_on','retrieval_method','grade','scope','review_due','candidate_ids','status')
        for e in items:
            for k in required:
                if k not in e:self.err('evidence.json',e.get('id','?')+'.'+k,'缺字段')
            if e.get('grade') not in ('官方','多人一致','单人说法','推测'):self.err('evidence.json',e['id'],'等级错误')
            if e.get('retrieval_method') not in ('curl','browser','provided','operator_check'):self.err('evidence.json',e['id'],'取文方式错误')
            if e.get('grade')=='官方' and not re.match(r'https?://',e.get('source',{}).get('url','')):self.err('evidence.json',e['id'],'官方网址为空')
            if day(e['retrieved_on'])>now or day(e['review_due'])<day(e['retrieved_on']):self.err('evidence.json',e['id'],'日期前后错误')
            if e.get('status')=='unretrieved' and not e.get('gap'):self.err('evidence.json',e['id'],'未取到缺原因')
            if e.get('status') not in ('verified','unretrieved'):self.err('evidence.json',e['id'],'证据状态错误')
            if e.get('status')=='verified' and not e.get('excerpt'):self.err('evidence.json',e['id'],'缺原文定位/关键摘录')
            if not e.get('claim') or not e.get('scope') or not e.get('source',{}).get('locator'):self.err('evidence.json',e['id'],'缺说法、范围或原件定位')
            if e.get('published_on'):day(e['published_on'])
            if e.get('verified_on') and day(e['verified_on'])>now:self.err('evidence.json',e['id'],'核实日期晚于出稿日')
            gid=e.get('source_group');groups=self.data['evidence.json'].get('source_groups',[])
            if type(gid) is not int or not 1<=gid<=len(groups):self.err('evidence.json',e['id'],'尾注来源组不存在')
        candidate_ids={x['id'] for k in ('paths','school_programs','job_types','jobs') for x in self.data.get('candidates.json',{}).get(k,[])}
        judgment_ids={x['id'] for x in self.data.get('judgment.json',{}).get('candidates',[])}
        def references(obj,location):
            if isinstance(obj,dict):
                for key,value in obj.items():
                    allowed={'evidence_refs':set(self.evidence),'candidate_refs':candidate_ids,'judgment_refs':judgment_ids}.get(key)
                    if allowed is not None:
                        if not isinstance(value,list) or any(ref not in allowed for ref in value):self.err(location,key,'引用不存在或不是ID数组')
                    if key=='calc_refs':
                        for ref in value:
                            try:pointer(self.data['calculations.json'],ref)
                            except (KeyError,ValueError,IndexError,TypeError):self.err(location,key,'计算引用不存在 '+str(ref))
                    references(value,location+'/'+key)
            elif isinstance(obj,list):
                for i,value in enumerate(obj):references(value,location+'/'+str(i))
        for file,obj in self.data.items():references(obj,file)

    def stage6(self):
        saved=self.need('calculations.json');plan=self.case.get('calculation_plan',{})
        if plan.get('engine')=='legacy_demo':
            from check_demos import calculate
            if calculate(self.case)!=saved:self.err('calculations.json','','既有计算不能复算')
            for key,spec in plan.get('display_inputs',{}).items():
                role=spec.get('role');where='calculation_plan.display_inputs.'+key
                if role not in ('declared_scenario','anonymous_aggregate','derived_rule_parameter'):
                    self.err('case.json',where,'必须区分情景、匿名加工和官方规则换算')
                if role=='declared_scenario' and spec.get('source_group')!=1:
                    self.err('case.json',where,'情景不能冒充官方输入')
                if role=='derived_rule_parameter':
                    refs=spec.get('evidence_refs',[]);values=spec.get('source_values',[])
                    def raw_number(eid):
                        e=self.evidence[eid]
                        if e.get('grade')!='官方' or e.get('status')!='verified' or not excerpt_contains(e.get('value'),e.get('excerpt','')):raise ValueError('不是已核官方数值')
                        return float(str(e['value']).rstrip('%'))
                    try:
                        if len(refs)!=len(values) or [raw_number(eid) for eid in refs]!=values:raise ValueError('原值不符')
                        if spec.get('algorithm') not in ('sum','percent_to_ratio'):raise ValueError('换算算法未登记')
                        if pointer(saved,'/report_parameters/'+key)!=pointer(self.case,spec['case_pointer']):raise ValueError('结果与输入不符')
                    except (ValueError,KeyError,TypeError):self.err('case.json',where,'官方参数换算缺正确原文/输入/算法')
            expected={path for section in ('budget','additional_scenarios','hypothetical_followup')
                      for path,v in walk(self.case.get(section,{}),'/'+section)
                      if isinstance(v,(int,float)) and not isinstance(v,bool)}
            bindings=plan.get('inputs',{})
            if set(bindings)!=expected:self.err('case.json','calculation_plan.inputs','计算输入来源未全部登记')
            for path,ref in bindings.items():
                try:
                    match=REF.fullmatch(ref)
                    if not match or self.resolve(match[1],match[2])!=pointer(self.case,path):raise ValueError('输入与来源值不一致')
                except (KeyError,ValueError,TypeError):self.err('case.json','calculation_plan.inputs'+path,'输入与来源值不一致')
        else:
            # 与核对工具同一份实现（verification_calculations），算法清单只维护一处。
            from verification_calculations import _registered
            computed,_=_registered(self.case,self.data['profile_parse.json'],self.data['evidence.json'])
            if computed!=saved:self.err('calculations.json','','计算结果与已登记算法不一致')
        scenarios=plan.get('scenarios',[])
        if len(scenarios)<self.limits['scenarios_min']:self.err('case.json','calculation_plan.scenarios','情景不足')
        signatures=[]
        for x in scenarios:
            if not x.get('changed_inputs') or not x.get('why') or not x.get('output_ref'):self.err('case.json','calculation_plan.scenarios','情景无关键变化/原因/输出')
            else:
                self.expand(x['output_ref']);signatures.append(json.dumps(x['changed_inputs'],sort_keys=True))
                if plan.get('engine')=='legacy_demo':
                    # These are named, reproduced branches in check_demos.calculate, not free-form claims.
                    registered={'grad':{'living':'/annual_cost_if_living_plus_200','other_fee':'/gdut_fee_reference/annual_cost'},
                                'career':{'housing':'/monthly_remaining_if_housing_plus_600','contract_city':'/hypothetical_offers/1/monthly_remaining_cash'}}
                    match=REF.fullmatch(x['output_ref'])
                    if x.get('id') not in registered[self.kind] or not match or match[1]!='c' or match[2]!=registered[self.kind][x['id']]:self.err('case.json','calculation_plan.scenarios','情景与已注册计算分支不符')
                    actual_changes={'grad':{'living':{'monthly_living_assumption':self.case['budget'].get('monthly_living_assumption',0)+200},'other_fee':{'tuition_reference':'广工旧年收费'}},
                                    'career':{'housing':{'monthly_housing_assumption':self.case['budget'].get('monthly_housing_assumption',0)+600},'contract_city':{'offer':'B','contract':'派遣','housing':self.case.get('hypothetical_followup',{}).get('offers',[{},{}])[1].get('monthly_rent')}}}
                    if x.get('id') in actual_changes[self.kind] and x['changed_inputs']!=actual_changes[self.kind][x['id']]:self.err('case.json','calculation_plan.scenarios','描述的变化与实际计算分支不一致')
        if len(signatures)!=len(set(signatures)):self.err('case.json','calculation_plan.scenarios','情景重复')

    def stage7(self):
        j=self.need('judgment.json');p=j.get('preferences',{})
        if not p.get('quote') or not p.get('profile_refs'):self.err('judgment.json','preferences','缺问卷优先级依据')
        if p.get('method')=='numeric':
            if not p.get('confirmed') or not p.get('weights') or abs(sum(p['weights'].values())-1)>1e-8:self.err('judgment.json','preferences','权重未经确认/合计不是1')
        elif p.get('weights') is not None:self.err('judgment.json','preferences','没有数值权重依据不得编权重')
        for c in j.get('candidates',[]):
            for key in ('supports','counters','costs','fallback','switch_conditions','checkpoint'):
                if not c.get(key):self.err('judgment.json',c.get('candidate_id','?')+'.'+key,'缺判断依据')
        if not all(j.get('recommendation',{}).get(k) for k in ('primary','backup','conditions')):self.err('judgment.json','recommendation','缺主路径/保险路径/条件')
        known={c['id'] for key in ('school_programs','paths','job_types','jobs') for c in self.data.get('candidates.json',{}).get(key,[])}
        if any(cid not in known for key in ('primary','backup') for cid in j.get('recommendation',{}).get(key,[])):self.err('judgment.json','recommendation','推荐了未登记候选')
        if not j.get('candidates') or not j.get('checkpoint'):self.err('judgment.json','','缺候选判断或检查点')
        for _,v in walk(j):
            if isinstance(v,str) and re.search(r'个人.{0,4}(?:上岸|录用|录取).{0,4}\d+%',self.expand(v)):self.err('judgment.json','','禁止个人概率')

    def stage8(self):
        self.need('narrative.json');self.errors.extend(self.contract_errors())

    def stage9(self):
        from operator_check import validate_operator
        self.errors.extend(validate_operator(self.root, require_completed=False))
        self.errors.extend(self.trace_errors())

    def trace_errors(self):
        path=self.root/'report_trace.json'
        if not path.exists():return ['report_trace.json：缺生成快照']
        trace=read(path);errors=[]
        expected=set((*FILES,*source_files(self.root)))
        if set(trace.get('source_sha256',{}))!=expected:errors.append('report_trace.json：输入快照不全')
        if trace.get('contract_sha256')!=sha(self.contract_path()):errors.append('report_trace.json：内容合同已变更，须重生成')
        tools=('planning_report.py','planning_workflow.py','operator_check.py','check_demos.py','report.py','render_report.py','profile_store.py')
        if set(trace.get('tool_sha256',{}))!=set(tools):errors.append('report_trace.json：缺算法/渲染器快照')
        elif any(sha(Path(__file__).with_name(f))!=h for f,h in trace['tool_sha256'].items()):errors.append('report_trace.json：算法或渲染器已变更，须重生成')
        for f,h in trace.get('verification_tools_sha256',{}).items():
            if f not in ('verify_report.py','verification_calculations.py') or sha(Path(__file__).with_name(f))!=h:errors.append('report_trace.json：核对材料工具已变更，须重生成')
        for f,h in {**trace.get('source_sha256',{}),**trace.get('artifacts',{})}.items():
            if Path(f).name!=f or not (self.root/f).is_file() or sha(self.root/f)!=h:errors.append('report_trace.json：已过期 '+f)
        return errors

    def stage10(self, delivery=False):
        if delivery and self.case.get('mode')=='formal' and self.case['context']['as_of']!=date.today().isoformat():self.err('case.json','context.as_of','正式交付须按当天核有效期并重生成')
        self.errors.extend(review_errors(self.root,delivery,self.limits))


def review_errors(root, delivery=False, limits=None):
    root=Path(root);errors=[];p=root/'review.json'
    if not p.exists():return ['review.json：缺复核记录']
    rev=read(p);lim=limits or read(SKILLS/'zhiqu/references/report-contract.json')['workflow_limits']
    score=rev.get('rubric',{}) if delivery else rev.get('self_assessment',{}).get('rubric',rev.get('rubric',{}));items=score.get('items',[])
    if {x.get('id') for x in items}!=set(RUBRIC) or len(items)!=len(RUBRIC):errors.append('review.json.rubric：评分项不齐/重复')
    if any(type(x.get('score')) is not int or x['score'] not in (0,1,2) or not x.get('reason') for x in items):errors.append('review.json.rubric：须有分值与扣分理由')
    elif any(x['score']==0 for x in items) or sum(x['score'] for x in items)<lim['review_score_min']:errors.append('review.json.rubric：评分未达标')
    if delivery:
        if rev.get('independent') is not True or rev.get('status')!='approved':errors.append('review.json：尚未独立批准交付')
        if not rev.get('reviewer') or not rev.get('date'):errors.append('review.json：缺独立复核者/日期')
        if rev.get('date'):
            try:day(rev['date'])
            except ValueError:errors.append('review.json：复核日期不合法')
        checks={x['item']:x for x in rev.get('pitfalls',[])}
        if any(checks.get(k,{}).get('result')!='pass' for k in PITFALLS):errors.append('review.json.pitfalls：未全部通过')
        if len(rev.get('sampled_sources',[]))<lim['review_samples_min'] or any(x.get('matches') is not True for x in rev.get('sampled_sources',[])):errors.append('review.json.sampled_sources：抽查未通过')
        from operator_check import validate_operator
        errors.extend(validate_operator(root,True))
    required=({'report.json','report.pdf'} | {str(p.relative_to(root)) for p in root.rglob('result*.json')}) if (root/'report.json').exists() else set((*FILES,*source_files(root),'report.md','report.html','report.pdf','report_trace.json'))
    required.add('operator_check.md')
    snapshot=rev.get('snapshot',{})
    if not required<=set(snapshot):errors.append('review.json.snapshot：缺完整输入/报告快照')
    if any(Path(f).is_absolute() or '..' in Path(f).parts or not (root/f).is_file() or sha(root/f)!=h for f,h in snapshot.items()):errors.append('review.json.snapshot：报告/输入变更，复核已失效')
    return errors
