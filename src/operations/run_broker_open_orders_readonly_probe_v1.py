from __future__ import annotations

import argparse
import os
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.execution.bitvavo_client import BitvavoClient


REPORT_NAME = "broker_open_orders_readonly_probe_v1"
REPORT_VERSION = "0.1"


def env_state(name: str, *, granted_value: str | None = None) -> str:
    value = os.getenv(name)

    if value is None or value == "":
        return "MISSING"

    if granted_value is not None:
        return "GRANTED" if value == granted_value else "PRESENT_BUT_NOT_GRANTED"

    return "PRESENT"


def format_decimal(value: Any) -> str:
    if value is None:
        return ""

    dec = Decimal(str(value))
    out = format(dec, "f")

    if "." in out:
        out = out.rstrip("0").rstrip(".")

    return out or "0"


def mask_text(value: Any, *, prefix: int = 8, suffix: int = 6) -> str:
    if value is None:
        return ""

    text = str(value)
    if len(text) <= prefix + suffix + 3:
        return text

    return f"{text[:prefix]}...{text[-suffix:]}"


def print_env_readiness() -> None:
    print("--- broker env readiness, values redacted ---")
    print(f"BITVAVO_API_KEY={env_state('BITVAVO_API_KEY')}")
    print(f"BITVAVO_API_SECRET={env_state('BITVAVO_API_SECRET')}")
    print(f"BITVAVO_REST_URL={env_state('BITVAVO_REST_URL')}")
    print(f"BITVAVO_BASE_URL={env_state('BITVAVO_BASE_URL')}")
    print(
        "SYNTH_BROKER_PRIVATE_READ_PERMISSION="
        f"{env_state('SYNTH_BROKER_PRIVATE_READ_PERMISSION', granted_value='I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA')}"
    )
    print(
        "SYNTH_BROKER_WRITE_PERMISSION="
        f"{env_state('SYNTH_BROKER_WRITE_PERMISSION', granted_value='I_UNDERSTAND_THIS_PLACES_REAL_ORDERS')}"
    )


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)))


def print_open_orders(orders: list[dict[str, Any]], *, limit: int) -> None:
    headers = [
        "market",
        "side",
        "type",
        "status",
        "amount",
        "remaining",
        "price",
        "on_hold",
        "hold_ccy",
        "order_id",
    ]

    table_rows: list[list[str]] = []

    for order in orders[:limit]:
        table_rows.append(
            [
                str(order.get("market") or ""),
                str(order.get("side") or ""),
                str(order.get("orderType") or ""),
                str(order.get("status") or ""),
                format_decimal(order.get("amount")),
                format_decimal(order.get("amountRemaining")),
                format_decimal(order.get("price")),
                format_decimal(order.get("onHold")),
                str(order.get("onHoldCurrency") or ""),
                mask_text(order.get("orderId")),
            ]
        )

    if not table_rows:
        print("(no open orders)")
        return

    print_table(headers, table_rows)

    if len(orders) > limit:
        print(f"[INFO] output truncated rows_shown={limit} rows_total={len(orders)}")


def summarize_open_orders(orders: list[dict[str, Any]]) -> None:
    by_status: dict[str, int] = {}
    by_side: dict[str, int] = {}
    by_hold_currency: dict[str, int] = {}

    for order in orders:
        status = str(order.get("status") or "UNKNOWN")
        side = str(order.get("side") or "UNKNOWN")
        hold_currency = str(order.get("onHoldCurrency") or "NONE")

        by_status[status] = by_status.get(status, 0) + 1
        by_side[side] = by_side.get(side, 0) + 1
        by_hold_currency[hold_currency] = by_hold_currency.get(hold_currency, 0) + 1

    print("--- summary ---")
    print(f"orders_total={len(orders)}")
    print("by_status=" + ",".join(f"{k}:{v}" for k, v in sorted(by_status.items())))
    print("by_side=" + ",".join(f"{k}:{v}" for k, v in sorted(by_side.items())))
    print("by_hold_currency=" + ",".join(f"{k}:{v}" for k, v in sorted(by_hold_currency.items())))


def print_http_error(exc: BaseException) -> None:
    response = getattr(exc, "response", None)

    if response is None:
        print("[ERROR] broker open orders request failed")
        print(f"error_type={type(exc).__name__}")
        print(f"error={exc}")
        return

    status_code = getattr(response, "status_code", None)
    print("[HTTP_ERROR] Bitvavo private open orders request rejected")
    print(f"status_code={status_code}")

    try:
        payload = response.json()
    except Exception:
        payload = {}

    if isinstance(payload, dict):
        print(f"error_code={payload.get('errorCode')}")
        print(f"error={payload.get('error')}")
        print(f"message={payload.get('message')}")
    else:
        print(f"raw_error={payload}")


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("[INFO] private read-only probe; no DB writes; no broker writes; no order submission")

    print_env_readiness()

    if not args.fetch_open_orders:
        print()
        print("[DONE] readiness_only=True open_orders_fetch=False")
        return 0

    print()
    print("--- private open orders fetch ---")

    try:
        client = BitvavoClient(timeout_seconds=args.timeout_seconds)
        orders = client.get_open_orders(market=args.market, base=args.base)
    except Exception as exc:
        text = str(exc)
        if "private read blocked fail-closed" in text:
            print(f"[BLOCKED] {text}")
            print("[DONE] open_orders_fetch=False reason=PRIVATE_READ_PERMISSION_NOT_GRANTED")
            return 0

        print_http_error(exc)
        print("[DONE] open_orders_fetch=False reason=BITVAVO_OR_NETWORK_ERROR")
        return 0

    summarize_open_orders(orders)

    if args.output == "table":
        print()
        print("--- open orders ---")
        print_open_orders(orders, limit=args.limit)

    print()
    print(
        "[DONE] "
        f"open_orders_fetch=True rows={len(orders)} "
        "db_writes=0 broker_writes=0 order_submission=0 position_mutation=0"
    )

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-open-orders", action="store_true")
    parser.add_argument("--market", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
