"""因子扫描：哪些填报前可知的信息，能预测专业录取线次年变热还是变冷。

逐省、逐年计算各因子与"扣除全省漂移后的变化"的相关（正值 = 次年变冷）。
逐年列出是为了看因子是否稳定、是否只在某个阶段有效。
usage: python3 scripts/factor_scan.py
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
