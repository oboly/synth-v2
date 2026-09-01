from __future__ import annotations

"""Bounded-memory evaluator core for Issue #593.

This module preserves the frozen validation semantics while consuming the
canonical dataset-builder JSONL in nondecreasing as-of order. Memory is bounded
by per-market temporal state, lead/lag turn indexes, regime aggregates, and one
as-of cohort rather than total row count.
"""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from math import atanh, erf, exp, isfinite, sqrt
from statistics import mean
from typing import Any, Iterable

from src.research.multi_horizon_rotation_validation_temporal_v1 import (
    MAX_TURN_MATCH_LAG_SAMPLES,
    MIN_REGIME_SAMPLE_COUNT,
)
from src.research.multi_horizon_rotation_validation_v1 import (
    CANDIDATE_IDS,
    CI_Z,
    FORWARD_FIELDS,
    SAMPLE_INTERVAL,
    CorrelationResult,
    holm_bonferroni,
)


@dataclass
class PairStats:
    n: int = 0
    sx: float = 0.0
    sy: float = 0.0
    sxx: float = 0.0
    syy: float = 0.0
    sxy: float = 0.0

    def add(self, x: float | None, y: float | None) -> None:
        if x is None or y is None or not isfinite(x) or not isfinite(y):
            return
        x = float(x)
        y = float(y)
        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x * x
        self.syy += y * y
        self.sxy += x * y

    def centered(self) -> tuple[float, float, float]:
        if self.n == 0:
            return 0.0, 0.0, 0.0
        n = float(self.n)
        return (
            self.sxx - self.sx * self.sx / n,
            self.syy - self.sy * self.sy / n,
            self.sxy - self.sx * self.sy / n,
        )

    def correlation(self) -> float | None:
        if self.n < 4:
            return None
        sxx, syy, sxy = self.centered()
        if sxx <= 0.0 or syy <= 0.0:
            return None
        value = sxy / sqrt(sxx * syy)
        return max(-1.0, min(1.0, value))


@dataclass
class TripleStats:
    n: int = 0
    sx: float = 0.0
    sy: float = 0.0
    sz: float = 0.0
    sxx: float = 0.0
    syy: float = 0.0
    szz: float = 0.0
    sxy: float = 0.0
    sxz: float = 0.0
    syz: float = 0.0

    def add(self, x: float | None, y: float | None, z: float | None) -> None:
        if x is None or y is None or z is None:
            return
        if not all(isfinite(float(value)) for value in (x, y, z)):
            return
        x = float(x)
        y = float(y)
        z = float(z)
        self.n += 1
        self.sx += x
        self.sy += y
        self.sz += z
        self.sxx += x * x
        self.syy += y * y
        self.szz += z * z
        self.sxy += x * y
        self.sxz += x * z
        self.syz += y * z

    def partial_correlation(self) -> float | None:
        if self.n <= 4:
            return None
        n = float(self.n)
        xx = self.sxx - self.sx * self.sx / n
        yy = self.syy - self.sy * self.sy / n
        zz = self.szz - self.sz * self.sz / n
        xy = self.sxy - self.sx * self.sy / n
        xz = self.sxz - self.sx * self.sz / n
        yz = self.syz - self.sy * self.sz / n
        if zz <= 0.0:
            return None
        xx_res = xx - (xz * xz / zz)
        yy_res = yy - (yz * yz / zz)
        xy_res = xy - (xz * yz / zz)
        if xx_res <= 0.0 or yy_res <= 0.0:
            return None
        value = xy_res / sqrt(xx_res * yy_res)
        return max(-1.0, min(1.0, value))


def correlation_result(sample_count: int, correlation: float | None, *, controlled_variables: int = 0) -> CorrelationResult:
    if correlation is None or sample_count <= controlled_variables + 3:
        return CorrelationResult(sample_count, None, None, None, None)
    clipped = max(-0.999999999999, min(0.999999999999, correlation))
    z = atanh(clipped)
    effective_n = sample_count - controlled_variables - 3
    se = 1.0 / sqrt(effective_n)
    lo_z = z - CI_Z * se
    hi_z = z + CI_Z * se
    lo = (exp(2 * lo_z) - 1) / (exp(2 * lo_z) + 1)
    hi = (exp(2 * hi_z) - 1) / (exp(2 * hi_z) + 1)
    z_null = abs(z) * sqrt(effective_n)
    p_approx = 2.0 * (1.0 - 0.5 * (1.0 + erf(z_null / sqrt(2.0))))
    return CorrelationResult(sample_count, correlation, lo, hi, max(0.0, min(1.0, p_approx)))


def pair_result(stats: PairStats) -> CorrelationResult:
    return correlation_result(stats.n, stats.correlation())


def triple_result(stats: TripleStats) -> CorrelationResult:
    return correlation_result(stats.n, stats.partial_correlation(), controlled_variables=1)


def _state(value: float | None) -> int | None:
    if value is None or not isfinite(value):
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


@dataclass
class PendingFlip:
    previous_state: int
    remaining: int


@dataclass
class MarketTemporalState:
    previous_ts: datetime | None = None
    current_state: int | None = None
    run_length: int = 0
    previous_candidate_state: int | None = None
    previous_b1_state: int | None = None
    pending_flips: list[PendingFlip] | None = None

    def __post_init__(self) -> None:
        if self.pending_flips is None:
            self.pending_flips = []


class StreamingValidationAccumulator:
    def __init__(self) -> None:
        self.sample_count = Counter({candidate: 0 for candidate in CANDIDATE_IDS})
        self.complete_count = Counter({candidate: 0 for candidate in CANDIDATE_IDS})
        self.vs_b0 = {candidate: PairStats() for candidate in CANDIDATE_IDS}
        self.vs_b1 = {candidate: PairStats() for candidate in CANDIDATE_IDS}
        self.forward = {
            candidate: {label: PairStats() for label in FORWARD_FIELDS}
            for candidate in CANDIDATE_IDS
        }
        self.partial_b0 = {
            candidate: {label: TripleStats() for label in FORWARD_FIELDS}
            for candidate in CANDIDATE_IDS
        }
        self.partial_b1 = {
            candidate: {label: TripleStats() for label in FORWARD_FIELDS}
            for candidate in CANDIDATE_IDS
        }
        self.cross = {
            "C1:C2": PairStats(),
            "C1:C3": PairStats(),
            "C2:C3": PairStats(),
        }
        self.regimes: dict[str, dict[str, dict[str, Any]]] = {
            candidate: {} for candidate in CANDIDATE_IDS
        }
        self.temporal: dict[tuple[str, int, str], MarketTemporalState] = {}
        self.run_length_counts: dict[str, Counter[int]] = {
            candidate: Counter() for candidate in CANDIDATE_IDS
        }
        self.sign_flips = Counter({candidate: 0 for candidate in CANDIDATE_IDS})
        self.chop_reversions = Counter({candidate: 0 for candidate in CANDIDATE_IDS})
        self.candidate_turns: dict[tuple[str, int, str], list[int]] = defaultdict(list)
        self.reference_turns: dict[tuple[str, int, str], list[int]] = defaultdict(list)
        self.current_asof: datetime | None = None
        self.current_cross: dict[tuple[str, int], dict[str, float | None]] = {}
        self.asof_index = -1

    def _flush_cross(self) -> None:
        for values in self.current_cross.values():
            self.cross["C1:C2"].add(values.get("C1"), values.get("C2"))
            self.cross["C1:C3"].add(values.get("C1"), values.get("C3"))
            self.cross["C2:C3"].add(values.get("C2"), values.get("C3"))
        self.current_cross.clear()

    def add(self, row: Any) -> None:
        candidate = row.candidate_id
        if candidate not in CANDIDATE_IDS:
            raise ValueError(f"unknown candidate id: {candidate}")
        ts = row.asof_ts
        if self.current_asof is None:
            self.current_asof = ts
            self.asof_index = 0
        elif ts < self.current_asof:
            raise ValueError("streaming evaluator requires nondecreasing canonical asof ordering")
        elif ts != self.current_asof:
            self._flush_cross()
            self.current_asof = ts
            self.asof_index += 1

        market = (row.venue, row.asset_id)
        candidate_values = self.current_cross.setdefault(market, {})
        if candidate in candidate_values:
            raise ValueError("duplicate validation row identity within asof cohort")
        candidate_values[candidate] = row.candidate_score

        self.sample_count[candidate] += 1
        if row.candidate_score is not None and isfinite(row.candidate_score):
            self.complete_count[candidate] += 1
        self.vs_b0[candidate].add(row.candidate_score, row.b0_score)
        self.vs_b1[candidate].add(row.candidate_score, row.b1_return)
        for label, field in FORWARD_FIELDS.items():
            outcome = getattr(row, field)
            self.forward[candidate][label].add(row.candidate_score, outcome)
            self.partial_b0[candidate][label].add(row.candidate_score, outcome, row.b0_score)
            self.partial_b1[candidate][label].add(row.candidate_score, outcome, row.b1_return)

        if row.b0_pressure_state is not None:
            state = str(row.b0_pressure_state)
            bucket = self.regimes[candidate].setdefault(
                state,
                {
                    "sample_count": 0,
                    "complete_count": 0,
                    "forward": {label: PairStats() for label in FORWARD_FIELDS},
                },
            )
            bucket["sample_count"] += 1
            if row.candidate_score is not None and isfinite(row.candidate_score):
                bucket["complete_count"] += 1
            for label, field in FORWARD_FIELDS.items():
                bucket["forward"][label].add(row.candidate_score, getattr(row, field))

        key = (row.venue, row.asset_id, candidate)
        tracker = self.temporal.setdefault(key, MarketTemporalState())
        contiguous = tracker.previous_ts is not None and ts - tracker.previous_ts == SAMPLE_INTERVAL
        state = _state(row.candidate_score)
        b1_state = _state(row.b1_return)

        if not contiguous:
            if tracker.run_length:
                self.run_length_counts[candidate][tracker.run_length] += 1
            tracker.current_state = None
            tracker.run_length = 0
            tracker.pending_flips.clear()
            tracker.previous_candidate_state = None
            tracker.previous_b1_state = None

        if state is None:
            if tracker.run_length:
                self.run_length_counts[candidate][tracker.run_length] += 1
            tracker.current_state = None
            tracker.run_length = 0
            tracker.pending_flips.clear()
        else:
            for pending in list(tracker.pending_flips):
                if state == pending.previous_state:
                    self.chop_reversions[candidate] += 1
                    tracker.pending_flips.remove(pending)
                else:
                    pending.remaining -= 1
                    if pending.remaining <= 0:
                        tracker.pending_flips.remove(pending)

            if tracker.current_state is None:
                tracker.current_state = state
                tracker.run_length = 1
            elif state == tracker.current_state:
                tracker.run_length += 1
            else:
                self.run_length_counts[candidate][tracker.run_length] += 1
                self.sign_flips[candidate] += 1
                tracker.pending_flips.append(PendingFlip(tracker.current_state, 4))
                tracker.current_state = state
                tracker.run_length = 1

        if contiguous and state is not None and tracker.previous_candidate_state is not None and state != tracker.previous_candidate_state:
            self.candidate_turns[key].append(self.asof_index)
        if contiguous and b1_state is not None and tracker.previous_b1_state is not None and b1_state != tracker.previous_b1_state:
            self.reference_turns[key].append(self.asof_index)

        tracker.previous_candidate_state = state
        tracker.previous_b1_state = b1_state
        tracker.previous_ts = ts

    def finish(self) -> dict[str, object]:
        self._flush_cross()
        for (venue, asset_id, candidate), tracker in self.temporal.items():
            _ = venue, asset_id
            if tracker.run_length:
                self.run_length_counts[candidate][tracker.run_length] += 1
                tracker.run_length = 0

        candidate_summaries: dict[str, object] = {}
        family_p_values: dict[str, float | None] = {}
        for candidate in CANDIDATE_IDS:
            sample_count = self.sample_count[candidate]
            complete_count = self.complete_count[candidate]
            forward_ic = {label: pair_result(stats) for label, stats in self.forward[candidate].items()}
            incremental_b0 = {label: triple_result(stats) for label, stats in self.partial_b0[candidate].items()}
            incremental_b1 = {label: triple_result(stats) for label, stats in self.partial_b1[candidate].items()}
            for label, result in forward_ic.items():
                family_p_values[f"{candidate}:{label}"] = result.p_value_approx
            candidate_summaries[candidate] = {
                "sample_count": sample_count,
                "complete_count": complete_count,
                "coverage": complete_count / sample_count if sample_count else 0.0,
                "correlation_vs_b0": pair_result(self.vs_b0[candidate]),
                "correlation_vs_b1": pair_result(self.vs_b1[candidate]),
                "forward_ic": forward_ic,
                "incremental_vs_b0": incremental_b0,
                "incremental_vs_b1": incremental_b1,
                "persistence": self._persistence(candidate),
                "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
            }

        return {
            "candidate_summaries": candidate_summaries,
            "cross_horizon_correlation": {key: pair_result(stats) for key, stats in self.cross.items()},
            "holm_bonferroni_family": holm_bonferroni(family_p_values),
            "holm_family_size": len(family_p_values),
            "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
            "lead_lag_vs_b1": self._lead_lag(),
            "regime_stability": self._regime_stability(),
        }

    def _persistence(self, candidate: str) -> dict[str, object]:
        counts = self.run_length_counts[candidate]
        run_count = sum(counts.values())
        total = sum(length * count for length, count in counts.items())
        median = None
        if run_count:
            left_rank = (run_count - 1) // 2
            right_rank = run_count // 2
            seen = 0
            left = right = None
            for length in sorted(counts):
                next_seen = seen + counts[length]
                if left is None and left_rank < next_seen:
                    left = length
                if right is None and right_rank < next_seen:
                    right = length
                    break
                seen = next_seen
            median = (float(left) + float(right)) / 2.0
        flips = self.sign_flips[candidate]
        chop = self.chop_reversions[candidate]
        return {
            "run_count": run_count,
            "mean_run_samples": total / run_count if run_count else None,
            "median_run_samples": median,
            "max_run_samples": max(counts) if counts else None,
            "sign_flip_count": flips,
            "chop_reversion_count": chop,
            "chop_rate": chop / flips if flips else None,
        }

    @staticmethod
    def _pair_turns(candidate_turns: list[int], reference_turns: list[int]) -> list[int]:
        unused = set(range(len(reference_turns)))
        deltas: list[int] = []
        for candidate_index in candidate_turns:
            eligible = [
                index for index in unused
                if abs(reference_turns[index] - candidate_index) <= MAX_TURN_MATCH_LAG_SAMPLES
            ]
            if not eligible:
                continue
            best = min(
                eligible,
                key=lambda index: (
                    abs(reference_turns[index] - candidate_index),
                    reference_turns[index],
                ),
            )
            unused.remove(best)
            deltas.append(candidate_index - reference_turns[best])
        return deltas

    def _lead_lag(self) -> dict[str, dict[str, object]]:
        output: dict[str, dict[str, object]] = {}
        for candidate in CANDIDATE_IDS:
            candidate_count = 0
            reference_count = 0
            deltas: list[int] = []
            keys = {key for key in self.temporal if key[2] == candidate}
            for key in keys:
                candidate_turns = self.candidate_turns.get(key, [])
                reference_turns = self.reference_turns.get(key, [])
                candidate_count += len(candidate_turns)
                reference_count += len(reference_turns)
                deltas.extend(self._pair_turns(candidate_turns, reference_turns))
            paired = len(deltas)
            ordered = sorted(deltas)
            median = None
            if ordered:
                mid = len(ordered) // 2
                median = float(ordered[mid]) if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
            output[candidate] = {
                "candidate_turn_count": candidate_count,
                "reference_turn_count": reference_count,
                "paired_turn_count": paired,
                "unmatched_candidate_turn_count": candidate_count - paired,
                "unmatched_reference_turn_count": reference_count - paired,
                "mean_delta_samples": mean(deltas) if deltas else None,
                "median_delta_samples": median,
                "min_delta_samples": min(deltas) if deltas else None,
                "max_delta_samples": max(deltas) if deltas else None,
            }
        return output

    def _regime_stability(self) -> dict[str, dict[str, object]]:
        output: dict[str, dict[str, object]] = {}
        for candidate in CANDIDATE_IDS:
            candidate_output: dict[str, object] = {}
            for state in sorted(self.regimes[candidate]):
                bucket = self.regimes[candidate][state]
                sample_count = int(bucket["sample_count"])
                complete_count = int(bucket["complete_count"])
                coverage = complete_count / sample_count if sample_count else 0.0
                if sample_count < MIN_REGIME_SAMPLE_COUNT:
                    candidate_output[state] = {
                        "status": "INSUFFICIENT_DATA",
                        "sample_count": sample_count,
                        "complete_count": complete_count,
                        "coverage": coverage,
                        "forward_ic": None,
                    }
                else:
                    candidate_output[state] = {
                        "status": "MEASURED",
                        "sample_count": sample_count,
                        "complete_count": complete_count,
                        "coverage": coverage,
                        "forward_ic": {
                            label: asdict(pair_result(stats))
                            for label, stats in bucket["forward"].items()
                        },
                    }
            output[candidate] = candidate_output
        return output


def serializable_streaming_summary(accumulator: StreamingValidationAccumulator) -> dict[str, object]:
    def convert(value: object) -> object:
        if hasattr(value, "__dataclass_fields__"):
            return {key: convert(item) for key, item in asdict(value).items()}
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        return value

    result = convert(accumulator.finish())
    assert isinstance(result, dict)
    return result
