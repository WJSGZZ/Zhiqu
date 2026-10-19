#!/usr/bin/env python3
"""Assemble staged graduate/career data, validate it, then publish report artifacts.

Usage: python3 skills/zhiqu/scripts/planning_report.py CASE_DIRECTORY
The separate operator checklist is not included in the customer's PDF.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from planning_workflow import PlanningCase, FILES, dump, sha


def table(columns, rows):
    return '\n'.join(['| '+' | '.join(columns)+' |','|'+'|'.join(['---']*len(columns))+'|',*['| '+' | '.join(map(str,r))+' |' for r in rows]])


def node_markdown(node, expand, numbers):
    typ=node['type'];x=node.get('content',{})
    def t(value): return expand(value)
    if typ=='conclusion_sentence':return '**'+t(x['text']).strip('*')+'**'
    if typ=='analysis':
        kind=x.get('kind','paragraph')
        if kind=='heading':return '### '+t(x['text'])
        if kind=='list':return '\n'.join('- '+t(v) for v in x['items'])
        if kind=='callout':return '> [!'+x.get('style','note')+'] '+re.sub(r'^\[!\w+\]\s*','',t(x['title']))+'\n'+'\n'.join('> '+t(v) for v in x['items'])
        if kind=='comment':return ''
        return t(x['text'])
    if typ=='kpi':return '::: kpi\n'+'\n'.join('- '+' | '.join(t(v) for v in r) for r in x['rows'])+'\n:::'
    if typ=='titled_points':return '> [!key] 核心结论\n'+'\n'.join('> - **'+t(v['title'])+'**：'+t(v['text']) for v in x['items'])
    if typ=='dated_actions':
        lines=[]
        for v in x['items']:
            text=t(v['text']);deadline=t(v['date'])
            # Keep an already written calendar date; otherwise the typed date must be visible.
            if not re.search(r'\d+\s*月\s*\d+\s*日|\d{4}-\d{2}-\d{2}',text):text=deadline+'：'+text
            lines.append('> - '+text)
        return '> [!warn] '+x.get('heading','接下来要做的事')+'\n'+'\n'.join(lines)
    if typ=='checkpoint':return t(x['text'])
    if typ in ('data_table','candidate_table','profile_table','assumption_table','term_table','question_table','offer_table'):
        return table([t(v) for v in x['columns']],[[t(v) for v in r] for r in x['rows']])
    if typ in ('decision_questions','direction_cards'):
        return '\n'.join('- '+t(v['text'] if isinstance(v,dict) else v) for v in x['items'])
    if typ=='scenario_table':return table([t(v) for v in x['columns']],[[t(v) for v in r] for r in x['rows']])
    if typ in ('bars','interval','timeline','comparison_matrix'):
        tag={'comparison_matrix':'matrix'}.get(typ,typ)
        refs=','.join(dict.fromkeys(str(numbers[e]) for e in node['evidence_refs']))
        opts=['::: '+tag+' '+t(x['title']),'caption: '+t(x['caption']),'source: '+refs]
        for k in ('unit','max'):
            if x.get(k):opts.append(k+': '+t(x[k]))
        if 'columns' in x:opts.append('columns: '+' | '.join(t(v) for v in x['columns']))
        return '\n'.join([*opts,*['- '+' | '.join(t(v) for v in r) for r in x['rows']],':::'])
    if typ=='route_cards':return '::: route '+t(x['title'])+'\n'+'\n'.join('- '+k+' | '+t(x[k]) for k in ('门槛','时间窗口','投入','切换条件'))+'\n:::'
    if typ=='evidence_legend':return '::: evidence\n'+'\n'.join('- '+' | '.join(t(v) for v in r) for r in x['rows'])+'\n:::'
    if typ=='unknown_explanation':return '### 仍需补充的信息\n\n'+'\n\n'.join(t(x[k]) for k in ('missing_information','retrieval_plan','decision_changes'))
    if typ=='disclaimer':return t(x['text'])
    if typ=='source_endnotes':return '__STAGED_SOURCES__'
    raise ValueError('未实现的组件：'+str(typ))


def assemble(case):
    case.trace=[]
    groups=case.data['evidence.json']['source_groups'];numbers={}
    for eid,item in case.evidence.items(): numbers[eid]=item['source_group']
    meta=case.case['report_meta'];out=['---',*[k+': '+case.expand(v,'meta.'+k) for k,v in meta.items()],'---','']
    for section in case.contract['sections']:
        sid=section['id'];title=case.data['narrative.json']['sections'][sid].get('title',section['default_title'])
        out.append('## '+sid+' '+title);out.append('')
        for index,entry in enumerate(case.nodes()[sid]):
            node=case.get_node(entry['ref']);where=f'{sid}.{entry["slot"]}.{index}'
            slot=next(s for s in section['slots'] if s['key']==entry['slot'])
            if not case.active(slot):continue
            if slot.get('heading'):
                import copy
                node=copy.deepcopy(node);node['content']['heading']=slot['heading']
            out.append(node_markdown(node,lambda text:case.expand(text,where),numbers));out.append('')
        inactive=[s for s in section['slots'] if not case.active(s) and s.get('otherwise')=='explicit_no_offer_and_input_gaps']
        if inactive:out.extend(['当前没有真实offer或具备输入依据的收入情景；应先取得工资、工时、缴存与生活支出条件，再比较收入。',''])
    source='::: sources\n'+'\n'.join('- '+g['title']+' | '+g.get('url','')+' | '+g['metadata'] for g in groups)+'\n:::'
    markdown='\n'.join(out).replace('__STAGED_SOURCES__',source)
    return '\n'.join(line.rstrip() for line in markdown.splitlines()).rstrip()+'\n',case.trace


def input_snapshot(case):
    return {f:sha(case.root/f) for f in (*FILES,'profile.txt')}


def generate(root, html_only=False):
    import render_report
    import check_report
    from check_layout import check_pdf
    case=PlanningCase(root);errors=case.check(8)
    if errors:raise ValueError('\n'.join(errors))
    markdown,trace=assemble(case)
    document=render_report.render(markdown)[0]
    errors=check_report.check_publication_html(document)
    if errors:raise ValueError('\n'.join(errors))
    # Prepare everything before touching any existing output; rollback on replacement error.
    names=['report.md','report.html','report_trace.json','operator_check.md']+([] if html_only else ['report.pdf'])
    with tempfile.TemporaryDirectory(prefix='.planning-',dir=case.root) as temp:
        tmp=Path(temp);(tmp/'report.md').write_text(markdown);(tmp/'report.html').write_text(document)
        if not html_only:
            cmd=[sys.executable,str(Path(__file__).with_name('render_report.py')),str(tmp/'report.md'),'--out',str(tmp/'report.pdf')]
            result=subprocess.run(cmd,capture_output=True,text=True)
            if result.returncode or not (tmp/'report.pdf').is_file():raise ValueError('PDF渲染失败：'+result.stdout+result.stderr)
            errors=check_pdf(str(tmp/'report.pdf'))
            if errors:raise ValueError('\n'.join(errors))
        from operator_check import generate as operator_generate
        operator_generate(case.root,output=tmp/'operator_check.md')
        manifest={'schema_version':1,'case_id':case.case['case_id'],'source_sha256':input_snapshot(case),
                  'contract_sha256':sha(case.contract_path()),
                  'tool_sha256':{f:sha(Path(__file__).with_name(f)) for f in ('planning_report.py','planning_workflow.py','operator_check.py','check_demos.py','report.py','render_report.py')},
                  'numeric_refs':trace,'artifacts':{n:sha(tmp/n) for n in names if n not in ('report_trace.json','operator_check.md')},'delivery_status':'awaiting_operator_and_independent_review'}
        dump(tmp/'report_trace.json',manifest)
        previous={name:(case.root/name).read_bytes() if (case.root/name).exists() else None for name in names}
        try:
            for name in names:os.replace(tmp/name,case.root/name)
        except OSError:
            for name,body in previous.items():
                p=case.root/name
                if body is None:p.unlink(missing_ok=True)
                else:p.write_bytes(body)
            raise
    return case.root/'report.pdf' if not html_only else case.root/'report.html'


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('case_dir');ap.add_argument('--html-only',action='store_true',help='仅供检查HTML草稿，不发布PDF');args=ap.parse_args()
    try:print(generate(args.case_dir,args.html_only))
    except (ValueError,KeyError,TypeError,OSError) as exc:ap.exit(1,str(exc)+'\n未发布新交付件。\n')
if __name__=='__main__':main()
