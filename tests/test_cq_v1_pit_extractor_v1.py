from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.research.cq_v1_pit_extractor_v1 import (
    MRP_MODEL_VERSION,
    SECTOR_MODEL_VERSION,
    SECTOR_WINDOW_CODE,
    FeatureExtraction,
    ShadowObservation,
    coverage_summary,
    fetch_mrp_asset,
    fetch_primary_sector_code,
    fetch_sector_rotation,
)

REGISTRY = Path("config/research/cq_v1_pit_extractor_v1.yaml")


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def execute(self, query, params):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def obs() -> ShadowObservation:
    return ShadowObservation(
        shadow_id=7,
        asset_id=42,
        venue="bitvavo",
        asof_ts_utc=datetime(2026, 8, 28, 12, 7, tzinfo=UTC),
        evidence_key="e" * 64,
        cq_model_version="cq_shadow_v1",
    )


def extraction(*, mrp=True, sector=True) -> FeatureExtraction:
    return FeatureExtraction(
        shadow_id=7,
        asset_id=42,
        venue="bitvavo",
        asof_ts_utc=obs().asof_ts_utc,
        evidence_key="e" * 64,
        cq_model_version="cq_shadow_v1",
        mrp_aggregate={} if mrp else None,
        mrp_asset={} if mrp else None,
        primary_sector_code="L1" if sector else None,
        sector_rotation={} if sector else None,
        mrp_aggregate_status="AVAILABLE" if mrp else "UNAVAILABLE_MRP_AGGREGATE",
        mrp_asset_status="AVAILABLE" if mrp else "UNAVAILABLE_MRP_ASSET",
        sector_membership_status="AVAILABLE" if sector else "UNAVAILABLE_PRIMARY_SECTOR",
        sector_rotation_status="AVAILABLE" if sector else "UNAVAILABLE_SECTOR_ROTATION",
    )


def test_registry_forbids_scoring_and_writes() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert registry["phase"] == "2C"
    assert registry["read_only"] is True
    assert registry["forbidden"]["model_weights"] is True
    assert registry["forbidden"]["cq_v1_score"] is True
    assert registry["forbidden"]["database_writes"] is True
    assert registry["safety"]["db_writes"] == 0
    assert registry["safety"]["live_orders"] == 0


def test_mrp_asset_inherits_same_venue_through_parent_snapshot() -> None:
    cursor = FakeCursor([None])
    fetch_mrp_asset(cursor, obs())
    query, params = cursor.executed[0]
    assert "JOIN market_rotation_pressure_snapshot_v1 s" in query
    assert "s.pressure_snapshot_id=o.pressure_snapshot_id" in query
    assert "s.venue=%s" in query
    assert "o.as_of_ts_utc <= %s" in query
    assert params[1] == "bitvavo"
    assert params[2] == MRP_MODEL_VERSION
    assert params[3] == MRP_MODEL_VERSION


def test_primary_sector_is_point_in_time_primary_with_frozen_tie_break() -> None:
    cursor = FakeCursor([{"sector_code": "L1"}])
    assert fetch_primary_sector_code(cursor, obs()) == "L1"
    query, params = cursor.executed[0]
    assert "membership_type='PRIMARY'" in query
    assert "valid_from_ts_utc <= %s" in query
    assert "valid_to_ts_utc IS NULL OR %s < valid_to_ts_utc" in query
    assert "ORDER BY membership_weight DESC, sector_code ASC" in query
    assert params == (42, obs().asof_ts_utc, obs().asof_ts_utc)


def test_sector_lookup_freezes_venue_window_version_and_lte_asof() -> None:
    cursor = FakeCursor([None])
    fetch_sector_rotation(cursor, obs(), "L1")
    query, params = cursor.executed[0]
    assert "venue=%s" in query
    assert "window_code=%s" in query
    assert "model_version=%s" in query
    assert "asof_ts_utc <= %s" in query
    assert params == ("L1", "bitvavo", SECTOR_WINDOW_CODE, SECTOR_MODEL_VERSION, obs().asof_ts_utc)


def test_coverage_summary_reports_same_population_denominator() -> None:
    rows = [extraction(mrp=True, sector=True), extraction(mrp=True, sector=False), extraction(mrp=False, sector=True)]
    summary = coverage_summary(rows)
    assert summary == {
        "sample_count": 3,
        "mrp_available_count": 2,
        "sector_available_count": 2,
        "joint_available_count": 1,
        "mrp_coverage": 0.666667,
        "sector_coverage": 0.666667,
        "joint_coverage": 0.333333,
    }
