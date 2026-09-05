"""Research-only incremental validation harness for Issue #310.

Consumes a frozen point-in-time feature table with explicit split labels and
future outcome labels. It reports raw and baseline-controlled rank association
for candidate MA/volume features. It does not choose thresholds, fit a trading
model, rank live assets, or write production state.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Final, Iterable

import numpy as np
import pandas as pd

MODEL_ID: Final[str] = "ma_volume_incremental_validation"
MODEL_VERSION: Final[str] = "1.0"
ALLOWED_SPLITS: Final[tuple[str, ...]] = ("DISCOVERY", "VALIDATION", "HOLDOUT")


class MAVolumeValidationInputError(ValueError):
    """Raised when the frozen validation frame is incomplete or ambiguous."""


@dataclass(frozen=True)
class FeatureSplitMetricV1:
    feature: str
    split: str
    sample_count: int
    raw_spearman: float | None
    partial_spearman_given_baseline: float | None


@dataclass(frozen=True)
class MAVolumeValidationReportV1:
    model_id: str
    model_version: str
    outcome_column: str
    baseline_columns: tuple[str, ...]
    candidate_columns: tuple[str, ...]
    metrics: tuple[FeatureSplitMetricV1, ...]


def _ordered_unique(values: Iterable[str], *, name: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result:
        raise MAVolumeValidationInputError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise MAVolumeValidationInputError(f"{name} contains duplicates")
    return result


def _rank(series: pd.Series) -> np.ndarray:
    return series.rank(method="average").to_numpy(dtype=float)


def _safe_corr(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 3:
        return None
    if np.nanstd(left) == 0.0 or np.nanstd(right) == 0.0:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if isfinite(value) else None


def _residualize(target: np.ndarray, controls: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(target), dtype=float), controls])
    beta, *_ = np.linalg.lstsq(design, target, rcond=None)
    return target - design @ beta


def _partial_spearman(
    frame: pd.DataFrame,
    *,
    feature: str,
    outcome: str,
    baseline_columns: tuple[str, ...],
) -> float | None:
    feature_rank = _rank(frame[feature])
    outcome_rank = _rank(frame[outcome])
    if not baseline_columns:
        return _safe_corr(feature_rank, outcome_rank)
    controls = np.column_stack([_rank(frame[column]) for column in baseline_columns])
    feature_residual = _residualize(feature_rank, controls)
    outcome_residual = _residualize(outcome_rank, controls)
    return _safe_corr(feature_residual, outcome_residual)


def evaluate_incremental_features(
    frame: pd.DataFrame,
    *,
    candidate_columns: Iterable[str],
    baseline_columns: Iterable[str],
    outcome_column: str,
    split_column: str = "split",
) -> MAVolumeValidationReportV1:
    """Evaluate candidate monotonic information separately inside frozen splits.

    Rank transforms and baseline residualization are performed independently per
    split. No row from one split can influence another split's metric.
    """
    candidates = _ordered_unique(candidate_columns, name="candidate_columns")
    baselines = tuple(baseline_columns)
    if len(set(baselines)) != len(baselines):
        raise MAVolumeValidationInputError("baseline_columns contains duplicates")
    if set(candidates).intersection(baselines):
        raise MAVolumeValidationInputError("candidate and baseline columns must be disjoint")

    required = {split_column, outcome_column, *candidates, *baselines}
    missing = required.difference(frame.columns)
    if missing:
        raise MAVolumeValidationInputError(f"validation frame missing columns: {sorted(missing)}")
    if frame.empty:
        raise MAVolumeValidationInputError("validation frame must not be empty")

    split_values = set(frame[split_column].astype(str))
    unknown = split_values.difference(ALLOWED_SPLITS)
    if unknown:
        raise MAVolumeValidationInputError(f"unknown split labels: {sorted(unknown)}")

    metrics: list[FeatureSplitMetricV1] = []
    for split in ALLOWED_SPLITS:
        split_frame = frame.loc[frame[split_column].astype(str) == split].copy()
        if split_frame.empty:
            continue
        for feature in candidates:
            columns = [feature, outcome_column, *baselines]
            usable = split_frame.loc[:, columns].apply(pd.to_numeric, errors="coerce").dropna()
            raw = None
            partial = None
            if len(usable) >= 3:
                raw = _safe_corr(_rank(usable[feature]), _rank(usable[outcome_column]))
                partial = _partial_spearman(
                    usable,
                    feature=feature,
                    outcome=outcome_column,
                    baseline_columns=baselines,
                )
            metrics.append(
                FeatureSplitMetricV1(
                    feature=feature,
                    split=split,
                    sample_count=len(usable),
                    raw_spearman=raw,
                    partial_spearman_given_baseline=partial,
                )
            )

    return MAVolumeValidationReportV1(
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        outcome_column=outcome_column,
        baseline_columns=baselines,
        candidate_columns=candidates,
        metrics=tuple(metrics),
    )
