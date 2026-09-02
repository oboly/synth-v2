from __future__ import annotations

from src.research import cq_v1_discovery_validation_evaluator_v1 as core


def test_partial_outcome_bucket_does_not_read_missing_non_selected_metrics() -> None:
    rows = [
        {
            "observation_id": "obs-1",
            "status": "COMPLETE",
            "scores": {"cq_v0": 0.1},
            "forward_return_pct": "1.0",
            "mfe_pct": None,
            "mae_pct": None,
        },
        {
            "observation_id": "obs-2",
            "status": "COMPLETE",
            "scores": {"cq_v0": 0.9},
            "forward_return_pct": "3.0",
            "mfe_pct": None,
            "mae_pct": None,
        },
    ]

    metrics = core.score_horizon_split_metrics(2, rows, "cq_v0")

    assert metrics["coverage"]["forward_return_pct"]["jointly_eligible_count"] == 2
    assert metrics["coverage"]["mfe_pct"]["jointly_eligible_count"] == 0
    assert metrics["coverage"]["mae_pct"]["jointly_eligible_count"] == 0
    assert metrics["buckets"]["forward_return_pct"]["top_bottom_spread"] == 2.0
    assert metrics["buckets"]["mfe_pct"]["buckets"] == []
    assert metrics["buckets"]["mae_pct"]["buckets"] == []
