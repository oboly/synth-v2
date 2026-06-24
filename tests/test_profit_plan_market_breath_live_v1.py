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


def test_phase_to_trajectory_mapping_offline() -> None:
    assert trajectory_label_for_market_breath_phase("INHALE_ACCUMULATION") == "BUILDING_TOWARD_EXPANSION"
    assert trajectory_label_for_market_breath_phase("HOLD_COMPRESSION") == "COMPRESSION_WAITING_FOR_BREAK"
    assert trajectory_label_for_market_breath_phase("EXHALE_EXPANSION") == "EXPANSION_ACTIVE"
    assert trajectory_label_for_market_breath_phase("OVERBREATH_EXTENSION") == "EXTENSION_COOLDOWN_RISK"
    assert trajectory_label_for_market_breath_phase("COLLAPSE_RESET") == "RESET_RECOVERY_WATCH"
    assert trajectory_label_for_market_breath_phase("NEUTRAL_TRANSITION") == "TRANSITION_UNCLEAR"
    assert trajectory_label_for_market_breath_phase("INSUFFICIENT_DATA") == "TRANSITION_UNCLEAR"
    assert trajectory_label_for_market_breath_phase("EXHALE_EXPANSION", availability_state=STATUS_STALE) == "TRANSITION_UNCLEAR"


def test_old_market_breath_live_payload_available(monkeypatch) -> None:
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

    assert payload["ETH"]["availability_state"] == STATUS_AVAILABLE
    assert payload["ETH"]["market_breath_phase"] == "EXHALE_EXPANSION"
    assert payload["ETH"]["market_breath_state"] == "CONFIRMED"
    assert payload["ETH"]["trajectory_label"] == "EXPANSION_ACTIVE"


def test_old_market_breath_live_payload_unavailable_and_stale(monkeypatch) -> None:
    asof = datetime(2026, 6, 24, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    stale_ts = asof - timedelta(hours=8)
    btc = Asset(asset_id=1, symbol="BTC")
    sol = Asset(asset_id=2, symbol="SOL")
    ada = Asset(asset_id=3, symbol="ADA")

    monkeypatch.setattr("src.reporting.market_breath_live_v1.latest_asof_ts", lambda *_args, **_kwargs: asof)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.fetch_assets", lambda *_args, **_kwargs: [btc, sol, ada])
    monkeypatch.setattr(
        "src.reporting.market_breath_live_v1.fetch_candles",
        lambda *_args, **_kwargs: {
            1: [_candle(1, asof)],
            2: [_candle(2, asof)],
            3: [_candle(3, stale_ts)],
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
        if asset.symbol == "SOL":
            return {
                "symbol": "SOL",
                "market_breath_phase": "INSUFFICIENT_DATA",
                "market_breath_state": "UNKNOWN",
                "market_breath_confidence": 0.0,
                "invalid_reason": "insufficient_candles:7<24",
            }
        return {
            "symbol": "ADA",
            "market_breath_phase": "INHALE_ACCUMULATION",
            "market_breath_state": "FORMING",
            "market_breath_confidence": 70.0,
            "invalid_reason": None,
        }

    monkeypatch.setattr("src.reporting.market_breath_live_v1.build_base_observation", _build_row)
    monkeypatch.setattr("src.reporting.market_breath_live_v1.add_breadth_and_scores", lambda rows, _lookback: rows)

    payload = build_market_breath_live_by_symbol(object(), symbols=["SOL", "ADA"])

    assert payload["SOL"]["availability_state"] == STATUS_UNAVAILABLE
    assert payload["SOL"]["warnings"] == ["insufficient_candles:7<24"]
    assert payload["ADA"]["availability_state"] == STATUS_STALE
    assert payload["ADA"]["warnings"] == ["SOURCE_CANDLE_STALE"]
