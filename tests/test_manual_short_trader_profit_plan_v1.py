from __future__ import annotations

import ast
import json
import tempfile
from decimal import Decimal
from pathlib import Path

import src.reporting.run_manual_short_trader_profit_plan_v1 as profit_plan_runner
from src.reporting.manual_short_trader_profit_plan_v1 import (
    RELEVANT_STATES,
    ActiveOrderSummary,
    FibExtContext,
    ProfitPlanCard,
    ReentryContext,
    build_json_snapshot,
    build_order_summary,
    build_profit_plan_card,
    render_full_html,
)
from src.reporting.run_manual_short_trader_profit_plan_v1 import OpenOrderInputLoadResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _wld_fib_ext(price_band: str = "BETWEEN_1272_1618") -> FibExtContext:
    return FibExtContext(
        ext_1_272=Decimal("0.4900"),
        ext_1_618=Decimal("0.6500"),
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


def _ondo_reentry() -> ReentryContext:
    return ReentryContext(
        r382_price=Decimal("0.900"),
        r500_price=Decimal("0.850"),
        r618_price=Decimal("0.800"),
        r786_price=Decimal("0.730"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )


class _FakeOrder:
    def __init__(self, price: str, side: str = "buy") -> None:
        self.limit_price = Decimal(price)
        self.side = side


def _make_card_with_manual_states(
    *,
    current_price: str | None,
    fib_ext: FibExtContext | None = None,
    reentry: ReentryContext | None = None,
    buy_orders: tuple[_FakeOrder, ...] = (),
    sell_orders: tuple[_FakeOrder, ...] = (),
) -> ProfitPlanCard:
    return build_profit_plan_card(
        "WLD",
        "WLD-EUR",
        Decimal(current_price) if current_price is not None else None,
        fib_ext=fib_ext,
        reentry=reentry,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
    )


# ---------------------------------------------------------------------------
# AST / safety
# ---------------------------------------------------------------------------

def test_pure_module_has_no_forbidden_imports() -> None:
    src = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"bitvavo_client", "decision_gate", "execution_planner", "executor", "pymysql", "db"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for f in forbidden:
                assert f not in module, f"forbidden '{f}' in pure module"


def test_runner_has_no_broker_write_calls() -> None:
    src = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    for forbidden in ("place_order", "cancel_order", "BROKER_WRITE_PERMISSION"):
        assert forbidden not in src, f"runner must not reference '{forbidden}'"


def test_json_snapshot_safety_markers() -> None:
    snap = build_json_snapshot([])
    assert snap["broker_writes"] == 0
    assert snap["order_submission"] == 0
    assert snap["executor"] == "none"


def test_load_open_order_inputs_prefers_snapshot_source() -> None:
    original_snapshot = profit_plan_runner.fetch_open_orders_from_snapshot
    original_broker = profit_plan_runner.fetch_broker_snapshot
    try:
        profit_plan_runner.fetch_open_orders_from_snapshot = lambda **_: OpenOrderInputLoadResult(
            orders=[],
            balances=[],
            source_name="account_open_order_snapshot",
            source_missing=False,
        )
        profit_plan_runner.fetch_broker_snapshot = lambda client: (_ for _ in ()).throw(
            AssertionError("broker fallback should not be used when snapshot exists")
        )
        result = profit_plan_runner.load_open_order_inputs(
            client=object(),
            account_code="bitvavo_synth_read",
            venue="bitvavo",
            allow_live_broker=True,
        )
        assert result.source_name == "account_open_order_snapshot"
    finally:
        profit_plan_runner.fetch_open_orders_from_snapshot = original_snapshot
        profit_plan_runner.fetch_broker_snapshot = original_broker


def test_load_open_order_inputs_uses_live_broker_only_when_snapshot_missing_and_allowed() -> None:
    original_snapshot = profit_plan_runner.fetch_open_orders_from_snapshot
    original_broker = profit_plan_runner.fetch_broker_snapshot
    try:
        expected_order = profit_plan_runner.BrokerOrderRow(
            order_id="o-1",
            market="WLD-EUR",
            side="sell",
            order_type="limit",
            limit_price=Decimal("0.6500"),
            amount=Decimal("10"),
            filled_amount=Decimal("0"),
            remaining_amount=Decimal("10"),
            status="new",
            created_at_ms=123,
        )
        profit_plan_runner.fetch_open_orders_from_snapshot = lambda **_: OpenOrderInputLoadResult(
            orders=[],
            balances=[],
            source_name="account_open_order_snapshot",
            source_missing=True,
        )
        profit_plan_runner.fetch_broker_snapshot = lambda client: ([expected_order], [])
        result = profit_plan_runner.load_open_order_inputs(
            client=object(),
            account_code="bitvavo_synth_read",
            venue="bitvavo",
            allow_live_broker=True,
        )
        assert result.source_name == "live_broker_private_read"
        assert len(result.orders) == 1
    finally:
        profit_plan_runner.fetch_open_orders_from_snapshot = original_snapshot
        profit_plan_runner.fetch_broker_snapshot = original_broker


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
        assert "WLD" in result.fib_ext_by_symbol
        assert "WLD" in result.reentry_by_symbol


def test_load_zone_contexts_manual_cli_overrides_missing_source() -> None:
    result = profit_plan_runner.load_zone_contexts(
        markets=["WLD-EUR"],
        prices={"WLD-EUR": Decimal("0.48")},
        swing_anchors={"WLD": ["0.30", "0.38"]},
        recent_lows={"WLD": ["0.33"]},
        fib_map_rows_path=Path("/tmp/does-not-exist-profit-plan-zones.csv"),
    )
    assert result.input_status_by_symbol["WLD"] == "MANUAL_ZONE_CONTEXT_USED"
    assert "WLD" in result.fib_ext_by_symbol
    assert "WLD" in result.reentry_by_symbol


def test_load_zone_contexts_missing_source_fails_closed() -> None:
    result = profit_plan_runner.load_zone_contexts(
        markets=["WLD-EUR"],
        prices={"WLD-EUR": Decimal("0.48")},
        swing_anchors={},
        recent_lows={},
        fib_map_rows_path=Path("/tmp/does-not-exist-profit-plan-zones.csv"),
    )
    assert result.input_status_by_symbol["WLD"] == "ZONE_SOURCE_MISSING"


def test_load_zone_contexts_symbol_missing_in_source_fails_closed() -> None:
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


# ---------------------------------------------------------------------------
# WLD-like: EXTENSION_RUNNER / TAKE_PROFIT_NEAR
# ---------------------------------------------------------------------------

def test_wld_scenario_extension_runner() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    assert card.scenario_type == "EXTENSION_RUNNER"


def test_wld_action_take_profit_near_between_1272_1618() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    assert card.action_label == "TAKE_PROFIT_NEAR"


def test_wld_sell_zone_includes_1618_ext() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    assert Decimal("0.6500") in card.sell_zone


def test_wld_reasons_mention_1618() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    combined = " ".join(card.reasons)
    assert "1.618" in combined


def test_wld_reasons_mention_round_number_or_momentum() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    combined = " ".join(card.reasons)
    assert any(word in combined for word in ("round", "Round", "momentum", "Momentum", "take-profit", "take profit"))


def test_wld_is_relevant() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    assert card.is_relevant is True


def test_between_1618_2000_action_take_profit() -> None:
    fib = _wld_fib_ext("BETWEEN_1618_2000")
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.70"), fib_ext=fib)
    assert card.action_label == "TAKE_PROFIT_NEAR"
    assert card.scenario_type == "EXTENSION_RUNNER"


def test_above_2000_action_far_moonbag() -> None:
    fib = _wld_fib_ext("ABOVE_2000")
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.90"), fib_ext=fib)
    assert card.action_label == "FAR_MOONBAG_ONLY"


def test_above_gate_approaching_1272_action_breakout_watch() -> None:
    fib = _wld_fib_ext("ABOVE_GATE_APPROACHING_1272")
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.41"), fib_ext=fib)
    assert card.action_label == "BREAKOUT_WATCH"
    assert card.scenario_type == "EXTENSION_RUNNER"


# ---------------------------------------------------------------------------
# FET-like: REENTRY_WAIT with missed_main_rebuy
# ---------------------------------------------------------------------------

def test_fet_scenario_reentry_wait() -> None:
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.230"), reentry=_fet_reentry())
    assert card.scenario_type == "REENTRY_WAIT"


def test_fet_action_rebuy_zone_near() -> None:
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.230"), reentry=_fet_reentry())
    assert card.action_label == "REBUY_ZONE_NEAR"


def test_fet_buy_zone_includes_r382_and_r500() -> None:
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.230"), reentry=_fet_reentry())
    assert Decimal("0.2142") in card.buy_zone
    assert Decimal("0.2050") in card.buy_zone


def test_fet_reasons_mention_missed_main_rebuy() -> None:
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.230"), reentry=_fet_reentry())
    combined = " ".join(card.reasons)
    assert "missed" in combined.lower() or "main" in combined.lower()


def test_fet_reasons_mention_first_touch_level() -> None:
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.230"), reentry=_fet_reentry())
    combined = " ".join(card.reasons)
    assert "0.2142" in combined or "first" in combined.lower() or "First" in combined


def test_fet_reasons_mention_main_rebuy_price() -> None:
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.230"), reentry=_fet_reentry())
    combined = " ".join(card.reasons)
    assert "0.2050" in combined or "main" in combined.lower()


def test_fet_is_relevant() -> None:
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.230"), reentry=_fet_reentry())
    assert card.is_relevant is True


# ---------------------------------------------------------------------------
# REENTRY_WAIT with r500 touched
# ---------------------------------------------------------------------------

def test_r500_touched_action_buy_dip() -> None:
    reentry = ReentryContext(
        r382_price=Decimal("0.2142"),
        r500_price=Decimal("0.2050"),
        r618_price=Decimal("0.1958"),
        r786_price=Decimal("0.1827"),
        deepest_touched_label="retrace_0_500",
        missed_main_rebuy_by_pct=None,
    )
    card = build_profit_plan_card("FET", "FET-EUR", Decimal("0.215"), reentry=reentry)
    assert card.action_label == "BUY_DIP"


# ---------------------------------------------------------------------------
# ONDO-like: RANGE_BOUNCE
# ---------------------------------------------------------------------------

def test_ondo_without_fib_ext_wait() -> None:
    card = build_profit_plan_card("ONDO", "ONDO-EUR", Decimal("0.95"), reentry=_ondo_reentry())
    assert card.scenario_type == "REENTRY_WAIT"


def test_deep_retrace_profile_range_bounce() -> None:
    card = build_profit_plan_card(
        "ONDO", "ONDO-EUR", Decimal("0.95"),
        reentry=_ondo_reentry(),
        profile_classification="DEEP_RETRACE",
    )
    assert card.scenario_type == "RANGE_BOUNCE"
    assert card.action_label == "BUY_DIP"


def test_deep_retrace_buy_zone_at_deeper_levels() -> None:
    card = build_profit_plan_card(
        "ONDO", "ONDO-EUR", Decimal("0.95"),
        reentry=_ondo_reentry(),
        profile_classification="DEEP_RETRACE",
    )
    assert Decimal("0.800") in card.buy_zone or Decimal("0.730") in card.buy_zone


# ---------------------------------------------------------------------------
# Breakout retest
# ---------------------------------------------------------------------------

def test_retesting_breakout_gate_scenario() -> None:
    fib = FibExtContext(
        ext_1_272=Decimal("0.49"),
        ext_1_618=Decimal("0.65"),
        ext_2_000=Decimal("0.80"),
        breakout_gate=Decimal("0.38"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=True,
        retesting_breakout_gate=True,
    )
    card = build_profit_plan_card("X", "X-EUR", Decimal("0.385"), fib_ext=fib)
    assert card.scenario_type == "BREAKOUT_RETEST"
    assert card.action_label == "BUY_DIP"


def test_ext_1272_touched_rejected_scenario_reentry_wait() -> None:
    # ext_1_272_touched_and_rejected=True implies current < 1.272, so band is ABOVE_GATE_*
    fib = FibExtContext(
        ext_1_272=Decimal("0.49"),
        ext_1_618=Decimal("0.65"),
        ext_2_000=Decimal("0.80"),
        breakout_gate=Decimal("0.38"),
        price_band="ABOVE_GATE_APPROACHING_1272",
        ext_1_272_touched_and_rejected=True,
        retesting_breakout_gate=False,
    )
    card = build_profit_plan_card("X", "X-EUR", Decimal("0.42"), fib_ext=fib, reentry=_fet_reentry())
    assert card.scenario_type == "REENTRY_WAIT"


# ---------------------------------------------------------------------------
# No context → NO_CLEAR_PLAN
# ---------------------------------------------------------------------------

def test_no_context_scenario_no_clear_plan() -> None:
    card = build_profit_plan_card("ZZZ", "ZZZ-EUR", Decimal("1.00"))
    assert card.scenario_type == "NO_CLEAR_PLAN"
    assert card.action_label == "WAIT"
    assert card.is_relevant is False


# ---------------------------------------------------------------------------
# is_relevant logic
# ---------------------------------------------------------------------------

def test_far_moonbag_not_relevant() -> None:
    fib = _wld_fib_ext("ABOVE_2000")
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.90"), fib_ext=fib)
    assert card.is_relevant is False


def test_do_not_touch_not_relevant() -> None:
    card = build_profit_plan_card("ZZZ", "ZZZ-EUR", Decimal("1.00"))
    assert card.is_relevant is False


def test_relevant_states_constant_has_expected_entries() -> None:
    assert "TAKE_PROFIT_NEAR" in RELEVANT_STATES
    assert "BUY_DIP" in RELEVANT_STATES
    assert "REBUY_ZONE_NEAR" in RELEVANT_STATES
    assert "BREAKOUT_WATCH" in RELEVANT_STATES
    assert "REENTRY_WAIT" in RELEVANT_STATES
    assert "RANGE_BOUNCE" in RELEVANT_STATES
    assert "BREAKOUT_RETEST" in RELEVANT_STATES


# ---------------------------------------------------------------------------
# Order summary
# ---------------------------------------------------------------------------

def test_order_summary_matching_buy_near_zone() -> None:
    buy_orders = (_FakeOrder("0.2050"),)
    sell_orders = ()
    summary = build_order_summary(
        Decimal("0.230"),
        (Decimal("0.2050"),),
        (),
        buy_orders,
        sell_orders,
    )
    assert summary.matching_buys == 1
    assert summary.open_buy_orders == 1
    assert "1 buy open" in summary.existing_open_orders_summary


def test_order_summary_no_match_when_far() -> None:
    buy_orders = (_FakeOrder("0.100"),)
    summary = build_order_summary(
        Decimal("0.230"),
        (Decimal("0.2050"),),
        (),
        buy_orders,
        (),
    )
    assert summary.matching_buys == 0


def test_order_summary_missing_suggested() -> None:
    summary = build_order_summary(
        Decimal("0.230"),
        (Decimal("0.2050"),),
        (Decimal("0.6500"),),
        (),
        (),
    )
    missing = list(summary.missing_suggested)
    assert any("0.2050" in m for m in missing)
    assert any("0.6500" in m for m in missing)


# ---------------------------------------------------------------------------
# Manual planning display states
# ---------------------------------------------------------------------------

def test_take_profit_waiting_when_target_is_near_and_sell_order_exists() -> None:
    card = _make_card_with_manual_states(
        current_price="0.6400",
        fib_ext=_wld_fib_ext(),
        sell_orders=(_FakeOrder("0.6500", side="sell"),),
    )
    assert card.primary_state == "TAKE_PROFIT_WAITING"
    assert card.suggested_manual_attention_label == "Take profit already waiting"


def test_reload_zone_approaching_when_price_is_near_reload_zone() -> None:
    card = _make_card_with_manual_states(
        current_price="0.2100",
        reentry=_fet_reentry(),
    )
    assert card.primary_state == "RELOAD_ZONE_APPROACHING"
    assert card.suggested_manual_attention_label == "Reload zone approaching"


def test_price_ran_away_when_price_is_far_above_target_assumptions() -> None:
    card = _make_card_with_manual_states(
        current_price="0.7600",
        fib_ext=_wld_fib_ext(),
    )
    assert card.primary_state == "PRICE_RAN_AWAY"
    assert card.suggested_manual_attention_label == "Price ran away"


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
    card = _make_card_with_manual_states(
        current_price="0.3600",
        fib_ext=fib,
    )
    assert card.primary_state == "INVALIDATION_NEAR"
    assert card.suggested_manual_attention_label == "Invalidation / risk zone near"


def test_order_too_far_or_stale_when_open_orders_are_far_from_current_price() -> None:
    card = _make_card_with_manual_states(
        current_price="0.3000",
        reentry=_fet_reentry(),
        buy_orders=(_FakeOrder("0.1000"),),
    )
    assert card.primary_state == "ORDER_TOO_FAR_OR_STALE"
    assert card.suggested_manual_attention_label == "Order too far or stale"


def test_do_nothing_for_neutral_valid_state() -> None:
    card = _make_card_with_manual_states(
        current_price="0.2500",
        reentry=_fet_reentry(),
    )
    assert card.primary_state == "DO_NOTHING"
    assert card.suggested_manual_attention_label == "Do nothing"


def test_insufficient_data_when_zones_are_missing() -> None:
    card = _make_card_with_manual_states(
        current_price=None,
        fib_ext=None,
        reentry=None,
    )
    assert card.primary_state == "INSUFFICIENT_DATA"
    assert card.suggested_manual_attention_label == "Insufficient data"


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def test_render_full_html_contains_toggle_buttons() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    html = render_full_html([card])
    assert "btn-relevant" in html
    assert "btn-all" in html
    assert "Relevant candidates" in html
    assert "All candidates" in html


def test_render_full_html_uses_profit_plan_title() -> None:
    html = render_full_html([])
    assert "Profit Plan" in html
    assert "Short Trader Profit Plan" not in html


def test_render_full_html_includes_manual_state_labels_and_fields() -> None:
    card = _make_card_with_manual_states(
        current_price="0.6400",
        fib_ext=_wld_fib_ext(),
        sell_orders=(_FakeOrder("0.6500", side="sell"),),
    )
    html = render_full_html([card], monitor_link="/tmp/manual_short_trader_dashboard_v1.html")
    assert "Take profit already waiting" in html
    assert "Existing open orders" in html
    assert "Distance to target" in html


def test_profit_plan_uses_public_monitor_href_not_filesystem_path() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    html = render_full_html([card], monitor_link="/synth/open-orders-monitor.html")
    assert 'href="/synth/open-orders-monitor.html"' in html or "href='/synth/open-orders-monitor.html'" in html
    assert "/var/www/html/synth/open-orders-monitor.html" not in html


def test_render_full_html_data_relevant_attribute() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    html = render_full_html([card])
    assert "data-relevant=\"true\"" in html or "data-relevant='true'" in html


def test_render_full_html_not_relevant_card_present() -> None:
    card = build_profit_plan_card("ZZZ", "ZZZ-EUR", Decimal("1.00"))
    html = render_full_html([card])
    assert "data-relevant=\"false\"" in html or "data-relevant='false'" in html


def test_render_full_html_safety_marker() -> None:
    html = render_full_html([])
    assert "broker_writes=0" in html
    assert "order_submission=0" in html


def test_render_full_html_javascript_setview() -> None:
    html = render_full_html([])
    assert "setView" in html
    assert "localStorage" in html


def test_render_full_html_no_raw_order_dump() -> None:
    # profit-plan page must NOT reference raw order ID columns
    html = render_full_html([])
    assert "Order ID" not in html
    assert "amountRemaining" not in html


def test_profit_plan_links_to_open_orders_monitor() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    html = render_full_html([card], monitor_link="/tmp/manual_short_trader_dashboard_v1.html")
    assert "Open Orders Monitor" in html


def test_resolve_monitor_link_prefers_public_href() -> None:
    assert profit_plan_runner.resolve_monitor_link(
        monitor_html="/var/www/html/synth/open-orders-monitor.html",
        monitor_href="/synth/open-orders-monitor.html",
    ) == "/synth/open-orders-monitor.html"


def test_profit_plan_sources_do_not_introduce_order_mutation_strings() -> None:
    for path in (
        "src/reporting/manual_short_trader_profit_plan_v1.py",
        "src/reporting/run_manual_short_trader_profit_plan_v1.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "placeOrder" not in source
        assert "cancelOrder" not in source
        assert "create order" not in source.lower()


# ---------------------------------------------------------------------------
# JSON snapshot
# ---------------------------------------------------------------------------

def test_json_snapshot_structure() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    snap = build_json_snapshot([card])
    assert len(snap["symbols"]) == 1
    sym = snap["symbols"][0]
    assert sym["symbol"] == "WLD"
    assert sym["scenario_type"] == "EXTENSION_RUNNER"
    assert "primary_state" in sym
    assert "suggested_manual_attention_label" in sym
    assert "broker_writes" in snap
    assert snap["broker_writes"] == 0


def test_json_snapshot_is_valid_json() -> None:
    card = build_profit_plan_card("WLD", "WLD-EUR", Decimal("0.48"), fib_ext=_wld_fib_ext())
    raw = json.dumps(build_json_snapshot([card]))
    parsed = json.loads(raw)
    assert parsed["symbols"][0]["action_label"] == "TAKE_PROFIT_NEAR"


def main() -> None:
    test_pure_module_has_no_forbidden_imports()
    test_runner_has_no_broker_write_calls()
    test_json_snapshot_safety_markers()
    test_load_open_order_inputs_prefers_snapshot_source()
    test_load_open_order_inputs_uses_live_broker_only_when_snapshot_missing_and_allowed()
    test_load_zone_contexts_uses_source_rows_without_manual_cli()
    test_load_zone_contexts_manual_cli_overrides_missing_source()
    test_load_zone_contexts_missing_source_fails_closed()
    test_load_zone_contexts_symbol_missing_in_source_fails_closed()
    test_wld_scenario_extension_runner()
    test_wld_action_take_profit_near_between_1272_1618()
    test_wld_sell_zone_includes_1618_ext()
    test_wld_reasons_mention_1618()
    test_wld_reasons_mention_round_number_or_momentum()
    test_wld_is_relevant()
    test_between_1618_2000_action_take_profit()
    test_above_2000_action_far_moonbag()
    test_above_gate_approaching_1272_action_breakout_watch()
    test_fet_scenario_reentry_wait()
    test_fet_action_rebuy_zone_near()
    test_fet_buy_zone_includes_r382_and_r500()
    test_fet_reasons_mention_missed_main_rebuy()
    test_fet_reasons_mention_first_touch_level()
    test_fet_reasons_mention_main_rebuy_price()
    test_fet_is_relevant()
    test_r500_touched_action_buy_dip()
    test_ondo_without_fib_ext_wait()
    test_deep_retrace_profile_range_bounce()
    test_deep_retrace_buy_zone_at_deeper_levels()
    test_retesting_breakout_gate_scenario()
    test_ext_1272_touched_rejected_scenario_reentry_wait()
    test_no_context_scenario_no_clear_plan()
    test_far_moonbag_not_relevant()
    test_do_not_touch_not_relevant()
    test_relevant_states_constant_has_expected_entries()
    test_order_summary_matching_buy_near_zone()
    test_order_summary_no_match_when_far()
    test_order_summary_missing_suggested()
    test_take_profit_waiting_when_target_is_near_and_sell_order_exists()
    test_reload_zone_approaching_when_price_is_near_reload_zone()
    test_price_ran_away_when_price_is_far_above_target_assumptions()
    test_invalidation_near_when_price_approaches_risk_zone()
    test_order_too_far_or_stale_when_open_orders_are_far_from_current_price()
    test_do_nothing_for_neutral_valid_state()
    test_insufficient_data_when_zones_are_missing()
    test_render_full_html_contains_toggle_buttons()
    test_render_full_html_uses_profit_plan_title()
    test_render_full_html_includes_manual_state_labels_and_fields()
    test_profit_plan_uses_public_monitor_href_not_filesystem_path()
    test_render_full_html_data_relevant_attribute()
    test_render_full_html_not_relevant_card_present()
    test_render_full_html_safety_marker()
    test_render_full_html_javascript_setview()
    test_render_full_html_no_raw_order_dump()
    test_profit_plan_links_to_open_orders_monitor()
    test_resolve_monitor_link_prefers_public_href()
    test_profit_plan_sources_do_not_introduce_order_mutation_strings()
    test_json_snapshot_structure()
    test_json_snapshot_is_valid_json()
    print("ok")


if __name__ == "__main__":
    main()
