from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research.cq_v1_paired_forward_comparison_v1 import HORIZONS, pair_rows, summarize
import src.research.run_cq_v1_paired_forward_comparison_v1 as runner


def score(shadow_id: int, *, cq_v0: str | None = "0.800000", available: bool = True) -> dict:
    candidate = lambda value: {
        "version": "1.0.0",
        "state": "AVAILABLE" if available else "INSUFFICIENT_DATA",
        "score": value if available else None,
        "reason": None if available else "CQ_V0_UNAVAILABLE",
    }
    return {
        "shadow_id": shadow_id,
        "asset_id": 31 + shadow_id,
        "venue": "bitvavo",
        "asof_ts_utc": "2026-08-26T20:15:47Z",
        "evidence_key": f"e{shadow_id}",
        "cq_model_version": "cq_shadow_v1",
        "cq_v0": cq_v0,
        "model_family_version": "1.0.0",
        "coverage_artifact_sha256": "f" * 64,
        "candidates": {
            "cq_v1_mrp_balanced_v1": candidate("0.700000"),
            "cq_v1_mrp_anchor_v1": candidate("0.750000"),
        },
    }


def outcome(shadow_id: int, horizon: str, *, status: str = "COMPLETE", cq_v0: str | None = "0.800000") -> dict:
    return {
        "shadow_id": shadow_id,
        "asset_id": 31 + shadow_id,
        "venue": "bitvavo",
        "observation_asof_ts_utc": "2026-08-26T20:15:47Z",
        "evidence_key": f"e{shadow_id}",
        "cq_model_version": "cq_shadow_v1",
        "horizon": horizon,
        "status": status,
        "ppp_pct": "20.0",
        "trade_quality_score": "0.6",
        "selection_score": "10.0",
        "cq_v0": cq_v0,
        "forward_return_pct": "2.0" if status == "COMPLETE" else None,
        "mfe_pct": "4.0" if status == "COMPLETE" else None,
        "mae_pct": "-1.0" if status == "COMPLETE" else None,
    }


def outcomes_for(shadow_id: int, *, status_by_horizon: dict[str, str] | None = None) -> list[dict]:
    status_by_horizon = status_by_horizon or {}
    return [outcome(shadow_id, horizon, status=status_by_horizon.get(horizon, "COMPLETE")) for horizon in HORIZONS]


def test_exact_identity_join_and_metric_construction() -> None:
    rows = pair_rows([score(1)], outcomes_for(1))
    assert len(rows) == 3
    metrics = rows[0]["metric_values"]
    assert metrics["ppp_only"] == 20.0
    assert metrics["cq_v1_mrp_balanced_v1"] == 0.7
    assert metrics["ppp_x_cq_v0"] == 16.0
    assert metrics["ppp_x_cq_v1_mrp_anchor_v1"] == 15.0


def test_identity_mismatch_fails() -> None:
    rows = outcomes_for(1)
    rows[0]["evidence_key"] = "different"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        pair_rows([score(1)], rows)


def test_cq_v0_mismatch_fails() -> None:
    rows = outcomes_for(1)
    rows[0]["cq_v0"] = "0.700000"
    with pytest.raises(ValueError, match="CQ_V0_MISMATCH"):
        pair_rows([score(1)], rows)


def test_duplicate_score_shadow_id_fails() -> None:
    with pytest.raises(ValueError, match="duplicate score shadow_id"):
        pair_rows([score(1), score(1)], outcomes_for(1))


def test_duplicate_shadow_horizon_fails() -> None:
    rows = outcomes_for(1) + [outcome(1, "1h")]
    with pytest.raises(ValueError, match="duplicate outcome identity"):
        pair_rows([score(1)], rows)


def test_missing_required_outcome_horizon_fails() -> None:
    rows = outcomes_for(1)
    rows = [row for row in rows if row["horizon"] != "24h"]
    with pytest.raises(ValueError, match="MISSING_OUTCOME_HORIZON:24h"):
        pair_rows([score(1)], rows)


def test_missing_candidate_stays_unavailable_not_imputed() -> None:
    rows = pair_rows([score(1, available=False)], outcomes_for(1))
    assert rows[0]["metric_values"]["cq_v1_mrp_balanced_v1"] is None
    assert rows[0]["metric_values"]["ppp_x_cq_v1_mrp_balanced_v1"] is None
    summary = summarize(rows)
    coverage = summary["horizons"]["1h"]["coverage"]["cq_v1_mrp_balanced_v1"]
    assert coverage["available_count"] == 0
    assert coverage["reason_counts"] == {"CQ_V0_UNAVAILABLE": 1}


def test_pairwise_uses_identical_intersection() -> None:
    scores = [score(1), score(2, available=False), score(3)]
    outcomes = outcomes_for(1) + outcomes_for(2) + outcomes_for(3)
    rows = pair_rows(scores, outcomes)
    summary = summarize(rows)
    pair = summary["horizons"]["1h"]["pairwise"]["cq_v1_mrp_balanced_v1__vs__cq_v0"]["forward_return_pct"]
    assert pair["n"] == 2
    assert pair["left"]["n"] == 2
    assert pair["right"]["n"] == 2


def test_incomplete_labels_are_excluded_from_metrics() -> None:
    rows = pair_rows(
        [score(1), score(2)],
        outcomes_for(1) + outcomes_for(2, status_by_horizon={"1h": "INSUFFICIENT_HORIZON_COVERAGE"}),
    )
    summary = summarize(rows)
    metric = summary["horizons"]["1h"]["metrics"]["cq_v0"]["forward_return_pct"]
    assert metric["n"] == 1
    assert summary["horizons"]["1h"]["label_status_counts"] == {"COMPLETE": 1, "INSUFFICIENT_HORIZON_COVERAGE": 1}


def test_runner_pins_input_hashes_and_cross_sectional_recommendation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scores = tmp_path / "scores.jsonl"
    outcomes = tmp_path / "outcomes.jsonl"
    scores.write_text(json.dumps(score(1)) + "\n", encoding="utf-8")
    outcomes.write_text("".join(json.dumps(row) + "\n" for row in outcomes_for(1)), encoding="utf-8")
    out = tmp_path / "out"
    args = runner.parse_args(["--scores-jsonl", str(scores), "--outcomes-jsonl", str(outcomes), "--output-dir", str(out)])
    assert runner.run(args) == 0
    stdout = capsys.readouterr().out
    assert "decision_gate=none" in stdout
    assert "execution_planner=none" in stdout
    assert "executor=none" in stdout
    summary = json.loads((out / runner.OUTPUT_SUMMARY).read_text(encoding="utf-8"))
    assert len(summary["score_input_sha256"]) == 64
    assert len(summary["outcome_input_sha256"]) == 64
    assert summary["bounded_cross_sectional_only"] is True
    assert summary["final_phase2_recommendation"] == "RESEARCH_FURTHER"
    assert summary["frozen_model_changed"] == 0
    assert summary["production_ranking_changed"] == 0
