from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from src.market_data.fib_navigation_map_v1 import (
    DIRECTION_BULLISH,
    MAP_STATE_EMERGENCY_REBUILT,
    TRIGGER_MAP_EXHAUSTED,
    FibNavCandle,
    PriorMapMeta,
    build_fib_navigation_map_from_anchor,
)
from src.reporting.manual_short_trader_profit_plan_v1 import (
    FibExtContext,
    FibNavContext,
    ProfitPlanCard,
    ReentryContext,
    TargetHistoryCandle,
    build_json_snapshot,
    build_profit_plan_card,
)
from src.reporting import run_manual_short_trader_profit_plan_v1 as profit_plan_runner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)

_SXT_LOW = Decimal("0.006571")
_SXT_HIGH = Decimal("0.010127")
_SXT_CURRENT = Decimal("0.009588")

# A fib_ext context where ALL three extension levels are below the history high
# (so _completed_map_override fires and marks all_sell_targets_completed=True).
_SXT_COMPLETED_FIB_EXT = FibExtContext(
    local_reaction_price=_SXT_HIGH,
    anchor_end_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
    ext_1_272=Decimal("0.011094"),
    ext_1_618=Decimal("0.012325"),
    ext_2_000=Decimal("0.013683"),
    breakout_gate=_SXT_HIGH,
    price_band="ABOVE_2000",
    ext_1_272_touched_and_rejected=False,
    retesting_breakout_gate=False,
)

# History high that exceeds all ext levels → triggers MAP_COMPLETED detection
_SXT_HISTORY_HIGH = Decimal("0.014000")


def _make_sxt_candles_for_pivot_detection() -> list[FibNavCandle]:
    """11 1h-equivalent candles with detectable pivot at low=0.006571, high=0.010127.

    Index 3 = pivot low (lowest in span-3 window).
    Index 7 = pivot high (highest in span-3 window).
    """
    now = _NOW
    base_ts = now - timedelta(hours=10)
    rows = [
        # pre-swing candles
        (Decimal("0.008000"), Decimal("0.007500")),   # 0
        (Decimal("0.007800"), Decimal("0.007200")),   # 1
        (Decimal("0.007500"), Decimal("0.006900")),   # 2
        (Decimal("0.007300"), Decimal("0.006571")),   # 3 ← pivot low
        (Decimal("0.008200"), Decimal("0.007100")),   # 4
        (Decimal("0.009000"), Decimal("0.008100")),   # 5
        (Decimal("0.009800"), Decimal("0.008900")),   # 6
        (Decimal("0.010127"), Decimal("0.009400")),   # 7 ← pivot high
        (Decimal("0.009900"), Decimal("0.009200")),   # 8
        (Decimal("0.009700"), Decimal("0.009100")),   # 9
        (Decimal("0.009700"), Decimal("0.009400")),   # 10 (current ~0.009588)
    ]
    return [
        FibNavCandle(
            close_ts_utc=base_ts + timedelta(hours=i),
            open_price=(h + l) / Decimal("2"),
            high_price=h,
            low_price=l,
            close_price=(h + l) / Decimal("2"),
        )
        for i, (h, l) in enumerate(rows)
    ]


def _make_sxt_history_candles() -> tuple[TargetHistoryCandle, ...]:
    """TargetHistoryCandle version of the same SXT candle set."""
    now = _NOW
    base_ts = now - timedelta(hours=10)
    rows = [
        (Decimal("0.008000"), Decimal("0.007500")),
        (Decimal("0.007800"), Decimal("0.007200")),
        (Decimal("0.007500"), Decimal("0.006900")),
        (Decimal("0.007300"), Decimal("0.006571")),   # pivot low
        (Decimal("0.008200"), Decimal("0.007100")),
        (Decimal("0.009000"), Decimal("0.008100")),
        (Decimal("0.009800"), Decimal("0.008900")),
        (Decimal("0.010127"), Decimal("0.009400")),   # pivot high
        (Decimal("0.009900"), Decimal("0.009200")),
        (Decimal("0.009700"), Decimal("0.009100")),
        (Decimal("0.009700"), Decimal("0.009400")),
    ]
    return tuple(
        TargetHistoryCandle(
            close_ts_utc=base_ts + timedelta(hours=i),
            high_price=h,
            low_price=l,
        )
        for i, (h, l) in enumerate(rows)
    )


def _make_sxt_prior_meta() -> PriorMapMeta:
    return PriorMapMeta(
        map_state="EXHAUSTED",
        anchor_low=Decimal("0.005000"),  # OLD anchor — different from candle swing
        anchor_high=Decimal("0.009000"),  # OLD anchor high
        direction=DIRECTION_BULLISH,
        top_extension_price=Decimal("0.018000"),
        candle_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _make_nav_map() -> "Any":
    return build_fib_navigation_map_from_anchor(
        anchor_low=_SXT_LOW,
        anchor_high=_SXT_HIGH,
        current_price=_SXT_CURRENT,
        computed_at_utc=_NOW,
    )


def _make_fib_nav_context(price: Decimal = _SXT_CURRENT) -> FibNavContext:
    nav = _make_nav_map()
    nav_sell = tuple(sorted(lvl.price for lvl in nav.extension_levels if lvl.price > price))
    nav_buy = tuple(sorted((lvl.price for lvl in nav.retracement_levels if lvl.price < price), reverse=True))
    r1000 = next((lvl.price for lvl in nav.retracement_levels if lvl.label == "r_1000"), None)
    return FibNavContext(
        nav_sell_levels=nav_sell,
        nav_buy_levels=nav_buy,
        nav_invalidation=r1000,
        map_state=nav.map_state,
        rebuild_trigger=nav.rebuild_trigger,
        anchor_low=nav.anchor_low,
        anchor_high=nav.anchor_high,
        direction=nav.direction,
    )


def _make_completed_card(fib_nav_context: FibNavContext | None = None) -> ProfitPlanCard:
    history = (
        TargetHistoryCandle(
            close_ts_utc=datetime(2026, 1, 5, tzinfo=UTC),
            high_price=_SXT_HISTORY_HIGH,
            low_price=Decimal("0.008000"),
        ),
    )
    return build_profit_plan_card(
        "SXT",
        "SXT-EUR",
        _SXT_CURRENT,
        fib_trading_horizon="SHORT",
        short_context_input_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        fib_ext=_SXT_COMPLETED_FIB_EXT,
        reentry=ReentryContext(
            r382_price=Decimal("0.008768"),
            r500_price=Decimal("0.008349"),
            r618_price=Decimal("0.007930"),
            r786_price=Decimal("0.007332"),
            deepest_touched_label=None,
            missed_main_rebuy_by_pct=None,
        ),
        history_high_since_activation=_SXT_HISTORY_HIGH,
        history_low_since_activation=Decimal("0.008000"),
        history_candles_since_activation=history,
        fib_nav_context=fib_nav_context,
    )


# ---------------------------------------------------------------------------
# 1. Exhausted targets + nav context → map in card payload
# ---------------------------------------------------------------------------

def test_exhausted_targets_plus_nav_context_populates_target_exit_zone() -> None:
    nav = _make_fib_nav_context()
    card = _make_completed_card(fib_nav_context=nav)

    assert card.all_sell_targets_completed is True
    assert card.fib_nav_context is not None
    assert card.fib_nav_context.map_state == MAP_STATE_EMERGENCY_REBUILT
    assert card.fib_nav_context.rebuild_trigger == TRIGGER_MAP_EXHAUSTED
    assert len(card.target_exit_zone) > 0, "target_exit_zone must not be empty with nav context"
    for lvl in card.target_exit_zone:
        assert lvl > _SXT_CURRENT, f"Nav sell level {lvl} should be above current {_SXT_CURRENT}"


def test_exhausted_targets_plus_nav_context_sets_action_label_navigation_only() -> None:
    nav = _make_fib_nav_context()
    card = _make_completed_card(fib_nav_context=nav)

    assert card.action_label == "NAVIGATION_ONLY"


def test_exhausted_targets_without_nav_context_collapses_to_no_levels() -> None:
    """Baseline: without nav context, exhausted map has empty target_exit_zone."""
    card = _make_completed_card(fib_nav_context=None)

    assert card.all_sell_targets_completed is True
    assert card.target_exit_zone == ()
    assert card.fib_nav_context is None


# ---------------------------------------------------------------------------
# 2. Card does not collapse to "No upcoming levels" when nav/fallback map exists
# ---------------------------------------------------------------------------

def test_card_has_upcoming_levels_with_nav_context() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import format_target_zone_line

    nav = _make_fib_nav_context()
    card = _make_completed_card(fib_nav_context=nav)

    formatted = format_target_zone_line(card.target_exit_zone, card.current_price)
    assert formatted != "No upcoming levels", (
        f"Expected nav levels in target zone, got: '{formatted}'"
    )
    assert formatted != ""


def test_card_collapses_to_no_upcoming_levels_without_nav_context() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import format_target_zone_line

    card = _make_completed_card(fib_nav_context=None)
    formatted = format_target_zone_line(card.target_exit_zone, card.current_price)
    assert formatted == "No upcoming levels"


# ---------------------------------------------------------------------------
# 3. JSON backward compatibility
# ---------------------------------------------------------------------------

def test_json_snapshot_includes_fib_nav_context_field() -> None:
    nav = _make_fib_nav_context()
    card = _make_completed_card(fib_nav_context=nav)
    snapshot = build_json_snapshot([card])

    symbol_data = snapshot["symbols"][0]
    assert "fib_nav_context" in symbol_data
    nav_json = symbol_data["fib_nav_context"]
    assert nav_json is not None
    assert "map_state" in nav_json
    assert "rebuild_trigger" in nav_json
    assert "nav_sell_levels" in nav_json
    assert "nav_buy_levels" in nav_json
    assert "anchor_low" in nav_json
    assert "anchor_high" in nav_json
    assert nav_json["map_state"] == MAP_STATE_EMERGENCY_REBUILT
    assert len(nav_json["nav_sell_levels"]) > 0


def test_json_snapshot_fib_nav_context_null_when_absent() -> None:
    card = _make_completed_card(fib_nav_context=None)
    snapshot = build_json_snapshot([card])

    symbol_data = snapshot["symbols"][0]
    assert "fib_nav_context" in symbol_data
    assert symbol_data["fib_nav_context"] is None


def test_json_snapshot_existing_fields_unchanged() -> None:
    """Confirm established fields are still present (backward compat)."""
    card = _make_completed_card(fib_nav_context=None)
    snapshot = build_json_snapshot([card])

    symbol_data = snapshot["symbols"][0]
    required_fields = (
        "symbol", "market", "fib_trading_horizon",
        "short_context_input_status", "short_context_coverage_status",
        "primary_state", "scenario_type", "action_label",
        "buy_zone", "sell_zone", "target_exit_zone",
        "active_target", "target_level_statuses",
        "broker_writes", "order_submission",
    )
    for field in required_fields:
        if field in ("broker_writes", "order_submission"):
            assert field in snapshot, f"Top-level field missing: {field}"
        else:
            assert field in symbol_data, f"Symbol field missing: {field}"


# ---------------------------------------------------------------------------
# 4. Reporting layer does not build fibs (architecture guard)
# ---------------------------------------------------------------------------

def test_profit_plan_card_module_has_no_fib_builder_imports() -> None:
    source = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_modules = (
        "src.market_data.fib_navigation_map_v1",
        "src.research.htf_fib_extension_confluence_v1",
        "src.research.htf_fib_reentry_ladder_v1",
        "src.market_data.native_short_fib_context_v1",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)

    for mod in forbidden_modules:
        assert mod not in imported, (
            f"Reporting card module must not import fib builder: {mod}"
        )


def test_runner_imports_fib_builder_not_card_module_imports_it() -> None:
    """Fib building belongs in the runner, not in the card module."""
    card_source = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    runner_source = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")

    assert "fib_navigation_map_v1" not in card_source, (
        "Card module must not import fib_navigation_map_v1 directly"
    )
    assert "fib_navigation_map_v1" in runner_source, (
        "Runner must import fib_navigation_map_v1 to build nav maps"
    )


def test_no_forbidden_imports_in_fib_navigation_map() -> None:
    source = Path("src/market_data/fib_navigation_map_v1.py").read_text(encoding="utf-8")
    forbidden = (
        "src.reporting",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "dashboard",
        "order_submission",
        "broker_write",
        "live_order",
    )
    for term in forbidden:
        assert term not in source, f"Market-only module contains forbidden reference: {term}"


# ---------------------------------------------------------------------------
# 5. build_fib_navigation_map_from_anchor: correct levels and state
# ---------------------------------------------------------------------------

def test_from_anchor_returns_emergency_rebuilt() -> None:
    nav = build_fib_navigation_map_from_anchor(
        anchor_low=_SXT_LOW,
        anchor_high=_SXT_HIGH,
        current_price=_SXT_CURRENT,
        computed_at_utc=_NOW,
    )
    assert nav.map_state == MAP_STATE_EMERGENCY_REBUILT
    assert nav.rebuild_trigger == TRIGGER_MAP_EXHAUSTED


def test_from_anchor_sxt_extension_levels() -> None:
    nav = build_fib_navigation_map_from_anchor(
        anchor_low=_SXT_LOW,
        anchor_high=_SXT_HIGH,
        current_price=_SXT_CURRENT,
        computed_at_utc=_NOW,
    )
    by_label = {lvl.label: lvl.price for lvl in nav.extension_levels}
    tol = Decimal("0.000010")

    assert abs(by_label["ext_1272"] - Decimal("0.011094")) <= tol
    assert abs(by_label["ext_2000"] - Decimal("0.013683")) <= tol
    assert abs(by_label["ext_4236"] - Decimal("0.021635")) <= tol


def test_from_anchor_full_level_set_present() -> None:
    """Anchor-based map must carry all 6 retrace + 9 extension levels."""
    nav = build_fib_navigation_map_from_anchor(
        anchor_low=_SXT_LOW,
        anchor_high=_SXT_HIGH,
        current_price=_SXT_CURRENT,
        computed_at_utc=_NOW,
    )
    assert len(nav.retracement_levels) == 6
    assert len(nav.extension_levels) == 9


def test_from_anchor_rejects_invalid_anchor() -> None:
    try:
        build_fib_navigation_map_from_anchor(
            anchor_low=Decimal("0.010000"),
            anchor_high=Decimal("0.005000"),
            current_price=Decimal("0.008000"),
            computed_at_utc=_NOW,
        )
    except ValueError:
        return
    raise AssertionError("Expected ValueError for inverted anchor")


# ---------------------------------------------------------------------------
# 6. Candle-driven rebuild path (primary)
# ---------------------------------------------------------------------------

def test_candle_driven_rebuild_detects_sxt_swing_not_old_anchor() -> None:
    """Primary path: candle swing detection finds new pivot, not the stale old anchor."""
    fib_candles = _make_sxt_candles_for_pivot_detection()
    old_anchor_meta = _make_sxt_prior_meta()  # old anchor: low=0.005, high=0.009

    ctx = profit_plan_runner._build_nav_context_from_candle_set(
        fib_nav_candles=fib_candles,
        current_price=_SXT_CURRENT,
        prior=old_anchor_meta,
        now_utc=_NOW,
    )

    assert ctx is not None
    assert ctx.map_state == MAP_STATE_EMERGENCY_REBUILT
    assert ctx.rebuild_trigger == TRIGGER_MAP_EXHAUSTED
    # Candle-detected swing: low=0.006571, high=0.010127 (not old anchor 0.005/0.009)
    tol = Decimal("0.000020")
    assert abs(ctx.anchor_low - _SXT_LOW) <= tol, (
        f"Expected candle-detected low={_SXT_LOW}, got {ctx.anchor_low}"
    )
    assert abs(ctx.anchor_high - _SXT_HIGH) <= tol, (
        f"Expected candle-detected high={_SXT_HIGH}, got {ctx.anchor_high}"
    )


def test_candle_driven_rebuild_sxt_extension_levels() -> None:
    """Candle-driven path produces SXT expected extension targets."""
    fib_candles = _make_sxt_candles_for_pivot_detection()
    prior = _make_sxt_prior_meta()

    ctx = profit_plan_runner._build_nav_context_from_candle_set(
        fib_nav_candles=fib_candles,
        current_price=_SXT_CURRENT,
        prior=prior,
        now_utc=_NOW,
    )
    assert ctx is not None

    # nav_sell_levels are extension levels above current price (ascending)
    sell_set = set(str(p)[:7] for p in ctx.nav_sell_levels)
    tol = Decimal("0.00002")

    # Validate at least the first three sell levels
    all_ext = sorted(ctx.nav_sell_levels)
    expected_first = Decimal("0.011094")
    assert abs(all_ext[0] - expected_first) <= tol, (
        f"First sell level expected ~{expected_first}, got {all_ext[0]}"
    )


def test_anchor_fallback_used_when_candles_insufficient() -> None:
    """With empty candles, anchor fallback produces levels from old anchor."""
    old_anchor_meta = PriorMapMeta(
        map_state="EXHAUSTED",
        anchor_low=_SXT_LOW,
        anchor_high=_SXT_HIGH,
        direction=DIRECTION_BULLISH,
        top_extension_price=Decimal("0.021635"),
        candle_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )

    ctx = profit_plan_runner._build_nav_context_from_candle_set(
        fib_nav_candles=[],  # empty candles → NO_DATA → fall back to anchor
        current_price=_SXT_CURRENT,
        prior=old_anchor_meta,
        now_utc=_NOW,
    )

    assert ctx is not None, "Anchor fallback must produce nav context when candles absent"
    assert ctx.map_state == MAP_STATE_EMERGENCY_REBUILT
    tol = Decimal("0.000020")
    assert abs(ctx.anchor_low - _SXT_LOW) <= tol
    assert abs(ctx.anchor_high - _SXT_HIGH) <= tol


def test_anchor_fallback_is_secondary_candle_path_wins_when_fresh() -> None:
    """Candle path overrides old anchor: detected swing differs from old anchor."""
    fib_candles = _make_sxt_candles_for_pivot_detection()
    old_anchor_meta = _make_sxt_prior_meta()  # old anchor differs from candle swing

    ctx = profit_plan_runner._build_nav_context_from_candle_set(
        fib_nav_candles=fib_candles,
        current_price=_SXT_CURRENT,
        prior=old_anchor_meta,
        now_utc=_NOW,
    )
    assert ctx is not None
    # Candle path found new swing (0.006571 / 0.010127), not old anchor (0.005 / 0.009)
    assert ctx.anchor_low != old_anchor_meta.anchor_low, (
        "Candle-detected swing should differ from old anchor"
    )


def test_no_valid_anchor_and_no_candles_returns_none() -> None:
    """No candles AND invalid anchor (low >= high) → None."""
    bad_meta = PriorMapMeta(
        map_state="EXHAUSTED",
        anchor_low=Decimal("0.010000"),
        anchor_high=Decimal("0.005000"),  # inverted → anchor builder raises
        direction=DIRECTION_BULLISH,
        top_extension_price=Decimal("0.020000"),
        candle_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )
    ctx = profit_plan_runner._build_nav_context_from_candle_set(
        fib_nav_candles=[],
        current_price=_SXT_CURRENT,
        prior=bad_meta,
        now_utc=_NOW,
    )
    assert ctx is None


def test_candles_to_fib_nav_converts_correctly() -> None:
    """_candles_to_fib_nav synthesizes midpoint open/close, zero volume."""
    raw = _make_sxt_history_candles()
    converted = profit_plan_runner._candles_to_fib_nav(raw)

    assert len(converted) == len(raw)
    for orig, conv in zip(raw, converted):
        assert conv.high_price == orig.high_price
        assert conv.low_price == orig.low_price
        assert conv.close_ts_utc == orig.close_ts_utc
        expected_mid = (orig.high_price + orig.low_price) / Decimal("2")
        assert conv.open_price == expected_mid
        assert conv.close_price == expected_mid
        assert conv.volume == Decimal("0")


def test_build_cards_uses_candle_driven_path() -> None:
    """build_cards() produces nav context from candles when prior_map_meta present."""
    from src.reporting.run_manual_short_trader_profit_plan_v1 import (
        MarketTargetHistory,
        build_cards,
    )

    history_candles = _make_sxt_history_candles()
    prior_meta = _make_sxt_prior_meta()

    cards = build_cards(
        markets=["SXT-EUR"],
        prices={"SXT-EUR": _SXT_CURRENT},
        price_status_by_market={"SXT-EUR": "FRESH"},
        price_age_min_by_market={"SXT-EUR": Decimal("1")},
        input_status_by_symbol={"SXT": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
        coverage_status_by_symbol={"SXT": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
        display_state_by_symbol={"SXT": "HAS_NATIVE_SHORT_FIB_CONTEXT"},
        fib_ext_by_symbol={"SXT": _SXT_COMPLETED_FIB_EXT},
        reentry_by_symbol={},
        history_by_symbol={
            "SXT": MarketTargetHistory(
                high_since_activation=_SXT_HISTORY_HIGH,
                low_since_activation=Decimal("0.006571"),
                candles_since_activation=history_candles,
            )
        },
        orders_by_symbol={},
        prior_map_meta_by_symbol={"SXT": prior_meta},
        now_utc=_NOW,
    )

    assert len(cards) == 1
    card = cards[0]
    assert card.fib_nav_context is not None, "build_cards must produce nav context when prior_map_meta is set"
    assert card.fib_nav_context.map_state == MAP_STATE_EMERGENCY_REBUILT
    # Candle-detected swing used (not old anchor)
    tol = Decimal("0.000020")
    assert abs(card.fib_nav_context.anchor_low - _SXT_LOW) <= tol


def test_build_cards_no_nav_context_without_prior_meta() -> None:
    """build_cards() produces no nav context when prior_map_meta absent."""
    from src.reporting.run_manual_short_trader_profit_plan_v1 import (
        MarketTargetHistory,
        build_cards,
    )

    history_candles = _make_sxt_history_candles()

    cards = build_cards(
        markets=["SXT-EUR"],
        prices={"SXT-EUR": _SXT_CURRENT},
        price_status_by_market={"SXT-EUR": "FRESH"},
        price_age_min_by_market={"SXT-EUR": Decimal("1")},
        input_status_by_symbol={"SXT": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
        coverage_status_by_symbol={"SXT": "NATIVE_SHORT_CONTEXT_AVAILABLE"},
        display_state_by_symbol={"SXT": "HAS_NATIVE_SHORT_FIB_CONTEXT"},
        fib_ext_by_symbol={"SXT": _SXT_COMPLETED_FIB_EXT},
        reentry_by_symbol={},
        history_by_symbol={
            "SXT": MarketTargetHistory(
                high_since_activation=_SXT_HISTORY_HIGH,
                low_since_activation=Decimal("0.006571"),
                candles_since_activation=history_candles,
            )
        },
        orders_by_symbol={},
        prior_map_meta_by_symbol={},  # no prior meta → no nav context
        now_utc=_NOW,
    )

    assert len(cards) == 1
    assert cards[0].fib_nav_context is None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    tests = [
        test_exhausted_targets_plus_nav_context_populates_target_exit_zone,
        test_exhausted_targets_plus_nav_context_sets_action_label_navigation_only,
        test_exhausted_targets_without_nav_context_collapses_to_no_levels,
        test_card_has_upcoming_levels_with_nav_context,
        test_card_collapses_to_no_upcoming_levels_without_nav_context,
        test_json_snapshot_includes_fib_nav_context_field,
        test_json_snapshot_fib_nav_context_null_when_absent,
        test_json_snapshot_existing_fields_unchanged,
        test_profit_plan_card_module_has_no_fib_builder_imports,
        test_runner_imports_fib_builder_not_card_module_imports_it,
        test_no_forbidden_imports_in_fib_navigation_map,
        test_from_anchor_returns_emergency_rebuilt,
        test_from_anchor_sxt_extension_levels,
        test_from_anchor_full_level_set_present,
        test_from_anchor_rejects_invalid_anchor,
        test_candle_driven_rebuild_detects_sxt_swing_not_old_anchor,
        test_candle_driven_rebuild_sxt_extension_levels,
        test_anchor_fallback_used_when_candles_insufficient,
        test_anchor_fallback_is_secondary_candle_path_wins_when_fresh,
        test_no_valid_anchor_and_no_candles_returns_none,
        test_candles_to_fib_nav_converts_correctly,
        test_build_cards_uses_candle_driven_path,
        test_build_cards_no_nav_context_without_prior_meta,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
