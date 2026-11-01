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

    def test_single_numeral_needs_a_measure_word(self):
        self.assertTrue(excerpt_contains(3, '学制三年，非全日制'))
        self.assertTrue(excerpt_contains('2', '复试加试两门本科主干课程'))
        self.assertFalse(excerpt_contains(4, '学制三年'))
        for excerpt in ('一般要求', '第三年起', '三月报名', '一次性缴清', '一年级新生', '三方协议'):
            self.assertFalse(excerpt_contains(1, excerpt) or excerpt_contains(3, excerpt), excerpt)


if __name__ == '__main__':
    unittest.main()
