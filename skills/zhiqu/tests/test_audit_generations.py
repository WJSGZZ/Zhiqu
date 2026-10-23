import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'zhiqu-shared', 'scripts'))
import audit_generations as ag  # noqa: E402


def query(path, audit):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE storage_manifest(key TEXT,value TEXT)')
        c.execute("INSERT INTO storage_manifest VALUES('audit_file',?)", (audit,))


def touch(path, age):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x')
    t = 1_000_000 + age
    os.utime(path, (t, t))


class AuditGenerations(unittest.TestCase):
    def test_classify(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            d, snaps = tmp / 'education', tmp / 'snaps'
            query(d / 'education.sqlite', 'audit-cur.sqlite')
            for i, n in enumerate(['audit-old1', 'audit-snap', 'audit-old2', 'audit-cur']):
                touch(d / f'{n}.sqlite', i)
            touch(d / 'audit-prev.sqlite', 10)
            query(snaps / 'a' / 'education.sqlite', 'audit-snap.sqlite')
            touch(snaps / 'a' / 'audit-snap.sqlite', 0)
            r = ag.classify(d, [snaps])
            self.assertEqual(r['current'], ['audit-cur.sqlite'])
            self.assertEqual(r['recent'], ['audit-prev.sqlite'])
            self.assertEqual(sorted(n for n, _ in r['removable']), ['audit-old1.sqlite', 'audit-old2.sqlite', 'audit-snap.sqlite'])

    def test_unreadable_manifest_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            touch(d / 'audit-a.sqlite', 0)
            with self.assertRaises(RuntimeError):
                ag.classify(d, [])


if __name__ == '__main__':
    unittest.main()
