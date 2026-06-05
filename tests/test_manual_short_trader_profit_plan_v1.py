from __future__ import annotations

import ast
import json
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import src.reporting.run_manual_short_trader_profit_plan_v1 as profit_plan_runner
import src.reporting.account_dashboard_profile_access_v1 as profile_access
from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot
from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountScopedShortDashboardContext
from src.reporting.manual_short_trader_dashboard_v1 import BrokerBalanceRow, BrokerOrderRow
from src.reporting.manual_short_trader_profit_plan_v1 import (
    FibExtContext,
    ProfitPlanCard,
    ReentryContext,
    build_json_snapshot,
    build_profit_plan_card,
    render_full_html,
)


def _wld_fib_ext(price_band: str = "BETWEEN_1272_1618") -> FibExtContext:
    return FibExtContext(
        ext_1_272=Decimal("0.454438"),
        ext_1_618=Decimal("0.515600"),
        ext_2_000=Decimal("0.8000"),
        breakout_gate=Decimal("0.3800"),
        price_band=price_band,
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )


def _fet_reentry(missed_pct: str | None = "1.95") -> ReentryContext:
    return ReentryContext(
        r382_price=Decimal("0.2142"),
        r500_price=Decimal("0.2050"),
        r618_price=Decimal("0.1958"),
        r786_price=Decimal("0.1827"),
        deepest_touched_label="retrace_0_382" if missed_pct else None,
        missed_main_rebuy_by_pct=Decimal(missed_pct) if missed_pct else None,
    )


class _FakeOrder:
    def __init__(self, price: str, side: str = "buy") -> None:
        self.limit_price = Decimal(price)
        self.side = side


def _make_card(
    *,
    current_price: str | None,
    fib_ext: FibExtContext | None = None,
    reentry: ReentryContext | None = None,
    buy_orders: tuple[_FakeOrder, ...] = (),
    sell_orders: tuple[_FakeOrder, ...] = (),
    filled_sell_levels: tuple[Decimal, ...] = (),
    completed_sell_levels: tuple[Decimal, ...] = (),
    symbol: str = "WLD",
    market: str = "WLD-EUR",
) -> ProfitPlanCard:
    return build_profit_plan_card(
        symbol=symbol,
        market=market,
        current_price=Decimal(current_price) if current_price is not None else None,
        fib_ext=fib_ext,
        reentry=reentry,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        filled_sell_levels=filled_sell_levels,
        completed_sell_levels=completed_sell_levels,
    )


def _price_snapshot(symbol: str, market: str, price: str) -> MarketPriceSnapshot:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    return MarketPriceSnapshot(
        venue="bitvavo",
        symbol=symbol,
        market=market,
        quote_currency="EUR",
        price=Decimal(price),
        source_name="market_price_snapshot_v1",
        source_ts_utc=now,
        observed_ts_utc=now,
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


def test_pure_module_has_no_forbidden_imports() -> None:
    source = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"bitvavo_client", "decision_gate", "execution_planner", "executor", "pymysql", "db"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for term in forbidden:
                assert term not in module


def test_runner_has_no_broker_or_execution_imports() -> None:
    source = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    for module_name in imported_modules:
        assert "bitvavo_client" not in module_name
        assert "decision_gate" not in module_name
        assert "execution_planner" not in module_name
        assert "executor" not in module_name
    for forbidden_call in ("place_order", "cancel_order", "BROKER_WRITE_PERMISSION"):
        assert forbidden_call not in source


def test_load_zone_contexts_uses_source_rows_without_manual_cli() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "\n".join([
                "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price",
                "WLD,0.48,0.30,0.38,0.38,0.33",
            ]) + "\n",
            encoding="utf-8",
        )
        result = profit_plan_runner.load_zone_contexts(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("0.48")},
            swing_anchors={},
            recent_lows={},
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "HAS_ZONE_CONTEXT"


def test_load_zone_contexts_manual_cli_overrides_missing_source() -> None:
    result = profit_plan_runner.load_zone_contexts(
        markets=["WLD-EUR"],
        prices={"WLD-EUR": Decimal("0.48")},
        swing_anchors={"WLD": ["0.30", "0.38"]},
        recent_lows={"WLD": ["0.33"]},
        fib_map_rows_path=Path("/tmp/missing-fib-map.csv"),
    )
    assert result.input_status_by_symbol["WLD"] == "MANUAL_ZONE_CONTEXT_USED"


def test_load_zone_contexts_missing_source_fails_closed() -> None:
    result = profit_plan_runner.load_zone_contexts(
        markets=["WLD-EUR"],
        prices={"WLD-EUR": Decimal("0.48")},
        swing_anchors={},
        recent_lows={},
        fib_map_rows_path=Path("/tmp/missing-fib-map.csv"),
    )
    assert result.input_status_by_symbol["WLD"] == "ZONE_SOURCE_MISSING"


def test_load_zone_contexts_symbol_missing_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "\n".join([
                "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price",
                "ONDO,0.90,0.70,1.05,1.05,0.82",
            ]) + "\n",
            encoding="utf-8",
        )
        result = profit_plan_runner.load_zone_contexts(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("0.48")},
            swing_anchors={},
            recent_lows={},
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING"


def test_take_profit_waiting_when_target_is_near_and_sell_order_exists() -> None:
    card = _make_card(
        current_price="0.5120",
        fib_ext=_wld_fib_ext(),
        sell_orders=(_FakeOrder("0.515600", side="sell"),),
    )
    assert card.primary_state == "TAKE_PROFIT_WAITING"


def test_reload_zone_approaching_when_price_is_near_reload_zone() -> None:
    card = _make_card(current_price="0.2100", reentry=_fet_reentry())
    assert card.primary_state == "RELOAD_ZONE_APPROACHING"


def test_price_ran_away_when_price_is_far_above_target_assumptions() -> None:
    card = _make_card(current_price="0.7600", fib_ext=_wld_fib_ext())
    assert card.primary_state == "PRICE_RAN_AWAY"


def test_invalidation_near_when_price_approaches_risk_zone() -> None:
    fib = FibExtContext(
        ext_1_272=Decimal("0.49"),
        ext_1_618=Decimal("0.65"),
        ext_2_000=Decimal("0.80"),
        breakout_gate=Decimal("0.38"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=True,
    )
    card = _make_card(current_price="0.3600", fib_ext=fib)
    assert card.primary_state == "INVALIDATION_NEAR"


def test_order_too_far_or_stale_when_open_orders_are_far() -> None:
    card = _make_card(
        current_price="0.3000",
        reentry=_fet_reentry(),
        buy_orders=(_FakeOrder("0.1000"),),
    )
    assert card.primary_state == "ORDER_TOO_FAR_OR_STALE"


def test_do_nothing_for_neutral_valid_state() -> None:
    card = _make_card(current_price="0.2500", reentry=_fet_reentry())
    assert card.primary_state == "DO_NOTHING"


def test_insufficient_data_when_zones_are_missing() -> None:
    card = _make_card(current_price=None)
    assert card.primary_state == "INSUFFICIENT_DATA"


def test_stale_current_price_blocks_actionable_profit_plan_outputs() -> None:
    card = build_profit_plan_card(
        symbol="HOME",
        market="HOME-EUR",
        current_price=Decimal("1.30"),
        current_price_status="STALE_CURRENT_PRICE",
        current_price_age_min=Decimal("2880"),
        fib_ext=_wld_fib_ext(),
    )
    assert card.primary_state == "STALE_CURRENT_PRICE"
    assert card.action_label == "NO_CURRENT_PRICE"
    assert card.distance_to_target_pct is None
    assert card.current_price is None


def test_render_full_html_uses_profit_plan_title_and_public_monitor_href() -> None:
    card = _make_card(current_price="0.48", fib_ext=_wld_fib_ext())
    html = render_full_html(
        [card],
        monitor_link="/synth/accounts/joost/open-orders-monitor.html",
        nav_html=(
            "<nav class='cockpit-nav'>"
            "<a href='/synth/about.html'>About</a>"
            "<a href='/synth/accounts/joost/wallet.html'>Wallet</a>"
            "<a href='/synth/accounts/joost/profit-plan.html'>Profit Plan</a>"
            "<a href='/synth/accounts/joost/open-orders-monitor.html'>Open Orders Monitor</a>"
            "</nav>"
        ),
    )
    assert "Profit Plan" in html
    assert 'href="/synth/accounts/joost/open-orders-monitor.html"' in html or "href='/synth/accounts/joost/open-orders-monitor.html'" in html
    assert "/synth/accounts/joost/wallet.html" in html
    assert "/synth/accounts/joost/profit-plan.html" in html
    assert "/var/www/html/synth/" not in html
    assert "/synth/profit-plan.html" not in html
    assert "/synth/open-orders-monitor.html" not in html


def test_json_snapshot_structure_and_safety_markers() -> None:
    card = _make_card(current_price="0.48", fib_ext=_wld_fib_ext())
    snapshot = build_json_snapshot([card], broker_mode="db_snapshot")
    assert snapshot["broker_writes"] == 0
    assert snapshot["order_submission"] == 0
    assert snapshot["executor"] == "none"
    assert snapshot["symbols"][0]["primary_state"] == card.primary_state
    assert "active_target" in snapshot["symbols"][0]
    assert "target_level_statuses" in snapshot["symbols"][0]


def test_wld_fixture_advances_active_target_and_does_not_mark_passed_level_missing() -> None:
    card = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        sell_orders=(
            _FakeOrder("0.454438", side="sell"),
            _FakeOrder("0.515600", side="sell"),
        ),
    )
    assert card.active_target == Decimal("0.515600")
    assert card.distance_to_target_pct is not None
    assert card.distance_to_target_pct > 0
    assert all("missing sell @ 0.454438" not in item for item in card.order_summary.missing_suggested)
    first_level = card.target_level_statuses[0]
    second_level = card.target_level_statuses[1]
    assert first_level.level == Decimal("0.454438")
    assert first_level.lifecycle_state == "PASSED"
    assert first_level.coverage_state == "PASSED_OPEN_ORDER"
    assert second_level.level == Decimal("0.515600")
    assert second_level.is_active_target is True
    assert second_level.matching_open_sell_orders == 1


def test_price_below_first_target_keeps_first_target_active() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    assert card.active_target == Decimal("0.454438")
    assert card.target_level_statuses[0].lifecycle_state in {"UPCOMING", "NEAR"}
    assert card.target_level_statuses[1].lifecycle_state == "UPCOMING"


def test_price_exactly_at_first_target_advances_to_second_target() -> None:
    card = _make_card(current_price="0.454438", fib_ext=_wld_fib_ext())
    assert card.active_target == Decimal("0.515600")
    assert card.target_level_statuses[0].lifecycle_state == "REACHED"
    assert card.target_level_statuses[0].is_active_target is False


def test_price_between_targets_uses_second_target_distance() -> None:
    card = _make_card(current_price="0.500000", fib_ext=_wld_fib_ext())
    assert card.active_target == Decimal("0.515600")
    assert card.distance_to_target_pct is not None
    assert card.distance_to_target_pct > 0
    assert card.target_level_statuses[0].lifecycle_state == "PASSED"


def test_price_above_all_targets_has_no_active_target() -> None:
    card = _make_card(current_price="0.530000", fib_ext=_wld_fib_ext())
    assert card.active_target is None
    assert card.target_level_statuses[0].lifecycle_state == "PASSED"
    assert card.target_level_statuses[1].lifecycle_state == "PASSED"


def test_multiple_orders_near_only_one_target_are_scoped_per_level() -> None:
    card = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        sell_orders=(
            _FakeOrder("0.454500", side="sell"),
            _FakeOrder("0.454300", side="sell"),
        ),
    )
    first_level = card.target_level_statuses[0]
    second_level = card.target_level_statuses[1]
    assert first_level.matching_open_sell_orders == 2
    assert second_level.matching_open_sell_orders == 0
    assert any("sell @ 0.515600" in item for item in card.order_summary.missing_suggested)


def test_passed_level_without_fill_evidence_is_marked_missed() -> None:
    card = _make_card(current_price="0.458790", fib_ext=_wld_fib_ext())
    first_level = card.target_level_statuses[0]
    assert first_level.lifecycle_state == "PASSED"
    assert first_level.coverage_state == "PASSED_UNFILLED"
    assert any("missed sell level @ 0.454438" in item for item in card.order_summary.missing_suggested)


def test_filled_and_completed_level_evidence_are_displayed() -> None:
    filled = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        filled_sell_levels=(Decimal("0.454438"),),
    )
    completed = _make_card(
        current_price="0.530000",
        fib_ext=_wld_fib_ext(),
        completed_sell_levels=(Decimal("0.454438"),),
    )
    assert filled.target_level_statuses[0].lifecycle_state == "REACHED_FILLED"
    assert completed.target_level_statuses[0].lifecycle_state == "COMPLETED"


def test_profit_plan_runner_scopes_output_per_account_and_prevents_cross_account_leakage() -> None:
    original_parse_args = profit_plan_runner.parse_args
    original_load_context = profit_plan_runner.load_account_scoped_short_dashboard_context
    original_resolve_access = profit_plan_runner.resolve_dashboard_profile_access
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fib_rows = root / "fibo_target_map_rows_v1.csv"
            fib_rows.write_text(
                "\n".join([
                    "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price",
                    "BTC,100000,80000,96000,96000,90000",
                    "WLD,0.48,0.30,0.38,0.38,0.33",
                    "ETH,2200,1800,2100,2100,1950",
                ]) + "\n",
                encoding="utf-8",
            )

            joost_context = _context(
                profile="joost",
                account_id=11,
                markets=("BTC-EUR", "WLD-EUR"),
                orders=(
                    BrokerOrderRow(
                        order_id="sell-1",
                        market="BTC-EUR",
                        side="sell",
                        order_type="limit",
                        limit_price=Decimal("105000"),
                        amount=Decimal("0.1"),
                        filled_amount=Decimal("0"),
                        remaining_amount=Decimal("0.1"),
                        status="new",
                        created_at_ms=1,
                    ),
                ),
                balances=(BrokerBalanceRow(symbol="BTC", available=Decimal("0.1"), in_order=Decimal("0")),),
                prices={"BTC-EUR": "100000", "WLD-EUR": "0.48"},
            )
            hugo_context = _context(
                profile="hugo",
                account_id=22,
                markets=("BTC-EUR", "ETH-EUR"),
                orders=(),
                balances=(BrokerBalanceRow(symbol="ETH", available=Decimal("2"), in_order=Decimal("0")),),
                prices={"BTC-EUR": "100000", "ETH-EUR": "2200"},
            )

            def _run_for(profile: str, context: AccountScopedShortDashboardContext) -> tuple[str, dict[str, object]]:
                profit_plan_runner.parse_args = lambda: type(
                    "Args",
                    (),
                    {
                        "account_profile": profile,
                        "account_code": None,
                        "venue": "bitvavo",
                        "output_root": str(root),
                        "output_html": None,
                        "output_json": None,
                        "monitor_href": None,
                        "fib_map_rows": str(fib_rows),
                        "swing_anchors": [],
                        "recent_lows": [],
                        "output": "none",
                    },
                )()
                profit_plan_runner.resolve_dashboard_profile_access = lambda **_: type(
                    "Access",
                    (),
                    {
                        "account_profile": profile,
                        "venue": "bitvavo",
                        "trading_account_stable_ref": context.account_code,
                    },
                )()
                profit_plan_runner.load_account_scoped_short_dashboard_context = lambda **_: context
                assert profit_plan_runner.main() == 0
                html_path = root / "accounts" / profile / "profit-plan.html"
                json_path = root / "accounts" / profile / "profit-plan.json"
                return html_path.read_text(encoding="utf-8"), json.loads(json_path.read_text(encoding="utf-8"))

            joost_html, joost_json = _run_for("joost", joost_context)
            hugo_html, hugo_json = _run_for("hugo", hugo_context)

            assert "BTC" in joost_html and "BTC" in hugo_html
            assert "WLD" in joost_html and "WLD" not in hugo_html
            assert "ETH" in hugo_html and "ETH" not in joost_html
            assert "/synth/accounts/joost/wallet.html" in joost_html
            assert "/synth/accounts/joost/profit-plan.html" in joost_html
            assert "/synth/accounts/joost/open-orders-monitor.html" in joost_html
            assert "/synth/accounts/hugo/wallet.html" in hugo_html
            assert "/synth/accounts/hugo/profit-plan.html" in hugo_html
            assert "/synth/accounts/hugo/open-orders-monitor.html" in hugo_html
            assert "/synth/profit-plan.html" not in joost_html
            assert "/synth/open-orders-monitor.html" not in joost_html
            assert {row["market"] for row in joost_json["symbols"]} == {"BTC-EUR", "WLD-EUR"}
            assert {row["market"] for row in hugo_json["symbols"]} == {"BTC-EUR", "ETH-EUR"}
    finally:
        profit_plan_runner.parse_args = original_parse_args
        profit_plan_runner.load_account_scoped_short_dashboard_context = original_load_context
        profit_plan_runner.resolve_dashboard_profile_access = original_resolve_access


def test_profit_plan_runner_missing_account_fails_closed() -> None:
    original_parse_args = profit_plan_runner.parse_args
    original_load_context = profit_plan_runner.load_account_scoped_short_dashboard_context
    original_resolve_access = profit_plan_runner.resolve_dashboard_profile_access
    try:
        profit_plan_runner.parse_args = lambda: type(
            "Args",
            (),
            {
                "account_profile": "joost",
                "venue": "bitvavo",
                "output_root": "/tmp",
                "output_html": None,
                "output_json": None,
                "monitor_href": None,
                "fib_map_rows": "/tmp/missing-fib-map.csv",
                "swing_anchors": [],
                "recent_lows": [],
                "output": "none",
            },
        )()
        profit_plan_runner.resolve_dashboard_profile_access = lambda **_: (_ for _ in ()).throw(
            RuntimeError(f"{profile_access.PROFILE_HAS_NO_ACCOUNT_ACCESS}: profile=hugo venue=bitvavo")
        )
        profit_plan_runner.load_account_scoped_short_dashboard_context = lambda **_: (_ for _ in ()).throw(
            RuntimeError("trading_account missing")
        )
        assert profit_plan_runner.main() == 1
    finally:
        profit_plan_runner.parse_args = original_parse_args
        profit_plan_runner.load_account_scoped_short_dashboard_context = original_load_context
        profit_plan_runner.resolve_dashboard_profile_access = original_resolve_access


def test_runner_source_does_not_construct_account_code_from_profile_name() -> None:
    source = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    assert "bitvavo_{args.account_profile}_read" not in source
    assert "default_account_code" not in source


def main() -> None:
    tests = [
        test_pure_module_has_no_forbidden_imports,
        test_runner_has_no_broker_or_execution_imports,
        test_load_zone_contexts_uses_source_rows_without_manual_cli,
        test_load_zone_contexts_manual_cli_overrides_missing_source,
        test_load_zone_contexts_missing_source_fails_closed,
        test_load_zone_contexts_symbol_missing_fails_closed,
        test_take_profit_waiting_when_target_is_near_and_sell_order_exists,
        test_reload_zone_approaching_when_price_is_near_reload_zone,
        test_price_ran_away_when_price_is_far_above_target_assumptions,
        test_invalidation_near_when_price_approaches_risk_zone,
        test_order_too_far_or_stale_when_open_orders_are_far,
        test_do_nothing_for_neutral_valid_state,
        test_insufficient_data_when_zones_are_missing,
        test_stale_current_price_blocks_actionable_profit_plan_outputs,
        test_render_full_html_uses_profit_plan_title_and_public_monitor_href,
        test_json_snapshot_structure_and_safety_markers,
        test_wld_fixture_advances_active_target_and_does_not_mark_passed_level_missing,
        test_price_below_first_target_keeps_first_target_active,
        test_price_exactly_at_first_target_advances_to_second_target,
        test_price_between_targets_uses_second_target_distance,
        test_price_above_all_targets_has_no_active_target,
        test_multiple_orders_near_only_one_target_are_scoped_per_level,
        test_passed_level_without_fill_evidence_is_marked_missed,
        test_filled_and_completed_level_evidence_are_displayed,
        test_profit_plan_runner_scopes_output_per_account_and_prevents_cross_account_leakage,
        test_profit_plan_runner_missing_account_fails_closed,
        test_runner_source_does_not_construct_account_code_from_profile_name,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
