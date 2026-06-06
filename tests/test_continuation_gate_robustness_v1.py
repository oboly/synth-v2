"""
Tests for run_continuation_gate_robustness_v1.py

Covers:
- bootstrap CI correctness (interval contains sample mean at typical sizes)
- trimmed mean excludes outliers
- LOO produces one estimate per unique bucket value
- C5 degeneracy detection (identical deltas → DEGENERATE_WITH_C2)
- C5 distinct detection (different deltas → DISTINCT_FROM_C2)
- high-change labels: positive returns → HIGHER_HIGH; negative → not
- narrative label assignment
- horizon comparison returns 3 rows for 3c/6c/12c
- output files created with correct keys
- safety markers in manifest
- concentration warning on high month fraction
- LOO sensitivity reflects removed bucket mean
- fee adjustment note is present and correct
"""
from __future__ import annotations

import json
import csv
import math
import statistics
from pathlib import Path

import pytest

from src.research.run_continuation_gate_robustness_v1 import (
    BOOTSTRAP_N,
    BOOTSTRAP_SEED,
    FEE_RT_PCT,
    HORIZON_COMPARISON,
    MATCHED_CONFLICT_N,
    _bootstrap_ci,
    _trimmed_mean,
    _stats,
    assign_high_change_labels,
    audit_c5_degeneracy,
    compute_breakdown,
    compute_concentration_summary,
    compute_horizon_comparison,
    compute_leave_one_out,
    load_and_join,
    write_robustness_outputs,
    write_visual_review,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ev(
    variant_type: str = "BREATH_HOLD",
    gate_state: str = "CONTINUATION_SUPPORTED",
    symbol: str = "BTC",
    asof_ts: str = "2026-04-01T00:00:00Z",
    delta: float = 1.0,
    r1: float = 1.0,
    r3: float = 1.5,
    r6: float = 2.0,
    r12: float = 3.0,
    r18: float = 4.0,
    r24: float = 5.0,
    max_runup: float = 6.0,
    min_fwd: float = -1.0,
    max_fwd: float = 6.0,
    max_drawdown: float = -0.5,
    market_regime: str = "TRENDING_UP",
    symbol_regime: str = "UNKNOWN",
    breath_phase: str = "EXPANSION",
    breath_alignment: str = "SUPPORTIVE",
    freshness: str = "FRESH",
) -> dict:
    return {
        "event_id": f"{symbol}_{asof_ts[:10]}",
        "symbol": symbol,
        "asof_ts_utc": asof_ts,
        "venue": "bitvavo",
        "interval_code": "4h",
        "variant_type": variant_type,
        "gate_state": gate_state,
        "delta_vs_c1": delta,
        "variant_return_pct": r6 if variant_type != "BASELINE" else r1,
        "live_valid": True,
        "fwd_return_1c": r1,
        "fwd_return_3c": r3,
        "fwd_return_6c": r6,
        "fwd_return_12c": r12,
        "fwd_return_18c": r18,
        "fwd_return_24c": r24,
        "max_runup_24c": max_runup,
        "min_fwd_return_24c": min_fwd,
        "max_fwd_return_24c": max_fwd,
        "max_drawdown_24c_from_asof_close": max_drawdown,
        "market_regime": market_regime,
        "symbol_regime": symbol_regime,
        "breath_phase": breath_phase,
        "breath_alignment": breath_alignment,
        "context_freshness_status": freshness,
        "context_lookup_status": "FOUND",
        "context_source": "signal_engine_state",
        "context_age_minutes": 60.0,
    }


# ---------------------------------------------------------------------------
# _bootstrap_ci
# ---------------------------------------------------------------------------

def test_bootstrap_ci_contains_sample_mean_for_large_n() -> None:
    """95% CI should bracket the sample mean for moderate n."""
    rng_vals = [float(i) for i in range(40)]
    mean = sum(rng_vals) / len(rng_vals)
    lo, hi = _bootstrap_ci(rng_vals)
    assert lo <= mean <= hi


def test_bootstrap_ci_symmetric_on_uniform_data() -> None:
    vals = [1.0] * 30
    lo, hi = _bootstrap_ci(vals)
    assert lo == pytest.approx(1.0, abs=0.01)
    assert hi == pytest.approx(1.0, abs=0.01)


def test_bootstrap_ci_empty_returns_nan() -> None:
    lo, hi = _bootstrap_ci([])
    assert math.isnan(lo) and math.isnan(hi)


def test_bootstrap_ci_wider_for_higher_variance() -> None:
    narrow = [1.0, 1.1, 1.2, 1.0, 1.1] * 6
    wide = [-10.0, 10.0, -5.0, 5.0, -8.0, 8.0] * 5
    lo_n, hi_n = _bootstrap_ci(narrow)
    lo_w, hi_w = _bootstrap_ci(wide)
    assert (hi_w - lo_w) > (hi_n - lo_n)


# ---------------------------------------------------------------------------
# _trimmed_mean
# ---------------------------------------------------------------------------

def test_trimmed_mean_removes_outlier() -> None:
    vals = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 100.0, -100.0]
    tm = _trimmed_mean(vals, fraction=0.10)
    assert tm is not None
    assert tm == pytest.approx(1.0, abs=0.1)


def test_trimmed_mean_empty_returns_none() -> None:
    assert _trimmed_mean([]) is None


def test_trimmed_mean_single_value() -> None:
    tm = _trimmed_mean([5.0])
    assert tm is not None


def test_trimmed_mean_less_than_raw_mean_with_positive_outlier() -> None:
    vals = [1.0] * 9 + [100.0]
    raw_mean = sum(vals) / len(vals)
    tm = _trimmed_mean(vals, fraction=0.10)
    assert tm is not None
    assert tm < raw_mean


# ---------------------------------------------------------------------------
# _stats
# ---------------------------------------------------------------------------

def test_stats_basic_correctness() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = _stats(vals, "test")
    assert s["n"] == 5
    assert s["mean"] == pytest.approx(3.0)
    assert s["median"] == pytest.approx(3.0)
    assert s["positive"] == 5
    assert s["negative"] == 0
    assert s["zero"] == 0
    assert s["win_rate_pct"] == 100.0


def test_stats_win_rate_half() -> None:
    vals = [1.0, -1.0, 2.0, -2.0]
    s = _stats(vals, "test")
    assert s["win_rate_pct"] == 50.0


def test_stats_fee_adj_mean_below_raw() -> None:
    vals = [2.0, 3.0, 4.0]
    s = _stats(vals, "test")
    assert s["fee_adj_mean"] == pytest.approx(s["mean"] - FEE_RT_PCT, abs=0.001)


def test_stats_sd_zero_for_uniform() -> None:
    s = _stats([5.0, 5.0, 5.0, 5.0], "test")
    assert s["sd"] == pytest.approx(0.0)


def test_stats_ci_in_output() -> None:
    vals = [1.0, 2.0, 3.0] * 10
    s = _stats(vals, "test")
    assert "ci_lo_95" in s
    assert "ci_hi_95" in s


def test_stats_empty() -> None:
    s = _stats([], "empty")
    assert s["n"] == 0


# ---------------------------------------------------------------------------
# assign_high_change_labels
# ---------------------------------------------------------------------------

def test_hc_positive_1c_sets_higher_high_4h() -> None:
    ev = _ev(r1=1.5)
    hc = assign_high_change_labels(ev)
    assert hc["higher_high_within_4h"] is True


def test_hc_negative_1c_clears_higher_high_4h() -> None:
    ev = _ev(r1=-0.5)
    hc = assign_high_change_labels(ev)
    assert hc["higher_high_within_4h"] is False


def test_hc_positive_6c_sets_higher_high_24h() -> None:
    ev = _ev(r6=2.0)
    hc = assign_high_change_labels(ev)
    assert hc["higher_high_within_24h"] is True


def test_hc_negative_6c_clears_higher_high_24h() -> None:
    ev = _ev(r6=-1.0)
    hc = assign_high_change_labels(ev)
    assert hc["higher_high_within_24h"] is False


def test_hc_extension_then_reversal() -> None:
    """Meaningful runup (>1%) but 6c return is negative → EXTENSION_THEN_REVERSAL."""
    ev = _ev(r6=-0.5, max_runup=2.0)
    hc = assign_high_change_labels(ev)
    assert hc["high_change_narrative"] == "EXTENSION_THEN_REVERSAL"


def test_hc_no_meaningful_extension() -> None:
    """Low runup and negative 6c return → NO_MEANINGFUL_EXTENSION."""
    ev = _ev(r6=-0.5, max_runup=0.3)
    hc = assign_high_change_labels(ev)
    assert hc["high_change_narrative"] == "NO_MEANINGFUL_EXTENSION"


def test_hc_extension_then_hold() -> None:
    ev = _ev(r6=2.0, max_runup=3.0)
    hc = assign_high_change_labels(ev)
    assert hc["high_change_narrative"] == "EXTENSION_THEN_HOLD"


def test_hc_mfe_mae_present() -> None:
    ev = _ev(max_runup=4.0, max_drawdown=-1.5)
    hc = assign_high_change_labels(ev)
    assert hc["mfe_24c_pct"] == pytest.approx(4.0)
    assert hc["mae_24c_pct"] == pytest.approx(-1.5)


def test_hc_note_about_4c_8c() -> None:
    ev = _ev()
    hc = assign_high_change_labels(ev)
    assert "note_4c_8c_missing" in hc


# ---------------------------------------------------------------------------
# audit_c5_degeneracy
# ---------------------------------------------------------------------------

def _make_c2_c5_pair(event_id: str, delta: float, same_delta: bool = True) -> list[dict]:
    c2 = _ev(variant_type="BREATH_HOLD", gate_state="CONTINUATION_SUPPORTED", delta=delta)
    c2["event_id"] = event_id
    c5 = _ev(variant_type="PARENT_CONTEXT", gate_state="CONTINUATION_SUPPORTED",
             delta=delta if same_delta else delta + 1.0)
    c5["event_id"] = event_id
    return [c2, c5]


def test_c5_degenerate_when_all_deltas_identical() -> None:
    events = []
    for i in range(5):
        events.extend(_make_c2_c5_pair(f"ev{i}", float(i), same_delta=True))
    result = audit_c5_degeneracy(events)
    assert result["c5_verdict"] == "DEGENERATE_WITH_C2"
    assert result["n_identical_delta"] == 5


def test_c5_distinct_when_deltas_differ() -> None:
    events = []
    for i in range(5):
        events.extend(_make_c2_c5_pair(f"ev{i}", float(i), same_delta=False))
    result = audit_c5_degeneracy(events)
    assert result["c5_verdict"] == "DISTINCT_FROM_C2"


def test_c5_recommendation_present() -> None:
    events = _make_c2_c5_pair("ev0", 1.0, same_delta=True)
    result = audit_c5_degeneracy(events)
    assert "recommendation" in result
    assert len(result["recommendation"]) > 10


# ---------------------------------------------------------------------------
# compute_leave_one_out
# ---------------------------------------------------------------------------

def test_loo_produces_one_row_per_unique_bucket() -> None:
    deltas = [1.0, 2.0, 3.0, 4.0, 5.0]
    labels = ["A", "B", "A", "C", "B"]
    rows = compute_leave_one_out(deltas, labels, "sym")
    assert len(rows) == 3  # A, B, C


def test_loo_full_mean_is_consistent() -> None:
    deltas = [2.0, 2.0, 2.0, 2.0]
    labels = ["A", "B", "C", "D"]
    rows = compute_leave_one_out(deltas, labels, "sym")
    for r in rows:
        assert r["full_mean"] == pytest.approx(2.0)


def test_loo_sensitivity_is_correct() -> None:
    """Bucket with above-average delta should pull full mean up (sensitivity negative when removed)."""
    deltas = [1.0, 1.0, 1.0, 10.0]
    labels = ["A", "A", "A", "B"]
    rows = compute_leave_one_out(deltas, labels, "sym")
    b_row = next(r for r in rows if r["bucket"] == "B")
    # Removing B (delta=10) should pull LOO mean below full mean
    assert b_row["loo_mean_excluding_bucket"] < b_row["full_mean"]
    assert b_row["sensitivity"] > 0  # full_mean - loo_mean is positive


def test_loo_empty_returns_empty() -> None:
    assert compute_leave_one_out([], [], "sym") == []


# ---------------------------------------------------------------------------
# compute_horizon_comparison
# ---------------------------------------------------------------------------

def test_horizon_comparison_produces_3_rows() -> None:
    events = [_ev(r1=1.0, r3=1.5, r6=2.0, r12=3.0) for _ in range(5)]
    rows = compute_horizon_comparison(events)
    assert len(rows) == 3


def test_horizon_comparison_horizons_are_correct() -> None:
    events = [_ev(r1=1.0, r3=1.5, r6=2.0, r12=3.0) for _ in range(5)]
    rows = compute_horizon_comparison(events)
    horizons = {r["hold_candles"] for r in rows}
    assert horizons == {3, 6, 12}


def test_horizon_comparison_6c_labeled_as_c2_hypothesis() -> None:
    events = [_ev(r1=1.0, r3=1.5, r6=2.0, r12=3.0) for _ in range(5)]
    rows = compute_horizon_comparison(events)
    c2_row = next(r for r in rows if r["hold_candles"] == 6)
    assert "hypothesis" in c2_row["note"].lower() or "6" in c2_row["note"]


def test_horizon_comparison_delta_is_vs_1c() -> None:
    events = [_ev(r1=1.0, r3=2.0, r6=3.0, r12=4.0) for _ in range(5)]
    rows = compute_horizon_comparison(events)
    r3_row = next(r for r in rows if r["hold_candles"] == 3)
    # delta = r3 - r1 = 2.0 - 1.0 = 1.0
    assert r3_row["mean"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_concentration_summary
# ---------------------------------------------------------------------------

def test_concentration_warns_on_high_month_fraction() -> None:
    events = [_ev(symbol="BTC", asof_ts="2026-03-01T00:00:00Z") for _ in range(40)]
    events += [_ev(symbol="ETH", asof_ts="2026-04-01T00:00:00Z") for _ in range(5)]
    deltas = [1.0] * 45
    conc = compute_concentration_summary(events, deltas)
    assert conc["warning_high_month_concentration"] is True


def test_concentration_no_warning_balanced() -> None:
    events = (
        [_ev(symbol="BTC", asof_ts="2026-03-01T00:00:00Z") for _ in range(20)]
        + [_ev(symbol="ETH", asof_ts="2026-04-01T00:00:00Z") for _ in range(20)]
    )
    deltas = [1.0] * 40
    conc = compute_concentration_summary(events, deltas)
    assert conc["warning_high_month_concentration"] is False


def test_concentration_top5_contribution() -> None:
    """Top 5 events should dominate when their deltas are large."""
    events = [_ev(symbol=f"S{i}", asof_ts="2026-04-01T00:00:00Z") for i in range(10)]
    deltas = [10.0, 10.0, 10.0, 10.0, 10.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    conc = compute_concentration_summary(events, deltas)
    # Top 5 contribute 50/(50+5) ≈ 0.91
    assert conc["top5_event_delta_contribution"] == pytest.approx(50 / 55, abs=0.01)


# ---------------------------------------------------------------------------
# write_robustness_outputs — file creation and safety markers
# ---------------------------------------------------------------------------

def _make_minimal_summary() -> dict:
    return {
        "runner": "TEST",
        "n_supported_events": 5,
        "stats_per_variant": {"C2": {"n": 5, "mean": 1.0}},
        "c5_audit": {"c5_verdict": "DEGENERATE_WITH_C2"},
        "safety_markers": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        },
    }


def test_write_robustness_outputs_creates_all_files(tmp_path: Path) -> None:
    summary = _make_minimal_summary()
    ev = _ev()
    hc = assign_high_change_labels(ev)
    hc_row = {"event_id": "ev1", "symbol": "BTC", "asof_ts_utc": "2026-04-01T00:00:00Z",
               "gate_state": "CONTINUATION_SUPPORTED", "delta_vs_c1": 1.0, **hc}
    loo = [{"dimension": "symbol", "bucket": "BTC", "n_in_bucket": 1,
             "n_remaining": 4, "bucket_mean_delta": 1.0, "full_mean": 1.5,
             "loo_mean_excluding_bucket": 1.6, "sensitivity": -0.1}]
    robustness_rows = [{"variant": "C2", "n": 5, "mean": 1.0}]
    written = write_robustness_outputs(
        tmp_path, summary, robustness_rows, loo, [hc_row], {}
    )
    assert written["robustness_summary"].exists()
    assert written["robustness_rows"].exists()
    assert written["loo"].exists()
    assert written["high_change_breakdown"].exists()


def test_write_robustness_safety_markers_in_summary(tmp_path: Path) -> None:
    summary = _make_minimal_summary()
    write_robustness_outputs(tmp_path, summary, [], [], [], {})
    loaded = json.loads((tmp_path / "continuation_gate_robustness_summary_v1.json").read_text())
    sm = loaded["safety_markers"]
    assert sm["broker_writes"] == 0
    assert sm["order_submission"] == 0
    assert sm["decision_gate"] == "none"


# ---------------------------------------------------------------------------
# write_visual_review — file creation
# ---------------------------------------------------------------------------

def test_write_visual_review_creates_index_and_event_pages(tmp_path: Path) -> None:
    events = [_ev(symbol=f"S{i}", asof_ts=f"2026-04-{i+1:02d}T00:00:00Z") for i in range(3)]
    written = write_visual_review(tmp_path, events, [], [], [])
    assert written["index"].exists()
    idx_html = written["index"].read_text()
    assert "index.html" in str(written["index"])
    # Check index contains event links
    assert "view" in idx_html
    assert "S0" in idx_html


def test_write_visual_review_index_has_filter_controls(tmp_path: Path) -> None:
    events = [_ev()]
    write_visual_review(tmp_path, events, [], [], [])
    idx = (tmp_path / "visual_review" / "index.html").read_text()
    assert "filter" in idx.lower()
    assert "gate" in idx.lower()


def test_write_visual_review_event_page_has_svg(tmp_path: Path) -> None:
    events = [_ev()]
    written = write_visual_review(tmp_path, events, [], [], [])
    # Find event page
    ev_pages = [v for k, v in written.items() if k.startswith("event_")]
    assert len(ev_pages) >= 1
    html = ev_pages[0].read_text()
    assert "<svg" in html
    assert "polyline" in html


def test_write_visual_review_matched_samples_included(tmp_path: Path) -> None:
    supported = [_ev(gate_state="CONTINUATION_SUPPORTED")]
    conflict = [_ev(gate_state="BREATH_CONFLICT", variant_type="BREATH_HOLD")]
    written = write_visual_review(tmp_path, supported, conflict, [], [])
    vdir = tmp_path / "visual_review"
    files = list(vdir.glob("*.html"))
    # index + at least 2 event pages (1 supported + 1 conflict)
    assert len(files) >= 3
