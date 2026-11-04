import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import school_equivalence as se


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f);w.writerow(header);w.writerows(rows)


class SchoolEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.data = Path(self.tmp.name)
        # 100 所有名次的学校：软科第 i 名，录取位次 100*i；另有一所无名次的合办校。
        rows = [[i, f'学校{i}', 1, 10, 10, 600, 100 * i, 'fixture'] for i in range(1, 101)]
        rows.append([999, '合办大学', 1, 10, 10, 600, 5000, 'fixture'])
        write(self.data / 'testprov/physics_2025.csv',
              ['code', 'name', 'group', 'plan', 'admit', 'score', 'rank', 'source_id'], rows)
        write(self.data / 'rankings/bcur_2025.csv', ['rank', 'name', 'name_en', 'province', 'category', 'source_id'],
              [[i, f'学校{i}', '', '', '', 'fixture'] for i in range(1, 101)])
        write(self.data / 'rankings/arwu_2025.csv', ['rank', 'name', 'name_en_slug', 'region', 'source_id'],
              [['401-500', '学校50', '', '中国', 'fixture'], ['601-700', '学校52', '', '中国', 'fixture']])
        self.table = se.admission_table(self.data, years=[2025])
        self.bcur = se.bcur_ranks(self.data / 'rankings/bcur_2025.csv')

    def tearDown(self):
        self.tmp.cleanup()

    def test_neighbors_within_window_set_the_equivalent(self):
        res = se.equivalent('合办大学', self.table, self.bcur)
        # 位次 5000 的 ±20% 是 4167—6000，对应第 42—60 名，中位数 51。
        self.assertEqual(res['equivalent_bcur'], 51)
        self.assertEqual(res['points'][0]['neighbors'], 19)

    def test_too_few_ranked_schools_gives_no_result(self):
        old = se.MIN_REFS;se.MIN_REFS = 101
        try:self.assertIsNone(se.equivalent('合办大学', self.table, self.bcur))
        finally:se.MIN_REFS = old

    def test_validation_excludes_the_school_itself(self):
        res = se.equivalent('学校50', self.table, self.bcur, exclude_self=True)
        # 去掉自己后邻居为第 42—49、51—60 名，中位 51.5；按倍数取窗口，结果略偏后。
        self.assertEqual(res['equivalent_bcur'], 52)
        self.assertLess(se.validate(self.table, self.bcur, min_points=1)['median_factor'], 1.1)

    def test_world_equivalent_uses_mainland_peers_only(self):
        arwu = se.arwu_ranks(self.data / 'rankings/arwu_2025.csv')
        res = se.world_equivalent(51, self.bcur, arwu)
        self.assertEqual(res['arwu_median'], 550)
        self.assertEqual(res['peers_in_top1000'], 2)

    def test_name_normalisation_and_bands(self):
        self.assertEqual(se.norm('香港城市大学（东莞）'), '香港城市大学(东莞)')
        self.assertEqual(se.norm('东华大学(上海市)[公办]'), '东华大学')
        self.assertEqual(se.norm('宁波诺丁汉大学[中外合作办学]'), '宁波诺丁汉大学')
        self.assertEqual(se.norm('河北大学(地方专项计划)'), '河北大学(地方专项计划)')
        self.assertEqual(se.norm('中国地质大学(北京)'), '中国地质大学(北京)')
        self.assertEqual(se.band_mid('801-900'), 850.5)

    def test_real_snapshot_lists_coop_universities(self):
        names = se.coop_schools()
        self.assertIn('宁波诺丁汉大学', names)
        self.assertNotIn('浙江大学', names)

    def test_ranking_snapshots_cite_registered_sources(self):
        root = se.DATA / 'rankings'
        ids = {r['source_id'] for r in se.read_csv(root / 'sources.csv')}
        for name in ('bcur_2025.csv', 'arwu_2025.csv'):
            rows = se.read_csv(root / name)
            self.assertTrue(rows)
            self.assertEqual({r['source_id'] for r in rows} - ids, set(), name)


if __name__ == '__main__':
    unittest.main()
