from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

MRP_MODEL_VERSION = "1.0"
SECTOR_MODEL_VERSION = "sector-rotation-v1.0.0"
SECTOR_WINDOW_CODE = "4h"


@dataclass(frozen=True)
class ShadowObservation:
    shadow_id: int
    asset_id: int
    venue: str
    asof_ts_utc: datetime
    evidence_key: str
    cq_model_version: str
    cq_v0: Decimal | None = None


@dataclass(frozen=True)
class FeatureExtraction:
    shadow_id: int
    asset_id: int
    venue: str
    asof_ts_utc: datetime
    evidence_key: str
    cq_model_version: str
    mrp_aggregate: Mapping[str, Any] | None
    mrp_asset: Mapping[str, Any] | None
    primary_sector_code: str | None
    sector_rotation: Mapping[str, Any] | None
    mrp_aggregate_status: str
    mrp_asset_status: str
    sector_membership_status: str
    sector_rotation_status: str
    cq_v0: Decimal | None = None

    @property
    def mrp_available(self) -> bool:
        return self.mrp_aggregate is not None and self.mrp_asset is not None

    @property
    def sector_available(self) -> bool:
        return self.primary_sector_code is not None and self.sector_rotation is not None

    @property
    def joint_available(self) -> bool:
        return self.mrp_available and self.sector_available


def _fetchone(cursor: Any, query: str, params: tuple[Any, ...]) -> Mapping[str, Any] | None:
    cursor.execute(query, params)
    row = cursor.fetchone()
    return row if row else None


def fetch_mrp_aggregate(cursor: Any, observation: ShadowObservation) -> Mapping[str, Any] | None:
    return _fetchone(
        cursor,
        """
        SELECT pressure_snapshot_id, as_of_ts_utc, venue, model_version,
               market_score, positive_breadth_ratio, negative_breadth_ratio,
               acceleration_state, concentration_state, confirmation_state,
               market_direction, evidence_light_count, eligible_asset_count
        FROM market_rotation_pressure_snapshot_v1
        WHERE venue=%s
          AND model_version=%s
          AND as_of_ts_utc <= %s
        ORDER BY as_of_ts_utc DESC, pressure_snapshot_id DESC
        LIMIT 1
        """,
        (observation.venue, MRP_MODEL_VERSION, observation.asof_ts_utc),
    )


def fetch_mrp_asset(cursor: Any, observation: ShadowObservation) -> Mapping[str, Any] | None:
    return _fetchone(
        cursor,
        """
        SELECT o.pressure_obs_id, o.pressure_snapshot_id, o.asset_id,
               o.as_of_ts_utc, o.model_version, o.score_total,
               o.pressure_state, o.phase_state, o.raw_market_relative_pct,
               s.venue
        FROM market_rotation_pressure_observation_v1 o
        JOIN market_rotation_pressure_snapshot_v1 s
          ON s.pressure_snapshot_id=o.pressure_snapshot_id
        WHERE o.asset_id=%s
          AND s.venue=%s
          AND o.model_version=%s
          AND s.model_version=%s
          AND o.as_of_ts_utc <= %s
          AND s.as_of_ts_utc <= %s
        ORDER BY o.as_of_ts_utc DESC, o.pressure_obs_id DESC
        LIMIT 1
        """,
        (
            observation.asset_id,
            observation.venue,
            MRP_MODEL_VERSION,
            MRP_MODEL_VERSION,
            observation.asof_ts_utc,
            observation.asof_ts_utc,
        ),
    )


def fetch_primary_sector_code(cursor: Any, observation: ShadowObservation) -> str | None:
    row = _fetchone(
        cursor,
        """
        SELECT sector_code
        FROM asset_cluster_membership
        WHERE asset_id=%s
          AND membership_type='PRIMARY'
          AND valid_from_ts_utc <= %s
          AND (valid_to_ts_utc IS NULL OR %s < valid_to_ts_utc)
        ORDER BY membership_weight DESC, sector_code ASC
        LIMIT 1
        """,
        (observation.asset_id, observation.asof_ts_utc, observation.asof_ts_utc),
    )
    return None if row is None else str(row["sector_code"])


def fetch_sector_rotation(
    cursor: Any,
    observation: ShadowObservation,
    sector_code: str,
) -> Mapping[str, Any] | None:
    return _fetchone(
        cursor,
        """
        SELECT sector_rotation_snapshot_id, sector_code, venue, window_code,
               asof_ts_utc, model_version, input_hash, taxonomy_versions_json,
               rotation_score, rotation_state, confidence,
               positive_participation_pct, negative_participation_pct,
               benchmark_outperformance_pct, relative_strength_vs_btc,
               relative_strength_vs_eth, sector_volume_share,
               sector_volume_share_change, momentum_positive_pct,
               persistence_score, persistence_status, coverage_ratio,
               participation_ratio
        FROM sector_rotation_snapshot
        WHERE sector_code=%s
          AND venue=%s
          AND window_code=%s
          AND model_version=%s
          AND asof_ts_utc <= %s
        ORDER BY asof_ts_utc DESC, sector_rotation_snapshot_id DESC
        LIMIT 1
        """,
        (
            sector_code,
            observation.venue,
            SECTOR_WINDOW_CODE,
            SECTOR_MODEL_VERSION,
            observation.asof_ts_utc,
        ),
    )


def extract_features(cursor: Any, observation: ShadowObservation) -> FeatureExtraction:
    aggregate = fetch_mrp_aggregate(cursor, observation)
    asset = fetch_mrp_asset(cursor, observation)
    sector_code = fetch_primary_sector_code(cursor, observation)
    sector = None if sector_code is None else fetch_sector_rotation(cursor, observation, sector_code)

    return FeatureExtraction(
        shadow_id=observation.shadow_id,
        asset_id=observation.asset_id,
        venue=observation.venue,
        asof_ts_utc=observation.asof_ts_utc,
        evidence_key=observation.evidence_key,
        cq_model_version=observation.cq_model_version,
        mrp_aggregate=aggregate,
        mrp_asset=asset,
        primary_sector_code=sector_code,
        sector_rotation=sector,
        mrp_aggregate_status="AVAILABLE" if aggregate is not None else "UNAVAILABLE_MRP_AGGREGATE",
        mrp_asset_status="AVAILABLE" if asset is not None else "UNAVAILABLE_MRP_ASSET",
        sector_membership_status="AVAILABLE" if sector_code is not None else "UNAVAILABLE_PRIMARY_SECTOR",
        sector_rotation_status="AVAILABLE" if sector is not None else "UNAVAILABLE_SECTOR_ROTATION",
        cq_v0=observation.cq_v0,
    )


def coverage_summary(rows: list[FeatureExtraction]) -> dict[str, Any]:
    count = len(rows)
    if count == 0:
        return {
            "sample_count": 0,
            "mrp_available_count": 0,
            "sector_available_count": 0,
            "joint_available_count": 0,
            "mrp_coverage": 0.0,
            "sector_coverage": 0.0,
            "joint_coverage": 0.0,
        }

    mrp = sum(row.mrp_available for row in rows)
    sector = sum(row.sector_available for row in rows)
    joint = sum(row.joint_available for row in rows)
    return {
        "sample_count": count,
        "mrp_available_count": mrp,
        "sector_available_count": sector,
        "joint_available_count": joint,
        "mrp_coverage": round(mrp / count, 6),
        "sector_coverage": round(sector / count, 6),
        "joint_coverage": round(joint / count, 6),
    }
