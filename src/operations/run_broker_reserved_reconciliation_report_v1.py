from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "broker_reserved_reconciliation_report_v1"
REPORT_VERSION = "0.1"
DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"
DEFAULT_BALANCE_SOURCE_NAME = "bitvavo_private_balance_read_v1"


@dataclass(frozen=True)
class BalanceReservedRow:
    currency_code: str
    available_amount: Decimal
    reserved_amount: Decimal
    total_amount: Decimal


@dataclass(frozen=True)
class OrderReservedRow:
    symbol: str
    open_order_count: int
    remaining_quantity_base: Decimal


@dataclass(frozen=True)
class ReconcileRow:
    symbol: str
    reserved_amount: Decimal
    open_order_remaining: Decimal
    diff: Decimal
    open_order_count: int
    status: str


def decimal_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def format_decimal(value: Any) -> str:
    if value is None:
        return ""

    dec = Decimal(str(value))
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


def fetch_balance_reserved_rows(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
    snapshot_ts_utc: Any,
) -> dict[str, BalanceReservedRow]:
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

    out: dict[str, BalanceReservedRow] = {}

    for row in rows:
        currency_code = str(row["currency_code"])
        out[currency_code] = BalanceReservedRow(
            currency_code=currency_code,
            available_amount=decimal_value(row["available_amount"]),
            reserved_amount=decimal_value(row["reserved_amount"]),
            total_amount=decimal_value(row["total_amount"]),
        )

    return out


def fetch_order_reserved_rows(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    snapshot_ts_utc: Any,
) -> dict[str, OrderReservedRow]:
    sql = """
    SELECT
        o.symbol,
        COUNT(*) AS open_order_count,
        SUM(o.remaining_quantity_base) AS remaining_quantity_base
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

    out: dict[str, OrderReservedRow] = {}

    for row in rows:
        symbol = str(row["symbol"])
        out[symbol] = OrderReservedRow(
            symbol=symbol,
            open_order_count=int(row["open_order_count"]),
            remaining_quantity_base=decimal_value(row["remaining_quantity_base"]),
        )

    return out


def build_reconciliation(
    *,
    balances: dict[str, BalanceReservedRow],
    orders: dict[str, OrderReservedRow],
    tolerance: Decimal,
    include_zero: bool,
) -> list[ReconcileRow]:
    symbols = sorted(set(balances.keys()) | set(orders.keys()))
    rows: list[ReconcileRow] = []

    for symbol in symbols:
        balance = balances.get(symbol)
        order = orders.get(symbol)

        reserved_amount = Decimal("0") if balance is None else balance.reserved_amount
        open_order_remaining = Decimal("0") if order is None else order.remaining_quantity_base
        open_order_count = 0 if order is None else order.open_order_count
        diff = reserved_amount - open_order_remaining

        if not include_zero and reserved_amount == 0 and open_order_remaining == 0:
            continue

        if abs(diff) <= tolerance:
            status = "MATCH"
        elif reserved_amount > 0 and open_order_remaining == 0:
            status = "RESERVED_WITHOUT_OPEN_ORDER"
        elif reserved_amount == 0 and open_order_remaining > 0:
            status = "OPEN_ORDER_WITHOUT_RESERVED"
        else:
            status = "MISMATCH"

        rows.append(
            ReconcileRow(
                symbol=symbol,
                reserved_amount=reserved_amount,
                open_order_remaining=open_order_remaining,
                diff=diff,
                open_order_count=open_order_count,
                status=status,
            )
        )

    rows.sort(
        key=lambda row: (
            0 if row.status != "MATCH" else 1,
            row.status,
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


def print_reconcile_rows(rows: list[ReconcileRow]) -> None:
    headers = [
        "symbol",
        "reserved_balance",
        "open_order_remaining",
        "diff",
        "open_orders",
        "status",
    ]

    table_rows = [
        [
            row.symbol,
            format_decimal(row.reserved_amount),
            format_decimal(row.open_order_remaining),
            format_decimal(row.diff),
            str(row.open_order_count),
            row.status,
        ]
        for row in rows
    ]

    if not table_rows:
        print("(no rows)")
        return

    print_table(headers, table_rows)


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


def print_safety_rows(rows: list[dict[str, Any]]) -> None:
    headers = ["check_name", "rows_total"]
    table_rows = [[str(row["check_name"]), str(row["rows_total"])] for row in rows]
    print_table(headers, table_rows)


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    write_permission = broker_write_permission_state()

    conn = get_db_connection()

    try:
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
        print(f"account_code={args.account_code} venue={args.venue}")
        print("[INFO] read-only reconciliation; no DB writes; no broker calls; no order submission")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")

        if latest_balance_ts is None:
            print("[FAIL] no trading account balance snapshot found")
            return 2

        if latest_order_ts is None:
            print("[FAIL] no broker order snapshot found")
            return 3

        balances = fetch_balance_reserved_rows(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.balance_source_name,
            snapshot_ts_utc=latest_balance_ts,
        )
        orders = fetch_order_reserved_rows(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            snapshot_ts_utc=latest_order_ts,
        )

        tolerance = Decimal(str(args.tolerance))
        rows = build_reconciliation(
            balances=balances,
            orders=orders,
            tolerance=tolerance,
            include_zero=args.include_zero,
        )

        status_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1

        mismatches = [row for row in rows if row.status != "MATCH"]
        hard_safety_rows = fetch_hard_safety_rows(conn)
        unsafe_hard_rows = [
            row for row in hard_safety_rows if int(row["rows_total"]) != 0
        ]

        print()
        print("--- batches ---")
        print(f"balance_snapshot_ts_utc={latest_balance_ts}")
        print(f"order_snapshot_ts_utc={latest_order_ts}")
        print(f"balance_currencies={len(balances)}")
        print(f"order_symbols={len(orders)}")
        print(f"tolerance={format_decimal(tolerance)}")

        print()
        print("--- reconciliation summary ---")
        print("status_counts=" + ",".join(f"{k}:{v}" for k, v in sorted(status_counts.items())))
        print(f"mismatch_count={len(mismatches)}")

        if args.output == "table":
            print()
            print("--- reconciliation rows ---")
            print_reconcile_rows(rows)

            print()
            print("--- hard safety ---")
            print_safety_rows(hard_safety_rows)

        print()
        print("--- permission/safety summary ---")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")
        print(f"hard_safety_nonzero_checks={len(unsafe_hard_rows)}")

        if write_permission == "GRANTED":
            print("[FAIL] broker write permission is granted")
            return 4

        if unsafe_hard_rows:
            print("[FAIL] hard safety checks contain nonzero rows")
            return 5

        if mismatches and not args.allow_mismatch_exit_zero:
            print("[FAIL] reserved balance/open order reconciliation has mismatches")
            return 6

        print()
        print(
            "[DONE] "
            f"reconciliation_rows={len(rows)} "
            f"mismatch_count={len(mismatches)} "
            "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0"
        )

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--balance-source-name", default=DEFAULT_BALANCE_SOURCE_NAME)
    parser.add_argument("--tolerance", default="0.00000001")
    parser.add_argument("--include-zero", action="store_true")
    parser.add_argument("--allow-mismatch-exit-zero", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
