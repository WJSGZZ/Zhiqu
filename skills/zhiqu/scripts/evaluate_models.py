#!/usr/bin/env python3
"""年度校准与固定厚尾候选的滚动验证（标准库）。

训练目标年 < --holdout；选择波动倍数后冻结，在留出年比较概率损失 NLL 和区间误差。
不会改生产预测参数。专业组号匹配结果为 exploratory，不能作为正式启用证据。
重复检验已揭盲年份不能重新称为独立留出；保留配置/分组以便复核。
"""
import argparse
import csv
import math
import os
import statistics as st
import sys

import backtest as bt
from optimize import model_parameters

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
SERIES = {
    'zhejiang': ('general', 'major', 'code'),
    'hebei': ('physics', 'major', 'name'),
    'shandong': ('general', 'major', 'code'),
    'liaoning': ('physics', 'major', 'code'),
    'guangdong': ('physics', 'group', 'code'),
    'jiangsu': ('physics', 'group', 'code'),
    'hunan': ('physics', 'group', 'code'),
    'hubei': ('physics', 'group', 'code'),
    'shanghai': ('general', 'group', 'code'),
    'heilongjiang': ('physics', 'group', 'code'),
}
SCALES = (0.7, 0.9, 1.0, 1.3, 1.7, 2.0)
# 在看留出结果前固定；禁止按留出表现再更改。
MIX_WEIGHT, MIX_SPREAD = 0.10, 3.0


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def score(errors, scale, distribution):
    pits, losses = [], []
    for residual, sigma in errors:
        z = residual / (sigma * scale)
        if distribution == 'normal':
            pit = phi(z)
            log_density = -0.5 * z*z - math.log(sigma * scale * math.sqrt(2 * math.pi))
        else:
            pit = (1-MIX_WEIGHT)*phi(z) + MIX_WEIGHT*phi(z/MIX_SPREAD)
            a = math.log(1-MIX_WEIGHT) - 0.5*z*z
            b = math.log(MIX_WEIGHT/MIX_SPREAD) - 0.5*(z/MIX_SPREAD)**2
            m = max(a, b)
            log_density = m + math.log(math.exp(a-m)+math.exp(b-m)) - math.log(sigma*scale*math.sqrt(2*math.pi))
        pits.append(pit)
        losses.append(-log_density)
    if not pits:
        return {}
    coverage = [sum((1-p)/2 <= u <= (1+p)/2 for u in pits)/len(pits) for p in (.5,.8,.9)]
    return dict(n=len(pits), nll=st.mean(losses), calibration_error=st.mean(abs(c-p) for c,p in zip(coverage,(.5,.8,.9))),
                coverage_80=coverage[1], hot_tail_05=sum(u < .05 for u in pits)/len(pits))


def load_series(province):
    stem, key, school = SERIES[province]
    bt.SCHOOL_BY, bt.METRIC = school, 'rank'
    data = {}
    for name in sorted(os.listdir(os.path.join(DATA, province))):
        if not name.startswith(stem+'_') or not name.endswith('.csv'):
            continue
        year = name[len(stem)+1:-4]
        if not year.isdigit():
            continue
        data[int(year)] = {k:v for k,v in bt.load(os.path.join(DATA, province, name), key).items()
                           if v['full'] and v['rank'] and v['rank'] >= 500}
    return data


def yearly_errors(data):
    years = sorted(data)
    steps = {}
    for a,b in zip(years,years[1:]):
        ds = [math.log(data[b][k]['rank']/data[a][k]['rank'])/(b-a) for k in data[a].keys() & data[b].keys()]
        if ds:
            steps[b] = st.median(ds)
    out = {}
    for target in years[1:]:
        prev = [y for y in years if y < target]
        known_steps = [steps[y] for y in prev if y in steps][-3:]
        drift = st.mean(known_steps) if known_steps else 0.0
        errors = []
        for k,v in data[target].items():
            hist = [data[y][k]['rank']*math.exp(drift*(target-y)) if k in data[y] else None for y in prev[::-1]]
            if not any(hist):
                continue
            mu, sigma, _ = model_parameters(hist)
            errors.append((math.log(v['rank'])-mu, sigma))
        out[target] = (drift, errors)
    return out


def review(province, holdout):
    data = load_series(province)
    yearly = yearly_errors(data)
    training = [e for y,(_,es) in yearly.items() if y < holdout for e in es]
    rows = []
    status = 'major_name' if SERIES[province][1] == 'major' else 'group_number_exploratory'
    if not training:
        return [dict(province=province, target_year=holdout, split='unavailable', matching_status=status, note='无可用训练位次，不调参')]
    fitted = {d:min(SCALES,key=lambda s:score(training,s,d)['nll']) for d in ('normal','mixture')}
    for target,(drift,errors) in yearly.items():
        if target > holdout or not errors:
            continue
        prior_errors = [e for y,(_,es) in yearly.items() if y < target for e in es]
        for d in ('normal','mixture'):
            scale = fitted[d] if target == holdout else (min(SCALES,key=lambda s:score(prior_errors,s,d)['nll']) if prior_errors else 1.0)
            rows.append(dict(province=province, target_year=target, split='retrospective_holdout' if target==holdout else 'rolling_history',
                             matching_status=status, distribution=d, sigma_scale=scale, drift=drift,
                             **score(errors,scale,d), note='固定混合10%×3；仅用目标年前误差选参，无先前误差用1；研究输出，不改生产默认'))
    hold = {r['distribution']:r for r in rows if r['split']=='retrospective_holdout'}
    if len(hold)==2:
        improves = hold['mixture']['nll'] < hold['normal']['nll'] and hold['mixture']['calibration_error'] < hold['normal']['calibration_error']
        for r in rows:
            r['holdout_improves_both'] = int(improves) if r['target_year']==holdout else ''
    return rows


def review_rho(out):
    rows=[]
    for province in ('zhejiang','hebei','shandong'):
        data=load_series(province);years=sorted(data);steps=[]
        for a,b in zip(years,years[1:]):
            change=[math.log(data[b][k]['rank']/data[a][k]['rank'])/(b-a) for k in data[a].keys() & data[b].keys()]
            if change: steps.append((b,st.median(change),st.pvariance(change)))
        for target in years[2:]:
            known=[s for s in steps if s[0]<target]
            common=st.variance(x[1] for x in known) if len(known)>1 else None
            within=st.mean(x[2] for x in known) if known else None
            rho=common/(common+within) if common is not None and common+within>0 else None
            rows.append(dict(province=province,target_year=target,n_prior_transitions=len(known),
                             common_variance='' if common is None else common,within_variance='' if within is None else within,
                             rho_estimate='' if rho is None else rho,
                             status='样本少；仅描述估计，不替代rho敏感性；未验证组合风险'))
    with open(out,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n");w.writeheader();w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--holdout',type=int,default=2026)
    ap.add_argument('--province',action='append',choices=sorted(SERIES))
    ap.add_argument('--out',required=True)
    ap.add_argument('--rho-out',help='三个专业匹配省份的年度共同波动描述估计CSV，不自动改变rho')
    a = ap.parse_args()
    rows = [r for p in a.province or SERIES for r in review(p,a.holdout)]
    fields = ['province','target_year','split','matching_status','distribution','sigma_scale','drift','n','nll',
              'calibration_error','coverage_80','hot_tail_05','holdout_improves_both','note']
    with open(a.out,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(rows)
    if a.rho_out: review_rho(a.rho_out)
    for r in rows:
        if r['split'] in ('holdout','unavailable'):
            print(r['province'],r.get('distribution','不可用'), 'n='+str(r.get('n',0)),
                  'NLL='+str(round(r.get('nll',0),4)), '区间误差='+str(round(r.get('calibration_error',0),4)),
                  r['matching_status'])


if __name__ == '__main__':
    main()
