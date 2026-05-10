from __future__ import annotations

import argparse
import os
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "broker_balance_latest_report_v1"
REPORT_VERSION = "0.1"
DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"
DEFAULT_SOURCE_NAME = "bitvavo_private_balance_read_v1"


def format_decimal(value: Any) -> str:
    if value is None:
        return ""
    dec = Decimal(str(value))
    out = format(dec, "f")
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out or "0"


def fetch_latest_batch_ts(
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

    if not row:
        return None

    return row["latest_snapshot_ts_utc"]


def fetch_batch_rows(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
    snapshot_ts_utc: Any,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        b.trading_account_balance_snapshot_id,
        b.snapshot_ts_utc,
        ta.account_code,
        b.venue,
        b.currency_code,
        b.available_amount,
        b.reserved_amount,
        b.total_amount,
        b.source_name,
        b.created_ts_utc
    FROM trading_account_balance_snapshot b
    JOIN trading_account ta
      ON ta.trading_account_id = b.trading_account_id
    WHERE ta.account_code = %s
      AND b.venue = %s
      AND b.source_name = %s
      AND b.snapshot_ts_utc = %s
    ORDER BY
        CASE WHEN b.currency_code = 'EUR' THEN 0 ELSE 1 END,
        CASE WHEN b.reserved_amount > 0 THEN 0 ELSE 1 END,
        b.currency_code
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, source_name, snapshot_ts_utc))
        return list(cur.fetchall())


def fetch_batch_integrity(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
    snapshot_ts_utc: Any,
) -> dict[str, Any]:
    sql = """
    SELECT
        COUNT(*) AS rows_total,
        COUNT(DISTINCT b.snapshot_ts_utc) AS distinct_snapshot_ts,
        MIN(b.snapshot_ts_utc) AS min_snapshot_ts_utc,
        MAX(b.snapshot_ts_utc) AS max_snapshot_ts_utc,
        SUM(CASE WHEN b.currency_code = 'EUR' THEN b.available_amount ELSE 0 END) AS eur_available,
        SUM(CASE WHEN b.currency_code = 'EUR' THEN b.reserved_amount ELSE 0 END) AS eur_reserved,
        SUM(CASE WHEN b.currency_code = 'EUR' THEN b.total_amount ELSE 0 END) AS eur_total,
        SUM(CASE WHEN b.reserved_amount > 0 THEN 1 ELSE 0 END) AS currencies_with_reserved
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
        row = cur.fetchone()

    return dict(row or {})


def fetch_safety_rows(conn: Any) -> list[dict[str, Any]]:
    sql = """
    SELECT
        'broker_order_snapshot' AS check_name,
        COUNT(*) AS rows_total
    FROM broker_order_snapshot

    UNION ALL

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


def broker_write_permission_state() -> str:
    expected = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"
    actual = os.getenv("SYNTH_BROKER_WRITE_PERMISSION")
    if actual == expected:
        return "GRANTED"
    if actual:
        return "PRESENT_BUT_NOT_GRANTED"
    return "MISSING"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)))


def print_balance_rows(rows: list[dict[str, Any]]) -> None:
    headers = ["currency", "available", "reserved", "total", "reserved?"]
    table_rows: list[list[str]] = []

    for row in rows:
        reserved_amount = Decimal(str(row["reserved_amount"]))
        table_rows.append(
            [
                str(row["currency_code"]),
                format_decimal(row["available_amount"]),
                format_decimal(row["reserved_amount"]),
                format_decimal(row["total_amount"]),
                "YES" if reserved_amount > 0 else "NO",
            ]
        )

    print_table(headers, table_rows)


def print_safety_rows(rows: list[dict[str, Any]]) -> None:
    headers = ["check_name", "rows_total"]
    table_rows = [[str(row["check_name"]), str(row["rows_total"])] for row in rows]
    print_table(headers, table_rows)


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()

    try:
        latest_batch_ts = fetch_latest_batch_ts(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.source_name,
        )

        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"account_code={args.account_code} venue={args.venue}")
        print("[INFO] read-only report; no DB writes; no broker calls; no order submission")

        if latest_batch_ts is None:
            print()
            print("[WARN] no broker balance snapshots found")
            return 0

        integrity = fetch_batch_integrity(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.source_name,
            snapshot_ts_utc=latest_batch_ts,
        )

        balance_rows = fetch_batch_rows(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.source_name,
            snapshot_ts_utc=latest_batch_ts,
        )

        safety_rows = fetch_safety_rows(conn)

        print()
        print("--- latest batch ---")
        print(f"snapshot_ts_utc={latest_batch_ts}")
        print(f"rows_total={integrity.get('rows_total')}")
        print(f"distinct_snapshot_ts={integrity.get('distinct_snapshot_ts')}")
        print(f"currencies_with_reserved={integrity.get('currencies_with_reserved')}")
        print(f"eur_available={format_decimal(integrity.get('eur_available'))}")
        print(f"eur_reserved={format_decimal(integrity.get('eur_reserved'))}")
        print(f"eur_total={format_decimal(integrity.get('eur_total'))}")

        if args.output == "table":
            print()
            print("--- balances ---")
            print_balance_rows(balance_rows)

            print()
            print("--- safety ---")
            print_safety_rows(safety_rows)

        write_permission = broker_write_permission_state()
        unsafe_safety_rows = [
            row for row in safety_rows if int(row["rows_total"]) != 0
        ]

        print()
        print("--- permission/safety summary ---")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")
        print(f"safety_nonzero_checks={len(unsafe_safety_rows)}")

        if write_permission == "GRANTED":
            print("[FAIL] broker write permission is granted")
            return 2

        if unsafe_safety_rows:
            print("[FAIL] safety checks contain nonzero broker/execution rows")
            return 3

        if int(integrity.get("distinct_snapshot_ts") or 0) != 1:
            print("[FAIL] latest batch is not coherent")
            return 4

        print()
        print(
            "[DONE] "
            f"latest_batch_rows={integrity.get('rows_total')} "
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
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
