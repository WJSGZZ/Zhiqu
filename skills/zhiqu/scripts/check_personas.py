#!/usr/bin/env python3
"""Check reusable simulated JSON profiles and their declared workflow depth.

The library contains persona metadata and links. Questionnaire answers live in
profile.json; oral context lives in profile-supplement.txt. This command never
rewrites either source, renders reports, or signs an independent review.
"""
import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from planning_workflow import PlanningCase, SKILLS

LIBRARY=SKILLS/'zhiqu-shared/references/sim-personas.md'
CASES=(('grad','2028-YJ-S02',10),('grad','2027-YJ-S03',4),('grad','2027-YJ-S04',4),
       ('career','2027-QZ-S02',10),('career','2027-QZ-S03',4),('career','2027-QZ-S04',4),
       ('career','2027-QZ-S05',10),('grad','2027-YJ-S05',10))


def profiles(text):
    """Return each persona's two canonical source links, rejecting duplicates."""
    result={}
    for match in re.finditer(r'^## (\d{4}-(YJ|QZ)-S\d{2}) · ([^\n]+)（模拟）\n(.*?)(?=^## \d{4}-|\Z)',text,re.M|re.S):
        cid,code,name,body=match.groups()
        if cid in result:raise ValueError('人物编号重复：'+cid)
        if '### 问卷回答' in body:raise ValueError('人物库重复维护问卷回答：'+cid)
        links={Path(link).name:link for link in re.findall(r'\]\(([^)]+)\)',body)}
        if not all(f in links for f in ('profile.json','profile-supplement.txt')):
            raise ValueError('人物缺 JSON 画像或口语补充入口：'+cid)
        result[cid]={'kind':'grad' if code=='YJ' else 'career','name':name,
                     'profile':links['profile.json'],'supplement':links['profile-supplement.txt']}
    return result


class QuestionParser(HTMLParser):
    """Read public question IDs, visible wording and sections without a browser."""
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self):
        super().__init__();self.stack=[];self.questions={};self.label_depth=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in self.VOID:return
        self.stack.append((tag,attrs))
        qid=attrs.get('data-profile-id')
        if qid:
            if qid in self.questions:raise ValueError('问卷题号重复：'+qid)
            section=next((a.get('data-title') for _,a in reversed(self.stack) if 'section' in a.get('class','').split()),None)
            self.questions[qid]={'section':section,'q':''}
        if 'q-label' in attrs.get('class','').split():self.label_depth=len(self.stack)
    def handle_endtag(self,tag):
        if self.label_depth==len(self.stack):self.label_depth=None
        if self.stack and self.stack[-1][0]==tag:self.stack.pop()
    def handle_data(self,data):
        if self.label_depth is None:return
        qid=next((a.get('data-profile-id') for _,a in reversed(self.stack) if a.get('data-profile-id')),None)
        if qid:self.questions[qid]['q']+=data


def questionnaire_questions(path):
    parser=QuestionParser();parser.feed(Path(path).read_text())
    for q in parser.questions.values():q['q']=re.sub(r'\s+',' ',q['q']).strip()
    return parser.questions


def profile_errors(data,questions,kind):
    errors=[]
    if not isinstance(data,dict):return ['画像须为 JSON 对象']
    if data.get('schema')!=1 or data.get('zhiqu')!=kind:errors.append('须使用对应路线的 schema=1 JSON 画像')
    if not re.fullmatch(r'[0-9a-f]{8}',str(data.get('form',''))):errors.append('form 须为八位十六进制题目指纹')
    try:
        from datetime import datetime
        if datetime.fromisoformat(data['filled_at']).tzinfo is None:raise ValueError()
    except (KeyError,TypeError,ValueError):errors.append('filled_at 须为含时区的填写时间')
    if not isinstance(data.get('sections'),list):return errors+['sections 须为数组']
    seen=set()
    for section in data['sections']:
        if not isinstance(section,dict) or not isinstance(section.get('items'),list):errors.append('章节缺 items 数组');continue
        for item in section['items']:
            if not isinstance(item,dict):errors.append('作答须为对象');continue
            qid=item.get('id');q=questions.get(qid)
            if not q:errors.append('未知题号：'+str(qid));continue
            if qid in seen:errors.append('重复作答：'+qid)
            seen.add(qid)
            if item.get('q')!=q['q']:errors.append(qid+'：题干与问卷原文不同')
            if section.get('title')!=q['section']:errors.append(qid+'：章节与问卷不同')
            if item.get('a') in (None,'',[],{}):errors.append(qid+'：空作答应记缺项')
    for section in data['sections']:
        if not isinstance(section,dict) or not isinstance(section.get('items'),list):continue
        for item in section['items']:
            if isinstance(item,dict) and item.get('followup_of') and item['followup_of'] not in seen:
                errors.append(str(item.get('id'))+'：追问指向未作答的题目')
    missing=data.get('未填的必答题')
    if not isinstance(missing,list) or any(not isinstance(q,str) or q not in {x['q'] for x in questions.values()} for q in missing):
        errors.append('未填的必答题须列问卷原题')
    if not isinstance(data.get('rank'),list) or not isinstance(data.get('derived'),dict):errors.append('rank/derived 类型错误')
    return errors


def check(root=SKILLS,library=LIBRARY):
    root=Path(root);library=Path(library);errors=[]
    try:canonical=profiles(library.read_text())
    except (OSError,ValueError) as exc:return [str(exc)]
    expected={cid for _,cid,_ in CASES}
    if set(canonical)!=expected:errors.append('人物库编号与声明的回归范围不一致')
    schemas={kind:questionnaire_questions(root.parent/(kind+'.html')) for kind in ('grad','career')}
    for kind,cid,stage in CASES:
        path=root/f'zhiqu-{kind}/examples'/cid
        if not path.is_dir():errors.append(cid+'：缺目录');continue
        if cid not in canonical:continue
        record=canonical[cid]
        for key,filename in (('profile','profile.json'),('supplement','profile-supplement.txt')):
            if (library.parent/record[key]).resolve()!=(path/filename).resolve():errors.append(cid+'：'+key+' 链接未指向本案例')
        try:
            data=json.loads((path/'profile.json').read_text())
            errors.extend(cid+'：'+e for e in profile_errors(data,schemas[kind],kind))
            supplement=(path/'profile-supplement.txt').read_text()
            if not supplement.startswith('问卷之外的补充（模拟）\n'):errors.append(cid+'：补充须明确为问卷之外的模拟说明')
            # Legacy prose remains byte-for-byte until all old consumers migrate.
            legacy=path/'profile.txt'
            if legacy.exists() and not supplement.endswith(legacy.read_text()):errors.append(cid+'：原口语说明未完整保留')
            case=PlanningCase(path);errors.extend(cid+'：'+e for e in case.check(stage))
            if case.case.get('mode')!='simulation':errors.append(cid+'：必须明确为模拟')
            if stage==4:
                for f in ('calculations.json','judgment.json','narrative.json','report.md','report.html',cid+'-report.pdf','review.json','operator_check.md'):
                    if (path/f).exists():errors.append(cid+'：前半程人物出现超出范围的产物 '+f)
            else:
                review=json.loads((path/'review.json').read_text())
                approved=review.get('status')=='approved' and review.get('independent') is True and review.get('reviewer') and review.get('date')
                waiting=review.get('status') in ('awaiting_independent_review','changes_required') and review.get('independent') is not True
                if not (approved or waiting):errors.append(cid+'：不能冒充独立审核通过')
        except (OSError,KeyError,ValueError,TypeError) as exc:errors.append(cid+'：'+str(exc))
    return errors


def main():
    p=argparse.ArgumentParser(description=__doc__);p.parse_args()
    errors=check()
    if errors:
        for e in errors:print(e)
        raise SystemExit(1)
    print('模拟人物回归通过：四份完整流程，四份仅阶段 0—4；JSON 画像与问卷题号、题干和节名一致。')
if __name__=='__main__':main()
