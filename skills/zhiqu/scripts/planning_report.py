#!/usr/bin/env python3
"""Assemble staged graduate/career data, validate it, then publish report artifacts.

Usage: python3 skills/zhiqu/scripts/planning_report.py CASE_DIRECTORY --profile-version PROFILE_FILE
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
from planning_workflow import PlanningCase, FILES, FIGURE_TYPES, GENERATION_TOOLS, POLICY_FILES, SKILLS, dump, sha
from profile_store import source_files


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
    if typ=='data_gap':return '缺口：'+t(x['missing'])+'；去哪里取：'+t(x['source'])+'；预计 '+t(x['expected_by'])+' 复核补齐，届时未取得仍保留待核。'
    if typ in ('question_table','scenario_table'):
        # 追问和风险触发画成卡片（与高考报告同一组件），不再是三列表格。
        kind={'question_table':'questions','scenario_table':'scenarios'}[typ]
        return '\n'.join(['::: '+kind,'columns: '+' | '.join(t(v) for v in x['columns']),*['- '+' | '.join(t(v) for v in r) for r in x['rows']],':::'])
    if typ in ('data_table','candidate_table','profile_table','assumption_table','term_table','offer_table'):
        return table([t(v) for v in x['columns']],[[t(v) for v in r] for r in x['rows']])
    if typ in ('decision_questions','direction_cards'):
        return '\n'.join('- '+t(v['text'] if isinstance(v,dict) else v) for v in x['items'])
    if typ in FIGURE_TYPES:
        tag={'comparison_matrix':'matrix'}.get(typ,typ)
        refs=','.join(dict.fromkeys(str(numbers[e]) for e in node['evidence_refs']))
        opts=['::: '+tag+' '+t(x['title']),'caption: '+t(x['caption']),'source: '+refs]
        for k in ('unit','max','percent'):
            if x.get(k):opts.append(k+': '+t(x[k]))
        if 'columns' in x:opts.append('columns: '+' | '.join(t(v) for v in x['columns']))
        return '\n'.join([*opts,*['- '+' | '.join(t(v) for v in r) for r in x['rows']],':::'])
    if typ=='route_cards':return '::: route '+t(x['title'])+'\n'+'\n'.join('- '+k+' | '+t(x[k]) for k in ('门槛','时间窗口','投入','切换条件'))+'\n:::'
    if typ=='evidence_legend':return '::: evidence\n'+'\n'.join('- '+' | '.join(t(v) for v in r) for r in x['rows'])+'\n:::'
    if typ=='unknown_explanation':return '### 仍需补充的信息\n\n'+'\n\n'.join(t(x[k]) for k in ('missing_information','retrieval_plan','decision_changes'))
    if typ=='disclaimer':return t(x['text'])
    if typ=='source_endnotes':return '__STAGED_SOURCES__'
    raise ValueError('未实现的组件：'+str(typ))


def offer_gap_notice(case, sid):
    section=next(s for s in case.contract['sections'] if s['id']==sid)
    if not any(not case.active(s) and s.get('otherwise')=='explicit_no_offer_and_input_gaps' for s in section['slots']):
        return ''
    # Suppress only when the existing paragraph already covers both the missing
    # offer and the need to establish comparable income conditions.
    visible=' '.join(str(case.get_node(e['ref']).get('content',{})) for e in case.nodes()[sid])
    if re.search(r'没有|暂无|尚无|还没|未拿到',visible) and re.search(r'offer|录用|工作',visible,re.I) and re.search(r'工资|薪|收入|工时|生活.*支出',visible):
        return ''
    return '你还没有拿到工作录用通知；先问清工资、工时、社保公积金和生活开销，再比较能存下多少钱。'


def assemble(case):
    case.trace=[]
    groups=case.data['evidence.json']['source_groups'];numbers={}
    for eid,item in case.evidence.items(): numbers[eid]=item['source_group']
    meta=case.case['report_meta'];out=['---',*[k+': '+case.expand(v,'meta.'+k) for k,v in meta.items()],'mode: '+case.case.get('mode','simulation'),'---','']
    for section in case.contract['sections']:
        sid=section['id'];title=case.data['narrative.json']['sections'][sid].get('title',section['default_title']) if section.get('title_override_allowed',True) else section['default_title']
        out.append('## '+sid+' '+title);out.append('')
        for index,entry in enumerate(case.nodes()[sid]):
            node=case.get_node(entry['ref']);where=f'{sid}.{entry["slot"]}.{index}'
            slot=next(s for s in section['slots'] if s['key']==entry['slot'])
            if not case.active(slot):continue
            if slot.get('heading'):
                import copy
                node=copy.deepcopy(node);node['content']['heading']=slot['heading']
            out.append(node_markdown(node,lambda text:case.expand(text,where),numbers));out.append('')
        notice=offer_gap_notice(case,sid)
        if notice:out.extend([notice,''])
    source='::: sources\n'+'\n'.join('- '+g['title']+' | '+g.get('url','')+' | '+g['metadata'] for g in groups)+'\n:::'
    markdown='\n'.join(out).replace('__STAGED_SOURCES__',source)
    return '\n'.join(line.rstrip() for line in markdown.splitlines()).rstrip()+'\n',case.trace


def input_snapshot(case):
    return {f:sha(case.root/f) for f in (*FILES,*source_files(case.root))}


def generate(root, html_only=False, profile_version=None):
    import render_report
    import check_report
    from check_layout import check_pdf
    from verify_report import bind_profile, planning_materials, append_html, attach_pdf, require_analysis_profile, report_pdf_name
    if not profile_version:raise ValueError('生成报告必须明确指定 profile_version / --profile-version')
    binding, profile, warning=bind_profile(root,profile_version,require_analysis=True)
    if warning:print(warning,file=sys.stderr)
    case=PlanningCase(root);errors=case.check(8)
    # 只在出报告时要求：只做到前几个阶段的案例，封面结论还是占位。
    if len(re.sub(r'\{\{[^}]*\}\}','0',case.case.get('report_meta',{}).get('conclusion','')))<60:
        errors.append('case.json report_meta.conclusion：封面一句话结论太短；写清本人情况与在乎什么、建议是什么（带关键数字）、先做什么，两三句')
    if errors:raise ValueError('\n'.join(errors))
    markdown,trace=assemble(case)
    document=render_report.render(markdown)[0]
    materials=planning_materials(case,trace,binding,warning)
    document=append_html(document,materials)
    errors=check_report.check_publication_html(document)
    if errors:raise ValueError('\n'.join(errors))
    # Prepare everything before touching any existing output; rollback on replacement error.
    pdf_name=report_pdf_name(case.case['case_id'])
    names=['report.md','report.html','report_trace.json','operator_check.md']+([] if html_only else [pdf_name])
    with tempfile.TemporaryDirectory(prefix='.planning-',dir=case.root) as temp:
        tmp=Path(temp);(tmp/'report.md').write_text(markdown);(tmp/'report.html').write_text(document)
        if not html_only:
            render_report._print_pdf(document,tmp/pdf_name)
            errors=check_pdf(str(tmp/pdf_name))
            if errors:raise ValueError('\n'.join(errors))
        from operator_check import generate as operator_generate
        operator_generate(case.root,output=tmp/'operator_check.md')
        manifest={'schema_version':1,'case_id':case.case['case_id'],'source_sha256':input_snapshot(case),
                  'contract_sha256':sha(case.contract_path()),
                  'tool_sha256':{f:sha(Path(__file__).with_name(f)) for f in GENERATION_TOOLS},
                  'numeric_refs':trace,'artifacts':{n:sha(tmp/n) for n in names if n not in ('report_trace.json','operator_check.md')},'delivery_status':'awaiting_operator_and_independent_review'}
        from authoring_metadata import trace_metadata
        manifest.update(trace_metadata(case.case,[Path(__file__).with_name(f) for f in ('planning_report.py','render_report.py','report.py')]))
        manifest['policy_sha256']={f:sha(SKILLS/f) for f in POLICY_FILES}
        manifest['report_profile']=binding
        manifest['verification_tools_sha256']={f:sha(Path(__file__).with_name(f)) for f in ('verify_report.py','verification_calculations.py')}
        dump(tmp/'report_trace.json',manifest)
        if not html_only:
            files={name:(case.root/name).read_bytes() for name in ('case.json','profile_parse.json','evidence.json','calculations.json')}
            files['profile.json']=(case.root/binding['file']).read_bytes()
            files['report_trace.json']=(tmp/'report_trace.json').read_bytes()
            attach_pdf(tmp/pdf_name,files,materials,case.case,binding,document)
            from verify_report import verify
            verification=verify(tmp/pdf_name)
            if not verification['ok']:raise ValueError('PDF核对失败：'+'；'.join(verification['errors']))
            manifest['artifacts'][pdf_name]=sha(tmp/pdf_name)
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
    from claim_check import build as build_claims
    build_claims(case.root,bind=True)
    if not html_only:
        from verify_report import record_generation
        record_generation(case.root,case.root/pdf_name)
    return case.root/pdf_name if not html_only else case.root/'report.html'


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('case_dir');ap.add_argument('--profile-version',required=True,help='明确指定案例内所用画像文件');ap.add_argument('--html-only',action='store_true',help='仅供检查HTML草稿，不发布PDF');args=ap.parse_args()
    try:print(generate(args.case_dir,args.html_only,args.profile_version))
    except (ValueError,KeyError,TypeError,OSError) as exc:ap.exit(1,str(exc)+'\n未发布新交付件。\n')
if __name__=='__main__':main()
