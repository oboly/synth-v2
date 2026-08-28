from __future__ import annotations

"""Frozen preregistration registry for Issue #418 BTC-to-alt Breathline research.

This module contains hypotheses and deterministic analysis contracts only. It
must not inspect market outcomes or alter the single-symbol #417 tracker.

Registry v1.0.3 is a pre-analysis architecture clarification created after
independent BTC and RENDER ledgers were frozen but before any BTC↔RENDER
relationship statistic was inspected.

Audit trail:
- v1.0.1 fixed exact statistics, minimum support and verdict rules;
- v1.0.2 fixed split-preserving permutation implementation;
- v1.0.3 makes explicit that SHARED_EXTENSION is retrospective association
  evidence because it uses completed maximum-overlap pairing. Only the PIT
  ROTATION_CANDIDATE lane may produce predictive research evidence.

The symbols, split, null families, seed, permutation count, hypotheses and
architecture boundary remain unchanged from v1.0.0.

Research-only, market-only, account-agnostic.
"""

from dataclasses import asdict, dataclass
from typing import Any

REGISTRY_NAME = "breathline_btc_alt_relationship_v1"
REGISTRY_VERSION = "1.0.3"

REFERENCE_SYMBOL = "BTC"
ALT_SYMBOL = "RENDER"
VENUE = "bitvavo"
INTERVAL_CODE = "4h"

DISCOVERY_FRACTION = 0.70
NULL_PERMUTATIONS = 2000
RANDOM_SEED = 418001
ALPHA = 0.05
MULTIPLE_COMPARISON_METHOD = "holm_bonferroni"

MIN_PAIRED_CYCLES_PER_SPLIT = 8
MIN_EVENT_COMPARISONS_PER_SPLIT = 5
MIN_SEQUENCE_CYCLES_PER_SPLIT = 5
MIN_BINARY_ROWS_PER_SPLIT = 10
MIN_BINARY_CLASS_COUNT = 3
MIN_PRIOR_RENDER_OUTCOMES = 8
MIN_SIGNIFICANT_LAG_EVENTS = 2

EVENTS: tuple[str, ...] = (
    "start",
    "recognition",
    "ignition",
    "main_pulse",
    "extension",
    "end",
)

PHASE_CHECKPOINTS: tuple[str, ...] = (
    "recognition",
    "ignition",
    "main_pulse",
    "extension",
)

PREDICTIVE_ALT_CHECKPOINTS: tuple[str, ...] = (
    "recognition",
    "ignition",
)

PREDICTIVE_OUTCOMES: tuple[str, ...] = (
    "main_pulse_confirmed",
    "extension_confirmed",
)

ROTATION_FEATURES: tuple[str, ...] = (
    "btc_main_pulse_recency_score",
    "btc_extension_recency_score",
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


@dataclass(frozen=True)
class ExactTestContract:
    phase_lock_statistic: str
    lead_lag_statistic: str
    convergence_statistic: str
    detached_sequence_rule: str
    relock_sequence_rule: str
    shared_extension_statistic: str
    rotation_candidate_statistic: str
    no_btc_baseline: str
    permutation_p_value: str
    multiple_comparison_scope: str


@dataclass(frozen=True)
class NullImplementationContract:
    pair_permutation: str
    event_timing_permutation: str
    extension_label_permutation: str
    missingness_rule: str


@dataclass(frozen=True)
class VerdictContract:
    phase_lock: str
    lead_lag: str
    convergence_divergence: str
    detached_relock: str
    shared_extension: str
    rotation_candidate: str
    overall: str
    insufficient: str


PAIRING_CONTRACT = PairingContract(
    primary_pairing=(
        "for each completed RENDER cycle, pair to the completed BTC cycle with maximum wall-clock overlap; overlap is max(0, min(end)-max(start))"
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
        "at each RENDER phase-checkpoint event timestamp that lies inside both paired completed cycles, signed_phase_delta=RENDER_realized_phase-BTC_realized_phase and absolute_phase_delta=abs(signed_phase_delta); do not wrap modulo 1"
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

EXACT_TEST_CONTRACT = ExactTestContract(
    phase_lock_statistic=(
        "mean absolute phase delta across all available RENDER recognition/ignition/main_pulse/extension timestamps that fall inside both paired completed cycles; lower is more phase-locked"
    ),
    lead_lag_statistic=(
        "per event name, mean signed same-event lag in days; discovery sign fixes candidate direction; start and end are descriptive only, inferential family is recognition/ignition/main_pulse/extension"
    ),
    convergence_statistic=(
        "per paired cycle, net_abs_phase_delta_change=last comparable absolute phase delta minus first comparable absolute phase delta across recognition/ignition/main_pulse/extension; mean across cycles; negative favors CONVERGING and positive favors DIVERGING"
    ),
    detached_sequence_rule=(
        "DETACHED sequence exists when a paired cycle has at least two consecutive positive changes in absolute phase delta across retained phase checkpoints; no magnitude threshold"
    ),
    relock_sequence_rule=(
        "RELOCK sequence exists when a DETACHED sequence is followed later in the same paired cycle by at least one negative change in absolute phase delta; no magnitude threshold"
    ),
    shared_extension_statistic=(
        "retrospective holdout association only: difference in RENDER extension-confirmation rate between completed maximum-overlap paired BTC extension_confirmed=true and false cycles; positive favors SHARED_EXTENSION but does not create PIT predictive authority"
    ),
    rotation_candidate_statistic=(
        "at each RENDER recognition/ignition feature_as_of_ts, define BTC recency scores as negative days since latest prior-confirmed BTC main-pulse or extension event respectively; higher means more recent; test tie-aware ROC AUC for later RENDER main_pulse_confirmed and extension_confirmed"
    ),
    no_btc_baseline=(
        "expanding prior RENDER outcome probability using only prior cycles with outcome_as_of_ts < feature_as_of_ts; require at least MIN_PRIOR_RENDER_OUTCOMES; compare holdout AUC of BTC recency score against this no-BTC prior score"
    ),
    permutation_p_value=(
        "(1 + count(null statistic at least as favorable as observed in the preregistered direction)) / (NULL_PERMUTATIONS + 1)"
    ),
    multiple_comparison_scope=(
        "Holm-Bonferroni alpha 0.05 is applied to holdout p-values within each hypothesis family: lead_lag over four inferential event names; detached_relock over DETACHED and RELOCK; rotation_candidate over 2 checkpoints x 2 BTC recency features x 2 outcomes. Other hypothesis families have one holdout test each."
    ),
)

NULL_IMPLEMENTATION_CONTRACT = NullImplementationContract(
    pair_permutation=(
        "within each split, permute retained BTC paired-cycle measurement vectors across RENDER pair rows with identical checkpoint-support patterns. Do not recompute wall-clock overlap after permutation. This preserves observed support while breaking BTC↔RENDER pairing association."
    ),
    event_timing_permutation=(
        "for Lane A LEADING/LAGGING, within each split and event name permute retained BTC same-event timestamps across rows with that event comparison. For Lane B ROTATION_CANDIDATE, within each split/checkpoint/feature/outcome test permute retained BTC recency-score values across the exact matched rows."
    ),
    extension_label_permutation=(
        "within each split, permute retained BTC extension_confirmed labels across the exact completed paired rows used by SHARED_EXTENSION"
    ),
    missingness_rule=(
        "all nulls operate on the exact observed eligible row set for that statistic; permutation changes only the preregistered BTC measurement, timing-score or label assignment. Row count, RENDER outcomes and missingness/support are invariant across permutations."
    ),
)

VERDICT_CONTRACT = VerdictContract(
    phase_lock=(
        "SUPPORTED_STRUCTURAL only if discovery observed mean absolute phase delta is below its permutation-null median and holdout observed mean is also below null median with holdout p<0.05; never predictive authority by itself"
    ),
    lead_lag=(
        "LEADING or LAGGING only if at least MIN_SIGNIFICANT_LAG_EVENTS inferential events have sufficient discovery+holdout support, discovery and holdout mean lags have the same sign, and their Holm-adjusted holdout p-values are <0.05; all significant events must agree on direction"
    ),
    convergence_divergence=(
        "CONVERGING or DIVERGING only if discovery and holdout mean net_abs_phase_delta_change have the same non-zero sign and holdout permutation p<0.05; negative=CONVERGING, positive=DIVERGING"
    ),
    detached_relock=(
        "DETACHED and RELOCK are tested separately as split-level sequence-rate excess over pair-permutation null; require discovery observed rate above null median and Holm-adjusted holdout p<0.05 with holdout rate above null median"
    ),
    shared_extension=(
        "SUPPORTED_ASSOCIATION only if discovery and holdout conditional-rate differences are positive and holdout permutation p<0.05; because maximum-overlap pairing uses completed cycle ends this result belongs to Lane A and cannot satisfy the predictive promotion gate"
    ),
    rotation_candidate=(
        "ROTATION_CANDIDATE only if at least one preregistered checkpoint/feature/outcome test has discovery AUC>0.5, holdout AUC>0.5, holdout AUC greater than the matched no-BTC expanding-prior AUC, and Holm-adjusted holdout permutation p<0.05"
    ),
    overall=(
        "overall evidence is POSITIVE_RESEARCH_EVIDENCE only when ROTATION_CANDIDATE is supported in PIT Lane B; any supported Lane A hypothesis, including SHARED_EXTENSION association, yields STRUCTURAL_EVIDENCE_ONLY; otherwise emit UNRELATED"
    ),
    insufficient=(
        "emit INSUFFICIENT_EVIDENCE for a hypothesis when either split fails its frozen minimum-support rule; never lower minimums after outcome inspection"
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
        "phase_checkpoints": list(PHASE_CHECKPOINTS),
        "predictive_alt_checkpoints": list(PREDICTIVE_ALT_CHECKPOINTS),
        "predictive_outcomes": list(PREDICTIVE_OUTCOMES),
        "rotation_features": list(ROTATION_FEATURES),
        "relationship_hypotheses": list(RELATIONSHIP_HYPOTHESES),
        "pairing": asdict(PAIRING_CONTRACT),
        "split": asdict(SPLIT_CONTRACT),
        "retrospective": asdict(RETROSPECTIVE_CONTRACT),
        "predictive": asdict(PREDICTIVE_CONTRACT),
        "exact_tests": asdict(EXACT_TEST_CONTRACT),
        "null_implementation": asdict(NULL_IMPLEMENTATION_CONTRACT),
        "verdicts": asdict(VERDICT_CONTRACT),
        "minimum_support": {
            "paired_cycles_per_split": MIN_PAIRED_CYCLES_PER_SPLIT,
            "event_comparisons_per_split": MIN_EVENT_COMPARISONS_PER_SPLIT,
            "sequence_cycles_per_split": MIN_SEQUENCE_CYCLES_PER_SPLIT,
            "binary_rows_per_split": MIN_BINARY_ROWS_PER_SPLIT,
            "binary_class_count": MIN_BINARY_CLASS_COUNT,
            "prior_render_outcomes": MIN_PRIOR_RENDER_OUTCOMES,
            "significant_lag_events": MIN_SIGNIFICANT_LAG_EVENTS,
        },
        "null_controls": list(NULL_CONTROLS),
        "null_permutations": NULL_PERMUTATIONS,
        "random_seed": RANDOM_SEED,
        "multiple_comparison_method": MULTIPLE_COMPARISON_METHOD,
        "alpha": ALPHA,
        "decision_contract": {
            "positive_relationship_requires": (
                "directionally consistent discovery and holdout evidence plus null-control superiority; no relationship is promoted from retrospective fit alone"
            ),
            "predictive_authority_source": "ROTATION_CANDIDATE PIT Lane B only",
            "shared_extension_authority": "retrospective association only",
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
    if MIN_PAIRED_CYCLES_PER_SPLIT < 1 or MIN_EVENT_COMPARISONS_PER_SPLIT < 1:
        raise RuntimeError("retrospective minimum support must be positive")
    if MIN_BINARY_ROWS_PER_SPLIT < 2 * MIN_BINARY_CLASS_COUNT:
        raise RuntimeError("binary row minimum cannot be below two class minima")
    if MIN_SIGNIFICANT_LAG_EVENTS < 1 or MIN_SIGNIFICANT_LAG_EVENTS > len(PHASE_CHECKPOINTS):
        raise RuntimeError("significant lag event requirement is invalid")


validate_registry()
