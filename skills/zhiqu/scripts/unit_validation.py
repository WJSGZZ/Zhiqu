#!/usr/bin/env python3
"""Check displayed units against independently declared reference metadata.

Public interfaces: reference_unit(case, kind, path), errors(case, text, location).
A missing unit is an error for numeric references, never inferred from prose.
"""
import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import unicodedata

SKILLS=Path(__file__).resolve().parents[2]
TABLE=json.loads((SKILLS/'zhiqu-shared/references/unit-families.json').read_text())
REF=re.compile(r'\{\{(e|c|k|p):([^{}|]+?)(?:\|([^{}]+))?\}\}')

def _clean(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value))).replace('／','/')

@dataclass(frozen=True)
class Unit:
    family: str
    currency: str=''
    scale: float=1
    period: str=''

ALIASES={_clean(a):Unit(row['family'],row.get('currency',''),row['scale'],row.get('period',''))
         for row in TABLE['units'] for a in row['aliases']}
PERIODS={_clean(k):v for k,v in TABLE['period_aliases'].items()}

def normalize_unit(unit):
    if not unit:return None
    raw=_clean(unit)
    # Per-student tuition and an individual annual tuition have the same displayed unit.
    raw=raw.replace('/生·','/').replace('/人·','/').replace('/生/','/').replace('/人/','/')
    raw=raw.replace('每年','/年').replace('每月','/月')
    if raw in ALIASES:return ALIASES[raw]
    parts=raw.split('/')
    base=ALIASES.get(parts[0],Unit('opaque:'+parts[0]))
    if len(parts)>1:
        base=replace(base,period=PERIODS.get(parts[-1],'opaque:'+parts[-1]))
    return base


def _documents(case):
    if isinstance(case,dict):
        return case.get('case.json',case),case.get('evidence.json',{}),case.get('calculations.json',{})
    return case.case,case.data.get('evidence.json',{}),case.data.get('calculations.json',{})


def reference_unit(case,kind,path):
    """Return declared source unit or None; never inspect surrounding report text."""
    doc,evidence,calculations=_documents(case)
    entries=getattr(case,'evidence',None)
    if entries is None:entries={x['id']:x for x in evidence.get('items',[])}
    if kind=='e':
        eid,_,subpath=path.partition('#')
        # A source's value unit cannot be applied to its date, source ID or other fields.
        if subpath=='/value' and entries.get(eid,{}).get('unit'):
            return entries[eid]['unit']
    explicit=doc.get('reference_units',{}).get(kind+':'+path)
    if explicit:return explicit
    if kind!='c':return None
    plan=doc.get('calculation_plan',{})
    if plan.get('engine')=='registered_operations':
        for op in plan.get('operations',[]):
            if path=='/'+str(op.get('output')) and op.get('unit'):return op['unit']
        for scenario in plan.get('scenarios',[]):
            if (m:=REF.fullmatch(str(scenario.get('output_ref','')))) and m[1]=='c' and m[2]==path:
                for op in plan.get('operations',[]):
                    if op.get('output')==scenario.get('baseline_output') and op.get('unit'):return op['unit']
    if plan.get('engine')=='legacy_demo':
        for rule in TABLE['legacy_demo_output_schema']:
            if re.fullmatch(rule['path_regex'],path):return rule['unit']
    return None


def _value(case,kind,path):
    if hasattr(case,'resolve'):return case.resolve(kind,path)
    from verification_calculations import pointer
    doc,evidence,calculations=_documents(case)
    if kind=='e':
        eid,_,subpath=path.partition('#');entries={x['id']:x for x in evidence.get('items',[])}
        return pointer(entries[eid],subpath)
    return pointer({'k':doc,'c':calculations,'p':case.get('profile_parse.json',{})}[kind],path)


def _numeric(value,fmt):
    if type(value) in (int,float):return True
    if not isinstance(value,str):return False
    if re.fullmatch(r'\d{4}-\d\d-\d\d.*',value):return False
    return bool(re.fullmatch(r'[-+]?\d[\d,.]*(?:%|元)?',_clean(value))) or fmt in ('yuan','arabic')

# 复合单位优先最长匹配；允许斜线两侧排版空白和全角斜线，不截成单个人数。
BASE_PATTERN='|'.join(re.escape(x).replace('/',r'\s*[/／]\s*') for x in sorted((a for a in ALIASES if a not in ('1','无量纲','ratio')),key=len,reverse=True))
PERIOD_PATTERN='|'.join(re.escape(x) for x in sorted(PERIODS,key=len,reverse=True))
SUFFIX=re.compile(r'^\s*[(（]?\s*(?P<base>'+BASE_PATTERN+r')(?P<denom>\s*[/／]\s*(?:(?:生|人)\s*[·/]\s*)?(?:'+PERIOD_PATTERN+r'))?')
PREFIX=re.compile(r'(?P<unit>'+'|'.join(re.escape(x) for x in sorted(set(TABLE['prefix_currency_aliases'])|{'万元','万港元','万美元'},key=len,reverse=True))+r')\s*$')


def _display_units(text,match,embedded_percent=False):
    after=text[match.end():]
    before=text[:match.start()]
    # Do not read through another reference or an intervening number.
    suffix=SUFFIX.match(after)
    prefix=PREFIX.search(before)
    found=[]
    if prefix:found.append((prefix['unit'],normalize_unit(prefix['unit'])))
    if suffix:
        raw=suffix['base']+(suffix['denom'] or '')
        # Avoid interpreting prose such as 分析/分别 as a score suffix.
        rest=after[suffix.end():]
        prose_starts={'分':r'(?:[析别布类开为享歧位]|数(?!学))', '岗':r'位', '条':r'件'}
        if not ((suffix['base'] in prose_starts and re.match(prose_starts[suffix['base']],rest)) or (suffix['base']=='个人' and embedded_percent)):
            actual=normalize_unit(raw)
            # 同一段必须已明确分母，才把‘人’理解为每名额人数；不把普通人数放宽为比率。
            paragraph=before.rsplit('\n\n',1)[-1]
            denominator=re.search(r'每(?:个)?名额(?:缴费人数|报名人数|人数|约|对应|[：:])',paragraph)
            if actual.family=='people' and denominator:
                actual=normalize_unit('人/名额')
            found.append((raw,actual))
    # Explicit temporal framing before a reference is a display assertion, not metadata.
    local=before[max(before.rfind('}}'),before.rfind('。'),before.rfind('；'),before.rfind('\n'),len(before)-24)+1:]
    temporal=list(re.finditer(r'每月|月度|每年|年度',local))
    if temporal:
        p='month' if temporal[-1][0] in ('每月','月度') else 'year'
        found += [(temporal[-1][0],replace(unit,period=p)) for raw,unit in list(found) if unit.family=='money']
    return found


def _compatible(expected,actual):
    # Omitting a source period is allowed; contradicting it is not.
    return (expected.family,expected.currency,expected.scale)==(actual.family,actual.currency,actual.scale) and (not actual.period or actual.period==expected.period)


def errors(case,text,location=''):
    problems=[];text=str(text)
    for match in REF.finditer(text):
        kind,path,fmt=match.groups()
        if kind not in ('k','c','e'):continue
        try:value=_value(case,kind,path)
        except (KeyError,IndexError,ValueError,TypeError):continue  # Existing reference gate owns these.
        if not _numeric(value,fmt):continue
        source=reference_unit(case,kind,path)
        if not source:
            problems.append(f'{location}：单位元数据缺失（missing-unit）：{kind}:{path}')
            continue
        expected=normalize_unit(source)
        # Registered percent formatting explicitly multiplies a ratio by 100.
        if fmt in ('percent0','percent1'):
            if expected.family!='ratio' or expected.scale!=1:
                problems.append(f'{location}：单位不一致：{kind}:{path} 的百分比格式要求真实单位为比率')
            expected=Unit('ratio',scale=.01)
        for raw,actual in _display_units(text,match,fmt in ('percent0','percent1') or (isinstance(value,str) and _clean(value).endswith('%'))):
            if not _compatible(expected,actual):
                problems.append(f'{location}：单位不一致：{kind}:{path} 真实单位“{source}”，显示单位“{raw}”')
    return problems


def preflight(root,output):
    from planning_workflow import PlanningCase,walk
    results=[]
    for skill in ('zhiqu-grad','zhiqu-career'):
        for path in sorted((root/'skills'/skill/'examples').glob('*/case.json')):
            case=PlanningCase(path.parent);missing={};mismatches=[]
            for file,data in case.data.items():
                if file not in ('narrative.json','judgment.json','candidates.json','directions.json'):continue
                for location,value in walk(data):
                    if not isinstance(value,str):continue
                    for match in REF.finditer(value):
                        kind,pointer,fmt=match.groups()
                        if kind not in ('k','c','e'):continue
                        try:actual=_value(case,kind,pointer)
                        except (KeyError,IndexError,TypeError,ValueError):continue
                        if _numeric(actual,fmt) and not reference_unit(case,kind,pointer):
                            key=kind+':'+pointer
                            item=missing.setdefault(key,{'reference':key,'value':actual,'locations':[],'unit':None,'status':'missing-unit; requires semantic review'})
                            item['locations'].append(file+location)
                    mismatches.extend(x for x in errors(case,value,file+location) if '单位不一致' in x)
            results.append({'case':str(path.parent.relative_to(root)),'missing_units':list(missing.values()),'display_mismatches':mismatches})
    for directory in sorted((root/'skills/zhiqu/examples').glob('*')):
        if not directory.is_dir():continue
        references=[]
        for file in directory.glob('*.json'):
            try:data=json.loads(file.read_text())
            except (OSError,ValueError):continue
            for location,value in walk(data):
                if isinstance(value,str):
                    references.extend({'file':file.name,'location':location,'reference':m[0]} for m in REF.finditer(value))
        results.append({'case':str(directory.relative_to(root)),'missing_units':[],
                        'display_mismatches':[], 'planning_references':references,
                        'status':'gaokao report engine; any planning references require separate review' if references else 'no planning unit references'})
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'source_units_inferred_from_display':False,'cases':results,'missing_reference_count':sum(len(x['missing_units']) for x in results)}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preflight',type=Path,required=True);a=p.parse_args()
    r=preflight(SKILLS.parent,a.preflight)
    print(json.dumps({'cases':len(r['cases']),'missing_reference_count':r['missing_reference_count'],'output':str(a.preflight)},ensure_ascii=False))
