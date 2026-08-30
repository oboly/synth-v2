from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import pytest

import src.research.cq_v1_model_candidate_v1 as model


def _features(*, market_score: object = 0, extra: bool = False) -> dict:
    payload = {
        "mrp_aggregate": {"model_version": "1.0", "market_score": market_score},
        "mrp_asset": {"model_version": "1.0", "score_total": 999999},
        "sector_rotation": {"rotation_score": -999999},
    }
    if extra:
        payload["future_outcome_that_must_be_ignored"] = 1_000_000
    return payload


def test_mrp_market_transform_boundaries_and_neutral() -> None:
    assert model.normalize_mrp_market_score(-100) == Decimal("0.000000")
    assert model.normalize_mrp_market_score(0) == Decimal("0.500000")
    assert model.normalize_mrp_market_score(100) == Decimal("1.000000")


@pytest.mark.parametrize("value", [-100.000001, 100.000001, "nan", "inf", True])
def test_mrp_market_transform_rejects_out_of_contract_values(value: object) -> None:
    with pytest.raises(ValueError):
        model.normalize_mrp_market_score(value)


def test_cq_v0_transform_is_bounded_identity() -> None:
    assert model.normalize_cq_v0(0) == Decimal("0.000000")
    assert model.normalize_cq_v0("0.4567894") == Decimal("0.456789")
    assert model.normalize_cq_v0(1) == Decimal("1.000000")
    with pytest.raises(ValueError):
        model.normalize_cq_v0(1.000001)


def test_candidate_family_is_small_and_weights_are_fixed() -> None:
    assert len(model.CANDIDATES) == 2
    assert len(model.CANDIDATES) <= 3
    assert {spec.candidate_id for spec in model.CANDIDATES} == {
        "cq_v1_mrp_balanced_v1",
        "cq_v1_mrp_anchor_v1",
    }
    assert all(spec.weight_sum == Decimal("1.000000") for spec in model.CANDIDATES)


def test_balanced_and_anchor_scores_are_deterministic_six_decimal() -> None:
    features = _features(market_score=20)
    balanced = model.score_candidate("cq_v1_mrp_balanced_v1", cq_v0="0.8", features=features)
    anchor = model.score_candidate("cq_v1_mrp_anchor_v1", cq_v0="0.8", features=features)

    assert balanced.state == model.AVAILABLE
    assert balanced.score == Decimal("0.700000")
    assert anchor.state == model.AVAILABLE
    assert anchor.score == Decimal("0.750000")
    assert str(balanced.score) == "0.700000"
    assert str(anchor.score) == "0.750000"


def test_missing_required_support_is_explicit_and_never_renormalized() -> None:
    missing_asset = _features()
    missing_asset["mrp_asset"] = None
    result = model.score_candidate("cq_v1_mrp_balanced_v1", cq_v0=0.8, features=missing_asset)
    assert result.state == model.INSUFFICIENT_DATA
    assert result.score is None
    assert result.reason == "UNAVAILABLE_MRP_ASSET"

    missing_cq = model.score_candidate("cq_v1_mrp_balanced_v1", cq_v0=None, features=_features())
    assert missing_cq.state == model.INSUFFICIENT_DATA
    assert missing_cq.score is None
    assert missing_cq.reason == "CQ_V0_UNAVAILABLE"


def test_present_invalid_payload_blocks_instead_of_imputing() -> None:
    features = _features(market_score=101)
    result = model.score_candidate("cq_v1_mrp_anchor_v1", cq_v0=0.5, features=features)
    assert result.state == model.BLOCKED
    assert result.score is None
    assert result.reason == "mrp_aggregate.market_score:OUT_OF_RANGE_MINUS100_100"


def test_wrong_source_model_version_blocks() -> None:
    features = _features()
    features["mrp_asset"]["model_version"] = "2.0"
    result = model.score_candidate("cq_v1_mrp_anchor_v1", cq_v0=0.5, features=features)
    assert result.state == model.BLOCKED
    assert result.reason == "MRP_ASSET_MODEL_VERSION_MISMATCH"


def test_unregistered_fields_and_unbounded_scores_cannot_affect_v1_score() -> None:
    base = model.score_candidate("cq_v1_mrp_balanced_v1", cq_v0=0.6, features=_features(market_score=-20))
    extra = _features(market_score=-20, extra=True)
    extra["mrp_asset"]["score_total"] = -999999999
    extra["sector_rotation"]["rotation_score"] = 999999999
    changed = model.score_candidate("cq_v1_mrp_balanced_v1", cq_v0=0.6, features=extra)
    assert changed == base


def test_all_available_scores_are_bounded() -> None:
    for candidate in model.CANDIDATES:
        for cq_v0 in (0, 0.25, 0.5, 0.75, 1):
            for mrp in (-100, -50, 0, 50, 100):
                result = model.score_candidate(candidate.candidate_id, cq_v0=cq_v0, features=_features(market_score=mrp))
                assert result.state == model.AVAILABLE
                assert Decimal("0") <= result.score <= Decimal("1")


def test_registry_pins_accepted_coverage_hash_and_freeze_state() -> None:
    registry = Path("config/research/cq_v1_model_candidate_v1.yaml").read_text(encoding="utf-8")
    assert model.COVERAGE_ARTIFACT_SHA256 in registry
    assert "transforms_frozen: true" in registry
    assert "model_family_frozen: true" in registry
    assert "holdout_outcomes_inspected: false" in registry
    assert "candidate_count: 2" in registry


def test_scorer_has_no_db_or_forward_outcome_dependency() -> None:
    source = inspect.getsource(model).lower()
    assert "src.common.db" not in source
    assert "get_connection" not in source
    assert "forward_outcomes" not in source
    assert "entry_quality_forward_validation" not in source
