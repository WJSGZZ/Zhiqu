import copy
import csv
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from group_match import FIELDS, load_groups, suggestions, export_confirmed, write_csv
from pool import load_group_map
from pipeline import merge_preferences


class GroupMatchTests(unittest.TestCase):
    def input_rows(self):
        rows = []
        for year, group, majors in ((2025,'201',['计算机科学与技术','软件工程']), (2026,'301',['计算机科学与技术','软件工程'])):
            for major in majors:
                rows.append(dict(province='示例省', category='物理', batch='本科', school='示例大学', code='10001', year=str(year), group=group, major=major, requirement='物理+化学', campus='主校区', pathway='普通', complete='1', source=f'https://example.edu/{year}'))
        return rows

    def groups(self, path, rows):
        write_csv(path, rows, list(rows[0]))
        return load_groups(path)

    def confirmed(self, rows):
        rows = copy.deepcopy(rows)
        for row in rows:
            row.update(confirmed='1',verification_source='https://example.edu/verified',verification_note='合成测试人工确认目录与条件一致',history_key='synthetic-computer')
        return rows

    def test_exact_content_can_suggest_changed_group_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = suggestions(self.groups(Path(tmp)/'input.csv', self.input_rows()), 2025,2026)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['jaccard'],'1.000000')
            self.assertEqual(rows[0]['confirmed'],'0')
            self.assertEqual(rows[0]['warnings'],'')

    def test_never_suggest_across_province_category_batch_or_school(self):
        with tempfile.TemporaryDirectory() as tmp:
            for field in ('province','category','batch','school'):
                rows = self.input_rows()
                for row in rows[2:]:row[field]='不同语境'
                self.assertEqual(suggestions(self.groups(Path(tmp)/'input.csv',rows),2025,2026),[])

    def test_split_and_condition_changes_are_visible_and_not_exportable(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=self.input_rows(); rows[2]['group']='301';rows[3]['group']='302'
            rows[3]['requirement']='仅物理';rows[3]['complete']='0';rows[3]['campus']='新校区';rows[3]['pathway']='中外合作'
            result=suggestions(self.groups(Path(tmp)/'input.csv',rows),2025,2026)
            self.assertEqual(len(result),2)
            self.assertEqual(result[0]['jaccard'],'0.500000')
            self.assertTrue(all('possible_split' in r['warnings'] for r in result))
            changed=next(r for r in result if r['to_group']=='302')
            for warning in ('incomplete_directory','requirement_changed','campus_changed','pathway_changed'):
                self.assertIn(warning,changed['warnings'])
            path=Path(tmp)/'checked.csv';write_csv(path,self.confirmed(result),FIELDS)
            with self.assertRaises(ValueError):export_confirmed(path)

    def test_only_explicit_confirmation_with_sources_exports_compatible_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);rows=suggestions(self.groups(base/'input.csv',self.input_rows()),2025,2026)
            write_csv(base/'review.csv',rows,FIELDS)
            with self.assertRaisesRegex(ValueError,'confirmed=1'):export_confirmed(base/'review.csv')
            checked=self.confirmed(rows);write_csv(base/'review.csv',checked,FIELDS)
            output=export_confirmed(base/'review.csv')
            write_csv(base/'map.csv',output,['year','name','group','history_key','source'])
            loaded=load_group_map(base/'map.csv','name')
            self.assertEqual(len(loaded),2)
            self.assertEqual(loaded[(2025,'示例大学','201')][0],loaded[(2026,'示例大学','301')][0])
            checked[0]['verification_source']='';write_csv(base/'review.csv',checked,FIELDS)
            with self.assertRaisesRegex(ValueError,'verification_source'):export_confirmed(base/'review.csv')

    def test_export_rejects_one_to_many_even_when_manually_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);rows=self.confirmed(suggestions(self.groups(base/'input.csv',self.input_rows()),2025,2026))
            second=copy.deepcopy(rows[0]);second['to_group']='302';rows.append(second)
            write_csv(base/'review.csv',rows,FIELDS)
            with self.assertRaisesRegex(ValueError,'多个专业组'):export_confirmed(base/'review.csv')
            rows[1]['province']='另一省';write_csv(base/'review.csv',rows,FIELDS)
            with self.assertRaisesRegex(ValueError,'同省'):export_confirmed(base/'review.csv')

    def test_conflicting_group_metadata_is_not_silently_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=self.input_rows();rows[1]['campus']='其他校区'
            with self.assertRaisesRegex(ValueError,'同组条件'):self.groups(Path(tmp)/'input.csv',rows)

    def test_pipeline_requires_explicit_major_completeness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);(base/'pool.csv').write_text('id,name,rank_2026\nx,示例组,20000\n')
            (base/'prefs.csv').write_text('id,majors\nx,专业:80:20000\n')
            with self.assertRaisesRegex(ValueError,'majors_complete'):merge_preferences(base/'pool.csv',base/'prefs.csv',base/'out.csv')
            (base/'prefs.csv').write_text('id,majors,majors_complete\nx,专业:80:20000,0\n')
            merge_preferences(base/'pool.csv',base/'prefs.csv',base/'out.csv')
            self.assertIn('majors_complete',(base/'out.csv').read_text())


if __name__ == '__main__':
    unittest.main()
