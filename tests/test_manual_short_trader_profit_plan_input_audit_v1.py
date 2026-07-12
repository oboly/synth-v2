from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

from src.reporting.manual_short_trader_profit_plan_v1 import (
    FibExtContext,
    ReentryContext,
    build_profit_plan_card,
)
from src.reporting.run_manual_short_trader_profit_plan_input_audit_v1 import (
    ProfitPlanInputAuditRow,
    build_json_snapshot,
    build_profit_plan_input_audit_rows,
    format_summary,
)


class _FakeOrder:
    def __init__(self, price: str, side: str = "buy") -> None:
        self.limit_price = Decimal(price)
        self.side = side


class _RawOrder:
    def __init__(self, market: str, created_at_ms: int | None = None) -> None:
        self.market = market
        self.created_at_ms = created_at_ms


def _fib_ext() -> FibExtContext:
    return FibExtContext(
        local_reaction_price=Decimal("0.40"),
        anchor_end_ts_utc=None,
        ext_1_272=Decimal("0.49"),
        ext_1_618=Decimal("0.65"),
        ext_2_000=Decimal("0.80"),
        breakout_gate=Decimal("0.38"),
        price_band="BETWEEN_1272_1618",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )


def _reentry() -> ReentryContext:
    return ReentryContext(
        r382_price=Decimal("0.2142"),
        r500_price=Decimal("0.2050"),
        r618_price=Decimal("0.1958"),
        r786_price=Decimal("0.1827"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )


def _build_rows_for_card(
    *,
    market: str = "WLD-EUR",
    current_price: str | None = "0.48",
    fib_ext: FibExtContext | None = None,
    reentry: ReentryContext | None = None,
    buy_orders: tuple[_FakeOrder, ...] = (),
    sell_orders: tuple[_FakeOrder, ...] = (),
    include_price: bool = True,
    include_raw_order_metadata: bool = False,
    zone_context_input_status: str = "HAS_ZONE_CONTEXT",
    open_order_source_missing: bool = False,
) -> list[ProfitPlanInputAuditRow]:
    card = build_profit_plan_card(
        symbol=market.split("-")[0],
        market=market,
        current_price=Decimal(current_price) if current_price is not None else None,
        short_context_input_status=zone_context_input_status,
        short_context_coverage_status=(
            "NATIVE_SHORT_CONTEXT_AVAILABLE"
            if zone_context_input_status == "HAS_ZONE_CONTEXT"
            else "CONTEXT_INVALID_OR_STALE"
        ),
        short_context_display_state=(
            "HAS_NATIVE_SHORT_FIB_CONTEXT"
            if zone_context_input_status == "HAS_ZONE_CONTEXT"
            else "NO_NATIVE_SHORT_FIB_CONTEXT"
        ),
        fib_ext=fib_ext,
        reentry=reentry,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
    )
    prices = {market: Decimal(current_price)} if include_price and current_price is not None else {}
    orders_by_symbol = {
        market.split("-")[0]: (buy_orders, sell_orders),
    }
    raw_orders_by_symbol = {
        market.split("-")[0]: ((_RawOrder(market, 1234),) if include_raw_order_metadata else ())
    }
    return build_profit_plan_input_audit_rows(
        markets=[market],
        prices=prices,
        cards=[card],
        fib_ext_by_symbol={market.split("-")[0]: fib_ext} if fib_ext is not None else {},
        reentry_by_symbol={market.split("-")[0]: reentry} if reentry is not None else {},
        orders_by_symbol=orders_by_symbol,
        raw_orders_by_symbol=raw_orders_by_symbol,
        open_order_source_missing=open_order_source_missing,
        zone_context_status_by_symbol={market.split("-")[0]: zone_context_input_status},
    )


def test_missing_price_reports_missing_current_price() -> None:
    row = _build_rows_for_card(fib_ext=_fib_ext(), include_price=False)[0]
    assert row.primary_missing_reason == "MISSING_CURRENT_PRICE"


def test_missing_zone_context_reports_missing_zone_context() -> None:
    row = _build_rows_for_card()[0]
    assert "MISSING_ZONE_CONTEXT" in row.all_missing_reasons
    assert row.primary_missing_reason == "MISSING_ZONE_CONTEXT"


def test_no_open_orders_reports_no_open_orders() -> None:
    row = _build_rows_for_card(fib_ext=_fib_ext())[0]
    assert row.open_order_input_status == "NO_OPEN_ORDERS"
    assert "NO_OPEN_ORDERS" not in row.all_missing_reasons
    assert row.primary_missing_reason == "NO_STALE_ORDER_METADATA"


def test_valid_zone_context_without_open_orders_can_still_render_visible_card() -> None:
    row = _build_rows_for_card(
        fib_ext=_fib_ext(),
        include_raw_order_metadata=True,
    )[0]
    assert row.open_order_input_status == "NO_OPEN_ORDERS"
    assert row.primary_missing_reason == "READY_FOR_PROFIT_PLAN"
    assert row.filtered_by_profit_plan is False


def test_open_order_source_missing_is_distinguished() -> None:
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.48"),
        fib_ext=_fib_ext(),
    )
    row = build_profit_plan_input_audit_rows(
        markets=["WLD-EUR"],
        prices={"WLD-EUR": Decimal("0.48")},
        cards=[card],
        fib_ext_by_symbol={"WLD": _fib_ext()},
        reentry_by_symbol={},
        orders_by_symbol={"WLD": ((), ())},
        raw_orders_by_symbol={"WLD": ()},
        open_order_source_missing=True,
        zone_context_status_by_symbol={"WLD": "HAS_ZONE_CONTEXT"},
    )[0]
    assert row.open_order_input_status == "OPEN_ORDER_SOURCE_MISSING"
    assert "OPEN_ORDER_SOURCE_MISSING" in row.all_missing_reasons


def test_valid_open_order_fixture_reports_has_open_orders() -> None:
    row = _build_rows_for_card(
        fib_ext=_fib_ext(),
        sell_orders=(_FakeOrder("0.6500", side="sell"),),
        include_raw_order_metadata=True,
    )[0]
    assert row.open_order_input_status == "HAS_OPEN_ORDERS"


def test_missing_zone_source_is_distinguished() -> None:
    row = _build_rows_for_card(
        zone_context_input_status="ZONE_SOURCE_MISSING",
    )[0]
    assert row.zone_context_input_status == "ZONE_SOURCE_MISSING"
    assert "ZONE_SOURCE_MISSING" in row.all_missing_reasons
    assert "MISSING_ZONE_CONTEXT" in row.all_missing_reasons


def test_symbol_missing_in_zone_source_is_distinguished() -> None:
    row = _build_rows_for_card(
        zone_context_input_status="ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING",
    )[0]
    assert row.zone_context_input_status == "ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING"
    assert "ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING" in row.all_missing_reasons
    assert "MISSING_ZONE_CONTEXT" in row.all_missing_reasons


def test_manual_zone_context_is_reported() -> None:
    row = _build_rows_for_card(
        fib_ext=_fib_ext(),
        zone_context_input_status="MANUAL_ZONE_CONTEXT_USED",
        include_raw_order_metadata=True,
    )[0]
    assert row.zone_context_input_status == "MANUAL_ZONE_CONTEXT_USED"
    assert row.primary_missing_reason == "READY_FOR_PROFIT_PLAN"


def test_valid_fixture_reports_ready_for_profit_plan() -> None:
    row = _build_rows_for_card(
        fib_ext=_fib_ext(),
        sell_orders=(_FakeOrder("0.6500", side="sell"),),
        include_raw_order_metadata=True,
    )[0]
    assert row.open_order_input_status == "HAS_OPEN_ORDERS"
    assert row.primary_missing_reason == "READY_FOR_PROFIT_PLAN"
    assert row.filtered_by_profit_plan is False


def test_json_snapshot_structure() -> None:
    row = _build_rows_for_card(
        fib_ext=_fib_ext(),
        sell_orders=(_FakeOrder("0.6500", side="sell"),),
        include_raw_order_metadata=True,
    )[0]
    snap = build_json_snapshot([row], broker_mode="offline")
    assert snap["broker_writes"] == 0
    assert snap["order_submission"] == 0
    assert snap["executor"] == "none"
    assert len(snap["markets"]) == 1
    assert snap["markets"][0]["primary_missing_reason"] == "READY_FOR_PROFIT_PLAN"


def test_summary_contains_ready_state() -> None:
    row = _build_rows_for_card(
        fib_ext=_fib_ext(),
        sell_orders=(_FakeOrder("0.6500", side="sell"),),
        include_raw_order_metadata=True,
    )[0]
    summary = format_summary([row], broker_mode="offline")
    assert "READY_FOR_PROFIT_PLAN" in summary


def test_runner_has_no_forbidden_imports() -> None:
    source = Path("src/reporting/run_manual_short_trader_profit_plan_input_audit_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"decision_gate", "execution_planner", "executor"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for item in forbidden:
                assert item not in module, f"forbidden import '{item}' in audit runner"


def test_runner_uses_canonical_db_price_input_without_ticker_compatibility_shim() -> None:
    source = Path("src/reporting/run_manual_short_trader_profit_plan_input_audit_v1.py").read_text(encoding="utf-8")
    assert "fetch_ticker_prices" not in source
    assert "load_account_scoped_short_dashboard_context" in source
    assert "classify_market_prices_by_market" in source
    assert "src.execution" not in source


def test_runner_has_no_order_mutation_strings() -> None:
    source = Path("src/reporting/run_manual_short_trader_profit_plan_input_audit_v1.py").read_text(encoding="utf-8")
    assert "placeOrder" not in source
    assert "cancelOrder" not in source
    assert "create order" not in source.lower()


def test_snapshot_is_valid_json() -> None:
    row = _build_rows_for_card(
        fib_ext=_fib_ext(),
        sell_orders=(_FakeOrder("0.6500", side="sell"),),
        include_raw_order_metadata=True,
    )[0]
    raw = json.dumps(build_json_snapshot([row], broker_mode="offline"))
    parsed = json.loads(raw)
    assert parsed["markets"][0]["market"] == "WLD-EUR"


def main() -> None:
    test_missing_price_reports_missing_current_price()
    test_missing_zone_context_reports_missing_zone_context()
    test_no_open_orders_reports_no_open_orders()
    test_valid_zone_context_without_open_orders_can_still_render_visible_card()
    test_open_order_source_missing_is_distinguished()
    test_valid_open_order_fixture_reports_has_open_orders()
    test_missing_zone_source_is_distinguished()
    test_symbol_missing_in_zone_source_is_distinguished()
    test_manual_zone_context_is_reported()
    test_valid_fixture_reports_ready_for_profit_plan()
    test_json_snapshot_structure()
    test_summary_contains_ready_state()
    test_runner_has_no_forbidden_imports()
    test_runner_has_no_order_mutation_strings()
    test_snapshot_is_valid_json()
    print("ok")


if __name__ == "__main__":
    main()
