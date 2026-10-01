"""Catch DOM identity collisions that corrupt saved/serialized answers."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids = []; self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'): self.ids.append(attrs['id'])
        target = attrs.get('src') if tag == 'script' else attrs.get('href') if tag == 'link' else None
        if target and target.startswith('assets/'): self.assets.append(target)


class QuestionnaireAssets(unittest.TestCase):
    def test_no_duplicate_dom_ids_and_shared_assets_exist(self):
        for name in ('gaokao', 'grad', 'career'):
            with self.subTest(name=name):
                p = Elements(); p.feed((ROOT / (name + '.html')).read_text())
                self.assertFalse([k for k, n in Counter(p.ids).items() if n > 1])
                self.assertIn('assets/questionnaire.css', p.assets)
                self.assertIn('assets/questionnaire.js', p.assets)
                for target in p.assets: self.assertTrue((ROOT / target).is_file())
