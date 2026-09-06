from decimal import Decimal

from src.market_models.retracement_reload_v0 import RetracementReloadV0
from src.reporting.manual_short_trader_profit_plan_v1 import (
    ActiveOrderSummary,
    ProfitPlanCard,
    _actionability_display_bundle,
    _card_delta_payload,
    apply_retracement_reload_overlay,
)


def _orders() -> ActiveOrderSummary:
    return ActiveOrderSummary(
        open_buy_orders=0, open_sell_orders=0, matching_buys=0, matching_sells=0,
        nearest_buy_price=None, nearest_sell_price=None,
        nearest_buy_distance_pct=None, nearest_sell_distance_pct=None,
        nearest_open_buy_distance_pct=None, nearest_open_sell_distance_pct=None,
        max_open_order_distance_pct=None, missing_suggested=(),
        existing_open_orders_summary="",
    )


def _card() -> ProfitPlanCard:
    return ProfitPlanCard(
        symbol="SOL", market="SOL-EUR", fib_trading_horizon="SHORT",
        short_context_input_status="OK", short_context_coverage_status="OK",
        short_context_display_state="OK", current_price=Decimal("100"),
        current_price_status="FRESH", current_price_age_min=Decimal("1"),
        history_high_since_activation=None, history_low_since_activation=None,
        all_sell_targets_completed=False, scenario_type="LONG", action_label="WAIT",
        timeframe_label="4H", buy_zone=(), sell_zone=(), invalidation_level=None,
        reasons=(), order_summary=_orders(), target_exit_zone=(), active_target=None,
        target_level_statuses=(), reload_reentry_zone=(), invalidation_risk_zone=None,
        distance_to_target_pct=None, distance_to_reload_pct=None,
        distance_to_invalidation_pct=None, primary_state="ACTIVE", secondary_state=None,
        suggested_manual_attention_label="NONE", setup_state="OK", event_state="NONE",
        ladder_states=(), relevance_reasons=(), is_relevant=True,
    )


def _reload() -> RetracementReloadV0:
    return RetracementReloadV0(
        reload_map_version="retracement_reload_v0", source_map_id="map-1",
        direction="BULLISH", swing_low=Decimal("80"), swing_high=Decimal("120"),
        continuation_strength_state="STRONG", reload_strength_score=Decimal("0.75"),
        reload_quality_state="HIGH", preferred_reload_1_level="r_0382",
        preferred_reload_1_price=Decimal("104.72"), preferred_reload_2_level="r_0500",
        preferred_reload_2_price=Decimal("100"), invalidation_price=Decimal("80"),
        reason_codes=("HEURISTIC_V0_STRONG",),
    )


def test_profit_plan_renders_only_prepared_reload_guidance() -> None:
    card = apply_retracement_reload_overlay(_card(), _reload())
    reentry_line = _actionability_display_bundle(card)[4]
    assert reentry_line == "STATE STRONG · RELOAD 1 R_0382 €104.72 · RELOAD 2 R_0500 €100"


def test_profit_plan_json_carries_prepared_reload_guidance() -> None:
    payload = _card_delta_payload(apply_retracement_reload_overlay(_card(), _reload()))
    assert payload["reload_strength_state"] == "STRONG"
    assert payload["preferred_reload_1_level"] == "r_0382"
    assert payload["preferred_reload_1_price"] == "104.72"
    assert payload["preferred_reload_2_level"] == "r_0500"
    assert payload["preferred_reload_2_price"] == "100"
