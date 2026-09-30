"""知衢脚本的自动测试（只用标准库）。

运行：在 skills/zhiqu 目录下执行
  python3 -m unittest discover -s tests -v
"""
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import optimize  # noqa: E402


def run(*args):
    """在 skills/zhiqu 目录下运行脚本，返回 (returncode, stdout, stderr)。"""
    p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def optimize_json(csv_path, *extra):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "r.json")
        code, _, err = run("scripts/optimize.py", csv_path, *extra, "--json", out)
        if code:
            raise AssertionError(err)
        with open(out, encoding="utf-8") as f:
            return json.load(f)


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class TestOptimizeRegression(unittest.TestCase):
    def test_demo_expected_utility(self):
        """回归基准：演示候选池的期望效用。模型有意修改时，同步更新这里和 examples 里的数字。"""
        r = optimize_json("examples/candidates_demo.csv", "--rank", "22000", "--slots", "6", "--u-fall", "-60")
        self.assertAlmostEqual(r["expected_utility"], 76.4, delta=0.1)
        self.assertEqual(len(r["list"]), 6)
        utils = [x["utility"] for x in r["list"]]
        self.assertEqual(utils, sorted(utils, reverse=True), "志愿表应按效用从高到低排列")

    def test_examples_reproduce(self):
        """示例 README 里的重现命令必须得到报告里的数字。"""
        c = optimize_json("examples/case_c_guangdong_e2e/candidates.csv", "--rank", "30500", "--slots", "45", "--u-fall", "-60",
                          "--max-fall", "0.01", "--drift", "0.06", "--target-year", "2027", "--sigma-scale", "1.7")
        self.assertAlmostEqual(c["expected_utility"], 93.7, delta=0.1)
        b = optimize_json("examples/case_b_zhejiang_2027/candidates.csv", "--rank", "28000", "--slots", "80", "--u-fall", "-60",
                          "--max-fall", "0.01", "--drift", "0.015", "--target-year", "2027", "--sigma-floor", "0.15", "--sigma-scale", "0.9")
        self.assertAlmostEqual(b["expected_utility"], 76.5, delta=0.1)

    def test_legacy_rule_still_available(self):
        r = optimize_json("examples/case_c_guangdong_e2e/candidates.csv", "--rank", "30500", "--slots", "45", "--u-fall", "-60",
                          "--max-fall", "0.01", "--drift", "0.06", "--target-year", "2027", "--sigma-scale", "1.6", "--sigma-rule", "legacy")
        self.assertAlmostEqual(r["expected_utility"], 94.1, delta=0.1)

    def test_sigma_scale_default_is_neutral(self):
        a = optimize_json("examples/candidates_demo.csv", "--rank", "22000", "--slots", "6", "--u-fall", "-60")
        b = optimize_json("examples/candidates_demo.csv", "--rank", "22000", "--slots", "6", "--u-fall", "-60", "--sigma-scale", "1.0")
        self.assertEqual(a["expected_utility"], b["expected_utility"])


class TestGroupMajors(unittest.TestCase):
    MAJORS = "计算机:100:14000;软件:90:16500;电子:75:19000"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "g.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def one(self, rank, rule="score", majors=None, complete="1"):
        write_csv(self.path, ["id", "name", "rank_2025", "rank_2024", "majors", "rule", "utility_adjusted", "majors_complete"],
                  [["G", "某校·05组", 19000, 19500, majors or self.MAJORS, rule, 30, complete]])
        r = optimize_json(self.path, "--rank", str(rank), "--slots", "1", "--u-fall", "-60")
        return r["list"][0]

    def test_parse_majors_relative_to_easiest(self):
        ms = optimize.parse_majors(self.MAJORS, hist_latest=20000, complete=True)
        self.assertEqual([m[0] for m in ms], ["计算机", "软件", "电子"])
        self.assertAlmostEqual(ms[-1][2], 0.0)  # 最松的专业就是组线
        self.assertLess(ms[0][2], ms[1][2])  # 越热门越难

    def test_parse_majors_incomplete_uses_group_line(self):
        ms = optimize.parse_majors("计算机:100:14000", hist_latest=20000, complete=False)
        self.assertLess(ms[0][2], 0)

    def test_top_student_gets_first_major(self):
        x = self.one(8000)
        top = x["majors"][0]
        self.assertGreater(top["p"], 0.95)

    def test_full_list_no_adjustment(self):
        """列全组内专业、服从调剂：进了组就一定能分到所填专业之一。"""
        x = self.one(18500)
        self.assertLess(x["p_adjusted"], 0.005)
        self.assertAlmostEqual(sum(m["p"] for m in x["majors"]) + x["p_adjusted"], x["p_land"], places=6)

    def test_first_choice_rule_adjusts_more(self):
        a = self.one(17000, rule="score")
        b = self.one(17000, rule="first")
        self.assertGreater(b["p_adjusted"], a["p_adjusted"])


class TestOtherScripts(unittest.TestCase):
    def test_calibrate_runs(self):
        years = [f"--year={y}=data/zhejiang/general_{y}.csv" for y in (2024, 2025, 2026)]
        code, out, err = run("scripts/calibrate.py", "--province", "浙江", "--key", "major", *years)
        self.assertEqual(code, 0, err)
        self.assertIn("80% 区间覆盖", out)

    def test_report_html(self):
        with tempfile.TemporaryDirectory() as d:
            res = os.path.join(d, "r.json")
            run("scripts/optimize.py", "examples/candidates_demo.csv", "--rank", "22000", "--slots", "6", "--u-fall", "-60", "--json", res)
            out = os.path.join(d, "r.html")
            code, _, err = run("scripts/report.py", "examples/report_demo.json", "--opt", res, "--out", out)
            self.assertEqual(code, 0, err)
            with open(out, encoding="utf-8") as f:
                html = f.read()
            for title in ("摘要", "志愿表", "填报单", "追问清单", "数据来源与声明"):
                self.assertIn(title, html)
            self.assertIn("知其所往，方行其衢。", html)

    def test_limits_shown_in_report(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "c.csv")
            with open(os.path.join(ROOT, "examples/candidates_demo.csv"), encoding="utf-8") as f:
                rows = list(csv.reader(f))
            rows[0].append("limits")
            for r in rows[1:]:
                r.append("色弱不宜报考；英语单科不低于 110 分")
            write_csv(src, rows[0], rows[1:])
            res = os.path.join(d, "r.json")
            run("scripts/optimize.py", src, "--rank", "22000", "--slots", "6", "--u-fall", "-60", "--json", res)
            with open(res, encoding="utf-8") as f:
                self.assertIn("色弱不宜报考", json.dumps(json.load(f), ensure_ascii=False))
            out = os.path.join(d, "r.html")
            run("scripts/report.py", "examples/report_demo.json", "--opt", res, "--out", out)
            with open(out, encoding="utf-8") as f:
                self.assertIn("限制：色弱不宜报考", f.read())

    def test_pool_filters(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "p.csv")
            code, _, err = run("scripts/pool.py", "--year", "2025=data/guangdong/physics_2025.csv",
                               "--year", "2026=data/guangdong/physics_2026.csv",
                               "--key", "group", "--in-province", "广东省", "--public",
                               "--rank-min", "20000", "--rank-max", "40000", "--out", out)
            self.assertEqual(code, 0, err)
            with open(out, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertTrue(rows)
            self.assertTrue(all(r["province"] == "广东省" for r in rows))
            self.assertTrue(all(20000 <= int(r["rank_2026"]) <= 40000 for r in rows))
            self.assertFalse(any("中外合作" in r["name"] or "专项" in r["name"] for r in rows))

    def test_pool_matches_provincial_codes_by_name(self):
        # 浙江用本省院校代号，必须按校名匹配教育部名单，否则"留本省"会筛掉全部条目
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "p.csv")
            code, _, err = run("scripts/pool.py", "--year", "2025=data/zhejiang/general_2025.csv",
                               "--year", "2026=data/zhejiang/general_2026.csv", "--key", "major",
                               "--in-province", "浙江省", "--public", "--out", out)
            self.assertEqual(code, 0, err)
            with open(out, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertGreater(len(rows), 1000)
            self.assertTrue(all(r["province"] == "浙江省" for r in rows))
            self.assertFalse(any(re.search("马来西亚|预科|高本贯通", r["name"]) for r in rows))

    def test_pool_lookup_and_exclusions(self):
        import pool
        by_code, by_name = pool.schools()
        self.assertEqual(pool.lookup("", "中国石油大学(华东)(青岛市)[公办]", by_code, by_name)["city"], "青岛市")
        self.assertEqual(pool.lookup("", "北京大学医学部", by_code, by_name)["name"], "北京大学")
        for name in ("重庆大学(本科预科班)", "湖南师范大学(面向麻阳县)", "中南大学(民族班)"):
            self.assertRegex(name, pool.EXCLUDE)
        self.assertNotRegex("中央民族大学", pool.EXCLUDE)


class TestPoolHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.path.join(self.tmp.name, "old.csv")
        self.new = os.path.join(self.tmp.name, "new.csv")
        self.out = os.path.join(self.tmp.name, "pool.csv")
        self.map = os.path.join(self.tmp.name, "map.csv")
        self.header = ["code", "name", "group", "major", "rank", "plan"]

    def tearDown(self):
        self.tmp.cleanup()

    def pool(self, *extra):
        return run("scripts/pool.py", "--year", "2025=" + self.old,
                   "--year", "2026=" + self.new, "--key", "group", "--out", self.out, *extra)

    def rows(self):
        with open(self.out, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_same_group_number_is_not_history_evidence(self):
        write_csv(self.old, self.header, [["11845", "旧名称", "201", "物理", 50000, 20]])
        write_csv(self.new, self.header, [["11845", "广东工业大学", "201", "物理+化学", 30000, ""]])
        self.assertEqual(self.pool()[0], 0)
        row = self.rows()[0]
        self.assertEqual(row["rank_2025"], "")
        self.assertEqual(row["rank_2026"], "30000")
        self.assertEqual(row["history_status"], "latest_only")
        self.assertEqual(row["name"], "广东工业大学·201组")
        self.assertEqual(row["requirement"], "物理+化学")
        self.assertEqual(row["plan"], "")

    def test_verified_map_matches_renumbered_groups(self):
        write_csv(self.old, self.header, [["11845", "广东工业大学", "201", "物理+化学", 50000, 20]])
        write_csv(self.new, self.header, [["11845", "广东工业大学", "209", "物理+化学", 30000, 25]])
        write_csv(self.map, ["year", "code", "group", "history_key", "source"],
                  [[2025, "11845", "201", "gdut-a", "official-old"],
                   [2026, "11845", "209", "gdut-a", "official-new"]])
        self.assertEqual(self.pool("--group-map", self.map)[0], 0)
        row = self.rows()[0]
        self.assertEqual((row["group"], row["rank_2025"], row["history_status"]), ("209", "50000", "verified"))
        self.assertIn("official-old", row["note"])
        self.assertIn("official-new", row["note"])

    def test_split_map_and_duplicate_input_fail_without_output(self):
        write_csv(self.old, self.header, [["11845", "广东工业大学", "201", "", 50000, 20]])
        write_csv(self.new, self.header, [["11845", "广东工业大学", "209", "", 30000, 25]] * 2)
        self.assertNotEqual(self.pool()[0], 0)
        self.assertFalse(os.path.exists(self.out))
        write_csv(self.map, ["year", "code", "group", "history_key", "source"],
                  [[2026, "11845", "209", "gdut-a", "official"],
                   [2026, "11845", "210", "gdut-a", "official"]])
        code, out, err = self.pool("--group-map", self.map)
        self.assertNotEqual(code, 0)
        self.assertIn("不是一对一", err)
        self.assertFalse(os.path.exists(self.out))

    def test_duplicate_major_year_is_excluded_not_overwritten(self):
        write_csv(self.old, self.header, [["11845", "广东工业大学", "", "计算机", 50000, 20],
                                         ["11845", "广东工业大学", "", "计算机", 45000, 10]])
        write_csv(self.new, self.header, [["11845", "广东工业大学", "", "计算机", 30000, 25]])
        code, out, err = run("scripts/pool.py", "--year", "2025=" + self.old,
                             "--year", "2026=" + self.new, "--key", "major", "--out", self.out)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows()[0]["rank_2025"], "")
        self.assertEqual(self.rows()[0]["rank_2026"], "30000")
        self.assertIn("重复", out)

    def test_public_filter_excludes_unknown_school(self):
        write_csv(self.old, self.header, [])
        write_csv(self.new, self.header, [["99999", "待核学校", "201", "", 30000, 20],
                                         ["11845", "广东工业大学", "209", "", 30000, 25]])
        self.assertEqual(self.pool("--public")[0], 0)
        self.assertEqual([r["code"] for r in self.rows()], ["11845"])
        self.assertEqual(self.pool("--in-province", "浙江省", "--out-province")[0], 0)
        self.assertEqual([r["code"] for r in self.rows()], ["11845"])


class TestCohortGuard(unittest.TestCase):
    def test_predict_and_optimize_reject_double_correction(self):
        shared = ["examples/candidates_demo.csv", "--rank", "22000", "--cohort", "2025=100000",
                  "--cohort-now", "110000", "--drift", "0.02"]
        for command in (["scripts/rank.py", "predict", *shared],
                        ["scripts/optimize.py", *shared, "--slots", "6", "--u-fall", "-60"]):
            code, out, err = run(*command)
            self.assertNotEqual(code, 0)
            self.assertIn("重复计算", err)

    def test_cohort_requires_pair_and_positive_counts(self):
        for extra in (["--cohort", "2025=100000"], ["--cohort-now", "110000"],
                      ["--cohort", "2025=0", "--cohort-now", "110000"]):
            code, out, err = run("scripts/rank.py", "predict", "examples/candidates_demo.csv", *extra)
            self.assertNotEqual(code, 0)
            self.assertNotIn("Traceback", err)


class TestValidateData(unittest.TestCase):
    def test_detects_scrambled_ranks(self):
        import random
        import validate_data
        rng = random.Random(1)
        with tempfile.TemporaryDirectory() as d:
            good, bad = os.path.join(d, "good.csv"), os.path.join(d, "bad.csv")
            rows = [[f"{10000 + i}", f"校{i}", "", 700 - i, 1000 + i * 50] for i in range(200)]
            write_csv(good, ["code", "name", "group", "score", "rank"], rows)
            shuffled = [r[:4] + [rng.randint(1000, 11000)] for r in rows]
            write_csv(bad, ["code", "name", "group", "score", "rank"], shuffled)
            codes = {r[0] for r in rows}
            self.assertEqual(validate_data.check_file(good, codes)[0], [])
            self.assertTrue(any("不一致" in i for i in validate_data.check_file(bad, codes)[0]))

    def test_repository_data_passes(self):
        code, out, err = run("scripts/validate_data.py")
        self.assertEqual(code, 0, out[-2000:] + err)


if __name__ == "__main__":
    unittest.main()
