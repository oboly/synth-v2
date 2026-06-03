from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
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
from src.reporting.manual_short_trader_profit_plan_v1 import (
    FibExtContext,
    ProfitPlanCard,
    ReentryContext,
    build_json_snapshot,
    build_profit_plan_card,
    render_full_html,
)
from src.research.htf_fib_extension_confluence_v1 import (
    HtfSwingInput,
    build_htf_extension_map,
)
from src.research.htf_fib_reentry_ladder_v1 import (
    HtfReentryInput,
    build_fib_retrace_ladder,
)


DEFAULT_OUTPUT_HTML = "/tmp/manual_short_trader_profit_plan_v1.html"
DEFAULT_MONITOR_HTML = "/tmp/manual_short_trader_dashboard_v1.html"
DEFAULT_OUTPUT_JSON: str | None = None

REPORT_NAME = "run_manual_short_trader_profit_plan_v1"
REPORT_VERSION = "0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the Synth v2 short-trader profit-plan dashboard. "
            "Read-only snapshot. No broker writes, no order submission."
        )
    )
    parser.add_argument(
        "--markets",
        nargs="+",
        default=["WLD-EUR", "ONDO-EUR"],
        metavar="MARKET",
    )
    parser.add_argument(
        "--output-html",
        default=DEFAULT_OUTPUT_HTML,
    )
    parser.add_argument(
        "--output-json",
        default=DEFAULT_OUTPUT_JSON,
        metavar="PATH",
    )
    parser.add_argument(
        "--monitor-html",
        default=DEFAULT_MONITOR_HTML,
        metavar="PATH",
        help="Path to the Open Orders Monitor HTML (linked from each card).",
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
        "--swing-anchors",
        nargs="+",
        default=[],
        metavar="SYMBOL:LOW:HIGH",
        help=(
            "HTF swing anchors for fib extension context, e.g. WLD:0.30:0.65. "
            "Can be repeated for multiple symbols."
        ),
    )
    parser.add_argument(
        "--recent-lows",
        nargs="+",
        default=[],
        metavar="SYMBOL:PRICE",
        help="Recent low prices for re-entry ladder context, e.g. FET:0.209.",
    )
    parser.add_argument(
        "--output",
        choices=("summary", "none"),
        default="summary",
    )
    return parser.parse_args()


def _parse_kv_list(items: list[str], n_parts: int) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        parts = item.split(":", n_parts - 1)
        if len(parts) == n_parts:
            result[parts[0].upper()] = parts[1:]
    return result


def fetch_ticker_prices(
    client: BitvavoClient,
    markets: list[str],
) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for market in markets:
        try:
            prices[market] = client.get_ticker_price(market)
        except Exception as exc:
            print(f"[warn] ticker fetch failed for {market}: {exc}", file=sys.stderr)
    return prices


def build_fib_ext_contexts(
    swing_anchors: dict[str, list[str]],
    prices: dict[str, Decimal],
    markets: list[str],
) -> dict[str, FibExtContext]:
    contexts: dict[str, FibExtContext] = {}
    for market in markets:
        symbol = market.split("-")[0].upper()
        anchor = swing_anchors.get(symbol)
        if anchor is None:
            continue
        try:
            sl = Decimal(anchor[0])
            sh = Decimal(anchor[1])
        except Exception:
            continue
        current = prices.get(market)
        if current is None:
            continue
        try:
            ext_map = build_htf_extension_map(
                HtfSwingInput(
                    symbol=symbol,
                    interval_code="1d",
                    swing_low=sl,
                    swing_high=sh,
                    current_price=current,
                )
            )
        except Exception as exc:
            print(f"[warn] fib ext map failed for {symbol}: {exc}", file=sys.stderr)
            continue
        target_by_label = {t.label: t.price for t in ext_map.targets}
        contexts[symbol] = FibExtContext(
            ext_1_272=target_by_label.get("ext_1_272", sh),
            ext_1_618=target_by_label.get("ext_1_618", sh),
            ext_2_000=target_by_label.get("ext_2_000", sh),
            breakout_gate=ext_map.breakout_gate,
            price_band=ext_map.price_band,
            ext_1_272_touched_and_rejected=ext_map.ext_1_272_touched_and_rejected,
            retesting_breakout_gate=ext_map.retesting_breakout_gate,
        )
    return contexts


def build_reentry_contexts(
    swing_anchors: dict[str, list[str]],
    recent_lows: dict[str, list[str]],
    prices: dict[str, Decimal],
    markets: list[str],
) -> dict[str, ReentryContext]:
    contexts: dict[str, ReentryContext] = {}
    for market in markets:
        symbol = market.split("-")[0].upper()
        anchor = swing_anchors.get(symbol)
        if anchor is None:
            continue
        try:
            sl = Decimal(anchor[0])
            sh = Decimal(anchor[1])
        except Exception:
            continue
        current = prices.get(market)
        if current is None:
            continue
        recent_low_parts = recent_lows.get(symbol)
        recent_low: Decimal | None = None
        if recent_low_parts:
            try:
                recent_low = Decimal(recent_low_parts[0])
            except Exception:
                pass
        try:
            ladder = build_fib_retrace_ladder(
                HtfReentryInput(
                    symbol=symbol,
                    interval_code="1d",
                    swing_low=sl,
                    swing_high=sh,
                    current_price=current,
                    recent_low_price=recent_low,
                )
            )
        except Exception as exc:
            print(f"[warn] reentry ladder failed for {symbol}: {exc}", file=sys.stderr)
            continue
        level_by_label = {row.label: row.price for row in ladder.levels}
        contexts[symbol] = ReentryContext(
            r382_price=level_by_label.get("retrace_0_382", sh),
            r500_price=level_by_label.get("retrace_0_500", sh),
            r618_price=level_by_label.get("retrace_0_618", sh),
            r786_price=level_by_label.get("retrace_0_786", sl),
            deepest_touched_label=ladder.deepest_touched_label,
            missed_main_rebuy_by_pct=ladder.missed_main_rebuy_by_pct,
        )
    return contexts


def build_cards(
    markets: list[str],
    prices: dict[str, Decimal],
    fib_ext_by_symbol: dict[str, FibExtContext],
    reentry_by_symbol: dict[str, ReentryContext],
    orders_by_symbol: dict[str, tuple[tuple[LadderOrderRow, ...], tuple[LadderOrderRow, ...]]],
) -> list[ProfitPlanCard]:
    cards: list[ProfitPlanCard] = []
    for market in markets:
        symbol = market.split("-")[0].upper()
        current = prices.get(market)
        buy_orders, sell_orders = orders_by_symbol.get(symbol, ((), ()))
        card = build_profit_plan_card(
            symbol=symbol,
            market=market,
            current_price=current,
            fib_ext=fib_ext_by_symbol.get(symbol),
            reentry=reentry_by_symbol.get(symbol),
            buy_orders=buy_orders,
            sell_orders=sell_orders,
        )
        cards.append(card)
    return cards


def print_summary(cards: list[ProfitPlanCard]) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print("broker_writes=0")
    print("order_submission=0")
    print("executor=none")
    relevant = [c for c in cards if c.is_relevant]
    print(f"relevant={len(relevant)}/{len(cards)}")
    for card in cards:
        rel_flag = "RELEVANT" if card.is_relevant else "filtered"
        print(
            f"{card.symbol}: scenario={card.scenario_type}"
            f" action={card.action_label}"
            f" [{rel_flag}]"
        )


def main() -> int:
    args = parse_args()

    client = BitvavoClient()
    prices = fetch_ticker_prices(client, args.markets)

    orders: list[BrokerOrderRow] = []
    broker_mode = "offline"
    if args.live_broker:
        try:
            raw_orders: list[dict[str, Any]] = client.get_open_orders()
            raw_balances: list[dict[str, Any]] = client.get_balance()
            orders = [normalize_broker_order(r) for r in raw_orders]
            balances = [normalize_broker_balance(r) for r in raw_balances]
            # fetch prices for any extra markets from open orders
            extra_markets = sorted(
                {o.market for o in orders} - set(prices.keys())
            )
            if extra_markets:
                prices = {**prices, **fetch_ticker_prices(client, extra_markets)}
            broker_mode = "live_read_only"
        except PermissionError as exc:
            print(f"[error] Broker private read blocked: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[error] Broker snapshot failed: {exc}", file=sys.stderr)
            return 1
    else:
        balances = []

    swing_anchors = _parse_kv_list(args.swing_anchors, 3)
    recent_lows = _parse_kv_list(args.recent_lows, 2)

    fib_ext_by_symbol = build_fib_ext_contexts(swing_anchors, prices, args.markets)
    reentry_by_symbol = build_reentry_contexts(swing_anchors, recent_lows, prices, args.markets)

    # Build order lookup from existing dashboard sections
    sections = build_all_sections(orders, balances, prices)
    orders_by_symbol: dict[str, tuple[tuple[LadderOrderRow, ...], tuple[LadderOrderRow, ...]]] = {
        s.symbol: (s.buy_orders, s.sell_orders) for s in sections
    }

    monitor_link = args.monitor_html if Path(args.monitor_html).exists() else None

    cards = build_cards(
        args.markets,
        prices,
        fib_ext_by_symbol,
        reentry_by_symbol,
        orders_by_symbol,
    )

    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_full_html(cards, broker_mode=broker_mode, monitor_link=monitor_link),
        encoding="utf-8",
    )

    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(
                build_json_snapshot(cards, broker_mode=broker_mode),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if args.output == "summary":
        print_summary(cards)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
