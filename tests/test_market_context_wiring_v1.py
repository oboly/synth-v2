from __future__ import annotations

import json
from pathlib import Path

from src.reporting.manual_short_trader_profit_plan_v1 import (
    ActiveOrderSummary,
    ProfitPlanCard,
    build_json_snapshot,
)

ROOT = Path(__file__).parent.parent


def _order_summary() -> ActiveOrderSummary:
    return ActiveOrderSummary(
        open_buy_orders=0,
        open_sell_orders=0,
        matching_buys=0,
        matching_sells=0,
        nearest_buy_price=None,
        nearest_sell_price=None,
        nearest_buy_distance_pct=None,
        nearest_sell_distance_pct=None,
        nearest_open_buy_distance_pct=None,
        nearest_open_sell_distance_pct=None,
        max_open_order_distance_pct=None,
        missing_suggested=(),
        existing_open_orders_summary="none",
    )


def _minimal_card(symbol: str) -> ProfitPlanCard:
    return ProfitPlanCard(
        symbol=symbol,
        market=f"{symbol}-EUR",
        fib_trading_horizon="DAILY",
        short_context_input_status="OK",
        short_context_coverage_status="OK",
        short_context_display_state="OK",
        current_price=None,
        current_price_status=None,
        current_price_age_min=None,
        history_high_since_activation=None,
        history_low_since_activation=None,
        all_sell_targets_completed=False,
        scenario_type="LONG",
        action_label="HOLD",
        timeframe_label="DAILY",
        buy_zone=(),
        sell_zone=(),
        invalidation_level=None,
        reasons=(),
        order_summary=_order_summary(),
        target_exit_zone=(),
        active_target=None,
        target_level_statuses=(),
        reload_reentry_zone=(),
        invalidation_risk_zone=None,
        distance_to_target_pct=None,
        distance_to_reload_pct=None,
        distance_to_invalidation_pct=None,
        primary_state="ACTIVE",
        secondary_state=None,
        suggested_manual_attention_label="NONE",
        setup_state="OK",
        event_state="NONE",
        ladder_states=(),
        relevance_reasons=(),
        is_relevant=True,
        fib_nav_context=None,
    )


_MINIMAL_MARKET_CONTEXT = {
    "local_ma_atr_context": {"state": "ABOVE_MA", "ma_price": None, "atr": None,
                             "distance_atr": None, "latest_close_ts_utc": None, "warnings": []},
    "impulse_health": {"state": "HEALTHY_IMPULSE", "ema_price": None, "atr": None,
                       "swing_high_price": None, "distance_atr": None,
                       "pullback_from_high_atr": None, "latest_close_ts_utc": None, "warnings": []},
    "extension_context": {"state": "BUILDING", "label": "Context building",
                          "suggested_profit_plan_bias": "NONE", "warnings": []},
}

_NO_DATA_MARKET_CONTEXT = {
    "local_ma_atr_context": {"state": "NO_DATA", "ma_price": None, "atr": None,
                             "distance_atr": None, "latest_close_ts_utc": None, "warnings": ["INSUFFICIENT_CANDLES"]},
    "impulse_health": {"state": "NO_DATA", "ema_price": None, "atr": None,
                       "swing_high_price": None, "distance_atr": None,
                       "pullback_from_high_atr": None, "latest_close_ts_utc": None, "warnings": ["INSUFFICIENT_CANDLES"]},
    "extension_context": {"state": "NO_DATA", "label": "Insufficient data",
                          "suggested_profit_plan_bias": "NONE", "warnings": []},
}


def test_market_context_appears_in_per_symbol_json() -> None:
    snapshot = build_json_snapshot(
        [_minimal_card("BTC")],
        market_context_by_symbol={"BTC": _MINIMAL_MARKET_CONTEXT},
    )
    sym = snapshot["symbols"][0]
    assert sym["market_context"] == _MINIMAL_MARKET_CONTEXT
    json.dumps(snapshot)


def test_market_context_is_null_when_not_passed() -> None:
    snapshot = build_json_snapshot([_minimal_card("BTC")])
    assert snapshot["symbols"][0]["market_context"] is None
    json.dumps(snapshot)


def test_market_context_is_null_when_symbol_missing_from_dict() -> None:
    snapshot = build_json_snapshot(
        [_minimal_card("BTC")],
        market_context_by_symbol={"ETH": _MINIMAL_MARKET_CONTEXT},
    )
    assert snapshot["symbols"][0]["market_context"] is None


def test_market_context_no_data_payload_is_emitted_as_non_null() -> None:
    snapshot = build_json_snapshot(
        [_minimal_card("BTC")],
        market_context_by_symbol={"BTC": _NO_DATA_MARKET_CONTEXT},
    )
    assert snapshot["symbols"][0]["market_context"] == _NO_DATA_MARKET_CONTEXT
    json.dumps(snapshot)


def test_market_context_payload_has_no_legacy_breathline_key() -> None:
    snapshot = build_json_snapshot(
        [_minimal_card("BTC")],
        market_context_by_symbol={"BTC": _MINIMAL_MARKET_CONTEXT},
    )
    assert "breathline" not in snapshot["symbols"][0]["market_context"]


def test_source_files_do_not_reintroduce_market_context_breathline_key() -> None:
    for rel_path in (
        "src/market_context/market_context_builder_v1.py",
        "src/reporting/manual_short_trader_profit_plan_v1.py",
    ):
        text = (ROOT / rel_path).read_text()
        assert '"breathline":' not in text


def test_existing_fields_still_present() -> None:
    snapshot = build_json_snapshot([_minimal_card("BTC")])
    sym = snapshot["symbols"][0]
    assert "market_context" in sym
    assert "symbol" in sym
    assert "order_summary" in sym
    assert "price_normalization" in sym
