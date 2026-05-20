from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import (
    MarketPriceSnapshot,
    fetch_latest_prices_by_symbol,
)
from src.reporting.entry_zone_state_v1 import classify_price_progress_state
from src.reporting.fast_lifecycle_recompute_v1 import classify_fast_lifecycle


REPORT_NAME = "intrabar_lifecycle_context_v1"
VERSION = "0.1"

DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_STRUCTURAL_INTERVAL = "4h"
DEFAULT_LIFECYCLE_INTERVAL = "15m"
PRICE_SNAPSHOT_FRESH_AFTER = timedelta(minutes=10)
LTF_FRESH_AFTER = timedelta(minutes=30)
MIN_LTF_HISTORY = 4


@dataclass(frozen=True)
class IntrabarLifecycleContext:
    symbol: str
    venue: str
    structural_interval_code: str
    lifecycle_interval_code: str
    structural_zone_asof_ts_utc: str | None
    latest_15m_close_ts_utc: str | None
    current_price: Decimal | None
    price_source: str
    leg_direction: str | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    tp_zone_low: Decimal | None
    tp_zone_high: Decimal | None
    invalidation_price: Decimal | None
    intrabar_lifecycle_state: str
    intrabar_progress_state: str
    intrabar_recompute_hint: str
    intrabar_reason: str
    data_quality_state: str


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _fmt_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _age(value: datetime | None, *, now_utc: datetime) -> timedelta | None:
    if value is None:
        return None
    normalized = value.replace(tzinfo=None)
    return now_utc.replace(tzinfo=None) - normalized


def _freshness(
    *,
    price_snapshot: MarketPriceSnapshot | None,
    latest_15m_close_ts: datetime | None,
    ltf_count: int,
    now_utc: datetime,
) -> str:
    parts: list[str] = []
    price_age = None if price_snapshot is None else _age(price_snapshot.observed_ts_utc, now_utc=now_utc)
    if price_age is not None and timedelta(0) <= price_age <= PRICE_SNAPSHOT_FRESH_AFTER:
        parts.append("PRICE_SNAPSHOT_FRESH")
    elif price_snapshot is not None:
        parts.append("PRICE_SNAPSHOT_STALE")

    if latest_15m_close_ts is None:
        parts.append("LTF_MISSING")
    else:
        ltf_age = _age(latest_15m_close_ts, now_utc=now_utc)
        if ltf_count < MIN_LTF_HISTORY:
            parts.append("LTF_HISTORY_SHORT")
        if ltf_age is not None and timedelta(0) <= ltf_age <= LTF_FRESH_AFTER:
            parts.append("LTF_CANDLES_FRESH")
        else:
            parts.append("LTF_CANDLES_STALE")

    return ";".join(parts) if parts else "LTF_MISSING"


def fetch_latest_structural_zones(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    symbol_filter = ""
    params: dict[str, Any] = {"venue": venue, "interval_code": interval_code}
    if symbols:
        placeholders = []
        for idx, symbol in enumerate(sorted(symbols)):
            key = f"symbol_{idx}"
            placeholders.append(f"%({key})s")
            params[key] = symbol
        symbol_filter = f"AND a.symbol IN ({', '.join(placeholders)})"

    sql = f"""
    WITH latest_zone AS (
        SELECT asset_id, MAX(asof_ts_utc) AS asof_ts_utc
        FROM execution_zone_context
        WHERE venue = %(venue)s
          AND interval_code = %(interval_code)s
        GROUP BY asset_id
    )
    SELECT
        a.asset_id,
        a.symbol,
        z.venue,
        z.interval_code,
        z.asof_ts_utc,
        CASE
            WHEN z.notes LIKE 'leg_direction=%%'
                THEN SUBSTRING_INDEX(SUBSTRING_INDEX(z.notes, 'leg_direction=', -1), ';', 1)
            ELSE NULL
        END AS leg_direction,
        z.expected_entry_zone_low AS entry_zone_low,
        z.expected_entry_zone_high AS entry_zone_high,
        z.expected_take_profit_zone_low AS tp_zone_low,
        z.expected_take_profit_zone_high AS tp_zone_high,
        z.invalidation_price
    FROM latest_zone lz
    JOIN execution_zone_context z
      ON z.asset_id = lz.asset_id
     AND z.asof_ts_utc = lz.asof_ts_utc
     AND z.venue = %(venue)s
     AND z.interval_code = %(interval_code)s
    JOIN asset a
      ON a.asset_id = z.asset_id
    WHERE 1=1
      {symbol_filter}
    ORDER BY a.symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def fetch_latest_ltf_candles(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: set[str],
    limit_per_asset: int = 8,
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}

    placeholders = []
    params: dict[str, Any] = {
        "venue": venue,
        "interval_code": interval_code,
        "limit_per_asset": int(limit_per_asset),
    }
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol

    sql = f"""
    WITH ranked_candles AS (
        SELECT
            a.symbol,
            c.close_ts_utc,
            c.close_price,
            ROW_NUMBER() OVER (
                PARTITION BY c.asset_id
                ORDER BY c.close_ts_utc DESC
            ) AS rn
        FROM obs_market_candle c
        JOIN asset a
          ON a.asset_id = c.asset_id
        WHERE c.venue = %(venue)s
          AND c.interval_code = %(interval_code)s
          AND a.symbol IN ({', '.join(placeholders)})
    )
    SELECT
        symbol,
        MAX(close_ts_utc) AS latest_close_ts_utc,
        SUBSTRING_INDEX(
            GROUP_CONCAT(CAST(close_price AS CHAR) ORDER BY close_ts_utc DESC),
            ',',
            1
        ) AS latest_close_price,
        COUNT(*) AS candle_count
    FROM ranked_candles
    WHERE rn <= %(limit_per_asset)s
    GROUP BY symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def _price_for_symbol(
    *,
    symbol: str,
    price_by_symbol: dict[str, MarketPriceSnapshot],
    ltf_row: dict[str, Any] | None,
) -> tuple[Decimal | None, str]:
    snapshot = price_by_symbol.get(symbol)
    if snapshot is not None:
        return snapshot.price, "market_price_snapshot"
    if ltf_row and ltf_row.get("latest_close_price") is not None:
        return _dec(ltf_row.get("latest_close_price")), "latest_15m_close"
    return None, "missing"


def _intrabar_lifecycle_state(lifecycle_state: str, reason: str) -> str:
    normalized = lifecycle_state.upper()
    reason_text = reason.upper()
    if normalized == "PRICE_UNKNOWN" or normalized == "LIFECYCLE_UNKNOWN":
        return "INTRABAR_UNKNOWN"
    if normalized == "TARGET_REACHED_STALE":
        return "INTRABAR_EXTENSION_CONTINUING"
    if normalized == "TARGET_OVERSHOT":
        return "INTRABAR_TARGET_OVERSHOT"
    if normalized == "TARGET_REACHED":
        return "INTRABAR_TARGET_TOUCHED"
    if normalized == "RECLAIM_CONFIRMED":
        return "INTRABAR_RECLAIM_CONFIRMED"
    if normalized == "RECLAIM_NEAR" or "RECLAIM_NEAR" in reason_text:
        return "INTRABAR_RECLAIM_TOUCHED"
    if normalized == "INVALIDATION_TOUCHED":
        return "INTRABAR_INVALIDATION_TOUCHED"
    return "INTRABAR_ACTIVE"


def _recompute_hint(intrabar_state: str, lifecycle_recompute_needed: bool) -> str:
    if intrabar_state in {
        "INTRABAR_TARGET_OVERSHOT",
        "INTRABAR_RECLAIM_CONFIRMED",
        "INTRABAR_INVALIDATION_TOUCHED",
        "INTRABAR_EXTENSION_CONTINUING",
    }:
        return "INTRABAR_RECOMPUTE_REVIEW"
    if intrabar_state in {"INTRABAR_TARGET_TOUCHED", "INTRABAR_RECLAIM_TOUCHED"}:
        return "INTRABAR_MONITOR_RECOMPUTE"
    if lifecycle_recompute_needed:
        return "INTRABAR_RECOMPUTE_REVIEW"
    return "NO_INTRABAR_RECOMPUTE_HINT"


def build_intrabar_lifecycle_context_rows(
    conn: Any,
    *,
    venue: str = DEFAULT_VENUE,
    quote_currency: str = DEFAULT_QUOTE,
    structural_interval_code: str = DEFAULT_STRUCTURAL_INTERVAL,
    lifecycle_interval_code: str = DEFAULT_LIFECYCLE_INTERVAL,
    symbols: list[str] | set[str] | tuple[str, ...] | None = None,
    now_utc: datetime | None = None,
) -> list[IntrabarLifecycleContext]:
    now = now_utc or datetime.now(UTC)
    normalized_symbols = {str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()}
    symbol_filter = normalized_symbols or None

    zones_by_symbol = fetch_latest_structural_zones(
        conn,
        venue=venue,
        interval_code=structural_interval_code,
        symbols=symbol_filter,
    )
    output_symbols = set(zones_by_symbol)
    if normalized_symbols:
        output_symbols.update(normalized_symbols)

    price_by_symbol = fetch_latest_prices_by_symbol(
        conn,
        venue=venue,
        quote_currency=quote_currency,
        symbols=output_symbols,
    )
    ltf_by_symbol = fetch_latest_ltf_candles(
        conn,
        venue=venue,
        interval_code=lifecycle_interval_code,
        symbols=output_symbols,
    )

    rows: list[IntrabarLifecycleContext] = []
    for symbol in sorted(output_symbols):
        zone = zones_by_symbol.get(symbol)
        ltf_row = ltf_by_symbol.get(symbol)
        latest_15m_close_ts = None if not ltf_row else ltf_row.get("latest_close_ts_utc")
        ltf_count = 0 if not ltf_row else int(ltf_row.get("candle_count") or 0)
        price, price_source = _price_for_symbol(
            symbol=symbol,
            price_by_symbol=price_by_symbol,
            ltf_row=ltf_row,
        )

        if zone is None:
            data_quality = _freshness(
                price_snapshot=price_by_symbol.get(symbol),
                latest_15m_close_ts=latest_15m_close_ts,
                ltf_count=ltf_count,
                now_utc=now,
            )
            rows.append(
                IntrabarLifecycleContext(
                    symbol=symbol,
                    venue=venue,
                    structural_interval_code=structural_interval_code,
                    lifecycle_interval_code=lifecycle_interval_code,
                    structural_zone_asof_ts_utc=None,
                    latest_15m_close_ts_utc=_fmt_ts(latest_15m_close_ts),
                    current_price=price,
                    price_source=price_source,
                    leg_direction=None,
                    entry_zone_low=None,
                    entry_zone_high=None,
                    tp_zone_low=None,
                    tp_zone_high=None,
                    invalidation_price=None,
                    intrabar_lifecycle_state="INTRABAR_UNKNOWN",
                    intrabar_progress_state="PRICE_PROGRESS_UNKNOWN",
                    intrabar_recompute_hint="NO_STRUCTURAL_MAP",
                    intrabar_reason="STRUCTURAL_MAP_MISSING",
                    data_quality_state=f"STRUCTURAL_MAP_MISSING;{data_quality}",
                )
            )
            continue

        leg_direction = zone.get("leg_direction")
        entry_zone_low = _dec(zone.get("entry_zone_low"))
        entry_zone_high = _dec(zone.get("entry_zone_high"))
        tp_zone_low = _dec(zone.get("tp_zone_low"))
        tp_zone_high = _dec(zone.get("tp_zone_high"))
        invalidation_price = _dec(zone.get("invalidation_price"))
        lifecycle = classify_fast_lifecycle(
            leg_direction=leg_direction,
            current_price=price,
            tp_zone_low=tp_zone_low,
            tp_zone_high=tp_zone_high,
            invalidation_price=invalidation_price,
        )
        progress = classify_price_progress_state(
            leg_direction=leg_direction,
            current_price=price,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            tp_zone_low=tp_zone_low,
            tp_zone_high=tp_zone_high,
        )
        intrabar_state = _intrabar_lifecycle_state(lifecycle.lifecycle_state, lifecycle.recompute_reason)
        data_quality = _freshness(
            price_snapshot=price_by_symbol.get(symbol),
            latest_15m_close_ts=latest_15m_close_ts,
            ltf_count=ltf_count,
            now_utc=now,
        )
        rows.append(
            IntrabarLifecycleContext(
                symbol=symbol,
                venue=venue,
                structural_interval_code=structural_interval_code,
                lifecycle_interval_code=lifecycle_interval_code,
                structural_zone_asof_ts_utc=_fmt_ts(zone.get("asof_ts_utc")),
                latest_15m_close_ts_utc=_fmt_ts(latest_15m_close_ts),
                current_price=price,
                price_source=price_source,
                leg_direction=None if leg_direction is None else str(leg_direction).upper(),
                entry_zone_low=entry_zone_low,
                entry_zone_high=entry_zone_high,
                tp_zone_low=tp_zone_low,
                tp_zone_high=tp_zone_high,
                invalidation_price=invalidation_price,
                intrabar_lifecycle_state=intrabar_state,
                intrabar_progress_state=progress.progress_state,
                intrabar_recompute_hint=_recompute_hint(intrabar_state, lifecycle.recompute_needed),
                intrabar_reason=lifecycle.recompute_reason,
                data_quality_state=data_quality,
            )
        )
    return rows


def rows_by_symbol(rows: list[IntrabarLifecycleContext]) -> dict[str, IntrabarLifecycleContext]:
    return {row.symbol.upper(): row for row in rows}


def render_table(rows: list[IntrabarLifecycleContext]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=market-only account-agnostic intrabar-lifecycle-overlay",
        "input=execution_zone_context market_price_snapshot obs_market_candle asset",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "",
        "symbol | price | source | 15m_close | intrabar_state | progress | recompute_hint | data_quality | reason",
        "-------+-------+--------+-----------+----------------+----------+----------------+--------------+-------",
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    row.symbol,
                    "" if row.current_price is None else str(row.current_price),
                    row.price_source,
                    row.latest_15m_close_ts_utc or "",
                    row.intrabar_lifecycle_state,
                    row.intrabar_progress_state,
                    row.intrabar_recompute_hint,
                    row.data_quality_state,
                    row.intrabar_reason,
                ]
            )
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render market-only intrabar lifecycle context.")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--structural-interval", default=DEFAULT_STRUCTURAL_INTERVAL)
    parser.add_argument("--lifecycle-interval", default=DEFAULT_LIFECYCLE_INTERVAL)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = get_connection()
    try:
        rows = build_intrabar_lifecycle_context_rows(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            structural_interval_code=str(args.structural_interval),
            lifecycle_interval_code=str(args.lifecycle_interval),
            symbols=args.symbols,
        )
        conn.rollback()
    finally:
        conn.close()

    if args.output == "json":
        print(json.dumps([asdict(row) for row in rows], indent=2, default=_json_default))
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
