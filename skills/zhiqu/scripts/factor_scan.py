"""因子扫描：哪些填报前可知的信息，能预测专业录取线次年变热还是变冷。

逐省、逐年计算各因子与"扣除全省漂移后的变化"的相关（正值 = 次年变冷）。
逐年列出是为了看因子是否稳定、是否只在某个阶段有效。
usage: python3 scripts/factor_scan.py                   # 因子扫描
       python3 scripts/factor_scan.py --teacher-births  # 出生人口与师范变冷的检验
"""
import csv,math,re,statistics as st,collections,random,sys
import os
D=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data')+'/'
CFG={'浙江':('zhejiang/general_{}.csv',range(2022,2027),'rank'),'河北':('hebei/physics_{}.csv',range(2021,2027),'rank'),
     '山东':('shandong/general_{}.csv',range(2023,2027),'rank'),'辽宁':('liaoning/physics_{}.csv',range(2021,2027),'score')}
def corr(x,z):
    n=len(x)
    if n<30: return None
    mx,mz=st.mean(x),st.mean(z); sx=math.sqrt(sum((a-mx)**2 for a in x)); sz=math.sqrt(sum((b-mz)**2 for b in z))
    return sum((a-mx)*(b-mz) for a,b in zip(x,z))/(sx*sz) if sx and sz else None
def val(v,metric):  # "coldness" level: larger = easier to get in
    return math.log(v) if metric=='rank' else -v/10.0
def scan():
    """逐省、逐年扫描各因子（默认模式）。"""
    res={}
    for prov,(pat,Y,metric) in CFG.items():
        data={}
        for y in Y:
            d={}
            for r in csv.DictReader(open(D+pat.format(y))):
                v=r[metric]
                if not v: continue
                k=(r['name'],r['major'])
                if k in d: continue
                d[k]=(val(float(v),metric), int(r['plan']) if r.get('plan') else None)
            data[y]=d
        smed={}
        for y in Y:
            t=collections.defaultdict(list)
            for (n,m),(v,p) in data[y].items(): t[n].append(v)
            smed[y]={n:st.median(v) for n,v in t.items() if len(v)>=3}
        rows=[]
        for y in list(Y)[1:]:
            a,b,aa=data[y-1],data[y],data.get(y-2,{})
            common=[k for k in a if k in b]
            drift=st.median(b[k][0]-a[k][0] for k in common)
            for k in common:
                n,m=k
                if n not in smed[y-1]: continue
                f={}
                f['计划变化']=math.log(b[k][1]/a[k][1]) if a[k][1] and b[k][1] else None
                f['上年跳变']=a[k][0]-aa[k][0] if k in aa else None
                f['位次水平']=a[k][0]
                f['低于本校中位']=a[k][0]-smed[y-1][n]
                f['低于本校中位(前年)']=(aa[k][0]-smed[y-2][n]) if k in aa and n in smed.get(y-2,{}) else None
                f['医学']=1.0 if re.search('医|药|护理',m) else 0.0
                f['师范']=1.0 if '师范' in m else 0.0
                f['计算机/AI']=1.0 if re.search('计算机|软件|人工智能|数据|智能',m) else 0.0
                f['中外合作']=1.0 if re.search('中外|合作',m+n) else 0.0
                rows.append((y,b[k][0]-a[k][0]-drift,f))
        res[prov]=rows
    feats=['低于本校中位','低于本校中位(前年)','位次水平','计划变化','上年跳变','医学','师范','计算机/AI','中外合作']
    print('逐年相关（正=次年变冷）')
    for f in feats:
        line=[f]
        for prov,rows in res.items():
            ys=sorted(set(r[0] for r in rows)); cs=[]
            for y in ys:
                pr=[(r[2][f],r[1]) for r in rows if r[0]==y and r[2][f] is not None]
                c=corr(*zip(*pr)) if len(pr)>=30 else None
                cs.append('  .  ' if c is None else f'{c:+.2f}')
            line.append(prov+':'+' '.join(cs))
        print(' | '.join(line))
    print({p:sorted(set(r[0] for r in rows)) for p,rows in res.items()})
    # discriminating test: partial effect of relative position controlling own last change
    print('\n控制"上年跳变"后，"低于本校中位"的偏相关；以及仅用前年相对位置')
    for prov,rows in res.items():
        pr=[(r[2]['低于本校中位'],r[2]['上年跳变'],r[1]) for r in rows if r[2]['上年跳变'] is not None]
        if len(pr)<100: continue
        x,z,yv=zip(*pr)
        rxy,rzy,rxz=corr(x,yv),corr(z,yv),corr(x,z)
        part=(rxy-rxz*rzy)/math.sqrt((1-rxz**2)*(1-rzy**2))
        print(prov,'n',len(pr),'原相关',round(rxy,3),'偏相关',round(part,3))


def teacher_births():
    """检验：师范专业相对同校其他专业的变冷，是否在出生人口降得更快的省份更明显。

    出生人口 = 年末常住人口 × 出生率（data/births_by_province.csv，国家统计局国家数据库"分省年度数据"），比较 2016 与 2024 年。
    用浙江、河北、山东三个有位次的省份，按院校所在省（data/schools.csv）汇总师范专业的相对变化。
    usage: python3 scripts/factor_scan.py --teacher-births
    """
    import random
    prov_of = {r["name"]: re.sub("省|市|壮族自治区|回族自治区|维吾尔自治区|自治区", "", r["province"])
               for r in csv.DictReader(open(D + "schools.csv", encoding="utf-8"))}
    births = {}
    for r in csv.DictReader(open(D + "births_by_province.csv", encoding="utf-8")):
        p = re.sub("省|市|壮族自治区|回族自治区|维吾尔自治区|自治区", "", r["province"])
        births[(p, int(r["year"]))] = float(r["population_10k"]) * float(r["birth_rate_permille"])
    decl = {p: math.log(births[(p, 2024)] / births[(p, 2016)]) for p, y in births if y == 2016 and (p, 2024) in births}
    per = collections.defaultdict(list)
    for exam in ("浙江", "河北", "山东"):
        pat, Y, _ = CFG[exam]
        data = {}
        for y in Y:
            d = {}
            for r in csv.DictReader(open(D + pat.format(y), encoding="utf-8")):
                if r["rank"]:
                    d.setdefault((re.sub(r"[\(（\[].*", "", r["name"]).strip(), r["major"]), math.log(float(r["rank"])))
            data[y] = d
        for y in list(Y)[1:]:
            ch = {k: data[y][k] - data[y - 1][k] for k in data[y - 1] if k in data[y]}
            other = collections.defaultdict(list)
            for (n, m), c in ch.items():
                if "师范" not in m:
                    other[n].append(c)
            for (n, m), c in ch.items():
                if "师范" in m and len(other.get(n, [])) >= 3 and n in prov_of:
                    per[prov_of[n]].append(c - st.median(other[n]))
    rows = sorted((p, len(v), st.mean(v), decl[p]) for p, v in per.items() if len(v) >= 15 and p in decl)
    x, y = [r[3] for r in rows], [r[2] for r in rows]
    r0 = st.correlation(x, y)
    rng = random.Random(0)
    pv = sum(abs(st.correlation(x, rng.sample(y, len(y)))) >= abs(r0) for _ in range(5000)) / 5000
    allv = [c for v in per.values() for c in v]
    print(f"师范相对同校其他专业：平均每年变冷 {st.mean(allv):.3f}（对数位次），{sum(v > 0 for v in allv) / len(allv):.0%} 的情况变冷，共 {len(allv)} 条")
    print(f"院校所在省 {len(rows)} 个：出生人口降幅与师范变冷的相关 {r0:.2f}，置换检验 p = {pv:.3f}（负相关 = 出生人口降得越多，师范越冷）")


if __name__ == "__main__":
    teacher_births() if "--teacher-births" in sys.argv else scan()
