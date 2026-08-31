from __future__ import annotations

"""Frozen temporal/stability metrics for Issue #593 validation."""

from dataclasses import asdict, dataclass
from datetime import timedelta
from statistics import mean
from typing import Sequence

from src.research.multi_horizon_rotation_validation_v1 import (
    CANDIDATE_IDS,
    FORWARD_FIELDS,
    SAMPLE_INTERVAL,
    ValidationRow,
    correlation_with_fisher_ci,
    ensure_utc,
)


MAX_TURN_MATCH_LAG_SAMPLES = 16
MIN_REGIME_SAMPLE_COUNT = 30


@dataclass(frozen=True)
class LeadLagResult:
    candidate_turn_count: int
    reference_turn_count: int
    paired_turn_count: int
    unmatched_candidate_turn_count: int
    unmatched_reference_turn_count: int
    mean_delta_samples: float | None
    median_delta_samples: float | None
    min_delta_samples: int | None
    max_delta_samples: int | None


def _state(value: float | None) -> int | None:
    if value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _median(values: Sequence[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _turns(rows: Sequence[ValidationRow], *, field: str) -> list:
    turns = []
    previous_ts = None
    previous_state = None
    for row in sorted(rows, key=lambda item: ensure_utc(item.asof_ts)):
        ts = ensure_utc(row.asof_ts)
        state = _state(getattr(row, field))
        contiguous = previous_ts is not None and ts - previous_ts == SAMPLE_INTERVAL
        if state is not None and previous_state is not None and contiguous and state != previous_state:
            turns.append(ts)
        if state is None or not contiguous:
            previous_state = state
        else:
            previous_state = state
        previous_ts = ts
    return turns


def _pair_turns(candidate_turns: Sequence, reference_turns: Sequence) -> list[int]:
    max_delta = SAMPLE_INTERVAL * MAX_TURN_MATCH_LAG_SAMPLES
    unused = set(range(len(reference_turns)))
    deltas: list[int] = []
    for candidate_ts in candidate_turns:
        eligible = [
            index
            for index in unused
            if abs(reference_turns[index] - candidate_ts) <= max_delta
        ]
        if not eligible:
            continue
        best = min(
            eligible,
            key=lambda index: (
                abs(reference_turns[index] - candidate_ts),
                reference_turns[index],
            ),
        )
        unused.remove(best)
        delta = candidate_ts - reference_turns[best]
        deltas.append(int(delta.total_seconds() // SAMPLE_INTERVAL.total_seconds()))
    return deltas


def lead_lag_vs_b1(rows: Sequence[ValidationRow]) -> LeadLagResult:
    candidate_ids = {row.candidate_id for row in rows}
    if len(candidate_ids) > 1:
        raise ValueError("lead_lag_vs_b1 requires one candidate_id")
    by_asset: dict[int, list[ValidationRow]] = {}
    for row in rows:
        by_asset.setdefault(row.asset_id, []).append(row)

    candidate_turn_count = 0
    reference_turn_count = 0
    deltas: list[int] = []
    for asset_rows in by_asset.values():
        candidate_turns = _turns(asset_rows, field="candidate_score")
        reference_turns = _turns(asset_rows, field="b1_return")
        candidate_turn_count += len(candidate_turns)
        reference_turn_count += len(reference_turns)
        deltas.extend(_pair_turns(candidate_turns, reference_turns))

    paired = len(deltas)
    return LeadLagResult(
        candidate_turn_count=candidate_turn_count,
        reference_turn_count=reference_turn_count,
        paired_turn_count=paired,
        unmatched_candidate_turn_count=candidate_turn_count - paired,
        unmatched_reference_turn_count=reference_turn_count - paired,
        mean_delta_samples=(mean(deltas) if deltas else None),
        median_delta_samples=_median(deltas),
        min_delta_samples=(min(deltas) if deltas else None),
        max_delta_samples=(max(deltas) if deltas else None),
    )


def all_candidate_lead_lag(rows: Sequence[ValidationRow]) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for candidate_id in CANDIDATE_IDS:
        candidate_rows = [row for row in rows if row.candidate_id == candidate_id]
        output[candidate_id] = asdict(lead_lag_vs_b1(candidate_rows))
    return output


def regime_stability(rows: Sequence[ValidationRow]) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for candidate_id in CANDIDATE_IDS:
        candidate_rows = [row for row in rows if row.candidate_id == candidate_id]
        states = sorted({row.b0_pressure_state for row in candidate_rows if row.b0_pressure_state is not None})
        candidate_output: dict[str, object] = {}
        for state in states:
            group = [row for row in candidate_rows if row.b0_pressure_state == state]
            sample_count = len(group)
            complete_count = sum(row.candidate_score is not None for row in group)
            coverage = complete_count / sample_count if sample_count else 0.0
            if sample_count < MIN_REGIME_SAMPLE_COUNT:
                candidate_output[str(state)] = {
                    "status": "INSUFFICIENT_DATA",
                    "sample_count": sample_count,
                    "complete_count": complete_count,
                    "coverage": coverage,
                    "forward_ic": None,
                }
                continue
            forward_ic = {
                label: asdict(
                    correlation_with_fisher_ci(
                        [row.candidate_score for row in group],
                        [getattr(row, field) for row in group],
                    )
                )
                for label, field in FORWARD_FIELDS.items()
            }
            candidate_output[str(state)] = {
                "status": "MEASURED",
                "sample_count": sample_count,
                "complete_count": complete_count,
                "coverage": coverage,
                "forward_ic": forward_ic,
            }
        output[candidate_id] = candidate_output
    return output
