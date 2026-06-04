from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.execution.bitvavo_client import BitvavoClient
from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerBalanceRow,
    BrokerOrderRow,
    LadderOrderRow,
    build_all_sections,
    collect_unpriced_markets,
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
DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"

REPORT_NAME = "run_manual_short_trader_profit_plan_v1"
REPORT_VERSION = "0.1"


@dataclass(frozen=True)
class OpenOrderInputLoadResult:
    orders: list[BrokerOrderRow]
    balances: list[BrokerBalanceRow]
    source_name: str
    source_missing: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the Synth v2 Profit Plan with manual planning states. "
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
        "--account-code",
        default=DEFAULT_ACCOUNT_CODE,
        help="Trading account code for DB-backed read-only open-order snapshots.",
    )
    parser.add_argument(
        "--venue",
        default=DEFAULT_VENUE,
        help="Venue for DB-backed read-only open-order snapshots.",
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


def fetch_broker_snapshot(
    client: BitvavoClient,
) -> tuple[list[BrokerOrderRow], list[BrokerBalanceRow]]:
    raw_orders: list[dict[str, Any]] = client.get_open_orders()
    raw_balances: list[dict[str, Any]] = client.get_balance()
    orders = [normalize_broker_order(r) for r in raw_orders]
    balances = [normalize_broker_balance(r) for r in raw_balances]
    return orders, balances


def _resolve_trading_account_id(
    conn: Any,
    *,
    account_code: str,
    venue: str,
) -> int | None:
    sql = """
    SELECT trading_account_id
    FROM trading_account
    WHERE account_code = %s
      AND venue = %s
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()
    if not row:
        return None
    return int(row["trading_account_id"])


def _fetch_latest_open_order_snapshot_ts(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> datetime | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM account_open_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue))
        row = cur.fetchone()
    return None if not row else row.get("latest_snapshot_ts_utc")


def _dt_to_ms(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp() * 1000)


def fetch_open_orders_from_snapshot(
    *,
    account_code: str,
    venue: str,
) -> OpenOrderInputLoadResult:
    try:
        conn = get_connection()
    except Exception:
        return OpenOrderInputLoadResult([], [], "account_open_order_snapshot", True)

    try:
        trading_account_id = _resolve_trading_account_id(
            conn,
            account_code=account_code,
            venue=venue,
        )
        if trading_account_id is None:
            return OpenOrderInputLoadResult([], [], "account_open_order_snapshot", True)

        latest_snapshot_ts = _fetch_latest_open_order_snapshot_ts(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
        )
        if latest_snapshot_ts is None:
            return OpenOrderInputLoadResult([], [], "account_open_order_snapshot", False)

        sql = """
        SELECT
            market,
            broker_order_id,
            side,
            order_type,
            limit_price,
            quantity,
            filled_quantity,
            remaining_quantity,
            broker_status,
            created_ts
        FROM account_open_order_snapshot
        WHERE trading_account_id = %s
          AND venue = %s
          AND snapshot_ts_utc = %s
        ORDER BY market, side, limit_price
        """
        with conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue, latest_snapshot_ts))
            rows = list(cur.fetchall())

        orders = [
            BrokerOrderRow(
                order_id=str(row.get("broker_order_id") or ""),
                market=str(row.get("market") or ""),
                side=str(row.get("side") or "").lower(),
                order_type=str(row.get("order_type") or "limit").lower(),
                limit_price=Decimal(str(row.get("limit_price") or "0")),
                amount=Decimal(str(row.get("quantity") or "0")),
                filled_amount=Decimal(str(row.get("filled_quantity") or "0")),
                remaining_amount=Decimal(str(row.get("remaining_quantity") or "0")),
                status=str(row.get("broker_status") or ""),
                created_at_ms=_dt_to_ms(row.get("created_ts")),
            )
            for row in rows
        ]
        return OpenOrderInputLoadResult(orders, [], "account_open_order_snapshot", False)
    except Exception:
        return OpenOrderInputLoadResult([], [], "account_open_order_snapshot", True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_open_order_inputs(
    *,
    client: BitvavoClient,
    account_code: str,
    venue: str,
    allow_live_broker: bool,
) -> OpenOrderInputLoadResult:
    snapshot_result = fetch_open_orders_from_snapshot(
        account_code=account_code,
        venue=venue,
    )
    if not snapshot_result.source_missing:
        return snapshot_result

    if not allow_live_broker:
        return snapshot_result

    orders, balances = fetch_broker_snapshot(client)
    return OpenOrderInputLoadResult(
        orders=orders,
        balances=balances,
        source_name="live_broker_private_read",
        source_missing=False,
    )


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
            f" primary_state={card.primary_state}"
            f" [{rel_flag}]"
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

    extra_markets = collect_unpriced_markets(orders, prices)
    if extra_markets:
        prices = {**prices, **fetch_ticker_prices(client, extra_markets)}

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
