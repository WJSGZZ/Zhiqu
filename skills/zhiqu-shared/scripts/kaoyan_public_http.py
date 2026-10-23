"""Public HTTP adapter for on-demand kaoyan retrieval. Public crawler guard unchanged; raw response bodies stay in RAM.
No live HTTP on import. Only exact parent-approved header/role mappings may be aggregated.
"""
from pathlib import Path
import hashlib,importlib.util,ipaddress,json,re,shutil,subprocess,sys,time
from urllib.parse import urlsplit,parse_qsl,unquote,urlencode
CRAWLER=Path.home()/'.agents/skills/xik-crawler/scripts/crawl.py'
MARK=b'\n__XIK_MEMORY_META_END__'
PRIVATE_KEYS=re.compile(r'^(?:name|xm|phone|email|contact|sfzh|ksbh|zkzh|student_?id|candidate_?id|candidate_name|candidate_number|student_name|id_card|identity_number|姓名|考生姓名|考生号|考生编号|准考证号|身份证号|password|passwd|pwd|access_token|session|cookie|passport|idcard)$',re.I)
class SafeStop(Exception):pass

def safe_url(url):
 p=urlsplit(url)
 if p.scheme not in{'http','https'}or not p.hostname or p.username or p.password or p.port not in{None,80 if p.scheme=='http'else 443}:raise SafeStop('unsafe_url')
 if re.search(r'/(?:login|logon|logout|signin|sso|captcha)(?:/|$)',p.path,re.I):raise SafeStop('restricted_url')
 for k,v in parse_qsl(p.query):
  if PRIVATE_KEYS.fullmatch(k)or re.search(r'(?<!\d)\d{12,18}[Xx]?(?!\d)',v):raise SafeStop('private_query')
 return url

def load_crawler():
 sys.path.insert(0,str(CRAWLER.parent));spec=importlib.util.spec_from_file_location('xik_memory_public_crawler',CRAWLER);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def memory_curl_adapter(crawl):
 """Same curl arguments/TLS/public DNS as official curl_once, sinks changed to pipes only."""
 def once(url,*,headers,form,max_bytes,timeout,resolved_ip=None):
  started=time.monotonic();ip=resolved_ip or crawl.resolve_public(url)
  if not ipaddress.ip_address(ip).is_global:raise crawl.Unretrieved('拒绝非公网目标')
  timeout-=time.monotonic()-started
  if timeout<1:raise crawl.ResolutionError('DNS解析耗尽本次请求时间预算；尚未连接原站')
  p=urlsplit(url);address=f'[{ip}]'if':'in ip else ip
  # stderr is an anonymous OS pipe via capture_output, not a disk file. No -L, -k, cookies or proxy.
  args=[shutil.which('curl')or'curl','-q','--silent','--show-error','--noproxy','*','--proto','=http,https','--connect-timeout',str(min(8,timeout)),'--max-time',str(timeout),'--max-filesize',str(max_bytes),'--resolve',f'{p.hostname}:{p.port or(443 if p.scheme=="https"else 80)}:{address}','--dump-header','/dev/stderr','--output','-','--write-out','%{stderr}'+MARK.decode()+'%{json}']
  for k,v in headers.items():args.extend(['--header',f'{k}: {v}'])
  if form is not None:args.extend(['--data-raw',urlencode(form)])
  args.extend(['--url',url])
  try:r=subprocess.run(args,capture_output=True,timeout=timeout+2)
  except(OSError,subprocess.TimeoutExpired):raise crawl.Unretrieved('curl 无法运行或请求超时')from None
  raw_headers,sep,meta_raw=r.stderr.rpartition(MARK)
  try:meta=json.loads(meta_raw)if sep else{}
  except(ValueError,TypeError):meta={}
  if r.returncode:
   phase=('连接尚未建立'if not meta.get('time_connect')else'TLS握手尚未完成'if p.scheme=='https'and not meta.get('time_appconnect')else'等待或传输正文超时')if r.returncode==28 else'传输失败'
   raise crawl.TransportError(r.returncode,phase)
  if not sep or not isinstance(meta,dict)or'http_code'not in meta:raise crawl.Unretrieved('未取到可解析的 curl 响应')
  body=r.stdout
  if len(body)>max_bytes:raise crawl.Unretrieved('响应超过大小上限')
  text=raw_headers.decode('iso-8859-1');loc=re.findall(r'^location:\s*(.+?)\r?$',text,re.I|re.M);kept={}
  for line in text.splitlines():
   if line.upper().startswith('HTTP/'):kept={}
   elif':'in line:
    k,v=line.split(':',1)
    if k.lower()in{'cache-control','age','vary','etag','last-modified','retry-after','set-cookie'}:kept[k.lower()]='[present]'if k.lower()=='set-cookie'else v.strip()
  return dict(url=url,http_status=int(meta['http_code']),content_type=meta.get('content_type')or'',resolved_ip=ip,resolution_method='fixed_service_pin'if resolved_ip else crawl.DNS_METHODS.get(p.hostname,'system'),headers=kept,location=loc[-1].strip()if loc else None,body=body)
 return once

def retrieve_memory(url,*,referer=None,max_bytes=50_000_000,max_attempts=2,crawler=None):
 safe_url(url)
 if referer:safe_url(referer)
 c=crawler or load_crawler();old=c.curl_once;c.curl_once=memory_curl_adapter(c)
 try:
  # Original retrieve owns RequestGuard.reserve/finish, DNS cache, redirect and challenge checks.
  return c.retrieve(url,referer=referer,max_bytes=max_bytes,transport='plain',fallback=False,max_attempts=max_attempts,allow_http_redirect=False)
 finally:c.curl_once=old

def public_receipt(url,item,attempts,reason):
 """No raw header/reason/body/exception is copied to disk or diagnostics."""
 safe_url(url);safe_attempts=[]
 for a in attempts:
  u=a.get('url',url);safe_url(u);z={k:a[k]for k in['http_status','bytes','body_sha256','origin_attempted']if k in a};z['url']=u
  if'retry_at'in a:z['retry_at']=round(a['retry_at'],3)
  if'reason'in a:z['stop_category']=stop_category(a['reason'])
  safe_attempts.append(z)
 return dict(source_url=url,status='retrieved'if item else'unretrieved',stop_category=stop_category(reason)if reason else None,sha256=hashlib.sha256(item['body']).hexdigest()if item else None,bytes=len(item['body'])if item else 0,attempts=safe_attempts,raw_original_written=False)

def stop_category(reason):
 s=str(reason or'')
 for p,k in [('site_|global_|interval|请求保护','shared_guard'),('登录|login|401','login'),('验证|captcha|challenge','verification'),('429|限流','rate_limit'),('403|412','http_block'),('DNS|解析','dns'),('TLS|证书|退出码 (?:51|60)','tls')]:
  if re.search(p,s,re.I):return k
 return'other_unretrieved'

