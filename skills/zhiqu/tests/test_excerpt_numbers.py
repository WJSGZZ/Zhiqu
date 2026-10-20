import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from planning_workflow import cn_number, excerpt_contains


class ExcerptNumberTests(unittest.TestCase):
    def test_chinese_numerals(self):
        self.assertEqual(cn_number('十八萬三千九百六十'), 183960)
        self.assertEqual(cn_number('一千零五'), 1005)
        self.assertEqual(cn_number('十二'), 12)

    def test_arabic_value_matches_chinese_excerpt(self):
        excerpt = '課程的全期學費為港幣十八萬三千九百六十元，此費用可能於日後調整。'
        self.assertTrue(excerpt_contains('183,960', excerpt))
        self.assertFalse(excerpt_contains('183,961', excerpt))


if __name__ == '__main__':
    unittest.main()
