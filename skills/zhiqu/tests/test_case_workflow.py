"""个案流程门槛与付费报告规格的自动测试。

运行：在 skills/zhiqu 目录下执行  python3 -m unittest tests.test_case_workflow -v
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
SAMPLE = os.path.join(ROOT, "examples", "2027-GK-S01")

import case_check  # noqa: E402
import check_report  # noqa: E402


def run(*args):
    p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class SampleCase(unittest.TestCase):
    def test_sample_passes_through_stage_7(self):
        gate = case_check.run(SAMPLE, 7)
        self.assertEqual(gate.errors, [])

    def test_stage_8_requires_independent_review(self):
        gate = case_check.run(SAMPLE, 8)
        self.assertTrue(any("review.json" in e for e in gate.errors))

    def test_result_reproduces(self):
        with open(os.path.join(SAMPLE, "result.json"), encoding="utf-8") as f:
            saved = json.load(f)
        p = saved["params"]
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "r.json")
            code, _, err = run("scripts/optimize.py", p["csv"], "--rank", str(p["rank"]), "--slots", str(p["slots"]), "--u-fall", str(p["u_fall"]),
                               "--max-fall", str(p["max_fall"]), "--drift", str(p["drift"]), "--target-year", str(p["target_year"]),
                               "--sigma-floor", str(p["sigma_floor"]), "--sigma-scale", str(p["sigma_scale"]),
                               "--decision-mode", p["decision_mode"], "--json", out)
            self.assertEqual(code, 0, err)
            with open(out, encoding="utf-8") as f:
                again = json.load(f)
        self.assertEqual([x["id"] for x in again["list"]], [x["id"] for x in saved["list"]])
        self.assertAlmostEqual(again["expected_utility"], saved["expected_utility"], places=6)

    def test_pool_reproduces_from_screening_rules(self):
        with open(os.path.join(SAMPLE, "pool.csv"), encoding="utf-8") as f:
            pool_ids = {r["id"] for r in csv.DictReader(f)}
        years = []
        for y in range(2022, 2027):
            years += ["--year", f"{y}=data/zhejiang/general_{y}.csv"]
        direction = None
        with open(os.path.join(SAMPLE, "screening.json"), encoding="utf-8") as f:
            for s in json.load(f)["steps"]:
                if s["reason"] == "direction":
                    direction = s["rule"].split("：", 1)[1] if "：" in s["rule"] else None
        self.assertTrue(direction, "方向步骤的 rule 应写明正则")
        with tempfile.TemporaryDirectory() as d:
            raw, pred = os.path.join(d, "raw.csv"), os.path.join(d, "pred.csv")
            code, _, err = run("scripts/pool.py", *years, "--key", "major", "--public", "--rank-min", "12000", "--rank-max", "70000",
                               "--match-major", direction, "--exclude-major", "双学士", "--in-provinces", "浙江省,上海市,江苏省,北京市", "--out", raw)
            self.assertEqual(code, 0, err)
            with open(raw, encoding="utf-8") as f:
                rows = [r for r in csv.DictReader(f) if "人工核对" not in r["note"]]
            manual = os.path.join(d, "manual.csv")
            with open(manual, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            code, _, err = run("scripts/rank.py", "predict", manual, "--rank", "33000", "--drift", "0.015", "--target-year", "2027",
                               "--sigma-floor", "0.15", "--sigma-scale", "0.9", "--min-p", "0.02", "--out", pred)
            self.assertEqual(code, 0, err)
            with open(pred, encoding="utf-8") as f:
                self.assertEqual({r["id"] for r in csv.DictReader(f)}, pool_ids)


class GateFailures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "2027-GK-S01")
        shutil.copytree(SAMPLE, self.dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit_json(self, name, fn):
        path = os.path.join(self.dir, name)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        fn(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def errors(self, stage):
        return case_check.run(self.dir, stage).errors

    def test_screening_ledger_must_balance(self):
        self.edit_json("screening.json", lambda d: d["steps"][2].update(before=d["steps"][2]["before"] + 1))
        self.assertTrue(any("账对不上" in e for e in self.errors(4)))

    def test_pool_below_two_times_slots_needs_reason(self):
        self.edit_json("case.json", lambda d: d.pop("pool_shortfall_reason"))
        self.assertTrue(any("pool_shortfall_reason" in e for e in self.errors(4)))

    def test_unconfirmed_scenario_blocks_stage_5(self):
        self.edit_json("preferences_config.json", lambda d: d["scenarios"]["student"].update(confirmed=False))
        self.assertTrue(any("未经本人确认" in e for e in self.errors(5)))

    def test_missing_sensitivity_blocks_stage_6(self):
        shutil.rmtree(os.path.join(self.dir, "sensitivity"))
        self.assertTrue(any("敏感性" in e for e in self.errors(6)))

    def test_stale_rules_check_blocks_stage_3(self):
        self.edit_json("rules_check.json", lambda d: d.update(checked_on="2026-01-01"))
        self.assertTrue(any("30 天" in e for e in self.errors(3)))

    def test_unknown_profile_field_must_be_listed_missing(self):
        self.edit_json("profile_parse.json", lambda d: d["fields"][2].update(status="unknown"))
        self.assertTrue(any("missing" in e for e in self.errors(1)))

    def test_empty_code_in_entry_sheet_blocks_stage_7(self):
        path = os.path.join(self.dir, "entry_sheet.csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        rows[1][1] = ""
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        self.assertTrue(any("空代码" in e for e in self.errors(7)))

    def test_report_section_minimums(self):
        self.edit_json("report.json", lambda d: d.update(ask_me=d["ask_me"][:1]))
        self.assertTrue(any("ask_me" in e for e in self.errors(7)))


class ReportSections(unittest.TestCase):
    def test_older_example_does_not_meet_paid_spec(self):
        with open(os.path.join(ROOT, "examples", "case_b_zhejiang_2027", "report.json"), encoding="utf-8") as f:
            errs = check_report.check_sections(json.load(f))
        self.assertTrue(any("roadmap" in e for e in errs))

    def test_unevidenced_research_does_not_count(self):
        with open(os.path.join(SAMPLE, "report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        for school in rep["research"]:
            for item in school["items"]:
                item[2] = "未取到：测试"
        self.assertTrue(any("有证据" in e for e in check_report.check_sections(rep)))


if __name__ == "__main__":
    unittest.main()
