from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.research.run_market_breath_analysis_v1 import (
    add_breadth_and_scores,
    build_base_observation,
    fetch_assets,
    fetch_candles,
    fmt_ts,
    latest_asof_ts,
    parse_ts,
    safe_return,
)


REPORT_NAME = "market_breath_context_bridge_v1"
VERSION = "0.1"

DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_LOOKBACK_CANDLES = 120

CONTEXT_BY_PHASE = {
    "INHALE_ACCUMULATION": "MARKET_BREATH_ACCUMULATION_CONTEXT",
    "OVERBREATH_EXTENSION": "MARKET_BREATH_LATE_RISK_CONTEXT",
    "COLLAPSE_RESET": "MARKET_BREATH_RESET_CONTEXT",
    "NEUTRAL_TRANSITION": "MARKET_BREATH_NEUTRAL_CONTEXT",
    "HOLD_COMPRESSION": "MARKET_BREATH_COMPRESSION_CONTEXT",
    "INSUFFICIENT_DATA": "MARKET_BREATH_UNKNOWN",
}

APLUS_FRESHNESS_FRESH_HOURS = 24.0
APLUS_FRESHNESS_AGING_HOURS = 72.0
APLUS_FRESHNESS_STALE_HOURS = 120.0


@dataclass(frozen=True)
class AplusLegacyRow:
    prediction_ts_utc: datetime | None
    strategic_bias: str | None


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    return str(value)


def _upper_symbols(symbols: list[str] | None) -> set[str] | None:
    if not symbols:
        return None
    return {symbol.strip().upper() for symbol in symbols if symbol.strip()}


def market_breath_context_state(row: dict[str, Any]) -> tuple[str, str]:
    phase = str(row.get("market_breath_phase") or "").upper()
    state = str(row.get("market_breath_state") or "").upper()
    momentum = float(row.get("momentum_score") or 0.0)
    relative_strength = float(row.get("relative_strength_score") or 0.0)

    if phase == "EXHALE_EXPANSION":
        if momentum > 0.0 and relative_strength > 0.0:
            return (
                "MARKET_BREATH_EXPANSION_CONTEXT",
                "EXHALE_EXPANSION with positive momentum and relative strength.",
            )
        return (
            "MARKET_BREATH_NEUTRAL_CONTEXT",
            "EXHALE_EXPANSION phase lacks positive momentum or relative strength confirmation.",
        )

    context_state = CONTEXT_BY_PHASE.get(phase, "MARKET_BREATH_UNKNOWN")
    return context_state, f"{phase or 'UNKNOWN'} / {state or 'UNKNOWN'} mapped to {context_state}."


def aplus_legacy_freshness_state(age_hours: float | None) -> str:
    if age_hours is None:
        return "UNKNOWN"
    if age_hours <= APLUS_FRESHNESS_FRESH_HOURS:
        return "FRESH"
    if age_hours <= APLUS_FRESHNESS_AGING_HOURS:
        return "AGING"
    if age_hours <= APLUS_FRESHNESS_STALE_HOURS:
        return "STALE"
    return "VERY_STALE"


def aplus_legacy_block_strength(*, strategic_bias: str | None, freshness_state: str) -> str:
    bias = (strategic_bias or "").strip().lower()
    if bias != "avoid":
        return "NONE"
    if freshness_state in {"STALE", "VERY_STALE"}:
        return "LEGACY_CONTEXT_ONLY"
    if freshness_state in {"FRESH", "AGING"}:
        return "READ_ONLY_APLUS_AVOID"
    return "UNKNOWN_LEGACY_CONTEXT"


def fetch_latest_aplus_legacy_rows(conn: Any) -> dict[str, AplusLegacyRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                aplus_table1_report_id,
                prediction_ts_utc
            FROM aplus_table1_report
            WHERE row_count > 0
            ORDER BY prediction_ts_utc DESC, aplus_table1_report_id DESC
            LIMIT 1
            """
        )
        report = cur.fetchone()

        if not report:
            return {}

        report_id = int(report["aplus_table1_report_id"])
        prediction_ts = report.get("prediction_ts_utc")

        cur.execute(
            """
            SELECT
                token,
                strategic_bias
            FROM aplus_table1_row
            WHERE aplus_table1_report_id = %s
              AND validation_status = 'VALID'
            ORDER BY token
            """,
            (report_id,),
        )
        rows = list(cur.fetchall())

    out: dict[str, AplusLegacyRow] = {}
    for row in rows:
        token = str(row.get("token") or "").upper()
        if not token:
            continue
        out[token] = AplusLegacyRow(
            prediction_ts_utc=prediction_ts,
            strategic_bias=str(row.get("strategic_bias") or "").lower() or None,
        )
    return out


def build_market_breath_observations(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    lookback_candles: int,
    symbols: set[str] | None = None,
    asof_ts: datetime | None = None,
) -> list[dict[str, Any]]:
    resolved_asof = asof_ts or latest_asof_ts(conn, venue, interval_code)
    assets = fetch_assets(conn)
    output_symbols = symbols

    candles_by_asset = fetch_candles(
        conn,
        assets=assets,
        venue=venue,
        interval_code=interval_code,
        asof_ts=resolved_asof,
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
            asof_ts=resolved_asof,
            btc_r6=btc_r6,
            btc_r12=btc_r12,
        )
        for asset in assets
    ]
    rows = add_breadth_and_scores(base_rows, lookback_candles)
    if output_symbols is not None:
        rows = [row for row in rows if str(row.get("symbol") or "").upper() in output_symbols]
    return rows


def build_market_breath_context_rows(
    conn: Any,
    *,
    venue: str = DEFAULT_VENUE,
    interval_code: str = DEFAULT_INTERVAL,
    lookback_candles: int = DEFAULT_LOOKBACK_CANDLES,
    symbols: list[str] | None = None,
    asof_ts: datetime | None = None,
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    symbol_filter = _upper_symbols(symbols)
    observations = build_market_breath_observations(
        conn,
        venue=venue,
        interval_code=interval_code,
        lookback_candles=lookback_candles,
        symbols=symbol_filter,
        asof_ts=asof_ts,
    )
    aplus_by_symbol = fetch_latest_aplus_legacy_rows(conn)
    age_reference = (now_utc or datetime.now(UTC)).replace(tzinfo=None)

    rows: list[dict[str, Any]] = []
    for observation in observations:
        symbol = str(observation.get("symbol") or "").upper()
        context_state, context_reason = market_breath_context_state(observation)
        aplus = aplus_by_symbol.get(symbol)
        prediction_ts = aplus.prediction_ts_utc if aplus else None
        age_hours = None
        if prediction_ts is not None:
            age = age_reference - prediction_ts.replace(tzinfo=None)
            age_hours = max(0.0, age.total_seconds() / 3600.0)
        freshness = aplus_legacy_freshness_state(age_hours)
        strategic_bias = aplus.strategic_bias if aplus else None
        block_strength = aplus_legacy_block_strength(
            strategic_bias=strategic_bias,
            freshness_state=freshness,
        )

        rows.append(
            {
                "symbol": symbol,
                "asof_ts_utc": observation.get("asof_ts_utc"),
                "market_breath_phase": observation.get("market_breath_phase"),
                "market_breath_state": observation.get("market_breath_state"),
                "market_breath_score": observation.get("market_breath_score"),
                "market_breath_confidence": observation.get("market_breath_confidence"),
                "compression_score": observation.get("compression_score"),
                "expansion_score": observation.get("expansion_score"),
                "momentum_score": observation.get("momentum_score"),
                "reversal_pressure_score": observation.get("reversal_pressure_score"),
                "relative_strength_score": observation.get("relative_strength_score"),
                "btc_alignment_score": observation.get("btc_alignment_score"),
                "breadth_alignment_score": observation.get("breadth_alignment_score"),
                "market_breath_context_state": context_state,
                "market_breath_context_reason": context_reason,
                "aplus_table1_latest_prediction_ts_utc": fmt_ts(prediction_ts) if prediction_ts else None,
                "aplus_table1_age_hours": None if age_hours is None else round(age_hours, 2),
                "aplus_table1_strategic_bias": strategic_bias,
                "aplus_legacy_freshness_state": freshness,
                "aplus_legacy_block_strength": block_strength,
            }
        )

    rows.sort(key=lambda row: row["symbol"])
    return rows


def rows_by_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("symbol") or "").upper(): row for row in rows}


def render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=reporting-helper market-only account-agnostic read-only",
        "input=asset obs_market_candle aplus_table1_report aplus_table1_row",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "",
        "symbol  asof_ts_utc           phase                  state      mb_context                         aplus_age_h  aplus_bias  aplus_freshness  aplus_block_strength",
    ]
    for row in rows:
        lines.append(
            "{symbol:<7} {asof:<21} {phase:<22} {state:<10} {context:<34} {age:<12} {bias:<11} {fresh:<16} {block}".format(
                symbol=str(row.get("symbol") or ""),
                asof=str(row.get("asof_ts_utc") or ""),
                phase=str(row.get("market_breath_phase") or ""),
                state=str(row.get("market_breath_state") or ""),
                context=str(row.get("market_breath_context_state") or ""),
                age=str(row.get("aplus_table1_age_hours") or ""),
                bias=str(row.get("aplus_table1_strategic_bias") or ""),
                fresh=str(row.get("aplus_legacy_freshness_state") or ""),
                block=str(row.get("aplus_legacy_block_strength") or ""),
            )
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expose latest Market Breath context plus read-only A+ legacy freshness diagnostics."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument("--asof-ts", default=None)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = get_connection()
    try:
        rows = build_market_breath_context_rows(
            conn,
            venue=str(args.venue),
            interval_code=str(args.interval),
            lookback_candles=int(args.lookback_candles),
            symbols=args.symbols,
            asof_ts=parse_ts(args.asof_ts) if args.asof_ts else None,
        )
        conn.rollback()
    finally:
        conn.close()

    if args.output == "json":
        print(json.dumps(rows, indent=2, sort_keys=True, default=_json_default))
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
