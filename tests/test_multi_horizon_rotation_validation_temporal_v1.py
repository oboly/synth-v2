from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.research.multi_horizon_rotation_validation_temporal_v1 import (
    MAX_TURN_MATCH_LAG_SAMPLES,
    lead_lag_vs_b1,
    regime_stability,
)
from src.research.multi_horizon_rotation_validation_v1 import ValidationRow


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _row(
    index: int,
    *,
    candidate: float | None,
    b1: float | None,
    candidate_id: str = "C1",
    asset_id: int = 1,
    regime: str = "ROTATION_IN",
    venue: str = "bitvavo",
) -> ValidationRow:
    return ValidationRow(
        venue=venue,
        asset_id=asset_id,
        asof_ts=BASE + timedelta(minutes=15 * index),
        candidate_id=candidate_id,
        candidate_score=candidate,
        b0_score=10.0,
        b0_pressure_state=regime,
        b1_return=b1,
        forward_15m=(None if candidate is None else candidate / 100.0),
        forward_1h=(None if candidate is None else candidate / 90.0),
        forward_4h=(None if candidate is None else candidate / 80.0),
        forward_24h=(None if candidate is None else candidate / 70.0),
    )


def test_lead_lag_negative_delta_means_candidate_leads_b1() -> None:
    rows = [
        _row(0, candidate=-1, b1=-1),
        _row(1, candidate=1, b1=-1),
        _row(2, candidate=1, b1=-1),
        _row(3, candidate=1, b1=1),
    ]
    result = lead_lag_vs_b1(rows)
    assert result.candidate_turn_count == 1
    assert result.reference_turn_count == 1
    assert result.paired_turn_count == 1
    assert result.mean_delta_samples == -2.0
    assert result.median_delta_samples == -2.0


def test_lead_lag_missing_sample_breaks_turn_chain() -> None:
    rows = [
        _row(0, candidate=-1, b1=-1),
        _row(1, candidate=None, b1=-1),
        _row(2, candidate=1, b1=1),
    ]
    result = lead_lag_vs_b1(rows)
    assert result.candidate_turn_count == 0
    assert result.paired_turn_count == 0


def test_lead_lag_does_not_mix_same_asset_across_venues() -> None:
    rows = [
        _row(0, candidate=-1, b1=-1, venue="bitvavo"),
        _row(1, candidate=1, b1=1, venue="bitvavo"),
        _row(0, candidate=1, b1=1, venue="other"),
        _row(1, candidate=-1, b1=-1, venue="other"),
    ]
    result = lead_lag_vs_b1(rows)
    assert result.candidate_turn_count == 2
    assert result.reference_turn_count == 2
    assert result.paired_turn_count == 2
    assert result.mean_delta_samples == 0.0


def test_lead_lag_does_not_pair_turns_beyond_frozen_four_hour_window() -> None:
    rows = []
    for index in range(MAX_TURN_MATCH_LAG_SAMPLES + 3):
        candidate = -1 if index == 0 else 1
        b1 = -1 if index <= MAX_TURN_MATCH_LAG_SAMPLES + 1 else 1
        rows.append(_row(index, candidate=candidate, b1=b1))
    result = lead_lag_vs_b1(rows)
    assert result.candidate_turn_count == 1
    assert result.reference_turn_count == 1
    assert result.paired_turn_count == 0


def test_regime_stability_fails_closed_below_thirty_rows() -> None:
    rows = [_row(index, candidate=float(index + 1), b1=0.01) for index in range(29)]
    result = regime_stability(rows)
    state = result["C1"]["ROTATION_IN"]
    assert state["status"] == "INSUFFICIENT_DATA"
    assert state["sample_count"] == 29
    assert state["forward_ic"] is None


def test_regime_stability_measures_frozen_forward_ic_at_thirty_rows() -> None:
    rows = [_row(index, candidate=float(index + 1), b1=0.01) for index in range(30)]
    result = regime_stability(rows)
    state = result["C1"]["ROTATION_IN"]
    assert state["status"] == "MEASURED"
    assert state["sample_count"] == 30
    assert state["coverage"] == 1.0
    forward_ic = state["forward_ic"]
    assert isinstance(forward_ic, dict)
    assert set(forward_ic) == {"15m", "1h", "4h", "24h"}
