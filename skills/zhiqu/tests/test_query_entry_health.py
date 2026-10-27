"""本机查询配置可选，失效入口须报错，检查不执行其内容。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import validate_data


class QueryEntryHealthTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = self.root / 'skills/zhiqu-shared/data/query_entry.json'
        self.config.parent.mkdir(parents=True)

    def check(self):
        return validate_data.check_local_query_entry(self.root)[0]

    def write(self, value):
        self.config.write_text(json.dumps(value), encoding='utf-8')

    def test_uninstalled_local_data_is_optional(self):
        self.assertEqual(self.check(), [])

    def test_invalid_json_or_non_object_is_rejected(self):
        self.config.write_text('{broken')
        self.assertTrue(self.check())
        for value in ([], None, 'entry'):
            self.write(value)
            self.assertTrue(self.check())

    def test_missing_blank_and_non_string_paths_are_rejected(self):
        for value in ({}, {'entry_path': ''}, {'entry_path': '  '},
                      {'entry_path': 1}, {'entry_path': None}):
            self.write(value)
            self.assertTrue(self.check())

    def test_removed_worktree_directory_and_broken_symlink_are_rejected(self):
        broken = self.root / 'broken.py'
        broken.symlink_to(self.root / 'removed.py')
        for path in (self.root / 'missing.py', self.root, broken):
            self.write({'entry_path': str(path)})
            self.assertTrue(self.check())

    def test_existing_relative_or_absolute_file_is_never_executed(self):
        script = self.root / 'query.py'
        marker = self.root / 'executed'
        script.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        for path in (str(script), 'query.py'):
            self.write({'entry_path': path, 'future_field': 'preserved'})
            self.assertEqual(self.check(), [])
            self.assertFalse(marker.exists())

    def test_broken_config_symlink_is_not_treated_as_uninstalled(self):
        self.config.symlink_to(self.root / 'missing-config')
        self.assertTrue(self.check())

    def test_invalid_encoding_and_embedded_null_fail_cleanly(self):
        self.config.write_bytes(b'\xff')
        self.assertTrue(self.check())
        self.write({'entry_path': 'bad\x00path'})
        self.assertTrue(self.check())


if __name__ == '__main__':
    unittest.main()
