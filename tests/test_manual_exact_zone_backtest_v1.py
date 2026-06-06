"""
Tests for run_manual_exact_zone_backtest_v1.

All tests use synthetic candles — no DB access required.

Coverage:
- Entry hit / no entry
- Target hit / no target
- No same-candle entry+exit
- Final-close valuation when target not hit
- MAE / MFE calculation
- buy-and-hold return and improvement
- Summary output keys
- Output file writing
- parse_ts helper
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research.run_manual_exact_zone_backtest_v1 import (
    BacktestResult,
    Candle,
    build_summary,
    parse_ts,
    simulate_exact_zone,
    write_outputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(offset_minutes: int, base: datetime | None = None) -> datetime:
    b = base or datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)
    return b + timedelta(minutes=offset_minutes)


def _candle(
    offset_min: int,
    high: str,
    low: str,
    close: str,
    open_: str | None = None,
    base: datetime | None = None,
) -> Candle:
    ts = _ts(offset_min, base)
    o = Decimal(open_) if open_ else (Decimal(high) + Decimal(low)) / Decimal("2")
    return Candle(
        open_ts_utc=ts,
        open_price=o,
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


PREDICTION_TS = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)
BUY = Decimal("2.00")
TARGET = Decimal("2.12")
CAPITAL = Decimal("100.00")


# ---------------------------------------------------------------------------
# parse_ts
# ---------------------------------------------------------------------------

def test_parse_ts_z_suffix() -> None:
    dt = parse_ts("2026-05-21T00:00:00Z")
    assert dt == datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)


def test_parse_ts_offset() -> None:
    dt = parse_ts("2026-05-21T00:00:00+00:00")
    assert dt.tzinfo is not None


def test_parse_ts_naive_gets_utc() -> None:
    dt = parse_ts("2026-05-21T00:00:00")
    assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# No entry — buy level never touched
# ---------------------------------------------------------------------------

def test_no_entry_when_low_never_reaches_buy_level() -> None:
    candles = [
        _candle(15, high="2.10", low="2.05", close="2.08"),
        _candle(30, high="2.11", low="2.06", close="2.09"),
        _candle(45, high="2.09", low="2.03", close="2.05"),
    ]
    result, events = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    assert result.entry_hit is False
    assert result.target_hit is False
    assert result.entry_ts is None
    assert result.exit_price is None
    assert any(e["event"] == "NO_ENTRY" for e in events)


def test_no_entry_empty_candle_list() -> None:
    result, events = simulate_exact_zone([], PREDICTION_TS, BUY, TARGET, CAPITAL)
    assert result.entry_hit is False
    assert result.candles_fetched == 0


# ---------------------------------------------------------------------------
# Entry hit, target hit
# ---------------------------------------------------------------------------

def test_entry_and_target_hit() -> None:
    candles = [
        _candle(15, high="2.05", low="1.98", close="2.01"),   # entry: low=1.98 <= 2.00
        _candle(30, high="2.15", low="2.00", close="2.13"),   # target: high=2.15 >= 2.12
    ]
    result, events = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.entry_hit is True
    assert result.entry_price == BUY
    assert result.target_hit is True
    assert result.exit_price == TARGET

    # gross return = (2.12 - 2.00) / 2.00 * 100 = 6.0%
    assert result.gross_return_pct == pytest.approx(Decimal("6.0"), abs=Decimal("0.001"))
    assert result.pnl_eur == pytest.approx(Decimal("6.0"), abs=Decimal("0.001"))
    assert result.final_value_eur == pytest.approx(Decimal("106.0"), abs=Decimal("0.001"))

    assert result.time_to_target_hours is not None
    assert result.time_to_target_hours == pytest.approx(Decimal("0.25"), abs=Decimal("0.01"))


def test_entry_exact_at_buy_level() -> None:
    # low == buy_level exactly → entry
    candles = [
        _candle(15, high="2.05", low="2.00", close="2.02"),
        _candle(30, high="2.12", low="1.99", close="2.10"),
    ]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    assert result.entry_hit is True


# ---------------------------------------------------------------------------
# No same-candle entry and exit
# ---------------------------------------------------------------------------

def test_no_same_candle_entry_and_exit() -> None:
    # First eligible candle: low <= 2.00 AND high >= 2.12 → entry yes, but exit NOT on same candle
    candles = [
        _candle(15, high="2.20", low="1.95", close="2.10"),   # entry candle — big range
        _candle(30, high="2.00", low="1.98", close="1.99"),   # high < 2.12 → no exit
        _candle(45, high="2.13", low="2.01", close="2.12"),   # exit here
    ]
    result, events = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.entry_hit is True
    assert result.entry_ts == _ts(15)
    assert result.target_hit is True
    assert result.target_ts == _ts(45)  # must be strictly after entry candle


def test_entry_candle_high_above_target_does_not_trigger_exit() -> None:
    # Entry candle has high > target — exit must NOT fire on same candle
    candles = [
        _candle(15, high="2.50", low="1.80", close="2.10"),   # entry + would-be exit (same candle)
        _candle(30, high="2.05", low="2.01", close="2.03"),   # high < 2.12
        # no exit candle → valued at close of last
    ]
    result, events = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.entry_hit is True
    assert result.target_hit is False
    # exit valued at close of last eligible candle (c30 close = 2.03)
    assert result.exit_price == Decimal("2.03")


# ---------------------------------------------------------------------------
# Target never hit — valued at final close
# ---------------------------------------------------------------------------

def test_target_never_hit_valued_at_final_close() -> None:
    candles = [
        _candle(15, high="2.05", low="1.98", close="2.01"),   # entry
        _candle(30, high="2.10", low="2.00", close="2.08"),   # miss
        _candle(45, high="2.11", low="2.02", close="2.05"),   # miss — final
    ]
    result, events = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.entry_hit is True
    assert result.target_hit is False
    assert result.exit_price == Decimal("2.05")  # final candle close
    assert result.time_to_target_hours is None
    assert any(e["event"] == "EXIT" and e["reason"] == "HORIZON_END_VALUED_AT_CLOSE"
               for e in events)


# ---------------------------------------------------------------------------
# Candles before prediction_ts are excluded
# ---------------------------------------------------------------------------

def test_candles_before_prediction_ts_excluded() -> None:
    pre = _candle(-15, high="2.05", low="1.90", close="2.00")  # before prediction_ts
    post = _candle(15, high="2.05", low="2.02", close="2.04")  # after, no entry
    candles = [pre, post]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    # pre candle (low=1.90 <= 2.00) must not trigger entry
    assert result.entry_hit is False


# ---------------------------------------------------------------------------
# MAE / MFE
# ---------------------------------------------------------------------------

def test_mae_mfe_with_entry_and_exit() -> None:
    # entry at BUY=2.00
    # entry candle: low=1.95, high=2.10
    # post-entry: low=1.92 (worst), high=2.15 (best, also triggers exit)
    candles = [
        _candle(15, high="2.10", low="1.95", close="2.05"),   # entry
        _candle(30, high="2.15", low="1.92", close="2.13"),   # exit + worst low
    ]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.entry_hit is True
    assert result.target_hit is True

    # MAE: worst low = 1.92, (1.92 - 2.00) / 2.00 * 100 = -4.0%
    assert result.maximum_adverse_excursion_pct == pytest.approx(
        Decimal("-4.0"), abs=Decimal("0.001")
    )
    # MFE: best high = 2.15, (2.15 - 2.00) / 2.00 * 100 = 7.5%
    assert result.maximum_favorable_excursion_pct == pytest.approx(
        Decimal("7.5"), abs=Decimal("0.001")
    )


def test_mae_mfe_no_exit() -> None:
    candles = [
        _candle(15, high="2.05", low="1.95", close="2.02"),   # entry
        _candle(30, high="2.08", low="1.90", close="1.95"),   # post-entry only
    ]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.entry_hit is True
    assert result.target_hit is False
    # worst low across [entry + post] = 1.90
    assert result.maximum_adverse_excursion_pct == pytest.approx(
        Decimal("-5.0"), abs=Decimal("0.001")
    )
    # best high = 2.08
    assert result.maximum_favorable_excursion_pct == pytest.approx(
        Decimal("4.0"), abs=Decimal("0.001")
    )


# ---------------------------------------------------------------------------
# Buy-and-hold return and improvement
# ---------------------------------------------------------------------------

def test_buy_and_hold_and_improvement() -> None:
    candles = [
        _candle(15, high="2.05", low="1.98", close="2.01"),   # entry
        _candle(30, high="2.12", low="2.00", close="2.11"),   # target hit (exit @ 2.12)
        _candle(45, high="2.18", low="2.10", close="2.14"),   # after exit — window not done
    ]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.target_hit is True
    # B&H: (2.14 - 2.00) / 2.00 * 100 = 7.0%
    assert result.buy_and_hold_return_from_entry_to_end == pytest.approx(
        Decimal("7.0"), abs=Decimal("0.001")
    )
    # gross = 6.0%, improvement = 6.0 - 7.0 = -1.0 (exit was early vs B&H)
    assert result.improvement_vs_buy_and_hold == pytest.approx(
        Decimal("-1.0"), abs=Decimal("0.001")
    )


def test_improvement_vs_bah_positive_when_target_beats_bah() -> None:
    candles = [
        _candle(15, high="2.05", low="1.98", close="2.01"),   # entry
        _candle(30, high="2.15", low="2.00", close="2.13"),   # target hit @ 2.12
        _candle(45, high="2.05", low="1.90", close="1.95"),   # after exit — price dropped
    ]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert result.target_hit is True
    # B&H final close = 1.95, return = (1.95-2.00)/2.00*100 = -2.5%
    assert result.buy_and_hold_return_from_entry_to_end == pytest.approx(
        Decimal("-2.5"), abs=Decimal("0.001")
    )
    # gross = 6.0%, improvement = 6.0 - (-2.5) = 8.5
    assert result.improvement_vs_buy_and_hold == pytest.approx(
        Decimal("8.5"), abs=Decimal("0.001")
    )


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

def _make_full_result() -> tuple[BacktestResult, list[Candle]]:
    candles = [
        _candle(15, high="2.05", low="1.98", close="2.01"),
        _candle(30, high="2.15", low="2.00", close="2.13"),
    ]
    result, events = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    result.symbol = "NEAR"
    result.quote = "EUR"
    result.venue = "bitvavo"
    result.interval_code = "15m"
    result.horizon_days = 14
    result.buy_level = BUY
    result.sell_target = TARGET
    result.starting_capital = CAPITAL
    result.prediction_ts = PREDICTION_TS
    result.prediction_timestamp_status = "ASSUMED"
    result.window_start_ts = PREDICTION_TS
    result.window_end_ts = PREDICTION_TS + timedelta(days=14)
    return result, candles


def test_write_outputs_creates_files() -> None:
    result, candles = _make_full_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_outputs(result, candles, Path(tmpdir), write_chart=False)
        assert "summary" in written
        assert "events" in written
        assert written["summary"].exists()
        assert written["events"].exists()


def test_summary_json_has_required_keys() -> None:
    result, candles = _make_full_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_outputs(result, candles, Path(tmpdir), write_chart=False)
        data = json.loads(written["summary"].read_text())

    required_keys = [
        "runner", "symbol", "quote", "venue", "interval_code",
        "buy_level", "sell_target", "prediction_ts", "prediction_timestamp_status",
        "entry_hit", "entry_ts", "entry_price",
        "target_hit", "target_ts", "exit_price",
        "gross_return_pct", "pnl_eur", "time_to_target_hours",
        "maximum_adverse_excursion_pct", "maximum_favorable_excursion_pct",
        "final_value_eur", "buy_and_hold_return_from_entry_to_end",
        "improvement_vs_buy_and_hold", "context",
    ]
    for key in required_keys:
        assert key in data, f"Missing key: {key}"


def test_summary_context_block_has_required_keys() -> None:
    result, candles = _make_full_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_outputs(result, candles, Path(tmpdir), write_chart=False)
        data = json.loads(written["summary"].read_text())

    ctx = data["context"]
    for key in [
        "market_regime", "symbol_regime", "breath_phase",
        "breath_alignment", "context_quality_tier",
    ]:
        assert key in ctx, f"Missing context key: {key}"


def test_event_rows_jsonl_parseable() -> None:
    result, candles = _make_full_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_outputs(result, candles, Path(tmpdir), write_chart=False)
        lines = written["events"].read_text().strip().split("\n")
        assert len(lines) > 0
        for line in lines:
            json.loads(line)


def test_event_rows_contain_entry_and_exit() -> None:
    result, candles = _make_full_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_outputs(result, candles, Path(tmpdir), write_chart=False)
        events = [json.loads(l) for l in written["events"].read_text().strip().split("\n")]

    event_types = {e["event"] for e in events}
    assert "ENTRY_HIT" in event_types
    assert "TARGET_HIT" in event_types
    assert "EXIT" in event_types


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------

def test_build_summary_prediction_status_preserved() -> None:
    result, _ = _make_full_result()
    result.prediction_timestamp_status = "ASSUMED"
    summary = build_summary(result)
    assert summary["prediction_timestamp_status"] == "ASSUMED"


def test_build_summary_no_entry_fields_are_none() -> None:
    candles = [_candle(15, high="2.10", low="2.05", close="2.08")]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    result.symbol = "NEAR"
    result.quote = "EUR"
    result.venue = "bitvavo"
    result.interval_code = "15m"
    result.horizon_days = 14
    result.buy_level = BUY
    result.sell_target = TARGET
    result.starting_capital = CAPITAL
    result.prediction_ts = PREDICTION_TS
    result.prediction_timestamp_status = "ASSUMED"
    result.window_start_ts = PREDICTION_TS
    result.window_end_ts = PREDICTION_TS + timedelta(days=14)

    summary = build_summary(result)
    assert summary["entry_hit"] is False
    assert summary["entry_ts"] is None
    assert summary["entry_price"] is None
    assert summary["target_hit"] is False


# ---------------------------------------------------------------------------
# Determinism check
# ---------------------------------------------------------------------------

def test_simulation_is_deterministic() -> None:
    candles = [
        _candle(15, high="2.05", low="1.98", close="2.01"),
        _candle(30, high="2.15", low="2.00", close="2.13"),
        _candle(45, high="2.20", low="2.10", close="2.18"),
    ]
    r1, e1 = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    r2, e2 = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)

    assert r1.entry_hit == r2.entry_hit
    assert r1.target_hit == r2.target_hit
    assert r1.gross_return_pct == r2.gross_return_pct
    assert r1.entry_ts == r2.entry_ts
    assert r1.target_ts == r2.target_ts
    assert len(e1) == len(e2)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_single_eligible_candle_no_exit_valued_at_close() -> None:
    candles = [_candle(15, high="2.08", low="1.99", close="2.05")]
    result, _ = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    assert result.entry_hit is True
    assert result.target_hit is False
    assert result.exit_price == Decimal("2.05")


def test_multiple_misses_before_entry() -> None:
    candles = [
        _candle(15, high="2.10", low="2.05", close="2.08"),  # miss
        _candle(30, high="2.09", low="2.04", close="2.06"),  # miss
        _candle(45, high="2.07", low="1.99", close="2.03"),  # entry
        _candle(60, high="2.13", low="2.02", close="2.12"),  # exit
    ]
    result, events = simulate_exact_zone(candles, PREDICTION_TS, BUY, TARGET, CAPITAL)
    assert result.entry_hit is True
    assert result.entry_ts == _ts(45)
    assert result.target_hit is True
    assert result.target_ts == _ts(60)

    miss_events = [e for e in events if e["event"] == "ENTRY_MISS"]
    assert len(miss_events) == 2
