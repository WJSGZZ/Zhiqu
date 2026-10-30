#!/usr/bin/env python3
"""Aggregate-only temporal diagnostic of graduate score tiers (never a personal admission probability).

沿用旧分支c813ec4的聚合诊断，适配只读院校库可用视图；不取名单或重构个人成绩。
The score-only decision is labelled total_only_analysis; subjects/singles are unknown,
so these diagnostics are not eligibility decisions by kaoyan_position.place().
"""
import argparse,collections,csv,hashlib,json,math,random,sqlite3,os,re
from pathlib import Path
TIERS=('冒险','够一够','相对稳妥')
KEY=('institution_id','program_code','college','study_mode','admission_route','special_plan','degree_type','direction','joint_program')
QUANTILES=(('min',0),('q1',.25),('median',.5),('q3',.75),('max',1))
DEFAULT_DB=Path(os.environ.get('ZHIQU_EDUCATION_DB') or Path(__file__).resolve().parents[2]/'zhiqu-shared/data/education/education.sqlite').expanduser()
FOCUS=('0812','0854','0835')
def total_only_analysis(score,previous,older=None):
    """现行总分阈值的条件诊断；不伪造模考完整性或单科资格。"""
    refs=[previous]+([older] if older else [])
    if any(not complete(r) or r['n']<5 for r in refs):return None
    tier='相对稳妥' if older and score>=previous['median'] and score>=older['median'] else '够一够' if score>=previous['q1'] else '冒险'
    return '够一够' if tier=='相对稳妥' and any(r['n']<10 for r in refs) else tier

def complete(r):
    n=r.get('n');vals=[r.get(k) for k,_ in QUANTILES]
    return (isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) and n>=1 and int(n)==n
            and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vals)
            and vals==sorted(vals) and vals[0]>=0)

def cluster_id(r):return r['institution_id']

def unknown(v):
    text=str(v or '').strip()
    return not text or any(x in text for x in ('未注明','未明确','未标','待核','无法区分','详见','不详','未知'))

def scope_risks(r):
    risks=[]
    for field,label in [('admission_route','一志愿/调剂'),('study_mode','学习方式'),('special_plan','专项'),('joint_program','联培'),('direction','方向'),('degree_type','学位类型')]:
        if unknown(r.get(field)):risks.append(label+'范围未明确')
    if any(x in str(r.get('scope') or '') for x in ('未排除','未做排除','无法区分','无备注')):risks.append('专项或联培口径可能混合')
    if r.get('scope_mismatch') not in (None,'','否','无','一致','无冲突'):risks.append('分布与线范围待核：'+str(r['scope_mismatch']))
    if r.get('grade')!='官方':risks.append('非官方独立统计，仅敏感性参照')
    precision=r.get('quantile_rounding')
    if r.get('quantile_method')!='inclusive_linear' or not isinstance(precision,(int,float)) or isinstance(precision,bool) or not math.isfinite(precision) or precision<0:risks.append('分位算法或舍入口径未确认')
    if unknown(r.get('scope')):risks.append('范围原文未明确')
    return risks

def line_compatibility(distribution,line):
    """只在同身份/学院/代码/年内进一步判范围；未知不冒相同。"""
    gaps=[]
    for field in KEY[3:]:
        a=distribution.get(field);b=line.get(field)
        if unknown(a) or unknown(b):gaps.append(field+'未能确认同口径')
        elif str(a).strip()!=str(b).strip():return False,[field+'明确不同']
    if distribution.get('scope')!=line.get('scope'):gaps.append('范围原文不同，未核语义等价')
    return True,gaps

def identification_available(r):
    # 数据字典目前没有确证方法和舍入精度的专列；不据“六项齐全”猜它们。
    precision=r.get('quantile_rounding')
    return r.get('quantile_method')=='inclusive_linear' and isinstance(precision,(int,float)) and not isinstance(precision,bool) and precision==0

def read_rows(con,view,fields,where='',parameters=()):
    columns={r[1] for r in con.execute('PRAGMA table_info("'+view+'")')}
    if not columns:return []
    select=','.join('"'+f+'"' if f in columns else 'NULL AS "'+f+'"' for f in fields)
    return [dict(r) for r in con.execute('SELECT '+select+' FROM "'+view+'"'+(' WHERE '+where if where else ''),parameters)]


def coarse_gaps(rows):
    """仅诊断同学校/代码的连续年为何未可比，不拼接分数或小n值。"""
    groups=collections.defaultdict(lambda:collections.defaultdict(list));out=[]
    for row in rows:
        if row.get('institution_id') and row.get('program_code'):groups[(row['institution_id'],row['program_code'])][row['year']].append(row)
    for (institution,code),years in sorted(groups.items()):
        for year,now in sorted(years.items()):
            previous=years.get(year-1)
            if not previous:continue
            mismatches=sorted({field for a in previous for b in now for field in KEY[2:] if (a.get(field)or'')!=(b.get(field)or'')})
            out.append({'institution_id':institution,'school':now[0]['school'],'code':code,'year':year,
                        'possible_row_pairs_before_scope':len(previous)*len(now),'changed_key_fields':';'.join(mismatches),
                        'has_small_reference_or_outcome':any(complete(r) and r['n']<5 for r in previous+now),
                        'missing_quartiles':any(not complete(r) for r in previous+now),
                        'source_previous':';'.join(sorted({str(r['source_id'])for r in previous})),
                        'source_current':';'.join(sorted({str(r['source_id'])for r in now})),
                        'note':'只列缺口，不将不同范围合并；不导出小n分数。'})
    return out


def order_bounds(admitted):
    """Conservative order-statistic envelopes implied by inclusive interpolation.

    At h=(n-1)p, x_floor(h) <= Qp <= x_ceil(h); if h is integral equality
    holds. Ignoring the interpolation equality coupling enlarges the feasible set,
    so the resulting count bounds are conservative, not confidence intervals.
    """
    if not complete(admitted):raise ValueError('分位统计须完整、有限、顺序合法且n为正整数')
    n=int(admitted['n']);lower=[admitted['min']]*n;upper=[admitted['max']]*n
    for field,p in QUANTILES:
        h=(n-1)*p;j=math.floor(h);k=math.ceil(h);q=admitted[field]
        for i in range(n):
            if i>=k:lower[i]=max(lower[i],q)
            if i<=j:upper[i]=min(upper[i],q)
    if any(a>b for a,b in zip(lower,upper)):raise ValueError('摘要与有序统计量约束不相容')
    return lower,upper

def count_bounds(admitted,low=-math.inf,high=math.inf):
    """Bounds for count with low <= score < high; scores are never reconstructed."""
    if low>=high:return (0,0)
    lo,hi=order_bounds(admitted)
    return sum(a>=low and b<high for a,b in zip(lo,hi)),sum(b>=low and a<high for a,b in zip(lo,hi))
def tier_intervals(previous,older=None):
    q=previous['q1'];steady=max(previous['median'],older['median']) if older and min(previous['n'],older['n'])>=10 else math.inf
    return [('冒险',-math.inf,q),('够一够',q,steady),('相对稳妥',steady,math.inf)]
def quantile(values,p):
    a=sorted(values);h=(len(a)-1)*p;j=int(h);return a[j]+(a[min(j+1,len(a)-1)]-a[j])*(h-j)
def bootstrap_rate(points,outcome,reps=2000,seed=20261020):
    groups=collections.defaultdict(list)
    for p in points:groups[p['cluster']].append(p[outcome])
    if not points:return None,None,'无评价点'
    if len(groups)<2:return None,None,'不足2个独立学校簇，95%区间不可估'
    counts=[(sum(v),len(v)) for _,v in sorted(groups.items())];rng=random.Random(seed);rates=[]
    for _ in range(reps):
        selected=[counts[rng.randrange(len(counts))] for _ in counts];rates.append(sum(x[0] for x in selected)/sum(x[1] for x in selected))
    return quantile(rates,.025),quantile(rates,.975),'学校外层整簇percentile bootstrap；非随机样本，不支持总体覆盖保证'
def write_csv(path,rows,fields=None):
    rows=list(rows);fields=fields or list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def summarize(points,reps,seed):
    out=[]
    for setting in ['strict_n10','sensitivity_n10','sensitivity_small_n']:
      for scenario in ['lowest_published_line','highest_published_line']:
       scopes=[('overall','all'),('year',None),('discipline',None)]
       for dimension,value in scopes:
        values=[value] if value else sorted({str(p[dimension]) for p in points if p['setting']==setting and p['scenario']==scenario})
        for group in values:
         for tier in TIERS:
          subset=[p for p in points if p['setting']==setting and p['scenario']==scenario and p['tier']==tier and (dimension=='overall' or str(p[dimension])==group)]
          for unit in ['published_quantile_anchor','integer_grid']:
           sub=[p for p in subset if p['unit']==unit];row=dict(setting=setting,scenario=scenario,dimension=dimension,group=group,tier=tier,unit=unit,n_points=len(sub),n_clusters=len({p['cluster'] for p in sub}),n_school_clusters=len({p['cluster'] for p in sub}),n_program_clusters=len({(p['cluster'],p['code']) for p in sub}))
           for outcome in ['above_line','in_admitted_range']:
            lo,hi,note=bootstrap_rate(sub,outcome,reps,seed);row[outcome+'_rate']=sum(p[outcome] for p in sub)/len(sub) if sub else None;row[outcome+'_ci95_low']=lo;row[outcome+'_ci95_high']=hi;row['interval_note']=note
           out.append(row)
    return out

def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()

def run(db,output,reps=2000,seed=20261020,prefixes=FOCUS):
    wal=Path(str(db.resolve())+'-wal')
    if wal.exists() and wal.stat().st_size:raise ValueError('存在非空WAL；主文件指纹不足以代表快照，须用已静态发布的只读库')
    output.mkdir(parents=True,exist_ok=True);before=db.stat();identity=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns);con=sqlite3.connect('file:'+str(db.resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    try:
        version_before=con.execute('PRAGMA data_version').fetchone()[0];con.execute('BEGIN')
        names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('view','table')")}
        dist_view='ky_v_usable' if 'ky_v_usable' in names else 'v_usable'
        line_view='ky_v_usable_line' if 'ky_v_usable_line' in names else 'v_usable_line'
        fields=list(dict.fromkeys(['record_id','school','year','source_id','src_row','scope','list_type','grade','scope_mismatch','n',*[k for k,_ in QUANTILES],*KEY,'quantile_method','quantile_rounding']))
        condition="list_type='拟录取'";args=[]
        if prefixes:
            condition+=' AND ('+' OR '.join('program_code LIKE ?' for _ in prefixes)+')';args=[x+'%' for x in prefixes]
        all_count=con.execute('SELECT count(*) FROM "'+dist_view+'" WHERE list_type=?',('拟录取',)).fetchone()[0]
        all_rows=read_rows(con,dist_view,fields,condition,args)
        fields_line=list(dict.fromkeys(['record_id','school','year','line_total','grade','source_id','src_row','scope',*KEY]))
        lines=read_rows(con,line_view,fields_line,'line_total IS NOT NULL')
        supplemental=read_rows(con,'ky_v_retest_line',['record_id','institution_id','school','program_code','college','year','total','degree_type','study_mode','special_plan','line_scope','source_id','src_locator'])
        source_grades={r[0]:r[1] for r in con.execute('SELECT source_id,grade FROM source')} if supplemental and 'source' in names else {}
        for row in supplemental:
            row.update(line_total=row.pop('total'),scope=row.pop('line_scope'),src_row=row.pop('src_locator'),grade=source_grades.get(row.get('source_id')))
        lines.extend(supplemental);con.commit();version_after=con.execute('PRAGMA data_version').fetchone()[0]
    finally:con.close()
    if version_before!=version_after or (wal.exists() and wal.stat().st_size):raise RuntimeError('数据库快照期间发生外部变更或出现WAL，请重跑静态库')
    if identity(db.stat())!=identity(before):raise RuntimeError('取样期间数据库版本改变，请重跑')
    db_sha=file_sha(db)
    if identity(db.stat())!=identity(before):raise RuntimeError('取指纹期间数据库版本改变，请重跑')
    lines=[r for r in lines if isinstance(r.get('line_total'),(int,float)) and not isinstance(r['line_total'],bool) and math.isfinite(r['line_total'])]
    line_groups=collections.defaultdict(list)
    for r in lines:line_groups[(r['institution_id'],r['program_code'],r['college'] or '',r['year'])].append(r)
    groups=collections.defaultdict(lambda:collections.defaultdict(list));excluded=[]
    for r in all_rows:
      if not complete(r):excluded.append({'record_id':r['record_id'],'reason':'缺完整六项或统计次序无效','year':r['year'],'school':r['school'],'code':r['program_code']});continue
      if not r.get('institution_id') or not re.fullmatch(r'\d{4}(?:\d{2})?',str(r.get('program_code')or'')):
          excluded.append({'record_id':r['record_id'],'reason':'学校/代码未明确；不合并多个原专业代码','year':r['year']});continue
      groups[tuple(r.get(k) or '' for k in KEY)][r['year']].append(r)
    points=[];pairs=[];bounds=[]
    for key,years in sorted(groups.items()):
      for year,current in sorted(years.items()):
       if year-1 not in years:
        excluded.append({'school':current[0]['school'],'code':key[1],'year':year,'reason':'同身份和口径键没有连续上一年完整分布'});continue
       previous=years[year-1];older=years.get(year-2,[])
       if len(current)!=1 or len(previous)!=1 or len(older)>1:
        excluded.append({'school':current[0]['school'],'code':key[1],'year':year,'reason':'同口径多源歧义；未任选或相加'});continue
       y=current[0];p=previous[0];o=older[0] if older else None
       if any(r['n']<5 for r in [y,p]+([o] if o else [])):
        excluded.append({'school':y['school'],'code':key[1],'year':year,'reason':'已知本年或参考年n<5，不能当无Y-2而定档；不导出小n分数'});continue
       choices=line_groups.get((key[0],key[1],key[2],year),[])
       compatible=[(x,line_compatibility(y,x)[1]) for x in choices if line_compatibility(y,x)[0]]
       choices=[x for x,gaps in compatible]
       exact_official=[x for x,gaps in compatible if x.get('grade')=='官方' and not gaps]
       choices=exact_official or choices
       values=sorted({x['line_total'] for x in choices})
       risks=sorted(set(scope_risks(y)+scope_risks(p)))
       if o:risks=sorted(set(risks+scope_risks(o)))
       same_scope=all(x.get('scope')==y.get('scope') for x in [p]+([o] if o else []))
       same_quantile=all((x.get('quantile_method'),x.get('quantile_rounding'))==(y.get('quantile_method'),y.get('quantile_rounding')) for x in [p]+([o] if o else []))
       if not same_scope:risks.append('跨年范围原文不同，未核等价')
       if not same_quantile:risks.append('跨年分位方法/精度不同')
       line_risks=sorted({gap for x in choices for gap in line_compatibility(y,x)[1]})
       risks+=line_risks
       if len(values)>1:risks.append('Y方向线多值；仅最低/最高已发布线情景，不能选统一线')
       if not values:risks.append('Y年同学院专业线未取得')
       if not o:risks.append('无连续Y-2，不可能产生相对稳妥')
       n_small=min(y['n'],p['n'],o['n'] if o else math.inf)<10
       strict=not scope_risks(y) and not scope_risks(p) and (not o or not scope_risks(o)) and len(values)==1 and not n_small and not line_risks and all(x.get('grade')=='官方' for x in choices) and same_scope and same_quantile
       pairid='|'.join(map(str,key))+'|'+str(year)
       pairs.append(dict(pair_id=pairid,school=y['school'],code=key[1],college=key[2],year=year,n_previous=p['n'],n_current=y['n'],older_year=year-2 if o else '',strict_eligible=strict,quantile_bounds_available=identification_available(y),small_n=n_small,line_values=json.dumps(values),risks='；'.join(risks),current_scope=y['scope'],previous_scope=p['scope'],source_current=y['source_id'],source_previous=p['source_id'],source_older=o['source_id'] if o else '',grade_current=y.get('grade'),grade_previous=p.get('grade'),joint_program=key[-1],line_sources=';'.join(x['source_id']+':'+str(x['src_row']) for x in choices)))
       settings=['sensitivity_small_n'] if n_small else ['sensitivity_n10']+(['strict_n10'] if strict else [])
       for scenario,line in [('lowest_published_line',min(values) if values else None),('highest_published_line',max(values) if values else None)]:
        # Count bounds are still possible without a Y line; line-conditioned rates are not.
        for tier,low,high in tier_intervals(p,o):
         identified=identification_available(y)
         l,u=count_bounds(y,low,high) if identified else (None,None)
         passed=count_bounds(y,max(low,line),high) if identified and line is not None else (None,None)
         failed=count_bounds(y,low,min(high,line)) if identified and line is not None else (None,None)
         bounds.append(dict(pair_id=pairid,scenario=scenario,tier=tier,n=y['n'],count_lower=l,count_upper=u,
             fraction_lower=l/y['n'] if identified else None,fraction_upper=u/y['n'] if identified else None,
             above_line_rate_lower=passed[0]/(passed[0]+failed[1]) if identified and line is not None and passed[0]+failed[1]>0 else None,
             above_line_rate_upper=passed[1]/(passed[1]+failed[0]) if identified and line is not None and passed[1]+failed[0]>0 else None,
             bound_type='分位数约束保守识别界；不是95%区间' if identified else '未确认inclusive分位算法及零舍入；人数识别界不报',
             in_admitted_range_note='实际录取者落在本年自身[min,max]内恒为1，不能验证上岸概率'))
        if line is None:continue
        evaluations=[('published_quantile_anchor',name,y[name]) for name,_ in QUANTILES]+[('integer_grid',str(score),float(score)) for score in range(max(0,math.ceil(line-30)),min(500,math.floor(line+30))+1)]
        for setting in settings:
         for unit,label,score in evaluations:
          points.append(dict(setting=setting,scenario=scenario,pair_id=pairid,cluster=cluster_id(y),school=y['school'],code=key[1],discipline=key[1][:4],year=year,unit=unit,anchor=label,score=score,tier=total_only_analysis(score,p,o),above_line=int(score>=line),in_admitted_range=int(y['min']<=score<=y['max']),line=line,admitted_min=y['min'],admitted_max=y['max'],analysis_type='total_only_analysis；未核科目及单科资格',source_current=y['source_id'],source_previous=p['source_id'],grade_current=y.get('grade'),grade_previous=p.get('grade'),risk='；'.join(risks)))
    summary=summarize(points,reps,seed)
    gaps=coarse_gaps(all_rows)
    write_csv(output/'scope_gaps.csv',gaps)
    write_csv(output/'pairs.csv',pairs);write_csv(output/'evaluation_points.csv',points);write_csv(output/'summary.csv',summary);write_csv(output/'quantile_identification_bounds.csv',bounds);write_csv(output/'excluded.csv',excluded)
    coverage={'db':str(db.resolve()),'db_sha256':db_sha,'seed':seed,'bootstrap_replicates':reps,'all_usable_admitted_rows':all_count,'usable_admitted_rows':len(all_rows),'source_grade_counts':dict(collections.Counter(r.get('grade')or'未提供' for r in all_rows)),'coarse_consecutive_school_code_cells':len(gaps),'complete_quantile_rows':sum(complete(r) for r in all_rows),'complete_n10_rows':sum(complete(r) and r['n']>=10 for r in all_rows),'consecutive_pairs':len(pairs),'strict_n10_pairs':sum(p['strict_eligible'] for p in pairs),'sensitivity_n10_pairs':sum(not p['small_n'] for p in pairs),'small_n_pairs':sum(p['small_n'] for p in pairs),'independent_school_clusters':len({p['cluster'] for p in points}),'school_program_clusters':len({(p['cluster'],p['code']) for p in points}),'pairs_with_two_training_years':sum(bool(p['older_year']) for p in pairs),'evaluation_points':len(points),'focus_prefixes':list(prefixes),'bounds_identified_pairs':sum(p['quantile_bounds_available'] for p in pairs),'actual_individual_admitted_rates':'不可识别；仅六项统计不能恢复逐人成绩，不构造个人样本'}
    (output/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2))
    overview=[]
    for r in summary:
     if r['setting']=='sensitivity_n10' and r['dimension']=='overall' and r['unit']=='integer_grid':overview.append('|'+r['scenario']+'|'+r['tier']+'|'+str(r['n_points'])+'|'+(f"{r['above_line_rate']:.1%}" if r['above_line_rate'] is not None else '不可估')+'|'+(f"{r['in_admitted_range_rate']:.1%}" if r['in_admitted_range_rate'] is not None else '不可估')+'|')
    text=f'''# 考研分档：统计摘要的跨年诊断

取样范围：专业原代码前缀{','.join(prefixes)}，不自动合并4位学科与6位专业。0854是电子信息大类，不能将全组当纯计算机。整数格点仅是0—500内的诊断设计，不认证科目或满分。

结论：现有数据不足以证明三档可靠，也不足以支持调整阈值。可用拟录取统计 {len(all_rows)} 行，完整且n≥10为 {coverage['complete_n10_rows']} 行；同学校身份×代码×学院×学习方式×一志愿/调剂×专项标签×学位类型×方向×联培的连续年对 {len(pairs)}，严格同口径n≥10年对 {coverage['strict_n10_pairs']}，宽松n≥10为 {coverage['sensitivity_n10_pairs']}。仅按学校/原代码连续的候选格{len(gaps)}个，改变了哪些结构化范围或遇到小n见scope_gaps.csv，不因它们粗键能连上就当可比较。具备Y-2、Y-1两年训练分布的年对 {coverage['pairs_with_two_training_years']}；缺两年不能出现“相对稳妥”。

方法：固定种子{seed}，只读v_usable的聚合统计；训练仅用Y-1和确有的连续Y-2，Y只评价。总分阈值照既有规则作total_only_analysis，未取得科目/单科资格，不能替个人定档。Y年真实发布的五个分位锚点作为“锚点”评价，重复分数仍各自代表对应锚点；每个Y年已发布线±30分的整数网格作敏感性诊断。两者都是非随机评价点，不是录取者样本；不按n给锚点或网格加人数权重，不从分位数还原个人分数。完整已录取者处在自身[min,max]内恒为1，不能把它解释为预测成功率。

|Y线情景|档|网格点数|过情景线比例|进入Y录取区间比例|
|---|---|---:|---:|---:|
{chr(10).join(overview)}

95%区间：summary.csv按学校外层整簇重采样（同校所有专业一起）{reps}次、percentile 2.5%/97.5%；同簇内专业/年份/网格全保留；不足2个独立学校簇不报区间。本次独立学校簇为{coverage['independent_school_clusters']}（{ '、'.join(sorted({p['school'] for p in points})) or '无'}）；少于2校的组95%区间不可估，多个专业不能伪装成独立学校。此样本不是随机抽样，区间只表示当前案例组合的重采样波动，不是全国覆盖保证；按年、四位学科的结果也在summary.csv。quantile_identification_bounds.csv仅在分位算法与精度明确时利用h=(n−1)p所限制的有序统计量上下界，给真实录取人数落入各档的保守识别界，忽略插值联动只会扩大界；这不是95%置信区间，真实录取个人比例仍不可识别。

口径影响：pairs.csv逐对留结构化范围、跨年原文、来源及等级。联培进入身份键；已明确不同方向、学位、专项、学习方式或路线的线不匹配。范围未明确、原文不同、第三方未核及多个可能适用线只作最低/最高线敏感性，不进严格组；无匹配线仍留缺口，不偷选同校其他线。没有科目和单科证明，严格组还要求同一明确分位方法和非负数值舍入精度（非零精度可比较已发布阈值，但不报精确人数界），也仅指这里登记的总分统计范围，不等于可报或三档完整规则验证。

识别界限制：只有输入明确记载inclusive_linear且quantile_rounding=0才报告人数界。现库未有可证明这两项的专列，未确认的界留空并写原因，不假设“六项统计齐全”就能忽略舍入。不能恢复个人分数；n<5不定档且不导出小n分数，5≤n<10最高只到够一够。


建议只记录、不改现有规则：保留两年中位数和单科/科目先行条件；在给稳定性结论前补同口径三年、各年n≥10且有学院/方向线的数据。先明确联培、专项、学习方式和调剂，分开记录调剂而非混池；不把相对稳妥当个人概率。本实验当前只能暴露数据覆盖与口径缺口，不能完成三档个人上岸率校准。

重跑：python3 skills/zhiqu/scripts/kaoyan_backtest.py --db /绝对路径/education.sqlite --output .cache/kaoyan-backtest --seed {seed}。DB指纹及样本数量见coverage.json。没有读取个人名单或修改原定档规则。
'''
    (output/'README.md').write_text(text)
    return coverage

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,default=DEFAULT_DB);p.add_argument('--output',type=Path,default=Path('.cache/kaoyan-backtest'));p.add_argument('--seed',type=int,default=20261020);p.add_argument('--bootstrap',type=int,default=2000);p.add_argument('--prefix',nargs='+',default=list(FOCUS),help='专业代码前缀；0854是电子信息大类，不全等于计算机');a=p.parse_args()
    if a.bootstrap<100:p.error('--bootstrap must be >=100')
    if any(not x.isdigit() or not 2<=len(x)<=6 for x in a.prefix):p.error('--prefix须为2—6位数字')
    print(json.dumps(run(a.db,a.output,a.bootstrap,a.seed,tuple(a.prefix)),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
