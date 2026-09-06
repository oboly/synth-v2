from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.research.momentum_flow_exhaustion_candidate_v1 import (
    ExhaustionCandidateInputError,
    STATE_CONFIRMED,
    STATE_INSUFFICIENT,
    build_exhaustion_candidate,
)


def _base(count: int = 25, *, direction: int = 1, volume: float = 1000.0) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(count):
        t = start + timedelta(hours=4 * i)
        close = 100.0 + direction * i * 0.6
        open_price = close - direction * 0.45
        rows.append({
            "market": "BTC-EUR", "interval": "4h", "start_ts": t,
            "end_ts": t + timedelta(hours=4), "open": open_price,
            "high": max(open_price, close) + 0.15, "low": min(open_price, close) - 0.15,
            "close": close, "volume": volume, "is_final": True,
        })
    return pd.DataFrame(rows)


def _set_last(df: pd.DataFrame, *, open_price: float, high: float, low: float, close: float, volume: float) -> pd.DataFrame:
    out = df.copy()
    idx = out.index[-1]
    out.loc[idx, ["open", "high", "low", "close", "volume"]] = [open_price, high, low, close, volume]
    return out


def _mirror(df: pd.DataFrame, pivot: float = 250.0) -> pd.DataFrame:
    out = df.copy()
    old_open = out["open"].copy()
    old_high = out["high"].copy()
    old_low = out["low"].copy()
    old_close = out["close"].copy()
    out["open"] = pivot - old_open
    out["high"] = pivot - old_low
    out["low"] = pivot - old_high
    out["close"] = pivot - old_close
    return out


def _row(df: pd.DataFrame):
    return build_exhaustion_candidate(df, asof_ts_utc=df.iloc[-1]["end_ts"]).iloc[0]


def test_healthy_bullish_continuation_has_low_buyer_exhaustion() -> None:
    df = _base(direction=1)
    prev = float(df.iloc[-2]["close"])
    df = _set_last(df, open_price=prev + 0.1, high=prev + 1.3, low=prev, close=prev + 1.15, volume=1700)
    row = _row(df)
    assert row["buyer_exhaustion_score"] < 45.0


def test_buyer_exhaustion_high_effort_poor_progress_upper_rejection() -> None:
    df = _base(direction=1)
    prev = float(df.iloc[-2]["close"])
    df = _set_last(df, open_price=prev + 0.05, high=prev + 1.4, low=prev - 0.15, close=prev + 0.08, volume=5000)
    row = _row(df)
    assert row["buyer_exhaustion_score"] >= 70.0
    assert row["buyer_exhaustion_state"] == STATE_CONFIRMED
    assert "BUYER_HIGH_PARTICIPATION_PROXY" in row["buyer_reason_codes"]


def test_healthy_bearish_continuation_has_low_seller_exhaustion() -> None:
    df = _base(direction=-1)
    prev = float(df.iloc[-2]["close"])
    df = _set_last(df, open_price=prev - 0.1, high=prev, low=prev - 1.3, close=prev - 1.15, volume=1700)
    row = _row(df)
    assert row["seller_exhaustion_score"] < 45.0


def test_seller_exhaustion_mirror_case_is_elevated() -> None:
    bull = _base(direction=1)
    prev = float(bull.iloc[-2]["close"])
    bull = _set_last(bull, open_price=prev + 0.05, high=prev + 1.4, low=prev - 0.15, close=prev + 0.08, volume=5000)
    row = _row(_mirror(bull))
    assert row["seller_exhaustion_score"] >= 70.0
    assert row["seller_exhaustion_state"] == STATE_CONFIRMED


def test_high_volume_no_progress_creates_absorption_proxy() -> None:
    df = _base(direction=1)
    prev = float(df.iloc[-2]["close"])
    df = _set_last(df, open_price=prev, high=prev + 0.7, low=prev - 0.7, close=prev + 0.01, volume=6000)
    row = _row(df)
    assert row["absorption_score_proxy"] >= 70.0


def test_low_volume_weak_progress_does_not_become_high_exhaustion() -> None:
    df = _base(direction=1)
    prev = float(df.iloc[-2]["close"])
    df = _set_last(df, open_price=prev, high=prev + 0.7, low=prev - 0.2, close=prev + 0.02, volume=250)
    row = _row(df)
    assert row["buyer_exhaustion_score"] < 20.0
    assert row["seller_exhaustion_score"] < 20.0


def test_insufficient_warmup_fails_closed() -> None:
    df = _base(count=10)
    row = _row(df)
    assert row["exhaustion_state"] == STATE_INSUFFICIENT
    assert row["reason_codes"] == ("INSUFFICIENT_WARMUP",)


def test_future_rows_cannot_change_point_in_time_candidate() -> None:
    df = _base(direction=1)
    asof = df.iloc[-1]["end_ts"]
    baseline = build_exhaustion_candidate(df, asof_ts_utc=asof)
    future = _base(count=2, direction=-1)
    future["market"] = "ETH-EUR"
    future["interval"] = "1d"
    future["start_ts"] = pd.Timestamp(asof) + pd.Timedelta(days=1)
    future["end_ts"] = pd.Timestamp(asof) + pd.Timedelta(days=2)
    future[["open", "high", "low", "close", "volume"]] = [9999.0, 12000.0, 1.0, 5000.0, 9_999_999.0]
    actual = build_exhaustion_candidate(pd.concat([df, future], ignore_index=True), asof_ts_utc=asof)
    pd.testing.assert_frame_equal(baseline, actual)


def test_mirror_symmetry_swaps_buyer_and_seller_scores_and_geometry() -> None:
    df = _base(direction=1)
    prev = float(df.iloc[-2]["close"])
    df = _set_last(df, open_price=prev + 0.05, high=prev + 1.4, low=prev - 0.15, close=prev + 0.08, volume=5000)
    original = _row(df)
    mirrored = _row(_mirror(df))
    assert mirrored["seller_exhaustion_score"] == pytest.approx(original["buyer_exhaustion_score"], abs=1e-9)
    assert mirrored["buyer_exhaustion_score"] == pytest.approx(original["seller_exhaustion_score"], abs=1e-9)
    assert mirrored["lower_wick_fraction"] == pytest.approx(original["upper_wick_fraction"], abs=1e-9)
    assert mirrored["close_position"] == pytest.approx(1.0 - original["close_position"], abs=1e-9)


def test_rejects_multiple_markets_inside_asof_window() -> None:
    df = pd.concat([_base(), _base().assign(market="ETH-EUR")], ignore_index=True)
    with pytest.raises(ExhaustionCandidateInputError, match="exactly one market"):
        build_exhaustion_candidate(df, asof_ts_utc=df["end_ts"].max())


def test_rejects_unsupported_interval() -> None:
    df = _base().assign(interval="2h")
    with pytest.raises(ExhaustionCandidateInputError, match="unsupported interval"):
        build_exhaustion_candidate(df, asof_ts_utc=df["end_ts"].max())


def test_prepended_history_beyond_required_warmup_does_not_change_candidate() -> None:
    df = _base(count=60, direction=1)
    prev = float(df.iloc[-2]["close"])
    df = _set_last(df, open_price=prev+0.05, high=prev+1.4, low=prev-0.15, close=prev+0.08, volume=5000)
    asof = df.iloc[-1]["end_ts"]
    full = build_exhaustion_candidate(df, asof_ts_utc=asof)
    tail = build_exhaustion_candidate(df.tail(20).reset_index(drop=True), asof_ts_utc=asof)
    pd.testing.assert_frame_equal(full, tail)
