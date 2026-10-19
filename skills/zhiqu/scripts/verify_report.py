#!/usr/bin/env python3
"""Inspect a delivered PDF offline; never execute embedded code or fetch URLs.

python3 verify_report.py report.pdf [--extract DIRECTORY] [--json]
The checks establish internal consistency, not the truth of an official source.
"""
import argparse
from collections import Counter
import csv
import hashlib
from html.parser import HTMLParser
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[3]
NUMBER = re.compile(r'(?<![A-Za-z])\d[\d,]*(?:\.\d+)?(?:%|％)?')
MAX_ATTACHMENT = 16 * 1024 * 1024


def digest(data):return hashlib.sha256(data).hexdigest()
def json_bytes(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
def read(path):return json.loads(Path(path).read_text())
def visible(value):
    if value is None:return '未记录'
    if isinstance(value,float):return format(value,'.10g')
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return str(value)
def norm(text):return re.sub(r'\s+','',text).replace('\u00ad','')
def ptr(value,path):
    for key in path.lstrip('/').split('/') if path else []:
        key=key.replace('~1','/').replace('~0','~');value=value[int(key)] if isinstance(value,list) else value[key]
    return value

def leaves(value,path=''):
    if isinstance(value,dict):
        for k,v in value.items():yield from leaves(v,path+'/'+str(k).replace('~','~0').replace('/','~1'))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from leaves(v,path+'/'+str(i))
    else:yield path,value


class SectionText(HTMLParser):
    def __init__(self):super().__init__();self.section=None;self.text={};self.ignore=0;self.reference_depth=0
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=='sup' and 'source-ref' in d.get('class','').split():self.ignore+=1;self.reference_depth+=1
        if tag in ('style','script','title'):self.ignore+=1
        if tag=='section':self.section=d.get('data-section')
        if tag in ('p','li','tr','td','th','text','h2','h3','h4','div','br') and self.section:self.text.setdefault(self.section,[]).append('\n')
    def handle_endtag(self,tag):
        if tag=='sup' and self.reference_depth:self.ignore-=1;self.reference_depth-=1
        if tag in ('style','script','title'):self.ignore-=1
        if tag=='section':self.section=None
    def handle_data(self,data):
        if self.section and not self.ignore:self.text.setdefault(self.section,[]).append(data)
    def sections(self):return {k:''.join(v) for k,v in self.text.items()}


def select_profile(root,version):
    """Explicit selection; legacy text is wrapped without inventing a fill date."""
    root=Path(root).resolve();path=Path(version)
    if not path.is_absolute():path=root/path
    path=path.resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('所用画像版本必须是案例目录内的现有文件')
    if path.suffix=='.json':
        data=read(path)
        if data.get('format')!='legacy-text':
            from profile_store import validate
            validate(data)
    else:
        raw=path.read_text();snapshot=root/'profile_snapshot.json'
        data={'format':'legacy-text','source_file':str(path.relative_to(root)),'source_sha256':digest(path.read_bytes()),'filled_at':None,'form':None,'text':raw,'note':'旧画像未记录填写时间和题目指纹；原文封装，不补造。'}
        if snapshot.exists() and read(snapshot)!=data:raise ValueError('旧画像封装已存在且内容不同，请另存新版本')
        if not snapshot.exists():snapshot.write_bytes(json_bytes(data))
        path=snapshot
    selected={'file':str(path.relative_to(root)),'sha256':digest(path.read_bytes()),'filled_at':data.get('filled_at'),'form':data.get('form')}
    warning=None
    profiles=[]
    known=list((root/'profiles').glob('*.json'))
    if (root/'profile.json').exists():known.append(root/'profile.json')
    for q in known:
        try:
            x=read(q)
            if x.get('filled_at'):profiles.append(x['filled_at'])
        except (OSError,ValueError):continue
    from profile_store import timestamp
    if profiles and (not selected['filled_at'] or max(map(timestamp,profiles))>timestamp(selected['filled_at'])):warning='报告基于旧画像'
    return selected,data,warning


def bind_profile(root,version,require_analysis=False):
    root=Path(root);binding,data,warning=select_profile(root,version);case=read(root/'case.json')
    if require_analysis:require_analysis_profile(root,binding,data)
    case['report_profile']=binding
    if not case.get('data_commit'):
        try:case['data_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
        except (OSError,subprocess.CalledProcessError):case['data_commit']='未记录构建快照（当前安装目录不是Git仓库）'
    (root/'case.json').write_bytes(json_bytes(case))
    return binding,data,warning


def require_analysis_profile(root,binding,profile):
    """A chosen archive cannot merely relabel an analysis made from another one."""
    root=Path(root);parsed=read(root/'profile_parse.json') if (root/'profile_parse.json').exists() else {}
    expected=parsed.get('source',{}).get('raw_sha256')
    if profile.get('format')=='legacy-text':
        if (root/'profile.txt').exists():
            if profile.get('text')!=(root/'profile.txt').read_text():raise ValueError('所选画像与分析所用旧画像不一致')
        elif (root/'report.json').exists():
            if profile.get('text')!=json.dumps(read(root/'report.json').get('profile',{}),ensure_ascii=False,indent=2):raise ValueError('所选画像与旧报告登记输入不一致')
        else:raise ValueError('无法确认所选旧画像与本次分析的绑定')
        if expected and profile.get('source_sha256')!=expected:raise ValueError('所选画像与画像解析来源指纹不一致')
    elif expected!=binding['sha256']:
        raise ValueError('所选画像与画像解析来源指纹不一致；先按该版本重新解析和分析')


def case_info(case,binding,warning=None):
    generated=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    return [('案例号',case['case_id']),('报告版本',case.get('report_version','1')),('生成时间',generated),
            ('所用画像时间',binding.get('filled_at') or '旧画像未记录填写时间'),('画像SHA256（前12位）',binding['sha256'][:12]),
            ('数据快照（data_commit）',case.get('data_commit','未记录')),('画像版本提示',warning or '生成时未发现更新版本')]


def planning_materials(case,trace,binding,warning=None):
    """Only explicit references determine provenance; never match by equal values."""
    from planning_workflow import REF
    from verification_calculations import calculation_rows
    evidence=case.evidence;sections={};registrations={};used={}
    # Include textual personal inputs and contrary evidence, not just digit refs.
    for sid,entries in case.nodes().items():
        for entry in entries:
            node=case.get_node(entry['ref'])
            for path,v in leaves(node):
                if isinstance(v,str):
                    for match in REF.finditer(v):
                        kind,reference,_=match.groups()
                        if kind in ('p','k'):registrations.setdefault((kind,reference),set()).add(sid)
                        if kind=='e':used.setdefault(reference.split('#')[0],set()).add(sid)
            for eid in node.get('evidence_refs',[]):used.setdefault(eid,set()).add(sid)
    groups={}
    for item in trace:
        groups.setdefault((item['ref'],str(item['display'])),[]).append(item['location'])
    numbers=[]
    for (reference,shown),locations in groups.items():
        if not NUMBER.search(shown):continue
        match=REF.fullmatch(reference)
        if not match:continue
        kind,path,_=match.groups();sids=sorted(set(x.split('.')[0] for x in locations));row={'label':reference,'value':shown,'sections':'、'.join(sids),'reference':reference}
        if kind=='e':
            e=evidence[path.split('#')[0]];source=e['source'];row.update(label=e['claim'],institution=source['organization'],url=source.get('url',''),excerpt=e.get('excerpt',''),evidence_id=e['id'],raw_value=e.get('value'),scope=e.get('scope',''))
        elif kind in ('p','k'):
            if kind=='k' and path.startswith('/context/personal_dates/'):
                role='本报告设置的个人检查点（安排，不是官方日期）'
            elif kind=='k' and 'assumption' in path:
                role='报告登记的费用或收入情景（不是已核实支或雇主报价）'
            else:role='本人画像或案例登记；未作官方认证'
            row.update(label=role+'：'+path,institution=role,excerpt='登记值：'+visible(case.resolve(kind,path)),raw_value=case.resolve(kind,path))
        else:row.update(label='计算或参数登记项：'+path,institution='本报告计算/参数登记；核对方式见下列公式',calculation_path=path)
        numbers.append(row)
    personal=[]
    if not case.case.get('report_input_usage'):raise ValueError('缺报告实际依赖的本人输入登记 report_input_usage')
    for use in case.case['report_input_usage']:
        field=ptr(case.data['profile_parse.json'],'/'+'/'.join(use['pointer'].lstrip('/').split('/')[:2]))
        if field.get('status')!='given':raise ValueError('未确认输入不能登记为报告已知条件')
        personal.append({'label':field['field'],'value':ptr(case.data['profile_parse.json'],use['pointer']),'sections':'、'.join(use['sections'])})
    for (kind,path),sids in registrations.items():
        if kind=='k' and (path.startswith('/context/') or 'assumption' in path):continue
        label=path
        if kind=='p':label=ptr(case.data['profile_parse.json'],'/'+ '/'.join(path.lstrip('/').split('/')[:2])).get('field',path)
        personal.append({'label':label,'value':case.resolve(kind,path),'sections':'、'.join(sorted(sids))})
    for eid,sids in used.items():
        e=evidence[eid]
        if e.get('publication_status')=='personal_input':personal.append({'label':e['claim'],'value':e['value'],'sections':'、'.join(sorted(sids))})
    dedup={}
    for row in personal:
        key=json.dumps(row['value'],ensure_ascii=False,sort_keys=True)
        if key in dedup:
            old=dedup[key];old['label']+=' / '+row['label'];old['sections']='、'.join(sorted(set(old['sections'].split('、')+row['sections'].split('、'))))
        else:dedup[key]=dict(row)
    personal=list(dedup.values())
    limitations=[]
    for candidate in case.data['judgment.json'].get('candidates',[]):
        src=[evidence[e]['source'] for e in candidate.get('evidence_refs',[]) if e in evidence]
        limitations.append({'claim':'；'.join(candidate.get('counters',[])),'reason':'支持条件：'+'；'.join(candidate.get('supports',[]))+'；仍须满足：'+'；'.join(case.data['judgment.json'].get('recommendation',{}).get('conditions',[])),'change_if':visible(candidate.get('switch_conditions','条件改变则重评')),'url':'；'.join(dict.fromkeys(s.get('url','') for s in src if s.get('url')))})
    for sid in ('04','09','10'):
        for entry in case.nodes()[sid]:
            node=case.get_node(entry['ref'])
            if node['type'] not in ('scenario_table','unknown_explanation','analysis','assumption_table'):continue
            content=node.get('content',{})
            if node['type']=='analysis' and content.get('kind')=='heading':continue
            source=[evidence[e]['source'] for e in node.get('evidence_refs',[]) if e in evidence]
            text='；'.join(case.expand(v,'appendix') for _,v in leaves(content) if isinstance(v,str))
            if not text:continue
            limitations.append({'claim':text,'reason':'结论仅在正文列明的资格、预算和本人接受条件内适用；第 '+sid+' 节原条件见本条。','change_if':'出现本条触发条件或补充信息与当前依据不符时，按第 09 节备选重新判断。','url':'；'.join(dict.fromkeys(s.get('url','') for s in source if s.get('url')))})
    gaps=[{'label':e['claim'],'reason':e.get('excerpt') or e.get('source',{}).get('locator','未取到原文'),'url':e.get('source',{}).get('url','')} for e in evidence.values() if e.get('status') in ('unretrieved','not_found') or e.get('publication_status')=='unpublished']
    formulas=calculation_rows(case.case,case.data['profile_parse.json'],case.data['evidence.json'],case.data['calculations.json'])
    calc_locations={}
    for item in trace:
        m=REF.fullmatch(item['ref'])
        if m and m[1]=='c':calc_locations.setdefault(m[2],set()).add(item['location'].split('.')[0])
    formulas=[dict(row,sections='、'.join(sorted(calc_locations.get(row.get('path',''),{'计算依赖；附录'})))) for row in formulas if row.get('path') in calc_locations]
    return {'case_info':case_info(case.case,binding,warning),'personal_inputs':personal,'numbers':numbers+formulas,'limitations':limitations,'gaps':gaps}


def candidate_file(root,result):
    root=Path(root).resolve();csvpath=Path(result.get('params',{}).get('csv',''))
    options=[csvpath.resolve(),(root/csvpath).resolve(),(ROOT/'skills/zhiqu'/csvpath).resolve()]
    chosen=next((p for p in options if p.is_file() and (p.is_relative_to(root) or p.is_relative_to(ROOT/'skills/zhiqu'))),None)
    if chosen is None:raise ValueError('缺生成结果所用的原序候选表；应放在案例目录：'+str(csvpath))
    return chosen


def gaokao_materials(root,rep,result,binding,warning=None):
    root=Path(root);case=read(root/'case.json');sources=rep.get('sources',[])
    personal=[{'label':label,'value':value,'sections':'02；03—09（方向与选择约束）'} for label,value in rep.get('profile',{}).get('facts',[])]
    personal += [{'label':'优先级：'+label,'value':value,'sections':'02、03、05、10'} for label,value in rep.get('profile',{}).get('priorities',[])]
    personal += [{'label':'本人约束','value':v,'sections':'02、04—09'} for v in rep.get('profile',{}).get('constraints',[])]
    numbers=[];gaps=[];seen_facts={}
    # Legacy report authored claims did not carry field-level source references.
    # Keep that limitation explicit instead of assigning a URL by numerical coincidence.
    mapping={'summary':'01','profile':'02','directions':'03','roadmap':'04','news':'04','why':'05','list_notes':'05','research':'06','questions':'07','todo':'08','ask_me':'09','assumptions':'10','backtest':'10','methods':'10','hindsight':'11'}
    for key,sid in mapping.items():
        for path,value in leaves(rep.get(key,{})):
            if isinstance(value,bool) or value is None:continue
            tokens=NUMBER.findall(str(value))
            if not tokens:continue
            matches=list(NUMBER.finditer(str(value)))
            for index,token in enumerate(tokens):
                match=matches[index]
                # Digits inside addresses are identifiers, not factual quantities.
                if any(a.start()<=match.start()<a.end() for a in re.finditer(r'https?://[^\s；，。]+',str(value))):continue
                fact=(str(value),token)
                if fact in seen_facts:
                    row=seen_facts[fact]
                    if sid not in row['sections'].split('、'):row['sections']+='、'+sid
                    continue
                short=str(value)[max(0,match.start()-16):min(len(str(value)),match.end()+16)]
                row={'label':'正文数字（旧资料待原文核对）','value':token,'sections':sid,'url':'','excerpt':'旧报告片段（非官方原文）：'+short,'provenance_status':'legacy_unmapped','report_pointer':'/'+key+path,'token_index':index}
                numbers.append(row);seen_facts[fact]=row
    if any(r.get('provenance_status')=='legacy_unmapped' for r in numbers):gaps.append({'label':'旧高考报告的部分文字数字缺逐项原文绑定','reason':'旧资料仅保留整理表、调研文字与来源清单，没有逐项原文摘录。上述“旧报告原句”不是官方原文，不应当作官方已核；须按第12节官网和附件整理表逐项复查。','url':''})
    for item in result.get('list',[]):
        for field,label in [('p_clear','单独过线'),('p_land','最终录取'),('expected_cut_rank','预测位次'),('utility','偏好分')]:
            numbers.append({'label':item['name']+'：'+label,'value':item[field],'sections':'01、05、10','institution':'录取线模型计算（群体回测口径）','formula':{'p_clear':f'{round(item[field]*result["params"]["sims"])} ÷ {result["params"]["sims"]}（单独过线事件数/模拟次数）' if field=='p_clear' else '', 'p_land':f'{round(item[field]*result["params"]["sims"])} ÷ {result["params"]["sims"]}（此前均未命中、本项命中事件数/模拟次数）' if field=='p_land' else '', 'expected_cut_rank':'历史位次先按登记漂移调整，再对数近期加权求均值，取exp并取整；参数见第10节，原序候选表见附件。', 'utility':'本人优先级和登记评分；专业组按专业事件效用加权。完整操作数在附件，复算给定序列，不证明组合最优。'}[field],'result':item[field]})
    land=sum(x['p_land'] for x in result['list'])
    csvpath=candidate_file(root,result)
    raw_rows={r['id']:r for r in csv.DictReader(io.StringIO(csvpath.read_text(encoding='utf-8-sig')))}
    terms=[]
    for x in result['list']:
        raw=raw_rows[x['id']];adjusted=float(raw.get('utility_adjusted') or x['utility']) if x.get('obey',True) else result['params']['u_fall']
        if x.get('majors'):terms.extend((m['p'],m['utility']) for m in x['majors'])
        else:terms.append((x['p_land']-x.get('p_adjusted',0),x['utility']))
        terms.append((x.get('p_adjusted',0),adjusted))
    terms.append((result['p_fall'],result['params']['u_fall']))
    eu=sum(p*u for p,u in terms)

    numbers += [{'label':'总概率核对','value':land+result['p_fall'],'sections':'01、05','inputs':f'各志愿最终录取概率之和 {land}；滑档 {result["p_fall"]}','formula':'各志愿最终录取概率之和 + 滑档概率 = 1（浮点误差除外）','result':land+result['p_fall']}, {'label':'平均满意度核对','value':result['expected_utility'],'sections':'01、05','inputs':'；'.join(f'{p} × {u}' for p,u in terms),'formula':'Σ（各实际专业落点概率 × 该专业效用）+ Σ（调剂概率 × 调剂效用）+ 滑档概率 × 滑档效用；显示值按正文精度取整','result':eu}]
    limits=[{'claim':v,'reason':'只在本条所列数据与资格范围内有效。','change_if':'目标年招生计划、资格、本人排序或可承受风险变化时重新出表。','url':''} for v in [rep.get('backtest',''),*rep.get('profile',{}).get('tensions',[])] if v]
    for r in rep.get('assumptions',[]):limits.append({'claim':'：'.join(map(str,r)),'reason':'这是正文第10节已披露的适用条件。','change_if':'数据或该项假设变化后重算；原结果不再自动适用。','url':''})
    return {'case_info':case_info(case,binding,warning),'personal_inputs':personal,'numbers':numbers,'limitations':limits,'gaps':gaps}


def gaokao_files(root,rep,result,binding,result_path):
    root=Path(root);case=read(root/'case.json')
    groups=[]
    for title,text,published in rep.get('sources',[]):
        for url in re.findall(r'https?://[^\s；，。]+',text):groups.append({'title':title,'url':url.rstrip('；;，,。'),'metadata':published})
    evidence={'schema_version':1,'items':[],'source_groups':groups,'archive_gap':'旧文字中的数字未逐项留存官方原文，见附录待核清单；不得以报告自身原句充作官方摘录。'}
    calculations={'engine':'gaokao_result','expected_utility':result['expected_utility'],'p_fall':result['p_fall'],'stress':result.get('stress',{})}
    trace={'schema_version':1,'case_id':case['case_id'],'report_profile':binding,'numeric_claims':rep.get('numeric_claims',[]),'source_sha256':{'case.json':digest((root/'case.json').read_bytes()),'report.json':digest(json_bytes(rep)),'result.json':digest(json_bytes(result))}}
    files={'case.json':(root/'case.json').read_bytes(),'profile.json':(root/binding['file']).read_bytes(),'report.json':json_bytes(rep),'result.json':json_bytes(result),'evidence.json':json_bytes(evidence),'calculations.json':json_bytes(calculations),'report_trace.json':json_bytes(trace)}
    files['candidates.csv']=candidate_file(root,result).read_bytes()
    return files


def append_html(document,materials):
    import report
    return document.replace('</body>',report.keep_numeric_runs(report.verification_appendix_html(materials))+'</body>')


def attach_pdf(pdf,files,materials,case,binding,body_html):
    """The embedded trace excludes its own final PDF digest to avoid a hash cycle."""
    import pymupdf
    pdf=Path(pdf);doc=pymupdf.open(pdf)
    metadata=dict(doc.metadata);metadata.update(title=case.get('report_meta',{}).get('title',case.get('case_id','知衢报告')),subject='案例号：'+case['case_id']+'；画像SHA256：'+binding['sha256'],keywords='zhiqu;case_id='+case['case_id']+';profile_sha256='+binding['sha256'])
    doc.set_metadata(metadata)
    clean={}
    for name,body in files.items():
        if Path(name).name!=name or '\\' in name or ':' in name or not name.endswith(('.json','.csv','.txt')):raise ValueError('不安全的附件名')
        if len(body)>MAX_ATTACHMENT:raise ValueError('附件过大')
        if name=='report_trace.json':
            trace=json.loads(body);trace.get('artifacts',{}).pop('report.pdf',None);trace['pdf_digest_scope']='最终PDF哈希保存在外部追踪文件；嵌入副本不包含自身哈希，避免循环。';body=json_bytes(trace)
        clean[name]=body
    parser=SectionText();parser.feed(body_html)
    manifest={'schema':1,'case_id':case['case_id'],'profile_sha256':binding['sha256'],'materials':materials,
              'files':{name:digest(body) for name,body in clean.items()},'page_text_sha256':[digest(norm(p.get_text()).encode()) for p in doc],
              'body_numbers':{sid:NUMBER.findall(text) for sid,text in parser.sections().items() if sid.isdigit() and sid!='12'},
              'section_anchors':{sid:norm(next((line for line in text.splitlines() if line.strip()),'')) for sid,text in parser.sections().items() if sid.isdigit()},
              'limits':['离线一致不等于官方真实性；仍须联网核对出处。','未附原始名单的官方汇总统计只核对登记值，不能据此声称重算原始名单。','未作数字签名，不能证明作者身份；不能抵抗同时重写附件和核对清单的伪造。']}
    clean['verification.json']=json_bytes(manifest)
    for name,body in clean.items():doc.embfile_add(name,body,filename=name,ufilename=name,desc='知衢核对材料 '+name)
    target=pdf.with_suffix('.verified.tmp.pdf');doc.save(target,garbage=4,deflate=True);doc.close();target.replace(pdf)


def _record_generation(root,pdf):
    """Public simulations use the public register; private records stay local."""
    root=Path(root).resolve();pdf=Path(pdf).resolve();case=read(root/'case.json')
    public=ROOT/'skills/zhiqu-shared/references/cases.json'
    if root.is_relative_to(ROOT/'skills') and 'examples' in root.parts:
        if case.get('mode')!='simulation' and case.get('simulated') is not True:raise ValueError('公开目录只登记模拟案例')
        if not pdf.is_relative_to(root):return
        registry=read(public);matching=[r for r in registry['cases'] if r['case_id']==case['case_id']]
        if len(matching)!=1:raise ValueError('公开案例登记缺失或重号')
        record=matching[0]
        if (ROOT/record['directory']).resolve()!=root:raise ValueError('案例号登记在另一个目录')
        import pymupdf
        with pymupdf.open(pdf) as doc:manifest=json.loads(doc.embfile_get('verification.json'))
        metadata=dict(manifest['materials']['case_info']);name=str(pdf.relative_to(ROOT))
        record['profile']=case['report_profile']
        versions=[r for r in record.get('report_versions',[]) if r['file']!=name]
        versions.append({'file':name,'generated_at':metadata['生成时间'],'version':metadata['报告版本'],'sha256':digest(pdf.read_bytes()),'profile_sha256':case['report_profile']['sha256']})
        record['report_versions']=versions
        record['reports']=sorted(set(record.get('reports',[])+[name]))
        with tempfile.NamedTemporaryFile(dir=public.parent,prefix='.cases-',suffix='.tmp',delete=False) as handle:
            temporary=Path(handle.name);handle.write(json_bytes(registry))
        try:temporary.replace(public)
        finally:temporary.unlink(missing_ok=True)
    else:
        registry=root.parent/'cases.json'
        if registry.exists() and case['case_id'] in read(registry).get('cases',{}):
            from profile_store import record_report
            record_report(root.parent,case['case_id'],pdf)


def record_generation(root,pdf):
    # Separate renderers may finish concurrently; serialize public-register writes.
    import fcntl
    lock=ROOT/'.cache/report-registry.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:_record_generation(root,pdf)
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def extract_files(doc):
    if doc.embfile_count()>40:raise ValueError('附件数量超过核对上限')
    result={}
    for name in doc.embfile_names():
        if name in result or Path(name).name!=name or '\\' in name or ':' in name or not name.endswith(('.json','.csv','.txt')):raise ValueError('不安全或重复附件名')
        if doc.embfile_info(name).get('size',0)>MAX_ATTACHMENT:raise ValueError('附件超过读取上限')
        raw=doc.embfile_get(name)
        if len(raw)>MAX_ATTACHMENT:raise ValueError('附件超过读取上限')
        result[name]=raw
    if sum(map(len,result.values()))>64*1024*1024:raise ValueError('附件总大小超过读取上限')
    return result


def verify(pdf,extract=None):
    import pymupdf
    errors=[];online=[];checks=[]
    with pymupdf.open(pdf) as doc:
        files=extract_files(doc)
        required={'verification.json','case.json','profile.json','evidence.json','calculations.json','report_trace.json'}
        if not required<=set(files):return {'ok':False,'errors':['缺核对附件：'+', '.join(sorted(required-set(files)))],'online_sources':[]}
        manifest=json.loads(files['verification.json']);case=json.loads(files['case.json']);binding=case.get('report_profile',{})
        if binding.get('sha256')!=digest(files['profile.json']) or manifest.get('profile_sha256')!=binding.get('sha256'):errors.append('画像指纹与所用画像附件不一致')
        if manifest.get('case_id')!=case.get('case_id'):errors.append('案例号与附件不一致')
        meta=doc.metadata
        if 'case_id='+case['case_id'] not in meta.get('keywords','') or 'profile_sha256='+binding.get('sha256','') not in meta.get('keywords',''):errors.append('PDF元数据缺正确案例号或画像指纹')
        for name,expected in manifest.get('files',{}).items():
            if name not in files or digest(files[name])!=expected:errors.append('附件摘要不一致：'+name)
        texts=[norm(p.get_text()) for p in doc]
        if [digest(t.encode()) for t in texts]!=manifest.get('page_text_sha256'):errors.append('PDF正文或核对表已被改动（逐页文字校验不一致）')
        raw_text=''.join(p.get_text(sort=True) for p in doc)
        index_map=[i for i,ch in enumerate(raw_text) if not ch.isspace() and ch!='\u00ad']
        whole=norm(raw_text);appendix=''.join(texts).split('附录：核对材料',1)[-1]
        if '附录：核对材料' not in whole:errors.append('缺可提取文字的核对附录')
        # Chromium may paint SVG labels after a following heading, while spatial
        # sorting can interleave text from separate table columns. Take the maximum
        # occurrence count from both readings, never their sum. Per-page full text
        # hashes still reject any visible edit, even a repeated digit.
        readings=[]
        for spatial in (False,True):
            raw=''.join(doc[i].get_text(sort=spatial) for i in range(1,len(doc))) if len(doc)>1 else doc[0].get_text(sort=spatial)
            indices=[i for i,ch in enumerate(raw) if not ch.isspace() and ch!='\u00ad']
            body=norm(raw).split('附录：核对材料',1)[0];positions={};cursor=0
            for sid,anchor in sorted(manifest.get('section_anchors',{}).items()):
                start=body.find(anchor,cursor);positions[sid]=start
                if start>=0:cursor=start+len(anchor)
            counts={}
            for sid,start in positions.items():
                if start<0:continue
                stop=min((v for v in positions.values() if v>start),default=len(body))
                a=indices[start] if start<len(indices) else len(raw)
                b=indices[stop] if stop<len(indices) else len(raw)
                counts[sid]=Counter(NUMBER.findall(raw[a:b]))
            readings.append(counts)
        for sid,expected in manifest.get('body_numbers',{}).items():
            if all(sid not in r for r in readings):errors.append('正文缺节标题：'+sid);continue
            counts=readings[0].get(sid,Counter()) | readings[1].get(sid,Counter())
            if Counter(expected)-counts:errors.append('正文数字与生成输入不一致：第'+sid+'节')
        evidence=json.loads(files['evidence.json']);calculations=json.loads(files['calculations.json'])
        lookup={e['id']:e for e in evidence.get('items',[])}
        for row in manifest['materials']['numbers']:
            if norm(visible(row['value'])) not in appendix:errors.append('核对表缺数字：'+row['label'])
            if row.get('provenance_status')=='legacy_unmapped':
                rep=json.loads(files['report.json']);raw=ptr(rep,row['report_pointer'])
                tokens=NUMBER.findall(str(raw))
                if row['token_index']>=len(tokens) or tokens[row['token_index']]!=row['value']:errors.append('旧报告数字与核对表不一致：'+row['label'])
            if row.get('evidence_id'):
                e=lookup.get(row['evidence_id'],{})
                if e.get('value')!=row.get('raw_value') or e.get('excerpt','')!=row.get('excerpt',''):errors.append('核对表与证据原值/摘录不一致：'+row['label'])
            if row.get('url'):online.append({'organization':row.get('institution',''),'url':row['url'],'what':row['label']})
        # Recompute only registered, trusted algorithms. Embedded code is never run.
        try:
            if case.get('kind') in ('grad','career'):
                from verification_calculations import recompute
                fresh=recompute(case,json.loads(files['profile_parse.json']),evidence,calculations)
                if fresh!=calculations:errors.append('计算结果不能复算')
                checks.append('全部登记计算逐值复算')
            else:
                result=json.loads(files['result.json'])
                if abs(sum(x['p_land'] for x in result['list'])+result['p_fall']-1)>1e-8:errors.append('录取/滑档概率之和不为1')
                if [x['order'] for x in result['list']]!=list(range(1,len(result['list'])+1)):errors.append('志愿顺序不连续')
                from verification_calculations import recompute_gaokao
                recompute_gaokao(result,files['candidates.csv'])
                from check_report import check_report as check_gaokao
                report=json.loads(files['report.json']);issues=check_gaokao(report,result)
                errors.extend(issues);checks.append('逐志愿单独过线/最终录取/专业组概率、位次与基准压力情景复算；顺序与数字声明核对（不证明选表全局最优）')
        except (KeyError,ValueError,TypeError,ZeroDivisionError,IndexError) as exc:errors.append('计算核对失败：'+str(exc))
        for item in evidence.get('source_groups',[]):
            if item.get('url'):online.append({'organization':item.get('title',''),'url':item['url'],'what':'原始官方来源及适用年份'})
        for item in lookup.values():
            url=item.get('source',{}).get('url')
            if url:online.append({'organization':item['source'].get('organization',''),'url':url,'what':item.get('claim','')})
        if extract:
            target=Path(extract)
            if target.is_symlink():raise ValueError('提取目录不能是符号链接')
            target.mkdir(parents=True,exist_ok=True)
            for name,body in files.items():
                p=target/name
                if p.exists() or p.is_symlink():raise ValueError('不覆盖已有附件：'+str(p))
                p.write_bytes(body)
        return {'ok':not errors,'case_id':case['case_id'],'pages':len(doc),'attachments':sorted(files),'checks':checks,'errors':errors,'online_sources':list({(r['url'],r['what']):r for r in online}.values()),'limitations':manifest.get('limits',[])}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('pdf');ap.add_argument('--extract',type=Path);ap.add_argument('--json',action='store_true');args=ap.parse_args()
    try:result=verify(args.pdf,args.extract)
    except Exception as exc:result={'ok':False,'errors':['无法核对PDF：'+str(exc)]}
    if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        print(('通过' if result['ok'] else '未通过')+'：'+str(result.get('case_id','')))
        for item in result.get('checks',[]):print('✓ '+item)
        for item in result.get('errors',[]):print('✗ '+item)
        print('仍需联网核对的出处：')
        for r in result.get('online_sources',[]):print(r['organization']+'：'+r['url']+'；核对 '+r['what'])
        for item in result.get('limitations',[]):print('范围：'+item)
    raise SystemExit(0 if result['ok'] else 1)
if __name__=='__main__':main()
