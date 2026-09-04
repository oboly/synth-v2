from __future__ import annotations

from src.research import cq_v1_discovery_validation_evaluator_v1 as core
from src.research import run_cq_v1_final_holdout_evaluator_v1 as runner


def test_cli_is_holdout_only_and_has_no_split_control() -> None:
    args = runner.parse_args(["--population", "p", "--outcomes", "o", "--output-dir", "x"])
    assert vars(args) == {"population": "p", "outcomes": "o", "output_dir": "x"}
    assert runner.HOLDOUT_SPLITS == ("holdout",)


def test_safety_markers_are_frozen_for_final_holdout() -> None:
    assert runner.SAFETY_MARKERS["research_only"] == 1
    assert runner.SAFETY_MARKERS["market_only"] == 1
    assert runner.SAFETY_MARKERS["db_writes"] == 0
    assert runner.SAFETY_MARKERS["model_retuning"] == 0
    assert runner.SAFETY_MARKERS["production_ranking_changes"] == 0
    assert runner.SAFETY_MARKERS["runtime_activation"] == 0
    assert runner.SAFETY_MARKERS["holdout_analytics_read"] == 1


def test_runner_reuses_exact_frozen_candidate_and_metric_core() -> None:
    assert runner.core is core
    assert core.HORIZONS == ("1h", "4h", "24h")
    assert core.OUTCOME_METRICS == ("forward_return_pct", "mfe_pct", "mae_pct")
    assert str(core.CQ_V1_BALANCED_CQ_V0_WEIGHT) == "0.50"
    assert str(core.CQ_V1_BALANCED_MRP_WEIGHT) == "0.50"
    assert str(core.CQ_V1_ANCHOR_CQ_V0_WEIGHT) == "0.75"
    assert str(core.CQ_V1_ANCHOR_MRP_WEIGHT) == "0.25"


def test_output_rows_always_mark_holdout_analytics_open() -> None:
    row = runner._with_safety({"split": "holdout", "n": 1})
    assert row["split"] == "holdout"
    assert row["holdout_analytics_read"] == 1
    assert row["model_retuning"] == 0
    assert row["production_ranking_changes"] == 0
