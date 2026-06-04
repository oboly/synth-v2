from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.execution.bitvavo_client import BitvavoClient
from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerBalanceRow,
    BrokerOrderRow,
    LadderSymbolSection,
    build_all_sections,
    build_json_snapshot,
    collect_unpriced_markets,
    fmt_price,
    normalize_broker_balance,
    normalize_broker_order,
    render_full_html,
)


DEFAULT_OUTPUT_HTML = "/tmp/manual_short_trader_dashboard_v1.html"
DEFAULT_FIB_MAP_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")

REPORT_NAME = "run_manual_short_trader_dashboard_v1"
REPORT_VERSION = "0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the Synth v2 Open Orders Monitor. "
            "Read-only snapshot only. No broker writes, no order submission."
        )
    )
    parser.add_argument(
        "--markets",
        nargs="+",
        default=["WLD-EUR", "ONDO-EUR"],
        metavar="MARKET",
        help="Bitvavo market codes to include (default: WLD-EUR ONDO-EUR)",
    )
    parser.add_argument(
        "--output-html",
        default=DEFAULT_OUTPUT_HTML,
        help="Output HTML path",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        help="Optional: also write JSON snapshot artifact",
    )
    parser.add_argument(
        "--fib-map-rows",
        default=str(DEFAULT_FIB_MAP_ROWS),
        help="Optional: path to fibo_target_map_rows_v1.csv for merged fib context",
    )
    parser.add_argument(
        "--live-broker",
        action="store_true",
        default=False,
        help=(
            "Enable broker private read calls (get_open_orders, get_balance). "
            "Requires SYNTH_BROKER_PRIVATE_READ_PERMISSION env gate to be set."
        ),
    )
    parser.add_argument(
        "--output",
        choices=("summary", "none"),
        default="summary",
    )
    return parser.parse_args()


def load_fib_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows_by_symbol: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol:
                rows_by_symbol[symbol] = {f"fib_map_{k}": v for k, v in row.items()}
    return rows_by_symbol


def fetch_ticker_prices(
    client: BitvavoClient,
    markets: list[str],
) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for market in markets:
        try:
            prices[market] = client.get_ticker_price(market)
        except Exception as exc:
            print(f"[warn] ticker price fetch failed for {market}: {exc}", file=sys.stderr)
    return prices


def fetch_broker_snapshot(
    client: BitvavoClient,
) -> tuple[list[BrokerOrderRow], list[BrokerBalanceRow]]:
    raw_orders: list[dict[str, Any]] = client.get_open_orders()
    raw_balances: list[dict[str, Any]] = client.get_balance()
    orders = [normalize_broker_order(r) for r in raw_orders]
    balances = [normalize_broker_balance(r) for r in raw_balances]
    return orders, balances


def print_summary(
    sections: list[LadderSymbolSection],
    *,
    output_html: Path,
    output_json: Path | None,
    broker_mode: str,
) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print(f"output_html={output_html}")
    if output_json:
        print(f"output_json={output_json}")
    print(f"broker_mode={broker_mode}")
    print("broker_writes=0")
    print("order_submission=0")
    print("executor=none")
    print("account_awareness=read_only_snapshot")
    for section in sections:
        print(
            f"{section.symbol}: price={fmt_price(section.current_price)}"
            f" buy={len(section.buy_orders)}"
            f" sell={len(section.sell_orders)}"
            f" labels={','.join(section.section_labels)}"
        )
    if not sections:
        print("sections=0 (no open orders or offline mode without --live-broker)")


def main() -> int:
    args = parse_args()

    client = BitvavoClient()
    prices = fetch_ticker_prices(client, args.markets)

    orders: list[BrokerOrderRow] = []
    balances: list[BrokerBalanceRow] = []
    broker_mode = "offline"

    if args.live_broker:
        try:
            orders, balances = fetch_broker_snapshot(client)
            broker_mode = "live_read_only"
        except PermissionError as exc:
            print(f"[error] Broker private read blocked: {exc}", file=sys.stderr)
            print(
                "[info] Set SYNTH_BROKER_PRIVATE_READ_PERMISSION="
                "I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA to enable.",
                file=sys.stderr,
            )
            return 1
        except Exception as exc:
            print(f"[error] Broker snapshot failed: {exc}", file=sys.stderr)
            return 1

    # Fetch public ticker prices for any markets discovered from open orders
    # that were not included in the initial --markets list.
    extra = collect_unpriced_markets(orders, prices)
    if extra:
        prices = {**prices, **fetch_ticker_prices(client, extra)}

    fib_rows = load_fib_rows(Path(args.fib_map_rows))
    sections = build_all_sections(orders, balances, prices, fib_rows=fib_rows)

    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_full_html(sections, broker_mode=broker_mode),
        encoding="utf-8",
    )

    output_json: Path | None = None
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(
                build_json_snapshot(sections),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if args.output == "summary":
        print_summary(
            sections,
            output_html=output_html,
            output_json=output_json,
            broker_mode=broker_mode,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
