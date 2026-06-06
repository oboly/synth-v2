"""
run_continuation_gate_multi_event_v1.py
========================================
Bounded multi-event continuation-gate evaluation.

Goal: Measure whether C2-C5 continuation gates improve outcomes versus the C1
baseline across a deterministic bounded event set drawn from the canonical
market-breath outcome validation dataset.

Research-only. No DB writes. No broker/account/execution code.
Reuses gate logic from run_manual_exact_zone_backtest_v1.

Input
-----
  data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl

Each row represents a 4h candle observation with pre-computed forward returns.
The asof_ts_utc is treated as the prediction/entry timestamp.
close_price is the assumed entry price.
fwd_return_*c fields are the pre-computed outcomes (no future-look from runner).

Variant outcome selection (using pre-computed forward returns)
--------------------------------------------------------------
  C1 BASELINE:       always fwd_return_1c   (immediate 1-candle hold)
  C2 BREATH_HOLD:    SUPPORTED/WEAK→6c;  else→1c
  C3 REGIME_SHIFT:   SUPPORTED/WEAK→12c; else→1c
  C4 TRAILING_RUNNER:SUPPORTED→24c; WEAK→12c; CONFLICT→1c; UNKNOWN→6c
  C5 PARENT_CONTEXT: SUPPORTED/WEAK→6c (same as C2); NOT_LIVE_VALID when unknown

Safety markers
--------------
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Re-use gate logic from single-event runner
# ---------------------------------------------------------------------------
from src.research.run_manual_exact_zone_backtest_v1 import (
    CTX_FOUND,
    CTX_SOURCE_MISSING,
    CTX_ASOF_JOIN_MISS,
    CTX_CONTEXT_TOO_STALE,
    GATE_CONTINUATION_SUPPORTED,
    GATE_CONTINUATION_WEAK,
    GATE_REGIME_CONFLICT,
    GATE_BREATH_CONFLICT,
    GATE_CONTEXT_UNKNOWN,
    GATE_NOT_LIVE_VALID,
    ContextLookupAudit,
    ContextTimeline,
    _POSITIVE_BREATH_PHASES,
    _NEGATIVE_BREATH_PHASES,
    _POSITIVE_BREATH_ALIGNMENTS,
    _NEGATIVE_BREATH_ALIGNMENTS,
    _POSITIVE_REGIMES,
    _NEGATIVE_REGIMES,
    fetch_context_timeline_raw,
    load_db_config,
    connect,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RUNNER_NAME = "CONTINUATION_GATE_MULTI_EVENT_V1"
VERSION = "1.0.0"

CANONICAL_INPUT = Path(
    "data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("data/research/continuation_gate_multi_event_v1")

# Default bounds
DEFAULT_DATE_FROM = "2026-03-14"
DEFAULT_DATE_TO   = "2026-05-12"
DEFAULT_MAX_EVENTS = 500
DEFAULT_INTERVAL   = "4h"

# Variant definitions
_VARIANTS = [
    ("C1", "BASELINE",         "C1_BASELINE"),
    ("C2", "BREATH_HOLD",      "C2_BREATH_HOLD"),
    ("C3", "REGIME_SHIFT",     "C3_REGIME_SHIFT"),
    ("C4", "TRAILING_RUNNER",  "C4_TRAILING_RUNNER"),
    ("C5", "PARENT_CONTEXT",   "C5_PARENT_CONTEXT"),
]

# Only SUPPORTED may change variant behavior from the C1 baseline.
# WEAK, CONFLICT, and UNKNOWN all fall through to the C1 baseline hold (1c).
_EXTENDING_STATES = frozenset({GATE_CONTINUATION_SUPPORTED})


# ---------------------------------------------------------------------------
# Context-only gate (multi-event dataset)
# ---------------------------------------------------------------------------

def evaluate_gate_multi_event(ctx: dict) -> str:
    """
    Evaluate continuation gate using only point-in-time context fields.

    Drops the close_above_target condition used in the single-event runner
    because this dataset has no per-event zone target price.
    All four context fields must come from data observable at decision candle
    close — no forward return fields are read.

    Priority (highest overrides lower):
      REGIME_CONFLICT > BREATH_CONFLICT > CONTEXT_UNKNOWN >
      CONTINUATION_WEAK > CONTINUATION_SUPPORTED
    """
    market_regime = ctx.get("market_regime", "UNKNOWN")
    symbol_regime = ctx.get("symbol_regime", "UNKNOWN")
    breath_phase = ctx.get("breath_phase", "UNKNOWN")
    breath_alignment = ctx.get("breath_alignment", "UNKNOWN")

    mr_up = market_regime.upper()
    sr_up = symbol_regime.upper()
    bp_up = breath_phase.upper()
    ba_up = breath_alignment.upper()

    if mr_up in _NEGATIVE_REGIMES or sr_up in _NEGATIVE_REGIMES:
        return GATE_REGIME_CONFLICT
    if bp_up in _NEGATIVE_BREATH_PHASES or ba_up in _NEGATIVE_BREATH_ALIGNMENTS:
        return GATE_BREATH_CONFLICT
    if all(v == "UNKNOWN" for v in [market_regime, symbol_regime, breath_phase, breath_alignment]):
        return GATE_CONTEXT_UNKNOWN

    positive_regime = mr_up in _POSITIVE_REGIMES or sr_up in _POSITIVE_REGIMES
    positive_breath = bp_up in _POSITIVE_BREATH_PHASES
    positive_alignment = ba_up in _POSITIVE_BREATH_ALIGNMENTS

    if positive_regime and positive_breath and positive_alignment:
        return GATE_CONTINUATION_SUPPORTED

    return GATE_CONTINUATION_WEAK


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EventRow:
    """One canonical event from the source file."""
    asof_ts_utc: str
    symbol: str
    venue: str
    interval_code: str
    close_price: float
    outcome_available: bool
    market_breath_phase: str
    market_breath_state: str
    fwd_return_1c: Optional[float]
    fwd_return_3c: Optional[float]
    fwd_return_6c: Optional[float]
    fwd_return_12c: Optional[float]
    fwd_return_18c: Optional[float]
    fwd_return_24c: Optional[float]
    max_drawdown_24c_from_asof_close: Optional[float]


@dataclass
class ExcludedEvent:
    symbol: str
    asof_ts_utc: str
    exclusion_reason: str


@dataclass
class VariantEventResult:
    """One C1-C5 variant result for one event."""
    event_id: str
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: str
    close_price: float
    market_breath_phase: str
    market_breath_state: str
    fwd_return_1c: Optional[float]
    fwd_return_6c: Optional[float]
    fwd_return_12c: Optional[float]
    fwd_return_24c: Optional[float]
    max_drawdown_24c_from_asof_close: Optional[float]
    # variant fields
    variant_id: str
    variant_type: str
    gate_state: str
    gate_applied: bool
    live_valid: bool
    context_lookup_status: str
    context_source: str
    context_ts_utc: str
    context_age_minutes: Optional[float]
    context_freshness_status: str
    breath_phase: str
    breath_alignment: str
    market_regime: str
    symbol_regime: str
    variant_hold_candles: int
    variant_return_pct: Optional[float]
    delta_vs_c1: Optional[float]  # variant_return - c1_return; None for C1 itself


# ---------------------------------------------------------------------------
# Event loading and filtering
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def _ts_date(ts_str: str) -> str:
    """Extract YYYY-MM-DD from ISO timestamp string."""
    return ts_str[:10]


def _event_id(symbol: str, asof_ts_utc: str) -> str:
    return f"{symbol}_{asof_ts_utc.replace(':', '').replace('-', '').replace('T', '_').replace('Z', '')}"


def load_events(
    source: Path,
    date_from: str,
    date_to: str,
    symbols: Optional[list[str]],
    max_events: int,
    interval_code: str,
) -> tuple[list[EventRow], list[ExcludedEvent]]:
    """
    Load and filter events from canonical source file.

    Deterministic selection:
      1. Load all rows from source file in file order.
      2. Filter by interval_code.
      3. Filter by outcome_available=True.
      4. Filter by date range [date_from, date_to] (inclusive on date portion).
      5. Filter by symbols if specified.
      6. Sort deterministically: (asof_ts_utc ASC, symbol ASC).
      7. Apply max_events cap.

    Every excluded row is recorded with its exclusion reason.
    Fail closed if source file is missing.
    """
    if not source.exists():
        raise FileNotFoundError(f"Canonical source not found: {source}")

    raw: list[dict] = []
    with open(source) as f:
        for line in f:
            line = line.strip()
            if line:
                raw.append(json.loads(line))

    included: list[EventRow] = []
    excluded: list[ExcludedEvent] = []

    # Symbols set for fast lookup
    sym_set = set(symbols) if symbols else None

    for r in raw:
        sym = r.get("symbol", "")
        ts = r.get("asof_ts_utc", "")
        reason: Optional[str] = None

        if r.get("interval_code") != interval_code:
            reason = f"interval_mismatch:{r.get('interval_code')}"
        elif not r.get("outcome_available", False):
            reason = "outcome_not_available"
        elif _ts_date(ts) < date_from:
            reason = f"before_date_from:{date_from}"
        elif _ts_date(ts) > date_to:
            reason = f"after_date_to:{date_to}"
        elif sym_set is not None and sym not in sym_set:
            reason = f"symbol_not_in_filter:{sym}"

        if reason:
            excluded.append(ExcludedEvent(symbol=sym, asof_ts_utc=ts, exclusion_reason=reason))
            continue

        included.append(EventRow(
            asof_ts_utc=ts,
            symbol=sym,
            venue=r.get("venue", ""),
            interval_code=r.get("interval_code", ""),
            close_price=float(r.get("close_price", 0)),
            outcome_available=bool(r.get("outcome_available")),
            market_breath_phase=r.get("market_breath_phase") or "UNKNOWN",
            market_breath_state=r.get("market_breath_state") or "UNKNOWN",
            fwd_return_1c=r.get("fwd_return_1c"),
            fwd_return_3c=r.get("fwd_return_3c"),
            fwd_return_6c=r.get("fwd_return_6c"),
            fwd_return_12c=r.get("fwd_return_12c"),
            fwd_return_18c=r.get("fwd_return_18c"),
            fwd_return_24c=r.get("fwd_return_24c"),
            max_drawdown_24c_from_asof_close=r.get("max_drawdown_24c_from_asof_close"),
        ))

    # Deterministic sort
    included.sort(key=lambda e: (e.asof_ts_utc, e.symbol))

    # Apply max cap (record overflowed events)
    if len(included) > max_events:
        overflow = included[max_events:]
        for e in overflow:
            excluded.append(ExcludedEvent(
                symbol=e.symbol,
                asof_ts_utc=e.asof_ts_utc,
                exclusion_reason=f"max_events_cap:{max_events}",
            ))
        included = included[:max_events]

    return included, excluded


# ---------------------------------------------------------------------------
# Variant outcome selection (pure, no DB)
# ---------------------------------------------------------------------------

def _select_return(
    event: EventRow,
    hold_candles: int,
) -> Optional[float]:
    """Pick forward return for given hold horizon."""
    mapping = {
        1:  event.fwd_return_1c,
        3:  event.fwd_return_3c,
        6:  event.fwd_return_6c,
        12: event.fwd_return_12c,
        18: event.fwd_return_18c,
        24: event.fwd_return_24c,
    }
    return mapping.get(hold_candles)


def _apply_variant(
    variant_id: str,
    variant_type: str,
    gate_state: str,
    ctx_audit: ContextLookupAudit,
    event: EventRow,
    c1_return: Optional[float],
) -> tuple[int, Optional[float], bool, bool, Optional[float]]:
    """
    Determine hold_candles, variant_return, gate_applied, live_valid, delta_vs_c1.
    Pure function — no DB, no future leakage.

    Semantic rules enforced here:
    - Only CONTINUATION_SUPPORTED extends holding beyond the C1 baseline.
    - CONTINUATION_WEAK falls back to C1 baseline (1c); gate_applied=False.
    - BREATH_CONFLICT and REGIME_CONFLICT do not extend holding; gate_applied=False.
    - CONTEXT_UNKNOWN uses C1 baseline; gate_applied=False.
    - gate_applied=True only when CONTINUATION_SUPPORTED fires and behavior changes.
    """
    is_baseline = variant_type == "BASELINE"
    is_supported = gate_state == GATE_CONTINUATION_SUPPORTED
    is_unknown = gate_state == GATE_CONTEXT_UNKNOWN

    if is_baseline:
        hold_candles = 1
        gate_applied = False
        live_valid = True
    elif variant_type == "BREATH_HOLD":
        hold_candles = 6 if is_supported else 1
        gate_applied = is_supported
        live_valid = True
    elif variant_type == "REGIME_SHIFT":
        hold_candles = 12 if is_supported else 1
        gate_applied = is_supported
        live_valid = True
    elif variant_type == "TRAILING_RUNNER":
        hold_candles = 24 if is_supported else 1
        gate_applied = is_supported
        live_valid = True
    elif variant_type == "PARENT_CONTEXT":
        hold_candles = 6 if is_supported else 1
        gate_applied = is_supported
        # NOT_LIVE_VALID when context is unknown — cannot validate continuation
        live_valid = not is_unknown
    else:
        hold_candles = 1
        gate_applied = False
        live_valid = True

    variant_return = _select_return(event, hold_candles)
    delta = (
        (variant_return - c1_return)
        if (not is_baseline and c1_return is not None and variant_return is not None)
        else None
    )

    return hold_candles, variant_return, gate_applied, live_valid, delta


# ---------------------------------------------------------------------------
# Per-event processing
# ---------------------------------------------------------------------------

def process_event(
    event: EventRow,
    timeline: ContextTimeline,
) -> list[VariantEventResult]:
    """
    Evaluate C1-C5 for one event.
    Context is fetched point-in-time from the pre-built timeline.
    """
    asof_ts = _parse_ts(event.asof_ts_utc)
    ctx, ctx_audit = timeline.at_with_audit(asof_ts)

    # Context-only gate — no zone target price available in this dataset.
    # All inputs are observable at decision candle close.
    gate_state = evaluate_gate_multi_event(ctx)

    eid = _event_id(event.symbol, event.asof_ts_utc)
    results: list[VariantEventResult] = []

    # Compute C1 return first so C2-C5 can compute delta
    c1_return = event.fwd_return_1c

    for vid, vtype, vname in _VARIANTS:
        hold_candles, variant_return, gate_applied, live_valid, delta = _apply_variant(
            vid, vtype, gate_state, ctx_audit, event, c1_return,
        )
        results.append(VariantEventResult(
            event_id=eid,
            symbol=event.symbol,
            venue=event.venue,
            interval_code=event.interval_code,
            asof_ts_utc=event.asof_ts_utc,
            close_price=event.close_price,
            market_breath_phase=event.market_breath_phase,
            market_breath_state=event.market_breath_state,
            fwd_return_1c=event.fwd_return_1c,
            fwd_return_6c=event.fwd_return_6c,
            fwd_return_12c=event.fwd_return_12c,
            fwd_return_24c=event.fwd_return_24c,
            max_drawdown_24c_from_asof_close=event.max_drawdown_24c_from_asof_close,
            variant_id=vname,
            variant_type=vtype,
            gate_state=gate_state,
            gate_applied=gate_applied,
            live_valid=live_valid,
            context_lookup_status=ctx_audit.context_lookup_status,
            context_source=ctx_audit.context_source or "",
            context_ts_utc=ctx_audit.context_ts_utc.isoformat().replace("+00:00", "Z")
                           if ctx_audit.context_ts_utc else "",
            context_age_minutes=float(ctx_audit.context_age_minutes) if ctx_audit.context_age_minutes is not None else None,
            context_freshness_status=ctx_audit.context_freshness_status or "",
            breath_phase=ctx.get("breath_phase", "UNKNOWN"),
            breath_alignment=ctx.get("breath_alignment", "UNKNOWN"),
            market_regime=ctx.get("market_regime", "UNKNOWN"),
            symbol_regime=ctx.get("symbol_regime", "UNKNOWN"),
            variant_hold_candles=hold_candles,
            variant_return_pct=variant_return,
            delta_vs_c1=delta,
        ))

    return results


# ---------------------------------------------------------------------------
# Context timeline pre-fetch per symbol
# ---------------------------------------------------------------------------

def prefetch_timelines(
    conn,
    events: list[EventRow],
    interval_code: str,
) -> dict[str, ContextTimeline]:
    """
    Pre-fetch one ContextTimeline per (symbol, venue) covering the full event
    date range for that symbol. Re-uses a single DB round-trip per symbol.
    """
    from datetime import timedelta

    # Determine window per symbol
    sym_windows: dict[str, tuple[datetime, datetime, str]] = {}
    for e in events:
        key = e.symbol
        ts = _parse_ts(e.asof_ts_utc)
        if key not in sym_windows:
            sym_windows[key] = (ts, ts, e.venue)
        else:
            lo, hi, venue = sym_windows[key]
            sym_windows[key] = (min(lo, ts), max(hi, ts), venue)

    timelines: dict[str, ContextTimeline] = {}
    for symbol, (lo, hi, venue) in sym_windows.items():
        # Add 1 day buffer on each end to ensure full context coverage
        win_start = lo - timedelta(days=1)
        win_end = hi + timedelta(days=1)
        try:
            tl = fetch_context_timeline_raw(
                conn, symbol, venue, win_start, win_end, interval_code=interval_code,
            )
        except Exception as exc:
            print(f"  WARNING: context fetch failed for {symbol}: {exc}", flush=True)
            # Return an empty timeline so we get SOURCE_MISSING audit status
            from src.research.run_manual_exact_zone_backtest_v1 import _empty_context_timeline
            tl = _empty_context_timeline()
        timelines[symbol] = tl

    return timelines


# ---------------------------------------------------------------------------
# Aggregate computation
# ---------------------------------------------------------------------------

def _safe_mean(vals: list[float]) -> Optional[float]:
    return statistics.mean(vals) if vals else None


def _safe_median(vals: list[float]) -> Optional[float]:
    return statistics.median(vals) if vals else None


def _outcome_counts(deltas: list[float]) -> dict[str, int]:
    pos = sum(1 for d in deltas if d > 0)
    neg = sum(1 for d in deltas if d < 0)
    tie = sum(1 for d in deltas if d == 0)
    return {"positive": pos, "negative": neg, "tie": tie}


def compute_variant_aggregates(results: list[VariantEventResult]) -> list[dict[str, Any]]:
    """Aggregate by (variant_id, gate_state)."""
    from collections import defaultdict

    groups: dict[tuple[str, str], list[VariantEventResult]] = defaultdict(list)
    for r in results:
        groups[(r.variant_id, r.gate_state)].append(r)

    aggs: list[dict[str, Any]] = []
    for (vid, gstate), rows in sorted(groups.items()):
        returns = [r.variant_return_pct for r in rows if r.variant_return_pct is not None]
        deltas = [r.delta_vs_c1 for r in rows if r.delta_vs_c1 is not None]
        aggs.append({
            "variant_id": vid,
            "variant_type": rows[0].variant_type,
            "gate_state": gstate,
            "event_count": len(rows),
            "usable_return_count": len(returns),
            "usable_delta_count": len(deltas),
            "mean_return_pct": _safe_mean(returns),
            "median_return_pct": _safe_median(returns),
            "mean_delta_vs_c1": _safe_mean(deltas),
            "median_delta_vs_c1": _safe_median(deltas),
            **_outcome_counts(deltas),
        })
    return aggs


def compute_symbol_aggregates(results: list[VariantEventResult]) -> list[dict[str, Any]]:
    """Aggregate by (variant_id, symbol)."""
    from collections import defaultdict

    groups: dict[tuple[str, str], list[VariantEventResult]] = defaultdict(list)
    for r in results:
        groups[(r.variant_id, r.symbol)].append(r)

    aggs: list[dict[str, Any]] = []
    for (vid, sym), rows in sorted(groups.items()):
        deltas = [r.delta_vs_c1 for r in rows if r.delta_vs_c1 is not None]
        returns = [r.variant_return_pct for r in rows if r.variant_return_pct is not None]
        aggs.append({
            "variant_id": vid,
            "symbol": sym,
            "event_count": len(rows),
            "mean_return_pct": _safe_mean(returns),
            "mean_delta_vs_c1": _safe_mean(deltas),
            **_outcome_counts(deltas),
        })
    return aggs


def compute_context_audit(results: list[VariantEventResult]) -> dict[str, Any]:
    """Aggregate context coverage/staleness rates across all variants."""
    from collections import Counter

    # Only count once per event (use C1 which always runs)
    c1 = [r for r in results if r.variant_type == "BASELINE"]

    status_counts = Counter(r.context_lookup_status for r in c1)
    freshness_counts = Counter(r.context_freshness_status for r in c1 if r.context_freshness_status)
    gate_state_counts = Counter(r.gate_state for r in c1)
    source_counts = Counter(r.context_source for r in c1)

    total = len(c1)
    found = status_counts.get(CTX_FOUND, 0)

    return {
        "total_events": total,
        "context_found": found,
        "context_found_pct": round(found / total * 100, 1) if total else 0,
        "context_stale": status_counts.get(CTX_CONTEXT_TOO_STALE, 0),
        "context_asof_miss": status_counts.get(CTX_ASOF_JOIN_MISS, 0),
        "context_source_missing": status_counts.get(CTX_SOURCE_MISSING, 0),
        "status_breakdown": dict(status_counts),
        "freshness_breakdown": dict(freshness_counts),
        "gate_state_breakdown": dict(gate_state_counts),
        "source_breakdown": dict(source_counts),
    }


def compute_concentration(events: list[EventRow]) -> dict[str, Any]:
    """Report symbol and time-bucket concentration."""
    from collections import Counter

    sym_counts = Counter(e.symbol for e in events)
    month_counts = Counter(e.asof_ts_utc[:7] for e in events)
    total = len(events)

    return {
        "total_events": total,
        "unique_symbols": len(sym_counts),
        "symbol_counts": dict(sym_counts.most_common()),
        "month_counts": dict(sorted(month_counts.items())),
        "max_symbol_fraction": round(max(sym_counts.values()) / total, 3) if total else 0,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _r(v: Optional[float], places: int = 4) -> Any:
    """Round float for output; return None if None."""
    if v is None:
        return None
    return round(v, places)


def write_outputs(
    output_dir: Path,
    events: list[EventRow],
    excluded: list[ExcludedEvent],
    results: list[VariantEventResult],
    variant_aggs: list[dict],
    symbol_aggs: list[dict],
    context_audit: dict,
    concentration: dict,
    args_dict: dict,
    source_path: Path,
) -> dict[str, Path]:
    """Write all output files and manifest. Returns path mapping."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    # --- Event-level CSV ---
    event_csv = output_dir / "event_results_v1.csv"
    if results:
        fieldnames = list(VariantEventResult.__dataclass_fields__.keys())
        with open(event_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                row = asdict(r)
                row["variant_return_pct"] = _r(row["variant_return_pct"])
                row["delta_vs_c1"] = _r(row["delta_vs_c1"])
                row["context_age_minutes"] = _r(row["context_age_minutes"], 1)
                writer.writerow(row)
    written["event_csv"] = event_csv

    # --- Event-level JSONL ---
    event_jsonl = output_dir / "event_results_v1.jsonl"
    with open(event_jsonl, "w") as f:
        for r in results:
            row = asdict(r)
            row["variant_return_pct"] = _r(row["variant_return_pct"])
            row["delta_vs_c1"] = _r(row["delta_vs_c1"])
            f.write(json.dumps(row) + "\n")
    written["event_jsonl"] = event_jsonl

    # --- Exclusion audit CSV ---
    excl_csv = output_dir / "excluded_events_v1.csv"
    with open(excl_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "asof_ts_utc", "exclusion_reason"])
        writer.writeheader()
        for e in excluded:
            writer.writerow(asdict(e))
    written["excluded_csv"] = excl_csv

    # --- Variant aggregate CSV ---
    vagg_csv = output_dir / "variant_aggregate_v1.csv"
    if variant_aggs:
        with open(vagg_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(variant_aggs[0].keys()))
            writer.writeheader()
            for row in variant_aggs:
                writer.writerow({k: _r(v) if isinstance(v, float) else v for k, v in row.items()})
    written["variant_agg_csv"] = vagg_csv

    # --- Variant aggregate JSON ---
    vagg_json = output_dir / "variant_aggregate_v1.json"
    with open(vagg_json, "w") as f:
        json.dump(variant_aggs, f, indent=2, default=str)
    written["variant_agg_json"] = vagg_json

    # --- Symbol aggregate CSV ---
    sagg_csv = output_dir / "symbol_aggregate_v1.csv"
    if symbol_aggs:
        with open(sagg_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(symbol_aggs[0].keys()))
            writer.writeheader()
            for row in symbol_aggs:
                writer.writerow({k: _r(v) if isinstance(v, float) else v for k, v in row.items()})
    written["symbol_agg_csv"] = sagg_csv

    # --- Symbol aggregate JSON ---
    sagg_json = output_dir / "symbol_aggregate_v1.json"
    with open(sagg_json, "w") as f:
        json.dump(symbol_aggs, f, indent=2, default=str)
    written["symbol_agg_json"] = sagg_json

    # --- Context audit CSV ---
    ctx_csv = output_dir / "context_audit_v1.csv"
    ctx_rows = [
        {"metric": k, "value": v}
        for k, v in context_audit.items()
        if not isinstance(v, dict)
    ]
    with open(ctx_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value"])
        writer.writeheader()
        writer.writerows(ctx_rows)
    written["context_audit_csv"] = ctx_csv

    # --- Context audit JSON ---
    ctx_json = output_dir / "context_audit_v1.json"
    with open(ctx_json, "w") as f:
        json.dump(context_audit, f, indent=2)
    written["context_audit_json"] = ctx_json

    # --- Concentration audit CSV ---
    conc_csv = output_dir / "concentration_audit_v1.csv"
    conc_rows = (
        [{"dimension": "symbol", "key": k, "count": v}
         for k, v in concentration["symbol_counts"].items()]
        + [{"dimension": "month", "key": k, "count": v}
           for k, v in concentration["month_counts"].items()]
    )
    with open(conc_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["dimension", "key", "count"])
        writer.writeheader()
        writer.writerows(conc_rows)
    written["concentration_csv"] = conc_csv

    # --- Concentration audit JSON ---
    conc_json = output_dir / "concentration_audit_v1.json"
    with open(conc_json, "w") as f:
        json.dump(concentration, f, indent=2)
    written["concentration_json"] = conc_json

    # --- Manifest ---
    manifest = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "run_ts_utc": datetime.now(timezone.utc).isoformat(),
        "args": args_dict,
        "source_path": str(source_path),
        "event_counts": {
            "total_source_rows": sum(1 for _ in open(source_path)),
            "included": len(events),
            "excluded": len(excluded),
            "result_rows": len(results),
        },
        "output_paths": {k: str(v) for k, v in written.items()},
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
    manifest_path = output_dir / "manifest_v1.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    written["manifest"] = manifest_path

    return written


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _fmt(v: Optional[float], fmt: str = ".2f") -> str:
    if v is None:
        return "n/a"
    return format(v, fmt)


def print_variant_summary(variant_aggs: list[dict]) -> None:
    """Print compact C1-C5 summary grouped by variant."""
    from collections import defaultdict

    by_variant: dict[str, list[dict]] = defaultdict(list)
    for row in variant_aggs:
        by_variant[row["variant_id"]].append(row)

    print("\n--- Variant aggregate (by variant × gate_state) ---")
    header = f"{'Variant':<28} {'Gate state':<26} {'N':>5} {'Mean ret%':>10} {'Mean Δvs C1':>12} {'Pos':>5} {'Neg':>5} {'Tie':>5}"
    print(header)
    for vid, rows in sorted(by_variant.items()):
        for row in sorted(rows, key=lambda r: r["gate_state"]):
            print(
                f"{row['variant_id']:<28} {row['gate_state']:<26} "
                f"{row['event_count']:>5} "
                f"{_fmt(row.get('mean_return_pct')):>10} "
                f"{_fmt(row.get('mean_delta_vs_c1')):>12} "
                f"{row.get('positive', 0):>5} "
                f"{row.get('negative', 0):>5} "
                f"{row.get('tie', 0):>5}"
            )


def print_context_summary(ctx: dict) -> None:
    print("\n--- Context coverage ---")
    print(f"  Events: {ctx['total_events']}")
    print(f"  Found:  {ctx['context_found']} ({ctx['context_found_pct']}%)")
    print(f"  Stale:  {ctx['context_stale']}")
    print(f"  Miss:   {ctx['context_asof_miss']}")
    print(f"  Src missing: {ctx['context_source_missing']}")
    print(f"  Gate states: {ctx['gate_state_breakdown']}")


def print_concentration_summary(conc: dict) -> None:
    print("\n--- Concentration ---")
    print(f"  Symbols: {conc['unique_symbols']}, Events: {conc['total_events']}")
    print(f"  Max symbol fraction: {conc['max_symbol_fraction']:.1%}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(
    date_from: str = DEFAULT_DATE_FROM,
    date_to: str = DEFAULT_DATE_TO,
    symbols: Optional[list[str]] = None,
    max_events: int = DEFAULT_MAX_EVENTS,
    interval_code: str = DEFAULT_INTERVAL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    source: Path = CANONICAL_INPUT,
    dry_run: bool = False,
    env_file: Optional[str] = None,
) -> int:
    print(f"STARTED {RUNNER_NAME} {VERSION}", flush=True)
    print(f"  date_from={date_from} date_to={date_to} max_events={max_events}", flush=True)
    print(f"  symbols={symbols or 'ALL'} interval={interval_code}", flush=True)
    print(f"  source={source}", flush=True)
    print(f"  output_dir={output_dir}", flush=True)
    print(f"  dry_run={dry_run}", flush=True)
    print(flush=True)

    # --- Load events ---
    print("Phase 1: Loading and filtering events...", flush=True)
    events, excluded = load_events(
        source, date_from, date_to, symbols, max_events, interval_code
    )
    print(f"  Included: {len(events)}, Excluded: {len(excluded)}", flush=True)
    if not events:
        print("FAILED: no events after filtering — check date range, symbols, outcome_available")
        return 1

    concentration = compute_concentration(events)
    print_concentration_summary(concentration)

    if dry_run:
        print("\nDRY RUN — stopping before DB queries and output writes.")
        print(f"  Would process {len(events)} events × 5 variants = {len(events) * 5} rows.")
        return 0

    # --- Pre-fetch context timelines ---
    print("\nPhase 2: Pre-fetching context timelines per symbol...", flush=True)
    db_config = load_db_config(env_file)
    conn = connect(db_config)
    try:
        timelines = prefetch_timelines(conn, events, interval_code)
    finally:
        conn.close()
    print(f"  Timelines fetched: {len(timelines)} symbols", flush=True)

    # --- Process events ---
    print("\nPhase 3: Evaluating C1-C5 per event...", flush=True)
    all_results: list[VariantEventResult] = []
    for i, event in enumerate(events):
        tl = timelines.get(event.symbol)
        if tl is None:
            from src.research.run_manual_exact_zone_backtest_v1 import _empty_context_timeline
            tl = _empty_context_timeline()
        results_for_event = process_event(event, tl)
        all_results.extend(results_for_event)
        if (i + 1) % 50 == 0 or (i + 1) == len(events):
            print(f"  Processed {i + 1}/{len(events)} events...", flush=True)

    print(f"  Total result rows: {len(all_results)}", flush=True)

    # --- Compute aggregates ---
    print("\nPhase 4: Computing aggregates...", flush=True)
    variant_aggs = compute_variant_aggregates(all_results)
    symbol_aggs = compute_symbol_aggregates(all_results)
    context_audit = compute_context_audit(all_results)

    print_context_summary(context_audit)
    print_variant_summary(variant_aggs)

    # --- Write outputs ---
    print("\nPhase 5: Writing outputs...", flush=True)
    args_dict = {
        "date_from": date_from, "date_to": date_to, "symbols": symbols,
        "max_events": max_events, "interval_code": interval_code,
        "source": str(source), "output_dir": str(output_dir),
    }
    written = write_outputs(
        output_dir, events, excluded, all_results,
        variant_aggs, symbol_aggs, context_audit, concentration,
        args_dict, source,
    )
    for name, path in written.items():
        print(f"  {name}: {path}", flush=True)

    print(f"\nFINISHED {RUNNER_NAME} — {len(events)} events, {len(all_results)} result rows")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded multi-event continuation-gate evaluation (research only)."
    )
    parser.add_argument("--date-from", default=DEFAULT_DATE_FROM,
                        help=f"Start date inclusive YYYY-MM-DD (default: {DEFAULT_DATE_FROM})")
    parser.add_argument("--date-to", default=DEFAULT_DATE_TO,
                        help=f"End date inclusive YYYY-MM-DD (default: {DEFAULT_DATE_TO})")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Symbol filter (default: all symbols)")
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS,
                        help=f"Hard cap on included events (default: {DEFAULT_MAX_EVENTS})")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL,
                        help=f"Candle interval filter (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--source", default=str(CANONICAL_INPUT),
                        help="Path to canonical source JSONL")
    parser.add_argument("--dry-run", action="store_true",
                        help="Load and filter events; skip DB queries and file writes")
    parser.add_argument("--env-file", default=None,
                        help="Path to .env file for DB config (default: auto-detect)")
    args = parser.parse_args(argv)

    return run(
        date_from=args.date_from,
        date_to=args.date_to,
        symbols=args.symbols,
        max_events=args.max_events,
        interval_code=args.interval,
        output_dir=Path(args.output_dir),
        source=Path(args.source),
        dry_run=args.dry_run,
        env_file=args.env_file,
    )


if __name__ == "__main__":
    sys.exit(main())
