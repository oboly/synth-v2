"""Canonical persistence contract for validated #593 C1 fast Rotation evidence.

Issue #733 owns persistence only. The frozen C1 calculation remains owned by
#593 and is consumed unchanged. This module does not recompute the signal,
change sign semantics, classify direction, rank markets, read account state,
or create execution authority.

The adapter intentionally validates the exact frozen C1 identity before any
row can be persisted. A semantic change therefore requires an explicit model
version / contract change rather than silently reusing C1 v1 identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

CANDIDATE_ID = "C1"
ROTATION_MODEL = "multi_horizon_rotation_relative_flow"
ROTATION_MODEL_VERSION = "1.0.0-c1"
INPUT_INTERVAL = "15m"
LOOKBACK_HORIZON = "current_15m_plus_previous_8_completed_15m_windows"
EFFECTIVE_HORIZON = "VERY_SHORT"
OBSERVED_LIFECYCLE = "UNMEASURED"
SOURCE_PROVENANCE = "obs_market_candle:15m:close_price+volume_base;owner=public_candle_freshness_writer"

# Frozen #593 final-holdout identities. These are provenance/semantic guards,
# not runtime configuration and have no refreeze/override path here.
FROZEN_REPLAY_SOURCE_SHA256 = "843475d2d44ae29d7393f369dcf876aa98a89b1c1941969a5c57db57192ce949"
FROZEN_FINAL_HOLDOUT_FINGERPRINT = "657ae08b479daa63b8454e3b8198b64a872681ae57af3d4adc1cfd7be787186c"

_REPLAY_RELATIVE_PATH = Path("src/research/multi_horizon_rotation_replay_v1.py")


class C1PersistenceContractError(ValueError):
    """Raised when a candidate row does not match the frozen C1 contract."""


@dataclass(frozen=True, slots=True)
class FastRotationC1Observation:
    venue: str
    asset_id: int
    market: str
    asof_ts_utc: Any
    candidate_id: str
    rotation_model: str
    rotation_model_version: str
    input_interval: str
    lookback_horizon: str
    effective_horizon: str
    observed_lifecycle: str
    rotation_score: Decimal | None
    relative_return_unit: Decimal | None
    signed_flow_unit: Decimal | None
    relative_acceleration_unit: Decimal | None
    cohort_size: int
    evaluated_universe_size: int
    coverage_ratio: Decimal
    freshness_state: str
    data_quality: str
    reason_code: str
    source_provenance: str
    frozen_replay_source_sha256: str
    frozen_final_holdout_fingerprint: str


def replay_source_path() -> Path:
    return Path(__file__).resolve().parents[2] / _REPLAY_RELATIVE_PATH


def replay_source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_replay_source() -> str:
    """Fail closed if the live C1 replay source drifted from frozen #593 bytes."""
    actual = replay_source_sha256(replay_source_path())
    if actual != FROZEN_REPLAY_SOURCE_SHA256:
        raise C1PersistenceContractError(
            "C1 replay source differs from frozen #593 implementation; explicit review/version change required"
        )
    return actual


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise C1PersistenceContractError("C1 numeric evidence must be finite")
    return result


def _require_exact(actual: Any, expected: str, field: str) -> None:
    if str(actual) != expected:
        raise C1PersistenceContractError(
            f"C1 {field} mismatch: expected={expected!r} actual={actual!r}"
        )


def _coverage(cohort_size: int, evaluated_universe_size: int) -> Decimal:
    if evaluated_universe_size <= 0:
        raise C1PersistenceContractError("evaluated_universe_size must be > 0")
    if cohort_size < 0 or cohort_size > evaluated_universe_size:
        raise C1PersistenceContractError(
            "C1 cohort_size must be within [0,evaluated_universe_size]"
        )
    return (Decimal(cohort_size) / Decimal(evaluated_universe_size)).quantize(Decimal("0.000001"))


def materialize_observation(
    result: Any,
    *,
    market: str,
    evaluated_universe_size: int,
) -> FastRotationC1Observation:
    """Map one frozen #593 CandidateResult to the canonical persistence row.

    No score transformation is performed. Negative scores remain negative.
    """
    if not market:
        raise C1PersistenceContractError("market identity is required")

    _require_exact(result.candidate_id, CANDIDATE_ID, "candidate_id")
    _require_exact(result.model_id, ROTATION_MODEL, "model_id")
    _require_exact(result.model_version, ROTATION_MODEL_VERSION, "model_version")
    _require_exact(result.input_interval, INPUT_INTERVAL, "input_interval")
    _require_exact(result.lookback_horizon, LOOKBACK_HORIZON, "lookback_horizon")
    _require_exact(result.effective_horizon, EFFECTIVE_HORIZON, "effective_horizon")
    _require_exact(result.observed_lifecycle, OBSERVED_LIFECYCLE, "observed_lifecycle")
    _require_exact(result.provenance, SOURCE_PROVENANCE, "provenance")

    freshness = str(result.freshness)
    if freshness not in {"FRESH", "STALE", "INSUFFICIENT_DATA", "UNKNOWN"}:
        raise C1PersistenceContractError(f"unsupported C1 freshness: {freshness!r}")

    data_quality = str(result.data_quality)
    if data_quality not in {"COMPLETE", "INSUFFICIENT_DATA"}:
        raise C1PersistenceContractError(f"unsupported C1 data_quality: {data_quality!r}")

    rotation_score = _decimal_or_none(result.rotation_score)
    relative_return_unit = _decimal_or_none(result.relative_return_unit)
    signed_flow_unit = _decimal_or_none(result.signed_flow_unit)
    relative_acceleration_unit = _decimal_or_none(result.relative_acceleration_unit)

    if data_quality == "COMPLETE":
        if any(
            value is None
            for value in (
                rotation_score,
                relative_return_unit,
                signed_flow_unit,
                relative_acceleration_unit,
            )
        ):
            raise C1PersistenceContractError("COMPLETE C1 row is missing numeric evidence")
        if freshness != "FRESH":
            raise C1PersistenceContractError("COMPLETE C1 row must preserve frozen freshness=FRESH")
    else:
        if rotation_score is not None:
            raise C1PersistenceContractError("INSUFFICIENT_DATA C1 row must not carry rotation_score")

    if rotation_score is not None and not Decimal("-100") <= rotation_score <= Decimal("100"):
        raise C1PersistenceContractError("C1 rotation_score outside frozen [-100,100] range")

    cohort_size = int(result.cohort_size)
    universe_size = int(evaluated_universe_size)
    coverage_ratio = _coverage(cohort_size, universe_size)

    return FastRotationC1Observation(
        venue=str(result.venue),
        asset_id=int(result.asset_id),
        market=market,
        asof_ts_utc=result.asof_ts,
        candidate_id=CANDIDATE_ID,
        rotation_model=ROTATION_MODEL,
        rotation_model_version=ROTATION_MODEL_VERSION,
        input_interval=INPUT_INTERVAL,
        lookback_horizon=LOOKBACK_HORIZON,
        effective_horizon=EFFECTIVE_HORIZON,
        observed_lifecycle=OBSERVED_LIFECYCLE,
        rotation_score=rotation_score,
        relative_return_unit=relative_return_unit,
        signed_flow_unit=signed_flow_unit,
        relative_acceleration_unit=relative_acceleration_unit,
        cohort_size=cohort_size,
        evaluated_universe_size=universe_size,
        coverage_ratio=coverage_ratio,
        freshness_state=freshness,
        data_quality=data_quality,
        reason_code=str(result.reason),
        source_provenance=SOURCE_PROVENANCE,
        frozen_replay_source_sha256=FROZEN_REPLAY_SOURCE_SHA256,
        frozen_final_holdout_fingerprint=FROZEN_FINAL_HOLDOUT_FINGERPRINT,
    )


def materialize_observations(
    results: Iterable[Any],
    *,
    market_by_asset: Mapping[int, str],
    evaluated_universe_size: int,
) -> tuple[FastRotationC1Observation, ...]:
    result_rows = tuple(results)
    universe_size = int(evaluated_universe_size)
    if universe_size <= 0:
        raise C1PersistenceContractError("evaluated_universe_size must be > 0")
    if len(result_rows) != universe_size:
        raise C1PersistenceContractError(
            "C1 result count must equal the immutable evaluated_universe_size denominator"
        )

    observations: list[FastRotationC1Observation] = []
    seen: set[tuple[str, str, int, Any]] = set()
    for result in result_rows:
        asset_id = int(result.asset_id)
        market = market_by_asset.get(asset_id)
        if market is None:
            raise C1PersistenceContractError(f"missing canonical market identity for asset_id={asset_id}")
        observation = materialize_observation(
            result,
            market=market,
            evaluated_universe_size=universe_size,
        )
        key = (observation.venue, observation.market, observation.asset_id, observation.asof_ts_utc)
        if key in seen:
            raise C1PersistenceContractError(f"duplicate C1 logical row in materialization batch: {key!r}")
        seen.add(key)
        observations.append(observation)
    return tuple(observations)


def _sql_values(observation: FastRotationC1Observation) -> tuple[Any, ...]:
    asof = observation.asof_ts_utc
    if getattr(asof, "tzinfo", None) is not None:
        asof = asof.astimezone(UTC).replace(tzinfo=None)
    return (
        observation.venue,
        observation.asset_id,
        observation.market,
        asof,
        observation.candidate_id,
        observation.rotation_model,
        observation.rotation_model_version,
        observation.input_interval,
        observation.lookback_horizon,
        observation.effective_horizon,
        observation.observed_lifecycle,
        None if observation.rotation_score is None else str(observation.rotation_score),
        None if observation.relative_return_unit is None else str(observation.relative_return_unit),
        None if observation.signed_flow_unit is None else str(observation.signed_flow_unit),
        None if observation.relative_acceleration_unit is None else str(observation.relative_acceleration_unit),
        observation.cohort_size,
        observation.evaluated_universe_size,
        str(observation.coverage_ratio),
        observation.freshness_state,
        observation.data_quality,
        observation.reason_code,
        observation.source_provenance,
        observation.frozen_replay_source_sha256,
        observation.frozen_final_holdout_fingerprint,
    )


def persist_observations(
    conn: Any,
    observations: Iterable[FastRotationC1Observation],
    *,
    authorization: Any,
) -> tuple[int, int]:
    """Persist C1 rows idempotently; returns (created, already_existing).

    Authorization remains externally owned. #733 deliberately does not grant
    or activate the writer capability.
    """
    from src.operations.writer_capability_authorization_v1 import require_writer_mutation_authorization

    require_writer_mutation_authorization(authorization, "fast_rotation_c1_history")
    rows = tuple(observations)
    if not rows:
        return (0, 0)

    sql = """
    INSERT INTO fast_rotation_c1_observation_v1 (
      venue,asset_id,market,asof_ts_utc,candidate_id,rotation_model,rotation_model_version,
      input_interval,lookback_horizon,effective_horizon,observed_lifecycle,rotation_score,
      relative_return_unit,signed_flow_unit,relative_acceleration_unit,cohort_size,
      evaluated_universe_size,coverage_ratio,freshness_state,data_quality,reason_code,
      source_provenance,frozen_replay_source_sha256,frozen_final_holdout_fingerprint
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE c1_observation_id=c1_observation_id
    """

    created = 0
    try:
        with conn.cursor() as cur:
            for observation in rows:
                created += 1 if int(cur.execute(sql, _sql_values(observation))) > 0 else 0
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return created, len(rows) - created
