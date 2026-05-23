from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from src.common.db import get_connection
from src.reporting.entry_zone_state_v1 import (
    classify_entry_zone_state,
    classify_price_progress_state,
    confirmation_display_state,
    semantic_advice_action_display,
    semantic_entry_display_state,
)
from src.reporting.fast_lifecycle_recompute_v1 import classify_fast_lifecycle
from src.reporting.market_breath_context_bridge_v1 import (
    aplus_legacy_block_strength,
    aplus_legacy_freshness_state,
    build_market_breath_observations,
    market_breath_context_state,
)
from src.reporting.next_zone_preview_v1 import preview_next_zones
from src.reporting.policy_block_reason_display_v1 import classify_policy_block_display
from src.reporting.rotation_destination_eligibility_v1 import (
    DestinationConfidence,
    DestinationEligibility,
    destination_confidence,
    evaluate_rotation_destination_eligibility,
)
from src.research.run_market_breath_analysis_v1 import (
    INTERVAL_SECONDS,
    fetch_assets,
    fmt_ts,
    latest_asof_ts,
    parse_ts,
)
from src.research.run_position_rotation_preview_v1 import (
    classify_rotation,
    dec,
    market_candidate_quality_score,
    rank_market_candidates,
    risk_state_for_advice,
    target_state_for_advice,
)


REPORT_NAME = "rotation_destination_outcome_audit_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_DIR = "data/research/rotation_destination_outcome_audit_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

EVENT_TABLE_CSV = "event_table_v1.csv"
EVENT_TABLE_JSONL = "event_table_v1.jsonl"
EVENT_TABLE_DEDUP_DESTINATION_CSV = "event_table_dedup_destination_v1.csv"
EVENT_TABLE_DEDUP_DESTINATION_JSONL = "event_table_dedup_destination_v1.jsonl"
SUMMARY_BY_CONFIDENCE_CSV = "summary_by_confidence_v1.csv"
SUMMARY_BY_REASON_CSV = "summary_by_reason_v1.csv"
SUMMARY_BY_CONFIDENCE_DEDUP_CSV = "summary_by_confidence_dedup_v1.csv"
SUMMARY_BY_REASON_DEDUP_CSV = "summary_by_reason_dedup_v1.csv"
SUMMARY_BY_CURVE_SANITY_DEDUP_CSV = "summary_by_curve_sanity_dedup_v1.csv"
MANIFEST_JSON = "manifest_v1.json"
REPORT_MD = "report_v1.md"

FORWARD_HORIZONS_HOURS = (1, 4, 24, 72)
MAX_HORIZON_HOURS = 72
MAE_MFE_HORIZON_HOURS = 24

SAFETY_MARKERS = {
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
}

EVENT_COLUMNS = [
    "asof_ts",
    "source_symbol",
    "destination_symbol",
    "destination_score",
    "destination_eligible",
    "destination_confidence",
    "destination_exclusion_reasons",
    "aplus_state",
    "aplus_freshness",
    "curve_sanity_label",
    "source_rotation_state",
    "destination_policy_label",
    "return_1h",
    "return_4h",
    "return_24h",
    "return_72h",
    "max_adverse_excursion_24h",
    "max_favorable_excursion_24h",
]


@dataclass(frozen=True)
class OutputPaths:
    event_csv: Path
    event_jsonl: Path
    event_dedup_destination_csv: Path
    event_dedup_destination_jsonl: Path
    summary_by_confidence_csv: Path
    summary_by_reason_csv: Path
    summary_by_confidence_dedup_csv: Path
    summary_by_reason_dedup_csv: Path
    summary_by_curve_sanity_dedup_csv: Path
    manifest_json: Path
    report_md: Path


@dataclass(frozen=True)
class CandlePoint:
    asset_id: int
    close_ts_utc: datetime
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal


@dataclass(frozen=True)
class DestinationContext:
    advice: dict[str, Any] | None
    current_price: Decimal | None
    target_state: str
    risk_state: str
    entry_display_state: str
    price_progress_state: str
    price_progress_labels: tuple[str, ...]
    lifecycle_state: str
    recompute_needed: bool
    recompute_reason: str
    next_zone_state: str
    next_reaction_zone_label: str
    next_target_zone_label: str
    next_target_zone: tuple[Decimal, Decimal] | None
    action_display: str
    confirmation_state: str
    policy_label: str
    eligibility: DestinationEligibility
    confidence: DestinationConfidence


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backtest rotation destination quality from historical paper advice and candles "
            "(research-only, market-only by default, file-output only)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--sample-step-hours", type=int, default=24)
    parser.add_argument("--max-events", type=int, default=1000)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def parse_symbols(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    symbols: list[str] = []
    for value in values:
        symbols.extend(part.strip().upper() for part in str(value).split(",") if part.strip())
    return sorted(dict.fromkeys(symbols)) or None


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.replace(tzinfo=UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_output_dir(*, requested_output_dir: str | None, run_id: str) -> Path:
    if requested_output_dir:
        return Path(requested_output_dir)
    return Path(DEFAULT_OUTPUT_DIR) / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    return str(value)


def decimal_text(value: Any, places: str = "0.000001") -> str:
    if value is None:
        return ""
    value_dec = dec(value)
    if value_dec is None:
        return ""
    try:
        return str(value_dec.quantize(Decimal(places)))
    except Exception:
        return str(value_dec)


def pct_return(base_price: Decimal | None, future_price: Decimal | None) -> Decimal | None:
    if base_price is None or future_price is None or base_price <= 0:
        return None
    return ((future_price / base_price) - Decimal("1")) * Decimal("100")


def pct_text(value: Decimal | None) -> str:
    return decimal_text(value, "0.000001")


def fetch_sample_asofs(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
    sample_step_hours: int,
) -> list[datetime]:
    sql = """
        SELECT DISTINCT asof_ts_utc
        FROM paper_advice_observation
        WHERE venue = %s
          AND interval_code = %s
          AND asof_ts_utc >= %s
          AND asof_ts_utc <= %s
        ORDER BY asof_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, from_ts, to_ts))
        rows = list(cur.fetchall())

    available = [row["asof_ts_utc"] for row in rows if row.get("asof_ts_utc") is not None]
    if sample_step_hours <= 0:
        return available

    selected: list[datetime] = []
    next_allowed: datetime | None = None
    step = timedelta(hours=sample_step_hours)
    for asof_ts in available:
        if next_allowed is None or asof_ts >= next_allowed:
            selected.append(asof_ts)
            next_allowed = asof_ts + step
    return selected


def fetch_advice_by_symbol(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    symbols: list[str] | None,
) -> dict[str, dict[str, Any]]:
    params: list[Any] = [venue, interval_code, asof_ts]
    symbol_filter = ""
    if symbols:
        placeholders = ", ".join(["%s"] * len(symbols))
        symbol_filter = f"AND symbol IN ({placeholders})"
        params.extend(symbols)

    sql = f"""
        SELECT p.*
        FROM paper_advice_observation p
        WHERE p.venue = %s
          AND p.interval_code = %s
          AND p.asof_ts_utc = %s
          {symbol_filter}
        ORDER BY p.symbol, p.policy_name, p.policy_version, p.paper_advice_observation_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def fetch_asof_candles_by_asset(
    conn: Any,
    *,
    asset_ids: list[int],
    venue: str,
    interval_code: str,
    asof_ts: datetime,
) -> dict[int, CandlePoint]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        WITH latest_candle AS (
            SELECT asset_id, MAX(close_ts_utc) AS close_ts_utc
            FROM obs_market_candle
            WHERE venue = %s
              AND interval_code = %s
              AND close_ts_utc <= %s
              AND asset_id IN ({placeholders})
            GROUP BY asset_id
        )
        SELECT
            c.asset_id,
            c.close_ts_utc,
            c.close_price,
            c.high_price,
            c.low_price
        FROM obs_market_candle c
        JOIN latest_candle lc
          ON lc.asset_id = c.asset_id
         AND lc.close_ts_utc = c.close_ts_utc
        WHERE c.venue = %s
          AND c.interval_code = %s
    """
    params: list[Any] = [venue, interval_code, asof_ts, *asset_ids, venue, interval_code]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    return {
        int(row["asset_id"]): CandlePoint(
            asset_id=int(row["asset_id"]),
            close_ts_utc=row["close_ts_utc"],
            close_price=Decimal(str(row["close_price"])),
            high_price=Decimal(str(row["high_price"])),
            low_price=Decimal(str(row["low_price"])),
        )
        for row in rows
        if row.get("close_price") is not None
    }


def fetch_future_candles_by_asset(
    conn: Any,
    *,
    asset_ids: list[int],
    venue: str,
    interval_code: str,
    min_base_ts: datetime,
    max_base_ts: datetime,
) -> dict[int, list[CandlePoint]]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    max_end_ts = max_base_ts + timedelta(hours=MAX_HORIZON_HOURS)
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
    params: list[Any] = [venue, interval_code, min_base_ts, max_end_ts, *asset_ids]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    grouped: dict[int, list[CandlePoint]] = defaultdict(list)
    for row in rows:
        if row.get("close_price") is None:
            continue
        grouped[int(row["asset_id"])].append(
            CandlePoint(
                asset_id=int(row["asset_id"]),
                close_ts_utc=row["close_ts_utc"],
                close_price=Decimal(str(row["close_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
            )
        )
    return dict(grouped)


def fetch_historical_aplus_legacy_rows(
    conn: Any,
    *,
    asof_ts: datetime,
) -> dict[str, dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                aplus_table1_report_id,
                prediction_ts_utc
            FROM aplus_table1_report
            WHERE row_count > 0
              AND prediction_ts_utc <= %s
            ORDER BY prediction_ts_utc DESC, aplus_table1_report_id DESC
            LIMIT 1
            """,
            (asof_ts,),
        )
        report = cur.fetchone()
        if not report:
            return {}

        report_id = int(report["aplus_table1_report_id"])
        prediction_ts = report.get("prediction_ts_utc")
        cur.execute(
            """
            SELECT token, strategic_bias
            FROM aplus_table1_row
            WHERE aplus_table1_report_id = %s
              AND validation_status = 'VALID'
            ORDER BY token
            """,
            (report_id,),
        )
        rows = list(cur.fetchall())

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("token") or "").upper()
        if not symbol:
            continue
        age_hours = None
        if prediction_ts is not None:
            age_hours = max(0.0, (asof_ts - prediction_ts.replace(tzinfo=None)).total_seconds() / 3600.0)
        freshness = aplus_legacy_freshness_state(age_hours)
        strategic_bias = str(row.get("strategic_bias") or "").lower() or None
        out[symbol] = {
            "aplus_table1_latest_prediction_ts_utc": fmt_ts(prediction_ts) if prediction_ts else None,
            "aplus_table1_age_hours": None if age_hours is None else round(age_hours, 2),
            "aplus_table1_strategic_bias": strategic_bias,
            "aplus_legacy_freshness_state": freshness,
            "aplus_legacy_block_strength": aplus_legacy_block_strength(
                strategic_bias=strategic_bias,
                freshness_state=freshness,
            ),
        }
    return out


def build_historical_market_breath_context(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: list[str],
    asof_ts: datetime,
) -> dict[str, dict[str, Any]]:
    observations = build_market_breath_observations(
        conn,
        venue=venue,
        interval_code=interval_code,
        lookback_candles=120,
        symbols=set(symbols),
        asof_ts=asof_ts,
    )
    aplus_by_symbol = fetch_historical_aplus_legacy_rows(conn, asof_ts=asof_ts)
    rows: dict[str, dict[str, Any]] = {}
    for observation in observations:
        symbol = str(observation.get("symbol") or "").upper()
        context_state, context_reason = market_breath_context_state(observation)
        aplus = aplus_by_symbol.get(symbol, {})
        rows[symbol] = {
            **observation,
            "market_breath_context_state": context_state,
            "market_breath_context_reason": context_reason,
            "aplus_table1_latest_prediction_ts_utc": aplus.get("aplus_table1_latest_prediction_ts_utc"),
            "aplus_table1_age_hours": aplus.get("aplus_table1_age_hours"),
            "aplus_table1_strategic_bias": aplus.get("aplus_table1_strategic_bias"),
            "aplus_legacy_freshness_state": aplus.get("aplus_legacy_freshness_state", "UNKNOWN"),
            "aplus_legacy_block_strength": aplus.get("aplus_legacy_block_strength", "UNKNOWN_LEGACY_CONTEXT"),
        }
    return rows


def build_destination_context(
    *,
    symbol: str,
    advice: dict[str, Any] | None,
    current_price: Decimal | None,
    market_breath_row: dict[str, Any] | None,
) -> DestinationContext:
    target_state = target_state_for_advice(advice, current_price)
    risk_state = risk_state_for_advice(advice, current_price)
    entry_state = classify_entry_zone_state(
        leg_direction=None if not advice else advice.get("leg_direction"),
        current_price=current_price,
        entry_zone_low=None if not advice else advice.get("entry_zone_low"),
        entry_zone_high=None if not advice else advice.get("entry_zone_high"),
    )
    price_progress = classify_price_progress_state(
        leg_direction=None if not advice else advice.get("leg_direction"),
        current_price=current_price,
        entry_zone_low=None if not advice else advice.get("entry_zone_low"),
        entry_zone_high=None if not advice else advice.get("entry_zone_high"),
        tp_zone_low=None if not advice else advice.get("tp_zone_low"),
        tp_zone_high=None if not advice else advice.get("tp_zone_high"),
        in_position_context=False,
    )
    entry_display_state = semantic_entry_display_state(
        entry_state=entry_state,
        price_progress_state=price_progress.progress_state,
        price_progress_labels=price_progress.labels,
    )
    confirmation_state = confirmation_display_state(
        advice_action=None if not advice else advice.get("advice_action"),
        policy_decision=None if not advice else advice.get("policy_decision"),
        entry_state=entry_state,
        price_progress_state=price_progress.progress_state,
        price_progress_labels=price_progress.labels,
    )
    lifecycle = classify_fast_lifecycle(
        leg_direction=None if not advice else advice.get("leg_direction"),
        current_price=current_price,
        tp_zone_low=None if not advice else advice.get("tp_zone_low"),
        tp_zone_high=None if not advice else advice.get("tp_zone_high"),
        invalidation_price=None if not advice else advice.get("invalidation_price"),
    )
    next_preview = preview_next_zones(
        symbol=symbol,
        leg_direction=None if not advice else advice.get("leg_direction"),
        current_price=current_price,
        entry_zone_low=None if not advice else advice.get("entry_zone_low"),
        entry_zone_high=None if not advice else advice.get("entry_zone_high"),
        tp_zone_low=None if not advice else advice.get("tp_zone_low"),
        tp_zone_high=None if not advice else advice.get("tp_zone_high"),
        invalidation_price=None if not advice else advice.get("invalidation_price"),
        lifecycle_state=lifecycle.lifecycle_state,
        lifecycle_reason=lifecycle.recompute_reason,
        target_state=target_state,
        price_progress_state=price_progress.progress_state,
    )
    action_display = semantic_advice_action_display(
        advice_action=None if not advice else advice.get("advice_action"),
        lifecycle_state=lifecycle.lifecycle_state,
        intrabar_state=None,
    )
    block_display = classify_policy_block_display(
        advice,
        lifecycle_state=lifecycle.lifecycle_state,
        recompute_needed=lifecycle.recompute_needed,
        recompute_reason=lifecycle.recompute_reason,
        target_state=target_state,
        entry_state=entry_display_state,
        price_progress_state=price_progress.progress_state,
        market_breath_row=market_breath_row,
    )
    policy_label = "ALLOW_OR_UNBLOCKED" if block_display is None else block_display.display_policy_label
    eligibility = evaluate_rotation_destination_eligibility(
        advice,
        current_price=current_price,
        target_state=target_state,
        risk_state=risk_state,
        lifecycle_state=lifecycle.lifecycle_state,
        recompute_needed=lifecycle.recompute_needed,
        recompute_reason=lifecycle.recompute_reason,
        policy_label=None if block_display is None else block_display.display_policy_label,
        action_label=action_display,
        entry_state=entry_display_state,
        price_progress_state=price_progress.progress_state,
        price_progress_labels=price_progress.labels,
        next_zone_state=next_preview.next_zone_state,
        next_reaction_zone_label=next_preview.next_reaction_zone_label,
        next_target_zone_label=next_preview.next_target_zone_label,
        next_target_zone=next_preview.next_target_zone,
    )
    confidence = destination_confidence(
        advice,
        market_breath_row=market_breath_row,
        target_state=target_state,
        risk_state=risk_state,
        lifecycle_state=lifecycle.lifecycle_state,
        recompute_reason=lifecycle.recompute_reason,
        price_progress_state=price_progress.progress_state,
        price_progress_labels=price_progress.labels,
        next_zone_state=next_preview.next_zone_state,
        next_reaction_zone_label=next_preview.next_reaction_zone_label,
        next_target_zone_label=next_preview.next_target_zone_label,
        confirmation_state=confirmation_state,
    )
    return DestinationContext(
        advice=advice,
        current_price=current_price,
        target_state=target_state,
        risk_state=risk_state,
        entry_display_state=entry_display_state,
        price_progress_state=price_progress.progress_state,
        price_progress_labels=price_progress.labels,
        lifecycle_state=lifecycle.lifecycle_state,
        recompute_needed=lifecycle.recompute_needed,
        recompute_reason=lifecycle.recompute_reason,
        next_zone_state=next_preview.next_zone_state,
        next_reaction_zone_label=next_preview.next_reaction_zone_label,
        next_target_zone_label=next_preview.next_target_zone_label,
        next_target_zone=next_preview.next_target_zone,
        action_display=action_display,
        confirmation_state=confirmation_state,
        policy_label=policy_label,
        eligibility=eligibility,
        confidence=confidence,
    )


def source_rotation_state(
    *,
    advice: dict[str, Any] | None,
    current_price: Decimal | None,
) -> str:
    target_state = target_state_for_advice(advice, current_price)
    risk_state = risk_state_for_advice(advice, current_price)
    state, _score, _reasons = classify_rotation(
        position_row={},
        advice_row=advice,
        position_source_state="FRESH",
        target_state=target_state,
        risk_state=risk_state,
    )
    return state


def outcome_metrics(
    *,
    base: CandlePoint | None,
    future_candles: list[CandlePoint],
) -> dict[str, str]:
    if base is None or base.close_price <= 0:
        return {
            "return_1h": "",
            "return_4h": "",
            "return_24h": "",
            "return_72h": "",
            "max_adverse_excursion_24h": "",
            "max_favorable_excursion_24h": "",
        }

    returns: dict[str, str] = {}
    for horizon in FORWARD_HORIZONS_HOURS:
        target_ts = base.close_ts_utc + timedelta(hours=horizon)
        future = next((candle for candle in future_candles if candle.close_ts_utc >= target_ts), None)
        returns[f"return_{horizon}h"] = pct_text(
            pct_return(base.close_price, None if future is None else future.close_price)
        )

    path_end = base.close_ts_utc + timedelta(hours=MAE_MFE_HORIZON_HOURS)
    path = [candle for candle in future_candles if candle.close_ts_utc <= path_end]
    max_high = max((candle.high_price for candle in path), default=None)
    min_low = min((candle.low_price for candle in path), default=None)
    returns["max_adverse_excursion_24h"] = pct_text(pct_return(base.close_price, min_low))
    returns["max_favorable_excursion_24h"] = pct_text(pct_return(base.close_price, max_high))
    return returns


def event_reason_labels(row: dict[str, Any]) -> list[str]:
    labels = [
        str(row.get("destination_confidence") or ""),
        str(row.get("curve_sanity_label") or ""),
        str(row.get("destination_policy_label") or ""),
    ]
    labels.extend(row.get("_evidence_labels") or [])
    labels.extend(row.get("_exclusion_reasons") or [])
    if row.get("_clean_actionable"):
        labels.append("CLEAN_DESTINATION")
    else:
        labels.append("EXCLUDED_OR_LOW_CONFIDENCE_DESTINATION")
    return [label for label in dict.fromkeys(labels) if label]


def build_events_for_asof(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    symbols: list[str] | None,
    remaining_events: int,
) -> list[dict[str, Any]]:
    advice_by_symbol = fetch_advice_by_symbol(
        conn,
        venue=venue,
        interval_code=interval_code,
        asof_ts=asof_ts,
        symbols=symbols,
    )
    if not advice_by_symbol:
        return []

    asset_ids = sorted(
        {
            int(row["asset_id"])
            for row in advice_by_symbol.values()
            if row.get("asset_id") is not None
        }
    )
    asof_candles = fetch_asof_candles_by_asset(
        conn,
        asset_ids=asset_ids,
        venue=venue,
        interval_code=interval_code,
        asof_ts=asof_ts,
    )
    price_by_symbol = {
        symbol: asof_candles[int(row["asset_id"])].close_price
        for symbol, row in advice_by_symbol.items()
        if row.get("asset_id") is not None and int(row["asset_id"]) in asof_candles
    }
    if not price_by_symbol:
        return []

    base_times = [candle.close_ts_utc for candle in asof_candles.values()]
    future_by_asset = fetch_future_candles_by_asset(
        conn,
        asset_ids=asset_ids,
        venue=venue,
        interval_code=interval_code,
        min_base_ts=min(base_times),
        max_base_ts=max(base_times),
    )
    market_breath_by_symbol = build_historical_market_breath_context(
        conn,
        venue=venue,
        interval_code=interval_code,
        symbols=sorted(advice_by_symbol),
        asof_ts=asof_ts,
    )
    ranked_candidates = rank_market_candidates(advice_by_symbol, price_by_symbol)

    context_by_symbol = {
        symbol: build_destination_context(
            symbol=symbol,
            advice=advice_by_symbol.get(symbol),
            current_price=price_by_symbol.get(symbol),
            market_breath_row=market_breath_by_symbol.get(symbol),
        )
        for symbol in advice_by_symbol
    }
    source_state_by_symbol = {
        symbol: source_rotation_state(
            advice=advice_by_symbol.get(symbol),
            current_price=price_by_symbol.get(symbol),
        )
        for symbol in advice_by_symbol
    }

    events: list[dict[str, Any]] = []
    for source_symbol in sorted(advice_by_symbol):
        source_quality = market_candidate_quality_score(advice_by_symbol.get(source_symbol))
        for destination_symbol, destination_score in ranked_candidates:
            if destination_symbol == source_symbol:
                continue
            if destination_score <= source_quality:
                continue

            destination_advice = advice_by_symbol.get(destination_symbol)
            asset_id = None if not destination_advice else int(destination_advice["asset_id"])
            base_candle = None if asset_id is None else asof_candles.get(asset_id)
            metrics = outcome_metrics(
                base=base_candle,
                future_candles=[] if asset_id is None else future_by_asset.get(asset_id, []),
            )
            context = context_by_symbol[destination_symbol]
            market_breath_row = market_breath_by_symbol.get(destination_symbol) or {}
            event = {
                "asof_ts": fmt_ts(asof_ts),
                "source_symbol": source_symbol,
                "destination_symbol": destination_symbol,
                "destination_score": decimal_text(destination_score, "0.01"),
                "destination_eligible": "1" if context.eligibility.eligible else "0",
                "destination_confidence": context.confidence.confidence_label,
                "destination_exclusion_reasons": ";".join(context.eligibility.exclusion_reasons),
                "aplus_state": "" if destination_advice is None else str(destination_advice.get("aplus_bucket") or ""),
                "aplus_freshness": str(market_breath_row.get("aplus_legacy_freshness_state") or "UNKNOWN"),
                "curve_sanity_label": context.confidence.curve_sanity_label,
                "source_rotation_state": source_state_by_symbol[source_symbol],
                "destination_policy_label": context.policy_label,
                **metrics,
                "_clean_actionable": bool(context.eligibility.eligible and context.confidence.clean_actionable),
                "_evidence_labels": context.confidence.evidence_labels,
                "_exclusion_reasons": context.eligibility.exclusion_reasons,
            }
            events.append(event)
            if len(events) >= remaining_events:
                return events
    return events


def numeric_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row.get(field)
        if raw in (None, ""):
            continue
        try:
            values.append(float(raw))
        except ValueError:
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


def summary_row(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return_24h = numeric_values(rows, "return_24h")
    return_72h = numeric_values(rows, "return_72h")
    return {
        "label": label,
        "event_count": len(rows),
        "eligible_count": sum(1 for row in rows if row.get("destination_eligible") == "1"),
        "clean_actionable_count": sum(1 for row in rows if row.get("_clean_actionable")),
        "avg_return_1h": avg(numeric_values(rows, "return_1h")),
        "avg_return_4h": avg(numeric_values(rows, "return_4h")),
        "avg_return_24h": avg(return_24h),
        "median_return_24h": median_or_none(return_24h),
        "positive_rate_24h": positive_rate(return_24h),
        "avg_return_72h": avg(return_72h),
        "median_return_72h": median_or_none(return_72h),
        "positive_rate_72h": positive_rate(return_72h),
        "avg_max_adverse_excursion_24h": avg(numeric_values(rows, "max_adverse_excursion_24h")),
        "avg_max_favorable_excursion_24h": avg(numeric_values(rows, "max_favorable_excursion_24h")),
    }


def build_summary_by_confidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = sorted({str(row.get("destination_confidence") or "") for row in rows if row.get("destination_confidence")})
    return [summary_row(label, [row for row in rows if row.get("destination_confidence") == label]) for label in labels]


def build_summary_by_reason(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_reason: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for label in event_reason_labels(row):
            by_reason[label].append(row)
    return [summary_row(label, by_reason[label]) for label in sorted(by_reason)]


def build_summary_by_field(rows: list[dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    labels = sorted(
        {
            str(row.get(field_name) or "")
            for row in rows
            if str(row.get(field_name) or "")
        }
    )
    return [summary_row(label, [row for row in rows if str(row.get(field_name) or "") == label]) for label in labels]


def dedup_destination_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        dedup_key = (
            str(row.get("asof_ts") or ""),
            str(row.get("destination_symbol") or ""),
        )
        current = best_by_key.get(dedup_key)
        if current is None:
            best_by_key[dedup_key] = row
            continue

        row_score = dec(row.get("destination_score")) or Decimal("-999999")
        current_score = dec(current.get("destination_score")) or Decimal("-999999")
        row_source = str(row.get("source_symbol") or "")
        current_source = str(current.get("source_symbol") or "")
        if row_score > current_score or (row_score == current_score and row_source < current_source):
            best_by_key[dedup_key] = row

    deduped = list(best_by_key.values())
    deduped.sort(
        key=lambda row: (
            str(row.get("asof_ts") or ""),
            str(row.get("destination_symbol") or ""),
            -(dec(row.get("destination_score")) or Decimal("0")),
            str(row.get("source_symbol") or ""),
        )
    )
    return deduped


def output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        event_csv=output_dir / EVENT_TABLE_CSV,
        event_jsonl=output_dir / EVENT_TABLE_JSONL,
        event_dedup_destination_csv=output_dir / EVENT_TABLE_DEDUP_DESTINATION_CSV,
        event_dedup_destination_jsonl=output_dir / EVENT_TABLE_DEDUP_DESTINATION_JSONL,
        summary_by_confidence_csv=output_dir / SUMMARY_BY_CONFIDENCE_CSV,
        summary_by_reason_csv=output_dir / SUMMARY_BY_REASON_CSV,
        summary_by_confidence_dedup_csv=output_dir / SUMMARY_BY_CONFIDENCE_DEDUP_CSV,
        summary_by_reason_dedup_csv=output_dir / SUMMARY_BY_REASON_DEDUP_CSV,
        summary_by_curve_sanity_dedup_csv=output_dir / SUMMARY_BY_CURVE_SANITY_DEDUP_CSV,
        manifest_json=output_dir / MANIFEST_JSON,
        report_md=output_dir / REPORT_MD,
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            public_row = {key: value for key, value in row.items() if not key.startswith("_")}
            handle.write(json.dumps(public_row, sort_keys=True, ensure_ascii=True, default=json_default) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def render_report(
    *,
    manifest: dict[str, Any],
    raw_summary_by_confidence: list[dict[str, Any]],
    dedup_summary_by_confidence: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Rotation Destination Outcome Audit V1",
        "",
        "Research-only audit of rotation destination quality using historical paper-advice snapshots and forward candles.",
        "",
        "## Scope",
        "",
        "- Reads historical `paper_advice_observation`, `obs_market_candle`, `asset`, and historical A+ report rows.",
        "- Does not write DB rows, call brokers, submit orders, or change runtime behavior.",
        "- Forward returns are future-aware research outcomes and must stay inside research outputs.",
        "",
        "## Run",
        "",
        f"- venue: `{manifest['venue']}`",
        f"- interval: `{manifest['interval_code']}`",
        f"- from_ts: `{manifest['from_ts']}`",
        f"- to_ts: `{manifest['to_ts']}`",
        f"- sample_count: `{manifest['sample_count']}`",
        f"- raw_event_count: `{manifest['raw_event_count']}`",
        f"- dedup_destination_event_count: `{manifest['dedup_destination_event_count']}`",
        "",
        "## Interpretation",
        "",
        "- Raw view is source-weighted: the same destination can appear multiple times at one as-of when several held source symbols point to it.",
        "- Destination-dedup view keeps one row per `asof_ts + destination_symbol`, choosing the highest `destination_score` and then `source_symbol` ascending as the deterministic tie-breaker.",
        "",
        "## Raw By Confidence",
        "",
        "| label | events | avg_24h | median_24h | positive_24h | avg_mae_24h | avg_mfe_24h |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in raw_summary_by_confidence:
        lines.append(
            f"| {row['label']} | {row['event_count']} | {row['avg_return_24h']} | "
            f"{row['median_return_24h']} | {row['positive_rate_24h']} | "
            f"{row['avg_max_adverse_excursion_24h']} | {row['avg_max_favorable_excursion_24h']} |"
        )

    lines.extend(
        [
            "",
            "## Dedup By Confidence",
            "",
            "| label | events | avg_24h | median_24h | positive_24h | avg_mae_24h | avg_mfe_24h |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in dedup_summary_by_confidence:
        lines.append(
            f"| {row['label']} | {row['event_count']} | {row['avg_return_24h']} | "
            f"{row['median_return_24h']} | {row['positive_rate_24h']} | "
            f"{row['avg_max_adverse_excursion_24h']} | {row['avg_max_favorable_excursion_24h']} |"
        )

    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- db_writes: `{manifest['db_writes']}`",
            f"- broker_calls: `{manifest['broker_calls']}`",
            f"- broker_writes: `{manifest['broker_writes']}`",
            f"- order_submission: `{manifest['order_submission']}`",
            f"- live_orders: `{manifest['live_orders']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def render_table(
    manifest: dict[str, Any],
    raw_summary_by_confidence: list[dict[str, Any]],
    dedup_summary_by_confidence: list[dict[str, Any]],
) -> str:
    lines = [
        f"[RUN][ID] {manifest['run_id']}",
        f"[RUN][OUT_DIR] {manifest['output_dir']}",
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only point-in-time outcome audit",
        "input=paper_advice_observation obs_market_candle asset aplus_table1_report aplus_table1_row",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        f"venue={manifest['venue']} interval={manifest['interval_code']}",
        (
            f"from_ts={manifest['from_ts']} to_ts={manifest['to_ts']} sample_count={manifest['sample_count']} "
            f"raw_event_count={manifest['raw_event_count']} dedup_destination_event_count={manifest['dedup_destination_event_count']}"
        ),
        "",
        "--- raw summary by confidence ---",
    ]
    for row in raw_summary_by_confidence:
        lines.append(
            "  "
            f"{row['label']} count={row['event_count']} clean={row['clean_actionable_count']} "
            f"avg_24h={row['avg_return_24h']} median_24h={row['median_return_24h']} "
            f"positive_24h={row['positive_rate_24h']} mae24={row['avg_max_adverse_excursion_24h']} "
            f"mfe24={row['avg_max_favorable_excursion_24h']}"
        )
    lines.append("")
    lines.append("--- dedup summary by confidence ---")
    for row in dedup_summary_by_confidence:
        lines.append(
            "  "
            f"{row['label']} count={row['event_count']} clean={row['clean_actionable_count']} "
            f"avg_24h={row['avg_return_24h']} median_24h={row['median_return_24h']} "
            f"positive_24h={row['positive_rate_24h']} mae24={row['avg_max_adverse_excursion_24h']} "
            f"mfe24={row['avg_max_favorable_excursion_24h']}"
        )
    lines.append("")
    lines.append(f"wrote_files={manifest['wrote_files']}")
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
            lines.append(f"  wrote_file[{key}]={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    out_dir: Path,
    from_ts: datetime,
    to_ts: datetime,
    sample_count: int,
    raw_event_count: int,
    dedup_destination_event_count: int,
    paths: OutputPaths,
    wrote_files: bool,
    run_started_at: datetime,
    run_finished_at: datetime,
    run_duration_sec: float,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(out_dir),
        "run_started_at_utc": fmt_ts(run_started_at.replace(tzinfo=None)),
        "run_finished_at_utc": fmt_ts(run_finished_at.replace(tzinfo=None)),
        "run_duration_sec": round(run_duration_sec, 6),
        "exit_code": int(exit_code),
        "venue": args.venue,
        "interval_code": args.interval,
        "from_ts": fmt_ts(from_ts),
        "to_ts": fmt_ts(to_ts),
        "symbols": parse_symbols(args.symbols),
        "sample_step_hours": int(args.sample_step_hours),
        "max_events": int(args.max_events),
        "sample_count": int(sample_count),
        "event_count": int(raw_event_count),
        "raw_event_count": int(raw_event_count),
        "dedup_destination_event_count": int(dedup_destination_event_count),
        "wrote_files": bool(wrote_files),
        "output_paths": {
            "event_table_csv": str(paths.event_csv),
            "event_table_jsonl": str(paths.event_jsonl),
            "event_table_dedup_destination_csv": str(paths.event_dedup_destination_csv),
            "event_table_dedup_destination_jsonl": str(paths.event_dedup_destination_jsonl),
            "summary_by_confidence_csv": str(paths.summary_by_confidence_csv),
            "summary_by_reason_csv": str(paths.summary_by_reason_csv),
            "summary_by_confidence_dedup_csv": str(paths.summary_by_confidence_dedup_csv),
            "summary_by_reason_dedup_csv": str(paths.summary_by_reason_dedup_csv),
            "summary_by_curve_sanity_dedup_csv": str(paths.summary_by_curve_sanity_dedup_csv),
            "manifest_json": str(paths.manifest_json),
            "report_md": str(paths.report_md),
        },
        "notes": [
            "Forward return horizons use the first selected-interval candle close at or after the target horizon.",
            "A+ context is selected point-in-time from the latest A+ Table 1 report at or before each as-of.",
            "This runner measures outcomes only and does not tune or promote runtime behavior.",
        ],
        **SAFETY_MARKERS,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {args.interval}")
    if args.sample_step_hours <= 0:
        raise ValueError("--sample-step-hours must be > 0")
    if args.max_events <= 0:
        raise ValueError("--max-events must be > 0")

    run_started_at = datetime.now(UTC)
    started = perf_counter()
    run_id = utc_run_id(run_started_at)
    out_dir = resolve_output_dir(requested_output_dir=args.output_dir, run_id=run_id)
    paths = output_paths(out_dir)
    symbols = parse_symbols(args.symbols)

    conn = get_connection()
    try:
        latest_ts = latest_asof_ts(conn, args.venue, args.interval)
        default_to_ts = latest_ts - timedelta(hours=MAX_HORIZON_HOURS)
        to_ts = parse_ts(args.to_ts) if args.to_ts else default_to_ts
        from_ts = parse_ts(args.from_ts) if args.from_ts else to_ts - timedelta(days=30)
        if from_ts > to_ts:
            raise ValueError("--from-ts must be <= --to-ts")

        # Validate candle/asset access early and keep this explicitly read-only.
        fetch_assets(conn)
        asof_samples = fetch_sample_asofs(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            from_ts=from_ts,
            to_ts=to_ts,
            sample_step_hours=args.sample_step_hours,
        )

        events: list[dict[str, Any]] = []
        for asof_ts in asof_samples:
            if len(events) >= args.max_events:
                break
            events.extend(
                build_events_for_asof(
                    conn,
                    venue=args.venue,
                    interval_code=args.interval,
                    asof_ts=asof_ts,
                    symbols=symbols,
                    remaining_events=int(args.max_events) - len(events),
                )
            )
        conn.rollback()
    finally:
        conn.close()

    dedup_destination_events_rows = dedup_destination_events(events)
    summary_by_confidence = build_summary_by_confidence(events)
    summary_by_reason = build_summary_by_reason(events)
    summary_by_confidence_dedup = build_summary_by_confidence(dedup_destination_events_rows)
    summary_by_reason_dedup = build_summary_by_reason(dedup_destination_events_rows)
    summary_by_curve_sanity_dedup = build_summary_by_field(
        dedup_destination_events_rows,
        "curve_sanity_label",
    )
    run_finished_at = datetime.now(UTC)
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        out_dir=out_dir,
        from_ts=from_ts,
        to_ts=to_ts,
        sample_count=len(asof_samples),
        raw_event_count=len(events),
        dedup_destination_event_count=len(dedup_destination_events_rows),
        paths=paths,
        wrote_files=bool(args.write_files),
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        run_duration_sec=perf_counter() - started,
        exit_code=0,
    )

    if args.write_files:
        write_csv(paths.event_csv, events, EVENT_COLUMNS)
        write_jsonl(paths.event_jsonl, events)
        write_csv(paths.event_dedup_destination_csv, dedup_destination_events_rows, EVENT_COLUMNS)
        write_jsonl(paths.event_dedup_destination_jsonl, dedup_destination_events_rows)
        summary_fields = list(summary_row("FIELDNAMES", []).keys())
        write_csv(paths.summary_by_confidence_csv, summary_by_confidence, summary_fields)
        write_csv(paths.summary_by_reason_csv, summary_by_reason, summary_fields)
        write_csv(paths.summary_by_confidence_dedup_csv, summary_by_confidence_dedup, summary_fields)
        write_csv(paths.summary_by_reason_dedup_csv, summary_by_reason_dedup, summary_fields)
        write_csv(paths.summary_by_curve_sanity_dedup_csv, summary_by_curve_sanity_dedup, summary_fields)
        write_json(paths.manifest_json, manifest)
        paths.report_md.write_text(
            render_report(
                manifest=manifest,
                raw_summary_by_confidence=summary_by_confidence,
                dedup_summary_by_confidence=summary_by_confidence_dedup,
            ),
            encoding="utf-8",
        )

    if args.output == "json":
        print(f"[RUN][ID] {manifest['run_id']}")
        print(f"[RUN][OUT_DIR] {manifest['output_dir']}")
        if manifest["wrote_files"]:
            for key, value in manifest["output_paths"].items():
                print(f"wrote_file[{key}]={value}")
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, default=json_default))
    else:
        print(render_table(manifest, summary_by_confidence, summary_by_confidence_dedup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
