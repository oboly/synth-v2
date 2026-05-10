from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "account_position_latest_report_v1"
REPORT_VERSION = "0.1"

DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"
DEFAULT_SOURCE_NAME = "bitvavo_private_balance_position_snapshot_v1"


@dataclass(frozen=True)
class PositionRow:
    symbol: str
    quantity_base: Decimal
    available_quantity_base: Decimal
    reserved_quantity_base: Decimal
    mark_price_eur: Decimal | None
    value_eur: Decimal | None
    source_name: str


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


def fetch_latest_snapshot_ts(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
) -> Any | None:
    sql = """
    SELECT MAX(p.snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM account_position_snapshot p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %s
      AND p.venue = %s
      AND p.source_name = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, source_name))
        row = cur.fetchone()

    return None if not row else row["latest_snapshot_ts_utc"]


def fetch_position_rows(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
    snapshot_ts_utc: Any,
) -> list[PositionRow]:
    sql = """
    SELECT
        p.symbol,
        p.quantity_base,
        p.available_quantity_base,
        p.reserved_quantity_base,
        p.mark_price_eur,
        p.source_name
    FROM account_position_snapshot p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %s
      AND p.venue = %s
      AND p.source_name = %s
      AND p.snapshot_ts_utc = %s
    ORDER BY
        COALESCE(p.quantity_base * p.mark_price_eur, 0) DESC,
        p.symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, source_name, snapshot_ts_utc))
        rows = cur.fetchall()

    out: list[PositionRow] = []

    for row in rows:
        quantity_base = decimal_value(row["quantity_base"])
        mark_price = None if row["mark_price_eur"] is None else decimal_value(row["mark_price_eur"])
        value_eur = None if mark_price is None else quantity_base * mark_price

        out.append(
            PositionRow(
                symbol=str(row["symbol"]),
                quantity_base=quantity_base,
                available_quantity_base=decimal_value(row["available_quantity_base"]),
                reserved_quantity_base=decimal_value(row["reserved_quantity_base"]),
                mark_price_eur=mark_price,
                value_eur=value_eur,
                source_name=str(row["source_name"]),
            )
        )

    return out


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


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)))


def print_positions(rows: list[PositionRow], *, limit: int) -> None:
    headers = [
        "symbol",
        "qty",
        "available",
        "reserved",
        "mark_price",
        "value_eur",
    ]

    table_rows = [
        [
            row.symbol,
            format_decimal(row.quantity_base),
            format_decimal(row.available_quantity_base),
            format_decimal(row.reserved_quantity_base),
            format_decimal(row.mark_price_eur),
            format_decimal(row.value_eur, places=2),
        ]
        for row in rows[:limit]
    ]

    if not table_rows:
        print("(no rows)")
        return

    print_table(headers, table_rows)

    if len(rows) > limit:
        print(f"[INFO] output truncated rows_shown={limit} rows_total={len(rows)}")


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    write_permission = broker_write_permission_state()
    conn = get_db_connection()

    try:
        latest_ts = fetch_latest_snapshot_ts(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.source_name,
        )

        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"account_code={args.account_code} venue={args.venue}")
        print("[INFO] read-only local DB report; no broker calls; no DB writes; no orders")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")

        if latest_ts is None:
            print("[FAIL] no account_position_snapshot rows found")
            return 2

        rows = fetch_position_rows(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.source_name,
            snapshot_ts_utc=latest_ts,
        )
        safety_rows = fetch_hard_safety_rows(conn)
        unsafe_hard_rows = [
            row for row in safety_rows if int(row["rows_total"]) != 0
        ]

        total_value = sum((row.value_eur or Decimal("0")) for row in rows)
        available_value = sum(
            (
                Decimal("0")
                if row.mark_price_eur is None
                else row.available_quantity_base * row.mark_price_eur
            )
            for row in rows
        )
        reserved_value = sum(
            (
                Decimal("0")
                if row.mark_price_eur is None
                else row.reserved_quantity_base * row.mark_price_eur
            )
            for row in rows
        )
        missing_mark_price_rows = sum(1 for row in rows if row.mark_price_eur is None)
        reserved_symbols = sum(1 for row in rows if row.reserved_quantity_base > 0)

        print()
        print("--- latest position batch ---")
        print(f"snapshot_ts_utc={latest_ts}")
        print(f"source_name={args.source_name}")
        print(f"rows_total={len(rows)}")
        print(f"reserved_symbols={reserved_symbols}")
        print(f"missing_mark_price_rows={missing_mark_price_rows}")
        print(f"total_value_eur={format_decimal(total_value, places=2)}")
        print(f"available_value_eur={format_decimal(available_value, places=2)}")
        print(f"reserved_value_eur={format_decimal(reserved_value, places=2)}")

        if args.output == "table":
            print()
            print("--- positions ---")
            print_positions(rows, limit=args.limit)

            print()
            print("--- hard safety ---")
            print_table(
                ["check_name", "rows_total"],
                [[str(row["check_name"]), str(row["rows_total"])] for row in safety_rows],
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
            f"position_rows={len(rows)} "
            f"total_value_eur={format_decimal(total_value, places=2)} "
            "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0"
        )

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--source-name", default=DEFAULT_SOURCE_NAME)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
