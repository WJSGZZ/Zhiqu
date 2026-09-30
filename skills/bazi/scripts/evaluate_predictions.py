#!/usr/bin/env python3
"""Freeze, verify, and score preregistered Bazi predictions using only stdlib."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PREDICTION_SCHEMA = "bazi-prediction-v1"
OUTCOME_SCHEMA = "bazi-outcome-v1"
ADJUDICATIONS = {"hit", "fail", "ambiguous", "unjudgeable"}


class ValidationError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValidationError(f"{path}:{line_number}: each line must be a JSON object")
            records.append(value)
    if not records:
        raise ValidationError(f"{path}: no records")
    return records


def require(record: dict[str, Any], names: Iterable[str], label: str) -> None:
    missing = [name for name in names if name not in record]
    if missing:
        raise ValidationError(f"{label}: missing fields: {', '.join(missing)}")


def finite_number(value: Any, label: str, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{label}: expected a finite number")
    number = float(value)
    if low is not None and number < low:
        raise ValidationError(f"{label}: must be >= {low}")
    if high is not None and number > high:
        raise ValidationError(f"{label}: must be <= {high}")
    return number


def parse_datetime(value: Any, label: str, date_only: bool = False) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{label}: expected ISO 8601 string")
    try:
        if date_only:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{label}: invalid ISO 8601 value") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{label}: timezone is required")
    return parsed


def validate_prediction(record: dict[str, Any], index: int) -> None:
    label = f"prediction[{index}]"
    require(record, ["schema_version", "prediction_id", "protocol_id", "case_id", "created_at",
                     "information_cutoff", "model_id", "rule_ids", "event_category", "direction",
                     "window", "probability", "conditions", "specificity", "complexity", "input_digest"], label)
    if record["schema_version"] != PREDICTION_SCHEMA:
        raise ValidationError(f"{label}: schema_version must be {PREDICTION_SCHEMA}")
    for name in ("prediction_id", "protocol_id", "case_id", "model_id", "event_category", "direction", "input_digest"):
        if not isinstance(record[name], str) or not record[name].strip():
            raise ValidationError(f"{label}.{name}: expected non-empty string")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", record["input_digest"]):
        raise ValidationError(f"{label}.input_digest: expected sha256 followed by 64 lowercase hex characters")
    parse_datetime(record["created_at"], f"{label}.created_at")
    cutoff = parse_datetime(record["information_cutoff"], f"{label}.information_cutoff")
    created = parse_datetime(record["created_at"], f"{label}.created_at")
    if cutoff > created:
        raise ValidationError(f"{label}: information_cutoff cannot be after created_at")
    if not isinstance(record["rule_ids"], list) or not record["rule_ids"] or not all(isinstance(x, str) and x for x in record["rule_ids"]):
        raise ValidationError(f"{label}.rule_ids: expected non-empty string array")
    if not isinstance(record["conditions"], list) or not all(isinstance(x, str) and x for x in record["conditions"]):
        raise ValidationError(f"{label}.conditions: expected string array")
    finite_number(record["probability"], f"{label}.probability", 0, 1)
    window = record["window"]
    if not isinstance(window, dict):
        raise ValidationError(f"{label}.window: expected object")
    require(window, ["start", "end"], f"{label}.window")
    start = parse_datetime(window["start"], f"{label}.window.start", date_only=True)
    end = parse_datetime(window["end"], f"{label}.window.end", date_only=True)
    if end < start:
        raise ValidationError(f"{label}.window: end precedes start")
    specificity = record["specificity"]
    if not isinstance(specificity, dict):
        raise ValidationError(f"{label}.specificity: expected object")
    require(specificity, ["temporal", "categorical", "directional"], f"{label}.specificity")
    for name in ("temporal", "categorical", "directional"):
        finite_number(specificity[name], f"{label}.specificity.{name}", 0, 1)
    complexity = record["complexity"]
    if not isinstance(complexity, dict):
        raise ValidationError(f"{label}.complexity: expected object")
    require(complexity, ["rule_count", "condition_count", "exception_count", "free_parameter_count"], f"{label}.complexity")
    for name in ("rule_count", "condition_count", "exception_count", "free_parameter_count"):
        value = finite_number(complexity[name], f"{label}.complexity.{name}", 0)
        if not value.is_integer():
            raise ValidationError(f"{label}.complexity.{name}: expected integer")
    if complexity["rule_count"] != len(record["rule_ids"]):
        raise ValidationError(f"{label}.complexity.rule_count: must equal len(rule_ids)")
    if complexity["condition_count"] != len(record["conditions"]):
        raise ValidationError(f"{label}.complexity.condition_count: must equal len(conditions)")


def validate_predictions(records: list[dict[str, Any]]) -> None:
    for index, record in enumerate(records, 1):
        validate_prediction(record, index)
    ids = [record["prediction_id"] for record in records]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValidationError(f"duplicate prediction_id: {', '.join(duplicates)}")


def validate_outcome(record: dict[str, Any], index: int) -> None:
    label = f"outcome[{index}]"
    require(record, ["schema_version", "prediction_id", "adjudication", "adjudicated_at",
                     "evidence_refs", "rationale", "adjudicator", "protocol_deviation"], label)
    if record["schema_version"] != OUTCOME_SCHEMA:
        raise ValidationError(f"{label}: schema_version must be {OUTCOME_SCHEMA}")
    if not isinstance(record["prediction_id"], str) or not record["prediction_id"]:
        raise ValidationError(f"{label}.prediction_id: expected non-empty string")
    adjudication = record["adjudication"]
    if adjudication not in ADJUDICATIONS:
        raise ValidationError(f"{label}.adjudication: expected one of {sorted(ADJUDICATIONS)}")
    parse_datetime(record["adjudicated_at"], f"{label}.adjudicated_at")
    if not isinstance(record["evidence_refs"], list) or not all(isinstance(x, str) and x for x in record["evidence_refs"]):
        raise ValidationError(f"{label}.evidence_refs: expected string array")
    for name in ("rationale", "adjudicator"):
        if not isinstance(record[name], str) or not record[name].strip():
            raise ValidationError(f"{label}.{name}: expected non-empty string")
    if not isinstance(record["protocol_deviation"], bool):
        raise ValidationError(f"{label}.protocol_deviation: expected boolean")
    if adjudication == "hit" and record.get("observed") != 1:
        raise ValidationError(f"{label}: hit requires observed=1")
    if adjudication == "fail" and record.get("observed") != 0:
        raise ValidationError(f"{label}: fail requires observed=0")
    if adjudication in {"ambiguous", "unjudgeable"} and "observed" in record:
        raise ValidationError(f"{label}: {adjudication} must omit observed")


def validate_outcomes(records: list[dict[str, Any]]) -> None:
    for index, record in enumerate(records, 1):
        validate_outcome(record, index)
    ids = [record["prediction_id"] for record in records]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValidationError(f"duplicate outcome prediction_id: {', '.join(duplicates)}")


def canonical_bytes(records: list[dict[str, Any]]) -> bytes:
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for record in records]
    return ("\n".join(lines) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_path(frozen_path: Path) -> Path:
    return Path(str(frozen_path) + ".manifest.json")


def atomic_create(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def freeze(input_path: Path, output_path: Path) -> dict[str, Any]:
    records = load_jsonl(input_path)
    validate_predictions(records)
    data = canonical_bytes(records)
    manifest = {
        "manifest_version": "bazi-freeze-manifest-v1",
        "frozen_file": output_path.name,
        "sha256": sha256(data),
        "bytes": len(data),
        "record_count": len(records),
        "protocol_ids": sorted({record["protocol_id"] for record in records}),
        "frozen_at": utc_now(),
    }
    sidecar = manifest_path(output_path)
    if output_path.exists() or sidecar.exists():
        raise ValidationError("refusing to overwrite frozen output or manifest")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_create(output_path, data)
    try:
        atomic_create(sidecar, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    output_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    sidecar.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return manifest


def verify(frozen_path: Path) -> dict[str, Any]:
    sidecar = manifest_path(frozen_path)
    if not sidecar.exists():
        raise ValidationError(f"missing manifest: {sidecar}")
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    data = frozen_path.read_bytes()
    records = load_jsonl(frozen_path)
    validate_predictions(records)
    checks = {
        "frozen_file": frozen_path.name == manifest.get("frozen_file"),
        "sha256": sha256(data) == manifest.get("sha256"),
        "bytes": len(data) == manifest.get("bytes"),
        "record_count": len(records) == manifest.get("record_count"),
        "protocol_ids": sorted({record["protocol_id"] for record in records}) == manifest.get("protocol_ids"),
        "canonical_encoding": data == canonical_bytes(records),
    }
    if not all(checks.values()):
        raise ValidationError(f"frozen file verification failed: {checks}")
    return {"verified": True, "file": str(frozen_path), "checks": checks, "sha256": manifest["sha256"]}


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def specificity(record: dict[str, Any]) -> float:
    item = record["specificity"]
    return (float(item["temporal"]) + float(item["categorical"]) + float(item["directional"])) / 3


def complexity_points(record: dict[str, Any]) -> float:
    item = record["complexity"]
    return (float(item["rule_count"]) + 0.5 * float(item["condition_count"]) +
            2 * float(item["exception_count"]) + float(item["free_parameter_count"]))


def calibration(rows: list[tuple[float, int]], bins: int) -> tuple[list[dict[str, Any]], float | None]:
    buckets: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for probability, observed in rows:
        index = min(int(probability * bins), bins - 1)
        buckets[index].append((probability, observed))
    table: list[dict[str, Any]] = []
    weighted_error = 0.0
    for index in range(bins):
        values = buckets.get(index, [])
        if not values:
            continue
        predicted_mean = sum(item[0] for item in values) / len(values)
        observed_rate = sum(item[1] for item in values) / len(values)
        weighted_error += len(values) * abs(predicted_mean - observed_rate)
        table.append({
            "lower_inclusive": index / bins,
            "upper_inclusive" if index == bins - 1 else "upper_exclusive": (index + 1) / bins,
            "count": len(values),
            "predicted_mean": predicted_mean,
            "observed_rate": observed_rate,
        })
    return table, weighted_error / len(rows) if rows else None


def score(frozen_path: Path, outcomes_path: Path, bins: int) -> dict[str, Any]:
    verification = verify(frozen_path)
    predictions = load_jsonl(frozen_path)
    outcomes = load_jsonl(outcomes_path)
    validate_outcomes(outcomes)
    prediction_by_id = {record["prediction_id"]: record for record in predictions}
    outcome_by_id = {record["prediction_id"]: record for record in outcomes}
    unknown = sorted(set(outcome_by_id) - set(prediction_by_id))
    missing = sorted(set(prediction_by_id) - set(outcome_by_id))
    if unknown:
        raise ValidationError(f"outcomes reference unknown prediction_id: {', '.join(unknown)}")
    if missing:
        raise ValidationError(f"missing outcomes for prediction_id: {', '.join(missing)}")

    counts = Counter(record["adjudication"] for record in outcomes)
    deviations = [record for record in outcomes if record["protocol_deviation"]]
    primary: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for prediction_id, prediction in prediction_by_id.items():
        outcome = outcome_by_id[prediction_id]
        if not outcome["protocol_deviation"] and outcome["adjudication"] in {"hit", "fail"}:
            primary.append((prediction, outcome))
    calibration_rows = [(float(prediction["probability"]), int(outcome["observed"])) for prediction, outcome in primary]
    brier_values = [(probability - observed) ** 2 for probability, observed in calibration_rows]
    calibration_table, ece = calibration(calibration_rows, bins)
    paired_count = len(predictions)
    strict_denominator = counts["hit"] + counts["fail"]
    report = {
        "report_version": "bazi-evaluation-report-v1",
        "generated_at": utc_now(),
        "frozen_sha256": verification["sha256"],
        "prediction_count": len(predictions),
        "case_count": len({record["case_id"] for record in predictions}),
        "adjudication_counts": {name: counts[name] for name in sorted(ADJUDICATIONS)},
        "adjudication_rates": {name: counts[name] / paired_count for name in sorted(ADJUDICATIONS)},
        "strict_accuracy_unadjusted_including_deviations": counts["hit"] / strict_denominator if strict_denominator else None,
        "coverage_unadjusted_including_deviations": strict_denominator / paired_count,
        "primary_judgeable_count_excluding_deviations": len(primary),
        "brier_score": mean(brier_values),
        "expected_calibration_error": ece,
        "calibration_bins": calibration_table,
        "specificity_mean_all": mean([specificity(record) for record in predictions]),
        "specificity_mean_primary": mean([specificity(prediction) for prediction, _ in primary]),
        "complexity_points_mean_all": mean([complexity_points(record) for record in predictions]),
        "complexity_formula": "rule_count + 0.5*condition_count + 2*exception_count + free_parameter_count",
        "protocol_deviation_count": len(deviations),
        "protocol_deviation_prediction_ids": sorted(record["prediction_id"] for record in deviations),
        "notes": [
            "Brier and calibration exclude ambiguous, unjudgeable, and protocol-deviation outcomes.",
            "Accuracy and coverage labeled unadjusted include protocol deviations; use counts plus primary metrics transparently.",
            "Correlated predictions within a case are not independent; case_id is the clustering unit.",
        ],
    }
    primary_hits = sum(outcome["adjudication"] == "hit" for _, outcome in primary)
    report["strict_accuracy_primary"] = primary_hits / len(primary) if primary else None
    report["coverage_primary"] = len(primary) / paired_count
    return report


def emit(value: dict[str, Any], output: Path | None = None) -> None:
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(data)
        return
    if output.exists():
        raise ValidationError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_create(output, data.encode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze", help="validate and freeze prediction JSONL")
    freeze_parser.add_argument("input", type=Path)
    freeze_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify", help="verify a frozen prediction file")
    verify_parser.add_argument("frozen", type=Path)
    score_parser = subparsers.add_parser("score", help="score frozen predictions against outcomes")
    score_parser.add_argument("frozen", type=Path)
    score_parser.add_argument("outcomes", type=Path)
    score_parser.add_argument("--bins", type=int, default=10)
    score_parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "freeze":
            emit(freeze(args.input, args.output))
        elif args.command == "verify":
            emit(verify(args.frozen))
        elif args.command == "score":
            if args.bins < 2 or args.bins > 100:
                raise ValidationError("--bins must be between 2 and 100")
            emit(score(args.frozen, args.outcomes, args.bins), args.output)
        return 0
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
