from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "rotation_destination_regime_interaction_audit_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/rotation_destination_regime_interaction_audit_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

ROTATION_FILE_NAME = "event_table_dedup_destination_historical_replay_v2.csv"
REGIME_FILE_NAME = "discovered_regime_samples_v1.csv"

SUMMARY_SYMBOL_CURVE_REGIME_CSV = "summary_symbol_curve_regime_v1.csv"
SUMMARY_SYMBOL_CONFIDENCE_REGIME_CSV = "summary_symbol_confidence_regime_v1.csv"
SUMMARY_CURVE_REGIME_CSV = "summary_curve_regime_v1.csv"
SUMMARY_CONFIDENCE_REGIME_CSV = "summary_confidence_regime_v1.csv"
SUMMARY_INCLUDED_REGIME_CSV = "summary_included_regime_v1.csv"
SUMMARY_SYMBOL_INCLUDED_REGIME_CSV = "summary_symbol_included_regime_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

SAFETY_MARKERS = {
    "db_reads": 0,
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
}

SUMMARY_FIELDS = [
    "discovered_regime_id",
    "discovered_regime_label_auto",
    "event_count",
    "included_count",
    "excluded_count",
    "avg_measurement_coverage_score",
    "avg_destination_return_24h_pct",
    "median_destination_return_24h_pct",
    "positive_rate_destination_return_24h_pct",
    "avg_destination_return_48h_pct",
    "avg_destination_forward_max_24h_pct",
    "avg_destination_forward_min_24h_pct",
]


class OutputPaths:
    def __init__(self, output_dir: Path) -> None:
        self.summary_symbol_curve_regime_csv = output_dir / SUMMARY_SYMBOL_CURVE_REGIME_CSV
        self.summary_symbol_confidence_regime_csv = output_dir / SUMMARY_SYMBOL_CONFIDENCE_REGIME_CSV
        self.summary_curve_regime_csv = output_dir / SUMMARY_CURVE_REGIME_CSV
        self.summary_confidence_regime_csv = output_dir / SUMMARY_CONFIDENCE_REGIME_CSV
        self.summary_included_regime_csv = output_dir / SUMMARY_INCLUDED_REGIME_CSV
        self.summary_symbol_included_regime_csv = output_dir / SUMMARY_SYMBOL_INCLUDED_REGIME_CSV
        self.manifest_json = output_dir / MANIFEST_JSON


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Join rotation destination replay dedup events with discovered regimes by sample_ts_utc "
            "(research-only, file-input-only, no DB required)."
        )
    )
    parser.add_argument("--rotation-run-dir", required=True)
    parser.add_argument("--regime-run-dir", required=True)
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


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def numeric_values(rows: list[dict[str, str]], field: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = as_float(row.get(field))
        if value is not None:
            out.append(value)
    return out


def mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def positive_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value > 0.0) / len(values) * 100.0


def included_state(row: dict[str, str]) -> str:
    return "EXCLUDED" if str(row.get("excluded_reason") or "") else "INCLUDED"


def summary_rows(
    rows: list[dict[str, str]],
    *,
    group_fields: list[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in group_fields)
        grouped[key].append(row)

    out: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group_rows = grouped[key]
        returns_24h = numeric_values(group_rows, "destination_return_24h_pct")
        out_row: dict[str, Any] = {field: key[idx] for idx, field in enumerate(group_fields)}
        out_row.update(
            {
                "event_count": len(group_rows),
                "included_count": sum(1 for row in group_rows if included_state(row) == "INCLUDED"),
                "excluded_count": sum(1 for row in group_rows if included_state(row) == "EXCLUDED"),
                "avg_measurement_coverage_score": format_number(
                    mean_or_none(numeric_values(group_rows, "measurement_coverage_score"))
                ),
                "avg_destination_return_24h_pct": format_number(mean_or_none(returns_24h)),
                "median_destination_return_24h_pct": format_number(median_or_none(returns_24h)),
                "positive_rate_destination_return_24h_pct": format_number(positive_rate(returns_24h)),
                "avg_destination_return_48h_pct": format_number(
                    mean_or_none(numeric_values(group_rows, "destination_return_48h_pct"))
                ),
                "avg_destination_forward_max_24h_pct": format_number(
                    mean_or_none(numeric_values(group_rows, "destination_forward_max_24h_pct"))
                ),
                "avg_destination_forward_min_24h_pct": format_number(
                    mean_or_none(numeric_values(group_rows, "destination_forward_min_24h_pct"))
                ),
            }
        )
        out.append(out_row)
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def build_manifest(
    *,
    run_id: str,
    output_dir: Path,
    rotation_run_dir: Path,
    regime_run_dir: Path,
    joined_event_count: int,
    unmatched_rotation_event_count: int,
    unmatched_regime_sample_count: int,
    run_started_at: datetime,
    run_finished_at: datetime,
    paths: OutputPaths,
    wrote_files: bool,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "rotation_run_dir": str(rotation_run_dir),
        "regime_run_dir": str(regime_run_dir),
        "run_started_at_utc": run_started_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "run_finished_at_utc": run_finished_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "run_duration_sec": round((run_finished_at - run_started_at).total_seconds(), 6),
        "joined_event_count": int(joined_event_count),
        "unmatched_rotation_event_count": int(unmatched_rotation_event_count),
        "unmatched_regime_sample_count": int(unmatched_regime_sample_count),
        "confidence_terminology_notes": [
            "confidence_bucket is legacy bucket naming retained for backward compatibility.",
            "measurement_coverage_score is coverage or measurement availability only.",
            "measurement_coverage_score is not trend probability.",
            "measurement_coverage_score is not phase stability.",
        ],
        "notes": [
            "Join key is sample_ts_utc from local CSV outputs only.",
            "This audit measures destination outcomes by discovered regime plus legacy destination labels.",
            "No candidate logic, thresholds, or label tuning are changed here.",
        ],
        "wrote_files": bool(wrote_files),
        "output_paths": {
            "summary_symbol_curve_regime_csv": str(paths.summary_symbol_curve_regime_csv),
            "summary_symbol_confidence_regime_csv": str(paths.summary_symbol_confidence_regime_csv),
            "summary_curve_regime_csv": str(paths.summary_curve_regime_csv),
            "summary_confidence_regime_csv": str(paths.summary_confidence_regime_csv),
            "summary_included_regime_csv": str(paths.summary_included_regime_csv),
            "summary_symbol_included_regime_csv": str(paths.summary_symbol_included_regime_csv),
            "manifest_json": str(paths.manifest_json),
        },
        **SAFETY_MARKERS,
    }


def render_table(manifest: dict[str, Any]) -> str:
    lines = [
        f"[RUN][ID] {manifest['run_id']}",
        f"[RUN][OUT_DIR] {manifest['output_dir']}",
        f"report={REPORT_NAME} version=1.0",
        "scope=research-only file-input-only no-db",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "db_reads=0 db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        f"rotation_run_dir={manifest['rotation_run_dir']}",
        f"regime_run_dir={manifest['regime_run_dir']}",
        (
            f"joined_event_count={manifest['joined_event_count']} "
            f"unmatched_rotation_event_count={manifest['unmatched_rotation_event_count']} "
            f"unmatched_regime_sample_count={manifest['unmatched_regime_sample_count']}"
        ),
        f"wrote_files={manifest['wrote_files']}",
    ]
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
            lines.append(f"  wrote_file[{key}]={value}")
    lines.append("[DONE] db_reads=0 db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rotation_run_dir = Path(args.rotation_run_dir)
    regime_run_dir = Path(args.regime_run_dir)
    rotation_csv = rotation_run_dir / ROTATION_FILE_NAME
    regime_csv = regime_run_dir / REGIME_FILE_NAME
    if not rotation_csv.exists():
        raise FileNotFoundError(f"Missing rotation input CSV: {rotation_csv}")
    if not regime_csv.exists():
        raise FileNotFoundError(f"Missing regime input CSV: {regime_csv}")

    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    paths = OutputPaths(output_dir)

    rotation_rows = read_csv_rows(rotation_csv)
    regime_rows = read_csv_rows(regime_csv)
    regime_by_ts = {str(row.get("sample_ts_utc") or ""): row for row in regime_rows}

    joined_rows: list[dict[str, str]] = []
    matched_ts: set[str] = set()
    unmatched_rotation_event_count = 0
    for row in rotation_rows:
        sample_ts = str(row.get("sample_ts_utc") or "")
        regime_row = regime_by_ts.get(sample_ts)
        if regime_row is None:
            unmatched_rotation_event_count += 1
            continue
        matched_ts.add(sample_ts)
        joined = dict(row)
        joined["discovered_regime_id"] = str(regime_row.get("discovered_regime_id") or "")
        joined["discovered_regime_label_auto"] = str(regime_row.get("discovered_regime_label_auto") or "")
        joined["included_state"] = included_state(row)
        joined_rows.append(joined)

    unmatched_regime_sample_count = sum(
        1 for row in regime_rows if str(row.get("sample_ts_utc") or "") not in matched_ts
    )

    summary_symbol_curve_regime = summary_rows(
        joined_rows,
        group_fields=[
            "destination_symbol",
            "curve_sanity_state",
            "discovered_regime_id",
            "discovered_regime_label_auto",
        ],
    )
    summary_symbol_confidence_regime = summary_rows(
        joined_rows,
        group_fields=[
            "destination_symbol",
            "confidence_bucket",
            "discovered_regime_id",
            "discovered_regime_label_auto",
        ],
    )
    summary_curve_regime = summary_rows(
        joined_rows,
        group_fields=["curve_sanity_state", "discovered_regime_id", "discovered_regime_label_auto"],
    )
    summary_confidence_regime = summary_rows(
        joined_rows,
        group_fields=["confidence_bucket", "discovered_regime_id", "discovered_regime_label_auto"],
    )
    summary_included_regime = summary_rows(
        joined_rows,
        group_fields=["included_state", "discovered_regime_id", "discovered_regime_label_auto"],
    )
    summary_symbol_included_regime = summary_rows(
        joined_rows,
        group_fields=["destination_symbol", "included_state", "discovered_regime_id", "discovered_regime_label_auto"],
    )

    run_finished_at = datetime.now(UTC)
    manifest = build_manifest(
        run_id=run_id,
        output_dir=output_dir,
        rotation_run_dir=rotation_run_dir,
        regime_run_dir=regime_run_dir,
        joined_event_count=len(joined_rows),
        unmatched_rotation_event_count=unmatched_rotation_event_count,
        unmatched_regime_sample_count=unmatched_regime_sample_count,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        paths=paths,
        wrote_files=args.write_files,
    )

    if args.write_files:
        write_csv(
            paths.summary_symbol_curve_regime_csv,
            summary_symbol_curve_regime,
            ["destination_symbol", "curve_sanity_state", *SUMMARY_FIELDS],
        )
        write_csv(
            paths.summary_symbol_confidence_regime_csv,
            summary_symbol_confidence_regime,
            ["destination_symbol", "confidence_bucket", *SUMMARY_FIELDS],
        )
        write_csv(
            paths.summary_curve_regime_csv,
            summary_curve_regime,
            ["curve_sanity_state", *SUMMARY_FIELDS],
        )
        write_csv(
            paths.summary_confidence_regime_csv,
            summary_confidence_regime,
            ["confidence_bucket", *SUMMARY_FIELDS],
        )
        write_csv(
            paths.summary_included_regime_csv,
            summary_included_regime,
            ["included_state", *SUMMARY_FIELDS],
        )
        write_csv(
            paths.summary_symbol_included_regime_csv,
            summary_symbol_included_regime,
            ["destination_symbol", "included_state", *SUMMARY_FIELDS],
        )
        write_json(paths.manifest_json, manifest)

    if args.output == "json":
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
