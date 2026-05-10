from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "broker_account_valuation_report_v1"
REPORT_VERSION = "0.1"
DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "1h"
DEFAULT_BALANCE_SOURCE_NAME = "bitvavo_private_balance_read_v1"


@dataclass(frozen=True)
class BalanceRow:
    currency_code: str
    available_amount: Decimal
    reserved_amount: Decimal
    total_amount: Decimal


@dataclass(frozen=True)
class PriceRow:
    symbol: str
    price_eur: Decimal
    price_ts_utc: Any


@dataclass(frozen=True)
class OrderRow:
    symbol: str
    open_order_count: int
    remaining_quantity_base: Decimal
    limit_notional_eur: Decimal


@dataclass(frozen=True)
class ValuationRow:
    symbol: str
    available_amount: Decimal
    reserved_amount: Decimal
    total_amount: Decimal
    price_eur: Decimal | None
    available_value_eur: Decimal | None
    reserved_value_eur: Decimal | None
    total_value_eur: Decimal | None
    open_order_count: int
    open_order_remaining: Decimal
    open_order_limit_notional_eur: Decimal
    price_ts_utc: Any
    valuation_status: str


def decimal_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def format_decimal(value: Any, *, places: int | None = None) -> str:
    if value is None:
        return ""

    dec = Decimal(str(value))

    if places is not None:
        q = Decimal("1").scaleb(-places)
        dec = dec.quantize(q)

    out = format(dec, "f")

    if "." in out:
        out = out.rstrip("0").rstrip(".")

    return out or "0"


def broker_write_permission_state() -> str:
    expected = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"
    actual = os.getenv("SYNTH_BROKER_WRITE_PERMISSION")

    if actual == expected:
        return "GRANTED"
    if actual:
        return "PRESENT_BUT_NOT_GRANTED"
    return "MISSING"


def detect_candle_columns(conn: Any) -> tuple[str, str]:
    sql = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'obs_market_candle'
      AND column_name IN ('close', 'close_price', 'close_eur', 'price_close', 'open_ts_utc', 'close_ts_utc')
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql)
        cols = {str(row["column_name"]) for row in cur.fetchall()}

    ts_col = "close_ts_utc" if "close_ts_utc" in cols else "open_ts_utc"

    for price_col in ("close_price", "close", "close_eur", "price_close"):
        if price_col in cols:
            return ts_col, price_col

    raise RuntimeError("Could not detect close price column in obs_market_candle.")


def fetch_latest_balance_batch_ts(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
) -> Any | None:
    sql = """
    SELECT MAX(b.snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM trading_account_balance_snapshot b
    JOIN trading_account ta
      ON ta.trading_account_id = b.trading_account_id
    WHERE ta.account_code = %s
      AND b.venue = %s
      AND b.source_name = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, source_name))
        row = cur.fetchone()

    return None if not row else row["latest_snapshot_ts_utc"]


def fetch_latest_order_batch_ts(
    conn: Any,
    *,
    account_code: str,
    venue: str,
) -> Any | None:
    sql = """
    SELECT MAX(o.snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM broker_order_snapshot o
    JOIN trading_account ta
      ON ta.trading_account_id = o.trading_account_id
    WHERE ta.account_code = %s
      AND o.venue = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()

    return None if not row else row["latest_snapshot_ts_utc"]


def fetch_balances(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
    snapshot_ts_utc: Any,
) -> dict[str, BalanceRow]:
    sql = """
    SELECT
        b.currency_code,
        b.available_amount,
        b.reserved_amount,
        b.total_amount
    FROM trading_account_balance_snapshot b
    JOIN trading_account ta
      ON ta.trading_account_id = b.trading_account_id
    WHERE ta.account_code = %s
      AND b.venue = %s
      AND b.source_name = %s
      AND b.snapshot_ts_utc = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, source_name, snapshot_ts_utc))
        rows = cur.fetchall()

    out: dict[str, BalanceRow] = {}

    for row in rows:
        symbol = str(row["currency_code"])
        out[symbol] = BalanceRow(
            currency_code=symbol,
            available_amount=decimal_value(row["available_amount"]),
            reserved_amount=decimal_value(row["reserved_amount"]),
            total_amount=decimal_value(row["total_amount"]),
        )

    return out


def fetch_prices(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: list[str],
    ts_col: str,
    price_col: str,
) -> dict[str, PriceRow]:
    prices: dict[str, PriceRow] = {
        "EUR": PriceRow(symbol="EUR", price_eur=Decimal("1"), price_ts_utc=None)
    }

    market_symbols = [symbol for symbol in symbols if symbol != "EUR"]
    if not market_symbols:
        return prices

    placeholders = ",".join(["%s"] * len(market_symbols))
    sql = f"""
    SELECT
        a.symbol,
        c.{price_col} AS price_eur,
        c.{ts_col} AS price_ts_utc
    FROM asset a
    JOIN obs_market_candle c
      ON c.asset_id = a.asset_id
    JOIN (
        SELECT
            c2.asset_id,
            MAX(c2.{ts_col}) AS max_price_ts_utc
        FROM obs_market_candle c2
        JOIN asset a2
          ON a2.asset_id = c2.asset_id
        WHERE c2.venue = %s
          AND c2.interval_code = %s
          AND a2.symbol IN ({placeholders})
        GROUP BY c2.asset_id
    ) latest
      ON latest.asset_id = c.asset_id
     AND latest.max_price_ts_utc = c.{ts_col}
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND a.symbol IN ({placeholders})
    """

    params = [venue, interval_code, *market_symbols, venue, interval_code, *market_symbols]

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    for row in rows:
        symbol = str(row["symbol"])
        prices[symbol] = PriceRow(
            symbol=symbol,
            price_eur=decimal_value(row["price_eur"]),
            price_ts_utc=row["price_ts_utc"],
        )

    return prices


def fetch_orders(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    snapshot_ts_utc: Any | None,
) -> dict[str, OrderRow]:
    if snapshot_ts_utc is None:
        return {}

    sql = """
    SELECT
        o.symbol,
        COUNT(*) AS open_order_count,
        SUM(o.remaining_quantity_base) AS remaining_quantity_base,
        SUM(o.remaining_quantity_base * COALESCE(o.limit_price_eur, 0)) AS limit_notional_eur
    FROM broker_order_snapshot o
    JOIN trading_account ta
      ON ta.trading_account_id = o.trading_account_id
    WHERE ta.account_code = %s
      AND o.venue = %s
      AND o.snapshot_ts_utc = %s
      AND o.side = 'SELL'
      AND o.order_type = 'LIMIT'
      AND o.broker_status IN ('NEW', 'OPEN', 'PARTIALLY_FILLED')
    GROUP BY o.symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, snapshot_ts_utc))
        rows = cur.fetchall()

    out: dict[str, OrderRow] = {}

    for row in rows:
        symbol = str(row["symbol"])
        out[symbol] = OrderRow(
            symbol=symbol,
            open_order_count=int(row["open_order_count"]),
            remaining_quantity_base=decimal_value(row["remaining_quantity_base"]),
            limit_notional_eur=decimal_value(row["limit_notional_eur"]),
        )

    return out


def build_valuation_rows(
    *,
    balances: dict[str, BalanceRow],
    prices: dict[str, PriceRow],
    orders: dict[str, OrderRow],
) -> list[ValuationRow]:
    rows: list[ValuationRow] = []

    for symbol in sorted(balances.keys()):
        balance = balances[symbol]
        price = prices.get(symbol)
        order = orders.get(symbol)

        open_order_count = 0 if order is None else order.open_order_count
        open_order_remaining = Decimal("0") if order is None else order.remaining_quantity_base
        open_order_limit_notional_eur = Decimal("0") if order is None else order.limit_notional_eur

        if price is None:
            price_eur = None
            available_value_eur = None
            reserved_value_eur = None
            total_value_eur = None
            price_ts_utc = None
            valuation_status = "NO_PRICE"
        else:
            price_eur = price.price_eur
            available_value_eur = balance.available_amount * price.price_eur
            reserved_value_eur = balance.reserved_amount * price.price_eur
            total_value_eur = balance.total_amount * price.price_eur
            price_ts_utc = price.price_ts_utc
            valuation_status = "OK"

        rows.append(
            ValuationRow(
                symbol=symbol,
                available_amount=balance.available_amount,
                reserved_amount=balance.reserved_amount,
                total_amount=balance.total_amount,
                price_eur=price_eur,
                available_value_eur=available_value_eur,
                reserved_value_eur=reserved_value_eur,
                total_value_eur=total_value_eur,
                open_order_count=open_order_count,
                open_order_remaining=open_order_remaining,
                open_order_limit_notional_eur=open_order_limit_notional_eur,
                price_ts_utc=price_ts_utc,
                valuation_status=valuation_status,
            )
        )

    rows.sort(
        key=lambda row: (
            row.valuation_status != "OK",
            -(row.total_value_eur or Decimal("0")),
            row.symbol,
        )
    )

    return rows


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)))


def print_valuation_rows(rows: list[ValuationRow], *, limit: int) -> None:
    headers = [
        "symbol",
        "total_qty",
        "reserved_qty",
        "price_eur",
        "total_eur",
        "reserved_eur",
        "open_orders",
        "limit_notional_eur",
        "status",
    ]

    table_rows = [
        [
            row.symbol,
            format_decimal(row.total_amount),
            format_decimal(row.reserved_amount),
            format_decimal(row.price_eur),
            format_decimal(row.total_value_eur, places=2),
            format_decimal(row.reserved_value_eur, places=2),
            str(row.open_order_count),
            format_decimal(row.open_order_limit_notional_eur, places=2),
            row.valuation_status,
        ]
        for row in rows[:limit]
    ]

    print_table(headers, table_rows)

    if len(rows) > limit:
        print(f"[INFO] output truncated rows_shown={limit} rows_total={len(rows)}")


def fetch_hard_safety_rows(conn: Any) -> list[dict[str, Any]]:
    sql = """
    SELECT
        'execution_sell_plan_broker_submission_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_plan
    WHERE broker_submission_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_plan_live_trading_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_plan
    WHERE live_trading_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_intent_live_trading_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_intent
    WHERE live_trading_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_intent_execution_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_intent
    WHERE execution_enabled = 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    write_permission = broker_write_permission_state()
    conn = get_db_connection()

    try:
        ts_col, price_col = detect_candle_columns(conn)

        latest_balance_ts = fetch_latest_balance_batch_ts(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.balance_source_name,
        )
        latest_order_ts = fetch_latest_order_batch_ts(
            conn,
            account_code=args.account_code,
            venue=args.venue,
        )

        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"account_code={args.account_code} venue={args.venue} interval={args.interval}")
        print("[INFO] read-only valuation; no DB writes; no broker calls; no order submission")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")

        if latest_balance_ts is None:
            print("[FAIL] no trading account balance snapshot found")
            return 2

        balances = fetch_balances(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.balance_source_name,
            snapshot_ts_utc=latest_balance_ts,
        )
        prices = fetch_prices(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            symbols=list(balances.keys()),
            ts_col=ts_col,
            price_col=price_col,
        )
        orders = fetch_orders(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            snapshot_ts_utc=latest_order_ts,
        )
        valuation_rows = build_valuation_rows(
            balances=balances,
            prices=prices,
            orders=orders,
        )

        hard_safety_rows = fetch_hard_safety_rows(conn)
        unsafe_hard_rows = [
            row for row in hard_safety_rows if int(row["rows_total"]) != 0
        ]

        total_value_eur = sum(
            (row.total_value_eur or Decimal("0")) for row in valuation_rows
        )
        available_value_eur = sum(
            (row.available_value_eur or Decimal("0")) for row in valuation_rows
        )
        reserved_value_eur = sum(
            (row.reserved_value_eur or Decimal("0")) for row in valuation_rows
        )
        open_order_limit_notional_eur = sum(
            row.open_order_limit_notional_eur for row in valuation_rows
        )
        no_price_rows = [row for row in valuation_rows if row.valuation_status != "OK"]

        print()
        print("--- batches ---")
        print(f"balance_snapshot_ts_utc={latest_balance_ts}")
        print(f"order_snapshot_ts_utc={latest_order_ts}")
        print(f"price_ts_column={ts_col}")
        print(f"price_column={price_col}")

        print()
        print("--- valuation summary ---")
        print(f"currencies={len(valuation_rows)}")
        print(f"total_value_eur={format_decimal(total_value_eur, places=2)}")
        print(f"available_value_eur={format_decimal(available_value_eur, places=2)}")
        print(f"reserved_value_eur={format_decimal(reserved_value_eur, places=2)}")
        print(f"open_order_limit_notional_eur={format_decimal(open_order_limit_notional_eur, places=2)}")
        print(f"no_price_count={len(no_price_rows)}")

        if args.output == "table":
            print()
            print("--- valuation rows ---")
            print_valuation_rows(valuation_rows, limit=args.limit)

            print()
            print("--- hard safety ---")
            print_table(
                ["check_name", "rows_total"],
                [[str(row["check_name"]), str(row["rows_total"])] for row in hard_safety_rows],
            )

        print()
        print("--- permission/safety summary ---")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")
        print(f"hard_safety_nonzero_checks={len(unsafe_hard_rows)}")

        if write_permission == "GRANTED":
            print("[FAIL] broker write permission is granted")
            return 3

        if unsafe_hard_rows:
            print("[FAIL] hard safety checks contain nonzero rows")
            return 4

        print()
        print(
            "[DONE] "
            f"valuation_rows={len(valuation_rows)} "
            f"total_value_eur={format_decimal(total_value_eur, places=2)} "
            "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0"
        )

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--balance-source-name", default=DEFAULT_BALANCE_SOURCE_NAME)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
