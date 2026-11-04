#!/usr/bin/env python3
"""没有软科名次的学校（中外合办、新校）按录取位次换算等效名次。

做法：同一省同一年同一科类，找录取位次在目标校 ±WINDOW 以内、有软科名次的学校，
取它们软科名次的中位数；再对各省年取中位数并报范围。世界等效取软科名次相近的内地学校
在 ARWU 中的名次中位数。结果是“考生用分数投票”的位置，不是教学或研究质量。

用法：
  python3 school_equivalence.py 宁波诺丁汉大学 [西交利物浦大学 ...] [--json]
  python3 school_equivalence.py --coop          # 教育部名单里全部合作办学本科
  python3 school_equivalence.py --validate      # 用有名次的学校留一检验误差
"""
from pathlib import Path
import argparse, csv, json, math, re, statistics as st
from collections import defaultdict

DATA = Path(__file__).resolve().parents[1] / 'data'
YEARS = range(2023, 2027)
WINDOW = 1.2          # 位次相差在 1/1.2—1.2 倍以内算“相近”
MIN_NEIGHBORS = 5
MIN_REFS = 80         # 一个省年至少要有这么多有名次的学校才用


def norm(name):
    return re.sub(r'\s+', '', name.replace('（', '(').replace('）', ')'))


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def bcur_ranks(path=None):
    rows = read_csv(path or DATA / 'rankings/bcur_2025.csv')
    return {norm(r['name']): int(r['rank']) for r in rows if r['rank'].isdigit()}


def arwu_ranks(path=None):
    rows = read_csv(path or DATA / 'rankings/arwu_2025.csv')
    return {norm(r['name']): (r['rank'], r['region']) for r in rows}


def band_mid(rank):
    m = re.fullmatch(r'(\d+)-(\d+)', rank)
    return (int(m[1]) + int(m[2])) / 2 if m else float(rank)


def admission_table(data=DATA, years=YEARS):
    """{(省, 年): {学校: 各组/专业最低位次的中位数}}；物理类，不分科的省用综合。"""
    out = {}
    for prov in sorted(p for p in data.iterdir() if p.is_dir()):
        for year in years:
            path = next((prov / f'{kind}_{year}.csv' for kind in ('physics', 'general')
                         if (prov / f'{kind}_{year}.csv').exists()), None)
            if not path:
                continue
            ranks = defaultdict(list)
            for row in read_csv(path):
                r = (row.get('rank') or '').strip()
                if r.isdigit() and int(r) > 0:
                    ranks[norm(row['name'])].append(int(r))
            out[(prov.name, year)] = {s: st.median(v) for s, v in ranks.items()}
    return out


def neighbors(rank, refs, exclude=None):
    return [k for s, (a, k) in refs.items() if s != exclude and rank / WINDOW <= a <= rank * WINDOW]


def ref_sets(table, bcur):
    out = {}
    for key, schools in table.items():
        refs = {s: (a, bcur[s]) for s, a in schools.items() if s in bcur}
        if len(refs) >= MIN_REFS:
            out[key] = refs
    return out


def equivalent(school, table, bcur, refs=None, exclude_self=False):
    school = norm(school);refs = refs or ref_sets(table, bcur);points = []
    for key, rset in refs.items():
        if school not in table[key]:
            continue
        a = table[key][school];near = neighbors(a, rset, school if exclude_self else None)
        if len(near) >= MIN_NEIGHBORS:
            points.append({'province': key[0], 'year': key[1], 'admission_rank': round(a),
                           'equivalent': round(st.median(near)), 'neighbors': len(near)})
    if not points:
        return None
    eq = sorted(p['equivalent'] for p in points)
    return {'school': school, 'equivalent_bcur': round(st.median(eq)), 'low': eq[0], 'high': eq[-1],
            'province_years': len(points), 'points': points}


def world_equivalent(bcur_rank, bcur, arwu, spread=0.15):
    near = [s for s, k in bcur.items() if bcur_rank * (1 - spread) <= k <= bcur_rank * (1 + spread)]
    inside = [band_mid(arwu[s][0]) for s in near if s in arwu and arwu[s][1] == '中国']
    if not inside:
        return None
    return {'arwu_median': round(st.median(inside)), 'peers_in_top1000': len(inside),
            'peers_outside_top1000': len(near) - len(inside)}


def validate(table, bcur, min_points=10):
    refs = ref_sets(table, bcur);ratios = defaultdict(list)
    for school, true in bcur.items():
        res = equivalent(school, table, bcur, refs, exclude_self=True)
        if res and res['province_years'] >= min_points:
            band = '1-50' if true <= 50 else '51-100' if true <= 100 else '101-200' if true <= 200 else '201+'
            ratios[band].append(res['equivalent_bcur'] / true)
    allr = [r for v in ratios.values() for r in v]
    if not allr:
        return None
    err = sorted(abs(math.log(r)) for r in allr)
    return {'schools': len(allr), 'median_factor': round(math.exp(st.median(err)), 2),
            'p80_factor': round(math.exp(err[int(0.8 * len(err))]), 2),
            'bias_by_band': {k: round(st.median(v), 2) for k, v in sorted(ratios.items())}}


def coop_schools(path=None):
    rows = read_csv(path or DATA / 'schools.csv')
    return [r['name'] for r in rows if r['level'] == '本科' and '合作办学' in (r.get('note') or '')]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('schools', nargs='*')
    ap.add_argument('--coop', action='store_true', help='换算教育部名单中全部合作办学本科')
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    table, bcur, arwu = admission_table(), bcur_ranks(), arwu_ranks()
    names = list(args.schools) + (coop_schools() if args.coop else [])
    results = []
    for name in names:
        if norm(name) in bcur:
            results.append({'school': norm(name), 'bcur': bcur[norm(name)], 'note': '有软科名次，不换算'})
            continue
        res = equivalent(name, table, bcur)
        if res:
            res['world'] = world_equivalent(res['equivalent_bcur'], bcur, arwu)
            own = arwu.get(norm(name))
            res['own_arwu'] = own[0] if own else None
        results.append(res or {'school': norm(name), 'note': '仓库投档表中可比数据不足'})
    out = {'results': results}
    if args.validate:
        out['validation'] = validate(table, bcur)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2));return
    for r in results:
        if 'equivalent_bcur' not in r:
            print(f"{r['school']}：{r.get('bcur') and '软科第%d名' % r['bcur'] or r['note']}");continue
        w = r['world'];w = f"；世界等效约 ARWU {w['arwu_median']}" if w else ''
        own = f"；本校 ARWU {r['own_arwu']}" if r['own_arwu'] else ''
        print(f"{r['school']}：等效软科约第{r['equivalent_bcur']}名（{r['low']}—{r['high']}，{r['province_years']}个省年）{w}{own}")
    if args.validate:
        print('检验：', json.dumps(out['validation'], ensure_ascii=False))


if __name__ == '__main__':
    main()
