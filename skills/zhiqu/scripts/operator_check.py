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
        urls=re.findall(r'https?://[^\s；，）]+',str(row[1]));url=urls[0] if urls else ''
        items.append({'id':f'G{i:03d}','claim':row[0],'value':None,'unit':'','grade':None,
                      'status':'unretrieved' if not url else 'verified','source':{'organization':str(row[1]),'url':url,'locator':f'report.json#/sources/{i-1}；发布机构/原记录：{row[1]}'},
                      'review_due':None,'main_conclusion':True,'scope':'按原报告的省份、年份、条目核适用性；未自动认证原文',
                      'gap':'旧记录未含逐条取文/等级信息，需回官方原文核查','origin_sha256':sha(root/'report.json')})
    return items


def generate(root, rep=None, output=None):
    root=Path(root);case=read(root/'case.json') if (root/'case.json').exists() else {}
    if (root/'evidence.json').exists():
        from planning_workflow import PlanningCase
        p=PlanningCase(root);items=list(p.evidence.values());judgment=p.data.get('judgment.json',{});now=case['context']['as_of'];due=p.limits['operator_due_days']
        missing=p.data.get('profile_parse.json',{}).get('missing',[])
        display=lambda value:p.expand(value,'operator_check')
    else:
        items=legacy_evidence(root,rep);judgment={};now=date.today().isoformat();due=30;missing=[]
        display=str
    dependencies=dependencies_for(p) if (root/'evidence.json').exists() else {}
    chosen=selected_evidence(items,now,judgment,due,dependencies)
    path=root/'operator_check.md';previous={}
    if path.exists():
        for m in MARKER.finditer(path.read_text()):
            meta=json.loads(m[1]);previous[(meta['id'],meta['fingerprint'])]=m[2]
    out=['# 操控者核查单','', '操控者是交付报告前亲自核查关键信息的人。本单不进入客户报告；未勾选与未填写表示尚未完成，不是已核实。','',f'核查基准：{now}；案例：{case.get("case_id",root.name)}。','']
    for e,reasons in chosen:
        fp=fingerprint(e);marker={'id':e['id'],'fingerprint':fp};old=previous.get((e['id'],fp))
        out.append('<!-- operator-item '+json.dumps(marker,ensure_ascii=False)+' -->')
        if old:out.append(old.rstrip());out.append('');continue
        source=e.get('source',{});claim=display(e.get('operator_prompt',e.get('claim','待核说法')));url=source.get('url') or source.get('locator') or '本人画像与原始材料'
        value=e.get('value');number='；记录值：'+json.dumps(value,ensure_ascii=False) if value is not None else ''
        out.extend([f'- [ ] {e["id"]}｜'+ ' / '.join(reasons),f'  核什么：{claim}{number}；确认适用范围：{display(e.get("scope","待核"))}。',
                    f'  去哪里核：{display(url)}；定位：{display(source.get("locator",e.get("original_locator","相关条款/表行")))}。',
                    '  核完填：核查人：___；核查日期：___；结果（确认/不符/仍未知）：___；原文依据与范围：___；对建议的处理：___。',''])
    for m in missing:
        e={'id':'P-'+m['field'],'claim':m.get('question',m['field']),'source':{'locator':'画像原文'},'scope':'请本人补充，不能由推断替代事实'}
        fp=fingerprint(e);marker={'id':e['id'],'fingerprint':fp};out.append('<!-- operator-item '+json.dumps(marker,ensure_ascii=False)+' -->')
        old=previous.get((e['id'],fp))
        if old:out.extend([old.rstrip(),'']);continue
        out.extend([f'- [ ] {e["id"]}｜本人信息缺项',f'  核什么：{e["claim"]}；影响：{m.get("impact","候选资格或取舍")}。','  去哪里核：请本人核对原画像及本人掌握的材料。','  核完填：核查人：___；核查日期：___；结果（确认/不符/仍未知）：___；原文依据与范围：___；对建议的处理：___。',''])
    destination=Path(output) if output else path
    destination.write_text('\n'.join(out),encoding='utf-8')
    return destination


def validate_operator(root,require_completed=False):
    root=Path(root);p=root/'operator_check.md'
    if not p.exists():return ['operator_check.md：缺操控者核查单']
    text=p.read_text();errors=[];records={json.loads(m[1])['id']:(json.loads(m[1]),m[2]) for m in MARKER.finditer(text)}
    if (root/'evidence.json').exists():
        from planning_workflow import PlanningCase
        c=PlanningCase(root)
        expected=selected_evidence(list(c.evidence.values()),c.case['context']['as_of'],c.data['judgment.json'],c.limits['operator_due_days'],dependencies_for(c))
        for e,reasons in expected:
            if e['id'] not in records or records[e['id']][0]['fingerprint']!=fingerprint(e):errors.append('operator_check.md：漏项/已变更 '+e['id'])
        for missing in c.data['profile_parse.json'].get('missing',[]):
            if 'P-'+missing['field'] not in records:errors.append('operator_check.md：缺本人信息问题 '+missing['field'])
    else:
        for e,_ in selected_evidence(legacy_evidence(root),date.today().isoformat()):
            if e['id'] not in records or records[e['id']][0]['fingerprint']!=fingerprint(e):errors.append('operator_check.md：漏项/已变更 '+e['id'])
    for eid,(_,body) in records.items():
        if any(k not in body for k in ('核什么：','去哪里核：','核完填：')):errors.append('operator_check.md：核查内容不完整 '+eid)
        if require_completed:
            result=re.search(r'结果（确认/不符/仍未知）：([^；\n]+)',body)
            checked=re.search(r'核查日期：(\d{4}-\d{2}-\d{2})',body)
            if '- [x]' not in body.lower() or '___' in body or not result or result[1].strip() not in ('确认','不符') or not checked:errors.append('operator_check.md：尚未完成 '+eid)
            elif checked:
                try:day(checked[1])
                except ValueError:errors.append('operator_check.md：核查日期不合法 '+eid)
    return errors


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('case_dir');args=ap.parse_args();print(generate(args.case_dir))
if __name__=='__main__':main()
