from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_VENUE,
    classify_market_prices_by_market,
    default_page_paths,
    load_account_scoped_short_dashboard_context,
    validate_profile_slug,
)
from src.reporting.account_dashboard_profile_access_v1 import resolve_dashboard_profile_access
from src.reporting.manual_short_trader_dashboard_v1 import (
    LadderSymbolSection,
    build_all_sections,
    build_json_snapshot,
    fmt_price,
    render_full_html,
)


DEFAULT_FIB_MAP_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")
REPORT_NAME = "run_manual_short_trader_dashboard_v1"
REPORT_VERSION = "0.2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the Synth v2 Open Orders Monitor for exactly one account profile. "
            "Read-only DB snapshot only. No broker reads, no broker writes, no order submission."
        )
    )
    parser.add_argument("--account-profile", required=True, metavar="PROFILE")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Synth web root. Outputs are written under accounts/<profile>/open-orders-monitor.html/json.",
    )
    parser.add_argument(
        "--output-html",
        default=None,
        metavar="PATH",
        help="Optional explicit HTML output path. Defaults to accounts/<profile>/open-orders-monitor.html under output-root.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        help="Optional explicit JSON output path. Defaults to accounts/<profile>/open-orders-monitor.json under output-root.",
    )
    parser.add_argument(
        "--fib-map-rows",
        default=str(DEFAULT_FIB_MAP_ROWS),
        help="Optional: path to fibo_target_map_rows_v1.csv for merged fib context.",
    )
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
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


def _build_sections(
    *,
    context,
    fib_rows: dict[str, dict[str, Any]],
) -> list[LadderSymbolSection]:
    price_display_by_market = classify_market_prices_by_market(context=context)
    prices = {
        market: display.safe_price
        for market, display in price_display_by_market.items()
        if display.safe_price is not None
    }
    return build_all_sections(
        list(context.orders),
        list(context.balances),
        prices,
        fib_rows=fib_rows,
        price_status_by_market={market: display.status for market, display in price_display_by_market.items()},
        price_age_min_by_market={market: display.age_min for market, display in price_display_by_market.items()},
    )


def print_summary(
    *,
    context,
    sections: list[LadderSymbolSection],
    output_html: Path,
    output_json: Path,
) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print(f"profile={context.profile}")
    print(f"account_code={context.account_code}")
    print(f"trading_account_id={context.trading_account_id}")
    print(f"venue={context.venue}")
    print(f"market_count={len(context.markets)}")
    print(f"open_order_count={len(context.orders)}")
    print(f"open_order_market_count={len(context.open_order_count_by_market)}")
    print(f"html_output={output_html}")
    print(f"json_output={output_json}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")
    for section in sections:
        print(
            f"{section.symbol}: price={fmt_price(section.current_price)}"
            f" buy={len(section.buy_orders)}"
            f" sell={len(section.sell_orders)}"
            f" labels={','.join(section.section_labels)}"
        )
    if not sections:
        print("sections=0 (no open orders found for this account)")


def main() -> int:
    args = parse_args()
    try:
        validate_profile_slug(args.account_profile)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    try:
        access = resolve_dashboard_profile_access(
            account_profile=args.account_profile,
            venue=args.venue,
        )
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    output_root = Path(args.output_root)
    default_html, default_json = default_page_paths(
        output_root=output_root,
        profile=args.account_profile,
        page_stem="open-orders-monitor",
    )
    output_html = Path(args.output_html) if args.output_html else default_html
    output_json = Path(args.output_json) if args.output_json else default_json

    try:
        context = load_account_scoped_short_dashboard_context(
            profile=args.account_profile,
            account_code=access.trading_account_stable_ref,
            venue=args.venue,
        )
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[error] account scope load failed: {exc}", file=sys.stderr)
        return 1

    fib_rows = load_fib_rows(Path(args.fib_map_rows))
    sections = _build_sections(context=context, fib_rows=fib_rows)

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_full_html(sections, broker_mode="db_snapshot"),
        encoding="utf-8",
    )
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
            context=context,
            sections=sections,
            output_html=output_html,
            output_json=output_json,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
