"""提前批 / 专项 / 定向等招生类型的回测汇总（广东、浙江、江苏）。

对每种类型输出两项：
- 同校比较：该类型投档线与同年同校普通批（剔除中外合作）各组的中位线相比。
  位次省份（广东、浙江）为 ln(类型位次 / 普通批中位位次)，> 0 表示比普通批容易；
  江苏只有分数，为 普通批中位分 − 类型投档分（分），> 0 表示比普通批容易。
- 年际波动：按 学校 + 类型 + 定向地区 取每年最低线，相邻年份变化的中位数。
usage: python3 scripts/special_types.py
"""
import csv,math,statistics as st,collections,re,os
D=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data')+'/'
EARLY={'gd':'guangdong/early_physics.csv','zj':'zhejiang/early_general.csv','js':'jiangsu/early_physics.csv'}
def reg(prov,y):
    f={'gd':f'guangdong/physics_{y}.csv','zj':f'zhejiang/general_{y}.csv','js':f'jiangsu/physics_{y}.csv'}[prov]
    try: R=list(csv.DictReader(open(D+f)))
    except FileNotFoundError: return {}
    tmp=collections.defaultdict(list)
    for r in R:
        n=re.sub(r'[(（].*','',r['name']).strip()
        if re.search('中外|合作|国际',r.get('major','')+r['name']): continue
        v=r['score'] if prov=='js' else r['rank']
        if v: tmp[n].append(int(v))
    return {n:st.median(v) for n,v in tmp.items()}
def load(prov):
    R=list(csv.DictReader(open(D+EARLY[prov])))
    if prov=='gd': R=[r for r in R if r['subject']=='物理']
    for r in R:
        r['name']=re.sub(r'[(（].*','',r['name']).strip()
        if prov=='zj':
            m=r['major']; r['type']='师范' if '师范' in m else '航海轮机' if re.search('航海|轮机',m) else '小语种等' if re.search('语',m) else '其他提前'
        r['type']=re.sub(r'（.*|\(.*','',r['type'])
    return R
res=[]
for prov in ('gd','zj','js'):
    R=load(prov); metric='score' if prov=='js' else 'rank'
    by=collections.defaultdict(list)
    for r in R: by[r['type']].append(r)
    for t,S in sorted(by.items()):
        # same-school discount vs regular batch
        disc=[]
        for r in S:
            g=reg(prov,r['year']).get(r['name'])
            if not g or not r[metric]: continue
            v=int(r[metric])
            disc.append(g-v if metric=='score' else math.log(v/g))  # >0: 提前/专项更容易
        # stability: school+type+region min per year
        agg=collections.defaultdict(dict)
        for r in S:
            k=(r['name'],r.get('region',''))
            v=int(r[metric]) if r[metric] else None
            if v is None: continue
            y=int(r['year']); cur=agg[k].get(y)
            agg[k][y]= (min(cur,v) if metric=='score' else max(cur,v)) if cur else v
        ch=[]
        for k,d in agg.items():
            for y in d:
                if y+1 in d: ch.append(abs(d[y+1]-d[y]) if metric=='score' else abs(math.log(d[y+1]/d[y])))
        yrs=sorted(set(r['year'] for r in S))
        res.append((prov,t,f"{yrs[0]}-{yrs[-1]}",len(S),len(disc),round(st.median(disc),2) if disc else '',len(ch),round(st.median(ch),3) if ch else ''))
# regular batch stability at school-min level
for prov,ys in (('gd',range(2022,2027)),('zj',range(2022,2027)),('js',range(2023,2027))):
    ch=[]
    for y in ys:
        a,b=reg(prov,y),reg(prov,y+1)
        for n in a:
            if n in b: ch.append(abs(b[n]-a[n]) if prov=='js' else abs(math.log(b[n]/a[n])))
    res.append((prov,'【普通批·学校最低】','',0,0,'',len(ch),round(st.median(ch),3)))
print('prov|type|years|n|n_disc|median_discount(logrank>0=easier; js: points below regular)|n_pairs|median_abs_change')
for r in res: print('|'.join(map(str,r)))
