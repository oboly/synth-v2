"""
run_parent_terminal_residual_exit_v1.py
=========================================
Research runner: Parent-terminal residual exit policy evaluation.

Policy Hypothesis
-----------------
  Child-horizon target touch permits partial trim only.
  Near-full reduction requires valid parent-horizon terminal confirmation.
  Parent TERMINAL_CONFIRMED + weakness/rejection → REDUCE_TO_RESIDUAL
    (default residual = 10% of position).
  Parent UNKNOWN or stale → fail closed; fall back to child partial-trim baseline.
  True full exit requires explicit residual_pct=0 (benchmark/profile policy only).
  residual_target_pct belongs to strategy/advice intent; never execution_planner.

Parent Terminal States
----------------------
  TERMINAL_CONFIRMED      Parent terminal zone confirmed; reduction eligible with weakness.
  TERMINAL_CANDIDATE      Approaching terminal; wait for confirmation.
  NOT_TERMINAL            Extension running; preserve runner.
  PARENT_MAP_COMPLETED    Full wave map completed; treated as TERMINAL_CONFIRMED.
  PARENT_MAP_INVALIDATED  Map invalidated; no exit confirmation.
  PARENT_CONTEXT_STALE    Context exists but too old; fail closed.
  PARENT_CONTEXT_UNKNOWN  No parent context available; fail closed.

Research Action States
----------------------
  PARTIAL_TRIM_ONLY       Trim child tranche only; no near-full exit.
  HOLD_RUNNER             Preserve more runner; no near-full exit.
  REDUCE_TO_RESIDUAL      Reduce to residual (default 10%); parent-confirmed only.
  NO_EXIT_CONFIRMATION    Map invalidated; withhold exit action.
  NOT_LIVE_VALID          Parent context absent or future; fall back; not live valid.

Policy Variants
---------------
  V1  CHILD_PARTIAL_TRIM    Baseline: always fwd_return_1c.
  V2  RESIDUAL_10           90% at 6c, 10% at 24c when TERMINAL_CONFIRMED + weakness.
  V3  RESIDUAL_5            95% at 6c, 5% at 24c when TERMINAL_CONFIRMED + weakness.
  V4  FULL_EXIT_BENCHMARK   100% at 6c (residual_pct=0; not live valid; benchmark only).
  V5  BUY_AND_HOLD          fwd_return_24c; always held regardless of gate.

Synthetic Parent State Derivation
----------------------------------
  Actual parent TF chart analysis (parent_map_state, parent_terminal_zone_state) does NOT
  exist in the pre-computed outcome_rows_v1 dataset. Synthetic proxies are assigned from
  market_breath_phase and market_breath_state:

    EXHALE_EXPANSION  / INHALE_ACCUMULATION  → NOT_TERMINAL
    OVERBREATH_EXTENSION / HOLD_COMPRESSION  → TERMINAL_CANDIDATE
    COLLAPSE_RESET                           → TERMINAL_CONFIRMED
    NEUTRAL_TRANSITION                       → PARENT_CONTEXT_UNKNOWN (87% of dataset)

  Weakness confirmation:
    COLLAPSE_RESET + RESET state → WEAKNESS_CONFIRMED
    All others                   → WEAKNESS_NOT_CONFIRMED or WEAKNESS_UNKNOWN

  All synthetic state assignments are labeled SYNTHETIC_PROXY in output.
  Do not claim parent terminal benefit if coverage is absent or degenerate.

Strict Historical Matching
--------------------------
  evaluate_parent_terminal_policy() rejects any parent_context_ts_utc > decision_ts_utc.
  Synthetic states derive only from the event's own row (point-in-time by construction).

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
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Parent terminal states
# ---------------------------------------------------------------------------
PARENT_TERMINAL_CONFIRMED = "TERMINAL_CONFIRMED"
PARENT_TERMINAL_CANDIDATE = "TERMINAL_CANDIDATE"
PARENT_NOT_TERMINAL = "NOT_TERMINAL"
PARENT_MAP_COMPLETED = "PARENT_MAP_COMPLETED"
PARENT_MAP_INVALIDATED = "PARENT_MAP_INVALIDATED"
PARENT_CONTEXT_STALE = "PARENT_CONTEXT_STALE"
PARENT_CONTEXT_UNKNOWN = "PARENT_CONTEXT_UNKNOWN"

_TERMINAL_STATES = frozenset({PARENT_TERMINAL_CONFIRMED, PARENT_MAP_COMPLETED})
_CLOSED_STATES = frozenset({PARENT_CONTEXT_UNKNOWN, PARENT_CONTEXT_STALE})

# ---------------------------------------------------------------------------
# Research action states
# ---------------------------------------------------------------------------
ACTION_PARTIAL_TRIM_ONLY = "PARTIAL_TRIM_ONLY"
ACTION_HOLD_RUNNER = "HOLD_RUNNER"
ACTION_REDUCE_TO_RESIDUAL = "REDUCE_TO_RESIDUAL"
ACTION_NO_EXIT_CONFIRMATION = "NO_EXIT_CONFIRMATION"
ACTION_NOT_LIVE_VALID = "NOT_LIVE_VALID"

# ---------------------------------------------------------------------------
# Weakness confirmation states
# ---------------------------------------------------------------------------
WEAKNESS_CONFIRMED = "WEAKNESS_CONFIRMED"
WEAKNESS_NOT_CONFIRMED = "WEAKNESS_NOT_CONFIRMED"
WEAKNESS_UNKNOWN = "WEAKNESS_UNKNOWN"

# ---------------------------------------------------------------------------
# Variant IDs
# ---------------------------------------------------------------------------
VARIANT_CHILD_PARTIAL_TRIM = "V1_CHILD_PARTIAL_TRIM"
VARIANT_RESIDUAL_10 = "V2_RESIDUAL_10"
VARIANT_RESIDUAL_5 = "V3_RESIDUAL_5"
VARIANT_FULL_EXIT_BENCHMARK = "V4_FULL_EXIT_BENCHMARK"
VARIANT_BUY_AND_HOLD = "V5_BUY_AND_HOLD"

# Variant residual percentages (None = not applicable)
_VARIANT_SPECS: list[tuple[str, Optional[float]]] = [
    (VARIANT_CHILD_PARTIAL_TRIM, None),
    (VARIANT_RESIDUAL_10, 10.0),
    (VARIANT_RESIDUAL_5, 5.0),
    (VARIANT_FULL_EXIT_BENCHMARK, 0.0),
    (VARIANT_BUY_AND_HOLD, None),
]

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------
RUNNER_NAME = "PARENT_TERMINAL_RESIDUAL_EXIT_V1"
VERSION = "1.0.0"
DEFAULT_RESIDUAL_PCT = 10.0
MAX_PARENT_CONTEXT_AGE_MINUTES = 480       # 8h
REDUCTION_HORIZON_CANDLES = 6             # 24h — bulk reduction point
RESIDUAL_HORIZON_CANDLES = 24             # 96h — residual hold point
MAX_EVENTS = 2500
DEFAULT_OUTPUT_DIR = Path("data/research/parent_terminal_residual_exit_v1")
OUTCOME_ROWS_PATH = Path(
    "data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl"
)

SYNTHETIC_PROXY_NOTE = (
    "SYNTHETIC_PROXY: parent_terminal_state derived from market_breath_phase. "
    "No actual parent TF chart data in pre-computed outcome dataset. "
    "Do not treat as validated parent map analysis."
)

# Synthetic parent state mapping from market_breath_phase
_BREATH_PHASE_TO_PARENT_STATE: dict[str, str] = {
    "EXHALE_EXPANSION": PARENT_NOT_TERMINAL,
    "INHALE_ACCUMULATION": PARENT_NOT_TERMINAL,
    "OVERBREATH_EXTENSION": PARENT_TERMINAL_CANDIDATE,
    "HOLD_COMPRESSION": PARENT_TERMINAL_CANDIDATE,
    "COLLAPSE_RESET": PARENT_TERMINAL_CONFIRMED,
    "NEUTRAL_TRANSITION": PARENT_CONTEXT_UNKNOWN,
}

# Synthetic weakness mapping
# CONFIRMED state in expansion phases means "expansion confirmed", not weakness.
# RESET state in COLLAPSE_RESET means the reset/rejection is confirmed.
_PHASE_STATE_TO_WEAKNESS: dict[tuple[str, str], str] = {
    ("COLLAPSE_RESET", "RESET"): WEAKNESS_CONFIRMED,
}
_DEFAULT_WEAKNESS_FOR_PHASE: dict[str, str] = {
    "EXHALE_EXPANSION": WEAKNESS_NOT_CONFIRMED,
    "INHALE_ACCUMULATION": WEAKNESS_NOT_CONFIRMED,
    "OVERBREATH_EXTENSION": WEAKNESS_NOT_CONFIRMED,
    "HOLD_COMPRESSION": WEAKNESS_NOT_CONFIRMED,
    "COLLAPSE_RESET": WEAKNESS_NOT_CONFIRMED,
    "NEUTRAL_TRANSITION": WEAKNESS_UNKNOWN,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyResult:
    parent_terminal_state: str
    parent_terminal_reason: str
    parent_child_confluence_state: str
    weakness_confirmation_state: str
    requested_reduce_pct: float
    residual_target_pct: float
    research_action: str
    live_valid: bool
    fallback_policy: Optional[str]
    fallback_reason: Optional[str]
    source_refs: str


# ---------------------------------------------------------------------------
# Core policy function (pure — no DB, no executor, no execution_planner)
# ---------------------------------------------------------------------------

def evaluate_parent_terminal_policy(
    parent_terminal_state: str,
    weakness_confirmation_state: str,
    decision_ts_utc: Optional[datetime] = None,
    parent_context_ts_utc: Optional[datetime] = None,
    parent_context_age_minutes: Optional[float] = None,
    max_parent_context_age_minutes: int = MAX_PARENT_CONTEXT_AGE_MINUTES,
    residual_target_pct: float = DEFAULT_RESIDUAL_PCT,
    child_target_state: str = "CHILD_TARGET_TOUCHED",
    source_refs: str = "",
) -> PolicyResult:
    """
    Deterministic parent-terminal residual exit policy.

    Rules (in priority order):
      1. Future parent context → rejected (no future leakage).
      2. Stale parent context → NOT_LIVE_VALID; fall back to child partial-trim.
      3. PARENT_CONTEXT_UNKNOWN → NOT_LIVE_VALID; fall back to child partial-trim.
      4. PARENT_MAP_INVALIDATED → NO_EXIT_CONFIRMATION.
      5. NOT_TERMINAL → PARTIAL_TRIM_ONLY; preserve runner.
      6. TERMINAL_CANDIDATE → PARTIAL_TRIM_ONLY; wait for confirmation.
      7. TERMINAL_CONFIRMED/PARENT_MAP_COMPLETED + weakness → REDUCE_TO_RESIDUAL.
      8. TERMINAL_CONFIRMED/PARENT_MAP_COMPLETED without weakness → HOLD_RUNNER.
      9. Child target alone (fallthrough) → PARTIAL_TRIM_ONLY.

    residual_pct=0 is a benchmark flag: REDUCE_TO_RESIDUAL fires but live_valid=False.
    parent_context_ts_utc > decision_ts_utc is a future-leakage violation.
    """
    # Rule 1: Reject future parent context (no future leakage)
    if (decision_ts_utc is not None
            and parent_context_ts_utc is not None
            and parent_context_ts_utc > decision_ts_utc):
        return PolicyResult(
            parent_terminal_state=PARENT_CONTEXT_STALE,
            parent_terminal_reason="future_parent_context_rejected_no_future_leakage",
            parent_child_confluence_state="REJECTED_FUTURE_CONTEXT",
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_NOT_LIVE_VALID,
            live_valid=False,
            fallback_policy=ACTION_PARTIAL_TRIM_ONLY,
            fallback_reason=(
                "parent_context_ts_utc > decision_ts_utc: "
                "future leakage rejected; fall back to child partial-trim"
            ),
            source_refs=source_refs,
        )

    # Rule 2: Stale parent context (age exceeds maximum)
    if (parent_context_age_minutes is not None
            and parent_context_age_minutes > max_parent_context_age_minutes):
        return PolicyResult(
            parent_terminal_state=PARENT_CONTEXT_STALE,
            parent_terminal_reason=(
                f"parent_context_age={parent_context_age_minutes:.0f}min "
                f"> max={max_parent_context_age_minutes}min"
            ),
            parent_child_confluence_state="STALE_CONTEXT",
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_NOT_LIVE_VALID,
            live_valid=False,
            fallback_policy=ACTION_PARTIAL_TRIM_ONLY,
            fallback_reason="parent_context_stale; fall back to child partial-trim",
            source_refs=source_refs,
        )

    # Rule 3: Unknown parent context → fail closed
    if parent_terminal_state == PARENT_CONTEXT_UNKNOWN:
        return PolicyResult(
            parent_terminal_state=PARENT_CONTEXT_UNKNOWN,
            parent_terminal_reason="parent_context_unavailable_fail_closed",
            parent_child_confluence_state="NO_CONFLUENCE",
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_NOT_LIVE_VALID,
            live_valid=False,
            fallback_policy=ACTION_PARTIAL_TRIM_ONLY,
            fallback_reason="parent_context_unknown; fall back to child partial-trim",
            source_refs=source_refs,
        )

    # Rule 2b: Stale state from caller-provided state
    if parent_terminal_state == PARENT_CONTEXT_STALE:
        return PolicyResult(
            parent_terminal_state=PARENT_CONTEXT_STALE,
            parent_terminal_reason="parent_context_stale_fail_closed",
            parent_child_confluence_state="STALE_CONTEXT",
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_NOT_LIVE_VALID,
            live_valid=False,
            fallback_policy=ACTION_PARTIAL_TRIM_ONLY,
            fallback_reason="parent_context_stale; fall back to child partial-trim",
            source_refs=source_refs,
        )

    # Rule 4: Map invalidated → withhold exit action
    if parent_terminal_state == PARENT_MAP_INVALIDATED:
        return PolicyResult(
            parent_terminal_state=PARENT_MAP_INVALIDATED,
            parent_terminal_reason="parent_map_invalidated_no_exit_confirmation",
            parent_child_confluence_state="MAP_INVALIDATED",
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_NO_EXIT_CONFIRMATION,
            live_valid=True,
            fallback_policy=None,
            fallback_reason=None,
            source_refs=source_refs,
        )

    # Rule 5: NOT_TERMINAL → preserve runner; child partial-trim only
    if parent_terminal_state == PARENT_NOT_TERMINAL:
        return PolicyResult(
            parent_terminal_state=PARENT_NOT_TERMINAL,
            parent_terminal_reason="parent_not_terminal_preserve_runner",
            parent_child_confluence_state="CHILD_ONLY",
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_PARTIAL_TRIM_ONLY,
            live_valid=True,
            fallback_policy=None,
            fallback_reason=None,
            source_refs=source_refs,
        )

    # Rule 6: TERMINAL_CANDIDATE → wait for confirmation; partial trim only
    if parent_terminal_state == PARENT_TERMINAL_CANDIDATE:
        return PolicyResult(
            parent_terminal_state=PARENT_TERMINAL_CANDIDATE,
            parent_terminal_reason="terminal_candidate_wait_for_confirmation",
            parent_child_confluence_state="CANDIDATE_PENDING",
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_PARTIAL_TRIM_ONLY,
            live_valid=True,
            fallback_policy=None,
            fallback_reason=None,
            source_refs=source_refs,
        )

    # Rules 7 and 8: TERMINAL_CONFIRMED or PARENT_MAP_COMPLETED
    if parent_terminal_state in _TERMINAL_STATES:
        confluence = (
            "TERMINAL_WITH_WEAKNESS"
            if weakness_confirmation_state == WEAKNESS_CONFIRMED
            else "TERMINAL_WITHOUT_WEAKNESS"
        )

        # Rule 7: Terminal confirmed + weakness → reduce to residual
        if weakness_confirmation_state == WEAKNESS_CONFIRMED:
            reduce_pct = 100.0 - residual_target_pct
            is_benchmark = (residual_target_pct == 0.0)
            return PolicyResult(
                parent_terminal_state=parent_terminal_state,
                parent_terminal_reason="terminal_confirmed_weakness_rejection_reduce",
                parent_child_confluence_state=confluence,
                weakness_confirmation_state=weakness_confirmation_state,
                requested_reduce_pct=reduce_pct,
                residual_target_pct=residual_target_pct,
                research_action=ACTION_REDUCE_TO_RESIDUAL,
                live_valid=not is_benchmark,
                fallback_policy=None,
                fallback_reason=(
                    "residual_pct=0 is benchmark-only; not live valid"
                    if is_benchmark else None
                ),
                source_refs=source_refs,
            )

        # Rule 8: Terminal confirmed without weakness → hold runner; no auto-reduce
        return PolicyResult(
            parent_terminal_state=parent_terminal_state,
            parent_terminal_reason="terminal_confirmed_no_weakness_hold_runner",
            parent_child_confluence_state=confluence,
            weakness_confirmation_state=weakness_confirmation_state,
            requested_reduce_pct=0.0,
            residual_target_pct=DEFAULT_RESIDUAL_PCT,
            research_action=ACTION_HOLD_RUNNER,
            live_valid=True,
            fallback_policy=None,
            fallback_reason=None,
            source_refs=source_refs,
        )

    # Rule 9: Child target alone (fallthrough)
    return PolicyResult(
        parent_terminal_state=parent_terminal_state,
        parent_terminal_reason="child_target_alone_no_parent_confirmation",
        parent_child_confluence_state="CHILD_ONLY",
        weakness_confirmation_state=weakness_confirmation_state,
        requested_reduce_pct=0.0,
        residual_target_pct=DEFAULT_RESIDUAL_PCT,
        research_action=ACTION_PARTIAL_TRIM_ONLY,
        live_valid=True,
        fallback_policy=None,
        fallback_reason=None,
        source_refs=source_refs,
    )


# ---------------------------------------------------------------------------
# Synthetic proxy assignment (from pre-computed outcome row)
# ---------------------------------------------------------------------------

def assign_synthetic_parent_state(
    market_breath_phase: str,
    market_breath_state: str = "UNKNOWN",
) -> str:
    """
    Assign a synthetic parent terminal state proxy from market_breath_phase.

    This function uses only observable data from the event's own row.
    It is point-in-time by construction — no future data is read.

    SYNTHETIC_PROXY: not actual parent TF chart analysis.
    No parent_map_state or parent_terminal_zone_state exists in the
    pre-computed outcome dataset.
    """
    return _BREATH_PHASE_TO_PARENT_STATE.get(market_breath_phase, PARENT_CONTEXT_UNKNOWN)


def assign_synthetic_weakness_state(
    market_breath_phase: str,
    market_breath_state: str = "UNKNOWN",
) -> str:
    """
    Assign a synthetic weakness confirmation state from breath phase + state.

    COLLAPSE_RESET + RESET state → WEAKNESS_CONFIRMED.
    All other phases → WEAKNESS_NOT_CONFIRMED or WEAKNESS_UNKNOWN.
    """
    key = (market_breath_phase, market_breath_state)
    if key in _PHASE_STATE_TO_WEAKNESS:
        return _PHASE_STATE_TO_WEAKNESS[key]
    return _DEFAULT_WEAKNESS_FOR_PHASE.get(market_breath_phase, WEAKNESS_UNKNOWN)


# ---------------------------------------------------------------------------
# Variant return computation
# ---------------------------------------------------------------------------

def compute_variant_return(
    variant_id: str,
    variant_residual_pct: Optional[float],
    research_action: str,
    r1: float,
    r6: float,
    r24: float,
) -> tuple[float, bool, str]:
    """
    Compute variant return and gate application.

    Returns (variant_return_pct, gate_applied, reason).

    V1 CHILD_PARTIAL_TRIM: always fwd_return_1c (baseline).
    V2 RESIDUAL_10:        REDUCE_TO_RESIDUAL → 0.90*r6 + 0.10*r24; else V1.
    V3 RESIDUAL_5:         REDUCE_TO_RESIDUAL → 0.95*r6 + 0.05*r24; else V1.
    V4 FULL_EXIT_BENCHMARK:REDUCE_TO_RESIDUAL → 1.00*r6 (benchmark; not live); else V1.
    V5 BUY_AND_HOLD:       always fwd_return_24c; no gate.
    """
    if variant_id == VARIANT_CHILD_PARTIAL_TRIM:
        return (r1, False, "child_partial_trim_baseline_1c")

    if variant_id == VARIANT_BUY_AND_HOLD:
        return (r24, False, "buy_and_hold_24c")

    if research_action != ACTION_REDUCE_TO_RESIDUAL:
        return (r1, False, f"fallback_to_child_partial_trim_1c_{research_action}")

    # REDUCE_TO_RESIDUAL applies — blended return
    if variant_id == VARIANT_FULL_EXIT_BENCHMARK:
        return (r6, True, "full_exit_at_6c_benchmark_residual_0pct")

    if variant_residual_pct is None:
        return (r1, False, "residual_pct_none_fallback_to_v1")

    residual_frac = variant_residual_pct / 100.0
    reduce_frac = 1.0 - residual_frac
    blended = reduce_frac * r6 + residual_frac * r24
    return (
        blended,
        True,
        f"reduce_{reduce_frac*100:.0f}pct_at_6c_hold_{residual_frac*100:.0f}pct_to_24c",
    )


# ---------------------------------------------------------------------------
# Event processing
# ---------------------------------------------------------------------------

def process_event(
    event: dict,
    decision_ts_utc: Optional[datetime] = None,
    parent_context_ts_utc: Optional[datetime] = None,
    parent_context_age_minutes: Optional[float] = None,
    max_parent_context_age_minutes: int = MAX_PARENT_CONTEXT_AGE_MINUTES,
) -> list[dict]:
    """
    Process one event and return one result row per policy variant.

    Synthetic parent state is derived from the event's own market_breath_phase
    and market_breath_state (point-in-time; no future data read).
    """
    symbol = event.get("symbol", "UNKNOWN")
    asof_ts = event.get("asof_ts_utc", "")
    event_id = f"{symbol}_{asof_ts}"

    breath_phase = event.get("market_breath_phase", "UNKNOWN")
    breath_state = event.get("market_breath_state", "UNKNOWN")

    parent_state = assign_synthetic_parent_state(breath_phase, breath_state)
    weakness_state = assign_synthetic_weakness_state(breath_phase, breath_state)

    src_refs = (
        f"market_breath_phase={breath_phase}; "
        f"market_breath_state={breath_state}; "
        "synthetic_proxy"
    )

    r1 = event.get("fwd_return_1c") or 0.0
    r6 = event.get("fwd_return_6c") or 0.0
    r12 = event.get("fwd_return_12c") or 0.0
    r24 = event.get("fwd_return_24c") or 0.0
    mfe = event.get("max_runup_24c_from_asof_close")
    mae = event.get("max_drawdown_24c_from_asof_close")

    rows = []
    for variant_id, variant_residual_pct in _VARIANT_SPECS:
        if variant_id == VARIANT_CHILD_PARTIAL_TRIM:
            # V1 baseline: always child partial trim, no policy evaluation
            result = PolicyResult(
                parent_terminal_state=parent_state,
                parent_terminal_reason="v1_baseline_child_partial_trim_no_gate",
                parent_child_confluence_state="V1_BASELINE",
                weakness_confirmation_state=weakness_state,
                requested_reduce_pct=0.0,
                residual_target_pct=DEFAULT_RESIDUAL_PCT,
                research_action=ACTION_PARTIAL_TRIM_ONLY,
                live_valid=True,
                fallback_policy=None,
                fallback_reason=None,
                source_refs=src_refs,
            )
            vret, gate_applied, reason = (r1, False, "child_partial_trim_baseline_1c")

        elif variant_id == VARIANT_BUY_AND_HOLD:
            # V5: always 24c hold, no policy evaluation
            result = PolicyResult(
                parent_terminal_state=parent_state,
                parent_terminal_reason="v5_buy_and_hold_no_gate",
                parent_child_confluence_state="V5_BUY_AND_HOLD",
                weakness_confirmation_state=weakness_state,
                requested_reduce_pct=0.0,
                residual_target_pct=DEFAULT_RESIDUAL_PCT,
                research_action=ACTION_HOLD_RUNNER,
                live_valid=True,
                fallback_policy=None,
                fallback_reason=None,
                source_refs=src_refs,
            )
            vret, gate_applied, reason = (r24, False, "buy_and_hold_24c")

        else:
            result = evaluate_parent_terminal_policy(
                parent_terminal_state=parent_state,
                weakness_confirmation_state=weakness_state,
                decision_ts_utc=decision_ts_utc,
                parent_context_ts_utc=parent_context_ts_utc,
                parent_context_age_minutes=parent_context_age_minutes,
                max_parent_context_age_minutes=max_parent_context_age_minutes,
                residual_target_pct=variant_residual_pct,
                source_refs=src_refs,
            )
            vret, gate_applied, reason = compute_variant_return(
                variant_id, variant_residual_pct, result.research_action,
                r1, r6, r24,
            )

        delta_vs_v1 = round(vret - r1, 6)

        rows.append({
            "event_id": event_id,
            "symbol": symbol,
            "asof_ts_utc": asof_ts,
            "close_price": event.get("close_price"),
            "fwd_return_1c": round(r1, 6),
            "fwd_return_6c": round(r6, 6),
            "fwd_return_12c": round(r12, 6),
            "fwd_return_24c": round(r24, 6),
            "max_runup_24c_pct": round(mfe, 4) if mfe is not None else None,
            "max_drawdown_24c_pct": round(mae, 4) if mae is not None else None,
            "market_breath_phase": breath_phase,
            "market_breath_state": breath_state,
            "synthetic_parent_terminal_state": result.parent_terminal_state,
            "parent_terminal_reason": result.parent_terminal_reason,
            "parent_child_confluence_state": result.parent_child_confluence_state,
            "synthetic_weakness_state": result.weakness_confirmation_state,
            "variant_id": variant_id,
            "variant_residual_pct": variant_residual_pct,
            "research_action": result.research_action,
            "live_valid": result.live_valid,
            "fallback_policy": result.fallback_policy,
            "fallback_reason": result.fallback_reason,
            "source_refs": result.source_refs,
            "variant_return_pct": round(vret, 6),
            "delta_vs_v1": delta_vs_v1,
            "gate_applied": gate_applied,
            "variant_return_reason": reason,
            "synthetic_proxy_note": SYNTHETIC_PROXY_NOTE,
        })

    return rows


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_events(
    path: Path = OUTCOME_ROWS_PATH,
    max_events: int = MAX_EVENTS,
    symbols: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """
    Load unique events from outcome_rows JSONL.

    Deduplicates by (symbol, asof_ts_utc) — one canonical row per event.
    Applies deterministic sort (asof_ts_utc, symbol) before capping.
    """
    if not path.exists():
        raise FileNotFoundError(f"Required input not found: {path}")

    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = (r["symbol"], r["asof_ts_utc"])
            if key in seen:
                continue
            seen.add(key)

            if symbols and r["symbol"] not in symbols:
                continue
            if date_from and r["asof_ts_utc"] < date_from:
                continue
            if date_to and r["asof_ts_utc"] > date_to:
                continue

            rows.append(r)

    rows.sort(key=lambda r: (r["asof_ts_utc"], r["symbol"]))
    return rows[:max_events]


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _safe_mean(vals: list[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 4) if vals else None


def _safe_median(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    sv = sorted(vals)
    n = len(sv)
    return round(sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2, 4)


def _win_rate(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)


def _stats(vals: list[float], label: str = "") -> dict[str, Any]:
    n = len(vals)
    if n == 0:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": n,
        "mean": _safe_mean(vals),
        "median": _safe_median(vals),
        "win_rate_pct": _win_rate(vals),
        "max": round(max(vals), 4),
        "min": round(min(vals), 4),
    }


def compute_policy_aggregate(
    rows: list[dict],
) -> list[dict[str, Any]]:
    """
    Aggregate variant returns by (synthetic_parent_terminal_state, variant_id).
    Only includes events where gate_applied=True for gated variants.
    """
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        key = (r["synthetic_parent_terminal_state"], r["variant_id"])
        groups[key].append(r["delta_vs_v1"])

    result = []
    for (parent_state, variant_id), deltas in sorted(groups.items()):
        s = _stats(deltas, f"{parent_state}|{variant_id}")
        s["synthetic_parent_terminal_state"] = parent_state
        s["variant_id"] = variant_id
        result.append(s)
    return result


def compute_variant_summary(rows: list[dict]) -> list[dict[str, Any]]:
    """Per-variant summary across all events."""
    groups: dict[str, list[float]] = defaultdict(list)
    gate_counts: dict[str, int] = defaultdict(int)
    live_invalid: dict[str, int] = defaultdict(int)
    for r in rows:
        vid = r["variant_id"]
        groups[vid].append(r["variant_return_pct"])
        if r.get("gate_applied"):
            gate_counts[vid] += 1
        if not r.get("live_valid", True):
            live_invalid[vid] += 1

    result = []
    for vid, _ in _VARIANT_SPECS:
        rets = groups.get(vid, [])
        s = _stats(rets, vid)
        s["variant_id"] = vid
        s["gate_applied_count"] = gate_counts.get(vid, 0)
        s["not_live_valid_count"] = live_invalid.get(vid, 0)
        # delta vs V1 (using mean return comparison)
        v1_mean = _safe_mean(groups.get(VARIANT_CHILD_PARTIAL_TRIM, []))
        s["mean_delta_vs_v1"] = (
            round((s["mean"] or 0) - (v1_mean or 0), 4) if v1_mean is not None else None
        )
        result.append(s)
    return result


def compute_concentration(rows: list[dict]) -> dict[str, Any]:
    """Symbol and month concentration for TERMINAL_CONFIRMED events."""
    terminal_events = [r for r in rows if
                       r["variant_id"] == VARIANT_CHILD_PARTIAL_TRIM
                       and r["synthetic_parent_terminal_state"] == PARENT_TERMINAL_CONFIRMED]
    n = len(terminal_events)
    sym_counts = Counter(r["symbol"] for r in terminal_events)
    month_counts = Counter(r["asof_ts_utc"][:7] for r in terminal_events)
    top_sym = sym_counts.most_common(1)[0] if sym_counts else ("", 0)
    top_month = month_counts.most_common(1)[0] if month_counts else ("", 0)
    return {
        "n_terminal_confirmed_events": n,
        "n_unique_symbols": len(sym_counts),
        "top_symbol": top_sym[0],
        "top_symbol_count": top_sym[1],
        "top_symbol_fraction": round(top_sym[1] / n, 3) if n else 0,
        "top_month": top_month[0],
        "top_month_count": top_month[1],
        "top_month_fraction": round(top_month[1] / n, 3) if n else 0,
        "symbol_counts": dict(sym_counts.most_common()),
        "month_counts": dict(sorted(month_counts.items())),
        "warning_high_symbol_concentration": (top_sym[1] / n > 0.5) if n else False,
        "warning_high_month_concentration": (top_month[1] / n > 0.5) if n else False,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_outputs(
    output_dir: Path,
    all_rows: list[dict],
    policy_aggregate: list[dict],
    variant_summary: list[dict],
    concentration: dict,
    summary: dict,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _collect_fields(rows: list[dict]) -> list[str]:
        seen_f: set[str] = set()
        fields: list[str] = []
        for row in rows:
            for k in row.keys():
                if k not in seen_f:
                    seen_f.add(k)
                    fields.append(k)
        return fields

    def _write_csv(p: Path, rows: list[dict]) -> None:
        if not rows:
            p.write_text("")
            return
        fields = _collect_fields(rows)
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _write_jsonl(p: Path, rows: list[dict]) -> None:
        with open(p, "w") as f:
            for row in rows:
                f.write(json.dumps(row, default=str) + "\n")

    # Event-level results (one row per event, V1 rows only — for event audit)
    event_audit_rows = [r for r in all_rows if r["variant_id"] == VARIANT_CHILD_PARTIAL_TRIM]
    p = output_dir / "event_results_v1.csv"
    _write_csv(p, event_audit_rows)
    written["event_results_csv"] = p

    # Full variant results
    p = output_dir / "variant_results_v1.csv"
    _write_csv(p, all_rows)
    written["variant_results_csv"] = p

    p = output_dir / "variant_results_v1.jsonl"
    _write_jsonl(p, all_rows)
    written["variant_results_jsonl"] = p

    # Policy aggregate
    p = output_dir / "policy_aggregate_v1.csv"
    _write_csv(p, policy_aggregate)
    written["policy_aggregate"] = p

    # Variant comparison summary
    p = output_dir / "variant_comparison_v1.csv"
    _write_csv(p, variant_summary)
    written["variant_comparison"] = p

    # Summary JSON
    p = output_dir / "summary_v1.json"
    with open(p, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    written["summary"] = p

    # Manifest
    manifest = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "output_paths": {k: str(v) for k, v in written.items()},
        "safety_markers": summary["safety_markers"],
    }
    mp = output_dir / "manifest_v1.json"
    mp.write_text(json.dumps(manifest, indent=2))
    written["manifest"] = mp

    return written


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(
    outcome_rows_path: Path = OUTCOME_ROWS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_events: int = MAX_EVENTS,
    symbols: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    print(f"STARTED {RUNNER_NAME} {VERSION}", flush=True)
    print(f"  outcome_rows={outcome_rows_path}", flush=True)
    print(f"  output_dir={output_dir}", flush=True)
    print(f"  max_events={max_events}", flush=True)
    if dry_run:
        print("  dry_run=True — load and process only; no file writes", flush=True)

    # Phase 1: Load events
    print("\nPhase 1: Loading events...", flush=True)
    events = load_events(outcome_rows_path, max_events, symbols, date_from, date_to)
    n_events = len(events)
    print(f"  Loaded {n_events} unique events", flush=True)
    if n_events == 0:
        print("FAILED: no events found")
        return 1

    # Phase 2: Process events
    print("\nPhase 2: Processing events...", flush=True)
    all_rows: list[dict] = []
    state_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()

    for ev in events:
        result_rows = process_event(ev)
        all_rows.extend(result_rows)
        # Audit from V1 row
        v1_row = result_rows[0]
        state_counts[v1_row["synthetic_parent_terminal_state"]] += 1
        for row in result_rows:
            if row["variant_id"] != VARIANT_CHILD_PARTIAL_TRIM:
                action_counts[row["research_action"]] += 1

    n_total_rows = len(all_rows)
    n_unknown = state_counts.get(PARENT_CONTEXT_UNKNOWN, 0)
    n_stale = state_counts.get(PARENT_CONTEXT_STALE, 0)
    n_fallback = n_unknown + n_stale
    n_terminal_confirmed = state_counts.get(PARENT_TERMINAL_CONFIRMED, 0)
    n_valid_parent = n_events - n_fallback
    print(f"  Total rows (events × variants): {n_total_rows}", flush=True)
    print(f"  Parent state distribution: {dict(state_counts.most_common())}", flush=True)
    print(f"  PARENT_CONTEXT_UNKNOWN: {n_unknown} ({n_unknown/n_events*100:.1f}%)", flush=True)
    print(f"  TERMINAL_CONFIRMED: {n_terminal_confirmed} ({n_terminal_confirmed/n_events*100:.1f}%)", flush=True)

    if n_terminal_confirmed == 0:
        print("  WARNING: no TERMINAL_CONFIRMED events; REDUCE_TO_RESIDUAL never fires", flush=True)
    if n_unknown / n_events > 0.5:
        print(
            f"  WARNING: {n_unknown/n_events*100:.1f}% PARENT_CONTEXT_UNKNOWN — "
            "parent coverage is degenerate; do not claim parent terminal benefit",
            flush=True,
        )

    # Phase 3: Aggregate
    print("\nPhase 3: Computing aggregates...", flush=True)
    policy_aggregate = compute_policy_aggregate(all_rows)
    variant_summary = compute_variant_summary(all_rows)
    concentration = compute_concentration(all_rows)

    # Print comparison
    v1_rows = [r for r in all_rows if r["variant_id"] == VARIANT_CHILD_PARTIAL_TRIM]
    reduce_events = [r for r in all_rows
                     if r["variant_id"] == VARIANT_RESIDUAL_10
                     and r["research_action"] == ACTION_REDUCE_TO_RESIDUAL]
    print(f"\n  Variant comparison (mean delta vs V1 baseline):", flush=True)
    for vs in variant_summary:
        print(
            f"    {vs['variant_id']:30s}: mean={vs.get('mean','n/a')}%  "
            f"delta_vs_v1={vs.get('mean_delta_vs_v1','n/a')}%  "
            f"gate_applied={vs.get('gate_applied_count',0)}",
            flush=True,
        )

    print(f"\n  REDUCE_TO_RESIDUAL fired for {len(reduce_events)}/{n_events} events", flush=True)
    if reduce_events:
        r2_deltas = [r["delta_vs_v1"] for r in reduce_events]
        print(
            f"  V2_RESIDUAL_10 delta (when fired): "
            f"mean={_safe_mean(r2_deltas)}%  median={_safe_median(r2_deltas)}%  "
            f"winrate={_win_rate(r2_deltas)}%",
            flush=True,
        )

    # Phase 4: Build summary
    summary = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "n_events": n_events,
        "n_total_rows": n_total_rows,
        "n_variants": len(_VARIANT_SPECS),
        "parent_state_distribution": dict(state_counts.most_common()),
        "parent_context_unknown_count": n_unknown,
        "parent_context_unknown_pct": round(n_unknown / n_events * 100, 1),
        "parent_context_fallback_count": n_fallback,
        "n_terminal_confirmed": n_terminal_confirmed,
        "n_valid_parent_proxy": n_valid_parent,
        "reduce_to_residual_events": len(reduce_events),
        "variant_summary": variant_summary,
        "policy_aggregate": policy_aggregate,
        "concentration": concentration,
        "notes": {
            "synthetic_proxy": (
                "Parent terminal states are SYNTHETIC PROXIES derived from market_breath_phase. "
                "No actual parent TF chart analysis exists in the pre-computed outcome dataset. "
                "Do not claim parent terminal benefit if coverage is absent or degenerate."
            ),
            "parent_coverage": (
                f"{n_unknown}/{n_events} ({n_unknown/n_events*100:.1f}%) events have "
                "PARENT_CONTEXT_UNKNOWN (NEUTRAL_TRANSITION phase). "
                "Only COLLAPSE_RESET events (TERMINAL_CONFIRMED proxy) produce REDUCE_TO_RESIDUAL. "
                "Coverage is sparse; results for TERMINAL_CONFIRMED reflect COLLAPSE_RESET events only."
            ),
            "reduction_horizon": (
                "Bulk reduction at 6c (24h); residual held to 24c (96h). "
                "Reduction horizon is a research approximation; actual timing depends on "
                "parent terminal confirmation sequence."
            ),
            "residual_ownership": (
                "residual_target_pct belongs to strategy/advice intent. "
                "Never passed to execution_planner. "
                "V4_FULL_EXIT_BENCHMARK (residual_pct=0) is not live valid."
            ),
            "buy_and_hold": (
                "V5_BUY_AND_HOLD holds for 24c regardless of gate state. "
                "Used as an upper-bound baseline."
            ),
            "context_quality_tier": (
                "context_quality_tier, parent_map_state, parent_terminal_zone_state: "
                "not available in pre-computed outcome dataset. "
                "Cannot break down by these dimensions."
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

    if dry_run:
        print("\nDRY RUN — skipping file writes", flush=True)
        print(f"FINISHED {RUNNER_NAME} (dry run)")
        return 0

    # Phase 5: Write outputs
    print("\nPhase 5: Writing outputs...", flush=True)
    written = write_outputs(
        output_dir, all_rows, policy_aggregate, variant_summary, concentration, summary,
    )
    for k, p in written.items():
        print(f"  {k}: {p}", flush=True)

    print(f"\nFINISHED {RUNNER_NAME}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"{RUNNER_NAME} — research-only parent terminal residual exit evaluation"
    )
    parser.add_argument("--outcome-rows", default=str(OUTCOME_ROWS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-events", type=int, default=MAX_EVENTS)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(
        outcome_rows_path=Path(args.outcome_rows),
        output_dir=Path(args.output_dir),
        max_events=args.max_events,
        symbols=args.symbols,
        date_from=args.date_from,
        date_to=args.date_to,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
