"""招生计划类括号（八协计划等）：新规则保留并标“资格待核”，已登记回溯案例沿用旧规则逐字节复现。"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import pipeline  # noqa: E402
import pool  # noqa: E402

R07 = os.path.join(ROOT, "examples", "2026-GK-R07")
BAXIE = "内蒙古大学(八协计划)[公办]·新闻学"


def run(*args):
    p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def r07_copy(tmp, rule):
    """R07 的登记配置复制到临时目录；rule=None 表示去掉开关（新案例默认）。"""
    case = os.path.join(tmp, "R07")
    os.makedirs(case)
    with open(os.path.join(R07, "retro_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.pop("plan_bracket_note", None)
    if rule is None:
        cfg.pop("plan_bracket_rule", None)
    else:
        cfg["plan_bracket_rule"] = rule
    with open(os.path.join(case, "retro_config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    return case


class TestPlanSplit(unittest.TestCase):
    def test_plan_brackets_are_split_off(self):
        self.assertEqual(pool.plan_split("内蒙古大学(八协计划)[公办]"), ("内蒙古大学", ["八协计划"]))
        self.assertEqual(pool.plan_split("华侨大学（面向厦门，01）"), ("华侨大学", ["面向厦门，01"]))
        self.assertEqual(pool.plan_split("某大学(保定)(地方专项计划)"), ("某大学（保定）", ["地方专项计划"]))

    def test_campus_and_college_brackets_are_not_plans(self):
        for name in ("华北电力大学(保定)", "内蒙古大学(呼和浩特市)[公办]", "哈尔滨工业大学（威海）（卓越优才计划）",
                     "烟台大学(原烟台大学文经学院)", "厦门大学(马来西亚分校)"):
            self.assertEqual(pool.plan_split(name)[1], [], name)

    def test_identity_plans_stay_excluded_by_default(self):
        for name in ("华侨大学（面向厦门）", "西南民族大学（少数民族）", "河北大学(地方专项计划)", "重庆大学(本科预科班)"):
            self.assertRegex(name, pool.EXCLUDE_TAGGED)
        self.assertNotRegex("内蒙古大学(八协计划)[公办]", pool.EXCLUDE_TAGGED)
        self.assertNotRegex("中央民族大学", pool.EXCLUDE_TAGGED)


class TestPoolPlanRule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.path.join(self.tmp.name, "old.csv")
        self.new = os.path.join(self.tmp.name, "new.csv")
        self.out = os.path.join(self.tmp.name, "pool.csv")
        self.log = os.path.join(self.tmp.name, "log.json")
        head = ["code", "name", "group", "major", "rank", "plan"]
        data = [["1143", "内蒙古大学(八协计划)[公办]", "", "新闻学", 44877, 3],
                ["0001", "华北电力大学(保定)", "", "电气工程及其自动化", 20000, 30],
                ["0002", "不存在大学(八协计划)[公办]", "", "法学", 30000, 2]]
        for p in (self.old, self.new):
            with open(p, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([head] + data)

    def tearDown(self):
        self.tmp.cleanup()

    def pool(self, *extra):
        code, out, err = run("scripts/pool.py", "--year", "2025=" + self.old, "--year", "2026=" + self.new,
                             "--key", "major", "--school", "name", "--public", "--out", self.out, *extra)
        self.assertEqual(code, 0, err)
        return {r["name"]: r for r in rows(self.out)}

    def test_tag_keeps_plan_with_mark_and_campus_rule_unchanged(self):
        got = self.pool("--screening-log", self.log)
        self.assertEqual(got[BAXIE]["limits"], "资格待核：八协计划")
        self.assertEqual(got[BAXIE]["province"], "内蒙古自治区")
        self.assertNotIn("校区括号", got[BAXIE]["note"])
        campus = got["华北电力大学(保定)·电气工程及其自动化"]
        self.assertIn("校区括号", campus["note"])  # 校区括号照旧提醒，回溯流程照旧剔除
        self.assertEqual(campus["limits"], "")
        self.assertNotIn("不存在大学(八协计划)[公办]·法学", got)  # 括号外校名对不上名单：剔除并记账
        with open(self.log, encoding="utf-8") as f:
            log = json.load(f)
        self.assertIn("不存在大学(八协计划)[公办]·法学", log["unmatched"])
        self.assertEqual(log["dropped"]["院校未匹配教育部名单（办学性质不明）"], 1)
        self.assertEqual(log["eligibility_pending"], [BAXIE])

    def test_legacy_treats_plan_as_campus(self):
        got = self.pool("--plan-brackets", "legacy")
        self.assertIn("校区括号“八协计划”", got[BAXIE]["note"])
        self.assertNotIn("limits", got[BAXIE])


class TestRetroPlanRule(unittest.TestCase):
    def test_registered_cases_pin_legacy(self):
        for i in range(1, 13):
            with open(os.path.join(ROOT, "examples", f"2026-GK-R{i:02d}", "retro_config.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f).get("plan_bracket_rule"), "legacy", f"R{i:02d}")

    def test_r07_legacy_reproduces_committed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = r07_copy(tmp, "legacy")
            code, _, err = run("scripts/retro_run.py", case)
            self.assertEqual(code, 0, err)
            rank = os.listdir(os.path.join(R07, "retro_ranks"))[0]
            for name in ("pool_raw.csv", "pool_manual.csv", "pool.csv", "attributes.csv", "reviewed.csv", "hindsight.json"):
                with open(os.path.join(case, "retro_ranks", rank, name), "rb") as a, \
                        open(os.path.join(R07, "retro_ranks", rank, name), "rb") as b:
                    self.assertEqual(a.read(), b.read(), name)
            def load(d):
                with open(os.path.join(d, "retro_ranks", rank, "result.json"), encoding="utf-8") as f:
                    return json.load(f)
            mine, committed = load(case), load(R07)
            for r in (mine, committed):  # 只有输入输出文件路径因目录不同而不同
                r["params"].pop("csv"), r["params"].pop("json")
            self.assertEqual(mine, committed)

    def test_r07_new_rule_keeps_baxie_journalism_with_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = r07_copy(tmp, None)
            code, _, err = run("scripts/retro_run.py", case, "--no-judge")
            self.assertEqual(code, 0, err)
            rank = os.listdir(os.path.join(case, "retro_ranks"))[0]
            kept = {r["name"]: r for r in rows(os.path.join(case, "retro_ranks", rank, "pool.csv"))}
            self.assertEqual(kept[BAXIE]["limits"], "资格待核：八协计划")
            self.assertGreater(float(kept[BAXIE]["p_clear"]), 0.95)
            self.assertFalse(any("校区括号" in r["note"] for r in kept.values()))
            legacy = {r["name"] for r in rows(os.path.join(R07, "retro_ranks", rank, "pool.csv"))}
            self.assertEqual(set(kept) - legacy, {BAXIE})  # 只多这一条，没有误保留


class TestPipelinePending(unittest.TestCase):
    def test_pipeline_keeps_pending_unless_verified(self):
        row = {"id": "a", "limits": "资格待核：八协计划"}
        self.assertEqual(pipeline.merge_row(row, {"id": "a", "utility": "50"})["limits"], "资格待核：八协计划")
        self.assertEqual(pipeline.merge_row(row, {"id": "a", "limits": "体检：色弱不录"})["limits"], "资格待核：八协计划；体检：色弱不录")
        ok = json.dumps({"status": "verified"})
        self.assertEqual(pipeline.merge_row(row, {"id": "a", "limits": "八协计划：报名资格已核实", "eligibility_evidence": ok})["limits"],
                         "八协计划：报名资格已核实")


if __name__ == "__main__":
    unittest.main()
