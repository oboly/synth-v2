from __future__ import annotations

"""Frozen preregistration registry for Issue #418 BTC-to-alt Breathline research.

This module contains hypotheses and deterministic analysis contracts only. It
must not inspect market outcomes or alter the single-symbol #417 tracker.

Research-only, market-only, account-agnostic.
"""

from dataclasses import asdict, dataclass
from typing import Any


REGISTRY_NAME = "breathline_btc_alt_relationship_v1"
REGISTRY_VERSION = "1.0.0"

REFERENCE_SYMBOL = "BTC"
ALT_SYMBOL = "RENDER"
VENUE = "bitvavo"
INTERVAL_CODE = "4h"

DISCOVERY_FRACTION = 0.70
NULL_PERMUTATIONS = 2000
RANDOM_SEED = 418001
ALPHA = 0.05
MULTIPLE_COMPARISON_METHOD = "holm_bonferroni"

EVENTS: tuple[str, ...] = (
    "start",
    "recognition",
    "ignition",
    "main_pulse",
    "extension",
    "end",
)

PREDICTIVE_ALT_CHECKPOINTS: tuple[str, ...] = (
    "recognition",
    "ignition",
)

RELATIONSHIP_HYPOTHESES: tuple[str, ...] = (
    "PHASE_LOCK",
    "LEADING",
    "LAGGING",
    "CONVERGING",
    "DIVERGING",
    "DETACHED",
    "RELOCK",
    "SHARED_EXTENSION",
    "ROTATION_CANDIDATE",
    "UNRELATED",
    "INSUFFICIENT_EVIDENCE",
)

NULL_CONTROLS: tuple[str, ...] = (
    "within_split_btc_cycle_pair_permutation",
    "within_split_btc_event_timing_permutation",
    "within_split_btc_extension_label_permutation",
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
class PairingContract:
    primary_pairing: str
    tie_break: str
    zero_overlap_behavior: str
    no_many_to_one_prohibition: bool


@dataclass(frozen=True)
class SplitContract:
    ordering: str
    discovery_fraction: float
    holdout_definition: str
    walk_forward_definition: str


@dataclass(frozen=True)
class RetrospectiveContract:
    lifecycle_phase_definition: str
    phase_delta_definition: str
    event_lag_definition: str
    convergence_definition: str


@dataclass(frozen=True)
class PredictiveContract:
    checkpoint_rule: str
    btc_information_rule: str
    forbidden_future_fields: tuple[str, ...]
    outcome_rule: str


PAIRING_CONTRACT = PairingContract(
    primary_pairing=(
        "for each completed RENDER cycle, pair to the completed BTC cycle with "
        "maximum wall-clock overlap; overlap is max(0, min(end)-max(start))"
    ),
    tie_break=(
        "largest overlap, then smallest absolute start-time lag, then earliest BTC start_ts, then lexical BTC cycle_id"
    ),
    zero_overlap_behavior="retain the RENDER cycle as UNPAIRED; never nearest-neighbor force a pair",
    no_many_to_one_prohibition=False,
)

SPLIT_CONTRACT = SplitContract(
    ordering="chronological_by_RENDER_cycle_start_ts",
    discovery_fraction=DISCOVERY_FRACTION,
    holdout_definition=(
        "first floor(70%) RENDER cycles are discovery and remaining cycles are holdout; the split is frozen before relationship outcomes"
    ),
    walk_forward_definition=(
        "expanding history; a prediction at an alt checkpoint may use only BTC and RENDER evidence whose availability timestamp is <= that checkpoint timestamp"
    ),
)

RETROSPECTIVE_CONTRACT = RetrospectiveContract(
    lifecycle_phase_definition=(
        "for a wall-clock timestamp t inside a completed cycle, realized_phase=(t-start_ts)/(end_ts-start_ts); this may use realized end_ts only in retrospective Lane A"
    ),
    phase_delta_definition=(
        "at each retained shared wall-clock event timestamp, signed_phase_delta=RENDER_realized_phase-BTC_realized_phase and absolute_phase_delta=abs(signed_phase_delta); do not wrap modulo 1"
    ),
    event_lag_definition=(
        "event_lag_days=(RENDER_event_ts-BTC_event_ts)/86400 for same-named present events in paired completed cycles; positive means RENDER later/lags BTC"
    ),
    convergence_definition=(
        "continuous change in absolute phase delta between successive comparable retained checkpoints; negative change is convergence, positive change is divergence; no post-hoc close-enough threshold"
    ),
)

PREDICTIVE_CONTRACT = PredictiveContract(
    checkpoint_rule=(
        "prediction rows are formed only at RENDER recognition_ts and ignition_ts, using the checkpoint's confirmed_at timestamp when available as feature_as_of_ts"
    ),
    btc_information_rule=(
        "at feature_as_of_ts, only BTC event/state information with its own availability/confirmation timestamp <= feature_as_of_ts may be used"
    ),
    forbidden_future_fields=(
        "BTC or RENDER realized full-cycle end/duration not yet known at feature_as_of_ts",
        "future BTC or RENDER main-pulse/extension outcome",
        "future reset or phase-shift state",
        "retrospective best pairing selected using a future cycle end",
        "future realized phase progress",
        "relationship label derived from holdout outcomes",
    ),
    outcome_rule=(
        "later RENDER main_pulse_confirmed, extension_confirmed and event timing are outcomes only; predictive usefulness must beat shuffled controls and simpler no-BTC historical baselines"
    ),
)


def registry_payload() -> dict[str, Any]:
    return {
        "registry_name": REGISTRY_NAME,
        "registry_version": REGISTRY_VERSION,
        "reference_symbol": REFERENCE_SYMBOL,
        "alt_symbol": ALT_SYMBOL,
        "venue": VENUE,
        "interval_code": INTERVAL_CODE,
        "events": list(EVENTS),
        "predictive_alt_checkpoints": list(PREDICTIVE_ALT_CHECKPOINTS),
        "relationship_hypotheses": list(RELATIONSHIP_HYPOTHESES),
        "pairing": asdict(PAIRING_CONTRACT),
        "split": asdict(SPLIT_CONTRACT),
        "retrospective": asdict(RETROSPECTIVE_CONTRACT),
        "predictive": asdict(PREDICTIVE_CONTRACT),
        "null_controls": list(NULL_CONTROLS),
        "null_permutations": NULL_PERMUTATIONS,
        "random_seed": RANDOM_SEED,
        "multiple_comparison_method": MULTIPLE_COMPARISON_METHOD,
        "alpha": ALPHA,
        "decision_contract": {
            "positive_relationship_requires": (
                "directionally consistent discovery and holdout evidence plus null-control superiority; no relationship is promoted from retrospective fit alone"
            ),
            "unrelated_default": (
                "if holdout/null evidence does not support a preregistered relationship, emit UNRELATED; if sample support is too small, emit INSUFFICIENT_EVIDENCE"
            ),
            "asset_specific_first": True,
            "runtime_promotion": False,
        },
        "safety": dict(SAFETY_MARKERS),
    }


def validate_registry() -> None:
    if not 0.0 < DISCOVERY_FRACTION < 1.0:
        raise RuntimeError("discovery fraction must be between 0 and 1")
    if NULL_PERMUTATIONS < 1000:
        raise RuntimeError("null permutation count below preregistered minimum")
    if MULTIPLE_COMPARISON_METHOD != "holm_bonferroni":
        raise RuntimeError("multiple-comparison method changed")
    if REFERENCE_SYMBOL == ALT_SYMBOL:
        raise RuntimeError("reference and alt symbols must differ")
    if "UNRELATED" not in RELATIONSHIP_HYPOTHESES:
        raise RuntimeError("UNRELATED must remain an explicit outcome")
    if "INSUFFICIENT_EVIDENCE" not in RELATIONSHIP_HYPOTHESES:
        raise RuntimeError("INSUFFICIENT_EVIDENCE must remain an explicit outcome")


validate_registry()
