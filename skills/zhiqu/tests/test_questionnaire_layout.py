import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipIf(importlib.util.find_spec('playwright') is None, '未安装 playwright，跳过问卷版面实测')
class QuestionnaireLayoutTests(unittest.TestCase):
    def test_no_crowded_controls(self):
        r = subprocess.run([sys.executable, str(ROOT / 'skills/zhiqu/scripts/check_questionnaire.py')], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
