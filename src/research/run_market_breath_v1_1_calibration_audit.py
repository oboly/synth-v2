from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.run_market_breath_analysis_v1 import (
    INTERVAL_SECONDS,
    PHASES,
    STATES,
    add_breadth_and_scores,
    build_base_observation,
    fetch_assets,
    fetch_candles,
    fmt_ts,
    latest_asof_ts,
    parse_ts,
    safe_return,
    top_phase,
)


REPORT_NAME = "market_breath_v1_1_calibration_audit"
VERSION = "1.1"
DEFAULT_OUTPUT_DIR = "data/research/market_breath_v1_1_calibration_audit"
OUTPUT_ROWS = "phase_distribution_by_asof_v1.jsonl"
OUTPUT_SUMMARY = "calibration_summary_v1.json"

PHASE_KEY_TO_PCT_FIELD = {
    "COLLAPSE_RESET": "collapse_reset_pct",
    "NEUTRAL_TRANSITION": "neutral_transition_pct",
    "INHALE_ACCUMULATION": "inhale_accumulation_pct",
    "HOLD_COMPRESSION": "hold_compression_pct",
    "EXHALE_EXPANSION": "exhale_expansion_pct",
    "OVERBREATH_EXTENSION": "overbreath_extension_pct",
    "INSUFFICIENT_DATA": "insufficient_data_pct",
}

SAFETY_MARKERS = {
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "db_writes": 0,
    "selection_engine_changes": 0,
    "advice_engine_changes": 0,
    "decision_gate_changes": 0,
    "execution_planner_changes": 0,
    "executor_changes": 0,
}

NEUTRAL_STRUCTURALLY_DOMINANT_PCT = 75.0
HOLD_SPARSE_PCT = 0.5
HOLD_ZERO_DAY_RATIO = 0.9
INHALE_SPARSE_PCT = 1.0
OVERBREATH_SPARSE_PCT = 1.5
COLLAPSE_NOT_DOMINANT_PCT = 10.0


@dataclass(frozen=True)
class OutputPaths:
    phase_distribution_jsonl: Path
    calibration_summary_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Market Breath V1.1 calibration audit over historical as-of windows "
            "(research-only, market-only, account-agnostic)."
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


def floor_to_utc_midnight(value: datetime) -> datetime:
    return datetime(value.year, value.month, value.day)


def ensure_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total * 100.0, 6)


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def avg_field(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return avg(values)


def phase_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    raw = Counter(row["market_breath_phase"] for row in rows)
    return {phase: raw.get(phase, 0) for phase in PHASES}


def state_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    raw = Counter(row["market_breath_state"] for row in rows)
    return {state: raw.get(state, 0) for state in STATES}


def top_symbols(rows: list[dict[str, Any]], phase: str, top_n: int = 8) -> list[str]:
    return [str(item["symbol"]) for item in top_phase(rows, phase, top_n=top_n)]


def fetch_available_close_ts(
    conn,
    *,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
) -> list[datetime]:
    sql = """
        SELECT DISTINCT close_ts_utc
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
        ORDER BY close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, from_ts, to_ts))
        rows = cur.fetchall()
    return [ensure_naive_utc(row["close_ts_utc"]) for row in rows]


def build_sample_targets(from_ts: datetime, to_ts: datetime, sample_step_hours: int) -> list[datetime]:
    if sample_step_hours <= 0:
        raise ValueError("--sample-step-hours must be > 0")

    if sample_step_hours == 24:
        current = floor_to_utc_midnight(from_ts)
        if current < from_ts:
            current += timedelta(days=1)
    else:
        current = from_ts

    targets: list[datetime] = []
    step = timedelta(hours=sample_step_hours)
    while current <= to_ts:
        targets.append(current)
        current += step
    return targets


def nearest_available_close(target: datetime, available: list[datetime]) -> datetime | None:
    if not available:
        return None
    return min(available, key=lambda close_ts: (abs(close_ts - target), close_ts))


def select_asof_samples(
    available: list[datetime],
    *,
    from_ts: datetime,
    to_ts: datetime,
    sample_step_hours: int,
) -> list[datetime]:
    targets = build_sample_targets(from_ts, to_ts, sample_step_hours)
    selected: list[datetime] = []
    seen: set[datetime] = set()
    for target in targets:
        nearest = nearest_available_close(target, available)
        if nearest is None:
            continue
        if nearest < from_ts or nearest > to_ts or nearest in seen:
            continue
        seen.add(nearest)
        selected.append(nearest)
    return selected


def build_rows_for_asof(
    conn,
    *,
    assets: list[Any],
    venue: str,
    interval_code: str,
    lookback_candles: int,
    asof_ts: datetime,
) -> list[dict[str, Any]]:
    candles_by_asset = fetch_candles(
        conn,
        assets=assets,
        venue=venue,
        interval_code=interval_code,
        asof_ts=asof_ts,
        lookback_candles=lookback_candles,
    )

    btc_asset = next((asset for asset in assets if asset.symbol == "BTC"), None)
    btc_candles = candles_by_asset.get(btc_asset.asset_id, []) if btc_asset else []
    btc_r6 = safe_return(btc_candles, 6) if btc_candles else None
    btc_r12 = safe_return(btc_candles, 12) if btc_candles else None

    base_rows = [
        build_base_observation(
            asset=asset,
            candles=candles_by_asset.get(asset.asset_id, []),
            venue=venue,
            interval_code=interval_code,
            lookback_candles=lookback_candles,
            asof_ts=asof_ts,
            btc_r6=btc_r6,
            btc_r12=btc_r12,
        )
        for asset in assets
    ]
    return add_breadth_and_scores(base_rows, lookback_candles)


def per_asof_record(rows: list[dict[str, Any]], *, venue: str, interval_code: str, asof_ts: datetime) -> dict[str, Any]:
    counts = phase_counts(rows)
    states = state_counts(rows)
    total = len(rows)
    record = {
        "venue": venue,
        "interval_code": interval_code,
        "asof_ts_utc": fmt_ts(asof_ts),
        "assets_processed": total,
        "phase_counts": counts,
        "state_counts": states,
        "avg_compression_score": avg_field(rows, "compression_score"),
        "avg_expansion_score": avg_field(rows, "expansion_score"),
        "avg_momentum_score": avg_field(rows, "momentum_score"),
        "avg_reversal_pressure_score": avg_field(rows, "reversal_pressure_score"),
        "avg_relative_strength_score": avg_field(rows, "relative_strength_score"),
        "avg_btc_alignment_score": avg_field(rows, "btc_alignment_score"),
        "avg_breadth_alignment_score": avg_field(rows, "breadth_alignment_score"),
        "avg_market_breath_confidence": avg_field(rows, "market_breath_confidence"),
        "top_collapse_reset_symbols": top_symbols(rows, "COLLAPSE_RESET"),
        "top_neutral_transition_symbols": top_symbols(rows, "NEUTRAL_TRANSITION"),
        "top_exhale_expansion_symbols": top_symbols(rows, "EXHALE_EXPANSION"),
        "top_inhale_accumulation_symbols": top_symbols(rows, "INHALE_ACCUMULATION"),
        "top_hold_compression_symbols": top_symbols(rows, "HOLD_COMPRESSION"),
        "top_overbreath_extension_symbols": top_symbols(rows, "OVERBREATH_EXTENSION"),
    }
    for phase, field in PHASE_KEY_TO_PCT_FIELD.items():
        record[field] = pct(counts[phase], total)
    return record


def aggregate_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    aggregate: Counter[str] = Counter()
    for record in records:
        aggregate.update(record["phase_counts"])
    return {phase: int(aggregate.get(phase, 0)) for phase in PHASES}


def most_common_phase(record: dict[str, Any]) -> str:
    counts = record["phase_counts"]
    return max(PHASES, key=lambda phase: (counts.get(phase, 0), -PHASES.index(phase)))


def detect_threshold_issues(records: list[dict[str, Any]], aggregate_percentages: dict[str, float]) -> list[str]:
    if not records:
        return ["NO_SAMPLES_AVAILABLE"]

    sample_count = len(records)
    issues: list[str] = []
    aggregate_counts_by_phase = aggregate_counts(records)
    collapse_dominant_days = sum(1 for record in records if record["collapse_reset_pct"] > 50.0)
    hold_zero_days = sum(1 for record in records if record["phase_counts"]["HOLD_COMPRESSION"] == 0)

    if (
        aggregate_percentages["COLLAPSE_RESET"] < COLLAPSE_NOT_DOMINANT_PCT
        and collapse_dominant_days <= 1
    ):
        issues.append("COLLAPSE_RESET not structurally dominant")
    else:
        issues.append("COLLAPSE_RESET needs review for dominance")

    if aggregate_percentages["NEUTRAL_TRANSITION"] > NEUTRAL_STRUCTURALLY_DOMINANT_PCT:
        issues.append("NEUTRAL_TRANSITION structurally dominant")

    if (
        aggregate_percentages["HOLD_COMPRESSION"] < HOLD_SPARSE_PCT
        or hold_zero_days / sample_count > HOLD_ZERO_DAY_RATIO
    ):
        issues.append("HOLD_COMPRESSION sparse / near-unreachable")

    if (
        aggregate_percentages["INHALE_ACCUMULATION"] < INHALE_SPARSE_PCT
        and aggregate_counts_by_phase["INHALE_ACCUMULATION"] > 0
    ):
        issues.append("INHALE_ACCUMULATION sparse but reachable")
    elif aggregate_counts_by_phase["INHALE_ACCUMULATION"] == 0:
        issues.append("INHALE_ACCUMULATION near-unreachable")

    if (
        aggregate_percentages["OVERBREATH_EXTENSION"] < OVERBREATH_SPARSE_PCT
        and aggregate_counts_by_phase["OVERBREATH_EXTENSION"] > 0
    ):
        issues.append("OVERBREATH_EXTENSION sparse but reachable")
    elif aggregate_counts_by_phase["OVERBREATH_EXTENSION"] == 0:
        issues.append("OVERBREATH_EXTENSION near-unreachable")

    if aggregate_counts_by_phase["EXHALE_EXPANSION"] > 0:
        issues.append("EXHALE_EXPANSION present; validate later if sample count is sufficient")
    else:
        issues.append("EXHALE_EXPANSION absent; review reachability before validation")

    issues.append("No Market Breath V1 threshold changes applied")
    if not issues:
        issues.append("No calibration diagnostics available")
    return issues


def calibration_recommendations(issues: list[str]) -> list[str]:
    recommendations = ["Do not change Market Breath V1 thresholds in this lane."]
    if "NO_SAMPLES_AVAILABLE" in issues:
        recommendations.append("Run the audit against a DB with obs_market_candle history before interpreting thresholds.")
        return recommendations
    recommendations.append("Treat sparse phase diagnostics as audit interpretation only, not strategy rules.")
    if "NEUTRAL_TRANSITION structurally dominant" in issues:
        recommendations.append("Use later validation to determine whether neutral dominance is acceptable before any promotion.")
    if "HOLD_COMPRESSION sparse / near-unreachable" in issues:
        recommendations.append("Record HOLD_COMPRESSION as sparse under current V1 thresholds; rarity alone is not evidence of wrong thresholds.")
    if "INHALE_ACCUMULATION sparse but reachable" in issues:
        recommendations.append("Record INHALE_ACCUMULATION as selective but reachable.")
    if "OVERBREATH_EXTENSION sparse but reachable" in issues:
        recommendations.append("Record OVERBREATH_EXTENSION as selective but reachable.")
    if "EXHALE_EXPANSION present; validate later if sample count is sufficient" in issues:
        recommendations.append("Keep EXHALE_EXPANSION available for later outcome validation when sample count is sufficient.")
    return recommendations


def build_summary(
    records: list[dict[str, Any]],
    *,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
    output_paths: OutputPaths,
    wrote_files: bool,
) -> dict[str, Any]:
    sample_count = len(records)
    assets_per_sample = [int(record["assets_processed"]) for record in records]
    aggregate = aggregate_counts(records)
    aggregate_total = sum(aggregate.values())
    aggregate_percentages = {phase: pct(count, aggregate_total) for phase, count in aggregate.items()}
    phase_by_day = Counter(most_common_phase(record) for record in records)
    issues = detect_threshold_issues(records, aggregate_percentages)

    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "scope": "research-only market-only account-agnostic no-aplus no-external-labels no-outcomes",
        "venue": venue,
        "interval_code": interval_code,
        "from_ts": fmt_ts(from_ts),
        "to_ts": fmt_ts(to_ts),
        "sample_count": sample_count,
        "assets_per_sample_avg": avg([float(v) for v in assets_per_sample]),
        "assets_per_sample_min": min(assets_per_sample) if assets_per_sample else 0,
        "assets_per_sample_max": max(assets_per_sample) if assets_per_sample else 0,
        "aggregate_phase_counts": aggregate,
        "aggregate_phase_percentages": aggregate_percentages,
        "days_with_zero_inhale": sum(1 for record in records if record["phase_counts"]["INHALE_ACCUMULATION"] == 0),
        "days_with_zero_hold": sum(1 for record in records if record["phase_counts"]["HOLD_COMPRESSION"] == 0),
        "days_with_zero_overbreath": sum(1 for record in records if record["phase_counts"]["OVERBREATH_EXTENSION"] == 0),
        "days_with_zero_exhale": sum(1 for record in records if record["phase_counts"]["EXHALE_EXPANSION"] == 0),
        "days_with_collapse_reset_gt_50pct": sum(1 for record in records if record["collapse_reset_pct"] > 50.0),
        "most_common_phase_per_day": {phase: phase_by_day.get(phase, 0) for phase in PHASES},
        "suspected_threshold_issues": issues,
        "calibration_recommendations": calibration_recommendations(issues),
        "no_threshold_changes_applied": True,
        "outcome_validation_allowed": False,
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
        "output_paths": {
            "phase_distribution_jsonl": str(output_paths.phase_distribution_jsonl),
            "calibration_summary_json": str(output_paths.calibration_summary_json),
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


def render_table(summary: dict[str, Any], records: list[dict[str, Any]]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only account-agnostic no_aplus no_external_labels no_outcomes",
        "input=obs_market_candle asset existing_market_breath_v1_logic",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none",
        f"venue={summary['venue']} interval={summary['interval_code']}",
        f"from_ts={summary['from_ts']} to_ts={summary['to_ts']} sample_count={summary['sample_count']}",
        (
            "assets_per_sample "
            f"avg={summary['assets_per_sample_avg']} "
            f"min={summary['assets_per_sample_min']} max={summary['assets_per_sample_max']}"
        ),
        "",
        "--- aggregate phase percentages ---",
    ]
    for phase in PHASES:
        lines.append(
            f"  {phase}={summary['aggregate_phase_counts'][phase]} "
            f"({summary['aggregate_phase_percentages'][phase]}%)"
        )
    lines.extend(
        [
            "",
            "--- zero / dominance diagnostics ---",
            f"  days_with_collapse_reset_gt_50pct={summary['days_with_collapse_reset_gt_50pct']}",
            f"  days_with_zero_inhale={summary['days_with_zero_inhale']}",
            f"  days_with_zero_hold={summary['days_with_zero_hold']}",
            f"  days_with_zero_overbreath={summary['days_with_zero_overbreath']}",
            f"  days_with_zero_exhale={summary['days_with_zero_exhale']}",
            "",
            "--- suspected threshold issues ---",
        ]
    )
    lines.extend(f"  {issue}" for issue in summary["suspected_threshold_issues"])
    lines.extend(["", "--- recommendations ---"])
    lines.extend(f"  {item}" for item in summary["calibration_recommendations"])
    lines.extend(["", "--- recent per-asof distribution preview ---"])
    for record in records[-10:]:
        lines.append(
            "  "
            f"{record['asof_ts_utc']} "
            f"collapse={record['collapse_reset_pct']}% "
            f"neutral={record['neutral_transition_pct']}% "
            f"inhale={record['inhale_accumulation_pct']}% "
            f"hold={record['hold_compression_pct']}% "
            f"exhale={record['exhale_expansion_pct']}% "
            f"overbreath={record['overbreath_extension_pct']}%"
        )
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
        phase_distribution_jsonl=out_dir / OUTPUT_ROWS,
        calibration_summary_json=out_dir / OUTPUT_SUMMARY,
    )

    conn = get_connection()
    try:
        to_ts = parse_ts(args.to_ts) if args.to_ts else latest_asof_ts(conn, args.venue, args.interval)
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

        records: list[dict[str, Any]] = []
        for asof_ts in asof_samples:
            rows = build_rows_for_asof(
                conn,
                assets=assets,
                venue=args.venue,
                interval_code=args.interval,
                lookback_candles=args.lookback_candles,
                asof_ts=asof_ts,
            )
            records.append(per_asof_record(rows, venue=args.venue, interval_code=args.interval, asof_ts=asof_ts))
        conn.rollback()
    finally:
        conn.close()

    summary = build_summary(
        records,
        venue=args.venue,
        interval_code=args.interval,
        from_ts=from_ts,
        to_ts=to_ts,
        output_paths=output_paths,
        wrote_files=bool(args.write_files),
    )

    if args.write_files:
        write_jsonl(output_paths.phase_distribution_jsonl, records)
        write_json(output_paths.calibration_summary_json, summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(summary, records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
