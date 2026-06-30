from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from src.market_context.breathline_lattice_matcher_v2 import (
    CYCLE_DAYS,
    DEFAULT_SHIFT_GRID_DAYS,
    SELECTION_STATUS_UNIQUE,
    Candle,
    ShiftSelectionSummary,
    ensure_supported_interval,
    iso_utc,
    parse_dt,
    select_best_shift,
)


RUNNER_NAME = "run_breathline_lattice_shift_calibration_v2"
VERSION = "2.0"
DEFAULT_CONTINUITY_ALERT_DELTA_DAYS = 3.0
RANKED_SHIFT_CANDIDATES_CSV = "ranked_shift_candidates.csv"
MARKER_SEQUENCE_EVIDENCE_CSV = "marker_sequence_evidence.csv"
EXTENSION_MARKER_EVIDENCE_CSV = "extension_marker_evidence.csv"
EPOCH_SHIFT_CONTINUITY_CSV = "epoch_shift_continuity.csv"
TOLERANCE_SENSITIVITY_SUMMARY_CSV = "tolerance_sensitivity_summary.csv"
MANIFEST_TXT = "manifest.txt"


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"
    commit = result.stdout.strip()
    return commit or "unavailable"


def ensure_empty_output_dir(path: Path) -> None:
    if path.exists():
        if any(path.iterdir()):
            raise ValueError(f"Output directory must be empty: {path}")
    else:
        path.mkdir(parents=True, exist_ok=True)


def parse_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def load_candles_jsonl(path: Path, interval_code: str) -> dict[str, list[Candle]]:
    ensure_supported_interval(interval_code)
    grouped: dict[str, list[Candle]] = defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            row = json.loads(raw_line)
            symbol = str(row.get("symbol") or "").strip()
            ts_raw = str(row.get("open_ts_utc") or "").strip()
            if not symbol or not ts_raw:
                raise ValueError(f"Candle row missing symbol/open_ts_utc at line {line_number}")
            grouped[symbol].append(
                Candle(
                    symbol=symbol,
                    open_ts_utc=parse_dt(ts_raw),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
            )
    for candles in grouped.values():
        candles.sort(key=lambda row: row.open_ts_utc)
    return grouped


def _table_cols(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            """,
            (table_name,),
        )
        return {row["COLUMN_NAME"] for row in cur.fetchall()}


def _choose(cols: set[str], options: list[str], *, required: bool = True) -> str | None:
    for option in options:
        if option in cols:
            return option
    if required:
        raise ValueError(f"Missing expected column. Tried: {options}")
    return None


def load_db_candles(symbol: str, interval_code: str) -> list[Candle]:
    ensure_supported_interval(interval_code)
    from src.common.db import db_cursor

    with db_cursor(commit=False) as (conn, cur):
        asset_cols = _table_cols(conn, "asset")
        candle_cols = _table_cols(conn, "obs_market_candle")

        asset_id_col = _choose(asset_cols, ["asset_id", "id"])
        asset_symbol_col = _choose(asset_cols, ["symbol", "asset_code", "code", "base_symbol", "ticker"])
        candle_asset_col = _choose(candle_cols, ["asset_id"])
        candle_interval_col = _choose(candle_cols, ["interval_code", "timeframe"], required=False)
        candle_ts_col = _choose(candle_cols, ["open_ts_utc", "ts_utc", "timestamp_utc"])
        candle_open_col = _choose(candle_cols, ["open", "open_price", "o"])
        candle_high_col = _choose(candle_cols, ["high", "high_price", "h"])
        candle_low_col = _choose(candle_cols, ["low", "low_price", "l"])
        candle_close_col = _choose(candle_cols, ["close", "close_price", "c"])

        cur.execute(
            f"""
            SELECT `{asset_id_col}` AS asset_id
            FROM asset
            WHERE UPPER(`{asset_symbol_col}`) = %s
            LIMIT 1
            """,
            (symbol.upper(),),
        )
        asset_row = cur.fetchone()
        if not asset_row:
            raise ValueError(f"Could not resolve asset for symbol={symbol}")

        where = [f"`{candle_asset_col}` = %s"]
        params: list[Any] = [asset_row["asset_id"]]
        if candle_interval_col is not None:
            where.append(f"`{candle_interval_col}` = %s")
            params.append(interval_code)

        cur.execute(
            f"""
            SELECT
                `{candle_ts_col}` AS open_ts_utc,
                `{candle_open_col}` AS open_price,
                `{candle_high_col}` AS high_price,
                `{candle_low_col}` AS low_price,
                `{candle_close_col}` AS close_price
            FROM obs_market_candle
            WHERE {' AND '.join(where)}
            ORDER BY `{candle_ts_col}` ASC
            """,
            tuple(params),
        )
        rows = cur.fetchall()

    candles: list[Candle] = []
    for row in rows:
        open_ts_value = row["open_ts_utc"]
        if isinstance(open_ts_value, str):
            open_ts_utc = parse_dt(open_ts_value)
        else:
            open_ts_utc = open_ts_value.astimezone(UTC) if open_ts_value.tzinfo else open_ts_value.replace(tzinfo=UTC)
        candles.append(
            Candle(
                symbol=symbol,
                open_ts_utc=open_ts_utc,
                open=float(row["open_price"]),
                high=float(row["high_price"]),
                low=float(row["low_price"]),
                close=float(row["close_price"]),
            )
        )
    return candles


def load_replay_epochs(path: Path, symbols_filter: set[str]) -> list[dict[str, str]]:
    accepted: dict[tuple[str, str], dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            row = json.loads(raw_line)
            if row.get("status") != "OK":
                continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                raise ValueError(f"Accepted replay row missing symbol at line {line_number}")
            if symbols_filter and symbol not in symbols_filter:
                continue
            raw_anchor = str(row.get("raw_lattice_anchor_ts_utc") or row.get("anchor_ts_utc") or "").strip()
            if not raw_anchor:
                raise ValueError(f"Accepted replay row missing raw_lattice_anchor_ts_utc/anchor_ts_utc at line {line_number}")
            interval_code = str(row.get("interval_code") or "1d").strip()
            ensure_supported_interval(interval_code)
            accepted.setdefault((symbol, raw_anchor), {
                "symbol": symbol,
                "raw_lattice_anchor_ts_utc": raw_anchor,
                "interval_code": interval_code,
            })
    return sorted(accepted.values(), key=lambda row: (row["symbol"], row["raw_lattice_anchor_ts_utc"]))


def evaluate_epochs(
    epochs: list[dict[str, str]],
    candles_by_symbol: dict[str, list[Candle]] | None,
    sensitivity_modes: list[str],
) -> tuple[list[ShiftSelectionSummary], str, int]:
    db_reads = 0
    results: list[ShiftSelectionSummary] = []
    db_candle_cache: dict[str, list[Candle]] = {}

    for epoch_index, epoch in enumerate(epochs, start=1):
        symbol = epoch["symbol"]
        interval_code = epoch["interval_code"]
        ensure_supported_interval(interval_code)

        if candles_by_symbol is None:
            if symbol not in db_candle_cache:
                print(f"  [db] loading candles symbol={symbol} interval={interval_code}", flush=True)
                db_candle_cache[symbol] = load_db_candles(symbol, interval_code)
                db_reads += 1
            candles = db_candle_cache[symbol]
            candle_source = "db_read_only_obs_market_candle"
        else:
            candles = candles_by_symbol.get(symbol, [])
            candle_source = "candles_jsonl_fixture"

        if not candles:
            raise ValueError(f"No candles available for symbol={symbol}")

        anchor_dt = parse_dt(epoch["raw_lattice_anchor_ts_utc"])
        for sensitivity_mode in sensitivity_modes:
            summary = select_best_shift(
                candles=candles,
                symbol=symbol,
                raw_lattice_anchor_ts_utc=anchor_dt,
                sensitivity_mode=sensitivity_mode,
                cycle_days=CYCLE_DAYS,
                interval_code=interval_code,
                shift_grid_days=DEFAULT_SHIFT_GRID_DAYS,
            )
            results.append(summary)

        if epoch_index % 10 == 0 or epoch_index == len(epochs):
            print(f"  [progress] epoch {epoch_index}/{len(epochs)}", flush=True)

    return results, candle_source if candles_by_symbol is not None else "db_read_only_obs_market_candle", db_reads


def build_ranked_shift_candidate_rows(summaries: list[ShiftSelectionSummary]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        top_key = summary.ranked_candidates[0].ranking_key
        for rank_index, candidate in enumerate(summary.ranked_candidates, start=1):
            is_top = candidate.ranking_key == top_key
            rows.append(
                {
                    "symbol": summary.symbol,
                    "raw_lattice_anchor_ts_utc": summary.raw_lattice_anchor_ts_utc,
                    "interval_code": summary.interval_code,
                    "sensitivity_mode": summary.sensitivity_mode,
                    "tolerance_hours": summary.tolerance_hours,
                    "selection_status": summary.selection_status,
                    "selected_template_time_shift_days": summary.selected_template_time_shift_days,
                    "tied_shift_days": ",".join(str(value) for value in summary.tied_shift_days),
                    "candidate_rank": rank_index,
                    "is_top_candidate": is_top,
                    "template_time_shift_days": candidate.template_time_shift_days,
                    "effective_schedule_origin_ts_utc": candidate.effective_schedule_origin_ts_utc,
                    "matched_base_marker_count": candidate.matched_base_marker_count,
                    "base_shape_rule_passed_count": candidate.base_shape_rule_passed_count,
                    "base_shape_rule_available_count": candidate.base_shape_rule_available_count,
                    "max_base_marker_residual_hours": candidate.max_base_marker_residual_hours,
                    "total_base_marker_residual_hours": candidate.total_base_marker_residual_hours,
                    "shape_reference_price": candidate.shape_rule_diagnostics.reference_price,
                    "diagnostic_second_peak_retests_first_lift_within_2p5pct": (
                        candidate.shape_rule_diagnostics.diagnostic_rules["second_peak_retests_first_lift_within_2p5pct"]
                    ),
                }
            )
    return rows


def build_marker_sequence_rows(summaries: list[ShiftSelectionSummary]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        for candidate in summary.ranked_candidates:
            for index, marker in enumerate(candidate.base_marker_evidence, start=1):
                row = {
                    "symbol": summary.symbol,
                    "raw_lattice_anchor_ts_utc": summary.raw_lattice_anchor_ts_utc,
                    "interval_code": summary.interval_code,
                    "sensitivity_mode": summary.sensitivity_mode,
                    "selection_status": summary.selection_status,
                    "selected_template_time_shift_days": summary.selected_template_time_shift_days,
                    "template_time_shift_days": candidate.template_time_shift_days,
                    "effective_schedule_origin_ts_utc": candidate.effective_schedule_origin_ts_utc,
                    "marker_sequence_index": index,
                    "marker_set": marker.marker_set,
                    "marker_ratio": marker.ratio,
                    "marker_code": marker.code,
                    "marker_kind": marker.kind,
                    "expected_ts_utc": marker.expected_ts_utc,
                    "observed_candle_open_ts_utc": marker.observed_candle_open_ts_utc,
                    "observed_price": marker.observed_price,
                    "marker_residual_hours": marker.residual_hours,
                    "matched": marker.matched,
                }
                row.update(candidate.shape_rule_diagnostics.ranking_rules)
                row.update(candidate.shape_rule_diagnostics.diagnostic_rules)
                rows.append(row)
    return rows


def build_extension_rows(summaries: list[ShiftSelectionSummary]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        if summary.selection_status != SELECTION_STATUS_UNIQUE or summary.selected_template_time_shift_days is None:
            continue
        selected = next(
            candidate
            for candidate in summary.ranked_candidates
            if candidate.template_time_shift_days == summary.selected_template_time_shift_days
        )
        for index, marker in enumerate(selected.extension_marker_evidence, start=1):
            rows.append(
                {
                    "symbol": summary.symbol,
                    "raw_lattice_anchor_ts_utc": summary.raw_lattice_anchor_ts_utc,
                    "interval_code": summary.interval_code,
                    "sensitivity_mode": summary.sensitivity_mode,
                    "selection_status": summary.selection_status,
                    "selected_template_time_shift_days": summary.selected_template_time_shift_days,
                    "effective_schedule_origin_ts_utc": selected.effective_schedule_origin_ts_utc,
                    "extension_sequence_index": index,
                    "marker_set": marker.marker_set,
                    "marker_ratio": marker.ratio,
                    "marker_code": marker.code,
                    "marker_kind": marker.kind,
                    "expected_ts_utc": marker.expected_ts_utc,
                    "observed_candle_open_ts_utc": marker.observed_candle_open_ts_utc,
                    "observed_price": marker.observed_price,
                    "marker_residual_hours": marker.residual_hours,
                    "matched": marker.matched,
                }
            )
    return rows


def _continuity_row(
    summary: ShiftSelectionSummary,
    previous_unique_shift: float | None,
    previous_anchor_dt: datetime | None,
    continuity_alert_delta_days: float,
) -> dict[str, Any]:
    current_anchor_dt = parse_dt(summary.raw_lattice_anchor_ts_utc)
    current_unique_shift = summary.selected_template_time_shift_days
    raw_shift_delta = None
    anchor_spacing_days = None
    effective_cycle_spacing_days = None
    exceeds_threshold = None

    if previous_unique_shift is not None and current_unique_shift is not None:
        raw_shift_delta = round(current_unique_shift - previous_unique_shift, 6)
        exceeds_threshold = abs(raw_shift_delta) >= continuity_alert_delta_days
    if previous_anchor_dt is not None:
        anchor_spacing_days = round((current_anchor_dt - previous_anchor_dt).total_seconds() / 86400.0, 6)
    if anchor_spacing_days is not None and raw_shift_delta is not None:
        effective_cycle_spacing_days = round(anchor_spacing_days + raw_shift_delta, 6)

    return {
        "symbol": summary.symbol,
        "raw_lattice_anchor_ts_utc": summary.raw_lattice_anchor_ts_utc,
        "sensitivity_mode": summary.sensitivity_mode,
        "selection_status": summary.selection_status,
        "selected_template_time_shift_days": summary.selected_template_time_shift_days,
        "previous_unique_template_time_shift_days": previous_unique_shift,
        "current_unique_template_time_shift_days": current_unique_shift,
        "raw_shift_delta_days": raw_shift_delta,
        "raw_anchor_spacing_days": anchor_spacing_days,
        "effective_cycle_spacing_days": effective_cycle_spacing_days,
        "continuity_alert_delta_days": continuity_alert_delta_days,
        "exceeds_continuity_alert_threshold": exceeds_threshold,
        "tied_shift_days": ",".join(str(value) for value in summary.tied_shift_days),
    }


def build_continuity_rows(
    summaries: list[ShiftSelectionSummary],
    continuity_alert_delta_days: float,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[ShiftSelectionSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[(summary.symbol, summary.sensitivity_mode)].append(summary)

    rows: list[dict[str, Any]] = []
    for (_, _), group in sorted(grouped.items()):
        group.sort(key=lambda row: row.raw_lattice_anchor_ts_utc)
        previous_unique_shift: float | None = None
        previous_unique_anchor_dt: datetime | None = None
        for summary in group:
            row = _continuity_row(summary, previous_unique_shift, previous_unique_anchor_dt, continuity_alert_delta_days)
            rows.append(row)
            if summary.selection_status == SELECTION_STATUS_UNIQUE and summary.selected_template_time_shift_days is not None:
                previous_unique_shift = summary.selected_template_time_shift_days
                previous_unique_anchor_dt = parse_dt(summary.raw_lattice_anchor_ts_utc)
    return rows


def build_tolerance_summary_rows(summaries: list[ShiftSelectionSummary]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ShiftSelectionSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[summary.sensitivity_mode].append(summary)

    rows: list[dict[str, Any]] = []
    for sensitivity_mode, group in sorted(grouped.items()):
        unique_rows = [row for row in group if row.selection_status == SELECTION_STATUS_UNIQUE]
        tied_rows = [row for row in group if row.selection_status != SELECTION_STATUS_UNIQUE]
        selected_shifts = [row.selected_template_time_shift_days for row in unique_rows if row.selected_template_time_shift_days is not None]
        matched_counts = [
            next(
                candidate.matched_base_marker_count
                for candidate in row.ranked_candidates
                if row.selected_template_time_shift_days is not None
                and candidate.template_time_shift_days == row.selected_template_time_shift_days
            )
            for row in unique_rows
            if row.selected_template_time_shift_days is not None
        ]
        rows.append(
            {
                "sensitivity_mode": sensitivity_mode,
                "tolerance_hours": group[0].tolerance_hours,
                "epoch_count": len(group),
                "unique_top_candidate_count": len(unique_rows),
                "tied_top_candidate_count": len(tied_rows),
                "avg_selected_template_time_shift_days": round(mean(selected_shifts), 6) if selected_shifts else "",
                "avg_matched_base_marker_count": round(mean(matched_counts), 6) if matched_counts else "",
            }
        )
    return rows


def write_manifest(
    path: Path,
    *,
    input_jsonl: Path,
    candle_source: str,
    candles_jsonl: Path | None,
    db_reads: int,
    continuity_alert_delta_days: float,
    replay_epoch_count: int,
    result_count: int,
) -> None:
    lines = [
        f"runner={RUNNER_NAME}",
        f"version={VERSION}",
        f"generated_at_utc={iso_utc(utc_now())}",
        f"source_git_commit={current_git_commit()}",
        f"input_jsonl={input_jsonl}",
        f"input_sha256={sha256_file(input_jsonl)}",
        f"candle_source={candle_source}",
        f"candles_jsonl={candles_jsonl or ''}",
        f"candles_jsonl_sha256={sha256_file(candles_jsonl) if candles_jsonl else ''}",
        f"replay_epoch_count={replay_epoch_count}",
        f"sensitivity_result_count={result_count}",
        f"continuity_alert_delta_days={continuity_alert_delta_days}",
        f"db_reads={db_reads}",
        "db_writes=0",
        "broker_calls=0",
        "broker_writes=0",
        "order_submission=0",
        "live_orders=0",
        "selection_engine=none",
        "decision_gate=none",
        "execution_planner=none",
        "executor=none",
        "scope=research-only market-only calibration lane",
        "boundary_marker=effective_schedule_origin_is_schedule_coordinate_only",
        "boundary_marker=no_reanchor_labels_no_phase_truth_claims",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only Breathline V2 lattice shift residual calibration runner."
    )
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--candles-jsonl", default="")
    parser.add_argument("--interval-code", default="1d")
    parser.add_argument("--sensitivity-modes", default="STRICT,NORMAL,MAX")
    parser.add_argument("--continuity-alert-delta-days", type=float, default=DEFAULT_CONTINUITY_ALERT_DELTA_DAYS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_supported_interval(args.interval_code)

    input_jsonl = Path(args.input_jsonl)
    out_dir = Path(args.out_dir)
    candles_jsonl = Path(args.candles_jsonl) if args.candles_jsonl else None
    ensure_empty_output_dir(out_dir)

    print(
        f"STARTED runner={RUNNER_NAME} version={VERSION}"
        f" symbols={args.symbols or 'ALL'}"
        f" sensitivity_modes={args.sensitivity_modes}"
        f" candle_source={'jsonl' if candles_jsonl else 'db'}"
        f" out_dir={out_dir}",
        flush=True,
    )

    symbols_filter = set(parse_csv_list(args.symbols))
    sensitivity_modes = parse_csv_list(args.sensitivity_modes)
    if not sensitivity_modes:
        raise ValueError("At least one sensitivity mode is required.")

    epochs = load_replay_epochs(input_jsonl, symbols_filter)
    if not epochs:
        raise ValueError("No accepted replay epochs found (status == 'OK').")

    candles_by_symbol = load_candles_jsonl(candles_jsonl, args.interval_code) if candles_jsonl else None
    summaries, candle_source, db_reads = evaluate_epochs(epochs, candles_by_symbol, sensitivity_modes)

    ranked_rows = build_ranked_shift_candidate_rows(summaries)
    marker_rows = build_marker_sequence_rows(summaries)
    extension_rows = build_extension_rows(summaries)
    continuity_rows = build_continuity_rows(summaries, args.continuity_alert_delta_days)
    tolerance_rows = build_tolerance_summary_rows(summaries)

    write_csv(
        out_dir / RANKED_SHIFT_CANDIDATES_CSV,
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "interval_code",
            "sensitivity_mode",
            "tolerance_hours",
            "selection_status",
            "selected_template_time_shift_days",
            "tied_shift_days",
            "candidate_rank",
            "is_top_candidate",
            "template_time_shift_days",
            "effective_schedule_origin_ts_utc",
            "matched_base_marker_count",
            "base_shape_rule_passed_count",
            "base_shape_rule_available_count",
            "max_base_marker_residual_hours",
            "total_base_marker_residual_hours",
            "shape_reference_price",
            "diagnostic_second_peak_retests_first_lift_within_2p5pct",
        ],
        ranked_rows,
    )
    write_csv(
        out_dir / MARKER_SEQUENCE_EVIDENCE_CSV,
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "interval_code",
            "sensitivity_mode",
            "selection_status",
            "selected_template_time_shift_days",
            "template_time_shift_days",
            "effective_schedule_origin_ts_utc",
            "marker_sequence_index",
            "marker_set",
            "marker_ratio",
            "marker_code",
            "marker_kind",
            "expected_ts_utc",
            "observed_candle_open_ts_utc",
            "observed_price",
            "marker_residual_hours",
            "matched",
            "first_lift_above_origin_reference",
            "first_dip_below_first_lift",
            "second_peak_above_first_dip",
            "second_dip_below_second_peak",
            "second_dip_higher_than_first_dip",
            "ignition_above_second_dip",
            "pulse_above_ignition",
            "pulse_above_second_peak",
            "second_peak_retests_first_lift_within_2p5pct",
        ],
        marker_rows,
    )
    write_csv(
        out_dir / EXTENSION_MARKER_EVIDENCE_CSV,
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "interval_code",
            "sensitivity_mode",
            "selection_status",
            "selected_template_time_shift_days",
            "effective_schedule_origin_ts_utc",
            "extension_sequence_index",
            "marker_set",
            "marker_ratio",
            "marker_code",
            "marker_kind",
            "expected_ts_utc",
            "observed_candle_open_ts_utc",
            "observed_price",
            "marker_residual_hours",
            "matched",
        ],
        extension_rows,
    )
    write_csv(
        out_dir / EPOCH_SHIFT_CONTINUITY_CSV,
        [
            "symbol",
            "raw_lattice_anchor_ts_utc",
            "sensitivity_mode",
            "selection_status",
            "selected_template_time_shift_days",
            "previous_unique_template_time_shift_days",
            "current_unique_template_time_shift_days",
            "raw_shift_delta_days",
            "raw_anchor_spacing_days",
            "effective_cycle_spacing_days",
            "continuity_alert_delta_days",
            "exceeds_continuity_alert_threshold",
            "tied_shift_days",
        ],
        continuity_rows,
    )
    write_csv(
        out_dir / TOLERANCE_SENSITIVITY_SUMMARY_CSV,
        [
            "sensitivity_mode",
            "tolerance_hours",
            "epoch_count",
            "unique_top_candidate_count",
            "tied_top_candidate_count",
            "avg_selected_template_time_shift_days",
            "avg_matched_base_marker_count",
        ],
        tolerance_rows,
    )
    write_manifest(
        out_dir / MANIFEST_TXT,
        input_jsonl=input_jsonl,
        candle_source=candle_source,
        candles_jsonl=candles_jsonl,
        db_reads=db_reads,
        continuity_alert_delta_days=args.continuity_alert_delta_days,
        replay_epoch_count=len(epochs),
        result_count=len(summaries),
    )
    print(
        f"FINISHED runner={RUNNER_NAME}"
        f" epochs={len(epochs)} results={len(summaries)} db_reads={db_reads}"
        f" out_dir={out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
