from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.research.bullish_breathline_tracker_v1 import (
    HALF_PHASE_SPLIT_CANDIDATE_DAYS,
    NORMAL_PHASE_OFFSETS_DAYS,
    CandleObservation,
    ConfirmedPivot,
    append_cycle_ledger,
    calibrate_checkpoint_grid,
    detect_confirmed_pivots,
    extract_bullish_cycles,
    walk_forward_checkpoint_evidence,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def pivot(kind: str, day: int, price: float) -> ConfirmedPivot:
    ts = BASE + timedelta(days=day)
    return ConfirmedPivot(
        kind=kind,
        pivot_ts=ts,
        confirmed_at_ts=ts + timedelta(days=1),
        price=price,
        source_index=day,
    )


def add_cycle(rows: list[ConfirmedPivot], start_day: int, base_price: float) -> None:
    rows.extend(
        [
            pivot("LOW", start_day, base_price),
            pivot("HIGH", start_day + 5, base_price + 20),
            pivot("LOW", start_day + 8, base_price + 8),
            pivot("HIGH", start_day + 11, base_price + 22),
            pivot("LOW", start_day + 13, base_price + 12),
            pivot("HIGH", start_day + 16, base_price + 25),
            pivot("LOW", start_day + 17, base_price + 15),
            pivot("HIGH", start_day + 20, base_price + 30),
            pivot("LOW", start_day + 21, base_price + 18),
            pivot("HIGH", start_day + 25, base_price + 40),
            # Keep the old extension line alive without accidentally making the
            # low at +21 a new five-pivot bullish recognition sequence.
            pivot("HIGH", start_day + 26, base_price + 39),
        ]
    )


def candles(days: int = 150) -> list[CandleObservation]:
    return [
        CandleObservation(
            ts=BASE + timedelta(days=day),
            open=100 + day,
            high=102 + day,
            low=98 + day,
            close=101 + day,
            volume=1000 + day * 10,
        )
        for day in range(days)
    ]


def test_half_phase_split_is_not_normal_offset() -> None:
    assert HALF_PHASE_SPLIT_CANDIDATE_DAYS not in NORMAL_PHASE_OFFSETS_DAYS
    assert -HALF_PHASE_SPLIT_CANDIDATE_DAYS not in NORMAL_PHASE_OFFSETS_DAYS


def test_pivots_are_confirmed_after_pivot_timestamp() -> None:
    rows = [
        CandleObservation(BASE + timedelta(days=0), 10, 11, 9, 10),
        CandleObservation(BASE + timedelta(days=1), 10, 12, 9, 11),
        CandleObservation(BASE + timedelta(days=2), 11, 20, 10, 15),
        CandleObservation(BASE + timedelta(days=3), 15, 16, 11, 12),
        CandleObservation(BASE + timedelta(days=4), 12, 15, 10, 11),
    ]
    detected = detect_confirmed_pivots(rows, left_bars=2, right_bars=2)
    high = next(item for item in detected if item.kind == "HIGH")
    assert high.pivot_ts == BASE + timedelta(days=2)
    assert high.confirmed_at_ts == BASE + timedelta(days=4)
    assert high.confirmed_at_ts > high.pivot_ts


def test_continuous_cycles_use_observed_transitions_not_21_day_reset() -> None:
    pivots: list[ConfirmedPivot] = []
    starts = [0, 32, 67, 103]
    for index, start in enumerate(starts):
        add_cycle(pivots, start, 100 + index * 50)
    result = extract_bullish_cycles("RENDER", candles(), pivots)

    assert len(result) == 4
    assert [int((cycle.start_ts - BASE).days) for cycle in result] == starts
    assert all(cycle.higher_low_confirmed for cycle in result)
    assert all(cycle.main_pulse_confirmed for cycle in result)
    assert all(cycle.extension_confirmed for cycle in result)
    assert all(cycle.extension_runner_state == "ACTIVE" for cycle in result)
    assert result[1].previous_cycle_id == result[0].cycle_id
    assert result[0].expected_node_ts["main_pulse"].endswith("Z")
    assert result[0].feature_as_of_ts <= result[0].outcome_as_of_ts


def test_ratio_selection_uses_discovery_then_reports_holdout_and_walk_forward() -> None:
    pivots: list[ConfirmedPivot] = []
    for index, start in enumerate([0, 32, 67, 103, 137]):
        add_cycle(pivots, start, 100 + index * 50)
    result = extract_bullish_cycles("TAO", candles(190), pivots)

    calibration = calibrate_checkpoint_grid(
        result,
        "recognition",
        discovery_fraction=0.6,
        min_discovery_matches=2,
    )
    assert calibration.selected_ratio == pytest.approx(0.618)
    assert calibration.discovery_cycle_ids
    assert calibration.holdout_cycle_ids
    assert set(calibration.discovery_cycle_ids).isdisjoint(calibration.holdout_cycle_ids)
    assert calibration.holdout_continuation_probability == pytest.approx(1.0)

    wf = walk_forward_checkpoint_evidence(result, "recognition", min_train_cycles=3)
    assert len(wf) == 2
    assert wf[0]["test_cycle_id"] == result[3].cycle_id


def test_append_only_ledger_is_idempotent_and_conflict_safe(tmp_path) -> None:
    pivots: list[ConfirmedPivot] = []
    add_cycle(pivots, 0, 100)
    result = extract_bullish_cycles("RENDER", candles(50), pivots)
    path = tmp_path / "cycle_ledger.jsonl"

    assert append_cycle_ledger(path, result) == 1
    assert append_cycle_ledger(path, result) == 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["cycle_id"] == result[0].cycle_id

    rows[0]["cycle_status"] = "MUTATED_HISTORY"
    path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="append-only ledger conflict"):
        append_cycle_ledger(path, result)
