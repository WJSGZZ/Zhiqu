"""campus_feed: a discovery lead, filtered offline, that never hides what it lacks."""
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'))
import campus_feed as feed  # noqa: E402

TODAY = dt.date(2026, 11, 18)
ITEMS = [
    {'company': '甲制造', 'cohort': '2027届', 'industry': '制造业', 'locations': ['浙江杭州'], 'positions': ['电气类'],
     'apply_url': None, 'deadline': None, 'last_seen': '2026-07-10'},
    {'company': '乙银行', 'cohort': '2027届', 'industry': '银行/金融', 'locations': ['杭州'], 'positions': [],
     'apply_url': 'https://jobs.example.com/a', 'deadline': '2026-11-25', 'last_seen': '2026-11-17'},
    {'company': '丙央企', 'cohort': '2027届', 'industry': '央国企', 'locations': ['北京'], 'positions': [],
     'apply_url': 'https://jobs.example.com/b', 'deadline': '2026-11-01', 'last_seen': '2026-10-01'},
    {'company': '丁学校', 'cohort': '2026届', 'industry': '高校/事业单位', 'locations': ['杭州'], 'positions': [],
     'apply_url': None, 'deadline': '2026-12-30', 'last_seen': '2026-11-01'},
    {'cohort': '2027届'},
]


class CampusFeed(unittest.TestCase):
    def test_filters_and_drops_expired(self):
        rows = feed.select(ITEMS, cohort='2027届', city='杭州', today=TODAY)
        self.assertEqual([r['company'] for r in rows], ['乙银行', '甲制造'])
        self.assertEqual(feed.select(ITEMS, cohort='2027届', industries=('央国企',), today=TODAY), [])

    def test_every_row_says_what_is_missing(self):
        rows = {r['company']: r for r in feed.select(ITEMS, today=TODAY)}
        self.assertTrue(all(r['grade'] == feed.GRADE for r in rows.values()))
        notes = '；'.join(rows['甲制造']['notes'])
        for text in ('无投递链接', '未列截止日', '可能已结束'):
            self.assertIn(text, notes)
        self.assertEqual(rows['乙银行']['notes'], [])

    def test_days_window_needs_a_deadline(self):
        rows = feed.select(ITEMS, cohort='2027届', days=14, today=TODAY)
        self.assertEqual([r['company'] for r in rows], ['乙银行'])

    def test_cli_reads_local_file_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.json'
            path.write_text(json.dumps(ITEMS, ensure_ascii=False), encoding='utf-8')
            out = io.StringIO()
            with redirect_stdout(out):
                feed.main(['--file', str(path), '--city', '杭州', '--json'])
            data = json.loads(out.getvalue())
            self.assertEqual(data['total'], len(ITEMS))
            self.assertIn('第三方', data['source'])

    def test_falls_back_to_next_mirror_and_names_failures(self):
        body = json.dumps(ITEMS).encode()
        calls = []

        def flaky(url, timeout):
            calls.append(url)
            if url == 'https://a.example':
                raise OSError('down')
            return body
        self.assertEqual(len(feed.fetch(('https://a.example', 'https://b.example'), download=flaky)), len(ITEMS))
        self.assertEqual(calls, ['https://a.example', 'https://b.example'])
        with self.assertRaises(SystemExit) as stop:
            feed.fetch(('https://a.example',), download=flaky)
        self.assertIn('--file', str(stop.exception))

if __name__ == '__main__':
    unittest.main()
