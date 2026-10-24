import contextlib
import importlib.util
import io
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

P = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts/kaoyan_tables.py'
spec = importlib.util.spec_from_file_location('kaoyan_tables', P)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class KaoyanTablesTests(unittest.TestCase):
    def parse(self, text, encoding='utf-8'):
        return mod.html_tables(text.encode(encoding))

    def reject(self, text):
        with self.assertRaisesRegex(ValueError, '^HTML表格结构或双读核对失败$'):
            self.parse(text)

    def test_simple_table_and_original_blank(self):
        x = self.parse('<table><tr><th>专业</th><th>人数</th></tr>'
                       '<tr><td>085404</td><td></td></tr></table>')[0]
        self.assertEqual(x, {'table': 1, 'rows': [['专业', '人数'], ['085404', '']],
                             'anchors': [[[1, 1], [1, 2]], [[2, 1], [2, 2]]],
                             'physical_rows': 2})

    def test_rowspan_continuation_across_tbody_and_colspan(self):
        x = self.parse('<table><tbody><tr><td rowspan="2">学院</td>'
                       '<td colspan="2">20</td></tr></tbody><tbody>'
                       '<tr><td>9</td><td>11</td></tr></tbody></table>')[0]
        self.assertEqual(x['rows'], [['学院', '20', '20'], ['学院', '9', '11']])
        self.assertEqual(x['anchors'][1], [[1, 1], [2, 1], [2, 2]])

    def test_no_inheritance_between_tables(self):
        x = self.parse('<table><tr><td>A</td></tr></table>'
                       '<table><tr><td></td></tr></table>')
        self.assertEqual(x[1]['rows'], [['']])
        self.reject('<table><tr><td rowspan="2">A</td></tr></table>'
                    '<table><tr><td>B</td></tr></table>')

    def test_nested_table_not_returned_or_leaked_into_outer_cell(self):
        x = self.parse('<table><tr><td>A<table><tr><td>内部内容</td></tr>'
                       '</table>B</td><td>C</td></tr></table>')
        self.assertEqual(len(x), 1)
        self.assertEqual(x[0]['rows'], [['AB', 'C']])
        self.assertEqual(x[0]['anchors'], [[[1, 1], [1, 2]]])

    def test_ragged_rows_have_absent_slot_sentinel(self):
        x = self.parse('<table><tr><td>A</td><td>B</td></tr>'
                       '<tr><td>C</td></tr></table>')[0]
        self.assertEqual(x['rows'][1], ['C', ''])
        self.assertEqual(x['anchors'][1], [[2, 1], [0, 0]])

    def test_empty_and_no_table(self):
        self.assertEqual(mod.html_tables(b''), [])
        self.assertEqual(self.parse('<p>说明</p>'), [])
        self.assertEqual(self.parse('<table></table>')[0]['physical_rows'], 0)

    def test_nfkc_and_unicode_whitespace_only(self):
        x = self.parse('<table><tr><td>０８５４０４\u3000\n 计划①</td>'
                       '<td>元／年</td></tr></table>')[0]
        self.assertEqual(x['rows'], [['085404 计划1', '元/年']])

    def test_utf8_bom_and_meta(self):
        body = '<meta charset="utf-8"><table><tr><td>计算机</td></tr></table>'
        self.assertEqual(mod.html_tables(b'\xef\xbb\xbf' + body.encode())[0]['rows'], [['计算机']])

    def test_gbk_explicit_and_http_equiv(self):
        for head in ['<meta charset="gbk">', '<meta http-equiv="Content-Type" content="text/html; charset=GB2312">']:
            self.assertEqual(self.parse(head+'<table><tr><td>计算机</td></tr></table>', 'gbk')[0]['rows'], [['计算机']])

    def test_undeclared_utf8_and_gbk(self):
        for encoding in ['utf-8', 'gbk']:
            self.assertEqual(self.parse('<table><tr><td>计算机</td></tr></table>', encoding)[0]['rows'], [['计算机']])

    def test_conflicting_or_unsupported_encoding_rejected(self):
        self.reject('<meta charset="utf-8"><meta charset="gbk"><table></table>')
        self.reject('<meta charset="utf-16"><table></table>')
        with self.assertRaises(ValueError):
            mod.html_tables(b'\xef\xbb\xbf<meta charset="gbk"><table></table>')
        with self.assertRaises(ValueError):
            mod.html_tables(b'<meta charset="utf-8">\xff<table></table>')

    def test_malformed_structural_tags_rejected(self):
        for body in ['<table><tr><td>A</tr></table>', '<table><tr><td>A',
                     '<table><td>A</td></table>', '<table><tr><td>A<td>B</td></tr></table>',
                     '<table><tr><td>A</th></tr></table>', '<table><tr/></table>']:
            with self.subTest(body=body):
                self.reject(body)

    def test_duplicate_attribute_rejected(self):
        self.reject('<table><tr><td colspan="1" colspan="2">A</td></tr></table>')

    def test_crossing_occupied_merge_rejected(self):
        self.reject('<table><tr><td>A</td><td rowspan="2">B</td></tr>'
                    '<tr><td colspan="2">C</td></tr></table>')

    def test_bad_zero_negative_or_huge_span_rejected(self):
        for span in ['0', '-1', '1.5', '999999999999', '1001', 'invalid']:
            with self.subTest(span=span):
                self.reject('<table><tr><td colspan="'+span+'">A</td></tr></table>')

    def test_expansion_limits_before_padding(self):
        with patch.object(mod, '_MAX_SLOTS', 3):
            self.reject('<table><tr><td colspan="2">A</td></tr>'
                        '<tr><td>B</td><td>C</td></tr></table>')
        with patch.object(mod, '_MAX_ROWS', 1):
            self.reject('<table><tr><td>A</td></tr><tr><td>B</td></tr></table>')

    def test_two_parser_value_or_anchor_disagreement_rejected(self):
        for altered in [[{'table': 1, 'rows': [['B']], 'anchors': [[[1, 1]]], 'physical_rows': 1}],
                        [{'table': 1, 'rows': [['A']], 'anchors': [[[9, 9]]], 'physical_rows': 1}]]:
            with patch.object(mod, '_bs4_tables', return_value=altered):
                self.reject('<table><tr><td>A</td></tr></table>')

    def test_personal_values_only_returned_in_ram_no_output_or_io(self):
        # Synthetic sentinel, not a real identity; this layer must not silently drop it.
        marker = '合成隐私标记'
        body = ('<table><tr><th>姓名</th><th>考生号</th></tr><tr><td>'+marker+
                '</td><td>123456789012345</td></tr></table>').encode()
        output = io.StringIO()
        with patch('builtins.open', side_effect=AssertionError('unexpected I/O')), \
             patch.object(Path, 'write_text', side_effect=AssertionError('unexpected write')), \
             patch.object(Path, 'write_bytes', side_effect=AssertionError('unexpected write')), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = mod.html_tables(body)
            with patch.object(mod, '_bs4_tables', return_value=[]):
                with self.assertRaises(ValueError) as raised:
                    mod.html_tables(body)
        self.assertEqual(result[0]['rows'][1], [marker, '123456789012345'])
        self.assertNotIn(marker, str(raised.exception))
        self.assertEqual(output.getvalue(), '')

    def test_parser_hints_do_not_log_or_echo_input(self):
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            self.assertEqual(self.parse('https://example.edu.cn/private-marker'), [])
            self.parse('<?xml version="1.0"?><table><tr><td>A</td></tr></table>')
        self.assertEqual(seen, [])

    def test_input_type_and_byte_limit(self):
        with self.assertRaises(ValueError):
            mod.html_tables('not bytes')
        with patch.object(mod, '_MAX_BYTES', 1):
            with self.assertRaises(ValueError):
                mod.html_tables(b'abc')


if __name__ == '__main__':
    unittest.main()
