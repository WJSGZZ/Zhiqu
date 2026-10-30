#!/usr/bin/env python3
"""Bounded recruitment evidence, not a general job spider or salary estimator.

Only an explicit official table with visible place/year/job columns is automated.
Other formats return a gap. Contact details, applications and candidate lists are
never persisted. Existing legacy notices are search hints, not verified hits.
"""
import argparse
import csv
import datetime as dt
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlsplit

from kaoyan_public_http import retrieve_memory, public_receipt, safe_url
from kaoyan_on_demand import Deadline
from ingest_kaoyan_lines import privacy
import zhiqu_db

ROOT = Path(__file__).resolve().parents[3]
DOMAINS = ROOT / 'skills/zhiqu-shared/references/official-domains.csv'
SCHEMA = 'career-table-evidence-v1'
FIELDS = {'duties': '岗位职责', 'requirements': '任职要求', 'pay': '报酬原文', 'schedule': '到岗安排'}
HEADERS = {'region': {'工作地点', '工作城市'}, 'year': {'招聘年度', '招聘年份'},
           'position': {'岗位名称', '职位名称'}, 'stage': {'招聘类型'}, 'duties': {'岗位职责', '工作职责'},
           'requirements': {'任职要求', '岗位要求'}, 'pay': {'实习报酬', '薪酬待遇', '报酬'},
           'schedule': {'到岗安排', '实习时间'}}
SOURCE_COLS = 'source_id grade publisher title landing_url file_url published retrieved method archive_sha256 archive_path archive_status wayback_url note citation license producer_revision'.split()


class Gap(ValueError):
    """Fixed messages only; never echo original cells or exception strings."""


def norm(value):
    return re.sub(r'\s+', ' ', value).strip()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def public_text(value):
    privacy(value)
    if re.search(r'姓名|考号|身份证|考生|准考证|联系|电话|邮箱|负责人|(?<!\d)1[3-9]\d{9}(?!\d)|[\w.+-]+@[\w.-]+',value):
        raise Gap('拟保存文本混有联系资料，不保存')


def dump(path, value):
    privacy(value)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w')as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        f.flush();os.fsync(f.fileno())
    os.replace(tmp, path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def official(url):
    safe_url(url)
    host = urlsplit(url).hostname
    with DOMAINS.open() as f:
        rows = list(csv.DictReader(f))
    # A government/school host still says nothing about a job's city or year.
    if host.endswith(('.gov.cn', '.edu.cn')):
        return True
    return any(host == r['domain'] or host.endswith('.' + r['domain']) for r in rows)


def publisher_matches(url, publisher):
    host = urlsplit(url).hostname or ''
    with DOMAINS.open() as f:
        return any((host == r['domain'] or host.endswith('.' + r['domain'])) and
                   publisher == r['organization'] for r in csv.DictReader(f))


class GridReader(HTMLParser):
    """Independent streaming table reader; reject merged/nested/hidden cells."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.table, self.row, self.cell = [], None, None, None
        self.depth = 0
        self.bad = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.table, self.bad = [], False
            else:
                self.bad = True
        if self.depth:
            if tag in {'script', 'style', 'template', 'input', 'form'} or 'hidden' in attrs:
                self.bad = True
            if 'display:none' in attrs.get('style', '').replace(' ', '').lower():
                self.bad = True
            if tag == 'tr':
                self.row = []
            if tag in {'td', 'th'}:
                if any(attrs.get(k, '1') != '1' for k in ('colspan', 'rowspan')):
                    self.bad = True
                self.cell = []
            if tag == 'br' and self.cell is not None:
                self.cell.append(' ')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            if self.row is not None:
                self.row.append(norm(''.join(self.cell)))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == 'table':
            self.depth -= 1
            if self.depth == 0:
                self.tables.append(None if self.bad else self.table)
                self.table = None


def parse_table(body, entry, request):
    """lxml DOM vs stdlib streaming parser, then raw-tag sample comparison.

    The regex sample only checks transcription, not meaning/continued validity.
    All relevant rows in a matching table must pass before any are returned.
    """
    from lxml import html
    try:
        text = body.decode('utf-8-sig')
        root = html.fromstring(text)
        second = GridReader()
        second.feed(text)
        second.close()
    except Exception:
        raise Gap('非UTF-8文字HTML表格，需专门解析与核对') from None
    title = norm(' '.join(root.xpath('//title/text()')))
    public_text(title)
    if entry['publisher'] not in norm(' '.join(root.itertext())):
        raise Gap('原页未找到登记的发布单位，不能认证来源身份')
    if not re.search(r'招聘|实习|careers?|internship|graduate.program|campus', title,re.I):
        raise Gap('页面标题未明确招聘或实习，栏目壳不算公告')
    if re.search('录用名单|拟录用|面试名单|报名名单|考生名单', title):
        raise Gap('名单不在本工具范围，不保存名单或逐人记录')
    tables = root.xpath('//table')
    if len(tables) != len(second.tables):
        raise Gap('两读表格边界不同')
    raw_tables = re.findall(r'<table\b[^>]*>(.*?)</table\s*>', text, re.I | re.S)
    if len(raw_tables) != len(tables):
        raise Gap('原HTML表边界不能独立抽核')
    rows, proofs = [], []
    for ti, table in enumerate(tables):
        if any('hidden' in node.attrib or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',node.get('style',''),re.I)
               for node in [table]+list(table.iterancestors())):
            continue
        if table.xpath('.//table') or second.tables[ti] is None:
            continue
        grid = [[norm(cell.text_content()) for cell in tr.xpath('./th|./td')]
                for tr in table.xpath('./tr|./thead/tr|./tbody/tr|./tfoot/tr')]
        if not grid:
            continue
        index = {}
        for key, aliases in HEADERS.items():
            hits = [n for n, header in enumerate(grid[0]) if header in aliases]
            if len(hits) > 1:
                raise Gap('同字段存在多列，口径待人工核对')
            if hits:
                index[key] = hits[0]
        if not {'region', 'year', 'position'} <= index.keys():
            continue
        if re.search('姓名|身份证|考号|考生|手机|电话|邮箱|联系人', ' '.join(grid[0])):
            raise Gap('表格含个人或联系人字段，本工具整表拒收')
        if grid != second.tables[ti]:
            raise Gap('两种读法逐格不一致，整表未入')
        if len(grid) < 2 or any(len(r) != len(grid[0]) for r in grid):
            raise Gap('表格空白或列数不齐')
        try:
            privacy(grid)
        except ValueError:
            raise Gap('原表出现疑似个人号码，整表未入') from None
        if any(re.search(r'联系|电话|邮箱|(?<!\d)1[3-9]\d{9}(?!\d)|[\w.+-]+@[\w.-]+', cell) for row in grid[1:] for cell in row):
            raise Gap('原表混有联系资料，整表未入且不保存单元格')
        chosen = []
        for ri, row in enumerate(grid[1:], 2):
            if (row[index['region']] != request['region'] or
                row[index['year']] not in [str(y) for y in request['years']] or
                request['direction'] not in row[index['position']] or
                (request['stage'] == 'internship' and '实习' not in row[index['position']]) or
                (request['stage'] == 'graduate' and ('stage' not in index or row[index['stage']] not in {'校园招聘','应届毕业生招聘'}))):
                continue
            values = {key: row[index[key]] if key in index else None for key in request['layers']}
            chosen.append(dict(region=request['region'], year=int(row[index['year']]),
                               position=row[index['position']], stage=request['stage'],
                               stage_raw=row[index['stage']]if 'stage'in index else row[index['position']],
                               fields=values, src_table=ti + 1, src_row=ri))
        if not chosen:
            continue
        count = len(grid) - 1
        sample = sorted(random.Random(20261030).sample(range(1, len(grid)), min(count, max(3, math.ceil(count * .03)))))
        raw_rows = re.findall(r'<tr\b[^>]*>(.*?)</tr\s*>', raw_tables[ti], re.I | re.S)
        if len(raw_rows) != len(grid):
            raise Gap('原始行数不能独立抽核')
        for ri in sample:
            cells = re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]\s*>', raw_rows[ri], re.I | re.S)
            extracted = [norm(unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', ' ', c, flags=re.I)))) for c in cells]
            if extracted != grid[ri]:
                raise Gap('原件抽核未通过，整表未入')
        rows += chosen
        proofs.append(dict(src_table=ti + 1, original_rows=count, dual_read_equal=True,
                           methods=['lxml-dom-cells', 'stdlib-htmlparser-cells'],
                           sample_method='raw-html-tag-cells', sample_rows=[x + 1 for x in sample],
                           sample_passed=True, loaded_rows=len(chosen)))
    if not rows:
        raise Gap('没有显式城市、招聘年度、岗位的匹配完整文字表；不从转载地或发布日期猜范围')
    return dict(title=title, rows=rows, proofs=proofs)


def lookup(database, request):
    """Only this protocol's scoped, unexpired, verified rows are reusable."""
    today = dt.date.today().isoformat()
    result = []
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as c:
        c.row_factory = sqlite3.Row
        for row in c.execute('SELECT n.*,s.grade,s.archive_sha256,s.publisher,s.landing_url,s.retrieved FROM recruitment_notice n JOIN source s USING(source_id) WHERE n.region=?', (request['region'],)):
            try:
                meta = json.loads(row['note'])
                proof = json.loads(row['excerpt'])
                checks=c.execute("SELECT checked_on,db_value,official_value,locator,official_source_id FROM check_sample WHERE table_name='recruitment_notice' AND row_key=? AND field='career-demand-review' AND verdict='一致' ORDER BY checked_on DESC",(row['record_id'],)).fetchall()
                state_key=digest(json.dumps(meta['fields'],sort_keys=True,ensure_ascii=False).encode())
                checked=None
                for check in checks:
                    locator=json.loads(check['locator'])
                    if check['db_value']==check['official_value']==state_key and check['official_source_id']==row['source_id'] and locator.get('sha256')==row['archive_sha256'] and all(locator.get(k)==proof.get(k)for k in ('src_row','src_table')):
                        checked=dt.date.fromisoformat(check['checked_on']);break
                due=(checked+dt.timedelta(days=7))if checked else dt.date.fromisoformat(meta['review_due'])
                good = (meta['schema'] == SCHEMA and meta['direction'] == request['direction'] and
                        meta['stage'] == request['stage'] and due >= dt.date.fromisoformat(today) and
                        checked is not None and checked<=dt.date.today() and type(row['year']) is int and row['year'] in request['years'] and row['grade'] == '官方' and official(row['landing_url']) and publisher_matches(row['landing_url'],row['publisher']) and
                        re.fullmatch('[0-9a-f]{64}', row['archive_sha256']) and proof['dual_read_equal'] is True and
                        proof['sample_passed'] is True and proof['sha256'] == row['archive_sha256'])
                if good:
                    for field in request['layers']:
                        if field in meta['fields']:
                            result.append(dict(row, field=field, value=meta['fields'][field], metadata=meta))
            except (ValueError, TypeError, KeyError, sqlite3.OperationalError):
                continue
    return result


def fetch_public(url, deadline):
    deadline()
    if deadline.remaining() < 40:
        raise TimeoutError('剩余时间不足一次受限取文')
    item, attempts, reason = retrieve_memory(url, max_attempts=3, max_bytes=5_000_000)
    deadline()
    return item, public_receipt(url, item, attempts, reason)


def run_request(request, *, fetch=fetch_public, lookup_fn=lookup, clock=time.monotonic):
    """No implicit publication. Return anonymous candidate+gaps, all bodies in RAM."""
    deadline = Deadline(request['seconds'], clock)
    cached = lookup_fn(request['database'], request)
    covered = {(r['year'], r['field']) for r in cached}
    needed = {(y, field) for y in request['years'] for field in request['layers']} - covered
    result = dict(schema=SCHEMA, request={k:request[k] for k in ('region','direction','years','stage','layers')},
                  cache=cached, candidates=[], attempts=[], gaps=[], published=False)
    if not needed:
        result['missing'] = []
        return result
    stopped_hosts = set()
    for entry in request['entries']:
        if not needed:
            break
        url = entry['url']
        try:
            if not official(url) or not publisher_matches(url, entry['publisher']):
                raise Gap('网址不在已确认的官方单位域名清单')
            host = urlsplit(url).hostname
            if host in stopped_hosts:
                result['gaps'].append(dict(url=url, reason='该站已停止，不再请求'))
                continue
            item, receipt = fetch(url, deadline)
            result['attempts'].append(receipt)
            if not item:
                if receipt.get('stop_category') in {'login','verification','http_block','rate_limit','restricted_redirect','tls'}:
                    stopped_hosts.add(host)
                result['gaps'].append(dict(url=url, reason=receipt.get('stop_category') or '未取得原文'))
                continue
            if not official(item['url']) or not publisher_matches(item['url'], entry['publisher']):
                raise Gap('最终网址不在已确认的官方单位域名清单')
            try:
                parsed = parse_table(item['body'], entry, request)
            except Gap as table_gap:
                from career_positions import parse_position
                if (urlsplit(item['url']).hostname or '') not in {'www.eitech.edu.cn','eitech.edu.cn','www.bodenai.com','bodenai.com','www.tngdigital.com.cn','tngdigital.com.cn'}:
                    raise table_gap
                parsed = parse_position(item['body'], dict(entry, url=item['url']), request)
            fingerprint = digest(item['body'])
            source = dict.fromkeys(SOURCE_COLS, '')
            source.update(source_id='career-demand-'+fingerprint, grade='官方', publisher=entry['publisher'],
                          title=parsed['title'], landing_url=item['url'], retrieved=dt.date.today().isoformat(),
                          method='HTML两读逐格一致；原始标签抽核3%且至少3行，不足3行全核；仅匹配行',
                          archive_sha256=fingerprint, archive_status='已核后删除（有指纹）',
                          citation=f"{entry['publisher']}：《{parsed['title']}》，{item['url']}，取得日期{dt.date.today().isoformat()}。",
                          license='未注明')
            if parsed['proofs'][0].get('kind') == 'position-body-v1':
                source['method'] = '具体岗位正文DOM/流式两读逐段一致；保留业务段原始标签全核；不保存联系资料'
                source['published'] = parsed.get('published','')
            result['candidates'].append(dict(source=source, rows=parsed['rows'], proofs=parsed['proofs']))
            for row in parsed['rows']:
                needed -= {(row['year'], key) for key in row['fields']}
        except TimeoutError:
            result['gaps'].append(dict(url=url, reason='取数期限已到'))
            break
        except (Gap, ValueError):
            # Gap contains only our fixed diagnostics; no parser traceback/cell values.
            result['gaps'].append(dict(url=url, reason=str(sys.exc_info()[1]) if isinstance(sys.exc_info()[1], Gap) else '网址或输入未通过安全检查'))
        except Exception:
            result['gaps'].append(dict(url=url, reason='读取或解析失败；未保存原异常与正文'))
    result['missing'] = [dict(year=y, field=field) for y, field in sorted(needed)]
    privacy(result)
    return result


def publish_result(result, database, output, deadline, *, metadata_builder=None, validator=None):
    """Append to the existing notice/source tables; never rebuild old datasets.

    Publication requires the local package generator, sealed DB, lock, unchanged
    original fingerprint, FK/old-row checks and candidate validate_data. SQLite
    readers keep the old inode. One own rollback is retained, never overwritten.
    """
    import contextlib
    import fcntl
    import importlib.util
    import io
    import shutil
    import uuid
    if not result['candidates']:
        return {'published':False, 'rows':0}
    database, output = Path(database).resolve(), Path(output).resolve()
    generator = ROOT/'skills/zhiqu-shared/data/build_packages.py'
    if metadata_builder is None and not generator.is_file():
        raise Gap('本机数据库字典生成器缺失，仅留匿名候选')
    def file_sha(path):
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024), b''):
                deadline()
                h.update(block)
        return h.hexdigest()
    def sealed():
        if any(Path(str(database)+s).exists() and Path(str(database)+s).stat().st_size for s in ('-wal','-journal')):
            raise Gap('正式库仍有未封存写入，不发布')
    output.mkdir(parents=True, exist_ok=True)
    candidate = output/'employment-candidate.sqlite'
    rollback = output/'rollback-employment.sqlite'
    package_out = output/'candidate-metadata'
    if candidate.exists() or rollback.exists():
        raise Gap('本轮已有候选或回滚，不覆盖；先核交接')
    deadline()
    with database.with_suffix('.career-demand.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Gap('已有按需发布任务，不并发写入') from None
        sealed()
        initial = file_sha(database)
        shutil.copyfile(database, candidate)
        inserted = 0
        verifications=0
        with sqlite3.connect(candidate.as_uri(), uri=True) as c:
            c.execute('PRAGMA foreign_keys=ON')
            version = c.execute('SELECT version FROM dataset_version ORDER BY rowid DESC LIMIT 1').fetchone()[0]
            parts = list(map(int, version.split('.')))
            version = f'{parts[0]}.{parts[1]+1}.0'
            for bundle in result['candidates']:
                deadline()
                source = bundle['source']
                if source['archive_sha256'] != source['source_id'].removeprefix('career-demand-'):
                    raise Gap('候选来源指纹不匹配')
                old = c.execute('SELECT '+','.join(SOURCE_COLS)+' FROM source WHERE source_id=?',(source['source_id'],)).fetchone()
                if old is None:
                    c.execute('INSERT INTO source('+','.join(SOURCE_COLS)+') VALUES('+','.join('?' for _ in SOURCE_COLS)+')',[source[k] for k in SOURCE_COLS])
                elif any(old[SOURCE_COLS.index(key)] != source[key] for key in ('grade','publisher','title','landing_url','file_url','archive_sha256')):
                    raise Gap('已有来源身份不同，不覆盖')
                for row in bundle['rows']:
                    proof = next(p for p in bundle['proofs'] if p['src_table']==row['src_table'])
                    if proof.get('dual_read_equal') is not True or proof.get('sample_passed') is not True:
                        raise Gap('候选核对未通过')
                    record_id = 'career-demand-'+digest(json.dumps([source['source_id'],row,result['request']['direction']],sort_keys=True,ensure_ascii=False).encode())
                    meta = dict(schema=SCHEMA, direction=result['request']['direction'], stage=row['stage'],
                                position=row['position'], stage_raw=row['stage_raw'], fields=row['fields'],
                                review_due=(dt.date.today()+dt.timedelta(days=7)).isoformat())
                    for key in ('year_basis','year_scope','published','recruitment_year','region_raw','region_basis','position_locator','field_locators','visibility_basis'):
                        if key in row:meta[key]=row[key]
                    evidence = dict(proof, sha256=source['archive_sha256'], src_row=row['src_row'],
                                    position=row['position'], fields=row['fields'])
                    values = [record_id,row['region'],row['year'],source['title'],source['source_id'],'原表匹配行已核',
                              json.dumps(meta,ensure_ascii=False),json.dumps(evidence,ensure_ascii=False),
                              json.dumps({k:'官方原值' if v else '来源未提供' for k,v in row['fields'].items()},ensure_ascii=False)]
                    prior = c.execute('SELECT * FROM recruitment_notice WHERE record_id=?',(record_id,)).fetchone()
                    if prior is None:
                        c.execute('INSERT INTO recruitment_notice VALUES('+','.join('?' for _ in values)+')',values)
                        inserted += 1
                    state_key=digest(json.dumps(row['fields'],sort_keys=True,ensure_ascii=False).encode())
                    sample_id=record_id+'-'+dt.date.today().isoformat()
                    if not c.execute('SELECT 1 FROM check_sample WHERE sample_id=?',(sample_id,)).fetchone():
                        c.execute('INSERT INTO check_sample VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                  (sample_id,'求职','recruitment_notice',record_id,'career-demand-review',state_key,state_key,
                                   source['source_id'],'一致',dt.date.today().isoformat(),'HTML两读及原始标签抽核通过；不是资格或当前在招认证','',
                                   json.dumps({'sha256':source['archive_sha256'],'src_table':row['src_table'],'src_row':row['src_row']},ensure_ascii=False),
                                   '自动转写核对（非独立语义复核）'))
                        verifications+=1
            if not inserted and not verifications:
                candidate.unlink()
                return {'published':False,'rows':0,'reason':'候选已在库内，未重复存储'}
            c.execute('INSERT INTO dataset_version VALUES(?,?,?)',(version,dt.date.today().isoformat(),'按需追加已核匿名招聘表匹配行；旧值不改'))
            c.execute('INSERT INTO provenance_batch VALUES(?,?,?,?)',('career-demand-'+uuid.uuid4().hex,version,dt.date.today().isoformat(),'城市/岗位/年份匹配行；双读及抽核；非全城市覆盖'))
            if c.execute('PRAGMA foreign_key_check').fetchall() or c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise Gap('候选库完整性或外键检查未过')
            c.execute('ATTACH DATABASE ? AS previous',(database.as_uri()+'?mode=ro',))
            for (table,) in c.execute("SELECT name FROM previous.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                quoted='"'+table.replace('"','""')+'"'
                if c.execute('SELECT * FROM previous.'+quoted+' EXCEPT SELECT * FROM main.'+quoted+' LIMIT 1').fetchone():
                    raise Gap('旧业务行发生变化，不发布')
        if metadata_builder is None:
            spec=importlib.util.spec_from_file_location('career_local_package_generator',generator)
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            metadata_builder=module.build
        with contextlib.redirect_stdout(io.StringIO()):
            metadata_builder(database.parent,database_path=candidate,output_dir=package_out)
        validate_candidate(candidate,result)
        validation_code=(validator(candidate) if validator else subprocess.run(
            [sys.executable,str(ROOT/'skills/zhiqu/scripts/validate_data.py')],capture_output=True,env=dict(os.environ,ZHIQU_EMPLOYMENT_DB=str(candidate)),
            timeout=max(1,deadline.remaining())).returncode)
        dump(output/'validation.json',{'project_public_csv_exit_code':validation_code,'candidate_rows_read_back':True,'old_rows_unchanged':True,'new_rows':inserted,'new_verifications':verifications})
        if validation_code:
            raise Gap('项目数据检查未通过，仅留候选')
        sealed()
        if file_sha(database)!=initial:
            raise Gap('正式库已被其他任务改变，不发布')
        deadline()
        if deadline.remaining()<15:
            raise Gap('剩余时间不足安全发布，只留候选')
        # The only irreversible window is atomic replacement; keep the old inode
        # and all old dictionary files until this local transaction completes.
        old_metadata = {name:(database.parent/name).read_bytes() if (database.parent/name).exists() else None
                        for name in ('datapackage.json','README.md','CHANGELOG.md','VERSION')}
        shutil.copyfile(database, rollback)
        receipt={'published':True,'rows':inserted,'version':version,'old_sha256':initial,
                 'sha256':file_sha(candidate),'rollback':str(rollback),'old_rows_unchanged':True}
        package_path=package_out/'datapackage.json'
        package=json.loads(package_path.read_text())
        package['x-database-file']=database.name
        for resource in package.get('resources',[]):
            original_path=resource.get('path')
            if original_path==candidate.name:resource['path']=database.name
            elif original_path=='sqlite:///file:'+str(candidate)+'?mode=ro&uri=true':
                resource['path']='sqlite:///file:'+str(database)+'?mode=ro&uri=true'
            elif isinstance(original_path,str)and str(candidate)in original_path:
                raise Gap('候选字典路径格式未识别，不发布失效入口')
        dump(package_path,package)
        for name,value in old_metadata.items():
            if value is not None:
                with (output/('before-'+name)).open('wb')as f:f.write(value);f.flush();os.fsync(f.fileno())
        dump(output/'publication-prepared.json',dict(receipt,database=str(database),
             old_metadata={k:digest(v)if v is not None else None for k,v in old_metadata.items()},
             new_metadata={k:file_sha(package_out/k) for k in old_metadata if (package_out/k).exists()}))
        try:
            os.replace(candidate,database)
            for name in old_metadata:
                p=package_out/name
                if p.exists():
                    target=database.parent/name
                    tmp=target.with_suffix(target.suffix+'.career-tmp')
                    tmp.write_bytes(p.read_bytes())
                    os.replace(tmp,target)
            dump(output/'publication.json',receipt)
        except BaseException:
            restore=output/'restore-employment.sqlite'
            shutil.copyfile(rollback,restore)
            os.replace(restore,database)
            for name,value in old_metadata.items():
                if value is not None:(database.parent/name).write_bytes(value)
                else:(database.parent/name).unlink(missing_ok=True)
            raise
        return receipt


def validate_candidate(candidate, result):
    """Read every proposed new value back; validate the actual candidate, not CSVs."""
    with sqlite3.connect(Path(candidate).resolve().as_uri()+'?mode=ro',uri=True)as c:
        for bundle in result['candidates']:
            source=bundle['source']
            stored_source=c.execute('SELECT '+','.join(SOURCE_COLS)+' FROM source WHERE source_id=?',(source['source_id'],)).fetchone()
            if stored_source is None or any(stored_source[SOURCE_COLS.index(key)]!=source[key]for key in ('grade','publisher','title','landing_url','file_url','archive_sha256')):
                raise Gap('候选实际来源回读不同')
            if not official(source['landing_url'])or not publisher_matches(source['landing_url'],source['publisher']):
                raise Gap('候选官方身份未绑定')
            public_text(source['title'])
            for row in bundle['rows']:
                privacy(row)
                q=result['request']
                if (row['region']!=q['region']or row['year']not in q['years']or row['stage']!=q['stage']or
                    q['direction']not in row['position']or set(row['fields'])!=set(q['layers'])or
                    (q['stage']=='internship'and '实习'not in row['position'])or
                    (q['stage']=='graduate'and row.get('stage_raw')not in {'校园招聘','应届毕业生招聘'})):
                    raise Gap('候选超出本次城市、年度、岗位或阶段')
                record_id='career-demand-'+digest(json.dumps([source['source_id'],row,result['request']['direction']],sort_keys=True,ensure_ascii=False).encode())
                stored=c.execute('SELECT region,year,note,excerpt FROM recruitment_notice WHERE record_id=? AND source_id=?',(record_id,source['source_id'])).fetchone()
                if stored is None or stored[:2]!=(row['region'],row['year']):raise Gap('候选范围回读不同')
                meta=json.loads(stored[2]);proof=json.loads(stored[3])
                if any(meta.get(k)!=value for k,value in {'stage':q['stage'],'direction':q['direction'],'position':row['position'],'stage_raw':row['stage_raw']}.items()):
                    raise Gap('候选阶段或方向回读不同')
                if meta['fields']!=row['fields']or proof.get('fields')!=row['fields']or proof.get('src_row')!=row['src_row']or proof.get('sha256')!=source['archive_sha256']:
                    raise Gap('候选原值或原行定位回读不同')
                if proof.get('dual_read_equal')is not True or proof.get('sample_passed')is not True:raise Gap('候选核对证明缺失')
                if proof.get('kind')=='position-body-v1':
                    for key in ('year_basis','year_scope','published','recruitment_year','region_raw','region_basis','position_locator','field_locators','visibility_basis'):
                        if key in row and meta.get(key)!=row[key]:
                            raise Gap('具体岗位口径或定位回读不同')
                    if proof.get('src_table')!=row['src_table']:
                        raise Gap('具体岗位正文定位回读不同')
                    from career_positions import validate_position_proof
                    validate_position_proof(row, proof)
                    continue
                n=proof.get('original_rows')
                sample=proof.get('sample_rows')
                if type(n)is not int or n<1 or not isinstance(sample,list)or any(type(x)is not int or not 2<=x<=n+1 for x in sample)or len(set(sample))<min(n,max(3,math.ceil(n*.03))):
                    raise Gap('候选抽核数或行定位不满足原表规则')


def publication_state(output, database):
    """A killed/expired worker is not proof of non-publication. Never guess."""
    output=Path(output)
    committed=output/'publication.json'
    prepared=output/'publication-prepared.json'
    if not committed.exists()and not prepared.exists():return '未发布'
    marker=json.loads((committed if committed.exists()else prepared).read_text())
    with Path(database).open('rb')as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    if committed.exists()and actual==marker['sha256']:return '已发布（小结未完成，保留提交记录）'
    if actual==marker['old_sha256']:return '未发布（原库仍在）'
    return '发布状态待核（保留事务记录及回滚，不重新取文或覆盖）'


def recover_publication(output, database):
    """After worker termination restore an incomplete own transaction, under lock.

    Never overwrite any DB/metadata not matching the prepared old/new hashes.
    Keep the verified rollback; do not rename or delete another writer's files.
    """
    import fcntl
    import shutil
    output=Path(output).resolve();database=Path(database).resolve()
    prepared=output/'publication-prepared.json'
    if not prepared.exists():return publication_state(output,database)
    with database.with_suffix('.career-demand.lock').open('a')as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return '发布状态待核（另一发布任务正在持锁）'
        marker=json.loads(prepared.read_text())
        if marker.get('database')!=str(database):return '发布状态待核（事务目标不符）'
        def sha(path):
            with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
        actual=sha(database)
        committed=output/'publication.json'
        if committed.exists() and actual==marker['sha256'] and all(
            (database.parent/name).is_file()and sha(database.parent/name)==value for name,value in marker['new_metadata'].items()):
            return '已发布（小结未完成，保留提交记录）'
        if actual not in {marker['sha256'],marker['old_sha256']}:return '发布状态待核（正式库已有其他变化）'
        rollback=output/'rollback-employment.sqlite'
        if not rollback.is_file()or sha(rollback)!=marker['old_sha256']:return '发布状态待核（回滚校验未过）'
        for name,old in marker['old_metadata'].items():
            target=database.parent/name;before=output/('before-'+name)
            if old is not None and (not before.is_file()or sha(before)!=old):return '发布状态待核（旧字典凭据未过）'
            if old is not None and not target.exists():return '发布状态待核（原有字典已被其他任务移除）'
            if target.exists()and sha(target)not in {old,marker['new_metadata'].get(name)}:return '发布状态待核（字典已有其他变化）'
        restore=output/'recover-employment.sqlite'
        shutil.copyfile(rollback,restore);os.replace(restore,database)
        for name,old in marker['old_metadata'].items():
            target=database.parent/name
            if old is None:target.unlink(missing_ok=True)
            else:
                tmp=target.with_suffix(target.suffix+'.career-recover')
                shutil.copyfile(output/('before-'+name),tmp);os.replace(tmp,target)
        dump(output/'recovery.json',{'status':'未发布（已恢复原库及字典）','old_sha256':marker['old_sha256']})
        return '未发布（已恢复原库及字典）'


def text_summary(result):
    q = result['request']
    stage={'internship':'在校实习','graduate':'应届校招'}[q['stage']]
    lines = [f"{q['region']}｜{q['direction']}｜{stage}：缓存{len(result['cache'])}项，候选{sum(len(x['rows']) for x in result['candidates'])}行。",
             ('已通过候选验收并发布。'if result['published']else'已复用库内核验记录，本次无新发布。'if result['cache']and not result['candidates']else'候选尚未发布。'if result['candidates']else'未形成可发布候选。')+'格式两读和抽核不等于仍在招聘或本人合格。']
    for row in result['cache']:
        lines.append(f"{row['year']} {row['metadata'].get('year_scope','')} {row['metadata']['position']} {FIELDS[row['field']]}：{row['value'] or '来源未提供'}｜官方｜{row['publisher']}｜{row['source_id']}")
        lines.append('来源：'+row['landing_url'])
    for bundle in result['candidates']:
        source = bundle['source']
        lines.append(f"来源：{source['publisher']}｜{source['title']}｜{source['landing_url']}")
        for row in bundle['rows']:
            lines.append(f"{row['year']} {row.get('year_scope','')} {row['region']} {row['position']}："+'；'.join(FIELDS[k]+'：'+(v or '来源未提供') for k,v in row['fields'].items()))
    for gap in result['gaps']:
        lines.append('未取得：'+gap['reason']+'｜'+gap['url'])
    for cell in result.get('missing', []):
        lines.append(f"仍缺：{cell['year']} {FIELDS[cell['field']]}（仅表示本次限定入口没有取得）")
    return '\n'.join(lines)+'\n'


def main():
    if sys.argv[1:] == ['--worker']:
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(1)))
        request = json.load(sys.stdin)
        try:
            result = run_request(request)
            dump(Path(request['output'])/'result.json', result)
            if request.get('publish') and result['candidates']:
                publication=publish_result(result,request['database'],request['output'],Deadline(max(0,request['seconds']-(time.monotonic()-request['started']))))
                result['published']=publication['published']
            dump(Path(request['output'])/'result.json', result)
            (Path(request['output'])/'README.md').write_text(text_summary(result))
        except Exception:
            dump(Path(request['output'])/'stopped.json', {'status':recover_publication(request['output'],request['database']),'reason':'输入、期限或安全检查失败'})
            raise SystemExit(1)
        return
    ap = argparse.ArgumentParser(description='按城市、岗位和年份限时查库/取官方招聘原文，不接触登录或名单')
    ap.add_argument('--region', required=True)
    ap.add_argument('--direction', required=True)
    ap.add_argument('--years', nargs='+', type=int, default=[dt.date.today().year])
    ap.add_argument('--stage', choices=['internship','graduate'], default='internship')
    ap.add_argument('--layers', nargs='+', choices=list(FIELDS), default=list(FIELDS))
    ap.add_argument('--entries', required=True, help='已定位的少量官方入口JSON：publisher/url；不猜站内路径')
    ap.add_argument('--minutes', type=float, default=5)
    ap.add_argument('--db', default=str(zhiqu_db.DEFAULTS['employment']))
    ap.add_argument('--output', required=True)
    ap.add_argument('--publish',action='store_true',help='候选验收通过后原子发布；保留本轮一份回滚')
    args = ap.parse_args()
    if not math.isfinite(args.minutes) or args.minutes <= 0 or not 1 <= len(set(args.years)) <= 3 or any(y<2000 or y>2100 for y in args.years):
        ap.error('限时须为正数，年份最多3个且在2000—2100')
    request = vars(args)
    request['database'] = request.pop('db')
    request['seconds'] = request.pop('minutes')*60
    request['entries'] = json.loads(Path(args.entries).read_text())
    request['started']=time.monotonic()
    if not isinstance(request['entries'], list) or len(request['entries']) > 6:
        ap.error('只接受最多6个已定位官方入口')
    privacy(request)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    worker = subprocess.Popen([sys.executable, __file__, '--worker'], stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        worker.communicate(json.dumps(request).encode(), timeout=request['seconds'])
    except subprocess.TimeoutExpired:
        os.killpg(worker.pid, signal.SIGTERM)
        try:
            worker.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(worker.pid, signal.SIGKILL)
            worker.wait()
        dump(output/'stopped.json', {'status':recover_publication(output,request['database']),'reason':'整次任务期限已到，子进程已结束'})
    if worker.returncode and not (output/'stopped.json').exists():
        dump(output/'stopped.json',{'status':recover_publication(output,request['database']),'reason':'工作进程异常退出，已核对事务状态'})
    summary = output/'README.md'
    stopped=output/'stopped.json'
    print(summary.read_text() if summary.exists() else
          json.loads(stopped.read_text())['status']+'，见输出目录停止记录。'if stopped.exists()else'本次未完成，见输出目录。')
    if worker.returncode:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
