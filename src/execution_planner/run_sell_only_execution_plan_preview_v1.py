"""
run_sell_only_execution_plan_preview_v1 — second stage of the whole-position
sell-only PAPER preview chain.

NOT the canonical manual execution path — see the module docstring in
src.decision_gate.run_sell_only_decision_gate_preview_v1 and
docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
bypass-list item 7. Left unmodified in this change. Route real manual SELL
execution requests through
src.manual_execution.manual_execution_service_v1.process() instead.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


POLICY_NAME = "sell_only_execution_plan_preview_v1"
POLICY_VERSION = "0.1"
DEFAULT_ACCOUNT_CODE = "paper_sell_only_preview"
DEFAULT_VENUE = "bitvavo"


@dataclass(frozen=True)
class ApprovedIntent:
    execution_sell_intent_id: int
    trading_account_id: int
    account_code: str
    asset_id: int
    symbol: str
    venue: str
    requested_quantity_base: Decimal
    reference_price_eur: Decimal
    source_position_snapshot_id: int | None
    live_trading_enabled: int
    decision_gate_enabled: int
    execution_enabled: int


@dataclass(frozen=True)
class PlanPreviewRow:
    account_code: str
    symbol: str
    intent_id: int
    plan_id: int | None
    quantity_base: Decimal
    reference_price_eur: Decimal
    limit_price_eur: Decimal
    plan_state: str
    broker_submission_enabled: int
    live_trading_enabled: int
    action: str


def fetch_latest_approved_intents(conn: Any, account_code: str, venue: str) -> list[ApprovedIntent]:
    sql = """
    SELECT
        i.execution_sell_intent_id,
        i.trading_account_id,
        ta.account_code,
        i.asset_id,
        i.symbol,
        i.venue,
        i.requested_quantity_base,
        i.reference_price_eur,
        i.source_position_snapshot_id,
        i.live_trading_enabled,
        i.decision_gate_enabled,
        i.execution_enabled
    FROM execution_sell_intent i
    JOIN trading_account ta
      ON ta.trading_account_id = i.trading_account_id
    JOIN (
        SELECT
            i2.trading_account_id,
            i2.venue,
            i2.symbol,
            i2.source_position_snapshot_id,
            MAX(i2.execution_sell_intent_id) AS latest_intent_id
        FROM execution_sell_intent i2
        WHERE i2.intent_source = 'sell_only_decision_gate_preview_v1'
          AND i2.intent_state = 'APPROVED'
          AND i2.side = 'SELL'
          AND i2.order_type = 'LIMIT'
          AND i2.live_trading_enabled = 0
          AND i2.decision_gate_enabled = 1
          AND i2.execution_enabled = 0
        GROUP BY
            i2.trading_account_id,
            i2.venue,
            i2.symbol,
            i2.source_position_snapshot_id
    ) latest
      ON latest.latest_intent_id = i.execution_sell_intent_id
    WHERE ta.account_code = %s
      AND ta.venue = %s
      AND ta.account_mode = 'paper'
      AND ta.enabled = 1
      AND i.venue = %s
    ORDER BY i.symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, venue))
        rows = cur.fetchall()

    intents: list[ApprovedIntent] = []
    for row in rows:
        reference_price = row["reference_price_eur"]
        if reference_price is None:
            continue

        intents.append(
            ApprovedIntent(
                execution_sell_intent_id=int(row["execution_sell_intent_id"]),
                trading_account_id=int(row["trading_account_id"]),
                account_code=str(row["account_code"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                requested_quantity_base=Decimal(str(row["requested_quantity_base"])),
                reference_price_eur=Decimal(str(reference_price)),
                source_position_snapshot_id=(
                    None
                    if row["source_position_snapshot_id"] is None
                    else int(row["source_position_snapshot_id"])
                ),
                live_trading_enabled=int(row["live_trading_enabled"]),
                decision_gate_enabled=int(row["decision_gate_enabled"]),
                execution_enabled=int(row["execution_enabled"]),
            )
        )

    return intents


def find_existing_plan(conn: Any, execution_sell_intent_id: int) -> int | None:
    sql = """
    SELECT execution_sell_plan_id
    FROM execution_sell_plan
    WHERE execution_sell_intent_id = %s
    LIMIT 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (execution_sell_intent_id,))
        row = cur.fetchone()

    if not row:
        return None
    return int(row["execution_sell_plan_id"])


def insert_plan(conn: Any, intent: ApprovedIntent) -> int:
    raise PermissionError(
        "legacy sell-only plan persistence is disabled; route through "
        "manual_execution_service_v1.process()"
    )

    # Unreachable compatibility SQL retained for read-migration analysis.
    sql = """
    INSERT INTO execution_sell_plan (
        execution_sell_intent_id,
        trading_account_id,
        asset_id,
        symbol,
        venue,
        plan_ts_utc,
        plan_mode,
        plan_state,
        side,
        order_type,
        quantity_base,
        reference_price_eur,
        limit_price_eur,
        source_position_snapshot_id,
        live_trading_enabled,
        broker_submission_enabled,
        client_order_id,
        broker_order_id,
        valid_until_ts_utc,
        notes
    )
    VALUES (
        %s,
        %s,
        %s,
        %s,
        %s,
        UTC_TIMESTAMP(6),
        'SELL_ONLY_LIMIT_PREVIEW',
        'PLANNED',
        'SELL',
        'LIMIT',
        %s,
        %s,
        %s,
        %s,
        0,
        0,
        NULL,
        NULL,
        DATE_ADD(UTC_TIMESTAMP(6), INTERVAL 1 HOUR),
        'Sell-only execution plan preview. No broker submission.'
    )
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                intent.execution_sell_intent_id,
                intent.trading_account_id,
                intent.asset_id,
                intent.symbol,
                intent.venue,
                intent.requested_quantity_base,
                intent.reference_price_eur,
                intent.reference_price_eur,
                intent.source_position_snapshot_id,
            ),
        )
        return int(cur.lastrowid)


def insert_event(conn: Any, *, intent: ApprovedIntent, plan_id: int, event_type: str, message: str) -> None:
    raise PermissionError(
        "legacy sell-only planner event persistence is disabled; route through "
        "manual_execution_service_v1.process()"
    )

    # Unreachable compatibility SQL retained for read-migration analysis.
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
        'execution_planner_preview',
        %s,
        'INFO',
        %s,
        %s
    )
    """

    payload = {
        "policy_name": POLICY_NAME,
        "policy_version": POLICY_VERSION,
        "execution_sell_intent_id": intent.execution_sell_intent_id,
        "execution_sell_plan_id": plan_id,
        "symbol": intent.symbol,
        "side": "SELL",
        "order_type": "LIMIT",
        "quantity_base": str(intent.requested_quantity_base),
        "reference_price_eur": str(intent.reference_price_eur),
        "limit_price_eur": str(intent.reference_price_eur),
        "broker_submission_enabled": False,
        "live_trading_enabled": False,
    }

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                intent.execution_sell_intent_id,
                plan_id,
                intent.trading_account_id,
                event_type,
                message,
                json.dumps(payload, sort_keys=True),
            ),
        )


def print_table(rows: list[PlanPreviewRow]) -> None:
    headers = [
        "account",
        "symbol",
        "intent_id",
        "plan_id",
        "qty",
        "ref_price",
        "limit_price",
        "plan_state",
        "broker_submit",
        "live",
        "action",
    ]

    table_rows: list[list[str]] = []
    for row in rows:
        table_rows.append(
            [
                row.account_code,
                row.symbol,
                str(row.intent_id),
                "" if row.plan_id is None else str(row.plan_id),
                str(row.quantity_base.normalize()),
                str(row.reference_price_eur.normalize()),
                str(row.limit_price_eur.normalize()),
                row.plan_state,
                str(row.broker_submission_enabled),
                str(row.live_trading_enabled),
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
    print(
        "[BLOCKED] legacy sell-only plan preview is disabled; "
        "use src.manual_execution.manual_execution_service_v1.process()"
    )
    return 2

    # Unreachable compatibility implementation retained temporarily for
    # readers of pre-migration PAPER rows. It must never execute.
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()
    preview_rows: list[PlanPreviewRow] = []

    try:
        intents = fetch_latest_approved_intents(conn, account_code=args.account_code, venue=args.venue)

        if not intents:
            print("[WARN] no approved sell-only preview intents found")
            print("[DONE] inserted_plans=0 reused_plans=0 broker=disabled live_order_submission=disabled")
            return 0

        inserted = 0
        reused = 0

        for intent in intents:
            existing_plan_id = find_existing_plan(conn, intent.execution_sell_intent_id)

            if existing_plan_id is not None:
                plan_id = existing_plan_id
                reused += 1
                action = "REUSED_PLAN"
            elif args.write_db:
                plan_id = insert_plan(conn, intent)
                insert_event(
                    conn,
                    intent=intent,
                    plan_id=plan_id,
                    event_type="SELL_ONLY_PLAN_PREVIEW_CREATED",
                    message="Sell-only execution plan preview created. Broker submission disabled.",
                )
                conn.commit()
                inserted += 1
                action = "INSERTED_PLAN"
            else:
                plan_id = None
                action = "DRY_RUN"

            preview_rows.append(
                PlanPreviewRow(
                    account_code=intent.account_code,
                    symbol=intent.symbol,
                    intent_id=intent.execution_sell_intent_id,
                    plan_id=plan_id,
                    quantity_base=intent.requested_quantity_base,
                    reference_price_eur=intent.reference_price_eur,
                    limit_price_eur=intent.reference_price_eur,
                    plan_state="PLANNED",
                    broker_submission_enabled=0,
                    live_trading_enabled=0,
                    action=action,
                )
            )

        if args.output == "table":
            print_table(preview_rows)

        print()
        print(
            "[DONE] policy="
            f"{POLICY_NAME} version={POLICY_VERSION} rows={len(preview_rows)} "
            f"inserted_plans={inserted} reused_plans={reused} write_db={args.write_db}"
        )
        print("[DONE] broker=disabled live_order_submission=disabled")

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
