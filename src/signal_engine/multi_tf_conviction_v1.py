"""Issue #591: Multi-TF Conviction — LONG/MID/SHORT composition contract v1.

Ownership
---------

This module is the strategy-owned horizon-role interpretation authorized by
``docs/architecture/multi_horizon_signal_contract_v1.md`` (Issue #243)
section 6: "A downstream strategy may assign different roles to horizons,
but those roles belong to that strategy's own reviewed contract. For
example, LONG = thesis, MID = exposure, SHORT = entry timing is a strategy
interpretation, not a generic truth created by this contract." Issue #591 is
that strategy.

It is a pure, deterministic composition function: three independent
horizons in, three independent horizon results out. It never recomputes an
upstream indicator, never blends horizons into one opaque aggregate score,
and never reads account state. Read-only, market-only, account-agnostic.

Repository audit (see docs/architecture/multi_tf_conviction_contract_v1.md
for the full record): no production module on ``main`` currently emits the
full ``SignalHorizonV1`` contract (``effective_horizon`` as a field exists
only in this doc and in Issue #593's research-only replay module, which is
explicitly excluded from production use here). This module therefore does
not wire any concrete evidence source yet -- that is deferred to a follow-up
issue once a canonical per-horizon evidence producer exists. Every horizon
without a supplied, fresh, replay-safe ``HorizonEvidenceV1`` fails closed to
``CONVICTION_INSUFFICIENT_DATA`` rather than inventing interpretation logic
over raw indicators.

Independence invariant
-----------------------

``evaluate_horizon_conviction_v1`` for LONG, MID, and SHORT never reads each
other's evidence or output. There is no shared mutable state and no
cross-horizon averaging anywhere in this module. This is what makes the core
#591 acceptance invariant -- "the same asset may simultaneously be LONG
strong, MID weak, SHORT weak" -- true by construction rather than by a
threshold tuned to make it look true.

Safety:
  market_only=1
  account_awareness=0
  selection_engine_changes=0
  decision_gate_changes=0
  execution_planner_changes=0
  executor_changes=0
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

SCHEMA_VERSION: Final[str] = "multi_tf_conviction_v1"
MODEL_VERSION: Final[str] = "1.0"

# --- Canonical horizon identity ---------------------------------------------
#
# Reuses the exact effective_horizon vocabulary from
# docs/architecture/multi_horizon_signal_contract_v1.md section 3.3 (a
# subset of it: this strategy only assigns roles to LONG/MID/SHORT).

HORIZON_LONG: Final[str] = "LONG"
HORIZON_MID: Final[str] = "MID"
HORIZON_SHORT: Final[str] = "SHORT"
_CANONICAL_HORIZONS: Final[tuple[str, ...]] = (HORIZON_LONG, HORIZON_MID, HORIZON_SHORT)

# --- Freshness vocabulary ----------------------------------------------------
#
# Reuses the exact freshness vocabulary from
# docs/architecture/multi_horizon_signal_contract_v1.md section 3.5.

FRESHNESS_FRESH: Final[str] = "FRESH"
FRESHNESS_STALE: Final[str] = "STALE"
FRESHNESS_INSUFFICIENT_DATA: Final[str] = "INSUFFICIENT_DATA"
FRESHNESS_UNKNOWN: Final[str] = "UNKNOWN"

# --- Evidence directional-state vocabulary ----------------------------------
#
# The caller/adapter (a future, separately reviewed task) is responsible for
# mapping whatever canonical per-horizon evidence it owns into this small,
# already-interpreted vocabulary before calling this module. This module
# never sees raw candles/indicators and never recomputes them -- it only
# classifies an already-produced qualitative state, which is the strategy
# interpretation section 6 of the #243 contract reserves to #591.

EVIDENCE_STATE_STRONG_POSITIVE: Final[str] = "STRONG_POSITIVE"
EVIDENCE_STATE_POSITIVE: Final[str] = "POSITIVE"
EVIDENCE_STATE_NEUTRAL: Final[str] = "NEUTRAL"
EVIDENCE_STATE_NEGATIVE: Final[str] = "NEGATIVE"
EVIDENCE_STATE_INVALIDATING: Final[str] = "INVALIDATING"

# --- Conviction state (output) ----------------------------------------------

CONVICTION_STRONG: Final[str] = "STRONG"
CONVICTION_MODERATE: Final[str] = "MODERATE"
CONVICTION_WEAK: Final[str] = "WEAK"
CONVICTION_INVALIDATED: Final[str] = "INVALIDATED"
CONVICTION_INSUFFICIENT_DATA: Final[str] = "INSUFFICIENT_DATA"

_EVIDENCE_STATE_TO_CONVICTION: Final[dict[str, str]] = {
    EVIDENCE_STATE_STRONG_POSITIVE: CONVICTION_STRONG,
    EVIDENCE_STATE_POSITIVE: CONVICTION_MODERATE,
    EVIDENCE_STATE_NEUTRAL: CONVICTION_WEAK,
    EVIDENCE_STATE_NEGATIVE: CONVICTION_WEAK,
    EVIDENCE_STATE_INVALIDATING: CONVICTION_INVALIDATED,
}

# --- Reason codes ------------------------------------------------------------

REASON_OK: Final[str] = "OK"
REASON_EVIDENCE_MISSING: Final[str] = "EVIDENCE_MISSING"
REASON_EVIDENCE_HORIZON_MISMATCH: Final[str] = "EVIDENCE_HORIZON_MISMATCH"
REASON_EVIDENCE_NOT_REPLAY_SAFE: Final[str] = "EVIDENCE_NOT_REPLAY_SAFE"
REASON_EVIDENCE_STALE: Final[str] = "EVIDENCE_STALE"
REASON_EVIDENCE_INSUFFICIENT_DATA: Final[str] = "EVIDENCE_INSUFFICIENT_DATA"
REASON_EVIDENCE_FRESHNESS_UNKNOWN: Final[str] = "EVIDENCE_FRESHNESS_UNKNOWN"
REASON_EVIDENCE_STATE_UNRECOGNIZED: Final[str] = "EVIDENCE_STATE_UNRECOGNIZED"
REASON_EVIDENCE_ASOF_MISSING: Final[str] = "EVIDENCE_ASOF_MISSING"

# --- Derived, horizon-scoped advisory semantics -----------------------------
#
# Advisory/market-interpretation labels only. They grant no permission and
# create no execution intent (never reach decision_gate/execution_planner/
# executor). Each horizon's derived field is computed only from that same
# horizon's own conviction_state -- LONG's capital_floor_state can never be
# influenced by MID or SHORT evidence.

DERIVED_FIELD_BY_HORIZON: Final[dict[str, str]] = {
    HORIZON_LONG: "capital_floor_state",
    HORIZON_MID: "exposure_state",
    HORIZON_SHORT: "entry_add_timing_state",
}

CAPITAL_FLOOR_CORE_INTACT: Final[str] = "CORE_INTACT"
CAPITAL_FLOOR_CORE_AT_RISK: Final[str] = "CORE_AT_RISK"
CAPITAL_FLOOR_CORE_COLLAPSED: Final[str] = "CORE_COLLAPSED"
CAPITAL_FLOOR_UNKNOWN: Final[str] = "UNKNOWN"

EXPOSURE_EXPAND: Final[str] = "EXPAND_EXPOSURE"
EXPOSURE_MAINTAIN: Final[str] = "MAINTAIN_EXPOSURE"
EXPOSURE_REDUCE: Final[str] = "REDUCE_EXPOSURE"
EXPOSURE_SUPPRESS: Final[str] = "SUPPRESS_EXPOSURE"
EXPOSURE_UNKNOWN: Final[str] = "UNKNOWN"

TIMING_FAVORABLE: Final[str] = "FAVORABLE_ADD_TIMING"
TIMING_NEUTRAL: Final[str] = "NEUTRAL_TIMING"
TIMING_UNFAVORABLE: Final[str] = "UNFAVORABLE_TIMING"
TIMING_BLOCKED: Final[str] = "BLOCK_ADD_TIMING"
TIMING_UNKNOWN: Final[str] = "UNKNOWN"

_DERIVED_STATE_BY_HORIZON: Final[dict[str, dict[str, str]]] = {
    HORIZON_LONG: {
        CONVICTION_STRONG: CAPITAL_FLOOR_CORE_INTACT,
        CONVICTION_MODERATE: CAPITAL_FLOOR_CORE_INTACT,
        CONVICTION_WEAK: CAPITAL_FLOOR_CORE_AT_RISK,
        CONVICTION_INVALIDATED: CAPITAL_FLOOR_CORE_COLLAPSED,
        CONVICTION_INSUFFICIENT_DATA: CAPITAL_FLOOR_UNKNOWN,
    },
    HORIZON_MID: {
        CONVICTION_STRONG: EXPOSURE_EXPAND,
        CONVICTION_MODERATE: EXPOSURE_MAINTAIN,
        CONVICTION_WEAK: EXPOSURE_REDUCE,
        CONVICTION_INVALIDATED: EXPOSURE_SUPPRESS,
        CONVICTION_INSUFFICIENT_DATA: EXPOSURE_UNKNOWN,
    },
    HORIZON_SHORT: {
        CONVICTION_STRONG: TIMING_FAVORABLE,
        CONVICTION_MODERATE: TIMING_NEUTRAL,
        CONVICTION_WEAK: TIMING_UNFAVORABLE,
        CONVICTION_INVALIDATED: TIMING_BLOCKED,
        CONVICTION_INSUFFICIENT_DATA: TIMING_UNKNOWN,
    },
}


# --- Evidence input / result output -----------------------------------------


@dataclass(frozen=True)
class HorizonEvidenceV1:
    """Caller-supplied, already-interpreted evidence for one horizon.

    This is a deliberately reduced, honestly-scoped subset of the canonical
    ``SignalHorizonV1`` contract (Issue #243): only the fields this
    composition actually needs to classify conviction and fail closed.
    """

    horizon: str
    state: str
    freshness: str
    asof_ts: datetime | None
    replay_safe: bool
    model_id: str
    model_version: str
    provenance: str
    confidence: float | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HorizonConvictionResultV1:
    horizon: str
    conviction_state: str
    reason_code: str
    derived_state_field: str
    derived_state: str
    confidence: float | None = None
    freshness: str | None = None
    asof_ts: datetime | None = None
    model_id: str | None = None
    model_version: str | None = None
    provenance: str | None = None
    evidence_reason_codes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MultiTFConvictionV1:
    schema_version: str
    model_version: str
    symbol: str
    generated_at_utc: datetime
    conviction_long: HorizonConvictionResultV1
    conviction_mid: HorizonConvictionResultV1
    conviction_short: HorizonConvictionResultV1


def _insufficient(
    horizon: str, reason_code: str, evidence: HorizonEvidenceV1 | None
) -> HorizonConvictionResultV1:
    return HorizonConvictionResultV1(
        horizon=horizon,
        conviction_state=CONVICTION_INSUFFICIENT_DATA,
        reason_code=reason_code,
        derived_state_field=DERIVED_FIELD_BY_HORIZON[horizon],
        derived_state=_DERIVED_STATE_BY_HORIZON[horizon][CONVICTION_INSUFFICIENT_DATA],
        confidence=evidence.confidence if evidence is not None else None,
        freshness=evidence.freshness if evidence is not None else None,
        asof_ts=evidence.asof_ts if evidence is not None else None,
        model_id=evidence.model_id if evidence is not None else None,
        model_version=evidence.model_version if evidence is not None else None,
        provenance=evidence.provenance if evidence is not None else None,
        evidence_reason_codes=evidence.reason_codes if evidence is not None else (),
    )


def evaluate_horizon_conviction_v1(
    horizon: str, evidence: HorizonEvidenceV1 | None
) -> HorizonConvictionResultV1:
    """Evaluate one horizon's conviction from its own evidence only.

    Fails closed to ``CONVICTION_INSUFFICIENT_DATA`` on: missing evidence,
    evidence bound to the wrong horizon, research-only/not-replay-safe
    evidence, a missing ``asof_ts``, non-``FRESH`` freshness, or an
    unrecognized evidence state. Never raises, never recomputes an
    indicator, never reads any other horizon's evidence.
    """
    if horizon not in _CANONICAL_HORIZONS:
        raise ValueError(f"UNKNOWN_HORIZON:{horizon}")

    if evidence is None:
        return _insufficient(horizon, REASON_EVIDENCE_MISSING, None)
    if evidence.horizon != horizon:
        return _insufficient(horizon, REASON_EVIDENCE_HORIZON_MISMATCH, evidence)
    if not evidence.replay_safe:
        return _insufficient(horizon, REASON_EVIDENCE_NOT_REPLAY_SAFE, evidence)
    if evidence.asof_ts is None:
        # A FRESH claim with no as-of timestamp is not replayable and must
        # not be classified as healthy evidence (docs/architecture/
        # multi_horizon_signal_contract_v1.md section 3.5).
        return _insufficient(horizon, REASON_EVIDENCE_ASOF_MISSING, evidence)

    if evidence.freshness == FRESHNESS_STALE:
        return _insufficient(horizon, REASON_EVIDENCE_STALE, evidence)
    if evidence.freshness == FRESHNESS_INSUFFICIENT_DATA:
        return _insufficient(horizon, REASON_EVIDENCE_INSUFFICIENT_DATA, evidence)
    if evidence.freshness != FRESHNESS_FRESH:
        # Covers FRESHNESS_UNKNOWN and any unrecognized freshness string.
        return _insufficient(horizon, REASON_EVIDENCE_FRESHNESS_UNKNOWN, evidence)

    conviction_state = _EVIDENCE_STATE_TO_CONVICTION.get(evidence.state)
    if conviction_state is None:
        return _insufficient(horizon, REASON_EVIDENCE_STATE_UNRECOGNIZED, evidence)

    return HorizonConvictionResultV1(
        horizon=horizon,
        conviction_state=conviction_state,
        reason_code=REASON_OK,
        derived_state_field=DERIVED_FIELD_BY_HORIZON[horizon],
        derived_state=_DERIVED_STATE_BY_HORIZON[horizon][conviction_state],
        confidence=evidence.confidence,
        freshness=evidence.freshness,
        asof_ts=evidence.asof_ts,
        model_id=evidence.model_id,
        model_version=evidence.model_version,
        provenance=evidence.provenance,
        evidence_reason_codes=evidence.reason_codes,
    )


def compose_multi_tf_conviction_v1(
    *,
    symbol: str,
    generated_at_utc: datetime,
    long_evidence: HorizonEvidenceV1 | None,
    mid_evidence: HorizonEvidenceV1 | None,
    short_evidence: HorizonEvidenceV1 | None,
) -> MultiTFConvictionV1:
    """Compose the three independent horizon results for one asset.

    This is three separate calls to ``evaluate_horizon_conviction_v1``, one
    per horizon, stored together for caller convenience only. There is no
    blending, averaging, or any other computation that combines them --
    ``docs/architecture/multi_horizon_signal_contract_v1.md`` section 6
    forbids exactly that ("no opaque averaging of unrelated horizons"), and
    this function structurally cannot produce one because it never
    constructs a value from more than one horizon's evidence.
    """
    return MultiTFConvictionV1(
        schema_version=SCHEMA_VERSION,
        model_version=MODEL_VERSION,
        symbol=symbol,
        generated_at_utc=generated_at_utc,
        conviction_long=evaluate_horizon_conviction_v1(HORIZON_LONG, long_evidence),
        conviction_mid=evaluate_horizon_conviction_v1(HORIZON_MID, mid_evidence),
        conviction_short=evaluate_horizon_conviction_v1(HORIZON_SHORT, short_evidence),
    )
