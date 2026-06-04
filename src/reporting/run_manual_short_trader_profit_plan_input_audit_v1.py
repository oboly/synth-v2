from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.execution.bitvavo_client import BitvavoClient
from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerOrderRow,
    LadderOrderRow,
    build_all_sections,
    normalize_broker_balance,
    normalize_broker_order,
)
from src.reporting.run_manual_short_trader_profit_plan_v1 import (
    _parse_kv_list,
    build_cards,
    build_fib_ext_contexts,
    build_reentry_contexts,
    fetch_ticker_prices,
    load_open_order_inputs,
)


REPORT_NAME = "run_manual_short_trader_profit_plan_input_audit_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_DIR = Path("/tmp/manual_short_trader_profit_plan_input_audit_v1")


@dataclass(frozen=True)
class ProfitPlanInputAuditRow:
    symbol: str
    market: str
    has_current_price: bool
    has_existing_open_orders: bool
    open_order_count: int
    open_order_input_status: str
    has_target_exit_zone: bool
    has_reload_reentry_zone: bool
    has_invalidation_zone: bool
    has_fib_extension_context: bool
    has_reentry_ladder_context: bool
    has_stale_order_metadata: bool
    primary_missing_reason: str
    all_missing_reasons: tuple[str, ...]
    would_render_state: str
    filtered_by_profit_plan: bool
    broker_writes: int
    order_submission: int
    executor: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Profit Plan input coverage using the same read-only inputs as the "
            "Profit Plan runner. No broker writes, no order submission."
        )
    )
    parser.add_argument(
        "--markets",
        nargs="+",
        default=["WLD-EUR", "ONDO-EUR"],
        metavar="MARKET",
    )
    parser.add_argument(
        "--live-broker",
        action="store_true",
        default=False,
        help=(
            "Enable broker private read calls (get_open_orders, get_balance). "
            "Requires SYNTH_BROKER_PRIVATE_READ_PERMISSION env gate."
        ),
    )
    parser.add_argument(
        "--account-code",
        default="bitvavo_synth_read",
        help="Trading account code for DB-backed read-only open-order snapshots.",
    )
    parser.add_argument(
        "--venue",
        default="bitvavo",
        help="Venue for DB-backed read-only open-order snapshots.",
    )
    parser.add_argument(
        "--swing-anchors",
        nargs="+",
        default=[],
        metavar="SYMBOL:LOW:HIGH",
    )
    parser.add_argument(
        "--recent-lows",
        nargs="+",
        default=[],
        metavar="SYMBOL:PRICE",
    )
    parser.add_argument(
        "--output",
        choices=("summary", "json", "none"),
        default="summary",
    )
    parser.add_argument(
        "--write-files",
        action="store_true",
        default=False,
        help="Write summary/json files to --output-dir. Use /tmp or non-committed paths only.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        metavar="PATH",
    )
    return parser.parse_args()


def build_profit_plan_input_audit_rows(
    *,
    markets: list[str],
    prices: dict[str, Any],
    cards: list[Any],
    fib_ext_by_symbol: dict[str, Any],
    reentry_by_symbol: dict[str, Any],
    orders_by_symbol: dict[str, tuple[tuple[LadderOrderRow, ...], tuple[LadderOrderRow, ...]]],
    raw_orders_by_symbol: dict[str, tuple[BrokerOrderRow, ...]],
    open_order_source_missing: bool,
) -> list[ProfitPlanInputAuditRow]:
    card_by_market = {card.market: card for card in cards}
    rows: list[ProfitPlanInputAuditRow] = []

    for market in markets:
        symbol = market.split("-")[0].upper()
        card = card_by_market[market]
        raw_orders = raw_orders_by_symbol.get(symbol, ())
        buy_orders, sell_orders = orders_by_symbol.get(symbol, ((), ()))
        open_order_count = len(buy_orders) + len(sell_orders)
        if open_order_source_missing:
            open_order_input_status = "OPEN_ORDER_SOURCE_MISSING"
        elif open_order_count > 0:
            open_order_input_status = "HAS_OPEN_ORDERS"
        else:
            open_order_input_status = "NO_OPEN_ORDERS"

        has_current_price = market in prices and prices[market] is not None
        has_existing_open_orders = open_order_input_status == "HAS_OPEN_ORDERS"
        has_target_exit_zone = bool(card.target_exit_zone)
        has_reload_reentry_zone = bool(card.reload_reentry_zone)
        has_invalidation_zone = card.invalidation_risk_zone is not None
        has_fib_extension_context = symbol in fib_ext_by_symbol
        has_reentry_ladder_context = symbol in reentry_by_symbol
        has_stale_order_metadata = any(order.created_at_ms is not None for order in raw_orders)

        missing_reasons: list[str] = []
        if not has_current_price:
            missing_reasons.append("MISSING_CURRENT_PRICE")
        if not (has_target_exit_zone or has_reload_reentry_zone or has_invalidation_zone):
            missing_reasons.append("MISSING_ZONE_CONTEXT")
        if open_order_input_status == "OPEN_ORDER_SOURCE_MISSING":
            missing_reasons.append("OPEN_ORDER_SOURCE_MISSING")
        elif open_order_input_status == "NO_OPEN_ORDERS":
            missing_reasons.append("NO_OPEN_ORDERS")
        if not has_stale_order_metadata:
            missing_reasons.append("NO_STALE_ORDER_METADATA")

        primary_missing_reason = missing_reasons[0] if missing_reasons else "READY_FOR_PROFIT_PLAN"

        rows.append(
            ProfitPlanInputAuditRow(
                symbol=symbol,
                market=market,
                has_current_price=has_current_price,
                has_existing_open_orders=has_existing_open_orders,
                open_order_count=open_order_count,
                open_order_input_status=open_order_input_status,
                has_target_exit_zone=has_target_exit_zone,
                has_reload_reentry_zone=has_reload_reentry_zone,
                has_invalidation_zone=has_invalidation_zone,
                has_fib_extension_context=has_fib_extension_context,
                has_reentry_ladder_context=has_reentry_ladder_context,
                has_stale_order_metadata=has_stale_order_metadata,
                primary_missing_reason=primary_missing_reason,
                all_missing_reasons=tuple(missing_reasons),
                would_render_state=card.primary_state,
                filtered_by_profit_plan=not card.is_relevant,
                broker_writes=0,
                order_submission=0,
                executor="none",
            )
        )

    return rows


def build_json_snapshot(
    rows: list[ProfitPlanInputAuditRow],
    *,
    broker_mode: str,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "broker_mode": broker_mode,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
        "markets": [asdict(row) for row in rows],
    }


def format_summary(rows: list[ProfitPlanInputAuditRow], *, broker_mode: str) -> str:
    ready_count = sum(1 for row in rows if row.primary_missing_reason == "READY_FOR_PROFIT_PLAN")
    lines = [
        f"report={REPORT_NAME}",
        f"version={REPORT_VERSION}",
        f"broker_mode={broker_mode}",
        "broker_writes=0",
        "order_submission=0",
        "executor=none",
        f"ready={ready_count}/{len(rows)}",
    ]
    for row in rows:
        reasons = ",".join(row.all_missing_reasons) if row.all_missing_reasons else "READY_FOR_PROFIT_PLAN"
        status = "filtered" if row.filtered_by_profit_plan else "visible"
        lines.append(
            f"{row.symbol}: open_order_input_status={row.open_order_input_status} "
            f"would_render_state={row.would_render_state} "
            f"primary_missing_reason={row.primary_missing_reason} "
            f"missing={reasons} [{status}]"
        )
    return "\n".join(lines)


def write_outputs(
    *,
    output_dir: Path,
    summary_text: str,
    snapshot: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manual_short_trader_profit_plan_input_audit_v1.summary.txt").write_text(
        summary_text + "\n",
        encoding="utf-8",
    )
    (output_dir / "manual_short_trader_profit_plan_input_audit_v1.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()

    client = BitvavoClient()
    prices = fetch_ticker_prices(client, args.markets)

    try:
        open_order_inputs = load_open_order_inputs(
            client=client,
            account_code=args.account_code,
            venue=args.venue,
            allow_live_broker=args.live_broker,
        )
    except PermissionError as exc:
        print(f"[error] Broker private read blocked: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[error] Open-order input load failed: {exc}", file=sys.stderr)
        return 1

    orders = open_order_inputs.orders
    balances = open_order_inputs.balances
    broker_mode = "live_read_only" if open_order_inputs.source_name == "live_broker_private_read" else "offline"
    extra_markets = sorted({order.market for order in orders} - set(prices.keys()))
    if extra_markets:
        prices = {**prices, **fetch_ticker_prices(client, extra_markets)}

    swing_anchors = _parse_kv_list(args.swing_anchors, 3)
    recent_lows = _parse_kv_list(args.recent_lows, 2)
    fib_ext_by_symbol = build_fib_ext_contexts(swing_anchors, prices, args.markets)
    reentry_by_symbol = build_reentry_contexts(swing_anchors, recent_lows, prices, args.markets)

    sections = build_all_sections(orders, balances, prices)
    orders_by_symbol: dict[str, tuple[tuple[LadderOrderRow, ...], tuple[LadderOrderRow, ...]]] = {
        section.symbol: (section.buy_orders, section.sell_orders)
        for section in sections
    }
    raw_orders_by_symbol: dict[str, tuple[BrokerOrderRow, ...]] = {}
    for order in orders:
        symbol = order.market.split("-")[0].upper()
        raw_orders_by_symbol.setdefault(symbol, tuple())
        raw_orders_by_symbol[symbol] = raw_orders_by_symbol[symbol] + (order,)

    cards = build_cards(
        args.markets,
        prices,
        fib_ext_by_symbol,
        reentry_by_symbol,
        orders_by_symbol,
    )
    rows = build_profit_plan_input_audit_rows(
        markets=args.markets,
        prices=prices,
        cards=cards,
        fib_ext_by_symbol=fib_ext_by_symbol,
        reentry_by_symbol=reentry_by_symbol,
        orders_by_symbol=orders_by_symbol,
        raw_orders_by_symbol=raw_orders_by_symbol,
        open_order_source_missing=open_order_inputs.source_missing,
    )

    snapshot = build_json_snapshot(rows, broker_mode=broker_mode)
    summary_text = format_summary(rows, broker_mode=broker_mode)

    if args.output == "summary":
        print(summary_text)
    elif args.output == "json":
        print(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False))

    if args.write_files:
        write_outputs(
            output_dir=Path(args.output_dir),
            summary_text=summary_text,
            snapshot=snapshot,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
