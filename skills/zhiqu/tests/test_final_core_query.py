"""Optional core-delta query support, using fictional temporary databases only."""
import importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts/zhiqu_db.py'
spec=importlib.util.spec_from_file_location('final_core_query_db',SCRIPT)
db=importlib.util.module_from_spec(spec);spec.loader.exec_module(db)

class CoreDeltaQuery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'education.sqlite';self.c=sqlite3.connect(self.path);self.addCleanup(self.c.close)
  self.c.executescript('''
   CREATE TABLE institution(institution_id TEXT,name TEXT,moe_code TEXT,province TEXT,status TEXT);
   INSERT INTO institution VALUES('i1','甲大学','10001','江苏','在办');
   CREATE TABLE source(source_id TEXT,grade TEXT,publisher TEXT,archive_status TEXT);
   INSERT INTO source VALUES('official','官方','甲大学招生办公室','已存原件');
   CREATE TABLE gk_v_usable(record_id TEXT,institution_id TEXT,year INTEGER,min_score REAL,source_id TEXT,value_status TEXT);
   INSERT INTO gk_v_usable VALUES('legacy','i1',2024,600,'official','{}');
  ''');self.c.commit()
 def views(self):
  columns='''record_id TEXT,source_id TEXT,vendor_source_id TEXT,institution_id TEXT,year INTEGER,province TEXT,subject TEXT,batch TEXT,school_raw TEXT,school_code TEXT,group_code TEXT,major_code TEXT,major_name TEXT,plan_type TEXT,scope_raw TEXT,field_name TEXT,field_label TEXT,value,raw_value,unit TEXT,value_status TEXT,src_sheet TEXT,src_row INTEGER,src_col TEXT,official_locator TEXT,major_full TEXT,school_group_code TEXT,group_name TEXT,subject_requirements TEXT,old_batch TEXT,duration TEXT,comparison_status TEXT,record_type TEXT,dataset_type TEXT,other_province_raw TEXT,year_status TEXT,province_status TEXT'''
  for kind in ('number','attribute'):
   self.c.execute('CREATE TABLE core_'+kind+'('+columns+')');self.c.execute('CREATE VIEW v_core_delta_'+kind+' AS SELECT * FROM core_'+kind)
  self.c.executescript('''CREATE TABLE core_delta_source(source_key INTEGER,source_id TEXT,existing_source_id TEXT,sha256 TEXT,relative_path TEXT,size INTEGER,category TEXT,province TEXT,year_hint INTEGER,status TEXT);
   INSERT INTO core_delta_source VALUES(1,'vendor',NULL,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','gaokao/合成统计.xlsx',123,'专业录取分','江苏',2025,'imported|originals_deleted');''');self.c.commit()
 def insert(self,kind='number',**changes):
  row=dict(record_id='a',source_id='vendor',vendor_source_id='vendor',institution_id='i1',year=2025,province='江苏',subject='物理',batch='本科批',school_raw='甲大学',school_code='10001',group_code='01',major_code='080901',major_name='计算机科学与技术',plan_type='普通类',scope_raw='[["备注","仅限校区A"]]',field_name='composite_score',field_label='综合分',value=612.5,raw_value='612.5分',unit='分',value_status='第三方整理未核',src_sheet='合成工作表',src_row=12,src_col='G',official_locator=None)
  row.update(changes);self.c.execute('INSERT INTO core_'+kind+'('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',list(row.values()));self.c.commit()
 def query(self,**kwargs):return db.query_school('甲大学',db=self.path,**kwargs)
 def section(self,**kwargs):return next(x for x in self.query(**kwargs)['sections'] if x['table']=='core_delta')
 def test_full_major_and_group_scope_displayed(self):
  self.views();self.insert(major_full='计算机科学与技术（联合培养）',school_group_code='10001-01',group_name='联合培养组',duration='四年')
  text=db.render_text(self.query())
  for value in ('计算机科学与技术（联合培养）','10001-01','联合培养组','四年'):self.assertIn(value,text)
 def test_unconfirmed_year_display_does_not_reuse_package_hint(self):
  self.views();self.insert(year=None,year_status='年份未确认：原表未核实')
  result=self.query();row=self.section()['rows'][0]
  self.assertNotIn('year',row['context'])
  self.assertEqual(row['context']['year_status'],'年份未确认：原表未核实')
  self.assertIn('年份状态：年份未确认',db.render_text(result))
  self.assertFalse(any(s['table']=='core_delta' for s in self.query(year=2025)['sections']))
 def test_missing_province_is_shown_as_unconfirmed_and_not_filter_matched(self):
  self.views();self.insert(province=None,province_status='省份未确认：原行无明确省份')
  text=db.render_text(self.query())
  self.assertIn('省份依据状态：省份未确认',text)
  self.assertFalse(any(s['table']=='core_delta' for s in self.query(province='江苏')['sections']))
 def test_source_unfilled_scope_is_visible_even_when_common_source_exists(self):
  self.views();self.insert()
  self.c.execute("INSERT INTO source VALUES('vendor','第三方整理','汇编整理方','已按授权删除')")
  self.c.execute('ALTER TABLE core_delta_source ADD COLUMN unfilled_reason TEXT')
  self.c.execute("UPDATE core_delta_source SET unfilled_reason='尚有2种未映射列；province_unconfirmed'");self.c.commit()
  text=db.render_text(self.query())
  self.assertIn('来源仍有未补或未解释内容',text);self.assertIn('省份缺少原行依据',text)
  self.assertNotIn('province_unconfirmed',text)
 def test_absent_views_exact_legacy_result(self):
  before=self.query();self.views();after=self.query()
  self.assertEqual(before,after)
  self.assertEqual([s['table'] for s in before['sections']],['gk_v_usable'])
 def test_number_source_fallback_scope_and_position(self):
  self.views();self.insert();result=self.query();section=result['sections'][-1]
  self.assertEqual(section['title'],'本轮补录字段');r=section['rows'][0];v=r['values']['composite_score']
  self.assertEqual(v['value'],612.5);self.assertEqual(v['grade'],'第三方整理');self.assertEqual(v['publisher'],'购买汇编');self.assertEqual(v['locator'],{'src_sheet':'合成工作表','src_row':12,'src_col':'G'})
  source=r['source'];self.assertEqual(source['archive_sha256'],'a'*64);self.assertIsNone(source['archive_path']);self.assertEqual(source['original_relative_path'],'gaokao/合成统计.xlsx');self.assertEqual(source['archive_status'],'已按用户授权删除');self.assertNotIn('landing_url',source)
  self.assertEqual(r['context']['scope_raw'],'[["备注","仅限校区A"]]');self.assertIsNone(r['excerpt'])
  text=db.render_text(result)
  for word in ('综合分：612.5 分','第三方整理｜购买汇编｜S1','出处：vendor','行：12','原表范围说明','仅限校区A'):self.assertIn(word,text)
  self.assertNotIn('最低分：612.5',text)
 def test_text_attribute_and_rank_label_are_not_reinterpreted(self):
  self.views();self.insert(kind='attribute',record_id='b',field_name='subject_requirements',field_label='选科要求',value='物理且化学',raw_value='物理且化学',unit='')
  self.insert(field_name='rank_number',field_label='位次号',value=1234,unit='位')
  text=db.render_text(self.query());self.assertIn('选科要求：物理且化学〔第三方整理',text);self.assertIn('位次号：1234 位',text);self.assertNotIn('最低位次：1234',text)
 def test_official_correction_has_own_locator_vendor_preserved(self):
  self.views();self.insert(source_id='official',value=620,official_locator='官方招生公告 第2页 表1 G8')
  row=self.section()['rows'][0];v=row['values']['composite_score'];self.assertEqual(v['grade'],'官方');self.assertEqual(v['source_id'],'official');self.assertEqual(v['original_source_id'],'vendor')
  self.assertEqual(row['original_locator']['src_row'],12);self.assertNotIn('src_row',row['locator']);self.assertNotIn('locator',v)
  text=db.render_text(self.query());self.assertIn('官方位置：官方招生公告 第2页 表1 G8',text);self.assertIn('原始单元格定位：工作表：合成工作表；行：12',text)
 def test_missing_official_locator_never_borrows_purchase_row(self):
  self.views();self.insert(source_id='official')
  row=self.section()['rows'][0];self.assertIsNone(row['values']['composite_score']['official_locator']);self.assertNotIn('src_row',row['locator'])
  self.assertIn('官方位置：未取到',db.render_text(self.query()))
 def test_old_source_wins_over_delta_fallback(self):
  self.views();self.c.execute("INSERT INTO source VALUES('vendor','第三方整理','原有登记单位','原有存档状态')");self.c.commit();self.insert()
  self.assertEqual(self.section()['rows'][0]['source']['publisher'],'原有登记单位')
  self.assertEqual(db.query_source('vendor',db=self.path)['source']['archive_status'],'原有存档状态')
 def test_filters_school_and_program_pagination_across_both_views(self):
  self.views();self.insert(record_id='a');self.insert(kind='attribute',record_id='b',field_name='requirement',field_label='选科要求',value='物化')
  self.insert(record_id='c',year=2024);self.insert(record_id='d',province='浙江');self.insert(record_id='e',major_name='哲学',major_code='010101');self.insert(record_id='f',subject='历史');self.insert(record_id='g',plan_type='专项')
  kwargs=dict(year=2025,province='江苏',major='计算机',subject='物理类',plan_type='普通类',limit=1,offset=1)
  s=self.section(**kwargs);self.assertEqual((s['total'],s['returned'],s['truncated']),(2,1,0));self.assertEqual(s['rows'][0]['record_id'],'b')
  r=db.query_program('甲大学','0809',db=self.path,**kwargs);s=r['sections'][-1];self.assertEqual(s['total'],2);self.assertEqual(s['rows'][0]['record_id'],'b')
  self.assertIn('原专业码前缀',r['warnings'][0])
 def test_zero_null_and_label_fallback(self):
  self.views();self.insert(value=0,field_label='');self.insert(kind='attribute',record_id='b',value=None,value_status='来源未提供',field_name='attribute_unknown',field_label='原表补充条件',unit='')
  s=self.section();self.assertEqual(s['rows'][0]['values']['composite_score']['value'],0)
  text=db.render_text(self.query());self.assertIn('composite_score：0 分',text);self.assertIn('原表补充条件：来源未提供',text)
 def test_alias_year_bounds_preserved_for_delta(self):
  self.views();self.insert();self.insert(record_id='older',year=2024)
  self.c.executescript("CREATE TABLE institution_alias(institution_id TEXT,alias TEXT,year INTEGER,year_from INTEGER,year_to INTEGER); INSERT INTO institution_alias VALUES('i1','旧甲大学',NULL,2025,2025);");self.c.commit()
  r=db.query_school('旧甲大学',db=self.path);s=r['sections'][-1];self.assertEqual(s['total'],1);self.assertEqual(s['rows'][0]['context']['year'],2025)
 def test_single_optional_view_supported(self):
  self.views();self.c.execute('DROP VIEW v_core_delta_attribute');self.c.commit();self.insert();self.assertEqual(self.section()['total'],1)
 def test_source_fallback_can_be_queried_without_fabricated_urls(self):
  self.views();r=db.query_source('vendor',db=self.path)
  self.assertEqual(r['source']['archive_sha256'],'a'*64);self.assertNotIn('file_url',r['source']);self.assertNotIn('landing_url',r['source'])

 def test_view_column_order_does_not_cross_bind_values(self):
  self.views();self.insert();self.insert(kind='attribute',record_id='b',field_name='subject_requirements',field_label='选科要求',value='物化',unit='')
  self.c.execute('DROP VIEW v_core_delta_attribute')
  columns=list(reversed(db.CORE_DELTA_COLUMNS))
  self.c.execute('CREATE VIEW v_core_delta_attribute AS SELECT '+','.join(columns)+' FROM core_attribute');self.c.commit()
  row=self.section()['rows'][1]
  self.assertEqual(row['values']['subject_requirements']['value'],'物化');self.assertEqual(row['source']['source_id'],'vendor');self.assertEqual(row['context']['year'],2025)

 def test_fallback_archive_status_tracks_actual_deletion_marker(self):
  self.views()
  for status in ('imported','validated|staged','',None):
   self.c.execute('UPDATE core_delta_source SET status=?',(status,));self.c.commit()
   source=db.query_source('vendor',db=self.path)['source']
   self.assertEqual(source['archive_status'],'临时原件待清理（有指纹）');self.assertEqual(source['source_record_status'],status);self.assertEqual(source['archive_path'],'gaokao/合成统计.xlsx');self.assertEqual(source['original_relative_path'],'gaokao/合成统计.xlsx')
  for status in ('imported|originals_deleted','已删除'):
   self.c.execute('UPDATE core_delta_source SET status=?',(status,));self.c.commit()
   source=db.query_source('vendor',db=self.path)['source'];self.assertEqual(source['archive_status'],'已按用户授权删除');self.assertIsNone(source['archive_path']);self.assertEqual(source['original_relative_path'],'gaokao/合成统计.xlsx')

 def test_core_only_sections_apply_gaokao_comparability_domain(self):
  self.views();self.insert()
  self.c.executescript("CREATE TABLE comparability(domain TEXT,scope TEXT,effective_year INTEGER,change TEXT,impact TEXT,source_id TEXT); INSERT INTO comparability VALUES('高考','甲大学',2025,'高考口径变化','须独立比较','official'); INSERT INTO comparability VALUES('考研','甲大学',2025,'考研口径变化','另一个范围','official');");self.c.commit()
  result=self.query(year=2025)
  self.assertEqual([s['table'] for s in result['sections']],['core_delta'])
  self.assertTrue(any('高考口径变化' in w for w in result['warnings']));self.assertFalse(any('考研口径变化' in w for w in result['warnings']))

 def test_empty_column_locator_is_explicitly_unresolved(self):
  self.views();self.insert(kind='attribute',src_col='',field_name='scope_raw',field_label='原表范围',value='仅限校区A')
  row=self.section()['rows'][0];value=row['values']['scope_raw']
  self.assertNotIn('src_col',value['locator']);self.assertEqual(value['locator']['src_row'],12)
  self.assertIn('未唯一确定',value['locator']['locator_status']);self.assertIn('不能视为逐值列定位完整',db.render_text(self.query()))

if __name__=='__main__':unittest.main()
