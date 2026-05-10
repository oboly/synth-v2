from __future__ import annotations

import argparse
import os
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "decision_gate_position_source_audit_v1"
REPORT_VERSION = "0.1"

DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"
DEFAULT_SOURCE_NAME = "bitvavo_private_balance_position_snapshot_v1"


def broker_write_permission_state() -> str:
    expected = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"
    actual = os.getenv("SYNTH_BROKER_WRITE_PERMISSION")

    if actual == expected:
        return "GRANTED"
    if actual:
        return "PRESENT_BUT_NOT_GRANTED"
    return "MISSING"


def fetch_account(conn: Any, *, account_code: str, venue: str) -> dict[str, Any] | None:
    sql = """
    SELECT
        trading_account_id,
        account_code,
        venue,
        account_mode,
        enabled,
        live_trading_enabled
    FROM trading_account
    WHERE account_code = %s
      AND venue = %s
    LIMIT 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue))
        return cur.fetchone()


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


def fetch_position_source_checks(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
    snapshot_ts_utc: Any,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        'position_rows_total' AS check_name,
        COUNT(*) AS rows_total
    FROM account_position_snapshot p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %s
      AND p.venue = %s
      AND p.source_name = %s
      AND p.snapshot_ts_utc = %s

    UNION ALL

    SELECT
        'distinct_symbols_total' AS check_name,
        COUNT(DISTINCT p.symbol) AS rows_total
    FROM account_position_snapshot p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %s
      AND p.venue = %s
      AND p.source_name = %s
      AND p.snapshot_ts_utc = %s

    UNION ALL

    SELECT
        'duplicate_symbol_rows' AS check_name,
        COALESCE(SUM(x.duplicate_rows), 0) AS rows_total
    FROM (
        SELECT
            p.symbol,
            GREATEST(COUNT(*) - 1, 0) AS duplicate_rows
        FROM account_position_snapshot p
        JOIN trading_account ta
          ON ta.trading_account_id = p.trading_account_id
        WHERE ta.account_code = %s
          AND p.venue = %s
          AND p.source_name = %s
          AND p.snapshot_ts_utc = %s
        GROUP BY p.symbol
        HAVING COUNT(*) > 1
    ) x

    UNION ALL

    SELECT
        'negative_quantity_rows' AS check_name,
        SUM(
            CASE
                WHEN p.quantity_base < 0
                  OR p.available_quantity_base < 0
                  OR p.reserved_quantity_base < 0
                THEN 1 ELSE 0
            END
        ) AS rows_total
    FROM account_position_snapshot p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %s
      AND p.venue = %s
      AND p.source_name = %s
      AND p.snapshot_ts_utc = %s

    UNION ALL

    SELECT
        'missing_mark_price_rows' AS check_name,
        SUM(CASE WHEN p.mark_price_eur IS NULL THEN 1 ELSE 0 END) AS rows_total
    FROM account_position_snapshot p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %s
      AND p.venue = %s
      AND p.source_name = %s
      AND p.snapshot_ts_utc = %s
    """

    params = []
    for _ in range(5):
        params.extend([account_code, venue, source_name, snapshot_ts_utc])

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


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


def fetch_sample_rows(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    source_name: str,
    snapshot_ts_utc: Any,
    limit: int,
) -> list[dict[str, Any]]:
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
    ORDER BY p.symbol
    LIMIT %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, source_name, snapshot_ts_utc, limit))
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


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    write_permission = broker_write_permission_state()
    conn = get_db_connection()

    try:
        account = fetch_account(conn, account_code=args.account_code, venue=args.venue)
        latest_ts = fetch_latest_snapshot_ts(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.source_name,
        )

        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"account_code={args.account_code} venue={args.venue}")
        print("[INFO] read-only decision_gate source audit; no DB writes; no broker calls; no orders")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")

        if account is None:
            print("[FAIL] trading_account missing")
            return 2

        print()
        print("--- trading account ---")
        for key in (
            "trading_account_id",
            "account_code",
            "venue",
            "account_mode",
            "enabled",
            "live_trading_enabled",
        ):
            print(f"{key}={account[key]}")

        if latest_ts is None:
            print("[FAIL] no account_position_snapshot source found")
            return 3

        source_checks = fetch_position_source_checks(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            source_name=args.source_name,
            snapshot_ts_utc=latest_ts,
        )
        hard_safety_rows = fetch_hard_safety_rows(conn)

        source_check_map = {
            str(row["check_name"]): int(row["rows_total"] or 0)
            for row in source_checks
        }

        hard_safety_nonzero = [
            row for row in hard_safety_rows if int(row["rows_total"]) != 0
        ]

        blocking_reasons: list[str] = []

        if int(account["enabled"]) != 1:
            blocking_reasons.append("TRADING_ACCOUNT_DISABLED")

        if int(account["live_trading_enabled"]) != 0:
            blocking_reasons.append("LIVE_TRADING_ENABLED_NOT_ALLOWED")

        if source_check_map.get("position_rows_total", 0) <= 0:
            blocking_reasons.append("NO_POSITION_ROWS")

        if source_check_map.get("duplicate_symbol_rows", 0) != 0:
            blocking_reasons.append("DUPLICATE_SYMBOL_ROWS")

        if source_check_map.get("negative_quantity_rows", 0) != 0:
            blocking_reasons.append("NEGATIVE_QUANTITY_ROWS")

        if source_check_map.get("missing_mark_price_rows", 0) != 0:
            blocking_reasons.append("MISSING_MARK_PRICE_ROWS")

        if hard_safety_nonzero:
            blocking_reasons.append("HARD_SAFETY_NONZERO")

        if write_permission == "GRANTED":
            blocking_reasons.append("BROKER_WRITE_PERMISSION_GRANTED")

        status = "READY_FOR_DECISION_GATE_READ" if not blocking_reasons else "BLOCKED"

        print()
        print("--- latest position source ---")
        print(f"source_name={args.source_name}")
        print(f"snapshot_ts_utc={latest_ts}")

        print()
        print("--- source checks ---")
        print_table(
            ["check_name", "rows_total"],
            [[str(row["check_name"]), str(row["rows_total"] or 0)] for row in source_checks],
        )

        print()
        print("--- hard safety ---")
        print_table(
            ["check_name", "rows_total"],
            [[str(row["check_name"]), str(row["rows_total"])] for row in hard_safety_rows],
        )

        if args.output == "table":
            sample_rows = fetch_sample_rows(
                conn,
                account_code=args.account_code,
                venue=args.venue,
                source_name=args.source_name,
                snapshot_ts_utc=latest_ts,
                limit=args.limit,
            )

            print()
            print("--- sample source rows ---")
            print_table(
                [
                    "symbol",
                    "qty",
                    "available",
                    "reserved",
                    "mark_price",
                    "source_name",
                ],
                [
                    [
                        str(row["symbol"]),
                        str(row["quantity_base"]),
                        str(row["available_quantity_base"]),
                        str(row["reserved_quantity_base"]),
                        "" if row["mark_price_eur"] is None else str(row["mark_price_eur"]),
                        str(row["source_name"]),
                    ]
                    for row in sample_rows
                ],
            )

        print()
        print("--- decision gate source audit result ---")
        print(f"status={status}")
        print(
            "blocking_reasons="
            + ("NONE" if not blocking_reasons else ",".join(blocking_reasons))
        )

        print()
        print(
            "[DONE] "
            f"status={status} "
            f"blocking_reasons={len(blocking_reasons)} "
            "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0"
        )

        return 0 if not blocking_reasons else 10

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--source-name", default=DEFAULT_SOURCE_NAME)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
