from __future__ import annotations

import argparse
import json
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



POLICY_NAME = "sell_only_decision_gate_preview_v1"
POLICY_VERSION = "0.3"
DEFAULT_ACCOUNT_CODE = "paper_sell_only_preview"
DEFAULT_VENUE = "bitvavo"
DEFAULT_REQUEST_FRACTION = Decimal("1.000000000000000000")


@dataclass(frozen=True)
class PositionRow:
    trading_account_id: int
    account_code: str
    account_mode: str
    account_enabled: int
    account_live_trading_enabled: int
    account_position_snapshot_id: int
    asset_id: int
    symbol: str
    venue: str
    quantity_base: Decimal
    available_quantity_base: Decimal
    reserved_quantity_base: Decimal
    mark_price_eur: Decimal | None


@dataclass(frozen=True)
class DecisionRow:
    account_code: str
    trading_account_id: int
    symbol: str | None
    quantity_base: Decimal | None
    available_quantity_base: Decimal | None
    requested_quantity_base: Decimal | None
    reference_price_eur: Decimal | None
    intent_state: str
    reason_code: str
    side: str | None
    order_type: str | None
    live_trading_enabled: int
    decision_gate_enabled: int
    execution_enabled: int
    action: str
    intent_id: int | None


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def fetch_latest_positions(conn: Any, account_code: str, venue: str) -> list[PositionRow]:
    sql = """
    SELECT
        ta.trading_account_id,
        ta.account_code,
        ta.account_mode,
        ta.enabled AS account_enabled,
        ta.live_trading_enabled AS account_live_trading_enabled,
        p.account_position_snapshot_id,
        p.asset_id,
        p.symbol,
        p.venue,
        p.quantity_base,
        p.available_quantity_base,
        p.reserved_quantity_base,
        p.mark_price_eur
    FROM trading_account ta
    JOIN account_position_snapshot p
      ON p.trading_account_id = ta.trading_account_id
    JOIN (
        SELECT
            p2.trading_account_id,
            p2.venue,
            p2.symbol,
            MAX(p2.snapshot_ts_utc) AS latest_snapshot_ts_utc
        FROM account_position_snapshot p2
        GROUP BY
            p2.trading_account_id,
            p2.venue,
            p2.symbol
    ) latest
      ON latest.trading_account_id = p.trading_account_id
     AND latest.venue = p.venue
     AND latest.symbol = p.symbol
     AND latest.latest_snapshot_ts_utc = p.snapshot_ts_utc
    WHERE ta.account_code = %s
      AND ta.venue = %s
      AND ta.account_mode = 'paper'
      AND ta.enabled = 1
      AND p.venue = %s
    ORDER BY p.symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue, venue))
        rows = cur.fetchall()

    positions: list[PositionRow] = []
    for row in rows:
        positions.append(
            PositionRow(
                trading_account_id=int(row["trading_account_id"]),
                account_code=str(row["account_code"]),
                account_mode=str(row["account_mode"]),
                account_enabled=int(row["account_enabled"]),
                account_live_trading_enabled=int(row["account_live_trading_enabled"]),
                account_position_snapshot_id=int(row["account_position_snapshot_id"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                quantity_base=Decimal(str(row["quantity_base"])),
                available_quantity_base=Decimal(str(row["available_quantity_base"])),
                reserved_quantity_base=Decimal(str(row["reserved_quantity_base"])),
                mark_price_eur=decimal_or_none(row["mark_price_eur"]),
            )
        )

    return positions


def account_exists(conn: Any, account_code: str, venue: str) -> int | None:
    sql = """
    SELECT trading_account_id
    FROM trading_account
    WHERE account_code = %s
      AND venue = %s
      AND account_mode = 'paper'
      AND enabled = 1
    LIMIT 1
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()

    if not row:
        return None
    return int(row["trading_account_id"])


def insert_event(
    conn: Any,
    *,
    trading_account_id: int | None,
    execution_sell_intent_id: int | None,
    event_type: str,
    severity: str,
    message: str,
    payload: dict[str, Any],
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
        NULL,
        NULL,
        %s,
        UTC_TIMESTAMP(6),
        'decision_gate_preview',
        %s,
        %s,
        %s,
        %s
    )
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                execution_sell_intent_id,
                trading_account_id,
                event_type,
                severity,
                message,
                json.dumps(payload, sort_keys=True),
            ),
        )


def decide_position(
    position: PositionRow,
    *,
    request_fraction: Decimal,
    approve_paper_preview: bool,
) -> tuple[str, str, int, int, int, Decimal]:
    requested_quantity = position.available_quantity_base * request_fraction

    if position.account_mode != "paper":
        return ("BLOCKED", "NON_PAPER_ACCOUNT_BLOCKED", 0, 0, 0, requested_quantity)

    policy_decision = evaluate_sell_intent_policy_v1(
        SellIntentPolicyInput(
            account_enabled=position.account_enabled,
            account_live_trading_enabled=position.account_live_trading_enabled,
            broker_write_permission_state="MISSING",
            hard_safety_nonzero=False,
            source_duplicate_symbol_rows=0,
            source_negative_quantity_rows=0,
            source_missing_mark_price_rows=0,
            position_exists=True,
            position_quantity_base=position.quantity_base,
            available_quantity_base=position.available_quantity_base,
            reserved_quantity_base=position.reserved_quantity_base,
            open_sell_order_remaining_base=position.reserved_quantity_base,
            requested_quantity_base=requested_quantity,
            mark_price_exists=position.mark_price_eur is not None and position.mark_price_eur > 0,
        )
    )

    reason_map = {
        "ACCOUNT_DISABLED": "ACCOUNT_DISABLED",
        "LIVE_TRADING_ENABLED_NOT_ALLOWED": "ACCOUNT_LIVE_TRADING_FLAG_NOT_ALLOWED_FOR_PREVIEW",
        "NO_POSITION_QUANTITY": "NO_POSITION",
        "NO_AVAILABLE_QUANTITY_RESERVED": "NO_AVAILABLE_QUANTITY",
        "NO_AVAILABLE_QUANTITY": "NO_AVAILABLE_QUANTITY",
        "REQUESTED_QUANTITY_NOT_POSITIVE": "REQUESTED_QUANTITY_NOT_POSITIVE",
        "REQUEST_EXCEEDS_AVAILABLE_QUANTITY": "REQUEST_EXCEEDS_AVAILABLE_QUANTITY",
        "MISSING_MARK_PRICE": "REFERENCE_PRICE_MISSING",
        "BROKER_WRITE_PERMISSION_GRANTED": "BROKER_WRITE_PERMISSION_GRANTED",
        "HARD_SAFETY_NONZERO": "HARD_SAFETY_NONZERO",
        "SOURCE_DUPLICATES": "SOURCE_DUPLICATES",
        "SOURCE_NEGATIVE_QUANTITIES": "SOURCE_NEGATIVE_QUANTITIES",
        "SOURCE_MISSING_MARK_PRICE": "SOURCE_MISSING_MARK_PRICE",
        "RESERVED_OPEN_ORDER_MISMATCH": "RESERVED_OPEN_ORDER_MISMATCH",
    }

    if policy_decision.blocking_reasons:
        first_reason = policy_decision.blocking_reasons[0]
        return (
            "BLOCKED",
            reason_map.get(first_reason, first_reason),
            0,
            0,
            0,
            requested_quantity,
        )

    if not approve_paper_preview:
        return ("BLOCKED", "PAPER_APPROVAL_FLAG_NOT_SET", 0, 0, 0, requested_quantity)

    return ("APPROVED", "PAPER_PREVIEW_APPROVED_SELL_LIMIT", 0, 1, 0, requested_quantity)


def find_existing_intent(
    conn: Any,
    *,
    position: PositionRow,
    intent_state: str,
    reason_code: str,
    requested_quantity_base: Decimal,
    live_trading_enabled: int,
    decision_gate_enabled: int,
    execution_enabled: int,
) -> int | None:
    sql = """
    SELECT execution_sell_intent_id
    FROM execution_sell_intent
    WHERE trading_account_id = %s
      AND asset_id = %s
      AND symbol = %s
      AND venue = %s
      AND intent_source = 'sell_only_decision_gate_preview_v1'
      AND intent_state = %s
      AND side = 'SELL'
      AND order_type = 'LIMIT'
      AND requested_quantity_base = %s
      AND source_position_snapshot_id = %s
      AND live_trading_enabled = %s
      AND decision_gate_enabled = %s
      AND execution_enabled = %s
      AND reason_code <=> %s
    ORDER BY intent_ts_utc DESC, execution_sell_intent_id DESC
    LIMIT 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            sql,
            (
                position.trading_account_id,
                position.asset_id,
                position.symbol,
                position.venue,
                intent_state,
                requested_quantity_base,
                position.account_position_snapshot_id,
                live_trading_enabled,
                decision_gate_enabled,
                execution_enabled,
                reason_code,
            ),
        )
        row = cur.fetchone()

    if not row:
        return None
    return int(row["execution_sell_intent_id"])


def insert_intent(
    conn: Any,
    *,
    position: PositionRow,
    intent_state: str,
    reason_code: str,
    requested_quantity_base: Decimal,
    live_trading_enabled: int,
    decision_gate_enabled: int,
    execution_enabled: int,
) -> int:
    sql = """
    INSERT INTO execution_sell_intent (
        trading_account_id,
        asset_id,
        symbol,
        venue,
        intent_ts_utc,
        intent_source,
        intent_state,
        side,
        order_type,
        requested_quantity_base,
        max_quantity_base,
        reference_price_eur,
        source_position_snapshot_id,
        live_trading_enabled,
        decision_gate_enabled,
        execution_enabled,
        reason_code,
        notes
    )
    VALUES (
        %s,
        %s,
        %s,
        %s,
        UTC_TIMESTAMP(6),
        'sell_only_decision_gate_preview_v1',
        %s,
        'SELL',
        'LIMIT',
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s
    )
    """

    notes = (
        "Sell-only decision-gate preview. "
        "No execution plan, no broker submission, no live order."
    )

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                position.trading_account_id,
                position.asset_id,
                position.symbol,
                position.venue,
                intent_state,
                requested_quantity_base,
                position.available_quantity_base,
                position.mark_price_eur,
                position.account_position_snapshot_id,
                live_trading_enabled,
                decision_gate_enabled,
                execution_enabled,
                reason_code,
                notes,
            ),
        )
        return int(cur.lastrowid)


def print_table(rows: list[DecisionRow]) -> None:
    headers = [
        "account",
        "symbol",
        "qty",
        "available",
        "request",
        "ref_price",
        "state",
        "reason",
        "action",
        "intent_id",
    ]

    table_rows: list[list[str]] = []
    for row in rows:
        table_rows.append(
            [
                row.account_code,
                row.symbol or "NONE",
                "" if row.quantity_base is None else str(row.quantity_base.normalize()),
                "" if row.available_quantity_base is None else str(row.available_quantity_base.normalize()),
                "" if row.requested_quantity_base is None else str(row.requested_quantity_base.normalize()),
                "" if row.reference_price_eur is None else str(row.reference_price_eur.normalize()),
                row.intent_state,
                row.reason_code,
                row.action,
                "" if row.intent_id is None else str(row.intent_id),
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

    request_fraction = Decimal(str(args.request_fraction))
    if request_fraction <= 0 or request_fraction > 1:
        raise SystemExit("--request-fraction must be > 0 and <= 1")

    conn = get_db_connection()
    decisions: list[DecisionRow] = []

    try:
        positions = fetch_latest_positions(conn, account_code=args.account_code, venue=args.venue)

        if not positions:
            trading_account_id = account_exists(conn, args.account_code, args.venue)
            if trading_account_id is None:
                print("[WARN] no matching enabled trading_account rows found")
                return 0

            if args.write_db:
                insert_event(
                    conn,
                    trading_account_id=trading_account_id,
                    execution_sell_intent_id=None,
                    event_type="NO_POSITION_SNAPSHOT",
                    severity="WARN",
                    message="No latest account_position_snapshot rows found for account.",
                    payload={
                        "policy_name": POLICY_NAME,
                        "policy_version": POLICY_VERSION,
                        "account_code": args.account_code,
                        "venue": args.venue,
                        "broker_submission_enabled": False,
                        "execution_plan_enabled": False,
                    },
                )
                conn.commit()

            decisions.append(
                DecisionRow(
                    account_code=args.account_code,
                    trading_account_id=trading_account_id,
                    symbol=None,
                    quantity_base=None,
                    available_quantity_base=None,
                    requested_quantity_base=None,
                    reference_price_eur=None,
                    intent_state="BLOCKED",
                    reason_code="NO_POSITION_SNAPSHOT",
                    side=None,
                    order_type=None,
                    live_trading_enabled=0,
                    decision_gate_enabled=0,
                    execution_enabled=0,
                    action="EVENT_ONLY",
                    intent_id=None,
                )
            )

            if args.output == "table":
                print_table(decisions)

            print()
            print(
                "[DONE] policy="
                f"{POLICY_NAME} version={POLICY_VERSION} rows=1 "
                "inserted_intents=0 reused_intents=0 event_only=1 write_db="
                f"{args.write_db}"
            )
            print("[DONE] broker=disabled planner=disabled live_order_submission=disabled")
            return 0

        inserted = 0
        reused = 0
        blocked = 0
        approved = 0

        for position in positions:
            (
                intent_state,
                reason_code,
                live_trading_enabled,
                decision_gate_enabled,
                execution_enabled,
                requested_quantity,
            ) = decide_position(
                position,
                request_fraction=request_fraction,
                approve_paper_preview=args.approve_paper_preview,
            )

            intent_id: int | None = None
            action = "DRY_RUN"

            if args.write_db:
                existing_intent_id = find_existing_intent(
                    conn,
                    position=position,
                    intent_state=intent_state,
                    reason_code=reason_code,
                    requested_quantity_base=requested_quantity,
                    live_trading_enabled=live_trading_enabled,
                    decision_gate_enabled=decision_gate_enabled,
                    execution_enabled=execution_enabled,
                )

                if existing_intent_id is not None:
                    intent_id = existing_intent_id
                    reused += 1
                    action = "REUSED_INTENT"
                else:
                    intent_id = insert_intent(
                        conn,
                        position=position,
                        intent_state=intent_state,
                        reason_code=reason_code,
                        requested_quantity_base=requested_quantity,
                        live_trading_enabled=live_trading_enabled,
                        decision_gate_enabled=decision_gate_enabled,
                        execution_enabled=execution_enabled,
                    )

                    event_type = (
                        "SELL_ONLY_INTENT_APPROVED_PREVIEW"
                        if intent_state == "APPROVED"
                        else "SELL_ONLY_INTENT_BLOCKED"
                    )
                    message = (
                        "Sell-only preview intent approved. No execution plan or broker submission."
                        if intent_state == "APPROVED"
                        else "Sell-only preview intent created as BLOCKED."
                    )

                    insert_event(
                        conn,
                        trading_account_id=position.trading_account_id,
                        execution_sell_intent_id=intent_id,
                        event_type=event_type,
                        severity="INFO",
                        message=message,
                        payload={
                            "policy_name": POLICY_NAME,
                            "policy_version": POLICY_VERSION,
                            "symbol": position.symbol,
                            "intent_state": intent_state,
                            "reason_code": reason_code,
                            "requested_quantity_base": str(requested_quantity),
                            "reference_price_eur": str(position.mark_price_eur),
                            "broker_submission_enabled": False,
                            "execution_plan_enabled": False,
                            "live_trading_enabled": bool(live_trading_enabled),
                            "decision_gate_enabled": bool(decision_gate_enabled),
                            "execution_enabled": bool(execution_enabled),
                        },
                    )
                    conn.commit()

                    inserted += 1
                    action = "INSERTED_INTENT"

            if intent_state == "APPROVED":
                approved += 1
            else:
                blocked += 1

            decisions.append(
                DecisionRow(
                    account_code=position.account_code,
                    trading_account_id=position.trading_account_id,
                    symbol=position.symbol,
                    quantity_base=position.quantity_base,
                    available_quantity_base=position.available_quantity_base,
                    requested_quantity_base=requested_quantity,
                    reference_price_eur=position.mark_price_eur,
                    intent_state=intent_state,
                    reason_code=reason_code,
                    side="SELL",
                    order_type="LIMIT",
                    live_trading_enabled=live_trading_enabled,
                    decision_gate_enabled=decision_gate_enabled,
                    execution_enabled=execution_enabled,
                    action=action,
                    intent_id=intent_id,
                )
            )

        if args.output == "table":
            print_table(decisions)

        print()
        print(
            "[DONE] policy="
            f"{POLICY_NAME} version={POLICY_VERSION} rows={len(decisions)} "
            f"inserted_intents={inserted} reused_intents={reused} "
            f"approved={approved} blocked={blocked} write_db={args.write_db}"
        )
        print("[DONE] broker=disabled planner=disabled live_order_submission=disabled")

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--request-fraction", default=str(DEFAULT_REQUEST_FRACTION))
    parser.add_argument("--approve-paper-preview", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
