from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import ast
from pathlib import Path

from src.market_context.breath_curve_core_v1 import Candle as CoreCandle
from src.market_context.breath_curve_live_v1 import (
    STATUS_UNAVAILABLE,
    BreathCurveLiveCandle,
    build_breath_curve_live_by_symbol,
)
from src.market_context.breath_curve_core_v1 import PartialResult
from src.reporting.manual_short_trader_profit_plan_v1 import (
    ActiveOrderSummary,
    ProfitPlanCard,
    build_json_snapshot,
    render_full_html,
)


ROOT = Path(__file__).parent.parent


def test_shared_core_is_volume_independent() -> None:
    assert "volume" not in {field.name for field in fields(CoreCandle)}


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



def test_unavailable_anchor_or_data_is_honest() -> None:
    payload = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": _enough_candles(10)},
        as_of_ts_utc=datetime(2026, 5, 10, tzinfo=UTC),
        symbols=["ETH"],
    )["ETH"]

    assert payload["availability_state"] == STATUS_UNAVAILABLE
    assert payload["phase_marker"] is None
    assert payload["current_checkpoint"] is None
    assert payload["resolver_name"] == "fixed_global_epoch_v1"
    assert payload["anchor_source"] == "fixed_global_epoch_v1"
    assert payload["anchor_ts_utc"] == "2026-05-03T00:00:00Z"
    assert payload["epoch_index"] == 5
    assert payload["warnings"] == ["INSUFFICIENT_CLOSED_DAILY_CANDLES"]


def _fake_pr(
    offset_days: float = -7.0,
    current_code: str = "IGNITION_PRE_SPIKE",
    next_code: str = "MAIN_PULSE_TP_HIGH",
    score: float = 0.82,
) -> PartialResult:
    return PartialResult(
        symbol="ETH",
        venue="live",
        interval_code="1d",
        anchor_ts_utc="2026-05-24T00:00:00Z",
        as_of_ts_utc="2026-06-09T00:00:00Z",
        cycle_days=21.0,
        phase_offset_days=offset_days,
        tolerance_hours=36.0,
        required_ratio=None,
        partial_match_score=score,
        partial_shape_score=score,
        partial_timing_score=score,
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


def test_no_future_candle_changes_payload(monkeypatch) -> None:
    as_of = datetime(2026, 6, 9, tzinfo=UTC)
    candles = _enough_candles(40)
    with_future = [*candles, _daily_candle(60, close_price="9.99")]

    seen_candle_counts: list[int] = []

    def _fake_select(candles, symbol, anchor, as_of):
        seen_candle_counts.append(len(candles))
        return None

    monkeypatch.setattr("src.market_context.breath_curve_live_v1._select_offset", _fake_select)

    base = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": candles, "BTC": candles},
        as_of_ts_utc=as_of,
        symbols=["ETH"],
    )
    with_future_result = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": with_future, "BTC": with_future},
        as_of_ts_utc=as_of,
        symbols=["ETH"],
    )

    assert base == with_future_result
    assert base["ETH"]["source_candle_ts_utc"] == "2026-06-09T00:00:00Z"
    assert all(count == 40 for count in seen_candle_counts)


def test_available_payload_fields_when_offset_resolved(monkeypatch) -> None:
    as_of = datetime(2026, 6, 9, tzinfo=UTC)
    candles = _enough_candles(40)
    pr = _fake_pr(-7.0, current_code="IGNITION_PRE_SPIKE", next_code="MAIN_PULSE_TP_HIGH")

    monkeypatch.setattr(
        "src.market_context.breath_curve_live_v1._select_offset",
        lambda *_args, **_kwargs: pr,
    )

    payload = build_breath_curve_live_by_symbol(
        candles_by_symbol={"ETH": candles, "BTC": candles},
        as_of_ts_utc=as_of,
        symbols=["ETH"],
    )["ETH"]

    # epoch: (2026-06-09 - 2026-01-18).days = 142; 142 // 21 = 6; anchor = Jan 18 + 126 = May 24
    assert payload["availability_state"] == "AVAILABLE"
    assert payload["resolver_name"] == "fixed_global_epoch_v1"
    assert payload["anchor_source"] == "fixed_global_epoch_v1"
    assert payload["epoch_index"] == 6
    assert payload["anchor_ts_utc"] == "2026-05-24T00:00:00Z"
    assert payload["phase_offset_days"] == -7.0
    assert payload["current_checkpoint"] == "IGNITION_PRE_SPIKE"
    assert payload["next_checkpoint"] == "MAIN_PULSE_TP_HIGH"
    assert payload["next_target_expected_ts_utc"] == "2026-06-13T00:00:00Z"
    assert payload["next_target_is_future"] is True
    assert "CURRENT_EPOCH_HOLDOUT_UNVERIFIED" in payload["warnings"]


def test_historical_epoch_anchors_match_backtest_records() -> None:
    from src.market_context.breath_curve_epoch_v1 import resolve_global_epoch_anchor

    historical = {
        datetime(2026, 3, 13, tzinfo=UTC): datetime(2026, 3, 1, tzinfo=UTC),
        datetime(2026, 4, 3, tzinfo=UTC): datetime(2026, 3, 22, tzinfo=UTC),
        datetime(2026, 4, 22, tzinfo=UTC): datetime(2026, 4, 12, tzinfo=UTC),
    }
    for as_of, expected_anchor in historical.items():
        anchor, _ = resolve_global_epoch_anchor(as_of)
        assert anchor == expected_anchor, f"as_of={as_of.date()}: got {anchor.date()}, want {expected_anchor.date()}"


def test_profit_plan_json_and_html_include_breath_curve_payload() -> None:
    # Payload matches the current fixed-epoch provider field contract.
    payload = {
        "availability_state": "AVAILABLE",
        "as_of_ts_utc": "2026-06-24T12:00:00Z",
        "source_candle_ts_utc": "2026-06-24T00:00:00Z",
        "freshness_label": "FRESH",
        "phase_marker": "IGNITION_PRE_SPIKE",
        "phase_offset_days": -7.0,
        "phase_offset_band": "-7",
        "template_match_score": 0.82,
        "current_checkpoint": "IGNITION_PRE_SPIKE",
        "next_checkpoint": "MAIN_PULSE_TP_HIGH",
        "next_target_expected_ts_utc": "2026-06-27T00:00:00Z",
        "next_target_is_future": True,
        "lead_lag_vs_btc": {"relation": "AHEAD_OF_BTC", "delta_days": 3.0},
        "anchor_ts_utc": "2026-06-14T00:00:00Z",
        "anchor_source": "fixed_global_epoch_v1",
        "epoch_index": 7,
        "validation_state": "CURRENT_EPOCH_HOLDOUT_UNVERIFIED",
        "resolver_name": "fixed_global_epoch_v1",
        "resolver_version": "0.1",
        "data_coverage": {"coverage_ratio": 1.0, "closed_candle_count": 120},
        "warnings": ["CURRENT_EPOCH_HOLDOUT_UNVERIFIED"],
    }
    card = _minimal_card("BTC", payload)

    snapshot = build_json_snapshot([card], broker_mode="db_snapshot")
    html = render_full_html([card], rendered_at="now", broker_mode="db_snapshot")

    # JSON contract: full payload stored under breath_curve; no market breath key present.
    assert snapshot["symbols"][0]["breath_curve"] == payload
    assert "market_breath" not in snapshot["symbols"][0]
    assert "market_breath_live" not in snapshot["symbols"][0]

    # Epoch provenance fields round-trip correctly.
    bc = snapshot["symbols"][0]["breath_curve"]
    assert bc["anchor_source"] == "fixed_global_epoch_v1"
    assert bc["epoch_index"] == 7
    assert bc["validation_state"] == "CURRENT_EPOCH_HOLDOUT_UNVERIFIED"
    assert bc["resolver_name"] == "fixed_global_epoch_v1"
    assert "anchor_search_days" not in bc
    assert "resolver_candidate_count" not in bc
    assert "resolver_rank_basis" not in bc

    # HTML contract: breath curve data attributes present; no market breath attributes.
    assert "data-bc-current-checkpoint='IGNITION_PRE_SPIKE'" in html
    assert "data-bc-next-checkpoint='MAIN_PULSE_TP_HIGH'" in html
    assert "data-mb-phase" not in html
    assert "data-mb-trajectory" not in html
    # Breathline is demoted to research-only muted context (label + disabled state).
    assert "Breathline context" in html
    assert "RESEARCH_ONLY_DISABLED" in html
    assert "MAIN_PULSE_TP_HIGH" in html


def test_live_provider_imports_no_research_runner_or_aplus_module() -> None:
    source = (ROOT / "src" / "market_context" / "breath_curve_live_v1.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert all(not name.startswith("src.research.run_") for name in imported_modules)
    assert all("aplus" not in name.lower() for name in imported_modules)
