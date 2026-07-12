from __future__ import annotations

from datetime import datetime

import pytest

from src.research.run_market_rotation_pressure_v1 import (
    MarketAggregate,
    PressureObservation,
    RotationPair,
    acceleration_factor,
    build_market_aggregate,
    build_pressure_observations,
    centered_percentile_scores,
    classify_phase_state,
    classify_pressure_state,
    compute_persistence_score,
    raw_direction_pressure,
    signed_volume_factor,
    zero_centered_robust_scores,
)


AS_OF = datetime(2026, 7, 12, 17, 0, 0)


def _pair(
    asset_id: int,
    market: str,
    r24: float,
    rv24: float,
    r7: float,
    rv7: float,
) -> RotationPair:
    return RotationPair(
        asset_id=asset_id,
        market=market,
        source_snapshot_24h_id=100 + asset_id,
        source_snapshot_7d_id=200 + asset_id,
        return_24h_pct=r24,
        relative_volume_24h=rv24,
        return_7d_pct=r7,
        relative_volume_7d=rv7,
    )


def _obs(
    asset_id: int,
    score: float,
    score24: float | None = None,
    score7: float | None = None,
    persistence: float = 0.0,
) -> PressureObservation:
    score24 = score if score24 is None else score24
    score7 = score if score7 is None else score7
    return PressureObservation(
        asset_id=asset_id,
        market=f"C{asset_id}-EUR",
        source_snapshot_24h_id=100 + asset_id,
        source_snapshot_7d_id=200 + asset_id,
        as_of_ts_utc=AS_OF,
        raw_return_24h_pct=score / 10,
        raw_relative_volume_24h=1.5,
        raw_return_7d_pct=score / 5,
        raw_relative_volume_7d=1.2,
        raw_acceleration_pct=0.0,
        raw_market_relative_pct=0.0,
        score_return_24h=score24,
        score_signed_volume_24h=score,
        score_return_7d=score7,
        score_signed_volume_7d=score,
        score_acceleration=score,
        score_market_relative=score,
        score_persistence=persistence,
        score_total=score,
        pressure_state=classify_pressure_state(score),
        phase_state="MIXED",
    )


def test_centered_percentile_scores_empty():
    assert centered_percentile_scores([]) == []


def test_centered_percentile_scores_single_is_neutral():
    assert centered_percentile_scores([9.0]) == [0.0]


def test_centered_percentile_scores_ordered_range():
    assert centered_percentile_scores([1.0, 2.0, 3.0]) == [-100.0, 0.0, 100.0]


def test_centered_percentile_scores_ties_use_midrank():
    assert centered_percentile_scores([1.0, 1.0, 3.0]) == [-50.0, -50.0, 100.0]


def test_centered_percentile_scores_all_equal_are_neutral():
    assert centered_percentile_scores([2.0, 2.0, 2.0]) == [0.0, 0.0, 0.0]


def test_centered_percentile_rejects_non_finite():
    with pytest.raises(ValueError, match="non-finite"):
        centered_percentile_scores([1.0, float("nan")])


def test_zero_centered_robust_scores_preserve_direction():
    scores = zero_centered_robust_scores([-4.0, -1.0, 0.0, 1.0, 4.0], floor_scale=1.0)
    assert scores[0] < scores[1] < 0
    assert scores[2] == 0.0
    assert 0 < scores[3] < scores[4]


def test_zero_centered_robust_scores_all_positive_stay_positive():
    scores = zero_centered_robust_scores([0.5, 1.0, 2.0], floor_scale=1.0)
    assert all(score > 0 for score in scores)


def test_zero_centered_robust_scores_reject_invalid_floor():
    with pytest.raises(ValueError, match="floor_scale"):
        zero_centered_robust_scores([1.0], floor_scale=0.0)


def test_signed_volume_positive_move_high_volume():
    assert signed_volume_factor(3.0, 2.0) > 0


def test_signed_volume_negative_move_high_volume():
    assert signed_volume_factor(-3.0, 2.0) < 0


def test_signed_volume_sub_baseline_is_zero():
    assert signed_volume_factor(3.0, 0.8) == 0.0


def test_signed_volume_flat_price_is_zero():
    assert signed_volume_factor(0.0, 2.0) == 0.0


def test_signed_volume_caps_extreme_relative_volume():
    assert signed_volume_factor(2.0, 100.0) == signed_volume_factor(2.0, 4.0)


def test_signed_volume_rejects_non_positive_volume():
    with pytest.raises(ValueError, match="> 0"):
        signed_volume_factor(1.0, 0.0)


def test_acceleration_compares_24h_to_7d_daily_pace():
    assert acceleration_factor(4.0, 7.0) == 3.0


def test_raw_direction_pressure_weights_short_horizon_more():
    assert raw_direction_pressure(5.0, -7.0) > 0


def test_persistence_all_matching_is_positive_100():
    history = [(3.0, 8.0), (2.0, 6.0), (1.0, 2.0)]
    assert compute_persistence_score(4.0, 10.0, history) == 100.0


def test_persistence_all_opposite_is_negative_100():
    history = [(-3.0, -8.0), (-2.0, -6.0)]
    assert compute_persistence_score(4.0, 10.0, history) == -100.0


def test_persistence_without_history_is_neutral():
    assert compute_persistence_score(4.0, 10.0, []) == 0.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (61.0, "STRONG_ROTATION_IN"),
        (30.0, "ROTATION_IN"),
        (0.0, "NEUTRAL_OR_MIXED"),
        (-30.0, "ROTATION_OUT"),
        (-61.0, "STRONG_ROTATION_OUT"),
    ],
)
def test_pressure_state_thresholds(score: float, expected: str):
    assert classify_pressure_state(score) == expected


def test_phase_early_reversal_in():
    assert classify_phase_state(
        score_total=45,
        return_24h_pct=4,
        return_7d_pct=-3,
        score_acceleration=20,
        score_signed_volume_24h=30,
        score_persistence=0,
    ) == "EARLY_REVERSAL_IN"


def test_phase_distribution_risk():
    assert classify_phase_state(
        score_total=-45,
        return_24h_pct=-4,
        return_7d_pct=8,
        score_acceleration=-20,
        score_signed_volume_24h=-50,
        score_persistence=0,
    ) == "DISTRIBUTION_RISK"


def test_build_pressure_observations_ranks_best_and_worst():
    pairs = [
        _pair(1, "GOOD-EUR", 8.0, 2.5, 20.0, 1.8),
        _pair(2, "MID-EUR", 1.0, 1.1, 2.0, 1.0),
        _pair(3, "BAD-EUR", -8.0, 2.5, -20.0, 1.8),
    ]
    history = {
        1: [(4.0, 10.0)] * 4,
        2: [(0.5, 1.0)] * 4,
        3: [(-4.0, -10.0)] * 4,
    }
    observations = build_pressure_observations(pairs, history, AS_OF)
    by_market = {obs.market: obs for obs in observations}
    assert by_market["GOOD-EUR"].score_total > by_market["MID-EUR"].score_total
    assert by_market["MID-EUR"].score_total > by_market["BAD-EUR"].score_total
    assert by_market["GOOD-EUR"].pressure_state == "STRONG_ROTATION_IN"
    assert by_market["BAD-EUR"].pressure_state == "STRONG_ROTATION_OUT"


def test_build_pressure_observations_is_order_stable():
    pairs = [
        _pair(1, "A-EUR", 8.0, 2.5, 20.0, 1.8),
        _pair(2, "B-EUR", 1.0, 1.1, 2.0, 1.0),
        _pair(3, "C-EUR", -8.0, 2.5, -20.0, 1.8),
    ]
    forward = build_pressure_observations(pairs, {}, AS_OF)
    reverse = build_pressure_observations(list(reversed(pairs)), {}, AS_OF)
    assert {o.asset_id: o.score_total for o in forward} == {o.asset_id: o.score_total for o in reverse}


def test_build_market_aggregate_empty():
    aggregate = build_market_aggregate([], None)
    assert aggregate == MarketAggregate(
        market_direction="MIXED",
        market_score=0.0,
        positive_count=0,
        neutral_count=0,
        negative_count=0,
        positive_breadth_ratio=0.0,
        negative_breadth_ratio=0.0,
        acceleration_state="UNKNOWN",
        concentration_state="UNKNOWN",
        confirmation_state="MIXED",
        evidence_light_count=0,
    )


def test_build_market_aggregate_detects_rotation_in():
    observations = [
        _obs(1, 80, persistence=80),
        _obs(2, 70, persistence=60),
        _obs(3, 55, persistence=40),
        _obs(4, 40, persistence=30),
        _obs(5, 10, persistence=10),
        _obs(6, -5, persistence=0),
    ]
    aggregate = build_market_aggregate(observations, prior_market_score=10)
    assert aggregate.market_direction == "ROTATION_IN"
    assert aggregate.positive_count == 4
    assert aggregate.negative_count == 0
    assert aggregate.acceleration_state == "ACCELERATING_IN"
    assert 0 <= aggregate.evidence_light_count <= 5


def test_build_market_aggregate_detects_rotation_out():
    observations = [
        _obs(1, -80, persistence=-80),
        _obs(2, -70, persistence=-60),
        _obs(3, -55, persistence=-40),
        _obs(4, -40, persistence=-30),
        _obs(5, -10, persistence=-10),
        _obs(6, 5, persistence=0),
    ]
    aggregate = build_market_aggregate(observations, prior_market_score=-10)
    assert aggregate.market_direction == "ROTATION_OUT"
    assert aggregate.negative_count == 4
    assert aggregate.acceleration_state == "ACCELERATING_OUT"


def test_build_market_aggregate_mixed_has_no_lights():
    observations = [_obs(1, 20), _obs(2, 10), _obs(3, -10), _obs(4, -20)]
    aggregate = build_market_aggregate(observations, prior_market_score=0)
    assert aggregate.market_direction == "MIXED"
    assert aggregate.evidence_light_count == 0


def test_all_positive_market_does_not_get_cross_sectionally_flattened():
    pairs = [
        _pair(1, "A-EUR", 1.0, 1.4, 4.0, 1.2),
        _pair(2, "B-EUR", 2.0, 1.8, 8.0, 1.5),
        _pair(3, "C-EUR", 4.0, 2.2, 12.0, 1.8),
        _pair(4, "D-EUR", 6.0, 2.5, 18.0, 2.0),
    ]
    observations = build_pressure_observations(pairs, {}, AS_OF)
    aggregate = build_market_aggregate(observations, prior_market_score=None)
    assert all(obs.score_total > 0 for obs in observations)
    assert aggregate.market_score > 0
    assert aggregate.market_direction == "ROTATION_IN"


def test_all_negative_market_does_not_get_cross_sectionally_flattened():
    pairs = [
        _pair(1, "A-EUR", -1.0, 1.4, -4.0, 1.2),
        _pair(2, "B-EUR", -2.0, 1.8, -8.0, 1.5),
        _pair(3, "C-EUR", -4.0, 2.2, -12.0, 1.8),
        _pair(4, "D-EUR", -6.0, 2.5, -18.0, 2.0),
    ]
    observations = build_pressure_observations(pairs, {}, AS_OF)
    aggregate = build_market_aggregate(observations, prior_market_score=None)
    assert all(obs.score_total < 0 for obs in observations)
    assert aggregate.market_score < 0
    assert aggregate.market_direction == "ROTATION_OUT"
