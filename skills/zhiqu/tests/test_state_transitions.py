"""States that used to be implicit: each one must be derivable, reversible where
the facts change back, and never claim a side it cannot prove."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
SHARED = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'
sys.path[:0] = [str(SCRIPTS), str(SHARED)]
import decision_evidence  # noqa: E402
import kaoyan_on_demand as kaoyan  # noqa: E402
import subject_check  # noqa: E402

SRC = 'https://example.edu.cn/subject-2027.pdf'


def evidence(status='pending', subject='unknown', other='met', unresolved=('选考要求待核',)):
    return {'status': status, 'year': 2027, 'source': SRC, 'unresolved': list(unresolved),
            'hard_conditions': [{'name': '选考科目', 'status': subject, 'source': SRC},
                                {'name': '体检', 'status': other, 'source': SRC}]}


class EligibilityTransitions(unittest.TestCase):
    def test_met_clears_only_subject_item_and_becomes_verified(self):
        ev = subject_check.update_evidence(evidence(), 'met', '满足', SRC)
        self.assertEqual((ev['status'], ev['unresolved']), ('verified', []))
        decision_evidence.validate_evidence(ev, 2027)

    def test_other_open_items_keep_pending(self):
        ev = subject_check.update_evidence(evidence(unresolved=('选考要求待核', '章程单科限制待核')), 'met', '满足', SRC)
        self.assertEqual((ev['status'], ev['unresolved']), ('pending', ['章程单科限制待核']))
        decision_evidence.validate_evidence(ev, 2027)

    def test_rerun_can_move_back_from_ineligible(self):
        ev = subject_check.update_evidence(evidence(), 'failed', '缺化学', SRC)
        self.assertEqual(ev['status'], 'ineligible')
        decision_evidence.validate_evidence(ev, 2027)
        ev = subject_check.update_evidence(ev, 'met', '已改选化学', SRC)
        self.assertEqual(ev['status'], 'verified')
        decision_evidence.validate_evidence(ev, 2027)

    def test_unknown_downgrades_verified_with_a_reason(self):
        ev = subject_check.update_evidence(evidence('verified', 'met', unresolved=()), 'unknown', '表中未列', SRC)
        self.assertEqual(ev['status'], 'pending')
        self.assertTrue(any('选考' in u for u in ev['unresolved']))
        decision_evidence.validate_evidence(ev, 2027)

    def test_expected_status_is_the_one_validate_accepts(self):
        for subject in ('met', 'unknown', 'failed'):
            for other in ('met', 'unknown', 'failed'):
                for open_items in ((), ('待核',)):
                    with self.subTest(subject=subject, other=other, open_items=open_items):
                        ev = evidence(subject=subject, other=other, unresolved=open_items)
                        ev['status'] = decision_evidence.expected_status(ev['hard_conditions'], open_items)
                        if ev['status'] == 'pending' and not open_items:
                            continue  # unknown without a written open item is rejected on purpose
                        decision_evidence.validate_evidence(ev, 2027)


class KaoyanPublicationState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / 'education.sqlite'
        self.db.write_bytes(b'old')
        self.out = root / 'run'
        self.out.mkdir()
        self.old = hashlib.sha256(b'old').hexdigest()
        self.new = hashlib.sha256(b'new').hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        kaoyan.write_json(self.out / 'publish-prepared.json',
                          {'database': str(self.db), 'old_query_sha256': self.old, 'new_query_sha256': self.new})

    def test_no_marker_is_unpublished(self):
        self.assertEqual(kaoyan.publication_state(self.out, self.db), kaoyan.UNPUBLISHED)

    def test_receipt_is_published(self):
        kaoyan.write_json(self.out / 'publish.json', {})
        self.assertEqual(kaoyan.publication_state(self.out, self.db), kaoyan.PUBLISHED)

    def test_killed_mid_publish_is_resolved_by_fingerprint(self):
        self.prepare()
        self.assertEqual(kaoyan.publication_state(self.out, self.db), kaoyan.UNPUBLISHED)
        self.db.write_bytes(b'new')
        self.assertEqual(kaoyan.publication_state(self.out, self.db), kaoyan.PUBLISHED)
        self.db.write_bytes(b'other writer')
        self.assertEqual(kaoyan.publication_state(self.out, self.db), kaoyan.UNCERTAIN)

    def test_timeout_after_publication_does_not_say_unpublished(self):
        kaoyan.write_json(self.out / 'progress.json', {'school': '合成大学', 'outcomes': [
            {'year': 2026, 'layer': 'lines', 'program': '0854', 'status': 'staged', 'reason': ''}]})
        kaoyan.write_json(self.out / 'publish.json', {})
        request = {'output': str(self.out), 'school': '合成大学', 'seconds': 1, 'database': str(self.db),
                   'years': [2026], 'layers': ['lines'], 'programs': ['0854'], 'coverage': str(self.out / 'coverage.csv')}
        summary = kaoyan.timed_out_summary(request)
        self.assertTrue(summary['published'])
        self.assertEqual(summary['publication_state'], kaoyan.PUBLISHED)
        self.assertIn('已发布', summary['outcomes'][0]['reason'])
        self.assertNotIn('未完成发布', summary['outcomes'][0]['reason'])


class QuestionnaireStageMapping(unittest.TestCase):
    """Every stage option in the questionnaire must have a documented decision_stage."""
    ROOT = Path(__file__).resolve().parents[3]

    def test_every_option_is_mapped(self):
        import re
        for html, name, doc, stages in (
                ('grad.html', 'stage', 'skills/zhiqu-grad/references/case-workflow.md', ['还在考虑', '备考中', '初试已出分', '已有录取']),
                ('career.html', 'job_stage', 'skills/zhiqu-career/references/case-workflow.md', ['还没开始', '投递中', '有 offer 在比较', '在职想跳槽'])):
            options = re.findall(r'name="%s" value="([^"]+)"' % name, (self.ROOT / html).read_text())
            rows = [line for line in (self.ROOT / doc).read_text().splitlines() if line.strip().startswith('| ') and '---' not in line]
            mapped = {}
            for row in rows:
                cells = [c.strip() for c in row.strip().strip('|').split('|')]
                if len(cells) == 2 and cells[0] != '问卷选项':
                    for option in options:
                        if option in cells[0]:
                            mapped[option] = cells[1]
            with self.subTest(html=html):
                self.assertTrue(options)
                self.assertEqual(sorted(set(options) - set(mapped)), [])
                for option, target in mapped.items():
                    self.assertTrue(any(stage in target for stage in stages), (option, target))


if __name__ == '__main__':
    unittest.main()
