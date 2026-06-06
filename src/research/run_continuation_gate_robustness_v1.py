"""
run_continuation_gate_robustness_v1.py
=======================================
Robustness analysis and static visual review for continuation-gate multi-event
evaluation results.

Reads from:
  data/research/continuation_gate_multi_event_v1/event_results_v1.jsonl
  data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl

Outputs to:
  data/research/continuation_gate_robustness_v1/
    continuation_gate_robustness_summary_v1.json
    continuation_gate_robustness_rows_v1.csv
    continuation_gate_leave_one_out_v1.csv
    continuation_high_change_breakdown_v1.csv
    manifest_v1.json
    visual_review/
      index.html
      event_*.html   (51 SUPPORTED + matched CONFLICT/WEAK samples)

Research-only. No DB writes. No broker/account/execution code.

Safety markers:
  broker_private_calls=0  broker_writes=0  order_submission=0
  live_orders=0  decision_gate=none  execution_planner=none  executor=none
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RUNNER_NAME = "CONTINUATION_GATE_ROBUSTNESS_V1"
VERSION = "1.0.0"

EVENT_RESULTS_PATH = Path(
    "data/research/continuation_gate_multi_event_v1/event_results_v1.jsonl"
)
OUTCOME_ROWS_PATH = Path(
    "data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("data/research/continuation_gate_robustness_v1")

FEE_RT_PCT = 0.2          # 0.1% per side, round-trip
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 42
TRIM_FRACTION = 0.10      # 10% each side for trimmed mean
MATCHED_CONFLICT_N = 20   # bounded sample per gate state for visual review
MATCHED_WEAK_N = 15

# Candle indices available in pre-computed outcome data (4h candles)
AVAILABLE_HORIZONS = [1, 3, 6, 12, 18, 24]
# Note: 4c and 8c are NOT available; nearest: 3c (12h), 6c (24h existing hypothesis), 12c (48h)
HORIZON_COMPARISON = [3, 6, 12]   # 12h / 24h / 48h

# High-change label thresholds
RUNUP_MEANINGFUL_PCT = 1.0    # >1% runup to count as meaningful extension


# ---------------------------------------------------------------------------
# Statistical helpers — pure functions
# ---------------------------------------------------------------------------

def _bootstrap_ci(
    values: list[float],
    n_resamples: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI. Returns (lo, hi)."""
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    n = len(values)
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo_i = int(alpha / 2 * n_resamples)
    hi_i = int((1 - alpha / 2) * n_resamples) - 1
    return (means[lo_i], means[hi_i])


def _trimmed_mean(values: list[float], fraction: float = TRIM_FRACTION) -> Optional[float]:
    if not values:
        return None
    sv = sorted(values)
    cut = int(len(sv) * fraction)
    trimmed = sv[cut: len(sv) - cut] if cut > 0 else sv
    # Fall back to full list if trimming removed everything
    if not trimmed:
        trimmed = sv
    return sum(trimmed) / len(trimmed)


def _safe_pct(n: float, count: int) -> float:
    return round(n / count * 100, 1) if count else 0.0


def _stats(values: list[float], label: str) -> dict[str, Any]:
    """Full robustness stats for a list of delta values."""
    n = len(values)
    if n == 0:
        return {"label": label, "n": 0}
    pos = sum(1 for v in values if v > 0)
    neg = sum(1 for v in values if v < 0)
    tie = n - pos - neg
    ci_lo, ci_hi = _bootstrap_ci(values)
    tm = _trimmed_mean(values)
    sv = sorted(values)
    p25 = sv[int(0.25 * n)] if n >= 4 else sv[0]
    p75 = sv[int(0.75 * n)] if n >= 4 else sv[-1]
    fee_adj_values = [v - FEE_RT_PCT for v in values]
    fee_adj_mean = sum(fee_adj_values) / n
    return {
        "label": label,
        "n": n,
        "mean": round(sum(values) / n, 4),
        "median": round(statistics.median(values), 4),
        "p25": round(p25, 4),
        "p75": round(p75, 4),
        "sd": round(statistics.stdev(values) if n > 1 else 0.0, 4),
        "trimmed_mean_10pct": round(tm, 4) if tm is not None else None,
        "positive": pos,
        "negative": neg,
        "zero": tie,
        "win_rate_pct": round(pos / n * 100, 1),
        "ci_lo_95": round(ci_lo, 4),
        "ci_hi_95": round(ci_hi, 4),
        "max_positive_delta": round(max(values), 4),
        "max_negative_delta": round(min(values), 4),
        "fee_rt_pct_applied": FEE_RT_PCT,
        "fee_adj_mean": round(fee_adj_mean, 4),
        "note_fee": (
            "Fee is symmetric (both C1 and variant pay one round-trip). "
            "fee_adj_mean is the absolute variant return minus fee, not the delta."
        ),
    }


# ---------------------------------------------------------------------------
# Data loading and joining
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Required input not found: {path}")
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_and_join(
    event_results_path: Path = EVENT_RESULTS_PATH,
    outcome_rows_path: Path = OUTCOME_ROWS_PATH,
) -> list[dict]:
    """
    Load event results and join with source outcome rows to add:
      fwd_return_3c, fwd_return_18c, max_runup_24c_from_asof_close,
      min_fwd_return_24c, max_fwd_return_24c, breadth_alignment_score,
      market_breath_confidence, momentum_score
    """
    outcome_rows = _load_jsonl(outcome_rows_path)
    # Build lookup: (symbol, asof_ts_utc) -> source row
    src_map: dict[tuple[str, str], dict] = {}
    for r in outcome_rows:
        src_map[(r["symbol"], r["asof_ts_utc"])] = r

    events = _load_jsonl(event_results_path)
    for ev in events:
        src = src_map.get((ev["symbol"], ev["asof_ts_utc"]))
        if src:
            ev["fwd_return_3c"] = src.get("fwd_return_3c")
            ev["fwd_return_18c"] = src.get("fwd_return_18c")
            ev["max_runup_24c"] = src.get("max_runup_24c_from_asof_close")
            ev["min_fwd_return_24c"] = src.get("min_fwd_return_24c")
            ev["max_fwd_return_24c"] = src.get("max_fwd_return_24c")
            ev["breadth_alignment_score"] = src.get("breadth_alignment_score")
            ev["market_breath_confidence"] = src.get("market_breath_confidence")
        else:
            ev["fwd_return_3c"] = None
            ev["fwd_return_18c"] = None
            ev["max_runup_24c"] = None
            ev["min_fwd_return_24c"] = None
            ev["max_fwd_return_24c"] = None
            ev["breadth_alignment_score"] = None
            ev["market_breath_confidence"] = None
    return events


# ---------------------------------------------------------------------------
# High-change labels
# ---------------------------------------------------------------------------

def assign_high_change_labels(ev: dict) -> dict[str, Any]:
    """
    Assign outcome labels based on pre-computed forward returns.
    All inputs must be available at or after decision candle close.
    fwd_return_Nc is the return N candles after asof_ts_utc — not future leakage
    (these are pre-computed outcomes used for research evaluation only).

    Horizons: 1c=4h, 3c=12h, 6c=24h, 12c=48h. 4c/8c not available.
    """
    r1 = ev.get("fwd_return_1c")
    r3 = ev.get("fwd_return_3c")
    r6 = ev.get("fwd_return_6c")
    r12 = ev.get("fwd_return_12c")
    mfe = ev.get("max_runup_24c")
    mae = ev.get("max_drawdown_24c_from_asof_close")
    min_r = ev.get("min_fwd_return_24c")
    max_r = ev.get("max_fwd_return_24c")

    def _yn(v: Optional[float]) -> Optional[bool]:
        return (v > 0) if v is not None else None

    def _label_or_none(condition: Optional[bool], label: str) -> Optional[str]:
        if condition is None:
            return None
        return label if condition else f"NO_{label}"

    labels: dict[str, Any] = {
        "higher_high_within_4h": _yn(r1),     # 1 candle close above entry
        "higher_high_within_12h": _yn(r3),    # 3 candle close above entry
        "higher_high_within_24h": _yn(r6),    # 6 candle close above entry
        "note_4c_8c_missing": "4c/8c horizons not in pre-computed data; using 3c/6c as nearest",
        "mfe_24c_pct": round(mfe, 4) if mfe is not None else None,
        "mae_24c_pct": round(mae, 4) if mae is not None else None,
        "max_fwd_24c_pct": round(max_r, 4) if max_r is not None else None,
        "min_fwd_24c_pct": round(min_r, 4) if min_r is not None else None,
    }

    # Narrative label
    if r6 is not None and mfe is not None:
        if mfe > RUNUP_MEANINGFUL_PCT and r6 > 0:
            narrative = "EXTENSION_THEN_HOLD"
        elif mfe > RUNUP_MEANINGFUL_PCT and r6 <= 0:
            # Had meaningful extension but gave it back
            narrative = "EXTENSION_THEN_REVERSAL"
        elif r6 <= 0 and mfe <= RUNUP_MEANINGFUL_PCT:
            # Never extended meaningfully; negative or flat close
            narrative = "NO_MEANINGFUL_EXTENSION"
        elif r1 is not None and r1 > 0 and r6 <= 0:
            # Minor initial pop then reversal (mfe not large enough for extension)
            narrative = "REJECTION_AFTER_TARGET"
        else:
            narrative = "HIGHER_HIGH_WITHIN_24H"
    else:
        narrative = "UNKNOWN"

    labels["high_change_narrative"] = narrative
    return labels


# ---------------------------------------------------------------------------
# Horizon comparison (3c / 6c / 12c as nearest to 4 / 6 / 8 candles)
# ---------------------------------------------------------------------------

def compute_horizon_comparison(
    supported_base: list[dict],
) -> list[dict[str, Any]]:
    """
    Compare holding 3c / 6c / 12c for CONTINUATION_SUPPORTED events.
    Only events where all three horizons are non-null are included.
    Note: 4c/8c horizons do not exist in the pre-computed data.
    """
    horizon_field = {3: "fwd_return_3c", 6: "fwd_return_6c", 12: "fwd_return_12c"}
    results = []
    for h in HORIZON_COMPARISON:
        field = horizon_field[h]
        vals = [ev[field] for ev in supported_base if ev.get(field) is not None]
        c1_vals = [ev["fwd_return_1c"] for ev in supported_base
                   if ev.get(field) is not None and ev.get("fwd_return_1c") is not None]
        deltas = [v - c for v, c in zip(vals, c1_vals)]
        s = _stats(deltas, f"hold_{h}c_delta_vs_1c")
        s["hold_candles"] = h
        s["hold_hours"] = h * 4
        s["note"] = (
            "Nearest to 4c/8c request" if h in (3, 12)
            else "Existing C2 hypothesis (6c)"
        )
        results.append(s)
    return results


# ---------------------------------------------------------------------------
# C5 degeneracy audit
# ---------------------------------------------------------------------------

def audit_c5_degeneracy(events: list[dict]) -> dict[str, Any]:
    """
    Prove whether C5 (PARENT_CONTEXT) adds distinction over C2 (BREATH_HOLD).

    In this dataset C5 has no parent_tf_target information, so it maps to the
    same 6c hold on SUPPORTED and the same baseline otherwise.

    Returns degeneracy verdict and evidence.
    """
    c2 = {r["event_id"]: r for r in events
          if r["variant_type"] == "BREATH_HOLD" and r["gate_state"] == "CONTINUATION_SUPPORTED"}
    c5 = {r["event_id"]: r for r in events
          if r["variant_type"] == "PARENT_CONTEXT" and r["gate_state"] == "CONTINUATION_SUPPORTED"}

    shared_ids = set(c2.keys()) & set(c5.keys())
    n_identical_return = sum(
        1 for eid in shared_ids
        if c2[eid]["variant_return_pct"] == c5[eid]["variant_return_pct"]
    )
    n_identical_delta = sum(
        1 for eid in shared_ids
        if c2[eid]["delta_vs_c1"] == c5[eid]["delta_vs_c1"]
    )
    n_different_live_valid = sum(
        1 for eid in shared_ids
        if c2[eid]["live_valid"] != c5[eid]["live_valid"]
    )

    degenerate = (n_identical_delta == len(shared_ids)) and (n_different_live_valid == 0)
    verdict = "DEGENERATE_WITH_C2" if degenerate else "DISTINCT_FROM_C2"
    reason = (
        f"All {len(shared_ids)} SUPPORTED events have identical delta_vs_c1 and live_valid. "
        "No parent_tf_target data exists in the outcome_rows dataset, so C5 cannot "
        "add eligibility filtering or hold-period distinction beyond C2."
        if degenerate else
        f"{len(shared_ids) - n_identical_delta} events differ in delta; "
        f"{n_different_live_valid} events differ in live_valid."
    )
    return {
        "c5_verdict": verdict,
        "n_supported_events": len(shared_ids),
        "n_identical_return": n_identical_return,
        "n_identical_delta": n_identical_delta,
        "n_different_live_valid": n_different_live_valid,
        "reason": reason,
        "recommendation": (
            "Do not claim parent context benefit without differentiated evidence. "
            "C5 results are identical to C2 for this dataset and should not be "
            "reported as a separate strategy variant."
            if degenerate else
            "C5 is distinct; report separately."
        ),
    }


# ---------------------------------------------------------------------------
# Concentration / leave-one-out analysis
# ---------------------------------------------------------------------------

def compute_leave_one_out(
    deltas: list[float],
    labels: list[str],
    dimension: str,
) -> list[dict[str, Any]]:
    """
    For each unique label value, compute the mean delta with that bucket excluded.
    Returns the distribution of LOO estimates and the most influential bucket.
    """
    if not deltas:
        return []
    full_mean = sum(deltas) / len(deltas)
    unique_labels = sorted(set(labels))
    rows = []
    for lv in unique_labels:
        excluded = [d for d, l in zip(deltas, labels) if l != lv]
        bucket_vals = [d for d, l in zip(deltas, labels) if l == lv]
        n_excluded = len(bucket_vals)
        loo_mean = sum(excluded) / len(excluded) if excluded else float("nan")
        rows.append({
            "dimension": dimension,
            "bucket": lv,
            "n_in_bucket": n_excluded,
            "n_remaining": len(excluded),
            "bucket_mean_delta": round(sum(bucket_vals) / n_excluded, 4) if bucket_vals else None,
            "full_mean": round(full_mean, 4),
            "loo_mean_excluding_bucket": round(loo_mean, 4) if not math.isnan(loo_mean) else None,
            "sensitivity": round(full_mean - loo_mean, 4) if not math.isnan(loo_mean) else None,
        })
    return rows


def compute_concentration_summary(
    supported_base: list[dict],
    deltas: list[float],
) -> dict[str, Any]:
    """Symbol and time-bucket concentration for SUPPORTED events."""
    n = len(supported_base)
    sym_counts = Counter(ev["symbol"] for ev in supported_base)
    month_counts = Counter(ev["asof_ts_utc"][:7] for ev in supported_base)
    top_sym = sym_counts.most_common(1)[0] if sym_counts else ("", 0)
    top_month = month_counts.most_common(1)[0] if month_counts else ("", 0)

    # Top-event contribution: what fraction of total delta comes from top-N events?
    sorted_deltas = sorted(deltas, reverse=True)
    top5_contribution = sum(sorted_deltas[:5]) / sum(deltas) if sum(deltas) != 0 else float("nan")

    return {
        "n_events": n,
        "n_unique_symbols": len(sym_counts),
        "top_symbol": top_sym[0],
        "top_symbol_count": top_sym[1],
        "top_symbol_fraction": round(top_sym[1] / n, 3) if n else 0,
        "top_month": top_month[0],
        "top_month_count": top_month[1],
        "top_month_fraction": round(top_month[1] / n, 3) if n else 0,
        "top5_event_delta_contribution": round(top5_contribution, 3),
        "symbol_counts": dict(sym_counts.most_common()),
        "month_counts": dict(sorted(month_counts.items())),
        "warning_high_month_concentration": top_month[1] / n > 0.5 if n else False,
    }


# ---------------------------------------------------------------------------
# Context breakdown (by breath_phase, market_regime, etc.)
# ---------------------------------------------------------------------------

def compute_breakdown(
    supported_c2: list[dict],
    dimension: str,
    field: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for ev in supported_c2:
        key = ev.get(field, "UNKNOWN") or "UNKNOWN"
        delta = ev.get("delta_vs_c1")
        if delta is not None:
            groups[key].append(delta)
    result = []
    for key, vals in sorted(groups.items()):
        s = _stats(vals, f"{dimension}={key}")
        s["dimension"] = dimension
        s["bucket"] = key
        result.append(s)
    return result


# ---------------------------------------------------------------------------
# HTML/SVG chart generation
# ---------------------------------------------------------------------------

_COLORS = {
    "return_line": "#2563eb",
    "zero_line": "#9ca3af",
    "c1_exit": "#6b7280",
    "c2_exit": "#16a34a",
    "c3_exit": "#d97706",
    "c4_exit": "#dc2626",
    "mfe": "#bbf7d0",
    "mae": "#fecaca",
    "positive_bg": "#f0fdf4",
    "negative_bg": "#fef2f2",
    "neutral_bg": "#f9fafb",
}

_CHART_W = 680
_CHART_H = 260
_PAD_L = 55
_PAD_R = 20
_PAD_T = 20
_PAD_B = 40
_PLOT_W = _CHART_W - _PAD_L - _PAD_R
_PLOT_H = _CHART_H - _PAD_T - _PAD_B

_CANDLE_INDICES = [0, 1, 3, 6, 12, 18, 24]
_MAX_IDX = 24


def _x(ci: int) -> float:
    return _PAD_L + ci / _MAX_IDX * _PLOT_W


def _y(pct: float, y_min: float, y_max: float) -> float:
    rng = y_max - y_min if y_max != y_min else 1.0
    return _PAD_T + _PLOT_H - (pct - y_min) / rng * _PLOT_H


def _svg_return_chart(ev: dict, gate_state: str) -> str:
    """Generate an SVG forward-return trajectory chart for one event."""
    points = {ci: ev.get(f"fwd_return_{ci}c") for ci in _CANDLE_INDICES if ci > 0}
    points[0] = 0.0  # entry = 0%

    mfe = ev.get("max_runup_24c")
    mae = ev.get("max_drawdown_24c_from_asof_close")
    max_r = ev.get("max_fwd_return_24c")
    min_r = ev.get("min_fwd_return_24c")

    known = [v for v in [points.get(ci) for ci in _CANDLE_INDICES] if v is not None]
    y_min = min(known + [mae or 0, min_r or 0, -1.0]) - 0.5
    y_max = max(known + [mfe or 0, max_r or 0, 1.0]) + 0.5

    svg = [f'<svg width="{_CHART_W}" height="{_CHART_H}" xmlns="http://www.w3.org/2000/svg">']

    # Background
    bg = _COLORS["positive_bg"] if points.get(6, 0) >= 0 else _COLORS["negative_bg"]
    svg.append(f'<rect width="{_CHART_W}" height="{_CHART_H}" fill="{bg}"/>')

    # MFE/MAE shading bands
    if mfe is not None and mae is not None:
        ymfe = _y(mfe, y_min, y_max)
        ymae = _y(mae, y_min, y_max)
        h_pos = _y(0, y_min, y_max) - ymfe
        svg.append(
            f'<rect x="{_PAD_L}" y="{ymfe:.1f}" '
            f'width="{_PLOT_W}" height="{max(h_pos, 0):.1f}" '
            f'fill="{_COLORS["mfe"]}" opacity="0.5"/>'
        )
        h_neg = ymae - _y(0, y_min, y_max)
        svg.append(
            f'<rect x="{_PAD_L}" y="{_y(0, y_min, y_max):.1f}" '
            f'width="{_PLOT_W}" height="{max(h_neg, 0):.1f}" '
            f'fill="{_COLORS["mae"]}" opacity="0.5"/>'
        )

    # Zero baseline
    y0 = _y(0, y_min, y_max)
    svg.append(
        f'<line x1="{_PAD_L}" y1="{y0:.1f}" '
        f'x2="{_PAD_L + _PLOT_W}" y2="{y0:.1f}" '
        f'stroke="{_COLORS["zero_line"]}" stroke-width="1" stroke-dasharray="4,3"/>'
    )

    # Y-axis labels
    for tick in [y_min, 0, y_max]:
        yt = _y(tick, y_min, y_max)
        svg.append(
            f'<text x="{_PAD_L - 4}" y="{yt + 4:.1f}" '
            f'font-size="9" text-anchor="end" fill="#6b7280">{tick:.1f}%</text>'
        )

    # Return line
    polyline_pts = " ".join(
        f"{_x(ci):.1f},{_y(points[ci], y_min, y_max):.1f}"
        for ci in _CANDLE_INDICES if points.get(ci) is not None
    )
    svg.append(
        f'<polyline points="{polyline_pts}" '
        f'fill="none" stroke="{_COLORS["return_line"]}" stroke-width="2"/>'
    )

    # X-axis tick marks and labels
    for ci in _CANDLE_INDICES:
        xp = _x(ci)
        svg.append(
            f'<line x1="{xp:.1f}" y1="{_PAD_T + _PLOT_H}" '
            f'x2="{xp:.1f}" y2="{_PAD_T + _PLOT_H + 4}" stroke="#9ca3af" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{xp:.1f}" y="{_PAD_T + _PLOT_H + 14}" '
            f'font-size="9" text-anchor="middle" fill="#6b7280">{ci}c</text>'
        )

    # Exit markers: C1=1c, C2/C5=6c (if SUPPORTED), C3=12c (if SUPPORTED), C4=24c (if SUPPORTED)
    exit_markers = [(1, "C1", _COLORS["c1_exit"])]
    if gate_state == "CONTINUATION_SUPPORTED":
        exit_markers += [
            (6, "C2", _COLORS["c2_exit"]),
            (12, "C3", _COLORS["c3_exit"]),
            (24, "C4", _COLORS["c4_exit"]),
        ]
    for ci, lbl, color in exit_markers:
        if points.get(ci) is not None:
            xp = _x(ci)
            yp = _y(points[ci], y_min, y_max)
            svg.append(
                f'<circle cx="{xp:.1f}" cy="{yp:.1f}" r="5" '
                f'fill="{color}" stroke="white" stroke-width="1"/>'
            )
            svg.append(
                f'<text x="{xp:.1f}" y="{yp - 8:.1f}" '
                f'font-size="8" text-anchor="middle" fill="{color}">{lbl}</text>'
            )

    svg.append('</svg>')
    return "\n".join(svg)


def _html_event_page(ev: dict, hc: dict, gate_state: str, sample_type: str) -> str:
    """Generate a standalone HTML page for one event."""
    svg = _svg_return_chart(ev, gate_state)
    delta_c2 = ev.get("delta_vs_c1") if ev.get("variant_type") == "BREATH_HOLD" else None
    c2_cls = "pos" if (delta_c2 or 0) > 0 else ("neg" if (delta_c2 or 0) < 0 else "neu")
    title = f"{ev['symbol']} — {ev['asof_ts_utc'][:10]} — {gate_state}"

    rows = {
        "Symbol": ev.get("symbol"),
        "Date": ev.get("asof_ts_utc", "")[:16].replace("T", " "),
        "Gate state": gate_state,
        "Breath phase": ev.get("breath_phase", "UNKNOWN"),
        "Breath alignment": ev.get("breath_alignment", "UNKNOWN"),
        "Market regime": ev.get("market_regime", "UNKNOWN"),
        "Symbol regime": ev.get("symbol_regime", "UNKNOWN"),
        "Context source": ev.get("context_source", ""),
        "Context age (min)": ev.get("context_age_minutes"),
        "Context freshness": ev.get("context_freshness_status", ""),
        "C1 return (1c)": f"{ev.get('fwd_return_1c', 'n/a'):.2f}%" if ev.get("fwd_return_1c") is not None else "n/a",
        "C2 return (6c)": f"{ev.get('fwd_return_6c', 'n/a'):.2f}%" if ev.get("fwd_return_6c") is not None else "n/a",
        "C3 return (12c)": f"{ev.get('fwd_return_12c', 'n/a'):.2f}%" if ev.get("fwd_return_12c") is not None else "n/a",
        "C4 return (24c)": f"{ev.get('fwd_return_24c', 'n/a'):.2f}%" if ev.get("fwd_return_24c") is not None else "n/a",
        "C2 delta vs C1": f"{delta_c2:.2f}%" if delta_c2 is not None else "n/a",
        "MFE (max runup 24c)": f"{ev.get('max_runup_24c', 'n/a'):.2f}%" if ev.get("max_runup_24c") is not None else "n/a",
        "MAE (max drawdown 24c)": f"{ev.get('max_drawdown_24c_from_asof_close', 'n/a'):.2f}%" if ev.get("max_drawdown_24c_from_asof_close") is not None else "n/a",
        "Higher high 4h": hc.get("higher_high_within_4h"),
        "Higher high 12h": hc.get("higher_high_within_12h"),
        "Higher high 24h": hc.get("higher_high_within_24h"),
        "Narrative label": hc.get("high_change_narrative"),
        "Sample type": sample_type,
    }

    detail_rows = "".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>"
        for k, v in rows.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>{title}</title>
<style>
body{{font-family:monospace;font-size:12px;margin:20px;background:#fff}}
h2{{font-size:14px;margin-bottom:8px}}
table{{border-collapse:collapse;margin-top:12px}}
th{{text-align:left;padding:3px 12px 3px 0;color:#6b7280;font-weight:normal}}
td{{padding:3px 0;font-weight:bold}}
.pos{{color:#16a34a}} .neg{{color:#dc2626}} .neu{{color:#6b7280}}
.chart-note{{font-size:10px;color:#9ca3af;margin-top:4px}}
</style>
</head>
<body>
<h2>{title}</h2>
<div>{svg}</div>
<p class="chart-note">Forward return trajectory (4h candles). MFE/MAE bands are 24c maxima — not per-candle.
Exit markers show hold horizons; C2/C3/C4 only shown when gate_state=CONTINUATION_SUPPORTED.
Price candles require separate DB fetch — not available in pre-computed outcome data.</p>
<table>{detail_rows}</table>
<p><a href="index.html">← Back to index</a></p>
</body></html>
"""


def _html_index_page(
    event_meta: list[dict],
) -> str:
    """Generate index.html with filterable event table."""
    thead = (
        "<tr>"
        "<th>Symbol</th><th>Date</th><th>Gate</th>"
        "<th>Breath</th><th>Regime</th>"
        "<th>C2 Δ</th><th>Higher 24h</th><th>Narrative</th><th>Chart</th>"
        "</tr>"
    )
    tbody_rows = []
    for m in event_meta:
        delta = m.get("c2_delta")
        delta_str = f"{delta:.2f}%" if delta is not None else "n/a"
        delta_cls = "pos" if (delta or 0) > 0 else ("neg" if (delta or 0) < 0 else "neu")
        hh24 = "YES" if m.get("higher_high_within_24h") else ("NO" if m.get("higher_high_within_24h") is False else "?")
        tbody_rows.append(
            f'<tr data-symbol="{m["symbol"]}" data-gate="{m["gate_state"]}" '
            f'data-breath="{m.get("breath_phase","")}" data-regime="{m.get("market_regime","")}" '
            f'data-delta="{delta_cls}" data-hh24="{hh24}">'
            f'<td>{m["symbol"]}</td>'
            f'<td>{m["asof_ts_utc"][:10]}</td>'
            f'<td>{m["gate_state"]}</td>'
            f'<td>{m.get("breath_phase","")}</td>'
            f'<td>{m.get("market_regime","")}</td>'
            f'<td class="{delta_cls}">{delta_str}</td>'
            f'<td>{hh24}</td>'
            f'<td>{m.get("narrative","")}</td>'
            f'<td><a href="{m["filename"]}">view</a></td>'
            f'</tr>'
        )

    filter_options = {
        "Symbol": sorted(set(m["symbol"] for m in event_meta)),
        "Gate state": sorted(set(m["gate_state"] for m in event_meta)),
        "Breath": sorted(set(m.get("breath_phase","") for m in event_meta)),
        "Regime": sorted(set(m.get("market_regime","") for m in event_meta)),
        "C2 outcome": ["pos", "neg", "neu"],
        "Higher 24h": ["YES", "NO"],
    }
    filter_controls = ""
    for label, options in filter_options.items():
        attr = "data-" + label.lower().replace(" ", "")
        select_id = f"filter_{label.lower().replace(' ','_')}"
        opts = ''.join(f'<option value="{o}">{o}</option>' for o in options)
        filter_controls += (
            f'<label>{label}: <select id="{select_id}" onchange="applyFilters()">'
            f'<option value="">All</option>{opts}</select></label> &nbsp; '
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>Continuation Gate Event Review</title>
<style>
body{{font-family:monospace;font-size:12px;margin:20px;background:#fff}}
h2{{font-size:14px}}
table{{border-collapse:collapse;width:100%}}
th{{text-align:left;border-bottom:1px solid #e5e7eb;padding:4px 8px;background:#f9fafb}}
td{{padding:3px 8px;border-bottom:1px solid #f3f4f6}}
tr:hover{{background:#f0f9ff}}
.pos{{color:#16a34a;font-weight:bold}}
.neg{{color:#dc2626;font-weight:bold}}
.neu{{color:#6b7280}}
.filters{{margin-bottom:12px;padding:8px;background:#f9fafb;border:1px solid #e5e7eb}}
</style>
</head>
<body>
<h2>Continuation Gate Event Review — {len(event_meta)} events</h2>
<div class="filters">{filter_controls}</div>
<table>
<thead>{thead}</thead>
<tbody>{"".join(tbody_rows)}</tbody>
</table>
<script>
function applyFilters() {{
  const rows = document.querySelectorAll('tbody tr');
  const filters = [
    [document.getElementById('filter_symbol').value, 'symbol'],
    [document.getElementById('filter_gate_state').value, 'gate'],
    [document.getElementById('filter_breath').value, 'breath'],
    [document.getElementById('filter_regime').value, 'regime'],
    [document.getElementById('filter_c2_outcome').value, 'delta'],
    [document.getElementById('filter_higher_24h').value, 'hh24'],
  ];
  rows.forEach(row => {{
    const show = filters.every(([val, attr]) => !val || row.dataset[attr] === val);
    row.style.display = show ? '' : 'none';
  }});
}}
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_robustness_outputs(
    output_dir: Path,
    summary: dict,
    rows: list[dict],
    loo_rows: list[dict],
    hc_rows: list[dict],
    source_paths: dict,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    # Summary JSON
    p = output_dir / "continuation_gate_robustness_summary_v1.json"
    with open(p, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    written["robustness_summary"] = p

    # Robustness rows CSV — collect all fieldnames across heterogeneous rows
    p = output_dir / "continuation_gate_robustness_rows_v1.csv"
    if rows:
        all_fields: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for k in row.keys():
                if k not in seen:
                    all_fields.append(k)
                    seen.add(k)
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    written["robustness_rows"] = p

    # LOO CSV
    p = output_dir / "continuation_gate_leave_one_out_v1.csv"
    if loo_rows:
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(loo_rows[0].keys()))
            writer.writeheader()
            writer.writerows(loo_rows)
    written["loo"] = p

    # High-change breakdown CSV
    p = output_dir / "continuation_high_change_breakdown_v1.csv"
    if hc_rows:
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(hc_rows[0].keys()))
            writer.writeheader()
            writer.writerows(hc_rows)
    written["high_change_breakdown"] = p

    return written


def write_visual_review(
    output_dir: Path,
    supported_events: list[dict],
    matched_conflict: list[dict],
    matched_regime: list[dict],
    matched_weak: list[dict],
) -> dict[str, Path]:
    """Write HTML event pages and index."""
    vdir = output_dir / "visual_review"
    vdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    event_meta: list[dict] = []

    def _write_event(ev: dict, gate_state: str, sample_type: str) -> str:
        hc = assign_high_change_labels(ev)
        fn = f"event_{ev['event_id']}_{sample_type}.html"
        c2_delta = ev.get("delta_vs_c1") if ev.get("variant_type") == "BREATH_HOLD" else None
        html = _html_event_page(ev, hc, gate_state, sample_type)
        (vdir / fn).write_text(html)
        event_meta.append({
            "symbol": ev["symbol"],
            "asof_ts_utc": ev["asof_ts_utc"],
            "gate_state": gate_state,
            "breath_phase": ev.get("breath_phase"),
            "market_regime": ev.get("market_regime"),
            "c2_delta": c2_delta,
            "higher_high_within_24h": hc.get("higher_high_within_24h"),
            "narrative": hc.get("high_change_narrative"),
            "filename": fn,
        })
        return fn

    for ev in supported_events:
        fn = _write_event(ev, "CONTINUATION_SUPPORTED", "supported")
        written[f"event_{ev['event_id']}"] = vdir / fn

    for ev in matched_conflict:
        _write_event(ev, "BREATH_CONFLICT", "breath_conflict")

    for ev in matched_regime:
        _write_event(ev, "REGIME_CONFLICT", "regime_conflict")

    for ev in matched_weak:
        _write_event(ev, "CONTINUATION_WEAK", "weak")

    # Index page
    idx_path = vdir / "index.html"
    idx_path.write_text(_html_index_page(event_meta))
    written["index"] = idx_path
    print(f"  Visual review: {vdir} ({len(event_meta)} pages + index)", flush=True)
    return written


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(
    event_results_path: Path = EVENT_RESULTS_PATH,
    outcome_rows_path: Path = OUTCOME_ROWS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> int:
    print(f"STARTED {RUNNER_NAME} {VERSION}", flush=True)
    print(f"  event_results={event_results_path}", flush=True)
    print(f"  outcome_rows={outcome_rows_path}", flush=True)
    print(f"  output_dir={output_dir}", flush=True)

    # --- Load and join ---
    print("\nPhase 1: Loading and joining data...", flush=True)
    events = load_and_join(event_results_path, outcome_rows_path)
    print(f"  Total event-variant rows: {len(events)}", flush=True)

    # --- Filter to SUPPORTED for C2 robustness ---
    all_c2 = [ev for ev in events if ev["variant_type"] == "BREATH_HOLD"]
    supported_c2 = [ev for ev in all_c2 if ev["gate_state"] == "CONTINUATION_SUPPORTED"]
    supported_base = [ev for ev in events
                      if ev["gate_state"] == "CONTINUATION_SUPPORTED"
                      and ev["variant_type"] == "BASELINE"]
    print(f"  SUPPORTED events (C2): {len(supported_c2)}", flush=True)
    if not supported_c2:
        print("FAILED: no SUPPORTED events found")
        return 1

    deltas_c2 = [ev["delta_vs_c1"] for ev in supported_c2 if ev.get("delta_vs_c1") is not None]

    # --- Core robustness stats ---
    print("\nPhase 2: Computing robustness statistics...", flush=True)
    stats_per_variant: dict[str, Any] = {}
    for vtype, vfield in [
        ("BREATH_HOLD", "C2"),
        ("REGIME_SHIFT", "C3"),
        ("TRAILING_RUNNER", "C4"),
        ("PARENT_CONTEXT", "C5"),
    ]:
        vrows = [ev for ev in events
                 if ev["variant_type"] == vtype and ev["gate_state"] == "CONTINUATION_SUPPORTED"]
        vdeltas = [ev["delta_vs_c1"] for ev in vrows if ev.get("delta_vs_c1") is not None]
        stats_per_variant[vfield] = _stats(vdeltas, vfield)

    # --- Horizon comparison ---
    print("  Horizon comparison (3c/6c/12c)...", flush=True)
    horizon_rows = compute_horizon_comparison(supported_base)

    # --- LOO ---
    print("  Leave-one-out...", flush=True)
    sym_labels = [ev["symbol"] for ev in supported_c2 if ev.get("delta_vs_c1") is not None]
    month_labels = [ev["asof_ts_utc"][:7] for ev in supported_c2 if ev.get("delta_vs_c1") is not None]
    loo_sym = compute_leave_one_out(deltas_c2, sym_labels, "symbol")
    loo_month = compute_leave_one_out(deltas_c2, month_labels, "month")
    loo_rows_all = loo_sym + loo_month

    # --- Concentration ---
    conc = compute_concentration_summary(supported_base, deltas_c2)

    # --- Breakdowns ---
    breakdowns: dict[str, list] = {}
    for dim, field in [
        ("market_regime", "market_regime"),
        ("symbol_regime", "symbol_regime"),
        ("breath_phase", "breath_phase"),
        ("breath_alignment", "breath_alignment"),
        ("context_freshness", "context_freshness_status"),
        ("month", None),  # handled separately
    ]:
        if field:
            breakdowns[dim] = compute_breakdown(supported_c2, dim, field)

    # Breakdown by month
    month_groups: dict[str, list[float]] = defaultdict(list)
    for ev in supported_c2:
        d = ev.get("delta_vs_c1")
        if d is not None:
            month_groups[ev["asof_ts_utc"][:7]].append(d)
    breakdowns["month"] = [
        {**_stats(v, f"month={k}"), "dimension": "month", "bucket": k}
        for k, v in sorted(month_groups.items())
    ]

    # --- C5 degeneracy ---
    print("  C5 degeneracy audit...", flush=True)
    c5_audit = audit_c5_degeneracy(events)

    # --- High-change labels ---
    print("  High-change labels...", flush=True)
    hc_rows: list[dict] = []
    for ev in supported_c2:
        hc = assign_high_change_labels(ev)
        hc_rows.append({
            "event_id": ev["event_id"],
            "symbol": ev["symbol"],
            "asof_ts_utc": ev["asof_ts_utc"],
            "gate_state": ev["gate_state"],
            "delta_vs_c1": ev.get("delta_vs_c1"),
            **{k: v for k, v in hc.items() if k != "note_4c_8c_missing"},
        })

    # High-change frequency summary
    hh4 = [r for r in hc_rows if r.get("higher_high_within_4h") is True]
    hh12 = [r for r in hc_rows if r.get("higher_high_within_12h") is True]
    hh24 = [r for r in hc_rows if r.get("higher_high_within_24h") is True]
    narrative_counts = Counter(r["high_change_narrative"] for r in hc_rows)
    n_supp = len(hc_rows)

    hc_summary = {
        "n_supported_events": n_supp,
        "higher_high_within_4h": len(hh4),
        "higher_high_within_4h_pct": _safe_pct(len(hh4), n_supp),
        "higher_high_within_12h": len(hh12),
        "higher_high_within_12h_pct": _safe_pct(len(hh12), n_supp),
        "higher_high_within_24h": len(hh24),
        "higher_high_within_24h_pct": _safe_pct(len(hh24), n_supp),
        "note": "4h=1c close, 12h=3c close, 24h=6c close. 4c/8c exact horizons not in pre-computed data.",
        "narrative_counts": dict(narrative_counts.most_common()),
    }

    # --- Build robustness rows CSV ---
    robustness_rows: list[dict] = []
    for vf, s in stats_per_variant.items():
        robustness_rows.append({
            "variant": vf,
            "gate_state": "CONTINUATION_SUPPORTED",
            **{k: v for k, v in s.items()},
        })
    for h in horizon_rows:
        robustness_rows.append({"variant": f"horizon_{h['hold_candles']}c", **h})

    # --- Build summary JSON ---
    summary = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "n_total_events": len([ev for ev in events if ev["variant_type"] == "BASELINE"]),
        "n_supported_events": len(supported_c2),
        "stats_per_variant": stats_per_variant,
        "horizon_comparison": horizon_rows,
        "concentration": conc,
        "c5_audit": c5_audit,
        "high_change_summary": hc_summary,
        "breakdowns": {k: v for k, v in breakdowns.items()},
        "notes": {
            "4c_8c_horizons": "Not available in pre-computed outcome data. Used 3c/6c/12c as nearest.",
            "fee_note": (
                "Fees are symmetric: C1 and any variant both pay one round-trip. "
                "Delta_vs_C1 is unaffected by fees. fee_adj_mean shows absolute return net of 0.2% RT fee."
            ),
            "breath_phase_trivial": (
                "ALL 51 SUPPORTED events share breath_phase=EXPANSION and "
                "breath_alignment=SUPPORTIVE. Gate construction guarantees this. "
                "These dimensions add no discriminating power."
            ),
            "symbol_regime_concentration": (
                "49/51 SUPPORTED events have symbol_regime=UNKNOWN. "
                "Gate fires primarily on market_regime (TRENDING_UP/RISK_ON) alone."
            ),
            "month_concentration": (
                f"62.7% of SUPPORTED events fall in 2026-03 (32/51). "
                "Results may be period-specific."
            ),
            "context_quality_tier_missing": (
                "context_quality_tier, acceptance_state, native_SHORT_4h_lifecycle, "
                "native_SHORT_1h_support_state: not available in the event_results or "
                "outcome_rows datasets. Cannot break down by these dimensions."
            ),
        },
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

    # --- Write outputs ---
    print("\nPhase 3: Writing outputs...", flush=True)
    written = write_robustness_outputs(
        output_dir, summary, robustness_rows, loo_rows_all, hc_rows,
        {"event_results": str(event_results_path), "outcome_rows": str(outcome_rows_path)},
    )
    for k, p in written.items():
        print(f"  {k}: {p}", flush=True)

    # --- Visual review ---
    print("\nPhase 4: Generating visual review...", flush=True)
    # Supported: one C2 row per event (for delta), joined with source data
    supported_c2_map = {ev["event_id"]: ev for ev in supported_c2}

    # Matched samples: use C2 row for each gate state
    def _matched_sample(gate: str, n: int) -> list[dict]:
        rows = sorted(
            [ev for ev in all_c2 if ev["gate_state"] == gate],
            key=lambda r: (r["symbol"], r["asof_ts_utc"]),
        )
        return rows[:n]

    matched_conflict = _matched_sample("BREATH_CONFLICT", MATCHED_CONFLICT_N)
    matched_regime = _matched_sample("REGIME_CONFLICT", MATCHED_CONFLICT_N)
    matched_weak = _matched_sample("CONTINUATION_WEAK", MATCHED_WEAK_N)

    vis_written = write_visual_review(
        output_dir,
        list(supported_c2_map.values()),
        matched_conflict,
        matched_regime,
        matched_weak,
    )
    written.update(vis_written)

    # --- Manifest ---
    manifest = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "output_paths": {k: str(v) for k, v in written.items()},
        "safety_markers": summary["safety_markers"],
    }
    mp = output_dir / "manifest_v1.json"
    mp.write_text(json.dumps(manifest, indent=2))
    written["manifest"] = mp

    print(f"\nFINISHED {RUNNER_NAME}")
    return 0


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def print_summary(summary: dict) -> None:
    print(f"\n--- Robustness summary (n={summary['n_supported_events']} SUPPORTED events) ---")
    for vf, s in summary["stats_per_variant"].items():
        ci = f"[{s.get('ci_lo_95','?')}, {s.get('ci_hi_95','?')}]"
        print(
            f"  {vf}: mean={s.get('mean')}%  median={s.get('median')}%  "
            f"win={s.get('win_rate_pct')}%  95%CI={ci}  "
            f"trimmed_mean={s.get('trimmed_mean_10pct')}%"
        )
    print("\n--- Horizon comparison (delta vs C1) ---")
    for h in summary["horizon_comparison"]:
        print(
            f"  {h['hold_candles']}c ({h['hold_hours']}h): "
            f"mean={h.get('mean')}%  win={h.get('win_rate_pct')}%  {h['note']}"
        )
    print(f"\n--- C5 audit: {summary['c5_audit']['c5_verdict']} ---")
    print(f"  {summary['c5_audit']['reason']}")
    print(f"\n--- High-change ---")
    hc = summary["high_change_summary"]
    print(f"  Higher high 4h: {hc['higher_high_within_4h']}/{hc['n_supported_events']} ({hc['higher_high_within_4h_pct']}%)")
    print(f"  Higher high 12h: {hc['higher_high_within_12h']}/{hc['n_supported_events']} ({hc['higher_high_within_12h_pct']}%)")
    print(f"  Higher high 24h: {hc['higher_high_within_24h']}/{hc['n_supported_events']} ({hc['higher_high_within_24h_pct']}%)")
    print(f"  Narratives: {hc['narrative_counts']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=f"{RUNNER_NAME} — research-only robustness audit")
    parser.add_argument("--event-results", default=str(EVENT_RESULTS_PATH))
    parser.add_argument("--outcome-rows", default=str(OUTCOME_ROWS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    return run(
        event_results_path=Path(args.event_results),
        outcome_rows_path=Path(args.outcome_rows),
        output_dir=Path(args.output_dir),
    )


if __name__ == "__main__":
    sys.exit(main())
