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
    - `freshness` is now producer-owned (#547 Phase C owner decision,
      superseding the `BLOCKED_NEEDS_MEASUREMENT` state left by #547 Phases
      A/B). `ROTATION_STALE_AFTER = 90 minutes` below. The dashboard's
      `classify_freshness()` / `DEFAULT_STALE_AFTER = 2h30m`
      (`src/reporting/market_rotation_pressure_dashboard_v1.py`) remains a
      separate consumer/reporting-owned rule and is explicitly NOT the
      basis for this value; `PUBLISHER_IS_FRESHNESS_AUTHORITY=0` --
      `src/reporting/market_rotation_pressure_dashboard_v1.py` and the
      Odroid publisher leg measured in #705 are downstream reporting
      observability only (`PUBLISHER_IS_REPORTING_ONLY=1`), never an input
      to this producer-owned boundary. See `ROTATION_STALE_AFTER` for the
      exact composition and
      `docs/architecture/rotation_pressure_v1_canonical_promotion_v1.md` §4.2
      for full record.
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

from datetime import datetime, timedelta
from typing import Any, Mapping

from src.features.evidence_contract_v1 import (
    EffectiveHorizon,
    FreshnessState,
    ReasonCode,
    SignalHorizonV1Evidence,
    UNMEASURED_LIFECYCLE,
    is_blank,
    normalize_to_utc,
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

# #547 Phase C owner decision: producer-owned Rotation freshness boundary.
# ROTATION_FRESHNESS_REFERENCE = producer persisted row asof_ts (this
# module's own `market_rotation_pressure_observation_v1.as_of_ts_utc`
# input) -> `rotation_evidence_contract_v1` persisted-evidence freshness
# boundary. The Odroid publisher/reporting leg measured in #705 is
# downstream reporting observability only (PUBLISHER_IS_FRESHNESS_AUTHORITY
# = 0, PUBLISHER_IS_REPORTING_ONLY = 1) and is never consulted here.
#
# 90 minutes is composed of three explicitly distinct pieces -- do not
# describe the whole 90m figure as "measured":
#   60m  canonical producer cadence (reviewed owner decision, "Cadence
#        decision" in docs/ops/market_rotation_pressure_runtime_owners_v1.md;
#        writer_oncalendar_utc = *:20:00 UTC)
#   ~23m38s (1418.2s) observed production asof->persist MAXIMUM, #705
#        Phase B measurement (n=417, continuous, 2026-08-08..2026-09-01;
#        docs/research/market_rotation_pressure_freshness_sla_measurement_v1.md
#        §4, steady-state max=1418.0s / raw max asof_to_persist_lag).
#   ~6m22s remaining operational margin to reach 90m -- an explicit OWNER
#        POLICY choice (#547 Phase C), NOT measured evidence. It exists
#        purely to round the 60m + ~23m38s sum up to a clean 90-minute
#        boundary with a small additional buffer; no distribution or
#        incident record backs this component.
# 60m + 1418.2s (~23m38s) + ~6m22s = 5400s = 90m exactly.
ROTATION_STALE_AFTER = timedelta(minutes=90)

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


def _compute_rotation_freshness(
    *,
    asof_ts: datetime | None,
    evaluated_at: datetime,
) -> tuple[datetime | None, str, tuple[str, ...]]:
    """Producer-owned Rotation freshness (#547 Phase C), deterministic from
    `asof_ts` + the caller-supplied `evaluated_at` only.

    No implicit wall-clock `now()` is ever read here -- `evaluated_at` is a
    required keyword-only argument with no default, so a replay caller
    always controls the evaluation instant and this function can never
    silently observe current time. There is no threshold/override
    parameter, so a caller cannot supply a different freshness boundary for
    Rotation than `ROTATION_STALE_AFTER`.

    Both timestamps are normalized to aware UTC via
    `evidence_contract_v1.normalize_to_utc` before comparison, so a
    naive-UTC-persisted `as_of_ts_utc` (this producer's `DATETIME(6)`
    column carries no explicit tzinfo) compares correctly against an aware
    `evaluated_at` deterministically, never by assuming local time.

    - missing `asof_ts`                -> INSUFFICIENT_DATA (fail closed)
    - `asof_ts` after `evaluated_at`    -> INSUFFICIENT_DATA (fail closed;
      a producer timestamp from the future is a data-integrity
      contradiction, not a staleness judgement)
    - age <= ROTATION_STALE_AFTER (90m) -> FRESH
    - age >  ROTATION_STALE_AFTER (90m) -> STALE (fail closed)
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

    age = normalized_evaluated_at - normalized_asof_ts
    if age <= ROTATION_STALE_AFTER:
        return normalized_asof_ts, FreshnessState.FRESH, ()
    return normalized_asof_ts, FreshnessState.STALE, (ReasonCode.STALE_EVIDENCE,)


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

    normalized_asof_ts, freshness, freshness_reason_codes = _compute_rotation_freshness(
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
