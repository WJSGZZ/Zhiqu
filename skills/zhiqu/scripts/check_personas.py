#!/usr/bin/env python3
"""Check the reusable simulated profiles and their declared workflow depth.

Run after changing planning rules/tools. --extract refreshes only derived
profile.txt files from the canonical questionnaire answers; it never renders
reports or signs an operator/independent review.
"""
import argparse
import json
import re
from pathlib import Path
from planning_workflow import PlanningCase, SKILLS

LIBRARY=SKILLS/'zhiqu-shared/references/sim-personas.md'
# Scope is explicit so that stopping an early case cannot hide a failed report.
CASES=(('grad','2028-YJ-S02',10),('grad','2027-YJ-S03',4),('grad','2027-YJ-S04',4),
       ('career','2027-QZ-S02',10),('career','2027-QZ-S03',4),('career','2027-QZ-S04',4))


def profiles(text):
    result={}
    for match in re.finditer(r'^## (\d{4}-(YJ|QZ)-S\d{2}) · ([^\n]+)（模拟）\n(.*?)(?=^## \d{4}-|\Z)',text,re.M|re.S):
        cid,code,name,body=match.groups()
        if cid in result:raise ValueError('人物编号重复：'+cid)
        if '### 问卷回答\n' not in body or '### 阶段产物' not in body:raise ValueError('人物缺回答或产物入口：'+cid)
        answers=body.split('### 问卷回答\n',1)[1].split('### 阶段产物',1)[0].strip()
        header='【读研 · 自我盘点】' if code=='YJ' else '【求职 · 自我盘点】'
        result[cid]=header+'\n人物：'+name+'（模拟）\n\n'+answers+'\n'
    return result


def check(root=SKILLS,library=LIBRARY,extract=False):
    root=Path(root);errors=[]
    try:canonical=profiles(Path(library).read_text())
    except (OSError,ValueError) as exc:return [str(exc)]
    expected={cid for _,cid,_ in CASES}
    if set(canonical)!=expected:errors.append('人物库编号与声明的回归范围不一致')
    for kind,cid,stage in CASES:
        path=root/f'zhiqu-{kind}/examples'/cid
        if not path.is_dir():errors.append(cid+'：缺目录');continue
        profile=path/'profile.txt'
        if extract and cid in canonical:profile.write_text(canonical[cid])
        if not profile.exists() or profile.read_text()!=canonical.get(cid):errors.append(cid+'：画像与人物库不同步')
        questionnaire=root.parent/f'{kind}.html'
        sections=re.findall(r'data-title="([^"]+)"',questionnaire.read_text())
        actual=re.findall(r'^#### (.+)$',canonical.get(cid,''),re.M)
        if actual!=sections:errors.append(cid+'：回答节名或次序与问卷不同步')
        try:
            case=PlanningCase(path);errors.extend(cid+'：'+e for e in case.check(stage))
            if case.case.get('mode')!='simulation':errors.append(cid+'：必须明确为模拟')
            if stage==4:
                for f in ('calculations.json','judgment.json','narrative.json','report.md','report.html','report.pdf','review.json','operator_check.md'):
                    if (path/f).exists():errors.append(cid+'：前半程人物出现超出范围的产物 '+f)
            else:
                review=json.loads((path/'review.json').read_text())
                if review.get('status')!='awaiting_independent_review' or review.get('independent') is not False:errors.append(cid+'：不能冒充独立审核通过')
        except (OSError,KeyError,ValueError,TypeError) as exc:errors.append(cid+'：'+str(exc))
    return errors


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--extract',action='store_true');args=p.parse_args()
    errors=check(extract=args.extract)
    if errors:
        for e in errors:print(e)
        raise SystemExit(1)
    print('模拟人物回归通过：两份完整流程，四份仅阶段 0—4；画像与问卷节名一致。')
if __name__=='__main__':main()
