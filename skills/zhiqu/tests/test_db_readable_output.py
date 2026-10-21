"""Readable defaults must preserve raw values and provenance in JSON/full."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts/zhiqu_db.py'
spec=importlib.util.spec_from_file_location('db_readable_output',SCRIPT);db=importlib.util.module_from_spec(spec);spec.loader.exec_module(db)

class ReadableOutput(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.execute("attach database ':memory:' as data");self.addCleanup(self.c.close)
  self.c.executescript('''create table data.source(source_id text,grade text,publisher text,title text,landing_url text,archive_sha256 text,published text);insert into data.source values('s','官方','某省考试院','2025年本科投档线','https://example.gov.cn/a','full-fingerprint','2025-07-20');
  create table data.gk_official_cutoff(province text,year integer,subject text,code text,name text,grp text,major_code text,major text,plan integer,admit integer,score integer,rank integer,source_id text,src text,src_row text,value_status text);''')
  self.patch=patch.object(db,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
 def source_csv(self,headers,rows=None):
  file=self.root/'skills/zhiqu/data/jiangsu/physics_2025.csv';file.parent.mkdir(parents=True,exist_ok=True)
  if rows is None:rows=[{'code':'1234','name':'甲大学','group':'01','major':'化学','major_code':'','score':'600','rank':'100','source_id':'s'}]
  with file.open('w',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore');w.writeheader();w.writerows(rows)
  db._public_format_record.cache_clear()
 def verified_format(self,fields=None,scope=None,fixed=None):
  self.c.execute('create table if not exists data.source_format_reference(source_id text primary key,provided_fields text,scope_fields text,excerpt text,locator text,scope_values text)')
  self.c.execute('insert or replace into data.source_format_reference values(?,?,?,?,?,?)',('s',json.dumps(fields or ['score','rank']),json.dumps(scope or {'major':'subject_requirements'}),'原表头：最低分、最低位次','原件第1页表头',json.dumps(fixed or {})))
 def raw(self,**changes):
  value={'province':'江苏','year':2025,'subject':'物理','code':'1234','name':'甲大学','grp':'01','major_code':'','major':'化学','plan':None,'admit':None,'score':600,'rank':100,'source_id':'s','src':'jiangsu/physics_2025.csv:2','src_row':'整理CSV:2','value_status':json.dumps({k:{'status':'原件缺失' if k in ('plan','admit') else '官方原值'} for k in ('plan','admit','score','rank')})};value.update(changes);return value
 def record(self,**changes):return db._record(self.c,'gk_official_cutoff',self.raw(**changes))
 def result(self,rows):return {'sections':[{'table':'gk_official_cutoff','title':'官方投档线','total':len(rows),'offset':0,'returned':len(rows),'truncated':0,'rows':rows}]}
 def test_group_requirements_not_invented_as_professional_name(self):
  self.source_csv(['code','name','group','major','score','rank','source_id'])
  self.verified_format();r=self.record();ctx=r['context'];self.assertEqual(ctx['source_group_code'],'01');self.assertEqual(ctx['group_scope_raw'],'化学');self.assertEqual(ctx['subject_requirements'],'化学');self.assertNotIn('major_name',ctx)
  text=db.render_text(self.result([r]));self.assertIn('选科要求：化学',text);self.assertNotIn('本科专业：化学',text)
 def test_full_professional_name_keeps_direction_and_original_code(self):
  self.source_csv(['code','name','group','major_code','major','score','rank','source_id'],[{'code':'1234','name':'甲大学','major':'化学(师范，定向)','major_code':'02','source_id':'s'}])
  self.verified_format(scope={'major':'major_name'});r=self.record(grp='',major='化学(师范，定向)',major_code='02');self.assertEqual(r['context']['major_name'],'化学(师范，定向)');self.assertEqual(r['context']['source_major_code'],'02');self.assertEqual(r['context']['source_school_code'],'1234')
 def test_known_format_absence_hidden_but_original_values_status_unchanged(self):
  self.source_csv(['code','name','group','major','score','rank','source_id']);self.verified_format();r=self.record();before=copy.deepcopy(r)
  short=db.render_text(self.result([r]));full=db.render_text(self.result([r]),full=True)
  self.assertNotIn('计划人数：',short);self.assertNotIn('录取人数：',short)
  self.assertIn('计划人数：来源未提供',full);self.assertEqual(r['values']['plan']['value_status']['applicable_by_format'],False);self.assertEqual(r['values']['plan']['value_status']['original_status']['status'],'原件缺失');self.assertEqual(r,before)
 def test_existing_but_blank_column_is_explicitly_shown(self):
  self.source_csv(['code','name','group','major','plan','admit','score','rank','source_id']);self.verified_format(fields=['plan','admit','score','rank']);text=db.render_text(self.result([self.record()]))
  self.assertIn('计划人数：表中空白（原因未核）',text);self.assertIn('录取人数：表中空白（原因未核）',text)
 def test_unknown_format_moves_missing_fields_to_full_with_explicit_block_notice(self):
  r=self.record(src='unknown.csv:2');text=db.render_text(self.result([r]));self.assertNotIn('计划人数：',text);self.assertNotIn('录取人数：',text);self.assertIn('原格式未核，空值状态见--full',text);self.assertIn('计划人数：原件缺失',db.render_text(self.result([r]),full=True))
 def test_nonempty_value_never_hidden_when_source_header_lacks_field(self):
  self.source_csv(['code','name','group','major','score','rank','source_id']);text=db.render_text(self.result([self.record(plan=12)]));self.assertIn('计划人数：12',text)
 def test_wrong_source_row_does_not_lend_its_format(self):
  self.source_csv(['code','name','group','major','score','rank','source_id'],[{'code':'9999','source_id':'s'}]);text=db.render_text(self.result([self.record()]));self.assertIn('原格式未核，空值状态见--full',text)
 def test_normalized_csv_header_does_not_verify_original_format(self):
  self.source_csv(['code','name','group','major','plan','admit','score','rank','source_id'])
  r=self.record();self.assertNotIn('source_format_columns',r['context']);self.assertNotIn('subject_requirements',r['context'])
  text=db.render_text(self.result([r]));self.assertIn('原格式未核',text);self.assertNotIn('表中空白',text)
 def test_verified_fixed_scope_and_per_record_original_scope_take_priority(self):
  self.source_csv(['code','name','group','major','score','rank','source_id']);self.verified_format(fixed={'source_batch_raw':'原件明确批次','subject':'综合'})
  self.c.execute('create table data.official_cutoff_scope(source_id text,public_record text,scope_json text,locator_json text)')
  self.c.execute('insert into data.official_cutoff_scope values(?,?,?,?)',('s','jiangsu/physics_2025.csv:2',json.dumps({'source_major_code':'真实专业码','subject_requirements':'物理和化学'}),json.dumps({'page':1,'row':2})))
  r=self.record();ctx=r['context'];self.assertEqual(ctx['source_batch_raw'],'原件明确批次');self.assertEqual(ctx['subject'],'综合');self.assertEqual(ctx['source_major_code'],'真实专业码');self.assertEqual(ctx['subject_requirements'],'物理和化学')
  d=self.result([r]);self.assertNotIn('source_scope_locator',db.render_text(d));self.assertIn('source_scope_locator',db.render_text(d,full=True))
 def test_source_query_retains_public_row_and_original_scope_coordinate(self):
  import contextlib
  self.source_csv(['code','name','group','major','score','rank','source_id']);self.verified_format()
  self.c.execute('create table data.official_cutoff_scope(source_id text,public_record text,scope_json text,locator_json text)')
  self.c.execute('insert into data.official_cutoff_scope values(?,?,?,?)',('s','jiangsu/physics_2025.csv:2','{}','{"row":3}'))
  raw=self.raw();self.c.execute('insert into data.gk_official_cutoff('+','.join(raw)+')values('+','.join('?' for _ in raw)+')',list(raw.values()))
  with patch.object(db,'_open',return_value=contextlib.nullcontext((self.c,self.root/'mock.sqlite'))):
   result=db.query_source('s')
  loc=result['locations'][0]['locator'];self.assertEqual(loc['public_record'],'jiangsu/physics_2025.csv:2');self.assertEqual(loc['original_scope']['row'],3)
  self.assertIn('原件第1页表头',loc['original_format']['locator'])

 def test_duplicate_scopes_receive_real_record_keys(self):
  self.source_csv(['code','name','group','major','score','rank','source_id']);raw=self.raw();cols=list(raw)
  for _ in range(2):self.c.execute('insert into data.gk_official_cutoff('+','.join(cols)+')values('+','.join('?' for _ in cols)+')',[raw[k] for k in cols])
  sec=db._section(self.c,'gk_official_cutoff','1=1',[],10,0);rows=sec['rows'];self.assertNotEqual(rows[0]['context']['scope_row_disambiguator'],rows[1]['context']['scope_row_disambiguator'])
  text=db.render_text({'sections':[sec]});scopes=[line.split(' | ')[0] for line in text.splitlines() if '600' in line and ' | ' in line];self.assertEqual(len(scopes),len(set(scopes)))
 def test_direct_rows_same_csv_location_retain_distinct_real_record_keys(self):
  self.source_csv(['code','name','group','major','score','rank','source_id']);rows=[self.record(),self.record()]
  for i,r in enumerate(rows):r['context']['source_record_key']='gk_official_cutoff:'+str(101+i)
  text=db.render_text(self.result(rows));scopes=[line.split(' | ')[0] for line in text.splitlines() if '600' in line and ' | ' in line]
  self.assertEqual(len(scopes),2);self.assertEqual(len(set(scopes)),2);self.assertIn('gk_official_cutoff:101',text);self.assertIn('gk_official_cutoff:102',text)
 def test_repeated_caveat_is_block_level_not_per_numeric_cell(self):
  rows=[self.record(),self.record()]
  for r in rows:
   for v in r['values'].values():v['supplement_warning']='共同范围仍待核'
  text=db.render_text(self.result(rows));self.assertEqual(text.count('共同范围仍待核'),1)
 def test_default_sources_simple_full_keeps_fingerprint_and_location(self):
  r=self.record();r['locator']={'src_page':2,'src_row':9};d=self.result([r]);before=copy.deepcopy(d);short=db.render_text(d);full=db.render_text(d,full=True)
  self.assertIn('某省考试院｜2025年本科投档线｜2025｜https://example.gov.cn/a',short);self.assertNotIn('full-fingerprint',short);self.assertNotIn('页：2',short)
  self.assertIn('full-fingerprint',full);self.assertIn('页：2',full);self.assertEqual(d,before)
 def test_unknown_project_text_kept_raw_without_inventing_professional(self):
  r=self.record(src='missing.csv:2',grp='',major='特殊项目说明');self.assertEqual(r['context']['original_major_raw'],'特殊项目说明');self.assertNotIn('major_name',r['context'])

 def test_full_only_and_default_hidden_are_unconditional_presentation_flags(self):
  rows=[self.record(),self.record(grp='02'),self.record(grp='03')]
  rows[1]['default_hidden']=True;rows[2]['full_only']=True;data=self.result(rows);before=copy.deepcopy(data)
  short=db.render_text(data);full=db.render_text(data,full=True)
  self.assertIn('原专业组码：01',short);self.assertNotIn('原专业组码：02',short);self.assertNotIn('原专业组码：03',short)
  self.assertIn('原专业组码：02',full);self.assertIn('原专业组码：03',full);self.assertEqual(data,before)
 def test_third_party_school_location_hidden_but_official_location_visible(self):
  value={'value':'江苏省','grade':'第三方整理','publisher':'汇编','source_id':'x','value_status':{'status':'第三方整理未核'}}
  row={'context':{},'values':{'school_location':value},'source':{'source_id':'x','publisher':'汇编'}}
  data={'sections':[{'table':'school_attribute_fact','title':'学校概况','total':1,'offset':0,'truncated':0,'rows':[row]}]}
  self.assertNotIn('江苏省',db.render_text(data));self.assertIn('江苏省',db.render_text(data,full=True))
  row['values']['school_location']['grade']='官方';self.assertIn('江苏省',db.render_text(data))
 def test_truncated_long_scopes_get_actual_csv_or_record_disambiguators(self):
  prefix='共同专业'*30
  rows=[self.record(src='unknown.csv:2',grp='',major=prefix+'甲'),self.record(src='unknown.csv:3',grp='',major=prefix+'乙')]
  rows[0]['context']['source_record_key']='gk_official_cutoff:101';rows[1]['context']['source_record_key']='gk_official_cutoff:102'
  text=db.render_text(self.result(rows));scopes=[line.split(' | ')[0] for line in text.splitlines() if '600' in line and ' | ' in line]
  self.assertEqual(len(scopes),len(set(scopes)));self.assertIn('记录位置',text)

 def test_annotation_and_background_context_only_full_but_admission_scope_stays(self):
  r=self.record();r['annotation_json']=[['校属旁注','第三方部属标记'],['背景项目','旁注211标记']]
  r['context'].update(school_tags='背景985标签',school_levels='学校层次标签',school_level='办学背景标签',special_plan='国家专项',source_group_code='01',subject_requirements='化学')
  d=self.result([r]);before=copy.deepcopy(d);short=db.render_text(d);full=db.render_text(d,full=True)
  for marker in ('第三方部属标记','旁注211标记','背景985标签','学校层次标签','办学背景标签'):
   self.assertNotIn(marker,short);self.assertIn(marker,full)
  for marker in ('国家专项','原专业组码：01','选科要求：化学'):self.assertIn(marker,short)
  self.assertEqual(d,before)
 def test_uniform_unverified_status_appears_once_default_full_retains_each(self):
  rows=[self.record(),self.record(grp='02')]
  for i,r in enumerate(rows):r['values']={'score':{'value':600+i,'grade':'第三方整理','publisher':'购买汇编','source_id':'s','value_status':{'status':'第三方整理未核'}}}
  d=self.result(rows);before=copy.deepcopy(d);short=db.render_text(d);full=db.render_text(d,full=True)
  self.assertEqual(short.count('第三方整理未核'),1)
  self.assertIn('600〔第三方整理｜购买汇编｜S1〕',short)
  self.assertIn('601〔第三方整理｜购买汇编｜S1〕',short)
  self.assertEqual(full.count('第三方整理未核'),2);self.assertEqual(d,before)
 def test_mixed_statuses_remain_per_value(self):
  rows=[self.record(),self.record(grp='02')]
  for i,r in enumerate(rows):r['values']={'score':{'value':600+i,'grade':'第三方整理','publisher':'购买汇编','source_id':'s','value_status':{'status':'第三方整理未核' if i==0 else '第三方已核一致'}}}
  text=db.render_text(self.result(rows))
  self.assertIn('S1；第三方整理未核〕',text);self.assertIn('S1；第三方已核一致〕',text)
  self.assertNotIn('本块有值记录均为',text)

if __name__=='__main__':unittest.main()
