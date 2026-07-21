from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.account.private_read_credential_resolver_v1 import (
    PrivateReadCredentialResolutionError,
    resolve_private_read_bitvavo_client_from_env,
)
from src.common.db import get_db_connection


WRITER_NAME = "broker_order_snapshot_writer_v1"
WRITER_VERSION = "0.2"
DEFAULT_VENUE = "bitvavo"


@dataclass(frozen=True)
class TradingAccount:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: int
    live_trading_enabled: int


@dataclass(frozen=True)
class BrokerOrderSnapshotRow:
    venue: str
    symbol: str
    broker_order_id: str
    client_order_id: str | None
    side: str
    order_type: str
    limit_price_eur: Decimal | None
    quantity_base: Decimal
    filled_quantity_base: Decimal
    remaining_quantity_base: Decimal
    broker_status: str
    raw_json: str


def decimal_value(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_snapshot_ts(value: str | None) -> datetime:
    if not value:
        return utc_now_naive()

    cleaned = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(cleaned)

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


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


def fetch_trading_account(conn: Any, *, account_code: str, venue: str) -> TradingAccount:
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
        raise RuntimeError(f"Trading account not found: account_code={account_code} venue={venue}")

    account = TradingAccount(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=int(row["enabled"]),
        live_trading_enabled=int(row["live_trading_enabled"]),
    )

    if account.enabled != 1:
        raise RuntimeError(f"Trading account disabled: account_code={account.account_code}")

    if account.live_trading_enabled != 0:
        raise RuntimeError(
            "Refusing broker snapshot writer because trading_account.live_trading_enabled is not 0."
        )

    return account


def normalize_order(order: dict[str, Any], *, venue: str) -> BrokerOrderSnapshotRow | None:
    market = str(order.get("market") or "")
    if not market.endswith("-EUR"):
        return None

    symbol = market[:-4]
    side = str(order.get("side") or "").upper()
    order_type = str(order.get("orderType") or "").upper()
    broker_status = str(order.get("status") or "UNKNOWN").upper()

    if side != "SELL" or order_type != "LIMIT":
        return None

    broker_order_id = str(order.get("orderId") or "")
    if not broker_order_id:
        return None

    quantity_base = decimal_value(order.get("amount"))
    remaining_quantity_base = decimal_value(order.get("amountRemaining"))
    filled_quantity_base = quantity_base - remaining_quantity_base

    if quantity_base <= 0:
        return None

    if filled_quantity_base < 0:
        filled_quantity_base = Decimal("0")

    raw = dict(order)
    raw["_synth_source"] = WRITER_NAME
    raw["_synth_version"] = WRITER_VERSION
    raw["_synth_note"] = "Private broker read snapshot only. No order placement or cancellation."

    return BrokerOrderSnapshotRow(
        venue=venue,
        symbol=symbol,
        broker_order_id=broker_order_id,
        client_order_id=order.get("clientOrderId"),
        side=side,
        order_type=order_type,
        limit_price_eur=optional_decimal(order.get("price")),
        quantity_base=quantity_base,
        filled_quantity_base=filled_quantity_base,
        remaining_quantity_base=remaining_quantity_base,
        broker_status=broker_status,
        raw_json=json.dumps(raw, sort_keys=True, separators=(",", ":")),
    )


def write_snapshot_rows(
    conn: Any,
    *,
    account: TradingAccount,
    snapshot_ts_utc: datetime,
    rows: list[BrokerOrderSnapshotRow],
) -> int:
    sql = """
    INSERT INTO broker_order_snapshot (
        snapshot_ts_utc,
        trading_account_id,
        execution_intent_id,
        venue,
        symbol,
        broker_order_id,
        client_order_id,
        side,
        order_type,
        limit_price_eur,
        quantity_base,
        filled_quantity_base,
        remaining_quantity_base,
        broker_status,
        raw_json
    ) VALUES (
        %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        client_order_id = VALUES(client_order_id),
        limit_price_eur = VALUES(limit_price_eur),
        quantity_base = VALUES(quantity_base),
        filled_quantity_base = VALUES(filled_quantity_base),
        remaining_quantity_base = VALUES(remaining_quantity_base),
        broker_status = VALUES(broker_status),
        raw_json = VALUES(raw_json)
    """

    written = 0

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                sql,
                (
                    snapshot_ts_utc,
                    account.trading_account_id,
                    row.venue,
                    row.symbol,
                    row.broker_order_id,
                    row.client_order_id,
                    row.side,
                    row.order_type,
                    row.limit_price_eur,
                    row.quantity_base,
                    row.filled_quantity_base,
                    row.remaining_quantity_base,
                    row.broker_status,
                    row.raw_json,
                ),
            )
            written += 1

    conn.commit()
    return written


def fetch_latest_snapshot_summary(
    conn: Any,
    *,
    account: TradingAccount,
    snapshot_ts_utc: datetime,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        broker_status,
        side,
        order_type,
        COUNT(*) AS rows_total,
        COUNT(DISTINCT snapshot_ts_utc) AS distinct_snapshot_ts,
        MIN(snapshot_ts_utc) AS min_snapshot_ts_utc,
        MAX(snapshot_ts_utc) AS max_snapshot_ts_utc,
        SUM(quantity_base) AS quantity_base_total,
        SUM(remaining_quantity_base) AS remaining_quantity_base_total
    FROM broker_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND snapshot_ts_utc = %s
    GROUP BY broker_status, side, order_type
    ORDER BY broker_status, side, order_type
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account.trading_account_id, account.venue, snapshot_ts_utc))
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


def print_snapshot_rows(rows: list[BrokerOrderSnapshotRow], *, limit: int) -> None:
    headers = [
        "symbol",
        "status",
        "side",
        "type",
        "qty",
        "remaining",
        "filled",
        "limit_price",
    ]

    table_rows: list[list[str]] = []

    for row in rows[:limit]:
        table_rows.append(
            [
                row.symbol,
                row.broker_status,
                row.side,
                row.order_type,
                format_decimal(row.quantity_base),
                format_decimal(row.remaining_quantity_base),
                format_decimal(row.filled_quantity_base),
                format_decimal(row.limit_price_eur),
            ]
        )

    if not table_rows:
        print("(no rows)")
        return

    print_table(headers, table_rows)

    if len(rows) > limit:
        print(f"[INFO] output truncated rows_shown={limit} rows_total={len(rows)}")


def print_summary_rows(rows: list[dict[str, Any]]) -> None:
    headers = [
        "status",
        "side",
        "type",
        "rows",
        "distinct_ts",
        "qty_total",
        "remaining_total",
    ]

    table_rows = [
        [
            str(row["broker_status"]),
            str(row["side"]),
            str(row["order_type"]),
            str(row["rows_total"]),
            str(row["distinct_snapshot_ts"]),
            format_decimal(row["quantity_base_total"]),
            format_decimal(row["remaining_quantity_base_total"]),
        ]
        for row in rows
    ]

    print_table(headers, table_rows)


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    write_permission = broker_write_permission_state()
    if write_permission == "GRANTED":
        print("FAIL: SYNTH_BROKER_WRITE_PERMISSION is granted; refusing read-only snapshot writer.")
        return 2

    snapshot_ts_utc = parse_snapshot_ts(args.snapshot_ts_utc)

    conn = get_db_connection()

    try:
        resolved = resolve_private_read_bitvavo_client_from_env(
            conn,
            trading_account_id=args.trading_account_id,
            account_code=args.account_code,
            profile_code=args.account_profile,
            venue=args.venue,
            timeout_seconds=args.timeout_seconds,
        )
        account = fetch_trading_account(
            conn,
            account_code=resolved.identity.account_code,
            venue=resolved.identity.venue,
        )

        print(f"writer={WRITER_NAME} version={WRITER_VERSION}")
        print(
            f"account_code={account.account_code} "
            f"trading_account_id={account.trading_account_id} "
            f"venue={account.venue}"
        )
        print("[INFO] private read only; DB writes only to broker_order_snapshot; no broker writes; no orders")
        print(f"snapshot_ts_utc={snapshot_ts_utc}")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")
        print(f"credential_profile_id={resolved.profile.trading_account_credential_id}")
        print(f"credential_fingerprint={resolved.profile.credential_fingerprint}")
        print(f"permission_scope={resolved.profile.permission_scope}")
        print(f"validation_state={resolved.profile.validation_state}")

        client = resolved.client
        raw_orders = client.get_open_orders(market=args.market, base=args.base)

        normalized_rows: list[BrokerOrderSnapshotRow] = []
        skipped_rows = 0

        for order in raw_orders:
            normalized = normalize_order(order, venue=args.venue)
            if normalized is None:
                skipped_rows += 1
                continue
            normalized_rows.append(normalized)

        print()
        print("--- read result ---")
        print(f"raw_orders={len(raw_orders)}")
        print(f"normalized_sell_limit_eur_rows={len(normalized_rows)}")
        print(f"skipped_rows={skipped_rows}")

        if args.output == "table":
            print()
            print("--- normalized rows preview ---")
            print_snapshot_rows(normalized_rows, limit=args.limit)

        written = 0
        if args.write_db:
            written = write_snapshot_rows(
                conn,
                account=account,
                snapshot_ts_utc=snapshot_ts_utc,
                rows=normalized_rows,
            )

            summary_rows = fetch_latest_snapshot_summary(
                conn,
                account=account,
                snapshot_ts_utc=snapshot_ts_utc,
            )

            print()
            print("--- written snapshot summary ---")
            print_summary_rows(summary_rows)
        else:
            print()
            print("[DRY_RUN] no DB writes performed")

        print()
        print(
            "[DONE] "
            f"private_open_orders_fetch=True "
            f"rows={len(normalized_rows)} "
            f"db_writes={written} "
            "broker_writes=0 order_submission=0 position_mutation=0"
        )

        return 0

    except PrivateReadCredentialResolutionError as exc:
        print(f"[ERROR] credential_resolution={exc}")
        return 2
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--trading-account-id", type=int, default=None)
    identity.add_argument("--account-code", default=None)
    identity.add_argument("--account-profile", default=None)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--market", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--snapshot-ts-utc", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
