#!/usr/bin/env python3
"""确认偏好与固定锚点计分；支持考生/家长场景和二选一检查，不改问卷。

输入 CSV: id,name,school_score,major_score,city_score,outlook_score,历年位次等。
config JSON: scenarios（每种 priority、anchors.low/high 及可选 checks），选择 --scenario。
锚点由本人确认，不能根据候选池极值生成；未知属性不自动补分。
"""
import argparse
import csv
import json
import math
import re

ATTRS = ('school', 'major', 'city', 'outlook')


def weights(priority, attrs=ATTRS):
    order = [x for x in priority if x != 'safety']
    if len(order) != len(attrs) or set(order) != set(attrs):
        raise ValueError('priority 必须各含已定义属性一次，可另含 safety')
    return {name: sum(1/j for j in range(i+1,len(order)+1))/len(order) for i,name in enumerate(order)}


def raw_score(scores, w):
    try:
        vals = {a:float(scores[a]) for a in w}
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError('属性未知，先调查或确认，不能自动填分') from exc
    if any(not math.isfinite(v) or not 0 <= v <= 10 for v in vals.values()):
        raise ValueError('属性分必须为 0–10 的有限数字；未知时先调查，不自动填分')
    return 10*sum(w[a]*vals[a] for a in w)


def has_cycle(edges):
    visiting, done = set(), set()
    def visit(node):
        if node in visiting: return True
        if node in done: return False
        visiting.add(node)
        if any(visit(n) for n in edges.get(node, ())): return True
        visiting.remove(node); done.add(node)
        return False
    return any(visit(n) for n in edges)


def evaluate(rows, config, scenario):
    spec = config['scenarios'][scenario]
    if spec.get('confirmed') is not True:
        raise ValueError('每个场景的排序与锚点必须由当事人确认（confirmed=true）')
    attrs = tuple(config.get('attributes', ATTRS))
    if len(attrs) < 2 or len(set(attrs)) != len(attrs) or any(not isinstance(a,str) or not re.fullmatch('[a-z][a-z0-9_]*',a) or a=='safety' for a in attrs):
        raise ValueError('attributes 须为至少两个不同属性标识，safety 另作风险约束')
    w = weights(spec['priority'], attrs)
    lo, hi = [raw_score(spec['anchors'][a]['scores'],w) for a in ('low','high')]
    if hi <= lo:
        raise ValueError('梦校锚点效用必须高于底线锚点；先澄清两者，不反转或夹断')
    lookup, output = {}, []
    for r in rows:
        identifier = r.get('id')
        if not identifier or identifier in lookup:
            raise ValueError('候选 id 必须非空且唯一')
        raw = raw_score({a:r[a+'_score'] for a in attrs},w)
        u = 100*(raw-lo)/(hi-lo)
        row=dict(r,utility=round(u,6),utility_scenario=scenario)
        output.append(row);lookup[identifier]=row
    warnings, edges = [], {}
    for check in spec.get('checks',[]):
        a,b,choice = check['a'],check['b'],check['choice']
        if a not in lookup or b not in lookup or a==b or choice not in (a,b,'tie'):
            raise ValueError('二选一核对必须引用两个不同且存在的 id，choice 为其中一个 id 或 tie')
        ua,ub = lookup[a]['utility'],lookup[b]['utility']
        predicted = 'tie' if math.isclose(ua,ub,abs_tol=1e-6) else (a if ua>ub else b)
        if predicted != choice:
            warnings.append(dict(a=a,b=b,choice=choice,predicted=predicted,
                                 reason='本人选择与当前权重/属性评分不一致，询问条件或修正评分，不能自动替本人改选择'))
        if choice!='tie':
            edges.setdefault(choice,set()).add(b if choice==a else a)
    if has_cycle(edges):
        warnings.append(dict(reason='二选一出现偏好循环，先确认问题情境是否一致；不强行自动求一套权重'))
    pairs=[]
    for i,a in enumerate(output):
        for b in output[i+1:]:
            diffs=[float(a[k+'_score'])-float(b[k+'_score']) for k in attrs]
            if any(d>0 for d in diffs) and any(d<0 for d in diffs):
                pairs.append((abs(a['utility']-b['utility']),a['id'],b['id']))
    return output, dict(scenario=scenario,weights=w,anchors=spec['anchors'],warnings=warnings,
                        suggested_pairs=[dict(a=a,b=b) for _,a,b in sorted(pairs)[:3]],
                        note='两套场景各用自己的锚点和风险参数，数值不作人际满意度比较；超出锚点的效用不夹断')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('csv');ap.add_argument('--config',required=True);ap.add_argument('--scenario',default='student')
    ap.add_argument('--out',required=True);ap.add_argument('--review',required=True)
    a=ap.parse_args()
    try:
        with open(a.csv,encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
        with open(a.config,encoding='utf-8') as f: config=json.load(f)
        output,review=evaluate(rows,config,a.scenario)
    except (KeyError,ValueError) as exc:
        ap.error(str(exc))
    fields=list(rows[0]) if rows else ['id','name']
    fields += [k for k in ('utility','utility_scenario') if k not in fields]
    with open(a.out,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(output)
    with open(a.review,'w',encoding='utf-8') as f: json.dump(review,f,ensure_ascii=False,indent=2)
    print(f'{a.scenario}: {len(output)} 个候选，{len(review["warnings"])} 个偏好待确认；输出 {a.out}')


if __name__=='__main__': main()
