#!/usr/bin/env python3
"""Offline official-source identity and fingerprint inventory.

Domain registration confirms an organization's site, not every claim on it.
A declared fingerprint is metadata, not proof of retrieval or claim support.
Excerpt/claim entailment still requires review. No networking or local-file reads.
"""
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from datetime import date
import argparse, csv, json, re

ROOT=Path(__file__).resolve().parents[3]
DOMAIN_CSV=ROOT/'skills/zhiqu-shared/references/official-domains.csv'

def normalize_url(url):
    try:
        p=urlsplit(url.strip())
        return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path or '/',p.query,''))
    except (ValueError,AttributeError):return ''

def load_official_domains(path=None):
    """Return reviewed domain -> organization/evidence rows; no suffix guessing."""
    path=Path(path or DOMAIN_CSV)
    if not path.exists():return {}
    with path.open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    required={'domain','organization','evidence'}
    if rows and not required.issubset(rows[0]):raise ValueError('official domain CSV missing fields')
    out={}
    for row in rows:
        domain=row['domain'].strip().lower().rstrip('.')
        if not domain or not row['organization'].strip() or not row['evidence'].strip():
            raise ValueError('empty reviewed domain identity/evidence')
        if domain in out:raise ValueError('duplicate reviewed domain: '+domain)
        out[domain]=row
    return out

def official_domain_for_url(url,domains=None):
    """Exact reviewed host or a subdomain of a reviewed organization root."""
    try:host=(urlsplit(url).hostname or '').lower().rstrip('.')
    except ValueError:return None
    domains=load_official_domains() if domains is None else domains
    for domain in sorted(domains,key=len,reverse=True):
        if host==domain or host.endswith('.'+domain):
            row=domains[domain]
            # A shared commercial attachment bucket is not an official website.
            # Accept only the exact objects linked by the reviewed official page.
            if domain.endswith('.aliyuncs.com'):
                allowed=re.findall(r'allowed_url=([^\s|;]+)',row['evidence'])
                if normalize_url(url) not in {normalize_url(x) for x in allowed}:return None
            return row
    return None

def scan_example_sources(root=ROOT):
    root=Path(root);rows=[]
    for path in sorted(root.glob('skills/*/examples/**/evidence.json')):
        obj=json.loads(path.read_text())
        for item in obj.get('items',[]):
            source=item.get('source') or {};url=source.get('url') or ''
            if not urlsplit(url).hostname:continue
            rows.append({'file':str(path.relative_to(root)),'id':item.get('id'),
                'url':url,'host':urlsplit(url).hostname,'grade':item.get('grade'),
                'organization':source.get('organization',''),'status':item.get('status'),
                'retrieved_on':item.get('retrieved_on'),'review_due':item.get('review_due'),
                'excerpt':item.get('excerpt',''),'locator':source.get('locator'),
                'kind':'evidence','claim':item.get('claim',''),
                'value_is_none':item.get('value') is None,
                'availability':item.get('availability'),'gap':item.get('gap'),
                'source':source,'value':item.get('value')})
    for path in sorted(root.glob('skills/zhiqu/examples/*/report.json')):
        obj=json.loads(path.read_text())
        for i,source in enumerate(obj.get('sources',[])):
            if isinstance(source,dict):
                name=source.get('name') or source.get('organization') or '';raw=source.get('url') or ''
                grade=source.get('grade');retrieved=source.get('retrieved_on')
            elif isinstance(source,list):
                name=str(source[0]) if source else '';raw=str(source[1]) if len(source)>1 else ''
                grade=None;retrieved=str(source[2]) if len(source)>2 else None
            else:continue
            for url in re.findall(r'https?://[^\s；，。\]\)"<>]+',raw):
                rows.append({'file':str(path.relative_to(root)),'id':str(i),
                    'url':url,'host':urlsplit(url).hostname,'grade':grade,
                    'organization':name,'status':None,'retrieved_on':retrieved,
                    'review_due':None,'excerpt':'','locator':None,'kind':'gaokao_report_source',
                    'claim':name,'value_is_none':None,'availability':None,'gap':None})
    return rows

def audit_sources(root=ROOT,as_of=None):
    """Inventory real gaps, preserving grades and unavailable source records."""
    root=Path(root);today=date.fromisoformat(as_of) if as_of else date.today()
    domains=load_official_domains(root/'skills/zhiqu-shared/references/official-domains.csv')
    rows=scan_example_sources(root)
    for row in rows:
        issues=[];official=row['grade']=='官方'
        registered=official_domain_for_url(row['url'],domains)
        row['registered_domain']=registered['domain'] if registered else None
        row['registered_organization']=registered['organization'] if registered else None
        if official and not registered:issues.append('official_domain_not_registered')
        if row['kind']=='gaokao_report_source' and row['grade'] is None:issues.append('legacy_source_missing_grade')
        if official and row['status']!='verified':issues.append('official_record_not_verified')
        if row['review_due']:
            try:
                if date.fromisoformat(row['review_due'])<today:issues.append('evidence_expired')
            except ValueError:issues.append('invalid_review_due')
        from source_authentication import THIRD_PARTY_NAME
        if THIRD_PARTY_NAME.search(row['organization']):
            issues.append('third_party_term_in_source_name')
        if official:
            from source_authentication import official_source_errors
            item={'id':row['id'],'grade':row['grade'],'status':row['status'],
                  'source':row.get('source',{}),'value':row.get('value')}
            issues.extend(official_source_errors(item))
        row['issues']=issues
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--as-of')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    rows=audit_sources(args.root,args.as_of)
    output=json.dumps({'as_of':args.as_of or date.today().isoformat(),'records':rows},ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(output)
    else:print(output)

if __name__=='__main__':main()
