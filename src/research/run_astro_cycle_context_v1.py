from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.research.run_market_breath_analysis_v1 import INTERVAL_SECONDS, fmt_ts, parse_ts


REPORT_NAME = "astro_cycle_context_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/astro_cycle_context_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

ASTRO_CONTEXT_CSV = "astro_cycle_context_v1.csv"
ASTRO_CONTEXT_JSONL = "astro_cycle_context_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

SYNODIC_MONTH_DAYS = 29.53058867
REFERENCE_NEW_MOON_UTC = datetime(2000, 1, 6, 18, 14, 0)
TROPICAL_YEAR_DAYS = 365.2422

SAFETY_MARKERS = {
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
}

OUTPUT_FIELDS = [
    "sample_ts_utc",
    "moon_phase_fraction",
    "moon_age_days",
    "moon_illumination_pct",
    "days_to_new_moon",
    "days_to_full_moon",
    "lunar_quarter",
    "solar_day_of_year",
    "seasonal_phase_fraction",
    "equinox_solstice_phase",
]


@dataclass(frozen=True)
class OutputPaths:
    astro_context_csv: Path
    astro_context_jsonl: Path
    manifest_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build external lunar and solar cycle context rows from timestamps only "
            "(research-only, no trading signal use)."
        )
    )
    parser.add_argument("--start-ts", required=True)
    parser.add_argument("--end-ts", required=True)
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.replace(tzinfo=UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_output_dir(*, output_root: str | None, run_id: str) -> Path:
    root = Path(output_root) if output_root else Path(DEFAULT_OUTPUT_ROOT)
    return root / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        astro_context_csv=output_dir / ASTRO_CONTEXT_CSV,
        astro_context_jsonl=output_dir / ASTRO_CONTEXT_JSONL,
        manifest_json=output_dir / MANIFEST_JSON,
    )


def format_number(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}f}"


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return fmt_ts(value)
    return value


def interval_delta(interval_code: str) -> timedelta:
    seconds = INTERVAL_SECONDS.get(interval_code)
    if seconds is None:
        raise ValueError(f"Unsupported interval: {interval_code}")
    return timedelta(seconds=seconds)


def generate_sample_timestamps(start_ts: datetime, end_ts: datetime, step: timedelta) -> list[datetime]:
    samples: list[datetime] = []
    current = start_ts
    while current <= end_ts:
        samples.append(current)
        current += step
    return samples


def moon_phase_context(sample_ts: datetime) -> dict[str, float | str]:
    delta_days = (sample_ts - REFERENCE_NEW_MOON_UTC).total_seconds() / 86400.0
    lunations = delta_days / SYNODIC_MONTH_DAYS
    phase_fraction = lunations % 1.0
    age_days = phase_fraction * SYNODIC_MONTH_DAYS
    illumination_pct = ((1.0 - math.cos(2.0 * math.pi * phase_fraction)) / 2.0) * 100.0
    days_to_new_moon = SYNODIC_MONTH_DAYS - age_days

    full_moon_age = SYNODIC_MONTH_DAYS / 2.0
    if age_days <= full_moon_age:
        days_to_full_moon = full_moon_age - age_days
    else:
        days_to_full_moon = SYNODIC_MONTH_DAYS + full_moon_age - age_days

    if phase_fraction < 0.25:
        lunar_quarter = "NEW_TO_FIRST_QUARTER"
    elif phase_fraction < 0.50:
        lunar_quarter = "FIRST_QUARTER_TO_FULL"
    elif phase_fraction < 0.75:
        lunar_quarter = "FULL_TO_LAST_QUARTER"
    else:
        lunar_quarter = "LAST_QUARTER_TO_NEW"

    return {
        "moon_phase_fraction": phase_fraction,
        "moon_age_days": age_days,
        "moon_illumination_pct": illumination_pct,
        "days_to_new_moon": days_to_new_moon,
        "days_to_full_moon": days_to_full_moon,
        "lunar_quarter": lunar_quarter,
    }


def seasonal_boundaries(year: int) -> list[tuple[str, datetime]]:
    return [
        ("MARCH_EQUINOX_TO_JUNE_SOLSTICE", datetime(year, 3, 20, 0, 0, 0)),
        ("JUNE_SOLSTICE_TO_SEPTEMBER_EQUINOX", datetime(year, 6, 21, 0, 0, 0)),
        ("SEPTEMBER_EQUINOX_TO_DECEMBER_SOLSTICE", datetime(year, 9, 22, 0, 0, 0)),
        ("DECEMBER_SOLSTICE_TO_MARCH_EQUINOX", datetime(year, 12, 21, 0, 0, 0)),
        ("NEXT_MARCH_EQUINOX", datetime(year + 1, 3, 20, 0, 0, 0)),
    ]


def solar_context(sample_ts: datetime) -> dict[str, float | int | str]:
    year_start = datetime(sample_ts.year, 1, 1, 0, 0, 0)
    solar_day_of_year = int((sample_ts - year_start).days) + 1

    march_equinox = datetime(sample_ts.year, 3, 20, 0, 0, 0)
    seasonal_days = ((sample_ts - march_equinox).total_seconds() / 86400.0) % TROPICAL_YEAR_DAYS
    seasonal_phase_fraction = seasonal_days / TROPICAL_YEAR_DAYS

    boundaries = seasonal_boundaries(sample_ts.year)
    for idx in range(len(boundaries) - 1):
        phase_label, phase_start = boundaries[idx]
        next_start = boundaries[idx + 1][1]
        if phase_start <= sample_ts < next_start:
            return {
                "solar_day_of_year": solar_day_of_year,
                "seasonal_phase_fraction": seasonal_phase_fraction,
                "equinox_solstice_phase": phase_label,
            }

    return {
        "solar_day_of_year": solar_day_of_year,
        "seasonal_phase_fraction": seasonal_phase_fraction,
        "equinox_solstice_phase": "DECEMBER_SOLSTICE_TO_MARCH_EQUINOX",
    }


def build_context_row(sample_ts: datetime) -> dict[str, str]:
    moon = moon_phase_context(sample_ts)
    solar = solar_context(sample_ts)
    return {
        "sample_ts_utc": fmt_ts(sample_ts),
        "moon_phase_fraction": format_number(float(moon["moon_phase_fraction"])),
        "moon_age_days": format_number(float(moon["moon_age_days"])),
        "moon_illumination_pct": format_number(float(moon["moon_illumination_pct"])),
        "days_to_new_moon": format_number(float(moon["days_to_new_moon"])),
        "days_to_full_moon": format_number(float(moon["days_to_full_moon"])),
        "lunar_quarter": str(moon["lunar_quarter"]),
        "solar_day_of_year": str(int(solar["solar_day_of_year"])),
        "seasonal_phase_fraction": format_number(float(solar["seasonal_phase_fraction"])),
        "equinox_solstice_phase": str(solar["equinox_solstice_phase"]),
    }


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
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, default=json_default) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    sample_count: int,
    run_started_at: datetime,
    run_finished_at: datetime,
    output_paths_map: OutputPaths,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at.replace(tzinfo=None)),
        "run_finished_at_utc": fmt_ts(run_finished_at.replace(tzinfo=None)),
        "run_duration_sec": round((run_finished_at - run_started_at).total_seconds(), 6),
        "start_ts": args.start_ts,
        "end_ts": args.end_ts,
        "interval": args.interval,
        "sample_count": int(sample_count),
        "wrote_files": bool(args.write_files),
        "scope": "research-only external-context-only",
        "trading_signal_allowed": False,
        "db_reads": 0,
        "notes": [
            "This dataset is external context only and is not a trading signal.",
            "Lunar values use deterministic astronomical approximations from timestamps only.",
            "No market, broker, account, order, or dashboard inputs are used.",
        ],
        "output_paths": {
            "astro_context_csv": str(output_paths_map.astro_context_csv),
            "astro_context_jsonl": str(output_paths_map.astro_context_jsonl),
            "manifest_json": str(output_paths_map.manifest_json),
        },
        **SAFETY_MARKERS,
    }


def render_table(manifest: dict[str, Any]) -> str:
    lines = [
        f"[RUN][ID] {manifest['run_id']}",
        f"[RUN][OUT_DIR] {manifest['output_dir']}",
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only external-context-only",
        "inputs=timestamps_only no_db no_broker no_account no_orders no_dashboard",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        (
            f"start_ts={manifest['start_ts']} end_ts={manifest['end_ts']} "
            f"interval={manifest['interval']} sample_count={manifest['sample_count']}"
        ),
        f"wrote_files={manifest['wrote_files']}",
    ]
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
            lines.append(f"  wrote_file[{key}]={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {args.interval}")

    start_ts = parse_ts(args.start_ts)
    end_ts = parse_ts(args.end_ts)
    if start_ts > end_ts:
        raise ValueError("--start-ts must be <= --end-ts")

    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    paths = output_paths(output_dir)

    samples = generate_sample_timestamps(start_ts, end_ts, interval_delta(args.interval))
    rows = [build_context_row(sample_ts) for sample_ts in samples]

    run_finished_at = datetime.now(UTC)
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        sample_count=len(rows),
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        output_paths_map=paths,
    )

    if args.write_files:
        write_csv(paths.astro_context_csv, rows, OUTPUT_FIELDS)
        write_jsonl(paths.astro_context_jsonl, rows)
        write_json(paths.manifest_json, manifest)

    if args.output == "json":
        print(f"[RUN][ID] {manifest['run_id']}")
        print(f"[RUN][OUT_DIR] {manifest['output_dir']}")
        if manifest["wrote_files"]:
            for key, value in manifest["output_paths"].items():
                print(f"wrote_file[{key}]={value}")
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, default=json_default))
    else:
        print(render_table(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
