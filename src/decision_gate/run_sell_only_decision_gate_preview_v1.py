from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


POLICY_NAME = "sell_only_decision_gate_preview_v1"
POLICY_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_ORDER_TYPE = "LIMIT"
DEFAULT_SIDE = "SELL"


@dataclass(frozen=True)
class TradingAccount:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: bool
    live_trading_enabled: bool


@dataclass(frozen=True)
class PositionSnapshot:
    account_position_snapshot_id: int
    trading_account_id: int
    asset_id: int
    symbol: str
    venue: str
    quantity_base: Decimal
    available_quantity_base: Decimal
    reserved_quantity_base: Decimal
    average_entry_price_eur: Decimal | None
    mark_price_eur: Decimal | None
    snapshot_ts_utc: datetime


@dataclass(frozen=True)
class PreviewRow:
    account_code: str
    trading_account_id: int
    symbol: str
    asset_id: int | None
    source_position_snapshot_id: int | None
    quantity_base: Decimal | None
    available_quantity_base: Decimal | None
    requested_quantity_base: Decimal | None
    reference_price_eur: Decimal | None
    intent_state: str
    reason_code: str
    action: str
    execution_sell_intent_id: int | None


def utc_now_db() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def decimal_gt_zero(value: Decimal | None) -> bool:
    return value is not None and value > Decimal("0")


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def load_env() -> None:
    load_dotenv(dotenv_path=Path(".env"), override=False)


def fetch_accounts(conn: Any, venue: str, account_code: str | None) -> list[TradingAccount]:
    if account_code:
        sql = """
            SELECT
                trading_account_id,
                account_code,
                venue,
                account_mode,
                enabled,
                live_trading_enabled
            FROM trading_account
            WHERE venue = %s
              AND account_code = %s
            ORDER BY trading_account_id
        """
        params: tuple[Any, ...] = (venue, account_code)
    else:
        sql = """
            SELECT
                trading_account_id,
                account_code,
                venue,
                account_mode,
                enabled,
                live_trading_enabled
            FROM trading_account
            WHERE venue = %s
              AND enabled = 1
            ORDER BY trading_account_id
        """
        params = (venue,)

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        TradingAccount(
            trading_account_id=int(row["trading_account_id"]),
            account_code=str(row["account_code"]),
            venue=str(row["venue"]),
            account_mode=str(row["account_mode"]),
            enabled=bool(row["enabled"]),
            live_trading_enabled=bool(row["live_trading_enabled"]),
        )
        for row in rows
    ]


def fetch_latest_positions(conn: Any, trading_account_id: int, venue: str) -> list[PositionSnapshot]:
    sql = """
        SELECT
            p.account_position_snapshot_id,
            p.trading_account_id,
            p.asset_id,
            p.symbol,
            p.venue,
            p.quantity_base,
            p.available_quantity_base,
            p.reserved_quantity_base,
            p.average_entry_price_eur,
            p.mark_price_eur,
            p.snapshot_ts_utc
        FROM account_position_snapshot p
        INNER JOIN (
            SELECT
                trading_account_id,
                venue,
                symbol,
                MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
            FROM account_position_snapshot
            WHERE trading_account_id = %s
              AND venue = %s
            GROUP BY trading_account_id, venue, symbol
        ) latest
          ON latest.trading_account_id = p.trading_account_id
         AND latest.venue = p.venue
         AND latest.symbol = p.symbol
         AND latest.latest_snapshot_ts_utc = p.snapshot_ts_utc
        WHERE p.trading_account_id = %s
          AND p.venue = %s
        ORDER BY p.symbol
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (trading_account_id, venue, trading_account_id, venue))
        rows = cur.fetchall()

    return [
        PositionSnapshot(
            account_position_snapshot_id=int(row["account_position_snapshot_id"]),
            trading_account_id=int(row["trading_account_id"]),
            asset_id=int(row["asset_id"]),
            symbol=str(row["symbol"]),
            venue=str(row["venue"]),
            quantity_base=Decimal(str(row["quantity_base"])),
            available_quantity_base=Decimal(str(row["available_quantity_base"])),
            reserved_quantity_base=Decimal(str(row["reserved_quantity_base"])),
            average_entry_price_eur=decimal_or_none(row["average_entry_price_eur"]),
            mark_price_eur=decimal_or_none(row["mark_price_eur"]),
            snapshot_ts_utc=row["snapshot_ts_utc"],
        )
        for row in rows
    ]


def choose_reference_price(position: PositionSnapshot) -> Decimal | None:
    if decimal_gt_zero(position.mark_price_eur):
        return position.mark_price_eur
    if decimal_gt_zero(position.average_entry_price_eur):
        return position.average_entry_price_eur
    return None


def evaluate_position(account: TradingAccount, position: PositionSnapshot) -> tuple[str, str, Decimal | None, Decimal | None]:
    if not account.enabled:
        return "BLOCKED", "ACCOUNT_DISABLED", None, choose_reference_price(position)

    if not decimal_gt_zero(position.quantity_base):
        return "BLOCKED", "NO_POSITION", None, choose_reference_price(position)

    if not decimal_gt_zero(position.available_quantity_base):
        return "BLOCKED", "NO_AVAILABLE_QUANTITY", None, choose_reference_price(position)

    if not account.live_trading_enabled:
        return (
            "BLOCKED",
            "LIVE_TRADING_DISABLED",
            position.available_quantity_base,
            choose_reference_price(position),
        )

    return (
        "BLOCKED",
        "SELL_ONLY_PREVIEW_NOT_EXECUTABLE",
        position.available_quantity_base,
        choose_reference_price(position),
    )


def find_existing_intent(
    conn: Any,
    source_position_snapshot_id: int,
    reason_code: str,
) -> int | None:
    sql = """
        SELECT execution_sell_intent_id
        FROM execution_sell_intent
        WHERE source_position_snapshot_id = %s
          AND intent_source = %s
          AND reason_code = %s
        ORDER BY execution_sell_intent_id DESC
        LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(sql, (source_position_snapshot_id, POLICY_NAME, reason_code))
        row = cur.fetchone()

    if not row:
        return None
    return int(row[0])


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
            %s,
            %s,
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
                utc_now_db(),
                "decision_gate",
                event_type,
                severity,
                message,
                json.dumps(payload, default=json_default, sort_keys=True),
            ),
        )


def insert_blocked_intent(
    conn: Any,
    *,
    account: TradingAccount,
    position: PositionSnapshot,
    requested_quantity_base: Decimal,
    reference_price_eur: Decimal | None,
    reason_code: str,
    notes: str,
) -> int:
    sql = """
        INSERT INTO execution_sell_intent (
            trading_account_id,
            asset_id,
            symbol,
            venue,
            intent_ts_utc,
            source_position_snapshot_id,
            requested_quantity_base,
            max_quantity_base,
            reference_price_eur,
            side,
            order_type,
            intent_source,
            intent_state,
            reason_code,
            live_trading_enabled,
            decision_gate_enabled,
            execution_enabled,
            notes
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            'BLOCKED',
            %s,
            0,
            0,
            0,
            %s
        )
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                account.trading_account_id,
                position.asset_id,
                position.symbol,
                position.venue,
                utc_now_db(),
                position.account_position_snapshot_id,
                requested_quantity_base,
                requested_quantity_base,
                reference_price_eur,
                DEFAULT_SIDE,
                DEFAULT_ORDER_TYPE,
                POLICY_NAME,
                reason_code,
                notes,
            ),
        )
        return int(cur.lastrowid)


def process_account(
    conn: Any,
    *,
    account: TradingAccount,
    venue: str,
    write_db: bool,
    max_symbols: int | None,
) -> list[PreviewRow]:
    rows: list[PreviewRow] = []
    positions = fetch_latest_positions(conn, account.trading_account_id, venue)

    if max_symbols is not None:
        positions = positions[:max_symbols]

    if not positions:
        if write_db:
            insert_event(
                conn,
                trading_account_id=account.trading_account_id,
                execution_sell_intent_id=None,
                event_type="NO_POSITION_SNAPSHOT",
                severity="WARN",
                message="No latest account_position_snapshot rows found for account.",
                payload={
                    "policy_name": POLICY_NAME,
                    "policy_version": POLICY_VERSION,
                    "account_code": account.account_code,
                    "venue": venue,
                },
            )
        rows.append(
            PreviewRow(
                account_code=account.account_code,
                trading_account_id=account.trading_account_id,
                symbol="NONE",
                asset_id=None,
                source_position_snapshot_id=None,
                quantity_base=None,
                available_quantity_base=None,
                requested_quantity_base=None,
                reference_price_eur=None,
                intent_state="BLOCKED",
                reason_code="NO_POSITION_SNAPSHOT",
                action="EVENT_ONLY" if write_db else "DRY_RUN_EVENT_ONLY",
                execution_sell_intent_id=None,
            )
        )
        return rows

    for position in positions:
        intent_state, reason_code, requested_quantity, reference_price = evaluate_position(account, position)

        if not decimal_gt_zero(requested_quantity):
            if write_db:
                insert_event(
                    conn,
                    trading_account_id=account.trading_account_id,
                    execution_sell_intent_id=None,
                    event_type=reason_code,
                    severity="INFO",
                    message="Position is not sellable by sell-only decision gate preview.",
                    payload={
                        "policy_name": POLICY_NAME,
                        "policy_version": POLICY_VERSION,
                        "account_code": account.account_code,
                        "symbol": position.symbol,
                        "asset_id": position.asset_id,
                        "source_position_snapshot_id": position.account_position_snapshot_id,
                        "quantity_base": position.quantity_base,
                        "available_quantity_base": position.available_quantity_base,
                        "reserved_quantity_base": position.reserved_quantity_base,
                        "reason_code": reason_code,
                    },
                )

            rows.append(
                PreviewRow(
                    account_code=account.account_code,
                    trading_account_id=account.trading_account_id,
                    symbol=position.symbol,
                    asset_id=position.asset_id,
                    source_position_snapshot_id=position.account_position_snapshot_id,
                    quantity_base=position.quantity_base,
                    available_quantity_base=position.available_quantity_base,
                    requested_quantity_base=None,
                    reference_price_eur=reference_price,
                    intent_state=intent_state,
                    reason_code=reason_code,
                    action="EVENT_ONLY" if write_db else "DRY_RUN_EVENT_ONLY",
                    execution_sell_intent_id=None,
                )
            )
            continue

        existing_id = find_existing_intent(
            conn,
            source_position_snapshot_id=position.account_position_snapshot_id,
            reason_code=reason_code,
        )

        if existing_id is not None:
            if write_db:
                insert_event(
                    conn,
                    trading_account_id=account.trading_account_id,
                    execution_sell_intent_id=existing_id,
                    event_type="DUPLICATE_INTENT_SKIPPED",
                    severity="INFO",
                    message="Existing sell-only preview intent found for same position snapshot and reason.",
                    payload={
                        "policy_name": POLICY_NAME,
                        "policy_version": POLICY_VERSION,
                        "account_code": account.account_code,
                        "symbol": position.symbol,
                        "asset_id": position.asset_id,
                        "source_position_snapshot_id": position.account_position_snapshot_id,
                        "reason_code": reason_code,
                        "existing_execution_sell_intent_id": existing_id,
                    },
                )

            rows.append(
                PreviewRow(
                    account_code=account.account_code,
                    trading_account_id=account.trading_account_id,
                    symbol=position.symbol,
                    asset_id=position.asset_id,
                    source_position_snapshot_id=position.account_position_snapshot_id,
                    quantity_base=position.quantity_base,
                    available_quantity_base=position.available_quantity_base,
                    requested_quantity_base=requested_quantity,
                    reference_price_eur=reference_price,
                    intent_state=intent_state,
                    reason_code=reason_code,
                    action="SKIPPED_DUPLICATE",
                    execution_sell_intent_id=existing_id,
                )
            )
            continue

        new_id: int | None = None

        if write_db:
            new_id = insert_blocked_intent(
                conn,
                account=account,
                position=position,
                requested_quantity_base=requested_quantity,
                reference_price_eur=reference_price,
                reason_code=reason_code,
                notes="sell-only decision gate preview; no planner, no broker, no order",
            )
            insert_event(
                conn,
                trading_account_id=account.trading_account_id,
                execution_sell_intent_id=new_id,
                event_type="SELL_ONLY_INTENT_BLOCKED",
                severity="INFO",
                message="Sell-only preview intent created as BLOCKED.",
                payload={
                    "policy_name": POLICY_NAME,
                    "policy_version": POLICY_VERSION,
                    "account_code": account.account_code,
                    "symbol": position.symbol,
                    "asset_id": position.asset_id,
                    "source_position_snapshot_id": position.account_position_snapshot_id,
                    "requested_quantity_base": requested_quantity,
                    "reference_price_eur": reference_price,
                    "reason_code": reason_code,
                    "broker_enabled": False,
                    "planner_enabled": False,
                },
            )

        rows.append(
            PreviewRow(
                account_code=account.account_code,
                trading_account_id=account.trading_account_id,
                symbol=position.symbol,
                asset_id=position.asset_id,
                source_position_snapshot_id=position.account_position_snapshot_id,
                quantity_base=position.quantity_base,
                available_quantity_base=position.available_quantity_base,
                requested_quantity_base=requested_quantity,
                reference_price_eur=reference_price,
                intent_state=intent_state,
                reason_code=reason_code,
                action="INSERTED_BLOCKED_INTENT" if write_db else "DRY_RUN_BLOCKED_INTENT",
                execution_sell_intent_id=new_id,
            )
        )

    return rows


def fmt_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def print_table(rows: list[PreviewRow]) -> None:
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

    table_rows = [
        [
            row.account_code,
            row.symbol,
            fmt_decimal(row.quantity_base),
            fmt_decimal(row.available_quantity_base),
            fmt_decimal(row.requested_quantity_base),
            fmt_decimal(row.reference_price_eur),
            row.intent_state,
            row.reason_code,
            row.action,
            "" if row.execution_sell_intent_id is None else str(row.execution_sell_intent_id),
        ]
        for row in rows
    ]

    widths = [
        max(len(str(item)) for item in [header] + [table_row[index] for table_row in table_rows])
        for index, header in enumerate(headers)
    ]

    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for table_row in table_rows:
        print(" | ".join(str(value).ljust(widths[index]) for index, value in enumerate(table_row)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write or preview sell-only decision-gate BLOCKED intents from latest account positions."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--account-code", default=None)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env()

    conn = get_db_connection()
    all_rows: list[PreviewRow] = []

    try:
        accounts = fetch_accounts(conn, venue=args.venue, account_code=args.account_code)

        if not accounts:
            print("[WARN] no matching enabled trading_account rows found")
            return 0

        for account in accounts:
            rows = process_account(
                conn,
                account=account,
                venue=args.venue,
                write_db=bool(args.write_db),
                max_symbols=args.max_symbols,
            )
            all_rows.extend(rows)

        if args.write_db:
            conn.commit()

    except Exception:
        if args.write_db:
            conn.rollback()
        raise
    finally:
        conn.close()

    if args.output == "table":
        print_table(all_rows)

    inserted = sum(1 for row in all_rows if row.action == "INSERTED_BLOCKED_INTENT")
    duplicates = sum(1 for row in all_rows if row.action == "SKIPPED_DUPLICATE")
    event_only = sum(1 for row in all_rows if row.action.endswith("EVENT_ONLY"))

    print()
    print(
        f"[DONE] policy={POLICY_NAME} version={POLICY_VERSION} "
        f"rows={len(all_rows)} inserted_blocked_intents={inserted} "
        f"duplicates={duplicates} event_only={event_only} write_db={bool(args.write_db)}"
    )
    print("[DONE] broker=disabled planner=disabled live_order_submission=disabled")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
