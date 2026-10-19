#!/usr/bin/env python3
"""Generate the separate operator checklist; never fill human confirmations."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from datetime import date
from planning_workflow import read, sha, day

MARKER=re.compile(r'<!-- operator-item (\{.*?\}) -->\n(.*?)(?=\n<!-- operator-item |\Z)',re.S)


def fingerprint(item):
    return hashlib.sha256(json.dumps(item,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def selected_evidence(items, as_of, judgment=None, due_days=30, dependencies=None):
    """Selection is a union; follow judgment/calc refs, including unflagged evidence."""
    by={x['id']:x for x in items};selected=[];ids=set()
    from planning_workflow import walk, REF
    if judgment:
        deps=dependencies or {};seen=set()
        def follow(obj):
            for _,value in walk(obj):
                if not isinstance(value,str):continue
                if value in by:ids.add(value)
                for m in REF.finditer(value):
                    if m[1]=='e':ids.add(m[2].split('#')[0])
                    elif m[1]=='c':follow_key('c:'+m[2])
                follow_key(value)
        def follow_key(key):
            if key in seen:return
            seen.add(key)
            if key in deps:follow(deps[key])
            for candidate in judgment.get('candidates',[]):
                if key in (candidate.get('id'),candidate.get('candidate_id')):follow(candidate)
        follow(judgment.get('recommendation',{}))
        # Summary prose and calculation inputs can affect a conclusion indirectly.
        follow(judgment.get('main_evidence_dependencies',[]))
    today=day(as_of)
    for e in items:
        reasons=[]
        if e.get('grade')!='官方':reasons.append('非官方依据')
        if e.get('status')=='unretrieved':reasons.append('原文未取到')
        try:
            diff=(day(e['review_due'])-today).days
            if diff<=due_days:reasons.append('已过期' if diff<0 else '临近复核期限')
        except (KeyError,ValueError,TypeError):reasons.append('缺有效复核期限')
        if e.get('main_conclusion') or e['id'] in ids:reasons.append('影响主结论')
        if reasons:selected.append((e,reasons))
    return selected


def dependencies_for(case):
    deps={}
    for key in ('paths','school_programs','job_types','jobs'):
        for c in case.data['candidates.json'].get(key,[]):deps[c['id']]=c
    plan=case.case.get('calculation_plan',{})
    if plan.get('dependencies',{}).get('*')=='all_inputs':
        from planning_workflow import walk
        for path,value in walk(case.data['calculations.json']):
            if isinstance(value,(int,float)) and not isinstance(value,bool):deps['c:'+path]=list(plan.get('inputs',{}).values())
    else:
        for path,refs in plan.get('dependencies',{}).items():deps['c:'+path]=refs
    return deps


def legacy_evidence(root, rep=None):
    """Read-only bridge for existing gaokao files; unlabelled data stays unknown."""
    root=Path(root);rep=rep or read(root/'report.json');items=[]
    for i,row in enumerate(rep.get('sources',[]),1):
        urls=list(dict.fromkeys(re.findall(r'https?://[^\s；，）]+',str(row[1])))) or ['']
        for j,url in enumerate(urls):
            eid=f'G{i:03d}'+(f'-{j+1}' if len(urls)>1 else '')
            items.append({'id':eid,'claim':row[0],'value':None,'unit':'','grade':None,
                          'status':'unretrieved' if not url else 'verified','source':{'organization':str(row[1]),'url':url,'locator':f'report.json#/sources/{i-1}；发布机构/原记录：{row[1]}'},
                          'review_due':None,'main_conclusion':True,'scope':'按原报告的省份、年份、条目核适用性；未自动认证原文',
                          'gap':'旧记录未含逐条取文/等级信息，需回官方原文核查','origin_sha256':sha(root/'report.json')})
    return items


def report_locations(case):
    """Return human-readable section/table positions for each provenance reference."""
    from planning_workflow import REF, walk
    locations={}
    for sid, entries in case.nodes().items():
        for block_index,entry in enumerate(entries):
            node=case.get_node(entry['ref']);content=node.get('content',{})
            labels={'analysis':'正文第 '+str(block_index+1)+' 块','kpis':'摘要数字卡','details':'比较表','actions':'接下来三件事','lead':'节首结论','core_points':'核心结论','profile':'本人画像','questions':'待核问题','assumptions':'费用与假设表'}
            title=content.get('title') or content.get('heading') or labels.get(entry['slot'],entry['slot'])
            for path,value in walk(content):
                if not isinstance(value,str):continue
                place=f'第 {int(sid)} 节 · {case.expand(title)}'
                parts=path.strip('/').split('/')
                if parts[0]=='rows' and len(parts)>2:
                    row=int(parts[1]);col=int(parts[2]);cols=content.get('columns',[])
                    label=case.expand(content['rows'][row][0])
                    place+=f' · {label} · '+(case.expand(cols[col]) if col<len(cols) else f'第 {col+1} 栏')
                elif parts[0]=='items' and len(parts)>1:place+=f' · 第 {int(parts[1])+1} 项'
                for m in REF.finditer(value):
                    key=m[1]+':'+m[2]
                    locations.setdefault(key,[])
                    if place not in locations[key]:locations[key].append(place)
    return locations


def compact_places(places):
    sections={}
    for place in places:
        parts=place.split(' · ');section=parts[0];component=parts[1] if len(parts)>1 else '正文'
        detail=parts[2] if len(parts)>2 else ''
        if detail.startswith('第 ') and detail.endswith(' 栏'):detail=''
        group=sections.setdefault(section,{})
        if detail not in group.setdefault(component,[]):group[component].append(detail)
    return '；'.join(section+'：'+'、'.join(component+('（'+'、'.join(d for d in details if d)+'）' if any(details) else '') for component,details in components.items()) for section,components in sections.items())


def checklist_groups(root, rep=None):
    """One source file per item, plus one profile and one declared-scenario item."""
    from planning_workflow import REF, walk, pointer
    root=Path(root);planning=(root/'evidence.json').exists()
    if not planning:
        items=legacy_evidence(root,rep);groups={}
        for e,reasons in selected_evidence(items,date.today().isoformat()):
            key=e['source'].get('url') or e['id']
            g=groups.setdefault(key,dict(id=e['id'],title=e['claim'],source=e['source'],items=[],reasons=[],checks=[]))
            g['items'].append(e);g['reasons']=list(dict.fromkeys(g['reasons']+reasons))
            url=e['source'].get('url','');detail=[]
            report=rep or read(root/'report.json')
            for index,row in enumerate(report.get('news',[])):
                if url and url in str(row):detail.append(str(row[0])+' → 第 8 节近期报道与政策，第 '+str(index+1)+' 行')
            for school in report.get('research',[]):
                if url and url in school.get('sources',[]):
                    selected=[row for row in school.get('items',[]) if str(row[0]) in e['claim']]
                    for row in selected:detail.append(school['school']+' / '+str(row[0])+'：'+str(row[1])+' → 第 6 节学校核查，'+school['school']+' / '+str(row[0]))
            if not detail:
                section='第 11 节事后回看' if '只用于第 11' in e['claim'] else '第 6 节志愿表与第 10 节方法' if '位次' in e['claim'] or '投档表' in e['claim'] else '第 12 节来源，核对应正文条款'
                detail=[e['claim']+' → '+section+'；原登记 '+e['source']['locator'].split('；')[0]]
            g['checks'].extend(detail)
        return list(groups.values()), date.today().isoformat(), {}
    from planning_workflow import PlanningCase
    c=PlanningCase(root);loc=report_locations(c);groups={}
    # Follow registered input roles; program length is not an input to annual cost.
    for key,places in list(loc.items()):
        paths=[];extra=[]
        if key.startswith(('c:/annual_cost','c:/annual_margin','c:/total_cost_over_program')):
            paths=['/budget/annual_tuition']
            if key.startswith('c:/total_cost_over_program'):paths.append('/budget/years')
        elif key.startswith('c:/gdut_fee_reference/'):
            paths=['/additional_scenarios/gdut_fee_reference/official_tuition']
            if key.endswith('/total_cost'):paths.append('/additional_scenarios/gdut_fee_reference/years')
        elif key.startswith(('c:/hypothetical_offers/','c:/offer_b_ordinary_month/')):
            paths=['/hypothetical_followup/ss_base_limits/lower','/hypothetical_followup/ss_base_limits/upper']
            extra=[e['id'] for e in c.evidence.values() if e['source_group']==11 and e.get('unit')=='元/年']
        ids=list(extra)
        for path in paths:
            binding=c.case['calculation_plan']['inputs'].get(path,'');m=REF.fullmatch(binding)
            if m and m[1]=='e':ids.append(m[2].split('#')[0])
        for eid in ids:
            target=loc.setdefault('e:'+eid+'#/value',[])
            target.extend(p for p in places if p not in target)
    reasons_by={e['id']:r for e,r in selected_evidence(list(c.evidence.values()),c.case['context']['as_of'],c.data['judgment.json'],c.limits['operator_due_days'],dependencies_for(c))}
    for e in c.evidence.values():
        if e.get('source_group')==1:continue
        source=e['source'];key=source.get('url') or 'unretrieved:'+e['id']
        group=groups.setdefault(key,dict(id=e['id'],title=c.data['evidence.json']['source_groups'][e['source_group']-1]['title'].split('；')[0],source=source,items=[],reasons=[],checks=[],scope=e.get('scope','')))
        group['items'].append(e);group['reasons']=list(dict.fromkeys(group['reasons']+reasons_by.get(e['id'],[])))
        places=loc.get('e:'+e['id']+'#/value',[])
        if e.get('value') is not None:
            text=e['claim']+' = '+str(e['value'])+((' '+e['unit']) if e.get('unit') else '')
            if not places:places=['计算输入；case.json 的 calculation_plan.inputs']
            group['checks'].append(text+' → '+compact_places(places))
        elif e.get('status')=='unretrieved':group['checks'].append('未取到：'+e.get('gap','原文不可用')+' → 候选清单与相关结论的资格缺口')
    def source_group_for_calc(path):
        if path.startswith('/scut_reference_statistics/2025') or path.startswith('/sample_reconciliation_2025'):return 12
        if path.startswith('/scut_reference_statistics/'):return 7
        if path.startswith('/gdut_2026_first_choice_retest_scores/'):return 14
        if path.startswith('/reference_wages_cny/'):return 2
        if path.startswith('/report_parameters/'):
            spec=c.case['calculation_plan']['display_inputs'].get(path.split('/')[2],{})
            if spec.get('role')=='anonymous_aggregate':return spec['source_group']
        return None
    for key,places in loc.items():
        if not key.startswith('c:'):continue
        path=key[2:];gid=source_group_for_calc(path)
        if gid:
            url=c.data['evidence.json']['source_groups'][gid-1]['url'];group=groups.get(url)
            if group:group['checks'].append('匿名加工/换算 '+path.replace('/scut_reference_statistics/','华工 ').replace('/gdut_2026_first_choice_retest_scores/','广工复试 ').replace('/reference_wages_cny/','工资换算 ').replace('/report_parameters/','输入 ').replace('additional_scenarios__gdut_2026_first_choice_retest_scores__full_time_rows','全日制复试总人数').replace('additional_scenarios__gdut_2026_first_choice_retest_scores__excluded_soldier_rows','排除专项人数').replace('/q1','/四分之一位').replace('/q3','/四分之三位').replace('/median','/中位数').replace('/n','/人数').replace('/min','/最低').replace('/max','/最高')+' = '+c.format(c.resolve('c',path))+' → '+compact_places(places))
    for g in groups.values():
        if not g['checks']:
            # Qualitative rules retain precise original-file locations instead of repeating the report sentence.
            e=g['items'][0];g['checks']=[e.get('original_locator') or e['source']['locator']]
        # Include a compact location for qualitative source files too.
        sections=[]
        for sid,entries in c.nodes().items():
            if any(any(eid in {e['id'] for e in g['items']} for eid in c.get_node(entry['ref']).get('evidence_refs',[])) for entry in entries):sections.append(str(int(sid)))
        g['report_sections']='、'.join(sections)
    profile=[]
    for i,f in enumerate(c.data['profile_parse.json']['fields']):
        if f['status']=='given':
            for path,value in walk(f['value']):profile.append(f['field']+path+' = '+str(value)+' → '+(compact_places(loc.get('p:/fields/'+str(i)+'/value'+path,[])) or '第 2 节画像与判断输入'))
    for item in c.data['profile_parse.json'].get('missing',[]):profile.append('尚缺 '+item['field']+'：'+item.get('question',item['field']))
    personal=dict(id='PROFILE',title='和客户确认画像',source={'locator':'profile.txt 对应节名；profile_parse.json.fields 的 quote/value'},items=c.data['profile_parse.json']['fields'],reasons=['本人登记与缺项'],checks=profile,scope='只确认本人提供的信息，不把报告情景当真实成绩、录取或offer')
    assumptions=[]
    for key,spec in c.case['calculation_plan'].get('display_inputs',{}).items():
        if spec['role']=='declared_scenario':
            assumptions.append(spec['description']+' = '+str(pointer(c.case,spec['case_pointer']))+' → '+(compact_places(loc.get('c:/report_parameters/'+key,[])) or '计算输入与敏感性情景'))
    scenario=dict(id='SCENARIO',title='确认条件情景与计算口径',source={'locator':'case.json 的 budget / hypothetical_followup / additional_scenarios；calculations.json'},items={'inputs':c.case['calculation_plan'],'outputs':c.data['calculations.json']},reasons=['假设与加工不等于本人事实'],checks=assumptions,scope='确认前提、单位、取整和压力测试；复算通过不等于现实中已取得该结果')
    ordered=sorted(groups.values(),key=lambda g:('影响主结论' not in g['reasons'],'原文未取到' not in g['reasons'],g['id']))
    return ordered+[personal,scenario],c.case['context']['as_of'],c.case


def generate(root, rep=None, output=None):
    root=Path(root);groups,now,case=checklist_groups(root,rep);path=root/'operator_check.md';previous={}
    if path.exists():
        for m in MARKER.finditer(path.read_text()):
            meta=json.loads(m[1]);previous[(meta['id'],meta['fingerprint'])]=m[2]
    out=['# 操控者核查单','', '操控者是交付报告前亲自核查关键信息的人。本单不进入客户报告；未勾选与未填写表示尚未完成。','',f'核查基准：{now}；案例：{case.get("case_id",root.name)}。按同一来源文件合并，共 {len(groups)} 项。','']
    for g in groups:
        marker={'id':g['id'],'fingerprint':fingerprint(g)};out.append('<!-- operator-item '+json.dumps(marker,ensure_ascii=False)+' -->')
        old=previous.get((g['id'],marker['fingerprint']))
        if old:out.extend([old.rstrip(),'']);continue
        out.extend([f'- [ ] {g["id"]}｜{g["title"]}｜'+ ' / '.join(g['reasons']), '  核什么：'])
        out.extend('  - '+text for text in dict.fromkeys(g['checks']))
        source=g['source'];out.extend(['  适用范围：'+g.get('scope','只核本报告对应省份、年份、计划和对象；不外推')+'。',
            '  去哪里核：'+(source.get('url') or source.get('locator','原画像')),
            '  定位：'+('报告第 '+g['report_sections']+' 节；' if g.get('report_sections') else '')+('；'.join(dict.fromkeys(e.get('original_locator') or '相关表行/条款' for e in g['items'] if e.get('value') is not None or e.get('status')=='unretrieved'))[:600] or '原文件标题、适用对象及报告所引条款')+'。' if isinstance(g['items'],list) and g['items'] and isinstance(g['items'][0],dict) and 'source' in g['items'][0] else '  定位：按上列登记字段逐项核对。',
            '  核完填：核查人：___；核查日期：___；结果（确认/不符/仍未知）：___；原文依据与范围：___；对建议的处理：___。',''])
    destination=Path(output) if output else path;destination.write_text('\n'.join(out),encoding='utf-8');return destination


def validate_operator(root,require_completed=False):
    root=Path(root);p=root/'operator_check.md'
    if not p.exists():return ['operator_check.md：缺操控者核查单']
    text=p.read_text();errors=[];records={json.loads(m[1])['id']:(json.loads(m[1]),m[2]) for m in MARKER.finditer(text)}
    groups,_,_=checklist_groups(root)
    for g in groups:
        if g['id'] not in records or records[g['id']][0]['fingerprint']!=fingerprint(g):errors.append('operator_check.md：漏项/已变更 '+g['id'])
    if set(records)!={g['id'] for g in groups}:errors.append('operator_check.md：存在过期或额外核查项')
    for eid,(_,body) in records.items():
        if any(k not in body for k in ('核什么：','去哪里核：','核完填：')):errors.append('operator_check.md：核查内容不完整 '+eid)
        if require_completed:
            result=re.search(r'结果（确认/不符/仍未知）：([^；\n]+)',body);checked=re.search(r'核查日期：(\d{4}-\d{2}-\d{2})',body)
            if '- [x]' not in body.lower() or '___' in body or not result or result[1].strip() not in ('确认','不符') or not checked:errors.append('operator_check.md：尚未完成 '+eid)
            else:
                try:day(checked[1])
                except ValueError:errors.append('operator_check.md：核查日期不合法 '+eid)
    return errors


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('case_dir');args=ap.parse_args();print(generate(args.case_dir))
if __name__=='__main__':main()
