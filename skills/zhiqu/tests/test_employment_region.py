"""Synthetic location boundaries; no network or real-person data."""
import sqlite3
import unittest
import test_zhiqu_db as fixtures

db=fixtures.db


class EmploymentRegion(unittest.TestCase):
    setUp=fixtures.UnifiedQueries.setUp
    tearDown=fixtures.UnifiedQueries.tearDown

    def totals(self,region,**kw):
        return {s['table']:s['total']for s in db.query_jobs(region=region,db=self.path,**kw)['sections']}

    def test_excluded_city_in_scope_does_not_override_province(self):
        with sqlite3.connect(self.path)as c:
            c.execute('ALTER TABLE competition_stat ADD COLUMN scope TEXT')
            c.execute("UPDATE competition_stat SET province='江苏',scope='省级与已核设区市；苏州分制未核'")
        self.assertNotIn('competition_stat',self.totals('苏州'))
        self.assertEqual(self.totals('江苏')['competition_stat'],1)

    def test_republisher_city_is_not_work_location(self):
        with sqlite3.connect(self.path)as c:
            c.executescript('''CREATE TABLE recruitment_notice(record_id text,region text,year integer,title text,source_id text,status text);
                INSERT INTO recruitment_notice VALUES('n','全国（上海税务网站转载）',2026,'公开招聘公告','s','已取正文');''')
        self.assertNotIn('recruitment_notice',self.totals('上海'))
        self.assertEqual(self.totals('全国')['recruitment_notice'],1)

    def test_scope_can_be_used_only_without_structured_region(self):
        with sqlite3.connect(self.path)as c:
            c.execute('ALTER TABLE wage_stat ADD COLUMN scope TEXT')
            c.execute("UPDATE wage_stat SET region='浙江',scope='杭州'")
        self.assertNotIn('wage_stat',self.totals('杭州'))
        self.assertEqual(self.totals('浙江')['wage_stat'],1)
        with sqlite3.connect(self.path)as c:
            c.executescript('DROP TABLE wage_stat;CREATE TABLE wage_stat(scope text,p50 real,unit text,source_id text);INSERT INTO wage_stat VALUES(\'杭州（企业在岗调查）\',95000,\'元/年\',\'s\');')
        self.assertEqual(self.totals('杭州')['wage_stat'],1)

    def test_city_requires_explicit_label_not_unit_name(self):
        with sqlite3.connect(self.path)as c:
            c.execute('ALTER TABLE job_summary ADD COLUMN unit TEXT')
            c.execute("UPDATE job_summary SET unit='宁波甲单位'")
        self.assertNotIn('job_summary',self.totals('宁波'))
        self.assertEqual(self.totals('浙江')['job_summary'],1)

    def test_normalize_city_suffix_and_hierarchy_without_city_expansion(self):
        for value,query in [('浙江·杭州','杭州'),('浙江省杭州市','杭州'),('浙江省杭州市','浙江'),('浙江省杭州市','浙江省杭州市'),('内蒙古自治区呼和浩特市','呼和浩特')]:
            with self.subTest(value=value,query=query):self.assertTrue(db._employment_region_match(value,query))
        for value,query in [('浙江','杭州'),('杭州市','杭州湾'),('全国','上海'),('江苏苏州市','浙江苏州市')]:
            with self.subTest(value=value,query=query):self.assertFalse(db._employment_region_match(value,query))

    def test_sql_wildcards_and_notes_are_not_region_queries(self):
        for query in ['%','_','州','杭州（上海）','江苏、浙江',"杭州' OR 1=1 --"]:
            with self.subTest(query=query):self.assertFalse(self.totals(query))

    def test_blank_region_can_fall_back_to_province_but_not_scope(self):
        with sqlite3.connect(self.path)as c:
            c.execute('ALTER TABLE wage_stat ADD COLUMN province TEXT')
            c.execute('ALTER TABLE wage_stat ADD COLUMN scope TEXT')
            c.execute("UPDATE wage_stat SET region=' ',province='江苏',scope='苏州未纳入'")
        self.assertNotIn('wage_stat',self.totals('苏州'))
        self.assertEqual(self.totals('江苏')['wage_stat'],1)

    def test_both_explicit_city_and_province_are_preserved(self):
        with sqlite3.connect(self.path)as c:
            c.execute('ALTER TABLE wage_stat ADD COLUMN province TEXT')
            c.execute("UPDATE wage_stat SET region='杭州市',province='浙江省'")
        for place in ['浙江','杭州','浙江省杭州市']:
            with self.subTest(place=place):self.assertEqual(self.totals(place)['wage_stat'],1)

    def test_similar_prefix_does_not_create_province_relationship(self):
        for value,query in [('海南藏族自治州','海南省'),('河北区','河北省'),('上海市税务局','上海'),('江苏苏州','苏州'),('广东省某大学','广东'),('浙江省外','浙江'),('江苏省外','江苏'),('上海以外省份','上海'),('[{上海','上海')]:
            with self.subTest(value=value):self.assertFalse(db._employment_region_match(value,query))

    def test_separate_city_paths_are_not_cross_joined(self):
        value='浙江省杭州市、江苏省苏州市'
        self.assertFalse(db._employment_region_match(value,'浙江省苏州市'))
        self.assertTrue(db._employment_region_match(value,'浙江省杭州市'))
        self.assertTrue(db._employment_region_match(value,'江苏省苏州市'))
        self.assertTrue(db._employment_region_match(value,'苏州'))
        self.assertFalse(db._employment_region_match(value,'浙江省','浙江省苏州市'))

    def test_explicit_province_and_city_homonyms_keep_their_level(self):
        self.assertFalse(db._employment_region_match('吉林市','吉林省'))
        self.assertFalse(db._employment_region_match('吉林省','吉林市'))
        self.assertTrue(db._employment_region_match('吉林省吉林市','吉林省'))
        self.assertTrue(db._employment_region_match('吉林省吉林市','吉林市'))
        self.assertFalse(db._employment_region_match('吉林','吉林市'))
        self.assertFalse(db._employment_region_match('浙江·杭州','杭州市'))
        self.assertTrue(db._employment_region_match('上海','上海市'))

    def test_bare_province_column_is_not_certified_as_same_named_city(self):
        with sqlite3.connect(self.path)as c:
            c.execute("UPDATE competition_stat SET province='吉林'")
        self.assertNotIn('competition_stat',self.totals('吉林市'))
        self.assertEqual(self.totals('吉林省')['competition_stat'],1)
        with sqlite3.connect(self.path)as c:c.execute("UPDATE competition_stat SET province='上海'")
        self.assertEqual(self.totals('上海市')['competition_stat'],1)

    def test_destination_uses_destination_not_school_city(self):
        with sqlite3.connect(self.path)as c:
            c.executescript('''CREATE TABLE graduate_destination(record_id text,source_id text,category text,item text,province_raw text,city_raw text,headcount integer);
                INSERT INTO graduate_destination VALUES('d','v','地区','杭州市','江苏','苏州',10);''')
        self.assertNotIn('graduate_destination',self.totals('苏州'))
        self.assertEqual(self.totals('杭州')['graduate_destination'],1)

    def test_filter_applies_before_count_and_pagination_without_mutation(self):
        with sqlite3.connect(self.path)as c:
            c.execute("INSERT INTO wage_stat VALUES('上海市',2022,'计算机专业人员',12345,'元/年','s','{}','原表匿名格','原表单元格摘录')")
        r=db.query_jobs(region='杭州',db=self.path,limit=1,offset=0)
        sec=next(s for s in r['sections']if s['table']=='wage_stat')
        self.assertEqual(sec['total'],1)
        self.assertEqual(sec['rows'][0]['values']['p50']['value'],95000)
        self.assertTrue(any('转载地' in x for x in r['warnings']))
        self.assertEqual(self.totals('上海')['wage_stat'],1)
        with sqlite3.connect(self.path)as c:self.assertEqual(c.execute('select count(*)from wage_stat').fetchone()[0],2)

    def test_second_and_empty_page_keep_filtered_totals(self):
        with sqlite3.connect(self.path)as c:
            for place,amount in [('杭州市',96000),('上海市',12345),('杭州市',97000)]:
                c.execute("INSERT INTO wage_stat VALUES(?,2022,'计算机专业人员',?,'元/年','s','{}','原表匿名格','原表单元格摘录')",(place,amount))
        for offset,expected in [(1,1),(3,0)]:
            r=db.query_jobs(region='杭州',db=self.path,limit=1,offset=offset)
            sec=next(s for s in r['sections']if s['table']=='wage_stat')
            self.assertEqual(sec['total'],3);self.assertEqual(len(sec['rows']),expected)
            if sec['rows']:self.assertEqual(sec['rows'][0]['values']['p50']['value'],96000)


if __name__=='__main__':unittest.main()
