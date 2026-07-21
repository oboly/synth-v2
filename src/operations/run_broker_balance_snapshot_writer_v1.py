from __future__ import annotations

import argparse
import json
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


WRITER_NAME = "broker_balance_snapshot_writer_v1"
WRITER_VERSION = "0.3"
DEFAULT_VENUE = "bitvavo"
SOURCE_NAME = "bitvavo_private_balance_read_v1"


@dataclass(frozen=True)
class TradingAccount:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: int
    live_trading_enabled: int


@dataclass(frozen=True)
class BalanceRow:
    currency_code: str
    available_amount: Decimal
    reserved_amount: Decimal
    total_amount: Decimal
    raw: dict[str, Any]


@dataclass(frozen=True)
class WriteResult:
    currency_code: str
    action: str
    row_id: int | None
    snapshot_ts_utc: datetime


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def decimal_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def format_decimal(value: Decimal) -> str:
    out = format(value, "f")
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out or "0"


def fetch_trading_account(conn: Any, account_code: str, venue: str) -> TradingAccount:
    sql = (
        "SELECT "
        "trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled "
        "FROM trading_account "
        "WHERE account_code = %s "
        "AND venue = %s "
        "LIMIT 1"
    )

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()

    if not row:
        raise RuntimeError(f"trading_account not found: account_code={account_code} venue={venue}")

    account = TradingAccount(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=int(row["enabled"]),
        live_trading_enabled=int(row["live_trading_enabled"]),
    )

    if account.enabled != 1:
        raise RuntimeError(f"trading_account disabled: account_code={account_code}")

    if account.live_trading_enabled != 0:
        raise RuntimeError(
            "Refusing broker balance snapshot for account with live_trading_enabled != 0."
        )

    return account


def normalize_balance_rows(raw_balances: Any) -> list[BalanceRow]:
    if isinstance(raw_balances, dict):
        rows = [raw_balances]
    elif isinstance(raw_balances, list):
        rows = raw_balances
    else:
        raise RuntimeError(f"Unexpected Bitvavo balance payload type: {type(raw_balances)}")

    normalized: list[BalanceRow] = []

    for raw in rows:
        if not isinstance(raw, dict):
            continue

        currency_code = str(
            raw.get("symbol")
            or raw.get("currency")
            or raw.get("asset")
            or ""
        ).strip().upper()

        if not currency_code:
            continue

        available_amount = decimal_value(raw.get("available"))
        reserved_amount = decimal_value(
            raw.get("inOrder")
            if raw.get("inOrder") is not None
            else raw.get("reserved")
        )
        total_amount = available_amount + reserved_amount

        normalized.append(
            BalanceRow(
                currency_code=currency_code,
                available_amount=available_amount,
                reserved_amount=reserved_amount,
                total_amount=total_amount,
                raw=raw,
            )
        )

    return sorted(normalized, key=lambda row: row.currency_code)


def insert_balance_rows(
    conn: Any,
    *,
    account: TradingAccount,
    balances: list[BalanceRow],
    snapshot_ts_utc: datetime,
) -> list[WriteResult]:
    sql = (
        "INSERT INTO trading_account_balance_snapshot ("
        "snapshot_ts_utc, "
        "trading_account_id, "
        "venue, "
        "currency_code, "
        "available_amount, "
        "reserved_amount, "
        "total_amount, "
        "source_name, "
        "raw_json"
        ") VALUES ("
        "%s, %s, %s, %s, %s, %s, %s, %s, %s"
        ")"
    )

    results: list[WriteResult] = []

    with conn.cursor() as cur:
        for balance in balances:
            cur.execute(
                sql,
                (
                    snapshot_ts_utc,
                    account.trading_account_id,
                    account.venue,
                    balance.currency_code,
                    balance.available_amount,
                    balance.reserved_amount,
                    balance.total_amount,
                    SOURCE_NAME,
                    json.dumps(
                        balance.raw,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ),
                ),
            )

            results.append(
                WriteResult(
                    currency_code=balance.currency_code,
                    action="INSERTED",
                    row_id=int(cur.lastrowid),
                    snapshot_ts_utc=snapshot_ts_utc,
                )
            )

    conn.commit()
    return results


def print_balance_table(balances: list[BalanceRow]) -> None:
    headers = ["currency", "available", "reserved", "total"]
    rows = [
        [
            row.currency_code,
            format_decimal(row.available_amount),
            format_decimal(row.reserved_amount),
            format_decimal(row.total_amount),
        ]
        for row in balances
    ]

    print_table(headers, rows)


def print_write_table(results: list[WriteResult]) -> None:
    headers = ["currency", "action", "row_id", "snapshot_ts_utc"]
    rows = [
        [
            row.currency_code,
            row.action,
            "" if row.row_id is None else str(row.row_id),
            row.snapshot_ts_utc.isoformat(sep=" "),
        ]
        for row in results
    ]

    print_table(headers, rows)


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
            "account_code="
            f"{account.account_code} "
            "trading_account_id="
            f"{account.trading_account_id} "
            "venue="
            f"{account.venue}"
        )
        print(f"credential_profile_id={resolved.profile.trading_account_credential_id}")
        print(f"credential_fingerprint={resolved.profile.credential_fingerprint}")
        print(f"permission_scope={resolved.profile.permission_scope}")
        print(f"validation_state={resolved.profile.validation_state}")
        print("[INFO] private read only; no broker writes; no orders; no position mutation")

        client = resolved.client

        raw_balances = client.get_balance(symbol=args.symbol)
        snapshot_ts_utc = utc_now_naive()
        balances = normalize_balance_rows(raw_balances)

        if not balances:
            print()
            print("[WARN] no balances returned")
            print(
                "[DONE] private_balance_fetch=True rows=0 db_writes=0 "
                "broker_writes=0 order_submission=0 position_mutation=0"
            )
            return 0

        print()
        print(f"snapshot_ts_utc={snapshot_ts_utc.isoformat(sep=' ')}")
        print(f"balance_rows={len(balances)}")
        print("currencies=" + ",".join(row.currency_code for row in balances))

        if args.output == "table":
            print()
            print("--- balances ---")
            print_balance_table(balances)

        db_writes = 0

        if args.write_db:
            results = insert_balance_rows(
                conn,
                account=account,
                balances=balances,
                snapshot_ts_utc=snapshot_ts_utc,
            )
            db_writes = len(results)

            if args.output == "table":
                print()
                print("--- write results ---")
                print_write_table(results)

            distinct_snapshot_ts = {result.snapshot_ts_utc for result in results}
            print()
            print(
                "[BATCH] "
                f"rows={len(results)} "
                f"distinct_snapshot_ts={len(distinct_snapshot_ts)} "
                f"snapshot_ts_utc={snapshot_ts_utc.isoformat(sep=' ')}"
            )

            if len(distinct_snapshot_ts) != 1:
                raise RuntimeError("Batch timestamp invariant failed.")

        print()
        print(
            "[DONE] private_balance_fetch=True "
            f"rows={len(balances)} "
            f"db_writes={db_writes} "
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
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
