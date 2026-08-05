from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from src.features.etl_candle_feat import filter_write_window


CLOSED_CANDLE_TS = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
INTERVAL = timedelta(hours=4)


def _candles(*timestamps: datetime) -> pd.DataFrame:
    return pd.DataFrame({"close_ts_utc": list(timestamps), "value": range(len(timestamps))})


def test_just_closed_candle_is_included_with_exclusive_end_one_interval_past_it() -> None:
    """Regression for the causal-audit root cause: the just-closed candle
    (the one the freshness gate already confirmed exists at exactly
    CLOSED_CANDLE_TS) must appear in the write window when the caller
    correctly passes write_end_ts_utc = CLOSED_CANDLE_TS + one interval, per
    the documented half-open [start, end) contract
    (docs/todo/replay_parameter_study_harness_v1.md)."""
    df = _candles(CLOSED_CANDLE_TS - INTERVAL, CLOSED_CANDLE_TS)
    out = filter_write_window(
        df,
        write_start_ts_utc=None,
        write_end_ts_utc=CLOSED_CANDLE_TS + INTERVAL,
    )
    assert list(out["close_ts_utc"]) == [CLOSED_CANDLE_TS - INTERVAL, CLOSED_CANDLE_TS]


def test_just_closed_candle_is_silently_excluded_by_the_pre_fix_boundary() -> None:
    """The exact defect PR #190 misdiagnosed: passing the closed candle's own
    identity timestamp directly as write_end_ts_utc (instead of one interval
    past it) excludes that candle from every asset's feat_candle write,
    leaving the newest row exactly one candle stale."""
    df = _candles(CLOSED_CANDLE_TS - INTERVAL, CLOSED_CANDLE_TS)
    out = filter_write_window(
        df,
        write_start_ts_utc=None,
        write_end_ts_utc=CLOSED_CANDLE_TS,
    )
    assert list(out["close_ts_utc"]) == [CLOSED_CANDLE_TS - INTERVAL]


def test_no_candle_after_the_intended_boundary_is_included() -> None:
    """A candle newer than the just-closed one (e.g. a not-yet-fully-settled
    or future-dated row) must never enter the write window even with the
    corrected exclusive bound."""
    future_candle = CLOSED_CANDLE_TS + INTERVAL
    df = _candles(CLOSED_CANDLE_TS, future_candle)
    out = filter_write_window(
        df,
        write_start_ts_utc=None,
        write_end_ts_utc=CLOSED_CANDLE_TS + INTERVAL,
    )
    assert list(out["close_ts_utc"]) == [CLOSED_CANDLE_TS]
