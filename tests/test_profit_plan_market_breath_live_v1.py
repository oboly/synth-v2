from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.reporting.manual_short_trader_profit_plan_v1 import (
    ActiveOrderSummary,
    ProfitPlanCard,
    build_json_snapshot,
    render_full_html,
)
from src.reporting.market_breath_live_v1 import (
    STATUS_AVAILABLE,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    build_market_breath_live_by_symbol,
    trajectory_label_for_market_breath_phase,
)
from src.research.run_market_breath_analysis_v1 import Asset, Candle


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


def _minimal_card(symbol: str, market_breath_live: dict[str, object] | None) -> ProfitPlanCard:
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
        market_breath_live=market_breath_live,
    )


def _candle(asset_id: int, close_ts_utc: datetime) -> Candle:
    return Candle(
        asset_id=asset_id,
        close_ts_utc=close_ts_utc,
        open_price=1.0,
        high_price=1.0,
        low_price=1.0,
        close_price=1.0,
    )


def test_phase_to_trajectory_mapping() -> None:
    assert trajectory_label_for_market_breath_phase("INHALE_ACCUMULATION") == "BUILDING_TOWARD_EXPANSION"
    assert trajectory_label_for_market_breath_phase("HOLD_COMPRESSION") == "COMPRESSION_WAITING_FOR_BREAK"
    assert trajectory_label_for_market_breath_phase("EXHALE_EXPANSION") == "EXPANSION_ACTIVE"
    assert trajectory_label_for_market_breath_phase("OVERBREATH_EXTENSION") == "EXTENSION_COOLDOWN_RISK"
    assert trajectory_label_for_market_breath_phase("COLLAPSE_RESET") == "RESET_RECOVERY_WATCH"
    assert trajectory_label_for_market_breath_phase("NEUTRAL_TRANSITION") == "TRANSITION_UNCLEAR"
    assert trajectory_label_for_market_breath_phase("INSUFFICIENT_DATA") == "TRANSITION_UNCLEAR"
    assert (
        trajectory_label_for_market_breath_phase(
            "EXHALE_EXPANSION",
            availability_state=STATUS_STALE,
        )
        == "TRANSITION_UNCLEAR"
    )


def test_live_payload_available(monkeypatch) -> None:
    asof = datetime(2026, 6, 24, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    btc = Asset(asset_id=1, symbol="BTC")
    eth = Asset(asset_id=2, symbol="ETH")

    monkeypatch.setattr("src.reporting.market_breath_live_v1.latest_asof_ts", lambda *_args, **_kwargs: asof)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.fetch_assets", lambda *_args, **_kwargs: [btc, eth])
    monkeypatch.setattr(
        "src.reporting.market_breath_live_v1.fetch_candles",
        lambda *_args, **_kwargs: {
            1: [_candle(1, asof)],
            2: [_candle(2, asof)],
        },
    )
    monkeypatch.setattr(
        "src.reporting.market_breath_live_v1.build_base_observation",
        lambda *, asset, **_kwargs: {
            "symbol": asset.symbol,
            "market_breath_phase": "NEUTRAL_TRANSITION" if asset.symbol == "BTC" else "EXHALE_EXPANSION",
            "market_breath_state": "UNKNOWN" if asset.symbol == "BTC" else "CONFIRMED",
            "market_breath_confidence": 83.5 if asset.symbol == "ETH" else 50.0,
            "compression_score": 10.0 if asset.symbol == "ETH" else 40.0,
            "expansion_score": 74.0 if asset.symbol == "ETH" else 20.0,
            "momentum_score": 38.0 if asset.symbol == "ETH" else 0.0,
            "reversal_pressure_score": 11.0 if asset.symbol == "ETH" else 0.0,
            "relative_strength_score": 4.0 if asset.symbol == "ETH" else 0.0,
            "invalid_reason": None,
        },
    )
    monkeypatch.setattr("src.reporting.market_breath_live_v1.add_breadth_and_scores", lambda rows, _lookback: rows)

    payload = build_market_breath_live_by_symbol(object(), symbols=["ETH"])

    assert set(payload) == {"ETH"}
    assert payload["ETH"] == {
        "availability_state": "AVAILABLE",
        "market_breath_phase": "EXHALE_EXPANSION",
        "market_breath_state": "CONFIRMED",
        "market_breath_confidence": 83.5,
        "raw_scores": {
            "compression": 10.0,
            "expansion": 74.0,
            "momentum": 38.0,
            "reversal_pressure": 11.0,
            "relative_strength": 4.0,
        },
        "closest_regime_context": "EXHALE_EXPANSION",
        "closest_regime_failed_conditions": [],
        "neutral_reason": None,
        "trajectory_label": "EXPANSION_ACTIVE",
        "source_candle_ts_utc": "2026-06-24T12:00:00Z",
        "resolved_asof_ts_utc": "2026-06-24T12:00:00Z",
        "freshness_label": "FRESH",
        "freshness_reason": "current_interval_candle",
        "warnings": [],
    }


def test_live_payload_insufficient_data_is_unavailable(monkeypatch) -> None:
    asof = datetime(2026, 6, 24, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    btc = Asset(asset_id=1, symbol="BTC")
    sol = Asset(asset_id=2, symbol="SOL")

    monkeypatch.setattr("src.reporting.market_breath_live_v1.latest_asof_ts", lambda *_args, **_kwargs: asof)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.fetch_assets", lambda *_args, **_kwargs: [btc, sol])
    monkeypatch.setattr(
        "src.reporting.market_breath_live_v1.fetch_candles",
        lambda *_args, **_kwargs: {
            1: [_candle(1, asof)],
            2: [_candle(2, asof)],
        },
    )

    def _build_row(*, asset, **_kwargs):
        if asset.symbol == "BTC":
            return {
                "symbol": "BTC",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
                "market_breath_confidence": 50.0,
                "invalid_reason": None,
            }
        return {
            "symbol": "SOL",
            "market_breath_phase": "INSUFFICIENT_DATA",
            "market_breath_state": "UNKNOWN",
            "market_breath_confidence": 0.0,
            "invalid_reason": "insufficient_candles:7<24",
        }

    monkeypatch.setattr("src.reporting.market_breath_live_v1.build_base_observation", _build_row)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.add_breadth_and_scores", lambda rows, _lookback: rows)

    payload = build_market_breath_live_by_symbol(object(), symbols=["SOL"])

    assert payload["SOL"]["availability_state"] == STATUS_UNAVAILABLE
    assert payload["SOL"]["market_breath_phase"] is None
    assert payload["SOL"]["market_breath_state"] is None
    assert payload["SOL"]["market_breath_confidence"] is None
    assert payload["SOL"]["raw_scores"] == {
        "compression": None,
        "expansion": None,
        "momentum": None,
        "reversal_pressure": None,
        "relative_strength": None,
    }
    assert payload["SOL"]["trajectory_label"] == "TRANSITION_UNCLEAR"
    assert payload["SOL"]["closest_regime_context"] is None
    assert payload["SOL"]["neutral_reason"] is None
    assert payload["SOL"]["warnings"] == ["insufficient_candles:7<24"]


def test_live_payload_stale_source_candle(monkeypatch) -> None:
    asof = datetime(2026, 6, 24, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    stale_ts = asof - timedelta(hours=8)
    btc = Asset(asset_id=1, symbol="BTC")
    ada = Asset(asset_id=2, symbol="ADA")

    monkeypatch.setattr("src.reporting.market_breath_live_v1.latest_asof_ts", lambda *_args, **_kwargs: asof)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.fetch_assets", lambda *_args, **_kwargs: [btc, ada])
    monkeypatch.setattr(
        "src.reporting.market_breath_live_v1.fetch_candles",
        lambda *_args, **_kwargs: {
            1: [_candle(1, asof)],
            2: [_candle(2, stale_ts)],
        },
    )
    monkeypatch.setattr(
        "src.reporting.market_breath_live_v1.build_base_observation",
        lambda *, asset, **_kwargs: {
            "symbol": asset.symbol,
            "market_breath_phase": "NEUTRAL_TRANSITION" if asset.symbol == "BTC" else "INHALE_ACCUMULATION",
            "market_breath_state": "UNKNOWN" if asset.symbol == "BTC" else "FORMING",
            "market_breath_confidence": 70.0,
            "invalid_reason": None,
        },
    )
    monkeypatch.setattr("src.reporting.market_breath_live_v1.add_breadth_and_scores", lambda rows, _lookback: rows)

    payload = build_market_breath_live_by_symbol(object(), symbols=["ADA"])

    assert payload["ADA"]["availability_state"] == STATUS_STALE
    assert payload["ADA"]["market_breath_phase"] is None
    assert payload["ADA"]["market_breath_state"] is None
    assert payload["ADA"]["market_breath_confidence"] is None
    assert payload["ADA"]["raw_scores"] == {
        "compression": None,
        "expansion": None,
        "momentum": None,
        "reversal_pressure": None,
        "relative_strength": None,
    }
    assert payload["ADA"]["trajectory_label"] == "TRANSITION_UNCLEAR"
    assert payload["ADA"]["source_candle_ts_utc"] == "2026-06-24T04:00:00Z"
    assert payload["ADA"]["warnings"] == ["SOURCE_CANDLE_STALE"]


def test_live_payload_neutral_row_gets_deterministic_diagnostics(monkeypatch) -> None:
    asof = datetime(2026, 6, 24, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    btc = Asset(asset_id=1, symbol="BTC")
    xrp = Asset(asset_id=2, symbol="XRP")

    monkeypatch.setattr("src.reporting.market_breath_live_v1.latest_asof_ts", lambda *_args, **_kwargs: asof)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.fetch_assets", lambda *_args, **_kwargs: [btc, xrp])
    monkeypatch.setattr(
        "src.reporting.market_breath_live_v1.fetch_candles",
        lambda *_args, **_kwargs: {
            1: [_candle(1, asof)],
            2: [_candle(2, asof)],
        },
    )

    def _build_row(*, asset, **_kwargs):
        if asset.symbol == "BTC":
            return {
                "symbol": "BTC",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
                "market_breath_confidence": 100.0,
                "compression_score": 10.0,
                "expansion_score": 10.0,
                "momentum_score": 0.0,
                "reversal_pressure_score": 0.0,
                "relative_strength_score": 0.0,
                "invalid_reason": None,
            }
        return {
            "symbol": "XRP",
            "market_breath_phase": "NEUTRAL_TRANSITION",
            "market_breath_state": "UNKNOWN",
            "market_breath_confidence": 100.0,
            "compression_score": 40.0,
            "expansion_score": 50.0,
            "momentum_score": 25.0,
            "reversal_pressure_score": 5.0,
            "relative_strength_score": -1.0,
            "invalid_reason": None,
        }

    monkeypatch.setattr("src.reporting.market_breath_live_v1.build_base_observation", _build_row)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.add_breadth_and_scores", lambda rows, _lookback: rows)

    payload = build_market_breath_live_by_symbol(object(), symbols=["XRP"])
    row = payload["XRP"]

    assert row["availability_state"] == STATUS_AVAILABLE
    assert row["market_breath_phase"] == "NEUTRAL_TRANSITION"
    assert row["market_breath_state"] == "UNKNOWN"
    assert row["raw_scores"] == {
        "compression": 40.0,
        "expansion": 50.0,
        "momentum": 25.0,
        "reversal_pressure": 5.0,
        "relative_strength": -1.0,
    }
    assert row["closest_regime_context"] == "EXHALE_EXPANSION"
    assert row["closest_regime_failed_conditions"] == [
        "expansion below EXHALE threshold (50.0 < 55.0)",
        "relative strength not above EXHALE threshold (-1.0 <= 0.0)",
    ]
    assert row["neutral_reason"] == (
        "No classified phase — expansion below EXHALE threshold (50.0 < 55.0); "
        "relative strength not above EXHALE threshold (-1.0 <= 0.0)"
    )


def test_profit_plan_json_and_html_include_market_breath_payload() -> None:
    payload = {
        "availability_state": "AVAILABLE",
        "market_breath_phase": "EXHALE_EXPANSION",
        "market_breath_state": "CONFIRMED",
        "market_breath_confidence": 88.2,
        "raw_scores": {
            "compression": 12.0,
            "expansion": 74.0,
            "momentum": 38.0,
            "reversal_pressure": 11.0,
            "relative_strength": 4.0,
        },
        "closest_regime_context": "EXHALE_EXPANSION",
        "closest_regime_failed_conditions": [],
        "neutral_reason": None,
        "trajectory_label": "EXPANSION_ACTIVE",
        "source_candle_ts_utc": "2026-06-24T12:00:00Z",
        "resolved_asof_ts_utc": "2026-06-24T12:00:00Z",
        "freshness_label": "FRESH",
        "freshness_reason": "current_interval_candle",
        "warnings": [],
    }
    card = _minimal_card("BTC", payload)

    snapshot = build_json_snapshot([card], broker_mode="db_snapshot")
    html = render_full_html([card], rendered_at="now", broker_mode="db_snapshot")

    assert snapshot["symbols"][0]["market_breath"] == payload
    assert "market_context" in snapshot["symbols"][0]
    assert "data-mb-phase='EXHALE_EXPANSION'" in html
    assert "data-mb-trajectory='EXPANSION_ACTIVE'" in html
    assert "Market Breath" in html
    assert "EXPANSION_ACTIVE" in html
    assert "Data coverage" in html
    assert "Confidence" not in html


def test_reporting_and_ui_do_not_duplicate_classifier_threshold_literals() -> None:
    reporting_source = Path("src/reporting/market_breath_live_v1.py").read_text(encoding="utf-8")
    ui_source = Path("src/reporting/manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")

    assert "diagnose_market_breath_context_v1(" in reporting_source
    for literal in ("-25.0", "45.0", "55.0", "65.0", "70.0", "75.0", "35.0", "20.0", "5.0"):
        assert literal not in reporting_source
        assert literal not in ui_source
