from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.execution.bitvavo_client import BitvavoClient


WRITER_NAME = "broker_balance_snapshot_writer_v1"
WRITER_VERSION = "0.1"
DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
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


def decimal_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def fetch_trading_account(conn: Any, account_code: str, venue: str) -> TradingAccount:
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
        raise RuntimeError(f"trading_account not found account_code={account_code} venue={venue}")

    account = TradingAccount(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=int(row["enabled"]),
        live_trading_enabled=int(row["live_trading_enabled"]),
    )

    if account.enabled != 1:
        raise RuntimeError(f"trading_account disabled account_code={account_code}")

    if account.account_mode != "live":
        raise RuntimeError(
            "broker private balances must be attached to a live/read-context trading_account, "
            f"got account_mode={account.account_mode}"
        )

    if account.live_trading_enabled != 0:
        raise RuntimeError("live_trading_enabled must remain 0 for read-only broker snapshot writer")

    return account


def normalize_balance_rows(raw_rows: list[dict[str, Any]], include_zero: bool) -> list[BalanceRow]:
    out: list[BalanceRow] = []

    for raw in raw_rows:
        currency_code = str(raw.get("symbol") or raw.get("currency") or "").upper().strip()
        if not currency_code:
            continue

        available_amount = decimal_value(raw.get("available"))
        reserved_amount = decimal_value(raw.get("inOrder"))
        total_amount = available_amount + reserved_amount

        if not include_zero and total_amount <= 0:
            continue

        out.append(
            BalanceRow(
                currency_code=currency_code,
                available_amount=available_amount,
                reserved_amount=reserved_amount,
                total_amount=total_amount,
                raw=raw,
            )
        )

    return sorted(out, key=lambda row: row.currency_code)


def insert_balance_snapshot_rows(
    conn: Any,
    *,
    account: TradingAccount,
    balances: list[BalanceRow],
) -> list[WriteResult]:
    sql = """
    INSERT INTO trading_account_balance_snapshot (
        snapshot_ts_utc,
        trading_account_id,
        venue,
        currency_code,
        available_amount,
        reserved_amount,
        total_amount,
        source_name,
        raw_json
    )
    VALUES (
        UTC_TIMESTAMP(6),
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

    results: list[WriteResult] = []

    with conn.cursor() as cur:
        for balance in balances:
            cur.execute(
                sql,
                (
                    account.trading_account_id,
                    account.venue,
                    balance.currency_code,
                    balance.available_amount,
                    balance.reserved_amount,
                    balance.total_amount,
                    SOURCE_NAME,
                    json.dumps(balance.raw, sort_keys=True),
                ),
            )
            results.append(
                WriteResult(
                    currency_code=balance.currency_code,
                    action="INSERTED",
                    row_id=int(cur.lastrowid),
                )
            )

    conn.commit()
    return results


def print_summary(
    *,
    account: TradingAccount,
    balances: list[BalanceRow],
    write_results: list[WriteResult],
    write_db: bool,
    show_amounts: bool,
) -> None:
    print(f"writer={WRITER_NAME} version={WRITER_VERSION}")
    print(f"account_code={account.account_code} trading_account_id={account.trading_account_id} venue={account.venue}")
    print("[INFO] private read only; no broker writes; no orders; no position mutation")
    print()

    if show_amounts:
        print("--- balances ---")
        print("currency | available | reserved | total")
        print("---------+-----------+----------+------")
        for row in balances:
            print(
                f"{row.currency_code:<8} | "
                f"{str(row.available_amount):<9} | "
                f"{str(row.reserved_amount):<8} | "
                f"{str(row.total_amount)}"
            )
        print()
    else:
        symbols = ",".join(row.currency_code for row in balances)
        print(f"balance_rows={len(balances)}")
        print(f"currencies={symbols}")
        print()

    if write_db:
        print("--- write results ---")
        for result in write_results:
            print({"currency_code": result.currency_code, "action": result.action, "row_id": result.row_id})
        print()

    print(
        "[DONE] "
        f"private_balance_fetch=True rows={len(balances)} "
        f"db_writes={len(write_results) if write_db else 0} "
        "broker_writes=0 order_submission=0 position_mutation=0"
    )


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()

    try:
        account = fetch_trading_account(conn, account_code=args.account_code, venue=args.venue)

        client = BitvavoClient(timeout_seconds=args.timeout_seconds)
        raw_balances = client.get_balance(symbol=args.symbol)

        balances = normalize_balance_rows(raw_balances, include_zero=args.include_zero)

        write_results: list[WriteResult] = []
        if args.write_db:
            write_results = insert_balance_snapshot_rows(conn, account=account, balances=balances)

        if args.output == "table":
            print_summary(
                account=account,
                balances=balances,
                write_results=write_results,
                write_db=args.write_db,
                show_amounts=args.show_amounts,
            )

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write private-read broker balance snapshots.")
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--include-zero", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--show-amounts", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
