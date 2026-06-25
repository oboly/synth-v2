from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.reporting.market_breath_live_v1 import (
    STATUS_AVAILABLE,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    build_market_breath_live_by_symbol,
    trajectory_label_for_market_breath_phase,
)
from src.research.run_market_breath_analysis_v1 import Asset, Candle


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
    assert payload["SOL"]["trajectory_label"] == "TRANSITION_UNCLEAR"
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
    assert payload["ADA"]["trajectory_label"] == "TRANSITION_UNCLEAR"
    assert payload["ADA"]["source_candle_ts_utc"] == "2026-06-24T04:00:00Z"
    assert payload["ADA"]["warnings"] == ["SOURCE_CANDLE_STALE"]


