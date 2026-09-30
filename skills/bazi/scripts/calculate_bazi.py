#!/usr/bin/env python3
"""Deterministic BaZi chart calculator with explicit calendrical conventions.

The calendrical core is lunar-python v1.4.8 (MIT), vendored beside this file.
This wrapper makes timezone, solar-time, late-Zi, uncertainty, and luck-cycle
assumptions explicit. It does not decide useful gods or predict life events.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VENDOR = Path(__file__).resolve().parent / "vendor"
sys.path.insert(0, str(VENDOR))

from lunar_python import Solar  # noqa: E402
from lunar_python.util import LunarUtil  # noqa: E402


ENGINE = {
    "name": "lunar-python",
    "version": "1.4.8",
    "commit": "000c8a3d74eed098d6256a28fdd51b869324c559",
    "license": "MIT",
}

try:
    TZDB_VERSION = importlib.metadata.version("tzdata")
except importlib.metadata.PackageNotFoundError:
    TZDB_VERSION = "system-zoneinfo-version-not-exposed"

GAN_ELEMENT = dict(zip("甲乙丙丁戊己庚辛壬癸", "木木火火土土金金水水"))
ZHI_ELEMENT = {
    "子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火",
    "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水",
}
SEASONAL = {
    "寅": ("木", "火", "水", "金", "土"), "卯": ("木", "火", "水", "金", "土"),
    "巳": ("火", "土", "木", "水", "金"), "午": ("火", "土", "木", "水", "金"),
    "申": ("金", "水", "土", "火", "木"), "酉": ("金", "水", "土", "火", "木"),
    "亥": ("水", "木", "金", "土", "火"), "子": ("水", "木", "金", "土", "火"),
    "辰": ("土", "金", "火", "木", "水"), "戌": ("土", "金", "火", "木", "水"),
    "丑": ("土", "金", "火", "木", "水"), "未": ("土", "金", "火", "木", "水"),
}
GAN_HE = {frozenset(x) for x in ("甲己", "乙庚", "丙辛", "丁壬", "戊癸")}
ZHI_CHONG = {frozenset(x) for x in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")}
ZHI_LIUHE = {frozenset(x) for x in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")}
ZHI_HAI = {frozenset(x) for x in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")}
ZHI_PO = {frozenset(x) for x in ("子酉", "丑辰", "寅亥", "卯午", "巳申", "未戌")}
SANHE = [set(x) for x in ("申子辰", "亥卯未", "寅午戌", "巳酉丑")]
SANHUI = [set(x) for x in ("寅卯辰", "巳午未", "申酉戌", "亥子丑")]
SANXING = [set(x) for x in ("寅巳申", "丑未戌")]
TIME_GAN_START = {"甲": 0, "己": 0, "乙": 2, "庚": 2, "丙": 4, "辛": 4, "丁": 6, "壬": 6, "戊": 8, "癸": 8}
CHANG_SHENG_OFFSET = {"甲": 1, "丙": 10, "戊": 10, "庚": 7, "壬": 4, "乙": 6, "丁": 9, "己": 9, "辛": 0, "癸": 3}
GAN_INDEX = {x: i for i, x in enumerate("甲乙丙丁戊己庚辛壬癸")}
ZHI_INDEX = {x: i for i, x in enumerate("子丑寅卯辰巳午未申酉戌亥")}
CHANG_SHENG = ("长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养")


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class LocalCandidate:
    aware: datetime
    fold: int
    label: str


def parse_local_datetime(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InputError("birth_datetime_local 必须是 ISO 8601，例如 2000-01-02T03:04:00") from exc
    if dt.tzinfo is not None:
        raise InputError("birth_datetime_local 不得自带时区偏移；请另传 timezone")
    return dt.replace(microsecond=0)


def valid_local_candidates(naive: datetime, zone: ZoneInfo, requested_fold: int | None) -> list[LocalCandidate]:
    found: list[LocalCandidate] = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        roundtrip = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == naive:
            key = aware.utcoffset()
            if not any(x.aware.utcoffset() == key for x in found):
                found.append(LocalCandidate(aware, fold, f"civil-fold-{fold}"))
    if not found:
        raise InputError("该当地时间处于夏令时跳时缺口，不存在；请核对时间或明确改用的实际时刻")
    if requested_fold is not None:
        matches = [x for x in found if x.fold == requested_fold]
        if not matches:
            raise InputError(f"fold={requested_fold} 对这个当地时间无效")
        return matches
    return found


def equation_of_time_minutes(dt: datetime) -> float:
    """NOAA-style approximation; adequate for convention sensitivity, not ephemeris research."""
    n = dt.timetuple().tm_yday
    hour = dt.hour + dt.minute / 60 + dt.second / 3600
    gamma = 2 * math.pi / 365 * (n - 1 + (hour - 12) / 24)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )


def adjust_time(candidate: LocalCandidate, basis: str, longitude: float | None) -> tuple[datetime, dict[str, Any]]:
    civil = candidate.aware.replace(tzinfo=None)
    if basis == "civil":
        return civil, {"basis": basis, "total_correction_minutes": 0.0}
    if longitude is None:
        raise InputError(f"time_basis={basis} 必须提供 longitude")
    utc_naive = candidate.aware.astimezone(timezone.utc).replace(tzinfo=None)
    mean_solar = utc_naive + timedelta(minutes=longitude * 4)
    longitude_correction = (mean_solar - civil).total_seconds() / 60
    eot = equation_of_time_minutes(mean_solar) if basis == "apparent_solar" else 0.0
    adjusted = mean_solar + timedelta(minutes=eot)
    return adjusted, {
        "basis": basis,
        "longitude_degrees_east": longitude,
        "longitude_and_zone_correction_minutes": round(longitude_correction, 4),
        "equation_of_time_minutes": round(eot, 4),
        "total_correction_minutes": round(longitude_correction + eot, 4),
        "equation_of_time_model": "NOAA approximation" if basis == "apparent_solar" else None,
    }


def solar_string(solar: Any) -> str:
    return solar.toYmdHms()


def pillar(eight: Any, name: str) -> dict[str, Any]:
    cap = name.capitalize()
    gz = getattr(eight, f"get{cap}")()
    hidden = list(getattr(eight, f"get{cap}HideGan")())
    return {
        "ganzhi": gz,
        "gan": gz[0],
        "zhi": gz[1],
        "gan_element": GAN_ELEMENT[gz[0]],
        "zhi_element": ZHI_ELEMENT[gz[1]],
        "hidden_stems": hidden,
        "ten_god_stem": getattr(eight, f"get{cap}ShiShenGan")(),
        "ten_gods_hidden": list(getattr(eight, f"get{cap}ShiShenZhi")()),
        "nayin": getattr(eight, f"get{cap}NaYin")(),
        "twelve_stage": getattr(eight, f"get{cap}DiShi")(),
    }


def follow_day_time_pillar(time_pillar: dict[str, Any], day_gan: str) -> dict[str, Any]:
    """Recompute the hour stem from the selected day stem (五鼠遁)."""
    zhi = time_pillar["zhi"]
    gan = "甲乙丙丁戊己庚辛壬癸"[(TIME_GAN_START[day_gan] + ZHI_INDEX[zhi]) % 10]
    item = dict(time_pillar)
    item.update({
        "ganzhi": gan + zhi,
        "gan": gan,
        "gan_element": GAN_ELEMENT[gan],
        "ten_god_stem": LunarUtil.SHI_SHEN[day_gan + gan],
        "nayin": LunarUtil.NAYIN[gan + zhi],
    })
    offset = CHANG_SHENG_OFFSET[day_gan] + (ZHI_INDEX[zhi] if GAN_INDEX[day_gan] % 2 == 0 else -ZHI_INDEX[zhi])
    item["twelve_stage"] = CHANG_SHENG[offset % 12]
    return item


def rebase_pillar_to_day_master(item: dict[str, Any], day_gan: str) -> dict[str, Any]:
    """Recompute day-master-relative fields after combining timezone-safe pillars."""
    out = dict(item)
    out["ten_god_stem"] = LunarUtil.SHI_SHEN[day_gan + out["gan"]]
    out["ten_gods_hidden"] = [LunarUtil.SHI_SHEN[day_gan + gan] for gan in out["hidden_stems"]]
    offset = CHANG_SHENG_OFFSET[day_gan] + (ZHI_INDEX[out["zhi"]] if GAN_INDEX[day_gan] % 2 == 0 else -ZHI_INDEX[out["zhi"]])
    out["twelve_stage"] = CHANG_SHENG[offset % 12]
    return out


def detect_relations(pillars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for i in range(len(pillars)):
        for j in range(i + 1, len(pillars)):
            a, b = pillars[i], pillars[j]
            gp = frozenset((a["gan"], b["gan"]))
            zp = frozenset((a["zhi"], b["zhi"]))
            for label, table in (("天干五合", GAN_HE), ("地支六合", ZHI_LIUHE), ("地支六冲", ZHI_CHONG),
                                 ("地支六害", ZHI_HAI), ("地支六破", ZHI_PO)):
                if (gp if label.startswith("天干") else zp) in table:
                    results.append({"relation": label, "positions": [a["position"], b["position"]],
                                    "members": [a["gan"], b["gan"]] if label.startswith("天干") else [a["zhi"], b["zhi"]]})
    branches = [p["zhi"] for p in pillars]
    branch_set = set(branches)
    for label, groups in (("地支三合", SANHE), ("地支三会", SANHUI), ("地支三刑", SANXING)):
        for group in groups:
            if group <= branch_set:
                results.append({"relation": label, "members": sorted(group), "positions": [p["position"] for p in pillars if p["zhi"] in group]})
    for zhi in set(branches):
        count = branches.count(zhi)
        if zhi in "辰午酉亥" and count >= 2:
            results.append({"relation": "自刑", "members": [zhi] * count,
                            "positions": [p["position"] for p in pillars if p["zhi"] == zhi]})
    for pair in (("子", "卯"),):
        if set(pair) <= branch_set:
            results.append({"relation": "无礼之刑", "members": list(pair),
                            "positions": [p["position"] for p in pillars if p["zhi"] in pair]})
    return results


def seasonal_state(month_zhi: str) -> dict[str, str]:
    values = SEASONAL[month_zhi]
    return dict(zip(("旺", "相", "休", "囚", "死"), values))


def luck_cycles(eight: Any, genders: Iterable[str], sect: int, count: int, include_liunian: bool,
                local_zone: ZoneInfo) -> list[dict[str, Any]]:
    out = []
    for gender in genders:
        yun = eight.getYun(1 if gender == "male" else 0, sect)
        start_beijing = datetime.strptime(solar_string(yun.getStartSolar()), "%Y-%m-%d %H:%M:%S")
        start_instant = start_beijing.replace(tzinfo=timezone(timedelta(hours=8)))
        item: dict[str, Any] = {
            "traditional_gender_parameter": gender,
            "direction": "forward" if yun.isForward() else "backward",
            "start_offset": {"years": yun.getStartYear(), "months": yun.getStartMonth(),
                             "days": yun.getStartDay(), "hours": yun.getStartHour()},
            "start_datetime_beijing_clock": start_beijing.isoformat(sep=" "),
            "start_datetime_birth_zone": start_instant.astimezone(local_zone).isoformat(),
            "start_calculation_sect": sect,
            "dayun": [],
        }
        for dy in yun.getDaYun(count + 1)[1:]:
            d: dict[str, Any] = {
                "ganzhi": dy.getGanZhi(), "start_year": dy.getStartYear(), "end_year": dy.getEndYear(),
                "start_age_nominal": dy.getStartAge(), "end_age_nominal": dy.getEndAge(),
            }
            if include_liunian:
                d["liunian"] = [{"year": x.getYear(), "age_nominal": x.getAge(), "ganzhi": x.getGanZhi()}
                                  for x in dy.getLiuNian()]
            item["dayun"].append(d)
        out.append(item)
    return out


def term_info(jie: Any, local_zone: ZoneInfo, birth_utc: datetime) -> dict[str, Any]:
    beijing_naive = datetime.strptime(solar_string(jie.getSolar()), "%Y-%m-%d %H:%M:%S")
    instant = beijing_naive.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
    return {
        "name": jie.getName(),
        "beijing_clock": beijing_naive.isoformat(sep=" "),
        "utc": instant.isoformat(),
        "birth_zone_clock": instant.astimezone(local_zone).isoformat(),
        "signed_minutes_from_birth": round((instant - birth_utc).total_seconds() / 60, 4),
    }


def compute_one(adjusted: datetime, reference_beijing: datetime, birth_utc: datetime, local_zone: ZoneInfo,
                day_boundary: str, late_zi_hour_stem: str, genders: list[str], luck_sect: int,
                dayun_count: int, include_liunian: bool) -> dict[str, Any]:
    day_solar = Solar.fromYmdHms(adjusted.year, adjusted.month, adjusted.day, adjusted.hour, adjusted.minute, adjusted.second)
    day_lunar = day_solar.getLunar()
    day_eight = day_lunar.getEightChar()
    day_eight.setSect(1 if day_boundary == "zi_initial" else 2)
    reference_solar = Solar.fromYmdHms(reference_beijing.year, reference_beijing.month, reference_beijing.day,
                                       reference_beijing.hour, reference_beijing.minute, reference_beijing.second)
    reference_lunar = reference_solar.getLunar()
    reference_eight = reference_lunar.getEightChar()
    reference_eight.setSect(2)
    ps = []
    for pos, source in (("year", reference_eight), ("month", reference_eight),
                        ("day", day_eight), ("time", day_eight)):
        p = pillar(source, pos)
        p["position"] = pos
        ps.append(p)
    day_gan = ps[2]["gan"]
    ps[0] = {**rebase_pillar_to_day_master(ps[0], day_gan), "position": "year"}
    ps[1] = {**rebase_pillar_to_day_master(ps[1], day_gan), "position": "month"}
    if adjusted.hour == 23 and day_boundary == "midnight" and late_zi_hour_stem == "follow_day":
        ps[3] = {**follow_day_time_pillar(ps[3], ps[2]["gan"]), "position": "time"}
    prev_jie = reference_lunar.getPrevJie()
    next_jie = reference_lunar.getNextJie()
    return {
        "adjusted_datetime_for_pillars": adjusted.isoformat(sep=" "),
        "absolute_instant_utc": birth_utc.isoformat(),
        "beijing_reference_for_solar_terms": reference_beijing.isoformat(sep=" "),
        "day_boundary": day_boundary,
        "late_zi_hour_stem": late_zi_hour_stem,
        "pillars_text": " ".join(p["ganzhi"] for p in ps),
        "day_master": ps[2]["gan"],
        "pillars": {p["position"]: {k: v for k, v in p.items() if k != "position"} for p in ps},
        "seasonal_wang_xiang_xiu_qiu_si": seasonal_state(ps[1]["zhi"]),
        "relations": detect_relations(ps),
        "jieqi": {
            "previous_jie": term_info(prev_jie, local_zone, birth_utc),
            "next_jie": term_info(next_jie, local_zone, birth_utc),
        },
        "luck": luck_cycles(reference_eight, genders, luck_sect, dayun_count, include_liunian, local_zone),
    }


def candidate_offsets(uncertainty: int) -> list[tuple[int, str]]:
    if uncertainty <= 0:
        return [(0, "reported")]
    step = 1 if uncertainty <= 720 else 15
    items = [(0, "reported"), (-uncertainty, "uncertainty-start"), (uncertainty, "uncertainty-end")]
    for value in range(-uncertainty, uncertainty + 1, step):
        items.append((value, "uncertainty-scan"))
    return items


def normalize_genders(value: str | None) -> list[str]:
    if value in (None, "both"):
        return ["male", "female"]
    if value not in ("male", "female"):
        raise InputError("traditional_gender_parameter 必须是 male、female 或 both")
    return [value]


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    naive = parse_local_datetime(payload["birth_datetime_local"])
    try:
        zone = ZoneInfo(payload["timezone"])
    except (ZoneInfoNotFoundError, KeyError) as exc:
        raise InputError("必须提供有效的 IANA timezone，例如 Asia/Shanghai") from exc
    fold = payload.get("fold")
    if fold not in (None, 0, 1):
        raise InputError("fold 只能为 0 或 1")
    local_candidates = valid_local_candidates(naive, zone, fold)
    basis_value = payload.get("time_basis", "civil")
    bases = ["civil", "mean_solar", "apparent_solar"] if basis_value == "compare" else [basis_value]
    if any(x not in ("civil", "mean_solar", "apparent_solar") for x in bases):
        raise InputError("time_basis 必须是 civil、mean_solar、apparent_solar 或 compare")
    longitude = payload.get("longitude")
    if longitude is not None:
        longitude = float(longitude)
        if not -180 <= longitude <= 180:
            raise InputError("longitude 必须在 -180 到 180 之间，东经为正")
    boundary_value = payload.get("day_boundary", "midnight")
    boundaries = ["zi_initial", "midnight"] if boundary_value == "both" else [boundary_value]
    if any(x not in ("zi_initial", "midnight") for x in boundaries):
        raise InputError("day_boundary 必须是 zi_initial、midnight 或 both")
    late_zi_value = payload.get("late_zi_hour_stem", "follow_day")
    late_zi_modes = ["follow_day", "next_day"] if late_zi_value == "both" else [late_zi_value]
    if any(x not in ("follow_day", "next_day") for x in late_zi_modes):
        raise InputError("late_zi_hour_stem 必须是 follow_day、next_day 或 both")
    genders = normalize_genders(payload.get("traditional_gender_parameter"))
    uncertainty = int(payload.get("uncertainty_minutes", 0))
    if not 0 <= uncertainty <= 10080:
        raise InputError("uncertainty_minutes 必须在 0 到 10080 之间")
    luck_sect = int(payload.get("luck_start_sect", 2))
    if luck_sect not in (1, 2):
        raise InputError("luck_start_sect 只能为 1 或 2")
    dayun_count = int(payload.get("dayun_count", 8))
    if not 1 <= dayun_count <= 12:
        raise InputError("dayun_count 必须在 1 到 12 之间")
    include_liunian = bool(payload.get("include_liunian", True))

    output: dict[str, Any] = {
        "schema_version": "1.0.0",
        "engine": ENGINE,
        "input": payload,
        "warnings": [],
        "candidates": [],
    }
    if len(local_candidates) > 1:
        output["warnings"].append("该当地时间处于夏令时重复时段；已分别计算两个 fold 候选")

    seen: dict[str, dict[str, Any]] = {}
    for local in local_candidates:
        for basis in bases:
            for minute_offset, time_label in candidate_offsets(uncertainty):
                shifted_utc = local.aware.astimezone(timezone.utc) + timedelta(minutes=minute_offset)
                shifted_aware = shifted_utc.astimezone(zone)
                shifted_local = LocalCandidate(shifted_aware, shifted_aware.fold, local.label)
                time_value, correction = adjust_time(shifted_local, basis, longitude)
                reference_beijing = shifted_utc.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
                for boundary in boundaries:
                    for late_zi_mode in late_zi_modes:
                        chart = compute_one(time_value, reference_beijing, shifted_utc, zone, boundary, late_zi_mode,
                                            genders, luck_sect, dayun_count, include_liunian)
                        signature = json.dumps({
                            "fold": shifted_aware.fold,
                            "pillars": chart["pillars_text"],
                            "luck_direction": [(x["traditional_gender_parameter"], x["direction"]) for x in chart["luck"]],
                        }, ensure_ascii=False, sort_keys=True)
                        if signature not in seen:
                            seen[signature] = {
                                "candidate_id": f"C{len(seen) + 1}", "civil_fold": shifted_aware.fold,
                                "resolved_civil_datetime": shifted_aware.isoformat(),
                                "timezone": payload["timezone"],
                                "timezone_database": TZDB_VERSION,
                                "time_basis": basis, "time_correction": correction,
                                "candidate_reason": [time_label],
                                "compatible_conventions": {
                                    "time_bases": [basis], "day_boundaries": [boundary],
                                    "late_zi_hour_stems": [late_zi_mode],
                                },
                                "_sample_times": {basis: [time_value.isoformat(sep=" ")]}, **chart,
                            }
                        else:
                            seen[signature]["_sample_times"].setdefault(basis, []).append(time_value.isoformat(sep=" "))
                            if time_label not in seen[signature]["candidate_reason"]:
                                seen[signature]["candidate_reason"].append(time_label)
                            conventions = seen[signature]["compatible_conventions"]
                            for key, value in (("time_bases", basis), ("day_boundaries", boundary),
                                               ("late_zi_hour_stems", late_zi_mode)):
                                if value not in conventions[key]:
                                    conventions[key].append(value)

            central_utc = local.aware.astimezone(timezone.utc)
            central_adjusted, _ = adjust_time(local, basis, longitude)
            central_beijing = central_utc.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
            base_chart = compute_one(central_adjusted, central_beijing, central_utc, zone, boundaries[0], late_zi_modes[0],
                                     genders, luck_sect, dayun_count, False)
            nearest = min(abs(base_chart["jieqi"]["previous_jie"]["signed_minutes_from_birth"]),
                          abs(base_chart["jieqi"]["next_jie"]["signed_minutes_from_birth"]))
            if nearest <= 30 and uncertainty == 0:
                output["warnings"].append(f"{basis} 时间距交节不足 {nearest:.1f} 分钟；需优先核对出生时间精度")
            if central_adjusted.hour == 23 or (central_adjusted.hour == 0 and central_adjusted.minute <= 30):
                if len(boundaries) == 1:
                    output["warnings"].append(f"{basis} 时间靠近换日争议区；建议 day_boundary=both 比较")
    for item in seen.values():
        sampled = item.pop("_sample_times")
        item["sampled_effective_time_ranges_by_basis"] = {
            basis: {"start": sorted(times)[0], "end": sorted(times)[-1]} for basis, times in sampled.items()
        }
    output["candidates"] = list(seen.values())
    output["candidate_count"] = len(output["candidates"])
    output["warnings"] = list(dict.fromkeys(output["warnings"]))
    output["interpretation_boundary"] = (
        "本输出只计算历法与结构事实；旺衰、格局、调候、从化和事件判断必须另行给出规则与证据。"
    )
    return output


def markdown(result: dict[str, Any]) -> str:
    lines = ["# 八字排盘结果", "", f"候选盘：{result['candidate_count']} 个", ""]
    for warning in result["warnings"]:
        lines.append(f"- 警告：{warning}")
    if result["warnings"]:
        lines.append("")
    for c in result["candidates"]:
        lines.extend([
            f"## {c['candidate_id']} — {c['pillars_text']}", "",
            f"- 时间口径：{'／'.join(c['compatible_conventions']['time_bases'])}；换日：{'／'.join(c['compatible_conventions']['day_boundaries'])}；fold：{c['civil_fold']}",
            f"- 排盘采用时间：{c['adjusted_datetime_for_pillars']}",
            f"- 日主：{c['day_master']}",
            f"- 前一节：{c['jieqi']['previous_jie']['name']} {c['jieqi']['previous_jie']['birth_zone_clock']}",
            f"- 后一节：{c['jieqi']['next_jie']['name']} {c['jieqi']['next_jie']['birth_zone_clock']}", "",
            "| 柱 | 干支 | 藏干 | 天干十神 | 藏干十神 | 纳音 | 十二长生 |", "|---|---|---|---|---|---|---|",
        ])
        for key, label in (("year", "年"), ("month", "月"), ("day", "日"), ("time", "时")):
            p = c["pillars"][key]
            lines.append(f"| {label} | {p['ganzhi']} | {'、'.join(p['hidden_stems'])} | {p['ten_god_stem']} | {'、'.join(p['ten_gods_hidden'])} | {p['nayin']} | {p['twelve_stage']} |")
        lines.append("")
    lines.append(f"> {result['interpretation_boundary']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="计算带明确口径和候选分支的八字命盘")
    parser.add_argument("input", help="输入 JSON 文件，使用 - 从 stdin 读取")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        payload = json.loads(raw)
        result = calculate(payload)
    except (OSError, json.JSONDecodeError, InputError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.format == "markdown":
        print(markdown(result), end="")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
