from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "sell_only_lifecycle_report_v1"
REPORT_VERSION = "0.1"
DEFAULT_ACCOUNT_CODE = "paper_sell_only_preview"
DEFAULT_VENUE = "bitvavo"


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value.normalize())
    return str(value)


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("[INFO] no rows")
        return

    headers = list(rows[0].keys())
    table_rows = [[format_value(row.get(header)) for header in headers] for row in rows]

    widths = [len(header) for header in headers]
    for table_row in table_rows:
        for idx, value in enumerate(table_row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for table_row in table_rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(table_row)))


def fetch_lifecycle_rows(
    conn: Any,
    *,
    account_code: str,
    venue: str,
    limit: int,
) -> list[dict[str, Any]]:
    sql = """
    SELECT *
    FROM (
        SELECT
            'POSITION' AS row_type,
            p.account_position_snapshot_id AS row_id,
            p.snapshot_ts_utc AS ts_utc,
            ta.account_code,
            p.trading_account_id,
            p.symbol,
            'POSITION_SNAPSHOT' AS lifecycle_state,
            p.source_name AS reason_or_message,
            CAST(NULL AS CHAR(16)) AS side,
            CAST(NULL AS CHAR(16)) AS order_type,
            p.quantity_base AS quantity_base,
            p.mark_price_eur AS reference_price_eur,
            CAST(NULL AS DECIMAL(38,18)) AS limit_price_eur,
            CAST(NULL AS SIGNED) AS live_trading_enabled,
            CAST(NULL AS SIGNED) AS decision_gate_enabled,
            CAST(NULL AS SIGNED) AS execution_enabled,
            CAST(NULL AS SIGNED) AS broker_submission_enabled,
            'account_position_snapshot' AS source_table
        FROM account_position_snapshot p
        JOIN trading_account ta
          ON ta.trading_account_id = p.trading_account_id
        WHERE ta.account_code = %(account_code)s
          AND ta.venue = %(venue)s

        UNION ALL

        SELECT
            'INTENT' AS row_type,
            i.execution_sell_intent_id AS row_id,
            i.intent_ts_utc AS ts_utc,
            ta.account_code,
            i.trading_account_id,
            i.symbol,
            i.intent_state AS lifecycle_state,
            i.reason_code AS reason_or_message,
            i.side,
            i.order_type,
            i.requested_quantity_base AS quantity_base,
            i.reference_price_eur,
            CAST(NULL AS DECIMAL(38,18)) AS limit_price_eur,
            i.live_trading_enabled,
            i.decision_gate_enabled,
            i.execution_enabled,
            CAST(NULL AS SIGNED) AS broker_submission_enabled,
            'execution_sell_intent' AS source_table
        FROM execution_sell_intent i
        JOIN trading_account ta
          ON ta.trading_account_id = i.trading_account_id
        WHERE ta.account_code = %(account_code)s
          AND ta.venue = %(venue)s

        UNION ALL

        SELECT
            'PLAN' AS row_type,
            p.execution_sell_plan_id AS row_id,
            p.plan_ts_utc AS ts_utc,
            ta.account_code,
            p.trading_account_id,
            p.symbol,
            p.plan_state AS lifecycle_state,
            p.plan_mode AS reason_or_message,
            p.side,
            p.order_type,
            p.quantity_base,
            p.reference_price_eur,
            p.limit_price_eur,
            p.live_trading_enabled,
            CAST(NULL AS SIGNED) AS decision_gate_enabled,
            CAST(NULL AS SIGNED) AS execution_enabled,
            p.broker_submission_enabled,
            'execution_sell_plan' AS source_table
        FROM execution_sell_plan p
        JOIN trading_account ta
          ON ta.trading_account_id = p.trading_account_id
        WHERE ta.account_code = %(account_code)s
          AND ta.venue = %(venue)s

        UNION ALL

        SELECT
            'EVENT' AS row_type,
            e.execution_sell_event_id AS row_id,
            e.event_ts_utc AS ts_utc,
            ta.account_code,
            e.trading_account_id,
            CAST(NULL AS CHAR(32)) AS symbol,
            e.event_type AS lifecycle_state,
            e.message AS reason_or_message,
            CAST(NULL AS CHAR(16)) AS side,
            CAST(NULL AS CHAR(16)) AS order_type,
            CAST(NULL AS DECIMAL(38,18)) AS quantity_base,
            CAST(NULL AS DECIMAL(38,18)) AS reference_price_eur,
            CAST(NULL AS DECIMAL(38,18)) AS limit_price_eur,
            CAST(NULL AS SIGNED) AS live_trading_enabled,
            CAST(NULL AS SIGNED) AS decision_gate_enabled,
            CAST(NULL AS SIGNED) AS execution_enabled,
            CAST(NULL AS SIGNED) AS broker_submission_enabled,
            'execution_sell_event' AS source_table
        FROM execution_sell_event e
        JOIN trading_account ta
          ON ta.trading_account_id = e.trading_account_id
        WHERE ta.account_code = %(account_code)s
          AND ta.venue = %(venue)s

        UNION ALL

        SELECT
            'BROKER_SNAPSHOT' AS row_type,
            b.broker_order_snapshot_id AS row_id,
            b.snapshot_ts_utc AS ts_utc,
            ta.account_code,
            b.trading_account_id,
            b.symbol,
            b.broker_status AS lifecycle_state,
            b.broker_order_id AS reason_or_message,
            b.side,
            b.order_type,
            b.quantity_base,
            b.limit_price_eur AS reference_price_eur,
            b.limit_price_eur,
            CAST(NULL AS SIGNED) AS live_trading_enabled,
            CAST(NULL AS SIGNED) AS decision_gate_enabled,
            CAST(NULL AS SIGNED) AS execution_enabled,
            CAST(NULL AS SIGNED) AS broker_submission_enabled,
            'broker_order_snapshot' AS source_table
        FROM broker_order_snapshot b
        JOIN trading_account ta
          ON ta.trading_account_id = b.trading_account_id
        WHERE ta.account_code = %(account_code)s
          AND ta.venue = %(venue)s
    ) unioned
    ORDER BY ts_utc DESC, row_type
    LIMIT %(limit)s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            sql,
            {
                "account_code": account_code,
                "venue": venue,
                "limit": limit,
            },
        )
        return list(cur.fetchall())


def fetch_safety_rows(conn: Any, *, account_code: str, venue: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        'broker_order_snapshot' AS check_name,
        COUNT(*) AS rows_total
    FROM broker_order_snapshot b
    JOIN trading_account ta
      ON ta.trading_account_id = b.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s

    UNION ALL

    SELECT
        'execution_sell_plan_broker_submission_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_plan p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s
      AND p.broker_submission_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_plan_live_trading_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_plan p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s
      AND p.live_trading_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_intent_live_trading_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_intent i
    JOIN trading_account ta
      ON ta.trading_account_id = i.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s
      AND i.live_trading_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_intent_execution_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_intent i
    JOIN trading_account ta
      ON ta.trading_account_id = i.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s
      AND i.execution_enabled = 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            sql,
            {
                "account_code": account_code,
                "venue": venue,
            },
        )
        return list(cur.fetchall())


def fetch_state_counts(conn: Any, *, account_code: str, venue: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        'intent_state' AS group_name,
        i.intent_state AS state_code,
        COUNT(*) AS rows_total
    FROM execution_sell_intent i
    JOIN trading_account ta
      ON ta.trading_account_id = i.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s
    GROUP BY i.intent_state

    UNION ALL

    SELECT
        'plan_state' AS group_name,
        p.plan_state AS state_code,
        COUNT(*) AS rows_total
    FROM execution_sell_plan p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s
    GROUP BY p.plan_state

    UNION ALL

    SELECT
        'event_type' AS group_name,
        e.event_type AS state_code,
        COUNT(*) AS rows_total
    FROM execution_sell_event e
    JOIN trading_account ta
      ON ta.trading_account_id = e.trading_account_id
    WHERE ta.account_code = %(account_code)s
      AND ta.venue = %(venue)s
    GROUP BY e.event_type
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            sql,
            {
                "account_code": account_code,
                "venue": venue,
            },
        )
        return list(cur.fetchall())


def print_rows(title: str, rows: list[dict[str, Any]], output: str) -> None:
    print()
    print(title)

    if output == "jsonl":
        for row in rows:
            print(json.dumps(row, sort_keys=True, default=str))
        return

    print_table(rows)


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()
    try:
        lifecycle_rows = fetch_lifecycle_rows(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            limit=args.limit,
        )
        safety_rows = fetch_safety_rows(
            conn,
            account_code=args.account_code,
            venue=args.venue,
        )
        state_rows = fetch_state_counts(
            conn,
            account_code=args.account_code,
            venue=args.venue,
        )
    finally:
        conn.close()

    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"account_code={args.account_code} venue={args.venue}")
    print("[INFO] read-only UNION report; no DB writes; no broker calls; no position mutation")

    print_rows("--- lifecycle union ---", lifecycle_rows, args.output)
    print_rows("--- safety union ---", safety_rows, args.output)
    print_rows("--- state counts union ---", state_rows, args.output)

    print()
    print(
        "[DONE] "
        f"lifecycle_rows={len(lifecycle_rows)} "
        f"safety_rows={len(safety_rows)} "
        f"state_count_rows={len(state_rows)}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--output", choices=["table", "jsonl"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
