from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPORT_NAME = "symbol_breath_profile_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/symbol_breath_profile_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

CURVE_SUMMARY_CSV = "summary_symbol_curve_regime_v1.csv"
CONFIDENCE_SUMMARY_CSV = "summary_symbol_confidence_regime_v1.csv"
INCLUDED_SUMMARY_CSV = "summary_symbol_included_regime_v1.csv"

PROFILE_CSV = "symbol_breath_profile_v1.csv"
PROFILE_JSONL = "symbol_breath_profile_v1.jsonl"
PROFILE_EVIDENCE_CSV = "profile_evidence_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

PROFILE_FIELDS = [
    "destination_symbol",
    "symbol_breath_profile_label",
    "profile_event_count",
    "measurement_coverage_score_avg",
    "avg_destination_return_24h_pct",
    "avg_destination_return_48h_pct",
    "dominant_curve_state",
    "dominant_confidence_bucket",
    "dominant_included_state",
    "regime_count",
    "profile_reason",
]

EVIDENCE_FIELDS = [
    "destination_symbol",
    "evidence_type",
    "evidence_key",
    "event_count",
    "avg_measurement_coverage_score",
    "avg_destination_return_24h_pct",
    "avg_destination_return_48h_pct",
    "positive_rate_destination_return_24h_pct",
    "avg_destination_forward_max_24h_pct",
    "avg_destination_forward_min_24h_pct",
]

SAFETY_MARKERS = {
    "db_reads": 0,
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
}


class OutputPaths:
    def __init__(self, output_dir: Path) -> None:
        self.profile_csv = output_dir / PROFILE_CSV
        self.profile_jsonl = output_dir / PROFILE_JSONL
        self.profile_evidence_csv = output_dir / PROFILE_EVIDENCE_CSV
        self.manifest_json = output_dir / MANIFEST_JSON


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify symbol breath profiles from local regime-interaction summary CSVs "
            "(research-only, file-input-only, no DB required)."
        )
    )
    parser.add_argument("--interaction-run-dir", required=True)
    parser.add_argument("--min-events", type=int, default=10)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.replace(tzinfo=UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_output_dir(*, output_root: str | None, run_id: str) -> Path:
    root = Path(output_root) if output_root else Path(DEFAULT_OUTPUT_ROOT)
    return root / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def format_number(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except Exception:
        return None


def as_int(value: Any) -> int:
    try:
        return int(str(value))
    except Exception:
        return 0


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def summarize_weighted(rows: list[dict[str, str]], field: str) -> float | None:
    total_weight = 0
    total_value = 0.0
    for row in rows:
        weight = as_int(row.get("event_count"))
        value = as_float(row.get(field))
        if weight <= 0 or value is None:
            continue
        total_weight += weight
        total_value += value * weight
    if total_weight <= 0:
        return None
    return total_value / total_weight


def dominant_key(rows: list[dict[str, str]], field: str) -> str:
    best_key = ""
    best_weight = -1
    best_return = float("-inf")
    for row in rows:
        key = str(row.get(field) or "")
        weight = as_int(row.get("event_count"))
        ret = as_float(row.get("avg_destination_return_24h_pct"))
        ret_value = ret if ret is not None else float("-inf")
        if weight > best_weight or (weight == best_weight and ret_value > best_return) or (
            weight == best_weight and ret_value == best_return and key < best_key
        ):
            best_key = key
            best_weight = weight
            best_return = ret_value
    return best_key


def classify_profile(
    *,
    total_events: int,
    curve_rows: list[dict[str, str]],
    confidence_rows: list[dict[str, str]],
    included_rows: list[dict[str, str]],
) -> tuple[str, str]:
    if total_events <= 0:
        return "INSUFFICIENT_SAMPLE", "NO_EVENTS"

    avg_return_24h = summarize_weighted(curve_rows, "avg_destination_return_24h_pct")
    avg_return_48h = summarize_weighted(curve_rows, "avg_destination_return_48h_pct")
    included_return = summarize_weighted(
        [row for row in included_rows if str(row.get("included_state") or "") == "INCLUDED"],
        "avg_destination_return_24h_pct",
    )
    excluded_return = summarize_weighted(
        [row for row in included_rows if str(row.get("included_state") or "") == "EXCLUDED"],
        "avg_destination_return_24h_pct",
    )

    dominant_curve = dominant_key(curve_rows, "curve_sanity_state")
    dominant_confidence = dominant_key(confidence_rows, "confidence_bucket")
    regime_ids = {
        str(row.get("discovered_regime_id") or "")
        for row in curve_rows + confidence_rows + included_rows
        if str(row.get("discovered_regime_id") or "")
    }

    if total_events < 10:
        return "INSUFFICIENT_SAMPLE", "EVENT_COUNT_BELOW_MIN_EVENTS"

    if len(regime_ids) >= 3 and included_return is not None and excluded_return is not None:
        if abs(included_return - excluded_return) >= 1.0:
            return "REGIME_SENSITIVE", "INCLUDED_EXCLUDED_SPLIT_ACROSS_MULTIPLE_REGIMES"

    if dominant_curve == "CURVE_DOWN_PRESSURE" and avg_return_24h is not None and avg_return_24h > 0.75:
        return "DAMAGE_REBOUND_RESPONDER", "POSITIVE_RESPONSE_DURING_CURVE_DOWN_PRESSURE"

    if dominant_curve == "CURVE_WEAK" and avg_return_24h is not None and avg_return_24h > 0.75:
        return "REBOUND_RESPONDER", "POSITIVE_RESPONSE_DURING_CURVE_WEAK"

    if dominant_curve == "CURVE_UP_CONFIRMED" and dominant_confidence in {
        "HIGH_CONFIDENCE_DESTINATION",
        "MEDIUM_CONFIDENCE_DESTINATION",
    }:
        if avg_return_24h is not None and avg_return_24h > 0.75 and avg_return_48h is not None and avg_return_48h > 1.0:
            return "CONFIRMED_CONTINUATION", "UP_CONFIRMED_WITH_POSITIVE_24H_AND_48H"

    if dominant_confidence == "HIGH_CONFIDENCE_DESTINATION" and avg_return_24h is not None and avg_return_24h < 0.25:
        return "LATE_EXPANSION_TRAP", "HIGH_CONFIDENCE_LABEL_WITH_WEAK_24H_OUTCOME"

    if len(regime_ids) >= 3:
        positive_rows = sum(
            1 for row in curve_rows if (as_float(row.get("avg_destination_return_24h_pct")) or 0.0) > 0.5
        )
        negative_rows = sum(
            1 for row in curve_rows if (as_float(row.get("avg_destination_return_24h_pct")) or 0.0) < -0.25
        )
        if positive_rows and negative_rows:
            return "REGIME_SENSITIVE", "MIXED_CURVE_OUTCOMES_ACROSS_MULTIPLE_REGIMES"

    return "INCOHERENT", "NO_CLEAR_REPEATABLE_PROFILE_PATTERN"


def build_manifest(
    *,
    run_id: str,
    output_dir: Path,
    interaction_run_dir: Path,
    min_events: int,
    profile_count: int,
    run_started_at: datetime,
    run_finished_at: datetime,
    output_paths: OutputPaths,
    wrote_files: bool,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "interaction_run_dir": str(interaction_run_dir),
        "min_events": int(min_events),
        "profile_count": int(profile_count),
        "run_started_at_utc": run_started_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "run_finished_at_utc": run_finished_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "run_duration_sec": round((run_finished_at - run_started_at).total_seconds(), 6),
        "confidence_terminology_notes": [
            "confidence_bucket is legacy naming retained for backward compatibility.",
            "measurement_coverage_score is coverage or measurement availability only.",
            "measurement_coverage_score is not trend confidence.",
            "measurement_coverage_score is not phase stability.",
        ],
        "notes": [
            "Profiles are descriptive research labels built from local interaction summary files only.",
            "No trade advice, live logic tuning, or runtime promotion is implied.",
            "Breath means rhythm, phase, or waveform context in this lane.",
        ],
        "wrote_files": bool(wrote_files),
        "output_paths": {
            "profile_csv": str(output_paths.profile_csv),
            "profile_jsonl": str(output_paths.profile_jsonl),
            "profile_evidence_csv": str(output_paths.profile_evidence_csv),
            "manifest_json": str(output_paths.manifest_json),
        },
        **SAFETY_MARKERS,
    }


def render_table(manifest: dict[str, Any]) -> str:
    lines = [
        f"[RUN][ID] {manifest['run_id']}",
        f"[RUN][OUT_DIR] {manifest['output_dir']}",
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only file-input-only no-db",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "db_reads=0 db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        f"interaction_run_dir={manifest['interaction_run_dir']}",
        f"min_events={manifest['min_events']} profile_count={manifest['profile_count']}",
        f"wrote_files={manifest['wrote_files']}",
    ]
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
            lines.append(f"  wrote_file[{key}]={value}")
    lines.append("[DONE] db_reads=0 db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.min_events <= 0:
        raise ValueError("--min-events must be > 0")

    interaction_run_dir = Path(args.interaction_run_dir)
    curve_csv = interaction_run_dir / CURVE_SUMMARY_CSV
    confidence_csv = interaction_run_dir / CONFIDENCE_SUMMARY_CSV
    included_csv = interaction_run_dir / INCLUDED_SUMMARY_CSV
    for path in [curve_csv, confidence_csv, included_csv]:
        if not path.exists():
            raise FileNotFoundError(f"Missing interaction input CSV: {path}")

    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    output_paths = OutputPaths(output_dir)

    curve_rows = read_csv_rows(curve_csv)
    confidence_rows = read_csv_rows(confidence_csv)
    included_rows = read_csv_rows(included_csv)

    curve_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    confidence_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    included_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in curve_rows:
        curve_by_symbol[str(row.get("destination_symbol") or "")].append(row)
    for row in confidence_rows:
        confidence_by_symbol[str(row.get("destination_symbol") or "")].append(row)
    for row in included_rows:
        included_by_symbol[str(row.get("destination_symbol") or "")].append(row)

    symbols = sorted(
        {
            *curve_by_symbol.keys(),
            *confidence_by_symbol.keys(),
            *included_by_symbol.keys(),
        }
    )

    profile_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        symbol_curve_rows = curve_by_symbol.get(symbol, [])
        symbol_confidence_rows = confidence_by_symbol.get(symbol, [])
        symbol_included_rows = included_by_symbol.get(symbol, [])
        total_events = max(
            sum(as_int(row.get("event_count")) for row in symbol_curve_rows),
            sum(as_int(row.get("event_count")) for row in symbol_confidence_rows),
            sum(as_int(row.get("event_count")) for row in symbol_included_rows),
        )

        label, reason = classify_profile(
            total_events=total_events,
            curve_rows=symbol_curve_rows,
            confidence_rows=symbol_confidence_rows,
            included_rows=symbol_included_rows,
        )
        if total_events < args.min_events:
            label = "INSUFFICIENT_SAMPLE"
            reason = "EVENT_COUNT_BELOW_MIN_EVENTS"

        profile_rows.append(
            {
                "destination_symbol": symbol,
                "symbol_breath_profile_label": label,
                "profile_event_count": total_events,
                "measurement_coverage_score_avg": format_number(
                    summarize_weighted(symbol_curve_rows, "avg_measurement_coverage_score")
                ),
                "avg_destination_return_24h_pct": format_number(
                    summarize_weighted(symbol_curve_rows, "avg_destination_return_24h_pct")
                ),
                "avg_destination_return_48h_pct": format_number(
                    summarize_weighted(symbol_curve_rows, "avg_destination_return_48h_pct")
                ),
                "dominant_curve_state": dominant_key(symbol_curve_rows, "curve_sanity_state"),
                "dominant_confidence_bucket": dominant_key(symbol_confidence_rows, "confidence_bucket"),
                "dominant_included_state": dominant_key(symbol_included_rows, "included_state"),
                "regime_count": len(
                    {
                        str(row.get("discovered_regime_id") or "")
                        for row in symbol_curve_rows + symbol_confidence_rows + symbol_included_rows
                        if str(row.get("discovered_regime_id") or "")
                    }
                ),
                "profile_reason": reason,
            }
        )

        for row in symbol_curve_rows:
            evidence_rows.append(
                {
                    "destination_symbol": symbol,
                    "evidence_type": "CURVE_REGIME",
                    "evidence_key": f"{row.get('curve_sanity_state','')}|{row.get('discovered_regime_label_auto','')}",
                    "event_count": row.get("event_count", ""),
                    "avg_measurement_coverage_score": row.get("avg_measurement_coverage_score", ""),
                    "avg_destination_return_24h_pct": row.get("avg_destination_return_24h_pct", ""),
                    "avg_destination_return_48h_pct": row.get("avg_destination_return_48h_pct", ""),
                    "positive_rate_destination_return_24h_pct": row.get("positive_rate_destination_return_24h_pct", ""),
                    "avg_destination_forward_max_24h_pct": row.get("avg_destination_forward_max_24h_pct", ""),
                    "avg_destination_forward_min_24h_pct": row.get("avg_destination_forward_min_24h_pct", ""),
                }
            )
        for row in symbol_confidence_rows:
            evidence_rows.append(
                {
                    "destination_symbol": symbol,
                    "evidence_type": "CONFIDENCE_REGIME",
                    "evidence_key": f"{row.get('confidence_bucket','')}|{row.get('discovered_regime_label_auto','')}",
                    "event_count": row.get("event_count", ""),
                    "avg_measurement_coverage_score": row.get("avg_measurement_coverage_score", ""),
                    "avg_destination_return_24h_pct": row.get("avg_destination_return_24h_pct", ""),
                    "avg_destination_return_48h_pct": row.get("avg_destination_return_48h_pct", ""),
                    "positive_rate_destination_return_24h_pct": row.get("positive_rate_destination_return_24h_pct", ""),
                    "avg_destination_forward_max_24h_pct": row.get("avg_destination_forward_max_24h_pct", ""),
                    "avg_destination_forward_min_24h_pct": row.get("avg_destination_forward_min_24h_pct", ""),
                }
            )
        for row in symbol_included_rows:
            evidence_rows.append(
                {
                    "destination_symbol": symbol,
                    "evidence_type": "INCLUDED_REGIME",
                    "evidence_key": f"{row.get('included_state','')}|{row.get('discovered_regime_label_auto','')}",
                    "event_count": row.get("event_count", ""),
                    "avg_measurement_coverage_score": row.get("avg_measurement_coverage_score", ""),
                    "avg_destination_return_24h_pct": row.get("avg_destination_return_24h_pct", ""),
                    "avg_destination_return_48h_pct": row.get("avg_destination_return_48h_pct", ""),
                    "positive_rate_destination_return_24h_pct": row.get("positive_rate_destination_return_24h_pct", ""),
                    "avg_destination_forward_max_24h_pct": row.get("avg_destination_forward_max_24h_pct", ""),
                    "avg_destination_forward_min_24h_pct": row.get("avg_destination_forward_min_24h_pct", ""),
                }
            )

    run_finished_at = datetime.now(UTC)
    manifest = build_manifest(
        run_id=run_id,
        output_dir=output_dir,
        interaction_run_dir=interaction_run_dir,
        min_events=args.min_events,
        profile_count=len(profile_rows),
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        output_paths=output_paths,
        wrote_files=args.write_files,
    )

    if args.write_files:
        write_csv(output_paths.profile_csv, profile_rows, PROFILE_FIELDS)
        write_jsonl(output_paths.profile_jsonl, profile_rows)
        write_csv(output_paths.profile_evidence_csv, evidence_rows, EVIDENCE_FIELDS)
        write_json(output_paths.manifest_json, manifest)

    if args.output == "json":
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
