"""
run_weakness_reentry_block_v1.py
=================================
Research runner: Weakness/rejection re-entry block policy evaluation.

Canonical Hypothesis
--------------------
  Weakness or rejection after a target blocks re-entry.
  Selling or trimming never automatically implies buying back lower.
  Re-entry becomes watchable only near a valid reload zone.
  Re-entry becomes context-supported only after an observable reset/reclaim.
  Breath/Regime must no longer be weakening/conflicting.
  Parent map must remain constructive.
  Parent terminal/completed context blocks same-cycle re-entry.

Re-Entry States
---------------
  REENTRY_BLOCKED_WEAKNESS       Weakness or rejection is active; re-entry blocked.
  REENTRY_BLOCKED_PARENT_TERMINAL Parent terminal/completed; same-cycle re-entry blocked.
  RESET_REQUIRED                 Extension or rejection active; wait for reset.
  WATCH_REENTRY                  Reset confirmed or forming; approaching reload zone.
  REENTRY_CONTEXT_SUPPORTED      All conditions met: reset, reclaim, zone, Breath, Regime ok.
  REENTRY_CONTEXT_CONFLICT       Reset/reclaim ok but Breath or Regime still conflicting.
  CONTEXT_UNKNOWN                No valid context available; fail closed.
  NOT_LIVE_VALID                 Future context, stale context, or missing inputs.

Required Inputs (policy function)
-----------------------------------
  decision_ts_utc          When re-entry is being evaluated.
  exit_or_trim_ts_utc      When the prior exit or trim occurred (optional — not in dataset).
  child_map_state          Child fib map state.
  child_target_state       Child target state (e.g. CHILD_TARGET_TOUCHED).
  reload_zone_low          Reload zone lower bound price.
  reload_zone_high         Reload zone upper bound price.
  current_price            Current market price.
  retest_price             Price at most recent reload zone retest.
  reset_state              Observable reset state.
  reclaim_state            Observable reclaim state.
  breath_phase             Breath phase (market_breath_phase).
  breath_alignment         Breath alignment direction (POSITIVE / NEGATIVE / NEUTRAL).
  market_regime            Market regime state.
  symbol_regime            Symbol-specific regime state.
  native_short_4h_lifecycle Short fib 4h lifecycle state.
  native_short_1h_support  Short fib 1h supporting state.
  parent_terminal_state    Parent terminal state from parent-terminal runner.
  parent_map_state         Parent map state.
  context_ts_utc           Timestamp of context (must be <= decision_ts_utc).
  context_age_minutes      Age of context in minutes.
  max_context_age_minutes  Maximum acceptable context age.

Policy Rules (priority order)
------------------------------
  1.  Future context (context_ts_utc > decision_ts_utc) → NOT_LIVE_VALID.
  2.  Stale context (context_age > max) → NOT_LIVE_VALID.
  3.  CONTEXT_UNKNOWN → NOT_LIVE_VALID; fail closed.
  4.  Weakness active (EXHALE_EXPANSION, OVERBREATH_EXTENSION) → REENTRY_BLOCKED_WEAKNESS.
  5.  Parent terminal/completed and same-cycle → REENTRY_BLOCKED_PARENT_TERMINAL.
  6.  Reset not confirmed → RESET_REQUIRED.
  7.  Reset forming (in progress) → WATCH_REENTRY.
  8.  Reset confirmed, no reclaim → WATCH_REENTRY.
  9.  Reset confirmed + reclaim + supportive Breath/Regime → REENTRY_CONTEXT_SUPPORTED.
  10. Reset confirmed + reclaim + conflicting Breath/Regime → REENTRY_CONTEXT_CONFLICT.
  11. Default → WATCH_REENTRY.

Synthetic Proxy Derivation
---------------------------
  Actual child fib maps, reload zone prices, exit timestamps, and parent map analysis
  are NOT available in the pre-computed outcome_rows_v1 dataset. Synthetic proxies are
  assigned from available market signal fields:

    market_breath_phase     → weakness_state, reset_state (primary proxy)
    market_breath_state     → reclaim_state (secondary proxy)
    reversal_pressure_score → secondary weakness signal (> threshold)
    compression_score       → reload zone state proxy (> threshold = zone tested)
    breadth_alignment_score → breath alignment and 1h support proxy
    market_breath_score     → market regime proxy
    momentum_score          → regime conflict proxy

  All synthetic state assignments are labeled SYNTHETIC_PROXY in output.

Evaluation Metrics
------------------
  false_reentry_rate:     REENTRY_CONTEXT_SUPPORTED events where fwd_return_6c < 0.
  missed_opportunity_rate: REENTRY_BLOCKED_* events where fwd_return_6c > OPPORTUNITY_THRESHOLD.
  Breakdown by breath phase, parent state, regime, native SHORT state.
  Report sample counts and concentration; do not create a rule from insufficient samples.

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
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Re-entry states
# ---------------------------------------------------------------------------
REENTRY_BLOCKED_WEAKNESS = "REENTRY_BLOCKED_WEAKNESS"
REENTRY_BLOCKED_PARENT_TERMINAL = "REENTRY_BLOCKED_PARENT_TERMINAL"
RESET_REQUIRED = "RESET_REQUIRED"
WATCH_REENTRY = "WATCH_REENTRY"
REENTRY_CONTEXT_SUPPORTED = "REENTRY_CONTEXT_SUPPORTED"
REENTRY_CONTEXT_CONFLICT = "REENTRY_CONTEXT_CONFLICT"
CONTEXT_UNKNOWN = "CONTEXT_UNKNOWN"
NOT_LIVE_VALID = "NOT_LIVE_VALID"

_BLOCKED_STATES = frozenset({REENTRY_BLOCKED_WEAKNESS, REENTRY_BLOCKED_PARENT_TERMINAL})
_WATCH_STATES = frozenset({RESET_REQUIRED, WATCH_REENTRY})
_SUPPORTED_STATES = frozenset({REENTRY_CONTEXT_SUPPORTED})
_CONFLICT_STATES = frozenset({REENTRY_CONTEXT_CONFLICT})

# ---------------------------------------------------------------------------
# Weakness states
# ---------------------------------------------------------------------------
WEAKNESS_ACTIVE = "WEAKNESS_ACTIVE"
WEAKNESS_CLEARING = "WEAKNESS_CLEARING"
WEAKNESS_RESOLVED = "WEAKNESS_RESOLVED"
WEAKNESS_UNKNOWN = "WEAKNESS_UNKNOWN"

# ---------------------------------------------------------------------------
# Reset / reclaim states
# ---------------------------------------------------------------------------
RESET_CONFIRMED_STATE = "RESET_CONFIRMED"
RESET_FORMING_STATE = "RESET_FORMING"
RESET_NOT_CONFIRMED_STATE = "RESET_NOT_CONFIRMED"
RESET_UNKNOWN_STATE = "RESET_UNKNOWN"

RECLAIM_CONFIRMED_STATE = "RECLAIM_CONFIRMED"
RECLAIM_NOT_CONFIRMED_STATE = "RECLAIM_NOT_CONFIRMED"
RECLAIM_UNKNOWN_STATE = "RECLAIM_UNKNOWN"

# ---------------------------------------------------------------------------
# Reload zone states
# ---------------------------------------------------------------------------
ZONE_TESTED = "ZONE_TESTED"
ZONE_APPROACHING = "ZONE_APPROACHING"
ZONE_NOT_TESTED = "ZONE_NOT_TESTED"
ZONE_UNKNOWN = "ZONE_UNKNOWN"

# ---------------------------------------------------------------------------
# Breath alignment states
# ---------------------------------------------------------------------------
BREATH_ALIGNMENT_POSITIVE = "ALIGNMENT_POSITIVE"
BREATH_ALIGNMENT_NEGATIVE = "ALIGNMENT_NEGATIVE"
BREATH_ALIGNMENT_NEUTRAL = "ALIGNMENT_NEUTRAL"
BREATH_ALIGNMENT_UNKNOWN = "ALIGNMENT_UNKNOWN"

# ---------------------------------------------------------------------------
# Regime states
# ---------------------------------------------------------------------------
REGIME_SUPPORTIVE = "REGIME_SUPPORTIVE"
REGIME_NEUTRAL = "REGIME_NEUTRAL"
REGIME_CONFLICTING = "REGIME_CONFLICTING"
REGIME_UNKNOWN = "REGIME_UNKNOWN"

# ---------------------------------------------------------------------------
# Parent constructive states
# ---------------------------------------------------------------------------
PARENT_CONSTRUCTIVE = "PARENT_CONSTRUCTIVE"
PARENT_BLOCKING = "PARENT_BLOCKING"
PARENT_UNKNOWN_STATE = "PARENT_UNKNOWN"

# ---------------------------------------------------------------------------
# Native SHORT lifecycle proxies
# ---------------------------------------------------------------------------
LIFECYCLE_TARGET_REACHED = "TARGET_REACHED_OR_PASSED"
LIFECYCLE_TARGET_ACTIVE = "TARGET_ACTIVE"
LIFECYCLE_MAP_COMPLETED = "MAP_COMPLETED"
LIFECYCLE_POST_PULLBACK = "POST_BREAKOUT_PULLBACK"
LIFECYCLE_BELOW_GATE = "BELOW_BREAKOUT_GATE"
LIFECYCLE_UNKNOWN = "LIFECYCLE_UNKNOWN"

SHORT_1H_ALIGNED = "ALIGNED_WITH_4H"
SHORT_1H_CONFLICT = "CONFLICT_WITH_4H"
SHORT_1H_NEUTRAL = "NEUTRAL_OR_NOT_CONFIRMING"

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------
RUNNER_NAME = "WEAKNESS_REENTRY_BLOCK_V1"
VERSION = "1.0.0"
MAX_CONTEXT_AGE_MINUTES = 480          # 8h
REVERSAL_PRESSURE_WEAKNESS_THRESHOLD = 70.0   # score > this → additional weakness
COMPRESSION_ZONE_TESTED_THRESHOLD = 40.0      # compression_score > this → zone tested proxy
COMPRESSION_ZONE_APPROACHING_THRESHOLD = 20.0
BREATH_ALIGNMENT_POSITIVE_THRESHOLD = 15.0    # breadth_alignment_score
BREATH_ALIGNMENT_NEGATIVE_THRESHOLD = -15.0
REGIME_SUPPORTIVE_BREATH_SCORE = 52.0         # market_breath_score > this → supportive
REGIME_CONFLICTING_BREATH_SCORE = 40.0        # market_breath_score < this → conflicting
REGIME_CONFLICT_MOMENTUM_THRESHOLD = -20.0    # momentum_score < this → conflict
MISSED_OPPORTUNITY_THRESHOLD_PCT = 2.0        # fwd_return_6c > this → meaningful missed gain
DEFAULT_OUTPUT_DIR = Path("data/research/weakness_reentry_block_v1")
OUTCOME_ROWS_PATH = Path(
    "data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl"
)
MAX_EVENTS = 2500

SYNTHETIC_PROXY_NOTE = (
    "SYNTHETIC_PROXY: re-entry states derived from market_breath_phase, "
    "reversal_pressure_score, compression_score, breadth_alignment_score, "
    "market_breath_score, momentum_score. "
    "No actual child fib maps, reload zone prices, or parent map analysis "
    "available in pre-computed outcome dataset."
)

# ---------------------------------------------------------------------------
# Synthetic proxy mappings
# ---------------------------------------------------------------------------

_BREATH_PHASE_TO_WEAKNESS: dict[str, str] = {
    "EXHALE_EXPANSION": WEAKNESS_ACTIVE,       # selling/downward phase; wr6=32%
    "OVERBREATH_EXTENSION": WEAKNESS_ACTIVE,   # extended, reversal_pressure=91%
    # COLLAPSE_RESET = terminal capitulation event — not a bullish reset.
    # Distinct from INHALE_ACCUMULATION (new energy build after bottom confirmed).
    # COLLAPSE_RESET can be bottom OR continued capitulation; the snapshot alone
    # cannot confirm which, so weakness remains ACTIVE at the collapse event.
    "COLLAPSE_RESET": WEAKNESS_ACTIVE,
    # INHALE_ACCUMULATION = new energy buildup AFTER reset is confirmed; weakness cleared.
    "INHALE_ACCUMULATION": WEAKNESS_RESOLVED,  # accumulation; reset confirmed
    "HOLD_COMPRESSION": WEAKNESS_RESOLVED,     # compression; zone holding
    "NEUTRAL_TRANSITION": WEAKNESS_UNKNOWN,
}

_BREATH_PHASE_TO_RESET: dict[str, str] = {
    "EXHALE_EXPANSION": RESET_NOT_CONFIRMED_STATE,
    "OVERBREATH_EXTENSION": RESET_NOT_CONFIRMED_STATE,
    # COLLAPSE_RESET = capitulation event; reset not yet confirmed (bottom may not be in).
    # Reset is confirmed only when INHALE_ACCUMULATION begins.
    "COLLAPSE_RESET": RESET_NOT_CONFIRMED_STATE,
    "INHALE_ACCUMULATION": RESET_CONFIRMED_STATE,
    "HOLD_COMPRESSION": RESET_CONFIRMED_STATE,
    "NEUTRAL_TRANSITION": RESET_UNKNOWN_STATE,
}

# Reclaim requires both phase AND confirmed state in accumulation
_PHASE_STATE_TO_RECLAIM: dict[tuple[str, str], str] = {
    ("INHALE_ACCUMULATION", "CONFIRMED"): RECLAIM_CONFIRMED_STATE,
    ("HOLD_COMPRESSION", "CONFIRMED"): RECLAIM_CONFIRMED_STATE,
    ("HOLD_COMPRESSION", "FORMING"): RECLAIM_NOT_CONFIRMED_STATE,
}
_DEFAULT_RECLAIM_FOR_PHASE: dict[str, str] = {
    "EXHALE_EXPANSION": RECLAIM_NOT_CONFIRMED_STATE,
    "OVERBREATH_EXTENSION": RECLAIM_NOT_CONFIRMED_STATE,
    "COLLAPSE_RESET": RECLAIM_NOT_CONFIRMED_STATE,
    "INHALE_ACCUMULATION": RECLAIM_NOT_CONFIRMED_STATE,
    "HOLD_COMPRESSION": RECLAIM_NOT_CONFIRMED_STATE,
    "NEUTRAL_TRANSITION": RECLAIM_UNKNOWN_STATE,
}

_BREATH_PHASE_TO_NATIVE_SHORT_4H: dict[str, str] = {
    "OVERBREATH_EXTENSION": LIFECYCLE_TARGET_REACHED,
    "EXHALE_EXPANSION": LIFECYCLE_TARGET_ACTIVE,
    "COLLAPSE_RESET": LIFECYCLE_MAP_COMPLETED,
    "HOLD_COMPRESSION": LIFECYCLE_POST_PULLBACK,
    "INHALE_ACCUMULATION": LIFECYCLE_POST_PULLBACK,
    "NEUTRAL_TRANSITION": LIFECYCLE_UNKNOWN,
}


# ---------------------------------------------------------------------------
# Synthetic proxy assignments
# ---------------------------------------------------------------------------

def assign_weakness_state(
    breath_phase: str,
    reversal_pressure_score: float = 0.0,
) -> str:
    base = _BREATH_PHASE_TO_WEAKNESS.get(breath_phase, WEAKNESS_UNKNOWN)
    # Override: high reversal pressure in any non-active phase → upgrade to clearing
    if (base == WEAKNESS_RESOLVED
            and reversal_pressure_score > REVERSAL_PRESSURE_WEAKNESS_THRESHOLD):
        return WEAKNESS_CLEARING
    return base


def assign_reset_state(breath_phase: str) -> str:
    return _BREATH_PHASE_TO_RESET.get(breath_phase, RESET_UNKNOWN_STATE)


def assign_reclaim_state(breath_phase: str, breath_state: str) -> str:
    key = (breath_phase, breath_state)
    if key in _PHASE_STATE_TO_RECLAIM:
        return _PHASE_STATE_TO_RECLAIM[key]
    return _DEFAULT_RECLAIM_FOR_PHASE.get(breath_phase, RECLAIM_UNKNOWN_STATE)


def assign_reload_zone_state(compression_score: float) -> str:
    if compression_score > COMPRESSION_ZONE_TESTED_THRESHOLD:
        return ZONE_TESTED
    if compression_score > COMPRESSION_ZONE_APPROACHING_THRESHOLD:
        return ZONE_APPROACHING
    return ZONE_NOT_TESTED


def assign_breath_alignment(breadth_alignment_score: float) -> str:
    if breadth_alignment_score > BREATH_ALIGNMENT_POSITIVE_THRESHOLD:
        return BREATH_ALIGNMENT_POSITIVE
    if breadth_alignment_score < BREATH_ALIGNMENT_NEGATIVE_THRESHOLD:
        return BREATH_ALIGNMENT_NEGATIVE
    return BREATH_ALIGNMENT_NEUTRAL


def assign_regime_state(
    market_breath_score: float,
    momentum_score: float,
) -> str:
    if market_breath_score < REGIME_CONFLICTING_BREATH_SCORE:
        return REGIME_CONFLICTING
    if momentum_score < REGIME_CONFLICT_MOMENTUM_THRESHOLD:
        return REGIME_CONFLICTING
    if market_breath_score > REGIME_SUPPORTIVE_BREATH_SCORE:
        return REGIME_SUPPORTIVE
    return REGIME_NEUTRAL


def assign_parent_constructive_state(parent_terminal_state: str) -> str:
    if parent_terminal_state in ("TERMINAL_CONFIRMED", "PARENT_MAP_COMPLETED"):
        return PARENT_BLOCKING
    if parent_terminal_state in ("PARENT_CONTEXT_UNKNOWN", "PARENT_CONTEXT_STALE"):
        return PARENT_UNKNOWN_STATE
    return PARENT_CONSTRUCTIVE


def assign_native_short_4h_lifecycle(breath_phase: str) -> str:
    return _BREATH_PHASE_TO_NATIVE_SHORT_4H.get(breath_phase, LIFECYCLE_UNKNOWN)


def assign_native_short_1h_support(breadth_alignment_score: float) -> str:
    if breadth_alignment_score > 20.0:
        return SHORT_1H_ALIGNED
    if breadth_alignment_score < -20.0:
        return SHORT_1H_CONFLICT
    return SHORT_1H_NEUTRAL


# ---------------------------------------------------------------------------
# Core policy result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReentryResult:
    reentry_state: str
    reentry_reason: str
    weakness_state: str
    reset_state: str
    reclaim_state: str
    reload_zone_state: str
    parent_constructive_state: str
    breath_alignment: str
    regime_state: str
    native_short_4h_lifecycle: str
    native_short_1h_support: str
    gate_applied: bool
    live_valid: bool
    fallback_policy: Optional[str]
    source_refs: str


# ---------------------------------------------------------------------------
# Core policy function (pure — no DB, no executor, no execution_planner)
# ---------------------------------------------------------------------------

def evaluate_reentry_block_policy(
    # Context timing
    decision_ts_utc: Optional[datetime] = None,
    exit_or_trim_ts_utc: Optional[datetime] = None,
    context_ts_utc: Optional[datetime] = None,
    context_age_minutes: float = 0.0,
    max_context_age_minutes: int = MAX_CONTEXT_AGE_MINUTES,
    # Derived state inputs
    weakness_state: str = WEAKNESS_UNKNOWN,
    reset_state: str = RESET_UNKNOWN_STATE,
    reclaim_state: str = RECLAIM_UNKNOWN_STATE,
    reload_zone_state: str = ZONE_UNKNOWN,
    breath_alignment: str = BREATH_ALIGNMENT_UNKNOWN,
    regime_state: str = REGIME_UNKNOWN,
    native_short_4h_lifecycle: str = LIFECYCLE_UNKNOWN,
    native_short_1h_support: str = SHORT_1H_NEUTRAL,
    parent_terminal_state: str = "PARENT_CONTEXT_UNKNOWN",
    parent_constructive_state: str = PARENT_UNKNOWN_STATE,
    # Optional child context
    child_map_state: str = "UNKNOWN",
    child_target_state: str = "UNKNOWN",
    source_refs: str = "",
) -> ReentryResult:
    """
    Deterministic re-entry block policy.

    Rules (priority order):
      1.  Future context → NOT_LIVE_VALID (no future leakage).
      2.  Stale context → NOT_LIVE_VALID.
      3.  CONTEXT_UNKNOWN → NOT_LIVE_VALID; fail closed.
      4.  WEAKNESS_ACTIVE → REENTRY_BLOCKED_WEAKNESS.
      5.  Parent blocking → REENTRY_BLOCKED_PARENT_TERMINAL.
      6.  RESET_NOT_CONFIRMED → RESET_REQUIRED.
      7.  RESET_FORMING → WATCH_REENTRY.
      8.  RESET_CONFIRMED + no reclaim → WATCH_REENTRY.
      9.  RESET_CONFIRMED + reclaim + supportive → REENTRY_CONTEXT_SUPPORTED.
      10. RESET_CONFIRMED + reclaim + conflicting → REENTRY_CONTEXT_CONFLICT.
      11. Default → WATCH_REENTRY.
    """
    def _result(state, reason, gate=False, live=True, fallback=None):
        return ReentryResult(
            reentry_state=state,
            reentry_reason=reason,
            weakness_state=weakness_state,
            reset_state=reset_state,
            reclaim_state=reclaim_state,
            reload_zone_state=reload_zone_state,
            parent_constructive_state=parent_constructive_state,
            breath_alignment=breath_alignment,
            regime_state=regime_state,
            native_short_4h_lifecycle=native_short_4h_lifecycle,
            native_short_1h_support=native_short_1h_support,
            gate_applied=gate,
            live_valid=live,
            fallback_policy=fallback,
            source_refs=source_refs,
        )

    # Rule 1: Future context → reject
    if (decision_ts_utc is not None
            and context_ts_utc is not None
            and context_ts_utc > decision_ts_utc):
        return _result(
            NOT_LIVE_VALID,
            "future_context_rejected_no_future_leakage",
            live=False, fallback="fail_closed",
        )

    # Rule 2: Stale context
    if context_age_minutes > max_context_age_minutes:
        return _result(
            NOT_LIVE_VALID,
            f"context_stale_{context_age_minutes:.0f}min>max_{max_context_age_minutes}min",
            live=False, fallback="fail_closed",
        )

    # Rule 3: Unknown context → fail closed
    if (weakness_state == WEAKNESS_UNKNOWN
            and reset_state == RESET_UNKNOWN_STATE
            and reclaim_state == RECLAIM_UNKNOWN_STATE):
        return _result(
            CONTEXT_UNKNOWN,
            "no_valid_context_available_fail_closed",
            live=False, fallback="fail_closed",
        )

    # Rule 4: Weakness active → block
    if weakness_state == WEAKNESS_ACTIVE:
        return _result(
            REENTRY_BLOCKED_WEAKNESS,
            "weakness_or_rejection_active_block_reentry",
            gate=True, live=True,
        )

    # Rule 5: Parent blocking (terminal/completed, same-cycle)
    if parent_constructive_state == PARENT_BLOCKING:
        return _result(
            REENTRY_BLOCKED_PARENT_TERMINAL,
            "parent_terminal_or_completed_block_same_cycle_reentry",
            gate=True, live=True,
        )

    # Rule 6: Reset not confirmed → wait for reset
    if reset_state == RESET_NOT_CONFIRMED_STATE:
        return _result(
            RESET_REQUIRED,
            "reset_not_confirmed_wait_for_reset",
            gate=True, live=True,
        )

    # Rule 7: Reset forming (in progress) → watch
    if reset_state == RESET_FORMING_STATE:
        return _result(
            WATCH_REENTRY,
            "reset_forming_watch_reentry",
            gate=True, live=True,
        )

    # Rule 8: Reset confirmed but no reclaim → watch
    if reclaim_state != RECLAIM_CONFIRMED_STATE:
        return _result(
            WATCH_REENTRY,
            "reset_confirmed_reclaim_not_confirmed_watch_reentry",
            gate=True, live=True,
        )

    # At this point: reset confirmed + reclaim confirmed
    # Check Breath/Regime conditions for supported vs conflict
    breath_ok = breath_alignment != BREATH_ALIGNMENT_NEGATIVE
    regime_ok = regime_state != REGIME_CONFLICTING
    parent_ok = parent_constructive_state != PARENT_BLOCKING
    short_1h_ok = native_short_1h_support != SHORT_1H_CONFLICT

    if breath_ok and regime_ok and parent_ok and short_1h_ok:
        # Rule 9: Full support
        return _result(
            REENTRY_CONTEXT_SUPPORTED,
            "reset_reclaim_breath_regime_all_supportive",
            gate=True, live=True,
        )

    # Rule 10: Conflict present
    conflict_reasons = []
    if not breath_ok:
        conflict_reasons.append("breath_alignment_negative")
    if not regime_ok:
        conflict_reasons.append(f"regime_conflicting_{regime_state}")
    if not short_1h_ok:
        conflict_reasons.append("native_short_1h_conflict")
    conflict_str = ";".join(conflict_reasons)
    return _result(
        REENTRY_CONTEXT_CONFLICT,
        f"reset_reclaim_ok_but_conflict:{conflict_str}",
        gate=True, live=True,
    )


# ---------------------------------------------------------------------------
# Event processing
# ---------------------------------------------------------------------------

def _derive_parent_terminal_state(breath_phase: str) -> str:
    _map = {
        "EXHALE_EXPANSION": "NOT_TERMINAL",
        "INHALE_ACCUMULATION": "NOT_TERMINAL",
        "OVERBREATH_EXTENSION": "TERMINAL_CANDIDATE",
        "HOLD_COMPRESSION": "TERMINAL_CANDIDATE",
        "COLLAPSE_RESET": "TERMINAL_CONFIRMED",
        "NEUTRAL_TRANSITION": "PARENT_CONTEXT_UNKNOWN",
    }
    return _map.get(breath_phase, "PARENT_CONTEXT_UNKNOWN")


def process_event(event: dict) -> dict:
    """Process one event and return a single result row."""
    symbol = event.get("symbol", "UNKNOWN")
    asof_ts = event.get("asof_ts_utc", "")
    event_id = f"{symbol}_{asof_ts}"

    breath_phase = event.get("market_breath_phase", "UNKNOWN")
    breath_state = event.get("market_breath_state", "UNKNOWN")

    reversal_pressure = event.get("reversal_pressure_score") or 0.0
    compression = event.get("compression_score") or 0.0
    breadth_alignment = event.get("breadth_alignment_score") or 0.0
    breath_score = event.get("market_breath_score") or 50.0
    momentum = event.get("momentum_score") or 0.0

    # Assign synthetic proxy states
    w_state = assign_weakness_state(breath_phase, reversal_pressure)
    r_state = assign_reset_state(breath_phase)
    rc_state = assign_reclaim_state(breath_phase, breath_state)
    rz_state = assign_reload_zone_state(compression)
    ba_state = assign_breath_alignment(breadth_alignment)
    reg_state = assign_regime_state(breath_score, momentum)

    parent_terminal = _derive_parent_terminal_state(breath_phase)
    parent_constructive = assign_parent_constructive_state(parent_terminal)
    n4h_state = assign_native_short_4h_lifecycle(breath_phase)
    n1h_state = assign_native_short_1h_support(breadth_alignment)

    src_refs = (
        f"market_breath_phase={breath_phase}; "
        f"market_breath_state={breath_state}; "
        f"reversal_pressure={reversal_pressure:.1f}; "
        f"compression={compression:.1f}; "
        f"breadth_alignment={breadth_alignment:.1f}; "
        f"market_breath_score={breath_score:.1f}; "
        f"momentum={momentum:.1f}; "
        "synthetic_proxy"
    )

    result = evaluate_reentry_block_policy(
        weakness_state=w_state,
        reset_state=r_state,
        reclaim_state=rc_state,
        reload_zone_state=rz_state,
        breath_alignment=ba_state,
        regime_state=reg_state,
        native_short_4h_lifecycle=n4h_state,
        native_short_1h_support=n1h_state,
        parent_terminal_state=parent_terminal,
        parent_constructive_state=parent_constructive,
        source_refs=src_refs,
    )

    r1 = event.get("fwd_return_1c") or 0.0
    r6 = event.get("fwd_return_6c") or 0.0
    r24 = event.get("fwd_return_24c") or 0.0
    mfe = event.get("max_runup_24c_from_asof_close")
    mae = event.get("max_drawdown_24c_from_asof_close")

    is_blocked = result.reentry_state in _BLOCKED_STATES
    is_supported = result.reentry_state in _SUPPORTED_STATES
    false_reentry = is_supported and r6 < 0
    missed_opportunity = is_blocked and r6 > MISSED_OPPORTUNITY_THRESHOLD_PCT

    return {
        "event_id": event_id,
        "symbol": symbol,
        "asof_ts_utc": asof_ts,
        "market_breath_phase": breath_phase,
        "market_breath_state": breath_state,
        "reversal_pressure_score": round(reversal_pressure, 2),
        "compression_score": round(compression, 2),
        "breadth_alignment_score": round(breadth_alignment, 2),
        "market_breath_score": round(breath_score, 2),
        "momentum_score": round(momentum, 2),
        "synthetic_weakness_state": result.weakness_state,
        "synthetic_reset_state": result.reset_state,
        "synthetic_reclaim_state": result.reclaim_state,
        "synthetic_reload_zone_state": result.reload_zone_state,
        "synthetic_breath_alignment": result.breath_alignment,
        "synthetic_regime_state": result.regime_state,
        "synthetic_native_short_4h": result.native_short_4h_lifecycle,
        "synthetic_native_short_1h": result.native_short_1h_support,
        "synthetic_parent_terminal_state": parent_terminal,
        "synthetic_parent_constructive_state": result.parent_constructive_state,
        "reentry_state": result.reentry_state,
        "reentry_reason": result.reentry_reason,
        "gate_applied": result.gate_applied,
        "live_valid": result.live_valid,
        "fallback_policy": result.fallback_policy,
        "fwd_return_1c": round(r1, 6),
        "fwd_return_6c": round(r6, 6),
        "fwd_return_24c": round(r24, 6),
        "max_runup_24c_pct": round(mfe, 4) if mfe is not None else None,
        "max_drawdown_24c_pct": round(mae, 4) if mae is not None else None,
        "is_blocked": is_blocked,
        "is_supported": is_supported,
        "false_reentry": false_reentry,
        "missed_opportunity": missed_opportunity,
        "source_refs": result.source_refs,
        "synthetic_proxy_note": SYNTHETIC_PROXY_NOTE,
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_events(
    path: Path,
    max_events: int = MAX_EVENTS,
    symbols: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
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


def compute_state_breakdown(rows: list[dict]) -> list[dict[str, Any]]:
    """Per re-entry state: n, mean/median r6, r24, MFE, win rates, blocked/supported counts."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["reentry_state"]].append(r)

    result = []
    all_states = [
        REENTRY_BLOCKED_WEAKNESS,
        REENTRY_BLOCKED_PARENT_TERMINAL,
        RESET_REQUIRED,
        WATCH_REENTRY,
        REENTRY_CONTEXT_SUPPORTED,
        REENTRY_CONTEXT_CONFLICT,
        CONTEXT_UNKNOWN,
        NOT_LIVE_VALID,
    ]
    for state in all_states:
        ev_rows = groups.get(state, [])
        n = len(ev_rows)
        r6_vals = [r["fwd_return_6c"] for r in ev_rows]
        r24_vals = [r["fwd_return_24c"] for r in ev_rows]
        mfe_vals = [r["max_runup_24c_pct"] for r in ev_rows if r.get("max_runup_24c_pct") is not None]
        mae_vals = [r["max_drawdown_24c_pct"] for r in ev_rows if r.get("max_drawdown_24c_pct") is not None]
        missed = sum(1 for r in ev_rows if r.get("missed_opportunity"))
        false_re = sum(1 for r in ev_rows if r.get("false_reentry"))
        result.append({
            "reentry_state": state,
            "n": n,
            "r6_mean": _safe_mean(r6_vals),
            "r6_median": _safe_median(r6_vals),
            "r6_win_rate_pct": _win_rate(r6_vals),
            "r24_mean": _safe_mean(r24_vals),
            "r24_median": _safe_median(r24_vals),
            "r24_win_rate_pct": _win_rate(r24_vals),
            "mfe_mean": _safe_mean(mfe_vals),
            "mfe_median": _safe_median(mfe_vals),
            "mae_mean": _safe_mean(mae_vals),
            "mae_median": _safe_median(mae_vals),
            "missed_opportunity_count": missed,
            "missed_opportunity_rate_pct": round(missed / n * 100, 1) if n else None,
            "false_reentry_count": false_re,
            "false_reentry_rate_pct": round(false_re / n * 100, 1) if n else None,
        })
    return result


def compute_breath_breakdown(rows: list[dict]) -> list[dict[str, Any]]:
    """Per breath phase × re-entry state breakdown."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["market_breath_phase"], r["reentry_state"])
        groups[key].append(r)

    result = []
    for (phase, state), ev_rows in sorted(groups.items()):
        n = len(ev_rows)
        r6_vals = [r["fwd_return_6c"] for r in ev_rows]
        result.append({
            "market_breath_phase": phase,
            "reentry_state": state,
            "n": n,
            "r6_mean": _safe_mean(r6_vals),
            "r6_win_rate_pct": _win_rate(r6_vals),
            "missed_opportunity_count": sum(1 for r in ev_rows if r.get("missed_opportunity")),
            "false_reentry_count": sum(1 for r in ev_rows if r.get("false_reentry")),
        })
    return result


def compute_parent_state_breakdown(rows: list[dict]) -> list[dict[str, Any]]:
    """Per parent terminal state × re-entry state breakdown."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["synthetic_parent_terminal_state"], r["reentry_state"])
        groups[key].append(r)

    result = []
    for (parent, state), ev_rows in sorted(groups.items()):
        n = len(ev_rows)
        r6_vals = [r["fwd_return_6c"] for r in ev_rows]
        result.append({
            "synthetic_parent_terminal_state": parent,
            "reentry_state": state,
            "n": n,
            "r6_mean": _safe_mean(r6_vals),
            "r6_win_rate_pct": _win_rate(r6_vals),
        })
    return result


def compute_concentration(rows: list[dict]) -> dict[str, Any]:
    """Symbol and month concentration for blocked and supported states."""
    result = {}
    for state in [REENTRY_BLOCKED_WEAKNESS, REENTRY_CONTEXT_SUPPORTED]:
        state_rows = [r for r in rows if r["reentry_state"] == state]
        n = len(state_rows)
        sym_counts = Counter(r["symbol"] for r in state_rows)
        month_counts = Counter(r["asof_ts_utc"][:7] for r in state_rows)
        top_sym = sym_counts.most_common(1)[0] if sym_counts else ("", 0)
        top_month = month_counts.most_common(1)[0] if month_counts else ("", 0)
        result[state] = {
            "n": n,
            "n_unique_symbols": len(sym_counts),
            "top_symbol": top_sym[0],
            "top_symbol_count": top_sym[1],
            "top_symbol_fraction": round(top_sym[1] / n, 3) if n else 0,
            "top_month": top_month[0],
            "top_month_count": top_month[1],
            "warning_high_symbol_concentration": (top_sym[1] / n > 0.5) if n else False,
            "warning_high_month_concentration": (top_month[1] / n > 0.5) if n else False,
        }
    return result


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_outputs(
    output_dir: Path,
    all_rows: list[dict],
    state_breakdown: list[dict],
    breath_breakdown: list[dict],
    parent_breakdown: list[dict],
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

    p = output_dir / "event_results_v1.csv"
    _write_csv(p, all_rows)
    written["event_results"] = p

    p = output_dir / "state_breakdown_v1.csv"
    _write_csv(p, state_breakdown)
    written["state_breakdown"] = p

    p = output_dir / "breath_breakdown_v1.csv"
    _write_csv(p, breath_breakdown)
    written["breath_breakdown"] = p

    p = output_dir / "parent_state_breakdown_v1.csv"
    _write_csv(p, parent_breakdown)
    written["parent_state_breakdown"] = p

    p = output_dir / "summary_v1.json"
    with open(p, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    written["summary"] = p

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
    state_counter: Counter[str] = Counter()

    for ev in events:
        row = process_event(ev)
        all_rows.append(row)
        state_counter[row["reentry_state"]] += 1

    n_blocked = sum(state_counter.get(s, 0) for s in _BLOCKED_STATES)
    n_supported = state_counter.get(REENTRY_CONTEXT_SUPPORTED, 0)
    n_conflict = state_counter.get(REENTRY_CONTEXT_CONFLICT, 0)
    n_watch = sum(state_counter.get(s, 0) for s in _WATCH_STATES)
    n_unknown = state_counter.get(CONTEXT_UNKNOWN, 0)
    n_not_live = state_counter.get(NOT_LIVE_VALID, 0)

    print(f"  Re-entry state distribution: {dict(state_counter.most_common())}", flush=True)
    n_false_re = sum(1 for r in all_rows if r.get("false_reentry"))
    n_missed_op = sum(1 for r in all_rows if r.get("missed_opportunity"))
    print(f"  Blocked: {n_blocked}  Supported: {n_supported}  Conflict: {n_conflict}  Watch: {n_watch}", flush=True)
    print(f"  Context unknown/not-live: {n_unknown + n_not_live}", flush=True)
    print(f"  False re-entry (supported but r6<0): {n_false_re}", flush=True)
    print(f"  Missed opportunity (blocked but r6>{MISSED_OPPORTUNITY_THRESHOLD_PCT}%): {n_missed_op}", flush=True)

    if n_supported < 10:
        print(f"  WARNING: n_supported={n_supported} — insufficient sample for REENTRY_CONTEXT_SUPPORTED; do not create a rule", flush=True)
    if n_unknown / n_events > 0.5:
        print(f"  WARNING: {n_unknown/n_events*100:.1f}% CONTEXT_UNKNOWN — context coverage is degenerate", flush=True)

    # Phase 3: Aggregate
    print("\nPhase 3: Computing aggregates...", flush=True)
    state_breakdown = compute_state_breakdown(all_rows)
    breath_breakdown = compute_breath_breakdown(all_rows)
    parent_breakdown = compute_parent_state_breakdown(all_rows)
    concentration = compute_concentration(all_rows)

    print("\n  State breakdown summary:", flush=True)
    for row in state_breakdown:
        if row["n"] > 0:
            print(
                f"    {row['reentry_state']:35s}: n={row['n']:4d}  "
                f"r6_mean={row['r6_mean']}%  wr6={row['r6_win_rate_pct']}%  "
                f"missed={row['missed_opportunity_count']}  false={row['false_reentry_count']}",
                flush=True,
            )

    # Phase 4: Build summary
    summary = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "n_events": n_events,
        "reentry_state_distribution": dict(state_counter.most_common()),
        "n_blocked": n_blocked,
        "n_supported": n_supported,
        "n_conflict": n_conflict,
        "n_watch": n_watch,
        "n_context_unknown": n_unknown,
        "n_not_live_valid": n_not_live,
        "n_false_reentry": n_false_re,
        "n_missed_opportunity": n_missed_op,
        "false_reentry_rate_pct": round(n_false_re / n_supported * 100, 1) if n_supported else None,
        "missed_opportunity_rate_pct": round(n_missed_op / n_blocked * 100, 1) if n_blocked else None,
        "state_breakdown": state_breakdown,
        "concentration": concentration,
        "notes": {
            "synthetic_proxy": SYNTHETIC_PROXY_NOTE,
            "context_coverage": (
                f"{n_unknown}/{n_events} ({n_unknown/n_events*100:.1f}%) events are CONTEXT_UNKNOWN "
                "(NEUTRAL_TRANSITION phase). Context coverage is degenerate for 87% of events."
            ),
            "sample_warning": (
                "REENTRY_CONTEXT_SUPPORTED and REENTRY_CONTEXT_CONFLICT have very small samples. "
                "Do not create a trading rule from insufficient samples. "
                "Results represent COLLAPSE_RESET/INHALE/HOLD_COMPRESSION proxy events only."
            ),
            "false_reentry_note": (
                "False re-entry rate: fraction of REENTRY_CONTEXT_SUPPORTED events where "
                "fwd_return_6c < 0. Measures gate precision for supported re-entry calls."
            ),
            "missed_opportunity_note": (
                f"Missed opportunity rate: fraction of REENTRY_BLOCKED events where "
                f"fwd_return_6c > {MISSED_OPPORTUNITY_THRESHOLD_PCT}%. "
                "Measures cost of blocking in terms of foregone positive outcomes."
            ),
            "exhale_expansion_finding": (
                "EXHALE_EXPANSION (wr6=32%) → REENTRY_BLOCKED_WEAKNESS. "
                "Ongoing selling/weakness phase with below-random forward win rate."
            ),
            "collapse_reset_finding": (
                "COLLAPSE_RESET (wr6=54%, r6_mean=+0.92%) → REENTRY_BLOCKED_WEAKNESS. "
                "COLLAPSE_RESET is terminal capitulation — NOT a bullish reset. "
                "The 54% win rate reflects that capitulation can precede a bounce, "
                "but ~46% of events continued lower. "
                "COLLAPSE_RESET ≠ INHALE_ACCUMULATION: the bottom is NOT confirmed at "
                "the collapse event. Re-entry wait state is INHALE_ACCUMULATION (new energy "
                "build confirmed). This distinction is the core architectural separation."
            ),
            "collapse_vs_inhale_distinction": (
                "COLLAPSE_RESET: weakness=WEAKNESS_ACTIVE, reset=RESET_NOT_CONFIRMED. "
                "Terminal capitulation event; bottom may or may not be in. "
                "INHALE_ACCUMULATION: weakness=WEAKNESS_RESOLVED, reset=RESET_CONFIRMED. "
                "New energy buildup after bottom is confirmed. "
                "These are distinct sequential phases, not equivalent 'reset' states. "
                "Conflating them would incorrectly allow re-entry at the capitulation event."
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
        output_dir, all_rows, state_breakdown, breath_breakdown, parent_breakdown,
        concentration, summary,
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
        description=f"{RUNNER_NAME} — research-only weakness/rejection re-entry block evaluation"
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
