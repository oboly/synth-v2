from __future__ import annotations

import inspect
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

import src.research.run_cq_v1_score_materialization_v1 as runner
from src.research.cq_v1_model_candidate_v1 import COVERAGE_ARTIFACT_SHA256, MODEL_FAMILY_VERSION


def _feature(*, shadow_id: int = 10, market_score: object = 20, mrp_asset: bool = True) -> dict:
    return {
        "shadow_id": shadow_id,
        "asset_id": 31,
        "venue": "bitvavo",
        "asof_ts_utc": "2026-08-26T20:15:47+00:00",
        "evidence_key": "abc123",
        "cq_model_version": "cq_shadow_v1",
        "mrp_aggregate": {"model_version": "1.0", "market_score": market_score},
        "mrp_asset": {"model_version": "1.0", "score_total": 999999} if mrp_asset else None,
        "sector_rotation": {"rotation_score": -999999},
    }


def _shadow(*, shadow_id: int = 10) -> dict:
    return {
        "shadow_id": shadow_id,
        "asset_id": 31,
        "venue": "bitvavo",
        "asof_ts_utc": datetime(2026, 8, 26, 20, 15, 47),
        "evidence_key": "abc123",
        "cq_model_version": "cq_shadow_v1",
        "entry_quality_score": Decimal("0.800000"),
    }


def test_materialize_valid_identity_preserves_frozen_scores() -> None:
    row = runner.materialize_row(_feature(), _shadow())
    assert row["shadow_id"] == 10
    assert row["model_family_version"] == MODEL_FAMILY_VERSION
    assert row["coverage_artifact_sha256"] == COVERAGE_ARTIFACT_SHA256
    assert row["candidates"]["cq_v1_mrp_balanced_v1"] == {
        "version": "1.0.0",
        "state": "AVAILABLE",
        "score": Decimal("0.700000"),
        "reason": None,
    }
    assert row["candidates"]["cq_v1_mrp_anchor_v1"]["score"] == Decimal("0.750000")


def test_missing_shadow_row_fails_closed() -> None:
    with pytest.raises(ValueError, match="SHADOW_ROW_MISSING"):
        runner.materialize_row(_feature(), None)  # type: ignore[arg-type]


def test_identity_mismatch_fails_closed() -> None:
    shadow = _shadow()
    shadow["evidence_key"] = "different"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH:evidence_key"):
        runner.materialize_row(_feature(), shadow)


def test_missing_mrp_support_is_not_imputed() -> None:
    row = runner.materialize_row(_feature(mrp_asset=False), _shadow())
    for payload in row["candidates"].values():
        assert payload["state"] == "INSUFFICIENT_DATA"
        assert payload["score"] is None
        assert payload["reason"] == "UNAVAILABLE_MRP_ASSET"


def test_unregistered_numeric_fields_cannot_change_scores() -> None:
    first = _feature()
    second = _feature()
    second["mrp_asset"]["score_total"] = -1_000_000_000
    second["sector_rotation"]["rotation_score"] = 1_000_000_000
    second["future_magic"] = 12345
    assert runner.materialize_row(first, _shadow())["candidates"] == runner.materialize_row(second, _shadow())["candidates"]


def test_summary_reports_actual_support_not_hard_coded() -> None:
    available = runner.materialize_row(_feature(shadow_id=10), _shadow(shadow_id=10))
    unavailable = runner.materialize_row(_feature(shadow_id=11, mrp_asset=False), _shadow(shadow_id=11))
    summary = runner.summarize([available, unavailable])
    assert summary["sample_count"] == 2
    assert summary["last_shadow_id"] == 11
    assert summary["candidate_available"]["cq_v1_mrp_balanced_v1"] == {"count": 1, "rate": 0.5}
    assert summary["candidate_state_counts"]["cq_v1_mrp_anchor_v1"] == {
        "AVAILABLE": 1,
        "INSUFFICIENT_DATA": 1,
    }
    assert summary["forward_outcomes_read"] == 0
    assert summary["production_ranking_changed"] == 0


def test_feature_loader_requires_strictly_increasing_identity(tmp_path: Path) -> None:
    path = tmp_path / "features.jsonl"
    path.write_text(json.dumps(_feature(shadow_id=2)) + "\n" + json.dumps(_feature(shadow_id=1)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="strictly increasing"):
        runner.load_feature_rows(path)


def test_output_score_is_json_safe_six_decimal() -> None:
    row = runner.materialize_row(_feature(), _shadow())
    encoded = json.dumps(row, default=runner._json_default, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["candidates"]["cq_v1_mrp_balanced_v1"]["score"] == "0.700000"
    assert decoded["cq_v0"] == "0.800000"


def test_runner_has_no_forward_outcome_dependency_or_candle_query() -> None:
    source = inspect.getsource(runner).lower()
    assert "entry_quality_forward_validation" not in source
    assert "forward_outcomes_v1" not in source
    assert "obs_market_candle" not in source
    assert "future candle" not in source
