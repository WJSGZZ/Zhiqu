"""Validate official source identity and declared fingerprints, without local files.

A well-formed fingerprint does not prove retrieval or support for a claim. Excerpt
support remains an independent claim-review decision. Unretrieved records are
allowed as explicit gaps, but their values cannot be affirmative factual inputs.
"""
import re
from official_source_audit import official_domain_for_url

# “机构” is a neutral organization term, including public official institutions.
# Only names explicitly identifying a third-party/experience provider are barred.
THIRD_PARTY_NAME=re.compile(r'第三方|经验帖|经验平台|经验整理|经验汇总|整理平台|培训机构|中介机构|咨询机构|留学机构|考研机构')
SHA256=re.compile(r'[0-9a-fA-F]{64}')

def official_source_errors(evidence,case_root=None):
    if evidence.get('grade')!='官方':return []
    source=evidence.get('source') or {};where='evidence.json.items.'+str(evidence.get('id','?'))+'.source'
    if not isinstance(source,dict):return [where+'：来源须为对象']
    errors=[];name=' '.join(str(source.get(k,'') or '') for k in ('name','organization','title','publisher')).strip()
    if not name:errors.append(where+'：官方来源须写发布单位或来源身份')
    if THIRD_PARTY_NAME.search(name):errors.append(where+'：明确的第三方/经验平台/商业机构来源不得标官方')
    url=source.get('url') or source.get('source_url') or ''
    if not official_domain_for_url(url):errors.append(where+'：source_url域名不在已核官方域名清单')
    fingerprint=source.get('sha256')
    if fingerprint not in (None,'') and (not isinstance(fingerprint,str) or not SHA256.fullmatch(fingerprint)):
        errors.append(where+'.sha256：指纹须为64位十六进制SHA-256')
    elif not fingerprint and evidence.get('status')!='unretrieved':
        errors.append(where+'.sha256：已取得的官方证据须记录原文指纹')
    if evidence.get('status')=='unretrieved' and evidence.get('value') is not None:
        errors.append(where+'：未取到原文的证据不能以确定值支持肯定事实')
    return errors
