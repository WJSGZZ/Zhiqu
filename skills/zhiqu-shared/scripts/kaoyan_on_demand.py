#!/usr/bin/env python3
"""School-scoped official retrieval with a hard per-school time budget.

CLI parent owns the wall-clock deadline and terminates its entire worker group
at expiry. Bodies remain in RAM. An unrecognized PDF/image or scope is a reported
gap, never an invented row. Reviewed PDF/image manifests may be resumed via --reviewed after source-SHA binding.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit

from kaoyan_adapters import parse_official_html, NeedsReview, fingerprint
from kaoyan_public_http import retrieve_memory, public_receipt, safe_url
from ingest_kaoyan_lines import privacy
import zhiqu_db

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / 'skills/zhiqu-shared'
ENTRIES = ROOT / 'skills/zhiqu-grad/data/kaoyan_entrypoints.csv'
LAYERS = {'lines': ('ky_retest_line', '学院专业资格线'), 'catalog': ('ky_program_year', '招生目录'),
          'stats': ('ky_score_dist', '拟录取统计')}
CN = {'lines': '复试线', 'catalog': '招生目录', 'stats': '拟录取统计'}
RESTRICTED = {'login', 'verification', 'http_block', 'rate_limit'}

class Deadline:
    def __init__(self, seconds, clock=time.monotonic):
        self.clock, self.end = clock, clock()+seconds
    def remaining(self):
        return max(0, self.end-self.clock())
    def __call__(self):
        if not self.remaining():
            raise TimeoutError('单校取数期限已到')
        return True


def write_json(path, obj):
    privacy(obj)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')


def entries(path=ENTRIES):
    with Path(path).open() as f:
        return list(csv.DictReader(f))


def resolve_school(database, name, registry):
    matches = [r for r in registry if name in (r['school'], r['admission_unit_code'], r['institution_id'])]
    ids={r['institution_id']for r in matches if r.get('institution_id')}
    # Several real CHSI entrances can belong to one MOE identity. This is not
    # permission to choose between distinct institutions sharing a short name.
    target = next(iter(ids)) if len(ids)==1 else matches[0]['school'] if len(matches)==1 else name
    with zhiqu_db._open('education', database) as (c, _):
        identity, warnings = zhiqu_db._identity(c, target)
    entry = next((r for r in registry if r['institution_id']==identity['institution_id'] or r['school']==identity['name']), {})
    return identity, entry, warnings


def lookup(database, identity, programs, years, layers, coverage):
    """Only official obtained cells are cache hits; third-party rows never suffice."""
    result = []
    with zhiqu_db._open('education', database) as (c, _):
        for year in years:
            for layer in layers:
                table, scope = LAYERS[layer]
                covered = any(r['school']==identity['name'] and str(year)==r['year'] and r['scope_level']==scope and r['status']=='obtained' for r in coverage)
                for program in programs:
                    cols = {'lines':'program_name,total,politics,english,math,major1,major2,line_scope,college,special_plan', 'catalog':'program_name,planned,tuimian,subjects,study_mode,college,direction', 'stats':'program_name,n,min,median,max,list_type,admission_route,special_plan,study_mode,college,direction,joint_program,scope_mismatch,scope_mismatch_note'}[layer]
                    usable=' AND t.quarantine_reason IS NULL'if 'quarantine_reason'in zhiqu_db._cols(c,table)else''
                    if layer=='stats':usable+=' AND t.n>=3'
                    rows = c.execute('SELECT t.record_id,t.program_code,t.source_id,'+','.join('t.'+x for x in cols.split(','))+' FROM data.'+table+
                        ' t JOIN data.source s ON s.source_id=t.source_id WHERE t.institution_id=? AND t.year=? AND CAST(t.program_code AS TEXT) LIKE ? AND s.grade=?'+usable,
                        (identity['institution_id'], year, program+'%', '官方')).fetchall()
                    records=[dict(r)for r in rows]
                    if layer=='lines':
                        for r in records:
                            context=c.execute('select direction,joint_program,admission_route,scope_raw from data.ky_line_scope_context where record_id=?',(r['record_id'],)).fetchone()if 'ky_line_scope_context'in zhiqu_db._tables(c)else None
                            if context:r.update(dict(context))
                    specific = [json.loads(r.get('on_demand_obtained') or '{}').get(program, []) for r in coverage if r['school']==identity['name'] and str(year)==r['year'] and r['scope_level']==scope]
                    explicit = any(set(ids) <= {r['source_id'] for r in rows} and bool(ids) for ids in specific)
                    result.append(dict(year=year, layer=layer, program=program, obtained=(covered or explicit) and bool(rows),
                                       existing_rows=len(rows), records=records, source_ids=sorted({r['source_id'] for r in rows})))
    return result


def official_url(url,entry):
    host=urlsplit(url).hostname or ''
    if host=='yz.chsi.com.cn' or host.endswith('.gov.cn'):return True
    known=[urlsplit(entry.get(k,'')).hostname or '' for k in ['graduate_site_url','school_homepage_url','known_official_document_entry_url']]
    return any(host==h or (h.endswith('.edu.cn') and host.endswith('.'+'.'.join(h.split('.')[-3:]))) for h in known if h)


def navigation_links(body,url,school,entry):
    from lxml import html
    from kaoyan_tables import _decode
    root=html.fromstring(_decode(body));out=[]
    if school not in ''.join(root.itertext()):return out
    for a in root.xpath('//a[@href]'):
        label=''.join(a.itertext())
        if not re.search('研究生院|研究生招生|学校官网|学校主页|学院网站|官方网站|学校网站|院校网站|招生单位网站|院校简介|院校介绍|学校概况|学校简介|联系方式',label):continue
        target=urljoin(url,a.get('href'));host=urlsplit(target).hostname or ''
        if urlsplit(url).hostname=='yz.chsi.com.cn' and host.endswith('.edu.cn'):
            entry['graduate_site_url']=target
        if official_url(target,entry):
            try:safe_url(target)
            except Exception:continue
            if target not in out:out.append(target)
    if urlsplit(url).hostname=='yz.chsi.com.cn':
        text=' '.join(root.itertext())
        for match in re.finditer(r'(?:学校网址|学校官网|学校网站|学校主页|院校网址)\s*[:：]?\s*(https?://[^<>\s\"\']+)',text):
            target=match[1].rstrip('。，；')
            try:safe_url(target)
            except Exception:continue
            if (urlsplit(target).hostname or'').endswith('.edu.cn'):
                entry['graduate_site_url']=target
                if target not in out:out.append(target)
    return out[:6]


def discover_links(body, url, year, layer):
    """Actual public hrefs only; no guessed path, pagination or API parameters."""
    from lxml import html
    from kaoyan_tables import _decode
    root = html.fromstring(_decode(body))
    links = []
    document_page=False
    from kaoyan_adapters import source_record
    title_text=''.join(root.xpath('//h1//text() | //title/text()'))
    # The parent itself must identify the correct year and business type.
    if str(year)in title_text and re.search({'lines':'复试.*(?:线|要求)|分数线','catalog':'目录|简章|专业.*计划','stats':'拟录取'}[layer],title_text):document_page=True
    terms = {'lines': r'复试.*(?:线|要求)|分数线', 'catalog': r'目录|简章|专业.*计划', 'stats': r'拟录取'}[layer]
    for a in root.xpath('//a[@href]'):
        label = ''.join(a.itertext())
        target = urljoin(url, a.get('href'))
        host = urlsplit(target).hostname or ''
        trusted = host.endswith(('.edu.cn','.gov.cn','.chsi.com.cn')) or host==urlsplit(url).hostname
        # CHSI site-wide catalogue/news navigation is not this school's source.
        # Follow a concrete dated article, or this school's actual /sch/ link.
        if host=='yz.chsi.com.cn' and not urlsplit(target).path.startswith('/sch/') and not re.search(r'20\d\d',label):continue
        attachment=document_page and bool(re.search(r'\.(?:pdf|xlsx?|docx?|png|jpe?g)(?:\?|$)',target,re.I))
        if not trusted or not (re.search(terms,label) or attachment) or (re.search(r'20\d\d',label) and str(year) not in label):
            continue
        try: safe_url(target)
        except Exception: continue
        if target not in links: links.append(target)
    return links[:12]


def reviewed_manifest(body, url, layer, reviewed):
    from kaoyan_adapters import samples
    digest=hashlib.sha256(body).hexdigest()
    for bundle in reviewed:
        if bundle.get('layer')!=layer or bundle.get('sha256')!=digest:continue
        m=bundle['manifest'];privacy(m);p=bundle['proof']
        if not m.get('sources') or not m.get('rows'):raise ValueError('清单必须有实际来源和业务行')
        source_ids={s['source_id']for s in m['sources']}
        if any(r.get('source_id')not in source_ids for r in m['rows']):raise ValueError('业务行未绑定实际来源')
        n=p.get('original_rows')
        if (type(n)is not int or n<1 or p.get('extracted_rows')!=n or
            p.get('dual_read_equal')is not True or p.get('status')!='approved' or
            not isinstance(p.get('methods'),list) or len(set(p['methods']))<2 or
            p.get('sample_passed')is not True or
            len({json.dumps(x,sort_keys=True)for x in p.get('sample_locators',[])})<len(samples(n,p.get('read_method')=='image'))):
            raise ValueError('人工范围或读图的双读/抽核证明未通过')
        if any(s['archive_sha256']!=digest or url not in [s.get('landing_url'),s.get('file_url')] or s.get('grade')!='官方' for s in m['sources']):
            raise ValueError('复用清单未绑定实际本次原件与官方入口')
        return {'manifest':m,'proofs':[p],'pending':[],'rows':len(m['rows'])}
    return None


def fetch_public(url, deadline):
    deadline()
    if deadline.remaining() < 40:
        raise TimeoutError('剩余时间不足一次受限取文，不发新请求')
    item, attempts, reason = retrieve_memory(url, max_attempts=1)
    deadline()
    return item, public_receipt(url,item,attempts,reason)


def counts(database):
    q = Path(database).resolve()
    with sqlite3.connect(q.as_uri()+'?mode=ro',uri=True) as c:
        cfg=dict(c.execute('select key,value from storage_manifest'))
    result={}
    for owner,path in [('data',q),('audit',q.parent/cfg['audit_file'])]:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:
            for (name,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
                result[owner+'.'+name]=c.execute('select count(*) from "'+name+'"').fetchone()[0]
    return result


def run_command(command, log, deadline, env=None):
    deadline()
    with Path(log).open('w') as f:
        try:
            r=subprocess.run(command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                             timeout=deadline.remaining(), env=env)
        except subprocess.TimeoutExpired:
            raise TimeoutError('验收超时，候选不发布') from None
    deadline()
    return {'ok':r.returncode==0, 'returncode':r.returncode, 'log':str(log)}


def regression(output, deadline, candidate, live):
    """Re-run all twelve cases against live then candidate at the SAME copied path."""
    work=Path(output)/'regression'
    skill=ROOT/'skills/zhiqu'
    work.mkdir(exist_ok=True)
    before={}
    result=[]
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    originals={str(p):sha(p) for n in range(1,13) for p in (skill/'examples'/f'2026-GK-R{n:02d}').rglob('*') if p.is_file()}
    for phase,db in [('before',live),('after',candidate)]:
        env=dict(os.environ,ZHIQU_EDUCATION_DB=str(db))
        for n in range(1,13):
            name=f'2026-GK-R{n:02d}'; target=work/name
            if phase=='before':
                shutil.copytree(skill/'examples'/name,target)
                (target/'README.md').unlink(missing_ok=True)
            r=run_command([sys.executable,str(skill/'scripts/retro_run.py'),str(target)],Path(output)/(phase+'-'+name+'.log'),deadline,env)
            files=[target/'retro_ranks.csv']+sorted(p for p in (target/'retro_ranks').rglob('*') if p.is_file())
            hashes={str(p.relative_to(target)):sha(p) for p in files if p.is_file()}
            if phase=='before': before[name]=hashes
            else: result.append({'case':name,'files':len(hashes),'ok':r['ok'] and hashes==before[name]})
            if not r['ok'] or not hashes: raise ValueError('高考回归计算失败，候选不发布')
    unchanged=all(sha(Path(p))==h for p,h in originals.items())
    return {'ok':unchanged and all(r['ok'] for r in result), 'cases':result,'examples_unchanged':unchanged}


def prepare_metadata(database,candidate,proof,table_counts,output):
    """Reuse the proven-unchanged schema dictionary; update only batch metadata."""
    database,candidate,output=Path(database),Path(candidate),Path(output)
    package_file=database.parent/'datapackage.json'
    if not package_file.is_file():raise ValueError('缺少既有数据字典，不能发布不完整元数据')
    package=json.loads(package_file.read_text())
    with sqlite3.connect(candidate)as c:
        c.row_factory=sqlite3.Row
        version=c.execute('select version from dataset_version order by rowid desc limit 1').fetchone()[0]
        sources=[dict(r)for r in c.execute('select source_id,publisher,title,grade,archive_sha256,landing_url,file_url from source order by source_id')]
        changes=['# 变更记录','','由dataset_version、correction生成。','']
        for table in ['dataset_version','correction']:
            changes.extend('- '+table+'：'+json.dumps(dict(r),ensure_ascii=False)for r in c.execute('select * from '+table))
    package.update(version=version)
    package['x-generation']=proof['candidate']['generation']
    package['x-database-sha256']=proof['candidate']['query_sha256']
    new_audit=candidate.parent/proof['candidate']['audit_file']
    package['x-databases']=[dict(owner=owner,file=dest.name,bytes=src.stat().st_size,sha256=proof['candidate'][kind+'_sha256'])for owner,kind,src,dest in [('query','query',candidate,database),('audit','audit',new_audit,database.parent/new_audit.name)]]
    package['sources']=[dict(title=(r['publisher']or'')+' '+(r['title']or''),**{'x-source-id':r['source_id'],'x-grade':r['grade'],'x-sha256':r['archive_sha256']},**({'path':r['landing_url']or r['file_url']}if r['landing_url']or r['file_url']else{}))for r in sources]
    dictionary=['# 院校与升学库','','版本'+version+'；本机库不进Git。下列字典由datapackage.json生成，须与同generation审计库配对。','']
    for resource in package['resources']:
        owner=resource['x-owner'];table=resource['dialect']['sql']['table']
        resource['x-row-count']=table_counts[('data'if owner=='query'else'audit')+'.'+table]
        path=database if owner=='query'else database.parent/new_audit.name
        resource['path']='sqlite:///file:'+str(path.resolve())+'?mode=ro&uri=true'
        dictionary.extend(['### '+owner+'.'+table,'',resource['description']+'；'+str(resource['x-row-count'])+'行。','','|列|类型|单位|说明|','|---|---|---|---|'])
        for field in resource['schema']['fields']:
            dictionary.append('| '+' | '.join(str(field.get(k,'')).replace('|','／').replace('\n',' ')for k in ['name','type','unit','description'])+' |')
        dictionary.append('')
    staged=output/'metadata';staged.mkdir(exist_ok=True)
    (staged/'datapackage.json').write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n')
    (staged/'README.md').write_text('\n'.join(dictionary)+'\n')
    (staged/'CHANGELOG.md').write_text('\n'.join(changes)+'\n')
    (staged/'VERSION').write_text(version+'\n')
    return staged


def validate_and_publish(database, manifests, output, deadline):
    import kaoyan_transaction as tx
    import ingest_kaoyan_lines as lines
    import ingest_kaoyan_catalog as catalog
    import ingest_kaoyan_verified_stats as stats
    output=Path(output); candidate=output/'candidate/education.stage.sqlite';candidate.parent.mkdir(exist_ok=True)
    baseline=counts(database)
    tx.clone_pair(database,candidate,deadline)
    receipts=[]
    for layer,manifest in manifests:
        deadline()
        receipts.append(({'lines':lines,'catalog':catalog,'stats':stats}[layer]).ingest(candidate,manifest))
    with sqlite3.connect(candidate) as c:
        version=c.execute('select version from dataset_version order by rowid desc limit 1').fetchone()[0]
        major,minor,_=map(int,version.split('.'))
        c.execute('insert into dataset_version values(?,?,?,?)',(f'{major}.{minor+1}.0',dt.date.today().isoformat(),'minor','按需取得学校/专业官方原表；旧记录不变'))
    after=counts(candidate);delta={k:after[k]-v for k,v in baseline.items()}
    proof=tx.verify_append_only(database,candidate,delta,progress=lambda p:write_json(output/'validation-progress.json',p))
    write_json(output/'append-only.json',proof)
    checks={}
    env=dict(os.environ,ZHIQU_EDUCATION_DB=str(candidate))
    cmds={
        'unittest':[sys.executable,'-m','unittest','discover','-s','skills/zhiqu/tests'],
        'check_family':[sys.executable,'skills/zhiqu/scripts/check_family.py'],
        'check_demos':[sys.executable,'skills/zhiqu/scripts/check_demos.py'],
        'validate_data':[sys.executable,'skills/zhiqu/scripts/validate_data.py']}
    for name,cmd in cmds.items():
        checks[name]=run_command(cmd,output/(name+'.log'),deadline,env)
        if not checks[name]['ok']: raise ValueError('全套验收失败，候选未发布')
    checks['gaokao_12']=regression(output,deadline,candidate,database)
    if not checks['gaokao_12']['ok']: raise ValueError('12个案例逐字节比对失败，候选未发布')
    write_json(output/'validation.json',checks)
    metadata=prepare_metadata(database,candidate,proof,after,output)
    # One local rollback pair, not the raw originals; no old audit is deleted.
    rollback=output/'rollback';rollback.mkdir(exist_ok=True)
    with sqlite3.connect(Path(database).as_uri()+'?mode=ro',uri=True) as c:
        audit=Path(database).parent/dict(c.execute('select key,value from storage_manifest'))['audit_file']
    for p in [Path(database),audit]:
        deadline(); dest=rollback/p.name
        if subprocess.run(['cp','-c',str(p),str(dest)],capture_output=True).returncode:shutil.copy2(p,dest)
    deadline()
    if deadline.remaining()<5:raise TimeoutError('预留原子发布回执时间不足，候选不发布')
    receipt=tx.publish_pair(database,candidate,proof['live']['query_sha256'],proof,checks,deadline)
    write_json(output/'publish.json',receipt)
    for f in metadata.iterdir():
        dest=Path(database).parent/f.name;tmp=dest.with_name('.'+dest.name+'.ondemand.tmp')
        shutil.copy2(f,tmp)
        with tmp.open('rb')as stream:os.fsync(stream.fileno())
        os.replace(tmp,dest)
    # The accepted pair now has a durable published copy and one rollback pair.
    # Avoid retaining a second full candidate after successful publication.
    for file in [candidate,candidate.parent/proof['candidate']['audit_file']]:file.unlink()
    return {'receipt':receipt,'ingest':receipts,'validation':checks}


def update_coverage(path, school, outcomes):
    path=Path(path)
    if not path.is_file(): return
    with path.open() as f:rs=list(csv.DictReader(f));fields=list(rs[0])
    if 'on_demand_obtained' not in fields:fields.append('on_demand_obtained')
    for item in outcomes:
        scope=LAYERS[item['layer']][1]
        match=next((r for r in rs if r['school']==school and r['year']==str(item['year']) and r['scope_level']==scope),None)
        if not match:
            match={k:'' for k in fields};match.update(school=school,year=str(item['year']),scope_level=scope,status='not fetched');rs.append(match)
        reason='按需取数：'+item['reason']
        match['reason']=(match.get('reason','')+'；'+reason).strip('；')
        if item.get('published_in_library') or item.get('published_rows'):
            match['formal_official_rows']=str(int(match.get('formal_official_rows')or 0)+item.get('published_rows',0))
            if item['status']=='obtained':
                obtained=json.loads(match.get('on_demand_obtained')or '{}');obtained[item['program']]=item.get('source_ids',[]);match['on_demand_obtained']=json.dumps(obtained,ensure_ascii=False)
            # A programme request cannot prove that all school directions are present.
            if match['status']!='obtained':match['status']='partial'
        if 'deferred_reason'in fields:match['deferred_reason']='' if item.get('published_in_library') or item.get('published_rows') else match.get('deferred_reason','')
    tmp=path.with_suffix('.ondemand.tmp')
    with tmp.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def run_request(request, *, fetch=fetch_public, publisher=validate_and_publish, registry=None, lookup_fn=lookup, clock=time.monotonic):
    """Dependency injection keeps offline orchestration tests fully network-free."""
    start=clock();deadline=Deadline(request.get('budget_seconds',request['seconds']),clock);out=Path(request['output']);out.mkdir(parents=True,exist_ok=True)
    registry=entries() if registry is None else registry
    reviewed=[]
    for f in request.get('reviewed',[]):
        bundle=json.loads(Path(f).read_text());privacy(bundle);reviewed.append(bundle)
    identity,entry,warnings=resolve_school(request['database'],request['school'],registry)
    coverage_path=Path(request['coverage'])
    coverage=list(csv.DictReader(coverage_path.open())) if coverage_path.exists() else []
    stop_path=Path(request['stop_ledger'])if request.get('stop_ledger')else None
    old_stops=json.loads(stop_path.read_text())if stop_path and stop_path.exists()else []
    known_stops={r['url']for r in old_stops if r.get('stop_category')in RESTRICTED}
    cached=lookup_fn(request['database'],identity,request['programs'],request['years'],request['layers'],coverage)
    outcomes=[];manifests=[];seen=set();stopped_hosts=set();attempts=[];bodies={}
    def checkpoint():
        write_json(out/'progress.json',dict(school=identity['name'],outcomes=outcomes,attempts=attempts))
    checkpoint()
    for cell in cached:
        try:deadline()
        except TimeoutError:break
        if cell['obtained']:
            outcomes.append(dict(cell,status='obtained',reason='已取得的官方库数据直接返回，未重新请求'))
            checkpoint();continue
        year,layer=cell['year'],cell['layer']
        # Reuse known actual original URLs; no reconstructed path. CHSI first,
        # then graduate/school site, then the proven document/college page.
        queue=[entry.get(k,'') for k in ['chsi_profile_url','graduate_site_url','school_homepage_url','known_official_document_entry_url']]
        queue += request.get('entries',[])
        result=dict(cell,status='not fetched',reason='未定位可双读的官方原表',attempted_entries=[])
        while queue:
            try:deadline()
            except TimeoutError:
                result['reason']='单校时间限制，未继续请求';break
            url=queue.pop(0)
            if not url or url in result['attempted_entries']or url in result.get('not_retried_entries',[]):continue
            safe_url(url);host=urlsplit(url).hostname
            if url in known_stops:
                result['reason']='已记录被拦/登录/验证的原入口，不重复请求';result.setdefault('not_retried_entries',[]).append(url);continue
            if not official_url(url,entry):
                result['reason']='入口域名未由本校官方名录/实际导航确认，未请求';continue
            if host in stopped_hosts:
                result['reason']='该官方站本次已被拦/需验证，停止重复请求';continue
            seen.add((url,year,layer));result['attempted_entries'].append(url)
            try:
                if url in bodies:
                    item,receipt=bodies[url]
                else:
                    item,receipt=fetch(url,deadline);bodies[url]=(item,receipt)
                    attempts.append(receipt);write_json(out/'fetch-receipts.json',attempts)
                if not item:
                    category=receipt.get('stop_category') or 'other_unretrieved'
                    result['reason']='官方入口未取得：'+category
                    if category in RESTRICTED:
                        stopped_hosts.add(host);known_stops.add(url)
                        if stop_path:
                            old_stops.append({'url':url,'stop_category':category,'basis':str(out/'fetch-receipts.json')});write_json(stop_path,old_stops)
                    continue
                final_url=item.get('url',url)
                safe_url(final_url)
                if not official_url(final_url,entry):
                    result['reason']='原入口跳转到未经确认的域名；未解析、未入库'
                    checkpoint();continue
                url=final_url
                body=item['body'];deadline()
                if b'<html' in body[:3000].lower():queue.extend(navigation_links(body,url,identity['name'],entry))
                reviewed_result=reviewed_manifest(body,url,layer,reviewed)
                if reviewed_result is None and not (not body.startswith((b'%PDF',b'\x89PNG',b'\xff\xd8',b'PK\x03\x04',b'\xd0\xcf\x11\xe0')) and re.search(rb'<(?:!doctype|html|head|body|table)\b',body[:65536],re.I)):
                    result['reason']='附件需PDF/读图独立读法核对；当前自动适配未能证明完整，不入库'
                    result['sha256']=hashlib.sha256(body).hexdigest();continue
                try:
                    parsed=reviewed_result or parse_official_html(body,url,identity,year,layer,[cell['program']])
                except NeedsReview as exc:
                    # Adapter diagnostics are fixed messages, never raw source text.
                    result['reason']=str(exc)
                    queue.extend(discover_links(body,url,year,layer));continue
                except ValueError:
                    result['reason']='原表双读或结构核对未通过，整份不入库';continue
                if parsed['rows']:
                    for business in parsed['manifest']['rows']:
                        row=business.get('row',business)
                        if row.get('school')!=identity['name']or row.get('year')!=year or business.get('institution_id')!=identity['institution_id']:raise ValueError('人工清单学校/年份范围不符')
                    manifests.append((layer,parsed['manifest']));write_json(out/('reviewed-manifest-'+str(len(manifests))+'.json'),{'layer':layer,'manifest':parsed['manifest'],'proofs':parsed['proofs']})
                    result.update(status='staged',reason='原格双读一致、固定3%至少3行抽核通过；待全套验收与发布',
                                  rows=parsed['rows'],pending=parsed['pending'],source_ids=[s['source_id']for s in parsed['manifest']['sources']],proofs=parsed['proofs'])
                    break
                result['reason']='所问专业的拟录取分组均n<3，整组不保存'if parsed.get('suppressed_groups')else'官方原表未找到所问专业，或该格式范围仍需核对'
                queue.extend(discover_links(body,url,year,layer))
            except TimeoutError:
                result.update(reason='单校时间限制，未验收部分不发布');break
            except Exception:
                result['reason']='公开入口取文或解析失败；未保存原文异常内容'
        outcomes.append(result)
        checkpoint()
        if deadline.remaining()<=0:break
    published=None
    if manifests:
        try:
            deadline()
            # Same original re-fetched on another date reuses the existing source
            # identity rather than overwriting its first retrieval metadata.
            with sqlite3.connect(Path(request['database']).as_uri()+'?mode=ro',uri=True)as c:
                c.row_factory=sqlite3.Row
                for _,manifest in manifests:
                    for i,source in enumerate(manifest['sources']):
                        old=c.execute('select * from source where source_id=?',(source['source_id'],)).fetchone()
                        if old:
                            if old['archive_sha256']!=source['archive_sha256']or old['grade']!='官方':raise ValueError('来源身份冲突')
                            manifest['sources'][i]=dict(old)
            published=publisher(Path(request['database']),manifests,out,deadline)
            if not published:raise ValueError('没有成功发布回执')
            staged_index=0
            for r in outcomes:
                if r['status']=='staged':
                    partial=bool(r.get('pending'))
                    receipt=published.get('ingest',[{}for _ in manifests])[staged_index]
                    added=receipt.get('rows_inserted',receipt.get('inserted',r['rows']))
                    r.update(status='partial'if partial else'obtained',published_rows=added,published_in_library=True,reason='已发布可核对部分，另有原表范围待核'if partial else'对应所问专业原表入库；两读/抽核/只增不改/全套检查与12案例回归通过')
                    staged_index+=1
        except (TimeoutError,ValueError) as exc:
            for r in outcomes:
                if r['status']=='staged':r.update(status='partial',reason='已提取但未完成验收/发布，正式库不变；'+('时间限制'if isinstance(exc,TimeoutError)else'验收失败'))
    # Deadline may interrupt later cells. Every requested cell gets a terminal outcome.
    completed={(r['year'],r['layer'],r['program'])for r in outcomes}
    for c in cached:
        if (c['year'],c['layer'],c['program'])not in completed:outcomes.append(dict(c,status='not fetched',reason='单校时间限制，尚未发起请求'))
    source_details=[]
    source_ids=sorted({sid for r in outcomes for sid in r.get('source_ids',[])})
    if source_ids:
        with sqlite3.connect(Path(request['database']).as_uri()+'?mode=ro',uri=True)as c:
            c.row_factory=sqlite3.Row
            for sid in source_ids:
                source=c.execute('select source_id,publisher,title,grade,landing_url,file_url,published,retrieved from source where source_id=?',(sid,)).fetchone()
                if source:
                    detail=dict(source)
                    if all(r['layer']=='stats'for r in outcomes if sid in r.get('source_ids',[])):detail['title']=identity['name']+'拟录取初试总分匿名统计'
                    source_details.append(detail)
    update_coverage(coverage_path,identity['name'],outcomes)
    summary=dict(school=identity['name'],institution_id=identity['institution_id'],seconds=round(clock()-start,3),
                 deadline_seconds=request['seconds'],outcomes=outcomes,source_details=source_details,attempts=attempts,published=bool(published),warnings=warnings)
    write_json(out/'summary.json',summary)
    lines=[f"{identity['name']}：实际用时{summary['seconds']}秒，限时{request['seconds']}秒。"]
    for r in outcomes:lines.append(f"{r['year']} {r['program']} {CN[r['layer']]}：{r['status']}，{r['reason']}。来源："+'；'.join((r.get('source_ids')or(r.get('attempted_entries',[])+r.get('not_retried_entries',[])))))
    for detail in source_details:lines.append('来源详情：'+'｜'.join(str(detail[k]or'')for k in ['publisher','title','published'])+'｜'+(detail['landing_url']or detail['file_url']or'原来源未提供网址'))
    (out/'README.md').write_text('\n'.join(lines)+'\n')
    return summary


def timed_out_summary(request):
    """The parent can still report every requested cell after killing its worker."""
    out=Path(request['output']);saved=out/'progress.json'
    progress=json.loads(saved.read_text()) if saved.exists() else {}
    outcomes=progress.get('outcomes',[])
    for item in outcomes:
        if item['status']=='staged':
            item.update(status='partial',reason='单校时间限制；已解析未完成发布回执，需核对正式库后续取')
    present={(r['year'],r['layer'],r['program'])for r in outcomes}
    for year in request['years']:
        for layer in request['layers']:
            for program in request['programs']:
                if (year,layer,program)not in present:
                    outcomes.append(dict(year=year,layer=layer,program=program,status='not fetched',reason='单校时间限制，本次未完成取得'))
    # Publication is a separate, atomically written receipt. A killed process
    # must never claim that a prepared candidate reached the live database.
    summary=dict(school=progress.get('school',request['school']),seconds=request['seconds'],
                 deadline_seconds=request['seconds'],outcomes=outcomes,attempts=progress.get('attempts',[]),
                 published=(out/'publish.json').is_file(),publication_receipt=str(out/'publish.json'))
    write_json(out/'timeout.json',summary)
    if not (out/'summary.json').exists():
        write_json(out/'summary.json',summary)
        text=[summary['school']+'：单校时间限制，已终止本任务全部子进程。']
        text.extend(f"{r['year']} {r['program']} {CN[r['layer']]}：{r['status']}；{r['reason']}"for r in outcomes)
        text.append('发布状态以publish.json及正式库指纹为准；候选不等于已发布。')
        (out/'README.md').write_text('\n'.join(text)+'\n')
        update_coverage(request['coverage'],summary['school'],[r for r in outcomes if not r.get('published_rows')])
    return summary


def year_range(value):
    if value is None:return list(range(dt.date.today().year-2,dt.date.today().year+1))
    match=re.fullmatch(r'(20\d\d)(?::(20\d\d))?',value)
    if not match:raise argparse.ArgumentTypeError('年份用2024:2026或2026')
    lo,hi=int(match[1]),int(match[2]or match[1])
    if hi<lo or hi-lo>10:raise argparse.ArgumentTypeError('年份范围须递增且不超过11年')
    return list(range(lo,hi+1))


def main():
    if sys.argv[1:]==['--worker']:
        request=json.load(sys.stdin)
        try:run_request(request)
        except Exception:
            # No traceback/source text can escape the private processing worker.
            write_json(Path(request['output'])/'stopped.json',{'status':'未发布','reason':'身份/输入/期限或验收失败，原始异常不输出'})
            raise SystemExit(1)
        return
    ap=argparse.ArgumentParser(description='按学校/专业限时取官方考研数据；不绕过登录、验证码或403/412')
    ap.add_argument('--school',required=True);ap.add_argument('--program',dest='programs',nargs='+',required=True)
    ap.add_argument('--years');ap.add_argument('--layers',nargs='+',choices=list(LAYERS),default=list(LAYERS))
    ap.add_argument('--minutes',type=float,default=30);ap.add_argument('--db',default=str(zhiqu_db.DEFAULTS['education']))
    ap.add_argument('--coverage',help='另选隔离覆盖表；自定义库默认不写共享覆盖表')
    ap.add_argument('--output');ap.add_argument('--entry',action='append',default=[])
    ap.add_argument('--reviewed',action='append',default=[],help='已独立核过的PDF/图片匿名清单和文件证明；仍实际重取并核对指纹')
    args=ap.parse_args()
    if not math.isfinite(args.minutes)or args.minutes<=0 or any(not re.fullmatch(r'(?:\d{4}(?:[0-9A-Z]{2})?|S\d{6})',p)for p in args.programs):ap.error('限时须为正数；专业代码须4/6位或原S前缀')
    live_default=Path(args.db).resolve()==Path(zhiqu_db.DEFAULTS['education']).resolve()
    coverage=args.coverage or (str(SHARED/'data/coverage/kaoyan.csv')if live_default else str(Path(args.output or ROOT/'.cache/kaoyan-on-demand-isolated')/'coverage.csv'))
    request=dict(school=args.school,programs=args.programs,years=year_range(args.years),layers=args.layers,
                 seconds=args.minutes*60,budget_seconds=max(0,args.minutes*60-5),database=str(Path(args.db).resolve()),
                 coverage=str(Path(coverage).resolve()),entries=args.entry,reviewed=args.reviewed,
                 stop_ledger=str(SHARED/'data/data_complete/on-demand-known-stop-entries.json'),
                 output=str(Path(args.output or ROOT/'.cache/kaoyan-on-demand'/str(time.time_ns())).resolve()))
    output_path=Path(request['output'])
    if output_path.exists() and any(output_path.iterdir()):ap.error('输出目录非空，请换新目录保留旧取数与验收回执')
    output_path.mkdir(parents=True,exist_ok=True)
    worker=subprocess.Popen([sys.executable,__file__,'--worker'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        worker.communicate(json.dumps(request).encode(),timeout=request['seconds'])
    except subprocess.TimeoutExpired:
        os.killpg(worker.pid,signal.SIGTERM)
        try:worker.wait(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(worker.pid,signal.SIGKILL);worker.wait()
        timed_out_summary(request)
    summary=Path(request['output'])/'README.md'
    print(summary.read_text() if summary.exists() else '本次未完成发布，原因见'+request['output'])

if __name__=='__main__':main()
