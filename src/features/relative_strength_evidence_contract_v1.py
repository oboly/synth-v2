"""
SYNTH v2
Module: features.relative_strength_evidence_contract_v1
Purpose:
    Complete the canonical `SignalHorizonV1` evidence contract (#243) for the
    cross-sectional-rank component of RELATIVE_STRENGTH, produced by
    `src/features/relative_strength_snapshot.py` (`relative_strength_snapshot`
    table). Does not recompute return/rank/zscore.

Per docs/architecture/regime_evidence_matrix_audit_v1.md 3.2:
    - `relative_strength_snapshot` persists `snapshot_ts_utc` per row. Per
      issue #669's explicit correction, this is the producer's `asof_ts`
      equivalent -- it is mapped here directly, not treated as absent.
    - The table has no `model_id`/`model_version` column at all (unlike
      `structure_state`, which at least has `engine_name`/`engine_version`).
      Per #243 3.6 every signal must expose deterministic provenance; since
      none is persisted, this contract fails closed to
      `INSUFFICIENT_DATA` / `MISSING_PROVENANCE` rather than fabricating an
      identity, unless a caller passes an explicit, already-reviewed
      `model_id`/`model_version` pair for the run that produced the row.
    - `input_interval` is hardcoded to `1d` in the producer's SQL (always
      queries `obs_market_candle` with `interval_code = '1d'`); this is a
      deterministic mapping of existing producer behaviour, not a new
      assumption.
    - `lookback_horizon` maps directly to the persisted `lookback_days`
      column (e.g. 7, 14), expressed as `"<n>d"` per #243 3.2 formatting.
    - This is generic cross-asset relative strength, not ETH/BTC leadership;
      the audit found no BTC/ETH-specific logic in this producer, so none is
      added here.
    - `freshness` is producer-owned (#243 3.5) and undeclared here; see
      `evidence_contract_v1.compute_freshness`. This module does not invent
      a staleness rule for `relative_strength_snapshot`.
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

FAMILY_RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
COMPONENT_CROSS_SECTIONAL_RANK = "CROSS_SECTIONAL_RANK"

INPUT_INTERVAL = "1d"
_MARKET = "asset"


def build_cross_sectional_rank_evidence(
    row: Mapping[str, Any],
    *,
    evaluated_at: datetime,
    model_id: str | None = None,
    model_version: str | None = None,
) -> SignalHorizonV1Evidence:
    """Map one `relative_strength_snapshot` row onto `SignalHorizonV1Evidence`.

    `row` must be the exact historical (or current) snapshot row for the
    asof being evaluated; this function performs no lookup of its own, so a
    replay caller can never receive a "latest" fallback for a historical
    asof.

    `model_id`/`model_version` are not persisted by the producer today, so
    they must be supplied explicitly by a caller that owns a reviewed
    identity for the run; omitting them fails the evidence closed rather
    than fabricating provenance.
    """
    raw_asof_ts = row.get("snapshot_ts_utc")
    lookback_days = row.get("lookback_days")
    lookback_horizon = f"{lookback_days}d" if lookback_days is not None else None

    normalized_asof_ts, freshness, freshness_reason_codes = compute_freshness(
        asof_ts=raw_asof_ts,
        evaluated_at=evaluated_at,
    )

    extra_reason_codes = freshness_reason_codes
    if model_id is None or model_version is None:
        extra_reason_codes += (ReasonCode.MISSING_PROVENANCE,)
    # effective_horizon is not declared by this producer; fail closed rather
    # than infer REGIME/MID/etc. from lookback_days.
    extra_reason_codes += (ReasonCode.UNMAPPED_HORIZON,)

    status, reason_codes = resolve_status(
        freshness=freshness,
        extra_reason_codes=extra_reason_codes,
    )

    return SignalHorizonV1Evidence(
        family=FAMILY_RELATIVE_STRENGTH,
        component=COMPONENT_CROSS_SECTIONAL_RANK,
        market=_MARKET,
        status=status,
        model_id=model_id,
        model_version=model_version,
        input_interval=INPUT_INTERVAL,
        lookback_horizon=lookback_horizon,
        effective_horizon=EffectiveHorizon.UNKNOWN,
        observed_lifecycle=UNMEASURED_LIFECYCLE,
        asof_ts=normalized_asof_ts,
        freshness=freshness,
        provenance={
            "asset_id": row.get("asset_id"),
            "universe_size": row.get("universe_size"),
        },
        raw={
            "return_pct": row.get("return_pct"),
            "rank_value": row.get("rank_value"),
            "rank_pct": row.get("rank_pct"),
            "zscore": row.get("zscore"),
        },
        reason_codes=reason_codes,
    )
