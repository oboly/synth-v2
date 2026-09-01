"""
SYNTH v2
Module: features.structure_evidence_contract_v1
Purpose:
    Complete the canonical `SignalHorizonV1` evidence contract (#243) for the
    existing PRICE_STRUCTURE producer, and for the RECLAIM component of the
    RELATIVE_STRENGTH family that shares the same `structure_state` table.

Canonical producer (unchanged, not reimplemented here):
    src/structure/trend_state_v1.py (ENGINE_NAME/ENGINE_VERSION)
    src/measurement/run_structure_state_engine.py (`structure_state` table)

Per docs/architecture/regime_evidence_matrix_audit_v1.md 3.1/3.2:
    - `structure_state` rows carry `asof_ts_utc` and `interval_code` per row,
      but no `effective_horizon`, no freshness rule, and no itemized
      reason-code contract. This module maps the existing row 1:1 onto
      `SignalHorizonV1Evidence` without inventing any new trend/pullback/
      reclaim threshold.
    - `effective_horizon` is producer-owned metadata (#243 3.3) that
      `structure_state_engine` has never declared. Per #243 12.3 ("leave
      unknown fields unknown rather than infer them") this module emits
      `UNKNOWN` and fails the evidence closed to `INSUFFICIENT_DATA` rather
      than inferring an horizon from `interval_code`.
    - `reclaim_state`/`reclaim_score` are exposed here as their own
      RELATIVE_STRENGTH component, kept separate from
      `relative_strength_evidence_contract_v1.py`'s cross-sectional-rank
      component per the audit's item 3 (reconciliation of the two lanes is
      an explicit open owner decision, not resolved by this contract
      completion).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from src.features.evidence_contract_v1 import (
    EffectiveHorizon,
    ReasonCode,
    SignalHorizonV1Evidence,
    UNMEASURED_LIFECYCLE,
    compute_freshness,
    resolve_status,
)

FAMILY_PRICE_STRUCTURE = "PRICE_STRUCTURE"
FAMILY_RELATIVE_STRENGTH = "RELATIVE_STRENGTH"

COMPONENT_TREND = "TREND"
COMPONENT_PULLBACK = "PULLBACK"
COMPONENT_RANGE = "RANGE"
COMPONENT_RECLAIM = "RECLAIM"

ENGINE_NAME = "structure_state_engine"

# Engine versions this contract has been reviewed against. An unreviewed
# engine_version fails closed rather than being silently trusted.
SUPPORTED_ENGINE_VERSIONS = frozenset({"1.2"})

_MARKET = "asset"

_STATE_FIELD_BY_COMPONENT: dict[str, tuple[str, str]] = {
    COMPONENT_TREND: ("trend_state", "trend_score"),
    COMPONENT_PULLBACK: ("pullback_state", "pullback_score"),
    COMPONENT_RANGE: ("range_state", "range_score"),
    COMPONENT_RECLAIM: ("reclaim_state", "reclaim_score"),
}


def _model_version_reason_codes(engine_version: str | None) -> tuple[str, ...]:
    if engine_version is None or engine_version not in SUPPORTED_ENGINE_VERSIONS:
        return (ReasonCode.UNSUPPORTED_MODEL_VERSION,)
    return ()


def build_structure_component_evidence(
    row: Mapping[str, Any],
    component: str,
    *,
    family: str,
    evaluated_at: datetime,
    stale_after_multiplier: float = 2.0,
) -> SignalHorizonV1Evidence:
    """Map one `structure_state` row + component onto `SignalHorizonV1Evidence`.

    `row` must be the exact historical (or current) `structure_state` row for
    the asof being evaluated; this function performs no lookup of its own, so
    a replay caller can never receive a "latest" fallback for a historical
    asof.
    """
    if component not in _STATE_FIELD_BY_COMPONENT:
        raise ValueError(f"Unknown structure_state component: {component!r}")

    state_field, score_field = _STATE_FIELD_BY_COMPONENT[component]

    asof_ts = row.get("asof_ts_utc")
    input_interval = row.get("interval_code")
    engine_version = row.get("engine_version")

    freshness, freshness_reason_codes = compute_freshness(
        asof_ts=asof_ts,
        evaluated_at=evaluated_at,
        input_interval=input_interval,
        stale_after_multiplier=stale_after_multiplier,
    )

    extra_reason_codes = freshness_reason_codes
    extra_reason_codes += _model_version_reason_codes(engine_version)
    # effective_horizon is never declared by this producer today; the
    # contract must fail closed rather than infer it from interval_code.
    extra_reason_codes += (ReasonCode.UNMAPPED_HORIZON,)

    status, reason_codes = resolve_status(
        freshness=freshness,
        extra_reason_codes=extra_reason_codes,
    )

    return SignalHorizonV1Evidence(
        family=family,
        component=component,
        market=_MARKET,
        status=status,
        model_id=ENGINE_NAME if engine_version is not None else None,
        model_version=engine_version,
        input_interval=input_interval,
        lookback_horizon=None,
        effective_horizon=EffectiveHorizon.UNKNOWN,
        observed_lifecycle=UNMEASURED_LIFECYCLE,
        asof_ts=asof_ts,
        freshness=freshness,
        provenance={
            "engine_name": row.get("engine_name"),
            "engine_version": engine_version,
            "asset_id": row.get("asset_id"),
            "venue": row.get("venue"),
        },
        raw={
            "state": row.get(state_field),
            "score": row.get(score_field),
        },
        reason_codes=reason_codes,
    )


def build_price_structure_evidence(
    row: Mapping[str, Any],
    *,
    evaluated_at: datetime,
    stale_after_multiplier: float = 2.0,
) -> dict[str, SignalHorizonV1Evidence]:
    """Complete PRICE_STRUCTURE evidence (TREND/PULLBACK/RANGE) for one row."""
    return {
        component: build_structure_component_evidence(
            row,
            component,
            family=FAMILY_PRICE_STRUCTURE,
            evaluated_at=evaluated_at,
            stale_after_multiplier=stale_after_multiplier,
        )
        for component in (COMPONENT_TREND, COMPONENT_PULLBACK, COMPONENT_RANGE)
    }


def build_reclaim_evidence(
    row: Mapping[str, Any],
    *,
    evaluated_at: datetime,
    stale_after_multiplier: float = 2.0,
) -> SignalHorizonV1Evidence:
    """Complete the RECLAIM component of RELATIVE_STRENGTH for one row."""
    return build_structure_component_evidence(
        row,
        COMPONENT_RECLAIM,
        family=FAMILY_RELATIVE_STRENGTH,
        evaluated_at=evaluated_at,
        stale_after_multiplier=stale_after_multiplier,
    )
