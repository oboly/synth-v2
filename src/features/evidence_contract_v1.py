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
    - unknown/unmapped/missing required fields fail closed rather than being
      guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    STALE_EVIDENCE = "STALE_EVIDENCE"
    UNMAPPED_HORIZON = "UNMAPPED_HORIZON"
    UNKNOWN_INPUT_INTERVAL = "UNKNOWN_INPUT_INTERVAL"
    UNSUPPORTED_MODEL_VERSION = "UNSUPPORTED_MODEL_VERSION"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    LIFECYCLE_UNMEASURED = "LIFECYCLE_UNMEASURED"


# Deterministic unit conversion only (not a market threshold). Extend rather
# than infer new interval codes silently.
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
    input_interval: str | None,
    stale_after_multiplier: float = 2.0,
) -> tuple[str, tuple[str, ...]]:
    """Generic, producer-agnostic freshness rule.

    This is contract-completion infrastructure (issue #669), not a
    structure/relative-strength indicator threshold: it only measures the
    age of an already-produced `asof_ts` against a multiple of the
    producer's own declared `input_interval` bar duration. No structure or
    relative-strength classification logic is touched.
    """
    if asof_ts is None:
        return FreshnessState.INSUFFICIENT_DATA, (ReasonCode.MISSING_ASOF_TS,)

    interval_seconds = interval_to_seconds(input_interval)
    if interval_seconds is None:
        return FreshnessState.UNKNOWN, (ReasonCode.UNKNOWN_INPUT_INTERVAL,)

    age = evaluated_at - asof_ts
    max_age = timedelta(seconds=interval_seconds * stale_after_multiplier)

    if age < timedelta(0):
        # Historical replay must never treat a future-dated row as fresh.
        return FreshnessState.STALE, (ReasonCode.STALE_EVIDENCE,)

    if age > max_age:
        return FreshnessState.STALE, (ReasonCode.STALE_EVIDENCE,)

    return FreshnessState.FRESH, ()


# Reason codes that must always fail an evidence contract closed to
# INSUFFICIENT_DATA regardless of freshness. `STALE_EVIDENCE` is
# deliberately excluded: staleness alone must resolve to `STALE`, not
# `INSUFFICIENT_DATA`, so consumers can distinguish "usable but old" from
# "cannot be trusted at all".
HARD_FAIL_REASON_CODES: frozenset[str] = frozenset(
    {
        ReasonCode.MISSING_ASOF_TS,
        ReasonCode.UNKNOWN_INPUT_INTERVAL,
        ReasonCode.UNMAPPED_HORIZON,
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
