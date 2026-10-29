"""Offline public-job evidence gates; fixtures are synthetic, never real people."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
sys.path.insert(0,str(SCRIPTS))
import career_on_demand as m


def request(db='unused'):
    return dict(region='杭州市',direction='软件',years=[2026],stage='internship',
                layers=['duties','requirements','pay'],seconds=120,database=str(db),
                entries=[dict(url='https://example.edu.cn/jobs',publisher='合成大学')])


def body(rows=None):
    rows=rows or [['杭州市','2026','软件实习生','维护软件','在校本科生','200元/天'],
                  ['宁波市','2026','软件实习生','维护软件','在校本科生','180元/天'],
                  ['杭州市','2025','软件实习生','维护软件','在校本科生','160元/天']]
    return ('<html><title>合成大学2026实习招聘</title><body><h1>合成大学</h1><table><tr>'+''.join('<th>'+v+'</th>'for v in ['工作地点','招聘年度','岗位名称','岗位职责','任职要求','实习报酬'])+'</tr>'+''.join('<tr>'+''.join('<td>'+v+'</td>'for v in row)+'</tr>'for row in rows)+'</table></body></html>').encode()


def fetched(url,deadline):
    return dict(body=body(),url=url),dict(source_url=url,status='retrieved',raw_original_written=False)


def parsed_result():
    with patch.object(m,'publisher_matches',return_value=True):
        return m.run_request(request(),fetch=fetched,lookup_fn=lambda *_:[])


def database(path):
    c=sqlite3.connect(path)
    c.execute('CREATE TABLE source('+','.join(k+' TEXT'+(' PRIMARY KEY'if k=='source_id'else'')for k in m.SOURCE_COLS)+')')
    c.execute('CREATE TABLE recruitment_notice(record_id TEXT PRIMARY KEY,region TEXT,year INTEGER,title TEXT,source_id TEXT REFERENCES source(source_id),status TEXT,note TEXT,excerpt TEXT,value_status TEXT)')
    c.execute('CREATE TABLE dataset_version(version TEXT PRIMARY KEY,date TEXT,note TEXT)')
    c.execute('INSERT INTO dataset_version VALUES(?,?,?)',('3.0.0','2026-01-01','prior'))
    c.execute('CREATE TABLE provenance_batch(batch_id TEXT PRIMARY KEY,version TEXT,date TEXT,note TEXT)')
    c.execute('CREATE TABLE old_fact(value INTEGER)');c.execute('INSERT INTO old_fact VALUES(42)')
    c.execute('CREATE TABLE check_sample(sample_id TEXT PRIMARY KEY,domain TEXT,table_name TEXT,row_key TEXT,field TEXT,db_value TEXT,official_value TEXT,official_source_id TEXT REFERENCES source(source_id),verdict TEXT,checked_on TEXT,reason TEXT,excerpt TEXT,locator TEXT,reviewer TEXT)')
    c.commit();c.close()


def metadata(directory,*,database_path,output_dir):
    output_dir.mkdir(parents=True)
    (output_dir/'datapackage.json').write_text(json.dumps({'x-database-file':database_path.name,'resources':[{'path':database_path.name}]}))
    (output_dir/'README.md').write_text('generated dictionary')
    (output_dir/'CHANGELOG.md').write_text('generated changelog')
    (output_dir/'VERSION').write_text('3.1.0\n')


class CareerDemandTests(unittest.TestCase):
    def setUp(self):
        self.identity=patch.object(m,'publisher_matches',return_value=True)
        self.identity.start();self.addCleanup(self.identity.stop)

    def test_scope_not_date_city_or_employer_guess(self):
        result=m.parse_table(body(),request()['entries'][0],request())
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['src_row'],2)
        self.assertEqual(result['proofs'][0]['sample_rows'],[2,3,4])

    def test_graduate_cannot_consume_internship(self):
        q=request();q['stage']='graduate'
        with self.assertRaises(m.Gap):m.parse_table(body(),q['entries'][0],q)

    def test_no_scope_table_is_gap(self):
        raw=body().replace('招聘年度'.encode(),'发布日期'.encode())
        with self.assertRaises(m.Gap):m.parse_table(raw,request()['entries'][0],request())

    def test_merged_hidden_and_nested_are_rejected(self):
        for change in ['rowspan="2"','hidden','style="display: none"']:
            with self.subTest(change=change),self.assertRaises(m.Gap):
                m.parse_table(body().replace(b'<td>',('<td '+change+'>').encode(),1),request()['entries'][0],request())

    def test_two_read_disagreement_rejects_whole_file(self):
        original=m.GridReader.handle_data
        def damaged(self,data):original(self,data.replace('200','201'))
        with patch.object(m.GridReader,'handle_data',damaged),self.assertRaises(m.Gap):
            m.parse_table(body(),request()['entries'][0],request())

    def test_personal_columns_or_cells_never_return(self):
        for raw in [body().replace('任职要求'.encode(),'姓名'.encode()),body().replace(b'200',b'13812345678')]:
            with self.subTest(),self.assertRaises(m.Gap):m.parse_table(raw,request()['entries'][0],request())

    def test_candidate_list_not_supported(self):
        with self.assertRaises(m.Gap):m.parse_table(body().replace('实习招聘</title>'.encode(),'实习招聘拟录用名单</title>'.encode()),request()['entries'][0],request())

    def test_no_fabricated_pay(self):
        raw=body().replace('实习报酬'.encode(),'福利说明'.encode())
        result=m.parse_table(raw,request()['entries'][0],request())
        self.assertIsNone(result['rows'][0]['fields']['pay'])

    def test_block_stops_same_host_no_bypass(self):
        calls=[]
        def stop(url,deadline):calls.append(url);return None,{'stop_category':'http_block'}
        q=request();q['entries']*=2
        with patch.object(m,'publisher_matches',return_value=True):r=m.run_request(q,fetch=stop,lookup_fn=lambda *_:[])
        self.assertEqual(len(calls),1);self.assertEqual(len(r['gaps']),2)
        self.assertFalse(r['published'])

    def test_deadline_stops_fetch_and_worker(self):
        times=iter([0,121,122,123])
        def fetch(url,deadline):deadline();self.fail('expired')
        with patch.object(m,'publisher_matches',return_value=True):r=m.run_request(request(),fetch=fetch,lookup_fn=lambda *_:[],clock=lambda:next(times))
        self.assertEqual(r['gaps'][0]['reason'],'取数期限已到')

    def test_cache_does_not_retrieve(self):
        rows=[dict(year=2026,field=f)for f in request()['layers']]
        r=m.run_request(request(),lookup_fn=lambda *_:rows,fetch=lambda *_:self.fail('cache re-fetched'))
        self.assertEqual(r['missing'],[])

    def test_unregistered_publisher_cannot_impersonate(self):
        q=request();q['entries']=[dict(url='https://www.ey.com/x',publisher='假单位')]
        with patch.object(m,'publisher_matches',return_value=False):
            r=m.run_request(q,fetch=lambda *_:self.fail('unapproved issuer'),lookup_fn=lambda *_:[])
        self.assertFalse(r['candidates'])

    def test_private_login_url_not_requested(self):
        q=request();q['entries']=[dict(url='https://example.edu.cn/login',publisher='合成大学')]
        r=m.run_request(q,fetch=lambda *_:self.fail('restricted fetch'),lookup_fn=lambda *_:[])
        self.assertFalse(r['candidates'])

    def test_source_hash_and_only_anonymous_rows(self):
        r=parsed_result();bundle=r['candidates'][0]
        self.assertEqual(bundle['source']['archive_sha256'],hashlib.sha256(body()).hexdigest())
        self.assertEqual(bundle['rows'][0]['fields']['pay'],'200元/天')
        self.assertNotIn('<html>',json.dumps(r))

    def test_publish_atomic_and_old_reader_stays_valid(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db)
            old=sqlite3.connect(db);out=root/'run'
            r=parsed_result()
            receipt=m.publish_result(r,db,out,m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            self.assertTrue(receipt['published']);self.assertEqual(receipt['rows'],1)
            self.assertEqual(old.execute('select count(*)from recruitment_notice').fetchone()[0],0)
            self.assertEqual(sqlite3.connect(db).execute('select value from old_fact').fetchone()[0],42)
            self.assertEqual(json.loads((root/'datapackage.json').read_text())['resources'][0]['path'],'employment.sqlite')
            hit=m.lookup(db,request(db));self.assertEqual(len(hit),3)
            self.assertEqual(hit[0]['grade'],'官方');old.close()

    def test_failed_validation_does_not_replace(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db);before=db.read_bytes()
            with self.assertRaises(m.Gap):m.publish_result(parsed_result(),db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:1)
            self.assertEqual(db.read_bytes(),before)

    def test_expired_and_legacy_not_reused(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db)
            m.publish_result(parsed_result(),db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            with sqlite3.connect(db)as c:
                c.execute("update check_sample set checked_on='2000-01-01'")
            self.assertEqual(m.lookup(db,request(db)),[])

    def test_same_original_reverification_refreshes_without_fact_duplicate(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db)
            m.publish_result(parsed_result(),db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            with sqlite3.connect(db)as c:
                c.execute("update check_sample set sample_id='historic',checked_on='2000-01-01'")
            self.assertEqual(m.lookup(db,request(db)),[])
            receipt=m.publish_result(parsed_result(),db,root/'renew',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            self.assertTrue(receipt['published']);self.assertEqual(receipt['rows'],0)
            self.assertEqual(sqlite3.connect(db).execute('select count(*)from recruitment_notice').fetchone()[0],1)
            self.assertEqual(len(m.lookup(db,request(db))),3)

    def test_prose_title_contact_rejected(self):
        for marker in ['负责人张三 13812345678','姓名合成人名','考号1234567','身份证未知']:
            raw=body().replace('</title>'.encode(),(marker+'</title>').encode())
            with self.subTest(marker=marker),self.assertRaises(m.Gap):m.parse_table(raw,request()['entries'][0],request())

    def test_visibility_hidden_not_visible_evidence(self):
        with self.assertRaises(m.Gap):m.parse_table(body().replace(b'<table>',b'<table style="visibility:hidden">'),request()['entries'][0],request())

    def test_social_job_is_not_graduate(self):
        q=request();q['stage']='graduate'
        with self.assertRaises(m.Gap):m.parse_table(body().replace('软件实习生'.encode(),'软件工程师'.encode()),q['entries'][0],q)

    def test_timeout_after_commit_must_not_claim_unpublished(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db)
            m.publish_result(parsed_result(),db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            self.assertTrue(m.publication_state(root/'run',db).startswith('已发布'))
            (root/'run/publication.json').unlink()
            self.assertTrue(m.publication_state(root/'run',db).startswith('发布状态待核'))

    def test_interrupted_publication_recovers_own_db_and_dictionary(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db);before=db.read_bytes()
            m.publish_result(parsed_result(),db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            (root/'run/publication.json').unlink()
            self.assertTrue(m.recover_publication(root/'run',db).startswith('未发布（已恢复'))
            self.assertEqual(db.read_bytes(),before)
            self.assertFalse((root/'datapackage.json').exists())

    def test_recovery_never_overwrites_someone_elses_change(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db)
            m.publish_result(parsed_result(),db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            (root/'run/publication.json').unlink()
            with sqlite3.connect(db)as c:c.execute('insert into old_fact values(43)')
            after=db.read_bytes()
            self.assertIn('其他变化',m.recover_publication(root/'run',db))
            self.assertEqual(db.read_bytes(),after)

    def test_wrong_existing_source_identity_is_not_overwritten(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db);r=parsed_result()
            wrong=dict(r['candidates'][0]['source'],publisher='错误单位')
            with sqlite3.connect(db)as c:c.execute('INSERT INTO source VALUES('+','.join('?'for _ in m.SOURCE_COLS)+')',[wrong[k]for k in m.SOURCE_COLS])
            before=db.read_bytes()
            with self.assertRaises(m.Gap):m.publish_result(r,db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            self.assertEqual(db.read_bytes(),before)

    def test_query_shows_fields_and_original_units(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db)
            m.publish_result(parsed_result(),db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            result=m.zhiqu_db.query_jobs(region='杭州市',major='软件',year=2026,db=db)
            row=result['sections'][0]['rows'][0]
            self.assertEqual(row['values']['报酬原文']['value'],'200元/天')
            self.assertEqual(row['values']['报酬原文']['grade'],'官方')
            self.assertEqual(row['locator']['src_row'],2)
            rendered=m.zhiqu_db.render_text(result)
            self.assertIn('200元/天',rendered)
            self.assertNotIn('career-table-evidence-v1',rendered)
            source=m.zhiqu_db.query_source(row['source']['source_id'],domain='employment',db=db)
            self.assertEqual(source['locations'][0]['locator']['src_row'],2)
            self.assertIn('已核匿名',source['locations'][0]['excerpt_kind'])

    def test_absent_pay_is_cached_as_not_provided_not_zero(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db)
            def without_pay(url,deadline):return dict(url=url,body=body().replace('实习报酬'.encode(),'其他福利'.encode())),{}
            r=m.run_request(request(),fetch=without_pay,lookup_fn=lambda *_:[])
            m.publish_result(r,db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            cached=m.run_request(request(db),fetch=lambda *_:self.fail('not-provided re-fetched'))
            self.assertEqual(cached['missing'],[])
            self.assertIn('来源未提供',m.text_summary(cached))

    def test_candidate_cross_city_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);db=root/'employment.sqlite';database(db);r=parsed_result()
            r['candidates'][0]['rows'][0]['region']='宁波市'
            before=db.read_bytes()
            with self.assertRaises(m.Gap):m.publish_result(r,db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
            self.assertEqual(db.read_bytes(),before)


if __name__=='__main__':unittest.main()
