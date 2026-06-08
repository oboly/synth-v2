from __future__ import annotations

import ast
import json
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.market_data.native_short_fib_context_v1 import NativeShortContextRow, write_context_rows
import src.reporting.run_manual_short_trader_profit_plan_v1 as profit_plan_runner
import src.reporting.account_dashboard_profile_access_v1 as profile_access
from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot
from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountScopedShortDashboardContext
from src.reporting.manual_short_trader_dashboard_v1 import BrokerBalanceRow, BrokerOrderRow
from src.reporting.manual_short_trader_profit_plan_v1 import (
    FibExtContext,
    ProfitPlanCard,
    ReentryContext,
    TargetHistoryCandle,
    build_card_search_text,
    build_json_snapshot,
    build_profit_plan_card,
    filter_cards_for_view,
    render_full_html,
    render_plan_card,
)


def _wld_fib_ext(price_band: str = "BETWEEN_1272_1618") -> FibExtContext:
    return FibExtContext(
        local_reaction_price=Decimal("0.399040"),
        anchor_end_ts_utc=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
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


def _native_short_row(
    *,
    symbol: str = "WLD",
    status: str = "NATIVE_SHORT_CONTEXT_AVAILABLE",
) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol,
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=status,
        map_cycle_id=f"{symbol}|SHORT|4h|demo",
        anchor_start_ts_utc=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        anchor_end_ts_utc=datetime(2026, 6, 2, 0, 0, tzinfo=UTC),
        anchor_low_price=Decimal("0.3000"),
        anchor_high_price=Decimal("0.3800"),
        breakout_gate_price=Decimal("0.3800"),
        latest_primary_close_ts_utc=datetime(2026, 6, 5, 8, 0, tzinfo=UTC),
        latest_support_close_ts_utc=datetime(2026, 6, 5, 11, 0, tzinfo=UTC),
        latest_primary_close_price=Decimal("0.4700"),
        ext_1_272_price=Decimal("0.454438"),
        ext_1_618_price=Decimal("0.515600"),
        ext_2_000_price=Decimal("0.6200"),
        active_target_levels=(Decimal("0.515600"), Decimal("0.6200")),
        previous_target_levels=(Decimal("0.454438"),),
        reload_r382_price=Decimal("0.3494"),
        reload_r500_price=Decimal("0.3400"),
        reload_r618_price=Decimal("0.3306"),
        reload_r786_price=Decimal("0.3171"),
        invalidation_price=Decimal("0.3000"),
        primary_4h_lifecycle_state="ACTIVE_4H_EXTENSION",
        supporting_1h_state="ALIGNED_WITH_4H",
        context_freshness_status="FRESH",
        max_primary_high_since_anchor=Decimal("0.4700"),
        min_primary_low_since_anchor=Decimal("0.3300"),
        source_name="native_short_fib_context_v1",
        source_version="0.1",
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
        current_map_status="CURRENT_ACTIVE_MAP",
        previous_map_cycle_id="",
        previous_map_lifecycle_state="",
        rollover_state="SINGLE_MAP",
        selection_reason="Single active map selected",
    )


class _FakeOrder:
    def __init__(self, price: str, side: str = "buy", created_at_ms: int | None = None) -> None:
        self.limit_price = Decimal(price)
        self.side = side
        self.created_at_ms = created_at_ms


def _make_card(
    *,
    current_price: str | None,
    short_context_input_status: str = "HAS_ZONE_CONTEXT",
    short_context_coverage_status: str = "NATIVE_SHORT_CONTEXT_AVAILABLE",
    short_context_display_state: str = "NO_NATIVE_SHORT_FIB_CONTEXT",
    fib_ext: FibExtContext | None = None,
    reentry: ReentryContext | None = None,
    buy_orders: tuple[_FakeOrder, ...] = (),
    sell_orders: tuple[_FakeOrder, ...] = (),
    filled_sell_levels: tuple[Decimal, ...] = (),
    completed_sell_levels: tuple[Decimal, ...] = (),
    history_high_since_activation: Decimal | None = None,
    history_low_since_activation: Decimal | None = None,
    history_candles_since_activation: tuple[TargetHistoryCandle, ...] = (),
    symbol: str = "WLD",
    market: str = "WLD-EUR",
) -> ProfitPlanCard:
    return build_profit_plan_card(
        symbol=symbol,
        market=market,
        current_price=Decimal(current_price) if current_price is not None else None,
        fib_trading_horizon="SHORT",
        short_context_input_status=short_context_input_status,
        short_context_coverage_status=short_context_coverage_status,
        short_context_display_state=short_context_display_state,
        fib_ext=fib_ext,
        reentry=reentry,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        filled_sell_levels=filled_sell_levels,
        completed_sell_levels=completed_sell_levels,
        history_high_since_activation=history_high_since_activation,
        history_low_since_activation=history_low_since_activation,
        history_candles_since_activation=history_candles_since_activation,
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
            native_short_rows_path=Path("/tmp/missing-native-short-context.csv"),
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "HAS_ZONE_CONTEXT"
        assert result.coverage_status_by_symbol["WLD"] == "LEGACY_1D_CONTEXT_ONLY"
        assert result.display_state_by_symbol["WLD"] == "NO_NATIVE_SHORT_FIB_CONTEXT"


def test_load_zone_contexts_prefers_native_short_rows() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "\n".join([
                "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price",
                "WLD,0.48,0.30,0.38,0.38,0.33",
            ]) + "\n",
            encoding="utf-8",
        )
        native_dir = Path(tmpdir) / "native"
        native_paths = write_context_rows(rows=[_native_short_row()], output_dir=native_dir)
        result = profit_plan_runner.load_zone_contexts(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("0.48")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "NATIVE_SHORT_CONTEXT_AVAILABLE"
        assert result.coverage_status_by_symbol["WLD"] == "NATIVE_SHORT_CONTEXT_AVAILABLE"
        assert result.display_state_by_symbol["WLD"] == "HAS_NATIVE_SHORT_FIB_CONTEXT"
        assert result.fib_ext_by_symbol["WLD"].ext_1_618 == Decimal("0.515600")


def test_load_zone_contexts_keeps_partial_native_gap_truthful_even_with_legacy_row() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "\n".join([
                "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price",
                "WLD,0.48,0.30,0.38,0.38,0.33",
            ]) + "\n",
            encoding="utf-8",
        )
        native_dir = Path(tmpdir) / "native"
        native_paths = write_context_rows(
            rows=[_native_short_row(status="INSUFFICIENT_1H_HISTORY")],
            output_dir=native_dir,
        )
        result = profit_plan_runner.load_zone_contexts(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("0.48")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "INSUFFICIENT_1H_HISTORY"
        assert result.coverage_status_by_symbol["WLD"] == "INSUFFICIENT_1H_HISTORY"
        assert result.display_state_by_symbol["WLD"] == "NO_NATIVE_SHORT_FIB_CONTEXT"
        assert result.fib_ext_by_symbol["WLD"].ext_1_618 == Decimal("0.515600")


def test_partial_native_row_with_incomplete_map_does_not_produce_actionable_plan() -> None:
    """Partial native row (INSUFFICIENT_4H_HISTORY, no ext prices) must fail closed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "\n".join([
                "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price",
                "WLD,0.48,0.30,0.38,0.38,0.33",
            ]) + "\n",
            encoding="utf-8",
        )
        native_dir = Path(tmpdir) / "native"
        # INSUFFICIENT_4H_HISTORY row: all ext prices are None (no candidate built)
        insufficient_row = NativeShortContextRow(
            symbol="WLD",
            venue="bitvavo",
            quote_currency="EUR",
            fib_trading_horizon="SHORT",
            primary_interval="4h",
            supporting_interval="1h",
            context_status="INSUFFICIENT_4H_HISTORY",
            map_cycle_id="",
            anchor_start_ts_utc=None,
            anchor_end_ts_utc=None,
            anchor_low_price=None,
            anchor_high_price=None,
            breakout_gate_price=None,
            latest_primary_close_ts_utc=None,
            latest_support_close_ts_utc=None,
            latest_primary_close_price=None,
            ext_1_272_price=None,
            ext_1_618_price=None,
            ext_2_000_price=None,
            active_target_levels=(),
            previous_target_levels=(),
            reload_r382_price=None,
            reload_r500_price=None,
            reload_r618_price=None,
            reload_r786_price=None,
            invalidation_price=None,
            primary_4h_lifecycle_state="UNKNOWN",
            supporting_1h_state="UNKNOWN",
            context_freshness_status="UNKNOWN",
            max_primary_high_since_anchor=None,
            min_primary_low_since_anchor=None,
            source_name="native_short_fib_context_v1",
            source_version="0.1",
            source_primary_ref="obs_market_candle:4h",
            source_support_ref="obs_market_candle:1h",
            current_map_status="NO_VALID_MAP",
            previous_map_cycle_id="",
            previous_map_lifecycle_state="",
            rollover_state="NO_VALID_MAP",
            selection_reason="",
        )
        native_paths = write_context_rows(rows=[insufficient_row], output_dir=native_dir)
        result = profit_plan_runner.load_zone_contexts(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("0.48")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "INSUFFICIENT_4H_HISTORY"
        assert result.coverage_status_by_symbol["WLD"] == "INSUFFICIENT_4H_HISTORY"
        assert result.display_state_by_symbol["WLD"] == "NO_NATIVE_SHORT_FIB_CONTEXT"
        # No fib_ext: incomplete native must not produce active map or actionable levels
        assert result.fib_ext_by_symbol.get("WLD") is None


def test_partial_native_row_card_is_non_actionable() -> None:
    """Card built from partial native context must not emit actionable BUY/SELL guidance."""
    card = _make_card(
        current_price="0.48",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="INSUFFICIENT_1H_HISTORY",
        short_context_coverage_status="INSUFFICIENT_1H_HISTORY",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
    )
    actionable = {"BUY_DIP", "TAKE_PROFIT_NEAR", "BREAKOUT_WATCH", "REBUY_ZONE_NEAR"}
    assert card.action_label not in actionable, (
        f"Partial native card must not emit actionable label; got: {card.action_label}"
    )
    assert card.is_relevant is False
    assert card.primary_state == "NO_NATIVE_SHORT_FIB_CONTEXT"


def test_no_native_row_legacy_path_unchanged() -> None:
    """No native row: legacy 1d path must continue to work as before."""
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
            native_short_rows_path=Path("/tmp/missing-native-short-context.csv"),
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "HAS_ZONE_CONTEXT"
        assert result.coverage_status_by_symbol["WLD"] == "LEGACY_1D_CONTEXT_ONLY"
        assert result.display_state_by_symbol["WLD"] == "NO_NATIVE_SHORT_FIB_CONTEXT"
        # Legacy fib_ext IS populated (existing behavior unchanged)
        assert result.fib_ext_by_symbol.get("WLD") is not None


def test_load_zone_contexts_manual_cli_overrides_missing_source() -> None:
    result = profit_plan_runner.load_zone_contexts(
        markets=["WLD-EUR"],
        prices={"WLD-EUR": Decimal("0.48")},
        swing_anchors={"WLD": ["0.30", "0.38"]},
        recent_lows={"WLD": ["0.33"]},
        native_short_rows_path=Path("/tmp/missing-native-short-context.csv"),
        fib_map_rows_path=Path("/tmp/missing-fib-map.csv"),
    )
    assert result.input_status_by_symbol["WLD"] == "MANUAL_ZONE_CONTEXT_USED"
    assert result.display_state_by_symbol["WLD"] == "NO_NATIVE_SHORT_FIB_CONTEXT"


def test_load_zone_contexts_missing_source_fails_closed() -> None:
    result = profit_plan_runner.load_zone_contexts(
        markets=["WLD-EUR"],
        prices={"WLD-EUR": Decimal("0.48")},
        swing_anchors={},
        recent_lows={},
        native_short_rows_path=Path("/tmp/missing-native-short-context.csv"),
        fib_map_rows_path=Path("/tmp/missing-fib-map.csv"),
    )
    assert result.input_status_by_symbol["WLD"] == "ZONE_SOURCE_MISSING"
    assert result.coverage_status_by_symbol["WLD"] == "FIB_MAP_SOURCE_MISSING"


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
            native_short_rows_path=Path("/tmp/missing-native-short-context.csv"),
            fib_map_rows_path=fib_rows,
        )
        assert result.input_status_by_symbol["WLD"] == "ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING"
        assert result.coverage_status_by_symbol["WLD"] == "FIB_MAP_SYMBOL_MISSING"


def test_short_context_coverage_summary_counts_expected_buckets() -> None:
    summary = profit_plan_runner.summarize_short_context_coverage(
        markets=["WLD-EUR", "ONDO-EUR", "PLUME-EUR", "HOME-EUR"],
        coverage_status_by_symbol={
            "WLD": "LEGACY_1D_CONTEXT_ONLY",
            "ONDO": "CONTEXT_INVALID_OR_STALE",
            "PLUME": "FIB_MAP_SYMBOL_MISSING",
            "HOME": "MARKET_DATA_MISSING",
        },
    )
    assert summary["NATIVE_SHORT_CONTEXT_AVAILABLE"] == 0
    assert summary["LEGACY_1D_CONTEXT_ONLY"] == 1
    assert summary["FIB_MAP_SYMBOL_MISSING"] == 1
    assert summary["MARKET_DATA_MISSING"] == 1
    assert summary["CONTEXT_INVALID_OR_STALE"] == 1


def test_load_zone_contexts_market_data_missing_is_truthful() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "\n".join([
                "symbol,target_status,anchor_reason,current_price,swing_low_price,swing_high_price,local_reaction_price",
                "PLUME,MISSING_MARKET_DATA,no_market_candles_found_for_symbol,,,,",
            ]) + "\n",
            encoding="utf-8",
        )
        result = profit_plan_runner.load_zone_contexts(
            markets=["PLUME-EUR"],
            prices={"PLUME-EUR": Decimal("0.155")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=Path("/tmp/missing-native-short-context.csv"),
            fib_map_rows_path=fib_rows,
        )
        assert result.coverage_status_by_symbol["PLUME"] == "MARKET_DATA_MISSING"
        assert result.display_state_by_symbol["PLUME"] == "MARKET_DATA_MISSING"


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


def test_map_recompute_needed_when_price_is_above_all_completed_targets() -> None:
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=(
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.4700"),
                low_price=Decimal("0.4300"),
            ),
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 4, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.7600"),
                low_price=Decimal("0.5000"),
            ),
        ),
    )
    assert card.all_sell_targets_completed is True
    assert card.active_target is None
    assert card.target_exit_zone == ()
    assert card.scenario_type == "MAP_COMPLETED"
    assert card.primary_state == "MAP_RECOMPUTE_NEEDED"
    assert card.action_label == "WAIT_FOR_NEW_MAP"
    assert card.primary_state != "PRICE_RAN_AWAY"


def test_invalidation_near_when_price_approaches_risk_zone() -> None:
    fib = FibExtContext(
        local_reaction_price=Decimal("0.399040"),
        anchor_end_ts_utc=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
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


def test_plume_without_fib_row_shows_truthful_short_context_gap() -> None:
    card = _make_card(
        current_price="0.155000",
        fib_ext=None,
        reentry=None,
        short_context_input_status="ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING",
        short_context_coverage_status="FIB_MAP_SYMBOL_MISSING",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        symbol="PLUME",
        market="PLUME-EUR",
    )
    assert card.primary_state == "NO_NATIVE_SHORT_FIB_CONTEXT"
    assert card.primary_state != "INSUFFICIENT_DATA"
    assert card.current_price == Decimal("0.155000")
    assert card.short_context_coverage_status == "FIB_MAP_SYMBOL_MISSING"


def test_legacy_1d_context_cannot_masquerade_as_native_short_action() -> None:
    card = _make_card(
        current_price="0.48",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="HAS_ZONE_CONTEXT",
        short_context_coverage_status="LEGACY_1D_CONTEXT_ONLY",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert card.scenario_type == "LEGACY_CONTEXT_REFERENCE_ONLY"
    assert card.action_label == "MANUAL_REVIEW"
    assert card.primary_state == "NO_NATIVE_SHORT_FIB_CONTEXT"
    assert card.is_relevant is False
    assert card.action_label not in {"TAKE_PROFIT_NEAR", "BUY_DIP", "WAIT_FOR_NEW_MAP"}
    assert card.scenario_type != "EXTENSION_RUNNER"
    assert any("reference only" in reason.lower() for reason in card.reasons)
    assert card.target_level_statuses


def test_all_candidates_search_matches_plu_to_plume_and_clear_restores_all() -> None:
    plume = _make_card(
        current_price="0.155000",
        fib_ext=None,
        reentry=None,
        short_context_input_status="ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING",
        short_context_coverage_status="FIB_MAP_SYMBOL_MISSING",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        symbol="PLUME",
        market="PLUME-EUR",
    )
    wld = _make_card(current_price="0.48", fib_ext=_wld_fib_ext())
    assert "plume" in build_card_search_text(plume)
    filtered = filter_cards_for_view([plume, wld], mode="all", query="PLU")
    assert [card.symbol for card in filtered] == ["PLUME"]
    restored = filter_cards_for_view([plume, wld], mode="all", query="")
    assert [card.symbol for card in restored] == ["PLUME", "WLD"]


def test_legacy_1d_context_is_not_relevant_only_from_legacy_levels() -> None:
    legacy = _make_card(
        current_price="0.48",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="HAS_ZONE_CONTEXT",
        short_context_coverage_status="LEGACY_1D_CONTEXT_ONLY",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
    )
    visible_all = filter_cards_for_view([legacy], mode="all", query="")
    visible_relevant = filter_cards_for_view([legacy], mode="relevant", query="")
    assert [card.symbol for card in visible_all] == ["WLD"]
    assert visible_relevant == []


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
        storage_scope="joost",
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
    assert "candidate-search" in html
    assert "ppView:joost" in html
    assert "ppQuery:joost" in html
    assert "search-shell" in html
    assert "no-results" in html
    assert "Matching 0 of 0" in html
    assert "shell.style.display = mode === 'all' ? 'flex' : 'none'" in html


def test_json_snapshot_structure_and_safety_markers() -> None:
    card = _make_card(current_price="0.48", fib_ext=_wld_fib_ext())
    snapshot = build_json_snapshot([card], broker_mode="db_snapshot")
    assert snapshot["broker_writes"] == 0
    assert snapshot["order_submission"] == 0
    assert snapshot["executor"] == "none"
    assert snapshot["symbols"][0]["primary_state"] == card.primary_state
    assert snapshot["symbols"][0]["short_context_coverage_status"] == card.short_context_coverage_status
    assert snapshot["symbols"][0]["fib_trading_horizon"] == "SHORT"
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
        history_high_since_activation=Decimal("0.470000"),
    )
    assert card.active_target == Decimal("0.515600")
    assert card.distance_to_target_pct is not None
    assert card.distance_to_target_pct > 0
    assert all("missing sell @ 0.454438" not in item for item in card.order_summary.missing_suggested)
    first_level = card.target_level_statuses[0]
    second_level = card.target_level_statuses[1]
    third_level = card.target_level_statuses[2]
    assert first_level.level == Decimal("0.399040")
    assert first_level.lifecycle_state == "PASSED"
    assert second_level.level == Decimal("0.454438")
    assert second_level.lifecycle_state == "PASSED"
    assert second_level.coverage_state == "OPEN_ORDER_AFTER_PASSED_LEVEL"
    assert third_level.level == Decimal("0.515600")
    assert third_level.is_active_target is True
    assert third_level.matching_open_sell_orders == 1
    assert Decimal("0.399040") not in card.target_exit_zone
    assert Decimal("0.454438") not in card.target_exit_zone
    assert Decimal("0.515600") in card.target_exit_zone


def test_history_aware_wld_pullback_does_not_regress_target_lifecycle() -> None:
    card = _make_card(
        current_price="0.452410",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.470000"),
    )
    assert card.active_target == Decimal("0.515600")
    assert card.target_level_statuses[1].level == Decimal("0.454438")
    assert card.target_level_statuses[1].lifecycle_state == "PASSED"
    assert card.target_level_statuses[1].retest_context == "PULLBACK_BELOW_PASSED_LEVEL"
    assert Decimal("0.399040") not in card.target_exit_zone
    assert Decimal("0.454438") not in card.target_exit_zone
    assert tuple(card.target_exit_zone) == (Decimal("0.515600"),)
    assert all("missing: missed sell level" not in item for item in card.order_summary.missing_suggested)


def test_price_below_first_target_keeps_first_target_active_without_history_touch() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    assert card.active_target == Decimal("0.454438")
    assert card.target_level_statuses[1].lifecycle_state in {"UPCOMING", "NEAR"}
    assert card.target_level_statuses[2].lifecycle_state == "UPCOMING"


def test_price_exactly_at_first_target_advances_to_second_target() -> None:
    card = _make_card(current_price="0.454438", fib_ext=_wld_fib_ext(), history_high_since_activation=Decimal("0.454438"))
    assert card.active_target == Decimal("0.515600")
    assert card.target_level_statuses[1].lifecycle_state == "REACHED"
    assert card.target_level_statuses[1].is_active_target is False


def test_price_between_targets_uses_second_target_distance() -> None:
    card = _make_card(current_price="0.500000", fib_ext=_wld_fib_ext(), history_high_since_activation=Decimal("0.500000"))
    assert card.active_target == Decimal("0.515600")
    assert card.distance_to_target_pct is not None
    assert card.distance_to_target_pct > 0
    assert card.target_level_statuses[1].lifecycle_state == "PASSED"


def test_price_above_all_targets_has_no_active_target() -> None:
    card = _make_card(current_price="0.530000", fib_ext=_wld_fib_ext(), history_high_since_activation=Decimal("0.530000"))
    assert card.active_target is None
    assert card.target_level_statuses[1].lifecycle_state == "PASSED"
    assert card.target_level_statuses[2].lifecycle_state == "PASSED"


def test_completed_map_synchronizes_scenario_and_state() -> None:
    card = _make_card(
        current_price="0.468850",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.543160"),
        history_candles_since_activation=(
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.470000"),
                low_price=Decimal("0.430000"),
            ),
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 4, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.543160"),
                low_price=Decimal("0.460000"),
            ),
        ),
    )
    assert card.all_sell_targets_completed is True
    assert card.active_target is None
    assert card.target_exit_zone == ()
    assert card.scenario_type == "MAP_COMPLETED"
    assert card.primary_state == "POST_EXTENSION_PULLBACK"
    assert card.action_label == "WAIT_FOR_NEW_MAP"
    assert card.suggested_manual_attention_label == "Post-extension pullback"
    assert card.primary_state != "TAKE_PROFIT_WAITING"
    assert card.primary_state != "PRICE_RAN_AWAY"


def test_order_before_cross_is_marked_missed_order() -> None:
    card = _make_card(
        current_price="0.452410",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.470000"),
        history_candles_since_activation=(
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.470000"),
                low_price=Decimal("0.440000"),
            ),
        ),
        sell_orders=(
            _FakeOrder("0.454438", side="sell", created_at_ms=int(datetime(2026, 6, 3, 15, 0, tzinfo=UTC).timestamp() * 1000)),
        ),
    )
    assert card.target_level_statuses[1].coverage_state == "MISSED_ORDER"
    assert any("missed sell level @ 0.454438" in item for item in card.order_summary.missing_suggested)


def test_multiple_orders_near_only_one_target_are_scoped_per_level() -> None:
    card = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        sell_orders=(
            _FakeOrder("0.454500", side="sell"),
            _FakeOrder("0.454300", side="sell"),
        ),
        history_high_since_activation=Decimal("0.470000"),
    )
    first_level = card.target_level_statuses[1]
    second_level = card.target_level_statuses[2]
    assert first_level.matching_open_sell_orders == 2
    assert second_level.matching_open_sell_orders == 0
    assert any("sell @ 0.515600" in item for item in card.order_summary.missing_suggested)


def test_passed_level_without_fill_evidence_is_marked_missed() -> None:
    card = _make_card(
        current_price="0.452410",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.470000"),
    )
    first_level = card.target_level_statuses[1]
    assert first_level.lifecycle_state == "PASSED"
    assert first_level.coverage_state == "PASSED_UNFILLED"
    assert any("missed sell level @ 0.454438" in item for item in card.order_summary.missing_suggested)


def test_filled_and_completed_level_evidence_are_displayed() -> None:
    filled = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        filled_sell_levels=(Decimal("0.454438"),),
        history_high_since_activation=Decimal("0.470000"),
    )
    completed = _make_card(
        current_price="0.530000",
        fib_ext=_wld_fib_ext(),
        completed_sell_levels=(Decimal("0.454438"),),
        history_high_since_activation=Decimal("0.530000"),
    )
    assert filled.target_level_statuses[1].lifecycle_state == "REACHED_FILLED"
    assert completed.target_level_statuses[1].lifecycle_state == "COMPLETED"


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
                        "native_short_context_rows": "/tmp/missing-native-short-context.csv",
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
                "native_short_context_rows": "/tmp/missing-native-short-context.csv",
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


# ---------------------------------------------------------------------------
# Semantic state field tests (v2 redesign)
# ---------------------------------------------------------------------------


def test_setup_state_extension_setup_for_extension_runner() -> None:
    card = _make_card(current_price="0.48", fib_ext=_wld_fib_ext())
    assert card.setup_state == "EXTENSION_SETUP"


def test_setup_state_reentry_setup_for_reentry_wait() -> None:
    card = _make_card(current_price="0.2500", reentry=_fet_reentry())
    assert card.setup_state == "REENTRY_SETUP"


def test_setup_state_map_completed_for_completed_map() -> None:
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=(
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.7600"),
                low_price=Decimal("0.5000"),
            ),
        ),
    )
    assert card.setup_state == "MAP_COMPLETED"


def test_setup_state_minimal_context_for_no_context() -> None:
    card = _make_card(
        current_price="0.155000",
        fib_ext=None,
        reentry=None,
        short_context_input_status="ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING",
        short_context_coverage_status="FIB_MAP_SYMBOL_MISSING",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        symbol="PLUME",
        market="PLUME-EUR",
    )
    assert card.setup_state == "MINIMAL_CONTEXT"


def test_event_state_target_approaching_for_take_profit_waiting() -> None:
    card = _make_card(
        current_price="0.5120",
        fib_ext=_wld_fib_ext(),
        sell_orders=(_FakeOrder("0.515600", side="sell"),),
    )
    assert card.primary_state == "TAKE_PROFIT_WAITING"
    assert card.event_state == "TARGET_APPROACHING"


def test_event_state_reload_zone_approaching_for_approaching_reentry() -> None:
    card = _make_card(current_price="0.2100", reentry=_fet_reentry())
    assert card.primary_state == "RELOAD_ZONE_APPROACHING"
    assert card.event_state == "RELOAD_ZONE_APPROACHING"


def test_event_state_map_expired_for_completed_map() -> None:
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=(
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 4, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.7600"),
                low_price=Decimal("0.5000"),
            ),
        ),
    )
    assert card.event_state == "MAP_EXPIRED"


def test_event_state_between_levels_for_do_nothing() -> None:
    card = _make_card(current_price="0.2500", reentry=_fet_reentry())
    assert card.primary_state == "DO_NOTHING"
    assert card.event_state == "BETWEEN_LEVELS"


def test_event_state_context_unavailable_for_stale_price() -> None:
    card = build_profit_plan_card(
        symbol="HOME",
        market="HOME-EUR",
        current_price=Decimal("1.30"),
        current_price_status="STALE_CURRENT_PRICE",
        current_price_age_min=Decimal("2880"),
        fib_ext=_wld_fib_ext(),
    )
    assert card.event_state == "CONTEXT_UNAVAILABLE"
    assert card.is_relevant is False


def test_event_state_context_unavailable_for_short_context_gap() -> None:
    card = _make_card(
        current_price="0.155000",
        fib_ext=None,
        reentry=None,
        short_context_input_status="ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING",
        short_context_coverage_status="FIB_MAP_SYMBOL_MISSING",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        symbol="PLUME",
        market="PLUME-EUR",
    )
    assert card.event_state == "CONTEXT_UNAVAILABLE"
    assert card.is_relevant is True
    assert "MINIMAL_CONTEXT" in card.relevance_reasons


def test_ladder_states_armed_when_all_active_targets_have_orders() -> None:
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        sell_orders=(
            _FakeOrder("0.454438", side="sell"),
            _FakeOrder("0.515600", side="sell"),
        ),
    )
    assert "LADDER_ARMED" in card.ladder_states
    assert "LADDER_MISSING" not in card.ladder_states


def test_ladder_states_missing_when_no_orders_at_active_target() -> None:
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        sell_orders=(),
    )
    assert "LADDER_MISSING" in card.ladder_states


def test_ladder_states_stale_orders_absent_for_moonbag_at_active_zone() -> None:
    """A sell order far above current price but at an UPCOMING target is ARMED, not STALE.
    This is the moonbag fix: aggregate max-distance check was wrong."""
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        sell_orders=(
            _FakeOrder("0.454438", side="sell"),
            _FakeOrder("0.515600", side="sell"),
        ),
    )
    assert "STALE_ORDERS_PRESENT" not in card.ladder_states
    assert "LADDER_ARMED" in card.ladder_states


def test_ladder_states_stale_present_for_order_matching_no_zone() -> None:
    card = _make_card(
        current_price="0.3000",
        reentry=_fet_reentry(),
        buy_orders=(_FakeOrder("0.1000"),),
    )
    assert "STALE_ORDERS_PRESENT" in card.ladder_states


def test_ladder_states_historical_order_does_not_trigger_stale() -> None:
    """A sell order near a PASSED target should be HISTORICAL, not STALE."""
    card = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.470000"),
        sell_orders=(
            _FakeOrder("0.454438", side="sell"),
            _FakeOrder("0.515600", side="sell"),
        ),
    )
    assert "STALE_ORDERS_PRESENT" not in card.ladder_states


def test_ladder_states_not_required_when_map_completed() -> None:
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=(
            TargetHistoryCandle(
                close_ts_utc=datetime(2026, 6, 4, 16, 0, tzinfo=UTC),
                high_price=Decimal("0.7600"),
                low_price=Decimal("0.5000"),
            ),
        ),
    )
    assert card.all_sell_targets_completed is True
    assert "LADDER_NOT_REQUIRED" in card.ladder_states


def test_reentry_wait_alone_without_orders_is_relevant_due_to_ladder_missing() -> None:
    """REENTRY_SETUP + BETWEEN_LEVELS + no orders → LADDER_MISSING → relevant.
    The card is relevant because orders are missing, not merely because of REENTRY_WAIT."""
    card = _make_card(current_price="0.2500", reentry=_fet_reentry())
    assert card.setup_state == "REENTRY_SETUP"
    assert card.event_state == "BETWEEN_LEVELS"
    assert "LADDER_MISSING" in card.ladder_states
    assert card.is_relevant is True
    assert "LADDER_MISSING" in card.relevance_reasons


def test_reentry_wait_with_armed_ladder_and_between_levels_is_not_relevant() -> None:
    """REENTRY_SETUP + BETWEEN_LEVELS + armed buy orders → not relevant.
    REENTRY_WAIT alone must not trigger relevance — only ladder/event state does."""
    r = _fet_reentry()
    card = _make_card(
        current_price="0.2500",
        reentry=r,
        buy_orders=(
            _FakeOrder(str(r.r382_price)),
            _FakeOrder(str(r.r500_price)),
        ),
    )
    assert card.setup_state == "REENTRY_SETUP"
    assert card.event_state == "BETWEEN_LEVELS"
    assert "LADDER_MISSING" not in card.ladder_states
    assert card.is_relevant is False


def test_relevance_reasons_populated_for_relevant_card() -> None:
    card = _make_card(current_price="0.2100", reentry=_fet_reentry())
    assert card.is_relevant is True
    assert len(card.relevance_reasons) > 0
    assert "RELOAD_ZONE_APPROACHING" in card.relevance_reasons


def test_relevance_reasons_empty_for_non_relevant_card() -> None:
    r = _fet_reentry()
    card = _make_card(
        current_price="0.2500",
        reentry=r,
        buy_orders=(
            _FakeOrder(str(r.r382_price)),
            _FakeOrder(str(r.r500_price)),
        ),
    )
    assert card.is_relevant is False
    assert card.relevance_reasons == ()


def test_json_snapshot_includes_new_semantic_fields() -> None:
    card = _make_card(current_price="0.48", fib_ext=_wld_fib_ext())
    snapshot = build_json_snapshot([card], broker_mode="db_snapshot")
    row = snapshot["symbols"][0]
    assert "setup_state" in row
    assert "event_state" in row
    assert "ladder_states" in row
    assert "relevance_reasons" in row
    assert isinstance(row["ladder_states"], list)
    assert isinstance(row["relevance_reasons"], list)


def test_html_does_not_show_wait_or_do_nothing_as_action_label() -> None:
    # missed_pct=None → deepest_touched_label=None → action_label="WAIT" → display "BETWEEN LEVELS"
    card = _make_card(current_price="0.2500", reentry=_fet_reentry(missed_pct=None))
    html = render_plan_card(card)
    assert ">WAIT<" not in html
    assert ">DO NOTHING<" not in html
    assert ">DO_NOTHING<" not in html
    assert "BETWEEN LEVELS" in html


def test_html_does_not_show_duplicate_active_target_field() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert html.count("Active target") <= 1


def test_setup_state_breakout_setup_for_breakout_retest() -> None:
    fib = FibExtContext(
        local_reaction_price=Decimal("0.399040"),
        anchor_end_ts_utc=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        ext_1_272=Decimal("0.49"),
        ext_1_618=Decimal("0.65"),
        ext_2_000=Decimal("0.80"),
        breakout_gate=Decimal("0.38"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=True,
    )
    card = _make_card(current_price="0.3750", fib_ext=fib)
    assert card.setup_state == "BREAKOUT_SETUP"


def main() -> None:
    tests = [
        test_pure_module_has_no_forbidden_imports,
        test_runner_has_no_broker_or_execution_imports,
        test_setup_state_extension_setup_for_extension_runner,
        test_setup_state_reentry_setup_for_reentry_wait,
        test_setup_state_map_completed_for_completed_map,
        test_setup_state_minimal_context_for_no_context,
        test_setup_state_breakout_setup_for_breakout_retest,
        test_event_state_target_approaching_for_take_profit_waiting,
        test_event_state_reload_zone_approaching_for_approaching_reentry,
        test_event_state_map_expired_for_completed_map,
        test_event_state_between_levels_for_do_nothing,
        test_event_state_context_unavailable_for_stale_price,
        test_event_state_context_unavailable_for_short_context_gap,
        test_ladder_states_armed_when_all_active_targets_have_orders,
        test_ladder_states_missing_when_no_orders_at_active_target,
        test_ladder_states_stale_orders_absent_for_moonbag_at_active_zone,
        test_ladder_states_stale_present_for_order_matching_no_zone,
        test_ladder_states_historical_order_does_not_trigger_stale,
        test_ladder_states_not_required_when_map_completed,
        test_reentry_wait_alone_without_orders_is_relevant_due_to_ladder_missing,
        test_reentry_wait_with_armed_ladder_and_between_levels_is_not_relevant,
        test_relevance_reasons_populated_for_relevant_card,
        test_relevance_reasons_empty_for_non_relevant_card,
        test_json_snapshot_includes_new_semantic_fields,
        test_html_does_not_show_wait_or_do_nothing_as_action_label,
        test_html_does_not_show_duplicate_active_target_field,
        test_load_zone_contexts_uses_source_rows_without_manual_cli,
        test_load_zone_contexts_manual_cli_overrides_missing_source,
        test_load_zone_contexts_missing_source_fails_closed,
        test_load_zone_contexts_symbol_missing_fails_closed,
        test_short_context_coverage_summary_counts_expected_buckets,
        test_load_zone_contexts_market_data_missing_is_truthful,
        test_take_profit_waiting_when_target_is_near_and_sell_order_exists,
        test_reload_zone_approaching_when_price_is_near_reload_zone,
        test_map_recompute_needed_when_price_is_above_all_completed_targets,
        test_invalidation_near_when_price_approaches_risk_zone,
        test_order_too_far_or_stale_when_open_orders_are_far,
        test_do_nothing_for_neutral_valid_state,
        test_insufficient_data_when_zones_are_missing,
        test_plume_without_fib_row_shows_truthful_short_context_gap,
        test_legacy_1d_context_cannot_masquerade_as_native_short_action,
        test_all_candidates_search_matches_plu_to_plume_and_clear_restores_all,
        test_legacy_1d_context_is_not_relevant_only_from_legacy_levels,
        test_stale_current_price_blocks_actionable_profit_plan_outputs,
        test_render_full_html_uses_profit_plan_title_and_public_monitor_href,
        test_json_snapshot_structure_and_safety_markers,
        test_wld_fixture_advances_active_target_and_does_not_mark_passed_level_missing,
        test_history_aware_wld_pullback_does_not_regress_target_lifecycle,
        test_price_below_first_target_keeps_first_target_active_without_history_touch,
        test_price_exactly_at_first_target_advances_to_second_target,
        test_price_between_targets_uses_second_target_distance,
        test_price_above_all_targets_has_no_active_target,
        test_completed_map_synchronizes_scenario_and_state,
        test_multiple_orders_near_only_one_target_are_scoped_per_level,
        test_order_before_cross_is_marked_missed_order,
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
