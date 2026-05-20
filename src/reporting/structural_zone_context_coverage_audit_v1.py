from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "structural_zone_context_coverage_audit_v1"
VERSION = "0.1"

DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_STRUCTURAL_INTERVAL = "4h"
DEFAULT_LTF_INTERVAL = "15m"
PRICE_SNAPSHOT_FRESH_AFTER = timedelta(minutes=10)
LTF_FRESH_AFTER = timedelta(minutes=30)
ZONE_STALE_AFTER = timedelta(hours=24)


@dataclass(frozen=True)
class StructuralZoneCoverageRow:
    symbol: str
    asset_id: int
    venue: str
    structural_interval_code: str
    latest_zone_asof_ts_utc: str | None
    has_structural_map: bool
    has_leg_direction: bool
    has_entry_zone: bool
    has_target_zone: bool
    has_invalidation_price: bool
    current_price: Decimal | None
    price_snapshot_freshness: str
    latest_15m_close_ts_utc: str | None
    ltf_candle_freshness: str
    coverage_state: str
    missing_fields: str
    recommended_action: str


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


def _age(value: datetime | None, *, now_utc: datetime) -> timedelta | None:
    if value is None:
        return None
    return now_utc.replace(tzinfo=None) - value.replace(tzinfo=None)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _freshness(value: datetime | None, *, now_utc: datetime, fresh_after: timedelta, fresh_label: str, stale_label: str, missing_label: str) -> str:
    if value is None:
        return missing_label
    age = _age(value, now_utc=now_utc)
    if age is not None and timedelta(0) <= age <= fresh_after:
        return fresh_label
    return stale_label


def fetch_assets(conn: Any, *, symbols: set[str] | None = None) -> dict[str, dict[str, Any]]:
    symbol_filter = ""
    params: dict[str, Any] = {}
    if symbols:
        placeholders = []
        for idx, symbol in enumerate(sorted(symbols)):
            key = f"symbol_{idx}"
            placeholders.append(f"%({key})s")
            params[key] = symbol
        symbol_filter = f"AND symbol IN ({', '.join(placeholders)})"
    sql = f"""
    SELECT asset_id, symbol
    FROM asset
    WHERE is_enabled = 1
      {symbol_filter}
    ORDER BY symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def fetch_latest_zones(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: set[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = []
    params: dict[str, Any] = {"venue": venue, "interval_code": interval_code}
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol
    sql = f"""
    WITH latest_zone AS (
        SELECT asset_id, MAX(asof_ts_utc) AS asof_ts_utc
        FROM execution_zone_context
        WHERE venue = %(venue)s
          AND interval_code = %(interval_code)s
        GROUP BY asset_id
    )
    SELECT
        a.symbol,
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
    WHERE a.symbol IN ({', '.join(placeholders)})
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def fetch_latest_prices(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    symbols: set[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = []
    params: dict[str, Any] = {"venue": venue, "quote_currency": quote_currency}
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol
    sql = f"""
    WITH latest_price AS (
        SELECT symbol, MAX(observed_ts_utc) AS observed_ts_utc
        FROM market_price_snapshot
        WHERE venue = %(venue)s
          AND quote_currency = %(quote_currency)s
          AND symbol IN ({', '.join(placeholders)})
        GROUP BY symbol
    )
    SELECT
        m.symbol,
        m.price,
        m.observed_ts_utc
    FROM market_price_snapshot m
    JOIN latest_price lp
      ON lp.symbol = m.symbol
     AND lp.observed_ts_utc = m.observed_ts_utc
    WHERE m.venue = %(venue)s
      AND m.quote_currency = %(quote_currency)s
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
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = []
    params: dict[str, Any] = {"venue": venue, "interval_code": interval_code}
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol
    sql = f"""
    SELECT
        a.symbol,
        MAX(c.close_ts_utc) AS latest_close_ts_utc,
        COUNT(*) AS candle_count
    FROM obs_market_candle c
    JOIN asset a
      ON a.asset_id = c.asset_id
    WHERE c.venue = %(venue)s
      AND c.interval_code = %(interval_code)s
      AND a.symbol IN ({', '.join(placeholders)})
    GROUP BY a.symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def _classify(
    *,
    has_structural_map: bool,
    has_leg_direction: bool,
    has_entry_zone: bool,
    has_target_zone: bool,
    has_invalidation_price: bool,
    latest_zone_asof: datetime | None,
    price_freshness: str,
    ltf_freshness: str,
    now_utc: datetime,
) -> tuple[str, str]:
    price_ready = price_freshness == "PRICE_SNAPSHOT_FRESH"
    ltf_ready = ltf_freshness == "LTF_CANDLES_FRESH"
    required_ready = has_leg_direction and has_entry_zone and has_target_zone and has_invalidation_price

    if price_freshness == "PRICE_DATA_MISSING":
        return "PRICE_DATA_MISSING", "SKIP_INSUFFICIENT_DATA"
    if ltf_freshness == "LTF_DATA_MISSING":
        return "LTF_DATA_MISSING", "CHECK_CANDLE_HISTORY"
    if not has_structural_map:
        if price_ready and ltf_ready:
            return "MARKET_DATA_READY_BUT_STRUCTURE_MISSING", "REFRESH_ZONE_CONTEXT"
        return "STRUCTURAL_MAP_MISSING", "REFRESH_ZONE_CONTEXT"
    if not required_ready:
        if price_ready and ltf_ready and not has_leg_direction:
            return "MARKET_DATA_READY_BUT_STRUCTURE_MISSING", "REFRESH_ZONE_CONTEXT"
        return "STRUCTURAL_MAP_PARTIAL", "REFRESH_ZONE_CONTEXT"

    zone_age = _age(latest_zone_asof, now_utc=now_utc)
    if zone_age is not None and zone_age > ZONE_STALE_AFTER:
        return "STRUCTURAL_MAP_STALE", "REFRESH_ZONE_AND_ADVICE"
    return "STRUCTURAL_MAP_READY", "NO_ACTION"


def build_coverage_rows(
    conn: Any,
    *,
    venue: str = DEFAULT_VENUE,
    quote_currency: str = DEFAULT_QUOTE,
    structural_interval_code: str = DEFAULT_STRUCTURAL_INTERVAL,
    ltf_interval_code: str = DEFAULT_LTF_INTERVAL,
    symbols: list[str] | set[str] | tuple[str, ...] | None = None,
    now_utc: datetime | None = None,
) -> list[StructuralZoneCoverageRow]:
    now = now_utc or datetime.now(UTC)
    requested_symbols = {str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()}
    assets = fetch_assets(conn, symbols=requested_symbols or None)
    if requested_symbols:
        for symbol in requested_symbols:
            assets.setdefault(symbol, {"asset_id": 0, "symbol": symbol})
    all_symbols = set(assets)

    zones = fetch_latest_zones(
        conn,
        venue=venue,
        interval_code=structural_interval_code,
        symbols=all_symbols,
    )
    prices = fetch_latest_prices(
        conn,
        venue=venue,
        quote_currency=quote_currency,
        symbols=all_symbols,
    )
    ltf = fetch_latest_ltf_candles(
        conn,
        venue=venue,
        interval_code=ltf_interval_code,
        symbols=all_symbols,
    )

    out: list[StructuralZoneCoverageRow] = []
    for symbol in sorted(all_symbols):
        asset = assets[symbol]
        zone = zones.get(symbol)
        price = prices.get(symbol)
        candle = ltf.get(symbol)

        has_structural_map = zone is not None
        has_leg_direction = bool(zone and str(zone.get("leg_direction") or "").strip().upper() in {"UP", "DOWN"})
        has_entry_zone = bool(zone and _has_value(zone.get("entry_zone_low")) and _has_value(zone.get("entry_zone_high")))
        has_target_zone = bool(zone and _has_value(zone.get("tp_zone_low")) and _has_value(zone.get("tp_zone_high")))
        has_invalidation_price = bool(zone and _has_value(zone.get("invalidation_price")))
        latest_zone_asof = None if not zone else zone.get("asof_ts_utc")
        latest_ltf_ts = None if not candle else candle.get("latest_close_ts_utc")
        price_ts = None if not price else price.get("observed_ts_utc")

        price_freshness = _freshness(
            price_ts,
            now_utc=now,
            fresh_after=PRICE_SNAPSHOT_FRESH_AFTER,
            fresh_label="PRICE_SNAPSHOT_FRESH",
            stale_label="PRICE_SNAPSHOT_STALE",
            missing_label="PRICE_DATA_MISSING",
        )
        ltf_freshness = _freshness(
            latest_ltf_ts,
            now_utc=now,
            fresh_after=LTF_FRESH_AFTER,
            fresh_label="LTF_CANDLES_FRESH",
            stale_label="LTF_CANDLES_STALE",
            missing_label="LTF_DATA_MISSING",
        )
        coverage_state, recommended_action = _classify(
            has_structural_map=has_structural_map,
            has_leg_direction=has_leg_direction,
            has_entry_zone=has_entry_zone,
            has_target_zone=has_target_zone,
            has_invalidation_price=has_invalidation_price,
            latest_zone_asof=latest_zone_asof,
            price_freshness=price_freshness,
            ltf_freshness=ltf_freshness,
            now_utc=now,
        )
        missing = []
        if not has_structural_map:
            missing.append("execution_zone_context")
        if has_structural_map and not has_leg_direction:
            missing.append("leg_direction")
        if has_structural_map and not has_entry_zone:
            missing.append("entry_zone")
        if has_structural_map and not has_target_zone:
            missing.append("target_zone")
        if has_structural_map and not has_invalidation_price:
            missing.append("invalidation_price")

        out.append(
            StructuralZoneCoverageRow(
                symbol=symbol,
                asset_id=int(asset.get("asset_id") or 0),
                venue=venue,
                structural_interval_code=structural_interval_code,
                latest_zone_asof_ts_utc=_fmt_ts(latest_zone_asof),
                has_structural_map=has_structural_map,
                has_leg_direction=has_leg_direction,
                has_entry_zone=has_entry_zone,
                has_target_zone=has_target_zone,
                has_invalidation_price=has_invalidation_price,
                current_price=None if not price else _dec(price.get("price")),
                price_snapshot_freshness=price_freshness,
                latest_15m_close_ts_utc=_fmt_ts(latest_ltf_ts),
                ltf_candle_freshness=ltf_freshness,
                coverage_state=coverage_state,
                missing_fields=",".join(missing),
                recommended_action=recommended_action,
            )
        )
    return out


def render_table(rows: list[StructuralZoneCoverageRow]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=market-only read-only structural-zone-coverage-audit",
        "input=asset market_price_snapshot obs_market_candle execution_zone_context",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "",
        "symbol | asset_id | coverage_state | missing_fields | price_freshness | ltf_freshness | zone_asof | recommended_action",
        "-------+----------+----------------+----------------+-----------------+---------------+-----------+-------------------",
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    row.symbol,
                    str(row.asset_id),
                    row.coverage_state,
                    row.missing_fields,
                    row.price_snapshot_freshness,
                    row.ltf_candle_freshness,
                    row.latest_zone_asof_ts_utc or "",
                    row.recommended_action,
                ]
            )
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit latest 4h structural zone context coverage.")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--structural-interval", default=DEFAULT_STRUCTURAL_INTERVAL)
    parser.add_argument("--ltf-interval", default=DEFAULT_LTF_INTERVAL)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = get_connection()
    try:
        rows = build_coverage_rows(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            structural_interval_code=str(args.structural_interval),
            ltf_interval_code=str(args.ltf_interval),
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
