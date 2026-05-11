from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.decision_gate.sell_intent_policy_v1 import (
    SellIntentPolicyInput,
    evaluate_sell_intent_policy_v1,
)



REPORT_NAME = "sell_intent_readonly_preview_v1"
REPORT_VERSION = "0.1"

DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"
DEFAULT_POSITION_SOURCE_NAME = "bitvavo_private_balance_position_snapshot_v1"
DEFAULT_TOLERANCE = Decimal("0.00000001")


@dataclass(frozen=True)
class TradingAccount:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: int
    live_trading_enabled: int


@dataclass(frozen=True)
class PositionRow:
    symbol: str
    quantity_base: Decimal
    available_quantity_base: Decimal
    reserved_quantity_base: Decimal
    mark_price_eur: Decimal | None


@dataclass(frozen=True)
class OrderSummary:
    symbol: str
    open_order_count: int
    remaining_quantity_base: Decimal
    limit_notional_eur: Decimal


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


def fetch_account(conn: Any, *, account_code: str, venue: str) -> TradingAccount:
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
        row = cur.fetchone()

    if not row:
        raise RuntimeError(f"Trading account not found: {account_code} / {venue}")

    return TradingAccount(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=int(row["enabled"]),
        live_trading_enabled=int(row["live_trading_enabled"]),
    )


def fetch_latest_position_ts(
    conn: Any,
    *,
    account: TradingAccount,
    source_name: str,
) -> Any | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account.trading_account_id, account.venue, source_name))
        row = cur.fetchone()

    return None if not row else row["latest_snapshot_ts_utc"]


def fetch_latest_order_ts(conn: Any, *, account: TradingAccount) -> Any | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM broker_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account.trading_account_id, account.venue))
        row = cur.fetchone()

    return None if not row else row["latest_snapshot_ts_utc"]


def fetch_position(
    conn: Any,
    *,
    account: TradingAccount,
    source_name: str,
    snapshot_ts_utc: Any,
    symbol: str,
) -> PositionRow | None:
    sql = """
    SELECT
        symbol,
        quantity_base,
        available_quantity_base,
        reserved_quantity_base,
        mark_price_eur
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s
      AND symbol = %s
    LIMIT 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account.trading_account_id, account.venue, source_name, snapshot_ts_utc, symbol))
        row = cur.fetchone()

    if not row:
        return None

    return PositionRow(
        symbol=str(row["symbol"]),
        quantity_base=decimal_value(row["quantity_base"]),
        available_quantity_base=decimal_value(row["available_quantity_base"]),
        reserved_quantity_base=decimal_value(row["reserved_quantity_base"]),
        mark_price_eur=None if row["mark_price_eur"] is None else decimal_value(row["mark_price_eur"]),
    )


def fetch_order_summary(
    conn: Any,
    *,
    account: TradingAccount,
    snapshot_ts_utc: Any | None,
    symbol: str,
) -> OrderSummary:
    if snapshot_ts_utc is None:
        return OrderSummary(symbol=symbol, open_order_count=0, remaining_quantity_base=Decimal("0"), limit_notional_eur=Decimal("0"))

    sql = """
    SELECT
        symbol,
        COUNT(*) AS open_order_count,
        COALESCE(SUM(remaining_quantity_base), 0) AS remaining_quantity_base,
        COALESCE(SUM(remaining_quantity_base * COALESCE(limit_price_eur, 0)), 0) AS limit_notional_eur
    FROM broker_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND snapshot_ts_utc = %s
      AND symbol = %s
      AND side = 'SELL'
      AND order_type = 'LIMIT'
      AND broker_status IN ('NEW', 'OPEN', 'PARTIALLY_FILLED')
    GROUP BY symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account.trading_account_id, account.venue, snapshot_ts_utc, symbol))
        row = cur.fetchone()

    if not row:
        return OrderSummary(symbol=symbol, open_order_count=0, remaining_quantity_base=Decimal("0"), limit_notional_eur=Decimal("0"))

    return OrderSummary(
        symbol=str(row["symbol"]),
        open_order_count=int(row["open_order_count"]),
        remaining_quantity_base=decimal_value(row["remaining_quantity_base"]),
        limit_notional_eur=decimal_value(row["limit_notional_eur"]),
    )


def fetch_source_checks(
    conn: Any,
    *,
    account: TradingAccount,
    source_name: str,
    position_ts: Any,
) -> dict[str, int]:
    sql = """
    SELECT
        'position_rows_total' AS check_name,
        COUNT(*) AS rows_total
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s

    UNION ALL

    SELECT
        'distinct_symbols_total' AS check_name,
        COUNT(DISTINCT symbol) AS rows_total
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s

    UNION ALL

    SELECT
        'duplicate_symbol_rows' AS check_name,
        COALESCE(SUM(duplicate_rows), 0) AS rows_total
    FROM (
        SELECT GREATEST(COUNT(*) - 1, 0) AS duplicate_rows
        FROM account_position_snapshot
        WHERE trading_account_id = %s
          AND venue = %s
          AND source_name = %s
          AND snapshot_ts_utc = %s
        GROUP BY symbol
        HAVING COUNT(*) > 1
    ) x

    UNION ALL

    SELECT
        'negative_quantity_rows' AS check_name,
        SUM(
            CASE
                WHEN quantity_base < 0
                  OR available_quantity_base < 0
                  OR reserved_quantity_base < 0
                THEN 1 ELSE 0
            END
        ) AS rows_total
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s

    UNION ALL

    SELECT
        'missing_mark_price_rows' AS check_name,
        SUM(CASE WHEN mark_price_eur IS NULL THEN 1 ELSE 0 END) AS rows_total
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s
    """

    params: list[Any] = []
    for _ in range(5):
        params.extend([account.trading_account_id, account.venue, source_name, position_ts])

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return {str(row["check_name"]): int(row["rows_total"] or 0) for row in rows}


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


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    symbol = args.symbol.upper()
    write_permission = broker_write_permission_state()
    tolerance = Decimal(str(args.tolerance))

    conn = get_db_connection()

    try:
        account = fetch_account(conn, account_code=args.account_code, venue=args.venue)
        position_ts = fetch_latest_position_ts(conn, account=account, source_name=args.position_source_name)
        order_ts = fetch_latest_order_ts(conn, account=account)

        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"account_code={account.account_code} venue={account.venue} symbol={symbol}")
        print("[INFO] read-only decision_gate intent preview; no DB writes; no broker calls; no orders")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")

        if position_ts is None:
            print("[FAIL] no position source snapshot found")
            return 2

        position = fetch_position(
            conn,
            account=account,
            source_name=args.position_source_name,
            snapshot_ts_utc=position_ts,
            symbol=symbol,
        )
        order_summary = fetch_order_summary(
            conn,
            account=account,
            snapshot_ts_utc=order_ts,
            symbol=symbol,
        )
        source_checks = fetch_source_checks(
            conn,
            account=account,
            source_name=args.position_source_name,
            position_ts=position_ts,
        )
        hard_safety_rows = fetch_hard_safety_rows(conn)
        hard_safety_nonzero_rows = [
            row for row in hard_safety_rows if int(row["rows_total"]) != 0
        ]

        if args.requested_quantity_base is None:
            requested_quantity_base = Decimal("0") if position is None else position.available_quantity_base
        else:
            requested_quantity_base = Decimal(str(args.requested_quantity_base))

        policy_decision = evaluate_sell_intent_policy_v1(
            SellIntentPolicyInput(
                account_enabled=account.enabled,
                account_live_trading_enabled=account.live_trading_enabled,
                broker_write_permission_state=write_permission,
                hard_safety_nonzero=bool(hard_safety_nonzero_rows),
                source_duplicate_symbol_rows=source_checks.get("duplicate_symbol_rows", 0),
                source_negative_quantity_rows=source_checks.get("negative_quantity_rows", 0),
                source_missing_mark_price_rows=source_checks.get("missing_mark_price_rows", 0),
                position_exists=position is not None,
                position_quantity_base=Decimal("0") if position is None else position.quantity_base,
                available_quantity_base=Decimal("0") if position is None else position.available_quantity_base,
                reserved_quantity_base=Decimal("0") if position is None else position.reserved_quantity_base,
                open_sell_order_remaining_base=order_summary.remaining_quantity_base,
                requested_quantity_base=requested_quantity_base,
                mark_price_exists=position is not None and position.mark_price_eur is not None,
                tolerance=tolerance,
            )
        )

        blockers = list(policy_decision.blocking_reasons)
        preview_state = policy_decision.preview_state
        actual_execution_permission = policy_decision.actual_execution_permission

        estimated_notional_eur = Decimal("0")
        if position is not None and position.mark_price_eur is not None:
            estimated_notional_eur = requested_quantity_base * position.mark_price_eur

        print()
        print("--- source batches ---")
        print(f"position_snapshot_ts_utc={position_ts}")
        print(f"order_snapshot_ts_utc={order_ts}")
        print(f"position_source_name={args.position_source_name}")

        print()
        print("--- account boundary ---")
        print(f"account_mode={account.account_mode}")
        print(f"account_enabled={account.enabled}")
        print(f"account_live_trading_enabled={account.live_trading_enabled}")
        print(f"actual_execution_permission={actual_execution_permission}")

        print()
        print("--- sell intent preview ---")
        rows = [
            ["symbol", symbol],
            ["requested_quantity_base", format_decimal(requested_quantity_base)],
            ["estimated_notional_eur", format_decimal(estimated_notional_eur, places=2)],
            ["preview_state", preview_state],
            ["blocking_reasons", "NONE" if not blockers else ",".join(blockers)],
        ]

        if position is None:
            rows.extend(
                [
                    ["position_quantity_base", ""],
                    ["available_quantity_base", ""],
                    ["reserved_quantity_base", ""],
                    ["mark_price_eur", ""],
                ]
            )
        else:
            rows.extend(
                [
                    ["position_quantity_base", format_decimal(position.quantity_base)],
                    ["available_quantity_base", format_decimal(position.available_quantity_base)],
                    ["reserved_quantity_base", format_decimal(position.reserved_quantity_base)],
                    ["mark_price_eur", format_decimal(position.mark_price_eur)],
                ]
            )

        rows.extend(
            [
                ["open_sell_order_count", str(order_summary.open_order_count)],
                ["open_sell_order_remaining", format_decimal(order_summary.remaining_quantity_base)],
                ["open_sell_order_limit_notional_eur", format_decimal(order_summary.limit_notional_eur, places=2)],
            ]
        )

        print_table(["field", "value"], rows)

        if args.output == "table":
            print()
            print("--- source checks ---")
            print_table(
                ["check_name", "rows_total"],
                [[key, str(value)] for key, value in source_checks.items()],
            )

            print()
            print("--- hard safety ---")
            print_table(
                ["check_name", "rows_total"],
                [[str(row["check_name"]), str(row["rows_total"])] for row in hard_safety_rows],
            )

        print()
        print("--- permission/safety summary ---")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")
        print("db_writes=0")
        print("broker_calls=0")
        print("broker_writes=0")
        print("order_submission=0")

        if write_permission == "GRANTED":
            print("[FAIL] broker write permission is granted")
            return 3

        if hard_safety_nonzero_rows:
            print("[FAIL] hard safety checks contain nonzero rows")
            return 4

        print()
        print(
            "[DONE] "
            f"preview_state={preview_state} "
            f"blockers={len(blockers)} "
            "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0"
        )

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--position-source-name", default=DEFAULT_POSITION_SOURCE_NAME)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--requested-quantity-base", default=None)
    parser.add_argument("--tolerance", default=str(DEFAULT_TOLERANCE))
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
