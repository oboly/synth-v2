from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection
from src.research.run_market_breath_analysis_v1 import (
    INTERVAL_SECONDS,
    PHASES,
    fmt_ts,
    latest_asof_ts,
    parse_ts,
)
from src.research.run_market_breath_v1_1_calibration_audit import (
    SAFETY_MARKERS,
    avg,
    build_rows_for_asof,
    fetch_assets,
    fetch_available_close_ts,
    select_asof_samples,
)


REPORT_NAME = "market_breath_outcome_validation_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_DIR = "data/research/market_breath_outcome_validation_v1"
OUTPUT_ROWS = "outcome_rows_v1.jsonl"
OUTPUT_SUMMARY = "outcome_summary_v1.json"

FORWARD_HORIZONS = [1, 3, 6, 12, 18, 24]
MAX_FORWARD_HORIZON = 24

PRIMARY_VALIDATION_PHASES = ["EXHALE_EXPANSION"]
EXPLORATORY_PHASES = ["OVERBREATH_EXTENSION", "INHALE_ACCUMULATION"]
EXCLUDED_FROM_CONCLUSIONS = ["HOLD_COMPRESSION"]

INTERPRETATION_BUCKETS = {
    "EXHALE_EXPANSION": "PRIMARY",
    "COLLAPSE_RESET": "SECONDARY",
    "OVERBREATH_EXTENSION": "EXPLORATORY",
    "INHALE_ACCUMULATION": "EXPLORATORY",
    "HOLD_COMPRESSION": "EXCLUDED_LOW_SAMPLE",
    "NEUTRAL_TRANSITION": "BASELINE_REST_BUCKET",
    "INSUFFICIENT_DATA": "EXCLUDED_LOW_SAMPLE",
}


@dataclass(frozen=True)
class OutputPaths:
    outcome_rows_jsonl: Path
    outcome_summary_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Market Breath outcome validation V1 over historical as-of samples "
            "(research-only, market-only, account-agnostic dry lane)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lookback-candles", type=int, default=120)
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--sample-step-hours", type=int, default=24)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    return parser.parse_args(argv)


def fetch_future_candles_for_asof(
    conn,
    *,
    asset_ids: list[int],
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    max_horizon: int,
) -> dict[int, list[dict[str, Any]]]:
    if not asset_ids:
        return {}

    interval_seconds = INTERVAL_SECONDS[interval_code]
    horizon_end = asof_ts + timedelta(seconds=interval_seconds * max_horizon)
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT
            asset_id,
            close_ts_utc,
            close_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc > %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code, asof_ts, horizon_end, *asset_ids]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["asset_id"])].append(
            {
                "close_ts_utc": row["close_ts_utc"],
                "close_price": float(row["close_price"]) if row["close_price"] is not None else None,
            }
        )
    return dict(grouped)


def close_to_close_return(asof_close: float | None, future_close: float | None) -> float | None:
    if asof_close is None or future_close is None or asof_close <= 0:
        return None
    return round((future_close / asof_close - 1.0) * 100.0, 6)


def outcome_metrics(row: dict[str, Any], future_candles: list[dict[str, Any]]) -> dict[str, Any]:
    asof_close = row.get("close_price")
    if asof_close is None or asof_close <= 0:
        return {
            **{f"fwd_return_{horizon}c": None for horizon in FORWARD_HORIZONS},
            "max_fwd_return_24c": None,
            "min_fwd_return_24c": None,
            "max_drawdown_24c_from_asof_close": None,
            "max_runup_24c_from_asof_close": None,
            "outcome_available": False,
            "invalid_reason": row.get("invalid_reason") or "missing_asof_close",
        }

    returns_by_horizon = {
        horizon: close_to_close_return(
            asof_close,
            future_candles[horizon - 1]["close_price"] if len(future_candles) >= horizon else None,
        )
        for horizon in FORWARD_HORIZONS
    }
    available_returns = [
        close_to_close_return(asof_close, candle["close_price"])
        for candle in future_candles[:MAX_FORWARD_HORIZON]
    ]
    available_returns = [value for value in available_returns if value is not None]
    outcome_available = len(future_candles) >= MAX_FORWARD_HORIZON and returns_by_horizon[MAX_FORWARD_HORIZON] is not None
    invalid_reason = None if outcome_available else f"insufficient_future_candles:{len(future_candles)}<{MAX_FORWARD_HORIZON}"

    return {
        **{f"fwd_return_{horizon}c": returns_by_horizon[horizon] for horizon in FORWARD_HORIZONS},
        "max_fwd_return_24c": round(max(available_returns), 6) if available_returns else None,
        "min_fwd_return_24c": round(min(available_returns), 6) if available_returns else None,
        "max_drawdown_24c_from_asof_close": round(min(available_returns), 6) if available_returns else None,
        "max_runup_24c_from_asof_close": round(max(available_returns), 6) if available_returns else None,
        "outcome_available": outcome_available,
        "invalid_reason": invalid_reason,
    }


def build_outcome_row(row: dict[str, Any], future_candles: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = outcome_metrics(row, future_candles)
    return {
        "venue": row["venue"],
        "interval_code": row["interval_code"],
        "asof_ts_utc": row["asof_ts_utc"],
        "asset_id": row["asset_id"],
        "symbol": row["symbol"],
        "market_breath_phase": row["market_breath_phase"],
        "market_breath_state": row["market_breath_state"],
        "market_breath_score": row["market_breath_score"],
        "market_breath_confidence": row["market_breath_confidence"],
        "compression_score": row["compression_score"],
        "expansion_score": row["expansion_score"],
        "momentum_score": row["momentum_score"],
        "reversal_pressure_score": row["reversal_pressure_score"],
        "relative_strength_score": row["relative_strength_score"],
        "btc_alignment_score": row["btc_alignment_score"],
        "breadth_alignment_score": row["breadth_alignment_score"],
        "close_price": row["close_price"],
        **metrics,
    }


def build_outcome_rows_for_asof(
    conn,
    *,
    assets: list[Any],
    venue: str,
    interval_code: str,
    lookback_candles: int,
    asof_ts: datetime,
) -> list[dict[str, Any]]:
    rows = build_rows_for_asof(
        conn,
        assets=assets,
        venue=venue,
        interval_code=interval_code,
        lookback_candles=lookback_candles,
        asof_ts=asof_ts,
    )
    future_by_asset = fetch_future_candles_for_asof(
        conn,
        asset_ids=[asset.asset_id for asset in assets],
        venue=venue,
        interval_code=interval_code,
        asof_ts=asof_ts,
        max_horizon=MAX_FORWARD_HORIZON,
    )
    return [
        build_outcome_row(row, future_by_asset.get(int(row["asset_id"]), []))
        for row in rows
    ]


def values_for_phase(rows: list[dict[str, Any]], phase: str, field: str) -> list[float]:
    values = [
        float(row[field])
        for row in rows
        if row["market_breath_phase"] == phase and row.get("outcome_available") and row.get(field) is not None
    ]
    return values


def average_or_none(values: list[float]) -> float | None:
    return avg(values) if values else None


def median_or_none(values: list[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def positive_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0.0) / len(values) * 100.0, 6)


def phase_outcome_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for phase in PHASES:
        phase_rows = [row for row in rows if row["market_breath_phase"] == phase]
        fwd24 = values_for_phase(rows, phase, "fwd_return_24c")
        output[phase] = {
            "count": len(phase_rows),
            "outcome_available_count": sum(1 for row in phase_rows if row.get("outcome_available")),
            "avg_fwd_return_1c": average_or_none(values_for_phase(rows, phase, "fwd_return_1c")),
            "avg_fwd_return_3c": average_or_none(values_for_phase(rows, phase, "fwd_return_3c")),
            "avg_fwd_return_6c": average_or_none(values_for_phase(rows, phase, "fwd_return_6c")),
            "avg_fwd_return_12c": average_or_none(values_for_phase(rows, phase, "fwd_return_12c")),
            "avg_fwd_return_18c": average_or_none(values_for_phase(rows, phase, "fwd_return_18c")),
            "avg_fwd_return_24c": average_or_none(fwd24),
            "median_fwd_return_24c": median_or_none(fwd24),
            "positive_rate_24c": positive_rate(fwd24),
            "avg_max_runup_24c": average_or_none(values_for_phase(rows, phase, "max_runup_24c_from_asof_close")),
            "avg_max_drawdown_24c": average_or_none(values_for_phase(rows, phase, "max_drawdown_24c_from_asof_close")),
            "interpretation_bucket": INTERPRETATION_BUCKETS.get(phase, "EXPLORATORY"),
        }
    return output


def build_summary(
    rows: list[dict[str, Any]],
    *,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
    sample_count: int,
    asset_counts: list[int],
    output_paths: OutputPaths,
    wrote_files: bool,
) -> dict[str, Any]:
    phase_counts = Counter(row["market_breath_phase"] for row in rows)
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "scope": "research-only market-only account-agnostic no-aplus no-pro no-symbolic-labels outcome-measurement-only",
        "venue": venue,
        "interval_code": interval_code,
        "from_ts": fmt_ts(from_ts),
        "to_ts": fmt_ts(to_ts),
        "sample_count": sample_count,
        "asset_count_avg": avg([float(value) for value in asset_counts]),
        "row_count": len(rows),
        "outcome_available_count": sum(1 for row in rows if row.get("outcome_available")),
        "phase_counts": {phase: int(phase_counts.get(phase, 0)) for phase in PHASES},
        "phase_outcome_summary": phase_outcome_summary(rows),
        "primary_validation_phases": PRIMARY_VALIDATION_PHASES,
        "exploratory_phases": EXPLORATORY_PHASES,
        "excluded_from_conclusions": EXCLUDED_FROM_CONCLUSIONS,
        "interpretation": [
            "First-pass outcome measurement only; do not declare strategy edge.",
            "EXHALE_EXPANSION is the primary validation candidate.",
            "COLLAPSE_RESET is the secondary validation candidate.",
            "OVERBREATH_EXTENSION and INHALE_ACCUMULATION are exploratory only.",
            "HOLD_COMPRESSION is excluded from conclusions due low sample count.",
            "NEUTRAL_TRANSITION is the conservative rest-bucket baseline.",
        ],
        "limitations": [
            "Uses future candles only after each historical as-of to calculate research outcomes.",
            "Does not use outcomes to change labels, thresholds, or runtime behavior.",
            "No strategy rules, buy/sell recommendations, or execution permissions are produced.",
            "Sparse phases may not have enough sample mass for stable conclusions.",
        ],
        "no_threshold_changes_applied": True,
        "strategy_logic_added": False,
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
        "output_paths": {
            "outcome_rows_jsonl": str(output_paths.outcome_rows_jsonl),
            "outcome_summary_json": str(output_paths.outcome_summary_json),
        },
        "wrote_files": wrote_files,
        **SAFETY_MARKERS,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def render_table(summary: dict[str, Any]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only account-agnostic no_aplus no_pro no_symbolic_labels outcome_measurement_only",
        "input=obs_market_candle asset existing_market_breath_v1_logic future_candles_for_research_outcomes",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none",
        f"venue={summary['venue']} interval={summary['interval_code']}",
        f"from_ts={summary['from_ts']} to_ts={summary['to_ts']} sample_count={summary['sample_count']}",
        f"asset_count_avg={summary['asset_count_avg']} row_count={summary['row_count']} outcome_available_count={summary['outcome_available_count']}",
        "",
        "--- phase outcome summary ---",
    ]
    for phase in PHASES:
        phase_summary = summary["phase_outcome_summary"][phase]
        lines.append(
            "  "
            f"{phase} bucket={phase_summary['interpretation_bucket']} "
            f"count={phase_summary['count']} available={phase_summary['outcome_available_count']} "
            f"avg_24c={phase_summary['avg_fwd_return_24c']} "
            f"median_24c={phase_summary['median_fwd_return_24c']} "
            f"positive_rate_24c={phase_summary['positive_rate_24c']}"
        )
    lines.extend(["", "--- interpretation ---"])
    lines.extend(f"  {item}" for item in summary["interpretation"])
    lines.append("")
    lines.append(f"wrote_files={summary['wrote_files']}")
    if summary["wrote_files"]:
        for key, value in summary["output_paths"].items():
            lines.append(f"  {key}={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {args.interval}")
    if args.lookback_candles < 24:
        raise ValueError("--lookback-candles must be >= 24")
    if args.sample_step_hours <= 0:
        raise ValueError("--sample-step-hours must be > 0")

    out_dir = Path(args.output_dir)
    output_paths = OutputPaths(
        outcome_rows_jsonl=out_dir / OUTPUT_ROWS,
        outcome_summary_json=out_dir / OUTPUT_SUMMARY,
    )

    conn = get_connection()
    try:
        latest_ts = latest_asof_ts(conn, args.venue, args.interval)
        max_horizon_delta = timedelta(seconds=INTERVAL_SECONDS[args.interval] * MAX_FORWARD_HORIZON)
        default_to_ts = latest_ts - max_horizon_delta
        to_ts = parse_ts(args.to_ts) if args.to_ts else default_to_ts
        from_ts = parse_ts(args.from_ts) if args.from_ts else to_ts - timedelta(days=60)
        if from_ts > to_ts:
            raise ValueError("--from-ts must be <= --to-ts")

        assets = fetch_assets(conn)
        available = fetch_available_close_ts(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        asof_samples = select_asof_samples(
            available,
            from_ts=from_ts,
            to_ts=to_ts,
            sample_step_hours=args.sample_step_hours,
        )

        rows: list[dict[str, Any]] = []
        asset_counts: list[int] = []
        for asof_ts in asof_samples:
            asof_rows = build_outcome_rows_for_asof(
                conn,
                assets=assets,
                venue=args.venue,
                interval_code=args.interval,
                lookback_candles=args.lookback_candles,
                asof_ts=asof_ts,
            )
            rows.extend(asof_rows)
            asset_counts.append(len(asof_rows))
        conn.rollback()
    finally:
        conn.close()

    summary = build_summary(
        rows,
        venue=args.venue,
        interval_code=args.interval,
        from_ts=from_ts,
        to_ts=to_ts,
        sample_count=len(asof_samples),
        asset_counts=asset_counts,
        output_paths=output_paths,
        wrote_files=bool(args.write_files),
    )

    if args.write_files:
        write_jsonl(output_paths.outcome_rows_jsonl, rows)
        write_json(output_paths.outcome_summary_json, summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
