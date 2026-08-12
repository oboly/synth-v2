from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Any

import requests

from src.account.account_snapshot_models_v1 import MarketSyncRow, MarketSyncResult
from src.common.db import get_db_connection


RUNNER_NAME = "bitvavo_market_sync_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
BITVAVO_MARKETS_URL = "https://api.bitvavo.com/v2/markets"


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fetch_bitvavo_markets(
    base_url: str = BITVAVO_MARKETS_URL,
    timeout_seconds: int = 15,
) -> list[dict[str, Any]]:
    response = requests.get(base_url, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected /markets response type: {type(data)}")
    return data


def normalize_market_rows(
    raw_markets: list[dict[str, Any]],
    *,
    quote_filter: str = "EUR",
) -> tuple[list[MarketSyncRow], int]:
    rows: list[MarketSyncRow] = []
    unsupported = 0
    for item in raw_markets:
        quote = str(item.get("quote") or "").upper()
        if quote != quote_filter:
            unsupported += 1
            continue
        market = str(item.get("market") or "")
        base = str(item.get("base") or "").upper()
        status = str(item.get("status") or "").lower()
        if not market or not base:
            unsupported += 1
            continue
        price_precision = item.get("pricePrecision")
        qty_precision = None  # Bitvavo doesn't expose qty precision directly in /markets
        rows.append(
            MarketSyncRow(
                market=market,
                base=base,
                quote=quote,
                status=status,
                is_tradeable=(status == "trading"),
                price_precision=int(price_precision) if price_precision is not None else None,
                qty_precision=qty_precision,
            )
        )
    return rows, unsupported


def fetch_asset_columns(conn: Any) -> list[dict[str, Any]]:
    sql = """
    SELECT
        COLUMN_NAME,
        DATA_TYPE,
        COLUMN_TYPE,
        IS_NULLABLE,
        COLUMN_DEFAULT,
        EXTRA
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'asset'
    ORDER BY ORDINAL_POSITION
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def _is_required_booleanish(column: dict[str, Any]) -> bool:
    data_type = str(column.get("DATA_TYPE") or "").lower()
    column_type = str(column.get("COLUMN_TYPE") or "").lower()
    if str(column.get("IS_NULLABLE") or "").upper() != "NO":
        return False
    if column.get("COLUMN_DEFAULT") is not None:
        return False
    return data_type in {"tinyint", "bit", "bool", "boolean"} or "tinyint(1)" in column_type


def _build_asset_insert_payload(
    asset_columns: list[dict[str, Any]],
    *,
    symbol: str,
) -> tuple[list[str], list[Any]]:
    values_by_column: dict[str, Any] = {}
    for column in asset_columns:
        name = str(column["COLUMN_NAME"])
        if name == "symbol":
            values_by_column[name] = symbol
        elif name == "name":
            values_by_column[name] = symbol
        elif name == "asset_class":
            values_by_column[name] = "CRYPTO"
        elif name == "is_enabled":
            values_by_column[name] = 1
        elif name == "is_tradeable":
            values_by_column[name] = 1
        elif name in {"is_portfolio", "is_publication_cohort"}:
            values_by_column[name] = 0
        elif _is_required_booleanish(column):
            values_by_column[name] = 0

    ordered_columns: list[str] = []
    ordered_values: list[Any] = []
    for column in asset_columns:
        name = str(column["COLUMN_NAME"])
        if name in values_by_column:
            ordered_columns.append(name)
            ordered_values.append(values_by_column[name])
    return ordered_columns, ordered_values


def upsert_asset(
    conn: Any,
    *,
    symbol: str,
    asset_columns: list[dict[str, Any]] | None = None,
) -> str:
    """Insert asset if not present. Never override legacy flags on existing rows. Returns INSERTED|EXISTING."""
    asset_columns = asset_columns or fetch_asset_columns(conn)
    insert_columns, insert_values = _build_asset_insert_payload(asset_columns, symbol=symbol)
    if not insert_columns:
        raise RuntimeError("asset schema discovery failed: no insertable columns found")

    columns_sql = ", ".join(insert_columns)
    placeholders_sql = ", ".join(["%s"] * len(insert_columns))
    safe_updates: list[str] = []
    if "name" in insert_columns:
        safe_updates.append("name = IF(name IS NULL OR name = '', VALUES(name), name)")
    if not safe_updates:
        safe_updates.append("symbol = symbol")

    sql_insert = f"""
    INSERT INTO asset ({columns_sql})
    VALUES ({placeholders_sql})
    ON DUPLICATE KEY UPDATE
        {", ".join(safe_updates)}
    """
    with conn.cursor() as cur:
        cur.execute(sql_insert, insert_values)
        affected = cur.rowcount
    # rowcount=1 → insert, rowcount=2 → update, rowcount=0 → no-op
    return "INSERTED" if affected == 1 else "EXISTING"


def fetch_asset_id(conn: Any, *, symbol: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id FROM asset WHERE symbol = %s LIMIT 1", (symbol,))
        row = cur.fetchone()
    if not row:
        return None
    return int(row["asset_id"])


def upsert_venue_market(
    conn: Any,
    *,
    venue: str,
    row: MarketSyncRow,
    base_asset_id: int,
    synced_at: datetime,
) -> str:
    """Upsert venue_market row. Returns INSERTED|UPDATED."""
    sql = """
    INSERT INTO venue_market (
        venue, market, base_asset_id, quote_currency,
        is_tradeable, is_market_data_enabled,
        price_precision,
        created_ts, updated_ts
    ) VALUES (
        %s, %s, %s, %s,
        %s, 1,
        %s,
        %s, %s
    )
    ON DUPLICATE KEY UPDATE
        is_tradeable = VALUES(is_tradeable),
        price_precision = IF(VALUES(price_precision) IS NOT NULL, VALUES(price_precision), price_precision),
        updated_ts = VALUES(updated_ts)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                row.market,
                base_asset_id,
                row.quote,
                1 if row.is_tradeable else 0,
                row.price_precision,
                synced_at,
                synced_at,
            ),
        )
        affected = cur.rowcount
    return "INSERTED" if affected == 1 else "UPDATED"


def mark_missing_markets_not_tradeable(
    conn: Any,
    *,
    venue: str,
    seen_markets: set[str],
    synced_at: datetime,
) -> int:
    if not seen_markets:
        return 0
    placeholders = ",".join(["%s"] * len(seen_markets))
    sql = f"""
    UPDATE venue_market
    SET is_tradeable = 0, updated_ts = %s
    WHERE venue = %s
      AND market NOT IN ({placeholders})
      AND is_tradeable = 1
    """
    params = [synced_at, venue, *sorted(seen_markets)]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def run_market_sync(
    conn: Any,
    *,
    venue: str,
    rows: list[MarketSyncRow],
    unsupported_count: int,
    write_db: bool,
) -> MarketSyncResult:
    synced_at = utc_now_naive()
    asset_inserted = 0
    asset_existing = 0
    vm_inserted = 0
    vm_updated = 0
    seen_markets: set[str] = set()
    asset_columns = fetch_asset_columns(conn) if write_db else []

    for row in rows:
        seen_markets.add(row.market)
        if not write_db:
            continue

        action = upsert_asset(conn, symbol=row.base, asset_columns=asset_columns)
        if action == "INSERTED":
            asset_inserted += 1
        else:
            asset_existing += 1

        asset_id = fetch_asset_id(conn, symbol=row.base)
        if asset_id is None:
            print(f"[warn] asset_id not found after upsert for {row.base}", file=sys.stderr)
            continue

        vm_action = upsert_venue_market(
            conn,
            venue=venue,
            row=row,
            base_asset_id=asset_id,
            synced_at=synced_at,
        )
        if vm_action == "INSERTED":
            vm_inserted += 1
        else:
            vm_updated += 1

    if write_db:
        conn.commit()
        mark_missing_markets_not_tradeable(conn, venue=venue, seen_markets=seen_markets, synced_at=synced_at)
        conn.commit()

    return MarketSyncResult(
        venue=venue,
        total_markets=len(rows),
        asset_inserted=asset_inserted,
        asset_existing=asset_existing,
        venue_market_inserted=vm_inserted,
        venue_market_updated=vm_updated,
        unsupported_count=unsupported_count,
    )


def print_summary(result: MarketSyncResult, *, write_db: bool) -> None:
    print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
    print(f"venue={result.venue}")
    print(f"total_markets={result.total_markets}")
    print(f"unsupported_quote_filter={result.unsupported_count}")
    if write_db:
        print(f"asset_inserted={result.asset_inserted}")
        print(f"asset_existing={result.asset_existing}")
        print(f"venue_market_inserted={result.venue_market_inserted}")
        print(f"venue_market_updated={result.venue_market_updated}")
    else:
        print("[DRY_RUN] --write-db not set; no DB writes performed")
    print("broker_writes=0")
    print("order_submission=0")
    print("executor=none")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync global Bitvavo market universe to asset + venue_market tables. "
            "Public API only. No broker writes, no order submission."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--quote-filter",
        default="EUR",
        help="Only sync markets quoted in this currency.",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        default=False,
        help="Persist upserts to DB. Dry-run if omitted.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=15,
    )
    parser.add_argument(
        "--output",
        choices=("summary", "none"),
        default="summary",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        raw = fetch_bitvavo_markets(timeout_seconds=args.timeout_seconds)
    except Exception as exc:
        print(f"[error] market fetch failed: {exc}", file=sys.stderr)
        return 1

    rows, unsupported_count = normalize_market_rows(raw, quote_filter=args.quote_filter)

    conn = get_db_connection()
    try:
        result = run_market_sync(
            conn,
            venue=args.venue,
            rows=rows,
            unsupported_count=unsupported_count,
            write_db=args.write_db,
        )
    finally:
        conn.close()

    if args.output == "summary":
        print_summary(result, write_db=args.write_db)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
