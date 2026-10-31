#!/usr/bin/env python3
"""有界的读者用语检查；术语候选有限，不声称识别任意中文专业术语。

只检查可见正文 01—11；第12节核对材料不进入检查。语境待判也返回，
由审阅人决定是否属于真实职业描述，不能靠包含一个职业词全局放行。
"""
import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT/'skills/zhiqu/references/report-guide.md'
CANDIDATES = ROOT/'skills/zhiqu-shared/references/reader-language.json'
DEV = re.compile(r'返工|复现|演示|脚本|快照|\.json(?![A-Za-z0-9_])|\.py(?![A-Za-z0-9_])|字段路径|/[a-z_]+(?:/[a-z_]+)+', re.I)
INTERNAL = re.compile(r'(?<![A-Za-z0-9])(?:见\s*|证据\s*)?E\d{3,}(?![A-Za-z0-9])')
REF = re.compile(r'\{\{[pkce]:.*?\}\}')

@dataclass
class Fragment:
    text: str
    section: str = ''
    location: str = ''
    page: int | None = None
    role: str = 'text'
    admission_codes: tuple = ()

def terminology(guide=GUIDE):
    """统一叫法唯一来源是 report-guide 的三列表，不复制到配置。"""
    rows=[];active=False
    for line in Path(guide).read_text().splitlines():
        if line.startswith('| 统一叫法 |'):active=True;continue
        if active and not line.startswith('|'):break
        if not active or re.match(r'^\|[-| ]+\|$',line):continue
        cells=[x.strip() for x in line.strip('|').split('|')]
        if len(cells)==3:rows.append((cells[0],cells[1],[x.strip() for x in re.split('[、，]',cells[2]) if x.strip()]))
    return rows

class BodyParser(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.fragments=[];self.section='';self.parts=[];self.role='text';self.suppressed=0;self.headers=[];self.cells=[];self.cell_parts=None;self.row_header=False
    def flush(self):
        text=''.join(self.parts).strip();self.parts=[]
        if text and self.section and 1<=int(self.section)<=11:
            codes=[]
            for index,cell in enumerate(self.cells):
                if index<len(self.headers) and re.search(r'(?:院校|学校|招生|专业|专业组).*代码',self.headers[index]) and re.fullmatch(r'E\d{3,}',cell.strip()):codes.append(cell.strip())
            self.fragments.append(Fragment(text,self.section,'HTML 第'+self.section+'节',role=self.role,admission_codes=tuple(codes)))
    def handle_starttag(self,tag,attrs):
        if tag=='table':self.headers=[]
        if tag=='tr':self.flush();self.cells=[];self.row_header=False
        if tag in ('td','th'):
            self.cell_parts=[]
            if tag=='th':self.row_header=True
        attrs=dict(attrs);previous=(self.section,self.role,self.suppressed)
        if tag=='section':self.flush();self.section=attrs.get('data-section',self.section)
        if tag in ('script','style'):self.suppressed+=1
        if tag in ('p','h2','h3','h4','li','tr','dt','dd','text'):
            self.flush();self.role='label' if tag in ('th','dt') else 'text'
        if tag=='th':self.role='label'
        if tag in ('td','th'):self.parts.append(' | ')
        if tag not in ('meta','link','br','img','input','hr','source'):self.stack.append((tag,previous))
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell_parts is not None:
            self.cells.append(''.join(self.cell_parts).strip());self.cell_parts=None
        if tag=='tr' and self.row_header:self.headers=list(self.cells)
        if tag in ('section','p','h2','h3','h4','li','tr','dt','dd','text'):self.flush()
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                self.section,self.role,self.suppressed=self.stack[index][1];del self.stack[index:];break
    def handle_data(self,data):
        if not self.suppressed:
            self.parts.append(data)
            if self.cell_parts is not None:self.cell_parts.append(data)

def html_fragments(raw):
    parser=BodyParser();parser.feed(raw);parser.flush();return parser.fragments

def json_fragments(data):
    """叙述组件只取 content 的可见文字；不把 evidence_refs 等元数据当正文。"""
    out=[]
    def walk(value,path,sid):
        if isinstance(value,str):
            out.append(Fragment(REF.sub('',value),sid,path,role='label' if path.endswith(('.title','.heading','.label')) else 'text'))
        elif isinstance(value,list):
            for i,item in enumerate(value):walk(item,f'{path}[{i}]',sid)
        elif isinstance(value,dict):
            if 'type' in value and 'content' in value:walk(value['content'],path+'.content',sid);return
            for key,item in value.items():
                if key not in ('evidence_refs','source','source_refs','id','ref','type'):walk(item,path+'.'+key,sid)
    for sid,section in data.get('sections',{}).items():
        if str(sid).isdigit() and 1<=int(sid)<=11:walk(section,'sections.'+sid,str(sid).zfill(2))
    return out

def pdf_fragments(path):
    try:import pymupdf
    except ImportError:import fitz as pymupdf
    out=[];section=''
    with pymupdf.open(path) as document:
        for page_num,page in enumerate(document,1):
            for block in page.get_text('blocks'):
                text=block[4].strip()
                # 只认标题行；避免把正文中的“12 个”误当核对节。
                heading=re.match(r'^(0[1-9]|1[0-2])\s+([^\n\d]{2,35})(?:\n|$)',text)
                if heading:section=heading[1]
                if section and 1<=int(section)<=11:out.append(Fragment(text,section,'PDF',page_num))
    return out

def _explained(term,text):
    escaped=re.escape(term)
    return bool(re.search(escaped+r'\s*(?:[（(][^）)]*[\u3400-\u9fff][^）)]*[）)]|[，,:： ]*(?:即|也就是|是指|指的是|意思是|指)[：: ]*[^。；]{2,})',text))

def check_fragments(fragments, *, glossary=None, guide=GUIDE, candidates=None):
    fragments=[f for f in fragments if f.section.isdigit() and 1<=int(f.section)<=11]
    glossary=glossary or {};rules=terminology(guide)
    if candidates is None:candidates=json.loads(CANDIDATES.read_text())['candidates']
    issues=[];seen=set()
    def issue(f,code,term,message,severity='error'):
        issues.append({'code':code,'severity':severity,'section':f.section,'location':f.location,'page':f.page,'term':term,'text':f.text,'message':message})
    for f in fragments:
        text=REF.sub('',f.text)
        for match in DEV.finditer(text):
            term=match.group();career_context=(term in ('脚本','复现','演示') and bool(re.search(r'你|本人|岗位|工作|项目|招聘|面试|能力|软件开发',text)) and bool(re.search(r'开发|编程|数据处理|实验|项目|招聘|岗位|面试',text)))
            issue(f,'development_language',term,'正文出现开发用语；真实职业任务描述须逐项人工确认' if career_context else '正文出现开发用语', 'needs_review' if career_context else 'error')
        for match in INTERNAL.finditer(text):
            # 仅表头明确的招生/院校代码单元格放行，不作 E100 全局白名单。
            if match.group() in f.admission_codes:continue
            issue(f,'internal_evidence_id',match.group(),'正文应使用读者可见出处，不显示内部证据编号')
        for canonical,meaning,alternatives in rules:
            for alternative in alternatives:
                if alternative not in text:continue
                # 表中相邻的真实概念不是同义词，只有明确用作同一统计字段标签才检查。
                if re.search(r'群体统计|官方原文|学校公布|全体|税前|扣税前|不是|不代表|并非|不等于',text):continue
                same_field=(f.role=='label' or ' | ' in text) and bool(re.search(r'预测|模型|志愿|计算|扣除.*(?:税|公积金)|扣.*住房',text))
                if alternative in ('过线概率','预测过线','落点概率','预测线'):
                    same_field=bool(re.search(r'志愿|模型|预测|表|图',text))
                if same_field:issue(f,'inconsistent_term',alternative,'同一计算字段按指南称为“'+canonical+'”；请核对口径后修改')
        for term in candidates:
            pattern=r'(?<![A-Za-z0-9])'+re.escape(term)+r'(?![A-Za-z0-9])' if term.isascii() else re.escape(term)
            if term in seen or not re.search(pattern,text,re.I):continue
            seen.add(term)
            if any(key.startswith(term) and definition for key,definition in glossary.items()) or _explained(term,text):continue
            issue(f,'unexplained_term',term,'有限术语候选首次出现未解释，且未在术语表登记解释')
    return issues

def glossary_from_html(raw):
    # 明确的术语表定义对，不以“全文某处出现中文”替代解释。
    definitions={}
    for term,definition in re.findall(r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>',raw,re.S):
        clean=lambda value:re.sub('<[^>]+>','',value).strip()
        if clean(definition):definitions[clean(term)]=clean(definition)
    return definitions

def check_html(raw):return check_fragments(html_fragments(raw),glossary=glossary_from_html(raw))

def check_planning_source(case):
    """Check active authored components before presentation word substitutions.

    public_text can replace developer terms with reader-facing wording; that must
    not silently turn an invalid authored paragraph into a successful publication.
    """
    fragments=[];glossary={};boundary_issues=[]
    def expand_source(value,path,sid):
        from planning_workflow import REF as SOURCE_REF
        for match in SOURCE_REF.finditer(value):
            suffix=re.match(r'[ \t]*([。，；])',value[match.end():])
            if not suffix:continue
            try:display=case.format(case.resolve(match[1],match[2]),match[3])
            except (KeyError,ValueError,IndexError,TypeError):continue
            if not display.rstrip(' \t').endswith(('。','！','？')):continue
            boundary_issues.append({'code':'reference_punctuation','severity':'error',
                'section':sid,'location':path,'page':None,'term':display.rstrip()[-1]+suffix[1],
                'text':value,'message':'引用末尾已有句末标点，模板紧接另一标点；保留原答，删除模板重复分隔或用引号明确边界'})
        try:return case.expand(value)
        except (KeyError,ValueError,IndexError,TypeError):return REF.sub('',value)
    def walk(value,path,sid):
        if isinstance(value,str):
            text=expand_source(value,path,sid)
            fragments.append(Fragment(text,sid,path,role='label' if path.endswith(('/title','/heading','/label')) or '/columns/' in path else 'text'))
        elif isinstance(value,list):
            for i,item in enumerate(value):walk(item,path+'/'+str(i),sid)
        elif isinstance(value,dict):
            for key,item in value.items():
                if key!='kind':walk(item,path+'/'+key,sid)
    for sid,entries in case.nodes().items():
        if not sid.isdigit() or not 1<=int(sid)<=11:continue
        section=next(s for s in case.contract['sections'] if s['id']==sid)
        for entry in entries:
            slot=next(s for s in section['slots'] if s['key']==entry['slot'])
            if not case.active(slot):continue
            node=case.get_node(entry['ref']);content=node.get('content',{})
            if node.get('type') in ('source_endnotes','evidence_legend') or node.get('type')=='analysis' and content.get('kind')=='comment':continue
            if node.get('type')=='term_table':
                for row in content.get('rows',[]):
                    if len(row)>=2:
                        for term in re.split('[、，/]',str(row[0])):glossary[term.strip()]=str(row[1])
            walk(content,entry['ref']+'/content',sid)
    issues=check_fragments(fragments,glossary=glossary)
    # 逐句回查看的是这里的源文字；印出来的文字必须与它一致，发布层不能再改字。
    from report import public_words
    cover=[]
    # 封面只有一句话结论经过发布层换词（对象名另由 simulated_name 处理）。
    for key,value in case.case.get('report_meta',{}).items():
        if key not in ('conclusion','note') or not isinstance(value,str):continue
        text=expand_source(value,'case.json#/report_meta/'+key,'01')
        cover.append(Fragment(text,'01','case.json#/report_meta/'+key))
    for f in [*fragments,*cover]:
        if not f.section.isdigit() or not 1<=int(f.section)<=11:continue
        printed=public_words(f.text)
        if printed!=f.text:
            changed=next((a for a,b in zip(f.text,printed) if a!=b),'')
            issues.append({'code':'rewritten_on_print','severity':'error','section':f.section,'location':f.location,'page':None,'term':printed[:40],'text':f.text,
                           'message':'这句会在印刷时被换词（逐句回查看到的与印出来的不一致）；请在源文件直接写读者用语，或把本人原话放进引号'})
    return issues+boundary_issues


def check_case(root):
    root=Path(root);issues=[]
    html=root/'report.html'
    if html.exists():
        issues=check_html(html.read_text())
        for issue in issues:issue['file']=str(html)
    elif (root/'narrative.json').exists():
        issues=check_fragments(json_fragments(json.loads((root/'narrative.json').read_text())))
        for issue in issues:issue['file']=str(root/'narrative.json')
    return issues

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('paths',nargs='*',type=Path);parser.add_argument('--all-examples',action='store_true');parser.add_argument('--output',type=Path)
    args=parser.parse_args();paths=args.paths
    if args.all_examples:paths=sorted((ROOT/'skills').glob('zhiqu*/examples/*/report.html'))
    results=[]
    for path in paths:
        if path.is_dir():issues=check_case(path)
        elif path.suffix=='.html':issues=check_html(path.read_text())
        elif path.suffix=='.pdf':issues=check_fragments(pdf_fragments(path))
        else:issues=check_fragments(json_fragments(json.loads(path.read_text())))
        results.extend(dict(issue,file=str(path)) for issue in issues)
    payload={'coverage':'固定开发词、指南明确同概念字段及有限术语候选；不作任意中文术语自动识别','issues':results,'errors':sum(x['severity']=='error' for x in results),'needs_review':sum(x['severity']=='needs_review' for x in results)}
    raw=json.dumps(payload,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(raw)
    else:print(raw,end='')
    return int(bool(payload['errors']))

if __name__=='__main__':raise SystemExit(main())
