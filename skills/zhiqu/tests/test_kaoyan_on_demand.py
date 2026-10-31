"""Offline orchestration/adapters: all HTTP and publication are injected fakes."""
import contextlib
import hashlib
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SHARED = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'
sys.path.insert(0, str(SHARED))
import kaoyan_on_demand as tool
import kaoyan_adapters as adapters

IDENTITY = {'name': '合成大学', 'institution_id': '4100000001'}
URL = 'https://fixture.edu.cn/2026/lines.html'


def page(table, title='合成大学2026年硕士复试分数线'):
    return ('<html><meta charset="utf-8"><title>'+title+'</title><body>'+table+'</body></html>').encode()


def line_page():
    return page('<table><tr><th>专业代码</th><th>专业名称</th><th>总分</th></tr>'
                '<tr><td>085404</td><td>计算机技术</td><td>300</td></tr></table>')


def roster(n, score_header='初试总分'):
    # Synthetic privacy sentinels are intentionally passed only to in-memory parsing.
    rows = ''.join('<tr><td>085404</td><td>合成隐私标记'+str(i)+'</td>'
                   '<td>12345678901234'+str(i)+'</td><td>'+str(300+i)+'</td></tr>' for i in range(n))
    return page('<table><tr><th>专业代码</th><th>姓名</th><th>考生号</th><th>'+score_header+
                '</th></tr>'+rows+'</table>', '合成大学2026年硕士拟录取名单')


class FakeClock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


class OnDemandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'tiny.sqlite'
        with sqlite3.connect(self.db) as c:
            c.execute('create table source(source_id text primary key,grade text,publisher text,title text,landing_url text,file_url text,published text,retrieved text,archive_sha256 text)')
            for table in ['ky_retest_line', 'ky_program_year', 'ky_score_dist']:
                c.execute('create table '+table+'(record_id text,institution_id text,year integer,program_code text,source_id text,program_name text,'
                          'total real,politics real,english real,math real,major1 real,major2 real,line_scope text,college text,special_plan text,'
                          'planned integer,tuimian integer,subjects text,study_mode text,verification_status text,direction text,n integer,min real,median real,max real,list_type text,admission_route text)')
        self.request = dict(database=str(self.db), school='合成大学', programs=['0854'], years=[2026],
                            layers=['lines'], seconds=120, output=str(self.root/'out'),
                            coverage=str(self.root/'coverage.csv'), entries=[URL])
        self.clock = FakeClock()

    def tearDown(self):
        self.tmp.cleanup()

    def cells(self, obtained=False, years=None):
        return [dict(year=y, layer='lines', program='0854', obtained=obtained,
                     existing_rows=int(obtained), source_ids=['s'] if obtained else [])
                for y in (years or [2026])]

    def run_fake(self, *, cells=None, fetch=None, publisher=None, entry=None):
        fetch = fetch or Mock(return_value=({'body': line_page()}, {'url': URL, 'http_status': 200}))
        publisher = publisher or Mock(return_value={'published': True})
        with patch.object(tool, 'resolve_school', return_value=(IDENTITY, entry if entry is not None else {'known_official_document_entry_url': URL}, [])):
            summary = tool.run_request(self.request, registry=[], lookup_fn=Mock(return_value=cells or self.cells()),
                                       fetch=fetch, publisher=publisher, clock=self.clock)
        return summary, fetch, publisher

    @contextlib.contextmanager
    def opened(self, *args):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.execute('attach database ? as data', (str(self.db),))
        try:
            yield c, None
        finally:
            c.close()

    def lookup(self, grade, status):
        with sqlite3.connect(self.db) as c:
            c.execute('insert into source(source_id,grade) values(?,?)', ('s', grade))
            c.execute('insert into ky_retest_line(record_id,institution_id,year,program_code,source_id) values(?,?,?,?,?)', ('r', IDENTITY['institution_id'], 2026, '085404', 's'))
            c.execute("update ky_retest_line set verification_status='原文审核通过' where record_id='r'")
        coverage = [dict(school='合成大学', year='2026', scope_level='学院专业资格线', status=status)]
        with patch.object(tool.zhiqu_db, '_open', side_effect=self.opened):
            return tool.lookup(self.db, IDENTITY, ['0854'], [2026], ['lines'], coverage)

    def test_pdf_attachment_reaches_automatic_reader_and_publisher(self):
        parsed=adapters.parse_official_html(line_page(),URL,IDENTITY,2026,'lines',['0854'])
        fetch=Mock(return_value=({'body':b'%PDF-real-content','url':URL},{'url':URL,'http_status':200}))
        with patch.object(tool,'parse_official_document',return_value=parsed)as reader:
            summary,_,publisher=self.run_fake(fetch=fetch)
        self.assertEqual(reader.call_count,1)
        self.assertTrue(summary['published'])
        self.assertEqual(publisher.call_count,1)
        self.assertIn('数据相关',summary['outcomes'][0]['entry_results'][0]['reason'])

    def test_pdf_mismatch_is_a_gap_and_no_publication(self):
        fetch=Mock(return_value=({'body':b'%PDF-real-content','url':URL},{'url':URL,'http_status':200}))
        with patch.object(tool,'parse_official_document',side_effect=adapters.NeedsReview('第三读抽核不一致，整份未入')):
            summary,_,publisher=self.run_fake(fetch=fetch)
        self.assertFalse(summary['published']);publisher.assert_not_called()
        self.assertIn('第三读',summary['outcomes'][0]['reason'])

    def test_unanchored_catalogue_numeric_row_cannot_disappear(self):
        body=page('<table><tr><th>专业代码</th><th>专业名称</th><th>招生人数</th></tr>'
                  '<tr><td>085404</td><td>计算机技术</td><td>10</td></tr>'
                  '<tr><td></td><td>未明确归属的续行</td><td>3</td></tr></table>',
                  '合成大学2026年硕士招生专业目录')
        with self.assertRaisesRegex(adapters.NeedsReview,'专业代码不明确'):
            adapters.parse_official_html(body,URL,IDENTITY,2026,'catalog',['0854'])

    def test_line_retains_explicit_subjects_without_inventing_shared_subject(self):
        blob=page('<table><tr><th>专业代码</th><th>总分</th><th>政治</th><th>英语</th><th>单科（满分&gt;100分）</th></tr><tr><td>085404</td><td>300</td><td>40</td><td>45</td><td>60</td></tr></table>')
        parsed=adapters.parse_official_html(blob,URL,IDENTITY,2026,'lines',['0854'])
        item=parsed['manifest']['rows'][0]
        self.assertEqual((item['row']['politics'],item['row']['english']),(40,45))
        self.assertIsNone(item['row']['math'])
        self.assertEqual(item['components'],{'single_gt100':60})

    def test_unmapped_subject_header_is_not_claimed_missing_from_original(self):
        blob=page('<table><tr><th>专业代码</th><th>总分</th><th>综合单科门槛</th></tr><tr><td>085404</td><td>300</td><td>70</td></tr></table>')
        with self.assertRaises(adapters.NeedsReview):adapters.parse_official_html(blob,URL,IDENTITY,2026,'lines',['0854'])

    def test_inline_title_fragments_are_one_original_heading_for_each_layer(self):
        tables={'lines':'<table><tr><th>专业代码</th><th>总分</th></tr><tr><td>085404</td><td>300</td></tr></table>',
                'catalog':'<table><tr><th>专业代码</th><th>招生人数</th></tr><tr><td>085404</td><td>9</td></tr></table>',
                'stats':'<table><tr><th>专业代码</th><th>初试总分</th></tr>'+''.join('<tr><td>085404</td><td>'+str(x)+'</td></tr>'for x in [300,301,302])+'</table>'}
        names={'lines':'复试分数线','catalog':'招生专业目录','stats':'拟录取名单'}
        for layer,table in tables.items():
            with self.subTest(layer=layer):
                heading='<h1>合成大学<span>2026</span>年<strong>硕士研究生</strong><em>'+names[layer]+'</em></h1>'
                result=adapters.parse_official_html(page(heading+table,'合成大学研究生院'),URL,IDENTITY,2026,layer,['0854'])
                self.assertEqual(result['rows'],1)
                self.assertTrue(result['proofs'][0]['sample_passed'])
                if layer=='stats':self.assertEqual(result['manifest']['rows'][0]['n'],3)
                else:self.assertEqual(result['manifest']['sources'][0]['title'],'合成大学2026年硕士研究生'+names[layer])

    def test_title_fragments_cannot_be_borrowed_from_other_headings_or_body(self):
        table='<table><tr><th>专业代码</th><th>总分</th></tr><tr><td>085404</td><td>300</td></tr></table>'
        for heading in ['<h1>合成大学2026年通知</h1><h2>合成大学2025年硕士复试分数线</h2>',
                        '<h1>合成大学硕士复试分数线</h1><p>2026</p>']:
            with self.subTest(kind=heading[:4]),self.assertRaises(adapters.NeedsReview):
                adapters.parse_official_html(page(heading+table,'合成大学研究生院'),URL,IDENTITY,2026,'lines',['0854'])

    def test_scripts_styles_comments_are_not_heading_scope_evidence(self):
        table='<table><tr><th>专业代码</th><th>总分</th></tr><tr><td>085404</td><td>300</td></tr></table>'
        for fragment in ['<script>2026年硕士复试分数线</script>',
                         '<style>2026年硕士复试分数线</style>',
                         '<!--2026年硕士复试分数线-->']:
            with self.subTest(kind=fragment[:8]),self.assertRaises(adapters.NeedsReview):
                adapters.parse_official_html(page('<h1>合成大学'+fragment+'</h1>'+table,'合成大学研究生院'),URL,IDENTITY,2026,'lines',['0854'])

    def test_inline_heading_is_kept_through_on_demand_manifest(self):
        table='<h1>合成大学<span>2026</span>年<strong>硕士</strong>复试分数线</h1><table><tr><th>专业代码</th><th>总分</th></tr><tr><td>085404</td><td>300</td></tr></table>'
        blob=page(table,'合成大学研究生院')
        summary,fetch,publisher=self.run_fake(fetch=Mock(return_value=({'body':blob,'url':URL},{'status':'retrieved'})))
        self.assertEqual(summary['outcomes'][0]['status'],'obtained');publisher.assert_called_once()
        manifest=json.loads((self.root/'out/reviewed-manifest-1.json').read_text())['manifest']
        self.assertEqual(manifest['sources'][0]['title'],'合成大学2026年硕士复试分数线')
        self.assertEqual(manifest['rows'][0]['row']['total'],300)

    def test_doctoral_or_unmarked_catalogue_is_not_masters(self):
        for title in ['合成大学2026年博士招生专业目录', '合成大学2026年招生专业目录']:
            with self.subTest(title=title), self.assertRaises(adapters.NeedsReview):
                adapters.parse_official_html(page('<table><tr><th>专业代码</th><th>招生人数</th></tr><tr><td>085404</td><td>9</td></tr></table>',title),URL,IDENTITY,2026,'catalog',['0854'])

    def test_chsi_global_navigation_is_not_school_document(self):
        body=page('<a href="/zsml/">招生目录</a><a href="/kyzx/zsjz/">招生简章</a>'
                  '<a href="/sch/viewZszc--infoId-1.dhtml">2026年硕士招生目录</a>')
        links=tool.discover_links(body,'https://yz.chsi.com.cn/sch/schoolInfo--schId-1.dhtml',2026,'catalog')
        self.assertEqual(links,['https://yz.chsi.com.cn/sch/viewZszc--infoId-1.dhtml'])

    def test_prior_recorded_block_is_not_requested(self):
        ledger=self.root/'stops.json'
        ledger.write_text(json.dumps([{'url':URL,'stop_category':'http_block'}]))
        self.request['stop_ledger']=str(ledger)
        summary,fetch,publisher=self.run_fake()
        fetch.assert_not_called();publisher.assert_not_called()
        self.assertEqual(summary['outcomes'][0]['attempted_entries'],[])
        self.assertEqual(summary['outcomes'][0]['not_retried_entries'],[URL])

    def test_old_tls_failure_is_not_a_permanent_captcha_stop(self):
        ledger=self.root/'stops.json'
        ledger.write_text(json.dumps([{'url':URL,'stop_category':'tls'}]))
        self.request['stop_ledger']=str(ledger)
        summary,fetch,publisher=self.run_fake()
        fetch.assert_called_once();publisher.assert_called_once()
        self.assertEqual(summary['outcomes'][0]['status'],'obtained')

    def test_unconfirmed_redirect_cannot_become_official_source(self):
        fetch=Mock(return_value=({'body':line_page(),'url':'https://unconfirmed.example/a'},
                                 {'status':'retrieved'}))
        summary,fetch,publisher=self.run_fake(fetch=fetch)
        publisher.assert_not_called()
        self.assertEqual(summary['outcomes'][0]['status'],'not fetched')
        self.assertIn('未经确认的域名',summary['outcomes'][0]['reason'])

    def test_last_tls_failure_does_not_hide_readable_unconfirmed_page(self):
        second=URL+'?second=1'
        self.request['entries']=[URL,second]
        wrong=page('<p>公开学校介绍，没有所问年份的硕士原表。</p>', '合成大学学校介绍')
        fetch=Mock(side_effect=[({'body':wrong,'url':URL},{'http_status':200}),
                                (None,{'stop_category':'tls'})])
        summary,fetch,publisher=self.run_fake(fetch=fetch)
        result=summary['outcomes'][0]
        publisher.assert_not_called()
        self.assertEqual(len(result['entry_results']),2)
        self.assertIn('原页标题',result['entry_results'][0]['reason'])
        self.assertIn('tls',result['entry_results'][1]['reason'])
        self.assertIn('原页标题',result['reason'])
        self.assertIn('tls',result['reason'])
        self.assertIn('原页标题',(self.root/'out'/'README.md').read_text())

    def test_confirmed_redirect_uses_actual_original_url(self):
        final_url=URL+'?actual=1'
        fetch=Mock(return_value=({'body':line_page(),'url':final_url},{'status':'retrieved'}))
        summary,fetch,publisher=self.run_fake(fetch=fetch)
        self.assertEqual(summary['outcomes'][0]['status'],'obtained')
        manifest=json.loads((self.root/'out/reviewed-manifest-1.json').read_text())['manifest']
        self.assertEqual(manifest['sources'][0]['landing_url'],final_url)

    def test_roster_title_is_not_copied_into_any_statistic(self):
        private_title='合成大学2026年硕士拟录取名单（合成人名甲等）'
        blob=roster(3).replace('合成大学2026年硕士拟录取名单'.encode(),private_title.encode())
        result=adapters.parse_official_html(blob,URL,IDENTITY,2026,'stats',['0854'])
        encoded=json.dumps(result,ensure_ascii=False)
        self.assertNotIn('合成人名甲',encoded)
        self.assertEqual(result['rows'],1)

    def test_bom_and_late_table_are_still_html(self):
        blob=b'\xef\xbb\xbf'+line_page().replace(b'<body>',b'<head>'+b'<!--pad-->'*3000+b'</head><body>')
        summary,fetch,publish=self.run_fake(fetch=Mock(return_value=({'body':blob},{'status':'retrieved'})))
        self.assertEqual(summary['outcomes'][0]['status'],'obtained')
        publish.assert_called_once()

    def test_duplicate_chsi_entries_for_same_unit_code_resolve_same_identity(self):
        registry=[dict(school=name,admission_unit_code='12345',institution_id=IDENTITY['institution_id'])for name in ['合成大学','合成大学研究生院']]
        with patch.object(tool.zhiqu_db,'_open',side_effect=self.opened),patch.object(tool.zhiqu_db,'_identity',return_value=(IDENTITY,[]))as resolve:
            identity,entry,warnings=tool.resolve_school(self.db,'12345',registry)
        resolve.assert_called_once_with(unittest.mock.ANY,IDENTITY['institution_id'])
        self.assertEqual(identity,IDENTITY)

    def test_ambiguous_school_writing_does_not_choose_one_institution(self):
        registry=[dict(school='合成学院',admission_unit_code=code,institution_id=iid)for code,iid in [('12345','4100000001'),('54321','4100000002')]]
        with patch.object(tool.zhiqu_db,'_open',side_effect=self.opened),patch.object(tool.zhiqu_db,'_identity',side_effect=ValueError('歧义'))as resolve:
            with self.assertRaises(ValueError):tool.resolve_school(self.db,'合成学院',registry)
        resolve.assert_called_once_with(unittest.mock.ANY,'合成学院')

    def test_unmapped_relevant_table_remains_pending(self):
        extra='<table><tr><th>学科专业</th><th>门槛</th></tr><tr><td>085404</td><td>280</td></tr></table>'
        blob=line_page().replace(b'</body>',extra.encode()+b'</body>')
        parsed=adapters.parse_official_html(blob,URL,IDENTITY,2026,'lines',['0854'])
        self.assertEqual(parsed['rows'],1)
        self.assertEqual(parsed['pending'][0]['table'],2)
        unrelated=blob.replace(b'<td>085404</td><td>280',b'<td>030101</td><td>280')
        self.assertFalse(adapters.parse_official_html(unrelated,URL,IDENTITY,2026,'lines',['0854'])['pending'])

    def test_partial_source_is_not_promoted_to_obtained(self):
        parsed=adapters.parse_official_html(line_page(),URL,IDENTITY,2026,'lines',['0854'])
        parsed['pending']=[{'table':2,'reason':'专项列尚未对应'}]
        with patch.object(tool,'parse_official_html',return_value=parsed):
            summary,_,_=self.run_fake()
        self.assertEqual(summary['outcomes'][0]['status'],'partial')
        self.assertEqual(summary['outcomes'][0]['published_rows'],1)

    def test_obtained_official_cache_skips_every_request(self):
        cells = self.lookup('官方', 'obtained')
        self.assertTrue(cells[0]['obtained'])
        summary, fetch, publish = self.run_fake(cells=cells)
        fetch.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(summary['outcomes'][0]['status'], 'obtained')

    def test_third_party_obtained_not_official_cache(self):
        self.assertFalse(self.lookup('第三方整理', 'obtained')[0]['obtained'])

    def test_official_partial_not_obtained_cache(self):
        self.assertFalse(self.lookup('官方', 'partial')[0]['obtained'])

    def test_program_specific_obtained_requires_still_present_official_sources(self):
        self.lookup('官方', 'partial')
        for source_ids, expected in [(['s'], True), (['deleted-source'], False), ([], False), (['s', 'deleted-source'], False)]:
            coverage = [dict(school='合成大学', year='2026', scope_level='学院专业资格线',
                             status='partial', on_demand_obtained=json.dumps({'0854': source_ids}))]
            with self.subTest(source_ids=source_ids), patch.object(tool.zhiqu_db, '_open', side_effect=self.opened):
                result = tool.lookup(self.db, IDENTITY, ['0854'], [2026], ['lines'], coverage)
            self.assertEqual(result[0]['obtained'], expected)

    def test_program_specific_obtained_cannot_reuse_third_party_source(self):
        self.lookup('第三方整理', 'partial')
        coverage = [dict(school='合成大学', year='2026', scope_level='学院专业资格线', status='partial',
                         on_demand_obtained=json.dumps({'0854': ['s']}))]
        with patch.object(tool.zhiqu_db, '_open', side_effect=self.opened):
            self.assertFalse(tool.lookup(self.db, IDENTITY, ['0854'], [2026], ['lines'], coverage)[0]['obtained'])

    def test_time_expiry_inside_fetch_stops_before_second_request(self):
        def fetch(url, deadline):
            self.clock.advance(121)
            return {'body': line_page()}, {'url': url, 'http_status': 200}
        self.request['entries'].append('https://other.edu.cn/next.html')
        mock = Mock(side_effect=fetch)
        summary, _, publish = self.run_fake(fetch=mock)
        self.assertEqual(mock.call_count, 1)
        publish.assert_not_called()
        self.assertFalse(summary['published'])

    def test_real_fetch_wrapper_refuses_insufficient_time_without_http(self):
        deadline = tool.Deadline(39, self.clock)
        with patch.object(tool, 'retrieve_memory') as network:
            with self.assertRaises(TimeoutError):
                tool.fetch_public(URL, deadline)
        network.assert_not_called()

    def test_timed_out_candidate_never_reports_publication(self):
        publish = Mock(side_effect=TimeoutError('fixed timeout'))
        summary, _, _ = self.run_fake(publisher=publish)
        self.assertEqual(publish.call_count, 1)
        self.assertFalse(summary['published'])
        self.assertEqual(summary['outcomes'][0]['status'], 'partial')

    def test_expired_after_parse_never_calls_publisher(self):
        real = tool.parse_official_html
        def slow(*args):
            value = real(*args)
            self.clock.advance(121)
            return value
        with patch.object(tool, 'parse_official_html', side_effect=slow):
            summary, _, publish = self.run_fake()
        publish.assert_not_called()
        self.assertFalse(summary['published'])

    def test_restricted_same_host_never_retries_or_changes_ua(self):
        for category, code in [('http_block', 403), ('http_block', 412),
                               ('verification', 200), ('login', 200)]:
            with self.subTest(category=category, code=code):
                self.request['entries'] = [URL, 'https://fixture.edu.cn/other.html']
                fetch = Mock(return_value=(None, {'url': URL, 'http_status': code, 'stop_category': category}))
                summary, _, publish = self.run_fake(fetch=fetch)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(fetch.call_args.args, (URL, fetch.call_args.args[1]))
                self.assertEqual(fetch.call_args.kwargs, {})
                publish.assert_not_called()
                self.assertFalse(summary['published'])

    def test_unknown_external_explicit_entry_is_not_requested_as_official(self):
        self.request['entries'] = ['https://untrusted.example/pretend-official.html']
        summary, fetch, publisher = self.run_fake(entry={})
        fetch.assert_not_called()
        publisher.assert_not_called()
        self.assertFalse(summary['published'])

    def test_reverified_existing_row_marks_program_obtained_without_count_inflation(self):
        import csv
        path=Path(self.request['coverage'])
        with path.open('w',newline='')as f:
            w=csv.DictWriter(f,fieldnames=['school','year','scope_level','status','reason','formal_official_rows']);w.writeheader();w.writerow(dict(school='合成大学',year=2026,scope_level='学院专业资格线',status='partial',reason='旧范围待核',formal_official_rows=1))
        tool.update_coverage(path,'合成大学',[dict(year=2026,layer='lines',program='0854',status='obtained',published_rows=0,published_in_library=True,source_ids=['s'],reason='原有行重新全套核验通过')])
        row=list(csv.DictReader(path.open()))[0]
        self.assertEqual(row['formal_official_rows'],'1')
        self.assertEqual(json.loads(row['on_demand_obtained']),{'0854':['s']})
        self.assertEqual(row['status'],'partial')

    def test_parent_timeout_reports_each_missing_cell_and_keeps_cached_result(self):
        out=Path(self.request['output']);out.mkdir()
        tool.write_json(out/'progress.json',dict(school='合成大学',outcomes=[dict(year=2026,layer='lines',program='0854',status='obtained',reason='已有缓存')]))
        request=dict(self.request,programs=['0854','0812'])
        summary=tool.timed_out_summary(request)
        self.assertEqual(len(summary['outcomes']),2)
        self.assertEqual(summary['outcomes'][0]['status'],'obtained')
        self.assertEqual(summary['outcomes'][1]['status'],'not fetched')
        self.assertFalse(summary['published'])
        self.assertTrue((out/'README.md').exists())
        readable=(out/'README.md').read_text()
        self.assertIn('已取得',readable)
        self.assertIn('未取得',readable)
        self.assertNotIn('not fetched',readable)
        self.assertNotIn('obtained',readable)

    def test_cli_hard_deadline_terminates_worker_process_group(self):
        worker=Mock(pid=43210);worker.communicate.side_effect=tool.subprocess.TimeoutExpired('worker',.01)
        with patch.object(sys,'argv',['kaoyan_on_demand','--school','合成大学','--program','0854','--minutes','0.0001','--output',self.request['output'],'--coverage',self.request['coverage']]),patch.object(tool.subprocess,'Popen',return_value=worker),patch.object(tool.os,'killpg')as kill,contextlib.redirect_stdout(io.StringIO()):
            tool.main()
        kill.assert_called_once_with(worker.pid,tool.signal.SIGTERM)
        worker.wait.assert_called_once_with(timeout=3)
        submitted=json.loads(worker.communicate.call_args.args[0])
        self.assertEqual(Path(submitted['coverage']),Path(self.request['coverage']).resolve())
        summary=json.loads((Path(self.request['output'])/'summary.json').read_text())
        self.assertEqual(len(summary['outcomes']),9)
        self.assertFalse(summary['published'])

    def test_custom_database_deadline_uses_isolated_coverage_by_default(self):
        worker=Mock(pid=43210);worker.communicate.side_effect=tool.subprocess.TimeoutExpired('worker',.01)
        args=['kaoyan_on_demand','--school','合成大学','--program','0854','--db',str(self.db),'--minutes','0.0001','--output',self.request['output']]
        with patch.object(sys,'argv',args),patch.object(tool.subprocess,'Popen',return_value=worker),patch.object(tool.os,'killpg'),contextlib.redirect_stdout(io.StringIO()):tool.main()
        submitted=json.loads(worker.communicate.call_args.args[0])
        self.assertEqual(Path(submitted['coverage']),Path(self.request['output']).resolve()/'coverage.csv')
        self.assertNotEqual(Path(submitted['coverage']),tool.SHARED/'data/coverage/kaoyan.csv')

    def test_existing_run_directory_is_not_overwritten(self):
        out=Path(self.request['output']);out.mkdir();(out/'publish.json').write_text('{}')
        args=['kaoyan_on_demand','--school','合成大学','--program','0854','--output',str(out)]
        with patch.object(sys,'argv',args),patch.object(tool.subprocess,'Popen')as worker,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):tool.main()
        worker.assert_not_called();self.assertEqual((out/'publish.json').read_text(),'{}')

    def test_cli_rejects_bypass_and_stealth_flags_before_worker(self):
        for flag in ['--bypass', '--stealth', '--bypass-captcha']:
            with self.subTest(flag=flag), patch.object(sys, 'argv', ['kaoyan_on_demand', '--school', '合成大学', '--program', '0854', flag]), \
                 patch.object(tool.subprocess, 'Popen') as worker, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    tool.main()
                self.assertEqual(raised.exception.code, 2)
                worker.assert_not_called()

    def test_source_body_never_written_to_outputs(self):
        marker = '合成原文专用标记不可落盘'
        body = line_page().replace(b'</body>', ('<p>'+marker+'</p></body>').encode())
        summary, _, _ = self.run_fake(fetch=Mock(return_value=({'body': body}, {'url': URL, 'http_status': 200})))
        self.assertTrue(summary['published'])
        for p in self.root.rglob('*'):
            if p.is_file() and p.suffix != '.sqlite':
                data = p.read_bytes()
                self.assertNotIn(marker.encode(), data)
                self.assertNotIn(body, data)

    def test_statistics_n_one_two_suppressed_n_three_aggregated(self):
        for n in [1, 2, 3]:
            with self.subTest(n=n), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                r = adapters.parse_official_html(roster(n), URL, IDENTITY, 2026, 'stats', ['0854'])
                self.assertEqual(r['rows'], int(n >= 3))
                if n >= 3:
                    row = r['manifest']['rows'][0]
                    self.assertEqual((row['n'], row['min'], row['median'], row['max']), (3, 300, 301, 302))
                else:
                    self.assertEqual(r['manifest']['files'][0]['excluded_rows'], n)
                dumped = json.dumps(r, ensure_ascii=False)
                self.assertNotIn('合成隐私标记', dumped)
                self.assertNotIn('12345678901234', dumped)
                self.assertEqual(stdout.getvalue()+stderr.getvalue(), '')

    def test_n_three_anonymous_manifest_reaches_publisher_without_private_output(self):
        self.request['layers'] = ['stats']
        cells = [dict(year=2026, layer='stats', program='0854', obtained=False,
                      existing_rows=0, source_ids=[])]
        summary, _, publisher = self.run_fake(cells=cells, fetch=Mock(return_value=(
            {'body': roster(3)}, {'url': URL, 'http_status': 200})))
        self.assertTrue(summary['published'])
        manifest = publisher.call_args.args[1][0][1]
        self.assertEqual(manifest['rows'][0]['n'], 3)
        self.assertNotIn('合成隐私标记', json.dumps(manifest, ensure_ascii=False))
        for p in (self.root/'out').rglob('*'):
            if p.is_file():
                self.assertNotIn('合成隐私标记'.encode(), p.read_bytes())
                self.assertNotIn(b'12345678901234', p.read_bytes())

    def test_previous_block_on_host_stops_new_path_but_not_other_official_host(self):
        ledger = self.root/'prior-stops.json'
        ledger.write_text(json.dumps([dict(url='https://fixture.edu.cn/old.html', stop_category='http_block')]))
        self.request['stop_ledger'] = str(ledger)
        summary, fetch, publish = self.run_fake()
        fetch.assert_not_called();publish.assert_not_called()
        self.assertEqual(summary['outcomes'][0]['not_retried_entries'], [URL])
        alternate = 'https://college.fixture.edu.cn/line.html'
        self.request['entries'] = [alternate]
        summary, fetch, publish = self.run_fake(fetch=Mock(return_value=({'body': line_page(), 'url': alternate}, {'status':'retrieved'})))
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(summary['published'])

    def test_fetch_allows_bounded_normal_redirects_without_transport_fallback(self):
        with patch.object(tool, 'retrieve_memory', return_value=({'body': b'anonymous'}, [], None)) as fetch:
            tool.fetch_public(URL, tool.Deadline(120))
        self.assertEqual(fetch.call_args.kwargs, {'max_attempts': 3})

    def test_injected_final_url_on_historically_blocked_host_cannot_publish(self):
        ledger = self.root/'old-block.json'
        ledger.write_text(json.dumps([dict(url=URL, stop_category='http_block')]))
        self.request['stop_ledger'] = str(ledger)
        alternative = 'https://college.fixture.edu.cn/redirect'
        self.request['entries'] = [alternative]
        summary, fetch, publisher = self.run_fake(fetch=Mock(return_value=(
            {'body': line_page(), 'url': URL}, {'status': 'retrieved'})))
        self.assertEqual(fetch.call_count, 1)
        publisher.assert_not_called()
        self.assertFalse(summary['published'])

    def test_rejected_redirect_receipt_stops_host_without_serializing_target(self):
        from kaoyan_public_http import public_receipt
        ledger = self.root/'rejected-stops.json'
        self.request['stop_ledger'] = str(ledger)
        self.request['entries'] = [URL, 'https://fixture.edu.cn/other-path']
        receipt = public_receipt(URL, None, [
            dict(url=URL, http_status=302),
            dict(url='https://fixture.edu.cn/sso/start', origin_attempted=False),
        ], 'fixed local rejection')
        summary, fetch, publisher = self.run_fake(fetch=Mock(return_value=(None, receipt)))
        self.assertEqual(fetch.call_count, 1)
        publisher.assert_not_called()
        self.assertEqual(json.loads(ledger.read_text())[0]['stop_category'], 'restricted_redirect')
        self.assertNotIn('/sso/start', json.dumps(summary))

    def test_recorded_graduate_basis_url_is_requested_before_generic_site(self):
        self.request['entries'] = []
        basis = 'https://fixture.edu.cn/actual-admission.html'
        summary, fetch, publisher = self.run_fake(entry={
            'graduate_site_url': 'https://fixture.edu.cn/',
            'graduate_entry_basis_url': basis,
        })
        self.assertEqual(fetch.call_args_list[0].args[0], basis)
        self.assertTrue(summary['published'])

    def test_masters_navigation_remains_school_bound_and_skips_doctoral_only(self):
        body = page('<a href="/masters">硕士研究生招生信息</a>'
                    '<a href="/doctoral">博士招生信息</a>'
                    '<a href="https://unconfirmed.example/master">硕士招生</a>')
        entry = {'graduate_site_url': 'https://fixture.edu.cn/'}
        self.assertEqual(tool.navigation_links(body, URL, '合成大学', entry), ['https://fixture.edu.cn/masters'])
        self.assertEqual(tool.navigation_links(body, URL, '另一所大学', entry), [])

    def test_admissions_navigation_wins_six_link_budget_over_school_overviews(self):
        markup = ''.join('<a href="/about'+str(i)+'">学校概况</a>' for i in range(6))
        markup += '<a href="/masters">硕士招生</a>'
        links = tool.navigation_links(page(markup), URL, '合成大学', {'graduate_site_url':'https://fixture.edu.cn/'})
        self.assertEqual(len(links), 6)
        self.assertEqual(links[0], 'https://fixture.edu.cn/masters')
        self.assertNotIn('https://fixture.edu.cn/about5', links)

    def test_non_stats_discovery_excludes_explicit_rosters_in_all_resource_roles(self):
        from urllib.parse import quote
        for layer,title in [('lines','复试分数线'),('catalog','招生目录')]:
            markup='<a href="/anonymous.pdf">正式原表</a><a href="/opaque.xlsx">拟录取名单</a>'
            markup+='<a href="/'+quote('复试名单')+'.PDF">附件</a><a href="/aria.pdf" aria-label="拟录取名单">附件</a>'
            markup+='<div class="wp_articlecontent"><img src="/good.png"><img src="/opaque.png" alt="复试名单"></div>'
            markup+='<iframe src="/opaque.pdf" title="拟录取名单"></iframe>'
            markup+='<object data="/'+quote('拟录取名单')+'.pdf"></object><object data="/fallback.pdf">拟录取名单</object>'
            markup+='<iframe src="/viewer.html?file=%2Fopaque.pdf&amp;title='+quote('拟录取名单')+'"></iframe>'
            links=tool.discover_links(page(markup,'合成大学2026年硕士'+title),URL,2026,layer)
            self.assertEqual(set(links),{'https://fixture.edu.cn/anonymous.pdf','https://fixture.edu.cn/good.png'})
        self.assertIn('https://fixture.edu.cn/opaque.xlsx',tool.discover_links(
            page('<a href="/opaque.xlsx">拟录取名单</a>','合成大学2026年硕士拟录取名单'),URL,2026,'stats'))

    def test_discovery_document_year_and_layer_stay_in_one_clean_heading(self):
        img='<div class="wp_articlecontent"><img src="/original.jpg"></div>'
        for title,head in [('合成大学2026年通知','<h1>2025年硕士复试分数线</h1>'),
                           ('合成大学2026年通知','<h1>2026年硕士复试线及拟录取名单</h1>'),
                           ('合成大学研究生院','<h1>硕士复试分数线<script>2026</script></h1>')]:
            self.assertEqual(tool.discover_links(page(head+img,title),URL,2026,'lines'),[])
        heading='<h1>合成大学<span>2026</span>年硕士<strong>复试分数线</strong></h1>'
        self.assertEqual(tool.discover_links(page(heading+img,'研究生院'),URL,2026,'lines'),['https://fixture.edu.cn/original.jpg'])

    def test_line_request_never_fetches_explicit_roster_discovered_on_parent(self):
        body=page('<a href="/opaque.xlsx">2026硕士招生拟录取名单</a>'
                  '<div class="wp_articlecontent"><img src="/opaque.png" alt="复试名单"></div>')
        def fetch(url,deadline):return {'body':body if url==URL else b'not-an-original'}, {'status':'retrieved'}
        fetcher=Mock(side_effect=fetch);summary,_,publisher=self.run_fake(fetch=fetcher)
        self.assertEqual([c.args[0]for c in fetcher.call_args_list],[URL])
        publisher.assert_not_called();self.assertFalse(summary['published'])

    def test_non_stats_queue_and_chsi_plaintext_entry_cannot_reintroduce_rosters(self):
        from urllib.parse import quote
        bad='https://fixture.edu.cn/'+quote('拟录取名单')+'.pdf'
        chsi='https://yz.chsi.com.cn/sch/schoolInfo--schId-1.dhtml'
        for layer in ('lines','catalog'):
            self.request['layers']=[layer];cells=self.cells();cells[0]['layer']=layer
            self.request['entries']=[bad]
            fetcher=Mock(return_value=({'body':b'not-an-original'},{'status':'retrieved'}))
            summary,_,publisher=self.run_fake(cells=cells,fetch=fetcher,entry={})
            fetcher.assert_not_called();publisher.assert_not_called()
            self.request['entries']=[chsi]
            entry={'chsi_profile_url':chsi}
            body=page('合成大学 学校官网：'+bad)
            fetcher=Mock(return_value=({'body':body},{'status':'retrieved'}))
            summary,_,publisher=self.run_fake(cells=cells,fetch=fetcher,entry=entry)
            self.assertEqual([c.args[0]for c in fetcher.call_args_list],[chsi])
            self.assertNotIn('graduate_site_url',entry);publisher.assert_not_called()

    def test_webplus_original_image_is_discovered_without_logo_or_external_images(self):
        body = page('<img src="/logo.jpg"><div class="content wp_articlecontent wide">'
                    '<img src="/original.jpg"><img src="https://unconfirmed.example/other.jpg"></div>'
                    '<div class="wp_articlecontent_fake"><img src="/layout.jpg"></div>')
        self.assertEqual(tool.discover_links(body, URL, 2026, 'lines'), ['https://fixture.edu.cn/original.jpg'])
        with self.assertRaisesRegex(adapters.NeedsReview, '原业务表为图片'):
            adapters.parse_official_html(body, URL, IDENTITY, 2026, 'lines', ['0854'])
        self.assertEqual(tool.discover_links(body, URL, 2025, 'lines'), [])
        logo_only = page('<img src="/logo.jpg"><div class="wp_articlecontent_fake"><img src="/layout.jpg"></div>')
        self.assertEqual(tool.discover_links(logo_only, URL, 2026, 'lines'), [])
        self.assertEqual(adapters.parse_official_html(logo_only, URL, IDENTITY, 2026, 'lines', ['0854'])['rows'], 0)

    def test_actual_original_attachment_is_tried_before_generic_fallback_page(self):
        parent = URL
        original = 'https://fixture.edu.cn/original.jpg'
        generic = 'https://fixture.edu.cn/about'
        self.request['entries'] = [parent, generic]
        body = page('<div class="wp_articlecontent"><img src="/original.jpg"></div>')
        def fetch(url, deadline):
            return {'body': body if url == parent else b'%unrecognized', 'url': url}, {'status':'retrieved'}
        f = Mock(side_effect=fetch)
        with patch.object(tool, 'parse_official_document', side_effect=adapters.NeedsReview('固定原图核验未通过')):
            summary, _, publisher = self.run_fake(fetch=f)
        self.assertEqual([c.args[0] for c in f.call_args_list[:2]], [parent, original])
        publisher.assert_not_called()
        self.assertFalse(summary['published'])

    def test_original_image_wins_twelve_link_budget_over_related_archive_links(self):
        markup = ''.join('<a href="/archive'+str(i)+'">2026年硕士复试分数线</a>' for i in range(12))
        markup += '<div class="wp_articlecontent"><img src="/original.jpg"></div>'
        links = tool.discover_links(page(markup), URL, 2026, 'lines')
        self.assertEqual(len(links), 12)
        self.assertEqual(links[0], 'https://fixture.edu.cn/original.jpg')
        self.assertNotIn('https://fixture.edu.cn/archive11', links)

    def test_literal_retest_score_header_preserves_degree_mode_and_header_spans(self):
        labels=['类别','专业代码','专业名称','学院','复试分数线']
        markup='<table><tr>'+''.join('<th rowspan="2">'+x+'</th>'for x in labels)+'</tr><tr></tr>'
        for code,mode in [('125300','全日制'),('125700','全日制'),('025300','非全日制')]:
            markup+='<tr><td>专业硕士('+mode+')</td><td>'+code+'</td><td>合成专业</td><td>合成学院</td><td>220</td></tr>'
        markup+='</table>'
        result=adapters.parse_official_html(page(markup),URL,IDENTITY,2026,'lines',['125300'])
        self.assertEqual(result['rows'],1)
        row=result['manifest']['rows'][0]
        self.assertEqual(row['row']['total'],220)
        self.assertEqual(row['row']['degree_type'],'专业学位')
        self.assertEqual(row['row']['study_mode'],'全日制')
        self.assertIn('专业硕士(全日制)',row['excerpt'])
        self.assertIn('原表类别',row['scope_context']['scope_raw'])
        proof=result['proofs'][0]
        self.assertEqual(proof['original_rows'],3)
        self.assertEqual(proof['sample_count'],3)
        self.assertEqual([x['row']for x in proof['sample_locators']],[3,4,5])
        self.assertEqual([x['row']for x in proof['header_continuation_rows']],[2])

    def test_category_cannot_hide_special_plan_or_conflicting_study_mode(self):
        for category,mode in [('地方专项','全日制'),('专业硕士(全日制)','非全日制'),('','全日制')]:
            markup='<table><tr><th>类别</th><th>专业代码</th><th>复试分数线</th><th>学习方式</th></tr>'
            markup+='<tr><td>'+category+'</td><td>125300</td><td>220</td><td>'+mode+'</td></tr></table>'
            with self.subTest(category=category,mode=mode),self.assertRaises(adapters.NeedsReview):
                adapters.parse_official_html(page(markup),URL,IDENTITY,2026,'lines',['125300'])

    def test_existing_original_under_another_source_id_does_not_duplicate_ingest(self):
        with sqlite3.connect(self.db) as c:
            c.execute('insert into source(source_id,grade,publisher,archive_sha256) values(?,?,?,?)',
                      ('old-prefix', '官方', IDENTITY['name'], hashlib.sha256(line_page()).hexdigest()))
        summary, _, publisher = self.run_fake()
        publisher.assert_not_called()
        self.assertFalse(summary['published'])
        self.assertEqual(summary['outcomes'][0]['status'], 'partial')
        self.assertFalse(summary['outcomes'][0]['published_in_library'])
        self.assertIn('未重复建来源', summary['outcomes'][0]['reason'])
        self.assertEqual(summary['outcomes'][0]['source_ids'], ['old-prefix'])
        self.assertTrue(list((self.root/'out').glob('existing-source-*.json')))

    def test_recorded_url_padding_is_removed_without_rewriting_address(self):
        path = self.root/'entries.csv'
        path.write_text('school,graduate_site_url\n合成大学,  https://fixture.edu.cn/path/  \n')
        self.assertEqual(tool.entries(path)[0]['graduate_site_url'], 'https://fixture.edu.cn/path/')

    def test_discovery_follows_existing_plan_wording_h2_and_full_anchor_title(self):
        cases = [
            ('<a href="/plan.html">合成大学2026年硕士招生计划分配</a>', 'catalog', '/plan.html'),
            ('<h2>合成大学2026年硕士复试分数线</h2><a href="/line.pdf">附件1</a>', 'lines', '/line.pdf'),
            ('<a href="/catalog.html" title="合成大学2026年硕士招生专业目录">合成大学2026年硕士研究生…</a>', 'catalog', '/catalog.html'),
        ]
        for markup, layer, suffix in cases:
            body = page(markup, '合成大学研究生院')
            self.assertEqual(tool.discover_links(body, URL, 2026, layer), ['https://fixture.edu.cn'+suffix])

    def test_discovery_title_hint_does_not_override_year_or_document_verification(self):
        body = page('<a href="/catalog.html" title="合成大学2025年硕士招生专业目录">更多</a>', '合成大学研究生院')
        self.assertEqual(tool.discover_links(body, URL, 2026, 'catalog'), [])
        with self.assertRaises(adapters.NeedsReview):
            adapters.parse_official_html(body, URL, IDENTITY, 2026, 'catalog', ['0854'])
        unsafe = page('<a href="https://evil.example/catalog.html" title="2026年硕士招生专业目录">更多</a>')
        self.assertEqual(tool.discover_links(unsafe, URL, 2026, 'catalog'), [])

    def test_partial_official_source_is_refetched_not_promoted_to_cache(self):
        prior = 'https://fixture.edu.cn/recorded.html'
        with sqlite3.connect(self.db) as c:
            c.execute('insert into source(source_id,grade,landing_url,file_url) values(?,?,?,?)',
                      ('partial', '官方', prior, ''))
            c.execute('insert into source(source_id,grade,landing_url,file_url) values(?,?,?,?)',
                      ('vendor', '第三方整理', 'https://fixture.edu.cn/vendor.html', ''))
        self.assertEqual(tool.existing_source_entries(self.db, ['partial', 'vendor']), [prior])
        self.request['entries'] = []
        cells = self.cells();cells[0]['source_ids'] = ['partial']
        summary, fetch, publisher = self.run_fake(cells=cells, entry={'graduate_site_url': 'https://fixture.edu.cn/'})
        self.assertEqual(fetch.call_args.args[0], prior)
        self.assertTrue(summary['published'])
        publisher.assert_called_once()

    def test_partial_source_url_is_still_subject_to_host_and_privacy_checks(self):
        with sqlite3.connect(self.db) as c:
            c.executemany('insert into source(source_id,grade,landing_url,file_url) values(?,?,?,?)', [
                ('external', '官方', 'https://unconfirmed.example/line.html', ''),
                ('private', '官方', 'https://fixture.edu.cn/a?candidate_name=sentinel', ''),
                ('login', '官方', 'https://fixture.edu.cn/login', ''),
            ])
        self.assertEqual(tool.existing_source_entries(self.db, ['external', 'private', 'login']), ['https://unconfirmed.example/line.html'])
        cells = self.cells();cells[0]['source_ids'] = ['external', 'private', 'login']
        summary, fetch, publisher = self.run_fake(cells=cells, entry={})
        fetch.assert_not_called();publisher.assert_not_called()
        self.assertFalse(summary['published'])

    def test_same_original_multiple_program_requests_reuses_ram_body(self):
        self.request['programs'] = ['085404', '085410']
        cells = [dict(year=2026, layer='lines', program=code, obtained=False,
                      existing_rows=0, source_ids=[]) for code in self.request['programs']]
        body = page('<table><tr><th>专业代码</th><th>总分</th></tr>'
                    '<tr><td>085404</td><td>300</td></tr>'
                    '<tr><td>085410</td><td>310</td></tr></table>')
        summary, fetch, publisher = self.run_fake(cells=cells, fetch=Mock(return_value=(
            {'body': body}, {'url': URL, 'http_status': 200})))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual([x['status'] for x in summary['outcomes']], ['obtained', 'obtained'])
        self.assertEqual(len(publisher.call_args.args[1]), 2)

    def test_non_initial_roster_score_not_used_for_statistics(self):
        for label in ['总成绩', '复试总分', '综合成绩']:
            with self.subTest(label=label):
                r = adapters.parse_official_html(roster(3, label), URL, IDENTITY, 2026, 'stats', ['0854'])
                self.assertEqual(r['rows'], 0)

    def test_dual_read_failure_rejects_entire_file_no_publish(self):
        with patch.object(adapters, 'html_tables', side_effect=ValueError('fixed')):
            summary, _, publish = self.run_fake()
        publish.assert_not_called()
        self.assertFalse(summary['published'])

    def test_missing_total_or_wrong_year_never_becomes_line(self):
        missing = page('<table><tr><th>专业代码</th><th>专业名称</th></tr><tr><td>085404</td><td>计算机</td></tr></table>')
        self.assertEqual(adapters.parse_official_html(missing, URL, IDENTITY, 2026, 'lines', ['0854'])['rows'], 0)
        with self.assertRaises(adapters.NeedsReview):
            adapters.parse_official_html(line_page().replace(b'2026', b'2025'), URL, IDENTITY, 2026, 'lines', ['0854'])

    def test_roster_title_and_private_table_not_misread_as_retest_line(self):
        body = roster(3).replace('初试总分'.encode(), '总分'.encode()).replace('拟录取名单'.encode(), '复试名单'.encode())
        with self.assertRaises(adapters.NeedsReview):
            adapters.parse_official_html(body, URL, IDENTITY, 2026, 'lines', ['0854'])

    def test_list_title_without_personal_columns_still_not_a_cutoff(self):
        body = line_page().replace('复试分数线'.encode(), '复试名单'.encode())
        try:
            r = adapters.parse_official_html(body, URL, IDENTITY, 2026, 'lines', ['0854'])
        except adapters.NeedsReview:
            return
        self.assertEqual(r['rows'], 0)

    def test_duplicate_business_headers_require_review(self):
        body = page('<table><tr><th>专业代码</th><th>总分</th><th>总分</th></tr>'
                    '<tr><td>085404</td><td>300</td><td>320</td></tr></table>')
        with self.assertRaises(adapters.NeedsReview):
            adapters.parse_official_html(body, URL, IDENTITY, 2026, 'lines', ['0854'])

    def test_shared_plan_cell_not_duplicated_across_distinct_programs(self):
        body = page('<table><tr><th>专业代码</th><th>招生人数</th><th>考试科目</th></tr>'
                    '<tr><td>085404</td><td rowspan="2">20</td><td>科目甲</td></tr>'
                    '<tr><td>085410</td><td>科目乙</td></tr></table>', '合成大学2026年硕士招生专业目录')
        try:
            r = adapters.parse_official_html(body, URL, IDENTITY, 2026, 'catalog', ['0854'])
        except adapters.NeedsReview:
            return  # Ambiguous shared count may conservatively hold the whole file.
        self.assertLessEqual(sum(row['planned'] or 0 for row in r['manifest']['rows']), 20)

    def test_catalog_subject_continuations_only_within_real_program_anchor(self):
        body = page('<table><tr><th>专业代码</th><th>招生人数</th><th>考试科目</th></tr>'
                    '<tr><td rowspan="2">085404</td><td rowspan="2">20</td><td>甲组合</td></tr>'
                    '<tr><td>乙组合</td></tr><tr><td>085410</td><td>3</td><td>丙组合</td></tr>'
                    '</table>', '合成大学2026年硕士招生专业目录')
        r = adapters.parse_official_html(body, URL, IDENTITY, 2026, 'catalog', ['0854'])
        rows = {z['program_code']: z for z in r['manifest']['rows']}
        self.assertEqual(len(rows), 2)
        self.assertIn('甲组合', rows['085404']['subjects'])
        self.assertIn('乙组合', rows['085404']['subjects'])
        self.assertNotIn('丙组合', rows['085404']['subjects'])
        self.assertEqual(rows['085410']['subjects'], '丙组合')
        self.assertEqual(rows['085404']['planned'], 20)

    def reviewed_bundle(self, n=60, read_method='image', samples=6):
        body = b'synthetic-public-image-or-pdf'
        digest = hashlib.sha256(body).hexdigest()
        manifest = {'sources': [{'source_id': 'reviewed-source', 'grade': '官方', 'archive_sha256': digest,
                                  'landing_url': URL, 'file_url': ''}], 'rows': [{'source_id': 'reviewed-source'}]}
        proof = dict(original_rows=n, extracted_rows=n, dual_read_equal=True, status='approved',
                     methods=['synthetic engine A', 'synthetic engine B'], read_method=read_method,
                     sample_passed=True, sample_locators=[{'row': i+1} for i in range(samples)])
        return body, dict(layer='lines', sha256=digest, manifest=manifest, proof=proof)

    def test_reviewed_image_real_sha_and_sufficient_samples_can_be_used(self):
        body, bundle = self.reviewed_bundle()
        result = tool.reviewed_manifest(body, URL, 'lines', [bundle])
        self.assertEqual(result['rows'], 1)

    def test_reviewed_outer_sha_mismatch_never_used(self):
        body, bundle = self.reviewed_bundle()
        bundle['sha256'] = '0'*64
        self.assertIsNone(tool.reviewed_manifest(body, URL, 'lines', [bundle]))

    def test_reviewed_source_sha_url_or_grade_must_match_actual_original(self):
        for field, value in [('archive_sha256', '0'*64), ('landing_url', 'https://other.edu.cn/source.html'),
                             ('grade', '第三方整理')]:
            body, bundle = self.reviewed_bundle()
            bundle['manifest']['sources'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                tool.reviewed_manifest(body, URL, 'lines', [bundle])

    def test_reviewed_bundle_without_any_source_binding_is_rejected(self):
        body, bundle = self.reviewed_bundle()
        bundle['manifest']['sources'] = []
        with self.assertRaises(ValueError):
            tool.reviewed_manifest(body, URL, 'lines', [bundle])

    def test_reviewed_image_requires_ten_percent_and_at_least_five(self):
        for n, count in [(60, 5), (10, 4), (60, 2)]:
            body, bundle = self.reviewed_bundle(n=n, samples=count)
            with self.subTest(n=n, count=count), self.assertRaises(ValueError):
                tool.reviewed_manifest(body, URL, 'lines', [bundle])

    def test_reviewed_text_pdf_requires_three_percent_and_at_least_three(self):
        body, bundle = self.reviewed_bundle(n=100, read_method='text', samples=2)
        with self.assertRaises(ValueError):
            tool.reviewed_manifest(body, URL, 'lines', [bundle])

    def test_reviewed_repeated_method_or_duplicate_samples_are_not_independent(self):
        for key, value in [('methods', ['same engine', 'same engine']),
                           ('sample_locators', [{'row': 1}]*6), ('dual_read_equal', False), ('sample_passed', False)]:
            body, bundle = self.reviewed_bundle()
            bundle['proof'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                tool.reviewed_manifest(body, URL, 'lines', [bundle])

    def test_default_years_are_current_and_previous_two(self):
        actual_date = dt.date
        class Today:
            @classmethod
            def today(cls):
                return actual_date(2026, 10, 23)
        with patch.object(tool.dt, 'date', Today):
            self.assertEqual(tool.year_range(None), [2026, 2025, 2024])
        self.assertEqual(tool.year_range('2025:2026'), [2026, 2025])


if __name__ == '__main__':
    unittest.main()
