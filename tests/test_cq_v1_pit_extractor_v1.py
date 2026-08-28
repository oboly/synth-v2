from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest
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
from src.research.run_cq_v1_pit_extractor_v1 import (
    RUNNER_NAME,
    _append_jsonl,
    reconcile_jsonl,
    validate_checkpoint_scope,
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


def checkpoint(*, processed: int, last_shadow_id: int, mrp: int, sector: int, joint: int) -> dict:
    return {
        "runner": RUNNER_NAME,
        "venue": None,
        "batch_size": 100,
        "processed": processed,
        "last_shadow_id": last_shadow_id,
        "mrp_available_count": mrp,
        "sector_available_count": sector,
        "joint_available_count": joint,
    }


def test_registry_forbids_scoring_and_writes() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert registry["phase"] == "2C"
    assert registry["read_only"] is True
    assert registry["forbidden"]["model_weights"] is True
    assert registry["forbidden"]["cq_v1_score"] is True
    assert registry["forbidden"]["database_writes"] is True
    assert registry["safety"]["db_writes"] == 0
    assert registry["safety"]["live_orders"] == 0


def test_mrp_asset_inherits_same_venue_and_bounds_parent_snapshot_asof() -> None:
    cursor = FakeCursor([None])
    fetch_mrp_asset(cursor, obs())
    query, params = cursor.executed[0]
    assert "JOIN market_rotation_pressure_snapshot_v1 s" in query
    assert "s.pressure_snapshot_id=o.pressure_snapshot_id" in query
    assert "s.venue=%s" in query
    assert "o.as_of_ts_utc <= %s" in query
    assert "s.as_of_ts_utc <= %s" in query
    assert params == (
        42,
        "bitvavo",
        MRP_MODEL_VERSION,
        MRP_MODEL_VERSION,
        obs().asof_ts_utc,
        obs().asof_ts_utc,
    )


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


def test_runner_jsonl_serializes_db_decimal_values_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "features.jsonl"
    _append_jsonl(
        path,
        {
            "shadow_id": 7,
            "asof_ts_utc": datetime(2026, 8, 28, 12, 7, tzinfo=UTC),
            "mrp_aggregate": {"market_score": Decimal("12.3400")},
            "sector_rotation": {"confidence": Decimal("0.875000")},
        },
    )
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["mrp_aggregate"]["market_score"] == "12.3400"
    assert row["sector_rotation"]["confidence"] == "0.875000"
    assert row["asof_ts_utc"] == "2026-08-28T12:07:00+00:00"


def test_checkpoint_scope_rejects_foreign_runner() -> None:
    data = checkpoint(processed=0, last_shadow_id=0, mrp=0, sector=0, joint=0)
    data["runner"] = "other_runner"
    with pytest.raises(SystemExit, match="checkpoint runner mismatch"):
        validate_checkpoint_scope(data, None, 100)


def test_resume_truncates_extra_or_malformed_uncheckpointed_tail(tmp_path: Path) -> None:
    path = tmp_path / "features.jsonl"
    path.write_text(
        '{"shadow_id":1,"mrp_available":true,"sector_available":false,"joint_available":false}\n'
        '{"shadow_id":2,"mrp_available":true,"sector_available":true,"joint_available":true}\n'
        '{"shadow_id":',
        encoding="utf-8",
    )
    reconcile_jsonl(path, checkpoint(processed=2, last_shadow_id=2, mrp=2, sector=1, joint=1))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_resume_fails_if_checkpointed_row_is_malformed(tmp_path: Path) -> None:
    path = tmp_path / "features.jsonl"
    path.write_text('{"shadow_id":1}\n{"shadow_id":', encoding="utf-8")
    with pytest.raises(ValueError, match="checkpointed JSONL line 2 is malformed"):
        reconcile_jsonl(path, checkpoint(processed=2, last_shadow_id=2, mrp=0, sector=0, joint=0))


def test_resume_fails_on_reordered_or_duplicate_shadow_ids(tmp_path: Path) -> None:
    path = tmp_path / "features.jsonl"
    path.write_text(
        '{"shadow_id":2,"mrp_available":false,"sector_available":false,"joint_available":false}\n'
        '{"shadow_id":2,"mrp_available":false,"sector_available":false,"joint_available":false}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="shadow_id sequence is not strictly increasing"):
        reconcile_jsonl(path, checkpoint(processed=2, last_shadow_id=2, mrp=0, sector=0, joint=0))


def test_resume_fails_when_checkpoint_availability_counters_do_not_match_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "features.jsonl"
    path.write_text(
        '{"shadow_id":1,"mrp_available":true,"sector_available":false,"joint_available":false}\n'
        '{"shadow_id":2,"mrp_available":false,"sector_available":true,"joint_available":false}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mrp_available_count differs"):
        reconcile_jsonl(path, checkpoint(processed=2, last_shadow_id=2, mrp=0, sector=1, joint=0))
