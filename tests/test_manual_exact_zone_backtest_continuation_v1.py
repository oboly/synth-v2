"""
Tests for continuation-gate variant simulation in run_manual_exact_zone_backtest_v1.

No DB access. ContextTimeline supplied directly via _empty_context_timeline()
or manually constructed rows.

Coverage:
- _latest_before: empty, single row, multiple rows, ts exactly on boundary
- ContextTimeline.at(): all unknown when empty, fields populated when rows present
- evaluate_continuation_gate: CONTEXT_UNKNOWN / REGIME_CONFLICT / BREATH_CONFLICT /
  CONTINUATION_SUPPORTED / CONTINUATION_WEAK
- evaluate_continuation_gate overshoot and close_vs_target fields
- simulate_continuation_variant: BASELINE, BREATH_HOLD, REGIME_SHIFT,
  TRAILING_RUNNER, PARENT_CONTEXT
- CONTEXT_UNKNOWN fallback: BASELINE/BREATH_HOLD/REGIME_SHIFT/TRAILING_RUNNER
  all match baseline C behavior when context empty
- C5 PARENT_CONTEXT live_valid=False when parent_tf_status=UNKNOWN
- run_all_continuation_variants: one result per spec, deterministic
- NEAR_CONTINUATION_VARIANTS: 5 variants, all construct without error
- write_continuation_outputs: creates required files
- print_continuation_comparison_table: runs without error
"""

from __future__ import annotations

import csv
import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from src.account.long_reserve_policy_v1 import (
    RESERVE_SOURCE_ASSET_OVERRIDE,
    TP_SCOPE_CHILD_SHORT_SWING,
)
from src.research.run_manual_exact_zone_backtest_v1 import (
    GATE_BREATH_CONFLICT,
    GATE_CONTEXT_UNKNOWN,
    GATE_CONTINUATION_SUPPORTED,
    GATE_CONTINUATION_WEAK,
    GATE_NOT_LIVE_VALID,
    GATE_REGIME_CONFLICT,
    NEAR_CONTINUATION_VARIANTS,
    VARIANT_TYPE_BASELINE,
    VARIANT_TYPE_BREATH_HOLD,
    VARIANT_TYPE_PARENT_CONTEXT,
    VARIANT_TYPE_REGIME_SHIFT,
    VARIANT_TYPE_TRAILING_RUNNER,
    Candle,
    ContextTimeline,
    SellTranche,
    VariantSpec,
    _empty_context_timeline,
    _latest_before,
    evaluate_continuation_gate,
    print_continuation_comparison_table,
    run_all_continuation_variants,
    simulate_continuation_variant,
    write_continuation_outputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PREDICTION_TS = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)
BUY = Decimal("2.00")
CAPITAL = Decimal("100.00")
_H = Decimal("100")
_Z = Decimal("0")


def _ts(offset_min: int) -> datetime:
    return PREDICTION_TS + timedelta(minutes=offset_min)


def _candle(
    offset_min: int,
    high: str,
    low: str,
    close: str,
    open_: Optional[str] = None,
) -> Candle:
    ts = _ts(offset_min)
    o = Decimal(open_) if open_ else (Decimal(high) + Decimal(low)) / Decimal("2")
    return Candle(
        open_ts_utc=ts,
        open_price=o,
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def _baseline_candles() -> list[Candle]:
    """Entry at offset 15, T1@2.12 at 30, T2@2.25 at 45, T3@2.35 at 60, final close 2.43."""
    return [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.14"),
        _candle(45, "2.28", "2.12", "2.25"),
        _candle(60, "2.40", "2.25", "2.38"),
        _candle(75, "2.45", "2.35", "2.43"),
    ]


def _spec(
    variant_id: str = "TEST",
    label: str = "TEST",
    tranches: Optional[list[SellTranche]] = None,
    parent_tf_status: str = "N/A",
    variant_type: str = VARIANT_TYPE_BASELINE,
) -> VariantSpec:
    return VariantSpec(
        variant_id=variant_id,
        label=label,
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=tranches or [
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
        parent_tf_target_status=parent_tf_status,
        variant_type=variant_type,
    )


def _ctx_row(ts: datetime, **kwargs) -> dict:
    return {"asof_ts_utc": ts, **kwargs}


def _breath_row(ts: datetime, **kwargs) -> dict:
    return {"observed_at_utc": ts, **kwargs}


# ---------------------------------------------------------------------------
# _latest_before
# ---------------------------------------------------------------------------

def test_latest_before_empty_returns_none() -> None:
    assert _latest_before([], _ts(30), "asof_ts_utc") is None


def test_latest_before_single_row_before_ts() -> None:
    rows = [_ctx_row(_ts(10), market_regime="BULL")]
    result = _latest_before(rows, _ts(30), "asof_ts_utc")
    assert result is not None
    assert result["market_regime"] == "BULL"


def test_latest_before_single_row_after_ts_returns_none() -> None:
    rows = [_ctx_row(_ts(60), market_regime="BULL")]
    result = _latest_before(rows, _ts(30), "asof_ts_utc")
    assert result is None


def test_latest_before_exact_boundary() -> None:
    rows = [_ctx_row(_ts(30), market_regime="BULL")]
    result = _latest_before(rows, _ts(30), "asof_ts_utc")
    assert result is not None


def test_latest_before_returns_latest_not_first() -> None:
    rows = [
        _ctx_row(_ts(10), market_regime="BEAR"),
        _ctx_row(_ts(20), market_regime="BULL"),
        _ctx_row(_ts(60), market_regime="NEUTRAL"),
    ]
    result = _latest_before(rows, _ts(30), "asof_ts_utc")
    assert result is not None
    assert result["market_regime"] == "BULL"


# ---------------------------------------------------------------------------
# ContextTimeline.at()
# ---------------------------------------------------------------------------

def test_empty_timeline_returns_all_unknown() -> None:
    tl = _empty_context_timeline()
    ctx = tl.at(_ts(30))
    assert ctx["market_regime"] == "UNKNOWN"
    assert ctx["breath_phase"] == "UNKNOWN"
    assert ctx["symbol_regime"] == "UNKNOWN"


def test_timeline_market_regime_populated() -> None:
    tl = ContextTimeline(
        market_regime_rows=[_ctx_row(_ts(10), market_regime="BULL")],
        breath_rows=[],
        selection_rows=[],
    )
    ctx = tl.at(_ts(30))
    assert ctx["market_regime"] == "BULL"


def test_timeline_breath_phase_from_paper_advice() -> None:
    tl = ContextTimeline(
        market_regime_rows=[],
        breath_rows=[_breath_row(_ts(10), breath_phase="EXPANSION", breath_alignment="POSITIVE")],
        selection_rows=[],
    )
    ctx = tl.at(_ts(30))
    assert ctx["breath_phase"] == "EXPANSION"
    assert ctx["breath_alignment"] == "POSITIVE"


def test_timeline_selection_state_fills_symbol_regime() -> None:
    tl = ContextTimeline(
        market_regime_rows=[],
        breath_rows=[],
        selection_rows=[_ctx_row(_ts(10), symbol_regime="UPTREND")],
    )
    ctx = tl.at(_ts(30))
    assert ctx["symbol_regime"] == "UPTREND"


def test_timeline_paper_advice_takes_priority_over_selection() -> None:
    tl = ContextTimeline(
        market_regime_rows=[],
        breath_rows=[_breath_row(_ts(15), symbol_regime="BULLISH")],
        selection_rows=[_ctx_row(_ts(10), symbol_regime="BEAR")],
    )
    ctx = tl.at(_ts(30))
    assert ctx["symbol_regime"] == "BULLISH"


# ---------------------------------------------------------------------------
# evaluate_continuation_gate
# ---------------------------------------------------------------------------

def _empty_ctx() -> dict:
    return {
        "market_regime": "UNKNOWN",
        "symbol_regime": "UNKNOWN",
        "breath_phase": "UNKNOWN",
        "breath_alignment": "UNKNOWN",
        "context_quality_tier": "UNKNOWN",
    }


def test_gate_all_unknown_returns_context_unknown() -> None:
    result = evaluate_continuation_gate(_empty_ctx(), None, Decimal("2.12"))
    assert result.gate_state == GATE_CONTEXT_UNKNOWN
    assert "unknown" in result.gate_reason.lower()


def test_gate_negative_market_regime_returns_regime_conflict() -> None:
    ctx = {**_empty_ctx(), "market_regime": "BEAR"}
    result = evaluate_continuation_gate(ctx, None, Decimal("2.12"))
    assert result.gate_state == GATE_REGIME_CONFLICT


def test_gate_negative_symbol_regime_returns_regime_conflict() -> None:
    ctx = {**_empty_ctx(), "symbol_regime": "DOWNTREND"}
    result = evaluate_continuation_gate(ctx, None, Decimal("2.12"))
    assert result.gate_state == GATE_REGIME_CONFLICT


def test_gate_negative_breath_phase_returns_breath_conflict() -> None:
    ctx = {**_empty_ctx(), "breath_phase": "EXHAUSTION", "market_regime": "NEUTRAL"}
    result = evaluate_continuation_gate(ctx, None, Decimal("2.12"))
    assert result.gate_state == GATE_BREATH_CONFLICT


def test_gate_negative_alignment_returns_breath_conflict() -> None:
    ctx = {**_empty_ctx(), "breath_alignment": "DIVERGING", "market_regime": "NEUTRAL"}
    result = evaluate_continuation_gate(ctx, None, Decimal("2.12"))
    assert result.gate_state == GATE_BREATH_CONFLICT


def test_gate_regime_conflict_takes_priority_over_breath() -> None:
    ctx = {
        **_empty_ctx(),
        "market_regime": "BEAR",
        "breath_phase": "EXHAUSTION",
    }
    result = evaluate_continuation_gate(ctx, None, Decimal("2.12"))
    assert result.gate_state == GATE_REGIME_CONFLICT


def test_gate_continuation_supported_requires_all_positive() -> None:
    ctx = {
        "market_regime": "BULL",
        "symbol_regime": "UPTREND",
        "breath_phase": "EXPANSION",
        "breath_alignment": "POSITIVE",
        "context_quality_tier": "A",
    }
    # Need close above target: touch candle close > target
    touch = _candle(30, "2.20", "2.10", "2.15")
    result = evaluate_continuation_gate(ctx, touch, Decimal("2.12"))
    assert result.gate_state == GATE_CONTINUATION_SUPPORTED


def test_gate_continuation_weak_when_close_below_target() -> None:
    ctx = {
        "market_regime": "BULL",
        "symbol_regime": "UPTREND",
        "breath_phase": "EXPANSION",
        "breath_alignment": "POSITIVE",
        "context_quality_tier": "A",
    }
    # Close below target
    touch = _candle(30, "2.15", "2.05", "2.10")
    result = evaluate_continuation_gate(ctx, touch, Decimal("2.12"))
    assert result.gate_state == GATE_CONTINUATION_WEAK


def test_gate_overshoot_and_close_vs_target_populated() -> None:
    ctx = _empty_ctx()
    touch = _candle(30, "2.20", "2.10", "2.15")
    result = evaluate_continuation_gate(ctx, touch, Decimal("2.12"))
    assert result.overshoot_pct is not None
    # (2.20 - 2.12) / 2.12 * 100 ≈ 3.77%
    assert result.overshoot_pct == pytest.approx(
        (Decimal("2.20") - Decimal("2.12")) / Decimal("2.12") * Decimal("100"),
        abs=Decimal("0.01"),
    )
    assert result.close_vs_target_pct is not None
    # (2.15 - 2.12) / 2.12 * 100 ≈ 1.42%
    assert result.close_vs_target_pct > Decimal("0")


def test_gate_no_touch_candle_overshoot_is_none() -> None:
    result = evaluate_continuation_gate(_empty_ctx(), None, Decimal("2.12"))
    assert result.overshoot_pct is None
    assert result.close_vs_target_pct is None


# ---------------------------------------------------------------------------
# simulate_continuation_variant: BASELINE (CONTEXT_UNKNOWN fallback)
# ---------------------------------------------------------------------------

def test_baseline_context_unknown_matches_standard_c_behavior() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_BASELINE)
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec,
                                      _empty_context_timeline())
    assert r.entry_hit is True
    assert r.target_hits == ["2.12", "2.25", "2.35"]
    assert r.short_swing_sold_pct == Decimal("50")
    assert r.continuation_gate_state == GATE_CONTEXT_UNKNOWN
    assert r.live_valid is True
    assert r.sell_reduction_reason == "BASELINE_NOT_GATED"


def test_baseline_no_entry_returns_entry_hit_false() -> None:
    candles = [_candle(15, "2.10", "2.05", "2.08")]
    spec = _spec(variant_type=VARIANT_TYPE_BASELINE)
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec,
                                      _empty_context_timeline())
    assert r.entry_hit is False
    assert r.pnl_eur is None
    assert r.live_valid is True


# ---------------------------------------------------------------------------
# simulate_continuation_variant: BREATH_HOLD
# ---------------------------------------------------------------------------

def test_breath_hold_context_unknown_falls_back_to_baseline() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_BREATH_HOLD)
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec,
                                      _empty_context_timeline())
    assert r.continuation_gate_state == GATE_CONTEXT_UNKNOWN
    # Fallback: baseline sell 20/15/15 — same target_hits
    assert r.target_hits == ["2.12", "2.25", "2.35"]
    assert r.short_swing_sold_pct == Decimal("50")
    assert "BASELINE_FALLBACK" in (r.sell_reduction_reason or "")


def test_breath_hold_supported_reduces_first_tranche() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_BREATH_HOLD)
    ctx = {
        "market_regime": "BULL", "symbol_regime": "UPTREND",
        "breath_phase": "EXPANSION", "breath_alignment": "POSITIVE",
        "context_quality_tier": "A",
    }
    # T1 touch candle at offset 30 with close 2.14 > 2.12
    tl = ContextTimeline(
        market_regime_rows=[_ctx_row(_ts(10), market_regime="BULL")],
        breath_rows=[_breath_row(_ts(10), breath_phase="EXPANSION", breath_alignment="POSITIVE",
                                 symbol_regime="UPTREND", context_quality_tier="A")],
        selection_rows=[],
    )
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec, tl)
    assert r.continuation_gate_state == GATE_CONTINUATION_SUPPORTED
    # First tranche should be reduced from 20% to 10%
    assert r.short_swing_sold_pct < Decimal("50")
    assert r.live_valid is True
    assert "REDUCED_T1" in (r.sell_reduction_reason or "")


# ---------------------------------------------------------------------------
# simulate_continuation_variant: REGIME_SHIFT
# ---------------------------------------------------------------------------

def test_regime_shift_context_unknown_no_shift() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_REGIME_SHIFT)
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec,
                                      _empty_context_timeline())
    assert r.continuation_gate_state == GATE_CONTEXT_UNKNOWN
    assert r.target_hits == ["2.12", "2.25", "2.35"]
    assert "NO_SHIFT" in (r.target_shift_reason or "")


def test_regime_shift_supported_shifts_ladder_up() -> None:
    # Candles: entry at 15, T1@2.25 at 45, T2@2.35 at 60, T3@2.43 at 75 (shifted targets)
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),    # entry
        _candle(30, "2.15", "2.00", "2.14"),    # passes 2.12 but shifted ladder ignores it
        _candle(45, "2.28", "2.12", "2.25"),    # T1 shifted = 2.25 hit here
        _candle(60, "2.40", "2.25", "2.38"),    # T2 shifted = 2.35 hit here
        _candle(75, "2.50", "2.38", "2.45"),    # T3 shifted = 2.43 hit here
    ]
    spec = _spec(variant_type=VARIANT_TYPE_REGIME_SHIFT)
    tl = ContextTimeline(
        market_regime_rows=[_ctx_row(_ts(10), market_regime="BULL")],
        breath_rows=[_breath_row(_ts(10), breath_phase="EXPANSION", breath_alignment="POSITIVE",
                                 symbol_regime="UPTREND", context_quality_tier="A")],
        selection_rows=[],
    )
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec, tl)
    assert r.continuation_gate_state == GATE_CONTINUATION_SUPPORTED
    assert "LADDER_UP" in (r.target_shift_reason or "")
    # T1 shifted to 2.25, T2 to 2.35, T3 to 2.43
    assert "2.25" in r.target_hits


# ---------------------------------------------------------------------------
# simulate_continuation_variant: TRAILING_RUNNER
# ---------------------------------------------------------------------------

def test_trailing_runner_context_unknown_holds_runner() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_TRAILING_RUNNER)
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec,
                                      _empty_context_timeline())
    assert r.continuation_gate_state == GATE_CONTEXT_UNKNOWN
    assert r.target_hits == ["2.12", "2.25", "2.35"]
    assert "NO_EXIT_SIGNAL" in (r.runner_hold_reason or "")


def test_trailing_runner_regime_conflict_stops_after_first_tranche() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_TRAILING_RUNNER)
    tl = ContextTimeline(
        market_regime_rows=[_ctx_row(_ts(10), market_regime="BEAR")],
        breath_rows=[],
        selection_rows=[],
    )
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec, tl)
    assert r.continuation_gate_state == GATE_REGIME_CONFLICT
    # Only first tranche executed — runner stopped
    assert r.target_hits == ["2.12"]
    assert r.short_swing_sold_pct == Decimal("20")
    assert "EARLY_STOP" in (r.runner_hold_reason or "")


def test_trailing_runner_breath_conflict_stops_after_first_tranche() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_TRAILING_RUNNER)
    tl = ContextTimeline(
        market_regime_rows=[],
        breath_rows=[_breath_row(_ts(10), breath_phase="EXHAUSTION",
                                 breath_alignment="NEGATIVE", symbol_regime="",
                                 context_quality_tier="")],
        selection_rows=[],
    )
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec, tl)
    assert r.continuation_gate_state == GATE_BREATH_CONFLICT
    assert r.target_hits == ["2.12"]


# ---------------------------------------------------------------------------
# simulate_continuation_variant: PARENT_CONTEXT
# ---------------------------------------------------------------------------

def test_parent_context_unknown_marks_not_live_valid() -> None:
    candles = _baseline_candles()
    spec = _spec(variant_type=VARIANT_TYPE_PARENT_CONTEXT, parent_tf_status="UNKNOWN")
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec,
                                      _empty_context_timeline())
    assert r.live_valid is False
    assert r.continuation_gate_state == GATE_NOT_LIVE_VALID
    # Still simulates baseline C
    assert r.target_hits == ["2.12", "2.25", "2.35"]


def test_parent_context_no_entry_still_not_live_valid() -> None:
    candles = [_candle(15, "2.10", "2.05", "2.08")]
    spec = _spec(variant_type=VARIANT_TYPE_PARENT_CONTEXT, parent_tf_status="UNKNOWN")
    r = simulate_continuation_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec,
                                      _empty_context_timeline())
    assert r.entry_hit is False
    assert r.live_valid is False
    assert r.continuation_gate_state == GATE_NOT_LIVE_VALID


# ---------------------------------------------------------------------------
# run_all_continuation_variants
# ---------------------------------------------------------------------------

def test_run_all_continuation_variants_returns_one_per_spec() -> None:
    candles = _baseline_candles()
    results = run_all_continuation_variants(
        candles=candles,
        prediction_ts=PREDICTION_TS,
        buy_level=BUY,
        starting_capital=CAPITAL,
        variants=NEAR_CONTINUATION_VARIANTS,
        context_timeline=_empty_context_timeline(),
    )
    assert len(results) == len(NEAR_CONTINUATION_VARIANTS)


def test_run_all_continuation_variants_is_deterministic() -> None:
    candles = _baseline_candles()
    r1 = run_all_continuation_variants(
        candles, PREDICTION_TS, BUY, CAPITAL, NEAR_CONTINUATION_VARIANTS, _empty_context_timeline()
    )
    r2 = run_all_continuation_variants(
        candles, PREDICTION_TS, BUY, CAPITAL, NEAR_CONTINUATION_VARIANTS, _empty_context_timeline()
    )
    for a, b in zip(r1, r2):
        assert a.final_value_eur == b.final_value_eur
        assert a.continuation_gate_state == b.continuation_gate_state


# ---------------------------------------------------------------------------
# NEAR_CONTINUATION_VARIANTS construction
# ---------------------------------------------------------------------------

def test_near_continuation_variants_construct_without_error() -> None:
    assert len(NEAR_CONTINUATION_VARIANTS) == 5
    ids = [v.variant_id for v in NEAR_CONTINUATION_VARIANTS]
    assert "C1_BASELINE_20_15_15_RUNNER" in ids
    assert "C2_BREATH_HOLD_FIRST_TARGET" in ids
    assert "C3_REGIME_TARGET_SHIFT" in ids
    assert "C4_BREATH_TRAILING_RUNNER" in ids
    assert "C5_PARENT_CONTEXT_RUNNER" in ids


def test_near_continuation_c5_parent_status_unknown() -> None:
    c5 = next(v for v in NEAR_CONTINUATION_VARIANTS if v.variant_id == "C5_PARENT_CONTEXT_RUNNER")
    assert c5.parent_tf_target_status == "UNKNOWN"
    assert c5.variant_type == VARIANT_TYPE_PARENT_CONTEXT


def test_near_continuation_c1_baseline_type() -> None:
    c1 = next(v for v in NEAR_CONTINUATION_VARIANTS if v.variant_id == "C1_BASELINE_20_15_15_RUNNER")
    assert c1.variant_type == VARIANT_TYPE_BASELINE


def test_near_continuation_all_have_three_tranches() -> None:
    for spec in NEAR_CONTINUATION_VARIANTS:
        assert len(spec.tranches) == 3, f"{spec.variant_id} has wrong tranche count"


def test_near_continuation_all_50pct_reserve() -> None:
    for spec in NEAR_CONTINUATION_VARIANTS:
        assert spec.active_long_reserve_pct == Decimal("50"), spec.variant_id


# ---------------------------------------------------------------------------
# write_continuation_outputs
# ---------------------------------------------------------------------------

def _make_continuation_results() -> list:
    candles = _baseline_candles()
    return run_all_continuation_variants(
        candles, PREDICTION_TS, BUY, CAPITAL, NEAR_CONTINUATION_VARIANTS, _empty_context_timeline()
    )


def test_write_continuation_outputs_creates_required_files() -> None:
    results = _make_continuation_results()
    candles = _baseline_candles()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_continuation_outputs(
            continuation_results=results,
            output_dir=Path(tmpdir),
            candles=candles,
            buy_level=BUY,
            prediction_ts=PREDICTION_TS,
            write_chart=False,
        )
        assert "continuation_summary" in written
        assert "continuation_rows" in written
        assert "continuation_gate_breakdown" in written
        assert "breath_regime_breakdown" in written
        for key, path in written.items():
            assert path.exists(), f"Missing: {key}"


def test_continuation_summary_json_has_correct_count() -> None:
    results = _make_continuation_results()
    candles = _baseline_candles()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_continuation_outputs(
            results, Path(tmpdir), candles, BUY, PREDICTION_TS, write_chart=False
        )
        data = json.loads(written["continuation_summary"].read_text())
    assert "continuation_variants" in data
    assert len(data["continuation_variants"]) == 5


def test_continuation_gate_breakdown_csv_has_5_data_rows() -> None:
    results = _make_continuation_results()
    candles = _baseline_candles()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_continuation_outputs(
            results, Path(tmpdir), candles, BUY, PREDICTION_TS, write_chart=False
        )
        with written["continuation_gate_breakdown"].open() as fh:
            reader = list(csv.DictReader(fh))
    assert len(reader) == 5


def test_breath_regime_breakdown_csv_has_header_and_rows() -> None:
    results = _make_continuation_results()
    candles = _baseline_candles()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_continuation_outputs(
            results, Path(tmpdir), candles, BUY, PREDICTION_TS, write_chart=False
        )
        with written["breath_regime_breakdown"].open() as fh:
            reader = list(csv.DictReader(fh))
    assert len(reader) == 5
    for row in reader:
        assert "gate_state" in row
        assert "variant_id" in row


def test_continuation_rows_jsonl_parseable() -> None:
    results = _make_continuation_results()
    candles = _baseline_candles()
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_continuation_outputs(
            results, Path(tmpdir), candles, BUY, PREDICTION_TS, write_chart=False
        )
        lines = written["continuation_rows"].read_text().strip().split("\n")
    assert len(lines) == 5
    for line in lines:
        json.loads(line)


# ---------------------------------------------------------------------------
# print_continuation_comparison_table (smoke — must not raise)
# ---------------------------------------------------------------------------

def test_print_continuation_comparison_table_runs(capsys) -> None:
    results = _make_continuation_results()
    print_continuation_comparison_table(results)
    captured = capsys.readouterr()
    assert "CONTINUATION GATE" in captured.out
    assert "C1_BASELINE" in captured.out
    assert "C5_PARENT" in captured.out


def test_continuation_table_shows_live_valid_flags(capsys) -> None:
    results = _make_continuation_results()
    print_continuation_comparison_table(results)
    captured = capsys.readouterr()
    # C5 should show False live_valid
    assert "False" in captured.out
    # C1-C4 should show True
    assert "True" in captured.out


# ---------------------------------------------------------------------------
# Context fields preserved in gate result
# ---------------------------------------------------------------------------

def test_gate_result_preserves_all_context_fields() -> None:
    ctx = {
        "market_regime": "BULL",
        "symbol_regime": "UPTREND",
        "breath_phase": "EXPANSION",
        "breath_alignment": "POSITIVE",
        "context_quality_tier": "A",
    }
    touch = _candle(30, "2.20", "2.10", "2.15")
    gate = evaluate_continuation_gate(ctx, touch, Decimal("2.12"))
    assert gate.market_regime == "BULL"
    assert gate.symbol_regime == "UPTREND"
    assert gate.breath_phase == "EXPANSION"
    assert gate.breath_alignment == "POSITIVE"
    assert gate.context_quality_tier == "A"
