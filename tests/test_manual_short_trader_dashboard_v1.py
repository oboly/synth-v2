from __future__ import annotations

import ast
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import src.reporting.account_dashboard_profile_access_v1 as profile_access
import src.reporting.run_manual_short_trader_dashboard_v1 as dashboard_runner
from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot
from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    AccountScopedShortDashboardContext,
    build_account_market_scope,
)
from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerBalanceRow,
    BrokerOrderRow,
    assign_order_labels,
    build_all_sections,
    build_json_snapshot,
    collect_unpriced_markets,
    compute_distance_pct,
    compute_quote_value,
    normalize_broker_balance,
    normalize_broker_order,
    parse_market,
    render_full_html,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _raw_order(
    order_id: str = "ord-001",
    market: str = "WLD-EUR",
    side: str = "buy",
    price: str = "0.3500",
    amount: str = "200",
    filled_amount: str = "0",
    status: str = "new",
    created: int = 1685000000000,
) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "market": market,
        "side": side,
        "orderType": "limit",
        "amount": amount,
        "amountRemaining": amount,
        "price": price,
        "filledAmount": filled_amount,
        "status": status,
        "created": created,
    }


def _raw_balance(
    symbol: str = "WLD",
    available: str = "150",
    in_order: str = "25",
) -> dict[str, Any]:
    return {"symbol": symbol, "available": available, "inOrder": in_order}


def _make_sections() -> list:
    orders = [
        normalize_broker_order(_raw_order("o-1", "WLD-EUR", "buy", "0.3500", "200")),
        normalize_broker_order(_raw_order("o-2", "WLD-EUR", "sell", "0.6800", "100")),
        normalize_broker_order(_raw_order("o-3", "ONDO-EUR", "buy", "0.8500", "500")),
    ]
    balances = [
        normalize_broker_balance(_raw_balance("WLD", "150", "70")),
        normalize_broker_balance({"symbol": "EUR", "available": "200", "inOrder": "50"}),
    ]
    prices: dict[str, Decimal] = {
        "WLD-EUR": Decimal("0.68"),
        "ONDO-EUR": Decimal("0.90"),
    }
    return build_all_sections(orders, balances, prices)


# ---------------------------------------------------------------------------
# parse_market
# ---------------------------------------------------------------------------

def test_parse_market_standard() -> None:
    symbol, quote = parse_market("WLD-EUR")
    assert symbol == "WLD"
    assert quote == "EUR"


def test_parse_market_lowercase_normalized() -> None:
    symbol, quote = parse_market("ondo-eur")
    assert symbol == "ONDO"
    assert quote == "EUR"


def test_parse_market_no_dash_returns_empty_quote() -> None:
    symbol, quote = parse_market("SOLO")
    assert symbol == "SOLO"
    assert quote == ""


# ---------------------------------------------------------------------------
# normalize_broker_order
# ---------------------------------------------------------------------------

def test_normalize_broker_order_field_mapping() -> None:
    row = normalize_broker_order(_raw_order())
    assert row.order_id == "ord-001"
    assert row.market == "WLD-EUR"
    assert row.side == "buy"
    assert row.order_type == "limit"
    assert row.limit_price == Decimal("0.3500")
    assert row.amount == Decimal("200")
    assert row.filled_amount == Decimal("0")
    assert row.status == "new"
    assert row.created_at_ms == 1685000000000


def test_normalize_broker_order_sell_side() -> None:
    row = normalize_broker_order(_raw_order(side="sell", price="0.6800", amount="100"))
    assert row.side == "sell"
    assert row.limit_price == Decimal("0.6800")
    assert row.amount == Decimal("100")


# ---------------------------------------------------------------------------
# normalize_broker_balance
# ---------------------------------------------------------------------------

def test_normalize_broker_balance_field_mapping() -> None:
    row = normalize_broker_balance(_raw_balance())
    assert row.symbol == "WLD"
    assert row.available == Decimal("150")
    assert row.in_order == Decimal("25")


def test_normalize_broker_balance_symbol_uppercased() -> None:
    row = normalize_broker_balance({"symbol": "eur", "available": "42", "inOrder": "8"})
    assert row.symbol == "EUR"


# ---------------------------------------------------------------------------
# compute_distance_pct
# ---------------------------------------------------------------------------

def test_compute_distance_pct_positive_when_order_above_current() -> None:
    dist = compute_distance_pct(Decimal("0.70"), Decimal("0.68"))
    assert dist is not None and dist > 0
    expected = (Decimal("0.70") - Decimal("0.68")) / Decimal("0.68") * Decimal("100")
    assert abs(dist - expected) < Decimal("0.000001")


def test_compute_distance_pct_negative_when_order_below_current() -> None:
    dist = compute_distance_pct(Decimal("0.65"), Decimal("0.68"))
    assert dist is not None and dist < 0


def test_compute_distance_pct_zero_when_at_current_price() -> None:
    dist = compute_distance_pct(Decimal("0.68"), Decimal("0.68"))
    assert dist == Decimal("0")


def test_compute_distance_pct_none_when_current_zero() -> None:
    assert compute_distance_pct(Decimal("0.68"), Decimal("0")) is None


def test_compute_distance_pct_none_when_current_negative() -> None:
    assert compute_distance_pct(Decimal("0.68"), Decimal("-1")) is None


# ---------------------------------------------------------------------------
# compute_quote_value
# ---------------------------------------------------------------------------

def test_compute_quote_value_basic() -> None:
    result = compute_quote_value(Decimal("0.3500"), Decimal("200"))
    assert result == Decimal("70.0000")


def test_compute_quote_value_decimal_precision() -> None:
    result = compute_quote_value(Decimal("0.6812"), Decimal("147.5"))
    assert result == Decimal("100.477")


def test_compute_quote_value_sell_order() -> None:
    result = compute_quote_value(Decimal("0.6800"), Decimal("100"))
    assert result == Decimal("68.0000")


# ---------------------------------------------------------------------------
# assign_order_labels
# ---------------------------------------------------------------------------

def test_assign_labels_near_sell_flagged_within_threshold() -> None:
    """Sell at 0.69, current at 0.68: distance ≈ +1.47 % → NEAR_SELL."""
    labels = assign_order_labels(
        side="sell",
        limit_price=Decimal("0.69"),
        filled_amount=Decimal("0"),
        amount=Decimal("100"),
        current_price=Decimal("0.68"),
    )
    assert "NEAR_SELL" in labels


def test_assign_labels_near_sell_not_flagged_when_far() -> None:
    """Sell at 0.80, current at 0.68: distance ≈ +17.6 % → not NEAR_SELL."""
    labels = assign_order_labels(
        side="sell",
        limit_price=Decimal("0.80"),
        filled_amount=Decimal("0"),
        amount=Decimal("100"),
        current_price=Decimal("0.68"),
    )
    assert "NEAR_SELL" not in labels


def test_assign_labels_near_sell_not_flagged_when_current_above_sell() -> None:
    """Sell at 0.65, current at 0.68: price already past sell → not NEAR_SELL."""
    labels = assign_order_labels(
        side="sell",
        limit_price=Decimal("0.65"),
        filled_amount=Decimal("0"),
        amount=Decimal("100"),
        current_price=Decimal("0.68"),
    )
    assert "NEAR_SELL" not in labels


def test_assign_labels_near_buy_flagged_within_threshold() -> None:
    """Buy at 0.67, current at 0.68: distance ≈ −1.47 % → NEAR_BUY."""
    labels = assign_order_labels(
        side="buy",
        limit_price=Decimal("0.67"),
        filled_amount=Decimal("0"),
        amount=Decimal("200"),
        current_price=Decimal("0.68"),
    )
    assert "NEAR_BUY" in labels


def test_assign_labels_near_buy_not_flagged_when_far() -> None:
    """Buy at 0.30, current at 0.68: distance ≈ −55.9 % → not NEAR_BUY."""
    labels = assign_order_labels(
        side="buy",
        limit_price=Decimal("0.30"),
        filled_amount=Decimal("0"),
        amount=Decimal("200"),
        current_price=Decimal("0.68"),
    )
    assert "NEAR_BUY" not in labels


def test_assign_labels_filled_review_needed_on_partial_fill() -> None:
    """50 of 100 filled → FILLED_REVIEW_NEEDED."""
    labels = assign_order_labels(
        side="buy",
        limit_price=Decimal("0.35"),
        filled_amount=Decimal("50"),
        amount=Decimal("100"),
        current_price=Decimal("0.40"),
    )
    assert "FILLED_REVIEW_NEEDED" in labels


def test_assign_labels_no_filled_review_when_unfilled() -> None:
    labels = assign_order_labels(
        side="buy",
        limit_price=Decimal("0.35"),
        filled_amount=Decimal("0"),
        amount=Decimal("100"),
        current_price=Decimal("0.40"),
    )
    assert "FILLED_REVIEW_NEEDED" not in labels


def test_assign_labels_no_filled_review_when_fully_filled() -> None:
    labels = assign_order_labels(
        side="buy",
        limit_price=Decimal("0.35"),
        filled_amount=Decimal("100"),
        amount=Decimal("100"),
        current_price=Decimal("0.40"),
    )
    assert "FILLED_REVIEW_NEEDED" not in labels


def test_assign_labels_manual_only_always_present() -> None:
    for side in ("buy", "sell"):
        labels = assign_order_labels(
            side=side,
            limit_price=Decimal("0.50"),
            filled_amount=Decimal("0"),
            amount=Decimal("100"),
            current_price=None,
        )
        assert "MANUAL_ONLY" in labels


def test_assign_labels_no_near_flags_without_current_price() -> None:
    labels = assign_order_labels(
        side="sell",
        limit_price=Decimal("0.69"),
        filled_amount=Decimal("0"),
        amount=Decimal("100"),
        current_price=None,
    )
    assert "NEAR_SELL" not in labels
    assert "NEAR_BUY" not in labels
    assert "MANUAL_ONLY" in labels


def test_assign_labels_near_sell_at_exact_threshold() -> None:
    """Exactly 2 % above → still NEAR_SELL (threshold is inclusive)."""
    current = Decimal("0.68")
    price_at_threshold = current * Decimal("1.02")
    labels = assign_order_labels(
        side="sell",
        limit_price=price_at_threshold,
        filled_amount=Decimal("0"),
        amount=Decimal("100"),
        current_price=current,
    )
    assert "NEAR_SELL" in labels


def test_assign_labels_near_buy_at_exact_threshold() -> None:
    """Exactly 2 % below → still NEAR_BUY (threshold is inclusive)."""
    current = Decimal("0.68")
    price_at_threshold = current * Decimal("0.98")
    labels = assign_order_labels(
        side="buy",
        limit_price=price_at_threshold,
        filled_amount=Decimal("0"),
        amount=Decimal("200"),
        current_price=current,
    )
    assert "NEAR_BUY" in labels


# ---------------------------------------------------------------------------
# build_all_sections
# ---------------------------------------------------------------------------

def test_build_all_sections_groups_by_market() -> None:
    sections = _make_sections()
    symbols = {s.symbol for s in sections}
    assert "WLD" in symbols
    assert "ONDO" in symbols


def test_build_all_sections_separates_buy_and_sell() -> None:
    sections = _make_sections()
    wld = next(s for s in sections if s.symbol == "WLD")
    assert len(wld.buy_orders) == 1
    assert len(wld.sell_orders) == 1
    assert wld.buy_orders[0].side == "buy"
    assert wld.sell_orders[0].side == "sell"


def test_build_all_sections_carries_balance() -> None:
    sections = _make_sections()
    wld = next(s for s in sections if s.symbol == "WLD")
    assert wld.balance_available == Decimal("150")
    assert wld.balance_in_order == Decimal("70")


def test_build_all_sections_current_price_set() -> None:
    sections = _make_sections()
    wld = next(s for s in sections if s.symbol == "WLD")
    assert wld.current_price == Decimal("0.68")


def test_build_all_sections_sell_at_current_is_near_sell() -> None:
    """WLD sell at 0.68 == current 0.68 → distance = 0 % → NEAR_SELL."""
    sections = _make_sections()
    wld = next(s for s in sections if s.symbol == "WLD")
    sell = wld.sell_orders[0]
    assert "NEAR_SELL" in sell.labels


def test_build_all_sections_quote_value_correct() -> None:
    sections = _make_sections()
    wld = next(s for s in sections if s.symbol == "WLD")
    buy = wld.buy_orders[0]
    assert buy.quote_value == Decimal("0.3500") * Decimal("200")


def test_build_all_sections_manual_only_in_section_labels() -> None:
    sections = _make_sections()
    for section in sections:
        assert "MANUAL_ONLY" in section.section_labels


def test_build_all_sections_empty_returns_empty_list() -> None:
    assert build_all_sections([], [], {}) == []


def test_build_all_sections_ondo_buy_far_from_current() -> None:
    """ONDO buy at 0.85, current at 0.90: distance ≈ −5.6 % → not NEAR_BUY."""
    sections = _make_sections()
    ondo = next(s for s in sections if s.symbol == "ONDO")
    buy = ondo.buy_orders[0]
    assert "NEAR_BUY" not in buy.labels
    assert "MANUAL_ONLY" in buy.labels


def test_build_all_sections_buy_orders_sorted_descending_by_price() -> None:
    orders = [
        normalize_broker_order(_raw_order("o-a", "WLD-EUR", "buy", "0.30", "100")),
        normalize_broker_order(_raw_order("o-b", "WLD-EUR", "buy", "0.35", "100")),
        normalize_broker_order(_raw_order("o-c", "WLD-EUR", "buy", "0.28", "100")),
    ]
    sections = build_all_sections(orders, [], {"WLD-EUR": Decimal("0.68")})
    wld = sections[0]
    prices = [row.limit_price for row in wld.buy_orders]
    assert prices == sorted(prices, reverse=True)


def test_build_all_sections_sell_orders_sorted_ascending_by_price() -> None:
    orders = [
        normalize_broker_order(_raw_order("o-a", "WLD-EUR", "sell", "0.80", "50")),
        normalize_broker_order(_raw_order("o-b", "WLD-EUR", "sell", "0.70", "50")),
        normalize_broker_order(_raw_order("o-c", "WLD-EUR", "sell", "0.90", "50")),
    ]
    sections = build_all_sections(orders, [], {"WLD-EUR": Decimal("0.68")})
    wld = sections[0]
    prices = [row.limit_price for row in wld.sell_orders]
    assert prices == sorted(prices)


# ---------------------------------------------------------------------------
# render_full_html (smoke tests)
# ---------------------------------------------------------------------------

def test_render_full_html_contains_symbol_names() -> None:
    sections = _make_sections()
    html = render_full_html(sections, broker_mode="offline")
    assert "WLD" in html
    assert "ONDO" in html


def test_render_full_html_contains_open_orders_monitor_title() -> None:
    html = render_full_html(_make_sections(), broker_mode="offline")
    assert "Open Orders Monitor" in html
    assert "Manual Short Trader Dashboard" not in html


def test_render_full_html_contains_safety_note() -> None:
    sections = _make_sections()
    html = render_full_html(sections, broker_mode="offline")
    assert "No broker writes" in html
    assert "No order submission" in html


def test_render_full_html_contains_current_price() -> None:
    sections = _make_sections()
    html = render_full_html(sections, broker_mode="offline")
    assert "0.68" in html


def test_render_full_html_empty_sections_shows_no_orders_note() -> None:
    html = render_full_html([], broker_mode="offline")
    assert "No open orders" in html


def test_render_full_html_buy_sell_headings_present() -> None:
    sections = _make_sections()
    html = render_full_html(sections, broker_mode="offline")
    assert "BUY Orders" in html
    assert "SELL Orders" in html


def test_dashboard_sources_do_not_introduce_order_mutation_strings() -> None:
    for path in (
        "src/reporting/manual_short_trader_dashboard_v1.py",
        "src/reporting/run_manual_short_trader_dashboard_v1.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "placeOrder" not in source
        assert "cancelOrder" not in source
        assert "create order" not in source.lower()


# ---------------------------------------------------------------------------
# build_json_snapshot
# ---------------------------------------------------------------------------

def test_build_json_snapshot_safety_markers() -> None:
    snapshot = build_json_snapshot(_make_sections(), snapshot_ts="2026-06-03T00:00:00+00:00")
    assert snapshot["broker_writes"] == 0
    assert snapshot["order_submission"] == 0


def test_build_json_snapshot_symbol_count() -> None:
    snapshot = build_json_snapshot(_make_sections())
    assert len(snapshot["symbols"]) == 2


def test_build_json_snapshot_is_json_serializable() -> None:
    text = json.dumps(build_json_snapshot(_make_sections()))
    parsed = json.loads(text)
    assert len(parsed["symbols"]) == 2


def test_build_json_snapshot_buy_sell_structure() -> None:
    snapshot = build_json_snapshot(_make_sections())
    wld = next(s for s in snapshot["symbols"] if s["symbol"] == "WLD")
    assert len(wld["buy_orders"]) == 1
    assert len(wld["sell_orders"]) == 1
    assert isinstance(wld["buy_orders"][0]["labels"], list)


def test_build_json_snapshot_order_fields_present() -> None:
    snapshot = build_json_snapshot(_make_sections())
    wld = next(s for s in snapshot["symbols"] if s["symbol"] == "WLD")
    order = wld["buy_orders"][0]
    for field in ("order_id", "market", "side", "limit_price", "amount",
                  "filled_amount", "quote_value", "distance_pct", "status", "labels"):
        assert field in order, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# collect_unpriced_markets
# ---------------------------------------------------------------------------

def test_collect_unpriced_markets_returns_discovered_markets() -> None:
    """Markets in orders but absent from prices dict must be returned."""
    orders = [
        normalize_broker_order(_raw_order("o-1", "WLD-EUR", "buy", "0.35", "100")),
        normalize_broker_order(_raw_order("o-2", "ALGO-EUR", "sell", "0.11", "500")),
        normalize_broker_order(_raw_order("o-3", "NEAR-EUR", "buy", "2.50", "200")),
    ]
    prices: dict[str, Decimal] = {"WLD-EUR": Decimal("0.68")}
    result = collect_unpriced_markets(orders, prices)
    assert "ALGO-EUR" in result
    assert "NEAR-EUR" in result
    assert "WLD-EUR" not in result


def test_collect_unpriced_markets_empty_when_all_priced() -> None:
    orders = [
        normalize_broker_order(_raw_order("o-1", "WLD-EUR", "buy", "0.35", "100")),
        normalize_broker_order(_raw_order("o-2", "ONDO-EUR", "sell", "0.90", "50")),
    ]
    prices: dict[str, Decimal] = {
        "WLD-EUR": Decimal("0.68"),
        "ONDO-EUR": Decimal("0.90"),
    }
    assert collect_unpriced_markets(orders, prices) == []


def test_collect_unpriced_markets_empty_when_no_orders() -> None:
    assert collect_unpriced_markets([], {"WLD-EUR": Decimal("0.68")}) == []


def test_collect_unpriced_markets_result_is_sorted() -> None:
    orders = [
        normalize_broker_order(_raw_order("o-1", "ZRX-EUR", "buy", "0.30", "100")),
        normalize_broker_order(_raw_order("o-2", "ALGO-EUR", "buy", "0.11", "200")),
    ]
    result = collect_unpriced_markets(orders, {})
    assert result == sorted(result)


def test_build_all_sections_uses_discovered_price() -> None:
    """
    Simulate what the runner does: orders contain a market (ALGO-EUR) not in
    the initial prices dict. After collect_unpriced_markets + price lookup the
    section should carry the discovered price and non-None distance values.
    """
    orders = [
        normalize_broker_order(_raw_order("o-1", "ALGO-EUR", "buy", "0.10", "300")),
    ]
    # Initial prices missing ALGO-EUR — simulates the old bug
    prices_initial: dict[str, Decimal] = {}
    assert collect_unpriced_markets(orders, prices_initial) == ["ALGO-EUR"]

    # Runner fetches the missing price and merges it
    discovered_price = Decimal("0.113")
    prices_full = {**prices_initial, "ALGO-EUR": discovered_price}

    sections = build_all_sections(orders, [], prices_full)
    algo = sections[0]
    assert algo.current_price == discovered_price
    assert algo.buy_orders[0].distance_pct is not None


# ---------------------------------------------------------------------------
# Boundary: no forbidden imports in the pure module
# ---------------------------------------------------------------------------

def test_pure_module_has_no_forbidden_imports() -> None:
    source = Path("src/reporting/manual_short_trader_dashboard_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_terms = (
        "bitvavo_client",
        "decision_gate",
        "execution_planner",
        "executor",
    )
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        parts = tuple(part for part in module_name.split(".") if part)
        for term in forbidden_terms:
            assert term not in parts, f"Forbidden module import in pure module: {module_name}"

    for ref in ("src.execution.bitvavo_client", "src.common.db",
                "src.decision_gate", "src.executor",
                "place_order", "cancel_order"):
        assert ref not in source, f"Forbidden reference in pure module: {ref}"


def test_runner_has_no_broker_write_calls() -> None:
    """Runner may read from broker but must not write (place/cancel orders)."""
    source = Path("src/reporting/run_manual_short_trader_dashboard_v1.py").read_text(encoding="utf-8")
    for forbidden in (
        "place_order",
        "cancel_order",
        "BROKER_WRITE_PERMISSION",
        "_require_private_write_permission",
    ):
        assert forbidden not in source, f"Forbidden broker write reference in runner: {forbidden}"


def _price_snapshot(symbol: str, market: str, price: str) -> MarketPriceSnapshot:
    return MarketPriceSnapshot(
        venue="bitvavo",
        symbol=symbol,
        market=market,
        quote_currency="EUR",
        price=Decimal(price),
        source_name="market_price_snapshot_v1",
        source_ts_utc=None,
        observed_ts_utc=None,
    )


def _context(
    *,
    profile: str,
    account_id: int,
    markets: tuple[str, ...],
    orders: tuple[BrokerOrderRow, ...],
    balances: tuple[BrokerBalanceRow, ...],
    prices: dict[str, str],
) -> AccountScopedShortDashboardContext:
    snapshots = {
        market.split("-", 1)[0]: _price_snapshot(market.split("-", 1)[0], market, price)
        for market, price in prices.items()
    }
    open_order_count_by_market: dict[str, int] = {}
    for order in orders:
        open_order_count_by_market[order.market] = open_order_count_by_market.get(order.market, 0) + 1
    return AccountScopedShortDashboardContext(
        profile=profile,
        account_code=f"stable-ref-{account_id}",
        trading_account_id=account_id,
        venue="bitvavo",
        latest_balance_snapshot_ts_utc=None,
        latest_order_snapshot_ts_utc=None,
        balances=balances,
        orders=orders,
        account_asset_rows=(),
        open_order_count_by_market=open_order_count_by_market,
        market_price_by_symbol=snapshots,
        markets=markets,
    )


def test_build_account_market_scope_excludes_hidden_asset_without_open_order() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[
            {
                "market": "WLD-EUR",
                "is_hidden": 1,
                "is_visible": 1,
                "source": "WALLET_DISCOVERY",
            }
        ],
        balances=[],
        orders=[],
    )
    assert markets == []


def test_build_account_market_scope_keeps_disabled_asset_with_open_order_visible() -> None:
    markets = build_account_market_scope(
        account_asset_rows=[
            {
                "market": "ONDO-EUR",
                "is_hidden": 1,
                "is_visible": 0,
                "source": "WALLET_DISCOVERY",
                "disabled_until_utc": "2099-01-01 00:00:00",
            }
        ],
        balances=[],
        orders=[
            BrokerOrderRow(
                order_id="ord-1",
                market="ONDO-EUR",
                side="buy",
                order_type="limit",
                limit_price=Decimal("0.80"),
                amount=Decimal("10"),
                filled_amount=Decimal("0"),
                remaining_amount=Decimal("10"),
                status="new",
                created_at_ms=1,
            )
        ],
    )
    assert markets == ["ONDO-EUR"]


def test_dashboard_runner_writes_account_scoped_outputs() -> None:
    original_parse_args = dashboard_runner.parse_args
    original_load_context = dashboard_runner.load_account_scoped_short_dashboard_context
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            dashboard_runner.parse_args = lambda: type(
                "Args",
                (),
                {
                    "account_profile": "joost",
                    "account_code": None,
                    "venue": "bitvavo",
                    "output_root": str(output_root),
                    "output_html": None,
                    "output_json": None,
                    "fib_map_rows": str(output_root / "missing.csv"),
                    "output": "none",
                },
            )()
            dashboard_runner.load_account_scoped_short_dashboard_context = lambda **_: _context(
                profile="joost",
                account_id=11,
                markets=("WLD-EUR",),
                orders=(
                    BrokerOrderRow(
                        order_id="ord-1",
                        market="WLD-EUR",
                        side="buy",
                        order_type="limit",
                        limit_price=Decimal("0.35"),
                        amount=Decimal("100"),
                        filled_amount=Decimal("0"),
                        remaining_amount=Decimal("100"),
                        status="new",
                        created_at_ms=1,
                    ),
                ),
                balances=(BrokerBalanceRow(symbol="WLD", available=Decimal("5"), in_order=Decimal("0")),),
                prices={"WLD-EUR": "0.40"},
            )
            assert dashboard_runner.main() == 0
            html_path = output_root / "accounts" / "joost" / "open-orders-monitor.html"
            json_path = output_root / "accounts" / "joost" / "open-orders-monitor.json"
            assert html_path.exists()
            assert json_path.exists()
            html = html_path.read_text(encoding="utf-8")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            assert "Open Orders Monitor" in html
            assert "WLD" in html
            assert payload["broker_writes"] == 0
            assert payload["order_submission"] == 0
    finally:
        dashboard_runner.parse_args = original_parse_args
        dashboard_runner.load_account_scoped_short_dashboard_context = original_load_context


def test_dashboard_runner_missing_account_fails_closed() -> None:
    original_parse_args = dashboard_runner.parse_args
    original_load_context = dashboard_runner.load_account_scoped_short_dashboard_context
    original_resolve_access = dashboard_runner.resolve_dashboard_profile_access
    try:
        dashboard_runner.parse_args = lambda: type(
            "Args",
            (),
            {
                "account_profile": "joost",
                "venue": "bitvavo",
                "output_root": "/tmp",
                "output_html": None,
                "output_json": None,
                "fib_map_rows": "/tmp/missing.csv",
                "output": "none",
            },
        )()
        dashboard_runner.resolve_dashboard_profile_access = lambda **_: (_ for _ in ()).throw(
            RuntimeError(f"{profile_access.PROFILE_HAS_NO_ACCOUNT_ACCESS}: profile=hugo venue=bitvavo")
        )
        dashboard_runner.load_account_scoped_short_dashboard_context = lambda **_: (_ for _ in ()).throw(
            RuntimeError("trading_account missing")
        )
        assert dashboard_runner.main() == 1
    finally:
        dashboard_runner.parse_args = original_parse_args
        dashboard_runner.load_account_scoped_short_dashboard_context = original_load_context
        dashboard_runner.resolve_dashboard_profile_access = original_resolve_access


def test_runner_source_does_not_construct_account_code_from_profile_name() -> None:
    source = Path("src/reporting/run_manual_short_trader_dashboard_v1.py").read_text(encoding="utf-8")
    assert "bitvavo_{args.account_profile}_read" not in source
    assert "default_account_code" not in source


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    tests = [
        test_parse_market_standard,
        test_parse_market_lowercase_normalized,
        test_parse_market_no_dash_returns_empty_quote,
        test_normalize_broker_order_field_mapping,
        test_normalize_broker_order_sell_side,
        test_normalize_broker_balance_field_mapping,
        test_normalize_broker_balance_symbol_uppercased,
        test_compute_distance_pct_positive_when_order_above_current,
        test_compute_distance_pct_negative_when_order_below_current,
        test_compute_distance_pct_zero_when_at_current_price,
        test_compute_distance_pct_none_when_current_zero,
        test_compute_distance_pct_none_when_current_negative,
        test_compute_quote_value_basic,
        test_compute_quote_value_decimal_precision,
        test_compute_quote_value_sell_order,
        test_assign_labels_near_sell_flagged_within_threshold,
        test_assign_labels_near_sell_not_flagged_when_far,
        test_assign_labels_near_sell_not_flagged_when_current_above_sell,
        test_assign_labels_near_buy_flagged_within_threshold,
        test_assign_labels_near_buy_not_flagged_when_far,
        test_assign_labels_filled_review_needed_on_partial_fill,
        test_assign_labels_no_filled_review_when_unfilled,
        test_assign_labels_no_filled_review_when_fully_filled,
        test_assign_labels_manual_only_always_present,
        test_assign_labels_no_near_flags_without_current_price,
        test_assign_labels_near_sell_at_exact_threshold,
        test_assign_labels_near_buy_at_exact_threshold,
        test_build_all_sections_groups_by_market,
        test_build_all_sections_separates_buy_and_sell,
        test_build_all_sections_carries_balance,
        test_build_all_sections_current_price_set,
        test_build_all_sections_sell_at_current_is_near_sell,
        test_build_all_sections_quote_value_correct,
        test_build_all_sections_manual_only_in_section_labels,
        test_build_all_sections_empty_returns_empty_list,
        test_build_all_sections_ondo_buy_far_from_current,
        test_build_all_sections_buy_orders_sorted_descending_by_price,
        test_build_all_sections_sell_orders_sorted_ascending_by_price,
        test_render_full_html_contains_symbol_names,
        test_render_full_html_contains_open_orders_monitor_title,
        test_render_full_html_contains_safety_note,
        test_render_full_html_contains_current_price,
        test_render_full_html_empty_sections_shows_no_orders_note,
        test_render_full_html_buy_sell_headings_present,
        test_dashboard_sources_do_not_introduce_order_mutation_strings,
        test_build_json_snapshot_safety_markers,
        test_build_json_snapshot_symbol_count,
        test_build_json_snapshot_is_json_serializable,
        test_build_json_snapshot_buy_sell_structure,
        test_build_json_snapshot_order_fields_present,
        test_collect_unpriced_markets_returns_discovered_markets,
        test_collect_unpriced_markets_empty_when_all_priced,
        test_collect_unpriced_markets_empty_when_no_orders,
        test_collect_unpriced_markets_result_is_sorted,
        test_build_all_sections_uses_discovered_price,
        test_pure_module_has_no_forbidden_imports,
        test_runner_has_no_broker_write_calls,
        test_build_account_market_scope_excludes_hidden_asset_without_open_order,
        test_build_account_market_scope_keeps_disabled_asset_with_open_order_visible,
        test_dashboard_runner_writes_account_scoped_outputs,
        test_dashboard_runner_missing_account_fails_closed,
        test_runner_source_does_not_construct_account_code_from_profile_name,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
