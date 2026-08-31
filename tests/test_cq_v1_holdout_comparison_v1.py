from __future__ import annotations

from copy import deepcopy

import pytest

from src.research.cq_v1_holdout_comparison_v1 import (
    REQUIRED_CANDIDATES,
    correlation,
    evaluate,
    join_artifacts,
    promotion_verdict,
)

ASOF = "2026-08-26T20:15:47Z"


def _score_row(shadow_id: int, candidate_a: float, candidate_b: float) -> dict:
    return {
        "shadow_id": shadow_id,
        "asset_id": shadow_id,
        "venue": "bitvavo",
        "asof_ts_utc": ASOF,
        "evidence_key": f"e-{shadow_id}",
        "cq_model_version": "cq-v0",
        "cq_v0": 0.20 + shadow_id / 1000,
        "candidates": {
            REQUIRED_CANDIDATES[0]: {
                "version": "1.0.0",
                "state": "AVAILABLE",
                "score": candidate_a,
                "reason": "OK",
            },
            REQUIRED_CANDIDATES[1]: {
                "version": "1.0.0",
                "state": "AVAILABLE",
                "score": candidate_b,
                "reason": "OK",
            },
        },
    }


def _outcome(shadow_id: int, horizon: str, forward: float, *, ppp_kind: str | None = None) -> dict:
    ppp = 20.0 + shadow_id / 100 if ppp_kind else None
    cq0 = 0.20 + shadow_id / 1000
    return {
        "shadow_id": shadow_id,
        "asset_id": shadow_id,
        "symbol": f"A{shadow_id}",
        "venue": "bitvavo",
        "observation_asof_ts_utc": ASOF,
        "evidence_key": f"e-{shadow_id}",
        "cq_model_version": "cq-v0",
        "ppp_pct": ppp,
        "ppp_kind": ppp_kind,
        "ppp_source_ref": "fixture" if ppp_kind else None,
        "trade_quality_score": cq0,
        "selection_score": cq0 * 0.9,
        "cq_v0": cq0,
        "cq_v0_state": "GOOD",
        "entry_strength_v0": ppp * cq0 if ppp is not None else None,
        "cq_v1": None,
        "entry_strength_v1": None,
        "target_outcome_status": "UNAVAILABLE_NO_CANONICAL_TARGET_PRICE",
        "horizon": horizon,
        "horizon_end_ts_utc": ASOF,
        "base_price": 100,
        "future_close_price": 100 + forward,
        "future_candle_count": 4,
        "forward_return_pct": forward,
        "mfe_pct": forward + 1,
        "mae_pct": forward - 1,
        "status": "COMPLETE",
    }


def test_correlation_handles_ties_deterministically() -> None:
    result = correlation([1.0, 1.0, 2.0, 3.0], [0.0, 0.0, 1.0, 2.0])
    assert result.sample_count == 4
    assert result.spearman == pytest.approx(1.0)


def test_join_rejects_duplicate_score_identity() -> None:
    score = _score_row(1, 0.3, 0.4)
    with pytest.raises(ValueError, match="DUPLICATE_SCORE_IDENTITY"):
        join_artifacts([_outcome(1, "1h", 1.0)], [score, deepcopy(score)], required_asof=ASOF)


def test_join_rejects_cross_artifact_identity_mismatch() -> None:
    score = _score_row(1, 0.3, 0.4)
    outcome = _outcome(1, "1h", 1.0)
    outcome["evidence_key"] = "wrong"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        join_artifacts([outcome], [score], required_asof=ASOF)


def test_incomplete_outcome_is_excluded_not_fabricated() -> None:
    outcome = _outcome(1, "1h", 1.0)
    outcome["status"] = "INSUFFICIENT_HORIZON_COVERAGE"
    joined = join_artifacts([outcome], [_score_row(1, 0.3, 0.4)], required_asof=ASOF)
    assert joined == []


def test_evaluation_uses_identical_candidate_baseline_samples() -> None:
    scores = [_score_row(i, i / 10, i / 20) for i in range(1, 11)]
    outcomes = [
        _outcome(i, horizon, i / 10)
        for i in range(1, 11)
        for horizon in ("1h", "4h", "24h")
    ]
    scores[-1]["candidates"][REQUIRED_CANDIDATES[0]]["state"] = "INSUFFICIENT_DATA"
    scores[-1]["candidates"][REQUIRED_CANDIDATES[0]]["score"] = None
    joined = join_artifacts(outcomes, scores, required_asof=ASOF)
    result = evaluate(joined)
    balanced = result["candidate_comparisons"][REQUIRED_CANDIDATES[0]]["1h"]
    anchor = result["candidate_comparisons"][REQUIRED_CANDIDATES[1]]["1h"]
    assert balanced["eligible_sample_count"] == 9
    assert anchor["eligible_sample_count"] == 10
    for metric in ("trade_quality_score", "selection_score", "cq_v0", REQUIRED_CANDIDATES[0]):
        assert balanced["metrics"][metric]["sample_count"] == 9


def test_ppp_kinds_are_never_mixed() -> None:
    scores = [_score_row(1, 0.4, 0.4), _score_row(2, 0.5, 0.5)]
    outcomes = []
    for horizon in ("1h", "4h", "24h"):
        outcomes.append(_outcome(1, horizon, 1.0, ppp_kind="PLANNING_PPP"))
        outcomes.append(_outcome(2, horizon, 2.0, ppp_kind="ACTIONABLE_PPP"))
    result = evaluate(join_artifacts(outcomes, scores, required_asof=ASOF))
    assert sorted(result["ppp_cohorts"]) == ["ACTIONABLE_PPP", "PLANNING_PPP"]
    for kind in result["ppp_cohorts"].values():
        assert kind[REQUIRED_CANDIDATES[0]]["1h"]["eligible_sample_count"] == 1


def test_promotion_rule_returns_research_further_when_sample_is_too_small() -> None:
    scores = [_score_row(i, i / 10, i / 10) for i in range(1, 6)]
    outcomes = [
        _outcome(i, horizon, float(i))
        for i in range(1, 6)
        for horizon in ("1h", "4h", "24h")
    ]
    evaluation = evaluate(join_artifacts(outcomes, scores, required_asof=ASOF))
    verdict, _ = promotion_verdict(evaluation, minimum_candidate_sample=100, material_delta=0.02)
    assert verdict == "RESEARCH_FURTHER"
