from __future__ import annotations

"""Frozen hypothesis/analysis registry for Issue #533.

This module is the preregistration boundary for the Breathline harmonic-family
falsification study. It contains no market outcomes and performs no analysis.

Research-only, market-only, account-agnostic.
"""

from dataclasses import asdict, dataclass
from typing import Any


REGISTRY_NAME = "breathline_harmonic_family_falsification_v1"
REGISTRY_VERSION = "1.0.1"

DURATION_FAMILY_DAYS: tuple[float, ...] = (
    3.0,
    6.0,
    9.0,
    12.0,
    21.0,
    42.0,
    63.0,
    105.0,
    126.0,
    147.0,
)

PHASE_MARKERS: tuple[tuple[str, float], ...] = (
    ("first_high", 0.236),
    ("first_low", 0.382),
    ("second_high", 0.500),
    ("recognition", 0.618),
    ("ignition", 0.786),
    ("main_pulse", 1.000),
    ("extension", 1.272),
)

HALF_PHASE_SPLIT_CANDIDATE_DAYS = 10.5

DISCOVERY_FRACTION = 0.70
WALK_FORWARD_MIN_PRIOR_ASSET_CYCLES = 8
WALK_FORWARD_MIN_PRIOR_POOLED_CYCLES = 12

NULL_PERMUTATIONS = 2000
RANDOM_SEED = 533001
ALPHA = 0.05
MULTIPLE_COMPARISON_METHOD = "holm_bonferroni"

CHECKPOINTS: tuple[tuple[str, float], ...] = (
    ("recognition", 0.618),
    ("ignition", 0.786),
)

BINARY_OUTCOMES: tuple[str, ...] = (
    "main_pulse_confirmed",
    "extension_confirmed",
)

EVENT_TIMING_OUTCOMES: tuple[tuple[str, float], ...] = (
    ("main_pulse", 1.000),
    ("extension", 1.272),
)

BASELINES: tuple[str, ...] = (
    "fixed_21d",
    "asset_prior_median_completed_duration",
    "pooled_prior_median_completed_duration",
)

NULL_CONTROLS: tuple[str, ...] = (
    "lane_a_phase_circular_shift_within_cycle",
    "lane_b_binary_outcome_permutation_within_asset_checkpoint",
    "lane_b_duration_outcome_permutation_within_asset",
)

METRICS: tuple[str, ...] = (
    "sample_count",
    "observed_cycle_length_days",
    "absolute_duration_error_days",
    "relative_duration_error",
    "nearest_candidate_duration_days",
    "nearest_candidate_absolute_error_days",
    "nearest_candidate_relative_error",
    "node_timing_residual_days",
    "phase_position_residual",
    "checkpoint_alignment_absolute_error_days",
    "checkpoint_alignment_auc",
    "continuation_probability",
    "extension_probability",
    "false_extension_rate",
    "mfe_pct",
    "mae_pct",
    "time_to_main_pulse_days",
    "time_to_extension_days",
    "event_timing_absolute_error_days",
    "duration_prediction_absolute_error_days",
    "duration_prediction_relative_error",
    "reset_frequency",
    "phase_shift_frequency",
)

SAFETY_MARKERS: dict[str, Any] = {
    "research_only": True,
    "market_only": True,
    "account_awareness": 0,
    "selection_engine_changes": 0,
    "decision_gate_changes": 0,
    "execution_planner_changes": 0,
    "executor_changes": 0,
    "broker_calls": 0,
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "live_trading_permission": 0,
    "production_db_writes": 0,
    "production_schema_changes": 0,
    "runtime_activation": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


@dataclass(frozen=True)
class SplitContract:
    discovery_fraction: float
    ordering: str
    per_asset_first: bool
    pooled_after_per_asset: bool
    holdout_definition: str
    walk_forward_definition: str
    min_prior_asset_cycles: int
    min_prior_pooled_cycles: int


@dataclass(frozen=True)
class NullContract:
    permutations: int
    random_seed: int
    phase_null: str
    binary_null: str
    duration_null: str
    permutation_p_value: str


@dataclass(frozen=True)
class MultipleComparisonContract:
    method: str
    alpha: float
    duration_scope: str
    phase_scope: str


SPLIT_CONTRACT = SplitContract(
    discovery_fraction=DISCOVERY_FRACTION,
    ordering="chronological_by_cycle_start_ts",
    per_asset_first=True,
    pooled_after_per_asset=True,
    holdout_definition=(
        "last 30% of cycles per asset after chronological ordering; pooled holdout is the union of per-asset holdouts"
    ),
    walk_forward_definition=(
        "expanding history; a current checkpoint may use only cycles whose outcome_as_of_ts is strictly earlier than that checkpoint feature_as_of_ts"
    ),
    min_prior_asset_cycles=WALK_FORWARD_MIN_PRIOR_ASSET_CYCLES,
    min_prior_pooled_cycles=WALK_FORWARD_MIN_PRIOR_POOLED_CYCLES,
)

NULL_CONTRACT = NullContract(
    permutations=NULL_PERMUTATIONS,
    random_seed=RANDOM_SEED,
    phase_null=(
        "for each completed cycle, circularly shift all observed internal phase positions by one deterministic seeded U[0,1) offset modulo 1; preserve relative node spacing; for both observed and null significance statistics map observed position and marker ratio modulo 1 and use shortest unit-circle distance min(abs(a-b), 1-abs(a-b)); unwrapped timing/phase residuals remain descriptive outputs"
    ),
    binary_null=(
        "within each asset/checkpoint evaluation set, permute future binary outcome labels after predictor rows are frozen"
    ),
    duration_null=(
        "within each asset evaluation set, permute future observed full-cycle durations after point-in-time predictions are frozen"
    ),
    permutation_p_value=(
        "(1 + count(null statistic at least as favorable as observed)) / (permutations + 1)"
    ),
)

MULTIPLE_COMPARISON_CONTRACT = MultipleComparisonContract(
    method=MULTIPLE_COMPARISON_METHOD,
    alpha=ALPHA,
    duration_scope=(
        "correct the 10 frozen duration-family member tests within each population x checkpoint x future-outcome x metric family"
    ),
    phase_scope=(
        "correct the 7 frozen phase-marker tests within each population for Lane A structural phase fit"
    ),
)


def phase_ratio(name: str) -> float:
    mapping = dict(PHASE_MARKERS)
    if name not in mapping:
        raise KeyError(name)
    return mapping[name]


def registry_payload() -> dict[str, Any]:
    return {
        "registry_name": REGISTRY_NAME,
        "registry_version": REGISTRY_VERSION,
        "duration_family_days": list(DURATION_FAMILY_DAYS),
        "phase_markers": [
            {"node": node, "ratio": ratio} for node, ratio in PHASE_MARKERS
        ],
        "half_phase_split_candidate_days": HALF_PHASE_SPLIT_CANDIDATE_DAYS,
        "checkpoints": [
            {"checkpoint": checkpoint, "ratio": ratio}
            for checkpoint, ratio in CHECKPOINTS
        ],
        "binary_outcomes": list(BINARY_OUTCOMES),
        "event_timing_outcomes": [
            {"event": event, "ratio": ratio}
            for event, ratio in EVENT_TIMING_OUTCOMES
        ],
        "baselines": list(BASELINES),
        "null_controls": list(NULL_CONTROLS),
        "metrics": list(METRICS),
        "split": asdict(SPLIT_CONTRACT),
        "nulls": asdict(NULL_CONTRACT),
        "multiple_comparisons": asdict(MULTIPLE_COMPARISON_CONTRACT),
        "lane_a": {
            "claim_type": "retrospective_descriptive_only",
            "may_use_realized_full_cycle_duration": True,
            "duration_fit": (
                "retain residuals against every frozen duration candidate plus nearest-family and fixed-21d residuals"
            ),
            "phase_fit": (
                "expected node time = cycle_start + observed_cycle_length_days * preregistered node ratio; retain continuous unwrapped timing and normalized phase-position residuals; phase-null significance uses the separately frozen shortest unit-circle distance for both observed and shifted-null statistics"
            ),
            "no_close_enough_threshold": True,
        },
        "lane_b": {
            "claim_type": "point_in_time_predictive_validation",
            "future_fields_forbidden_as_predictors": [
                "observed_cycle_length_days",
                "future_best_fit_phase_offset",
                "future_drift",
                "eventual_main_pulse_outcome",
                "eventual_extension_outcome",
                "future_reset_state",
                "future_phase_shift_state",
            ],
            "checkpoint_alignment_error": (
                "abs((checkpoint_ts - cycle_start_ts).days - candidate_duration_days * checkpoint_ratio)"
            ),
            "alignment_score": "negative checkpoint_alignment_error_days; larger is better",
            "recognition_ignition_accuracy_definition": (
                "continuous checkpoint-alignment MAE; no binary close-enough threshold"
            ),
            "family_duration_selector": (
                "candidate with minimum current checkpoint alignment absolute error; ties resolve by ascending frozen candidate order"
            ),
            "fixed_21d_baseline": 21.0,
            "historical_baseline_statistic": "median completed observed cycle duration",
            "historical_baseline_pit_rule": (
                "only cycles with outcome_as_of_ts strictly earlier than current feature_as_of_ts may contribute"
            ),
            "candidate_binary_discrimination": (
                "tie-aware ROC AUC of negative checkpoint-alignment error versus later main-pulse/extension outcomes"
            ),
            "event_timing_prediction": (
                "predicted event timestamp = cycle_start + predicted_duration * preregistered event ratio"
            ),
            "duration_prediction_evaluation": (
                "realized full-cycle duration is evaluation-only and may never select or alter a current predictor"
            ),
        },
        "multiple_comparison_method": MULTIPLE_COMPARISON_METHOD,
        "alpha": ALPHA,
        "null_permutations": NULL_PERMUTATIONS,
        "random_seed": RANDOM_SEED,
        "safety": dict(SAFETY_MARKERS),
    }


def validate_registry() -> None:
    if DURATION_FAMILY_DAYS != tuple(sorted(set(DURATION_FAMILY_DAYS))):
        raise RuntimeError("duration family must be unique and ascending")
    if 21.0 not in DURATION_FAMILY_DAYS:
        raise RuntimeError("21d prior must remain in the frozen family")
    if HALF_PHASE_SPLIT_CANDIDATE_DAYS in DURATION_FAMILY_DAYS:
        raise RuntimeError("10.5d HALF_PHASE_SPLIT must remain separate")
    if tuple(ratio for _, ratio in PHASE_MARKERS) != (
        0.236,
        0.382,
        0.500,
        0.618,
        0.786,
        1.000,
        1.272,
    ):
        raise RuntimeError("phase-marker ratios changed")
    if not 0.0 < DISCOVERY_FRACTION < 1.0:
        raise RuntimeError("discovery fraction must be between 0 and 1")
    if NULL_PERMUTATIONS < 1000:
        raise RuntimeError("permutation count is below preregistered minimum")
    if MULTIPLE_COMPARISON_METHOD != "holm_bonferroni":
        raise RuntimeError("multiple-comparison method changed")


validate_registry()
