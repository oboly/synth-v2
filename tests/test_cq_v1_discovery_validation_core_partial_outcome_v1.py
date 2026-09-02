from __future__ import annotations

from src.research import cq_v1_discovery_validation_evaluator_v1 as core


def test_core_bucket_builder_tolerates_missing_non_selected_outcomes() -> None:
    rows = [
        {
            "observation_id": "obs-1",
            "status": "COMPLETE",
            "scores": {core.CQ_V0: 0.1},
            "forward_return_pct": "1.0",
            "mfe_pct": None,
            "mae_pct": None,
        },
        {
            "observation_id": "obs-2",
            "status": "COMPLETE",
            "scores": {core.CQ_V0: 0.9},
            "forward_return_pct": "3.0",
            "mfe_pct": None,
            "mae_pct": None,
        },
    ]

    metrics = core.score_horizon_split_metrics(2, rows, core.CQ_V0)

    return_buckets = metrics["buckets"]["forward_return_pct"]
    assert return_buckets["bucket_count"] == 2
    assert return_buckets["top_bottom_spread"] == 2.0
    assert all(bucket["forward_return_pct"]["n"] == 1 for bucket in return_buckets["buckets"])

    mfe_buckets = metrics["buckets"]["mfe_pct"]
    mae_buckets = metrics["buckets"]["mae_pct"]
    assert mfe_buckets["bucket_count"] == 0
    assert mae_buckets["bucket_count"] == 0
