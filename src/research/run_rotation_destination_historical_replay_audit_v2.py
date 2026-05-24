from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from src.common.db import get_connection
from src.reporting.market_breath_context_bridge_v1 import build_market_breath_observations
from src.research.run_market_breath_analysis_v1 import (
    INTERVAL_SECONDS,
    fetch_assets,
    fmt_ts,
    latest_asof_ts,
    parse_ts,
)


REPORT_NAME = "rotation_destination_historical_replay_audit_v2"
VERSION = "2.0"
DEFAULT_OUTPUT_ROOT = "data/research/rotation_destination_historical_replay_audit_v2"
DEFAULT_RUN_DIR_PREFIX = "run_"

RAW_EVENT_CSV = "event_table_raw_historical_replay_v2.csv"
RAW_EVENT_JSONL = "event_table_raw_historical_replay_v2.jsonl"
DEDUP_EVENT_CSV = "event_table_dedup_destination_historical_replay_v2.csv"
DEDUP_EVENT_JSONL = "event_table_dedup_destination_historical_replay_v2.jsonl"
SUMMARY_BY_CONFIDENCE_CSV = "summary_by_confidence_historical_replay_v2.csv"
SUMMARY_BY_CONFIDENCE_INCLUDED_ONLY_CSV = "summary_by_confidence_included_only_v2.csv"
SUMMARY_BY_CONFIDENCE_EXCLUDED_ONLY_CSV = "summary_by_confidence_excluded_only_v2.csv"
SUMMARY_BY_REASON_CSV = "summary_by_reason_historical_replay_v2.csv"
SUMMARY_BY_DESTINATION_SYMBOL_CSV = "summary_by_destination_symbol_historical_replay_v2.csv"
SUMMARY_BY_SYMBOL_AND_CONFIDENCE_CSV = "summary_by_symbol_and_confidence_v2.csv"
SUMMARY_BY_CURVE_SANITY_CSV = "summary_by_curve_sanity_historical_replay_v2.csv"
SUMMARY_BY_SYMBOL_AND_CURVE_SANITY_CSV = "summary_by_symbol_and_curve_sanity_v2.csv"
SUMMARY_BY_MARKET_REGIME_CSV = "summary_by_market_regime_historical_replay_v2.csv"
SUMMARY_BY_RANK_BUCKET_CSV = "summary_by_rank_bucket_historical_replay_v2.csv"
MANIFEST_JSON = "manifest_v2.json"
LEAKAGE_GUARD_JSON = "leakage_guard_report_v2.json"

DEFAULT_HORIZONS_HOURS = [4, 8, 12, 24, 48]
OUTPUT_FLOAT_COLUMNS = [
    "destination_price_at_asof",
    "destination_price_4h",
    "destination_price_8h",
    "destination_price_12h",
    "destination_price_24h",
    "destination_price_48h",
    "destination_return_4h_pct",
    "destination_return_8h_pct",
    "destination_return_12h_pct",
    "destination_return_24h_pct",
    "destination_return_48h_pct",
    "destination_forward_max_24h_pct",
    "destination_forward_min_24h_pct",
    "destination_score",
]

SAFETY_MARKERS = {
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "db_writes": 0,
    "paper_advice_snapshots_used": False,
    "account_tables_used": False,
}

EVENT_COLUMNS = [
    "run_id",
    "audit_version",
    "sample_ts_utc",
    "source_mode",
    "source_symbol",
    "destination_symbol",
    "destination_rank",
    "destination_score",
    "destination_selection_state",
    "destination_setup_state",
    "destination_setup_reason",
    "destination_policy_preview_state",
    "confidence_bucket",
    "confidence_reason",
    "curve_sanity_state",
    "market_regime_state",
    "btc_prior_24h_return",
    "destination_price_at_asof",
    "destination_price_4h",
    "destination_price_8h",
    "destination_price_12h",
    "destination_price_24h",
    "destination_price_48h",
    "destination_return_4h_pct",
    "destination_return_8h_pct",
    "destination_return_12h_pct",
    "destination_return_24h_pct",
    "destination_return_48h_pct",
    "destination_forward_max_24h_pct",
    "destination_forward_min_24h_pct",
    "data_quality_state",
    "excluded_reason",
]


@dataclass(frozen=True)
class OutputPaths:
    raw_event_csv: Path
    raw_event_jsonl: Path
    dedup_event_csv: Path
    dedup_event_jsonl: Path
    summary_by_confidence_csv: Path
    summary_by_confidence_included_only_csv: Path
    summary_by_confidence_excluded_only_csv: Path
    summary_by_reason_csv: Path
    summary_by_destination_symbol_csv: Path
    summary_by_symbol_and_confidence_csv: Path
    summary_by_curve_sanity_csv: Path
    summary_by_symbol_and_curve_sanity_csv: Path
    summary_by_market_regime_csv: Path
    summary_by_rank_bucket_csv: Path
    manifest_json: Path
    leakage_guard_json: Path


@dataclass(frozen=True)
class ReplayCandle:
    asset_id: int
    close_ts_utc: datetime
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct historical rotation destination candidates from market-only point-in-time state "
            "and evaluate forward outcomes (research-only, no paper_advice candidate source)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--start-ts", default=None)
    parser.add_argument("--end-ts", default=None)
    parser.add_argument("--sample-every-n", type=int, default=6)
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Maximum sampled timestamps to replay. Use 0 for unlimited.",
    )
    parser.add_argument("--top-n-destinations", type=int, default=10)
    parser.add_argument(
        "--horizons-hours",
        nargs="+",
        default=[str(value) for value in DEFAULT_HORIZONS_HOURS],
        help="Forward horizons in hours. Accepts either spaced values or comma-separated groups.",
    )
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.replace(tzinfo=UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_output_dir(*, output_root: str | None, run_id: str) -> Path:
    root = Path(output_root) if output_root else Path(DEFAULT_OUTPUT_ROOT)
    return root / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def format_number(value: Any, places: str = "0.000001") -> str:
    if value is None:
        return ""
    as_dec = to_decimal(value)
    if as_dec is None:
        return ""
    try:
        return str(as_dec.quantize(Decimal(places)))
    except Exception:
        return str(as_dec)


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_horizons_hours(values: list[Any] | None) -> list[int]:
    if not values:
        raise ValueError("--horizons-hours must not be empty")
    horizons: list[int] = []
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        for piece in raw.split(","):
            token = piece.strip()
            if not token:
                continue
            try:
                parsed = int(token)
            except Exception as exc:
                raise ValueError(f"Invalid --horizons-hours value: {token}") from exc
            if parsed <= 0:
                raise ValueError("--horizons-hours values must be > 0")
            horizons.append(parsed)
    if not horizons:
        raise ValueError("--horizons-hours must not be empty")
    return horizons


def as_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        return 0.0


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    return str(value)


def pct_return(base_price: Decimal | None, future_price: Decimal | None) -> Decimal | None:
    if base_price is None or future_price is None or base_price <= 0:
        return None
    return ((future_price / base_price) - Decimal("1")) * Decimal("100")


def fetch_asset_map(conn: Any) -> dict[str, int]:
    assets = fetch_assets(conn)
    return {str(asset.symbol).upper(): int(asset.asset_id) for asset in assets}


def fetch_sample_timestamps(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
    sample_every_n: int,
    max_samples: int | None,
) -> list[datetime]:
    if sample_every_n <= 0:
        raise ValueError("--sample-every-n must be > 0")

    btc_id = fetch_asset_map(conn).get("BTC")
    asset_filter = ""
    params: list[Any] = [venue, interval_code, start_ts, end_ts]
    if btc_id is not None:
        asset_filter = "AND asset_id = %s"
        params.append(btc_id)

    sql = f"""
        SELECT DISTINCT close_ts_utc
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
          {asset_filter}
        ORDER BY close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    available = [row["close_ts_utc"] for row in rows if row.get("close_ts_utc") is not None]
    sampled = available[::sample_every_n]
    if max_samples is not None and max_samples > 0:
        sampled = sampled[:max_samples]
    return sampled


def fetch_future_candles(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    sample_ts: datetime,
    max_horizon_hours: int,
    asset_ids: list[int],
) -> dict[int, list[ReplayCandle]]:
    if not asset_ids:
        return {}
    horizon_end = sample_ts + timedelta(hours=max_horizon_hours)
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT
            asset_id,
            close_ts_utc,
            close_price,
            high_price,
            low_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc > %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code, sample_ts, horizon_end, *asset_ids]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    grouped: dict[int, list[ReplayCandle]] = defaultdict(list)
    for row in rows:
        if row.get("close_price") is None:
            continue
        grouped[int(row["asset_id"])].append(
            ReplayCandle(
                asset_id=int(row["asset_id"]),
                close_ts_utc=row["close_ts_utc"],
                close_price=Decimal(str(row["close_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
            )
        )
    return dict(grouped)


def market_replay_score(observation: dict[str, Any]) -> float:
    if observation.get("invalid_reason"):
        return -9999.0
    market_breath_score = as_float(observation.get("market_breath_score"))
    momentum = as_float(observation.get("momentum_score"))
    relative_strength = as_float(observation.get("relative_strength_score"))
    expansion = as_float(observation.get("expansion_score"))
    reversal = as_float(observation.get("reversal_pressure_score"))
    compression = as_float(observation.get("compression_score"))
    ret6 = as_float(observation.get("return_6"))
    score = (
        market_breath_score
        + 0.25 * momentum
        + 0.20 * relative_strength
        + 0.10 * expansion
        - 0.15 * reversal
        + 0.05 * compression
        + 0.10 * ret6
    )
    return round(score, 6)


def selection_state(observation: dict[str, Any], score: float) -> str:
    if observation.get("invalid_reason"):
        return "AVOID"
    phase = str(observation.get("market_breath_phase") or "").upper()
    confidence = as_float(observation.get("market_breath_confidence"))
    if phase in {"COLLAPSE_RESET", "INSUFFICIENT_DATA"}:
        return "AVOID"
    if score >= 60.0 and confidence >= 65.0:
        return "WATCHLIST"
    if score >= 45.0:
        return "NEUTRAL"
    return "AVOID"


def setup_state_and_reason(observation: dict[str, Any]) -> tuple[str, str]:
    if observation.get("invalid_reason"):
        return "FAIL", "INSUFFICIENT_SAMPLE"
    phase = str(observation.get("market_breath_phase") or "").upper()
    reversal = as_float(observation.get("reversal_pressure_score"))
    momentum = as_float(observation.get("momentum_score"))
    if phase == "COLLAPSE_RESET":
        return "FAIL", "MARKET_DAMAGE_RISK"
    if reversal >= 60.0:
        return "FAIL", "MARKET_DAMAGE_CAUTION"
    if phase in {"NEUTRAL_TRANSITION", "HOLD_COMPRESSION"} and momentum <= 0:
        return "FAIL", "SELECTION_STATE_NOT_ELIGIBLE"
    return "PASS", "SETUP_PASS"


def curve_sanity_state(observation: dict[str, Any]) -> str:
    phase = str(observation.get("market_breath_phase") or "").upper()
    momentum = as_float(observation.get("momentum_score"))
    ret3 = as_float(observation.get("return_3"))
    if phase == "COLLAPSE_RESET" or momentum < -10.0:
        return "CURVE_DOWN_PRESSURE"
    if momentum > 20.0 and ret3 > 0.0:
        return "CURVE_UP_CONFIRMED"
    if abs(momentum) <= 10.0:
        return "CURVE_WEAK"
    return "CURVE_NEUTRAL"


def confidence_bucket_and_reason(
    observation: dict[str, Any],
    score: float,
    curve_state: str,
) -> tuple[str, str]:
    phase = str(observation.get("market_breath_phase") or "").upper()
    confidence = as_float(observation.get("market_breath_confidence"))
    if (
        phase == "EXHALE_EXPANSION"
        and curve_state == "CURVE_UP_CONFIRMED"
        and score >= 60.0
        and confidence >= 70.0
    ):
        return "HIGH_CONFIDENCE_DESTINATION", "EXHALE_EXPANSION_UP_CONFIRMED"
    if phase in {"EXHALE_EXPANSION", "INHALE_ACCUMULATION"} and score >= 45.0:
        return "MEDIUM_CONFIDENCE_DESTINATION", "TREND_OR_ACCUMULATION_WITH_MIXED_SIGNAL"
    if curve_state == "CURVE_DOWN_PRESSURE":
        return "MARKET_ONLY_DESTINATION", "DOWN_PRESSURE_MARKET_ONLY"
    return "LOW_CONFIDENCE_DESTINATION", "WEAK_OR_AMBIGUOUS_CONTEXT"


def policy_preview_state(
    *,
    setup_state_value: str,
    setup_reason_value: str,
    confidence_bucket_value: str,
) -> str:
    if setup_state_value != "PASS":
        if setup_reason_value == "MARKET_DAMAGE_RISK":
            return "BLOCK_MARKET_DAMAGE"
        if setup_reason_value == "INSUFFICIENT_SAMPLE":
            return "BLOCK_INSUFFICIENT_SAMPLE"
        return "BLOCK_SETUP_FILTER_FAIL"
    if confidence_bucket_value == "LOW_CONFIDENCE_DESTINATION":
        return "WATCH_ONLY"
    if confidence_bucket_value == "MARKET_ONLY_DESTINATION":
        return "CONTEXT_ONLY"
    return "ALLOW"


def source_symbol_candidates(observations: list[dict[str, Any]]) -> list[str]:
    weak_symbols: list[str] = []
    scored: list[tuple[str, float]] = []
    for row in observations:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or row.get("invalid_reason"):
            continue
        score = market_replay_score(row)
        phase = str(row.get("market_breath_phase") or "").upper()
        momentum = as_float(row.get("momentum_score"))
        scored.append((symbol, score))
        if phase in {"COLLAPSE_RESET", "OVERBREATH_EXTENSION", "NEUTRAL_TRANSITION"} or momentum < 0:
            weak_symbols.append(symbol)

    weak_symbols = sorted(dict.fromkeys(weak_symbols))
    if weak_symbols:
        return weak_symbols
    if not scored:
        return []
    scored.sort(key=lambda item: (item[1], item[0]))
    take_n = max(1, min(5, len(scored) // 4 or 1))
    return [item[0] for item in scored[:take_n]]


def price_at_horizon(
    sample_ts: datetime,
    future_candles: list[ReplayCandle],
    horizon_hours: int,
) -> Decimal | None:
    target = sample_ts + timedelta(hours=horizon_hours)
    future = next((row for row in future_candles if row.close_ts_utc >= target), None)
    return None if future is None else future.close_price


def forward_24h_range(
    sample_ts: datetime,
    future_candles: list[ReplayCandle],
) -> tuple[Decimal | None, Decimal | None]:
    end = sample_ts + timedelta(hours=24)
    window = [row for row in future_candles if row.close_ts_utc <= end]
    if not window:
        return None, None
    return max((row.high_price for row in window), default=None), min((row.low_price for row in window), default=None)


def build_sample_events(
    *,
    run_id: str,
    sample_ts: datetime,
    observations: list[dict[str, Any]],
    top_n_destinations: int,
    horizons_hours: list[int],
    future_candles_by_asset: dict[int, list[ReplayCandle]],
) -> tuple[list[dict[str, Any]], int]:
    by_symbol = {str(row.get("symbol") or "").upper(): row for row in observations}
    source_symbols = source_symbol_candidates(observations)

    destination_scored: list[tuple[str, float]] = []
    for row in observations:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        score = market_replay_score(row)
        destination_scored.append((symbol, score))
    destination_scored.sort(key=lambda item: (item[1], item[0]), reverse=True)

    destinations_top = [symbol for symbol, _score in destination_scored[:top_n_destinations]]
    rank_by_symbol = {symbol: idx + 1 for idx, symbol in enumerate(destinations_top)}

    max_input_ts_gt_sample_ts_rows = 0
    events: list[dict[str, Any]] = []
    btc_row = by_symbol.get("BTC")
    btc_prior_24h_return = format_number(None if btc_row is None else btc_row.get("return_6"))

    for source_symbol in sorted(source_symbols):
        source_obs = by_symbol.get(source_symbol)
        if source_obs is None:
            continue
        source_score = market_replay_score(source_obs)
        for destination_symbol in destinations_top:
            if destination_symbol == source_symbol:
                continue
            dest_obs = by_symbol.get(destination_symbol)
            if dest_obs is None:
                continue

            destination_rank = rank_by_symbol[destination_symbol]
            destination_score = market_replay_score(dest_obs)
            if destination_score <= source_score:
                continue

            dest_selection_state = selection_state(dest_obs, destination_score)
            setup_state_value, setup_reason_value = setup_state_and_reason(dest_obs)
            curve_state = curve_sanity_state(dest_obs)
            confidence_bucket, confidence_reason = confidence_bucket_and_reason(
                dest_obs,
                destination_score,
                curve_state,
            )
            policy_state = policy_preview_state(
                setup_state_value=setup_state_value,
                setup_reason_value=setup_reason_value,
                confidence_bucket_value=confidence_bucket,
            )
            phase = str(dest_obs.get("market_breath_phase") or "").upper()
            state = str(dest_obs.get("market_breath_state") or "").upper()
            market_regime_state = f"{phase}:{state}" if phase or state else "UNKNOWN:UNKNOWN"

            asset_id = int(dest_obs["asset_id"]) if dest_obs.get("asset_id") is not None else -1
            asof_price = to_decimal(dest_obs.get("close_price"))
            future_candles = future_candles_by_asset.get(asset_id, [])

            prices_by_horizon: dict[int, Decimal | None] = {
                horizon: price_at_horizon(sample_ts, future_candles, horizon)
                for horizon in horizons_hours
            }
            returns_by_horizon: dict[int, Decimal | None] = {
                horizon: pct_return(asof_price, prices_by_horizon[horizon])
                for horizon in horizons_hours
            }
            max_24h, min_24h = forward_24h_range(sample_ts, future_candles)
            fwd_max_24h = pct_return(asof_price, max_24h)
            fwd_min_24h = pct_return(asof_price, min_24h)

            quality_labels: list[str] = []
            if asof_price is None:
                quality_labels.append("MISSING_ASOF_PRICE")
            if all(prices_by_horizon.get(h) is None for h in horizons_hours):
                quality_labels.append("MISSING_FUTURE_HORIZONS")
            if prices_by_horizon.get(24) is None:
                quality_labels.append("MISSING_24H_OUTCOME")
            if not quality_labels:
                quality_labels.append("OK")

            excluded_reason = ""
            if setup_state_value != "PASS":
                excluded_reason = setup_reason_value
            elif dest_selection_state == "AVOID":
                excluded_reason = "SELECTION_AVOID"

            event = {
                "run_id": run_id,
                "audit_version": VERSION,
                "sample_ts_utc": fmt_ts(sample_ts),
                "source_mode": "MARKET_WEAK_TO_STRONG_REPLAY",
                "source_symbol": source_symbol,
                "destination_symbol": destination_symbol,
                "destination_rank": str(destination_rank),
                "destination_score": format_number(destination_score),
                "destination_selection_state": dest_selection_state,
                "destination_setup_state": setup_state_value,
                "destination_setup_reason": setup_reason_value,
                "destination_policy_preview_state": policy_state,
                "confidence_bucket": confidence_bucket,
                "confidence_reason": confidence_reason,
                "curve_sanity_state": curve_state,
                "market_regime_state": market_regime_state,
                "btc_prior_24h_return": btc_prior_24h_return,
                "destination_price_at_asof": format_number(asof_price, "0.00000001"),
                "destination_price_4h": format_number(prices_by_horizon.get(4), "0.00000001"),
                "destination_price_8h": format_number(prices_by_horizon.get(8), "0.00000001"),
                "destination_price_12h": format_number(prices_by_horizon.get(12), "0.00000001"),
                "destination_price_24h": format_number(prices_by_horizon.get(24), "0.00000001"),
                "destination_price_48h": format_number(prices_by_horizon.get(48), "0.00000001"),
                "destination_return_4h_pct": format_number(returns_by_horizon.get(4)),
                "destination_return_8h_pct": format_number(returns_by_horizon.get(8)),
                "destination_return_12h_pct": format_number(returns_by_horizon.get(12)),
                "destination_return_24h_pct": format_number(returns_by_horizon.get(24)),
                "destination_return_48h_pct": format_number(returns_by_horizon.get(48)),
                "destination_forward_max_24h_pct": format_number(fwd_max_24h),
                "destination_forward_min_24h_pct": format_number(fwd_min_24h),
                "data_quality_state": ";".join(quality_labels),
                "excluded_reason": excluded_reason,
            }
            events.append(event)
    return events, max_input_ts_gt_sample_ts_rows


def dedup_destination_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("sample_ts_utc") or ""), str(row.get("destination_symbol") or ""))
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = row
            continue
        row_score = to_decimal(row.get("destination_score")) or Decimal("-999999")
        existing_score = to_decimal(existing.get("destination_score")) or Decimal("-999999")
        row_source = str(row.get("source_symbol") or "")
        existing_source = str(existing.get("source_symbol") or "")
        if row_score > existing_score or (row_score == existing_score and row_source < existing_source):
            best_by_key[key] = row

    deduped = list(best_by_key.values())
    deduped.sort(
        key=lambda row: (
            str(row.get("sample_ts_utc") or ""),
            str(row.get("destination_symbol") or ""),
            -(to_decimal(row.get("destination_score")) or Decimal("0")),
            str(row.get("source_symbol") or ""),
        )
    )
    return deduped


def summary_label_rows(rows: list[dict[str, Any]], label_field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        label = str(row.get(label_field) or "")
        if label:
            grouped[label].append(row)

    output: list[dict[str, Any]] = []
    for label in sorted(grouped):
        label_rows = grouped[label]
        return_24 = numeric_values(label_rows, "destination_return_24h_pct")
        return_48 = numeric_values(label_rows, "destination_return_48h_pct")
        output.append(
            {
                "label": label,
                "event_count": len(label_rows),
                "included_count": sum(1 for row in label_rows if not str(row.get("excluded_reason") or "")),
                "excluded_count": sum(1 for row in label_rows if str(row.get("excluded_reason") or "")),
                "avg_return_4h_pct": avg(numeric_values(label_rows, "destination_return_4h_pct")),
                "avg_return_8h_pct": avg(numeric_values(label_rows, "destination_return_8h_pct")),
                "avg_return_12h_pct": avg(numeric_values(label_rows, "destination_return_12h_pct")),
                "avg_return_24h_pct": avg(return_24),
                "median_return_24h_pct": median_or_none(return_24),
                "positive_rate_24h_pct": positive_rate(return_24),
                "avg_return_48h_pct": avg(return_48),
                "median_return_48h_pct": median_or_none(return_48),
                "positive_rate_48h_pct": positive_rate(return_48),
                "avg_forward_max_24h_pct": avg(numeric_values(label_rows, "destination_forward_max_24h_pct")),
                "avg_forward_min_24h_pct": avg(numeric_values(label_rows, "destination_forward_min_24h_pct")),
            }
        )
    return output


def summary_label_rows_from_labels(
    rows: list[dict[str, Any]],
    label_builder: Any,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        label = str(label_builder(row) or "")
        if label:
            grouped[label].append(row)

    output: list[dict[str, Any]] = []
    for label in sorted(grouped):
        label_rows = grouped[label]
        return_24 = numeric_values(label_rows, "destination_return_24h_pct")
        return_48 = numeric_values(label_rows, "destination_return_48h_pct")
        output.append(
            {
                "label": label,
                "event_count": len(label_rows),
                "included_count": sum(1 for row in label_rows if not str(row.get("excluded_reason") or "")),
                "excluded_count": sum(1 for row in label_rows if str(row.get("excluded_reason") or "")),
                "avg_return_4h_pct": avg(numeric_values(label_rows, "destination_return_4h_pct")),
                "avg_return_8h_pct": avg(numeric_values(label_rows, "destination_return_8h_pct")),
                "avg_return_12h_pct": avg(numeric_values(label_rows, "destination_return_12h_pct")),
                "avg_return_24h_pct": avg(return_24),
                "median_return_24h_pct": median_or_none(return_24),
                "positive_rate_24h_pct": positive_rate(return_24),
                "avg_return_48h_pct": avg(return_48),
                "median_return_48h_pct": median_or_none(return_48),
                "positive_rate_48h_pct": positive_rate(return_48),
                "avg_forward_max_24h_pct": avg(numeric_values(label_rows, "destination_forward_max_24h_pct")),
                "avg_forward_min_24h_pct": avg(numeric_values(label_rows, "destination_forward_min_24h_pct")),
            }
        )
    return output


def rank_bucket(value: str) -> str:
    try:
        rank = int(value)
    except Exception:
        return "UNKNOWN"
    if rank <= 1:
        return "TOP_1"
    if rank <= 3:
        return "TOP_3"
    if rank <= 5:
        return "TOP_5"
    return "TOP_N"


def with_rank_bucket(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        copied["rank_bucket"] = rank_bucket(str(row.get("destination_rank") or ""))
        out.append(copied)
    return out


def numeric_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row.get(field)
        if raw in ("", None):
            continue
        try:
            values.append(float(raw))
        except Exception:
            continue
    return values


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 6)


def positive_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0.0) / len(values) * 100.0, 6)


def output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        raw_event_csv=output_dir / RAW_EVENT_CSV,
        raw_event_jsonl=output_dir / RAW_EVENT_JSONL,
        dedup_event_csv=output_dir / DEDUP_EVENT_CSV,
        dedup_event_jsonl=output_dir / DEDUP_EVENT_JSONL,
        summary_by_confidence_csv=output_dir / SUMMARY_BY_CONFIDENCE_CSV,
        summary_by_confidence_included_only_csv=output_dir / SUMMARY_BY_CONFIDENCE_INCLUDED_ONLY_CSV,
        summary_by_confidence_excluded_only_csv=output_dir / SUMMARY_BY_CONFIDENCE_EXCLUDED_ONLY_CSV,
        summary_by_reason_csv=output_dir / SUMMARY_BY_REASON_CSV,
        summary_by_destination_symbol_csv=output_dir / SUMMARY_BY_DESTINATION_SYMBOL_CSV,
        summary_by_symbol_and_confidence_csv=output_dir / SUMMARY_BY_SYMBOL_AND_CONFIDENCE_CSV,
        summary_by_curve_sanity_csv=output_dir / SUMMARY_BY_CURVE_SANITY_CSV,
        summary_by_symbol_and_curve_sanity_csv=output_dir / SUMMARY_BY_SYMBOL_AND_CURVE_SANITY_CSV,
        summary_by_market_regime_csv=output_dir / SUMMARY_BY_MARKET_REGIME_CSV,
        summary_by_rank_bucket_csv=output_dir / SUMMARY_BY_RANK_BUCKET_CSV,
        manifest_json=output_dir / MANIFEST_JSON,
        leakage_guard_json=output_dir / LEAKAGE_GUARD_JSON,
    )


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


def summary_fields() -> list[str]:
    return [
        "label",
        "event_count",
        "included_count",
        "excluded_count",
        "avg_return_4h_pct",
        "avg_return_8h_pct",
        "avg_return_12h_pct",
        "avg_return_24h_pct",
        "median_return_24h_pct",
        "positive_rate_24h_pct",
        "avg_return_48h_pct",
        "median_return_48h_pct",
        "positive_rate_48h_pct",
        "avg_forward_max_24h_pct",
        "avg_forward_min_24h_pct",
    ]


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    start_ts: datetime,
    end_ts: datetime,
    sample_count: int,
    raw_event_count: int,
    dedup_destination_event_count: int,
    max_input_ts_gt_sample_ts_rows: int,
    output_paths_map: OutputPaths,
    run_started_at: datetime,
    run_finished_at: datetime,
    run_duration_sec: float,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at.replace(tzinfo=None)),
        "run_finished_at_utc": fmt_ts(run_finished_at.replace(tzinfo=None)),
        "run_duration_sec": round(run_duration_sec, 6),
        "exit_code": int(exit_code),
        "venue": args.venue,
        "interval_code": args.interval,
        "start_ts": fmt_ts(start_ts),
        "end_ts": fmt_ts(end_ts),
        "sample_every_n": int(args.sample_every_n),
        "max_samples": None if args.max_samples is None else int(args.max_samples),
        "top_n_destinations": int(args.top_n_destinations),
        "horizons_hours": [int(value) for value in args.horizons_hours],
        "sample_count": int(sample_count),
        "raw_event_count": int(raw_event_count),
        "dedup_destination_event_count": int(dedup_destination_event_count),
        "source_mode": "MARKET_WEAK_TO_STRONG_REPLAY",
        "paper_advice_snapshots_used": False,
        "account_tables_used": False,
        "max_input_ts_gt_sample_ts_rows": int(max_input_ts_gt_sample_ts_rows),
        "wrote_files": bool(args.write_files),
        "output_paths": {
            "raw_event_csv": str(output_paths_map.raw_event_csv),
            "raw_event_jsonl": str(output_paths_map.raw_event_jsonl),
            "dedup_event_csv": str(output_paths_map.dedup_event_csv),
            "dedup_event_jsonl": str(output_paths_map.dedup_event_jsonl),
            "summary_by_confidence_csv": str(output_paths_map.summary_by_confidence_csv),
            "summary_by_confidence_included_only_csv": str(output_paths_map.summary_by_confidence_included_only_csv),
            "summary_by_confidence_excluded_only_csv": str(output_paths_map.summary_by_confidence_excluded_only_csv),
            "summary_by_reason_csv": str(output_paths_map.summary_by_reason_csv),
            "summary_by_destination_symbol_csv": str(output_paths_map.summary_by_destination_symbol_csv),
            "summary_by_symbol_and_confidence_csv": str(output_paths_map.summary_by_symbol_and_confidence_csv),
            "summary_by_curve_sanity_csv": str(output_paths_map.summary_by_curve_sanity_csv),
            "summary_by_symbol_and_curve_sanity_csv": str(output_paths_map.summary_by_symbol_and_curve_sanity_csv),
            "summary_by_market_regime_csv": str(output_paths_map.summary_by_market_regime_csv),
            "summary_by_rank_bucket_csv": str(output_paths_map.summary_by_rank_bucket_csv),
            "manifest_json": str(output_paths_map.manifest_json),
            "leakage_guard_json": str(output_paths_map.leakage_guard_json),
        },
        "source_tables_used": [
            "asset",
            "obs_market_candle",
        ],
        "excluded_or_forbidden_tables": [
            "paper_advice_observation",
            "account_position_snapshot",
            "trading_account_balance_snapshot",
            "open_order",
        ],
        "notes": [
            "Historical candidate replay is reconstructed from market-only point-in-time candle state.",
            "Future candles are used only for outcome measurements.",
            "No paper advice snapshots are used as candidate source.",
        ],
        **SAFETY_MARKERS,
    }


def build_leakage_guard_report(
    *,
    run_id: str,
    sample_count: int,
    raw_event_count: int,
    dedup_destination_event_count: int,
    max_input_ts_gt_sample_ts_rows: int,
    start_ts: datetime,
    end_ts: datetime,
    venue: str,
    interval_code: str,
) -> dict[str, Any]:
    return {
        "report": "leakage_guard_report_v2",
        "run_id": run_id,
        "venue": venue,
        "interval_code": interval_code,
        "start_ts": fmt_ts(start_ts),
        "end_ts": fmt_ts(end_ts),
        "sample_count": int(sample_count),
        "raw_event_count": int(raw_event_count),
        "dedup_destination_event_count": int(dedup_destination_event_count),
        "paper_advice_snapshots_used": False,
        "account_tables_used": False,
        "future_candles_used_for_outcomes_only": True,
        "max_input_ts_gt_sample_ts_rows": int(max_input_ts_gt_sample_ts_rows),
        "leakage_check_passed": max_input_ts_gt_sample_ts_rows == 0,
        "guardrails": [
            "No paper_advice snapshot table is used as replay candidate source.",
            "No account/broker/order tables are queried.",
            "All replay candidate inputs are bounded at or before each sample_ts.",
            "Future candles are accessed only for outcome fields.",
        ],
        **SAFETY_MARKERS,
    }


def render_table(
    manifest: dict[str, Any],
    summary_by_confidence: list[dict[str, Any]],
    summary_by_curve: list[dict[str, Any]],
) -> str:
    lines = [
        f"[RUN][ID] {manifest['run_id']}",
        f"[RUN][OUT_DIR] {manifest['output_dir']}",
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only historical replay account-agnostic",
        "candidate_source=historical market replay (no paper_advice snapshots)",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        f"venue={manifest['venue']} interval={manifest['interval_code']}",
        (
            f"start_ts={manifest['start_ts']} end_ts={manifest['end_ts']} "
            f"sample_count={manifest['sample_count']} raw_event_count={manifest['raw_event_count']} "
            f"dedup_destination_event_count={manifest['dedup_destination_event_count']}"
        ),
        (
            f"paper_advice_snapshots_used={manifest['paper_advice_snapshots_used']} "
            f"account_tables_used={manifest['account_tables_used']} "
            f"max_input_ts_gt_sample_ts_rows={manifest['max_input_ts_gt_sample_ts_rows']}"
        ),
        "",
        "--- dedup summary by confidence ---",
    ]
    for row in summary_by_confidence:
        lines.append(
            "  "
            f"{row['label']} count={row['event_count']} avg_24h={row['avg_return_24h_pct']} "
            f"median_24h={row['median_return_24h_pct']} positive_24h={row['positive_rate_24h_pct']}"
        )
    lines.append("")
    lines.append("--- dedup summary by curve_sanity ---")
    for row in summary_by_curve:
        lines.append(
            "  "
            f"{row['label']} count={row['event_count']} avg_24h={row['avg_return_24h_pct']} "
            f"median_24h={row['median_return_24h_pct']} positive_24h={row['positive_rate_24h_pct']}"
        )
    lines.append("")
    lines.append(f"wrote_files={manifest['wrote_files']}")
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
            lines.append(f"  wrote_file[{key}]={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.horizons_hours = parse_horizons_hours(args.horizons_hours)
    if args.max_samples == 0:
        args.max_samples = None
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {args.interval}")
    if args.sample_every_n <= 0:
        raise ValueError("--sample-every-n must be > 0")
    if args.top_n_destinations <= 0:
        raise ValueError("--top-n-destinations must be > 0")
    if args.max_samples is not None and args.max_samples < 0:
        raise ValueError("--max-samples must be >= 0 when provided")

    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)
    out_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    paths = output_paths(out_dir)
    max_horizon = max(int(value) for value in args.horizons_hours)
    started = perf_counter()

    conn = get_connection()
    try:
        latest_ts = latest_asof_ts(conn, args.venue, args.interval)
        default_end = latest_ts - timedelta(hours=max_horizon)
        end_ts = parse_ts(args.end_ts) if args.end_ts else default_end
        start_ts = parse_ts(args.start_ts) if args.start_ts else end_ts - timedelta(days=120)
        if start_ts > end_ts:
            raise ValueError("--start-ts must be <= --end-ts")

        sample_ts_values = fetch_sample_timestamps(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            start_ts=start_ts,
            end_ts=end_ts,
            sample_every_n=int(args.sample_every_n),
            max_samples=args.max_samples,
        )

        raw_events: list[dict[str, Any]] = []
        max_input_ts_gt_sample_ts_rows = 0
        for sample_ts in sample_ts_values:
            observations = build_market_breath_observations(
                conn,
                venue=args.venue,
                interval_code=args.interval,
                lookback_candles=120,
                asof_ts=sample_ts,
            )
            asset_ids = sorted({int(row["asset_id"]) for row in observations if row.get("asset_id") is not None})
            future_candles_by_asset = fetch_future_candles(
                conn,
                venue=args.venue,
                interval_code=args.interval,
                sample_ts=sample_ts,
                max_horizon_hours=max_horizon,
                asset_ids=asset_ids,
            )
            sample_events, overflow_count = build_sample_events(
                run_id=run_id,
                sample_ts=sample_ts,
                observations=observations,
                top_n_destinations=int(args.top_n_destinations),
                horizons_hours=[int(value) for value in args.horizons_hours],
                future_candles_by_asset=future_candles_by_asset,
            )
            raw_events.extend(sample_events)
            max_input_ts_gt_sample_ts_rows = max(max_input_ts_gt_sample_ts_rows, overflow_count)
        conn.rollback()
    finally:
        conn.close()

    dedup_events = dedup_destination_rows(raw_events)
    dedup_with_rank = with_rank_bucket(dedup_events)
    summary_confidence = summary_label_rows(dedup_events, "confidence_bucket")
    included_only_events = [row for row in dedup_events if not str(row.get("excluded_reason") or "")]
    excluded_only_events = [row for row in dedup_events if str(row.get("excluded_reason") or "")]
    summary_confidence_included_only = summary_label_rows(included_only_events, "confidence_bucket")
    summary_confidence_excluded_only = summary_label_rows(excluded_only_events, "confidence_bucket")
    summary_reason = summary_label_rows(dedup_events, "confidence_reason")
    summary_destination = summary_label_rows(dedup_events, "destination_symbol")
    summary_symbol_and_confidence = summary_label_rows_from_labels(
        dedup_events,
        lambda row: f"{str(row.get('destination_symbol') or '')}|{str(row.get('confidence_bucket') or '')}",
    )
    summary_curve = summary_label_rows(dedup_events, "curve_sanity_state")
    summary_symbol_and_curve = summary_label_rows_from_labels(
        dedup_events,
        lambda row: f"{str(row.get('destination_symbol') or '')}|{str(row.get('curve_sanity_state') or '')}",
    )
    summary_regime = summary_label_rows(dedup_events, "market_regime_state")
    summary_rank = summary_label_rows(dedup_with_rank, "rank_bucket")

    run_finished_at = datetime.now(UTC)
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        output_dir=out_dir,
        start_ts=start_ts,
        end_ts=end_ts,
        sample_count=len(sample_ts_values),
        raw_event_count=len(raw_events),
        dedup_destination_event_count=len(dedup_events),
        max_input_ts_gt_sample_ts_rows=max_input_ts_gt_sample_ts_rows,
        output_paths_map=paths,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        run_duration_sec=perf_counter() - started,
        exit_code=0,
    )
    leakage_guard = build_leakage_guard_report(
        run_id=run_id,
        sample_count=len(sample_ts_values),
        raw_event_count=len(raw_events),
        dedup_destination_event_count=len(dedup_events),
        max_input_ts_gt_sample_ts_rows=max_input_ts_gt_sample_ts_rows,
        start_ts=start_ts,
        end_ts=end_ts,
        venue=args.venue,
        interval_code=args.interval,
    )

    if args.write_files:
        write_csv(paths.raw_event_csv, raw_events, EVENT_COLUMNS)
        write_jsonl(paths.raw_event_jsonl, raw_events)
        write_csv(paths.dedup_event_csv, dedup_events, EVENT_COLUMNS)
        write_jsonl(paths.dedup_event_jsonl, dedup_events)
        fields = summary_fields()
        write_csv(paths.summary_by_confidence_csv, summary_confidence, fields)
        write_csv(paths.summary_by_confidence_included_only_csv, summary_confidence_included_only, fields)
        write_csv(paths.summary_by_confidence_excluded_only_csv, summary_confidence_excluded_only, fields)
        write_csv(paths.summary_by_reason_csv, summary_reason, fields)
        write_csv(paths.summary_by_destination_symbol_csv, summary_destination, fields)
        write_csv(paths.summary_by_symbol_and_confidence_csv, summary_symbol_and_confidence, fields)
        write_csv(paths.summary_by_curve_sanity_csv, summary_curve, fields)
        write_csv(paths.summary_by_symbol_and_curve_sanity_csv, summary_symbol_and_curve, fields)
        write_csv(paths.summary_by_market_regime_csv, summary_regime, fields)
        write_csv(paths.summary_by_rank_bucket_csv, summary_rank, fields)
        write_json(paths.manifest_json, manifest)
        write_json(paths.leakage_guard_json, leakage_guard)

    if args.output == "json":
        print(f"[RUN][ID] {manifest['run_id']}")
        print(f"[RUN][OUT_DIR] {manifest['output_dir']}")
        if manifest["wrote_files"]:
            for key, value in manifest["output_paths"].items():
                print(f"wrote_file[{key}]={value}")
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, default=json_default))
    else:
        print(render_table(manifest, summary_confidence, summary_curve))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
