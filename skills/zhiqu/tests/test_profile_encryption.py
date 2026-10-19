"""Local-only encrypted profile roundtrips and integrity rejection cases."""
import base64
import copy
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import profile_store as store


def profile():
    data = {'zhiqu': 'grad', 'schema': 1, '问卷': '知衢 · 读研 · 自我盘点',
            'form': 'abcdef12', 'filled_at': '2026-10-19T12:00:00+08:00',
            'sections': [{'title': '模拟登记', 'items': [
                {'id': 'grade', 'q': '目前年级', 'status': '已答', 'required': True, 'a': '大三'},
                {'id': 'major', 'q': '专业', 'status': '未填', 'required': True}]}],
            'rank': [], 'derived': {}, 'collapsed': ['work_offer'],
            'counts': {'visible': 2, 'answered': 1}}
    data['checksum'] = store.checksum(data)
    return data


class ProfileIntegrity(unittest.TestCase):
    def test_plain_roundtrip_and_unanswered_field_stays_unknown(self):
        data = profile(); raw = json.dumps(data, ensure_ascii=False)
        self.assertEqual(store.parse_profile(raw), data)
        parsed = store.build_parse(raw, 'grad')
        major = next(f for f in parsed['fields'] if f['field'] == '专业')
        self.assertEqual(major['status'], 'unknown')
        self.assertIsNone(major['value'])
        with tempfile.TemporaryDirectory() as directory:
            info = store.ingest(Path(directory), '2027-YJ-0001', raw)
            self.assertEqual(info['integrity'], '校验通过')
            self.assertEqual(store.latest(Path(directory), '2027-YJ-0001')[1], raw)

    def test_diff_two_versions_with_unanswered_items(self):
        first = profile()
        second = copy.deepcopy(first)
        second['filled_at'] = '2026-10-20T12:00:00+08:00'
        second['sections'][0]['items'][0]['a'] = '大四'
        second['checksum'] = store.checksum(second)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for data in (first, second):
                store.ingest(root, '2027-YJ-0001', json.dumps(data))
            comparison = store.diff(root, '2027-YJ-0001')
            self.assertEqual(comparison['modified'], {'grade': {'old': '大三', 'new': '大四'}})
            self.assertEqual(comparison['added'], {})
            self.assertEqual(comparison['deleted'], {})
            self.assertNotIn('major', comparison['modified'])

    def test_changed_character_removed_question_and_truncation_rejected(self):
        data = profile()
        changed = copy.deepcopy(data); changed['sections'][0]['items'][0]['a'] = '大四'
        removed = copy.deepcopy(data); removed['sections'][0]['items'].pop()
        raw = json.dumps(data, ensure_ascii=False)
        for text in (json.dumps(changed), json.dumps(removed), raw[:len(raw)//2]):
            with self.subTest(text=text[:60]), self.assertRaisesRegex(ValueError, store.INTEGRITY_ERROR):
                store.parse_profile(text)

    def test_rehashed_inconsistent_counts_status_and_collapsed_rejected(self):
        for mutate in (
            lambda d: d['counts'].update(visible=3),
            lambda d: d['counts'].update(answered=2),
            lambda d: d['sections'][0]['items'][0].pop('status'),
            lambda d: d['collapsed'].append('grade'),
            lambda d: d['sections'][0]['items'][1].update(a='未填却带答案'),
        ):
            data = profile(); mutate(data); data['checksum'] = store.checksum(data)
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, store.INTEGRITY_ERROR):
                store.validate(data)

    def test_removing_checksum_cannot_downgrade_current_format(self):
        data = profile(); data.pop('checksum')
        with self.assertRaisesRegex(ValueError, store.INTEGRITY_ERROR):
            store.validate(data)

    def test_legacy_json_is_explicitly_unchecked(self):
        data = profile()
        for key in ('checksum', 'counts', 'collapsed'): data.pop(key)
        data['sections'][0]['items'].pop()
        for item in data['sections'][0]['items']:
            item.pop('status'); item.pop('required', None)
        data['未填的必答题'] = []
        with tempfile.TemporaryDirectory() as directory:
            info = store.ingest(Path(directory), '2027-YJ-0001', json.dumps(data))
            self.assertEqual(info['integrity'], '无校验')

    def test_crypto_is_lazy_and_plain_processing_works_without_it(self):
        script = '''
import builtins, sys
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name.startswith('cryptography'): raise ImportError('deliberately unavailable')
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
import profile_store
profile_store.parse_profile(sys.stdin.read())
assert not any(name.startswith('cryptography') for name in sys.modules)
try: profile_store.crypto_modules()
except ValueError as exc: assert 'pip install cryptography' in str(exc)
else: raise AssertionError('missing dependency not explained')
'''
        result = subprocess.run([sys.executable, '-c', script],
            input=json.dumps(profile()), capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(Path(store.__file__).parent)}, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keygen_refuses_private_key_inside_repository(self):
        with self.assertRaisesRegex(ValueError, '仓库以外'):
            store.keygen(store.REPO / '.cache' / 'forbidden-test-key.pem', store.REPO / '.cache' / 'unused-public.js')


@unittest.skipUnless(importlib.util.find_spec('cryptography'), 'optional cryptography not installed')
class ProfileEncryption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.private = cls.root / 'recipient.pem'; cls.public = cls.root / 'recipient.js'
        store.keygen(cls.private, cls.public)
        cls.hashes, cls.serialization, cls.padding, cls.rsa, cls.AESGCM = store.crypto_modules()
        cls.key = cls.serialization.load_pem_private_key(cls.private.read_bytes(), password=None)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def encrypt(self, raw):
        secret = os.urandom(32); nonce = os.urandom(12)
        wrapped = self.key.public_key().encrypt(secret, self.padding.OAEP(
            mgf=self.padding.MGF1(self.hashes.SHA256()), algorithm=self.hashes.SHA256(), label=None))
        ciphertext = self.AESGCM(secret).encrypt(nonce, gzip.compress(raw.encode()), b'ZQ1')
        return 'ZQ1:' + base64.urlsafe_b64encode(len(wrapped).to_bytes(2, 'big') + wrapped + nonce + ciphertext).decode().rstrip('=')

    def test_encrypted_roundtrip_stores_only_plain_json(self):
        raw = json.dumps(profile(), ensure_ascii=False, indent=2)
        encrypted = self.encrypt(raw)
        self.assertEqual(store.decrypt_profile(encrypted, self.private), raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = store.ingest(root, '2027-YJ-0001', encrypted, private_key=self.private)
            self.assertEqual(info['integrity'], '校验通过')
            archived = root / '2027-YJ-0001' / info['file']
            self.assertEqual(archived.read_text(), raw)
            self.assertNotIn('ZQ1:', archived.read_text())
        with patch.dict(os.environ, {'ZHIQU_PRIVATE_KEY': str(self.private)}):
            self.assertEqual(store.decrypt_profile(encrypted), raw)

    def test_wrong_private_key_and_corrupt_or_truncated_ciphertext_rejected(self):
        other = self.rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_path = self.root / 'wrong.pem'
        other_path.write_bytes(other.private_bytes(self.serialization.Encoding.PEM,
            self.serialization.PrivateFormat.PKCS8, self.serialization.NoEncryption()))
        encrypted = self.encrypt(json.dumps(profile()))
        for text, key in ((encrypted, other_path), (encrypted[:len(encrypted)//2], self.private),
                          (encrypted[:-5] + 'AAAAA', self.private)):
            with self.subTest(key=str(key)), self.assertRaisesRegex(ValueError, store.INTEGRITY_ERROR):
                store.decrypt_profile(text, key)

    def test_keygen_private_permissions_public_only_and_no_overwrite(self):
        self.assertEqual(self.private.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('PRIVATE KEY', self.public.read_text())
        self.assertIn('wjsgzz.github.io', self.public.read_text())
        with self.assertRaisesRegex(ValueError, '拒绝覆盖'):
            store.keygen(self.private, self.public)


if __name__ == '__main__':
    unittest.main()
