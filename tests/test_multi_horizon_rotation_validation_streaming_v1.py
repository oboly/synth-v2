from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.research.multi_horizon_rotation_validation_streaming_v1 import (
    StreamingValidationAccumulator,
    serializable_streaming_summary,
)
from src.research.multi_horizon_rotation_validation_temporal_v1 import (
    all_candidate_lead_lag,
    regime_stability,
)
from src.research.multi_horizon_rotation_validation_v1 import (
    ValidationRow,
    serializable_validation_summary,
)


def _rows() -> list[ValidationRow]:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    rows: list[ValidationRow] = []
    candidate_scale = {"C1": 1.0, "C2": 0.7, "C3": 0.4}
    for sample in range(40):
        ts = start + timedelta(minutes=15 * sample)
        for candidate in ("C1", "C2", "C3"):
            scale = candidate_scale[candidate]
            for asset_id in (1, 2, 3):
                sign = -1.0 if ((sample // 3) + asset_id) % 2 else 1.0
                candidate_score = sign * scale * (1.0 + sample / 50.0)
                if candidate == "C3" and sample % 11 == 0:
                    candidate_score = None
                b1 = sign * (0.02 + sample / 10000.0)
                b0 = sign * (20.0 + asset_id)
                forward = None if sample >= 38 else sign * (0.005 + asset_id / 1000.0)
                rows.append(
                    ValidationRow(
                        venue="bitvavo",
                        asset_id=asset_id,
                        asof_ts=ts,
                        candidate_id=candidate,
                        candidate_score=candidate_score,
                        b0_score=b0,
                        b0_pressure_state="ROTATION_IN" if sign > 0 else "ROTATION_OUT",
                        b1_return=b1,
                        forward_15m=forward,
                        forward_1h=forward,
                        forward_4h=forward,
                        forward_24h=forward,
                    )
                )
    return rows


def _reference(rows: list[ValidationRow]) -> dict[str, object]:
    output = serializable_validation_summary(rows)
    output["lead_lag_vs_b1"] = all_candidate_lead_lag(rows)
    output["regime_stability"] = regime_stability(rows)
    return output


def _assert_equivalent(actual: object, expected: object, *, path: str = "root") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert set(actual) == set(expected), path
        for key in expected:
            _assert_equivalent(actual[key], expected[key], path=f"{path}.{key}")
        return
    if isinstance(expected, list):
        assert isinstance(actual, list), path
        assert len(actual) == len(expected), path
        for index, value in enumerate(expected):
            _assert_equivalent(actual[index], value, path=f"{path}[{index}]")
        return
    if isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-10, abs=1e-12), path
        return
    assert actual == expected, path


def _summary(rows: list[ValidationRow]) -> dict[str, object]:
    accumulator = StreamingValidationAccumulator()
    for row in rows:
        accumulator.add(row)
    return serializable_streaming_summary(accumulator)


def test_streaming_summary_matches_frozen_in_memory_semantics() -> None:
    rows = _rows()
    _assert_equivalent(_summary(rows), _reference(rows))


def test_streaming_summary_matches_sparse_global_asof_semantics() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    rows: list[ValidationRow] = []
    samples = (0, 1, 2, 4, 5)
    candidate_values = {0: 1.0, 1: 1.0, 2: -1.0, 4: -1.0, 5: -1.0}
    b1_values = {0: 1.0, 1: 1.0, 2: 1.0, 4: 1.0, 5: -1.0}
    for sample in samples:
        ts = start + timedelta(minutes=15 * sample)
        for candidate in ("C1", "C2", "C3"):
            rows.append(
                ValidationRow(
                    venue="bitvavo",
                    asset_id=1,
                    asof_ts=ts,
                    candidate_id=candidate,
                    candidate_score=candidate_values[sample],
                    b0_score=10.0,
                    b0_pressure_state="ROTATION_IN",
                    b1_return=b1_values[sample],
                    forward_15m=0.01,
                    forward_1h=0.01,
                    forward_4h=0.01,
                    forward_24h=0.01,
                )
            )
    actual = _summary(rows)
    expected = _reference(rows)
    _assert_equivalent(actual, expected)
    for candidate in ("C1", "C2", "C3"):
        assert actual["lead_lag_vs_b1"][candidate]["mean_delta_samples"] == -3.0


def test_lead_lag_pairing_state_stays_bounded_on_alternating_input() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    accumulator = StreamingValidationAccumulator()
    for sample in range(500):
        ts = start + timedelta(minutes=15 * sample)
        sign = 1.0 if sample % 2 == 0 else -1.0
        for candidate in ("C1", "C2", "C3"):
            accumulator.add(
                ValidationRow(
                    venue="bitvavo",
                    asset_id=1,
                    asof_ts=ts,
                    candidate_id=candidate,
                    candidate_score=sign,
                    b0_score=sign,
                    b0_pressure_state="ROTATION_IN" if sign > 0 else "ROTATION_OUT",
                    b1_return=-sign,
                    forward_15m=sign * 0.01,
                    forward_1h=sign * 0.01,
                    forward_4h=sign * 0.01,
                    forward_24h=sign * 0.01,
                )
            )
    accumulator.finish()
    for pairer in accumulator.lead_lag.values():
        assert len(pairer.pending_candidates) == 0
        assert len(pairer.references) == 0
        assert len(pairer.delta_counts) <= 33


def test_streaming_accumulator_rejects_asof_reversal() -> None:
    rows = _rows()
    accumulator = StreamingValidationAccumulator()
    accumulator.add(rows[9])
    with pytest.raises(ValueError, match="nondecreasing canonical asof ordering"):
        accumulator.add(rows[0])
