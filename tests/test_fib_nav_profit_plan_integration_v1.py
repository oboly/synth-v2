from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from src.market_data.fib_navigation_map_v1 import (
    MAP_STATE_EMERGENCY_REBUILT,
    TRIGGER_MAP_EXHAUSTED,
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
    # target_exit_zone must be non-empty — nav levels populated it
    assert len(card.target_exit_zone) > 0, "target_exit_zone must not be empty with nav context"
    # All levels should be above current price
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
        # broker_writes etc. are top-level
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
