from __future__ import annotations

from datetime import UTC, datetime, timedelta
import random

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

    recognition_day = recognition_day if recognition_day is not None else start_day + (end_day - start_day) * 0.5
    recognition_confirm_day = recognition_confirm_day if recognition_confirm_day is not None else recognition_day
    outcome_as_of_day = outcome_as_of_day if outcome_as_of_day is not None else end_day
    main_confirmed = main_confirmed if main_confirmed is not None else main_day is not None
    extension_confirmed = extension_confirmed if extension_confirmed is not None else extension_day is not None
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


def test_registry_v102_is_frozen() -> None:
    assert REGISTRY_VERSION == "1.0.2"
    assert DISCOVERY_FRACTION == 0.70
    assert NULL_PERMUTATIONS == 2000
    assert RANDOM_SEED == 418001
    assert ALPHA == 0.05
    assert MIN_BINARY_ROWS_PER_SPLIT >= 2 * MIN_BINARY_CLASS_COUNT


def test_chronological_render_split_is_exact_70_30() -> None:
    rows = [cycle("RENDER", idx, start_day=idx * 2, end_day=idx * 2 + 1) for idx in range(10)]
    split = split_render_cycles(rows)
    assert [split[f"RENDER-{idx}"] for idx in range(10)] == ["discovery"] * 7 + ["holdout"] * 3


def test_pairing_uses_maximum_overlap_and_zero_overlap_is_not_forced() -> None:
    render = cycle("RENDER", 1, start_day=10, end_day=20)
    btc_small = cycle("BTC", 1, start_day=9, end_day=12)
    btc_large = cycle("BTC", 2, start_day=11, end_day=19)
    btc_none = cycle("BTC", 3, start_day=30, end_day=40)
    assert best_btc_pair(render, [btc_small, btc_large, btc_none])["cycle_id"] == "BTC-2"
    assert best_btc_pair(cycle("RENDER", 2, start_day=50, end_day=55), [btc_small, btc_large, btc_none]) is None


def test_pairing_tie_break_prefers_smallest_start_lag() -> None:
    render = cycle("RENDER", 1, start_day=10, end_day=20)
    # Equal 8d overlap. BTC-2 has smaller absolute start lag.
    btc1 = cycle("BTC", 1, start_day=8, end_day=18)
    btc2 = cycle("BTC", 2, start_day=9, end_day=18)
    assert best_btc_pair(render, [btc1, btc2])["cycle_id"] == "BTC-2"


def test_realized_phase_is_unwrapped_and_requires_inside_cycle() -> None:
    row = cycle("BTC", 1, start_day=0, end_day=10)
    assert realized_phase(row, BASE + timedelta(days=2.5)) == 0.25
    assert realized_phase(row, BASE + timedelta(days=12)) is None


def test_phase_delta_uses_common_wall_clock_without_modulo() -> None:
    render = cycle("RENDER", 1, start_day=0, end_day=10, recognition_day=8, ignition_day=9)
    btc = cycle("BTC", 1, start_day=-10, end_day=10, recognition_day=-2, ignition_day=0)
    pairs, phases, _, _ = build_pair_rows([btc], [render], {"RENDER-1": "holdout"})
    recognition = next(row for row in phases if row["checkpoint"] == "recognition")
    assert round(recognition["signed_phase_delta"], 9) == -0.1
    assert round(recognition["absolute_phase_delta"], 9) == 0.1
    assert pairs[0]["phase_support_pattern"] == ["recognition", "ignition"]


def test_pair_null_permutation_preserves_support_pattern() -> None:
    rows = [
        {"render_phase_vector": {"recognition": 0.6, "ignition": 0.8}, "btc_phase_vector": {"recognition": 0.4, "ignition": 0.7}, "phase_support_pattern": ["recognition", "ignition"]},
        {"render_phase_vector": {"recognition": 0.5, "ignition": 0.9}, "btc_phase_vector": {"recognition": 0.2, "ignition": 0.6}, "phase_support_pattern": ["recognition", "ignition"]},
        {"render_phase_vector": {"recognition": 0.7}, "btc_phase_vector": {"recognition": 0.3}, "phase_support_pattern": ["recognition"]},
    ]
    patterns = [tuple(row["phase_support_pattern"]) for row in rows]
    permuted = permute_btc_vectors(rows, random.Random(123))
    assert len(permuted) == len(rows)
    assert [tuple(row["phase_support_pattern"]) for row in permuted] == patterns
    for row in permuted:
        assert tuple(row["btc_phase_vector"].keys()) == tuple(row["phase_support_pattern"])
    assert phase_stat_from_vectors(permuted) is not None


def test_tie_aware_auc_and_holm() -> None:
    assert roc_auc([1.0, 1.0], [True, False]) == 0.5
    assert roc_auc([2.0, 1.0, 0.0], [True, False, False]) == 1.0
    assert roc_auc([0.0, 1.0], [True, False]) == 0.0
    adjusted = holm_adjust({"a": 0.01, "b": 0.02, "c": 0.20, "missing": None})
    assert adjusted == {"a": 0.03, "b": 0.04, "c": 0.20, "missing": None}


def test_binary_support_requires_both_classes() -> None:
    assert binary_support([True] * MIN_BINARY_ROWS_PER_SPLIT) is False
    labels = [True] * MIN_BINARY_CLASS_COUNT + [False] * (MIN_BINARY_ROWS_PER_SPLIT - MIN_BINARY_CLASS_COUNT)
    assert binary_support(labels) is True


def test_lane_b_ignores_future_btc_confirmations() -> None:
    btc_past = cycle("BTC", 1, start_day=0, end_day=5, main_day=2, main_confirm_day=2.5, extension_day=3, extension_confirm_day=3.5)
    btc_future = cycle("BTC", 2, start_day=20, end_day=25, main_day=22, main_confirm_day=22.5, extension_day=23, extension_confirm_day=23.5)
    render = cycle("RENDER", 1, start_day=5, end_day=15, recognition_day=8, recognition_confirm_day=8.5, ignition_day=9, ignition_confirm_day=9.5, main_day=11, main_confirm_day=11.5)
    split = {"RENDER-1": "holdout"}
    before = build_lane_b_rows([btc_past], [render], split)
    after = build_lane_b_rows([btc_past, btc_future], [render], split)
    assert [row["btc_main_pulse_recency_score"] for row in before] == [row["btc_main_pulse_recency_score"] for row in after]
    assert [row["btc_extension_recency_score"] for row in before] == [row["btc_extension_recency_score"] for row in after]


def test_no_btc_prior_uses_strictly_available_outcomes() -> None:
    prior = [
        cycle("RENDER", idx, start_day=idx, end_day=idx + 0.5, recognition_day=idx + 0.2, main_confirmed=idx % 2 == 0, extension_confirmed=False)
        for idx in range(8)
    ]
    current = cycle("RENDER", 99, start_day=10, end_day=12, recognition_day=10.2, recognition_confirm_day=10.3, main_confirmed=True, extension_confirmed=False)
    future_outcome = cycle("RENDER", 100, start_day=9, end_day=20, recognition_day=9.2, outcome_as_of_day=20, main_confirmed=True, extension_confirmed=True)
    rows_in = prior + [future_outcome, current]
    split = {str(row["cycle_id"]): "holdout" for row in rows_in}
    rows = build_lane_b_rows([], rows_in, split)
    current_row = next(row for row in rows if row["render_cycle_id"] == "RENDER-99" and row["checkpoint"] == "recognition")
    assert current_row["no_btc_prior_main_pulse_confirmed_count"] == 8
    assert current_row["no_btc_prior_main_pulse_confirmed"] == 0.5
