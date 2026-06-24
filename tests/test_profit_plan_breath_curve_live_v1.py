from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_context.breath_curve_live_v1 import (
    STATUS_UNAVAILABLE,
    BreathCurveLiveCandle,
    BreathCurveResolvedCandidate,
    build_breath_curve_live_by_symbol,
)
from src.research.run_breath_curve_template_partial_v1 import PartialResult
from src.reporting.manual_short_trader_profit_plan_v1 import (
    ActiveOrderSummary,
    ProfitPlanCard,
    build_json_snapshot,
    render_full_html,
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


def _minimal_card(symbol: str, breath_curve: dict[str, object] | None) -> ProfitPlanCard:
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
        breath_curve=breath_curve,
    )


def _daily_candle(day: int, *, close_price: str = "1.00") -> BreathCurveLiveCandle:
    ts = datetime(2026, 5, 1, tzinfo=UTC) + timedelta(days=day)
    price = Decimal(close_price)
    return BreathCurveLiveCandle(
        close_ts_utc=ts,
        open_price=price,
        high_price=price,
        low_price=price,
        close_price=price,
    )


def _enough_candles(count: int = 40) -> list[BreathCurveLiveCandle]:
    return [_daily_candle(day) for day in range(count)]


def _candidate(offset_days: float, *, current_code: str, next_code: str) -> BreathCurveResolvedCandidate:
    partial = PartialResult(
        symbol="ETH",
        venue="live",
        interval_code="1d",
        anchor_ts_utc="2026-05-01T00:00:00Z",
        as_of_ts_utc="2026-06-09T00:00:00Z",
        cycle_days=21.0,
        phase_offset_days=offset_days,
        tolerance_hours=36.0,
        required_ratio=None,
        partial_match_score=0.82,
        partial_shape_score=0.88,
        partial_timing_score=0.79,
        marker_coverage_score=1.0,
        observed_marker_count=5,
        due_marker_count=5,
        available_shape_rule_count=8,
        passed_shape_rule_count=7,
        flags={"first_lift_above_anchor": True},
        markers=[
            {
                "ratio": 0.786,
                "code": current_code,
                "kind": "HIGH",
                "status": "OBSERVED_CLOSED_WINDOW",
                "expected_ts_utc": "2026-06-09T00:00:00Z",
                "observed_ts_utc": "2026-06-09T00:00:00Z",
                "observed_price": 1.0,
                "timing_error_hours": 0.0,
                "timing_score": 1.0,
                "matched": True,
            },
            {
                "ratio": 1.0,
                "code": next_code,
                "kind": "HIGH",
                "status": "FUTURE",
                "expected_ts_utc": "2026-06-13T00:00:00Z",
                "observed_ts_utc": None,
                "observed_price": None,
                "timing_error_hours": None,
                "timing_score": 0.0,
                "matched": False,
            },
        ],
        notes=[],
    )
    return BreathCurveResolvedCandidate(
        anchor_ts_utc=datetime(2026, 5, 1, tzinfo=UTC),
        partial_result=partial,
        phase_offset_band="-7",
        current_marker=partial.markers[0],
        next_marker=partial.markers[1],
    )


def test_no_future_candle_is_used() -> None:
    as_of = datetime(2026, 5, 3, tzinfo=UTC)
    candles = [_daily_candle(0), _daily_candle(1)]
    with_future = [*candles, _daily_candle(5, close_price="9.99")]

    base = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": candles},
        as_of_ts_utc=as_of,
        symbols=["ETH"],
    )
    future = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": with_future},
        as_of_ts_utc=as_of,
        symbols=["ETH"],
    )

    assert base == future
    assert base["ETH"]["source_candle_ts_utc"] == "2026-05-02T00:00:00Z"
    assert base["ETH"]["availability_state"] == STATUS_UNAVAILABLE


def test_same_as_of_input_is_deterministic() -> None:
    as_of = datetime(2026, 5, 10, tzinfo=UTC)
    candles = _enough_candles()

    first = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": candles, "BTC": candles},
        as_of_ts_utc=as_of,
        symbols=["ETH"],
    )
    second = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": candles, "BTC": candles},
        as_of_ts_utc=as_of,
        symbols=["ETH"],
    )

    assert first == second


def test_phase_offset_and_next_target_come_from_matcher_progression(monkeypatch) -> None:
    candidate = _candidate(-7.0, current_code="IGNITION_PRE_SPIKE", next_code="MAIN_PULSE_TP_HIGH")
    candles = _enough_candles()

    monkeypatch.setattr(
        "src.market_context.breath_curve_live_v1._resolve_candidate",
        lambda **_kwargs: candidate,
    )

    payload = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": candles, "BTC": candles},
        as_of_ts_utc=datetime(2026, 6, 9, tzinfo=UTC),
        symbols=["ETH"],
    )["ETH"]

    assert payload["availability_state"] == "AVAILABLE"
    assert payload["phase_offset_days"] == -7.0
    assert payload["phase_offset_band"] == "-7"
    assert payload["current_checkpoint"] == "IGNITION_PRE_SPIKE"
    assert payload["next_checkpoint"] == "MAIN_PULSE_TP_HIGH"
    assert payload["next_target_expected_ts_utc"] == "2026-06-13T00:00:00Z"
    assert payload["next_target_is_future"] is True


def test_unavailable_anchor_or_data_is_honest() -> None:
    payload = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": _enough_candles(10)},
        as_of_ts_utc=datetime(2026, 5, 10, tzinfo=UTC),
        symbols=["ETH"],
    )["ETH"]

    assert payload["availability_state"] == STATUS_UNAVAILABLE
    assert payload["phase_marker"] is None
    assert payload["current_checkpoint"] is None
    assert payload["warnings"] == ["INSUFFICIENT_CLOSED_DAILY_CANDLES"]


def test_profit_plan_json_and_html_use_breath_curve_not_market_breath() -> None:
    payload = {
        "availability_state": "AVAILABLE",
        "as_of_ts_utc": "2026-06-24T12:00:00Z",
        "source_candle_ts_utc": "2026-06-24T00:00:00Z",
        "freshness_label": "FRESH",
        "phase_marker": "IGNITION_PRE_SPIKE",
        "phase_offset_days": -7.0,
        "phase_offset_band": "-7",
        "template_match_score": 0.8123,
        "current_checkpoint": "IGNITION_PRE_SPIKE",
        "next_checkpoint": "MAIN_PULSE_TP_HIGH",
        "next_target_expected_ts_utc": "2026-06-27T00:00:00Z",
        "next_target_is_future": True,
        "lead_lag_vs_btc": {"relation": "AHEAD_OF_BTC", "delta_days": 3.0},
        "data_coverage": {"coverage_ratio": 1.0, "closed_candle_count": 120},
        "warnings": [],
    }
    card = _minimal_card("BTC", payload)

    snapshot = build_json_snapshot([card], broker_mode="db_snapshot")
    html = render_full_html([card], rendered_at="now", broker_mode="db_snapshot")

    assert snapshot["symbols"][0]["breath_curve"] == payload
    assert "market_breath" not in snapshot["symbols"][0]
    assert "data-bc-current-checkpoint='IGNITION_PRE_SPIKE'" in html
    assert "data-mb-phase" not in html
    assert "Breath Curve" in html
    assert "MAIN_PULSE_TP_HIGH" in html


def test_live_provider_has_no_aplus_dependency() -> None:
    text = (ROOT / "src" / "market_context" / "breath_curve_live_v1.py").read_text(encoding="utf-8").lower()
    assert "aplus" not in text
    assert "raw_text" not in text
