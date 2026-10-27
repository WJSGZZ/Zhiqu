#!/usr/bin/env python3
"""校验各省投档 CSV、入学后的机会表和求职版选调高校范围表。

检查：
1. 表头是否包含 code, name 和 score / rank 之一；
2. 位次与分数是否一致：同一文件里分数更高的条目，位次应更靠前（数字更小）。
   随机抽取成对比较，违反比例超过阈值（默认 2%）报警——多半是列错位、OCR 错读或位次推算有误；
3. 重复键（同一院校代码 + 专业组 / 专业出现多次）；
4. 年份覆盖（中间缺年）；
5. 代码数值在教育部高校名单（data/schools.csv）的出现率，不证明同一学校，须核对校名；
6. 同一院校代码在同一文件里出现多个校名（括号注释除外）——多半是 PDF 水印字或识别噪声混进了校名
   （如江苏的"育南京大学"、上海的"市华东师大"、湖北的"北京化 工大学信"）；
7. 入学后的机会表：必要列、证据状态、来源网址、真实日期与复核先后顺序；
8. 选调高校范围表：必要列、2027 年份、来源定位、日期与复核先后顺序、重复条目；
9. 来源（data-model.md）：每个省份目录有 sources.csv，目录里每个 CSV 的每一行都带 source_id 且能在 sources.csv 找到；
   data/ 根目录的 schools.csv、undergrad_majors.csv 对应 data/sources.csv。

usage: python3 scripts/validate_data.py [省份目录名 ...]   # 不给则检查全部
"""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
from datetime import date
import os
import random
import re
import sys
from urllib.parse import urlsplit

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CAREER_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "zhiqu-career", "data")
SKIP_DIRS = {"civil_service", "calibration", "purchased"}  # purchased 是本地内部库，不提交
MAX_SCORE = 750
VIOLATION_WARN = 0.02
AFTER_ENTRY_FIELDS = (
    "school", "province", "opportunity_type", "project_name", "eligibility",
    "selection_time", "selection_method", "seats", "available_majors",
    "extra_fees", "applicable_year", "source_url", "verified_date",
    "review_deadline", "status", "notes",
)
AFTER_ENTRY_STATUSES = {"verified", "not_found", "unretrieved"}
SOURCE_FIELDS = ("source_id", "grade", "publisher", "title", "landing_url", "file_url", "published", "retrieved", "method", "archive_sha256", "archive_path", "archive_status", "wayback_url", "note", "citation", "license", "producer_revision")
LEGACY_SOURCE_FIELDS = ("source_id", "grade", "publisher", "title", "url", "landing_url", "published", "retrieved", "method", "note")
STORED_STATUSES = {"已存原件", "原链接失效·存档副本"}
DELETED_STATUSES = {"已核后删除（有指纹）", "已删除（有指纹，核对见记录）"}
ARCHIVE_STATUSES = STORED_STATUSES | DELETED_STATUSES | {"未取到"}
ORIGINAL_INDEX_FIELDS = ("sha256", "size", "media_type", "source_url", "retrieved", "source_id")
REPO_ROOT = Path(__file__).resolve().parents[3]
ORIGINALS_RELATIVE = Path("skills/zhiqu-shared/originals")
MAX_ORIGINAL_BYTES = 5_000_000
LOCAL_ORIGINALS_RELATIVE = (Path("skills/zhiqu/data/purchased/originals"),
                            Path("skills/zhiqu-grad/data/purchased/originals"))
SOURCE_GRADES = {"官方", "第三方整理"}
ROOT_SOURCED = ("schools.csv", "undergrad_majors.csv")
SELECTED_UNIVERSITIES_FIELDS = (
    "province", "year", "category", "school", "major_restriction", "source_url",
    "published_date", "retrieved_date", "review_deadline", "source_locator", "notes",
)


def num(v):
    v = (v or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def check_after_entry_file(path):
    """校验机会表的来源地址与复核时间；不把格式合格当作内容已核实。"""
    issues, notes = [], []
    if not os.path.isfile(path):
        return ["入学后的机会表不存在"], notes
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing = [field for field in AFTER_ENTRY_FIELDS if field not in header]
        if missing:
            return [f"表头缺少必要列：{', '.join(missing)}"], notes
        rows = list(reader)
    if not rows:
        return ["空文件"], notes
    for line, row in enumerate(rows, start=2):
        for field in ("school", "province", "opportunity_type", "status"):
            if not (row.get(field) or "").strip():
                issues.append(f"第 {line} 行 {field} 不能为空")
        status = (row.get("status") or "").strip()
        if status and status not in AFTER_ENTRY_STATUSES:
            issues.append(f"第 {line} 行 status 未知：{status}")
        source = (row.get("source_url") or "").strip()
        try:
            parsed = urlsplit(source)
            valid_source = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            valid_source = False
        if not valid_source:
            issues.append(f"第 {line} 行 source_url 必须是非空的 http/https 网址")
        dates = {}
        for field in ("verified_date", "review_deadline"):
            value = (row.get(field) or "").strip()
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError
                dates[field] = date.fromisoformat(value)
            except ValueError:
                issues.append(f"第 {line} 行 {field} 必须是真实的 YYYY-MM-DD 日期：{value}")
        if len(dates) == 2 and dates["review_deadline"] < dates["verified_date"]:
            issues.append(f"第 {line} 行复核期限早于核实日期")
    notes.append(f"{len(rows)} 行，{len({(row.get('school') or '').strip() for row in rows})} 所学校")
    return issues, notes


COMPETITION_FIELDS = (
    "province", "year", "measure", "unit", "group_type", "group", "n_jobs",
    "p10", "p25", "p50", "p75", "p90", "share_below_10", "share_100_plus",
    "scope", "source_url", "published_date", "retrieved_date", "review_deadline",
)


def check_competition_file(path):
    """校验公务员竞争汇总表：分位数要递增，比例在 0—1，日期为真实日期。"""
    issues, notes = [], []
    if not os.path.isfile(path):
        return ["竞争汇总表不存在"], notes
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [x for x in COMPETITION_FIELDS if x not in (reader.fieldnames or [])]
        if missing:
            return [f"表头缺少必要列：{', '.join(missing)}"], notes
        rows = list(reader)
    if not rows:
        return ["空文件"], notes
    for i, r in enumerate(rows, start=2):
        where = f"第 {i} 行"
        if not re.match(r"^https?://", r["source_url"].strip()):
            issues.append(f"{where}：source_url 不是网址")
        for k in ("retrieved_date", "review_deadline") + (("published_date",) if r["published_date"].strip() else ()):
            try:
                datetime.date.fromisoformat(r[k].strip())
            except ValueError:
                issues.append(f"{where}：{k} 不是真实日期")
        try:
            n = int(r["n_jobs"])
            qs = [float(r[k]) for k in ("p10", "p25", "p50", "p75", "p90")]
        except ValueError:
            issues.append(f"{where}：n_jobs 或分位数不是数字")
            continue
        if n <= 0:
            issues.append(f"{where}：n_jobs 必须为正")
        if qs != sorted(qs):
            issues.append(f"{where}：分位数没有递增")
        for k in ("share_below_10", "share_100_plus"):
            v = r[k].strip()
            if v and not 0 <= float(v) <= 1:
                issues.append(f"{where}：{k} 不在 0—1")
    notes.append(f"{len(rows)} 行")
    return issues, notes


def check_selected_universities_file(path):
    """校验选调高校范围表；来源定位供人工回到官方附件复核。"""
    issues, notes = [], []
    if not os.path.isfile(path):
        return ["选调高校范围表不存在"], notes
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [field for field in SELECTED_UNIVERSITIES_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            return [f"表头缺少必要列：{', '.join(missing)}"], notes
        rows = list(reader)
    if not rows:
        return ["空文件"], notes
    seen = {}
    required = set(SELECTED_UNIVERSITIES_FIELDS) - {"major_restriction", "notes"}
    for line, row in enumerate(rows, start=2):
        values = {field: (row.get(field) or "").strip() for field in SELECTED_UNIVERSITIES_FIELDS}
        for field in SELECTED_UNIVERSITIES_FIELDS:
            if field in required and not values[field]:
                issues.append(f"第 {line} 行 {field} 不能为空")
        if values["year"] != "2027":
            issues.append(f"第 {line} 行 year 必须是整数 2027：{values['year']}")
        source = values["source_url"]
        try:
            parsed = urlsplit(source)
            valid_source = (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                            and not re.search(r"\s", source))
            parsed.port  # 非数字或超范围端口也不是合法网址
        except ValueError:
            valid_source = False
        if not valid_source:
            issues.append(f"第 {line} 行 source_url 必须是非空的 http/https 网址")
        dates = {}
        for field in ("published_date", "retrieved_date", "review_deadline"):
            value = values[field]
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    raise ValueError
                dates[field] = date.fromisoformat(value)
            except ValueError:
                issues.append(f"第 {line} 行 {field} 必须是真实的 YYYY-MM-DD 日期：{value}")
        if ("review_deadline" in dates and "retrieved_date" in dates
                and dates["review_deadline"] < dates["retrieved_date"]):
            issues.append(f"第 {line} 行复核期限早于取得日期")
        key = tuple(values[field] for field in ("province", "year", "category", "school", "major_restriction"))
        if key in seen:
            issues.append(f"第 {line} 行与第 {seen[key]} 行重复：province/year/category/school/major_restriction")
        else:
            seen[key] = line
    notes.append(f"{len(rows)} 行，{len({row.get('school') for row in rows})} 个原文校名")
    return issues, notes


def read_sources(path):
    """Read provenance rows; legacy url is an explicit read-only alias for file_url.

    This helper does not certify the schema. check_sources still rejects a legacy
    header and all new rows must supply the complete unified provenance fields.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = tuple(reader.fieldnames or ())
        rows = [{k: (v or "").strip() if isinstance(v, str) or v is None else v
                 for k, v in row.items()} for row in reader]
    if "url" in header:
        for row in rows:
            if not row.get("file_url"):
                row["file_url"] = row.get("url", "")
    return rows, header


def _valid_source_url(value):
    try:
        parsed = urlsplit(value)
        parsed.port
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and not re.search(r"\s", value))
    except (ValueError, TypeError):
        return False


def _real_iso_date(value):
    try:
        return bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) and date.fromisoformat(value))
    except (ValueError, TypeError):
        return False


def _archive_file(root, relative, sha):
    """Resolve only canonical repository-relative, content-addressed originals."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        return None, "archive_path 必须是仓库相对路径"
    posix = PurePosixPath(relative)
    if posix.is_absolute() or any(p in (".", "..", "") for p in relative.split("/")):
        return None, "archive_path 不得为绝对路径或包含路径越界片段"
    base = None
    for candidate in (ORIGINALS_RELATIVE, *LOCAL_ORIGINALS_RELATIVE):
        expected = candidate.as_posix() + "/" + sha[:2] + "/" + sha
        if re.fullmatch(re.escape(expected) + r"\.[a-z0-9]{1,10}", relative):
            base = candidate
            break
    if base is None:
        return None, "archive_path 应为公开或两个本机原件库 originals/sha前2位/sha.ext 的完整仓库相对路径"
    path = (Path(root) / posix).resolve()
    originals = (Path(root) / base).resolve()
    if not originals.is_relative_to(Path(root).resolve()) or not path.is_relative_to(originals):
        return None, "archive_path 路径越界（含符号链接）"
    if not path.is_file():
        return None, "archive_path 原件不存在"
    if base == ORIGINALS_RELATIVE and path.stat().st_size > MAX_ORIGINAL_BYTES:
        return None, "原件超过 5,000,000 bytes，不得放入公开原件库"
    digest = hashlib.sha256()
    with path.open("rb") as original:
        for chunk in iter(lambda: original.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha:
        return None, "archive_sha256 与原件内容不符"
    return path, None


def check_sources(folder, files, repository_root=None):
    """Validate the strict unified header, original hashes and source_id links."""
    issues, notes = [], []
    root = Path(repository_root or REPO_ROOT)
    path = os.path.join(folder, "sources.csv")
    if not os.path.isfile(path):
        return ["缺少 sources.csv"], notes
    rows, header = read_sources(path)
    if header != SOURCE_FIELDS:
        legacy = "；旧 url 可兼容读取，但必须迁移到新表头后才通过校验" if "url" in header else ""
        return [f"sources.csv 列应为 {','.join(SOURCE_FIELDS)}{legacy}"], notes
    ids = {}
    for line, r in enumerate(rows, 2):
        where = f"sources.csv 第 {line} 行"
        if None in r:
            issues.append(f"{where} CSV数据列数多于统一表头")
        sid = r["source_id"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", sid):
            issues.append(f"{where} source_id 只能用小写字母、数字和连字符：{sid!r}")
        if sid in ids:
            issues.append(f"{where} source_id 与第 {ids[sid]} 行重复：{sid}")
        ids[sid] = line
        if r["grade"] not in SOURCE_GRADES:
            issues.append(f"{where} grade 只能是 {'、'.join(sorted(SOURCE_GRADES))}：{r['grade']!r}")
        if not r["publisher"]:
            issues.append(f"{where} 缺 publisher")
        for field in ("published", "retrieved"):
            if r[field] and not _real_iso_date(r[field]):
                issues.append(f"{where} {field} 须为 YYYY-MM-DD：{r[field]}")
        for field in ("landing_url", "file_url", "wayback_url"):
            if r[field] and not _valid_source_url(r[field]):
                issues.append(f"{where} {field} 不是有效的 http/https 网址：{r[field]}")
        if r["grade"] == "官方" and not (r["landing_url"] or r["file_url"]):
            issues.append(f"{where} 官方来源至少须有 landing_url 或 file_url")
        status, sha, archive = r["archive_status"], r["archive_sha256"], r["archive_path"]
        if status not in ARCHIVE_STATUSES:
            issues.append(f"{where} archive_status 只能是 {'、'.join(sorted(ARCHIVE_STATUSES))}")
        if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
            issues.append(f"{where} archive_sha256 须为64位小写十六进制")
        if status in STORED_STATUSES:
            if r["grade"] != "官方" and archive.startswith(ORIGINALS_RELATIVE.as_posix() + "/"):
                issues.append(f"{where} 公开原件库仅收官方公开原件")
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                issues.append(f"{where} 声称已存原件必须有 archive_sha256")
            else:
                _, error = _archive_file(root, archive, sha)
                if error:
                    issues.append(f"{where} {error}")
        elif status in DELETED_STATUSES:
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                issues.append(f"{where} 已删除原件必须有64位 archive_sha256")
            if archive:
                issues.append(f"{where} 已删除原件不得填写 archive_path")
        elif status == "未取到" and archive:
            issues.append(f"{where} 未取到不得填写 archive_path 或声称已存原件")
    used = set()
    for fn in files:
        with open(os.path.join(folder, fn), encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if "source_id" not in (reader.fieldnames or []):
                issues.append(f"{fn} 缺 source_id 列")
                continue
            bad = []
            for line, r in enumerate(reader, 2):
                if r.get("source_id") in ids:
                    used.add(r["source_id"])
                else:
                    bad.append((line, r.get("source_id")))
        if bad:
            issues.append(f"{fn} 有 {len(bad)} 行 source_id 为空或未在 sources.csv 登记（如第 {bad[0][0]} 行 {bad[0][1]!r}）")
    unused = sorted(set(ids) - used)
    notes.append(f"来源 {len(ids)} 条" + (f"，未被引用 {len(unused)} 条：{', '.join(unused[:3])}" if unused else ""))
    return issues, notes


def check_originals_index(repository_root=None, index_path=None, source_paths=None):
    """Offline cross-check of the public original index and registered source rows.

    “Official/public” means an official row with a public HTTP(S) source URL; this
    mechanical check does not replace human verification of the publisher.
    """
    root = Path(repository_root or REPO_ROOT).resolve()
    directory = root / ORIGINALS_RELATIVE
    path = Path(index_path) if index_path else directory / "index.csv"
    issues, notes = [], []
    if not directory.exists() and index_path is None:
        # Current policy retains fingerprints/locators, then deletes originals.
        # Absence of the legacy directory is valid; provenance rows still must
        # satisfy the same URL, grade, date, status, hash and path invariants.
        paths = list(source_paths) if source_paths is not None else [
            p for p in root.glob("skills/*/data/**/sources.csv") if "purchased" not in p.parts]
        for source_path in paths:
            metadata_issues, _ = check_sources(Path(source_path).parent, [], root)
            relative = str(Path(source_path).relative_to(root))
            issues.extend(relative + "：" + issue for issue in metadata_issues)
        notes.append(f"原件按删除政策不留存；已校验 {len(paths)} 份来源元数据")
        return issues, notes
    if not path.is_file():
        return ["公开原件库缺 index.csv"], notes
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != ORIGINAL_INDEX_FIELDS:
            return ["原件 index.csv 列应为 " + ",".join(ORIGINAL_INDEX_FIELDS)], notes
        rows = list(reader)
    if source_paths is None:
        source_paths = [p for p in root.glob("skills/*/data/**/sources.csv") if "purchased" not in p.parts]
    source_paths = list(source_paths)
    catalog = directory / "sources.csv"
    if catalog.is_file() and catalog not in source_paths:
        source_paths.append(catalog)
    sources = {}
    catalog_rows = []
    for source_path in source_paths:
        source_rows, header = read_sources(source_path)
        if header != SOURCE_FIELDS:
            issues.append(str(Path(source_path).relative_to(root)) + " 来源表不是统一新表头")
        if Path(source_path) == catalog:
            catalog_issues, _ = check_sources(directory, [], root)
            issues.extend("原件 canonical catalog：" + issue for issue in catalog_issues)
            catalog_rows = source_rows
            partial_ids = set()
            member_path = directory / "assets.csv"
            if member_path.exists():
                with member_path.open(encoding="utf-8-sig", newline="") as f:
                    partial_ids = {r.get("source_id") for r in csv.DictReader(f)}
            for row in catalog_rows:
                partial = row.get("archive_status") == "未取到" and row.get("source_id") in partial_ids
                if (row.get("grade") != "官方" or (not partial and (row.get("archive_status") not in STORED_STATUSES
                        or not (row.get("archive_path") or "").startswith(ORIGINALS_RELATIVE.as_posix() + "/")))):
                    issues.append("原件 canonical catalog 仅允许实际已存的官方公开来源（不能登记本机原件）：" + str(row.get("source_id", "")))
        for row in source_rows:
            sources.setdefault(row.get("source_id", ""), []).append(row)
    # A database-only official source may be registered solely in the tracked
    # catalog. Repeated public identities must agree instead of silently letting
    # one catalog row override contradictory public provenance.
    for row in catalog_rows:
        sid = row.get("source_id", "")
        for other in sources.get(sid, []):
            if other is row:
                continue
            fields = ("grade", "archive_sha256", "archive_path", "archive_status")
            conflicts = [field for field in fields if row.get(field, "") != other.get(field, "")]
            urls = lambda value: {value.get(k) for k in ("landing_url", "file_url", "wayback_url") if value.get(k)}
            if not urls(row).intersection(urls(other)):
                conflicts.append("URL")
            if conflicts:
                issues.append("原件 canonical catalog 与公开来源不一致：" + sid + "（" + ",".join(conflicts) + "）")
    # A source can comprise a landing page plus several actual data images.
    # Each member is registered explicitly; an arbitrary matching URL/hash is insufficient.
    assets = {}
    assets_path = directory / "assets.csv"
    asset_fields = ("source_id", "sha256", "path", "url", "role", "retrieved")
    if assets_path.exists():
        with assets_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if tuple(reader.fieldnames or ()) != asset_fields:
                issues.append("原件 assets.csv 表头不符合逐成员规范")
            for asset in reader:
                sid = asset.get("source_id", "")
                key = (sid, asset.get("sha256", ""))
                if key in assets:
                    issues.append("原件成员重复：" + sid)
                assets[key] = asset
                if not any(x.get("grade") == "官方" for x in sources.get(sid, [])):
                    issues.append("原件成员没有官方来源：" + sid)
                if asset.get("role") not in ("data_image", "attachment", "landing_page"):
                    issues.append("原件成员role非法：" + sid)
                if not _valid_source_url(asset.get("url", "")) or not _real_iso_date(asset.get("retrieved", "")):
                    issues.append("原件成员网址或日期非法：" + sid)
                _, error = _archive_file(root, asset.get("path", ""), asset.get("sha256", ""))
                if error:
                    issues.append("原件成员 " + sid + " " + error)
    seen, indexed_files = set(), set()
    for line, row in enumerate(rows, 2):
        where = f"原件 index.csv 第 {line} 行"
        sha, sid = row.get("sha256") or "", row.get("source_id") or ""
        pair = (sha, sid)
        if pair in seen:
            issues.append(f"{where} (sha256,source_id) 重复")
        seen.add(pair)
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            issues.append(f"{where} sha256 须为64位小写十六进制")
            continue
        try:
            size = int(row.get("size", ""))
            if not 0 < size <= MAX_ORIGINAL_BYTES:
                raise ValueError
        except (ValueError, TypeError):
            issues.append(f"{where} size 必须在1—5,000,000 bytes")
            size = None
        media = row.get("media_type") or ""
        if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", media):
            issues.append(f"{where} media_type 须为明确MIME类型")
        if not _valid_source_url(row.get("source_url") or ""):
            issues.append(f"{where} source_url 必须为公开 http/https 网址")
        if not _real_iso_date(row.get("retrieved") or ""):
            issues.append(f"{where} retrieved 须为真实 YYYY-MM-DD")
        candidates = list((directory / sha[:2]).glob(sha + ".*"))
        if len(candidates) != 1:
            issues.append(f"{where} sha路径应恰好对应一份原件，实际 {len(candidates)} 份")
            continue
        relative = candidates[0].relative_to(root).as_posix()
        actual, error = _archive_file(root, relative, sha)
        if error:
            issues.append(f"{where} {error}")
        if actual:
            indexed_files.add(actual)
            if size is not None and actual.stat().st_size != size:
                issues.append(f"{where} size 与文件实际大小不符")
        matching = [s for s in sources.get(sid, []) if s.get("grade") == "官方"
                    and s.get("archive_status") in STORED_STATUSES
                    and s.get("archive_sha256") == sha and s.get("archive_path") == relative]
        asset = assets.get((sid, sha))
        member_match = asset and asset.get("path") == relative and asset.get("url") == row.get("source_url")
        if not matching and not member_match:
            issues.append(f"{where} source_id 未关联同hash/路径的官方已存原件来源或登记成员")
        elif matching and not member_match and not any(row.get("source_url") in (s.get("landing_url"), s.get("file_url"), s.get("wayback_url")) for s in matching):
            issues.append(f"{where} source_url 与登记的官方来源链接不符")
    for sid, source_rows in sources.items():
        for row in source_rows:
            if row.get("archive_status") not in STORED_STATUSES:
                continue
            sha, relative = row.get("archive_sha256") or "", row.get("archive_path") or ""
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                issues.append(f"来源 {sid} 已存原件缺有效archive_sha256")
                continue
            _, error = _archive_file(root, relative, sha)
            if error:
                issues.append(f"来源 {sid} {error}")
            if (relative.startswith(ORIGINALS_RELATIVE.as_posix() + "/")
                    and (sha, sid) not in seen):
                issues.append(f"来源 {sid} 声称已存原件但缺原件库索引")
    for (sid, sha), asset in assets.items():
        if (sha, sid) not in seen:
            issues.append("原件成员未登记index：" + sid)
    attributes = directory / ".gitattributes"
    if attributes.exists() and attributes.read_bytes() != b"*/* -text -diff -merge\n":
        issues.append("原件Git属性必须禁止文本转换、文本diff和自动merge，不得配置转换filter")
    if directory.exists():
        for candidate in directory.rglob("*"):
            metadata_files = {directory / "index.csv", directory / "README.md", directory / "sources.csv", directory / ".gitattributes", directory / "assets.csv"}
            if candidate.is_file() and candidate not in metadata_files and candidate.resolve() not in indexed_files:
                issues.append("公开原件文件未入index或路径不规范：" + candidate.relative_to(root).as_posix())
    notes.append(f"原件索引 {len(rows)} 条，{len(indexed_files)} 份去重原件")
    return issues, notes


def check_file(path, codes):
    issues, notes = [], []
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        header = rows[0].keys() if rows else []
    if not rows:
        return ["空文件"], notes
    if "code" not in header or "name" not in header or not ({"score", "rank"} & set(header)):
        issues.append(f"表头缺少必要列：{', '.join(header)}")
        return issues, notes
    # 分数超出满分：十省高考总分均为 750；2026-10 发现江苏 xls 数值格转换时丢了小数点（688.0 → 6880）
    over = [(r.get("name"), r.get("score")) for r in rows if (num(r.get("score")) or 0) > MAX_SCORE]
    if over:
        issues.append(f"{len(over)} 行分数超过满分 {MAX_SCORE}，疑似转换时丢了小数点：{over[:3]}")
    # 位次与分数一致性
    pairs = [(num(r.get("score")), num(r.get("rank"))) for r in rows]
    pairs = [(s, k) for s, k in pairs if s and k]
    if len(pairs) > 50:
        rng = random.Random(0)
        bad = tot = 0
        for _ in range(4000):
            (s1, k1), (s2, k2) = rng.sample(pairs, 2)
            if s1 == s2:
                continue
            tot += 1
            if (s1 > s2) != (k1 < k2):
                bad += 1
        rate = bad / tot if tot else 0
        notes.append(f"分数-位次不一致 {rate:.2%}")
        if rate > VIOLATION_WARN:
            issues.append(f"分数与位次不一致的比例 {rate:.1%}（阈值 {VIOLATION_WARN:.0%}）：检查列是否错位、识别是否出错")
    # 重复键
    sub = "group" if any((r.get("group") or "").strip() for r in rows) else ("major" if "major" in header else None)
    keys = [((r.get("code") or "").strip(), (r.get(sub) or "").strip() if sub else "") for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        notes.append(f"重复键 {dup} 条（按 code + {sub or '无'}）")
        if dup / len(keys) > 0.05:
            issues.append(f"重复键占 {dup / len(keys):.1%}：同校同名专业（如不同校区）会在回测中被剔除，比例过高需检查")
    # 同一代码多个校名（去掉括号里的校区、办学类型等注释后比较）
    names = {}
    for r in rows:
        base = re.sub(r"[（(\[].*$", "", (r.get("name") or "").strip()).strip()
        names.setdefault((r.get("code") or "").strip(), set()).add(base)
    multi = {c: n for c, n in names.items() if c and len(n) > 1}
    if multi:
        eg = "；".join(f"{c}: {'/'.join(sorted(n))}" for c, n in list(multi.items())[:3])
        notes.append(f"同代码多校名 {len(multi)} 个")
        if multi:
            issues.append(f"{len(multi)} 个院校代码对应多个校名（如 {eg}）：检查水印字或识别错误")
    # 院校代码匹配
    c5 = [k[0] for k in keys if re.fullmatch(r"\d{5}", k[0])]
    if len(c5) > 0.8 * len(keys):
        rate = sum(c in codes for c in c5) / len(c5)
        notes.append(f"代码值在教育部名单出现 {rate:.1%}（数值重合不证明学校身份）")
        if rate < 0.9:
            issues.append(f"院校代码与教育部名单匹配率只有 {rate:.1%}")
    return issues, notes


def check_local_query_entry(repository_root=None):
    """本机可选入口只检查文件存在性，不执行配置指定的程序。"""
    root = Path(repository_root) if repository_root is not None else REPO_ROOT
    config = root / "skills/zhiqu-shared/data/query_entry.json"
    if not config.exists() and not config.is_symlink():
        return [], ["未配置本机查询入口，跳过"]
    try:
        value = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return ["query_entry.json 无法读取或不是有效 JSON"], []
    if not isinstance(value, dict):
        return ["query_entry.json 必须是 JSON 对象"], []
    entry = value.get("entry_path")
    if not isinstance(entry, str) or not entry.strip():
        return ["query_entry.json 的 entry_path 必须是非空文件路径"], []
    target = Path(entry)
    if not target.is_absolute():
        target = root / target
    try:
        exists = target.is_file()
    except (OSError, ValueError):
        exists = False
    if not exists:
        return ["query_entry.json 的 entry_path 未指向现存文件，请修复本机查询入口"], []
    return [], ["本机查询入口文件存在（未执行）"]


def main():
    parser = argparse.ArgumentParser(description="校验投档 CSV、入学后的机会表和选调高校范围表")
    parser.add_argument("provinces", nargs="*", help="data 下的省份目录；默认全部省份")
    args = parser.parse_args()
    with open(os.path.join(DATA, "schools.csv"), encoding="utf-8") as f:
        codes = {r["code"] for r in csv.DictReader(f)}
    provs = args.provinces or sorted(d for d in os.listdir(DATA) if os.path.isdir(os.path.join(DATA, d)) and d not in SKIP_DIRS)
    for province in provs:
        if province not in os.listdir(DATA) or not os.path.isdir(os.path.join(DATA, province)):
            parser.error(f"未知省份目录：{province}")
    n_issue = 0
    issues, notes = check_local_query_entry()
    print(f"## 本机查询入口：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    issues, notes = check_originals_index()
    print(f"## 公开原件库：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    issues, notes = check_after_entry_file(os.path.join(DATA, "after-entry-opportunities.csv"))
    print(f"## after-entry-opportunities.csv：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    issues, notes = check_selected_universities_file(os.path.join(CAREER_DATA, "selected-universities-2027.csv"))
    print(f"## selected-universities-2027.csv：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    issues, notes = check_competition_file(os.path.join(CAREER_DATA, "civil-service-competition-2026.csv"))
    print(f"## civil-service-competition-2026.csv：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    issues, notes = check_sources(DATA, [fn for fn in ROOT_SOURCED if os.path.isfile(os.path.join(DATA, fn))])
    print(f"## data/sources.csv：{'；'.join(notes) or '—'}")
    for issue in issues:
        print(f"    ⚠ {issue}")
        n_issue += 1
    for p in provs:
        every = sorted(fn for fn in os.listdir(os.path.join(DATA, p)) if fn.endswith(".csv") and fn != "sources.csv")
        files = [fn for fn in every if not fn.startswith(("yfyd", "early"))]
        series = {}
        for fn in files:
            m = re.match(r"(.+)_(\d{4})\.csv$", fn)
            if m:
                series.setdefault(m.group(1), []).append(int(m.group(2)))
        print(f"## {p}")
        for name, ys in series.items():
            gaps = [y for y in range(min(ys), max(ys) + 1) if y not in ys]
            print(f"- {name}：{min(ys)}–{max(ys)}" + (f"，缺 {gaps}" if gaps else ""))
        issues, notes = check_sources(os.path.join(DATA, p), every)
        print(f"  sources.csv：{'；'.join(notes) or '—'}")
        for i in issues:
            print(f"    ⚠ {i}")
            n_issue += 1
        for fn in files:
            issues, notes = check_file(os.path.join(DATA, p, fn), codes)
            print(f"  {fn}：{'；'.join(notes) or '—'}")
            for i in issues:
                print(f"    ⚠ {i}")
                n_issue += 1
    print(f"\n共 {n_issue} 个需要处理的问题")
    sys.exit(1 if n_issue else 0)


if __name__ == "__main__":
    main()
