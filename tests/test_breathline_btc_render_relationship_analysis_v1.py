from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.research.breathline_btc_alt_relationship_registry_v1 import (
    ALPHA,
    DISCOVERY_FRACTION,
    MIN_BINARY_CLASS_COUNT,
    MIN_BINARY_ROWS_PER_SPLIT,
    NULL_PERMUTATIONS,
    RANDOM_SEED,
    REGISTRY_VERSION,
)
from src.research.run_breathline_btc_render_relationship_analysis_v1 import (
    best_btc_pair,
    binary_support,
    build_lane_b_rows,
    build_pair_rows,
    holm_adjust,
    phase_stat_from_vectors,
    permute_btc_vectors,
    realized_phase,
    roc_auc,
    split_render_cycles,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def cycle(
    symbol: str,
    idx: int,
    *,
    start_day: float,
    end_day: float,
    recognition_day: float | None = None,
    ignition_day: float | None = None,
    main_day: float | None = None,
    extension_day: float | None = None,
    recognition_confirm_day: float | None = None,
    ignition_confirm_day: float | None = None,
    main_confirm_day: float | None = None,
    extension_confirm_day: float | None = None,
    outcome_as_of_day: float | None = None,
    main_confirmed: bool | None = None,
    extension_confirmed: bool | None = None,
) -> dict[str, object]:
    def ts(day: float | None) -> str | None:
        return None if day is None else iso(BASE + timedelta(days=day))

    if recognition_day is None:
        recognition_day = start_day + (end_day - start_day) * 0.5
    if recognition_confirm_day is None:
        recognition_confirm_day = recognition_day
    if outcome_as_of_day is None:
        outcome_as_of_day = end_day
    if main_confirmed is None:
        main_confirmed = main_day is not None
    if extension_confirmed is None:
        extension_confirmed = extension_day is not None

    return {
        "cycle_id": f"{symbol}-{idx}",
        "symbol": symbol,
        "start_ts": ts(start_day),
        "end_ts": ts(end_day),
        "recognition_ts": ts(recognition_day),
        "ignition_ts": ts(ignition_day),
        "main_pulse_ts": ts(main_day),
        "extension_ts": ts(extension_day),
        "recognition_confirmed_at_ts": ts(recognition_confirm_day),
        "ignition_confirmed_at_ts": ts(ignition_confirm_day),
        "main_pulse_confirmed_at_ts": ts(main_confirm_day),
        "extension_confirmed_at_ts": ts(extension_confirm_day),
        "main_pulse_confirmed": main_confirmed,
        "extension_confirmed": extension_confirmed,
        "outcome_as_of_ts": ts(outcome_as_of_day),
    }


def test_registry_v102_is_frozen_before_relationship_outcomes() -> None:
    assert REGISTRY_VERSION == "1.0.2"
    assert DISCOVERY_FRACTION == 0.70
    assert NULL_PERMUTATIONS == 2000
    assert RANDOM_SEED == 418001
    assert ALPHA == 0.05
    assert MIN_BINARY_ROWS_PER_SPLIT >= 2 * MIN_BINARY_CLASS_COUNT


def test_chronological_render_split_is_exact_70_30() -> None:
    rows = [cycle("RENDER", idx, start_day=idx * 2, end_day=idx * 2 + 1) for idx in range(10)]
    split = split_render_cycles(rows)
    assert [split[f"RENDER-{idx}"] for idx in range(10)] == [
        "discovery",
        "discovery",
        "discovery",
        "discovery",
        "discovery",
        "discovery",
        "discovery",
        "holdout",
        "holdout",
        "holdout",
    ]


def test_pairing_uses_maximum_overlap_and_zero_overlap_is_not_forced() -> None:
    render = cycle("RENDER", 1, start_day=10, end_day=20)
    btc_small = cycle("BTC", 1, start_day=9, end_day=12)
    btc_large = cycle("BTC", 2, start_day=11, end_day=19)
    btc_none = cycle("BTC", 3, start_day=30, end_day=40)
    assert best_btc_pair(render, [btc_small, btc_large, btc_none])["cycle_id"] == "BTC-2"

    isolated = cycle("RENDER", 2, start_day=50, end_day=55)
    assert best_btc_pair(isolated, [btc_small, btc_large, btc_none]) is None


def test_pairing_tie_break_prefers_smallest_start_lag_then_earliest_btc_start() -> None:
    render = cycle("RENDER", 1, start_day=10, end_day=20)
    # Both overlap 8d; BTC-1 start lag=2d, BTC-2 start lag=1d.
    btc1 = cycle("BTC", 1, start_day=8, end_day=18)
    btc2 = cycle("BTC", 2, start_day=9, end_day=17)
    assert best_btc_pair(render, [btc1, btc2])["cycle_id"] == "BTC-2"


def test_realized_phase_is_unwrapped_and_requires_timestamp_inside_cycle() -> None:
    row = cycle("BTC", 1, start_day=0, end_day=10)
    assert realized_phase(row, BASE + timedelta(days=2.5)) == 0.25
    assert realized_phase(row, BASE + timedelta(days=12)) is None


def test_phase_delta_uses_common_wall_clock_without_modulo_wrapping() -> None:
    render = cycle(
        "RENDER",
        1,
        start_day=0,
        end_day=10,
        recognition_day=8,
        ignition_day=9,
    )
    btc = cycle(
        "BTC",
        1,
        start_day=-10,
        end_day=10,
        recognition_day=-2,
        ignition_day=0,
    )
    split = {"RENDER-1": "holdout"}
    pairs, phases, _, _ = build_pair_rows([btc], [render], split)
    recognition = next(row for row in phases if row["checkpoint"] == "recognition")
    # At day 8: RENDER phase=.8, BTC phase=.9, signed delta=-.1.
    assert round(recognition["signed_phase_delta"], 9) == -0.1
    assert round(recognition["absolute_phase_delta"], 9) == 0.1
    assert pairs[0]["phase_support_pattern"] == ["recognition", "ignition"]


def test_pair_null_permutation_preserves_support_pattern_and_row_count() -> None:
    rows = [
        {
            "render_phase_vector": {"recognition": 0.6, "ignition": 0.8},
            "btc_phase_vector": {"recognition": 0.4, "ignition": 0.7},
            "phase_support_pattern": ["recognition", "ignition"],
        },
        {
            "render_phase_vector": {"recognition": 0.5, "ignition": 0.9},
            "btc_phase_vector": {"recognition": 0.2, "ignition": 0.6},
            "phase_support_pattern": ["recognition", "ignition"],
        },
        {
            "render_phase_vector": {"recognition": 0.7},
            "btc_phase_vector": {"recognition": 0.3},
            "phase_support_pattern": ["recognition"],
        },
    ]
    import random

    before_patterns = [tuple(row["phase_support_pattern"]) for row in rows]
    before_count = len(rows)
    permuted = permute_btc_vectors(rows, random.Random(123))
    assert len(permuted) == before_count
    assert [tuple(row["phase_support_pattern"]) for row in permuted] == before_patterns
    for row in permuted:
        assert tuple(row["btc_phase_vector"].keys()) == tuple(row["phase_support_pattern"])
    assert phase_stat_from_vectors(permuted) is not None


def test_tie_aware_auc() -> None:
    assert roc_auc([1.0, 1.0], [True, False]) == 0.5
    assert roc_auc([2.0, 1.0, 0.0], [True, False, False]) == 1.0
    assert roc_auc([0.0, 1.0], [True, False]) == 0.0


def test_holm_adjustment_is_monotone_and_familywise() -> None:
    adjusted = holm_adjust({"a": 0.01, "b": 0.02, "c": 0.20, "missing": None})
    assert adjusted["a"] == 0.03
    assert adjusted["b"] == 0.04
    assert adjusted["c"] == 0.20
    assert adjusted["missing"] is None


def test_binary_support_requires_both_classes() -> None:
    assert binary_support([True] * MIN_BINARY_ROWS_PER_SPLIT) is False
    labels = [True] * MIN_BINARY_CLASS_COUNT + [False] * (MIN_BINARY_ROWS_PER_SPLIT - MIN_BINARY_CLASS_COUNT)
    assert binary_support(labels) is True


def test_lane_b_ignores_future_btc_confirmations_for_earlier_checkpoint() -> None:
    btc_past = cycle(
        "BTC",
        1,
        start_day=0,
        end_day=5,
        main_day=2,
        main_confirm_day=2.5,
        extension_day=3,
        extension_confirm_day=3.5,
    )
    btc_future = cycle(
        "BTC",
        2,
        start_day=20,
        end_day=25,
        main_day=22,
        main_confirm_day=22.5,
        extension_day=23,
        extension_confirm_day=23.5,
    )
    render = cycle(
        "RENDER",
        1,
        start_day=5,
        end_day=15,
        recognition_day=8,
        recognition_confirm_day=8.5,
        ignition_day=9,
        ignition_confirm_day=9.5,
        main_day=11,
        main_confirm_day=11.5,
        outcome_as_of_day=15,
    )
    split = {"RENDER-1": "holdout"}
    before = build_lane_b_rows([btc_past], [render], split)
    after = build_lane_b_rows([btc_past, btc_future], [render], split)
    assert [row["btc_main_pulse_recency_score"] for row in before] == [
        row["btc_main_pulse_recency_score"] for row in after
    ]
    assert [row["btc_extension_recency_score"] for row in before] == [
        row["btc_extension_recency_score"] for row in after
    ]


def test_no_btc_prior_uses_only_outcomes_available_before_checkpoint() -> None:
    prior_cycles = []
    for idx in range(8):
        prior_cycles.append(
            cycle(
                "RENDER",
                idx,
                start_day=idx,
                end_day=idx + 0.5,
                recognition_day=idx + 0.2,
                outcome_as_of_day=idx + 0.5,
                main_confirmed=idx % 2 == 0,
                extension_confirmed=False,
            )
        )
    current = cycle(
        "RENDER",
        99,
        start_day=10,
        end_day=12,
        recognition_day=10.2,
        recognition_confirm_day=10.3,
        outcome_as_of_day=12,
        main_confirmed=True,
        extension_confirmed=False,
    )
    future_known_late = cycle(
        "RENDER",
        100,
        start_day=9,
        end_day=20,
        recognition_day=9.2,
        recognition_confirm_day=9.3,
        outcome_as_of_day=20,
        main_confirmed=True,
        extension_confirmed=True,
    )
    all_render = prior_cycles + [future_known_late, current]
    split = {str(row["cycle_id"]): "holdout" for row in all_render}
    rows = build_lane_b_rows([], all_render, split)
    current_row = next(row for row in rows if row["render_cycle_id"] == "RENDER-99" and row["checkpoint"] == "recognition")
    assert current_row["no_btc_prior_main_pulse_confirmed_count"] == 8
    assert current_row["no_btc_prior_main_pulse_confirmed"] == 0.5
