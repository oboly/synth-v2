"""
run_unified_lifecycle_visual_review_v1.py
==========================================
Unified child/parent/Breath/Regime lifecycle visual review.

Creates one transparent static HTML visual showing why an event leads to:
  - partial trim (CONTINUATION_WEAK / BREATH_CONFLICT / REGIME_CONFLICT)
  - continuation hold (CONTINUATION_SUPPORTED)
  - reduce to residual (TERMINAL_CONFIRMED + WEAKNESS_CONFIRMED)
  - re-entry blocked (REENTRY_BLOCKED_WEAKNESS / REENTRY_BLOCKED_PARENT_TERMINAL)
  - watch re-entry (WATCH_REENTRY)
  - re-entry context supported (REENTRY_CONTEXT_SUPPORTED)

Visual Layers per Event Page
-----------------------------
  1. Price return chart (SVG): close + fwd return trajectory
  2. Child fib map layer: synthetic reload levels, target, invalidation (noted as proxies)
  3. Parent fib map layer: parent terminal state, lifecycle (synthetic proxies)
  4. Breath layer: phase, alignment, score, state
  5. Regime layer: market regime, symbol regime, scores
  6. Event markers: target touch, decision, trim/exit, weakness/rejection, reset, re-entry
  7. Outcomes: MFE/MAE lines, extension then reversal, close at horizon, policy outcomes

Required Input Sources
-----------------------
  data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl
  data/research/continuation_gate_multi_event_v1/event_results_v1.jsonl
  data/research/weakness_reentry_block_v1/event_results_v1.csv
  data/research/parent_terminal_residual_exit_v1/event_results_v1.csv

Matched Examples Per Category
------------------------------
  CONTINUATION_SUPPORTED       (gate_state from multi-event runner)
  BREATH_CONFLICT              (gate_state from multi-event runner)
  REGIME_CONFLICT              (gate_state from multi-event runner)
  TERMINAL_CONFIRMED           (parent terminal proxy from COLLAPSE_RESET events)
  PARENT_CONTEXT_UNKNOWN       (NEUTRAL_TRANSITION phase events)
  REENTRY_BLOCKED_WEAKNESS     (re-entry block runner)
  REENTRY_CONTEXT_SUPPORTED    (re-entry block runner)

Filters (JavaScript, in-page)
-------------------------------
  symbol, date range, gate state, parent state, re-entry state,
  breath phase, breath alignment, regime, outcome classification,
  positive/negative r6 outcome

Requirements
-------------
  Static HTML/SVG only (no external CDN dependencies).
  All timestamps and source provenance visible.
  No hidden score: all scores shown numerically.
  No future evidence before decision timestamp.
  No filesystem paths in public hrefs (all relative paths).
  Do not commit generated outputs.

Research-only. No DB writes. No broker/account/execution/decision_gate code.

Safety markers
--------------
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none

Regenerate
----------
  python -m src.research.run_unified_lifecycle_visual_review_v1 [--max-per-category N]
  Output: data/research/unified_lifecycle_visual_review_v1/
    index.html
    event_*.html
    manifest_v1.json
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RUNNER_NAME = "UNIFIED_LIFECYCLE_VISUAL_REVIEW_V1"
VERSION = "1.0.0"
DEFAULT_OUTPUT_DIR = Path("data/research/unified_lifecycle_visual_review_v1")
OUTCOME_ROWS_PATH = Path(
    "data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl"
)
MULTI_EVENT_PATH = Path(
    "data/research/continuation_gate_multi_event_v1/event_results_v1.jsonl"
)
REENTRY_PATH = Path(
    "data/research/weakness_reentry_block_v1/event_results_v1.csv"
)
RESIDUAL_PATH = Path(
    "data/research/parent_terminal_residual_exit_v1/event_results_v1.csv"
)

MAX_PER_CATEGORY = 5

# Category definitions for matched examples
CATEGORIES = [
    "CONTINUATION_SUPPORTED",
    "BREATH_CONFLICT",
    "REGIME_CONFLICT",
    "TERMINAL_CONFIRMED",
    "PARENT_CONTEXT_UNKNOWN",
    "REENTRY_BLOCKED_WEAKNESS",
    "REENTRY_CONTEXT_SUPPORTED",
]

# Horizons available in pre-computed data (4h candles each)
HORIZONS = [
    (0, "decision", 0.0),
    (1, "4h", None),
    (3, "12h", None),
    (6, "24h", None),
    (12, "48h", None),
    (18, "72h", None),
    (24, "96h", None),
]
HORIZON_FIELDS = {1: "fwd_return_1c", 3: "fwd_return_3c", 6: "fwd_return_6c",
                  12: "fwd_return_12c", 18: "fwd_return_18c", 24: "fwd_return_24c"}

# SVG dimensions
SVG_W = 820
SVG_H = 260
SVG_PAD_L = 50
SVG_PAD_R = 20
SVG_PAD_T = 20
SVG_PAD_B = 40
CHART_W = SVG_W - SVG_PAD_L - SVG_PAD_R
CHART_H = SVG_H - SVG_PAD_T - SVG_PAD_B

MAX_X_CANDLE = 24   # rightmost candle index
Y_RANGE_PCT = 10.0  # default y-axis range ±%

SYNTHETIC_NOTE = (
    "Child fib map layers (reload zones, invalidation, target levels) and parent fib map layers "
    "(parent terminal zone, parent lifecycle) are SYNTHETIC PROXIES derived from breath and "
    "regime signals. No actual fib map data available in pre-computed outcome dataset."
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  WARNING: {path} not found — skipping", flush=True)
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  WARNING: {path} not found — skipping", flush=True)
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _event_key(symbol: str, asof_ts: str) -> str:
    return f"{symbol}_{asof_ts}"


def build_unified_events(
    outcome_rows: list[dict],
    multi_event_rows: list[dict],
    reentry_rows: list[dict],
    residual_rows: list[dict],
) -> list[dict]:
    """
    Join all data sources on (symbol, asof_ts_utc).
    One unified dict per event.
    """
    # Multi-event: take C1 baseline rows (variant_type==BASELINE) for gate_state
    multi_by_key: dict[str, dict] = {}
    for r in multi_event_rows:
        if r.get("variant_type") == "BASELINE":
            k = _event_key(r["symbol"], r["asof_ts_utc"])
            multi_by_key[k] = r

    # Re-entry: one row per event
    reentry_by_key: dict[str, dict] = {}
    for r in reentry_rows:
        k = _event_key(r["symbol"], r["asof_ts_utc"])
        reentry_by_key[k] = r

    # Residual: V1 baseline rows
    residual_by_key: dict[str, dict] = {}
    for r in residual_rows:
        if r.get("variant_id") == "V1_CHILD_PARTIAL_TRIM":
            k = _event_key(r["symbol"], r["asof_ts_utc"])
            residual_by_key[k] = r

    unified: list[dict] = []
    seen: set[str] = set()

    for ev in outcome_rows:
        k = _event_key(ev["symbol"], ev["asof_ts_utc"])
        if k in seen:
            continue
        seen.add(k)

        me = multi_by_key.get(k, {})
        re_ = reentry_by_key.get(k, {})
        res = residual_by_key.get(k, {})

        gate_state = me.get("gate_state", "NOT_EVALUATED")
        parent_state = res.get("synthetic_parent_terminal_state", "PARENT_CONTEXT_UNKNOWN")
        reentry_state = re_.get("reentry_state", "NOT_EVALUATED")
        weakness_state = re_.get("synthetic_weakness_state", "WEAKNESS_UNKNOWN")
        reset_state = re_.get("synthetic_reset_state", "RESET_UNKNOWN")
        reclaim_state = re_.get("synthetic_reclaim_state", "RECLAIM_UNKNOWN")
        breath_alignment = me.get("breath_alignment") or re_.get("synthetic_breath_alignment", "UNKNOWN")
        market_regime = me.get("market_regime") or re_.get("synthetic_regime_state", "UNKNOWN")

        # Derive category membership
        categories: list[str] = []
        if gate_state == "CONTINUATION_SUPPORTED":
            categories.append("CONTINUATION_SUPPORTED")
        if gate_state == "BREATH_CONFLICT":
            categories.append("BREATH_CONFLICT")
        if gate_state == "REGIME_CONFLICT":
            categories.append("REGIME_CONFLICT")
        if parent_state == "TERMINAL_CONFIRMED":
            categories.append("TERMINAL_CONFIRMED")
        if parent_state == "PARENT_CONTEXT_UNKNOWN":
            categories.append("PARENT_CONTEXT_UNKNOWN")
        if reentry_state == "REENTRY_BLOCKED_WEAKNESS":
            categories.append("REENTRY_BLOCKED_WEAKNESS")
        if reentry_state == "REENTRY_CONTEXT_SUPPORTED":
            categories.append("REENTRY_CONTEXT_SUPPORTED")

        # Forward returns
        r1 = ev.get("fwd_return_1c") or 0.0
        r3 = ev.get("fwd_return_3c") or 0.0
        r6 = ev.get("fwd_return_6c") or 0.0
        r12 = ev.get("fwd_return_12c") or 0.0
        r18 = ev.get("fwd_return_18c") or 0.0
        r24 = ev.get("fwd_return_24c") or 0.0
        mfe = ev.get("max_runup_24c_from_asof_close")
        mae = ev.get("max_drawdown_24c_from_asof_close")

        # Outcome classification
        outcome_cls = "UNKNOWN"
        if mfe is not None and r6 is not None:
            if mfe <= 0:
                outcome_cls = "NO_MEANINGFUL_EXTENSION"
            elif mfe > 1.0:
                outcome_cls = "CLEAN_EXTENSION_AND_HOLD" if r6 > 0 else "EXTENSION_THEN_REVERSAL"
            elif r1 is not None and r1 > 0 and r6 <= 0:
                outcome_cls = "REJECTION_AFTER_TARGET"
            elif mfe > 0 and r6 > 0:
                outcome_cls = "CLOSE_HIGHER_WITHOUT_NEW_HIGH"
            else:
                outcome_cls = "HIGHER_HIGH_WITHOUT_HOLD"

        unified.append({
            "event_id": k,
            "symbol": ev["symbol"],
            "venue": ev.get("venue", "UNKNOWN"),
            "asof_ts_utc": ev["asof_ts_utc"],
            "close_price": ev.get("close_price"),
            # Breath/regime
            "market_breath_phase": ev.get("market_breath_phase", "UNKNOWN"),
            "market_breath_state": ev.get("market_breath_state", "UNKNOWN"),
            "market_breath_score": ev.get("market_breath_score"),
            "market_breath_confidence": ev.get("market_breath_confidence"),
            "breadth_alignment_score": ev.get("breadth_alignment_score"),
            "btc_alignment_score": ev.get("btc_alignment_score"),
            "momentum_score": ev.get("momentum_score"),
            "compression_score": ev.get("compression_score"),
            "expansion_score": ev.get("expansion_score"),
            "reversal_pressure_score": ev.get("reversal_pressure_score"),
            "relative_strength_score": ev.get("relative_strength_score"),
            # Gate states
            "gate_state": gate_state,
            "gate_applied": me.get("gate_applied", ""),
            "breath_alignment": breath_alignment,
            "market_regime": market_regime,
            "symbol_regime": me.get("symbol_regime", "UNKNOWN"),
            "live_valid": me.get("live_valid", ""),
            # Parent states
            "synthetic_parent_terminal_state": parent_state,
            "parent_constructive_state": res.get("synthetic_parent_constructive_state", "UNKNOWN"),
            # Re-entry states
            "reentry_state": reentry_state,
            "reentry_reason": re_.get("reentry_reason", ""),
            "weakness_state": weakness_state,
            "reset_state": reset_state,
            "reclaim_state": reclaim_state,
            "reload_zone_state": re_.get("synthetic_reload_zone_state", "UNKNOWN"),
            "native_short_4h": re_.get("synthetic_native_short_4h", "UNKNOWN"),
            "native_short_1h": re_.get("synthetic_native_short_1h", "UNKNOWN"),
            # Residual policy
            "residual_research_action": res.get("research_action", "NOT_EVALUATED"),
            # Forward returns
            "fwd_return_1c": r1, "fwd_return_3c": r3, "fwd_return_6c": r6,
            "fwd_return_12c": r12, "fwd_return_18c": r18, "fwd_return_24c": r24,
            "max_runup_24c_pct": mfe, "max_drawdown_24c_pct": mae,
            "outcome_classification": outcome_cls,
            # Category membership (list→json string for CSV compat)
            "categories": json.dumps(categories),
            "categories_list": categories,
        })

    return unified


# ---------------------------------------------------------------------------
# SVG chart generation
# ---------------------------------------------------------------------------

def _x_pos(candle_idx: int) -> float:
    """Map candle index 0..24 to SVG x pixel."""
    return SVG_PAD_L + (candle_idx / MAX_X_CANDLE) * CHART_W


def _y_pos(pct: float, y_min: float, y_max: float) -> float:
    """Map a percent-return value to SVG y pixel (inverted)."""
    if y_max == y_min:
        return SVG_PAD_T + CHART_H / 2
    frac = (pct - y_min) / (y_max - y_min)
    return SVG_PAD_T + CHART_H - frac * CHART_H


def _fmt(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def _color(v: Optional[float]) -> str:
    if v is None:
        return "#888"
    return "#2e9e4f" if v >= 0 else "#c0392b"


def _gate_color(gate: str) -> str:
    return {
        "CONTINUATION_SUPPORTED": "#2e9e4f",
        "BREATH_CONFLICT": "#e67e22",
        "REGIME_CONFLICT": "#c0392b",
        "CONTINUATION_WEAK": "#8e44ad",
        "CONTEXT_UNKNOWN": "#7f8c8d",
    }.get(gate, "#95a5a6")


def _state_color(state: str) -> str:
    return {
        "REENTRY_BLOCKED_WEAKNESS": "#c0392b",
        "REENTRY_BLOCKED_PARENT_TERMINAL": "#e74c3c",
        "RESET_REQUIRED": "#e67e22",
        "WATCH_REENTRY": "#f39c12",
        "REENTRY_CONTEXT_SUPPORTED": "#2e9e4f",
        "REENTRY_CONTEXT_CONFLICT": "#d35400",
        "CONTEXT_UNKNOWN": "#7f8c8d",
        "NOT_LIVE_VALID": "#95a5a6",
        "TERMINAL_CONFIRMED": "#c0392b",
        "TERMINAL_CANDIDATE": "#e67e22",
        "NOT_TERMINAL": "#2e9e4f",
        "PARENT_CONTEXT_UNKNOWN": "#7f8c8d",
        "REDUCE_TO_RESIDUAL": "#c0392b",
        "PARTIAL_TRIM_ONLY": "#2980b9",
        "HOLD_RUNNER": "#27ae60",
        "NO_EXIT_CONFIRMATION": "#7f8c8d",
    }.get(state, "#95a5a6")


def _svg_lifecycle_chart(ev: dict) -> str:
    r1 = ev.get("fwd_return_1c") or 0.0
    r3 = ev.get("fwd_return_3c") or 0.0
    r6 = ev.get("fwd_return_6c") or 0.0
    r12 = ev.get("fwd_return_12c") or 0.0
    r18 = ev.get("fwd_return_18c") or 0.0
    r24 = ev.get("fwd_return_24c") or 0.0
    mfe = ev.get("max_runup_24c_pct")
    mae = ev.get("max_drawdown_24c_pct")

    returns = [0.0, r1, r3, r6, r12, r18, r24]
    candle_xs = [0, 1, 3, 6, 12, 18, 24]

    all_vals = [v for v in returns + ([mfe] if mfe else []) + ([-mae] if mae else []) if v is not None]
    y_min = min(all_vals) if all_vals else -5.0
    y_max = max(all_vals) if all_vals else 5.0
    margin = max(1.0, (y_max - y_min) * 0.15)
    y_min -= margin
    y_max += margin

    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_W}" height="{SVG_H}" '
             f'style="background:#1a1a2e;border-radius:6px;font-family:monospace">']

    # Grid lines
    for pct in [0]:
        y = _y_pos(pct, y_min, y_max)
        lines.append(
            f'<line x1="{SVG_PAD_L}" y1="{y:.1f}" x2="{SVG_W-SVG_PAD_R}" y2="{y:.1f}" '
            f'stroke="#444" stroke-width="1" stroke-dasharray="3,3"/>'
        )

    # Candle checkpoint verticals
    for cx, label, stroke in [
        (1, "4h", "#3498db40"),
        (6, "24h", "#e67e2240"),
        (24, "96h", "#8e44ad40"),
    ]:
        x = _x_pos(cx)
        lines.append(
            f'<line x1="{x:.1f}" y1="{SVG_PAD_T}" x2="{x:.1f}" y2="{SVG_PAD_T+CHART_H}" '
            f'stroke="{stroke}" stroke-width="12"/>'
        )
        lines.append(
            f'<text x="{x:.1f}" y="{SVG_PAD_T-4}" text-anchor="middle" '
            f'fill="#888" font-size="9">{label}</text>'
        )

    # MFE dotted line (green)
    if mfe is not None:
        y = _y_pos(mfe, y_min, y_max)
        lines.append(
            f'<line x1="{SVG_PAD_L}" y1="{y:.1f}" x2="{SVG_W-SVG_PAD_R}" y2="{y:.1f}" '
            f'stroke="#2e9e4f" stroke-width="1.5" stroke-dasharray="6,3"/>'
        )
        lines.append(
            f'<text x="{SVG_PAD_L+4}" y="{y:.1f}-3" fill="#2e9e4f" font-size="9">'
            f'Max H {_fmt(mfe)}</text>'
        )

    # MAE dotted line (red) — mae stored as positive drawdown
    if mae is not None:
        y = _y_pos(-mae, y_min, y_max)
        lines.append(
            f'<line x1="{SVG_PAD_L}" y1="{y:.1f}" x2="{SVG_W-SVG_PAD_R}" y2="{y:.1f}" '
            f'stroke="#c0392b" stroke-width="1.5" stroke-dasharray="6,3"/>'
        )
        lines.append(
            f'<text x="{SVG_PAD_L+4}" y="{y:.1f}-3" fill="#c0392b" font-size="9">'
            f'Min L {_fmt(-mae)}</text>'
        )

    # Return trajectory (close-based)
    pts = " ".join(
        f"{_x_pos(cx):.1f},{_y_pos(rv, y_min, y_max):.1f}"
        for cx, rv in zip(candle_xs, returns)
        if rv is not None
    )
    lines.append(
        f'<polyline points="{pts}" fill="none" stroke="#3498db" stroke-width="2"/>'
    )

    # Dots at each candle
    for cx, rv in zip(candle_xs, returns):
        if rv is None:
            continue
        x = _x_pos(cx)
        y = _y_pos(rv, y_min, y_max)
        col = "#2e9e4f" if rv >= 0 else "#c0392b"
        lines.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{col}" stroke="#1a1a2e" stroke-width="1"/>'
        )
        if cx in (0, 1, 6, 24):
            label = _fmt(rv, 2)
            anchor = "end" if cx == 0 else "middle"
            ty = y - 8 if y > SVG_PAD_T + 20 else y + 14
            lines.append(
                f'<text x="{x:.1f}" y="{ty:.1f}" text-anchor="{anchor}" '
                f'fill="{col}" font-size="9">{html.escape(label)}</text>'
            )

    # Decision candle marker (vertical at 0)
    xd = _x_pos(0)
    lines.append(
        f'<line x1="{xd}" y1="{SVG_PAD_T}" x2="{xd}" y2="{SVG_PAD_T+CHART_H}" '
        f'stroke="#ecf0f1" stroke-width="1.5"/>'
    )
    lines.append(
        f'<text x="{xd+3}" y="{SVG_PAD_T+12}" fill="#ecf0f1" font-size="9">decision</text>'
    )

    # Y-axis labels
    for pct in [y_min + margin, 0.0, y_max - margin]:
        y = _y_pos(pct, y_min, y_max)
        if SVG_PAD_T <= y <= SVG_PAD_T + CHART_H:
            lines.append(
                f'<text x="{SVG_PAD_L-4}" y="{y+3:.1f}" text-anchor="end" '
                f'fill="#888" font-size="9">{pct:+.1f}%</text>'
            )

    # X-axis
    for cx, lbl, _ in HORIZONS:
        x = _x_pos(cx)
        lines.append(
            f'<text x="{x:.1f}" y="{SVG_PAD_T+CHART_H+14}" text-anchor="middle" '
            f'fill="#555" font-size="9">{cx}c</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Badge rendering
# ---------------------------------------------------------------------------

def _badge(label: str, value: str, color: str = "#2c3e50") -> str:
    esc_v = html.escape(str(value))
    return (
        f'<span style="display:inline-block;margin:3px 4px;padding:3px 8px;'
        f'border-radius:4px;background:{color};color:#ecf0f1;font-size:11px;'
        f'font-family:monospace">'
        f'<span style="opacity:.7">{html.escape(label)}: </span>'
        f'<strong>{esc_v}</strong></span>'
    )


def _score_bar(label: str, value: Optional[float], scale_min: float = -100.0,
               scale_max: float = 100.0) -> str:
    if value is None:
        return _badge(label, "n/a")
    pct = max(0.0, min(100.0, (value - scale_min) / (scale_max - scale_min) * 100))
    color = "#2e9e4f" if value >= 0 else "#c0392b"
    return (
        f'<div style="display:inline-block;margin:3px 4px;font-size:10px;'
        f'font-family:monospace;vertical-align:middle">'
        f'<span style="color:#888">{html.escape(label)}: </span>'
        f'<span style="color:{color};font-weight:bold">{value:+.1f}</span>'
        f'<div style="display:inline-block;width:60px;height:6px;background:#2c3e50;'
        f'margin-left:4px;border-radius:2px;vertical-align:middle">'
        f'<div style="width:{pct:.0f}%;height:100%;background:{color};border-radius:2px"></div>'
        f'</div></div>'
    )


# ---------------------------------------------------------------------------
# HTML event page
# ---------------------------------------------------------------------------

def _html_event_page(ev: dict, page_href: str = "") -> str:
    symbol = ev["symbol"]
    asof = ev["asof_ts_utc"]
    gate = ev["gate_state"]
    parent = ev["synthetic_parent_terminal_state"]
    reentry = ev["reentry_state"]
    outcome = ev["outcome_classification"]

    svg = _svg_lifecycle_chart(ev)

    r6 = ev.get("fwd_return_6c") or 0.0
    r24 = ev.get("fwd_return_24c") or 0.0
    mfe = ev.get("max_runup_24c_pct")
    mae = ev.get("max_drawdown_24c_pct")
    gave_back = round(mfe - r24, 2) if mfe is not None and r24 is not None else None

    categories = ev.get("categories_list", []) or json.loads(ev.get("categories", "[]"))

    def _section(title: str, content: str) -> str:
        return (
            f'<div style="margin:12px 0">'
            f'<div style="color:#7f8c8d;font-size:10px;font-family:monospace;'
            f'text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">{title}</div>'
            f'{content}</div>'
        )

    # Breath layer
    breath_section = _section("Breath Layer", (
        _badge("phase", ev.get("market_breath_phase", "?"), color="#16213e") +
        _badge("state", ev.get("market_breath_state", "?"), color="#16213e") +
        _score_bar("breath_score", ev.get("market_breath_score"), 0, 100) +
        _score_bar("alignment", ev.get("breadth_alignment_score"), -100, 100) +
        _score_bar("momentum", ev.get("momentum_score"), -100, 100) +
        _score_bar("reversal_pressure", ev.get("reversal_pressure_score"), 0, 100) +
        _score_bar("compression", ev.get("compression_score"), 0, 70) +
        _score_bar("expansion", ev.get("expansion_score"), 0, 100) +
        "<br/>" +
        _badge("breath_alignment", ev.get("breath_alignment", "?"), color="#1a1a4e") +
        _badge("breath_confidence", str(ev.get("market_breath_confidence", "?")), color="#1a1a4e")
    ))

    # Regime layer
    regime_section = _section("Regime Layer", (
        _badge("market_regime", ev.get("market_regime", "?"),
               color=_state_color(str(ev.get("market_regime", "")))) +
        _badge("symbol_regime", ev.get("symbol_regime", "?"), color="#16213e") +
        _score_bar("relative_strength", ev.get("relative_strength_score"), -100, 100) +
        _score_bar("btc_alignment", ev.get("btc_alignment_score"), -100, 100)
    ))

    # Child fib map layer (synthetic)
    child_section = _section("Child Fib Map (Synthetic Proxy)", (
        _badge("native_short_4h", ev.get("native_short_4h", "?"), color="#2c2c4e") +
        _badge("native_short_1h", ev.get("native_short_1h", "?"), color="#2c2c4e") +
        _badge("weakness_state", ev.get("weakness_state", "?"),
               color=_state_color(str(ev.get("weakness_state", "")))) +
        _badge("reload_zone_state", ev.get("reload_zone_state", "?"), color="#2c2c4e") +
        '<br/><span style="color:#7f8c8d;font-size:9px;font-family:monospace">'
        + html.escape(SYNTHETIC_NOTE[:100] + "...") + '</span>'
    ))

    # Parent fib map layer (synthetic)
    parent_section = _section("Parent Fib Map (Synthetic Proxy)", (
        _badge("parent_terminal_state", parent,
               color=_state_color(parent)) +
        _badge("parent_constructive_state", ev.get("parent_constructive_state", "?"),
               color=_state_color(str(ev.get("parent_constructive_state", "")))) +
        _badge("residual_action", ev.get("residual_research_action", "?"),
               color=_state_color(str(ev.get("residual_research_action", ""))))
    ))

    # Re-entry layer
    reentry_section = _section("Re-entry Gate", (
        _badge("reentry_state", reentry,
               color=_state_color(reentry)) +
        _badge("reset_state", ev.get("reset_state", "?"), color="#16213e") +
        _badge("reclaim_state", ev.get("reclaim_state", "?"), color="#16213e") +
        "<br/>" +
        f'<span style="color:#888;font-size:9px;font-family:monospace">'
        f'{html.escape(ev.get("reentry_reason", "")[:120])}</span>'
    ))

    # Gate state (continuation)
    gate_section = _section("Continuation Gate", (
        _badge("gate_state", gate, color=_gate_color(gate)) +
        _badge("gate_applied", str(ev.get("gate_applied", "?")), color="#16213e") +
        _badge("live_valid", str(ev.get("live_valid", "?")), color="#16213e")
    ))

    # Outcomes
    outcome_section = _section("Outcomes", (
        _badge("outcome_cls", outcome, color="#16213e") +
        _badge("r1(4h)", _fmt(ev.get("fwd_return_1c")), color=_color(ev.get("fwd_return_1c"))) +
        _badge("r6(24h)", _fmt(ev.get("fwd_return_6c")), color=_color(ev.get("fwd_return_6c"))) +
        _badge("r12(48h)", _fmt(ev.get("fwd_return_12c")), color=_color(ev.get("fwd_return_12c"))) +
        _badge("r24(96h)", _fmt(ev.get("fwd_return_24c")), color=_color(ev.get("fwd_return_24c"))) +
        "<br/>" +
        _badge("MFE(96h)", _fmt(mfe), color="#1a4e1a" if mfe and mfe > 0 else "#16213e") +
        _badge("MAE(96h)", _fmt(-mae if mae else None), color="#4e1a1a" if mae and mae > 0 else "#16213e") +
        _badge("gave_back", _fmt(gave_back), color=_color(-gave_back if gave_back else None))
    ))

    # Categories
    cat_html = "".join(
        f'<span style="display:inline-block;margin:2px 3px;padding:2px 7px;'
        f'border-radius:3px;background:#0d3349;color:#3498db;font-size:10px;'
        f'font-family:monospace">{html.escape(c)}</span>'
        for c in categories
    )

    # Provenance
    prov_section = _section("Source Provenance", (
        _badge("asof_ts_utc", asof, color="#16213e") +
        _badge("close_price", str(ev.get("close_price", "?")), color="#16213e") +
        _badge("venue", ev.get("venue", "?"), color="#16213e") +
        '<br/><span style="color:#7f8c8d;font-size:9px;font-family:monospace">' +
        "All timestamps are UTC. Synthetic proxies labeled above. "
        "No future evidence appears before decision timestamp (asof_ts_utc = candle 0)."
        + '</span>'
    ))

    back_link = '<a href="index.html" style="color:#3498db;font-size:11px;text-decoration:none">← Back to index</a>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(symbol)} {asof[:10]} — Lifecycle Review</title>
<style>
body{{background:#0d1117;color:#ecf0f1;font-family:monospace;font-size:13px;margin:0;padding:20px}}
h1{{font-size:16px;color:#ecf0f1;margin-bottom:4px}}
h2{{font-size:12px;color:#7f8c8d;font-weight:normal;margin-top:0}}
.categories{{margin:8px 0}}
.chart{{margin:16px 0}}
.layers{{margin:8px 0;padding:12px;background:#16213e;border-radius:6px}}
</style>
</head>
<body>
{back_link}
<h1>{html.escape(symbol)} — {html.escape(asof[:16])} UTC</h1>
<h2>close={ev.get('close_price','?')} · venue={html.escape(ev.get('venue','?'))}</h2>
<div class="categories">{cat_html}</div>
<div class="chart">{svg}</div>
<div class="layers">
{gate_section}
{breath_section}
{regime_section}
{child_section}
{parent_section}
{reentry_section}
{outcome_section}
{prov_section}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

def _html_index_page(
    unified_events: list[dict],
    event_pages: dict[str, str],  # event_id → page filename
    categories_selected: list[str],
) -> str:
    # Build row data for filtering
    rows_js = []
    for ev in unified_events:
        if ev["event_id"] not in event_pages:
            continue
        cats = ev.get("categories_list") or json.loads(ev.get("categories", "[]"))
        rows_js.append({
            "event_id": ev["event_id"],
            "symbol": ev["symbol"],
            "date": ev["asof_ts_utc"][:10],
            "gate_state": ev["gate_state"],
            "parent_state": ev["synthetic_parent_terminal_state"],
            "reentry_state": ev["reentry_state"],
            "breath_phase": ev["market_breath_phase"],
            "breath_alignment": ev.get("breath_alignment", "?"),
            "regime": ev.get("market_regime", "?"),
            "outcome_cls": ev["outcome_classification"],
            "r6_pos": (ev.get("fwd_return_6c") or 0) >= 0,
            "categories": cats,
            "page": event_pages[ev["event_id"]],
            "r6": round(ev.get("fwd_return_6c") or 0, 2),
            "r24": round(ev.get("fwd_return_24c") or 0, 2),
            "mfe": round(ev.get("max_runup_24c_pct") or 0, 2),
        })

    rows_json = json.dumps(rows_js, ensure_ascii=False)
    n_pages = len(event_pages)
    categories_js = json.dumps(CATEGORIES)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Unified Lifecycle Visual Review v1</title>
<style>
body{{background:#0d1117;color:#ecf0f1;font-family:monospace;font-size:12px;margin:0;padding:20px}}
h1{{font-size:16px;color:#ecf0f1}}
.filters{{background:#16213e;padding:12px;border-radius:6px;margin:12px 0;display:flex;flex-wrap:wrap;gap:8px}}
.filter-group{{display:flex;flex-direction:column;gap:4px}}
label{{font-size:10px;color:#7f8c8d}}
select,input{{background:#0d1117;color:#ecf0f1;border:1px solid #2c3e50;border-radius:3px;
  padding:3px 6px;font-size:11px;font-family:monospace}}
table{{border-collapse:collapse;width:100%;margin-top:12px}}
th{{background:#16213e;color:#7f8c8d;text-align:left;padding:6px 8px;font-size:10px;
   text-transform:uppercase;letter-spacing:0.5px;position:sticky;top:0}}
td{{padding:5px 8px;border-bottom:1px solid #16213e;vertical-align:middle}}
tr:hover td{{background:#16213e}}
a{{color:#3498db;text-decoration:none}}
a:hover{{text-decoration:underline}}
.badge{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px}}
.pos{{color:#2e9e4f}} .neg{{color:#c0392b}} .neu{{color:#888}}
.count{{color:#7f8c8d;font-size:11px}}
</style>
</head>
<body>
<h1>Unified Lifecycle Visual Review v1</h1>
<p style="color:#7f8c8d;font-size:11px">
  {n_pages} event pages across {len(categories_selected)} categories.
  All synthetic proxies. No actual fib map data. Research-only.
  <br>
  Regenerate: <code>python -m src.research.run_unified_lifecycle_visual_review_v1</code>
</p>
<div class="filters">
  <div class="filter-group">
    <label>Symbol</label>
    <select id="f-symbol" onchange="applyFilters()">
      <option value="">All</option>
    </select>
  </div>
  <div class="filter-group">
    <label>Category</label>
    <select id="f-category" onchange="applyFilters()">
      <option value="">All</option>
    </select>
  </div>
  <div class="filter-group">
    <label>Gate State</label>
    <select id="f-gate" onchange="applyFilters()">
      <option value="">All</option>
    </select>
  </div>
  <div class="filter-group">
    <label>Parent State</label>
    <select id="f-parent" onchange="applyFilters()">
      <option value="">All</option>
    </select>
  </div>
  <div class="filter-group">
    <label>Re-entry State</label>
    <select id="f-reentry" onchange="applyFilters()">
      <option value="">All</option>
    </select>
  </div>
  <div class="filter-group">
    <label>Breath Phase</label>
    <select id="f-breath" onchange="applyFilters()">
      <option value="">All</option>
    </select>
  </div>
  <div class="filter-group">
    <label>Outcome (r6)</label>
    <select id="f-outcome" onchange="applyFilters()">
      <option value="">All</option>
      <option value="pos">Positive r6</option>
      <option value="neg">Negative r6</option>
    </select>
  </div>
  <div class="filter-group">
    <label>Outcome Classification</label>
    <select id="f-outcls" onchange="applyFilters()">
      <option value="">All</option>
    </select>
  </div>
</div>
<span class="count" id="count-label">{n_pages} events</span>
<table id="event-table">
<thead>
<tr>
  <th>Symbol</th><th>Date</th><th>Gate State</th><th>Parent</th>
  <th>Re-entry</th><th>Breath Phase</th><th>Regime</th>
  <th>Outcome Cls</th><th>r6</th><th>r24</th><th>MFE</th><th>Categories</th>
</tr>
</thead>
<tbody id="table-body"></tbody>
</table>
<script>
const ROWS = {rows_json};
const CATEGORIES = {categories_js};

function gateColor(g) {{
  const m = {{CONTINUATION_SUPPORTED:"#2e9e4f",BREATH_CONFLICT:"#e67e22",
    REGIME_CONFLICT:"#c0392b",CONTINUATION_WEAK:"#8e44ad",CONTEXT_UNKNOWN:"#7f8c8d"}};
  return m[g] || "#95a5a6";
}}
function stateColor(s) {{
  const m = {{REENTRY_BLOCKED_WEAKNESS:"#c0392b",REENTRY_BLOCKED_PARENT_TERMINAL:"#e74c3c",
    WATCH_REENTRY:"#f39c12",REENTRY_CONTEXT_SUPPORTED:"#2e9e4f",
    CONTEXT_UNKNOWN:"#7f8c8d",TERMINAL_CONFIRMED:"#c0392b",NOT_TERMINAL:"#2e9e4f",
    PARENT_CONTEXT_UNKNOWN:"#7f8c8d"}};
  return m[s] || "#95a5a6";
}}
function badge(val, color) {{
  return `<span class="badge" style="background:${{color || "#2c3e50"}};color:#ecf0f1">${{val}}</span>`;
}}
function fmtPct(v) {{
  const cls = v >= 0 ? "pos" : "neg";
  const sign = v >= 0 ? "+" : "";
  return `<span class="${{cls}}">${{sign}}${{v.toFixed(2)}}%</span>`;
}}

function populateSelects() {{
  const filters = {{
    "f-symbol": [...new Set(ROWS.map(r => r.symbol))].sort(),
    "f-gate": [...new Set(ROWS.map(r => r.gate_state))].sort(),
    "f-parent": [...new Set(ROWS.map(r => r.parent_state))].sort(),
    "f-reentry": [...new Set(ROWS.map(r => r.reentry_state))].sort(),
    "f-breath": [...new Set(ROWS.map(r => r.breath_phase))].sort(),
    "f-outcls": [...new Set(ROWS.map(r => r.outcome_cls))].sort(),
  }};
  for (const [id, vals] of Object.entries(filters)) {{
    const sel = document.getElementById(id);
    vals.forEach(v => {{
      const o = document.createElement("option");
      o.value = v; o.text = v;
      sel.appendChild(o);
    }});
  }}
  const catSel = document.getElementById("f-category");
  CATEGORIES.forEach(c => {{
    const o = document.createElement("option");
    o.value = c; o.text = c;
    catSel.appendChild(o);
  }});
}}

function applyFilters() {{
  const sym = document.getElementById("f-symbol").value;
  const cat = document.getElementById("f-category").value;
  const gate = document.getElementById("f-gate").value;
  const parent = document.getElementById("f-parent").value;
  const reentry = document.getElementById("f-reentry").value;
  const breath = document.getElementById("f-breath").value;
  const outcome = document.getElementById("f-outcome").value;
  const outcls = document.getElementById("f-outcls").value;

  const filtered = ROWS.filter(r => {{
    if (sym && r.symbol !== sym) return false;
    if (cat && !r.categories.includes(cat)) return false;
    if (gate && r.gate_state !== gate) return false;
    if (parent && r.parent_state !== parent) return false;
    if (reentry && r.reentry_state !== reentry) return false;
    if (breath && r.breath_phase !== breath) return false;
    if (outcome === "pos" && !r.r6_pos) return false;
    if (outcome === "neg" && r.r6_pos) return false;
    if (outcls && r.outcome_cls !== outcls) return false;
    return true;
  }});

  renderRows(filtered);
  document.getElementById("count-label").textContent = filtered.length + " events";
}}

function renderRows(rows) {{
  const tbody = document.getElementById("table-body");
  tbody.innerHTML = "";
  rows.forEach(r => {{
    const cats = r.categories.map(c =>
      `<span style="display:inline-block;margin:1px 2px;padding:1px 5px;border-radius:2px;`
      + `background:#0d3349;color:#3498db;font-size:9px">${{c}}</span>`
    ).join("");
    const tr = `<tr>
      <td><a href="${{r.page}}">${{r.symbol}}</a></td>
      <td style="color:#888">${{r.date}}</td>
      <td>${{badge(r.gate_state, gateColor(r.gate_state))}}</td>
      <td>${{badge(r.parent_state, stateColor(r.parent_state))}}</td>
      <td>${{badge(r.reentry_state, stateColor(r.reentry_state))}}</td>
      <td style="color:#7f8c8d">${{r.breath_phase}}</td>
      <td style="color:#888">${{r.regime}}</td>
      <td style="color:#7f8c8d;font-size:10px">${{r.outcome_cls}}</td>
      <td>${{fmtPct(r.r6)}}</td>
      <td>${{fmtPct(r.r24)}}</td>
      <td class="${{r.mfe > 0 ? 'pos' : 'neu'}}">${{r.mfe > 0 ? '+' : ''}}${{r.mfe.toFixed(2)}}%</td>
      <td>${{cats}}</td>
    </tr>`;
    tbody.insertAdjacentHTML("beforeend", tr);
  }});
}}

populateSelects();
renderRows(ROWS);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Event selection
# ---------------------------------------------------------------------------

def select_matched_examples(
    unified_events: list[dict],
    max_per_category: int = MAX_PER_CATEGORY,
) -> dict[str, list[dict]]:
    """
    Select up to max_per_category events per category.
    Prefer events with more categories for richness.
    """
    category_events: dict[str, list[dict]] = {cat: [] for cat in CATEGORIES}
    for ev in unified_events:
        cats = ev.get("categories_list") or json.loads(ev.get("categories", "[]"))
        for cat in cats:
            if cat in category_events:
                category_events[cat].append(ev)

    selected: dict[str, list[dict]] = {}
    for cat, events in category_events.items():
        # Sort: prefer events with more categories (richer examples), then by symbol
        events_sorted = sorted(
            events,
            key=lambda e: (-len(e.get("categories_list") or []), e["symbol"]),
        )
        selected[cat] = events_sorted[:max_per_category]

    return selected


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(
    outcome_rows_path: Path = OUTCOME_ROWS_PATH,
    multi_event_path: Path = MULTI_EVENT_PATH,
    reentry_path: Path = REENTRY_PATH,
    residual_path: Path = RESIDUAL_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_per_category: int = MAX_PER_CATEGORY,
    dry_run: bool = False,
) -> int:
    print(f"STARTED {RUNNER_NAME} {VERSION}", flush=True)
    print(f"  output_dir={output_dir}", flush=True)
    print(f"  max_per_category={max_per_category}", flush=True)

    # Phase 1: Load data
    print("\nPhase 1: Loading data sources...", flush=True)
    outcome_rows = _load_jsonl(outcome_rows_path)
    multi_event_rows = _load_jsonl(multi_event_path)
    reentry_rows = _load_csv(reentry_path)
    residual_rows = _load_csv(residual_path)
    print(
        f"  outcome_rows={len(outcome_rows)}  multi_event={len(multi_event_rows)}  "
        f"reentry={len(reentry_rows)}  residual={len(residual_rows)}",
        flush=True,
    )

    # Phase 2: Build unified events
    print("\nPhase 2: Building unified event records...", flush=True)
    unified = build_unified_events(outcome_rows, multi_event_rows, reentry_rows, residual_rows)
    print(f"  Unified events: {len(unified)}", flush=True)

    # Phase 3: Select matched examples
    print("\nPhase 3: Selecting matched examples...", flush=True)
    selected = select_matched_examples(unified, max_per_category)
    for cat, events in selected.items():
        print(f"  {cat:35s}: {len(events)} events", flush=True)
        if len(events) < 2:
            print(f"    WARNING: insufficient sample for {cat}", flush=True)

    # Collect all events to render (deduplicated)
    all_selected: dict[str, dict] = {}
    for events in selected.values():
        for ev in events:
            all_selected[ev["event_id"]] = ev
    n_pages = len(all_selected)
    print(f"  Total unique event pages: {n_pages}", flush=True)

    if n_pages == 0:
        print("WARNING: no events selected; check that input data sources exist", flush=True)

    if dry_run:
        print("\nDRY RUN — skipping file writes", flush=True)
        print(f"FINISHED {RUNNER_NAME} (dry run)")
        return 0

    # Phase 4: Write event pages
    print("\nPhase 4: Writing event pages...", flush=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_pages: dict[str, str] = {}

    for ev in all_selected.values():
        # Build safe filename
        ts_safe = ev["asof_ts_utc"][:16].replace(":", "").replace("T", "_").replace(" ", "_")
        fname = f"event_{ev['symbol']}_{ts_safe}.html"
        fpath = output_dir / fname
        content = _html_event_page(ev)
        fpath.write_text(content, encoding="utf-8")
        event_pages[ev["event_id"]] = fname

    print(f"  Wrote {len(event_pages)} event pages", flush=True)

    # Phase 5: Write index
    print("\nPhase 5: Writing index...", flush=True)
    index_path = output_dir / "index.html"
    index_html = _html_index_page(unified, event_pages, CATEGORIES)
    index_path.write_text(index_html, encoding="utf-8")
    print(f"  Index: {index_path}", flush=True)

    # Phase 6: Write manifest
    manifest = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "n_unified_events": len(unified),
        "n_event_pages": n_pages,
        "categories": {cat: len(evs) for cat, evs in selected.items()},
        "input_sources": {
            "outcome_rows": str(outcome_rows_path),
            "multi_event": str(multi_event_path),
            "reentry": str(reentry_path),
            "residual": str(residual_path),
        },
        "output_dir": str(output_dir),
        "index": "index.html",
        "regenerate_cmd": "python -m src.research.run_unified_lifecycle_visual_review_v1",
        "notes": {
            "synthetic_proxy": SYNTHETIC_NOTE,
            "no_future_evidence": (
                "All event pages use asof_ts_utc as the decision timestamp (candle 0). "
                "Forward returns are the research outcome only; they do not appear "
                "in any gate state logic."
            ),
            "no_fs_paths_in_hrefs": (
                "All href attributes use relative paths (event_*.html, index.html). "
                "No absolute filesystem paths in public HTML."
            ),
            "filters": (
                "Index page filters: symbol, date, gate_state, parent_state, reentry_state, "
                "breath_phase, breath_alignment, regime, outcome_classification, r6 pos/neg. "
                "JavaScript-only; no server required."
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
    mp = output_dir / "manifest_v1.json"
    mp.write_text(json.dumps(manifest, indent=2))

    print(f"\nFINISHED {RUNNER_NAME}")
    print(f"  index.html: {index_path}", flush=True)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"{RUNNER_NAME} — unified lifecycle visual review"
    )
    parser.add_argument("--outcome-rows", default=str(OUTCOME_ROWS_PATH))
    parser.add_argument("--multi-event", default=str(MULTI_EVENT_PATH))
    parser.add_argument("--reentry", default=str(REENTRY_PATH))
    parser.add_argument("--residual", default=str(RESIDUAL_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-per-category", type=int, default=MAX_PER_CATEGORY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(
        outcome_rows_path=Path(args.outcome_rows),
        multi_event_path=Path(args.multi_event),
        reentry_path=Path(args.reentry),
        residual_path=Path(args.residual),
        output_dir=Path(args.output_dir),
        max_per_category=args.max_per_category,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
