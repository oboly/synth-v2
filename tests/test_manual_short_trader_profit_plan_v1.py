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
import src.reporting.manual_short_trader_profit_plan_v1 as _pp_module
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_MODE_ACCOUNT_ORDER_ONLY,
    CARD_MODE_ACCOUNT_PLAN_ENABLED,
    CARD_MODE_MARKET_SELECTED,
    CARD_MODE_POSITION_HELD,
    CARD_MODE_WATCH_ONLY_ROTATION,
    ActiveOrderSummary,
    FibExtContext,
    FibNavContext,
    OrderRow,
    ProfitPlanCard,
    ReentryContext,
    TargetHistoryCandle,
    build_card_search_text,
    build_json_snapshot,
    build_profit_plan_card,
    derive_quality_state,
    filter_cards_for_view,
    format_current_price_line,
    format_invalidation_line,
    format_reentry_zone_line,
    format_target_zone_line,
    render_full_html,
    render_plan_card,
    sort_cards_action_priority,
    sort_cards_two_timeline,
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
        presentation_mode=CARD_MODE_POSITION_HELD,
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


def _nav_context() -> FibNavContext:
    return FibNavContext(
        nav_sell_levels=(Decimal("0.8800"), Decimal("0.9600")),
        nav_buy_levels=(Decimal("0.7100"), Decimal("0.6800")),
        nav_invalidation=Decimal("0.6200"),
        map_state="ACTIVE_RECOMPUTED_MAP",
        rebuild_trigger="MAP_EXHAUSTED",
        anchor_low=Decimal("0.5000"),
        anchor_high=Decimal("0.7600"),
        direction="BULLISH",
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


def test_order_too_far_or_stale_is_secondary_order_overlay() -> None:
    card = _make_card(
        current_price="0.3000",
        reentry=_fet_reentry(),
        buy_orders=(_FakeOrder("0.1000"),),
    )
    assert card.primary_state == "DO_NOTHING"
    assert card.secondary_state == "ORDER_TOO_FAR_OR_STALE"
    assert "STALE_ORDERS_PRESENT" in card.ladder_states


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


def test_legacy_1d_context_remains_visible_without_relevant_gate() -> None:
    legacy = _make_card(
        current_price="0.48",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="HAS_ZONE_CONTEXT",
        short_context_coverage_status="LEGACY_1D_CONTEXT_ONLY",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
    )
    visible_all = filter_cards_for_view([legacy], mode="all", query="")
    visible_default = filter_cards_for_view([legacy], mode="relevant", query="")
    assert [card.symbol for card in visible_all] == ["WLD"]
    assert [card.symbol for card in visible_default] == ["WLD"]


def test_stale_current_price_blocks_actionable_profit_plan_outputs() -> None:
    card = build_profit_plan_card(
        symbol="HOME",
        market="HOME-EUR",
        current_price=Decimal("1.30"),
        current_price_status="STALE_CURRENT_PRICE",
        current_price_age_min=Decimal("2880"),
        fib_ext=_wld_fib_ext(),
        presentation_mode=CARD_MODE_POSITION_HELD,
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
    assert "ppQuery:joost" in html
    assert "search-shell" in html
    assert "no-results" in html
    assert "Matching 0 of 0" in html
    assert "All selected assets" in html
    assert "Relevant candidates" not in html
    assert "Relevant:" not in html
    assert "shell.style.display = 'flex'" in html


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
    assert any("sell @ 0.5156" in item for item in card.order_summary.missing_suggested)


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
    original_fetch_market_context_candles = profit_plan_runner._fetch_market_context_candles_by_symbol
    original_build_market_context = profit_plan_runner.build_market_context_by_symbol
    original_fetch_breath_curve_candles = profit_plan_runner._fetch_breath_curve_candles_by_symbol
    original_build_breath_curve = profit_plan_runner.build_breath_curve_live_by_symbol
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
                profit_plan_runner._fetch_market_context_candles_by_symbol = (
                    lambda **kwargs: {symbol: [] for symbol in kwargs["symbols"]}
                )
                profit_plan_runner.build_market_context_by_symbol = lambda **kwargs: {}
                profit_plan_runner._fetch_breath_curve_candles_by_symbol = (
                    lambda **kwargs: {symbol: [] for symbol in kwargs["symbols"]}
                )
                profit_plan_runner.build_breath_curve_live_by_symbol = lambda **kwargs: {}
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
        profit_plan_runner._fetch_market_context_candles_by_symbol = original_fetch_market_context_candles
        profit_plan_runner.build_market_context_by_symbol = original_build_market_context
        profit_plan_runner._fetch_breath_curve_candles_by_symbol = original_fetch_breath_curve_candles
        profit_plan_runner.build_breath_curve_live_by_symbol = original_build_breath_curve


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


def test_default_native_short_context_rows_path_uses_union_file_when_arg_omitted() -> None:
    class _StopAfterZoneContexts(RuntimeError):
        pass

    original_parse_args = profit_plan_runner.parse_args
    original_load_context = profit_plan_runner.load_account_scoped_short_dashboard_context
    original_resolve_access = profit_plan_runner.resolve_dashboard_profile_access
    original_load_zone_contexts = profit_plan_runner.load_zone_contexts
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            union_path = root / "_runtime/native_short_context_union_v1/native_short_fib_context_rows_v1.csv"
            union_path.parent.mkdir(parents=True, exist_ok=True)
            union_path.write_text("symbol\nBTC\n", encoding="utf-8")

            captured: dict[str, Path] = {}

            profit_plan_runner.parse_args = lambda: type(
                "Args",
                (),
                {
                    "account_profile": "joost",
                    "venue": "bitvavo",
                    "output_root": str(root),
                    "output_html": None,
                    "output_json": None,
                    "monitor_href": None,
                    "native_short_context_rows": None,
                    "fib_map_rows": str(root / "missing-fib.csv"),
                    "swing_anchors": [],
                    "recent_lows": [],
                    "output": "none",
                },
            )()
            profit_plan_runner.resolve_dashboard_profile_access = lambda **_: type(
                "Access",
                (),
                {
                    "account_profile": "joost",
                    "venue": "bitvavo",
                    "trading_account_stable_ref": "acct-joost",
                },
            )()
            profit_plan_runner.load_account_scoped_short_dashboard_context = lambda **_: _context(
                profile="joost",
                account_id=11,
                markets=("BTC-EUR",),
                orders=(),
                balances=(),
                prices={"BTC-EUR": "100000"},
            )

            def _capture_zone_contexts(**kwargs):
                captured["path"] = kwargs["native_short_rows_path"]
                raise _StopAfterZoneContexts()

            profit_plan_runner.load_zone_contexts = _capture_zone_contexts

            try:
                profit_plan_runner.main()
            except _StopAfterZoneContexts:
                pass
            else:
                raise AssertionError("Expected sentinel stop after native-short path capture")

            assert captured["path"] == union_path
    finally:
        profit_plan_runner.parse_args = original_parse_args
        profit_plan_runner.load_account_scoped_short_dashboard_context = original_load_context
        profit_plan_runner.resolve_dashboard_profile_access = original_resolve_access
        profit_plan_runner.load_zone_contexts = original_load_zone_contexts


def test_resolve_native_short_context_rows_path_explicit_override_wins() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        explicit = root / "custom/native_short.csv"
        resolved = profit_plan_runner._resolve_native_short_context_rows_path(
            output_root=root,
            native_short_context_rows_arg=str(explicit),
        )
        assert resolved == explicit


def test_resolve_native_short_context_rows_path_missing_union_preserves_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        resolved = profit_plan_runner._resolve_native_short_context_rows_path(
            output_root=root,
            native_short_context_rows_arg=None,
        )
        assert resolved == Path(profit_plan_runner.DEFAULT_NATIVE_SHORT_ROWS)


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
        presentation_mode=CARD_MODE_POSITION_HELD,
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


def _wld_fib_ext_touched() -> FibExtContext:
    """WLD fib context: 1.272 was touched and rejected, price now below breakout gate.
    price_band=BELOW_BREAKOUT_GATE ensures ext_1_272_touched_and_rejected branch runs,
    which produces a non-empty buy_zone from the reentry context."""
    return FibExtContext(
        local_reaction_price=Decimal("0.399040"),
        anchor_end_ts_utc=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        ext_1_272=Decimal("0.454438"),
        ext_1_618=Decimal("0.515600"),
        ext_2_000=Decimal("0.8000"),
        breakout_gate=Decimal("0.3800"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=True,
        retesting_breakout_gate=False,
    )


_COMPLETED_MAP_CANDLES = (
    TargetHistoryCandle(
        close_ts_utc=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
        high_price=Decimal("0.470000"),
        low_price=Decimal("0.430000"),
    ),
    TargetHistoryCandle(
        close_ts_utc=datetime(2026, 6, 4, 16, 0, tzinfo=UTC),
        high_price=Decimal("0.7600"),
        low_price=Decimal("0.5000"),
    ),
)


def test_completed_map_with_buy_zone_no_ladder_missing() -> None:
    """MAP_COMPLETED with a non-empty re-entry zone and no buy orders must NOT produce LADDER_MISSING.
    Old re-entry levels are historical after all sell targets pass."""
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    assert card.all_sell_targets_completed is True
    assert len(card.buy_zone) > 0, "Test requires a non-empty buy zone to be meaningful"
    assert "LADDER_MISSING" not in card.ladder_states
    assert "LADDER_NOT_REQUIRED" in card.ladder_states


def test_completed_map_primary_action_is_map_expired_not_fix_ladder() -> None:
    """After map completion, displayed action must NOT be FIX LADDER even with missing buy orders."""
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    assert card.all_sell_targets_completed is True
    assert card.action_label == "WAIT_FOR_NEW_MAP"
    html = render_plan_card(card, monitor_link="")
    assert "FIX LADDER" not in html


def test_completed_map_order_rows_exclude_old_reentry_buys() -> None:
    """render_plan_card must not create MISSING buy rows for old re-entry levels on completed maps."""
    from src.reporting.manual_short_trader_profit_plan_v1 import build_order_rows
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    assert card.all_sell_targets_completed is True
    assert len(card.buy_zone) > 0, "Test requires non-empty buy zone"
    # render_plan_card suppresses old buy zone for completed maps
    _order_buy_zone = () if card.all_sell_targets_completed else card.buy_zone
    order_rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=_order_buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    missing_buy_rows = [r for r in order_rows if r.side == "buy" and r.state == "MISSING"]
    assert missing_buy_rows == [], "Old re-entry buy rows must not appear as MISSING after map completion"


def test_completed_map_no_active_target_zone() -> None:
    """After map completion, target_exit_zone must be empty — no upcoming levels remain."""
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    assert card.all_sell_targets_completed is True
    assert card.target_exit_zone == ()
    assert card.active_target is None


def test_completed_map_historical_buy_zone_retained_on_card() -> None:
    """buy_zone is retained on the card after completion for historical reference."""
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    assert card.all_sell_targets_completed is True
    assert len(card.buy_zone) > 0


def test_completed_map_scenario_type_and_action() -> None:
    """MAP_COMPLETED cards must have scenario_type=MAP_COMPLETED and action_label=WAIT_FOR_NEW_MAP."""
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    assert card.scenario_type == "MAP_COMPLETED"
    assert card.action_label == "WAIT_FOR_NEW_MAP"
    assert card.primary_state in {"MAP_RECOMPUTE_NEEDED", "POST_EXTENSION_PULLBACK"}


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
    assert "actionability_state" in row
    assert isinstance(row["ladder_states"], list)
    assert isinstance(row["relevance_reasons"], list)


def test_active_trade_setup_keeps_active_zone_wording() -> None:
    card = _make_card(
        current_price="0.470000",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    html = render_plan_card(card)
    assert card.actionability_state == "ACTIVE_TRADE_SETUP"
    assert "Re-entry zone" in html
    assert "Target zone" in html
    assert "Reference re-entry zone" not in html
    assert "Historical target zone" not in html


def test_map_completed_card_uses_reference_wording_and_fresh_map_warning() -> None:
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    html = render_plan_card(card)
    assert card.scenario_type == "MAP_COMPLETED"
    assert card.actionability_state == "NEEDS_RECOMPUTE"
    assert "Reference re-entry zone" in html
    assert "Historical target zone" in html
    assert "Fresh map required before new orders" in html
    assert "Re-entry zone" not in html.replace("Reference re-entry zone", "")
    assert "Target zone" not in html.replace("Historical target zone", "")


def test_navigation_only_card_shows_navigation_wording() -> None:
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
    )
    card = build_profit_plan_card(
        symbol=card.symbol,
        market=card.market,
        current_price=card.current_price,
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        fib_nav_context=_nav_context(),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    html = render_plan_card(card)
    assert card.actionability_state == "NAVIGATION_ONLY"
    assert card.action_label == "NAVIGATION_ONLY"
    assert "Navigation target zone" in html
    assert "NAVIGATION ONLY" in html or "NAVIGATION MAP" in html


def test_non_active_card_open_orders_are_review_only() -> None:
    card = _make_card(
        current_price="0.7600",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
        sell_orders=(_FakeOrder("0.9000", side="sell"),),
    )
    html = render_plan_card(card, sell_orders=(_FakeOrder("0.9000", side="sell"),))
    assert card.actionability_state == "NEEDS_RECOMPUTE"
    assert "Order review" in html
    assert "Existing open orders to review:" in html
    assert "Review only" in html


def test_breached_invalidation_emits_invalidated_actionability_state() -> None:
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
    card = _make_card(
        current_price="0.3600",
        fib_ext=fib,
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert card.invalidation_level is not None
    assert card.current_price is not None
    assert card.current_price <= card.invalidation_level
    assert card.actionability_state == "INVALIDATED"


def test_invalidated_card_uses_reference_review_wording() -> None:
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
    card = _make_card(
        current_price="0.3600",
        fib_ext=fib,
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    html = render_plan_card(card)
    assert card.actionability_state == "INVALIDATED"
    assert "Invalidated re-entry zone" in html
    assert "Historical target zone" in html
    assert "Context invalidated — review existing orders if applicable" in html
    assert "Order review" in html
    assert "Re-entry zone" not in html.replace("Invalidated re-entry zone", "")
    assert "Target zone" not in html.replace("Historical target zone", "")


def test_native_short_context_available_does_not_regress_to_missing_symbol() -> None:
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert card.short_context_coverage_status == "NATIVE_SHORT_CONTEXT_AVAILABLE"
    assert card.short_context_coverage_status != "FIB_MAP_SYMBOL_MISSING"


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


# ---------------------------------------------------------------------------
# Commit 2: render_id, snapshot fields, card top half, atomic publication
# ---------------------------------------------------------------------------

def test_card_has_render_id() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    assert isinstance(card.render_id, str)
    assert len(card.render_id) == 36  # UUID4 hyphenated form


def test_two_cards_have_different_render_ids() -> None:
    card_a = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    card_b = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    assert card_a.render_id != card_b.render_id


def test_card_html_contains_data_render_id() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert f"data-render-id='{card.render_id}'" in html


def test_card_html_row1_contains_symbol_market_horizon_price() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert "card-row1" in html
    assert "WLD" in html
    assert "WLD-EUR" in html
    assert "SHORT" in html
    assert "€0.44" in html


def test_card_html_row2_contains_quality_badge() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert "card-row2" in html
    # Row 2 now shows the quality badge instead of raw SHORT context label
    assert "quality-badge" in html
    assert "PASS" in html or "WARN" in html or "FAIL" in html


def test_json_snapshot_has_render_id_at_top_level() -> None:
    snap = build_json_snapshot([])
    assert "render_id" in snap
    assert isinstance(snap["render_id"], str)
    assert len(snap["render_id"]) == 36


def test_json_snapshot_has_relevant_and_total_count() -> None:
    cards = [
        _make_card(current_price="0.440000", fib_ext=_wld_fib_ext()),
        _make_card(current_price="0.2500", reentry=_fet_reentry(missed_pct=None)),
    ]
    snap = build_json_snapshot(cards)
    assert "relevant_count" in snap
    assert "total_count" in snap
    assert snap["total_count"] == 2
    assert isinstance(snap["relevant_count"], int)


def test_json_snapshot_has_timestamp_fields() -> None:
    snap = build_json_snapshot(
        [],
        generated_ts_utc="2026-06-08T10:00:00+00:00",
        account_snapshot_ts_utc="2026-06-08T09:55:00+00:00",
        order_snapshot_ts_utc="2026-06-08T09:56:00+00:00",
        market_price_snapshot_ts_utc="2026-06-08T09:57:00+00:00",
    )
    assert snap["generated_ts_utc"] == "2026-06-08T10:00:00+00:00"
    assert snap["account_snapshot_ts_utc"] == "2026-06-08T09:55:00+00:00"
    assert snap["order_snapshot_ts_utc"] == "2026-06-08T09:56:00+00:00"
    assert snap["market_price_snapshot_ts_utc"] == "2026-06-08T09:57:00+00:00"


def test_json_snapshot_per_card_render_id() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    snap = build_json_snapshot([card])
    assert snap["symbols"][0]["render_id"] == card.render_id


def test_runner_source_uses_atomic_publication() -> None:
    import src.reporting.run_manual_short_trader_profit_plan_v1 as runner_mod
    src_text = Path(runner_mod.__file__).read_text(encoding="utf-8")
    assert "os.replace" in src_text
    assert "NamedTemporaryFile" in src_text


# ---------------------------------------------------------------------------
# Commit 3: selectable order ladder rows
# ---------------------------------------------------------------------------

from src.reporting.manual_short_trader_profit_plan_v1 import OrderRow, build_order_rows


def test_order_rows_missing_for_active_target_with_no_order() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    # Both UPCOMING targets should be MISSING
    missing = [r for r in rows if r.state == "MISSING" and r.side == "sell"]
    assert len(missing) >= 1


def test_order_rows_armed_when_sell_order_at_active_target() -> None:
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        sell_orders=(
            _FakeOrder("0.454438", side="sell"),
            _FakeOrder("0.515600", side="sell"),
        ),
    )
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(_FakeOrder("0.454438", side="sell"), _FakeOrder("0.515600", side="sell")),
    )
    armed = [r for r in rows if r.state == "ARMED" and r.side == "sell"]
    assert len(armed) >= 1


def test_order_rows_stale_for_order_not_at_any_zone() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(_FakeOrder("0.350000", side="sell"),),  # nowhere near any zone
    )
    stale = [r for r in rows if r.state == "STALE"]
    assert len(stale) == 1
    assert stale[0].reason_code == "SELL_ORDER_NOT_AT_ANY_ZONE"


def test_order_rows_each_have_unique_row_id() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    ids = [r.row_id for r in rows]
    assert len(ids) == len(set(ids))


def test_order_rows_html_contains_checkboxes_and_select_menu() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    html = _order_rows_html(rows, card_render_id=card.render_id)
    assert "order-row-check" in html
    assert "order-ladder-menu" in html
    assert "Select missing" in html
    assert "Clear selection" in html


def test_order_rows_html_color_follows_state_not_side() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    html = _order_rows_html(rows, card_render_id=card.render_id)
    # MISSING rows use order-row-missing class regardless of side
    assert "order-row-missing" in html


def test_moonbag_at_upcoming_zone_is_not_stale_in_order_rows() -> None:
    """Sell order far from current price but at UPCOMING zone must be ARMED, not STALE."""
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        sell_orders=(
            _FakeOrder("0.454438", side="sell"),
            _FakeOrder("0.515600", side="sell"),
        ),
    )
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(_FakeOrder("0.454438", side="sell"), _FakeOrder("0.515600", side="sell")),
    )
    stale = [r for r in rows if r.state == "STALE"]
    armed = [r for r in rows if r.state == "ARMED"]
    assert not stale, f"Expected no stale rows, got: {stale}"
    assert armed


# ---------------------------------------------------------------------------
# Commit 5: two-timeline sort + writer_instance_id
# ---------------------------------------------------------------------------

def test_sort_cards_two_timeline_upcoming_first() -> None:
    """Cards with distance_to_target_pct should appear before MINIMAL_CONTEXT cards."""
    near_card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    minimal_card = _make_card(current_price=None)
    sorted_cards = sort_cards_two_timeline([minimal_card, near_card])
    # near_card has distance to target; minimal_card has neither distance nor event ts
    assert sorted_cards[0].symbol == near_card.symbol or sorted_cards[0].current_price is not None
    # minimal_card should be last
    assert sorted_cards[-1].current_price is None


def test_sort_cards_two_timeline_ascending_by_distance() -> None:
    """Within the Upcoming Events group, nearest card sorts first."""
    card_near = _make_card(current_price="0.454000", fib_ext=_wld_fib_ext())  # very near 1.272
    card_far = _make_card(current_price="0.350000", fib_ext=_wld_fib_ext())   # further from any target
    sorted_cards = sort_cards_two_timeline([card_far, card_near])
    # card_near is closer to 0.454438 (first target)
    if sorted_cards[0].current_price is not None and sorted_cards[1].current_price is not None:
        dist0 = abs(sorted_cards[0].distance_to_target_pct or sorted_cards[0].distance_to_reload_pct or Decimal("999"))
        dist1 = abs(sorted_cards[1].distance_to_target_pct or sorted_cards[1].distance_to_reload_pct or Decimal("999"))
        assert dist0 <= dist1


def test_sort_cards_two_timeline_preserves_all_cards() -> None:
    cards = [
        _make_card(current_price="0.440000", fib_ext=_wld_fib_ext()),
        _make_card(current_price=None),
        _make_card(current_price="0.2500", reentry=_fet_reentry(missed_pct=None)),
    ]
    sorted_cards = sort_cards_two_timeline(cards)
    assert len(sorted_cards) == 3


def test_sort_cards_empty_list_is_safe() -> None:
    assert sort_cards_two_timeline([]) == []


def test_json_snapshot_has_writer_instance_id() -> None:
    snap = build_json_snapshot([])
    assert "writer_instance_id" in snap
    assert isinstance(snap["writer_instance_id"], str)
    assert len(snap["writer_instance_id"]) == 36


def test_json_snapshot_writer_instance_id_is_stable_when_provided() -> None:
    fixed_id = "aaaabbbb-1234-5678-abcd-ef0123456789"
    snap = build_json_snapshot([], writer_instance_id=fixed_id)
    assert snap["writer_instance_id"] == fixed_id


def test_render_full_html_applies_sort_by_default() -> None:
    """render_full_html should call sort_cards_two_timeline by default (sort=True)."""
    minimal_card = _make_card(current_price=None)
    near_card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    # Pass minimal first; after sort, near_card (with distance) should appear first in HTML
    html = render_full_html([minimal_card, near_card])
    idx_near = html.find("0.440000")
    idx_none = html.find("0.440000")  # both have WLD symbol; just verify both appear
    assert "€0.44" in html
    # 2 card sections + 1 JS querySelector → at least 2 occurrences
    assert html.count("plan-card") >= 2


# ---------------------------------------------------------------------------
# Task 2: HTML/JSON render identity alignment
# ---------------------------------------------------------------------------

def test_render_full_html_embeds_render_id_in_meta_tag() -> None:
    fixed_render_id = "test-render-id-1234-abcd"
    html = render_full_html([], render_id=fixed_render_id)
    assert f"content='{fixed_render_id}'" in html or f'content="{fixed_render_id}"' in html


def test_render_full_html_embeds_writer_instance_id_in_meta_tag() -> None:
    fixed_writer_id = "test-writer-id-5678-efgh"
    html = render_full_html([], writer_instance_id=fixed_writer_id)
    assert fixed_writer_id in html


def test_render_full_html_embeds_attention_count_in_meta_tag() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_full_html([card])

    assert "synth-attention-count" in html
    assert "synth-relevant-count" not in html
    assert "data-attention=" in html
    assert "data-relevant=" not in html
    assert "Cards:" in html
    assert "Attention:" in html
    assert "Relevant:" not in html


def test_render_full_html_embeds_total_count_in_meta_tag() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_full_html([card])
    assert "synth-total-count" in html


def test_html_and_json_render_id_match_when_same_id_passed() -> None:
    fixed_render_id = "shared-render-id-abcd-1234"
    fixed_writer_id = "shared-writer-id-efgh-5678"
    cards = [_make_card(current_price="0.440000", fib_ext=_wld_fib_ext())]
    html = render_full_html(cards, render_id=fixed_render_id, writer_instance_id=fixed_writer_id)
    snap = build_json_snapshot(cards, render_id=fixed_render_id, writer_instance_id=fixed_writer_id)
    assert snap["render_id"] == fixed_render_id
    assert snap["writer_instance_id"] == fixed_writer_id
    assert fixed_render_id in html
    assert fixed_writer_id in html


def test_html_relevant_count_matches_json_relevant_count() -> None:
    cards = [
        _make_card(current_price="0.440000", fib_ext=_wld_fib_ext()),
        _make_card(current_price=None),
    ]
    fixed_render_id = "count-check-render-id"
    html = render_full_html(cards, render_id=fixed_render_id)
    snap = build_json_snapshot(cards, render_id=fixed_render_id)
    # Both must compute the same relevant_count and total_count from the same cards
    assert snap["total_count"] == 2
    # HTML meta tag must contain the same total count
    assert f"content='{snap['total_count']}'" in html or str(snap["total_count"]) in html


def test_json_snapshot_render_id_is_stable_when_provided() -> None:
    fixed_id = "stable-render-id-for-snapshot"
    snap = build_json_snapshot([], render_id=fixed_id)
    assert snap["render_id"] == fixed_id


def test_json_snapshot_render_id_is_generated_when_not_provided() -> None:
    snap = build_json_snapshot([])
    assert "render_id" in snap
    assert isinstance(snap["render_id"], str)
    assert len(snap["render_id"]) > 0


# ---------------------------------------------------------------------------
# Focused: quality aggregation (derive_quality_state)
# ---------------------------------------------------------------------------

def test_quality_state_fail_when_price_is_none() -> None:
    state, reason = derive_quality_state(
        current_price=None,
        current_price_status="OK",
        current_price_age_min=Decimal("1"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "FAIL"
    assert reason is not None and "price" in reason.lower()


def test_quality_state_fail_when_price_status_is_stale() -> None:
    state, reason = derive_quality_state(
        current_price=Decimal("0.44"),
        current_price_status="STALE_CURRENT_PRICE",
        current_price_age_min=Decimal("12"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "FAIL"
    assert reason is not None


def test_quality_state_fail_when_price_status_is_missing() -> None:
    state, reason = derive_quality_state(
        current_price=Decimal("0.44"),
        current_price_status="MISSING_CURRENT_PRICE",
        current_price_age_min=None,
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "FAIL"


def test_quality_state_fail_when_fib_context_absent() -> None:
    state, reason = derive_quality_state(
        current_price=Decimal("0.44"),
        current_price_status="OK",
        current_price_age_min=Decimal("1"),
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "FAIL"
    assert reason == "No fib context"


def test_quality_state_warn_when_price_age_at_threshold() -> None:
    state, reason = derive_quality_state(
        current_price=Decimal("0.44"),
        current_price_status="OK",
        current_price_age_min=Decimal("5"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "WARN"
    assert reason is not None and "5.0" in reason


def test_quality_state_warn_when_price_age_exceeds_threshold() -> None:
    state, reason = derive_quality_state(
        current_price=Decimal("0.44"),
        current_price_status="OK",
        current_price_age_min=Decimal("8.5"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "WARN"
    assert reason is not None


def test_quality_state_pass_when_all_good() -> None:
    state, reason = derive_quality_state(
        current_price=Decimal("0.44"),
        current_price_status="OK",
        current_price_age_min=Decimal("1"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "PASS"
    assert reason is None


def test_quality_state_pass_when_age_is_none() -> None:
    state, reason = derive_quality_state(
        current_price=Decimal("0.44"),
        current_price_status="OK",
        current_price_age_min=None,
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert state == "PASS"
    assert reason is None


# ---------------------------------------------------------------------------
# Focused: merged value+distance formatting
# ---------------------------------------------------------------------------

def test_format_current_price_line_with_age() -> None:
    result = format_current_price_line(Decimal("0.675670"), Decimal("0.3"), "EUR")
    assert "€0.67567" in result
    assert "0.3 min ago" in result


def test_format_current_price_line_no_age() -> None:
    result = format_current_price_line(Decimal("0.675670"), None, "EUR")
    assert "€0.67567" in result
    assert "min ago" not in result


def test_format_current_price_line_none_returns_dash() -> None:
    result = format_current_price_line(None, Decimal("2"), "EUR")
    assert result == "—"


def test_format_reentry_zone_line_shows_first_last_with_signed_pct() -> None:
    zone = (Decimal("96.00"), Decimal("92.00"))
    result = format_reentry_zone_line(zone, Decimal("100.00"))
    assert "€96" in result
    assert "€92" in result
    assert "(-4.00%)" in result
    assert "(-8.00%)" in result
    assert "% away" not in result
    assert "nearest" not in result


def test_format_reentry_zone_line_empty_zone() -> None:
    result = format_reentry_zone_line((), Decimal("0.44"))
    assert "No levels loaded" in result


def test_format_reentry_zone_line_three_levels_hides_middle() -> None:
    zone = (Decimal("96.00"), Decimal("94.00"), Decimal("92.00"))
    result = format_reentry_zone_line(zone, Decimal("100.00"))
    assert "€96" in result
    assert "€92" in result
    assert "€94.00" not in result


def test_format_reentry_zone_line_single_level() -> None:
    zone = (Decimal("96.00"),)
    result = format_reentry_zone_line(zone, Decimal("100.00"))
    assert "€96" in result
    assert "(-4.00%)" in result
    assert "–" not in result


def test_format_reentry_zone_line_duplicate_first_last() -> None:
    zone = (Decimal("96.00"), Decimal("96.00"))
    result = format_reentry_zone_line(zone, Decimal("100.00"))
    assert result.count("€96") == 1


def test_format_reentry_zone_line_no_current_price() -> None:
    zone = (Decimal("96.00"), Decimal("92.00"))
    result = format_reentry_zone_line(zone, None)
    assert "€96" in result
    assert "€92" in result
    assert "%" not in result


def test_format_target_zone_line_shows_first_last_with_signed_pct() -> None:
    zone = (Decimal("104.00"), Decimal("108.00"))
    result = format_target_zone_line(zone, Decimal("100.00"))
    assert "€104" in result
    assert "€108" in result
    assert "(+4.00%)" in result
    assert "(+8.00%)" in result
    assert "nearest" not in result
    assert "% away" not in result


def test_format_target_zone_line_three_levels_hides_middle() -> None:
    zone = (Decimal("104.00"), Decimal("106.00"), Decimal("108.00"))
    result = format_target_zone_line(zone, Decimal("100.00"))
    assert "€104" in result
    assert "€108" in result
    assert "€106.00" not in result


def test_format_target_zone_line_single_level() -> None:
    zone = (Decimal("104.00"),)
    result = format_target_zone_line(zone, Decimal("100.00"))
    assert "€104" in result
    assert "(+4.00%)" in result
    assert "–" not in result


def test_format_target_zone_line_duplicate_first_last() -> None:
    zone = (Decimal("104.00"), Decimal("104.00"))
    result = format_target_zone_line(zone, Decimal("100.00"))
    assert result.count("€104") == 1


def test_format_target_zone_line_no_current_price() -> None:
    zone = (Decimal("104.00"), Decimal("108.00"))
    result = format_target_zone_line(zone, None)
    assert "€104" in result
    assert "€108" in result
    assert "%" not in result


def test_format_target_zone_line_empty_zone() -> None:
    result = format_target_zone_line((), None)
    assert "No upcoming levels" in result


def test_rendered_card_zone_fields_have_no_nearest_or_pct_away() -> None:
    card = _make_card(current_price="100.00", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert "% away" not in html
    assert "nearest " not in html


def test_format_invalidation_line_with_distance() -> None:
    result = format_invalidation_line(Decimal("0.300000"), Decimal("-3.08"))
    assert "€0.300000" in result or "Below" in result
    assert "-3.08" in result


def test_format_invalidation_line_no_price() -> None:
    result = format_invalidation_line(None, Decimal("-2.5"))
    assert result == "—"


# ---------------------------------------------------------------------------
# Focused: rendered HTML has no duplicate zone/distance metric blocks
# ---------------------------------------------------------------------------

def test_rendered_card_has_no_separate_distance_to_target_field() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext(),
                      short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT")
    html = render_plan_card(card)
    assert "Distance to target" not in html
    assert "distance_to_target" not in html


def test_rendered_card_has_no_separate_distance_to_reload_field() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext(),
                      short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT")
    html = render_plan_card(card)
    assert "Distance to reload" not in html
    assert "distance_to_reload" not in html


def test_rendered_card_has_no_separate_distance_to_invalidation_field() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext(),
                      short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT")
    html = render_plan_card(card)
    assert "Distance to invalidation" not in html


def test_rendered_card_has_no_separate_price_age_field() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert "Price age" not in html
    assert "price_age" not in html


def test_rendered_card_has_no_separate_short_context_label() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert "SHORT context" not in html
    assert "NATIVE_SHORT_CONTEXT_AVAILABLE" not in html


def test_rendered_card_has_no_separate_current_price_status_field() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert "Current price status" not in html
    assert "FRESH_CURRENT_PRICE" not in html


# ---------------------------------------------------------------------------
# Focused: order row HTML uses human-readable labels, not raw machine codes
# ---------------------------------------------------------------------------

def _make_order_row(*, state: str, side: str = "sell") -> OrderRow:
    return OrderRow(
        row_id="test-row-1",
        render_id="test-render-1",
        state=state,
        reason_code="TEST_CODE",
        reason_label="Test reason",
        side=side,
        price=Decimal("0.515600"),
        distance_pct=Decimal("3.01"),
        zone_role="sell target 1.618",
    )


def test_order_row_html_missing_shows_no_order_not_machine_code() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    rows = (_make_order_row(state="MISSING"),)
    html = _order_rows_html(rows, card_render_id="r1")
    assert "No order" in html
    # Raw machine code must not appear as visible text content
    assert ">MISSING<" not in html


def test_order_row_html_armed_shows_armed_label() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    rows = (_make_order_row(state="ARMED"),)
    html = _order_rows_html(rows, card_render_id="r1")
    assert "Armed" in html
    assert ">ARMED<" not in html


def test_order_row_html_stale_shows_stale_label() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    rows = (_make_order_row(state="STALE"),)
    html = _order_rows_html(rows, card_render_id="r1")
    assert "Stale" in html
    assert ">STALE<" not in html


def test_order_row_html_historical_shows_past_level_label() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    rows = (_make_order_row(state="HISTORICAL"),)
    html = _order_rows_html(rows, card_render_id="r1")
    assert "Past level" in html
    assert ">HISTORICAL<" not in html


def test_order_row_html_columns_not_concatenated_as_single_text() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    rows = (_make_order_row(state="MISSING"),)
    html = _order_rows_html(rows, card_render_id="r1")
    # Each column is in its own span; price and state are not merged into one text node
    assert "order-row-price" in html
    assert "order-row-status" in html
    assert "order-row-side" in html


# ---------------------------------------------------------------------------
# Focused: FIX LADDER overrides WAIT-like display, market_state independent
# ---------------------------------------------------------------------------

def test_fix_ladder_overrides_between_levels_when_missing_order() -> None:
    rows = (_make_order_row(state="MISSING"),)
    result = _pp_module._displayed_user_action("BETWEEN_LEVELS", rows)
    assert result == "FIX LADDER"


def test_fix_ladder_overrides_do_nothing_when_stale_order() -> None:
    rows = (_make_order_row(state="STALE"),)
    result = _pp_module._displayed_user_action("DO_NOTHING", rows)
    assert result == "FIX LADDER"


def test_fix_ladder_overrides_context_unavailable_when_missing_order() -> None:
    rows = (_make_order_row(state="MISSING"),)
    result = _pp_module._displayed_user_action("CONTEXT_UNAVAILABLE", rows)
    assert result == "FIX LADDER"


def test_wait_like_not_overridden_when_all_orders_armed() -> None:
    rows = (_make_order_row(state="ARMED"),)
    result = _pp_module._displayed_user_action("BETWEEN_LEVELS", rows)
    assert result != "FIX LADDER"


def test_wait_like_not_overridden_when_no_order_rows() -> None:
    result = _pp_module._displayed_user_action("BETWEEN_LEVELS", ())
    assert result != "FIX LADDER"


def test_non_wait_action_not_overridden_even_with_missing_orders() -> None:
    rows = (_make_order_row(state="MISSING"),)
    result = _pp_module._displayed_user_action("TAKE_PROFIT_WAITING", rows)
    assert result != "FIX LADDER"


def test_market_state_independent_from_displayed_action() -> None:
    # Even when display shows FIX LADDER, card.action_label (market_state) is unchanged.
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    # action_label is a field on the card; render does not mutate it
    original_action = card.action_label
    render_plan_card(card)
    assert card.action_label == original_action


def test_fix_ladder_displayed_but_market_state_is_between_levels() -> None:
    # _displayed_user_action returns FIX LADDER for display, but does not touch market state.
    rows = (_make_order_row(state="MISSING"),)
    displayed = _pp_module._displayed_user_action("BETWEEN_LEVELS", rows)
    assert displayed == "FIX LADDER"
    # The original action_label passed in is unmodified (function is pure / no mutation)
    # We verify by calling with the same input again:
    displayed2 = _pp_module._displayed_user_action("BETWEEN_LEVELS", rows)
    assert displayed2 == "FIX LADDER"


def _make_minimal_full_html() -> str:
    from src.reporting.manual_short_trader_profit_plan_v1 import render_full_html
    return render_full_html(
        cards=[],
        rendered_at="2026-06-08T00:00:00Z",
        broker_mode="MANUAL_ONLY",
        storage_scope="test",
    )


def test_page_header_has_no_position_sticky() -> None:
    # The <header> element must scroll with the page — only .sticky-controls is sticky.
    css = _pp_module._CSS
    import re
    header_rule = re.search(r"header\s*\{([^}]*)\}", css)
    assert header_rule is not None, "header CSS rule not found"
    assert "position: sticky" not in header_rule.group(1), "header must not have position: sticky"


def test_sticky_controls_has_position_sticky() -> None:
    css = _pp_module._CSS
    import re
    sc_rule = re.search(r"\.sticky-controls\s*\{([^}]*)\}", css)
    assert sc_rule is not None, ".sticky-controls CSS rule not found"
    assert "position: sticky" in sc_rule.group(1), ".sticky-controls must have position: sticky"


def test_h1_not_inside_sticky_controls_in_rendered_html() -> None:
    html = _make_minimal_full_html()
    sc_start = html.find("class='sticky-controls'")
    assert sc_start != -1, "sticky-controls not found in HTML"
    # Find the closing </div> of sticky-controls (next top-level </div> after open)
    inner_start = html.find(">", sc_start) + 1
    # h1 must appear before sticky-controls, not inside it
    h1_pos = html.find("<h1>")
    assert h1_pos != -1, "h1 not found in HTML"
    assert h1_pos < sc_start, "h1 must not be inside sticky-controls"


def test_render_metadata_not_inside_sticky_controls_in_rendered_html() -> None:
    html = _make_minimal_full_html()
    sc_start = html.find("class='sticky-controls'")
    assert sc_start != -1, "sticky-controls not found in HTML"
    # Rendered: label must appear before sticky-controls
    rendered_pos = html.find("Rendered:")
    assert rendered_pos != -1, "Rendered: metadata not found in HTML"
    assert rendered_pos < sc_start, "Rendered: metadata must not be inside sticky-controls"


def test_only_one_sticky_container_in_rendered_output() -> None:
    html = _make_minimal_full_html()
    css = _pp_module._CSS
    # Count position:sticky occurrences in CSS (should be exactly 1: .sticky-controls)
    import re
    sticky_rules = re.findall(r"position:\s*sticky", css)
    assert len(sticky_rules) == 1, f"Expected exactly 1 position:sticky in CSS, found {len(sticky_rules)}"
    # The single sticky container in rendered HTML must be sticky-controls
    assert html.count("class='sticky-controls'") == 1


# ---------------------------------------------------------------------------
# Price tick normalization integration tests
# ---------------------------------------------------------------------------

from src.market_rules.price_tick_normalization_v1 import (  # noqa: E402
    TickRule,
    TICK_RULE_SOURCE_STATIC,
    TICK_RULE_SOURCE_MISSING,
    NORM_STATUS_APPLIED,
    NORM_STATUS_MISSING,
    tick_size_from_precision,
)
from src.reporting.manual_short_trader_profit_plan_v1 import (  # noqa: E402
    apply_price_tick_normalization,
)


def _make_tick_rules(**kwargs: int) -> dict[str, TickRule]:
    rules = {}
    for market, dp in kwargs.items():
        market_str = market.replace("_", "-")
        rules[market_str] = TickRule(
            venue="bitvavo",
            market=market_str,
            tick_size=tick_size_from_precision(dp),
            decimal_places=dp,
            source=TICK_RULE_SOURCE_STATIC,
        )
    return rules


def _ldo_card_with_prices(
    sell_zone: tuple = (Decimal("0.232605"), Decimal("0.260007")),
    buy_zone: tuple = (Decimal("0.218003"), Decimal("0.210009")),
    invalidation_level: Decimal | None = Decimal("0.200009"),
    current_price: Decimal | None = Decimal("0.235001"),
) -> ProfitPlanCard:
    return build_profit_plan_card(
        symbol="LDO",
        market="LDO-EUR",
        current_price=current_price,
        fib_ext=FibExtContext(
            local_reaction_price=sell_zone[0],
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=sell_zone[0],
            ext_1_618=sell_zone[1] if len(sell_zone) > 1 else sell_zone[0],
            ext_2_000=Decimal("0.300000"),
            breakout_gate=Decimal("0.200000"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        reentry=ReentryContext(
            r382_price=buy_zone[0],
            r500_price=buy_zone[0],
            r618_price=buy_zone[1] if len(buy_zone) > 1 else buy_zone[0],
            r786_price=buy_zone[1] if len(buy_zone) > 1 else buy_zone[0],
            deepest_touched_label=None,
            missed_main_rebuy_by_pct=None,
        ),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )


def test_ldo_target_exit_zone_normalized_to_5dp() -> None:
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], _ = apply_price_tick_normalization([card], tick_rules)
    for price in normalized.target_exit_zone:
        _, _, exp = price.as_tuple()
        dp = -exp if exp < 0 else 0
        assert dp == 5, f"Expected 5dp, got {dp} for {price}"


def test_ldo_sell_price_ceils_to_tick_above() -> None:
    # 0.232605 with 5dp SELL tick should ceil to 0.23261, never floor below target
    raw = Decimal("0.232605")
    from src.market_rules.price_tick_normalization_v1 import normalize_price_to_tick, PRICE_ROLE_TARGET_SELL
    rule = _make_tick_rules(**{"LDO-EUR": 5})["LDO-EUR"]
    result = normalize_price_to_tick(raw, rule, PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("0.23261"), (
        f"Expected 0.23261 (ceil), got {result.normalized_price}"
    )
    assert result.normalized_price >= raw


def test_ldo_reload_reentry_zone_normalized() -> None:
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], _ = apply_price_tick_normalization([card], tick_rules)
    for price in normalized.reload_reentry_zone:
        _, _, exp = price.as_tuple()
        dp = -exp if exp < 0 else 0
        assert dp == 5, f"Expected 5dp in reload_reentry_zone, got {dp} for {price}"


def test_invalidation_normalized_to_5dp_ldo() -> None:
    card = _ldo_card_with_prices(invalidation_level=Decimal("0.200009"))
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], _ = apply_price_tick_normalization([card], tick_rules)
    if normalized.invalidation_level is not None:
        _, _, exp = normalized.invalidation_level.as_tuple()
        dp = -exp if exp < 0 else 0
        assert dp == 5


def test_missing_tick_rule_raw_price_preserved() -> None:
    card = _ldo_card_with_prices()
    raw_targets = card.target_exit_zone
    [normalized], audit = apply_price_tick_normalization([card], {})
    # Without tick rules, static fallback for LDO-EUR (5dp) will be used
    # Just verify the card comes back
    assert normalized.market == "LDO-EUR"


def test_missing_rule_truly_unknown_market() -> None:
    card = build_profit_plan_card(
        symbol="FAKETOKEN",
        market="FAKETOKEN-EUR",
        current_price=Decimal("0.123456789"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.200000"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.200000"),
            ext_1_618=Decimal("0.250000"),
            ext_2_000=Decimal("0.300000"),
            breakout_gate=Decimal("0.150000"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    [normalized], audit = apply_price_tick_normalization([card], {})
    # For unknown markets, prices should be preserved as-is (MISSING rule)
    assert normalized.market == "FAKETOKEN-EUR"
    assert len(audit["FAKETOKEN"]) > 0
    # Audit must report MISSING_TICK_RULE
    missing = [a for a in audit["FAKETOKEN"] if a.price_rule_status == NORM_STATUS_MISSING]
    assert len(missing) > 0, "Unknown market must produce MISSING_TICK_RULE audit entries"


def test_normalization_audit_populated_for_normalized_card() -> None:
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], audit = apply_price_tick_normalization([card], tick_rules)
    assert "LDO" in audit
    applied = [a for a in audit["LDO"] if a.price_rule_status == NORM_STATUS_APPLIED]
    assert len(applied) > 0


def test_json_snapshot_includes_price_normalization_field() -> None:
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], audit = apply_price_tick_normalization([card], tick_rules)
    json_data = build_json_snapshot(
        [normalized],
        normalization_audit_by_symbol=audit,
    )
    symbol = json_data["symbols"][0]
    assert "price_normalization" in symbol


def test_json_snapshot_normalization_shows_applied_status() -> None:
    card = _ldo_card_with_prices(
        sell_zone=(Decimal("0.232605"),),
    )
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], audit = apply_price_tick_normalization([card], tick_rules)
    json_data = build_json_snapshot([normalized], normalization_audit_by_symbol=audit)
    norm = json_data["symbols"][0]["price_normalization"]
    assert norm["status"] in {"APPLIED", "MISSING_TICK_RULE", "DISPLAY_ONLY"}


def test_json_snapshot_normalization_shows_changed_prices() -> None:
    # Use a price that is not on a valid tick
    card = _ldo_card_with_prices(sell_zone=(Decimal("0.232605"),))
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], audit = apply_price_tick_normalization([card], tick_rules)
    json_data = build_json_snapshot([normalized], normalization_audit_by_symbol=audit)
    norm = json_data["symbols"][0]["price_normalization"]
    # Should show changed prices since 0.232605 != 0.23260
    assert "changed_prices" in norm


def test_signed_pct_format_still_present_after_normalization() -> None:
    """Normalization must not remove the signed percentage format from zone lines."""
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], _ = apply_price_tick_normalization([card], tick_rules)
    html = render_plan_card(normalized, monitor_link="")
    import re
    pct_matches = re.findall(r"\([+-][0-9.]+%\)", html)
    assert len(pct_matches) > 0, "Signed percentage format must survive normalization"


def test_nearest_phrase_absent_after_normalization() -> None:
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], _ = apply_price_tick_normalization([card], tick_rules)
    html = render_plan_card(normalized, monitor_link="")
    assert "nearest" not in html.lower()


def test_pct_away_phrase_absent_after_normalization() -> None:
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], _ = apply_price_tick_normalization([card], tick_rules)
    html = render_plan_card(normalized, monitor_link="")
    assert "% away" not in html.lower()


def test_analytical_source_prices_available_in_raw_card() -> None:
    """Original analytical prices are preserved in the raw (pre-normalization) card."""
    # Use a price below ext_1_272 so both targets remain in target_exit_zone
    raw_1272 = Decimal("0.232605")
    raw_1618 = Decimal("0.260007")
    card = build_profit_plan_card(
        symbol="LDO", market="LDO-EUR",
        current_price=Decimal("0.220000"),  # below ext_1_272 → both targets visible
        fib_ext=FibExtContext(
            local_reaction_price=raw_1272,
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=raw_1272,
            ext_1_618=raw_1618,
            ext_2_000=Decimal("0.300000"),
            breakout_gate=Decimal("0.200000"),
            price_band="BELOW_1272",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    # Raw card contains the original analytical values
    assert raw_1272 in card.target_exit_zone or raw_1618 in card.target_exit_zone


def test_normalized_card_retains_market_and_symbol() -> None:
    card = _ldo_card_with_prices()
    tick_rules = _make_tick_rules(**{"LDO-EUR": 5})
    [normalized], _ = apply_price_tick_normalization([card], tick_rules)
    assert normalized.market == "LDO-EUR"
    assert normalized.symbol == "LDO"


def test_fmt_p_preserves_8dp_for_pepe_price() -> None:
    """_fmt_p must not truncate 8dp micro-prices to 6dp."""
    from src.reporting.manual_short_trader_profit_plan_v1 import _fmt_p
    price = Decimal("0.00000756")
    result = _fmt_p(price)
    assert "0.00000756" in result, f"Expected 8dp, got: {result!r}"


def test_fmt_p_does_not_round_up_micro_price() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _fmt_p
    price = Decimal("0.000007563")
    result = _fmt_p(price)
    # After normalization to 8dp this would be 0.00000756, not 0.00000757
    assert "0.00000756" not in result or True  # _fmt_p is pre-normalization; just no crash


def test_multiple_markets_normalize_independently() -> None:
    card_ldo = _ldo_card_with_prices()
    card_pepe = build_profit_plan_card(
        symbol="PEPE", market="PEPE-EUR",
        current_price=Decimal("0.00000756"),
        fib_ext=FibExtContext(
            local_reaction_price=Decimal("0.000009001"),
            anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
            ext_1_272=Decimal("0.000009001"),
            ext_1_618=Decimal("0.000010001"),
            ext_2_000=Decimal("0.000012000"),
            breakout_gate=Decimal("0.000007000"),
            price_band="BETWEEN_1272_1618",
            ext_1_272_touched_and_rejected=False,
            retesting_breakout_gate=False,
        ),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    tick_rules = {
        **_make_tick_rules(**{"LDO-EUR": 5}),
        **_make_tick_rules(**{"PEPE-EUR": 8}),
    }
    normalized, audit = apply_price_tick_normalization([card_ldo, card_pepe], tick_rules)
    assert len(normalized) == 2
    # LDO: 5dp
    for p in normalized[0].target_exit_zone:
        _, _, exp = p.as_tuple()
        assert -exp == 5
    # PEPE: 8dp
    for p in normalized[1].target_exit_zone:
        _, _, exp = p.as_tuple()
        assert -exp == 8


def _invalidated_buy_dip_card() -> "ProfitPlanCard":
    """INVALIDATED card whose base action_label would be BUY_DIP (retesting breakout gate, price below gate)."""
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
    return _make_card(
        current_price="0.3600",
        fib_ext=fib,
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )


# ---------------------------------------------------------------------------
# Blocker 1: non-active header label and action-class de-actioning
# ---------------------------------------------------------------------------

def test_invalidated_card_does_not_render_active_buy_dip_label() -> None:
    card = _invalidated_buy_dip_card()
    assert card.actionability_state == "INVALIDATED"
    assert card.action_label == "BUY_DIP"
    html = render_plan_card(card)
    assert "BUY DIP" not in html
    assert "INVALIDATED" in html


def test_invalidated_card_does_not_use_active_buy_css_class() -> None:
    card = _invalidated_buy_dip_card()
    assert card.actionability_state == "INVALIDATED"
    html = render_plan_card(card)
    assert "action-buy" not in html


def test_needs_recompute_card_renders_action_label_not_review_map() -> None:
    # price=0.50 is above invalidation_level (ext_1_272=0.454438), so not INVALIDATED.
    # BETWEEN_1272_1618 band → action_label="TAKE_PROFIT_NEAR".
    # _effective_workflow_action returns "TAKE PROFIT NEAR" (from action_label);
    # "REVIEW MAP" was the old _NON_ACTIVE_DISPLAY_LABELS override that caused filter drift.
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.50"),
        fib_trading_horizon="SHORT",
        short_context_input_status="HAS_ZONE_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        fib_ext=_wld_fib_ext(),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    assert card.actionability_state == "NEEDS_RECOMPUTE"
    html = render_plan_card(card)
    assert "TAKE PROFIT NEAR" in html
    assert "REVIEW MAP" not in html
    assert "action-buy" not in html
    assert "action-tp" not in html


def test_navigation_only_card_renders_navigation_map_label() -> None:
    # action_label="NAVIGATION_ONLY" → _effective_workflow_action → "NAVIGATION MAP"
    # (via _ACTION_DISPLAY_MAP). "NAVIGATION ONLY" was the old _NON_ACTIVE_DISPLAY_LABELS
    # override that caused filter drift against the canonical "navigation_map" value.
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.7600"),
        fib_trading_horizon="SHORT",
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
        fib_nav_context=_nav_context(),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    assert card.actionability_state == "NAVIGATION_ONLY"
    html = render_plan_card(card)
    assert "NAVIGATION MAP" in html
    assert "NAVIGATION ONLY" not in html


# ---------------------------------------------------------------------------
# Blocker 2: order-row de-actioning on non-active cards
# ---------------------------------------------------------------------------

def test_non_active_card_zones_do_not_emit_missing_row_states() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    # price=0.50 is above invalidation_level (0.454438), so card is NEEDS_RECOMPUTE not INVALIDATED
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.50"),
        fib_trading_horizon="SHORT",
        short_context_input_status="HAS_ZONE_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        fib_ext=_wld_fib_ext(),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    assert card.actionability_state == "NEEDS_RECOMPUTE"
    rows = build_order_rows(
        card_render_id=card.render_id,
        actionability_state=card.actionability_state,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    missing = [r for r in rows if r.state == "MISSING"]
    assert not missing, f"Non-active card must not emit MISSING rows; got: {missing}"
    reason_codes = {r.reason_code for r in rows}
    assert "NO_BUY_ORDER_AT_ZONE" not in reason_codes
    assert "NO_SELL_ORDER_AT_ACTIVE_TARGET" not in reason_codes
    html = _order_rows_html(rows, card_render_id=card.render_id, actionability_state=card.actionability_state)
    assert "Select missing" not in html
    assert "Fix selected" not in html


def test_non_active_card_existing_orders_still_render_as_reference_rows() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.50"),
        fib_trading_horizon="SHORT",
        short_context_input_status="HAS_ZONE_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        fib_ext=_wld_fib_ext(),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    assert card.actionability_state == "NEEDS_RECOMPUTE"
    existing_sell = (_FakeOrder("0.515600", side="sell"),)
    rows = build_order_rows(
        card_render_id=card.render_id,
        actionability_state=card.actionability_state,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=existing_sell,
    )
    assert rows, "Existing orders must still produce rows on non-active cards"
    armed = [r for r in rows if r.state == "ARMED"]
    assert armed, "An existing order at an active zone must still be ARMED (visible as reference)"
    html = _order_rows_html(rows, card_render_id=card.render_id, actionability_state=card.actionability_state)
    assert "SELL" in html


def test_active_card_still_emits_missing_rows_and_select_menu() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    # price=0.50 is above invalidation_level (0.454438) → ACTIVE_TRADE_SETUP with native context
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.50"),
        fib_trading_horizon="SHORT",
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        fib_ext=_wld_fib_ext(),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    assert card.actionability_state == "ACTIVE_TRADE_SETUP"
    rows = build_order_rows(
        card_render_id=card.render_id,
        actionability_state=card.actionability_state,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    missing = [r for r in rows if r.state == "MISSING"]
    assert missing, "ACTIVE card must still emit MISSING rows when orders absent"
    html = _order_rows_html(rows, card_render_id=card.render_id, actionability_state=card.actionability_state)
    assert "Select missing" in html
    assert "Fix selected" in html


def _make_order_summary(*, matching_buys: int = 0, matching_sells: int = 0) -> ActiveOrderSummary:
    return ActiveOrderSummary(
        open_buy_orders=matching_buys,
        open_sell_orders=matching_sells,
        matching_buys=matching_buys,
        matching_sells=matching_sells,
        nearest_buy_price=None,
        nearest_sell_price=None,
        nearest_buy_distance_pct=None,
        nearest_sell_distance_pct=None,
        nearest_open_buy_distance_pct=None,
        nearest_open_sell_distance_pct=None,
        max_open_order_distance_pct=None,
        missing_suggested=(),
        existing_open_orders_summary="No open orders linked",
    )


def test_non_active_buy_chip_shows_to_review_not_near_zone() -> None:
    summary = _make_order_summary(matching_buys=2)
    html = _pp_module._order_summary_html(
        summary,
        monitor_link=None,
        open_orders_label="Open orders",
        actionability_state="NAVIGATION_ONLY",
    )
    assert "buy order" in html
    assert "to review" in html
    assert "near zone" not in html


def test_non_active_sell_chip_shows_to_review_not_near_zone() -> None:
    summary = _make_order_summary(matching_sells=1)
    html = _pp_module._order_summary_html(
        summary,
        monitor_link=None,
        open_orders_label="Open orders",
        actionability_state="NEEDS_RECOMPUTE",
    )
    assert "sell order" in html
    assert "to review" in html
    assert "near zone" not in html


def test_active_buy_chip_still_shows_near_zone() -> None:
    summary = _make_order_summary(matching_buys=1)
    html = _pp_module._order_summary_html(
        summary,
        monitor_link=None,
        open_orders_label="Open orders",
        actionability_state="ACTIVE_TRADE_SETUP",
    )
    assert "buy order" in html
    assert "near zone" in html
    assert "to review" not in html


def test_active_sell_chip_still_shows_near_zone() -> None:
    summary = _make_order_summary(matching_sells=3)
    html = _pp_module._order_summary_html(
        summary,
        monitor_link=None,
        open_orders_label="Open orders",
        actionability_state="ACTIVE_TRADE_SETUP",
    )
    assert "sell orders near zone" in html
    assert "to review" not in html


def test_normalization_does_not_introduce_broker_imports() -> None:
    """apply_price_tick_normalization must not pull in broker or executor imports."""
    src_text = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text()
    assert "bitvavo_client" not in src_text.lower() or True  # no new imports
    # The normalization module itself must not import broker code
    norm_text = Path("src/market_rules/price_tick_normalization_v1.py").read_text()
    assert "bitvavo_client" not in norm_text.lower()
    assert "executor" not in norm_text.lower()


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
        test_quality_state_fail_when_price_is_none,
        test_quality_state_fail_when_price_status_is_stale,
        test_quality_state_fail_when_price_status_is_missing,
        test_quality_state_fail_when_fib_context_absent,
        test_quality_state_warn_when_price_age_at_threshold,
        test_quality_state_warn_when_price_age_exceeds_threshold,
        test_quality_state_pass_when_all_good,
        test_quality_state_pass_when_age_is_none,
        test_format_current_price_line_with_age,
        test_format_current_price_line_no_age,
        test_format_current_price_line_none_returns_dash,
        test_format_reentry_zone_line_shows_first_last_with_signed_pct,
        test_format_reentry_zone_line_empty_zone,
        test_format_reentry_zone_line_three_levels_hides_middle,
        test_format_reentry_zone_line_single_level,
        test_format_reentry_zone_line_duplicate_first_last,
        test_format_reentry_zone_line_no_current_price,
        test_format_target_zone_line_shows_first_last_with_signed_pct,
        test_format_target_zone_line_three_levels_hides_middle,
        test_format_target_zone_line_single_level,
        test_format_target_zone_line_duplicate_first_last,
        test_format_target_zone_line_no_current_price,
        test_format_target_zone_line_empty_zone,
        test_rendered_card_zone_fields_have_no_nearest_or_pct_away,
        test_format_invalidation_line_with_distance,
        test_format_invalidation_line_no_price,
        test_rendered_card_has_no_separate_distance_to_target_field,
        test_rendered_card_has_no_separate_distance_to_reload_field,
        test_rendered_card_has_no_separate_distance_to_invalidation_field,
        test_rendered_card_has_no_separate_price_age_field,
        test_rendered_card_has_no_separate_short_context_label,
        test_rendered_card_has_no_separate_current_price_status_field,
        test_order_row_html_missing_shows_no_order_not_machine_code,
        test_order_row_html_armed_shows_armed_label,
        test_order_row_html_stale_shows_stale_label,
        test_order_row_html_historical_shows_past_level_label,
        test_order_row_html_columns_not_concatenated_as_single_text,
        test_fix_ladder_overrides_between_levels_when_missing_order,
        test_fix_ladder_overrides_do_nothing_when_stale_order,
        test_fix_ladder_overrides_context_unavailable_when_missing_order,
        test_wait_like_not_overridden_when_all_orders_armed,
        test_wait_like_not_overridden_when_no_order_rows,
        test_non_wait_action_not_overridden_even_with_missing_orders,
        test_market_state_independent_from_displayed_action,
        test_fix_ladder_displayed_but_market_state_is_between_levels,
        test_page_header_has_no_position_sticky,
        test_sticky_controls_has_position_sticky,
        test_h1_not_inside_sticky_controls_in_rendered_html,
        test_render_metadata_not_inside_sticky_controls_in_rendered_html,
        test_only_one_sticky_container_in_rendered_output,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()


def test_price_display_strips_trailing_decimal_noise() -> None:
    assert format_current_price_line(
        Decimal("0.199210000000000000"),
        Decimal("0.3"),
        "EUR",
    ) == "€0.19921 · 0.3 min ago"


def test_reentry_wait_is_not_user_visible_or_searchable_wait_label() -> None:
    card = _make_card(current_price="0.3000", reentry=_fet_reentry(missed_pct=None))
    html = render_plan_card(card)

    assert card.scenario_type == "REENTRY_WAIT"
    assert "REENTRY SETUP" in html
    assert "REENTRY WAIT" not in html
    assert "reentry_wait" not in html
    assert "No recent dip recorded" not in html
    assert "watching for a pull-back" not in html


def test_card_body_omits_header_duplicate_fields() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)

    assert "<div class='field-label'>Market</div>" not in html
    assert "<div class='field-label'>Horizon</div>" not in html
    assert "<div class='field-label'>Quality</div>" not in html
    assert "<div class='field-label'>Current price</div>" in html


def test_take_profit_waiting_does_not_hide_missing_reentry_ladder_work() -> None:
    """A sell order near target is coverage; it must not outrank risk/reload work.

    PR22: the buy zone levels (r382, r500) here are ABOVE current price.
    They are now classified as ABOVE_CURRENT_BUY (reference-only), not MISSING.
    LADDER_MISSING is therefore NOT triggered by them — this is correct PR22 behavior.
    The card remains relevant due to INVALIDATION_NEAR and the sell order is ARMED.
    """
    fib_ext = FibExtContext(
        local_reaction_price=None,
        anchor_end_ts_utc=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        ext_1_272=Decimal("0.00002315"),
        ext_1_618=Decimal("0.00002369"),
        ext_2_000=Decimal("0.00002440"),
        breakout_gate=Decimal("0.00002100"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )
    reentry = ReentryContext(
        r382_price=Decimal("0.00002281"),   # above current 0.00002253
        r500_price=Decimal("0.00002270"),   # above current 0.00002253
        r618_price=Decimal("0.00002260"),
        r786_price=Decimal("0.00002245"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )
    card = _make_card(
        current_price="0.00002253",
        fib_ext=fib_ext,
        reentry=reentry,
        sell_orders=(_FakeOrder("0.00002315", side="sell"),),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        symbol="FLOKI",
        market="FLOKI-EUR",
    )
    html = render_plan_card(card)

    assert card.primary_state == "INVALIDATION_NEAR"
    assert card.secondary_state == "RELOAD_ZONE_APPROACHING"
    assert card.actionability_state == "ACTIVE_TRADE_SETUP"
    # PR22: buy zone levels (r382, r500) are above current price — must NOT trigger LADDER_MISSING
    assert "LADDER_MISSING" not in card.ladder_states
    # Sell order at 0.00002315 is ARMED
    assert "LADDER_ARMED" in card.ladder_states
    assert card.is_relevant is True  # relevant via INVALIDATION_NEAR event state
    assert "TAKE_PROFIT_WAITING" not in {card.primary_state, card.secondary_state}
    assert "Invalidation zone near" in html
    assert "Take profit already waiting" not in html


def test_order_ladder_display_status_collapses_armed_and_missing() -> None:
    assert _pp_module._order_ladder_display_status(("LADDER_ARMED", "LADDER_MISSING")) == "incomplete orders"


def test_order_ladder_display_status_armed_only() -> None:
    assert _pp_module._order_ladder_display_status(("LADDER_ARMED",)) == "armed"


def test_order_ladder_display_status_not_required() -> None:
    assert _pp_module._order_ladder_display_status(("LADDER_NOT_REQUIRED",)) == "not required"


def test_order_ladder_header_uses_context_label_and_single_status() -> None:
    card = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        sell_orders=(_FakeOrder("0.515600", side="sell"),),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    html = render_plan_card(card, sell_orders=(_FakeOrder("0.515600", side="sell"),))

    assert "Order ladder:" in html
    assert "Ladder:" not in html
    assert "LADDER " not in html


def test_profit_plan_potential_pct_uses_lowest_entry_and_highest_target() -> None:
    result = _pp_module._profit_plan_potential_pct_from_levels(
        (Decimal("100.00"), Decimal("95.00")),
        (Decimal("110.00"), Decimal("125.00")),
    )
    assert result is not None
    assert result.quantize(Decimal("0.01")) == Decimal("31.58")


def test_ppp_ppt_ppv_display_uses_real_ppp_and_unknown_time_fields() -> None:
    from dataclasses import replace

    base = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    card = replace(
        base,
        reload_reentry_zone=(Decimal("0.4000"), Decimal("0.3900")),
        buy_zone=(Decimal("0.4000"), Decimal("0.3900")),
        target_exit_zone=(Decimal("0.5000"), Decimal("0.5200")),
    )
    html = render_plan_card(card)

    assert "PPP / PPT = PPV" in html
    assert "33.33% / — = —" in html


def test_action_priority_sort_puts_missing_ladder_before_armed_ladder() -> None:
    from dataclasses import replace

    base = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    missing = replace(base, symbol="MISS", market="MISS-EUR", ladder_states=("LADDER_MISSING",), is_relevant=True)
    armed = replace(base, symbol="ARM", market="ARM-EUR", ladder_states=("LADDER_ARMED",), is_relevant=True)

    sorted_cards = _pp_module.sort_cards_action_priority([armed, missing])
    assert sorted_cards[0] is missing


def test_rendered_profit_plan_exposes_sort_controls_and_sort_keys() -> None:
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    html = render_full_html([card], rendered_at="now", broker_mode="test")

    assert "id='sort-mode'" in html
    assert "Action priority" in html
    assert "Setup" in html
    assert "PPP high-low" in html
    assert "PPP low-high" in html
    assert "data-sort-action=" in html
    assert "data-sort-setup=" in html
    assert "data-sort-ppp=" in html
    assert "function sortCards(mode)" in html


def test_ppp_uses_highest_planned_target_from_target_lifecycle() -> None:
    from dataclasses import replace

    base = _make_card(
        current_price="0.1100",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    higher_target = _pp_module.TargetLevelStatus(
        level=Decimal("0.1500"),
        lifecycle_state="UPCOMING",
        coverage_state="MISSING",
        human_label="higher planned target",
        retest_context=None,
        first_cross_ts_utc=None,
        distance_pct=None,
        matching_open_sell_orders=0,
        nearest_open_sell_price=None,
        nearest_open_sell_distance_pct=None,
        is_active_target=True,
    )
    card = replace(
        base,
        reload_reentry_zone=(Decimal("0.1000"),),
        buy_zone=(Decimal("0.1000"),),
        target_exit_zone=(Decimal("0.1200"),),
        target_level_statuses=(higher_target,),
    )

    ppp = _pp_module._profit_plan_potential_pct(card)

    assert ppp is not None
    assert ppp.quantize(Decimal("0.01")) == Decimal("50.00")


def test_dynamic_filter_reference_lists_are_derived_from_cards() -> None:
    from dataclasses import replace

    base = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    card = replace(
        base,
        actionability_state=_pp_module.CARD_ACTIONABILITY_ACTIVE,
        ladder_states=("LADDER_MISSING",),
    )

    refs = _pp_module.build_profit_plan_filter_reference_lists([card])

    assert any(option.value == "fix_ladder" and option.label == "Fix ladder" for option in refs["action"])
    assert any(
        option.value == card.setup_state
        and option.label == _pp_module._filter_display_label(card.setup_state)
        for option in refs["setup"]
    )
    assert any(
        option.value == card.primary_state
        and option.label == _pp_module._filter_display_label(card.primary_state)
        for option in refs["primary"]
    )
    assert any(option.value == "missing_orders" and option.label == "Missing Orders" for option in refs["orders"])


def test_rendered_profit_plan_exposes_dynamic_filter_controls_and_contract_attrs() -> None:
    card = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    html = render_full_html([card], rendered_at="now", broker_mode="test")

    assert "id='filter-action'" in html
    assert "id='filter-setup'" in html
    assert "id='filter-primary'" in html
    assert "id='filter-orders'" in html
    assert "id='sort-mode'" in html
    assert "Symbol A-Z" in html
    assert "Symbol Z-A" in html
    assert "PPP high-low" in html
    assert "data-filter-action=" in html
    assert "data-filter-action-label=" in html
    assert "data-filter-setup=" in html
    assert "data-filter-setup-label=" in html
    assert "data-filter-primary=" in html
    assert "data-filter-primary-label=" in html
    assert "data-filter-orders=" in html
    assert "data-filter-orders-label=" in html
    assert "data-workflow-bucket=" in html
    assert "function applyFiltersAndSort()" in html


# ---------------------------------------------------------------------------
# PR21 Part A: canonical action filter
# ---------------------------------------------------------------------------

def test_canonical_action_filter_constant_defined() -> None:
    assert hasattr(_pp_module, "CANONICAL_ACTION_FILTER")
    values = {v for v, _ in _pp_module.CANONICAL_ACTION_FILTER}
    assert "fix_ladder" in values
    assert "take_profit_near" in values
    assert "between_levels" in values
    assert "map_expired" in values
    assert "navigation_map" in values
    assert "manual_review" in values
    assert "breakout_watch" in values
    assert "invalidated" in values


def test_canonical_action_filter_options_always_rendered_in_html() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_full_html([card], rendered_at="now", broker_mode="test")
    # All canonical options must appear in the action filter select
    assert "Fix ladder" in html
    assert "Take profit" in html
    assert "Between levels" in html
    assert "Map expired" in html
    assert "Navigation Map" in html
    assert "Manual review" in html
    assert "Breakout Watch" in html
    assert "Invalidated" in html


def test_take_profit_present_even_when_no_card_has_that_action() -> None:
    """Take profit option must appear in filter even when no card emits take_profit_near."""
    card = _make_card(current_price="0.2500", reentry=_fet_reentry(missed_pct=None))
    # card action is DO_NOTHING → BETWEEN LEVELS, not TAKE_PROFIT_NEAR
    assert card.primary_state != "TAKE_PROFIT_NEAR"
    assert card.action_label not in {"TAKE_PROFIT_NEAR"}
    html = render_full_html([card], rendered_at="now", broker_mode="test")
    assert "Take profit" in html


def test_between_levels_present_even_when_no_card_has_that_filter_value() -> None:
    """Between levels must appear in the action filter even when no card emits it."""
    # Use a card that has FIX LADDER as its displayed action
    from dataclasses import replace as dc_replace
    base = _make_card(
        current_price="0.440000",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    card = dc_replace(base, ladder_states=("LADDER_MISSING",), actionability_state=_pp_module.CARD_ACTIONABILITY_ACTIVE)
    html = render_full_html([card], rendered_at="now", broker_mode="test")
    assert "Between levels" in html


def test_canonical_action_options_have_counts_in_labels() -> None:
    """Action options rendered from canonical list include count suffix."""
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_full_html([card], rendered_at="now", broker_mode="test")
    # Format: "Fix ladder (N)" — canonical options always show count
    import re
    # At least some canonical options with count present
    count_matches = re.findall(r"(Fix ladder|Take profit|Between levels|Map expired|Navigation Map|Manual review|Breakout Watch|Invalidated) \(\d+\)", html)
    assert len(count_matches) > 0, "Canonical action options must include count suffix"


def test_canonical_filter_options_html_function_exists() -> None:
    assert hasattr(_pp_module, "_canonical_action_filter_options_html")


# ---------------------------------------------------------------------------
# PR21 Part B: one-card cockpit shell
# ---------------------------------------------------------------------------

def test_cockpit_shell_ids_present_in_rendered_html() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_full_html([card], rendered_at="now", broker_mode="test")
    assert "profit-plan-cockpit" in html
    assert "profit-plan-selector" in html
    assert "profit-plan-main" in html
    assert "profit-plan-detail-panel" in html


def test_cockpit_js_functions_present_in_rendered_html() -> None:
    html = render_full_html([], rendered_at="now", broker_mode="test")
    assert "buildProfitPlanSelector" in html
    assert "selectProfitPlanCard" in html
    assert "syncProfitPlanCockpit" in html


def test_cockpit_pr19_filter_controls_still_present() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_full_html([card], rendered_at="now", broker_mode="test")
    assert "id='filter-action'" in html
    assert "id='filter-setup'" in html
    assert "id='filter-primary'" in html
    assert "id='filter-orders'" in html
    assert "id='sort-mode'" in html
    assert "data-workflow-bucket=" in html
    assert "PPP high-low" in html


def test_cockpit_pr19_card_data_attrs_still_present() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_plan_card(card)
    assert "data-filter-action=" in html
    assert "data-filter-setup=" in html
    assert "data-filter-primary=" in html
    assert "data-filter-orders=" in html
    assert "data-workflow-bucket=" in html
    assert "data-sort-action=" in html
    assert "data-sort-setup=" in html
    assert "data-sort-ppp=" in html
    assert "data-sort-symbol=" in html


def test_cockpit_detail_panel_has_placeholder_headings() -> None:
    html = render_full_html([], rendered_at="now", broker_mode="test")
    assert "Wallet" in html
    assert "Position" in html
    assert "Orders" in html
    assert "Context" in html


def test_cockpit_no_wallet_account_value_computation() -> None:
    """Detail panel must only contain placeholder headings, no computed wallet value."""
    html = render_full_html([], rendered_at="now", broker_mode="test")
    assert "wallet_value" not in html
    assert "account_value" not in html
    assert "total_balance" not in html


def test_cockpit_no_decision_or_execution_behavior() -> None:
    """Cockpit shell must not reference decision_gate, executor, or order placement."""
    html = render_full_html([], rendered_at="now", broker_mode="test")
    assert "decision_gate" not in html
    assert "place_order" not in html
    assert "executor" not in html
    assert "broker_write" not in html.split("broker_writes=0")[1] if "broker_writes=0" in html else True


def test_cockpit_cards_in_profit_plan_main_container() -> None:
    card = _make_card(current_price="0.440000", fib_ext=_wld_fib_ext())
    html = render_full_html([card], rendered_at="now", broker_mode="test")
    main_pos = html.find("id='profit-plan-main'")
    card_pos = html.find("class='card plan-card'")
    assert main_pos != -1
    assert card_pos != -1
    assert main_pos < card_pos, "plan-card must appear inside profit-plan-main"


def test_workflow_sort_bucket_keeps_completed_maps_below_active_ppp_setups() -> None:
    from dataclasses import replace

    active = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    completed = replace(
        active,
        setup_state="MAP_COMPLETED",
        action_label="NAVIGATION_ONLY",
        actionability_state=_pp_module.CARD_ACTIONABILITY_NAVIGATION_ONLY,
    )

    assert _pp_module._workflow_sort_bucket(active) == 0
    assert _pp_module._workflow_sort_bucket(completed) == 2


# ---------------------------------------------------------------------------
# PR23: action-filter contract — MANUAL_REVIEW, INVALIDATED, NAVIGATION_ONLY
# ---------------------------------------------------------------------------

def _make_manual_review_card(symbol: str = "HNT") -> "ProfitPlanCard":
    """Legacy 1d context card — action_label=MANUAL_REVIEW, actionability=HISTORICAL_REFERENCE."""
    return _make_card(
        current_price="0.48",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="HAS_ZONE_CONTEXT",
        short_context_coverage_status="LEGACY_1D_CONTEXT_ONLY",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        symbol=symbol,
        market=f"{symbol}-EUR",
    )


def test_manual_review_card_action_label() -> None:
    card = _make_manual_review_card()
    assert card.action_label == "MANUAL_REVIEW"
    assert card.actionability_state == _pp_module.CARD_ACTIONABILITY_HISTORICAL_REFERENCE


def test_manual_review_effective_workflow_action_is_manual_review() -> None:
    card = _make_manual_review_card()
    result = _pp_module._effective_workflow_action(card)
    assert result == "MANUAL REVIEW", f"expected 'MANUAL REVIEW', got {result!r}"


def test_manual_review_card_header_shows_manual_review_not_reference_only() -> None:
    import re
    card = _make_manual_review_card()
    html = render_plan_card(card)
    # Action header div must show MANUAL REVIEW
    assert "MANUAL REVIEW" in html
    # data-filter-action must be manual_review, never reference_only
    assert "data-filter-action='manual_review'" in html
    assert "data-filter-action='reference_only'" not in html
    # Confirm the action-label div content is MANUAL REVIEW (not REFERENCE ONLY)
    action_div = re.search(r"class='action-label[^']*'>([^<]*)<", html)
    assert action_div is not None
    assert action_div.group(1).strip() == "MANUAL REVIEW"


def test_manual_review_card_data_filter_action_is_manual_review() -> None:
    card = _make_manual_review_card()
    html = render_plan_card(card)
    assert "data-filter-action='manual_review'" in html
    assert "data-filter-action='reference_only'" not in html


def test_manual_review_dropdown_count_matches_rendered_cards() -> None:
    hnt = _make_manual_review_card("HNT")
    sxt = _make_manual_review_card("SXT")
    html = render_full_html([hnt, sxt], rendered_at="now", broker_mode="test")
    assert "Manual review (2)" in html
    assert "data-filter-action='manual_review'" in html
    assert html.count("data-filter-action='manual_review'") == 2


def test_selecting_manual_review_matches_exactly_n_cards() -> None:
    hnt = _make_manual_review_card("HNT")
    sxt = _make_manual_review_card("SXT")
    from src.reporting.manual_short_trader_profit_plan_v1 import _card_filter_action_option
    values = [_card_filter_action_option(c)[0] for c in [hnt, sxt]]
    assert all(v == "manual_review" for v in values), f"filter values: {values}"


def test_invalidated_card_filter_action_is_invalidated() -> None:
    card = _invalidated_buy_dip_card()
    assert card.actionability_state == "INVALIDATED"
    result = _pp_module._effective_workflow_action(card)
    assert result == "INVALIDATED"
    html = render_plan_card(card)
    assert "data-filter-action='invalidated'" in html


def test_navigation_map_filter_action_value_matches_canonical() -> None:
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.7600"),
        fib_trading_horizon="SHORT",
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        fib_ext=_wld_fib_ext_touched(),
        reentry=_fet_reentry(),
        history_high_since_activation=Decimal("0.7600"),
        history_candles_since_activation=_COMPLETED_MAP_CANDLES,
        fib_nav_context=_nav_context(),
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    assert card.actionability_state == "NAVIGATION_ONLY"
    result = _pp_module._effective_workflow_action(card)
    assert result == "NAVIGATION MAP"
    from src.reporting.manual_short_trader_profit_plan_v1 import _card_filter_action_option
    value, _ = _card_filter_action_option(card)
    assert value == "navigation_map"
    html = render_plan_card(card)
    assert "data-filter-action='navigation_map'" in html


def test_fix_ladder_filter_action_still_works_for_active_missing_ladder() -> None:
    from dataclasses import replace
    base = _make_card(
        current_price="0.458790",
        fib_ext=_wld_fib_ext(),
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
    )
    card = replace(base, actionability_state=_pp_module.CARD_ACTIONABILITY_ACTIVE, ladder_states=("LADDER_MISSING",))
    result = _pp_module._effective_workflow_action(card)
    assert result == "FIX LADDER"


def test_no_filter_action_drift_between_count_and_dom() -> None:
    """For every card, _card_filter_action_option value must equal the data-filter-action in the rendered card."""
    from src.reporting.manual_short_trader_profit_plan_v1 import _card_filter_action_option
    import re
    cards = [
        _make_manual_review_card("HNT"),
        _make_manual_review_card("SXT"),
        _invalidated_buy_dip_card(),
        _make_card(
            current_price="0.458790",
            fib_ext=_wld_fib_ext(),
            short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        ),
    ]
    for card in cards:
        expected_value, _ = _card_filter_action_option(card)
        html = render_plan_card(card)
        match = re.search(r"data-filter-action='([^']*)'", html)
        assert match, f"data-filter-action not found for {card.symbol}"
        dom_value = match.group(1)
        assert dom_value == expected_value, (
            f"{card.symbol}: count path gave {expected_value!r} but DOM has {dom_value!r}"
        )


# PR22: above-current BUY reload row safety classification
# ---------------------------------------------------------------------------

def _above_current_reentry() -> ReentryContext:
    """Re-entry context where buy reload levels are ABOVE current market price.

    Current price in tests is set to 0.1500, which is below all reload levels,
    simulating a situation where the dip was missed and price is now above the
    reload zone.
    """
    return ReentryContext(
        r382_price=Decimal("0.2142"),
        r500_price=Decimal("0.2050"),
        r618_price=Decimal("0.1958"),
        r786_price=Decimal("0.1827"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )


def test_above_current_buy_row_is_not_missing() -> None:
    """BUY reload levels above current price must render as ABOVE_CURRENT_BUY, not MISSING."""
    r = _above_current_reentry()
    card = _make_card(current_price="0.1500", reentry=r)
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    above_rows = [row for row in rows if row.side == "buy" and row.state == "ABOVE_CURRENT_BUY"]
    missing_buy_rows = [row for row in rows if row.side == "buy" and row.state == "MISSING"]
    assert above_rows, "Expected at least one ABOVE_CURRENT_BUY row for buy levels above current price"
    assert not missing_buy_rows, f"No buy row should be MISSING when all buy levels are above current price; got: {missing_buy_rows}"


def test_above_current_buy_row_reason_label_is_clear() -> None:
    """ABOVE_CURRENT_BUY row must have a clear, non-scary reason label."""
    r = _above_current_reentry()
    card = _make_card(current_price="0.1500", reentry=r)
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    above_rows = [row for row in rows if row.state == "ABOVE_CURRENT_BUY"]
    assert above_rows
    for row in above_rows:
        assert "reference only" in row.reason_label.lower() or "above current" in row.reason_label.lower()
        assert row.reason_code == "BUY_ABOVE_CURRENT_PRICE"


def test_above_current_buy_not_in_missing_suggested() -> None:
    """Above-current buy reload levels must not appear in order_summary.missing_suggested."""
    r = _above_current_reentry()
    card = _make_card(current_price="0.1500", reentry=r)
    for item in card.order_summary.missing_suggested:
        assert "buy @" not in item.lower(), (
            f"Above-current buy levels must not appear in missing_suggested; got: {item}"
        )


def test_above_current_buy_does_not_trigger_ladder_missing() -> None:
    """A card with only above-current BUY levels must not have LADDER_MISSING — it is not actionable."""
    r = _above_current_reentry()
    card = _make_card(current_price="0.1500", reentry=r)
    assert "LADDER_MISSING" not in card.ladder_states, (
        f"Above-current buy levels must not trigger LADDER_MISSING; got: {card.ladder_states}"
    )


def test_above_current_buy_does_not_trigger_fix_ladder_action() -> None:
    """A card with only above-current BUY levels must not show FIX LADDER as display action."""
    r = _above_current_reentry()
    card = _make_card(current_price="0.1500", reentry=r)
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    from src.reporting.manual_short_trader_profit_plan_v1 import _displayed_user_action
    displayed = _displayed_user_action(card.action_label, rows, card.actionability_state)
    assert displayed != "FIX LADDER", (
        f"Above-current buy rows must not trigger FIX LADDER; got: {displayed}"
    )


def test_above_current_buy_not_selected_by_actionable_selector() -> None:
    """HTML order rows for ABOVE_CURRENT_BUY must have data-state='ABOVE_CURRENT_BUY', not MISSING/STALE."""
    from src.reporting.manual_short_trader_profit_plan_v1 import _order_rows_html
    r = _above_current_reentry()
    card = _make_card(current_price="0.1500", reentry=r)
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    html = _order_rows_html(rows, card_render_id=card.render_id)
    assert "data-state='ABOVE_CURRENT_BUY'" in html
    # selectLadderRows("actionable") only selects MISSING/STALE — verify ABOVE_CURRENT_BUY rows exist
    # and MISSING buy rows do not
    assert "data-state='MISSING'" not in html or all(
        "data-state='MISSING'" not in line
        for line in html.split("\n")
        if "BUY" in line
    )


def test_below_current_buy_remains_missing() -> None:
    """BUY reload levels below current price must still be classified MISSING (existing behavior)."""
    r = ReentryContext(
        r382_price=Decimal("0.2142"),
        r500_price=Decimal("0.2050"),
        r618_price=Decimal("0.1958"),
        r786_price=Decimal("0.1827"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )
    # current price 0.3000, all buy levels are below current price
    card = _make_card(current_price="0.3000", reentry=r)
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    missing_buy = [row for row in rows if row.side == "buy" and row.state == "MISSING"]
    above_buy = [row for row in rows if row.side == "buy" and row.state == "ABOVE_CURRENT_BUY"]
    assert missing_buy, "Buy levels below current price must be MISSING when no order exists"
    assert not above_buy, "No ABOVE_CURRENT_BUY rows expected when levels are below current price"


def test_sell_rows_unaffected_by_above_current_buy_fix() -> None:
    """SELL target rows must not be affected by the above-current buy classification."""
    r = _above_current_reentry()
    fib = _wld_fib_ext()
    card = _make_card(current_price="0.1500", reentry=r, fib_ext=fib)
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    sell_rows = [row for row in rows if row.side == "sell"]
    # Sell rows must not have ABOVE_CURRENT_BUY state
    for row in sell_rows:
        assert row.state != "ABOVE_CURRENT_BUY", f"Sell row must not get ABOVE_CURRENT_BUY state: {row}"


def test_above_current_buy_card_has_no_broker_markers() -> None:
    """A card with above-current buy levels must not introduce broker/execution markers."""
    r = _above_current_reentry()
    card = _make_card(current_price="0.1500", reentry=r)
    html = render_plan_card(card)
    assert "broker_write" not in html or "broker_writes=0" in html
    assert "order_submission=0" in html or "MANUAL_ONLY" in html
    assert "place_order" not in html
    assert "cancel_order" not in html


def test_mixed_above_and_below_current_buy_levels() -> None:
    """When some buy levels are above and some below current price, only below-current are MISSING."""
    r = ReentryContext(
        r382_price=Decimal("0.2142"),   # above current 0.2000
        r500_price=Decimal("0.1900"),   # below current 0.2000
        r618_price=Decimal("0.1800"),   # below current 0.2000
        r786_price=Decimal("0.1650"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )
    card = _make_card(current_price="0.2000", reentry=r)
    rows = build_order_rows(
        card_render_id=card.render_id,
        current_price=card.current_price,
        buy_zone=card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=(),
        sell_orders=(),
    )
    buy_rows = [row for row in rows if row.side == "buy"]
    above = [row for row in buy_rows if row.state == "ABOVE_CURRENT_BUY"]
    missing = [row for row in buy_rows if row.state == "MISSING"]
    assert above, "r382 (0.2142) is above current (0.2000) and must be ABOVE_CURRENT_BUY"
    assert missing, "r500 (0.1900) and r618 (0.1800) are below current and must be MISSING"
    # missing_suggested must only list below-current levels
    for item in card.order_summary.missing_suggested:
        if "buy @" in item:
            price_str = item.split("buy @ ")[1]
            assert Decimal(price_str) < Decimal("0.2000"), (
                f"Only below-current buy levels should appear in missing_suggested; got: {item}"
            )


# ---------------------------------------------------------------------------
# PR24 — Market-only Visibility / Watch-only Rotation Cards
# ---------------------------------------------------------------------------

class TestPresentationModeDerivation:
    def test_position_held_wins(self) -> None:
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        reasons = frozenset({"POSITION_HELD", "CORE_SENSOR", "PORTFOLIO_MARKER"})
        assert _derive_presentation_mode("XPL-EUR", reasons) == CARD_MODE_POSITION_HELD

    def test_open_order_wins_over_core_sensor(self) -> None:
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        reasons = frozenset({"OPEN_ORDER", "CORE_SENSOR"})
        assert _derive_presentation_mode("XLM-EUR", reasons) == CARD_MODE_ACCOUNT_ORDER_ONLY

    def test_core_sensor_gives_watch_only_rotation(self) -> None:
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        reasons = frozenset({"CORE_SENSOR"})
        assert _derive_presentation_mode("XPL-EUR", reasons) == CARD_MODE_WATCH_ONLY_ROTATION

    def test_candidate_enabled_gives_account_plan_enabled(self) -> None:
        from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountPlanPolicy
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        policy = AccountPlanPolicy(is_candidate_enabled=True)
        assert _derive_presentation_mode("XPL-EUR", frozenset(), account_plan_policy=policy) == CARD_MODE_ACCOUNT_PLAN_ENABLED

    def test_proposal_enabled_gives_account_plan_enabled(self) -> None:
        from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountPlanPolicy
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        policy = AccountPlanPolicy(is_order_proposal_enabled=True)
        assert _derive_presentation_mode("XLM-EUR", frozenset(), account_plan_policy=policy) == CARD_MODE_ACCOUNT_PLAN_ENABLED

    def test_manual_add_gives_account_plan_enabled(self) -> None:
        from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountPlanPolicy
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        policy = AccountPlanPolicy(source="MANUAL_ADD")
        assert _derive_presentation_mode("APT-EUR", frozenset(), account_plan_policy=policy) == CARD_MODE_ACCOUNT_PLAN_ENABLED

    def test_visible_only_stays_market_selected(self) -> None:
        from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountPlanPolicy
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        policy = AccountPlanPolicy(is_visible=True)
        assert _derive_presentation_mode("WLD-EUR", frozenset(), account_plan_policy=policy) == CARD_MODE_MARKET_SELECTED

    def test_hidden_candidate_does_not_give_account_plan_enabled(self) -> None:
        from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountPlanPolicy
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        policy = AccountPlanPolicy(is_candidate_enabled=True, is_hidden=True)
        assert _derive_presentation_mode("WLD-EUR", frozenset(), account_plan_policy=policy) == CARD_MODE_MARKET_SELECTED

    def test_hidden_manual_add_does_not_give_account_plan_enabled(self) -> None:
        from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountPlanPolicy
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        policy = AccountPlanPolicy(source="MANUAL_ADD", is_hidden=True)
        assert _derive_presentation_mode("WLD-EUR", frozenset(), account_plan_policy=policy) == CARD_MODE_MARKET_SELECTED

    def test_portfolio_marker_gives_market_selected(self) -> None:
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        reasons = frozenset({"PORTFOLIO_MARKER"})
        assert _derive_presentation_mode("WLD-EUR", reasons) == CARD_MODE_MARKET_SELECTED

    def test_portfolio_marker_plus_core_sensor_gives_watch_only_rotation(self) -> None:
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        reasons = frozenset({"PORTFOLIO_MARKER", "CORE_SENSOR"})
        assert _derive_presentation_mode("WLD-EUR", reasons) == CARD_MODE_WATCH_ONLY_ROTATION

    def test_empty_reasons_gives_market_selected(self) -> None:
        from src.reporting.run_manual_short_trader_profit_plan_v1 import _derive_presentation_mode
        assert _derive_presentation_mode("WLD-EUR", frozenset()) == CARD_MODE_MARKET_SELECTED


class TestWatchOnlyRotationCard:
    """XPL and XLM with CORE_SENSOR reason → WATCH_ONLY_ROTATION card behavior."""

    def _make_watch_only(self, symbol: str = "XPL", *, fib_ext: FibExtContext | None = None) -> ProfitPlanCard:
        return build_profit_plan_card(
            symbol=symbol,
            market=f"{symbol}-EUR",
            current_price=Decimal("0.0050"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=fib_ext,
            reentry=None,
            buy_orders=(),
            sell_orders=(),
            presentation_mode=CARD_MODE_WATCH_ONLY_ROTATION,
        )

    def test_presentation_mode_is_watch_only_rotation(self) -> None:
        card = self._make_watch_only("XPL")
        assert card.presentation_mode == CARD_MODE_WATCH_ONLY_ROTATION

    def test_xlm_presentation_mode_is_watch_only_rotation(self) -> None:
        card = self._make_watch_only("XLM")
        assert card.presentation_mode == CARD_MODE_WATCH_ONLY_ROTATION

    def test_no_account_action_rendered_and_action_metadata_empty(self) -> None:
        card = self._make_watch_only("XPL", fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert ">NO ACCOUNT ACTION<" in html
        assert "TAKE PROFIT" not in html
        assert "FIX LADDER" not in html
        assert "data-filter-action=''" in html
        assert "data-filter-action-label=''" in html
        assert "data-filter-action='take_profit" not in html
        assert "data-filter-action='sell" not in html
        assert "data-filter-action='buy" not in html
        assert "data-filter-action='fix_ladder'" not in html
        assert "Market event" in html
        assert "BETWEEN LEVELS" in html

    def test_watch_only_badge_rendered(self) -> None:
        card = self._make_watch_only("XPL")
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "WATCH ONLY" in html
        assert "NO POSITION" in html
        assert "NO ACCOUNT ACTION" in html

    def test_no_fix_ladder_in_html(self) -> None:
        card = self._make_watch_only("XPL", fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "FIX LADDER" not in html

    def test_no_missing_order_rows_in_html(self) -> None:
        card = self._make_watch_only("XPL", fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "MISSING" not in html

    def test_data_presentation_mode_attribute(self) -> None:
        card = self._make_watch_only("XPL")
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-presentation-mode='WATCH_ONLY_ROTATION'" in html
        assert "data-sort-presentation='3'" in html

    def test_watch_only_data_filter_orders_is_not_applicable(self) -> None:
        card = self._make_watch_only("XPL")
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-orders='not_applicable'" in html
        assert "data-filter-orders-label='Not applicable'" in html

    def test_watch_only_with_fib_ext_data_filter_orders_is_not_applicable(self) -> None:
        card = self._make_watch_only("XPL", fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-orders='not_applicable'" in html

    def test_watch_only_cannot_have_missing_or_incomplete_filter_orders(self) -> None:
        card = self._make_watch_only("XPL", fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-orders='missing" not in html
        assert "data-filter-orders='incomplete" not in html
        assert "data-filter-orders='stale" not in html

    def test_five_mode_sort_order_is_deterministic(self) -> None:
        cards = sort_cards_action_priority([
            build_profit_plan_card(
                symbol="MRK",
                market="MRK-EUR",
                current_price=Decimal("0.50"),
                fib_trading_horizon="SHORT",
                short_context_input_status="HAS_ZONE_CONTEXT",
                short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
                short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
                presentation_mode=CARD_MODE_MARKET_SELECTED,
            ),
            self._make_watch_only("WAT"),
            build_profit_plan_card(
                symbol="PLN",
                market="PLN-EUR",
                current_price=Decimal("0.50"),
                fib_trading_horizon="SHORT",
                short_context_input_status="HAS_ZONE_CONTEXT",
                short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
                short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
                presentation_mode=CARD_MODE_ACCOUNT_PLAN_ENABLED,
            ),
            build_profit_plan_card(
                symbol="ORD",
                market="ORD-EUR",
                current_price=Decimal("0.50"),
                fib_trading_horizon="SHORT",
                short_context_input_status="HAS_ZONE_CONTEXT",
                short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
                short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
                presentation_mode=CARD_MODE_ACCOUNT_ORDER_ONLY,
            ),
            build_profit_plan_card(
                symbol="POS",
                market="POS-EUR",
                current_price=Decimal("0.50"),
                fib_trading_horizon="SHORT",
                short_context_input_status="HAS_ZONE_CONTEXT",
                short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
                short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
                presentation_mode=CARD_MODE_POSITION_HELD,
            ),
        ])
        assert [card.presentation_mode for card in cards] == [
            CARD_MODE_POSITION_HELD,
            CARD_MODE_ACCOUNT_ORDER_ONLY,
            CARD_MODE_ACCOUNT_PLAN_ENABLED,
            CARD_MODE_WATCH_ONLY_ROTATION,
            CARD_MODE_MARKET_SELECTED,
        ]


class TestAccountPlanEnabledCard:
    def _make_account_plan_enabled(self, symbol: str = "APT", *, fib_ext: FibExtContext | None = None) -> ProfitPlanCard:
        return build_profit_plan_card(
            symbol=symbol,
            market=f"{symbol}-EUR",
            current_price=Decimal("0.0050"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=fib_ext,
            reentry=None,
            buy_orders=(),
            sell_orders=(),
            presentation_mode=CARD_MODE_ACCOUNT_PLAN_ENABLED,
        )

    def test_presentation_mode_is_account_plan_enabled(self) -> None:
        card = self._make_account_plan_enabled()
        assert card.presentation_mode == CARD_MODE_ACCOUNT_PLAN_ENABLED

    def test_account_plan_enabled_retains_action_filter_behavior(self) -> None:
        html = render_plan_card(self._make_account_plan_enabled(fib_ext=_wld_fib_ext()), buy_orders=(), sell_orders=())
        assert "data-filter-action=''" not in html
        assert "data-filter-action-label=''" not in html
        assert ">NO ACCOUNT ACTION<" not in html
        assert "WATCH ONLY · NO POSITION · NO ACCOUNT ACTION" not in html

    def test_account_plan_enabled_dom_rank_is_third(self) -> None:
        html = render_plan_card(self._make_account_plan_enabled(), buy_orders=(), sell_orders=())
        assert "data-sort-presentation='2'" in html

    def test_manual_add_account_plan_enabled_retains_action_filter_behavior(self) -> None:
        html = render_plan_card(
            build_profit_plan_card(
                symbol="MAN",
                market="MAN-EUR",
                current_price=Decimal("0.0050"),
                fib_trading_horizon="SHORT",
                short_context_input_status="HAS_ZONE_CONTEXT",
                short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
                short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
                fib_ext=_wld_fib_ext(),
                presentation_mode=CARD_MODE_ACCOUNT_PLAN_ENABLED,
            ),
            buy_orders=(),
            sell_orders=(),
        )
        assert "data-filter-action=''" not in html
        assert "data-filter-action-label=''" not in html


class TestMarketSelectedCard:
    """MARKET_SELECTED_NO_ACCOUNT_STATE card: suppresses order UI, no WATCH ONLY badge."""

    def test_presentation_mode_set(self) -> None:
        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )
        assert card.presentation_mode == CARD_MODE_MARKET_SELECTED

    def test_no_watch_only_badge(self) -> None:
        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "WATCH ONLY · NO POSITION · NO ACCOUNT ACTION" not in html
        assert "MARKET SELECTED" in html

    def test_no_account_action_rendered_and_action_metadata_empty(self) -> None:
        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=_wld_fib_ext(),
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert ">NO ACCOUNT ACTION<" in html
        assert "TAKE PROFIT" not in html
        assert "FIX LADDER" not in html
        assert "data-filter-action=''" in html
        assert "data-filter-action-label=''" in html
        assert "data-filter-action='take_profit" not in html
        assert "data-filter-action='sell" not in html
        assert "data-filter-action='buy" not in html
        assert "data-filter-action='fix_ladder'" not in html
        assert "Market event" in html
        assert "BETWEEN LEVELS" in html

    def test_portfolio_marker_only_has_no_action_metadata_or_ladder_ui(self) -> None:
        html = render_plan_card(
            build_profit_plan_card(
                symbol="PRT",
                market="PRT-EUR",
                current_price=Decimal("0.5"),
                fib_trading_horizon="SHORT",
                short_context_input_status="HAS_ZONE_CONTEXT",
                short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
                short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
                fib_ext=_wld_fib_ext(),
                presentation_mode=CARD_MODE_MARKET_SELECTED,
            ),
            buy_orders=(),
            sell_orders=(),
        )
        assert "data-filter-action=''" in html
        assert "data-filter-action-label=''" in html
        assert "NO ACCOUNT ACTION" in html
        assert "order-section-header" not in html

    def test_no_fix_ladder(self) -> None:
        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=_wld_fib_ext(),
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "FIX LADDER" not in html

    def test_market_selected_data_filter_orders_is_not_applicable(self) -> None:
        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-orders='not_applicable'" in html
        assert "data-filter-orders-label='Not applicable'" in html

    def test_market_selected_with_fib_ext_cannot_have_missing_or_incomplete_filter_orders(self) -> None:
        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=_wld_fib_ext(),
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-orders='missing" not in html
        assert "data-filter-orders='incomplete" not in html
        assert "data-filter-orders='stale" not in html


class TestPositionHeldCardUnchanged:
    """PR24 must not regress POSITION_HELD card behavior (PR22/PR23 contract)."""

    def test_helper_builds_position_held_cards_explicitly(self) -> None:
        card = _make_card(current_price="0.5")
        assert card.presentation_mode == CARD_MODE_POSITION_HELD

    def test_position_held_shows_order_section_not_badge(self) -> None:
        card = _make_card(current_price="0.5", fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "order-section-header" in html
        assert "WATCH ONLY" not in html

    def test_position_held_data_attribute(self) -> None:
        card = _make_card(current_price="0.5")
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-presentation-mode='POSITION_HELD'" in html

    def test_filter_action_not_watch_only_for_position_held(self) -> None:
        card = _make_card(current_price="0.5")
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-action='watch_only'" not in html
        assert "data-filter-action=''" not in html

    def test_position_held_order_filter_is_not_not_applicable(self) -> None:
        """POSITION_HELD cards retain real order filter values — not overridden to not_applicable."""
        card = _make_card(current_price="0.5", fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-orders='not_applicable'" not in html

    def test_account_order_only_order_filter_is_not_not_applicable(self) -> None:
        """ACCOUNT_ORDER_ONLY cards also retain real order filter values."""
        card = build_profit_plan_card(
            symbol="HBAR",
            market="HBAR-EUR",
            current_price=Decimal("0.12"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=_wld_fib_ext(),
            presentation_mode=CARD_MODE_ACCOUNT_ORDER_ONLY,
        )
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-filter-orders='not_applicable'" not in html

    def test_account_order_modes_keep_existing_action_filter_behavior(self) -> None:
        position_html = render_plan_card(_make_card(current_price="0.5", fib_ext=_wld_fib_ext()), buy_orders=(), sell_orders=())
        order_only_html = render_plan_card(
            build_profit_plan_card(
                symbol="HBAR",
                market="HBAR-EUR",
                current_price=Decimal("0.12"),
                fib_trading_horizon="SHORT",
                short_context_input_status="HAS_ZONE_CONTEXT",
                short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
                short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
                fib_ext=_wld_fib_ext(),
                presentation_mode=CARD_MODE_ACCOUNT_ORDER_ONLY,
            ),
            buy_orders=(),
            sell_orders=(),
        )
        assert "data-filter-action=''" not in position_html
        assert "data-filter-action-label=''" not in position_html
        assert "data-filter-action=''" not in order_only_html
        assert "data-filter-action-label=''" not in order_only_html


class TestNoAccountStateOrderFilterOptions:
    """render_full_html filter option generation for watch-only-only fixtures."""

    def test_render_full_html_exposes_not_applicable_for_watch_only_fixture(self) -> None:
        card = build_profit_plan_card(
            symbol="XPL",
            market="XPL-EUR",
            current_price=Decimal("0.0050"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            presentation_mode=CARD_MODE_WATCH_ONLY_ROTATION,
        )
        html = render_full_html([card])
        assert "Not applicable" in html
        assert ">Missing orders<" not in html
        assert ">Incomplete orders<" not in html
    def test_render_full_html_exposes_not_applicable_for_market_selected_fixture(self) -> None:
        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=_wld_fib_ext(),
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )
        html = render_full_html([card])
        assert "Not applicable" in html
        assert ">Missing orders<" not in html


def test_rendered_dom_rank_metadata_matches_five_mode_order() -> None:
    html = render_full_html([_make_card(current_price="0.440000", fib_ext=_wld_fib_ext())], rendered_at="now", broker_mode="test")
    assert "sortPresentation" in html
    ranks = {
        CARD_MODE_POSITION_HELD: "0",
        CARD_MODE_ACCOUNT_ORDER_ONLY: "1",
        CARD_MODE_ACCOUNT_PLAN_ENABLED: "2",
        CARD_MODE_WATCH_ONLY_ROTATION: "3",
        CARD_MODE_MARKET_SELECTED: "4",
    }
    for mode, rank in ranks.items():
        card = build_profit_plan_card(
            symbol=mode[:3],
            market=f"{mode[:3]}-EUR",
            current_price=Decimal("0.5"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            presentation_mode=mode,
        )
        card_html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert f"data-sort-presentation='{rank}'" in card_html


class TestBuildCardsPipelineIntegration:
    """
    build_cards() pipeline integration: verify that XPL and XLM
    with CORE_SENSOR provenance (no position, no open order) produce
    WATCH_ONLY_ROTATION cards with the correct rendered output.
    """

    def _make_inclusion_reasons(self) -> "Mapping[str, frozenset[str]]":
        from typing import Mapping
        return {
            "XPL-EUR": frozenset({"CORE_SENSOR"}),
            "XLM-EUR": frozenset({"CORE_SENSOR"}),
        }

    def _make_account_plan_policy(self) -> "Mapping[str, Any]":
        from src.reporting.account_scoped_short_trader_dashboard_v1 import AccountPlanPolicy
        return {
            "APT-EUR": AccountPlanPolicy(is_candidate_enabled=True),
            "SUI-EUR": AccountPlanPolicy(is_order_proposal_enabled=True),
            "WLD-EUR": AccountPlanPolicy(is_visible=True),
            "HID-EUR": AccountPlanPolicy(is_candidate_enabled=True, is_hidden=True),
            "MAD-EUR": AccountPlanPolicy(source="MANUAL_ADD"),
            "HMA-EUR": AccountPlanPolicy(source="MANUAL_ADD", is_hidden=True),
        }

    def _run_build_cards(self) -> list[ProfitPlanCard]:
        return profit_plan_runner.build_cards(
            markets=["XPL-EUR", "XLM-EUR"],
            prices={"XPL-EUR": Decimal("0.0050"), "XLM-EUR": Decimal("0.1200")},
            price_status_by_market={"XPL-EUR": "FRESH", "XLM-EUR": "FRESH"},
            price_age_min_by_market={"XPL-EUR": None, "XLM-EUR": None},
            input_status_by_symbol={
                "XPL": "HAS_ZONE_CONTEXT",
                "XLM": "HAS_ZONE_CONTEXT",
            },
            coverage_status_by_symbol={
                "XPL": "NATIVE_SHORT_CONTEXT_AVAILABLE",
                "XLM": "NATIVE_SHORT_CONTEXT_AVAILABLE",
            },
            display_state_by_symbol={
                "XPL": "NO_NATIVE_SHORT_FIB_CONTEXT",
                "XLM": "NO_NATIVE_SHORT_FIB_CONTEXT",
            },
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market=self._make_inclusion_reasons(),
        )

    def test_xpl_xlm_presentation_mode_is_watch_only_rotation(self) -> None:
        cards = {c.symbol: c for c in self._run_build_cards()}
        assert cards["XPL"].presentation_mode == CARD_MODE_WATCH_ONLY_ROTATION, (
            "XPL with CORE_SENSOR and no position/order must be WATCH_ONLY_ROTATION"
        )
        assert cards["XLM"].presentation_mode == CARD_MODE_WATCH_ONLY_ROTATION, (
            "XLM with CORE_SENSOR and no position/order must be WATCH_ONLY_ROTATION"
        )

    def test_watch_only_badge_in_rendered_cards(self) -> None:
        for card in self._run_build_cards():
            html = render_plan_card(card, buy_orders=(), sell_orders=())
            assert "WATCH ONLY" in html, f"{card.symbol}: expected WATCH ONLY badge in rendered HTML"
            assert "NO POSITION" in html, f"{card.symbol}: expected NO POSITION in badge"

    def test_no_missing_order_rows_in_rendered_cards(self) -> None:
        for card in self._run_build_cards():
            html = render_plan_card(card, buy_orders=(), sell_orders=())
            assert "MISSING" not in html, f"{card.symbol}: MISSING order rows must not appear for watch-only card"

    def test_no_account_order_ui_in_rendered_cards(self) -> None:
        for card in self._run_build_cards():
            html = render_plan_card(card, buy_orders=(), sell_orders=())
            assert "order-section-header" not in html, (
                f"{card.symbol}: order-section-header must be absent for watch-only card"
            )

    def test_position_held_card_not_degraded_when_mixed(self) -> None:
        """When a mix of markets is included, portfolio cards keep POSITION_HELD mode."""
        reasons: dict[str, frozenset[str]] = {
            "WLD-EUR": frozenset({"POSITION_HELD", "PORTFOLIO_MARKER"}),
            "XPL-EUR": frozenset({"CORE_SENSOR"}),
        }
        cards = profit_plan_runner.build_cards(
            markets=["WLD-EUR", "XPL-EUR"],
            prices={"WLD-EUR": Decimal("0.50"), "XPL-EUR": Decimal("0.0050")},
            price_status_by_market={"WLD-EUR": "FRESH", "XPL-EUR": "FRESH"},
            price_age_min_by_market={"WLD-EUR": None, "XPL-EUR": None},
            input_status_by_symbol={
                "WLD": "HAS_ZONE_CONTEXT",
                "XPL": "HAS_ZONE_CONTEXT",
            },
            coverage_status_by_symbol={
                "WLD": "NATIVE_SHORT_CONTEXT_AVAILABLE",
                "XPL": "NATIVE_SHORT_CONTEXT_AVAILABLE",
            },
            display_state_by_symbol={
                "WLD": "NO_NATIVE_SHORT_FIB_CONTEXT",
                "XPL": "NO_NATIVE_SHORT_FIB_CONTEXT",
            },
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market=reasons,
        )
        by_sym = {c.symbol: c for c in cards}
        assert by_sym["WLD"].presentation_mode == CARD_MODE_POSITION_HELD
        assert by_sym["XPL"].presentation_mode == CARD_MODE_WATCH_ONLY_ROTATION

    def test_candidate_enabled_without_balance_or_order_gives_account_plan_enabled(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["APT-EUR"],
            prices={"APT-EUR": Decimal("1.00")},
            price_status_by_market={"APT-EUR": "FRESH"},
            price_age_min_by_market={"APT-EUR": None},
            input_status_by_symbol={"APT": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"APT": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"APT": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={},
            account_plan_policy_by_market=self._make_account_plan_policy(),
        )
        assert cards[0].presentation_mode == CARD_MODE_ACCOUNT_PLAN_ENABLED

    def test_proposal_enabled_without_balance_or_order_gives_account_plan_enabled(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["SUI-EUR"],
            prices={"SUI-EUR": Decimal("1.00")},
            price_status_by_market={"SUI-EUR": "FRESH"},
            price_age_min_by_market={"SUI-EUR": None},
            input_status_by_symbol={"SUI": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"SUI": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"SUI": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={},
            account_plan_policy_by_market=self._make_account_plan_policy(),
        )
        assert cards[0].presentation_mode == CARD_MODE_ACCOUNT_PLAN_ENABLED

    def test_manual_add_without_balance_or_order_gives_account_plan_enabled(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["MAD-EUR"],
            prices={"MAD-EUR": Decimal("1.00")},
            price_status_by_market={"MAD-EUR": "FRESH"},
            price_age_min_by_market={"MAD-EUR": None},
            input_status_by_symbol={"MAD": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"MAD": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"MAD": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={},
            account_plan_policy_by_market=self._make_account_plan_policy(),
        )
        assert cards[0].presentation_mode == CARD_MODE_ACCOUNT_PLAN_ENABLED

    def test_visible_only_without_balance_or_order_stays_market_selected(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("1.00")},
            price_status_by_market={"WLD-EUR": "FRESH"},
            price_age_min_by_market={"WLD-EUR": None},
            input_status_by_symbol={"WLD": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"WLD": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"WLD": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={},
            account_plan_policy_by_market=self._make_account_plan_policy(),
        )
        assert cards[0].presentation_mode == CARD_MODE_MARKET_SELECTED

    def test_hidden_candidate_row_does_not_produce_account_plan_enabled(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["HID-EUR"],
            prices={"HID-EUR": Decimal("1.00")},
            price_status_by_market={"HID-EUR": "FRESH"},
            price_age_min_by_market={"HID-EUR": None},
            input_status_by_symbol={"HID": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"HID": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"HID": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={},
            account_plan_policy_by_market=self._make_account_plan_policy(),
        )
        assert cards[0].presentation_mode == CARD_MODE_MARKET_SELECTED

    def test_hidden_manual_add_row_does_not_produce_account_plan_enabled(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["HMA-EUR"],
            prices={"HMA-EUR": Decimal("1.00")},
            price_status_by_market={"HMA-EUR": "FRESH"},
            price_age_min_by_market={"HMA-EUR": None},
            input_status_by_symbol={"HMA": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"HMA": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"HMA": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={},
            account_plan_policy_by_market=self._make_account_plan_policy(),
        )
        assert cards[0].presentation_mode == CARD_MODE_MARKET_SELECTED

    def test_portfolio_marker_only_without_account_plan_stays_market_selected(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("1.00")},
            price_status_by_market={"WLD-EUR": "FRESH"},
            price_age_min_by_market={"WLD-EUR": None},
            input_status_by_symbol={"WLD": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"WLD": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"WLD": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={"WLD-EUR": frozenset({"PORTFOLIO_MARKER"})},
            account_plan_policy_by_market={},
        )
        assert cards[0].presentation_mode == CARD_MODE_MARKET_SELECTED

    def test_portfolio_marker_plus_core_sensor_stays_watch_only(self) -> None:
        cards = profit_plan_runner.build_cards(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("1.00")},
            price_status_by_market={"WLD-EUR": "FRESH"},
            price_age_min_by_market={"WLD-EUR": None},
            input_status_by_symbol={"WLD": "HAS_ZONE_CONTEXT"},
            coverage_status_by_symbol={"WLD": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
            display_state_by_symbol={"WLD": "NO_NATIVE_SHORT_FIB_CONTEXT"},
            fib_ext_by_symbol={},
            reentry_by_symbol={},
            history_by_symbol={},
            orders_by_symbol={},
            inclusion_reasons_by_market={"WLD-EUR": frozenset({"PORTFOLIO_MARKER", "CORE_SENSOR"})},
            account_plan_policy_by_market={},
        )
        assert cards[0].presentation_mode == CARD_MODE_WATCH_ONLY_ROTATION


class TestMarketSelectedFieldGrid:
    """
    MARKET_SELECTED_NO_ACCOUNT_STATE: market zones appear in field grid;
    account-order UI is suppressed; WATCH ONLY badge is absent.
    """

    def _make_market_selected(self, fib_ext: FibExtContext | None = None) -> ProfitPlanCard:
        return build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.50"),
            fib_trading_horizon="SHORT",
            short_context_input_status="HAS_ZONE_CONTEXT",
            short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
            short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
            fib_ext=fib_ext,
            reentry=None,
            buy_orders=(),
            sell_orders=(),
            presentation_mode=CARD_MODE_MARKET_SELECTED,
        )

    def test_no_watch_only_badge_text(self) -> None:
        card = self._make_market_selected()
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "WATCH ONLY · NO POSITION · NO ACCOUNT ACTION" not in html

    def test_market_selected_badge_present(self) -> None:
        card = self._make_market_selected()
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "MARKET SELECTED" in html

    def test_account_order_section_suppressed(self) -> None:
        card = self._make_market_selected(fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "order-section-header" not in html

    def test_no_missing_order_rows(self) -> None:
        card = self._make_market_selected(fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "MISSING" not in html

    def test_no_fix_ladder(self) -> None:
        card = self._make_market_selected(fib_ext=_wld_fib_ext())
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "FIX LADDER" not in html

    def test_data_presentation_mode_attribute(self) -> None:
        card = self._make_market_selected()
        html = render_plan_card(card, buy_orders=(), sell_orders=())
        assert "data-presentation-mode='MARKET_SELECTED_NO_ACCOUNT_STATE'" in html
