from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerOrderRow,
    LadderOrderRow,
    build_all_sections,
)
from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    classify_market_prices_by_market,
    load_account_scoped_short_dashboard_context,
)
from src.reporting.manual_short_trader_profit_plan_v1 import VISIBILITY_CANONICAL_NAVIGATION_REFERENCE
from src.reporting.run_manual_short_trader_profit_plan_v1 import (
    _parse_kv_list,
    build_cards,
    load_zone_contexts,
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
    zone_context_input_status: str
    has_target_exit_zone: bool
    has_reload_reentry_zone: bool
    has_invalidation_zone: bool
    has_fib_extension_context: bool
    has_reentry_ladder_context: bool
    has_stale_order_metadata: bool
    primary_missing_reason: str
    all_missing_reasons: tuple[str, ...]
    would_render_state: str
    visibility_class: str
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
            "Deprecated compatibility option; broker reads are not supported by this audit."
        ),
    )
    parser.add_argument(
        "--account-profile",
        default="audit",
        help="Profile label for the canonical account-scoped read-only context.",
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
        "--fib-map-rows",
        default="data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv",
        help="Optional: path to fibo_target_map_rows_v1.csv for read-only zone context.",
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
    zone_context_status_by_symbol: dict[str, str],
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
        zone_context_input_status = zone_context_status_by_symbol.get(symbol, "MISSING_ZONE_CONTEXT")

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
        if zone_context_input_status == "ZONE_SOURCE_MISSING":
            missing_reasons.append("ZONE_SOURCE_MISSING")
        elif zone_context_input_status == "ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING":
            missing_reasons.append("ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING")
        if not (has_target_exit_zone or has_reload_reentry_zone or has_invalidation_zone):
            missing_reasons.append("MISSING_ZONE_CONTEXT")
        if open_order_input_status == "OPEN_ORDER_SOURCE_MISSING":
            missing_reasons.append("OPEN_ORDER_SOURCE_MISSING")
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
                zone_context_input_status=zone_context_input_status,
                has_target_exit_zone=has_target_exit_zone,
                has_reload_reentry_zone=has_reload_reentry_zone,
                has_invalidation_zone=has_invalidation_zone,
                has_fib_extension_context=has_fib_extension_context,
                has_reentry_ladder_context=has_reentry_ladder_context,
                has_stale_order_metadata=has_stale_order_metadata,
                primary_missing_reason=primary_missing_reason,
                all_missing_reasons=tuple(missing_reasons),
                would_render_state=card.primary_state,
                visibility_class=card.visibility_class,
                # Issue #212: preserve the existing not-is_relevant meaning of
                # "filtered" for every other case, but explicitly carve out
                # canonical navigation-only cards -- they are discoverable in
                # the default rendered view and must never be reported as
                # filtered, even though card.is_relevant is False for them by
                # design (non-actionable, not non-visible).
                filtered_by_profit_plan=(
                    not card.is_relevant
                    and card.visibility_class != VISIBILITY_CANONICAL_NAVIGATION_REFERENCE
                ),
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
            f"zone_context_input_status={row.zone_context_input_status} "
            f"would_render_state={row.would_render_state} "
            f"visibility_class={row.visibility_class} "
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

    if args.live_broker:
        print("[error] --live-broker is not supported; use DB snapshots only", file=sys.stderr)
        return 1

    try:
        context = load_account_scoped_short_dashboard_context(
            profile=args.account_profile,
            account_code=args.account_code,
            venue=args.venue,
        )
    except Exception as exc:
        print(f"[error] account-scoped input load failed: {exc}", file=sys.stderr)
        return 1

    markets = [market.upper() for market in args.markets]
    price_display_by_market = classify_market_prices_by_market(context=context)
    prices = {
        market: display.safe_price
        for market, display in price_display_by_market.items()
        if display.safe_price is not None
    }
    orders = list(context.orders)
    balances = list(context.balances)
    broker_mode = "db_snapshot"
    open_order_source_missing = context.latest_order_snapshot_ts_utc is None

    swing_anchors = _parse_kv_list(args.swing_anchors, 3)
    recent_lows = _parse_kv_list(args.recent_lows, 2)
    zone_contexts = load_zone_contexts(
        markets=markets,
        prices=prices,
        swing_anchors=swing_anchors,
        recent_lows=recent_lows,
        native_short_rows_path=Path("data/research/native_short_fib_context_v1/native_short_fib_context_rows_v1.csv"),
        fib_map_rows_path=Path(args.fib_map_rows),
    )
    fib_ext_by_symbol = zone_contexts.fib_ext_by_symbol
    reentry_by_symbol = zone_contexts.reentry_by_symbol

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
        markets,
        prices,
        {market: display.status for market, display in price_display_by_market.items()},
        {market: display.age_min for market, display in price_display_by_market.items()},
        zone_contexts.input_status_by_symbol,
        zone_contexts.coverage_status_by_symbol,
        zone_contexts.display_state_by_symbol,
        fib_ext_by_symbol,
        reentry_by_symbol,
        {},
        orders_by_symbol,
        prior_map_meta_by_symbol=zone_contexts.prior_map_meta_by_symbol,
        inclusion_reasons_by_market=context.market_inclusion_reasons_by_market,
        account_plan_policy_by_market=context.account_plan_policy_by_market,
        evidence_by_symbol=zone_contexts.evidence_by_symbol,
        price_ts_by_market={
            market: (
                context.market_price_by_symbol.get(market.split("-", 1)[0]).source_ts_utc
                if context.market_price_by_symbol.get(market.split("-", 1)[0]) is not None
                else None
            )
            for market in markets
        },
        order_snapshot_ts_utc=context.latest_order_snapshot_ts_utc,
    )
    rows = build_profit_plan_input_audit_rows(
        markets=markets,
        prices=prices,
        cards=cards,
        fib_ext_by_symbol=fib_ext_by_symbol,
        reentry_by_symbol=reentry_by_symbol,
        orders_by_symbol=orders_by_symbol,
        raw_orders_by_symbol=raw_orders_by_symbol,
        open_order_source_missing=open_order_source_missing,
        zone_context_status_by_symbol=zone_contexts.input_status_by_symbol,
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
