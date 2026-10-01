import copy
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from decision_evidence import validate_evidence


class EligibilityGate(unittest.TestCase):
    def test_cli_formal_rejects_unknown_failed_missing_and_wrong_year(self):
        evidence = {'status': 'verified', 'year': 2027, 'source': 'https://www.zjzs.net/',
                    'hard_conditions': [{'name': '选科', 'status': 'met', 'source': 'https://www.zjzs.net/'}], 'unresolved': []}
        cases = [({}, False), (evidence, True)]
        for status, condition in [('pending', 'unknown'), ('ineligible', 'failed')]:
            item = copy.deepcopy(evidence)
            item.update(status=status, unresolved=['选科'])
            item['hard_conditions'][0]['status'] = condition
            cases.append((item, False))
        cases.append((dict(evidence, year=2026), False))
        for item, allowed in cases:
            with self.subTest(item=item), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'candidates.csv'
                with path.open('w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=['id', 'name', 'utility', 'rank_2026', 'eligibility_evidence'])
                    w.writeheader(); w.writerow(dict(id='x', name='模拟候选', utility=80, rank_2026=30000, eligibility_evidence=json.dumps(item)))
                command = [sys.executable, str(SCRIPTS / 'optimize.py'), str(path), '--rank', '20000', '--slots', '1', '--u-fall', '-60', '--target-year', '2027', '--decision-mode', 'formal', '--sims', '100']
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, allowed, result.stderr)

    def test_verified_cannot_hide_failed_or_unknown_conditions(self):
        for state in ('unknown', 'failed'):
            with self.assertRaises(ValueError):
                validate_evidence({'status':'verified', 'year':2027, 'source':'https://example.org/', 'hard_conditions':[{'name':'条件', 'status':state, 'source':'https://example.org/'}]})
