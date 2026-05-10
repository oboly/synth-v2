from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


POLICY_NAME = "sell_only_paper_executor_preview_v1"
POLICY_VERSION = "0.1"
DEFAULT_ACCOUNT_CODE = "paper_sell_only_preview"
DEFAULT_VENUE = "bitvavo"


@dataclass(frozen=True)
class PlanRow:
    execution_sell_plan_id: int
    execution_sell_intent_id: int
    trading_account_id: int
    account_code: str
    asset_id: int
    symbol: str
    venue: str
    quantity_base: Decimal
    reference_price_eur: Decimal
    limit_price_eur: Decimal
    plan_state: str
    plan_mode: str
    live_trading_enabled: int
    broker_submission_enabled: int


@dataclass(frozen=True)
class ExecutorPreviewRow:
    account_code: str
    symbol: str
    plan_id: int
    intent_id: int
    quantity_base: Decimal
    limit_price_eur: Decimal
    from_state: str
    to_state: str
    event_type: str
    action: str


def format_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fetch_eligible_plans(conn: Any, account_code: str, venue: str, max_plans: int) -> list[PlanRow]:
    sql = """
    SELECT
        p.execution_sell_plan_id,
        p.execution_sell_intent_id,
        p.trading_account_id,
        ta.account_code,
        p.asset_id,
        p.symbol,
        p.venue,
        p.quantity_base,
        p.reference_price_eur,
        p.limit_price_eur,
        p.plan_state,
        p.plan_mode,
        p.live_trading_enabled,
        p.broker_submission_enabled
    FROM execution_sell_plan p
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    JOIN execution_sell_intent i
      ON i.execution_sell_intent_id = p.execution_sell_intent_id
    WHERE ta.account_code = %s
      AND ta.venue = %s
      AND ta.account_mode = 'paper'
      AND ta.enabled = 1
      AND p.venue = %s
      AND p.side = 'SELL'
      AND p.order_type = 'LIMIT'
      AND p.plan_mode = 'SELL_ONLY_LIMIT_PREVIEW'
      AND p.live_trading_enabled = 0
      AND p.broker_submission_enabled = 0
      AND p.plan_state IN ('PLANNED', 'READY_TO_SUBMIT', 'SUBMITTED')
      AND i.intent_state = 'APPROVED'
      AND i.side = 'SELL'
      AND i.order_type = 'LIMIT'
      AND i.live_trading_enabled = 0
      AND i.decision_gate_enabled = 1
      AND i.execution_enabled = 0
    ORDER BY p.plan_ts_utc ASC, p.execution_sell_plan_id ASC
    LIMIT %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, venue, max_plans))
        rows = cur.fetchall()

    plans: list[PlanRow] = []
    for row in rows:
        plans.append(
            PlanRow(
                execution_sell_plan_id=int(row["execution_sell_plan_id"]),
                execution_sell_intent_id=int(row["execution_sell_intent_id"]),
                trading_account_id=int(row["trading_account_id"]),
                account_code=str(row["account_code"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                quantity_base=Decimal(str(row["quantity_base"])),
                reference_price_eur=Decimal(str(row["reference_price_eur"])),
                limit_price_eur=Decimal(str(row["limit_price_eur"])),
                plan_state=str(row["plan_state"]),
                plan_mode=str(row["plan_mode"]),
                live_trading_enabled=int(row["live_trading_enabled"]),
                broker_submission_enabled=int(row["broker_submission_enabled"]),
            )
        )

    return plans


def next_state_for(plan_state: str) -> tuple[str, str, str]:
    if plan_state == "PLANNED":
        return (
            "READY_TO_SUBMIT",
            "SELL_ONLY_PAPER_READY_TO_SUBMIT_PREVIEW",
            "Sell-only paper executor preview marked plan ready. No broker submission.",
        )

    if plan_state == "READY_TO_SUBMIT":
        return (
            "SUBMITTED",
            "SELL_ONLY_PAPER_SUBMITTED_PREVIEW",
            "Sell-only paper executor preview marked plan submitted. Broker remains disabled.",
        )

    if plan_state == "SUBMITTED":
        return (
            "FILLED",
            "SELL_ONLY_PAPER_FILLED_PREVIEW",
            "Sell-only paper executor preview marked plan filled. Position mutation not performed.",
        )

    raise ValueError(f"unsupported plan_state={plan_state}")


def update_plan_state(
    conn: Any,
    *,
    plan: PlanRow,
    to_state: str,
    note: str,
) -> int:
    sql = """
    UPDATE execution_sell_plan
    SET
        plan_state = %s,
        updated_ts_utc = UTC_TIMESTAMP(6),
        notes = LEFT(CONCAT(COALESCE(notes, ''), ' | ', %s), 512)
    WHERE execution_sell_plan_id = %s
      AND plan_state = %s
      AND live_trading_enabled = 0
      AND broker_submission_enabled = 0
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                to_state,
                f"{POLICY_NAME} {POLICY_VERSION}: {note}",
                plan.execution_sell_plan_id,
                plan.plan_state,
            ),
        )
        return int(cur.rowcount)


def insert_event(
    conn: Any,
    *,
    plan: PlanRow,
    event_type: str,
    message: str,
    to_state: str,
) -> None:
    sql = """
    INSERT INTO execution_sell_event (
        execution_sell_intent_id,
        execution_sell_plan_id,
        broker_order_snapshot_id,
        trading_account_id,
        event_ts_utc,
        event_layer,
        event_type,
        severity,
        message,
        payload_json
    )
    VALUES (
        %s,
        %s,
        NULL,
        %s,
        UTC_TIMESTAMP(6),
        'paper_executor_preview',
        %s,
        'INFO',
        %s,
        %s
    )
    """

    payload = {
        "policy_name": POLICY_NAME,
        "policy_version": POLICY_VERSION,
        "symbol": plan.symbol,
        "from_state": plan.plan_state,
        "to_state": to_state,
        "quantity_base": str(plan.quantity_base),
        "reference_price_eur": str(plan.reference_price_eur),
        "limit_price_eur": str(plan.limit_price_eur),
        "broker_submission_enabled": False,
        "live_trading_enabled": False,
        "position_mutation_enabled": False,
    }

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                plan.execution_sell_intent_id,
                plan.execution_sell_plan_id,
                plan.trading_account_id,
                event_type,
                message,
                json.dumps(payload, sort_keys=True),
            ),
        )


def print_table(rows: list[ExecutorPreviewRow]) -> None:
    headers = [
        "account",
        "symbol",
        "plan_id",
        "intent_id",
        "qty",
        "limit_price",
        "from_state",
        "to_state",
        "event_type",
        "action",
    ]

    table_rows: list[list[str]] = []
    for row in rows:
        table_rows.append(
            [
                row.account_code,
                row.symbol,
                str(row.plan_id),
                str(row.intent_id),
                format_decimal(row.quantity_base),
                format_decimal(row.limit_price_eur),
                row.from_state,
                row.to_state,
                row.event_type,
                row.action,
            ]
        )

    widths = [len(header) for header in headers]
    for table_row in table_rows:
        for idx, value in enumerate(table_row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for table_row in table_rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(table_row)))


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()
    rows: list[ExecutorPreviewRow] = []

    try:
        plans = fetch_eligible_plans(
            conn,
            account_code=args.account_code,
            venue=args.venue,
            max_plans=args.max_plans,
        )

        advanced = 0
        skipped = 0

        for plan in plans:
            to_state, event_type, message = next_state_for(plan.plan_state)

            action = "DRY_RUN"
            if args.write_db:
                affected = update_plan_state(
                    conn,
                    plan=plan,
                    to_state=to_state,
                    note=message,
                )

                if affected == 1:
                    insert_event(
                        conn,
                        plan=plan,
                        event_type=event_type,
                        message=message,
                        to_state=to_state,
                    )
                    conn.commit()
                    advanced += 1
                    action = "ADVANCED"
                else:
                    conn.rollback()
                    skipped += 1
                    action = "SKIPPED_CONCURRENT_CHANGE"

            rows.append(
                ExecutorPreviewRow(
                    account_code=plan.account_code,
                    symbol=plan.symbol,
                    plan_id=plan.execution_sell_plan_id,
                    intent_id=plan.execution_sell_intent_id,
                    quantity_base=plan.quantity_base,
                    limit_price_eur=plan.limit_price_eur,
                    from_state=plan.plan_state,
                    to_state=to_state,
                    event_type=event_type,
                    action=action,
                )
            )

        if args.output == "table":
            if rows:
                print_table(rows)
            else:
                print("No eligible sell-only paper plans found.")

        print()
        print(
            "[DONE] policy="
            f"{POLICY_NAME} version={POLICY_VERSION} rows={len(rows)} "
            f"advanced={advanced} skipped={skipped} write_db={args.write_db}"
        )
        print("[DONE] broker=disabled live_order_submission=disabled position_mutation=disabled")
        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--max-plans", type=int, default=20)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
