#!/usr/bin/env python3
"""Reproducible retrospective research, never production calibration.

2026 has already been unblinded. Use official processed CSVs, with separate
province series; selection uses only earlier years. Missing target observations
make a landing unknown, not a rejection. Synthetic utility is not a person.
"""
import argparse
import csv
import math
import random
import statistics as st
from pathlib import Path

import evaluate_models as models
import optimize as opt

PROVINCES = ('zhejiang', 'hebei', 'shandong')
SEED = 20261001


def probability(row, rank, mixture=False):
    z = (row['mu'] - math.log(rank)) / row['sigma']
    return .9 * models.phi(z) + .1 * models.phi(z / 3) if mixture else models.phi(z)


def historical_rows(data, target):
    years = sorted(y for y in data if y < target)
    if len(years) < 2:
        raise ValueError('at least two pre-target years required')
    steps = []
    for a, b in zip(years, years[1:]):
        ds = [math.log(data[b][k]['rank'] / data[a][k]['rank']) / (b-a)
              for k in data[a].keys() & data[b].keys()]
        if ds:
            steps.append(st.median(ds))
    drift = st.mean(steps[-3:]) if steps else 0
    rows = []
    for key, value in sorted(data[years[-1]].items()):
        history = [data[y][key]['rank'] * math.exp(drift*(target-y))
                   if key in data[y] else None for y in years[::-1]]
        if sum(x is not None for x in history) < 2:
            continue
        mu, sigma, _ = opt.model_parameters(history)
        # Fixed anchors independent of the pool and target-year results.
        utility = 100 * max(0, min(1, math.log(300000/value['rank']) / math.log(300000/500)))
        rows.append(dict(key=key, name=value['name'], latest=value['rank'], mu=mu,
                         sigma=sigma, u=utility, ua=0, majors=[], p_adj=0))
    return rows


def mechanical(rows, rank, safe=False):
    probs = [probability(r, rank) for r in rows]
    if safe:
        return sorted(range(len(rows)), key=lambda j: (-probs[j], j))[:10]
    selected = []
    for lo, hi, n, center in ((.05, .4, 3, .225), (.4, .8, 4, .6), (.8, 1.01, 3, .9)):
        members = [j for j, p in enumerate(probs) if lo <= p < hi and j not in selected]
        selected.extend(sorted(members, key=lambda j: (-rows[j]['u'], j))[:n])
        if len(members) < n:
            fill = sorted((j for j in range(len(rows)) if j not in selected),
                          key=lambda j: (abs(probs[j]-center), j))
            selected.extend(fill[:n-len(members)])
    return selected


def landing(rows, selected, observations, rank):
    """An unobserved earlier preference prevents knowing the first landing."""
    for position, j in enumerate(selected, 1):
        actual = observations.get(rows[j]['key'])
        if actual is None:
            return None, None, None
        if rank <= actual['rank']:
            return 0, rows[j]['u'], position
    return 1, 0, 0


def portfolio_review(province, data, target):
    rows = historical_rows(data, target)
    out, tails = [], []
    ranks = sorted(r['latest'] for r in rows)
    for quantile in (.2, .35, .5, .65, .8):
        rank = ranks[int((len(ranks)-1)*quantile)]
        eligible = sorted((r for r in rows if .5 <= r['latest']/rank <= 3),
                          key=lambda r: (r['latest'], r['key']))
        size = min(40, len(eligible))
        pool = [eligible[round(i*(len(eligible)-1)/(size-1))] for i in range(size)] if size > 1 else eligible
        for rho in (.1, .5):
            admit, adjust, masks = opt.simulate(pool, rank, 0, rho, 3000, SEED)
            ev = opt.Evaluator(pool, admit, adjust, masks, 3000, 0, .05, 4000)
            sa, sd, sm = opt.simulate(pool, rank, 0, rho, 3000, SEED, 1.5)
            stress = opt.Evaluator(pool, sa, sd, sm, 3000, 0, .05, 4000)
            selected = opt.greedy(ev, len(pool), 10, 4000)
            selected = ev.order(opt.fill_under_stress(ev, stress, selected, len(pool), 10))
            for method, choice in (('optimized', selected),
                                   ('mechanical_343', ev.order(mechanical(pool, rank))),
                                   ('all_safe', ev.order(mechanical(pool, rank, True)))):
                fall, utility, pos = landing(pool, choice, data.get(target, {}), rank)
                remaining, redundant = ev.full, 0
                for j in choice:
                    if not remaining & admit[j]:
                        redundant += 1
                    remaining &= ~admit[j]
                eu, risk, _ = ev.evaluate(choice)
                out.append(dict(province=province, target_year=target, quantile=quantile,
                                virtual_rank=rank, rho=rho, method=method, slots=len(choice),
                                observable=int(fall is not None), actual_fall=fall,
                                realized_synthetic_utility=utility, landing_position=pos,
                                simulated_redundant_slots=redundant, predicted_utility=eu,
                                predicted_fall=risk, scope='retrospective_synthetic_projection_only'))
        # Same observations for both distributions; do not select on future lines.
        for distribution in ('normal', 'mixture'):
            pairs = [(probability(r, rank, distribution == 'mixture'),
                      int(rank <= data[target][r['key']]['rank']))
                     for r in pool if r['key'] in data.get(target, {})]
            low = [(p, y) for p, y in pairs if .05 <= p <= .2]
            tails.append(dict(province=province, target_year=target, quantile=quantile,
                              distribution=distribution, n=len(pairs), low_n=len(low),
                              low_predicted=st.mean(p for p, y in low) if low else None,
                              low_observed=st.mean(y for p, y in low) if low else None,
                              brier=st.mean((p-y)**2 for p, y in pairs) if pairs else None,
                              scope='retrospective_repeated_schools_not_independent_trials'))
    return out, tails


def category(name):
    if '师范' in name:
        return 'teacher'
    if any(word in name for word in ('医科', '医学院', '医药', '中医')):
        return 'medical'
    return 'other'


def variance_components(values, labels):
    groups = {label: [v for v, lab in zip(values, labels) if lab == label] for label in set(labels)}
    n, k = len(values), len(groups)
    if k < 2 or n <= k:
        return 0, 0
    mean = st.mean(values)
    between = sum(len(g)*(st.mean(g)-mean)**2 for g in groups.values()) / (k-1)
    within_sum = 0
    for group in groups.values():
        center = st.mean(group)
        within_sum += sum((v-center)**2 for v in group)
    within = within_sum / (n-k)
    effective_n = (n-sum(len(g)**2 for g in groups.values())/n) / (k-1)
    common = max(0, (between-within)/effective_n)
    ratio = common/(common+within) if common+within else 0
    return ratio, between/within if within else 0


def resonance_review(province, data, target):
    schools, names = {}, {}
    for r in historical_rows(data, target):
        actual = data.get(target, {}).get(r['key'])
        if actual is not None:
            schools.setdefault(r['key'][0], []).append(math.log(actual['rank'])-r['mu'])
            names[r['key'][0]] = r['name']
    keys = sorted(schools)
    values = [st.mean(schools[k]) for k in keys]
    labels = [category(names[k]) for k in keys]
    if not values:
        return dict(province=province, target_year=target, n_schools=0,
                    n_teacher=0, n_medical=0, teacher_centered_residual=None,
                    medical_centered_residual=None, category_variance_ratio=None,
                    permutation_p=None, scope='unavailable_target_observations')
    ratio, statistic = variance_components(values, labels)
    rng = random.Random(SEED)
    shuffled = labels[:]
    extreme = 0
    for _ in range(200):
        rng.shuffle(shuffled)
        extreme += variance_components(values, shuffled)[1] >= statistic
    center = st.mean(values)
    means = {label: st.mean(v for v, lab in zip(values, labels) if lab == label)-center
             for label in set(labels)}
    return dict(province=province, target_year=target, n_schools=len(keys),
                n_teacher=labels.count('teacher'), n_medical=labels.count('medical'),
                teacher_centered_residual=means.get('teacher'), medical_centered_residual=means.get('medical'),
                category_variance_ratio=ratio, permutation_p=(extreme+1)/201,
                scope='retrospective_school_name_proxy_not_causal')


def bh(p_values):
    ordered = sorted(range(len(p_values)), key=lambda i: p_values[i])
    qs, running = [1.] * len(p_values), 1.
    for rank in range(len(ordered), 0, -1):
        i = ordered[rank-1]
        running = min(running, p_values[i]*len(ordered)/rank)
        qs[i] = running
    return qs


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-year', type=int, default=2026)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    portfolios, tails, resonance = [], [], []
    for province in PROVINCES:
        data = models.load_series(province)
        p, t = portfolio_review(province, data, args.target_year)
        portfolios.extend(p)
        tails.extend(t)
        resonance.append(resonance_review(province, data, args.target_year))
    available = [r for r in resonance if r['permutation_p'] is not None]
    for row in resonance:
        row['bh_q'] = None
    for row, q in zip(available, bh([r['permutation_p'] for r in available])):
        row['bh_q'] = q
    write_csv(args.out_dir / f'portfolio_review_{args.target_year}.csv', portfolios)
    write_csv(args.out_dir / f'category_review_{args.target_year}.csv', resonance)
    write_csv(args.out_dir / f'tail_review_{args.target_year}.csv', tails)
    print(f'{len(portfolios)} portfolio scenarios, {len(resonance)} province category tests, {len(tails)} tail scenarios; research only')


if __name__ == '__main__':
    main()
