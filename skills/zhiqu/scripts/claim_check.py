#!/usr/bin/env python3
"""Extract reviewable sentence/evidence pairs. This tool never judges entailment.

build CASE creates/refreshes a pending manifest; bind CASE attaches rendered hashes.
check CASE requires a separate review session, complete decisions and current content.
"""
import argparse,hashlib,json,re
from pathlib import Path

SCHEMA=1
DECISIONS=('支持','部分支持','不支持')
KINDS=('事实','个人登记','计算','推测','建议','结构标签')
FACT_TRIGGER=re.compile(r'\d|规定|要求|必须|只能|不能|免试|保证|均可|全部|所有|自动|属于|实行|将获|毕业即|享有')
REF=re.compile(r'\{\{(e|c|k|p):([^{}|]+?)(?:\|([^{}]+))?\}\}')

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def write(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def leaves(obj,path=''):
 if isinstance(obj,dict):
  for k,v in obj.items():yield from leaves(v,path+'/'+str(k).replace('~','~0').replace('/','~1'))
 elif isinstance(obj,list):
  for i,v in enumerate(obj):yield from leaves(v,path+'/'+str(i))
 elif isinstance(obj,(str,int,float)) and not isinstance(obj,bool):yield path,str(obj)

def sentences(text):
 # References are atomic. Decimal points and filenames are not sentence boundaries.
 parts=[s.strip() for s in re.findall(r'[^。！？\n]+[。！？]?(?:\[\d+\])*',text) if s.strip()]
 return parts

class GaokaoCase:
 """Read the inputs actually rendered by report.py; never certify their meaning.

 The source table remains authoritative. Optional source_details supplies retained
 excerpts and scope; an URL alone must not become a verified official quotation.
 """
 def __init__(self,root):
  self.root=Path(root);self.case=read(self.root/'case.json')
  self.report=read(self.root/'report.json');self.result=read(self.root/'result.json')
  self.case=dict(self.case,report_meta=self.report.get('meta',{}))
  self.data={'narrative.json':{}};self.evidence={};self._nodes={}
  from operator_check import legacy_evidence
  details=self.report.get('source_details',{})
  for item in legacy_evidence(self.root,self.report):
   eid=item['id'];explicit=details.get(eid,{})
   self.evidence[eid]=dict(item,**{k:explicit[k] for k in ('excerpt','grade','status','source','scope','value','unit') if k in explicit})
  self.refs=self.report.get('claim_evidence_refs',{})
  sections={'01':('summary',),'02':('profile',),'03':('directions_intro','directions','roadmap','news'),
            '04':('list_notes','third_party_review'),'05':('why','stress_mult','sensitivity'),'06':('research','questions'),
            '07':('todo',),'09':('ask_me_intro','ask_me'),'10':('assumptions','backtest','methods'),'11':('hindsight','omitted')}
  self.contract={'sections':[{'id':f'{i:02}','slots':[{'key':'body'}]} for i in range(1,13)]}
  for sid,keys in sections.items():
   for key in keys:
    if key in self.report:self._nodes['report.json#/'+key]=(sid,self.report[key])
  # Generated tables are report content too. C/D reports do not display precise
  # probabilities, so those hidden fields must not be presented as authored claims.
  precise=self.report.get('meta',{}).get('prob_grade','A') in ('A','B')
  for i,item in enumerate(self.result.get('list',[])):
   shown={k:item[k] for k in ('order','name','code','group','major_code','utility','tag','expected_cut_rank') if k in item}
   if precise:shown.update({k:item[k] for k in ('p_clear','p_land') if k in item})
   if self.report.get('meta',{}).get('prob_grade','A') != 'A' and 'sigma' in item and 'expected_cut_rank' in item:
    from report import interval80
    shown['rendered_interval']=interval80(item)
   from data_provenance import evidence_lines
   shown['historical_values']=evidence_lines(item)
   from report import code_reference
   shown['code_reference']=code_reference(item,self.result.get('params',{}).get('target_year'))
   self._nodes[f'result.json#/list/{i}']=('04',shown)
   self._nodes[f'result.json#/entry_sheet/{i}']=('08',{k:item.get(k) for k in ('name','code','group','major_code')})
 def nodes(self):
  result={f'{i:02}':[] for i in range(1,13)}
  for ref,(sid,_) in self._nodes.items():result[sid].append({'slot':'body','ref':ref})
  return result
 def get_node(self,ref):
  refs=[]
  for prefix,values in self.refs.items():
   if ref==prefix or ref.startswith(prefix.rstrip('/')+'/'):refs.extend(values)
  return {'type':'analysis','content':self._nodes[ref][1],'evidence_refs':sorted(set(refs))}
 def active(self,slot):return True
 def expand(self,text,where):return text
 def resolve(self,kind,path):
  # Gaokao prose is plain report.json text, not PlanningCase templates.
  raise KeyError(path)

def case_for(root):
 root=Path(root);registration=read(root/'case.json')
 if registration.get('kind')=='gaokao' or registration.get('product')=='gaokao':return GaokaoCase(root)
 from planning_workflow import PlanningCase
 return PlanningCase(root)

def extract(case):
 items=[];seen=set()
 def add(section,location,text,refs=()):
  for i,sentence in enumerate(sentences(text)):
   direct=[m[2].split('#')[0] for m in REF.finditer(sentence) if m[1]=='e']
   groups={int(n) for n in re.findall(r'\[(\d+)\]',sentence)}
   grouped=[eid for eid,e in case.evidence.items() if e.get('source_group') in groups]
   eids=sorted(set(refs)|set(direct)|set(grouped));bindings=[]
   for m in REF.finditer(sentence):
    try:value=case.resolve(m[1],m[2])
    except (KeyError,ValueError,IndexError,TypeError):value={'unresolved':True}
    bindings.append(dict(kind=m[1],ref=m[2],value=value))
   # Deliberately include uncertain prose: a reviewer, not this regex, decides
   # whether it is factual. Short factual assertions still match FACT_TRIGGER.
   if not(eids or bindings or FACT_TRIGGER.search(sentence) or len(re.sub(r'\W','',sentence))>=8):continue
   try:expanded=case.expand(sentence,'claim_check')
   except (KeyError,ValueError,IndexError,TypeError):expanded=sentence
   evidence=[dict(id=eid,excerpt=case.evidence.get(eid,{}).get('excerpt',''),grade=case.evidence.get(eid,{}).get('grade'),status=case.evidence.get(eid,{}).get('status'),source=case.evidence.get(eid,{}).get('source',{}),scope=case.evidence.get(eid,{}).get('scope')) for eid in eids]
   row=dict(section=section,location=location+':sentence'+str(i+1),text=sentence,expanded_text=expanded,evidence_refs=eids,evidence=evidence,bindings=bindings)
   row['claim_id']='C'+digest(row)[:24]
   if row['claim_id'] in seen:continue
   seen.add(row['claim_id']);items.append(row)
 for key,text in leaves(case.case.get('report_meta',{})):
  add('00','case.json#/report_meta'+key,text)
 for section,entries in case.nodes().items():
  title=case.data.get('narrative.json',{}).get('sections',{}).get(section,{}).get('title')
  if title:add(section,'narrative.json#/sections/'+section+'/title',title)
  for n,entry in enumerate(entries):
   node=case.get_node(entry['ref'])
   # Sources, machine metadata and copied quotations are inputs, not authored claims.
   if node.get('type') in ('source_endnotes','evidence_legend'):continue
   if node.get('type')=='analysis' and isinstance(node.get('content'),dict) and node['content'].get('kind')=='comment':continue
   slot=next(s for s in case.contract['sections'] if s['id']==section)
   cfg=next((s for s in slot['slots'] if s['key']==entry['slot']),{})
   if not case.active(cfg):continue
   for path,text in leaves(node.get('content',{})):
    if path.endswith(('/kind','/comment')):continue
    add(section,entry['ref']+'/content'+path,text,node.get('evidence_refs',[]))
 # The generated offer-gap paragraph must be reviewed as well as hand-written prose.
 if not isinstance(case,GaokaoCase):
  from planning_report import offer_gap_notice
  for section in case.contract['sections']:
   sid=section['id'];notice=offer_gap_notice(case,sid)
   if notice:add(sid,'planning_report.py#offer_gap_notice',notice)
 return items

def content_snapshot(case):
 from planning_workflow import FILES
 from profile_store import source_files
 if isinstance(case,GaokaoCase):
  names={'case.json','report.json','result.json',*source_files(case.root)}
  names.update(n for n in ('profile_parse.json','directions.json','rules_check.json','screening.json','pool.csv','attributes.csv','preferences_config.json','preferences_review.json','reviewed.csv','run.json','narrative.json') if (case.root/n).is_file())
  names.update(str(p.relative_to(case.root)) for p in (case.root/'sensitivity').glob('*') if p.is_file())
  return {name:file_sha(case.root/name) for name in sorted(names)}
 return {name:file_sha(case.root/name) for name in (*FILES,*source_files(case.root))}

def build(root,bind=False):
 root=Path(root);case=case_for(root);items=extract(case);path=root/'claim_check.json'
 old=read(path) if path.exists() else {};prior={x['claim_id']:x for x in old.get('items',[])}
 # Adding a citation cannot make a supported sentence unsupported: keep a "支持" verdict
 # when the sentence, its bindings and every previously cited excerpt are unchanged and
 # the new citation list only adds evidence. Anything else loses its verdict as before.
 by_place={(x['location'],x['text']):x for x in old.get('items',[]) if (x.get('review') or {}).get('decision')=='支持'}
 def evidence_only_added(prev,item):
  if prev.get('expanded_text')!=item['expanded_text'] or prev.get('bindings')!=item['bindings']:return False
  old_ev={e['id']:e for e in prev.get('evidence',[])};new_ev={e['id']:e for e in item['evidence']}
  return set(old_ev)<set(new_ev) and all(new_ev[k]==v for k,v in old_ev.items())
 for item in items:
  if item['claim_id'] in prior and prior[item['claim_id']].get('review'):
   item['review']=prior[item['claim_id']]['review']
  elif (prev:=by_place.get((item['location'],item['text']))) and evidence_only_added(prev,item):
   item['review']=dict(prev['review'],carried_from=prev['claim_id'],carried_reason='只增补出处：原句、绑定数值和原引证据摘录均未变，原“支持”判定保留；新增证据 '+'、'.join(sorted({e['id'] for e in item['evidence']}-{e['id'] for e in prev.get('evidence',[])})))
  else:item['review']=None
 manifest=digest([{k:v for k,v in x.items() if k!='review'} for x in items])
 result=dict(schema_version=SCHEMA,case_id=case.case['case_id'],manifest_sha256=manifest,source_sha256=content_snapshot(case),items=items,reviewer=old.get('reviewer'),reviewed_manifest_sha256=old.get('reviewed_manifest_sha256'),retired=old.get('retired',[]),cross_reviewers=old.get('cross_reviewers',[]))
 current={x['claim_id'] for x in items}
 for x in old.get('items',[]):
  if x['claim_id'] not in current and x.get('review') and x['review'].get('decision') in ('部分支持','不支持'):
   previous={k:x.get(k) for k in ('claim_id','text','location','review')}
   if previous not in result['retired']:result['retired'].append(previous)
 if bind:
  trace=read(root/'report_trace.json')
  result['report_snapshot']=dict(trace_sha256=file_sha(root/'report_trace.json'),artifacts=trace.get('artifacts',{}))
 write(path,result);return result

def errors(root,require_review=True,require_report=True):
 root=Path(root);path=root/'claim_check.json'
 if not path.exists():return ['claim_check.json：缺逐句回查清单']
 data=read(path);case=case_for(root);expected=extract(case);problems=[]
 expected_payload=[{k:v for k,v in x.items() if k!='review'} for x in expected]
 actual_payload=[{k:v for k,v in x.items() if k!='review'} for x in data.get('items',[])]
 if expected_payload!=actual_payload or data.get('manifest_sha256')!=digest(expected_payload):problems.append('claim_check.json：句子/组件/引用摘录清单不完整或已变更，须重新抽取')
 if data.get('source_sha256')!=content_snapshot(case):problems.append('claim_check.json：输入快照已过期')
 if require_report:
  trace=root/'report_trace.json';snapshot=data.get('report_snapshot',{})
  if not trace.exists() or snapshot.get('trace_sha256')!=file_sha(trace):problems.append('claim_check.json：未绑定当前报告快照')
  else:
   artifacts=read(trace).get('artifacts',{})
   if snapshot.get('artifacts')!=artifacts:problems.append('claim_check.json：报告文件集合不一致')
   for name,sha in artifacts.items():
    if Path(name).name!=name or not(root/name).is_file() or file_sha(root/name)!=sha:problems.append('claim_check.json：报告已变更 '+name)
 if not require_review:return problems
 reviewer=data.get('reviewer') or {}
 author=case.case.get('authoring',{}).get('session_id')
 if author and reviewer.get('session_id')==author:problems.append('claim_check.json.reviewer：复核会话与写作会话相同')
 if reviewer.get('independent') is not True or not reviewer.get('session_id') or not reviewer.get('model'):problems.append('claim_check.json.reviewer：须由未参与写作的独立会话逐句填写，记录会话及模型')
 if data.get('reviewed_manifest_sha256')!=data.get('manifest_sha256'):problems.append('claim_check.json：独立复核未覆盖当前句子清单')
 for item in data.get('items',[]):
  review=item.get('review') or {};where='claim_check.json.'+str(item.get('claim_id'))
  effective=review.get('reviewer') or reviewer
  writer=review.get('author_session_id') or author
  if effective.get('independent') is not True or not effective.get('session_id') or not effective.get('model'):problems.append(where+'：缺独立复核会话和模型')
  if writer and effective.get('session_id')==writer:problems.append(where+'：写作/改写会话不能复核自己的句子')
  if review.get('decision') not in DECISIONS or review.get('kind') not in KINDS or not str(review.get('reason') or '').strip():problems.append(where+'：缺支持/部分支持/不支持判定、类型或具体理由');continue
  if review['decision']=='不支持':
   # Marking as inference must be visible in the current sentence itself.
   if review['kind']!='推测' or not re.search(r'推测|推断|假设',item['text']):problems.append(where+'：不支持的句子须删除或明确改标推测并说明前提')
  if review['decision']=='部分支持':problems.append(where+'：部分支持的当前句须改写后重新抽取复核')
  if review['kind']=='事实' and not item['evidence_refs']:problems.append(where+'：事实句没有证据引用，须补引用或改写')
  if review['kind']=='个人登记' and not(item['evidence_refs'] or any(x['kind'] in ('p','k') for x in item['bindings'])):problems.append(where+'：本人事实没有登记/个人证据定位')
 return problems

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('action',choices=['build','bind','check']);a.add_argument('case_dir',type=Path);args=a.parse_args()
 if args.action in ('build','bind'):r=build(args.case_dir,args.action=='bind');print('已抽取',len(r['items']),'句；语义判定留给独立会话')
 else:
  issues=errors(args.case_dir);print(json.dumps(dict(ok=not issues,errors=issues),ensure_ascii=False,indent=2));raise SystemExit(bool(issues))
if __name__=='__main__':main()
