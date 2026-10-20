#!/usr/bin/env python3
"""本机画像存档，不联网，不推断本人没说的资格。

new-id grad 2027 --mode formal       分配并占用案例号
 ingest 2027-YJ-0001 pasted.json     原样存档（默认根目录 cases/）
 latest 2027-YJ-0001                返回最新版本与原文
 diff 2027-YJ-0001                  按题目 id 对比最近两版
 parse <案例目录> [--replace]        优先 JSON 生成字段；旧文字仍需人工解析
 report 2027-YJ-0001 2027-YJ-0001-report.pdf  登记本机报告版本，不生成报告

各命令可用 --root 指定本机案例根目录；真实资料不得进入受版本管理的目录。
"""
import argparse
import base64
import gzip
import io
import os
import hmac
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[3]
HEADERS = {'gaokao':'【高考志愿 · 自我盘点】','grad':'【读研 · 自我盘点】','career':'【求职 · 自我盘点】'}
LABELS = {'gaokao':'高考志愿','grad':'读研','career':'求职'}
CODES = {'GK':'gaokao','YJ':'grad','QZ':'career'}
CASE_ID = re.compile(r'^\d{4}-(GK|YJ|QZ)-(?:\d{4}|[SR]\d{2})$')
ID = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')
FIELD_MAP = {
 'gaokao': [('年份','fact','gk_year'),('省份','fact','province'),('位次','fact','rank'),('选科','fact','kelei','subjects'),('批次','fact','batch'),('体检','constraint','body'),('学费上限','constraint','money','four_year_budget'),('调剂态度','preference','tiaoji'),('优先级','preference','priority')],
 'grad': [('年级','fact','grade'),('专业','fact','major'),('院校层次','fact','school_tier'),('均分或排名','fact','gpa','rank_in_major'),('英语','fact','eng','eng_score'),('数学基础','fact','math','math_courses'),('读研动机','self_judgment','why','why_main'),('目标方向','preference','dir_want'),('预算','constraint','money','finance_note'),('能否二战','constraint','worst','earning_year'),('目标地区','preference','city_pref','city','home_province','near_home')],
 'career': [('学历','fact','degree'),('专业','fact','major_name','major_code','minor_major','dual_major'),('毕业时间','fact','grad_time'),('求职阶段','fact','job_stage'),('经历','fact','work_exp','employment_history'),('证书','fact','certs','certs_detail'),('目标岗位','preference','tgt1','tgt2','tgt3'),('收入底线','constraint','min_salary','salary_known'),('城市','preference','city_first','city_second','city_third'),('单位类型偏好','preference','org_type'),('户籍','fact','hukou','origin_province','hukou_location','hukou_disclosure'),('政治面貌','fact','political'),('多快需要收入','constraint','income_deadline','income_deadline_status')]
}


def sha(raw):return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def dump(path, data):
    path=Path(path)
    # Replace only the registry/working parse, never archived submissions.
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as out:
        json.dump(data,out,ensure_ascii=False,indent=2);out.write('\n')
    tmp.chmod(0o600);tmp.replace(path)


def check_id(case_id):
    match=CASE_ID.fullmatch(case_id)
    if not match:raise ValueError('案例号须为 年份-GK/YJ/QZ-四位序号（模拟可用 S/R 加两位序号）')
    return CODES[match[1]]


def timestamp(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)',value):
        raise ValueError('filled_at 须为含时区的 ISO 日期时间')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def archive_filename(stamp, suffix='.json'):
    """Filesystem-safe timestamp; preserve fractions and offset, accept legacy ISO input."""
    timestamp(stamp)
    if suffix not in ('.json', '.txt'):raise ValueError('画像存档只允许 JSON 或文字')
    stamp=stamp.replace('Z','+00:00')
    return stamp[:10]+'T'+stamp[11:19].replace(':','-')+stamp[19:].replace(':','')+suffix


def parse_filename_stamp(name):
    """Read both historical ISO filenames and Windows-safe archive filenames."""
    stem=Path(name).stem
    if re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d(?:\.\d+)?[+-]\d{4}',stem):
        stem=stem[:10]+'T'+stem[11:19].replace('-',':')+stem[19:-5]+stem[-5:-2]+':'+stem[-2:]
    timestamp(stem)
    return stem


def valid_answer(value):
    if isinstance(value,str):return bool(value.strip())
    if isinstance(value,list):return bool(value) and all(isinstance(x,str) and x.strip() for x in value) and len(value)==len(set(value))
    if isinstance(value,dict):return bool(value) and all(isinstance(k,str) and k.strip() and (isinstance(v,str) or isinstance(v,list)) and valid_answer(v) for k,v in value.items())
    return False


INTEGRITY_ERROR = '画像可能被改动或不完整，请让对方重新复制'
MAX_PROFILE_BYTES = 8 * 1024 * 1024


def canonical(data):
    """Sorted UTF-16 keys, compact UTF-8, JSON primitives (matching the webpage)."""
    def ordered(value):
        if isinstance(value, dict):return {k:ordered(value[k]) for k in sorted(value,key=lambda k:k.encode('utf-16-be'))}
        if isinstance(value, list):return [ordered(v) for v in value]
        return value
    return json.dumps(ordered(data),ensure_ascii=False,separators=(',',':'),allow_nan=False)


def checksum(data):
    return sha(canonical({k:v for k,v in data.items() if k!='checksum'}))


def integrity(data):
    if 'checksum' not in data:
        # Current-shaped messages must not downgrade to unchecked by deleting the hash.
        if any(k in data for k in ('counts','collapsed')) or any('status' in i for sec in data.get('sections',[]) for i in sec.get('items',[])):
            raise ValueError(INTEGRITY_ERROR)
        return '无校验'
    try:
        if not isinstance(data['checksum'],str) or not hmac.compare_digest(data['checksum'],checksum(data)):raise ValueError()
        entries=[i for sec in data['sections'] for i in sec['items']]
        if any(i.get('status') not in ('已答','未填') for i in entries):raise ValueError()
        if any(('a' not in i or not valid_answer(i['a'])) if i['status']=='已答' else 'a' in i for i in entries):raise ValueError()
        counts=data['counts']
        if set(counts)!={'visible','answered'} or any(type(v) is not int for v in counts.values()):raise ValueError()
        if counts!={'visible':len(entries),'answered':sum(i['status']=='已答' for i in entries)}:raise ValueError()
        ids=[i['id'] for i in entries];hidden=data['collapsed']
        if not isinstance(hidden,list) or any(not isinstance(x,str) or not ID.fullmatch(x) for x in hidden) or len(set(hidden))!=len(hidden) or set(ids)&set(hidden):raise ValueError()
        if any('required' in i and i['required'] is not True for i in entries):raise ValueError()
    except (KeyError,TypeError,ValueError,AttributeError) as exc:raise ValueError(INTEGRITY_ERROR) from exc
    return '校验通过'


def crypto_modules():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:raise ValueError('接收密文或生成钥匙需要 cryptography，请运行 python3 -m pip install cryptography') from exc
    return hashes,serialization,padding,rsa,AESGCM


def keygen(private_key,public_config,recipient_name='知衢顾问',hostname='wjsgzz.github.io'):
    private_key=Path(private_key).expanduser().resolve();public_config=Path(public_config)
    if private_key.is_relative_to(REPO):raise ValueError('私钥必须放在仓库以外')
    if private_key.exists():raise ValueError('私钥已存在，拒绝覆盖；更换钥匙前先备份旧钥匙')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+',hostname):raise ValueError('hostname 只填域名，不带协议和路径')
    hashes,serialization,padding,rsa,AESGCM=crypto_modules()
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    private_key.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(private_key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as out:out.write(pem)
    public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    config={'name':recipient_name,'hostname':hostname.lower(),'spki':base64.b64encode(public).decode()}
    public_config.parent.mkdir(parents=True,exist_ok=True)
    public_config.write_text('// Public recipient only. Keep the private key outside the repository.\nwindow.ZHIQU_RECIPIENT = '+json.dumps(config,ensure_ascii=False,indent=2)+';\n')
    return {'private_key':str(private_key),'public_config':str(public_config),'notice':'请立即把私钥备份到安全的离线位置；丢失后未解密消息无法恢复。'}


def decrypt_profile(raw,private_key=None):
    hashes,serialization,padding,rsa,AESGCM=crypto_modules()
    path=private_key or os.environ.get('ZHIQU_PRIVATE_KEY')
    if not path:raise ValueError('请用 --private-key 或 ZHIQU_PRIVATE_KEY 指定仓库外私钥')
    try:
        encoded=raw.strip()[4:]
        if len(encoded)>MAX_PROFILE_BYTES or not re.fullmatch(r'[A-Za-z0-9_-]+',encoded):raise ValueError()
        blob=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4));n=int.from_bytes(blob[:2],'big')
        if n not in (256,384,512) or len(blob)<2+n+12+16:raise ValueError()
        key=serialization.load_pem_private_key(Path(path).expanduser().read_bytes(),password=None)
        secret=key.decrypt(blob[2:2+n],padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        zipped=AESGCM(secret).decrypt(blob[2+n:14+n],blob[14+n:],b'ZQ1')
        with gzip.GzipFile(fileobj=io.BytesIO(zipped)) as stream:plain=stream.read(MAX_PROFILE_BYTES+1)
        if len(plain)>MAX_PROFILE_BYTES:raise ValueError()
        text=plain.decode('utf-8');data=json.loads(text)
        if not isinstance(data,dict) or 'checksum' not in data:raise ValueError()
        validate(data)
        return text
    except Exception as exc:raise ValueError(INTEGRITY_ERROR+'（解密或解压失败，请核对私钥）') from exc


def validate(data):
    if isinstance(data,dict):integrity(data)
    if not isinstance(data,dict) or data.get('schema')!=1 or data.get('zhiqu') not in HEADERS:raise ValueError('画像须为含 zhiqu、schema=1 的 JSON 对象')
    if not isinstance(data.get('问卷'),str) or not data['问卷'].strip():raise ValueError('缺问卷名称')
    if LABELS[data['zhiqu']].replace('志愿','') not in data['问卷']:raise ValueError('问卷名称与类型不一致')
    if not isinstance(data.get('form'),str) or not data['form'].strip():raise ValueError('缺题目指纹 form')
    timestamp(data.get('filled_at'))
    if not isinstance(data.get('sections'),list):raise ValueError('sections 须为列表')
    checked='checksum' in data
    seen=set()
    for section in data['sections']:
        if not isinstance(section,dict) or not isinstance(section.get('title'),str) or not isinstance(section.get('items'),list):raise ValueError('节名或 items 格式错误')
        for item in section['items']:
            if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not ID.fullmatch(item['id']) or item['id'] in seen:raise ValueError('题目 id 须为不重复的稳定英文名')
            if not isinstance(item.get('q'),str) or not item['q'].strip() or (not checked or item.get('status')=='已答') and not valid_answer(item.get('a')):raise ValueError('题目须有原文与已作答答案')
            if item.get('followup_of') and item['followup_of'] not in seen:raise ValueError('追问须跟在所属题后面，followup_of 须已出现')
            seen.add(item['id'])
    if not isinstance(data.get('rank'),list) or not all(isinstance(x,str) for x in data['rank']) or len(data['rank'])!=len(set(data['rank'])):raise ValueError('rank 须为无重复字符串列表')
    if not isinstance(data.get('derived'),dict) or set(data['derived'])-{'bazi'} or ('bazi' in data['derived'] and not isinstance(data['derived']['bazi'],str)):raise ValueError('derived 只接受排盘文字 bazi')
    if not checked and not isinstance(data.get('未填的必答题'),list) or not checked and not all(isinstance(x,str) for x in data['未填的必答题']):raise ValueError('未填的必答题须为题目原文列表')
    priority=next((i.get('a',[]) for sec in data['sections'] for i in sec['items'] if i['id']=='priority'),data['rank'])
    if priority!=data['rank']:raise ValueError('排序题与 rank 不一致')
    return data


def parse_profile(raw):
    text=raw.lstrip('\ufeff \n\r')
    if text.startswith('{'):
        try:return validate(json.loads(text))
        except json.JSONDecodeError as exc:raise ValueError(INTEGRITY_ERROR) from exc
    kind=next((k for k,h in HEADERS.items() if text.startswith(h)),None)
    if not kind:raise ValueError('画像须为 JSON 或旧版自我盘点文字')
    # Compatibility for the short-lived prose + answers data-line format.
    found=[]
    for line in text.splitlines():
        if not line.strip().startswith('{') or '"zhiqu"' not in line:continue
        try:old=json.loads(line)
        except json.JSONDecodeError as exc:raise ValueError('旧画像数据行损坏') from exc
        if old.get('zhiqu')!=kind:raise ValueError('画像标题与数据类型不一致')
        timestamp(old.get('filled_at'))
        answers=old.get('answers')
        if not isinstance(answers,dict) or any(not isinstance(answers.get(g),dict) for g in ('text','radio','check')):raise ValueError('旧 answers 格式错误')
        items=[];ids=set()
        for group in ('text','radio','check'):
            for key,value in answers[group].items():
                if not ID.fullmatch(key) or key in ids:raise ValueError('旧字段 id 重复或不合法')
                if group=='check' and not isinstance(value,list) or group!='check' and not isinstance(value,str):raise ValueError('旧作答类型错误')
                ids.add(key)
                if valid_answer(value):items.append({'id':key,'q':'旧问卷字段 '+key,'a':value})
        found.append(validate({'zhiqu':kind,'schema':1,'问卷':'知衢 · '+LABELS[kind]+' · 自我盘点','form':old.get('form'),'filled_at':old['filled_at'],'sections':[{'title':'旧版结构化作答','items':items}],'rank':answers.get('rank',[]),'derived':{},'未填的必答题':[]}))
    if len(found)>1:raise ValueError('发现多条画像数据，每次只存一版')
    return found[0] if found else None


def private_root(root):
    root=Path(root).resolve()
    if root.is_relative_to(REPO):
        probe=subprocess.run(['git','check-ignore','--quiet',str((root/'cases.json').relative_to(REPO))],cwd=REPO,capture_output=True)
        if probe.returncode:raise ValueError('真实画像只能写入本机忽略目录；先在 .git/info/exclude 排除案例目录')
    return root


def folder_for(root,case_id,writing=False):
    check_id(case_id);root=private_root(root) if writing else Path(root).resolve();folder=root/case_id
    if folder.is_symlink() or (folder/'profiles').is_symlink():raise ValueError('案例或 profiles 不能是符号链接')
    return folder


@contextmanager
def registry(root):
    root=private_root(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=root/'.cases.lock'
    with lock.open('a') as handle:
        lock.chmod(0o600);fcntl.flock(handle,fcntl.LOCK_EX)
        path=root/'cases.json'
        data=json.loads(path.read_text()) if path.exists() else {'schema':1,'cases':{}}
        try:
            yield data
            dump(path,data)
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def register(reg,case_id,mode,created):
    kind=check_id(case_id)
    if mode not in ('formal','simulation'):raise ValueError('mode 须为 formal 或 simulation')
    return reg['cases'].setdefault(case_id,{'kind':kind,'mode':mode,'created_at':created,'profiles':[],'reports':[]})


def new_id(root,kind,year,mode='formal'):
    if kind not in HEADERS or not re.fullmatch(r'\d{4}',str(year)):raise ValueError('类型或年份错误')
    if mode not in ('formal','simulation'):raise ValueError('mode 须为 formal 或 simulation')
    code=next(k for k,v in CODES.items() if v==kind);prefix=f'{year}-{code}-'
    with registry(root) as reg:
        occupied=set(reg['cases'])|{p.name for p in Path(root).iterdir()}
        cid=next((prefix+f'{i:04d}' for i in range(1,10000) if prefix+f'{i:04d}' not in occupied),None)
        if cid is None:raise ValueError('该年度案例号已用完')
        now=datetime.now(timezone.utc).isoformat(timespec='microseconds');register(reg,cid,mode,now)
        folder=folder_for(root,cid,True);folder.mkdir(mode=0o700)
        dump(folder/'case.json',{'case_id':cid,'kind':kind,'mode':mode,'created_at':now})
        return cid


def snapshot_info(path,raw,data,case_id):
    return {'case_id':case_id,'file':'profiles/'+path.name,'filled_at':data['filled_at'],'form':data['form'],'sha256':sha(raw),'status':'有数据','integrity':'校验通过' if 'checksum' in data else '无校验'}


def snapshots(folder):
    folder=Path(folder);versions=[]
    for path in (folder/'profiles').glob('*.json'):
        if path.is_symlink():raise ValueError('快照不能是符号链接')
        raw=path.read_text(encoding='utf-8');data=parse_profile(raw)
        if data and timestamp(parse_filename_stamp(path.name))!=timestamp(data['filled_at']):raise ValueError('画像文件名与 filled_at 不一致')
        registry_path=folder.parent/'cases.json'
        if registry_path.exists():
            record=json.loads(registry_path.read_text()).get('cases',{}).get(folder.name,{})
            expected=next((x['sha256'] for x in record.get('profiles',[]) if x['file']=='profiles/'+path.name),None)
            if expected and sha(raw)!=expected:raise ValueError('画像摘要不一致，存档可能被改写')
        if data is None or data['zhiqu']!=check_id(folder.name):raise ValueError('快照类型或案例号不一致')
        versions.append((timestamp(data['filled_at']),path.name,snapshot_info(path,raw,data,folder.name),raw))
    return sorted(versions,key=lambda x:(x[0],x[1]))


def ingest(root,case_id,raw,now=None,private_key=None):
    if raw.lstrip().startswith('ZQ1:'):raw=decrypt_profile(raw.lstrip(),private_key)
    kind=check_id(case_id);data=parse_profile(raw)
    if data and data['zhiqu']!=kind:raise ValueError('案例号与画像类型不一致')
    if data is None and not raw.lstrip('\ufeff \n\r').startswith(HEADERS[kind]):raise ValueError('案例号与文字画像类型不一致')
    filled=data['filled_at'] if data else (now or datetime.now(timezone.utc)).isoformat(timespec='microseconds')
    timestamp(filled)
    folder=folder_for(root,case_id,True)
    with registry(root) as reg:
        folder.mkdir(parents=True,exist_ok=True,mode=0o700);archive=folder/'profiles';archive.mkdir(exist_ok=True,mode=0o700)
        case_path=folder/'case.json';case=json.loads(case_path.read_text()) if case_path.exists() else {'case_id':case_id,'kind':kind,'mode':'simulation' if re.search(r'-[SR]',case_id) else 'formal'}
        case.setdefault('case_id',case_id);case.setdefault('kind',kind)
        if case.get('case_id')!=case_id or case.get('kind',kind)!=kind:raise ValueError('案例登记与画像类型不一致')
        entry=register(reg,case_id,case.get('mode','formal'),datetime.now(timezone.utc).isoformat())
        is_json=raw.lstrip('\ufeff \n\r').startswith('{')
        suffix='.json' if is_json else '.txt';path=archive/archive_filename(filled,suffix)
        # Reuse an old filename for the same instant; never create a second version.
        for prior in archive.glob('*'+suffix):
            if timestamp(parse_filename_stamp(prior.name))==timestamp(filled):
                path=prior;break
        if path.exists() and (path.is_symlink() or path.read_text(encoding='utf-8')!=raw):raise ValueError('同一 filled_at 已有不同画像，拒绝覆盖')
        if not path.exists():
            with path.open('x',encoding='utf-8') as out:out.write(raw)
            path.chmod(0o600)
        if data and not is_json:
            converted=archive/archive_filename(filled)
            if converted.exists() and parse_profile(converted.read_text())!=data:raise ValueError('转换版已存在且不同，拒绝覆盖')
            if not converted.exists():dump(converted,data)
            path=converted
        info=snapshot_info(path,path.read_text(),data,case_id) if data else {'case_id':case_id,'file':'profiles/'+path.name,'filled_at':filled,'form':None,'sha256':sha(raw),'status':'无数据，需人工解析'}
        if not any(v['file']==info['file'] for v in entry['profiles']):entry['profiles'].append(info)
        entry['profiles'].sort(key=lambda x:timestamp(x['filled_at']))
        case['profile']=entry['profiles'][-1];dump(case_path,case)
        return info


def latest(root,case_id):
    folder=folder_for(root,case_id);versions=snapshots(folder)
    # Legacy text without parseable data remains an explicit manual gap.
    texts=list((folder/'profiles').glob('*.txt'))
    latest_text=max(texts,key=lambda p:timestamp(parse_filename_stamp(p.name)),default=None)
    if latest_text and (not versions or timestamp(parse_filename_stamp(latest_text.name))>versions[-1][0]):
        raw=latest_text.read_text();return {'case_id':case_id,'file':'profiles/'+latest_text.name,'filled_at':parse_filename_stamp(latest_text.name),'form':None,'sha256':sha(raw),'status':'无数据，需人工解析'},raw
    if not versions:
        if (folder/'profile.json').exists():
            path=folder/'profile.json';raw=path.read_text();data=parse_profile(raw)
            if data is None or data['zhiqu']!=check_id(case_id):raise ValueError('画像类型与案例号不一致')
            return {**snapshot_info(path,raw,data,case_id),'file':'profile.json'},raw
        raise ValueError('该案例还没有画像存档')
    return versions[-1][2],versions[-1][3]


def items(data):return {item['id']:item for sec in data['sections'] for item in sec['items']}


def diff(root,case_id,old=None,new=None):
    versions=snapshots(folder_for(root,case_id))
    texts=list((folder_for(root,case_id)/'profiles').glob('*.txt'))
    newest=max(texts,key=lambda p:timestamp(parse_filename_stamp(p.name)),default=None)
    if newest and versions and timestamp(parse_filename_stamp(newest.name))>versions[-1][0] and not old and not new:
        return {'case_id':case_id,'warnings':['无数据，需人工解析；旧文字只提供原文对照，不推断删除作答'],'added':{},'modified':{},'deleted':{},'old_text':versions[-1][3],'new_text':newest.read_text()}
    if len(versions)<2:raise ValueError('至少需要两版 JSON 画像才能比较；旧文字需人工对照')
    by={parse_profile(v[3])['filled_at']:v for v in versions};by.update({v[1]:v for v in versions});by.update({Path(v[1]).stem:v for v in versions});by.update({'profiles/'+v[1]:v for v in versions})
    try:a=by[old] if old else versions[-2];b=by[new] if new else versions[-1]
    except KeyError as exc:raise ValueError('指定快照不属于这个案例') from exc
    if a[1]==b[1]:raise ValueError('请选择两版不同画像')
    da,db=parse_profile(a[3]),parse_profile(b[3]);fa={k:v['a'] for k,v in items(da).items() if 'a' in v};fb={k:v['a'] for k,v in items(db).items() if 'a' in v}
    modified={k:{'old':fa[k],'new':fb[k]} for k in sorted(fa.keys()&fb.keys()) if fa[k]!=fb[k]}
    if da['rank']!=db['rank']:modified['rank']={'old':da['rank'],'new':db['rank']}
    return {'case_id':case_id,'old':a[1],'new':b[1],'warnings':['题目版本不同，部分题可能对不上'] if da['form']!=db['form'] else [],'added':{k:fb[k] for k in sorted(fb.keys()-fa.keys())},'modified':modified,'deleted':{k:fa[k] for k in sorted(fa.keys()-fb.keys())}}


class QuestionMap(HTMLParser):
    def __init__(self):super().__init__();self.stack=[];self.mapping={}
    def handle_starttag(self,tag,attrs):
        d=dict(attrs);qid=d.get('data-profile-id')
        if tag in ('input','textarea','select'):
            owner=next((x[1] for x in reversed(self.stack) if x[1]),None)
            if owner:self.mapping[d.get('name') or d.get('id')]=owner
        if tag not in ('input','meta','link','br','hr','img'):self.stack.append((tag,qid))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:self.stack=self.stack[:i];break


def build_parse(raw,kind):
    data=parse_profile(raw)
    if kind not in HEADERS or data and data['zhiqu']!=kind:raise ValueError('登记与画像类型不一致')
    if data is None:return None
    mapping=QuestionMap();mapping.feed((REPO/(kind+'.html')).read_text())
    given=items(data);fields=[];missing=[]
    for name,category,*keys in FIELD_MAP[kind]:
        refs=list(dict.fromkeys(mapping.mapping.get(k,k) for k in keys));values={k:given[k]['a'] for k in refs if k in given and 'a' in given[k]}
        if name=='优先级' and data['rank']:values={'priority':data['rank']}
        # A refused/unknown answer is retained verbatim but cannot become a known constraint.
        unknown={'不想说','不清楚','不确定','还没想','还没想好','不知道','不了解','还没定','还没和家里谈','要和家里商量','不确定，请帮我算'}
        def is_known(value):
            if isinstance(value,str):return value not in unknown
            if isinstance(value,list):return any(is_known(x) for x in value)
            if isinstance(value,dict):return any(is_known(x) for x in value.values())
            return False
        known={k:v for k,v in values.items() if is_known(v)}
        value=next(iter(known.values())) if len(known)==1 else known if known else None
        fields.append({'field':name,'category':category,'status':'given' if known else 'unknown','value':value,
                       'quote':json.dumps(values,ensure_ascii=False) if values else '',
                       'locator':'画像 JSON 题目：'+', '.join(values),'confirmed':False,'answer_refs':list(values)})
        if not known:missing.append({'field':name,'question':'请补充或确认「'+name+'」','impact':'相关判断保留未知，不能当作没有资格','ask':'本人'})
    return {'schema_version':1,'source':{'kind':kind,'form':data['form'],'filled_at':data['filled_at'],'raw_sha256':sha(raw)},'questionnaire':data,'fields':fields,'missing':[x['field'] for x in missing] if kind=='gaokao' else missing}


def active_profile(case_dir):
    folder=Path(case_dir)
    if (folder/'profiles').exists():
        try:return latest(folder.parent,folder.name)[1]
        except ValueError as exc:
            if '还没有' not in str(exc):raise
    if (folder/'profile.json').exists():return (folder/'profile.json').read_text(encoding='utf-8')
    return (folder/'profile.txt').read_text(encoding='utf-8')


def source_files(case_dir):
    folder=Path(case_dir)
    if (folder/'profile.json').exists():return ['profile.json']+(['profile-supplement.txt'] if (folder/'profile-supplement.txt').exists() else [])
    return ['profile.txt']


def prepare(case_dir,replace=False):
    folder=Path(case_dir);case=json.loads((folder/'case.json').read_text());kind=case.get('kind','gaokao');raw=active_profile(folder);result=build_parse(raw,kind)
    if result is None:return {'status':'无数据，需人工解析；沿用旧文字工作流'}
    path=folder/'profile_parse.json'
    if path.exists() and not replace:raise ValueError('已有画像解析，确认重做分析后用 --replace；不能悄悄覆盖旧判断')
    dump(path,result)
    # Working copy for report provenance; archives remain byte-for-byte unchanged.
    (folder/'profile.json').write_text(raw,encoding='utf-8');(folder/'profile.json').chmod(0o600)
    if case.get('profile'):
        info,_=latest(folder.parent,folder.name);case['profile']=info;dump(folder/'case.json',case)
    return {'status':'已按最新 JSON 生成画像字段；缺项和既有分析须重新核对','fields':len(result['fields'])}


def alignment_errors(case_dir):
    folder=Path(case_dir)
    try:
        raw=active_profile(folder);data=parse_profile(raw)
        case=json.loads((folder/'case.json').read_text());kind=case.get('kind','gaokao')
        if data is None:
            if case.get('profile'):
                parsed=json.loads((folder/'profile_parse.json').read_text()) if (folder/'profile_parse.json').exists() else {}
                if parsed.get('source',{}).get('raw_sha256')!=sha(raw):return ['最新画像无数据，需人工解析并记录原文摘要，不能沿用旧判断']
            return []
        expected=build_parse(raw,kind)
        if not (folder/'profile_parse.json').exists():return ['有画像数据，请先运行 case_check.py <案例目录> --stage 1 --parse-profile']
        parsed=json.loads((folder/'profile_parse.json').read_text())
        if parsed.get('source')!=expected['source']:return ['画像已更新，须优先采用最新存档并重新解析，不能沿用旧作答']
        fields={f['field']:f for f in parsed.get('questionnaire_fields',parsed.get('fields',[]))}
        for f in expected['fields']:
            if fields.get(f['field'],{}).get('value')!=f['value'] or fields.get(f['field'],{}).get('status')!=f['status']:return ['结构化画像字段与原始作答不一致：'+f['field']]
        if case.get('profile'):
            info,_=latest(folder.parent,folder.name)
            if {k:v for k,v in case['profile'].items() if k!='integrity'}!={k:v for k,v in info.items() if k!='integrity'}:return ['case.json 当前画像版本与最新存档不一致']
        return []
    except FileNotFoundError:return [] # Original stage checks identify missing inputs.
    except (ValueError,KeyError,TypeError,OSError) as exc:return ['画像版本/数据错误：'+str(exc)]


def record_report(root,case_id,path,now=None):
    folder_for(root,case_id);path=Path(path);raw=path.read_bytes()
    info={'file':str(path.resolve()),'recorded_at':(now or datetime.now(timezone.utc)).isoformat(),'generated_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),'sha256':hashlib.sha256(raw).hexdigest()}
    with registry(root) as reg:
        if case_id not in reg['cases']:raise ValueError('案例尚未登记')
        reg['cases'][case_id]['reports'].append(info)
    return info


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter);sub=parser.add_subparsers(dest='command',required=True)
    for cmd in ('new-id','ingest','latest','diff','report'):
        p=sub.add_parser(cmd);p.add_argument('--root',type=Path,default=REPO/'cases')
        if cmd=='new-id':p.add_argument('kind',choices=HEADERS);p.add_argument('year',type=int);p.add_argument('--mode',choices=('formal','simulation'),default='formal')
        else:p.add_argument('case_id')
        if cmd in ('ingest','report'):p.add_argument('file',type=Path)
        if cmd=='diff':p.add_argument('--old');p.add_argument('--new')
    p=sub.add_parser('parse');p.add_argument('case_dir',type=Path);p.add_argument('--replace',action='store_true')
    p=sub.add_parser('keygen');p.add_argument('--private-key',type=Path,required=True);p.add_argument('--public-config',type=Path,required=True);p.add_argument('--recipient-name',default='知衢顾问');p.add_argument('--hostname',default='wjsgzz.github.io')
    sub.choices['ingest'].add_argument('--private-key',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='keygen':result=keygen(args.private_key,args.public_config,args.recipient_name,args.hostname)
        elif args.command=='new-id':result=new_id(args.root,args.kind,args.year,args.mode)
        elif args.command=='ingest':result=ingest(args.root,args.case_id,args.file.read_text(encoding='utf-8'),private_key=args.private_key)
        elif args.command=='latest':info,raw=latest(args.root,args.case_id);result={**info,'raw':raw}
        elif args.command=='diff':result=diff(args.root,args.case_id,args.old,args.new)
        elif args.command=='report':result=record_report(args.root,args.case_id,args.file)
        else:result=prepare(args.case_dir,args.replace)
    except (ValueError,KeyError,TypeError,OSError) as exc:parser.exit(1,str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
