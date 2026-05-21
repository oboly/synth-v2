from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection
from src.research.run_market_breath_analysis_v1 import (
    INTERVAL_SECONDS,
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


REPORT_NAME = "overbreath_by_regime_backtest_v1"
VERSION = "0.1"
DEFAULT_OUTPUT_DIR = "data/research/overbreath_by_regime_backtest_v1"

REGIME_BUCKETS = [
    "SIDEWAYS_MARKET",
    "BULL_MARKET",
    "BEAR_MARKET",
    "CRASH_MARKET",
    "SUPER_BULL_MARKET",
    "LIQUIDITY_ROTATION",
]

DEFAULT_EVENT_PHASES = ["OVERBREATH_EXTENSION"]
FORWARD_DAYS = [1, 3, 5, 10, 21]
MAX_FORWARD_DAYS = max(FORWARD_DAYS)

POLICY_FIELDS = {
    "reduce_immediately": "policy_reduce_immediately_return_21d",
    "partial_reduce_trail": "policy_partial_reduce_trail_return_21d",
    "hold_bull_super_bull": "policy_hold_bull_super_bull_return_21d",
    "wait_breakdown_confirmation": "policy_wait_breakdown_confirmation_return_21d",
    "short_term_breath_exit": "policy_short_term_breath_exit_return_3d",
    "long_term_fibo_hold": "policy_long_term_fibo_hold_return_21d",
    "bucket_50_50": "policy_50_long_term_50_short_term_return",
}

EVENT_TABLE_FIELDS = [
    "venue",
    "interval_code",
    "asof_ts_utc",
    "asset_id",
    "symbol",
    "macro_regime",
    "regime_classifier",
    "market_breath_phase",
    "market_breath_state",
    "market_breath_score",
    "market_breath_confidence",
    "close_price",
    "btc_return_10d_pct",
    "btc_return_30d_pct",
    "btc_return_60d_pct",
    "btc_drawdown_from_60d_high_pct",
    "positive_participation_pct",
    "alt_relative_strength_avg",
    "volatility_spike",
    "momentum_score",
    "relative_strength_score",
    "btc_alignment_score",
    "breadth_alignment_score",
    "fwd_return_1d_pct",
    "fwd_return_3d_pct",
    "fwd_return_5d_pct",
    "fwd_return_10d_pct",
    "fwd_return_21d_pct",
    "max_favorable_excursion_21d_pct",
    "max_adverse_excursion_21d_pct",
    "drawdown_before_continuation_pct",
    "continuation_10d",
    "continuation_21d",
    "sharp_reversal_5d",
    "outcome_available",
    *POLICY_FIELDS.values(),
]

SUMMARY_TABLE_FIELDS = [
    "macro_regime",
    "event_count",
    "outcome_available_count",
    "continuation_probability_10d_pct",
    "continuation_probability_21d_pct",
    "sharp_reversal_probability_pct",
    *[f"avg_fwd_return_{day}d_pct" for day in FORWARD_DAYS],
    *[f"median_fwd_return_{day}d_pct" for day in FORWARD_DAYS],
    "avg_mfe_21d_pct",
    "avg_mae_21d_pct",
    "avg_drawdown_before_continuation_pct",
    *[f"avg_{field}" for field in POLICY_FIELDS.values()],
]


@dataclass(frozen=True)
class OutputPaths:
    event_table_csv: Path
    event_table_jsonl: Path
    summary_by_regime_csv: Path
    summary_by_regime_json: Path
    report_md: Path
    manifest_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backtest Market Breath OVERBREATH_EXTENSION outcomes by provisional macro regime "
            "(research-only, market-only, account-agnostic, file-output only)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lookback-candles", type=int, default=120)
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--sample-step-hours", type=int, default=24)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--event-phases", nargs="*", default=DEFAULT_EVENT_PHASES)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def output_paths(output_dir: str) -> OutputPaths:
    root = Path(output_dir)
    return OutputPaths(
        event_table_csv=root / "event_table_v1.csv",
        event_table_jsonl=root / "event_table_v1.jsonl",
        summary_by_regime_csv=root / "summary_by_regime_v1.csv",
        summary_by_regime_json=root / "summary_by_regime_v1.json",
        report_md=root / "overbreath_by_regime_backtest_v1.md",
        manifest_json=root / "manifest_v1.json",
    )


def normalize_symbols(symbols: list[str] | None) -> set[str] | None:
    if not symbols:
        return None
    cleaned = {symbol.strip().upper() for symbol in symbols if symbol.strip()}
    return cleaned or None


def decimal_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return round((end / start - 1.0) * 100.0, 6)


def interval_candles_for_days(interval_code: str, days: int) -> int:
    interval_seconds = INTERVAL_SECONDS[interval_code]
    return max(1, int(round(days * 86400 / interval_seconds)))


def fetch_future_ohlc_for_asof(
    conn: Any,
    *,
    asset_ids: list[int],
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    max_forward_candles: int,
) -> dict[int, list[dict[str, Any]]]:
    if not asset_ids:
        return {}
    horizon_end = asof_ts + timedelta(seconds=INTERVAL_SECONDS[interval_code] * max_forward_candles)
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT
            asset_id,
            close_ts_utc,
            high_price,
            low_price,
            close_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc > %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, interval_code, asof_ts, horizon_end, *asset_ids])
        rows = cur.fetchall()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["asset_id"])].append(
            {
                "close_ts_utc": row["close_ts_utc"],
                "high_price": decimal_to_float(row.get("high_price")),
                "low_price": decimal_to_float(row.get("low_price")),
                "close_price": decimal_to_float(row.get("close_price")),
            }
        )
    return dict(grouped)


def fetch_asset_candles_until(
    conn: Any,
    *,
    asset_id: int,
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    sql = """
        SELECT close_ts_utc, high_price, low_price, close_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND asset_id = %s
          AND close_ts_utc <= %s
        ORDER BY close_ts_utc DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, asset_id, asof_ts, int(limit)))
        rows = list(cur.fetchall())
    rows.reverse()
    return [
        {
            "close_ts_utc": row["close_ts_utc"],
            "high_price": decimal_to_float(row.get("high_price")),
            "low_price": decimal_to_float(row.get("low_price")),
            "close_price": decimal_to_float(row.get("close_price")),
        }
        for row in rows
    ]


def value_n_from_end(candles: list[dict[str, Any]], periods: int, field: str = "close_price") -> float | None:
    if len(candles) <= periods:
        return None
    return decimal_to_float(candles[-periods - 1].get(field))


def current_close(candles: list[dict[str, Any]]) -> float | None:
    if not candles:
        return None
    return decimal_to_float(candles[-1].get("close_price"))


def median_or_none(values: list[float]) -> float | None:
    return None if not values else round(float(median(values)), 6)


def classify_provisional_macro_regime(
    *,
    interval_code: str,
    btc_candles: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    close = current_close(btc_candles)
    c10 = interval_candles_for_days(interval_code, 10)
    c30 = interval_candles_for_days(interval_code, 30)
    c60 = interval_candles_for_days(interval_code, 60)

    btc_10d = pct_return(value_n_from_end(btc_candles, c10), close)
    btc_30d = pct_return(value_n_from_end(btc_candles, c30), close)
    btc_60d = pct_return(value_n_from_end(btc_candles, c60), close)
    recent_highs = [candle["high_price"] for candle in btc_candles[-c60:] if candle.get("high_price") is not None]
    recent_high = max(recent_highs) if recent_highs else None
    btc_drawdown = pct_return(recent_high, close) if recent_high else None

    participation_values = [
        row.get("return_12")
        for row in market_rows
        if row.get("return_12") is not None and row.get("market_breath_phase") != "INSUFFICIENT_DATA"
    ]
    positive_participation_pct = (
        round(sum(1 for value in participation_values if float(value) > 0.0) / len(participation_values) * 100.0, 6)
        if participation_values
        else None
    )
    alt_relative_strength_values = [
        float(row["relative_strength_score"])
        for row in market_rows
        if row.get("relative_strength_score") is not None and str(row.get("symbol") or "").upper() not in {"BTC", "ETH"}
    ]
    alt_relative_strength_avg = avg(alt_relative_strength_values)

    ranges = [
        None
        if candle.get("high_price") is None or candle.get("low_price") is None or candle.get("close_price") in {None, 0}
        else (float(candle["high_price"]) / float(candle["low_price"]) - 1.0) * 100.0
        for candle in btc_candles[-c30:]
    ]
    ranges = [value for value in ranges if value is not None]
    current_ranges = ranges[-interval_candles_for_days(interval_code, 3) :] if ranges else []
    volatility_spike = bool(ranges and current_ranges and avg(current_ranges) is not None and avg(current_ranges) > (median(ranges) * 1.8))

    regime = "SIDEWAYS_MARKET"
    if (btc_30d is not None and btc_30d <= -25.0) or (btc_drawdown is not None and btc_drawdown <= -35.0):
        regime = "CRASH_MARKET"
    elif volatility_spike and btc_10d is not None and btc_10d <= -15.0:
        regime = "CRASH_MARKET"
    elif (
        (btc_60d is not None and btc_60d <= -20.0)
        or (btc_drawdown is not None and btc_drawdown <= -25.0 and (positive_participation_pct or 0.0) < 40.0)
    ):
        regime = "BEAR_MARKET"
    elif (
        btc_30d is not None
        and btc_60d is not None
        and positive_participation_pct is not None
        and btc_30d >= 25.0
        and btc_60d >= 35.0
        and positive_participation_pct >= 60.0
    ):
        regime = "SUPER_BULL_MARKET"
    elif (
        btc_30d is not None
        and btc_60d is not None
        and positive_participation_pct is not None
        and btc_30d >= 8.0
        and btc_60d >= 10.0
        and positive_participation_pct >= 50.0
    ):
        regime = "BULL_MARKET"
    elif (
        btc_30d is not None
        and positive_participation_pct is not None
        and alt_relative_strength_avg is not None
        and -10.0 <= btc_30d <= 15.0
        and positive_participation_pct >= 55.0
        and alt_relative_strength_avg >= 15.0
    ):
        regime = "LIQUIDITY_ROTATION"

    return {
        "macro_regime": regime,
        "regime_classifier": "PROVISIONAL_RESEARCH_ONLY",
        "btc_return_10d_pct": btc_10d,
        "btc_return_30d_pct": btc_30d,
        "btc_return_60d_pct": btc_60d,
        "btc_drawdown_from_60d_high_pct": btc_drawdown,
        "positive_participation_pct": positive_participation_pct,
        "alt_relative_strength_avg": alt_relative_strength_avg,
        "volatility_spike": volatility_spike,
    }


def outcome_metrics(
    *,
    asof_close: float | None,
    future_candles: list[dict[str, Any]],
    interval_code: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for day in FORWARD_DAYS:
        horizon = interval_candles_for_days(interval_code, day)
        future_close = future_candles[horizon - 1]["close_price"] if len(future_candles) >= horizon else None
        out[f"fwd_return_{day}d_pct"] = pct_return(asof_close, future_close)

    max_horizon = interval_candles_for_days(interval_code, MAX_FORWARD_DAYS)
    horizon_candles = future_candles[:max_horizon]
    highs = [candle["high_price"] for candle in horizon_candles if candle.get("high_price") is not None]
    lows = [candle["low_price"] for candle in horizon_candles if candle.get("low_price") is not None]
    max_high = max(highs) if highs else None
    min_low = min(lows) if lows else None
    out["max_favorable_excursion_21d_pct"] = pct_return(asof_close, max_high)
    out["max_adverse_excursion_21d_pct"] = pct_return(asof_close, min_low)

    close_returns = [pct_return(asof_close, candle.get("close_price")) for candle in horizon_candles]
    close_returns = [value for value in close_returns if value is not None]
    if close_returns:
        max_idx = max(range(len(close_returns)), key=lambda idx: close_returns[idx])
        out["drawdown_before_continuation_pct"] = round(min(close_returns[: max_idx + 1]), 6)
    else:
        out["drawdown_before_continuation_pct"] = None

    out["continuation_10d"] = bool(out.get("fwd_return_10d_pct") is not None and out["fwd_return_10d_pct"] > 0.0)
    out["continuation_21d"] = bool(out.get("fwd_return_21d_pct") is not None and out["fwd_return_21d_pct"] > 0.0)
    out["sharp_reversal_5d"] = bool(
        out.get("max_adverse_excursion_21d_pct") is not None
        and out["max_adverse_excursion_21d_pct"] <= -7.5
        and out.get("fwd_return_5d_pct") is not None
        and out["fwd_return_5d_pct"] < 0.0
    )
    out["outcome_available"] = len(future_candles) >= max_horizon and out.get("fwd_return_21d_pct") is not None
    return out


def policy_returns(metrics: dict[str, Any], regime: str) -> dict[str, float | None]:
    fwd3 = metrics.get("fwd_return_3d_pct")
    fwd5 = metrics.get("fwd_return_5d_pct")
    fwd21 = metrics.get("fwd_return_21d_pct")
    mae = metrics.get("max_adverse_excursion_21d_pct")
    if fwd21 is None:
        return {field: None for field in POLICY_FIELDS.values()}

    wait_breakdown = fwd21
    if mae is not None and mae <= -5.0 and fwd5 is not None:
        wait_breakdown = fwd5

    return {
        "policy_reduce_immediately_return_21d": 0.0,
        "policy_partial_reduce_trail_return_21d": round(fwd21 * 0.5, 6),
        "policy_hold_bull_super_bull_return_21d": fwd21 if regime in {"BULL_MARKET", "SUPER_BULL_MARKET"} else 0.0,
        "policy_wait_breakdown_confirmation_return_21d": wait_breakdown,
        "policy_short_term_breath_exit_return_3d": fwd3,
        "policy_long_term_fibo_hold_return_21d": fwd21,
        "policy_50_long_term_50_short_term_return": None if fwd3 is None else round((fwd21 * 0.5) + (fwd3 * 0.5), 6),
    }


def build_event_row(
    row: dict[str, Any],
    *,
    regime: dict[str, Any],
    future_candles: list[dict[str, Any]],
    interval_code: str,
) -> dict[str, Any]:
    asof_close = decimal_to_float(row.get("close_price"))
    metrics = outcome_metrics(asof_close=asof_close, future_candles=future_candles, interval_code=interval_code)
    policies = policy_returns(metrics, str(regime["macro_regime"]))
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
        "momentum_score": row["momentum_score"],
        "relative_strength_score": row["relative_strength_score"],
        "btc_alignment_score": row["btc_alignment_score"],
        "breadth_alignment_score": row["breadth_alignment_score"],
        "close_price": asof_close,
        **regime,
        **metrics,
        **policies,
    }


def event_rows_for_asof(
    conn: Any,
    *,
    assets: list[Any],
    btc_asset_id: int,
    venue: str,
    interval_code: str,
    lookback_candles: int,
    asof_ts: datetime,
    event_phases: set[str],
) -> list[dict[str, Any]]:
    market_rows = build_rows_for_asof(
        conn,
        assets=assets,
        venue=venue,
        interval_code=interval_code,
        lookback_candles=lookback_candles,
        asof_ts=asof_ts,
    )
    btc_candles = fetch_asset_candles_until(
        conn,
        asset_id=btc_asset_id,
        venue=venue,
        interval_code=interval_code,
        asof_ts=asof_ts,
        limit=max(interval_candles_for_days(interval_code, 70), lookback_candles),
    )
    regime = classify_provisional_macro_regime(
        interval_code=interval_code,
        btc_candles=btc_candles,
        market_rows=market_rows,
    )
    event_base_rows = [row for row in market_rows if str(row.get("market_breath_phase") or "").upper() in event_phases]
    future_by_asset = fetch_future_ohlc_for_asof(
        conn,
        asset_ids=[int(row["asset_id"]) for row in event_base_rows],
        venue=venue,
        interval_code=interval_code,
        asof_ts=asof_ts,
        max_forward_candles=interval_candles_for_days(interval_code, MAX_FORWARD_DAYS),
    )
    return [
        build_event_row(
            row,
            regime=regime,
            future_candles=future_by_asset.get(int(row["asset_id"]), []),
            interval_code=interval_code,
        )
        for row in event_base_rows
    ]


def non_null_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [float(row[field]) for row in rows if row.get(field) is not None]


def rate(rows: list[dict[str, Any]], field: str) -> float | None:
    eligible = [row for row in rows if row.get("outcome_available")]
    if not eligible:
        return None
    return round(sum(1 for row in eligible if row.get(field)) / len(eligible) * 100.0, 6)


def summarize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for regime in REGIME_BUCKETS:
        regime_rows = [row for row in rows if row.get("macro_regime") == regime]
        available = [row for row in regime_rows if row.get("outcome_available")]
        item: dict[str, Any] = {
            "macro_regime": regime,
            "event_count": len(regime_rows),
            "outcome_available_count": len(available),
            "continuation_probability_10d_pct": rate(regime_rows, "continuation_10d"),
            "continuation_probability_21d_pct": rate(regime_rows, "continuation_21d"),
            "sharp_reversal_probability_pct": rate(regime_rows, "sharp_reversal_5d"),
        }
        for day in FORWARD_DAYS:
            item[f"avg_fwd_return_{day}d_pct"] = avg(non_null_values(available, f"fwd_return_{day}d_pct"))
            item[f"median_fwd_return_{day}d_pct"] = median_or_none(non_null_values(available, f"fwd_return_{day}d_pct"))
        item["avg_mfe_21d_pct"] = avg(non_null_values(available, "max_favorable_excursion_21d_pct"))
        item["avg_mae_21d_pct"] = avg(non_null_values(available, "max_adverse_excursion_21d_pct"))
        item["avg_drawdown_before_continuation_pct"] = avg(non_null_values(available, "drawdown_before_continuation_pct"))
        for field in POLICY_FIELDS.values():
            item[f"avg_{field}"] = avg(non_null_values(available, field))
        summary.append(item)
    return summary


def build_manifest(
    *,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
    sample_count: int,
    event_phases: list[str],
    rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    paths: OutputPaths,
    wrote_files: bool,
) -> dict[str, Any]:
    regime_counts = Counter(row.get("macro_regime") for row in rows)
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "scope": "research-only market-only account-agnostic file-output-only",
        "venue": venue,
        "interval_code": interval_code,
        "from_ts_utc": fmt_ts(from_ts),
        "to_ts_utc": fmt_ts(to_ts),
        "sample_count": sample_count,
        "event_phases": event_phases,
        "event_count": len(rows),
        "outcome_available_count": sum(1 for row in rows if row.get("outcome_available")),
        "regime_counts": {regime: int(regime_counts.get(regime, 0)) for regime in REGIME_BUCKETS},
        "summary_by_regime": summary_rows,
        "regime_classifier": "PROVISIONAL_RESEARCH_ONLY",
        "regime_classifier_notes": [
            "No canonical long-term regime classifier is wired into runtime.",
            "This backtest uses a provisional research-only classifier from BTC returns, BTC drawdown, participation, volatility, and alt relative strength.",
            "Classifier labels must not be promoted to runtime without separate validation.",
        ],
        "policy_proxy_notes": [
            "Policy comparisons are exposure-return proxies, not executable rules.",
            "reduce_immediately is modeled as zero further exposure from the event.",
            "partial_reduce_trail is modeled as half exposure retained to 21d.",
            "short_term_breath_exit uses the 3d forward return.",
            "long_term_fibo_hold uses the 21d forward return.",
        ],
        "output_paths": {key: str(value) for key, value in paths.__dict__.items()},
        "wrote_files": wrote_files,
        **SAFETY_MARKERS,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_fieldnames = fieldnames or sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=resolved_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def render_markdown_report(manifest: dict[str, Any], summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Overbreath by Regime Backtest v1",
        "",
        "Research-only Market Breath outcome measurement. No runtime behavior is changed.",
        "",
        "## Scope",
        "",
        "- market-only",
        "- account-agnostic",
        "- file-output only",
        "- no decision gate, execution planner, executor, broker, orders, or live trading",
        "",
        "## Provisional Regime Classifier",
        "",
        "No canonical long-term regime classifier exists in runtime for this task. The classifier here is provisional and research-only.",
        "",
        "Features used: BTC 10d/30d/60d return, BTC drawdown from recent high, market participation, volatility spike proxy, and alt relative strength proxy.",
        "",
        "## Summary by Regime",
        "",
        "| Regime | Events | Available | Avg 21d | Continuation 21d % | Sharp reversal % |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            "| {regime} | {events} | {available} | {avg21} | {cont21} | {sharp} |".format(
                regime=row["macro_regime"],
                events=row["event_count"],
                available=row["outcome_available_count"],
                avg21=row.get("avg_fwd_return_21d_pct"),
                cont21=row.get("continuation_probability_21d_pct"),
                sharp=row.get("sharp_reversal_probability_pct"),
            )
        )
    lines.extend(
        [
            "",
            "## Policy Proxies",
            "",
            "The policy comparison fields are research proxies only:",
            "",
            "- reduce immediately at overbreath",
            "- partial reduce + trail",
            "- hold through overbreath in bull/super-bull",
            "- wait for breakdown confirmation",
            "- short-term breath exit only",
            "- long-term fibo hold only",
            "- 50% long-term fibo bucket + 50% short-term breath trading bucket",
            "",
            "These are not trade permissions and do not create buy/sell/order logic.",
            "",
            "## Safety",
            "",
            "```text",
            "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
            "selection_engine_changes=0 decision_gate_changes=0 execution_planner_changes=0 executor_changes=0",
            "```",
            "",
            "## Outputs",
            "",
        ]
    )
    for key, value in manifest["output_paths"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def render_table(manifest: dict[str, Any], summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only account-agnostic file-output-only",
        "input=obs_market_candle asset existing_market_breath_v1_logic future_candles_for_research_outcomes",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        f"venue={manifest['venue']} interval={manifest['interval_code']}",
        f"from_ts={manifest['from_ts_utc']} to_ts={manifest['to_ts_utc']} sample_count={manifest['sample_count']}",
        f"event_phases={','.join(manifest['event_phases'])} event_count={manifest['event_count']} outcome_available={manifest['outcome_available_count']}",
        "",
        "--- summary by regime ---",
    ]
    for row in summary_rows:
        lines.append(
            "  {regime:<20} events={events:<5} available={available:<5} avg21={avg21} cont21={cont21} sharp_rev={sharp}".format(
                regime=row["macro_regime"],
                events=row["event_count"],
                available=row["outcome_available_count"],
                avg21=row.get("avg_fwd_return_21d_pct"),
                cont21=row.get("continuation_probability_21d_pct"),
                sharp=row.get("sharp_reversal_probability_pct"),
            )
        )
    lines.append("")
    lines.append("regime_classifier=PROVISIONAL_RESEARCH_ONLY")
    lines.append(f"wrote_files={manifest['wrote_files']}")
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
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

    symbol_filter = normalize_symbols(args.symbols)
    event_phases = {phase.strip().upper() for phase in args.event_phases if phase.strip()}
    paths = output_paths(args.output_dir)

    conn = get_connection()
    try:
        latest_ts = latest_asof_ts(conn, args.venue, args.interval)
        max_horizon_delta = timedelta(seconds=INTERVAL_SECONDS[args.interval] * interval_candles_for_days(args.interval, MAX_FORWARD_DAYS))
        default_to_ts = latest_ts - max_horizon_delta
        to_ts = parse_ts(args.to_ts) if args.to_ts else default_to_ts
        from_ts = parse_ts(args.from_ts) if args.from_ts else to_ts - timedelta(days=180)
        if from_ts > to_ts:
            raise ValueError("--from-ts must be <= --to-ts")

        all_assets = fetch_assets(conn)
        btc_asset = next((asset for asset in all_assets if asset.symbol == "BTC"), None)
        if btc_asset is None:
            raise RuntimeError("BTC asset is required for provisional macro regime classification")
        assets = [asset for asset in all_assets if symbol_filter is None or asset.symbol in symbol_filter]
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
        for asof_ts in asof_samples:
            rows.extend(
                event_rows_for_asof(
                    conn,
                    assets=assets,
                    btc_asset_id=btc_asset.asset_id,
                    venue=args.venue,
                    interval_code=args.interval,
                    lookback_candles=args.lookback_candles,
                    asof_ts=asof_ts,
                    event_phases=event_phases,
                )
            )
        conn.rollback()
    finally:
        conn.close()

    summary_rows = summarize_rows(rows)
    manifest = build_manifest(
        venue=args.venue,
        interval_code=args.interval,
        from_ts=from_ts,
        to_ts=to_ts,
        sample_count=len(asof_samples),
        event_phases=sorted(event_phases),
        rows=rows,
        summary_rows=summary_rows,
        paths=paths,
        wrote_files=bool(args.write_files),
    )

    if args.write_files:
        write_csv(paths.event_table_csv, rows, fieldnames=EVENT_TABLE_FIELDS)
        write_jsonl(paths.event_table_jsonl, rows)
        write_csv(paths.summary_by_regime_csv, summary_rows, fieldnames=SUMMARY_TABLE_FIELDS)
        write_json(paths.summary_by_regime_json, summary_rows)
        write_json(paths.manifest_json, manifest)
        paths.report_md.write_text(render_markdown_report(manifest, summary_rows), encoding="utf-8")

    if args.output == "json":
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(manifest, summary_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
