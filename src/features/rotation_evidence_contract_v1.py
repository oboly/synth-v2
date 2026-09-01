"""
SYNTH v2
Module: features.rotation_evidence_contract_v1
Purpose:
    Complete the canonical `SignalHorizonV1` evidence contract (#243) for the
    per-asset Market Rotation Pressure V1 producer
    (`src/research/run_market_rotation_pressure_v1.py`,
    `market_rotation_pressure_observation_v1` table), following the #676
    owner decision that promoted this lane to the canonical `ROTATION`
    market-evidence owner.

Owner decision (#676, resolving the `BLOCKED_OWNER_DECISION` finding in
`docs/architecture/rotation_pressure_v1_authority_audit_v1.md`):
    - `market_rotation_pressure_v1` (the broad/regime V1 lane only) is
      promoted as the canonical production-safe market evidence owner for
      `family=ROTATION`. #593's faster C1/C2/C3 multi-horizon Rotation
      candidates are explicitly NOT promoted and are not read by this
      module.
    - Evidence/reporting authority only: no `selection_engine`, account,
      `decision_gate`, `execution_planner`, `executor`, or runtime/deploy
      authority is granted or implied.

Full reconciliation rationale, horizon interpretation, and remaining
fail-closed gaps are documented in
`docs/architecture/rotation_pressure_v1_canonical_promotion_v1.md`. Summary:
    - `input_interval`: the upstream `market_rotation_snapshot_v1` header
      table persists `candle_interval_code` (default `'1h'`), and its sole
      writer (`src/research/run_market_rotation_history_v1.py`) hardcodes
      `CANDLE_INTERVAL = "1h"` (never any other value) -- this is a
      deterministic producer-owned fact, not a guess from the lookback
      windows, so `INPUT_INTERVAL = "1h"` here.
    - `lookback_horizon = "24h+168h"` and `effective_horizon = REGIME` are
      now an explicit, reviewed owner declaration (#676), not an inference
      from `input_interval` (#243 3.3's prohibition is about inference, not
      about an explicit reviewed declaration).
    - `observed_lifecycle` remains `UNMEASURED`: no persisted empirical
      lifecycle analysis exists for this lane.
    - `freshness` remains producer-undeclared: the only existing staleness
      rule (`classify_freshness()` / `DEFAULT_STALE_AFTER = 2h30m`) lives in
      `src/reporting/market_rotation_pressure_dashboard_v1.py`, a
      consumer/dashboard module, and the #676 owner decision does not adopt
      it as producer-owned truth. An hourly writer cadence is a runtime
      cadence fact, not a reviewed freshness rule (per the #676 task
      contract: "Runtime cadence alone is NOT automatically the same as
      freshness semantics"). This module reuses
      `evidence_contract_v1.compute_freshness` unchanged, so freshness stays
      `UNKNOWN`/`INSUFFICIENT_DATA` until a producer-owned rule is reviewed.
    - `model_id`/`model_version`: no `model_id` column is persisted. The
      #676 owner decision explicitly authorizes declaring
      `model_id = "market_rotation_pressure_v1"` as this producer's own
      identity constant (`RUNNER_NAME` in the producer module) -- this is
      not fabricated from row data; it is only ever attached when the row's
      persisted `model_version` is present and in the reviewed set
      `{"1.0"}` (the producer's own `MODEL_VERSION` constant). A missing/
      blank/unsupported `model_version` fails the whole identity closed
      (`model_id` stays `None` too) rather than asserting an identity the
      row's own version does not support.
    - Only the per-asset `market_rotation_pressure_observation_v1` scope is
      mapped in this slice, per the #676 task contract ("only add [aggregate
      evidence] if it fits the same clean contract seam without broadening
      scope. Otherwise explicitly keep this bounded to the per-asset
      evidence needed by #617"). Market-level aggregate
      (`market_rotation_pressure_snapshot_v1`) evidence is an explicit,
      documented later bounded slice, not implemented here.
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
    is_blank,
    resolve_status,
    validate_input_interval,
)

FAMILY_ROTATION = "ROTATION"
COMPONENT_PER_ASSET_PRESSURE = "PER_ASSET_PRESSURE"

MODEL_ID = "market_rotation_pressure_v1"

# Reviewed model_version values this contract has been checked against. An
# unreviewed/absent model_version fails closed rather than being trusted.
SUPPORTED_MODEL_VERSIONS = frozenset({"1.0"})

INPUT_INTERVAL = "1h"
LOOKBACK_HORIZON = "24h+168h"

_MARKET = "asset"


def _resolve_model_identity(
    model_version: str | None,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Map the persisted `model_version` to `model_id`/`model_version`
    strictly. `model_id` is only ever populated when `model_version` is
    present and in the reviewed set -- never fabricated for a row whose
    version this contract has not reviewed."""
    if is_blank(model_version):
        return None, None, (ReasonCode.MISSING_PROVENANCE,)
    if model_version not in SUPPORTED_MODEL_VERSIONS:
        return None, None, (ReasonCode.UNSUPPORTED_MODEL_VERSION,)
    return MODEL_ID, model_version, ()


def build_rotation_pressure_evidence(
    row: Mapping[str, Any],
    *,
    evaluated_at: datetime,
) -> SignalHorizonV1Evidence:
    """Map one `market_rotation_pressure_observation_v1` row onto
    `SignalHorizonV1Evidence`.

    `row` must be the exact historical (or current) observation row for the
    asof being evaluated; this function performs no lookup of its own, so a
    replay caller can never receive a "latest" fallback for a historical
    asof.
    """
    raw_asof_ts = row.get("as_of_ts_utc")
    model_version = row.get("model_version")

    normalized_asof_ts, freshness, freshness_reason_codes = compute_freshness(
        asof_ts=raw_asof_ts,
        evaluated_at=evaluated_at,
    )

    model_id, resolved_model_version, identity_reason_codes = _resolve_model_identity(
        model_version
    )

    extra_reason_codes = freshness_reason_codes
    extra_reason_codes += validate_input_interval(INPUT_INTERVAL)
    extra_reason_codes += identity_reason_codes
    # effective_horizon is an explicit #676 owner declaration (REGIME), not
    # an inference, so -- unlike the still-unresolved PRICE_STRUCTURE/
    # RELATIVE_STRENGTH families in #669/#672 -- no UNMAPPED_HORIZON reason
    # code is added here.

    status, reason_codes = resolve_status(
        freshness=freshness,
        extra_reason_codes=extra_reason_codes,
    )

    return SignalHorizonV1Evidence(
        family=FAMILY_ROTATION,
        component=COMPONENT_PER_ASSET_PRESSURE,
        market=_MARKET,
        status=status,
        model_id=model_id,
        model_version=resolved_model_version,
        input_interval=INPUT_INTERVAL,
        lookback_horizon=LOOKBACK_HORIZON,
        effective_horizon=EffectiveHorizon.REGIME,
        observed_lifecycle=UNMEASURED_LIFECYCLE,
        asof_ts=normalized_asof_ts,
        freshness=freshness,
        provenance={
            "asset_id": row.get("asset_id"),
            "market": row.get("market"),
            "venue": row.get("venue"),
            "source_snapshot_24h_id": row.get("source_snapshot_24h_id"),
            "source_snapshot_7d_id": row.get("source_snapshot_7d_id"),
        },
        raw={
            "score_total": row.get("score_total"),
            "pressure_state": row.get("pressure_state"),
            "phase_state": row.get("phase_state"),
            "raw_return_24h_pct": row.get("raw_return_24h_pct"),
            "raw_return_7d_pct": row.get("raw_return_7d_pct"),
        },
        reason_codes=reason_codes,
    )
