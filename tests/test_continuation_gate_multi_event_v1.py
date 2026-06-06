"""
Tests for run_continuation_gate_multi_event_v1.py

Covers:
- deterministic event selection
- bounded max-events cap
- exclusion audit completeness
- no gate applied to C1
- paired C1 delta computation
- aggregate math (mean/median)
- unknown/stale context → CONTEXT_UNKNOWN gate
- stable output schemas
- safety markers in manifest
- C5 NOT_LIVE_VALID semantics
"""
from __future__ import annotations

import csv
import json
import statistics
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.research.run_continuation_gate_multi_event_v1 import (
    DEFAULT_INTERVAL,
    GATE_CONTEXT_UNKNOWN,
    GATE_CONTINUATION_SUPPORTED,
    GATE_CONTINUATION_WEAK,
    GATE_REGIME_CONFLICT,
    GATE_BREATH_CONFLICT,
    ExcludedEvent,
    EventRow,
    VariantEventResult,
    _apply_variant,
    _event_id,
    _select_return,
    compute_context_audit,
    compute_concentration,
    compute_symbol_aggregates,
    compute_variant_aggregates,
    load_events,
    process_event,
    write_outputs,
)
from src.research.run_manual_exact_zone_backtest_v1 import (
    CTX_FOUND,
    CTX_SOURCE_MISSING,
    ContextLookupAudit,
    ContextTimeline,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_event(
    symbol: str = "BTC",
    asof_ts: str = "2026-04-01T00:00:00Z",
    venue: str = "bitvavo",
    interval_code: str = "4h",
    close_price: float = 60000.0,
    outcome_available: bool = True,
    market_breath_phase: str = "EXPANSION",
    market_breath_state: str = "BULLISH",
    fwd_return_1c: float = 1.0,
    fwd_return_3c: float = 2.0,
    fwd_return_6c: float = 3.0,
    fwd_return_12c: float = 4.0,
    fwd_return_18c: float = 5.0,
    fwd_return_24c: float = 6.0,
    max_drawdown: float = -0.5,
) -> EventRow:
    return EventRow(
        asof_ts_utc=asof_ts,
        symbol=symbol,
        venue=venue,
        interval_code=interval_code,
        close_price=close_price,
        outcome_available=outcome_available,
        market_breath_phase=market_breath_phase,
        market_breath_state=market_breath_state,
        fwd_return_1c=fwd_return_1c,
        fwd_return_3c=fwd_return_3c,
        fwd_return_6c=fwd_return_6c,
        fwd_return_12c=fwd_return_12c,
        fwd_return_18c=fwd_return_18c,
        fwd_return_24c=fwd_return_24c,
        max_drawdown_24c_from_asof_close=max_drawdown,
    )


def _make_audit(
    status: str = CTX_FOUND,
    source: str = "signal_engine_state",
    gate_applied: bool = True,
    age_minutes: float = 60.0,
    freshness_status: str = "FRESH",
    context_ts_utc: str = "2026-04-01T00:00:00Z",
) -> ContextLookupAudit:
    ts = datetime.fromisoformat(context_ts_utc.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    return ContextLookupAudit(
        context_lookup_status=status,
        context_source=source,
        context_ts_utc=ts,
        context_age_minutes=age_minutes,
        max_context_age_minutes=2880,
        context_freshness_status=freshness_status,
        source_refs=source,
        gate_applied=gate_applied,
        fallback_policy=None,
        fallback_reason=None,
    )


def _make_timeline_with_audit(gate_state: str, audit: ContextLookupAudit) -> ContextTimeline:
    """Build a mock ContextTimeline whose at_with_audit() returns a matching ctx."""
    ctx = _gate_state_to_ctx(gate_state)
    tl = MagicMock(spec=ContextTimeline)
    tl.at_with_audit.return_value = (ctx, audit)
    return tl


def _gate_state_to_ctx(gate_state: str) -> dict:
    """Produce a ctx dict that will trigger the given gate state."""
    if gate_state == GATE_REGIME_CONFLICT:
        return {"market_regime": "BEARISH", "symbol_regime": "UNKNOWN",
                "breath_phase": "EXPANSION", "breath_alignment": "SUPPORTIVE"}
    if gate_state == GATE_BREATH_CONFLICT:
        return {"market_regime": "TRENDING_UP", "symbol_regime": "RANGE",
                "breath_phase": "DISTRIBUTION", "breath_alignment": "WEAK"}
    if gate_state == GATE_CONTEXT_UNKNOWN:
        return {"market_regime": "UNKNOWN", "symbol_regime": "UNKNOWN",
                "breath_phase": "UNKNOWN", "breath_alignment": "UNKNOWN"}
    if gate_state == GATE_CONTINUATION_SUPPORTED:
        # touch_candle=None so close_above always False; can't reach SUPPORTED from runtime
        # Use all positives — gate lands at WEAK because close_above=False
        return {"market_regime": "TRENDING_UP", "symbol_regime": "RANGE",
                "breath_phase": "EXPANSION", "breath_alignment": "SUPPORTIVE"}
    # WEAK
    return {"market_regime": "TRENDING_UP", "symbol_regime": "RANGE",
            "breath_phase": "EXPANSION", "breath_alignment": "SUPPORTIVE"}


def _write_source_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _make_source_row(
    symbol: str = "BTC",
    asof_ts: str = "2026-04-01T00:00:00Z",
    outcome_available: bool = True,
    interval_code: str = "4h",
    venue: str = "bitvavo",
) -> dict:
    return {
        "asof_ts_utc": asof_ts,
        "symbol": symbol,
        "venue": venue,
        "interval_code": interval_code,
        "close_price": 60000.0,
        "outcome_available": outcome_available,
        "market_breath_phase": "EXPANSION",
        "market_breath_state": "BULLISH",
        "fwd_return_1c": 1.0,
        "fwd_return_3c": 2.0,
        "fwd_return_6c": 3.0,
        "fwd_return_12c": 4.0,
        "fwd_return_18c": 5.0,
        "fwd_return_24c": 6.0,
        "max_drawdown_24c_from_asof_close": -0.5,
    }


# ---------------------------------------------------------------------------
# load_events — deterministic selection
# ---------------------------------------------------------------------------

def test_load_events_deterministic_order(tmp_path: Path) -> None:
    """Same file always produces same event order (sorted by ts then symbol)."""
    src = tmp_path / "events.jsonl"
    # Write in non-sorted order
    rows = [
        _make_source_row("ETH", "2026-04-02T00:00:00Z"),
        _make_source_row("BTC", "2026-04-02T00:00:00Z"),
        _make_source_row("BTC", "2026-04-01T00:00:00Z"),
    ]
    _write_source_jsonl(src, rows)
    events, _ = load_events(src, "2026-04-01", "2026-04-30", None, 100, "4h")
    assert [(e.asof_ts_utc, e.symbol) for e in events] == [
        ("2026-04-01T00:00:00Z", "BTC"),
        ("2026-04-02T00:00:00Z", "BTC"),
        ("2026-04-02T00:00:00Z", "ETH"),
    ]


def test_load_events_deterministic_same_result_on_rerun(tmp_path: Path) -> None:
    src = tmp_path / "events.jsonl"
    rows = [_make_source_row(f"SYM{i}", "2026-04-01T00:00:00Z") for i in range(5, 0, -1)]
    _write_source_jsonl(src, rows)
    a, _ = load_events(src, "2026-04-01", "2026-04-30", None, 10, "4h")
    b, _ = load_events(src, "2026-04-01", "2026-04-30", None, 10, "4h")
    assert [(e.asof_ts_utc, e.symbol) for e in a] == [(e.asof_ts_utc, e.symbol) for e in b]


# ---------------------------------------------------------------------------
# load_events — bounds and exclusions
# ---------------------------------------------------------------------------

def test_load_events_max_events_cap(tmp_path: Path) -> None:
    src = tmp_path / "events.jsonl"
    rows = [_make_source_row(f"SYM{i:02d}", "2026-04-01T00:00:00Z") for i in range(10)]
    _write_source_jsonl(src, rows)
    events, excluded = load_events(src, "2026-04-01", "2026-04-30", None, 5, "4h")
    assert len(events) == 5
    overflow_excluded = [e for e in excluded if "max_events_cap" in e.exclusion_reason]
    assert len(overflow_excluded) == 5


def test_load_events_excluded_outcome_not_available(tmp_path: Path) -> None:
    src = tmp_path / "events.jsonl"
    rows = [
        _make_source_row("BTC", outcome_available=True),
        _make_source_row("ETH", outcome_available=False),
    ]
    _write_source_jsonl(src, rows)
    events, excluded = load_events(src, "2026-04-01", "2026-04-30", None, 100, "4h")
    assert len(events) == 1
    assert events[0].symbol == "BTC"
    assert any("outcome_not_available" in e.exclusion_reason for e in excluded)


def test_load_events_excluded_before_date_from(tmp_path: Path) -> None:
    src = tmp_path / "events.jsonl"
    rows = [
        _make_source_row("BTC", "2026-03-01T00:00:00Z"),
        _make_source_row("ETH", "2026-04-01T00:00:00Z"),
    ]
    _write_source_jsonl(src, rows)
    events, excluded = load_events(src, "2026-04-01", "2026-04-30", None, 100, "4h")
    assert len(events) == 1
    assert events[0].symbol == "ETH"
    assert any("before_date_from" in e.exclusion_reason for e in excluded)


def test_load_events_excluded_after_date_to(tmp_path: Path) -> None:
    src = tmp_path / "events.jsonl"
    rows = [
        _make_source_row("BTC", "2026-04-01T00:00:00Z"),
        _make_source_row("ETH", "2026-05-01T00:00:00Z"),
    ]
    _write_source_jsonl(src, rows)
    events, excluded = load_events(src, "2026-04-01", "2026-04-30", None, 100, "4h")
    assert len(events) == 1
    assert events[0].symbol == "BTC"
    assert any("after_date_to" in e.exclusion_reason for e in excluded)


def test_load_events_symbol_filter(tmp_path: Path) -> None:
    src = tmp_path / "events.jsonl"
    rows = [
        _make_source_row("BTC"),
        _make_source_row("ETH"),
        _make_source_row("SOL"),
    ]
    _write_source_jsonl(src, rows)
    events, excluded = load_events(src, "2026-04-01", "2026-04-30", ["BTC", "ETH"], 100, "4h")
    assert {e.symbol for e in events} == {"BTC", "ETH"}
    assert any("symbol_not_in_filter" in e.exclusion_reason for e in excluded)


def test_load_events_interval_filter(tmp_path: Path) -> None:
    src = tmp_path / "events.jsonl"
    rows = [
        _make_source_row("BTC", interval_code="4h"),
        _make_source_row("ETH", interval_code="1h"),
    ]
    _write_source_jsonl(src, rows)
    events, excluded = load_events(src, "2026-04-01", "2026-04-30", None, 100, "4h")
    assert len(events) == 1
    assert events[0].symbol == "BTC"
    assert any("interval_mismatch" in e.exclusion_reason for e in excluded)


def test_load_events_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_events(tmp_path / "nonexistent.jsonl", "2026-04-01", "2026-04-30", None, 100, "4h")


def test_load_events_all_excluded_records_all(tmp_path: Path) -> None:
    """Every source row that doesn't pass any filter must appear in excluded list."""
    src = tmp_path / "events.jsonl"
    rows = [
        _make_source_row("BTC", outcome_available=False),
        _make_source_row("ETH", "2026-01-01T00:00:00Z"),  # before date_from
    ]
    _write_source_jsonl(src, rows)
    events, excluded = load_events(src, "2026-04-01", "2026-04-30", None, 100, "4h")
    assert len(events) == 0
    assert len(excluded) == 2


# ---------------------------------------------------------------------------
# _apply_variant — no gate on C1
# ---------------------------------------------------------------------------

def _audit_gate_applied() -> ContextLookupAudit:
    return _make_audit(gate_applied=True)


def _audit_gate_not_applied() -> ContextLookupAudit:
    return _make_audit(gate_applied=False)


def test_c1_baseline_never_gate_applied() -> None:
    audit = _audit_gate_applied()  # even if audit says True
    _, _, gate_applied, _, _ = _apply_variant("C1", "BASELINE", GATE_CONTINUATION_WEAK, audit, _make_event(), 1.0)
    assert gate_applied is False


def test_c1_baseline_always_hold_1c() -> None:
    audit = _audit_gate_applied()
    hold, _, _, _, _ = _apply_variant("C1", "BASELINE", GATE_CONTINUATION_WEAK, audit, _make_event(), 1.0)
    assert hold == 1


def test_c1_baseline_delta_is_none() -> None:
    audit = _audit_gate_applied()
    _, _, _, _, delta = _apply_variant("C1", "BASELINE", GATE_CONTINUATION_WEAK, audit, _make_event(), 1.0)
    assert delta is None


# ---------------------------------------------------------------------------
# _apply_variant — C2 BREATH_HOLD
# ---------------------------------------------------------------------------

def test_c2_hold_6c_on_weak() -> None:
    audit = _audit_gate_applied()
    hold, ret, _, _, _ = _apply_variant("C2", "BREATH_HOLD", GATE_CONTINUATION_WEAK, audit, _make_event(), 1.0)
    assert hold == 6
    assert ret == 3.0  # fwd_return_6c


def test_c2_hold_1c_on_conflict() -> None:
    audit = _audit_gate_applied()
    hold, ret, _, _, _ = _apply_variant("C2", "BREATH_HOLD", GATE_REGIME_CONFLICT, audit, _make_event(), 1.0)
    assert hold == 1
    assert ret == 1.0


def test_c2_hold_1c_on_unknown() -> None:
    audit = _audit_gate_not_applied()
    hold, _, _, _, _ = _apply_variant("C2", "BREATH_HOLD", GATE_CONTEXT_UNKNOWN, audit, _make_event(), 1.0)
    assert hold == 1


# ---------------------------------------------------------------------------
# _apply_variant — C3 REGIME_SHIFT
# ---------------------------------------------------------------------------

def test_c3_hold_12c_on_weak() -> None:
    audit = _audit_gate_applied()
    hold, ret, _, _, _ = _apply_variant("C3", "REGIME_SHIFT", GATE_CONTINUATION_WEAK, audit, _make_event(), 1.0)
    assert hold == 12
    assert ret == 4.0  # fwd_return_12c


def test_c3_hold_1c_on_conflict() -> None:
    audit = _audit_gate_applied()
    hold, _, _, _, _ = _apply_variant("C3", "REGIME_SHIFT", GATE_REGIME_CONFLICT, audit, _make_event(), 1.0)
    assert hold == 1


# ---------------------------------------------------------------------------
# _apply_variant — C4 TRAILING_RUNNER
# ---------------------------------------------------------------------------

def test_c4_hold_12c_on_weak() -> None:
    audit = _audit_gate_applied()
    hold, _, _, _, _ = _apply_variant("C4", "TRAILING_RUNNER", GATE_CONTINUATION_WEAK, audit, _make_event(), 1.0)
    assert hold == 12


def test_c4_hold_1c_on_conflict() -> None:
    audit = _audit_gate_applied()
    hold, _, _, _, _ = _apply_variant("C4", "TRAILING_RUNNER", GATE_REGIME_CONFLICT, audit, _make_event(), 1.0)
    assert hold == 1


def test_c4_hold_6c_on_unknown() -> None:
    audit = _audit_gate_not_applied()
    hold, _, _, _, _ = _apply_variant("C4", "TRAILING_RUNNER", GATE_CONTEXT_UNKNOWN, audit, _make_event(), 1.0)
    assert hold == 6


# ---------------------------------------------------------------------------
# _apply_variant — C5 PARENT_CONTEXT live_valid
# ---------------------------------------------------------------------------

def test_c5_live_valid_false_on_context_unknown() -> None:
    audit = _audit_gate_not_applied()
    _, _, _, live_valid, _ = _apply_variant("C5", "PARENT_CONTEXT", GATE_CONTEXT_UNKNOWN, audit, _make_event(), 1.0)
    assert live_valid is False


def test_c5_live_valid_true_on_weak() -> None:
    audit = _audit_gate_applied()
    _, _, _, live_valid, _ = _apply_variant("C5", "PARENT_CONTEXT", GATE_CONTINUATION_WEAK, audit, _make_event(), 1.0)
    assert live_valid is True


# ---------------------------------------------------------------------------
# Paired C1 delta computation
# ---------------------------------------------------------------------------

def test_delta_vs_c1_correct_math() -> None:
    audit = _audit_gate_applied()
    event = _make_event(fwd_return_1c=1.0, fwd_return_6c=4.0)
    _, _, _, _, delta = _apply_variant("C2", "BREATH_HOLD", GATE_CONTINUATION_WEAK, audit, event, c1_return=1.0)
    assert delta == pytest.approx(3.0)  # 4.0 - 1.0


def test_delta_vs_c1_negative_when_variant_underperforms() -> None:
    audit = _audit_gate_applied()
    event = _make_event(fwd_return_1c=5.0, fwd_return_6c=2.0)
    _, _, _, _, delta = _apply_variant("C2", "BREATH_HOLD", GATE_CONTINUATION_WEAK, audit, event, c1_return=5.0)
    assert delta == pytest.approx(-3.0)


def test_delta_vs_c1_none_when_c1_return_is_none() -> None:
    audit = _audit_gate_applied()
    event = _make_event(fwd_return_1c=None)
    _, _, _, _, delta = _apply_variant("C2", "BREATH_HOLD", GATE_CONTINUATION_WEAK, audit, event, c1_return=None)
    assert delta is None


# ---------------------------------------------------------------------------
# process_event — integration with mock timeline
# ---------------------------------------------------------------------------

def test_process_event_produces_5_variants() -> None:
    audit = _make_audit(status=CTX_FOUND, gate_applied=True)
    tl = _make_timeline_with_audit(GATE_CONTINUATION_WEAK, audit)
    event = _make_event()
    results = process_event(event, tl)
    assert len(results) == 5


def test_process_event_c1_gate_applied_false() -> None:
    audit = _make_audit(status=CTX_FOUND, gate_applied=True)
    tl = _make_timeline_with_audit(GATE_CONTINUATION_WEAK, audit)
    results = process_event(_make_event(), tl)
    c1 = next(r for r in results if r.variant_type == "BASELINE")
    assert c1.gate_applied is False


def test_process_event_context_unknown_gate_state() -> None:
    audit = _make_audit(status=CTX_SOURCE_MISSING, gate_applied=False)
    tl = _make_timeline_with_audit(GATE_CONTEXT_UNKNOWN, audit)
    tl.at_with_audit.return_value = (
        {"market_regime": "UNKNOWN", "symbol_regime": "UNKNOWN",
         "breath_phase": "UNKNOWN", "breath_alignment": "UNKNOWN"},
        audit,
    )
    results = process_event(_make_event(), tl)
    for r in results:
        assert r.gate_state == GATE_CONTEXT_UNKNOWN


def test_process_event_context_lookup_status_propagated() -> None:
    audit = _make_audit(status=CTX_SOURCE_MISSING, gate_applied=False)
    tl = _make_timeline_with_audit(GATE_CONTEXT_UNKNOWN, audit)
    tl.at_with_audit.return_value = (
        {"market_regime": "UNKNOWN", "symbol_regime": "UNKNOWN",
         "breath_phase": "UNKNOWN", "breath_alignment": "UNKNOWN"},
        audit,
    )
    results = process_event(_make_event(), tl)
    for r in results:
        assert r.context_lookup_status == CTX_SOURCE_MISSING


# ---------------------------------------------------------------------------
# compute_variant_aggregates — math correctness
# ---------------------------------------------------------------------------

def _make_result(variant_type: str, gate_state: str, variant_return: float, delta: float) -> VariantEventResult:
    return VariantEventResult(
        event_id="ev1",
        symbol="BTC",
        venue="bitvavo",
        interval_code="4h",
        asof_ts_utc="2026-04-01T00:00:00Z",
        close_price=60000.0,
        market_breath_phase="EXPANSION",
        market_breath_state="BULLISH",
        fwd_return_1c=1.0,
        fwd_return_6c=3.0,
        fwd_return_12c=4.0,
        fwd_return_24c=6.0,
        max_drawdown_24c_from_asof_close=-0.5,
        variant_id="C2",
        variant_type=variant_type,
        gate_state=gate_state,
        gate_applied=True,
        live_valid=True,
        context_lookup_status=CTX_FOUND,
        context_source="signal_engine_state",
        context_ts_utc="2026-04-01T00:00:00Z",
        context_age_minutes=60.0,
        context_freshness_status="FRESH",
        breath_phase="EXPANSION",
        breath_alignment="SUPPORTIVE",
        market_regime="TRENDING_UP",
        symbol_regime="RANGE",
        variant_hold_candles=6,
        variant_return_pct=variant_return,
        delta_vs_c1=delta,
    )


def test_variant_aggregate_mean_delta_correct() -> None:
    results = [
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 3.0, 2.0),
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 5.0, 4.0),
    ]
    aggs = compute_variant_aggregates(results)
    row = next(a for a in aggs if a["variant_type"] == "BREATH_HOLD")
    assert row["mean_delta_vs_c1"] == pytest.approx(3.0)


def test_variant_aggregate_median_delta_correct() -> None:
    results = [
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 1.0, 1.0),
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 2.0, 2.0),
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 9.0, 9.0),
    ]
    aggs = compute_variant_aggregates(results)
    row = next(a for a in aggs if a["variant_type"] == "BREATH_HOLD")
    assert row["median_delta_vs_c1"] == pytest.approx(2.0)


def test_variant_aggregate_outcome_counts() -> None:
    results = [
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 3.0, 2.0),   # positive
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 0.0, -1.0),  # negative
        _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 1.0, 0.0),   # tie
    ]
    aggs = compute_variant_aggregates(results)
    row = next(a for a in aggs if a["variant_type"] == "BREATH_HOLD")
    assert row["positive"] == 1
    assert row["negative"] == 1
    assert row["tie"] == 1


# ---------------------------------------------------------------------------
# compute_context_audit — coverage rates
# ---------------------------------------------------------------------------

def _make_baseline_result(ctx_status: str, gate_state: str) -> VariantEventResult:
    r = _make_result("BASELINE", gate_state, 1.0, 0.0)
    r = VariantEventResult(**{**asdict(r), "context_lookup_status": ctx_status,
                               "variant_type": "BASELINE", "variant_id": "C1"})
    return r


def test_context_audit_found_count() -> None:
    results = [
        _make_baseline_result(CTX_FOUND, GATE_CONTINUATION_WEAK),
        _make_baseline_result(CTX_FOUND, GATE_CONTINUATION_WEAK),
        _make_baseline_result(CTX_SOURCE_MISSING, GATE_CONTEXT_UNKNOWN),
    ]
    audit = compute_context_audit(results)
    assert audit["context_found"] == 2
    assert audit["context_source_missing"] == 1


def test_context_audit_found_pct() -> None:
    results = [_make_baseline_result(CTX_FOUND, GATE_CONTINUATION_WEAK) for _ in range(3)]
    audit = compute_context_audit(results)
    assert audit["context_found_pct"] == 100.0


def test_context_audit_only_counts_baseline_rows() -> None:
    """Non-baseline rows should not inflate context counts."""
    baseline = _make_baseline_result(CTX_FOUND, GATE_CONTINUATION_WEAK)
    non_baseline = _make_result("BREATH_HOLD", GATE_CONTINUATION_WEAK, 3.0, 2.0)
    # patch non-baseline context status to SOURCE_MISSING — should not count
    nb = VariantEventResult(**{**asdict(non_baseline), "context_lookup_status": CTX_SOURCE_MISSING})
    audit = compute_context_audit([baseline, nb])
    assert audit["total_events"] == 1
    assert audit["context_found"] == 1


# ---------------------------------------------------------------------------
# compute_concentration
# ---------------------------------------------------------------------------

def test_concentration_symbol_counts() -> None:
    events = [
        _make_event("BTC"),
        _make_event("BTC"),
        _make_event("ETH"),
    ]
    conc = compute_concentration(events)
    assert conc["symbol_counts"]["BTC"] == 2
    assert conc["symbol_counts"]["ETH"] == 1
    assert conc["unique_symbols"] == 2
    assert conc["max_symbol_fraction"] == pytest.approx(2 / 3, abs=0.01)


def test_concentration_month_counts() -> None:
    events = [
        _make_event(asof_ts="2026-04-01T00:00:00Z"),
        _make_event(asof_ts="2026-04-15T00:00:00Z"),
        _make_event(asof_ts="2026-05-01T00:00:00Z"),
    ]
    conc = compute_concentration(events)
    assert conc["month_counts"]["2026-04"] == 2
    assert conc["month_counts"]["2026-05"] == 1


# ---------------------------------------------------------------------------
# write_outputs — schema stability and safety markers
# ---------------------------------------------------------------------------

def _make_full_output_data():
    """Build a minimal coherent dataset for write_outputs testing."""
    event = _make_event()
    excluded = [ExcludedEvent(symbol="SOL", asof_ts_utc="2026-04-01T00:00:00Z",
                              exclusion_reason="outcome_not_available")]
    audit = _make_audit()
    tl = _make_timeline_with_audit(GATE_CONTINUATION_WEAK, audit)
    results = process_event(event, tl)
    events = [event]
    variant_aggs = compute_variant_aggregates(results)
    symbol_aggs = compute_symbol_aggregates(results)
    context_audit = compute_context_audit([r for r in results if r.variant_type == "BASELINE"])
    concentration = compute_concentration(events)
    args_dict = {"date_from": "2026-04-01", "date_to": "2026-04-30"}
    return events, excluded, results, variant_aggs, symbol_aggs, context_audit, concentration, args_dict


def test_write_outputs_creates_all_files(tmp_path: Path) -> None:
    events, excluded, results, vaggs, saggs, ctx, conc, args = _make_full_output_data()
    src = tmp_path / "source.jsonl"
    _write_source_jsonl(src, [_make_source_row()])
    written = write_outputs(tmp_path / "out", events, excluded, results, vaggs, saggs, ctx, conc, args, src)
    required = [
        "event_csv", "event_jsonl", "excluded_csv",
        "variant_agg_csv", "variant_agg_json",
        "symbol_agg_csv", "symbol_agg_json",
        "context_audit_csv", "context_audit_json",
        "concentration_csv", "concentration_json",
        "manifest",
    ]
    for key in required:
        assert key in written, f"Missing output: {key}"
        assert written[key].exists(), f"File not created: {key}"


def test_write_outputs_manifest_has_safety_markers(tmp_path: Path) -> None:
    events, excluded, results, vaggs, saggs, ctx, conc, args = _make_full_output_data()
    src = tmp_path / "source.jsonl"
    _write_source_jsonl(src, [_make_source_row()])
    written = write_outputs(tmp_path / "out", events, excluded, results, vaggs, saggs, ctx, conc, args, src)
    manifest = json.loads(written["manifest"].read_text())
    safety = manifest["safety_markers"]
    assert safety["broker_private_calls"] == 0
    assert safety["broker_writes"] == 0
    assert safety["order_submission"] == 0
    assert safety["live_orders"] == 0
    assert safety["decision_gate"] == "none"
    assert safety["execution_planner"] == "none"
    assert safety["executor"] == "none"


def test_write_outputs_event_csv_has_expected_columns(tmp_path: Path) -> None:
    events, excluded, results, vaggs, saggs, ctx, conc, args = _make_full_output_data()
    src = tmp_path / "source.jsonl"
    _write_source_jsonl(src, [_make_source_row()])
    written = write_outputs(tmp_path / "out", events, excluded, results, vaggs, saggs, ctx, conc, args, src)
    with open(written["event_csv"]) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
    required_cols = [
        "event_id", "symbol", "asof_ts_utc", "variant_id", "variant_type",
        "gate_state", "gate_applied", "context_lookup_status", "context_source",
        "variant_hold_candles", "variant_return_pct", "delta_vs_c1", "live_valid",
    ]
    for col in required_cols:
        assert col in headers, f"Missing CSV column: {col}"


def test_write_outputs_excluded_csv_records_reasons(tmp_path: Path) -> None:
    events, excluded, results, vaggs, saggs, ctx, conc, args = _make_full_output_data()
    src = tmp_path / "source.jsonl"
    _write_source_jsonl(src, [_make_source_row()])
    written = write_outputs(tmp_path / "out", events, excluded, results, vaggs, saggs, ctx, conc, args, src)
    with open(written["excluded_csv"]) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(excluded)
    assert all("exclusion_reason" in r for r in rows)


def test_write_outputs_manifest_event_counts_match(tmp_path: Path) -> None:
    events, excluded, results, vaggs, saggs, ctx, conc, args = _make_full_output_data()
    src = tmp_path / "source.jsonl"
    _write_source_jsonl(src, [_make_source_row()])
    written = write_outputs(tmp_path / "out", events, excluded, results, vaggs, saggs, ctx, conc, args, src)
    manifest = json.loads(written["manifest"].read_text())
    counts = manifest["event_counts"]
    assert counts["included"] == len(events)
    assert counts["excluded"] == len(excluded)
    assert counts["result_rows"] == len(results)


# ---------------------------------------------------------------------------
# _select_return — correct horizon mapping
# ---------------------------------------------------------------------------

def test_select_return_1c() -> None:
    e = _make_event(fwd_return_1c=1.5)
    assert _select_return(e, 1) == 1.5


def test_select_return_6c() -> None:
    e = _make_event(fwd_return_6c=3.5)
    assert _select_return(e, 6) == 3.5


def test_select_return_24c() -> None:
    e = _make_event(fwd_return_24c=6.5)
    assert _select_return(e, 24) == 6.5


def test_select_return_unknown_horizon_none() -> None:
    e = _make_event()
    assert _select_return(e, 999) is None


# ---------------------------------------------------------------------------
# _event_id — stable format
# ---------------------------------------------------------------------------

def test_event_id_stable() -> None:
    a = _event_id("BTC", "2026-04-01T00:00:00Z")
    b = _event_id("BTC", "2026-04-01T00:00:00Z")
    assert a == b


def test_event_id_unique_per_symbol_ts() -> None:
    a = _event_id("BTC", "2026-04-01T00:00:00Z")
    b = _event_id("ETH", "2026-04-01T00:00:00Z")
    c = _event_id("BTC", "2026-04-02T00:00:00Z")
    assert a != b
    assert a != c
