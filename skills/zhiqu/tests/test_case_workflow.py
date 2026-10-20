"""个案流程门槛与付费报告规格的自动测试。

运行：在 skills/zhiqu 目录下执行  python3 -m unittest tests.test_case_workflow -v
"""
import csv
import json
import os
import re
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
        with tempfile.TemporaryDirectory() as d:
            case = os.path.join(d, "2027-GK-S01")
            shutil.copytree(SAMPLE, case)
            review = os.path.join(case, "review.json")
            if os.path.exists(review):
                os.remove(review)
            gate = case_check.run(case, 8)
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
    def test_report_without_roadmap_does_not_meet_paid_spec(self):
        with open(os.path.join(SAMPLE, "report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        rep.pop("roadmap", None)
        self.assertTrue(any("roadmap" in e for e in check_report.check_sections(rep)))

    def test_unevidenced_research_does_not_count(self):
        with open(os.path.join(SAMPLE, "report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        for school in rep["research"]:
            for item in school["items"]:
                item[2] = "未取到：测试"
        self.assertTrue(any("有证据" in e for e in check_report.check_sections(rep)))


    def test_methods_must_cover_six_topics_and_grades(self):
        with open(os.path.join(SAMPLE, "report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(check_report.check_sections(rep), [])
        rep["methods"] = [b for b in rep["methods"] if "局限" not in b["title"]]
        self.assertTrue(any("局限" in e for e in check_report.check_sections(rep)))
        grade = next(b for b in rep["methods"] if "证据等级" in b["title"])
        grade["rows"][0][2] = "很可能"
        self.assertTrue(any("证据等级" in e for e in check_report.check_sections(rep)))


    def test_only_cover_forces_page_break(self):
        # 文中强制分页会让上一节剩一两行独占一页，留下大片空白；只允许封面之后、第 12 节“核对与来源”之前各分页一次
        with open(os.path.join(SAMPLE, "report.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertEqual(re.findall(r'<section class="newpage"(?: data-section="(\d+)")?>',html), ["01", "12"])
        self.assertNotIn("avoid-page", html)

RETRO = os.path.join(ROOT, "examples", "2026-GK-R01")


class RetroSample(unittest.TestCase):
    def test_retro_sample_passes_through_stage_7(self):
        self.assertEqual(case_check.run(RETRO, 7).errors, [])

    def test_retro_uses_only_pre_target_years(self):
        with open(os.path.join(RETRO, "screening.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["source_table"], "data/zhejiang/general_2025.csv")
        with open(os.path.join(RETRO, "pool.csv"), encoding="utf-8") as f:
            header = next(csv.reader(f))
        self.assertNotIn("rank_2026", header)

    def test_retro_judge_reproduces_hindsight(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "h.json")
            code, _, err = run("scripts/retro_judge.py", os.path.join(RETRO, "result.json"), "--target", "data/zhejiang/general_2026.csv",
                               "--rank", "33000", "--json", out)
            self.assertEqual(code, 0, err)
            with open(out, encoding="utf-8") as f:
                again = json.load(f)
        self.assertEqual((again["status"], again["landing_order"]), ("投档", 3))
        with open(os.path.join(RETRO, "hindsight.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["rows"], again["rows"])


class RetroJudge(unittest.TestCase):
    def judge(self, cuts, rank=100):
        import retro_judge
        idx = {("A", f"m{k}"): [(c, "")] for k, c in enumerate(cuts) if c != "missing"}
        result = {"list": [{"order": k + 1, "id": f"A-m{k}", "code": "A", "name": f"m{k}", "p_clear": .5, "utility": 50}
                           for k in range(len(cuts))]}
        return retro_judge.judge(result, idx, rank, "major")

    def test_name_key_for_provinces_that_renumber_codes(self):
        import retro_judge
        idx = {("甲校", "计算机"): [(150, "")]}
        result = {"list": [{"order": 1, "id": "0142-计算机", "code": "0142", "name": "甲校·计算机", "p_clear": .5, "utility": 50}]}
        out = retro_judge.judge(result, idx, 100, "major", school="name")
        self.assertEqual((out["status"], out["landing_order"]), ("投档", 1))

    def test_group_with_changed_requirement_is_not_compared(self):
        import retro_judge
        idx = {("A", "01"): [(150, "化学")], ("A", "02"): [(150, "不限")]}
        result = {"list": [{"order": k + 1, "id": f"A-0{k + 1}", "code": "A", "group": f"0{k + 1}", "name": f"A·0{k + 1}组",
                            "p_clear": .5, "utility": 50} for k in range(2)]}
        out = retro_judge.judge(result, idx, 100, "group", requirement={"A-01": "化学和生物", "A-02": "不限"})
        self.assertEqual((out["status"], out["blocker_order"]), ("无法判定", 1))
        self.assertIn("选科要求变了", out["rows"][0]["note"])

    def test_first_cleared_entry_is_landing(self):
        out = self.judge([90, 120, 200])
        self.assertEqual((out["status"], out["landing_order"]), ("投档", 2))

    def test_missing_before_landing_is_unknown_not_skipped(self):
        out = self.judge([90, "missing", 200])
        self.assertEqual((out["status"], out["blocker_order"]), ("无法判定", 2))

    def test_all_short_is_fall(self):
        self.assertEqual(self.judge([90, 80])["status"], "滑档")


class SubjectCheck(unittest.TestCase):
    def test_requirement_parsing(self):
        import subject_check
        self.assertEqual(subject_check.required("物理,化学(2门科目考生均须选考方可报考)"), ["物理", "化学"])
        self.assertEqual(subject_check.required("不提科目要求"), [])
        idx = {("甲大学", "电气工程及其自动化"): ["物理,化学(2门科目考生均须选考方可报考)"]}
        self.assertEqual(subject_check.check("甲大学·电气工程及其自动化(卓越班)", idx, {"物理", "化学", "技术"})[0], "met")
        self.assertEqual(subject_check.check("甲大学·电气工程及其自动化", idx, {"物理", "生物", "技术"})[0], "failed")
        self.assertEqual(subject_check.check("乙大学·自动化", idx, {"物理"})[0], "unknown")



class GradeWording(unittest.TestCase):
    def rep(self, name):
        with open(os.path.join(ROOT, "examples", name, "report.json"), encoding="utf-8") as f:
            return json.load(f)

    def result(self, name):
        with open(os.path.join(ROOT, "examples", name, "result.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_b_formatter_rounds_to_five(self):
        import report
        f = report.prob_formatter("B")
        self.assertEqual((f(0.148), f(0.749), f(0.01), f(0.03), f(0.96), f(0.9999), f(0), f(1)),
                         ("约 15%", "约 75%", "&lt; 5%", "&lt; 5%", "&gt; 95%", "&gt; 95%", "0%", "100%"))
        self.assertIsNone(report.prob_formatter("C")(0.5))

    def test_samples_pass_grade_checks(self):
        for name in ("2026-GK-R01", "2027-GK-S01"):
            self.assertEqual(check_report.check_grade(self.rep(name), self.result(name)), [])

    def test_grade_cannot_be_more_optimistic_than_health_check(self):
        rep = self.rep("2027-GK-S01")
        rep["meta"]["prob_grade"] = "B"  # 浙江 B、2027 改版年 → 最乐观只能 C
        self.assertTrue(any("更乐观" in e for e in check_report.check_grade(rep)))

    def test_c_grade_text_may_not_quote_percentages(self):
        rep = self.rep("2027-GK-S01")
        rep["summary"]["points"][0] += "中国计量过线约 99%。"
        self.assertTrue(any("不写百分比" in e for e in check_report.check_grade(rep)))

    def test_b_grade_needs_wide_safety_pick(self):
        rep, res = self.rep("2026-GK-R01"), self.result("2026-GK-R01")
        for x in res["list"]:
            x["expected_cut_rank"] = int(res["params"]["rank"] * 1.1)
        self.assertTrue(any("保底不足" in e for e in check_report.check_grade(rep, res)))

class ProvinceHealth(unittest.TestCase):
    def test_grade_thresholds(self):
        import province_health as ph
        good = dict(coverage_80=.8, fail_95=.03, worst_fail_95=.05, match_rate=.8)
        self.assertEqual(ph.grade(good, "major", 3, 2), "A")
        self.assertEqual(ph.grade(good, "major", 3, 1), "B")
        self.assertEqual(ph.grade(dict(good, worst_fail_95=.2), "major", 4, 3), "B")
        self.assertEqual(ph.grade(dict(good, coverage_80=.97), "major", 3, 2), "C")
        self.assertEqual(ph.grade(good, "major", 1, 0), "C")
        self.assertEqual(ph.grade(good, "major", 0, 0), "D")

    def test_renumbered_school_codes_match_by_name(self):
        import province_health as ph
        by = {(p, c): school for p, c, _, school in ph.SERIES}
        for p in ("hebei", "fujian", "shanxi"):
            self.assertEqual(by[(p, "physics")], "name")

    def test_saved_grades(self):
        with open(os.path.join(ROOT, "data", "calibration", "province_health.csv"), encoding="utf-8") as f:
            pooled = {(r["province"], r["category"], r["key"]): r["grade"] for r in csv.DictReader(f) if r["record"] == "pooled"}
        self.assertEqual(pooled[("hebei", "physics", "院校+专业名")], "A")
        self.assertEqual(pooled[("henan", "physics", "")], "D")
        self.assertNotIn("A", {g for (p, _, k), g in pooled.items() if k == "院校+组号"})

if __name__ == "__main__":
    unittest.main()


class CaseLibrary(unittest.TestCase):
    """案例库（examples/2026-GK-R02…）：完整版报告由计算结果与手写内容生成；同样的输入必须得到同样的报告。"""

    def cases(self):
        import glob
        return [d for d in sorted(glob.glob(os.path.join(ROOT, "examples", "2026-GK-R*")))
                if os.path.exists(os.path.join(d, "narrative.json"))]

    def test_reports_regenerate_identically(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import case_report
        cases = self.cases()
        self.assertGreaterEqual(len(cases), 11)
        for d in cases:
            with self.subTest(case=os.path.basename(d)):
                with open(os.path.join(d, "report.json"), encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(case_report.build(d, render=False), saved)

    def test_render_requires_explicit_profile_and_forwards_selected_version(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        import case_report
        # Missing selection must stop before any case files are read or written.
        with self.assertRaisesRegex(ValueError,'明确指定'):
            case_report.build('/does-not-exist',render=True)
        source=Path(ROOT)/'examples/2026-GK-R02'
        with tempfile.TemporaryDirectory() as tmp:
            skill=Path(tmp).resolve();folder=skill/'examples'/source.name
            shutil.copytree(source,folder)
            (skill/'data').symlink_to(Path(ROOT)/'data',target_is_directory=True)
            before=(source/'report.json').read_bytes()
            result=SimpleNamespace(returncode=0,stdout='passed',stderr='')
            with patch.object(case_report,'SKILL',skill),patch('case_report.subprocess.run',return_value=result) as invoke,patch('operator_check.generate'):
                case_report.build(folder,render=True,profile_version='profile_snapshot.json')
            calls=[args.args[0] for args in invoke.call_args_list if args.args[0][1]=='scripts/report.py']
            self.assertEqual(len(calls),2)
            self.assertTrue(all(cmd[cmd.index('--profile-version')+1]=='profile_snapshot.json' for cmd in calls))
            self.assertEqual((source/'report.json').read_bytes(),before)

    def test_no_markup_leaks_into_prose(self):
        """手写内容里不能混进简版报告的排版标记（::: 卡片、表格竖线、** 粗体）。"""
        for d in self.cases():
            with open(os.path.join(d, "report.json"), encoding="utf-8") as f:
                rep = json.load(f)
            texts = [rep["summary"]["headline"]] + rep["summary"]["points"] + rep["summary"]["after_the_fact"] + rep["why"]
            for t in texts:
                self.assertNotRegex(t, r":::|\*\*|\s\|\s", f"{os.path.basename(d)}：{t[:40]}")

    def test_reports_state_the_real_outcome(self):
        import glob
        for d in self.cases():
            run = glob.glob(os.path.join(d, "retro_ranks", "*"))[0]
            with open(os.path.join(run, "hindsight.json"), encoding="utf-8") as f:
                h = json.load(f)
            with open(os.path.join(d, "report.json"), encoding="utf-8") as f:
                rep = json.load(f)
            notes = " ".join(rep["hindsight"]["notes"])
            self.assertIn(h["status"], notes, d)
            if h["landing"]:
                self.assertIn(h["landing"].replace("[公办]", "").replace("[民办]", ""), notes, d)


class ScoreTable(unittest.TestCase):
    def test_merged_first_row_uses_official_cumulative(self):
        """各省表首行常是合并档（本段人数不含更高分的人），位次必须取 cum 列，不能逐行累加 count。"""
        import tempfile
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from rank import Table
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("score,count,cum,source\n697,7,56,官方，首行为合并档\n696,14,70,官方\n695,10,80,官方\n")
        try:
            self.assertEqual(Table(f.name).rank_of(695), (71, 80))
        finally:
            os.unlink(f.name)
