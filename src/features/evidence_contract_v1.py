"""
SYNTH v2
Module: features.evidence_contract_v1
Purpose:
    Shared, generic mapping primitives for completing canonical
    `SignalHorizonV1` evidence contracts (docs/architecture/
    multi_horizon_signal_contract_v1.md, issue #243) for existing
    market-only producers.

Scope (issue #669):
    This module performs contract *completion* only. It does not compute,
    reinterpret, or threshold any market indicator. Family-specific adapters
    (structure_evidence_contract_v1.py, relative_strength_evidence_contract_v1.py)
    pass already-computed producer rows through these pure functions to
    produce a `SignalHorizonV1Evidence` object.

Boundary:
    - read-only, no DB access, no I/O;
    - no new indicator/classification thresholds;
    - never falls back to "latest" state; callers must supply the exact
      historical row and the exact evaluation timestamp, so replay callers
      cannot accidentally observe current/live truth for a historical asof;
    - `effective_horizon` is never inferred from `input_interval` (#243 3.3);
    - `freshness` is producer-owned per #243 3.5. Neither `structure_state_engine`
      nor `relative_strength_snapshot` has a reviewed staleness rule, so this
      module does not invent one (no interval-relative threshold, no
      caller-supplied threshold). `compute_freshness` can only distinguish
      "no asof at all" (INSUFFICIENT_DATA) from "asof present, freshness not
      yet owner-defined" (UNKNOWN). Promoting a producer to FRESH/STALE
      requires an explicit upstream owner decision recording a reviewed rule
      for that producer, tracked outside this module;
    - unknown/unmapped/missing required fields fail closed rather than being
      guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class EffectiveHorizon:
    VERY_SHORT = "VERY_SHORT"
    SHORT = "SHORT"
    MID = "MID"
    LONG = "LONG"
    REGIME = "REGIME"
    MULTI_HORIZON = "MULTI_HORIZON"
    UNKNOWN = "UNKNOWN"


class FreshnessState:
    # FRESH/STALE are reserved for a future producer-owned staleness rule.
    # `compute_freshness` in this module never emits them today.
    FRESH = "FRESH"
    STALE = "STALE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNKNOWN = "UNKNOWN"


class LifecycleStatus:
    MEASURED = "MEASURED"
    UNMEASURED = "UNMEASURED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class EvidenceStatus:
    """Top-level usability status of a completed evidence contract."""

    VALID = "VALID"
    STALE = "STALE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Reason codes are deterministic and enumerated. Do not add ad hoc strings
# at call sites; extend this list instead.
class ReasonCode:
    MISSING_ASOF_TS = "MISSING_ASOF_TS"
    ASOF_AFTER_EVALUATION_TS = "ASOF_AFTER_EVALUATION_TS"
    FRESHNESS_NOT_OWNER_DEFINED = "FRESHNESS_NOT_OWNER_DEFINED"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    UNMAPPED_HORIZON = "UNMAPPED_HORIZON"
    UNKNOWN_INPUT_INTERVAL = "UNKNOWN_INPUT_INTERVAL"
    MISSING_ENGINE_NAME = "MISSING_ENGINE_NAME"
    UNEXPECTED_ENGINE_NAME = "UNEXPECTED_ENGINE_NAME"
    MISSING_ENGINE_VERSION = "MISSING_ENGINE_VERSION"
    UNSUPPORTED_MODEL_VERSION = "UNSUPPORTED_MODEL_VERSION"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    LIFECYCLE_UNMEASURED = "LIFECYCLE_UNMEASURED"


# Deterministic unit conversion only (not a market threshold, and not
# currently consulted by `compute_freshness` -- reserved for a future
# producer-owned freshness rule that needs interval-relative age math).
_INTERVAL_SECONDS: dict[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def interval_to_seconds(input_interval: str | None) -> int | None:
    """Deterministic candle-interval-code to seconds mapping. Returns None
    for an unrecognized/unmapped interval code rather than guessing."""
    if input_interval is None:
        return None
    return _INTERVAL_SECONDS.get(input_interval)


def validate_input_interval(input_interval: str | None) -> tuple[str, ...]:
    """Flag an unrecognized/unmapped `input_interval` deterministically."""
    if interval_to_seconds(input_interval) is None:
        return (ReasonCode.UNKNOWN_INPUT_INTERVAL,)
    return ()


def normalize_to_utc(dt: datetime | None) -> datetime | None:
    """Normalize a producer timestamp to one internal UTC representation.

    Persisted `structure_state`/`relative_strength_snapshot` rows are
    naive-UTC (the writer strips tzinfo before persisting); callers may also
    supply timezone-aware UTC. Both are deterministically mapped onto the
    same aware-UTC value so comparisons never raise
    `TypeError: can't compare offset-naive and offset-aware datetimes` and
    never silently assume local time. A non-UTC aware offset is converted to
    UTC via `astimezone`, not truncated/ignored.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ObservedLifecycle:
    status: str = LifecycleStatus.UNMEASURED
    sample_count: int | None = None
    p25_seconds: int | None = None
    p50_seconds: int | None = None
    p75_seconds: int | None = None
    p90_seconds: int | None = None
    censoring_method: str | None = None
    analysis_ref: str | None = None


UNMEASURED_LIFECYCLE = ObservedLifecycle(status=LifecycleStatus.UNMEASURED)


@dataclass(frozen=True, slots=True)
class SignalHorizonV1Evidence:
    """Completed `SignalHorizonV1` evidence for one family/component pair."""

    family: str
    component: str
    market: str
    status: str
    model_id: str | None
    model_version: str | None
    input_interval: str | None
    lookback_horizon: str | None
    effective_horizon: str
    observed_lifecycle: ObservedLifecycle
    asof_ts: datetime | None
    freshness: str
    provenance: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def compute_freshness(
    *,
    asof_ts: datetime | None,
    evaluated_at: datetime,
) -> tuple[datetime | None, str, tuple[str, ...]]:
    """Producer-owned freshness (#243 3.5), not invented here.

    Returns `(normalized_asof_ts, freshness, reason_codes)`. Neither
    `structure_state_engine` nor `relative_strength_snapshot` has a reviewed
    staleness rule, so this function never classifies FRESH/STALE from an
    age-vs-interval computation. It only distinguishes:

    - no `asof_ts` at all -> INSUFFICIENT_DATA;
    - an `asof_ts` dated after `evaluated_at` -> INSUFFICIENT_DATA (a
      producer timestamp from the future relative to the replay/evaluation
      point is a data-integrity contradiction, not a staleness judgement,
      so this is a zero-tolerance validity check rather than an invented
      threshold);
    - otherwise -> UNKNOWN, because freshness has not yet been defined by
      the owning producer.

    Both timestamps are normalized to aware UTC via `normalize_to_utc`
    before comparison.
    """
    normalized_asof_ts = normalize_to_utc(asof_ts)
    normalized_evaluated_at = normalize_to_utc(evaluated_at)

    if normalized_asof_ts is None:
        return None, FreshnessState.INSUFFICIENT_DATA, (ReasonCode.MISSING_ASOF_TS,)

    if normalized_asof_ts > normalized_evaluated_at:
        return (
            normalized_asof_ts,
            FreshnessState.INSUFFICIENT_DATA,
            (ReasonCode.ASOF_AFTER_EVALUATION_TS,),
        )

    return (
        normalized_asof_ts,
        FreshnessState.UNKNOWN,
        (ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,),
    )


# Reason codes that must always fail an evidence contract closed to
# INSUFFICIENT_DATA regardless of freshness. `STALE_EVIDENCE` is reserved
# for a future producer-owned staleness rule and is deliberately excluded:
# staleness alone should resolve to `STALE`, not `INSUFFICIENT_DATA`, once
# such a rule exists.
HARD_FAIL_REASON_CODES: frozenset[str] = frozenset(
    {
        ReasonCode.MISSING_ASOF_TS,
        ReasonCode.ASOF_AFTER_EVALUATION_TS,
        ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,
        ReasonCode.UNKNOWN_INPUT_INTERVAL,
        ReasonCode.UNMAPPED_HORIZON,
        ReasonCode.MISSING_ENGINE_NAME,
        ReasonCode.UNEXPECTED_ENGINE_NAME,
        ReasonCode.MISSING_ENGINE_VERSION,
        ReasonCode.UNSUPPORTED_MODEL_VERSION,
        ReasonCode.MISSING_PROVENANCE,
    }
)


def resolve_status(
    *,
    freshness: str,
    extra_reason_codes: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    """Fold freshness plus any additional fail-closed reason codes into a
    single top-level `EvidenceStatus`."""
    reason_codes = tuple(extra_reason_codes)

    if freshness in (FreshnessState.INSUFFICIENT_DATA, FreshnessState.UNKNOWN):
        return EvidenceStatus.INSUFFICIENT_DATA, reason_codes
    if any(code in HARD_FAIL_REASON_CODES for code in reason_codes):
        return EvidenceStatus.INSUFFICIENT_DATA, reason_codes
    if freshness == FreshnessState.STALE:
        return EvidenceStatus.STALE, reason_codes

    return EvidenceStatus.VALID, reason_codes
