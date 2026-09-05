from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.ma_volume_incremental_validation_v1 import (
    MAVolumeValidationInputError,
    evaluate_incremental_features,
)


def _frame() -> pd.DataFrame:
    rows = []
    for split_index, split in enumerate(("DISCOVERY", "VALIDATION", "HOLDOUT")):
        for index in range(1, 21):
            baseline = float(index)
            candidate = float((index % 5) - 2)
            outcome = baseline * 0.2 + candidate * 2.0 + split_index * 0.01
            rows.append(
                {
                    "split": split,
                    "baseline_structure": baseline,
                    "candidate_sma150_slope": candidate,
                    "candidate_duplicate_baseline": baseline,
                    "forward_return_pct": outcome,
                }
            )
    return pd.DataFrame(rows)


def test_reports_raw_and_baseline_controlled_rank_association_per_split() -> None:
    report = evaluate_incremental_features(
        _frame(),
        candidate_columns=("candidate_sma150_slope",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    assert [metric.split for metric in report.metrics] == ["DISCOVERY", "VALIDATION", "HOLDOUT"]
    assert all(metric.sample_count == 20 for metric in report.metrics)
    assert all(metric.partial_sample_count == 20 for metric in report.metrics)
    assert all(metric.partial_spearman_given_baseline is not None for metric in report.metrics)
    assert all(metric.partial_spearman_given_baseline > 0.8 for metric in report.metrics)


def test_candidate_that_duplicates_baseline_has_no_incremental_rank_information() -> None:
    report = evaluate_incremental_features(
        _frame(),
        candidate_columns=("candidate_duplicate_baseline",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    assert all(metric.partial_spearman_given_baseline is None for metric in report.metrics)


def test_split_metrics_are_isolated_from_other_split_outcomes() -> None:
    frame = _frame()
    baseline_report = evaluate_incremental_features(
        frame,
        candidate_columns=("candidate_sma150_slope",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    mutated = frame.copy()
    mutated.loc[mutated["split"] == "HOLDOUT", "forward_return_pct"] *= -1000.0
    mutated_report = evaluate_incremental_features(
        mutated,
        candidate_columns=("candidate_sma150_slope",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    before = {metric.split: metric for metric in baseline_report.metrics}
    after = {metric.split: metric for metric in mutated_report.metrics}
    assert before["DISCOVERY"] == after["DISCOVERY"]
    assert before["VALIDATION"] == after["VALIDATION"]
    assert before["HOLDOUT"] != after["HOLDOUT"]


def test_missing_candidate_values_reduce_both_samples() -> None:
    frame = _frame()
    frame.loc[0:4, "candidate_sma150_slope"] = np.nan

    report = evaluate_incremental_features(
        frame,
        candidate_columns=("candidate_sma150_slope",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    discovery = next(metric for metric in report.metrics if metric.split == "DISCOVERY")
    assert discovery.sample_count == 15
    assert discovery.partial_sample_count == 15


def test_missing_baseline_values_do_not_change_raw_spearman_sample() -> None:
    frame = _frame()
    baseline_report = evaluate_incremental_features(
        frame,
        candidate_columns=("candidate_sma150_slope",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    missing_baseline = frame.copy()
    missing_baseline.loc[0:4, "baseline_structure"] = np.nan
    changed_report = evaluate_incremental_features(
        missing_baseline,
        candidate_columns=("candidate_sma150_slope",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    before = next(metric for metric in baseline_report.metrics if metric.split == "DISCOVERY")
    after = next(metric for metric in changed_report.metrics if metric.split == "DISCOVERY")
    assert after.sample_count == before.sample_count == 20
    assert after.raw_spearman == before.raw_spearman
    assert after.partial_sample_count == 15


def test_partial_metric_is_none_when_controls_exhaust_residual_degrees_of_freedom() -> None:
    rows = []
    for split in ("DISCOVERY", "VALIDATION", "HOLDOUT"):
        for index in range(3):
            rows.append(
                {
                    "split": split,
                    "baseline_structure": float(index),
                    "candidate_sma150_slope": float(index * 2 + 1),
                    "forward_return_pct": float(index * 3 + 2),
                }
            )
    report = evaluate_incremental_features(
        pd.DataFrame(rows),
        candidate_columns=("candidate_sma150_slope",),
        baseline_columns=("baseline_structure",),
        outcome_column="forward_return_pct",
    )

    assert all(metric.sample_count == 3 for metric in report.metrics)
    assert all(metric.partial_sample_count == 3 for metric in report.metrics)
    assert all(metric.partial_spearman_given_baseline is None for metric in report.metrics)


def test_rejects_unknown_splits_missing_splits_and_role_aliases() -> None:
    frame = _frame()
    bad_split = frame.copy()
    bad_split.loc[0, "split"] = "TEST"

    with pytest.raises(MAVolumeValidationInputError, match="unknown split"):
        evaluate_incremental_features(
            bad_split,
            candidate_columns=("candidate_sma150_slope",),
            baseline_columns=("baseline_structure",),
            outcome_column="forward_return_pct",
        )

    missing_holdout = frame.loc[frame["split"] != "HOLDOUT"].copy()
    with pytest.raises(MAVolumeValidationInputError, match="missing required split"):
        evaluate_incremental_features(
            missing_holdout,
            candidate_columns=("candidate_sma150_slope",),
            baseline_columns=("baseline_structure",),
            outcome_column="forward_return_pct",
        )

    alias_cases = (
        (("baseline_structure",), ("baseline_structure",), "forward_return_pct", "split"),
        (("forward_return_pct",), ("baseline_structure",), "forward_return_pct", "split"),
        (("candidate_sma150_slope",), ("forward_return_pct",), "forward_return_pct", "split"),
        (("split",), ("baseline_structure",), "forward_return_pct", "split"),
        (("candidate_sma150_slope",), ("split",), "forward_return_pct", "split"),
        (("candidate_sma150_slope",), ("baseline_structure",), "split", "split"),
    )
    for candidates, baselines, outcome, split_column in alias_cases:
        with pytest.raises(MAVolumeValidationInputError, match="mutually disjoint"):
            evaluate_incremental_features(
                frame,
                candidate_columns=candidates,
                baseline_columns=baselines,
                outcome_column=outcome,
                split_column=split_column,
            )
