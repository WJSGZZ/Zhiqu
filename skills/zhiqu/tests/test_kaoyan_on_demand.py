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
                          'planned integer,tuimian integer,subjects text,study_mode text,direction text,n integer,min real,median real,max real,list_type text,admission_route text)')
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
        coverage = [dict(school='合成大学', year='2026', scope_level='学院专业资格线', status=status)]
        with patch.object(tool.zhiqu_db, '_open', side_effect=self.opened):
            return tool.lookup(self.db, IDENTITY, ['0854'], [2026], ['lines'], coverage)

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

    def test_cli_hard_deadline_terminates_worker_process_group(self):
        worker=Mock(pid=43210);worker.communicate.side_effect=tool.subprocess.TimeoutExpired('worker',.01)
        with patch.object(sys,'argv',['kaoyan_on_demand','--school','合成大学','--program','0854','--minutes','0.0001','--output',self.request['output']]),patch.object(tool.subprocess,'Popen',return_value=worker),patch.object(tool.os,'killpg')as kill,contextlib.redirect_stdout(io.StringIO()):
            tool.main()
        kill.assert_called_once_with(worker.pid,tool.signal.SIGTERM)
        worker.wait.assert_called_once_with(timeout=3)
        summary=json.loads((Path(self.request['output'])/'summary.json').read_text())
        self.assertEqual(len(summary['outcomes']),9)
        self.assertFalse(summary['published'])

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
            self.assertEqual(tool.year_range(None), [2024, 2025, 2026])
        self.assertEqual(tool.year_range('2025:2026'), [2025, 2026])


if __name__ == '__main__':
    unittest.main()
