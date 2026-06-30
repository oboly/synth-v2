from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.market_context.breathline_lattice_matcher_v2 import (
    CYCLE_DAYS,
    BASE_MARKERS,
    Candle,
    SELECTION_STATUS_TIED,
    SENSITIVITY_TOLERANCE_HOURS,
    attach_extension_evidence,
    calculate_candle_residual_hours,
    evaluate_shift_candidate,
    expected_marker_ts,
    select_best_shift,
)


def _day_start(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _candle(
    symbol: str,
    ts: datetime,
    *,
    open_price: float = 100.0,
    high_price: float = 101.0,
    low_price: float = 99.0,
    close_price: float = 100.0,
) -> Candle:
    return Candle(
        symbol=symbol,
        open_ts_utc=ts,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
    )


def _build_cycle_candles(symbol: str, anchor: datetime, shift_days: float) -> list[Candle]:
    start = _day_start(anchor - timedelta(days=2))
    candles = {
        start + timedelta(days=index): _candle(symbol, start + timedelta(days=index))
        for index in range(40)
    }
    marker_shapes = {
        "FIRST_LIFT_HIGH": {"high_price": 110.0, "low_price": 100.0, "close_price": 105.0},
        "FIRST_DIP_LOW": {"high_price": 99.0, "low_price": 90.0, "close_price": 94.0},
        "SECOND_PEAK_RETEST_HIGH": {"high_price": 108.0, "low_price": 99.0, "close_price": 104.0},
        "SECOND_DIP_HIGHER_LOW": {"high_price": 100.0, "low_price": 95.0, "close_price": 97.0},
        "IGNITION_PRE_SPIKE": {"high_price": 112.0, "low_price": 100.0, "close_price": 108.0},
        "MAIN_PULSE_TP_HIGH": {"high_price": 130.0, "low_price": 109.0, "close_price": 125.0},
    }
    for marker in BASE_MARKERS:
        ts = _day_start(expected_marker_ts(anchor, shift_days, CYCLE_DAYS, marker.ratio))
        candles[ts] = _candle(symbol, ts, **marker_shapes[marker.code])
    return sorted(candles.values(), key=lambda row: row.open_ts_utc)


def _build_uniform_candles(symbol: str, anchor: datetime, days: int) -> list[Candle]:
    start = _day_start(anchor - timedelta(days=1))
    return [
        _candle(symbol, start + timedelta(days=index), high_price=110.0, low_price=90.0, close_price=100.0)
        for index in range(days)
    ]


def test_daily_candle_interval_residual_is_zero_when_expected_time_falls_inside_candle() -> None:
    candle = _candle("BTC", datetime(2025, 1, 6, 0, 0, tzinfo=UTC))
    expected = datetime(2025, 1, 6, 14, 0, tzinfo=UTC)
    assert calculate_candle_residual_hours(expected, candle, "1d") == 0.0


def test_marker_sequence_cannot_reuse_one_candle() -> None:
    anchor = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    candles = [
        _candle("BTC", datetime(2025, 1, 10, 0, 0, tzinfo=UTC), high_price=125.0, low_price=80.0, close_price=100.0),
    ]
    candidate = evaluate_shift_candidate(
        candles=candles,
        symbol="BTC",
        raw_lattice_anchor_ts_utc=anchor,
        sensitivity_mode="STRICT",
        template_time_shift_days=0.0,
        tolerance_hours=400.0,
    )
    assert candidate.matched_base_marker_count == 1


def test_marker_sequence_is_strictly_chronological() -> None:
    anchor = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    candidate = evaluate_shift_candidate(
        candles=_build_cycle_candles("BTC", anchor, 0.0),
        symbol="BTC",
        raw_lattice_anchor_ts_utc=anchor,
        sensitivity_mode="STRICT",
        template_time_shift_days=0.0,
    )
    observed = [
        row.observed_candle_open_ts_utc
        for row in candidate.base_marker_evidence
        if row.matched and row.observed_candle_open_ts_utc is not None
    ]
    assert observed == sorted(observed)
    assert len(observed) == len(set(observed))


def test_extensions_do_not_change_base_shift_ranking() -> None:
    anchor = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    candles = _build_uniform_candles("BTC", anchor, days=28)
    shift_zero = attach_extension_evidence(
        evaluate_shift_candidate(candles, "BTC", anchor, "STRICT", 0.0),
        candles,
    )
    shift_one = attach_extension_evidence(
        evaluate_shift_candidate(candles, "BTC", anchor, "STRICT", 1.0),
        candles,
    )
    assert shift_zero.ranking_key == shift_one.ranking_key
    assert sum(1 for row in shift_zero.extension_marker_evidence if row.matched) != sum(
        1 for row in shift_one.extension_marker_evidence if row.matched
    )
    summary = select_best_shift(
        candles=candles,
        symbol="BTC",
        raw_lattice_anchor_ts_utc=anchor,
        sensitivity_mode="STRICT",
        shift_grid_days=(0.0, 1.0),
    )
    assert summary.selection_status == SELECTION_STATUS_TIED


def test_tied_best_candidates_remain_tied_and_produce_no_selected_shift() -> None:
    anchor = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    candles = _build_uniform_candles("BTC", anchor, days=28)
    summary = select_best_shift(
        candles=candles,
        symbol="BTC",
        raw_lattice_anchor_ts_utc=anchor,
        sensitivity_mode="STRICT",
        shift_grid_days=(0.0, 1.0),
    )
    assert summary.selection_status == SELECTION_STATUS_TIED
    assert summary.selected_template_time_shift_days is None
    assert summary.tied_shift_days == (0.0, 1.0)


def test_sensitivity_modes_use_exact_required_hours() -> None:
    assert SENSITIVITY_TOLERANCE_HOURS == {
        "STRICT": 12.0,
        "NORMAL": 18.0,
        "MAX": 24.0,
    }
