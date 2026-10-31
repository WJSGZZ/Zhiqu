"""Bounded public HZNU 2026 catalogue adapter. No remote JS execution.

The two JS fingerprints bind reviewed route/API/column semantics, not business
values. A changed frontend fails closed until its public mapping is reviewed.
Only a full six-digit requested programme is supported. Bodies stay in the
on-demand worker's existing RAM cache; the adapter never fetches or writes files.
"""
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
from lxml import html
from kaoyan_adapters import NeedsReview, fingerprint, samples, state
from kaoyan_tables import _decode, _lxml_text
from ingest_kaoyan_lines import dump, privacy

PARENT = 'https://yjs.hznu.edu.cn/c/2025-09-28/3113195.shtml'
SERVICE = 'https://yjsfw.hznu.edu.cn/open/zsss/ZsssTksList?zsnf=2026'
APP = 'https://yjsfw.hznu.edu.cn/open/js/app.0e2179d6.js'
CHUNK = 'https://yjsfw.hznu.edu.cn/open/js/chunk-60d44128.ee0ece6a.js'
DICTIONARY = 'https://yjsfw.hznu.edu.cn/dataapi/open/zsss/queryZyList?mllx=0&zsnf=2026'
APP_SHA = '7264db13f962f5dc490380a684c6072092398dd01ee100cd2bbd357c7b482be8'
CHUNK_SHA = '3e8fde1739f643e7b0d1f4227a243488187eb120d89898a9e79cf52c63f996db'
SCHOOL = '杭州师范大学'
IID = '4133010346'
KEYS = ('id zsnf zyId yjfxXh yjfx xxfs xwlb tkme tkmesm kskm ejxkdm ejxkmc '
        'sysOrgCode_dictText zyId_dictText xxfs_dictText xwlb_dictText ksfs_dictText '
        'tydxs_dictText jsggjh_dictText tkbz').split()
NODE = '''let b="";process.stdin.on("data",x=>b+=x);process.stdin.on("end",()=>{try{console.log(JSON.stringify(JSON.parse(b)));}catch(e){process.exit(2);}});'''


def sha(body):
    return hashlib.sha256(body).hexdigest()


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise NeedsReview('公开目录JSON含重复键，整份不入库')
        out[key] = value
    return out


def dual_json(body, deadline):
    """Independent standard-library and Node parsers, not two json.loads calls."""
    deadline()
    if len(body) > 8_000_000 or not shutil.which('node'):
        raise NeedsReview('公开目录缺少独立JSON读法或响应过大，未入库')
    try:
        first = json.loads(body, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        run = subprocess.run(['node', '-e', NODE], input=body, capture_output=True,
                             timeout=min(8, max(.01, deadline.remaining())), check=True)
        second = json.loads(run.stdout)
        deadline()
        if first != second or not isinstance(first, dict) or first.get('success') is not True or not isinstance(first.get('result'), list):
            raise NeedsReview('公开目录接口未返回一致的成功列表，未入库')
        privacy(first)
        return first['result']
    except NeedsReview:
        raise
    except (ValueError, UnicodeError, subprocess.SubprocessError):
        raise NeedsReview('公开目录JSON双读未通过，整份不入库') from None


def _body(bodies, url):
    found = bodies.get(url)
    if not found or not found[0]:
        return None
    item = found[0]
    # Never authorize the payload by the requested URL after a redirect.
    if item.get('url', url) != url:
        raise NeedsReview('公开目录来源跳转改变，须重新核对入口')
    return item['body']


def _text(value, *, required=False):
    if value is None and not required:
        return ''
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > 2000:
        raise NeedsReview('公开目录文字字段不明确，未入库')
    return value


def _result(rows, digest, api, identity, title, chain):
    today = dt.date.today().isoformat(); sid = 'src-ondemand-' + digest[:24]
    source = dict(source_id=sid, grade='官方', publisher=SCHOOL, title=title,
                  landing_url=PARENT, file_url=api, published='', retrieved=today,
                  method='公开JSON：Python/Node独立解码逐值一致；官方前端列映射绑定指纹；固定种子3%至少3行（不足全核）',
                  archive_sha256=digest, archive_path='', archive_status='已核后删除（有指纹）',
                  wayback_url='', note='仅所问专业目录；拟招生名额含推免，专项名额范围未明确；原件RAM处理后删除。'+dump(chain),
                  citation=f'{SCHOOL}，{title}，2026，{api}，取得日期{today}', license='未注明', producer_revision='')
    output=[]
    for i, raw in enumerate(rows):
        value={k:raw.get(k) for k in KEYS}
        for k in ['id','zyId','yjfxXh','yjfx','ejxkdm','ejxkmc','sysOrgCode_dictText','xxfs_dictText','xwlb_dictText','ksfs_dictText','kskm']:
            _text(value[k], required=True)
        if not re.fullmatch(r'[0-9a-f]{32}', value['id']) or not re.fullmatch(r'[0-9A-Fa-f]{32}', value['zyId']):
            raise NeedsReview('公开目录行标识变化，未入库')
        if (value['xxfs'],value['xxfs_dictText']) != ('1','全日制') or (value['xwlb'],value['xwlb_dictText']) != ('1','专业学位') or value['ksfs_dictText'] != '统考':
            raise NeedsReview('公开目录层次或考试方式未知，未入库')
        planned=value['tkme']
        if planned is not None and (type(planned) is not int or not 0 <= planned <= 100000):
            raise NeedsReview('公开目录拟招生名额不是明确整数，未入库')
        for k in ['tkbz','tkmesm','tydxs_dictText','jsggjh_dictText']:
            _text(value[k])
        locator={'json_path':f'$.result[{i}]','id':value['id'],'zyId':value['zyId'],
                 'year':2026,'program_code':value['ejxkdm'],'direction_code':value['yjfxXh'],'sha256':digest}
        extra={'locator':locator,'source_chain':chain,'original_plan_header':'拟招生名额(含推免)',
               'planned_note_raw':value['tkmesm'],'remarks_raw':value['tkbz'],
               'admission_route_raw':value['ksfs_dictText'],
               'special_eligibility_raw':{'是否接收退役大学生士兵':value['tydxs_dictText'],'是否接收少民骨干':value['jsggjh_dictText']},
               'special_plan_count_scope':'未明确，不从接收标志推算人数',
               'tuimian_raw':None,'tuimian_note':'公开列未独列推免人数；不使用未核标签的后端tmme字段'}
        output.append(dict(record_id=fingerprint([sid,value['id']])[:32],institution_id=identity['institution_id'],school=SCHOOL,
            college=value['sysOrgCode_dictText'],program_code=value['ejxkdm'],program_name=value['ejxkmc'],degree_type=value['xwlb_dictText'],
            year=2026,study_mode=value['xxfs_dictText'],direction=value['yjfx'],direction_raw=value['yjfxXh']+' '+value['yjfx'],
            special_plan=None,scope='拟招生名额(含推免)；专项名额范围未明确',scope_raw='拟招生名额(含推免)；'+(value['tkmesm'] or ''),
            source_id=sid,src_row=dump(locator),src_page=None,src_table='公开招生目录JSON result',locator_method='公开JSON双独立解码',locator_status='核验通过',
            planned=planned,planned_raw='' if planned is None else str(planned),planned_scope='含推免；专项名额范围未明确',subjects=value['kskm'],
            extra_json=dump(extra),value_status=dump({'planned':state(planned,'前端原列“拟招生名额(含推免)”；'+(value['tkmesm'] or '')),
            'tuimian':state(None)}),tuimian=None))
    indices=samples(len(output));checked=[]
    for i in indices:
        row=output[i]
        checked.append(dict(sample_id=fingerprint(['sample',row['record_id']])[:32],domain='考研',table_name='ky_program_year',row_key=row['record_id'],
            field='planned',db_value=str(row['planned']),official_value=str(rows[i]['tkme']),official_source_id=sid,verdict='一致',checked_on=today,
            reason='独立JSON读法逐值一致；原API取值与已核前端列映射抽核，非OCR准确率认证',excerpt='拟招生名额(含推免)：'+row['planned_raw'],
            locator=row['src_row'],reviewer='双读程序'))
    manifest={'sources':[source],'rows':output,'samples':checked};privacy(manifest)
    return {'manifest':manifest,'rows':len(output),'pending':[],'proofs':[{'source_sha256':digest,'readers':['Python json','Node JSON.parse'],
            'dual_read_equal':True,'source_rows':len(rows),'included_rows':len(output),'sample_count':len(indices),'sample_indices':indices,
            'scope':'仅所问六位专业，不认证全校目录','column_mapping_sha256':CHUNK_SHA,'original_plan_header':'拟招生名额(含推免)'}]}


def advance(body, url, identity, year, layer, programs, bodies, deadline):
    """Return None (not this adapter), a next public URL, or a reviewed manifest.

    All returned URLs are derived from the real, pinned anonymous frontend.
    The caller applies its normal domain, known-stop, deadline and fetch guards.
    """
    if layer!='catalog' or year!=2026 or identity.get('name')!=SCHOOL or identity.get('institution_id')!=IID:
        return None
    relevant={PARENT,SERVICE,APP,CHUNK,DICTIONARY}
    if url not in relevant and not url.startswith('https://yjsfw.hznu.edu.cn/dataapi/open/zsss/zsml?'):
        return None
    if len(programs)!=1 or not re.fullmatch(r'\d{6}',programs[0]):
        raise NeedsReview('该公开目录适配须明确一个六位专业；不由四位前缀猜专业')
    def need(target):
        return {'next_urls':[target],'reason':'已确认公开目录链，继续取所问专业的匿名目录数据'}
    parent=_body(bodies,PARENT)
    if parent is None:return need(PARENT)
    root=html.fromstring(_decode(parent))
    titles=[_lxml_text(n)for n in root.xpath('//title|//h1|//h2')]
    expected='杭州师范大学2026年硕士研究生招生简章'
    business=[t.strip()for t in titles if re.search('招生|目录|简章',t)and re.search(r'20\d{2}',t)]
    if not business or any(t!=expected for t in business):
        raise NeedsReview('目录父公告学校、年份或硕士层次变化，未入库')
    links=[a for a in root.xpath('//a[@href]')if a.get('href')==SERVICE and _lxml_text(a).strip()=='杭州师范大学2026年硕士研究生招生专业目录（点击查看）']
    if not links:raise NeedsReview('父公告未确认该届公开目录链接，未入库')
    service=_body(bodies,SERVICE)
    if service is None:return need(SERVICE)
    scripts=html.fromstring(_decode(service)).xpath('//script/@src')
    if '/open/js/app.0e2179d6.js'not in scripts:raise NeedsReview('公开目录前端入口变化，须重新核对，不猜接口')
    app=_body(bodies,APP)
    if app is None:return need(APP)
    if sha(app)!=APP_SHA:raise NeedsReview('公开目录路由/API版本变化，须重新核对，不执行JS')
    chunk=_body(bodies,CHUNK)
    if chunk is None:return need(CHUNK)
    if sha(chunk)!=CHUNK_SHA:raise NeedsReview('公开目录列映射版本变化，须重新核对，不猜字段')
    dictionary=_body(bodies,DICTIONARY)
    if dictionary is None:return need(DICTIONARY)
    matches=[r for r in dual_json(dictionary,deadline)if isinstance(r,dict)and r.get('dm')==programs[0]]
    if len(matches)!=1 or not re.fullmatch(r'[0-9A-Fa-f]{32}',str(matches[0].get('id',''))):
        raise NeedsReview('公开目录专业字典无唯一代码锚点，未入库')
    target=matches[0];name=_text(target.get('mc'),required=True)
    api='https://yjsfw.hznu.edu.cn/dataapi/open/zsss/zsml?mllx=0&zsnf=2026&zyId='+target['id']+'&pageNo=1&pageSize=10'
    payload=_body(bodies,api)
    if payload is None:return need(api)
    rows=dual_json(payload,deadline)
    if not rows:raise NeedsReview('公开目录所问专业未返回方向，未入库')
    ids=[];scopes=[]
    for row in rows:
        if not isinstance(row,dict)or row.get('zsnf')!='2026'or row.get('zyId')!=target['id']or row.get('ejxkdm')!=programs[0]or row.get('ejxkmc')!=name or row.get('zyId_dictText')!=name:
            raise NeedsReview('公开目录逐行学校链、年份或专业锚点不一致，整份不入库')
        ids.append(row.get('id'))
        scopes.append(tuple(row.get(k)for k in ['sysOrgCode_dictText','ejxkdm','yjfxXh','xxfs','xwlb','ksfs_dictText']))
    if len(set(scopes))!=len(scopes):raise NeedsReview('公开目录重复业务方向，即使行标识不同也不重复存，整份待核')
    if len(set(ids))!=len(ids):raise NeedsReview('公开目录重复方向标识，整份不入库')
    chain=[{'url':u,'sha256':sha(_body(bodies,u))}for u in [PARENT,SERVICE,APP,CHUNK,DICTIONARY]]
    return _result(rows,sha(payload),api,identity,'杭州师范大学2026年硕士研究生招生专业目录（'+programs[0]+'）',chain)
