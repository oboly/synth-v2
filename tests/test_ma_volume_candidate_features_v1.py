from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.research.ma_volume_candidate_features_v1 import (
    MAVolumeCandidateInputError,
    MODEL_ID,
    MODEL_VERSION,
    build_candidate_frame,
)


def _candles(count: int = 230, *, market: str = "BTC-EUR") -> pd.DataFrame:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    rows = []
    for index in range(count):
        open_ts = start + timedelta(hours=4 * index)
        close = 100.0 + index * 0.25
        rows.append(
            {
                "market": market,
                "interval": "4h",
                "start_ts": open_ts,
                "end_ts": open_ts + timedelta(hours=4),
                "open": close - 0.1,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": 1000.0 + index,
                "is_final": True,
            }
        )
    return pd.DataFrame(rows)


def test_builds_sma150_sma200_slope_stack_and_existing_volume_ratio() -> None:
    candles = _candles()
    asof = candles.iloc[-1]["end_ts"]

    result = build_candidate_frame(candles, asof_ts_utc=asof)
    row = result.iloc[-1]

    assert pd.notna(row["sma_150"])
    assert pd.notna(row["sma_200"])
    assert pd.notna(row["close_vs_sma150_pct"])
    assert pd.notna(row["sma150_slope_pct_6b"])
    assert bool(row["bullish_ma_stack"]) is True
    assert pd.notna(row["volume_ratio_20"])
    assert row["candidate_model_id"] == MODEL_ID
    assert row["candidate_model_version"] == MODEL_VERSION
    assert row["candidate_slope_bars"] == 6


def test_future_candles_do_not_change_point_in_time_result() -> None:
    candles = _candles()
    asof = candles.iloc[219]["end_ts"]
    baseline = build_candidate_frame(candles, asof_ts_utc=asof)

    future = candles.iloc[-1:].copy()
    future["start_ts"] = pd.Timestamp(asof) + pd.Timedelta(hours=4)
    future["end_ts"] = pd.Timestamp(asof) + pd.Timedelta(hours=8)
    future["open"] = 1_000_000.0
    future["high"] = 1_000_001.0
    future["low"] = 999_999.0
    future["close"] = 1_000_000.0
    future["volume"] = 9_999_999.0

    with_future = build_candidate_frame(
        pd.concat([candles, future], ignore_index=True),
        asof_ts_utc=asof,
    )

    pd.testing.assert_frame_equal(baseline, with_future)


def test_slope_window_is_explicit_research_parameter() -> None:
    candles = _candles()
    asof = candles.iloc[-1]["end_ts"]

    result = build_candidate_frame(candles, asof_ts_utc=asof, slope_bars=12)

    assert "sma50_slope_pct_12b" in result.columns
    assert "sma150_slope_pct_12b" in result.columns
    assert "sma200_slope_pct_12b" in result.columns
    assert set(result["candidate_slope_bars"]) == {12}


def test_rejects_multi_market_input_instead_of_mixing_series() -> None:
    candles = pd.concat([_candles(210, market="BTC-EUR"), _candles(210, market="ETH-EUR")])
    asof = candles["end_ts"].max()

    with pytest.raises(MAVolumeCandidateInputError, match="exactly one market"):
        build_candidate_frame(candles, asof_ts_utc=asof)


def test_rejects_non_positive_slope_window() -> None:
    candles = _candles()
    asof = candles.iloc[-1]["end_ts"]

    with pytest.raises(MAVolumeCandidateInputError, match="positive"):
        build_candidate_frame(candles, asof_ts_utc=asof, slope_bars=0)
