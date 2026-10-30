"""Public HTTP adapter for on-demand kaoyan retrieval. Business bodies stay in RAM.
The fixed public DNS helper retains the crawler's native guarded transport.
No live HTTP on import. Only exact parent-approved header/role mappings may be aggregated.
"""
from pathlib import Path
from html.parser import HTMLParser
import hashlib,importlib.util,ipaddress,json,re,shutil,subprocess,sys,time
from urllib.parse import urlsplit,parse_qsl,unquote,urlencode
CRAWLER=Path.home()/'.agents/skills/xik-crawler/scripts/crawl.py'
MARK=b'\n__XIK_MEMORY_META_END__'
PRIVATE_KEYS=re.compile(r'^(?:name|xm|phone|email|contact|sfzh|ksbh|zkzh|student_?id|candidate_?id|candidate_name|candidate_number|student_name|id_card|identity_number|姓名|考生姓名|考生号|考生编号|准考证号|身份证号|password|passwd|pwd|access_token|session|cookie|passport|idcard)$',re.I)
class SafeStop(Exception):pass

def safe_url(url):
 if re.search(r'%(?![0-9a-fA-F]{2})',url):raise SafeStop('unsafe_url')
 p=urlsplit(url)
 if p.scheme not in{'http','https'}or not p.hostname or p.username or p.password or p.port not in{None,80 if p.scheme=='http'else 443}:raise SafeStop('unsafe_url')
 path=p.path
 for _ in range(2):path=unquote(path)
 if re.search(r'/(?:login|logon|logout|signin|sso|captcha)(?:\.(?:html?|aspx?|ashx|jsp|php|do|action|cgi))?(?:/|$)',path,re.I):raise SafeStop('restricted_url')
 for k,v in parse_qsl(p.query):
  if PRIVATE_KEYS.fullmatch(k)or re.search(r'(?<!\d)\d{12,18}[Xx]?(?!\d)',v):raise SafeStop('private_query')
 return url

def load_crawler():
 sys.path.insert(0,str(CRAWLER.parent));spec=importlib.util.spec_from_file_location('xik_memory_public_crawler',CRAWLER);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def memory_curl_adapter(crawl):
 """Same curl arguments/TLS/public DNS as official curl_once, sinks changed to pipes only."""
 def once(url,*,headers,form,max_bytes,timeout,resolved_ip=None):
  # retrieve() validates generic public targets, but our stricter privacy and
  # login-path rules must also run before every redirect's DNS/HTTP attempt.
  try:safe_url(url)
  except SafeStop:raise crawl.TargetValidationError('拒绝不符合公开取文规则的跳转目标')from None
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
 c=crawler or load_crawler();old=c.curl_once;memory_send=memory_curl_adapter(c)
 # resolve_public() uses this same module-level transport for its internal
 # public DNS query. Its `name` is the exact requested hostname, not a person.
 # Keep that fixed helper on the original crawler transport; never exempt a
 # business URL's name query or an arbitrary request to the resolver host.
 resolver_url='https://cloudflare-dns.com/dns-query?'+urlencode({'name':urlsplit(url).hostname,'type':'A'})
 def send(target,**kwargs):
  if (target==resolver_url and kwargs.get('resolved_ip')=='1.1.1.1'
      and kwargs.get('form')is None and kwargs.get('headers')=={'Accept':'application/dns-json'}
      and kwargs.get('max_bytes')==65536 and kwargs.get('timeout')==8):
   return old(target,**kwargs)
  return memory_send(target,**kwargs)
 c.curl_once=send
 try:
  # Original retrieve owns RequestGuard.reserve/finish, DNS cache, redirect and challenge checks.
  return c.retrieve(url,referer=referer,max_bytes=max_bytes,transport='plain',fallback=False,max_attempts=max_attempts,allow_http_redirect=False)
 finally:c.curl_once=old

# Diagnostic enums only: even a syntactically valid MIME subtype can contain
# arbitrary private text. Never retain unknown header values or byte previews.
MIME_HINTS=frozenset(('text/html','application/xhtml+xml','application/pdf','application/zip',
 'application/octet-stream','application/vnd.ms-excel',
 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
 'application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document',
 'image/png','image/jpeg','image/gif','image/webp','image/svg+xml',
 'application/json','text/plain','text/csv','text/xml','application/xml'))
FORMAT_HINT_PREFIX_BYTES=262144

class _ReceiptTags(HTMLParser):
 # Treat title/textarea content as text, just as script/style content is text.
 CDATA_CONTENT_ELEMENTS=('script','style','title','textarea')
 def __init__(self):
  super().__init__();self.flags={k:False for k in ('html','title','script','form','table','img','iframe','object','embed')};self.in_title=False;self.title_text=False
 def handle_starttag(self,tag,attrs):
  if tag in self.flags:self.flags[tag]=True
  if tag=='title':self.in_title=True
 def handle_startendtag(self,tag,attrs):
  self.handle_starttag(tag,attrs)
  if tag=='title':self.in_title=False
 def handle_endtag(self,tag):
  if tag=='title':self.in_title=False
 def handle_data(self,data):
  if self.in_title and data.strip():self.title_text=True

def response_format_hint(item):
 """Bounded RAM observations, not a parser, source identity or block verdict."""
 body=item['body'];sample=bytes(body[:FORMAT_HINT_PREFIX_BYTES]);mime=item.get('content_type')
 declared=mime.split(';',1)[0].strip().lower()if isinstance(mime,str)else''
 missing=mime is None or isinstance(mime,str)and not mime.strip()
 declared=declared if declared in MIME_HINTS else'not_provided'if missing else'unrecognized'
 signatures=((b'%PDF-','pdf'),(b'PK\x03\x04','zip'),(b'PK\x05\x06','zip'),(b'PK\x07\x08','zip'),
  (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1','ole_compound'),(b'\x89PNG\r\n\x1a\n','png'),
  (b'\xff\xd8\xff','jpeg'),(b'GIF87a','gif'),(b'GIF89a','gif'))
 signature=next((name for magic,name in signatures if sample.startswith(magic)),'empty'if not sample else'unknown')
 if sample.startswith(b'RIFF')and sample[8:12]==b'WEBP':signature='webp'
 text=None
 if signature=='unknown'or declared in ('text/html','application/xhtml+xml'):
  text=sample.decode('utf-16'if sample.startswith((b'\xff\xfe',b'\xfe\xff'))else'utf-8-sig',errors='replace')
  beginning=text.lstrip().lower()
  if signature=='unknown':
   if any(beginning.startswith(k)for k in ('<!doctype html','<html','<head','<body','<script')):signature='html_prefix'
   elif beginning.startswith(('<?xml','<svg')):signature='xml_prefix'
 tags=None
 if signature=='html_prefix'or declared in ('text/html','application/xhtml+xml'):
  parser=_ReceiptTags()
  try:parser.feed(text or'');parser.close();tags=dict(parser.flags,title_has_nonspace_text=parser.title_text)
  except (ValueError,AssertionError):tags={'inspection_failed':True}
 return dict(scope='byte_prefix_only_not_business_verification',declared_mime=declared,
  body_signature=signature,inspected_bytes=len(sample),prefix_truncated=len(body)>len(sample),html_tags=tags)

def public_receipt(url,item,attempts,reason):
 """No raw header/reason/body/exception is copied to disk or diagnostics."""
 safe_url(url);safe_attempts=[]
 for a in attempts:
  u=a.get('url',url)
  try:safe_url(u)
  except SafeStop:
   # The transport rejected this hop before sending it. Do not serialize its
   # private query/path, but retain a stop receipt so no other path is tried.
   rejected={'url':url,'stop_category':'restricted_redirect','target_url_suppressed':True}
   if 'origin_attempted'in a:rejected['origin_attempted']=a['origin_attempted']
   safe_attempts.append(rejected)
   continue
  z={k:a[k]for k in['http_status','bytes','body_sha256','origin_attempted']if k in a};z['url']=u
  if'retry_at'in a:z['retry_at']=round(a['retry_at'],3)
  if'reason'in a:z['stop_category']=stop_category(a['reason'],a.get('http_status'))
  safe_attempts.append(z)
 last_status=next((a['http_status']for a in reversed(attempts)if a.get('http_status')is not None),None)
 category='restricted_redirect'if any(a.get('stop_category')=='restricted_redirect'for a in safe_attempts)else stop_category(reason,last_status)
 return dict(source_url=url,status='retrieved'if item else'unretrieved',stop_category=None if item else category,sha256=hashlib.sha256(item['body']).hexdigest()if item else None,bytes=len(item['body'])if item else 0,attempts=safe_attempts,raw_original_written=False,format_hint=response_format_hint(item)if item else None)

def stop_category(reason,http_status=None):
 """Classify actual status/reason, never digits in a URL or fingerprint."""
 s=str(reason or'')
 for p,k in [(r'请求保护|(?:^|\s)(?:site_|global_|interval)[a-z_]*','shared_guard'),('登录|login','login'),('验证|captcha|challenge|环境检测|浏览器校验|安全校验|人机校验','verification')]:
  if re.search(p,s,re.I):return k
 try:code=int(http_status)if http_status is not None else None
 except (ValueError,TypeError):code=None
 if code is None:
  m=re.search(r'\bHTTP(?:[\s_-]*(?:status|状态码))?[\s:=_-]*(401|403|412|429)(?!\d)|^\s*(401|403|412|429)\s*$',s,re.I)
  if m:code=int(m.group(1)or m.group(2))
 if code in {401,403,412,429}:return {401:'login',403:'http_block',412:'http_block',429:'rate_limit'}[code]
 for p,k in [('限流','rate_limit'),('DNS|解析','dns'),('TLS|证书|退出码 (?:51|60)','tls')]:
  if re.search(p,s,re.I):return k
 return'other_unretrieved'

