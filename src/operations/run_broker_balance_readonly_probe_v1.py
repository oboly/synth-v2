from __future__ import annotations

import argparse
import os
from decimal import Decimal, InvalidOperation
from typing import Any

from dotenv import load_dotenv

from src.execution.bitvavo_client import (
    BROKER_PRIVATE_READ_PERMISSION_ENV,
    BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
    BitvavoClient,
)


REPORT_NAME = "broker_balance_readonly_probe_v1"
REPORT_VERSION = "0.1"


def decimal_from_text(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def env_presence(name: str) -> str:
    value = os.getenv(name, "")
    return "PRESENT" if value else "MISSING"


def permission_state(name: str, granted_value: str) -> str:
    value = os.getenv(name, "")
    if not value:
        return "MISSING"
    if value == granted_value:
        return "GRANTED"
    return "PRESENT_BUT_NOT_GRANTED"


def print_env_report() -> None:
    rows = [
        ("BITVAVO_API_KEY", env_presence("BITVAVO_API_KEY")),
        ("BITVAVO_API_SECRET", env_presence("BITVAVO_API_SECRET")),
        ("BITVAVO_REST_URL", env_presence("BITVAVO_REST_URL")),
        ("BITVAVO_BASE_URL", env_presence("BITVAVO_BASE_URL")),
        (
            BROKER_PRIVATE_READ_PERMISSION_ENV,
            permission_state(
                BROKER_PRIVATE_READ_PERMISSION_ENV,
                BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
            ),
        ),
        (
            BROKER_WRITE_PERMISSION_ENV,
            permission_state(
                BROKER_WRITE_PERMISSION_ENV,
                BROKER_WRITE_PERMISSION_GRANTED_VALUE,
            ),
        ),
    ]

    print("--- broker env readiness, values redacted ---")
    for key, state in rows:
        print(f"{key}={state}")


def print_balance_table(rows: list[dict[str, Any]]) -> None:
    headers = ["symbol", "available", "in_order", "total"]

    table_rows: list[list[str]] = []
    for row in rows:
        available = decimal_from_text(row.get("available"))
        in_order = decimal_from_text(row.get("inOrder"))
        total = available + in_order

        table_rows.append(
            [
                str(row.get("symbol", "")),
                str(available.normalize()),
                str(in_order.normalize()),
                str(total.normalize()),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only Bitvavo balance probe.")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--fetch-private-balance", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("[INFO] read-only probe; no DB writes; no broker writes; no order submission")
    print_env_report()

    if not args.fetch_private_balance:
        print()
        print("[DONE] readiness_only=True private_balance_fetch=False")
        return 0

    print()
    print("--- private balance fetch ---")

    client = BitvavoClient(timeout_seconds=args.timeout_seconds)

    try:
        balances = client.get_balance(symbol=args.symbol)
    except PermissionError as exc:
        print(f"[BLOCKED] {exc}")
        print("[DONE] private_balance_fetch=False reason=PRIVATE_READ_PERMISSION_NOT_GRANTED")
        return 0
    except RuntimeError as exc:
        print(f"[BLOCKED] {exc}")
        print("[DONE] private_balance_fetch=False reason=PRIVATE_READ_NOT_READY")
        return 0

    if args.output == "table":
        print_balance_table(balances)

    print()
    print(f"[DONE] private_balance_fetch=True rows={len(balances)} db_writes=0 broker_writes=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
