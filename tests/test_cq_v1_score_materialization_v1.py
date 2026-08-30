from __future__ import annotations

import argparse
import inspect
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

import src.research.cq_v1_pit_extractor_v1 as pit
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
        "cq_v0": "0.800000",
        "mrp_aggregate": {"model_version": "1.0", "market_score": market_score},
        "mrp_asset": {"model_version": "1.0", "score_total": 999999} if mrp_asset else None,
        "sector_rotation": {"rotation_score": -999999},
    }


def _shadow(*, shadow_id: int = 10, cq_v0: str = "0.800000") -> dict:
    return {
        "shadow_id": shadow_id,
        "asset_id": 31,
        "venue": "bitvavo",
        "asof_ts_utc": datetime(2026, 8, 26, 20, 15, 47),
        "evidence_key": "abc123",
        "cq_model_version": "cq_shadow_v1",
        "entry_quality_score": Decimal(cq_v0),
    }


def test_pit_extraction_preserves_cq_v0(monkeypatch: pytest.MonkeyPatch) -> None:
    observation = pit.ShadowObservation(
        shadow_id=10,
        asset_id=31,
        venue="bitvavo",
        asof_ts_utc=datetime(2026, 8, 26, 20, 15, 47),
        evidence_key="abc123",
        cq_model_version="cq_shadow_v1",
        cq_v0=Decimal("0.800000"),
    )
    monkeypatch.setattr(pit, "fetch_mrp_aggregate", lambda *_: None)
    monkeypatch.setattr(pit, "fetch_mrp_asset", lambda *_: None)
    monkeypatch.setattr(pit, "fetch_primary_sector_code", lambda *_: None)
    extracted = pit.extract_features(object(), observation)
    assert extracted.cq_v0 == Decimal("0.800000")


def test_materialize_valid_identity_preserves_frozen_scores() -> None:
    row = runner.materialize_row(_feature(), _shadow())
    assert row["shadow_id"] == 10
    assert row["cq_v0"] == Decimal("0.800000")
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
        runner.materialize_row(_feature(), None)


def test_identity_mismatch_fails_closed() -> None:
    shadow = _shadow()
    shadow["evidence_key"] = "different"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH:evidence_key"):
        runner.materialize_row(_feature(), shadow)


def test_changed_cq_v0_same_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match="CQ_V0_MISMATCH"):
        runner.materialize_row(_feature(), _shadow(cq_v0="0.700000"))


def test_feature_loader_requires_frozen_cq_v0(tmp_path: Path) -> None:
    feature = _feature()
    del feature["cq_v0"]
    path = tmp_path / "features.jsonl"
    path.write_text(json.dumps(feature) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing frozen cq_v0"):
        runner.load_feature_rows(path)


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
    summary = runner.summarize([available, unavailable], "FINISHED")
    assert summary["sample_count"] == 2
    assert summary["last_shadow_id"] == 11
    assert summary["candidate_available"]["cq_v1_mrp_balanced_v1"] == {"count": 1, "rate": 0.5}
    assert summary["candidate_state_counts"]["cq_v1_mrp_anchor_v1"] == {
        "AVAILABLE": 1,
        "INSUFFICIENT_DATA": 1,
    }
    assert summary["terminal_state"] == "FINISHED"
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


class _FakeConn:
    def close(self) -> None:
        pass


def test_interrupted_run_writes_checkpoint_and_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    features_path = tmp_path / "features.jsonl"
    features = [_feature(shadow_id=10), _feature(shadow_id=11)]
    features_path.write_text("".join(json.dumps(row) + "\n" for row in features), encoding="utf-8")
    output_dir = tmp_path / "out"
    shadow_rows = {10: _shadow(shadow_id=10), 11: _shadow(shadow_id=11)}

    monkeypatch.setattr(runner, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(runner, "fetch_shadow_rows", lambda _conn, ids: {shadow_id: shadow_rows[shadow_id] for shadow_id in ids})
    original_materialize = runner.materialize_row
    calls = 0

    def interrupt_after_first(feature, shadow):
        nonlocal calls
        row = original_materialize(feature, shadow)
        calls += 1
        if calls == 1:
            runner._STOP_REQUESTED = True
        return row

    monkeypatch.setattr(runner, "materialize_row", interrupt_after_first)
    args = argparse.Namespace(features_jsonl=str(features_path), output_dir=str(output_dir), batch_size=100, resume=False)
    assert runner.run(args) == 130
    interrupted_summary = json.loads((output_dir / runner.OUTPUT_SUMMARY).read_text(encoding="utf-8"))
    interrupted_checkpoint = json.loads((output_dir / runner.OUTPUT_CHECKPOINT).read_text(encoding="utf-8"))
    assert interrupted_summary["terminal_state"] == "INTERRUPTED"
    assert interrupted_summary["sample_count"] == 1
    assert interrupted_checkpoint["processed"] == 1
    assert interrupted_checkpoint["last_shadow_id"] == 10

    monkeypatch.setattr(runner, "materialize_row", original_materialize)
    resume_args = argparse.Namespace(features_jsonl=str(features_path), output_dir=str(output_dir), batch_size=100, resume=True)
    assert runner.run(resume_args) == 0
    final_summary = json.loads((output_dir / runner.OUTPUT_SUMMARY).read_text(encoding="utf-8"))
    assert final_summary["terminal_state"] == "FINISHED"
    assert final_summary["sample_count"] == 2
    assert len((output_dir / runner.OUTPUT_ROWS).read_text(encoding="utf-8").splitlines()) == 2


def test_runner_has_no_forward_outcome_dependency_or_candle_query() -> None:
    source = inspect.getsource(runner).lower()
    assert "entry_quality_forward_validation" not in source
    assert "forward_outcomes_v1" not in source
    assert "obs_market_candle" not in source
    assert "future candle" not in source
