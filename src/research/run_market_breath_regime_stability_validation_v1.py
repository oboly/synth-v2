from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Callable

from src.common.db import get_connection
from src.research.run_market_breath_analysis_v1 import INTERVAL_SECONDS, PHASES, fmt_ts, latest_asof_ts, parse_ts
from src.research.run_market_breath_outcome_bucket_analysis_v1 import (
    btc_alignment_band,
    breadth_alignment_band,
    relative_strength_band,
)
from src.research.run_market_breath_outcome_validation_v1 import (
    MAX_FORWARD_HORIZON,
    build_outcome_rows_for_asof,
)
from src.research.run_market_breath_v1_1_calibration_audit import (
    SAFETY_MARKERS,
    avg,
    fetch_assets,
    fetch_available_close_ts,
    select_asof_samples,
)


REPORT_NAME = "market_breath_regime_stability_validation_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_DIR = "data/research/market_breath_regime_stability_validation_v1"
OUTPUT_WINDOWS = "window_summary_v1.jsonl"
OUTPUT_SUMMARY = "stability_summary_v1.json"

KEY_BUCKET_DIMENSIONS: list[tuple[str, str, Callable[[dict[str, Any]], str]]] = [
    ("COLLAPSE_RESET", "relative_strength_band", relative_strength_band),
    ("COLLAPSE_RESET", "btc_alignment_band", btc_alignment_band),
    ("COLLAPSE_RESET", "breadth_alignment_band", breadth_alignment_band),
    ("EXHALE_EXPANSION", "btc_alignment_band", btc_alignment_band),
    ("EXHALE_EXPANSION", "relative_strength_band", relative_strength_band),
    ("EXHALE_EXPANSION", "market_breath_state", lambda row: str(row["market_breath_state"])),
    ("OVERBREATH_EXTENSION", "phase", lambda row: str(row["market_breath_phase"])),
]


@dataclass(frozen=True)
class OutputPaths:
    window_summary_jsonl: Path
    stability_summary_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Market Breath regime stability validation over rolling windows "
            "(research-only, market-only, account-agnostic)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lookback-candles", type=int, default=120)
    parser.add_argument("--window-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=30)
    parser.add_argument("--history-days", type=int, default=180)
    parser.add_argument("--sample-step-hours", type=int, default=24)
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    return parser.parse_args(argv)


def values(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [
        float(row[field])
        for row in rows
        if row.get("outcome_available") and row.get(field) is not None
    ]


def median_or_none(items: list[float]) -> float | None:
    if not items:
        return None
    return round(float(median(items)), 6)


def positive_rate(items: list[float]) -> float | None:
    if not items:
        return None
    return round(sum(1 for item in items if item > 0.0) / len(items) * 100.0, 6)


def interpretation_hint(
    *,
    outcome_available_count: int,
    min_count: int,
    avg_24c: float | None,
    positive_rate_24c: float | None,
    neutral_avg_24c: float | None,
    neutral_positive_rate_24c: float | None,
) -> str:
    if outcome_available_count < min_count:
        return "LOW_SAMPLE"
    if (
        avg_24c is not None
        and positive_rate_24c is not None
        and neutral_avg_24c is not None
        and neutral_positive_rate_24c is not None
        and avg_24c >= neutral_avg_24c + 1.0
        and positive_rate_24c >= neutral_positive_rate_24c + 5.0
    ):
        return "OUTPERFORMS_BASELINE"
    if (
        avg_24c is not None
        and positive_rate_24c is not None
        and neutral_avg_24c is not None
        and neutral_positive_rate_24c is not None
        and avg_24c <= neutral_avg_24c - 1.0
        and positive_rate_24c <= neutral_positive_rate_24c - 5.0
    ):
        return "UNDERPERFORMS_BASELINE"
    return "MIXED_OR_FLAT"


def outcome_record(
    rows: list[dict[str, Any]],
    *,
    min_count: int,
    neutral_avg_24c: float | None,
    neutral_positive_rate_24c: float | None,
) -> dict[str, Any]:
    fwd24 = values(rows, "fwd_return_24c")
    avg_24c = avg(fwd24)
    pos_24c = positive_rate(fwd24)
    outcome_available_count = sum(1 for row in rows if row.get("outcome_available"))
    sample_status = "SUFFICIENT" if outcome_available_count >= min_count else "LOW_SAMPLE"
    return {
        "count": len(rows),
        "outcome_available_count": outcome_available_count,
        "avg_fwd_return_24c": avg_24c,
        "median_fwd_return_24c": median_or_none(fwd24),
        "positive_rate_24c": pos_24c,
        "avg_max_runup_24c": avg(values(rows, "max_runup_24c_from_asof_close")),
        "avg_max_drawdown_24c": avg(values(rows, "max_drawdown_24c_from_asof_close")),
        "vs_neutral_avg_fwd_return_24c": (
            round(avg_24c - neutral_avg_24c, 6)
            if avg_24c is not None and neutral_avg_24c is not None
            else None
        ),
        "vs_neutral_positive_rate_24c": (
            round(pos_24c - neutral_positive_rate_24c, 6)
            if pos_24c is not None and neutral_positive_rate_24c is not None
            else None
        ),
        "sample_status": sample_status,
        "interpretation_hint": interpretation_hint(
            outcome_available_count=outcome_available_count,
            min_count=min_count,
            avg_24c=avg_24c,
            positive_rate_24c=pos_24c,
            neutral_avg_24c=neutral_avg_24c,
            neutral_positive_rate_24c=neutral_positive_rate_24c,
        ),
    }


def build_windows(*, latest_usable_ts: datetime, history_days: int, window_days: int, step_days: int) -> list[tuple[datetime, datetime]]:
    history_start = latest_usable_ts - timedelta(days=history_days)
    windows: list[tuple[datetime, datetime]] = []
    current = history_start
    while current + timedelta(days=window_days) <= latest_usable_ts:
        windows.append((current, current + timedelta(days=window_days)))
        current += timedelta(days=step_days)
    return windows


def key_bucket_outcomes(
    rows: list[dict[str, Any]],
    *,
    min_count: int,
    neutral_avg_24c: float | None,
    neutral_positive_rate_24c: float | None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for phase, dimension, key_fn in KEY_BUCKET_DIMENSIONS:
        phase_rows = [row for row in rows if row["market_breath_phase"] == phase]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in phase_rows:
            grouped[key_fn(row)].append(row)
        for key, bucket_rows in sorted(grouped.items()):
            output.append(
                {
                    "market_breath_phase": phase,
                    "bucket_dimension": dimension,
                    "bucket_key": f"{phase}|{key}" if dimension != "phase" else phase,
                    **outcome_record(
                        bucket_rows,
                        min_count=min_count,
                        neutral_avg_24c=neutral_avg_24c,
                        neutral_positive_rate_24c=neutral_positive_rate_24c,
                    ),
                }
            )
    return output


def summarize_window(
    *,
    rows: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    sample_count: int,
    min_count: int,
) -> dict[str, Any]:
    by_phase: dict[str, list[dict[str, Any]]] = {
        phase: [row for row in rows if row["market_breath_phase"] == phase]
        for phase in PHASES
    }
    neutral_rows = by_phase["NEUTRAL_TRANSITION"]
    neutral_fwd24 = values(neutral_rows, "fwd_return_24c")
    neutral_baseline = {
        "avg_fwd_return_24c": avg(neutral_fwd24),
        "median_fwd_return_24c": median_or_none(neutral_fwd24),
        "positive_rate_24c": positive_rate(neutral_fwd24),
        "outcome_available_count": sum(1 for row in neutral_rows if row.get("outcome_available")),
    }
    phase_outcomes = {
        phase: outcome_record(
            phase_rows,
            min_count=min_count,
            neutral_avg_24c=neutral_baseline["avg_fwd_return_24c"],
            neutral_positive_rate_24c=neutral_baseline["positive_rate_24c"],
        )
        for phase, phase_rows in by_phase.items()
    }
    return {
        "window_start_ts": fmt_ts(window_start),
        "window_end_ts": fmt_ts(window_end),
        "sample_count": sample_count,
        "row_count": len(rows),
        "outcome_available_count": sum(1 for row in rows if row.get("outcome_available")),
        "neutral_baseline": neutral_baseline,
        "phase_outcomes": phase_outcomes,
        "key_bucket_outcomes": key_bucket_outcomes(
            rows,
            min_count=min_count,
            neutral_avg_24c=neutral_baseline["avg_fwd_return_24c"],
            neutral_positive_rate_24c=neutral_baseline["positive_rate_24c"],
        ),
    }


def stability_hint(windows_sufficient: int, outperforming: int, underperforming: int) -> str:
    if windows_sufficient < 2:
        return "LOW_SAMPLE"
    if outperforming / windows_sufficient >= 0.6:
        return "CONSISTENT_OUTPERFORMER"
    if underperforming / windows_sufficient >= 0.6:
        return "CONSISTENT_UNDERPERFORMER"
    return "MIXED"


def phase_stability(window_summaries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for phase in PHASES:
        records = [window["phase_outcomes"][phase] for window in window_summaries]
        sufficient = [record for record in records if record["sample_status"] == "SUFFICIENT"]
        outperforming = [record for record in sufficient if record["interpretation_hint"] == "OUTPERFORMS_BASELINE"]
        underperforming = [record for record in sufficient if record["interpretation_hint"] == "UNDERPERFORMS_BASELINE"]
        vs_avg = [
            float(record["vs_neutral_avg_fwd_return_24c"])
            for record in sufficient
            if record.get("vs_neutral_avg_fwd_return_24c") is not None
        ]
        vs_pos = [
            float(record["vs_neutral_positive_rate_24c"])
            for record in sufficient
            if record.get("vs_neutral_positive_rate_24c") is not None
        ]
        output[phase] = {
            "windows_sufficient": len(sufficient),
            "windows_outperforming_baseline": len(outperforming),
            "windows_underperforming_baseline": len(underperforming),
            "avg_vs_neutral_avg_fwd_return_24c": avg(vs_avg),
            "avg_vs_neutral_positive_rate_24c": avg(vs_pos),
            "stability_hint": stability_hint(len(sufficient), len(outperforming), len(underperforming)),
        }
    return output


def build_stability_summary(
    *,
    window_summaries: list[dict[str, Any]],
    venue: str,
    interval_code: str,
    history_days: int,
    window_days: int,
    step_days: int,
    min_count: int,
) -> dict[str, Any]:
    stability = phase_stability(window_summaries)
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "scope": "research-only market-only account-agnostic no-aplus no-pro no-symbolic-labels outcome-measurement-only",
        "venue": venue,
        "interval_code": interval_code,
        "history_days": history_days,
        "window_days": window_days,
        "step_days": step_days,
        "window_count": len(window_summaries),
        "min_count": min_count,
        "phase_stability": stability,
        "regime_dependency_assumption": (
            "Treat all Market Breath outcome behavior as regime-dependent. "
            "Stability hints describe repeated behavior across sampled rolling windows only; "
            "they are not claims of regime-independent behavior."
        ),
        "collapse_reset_stability_interpretation": (
            "COLLAPSE_RESET repeats in some favorable windows but remains regime-dependent; treat it as a research context candidate only."
            if stability["COLLAPSE_RESET"]["stability_hint"] == "CONSISTENT_OUTPERFORMER"
            else "COLLAPSE_RESET is mixed across rolling windows; treat any outperformance as regime-dependent."
        ),
        "exhale_expansion_stability_interpretation": (
            "EXHALE_EXPANSION repeatedly underperforms in sampled windows; treat it as a regime-dependent late-risk / exhaustion context candidate only."
            if stability["EXHALE_EXPANSION"]["stability_hint"] == "CONSISTENT_UNDERPERFORMER"
            else "EXHALE_EXPANSION is mixed across rolling windows; keep reviewing by regime before calibration decisions."
        ),
        "overbreath_extension_stability_interpretation": (
            "OVERBREATH_EXTENSION repeatedly underperforms in sufficient sampled windows; treat it as a regime-dependent late-risk / exhaustion context candidate only if manual review accepts the sample mass."
            if stability["OVERBREATH_EXTENSION"]["stability_hint"] == "CONSISTENT_UNDERPERFORMER"
            else "OVERBREATH_EXTENSION remains exploratory due mixed or low-sample rolling-window behavior."
        ),
        "threshold_calibration_status": "blocked; no threshold changes applied",
        "next_recommended_step": [
            "Manually review stability_summary_v1.json.",
            "Decide whether Market Breath should be documented as a state/risk-timing classifier.",
            "Review phase behavior by regime/window instead of searching for regime-independent stability.",
            "Keep threshold calibration blocked unless regime-specific findings indicate a measurement or reachability problem.",
            "Do not promote to runtime.",
        ],
        "no_threshold_changes_applied": True,
        "strategy_logic_added": False,
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
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
        "scope=research-only market-only account-agnostic no_aplus no_pro no_symbolic_labels no_strategy no_runtime",
        f"venue={summary['venue']} interval={summary['interval_code']}",
        (
            f"history_days={summary['history_days']} window_days={summary['window_days']} "
            f"step_days={summary['step_days']} window_count={summary['window_count']} min_count={summary['min_count']}"
        ),
        "",
        "--- rolling-window regime dependency ---",
    ]
    for phase in PHASES:
        item = summary["phase_stability"][phase]
        lines.append(
            "  "
            f"{phase} sufficient={item['windows_sufficient']} "
            f"outperform={item['windows_outperforming_baseline']} "
            f"underperform={item['windows_underperforming_baseline']} "
            f"avg_vs_neutral_24c={item['avg_vs_neutral_avg_fwd_return_24c']} "
            f"avg_vs_neutral_pos_rate={item['avg_vs_neutral_positive_rate_24c']} "
            f"hint={item['stability_hint']}"
        )
    lines.extend(
        [
            "",
            f"collapse_reset={summary['collapse_reset_stability_interpretation']}",
            f"exhale_expansion={summary['exhale_expansion_stability_interpretation']}",
            f"overbreath_extension={summary['overbreath_extension_stability_interpretation']}",
            f"threshold_calibration_status={summary['threshold_calibration_status']}",
            "[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {args.interval}")
    if args.lookback_candles < 24:
        raise ValueError("--lookback-candles must be >= 24")
    if args.window_days <= 0 or args.step_days <= 0 or args.history_days <= 0:
        raise ValueError("--history-days, --window-days, and --step-days must be > 0")
    if args.window_days > args.history_days:
        raise ValueError("--window-days must be <= --history-days")
    if args.sample_step_hours <= 0:
        raise ValueError("--sample-step-hours must be > 0")
    if args.min_count <= 0:
        raise ValueError("--min-count must be > 0")

    output_dir = Path(args.output_dir)
    output_paths = OutputPaths(
        window_summary_jsonl=output_dir / OUTPUT_WINDOWS,
        stability_summary_json=output_dir / OUTPUT_SUMMARY,
    )

    conn = get_connection()
    try:
        latest_ts = latest_asof_ts(conn, args.venue, args.interval)
        latest_usable_ts = latest_ts - timedelta(seconds=INTERVAL_SECONDS[args.interval] * MAX_FORWARD_HORIZON)
        windows = build_windows(
            latest_usable_ts=latest_usable_ts,
            history_days=args.history_days,
            window_days=args.window_days,
            step_days=args.step_days,
        )
        if not windows:
            raise RuntimeError("No rolling windows available for requested parameters.")

        assets = fetch_assets(conn)
        asof_cache: dict[datetime, list[dict[str, Any]]] = {}
        window_summaries: list[dict[str, Any]] = []
        for window_start, window_end in windows:
            available = fetch_available_close_ts(
                conn,
                venue=args.venue,
                interval_code=args.interval,
                from_ts=window_start,
                to_ts=window_end,
            )
            asof_samples = select_asof_samples(
                available,
                from_ts=window_start,
                to_ts=window_end,
                sample_step_hours=args.sample_step_hours,
            )
            rows: list[dict[str, Any]] = []
            for asof_ts in asof_samples:
                if asof_ts not in asof_cache:
                    asof_cache[asof_ts] = build_outcome_rows_for_asof(
                        conn,
                        assets=assets,
                        venue=args.venue,
                        interval_code=args.interval,
                        lookback_candles=args.lookback_candles,
                        asof_ts=asof_ts,
                    )
                rows.extend(asof_cache[asof_ts])
            window_summaries.append(
                summarize_window(
                    rows=rows,
                    window_start=window_start,
                    window_end=window_end,
                    sample_count=len(asof_samples),
                    min_count=args.min_count,
                )
            )
        conn.rollback()
    finally:
        conn.close()

    summary = build_stability_summary(
        window_summaries=window_summaries,
        venue=args.venue,
        interval_code=args.interval,
        history_days=args.history_days,
        window_days=args.window_days,
        step_days=args.step_days,
        min_count=args.min_count,
    )

    if args.write_files:
        write_jsonl(output_paths.window_summary_jsonl, window_summaries)
        write_json(output_paths.stability_summary_json, summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
