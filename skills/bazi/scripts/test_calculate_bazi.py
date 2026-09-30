#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("calculate_bazi.py")
SPEC = importlib.util.spec_from_file_location("calculate_bazi", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def payload(**overrides):
    data = {
        "birth_datetime_local": "2005-12-23T08:37:00",
        "timezone": "Asia/Shanghai",
        "time_basis": "civil",
        "day_boundary": "midnight",
        "traditional_gender_parameter": "male",
        "dayun_count": 2,
        "include_liunian": False,
    }
    data.update(overrides)
    return data


class BaziCalculatorTest(unittest.TestCase):
    def test_known_engine_fixture(self):
        result = MOD.calculate(payload())
        self.assertEqual(1, result["candidate_count"])
        chart = result["candidates"][0]
        self.assertEqual("乙酉 戊子 辛巳 壬辰", chart["pillars_text"])
        self.assertEqual("偏财", chart["pillars"]["year"]["ten_god_stem"])
        self.assertEqual(["丙", "庚", "戊"], chart["pillars"]["day"]["hidden_stems"])

    def test_relation_detection_reports_structure_without_interpreting_it(self):
        pillars = [
            {"position": "year", "gan": "甲", "zhi": "申"},
            {"position": "month", "gan": "己", "zhi": "子"},
            {"position": "day", "gan": "丙", "zhi": "辰"},
            {"position": "time", "gan": "辛", "zhi": "寅"},
        ]
        relations = MOD.detect_relations(pillars)
        labels = {x["relation"] for x in relations}
        self.assertIn("天干五合", labels)
        self.assertIn("地支六冲", labels)
        self.assertIn("地支三合", labels)

    def test_seasonal_table_is_explicit_traditional_mapping(self):
        self.assertEqual({"旺": "木", "相": "火", "休": "水", "囚": "金", "死": "土"}, MOD.seasonal_state("寅"))

    def test_late_zi_conventions_branch(self):
        result = MOD.calculate(payload(
            birth_datetime_local="1988-02-15T23:30:00",
            day_boundary="both",
        ))
        pillars = {x["pillars_text"] for x in result["candidates"]}
        self.assertIn("戊辰 甲寅 辛丑 戊子", pillars)
        self.assertIn("戊辰 甲寅 庚子 丙子", pillars)

    def test_late_zi_hour_stem_can_compare(self):
        result = MOD.calculate(payload(
            birth_datetime_local="1988-02-15T23:30:00",
            day_boundary="midnight",
            late_zi_hour_stem="both",
        ))
        pillars = {x["pillars_text"] for x in result["candidates"]}
        self.assertEqual({"戊辰 甲寅 庚子 丙子", "戊辰 甲寅 庚子 戊子"}, pillars)

    def test_dst_fold_generates_two_candidates(self):
        result = MOD.calculate(payload(
            birth_datetime_local="2023-11-05T01:30:00",
            timezone="America/New_York",
        ))
        self.assertEqual({0, 1}, {x["civil_fold"] for x in result["candidates"]})
        self.assertTrue(any("夏令时重复" in x for x in result["warnings"]))

    def test_dst_gap_rejected(self):
        with self.assertRaises(MOD.InputError):
            MOD.calculate(payload(
                birth_datetime_local="2023-03-12T02:30:00",
                timezone="America/New_York",
            ))

    def test_solar_time_requires_longitude(self):
        with self.assertRaises(MOD.InputError):
            MOD.calculate(payload(time_basis="apparent_solar"))

    def test_solar_time_changes_effective_time(self):
        result = MOD.calculate(payload(
            birth_datetime_local="2000-01-01T12:00:00",
            time_basis="compare",
            longitude=75.0,
        ))
        bases = {basis for x in result["candidates"] for basis in x["compatible_conventions"]["time_bases"]}
        self.assertEqual({"civil", "mean_solar", "apparent_solar"}, bases)

    def test_uncertainty_deduplicates_structural_candidates(self):
        result = MOD.calculate(payload(uncertainty_minutes=90))
        self.assertGreaterEqual(result["candidate_count"], 2)
        self.assertLess(result["candidate_count"], 20)

    def test_sixty_day_cycle_advances(self):
        first = MOD.calculate(payload(birth_datetime_local="2000-01-01T12:00:00"))["candidates"][0]
        second = MOD.calculate(payload(birth_datetime_local="2000-01-02T12:00:00"))["candidates"][0]
        self.assertNotEqual(first["pillars"]["day"]["ganzhi"], second["pillars"]["day"]["ganzhi"])

    def test_sixty_days_returns_same_day_pillar(self):
        first = MOD.calculate(payload(birth_datetime_local="2000-01-01T12:00:00"))["candidates"][0]
        later = MOD.calculate(payload(birth_datetime_local="2000-03-01T12:00:00"))["candidates"][0]
        self.assertEqual(first["pillars"]["day"]["ganzhi"], later["pillars"]["day"]["ganzhi"])

    def test_lichun_changes_year_and_month_at_exact_instant(self):
        before = MOD.calculate(payload(birth_datetime_local="2024-02-04T16:27:06"))["candidates"][0]
        after = MOD.calculate(payload(birth_datetime_local="2024-02-04T16:27:08"))["candidates"][0]
        self.assertEqual("癸卯", before["pillars"]["year"]["ganzhi"])
        self.assertEqual("乙丑", before["pillars"]["month"]["ganzhi"])
        self.assertEqual("甲辰", after["pillars"]["year"]["ganzhi"])
        self.assertEqual("丙寅", after["pillars"]["month"]["ganzhi"])

    def test_same_instant_has_same_year_month_across_zones(self):
        shanghai = MOD.calculate(payload(birth_datetime_local="2024-02-04T16:27:08"))["candidates"][0]
        new_york = MOD.calculate(payload(
            birth_datetime_local="2024-02-04T03:27:08",
            timezone="America/New_York",
        ))["candidates"][0]
        self.assertEqual(shanghai["pillars"]["year"]["ganzhi"], new_york["pillars"]["year"]["ganzhi"])
        self.assertEqual(shanghai["pillars"]["month"]["ganzhi"], new_york["pillars"]["month"]["ganzhi"])
        self.assertNotEqual(shanghai["pillars"]["time"]["ganzhi"], new_york["pillars"]["time"]["ganzhi"])

    def test_irrelevant_convention_branches_are_merged(self):
        result = MOD.calculate(payload(
            birth_datetime_local="2024-02-04T03:27:00",
            timezone="America/New_York",
            longitude=-74.006,
            time_basis="compare",
            day_boundary="both",
            late_zi_hour_stem="both",
            traditional_gender_parameter="both",
            uncertainty_minutes=5,
        ))
        self.assertEqual(2, result["candidate_count"])
        self.assertEqual(
            {"癸卯 乙丑 戊戌 甲寅", "甲辰 丙寅 戊戌 甲寅"},
            {x["pillars_text"] for x in result["candidates"]},
        )
        for candidate in result["candidates"]:
            self.assertEqual({"zi_initial", "midnight"}, set(candidate["compatible_conventions"]["day_boundaries"]))

    def test_leap_lunar_month_does_not_reset_bazi_month(self):
        first = MOD.calculate(payload(birth_datetime_local="2023-03-23T12:00:00"))["candidates"][0]
        second = MOD.calculate(payload(birth_datetime_local="2023-04-01T12:00:00"))["candidates"][0]
        self.assertEqual(first["pillars"]["month"]["ganzhi"], second["pillars"]["month"]["ganzhi"])


if __name__ == "__main__":
    unittest.main()
